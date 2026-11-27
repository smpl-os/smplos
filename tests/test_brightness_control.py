import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/shared/bin/brightness-ctl"


class BrightnessControlTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.call_log = self.root / "calls"
        self.env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "CALLS": str(self.call_log),
            "HOME": str(self.root),
        }

    def tool(self, name, body="exit 0"):
        path = self.bin / name
        path.write_text(
            f'#!/bin/bash\nprintf "%s %s\\n" "{name}" "$*" >> "$CALLS"\n{body}\n'
        )
        path.chmod(0o755)

    def invoke(self, *args):
        return subprocess.run(
            ["/bin/bash", str(SCRIPT), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def recorded(self):
        return (
            self.call_log.read_text().splitlines()
            if self.call_log.exists()
            else []
        )

    def test_ddc_fallback_sets_and_reads_external_monitor_brightness(self):
        self.tool("notify-send")
        self.tool(
            "ddcutil",
            """
case "$1" in
    detect)
        cat <<'EOF'
Display 1
   I2C bus: /dev/i2c-4
   DRM_connector: card1-HDMI-A-1
   VCP version: 2.2
Invalid display
   I2C bus: /dev/i2c-5
   DRM_connector: card1-DP-3
   DDC communication failed
EOF
        ;;
    --display)
        if [[ "$3" == getvcp ]]; then
            echo 'VCP 10 C 42 100'
        fi
        ;;
esac
""",
        )
        result = self.invoke("42", "set")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ddcutil --display 1 setvcp 10 42", self.recorded())
        self.assertIn(
            "notify-send Brightness 42% -h int:value:42 -t 1000",
            self.recorded(),
        )

    def test_no_supported_backend_reports_a_real_error(self):
        self.tool("notify-send")
        self.tool("ddcutil", "exit 1")
        result = self.invoke("42", "set")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No supported backlight or DDC/CI monitor", result.stderr)


if __name__ == "__main__":
    unittest.main()
