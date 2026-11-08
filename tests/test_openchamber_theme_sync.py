import copy
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_app_delivery import function
from test_theme_switching import MOCK_COMMAND


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/shared/bin/theme-set-openchamber"
loader = importlib.machinery.SourceFileLoader("openchamber_theme_sync", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
sync = importlib.util.module_from_spec(spec)
loader.exec_module(sync)


class OpenChamberThemeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.current = self.home / ".config/smplos/current"
        self.current.mkdir(parents=True)
        self.data = self.home / ".config/openchamber"
        self.data.mkdir()
        self.settings = self.data / "settings.json"
        self.settings_saved = b'{"personal":"keep","themeVariant":"system"}\n'
        self.settings.write_bytes(self.settings_saved)
        self.path = self.data / "preferences.json"
        self.document = {
            "version": 1, "personal": {"unique": ["keep"]},
            "fields": {
                "themeId": {
                    "value": "base-theme", "updatedAt": 10,
                    "surfaces": {
                        "desktop": {"value": "previous", "updatedAt": 20},
                        "web": {"value": "web-theme", "updatedAt": 30},
                    },
                    "personal": "keep",
                },
                "themeVariant": {"value": "system", "updatedAt": 1},
                "lightThemeId": {
                    "surfaces": {"desktop": {"value": "existing-light", "updatedAt": 2}},
                },
                "font": {"value": {"size": 13}, "updatedAt": 5},
            },
        }
        self.saved = json.dumps(self.document, indent=2).encode() + b"\n"
        self.path.write_bytes(self.saved)
        self.select("amber")
        self.no_network = patch("socket.socket", side_effect=AssertionError("Network is forbidden"))
        self.no_network.start()
        self.addCleanup(self.no_network.stop)

    def select(self, name):
        (self.current / "theme.name").write_text(name + "\n")
        if (self.current / "theme").exists():
            shutil.rmtree(self.current / "theme")
        shutil.copytree(ROOT / "src/shared/themes" / name, self.current / "theme")

    def publish(self):
        sync.publish(self.home, self.data, sync.palette(self.current))

    def desktop(self, key):
        return json.loads(self.path.read_bytes())["fields"][key]["surfaces"]["desktop"]

    def test_all_stock_palettes_have_exact_roles_alpha_variant_and_deterministic_ids(self):
        for path in (ROOT / "src/shared/themes").glob("*/colors.toml"):
            with self.subTest(theme=path.parent.name):
                self.select(path.parent.name)
                theme = sync.palette(self.current)
                with path.open("rb") as source:
                    colors = sync.tomllib.load(source)
                self.assertEqual(theme["metadata"]["id"], f"smplos-{path.parent.name}")
                self.assertEqual(theme["colors"]["surface"]["background"], colors["background"])
                self.assertEqual(theme["colors"]["surface"]["foreground"], colors["foreground"])
                self.assertEqual(theme["colors"]["primary"]["base"], colors["accent"])
                self.assertEqual(theme["config"]["backgroundOpacity"], float(colors["app_background_opacity"]))
                self.assertEqual(theme["metadata"]["variant"],
                                 "light" if (path.parent / "light.mode").exists() else "dark")
                self.assertEqual(theme, sync.palette(self.current))

    def test_publish_only_changes_desktop_selection_preserving_every_other_value(self):
        self.publish()
        actual = json.loads(self.path.read_bytes())
        expected = copy.deepcopy(self.document)
        for key, value in (("themeId", "smplos-amber"), ("darkThemeId", "smplos-amber"),
                           ("useSystemTheme", False)):
            record = actual["fields"][key]["surfaces"]["desktop"]
            self.assertEqual(record["value"], value)
            self.assertGreater(record["updatedAt"], 30)
            expected["fields"].setdefault(key, {"updatedAt": 0}).setdefault("surfaces", {})["desktop"] = record
        self.assertEqual(actual, expected)
        self.assertEqual(self.settings.read_bytes(), self.settings_saved)
        self.assertEqual(json.loads((self.data / "themes/smplos-amber.json").read_bytes()),
                         sync.palette(self.current))
        backups = list((self.home / ".local/state/smplos/openchamber-theme-backups").rglob("preferences.json.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.saved)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.data.rglob("*.tmp")), [])

    def test_repeat_is_byte_identical_without_timestamp_or_id_churn(self):
        self.publish()
        before = self.path.read_bytes()
        target = self.data / "themes/smplos-amber.json"
        before_stat = target.stat()
        self.publish()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(target.stat().st_ino, before_stat.st_ino)
        self.assertEqual(list(target.parent.glob("*.json")), [target])

    def test_exact_minimal_and_desktop_only_documents_from_app_contract(self):
        documents = [
            {"version": 1, "fields": {}},
            {"version": 1, "fields": {
                key: {"updatedAt": 0, "surfaces": {
                    "desktop": {"value": value, "updatedAt": 1720000000000},
                }}
                for key, value in (("themeId", "smplos-example"), ("useSystemTheme", False),
                                   ("darkThemeId", "smplos-example"))
            }},
            {"version": 1, "fields": {"themeId": {"surfaces": {"desktop": {"value": "old"}}}}},
        ]
        for document in documents:
            with self.subTest(document=document):
                self.path.write_text(json.dumps(document))
                self.publish()
                result = json.loads(self.path.read_bytes())
                sync.preferences(self.path.read_bytes())
                self.assertNotIn("value", result["fields"]["themeId"])
                self.assertEqual(self.desktop("themeId")["value"], "smplos-amber")
                self.assertEqual(self.desktop("darkThemeId")["value"], "smplos-amber")
                self.assertIs(self.desktop("useSystemTheme")["value"], False)
                self.assertNotIn("lightThemeId", result["fields"])
                for field in result["fields"].values():
                    self.assertIsInstance(field["surfaces"]["desktop"]["updatedAt"], int)

    def test_same_selected_id_republishes_palette_and_preserves_preferences_bytes(self):
        self.publish()
        before = self.path.read_bytes()
        target = self.data / "themes/smplos-amber.json"
        previous = target.read_bytes()
        colors = self.current / "theme/colors.toml"
        colors.write_text(colors.read_text().replace('accent = "#FFA033"', 'accent = "#112233"'))
        self.publish()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(json.loads(target.read_bytes())["colors"]["primary"]["base"], "#112233")
        backups = list((self.home / ".local/state/smplos/openchamber-theme-backups").rglob("smplos-amber.json.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), previous)

    def test_opaque_translucent_light_and_opaque_roundtrip_uses_actual_palette_identity(self):
        for name in ("amber", "catppuccin", "catppuccin-latte", "amber"):
            self.select(name)
            self.publish()
            theme = sync.palette(self.current)
            self.assertEqual(self.desktop("themeId")["value"], theme["metadata"]["id"])
            self.assertEqual(self.desktop(f'{theme["metadata"]["variant"]}ThemeId')["value"],
                             theme["metadata"]["id"])
            self.assertIs(self.desktop("useSystemTheme")["value"], False)
            published = json.loads((self.data / "themes" / f"smplos-{name}.json").read_bytes())
            self.assertEqual(published, theme)
        self.assertEqual(self.settings.read_bytes(), self.settings_saved)
        self.assertEqual(self.desktop("lightThemeId")["value"], "smplos-catppuccin-latte")

    def test_future_timestamps_are_not_overruled_by_older_desktop_updates(self):
        document = copy.deepcopy(self.document)
        document["fields"]["themeId"]["updatedAt"] = 9_000_000_000_000
        self.path.write_text(json.dumps(document))
        with patch.object(sync.time, "time_ns", return_value=1):
            self.publish()
        self.assertGreater(self.desktop("themeId")["updatedAt"], 9_000_000_000_000)

    def test_unadvanceable_timestamps_refuse_publication_without_overwrite(self):
        document = copy.deepcopy(self.document)
        document["fields"]["themeId"]["updatedAt"] = 9_007_199_254_740_991
        self.path.write_text(json.dumps(document))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "advanced safely"):
            self.publish()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.data / "themes").exists())

    def test_invalid_preferences_are_never_backed_up_or_replaced_and_publish_no_palette(self):
        invalid = [
            b"invalid", b"[]", b'{"version":2,"fields":{}}',
            b'{"version":true,"fields":{}}', b'{"version":1,"fields":[]}',
            b'{"version":1,"version":1,"fields":{}}',
            b'{"version":1,"fields":{"themeId":null}}',
            b'{"version":1,"fields":{"themeId":{"surfaces":[]}}}',
            b'{"version":1,"fields":{"themeId":{"value":"a","updatedAt":NaN}}}',
            b'{"version":1,"fields":{"themeId":{"surfaces":{"desktop":{}}}}}',
            b'{"version":1,"fields":{},"personal":{"value":1e999}}',
            b'{"version":1,"fields":{"themeId":{"value":"a","updatedAt":-1}}}',
            b'{"version":1,"fields":{"themeId":{"value":"a","updatedAt":true}}}',
            b'{"version":1,"fields":{"themeId":{}}}',
            b'{"version":1,"fields":{"themeId":{"surfaces":{"unknown":{"value":"a"}}}}}',
        ]
        for content in invalid:
            with self.subTest(content=content):
                self.path.write_bytes(content)
                with self.assertRaises(ValueError):
                    self.publish()
                self.assertEqual(self.path.read_bytes(), content)
                self.assertFalse((self.data / "themes").exists())
                self.assertFalse((self.home / ".local/state/smplos/openchamber-theme-backups").exists())

    def test_missing_unreadable_and_symlinked_preferences_fail_before_writes(self):
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.publish()
        self.path.write_bytes(self.saved)
        original = Path.read_bytes

        def unreadable(path):
            if path == self.path:
                raise PermissionError("fixture unreadable")
            return original(path)

        with patch.object(Path, "read_bytes", unreadable), self.assertRaises(PermissionError):
            self.publish()
        alternate = self.home / "unique-preferences"
        alternate.write_bytes(self.saved)
        self.path.unlink()
        self.path.symlink_to(alternate)
        with self.assertRaisesRegex(ValueError, "symlinked"):
            self.publish()
        self.assertEqual(alternate.read_bytes(), self.saved)
        self.assertFalse((self.data / "themes").exists())

    def test_concurrent_preferences_write_is_preserved_and_partial_publication_reported(self):
        original = sync.atomic_write
        concurrent = self.saved.replace(b'"keep"', b'"concurrent"')

        def race(path, content, previous):
            if path == self.path:
                path.write_bytes(concurrent)
            return original(path, content, previous)

        with patch.object(sync, "atomic_write", race):
            with self.assertRaisesRegex(ValueError, "selection is unconfirmed.*concurrent edits"):
                self.publish()
        self.assertEqual(self.path.read_bytes(), concurrent)
        self.assertTrue((self.data / "themes/smplos-amber.json").exists())
        self.assertEqual(list(self.data.rglob("*.tmp")), [])

    def test_concurrent_palette_write_is_not_lost(self):
        original = sync.atomic_write
        target = self.data / "themes/smplos-amber.json"
        concurrent = b'{"unique":"concurrent palette"}'

        def race(path, content, previous):
            if path == target:
                path.write_bytes(concurrent)
            return original(path, content, previous)

        with patch.object(sync, "atomic_write", race):
            with self.assertRaisesRegex(ValueError, "concurrent edits"):
                self.publish()
        self.assertEqual(target.read_bytes(), concurrent)
        self.assertEqual(self.path.read_bytes(), self.saved)
        self.assertEqual(list(self.data.rglob("*.tmp")), [])

    def test_backup_failure_stops_before_publication(self):
        with patch.object(sync, "backup", side_effect=OSError("backup failed")):
            with self.assertRaisesRegex(OSError, "backup failed"):
                self.publish()
        self.assertFalse((self.data / "themes").exists())
        self.assertEqual(self.path.read_bytes(), self.saved)

    def test_existing_backup_permissions_are_repaired_without_losing_data(self):
        sync.backup(self.home, self.path, self.saved)
        root = self.home / ".local/state/smplos/openchamber-theme-backups"
        target = next(root.rglob("preferences.json.*"))
        root.chmod(0o755)
        target.parent.chmod(0o755)
        target.chmod(0o644)
        sync.backup(self.home, self.path, self.saved)
        for path in (root, target.parent):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.read_bytes(), self.saved)

    def test_missing_app_is_noop_explicit_bad_target_errors_and_discovery_is_local(self):
        for path in (self.path, self.settings):
            path.unlink()
        with patch.dict(sync.os.environ, {}, clear=True):
            self.assertEqual(sync.targets(self.home), [])
        self.path.write_bytes(self.saved)
        with patch.dict(sync.os.environ, {}, clear=True):
            self.assertEqual(sync.targets(self.home), [self.data])
        for value in ("relative", "https://example.test/data"):
            with patch.dict(sync.os.environ, {"OPENCHAMBER_DATA_DIR": value}, clear=True):
                with self.assertRaises(ValueError):
                    sync.targets(self.home)

    def test_override_replaces_default_and_preserves_real_instance(self):
        demo = self.home / "demo"
        demo.mkdir()
        (demo / "preferences.json").write_bytes(self.saved)
        override = self.current.parent / "openchamber-data-dirs"
        override.write_text(f"# isolated only\n{demo}\n{demo}\n")
        with patch.dict(sync.os.environ, {}, clear=True):
            self.assertEqual(sync.targets(self.home), [demo])
        sync.publish(self.home, demo, sync.palette(self.current))
        self.assertFalse((self.data / "themes").exists())
        self.assertEqual(self.path.read_bytes(), self.saved)
        override.write_text("")
        with self.assertRaises(ValueError):
            sync.targets(self.home)

    def test_invalid_colors_and_opacity_are_errors(self):
        colors = self.current / "theme/colors.toml"
        original = colors.read_text()
        for value in ('"NaN"', '"2"', '"0"', 'true', '""'):
            with self.subTest(value=value):
                colors.write_text(original.replace('app_background_opacity = "1.0"',
                                                   f"app_background_opacity = {value}"))
                with self.assertRaises(ValueError):
                    sync.palette(self.current)
        colors.write_text(original.replace('accent = "#FFA033"', 'accent = "#FFA03380"'))
        with self.assertRaises(ValueError):
            sync.palette(self.current)

    def test_real_canonical_entry_point_publishes_only_isolated_instance_without_api(self):
        demo = self.home / "demo"
        demo.mkdir()
        (demo / "preferences.json").write_bytes(self.saved)
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        (bin_dir / "theme-set-openchamber").symlink_to(SCRIPT)
        for command in ("pgrep", "gsettings", "fish", "code", "codium", "cursor"):
            target = bin_dir / command
            target.write_text(MOCK_COMMAND)
            target.chmod(0o755)
        env = {
            **os.environ, "HOME": str(self.home), "OPENCHAMBER_DATA_DIR": str(demo),
            "PATH": f"{bin_dir}:/usr/bin:/bin", "CALL_LOG": str(self.home / "calls"),
            "WAYLAND_DISPLAY": "", "DISPLAY": "", "ST_PID": "",
            "DBUS_SESSION_BUS_ADDRESS": "", "XDG_CONFIG_HOME": str(self.home / ".config"),
        }
        for name in ("amber", "catppuccin", "catppuccin-latte", "amber"):
            self.select(name)
            result = subprocess.run(["bash", str(SCRIPT.parent / "theme-set"), "--apps"],
                                    env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("OpenChamber theme sync failed", result.stderr)
            theme_path = demo / "themes" / f"smplos-{name}.json"
            self.assertEqual(json.loads(theme_path.read_bytes()), sync.palette(self.current))
            actual = json.loads((demo / "preferences.json").read_bytes())
            self.assertEqual(actual["fields"]["themeId"]["surfaces"]["desktop"]["value"],
                             f"smplos-{name}")
        self.assertEqual(self.path.read_bytes(), self.saved)
        self.assertEqual(self.settings.read_bytes(), self.settings_saved)
        self.assertFalse((self.data / "themes").exists())
        source = SCRIPT.read_text()
        for forbidden in ("http.client", "theme.set", "theme.capabilities", "/api/"):
            self.assertNotIn(forbidden, source)

    def test_normal_os_delivery_installs_bridge_and_both_native_alpha_rules(self):
        project = self.home / "repo"
        scripts = project / "src/shared/bin"
        scripts.mkdir(parents=True)
        for name in ("theme-set", "theme-set-openchamber"):
            shutil.copyfile(ROOT / "src/shared/bin" / name, scripts / name)
        rules = project / "src/compositors/hyprland/hypr"
        rules.mkdir(parents=True)
        for name in ("windows.lua", "windows.conf"):
            shutil.copyfile(ROOT / "src/compositors/hyprland/hypr" / name, rules / name)
        destination = self.home / "installed-bin"
        destination.mkdir()
        personal = self.home / ".config/hypr/bindings.conf"
        personal.parent.mkdir(parents=True)
        personal.write_text("my bindings\n")
        (rules / "bindings.conf").write_text("stock bindings\n")
        updater = ROOT / "src/shared/bin/smplos-os-update"
        sync_scripts = function(updater, "sync_scripts").replace(
            'dest="/usr/local/bin/$name"', 'dest="$FIXTURE_BIN/$name"')
        script = """
set -e
header() { :; }; ok() { :; }; log() { :; }; die() { echo "$*" >&2; exit 1; }
as_invoker() { "$@"; }; sync_libs() { :; }
install_system_file() { install -m"$3" "$1" "$2"; }
copy_user_config() { install -m644 "$1" "$2"; }
"""
        script += sync_scripts + "\n" + function(updater, "sync_hypr_configs")
        script += "\nsync_scripts\nsync_hypr_configs\nsync_scripts\nsync_hypr_configs\n"
        result = subprocess.run(
            ["bash", "-c", script],
            env={**os.environ, "HOME": str(self.home), "SMPLOS_REPO": str(project),
                 "FIXTURE_BIN": str(destination)},
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ("theme-set", "theme-set-openchamber"):
            self.assertEqual((destination / name).read_bytes(), (scripts / name).read_bytes())
            self.assertEqual((destination / name).stat().st_mode & 0o777, 0o755)
        for name in ("windows.lua", "windows.conf"):
            self.assertEqual((personal.parent / name).read_bytes(), (rules / name).read_bytes())
            self.assertIn("openchamber", (personal.parent / name).read_text())
        self.assertEqual(personal.read_text(), "my bindings\n")
        optional = updater.read_text().split('if [[ ${OPTIONAL_ONLY:-0} -eq 1 ]]; then', 1)[1]
        self.assertIn("as_invoker theme-set --apps || optional_failed=1", optional)
        builder = (ROOT / "src/builder/build.sh").read_text()
        self.assertIn('cp -r "$SRC_DIR/shared/bin/"* "$airootfs/usr/local/bin/"', builder)
        self.assertIn('cp -r "$compositor_dir/hypr/"* "$skel/.config/hypr/"', builder)


if __name__ == "__main__":
    unittest.main()
