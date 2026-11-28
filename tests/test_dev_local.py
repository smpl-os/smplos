"""Exercise local-deploy fragments in temporary homes, never as root."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "release/dev-local.sh").read_text()


class LocalDeployTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        (self.home / ".config/smplos/current").mkdir(parents=True)
        (self.home / ".config/smplos/current/theme.name").write_text("grafium\n")
        theme = self.home / ".config/smplos/current/theme"
        theme.mkdir()
        (theme / "colors.toml").write_text('background = "#101010"\n')
        self.env = {**os.environ, "USER_HOME": str(self.home)}

    def run_fragment(self, fragment, **env):
        prelude = """
set -euo pipefail
log() { echo "$*"; }
warn() { echo "$*"; }
err() { echo "$*" >&2; }
BOLD= NC=
restart_hypr="${RESTART_HYPR:-false}"
plugin_action="${PLUGIN_ACTION:-}"
do_component() { [[ "$1" == "${COMPONENT:-themes}" ]]; }
own() { :; }
command() {
    [[ "$*" == "-v chromium" || "$*" == "-v brave" ]] && return 1
    builtin command "$@"
}
run_as_user() {
    echo "as-user $*"
    case "$*" in
        "theme-set "*)
            if [[ "${FAIL_THEME:-0}" != 0 ]]; then
                echo "precise theme failure" >&2
                return "$FAIL_THEME"
            fi ;;
        "bar-ctl reload") return "${FAIL_BAR:-0}" ;;
        "hyprctl reload") return "${FAIL_HYPR:-0}" ;;
        *smplos-plugins*) return "${FAIL_PLUGIN:-0}" ;;
    esac
}
"""
        return subprocess.run(["bash", "-c", prelude + fragment],
                              env={**self.env, **env}, capture_output=True, text=True, timeout=5)

    def restart_fragment(self):
        return SOURCE.split("# ── Restart services", 1)[1].split("\n", 1)[1]

    def test_theme_failure_is_visible_and_never_starts_or_reports_success(self):
        result = self.run_fragment(self.restart_fragment(), FAIL_THEME="7")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("precise theme failure", result.stderr)
        self.assertIn("deployment is incomplete", result.stderr)
        self.assertNotIn("All done!", result.stdout)
        self.assertNotIn("bar-ctl start", result.stdout)
        self.assertNotIn("kill", result.stdout)

    def test_success_uses_existing_daemon_without_parallel_start(self):
        result = self.run_fragment(self.restart_fragment())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("as-user theme-set 'grafium'", result.stdout)
        self.assertIn("All done!", result.stdout)
        self.assertNotIn("bar-ctl start", result.stdout)
        self.assertNotIn("killall", SOURCE)

    def test_plugins_reload_after_hyprland_reload_with_the_checkout_tool(self):
        result = self.run_fragment(self.restart_fragment(), RESTART_HYPR="true",
                                   PLUGIN_ACTION="reload", SRC_DIR="/checkout/src")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        tool = "as-user bash '/checkout/src/shared/bin/smplos-plugins' reload"
        self.assertIn(tool, lines)
        self.assertLess(lines.index("as-user hyprctl reload"), lines.index(tool))
        self.assertIn("All done!", result.stdout)

    def test_plugins_untouched_when_the_component_was_not_selected(self):
        result = self.run_fragment(self.restart_fragment(), RESTART_HYPR="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("smplos-plugins", result.stdout)

    def test_plugin_reload_failure_stops_deployment(self):
        result = self.run_fragment(self.restart_fragment(), PLUGIN_ACTION="load",
                                   SRC_DIR="/checkout/src", FAIL_PLUGIN="9")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Plugin load failed", result.stderr)
        self.assertNotIn("All done!", result.stdout)

    def plugin_build_fragment(self):
        fragment = SOURCE.split("# ── Compositor plugins ", 1)[1].split("\n", 1)[1]
        return fragment.split("# ── Rust apps", 1)[0] + '\necho "action=$plugin_action"\n'

    def run_plugin_build(self, tool_body, headers=True):
        src = self.home / "checkout/src"
        (src / "shared/bin").mkdir(parents=True)
        (src / "compositors/hyprland/plugins/demo").mkdir(parents=True)
        (src / "shared/bin/smplos-plugins").write_text(tool_body)
        installed = self.home / "installed"
        installed.mkdir()
        header = self.home / "version.h"
        if headers:
            header.write_text("#define GIT_COMMIT_HASH \"x\"\n")
        result = self.run_fragment(
            self.plugin_build_fragment(), COMPONENT="plugins", REAL_USER="tester",
            SRC_DIR=str(src), SMPLOS_PLUGIN_DIR=str(installed),
            SMPLOS_HYPRLAND_VERSION_H=str(header))
        return result, installed

    def test_plugin_build_compiles_as_the_user_and_loads_when_nothing_changed(self):
        result, _ = self.run_plugin_build(
            'echo "tool user=$SMPLOS_INVOKER_USER args=$*"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tool user=tester args=sync --src ", result.stdout)
        self.assertIn("compositors/hyprland/plugins", result.stdout)
        self.assertIn("action=load", result.stdout)

    def test_plugin_build_reloads_when_a_binary_was_installed(self):
        result, installed = self.run_plugin_build(
            'echo built > "$SMPLOS_PLUGIN_DIR/demo.abc.so"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("action=reload", result.stdout)
        self.assertTrue((installed / "demo.abc.so").exists())

    def test_plugin_build_failure_stops_deployment(self):
        result, _ = self.run_plugin_build("exit 1\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Plugin build failed", result.stderr)
        self.assertNotIn("action=", result.stdout)

    def test_plugin_build_is_skipped_without_hyprland_headers(self):
        result, _ = self.run_plugin_build('echo "tool ran"\n', headers=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("tool ran", result.stdout)
        self.assertIn("Hyprland headers are not installed", result.stdout)
        self.assertIn("action=\n", result.stdout)

if __name__ == "__main__":
    unittest.main()
