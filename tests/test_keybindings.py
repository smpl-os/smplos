"""Keybinding tests: every stock bind gets its own tests, and the checker that runs them is tested.

  PYTHONPATH=tests python3 -m unittest test_keybindings -v             everything
  ... -k SUPER_TAB                                                      one bind (both kinds)
  ... -k window_management                                              one group of binds
  ... -k StaticBindTests | NativeBindTests | MessengerBindTests         one kind of check
  KEYBIND_LAB=1 ... -k LabTests                                         press the chords (below)

StaticBindTests    the rules in tools/keybind_check/rules.py, on what bindings_loader.lua really
                   registers for each bind, with the workspace policy off and on.
NativeBindTests    `Hyprland --verify-config` accepts each bind line, exactly as installed.
LabTests           opt-in (KEYBIND_LAB=1, needs a GPU render node): a headless Hyprland, the
                   chord typed on a virtual keyboard, and the effect checked. Local only.

A missing tool skips the checks that need it. KEYBIND_CHECK_REQUIRE=lua,xkbcommon,hyprland (comma
separated) makes a missing tool fail test_required_tools_are_installed instead, so a CI job that
should be checking can never pass by checking nothing. tools/keybind-check runs the same checks
with friendlier output; DEVELOPMENT.md has the whole story.
"""
import contextlib
import functools
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import typing
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from keybind_check import cli, lab, loader, model, native, rules, snapshot, xkb  # noqa: E402

SHIM = ROOT / "tools/keybind-check"
GENERATOR = ROOT / "src/shared/bin/generate-messenger-bindings"
DEFAULT_MESSENGERS = ROOT / "src/shared/configs/smplos/messengers.conf"

# A bindings.conf as installed before the scrolling-layout shortcut migration: `layoutmsg
# orientationnext` and `movewindow` do not exist in the scrolling layout (the Lua errors on
# Super+J and Super+Shift+Left/Right), and four chords are bound twice.
STALE_BINDINGS = """\
bindd = SUPER SHIFT, LEFT, Move column left, layoutmsg, movewindow l
bindd = SUPER SHIFT, RIGHT, Move column right, layoutmsg, movewindow r
bindd = SUPER SHIFT, LEFT, Swap window left, swapwindow, l
bindd = SUPER SHIFT, RIGHT, Swap window right, swapwindow, r
bindd = SUPER, R, Expand column to fill, layoutmsg, fit expand
bindd = SUPER, R, Resize mode (arrow keys to resize - Esc to exit), submap, resize
bindd = SUPER, J, Cycle layout orientation (left/top/right/bottom), layoutmsg, orientationnext
bindd = SUPER, S, Scratchpad, togglespecialworkspace, scratchpad
bindd = SUPER, S, Signal, exec, toggle-messenger "signal" signal-desktop

submap = resize
bindd = , LEFT, Shrink, resizeactive, -30 0
bindd = , escape, Done, submap, reset
submap = reset
"""

TOOLS = {
    "lua": (lambda: loader.lua_binary() is not None, "Lua (lua, lua5.4 or luajit)"),
    "xkbcommon": (xkb.available, "libxkbcommon"),
    "hyprland": (native.available, f"Hyprland (or {native.BINARY_ENV} pointing at it)"),
}
REQUIRED = {name.strip() for name in os.environ.get("KEYBIND_CHECK_REQUIRE", "").split(",") if name.strip()}


def need(*names):
    missing = [TOOLS[name][1] for name in names if not TOOLS[name][0]()]
    if missing:
        raise unittest.SkipTest("needs " + ", ".join(missing))


SOURCES = model.default_sources()
PARSED = model.load_sources(SOURCES)
BINDS = model.all_binds(PARSED)
NAMES = model.assign_names(BINDS)


class Loaded(typing.NamedTuple):
    recording: loader.Recording
    entries: list
    findings: list


@functools.cache
def stock_set(policy):
    """The stock binds loaded through the real loader, and every finding the rules report."""
    recording = loader.record(SOURCES, policy=policy)
    entries = loader.pair(PARSED, recording)
    return Loaded(recording, entries, rules.check_set(PARSED, recording, entries, rules.RepoResolver()))


def report(test, problems):
    if problems:
        test.fail("\n" + "\n".join(str(problem) for problem in problems))


