"""pointer.conf contract: the Lua loader, its hook in hyprland.lua and the update guards.

Everything runs against temporary files, a fake `hl` and a fake repository;
nothing reads or changes the live compositor.
"""

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest

from test_display_stack import BIN, HYPR, LUA_ENCODER, NEEDS_LUA, lua, plain
from test_workspace_rollout import function


LOADER_HARNESS = LUA_ENCODER + r'''
package.path = arg[1] .. "/?.lua;" .. package.path
local refused = arg[3]
hl = {config = function(spec)
    for key in pairs(spec.input) do
        if key == refused then error("rejected by fake hl") end
    end
    io.write("CALL ", encode(spec), "\n")
end}
print = function(...) io.write("LOG ", table.concat({...}, " "), "\n") end
require("pointer_loader").load(arg[2])
'''

ENTRY_HARNESS = r'''
local root, mode = arg[1], arg[2]
package.path = root .. "/?.lua;" .. package.path
local function note(text) io.write("EVENT ", text, "\n") end
for _, name in ipairs({"workspace_policy", "envs", "input", "looknfeel", "windows",
                       "aspect_column", "popup_watchers", "apps", "autostart", "opacity-policy"}) do
    package.preload[name] = function() note(name) return {} end
end
package.preload.monitors_loader = function() return {load = function() end} end
package.preload.bindings_loader = function() return {load = function() end} end
package.preload.pointer_loader = function()
    if mode == "broken-module" then error("broken module") end
    return {load = function(path)
        if mode == "broken-load" then error("broken load") end
        note("pointer_loader " .. path)
    end}
end
hl = {monitor = function() end}
local getenv = os.getenv
os.getenv = function(name) if name == "HOME" then return "/fixture-home" end return getenv(name) end
print = function(...) io.write("LOG ", table.concat({...}, " "), "\n") end
dofile(root .. "/hyprland.lua")
note("end")
'''


def split_output(output, event_kind):
    events, logs = [], []
    for line in output.splitlines():
        kind, _, payload = line.partition(" ")
        (events if kind == event_kind else logs).append(payload)
    return events, logs


