"""Visible-special indicator: neutral synthetic regression cases.

No compositor/desktop is driven. The controller is exercised through the same
mocked backend harness the policy suite uses, and the EWW wiring is checked at
the contract level (the exact live-widget expressions the bar renders).
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
OVERVIEW = (ROOT / "src/shared/eww/workspace-overview.yuck").read_text()
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


# Minimal evaluator for the guarded live-widget expressions. It covers
# exactly the syntax those yuck expressions use (refs, strings, the
# jq '.field // false' guards, `!`, `&&`, `==`/`!=`, ternaries) so
# startup/old-state shapes resolve the way EWW would, without driving a
# compositor or a desktop.
_TOKEN_RE = re.compile(r"\s*(==|!=|&&|[?!(),:]"
                       r"|\"[^\"]*\"|'[^']*'"
                       r"|[A-Za-z_][A-Za-z0-9_]*(?:[-.][A-Za-z0-9_]+)*)")


def tokenize(expression):
    tokens = []
    position = 0
    while position < len(expression):
        match = _TOKEN_RE.match(expression, position)
        assert match, expression
        token = match.group(1)
        position = match.end()
        if token.startswith(('"', "'")):
            tokens.append(("str", token[1:-1]))
        elif token in ("==", "!=", "&&", "!", "?", ":", "(", ")", ","):
            tokens.append(("op", token))
        elif token in ("true", "false", "nil"):
            tokens.append(("lit", {"true": True, "false": False, "nil": None}[token]))
        else:
            tokens.append(("ident", token))
    return tokens


def _parse_ternary(tokens, pos):
    condition, pos = _parse_and(tokens, pos)
    if pos < len(tokens) and tokens[pos] == ("op", "?"):
        then, pos = _parse_ternary(tokens, pos + 1)
        assert tokens[pos] == ("op", ":")
        otherwise, pos = _parse_ternary(tokens, pos + 1)
        return ("ternary", condition, then, otherwise), pos
    return condition, pos


def _parse_and(tokens, pos):
    left, pos = _parse_unary(tokens, pos)
    while pos < len(tokens) and tokens[pos] == ("op", "&&"):
        right, pos = _parse_unary(tokens, pos + 1)
        left = ("and", left, right)
    return left, pos


def _parse_unary(tokens, pos):
    if pos < len(tokens) and tokens[pos] == ("op", "!"):
        operand, pos = _parse_unary(tokens, pos + 1)
        return ("not", operand), pos
    return _parse_comparison(tokens, pos)


def _parse_comparison(tokens, pos):
    left, pos = _parse_primary(tokens, pos)
    if pos < len(tokens) and tokens[pos][1] in ("==", "!="):
        op = tokens[pos][1]
        right, pos = _parse_primary(tokens, pos + 1)
        return ("cmp", op, left, right), pos
    return left, pos


def _parse_call(tokens, pos):
    name = tokens[pos][1]
    assert tokens[pos + 1] == ("op", "(")
    pos += 2
    arguments = []
    while True:
        argument, pos = _parse_ternary(tokens, pos)
        arguments.append(argument)
        if tokens[pos] == ("op", ")"):
            return ("call", name, arguments), pos + 1
        assert tokens[pos] == ("op", ","), tokens[pos]
        pos += 1


def _parse_primary(tokens, pos):
    kind, value = tokens[pos]
    if kind in ("str", "lit"):
        return ("lit", value), pos + 1
    if kind == "ident":
        if pos + 1 < len(tokens) and tokens[pos + 1] == ("op", "("):
            return _parse_call(tokens, pos)
        return ("ref", value), pos + 1
    assert (kind, value) == ("op", "("), tokens[pos]
    node, pos = _parse_ternary(tokens, pos + 1)
    assert tokens[pos] == ("op", ")"), tokens[pos]
    return node, pos + 1


def _evaluate(node, scope):
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "ref":
        value = scope
        for part in node[1].split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return value
    if kind == "call":
        assert node[1] == "jq", node
        container = _evaluate(node[2][0], scope)
        guard = re.fullmatch(r"\.([A-Za-z0-9_]+) // false", _evaluate(node[2][1], scope))
        assert guard, node[2][1]
        return container.get(guard.group(1), False) if isinstance(container, dict) else False
    if kind == "not":
        return not _evaluate(node[1], scope)
    if kind == "and":
        return _evaluate(node[1], scope) and _evaluate(node[2], scope)
    if kind == "cmp":
        left = _evaluate(node[2], scope)
        right = _evaluate(node[3], scope)
        return left == right if node[1] == "==" else left != right
    if kind == "ternary":
        if _evaluate(node[1], scope):
            return _evaluate(node[2], scope)
        return _evaluate(node[3], scope)
    raise AssertionError(kind)


def eval_expr(expression, scope):
    tokens = tokenize(expression)
    node, pos = _parse_ternary(tokens, 0)
    assert pos == len(tokens), expression
    return _evaluate(node, scope)


class ScratchIndicatorWiringTests(unittest.TestCase):
    def test_live_bar_shows_s_and_hides_numbered_groups(self):
        trial = definition(OVERVIEW, "workspace-trial-bar")
        self.assertIn("jq(workspace-state, '.focused_special // false') == true ? 'S'", trial)
        self.assertIn("ws-style == \"numbers\" && jq(workspace-state, '.focused_special // false') == false", trial)
        self.assertIn("ws-style == \"squares\" && jq(workspace-state, '.focused_special // false') == false", trial)
        # The normal label fallback is preserved when no special is shown.
        self.assertIn('workspace-state.focused_label : "WS"', trial)

    def test_overview_rows_show_s_and_hide_only_their_numbers(self):
        row = definition(OVERVIEW, "workspace-monitor-row")
        self.assertIn("jq(monitor, '.special_visible // false') == true ? 'S' : monitor.label", row)
        self.assertIn(":visible {jq(monitor, '.special_visible // false') == false}", row)
        # The per-monitor chip list still exists for normal groups.
        self.assertIn("(workspace-choice :ws ws)", row)

    def test_live_bar_normal_path_is_untouched(self):
        trial = definition(OVERVIEW, "workspace-trial-bar")
        self.assertIn("(workspace-bar-choice :ws ws :square false)", trial)
        self.assertIn("(workspace-bar-choice :ws ws :square true)", trial)
        self.assertIn('ws-style == "numbers"', trial)
        self.assertIn('ws-style == "squares"', trial)

    def test_initial_state_shape_is_unchanged(self):
        initial = json.loads(re.search(r":initial '([^']*)'", OVERVIEW).group(1))
        self.assertNotIn("focused_special", initial)
        self.assertNotIn("special_visible", json.dumps(initial))

    def test_guarded_booleans_resolve_on_startup_and_old_state(self):
        # The initial listen JSON (pinned exactly by the read-only overview
        # tests) has no focused_special, and pre-existing monitor rows lack
        # special_visible. The live expressions must resolve those absences
        # to the normal rendering instead of tripping on missing fields.
        trial = definition(OVERVIEW, "workspace-trial-bar")
        row = definition(OVERVIEW, "workspace-monitor-row")
        bar_label = re.search(r":text \{(.+?)\}\)", trial).group(1)
        visibilities = re.findall(r":visible \{(.+?)\}", trial)
        numbers_visible = next(v for v in visibilities if "numbers" in v)
        squares_visible = next(v for v in visibilities if "squares" in v)
        row_label = re.search(r":text \{(.+?)\}", row).group(1)
        chips_visible = re.search(r":visible \{(.+?)\}", row).group(1)
        startup = {
            "workspace-state": json.loads(
                re.search(r":initial '([^']*)'", OVERVIEW).group(1)),
            "ws-style": "numbers",
        }
        self.assertEqual(eval_expr(bar_label, startup), "WS")
        # The two normal groups are mutually exclusive by ws-style: the
        # numbers style renders the numbers and hides the squares.
        self.assertTrue(eval_expr(numbers_visible, startup))
        self.assertFalse(eval_expr(squares_visible, startup))
        squares = dict(startup)
        squares["ws-style"] = "squares"
        self.assertEqual(eval_expr(bar_label, squares), "WS")
        self.assertFalse(eval_expr(numbers_visible, squares))
        self.assertTrue(eval_expr(squares_visible, squares))
        stale_row = {"monitor": {"label": "M1", "connector": "HDMI-A-1",
                                 "focused": False, "active_workspace": 1,
                                 "workspaces": []}}
        self.assertEqual(eval_expr(row_label, stale_row), "M1")
        self.assertTrue(eval_expr(chips_visible, stale_row))
        # The same guarded expressions render the special state when the
        # provider supplies the fields: the bar shows S and no numbered
        # group is visible while the special overlay is open, under either
        # ws-style.
        special_state = dict(startup)
        special_state["workspace-state"] = dict(startup["workspace-state"],
                                                focused_special=True)
        self.assertEqual(eval_expr(bar_label, special_state), "S")
        self.assertFalse(eval_expr(numbers_visible, special_state))
        self.assertFalse(eval_expr(squares_visible, special_state))
        special_squares = dict(special_state)
        special_squares["ws-style"] = "squares"
        self.assertEqual(eval_expr(bar_label, special_squares), "S")
        self.assertFalse(eval_expr(numbers_visible, special_squares))
        self.assertFalse(eval_expr(squares_visible, special_squares))
        open_row = {"monitor": dict(stale_row["monitor"], special_visible=True)}
        self.assertEqual(eval_expr(row_label, open_row), "S")
        self.assertFalse(eval_expr(chips_visible, open_row))


if __name__ == "__main__":
    unittest.main()
