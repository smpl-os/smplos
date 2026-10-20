"""Screenshots must not capture slurp's selection overlay.

slurp draws a translucent layer surface (namespace "selection") that Hyprland
animates away when slurp exits. grim runs immediately afterwards, so a captured
frame contained the half-faded white wash and black border. The fix is a
no-animation layer rule in both Hyprland rule trees plus a short settle in the
screenshot script. Every fake below runs from a private directory: the tests
never touch the real compositor, screen or ~/Pictures.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT = ROOT / "src/shared/bin/screenshot"
HYPR = ROOT / "src/compositors/hyprland/hypr"


class SelectionOverlayRuleTests(unittest.TestCase):
    def test_conf_disables_animation_for_slurp_selection_layer(self):
        rules = (HYPR / "windows.conf").read_text().splitlines()
        self.assertIn("layerrule = no_anim on, match:namespace selection", rules)

    @unittest.skipUnless(shutil.which("lua"), "Lua runtime unavailable")
    def test_lua_disables_animation_for_slurp_selection_layer(self):
        harness = r'''
package.path = arg[1] .. "/?.lua;" .. package.path
package.preload.theme = function()
    return {themeOpacityActive = "1.0", themeOpacityInactive = "1.0", themeMessengerOpacity = "1.0"}
end
package.preload.keypad_glass = function() return {} end
hl = {window_rule = function() end,
      layer_rule = function(rule)
          print(rule.match.namespace .. "\t" .. tostring(rule.no_anim))
      end}
dofile(arg[1] .. "/windows.lua")
'''
        result = subprocess.run(["lua", "-", str(HYPR)], input=harness, text=True,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("selection\ttrue", result.stdout.splitlines())


class ScreenshotSettleTests(unittest.TestCase):
    """The script must let the overlay disappear before grim captures."""

    MIN_SETTLE_NS = 150_000_000

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.pictures = self.root / "pictures"
        self.env = dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            HOME=str(self.root),
            XDG_PICTURES_DIR=str(self.pictures),
            WAYLAND_DISPLAY="wayland-fake",
            FAKE_ROOT=str(self.root),
        )

    def fake(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + textwrap.dedent(body))
        path.chmod(0o755)

    def install_fakes(self, selection="10,20 300x200", satty=False):
        self.fake("slurp", f'''
            [[ -n "{selection}" ]] && echo "{selection}"
            date +%s%N > "$FAKE_ROOT/slurp_exit"
            [[ -n "{selection}" ]]
            ''')
        self.fake("grim", '''
            date +%s%N > "$FAKE_ROOT/grim_start"
            echo "$*" > "$FAKE_ROOT/grim_args"
            [[ "${@: -1}" == - ]] && printf png || printf png > "${@: -1}"
            ''')
        self.fake("wl-copy", "cat > /dev/null\n")
        self.fake("notify-send", ":\n")
        if satty:
            self.fake("satty", 'cat > /dev/null; : > "$FAKE_ROOT/satty_ran"\n')

    def run_script(self, *args):
        return subprocess.run(["bash", str(SCREENSHOT), *args], env=self.env,
                              capture_output=True, text=True, timeout=15)

    def stamp(self, name):
        return int((self.root / name).read_text())

    def test_quick_region_capture_waits_for_overlay_to_go_away(self):
        self.install_fakes()
        result = self.run_script("region", "quick")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(self.stamp("grim_start") - self.stamp("slurp_exit"),
                                self.MIN_SETTLE_NS)
        self.assertEqual((self.root / "grim_args").read_text().split()[:2], ["-g", "10,20"])

    def test_edit_region_capture_waits_for_overlay_to_go_away(self):
        self.install_fakes(satty=True)
        result = self.run_script("region", "edit")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "satty_ran").exists())
        self.assertGreaterEqual(self.stamp("grim_start") - self.stamp("slurp_exit"),
                                self.MIN_SETTLE_NS)

    def test_cancelled_selection_captures_nothing(self):
        self.install_fakes(selection="")
        result = self.run_script("region", "quick")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "grim_start").exists())


if __name__ == "__main__":
    unittest.main()
