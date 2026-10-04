"""smplos-update: one-transaction system upgrades and the Hyprland series rule."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "src/shared/update-policy"
UPDATER = (ROOT / "src/shared/bin/smplos-update").read_text()


def function(name):
    body = UPDATER.split(f"{name}() {{", 1)[1].split("\n}\n", 1)[0]
    return f"{name}() {{" + body + "\n}\n"


def bundle():
    script = f'source {shlex.quote(str(POLICY / "critical-bundle.conf"))}; ' \
             'printf "%s\\n" "$BUNDLE_ID" "$HYPRLAND_SERIES" "$PACKAGES" "$PACKAGES_IF_INSTALLED"'
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout
    bundle_id, series, packages, optional = out.splitlines()
    return bundle_id, series, packages.split(), optional.split()


class PolicyTests(unittest.TestCase):
    def test_only_the_compositor_and_portal_can_be_held(self):
        lines = (POLICY / "critical-packages.txt").read_text().splitlines()
        held = [l.strip() for l in lines if l.strip() and not l.lstrip().startswith("#")]
        self.assertEqual(held, ["hyprland", "xdg-desktop-portal-hyprland"])

    def test_series_and_bundle(self):
        _, series, packages, optional = bundle()
        self.assertRegex(series, r"^\d+\.\d+$")
        # The stack moves with the system upgrade, never through the bundle.
        self.assertFalse({"hyprland", "xdg-desktop-portal-hyprland"} & set(packages + optional))
        # The NVIDIA driver must never be forced onto other GPUs.
        self.assertFalse([p for p in packages if "nvidia" in p])
        self.assertIn("nvidia-open-dkms", optional)


# Fake pacman: AVAILABLE is the repo hyprland version, INSTALLED_AFTER the
# hyprland version once -Su ran, SY_FAIL / SU_FAIL make those steps fail and
# QQ_<pkg> is what `pacman -Qq <pkg>` prints (a provider's name, for example).
PACMAN = textwrap.dedent("""\
    #!/bin/bash
    echo "$*" >> "$CALLS"
    state="$(dirname "$CALLS")/upgraded"
    case "$1" in
      -Sy) [[ "${SY_FAIL:-0}" == 1 ]] && exit 1; exit 0 ;;
      -Su) [[ "${SU_FAIL:-0}" == 1 ]] && exit 1; touch "$state"; exit 0 ;;
      -Si) [[ -n "${AVAILABLE:-}" ]] || exit 1
           # pacman translates labels unless the C locale is forced.
           if [[ "${LC_ALL:-}" == C ]]; then echo "Version         : $AVAILABLE"
           else echo "Versión         : $AVAILABLE"; fi ;;
      -Qq) var="QQ_${2//-/_}"; [[ -n "${!var:-}" ]] || exit 1; echo "${!var}" ;;
      -Q)  if [[ -f "$state" ]]; then echo "hyprland ${INSTALLED_AFTER:-0.56.0-2}"
           else echo "hyprland 0.56.0-2"; fi ;;
      -S)  exit 0 ;;
    esac
    """)


class SystemUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        self.calls = root / "calls"
        (bin_dir / "pacman").write_text(PACMAN)
        (bin_dir / "sudo").write_text('#!/bin/bash\nexec "$@"\n')
        for tool in ("pacman", "sudo"):
            (bin_dir / tool).chmod(0o755)
        self.state = root / "state"
        self.home = root / "home"
        self.env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", CALLS=str(self.calls),
                        HOME=str(self.home), LANG="es_ES.UTF-8", LC_ALL="")

    def run_updater_step(self, body, conf_extra="", **env):
        conf = Path(self.temp.name) / "critical-bundle.conf"
        conf.write_text('BUNDLE_ID="test-1"\nHYPRLAND_SERIES="0.56"\n'
                        'PACKAGES="linux-lts kernel-modules-hook"\n'
                        'PACKAGES_IF_INSTALLED="nvidia-open-dkms nvidia-utils"\n' + conf_extra)
        script = "\n".join([
            "UPDATE_MODE=full", "NETWORK_OK=1", "UPDATE_FAILED=0", "SYSTEM_UPGRADED=0",
            f"STATE_DIR={shlex.quote(str(self.state))}",
            'APPLIED_BUNDLE_FILE="$STATE_DIR/critical-bundle-applied"',
            'BUNDLE_SNAPSHOT_FILE="$STATE_DIR/critical-bundle-versions"',
            f"CRITICAL_BUNDLE_FILE={shlex.quote(str(conf))}",
            f"CRITICAL_LIST_FILE={shlex.quote(str(POLICY / 'critical-packages.txt'))}",
            "DEFAULT_CRITICAL_PACKAGES=(hyprland)", "APPS_EXTRA_IGNORE=(pacman libalpm)",
            'REBOOT_MARKER="$HOME/.local/state/smplos/reboot-pending"',
            *(function(name) for name in ("csv_join", "load_critical_packages", "refresh_bundle_snapshot",
                                          "stack_versions", "mark_reboot_pending", "system_upgrade",
                                          "critical_bundle_prompt_and_apply")),
            "load_critical_packages", body,
            'echo "RESULT failed=$UPDATE_FAILED upgraded=$SYSTEM_UPGRADED series=$HYPRLAND_SERIES"',
        ])
        result = subprocess.run(["bash", "-c", script], env=dict(self.env, **env),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text().splitlines() if self.calls.exists() else []
        return result.stdout, [c for c in calls if not c.startswith(("-Q", "-Si"))]

    def test_validated_series_upgrades_everything_in_one_transaction(self):
        out, calls = self.run_updater_step("system_upgrade", AVAILABLE="0.56.2-4", INSTALLED_AFTER="0.56.2-4")
        self.assertEqual(calls, ["-Sy --noconfirm", "-Su --noconfirm"])
        self.assertIn("RESULT failed=0 upgraded=1 series=0.56", out)
        marker = self.home / ".local/state/smplos/reboot-pending"
        self.assertTrue(marker.exists(), "a new compositor needs a new session")
        # The reminder reads exactly this marker.
        notifier = (ROOT / "src/shared/bin/smplos-reboot-notify").read_text()
        self.assertIn('MARKER="$HOME/.local/state/smplos/reboot-pending"', notifier)

    def test_unvalidated_series_is_held(self):
        out, calls = self.run_updater_step("system_upgrade", AVAILABLE="0.57.0-1")
        self.assertEqual(calls, ["-Sy --noconfirm", "-Su --noconfirm --ignore hyprland,xdg-desktop-portal-hyprland"])
        self.assertIn("Holding Hyprland 0.57.0-1", out)
        self.assertIn("RESULT failed=0 upgraded=1", out)
        self.assertFalse((self.home / ".local/state/smplos/reboot-pending").exists())

    def test_an_unknown_version_is_held_like_before(self):
        out, calls = self.run_updater_step("system_upgrade", AVAILABLE="")
        self.assertEqual(calls, ["-Sy --noconfirm", "-Su --noconfirm --ignore hyprland,xdg-desktop-portal-hyprland"])
        self.assertIn("could not compare", out)

    def test_held_series_that_blocks_the_upgrade_is_reported(self):
        out, _ = self.run_updater_step("system_upgrade", AVAILABLE="0.57.0-1", SU_FAIL="1")
        self.assertIn("RESULT failed=1 upgraded=0", out)
        self.assertIn("has not", out)

    def test_failed_refresh_or_upgrade_is_reported_not_hidden(self):
        out, calls = self.run_updater_step("system_upgrade", AVAILABLE="0.56.2-4", SY_FAIL="1")
        self.assertEqual(calls, ["-Sy --noconfirm"])
        self.assertIn("RESULT failed=1 upgraded=0", out)
        out, _ = self.run_updater_step("system_upgrade", AVAILABLE="0.56.2-4", SU_FAIL="1")
        self.assertIn("RESULT failed=1 upgraded=0", out)

    def test_bundle_waits_for_a_completed_upgrade(self):
        out, calls = self.run_updater_step("critical_bundle_prompt_and_apply")
        self.assertFalse([c for c in calls if c.startswith("-S ")])
        self.assertIn("Skipped test-1", out)
        self.assertFalse((self.state / "critical-bundle-applied").exists())

    def test_bundle_refreshes_the_nvidia_driver_only_where_installed_by_name(self):
        _, calls = self.run_updater_step("system_upgrade\ncritical_bundle_prompt_and_apply",
                                         AVAILABLE="0.56.2-4", QQ_nvidia_open_dkms="nvidia-open-dkms",
                                         QQ_nvidia_utils="nvidia-580xx-utils")
        self.assertEqual(calls[-1], "-S --noconfirm --needed linux-lts kernel-modules-hook nvidia-open-dkms")
        self.assertEqual((self.state / "critical-bundle-applied").read_text().strip(), "test-1")

    def test_series_parsing_ignores_anything_but_major_minor(self):
        for line, expected in (('HYPRLAND_SERIES=0.57\n', "0.57"), ('HYPRLAND_SERIES="0.58"  # tested\n', "0.58"),
                               ('HYPRLAND_SERIES="$(id)"\n', "")):
            conf = Path(self.temp.name) / "c.conf"
            conf.write_text(line)
            script = "\n".join([f"CRITICAL_BUNDLE_FILE={shlex.quote(str(conf))}",
                                f"CRITICAL_LIST_FILE={shlex.quote(str(POLICY / 'critical-packages.txt'))}",
                                "DEFAULT_CRITICAL_PACKAGES=(hyprland)", "APPS_EXTRA_IGNORE=()",
                                function("csv_join"), function("load_critical_packages"),
                                "load_critical_packages", 'printf "%s" "$HYPRLAND_SERIES"'])
            out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout
            self.assertEqual(out, expected)

    def test_the_shipped_series_is_read_by_the_updater_itself(self):
        _, series, _, _ = bundle()
        script = "\n".join([f"CRITICAL_BUNDLE_FILE={shlex.quote(str(POLICY / 'critical-bundle.conf'))}",
                            f"CRITICAL_LIST_FILE={shlex.quote(str(POLICY / 'critical-packages.txt'))}",
                            "DEFAULT_CRITICAL_PACKAGES=(hyprland)", "APPS_EXTRA_IGNORE=()",
                            function("csv_join"), function("load_critical_packages"),
                            "load_critical_packages", 'printf "%s" "$HYPRLAND_SERIES"'])
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout
        self.assertEqual(out, series)

    def test_the_full_update_uses_the_one_transaction_step(self):
        step = UPDATER.split("# ── Step 2: Official repos", 1)[1].split("# ── Step 4", 1)[0]
        full = step.split("else\n", 1)[1]
        self.assertIn("system_upgrade", full)
        self.assertNotRegex(full, re.compile(r"pacman -Syu .*--ignore"))


if __name__ == "__main__":
    unittest.main()
