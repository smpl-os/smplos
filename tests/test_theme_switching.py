import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from test_app_delivery import function


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
  theme-set-copilot) exit "${FAIL_COPILOT:-0}" ;;
  theme-set-openchamber) exit "${FAIL_OPENCHAMBER:-0}" ;;
  gsettings)
    key="$3"
    case "$1" in
      get)
        if [[ -f "$HOME/gsettings-$key" ]]; then
          cat "$HOME/gsettings-$key"
        else
          case "$key" in
            gtk-theme) echo "'Adwaita'" ;;
            icon-theme) echo "'Adwaita'" ;;
            color-scheme) echo "'default'" ;;
          esac
        fi ;;
      set)
        printf "'%s'\\n" "$4" > "$HOME/gsettings-$key" ;;
    esac ;;
  hyprctl)
    case "$1" in
      eval)
        if [[ "${2:-}" == assert* ]]; then
          case "${HYPR_PROVIDER:-lua}" in
            lua) echo ok ;;
            legacy) echo 'eval is only supported with the lua config manager' ;;
            *) echo 'unknown request'; exit 1 ;;
          esac
        else
          echo "${HYPR_ENV_REPLY:-ok}"
          exit "${HYPR_ENV_STATUS:-0}"
        fi ;;
      keyword)
        echo "${HYPR_ENV_REPLY:-ok}"
        exit "${HYPR_ENV_STATUS:-0}" ;;
      version) echo "Hyprland ${HYPR_VERSION:-0.54.3} built from fixture" ;;
    esac ;;
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
            "DBUS_SESSION_BUS_ADDRESS": "",
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_DATA_DIRS": str(self.home / "data"),
        }
        for cmd in (
            "pgrep", "cp", "bar-ctl", "theme-bg-next", "theme-set-st", "fish",
            "gsettings", "hyprctl", "systemctl", "dbus-update-activation-environment",
            "code", "codium", "cursor", "notify-send",
        ):
            path = self.bin / cmd
            path.write_text(MOCK_COMMAND)
            path.chmod(0o755)
        self.make_theme("old", "#000000")
        self.make_theme("new", "#111c18")
        icons = self.home / "data/icons/Adwaita"
        icons.mkdir(parents=True)
        (icons / "index.theme").write_text("[Icon Theme]\nName=Adwaita\n")

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

    def test_core_theme_skips_optional_editors_and_apps_phase_keeps_core_unchanged(self):
        (self.stock / "new/foot.ini").write_text("new foot colors\n")
        (self.stock / "new/btop.theme").write_text("new btop colors\n")
        core = subprocess.run(
            ["bash", str(BIN / "theme-set"), "--core", "new"],
            env=self.env, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(core.returncode, 0, core.stderr)
        palette = self.home / ".config/eww/theme-colors.scss"
        nemo = self.home / ".config/smplos/nemo-theme.css"
        before = (palette.read_bytes(), nemo.read_bytes(), (self.current / "theme.name").read_bytes())
        self.assertFalse((self.home / ".config/Code/User/settings.json").exists())
        self.assertFalse((self.home / ".config/foot/theme.ini").exists())
        self.assertFalse((self.home / ".config/btop/themes/current.theme").exists())
        apps = subprocess.run(
            ["bash", str(BIN / "theme-set"), "--apps"],
            env=self.env, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(apps.returncode, 0, apps.stderr)
        self.assertEqual(before, (palette.read_bytes(), nemo.read_bytes(),
                                  (self.current / "theme.name").read_bytes()))
        self.assert_switched("new")
        self.assertEqual((self.home / ".config/foot/theme.ini").read_text(), "new foot colors\n")
        self.assertEqual((self.home / ".config/btop/themes/current.theme").read_text(), "new btop colors\n")

    def test_failed_optional_theme_copy_is_visible_and_leaves_verified_core_unchanged(self):
        self.assertEqual(subprocess.run(
            ["bash", str(BIN / "theme-set"), "--core", "new"],
            env=self.env, capture_output=True, timeout=15,
        ).returncode, 0)
        (self.current / "theme/foot.ini").write_text("optional colors\n")
        palette = self.home / ".config/eww/theme-colors.scss"
        nemo = self.home / ".config/smplos/nemo-theme.css"
        before = (palette.read_bytes(), nemo.read_bytes())
        apps = subprocess.run(
            ["bash", str(BIN / "theme-set"), "--apps"],
            env={**self.env, "FAIL_COPY": "1"}, capture_output=True, timeout=15,
        )
        self.assertNotEqual(apps.returncode, 0)
        self.assertEqual(before, (palette.read_bytes(), nemo.read_bytes()))
        self.assertEqual((self.current / "theme.name").read_text().strip(), "new")

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

    def test_frosted_status_icons_use_glass_ink_and_switch_back(self):
        template = self.home / ".local/share/smplos/icons/status"
        template.mkdir(parents=True)
        (template / "test.svg").write_text('<svg fill="{{accent}}" stroke="{{fg}}"/>')
        frosted = self.make_theme("frosted", "#0b2230")
        with (frosted / "colors.toml").open("a") as file:
            file.write('glass = "true"\nglass_background = "#dce6f0"\n'
                       'glass_foreground = "#f4f8ff"\nglass_accent = "#d4e8fa"\n')
        icon = self.home / ".config/eww/icons/status/test.svg"
        for name, foreground, accent in (
            ("frosted", "#f4f8ff", "#d4e8fa"),
            ("old", "#c1c497", "#509475"),
        ):
            result = self.switch(name)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(icon.read_text(), f'<svg fill="{accent}" stroke="{foreground}"/>')

    def test_dark_frosted_switch_retires_old_light_marker_and_applies_dark_mode(self):
        shutil.copytree(ROOT / "src/shared/themes/frosted", self.stock / "frosted")
        old = self.current / "theme"
        old.mkdir()
        (old / "light.mode").touch()
        result = self.switch("frosted")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.current / "theme/light.mode").exists())
        self.assertEqual((self.current / "theme.name").read_text().strip(), "frosted")
        self.assertIn("gsettings set org.gnome.desktop.interface color-scheme prefer-dark",
                      self.log.read_text())
        self.assertFalse((self.home / ".config/environment.d/gtk.conf").exists())
        self.assertIn("gtk-application-prefer-dark-theme=1",
                      (self.home / ".config/gtk-4.0/settings.ini").read_text())
        self.assertIn("background = \"#0b2230\"", (self.current / "theme/colors.toml").read_text())

    def test_retired_logseq_data_never_changes_or_blocks_theme_switching(self):
        theme = self.stock / "new"
        (theme / "logseq-custom.css").write_text('body { color: "blue"; }\n')
        files = {
            self.home / ".logseq/preferences.json": '{broken but must remain untouched',
            self.home / ".logseq/config/config.edn":
                ';; personal config\n{:journals-directory "notes" :shortcuts {:x "a"}\n'
                ' :custom-css-url "my css"}\n',
            self.home / ".logseq/custom.css": "/* personal global CSS */\n",
            self.home / "graph/logseq/config.edn": '{:preferred-format :markdown}\n',
            self.home / "graph/logseq/custom.css": "/* personal graph CSS */\n",
        }
        for path, content in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        original_paths = set((self.home / ".logseq").rglob("*"))
        for name in ("new", "old", "new"):
            result = self.switch(name)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"Theme set to: {name}", result.stdout)
            for path, content in files.items():
                self.assertEqual(path.read_text(), content)
        self.assertEqual(set((self.home / ".logseq").rglob("*")), original_paths)
        self.assert_switched("new")

    def test_logseq_symlink_preferences_are_preserved(self):
        prefs = self.home / ".logseq/preferences.json"
        prefs.parent.mkdir()
        target = self.home / "personal.json"
        target.write_text('{"externals":["keep"]}')
        prefs.symlink_to(target)
        result = self.switch("new")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(prefs.is_symlink())
        self.assertEqual(target.read_text(), '{"externals":["keep"]}')
        self.assertNotIn("Logseq", result.stderr)

    def test_theme_switch_does_not_initialize_retired_logseq(self):
        (self.stock / "new/logseq-custom.css").write_text('body { content: "\\\\"; }\n')
        result = self.switch("new")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / ".logseq").exists())

    def test_openchamber_sync_runs_only_in_apps_stage_and_failure_is_nonfatal(self):
        helper = self.bin / "theme-set-openchamber"
        helper.write_text(MOCK_COMMAND)
        helper.chmod(0o755)
        core = subprocess.run(
            ["bash", str(BIN / "theme-set"), "--core", "new"],
            env=self.env, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(core.returncode, 0, core.stderr)
        self.assertNotIn("theme-set-openchamber", self.log.read_text())
        apps = subprocess.run(
            ["bash", str(BIN / "theme-set"), "--apps"],
            env={**self.env, "FAIL_OPENCHAMBER": "1"}, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(apps.returncode, 0, apps.stderr)
        self.assertIn("OpenChamber theme sync failed", apps.stderr)
        self.assertEqual(self.log.read_text().count("theme-set-openchamber \n"), 1)
        self.assert_switched("new")
        self.assertEqual(self.switch("old").returncode, 0)
        self.assertEqual(self.log.read_text().count("theme-set-openchamber \n"), 2)

    def test_copilot_sync_is_opt_in_and_failure_does_not_abort_theme_switch(self):
        helper = self.bin / "theme-set-copilot"
        helper.write_text(MOCK_COMMAND)
        helper.chmod(0o755)
        self.assertEqual(self.switch("old").returncode, 0)
        self.assertNotIn("theme-set-copilot", self.log.read_text())
        (self.home / ".config/smplos/copilot-theme-sync.enabled").touch()
        result = self.switch("new", FAIL_COPILOT="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Copilot theme sync failed", result.stderr)
        self.assertEqual(self.log.read_text().count("theme-set-copilot \n"), 1)
        self.assert_switched("new")

    def test_missing_opted_in_copilot_helper_warns_without_aborting(self):
        (self.home / ".config/smplos/copilot-theme-sync.enabled").touch()
        result = self.switch("new")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("theme-set-copilot is not installed", result.stderr)
        self.assert_switched("new")

    def test_bar_ctl_preserves_eww_reload_failure(self):
        eww = self.bin / "eww"
        eww.write_text("#!/bin/bash\nexit 42\n")
        eww.chmod(0o755)
        result = subprocess.run(
            ["bash", str(BIN / "bar-ctl"), "reload"],
            env={**self.env, "HYPRLAND_INSTANCE_SIGNATURE": ""}, capture_output=True, timeout=5,
        )
        self.assertEqual(result.returncode, 42)

    def test_same_palette_is_not_republished_and_failed_reload_releases_batch_lock(self):
        self.assertEqual(self.switch("new").returncode, 0)
        palette = self.home / ".config/eww/theme-colors.scss"
        before = palette.stat()
        self.assertEqual(self.switch("new").returncode, 0)
        after = palette.stat()
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))
        self.assertNotEqual(self.switch("old", FAIL_RELOAD="1").returncode, 0)
        with (self.home / ".config/eww/.smplos-reload.lock").open("r") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_hyprland_environment_uses_running_lua_or_legacy_provider_not_setenv(self):
        for provider in ("lua", "legacy", "old"):
            with self.subTest(provider=provider):
                self.log.write_text("")
                result = self.switch(
                    "new", WAYLAND_DISPLAY="wayland-test",
                    HYPRLAND_INSTANCE_SIGNATURE="fixture", HYPR_PROVIDER=provider,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = self.log.read_text()
                self.assertNotIn("hyprctl setenv ", calls)
                self.assertNotIn("unknown request", result.stdout + result.stderr)
                if provider == "lua":
                    self.assertIn("hyprctl eval hl.env('GTK_THEME', '')", calls)
                    self.assertNotIn("hyprctl keyword env", calls)
                else:
                    self.assertIn("hyprctl keyword env GTK_THEME,", calls)

    def test_hyprland_environment_rejects_unknown_apis_and_success_exit_with_error_reply(self):
        for extra in (
            {"HYPR_PROVIDER": "unknown", "HYPR_VERSION": "0.56.2"},
            {"HYPR_ENV_REPLY": "unknown request"},
            {"HYPR_ENV_STATUS": "1", "HYPR_ENV_REPLY": "connection refused"},
        ):
            with self.subTest(extra=extra):
                result = self.switch(
                    "new", WAYLAND_DISPLAY="wayland-test",
                    HYPRLAND_INSTANCE_SIGNATURE="fixture", **extra,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("theme-set:", result.stderr)
                self.assertNotIn("Theme set to:", result.stdout)

    def test_no_hyprland_environment_request_for_x11_or_other_wayland_compositors(self):
        for wayland, signature in (("", "stale"), ("niri-test", "")):
            self.log.write_text("")
            result = self.switch(
                "new", WAYLAND_DISPLAY=wayland, HYPRLAND_INSTANCE_SIGNATURE=signature,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = self.log.read_text()
            self.assertNotIn("hyprctl eval ", calls)
            self.assertNotIn("hyprctl keyword env ", calls)
            self.assertNotIn("hyprctl setenv ", calls)

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

    def test_exited_unreaped_terminal_has_no_pty_and_is_not_a_refresh_failure(self):
        self.assertEqual(self.switch("new").returncode, 0)
        child = subprocess.Popen(
            [sys.executable, "-c", 'open("/proc/self/comm", "w").write("st-wl")'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            status = Path(f"/proc/{child.pid}/status")
            deadline = time.monotonic() + 5
            while "\nState:\tZ " not in status.read_text() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIn("\nState:\tZ ", status.read_text())
            result = subprocess.run(
                ["bash", str(BIN / "theme-set-st")],
                env={**self.env, "ST_PID": str(child.pid)},
                text=True, capture_output=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Cannot find PTY", result.stderr)
        finally:
            child.wait(timeout=5)

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


class StockThemeSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.repo = self.base / "repo"
        self.source = self.repo / "src/shared/themes/amber"
        self.source.mkdir(parents=True)
        (self.source / "colors.toml").write_text('background = "#123456"\n')
        (self.source / "nemo.css").write_text("latest CSS\n")
        self.stock = self.home / ".local/share/smplos/themes/amber"
        self.override = self.home / ".config/smplos/themes/amber"
        self.backups = self.home / ".local/state/smplos/theme-backups"
        self.env = {**os.environ, "HOME": str(self.home),
                    "XDG_STATE_HOME": str(self.home / ".local/state"),
                    "SMPLOS_REPO": str(self.repo)}
        script = BIN / "smplos-os-update"
        self.script = "\n".join(function(script, name) for name in ("replace_theme_tree", "sync_themes"))
        self.script += """
die() { echo "$*" >&2; exit 1; }
header() { :; }; ok() { echo "$*"; }
THEMES_CHANGED=0
sync_themes
echo "changed=$THEMES_CHANGED"
"""

    def sync(self, prefix=""):
        return subprocess.run(["bash", "-c", prefix + self.script], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def seed(self, path, content="personal old theme"):
        path.mkdir(parents=True)
        (path / "colors.toml").write_text(content)
        (path / "obsolete.css").write_text("stale file must not survive replacement")

    def test_exact_replacement_and_verified_backups_include_matching_overrides(self):
        self.seed(self.stock, "old stock modifications")
        self.seed(self.override, "personal overrides")
        custom = self.override.parent / "my-personal-theme"
        self.seed(custom)
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for destination in (self.stock, self.override):
            self.assertEqual({p.name: p.read_bytes() for p in destination.iterdir()},
                             {p.name: p.read_bytes() for p in self.source.iterdir()})
        self.assertEqual((custom / "colors.toml").read_text(), "personal old theme")
        backups = {Path((p / "path").read_text().strip()): p for p in self.backups.iterdir()}
        self.assertEqual(set(backups), {self.stock, self.override})
        self.assertEqual((backups[self.stock] / "original/colors.toml").read_text(),
                         "old stock modifications")
        self.assertEqual((backups[self.override] / "original/colors.toml").read_text(), "personal overrides")
        self.assertTrue((backups[self.override] / "original/obsolete.css").is_file())
        self.assertIn("changed=1", result.stdout)
        second = self.sync()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("changed=0", second.stdout)
        self.assertEqual(len(list(self.backups.iterdir())), 2)
        self.assertEqual(list(self.stock.parent.glob(".*.update.*")), [])
        self.assertEqual(list(self.override.parent.glob(".*.update.*")), [])

    def test_backup_failure_never_replaces_personal_theme(self):
        self.seed(self.stock)
        result = self.sync('cp() { [[ "$*" != *"/original"* ]] || return 23; command cp "$@"; }\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot verify theme backup", result.stderr)
        self.assertEqual((self.stock / "colors.toml").read_text(), "personal old theme")

    def test_failed_publication_restores_old_tree_and_keeps_backup(self):
        self.seed(self.stock)
        prefix = """mv() {
if [[ "$2" == -- && "$3" == *".update."* && "$3" != *.previous && "$4" == *"/themes/amber" ]]; then
    return 24
fi
command mv "$@"
}
"""
        result = self.sync(prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("previous theme restored", result.stderr)
        self.assertEqual((self.stock / "colors.toml").read_text(), "personal old theme")
        self.assertTrue(next(self.backups.glob("*/original/obsolete.css")).is_file())

    def test_symlink_override_is_replaced_without_touching_its_target(self):
        custom = self.home / "my-original-theme"
        self.seed(custom)
        self.override.parent.mkdir(parents=True)
        self.override.symlink_to(custom, target_is_directory=True)
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.override.is_symlink())
        self.assertEqual((custom / "colors.toml").read_text(), "personal old theme")
        original = next(self.backups.glob("*/original"))
        self.assertTrue(original.is_symlink())
        self.assertEqual(original.readlink(), custom)


if __name__ == "__main__":
    unittest.main()
