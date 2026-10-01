import contextlib
import copy
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/shared/bin/theme-set-copilot"
loader = importlib.machinery.SourceFileLoader("copilot_theme_sync", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
sync = importlib.util.module_from_spec(spec)
loader.exec_module(sync)

ORIGINAL = {
    "themeName": "Homebrew", "mode": "dark", "terminalMode": "dark",
    "recentThemes": ["Homebrew", "GitHub"], "colorMode": "default",
    "codeFontScale": 110, "uiFontScale": 90, "showPointerOnHover": False,
}


class FakeUI:
    bus_error = ConnectionError

    def __init__(self, state):
        self.state = state
        self.events = []
        self.fail = False
        self.unavailable = False

    def open(self):
        self.events.append("open")

    def validate(self, target):
        self.events.append("validate")
        if self.unavailable:
            raise sync.SyncError("Palette not visible")

    def apply(self, target):
        self.events.append(("apply", target.copy()))
        self.state.update(target)
        self.state["recentThemes"] = [target["themeName"]]
        if self.fail:
            self.fail = False
            raise sync.SyncError("Live UI did not confirm")

    def close(self):
        self.events.append("close")


class CopilotThemeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / ".config/smplos"
        self.current = self.config / "current"
        (self.current / "theme").mkdir(parents=True)
        (self.current / "theme.name").write_text("everforest\n")
        self.database = self.home / ".copilot/data.db"
        self.database.parent.mkdir()
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT)")
            db.execute("INSERT INTO app_state VALUES (?, ?)", (
                "theme-settings-v2", json.dumps({"state": ORIGINAL, "version": 3}),
            ))
            db.execute("INSERT INTO app_state VALUES ('unrelated', 'untouched')")

    def test_mapping_covers_stock_and_only_verified_palette_names(self):
        stock = {p.parent.name for p in (ROOT / "src/shared/themes").glob("*/colors.toml")}
        self.assertEqual(stock, set(sync.PALETTES))
        verified = {
            "IC Orange PPL", "Catppuccin Mocha", "Light purple", "Selene Selenized",
            "Flexoki", "GitHub", "Gruvbox Material", "Homebrew", "Kanso Ink",
            "Monochrome", "Nord Midnight", "Espresso", "Rosé Pine", "Tokyo Night",
        }
        self.assertEqual(set(sync.PALETTES.values()), verified)
        for name, palette in sync.PALETTES.items():
            with self.subTest(name=name):
                (self.current / "theme.name").write_text(name)
                self.assertEqual(sync.target_for(self.current)["themeName"], palette)

    def test_mode_uses_marker_including_custom_theme(self):
        self.assertEqual(sync.target_for(self.current)["mode"], "dark")
        (self.current / "theme/light.mode").touch()
        (self.current / "theme.name").write_text("custom forest")
        with contextlib.redirect_stderr(io.StringIO()) as warning:
            result = sync.target_for(self.current)
        self.assertEqual(result, {"themeName": "GitHub", "mode": "light", "terminalMode": "light"})
        self.assertIn("No built-in mapping", warning.getvalue())

    def test_only_settings_row_read_and_database_unchanged(self):
        original = self.database.read_bytes()
        self.assertEqual(sync.read_settings(self.database), ORIGINAL)
        self.assertEqual(self.database.read_bytes(), original)

    def test_unsupported_settings_fail_before_ui_mutation(self):
        for value in ([], {"version": 4, "state": ORIGINAL}, {"version": 3, "state": {}}):
            with self.subTest(value=value), contextlib.closing(sqlite3.connect(self.database)) as db, db:
                db.execute("UPDATE app_state SET value=? WHERE key='theme-settings-v2'", (json.dumps(value),))
            with self.assertRaises(sync.SyncError):
                sync.read_settings(self.database)

    def test_absent_database_is_not_created(self):
        absent = self.home / "absent.db"
        with self.assertRaises(sqlite3.OperationalError):
            sync.read_settings(absent)
        self.assertFalse(absent.exists())

    def test_success_preserves_unrelated_settings_and_closes_view(self):
        state = copy.deepcopy(ORIGINAL)
        ui = FakeUI(state)
        target = sync.target_for(self.current)
        self.assertTrue(sync.synchronize(target, lambda: state.copy(), lambda: ui))
        self.assertEqual(ui.events[0], "open")
        self.assertEqual(ui.events[-1], "close")
        self.assertTrue(sync.matches(state, target))
        for key in set(ORIGINAL) - sync.MANAGED:
            self.assertEqual(state[key], ORIGINAL[key])

    def test_same_theme_does_not_open_settings(self):
        target = {k: ORIGINAL[k] for k in ("themeName", "mode", "terminalMode")}
        def forbidden():
            self.fail("UI must not be constructed for unchanged themes")
        self.assertFalse(sync.synchronize(target, lambda: ORIGINAL.copy(), forbidden))

    def test_partial_failure_rolls_back_through_ui_and_closes(self):
        state = copy.deepcopy(ORIGINAL)
        ui = FakeUI(state)
        ui.fail = True
        with self.assertRaisesRegex(sync.SyncError, "Live UI"):
            sync.synchronize(sync.target_for(self.current), lambda: state.copy(), lambda: ui)
        self.assertTrue(sync.matches(state, {k: ORIGINAL[k] for k in ("themeName", "mode", "terminalMode")}))
        self.assertEqual(ui.events[-1], "close")

    def test_missing_palette_closes_without_applying(self):
        ui = FakeUI(copy.deepcopy(ORIGINAL))
        ui.unavailable = True
        with self.assertRaisesRegex(sync.SyncError, "Palette not visible"):
            sync.synchronize(sync.target_for(self.current), lambda: ORIGINAL.copy(), lambda: ui)
        self.assertEqual(ui.events, ["open", "validate", "close"])

    def test_persistence_failure_is_not_success(self):
        ui = FakeUI(copy.deepcopy(ORIGINAL))
        with patch.object(sync.time, "monotonic", side_effect=[0, 5, 5]):
            with self.assertRaisesRegex(sync.SyncError, "not persisted"):
                sync.synchronize(sync.target_for(self.current), lambda: ORIGINAL.copy(), lambda: ui)
        self.assertEqual(ui.events[-1], "close")

    def run_cli(self):
        return subprocess.run(
            ["/usr/bin/python3", str(SCRIPT)], env={**os.environ, "HOME": str(self.home)},
            text=True, capture_output=True, timeout=5,
        )

    def test_opted_out_needs_no_accessibility_or_database(self):
        self.database.unlink()
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, "")

    def test_opted_in_missing_app_warns(self):
        (self.config / "copilot-theme-sync.enabled").touch()
        self.database.unlink()
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("start and configure the app", result.stderr)

    def test_reentrant_invocation_does_not_access_ui(self):
        (self.config / "copilot-theme-sync.enabled").touch()
        with (self.config / ".copilot-theme-sync.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("already running", result.stderr)

    def test_app_and_terminal_controls_are_scoped_separately(self):
        ui = object.__new__(sync.CopilotUI)
        ui.content = lambda: "theme-content"
        calls = []
        def require(root, role, name):
            calls.append((root, role, name))
            return name
        ui.require = require
        ui.mode("Terminal", "light")
        self.assertEqual(calls, [
            ("theme-content", "panel", "Terminal"), ("Terminal", "radio button", "Light"),
        ])

    def test_existing_settings_are_not_hijacked(self):
        ui = object.__new__(sync.CopilotUI)
        ui.settings_dialog = lambda: object()
        with self.assertRaisesRegex(sync.SyncError, "already open"):
            ui.open()

    def test_timed_out_action_observes_result_without_pressing_twice(self):
        ui = object.__new__(sync.CopilotUI)
        ui.bus_error = ConnectionError
        ui.deadline = sync.time.monotonic() + 5
        calls = []
        class Action:
            def get_n_actions(self):
                return 1
            def do_action(self, index):
                calls.append(index)
                raise ConnectionError("reply timed out after application")
        class Node:
            def get_action_iface(self):
                return Action()
        ui.press(Node(), lambda: True)
        self.assertEqual(calls, [0])

    def test_absent_accessible_app_warns_before_any_mutation(self):
        def absent():
            raise sync.SyncError("One running accessible GitHub Copilot app is required")
        with self.assertRaisesRegex(sync.SyncError, "running accessible"):
            sync.synchronize(sync.target_for(self.current), lambda: ORIGINAL.copy(), absent)

    def test_unrelated_settings_change_is_reported_not_overwritten(self):
        state = copy.deepcopy(ORIGINAL)
        ui = FakeUI(state)
        def read_state():
            result = state.copy()
            if ui.events:
                result["uiFontScale"] = 150
            return result
        with self.assertRaisesRegex(sync.SyncError, "Other Copilot settings changed"):
            sync.synchronize(sync.target_for(self.current), read_state, lambda: ui)
        self.assertEqual(ui.events[-1], "close")

    def test_keybinding_reaches_existing_picker_and_hook(self):
        bindings = (ROOT / "src/shared/configs/smplos/bindings.conf").read_text()
        picker = (ROOT / "src/shared/bin/theme-picker").read_text()
        theme_set = (ROOT / "src/shared/bin/theme-set").read_text()
        self.assertIn("bindd = SUPER SHIFT, T, Theme picker, exec, theme-picker", bindings)
        self.assertIn('theme-set "$dir_name" &', picker)
        self.assertIn("elif ! theme-set-copilot; then", theme_set)


if __name__ == "__main__":
    unittest.main()
