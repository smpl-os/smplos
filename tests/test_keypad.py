"""Macro keypad support: detection, firmware dry run, bar/udev/unit wiring, migration.

Everything runs against a fake sysfs tree and fake tools; nothing here opens a
USB device, runs wchisp or talks to the user's session.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
KEYPAD_CTL = ROOT / "src/shared/bin/keypad-ctl"
LISTENER = ROOT / "src/shared/eww/scripts/keypad-listener.sh"
MIGRATION = ROOT / "migrations/20261007-123000-macro-keypad-support.sh"
UDEV = ROOT / "src/shared/system/udev"
UNIT = ROOT / "src/shared/configs/systemd/user/control-surface.service"

STOCK = dict(idVendor="1189", idProduct="8890", manufacturer="wch.cn", product="CH552",
             serial="key153", bcdDevice="0100")
UPSTREAM = dict(STOCK, manufacturer="SY181", product="Macropad 12+3", serial="CH552GPAD")
OPEN = dict(STOCK, manufacturer="OpenMacroPad", product="Control Surface 12+2", bcdDevice="0200")
BOOTLOADER = dict(idVendor="4348", idProduct="55e0", busnum="3", devnum="9")
KEYBOARD = dict(idVendor="0c45", idProduct="760a", manufacturer="SONiX", product="USB Keyboard")


class KeypadCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sysfs = self.root / "sysfs"
        self.sysfs.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        self.env = dict(os.environ, HOME=str(self.home), SMPLOS_KEYPAD_SYSFS=str(self.sysfs),
                        PATH=f"{self.bin}:{os.environ['PATH']}", CALLS=str(self.calls))
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "SMPLOS_WCHISP", "SMPLOS_KEYPAD_FIRMWARE_DIRS",
                    "WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"):
            self.env.pop(key, None)

    def device(self, name, attrs):
        path = self.sysfs / name
        path.mkdir()
        for key, value in attrs.items():
            (path / key).write_text(value + "\n")
        return path

    def tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        return path

    def spawn(self, *args, env=None):
        process = subprocess.Popen(list(args), env=env or self.env, stdout=subprocess.PIPE, text=True)

        def stop():
            process.kill()
            process.wait()
            process.stdout.close()
        self.addCleanup(stop)
        return process

    def calls_made(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def ctl(self, *args, check=True):
        result = subprocess.run(["python3", str(KEYPAD_CTL), *args], env=self.env,
                                capture_output=True, text=True, timeout=20)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result

    def status(self):
        return json.loads(self.ctl("status").stdout)


class DetectionTests(KeypadCase):
    def test_absent_without_keypads_and_ignores_other_keyboards(self):
        self.device("1-1", KEYBOARD)
        data = self.status()
        self.assertEqual((data["present"], data["state"], data["count"]), ("no", "absent", "0"))
        self.assertEqual(data["devices"], [])
        self.assertEqual(self.ctl("present", check=False).returncode, 1)

    def test_stock_keypad_uses_the_default_board_profile(self):
        self.device("1-2", STOCK)
        self.device("1-2:1.0", {})  # interfaces are skipped
        data = self.status()
        self.assertEqual((data["present"], data["state"], data["count"]), ("yes", "ready", "1"))
        pad = data["devices"][0]
        self.assertEqual((pad["firmware"], pad["serial"], pad["path"]), ("stock", "key153", "1-2"))
        self.assertEqual(pad["layout"], dict(board="15+3", keys=15, knobs=3, cols=5,
                                             source="default", supported=True))
        self.assertIn("15 keys, 3 knobs", data["tooltip"])
        self.assertEqual(self.ctl("present", check=False).returncode, 0)

    def test_upstream_open_firmware_is_not_trusted_for_layout(self):
        self.device("1-5", UPSTREAM)
        pad = self.status()["devices"][0]
        self.assertEqual(pad["firmware"], "open-upstream")
        self.assertEqual(pad["layout"]["board"], "15+3")

    def test_our_firmware_describes_its_own_layout(self):
        self.device("1-5", OPEN)
        pad = self.status()["devices"][0]
        self.assertEqual(pad["firmware"], "open")
        self.assertEqual(pad["layout"], dict(board="12+2", keys=12, knobs=2, cols=4,
                                             source="device", supported=True))

    def test_bootloader_alone_shows_update_mode(self):
        self.device("3-1", BOOTLOADER)
        data = self.status()
        self.assertEqual((data["present"], data["state"]), ("yes", "bootloader"))
        self.assertEqual(data["bootloaders"][0]["vid"], "4348")
        self.assertIn("firmware update mode", data["tooltip"])
        self.assertEqual(self.ctl("present", check=False).returncode, 1)
        self.assertEqual(self.ctl("present", "--bootloader", check=False).returncode, 0)

    def test_board_override_round_trip(self):
        self.device("1-2", STOCK)
        self.ctl("set-board", "16+0")
        layout = self.status()["devices"][0]["layout"]
        self.assertEqual((layout["board"], layout["source"], layout["supported"]), ("16+0", "user", True))
        self.assertEqual(self.ctl("set-board", "bogus", check=False).returncode, 2)
        self.ctl("set-board", "auto")
        self.assertEqual(self.status()["devices"][0]["layout"]["source"], "default")
        boards = json.loads(self.ctl("boards").stdout)
        self.assertIn("15+3", [b["id"] for b in boards])

    def test_watch_emits_on_start_and_after_a_change(self):
        process = self.spawn("python3", str(KEYPAD_CTL), "watch")
        first = json.loads(process.stdout.readline())
        self.assertEqual(first["present"], "no")
        self.device("1-2", STOCK)
        second = json.loads(process.stdout.readline())
        self.assertEqual(second["state"], "ready")
        self.assertNotIn("\n", json.dumps(second))

    def test_listener_falls_back_when_keypad_ctl_is_missing(self):
        env = dict(self.env, PATH=f"{self.bin}:/usr/bin:/bin")
        process = self.spawn("bash", str(LISTENER), env=env)
        self.assertEqual(json.loads(process.stdout.readline())["present"], "no")


class FirmwareTests(KeypadCase):
    def setUp(self):
        super().setUp()
        self.fw = self.root / "fw"
        self.fw.mkdir()
        self.env["SMPLOS_KEYPAD_FIRMWARE_DIRS"] = str(self.fw)
        self.image = self.fw / "padfw.bin"
        self.image.write_bytes(b"\x02" * 6144)
        self.digest = hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.wchisp = self.tool("wchisp", 'echo "$*" >> "$CALLS"\n'
                                'case "$1" in\n'
                                '  info) echo "[INFO] Chip: ${CHIP:-CH552}[0x5211] (Code Flash: 14KiB)";;\n'
                                '  flash) echo "[INFO] Erasing..."; echo "[INFO] Erase done";'
                                ' echo "[INFO] Writing to code flash..."; echo "[INFO] Code flash 6144 bytes written";'
                                ' echo "[INFO] Verifying..."; [ -n "$BAD_VERIFY" ] && exit 1; echo "[INFO] Verify OK";;\n'
                                'esac\n')
        self.env["SMPLOS_WCHISP"] = str(self.wchisp)

    def flash(self, *extra, check=False):
        result = self.ctl("firmware", "flash", str(self.image), "--json", *extra, check=check)
        return result.returncode, [json.loads(line) for line in result.stdout.splitlines()]

    def test_list_reports_manifest_verification(self):
        (self.fw / "padfw.json").write_text(json.dumps({"name": "Open firmware", "version": "1.0",
                                                        "sha256": self.digest, "board": "15+3"}))
        (self.fw / "other.bin").write_bytes(b"x")
        (self.fw / "other.json").write_text(json.dumps({"sha256": "0" * 64}))
        images = {Path(i["path"]).name: i for i in json.loads(self.ctl("firmware", "list").stdout)}
        self.assertTrue(images["padfw.bin"]["verified"])
        self.assertEqual(images["padfw.bin"]["name"], "Open firmware")
        self.assertTrue(images["other.bin"]["mismatch"])

    def test_dry_run_never_runs_wchisp(self):
        self.device("3-1", BOOTLOADER)
        code, steps = self.flash()
        self.assertEqual(code, 0)
        self.assertEqual([s["step"] for s in steps], ["preflight", "chip", "erase", "program", "verify", "done"])
        self.assertTrue(all(s["dry_run"] for s in steps))
        self.assertEqual(self.calls_made(), [])

    def test_refuses_without_exactly_one_bootloader(self):
        code, steps = self.flash()
        self.assertEqual((code, steps[-1]["step"]), (1, "error"))
        self.assertIn("hold the top-left key", steps[-1]["detail"])
        self.device("3-1", BOOTLOADER)
        self.device("3-2", dict(BOOTLOADER, idVendor="1a86"))
        code, steps = self.flash("--execute")
        self.assertIn("more than one", steps[-1]["detail"])
        self.assertEqual(self.calls_made(), [])

    def test_refuses_bad_images(self):
        self.device("3-1", BOOTLOADER)
        self.image.write_bytes(b"\x00" * (14 * 1024 + 1))
        code, steps = self.flash("--execute")
        self.assertIn("at most 14336", steps[-1]["detail"])
        self.image.write_bytes(b"\x00" * 100)
        (self.fw / "padfw.json").write_text(json.dumps({"sha256": "f" * 64}))
        code, steps = self.flash("--execute")
        self.assertIn("checksum", steps[-1]["detail"])
        self.assertEqual(self.calls_made(), [])

    def test_execute_checks_the_chip_then_flashes_only(self):
        self.device("3-1", BOOTLOADER)
        code, steps = self.flash("--execute")
        self.assertEqual(code, 0, steps)
        self.assertEqual(self.calls_made(), ["info", f"flash {self.image}"])
        self.assertEqual([(s["step"], s["status"]) for s in steps if s["status"] == "ok"],
                         [("preflight", "ok"), ("chip", "ok"), ("erase", "ok"), ("program", "ok"),
                          ("verify", "ok"), ("done", "ok")])

    def test_execute_refuses_other_chips_and_reports_failed_verify(self):
        self.device("3-1", BOOTLOADER)
        self.env["CHIP"] = "CH32V307"
        code, steps = self.flash("--execute")
        self.assertEqual(code, 1)
        self.assertIn("only flashes CH552", steps[-1]["detail"])
        self.assertEqual(self.calls_made(), ["info"])
        del self.env["CHIP"]
        self.env["BAD_VERIFY"] = "1"
        code, steps = self.flash("--execute")
        self.assertEqual((code, steps[-1]["step"]), (1, "error"))

    def test_wchisp_allowlist(self):
        module = runpy.run_path(str(KEYPAD_CTL))
        for args in (["config", "reset"], ["eeprom", "erase"], ["erase"], ["flash", "x.bin", "--no-verify"], []):
            with self.assertRaises(module["FlashError"]):
                module["run_wchisp"](str(self.wchisp), args, lambda line: None)


class WiringTests(unittest.TestCase):
    def test_udev_rules_match_only_the_keypad_and_start_the_unit(self):
        rules = (UDEV / "70-ch552-macropad.rules").read_text()
        active = [line for line in rules.splitlines() if line and not line.startswith("#")]
        for line in active:
            if "uinput" not in line:
                self.assertIn('ATTR{idVendor}=="1189"' if "usb_device" in line else 'ATTRS{idVendor}=="1189"', line)
                self.assertIn("8890", line)
        self.assertNotIn("0c45", rules)
        self.assertIn('ENV{SYSTEMD_USER_WANTS}+="control-surface.service"', rules)
        symlink = re.search(r'SYMLINK\+="([^"%]+)%k"', rules).group(1)
        self.assertIn(f"ConditionPathExistsGlob=/dev/{symlink}*", UNIT.read_text())
        loader = (UDEV / "71-wch-isp-bootloader.rules").read_text()
        self.assertIn('ATTR{idVendor}=="4348", ATTR{idProduct}=="55e0", TAG+="uaccess"', loader)

    def test_unit_is_inert_without_daemon_or_keypad(self):
        unit = UNIT.read_text()
        self.assertIn("ConditionPathExists=/usr/bin/control-surfaced", unit)
        self.assertIn("ExecStart=/usr/bin/control-surfaced run --quiet", unit)
        self.assertIn("WantedBy=graphical-session.target", unit)
        build = (ROOT / "src/builder/build.sh").read_text()
        self.assertIn('"$user_graphical_wants/control-surface.service"', build)

    def test_bar_icon_and_settings_entry(self):
        yuck = (ROOT / "src/shared/eww/eww.yuck").read_text()
        self.assertIn("`scripts/keypad-listener.sh`", yuck)
        widget = yuck[yuck.index("(defwidget tray-keypad"):]
        widget = widget[:widget.index("\n\n")]
        self.assertIn(':visible {keypad-data.present == "yes"}', widget)
        self.assertIn(':onclick "smplos-settings keypad &"', widget)
        tray = yuck[yuck.index("(defwidget tray []"):]
        self.assertIn("(tray-keypad)", tray[:tray.index("\n\n")])
        self.assertIn(".tray-keypad", (ROOT / "src/shared/eww/eww.scss").read_text())
        for icon in ("keypad.svg", "keypad-bootloader.svg"):
            self.assertIn("{{accent}}", (ROOT / "src/shared/icons/status" / icon).read_text())
        settings = (ROOT / "src/shared/bin/smplos-settings").read_text()
        self.assertIn("exec settings --tab keypad", settings)
        self.assertIn("Keypad;smplos-settings keypad;settings;", (ROOT / "src/shared/bin/rebuild-app-cache").read_text())

    def test_pending_daemon_recipe_is_parked(self):
        self.assertTrue((ROOT / "src/shared/pkgbuilds/control-surface/PENDING").exists())
        self.assertIn('[[ -f "$dir/PENDING" ]]', (ROOT / "src/build-iso.sh").read_text())
        aur = (ROOT / "src/shared/packages-aur.txt").read_text().splitlines()
        self.assertIn("wchisp", aur)
        self.assertIn("# control-surface", aur)


class MigrationTests(KeypadCase):
    def setUp(self):
        super().setUp()
        self.repo = self.root / "repo"
        (self.repo / "migrations").mkdir(parents=True)
        (self.repo / "src/shared/lib").mkdir(parents=True)
        shutil.copy(MIGRATION, self.repo / "migrations")
        (self.repo / "src/shared/lib/smplos-session-env.sh").write_text(
            'smplos_have_user_bus() { return 0; }\n'
            'smplos_run_as_user() { echo "session $*" >> "$CALLS"; }\n')
        self.udev = self.root / "rules.d"
        self.tool("sudo", '"$@"\n')
        self.tool("udevadm", 'echo "udevadm $*" >> "$CALLS"\n')
        self.env.update(SMPLOS_REPO=str(ROOT), SMPLOS_UDEV_RULES_DIR=str(self.udev))
        theme = self.home / ".config/smplos/current/theme"
        theme.mkdir(parents=True)
        (theme / "colors.toml").write_text('accent = "#123abc"\n')
        (self.home / ".config/eww").mkdir(parents=True)
        self.units = self.home / ".config/systemd/user"

    def migrate(self):
        result = subprocess.run(["bash", str(self.repo / "migrations" / MIGRATION.name)], env=self.env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result.stdout

    def test_fresh_migration_installs_everything_once(self):
        pad = self.device("1-5", STOCK)
        output = self.migrate()
        for rule in ("70-ch552-macropad.rules", "71-wch-isp-bootloader.rules"):
            self.assertEqual((self.udev / rule).read_text(), (UDEV / rule).read_text())
        self.assertEqual((self.units / "control-surface.service").read_text(), UNIT.read_text())
        wants = self.units / "graphical-session.target.wants/control-surface.service"
        self.assertTrue(wants.is_symlink())
        baked = (self.home / ".config/eww/icons/status/keypad.svg").read_text()
        self.assertIn('stroke="#123abc"', baked)
        self.assertTrue((self.home / ".local/share/smplos/icons/status/keypad-bootloader.svg").exists())
        calls = self.calls_made()
        self.assertIn("udevadm control --reload-rules", calls)
        self.assertIn(f"udevadm trigger --action=change --parent-match={pad.resolve()}", calls)
        self.assertIn("session systemctl --user start control-surface.service", calls)
        self.assertFalse(any("subsystem-match" in call for call in calls), "only targeted triggers")
        self.assertIn("configured", output)

        self.calls.unlink()
        self.assertIn("already configured", self.migrate())
        self.assertEqual(self.calls_made(), [])

    def test_custom_unit_is_left_alone(self):
        self.units.mkdir(parents=True)
        custom = "[Service]\nExecStart=%h/.local/bin/control-surfaced run --quiet\n"
        (self.units / "control-surface.service").write_text(custom)
        output = self.migrate()
        self.assertEqual((self.units / "control-surface.service").read_text(), custom)
        self.assertFalse((self.units / "graphical-session.target.wants/control-surface.service").exists())
        self.assertIn("custom unit", output)


if __name__ == "__main__":
    unittest.main()
