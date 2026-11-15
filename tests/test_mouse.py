"""Mouse remapping integration, using fake sysfs and tools, never live input."""

import json
from pathlib import Path
import shutil
import subprocess

from test_keypad import KeypadCase, ROOT, escape_device


MIGRATION = ROOT / "migrations/20261021-210000-razer-mouse-remapping.sh"
RULE = ROOT / "src/shared/system/udev/70-smplos-mice.rules"
UNIT = ROOT / "src/shared/configs/systemd/user/mouse-remap.service"
FEATURES = dict(apiVersion=1, vendor="1532", product="00b4", learning=True,
                identify=True, identifyWheels=True, guidedCalibration=True, guidedSetup=True,
                tiltNavigationGestures=True, kdenliveApi=True,
                passthrough=True, appProfiles="hyprland")


class MouseIntegrationTests(KeypadCase):
    def setUp(self):
        super().setUp()
        self.repo = self.root / "repo"
        for source in (MIGRATION, RULE, UNIT, ROOT / "src/shared/lib/smplos-keypad-units.sh"):
            destination = self.repo / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        (self.repo / "src/shared/lib/smplos-session-env.sh").write_text(
            'smplos_have_user_bus() { return 0; }\n'
            'smplos_run_as_user() { echo "session $*" >> "$CALLS"; }\n')
        self.rules = self.root / "rules"
        self.units = self.home / ".config/systemd/user"
        self.state = self.home / ".local/state/smplos/mouse-units"
        self.uinput = self.root / "uinput"
        self.uinput.mkdir()
        self.tool("sudo", '"$@"\n')
        self.tool("udevadm", 'echo "udevadm $*" >> "$CALLS"\n')
        self.daemon = self.tool("mouse-remapperd",
                                'echo "mouse-runtime $*" >> "$CALLS"\n'
                                '[ "$*" = "features --json" ] || exit 2\n'
                                '[ -z "$RUNTIME_FAIL" ] || exit 127\n'
                                'printf "%s\\n" "$FEATURES"\n')
        self.env.update(SMPLOS_REPO=str(self.repo), SMPLOS_MOUSE_SYSFS=str(self.sysfs),
                        SMPLOS_UDEV_RULES_DIR=str(self.rules),
                        SMPLOS_MOUSE_UINPUT_SYSFS=str(self.uinput),
                        SMPLOS_MOUSE_DAEMON=str(self.daemon), FEATURES=json.dumps(FEATURES))

    def migrate(self):
        return subprocess.run(["bash", str(MIGRATION)], env=self.env,
                              capture_output=True, text=True, timeout=20)

    def test_rules_scope_every_event_interface_to_only_the_supported_mouse(self):
        rules = [line for line in RULE.read_text().splitlines() if line.startswith("SUBSYSTEM")]
        self.assertEqual(len(rules), 2)
        for line in rules:
            self.assertIn('"1532"', line)
            self.assertIn('"00b4"', line)
            self.assertNotIn("MODE=", line)
            self.assertNotIn("GROUP=", line)
        self.assertIn('ENV{SYSTEMD_USER_WANTS}+="mouse-remap.service"', rules[0])
        self.assertIn('KERNEL=="event*"', rules[1])
        self.assertIn('TAG+="uaccess"', rules[1])
        self.assertEqual(escape_device("/smplos/mouse"), "smplos-mouse.device")
        self.assertNotIn("control-surface.service", RULE.read_text())

    def test_service_has_no_target_enablement_or_keypad_dependencies(self):
        unit = UNIT.read_text()
        self.assertIn("BindsTo=smplos-mouse.device", unit)
        self.assertIn("After=smplos-mouse.device graphical-session.target", unit)
        self.assertIn("ExecStart=/usr/bin/mouse-remapperd run", unit)
        self.assertIn("ConditionPathExists=/usr/bin/mouse-remapperd", unit)
        for forbidden in ("[Install]", "WantedBy", "eww", "smplos-keypad"):
            self.assertNotIn(forbidden, unit)

    def test_migration_is_idempotent_and_triggers_only_our_mouse_and_uinput(self):
        mouse = self.device("1-5", dict(idVendor="1532", idProduct="00b4"))
        self.device("1-6", dict(idVendor="1532", idProduct="9999"))
        self.device("1-7", dict(idVendor="1189", idProduct="8890"))
        result = self.migrate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.rules / RULE.name).read_bytes(), RULE.read_bytes())
        self.assertEqual((self.units / UNIT.name).read_bytes(), UNIT.read_bytes())
        self.assertEqual((self.state / "last-installed.service").read_bytes(), UNIT.read_bytes())
        calls = self.calls_made()
        self.assertLess(calls.index("session systemctl --user daemon-reload"),
                        calls.index("udevadm control --reload-rules"))
        self.assertEqual([call for call in calls if call.startswith("udevadm trigger")], [
            f"udevadm trigger --action=change --parent-match={mouse.resolve()}",
            f"udevadm trigger --action=change {self.uinput}"])
        self.assertFalse(any(" restart " in call or " enable " in call for call in calls))
        self.assertFalse(list(self.units.glob("*.wants/*")))
        self.calls.unlink()
        self.assertEqual(self.migrate().returncode, 0)
        self.assertEqual(self.calls_made(), ["mouse-runtime features --json"])

    def test_missing_incompatible_or_broken_daemon_defers_without_changing_system(self):
        invalid = ["{}", "not json", json.dumps(dict(FEATURES, vendor="1189")),
                   json.dumps(dict(FEATURES, apiVersion=True)),
                   json.dumps(dict(FEATURES, learning=False)),
                   json.dumps(dict(FEATURES, identify=False)),
                   json.dumps(dict(FEATURES, identifyWheels=False)),
                   json.dumps(dict(FEATURES, guidedCalibration=False)),
                   json.dumps(dict(FEATURES, guidedSetup=False)),
                   json.dumps(dict(FEATURES, tiltNavigationGestures=False)),
                   json.dumps({key: value for key, value in FEATURES.items()
                               if key != "identifyWheels"}),
                   json.dumps({key: value for key, value in FEATURES.items()
                               if key != "guidedCalibration"}),
                   json.dumps({key: value for key, value in FEATURES.items()
                               if key != "guidedSetup"}),
                   json.dumps({key: value for key, value in FEATURES.items()
                               if key != "tiltNavigationGestures"}),
                   json.dumps(dict(FEATURES, kdenliveApi=False)),
                   json.dumps(dict(FEATURES, passthrough=False))]
        for features in invalid:
            with self.subTest(features=features):
                self.env["FEATURES"] = features
                result = self.migrate()
                self.assertEqual(result.returncode, 75)
                self.assertIn("compatible mouse-remapperd release is required", result.stderr)
                self.assertFalse(self.rules.exists())
                self.assertFalse(self.units.exists())
        self.env["FEATURES"] = json.dumps(FEATURES)
        self.env["RUNTIME_FAIL"] = "1"
        self.assertEqual(self.migrate().returncode, 75)
        self.env["SMPLOS_MOUSE_DAEMON"] = str(self.bin / "missing")
        self.assertEqual(self.migrate().returncode, 75)
        self.assertFalse(any("udevadm" in call for call in self.calls_made()))

    def test_custom_unit_symlink_dropins_and_mappings_are_preserved(self):
        self.units.mkdir(parents=True)
        external = self.root / "developer-mouse.service"
        external.write_text("[Service]\nExecStart=/custom/mouse-remapperd run\n")
        (self.units / UNIT.name).symlink_to(external)
        dropin = self.units / (UNIT.name + ".d") / "custom.conf"
        dropin.parent.mkdir()
        dropin.write_text("[Service]\nEnvironment=CUSTOM=yes\n")
        mapping = self.home / ".config/smplos/mouse.json"
        mapping.parent.mkdir(parents=True)
        mapping.write_text('{"custom": "keep exactly"}\n')
        result = self.migrate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("custom unit", result.stdout)
        self.assertTrue((self.units / UNIT.name).is_symlink())
        self.assertEqual(external.read_text(), "[Service]\nExecStart=/custom/mouse-remapperd run\n")
        self.assertEqual(dropin.read_text(), "[Service]\nEnvironment=CUSTOM=yes\n")
        self.assertEqual(mapping.read_text(), '{"custom": "keep exactly"}\n')

    def test_last_installed_unit_and_old_rule_are_backed_up_before_replacement(self):
        self.assertEqual(self.migrate().returncode, 0)
        unit = self.units / UNIT.name
        old_unit = UNIT.read_text().replace("RestartSec=2", "RestartSec=3")
        unit.write_text(old_unit)
        (self.state / "last-installed.service").write_text(old_unit)
        old_rule = "# earlier stock rule\n"
        (self.rules / RULE.name).write_text(old_rule)
        result = self.migrate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(unit.read_bytes(), UNIT.read_bytes())
        self.assertEqual(next(self.state.glob("backup.*/preimage")).read_text(), old_unit)
        self.assertEqual(next(self.rules.glob("smplos-mouse-backup.*/*")).read_text(), old_rule)

    def test_updater_reconciles_mouse_support_after_delivery_before_verification(self):
        updater = (ROOT / "src/shared/bin/smplos-os-update").read_text()
        main = updater.split("# ── Main", 1)[1]
        self.assertLess(main.index("sync_keypad_support"), main.index("sync_mouse_support"))
        self.assertLess(main.index("sync_mouse_support"), main.index("sync_user_units"))
        self.assertIn(MIGRATION.name, updater)

    def test_service_syntax_is_valid_without_running_a_daemon(self):
        if not shutil.which("systemd-analyze"):
            self.skipTest("systemd-analyze is not installed")
        unit = self.root / UNIT.name
        unit.write_text(UNIT.read_text().replace("/usr/bin/mouse-remapperd", "/usr/bin/true"))
        result = subprocess.run(["systemd-analyze", "--user", "verify", str(unit)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
