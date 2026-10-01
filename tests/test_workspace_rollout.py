import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "src/shared/bin"
MIGRATION = ROOT / "migrations/20260929-195600-monitor-owned-workspaces.sh"
UPDATER = (BIN / "smplos-os-update").read_text()


def function(name):
    body = UPDATER.split(f"{name}() {{", 1)[1].split("\n}\n", 1)[0]
    return f"{name}() {{" + body + "\n}\n"


class WorkspaceRolloutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home with spaces"
        self.home.mkdir()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls"
        self.log.touch()
        self.env = {
            **os.environ, "HOME": str(self.home), "SMPLOS_REPO": str(self.repo),
            "PATH": f"{self.bin}:{os.environ['PATH']}", "TEST_LOG": str(self.log),
            "HYPRLAND_INSTANCE_SIGNATURE": "test-session", "NIRI_SOCKET": "",
            "HAVE_HYPRLAND": "yes", "HAVE_EWW": "yes", "FAIL_BAR": "0",
        }

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_bash(self, source, check=True):
        return subprocess.run(
            ["bash", "-c", source], env=self.env, text=True, capture_output=True,
            check=check, timeout=10,
        )

    def mocks(self):
        for name in ("workspace-ctl", "workspace-group", "hyprctl", "pgrep", "bar-ctl"):
            path = self.write(self.bin / name, """#!/bin/bash
printf '%s %s\\n' "${0##*/}" "$*" >> "$TEST_LOG"
case "${0##*/}" in
  pgrep) [[ "$HAVE_EWW" == yes ]] ;;
  bar-ctl) exit "$FAIL_BAR" ;;
esac
""")
            path.chmod(0o755)

    def config_sync_script(self):
        return r"""
set -euo pipefail
header() { :; }
log() { :; }
ok() { :; }
die() { echo "$*" >&2; exit 1; }
as_invoker() {
    if [[ "$1" == install && "${FAIL_FRAGMENT:-0}" == 1 && "$3" == */workspace-overview.yuck ]]; then
        return 1
    fi
    if [[ "$1" == mv ]]; then
        destination="${@: -1}"
        case "$destination" in
          */eww.yuck) [[ -f "$HOME/.config/eww/workspace-overview.yuck" ]] ;;
          */hyprland.lua)
            [[ -f "$HOME/.config/hypr/workspace_policy.lua" ]]
            [[ -f "$HOME/.config/hypr/apps/example.lua" ]] ;;
        esac
        printf '%s\n' "$destination" >> "$TEST_LOG"
    fi
    "$@"
}
""" + function("copy_user_config") + function("sync_configs") + function("sync_hypr_configs")

    def test_update_publishes_fragments_and_modules_before_entrypoints(self):
        self.write(self.repo / "src/shared/eww/workspace-overview.yuck", "(defwidget overview [] (label :text \"map\"))\n")
        self.write(self.repo / "src/shared/eww/eww.yuck", '(include "./workspace-overview.yuck")\n')
        self.write(self.repo / "src/shared/eww/eww.scss", ".bar { color: green; }\n")
        hypr = self.repo / "src/compositors/hyprland/hypr"
        self.write(hypr / "workspace_policy.lua", "return true\n")
        self.write(hypr / "hyprland.lua", 'require("workspace_policy")\n')
        self.write(hypr / "apps/example.lua", "-- app rules\n")
        self.write(hypr / "apps/theme.conf", "managed app theme\n")
        self.write(hypr / "monitors.conf", "stock monitor\n")
        self.write(hypr / "bindings.conf", "stock bindings\n")
        monitor = self.write(self.home / ".config/hypr/monitors.conf", "user monitor\n")
        binding = self.write(self.home / ".config/hypr/bindings.conf", "user bindings\n")
        colors = self.write(self.home / ".config/eww/theme-colors.scss", "user theme\n")
        choice = self.write(self.home / ".config/smplos/workspace-policy.json", '{"enabled":false}\n')
        script = self.config_sync_script() + "\nsync_configs\nsync_hypr_configs\n"
        self.run_bash(script)
        self.assertEqual(monitor.read_text(), "user monitor\n")
        self.assertEqual(binding.read_text(), "user bindings\n")
        self.assertEqual(colors.read_text(), "user theme\n")
        self.assertEqual(choice.read_text(), '{"enabled":false}\n')
        self.assertEqual((self.home / ".config/hypr/apps/theme.conf").read_text(), "managed app theme\n")
        events = self.log.read_text().splitlines()
        self.assertLess(events.index(str(self.home / ".config/eww/workspace-overview.yuck")),
                        events.index(str(self.home / ".config/eww/eww.yuck")))
        self.assertLess(events.index(str(self.home / ".config/hypr/workspace_policy.lua")),
                        events.index(str(self.home / ".config/hypr/hyprland.lua")))
        self.run_bash(script)
        self.assertEqual(self.log.read_text().splitlines(), events)

    def test_failed_fragment_install_leaves_old_entrypoint_intact(self):
        self.write(self.repo / "src/shared/eww/workspace-overview.yuck", "new fragment\n")
        self.write(self.repo / "src/shared/eww/eww.yuck", "new entry point\n")
        old = self.write(self.home / ".config/eww/eww.yuck", "old entry point\n")
        self.env["FAIL_FRAGMENT"] = "1"
        result = self.run_bash(self.config_sync_script() + "\nsync_configs\n", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not update config", result.stderr)
        self.assertEqual(old.read_text(), "old entry point\n")
        self.assertFalse((old.parent / "workspace-overview.yuck").exists())

    def test_normal_update_delivers_taskbar_files_without_replacing_preferences(self):
        commands = ("bar-ctl", "workspace-ctl", "smplos-hypr-dpms")
        configs = ("workspace-overview.yuck", "eww.yuck", "eww.scss",
                   "scripts/workspace-count.sh")
        for relative in ([f"src/shared/bin/{name}" for name in commands]
                         + [f"src/shared/eww/{name}" for name in configs]):
            destination = self.repo / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        preferences = {
            ".config/smplos/bar.conf": "ws_count=7\nws_style=squares\nws_spacing=3\nws_position=left\n",
            ".config/smplos/workspace-policy.json": '{"enabled":true,"homes":{"7":"m2"}}\n',
            ".config/hypr/hypridle.conf": "general {\n    lock_cmd = custom-lock\n}\n",
        }
        for relative, contents in preferences.items():
            self.write(self.home / relative, contents)
        installed = self.root / "installed"
        installed.mkdir()
        self.env["TEST_INSTALL_ROOT"] = str(installed)
        script = self.config_sync_script() + r"""
warn() { echo "$*" >&2; }
sudo() {
    [[ "$1" == install && "${@: -1}" == "$TEST_INSTALL_ROOT/"* ]] || {
        echo "FORBIDDEN sudo operation" >&2
        return 99
    }
    "$@"
}
sync_libs() { :; }
"""
        script += function("sync_scripts").replace(
            'dest="/usr/local/bin/$name"', 'dest="$TEST_INSTALL_ROOT/$name"')
        script += "\nsync_scripts\nsync_configs\n"
        result = self.run_bash(script)
        self.assertNotIn("FORBIDDEN", result.stderr)
        for name in commands:
            self.assertEqual((installed / name).read_bytes(), (BIN / name).read_bytes())
            self.assertTrue(os.access(installed / name, os.X_OK))
        for name in configs:
            self.assertEqual((self.home / ".config/eww" / name).read_bytes(),
                             (ROOT / "src/shared/eww" / name).read_bytes())
        self.assertTrue(os.access(self.home / ".config/eww/scripts/workspace-count.sh", os.X_OK))
        for relative, contents in preferences.items():
            self.assertEqual((self.home / relative).read_text(), contents)
        self.run_bash(script)
        for relative, contents in preferences.items():
            self.assertEqual((self.home / relative).read_text(), contents)

    def test_first_login_enrolls_once_and_keeps_enabled_or_disabled_choices(self):
        self.mocks()
        script = 'exec bash "$SESSION_INIT"'
        self.env["SESSION_INIT"] = str(BIN / "workspace-session-init")
        self.run_bash(script)
        self.assertEqual(self.log.read_text(), "workspace-ctl enroll\n")
        self.log.write_text("")
        config = self.home / ".config/smplos"
        self.write(config / "workspace-policy.json", '{"enabled":false}\n')
        self.run_bash(script)
        self.assertEqual(self.log.read_text(), "workspace-group 1\n")
        self.log.write_text("")
        self.write(config / "workspace-policy.enabled", "")
        self.run_bash(script)
        self.assertEqual(self.log.read_text(), "workspace-ctl apply\n")
        self.log.write_text("")
        self.env["NIRI_SOCKET"] = "/mock/niri"
        self.run_bash(script)
        self.assertEqual(self.log.read_text(), "workspace-group 1\n")

    def migration_fixture(self):
        self.mocks()
        destination = self.repo / "migrations" / MIGRATION.name
        destination.parent.mkdir()
        shutil.copyfile(MIGRATION, destination)
        self.write(self.repo / "src/shared/lib/smplos-session-env.sh", """
SMPLOS_SESSION_UID=1234
smplos_have_hyprland() { [[ "$HAVE_HYPRLAND" == yes ]]; }
smplos_run_as_user() {
    printf 'as-user %s\\n' "$*" >> "$TEST_LOG"
    "$@"
}
""")
        self.env["MIGRATION"] = str(destination)

    def test_migration_uses_user_session_and_reloads_without_killing_bar(self):
        self.migration_fixture()
        self.run_bash('source "$MIGRATION"')
        calls = self.log.read_text()
        self.assertIn("as-user hyprctl reload config-only", calls)
        self.assertIn("as-user workspace-ctl enroll", calls)
        self.assertIn("as-user pgrep -u 1234 -x eww", calls)
        self.assertIn("as-user bar-ctl reload", calls)
        self.assertNotIn("kill", calls)
        self.assertLess(calls.index("hyprctl reload"), calls.index("workspace-ctl enroll"))

    def test_migration_defers_offline_session_and_surfaces_failures(self):
        self.migration_fixture()
        self.env["HAVE_HYPRLAND"] = "no"
        result = self.run_bash('source "$MIGRATION"')
        self.assertIn("next Hyprland login", result.stdout)
        self.assertEqual(self.log.read_text(), "")
        self.env["HAVE_HYPRLAND"] = "yes"
        self.env["FAIL_BAR"] = "1"
        self.assertNotEqual(self.run_bash('source "$MIGRATION"', check=False).returncode, 0)

    def test_missing_python_fails_before_any_live_session_action(self):
        self.migration_fixture()
        result = self.run_bash("""
command() {
    if [[ "$*" == "-v python3" ]]; then return 1; fi
    builtin command "$@"
}
source "$MIGRATION"
""", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python is missing", result.stderr)
        self.assertEqual(self.log.read_text(), "")

    def test_iso_payload_contains_controller_and_first_login_hook(self):
        source = self.repo / "src"
        for name in ("workspace-ctl", "workspace-session-init"):
            self.write(source / "shared/bin" / name, (BIN / name).read_text())
        image = self.root / "image"
        (image / "usr/local/bin").mkdir(parents=True)
        builder = (ROOT / "src/builder/build.sh").read_text()
        block = builder.split("    # Copy shared bin scripts\n", 1)[1].split(
            "    # Copy shared shell libraries", 1)[0]
        self.env.update(SRC_DIR=str(source), airootfs=str(image))
        self.run_bash("set -e\nlog_info() { :; }\n" + block)
        for name in ("workspace-ctl", "workspace-session-init"):
            for prefix in ("usr/local/bin", "root/smplos/bin"):
                installed = image / prefix / name
                self.assertEqual(installed.read_bytes(), (BIN / name).read_bytes())
                self.assertTrue(os.access(installed, os.X_OK))
        self.assertIn("\npython\n", (ROOT / "src/shared/packages.txt").read_text())
        self.assertIn("workspace-session-init",
                      (ROOT / "src/compositors/hyprland/hypr/autostart.lua").read_text())


if __name__ == "__main__":
    unittest.main()
