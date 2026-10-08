"""Macro keypad support: detection, firmware dry run, device-bound lifecycle,
bar wiring and migration.

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
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
KEYPAD_CTL = ROOT / "src/shared/bin/keypad-ctl"
BAR_CTL = ROOT / "src/shared/bin/bar-ctl"
SESSION_SERVICES = ROOT / "src/shared/bin/smplos-session-services"
MIGRATION = ROOT / "migrations/20261007-123000-macro-keypad-support.sh"
UDEV = ROOT / "src/shared/system/udev"
UNIT = ROOT / "src/shared/configs/systemd/user/control-surface.service"
SHEET_HIDE = ROOT / "src/shared/eww/scripts/pad-sheet-hide.sh"

STOCK = dict(idVendor="1189", idProduct="8890", manufacturer="wch.cn", product="CH552",
             serial="key153", bcdDevice="0100")
UPSTREAM = dict(STOCK, manufacturer="SY181", product="Macropad 12+3", serial="CH552GPAD")
OPEN = dict(STOCK, manufacturer="OpenMacroPad", product="Control Surface 15+3", bcdDevice="0201")
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
        self.assertEqual((data["state"], data["devices"], data["bootloaders"]), ("absent", [], []))
        self.assertEqual(self.ctl("present", check=False).returncode, 1)

    def test_stock_keypad_has_no_self_described_layout(self):
        self.device("1-2", STOCK)
        self.device("1-2:1.0", {})  # interfaces are skipped
        data = self.status()
        self.assertEqual(data["state"], "ready")
        pad = data["devices"][0]
        self.assertEqual((pad["firmware"], pad["firmware_type"], pad["serial"], pad["path"]),
                         ("stock", "stock", "key153", "1-2"))
        self.assertIsNone(pad["layout"])
        self.assertEqual(self.ctl("present", check=False).returncode, 0)

    def test_upstream_open_firmware_is_not_trusted_for_layout(self):
        self.device("1-5", UPSTREAM)
        pad = self.status()["devices"][0]
        self.assertEqual((pad["firmware"], pad["firmware_type"]), ("open-upstream", "openmacropad"))
        self.assertIsNone(pad["layout"])

    def test_our_firmware_describes_its_own_layout(self):
        self.device("1-5", OPEN)
        pad = self.status()["devices"][0]
        self.assertEqual((pad["firmware"], pad["firmware_type"]), ("open", "control-surface"))
        self.assertEqual(pad["layout"], {"board": "sy181-15k3e", "keys": 15, "knobs": 3})
        self.device("1-6", dict(OPEN, product="Control Surface 12+2"))
        other = self.status()["devices"][1]
        self.assertEqual(other["layout"], {"board": "", "keys": 12, "knobs": 2})

    def test_bootloader_alone(self):
        self.device("3-1", BOOTLOADER)
        data = self.status()
        self.assertEqual(data["state"], "bootloader")
        self.assertEqual(data["bootloaders"][0]["vid"], "4348")
        self.assertEqual(self.ctl("present", check=False).returncode, 1)
        self.assertEqual(self.ctl("present", "--bootloader", check=False).returncode, 0)

    def test_no_background_commands(self):
        help_text = self.ctl("--help").stdout
        for gone in ("watch", "set-board", "boards"):
            self.assertNotIn(gone, help_text)
            self.assertNotEqual(self.ctl(gone, check=False).returncode, 0)


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


def escape_device(path):
    return subprocess.run(["systemd-escape", "--path", "--suffix=device", path],
                          capture_output=True, text=True, check=True).stdout.strip()


class SheetHideTests(KeypadCase):
    """scripts/pad-sheet-hide.sh: what a click on the cheatsheet overlay runs.
    EWW runs it from its config directory, so it needs nothing on PATH but
    busctl and eww."""

    def setUp(self):
        super().setUp()
        self.tool("eww", 'echo "eww $*" >> "$CALLS"\n')
        self.config = self.root / "eww"
        (self.config / "scripts").mkdir(parents=True)
        shutil.copy(SHEET_HIDE, self.config / "scripts")

    def hide(self):
        result = subprocess.run(["sh", "scripts/pad-sheet-hide.sh"], cwd=self.config, env=self.env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_asks_the_daemon_first(self):
        self.tool("busctl", 'echo "busctl $*" >> "$CALLS"\n')
        self.hide()
        self.assertEqual(self.calls_made(), [
            "busctl --user --timeout=2 call org.smplos.ControlSurface /org/smplos/ControlSurface "
            "org.smplos.ControlSurface1 HideCheatsheet"])

    def test_closes_it_in_its_own_eww_without_a_daemon(self):
        self.tool("busctl", 'echo "busctl $*" >> "$CALLS"\nexit 1\n')
        self.hide()
        self.assertEqual(self.calls_made()[1:], [
            f"eww --config {self.config} close pad-cheatsheet pad-cheatsheet-passthrough",
            f'eww --config {self.config} update pad_sheet={{"visible":false}}'])


FONTS = ROOT / "src/shared/fonts"
PAD_ICONS = ROOT / "src/shared/eww/pad-icons.yuck"
# Every icon the keypad app picks by itself (features.cheatsheet.icons.auto),
# pinned from its build: all of them must be in the bundled font.
DAEMON_AUTO = FONTS / "keypad-icons/daemon-auto.txt"


def names_in(path):
    return [w for line in path.read_text().splitlines() for w in line.split("#")[0].split()]


def icon_vocabulary():
    names = []
    for line in (FONTS / "keypad-icons/icons.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("["):
            names += line.split()
    return names


class KeypadIconTests(unittest.TestCase):
    """The cheatsheet's outline icons: icons.txt -> font, JSON and eww table."""

    def table(self):
        return json.loads((FONTS / "keypad-icons.json").read_text())

    def eww_glyphs(self):
        text = PAD_ICONS.read_text()
        literal = re.search(r"\(defvar pad_icons '(.*)'\)", text).group(1)
        # yuck strings drop one backslash; eww then parses the JSON.
        return json.loads(literal.replace("\\\\", "\\"))

    def test_icons_txt_json_and_eww_table_agree(self):
        names = icon_vocabulary()
        self.assertEqual(len(names), len(set(names)))
        table = self.table()
        self.assertEqual(table["family"], "smplOS Keypad Icons")
        self.assertEqual([i["name"] for i in table["icons"]], names)
        glyphs = self.eww_glyphs()
        self.assertEqual(list(glyphs), names)
        for icon in table["icons"]:
            self.assertEqual(glyphs[icon["name"]], chr(int(icon["codepoint"], 16)), icon["name"])
        self.assertTrue(PAD_ICONS.read_text().isascii(), "generated, but readable and diffable")

    def test_every_automatic_and_overlay_icon_is_bundled(self):
        names = set(icon_vocabulary())
        auto = names_in(DAEMON_AUTO)
        self.assertGreaterEqual(len(auto), 121)
        self.assertEqual(sorted(set(auto) - names), [], "the keypad app's automatic icons need glyphs")
        yuck = (ROOT / "src/shared/eww/eww.yuck").read_text()
        for direction in re.findall(r':dir "([a-z0-9-]+)"', yuck):
            self.assertIn(direction, names)

    def test_a_built_keypad_app_picks_only_bundled_icons(self):
        """With SMPLOS_CONTROL_SURFACED or control-surfaced on PATH (a build
        with icons), its live features --json must also be covered."""
        daemon = os.environ.get("SMPLOS_CONTROL_SURFACED") or shutil.which("control-surfaced")
        if not daemon:
            self.skipTest("no keypad app to ask")
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run([daemon, "features", "--json"], env=dict(os.environ, HOME=home),
                                    capture_output=True, text=True, timeout=20)
        icons = json.loads(result.stdout or "{}").get("cheatsheet", {}).get("icons") if result.returncode == 0 else None
        if not icons:
            self.skipTest("this keypad app predates icons")
        self.assertEqual((icons["set"], icons["version"]), ("tabler-outline", self.table()["source"].split()[2]))
        self.assertEqual(sorted(set(icons["auto"]) - set(icon_vocabulary())), [])

    def test_font_has_every_glyph_under_its_family_name(self):
        try:
            from fontTools.ttLib import TTFont
        except ImportError:
            self.skipTest("fontTools not installed")
        font = TTFont(FONTS / "smplos-keypad-icons.ttf")
        cmap = font.getBestCmap()
        for icon in self.table()["icons"]:
            self.assertIn(int(icon["codepoint"], 16), cmap, icon["name"])
        self.assertEqual(font["name"].getDebugName(1), "smplOS Keypad Icons")
        self.assertLess((FONTS / "smplos-keypad-icons.ttf").stat().st_size, 100_000, "a subset, not all of Tabler")

    def test_overlay_draws_icons_with_the_bundled_font(self):
        yuck = (ROOT / "src/shared/eww/eww.yuck").read_text()
        self.assertIn('(include "./pad-icons.yuck")', yuck)
        self.assertIn('(pad-sheet-key :k k :glyph {pad_icons_font == "yes" ? (pad_icons[k?.icon ?: ""] ?: "") : ""})', yuck)
        for event in ("ccw", "press", "cw"):
            self.assertIn(f':glyph {{pad_icons_font == "yes" ? (pad_icons[n.{event}?.icon ?: ""] ?: "") : ""}}', yuck)
        key = yuck[yuck.index("(defwidget pad-sheet-key"):yuck.index("(defwidget pad-sheet-turn")]
        self.assertIn('(label :class "pad-sheet-icon" :visible {k.bound && glyph != ""} :text glyph)', key)
        scss = (ROOT / "src/shared/eww/eww.scss").read_text()
        icons = scss[scss.index(".pad-sheet-icon,"):]
        self.assertIn(f'font-family: "{self.table()["family"]}";', icons)
        self.assertNotRegex(icons, r"(?<!-)opacity\s*:", "icons are as opaque as text")

    def test_licence_ships_with_the_font(self):
        licence = (FONTS / "keypad-icons/LICENSE-tabler-icons.txt").read_text()
        self.assertTrue(licence.startswith("MIT License"))
        self.assertIn("Paweł Kuna", licence)
        build = (ROOT / "src/builder/build.sh").read_text()
        self.assertIn('"$SRC_DIR/shared/fonts/keypad-icons/LICENSE-tabler-icons.txt"', build)
        self.assertIn('$skel/.local/share/fonts/smplos/', build)
        install = (ROOT / "src/shared/installer/install.sh").read_text()
        self.assertIn('"$HOME/.local/share/fonts/smplos" "$SMPLOS_PATH/fonts/"*.ttf "$SMPLOS_PATH/fonts/"LICENSE-*.txt', install)
        self.assertIn("Tabler Icons", (ROOT / "KEYPAD.md").read_text())