def judge(sources):
    """Entries and findings of a set of bind files in both workspace policy modes (no repo-wide rules)."""
    parsed = model.load_sources(sources)
    entries, findings = [], []
    for policy in (False, True):
        recording = loader.record(sources, policy=policy)
        entries = loader.pair(parsed, recording)
        findings += rules.check_set(parsed, recording, entries, rules.RepoResolver(), with_repo=False)
    return entries, list(dict.fromkeys(findings))


@functools.cache
def baseline_findings():
    """What the rules say about the stock set alone, so a test about added binds blames only those."""
    return frozenset(judge(SOURCES)[1])


def static_problems(bind):
    """Findings about one bind line; one that only appears in one workspace policy says which."""
    modes = {}
    for policy in (False, True):
        for item in stock_set(policy).findings:
            if item.where == bind.where:
                modes.setdefault(str(item), set()).add(policy)
    return [text if len(on) == 2 else f"{text} (workspace policy {'on' if True in on else 'off'})"
            for text, on in modes.items()]


class Scratch(unittest.TestCase):
    """A scratch directory for the bind files a test writes."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="keybind-test-")
        self.addCleanup(tmp.cleanup)
        self.scratch = Path(tmp.name)

    def write(self, text, name="bindings.conf"):
        path = self.scratch / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


# ── One test per stock bind ─────────────────────────────────────────────────

class StaticBindTests(unittest.TestCase):
    """Each stock bind passes every static rule in both workspace policy modes (warnings too)."""

    @classmethod
    def setUpClass(cls):
        need("lua")
        for policy in (False, True):
            stock_set(policy)  # a loader/model parity failure is reported once, not per bind


class NativeBindTests(unittest.TestCase):
    """Hyprland's own parser accepts each stock bind, and the dispatch expressions it runs."""

    @classmethod
    def setUpClass(cls):
        need("lua", "hyprland")
        cls.entries = {entry.bind: entry for entry in stock_set(False).entries}
        cls.verifier = native.Verifier()
        cls.addClassCleanup(cls.verifier.close)

    def test_popup_watchers(self):
        """popup_watchers.lua, which registers the click-outside bind, loads."""
        report(self, self.verifier.check_file(model.POPUP_WATCHERS))


def _static_test(bind):
    def test(self):
        report(self, static_problems(bind))
    test.__doc__ = f"{bind.label}: {bind.desc}"
    return test


def _native_test(bind):
    def test(self):
        entry = self.entries.get(bind)
        if entry is None:
            self.skipTest("the loader does not register this line; the static test says why")
        report(self, self.verifier.check([entry]))
    test.__doc__ = f"{bind.label}: {bind.desc}"
    return test


def _add_bind_tests():
    for bind in BINDS:
        name = f"test_{NAMES[bind]}"
        setattr(StaticBindTests, name, _static_test(bind))
        setattr(NativeBindTests, name, _native_test(bind))


_add_bind_tests()


# ── The stock set as a whole ────────────────────────────────────────────────

class ParserTests(unittest.TestCase):
    def test_the_parser_sees_every_bind_line(self):
        """An independent count, so a parser that silently skipped lines cannot pass vacuously."""
        for item in PARSED:
            text = Path(item.source.path).read_text(encoding="utf-8")
            counted = len(re.findall(r"^[ \t]*bind[a-z]*[ \t]*=", text, re.M))
            self.assertEqual(counted, len(item.binds), item.source.name)
        self.assertEqual("stock", PARSED[0].source.name)
        self.assertTrue(PARSED[0].binds)

    def test_every_bind_gets_its_own_test_name_that_k_can_select(self):
        self.assertEqual(len(BINDS), len(set(NAMES.values())))
        for name in NAMES.values():
            self.assertRegex(name, r"^\w+$")


class StockSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        need("lua")

    def test_both_policy_modes_bind_the_same_keys(self):
        def keys(policy):
            return [(call.source, call.submap, call.keys) for call in stock_set(policy).recording.calls]
        self.assertEqual(keys(False), keys(True))

    def test_repository_wiring(self):
        """Bind file load order, the scrolling layout, the emergency binds, rule coverage of the
        loader, submaps, and chords clashing with popup_watchers.lua: findings about no one bind."""
        for policy in (False, True):
            wiring = [item for item in stock_set(policy).findings if item.where not in {b.where for b in BINDS}]
            with self.subTest(workspace_policy="on" if policy else "off"):
                report(self, wiring)

    def test_snapshot_matches_the_stock_binds(self):
        """Any change to a stock shortcut, or to how bindings_loader.lua translates one (a merge
        or revert that does it silently included), shows up as a diff a reviewer reads."""
        delta = snapshot.diff()
        if delta:
            self.fail("what the stock binds do changed. If that is intended, run "
                      "`tools/keybind-check snapshot --update` and commit the new snapshot.\n" + delta)