@NEEDS_LUA
class PointerLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.conf = Path(self.temp.name) / "pointer.conf"

    def load(self, text, refused=None):
        """The raw hl.config calls and the log lines for a pointer.conf."""
        data = text if isinstance(text, bytes) else textwrap.dedent(text).encode()
        self.conf.write_bytes(data)
        output = lua(LOADER_HARNESS, HYPR, self.conf, *([refused] if refused else []))
        calls, logs = split_output(output, "CALL")
        return [json.loads(call) for call in calls], logs

    def options(self, text, refused=None):
        """The (option, value) pairs in the order hl.config received them."""
        calls, logs = self.load(text, refused)
        return [next(iter(plain(call)["input"].items())) for call in calls], logs

    def test_settings_output_is_applied_one_option_per_call(self):
        calls, logs = self.load("""\
            # Pointer options, written by smplOS Settings (Mouse tab).
            # Settings changes only the options in the input block below and keeps
            # every other line. Hyprland reads the file where its config loads it.
            input {
                sensitivity = 0.4
                accel_profile = flat
                natural_scroll = true
                scroll_factor = 1.5
            }
            """)
        self.assertEqual(logs, [])
        self.assertEqual([plain(call) for call in calls], [
            {"input": {"sensitivity": 0.4}},
            {"input": {"accel_profile": "flat"}},
            {"input": {"natural_scroll": True}},
            {"input": {"scroll_factor": 1.5}},
        ])
        kinds = [next(iter(call["input"].values()))[0] for call in calls]
        self.assertEqual(kinds, ["float", "string", "boolean", "float"])

    def test_options_arrive_in_a_fixed_order_and_numbers_as_floats(self):
        calls, logs = self.load("""\
            input {
                scroll_factor = 2
                natural_scroll = no
                accel_profile = adaptive
                sensitivity = 0
            }
            """)
        self.assertEqual(logs, [])
        self.assertEqual([next(iter(plain(call)["input"])) for call in calls],
                         ["sensitivity", "accel_profile", "natural_scroll", "scroll_factor"])
        self.assertEqual(next(iter(calls[0]["input"].values()))[0], "float")
        self.assertEqual(next(iter(calls[3]["input"].values()))[0], "float")

    def test_options_the_file_does_not_set_are_never_applied(self):
        for text in ("", "# only a comment\n", "input {\n}\n", "general {\n    sensitivity = 1\n}\n",
                     "input {\n    follow_mouse = 1\n}\n"):
            with self.subTest(text=text):
                self.assertEqual(self.load(text), ([], []))
        self.assertEqual(self.options("input {\n    sensitivity = -0.5\n}\n"),
                         ([("sensitivity", -0.5)], []))

    def test_only_the_top_level_input_block_is_read(self):
        options, logs = self.options("""\
            general {
                sensitivity = 1
                natural_scroll = true
            }
            input:accel_profile = adaptive
            input {
                kb_layout = de
                follow_mouse = 1
                sensitivity = 0.25
                touchpad {
                    natural_scroll = true
                    scroll_factor = 3
                }
                natural_scroll = false
            }
            misc {
                scroll_factor = 4
            }
            scroll_factor = 5
            """)
        self.assertEqual(options, [("sensitivity", 0.25), ("natural_scroll", False)])
        self.assertEqual(logs, [])

    def test_last_valid_assignment_wins_and_invalid_ones_never_cancel_it(self):
        options, logs = self.options("""\
            input {
                sensitivity = 0.1
                sensitivity = oops
                natural_scroll = true
                natural_scroll = maybe
                accel_profile = flat
            }
            input {
                accel_profile = adaptive
                sensitivity = -0.2
            }
            """)
        self.assertEqual(options, [("sensitivity", -0.2), ("accel_profile", "adaptive"),
                                   ("natural_scroll", True)])
        self.assertEqual(len(logs), 2)
        self.assertIn(":3: sensitivity: 'oops' is not a number; skipped", logs[0])
        self.assertIn(":5: natural_scroll: 'maybe' is not true or false; skipped", logs[1])

    def test_numbers_must_be_plain_decimals(self):
        for text, expected in {".5": 0.5, "+.5": 0.5, "-0.25": -0.25, "0": 0.0, "1.": 1.0}.items():
            with self.subTest(accepted=text):
                self.assertEqual(self.options(f"input {{\n sensitivity = {text}\n}}\n"),
                                 ([("sensitivity", expected)], []))
        for text in ("1e-1", "0x10", "inf", "nan", "", "abc", "0.4 0.5", "--1", "1.2.3",
                     ".", "+", "-", "0,5"):
            with self.subTest(rejected=text):
                options, logs = self.options(f"input {{\n sensitivity = {text}\n}}\n")
                self.assertEqual(options, [])
                self.assertEqual(len(logs), 1)
                self.assertIn(f":2: sensitivity: '{text}' is not a number; skipped", logs[0])

    def test_numbers_are_clamped_to_the_ranges_settings_offers(self):
        for key, text, expected in (("sensitivity", "1", 1.0), ("sensitivity", "-1", -1.0),
                                    ("scroll_factor", "0.1", 0.1), ("scroll_factor", "10", 10.0)):
            with self.subTest(key=key, text=text):
                self.assertEqual(self.options(f"input {{\n {key} = {text}\n}}\n"),
                                 ([(key, expected)], []))
        for key, text, expected, note in (
                ("sensitivity", "1.5", 1.0, "1.5 is outside -1..1; using 1"),
                ("sensitivity", "-3", -1.0, "-3 is outside -1..1; using -1"),
                ("scroll_factor", "0.05", 0.1, "0.05 is outside 0.1..10; using 0.1"),
                ("scroll_factor", "0", 0.1, "0 is outside 0.1..10; using 0.1"),
                ("scroll_factor", "-2", 0.1, "-2 is outside 0.1..10; using 0.1"),
                ("scroll_factor", "11", 10.0, "11 is outside 0.1..10; using 10")):
            with self.subTest(key=key, text=text):
                options, logs = self.options(f"input {{\n {key} = {text}\n}}\n")
                self.assertEqual(options, [(key, expected)])
                self.assertEqual(len(logs), 1)
                self.assertTrue(logs[0].endswith(f":2: {key}: {note}"), logs[0])

    def test_booleans_accept_the_hyprlang_spellings(self):
        for text, expected in {"true": True, "TRUE": True, "Yes": True, "on": True, "1": True,
                               "false": False, "No": False, "OFF": False, "0": False}.items():
            with self.subTest(accepted=text):
                calls, logs = self.load(f"input {{\n natural_scroll = {text}\n}}\n")
                self.assertEqual(logs, [])
                self.assertEqual(plain(calls[0]), {"input": {"natural_scroll": expected}})
                self.assertEqual(calls[0]["input"]["natural_scroll"][0], "boolean")
        for text in ("2", "maybe", "", "t", "enabled", "truee"):
            with self.subTest(rejected=text):
                options, logs = self.options(f"input {{\n natural_scroll = {text}\n}}\n")
                self.assertEqual(options, [])
                self.assertEqual(len(logs), 1)
                self.assertIn(f":2: natural_scroll: '{text}' is not true or false; skipped", logs[0])

    def test_accel_profile_forms(self):
        for text, expected in {
                "flat": "flat", "adaptive": "adaptive", "custom 0.2 0.0 1.0": "custom 0.2 0.0 1.0",
                "custom \t 0.2   0.0\t1.0 ": "custom 0.2 0.0 1.0", "custom 0.2 0.0": "custom 0.2 0.0",
                "": "", "[[EMPTY]]": "", "flat # steady": "flat"}.items():
            with self.subTest(accepted=text):
                calls, logs = self.load(f"input {{\n accel_profile = {text}\n}}\n")
                self.assertEqual(logs, [])
                self.assertEqual(plain(calls[0]), {"input": {"accel_profile": expected}})
                self.assertEqual(calls[0]["input"]["accel_profile"][0], "string")
        for text in ("Flat", "ADAPTIVE", "bogus", "custom", "custom 0.2", "custom a b c",
                     "custom 0.2 0x1 3", "custom 1e-1 2 3", "customs 0.2 0.0 1.0", "flat adaptive",
                     "[[empty]]"):
            with self.subTest(rejected=text):
                options, logs = self.options(f"input {{\n accel_profile = {text}\n}}\n")
                self.assertEqual(options, [])
                self.assertEqual(len(logs), 1)
                self.assertIn(f":2: accel_profile: '{text}' is not flat, adaptive or custom", logs[0])

    def test_comments_whitespace_and_crlf(self):
        options, logs = self.options(
            b"# header\r\ninput {   # pointer\r\n\tsensitivity=0.3   # no spaces around =\r\n"
            b"    # natural_scroll = true\r\n    natural_scroll = off # trailing\r\n}   # end\r\n")
        self.assertEqual(options, [("sensitivity", 0.3), ("natural_scroll", False)])
        self.assertEqual(logs, [])

    def test_binary_garbage_applies_nothing_and_cannot_raise(self):
        self.assertEqual(self.load(b"\xff\xfe\x00input {\n\x00sensitivity = 0.5\n}\n\x00\x00"), ([], []))

    def test_a_refused_option_does_not_block_the_others(self):
        calls, logs = self.load("""\
            input {
                sensitivity = 0.3
                accel_profile = flat
                natural_scroll = true
                scroll_factor = 2
            }
            """, refused="accel_profile")
        self.assertEqual([next(iter(plain(call)["input"])) for call in calls],
                         ["sensitivity", "natural_scroll", "scroll_factor"])
        self.assertEqual(len(logs), 1)
        self.assertRegex(logs[0], r"^pointer_loader: accel_profile: .*rejected by fake hl$")

    def test_missing_file_is_silent(self):
        self.assertEqual(lua(LOADER_HARNESS, HYPR, self.conf.with_name("absent.conf")), "")

    def test_unreadable_file_is_reported_not_raised(self):
        self.conf.mkdir()
        calls, logs = split_output(lua(LOADER_HARNESS, HYPR, self.conf), "CALL")
        self.assertEqual(calls, [])
        self.assertEqual(len(logs), 1)
        self.assertTrue(logs[0].startswith(f"pointer_loader: {self.conf}: "), logs[0])


