import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOGGLE = ROOT / "src/shared/bin/toggle-messenger"
MOCK_HYPRCTL = r"""#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path

path = Path(os.environ["TEST_STATE"])
state = json.loads(path.read_text())
args = sys.argv[1:]
with open(os.environ["TEST_CALLS"], "a") as log:
    log.write(json.dumps(args) + "\n")

def client(address):
    return next(w for w in state["clients"] if w["address"] == address)

def focus(address):
    state["active"] = address
    state["monitor"] = client(address)["monitor"]

if "monitors" in args:
    for m in state["monitors"]:
        m["focused"] = m["id"] == state["monitor"]
    print(json.dumps(state["monitors"]))
elif "clients" in args:
    print(json.dumps(state["clients"]))
elif "activewindow" in args:
    print(json.dumps(next((w for w in state["clients"] if w["address"] == state["active"]), {})))
elif "activeworkspace" in args:
    print(json.dumps(state["monitors"][state["monitor"]]["activeWorkspace"]))
elif "cursorpos" in args:
    print("3222, 1101")
elif args[0] == "dispatch":
    command = args[1]
    address = re.search(r"address:(0x[0-9a-f]+)", command)
    if ".focus(" in command:
        focus(address[1])
    elif ".window.move(" in command and "workspace=" in command:
        w = client(address[1])
        workspace = re.search(r"workspace='([^']+)'", command)[1]
        if workspace.startswith("special:"):
            w["workspace"] = {"id": -97, "name": workspace}
            state["monitors"][w["monitor"]]["specialWorkspace"] = w["workspace"]
            focus(w["address"])
        else:
            w["workspace"] = {"id": int(workspace), "name": workspace}
            w["monitor"] = next(m["id"] for m in state["monitors"]
                                if m["activeWorkspace"]["id"] == int(workspace))
            focus(w["address"])
    elif ".window.move(" in command:
        client(address[1])["at"] = [
            int(re.search(r"x=(-?\d+)", command)[1]),
            int(re.search(r"y=(-?\d+)", command)[1]),
        ]
    elif ".window.resize(" in command:
        client(address[1])["size"] = [
            int(re.search(r"x=(\d+)", command)[1]),
            int(re.search(r"y=(\d+)", command)[1]),
        ]
    elif ".workspace.toggle_special(" in command:
        for m in state["monitors"]:
            m["specialWorkspace"] = {"id": 0, "name": ""}
        # Reproduce the compositor's unwanted cross-monitor fallback.
        focus("0x30")
        if state.get("switch_during_hide"):
            state["monitors"][0]["activeWorkspace"] = {"id": 3, "name": "3"}
    path.write_text(json.dumps(state))
    print("ok")
else:
    sys.exit(2)
"""


class MessengerFocusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        mocks = self.home / "bin"
        mocks.mkdir()
        hyprctl = mocks / "hyprctl"
        hyprctl.write_text(MOCK_HYPRCTL)
        hyprctl.chmod(0o755)
        self.state_path = self.home / "state.json"
        self.calls_path = self.home / "calls.jsonl"
        self.calls_path.touch()
        self.runtime = self.home / "runtime"
        self.focus_state = self.runtime / "toggle-messenger-messenger_signal.focus.json"
        self.env = {
            **os.environ, "HOME": str(self.home), "NIRI_SOCKET": "",
            "XDG_RUNTIME_DIR": str(self.runtime),
            "PATH": f"{mocks}:{os.environ['PATH']}",
            "TEST_STATE": str(self.state_path), "TEST_CALLS": str(self.calls_path),
        }
        self.save({
            "active": "0x10", "monitor": 0,
            "monitors": [
                {"id": 0, "x": 0, "y": 0, "width": 2560, "height": 1440,
                 "scale": 1, "transform": 0, "activeWorkspace": {"id": 2, "name": "2"},
                 "specialWorkspace": {"id": 0, "name": ""}},
                {"id": 1, "x": 2560, "y": 0, "width": 1920, "height": 1080,
                 "scale": 1, "transform": 1, "activeWorkspace": {"id": 1, "name": "1"},
                 "specialWorkspace": {"id": 0, "name": ""}},
            ],
            "clients": [
                {"address": "0x10", "class": "nemo", "mapped": True, "monitor": 0,
                 "workspace": {"id": 2, "name": "2"}},
                {"address": "0x20", "class": "signal", "mapped": True, "monitor": 1,
                 "workspace": {"id": -97, "name": "special:messenger_signal"}},
                {"address": "0x30", "class": "brave-browser", "mapped": True, "monitor": 1,
                 "workspace": {"id": 1, "name": "1"}},
            ],
        })

    def save(self, state):
        self.state_path.write_text(json.dumps(state))

    def state(self):
        return json.loads(self.state_path.read_text())

    def calls(self):
        return [json.loads(line) for line in self.calls_path.read_text().splitlines()]

    def toggle(self):
        subprocess.run(
            [str(TOGGLE), "signal", "signal-desktop"], env=self.env,
            capture_output=True, text=True, check=True, timeout=5,
        )

    def test_show_uses_keyboard_monitor_and_workspace_not_pointer_monitor(self):
        self.toggle()
        signal = self.state()["clients"][1]
        self.assertEqual(signal["workspace"]["id"], 2)
        self.assertEqual(signal["monitor"], 0)
        self.assertEqual(signal["at"], [2078, 686])
        self.assertEqual(json.loads(self.focus_state.read_text())["address"], "0x10")
        self.assertNotIn(["cursorpos"], self.calls())

    def test_hide_restores_exact_previous_window_before_and_after_special_hide(self):
        self.toggle()
        self.toggle()
        self.assertEqual(self.state()["active"], "0x10")
        self.assertEqual(self.state()["monitor"], 0)
        self.assertEqual(self.state()["clients"][1]["workspace"]["name"], "special:messenger_signal")
        focus_calls = [c for c in self.calls() if c[0] == "dispatch" and ".focus(" in c[1]]
        self.assertEqual(sum("address:0x10" in c[1] for c in focus_calls), 2)
        self.assertFalse(self.focus_state.exists())

    def notification_focus(self):
        state = self.state()
        state.update(active="0x20", monitor=0)
        state["clients"][1]["monitor"] = 0
        state["monitors"][0]["specialWorkspace"] = state["clients"][1]["workspace"]
        state["clients"][0]["focusHistoryID"] = 2
        state["clients"].append({
            "address": "0x40", "class": "terminal", "mapped": True, "monitor": 0,
            "workspace": {"id": 2, "name": "2"}, "focusHistoryID": 1,
        })
        self.save(state)

    def test_notification_revealed_special_returns_to_mru_not_first_window(self):
        self.notification_focus()
        self.toggle()
        self.assertEqual(json.loads(self.focus_state.read_text())["address"], "0x40")
        self.toggle()
        self.assertEqual(self.state()["active"], "0x40")
        self.assertEqual(self.state()["clients"][1]["workspace"]["name"], "special:messenger_signal")

    def test_notification_on_normal_workspace_without_saved_focus_recovers_mru(self):
        self.notification_focus()
        state = self.state()
        state["clients"][1]["workspace"] = {"id": 2, "name": "2"}
        state["monitors"][0]["specialWorkspace"] = {"id": 0, "name": ""}
        self.save(state)
        self.toggle()
        self.assertEqual(self.state()["active"], "0x40")

    def test_legacy_saved_self_focus_is_recovered(self):
        self.notification_focus()
        state = self.state()
        state["clients"][1]["workspace"] = {"id": 2, "name": "2"}
        state["monitors"][0]["specialWorkspace"] = {"id": 0, "name": ""}
        self.save(state)
        self.runtime.mkdir()
        self.focus_state.write_text(json.dumps({
            "address": "0x20", "workspace": -97, "monitor": 0,
        }))
        self.toggle()
        self.assertEqual(self.state()["active"], "0x40")

    def test_notification_focus_history_excludes_hidden_and_other_workspace_windows(self):
        self.notification_focus()
        state = self.state()
        state["clients"].extend([
            {"address": "0x50", "mapped": True, "hidden": True, "monitor": 0,
             "workspace": {"id": 2, "name": "2"}, "focusHistoryID": 0},
            {"address": "0x60", "mapped": True, "monitor": 0,
             "workspace": {"id": 3, "name": "3"}, "focusHistoryID": 0},
        ])
        self.save(state)
        self.toggle()
        self.toggle()
        self.assertEqual(self.state()["active"], "0x40")

    def test_portrait_monitor_geometry_stays_correct(self):
        state = self.state()
        state.update(active="0x30", monitor=1)
        self.save(state)
        self.toggle()
        self.assertEqual(self.state()["clients"][1]["workspace"]["id"], 1)
        self.assertEqual(self.state()["clients"][1]["at"], [3158, 1166])
        self.toggle()
        self.assertEqual(self.state()["active"], "0x30")

    def test_hiding_while_another_app_is_focused_does_not_restore_stale_focus(self):
        self.toggle()
        state = self.state()
        state.update(active="0x30", monitor=1)
        self.save(state)
        self.toggle()
        self.assertEqual(self.state()["active"], "0x30")
        self.assertFalse(any(c[0] == "dispatch" and "focus({window='address:0x10'" in c[1]
                             for c in self.calls()))

    def assert_previous_window_change_is_respected(self, removed):
        self.toggle()
        state = self.state()
        if removed:
            state["clients"] = state["clients"][1:]
        else:
            state["clients"][0]["workspace"] = {"id": 4, "name": "4"}
        self.save(state)
        self.toggle()
        self.assertEqual(self.state()["active"], "0x30")

    def test_closed_previous_window_is_not_restored(self):
        self.assert_previous_window_change_is_respected(removed=True)

    def test_moved_previous_window_is_not_restored(self):
        self.assert_previous_window_change_is_respected(removed=False)

    def test_does_not_reopen_workspace_changed_during_dismissal(self):
        self.toggle()
        state = self.state()
        state["switch_during_hide"] = True
        self.save(state)
        self.toggle()
        self.assertEqual(self.state()["monitors"][0]["activeWorkspace"]["id"], 3)
        self.assertEqual(self.state()["active"], "0x30")

    def test_cold_launch_remembers_focus_too(self):
        state = self.state()
        state["clients"] = [w for w in state["clients"] if w["class"] != "signal"]
        self.save(state)
        self.toggle()
        self.assertEqual(json.loads(self.focus_state.read_text())["address"], "0x10")
        self.assertTrue(any(c[0] == "dispatch" and "hl.dsp.exec_cmd" in c[1] for c in self.calls()))

    def fit_calls(self):
        return [c for c in self.calls() if c[:2] == ["smplhud", "fit"]]

    def test_show_asks_the_hud_plugin_to_fit_the_frame_once_the_window_is_placed(self):
        self.toggle()
        calls = self.calls()
        self.assertEqual(self.fit_calls(), [["smplhud", "fit", "0x20"]])
        placed = max(i for i, c in enumerate(calls)
                     if c[0] == "dispatch" and ".window.move(" in c[1] and "x=" in c[1])
        asked = calls.index(["smplhud", "fit", "0x20"])
        focused = next(i for i, c in enumerate(calls)
                       if c[0] == "dispatch" and ".focus(" in c[1] and "address:0x20" in c[1])
        self.assertLess(placed, asked)
        self.assertLess(asked, focused)

    def test_only_showing_asks_for_a_fit(self):
        self.toggle()
        self.toggle()
        self.assertEqual(len(self.fit_calls()), 1)

        # A cold launch is placed by the window rules and by the plugin when the window opens.
        state = self.state()
        state["clients"] = [w for w in state["clients"] if w["class"] != "signal"]
        self.save(state)
        self.toggle()
        self.assertEqual(len(self.fit_calls()), 1)

    def add_stashed_browser(self):
        state = self.state()
        state["clients"].append({
            "address": "0x40", "class": "brave-private", "mapped": True, "monitor": 1,
            "workspace": {"id": -97, "name": "special:messenger_signal"},
        })
        self.save(state)

    def assert_browser_recovered_and_focus_preserved(self):
        recovered = next(w for w in self.state()["clients"] if w["address"] == "0x40")
        self.assertEqual(recovered["workspace"]["id"], 2)
        self.assertEqual(self.state()["active"], "0x10")

    def test_recovering_stashed_window_on_show_preserves_return_focus(self):
        self.add_stashed_browser()
        self.toggle()
        self.assertEqual(json.loads(self.focus_state.read_text())["address"], "0x10")
        self.toggle()
        self.assert_browser_recovered_and_focus_preserved()

    def test_recovering_stashed_window_on_hide_preserves_return_focus(self):
        self.toggle()
        self.add_stashed_browser()
        self.toggle()
        self.assert_browser_recovered_and_focus_preserved()


if __name__ == "__main__":
    unittest.main()