class ToolchainTests(unittest.TestCase):
    def test_required_tools_are_installed(self):
        """The checks above skip when Lua or Hyprland is missing; CI names the tools it needs."""
        unknown = REQUIRED - set(TOOLS)
        self.assertFalse(unknown, f"KEYBIND_CHECK_REQUIRE names unknown tools {sorted(unknown)}; "
                                  f"known: {sorted(TOOLS)}")
        missing = [TOOLS[name][1] for name in sorted(REQUIRED) if not TOOLS[name][0]()]
        self.assertFalse(missing, "required but not installed: " + ", ".join(missing))


# ── Binds generated at login ────────────────────────────────────────────────

class MessengerBindTests(Scratch):
    """generate-messenger-bindings adds binds at login; they must not clash with the stock set."""

    @classmethod
    def setUpClass(cls):
        need("lua")

    def generate(self, messengers, commands):
        """Run the real generator over the stock bindings.conf in a throw-away HOME."""
        config = self.scratch / "config"
        (config / "smplos").mkdir(parents=True)
        (config / "hypr").mkdir()
        (config / "smplos/bindings.conf").write_bytes(model.STOCK_BINDINGS.read_bytes())
        (config / "smplos/messengers.conf").write_text(messengers, encoding="utf-8")
        stubs = self.scratch / "bin"
        stubs.mkdir()
        for command in commands:
            (stubs / command).write_text("#!/bin/sh\nexit 99\n")
            (stubs / command).chmod(0o755)
        env = {**os.environ, "HOME": str(self.scratch), "XDG_CONFIG_HOME": str(config),
               "SMPLOS_PATH": str(self.scratch / "smplos"), "PATH": f"{stubs}:/usr/bin:/bin",
               "WAYLAND_DISPLAY": "", "NIRI_SOCKET": ""}
        result = subprocess.run(["bash", str(GENERATOR)], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(0, result.returncode, result.stderr)
        return config / "hypr/messenger-bindings.conf"

    def load(self, messenger_file):
        """The messenger binds, and the findings that adding the file to the stock set brings."""
        entries, findings = judge(model.default_sources(messenger=messenger_file))
        known = baseline_findings()
        return ([entry for entry in entries if entry.bind.source == "messenger"],
                [item for item in findings if item not in known])

    def default_list(self):
        text = DEFAULT_MESSENGERS.read_text(encoding="utf-8")
        commands = [line.split("|")[2].strip() for line in text.splitlines()
                    if line.count("|") == 2 and not line.lstrip().startswith("#")]
        return text, commands

    def test_the_default_messenger_list_does_not_clash_with_anything(self):
        mine, findings = self.load(self.generate(*self.default_list()))
        self.assertTrue(mine, "the generator produced no binds, so there is nothing to check")
        report(self, findings)

    def test_every_free_super_shift_key_can_go_to_a_messenger_without_a_clash(self):
        """A messenger per letter takes every key the generator thinks is free, so a stock bind
        the generator cannot see (another spelling, another file) shows up as a duplicate chord."""
        letters = "abcdefghijklmnopqrstuvwxyz"
        path = self.generate("".join(f"{letter.upper()} | class-{letter} | app-{letter}\n" for letter in letters),
                             [f"app-{letter}" for letter in letters])
        mine, findings = self.load(path)
        self.assertTrue(mine, "the generator produced no binds, so there is nothing to check")
        report(self, findings)

    def test_generated_binds_are_accepted_by_hyprland(self):
        need("hyprland")
        mine, _ = self.load(self.generate(*self.default_list()))
        with native.Verifier() as verifier:
            report(self, verifier.check(mine))

    def test_a_messenger_chord_that_the_stock_set_already_uses_is_reported(self):
        taken = BINDS[0]
        path = self.write(f"bindd = {taken.mods}, {taken.key}, Clash, exec, terminal\n", "messenger-bindings.conf")
        _, findings = self.load(path)
        self.assertEqual([("duplicate-chord", taken.label)], [(item.rule, item.label) for item in findings])


# ── The checker itself ──────────────────────────────────────────────────────

class CheckerSelfTests(Scratch):
    """Known-bad bind lines are caught; the checks would otherwise pass vacuously."""

    @classmethod
    def setUpClass(cls):
        need("lua")

    def findings(self, text, popup=False):
        path = self.write(text)
        sources = [model.Source("stock", path)]
        parsed = model.load_sources(sources)
        recording = loader.record(sources, policy=False, popup=popup)
        entries = loader.pair(parsed, recording)
        return rules.check_set(parsed, recording, entries, rules.RepoResolver(), with_repo=False)

    def test_the_stale_config_of_a_pre_migration_install_is_caught(self):
        found = {(item.label, item.rule) for item in self.findings(STALE_BINDINGS)}
        self.assertEqual({
            ("SUPER+J", "layout"),
            ("SUPER+SHIFT+LEFT", "layout"), ("SUPER+SHIFT+RIGHT", "layout"),
            ("SUPER+SHIFT+LEFT", "duplicate-chord"), ("SUPER+SHIFT+RIGHT", "duplicate-chord"),
            ("SUPER+R", "duplicate-chord"), ("SUPER+S", "duplicate-chord"),
        }, found)

    def test_a_clean_bind_is_not_reported(self):
        for command in ("terminal", "terminal | cat"):
            with self.subTest(command=command):
                self.assertEqual([], self.findings(f"bindd = SUPER, K, Run, exec, {command}\n"))

    def test_each_kind_of_mistake_is_reported_by_its_rule(self):
        mistakes = (
            ("bindd = Super, K, Run, exec, terminal", "modifiers"),
            ("bindd = $mod, K, Run, exec, terminal", "modifiers"),
            ("bindd = SUPER SUPER, K, Run, exec, terminal", "modifiers-repeat"),
            ("bindd = SUPER, NOSUCHKEY, Run, exec, terminal", "key"),
            ("bindxd = SUPER, K, Run, exec, terminal", "flags"),
            ("binderd = SUPER, K, Run, exec, terminal", "flags"),
            ("bindd = SUPER, K, desc", "fields"),
            ("bindd = SUPER, K, , exec, terminal", "description"),
            ("bindd = SUPER, K, Go, workspace, 3 # three", "comment"),
            ("bindd = SUPER, K, Go, workspace, banana", "workspace"),
            ("bindd = SUPER, K, Frob, frobnicate, 1", "dispatcher"),
            ("bindd = SUPER, K, Full, fullscreen, 7", "argument"),
            ("bindd = SUPER, K, Focus, movefocus, x", "argument"),
            ("bindd = SUPER, K, Go, submap, nowhere", "submap"),
            ("bindd = SUPER, K, Run, exec, definitely-not-installed-tool --flag", "exec-target"),
            ('bindd = SUPER, K, Run, exec, hyprctl dispatch "workspace 3"', "hyprctl-expression"),
        )
        for line, rule in mistakes:
            with self.subTest(line=line):
                self.assertIn(rule, {item.rule for item in self.findings(line + "\n")})

    def test_a_bind_that_popup_watchers_registers_again_is_caught(self):
        """The click-outside bind once sat in bindings.conf too, so every click ran it twice."""
        found = self.findings("bindn = , mouse:272, exec, popup-click-check\n", popup=True)
        self.assertEqual(["duplicate-chord"], [item.rule for item in found])
        self.assertIn("popup_watchers", found[0].where)

    def test_native_verification_reports_what_hyprland_rejects(self):
        need("hyprland")
        path = self.write("bindd = SUPER, NOSUCHKEY, Run, exec, terminal\n"
                          'bindd = SUPER, K, Run, exec, hyprctl dispatch "hl.dsp.window.nonexistent()"\n'
                          "bindd = SUPER, L, Run, exec, terminal\n")
        sources = [model.Source("stock", path)]
        entries = loader.pair(model.load_sources(sources), loader.record(sources, popup=False))
        with native.Verifier() as verifier:
            found = {(item.label, item.rule) for item in verifier.check(entries)}
        self.assertEqual({("SUPER+NOSUCHKEY", "native"), ("SUPER+K", "native-expression")}, found)

    def test_the_verifier_overrides_hyprlands_root_check_only_when_running_as_root(self):
        """CI containers run as root, where Hyprland will not load a config without the override."""
        parsed = subprocess.CompletedProcess([], 0, b"Config parsing result:\nconfig ok\n", b"")

        def launched_as(euid):
            with mock.patch.object(native.os, "geteuid", return_value=euid), \
                    mock.patch.object(native.subprocess, "run", return_value=parsed) as run, \
                    native.Verifier(hyprland="Hyprland") as verifier:
                self.assertTrue(verifier.expression("hl.dsp.exit()").ok)
            return run.call_args.args[0]

        self.assertIn(native.ROOT_OVERRIDE, launched_as(0))
        self.assertNotIn(native.ROOT_OVERRIDE, launched_as(1000))


class LoaderMappingTests(Scratch):
    """What bindings_loader.lua makes of a bind line; every row here once broke a real shortcut."""

    @classmethod
    def setUpClass(cls):
        need("lua")

    MAPPINGS = (
        # dispatcher and argument, the Lua action with the workspace policy off, and with it on
        ("fullscreen, 0", 'window.fullscreen({"mode":"fullscreen"})', None),
        ("fullscreen", 'window.fullscreen({"mode":"fullscreen"})', None),
        ("fullscreen, 1", 'window.fullscreen({"mode":"maximized"})', None),
        ("workspace, 3", 'focus({"workspace":3})', None),
        ("workspace, +1", 'focus({"workspace":"+1"})', 'exec_cmd("workspace-ctl select +1")'),
        ("workspace, -1", 'focus({"workspace":"-1"})', 'exec_cmd("workspace-ctl select -1")'),
        ("movetoworkspace, 3", 'window.move({"workspace":3})', 'exec_cmd("workspace-ctl send 3")'),
        ("movetoworkspacesilent, 3", 'window.move({"follow":false,"workspace":3})',
         'exec_cmd("workspace-ctl send 3 --silent")'),
        ("movetoworkspacesilent, special:scratchpad",
         'window.move({"follow":false,"workspace":"special:scratchpad"})', None),
    )

    def translate(self, dispatch, policy):
        path = self.write(f"bindd = SUPER, K, Test, {dispatch}\n")
        calls = loader.record([model.Source("stock", path)], policy=policy, popup=False).calls
        self.assertEqual(1, len(calls), dispatch)
        return snapshot.describe(calls[0]) + snapshot.options(calls[0])

    def test_the_loader_translates_each_bind_to_the_action_it_means(self):
        for dispatch, plain, policy in self.MAPPINGS:
            for on, expected in ((False, plain), (True, policy or plain)):
                with self.subTest(bind=dispatch, workspace_policy="on" if on else "off"):
                    self.assertEqual(expected, self.translate(dispatch, on))

    def test_numbered_workspace_navigation_never_runs_reconciliation_or_moves(self):
        for workspace in range(1, 11):
            for policy in (False, True):
                with self.subTest(workspace=workspace, policy=policy):
                    self.assertEqual(
                        f'focus({{"workspace":{workspace}}})',
                        self.translate(f"workspace, {workspace}", policy),
                    )


# ── The command line ────────────────────────────────────────────────────────

class CliTests(Scratch):
    @classmethod
    def setUpClass(cls):
        need("lua")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def stale_home(self, extra=""):
        """A HOME whose installed bindings.conf is the stale one, as on a machine awaiting Update OS."""
        home = self.scratch / "home"
        self.write(STALE_BINDINGS + extra, "home/.config/smplos/bindings.conf")
        return mock.patch.object(Path, "home", return_value=home)

    def test_check_passes_on_the_stock_binds(self):
        code, out, _ = self.run_cli("check", *(() if native.available() else ("--no-native",)))
        self.assertEqual(0, code, out)
        self.assertRegex(out, rf"OK: {len(BINDS)} bind\(s\)")

    def test_check_only_looks_at_the_chosen_bind(self):
        code, out, _ = self.run_cli("check", "--only", BINDS[0].label, "--no-native")
        self.assertEqual(0, code, out)
        self.assertIn("OK: 1 bind(s)", out)

    def test_check_fails_on_a_stale_bindings_file_and_names_the_broken_binds(self):
        path = self.write(STALE_BINDINGS)
        code, out, _ = self.run_cli("check", "--bindings", str(path), "--commands", "repo", "--no-native")
        self.assertEqual(1, code, out)
        for label in ("SUPER+J", "SUPER+SHIFT+LEFT", "SUPER+R", "SUPER+S"):
            self.assertIn(f"{label}: error[", out)
        self.assertIn("FAIL: 7 error(s)", out)

    def test_check_live_audits_the_installed_bindings_and_explains_the_fix(self):
        with self.stale_home():
            code, out, _ = self.run_cli("check", "--live", "--commands", "repo", "--no-native")
        self.assertEqual(1, code, out)
        self.assertIn("SUPER+J: error[layout]", out)
        self.assertIn("Update OS never rewrites a bindings.conf", out)

    def test_diff_live_shows_how_the_installed_bindings_differ_from_stock(self):
        with self.stale_home("bindd = SUPER CTRL ALT SHIFT, F24, Only here, exec, terminal\n"):
            code, out, _ = self.run_cli("diff", "--live", "--json")
        self.assertEqual(0, code, out)
        differences = {(row["kind"], row["chord"]) for row in json.loads(out)["differences"]}
        self.assertIn(("changed", "SUPER+SHIFT+LEFT"), differences)
        self.assertIn(("missing", "SUPER+RETURN"), differences)
        self.assertIn(("extra", "SUPER+CTRL+ALT+SHIFT+F24"), differences)

    def test_a_missing_bindings_file_and_an_unknown_selector_are_usage_errors(self):
        with mock.patch.object(Path, "home", return_value=self.scratch / "empty"):
            code, _, err = self.run_cli("check", "--live", "--no-native")
        self.assertEqual(2, code)
        self.assertIn("no bindings.conf", err)
        code, _, err = self.run_cli("check", "--only", "NO+SUCH+CHORD", "--no-native")
        self.assertEqual(2, code)
        self.assertIn("no bind matches", err)

    def test_list_names_every_stock_chord(self):
        code, out, _ = self.run_cli("list", "--json")
        self.assertEqual(0, code)
        listed = {row["chord"] for row in json.loads(out)}
        self.assertLessEqual({bind.label for bind in BINDS}, listed)

    def test_the_shim_runs_from_any_directory(self):
        self.assertTrue(os.access(SHIM, os.X_OK), "tools/keybind-check must be executable")
        result = subprocess.run([str(SHIM), "doctor"], capture_output=True, text=True, timeout=60,
                                cwd=self.scratch)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Lua", result.stdout)


# ── The lab: real chords in a headless Hyprland (opt-in) ────────────────────

@unittest.skipUnless(os.environ.get("KEYBIND_LAB") == "1",
                     "set KEYBIND_LAB=1 to press every chord in a headless Hyprland (needs a GPU render node)")
class LabTests(Scratch):
    @classmethod
    def setUpClass(cls):
        need("lua")
        problems = lab.preflight()
        if problems:  # asked for explicitly, so a lab that cannot run is a failure, not a skip
            raise AssertionError("KEYBIND_LAB=1 but the lab cannot run here: " + "; ".join(problems))

    def test_every_stock_chord_does_what_it_says(self):
        for policy in (False, True):
            loaded = stock_set(policy)
            with self.subTest(workspace_policy="on" if policy else "off"):
                results = lab.run(loaded.entries, SOURCES, policy=policy, show=False)
                self.assertEqual(len(loaded.entries), len(results))
                report(self, [f"{r.label} ({r.where}): {r.detail}" for r in results if r.status == lab.FAIL])
                skipped = [r for r in results if r.status == lab.SKIP]
                self.assertLessEqual(len(skipped), len(results) // 10,
                                     "the lab skipped too many binds: " + ", ".join(r.label for r in skipped))

    def test_the_lab_notices_the_broken_binds_of_a_stale_config(self):
        """The negative control: a lab that passes everything would pass this suite vacuously."""
        sources = model.default_sources(bindings=self.write(STALE_BINDINGS))
        parsed = model.load_sources(sources)
        entries = [entry for entry in loader.pair(parsed, loader.record(sources))
                   if entry.bind.source == "stock" and not entry.bind.submap]
        results = {}
        for result in lab.run(entries, sources, show=False):
            results.setdefault(result.label, []).append(result)
        for label, why in (("SUPER+J", "no such layoutmsg"), ("SUPER+SHIFT+LEFT", "no such layoutmsg"),
                           ("SUPER+R", "more than once"), ("SUPER+S", "more than once")):
            with self.subTest(chord=label):
                for result in results[label]:
                    self.assertEqual(lab.FAIL, result.status, result.detail)
                    self.assertIn(why, result.detail)


if __name__ == "__main__":
    unittest.main()