class IconSyncTests(KeypadCase):
    """smplos-os-update delivers the font and the eww icon table."""

    def test_update_installs_the_font_and_table_before_the_bar(self):
        updater = (ROOT / "src/shared/bin/smplos-os-update").read_text()
        function = lambda name: f"{name}() {{" + updater.split(f"{name}() {{", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
        repo = self.root / "repo"
        for rel in ("src/shared/eww/eww.yuck", "src/shared/eww/pad-icons.yuck", "src/shared/eww/eww.scss",
                    "src/shared/fonts/smplos-keypad-icons.ttf", "src/shared/fonts/keypad-icons/LICENSE-tabler-icons.txt"):
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / rel, repo / rel)
        self.tool("fc-cache", 'echo "fc-cache $*" >> "$CALLS"\n')
        script = ("set -euo pipefail\nheader() { :; }\nok() { :; }\ndie() { echo \"$*\" >&2; exit 1; }\n"
                  "as_invoker() { [[ $1 == mv ]] && echo \"mv ${@: -1}\" >> \"$CALLS\"; \"$@\"; }\n"
                  + function("copy_user_config") + function("sync_configs") + "sync_configs\n")
        env = dict(self.env, SMPLOS_REPO=str(repo))
        for _ in range(2):
            subprocess.run(["bash", "-c", script], env=env, check=True, capture_output=True, text=True, timeout=20)
        fonts = self.home / ".local/share/fonts/smplos"
        self.assertEqual((fonts / "smplos-keypad-icons.ttf").read_bytes(), (FONTS / "smplos-keypad-icons.ttf").read_bytes())
        self.assertTrue((fonts / "LICENSE-tabler-icons.txt").exists())
        calls = self.calls_made()
        self.assertEqual([c for c in calls if c.startswith("fc-cache")], [f"fc-cache -f {fonts}"], "once, only on change")
        moved = [c for c in calls if c.startswith("mv ")]
        self.assertLess(moved.index(f"mv {self.home}/.config/eww/pad-icons.yuck"),
                        moved.index(f"mv {self.home}/.config/eww/eww.yuck"), "the include lands first")


