"""bar-ctl apply contract, with private HOME and no desktop/IPC access."""

import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
Policy = runpy.run_path(str(ROOT / "src/shared/bin/workspace-ctl"))["Policy"]


class BarApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / ".config/eww"
        (self.config / "scripts").mkdir(parents=True)
        for name in ("eww.yuck", "eww.scss", "theme-colors.scss"):
            (self.config / name).touch()
        self.conf = self.root / ".config/smplos/bar.conf"
        self.conf.parent.mkdir()
        self.log = self.root / "bar.log"
        self.calls = self.root / "calls"
        self.script = self.root / "bar-ctl"
        # Redirect the legacy shared startup log; nothing touches the real HOME.
        self.script.write_text((ROOT / "src/shared/bin/bar-ctl").read_text().replace(
            'LOG="/tmp/eww-startup.log"', f'LOG="{self.log}"'))
        mock_bin = self.root / "bin"
        mock_bin.mkdir()
        eww = mock_bin / "eww"
        eww.write_text(
            "#!/usr/bin/env python3\nimport json, os, sys\n"
            "with open(os.environ['CALLS'], 'a') as out:\n"
            "    out.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if os.environ.get('FAIL_EWW') == '1':\n"
            "    print('mock: EWW connection failed', file=sys.stderr)\n"
            "    sys.exit(17)\n")
        eww.chmod(0o755)
        watcher = mock_bin / "inotifywait"
        watcher.write_text("#!/bin/sh\nexit 0\n")
        watcher.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.root), PATH=f"{mock_bin}:{os.environ['PATH']}",
                        CALLS=str(self.calls))
        for key in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE",
                    "NIRI_SOCKET", "DBUS_SESSION_BUS_ADDRESS"):
            self.env.pop(key, None)

    def run_apply(self, **env):
        return subprocess.run(["bash", str(self.script), "apply"],
                              env=dict(self.env, **env), capture_output=True, text=True, timeout=10)

    def read_legacy_count(self):
        return subprocess.run(["bash", str(ROOT / "src/shared/eww/scripts/workspace-count.sh")],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def read_policy_count(self):
        return Policy(backend=object(), config_dir=self.conf.parent,
                      runtime_dir=self.root / "runtime").configured_count()

    def assert_update(self, count="4", position="center", spacing="1", style="numbers"):
        self.assertEqual([json.loads(line) for line in self.calls.read_text().splitlines()], [[
            "--config", str(self.config), "update", f"ws-count={count}", f"ws-position={position}",
            f"ws-spacing={spacing}", f"ws-style={style}",
        ]])

    def test_missing_file_uses_existing_defaults_in_one_update(self):
        self.assertEqual(self.run_apply().returncode, 0)
        self.assert_update()
        self.assertFalse(self.conf.exists())

    def test_all_preferences_and_unrelated_clock_keys(self):
        contents = "# user comment\nws_count=7\nclock_date_fmt=Mon D\nws_position=left\nws_spacing=10\nws_style=squares"
        self.conf.write_text(contents)
        self.assertEqual(self.run_apply().returncode, 0)
        self.assert_update("7", "left", "10", "squares")
        self.assertEqual(self.conf.read_text(), contents)

    def test_each_valid_spacing_and_count_boundary(self):
        for spacing in range(1, 11):
            self.conf.write_text(f"ws_count=10\nws_spacing={spacing}\n")
            self.calls.unlink(missing_ok=True)
            self.assertEqual(self.run_apply().returncode, 0)
            self.assert_update(count="10", spacing=str(spacing))
        self.conf.write_text("ws_count=1\n")
        self.calls.unlink()
        self.assertEqual(self.run_apply().returncode, 0)
        self.assert_update(count="1")

    def test_invalid_preferences_never_update_any_variable(self):
        for key, values in (
            ("ws_count", ("0", "11", "-1", "1.5", "1 0", "no", "")),
            ("ws_spacing", ("0", "11", "-1", "1.5", "1 0", "no", "")),
            ("ws_position", ("right", "")),
            ("ws_style", ("circles", "")),
        ):
            for value in values:
                with self.subTest(key=key, value=value):
                    self.conf.write_text(f"{key}={value}\n")
                    result = self.run_apply()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"Invalid {key}", result.stderr)
                    self.assertFalse(self.calls.exists())
                    self.assertNotIn("bar-ctl apply: ws_count=", self.log.read_text())

    def test_duplicate_managed_preferences_are_rejected(self):
        for key, value in (("ws_count", "7"), ("ws_spacing", "2"),
                           ("ws_position", "left"), ("ws_style", "squares")):
            with self.subTest(key=key):
                self.conf.write_text(f"{key}={value}\n {key} = {value}\n")
                result = self.run_apply()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"Duplicate {key}", result.stderr)
                self.assertFalse(self.calls.exists())

    def test_count_readers_share_whitespace_comment_and_crlf_grammar(self):
        fixtures = (
            ("", 4),
            ("# ws_count=9\n \t# ws_count = 8\r\n", 4),
            ("ws_count=7", 7),
            (" \tws_count \t= \t7 \t\r\n", 7),
            ("\r\n# user prefs\r\nclock_date_fmt=Mon D\r\n ws_count = 7 \r\n", 7),
            ("ws_ count=7\nws_co\tunt=8\n", 4),
        )
        for contents, count in fixtures:
            with self.subTest(contents=contents):
                self.conf.write_bytes(contents.encode())
                self.calls.unlink(missing_ok=True)
                self.assertEqual(self.run_apply().returncode, 0)
                self.assert_update(count=str(count))
                self.assertEqual(self.read_policy_count(), count)
                legacy = self.read_legacy_count()
                self.assertEqual(legacy.returncode, 0, legacy.stderr)
                self.assertEqual(legacy.stdout.strip(), str(count))
                self.assertEqual(self.conf.read_bytes(), contents.encode())

    def test_count_readers_report_invalid_values_and_duplicates(self):
        for contents in ("ws_count=1 0\n", "ws_count=1\t0\n", "ws_count=1_0\n",
                         "ws_count=no\n", "ws_count=\n", "ws_count\n",
                         "ws_count=7\n ws_count = 8\r\n"):
            with self.subTest(contents=contents):
                self.conf.write_text(contents)
                applied = self.run_apply()
                self.assertNotEqual(applied.returncode, 0)
                self.assertIn("ws_count", applied.stderr)
                self.assertFalse(self.calls.exists())
                with self.assertRaises(ValueError):
                    self.read_policy_count()
                legacy = self.read_legacy_count()
                self.assertNotEqual(legacy.returncode, 0)
                self.assertIn("ws_count", legacy.stderr)
                self.assertEqual(legacy.stdout, "")

    def test_count_readers_keep_their_existing_ranges(self):
        for value, policy_count, legacy_count in (("0", None, 1), ("11", 11, 10), ("100", 100, 10)):
            with self.subTest(value=value):
                self.conf.write_text(f"ws_count={value}\n")
                self.assertNotEqual(self.run_apply().returncode, 0)
                if policy_count is None:
                    with self.assertRaises(ValueError):
                        self.read_policy_count()
                else:
                    self.assertEqual(self.read_policy_count(), policy_count)
                legacy = self.read_legacy_count()
                self.assertEqual(legacy.returncode, 0, legacy.stderr)
                self.assertEqual(legacy.stdout.strip(), str(legacy_count))

    def test_unreadable_config_type_reports_error(self):
        self.conf.mkdir()
        result = self.run_apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot read", result.stderr)
        self.assertFalse(self.calls.exists())
        with self.assertRaises(OSError):
            self.read_policy_count()
        legacy = self.read_legacy_count()
        self.assertNotEqual(legacy.returncode, 0)
        self.assertIn("Cannot read", legacy.stderr)
        self.assertEqual(legacy.stdout, "")

    def test_eww_failure_propagates_without_success_log(self):
        result = self.run_apply(FAIL_EWW="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mock: EWW connection failed", result.stderr)
        self.assertIn("saved preferences have not been applied", result.stderr)
        self.assertNotIn("bar-ctl apply: ws_count=", self.log.read_text())
        self.assert_update()

    def test_compositor_variables_do_not_dispatch_or_change_contract(self):
        for variables in ({}, {"NIRI_SOCKET": "test"}, {"HYPRLAND_INSTANCE_SIGNATURE": "test"}):
            self.calls.unlink(missing_ok=True)
            self.assertEqual(self.run_apply(**variables).returncode, 0)
            self.assert_update()


if __name__ == "__main__":
    unittest.main()
