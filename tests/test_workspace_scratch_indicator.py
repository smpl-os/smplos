"""Visible-special indicator: neutral synthetic regression cases.

No compositor/desktop is driven. The controller is exercised through the same
mocked backend harness the policy suite uses, and native bar data contracts are covered separately.
"""

import copy
import importlib.machinery
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "src/shared/bin/workspace-ctl"
loader = importlib.machinery.SourceFileLoader("workspace_ctl_scratch", str(CONTROLLER))
spec = importlib.util.spec_from_loader(loader.name, loader)
scratch_module = importlib.util.module_from_spec(spec)
loader.exec_module(scratch_module)


def monitor(index, connector, active, x=0, y=0, width=1920, height=1080, special=0):
    return {
        "id": index, "name": connector, "make": "Test", "model": "Panel",
        "serial": f"serial-{index}", "description": f"Test panel {index}",
        "x": x, "y": y, "width": width, "height": height, "scale": 1,
        "transform": 0, "focused": index == 0,
        "activeWorkspace": {"id": active, "name": str(active)},
        "specialWorkspace": {"id": special, "name": f"special-{index}" if special else ""},
    }


class Backend:
    def __init__(self, snapshot):
        self.data = copy.deepcopy(snapshot)
        self.actions = []
        self.reloads = 0

    @staticmethod
    def available():
        return True

    def snapshot(self):
        return copy.deepcopy(self.data)

    def clients(self):
        return []

    def escape_available(self):
        return False

    def ensure_setup(self):
        pass

    def reload(self):
        self.reloads += 1

    def dispatch(self, expression):
        self.actions.append(expression)
        # Synthetic in-memory materialization of the move/focus the real
        # sync re-reads to verify (same fake contract as the policy suite
        # backend); no compositor or desktop is driven.
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


def definition(source, name):
    start = source.index(f"(defwidget {name} ")
    end = source.find("\n(def", start + 1)
    return source[start:end if end != -1 else len(source)]


class ScratchIndicatorDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.config = self.home / "config"
        self.config.mkdir()
        (self.config / "bar.conf").write_text("ws_count=7\n")
        self.backend = Backend({
            "monitors": [monitor(0, "HDMI-A-1", 1, x=0), monitor(1, "DP-3", 1, x=1920)],
            "workspaces": [{"id": 1, "name": "1", "monitor": "HDMI-A-1", "windows": 0}],
            "active": {"address": "0x1", "monitor": 0, "workspace": {"id": 1}},
        })
        self.policy = scratch_module.Policy(self.backend, self.config, self.home / "runtime")
        self.policy.init()

    def set_scene(self, monitors, focus, workspaces=None):
        # monitors: list of (connector, active_workspace, special_workspace)
        self.backend.data = {
            "monitors": [monitor(i, connector, active, x=i * 1920, special=special)
                         for i, (connector, active, special) in enumerate(monitors)],
            "workspaces": workspaces if workspaces is not None else [],
            "active": {"address": "0x1", "monitor": focus,
                       "workspace": {"id": monitors[focus][1]}},
        }

    def by_id(self, state):
        return {m["id"]: m for m in state["monitors"]}

    def test_open_sets_s_on_focused_monitor_only(self):
        # Native visible shape: the normal activeWorkspace id stays positive
        # (1) while specialWorkspace.id is negative (-98) on the same monitor.
        self.set_scene(
            [("HDMI-A-1", 1, -98), ("DP-3", 2, 0)], focus=0,
            workspaces=[
                {"id": -98, "name": "scratchpad", "monitor": "HDMI-A-1", "windows": 2},
                {"id": 1, "name": "1", "monitor": "HDMI-A-1", "windows": 0},
                {"id": 2, "name": "2", "monitor": "DP-3", "windows": 0},
            ])
        state = self.policy.state()
        self.assertTrue(state["focused_special"])
        groups = self.by_id(state)
        self.assertTrue(groups["m1"]["special_visible"])
        self.assertFalse(groups["m2"]["special_visible"])
        self.assertEqual(state["focused_label"], "M1")

    def test_closure_restores_the_normal_group(self):
        # Same monitor, back on a numbered workspace; closed shape is
        # normal active 1 with specialWorkspace.id back to 0, even though
        # the scratchpad still holds parked (hidden) clients.
        self.set_scene(
            [("HDMI-A-1", 1, 0), ("DP-3", 2, 0)], focus=0,
            workspaces=[
                {"id": -98, "name": "scratchpad", "monitor": "HDMI-A-1", "windows": 2},
                {"id": 1, "name": "1", "monitor": "HDMI-A-1", "windows": 1},
                {"id": 2, "name": "2", "monitor": "DP-3", "windows": 0},
            ])
        state = self.policy.state()
        self.assertFalse(state["focused_special"])
        groups = self.by_id(state)
        self.assertFalse(groups["m1"]["special_visible"])
        self.assertFalse(groups["m2"]["special_visible"])

    def test_parked_special_clients_alone_do_not_set_s(self):
        # The special workspace holds parked (hidden) clients but is not
        # shown: hidden shape is normal active 1 with specialWorkspace.id 0.
        self.set_scene(
            [("HDMI-A-1", 1, 0), ("DP-3", 2, 0)], focus=0,
            workspaces=[
                {"id": -98, "name": "scratchpad", "monitor": "HDMI-A-1", "windows": 3},
                {"id": 1, "name": "1", "monitor": "HDMI-A-1", "windows": 1},
                {"id": 2, "name": "2", "monitor": "DP-3", "windows": 0},
            ])
        state = self.policy.state()
        self.assertFalse(state["focused_special"])
        self.assertFalse(self.by_id(state)["m1"]["special_visible"])

    def test_monitors_are_independent_and_focus_tracks_the_bar(self):
        # DP-3's native visible shape: normal active stays positive (2)
        # while its specialWorkspace.id is -98.
        self.set_scene(
            [("HDMI-A-1", 1, 0), ("DP-3", 2, -98), ("HDMI-C-1", 3, 0)], focus=1,
            workspaces=[
                {"id": -98, "name": "scratchpad", "monitor": "DP-3", "windows": 1},
                {"id": 2, "name": "2", "monitor": "DP-3", "windows": 0},
                {"id": 1, "name": "1", "monitor": "HDMI-A-1", "windows": 0},
                {"id": 3, "name": "3", "monitor": "HDMI-C-1", "windows": 0},
            ])
        state = self.policy.state()
        groups = self.by_id(state)
        # The focused monitor (DP-3) is in its scratchpad.
        self.assertTrue(state["focused_special"])
        self.assertTrue(groups["m2"]["special_visible"])
        self.assertFalse(groups["m1"]["special_visible"])
        self.assertFalse(groups["m3"]["special_visible"])
        # Moving focus off the scratchpad monitor clears the bar's S, but
        # the other group still reports its own (independent) visibility:
        # DP-3 keeps active 2 / special -98, HDMI-A-1 keeps active 1 / 0.
        self.set_scene(
            [("HDMI-A-1", 1, 0), ("DP-3", 2, -98), ("HDMI-C-1", 3, 0)], focus=0,
            workspaces=[
                {"id": -98, "name": "scratchpad", "monitor": "DP-3", "windows": 1},
                {"id": 1, "name": "1", "monitor": "HDMI-A-1", "windows": 0},
                {"id": 3, "name": "3", "monitor": "HDMI-C-1", "windows": 0},
            ])
        state = self.policy.state()
        groups = self.by_id(state)
        self.assertFalse(state["focused_special"])
        self.assertTrue(groups["m2"]["special_visible"])
        self.assertFalse(groups["m1"]["special_visible"])

    def test_monitor_without_special_workspace_never_shows_s(self):
        self.set_scene([("HDMI-A-1", 1, 0)], focus=0,
                       workspaces=[{"id": 1, "name": "1", "monitor": "HDMI-A-1", "windows": 0}])
        state = self.policy.state()
        self.assertFalse(state["focused_special"])
        self.assertFalse(self.by_id(state)["m1"]["special_visible"])

    def test_disabled_state_has_a_stable_special_field(self):
        state = scratch_module.empty_state()
        self.assertFalse(state["focused_special"])
        self.assertIn("focused_special", state)