class LifecycleTests(unittest.TestCase):
    """Nothing keypad related runs without a keypad; the unit follows the device."""

    def unit(self):
        return UNIT.read_text()

    def test_udev_rule_matches_only_the_keypad_and_names_its_device_unit(self):
        rules = (UDEV / "70-ch552-macropad.rules").read_text()
        active = [line for line in rules.splitlines() if line and not line.startswith("#")]
        for line in active:
            if "uinput" not in line:
                self.assertIn('ATTR{idVendor}=="1189"' if "usb_device" in line else 'ATTRS{idVendor}=="1189"', line)
                self.assertIn("8890", line)
        self.assertNotIn("0c45", rules)
        usb = next(line for line in active if "usb_device" in line)
        self.assertIn('TAG+="systemd"', usb)
        self.assertIn('ENV{SYSTEMD_USER_WANTS}+="control-surface.service"', usb)
        alias = re.search(r'ENV\{SYSTEMD_ALIAS\}="([^"]+)"', usb).group(1)
        self.assertTrue(alias.startswith("/"), "SYSTEMD_ALIAS must be an absolute path")
        self.assertNotIn("%", alias, "the alias must not vary, so BindsTo= can name it")
        self.assertNotIn("SYMLINK", rules)
        loader = (UDEV / "71-wch-isp-bootloader.rules").read_text()
        self.assertIn('ATTR{idVendor}=="4348", ATTR{idProduct}=="55e0", TAG+="uaccess"', loader)

    @unittest.skipUnless(shutil.which("systemd-escape"), "systemd-escape not installed")
    def test_unit_binds_to_the_alias_device_unit(self):
        rules = (UDEV / "70-ch552-macropad.rules").read_text()
        alias = re.search(r'ENV\{SYSTEMD_ALIAS\}="([^"]+)"', rules).group(1)
        device = escape_device(alias)
        self.assertEqual(device, "smplos-keypad.device")
        unit = self.unit()
        self.assertIn(f"BindsTo={device}\n", unit)
        after = re.search(r"^After=(.*)$", unit, re.M).group(1).split()
        self.assertIn(device, after, "BindsTo= needs After= to stop with the device")
        self.assertIn("smplos-keypad.device", (ROOT / "src/shared/bin/smplos-session-services").read_text())

    def test_unit_is_never_enabled_and_drives_the_bar_variable(self):
        unit = self.unit()
        self.assertNotIn("[Install]", unit)
        self.assertNotIn("WantedBy", unit)
        self.assertNotIn("Requisite=", unit)
        self.assertIn("ConditionPathExists=/usr/bin/control-surfaced", unit)
        self.assertIn("ExecStart=/usr/bin/control-surfaced run --quiet --eww-window pad-cheatsheet "
                      "--eww-config %h/.config/eww", unit)
        self.assertIn('grep -q \'"eww-window"\'', (ROOT / "src/shared/pkgbuilds/control-surface/PKGBUILD").read_text(),
                      "the package refuses daemon sources that lack the unit's flags")
        self.assertIn("ExecStartPost=-/usr/bin/eww --config %h/.config/eww update keypad-present=yes", unit)
        self.assertIn("ExecStopPost=-/usr/bin/eww --config %h/.config/eww update keypad-present=no", unit)
        build = (ROOT / "src/builder/build.sh").read_text()
        self.assertNotIn('wants/control-surface.service"', build)
        self.assertNotIn("enable control-surface", MIGRATION.read_text())

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze not installed")
    def test_unit_passes_systemd_analyze_verify(self):
        with tempfile.TemporaryDirectory() as temp:
            unit = Path(temp) / "control-surface.service"
            # The binaries don't exist on a build host; everything else is checked.
            unit.write_text(self.unit().replace("/usr/bin/control-surfaced", "/usr/bin/true")
                            .replace("/usr/bin/eww", "/usr/bin/true"))
            env = {k: v for k, v in os.environ.items() if k != "DBUS_SESSION_BUS_ADDRESS"}
            env.update(XDG_RUNTIME_DIR=temp, SYSTEMD_UNIT_PATH=f"{temp}:")
            result = subprocess.run(["systemd-analyze", "--user", "--man=no", "verify", str(unit)],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bar_has_no_keypad_watcher(self):
        yuck = (ROOT / "src/shared/eww/eww.yuck").read_text()
        for line in yuck.splitlines():
            if re.match(r"\s*\((deflisten|defpoll)\b", line):
                self.assertNotIn("keypad", line)
                self.assertNotIn("pad-sheet", line, "the overlay's click handler runs only on a click")
        self.assertIn('(defvar keypad-present "no")', yuck)
        self.assertFalse(list((ROOT / "src/shared/eww/scripts").glob("*keypad*")))
        self.assertNotIn("bootloader", yuck[yuck.index("(defwidget tray-keypad"):])

    def test_bar_icon_and_settings_entry(self):
        yuck = (ROOT / "src/shared/eww/eww.yuck").read_text()
        widget = yuck[yuck.index("(defwidget tray-keypad"):]
        widget = widget[:widget.index("\n\n")]
        self.assertIn(':visible {keypad-present == "yes"}', widget)
        self.assertIn(':onclick "smplos-settings keypad &"', widget)
        tray = yuck[yuck.index("(defwidget tray []"):]
        self.assertIn("(tray-keypad)", tray[:tray.index("\n\n")])
        self.assertIn(".tray-keypad", (ROOT / "src/shared/eww/eww.scss").read_text())
        self.assertIn("{{accent}}", (ROOT / "src/shared/icons/status/keypad.svg").read_text())
        self.assertFalse((ROOT / "src/shared/icons/status/keypad-bootloader.svg").exists())
        settings = (ROOT / "src/shared/bin/smplos-settings").read_text()
        self.assertIn("exec settings --tab keypad", settings)
        self.assertIn("Keypad;smplos-settings keypad;settings;", (ROOT / "src/shared/bin/rebuild-app-cache").read_text())

    def test_cheatsheet_overlay_is_pushed_not_listened_for(self):
        yuck = (ROOT / "src/shared/eww/eww.yuck").read_text()
        self.assertIn("""(defvar pad_sheet '{"visible":false}')""", yuck)
        self.assertNotIn("cheatsheet --follow", yuck)
        windows = dict(re.findall(r"\(defwindow (pad-cheatsheet\S*)\n(.*?)\n\n", yuck + "\n\n", re.S))
        self.assertEqual(sorted(windows), ["pad-cheatsheet", "pad-cheatsheet-passthrough"])
        self.assertIn("close " + " ".join(sorted(windows)), SHEET_HIDE.read_text(),
                      "a click closes every overlay window")
        for name, window in windows.items():
            for needle in (':namespace "eww-pad-cheatsheet"', ':stacking "overlay"', ":focusable false"):
                self.assertIn(needle, window)
            through = name.endswith("-passthrough")
            self.assertEqual(":passthrough true" in window, through)
            self.assertIn(f"(pad-sheet :through {str(through).lower()})", window)
        sheet = yuck[yuck.index("(defwidget pad-sheet-hint"):yuck.index("(defwindow pad-cheatsheet")]
        for field in ("pad_sheet.title", "pad_sheet.notice", "pad_sheet.keys", "pad_sheet.knobs",
                      "pad_sheet.options?.opacity", "pad_sheet.layers", "pad_sheet.options?.autoHideMs"):
            self.assertIn(field, sheet)
        self.assertIn('(eventbox :onclick "sh scripts/pad-sheet-hide.sh &"', sheet, "a click anywhere dismisses it")
        self.assertIn('"Click to close"', sheet)
        self.assertIn("(pad_sheet.options?.opacity ?: 0.35) * 20", sheet, "see-through by default")
        scss = (ROOT / "src/shared/eww/eww.scss").read_text()
        self.assertIn(".pad-sheet.o#{$i}", scss)
        self.assertIn("background-color: rgba(darken($bg, 5%), $i / 20)", scss)
        self.assertIn("border: 1px dashed", scss, "inactive bindings differ by shape, not only color")
        styles = scss[scss.index("Macro keypad cheatsheet"):]
        self.assertNotRegex(styles, r"(?<!-)opacity\s*:", "alpha only on the background, never on text")
        self.assertEqual(styles.count("rgba("), 1, "the background loop is the only translucent color")
        for path in ("windows.conf", "windows.lua"):
            self.assertIn("eww-pad-cheatsheet", (ROOT / "src/compositors/hyprland/hypr" / path).read_text())

    @unittest.skipUnless(shutil.which("eww"), "eww not installed")
    def test_eww_parses_the_bar_config(self):
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="kpe") as temp:
            config = Path(temp) / "eww"
            shutil.copytree(ROOT / "src/shared/eww", config)
            for script in (config / "scripts").iterdir():
                script.write_text("#!/bin/sh\nexec sleep 30\n")
                script.chmod(0o755)
            run = Path(temp) / "run"
            run.mkdir(mode=0o700)
            env = {k: v for k, v in os.environ.items() if k not in (
                "WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "XDG_SESSION_TYPE", "DBUS_SESSION_BUS_ADDRESS")}
            env.update(HOME=temp, XDG_RUNTIME_DIR=str(run))
            # Without a display the daemon can't start GTK, but the config is
            # parsed first: a yuck error is reported before that.
            result = subprocess.run(["eww", "--config", str(config), "daemon", "--no-daemonize"],
                                    env=env, capture_output=True, text=True, timeout=30)
            output = result.stdout + result.stderr
            self.assertNotIn("error:", output.split("Failed to initialize GTK")[0].lower(), output)

    def test_pending_daemon_recipe_is_parked(self):
        self.assertTrue((ROOT / "src/shared/pkgbuilds/control-surface/PENDING").exists())
        self.assertIn('[[ -f "$dir/PENDING" ]]', (ROOT / "src/build-iso.sh").read_text())
        aur = (ROOT / "src/shared/packages-aur.txt").read_text().splitlines()
        self.assertIn("wchisp", aur)
        self.assertIn("# control-surface", aur)


class OneShotSyncTests(KeypadCase):
    """The bar learns the state once at start/reload; login restarts the app once."""

    def setUp(self):
        super().setUp()
        self.tool("systemctl", 'echo "systemctl $*" >> "$CALLS"\n'
                  'case "$*" in\n'
                  '  *"is-active --quiet control-surface.service"*) [ -n "$APP_ACTIVE" ];;\n'
                  '  *"is-active --quiet smplos-keypad.device"*) [ -n "$KEYPAD" ];;\n'
                  '  *is-active*) exit 3;;\n'
                  'esac\n')
        self.tool("eww", 'echo "eww $*" >> "$CALLS"\n')
        self.tool("notify-send", "exit 0\n")
        (self.home / ".config/eww").mkdir(parents=True)
        for name in ("eww.yuck", "eww.scss", "theme-colors.scss"):
            (self.home / ".config/eww" / name).touch()
        self.bar_ctl = self.root / "bar-ctl"
        self.bar_ctl.write_text(BAR_CTL.read_text().replace('LOG="/tmp/eww-startup.log"',
                                                           f'LOG="{self.root / "bar.log"}"'))

    def reload_bar(self, **env):
        self.calls.unlink(missing_ok=True)
        subprocess.run(["bash", str(self.bar_ctl), "reload"], env=dict(self.env, **env),
                       capture_output=True, text=True, timeout=20)
        return [c for c in self.calls_made() if "keypad" in c]

    def test_bar_reload_sets_the_icon_only_while_the_app_runs(self):
        config = self.home / ".config/eww"
        self.assertEqual(self.reload_bar(APP_ACTIVE="1"),
                         [f"eww --config {config} update keypad-present=yes"])
        self.assertEqual(self.reload_bar(), [], "inactive: the defvar default already says no")

    def icons_flag(self, font_age, eww_age, installed=True):
        """bar-ctl reload with an icon font installed font_age s ago and an
        EWW daemon started eww_age s ago."""
        font = self.root / "fonts/smplos-keypad-icons.ttf"
        font.parent.mkdir(exist_ok=True)
        font.touch()
        os.utime(font, (time.time() - font_age,) * 2)
        self.tool("fc-list", f'[ -n "{"1" if installed else ""}" ] && echo "{font}"\nexit 0\n')
        self.tool("pgrep", 'echo 4242\n')
        self.tool("ps", f'echo "{eww_age}"\n')
        self.calls.unlink(missing_ok=True)
        subprocess.run(["bash", str(self.bar_ctl), "reload"], env=self.env, capture_output=True, text=True, timeout=20)
        return [c for c in self.calls_made() if "pad_icons_font" in c]

    def test_icons_only_for_an_eww_that_started_with_the_font(self):
        config = self.home / ".config/eww"
        self.assertEqual(self.icons_flag(font_age=600, eww_age=60), [f"eww --config {config} update pad_icons_font=yes"])
        self.assertEqual(self.icons_flag(font_age=60, eww_age=600), [], "font installed after EWW started")
        self.assertEqual(self.icons_flag(font_age=600, eww_age=60, installed=False), [], "no font")
        yuck = (ROOT / "src/shared/eww/eww.yuck").read_text()
        self.assertIn('(defvar pad_icons_font "no")', yuck)
        self.assertEqual(yuck.count('pad_icons_font == "yes" ? (pad_icons['), 4, "every glyph lookup is gated")

    def login(self, **env):
        self.calls.unlink(missing_ok=True)
        env = dict(self.env, XDG_CONFIG_HOME=str(self.root / "cfg"), XDG_STATE_HOME=str(self.root / "state"),
                   XDG_CACHE_HOME=str(self.root / "cache"), SMPLOS_SYSTEM_USER_UNITS=str(self.root / "none"),
                   SMPLOS_SESSION_SETTLE="0", SMPLOS_SESSION_RETRY="0", **env)
        subprocess.run(["bash", str(SESSION_SERVICES)], env=env, capture_output=True, text=True, timeout=20)
        return self.calls_made()

    def test_login_restarts_the_app_once_only_with_a_keypad(self):
        calls = self.login(KEYPAD="1")
        self.assertIn("systemctl --user restart control-surface.service", calls)
        self.assertLess(calls.index("systemctl --user start smplos-session.target"),
                        calls.index("systemctl --user restart control-surface.service"))
        self.assertNotIn("systemctl --user restart control-surface.service", self.login())


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

    def test_fresh_migration_installs_but_never_enables(self):
        pad = self.device("1-5", STOCK)
        output = self.migrate()
        for rule in ("70-ch552-macropad.rules", "71-wch-isp-bootloader.rules"):
            self.assertEqual((self.udev / rule).read_text(), (UDEV / rule).read_text())
        self.assertEqual((self.units / "control-surface.service").read_text(), UNIT.read_text())
        self.assertFalse(list(self.units.glob("*.wants/control-surface.service")))
        baked = (self.home / ".config/eww/icons/status/keypad.svg").read_text()
        self.assertIn('stroke="#123abc"', baked)
        calls = self.calls_made()
        self.assertIn("udevadm control --reload-rules", calls)
        self.assertIn(f"udevadm trigger --action=change --parent-match={pad.resolve()}", calls)
        self.assertIn("session systemctl --user daemon-reload", calls)
        self.assertFalse(any("start" in call or "enable" in call for call in calls))
        self.assertFalse(any("subsystem-match" in call for call in calls), "only targeted triggers")
        self.assertIn("configured", output)

        self.calls.unlink()
        self.assertIn("already configured", self.migrate())
        self.assertEqual(self.calls_made(), [])

    def test_an_earlier_smplos_unit_is_updated_and_no_longer_starts_at_login(self):
        self.units.mkdir(parents=True)
        old = ("[Unit]\nDocumentation=https://github.com/smpl-os/smplos/blob/main/KEYPAD.md\n"
               "[Service]\nExecStart=/usr/bin/control-surfaced run --quiet\n"
               "[Install]\nWantedBy=graphical-session.target\n")
        (self.units / "control-surface.service").write_text(old)
        wants = self.units / "graphical-session.target.wants"
        wants.mkdir()
        (wants / "control-surface.service").symlink_to("../control-surface.service")
        output = self.migrate()
        self.assertEqual((self.units / "control-surface.service").read_text(), UNIT.read_text())
        self.assertFalse((wants / "control-surface.service").is_symlink())
        self.assertIn("Removed the old login start", output)

    def test_custom_unit_is_left_alone(self):
        self.units.mkdir(parents=True)
        custom = "[Service]\nExecStart=%h/.local/bin/control-surfaced run --quiet\n"
        (self.units / "control-surface.service").write_text(custom)
        wants = self.units / "graphical-session.target.wants"
        wants.mkdir()
        (wants / "control-surface.service").symlink_to("../control-surface.service")
        output = self.migrate()
        self.assertEqual((self.units / "control-surface.service").read_text(), custom)
        self.assertTrue((wants / "control-surface.service").is_symlink())
        self.assertIn("custom unit", output)


if __name__ == "__main__":
    unittest.main()
