"""popup-toggle places popups on the primary monitor, with mocked EWW and no desktop access."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/shared/bin/popup-toggle"

MOCK_EWW = f"""#!{sys.executable}
import json, os, sys
args = sys.argv[3:]
with open(os.environ["CALLS"], "a") as out:
    out.write(json.dumps(args) + "\\n")
if args[0] == "active-windows":
    for name in filter(None, os.environ["OPEN_WINDOWS"].split(",")):
        print(f"{{name}}: {{name}}")
elif args[0] == "get":
    if not os.environ["OVERVIEW_STATE"]:
        sys.exit(1)
    print(os.environ["OVERVIEW_STATE"])
elif args[0] == "open" and "--screen" in args and os.environ.get("FAIL_SCREEN") == "1":
    print("mock: unknown monitor", file=sys.stderr)
    sys.exit(18)
"""

MOCK_WORKSPACE_CTL = """#!/bin/sh
printf '["workspace-ctl", "%s"]\\n' "$1" >> "$CALLS"
[ -z "$PRIMARY_DELAY" ] || sleep "$PRIMARY_DELAY"
if [ -z "$PRIMARY" ]; then
    echo "workspace-ctl: Stable workspace policy is not enabled" >&2
    exit 1
fi
echo "$PRIMARY"
"""


class PopupToggleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = self.root / "calls"
        self.mock_bin = self.root / "bin"
        self.mock_bin.mkdir()
        for name, body in (("eww", MOCK_EWW), ("workspace-ctl", MOCK_WORKSPACE_CTL),
                           # Closing a popup warps the pointer; never reach a real compositor.
                           ("hyprctl", "#!/bin/sh\nexit 1\n")):
            mock = self.mock_bin / name
            mock.write_text(body)
            mock.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.root), CALLS=str(self.calls),
                        PATH=f"{self.mock_bin}:{os.environ['PATH']}", PRIMARY="",
                        PRIMARY_DELAY="", OPEN_WINDOWS="", OVERVIEW_STATE='{"workspaces": []}')
        for key in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "NIRI_SOCKET"):
            self.env.pop(key, None)

    def toggle(self, *args, **env):
        return subprocess.run(["bash", str(SCRIPT), *args], env={**self.env, **env},
                              capture_output=True, text=True, timeout=15)

    def recorded(self):
        if not self.calls.exists():
            return []
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def calls_of(self, verb):
        return [call for call in self.recorded() if call[0] == verb]

    def window_changes(self):
        return [call for call in self.recorded() if call[0] in ("open", "close")]

    def test_every_popup_opens_on_the_primary_monitor(self):
        for window in ("calendar-popup", "quick-settings", "notification-hub", "usb-popup"):
            with self.subTest(window=window):
                self.calls.unlink(missing_ok=True)
                result = self.toggle(window, PRIMARY="DP-3")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls_of("open"), [["open", window, "--screen", "DP-3"]])
                self.assertEqual(self.calls_of("workspace-ctl"), [["workspace-ctl", "primary"]])

    def test_overview_keeps_its_state_argument_and_opens_on_the_primary_monitor(self):
        result = self.toggle("workspace-overview", PRIMARY="HDMI-A-1", OVERVIEW_STATE='{"a": 1}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls_of("open"), [[
            "open", "workspace-overview", "--arg", 'overview-state={"a": 1}', "--screen", "HDMI-A-1"]])

    def test_unknown_primary_opens_on_the_default_monitor_without_noise(self):
        for window, expected in (("calendar-popup", ["open", "calendar-popup"]),
                                 ("workspace-overview", ["open", "workspace-overview", "--arg",
                                                         'overview-state={"workspaces": []}'])):
            with self.subTest(window=window):
                self.calls.unlink(missing_ok=True)
                result = self.toggle(window)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(self.calls_of("open"), [expected])

    def test_unaddressable_primary_falls_back_to_a_plain_open(self):
        result = self.toggle("calendar-popup", PRIMARY="DP-3", FAIL_SCREEN="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls_of("open"), [["open", "calendar-popup", "--screen", "DP-3"],
                                                 ["open", "calendar-popup"]])

    def test_other_popups_close_before_the_new_popup_opens_on_the_primary_monitor(self):
        result = self.toggle("calendar-popup", PRIMARY="DP-3", OPEN_WINDOWS="usb-popup,notification-hub")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.window_changes(), [["close", "notification-hub"], ["close", "usb-popup"],
                                                 ["open", "calendar-popup", "--screen", "DP-3"]])

    def test_closing_an_open_popup_neither_looks_up_the_primary_nor_reopens(self):
        result = self.toggle("calendar-popup", PRIMARY="DP-3", OPEN_WINDOWS="calendar-popup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.window_changes(), [["close", "calendar-popup"]])
        self.assertEqual(self.calls_of("workspace-ctl"), [])

    def test_close_all_never_looks_up_the_primary(self):
        result = self.toggle("--close", PRIMARY="DP-3", OPEN_WINDOWS="usb-popup,calendar-popup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.window_changes(), [["close", "calendar-popup"], ["close", "usb-popup"]])
        self.assertEqual(self.calls_of("workspace-ctl"), [])

    def test_unreadable_overview_state_fails_before_any_window_opens(self):
        result = self.toggle("workspace-overview", PRIMARY="DP-3", OVERVIEW_STATE="")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Cannot read workspace overview state", result.stderr)
        self.assertEqual(self.calls_of("open"), [])

    def test_missing_workspace_ctl_opens_on_the_default_monitor_silently(self):
        (self.mock_bin / "workspace-ctl").unlink()
        system_path = "/usr/bin:/bin"
        if shutil.which("workspace-ctl", path=system_path):
            self.skipTest("a system workspace-ctl would be found instead of the missing one")
        result = self.toggle("calendar-popup", PATH=f"{self.mock_bin}:{system_path}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.calls_of("open"), [["open", "calendar-popup"]])

    def test_a_stuck_primary_lookup_delays_the_popup_by_a_bounded_time(self):
        started = time.monotonic()
        process = subprocess.Popen(["bash", str(SCRIPT), "calendar-popup"],
                                   env={**self.env, "PRIMARY": "DP-3", "PRIMARY_DELAY": "8"},
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.assertEqual(process.wait(timeout=6), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        self.assertLess(time.monotonic() - started, 6)
        self.assertEqual(self.calls_of("open"), [["open", "calendar-popup"]])


if __name__ == "__main__":
    unittest.main()
