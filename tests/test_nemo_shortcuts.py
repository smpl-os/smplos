"""Nemo shortcut enrollment uses private schemas/settings, never real user files."""

import configparser
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations/20261118-000000-nemo-trash-and-admin.sh"
BIN = ROOT / "src/shared/bin"
DEFAULTS = {
    "trash": "F8",
    "trash-alt": "",
    "delete-permanently": "Delete",
    "delete-permanently-alt": "<Shift>F8",
    "custom-action": "<Control>q",
}


class NemoShortcutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        schema_dir = self.home / "schemas"
        schema_dir.mkdir()
        keys = "".join(
            f'<key name="{key}" type="s"><default>{escape(repr(value))}</default></key>'
            for key, value in DEFAULTS.items()
        )
        (schema_dir / "nemo.gschema.xml").write_text(
            '<schemalist><schema id="org.nemo.keybindings" path="/org/nemo/keybindings/">'
            + keys + "</schema></schemalist>"
        )
        subprocess.run(["glib-compile-schemas", str(schema_dir)], check=True, capture_output=True)
        self.env = {
            **os.environ, "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_STATE_HOME": str(self.home / ".local/state"),
            "GSETTINGS_SCHEMA_DIR": str(schema_dir), "GSETTINGS_BACKEND": "keyfile",
            "SMPLOS_PATH": str(self.home / "smplos"),
        }
        self.bindings = self.home / ".config/smplos/bindings.conf"
        self.bindings.parent.mkdir(parents=True)
        self.original = "bindd = SUPER SHIFT, F, File manager, exec, focus-or-launch --current-workspace nemo nemo\n"
        self.bindings.write_text(self.original)

    def settings(self, updates=None):
        program = """
import json, sys
from gi.repository import Gio
s=Gio.Settings.new("org.nemo.keybindings")
for key, value in json.loads(sys.argv[1]).items():
    assert s.set_string(key, value)
Gio.Settings.sync()
source=Gio.SettingsSchemaSource.get_default().lookup("org.nemo.keybindings", True)
print(json.dumps({key:s.get_string(key) for key in source.list_keys()}))
"""
        result = subprocess.run(
            ["python3", "-c", program, json.dumps(updates or {})], env=self.env,
            text=True, capture_output=True, check=True, timeout=10,
        )
        return json.loads(result.stdout)

    def migrate(self, success=True):
        result = subprocess.run(
            ["bash", str(MIGRATION)], env=self.env, text=True, capture_output=True, timeout=10,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_existing_nc_install_gains_delete_trash_and_keeps_permanent_alternates(self):
        self.settings({"delete-permanently": "<Shift>Delete"})
        self.migrate()
        self.assertEqual(self.settings(), {
            **DEFAULTS, "trash-alt": "Delete", "delete-permanently": "<Shift>Delete",
        })
        self.assertIn(self.original, self.bindings.read_text())
        self.assertIn("SUPER CTRL SHIFT, F, File manager (administrator), exec, nemo-admin",
                      self.bindings.read_text())
        backup_dir = self.home / ".local/state/smplos/backups/nemo-shortcuts"
        settings_backup = json.loads(next(backup_dir.glob("gsettings.*")).read_text())
        self.assertIsNone(settings_backup["trash-alt"]["user"])
        self.assertEqual(settings_backup["delete-permanently"]["user"], "'<Shift>Delete'")
        self.assertEqual(next(backup_dir.glob("bindings-*")).read_text(), self.original)
        for path in backup_dir.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        before = {path.name: path.read_bytes() for path in backup_dir.iterdir()}
        text = self.bindings.read_bytes()
        self.migrate()
        self.assertEqual(self.bindings.read_bytes(), text)
        self.assertEqual({path.name: path.read_bytes() for path in backup_dir.iterdir()}, before)

    def test_old_bare_permanent_default_is_repaired_before_delete_is_assigned_to_trash(self):
        self.migrate()
        values = self.settings()
        self.assertEqual(values["trash-alt"], "Delete")
        self.assertEqual(values["delete-permanently"], "<Shift>Delete")

    def test_explicit_custom_assignments_including_disabled_shortcuts_are_preserved(self):
        custom = {"trash": "<Control>t", "trash-alt": "",
                  "delete-permanently": "Delete", "delete-permanently-alt": "<Alt>d"}
        self.settings(custom)
        self.migrate()
        self.assertEqual(self.settings(), {**DEFAULTS, **custom})

    def test_custom_delete_conflict_preserves_assignment_and_reports_warning(self):
        self.settings({"custom-action": "Delete"})
        result = self.migrate()
        self.assertIn("already assigned", result.stdout)
        values = self.settings()
        self.assertEqual(values["custom-action"], "Delete")
        self.assertEqual(values["trash-alt"], "")

    def test_conflicting_permanent_repair_does_not_create_two_delete_actions(self):
        self.settings({"custom-action": "<shift>Delete"})
        result = self.migrate()
        self.assertIn("already assigned", result.stdout)
        self.assertEqual(self.settings()["delete-permanently"], "Delete")
        self.assertEqual(self.settings()["trash-alt"], "")

    def test_custom_admin_chord_in_legacy_file_prevents_duplicate_shared_binding(self):
        legacy = self.home / ".config/hypr/bindings.conf"
        legacy.parent.mkdir(parents=True)
        custom = "bind = SHIFT SUPER CTRL, f, exec, personal-file-manager\n"
        legacy.write_text(custom)
        self.migrate()
        self.assertEqual(legacy.read_text(), custom)
        self.assertEqual(self.bindings.read_text(), self.original)

    def test_unterminated_submap_cannot_capture_administrator_binding(self):
        self.bindings.write_text(self.original + "submap = resize\n")
        self.migrate()
        self.assertIn("submap = reset\nbindd = SUPER CTRL SHIFT, F", self.bindings.read_text())

    def test_symlinked_bindings_are_not_replaced(self):
        target = self.home / "custom-bindings"
        target.write_text(self.original)
        self.bindings.unlink()
        self.bindings.symlink_to(target)
        self.migrate(success=False)
        self.assertTrue(self.bindings.is_symlink())
        self.assertEqual(target.read_text(), self.original)

    def test_real_core_migration_runner_retries_failure_and_records_success_once(self):
        migrations = self.home / "smplos/repo/migrations"
        migrations.mkdir(parents=True)
        (migrations / MIGRATION.name).symlink_to(MIGRATION)
        marker = self.home / ".local/state/smplos/migrations" / MIGRATION.name
        target = self.home / "custom-bindings"
        target.write_text(self.original)
        self.bindings.unlink()
        self.bindings.symlink_to(target)

        def run():
            return subprocess.run(
                ["bash", str(BIN / "smplos-migrate"), "--phase", "core"],
                env=self.env, capture_output=True, text=True, timeout=10,
            )

        self.assertNotEqual(run().returncode, 0)
        self.assertFalse(marker.exists())
        self.bindings.unlink()
        self.bindings.write_text(self.original)
        result = run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(marker.exists())
        self.assertEqual(self.settings()["trash-alt"], "Delete")
        self.assertIn("exec, nemo-admin", self.bindings.read_text())
        before = self.bindings.read_bytes()
        self.assertEqual(run().returncode, 0)
        self.assertEqual(self.bindings.read_bytes(), before)

    def test_niri_live_and_source_configs_gain_chord_without_replacing_custom_commands(self):
        niri_paths = [
            self.home / "smplos/configs/niri/binds.kdl",
            self.home / ".config/niri/binds.kdl",
            self.home / ".config/niri/config.kdl",
        ]
        custom = 'binds {\n    Shift+Mod+Ctrl+F { spawn "personal-command"; }\n}\n'
        for path in niri_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(custom if path == niri_paths[1] else 'binds {\n    Mod+x { close-window; }\n}\n')
        self.migrate()
        for path in (niri_paths[0], niri_paths[2]):
            self.assertIn('Mod+Ctrl+Shift+f hotkey-overlay-title="File manager (administrator)"',
                          path.read_text())
            self.assertIn("Mod+x { close-window; }", path.read_text())
        self.assertEqual(niri_paths[1].read_text(), custom)
        before = [path.read_bytes() for path in niri_paths]
        self.migrate()
        self.assertEqual([path.read_bytes() for path in niri_paths], before)

    def test_admin_launcher_passes_only_admin_uri_to_normal_nemo_and_propagates_errors(self):
        mocks = self.home / "bin"
        mocks.mkdir()
        nemo = mocks / "nemo"
        nemo.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$HOME/launch-args"\nexit "${FAIL:-0}"\n')
        nemo.chmod(0o755)
        env = {**self.env, "PATH": f"{mocks}:{os.environ['PATH']}"}
        for status in (0, 7):
            result = subprocess.run(
                [str(BIN / "nemo-admin")], env={**env, "FAIL": str(status)},
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(result.returncode, status)
            self.assertEqual((self.home / "launch-args").read_text(), "admin:///\n")
        (self.home / "launch-args").unlink()
        result = subprocess.run(
            [str(BIN / "nemo-admin"), "/etc"], env=env, capture_output=True, text=True, timeout=5,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / "launch-args").exists())

    def test_stock_defaults_and_niri_translation_match_requested_layout(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read(ROOT / "src/shared/system/dconf/00-nemo")
        self.assertEqual(dict(config["org/nemo/keybindings"])["trash"], "'F8'")
        self.assertEqual(config["org/nemo/keybindings"]["trash-alt"], "'Delete'")
        self.assertEqual(config["org/nemo/keybindings"]["delete-permanently"], "'<Shift>Delete'")
        self.assertEqual(config["org/nemo/keybindings"]["delete-permanently-alt"], "'<Shift>F8'")
        binding = next(line for line in (ROOT / "src/shared/configs/smplos/bindings.conf").read_text()
                       .splitlines() if ", exec, nemo-admin" in line)
        result = subprocess.run(
            ["bash", str(BIN / "bindings-to-niri.sh"), "-", "-"],
            input=binding + "\n", capture_output=True, text=True, check=True, timeout=5,
        )
        generated = next(line for line in result.stdout.splitlines() if "nemo-admin" in line)
        self.assertIn(generated, (ROOT / "src/compositors/niri/binds.kdl").read_text())


if __name__ == "__main__":
    unittest.main()
