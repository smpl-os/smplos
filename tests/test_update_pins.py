"""Protected-stack planning and auditing, without modifying host packages."""

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

import test_update_safety as safety

CHECK = safety.CHECK


class PinPlanTests(unittest.TestCase):
    def setUp(self):
        self.fixture = safety.InstalledStateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.repo = self.fixture.repo
        self.policy = self.repo / "src/shared/update-policy"
        self.policy.mkdir(parents=True)
        self.patterns = "hypr*\naquamarine\nlinux-lts\n*nvidia*\n*mesa*\npipewire*\nobs-studio\n"
        (self.policy / "critical-packages.txt").write_text(self.patterns)
        (self.policy / "critical-bundle.conf").write_text('HYPRLAND_SERIES="0.56"\n')
        self.available = "0.57.0-1"
        self.responses = [(0, "tailscale 2-1\n", "")]
        self.previews = []

    def runner(self, *args):
        if args == ("pacman", "-Si", "hyprland"):
            return subprocess.CompletedProcess(args, 0, f"Version : {self.available}\n", "")
        if args[:2] == ("pacman", "-Su"):
            self.previews.append(args)
            status, out, err = self.responses.pop(0)
            return subprocess.CompletedProcess(args, status, out, err)
        return self.fixture.runner(*args)

    def plan(self):
        audit = CHECK.Audit(self.fixture.home, self.repo, self.fixture.root, self.runner)
        audit.snapshot()
        audit.plan_pins()
        return audit

    def test_new_compositor_keeps_stack_and_allows_unrelated_update(self):
        for name in ("aquamarine", "nvidia-open-dkms", "nvidia-utils", "lib32-nvidia-utils",
                     "mesa", "lib32-mesa", "pipewire", "obs-studio"):
            self.fixture.packages[name] = "1-1"
        audit = self.plan()
        self.assertEqual(audit.report["errors"], [])
        pins = audit.report["pin_plan"]["pins"]
        self.assertEqual(set(pins), self.fixture.packages.keys() - {"glibc"})
        self.assertEqual(audit.report["pin_plan"]["targets"], {"tailscale": "2-1"})
        self.assertEqual(self.previews[0][-2:], ("--ignore", ",".join(sorted(pins))))
        self.assertNotIn("--nodeps", self.previews[0])

    def test_approved_series_and_non_hyprland_hosts_do_not_acquire_transition_pins(self):
        for installed in (True, False):
            with self.subTest(installed=installed):
                self.available = "0.56.3-1"
                if not installed:
                    del self.fixture.packages["hyprland"]
                self.responses = [(0, "tailscale 2-1\n", "")]
                self.assertEqual(self.plan().report["pin_plan"]["pins"], {})
                self.assertNotIn("--ignore", self.previews[-1])

    def test_epoch_version_is_supported_but_unknown_policy_or_wrong_installed_series_is_not(self):
        self.available = "1:0.56.4-1"
        self.fixture.packages["hyprland"] = "1:0.56.2-1"
        self.assertEqual(self.plan().report["errors"], [])
        for installed, available, policy in (
            ("0.56.2-1", "", 'HYPRLAND_SERIES="0.56"\n'),
            ("0.56.2-1", "0.57.0-1", 'HYPRLAND_SERIES="$(id)"\n'),
            ("0.57.0-1", "0.57.1-1", 'HYPRLAND_SERIES="0.56"\n'),
        ):
            with self.subTest(installed=installed, available=available):
                self.fixture.packages["hyprland"] = installed
                self.available = available
                (self.policy / "critical-bundle.conf").write_text(policy)
                self.assertTrue(self.plan().report["errors"])

    def test_advancing_the_approved_series_releases_pins_and_allows_the_validated_upgrade(self):
        (self.policy / "critical-bundle.conf").write_text('HYPRLAND_SERIES="0.57"\n')
        self.responses = [(0, "hyprland 0.57.0-1\ntailscale 2-1\n", "")]
        audit = self.plan()
        self.assertEqual(audit.report["errors"], [])
        self.assertEqual(audit.report["pin_plan"]["pins"], {})
        self.fixture.packages["hyprland"] = "0.58.0-1"
        self.assertTrue(self.plan().report["errors"])

    def test_abi_dependencies_expand_transitively_and_reverse_dependents_are_deferred(self):
        self.fixture.packages.update({"library": "1-1", "backing-library": "1-1", "editor": "1-1"})
        self.fixture.provides["library"] = ["libtest.so=1-64"]
        self.responses = [
            (1, ":: installing library (2-1) breaks dependency 'libtest.so=1-64' required by hyprland\n", ""),
            (1, ":: installing backing-library (2-1) breaks dependency 'backing-library=1' required by library\n", ""),
            (1, ":: unable to satisfy dependency 'libtest.so=2-64' required by editor\n", ""),
            (0, "tailscale 2-1\n", ""),
        ]
        audit = self.plan()
        self.assertEqual(audit.report["errors"], [])
        pins = audit.report["pin_plan"]["pins"]
        self.assertTrue({"hyprland", "linux-lts", "library", "backing-library", "editor"} <= pins.keys())
        self.assertIn("hyprland", pins["library"]["reason"])
        self.assertIn("unavailable with the approved stack", pins["editor"]["reason"])
        self.assertEqual(len(self.previews), 4)

    def test_unknown_or_unrelated_solver_errors_are_not_hidden_by_freezing_more_packages(self):
        for output in (
            "error: corrupted database\n",
            ":: installing glibc (3-1) breaks dependency 'glibc=2' required by unrelated-aur\n",
            ":: unable to satisfy dependency 'missing-library' required by new-package\n",
        ):
            with self.subTest(output=output):
                self.responses = [(1, "", output)]
                audit = self.plan()
                self.assertIn(output.strip(), "\n".join(audit.report["errors"]))
                self.assertNotIn("glibc", audit.report["pin_plan"]["pins"])

    def test_no_progress_or_invalid_preview_is_not_accepted(self):
        for output in (
            ":: installing hyprland (0.57-1) breaks dependency 'hyprland=0.56' required by hyprland\n",
            "hyprland 0.57-1\n",
            "unexpected transaction message\n",
        ):
            with self.subTest(output=output):
                self.responses = [(int(output.startswith("::")), output, "")]
                self.assertTrue(self.plan().report["errors"])

    def load(self, original, report=None, previous=None):
        path = self.fixture.base / "pins.json"
        path.write_text(json.dumps(report or original.report))
        audit = CHECK.Audit(self.fixture.home, self.repo, self.fixture.root, self.runner)
        audit.snapshot()
        audit.load_pins(path, previous or original.report)
        return audit

    def test_audit_exempts_only_this_runs_unchanged_pins_and_checks_every_other_package(self):
        original = self.plan()
        self.fixture.available["hyprland"] = "0.57.0-1"
        self.fixture.pending = "hyprland 0.56.0-2 -> 0.57.0-1\n"
        audit = self.load(original)
        audit.system()
        self.assertEqual(audit.report["errors"], [])
        self.assertEqual(audit.report["package_status"]["hyprland"]["status"], "pinned")
        self.fixture.available["glibc"] = "3-1"
        self.fixture.pending += "glibc 2.42-1 -> 3-1\n"
        audit = self.load(original)
        audit.system()
        self.assertIn("Package was not updated: glibc", "\n".join(audit.report["errors"]))
        self.assertIn("Repository updates remain", "\n".join(audit.report["errors"]))

    def test_changed_or_removed_pins_and_stale_or_failed_plans_are_errors(self):
        original = self.plan()
        self.fixture.packages["hyprland"] = "0.57.0-1"
        self.assertIn("Protected package changed", "\n".join(self.load(original).report["errors"]))
        del self.fixture.packages["hyprland"]
        self.assertIn("Protected package changed", "\n".join(self.load(original).report["errors"]))
        self.fixture.packages["hyprland"] = "0.56.0-2"
        for key in ("baseline", "errors", "source", "solver", "policy", "pins", "pin-value"):
            with self.subTest(key=key):
                report = json.loads(json.dumps(original.report))
                if key == "baseline":
                    report["packages"]["glibc"] = "other"
                elif key == "errors":
                    report["errors"] = ["failed"]
                elif key == "source":
                    report["source_commit"] = "other"
                elif key == "solver":
                    report["pin_plan"]["attempts"][-1]["returncode"] = 1
                elif key == "policy":
                    report["pin_plan"]["policy"]["critical-packages.txt"] = "other"
                elif key == "pins":
                    report["pin_plan"]["pins"] = []
                else:
                    report["pin_plan"]["pins"]["hyprland"] = None
                with self.assertRaises(ValueError):
                    self.load(original, report)


class PacmanGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.calls = self.base / "calls"
        mock_pacman = self.base / "pacman"
        mock_pacman.write_text("""#!/usr/bin/env python3
import json, os, sys
with open(os.environ["CALLS"], "a") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
if "--hookdir" in sys.argv:
    from pathlib import Path
    hook_dir = Path(sys.argv[sys.argv.index("--hookdir") + 1])
    Path(os.environ["HOOK_CAPTURE"]).write_text((hook_dir / "00-smplos-protected-stack.hook").read_text())
if "--print" in sys.argv:
    print(os.environ.get("TARGETS", "editor"))
    sys.exit(int(os.environ.get("PREVIEW_FAIL", "0")))
""")
        mock_pacman.chmod(0o755)
        self.guard = self.base / "guard"
        source = (safety.BIN / "smplos-pacman").read_text()
        self.guard.write_text(source.replace("/usr/bin/pacman", str(mock_pacman)))

    def run_guard(self, *args, **env):
        self.calls.write_text("")
        result = subprocess.run(
            ["bash", str(self.guard), *args], text=True, capture_output=True, timeout=5,
            env={**os.environ, "SMPLOS_UPDATE_PIN_IGNORE": "hyprland,display-lib",
                 "CALLS": str(self.calls), "HOOK_CAPTURE": str(self.base / "hook"), **env},
        )
        return result, [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_dependency_install_is_previewed_and_committed_with_the_same_pins(self):
        result, calls = self.run_guard("-S", "--noconfirm", "editor")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1] + ["--print", "--print-format", "%n"])
        self.assertEqual(calls[1][-4:-2], ["--ignore", "hyprland,display-lib"])
        hook = (self.base / "hook").read_text()
        for expected in ("Operation = Remove", "Target = hyprland", "Target = display-lib", "AbortOnFail"):
            self.assertIn(expected, hook)
        self.assertFalse(Path(calls[1][-1]).exists())

    def test_queries_and_an_existing_ignore_option_are_handled_without_false_pin_matches(self):
        for args in (("-Q", "hyprland"), ("-Si", "hyprland")):
            result, calls = self.run_guard(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls, [list(args)])
        result, calls = self.run_guard("-S", "--ignore", "hyprland", "editor")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)

    def test_explicit_and_implicit_protected_changes_and_removals_are_refused(self):
        for args, targets in (
            (("-S", "hyprland"), ""),
            (("-S", "editor"), "display-lib"),
            (("-U", "/tmp/package.pkg.tar.zst"), "hyprland"),
            (("-Rns", "unused-app"), "unused-app\nhyprland"),
        ):
            with self.subTest(args=args):
                result, calls = self.run_guard(*args, TARGETS=targets)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("refused", result.stderr)
                self.assertLessEqual(len(calls), 1)

    def test_solver_errors_malformed_results_and_dependency_bypasses_cannot_install(self):
        for env in ({"PREVIEW_FAIL": "1"}, {"TARGETS": "unexpected preview output"}):
            result, calls = self.run_guard("-S", "editor", **env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(calls), 1)
        for args in (("-Sdd", "editor"), ("-Rdd", "editor"), ("-S", "--nodeps", "editor"),
                     ("-S", "--assume-installed=display-lib=2", "editor")):
            result, calls = self.run_guard(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])


