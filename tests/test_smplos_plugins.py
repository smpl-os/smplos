"""smplos-plugins: ABI keys, loading, building and pruning, with every external tool faked."""

import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/shared/bin/smplos-plugins"

INSTALLED_COMMIT = "a" * 40
OLD_COMMIT = "b" * 40


def version_h(commit, aq="0.15.1", hu="0.14.2", hg="0.5.1", hc="0.1.13", hlg="0.6.8"):
    return (
        "#pragma once\n"
        f'#define GIT_COMMIT_HASH    "{commit}"\n'
        '#define GIT_BRANCH         "v0.56.2"\n'
        f'#define AQUAMARINE_VERSION "{aq}"\n'
        "#define AQUAMARINE_VERSION_MAJOR 0\n"
        f'#define HYPRLANG_VERSION     "{hlg}"\n'
        f'#define HYPRUTILS_VERSION    "{hu}"\n'
        f'#define HYPRCURSOR_VERSION   "{hc}"\n'
        f'#define HYPRGRAPHICS_VERSION "{hg}"\n'
    )


def abi(commit):
    return f"{commit}_aq_0.15_hu_0.14_hg_0.5_hc_0.1_hlg_0.6"


FAKE_HYPRCTL = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as out:
    out.write(json.dumps(args) + "\\n")
if os.environ.get("NO_SESSION") == "1":
    print("HYPRLAND_INSTANCE_SIGNATURE not set!", file=sys.stderr)
    sys.exit(1)
path = os.environ["FAKE_STATE"]
state = json.load(open(path)) if os.path.exists(path) else {"plugins": []}
if args == ["version"]:
    print("Hyprland fake")
elif args == ["-j", "version"]:
    print(json.dumps({"branch": "x", "abiHash": os.environ["RUNNING_ABI"]}, indent=2))
elif args[:2] == ["plugin", "list"]:
    if not state["plugins"]:
        print("no plugins loaded")
    for plugin in state["plugins"]:
        print(f"Plugin {plugin['name']} by smplOS:\\n\\tHandle: 1\\n\\tVersion: 1.0\\n\\tDescription: fake\\n")
elif args[:2] == ["plugin", "load"]:
    if os.environ.get("FAIL_LOAD") == "1":
        print("plugin failed to load")
    else:
        name = os.path.basename(args[2]).split(".")[0]
        state["plugins"].append({"name": name, "path": args[2]})
        json.dump(state, open(path, "w"))
        print("ok")
elif args[:2] == ["plugin", "unload"]:
    kept = [p for p in state["plugins"] if p["path"] != args[2]]
    print("ok" if len(kept) != len(state["plugins"]) else "plugin not loaded")
    state["plugins"] = kept
    json.dump(state, open(path, "w"))
"""

FAKE_MAKE = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_MAKE_CALLS"], "a") as out:
    out.write(json.dumps(args) + "\\n")
source = args[args.index("-C") + 1]
if os.environ.get("FAIL_MAKE") in ("1", os.path.basename(source)):
    print("x.cpp:1: error: boom", file=sys.stderr)
    sys.exit(2)
build = next(a.split("=", 1)[1] for a in args if a.startswith("BUILD="))
os.makedirs(build, exist_ok=True)
with open(os.path.join(build, os.path.basename(source) + ".so"), "w") as out:
    out.write("plugin built from " + open(os.path.join(source, "x.cpp")).read())
"""


class PluginToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.plugins = self.root / "plugins"
        self.src = self.root / "plugin-src"
        self.tmpdir = self.root / "tmp"
        self.state = self.root / "state"
        for directory in (self.bin, self.plugins, self.src / "smpl-hud", self.tmpdir, self.state):
            directory.mkdir(parents=True)
        (self.src / "smpl-hud/Makefile").write_text("all:\n")
        self.source_file = self.src / "smpl-hud/x.cpp"
        self.source_file.write_text("v1")
        self.headers = self.root / "version.h"
        self.headers.write_text(version_h(INSTALLED_COMMIT))
        self.calls = self.root / "hypr-calls"
        self.make_calls = self.root / "make-calls"
        self.notices = self.root / "notices"

        self.fake("hyprctl", FAKE_HYPRCTL)
        self.fake("make", FAKE_MAKE)
        self.fake("g++", "#!/bin/sh\nexit 0\n")
        self.fake("pkg-config", "#!/bin/sh\nexit 0\n")
        self.fake("notify-send", f'#!/bin/sh\necho "$*" >> "{self.notices}"\n')

        self.env = dict(
            os.environ, HOME=str(self.root), XDG_STATE_HOME=str(self.state), TMPDIR=str(self.tmpdir),
            PATH=f"{self.bin}:{os.environ['PATH']}", SMPLOS_PLUGIN_DIR=str(self.plugins),
            SMPLOS_HYPRLAND_VERSION_H=str(self.headers), FAKE_CALLS=str(self.calls),
            FAKE_MAKE_CALLS=str(self.make_calls), FAKE_STATE=str(self.root / "loaded.json"),
            RUNNING_ABI=abi(INSTALLED_COMMIT),
        )
        for key in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "SMPLOS_INVOKER_USER",
                    "SMPLOS_PATH", "CXX", "NO_SESSION", "FAIL_LOAD", "FAIL_MAKE"):
            self.env.pop(key, None)

    def fake(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def run_tool(self, *args, **env):
        return subprocess.run(["bash", str(SCRIPT), *args], env=dict(self.env, **env),
                              capture_output=True, text=True, timeout=60)

    def binary(self, commit, content="old build", name="smpl-hud"):
        path = self.plugins / f"{name}.{abi(commit)}.so"
        path.write_text(content)
        return path

    def loaded(self):
        state = self.root / "loaded.json"
        return json.loads(state.read_text())["plugins"] if state.exists() else []

    def hypr_calls(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def builds(self):
        return [json.loads(line) for line in self.make_calls.read_text().splitlines()] if self.make_calls.exists() else []

    def plugin_files(self):
        return sorted(path.name for path in self.plugins.iterdir())


class AbiTests(PluginToolTests):
    def test_installed_key_follows_hyprlands_formula(self):
        self.headers.write_text(version_h("c" * 40, aq="0.15.1", hu="0.14.2", hg="0.5.1", hc="0.1.13", hlg="0.6.8"))
        result = self.run_tool("abi", "--installed")
        self.assertEqual((result.returncode, result.stdout.strip()), (0, abi("c" * 40)))

    def test_version_without_patch_component_is_kept(self):
        self.headers.write_text(version_h("c" * 40, hu="7"))
        self.assertIn("_hu_7_", self.run_tool("abi", "--installed").stdout)

    def test_running_key_wins_and_installed_is_the_fallback(self):
        self.assertEqual(self.run_tool("abi", RUNNING_ABI="running-key").stdout.strip(), "running-key")
        self.assertEqual(self.run_tool("abi", "--running", RUNNING_ABI="running-key").stdout.strip(), "running-key")
        self.assertEqual(self.run_tool("abi", "--installed", RUNNING_ABI="running-key").stdout.strip(),
                         abi(INSTALLED_COMMIT))
        offline = self.run_tool("abi", NO_SESSION="1")
        self.assertEqual((offline.returncode, offline.stdout.strip()), (0, abi(INSTALLED_COMMIT)))
        self.assertEqual(self.run_tool("abi", "--running", NO_SESSION="1").returncode, 1)

    def test_unusable_headers_give_no_key(self):
        self.headers.write_text(version_h("not-a-commit"))
        self.assertEqual(self.run_tool("abi", "--installed").returncode, 1)
        self.headers.unlink()
        self.assertEqual(self.run_tool("abi", "--installed").returncode, 1)

    def test_abi_matches_the_header_on_this_machine(self):
        real = Path("/usr/include/hyprland/src/version.h")
        if not real.exists():
            self.skipTest("hyprland headers not installed")
        key = self.run_tool("abi", "--installed", SMPLOS_HYPRLAND_VERSION_H=str(real)).stdout.strip()
        self.assertRegex(key, r"^[0-9a-f]{40}_aq_[\d.]+_hu_[\d.]+_hg_[\d.]+_hc_[\d.]+_hlg_[\d.]+$")


class LoadTests(PluginToolTests):
    def test_outside_a_session_is_a_silent_noop(self):
        self.binary(INSTALLED_COMMIT)
        result = self.run_tool("load", NO_SESSION="1")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual([call for call in self.hypr_calls() if call[0] == "plugin"], [])

    def test_loads_only_the_binary_built_for_the_running_compositor(self):
        stale = self.binary(OLD_COMMIT)
        current = self.binary(INSTALLED_COMMIT)
        self.assertEqual(self.run_tool("load").returncode, 0)
        self.assertEqual([plugin["path"] for plugin in self.loaded()], [str(current)])
        self.assertNotIn(str(stale), json.dumps(self.hypr_calls()))

    def test_load_is_idempotent(self):
        self.binary(INSTALLED_COMMIT)
        self.run_tool("load")
        self.run_tool("load")
        loads = [call for call in self.hypr_calls() if call[:2] == ["plugin", "load"]]
        self.assertEqual(len(loads), 1)
        self.assertEqual(len(self.loaded()), 1)

    def test_nothing_installed_is_silent(self):
        result = self.run_tool("load")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertFalse(self.notices.exists())

    def test_binary_for_another_hyprland_warns_once_per_version(self):
        self.binary(OLD_COMMIT)
        first = self.run_tool("load")
        self.assertEqual(first.returncode, 0)
        self.assertIn("another Hyprland version", first.stderr)
        self.assertEqual(self.loaded(), [])
        self.assertEqual(len(self.notices.read_text().splitlines()), 1)
        self.assertEqual(self.run_tool("load").stderr, "")
        self.assertEqual(len(self.notices.read_text().splitlines()), 1)
        again = self.run_tool("load", RUNNING_ABI=abi("c" * 40))
        self.assertIn("another Hyprland version", again.stderr)
        self.assertEqual(len(self.notices.read_text().splitlines()), 2)

    def test_load_failure_is_reported(self):
        self.binary(INSTALLED_COMMIT)
        result = self.run_tool("load", FAIL_LOAD="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("failed to load smpl-hud", result.stderr)

    def test_unload_and_reload(self):
        current = self.binary(INSTALLED_COMMIT)
        self.run_tool("load")
        self.assertEqual(self.run_tool("unload").returncode, 0)
        self.assertEqual(self.loaded(), [])
        self.assertEqual(self.run_tool("reload").returncode, 0)
        self.assertEqual([plugin["path"] for plugin in self.loaded()], [str(current)])
        self.run_tool("reload", "smpl-hud")
        self.assertEqual(len(self.loaded()), 1)

    def test_rejects_unsafe_plugin_names(self):
        self.assertEqual(self.run_tool("load", "../evil").returncode, 1)
        self.assertEqual(self.run_tool("bogus").returncode, 2)

    def test_status_reports_keys_and_state(self):
        self.binary(OLD_COMMIT)
        self.binary(INSTALLED_COMMIT)
        self.run_tool("load")
        rows = [line.split() for line in self.run_tool("status").stdout.splitlines()]
        self.assertIn(["smpl-hud", abi(INSTALLED_COMMIT), "running", "installed", "loaded"], rows)
        self.assertIn(["smpl-hud", abi(OLD_COMMIT), "stale"], rows)


class SyncTests(PluginToolTests):
    def sync(self, *args, **env):
        return self.run_tool("sync", "--src", str(self.src), *args, **env)

    def test_builds_out_of_tree_and_installs_under_the_installed_key(self):
        os.chmod(self.src / "smpl-hud", 0o555)
        self.addCleanup(os.chmod, self.src / "smpl-hud", 0o755)
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        binary = self.plugins / f"smpl-hud.{abi(INSTALLED_COMMIT)}.so"
        self.assertEqual(binary.read_text(), "plugin built from v1")
        self.assertEqual(stat.S_IMODE(binary.stat().st_mode), 0o755)
        self.assertTrue(Path(f"{binary}.src-sha256").is_file())
        [call] = self.builds()
        self.assertEqual(call[:2], ["-C", str(self.src / "smpl-hud")])
        build_dir = next(arg for arg in call if arg.startswith("BUILD=")).split("=", 1)[1]
        self.assertTrue(build_dir.startswith(str(self.tmpdir)))
        self.assertEqual(call[-1], "all")
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_unchanged_source_is_not_rebuilt_but_changes_and_rebuild_are(self):
        self.sync()
        self.sync()
        self.assertEqual(len(self.builds()), 1)
        self.source_file.write_text("v2")
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(len(self.builds()), 2)
        binary = self.plugins / f"smpl-hud.{abi(INSTALLED_COMMIT)}.so"
        self.assertEqual(binary.read_text(), "plugin built from v2")
        self.sync("--rebuild")
        self.assertEqual(len(self.builds()), 3)

    def test_prunes_other_hyprland_builds_but_keeps_the_running_one(self):
        old = self.binary(OLD_COMMIT)
        Path(f"{old}.src-sha256").write_text("x\n")
        running = self.binary("c" * 40)
        result = self.sync(RUNNING_ABI=abi("c" * 40))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.plugin_files(), sorted([
            running.name, f"smpl-hud.{abi(INSTALLED_COMMIT)}.so", f"smpl-hud.{abi(INSTALLED_COMMIT)}.so.src-sha256"]))

    def test_failed_build_keeps_everything_and_fails(self):
        old = self.binary(OLD_COMMIT)
        result = self.sync(FAIL_MAKE="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("build failed", result.stderr)
        self.assertIn("boom", result.stderr)
        self.assertEqual(self.plugin_files(), [old.name])
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_missing_headers_or_sources_fail_clearly(self):
        self.headers.unlink()
        self.assertIn("headers not found", self.sync().stderr)
        self.assertEqual(self.sync().returncode, 1)
        self.headers.write_text(version_h(INSTALLED_COMMIT))
        missing = self.run_tool("sync", "--src", str(self.root / "nope"))
        self.assertEqual(missing.returncode, 1)
        self.assertIn("no plugin sources", missing.stderr)

    def test_missing_toolchain_is_reported(self):
        result = self.sync(CXX="no-such-compiler-for-smplos")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing no-such-compiler-for-smplos", result.stderr)
        self.assertEqual(self.builds(), [])

    def test_only_directories_with_a_makefile_are_plugins(self):
        (self.src / "notes").mkdir()
        (self.src / "notes/x.cpp").write_text("nope")
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(len(self.builds()), 1)

    def test_reload_loads_the_fresh_binary_into_the_running_compositor(self):
        result = self.sync("--reload")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([plugin["path"] for plugin in self.loaded()],
                         [str(self.plugins / f"smpl-hud.{abi(INSTALLED_COMMIT)}.so")])
        self.source_file.write_text("v2")
        self.sync("--reload")
        calls = [call[:2] for call in self.hypr_calls() if call[0] == "plugin" and call[1] != "list"]
        self.assertEqual(calls, [["plugin", "load"], ["plugin", "unload"], ["plugin", "load"]])
        self.assertEqual(len(self.loaded()), 1)

    def test_reload_leaves_a_plugin_for_a_not_yet_running_hyprland_alone(self):
        running = self.binary(OLD_COMMIT, "running build")
        self.run_tool("load", RUNNING_ABI=abi(OLD_COMMIT))
        self.assertEqual(len(self.loaded()), 1)
        result = self.sync("--reload", RUNNING_ABI=abi(OLD_COMMIT))
        self.assertEqual(result.returncode, 0, result.stderr)
        unloads = [call for call in self.hypr_calls() if call[:2] == ["plugin", "unload"]]
        self.assertEqual(unloads, [])
        self.assertTrue(running.exists())
        self.assertEqual(len(self.loaded()), 1)

    def test_reload_without_a_session_still_installs(self):
        result = self.sync("--reload", NO_SESSION="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.plugins / f"smpl-hud.{abi(INSTALLED_COMMIT)}.so").exists())
        self.assertEqual(self.loaded(), [])


class MultiplePluginTests(PluginToolTests):
    """smpl-hud and smpl-scroll ship together: each is built, kept, pruned and loaded on its own."""

    def setUp(self):
        super().setUp()
        (self.src / "smpl-scroll").mkdir()
        (self.src / "smpl-scroll/Makefile").write_text("all:\n")
        (self.src / "smpl-scroll/x.cpp").write_text("scroll v1")

    def sync(self, *args, **env):
        return self.run_tool("sync", "--src", str(self.src), *args, **env)

    def built(self):
        return [Path(call[1]).name for call in self.builds()]

    def names(self):
        return sorted(plugin["name"] for plugin in self.loaded())

    def test_sync_builds_and_installs_every_plugin(self):
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(self.built()), ["smpl-hud", "smpl-scroll"])
        for name, source in (("smpl-hud", "v1"), ("smpl-scroll", "scroll v1")):
            binary = self.plugins / f"{name}.{abi(INSTALLED_COMMIT)}.so"
            self.assertEqual(binary.read_text(), f"plugin built from {source}")
            self.assertTrue(Path(f"{binary}.src-sha256").is_file())

    def test_only_the_plugin_whose_source_changed_is_rebuilt(self):
        self.sync()
        self.sync()
        self.assertEqual(len(self.builds()), 2)
        (self.src / "smpl-scroll/x.cpp").write_text("scroll v2")
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(self.built()[2:], ["smpl-scroll"])

    def test_a_failing_plugin_does_not_stop_the_others(self):
        result = self.sync(FAIL_MAKE="smpl-hud")
        self.assertEqual(result.returncode, 1)
        self.assertIn("smpl-hud: build failed", result.stderr)
        self.assertEqual(self.plugin_files(), sorted([
            f"smpl-scroll.{abi(INSTALLED_COMMIT)}.so", f"smpl-scroll.{abi(INSTALLED_COMMIT)}.so.src-sha256"]))

    def test_old_hyprland_builds_are_pruned_per_plugin(self):
        old = [self.binary(OLD_COMMIT, name=name) for name in ("smpl-hud", "smpl-scroll")]
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual([path.exists() for path in old], [False, False])
        self.assertEqual(len(self.plugin_files()), 4)

    def test_load_loads_every_plugin_built_for_the_running_compositor(self):
        hud = self.binary(INSTALLED_COMMIT)
        scroll = self.binary(INSTALLED_COMMIT, name="smpl-scroll")
        self.assertEqual(self.run_tool("load").returncode, 0)
        self.assertEqual(sorted(plugin["path"] for plugin in self.loaded()), sorted([str(hud), str(scroll)]))
        self.run_tool("load")
        loads = [call for call in self.hypr_calls() if call[:2] == ["plugin", "load"]]
        self.assertEqual(len(loads), 2)
        rows = [line.split() for line in self.run_tool("status").stdout.splitlines()]
        self.assertIn(["smpl-scroll", abi(INSTALLED_COMMIT), "running", "installed", "loaded"], rows)

    def test_unload_and_reload_can_target_one_plugin(self):
        self.binary(INSTALLED_COMMIT)
        self.binary(INSTALLED_COMMIT, name="smpl-scroll")
        self.run_tool("load")
        self.assertEqual(self.run_tool("unload", "smpl-scroll").returncode, 0)
        self.assertEqual(self.names(), ["smpl-hud"])
        self.assertEqual(self.run_tool("reload", "smpl-scroll").returncode, 0)
        self.assertEqual(self.names(), ["smpl-hud", "smpl-scroll"])

    def test_a_stale_plugin_does_not_keep_the_current_one_from_loading(self):
        self.binary(INSTALLED_COMMIT)
        self.binary(OLD_COMMIT, name="smpl-scroll")
        result = self.run_tool("load")
        self.assertEqual(result.returncode, 0)
        self.assertIn("smpl-scroll was built for another Hyprland version", result.stderr)
        self.assertEqual(self.names(), ["smpl-hud"])

    def test_reload_after_sync_swaps_only_the_rebuilt_plugin(self):
        self.assertEqual(self.sync("--reload").returncode, 0)
        self.assertEqual(self.names(), ["smpl-hud", "smpl-scroll"])
        (self.src / "smpl-scroll/x.cpp").write_text("scroll v2")
        self.assertEqual(self.sync("--reload").returncode, 0)
        unloads = [call for call in self.hypr_calls() if call[:2] == ["plugin", "unload"]]
        self.assertEqual(len(unloads), 1)
        self.assertIn("smpl-scroll.", unloads[0][2])
        self.assertEqual(self.names(), ["smpl-hud", "smpl-scroll"])


class OsUpdateSyncPluginsTests(unittest.TestCase):
    """sync_plugins as Update OS runs it, with the tool and session helpers faked."""

    @classmethod
    def setUpClass(cls):
        text = (ROOT / "src/shared/bin/smplos-os-update").read_text()
        match = re.search(r"^sync_plugins\(\) \{\n.*?^\}\n", text, re.S | re.M)
        assert match, "sync_plugins is not defined in smplos-os-update"
        cls.function = match.group(0)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.sources = self.repo / "src/compositors/hyprland/plugins"
        self.tool = self.repo / "src/shared/bin/smplos-plugins"
        self.tool.parent.mkdir(parents=True)
        self.tool.write_text('echo "tool $*"\n[[ -z "${FAIL_TOOL:-}" ]]\n')
        self.sources.mkdir(parents=True)
        self.bin = self.root / "bin"
        self.bare = self.root / "bare"
        for directory in (self.bin, self.bare):
            directory.mkdir()
            (directory / "bash").symlink_to(shutil.which("bash"))
        (self.bin / "hyprctl").write_text("#!/bin/sh\nexit 0\n")
        (self.bin / "hyprctl").chmod(0o755)

    def run_sync(self, session=False, quiet=0, hyprctl=True, **env):
        script = f"""
set -euo pipefail
QUIET={quiet}
SMPLOS_REPO={self.repo}
header() {{ [[ $QUIET -eq 0 ]] && echo "$*" || true; }}
ok()     {{ [[ $QUIET -eq 0 ]] && echo "ok: $*" || true; }}
warn()   {{ echo "warn: $*" >&2; }}
smplos_have_hyprland() {{ {'true' if session else 'false'}; }}
smplos_run_as_user() {{ echo "as-user $*"; "$@"; }}
{self.function}
sync_plugins
echo "returned $?"
"""
        path = str(self.bin if hyprctl else self.bare)
        return subprocess.run([shutil.which("bash"), "-c", script], capture_output=True,
                              text=True, timeout=10, env={"PATH": path, **env})

    def test_builds_for_the_installed_hyprland_and_reloads_the_running_one(self):
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"tool sync --src {self.sources} --reload", result.stdout)
        self.assertNotIn("as-user", result.stdout)
        self.assertIn("Compositor plugins are current", result.stdout)

    def test_reaches_the_desktop_session_from_a_bare_tty(self):
        result = self.run_sync(session=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"as-user bash {self.tool} sync --src {self.sources} --reload", result.stdout)

    def test_a_failed_build_warns_and_never_fails_the_update(self):
        result = self.run_sync(FAIL_TOOL="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("returned 0", result.stdout)
        self.assertIn("could not be built", result.stderr)
        self.assertNotIn("Compositor plugins are current", result.stdout)

    def test_quiet_update_hides_the_tool_output(self):
        result = self.run_sync(quiet=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "returned 0")

    def test_nothing_happens_without_plugin_sources_or_hyprland(self):
        shutil.rmtree(self.sources)
        result = self.run_sync()
        self.assertEqual(result.stdout.strip(), "returned 0")
        self.sources.mkdir()
        result = self.run_sync(hyprctl=False)
        self.assertEqual(result.stdout.strip(), "returned 0")


class IntegrationWiringTests(unittest.TestCase):
    """The plugin has to ship in the ISO, the installer, Update OS and every session."""

    def read(self, path):
        return (ROOT / path).read_text()

    def body(self, text, name):
        match = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}\n", text, re.S | re.M)
        self.assertIsNotNone(match, f"{name} is not defined")
        return match.group(1)

    def calls(self, text, function):
        return [line.strip() for line in self.body(text, function).splitlines()]

    def test_every_session_loads_the_plugin_and_not_the_old_overlay(self):
        for name in ("autostart.lua", "autostart.conf"):
            text = self.read(f"src/compositors/hyprland/hypr/{name}")
            self.assertIn("smplos-plugins load", text, name)
            self.assertNotIn("hud-frame", text, name)

    def test_iso_build_compiles_the_plugin_between_the_apps_and_boot_setup(self):
        main = self.calls(self.read("src/builder/build.sh"), "main")
        order = [main.index(step) for step in
                 ("install_prebuilt_apps", "build_hyprland_plugins", "setup_boot")]
        self.assertEqual(order, sorted(order))

    def test_iso_build_installs_into_the_live_image_and_only_warns_on_failure(self):
        body = self.body(self.read("src/builder/build.sh"), "build_hyprland_plugins")
        self.assertIn("usr/local/lib/smplos/plugins", body)
        self.assertIn("shared/bin/smplos-plugins", body)
        self.assertRegex(body, r"sync --src")
        self.assertIn("log_warn", body)
        self.assertNotRegex(body, r"\bdie\b|\bexit 1\b")

    def test_installer_copies_the_live_plugins_to_the_target_system(self):
        text = self.read("src/shared/installer/automated_script.sh")
        self.assertIn("/usr/local/lib/smplos/plugins", text)
        self.assertIn("/mnt/usr/local/lib/smplos/plugins", text)

    def test_update_os_builds_plugins_right_after_the_hyprland_configs(self):
        text = self.read("src/shared/bin/smplos-os-update")
        main = text.split("# ── Main ", 1)[1]
        self.assertLess(main.index("sync_hypr_configs"), main.index("sync_plugins"))
        self.assertNotIn("intentionally NOT installed", text)
        post_deploy = self.body(text, "post_deploy")
        self.assertIn('"$plugins_tool" load', post_deploy)

    def test_dev_workflows_build_and_reload_the_plugins(self):
        local = self.read("release/dev-local.sh")
        defaults = re.search(r"components=\((bin [^)]*)\)", local)
        self.assertIsNotNone(defaults, "dev-local.sh has no default component list")
        self.assertIn("plugins", defaults.group(1).split())
        self.assertIn('"$SHARE/plugins"', self.read("release/dev-push.sh"))
        apply = self.read("release/dev-apply.sh")
        self.assertIn('smplos-plugins" sync --src "$SHARE/plugins"', apply)
        self.assertIn("smplos-plugins $plugin_action", apply)

    def plugin_dirs(self):
        return sorted(path.parent for path in (ROOT / "src/compositors/hyprland/plugins").glob("*/Makefile"))

    def test_every_shipped_plugin_has_the_names_the_tool_relies_on(self):
        directories = self.plugin_dirs()
        self.assertLessEqual({"smpl-hud", "smpl-scroll"}, {directory.name for directory in directories})
        for directory in directories:
            name = directory.name
            self.assertRegex(name, r"^[A-Za-z0-9_-]+$")
            self.assertRegex((directory / "Makefile").read_text(),
                             rf"(?m)^PLUGIN\s*:=\s*\$\(BUILD\)/{re.escape(name)}\.so$")
            self.assertIn(f'return {{"{name}",', (directory / "main.cpp").read_text(), name)
            self.assertTrue((directory / "README.md").is_file(), name)

    def test_ci_unit_tests_every_plugin_that_has_tests(self):
        workflow = self.read(".github/workflows/themes.yml")
        for directory in self.plugin_dirs():
            if (directory / "tests").is_dir():
                self.assertIn(f"make -C src/compositors/hyprland/plugins/{directory.name} test", workflow, directory.name)

    def test_old_overlay_is_gone(self):
        self.assertFalse((ROOT / "src/shared/bin/hud-frame").exists())
        self.assertFalse((ROOT / "tests/test_hud_frame.py").exists())
        for path in ("src/compositors/hyprland/hypr/windows.lua",
                     "src/compositors/hyprland/hypr/windows.conf",
                     "src/compositors/hyprland/packages.txt",
                     "src/shared/bin/theme-set"):
            self.assertNotIn("hud-frame", self.read(path), path)


if __name__ == "__main__":
    unittest.main()
