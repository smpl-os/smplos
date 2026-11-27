from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOGOUT = ROOT / "src/shared/bin/smplos-session-logout"


class SessionLogoutTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bin = Path(tmp.name) / "bin"
        self.bin.mkdir()
        self.calls = Path(tmp.name) / "calls"

    def tool(self, name, body=""):
        path = self.bin / name
        path.write_text(
            f'#!/bin/bash\nprintf "%s %s\\n" "{name}" "$*" >> "$CALLS"\n{body}\n'
        )
        path.chmod(0o755)

    def invoke(self, *arguments, **environment):
        return subprocess.run(
            ["/bin/bash", str(LOGOUT), *arguments],
            env={
                "PATH": str(self.bin),
                "CALLS": str(self.calls),
                **environment,
            },
            capture_output=True,
            text=True,
            timeout=10,
        )

    def recorded(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_refuses_to_log_out_without_ui_confirmation_gate(self):
        self.tool("notify-send")
        result = self.invoke()
        self.assertEqual(result.returncode, 1)
        self.assertIn("requires explicit user confirmation", result.stderr)
        self.assertEqual(self.recorded(), [
            "notify-send -u critical Log out failed "
            "log out requires explicit user confirmation",
        ])

        self.calls.unlink()
        result = self.invoke("--confirmed", "extra")
        self.assertEqual(result.returncode, 1)
        self.assertIn("requires explicit user confirmation", result.stderr)

    def test_confirmed_hyprland_logout_exits_only_the_compositor(self):
        self.tool("hyprctl")
        result = self.invoke(
            "--confirmed",
            HYPRLAND_INSTANCE_SIGNATURE="fixture",
            XDG_SESSION_ID="17",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded(), ["hyprctl dispatch hl.dsp.exit()"])

    def test_confirmed_niri_logout_exits_only_niri(self):
        self.tool("niri")
        result = self.invoke(
            "--confirmed",
            NIRI_SOCKET="/tmp/niri.sock",
            XDG_SESSION_ID="18",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded(), ["niri msg action quit"])

    def test_x11_logout_terminates_the_current_session_only(self):
        self.tool("loginctl")
        result = self.invoke("--confirmed", XDG_SESSION_ID="19")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded(), ["loginctl terminate-session 19"])

    def test_logout_fails_closed_without_a_session_target(self):
        self.tool("notify-send")
        result = self.invoke("--confirmed")
        self.assertEqual(result.returncode, 1)
        self.assertIn("desktop session ID is unavailable", result.stderr)


if __name__ == "__main__":
    unittest.main()
