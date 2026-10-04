"""Package cleanup migrations: remove only what Arch dropped and nothing needs."""

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
LIB32 = MIGRATIONS / "20260805-100060-remove-dropped-lib32-gstreamer.sh"
WEBKIT = MIGRATIONS / "20260805-100070-remove-orphaned-webkit2gtk.sh"
CATCHUP = MIGRATIONS / "20260805-100300-force-catchup-update.sh"
CHAIN = ["lib32-gst-plugins-good", "lib32-gst-plugins-base", "lib32-gst-plugins-base-libs",
         "lib32-gstreamer", "lib32-libcap", "lib32-pam", "lib32-audit", "lib32-libnsl",
         "lib32-libtirpc"]
REQUIRED_BY = {
    "lib32-gst-plugins-base-libs": "lib32-gst-plugins-base  lib32-gst-plugins-good",
    "lib32-gstreamer": "lib32-gst-plugins-base-libs",
    "lib32-libcap": "lib32-gstreamer",
    "lib32-pam": "lib32-libcap",
    "lib32-audit": "lib32-pam",
    "lib32-libnsl": "lib32-pam",
    "lib32-libtirpc": "lib32-libnsl  lib32-pam",
}

# Fake pacman: INSTALLED / IN_REPO / ORPHANS are space-separated package lists,
# REQ_<pkg> is "Required By", DEPS_<pkg> is the repository "Depends On" and
# SYU_FAIL=1 makes `pacman -Syu` fail. Mutating calls are logged to $CALLS.
PACMAN = textwrap.dedent("""\
    #!/bin/bash
    in_list() { [[ " $1 " == *" $2 "* ]]; }
    var() { local name="$1_${2//-/_}"; printf '%s' "${!name:-}"; }
    case "$1" in
      -Q)    in_list "$INSTALLED" "$2" && echo "$2 1-1" ;;
      -Qq)   in_list "$INSTALLED" "$2" && echo "$2" ;;
      -Qdtq) in_list "$ORPHANS" "$2" && echo "$2" ;;
      -Qmq)  in_list "$INSTALLED" "$2" && ! in_list "$IN_REPO" "$2" && echo "$2" ;;
      -Qi)   echo "Name            : $2"; r=$(var REQ "$2"); echo "Required By     : ${r:-None}" ;;
      -Si)   in_list "$IN_REPO" "$2" || exit 1
             echo "Name            : $2"; d=$(var DEPS "$2"); echo "Depends On      : ${d:-None}" ;;
      *)     echo "$*" >> "$CALLS"
             [[ "$1" == -Syu && "${SYU_FAIL:-0}" == 1 ]] && exit 1
             exit 0 ;;
    esac
    """)


class MigrationHarness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        self.calls = self.root / "calls"
        for name, body in (("pacman", PACMAN), ("sudo", '#!/bin/bash\nexec "$@"\n'),
                           ("curl", '#!/bin/sh\n[ "${OFFLINE:-0}" = 1 ] && exit 7\nexit 0\n'),
                           ("lspci", "#!/bin/sh\nexit 0\n")):
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        self.env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", CALLS=str(self.calls),
                        HOME=str(self.root / "home"), INSTALLED="", IN_REPO="", ORPHANS="")

    def run_migration(self, script, **env):
        self.calls.unlink(missing_ok=True)
        result = subprocess.run(["bash", str(script)], env=dict(self.env, **env),
                                capture_output=True, text=True, timeout=10)
        calls = self.calls.read_text().splitlines() if self.calls.exists() else []
        return result, calls


