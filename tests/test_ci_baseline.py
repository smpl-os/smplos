"""Required native CI must exercise shared approved policy, never rolling-library partial upgrades."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ci_baseline  # noqa: E402


class BaselinePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "src/shared/update-policy"
        self.directory.mkdir(parents=True)
        self.policy = ci_baseline.load_policy()
        self.series = self.policy["hyprland_version"].rsplit(".", 1)[0]
        self.write_policy()
        (self.directory / "critical-bundle.conf").write_text(f'HYPRLAND_SERIES="{self.series}"\n')

    def write_policy(self):
        (self.directory / "ci-baseline.json").write_text(json.dumps(self.policy))

    def test_committed_baseline_matches_shared_series(self):
        self.assertEqual(self.policy, ci_baseline.load_policy(self.root))

    def test_missing_policy_is_an_error(self):
        (self.directory / "ci-baseline.json").unlink()
        with self.assertRaises(FileNotFoundError):
            ci_baseline.load_policy(self.root)

    def test_invalid_or_incomplete_baselines_are_errors(self):
        original = self.policy.copy()
        for key, value in (("image", "archlinux:latest"), ("snapshot", "last"),
                           ("snapshot", "2026/02/30"), ("hyprland_version", "9.99.0-1"),
                           ("hyprland_version", f"{self.series}0.1-1"), ("image", None)):
            with self.subTest(key=key, value=value):
                self.policy = dict(original, **{key: value})
                self.write_policy()
                with self.assertRaises(ValueError):
                    ci_baseline.load_policy(self.root)
        self.policy = {"image": original["image"]}
        self.write_policy()
        with self.assertRaises(ValueError):
            ci_baseline.load_policy(self.root)

    def test_missing_changed_or_ambiguous_series_is_an_error(self):
        for text in ('# no series\n', 'HYPRLAND_SERIES="9.99"\n',
                     f'HYPRLAND_SERIES="{self.series}"\nHYPRLAND_SERIES="9.99"\n'):
            with self.subTest(text=text):
                (self.directory / "critical-bundle.conf").write_text(text)
                with self.assertRaises(ValueError):
                    ci_baseline.load_policy(self.root)

    def test_container_is_disposable_read_only_and_requires_all_tools(self):
        command = ci_baseline.container_command(self.policy, "podman", "quoted; filter")
        self.assertEqual(command[:3], ["podman", "run", "--rm"])
        self.assertIn(f"{ROOT}:/src:ro", command)
        self.assertIn("KEYBIND_CHECK_REQUIRE=lua,xkbcommon,hyprland", command)
        self.assertIn(self.policy["image"], command)
        self.assertEqual(command[-2:], [self.policy["snapshot"], "quoted; filter"])
        self.assertNotIn("--privileged", command)
        subprocess.run(["bash", "-n"], input=ci_baseline.INSTALL_AND_TEST, text=True, check=True)
        self.assertIn("-Syyuu", ci_baseline.INSTALL_AND_TEST)
        self.assertNotIn("mirrorlist", ci_baseline.INSTALL_AND_TEST)

    def test_container_or_archive_failure_is_not_converted_to_success(self):
        with mock.patch.object(sys, "argv", ["ci_baseline.py"]), \
                mock.patch.object(ci_baseline.subprocess, "run",
                                  side_effect=subprocess.CalledProcessError(1, ["docker"])) as run, \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ci_baseline.main(), 1)
            self.assertTrue(run.call_args.kwargs["check"])


class InstalledBaselineTests(unittest.TestCase):
    def setUp(self):
        self.policy = ci_baseline.load_policy()
        self.version = self.policy["hyprland_version"]
        self.upstream = self.version.rsplit("-", 1)[0]

    def verify(self, installed=None, available=None, executable=None):
        if installed is None:
            installed = f"hyprland {self.version}\nlua 5.5.1-1\n"
        if available is None:
            available = f"extra hyprland {self.version} [installed]\nextra lua 5.5.1-1 [installed]\n"
        if executable is None:
            executable = f"Hyprland {self.upstream} built from branch v{self.upstream}\n"
        with mock.patch.object(ci_baseline, "output", side_effect=[installed, available, executable]), \
                contextlib.redirect_stdout(io.StringIO()):
            ci_baseline.verify_installed(self.policy)

    def test_coherent_exact_baseline_passes(self):
        self.verify()

    def test_newest_library_beside_old_hyprland_fails(self):
        with self.assertRaisesRegex(ValueError, "lua: installed"):
            self.verify(installed=f"hyprland {self.version}\nlua 6.0.0-1\n")

    def test_package_outside_snapshot_fails(self):
        with self.assertRaisesRegex(ValueError, "snapshot MISSING"):
            self.verify(installed=f"hyprland {self.version}\nforeign 1.0-1\n")

    def test_wrong_exact_hyprland_fails_even_if_repositories_agree(self):
        wrong = f"{self.upstream}-999"
        with self.assertRaisesRegex(ValueError, "Expected hyprland"):
            self.verify(installed=f"hyprland {wrong}\n", available=f"extra hyprland {wrong}\n")

    def test_missing_hyprland_fails(self):
        with self.assertRaisesRegex(ValueError, "installed MISSING"):
            self.verify(installed="")

    def test_wrong_executable_fails(self):
        for version in ("9.99.0", f"{self.upstream}.1"):
            with self.subTest(version=version), \
                    self.assertRaisesRegex(ValueError, "executable does not match"):
                self.verify(executable=f"Hyprland {version}\n")

    def test_missing_shared_library_or_failed_query_is_an_error(self):
        with mock.patch.object(ci_baseline, "output",
                               side_effect=subprocess.CalledProcessError(127, ["Hyprland"])):
            with self.assertRaises(subprocess.CalledProcessError):
                ci_baseline.verify_installed(self.policy)


class ReleaseGateTests(unittest.TestCase):
    def test_required_native_job_uses_policy_after_checkout(self):
        workflow = (ROOT / ".github/workflows/keybindings.yml").read_text()
        native = workflow.split("\n  native:\n", 1)[1]
        self.assertLess(native.index("actions/checkout@"), native.index("tools/ci_baseline.py"))
        self.assertNotIn("archlinux:latest", native)
        self.assertNotIn("continue-on-error", native)
        self.assertIn("test_ci_baseline test_keybindings", workflow)
        release = (ROOT / ".github/workflows/auto-release.yml").read_text()
        self.assertIn("needs: keybindings", release)
        self.assertNotIn("keybindings-forward", release)

    def test_forward_check_remains_separate_and_non_blocking(self):
        workflow = (ROOT / ".github/workflows/keybindings-forward.yml").read_text()
        self.assertIn("container: archlinux:latest", workflow)
        self.assertIn("continue-on-error: true", workflow)
        self.assertIn("test_keybindings -v", workflow)
        self.assertNotIn("workflow_call:", workflow)
