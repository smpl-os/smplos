"""The package and repository run the same synthetic notification bridge tests."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

path = Path(__file__).resolve().parents[1] / "src/shared/pkgbuilds/dunst-smplos/test_activation.py"
spec = importlib.util.spec_from_file_location("dunst_activation_tests", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
HelperTests = module.HelperTests
PrivateBusTests = module.PrivateBusTests
LuaTests = module.LuaTests
NativeTests = module.NativeTests


class DeliveryTests(unittest.TestCase):
    def test_offline_recipe_and_no_install_restart_hook(self):
        shared = path.parents[2]
        self.assertIn("dunst-smplos", (shared / "packages-aur.txt").read_text())
        self.assertNotRegex((shared / "packages.txt").read_text(), r"(?m)^\s*dunst\s*$")
        self.assertIn("dunst-smplos", (shared / "update-policy/os-suite-packages.txt").read_text())
        recipe = (path.parent / "PKGBUILD").read_text()
        self.assertNotIn("'SKIP'", recipe)
        self.assertNotRegex(recipe, r"(?m)^\s*install=")
        self.assertIn("SMPLOS_DUNST_SOURCE=", recipe)

    def test_actual_migration_only_installs_or_reports_retryable_failure(self):
        repo = path.parents[4]
        script = repo / "migrations/20261028-080000-signal-notification-workspace.sh"
        text = script.read_text()
        self.assertNotRegex(text, r"\b(kill|pkill|killall|dunstctl|hyprctl|systemctl|pkexec|sudo)\b")
        for installed, fail, expected in (("", "0", 0), ("1.13.2-1", "0", 0), ("", "1", 1)):
            with self.subTest(installed=installed, fail=fail), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                lib = root / "src/shared/lib/smplos-pkgbuild.sh"
                lib.parent.mkdir(parents=True)
                lib.write_text(
                    'smplos_pkgbuild_version() { printf "1.13.2-1\\n"; }\n'
                    'smplos_pkg_version() { printf "%s\\n" "$CURRENT_VERSION"; }\n'
                    'smplos_pkgbuild_install() {\n'
                    '  [[ "$TEST_FAIL" == 0 ]] || return 1\n'
                    '  CURRENT_VERSION=1.13.2-1\n'
                    '}\n')
                result = subprocess.run(
                    ["/bin/bash", str(script)], text=True, capture_output=True, timeout=5,
                    env={"PATH": temp, "SMPLOS_REPO": temp,
                         "CURRENT_VERSION": installed, "TEST_FAIL": fail})
                self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
                if expected:
                    self.assertIn("retry Update OS", result.stdout)
                else:
                    self.assertRegex(result.stdout, "NOT activated|no daemon restart")
