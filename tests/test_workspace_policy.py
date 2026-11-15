import copy
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "src/shared/bin/workspace-ctl"
loader = importlib.machinery.SourceFileLoader("workspace_policy", str(CONTROLLER))
spec = importlib.util.spec_from_loader(loader.name, loader)
policy_module = importlib.util.module_from_spec(spec)
loader.exec_module(policy_module)


def monitor(index, connector, workspace, x=0, y=0, width=1920, height=1080, transform=0, serial=None):
    return {
        "id": index, "name": connector, "make": "Test", "model": "Panel",
        "serial": serial or f"serial-{index}", "description": f"Test panel {index}",
        "x": x, "y": y, "width": width, "height": height, "scale": 1,
        "transform": transform, "focused": index == 0,
        "activeWorkspace": {"id": workspace, "name": str(workspace)},
    }


class Backend:
    def __init__(self, snapshot):
        self.data = copy.deepcopy(snapshot)
        self.actions = []
        self.reloads = 0
        self.rules = None

    @staticmethod
    def available():
        return True

    def snapshot(self):
        return copy.deepcopy(self.data)

    def clients(self):
        return [copy.deepcopy(self.data["active"])]

    def escape_available(self):
        return True

    def ensure_setup(self):
        pass

    def reload(self):
        self.reloads += 1
        if self.rules and self.rules.exists():
            for workspace, connector in re.findall(
                r'workspace = "(\d+)", monitor = "([^"]+)"', self.rules.read_text()
            ):
                if not any(w["id"] == int(workspace) for w in self.data["workspaces"]):
                    self.data["workspaces"].append({
                        "id": int(workspace), "name": workspace, "monitor": connector, "windows": 0,
                    })

    def dispatch(self, expression):
        self.actions.append(expression)
        if expression.startswith("hl.dsp.workspace.move"):
            workspace = int(re.search(r"workspace=(\d+)", expression)[1])
            connector = re.search(r'monitor="([^"]+)"', expression)[1]
            next(w for w in self.data["workspaces"] if w["id"] == workspace)["monitor"] = connector
        elif expression.startswith("hl.dsp.focus({workspace="):
            workspace = int(re.search(r"workspace=(\d+)", expression)[1])
            connector = next(w for w in self.data["workspaces"] if w["id"] == workspace)["monitor"]
            target = next(m for m in self.data["monitors"] if m["name"] == connector)
            target["activeWorkspace"] = {"id": workspace, "name": str(workspace)}
            for m in self.data["monitors"]:
                m["focused"] = m is target
            self.data["active"] = {}


class WorkspacePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.config = self.home / "config"
        self.config.mkdir()
        (self.config / "bar.conf").write_text("ws_count=7\n")
        self.backend = Backend({
            "monitors": [
                monitor(0, "HDMI-A-1", 2, width=2560, height=1440),
                monitor(1, "DP-3", 1, x=2560, transform=1),
            ],
            "workspaces": [
                {"id": 1, "name": "1", "monitor": "DP-3", "windows": 2},
                {"id": 2, "name": "2", "monitor": "HDMI-A-1", "windows": 3},
                {"id": -97, "name": "special:messenger_signal", "monitor": "DP-3", "windows": 1},
            ],
            "active": {"address": "0x12", "monitor": 0, "workspace": {"id": 2}},
        })
        self.policy = policy_module.Policy(self.backend, self.config, self.home / "runtime")
        self.backend.rules = self.policy.rules

    def enable(self):
        self.policy.init()
        return self.policy.load()

    def test_disabled_trial_does_not_change_compositor(self):
        self.assertFalse(self.policy.enabled())
        self.assertFalse(self.policy.state()["enabled"])
        self.assertEqual(self.backend.actions, [])
        self.assertEqual(self.backend.reloads, 0)

    def test_initialization_preserves_existing_homes_and_balances_unused_slots(self):
        profile = self.enable()
        self.assertEqual(profile["homes"], {
            "1": "m2", "2": "m1", "3": "m1", "4": "m2", "5": "m1", "6": "m2", "7": "m1",
        })
        self.assertEqual(profile["defaults"], {"m1": 2, "m2": 1})
        self.assertEqual(self.backend.actions, [])
        self.assertNotIn("-97", profile["homes"])
        self.assertIn('workspace = "1", monitor = "DP-3"', self.policy.rules.read_text())

    def test_default_enrollment_is_automatic_and_idempotent(self):
        self.assertTrue(self.policy.init(only_new=True))
        profile = self.policy.load()
        self.assertEqual(profile["assignment"], "spatial-round-robin")
        self.assertEqual(profile["homes"]["1"], "m1")
        self.assertEqual(profile["homes"]["2"], "m2")
        actions = list(self.backend.actions)
        self.assertFalse(self.policy.init(only_new=True))
        self.assertEqual(self.policy.load(), profile)
        self.assertEqual(self.backend.actions, actions)

    def test_unsupported_setup_does_not_leave_partial_default_enrollment(self):
        self.backend.ensure_setup = lambda: (_ for _ in ()).throw(RuntimeError("unsupported API"))
        with self.assertRaises(RuntimeError):
            self.policy.init(only_new=True)
        self.assertFalse(self.policy.path.exists())
        self.assertFalse(self.policy.marker.exists())

    def test_default_enrollment_preserves_fixed_homes_and_disabled_preferences(self):
        profile = self.enable()
        self.assertFalse(self.policy.init(only_new=True))
        self.assertEqual(self.policy.load(), profile)
        self.policy.disable()
        disabled = self.policy.path.read_bytes()
        self.assertFalse(self.policy.init(only_new=True))
        self.assertEqual(self.policy.path.read_bytes(), disabled)
        self.assertFalse(self.policy.marker.exists())

    def test_opt_out_before_first_enrollment_is_persistent(self):
        self.policy.disable()
        self.assertFalse(self.policy.init(only_new=True))
        self.assertFalse(self.policy.enabled())
        self.assertFalse(self.policy.load()["enabled"])
        self.assertEqual(self.policy.load()["homes"], {})

    def test_spatial_arrangement_puts_odds_left_and_evens_right(self):
        self.enable()
        self.policy.arrange(automatic=True)
        profile = self.policy.load()
        self.assertEqual(profile["assignment"], "spatial-round-robin")
        self.assertEqual(profile["homes"], {
            str(w): "m1" if w % 2 else "m2" for w in range(1, 8)
        })
        self.assertEqual(profile["defaults"], {"m1": 1, "m2": 2})
        self.assertEqual(
            [m["activeWorkspace"]["id"] for m in self.backend.data["monitors"]], [1, 2])
        self.assertEqual(self.backend.actions[-1], 'hl.dsp.focus({window="address:0x12"})')

    def test_spatial_arrangement_wraps_across_three_monitors_not_ipc_order(self):
        self.backend.data["monitors"] = [
            monitor(2, "DP-right", 3, x=3840),
            monitor(0, "DP-left", 2),
            monitor(1, "DP-middle", 1, x=1920),
        ]
        self.backend.data["workspaces"] = [
            {"id": m["activeWorkspace"]["id"], "name": str(m["activeWorkspace"]["id"]),
             "monitor": m["name"], "windows": 1}
            for m in self.backend.data["monitors"]
        ]
        self.enable()
        self.policy.arrange(automatic=True)
        self.assertEqual(self.policy.load()["homes"], {
            str(w): f"m{(w - 1) % 3 + 1}" for w in range(1, 8)
        })

    def test_spatial_order_runs_top_to_bottom_for_vertically_aligned_monitors(self):
        self.backend.data["monitors"] = [
            monitor(0, "DP-middle", 2, y=0),
            monitor(1, "DP-top", 1, y=-1080),
            monitor(2, "DP-bottom", 3, y=1080),
        ]
        self.backend.data["workspaces"] = [
            {"id": m["activeWorkspace"]["id"], "name": str(m["activeWorkspace"]["id"]),
             "monitor": m["name"], "windows": 1}
            for m in self.backend.data["monitors"]
        ]
        self.enable()
        self.policy.arrange(automatic=True)
        state = self.policy.state()
        self.assertEqual([m["connector"] for m in state["monitors"]],
                         ["DP-top", "DP-middle", "DP-bottom"])
        self.assertEqual([w["id"] for w in state["monitors"][0]["workspaces"]], [1, 4, 7])

    def test_round_robin_scales_to_two_three_four_and_six_monitors(self):
        for count in (2, 3, 4, 6):
            with self.subTest(monitors=count):
                monitors = [
                    {"id": f"m{i+1}", "x": i * 1920, "y": 0}
                    for i in reversed(range(count))
                ]
                profile = {"assignment": "spatial-round-robin", "homes": {}}
                actual = [self.policy.new_home(profile, monitors, w)
                          for w in range(1, count * 2 + 1)]
                self.assertEqual(actual, [f"m{i+1}" for i in range(count)] * 2)

    def test_automatic_assignment_reacts_to_layout_changes_but_not_focus(self):
        self.enable()
        self.policy.arrange(automatic=True)
        self.policy.select("3")
        self.policy.move("right", whole_workspace=True)
        self.assertEqual(self.policy.load()["homes"]["3"], "m2")
        self.policy.state()
        self.assertEqual(self.policy.load()["homes"]["3"], "m2")
        self.backend.data["monitors"][0]["x"] = 2560
        self.backend.data["monitors"][1]["x"] = 0
        state = self.policy.state()
        self.assertEqual(self.policy.load()["homes"]["1"], "m2")
        self.assertEqual(self.policy.load()["homes"]["2"], "m1")
        self.assertEqual(self.policy.load()["homes"]["3"], "m2")
        self.assertEqual(state["monitors"][0]["id"], "m2")
        self.backend.data["monitors"].append(monitor(2, "DP-new", 8, x=5120))
        self.backend.data["workspaces"].append(
            {"id": 8, "name": "8", "monitor": "DP-new", "windows": 0})
        self.policy.state()
        self.assertEqual(self.policy.load()["homes"]["3"], "m3")
        self.assertNotIn("8", self.policy.load()["homes"])

    def test_one_time_arrangement_stays_fixed_and_preserve_stops_automatic_mode(self):
        self.enable()
        self.policy.arrange()
        homes = self.policy.load()["homes"]
        self.assertEqual(self.policy.load()["assignment"], "preserve")
        self.backend.data["monitors"][0]["x"] = 2560
        self.backend.data["monitors"][1]["x"] = 0
        self.policy.state()
        self.assertEqual(self.policy.load()["homes"], homes)
        self.policy.arrange(automatic=True)
        homes = self.policy.load()["homes"]
        self.policy.init(preserve=True)
        self.assertEqual(self.policy.load()["assignment"], "preserve")
        self.assertEqual(self.policy.load()["homes"], homes)

    def test_new_workspace_ids_follow_spatial_rule_and_previous_stays_local(self):
        self.enable()
        self.policy.arrange(automatic=True)
        self.policy.select("1")
        self.policy.select("8")
        self.assertEqual(self.policy.load()["homes"]["8"], "m2")
        self.policy.select("1")
        self.policy.runtime.mkdir(parents=True, exist_ok=True)
        (self.policy.runtime / "workspace-history.json").write_text('{"m1":2}\n')
        before = len(self.backend.actions)
        self.policy.select("previous")
        self.assertEqual(len(self.backend.actions), before)

    def test_automatic_assignment_redistributes_on_disconnect_and_reconnect(self):
        self.enable()
        self.policy.arrange(automatic=True)
        detached = self.backend.data["monitors"].pop()
        self.policy.state()
        self.assertEqual(set(self.policy.load()["homes"].values()), {"m1"})
        self.backend.data["monitors"].append(detached)
        self.policy.state()
        self.assertEqual(self.policy.load()["homes"], {
            str(w): "m1" if w % 2 else "m2" for w in range(1, 8)
        })

    def test_watch_detects_layout_changes_without_ipc_events(self):
        self.enable()
        self.policy.arrange(automatic=True)
        clock = [1.0]

        def no_events(*_):
            clock[0] += 0.5
            if clock[0] >= 4:
                raise StopIteration
            self.backend.data["monitors"][0]["x"] = 2560
            self.backend.data["monitors"][1]["x"] = 0
            return [], [], []

        output = io.StringIO()
        with mock.patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "fixture"}), \
                mock.patch.object(policy_module.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(policy_module.select, "select", side_effect=no_events), \
                mock.patch.object(policy_module.socket, "socket"), \
                contextlib.redirect_stdout(output), self.assertRaises(StopIteration):
            self.policy.watch()
        states = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertGreaterEqual(len(states), 2)
        self.assertEqual(states[-1]["monitors"][0]["id"], "m2")
        self.assertEqual(self.policy.load()["homes"]["1"], "m2")

    def test_select_follows_home_without_swapping_monitor_workspaces(self):
        self.enable()
        self.policy.select("1")
        self.assertEqual(self.backend.actions, ["hl.dsp.focus({workspace=1})"])
        self.assertEqual(self.backend.data["monitors"][0]["activeWorkspace"]["id"], 2)
        self.assertEqual(self.backend.data["monitors"][1]["activeWorkspace"]["id"], 1)

    def test_local_cycle_and_previous_keep_global_workspace_ids(self):
        self.enable()
        self.policy.select("+1")
        self.assertEqual(self.backend.actions[-1], "hl.dsp.focus({workspace=3})")
        self.policy.select("previous")
        self.assertEqual(self.backend.actions[-1], "hl.dsp.focus({workspace=2})")

    def test_bar_state_shows_both_visible_workspaces_and_keyboard_focus(self):
        self.enable()
        # Simulate mouse/bar monitor focus differing from keyboard focus.
        self.backend.data["monitors"][0]["focused"] = False
        self.backend.data["monitors"][1]["focused"] = True
        state = self.policy.state()
        self.assertEqual(state["focused_monitor"], "m1")
        self.assertEqual([w["id"] for w in state["current"]], [2, 3, 5, 7])
        self.assertTrue(next(w for w in state["current"] if w["id"] == 2)["focused"])
        other = state["monitors"][1]["workspaces"][0]
        self.assertEqual(other["id"], 1)
        self.assertTrue(other["visible"])
        self.assertFalse(other["focused"])
        self.assertTrue(other["occupied"])

    def test_spatial_map_handles_six_monitors_negative_coordinates_and_rotation(self):
        self.backend.data["monitors"] = [
            monitor(i, f"DP-{i}", i + 1, x=(i % 3 - 1) * 1920, y=(i // 3 - 1) * 1080)
            for i in range(6)
        ]
        self.backend.data["monitors"][4]["transform"] = 1
        self.backend.data["workspaces"] = [
            {"id": i + 1, "name": str(i + 1), "monitor": f"DP-{i}", "windows": 1}
            for i in range(6)
        ]
        self.backend.data["active"] = {"address": "0x12", "monitor": 0, "workspace": {"id": 1}}
        self.enable()
        state = self.policy.state()
        self.assertEqual(len(state["monitors"]), 6)
        self.assertLessEqual(state["map_width"], 560)
        self.assertLessEqual(state["map_height"], 260)
        for m in state["monitors"]:
            self.assertGreaterEqual(m["map_x"], 0)
            self.assertGreaterEqual(m["map_y"], 0)
            self.assertLessEqual(m["map_x"] + m["map_width"], state["map_width"] + 1)
            self.assertLessEqual(m["map_y"] + m["map_height"], state["map_height"] + 1)
        rotated = next(m for m in state["monitors"] if m["connector"] == "DP-4")
        self.assertEqual((rotated["width"], rotated["height"]), (1080, 1920))

    def test_monitor_identity_survives_geometry_order_and_connector_changes(self):
        before = self.enable()
        self.backend.data["monitors"].reverse()
        self.backend.data["monitors"][0]["name"] = "DP-8"
        self.backend.data["monitors"][0]["x"] = -1080
        for w in self.backend.data["workspaces"]:
            if w["monitor"] == "DP-3":
                w["monitor"] = "DP-8"
        self.policy.state()
        after = self.policy.load()
        self.assertEqual(after["homes"], before["homes"])
        self.assertEqual(next(m for m in after["monitors"] if m["id"] == "m2")["connector"], "DP-8")

    def test_identical_monitors_use_connectors_without_swapping_ids(self):
        for m in self.backend.data["monitors"]:
            m["serial"] = ""
        before = self.enable()
        self.backend.data["monitors"].reverse()
        self.backend.data["monitors"][0]["x"] = -1920
        self.policy.state()
        self.assertEqual(self.policy.load()["homes"], before["homes"])

    def test_disconnected_homes_fall_back_without_forgetting_ownership(self):
        profile = self.enable()
        self.backend.data["monitors"] = self.backend.data["monitors"][:1]
        state = self.policy.state()
        self.assertEqual(self.policy.load()["homes"], profile["homes"])
        borrowed = next(w for w in state["current"] if w["id"] == 1)
        self.assertTrue(borrowed["temporary"])
        self.assertEqual(borrowed["home"], "m2")
        self.assertEqual(state["disconnected"][0]["id"], "m2")
        self.assertEqual(next(w for w in self.backend.data["workspaces"] if w["id"] == 1)["monitor"],
                         "HDMI-A-1")
        self.backend.data["monitors"].append(monitor(1, "DP-3", 1, x=2560, transform=1))
        self.policy.state()
        self.assertEqual(next(w for w in self.backend.data["workspaces"] if w["id"] == 1)["monitor"], "DP-3")
        self.assertEqual(self.policy.load()["homes"], profile["homes"])

    def test_directional_neighbors_follow_geometry_not_array_order(self):
        monitors = [
            {"id": "center", "x": 0, "y": 0, "width": 100, "height": 100},
            {"id": "up", "x": 0, "y": -100, "width": 100, "height": 100},
            {"id": "down", "x": 0, "y": 100, "width": 100, "height": 100},
            {"id": "left", "x": -100, "y": 0, "width": 100, "height": 100},
            {"id": "diagonal", "x": 100, "y": 100, "width": 100, "height": 100},
            {"id": "right", "x": 100, "y": 0, "width": 100, "height": 100},
        ]
        for direction in ("left", "right", "up", "down"):
            with self.subTest(direction=direction):
                self.assertEqual(policy_module.neighbor(monitors, monitors[0], direction)["id"], direction)
        self.assertIsNone(policy_module.neighbor(monitors, monitors[1], "up"))

    def test_move_window_targets_other_monitors_visible_workspace_not_group_offset(self):
        self.enable()
        self.policy.move("right")
        self.assertEqual(self.backend.actions, [
            'hl.dsp.window.move({window="address:0x12", workspace=1, follow=false})',
            'hl.dsp.focus({window="address:0x12"})',
        ])

    def test_explicit_workspace_move_updates_its_home(self):
        self.enable()
        self.policy.move("right", whole_workspace=True)
        self.assertEqual(self.policy.load()["homes"]["2"], "m2")
        self.assertEqual(next(w for w in self.backend.data["workspaces"] if w["id"] == 2)["monitor"], "DP-3")

    def use_three_monitors(self):
        self.backend.data["monitors"] = [
            monitor(2, "DP-right", 3, x=3840),
            monitor(0, "DP-left", 2),
            monitor(1, "DP-middle", 1, x=1920),
        ]
        self.backend.data["workspaces"] = [
            {"id": m["activeWorkspace"]["id"], "name": str(m["activeWorkspace"]["id"]),
             "monitor": m["name"], "windows": 1}
            for m in self.backend.data["monitors"]
        ]

    def run_cli(self, *argv):
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.object(policy_module, "Policy", return_value=self.policy), \
                mock.patch("sys.argv", ["workspace-ctl", *argv]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = policy_module.main()
        return code, output.getvalue(), errors.getvalue()

    def workspace_monitors(self):
        return {w["id"]: w["monitor"] for w in self.backend.data["workspaces"] if w["id"] > 0}

    def test_primary_is_the_monitor_that_owns_workspace_one_and_reading_it_changes_nothing(self):
        self.enable()
        saved = (self.policy.path.read_bytes(), self.policy.rules.read_bytes())
        actions, reloads = list(self.backend.actions), self.backend.reloads
        self.assertEqual(self.policy.primary_connector(), "DP-3")
        self.assertEqual((self.policy.path.read_bytes(), self.policy.rules.read_bytes()), saved)
        self.assertEqual((self.backend.actions, self.backend.reloads), (actions, reloads))
        self.policy.arrange(automatic=True)
        self.assertEqual(self.policy.primary_connector(), "HDMI-A-1")
        self.backend.data["monitors"] = []
        with self.assertRaises(RuntimeError):
            self.policy.primary_connector()

    def test_set_primary_in_spatial_mode_gives_workspace_one_to_the_chosen_monitor(self):
        self.policy.init(only_new=True)
        self.assertEqual(self.policy.primary_connector(), "HDMI-A-1")
        self.assertEqual(self.policy.set_primary("DP-3"), "DP-3")
        profile = self.policy.load()
        self.assertEqual(profile["primary"], "m2")
        self.assertEqual(profile["assignment"], "spatial-round-robin")
        self.assertEqual(profile["homes"], {str(w): "m2" if w % 2 else "m1" for w in range(1, 8)})
        self.assertIn('workspace = "1", monitor = "DP-3"', self.policy.rules.read_text())
        self.assertEqual(self.workspace_monitors()[1], "DP-3")
        self.assertEqual(self.policy.primary_connector(), "DP-3")

    def test_set_primary_in_preserve_mode_swaps_homes_and_keeps_the_mode(self):
        self.enable()
        self.assertEqual(self.policy.set_primary("HDMI-A-1"), "HDMI-A-1")
        profile = self.policy.load()
        self.assertEqual(profile["assignment"], "preserve")
        self.assertEqual(profile["homes"], {
            "1": "m1", "2": "m2", "3": "m2", "4": "m1", "5": "m2", "6": "m1", "7": "m2",
        })
        self.assertEqual(self.workspace_monitors(), {
            1: "HDMI-A-1", 2: "DP-3", 3: "DP-3", 4: "HDMI-A-1", 5: "DP-3", 6: "HDMI-A-1", 7: "DP-3",
        })
        self.assertEqual(self.policy.primary_connector(), "HDMI-A-1")

    def test_set_primary_with_three_monitors_continues_spatially_after_the_primary(self):
        self.use_three_monitors()
        self.enable()
        self.policy.arrange(automatic=True)
        self.policy.set_primary("DP-middle")
        self.assertEqual(self.policy.load()["homes"], {
            "1": "m2", "2": "m1", "3": "m3", "4": "m2", "5": "m1", "6": "m3", "7": "m2",
        })
        self.assertEqual(self.policy.primary_connector(), "DP-middle")

    def test_chosen_primary_survives_layout_changes_and_reconnects(self):
        self.policy.init(only_new=True)
        self.policy.set_primary("DP-3")
        homes = self.policy.load()["homes"]
        self.backend.data["monitors"][1]["x"] = 3000
        self.policy.state()
        self.assertEqual(self.policy.load()["homes"], homes)
        detached = self.backend.data["monitors"].pop()
        self.policy.state()
        self.assertEqual(self.policy.load()["primary"], "m2")
        self.assertEqual(self.policy.primary_connector(), "HDMI-A-1")
        self.backend.data["monitors"].append(detached)
        self.policy.state()
        self.assertEqual(self.policy.load()["homes"], homes)
        self.assertEqual(self.policy.primary_connector(), "DP-3")

    def test_set_primary_is_idempotent_and_accepts_the_stable_monitor_id(self):
        self.enable()
        self.policy.set_primary("HDMI-A-1")
        saved = self.policy.path.read_bytes()
        stamp = self.policy.path.stat().st_mtime_ns
        actions, reloads = list(self.backend.actions), self.backend.reloads
        for target in ("HDMI-A-1", "m1"):
            self.assertEqual(self.policy.set_primary(target), "HDMI-A-1")
        self.assertEqual(self.policy.path.read_bytes(), saved)
        self.assertEqual(self.policy.path.stat().st_mtime_ns, stamp)
        self.assertEqual((self.backend.actions, self.backend.reloads), (actions, reloads))

    def test_set_primary_rejects_unknown_and_disconnected_monitors_without_writing(self):
        self.enable()
        saved = self.policy.path.read_bytes()
        actions, reloads = list(self.backend.actions), self.backend.reloads
        with self.assertRaisesRegex(ValueError, "DP-9"):
            self.policy.set_primary("DP-9")
        self.backend.data["monitors"].pop()
        with self.assertRaisesRegex(ValueError, "DP-3"):
            self.policy.set_primary("DP-3")
        self.assertEqual(self.policy.path.read_bytes(), saved)
        self.assertEqual((self.backend.actions, self.backend.reloads), (actions, reloads))

    def test_primary_follows_an_explicit_move_of_workspace_one(self):
        self.enable()
        self.policy.select("1")
        self.policy.move("left", whole_workspace=True)
        self.assertEqual(self.policy.load()["homes"]["1"], "m1")
        self.assertEqual(self.policy.primary_connector(), "HDMI-A-1")

    def test_invalid_primary_monitor_fails_explicitly(self):
        self.enable()
        profile = self.policy.load()
        profile["primary"] = None
        self.policy.save(profile)
        self.assertIsNone(self.policy.load()["primary"])
        for bad in ("m9", "", 1, ["m1"], True):
            with self.subTest(primary=bad):
                profile["primary"] = bad
                self.policy.save(profile)
                with self.assertRaises(ValueError):
                    self.policy.load()

    def test_primary_commands_require_the_enabled_policy_and_never_touch_the_compositor(self):
        env = {**os.environ, "HOME": str(self.home), "XDG_RUNTIME_DIR": str(self.home / "run")}
        for command in (["primary"], ["set-primary", "DP-3"]):
            with self.subTest(command=command):
                result = subprocess.run([str(CONTROLLER), *command], env=env, capture_output=True,
                                        text=True, timeout=10)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("workspace-ctl: Stable workspace policy is not enabled", result.stderr)

    def test_primary_command_prints_one_connector(self):
        self.enable()
        self.assertEqual(self.run_cli("primary"), (0, "DP-3\n", ""))

    def test_set_primary_command_refreshes_the_taskbar_even_when_nothing_changed(self):
        self.enable()
        with mock.patch.object(policy_module.subprocess, "Popen") as popen:
            popen.return_value.wait.return_value = 0
            self.assertEqual(self.run_cli("set-primary", "HDMI-A-1"), (0, "Primary monitor: HDMI-A-1\n", ""))
            self.assertEqual(self.run_cli("set-primary", "HDMI-A-1"), (0, "Primary monitor: HDMI-A-1\n", ""))
        self.assertEqual([call.args[0] for call in popen.call_args_list], [["bar-ctl", "refresh"]] * 2)

    def test_failed_taskbar_refresh_does_not_undo_the_primary_change(self):
        self.enable()
        failures = {
            "bar-ctl missing": {"side_effect": FileNotFoundError("bar-ctl")},
            "bar-ctl failed": {"return_value": mock.Mock(wait=mock.Mock(return_value=1))},
        }
        for label, failure in failures.items():
            with self.subTest(label), mock.patch.object(policy_module.subprocess, "Popen", **failure):
                code, output, errors = self.run_cli("set-primary", "HDMI-A-1")
                self.assertEqual((code, output), (0, "Primary monitor: HDMI-A-1\n"))
                self.assertIn("workspace-ctl: the bar was not moved", errors)
                self.assertEqual(self.policy.primary_connector(), "HDMI-A-1")

    def test_slow_taskbar_refresh_is_not_killed_and_set_primary_answers_inside_the_settings_limit(self):
        self.enable()
        # Settings abandons a command after 8 seconds.
        self.assertLess(policy_module.BAR_REFRESH_WAIT, 8)
        with mock.patch.object(policy_module.subprocess, "Popen") as popen:
            popen.return_value.wait.side_effect = subprocess.TimeoutExpired(["bar-ctl", "refresh"], 5)
            code, output, errors = self.run_cli("set-primary", "HDMI-A-1")
        self.assertEqual((code, output), (0, "Primary monitor: HDMI-A-1\n"))
        self.assertIn("workspace-ctl: the bar is still moving", errors)
        popen.return_value.wait.assert_called_once_with(timeout=policy_module.BAR_REFRESH_WAIT)
        popen.return_value.kill.assert_not_called()
        popen.return_value.terminate.assert_not_called()
        self.assertEqual(self.policy.primary_connector(), "HDMI-A-1")

    def test_slow_taskbar_refresh_keeps_running_after_set_primary_returns(self):
        self.enable()
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        release, finished = self.home / "release", self.home / "bar-refreshed"
        fake = bin_dir / "bar-ctl"
        fake.write_text(
            "#!/bin/sh\n"
            "i=0\n"
            f"while [ ! -e '{release}' ] && [ $i -lt 200 ]; do sleep 0.05; i=$((i+1)); done\n"
            f"touch '{finished}'\n"
        )
        fake.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}"}), \
                mock.patch.object(policy_module, "BAR_REFRESH_WAIT", 0.2):
            code, output, errors = self.run_cli("set-primary", "HDMI-A-1")
        self.assertEqual((code, output), (0, "Primary monitor: HDMI-A-1\n"))
        self.assertIn("still moving", errors)
        self.assertFalse(finished.exists())
        release.touch()
        deadline = time.monotonic() + 10
        while not finished.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(finished.exists(), "bar-ctl was killed instead of being left to finish")

    def test_rejected_primary_target_leaves_the_taskbar_alone(self):
        self.enable()
        with mock.patch.object(policy_module.subprocess, "run") as run, self.assertRaises(ValueError):
            self.run_cli("set-primary", "DP-9")
        run.assert_not_called()

    def test_send_and_focus_existing_window_use_exact_id(self):
        self.enable()
        self.policy.send("1", silent=True)
        self.assertEqual(self.backend.actions[-1],
                         'hl.dsp.window.move({window="address:0x12", workspace=1, follow=false})')
        self.policy.focus_window("0x12")
        self.assertEqual(self.backend.actions[-1], 'hl.dsp.focus({window="address:0x12"})')

    def test_current_preserves_visible_special_workspace_for_local_launches(self):
        self.enable()
        self.backend.data["active"]["workspace"] = {"id": -97}
        self.backend.data["monitors"][0]["specialWorkspace"] = {"id": -97, "name": "special:scratchpad"}
        self.assertEqual(self.policy.current_workspace(), -97)
        self.assertEqual(self.policy.current_monitor()["id"], 0)

    def test_existing_hidden_webapp_is_focused_without_adopting_special_workspace(self):
        profile = self.enable()
        self.backend.data["active"]["workspace"] = {"id": -97}
        self.policy.focus_window("0x12")
        self.assertEqual(self.backend.actions, ['hl.dsp.focus({window="address:0x12"})'])
        self.assertEqual(self.policy.load()["homes"], profile["homes"])

    def test_failed_reload_is_retried_even_after_rule_file_was_written(self):
        self.enable()
        self.backend.data["monitors"] = self.backend.data["monitors"][:1]
        original = self.backend.reload
        self.backend.reload = lambda: (_ for _ in ()).throw(RuntimeError("reload failed"))
        with self.assertRaises(RuntimeError):
            self.policy.state()
        self.assertTrue(self.policy.pending_rules.exists())
        self.backend.reload = original
        state = self.policy.state()
        self.assertFalse(self.policy.pending_rules.exists())
        self.assertTrue(next(w for w in state["current"] if w["id"] == 1)["temporary"])

    def test_failed_move_is_retried_even_when_rule_text_does_not_change(self):
        self.enable()
        self.backend.data["monitors"] = self.backend.data["monitors"][:1]
        original = self.backend.dispatch
        self.backend.dispatch = lambda _: (_ for _ in ()).throw(RuntimeError("move failed"))
        with self.assertRaises(RuntimeError):
            self.policy.state()
        self.backend.dispatch = original
        self.policy.state()
        self.assertEqual(next(w for w in self.backend.data["workspaces"] if w["id"] == 1)["monitor"],
                         "HDMI-A-1")

    def test_disabled_state_preserves_profile_for_rollback_and_reenable(self):
        profile = self.enable()
        self.policy.disable()
        self.assertFalse(self.policy.enabled())
        self.assertFalse(self.policy.marker.exists())
        self.assertEqual(self.policy.load()["homes"], profile["homes"])
        self.policy.init()
        self.assertTrue(self.policy.enabled())
        self.assertEqual(self.policy.load()["homes"], profile["homes"])

    def test_disable_still_works_with_an_invalid_saved_profile(self):
        self.enable()
        self.policy.path.write_text("invalid json\n")
        warning = io.StringIO()
        with contextlib.redirect_stderr(warning):
            self.policy.disable()
        self.assertIn("leaving invalid saved profile unchanged", warning.getvalue())
        self.assertFalse(self.policy.enabled())
        self.assertFalse(self.policy.marker.exists())
        self.assertEqual(self.policy.path.read_text(), "invalid json\n")

    def test_invalid_policy_and_selectors_fail_explicitly(self):
        self.enable()
        with self.assertRaises(ValueError):
            self.policy.select("1; do something")
        profile = self.policy.load()
        profile["homes"]["1"] = "unknown-monitor"
        self.policy.save(profile)
        with self.assertRaises(ValueError):
            self.policy.load()

    def test_bar_count_change_keeps_occupied_or_visible_workspaces(self):
        self.enable()
        self.backend.data["workspaces"].append(
            {"id": 12, "name": "12", "monitor": "DP-3", "windows": 1})
        self.policy.state()
        (self.config / "bar.conf").write_text("ws_count=1\n")
        self.policy.state()
        self.assertEqual(set(self.policy.load()["homes"]), {"1", "2", "12"})

    def test_taskbar_presentation_does_not_rewrite_policy_or_move_focus(self):
        self.policy.init(only_new=True)
        self.policy.state()
        profile = self.policy.path.read_bytes()
        rules = self.policy.rules.read_bytes()
        stamps = (self.policy.path.stat().st_mtime_ns, self.policy.rules.stat().st_mtime_ns)
        actions = list(self.backend.actions)
        reloads = self.backend.reloads
        active = copy.deepcopy(self.backend.data["active"])
        for style, spacing, position in (("squares", 10, "left"), ("numbers", 1, "center")):
            (self.config / "bar.conf").write_text(
                f"ws_count=7\nws_style={style}\nws_spacing={spacing}\nws_position={position}\n")
            state = self.policy.state()
            self.assertEqual(self.policy.path.read_bytes(), profile)
            self.assertEqual(self.policy.rules.read_bytes(), rules)
            self.assertEqual((self.policy.path.stat().st_mtime_ns,
                              self.policy.rules.stat().st_mtime_ns), stamps)
            self.assertEqual(self.backend.actions, actions)
            self.assertEqual(self.backend.reloads, reloads)
            self.assertEqual(self.backend.data["active"], active)
            self.assertEqual([[ws["id"] for ws in monitor["workspaces"]]
                              for monitor in state["monitors"]], [[1, 3, 5, 7], [2, 4, 6]])

    def test_taskbar_count_is_global_and_changes_reconcile_without_app_dispatch(self):
        self.policy.init(only_new=True)
        (self.config / "bar.conf").write_text("ws_count=10\n")
        state = self.policy.state()
        self.assertEqual([[ws["id"] for ws in monitor["workspaces"]]
                          for monitor in state["monitors"]], [[1, 3, 5, 7, 9], [2, 4, 6, 8, 10]])
        self.backend.data["workspaces"].append(
            {"id": 12, "name": "12", "monitor": "DP-3", "windows": 1})
        self.policy.state()
        (self.config / "bar.conf").write_text("ws_count=1\n")
        state = self.policy.state()
        self.assertEqual(self.policy.load()["count"], 1)
        self.assertEqual({ws["id"] for monitor in state["monitors"] for ws in monitor["workspaces"]},
                         {1, 2, 12})
        self.assertTrue(all(monitor["workspaces"] for monitor in state["monitors"]))

    def test_disabled_watch_emits_single_line_json_without_compositor_access(self):
        env = {**os.environ, "HOME": str(self.home), "XDG_RUNTIME_DIR": str(self.home / "run")}
        process = subprocess.Popen(
            [str(CONTROLLER), "watch"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            state = json.loads(process.stdout.readline())
            self.assertFalse(state["enabled"])
        finally:
            process.terminate()
            process.communicate(timeout=5)

    @unittest.skipUnless(shutil.which("lua"), "requires the existing Lua interpreter")
    def test_lua_bootstrap_and_bindings_gate_the_trial_without_breaking_specials(self):
        directory = self.home / ".config/smplos"
        directory.mkdir(parents=True)
        bindings = self.home / "bindings.conf"
        bindings.write_text(
            "bindd = SUPER, 1, Workspace, workspace, 1\n"
            "bindd = SUPER, TAB, Next, workspace, +1\n"
            "bindd = SUPER SHIFT, 1, Send, movetoworkspace, 1\n"
            "bindd = SUPER CTRL, 1, Silent, movetoworkspacesilent, 1\n"
            "bindd = SUPER SHIFT ALT, UP, Move home, movecurrentworkspacetomonitor, u\n"
            "bindd = SUPER, S, Scratchpad, togglespecialworkspace, scratchpad\n"
        )
        script = """
local function op(kind)
  return function(value) return {kind=kind, value=value} end
end
hl = {
  workspace_rule=function(_) end,
  get_workspaces=function() return {} end,
  get_windows=function() return {} end,
  get_active_window=function() return nil end,
  dispatch=function(action)
    print(action.kind .. ":" .. (type(action.value) == "string" and action.value or "table"))
  end,
  dsp={
    focus=op("native-focus"), exec_cmd=op("exec"),
    window={move=op("native-send")},
    workspace={move=op("native-workspace-move"), toggle_special=op("special")}
  },
  bind=function(_, action, _)
    if type(action) == "function" then action() else hl.dispatch(action) end
  end
}
dofile(arg[1])
dofile(arg[2]).load(arg[3])
"""
        command_args = ["lua", "-",
                        str(ROOT / "src/compositors/hyprland/hypr/workspace_policy.lua"),
                        str(ROOT / "src/compositors/hyprland/hypr/bindings_loader.lua"), str(bindings)]
        env = {**os.environ, "HOME": str(self.home)}
        legacy = subprocess.run(command_args, input=script, text=True, capture_output=True,
                                env=env, check=True).stdout
        self.assertIn("native-focus:table", legacy)
        self.assertNotIn("workspace-ctl", legacy)
        (directory / "workspace-policy.enabled").touch()
        (directory / "workspace-rules.lua").write_text('hl.workspace_rule({workspace="1", monitor="DP-1"})\n')
        enabled = subprocess.run(command_args, input=script, text=True, capture_output=True,
                                 env=env, check=True).stdout
        self.assertIn("native-focus:table", enabled)
        self.assertNotIn("exec:workspace-ctl select 1\n", enabled)
        self.assertIn("exec:workspace-ctl select +1", enabled)
        self.assertIn("exec:workspace-ctl send 1 --silent", enabled)
        self.assertIn("exec:workspace-ctl move-workspace up", enabled)
        self.assertIn("special:scratchpad", enabled)
        (directory / "workspace-rules.lua").write_text("invalid lua syntax !!!\n")
        failed = subprocess.run(command_args, input=script, text=True, capture_output=True,
                                env=env, check=True).stdout
        self.assertIn("smplOS workspace policy:", failed)
        self.assertIn("native-focus:table", failed)
        self.assertNotIn("exec:workspace-ctl", failed)


if __name__ == "__main__":
    unittest.main()
