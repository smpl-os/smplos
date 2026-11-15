"""Audio launcher selection with fake mixers; no desktop or audio-device access."""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "src/shared/bin/smplos-settings"
GUI_MIXERS = ("pavucontrol", "pwvucontrol", "pavucontrol-qt", "qasmixer", "alsamixergui")
TUI_MIXERS = ("wiremix", "pulsemixer", "ncpamixer", "pamix", "alsamixer")


class AudioSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        self.env = {
            "PATH": str(self.bin),
            "HOME": str(self.root),
            "CALLS": str(self.calls),
        }
        self.tool("notify-send")

    def tool(self, name, body=""):
        path = self.bin / name
        path.write_text(
            f"#!/bin/sh\nprintf '%s\\n' '{name}' \"$@\" >> \"$CALLS\"\n{body}\n"
        )
        path.chmod(0o755)
        return path

    def terminal(self):
        self.tool("terminal", '[ "$1" = "-e" ] || exit 99\nshift\nexec "$@"')

    def run_audio(self):
        return subprocess.run(
            ["/bin/bash", str(SETTINGS), "audio"],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def calls_made(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_each_graphical_mixer_opens_without_a_terminal(self):
        for mixer in GUI_MIXERS:
            with self.subTest(mixer=mixer):
                path = self.tool(mixer)
                result = self.run_audio()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls_made(), [mixer])
                path.unlink()
                self.calls.unlink()

    def test_each_terminal_mixer_opens_inside_the_terminal(self):
        self.terminal()
        for mixer in TUI_MIXERS:
            with self.subTest(mixer=mixer):
                path = self.tool(mixer)
                result = self.run_audio()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls_made(), ["terminal", "-e", mixer, mixer])
                path.unlink()
                self.calls.unlink()

    def test_graphical_preference_and_fallback_order(self):
        for mixer in (*GUI_MIXERS, *TUI_MIXERS):
            self.tool(mixer)
        for mixer in GUI_MIXERS:
            with self.subTest(mixer=mixer):
                result = self.run_audio()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls_made(), [mixer])
                (self.bin / mixer).unlink()
                self.calls.unlink()

    def test_terminal_preference_and_fallback_order(self):
        self.terminal()
        for mixer in TUI_MIXERS:
            self.tool(mixer)
        for mixer in TUI_MIXERS:
            with self.subTest(mixer=mixer):
                result = self.run_audio()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls_made(), ["terminal", "-e", mixer, mixer])
                (self.bin / mixer).unlink()
                self.calls.unlink()

    def test_missing_mixers_report_an_actionable_failure(self):
        result = self.run_audio()
        self.assertEqual(result.returncode, 1)
        self.assertIn("no supported audio mixer found", result.stderr)
        self.assertEqual(
            self.calls_made(),
            ["notify-send", "smplOS Settings",
             "No audio mixer found (install pavucontrol, pwvucontrol, pulsemixer or alsa-utils)"],
        )

    def test_terminal_mixer_without_terminal_reports_the_missing_launcher(self):
        self.tool("alsamixer")
        result = self.run_audio()
        self.assertEqual(result.returncode, 1)
        self.assertIn("terminal launcher is missing (needed for alsamixer)", result.stderr)
        self.assertEqual(
            self.calls_made(),
            ["notify-send", "smplOS Settings", "Terminal launcher not found (needed for alsamixer)"],
        )

    def test_mixer_errors_are_not_hidden_by_starting_another_mixer(self):
        self.tool("pavucontrol", "echo 'mixer failed' >&2\nexit 42")
        self.tool("pwvucontrol")
        result = self.run_audio()
        self.assertEqual(result.returncode, 42)
        self.assertIn("mixer failed", result.stderr)
        self.assertEqual(self.calls_made(), ["pavucontrol"])

    def test_terminal_errors_are_not_hidden(self):
        self.tool("terminal", "echo 'terminal failed' >&2\nexit 43")
        self.tool("alsamixer")
        result = self.run_audio()
        self.assertEqual(result.returncode, 43)
        self.assertIn("terminal failed", result.stderr)
        self.assertEqual(self.calls_made(), ["terminal", "-e", "alsamixer"])

    def test_volume_bar_right_click_uses_the_same_audio_fallback(self):
        bar = (ROOT / "src/shared/eww/eww.yuck").read_text()
        widget = re.search(r"^\(defwidget tray-volume \[\]\n.*?(?=^\(defwidget |\Z)",
                           bar, re.M | re.S)
        self.assertIsNotNone(widget)
        action = re.search(r':onrightclick "([^"]+)"', widget.group())
        self.assertIsNotNone(action)
        self.assertEqual(action[1], "smplos-settings audio &")
        launcher = self.bin / "smplos-settings"
        launcher.write_bytes(SETTINGS.read_bytes())
        launcher.chmod(0o755)
        self.terminal()
        self.tool("alsamixer")
        result = subprocess.run(
            ["/bin/bash", "-c", action[1] + ' wait "$!"'], env=self.env,
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls_made(), ["terminal", "-e", "alsamixer", "alsamixer"])


if __name__ == "__main__":
    unittest.main()
