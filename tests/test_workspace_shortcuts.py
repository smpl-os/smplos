"""Execute stock numbered bindings through the real Lua loader, without IPC."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
LUA = shutil.which("lua") or shutil.which("lua5.4")
LOADER = ROOT / "src/compositors/hyprland/hypr/bindings_loader.lua"
BINDINGS = ROOT / "src/shared/configs/smplos/bindings.conf"

HARNESS = r"""
local bindings, calls = {}, {}
local owners = {[1]=0, [2]=1, [3]=0}
local visible = {[0]=1, [1]=2}
local focused = 0
local function proxy(path)
    return setmetatable({}, {
        __index=function(_, key)
            return proxy(path == "" and key or path .. "." .. key)
        end,
        __call=function(_, value)
            return function()
                calls[#calls+1] = {path, value}
                if path == "focus" then
                    focused = assert(owners[value.workspace])
                    visible[focused] = value.workspace
                end
            end
        end,
    })
end
hl = {
    dsp=proxy(""),
    bind=function(keys, callback) bindings[keys]=callback end,
    define_submap=function(_, callback) callback() end,
}
_G.smplos_workspace_policy_active = arg[3] == "1"
dofile(arg[1]).load(arg[2])
local keys = {"SUPER + 3", "SUPER + 1"}
for _, key in ipairs(keys) do
    local callback = assert(bindings[key], "missing stock bind " .. key)
    callback()
end
assert(#calls == 2)
for i, workspace in ipairs({3, 1}) do
    assert(calls[i][1] == "focus", "numbered key did not invoke native focus")
    assert(calls[i][2].workspace == workspace)
    assert(calls[i][2].on_current_monitor == nil, "workspace must retain its home")
end
assert(visible[0] == 1 and visible[1] == 2 and focused == 0)
calls = {}
assert(bindings["SUPER + SHIFT + 1"])()
assert(#calls == 1)
if arg[3] == "1" then
    assert(calls[1][1] == "exec_cmd" and calls[1][2] == "workspace-ctl send 1")
else
    assert(calls[1][1] == "window.move" and calls[1][2].workspace == 1)
end
print('{"focus_only":true,"modified_move_preserved":true}')
"""


@unittest.skipUnless(LUA, "requires Lua")
class NumberedWorkspaceShortcutsTests(unittest.TestCase):
    def test_registered_super_one_and_three_only_focus_and_preserve_modified_moves(self):
        for enabled in (False, True):
            with self.subTest(policy=enabled):
                result = subprocess.run(
                    [LUA, "-", str(LOADER), str(BINDINGS), str(int(enabled))],
                    input=HARNESS, text=True, capture_output=True, check=True, timeout=5,
                )
                self.assertEqual(
                    json.loads(result.stdout),
                    {"focus_only": True, "modified_move_preserved": True},
                )


if __name__ == "__main__":
    unittest.main()
