from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = ROOT / "src/shared/bin/smplos-settings"
BUILDER = ROOT / "src/shared/bin/rebuild-app-cache"
SETTINGS_TABS = ("about", "keyboard", "dictation", "display", "power", "keybindings",
                 "taskbar", "connections", "wifi", "bluetooth", "keypad", "mouse")


class SettingsDispatchTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bin = Path(tmp.name) / "bin"
        self.bin.mkdir()
        self.log = Path(tmp.name) / "calls.log"

    def install(self, name, body=""):
        tool = self.bin / name
        tool.write_text(f'#!/bin/bash\necho "{name} $*" >> "{self.log}"\n{body}\n')
        tool.chmod(0o755)

    def dispatch(self, *args, **env):
        # Only the mocks are on PATH, so no real tool or settings app can answer.
        return subprocess.run(["/bin/bash", str(DISPATCHER), *args],
                              env={"PATH": str(self.bin), **env},
                              capture_output=True, text=True, timeout=15)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_each_tab_name_opens_that_tab_of_the_settings_app(self):
        self.install("settings")
        for tab in SETTINGS_TABS:
            with self.subTest(tab=tab):
                self.log.unlink(missing_ok=True)
                result = self.dispatch(tab)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls(), [f"settings --tab {tab}"])

    def test_a_missing_settings_app_is_reported_instead_of_ignored(self):
        self.install("notify-send")
        for tab in ("connections", "mouse", "keypad", "keybindings", "taskbar"):
            with self.subTest(tab=tab):
                self.log.unlink(missing_ok=True)
                result = self.dispatch(tab)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(len(self.calls()), 1, self.calls())
                self.assertIn("Settings app not found", self.calls()[0])

    def test_terminal_fallbacks_execute_the_tool_inside_terminal(self):
        self.install("terminal", '[ "$1" = "-e" ] || exit 99\nshift\nexec "$@"')
        for category, tool in (("display", "wlr-randr"), ("network", "nmtui"),
                               ("bluetooth", "bluetuith")):
            with self.subTest(category=category):
                self.log.unlink(missing_ok=True)
                self.install(tool)
                result = self.dispatch(category, WAYLAND_DISPLAY="wayland-fixture")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls(), [f"terminal -e {tool}", f"{tool} "])

    def test_graphical_tools_still_take_precedence_over_terminal_fallbacks(self):
        self.install("terminal")
        for category, gui, tui in (("display", "wdisplays", "wlr-randr"),
                                   ("network", "nm-connection-editor", "nmtui"),
                                   ("bluetooth", "blueman-manager", "bluetuith")):
            with self.subTest(category=category):
                self.log.unlink(missing_ok=True)
                self.install(gui)
                self.install(tui)
                result = self.dispatch(category, WAYLAND_DISPLAY="wayland-fixture")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls(), [f"{gui} "])

    def test_wayland_display_fallback_is_not_used_on_x11(self):
        for tool in ("terminal", "wlr-randr", "notify-send"):
            self.install(tool)
        result = self.dispatch("display")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.calls(), [
            "notify-send smplOS Settings No display tool found (install arandr)",
        ])

    def test_terminal_fallbacks_propagate_tool_failures(self):
        self.install("terminal", 'shift\nexec "$@"')
        for category, tool in (("display", "wlr-randr"), ("network", "nmtui"),
                               ("bluetooth", "bluetuith")):
            with self.subTest(category=category):
                self.log.unlink(missing_ok=True)
                self.install(tool, "echo 'tool failed' >&2\nexit 42")
                result = self.dispatch(category, WAYLAND_DISPLAY="wayland-fixture")
                self.assertEqual(result.returncode, 42)
                self.assertIn("tool failed", result.stderr)
                self.assertEqual(self.calls(), [f"terminal -e {tool}", f"{tool} "])

    def test_unknown_name_prints_a_usage_line_naming_every_tab(self):
        result = self.dispatch("no-such-tab")
        self.assertEqual(result.returncode, 1)
        usage = result.stderr.split("Usage:", 1)[1]
        for tab in SETTINGS_TABS:
            with self.subTest(tab=tab):
                self.assertRegex(usage, rf"[{{|]{tab}[|}}]")

    def test_every_launcher_entry_names_something_the_dispatcher_handles(self):
        self.install("settings")
        self.install("notify-send")
        names = set(re.findall(r"\bsmplos-settings ([a-z][\w-]*)", BUILDER.read_text()))
        self.assertLessEqual({"connections", "mouse", "keypad", "keybindings", "taskbar"}, names)
        for name in sorted(names):
            with self.subTest(entry=name):
                result = self.dispatch(name)
                self.assertNotIn("Usage:", result.stderr,
                                 f"'smplos-settings {name}' has no case in the dispatcher")


if __name__ == "__main__":
    unittest.main()