class EntryPointTests(unittest.TestCase):
    def run_entry(self, mode="ok"):
        return split_output(lua(ENTRY_HARNESS, HYPR, mode), "EVENT")

    @NEEDS_LUA
    def test_saved_pointer_options_load_after_the_input_defaults(self):
        events, logs = self.run_entry()
        loader = "pointer_loader /fixture-home/.config/hypr/pointer.conf"
        self.assertEqual(logs, [])
        self.assertIn(loader, events)
        self.assertLess(events.index("input"), events.index(loader))
        self.assertEqual(events[-1], "end")

    @NEEDS_LUA
    def test_loader_failure_cannot_abort_the_lua_config(self):
        for mode in ("broken-load", "broken-module"):
            with self.subTest(mode):
                events, logs = self.run_entry(mode)
                self.assertEqual(len(logs), 1)
                self.assertIn("pointer_loader failed", logs[0])
                self.assertIn("looknfeel", events)
                self.assertEqual(events[-1], "end")

    def test_hyprlang_rollback_does_not_source_pointer_conf(self):
        self.assertNotIn(
            "pointer.conf", (HYPR / "hyprland.conf").read_text(encoding="utf-8"),
            "hyprland.conf must not source pointer.conf: Hyprland reports a missing `source =` "
            "target as a config error, and Settings creates the file only on the first change "
            "in Mouse. See README.md, 'pointer.conf contract'.")