@unittest.skipUnless(shutil.which("pacman"), "requires Arch's real dependency solver")
class PacmanPinIntegrationTests(unittest.TestCase):
    """Synthetic package databases exercise libalpm, not localized error mocks."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "root"
        self.root.mkdir()
        self.db = self.base / "db"
        (self.db / "local").mkdir(parents=True)
        (self.db / "local/ALPM_DB_VERSION").write_text("9\n")
        (self.db / "sync").mkdir()
        self.repo = self.base / "repo"
        policy = self.repo / "src/shared/update-policy"
        policy.mkdir(parents=True)
        (policy / "critical-bundle.conf").write_text('HYPRLAND_SERIES="0.56"\n')
        (policy / "critical-packages.txt").write_text("hyprland\n")
        self.config = self.base / "pacman.conf"
        self.config.write_text("[options]\nArchitecture = x86_64\nSigLevel = Never\n"
                               "[test]\nServer = file:///not-used\n")

    def desc(self, name, version, depends=(), provides=(), replaces=()):
        fields = {"NAME": [name], "VERSION": [version], "ARCH": ["x86_64"],
                  "DESC": ["synthetic fixture"], "FILENAME": [f"{name}-{version}-x86_64.pkg.tar.zst"],
                  "CSIZE": ["1"], "ISIZE": ["1"], "DEPENDS": depends, "PROVIDES": provides,
                  "REPLACES": replaces}
        return "".join(f"%{key}%\n" + "\n".join(value) + "\n\n"
                       for key, value in fields.items() if value)

    def inventory(self, installed, available):
        for name, (version, dependencies, provides) in installed.items():
            path = self.db / "local" / f"{name}-{version}"
            path.mkdir()
            (path / "desc").write_text(self.desc(name, version, dependencies, provides))
            (path / "files").write_text("%FILES%\n\n")
        with tarfile.open(self.db / "sync/test.db", "w:gz") as archive:
            for name, values in available.items():
                data = self.desc(name, *values).encode()
                entry = tarfile.TarInfo(f"{name}-{values[0]}/desc")
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))

    def runner(self, *args):
        if args[0] == "pacman":
            args = (args[0], "--config", str(self.config), "--root", str(self.root),
                    "--dbpath", str(self.db), *args[1:])
        if args[0] == "git":
            return subprocess.CompletedProcess(args, 0, "f" * 40, "")
        return subprocess.run(args, text=True, capture_output=True, timeout=10,
                              env={**os.environ, "LC_ALL": "C"})

    def plan(self):
        audit = CHECK.Audit(self.base, self.repo, self.root, self.runner)
        audit.snapshot()
        audit.plan_pins()
        self.assertEqual(audit.report["errors"], [])
        self.assertFalse((self.db / "db.lck").exists())
        self.assertFalse((self.root / "usr").exists(), "Preview must not install any files")
        return audit.report["pin_plan"]

    @unittest.skipUnless(os.geteuid() == 0, "real fixture transaction requires root; covered in Arch CI")
    def test_abort_hook_prevents_protected_removals_not_exposed_in_the_preview(self):
        self.inventory(
            {"hyprland": ("0.56.2-1", ["display-lib"], []), "display-lib": ("1-1", [], [])},
            {},
        )
        driver = self.base / "preview-omits-removals"
        driver.write_text("#!/usr/bin/env python3\nimport os, sys\n"
                          "if '--print' in sys.argv: sys.exit(0)\n"
                          f"command = {['pacman', '--config', str(self.config), '--root', str(self.root), '--dbpath', str(self.db)]!r}\n"
                          f"os.execv({shutil.which('pacman')!r}, command + sys.argv[1:])\n")
        driver.chmod(0o755)
        guard = self.base / "guard"
        guard.write_text((safety.BIN / "smplos-pacman").read_text().replace("/usr/bin/pacman", str(driver)))
        result = subprocess.run(
            ["bash", str(guard), "-Rsc", "--noconfirm", "display-lib"],
            env={**os.environ, "LC_ALL": "C", "SMPLOS_UPDATE_PIN_IGNORE": "hyprland"},
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("protected smplOS stack", result.stdout + result.stderr)
        self.assertEqual(self.runner("pacman", "-Q", "hyprland", "display-lib").returncode, 0)
        self.assertFalse((self.db / "db.lck").exists())

    def test_real_solver_preserves_abi_and_reverse_dependencies_while_updating_unrelated_packages(self):
        self.inventory(
            {"hyprland": ("0.56.2-1", ["libdisplay.so=1-64"], []),
             "display-lib": ("1-1", [], ["libdisplay.so=1-64"]),
             "editor": ("1-1", ["display-lib>=1"], []), "tailscale": ("1-1", [], [])},
            {"hyprland": ("0.57.0-1", ["libdisplay.so=2-64"], []),
             "display-lib": ("2-1", [], ["libdisplay.so=2-64"]),
             "editor": ("2-1", ["display-lib>=2"], []), "tailscale": ("2-1", [], [])},
        )
        plan = self.plan()
        self.assertEqual(set(plan["pins"]), {"hyprland", "display-lib", "editor"})
        self.assertEqual(plan["targets"], {"tailscale": "2-1"})
        self.assertGreaterEqual(len(plan["attempts"]), 3)

    def test_a_repository_replacement_must_not_remove_a_protected_package(self):
        self.inventory(
            {"hyprland": ("0.56.2-1", [], []), "tailscale": ("1-1", [], [])},
            {"hyprland": ("0.57.0-1", [], []), "new-compositor": ("1-1", [], [], ["hyprland"]),
             "tailscale": ("2-1", [], [])},
        )
        self.assertEqual(self.plan()["targets"], {"tailscale": "2-1"})

    def test_unrelated_official_replacements_remain_part_of_the_resolved_transaction(self):
        self.inventory(
            {"hyprland": ("0.56.2-1", [], []), "old-helper": ("1-1", [], []),
             "tailscale": ("1-1", [], [])},
            {"hyprland": ("0.57.0-1", [], []), "new-helper": ("2-1", [], [], ["old-helper"]),
             "tailscale": ("2-1", [], [])},
        )
        self.assertEqual(self.plan()["targets"], {"new-helper": "2-1", "tailscale": "2-1"})


if __name__ == "__main__":
    unittest.main()
