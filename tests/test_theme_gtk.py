import configparser
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest
import shutil

import test_theme_switching as switching


ROOT = switching.ROOT


HELPER = ROOT / "src/shared/lib/smplos-gtk.py"
MIGRATION = ROOT / "migrations/20261027-140000-standard-gtk-defaults.sh"
spec = importlib.util.spec_from_file_location("smplos_gtk", HELPER)
gtk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gtk)


class GtkDefaultsTests(unittest.TestCase):
    setUp = switching.ThemeSwitchingTests.setUp
    make_theme = switching.ThemeSwitchingTests.make_theme
    switch = switching.ThemeSwitchingTests.switch

    def run_helper(self, mode="--dark", **extra):
        return subprocess.run(
            ["python3", str(HELPER), mode], env={**self.env, **extra},
            text=True, capture_output=True, timeout=15,
        )

    def setting(self, key, value):
        (self.home / f"gsettings-{key}").write_text(repr(value) + "\n")

    def read_setting(self, key):
        return (self.home / f"gsettings-{key}").read_text().strip()

    def test_missing_palette_icon_theme_is_repaired_and_backed_up(self):
        self.setting("icon-theme", "Yaru-yellow")
        old = (
            "[Settings]\n# personal settings\n"
            "gtk-icon-theme-name=Adwaita\ngtk-font-name=Personal Font 13\n"
            "gtk-enable-mnemonics=0\ngtk-auto-mnemonics=1\n"
            "gtk-overlay-scrolling=0\ngtk-cursor-theme-name=PersonalCursor\n"
        )
        for version in (3, 4):
            path = self.home / f".config/gtk-{version}.0/settings.ini"
            path.parent.mkdir(parents=True)
            path.write_text(old)
        env_file = self.home / ".config/environment.d/gtk.conf"
        env_file.parent.mkdir()
        env_file.write_text("# keep this\nGTK_THEME=Adwaita:dark\nXCURSOR_THEME=Adwaita\nOTHER=1\n")
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("unavailable", result.stderr)
        self.assertEqual(self.read_setting("icon-theme"), "'Adwaita'")
        for version in (3, 4):
            text = (self.home / f".config/gtk-{version}.0/settings.ini").read_text()
            self.assertIn("# personal settings", text)
            self.assertIn("Personal Font 13", text)
            self.assertIn("PersonalCursor", text)
            self.assertIn("gtk-overlay-scrolling=0", text)
            self.assertEqual("gtk-auto-mnemonics=1" in text, version == 3)
            self.assertEqual("gtk-enable-mnemonics=0" in text, version == 3)
        self.assertEqual(env_file.read_text(), "# keep this\nXCURSOR_THEME=Adwaita\nOTHER=1\n")
        saved = self.home / ".local/state/smplos/backups/gtk"
        snapshots = [json.loads(p.read_text()) for p in saved.glob("gsettings-*.bak")]
        self.assertEqual(snapshots[0]["icon-theme"], "Yaru-yellow")
        self.assertTrue(any(p.read_bytes() == old.encode() for p in saved.glob("gtk-4*.bak")))
        before = {p: p.read_bytes() for p in saved.iterdir()}
        self.assertEqual(self.run_helper().returncode, 0)
        self.assertEqual(before, {p: p.read_bytes() for p in saved.iterdir()})
        self.assertEqual(saved.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in saved.iterdir()))

    def test_installed_custom_icons_and_widget_theme_survive_switches(self):
        icons = self.home / "data/icons/PersonalIcons"
        icons.mkdir()
        (icons / "index.theme").write_text("[Icon Theme]\nName=PersonalIcons\n")
        self.setting("icon-theme", "PersonalIcons")
        self.setting("gtk-theme", "PersonalWidgets")
        (self.stock / "new/icons.theme").write_text("Yaru-purple\n")
        for name in ("new", "old"):
            result = self.switch(name)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.read_setting("icon-theme"), "'PersonalIcons'")
            self.assertEqual(self.read_setting("gtk-theme"), "'PersonalWidgets'")
            for version in (3, 4):
                settings = (self.home / f".config/gtk-{version}.0/settings.ini").read_text()
                self.assertIn("gtk-icon-theme-name=PersonalIcons", settings)

    def test_light_and_dark_do_not_force_the_global_theme(self):
        (self.stock / "new/light.mode").touch()
        for name, dark, scheme in (("new", 0, "prefer-light"), ("old", 1, "prefer-dark")):
            result = self.switch(name, GTK_THEME="Adwaita:dark",
                                 DBUS_SESSION_BUS_ADDRESS="unix:path=/fixture")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"gsettings set org.gnome.desktop.interface color-scheme {scheme}",
                          self.log.read_text())
            text = (self.home / ".config/gtk-4.0/settings.ini").read_text()
            self.assertIn(f"gtk-application-prefer-dark-theme={dark}", text)
            self.assertNotIn("gtk-auto-mnemonics", text)
        calls = self.log.read_text()
        self.assertIn("systemctl --user unset-environment GTK_THEME", calls)
        self.assertIn("dbus-update-activation-environment GTK_THEME=", calls)
        self.assertNotIn("import-environment GTK_THEME", calls)

    def test_explicit_custom_theme_override_and_cursor_are_not_rewritten(self):
        result = self.switch(
            "new", GTK_THEME="Personal", WAYLAND_DISPLAY="wayland-test",
            HYPRLAND_INSTANCE_SIGNATURE="fixture", DBUS_SESSION_BUS_ADDRESS="unix:path=/fixture",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text()
        self.assertNotIn("unset-environment", calls)
        self.assertNotIn("hyprctl eval ", calls)
        self.assertNotIn("hyprctl setcursor ", calls)
        self.assertNotIn("set org.gnome.desktop.interface cursor-theme", calls)

    def test_missing_default_assets_is_an_explicit_failure(self):
        (self.home / "data/icons/Adwaita/index.theme").unlink()
        self.setting("icon-theme", "Missing")
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("adwaita-icon-theme", result.stderr)
        self.assertEqual(self.read_setting("icon-theme"), "'Missing'")

    def test_malformed_ini_is_not_overwritten(self):
        config = self.home / ".config/gtk-4.0/settings.ini"
        config.parent.mkdir(parents=True)
        config.write_text("personal malformed settings\n")
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gtk:", result.stderr)
        self.assertEqual(config.read_text(), "personal malformed settings\n")

    def test_symlinked_settings_keep_link_and_backup_target(self):
        target = self.home / "personal-gtk.ini"
        target.write_text("[Settings]\ngtk-font-name=Keep 14\n")
        config = self.home / ".config/gtk-4.0/settings.ini"
        config.parent.mkdir(parents=True)
        config.symlink_to(target)
        self.assertEqual(self.run_helper().returncode, 0)
        self.assertTrue(config.is_symlink())
        self.assertIn("gtk-icon-theme-name=Adwaita", target.read_text())
        self.assertIn("Keep 14", target.read_text())

    def test_ini_sections_and_custom_environment_are_preserved(self):
        text = "[Settings]\ngtk-font-name=Keep 14\n[Other]\nkey=value\n"
        updated = gtk.settings_ini(text, False, "Adwaita", 4)
        parsed = configparser.ConfigParser()
        parsed.read_string(updated)
        self.assertEqual(parsed["Settings"]["gtk-icon-theme-name"], "Adwaita")
        self.assertEqual(parsed["Other"]["key"], "value")
        custom = "GTK_THEME=Personal\nCUSTOM=keep\n"
        self.assertEqual(gtk.environment_file(custom), custom)

    def test_existing_compositor_configs_retire_only_stock_overrides(self):
        examples = {
            self.home / ".config/hypr/envs.conf":
                "env = GTK_THEME,Adwaita:dark\nenv = OTHER,keep\n",
            self.home / ".config/hypr/envs.lua":
                'hl.env("GTK_THEME", "Adwaita:dark")\nhl.env("OTHER", "keep")\n',
            self.home / ".config/niri/config.kdl":
                'environment {\n    GTK_THEME "Adwaita:dark"\n    OTHER "keep"\n}\n',
            self.stock.parent / "configs/niri/base.kdl":
                'environment {\n    GTK_THEME "Adwaita:dark"\n}\n',
        }
        for path, text in examples.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in examples:
            self.assertNotIn("GTK_THEME", path.read_text())
        self.assertIn('OTHER "keep"', (self.home / ".config/niri/config.kdl").read_text())
        for kind, custom in (
            ("conf", "env = GTK_THEME,Personal\n"),
            ("lua", 'hl.env("GTK_THEME", "Personal")\n'),
            ("kdl", 'GTK_THEME "Personal"\n'),
        ):
            self.assertEqual(gtk.compositor_file(custom, kind), custom)

    def test_migration_defers_packages_then_repairs_preferences_idempotently(self):
        repo = self.stock.parent / "repo"
        script = repo / "migrations" / MIGRATION.name
        script.parent.mkdir(parents=True)
        shutil.copyfile(MIGRATION, script)
        lib = repo / "src/shared/lib"
        lib.mkdir(parents=True)
        shutil.copyfile(HELPER, lib / HELPER.name)
        (lib / "smplos-session-env.sh").write_text(
            'smplos_have_user_bus() { [[ "${HAVE_BUS:-1}" == 1 ]]; }\n'
            'smplos_run_as_user() { "$@"; }\n'
        )
        for name, body in (
            ("pacman", '[[ "${PACKAGES_INSTALLED:-0}" == 1 ]]\n'),
            ("pkexec", 'echo "unexpected installation" >&2; exit 99\n'),
        ):
            mock = self.bin / name
            mock.write_text("#!/bin/bash\n" + body)
            mock.chmod(0o755)
        self.setting("icon-theme", "Yaru-yellow")
        for extra, code in (
            ({}, 75),
            ({"PACKAGES_INSTALLED": "1", "HAVE_BUS": "0"}, 75),
            ({"SMPLOS_SYSTEM_UPGRADED": "1"}, 99),
            ({"PACKAGES_INSTALLED": "1"}, 0),
            ({"PACKAGES_INSTALLED": "1"}, 0),
        ):
            result = subprocess.run(
                ["bash", str(script)], env={**self.env, **extra},
                text=True, capture_output=True, timeout=15,
            )
            self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual(self.read_setting("icon-theme"), "'Adwaita'")

    def test_stock_themes_and_boot_configs_do_not_request_missing_icons_or_overrides(self):
        for path in (ROOT / "src/shared/themes").glob("*/icons.theme"):
            self.assertEqual(path.read_text().strip(), "Adwaita", str(path))
        for path in (
            ROOT / "src/compositors/hyprland/hypr/envs.conf",
            ROOT / "src/compositors/hyprland/hypr/envs.lua",
            ROOT / "src/compositors/niri/config.kdl",
            ROOT / "src/compositors/hyprland/postinstall.sh",
            ROOT / "src/compositors/niri/postinstall.sh",
        ):
            self.assertNotIn("GTK_THEME", path.read_text(), str(path))
        self.assertIn("adwaita-icon-theme", (ROOT / "src/shared/packages.txt").read_text())
        self.assertIn("# SMPLOS_UPDATE_PRIORITY=core", MIGRATION.read_text())

    def test_iso_stages_python_helpers_for_live_and_installed_systems(self):
        source = (ROOT / "src/builder/build.sh").read_text()
        fragment = source.split("    # Copy shared shell libraries ", 1)[1]
        fragment = fragment.split("    # Deploy shared web app", 1)[0].split("\n", 1)[1]
        source_root = self.home / "source"
        libraries = source_root / "shared/lib"
        libraries.mkdir(parents=True)
        shutil.copyfile(HELPER, libraries / HELPER.name)
        (libraries / "test.sh").write_text("# shell helper\n")
        destination = self.home / "airootfs"
        result = subprocess.run(
            ["bash", "-c", 'log_info() { :; }; stage() {\n' + fragment + '\n}; stage'],
            env={**self.env, "SRC_DIR": str(source_root), "airootfs": str(destination)},
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for relative in ("usr/local/lib/smplos", "root/smplos/lib"):
            target = destination / relative / HELPER.name
            self.assertEqual(target.read_bytes(), HELPER.read_bytes())
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)
        for path in (
            "src/shared/installer/automated_script.sh",
            "release/dev-local.sh", "release/dev-push.sh", "release/dev-apply.sh",
        ):
            self.assertIn('*.py', (ROOT / path).read_text(), path)


if __name__ == "__main__":
    unittest.main()