def protected_by_os_update():
    text = (BIN / "smplos-os-update").read_text(encoding="utf-8")
    block = re.search(r"local protected=\(\n(.*?)\n\s*\)", text, re.S).group(1)
    return set(re.findall(r"^\s*([\w.-]+)\s*(?:#.*)?$", block, re.M))


def protected_by_update_check():
    tree = ast.parse((BIN / "smplos-update-check").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "USER_HYPR" for target in node.targets):
            return set(ast.literal_eval(node.value))
    raise AssertionError("USER_HYPR is missing from smplos-update-check")


class UpdateGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.home = root / "home"
        self.repo = root / "repo"
        self.hypr = self.home / ".config/hypr"
        self.stock = self.repo / "src/compositors/hyprland/hypr"
        self.hypr.mkdir(parents=True)
        self.stock.mkdir(parents=True)

    def sync(self):
        script = ("set -euo pipefail\n"
                  "header() { :; }; log() { :; }; ok() { :; }\n"
                  'die() { echo "$*" >&2; exit 1; }\n'
                  'as_invoker() { "$@"; }\n'
                  + function("copy_user_config") + function("sync_hypr_configs")
                  + "\nsync_hypr_configs\n")
        env = dict(os.environ, HOME=str(self.home), SMPLOS_REPO=str(self.repo))
        subprocess.run(["bash", "-c", script], env=env, check=True, timeout=15,
                       capture_output=True, text=True)

    def test_both_update_scripts_protect_pointer_conf_and_agree(self):
        updater, checker = protected_by_os_update(), protected_by_update_check()
        self.assertIn("pointer.conf", updater)
        self.assertIn("pointer.conf", checker)
        self.assertEqual(updater, checker,
                         "smplos-os-update and smplos-update-check must protect the same files")

    def test_sync_installs_the_loader_but_never_touches_pointer_conf(self):
        (self.hypr / "hypridle.conf").write_text("# idle\n")
        for name, text in {"pointer_loader.lua": "-- loader\n", "hyprland.lua": "-- entry\n",
                           "pointer.conf": "# stock, never installed\n"}.items():
            (self.stock / name).write_text(text)
        saved = "input {\n    sensitivity = 0.4\n}\n"
        (self.hypr / "pointer.conf").write_text(saved)
        self.sync()
        self.assertEqual((self.hypr / "pointer.conf").read_text(), saved)
        self.assertEqual((self.hypr / "pointer_loader.lua").read_text(), "-- loader\n")
        self.assertEqual((self.hypr / "hyprland.lua").read_text(), "-- entry\n")
        (self.hypr / "pointer.conf").unlink()
        self.sync()
        self.assertFalse((self.hypr / "pointer.conf").exists())


if __name__ == "__main__":
    unittest.main()
