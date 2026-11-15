import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "src/shared/bin/rebuild-app-cache"


class AppCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.user_data = self.home / "user-data"
        self.local_data = self.home / "local-data"
        self.system_data = self.home / "system-data"
        self.cache = self.home / ".cache/smplos/app_index"
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "LC_ALL": "C",
            "XDG_DATA_HOME": str(self.user_data),
            "XDG_DATA_DIRS": f"{self.local_data}:{self.system_data}",
        }
        self.mock_find()

    def mock_find(self, fail=False):
        script = self.bin / "find"
        script.write_text(
            "#!/bin/bash\n"
            '[[ "$1" == /var/lib/flatpak/* ]] && exit 0\n'
            + ('echo "fixture scan failed" >&2; exit 1\n' if fail else
               'exec /usr/bin/find "$@"\n')
        )
        script.chmod(0o755)

    def desktop(self, root, desktop_id="grafium.desktop", **values):
        path = root / "applications" / desktop_id
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = {"Type": "Application", "Name": "Grafium", "Exec": "grafium",
                  "Icon": "grafium", **values}
        path.write_text("[Desktop Entry]\n" + "".join(
            f"{key}={value}\n" for key, value in fields.items()
        ))
        return path

    def rebuild(self, **env):
        return subprocess.run(
            ["bash", str(BUILDER)], env={**self.env, **env},
            capture_output=True, text=True, timeout=15,
        )

    def rows(self):
        return [line.split(";") for line in self.cache.read_text().splitlines()]

    def test_user_desktop_and_icon_override_win_before_name_dedup(self):
        self.desktop(self.system_data, "system-grafium.desktop", Icon="stale-blue")
        self.desktop(self.local_data, "local-grafium.desktop", Icon="local-system")
        self.desktop(self.user_data, Icon="/custom/icon.png", Exec='"grafium"')
        result = self.rebuild()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([row for row in self.rows() if row[0] == "Grafium"],
                         [["Grafium", '"grafium"', "apps", "/custom/icon.png"]])

    def test_desktop_id_override_can_rename_application(self):
        self.desktop(self.system_data)
        self.desktop(self.user_data, Name="My Notes", Icon="user-icon")
        self.assertEqual(self.rebuild().returncode, 0)
        self.assertNotIn("Grafium", [row[0] for row in self.rows()])
        self.assertIn(["My Notes", "grafium", "apps", "user-icon"], self.rows())

    def test_hidden_nodisplay_and_incomplete_overrides_mask_system_entry(self):
        for values in ({"Hidden": "true"}, {"NoDisplay": "true"}, {"Exec": ""}):
            with self.subTest(values=values):
                self.desktop(self.system_data)
                self.desktop(self.user_data, **values)
                self.desktop(self.user_data, "other.desktop", Name="Other")
                result = self.rebuild()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("Grafium", [row[0] for row in self.rows()])
                self.assertIn("Other", [row[0] for row in self.rows()])

    def test_nested_desktop_id_masks_flat_system_id(self):
        self.desktop(self.system_data, "wine-notes.desktop")
        self.desktop(self.user_data, "wine/notes.desktop", Name="Wine Notes")
        self.assertEqual(self.rebuild().returncode, 0)
        self.assertNotIn("Grafium", [row[0] for row in self.rows()])
        self.assertIn("Wine Notes", [row[0] for row in self.rows()])

    def test_data_dir_order_and_duplicate_roots(self):
        self.desktop(self.system_data)
        self.desktop(self.local_data, Name="Local Notes")
        result = self.rebuild(
            XDG_DATA_DIRS=f"{self.local_data}:{self.system_data}:{self.local_data}"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([row[0] for row in self.rows()].count("Local Notes"), 1)
        self.assertNotIn("Grafium", [row[0] for row in self.rows()])

    def test_default_and_invalid_relative_data_home_use_home(self):
        self.desktop(self.home / ".local/share", Icon="user-default")
        for data_home in ("", "relative/path"):
            with self.subTest(data_home=data_home):
                result = self.rebuild(XDG_DATA_HOME=data_home)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(["Grafium", "grafium", "apps", "user-default"], self.rows())

    def test_symlinked_flatpak_desktop_and_appimage_remain_indexed(self):
        export = self.user_data / "flatpak/exports/share"
        path = self.desktop(export, Name="Flatpak Notes", Exec="flatpak run notes %U")
        target = path.with_suffix(".source")
        path.rename(target)
        path.symlink_to(target)
        appimage = self.home / "Applications/Portable-1.2.AppImage"
        appimage.parent.mkdir()
        appimage.touch(mode=0o755)
        result = self.rebuild()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["Flatpak Notes", "flatpak run notes", "apps", "grafium"],
                      self.rows())
        self.assertIn(["Portable", str(appimage), "apps", "application-x-executable"],
                      self.rows())

    def test_crlf_no_final_newline_and_desktop_actions(self):
        path = self.desktop(self.user_data)
        path.write_bytes(
            b"[Desktop Entry]\r\nName=Editor\r\nExec=editor %U\r\n"
            b"Icon=editor\r\nTerminal=true\r\nCategories=Development;\r\n"
            b"[Desktop Action New]\r\nName=Wrong\r\nExec=wrong"
        )
        result = self.rebuild()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["Editor", "terminal -e editor", "development", "editor"],
                      self.rows())

    def test_settings_schema_legacy_cache_path_and_pins_are_preserved(self):
        self.cache.parent.mkdir(parents=True)
        (self.cache.parent / "settings_index").write_text(
            'Custom Card;settings --tab wifi --highlight "Custom Card";settings;\n'
        )
        pins = self.home / ".config/smplos/pinned-apps.txt"
        pins.parent.mkdir(parents=True)
        pins.write_text('custom --arg\n"grafium"\n')
        result = self.rebuild(XDG_CACHE_HOME=str(self.home / "other-cache"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            ["Custom Card", 'settings --tab wifi --highlight "Custom Card"',
             "settings", "network-wireless", "1"], self.rows(),
        )
        self.assertEqual(pins.read_text(), 'custom --arg\n"grafium"\n')
        self.assertFalse((self.home / "other-cache/smplos/app_index").exists())

    def settings_rows(self):
        result = self.rebuild()
        self.assertEqual(result.returncode, 0, result.stderr)
        return {row[0]: row for row in self.rows() if row[2] == "settings"}

    def test_settings_browse_list_shows_connections_and_mouse_not_wifi_and_bluetooth(self):
        rows = self.settings_rows()
        self.assertEqual(rows["Connections"], ["Connections", "smplos-settings connections",
                                               "settings", "network-wireless"])
        self.assertEqual(rows["Mouse"], ["Mouse", "smplos-settings mouse", "settings", "input-mouse"])
        browsable = {name for name, row in rows.items() if len(row) == 4}
        self.assertLessEqual({"Connections", "Mouse", "Keypad", "Keyboard", "Display"}, browsable)
        self.assertFalse({"Wi-Fi", "Bluetooth"} & browsable,
                         "both radios live inside the Connections tab now")

    def test_wifi_bluetooth_and_airplane_mode_stay_searchable_and_open_connections(self):
        rows = self.settings_rows()
        for name, icon in (("Wi-Fi", "network-wireless"), ("Wi-Fi Password", "network-wireless"),
                           ("Airplane Mode", "network-wireless"), ("Bluetooth", "bluetooth"),
                           ("Pair Bluetooth", "bluetooth"), ("Headphones", "bluetooth")):
            with self.subTest(name=name):
                self.assertEqual(rows[name], [name, f'settings --tab connections --highlight "{name}"',
                                              "settings", icon, "1"])
        for name, row in rows.items():
            with self.subTest(entry=name):
                self.assertNotRegex(row[1], r"--tab (wifi|bluetooth)\b",
                                    "the standalone tabs are only kept as aliases")

    def test_audio_search_aliases_share_the_mixer_dispatcher_and_stay_search_only(self):
        rows = self.settings_rows()
        self.assertEqual(rows["Audio"], ["Audio", "smplos-settings audio",
                                        "settings", "audio-volume-high"])
        for name in ("Volume", "Sound", "Speakers", "Output Device", "Input Device"):
            with self.subTest(alias=name):
                icon = "audio-input-microphone" if name == "Input Device" else "audio-volume-high"
                self.assertEqual(rows[name], [name, "smplos-settings audio", "settings", icon, "1"])

    def test_settings_index_deep_links_get_an_icon_per_tab_and_section(self):
        self.cache.parent.mkdir(parents=True)
        (self.cache.parent / "settings_index").write_text(
            'Share Wi-Fi;settings --tab connections --highlight "Share Wi-Fi";settings;\n'
            'Bluetooth Radio;settings --tab connections --highlight "Bluetooth Radio";settings;\n'
            'Pointer Speed;settings --tab mouse --highlight "Pointer Speed";settings;\n'
            'Old Radio;settings --tab bluetooth --highlight "Old Radio";settings;\n'
        )
        self.assertEqual(self.rebuild().returncode, 0)
        rows = {row[0]: row for row in self.rows()}
        for name, tab, icon in (("Share Wi-Fi", "connections", "network-wireless"),
                                ("Bluetooth Radio", "connections", "bluetooth"),
                                ("Pointer Speed", "mouse", "input-mouse"),
                                ("Old Radio", "bluetooth", "bluetooth")):
            with self.subTest(name=name):
                self.assertEqual(rows[name], [name, f'settings --tab {tab} --highlight "{name}"',
                                              "settings", icon, "1"])

    def test_scan_failure_preserves_previous_cache_and_reports_error(self):
        self.desktop(self.user_data)
        self.cache.parent.mkdir(parents=True)
        self.cache.write_text("previous-cache\n")
        self.mock_find(fail=True)
        result = self.rebuild()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture scan failed", result.stderr)
        self.assertEqual(self.cache.read_text(), "previous-cache\n")
        self.assertEqual(list(self.cache.parent.glob("app_index.*")), [])

    def test_parallel_rebuilds_publish_complete_cache_without_temp_race(self):
        for number in range(40):
            self.desktop(self.user_data, f"app-{number}.desktop", Name=f"App {number}")
        self.assertEqual(self.rebuild().returncode, 0)
        expected = self.cache.read_bytes()
        children = [
            subprocess.Popen(["bash", str(BUILDER)], env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(12)
        ]
        try:
            deadline = time.monotonic() + 15
            while any(child.poll() is None for child in children):
                self.assertEqual(self.cache.read_bytes(), expected)
                self.assertLess(time.monotonic(), deadline, "cache rebuild timed out")
                time.sleep(0.005)
            for child in children:
                _, stderr = child.communicate(timeout=15)
                self.assertEqual(child.returncode, 0, stderr.decode())
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
                child.communicate(timeout=15)
        self.assertEqual(list(self.cache.parent.glob("app_index.*")), [])

    def test_elevated_refresh_resolves_invoker_and_reexecutes_without_writing_cache(self):
        # Exercise the root-only routing with mocked identity tools; no sudo or
        # real user lookup is needed on an unprivileged test runner.
        prefix = BUILDER.read_text().split('CACHE_DIR="$HOME/.cache/smplos"', 1)[0]
        prefix = prefix.replace("if [[ $EUID -eq 0 ]]; then", "if true; then", 1)
        getent = self.bin / "getent"
        getent.write_text(
            '#!/bin/bash\n[[ "$*" == "passwd 1234" ]] || exit 2\n'
            'printf "desktop:x:1234:1234::%s:/bin/bash\\n" "$HOME"\n'
        )
        getent.chmod(0o755)
        runuser = self.bin / "runuser"
        runuser.write_text('#!/bin/bash\nprintf "<%s>\\n" "$@"\n')
        runuser.chmod(0o755)
        for hint in ("SMPLOS_INVOKER_UID", "PKEXEC_UID", "SUDO_UID"):
            with self.subTest(hint=hint):
                result = subprocess.run(
                    ["bash", "-c", prefix], env={**self.env, hint: "1234"},
                    capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"<-u>\n<desktop>\n<-->\n<env>\n<HOME={self.home}>",
                              result.stdout)
                self.assertFalse(self.cache.exists())
        result = subprocess.run(
            ["bash", "-c", prefix], env={**self.env, "SUDO_UID": "9999"},
            capture_output=True, text=True, timeout=5,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot resolve invoking user", result.stderr)


if __name__ == "__main__":
    unittest.main()
