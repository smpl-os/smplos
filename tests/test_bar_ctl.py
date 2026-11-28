"""Native-only bar-ctl validation and Settings apply contract."""

import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BAR_CTL = ROOT / "src/shared/bin/bar-ctl"


class BarCtlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".bar-ctl-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.bin = self.root / "bin"
        (self.home / ".config/smplos").mkdir(parents=True)
        self.bin.mkdir()
        self.calls = self.root / "calls"
        self.env = {
            **os.environ, "HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin",
            "CALLS": str(self.calls), "XDG_RUNTIME_DIR": str(self.root / "runtime"),
            "XDG_STATE_HOME": str(self.root / "state"),
        }
        native = self.bin / "smpl-bar"
        native.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n')
        native.chmod(native.stat().st_mode | stat.S_IXUSR)

    def conf(self, text=""):
        (self.home / ".config/smplos/bar.conf").write_text(text)

    def invoke_bar(self, action="apply"):
        return subprocess.run(["bash", str(BAR_CTL), action], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def test_backend_is_always_native(self):
        result = self.invoke_bar("backend")
        self.assertEqual((result.returncode, result.stdout), (0, "smpl-bar\n"))
        self.conf("backend=eww\n")
        self.assertEqual(self.invoke_bar("backend").stdout, "smpl-bar\n")

    def test_all_settings_are_validated_then_applied_by_native_ipc(self):
        settings = (
            "ws_count=10\nws_position=left\nws_spacing=10\nws_style=squares\n"
            "clock_format=date\nclock_24h=true\nclock_date_fmt=Mon D\n"
            "bar_edge=left\nbar_mode=floating\nbar_margin=24\n"
        )
        self.conf(settings)
        result = self.invoke_bar()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls.read_text(), "apply\n")
        self.assertEqual((self.home / ".config/smplos/bar.conf").read_text(), settings)

    def test_every_choice_and_taskbar_geometry_value_has_a_native_contract(self):
        valid = {
            "ws_position": ("center", "left"), "ws_style": ("numbers", "squares"),
            "clock_format": ("time", "dow", "date"), "clock_24h": ("auto", "true", "false"),
            "clock_date_fmt": ("auto", "M/D", "D/M", "ISO", "Mon D"),
            "bar_edge": ("top", "bottom", "left", "right"),
            "bar_mode": ("pinned", "floating"),
        }
        for key, choices in valid.items():
            for value in choices:
                with self.subTest(key=key, value=value):
                    self.calls.unlink(missing_ok=True)
                    self.conf(f"{key}={value}\n")
                    self.assertEqual(self.invoke_bar().returncode, 0)
                    self.assertEqual(self.calls.read_text(), "apply\n")

    def test_invalid_or_duplicate_settings_fail_without_native_apply(self):
        fixtures = (
            "ws_count=11\n", "ws_spacing=0\n", "ws_position=right\n",
            "ws_style=circles\n", "clock_format=full\n", "clock_24h=yes\n",
            "clock_date_fmt=European\n", "bar_edge=side\n", "bar_mode=overlay\n",
            "bar_margin=25\n", "bar_edge=top\n bar_edge=bottom\n",
        )
        for contents in fixtures:
            with self.subTest(contents=contents):
                self.calls.unlink(missing_ok=True)
                self.conf(contents)
                self.assertNotEqual(self.invoke_bar().returncode, 0)
                self.assertFalse(self.calls.exists())

    def test_unreadable_config_type_fails_closed(self):
        (self.home / ".config/smplos/bar.conf").mkdir()
        result = self.invoke_bar()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot read", result.stderr)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
