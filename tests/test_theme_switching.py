import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "src/shared/bin"

MOCK_COMMAND = """#!/bin/bash
name=${0##*/}
printf '%s %s\\n' "$name" "$*" >> "$CALL_LOG"
case "$name" in
  pgrep)
    [[ -n "${ST_PID:-}" ]] && { echo "$ST_PID"; exit 0; }
    [[ "$*" == *eww ]] && { echo 123; exit 0; }
    exit 1 ;;
  cp)
    [[ "${FAIL_COPY:-0}" == 1 ]] && exit 1
    exec /usr/bin/cp "$@" ;;
  bar-ctl) exit "${FAIL_RELOAD:-0}" ;;
  theme-set-st) exit "${FAIL_TERMINAL:-0}" ;;
  code|codium|cursor) exit 0 ;;
esac
"""

TERMINAL_CHILD = """
import os, pty, select, signal, sys, termios, time
name, paused = sys.argv[1:]
with open("/proc/self/comm", "w") as f:
    f.write(name)
signalled = []
signal.signal(signal.SIGUSR1, lambda *_: signalled.append(True))
master, slave = pty.openpty()
if paused == "True":
    termios.tcflow(slave, termios.TCOOFF)
print("ready", flush=True)
data = b""
deadline = time.monotonic() + 3
while time.monotonic() < deadline:
    if select.select([master], [], [], 0.05)[0]:
        data += os.read(master, 4096)
    if b"\\x1b]12;#d7c995\\x1b\\\\" in data and (name == "st" or signalled):
        break
print(data.hex(), flush=True)
print(bool(signalled), flush=True)
"""


class ThemeSwitchingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.stock = self.home / "stock/themes"
        self.current = self.home / ".config/smplos/current"
        self.current.mkdir(parents=True)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.log = self.home / "calls.log"
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "SMPLOS_PATH": str(self.stock.parent),
            "XDG_RUNTIME_DIR": str(self.home / "runtime"),
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "CALL_LOG": str(self.log),
            "WAYLAND_DISPLAY": "",
            "DISPLAY": "",
            "NIRI_SOCKET": "",
            "ST_PID": "",
        }
        for cmd in (
            "pgrep", "cp", "bar-ctl", "theme-bg-next", "theme-set-st", "fish",
            "gsettings", "hyprctl", "systemctl", "code", "codium", "cursor",
        ):
            path = self.bin / cmd
            path.write_text(MOCK_COMMAND)
            path.chmod(0o755)
        self.make_theme("old", "#000000")
        self.make_theme("new", "#111c18")

    def make_theme(self, name, background):
        theme = self.stock / name
        theme.mkdir(parents=True)
        colors = {
            "background": background, "bg_light": background, "surface": background,
            "foreground": "#c1c497", "fg_alt": "#c1c497", "accent": "#509475",
            "muted": "#555555", "cursor": "#d7c995", "color0": background,
        }
        (theme / "colors.toml").write_text(
            "".join(f'{key} = "{value}"\n' for key, value in colors.items())
        )
        (theme / "eww-colors.scss").write_text(f"$theme-bg: {background};\n")
        (theme / "nemo.css").write_text(f"window {{ background: {background}; }}\n")
        (theme / "vscode.json").write_text(json.dumps({"name": name}))
        (theme / ".hidden").write_text(name)
        return theme

    def switch(self, name, **env):
        return subprocess.run(
            ["bash", str(BIN / "theme-set"), name],
            env={**self.env, **env}, text=True, capture_output=True, timeout=15,
        )

    def assert_switched(self, name):
        self.assertEqual((self.current / "theme.name").read_text().strip(), name)
        for source, target in (
            ("colors.toml", self.current / "theme/colors.toml"),
            (".hidden", self.current / "theme/.hidden"),
            ("eww-colors.scss", self.home / ".config/eww/theme-colors.scss"),
            ("nemo.css", self.home / ".config/smplos/nemo-theme.css"),
        ):
            self.assertEqual(target.read_bytes(), (self.stock / name / source).read_bytes())
        settings = self.home / ".config/Code/User/settings.json"
        # VS Code accepts JSONC (including the trailing comma on a new settings file).
        self.assertIn(f'"workbench.colorTheme": "{name}"', settings.read_text())

    def test_switch_updates_all_consumers_and_keeps_editor_settings(self):
        settings = self.home / ".config/Code/User/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{\n// keep this comment\n"editor.fontSize": 15\n}\n')
        for name in ("old", "new", "old"):
            result = self.switch(name)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assert_switched(name)
        self.assertIn("// keep this comment", settings.read_text())
        self.assertIn('"editor.fontSize": 15', settings.read_text())
        calls = self.log.read_text()
        self.assertEqual(calls.count("bar-ctl reload\n"), 3)
        self.assertEqual(calls.count("theme-bg-next \n"), 3)
        self.assertEqual(calls.count("theme-set-st \n"), 3)
        self.assertEqual(list(self.current.glob(".theme-set.*")), [self.current / ".theme-set.lock"])

    @unittest.skipIf(os.geteuid() == 0, "requires unprivileged filesystem permissions")
    def test_unremovable_previous_theme_is_preserved_and_replaced(self):
        self.assertEqual(self.switch("old").returncode, 0)
        old = self.current / "theme"
        old.chmod(0o555)
        # A read-only directory reproduces the unlink failure of the root-owned
        # directory left by the updater, without requiring root to run the test.
        self.addCleanup(self.restore_directory_permissions)
        result = self.switch("new")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_switched("new")
        backups = list(self.current.glob(".theme-set.*.previous"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(
            (backups[0] / "colors.toml").read_bytes(),
            (self.stock / "old/colors.toml").read_bytes(),
        )
        self.assertIn("Preserved old theme", result.stderr)
        self.assertEqual(self.switch("old").returncode, 0)
        self.assert_switched("old")

    def restore_directory_permissions(self):
        for directory, _, _ in os.walk(self.home):
            Path(directory).chmod(0o755)

    def test_copy_failure_keeps_active_theme_and_does_not_reload_apps(self):
        self.assertEqual(self.switch("old").returncode, 0)
        calls = self.log.read_text()
        result = self.switch("new", FAIL_COPY="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Theme set to:", result.stdout)
        self.assert_switched("old")
        self.assertNotIn("bar-ctl", self.log.read_text()[len(calls):])

    def test_missing_palette_keeps_active_theme(self):
        self.assertEqual(self.switch("old").returncode, 0)
        (self.stock / "new/colors.toml").unlink()
        result = self.switch("new")
        self.assertNotEqual(result.returncode, 0)
        self.assert_switched("old")

    def test_palette_publication_replaces_inode_without_truncating_readers(self):
        self.assertEqual(self.switch("old").returncode, 0)
        for relative in ("eww/theme-colors.scss", "smplos/nemo-theme.css"):
            target = self.home / ".config" / relative
            with self.subTest(target=relative), target.open("rb") as reader:
                old = reader.read()
                reader.seek(0)
                self.assertEqual(self.switch("new").returncode, 0)
                self.assertEqual(reader.read(), old)
                self.assertNotEqual(target.read_bytes(), old)
            self.assertEqual(self.switch("old").returncode, 0)

    def test_reload_failure_is_not_reported_as_success(self):
        result = self.switch("new", FAIL_RELOAD="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot reload EWW theme", result.stderr)
        self.assertNotIn("Theme set to:", result.stdout)

    def test_terminal_failure_does_not_prevent_other_app_updates(self):
        result = self.switch("new", FAIL_TERMINAL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("terminal refresh failed", result.stderr)
        self.assertNotIn("Theme set to:", result.stdout)
        self.assert_switched("new")

    def test_bar_ctl_preserves_eww_reload_failure(self):
        eww = self.bin / "eww"
        eww.write_text("#!/bin/bash\nexit 42\n")
        eww.chmod(0o755)
        result = subprocess.run(
            ["bash", str(BIN / "bar-ctl"), "reload"],
            env=self.env, capture_output=True, timeout=5,
        )
        self.assertEqual(result.returncode, 42)

    def refresh_terminal(self, name, paused=False):
        child = subprocess.Popen(
            [sys.executable, "-c", TERMINAL_CHILD, name, str(paused)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            result = subprocess.run(
                ["bash", str(BIN / "theme-set-st")],
                env={**self.env, "ST_PID": str(child.pid)},
                text=True, capture_output=True, timeout=2.5,
            )
            output, errors = child.communicate(timeout=5)
            self.assertEqual(child.returncode, 0, errors)
            payload, signalled = output.splitlines()
            return result, bytes.fromhex(payload), signalled
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate()

    def test_terminal_refresh_uses_master_fdinfo_not_stdin(self):
        self.assertEqual(self.switch("new").returncode, 0)
        for name in ("st", "st-wl"):
            with self.subTest(terminal=name):
                result, payload, signalled = self.refresh_terminal(name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(b"\x1b]11;#111c18\x1b\\", payload)
                self.assertIn(b"\x1b]10;#c1c497\x1b\\", payload)
                self.assertEqual(signalled, str(name == "st-wl"))

    def test_paused_terminal_times_out_without_waiting_for_resume(self):
        self.assertEqual(self.switch("new").returncode, 0)
        result, payload, signalled = self.refresh_terminal("st-wl", paused=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Cannot update /dev/pts/", result.stderr)
        self.assertEqual(payload, b"")
        self.assertEqual(signalled, "False")

    def test_post_deploy_drops_privileges_without_retrying_failed_switch(self):
        source = (BIN / "smplos-os-update").read_text()
        function = source.split("post_deploy() {", 1)[1].split("# ── Main", 1)[0]
        script = """
sync_version() { :; }
theme-current() { echo new; }
log() { :; }
warn() { echo "$*"; }
restart_updated_apps() { :; }
smplos_have_session() { [[ "$HAVE_SESSION" == 1 ]]; }
smplos_run_as_user() { echo "session-user $*"; return "$SWITCH_STATUS"; }
as_invoker() { echo "invoker $*"; return "$SWITCH_STATUS"; }
hyprctl() { return 1; }
smplos_have_hyprland() { return 1; }
theme-set() { echo "BUG: elevated theme-set"; }
post_deploy() {
""" + function + "\npost_deploy\n"
        for session in ("0", "1"):
            for status in ("0", "1"):
                with self.subTest(session=session, status=status):
                    result = subprocess.run(
                        ["bash", "-c", script],
                        env={**self.env, "HAVE_SESSION": session, "SWITCH_STATUS": status},
                        text=True, capture_output=True, timeout=5,
                    )
                    runner = "session-user" if session == "1" else "invoker"
                    self.assertIn(f"{runner} theme-set new", result.stdout)
                    self.assertEqual(result.stdout.count("theme-set new"), 1)
                    self.assertNotIn("BUG:", result.stdout)


if __name__ == "__main__":
    unittest.main()