class DroppedLib32GstreamerTests(MigrationHarness):
    def setUp(self):
        super().setUp()
        self.env["INSTALLED"] = " ".join(CHAIN)
        for pkg, dependents in REQUIRED_BY.items():
            self.env["REQ_" + pkg.replace("-", "_")] = dependents

    def test_removes_the_whole_self_contained_chain(self):
        result, calls = self.run_migration(LIB32)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(calls, ["-Sy --noconfirm", "-R --noconfirm " + " ".join(CHAIN)])

    def test_nothing_installed_is_a_no_op(self):
        result, calls = self.run_migration(LIB32, INSTALLED="")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_offline_defers_without_failing_the_update(self):
        result, calls = self.run_migration(LIB32, OFFLINE="1")
        self.assertEqual(result.returncode, 75)
        self.assertEqual(calls, [])

    def test_a_package_still_needed_by_a_kept_repository_package_defers(self):
        result, calls = self.run_migration(LIB32, INSTALLED="lib32-pam lib32-audit", IN_REPO="lib32-pam",
                                           REQ_lib32_audit="lib32-pam", REQ_lib32_pam="None",
                                           DEPS_lib32_pam="lib32-audit lib32-glibc")
        self.assertEqual(result.returncode, 75, result.stdout)
        self.assertIn("keeping it", result.stdout)
        self.assertEqual(calls, ["-Sy --noconfirm"])

    def test_an_outside_dependent_that_drops_the_dependency_when_upgraded_is_allowed(self):
        # lib32-systemd <= 259 required lib32-libcap; the current version does not.
        result, calls = self.run_migration(
            LIB32, IN_REPO="lib32-systemd", DEPS_lib32_systemd="systemd-libs lib32-gcc-libs",
            REQ_lib32_libcap="lib32-gstreamer  lib32-systemd")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(calls, ["-Sy --noconfirm", "-Rdd --noconfirm " + " ".join(CHAIN)])

    def test_an_outside_dependent_that_still_requires_it_defers(self):
        for repo in ("lib32-systemd", ""):
            with self.subTest(dependent_in_repo=bool(repo)):
                result, calls = self.run_migration(
                    LIB32, IN_REPO=repo, DEPS_lib32_systemd="lib32-libcap>=2.70",
                    REQ_lib32_libcap="lib32-gstreamer  lib32-systemd")
                self.assertEqual(result.returncode, 75, result.stdout)
                self.assertIn("lib32-systemd", result.stdout)
                self.assertEqual(calls, ["-Sy --noconfirm"])


class OrphanedWebkit2gtkTests(MigrationHarness):
    def test_removes_an_orphan_no_repository_provides(self):
        result, calls = self.run_migration(WEBKIT, INSTALLED="webkit2gtk", ORPHANS="webkit2gtk")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(calls, ["-R --noconfirm webkit2gtk"])

    def test_keeps_it_when_needed_explicit_or_still_shipped(self):
        for env in ({"INSTALLED": ""},
                    {"INSTALLED": "webkit2gtk"},
                    {"INSTALLED": "webkit2gtk", "ORPHANS": "webkit2gtk", "IN_REPO": "webkit2gtk"}):
            with self.subTest(**env):
                result, calls = self.run_migration(WEBKIT, **env)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(calls, [])


class MigrationOrderTests(unittest.TestCase):
    def test_cleanups_run_before_the_catchup_upgrade_they_unblock(self):
        names = sorted(p.name for p in MIGRATIONS.glob("*.sh"))
        for cleanup in (LIB32.name, WEBKIT.name):
            self.assertLess(names.index(cleanup), names.index("20260805-100100-hyprland-0.56-pin.sh"))
            self.assertLess(names.index(cleanup), names.index(CATCHUP.name))


class CatchupMigrationTests(MigrationHarness):
    def setUp(self):
        super().setUp()
        policy = self.root / "smplos/repo/src/shared/update-policy"
        policy.mkdir(parents=True)
        (policy / "critical-packages.txt").write_text("hyprland\nxdg-desktop-portal-hyprland\n")
        (policy / "critical-bundle.conf").write_text('BUNDLE_ID="test-1"\nPACKAGES="linux-lts hyprland"\n')
        self.env["SMPLOS_PATH"] = str(self.root / "smplos")
        self.applied = self.root / "home/.local/state/smplos/update/critical-bundle-applied"

    def test_bundle_is_not_installed_after_a_failed_system_upgrade(self):
        result, calls = self.run_migration(CATCHUP, SYU_FAIL="1")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertFalse([c for c in calls if c.startswith("-S --noconfirm --needed")])
        self.assertFalse(self.applied.exists())

    def test_bundle_is_installed_after_a_successful_system_upgrade(self):
        result, calls = self.run_migration(CATCHUP)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("-S --noconfirm --needed linux-lts hyprland", calls)
        self.assertEqual(self.applied.read_text().strip(), "test-1")


if __name__ == "__main__":
    unittest.main()
