"""Exercise keyboard MRU focus through the loader and an opt-in real compositor."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LUA = shutil.which("lua") or shutil.which("lua5.4")
LOADER = ROOT / "src/compositors/hyprland/hypr/bindings_loader.lua"
BINDINGS = ROOT / "src/shared/configs/smplos/bindings.conf"
sys.path.insert(0, str(ROOT / "tools"))
from keybind_check import lab, model  # noqa: E402

HARNESS = r"""
local bindings, calls = {}, {}
local monitors = {{id=0}, {id=1}, {id=2}}
local owners = {[1]=monitors[1], [4]=monitors[2], [6]=monitors[2], [10]=monitors[3]}
local visible = {[0]=1, [1]=4, [2]=10}
local focused, active = monitors[2], nil
local workspaces, windows = {}, {}
for _, id in ipairs({1, 4, 6, 10}) do
    workspaces[#workspaces+1] = {id=id, monitor=owners[id]}
end
local function workspace(id)
    for _, ws in ipairs(workspaces) do if ws.id == id then return ws end end
end
local function window(address, id, rank)
    local w = {address=address,workspace=workspace(id),monitor=owners[id],mapped=true,
               hidden=false,accepts_input=true,focus_history_id=rank}
    windows[#windows+1] = w
    return w
end
local source = window("source", 1, 0)
local older = window("older", 4, 4)
local recent = window("recent", 4, 1)
workspace(1).last_window, workspace(4).last_window = source, recent
active = source
local function focus(w)
    active = w
    if w then
        focused = w.monitor
        visible[focused.id] = w.workspace.id
        w.workspace.last_window = w
    end
end
local function proxy(path)
    return setmetatable({}, {
        __index=function(_, key)
            return proxy(path == "" and key or path .. "." .. key)
        end,
        __call=function(_, value)
            return function()
                calls[#calls+1] = {path, value}
                assert(path == "focus" or path == "exec_cmd" or path == "window.move",
                       "unexpected dispatcher " .. path)
                if path ~= "focus" then return end
                if value.window then
                    focus(value.window)
                elseif value.monitor then
                    if focused ~= value.monitor then
                        focused = value.monitor
                        focus(workspace(visible[focused.id]).last_window)
                    end
                elseif value.workspace then
                    local id = value.workspace
                    if type(id) ~= "number" then return end
                    local owner = assert(owners[id])
                    -- Hyprland's same-monitor, already-visible path does not
                    -- restore keyboard focus, even if it is on another output.
                    if focused ~= owner or visible[owner.id] ~= id then
                        focused = owner
                        visible[owner.id] = id
                        focus(workspace(id).last_window)
                    end
                end
            end
        end,
    })
end
hl = {
    dsp=proxy(""),
    bind=function(keys, callback) bindings[keys]=callback end,
    define_submap=function(_, callback) callback() end,
    dispatch=function(callback) callback() end,
    get_workspaces=function() return workspaces end,
    get_windows=function() return windows end,
    get_active_window=function() return active end,
}
_G.smplos_workspace_policy_active = arg[3] == "1"
dofile(arg[1]).load(arg[2])
local function press(number)
    assert(bindings["SUPER + " .. (number == 10 and "0" or number)])()
    assert(focused == owners[number], "target monitor not focused")
    assert(visible[focused.id] == number, "target workspace not activated")
    for _, call in ipairs(calls) do
        assert(call[1] == "focus", "navigation moved windows or reconciled homes")
        assert(not call[2].on_current_monitor, "workspace must retain its home")
    end
end
"""

SCENARIOS = {
    "all_numbers": """
for id = 1, 10 do
    if not workspace(id) then
        owners[id] = monitors[id % #monitors + 1]
        workspaces[#workspaces+1] = {id=id,monitor=owners[id]}
    end
    local remembered = window("target-" .. id, id, id)
    workspace(id).last_window = remembered
    active, focused = source, monitors[id % #monitors + 1]
    press(id)
    assert(active == remembered, "shortcut selected the wrong numbered target")
end
""",
    "visible": """
for _, pointer_monitor in ipairs(monitors) do
    active, focused = source, pointer_monitor
    press(4)
    assert(active == recent, "did not restore the remembered window")
    assert(visible[0] == 1 and visible[2] == 10, "another output changed")
end
""",
    "hidden": """
visible[1] = 6
recent.visible = false
press(4)
assert(active == recent, "hidden workspace lost its remembered focus")
""",
    "fresh_memory": """
press(4)
focus(older)
focus(source)
focused = monitors[2]
press(4)
assert(active == older, "callback captured old window instead of querying per press")
""",
    "stale_memory": """
for _, stale in ipairs({
    {mapped=false},
    {mapped=true,hidden=true},
    {mapped=true,accepts_input=false},
    {mapped=true,accepts_input=true,workspace=workspace(1)},
    {},
}) do
    workspace(4).last_window = stale
    active, focused = source, monitors[2]
    press(4)
    assert(active == recent, "did not fall back to eligible MRU")
end
""",
    "unranked": """
workspace(4).last_window = nil
older.focus_history_id = -1
press(4)
assert(active == recent, "unranked window beat MRU")
workspace(4).last_window = nil
recent.focus_history_id = -1
press(4)
assert(active == older, "no safe fallback for windows without focus history")
""",
    "ineligible": """
workspace(4).last_window = nil
window("unmapped",4,0).mapped = false
window("hidden",4,0).hidden = true
window("noinput",4,0).accepts_input = false
window("other-workspace",1,0)
press(4)
assert(active == recent, "ineligible candidate beat the target's MRU")
""",
    "empty": """
for _, id in ipairs({6, 10}) do
    for _, shown in ipairs({4, id}) do
        visible[owners[id].id] = shown
        active, focused = source, owners[id]
        press(id)
        assert(not active, "empty workspace retained old keyboard recipient")
    end
end
""",
    "no_active_window": """
active = nil
visible[1] = 6
press(6)
assert(not active, "empty target invented a keyboard recipient")
""",
    "new_workspace": """
-- No remembered window or instantiated workspace 10 at invocation time.
hl.get_workspaces = function() return {workspace(1),workspace(4),workspace(6)} end
press(10)
assert(not active, "new workspace retained old keyboard recipient")
""",
    "modified_moves": """
for _, item in ipairs({
    {"SUPER + SHIFT + 1", "workspace-ctl send 1", nil},
    {"SUPER + SHIFT + ALT + 1", "workspace-ctl send 1 --silent", false},
}) do
    calls = {}
    assert(bindings[item[1]])()
    assert(#calls == 1)
    if arg[3] == "1" then
        assert(calls[1][1] == "exec_cmd" and calls[1][2] == item[2])
    else
        assert(calls[1][1] == "window.move" and calls[1][2].workspace == 1)
        assert(calls[1][2].follow == item[3])
    end
end
""",
}


@unittest.skipUnless(LUA, "requires Lua")
class NumberedWorkspaceShortcutsTests(unittest.TestCase):
    def test_registered_shortcuts_focus_last_used_window_without_pointer_dependency(self):
        for enabled in (False, True):
            for name, scenario in SCENARIOS.items():
                with self.subTest(policy=enabled, scenario=name):
                    result = subprocess.run(
                        [LUA, "-", str(LOADER), str(BINDINGS), str(int(enabled))],
                        input=HARNESS + scenario, text=True, capture_output=True, timeout=5,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_custom_commands_and_non_numbered_selectors_are_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "bindings.conf"
            path.write_text("""\
bindd = SUPER, 4, Custom action, exec, my-workspace-command
bindd = SUPER, K, Named workspace, workspace, name:custom
bindd = SUPER, L, Relative workspace, workspace, +1
""")
            for policy in (False, True):
                result = subprocess.run(
                    [LUA, "-", str(LOADER), str(path), str(int(policy))],
                    input=HARNESS + """
bindings["SUPER + 4"]()
bindings["SUPER + K"]()
bindings["SUPER + L"]()
assert(calls[1][1] == "exec_cmd" and calls[1][2] == "my-workspace-command")
assert(calls[2][1] == "focus" and calls[2][2].workspace == "name:custom")
if arg[3] == "1" then
    assert(calls[3][1] == "exec_cmd" and calls[3][2] == "workspace-ctl select +1")
else
    assert(calls[3][1] == "focus" and calls[3][2].workspace == "+1")
end
""",
                    text=True, capture_output=True, timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(os.environ.get("KEYBIND_LAB") == "1",
                     "set KEYBIND_LAB=1 for isolated two-monitor Hyprland coverage")
class NativeWorkspaceFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        problems = lab.preflight()
        if problems:
            raise AssertionError("KEYBIND_LAB=1: " + "; ".join(problems))

    def test_number_shortcut_restores_keyboard_focus_independently_of_pointer(self):
        for policy, no_warps in ((p, w) for p in (False, True) for w in (False, True)):
            with self.subTest(policy=policy, no_warps=no_warps), \
                    mock.patch.object(lab, "WINDOW_COUNT", 3), \
                    lab.Lab([model.Source("stock", BINDINGS)], policy=policy) as desktop:
                self.assertEqual(desktop.hyprctl("output", "create", "headless")[0], 0)
                self.assertTrue(desktop.wait(lambda: len(desktop.json("monitors")) == 2, 5))
                code, out = desktop.hyprctl("repl", """
hl.monitor({output="HEADLESS-2",mode="1920x1080@60",position="1920x0",scale=1})
hl.workspace_rule({workspace="1",monitor="HEADLESS-1"})
hl.workspace_rule({workspace="4",monitor="HEADLESS-2"})
hl.workspace_rule({workspace="6",monitor="HEADLESS-2"})
hl.config({input={follow_mouse=2},cursor={no_warps=true}})
""")
                self.assertEqual(code, 0, out)
                self.assertFalse(any(desktop.json("configerrors")), out)
                source, older, recent = sorted(desktop.clients(), key=lambda c: c["title"])

                def focus(window):
                    self.assertEqual(desktop.dispatch(
                        f'hl.dsp.focus({{window="address:{window["address"]}"}})'), "ok")

                for window in (older, recent):
                    self.assertEqual(desktop.dispatch(
                        f'hl.dsp.window.move({{window="address:{window["address"]}",'
                        'workspace=4,follow=false})'), "ok")
                focus(older)
                focus(recent)
                focus(source)

                def point_at(x, y):
                    self.assertEqual(desktop.dispatch(
                        f"hl.dsp.cursor.move({{x={x},y={y}}})"), "ok")
                    time.sleep(0.1)

                def press(number):
                    key = "0" if number == 10 else str(number)
                    desktop.keyboard.tap(desktop.keymap.evdev_code(key), 64)
                    time.sleep(lab.SETTLE)

                # The pointer-selected monitor differs from keyboard focus.
                other = desktop.client(older["address"])
                point_at(max(1920, other["at"][0]) + 30, other["at"][1] + 30)
                self.assertEqual(desktop.active()["address"], source["address"])
                self.assertEqual(desktop.workspace()["id"], 4,
                                 (desktop.json("monitors"), desktop.clients(),
                                  desktop.hyprctl("cursorpos")))
                self.assertEqual(desktop.hyprctl(
                    "repl", "hl.config({cursor={no_warps="
                    + str(no_warps).lower() + "}})")[1], "ok")
                press(4)
                self.assertEqual(desktop.active()["address"], recent["address"])
                self.assertEqual(desktop.client(recent["address"])["workspace"]["id"], 4)
                self.assertEqual({m["name"]: m["activeWorkspace"]["id"]
                                  for m in desktop.json("monitors")},
                                 {"HEADLESS-1": 1, "HEADLESS-2": 4})

                # A hidden target must remember the window from before switching.
                self.assertEqual(desktop.dispatch("hl.dsp.focus({workspace=6})"), "ok")
                focus(source)
                point_at(100, 100)
                press(4)
                self.assertEqual(desktop.active()["address"], recent["address"])

                # Repeated selection must not pick the window under the pointer.
                other = desktop.client(older["address"])
                point_at(max(1920, other["at"][0]) + 30, other["at"][1] + 30)
                press(4)
                self.assertEqual(desktop.active()["address"], recent["address"])

                # Empty targets still activate their monitor/workspace safely.
                for _ in range(2):
                    focus(source)
                    point_at(2000, 100)
                    press(6)
                    self.assertEqual(desktop.workspace()["id"], 6)
                    self.assertFalse(desktop.active().get("address"))


if __name__ == "__main__":
    unittest.main()
