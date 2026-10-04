"""toggle-start-menu: resident menus are signalled, older builds keep launch/kill.

Every fake runs under a private process name and XDG_RUNTIME_DIR, so the
tests can never signal or kill the user's real Start Menu.
"""

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOGGLE = ROOT / "src/shared/bin/toggle-start-menu"
CLICK_CHECK = ROOT / "src/shared/bin/start-menu-click-check"
HYPR = ROOT / "src/compositors/hyprland/hypr"
NAME = "smtest-menu"  # 12 chars: fits /proc/<pid>/comm


class ToggleStartMenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.log = self.root / "log"
        self.fake = self.root / NAME
        self.env = dict(os.environ, XDG_RUNTIME_DIR=str(self.runtime), SMPL_START_MENU_NAME=NAME,
                        SMPL_START_MENU_BIN=str(self.fake), LOG=str(self.log))
        self.addCleanup(self.stop_fakes)

    def write_fake(self, resident):
        features = 'echo "features: resident"' if resident else ":"
        self.fake.write_text(textwrap.dedent(f"""\
            #!/bin/bash
            if [[ "${{1:-}}" == --version ]]; then
                echo "{NAME} v0.0.1"; {features}; exit 0
            fi
            echo "start $*" >> "$LOG"
            trap 'echo USR1 >> "$LOG"' USR1
            trap 'echo USR2 >> "$LOG"' USR2
            trap 'exit 0' TERM
            if [[ "${{1:-}}" == --resident ]]; then
                sleep "${{PIDFILE_DELAY:-0}}"
                mkdir -p "$XDG_RUNTIME_DIR/smplos"
                echo $$ > "$XDG_RUNTIME_DIR/smplos/start-menu.pid"
            fi
            while :; do sleep 0.05; done
            """))
        self.fake.chmod(0o755)

    def stop_fakes(self):
        subprocess.run(["pkill", "-KILL", "-x", NAME], check=False)
        deadline = time.monotonic() + 5
        while self.running() and time.monotonic() < deadline:
            time.sleep(0.02)

    def toggle(self, *args):
        subprocess.run(["bash", str(TOGGLE), *args], env=self.env, check=True, timeout=10)

    def events(self, count, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            lines = self.log.read_text().splitlines() if self.log.exists() else []
            if len(lines) >= count:
                return lines
            time.sleep(0.02)
        return self.log.read_text().splitlines() if self.log.exists() else []

    def running(self):
        return subprocess.run(["pgrep", "-x", NAME], capture_output=True).returncode == 0

    def test_resident_menu_is_started_once_then_toggled_and_hidden_by_signals(self):
        self.write_fake(resident=True)
        self.toggle()
        self.assertEqual(self.events(1), ["start --resident"])
        self.toggle()
        self.toggle("--hide")
        self.assertEqual(self.events(3), ["start --resident", "USR1", "USR2"])
        self.assertTrue(self.running())

    def test_preload_starts_a_hidden_resident_menu_only_once(self):
        self.write_fake(resident=True)
        self.toggle("--preload")
        self.assertEqual(self.events(1), ["start --resident --hidden"])
        self.toggle("--preload")
        time.sleep(0.3)
        self.assertEqual(self.events(1), ["start --resident --hidden"])

    def test_older_builds_keep_launch_and_kill_and_are_never_preloaded(self):
        self.write_fake(resident=False)
        self.toggle("--preload")
        time.sleep(0.3)
        self.assertFalse(self.log.exists(), "an old build must not be started (it would show the UI)")
        self.toggle()
        self.assertEqual(self.events(1), ["start "])
        self.toggle()
        deadline = time.monotonic() + 5
        while self.running() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.running())

    def test_a_resident_that_is_still_starting_is_never_killed(self):
        self.write_fake(resident=True)
        starting = subprocess.Popen([str(self.fake), "--resident", "--hidden"],
                                    env=dict(self.env, PIDFILE_DELAY="3"))
        self.addCleanup(starting.kill)
        self.assertEqual(self.events(1), ["start --resident --hidden"])
        self.toggle()
        self.toggle("--hide")
        time.sleep(0.3)
        self.assertIsNone(starting.poll(), "the starting resident must survive")
        self.assertIn("start --resident", self.events(2))

    def test_a_stale_pidfile_starts_a_new_resident_menu(self):
        self.write_fake(resident=True)
        (self.runtime / "smplos").mkdir()
        (self.runtime / "smplos/start-menu.pid").write_text("999999\n")
        self.toggle()
        self.assertEqual(self.events(1), ["start --resident"])

    def test_click_outside_hides_instead_of_killing(self):
        text = CLICK_CHECK.read_text()
        self.assertIn("toggle-start-menu --hide", text)
        self.assertNotIn("pkill -x start-menu", text)

    def test_both_config_trees_preload_the_menu(self):
        self.assertIn('hl.exec_cmd("bash -c \'sleep 2 && toggle-start-menu --preload\'")',
                      (HYPR / "autostart.lua").read_text())
        self.assertIn("exec-once = bash -c 'sleep 2 && toggle-start-menu --preload'",
                      (HYPR / "autostart.conf").read_text())

    def test_menu_appears_without_the_slide_animation(self):
        self.assertRegex((HYPR / "windows.lua").read_text(),
                         r'class = "\^\(start-menu\)\$" \},[^}]*no_anim = true')
        self.assertIn("windowrule = no_anim on, match:class ^(start-menu)$", (HYPR / "windows.conf").read_text())


if __name__ == "__main__":
    unittest.main()
