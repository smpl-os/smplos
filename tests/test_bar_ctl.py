"""bar-ctl apply contract, with private HOME and no desktop/IPC access."""

import json
import os
from pathlib import Path
import runpy
import select
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
Policy = runpy.run_path(str(ROOT / "src/shared/bin/workspace-ctl"))["Policy"]


class BarApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / ".config/eww"
        (self.config / "scripts").mkdir(parents=True)
        for name in ("eww.yuck", "eww.scss", "theme-colors.scss"):
            (self.config / name).touch()
        self.conf = self.root / ".config/smplos/bar.conf"
        self.conf.parent.mkdir()
        self.log = self.root / "bar.log"
        self.calls = self.root / "calls"
        self.script = self.root / "bar-ctl"
        # Keep startup logging private even with an inherited XDG_STATE_HOME.
        self.script.write_text((ROOT / "src/shared/bin/bar-ctl").read_text().replace(
            'LOG="${XDG_STATE_HOME:-$HOME/.local/state}/smplos/eww-startup.log"', f'LOG="{self.log}"'))
        mock_bin = self.root / "bin"
        mock_bin.mkdir()
        eww = mock_bin / "eww"
        eww.write_text(
            "#!/usr/bin/env python3\nimport json, os, sys\n"
            "with open(os.environ['CALLS'], 'a') as out:\n"
            "    out.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if os.environ.get('FAIL_EWW') == '1':\n"
            "    print('mock: EWW connection failed', file=sys.stderr)\n"
            "    sys.exit(17)\n"
            "if os.environ.get('FAIL_SCREEN') == '1' and '--screen' in sys.argv:\n"
            "    print('mock: unknown monitor', file=sys.stderr)\n"
            "    sys.exit(18)\n")
        eww.chmod(0o755)
        workspace_ctl = mock_bin / "workspace-ctl"
        workspace_ctl.write_text('#!/bin/sh\n[ "$1" = primary ] && [ -n "$PRIMARY" ] && echo "$PRIMARY"\n')
        workspace_ctl.chmod(0o755)
        watcher = mock_bin / "inotifywait"
        watcher.write_text("#!/bin/sh\nexit 0\n")
        watcher.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.root), PATH=f"{mock_bin}:{os.environ['PATH']}",
                        CALLS=str(self.calls), XDG_RUNTIME_DIR=str(self.root / "runtime"), PRIMARY="")
        for key in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE",
                    "NIRI_SOCKET", "DBUS_SESSION_BUS_ADDRESS"):
            self.env.pop(key, None)

    def run_apply(self, **env):
        return subprocess.run(["bash", str(self.script), "apply"],
                              env=dict(self.env, **env), capture_output=True, text=True, timeout=10)

    def read_legacy_count(self):
        return subprocess.run(["bash", str(ROOT / "src/shared/eww/scripts/workspace-count.sh")],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def read_policy_count(self):
        return Policy(backend=object(), config_dir=self.conf.parent,
                      runtime_dir=self.root / "runtime").configured_count()

    def assert_update(self, count="4", position="center", spacing="1", style="numbers"):
        self.assertEqual([json.loads(line) for line in self.calls.read_text().splitlines()], [[
            "--config", str(self.config), "update", f"ws-count={count}", f"ws-position={position}",
            f"ws-spacing={spacing}", f"ws-style={style}",
        ]])

    def test_missing_file_uses_existing_defaults_in_one_update(self):
        self.assertEqual(self.run_apply().returncode, 0)
        self.assert_update()
        self.assertFalse(self.conf.exists())

    def test_all_preferences_and_unrelated_clock_keys(self):
        contents = "# user comment\nws_count=7\nclock_date_fmt=Mon D\nws_position=left\nws_spacing=10\nws_style=squares"
        self.conf.write_text(contents)
        self.assertEqual(self.run_apply().returncode, 0)
        self.assert_update("7", "left", "10", "squares")
        self.assertEqual(self.conf.read_text(), contents)

    def test_each_valid_spacing_and_count_boundary(self):
        for spacing in range(1, 11):
            self.conf.write_text(f"ws_count=10\nws_spacing={spacing}\n")
            self.calls.unlink(missing_ok=True)
            self.assertEqual(self.run_apply().returncode, 0)
            self.assert_update(count="10", spacing=str(spacing))
        self.conf.write_text("ws_count=1\n")
        self.calls.unlink()
        self.assertEqual(self.run_apply().returncode, 0)
        self.assert_update(count="1")

    def test_invalid_preferences_never_update_any_variable(self):
        for key, values in (
            ("ws_count", ("0", "11", "-1", "1.5", "1 0", "no", "")),
            ("ws_spacing", ("0", "11", "-1", "1.5", "1 0", "no", "")),
            ("ws_position", ("right", "")),
            ("ws_style", ("circles", "")),
        ):
            for value in values:
                with self.subTest(key=key, value=value):
                    self.conf.write_text(f"{key}={value}\n")
                    result = self.run_apply()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"Invalid {key}", result.stderr)
                    self.assertFalse(self.calls.exists())
                    self.assertNotIn("bar-ctl apply: ws_count=", self.log.read_text())

    def test_duplicate_managed_preferences_are_rejected(self):
        for key, value in (("ws_count", "7"), ("ws_spacing", "2"),
                           ("ws_position", "left"), ("ws_style", "squares")):
            with self.subTest(key=key):
                self.conf.write_text(f"{key}={value}\n {key} = {value}\n")
                result = self.run_apply()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"Duplicate {key}", result.stderr)
                self.assertFalse(self.calls.exists())

    def test_count_readers_share_whitespace_comment_and_crlf_grammar(self):
        fixtures = (
            ("", 4),
            ("# ws_count=9\n \t# ws_count = 8\r\n", 4),
            ("ws_count=7", 7),
            (" \tws_count \t= \t7 \t\r\n", 7),
            ("\r\n# user prefs\r\nclock_date_fmt=Mon D\r\n ws_count = 7 \r\n", 7),
            ("ws_ count=7\nws_co\tunt=8\n", 4),
        )
        for contents, count in fixtures:
            with self.subTest(contents=contents):
                self.conf.write_bytes(contents.encode())
                self.calls.unlink(missing_ok=True)
                self.assertEqual(self.run_apply().returncode, 0)
                self.assert_update(count=str(count))
                self.assertEqual(self.read_policy_count(), count)
                legacy = self.read_legacy_count()
                self.assertEqual(legacy.returncode, 0, legacy.stderr)
                self.assertEqual(legacy.stdout.strip(), str(count))
                self.assertEqual(self.conf.read_bytes(), contents.encode())

    def test_count_readers_report_invalid_values_and_duplicates(self):
        for contents in ("ws_count=1 0\n", "ws_count=1\t0\n", "ws_count=1_0\n",
                         "ws_count=no\n", "ws_count=\n", "ws_count\n",
                         "ws_count=7\n ws_count = 8\r\n"):
            with self.subTest(contents=contents):
                self.conf.write_text(contents)
                applied = self.run_apply()
                self.assertNotEqual(applied.returncode, 0)
                self.assertIn("ws_count", applied.stderr)
                self.assertFalse(self.calls.exists())
                with self.assertRaises(ValueError):
                    self.read_policy_count()
                legacy = self.read_legacy_count()
                self.assertEqual(legacy.returncode, 0)  # Finite mock watcher exits normally.
                self.assertIn("ws_count", legacy.stderr)
                self.assertEqual(legacy.stdout, "")

    def test_count_readers_keep_their_existing_ranges(self):
        for value, policy_count, legacy_count in (("0", None, 1), ("11", 11, 10), ("100", 100, 10)):
            with self.subTest(value=value):
                self.conf.write_text(f"ws_count={value}\n")
                self.assertNotEqual(self.run_apply().returncode, 0)
                if policy_count is None:
                    with self.assertRaises(ValueError):
                        self.read_policy_count()
                else:
                    self.assertEqual(self.read_policy_count(), policy_count)
                legacy = self.read_legacy_count()
                self.assertEqual(legacy.returncode, 0, legacy.stderr)
                self.assertEqual(legacy.stdout.strip(), str(legacy_count))

    def test_unreadable_config_type_reports_error(self):
        self.conf.mkdir()
        result = self.run_apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot read", result.stderr)
        self.assertFalse(self.calls.exists())
        with self.assertRaises(OSError):
            self.read_policy_count()
        legacy = self.read_legacy_count()
        self.assertEqual(legacy.returncode, 0)
        self.assertIn("Cannot read", legacy.stderr)
        self.assertEqual(legacy.stdout, "")

    def test_live_count_listener_recovers_without_restart_and_keeps_last_good_value(self):
        watcher = self.root / "bin/inotifywait"
        watcher.write_text(
            "#!/usr/bin/env python3\nimport sys\n"
            "for event in sys.stdin:\n"
            "    print(f'{sys.argv[-1]} MOVED_TO bar.conf', flush=True)\n")

        def read_line(stream):
            self.assertTrue(select.select([stream], [], [], 3)[0], "Listener did not respond")
            return stream.readline().decode().strip()

        for initial in ("malformed", "unreadable"):
            with self.subTest(initial=initial):
                self.conf.unlink(missing_ok=True)
                if initial == "unreadable":
                    self.conf.mkdir()
                else:
                    self.conf.write_text("ws_count=invalid\n")
                listener = subprocess.Popen(
                    ["bash", str(ROOT / "src/shared/eww/scripts/workspace-count.sh")],
                    env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, bufsize=0,
                )
                try:
                    self.assertIn("workspace-count:", read_line(listener.stderr))
                    self.assertIsNone(listener.poll())
                    self.assertFalse(select.select([listener.stdout], [], [], 0.05)[0])
                    if initial == "unreadable":
                        self.conf.rmdir()
                    for contents, expected in (("ws_count=7\n", "7"),
                                               ("ws_count=1 0\n", None),
                                               (" ws_count = 3 \r\n", "3")):
                        replacement = self.conf.with_suffix(".tmp")
                        replacement.write_bytes(contents.encode())
                        replacement.replace(self.conf)
                        listener.stdin.write(b"changed\n")
                        if expected is None:
                            self.assertIn("Invalid ws_count", read_line(listener.stderr))
                            self.assertFalse(select.select([listener.stdout], [], [], 0.05)[0])
                        else:
                            self.assertEqual(read_line(listener.stdout), expected)
                        self.assertIsNone(listener.poll())
                finally:
                    listener.stdin.close()
                    listener.wait(timeout=5)
                    listener.stdout.close()
                    listener.stderr.close()
                self.assertEqual(listener.returncode, 0)

    def test_eww_failure_propagates_without_success_log(self):
        result = self.run_apply(FAIL_EWW="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mock: EWW connection failed", result.stderr)
        self.assertIn("saved preferences have not been applied", result.stderr)
        self.assertNotIn("bar-ctl apply: ws_count=", self.log.read_text())
        self.assert_update()

    def test_compositor_variables_do_not_dispatch_or_change_contract(self):
        for variables in ({}, {"NIRI_SOCKET": "test"}, {"HYPRLAND_INSTANCE_SIGNATURE": "test"}):
            self.calls.unlink(missing_ok=True)
            self.assertEqual(self.run_apply(**variables).returncode, 0)
            self.assert_update()

    def test_reload_and_geometry_redraw_are_serialized_without_inherited_locks(self):
        eww = self.root / "bin/eww"
        eww.write_text(
            "#!/usr/bin/env python3\nimport os, sys, time\n"
            "try:\n"
            "    os.fstat(9)\n"
            "except OSError:\n"
            "    pass\n"
            "else:\n"
            "    raise RuntimeError('daemon inherited lifecycle lock')\n"
            "with open(os.environ['CALLS'], 'a') as f:\n"
            "    f.write('begin ' + sys.argv[3] + '\\n')\n"
            "time.sleep(0.08)\n"
            "with open(os.environ['CALLS'], 'a') as f:\n"
            "    f.write('end ' + sys.argv[3] + '\\n')\n")
        processes = [
            subprocess.Popen(["bash", str(self.script), action], env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for action in ("reload", "redraw", "reload")
        ]
        try:
            for process in processes:
                out, err = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, out + err)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
        commands = [line for line in self.calls.read_text().splitlines() if line.startswith("begin ")]
        self.assertIn(commands, [
            ["begin reload", "begin update", "begin close", "begin open", "begin update", "begin reload", "begin update"],
            ["begin close", "begin open", "begin update", "begin reload", "begin update", "begin reload", "begin update"],
            ["begin reload", "begin update", "begin reload", "begin update", "begin close", "begin open", "begin update"],
        ])
        source = self.script.read_text()
        self.assertIn('"$0" refresh "$BAR_NAME"', source)
        self.assertIn('watch "$BAR_NAME" 8>&- 9>&-', source)
        self.assertIn(') 8>&- 9>&- >/dev/null', source)

    def test_open_failure_never_applies_preferences_or_reports_start_success(self):
        self.assertNotIn("pkill", self.script.read_text())
        for action in ("start", "redraw"):
            self.calls.unlink(missing_ok=True)
            result = subprocess.run(
                ["bash", str(self.script), action], env={**self.env, "FAIL_EWW": "1"},
                capture_output=True, text=True, timeout=5,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(f"bar-ctl {action} complete", self.log.read_text())
            calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
            self.assertFalse(any("update" in call for call in calls))

    def test_concurrent_cold_starts_spawn_exactly_one_daemon(self):
        self.script.write_text(self.script.read_text().replace(
            '( sleep 2; "$0" refresh "$BAR_NAME" ) 8>&- 9>&- >/dev/null 2>&1 &',
            ': # Boot geometry timer is outside this cold-start fixture.'))
        pgrep = self.root / "bin/pgrep"
        pgrep.write_text("#!/bin/sh\nexit 0\n")
        pgrep.chmod(0o755)
        eww = self.root / "bin/eww"
        eww.write_text(
            "#!/usr/bin/env python3\nimport os, pathlib, sys, time\n"
            "if sys.argv[3] == 'open':\n"
            "    root = pathlib.Path(os.environ['HOME'])\n"
            "    if (root / 'spawning').exists():\n"
            "        raise RuntimeError('concurrent daemon spawn')\n"
            "    if not (root / 'ready').exists():\n"
            "        (root / 'spawning').touch()\n"
            "        time.sleep(0.15)\n"
            "        (root / 'ready').touch()\n"
            "        (root / 'spawning').unlink()\n"
            "        with open(os.environ['CALLS'], 'a') as out:\n"
            "            out.write('spawn\\n')\n")
        processes = [
            subprocess.Popen(["bash", str(self.script), "start"], env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(2)
        ]
        try:
            for process in processes:
                out, err = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, out + err)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
        self.assertEqual(self.calls.read_text(), "spawn\n")

    def test_ensure_checks_visibility_without_reloading_a_present_bar(self):
        eww = self.root / "bin/eww"
        eww.write_text(
            "#!/usr/bin/env python3\nimport json, os, sys\n"
            "with open(os.environ['CALLS'], 'a') as out:\n"
            "    out.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[3] == 'active-windows': print('bar: bar')\n")
        result = subprocess.run(["bash", str(self.script), "ensure"], env=self.env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([json.loads(line)[2] for line in self.calls.read_text().splitlines()],
                         ["active-windows", "update", "active-windows"])

    def test_geometry_refresh_skips_reloads_and_redraws_when_only_focus_changes(self):
        monitors = self.root / "monitors"
        monitor = dict(name="TEST-1", width=1920, height=1080, scale=1,
                       transform=0, x=0, y=0, focused=True)
        monitors.write_text(json.dumps([monitor]))
        hyprctl = self.root / "bin/hyprctl"
        hyprctl.write_text('#!/bin/sh\ncat "$MONITORS"\n')
        hyprctl.chmod(0o755)
        env = {**self.env, "HYPRLAND_INSTANCE_SIGNATURE": "fixture", "MONITORS": str(monitors)}

        def invoke(action):
            result = subprocess.run(["bash", str(self.script), action], env=env,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)

        invoke("reload")
        initial_calls = self.calls.read_bytes()
        for focused in (False, True, False):
            monitor.update(focused=focused, activeWorkspace={"id": 4})
            monitors.write_text(json.dumps([monitor]))
            invoke("refresh")
            invoke("redraw")
        self.assertEqual(self.calls.read_bytes(), initial_calls)
        monitor["scale"] = 1.25
        monitors.write_text(json.dumps([monitor]))
        invoke("refresh")
        after_resize = self.calls.read_bytes()
        self.assertEqual([json.loads(line)[2] for line in after_resize.splitlines()],
                         ["reload", "update", "close", "open", "update"])
        invoke("refresh")
        self.assertEqual(self.calls.read_bytes(), after_resize)

    def test_failed_geometry_query_is_visible_and_never_closes_the_bar(self):
        hyprctl = self.root / "bin/hyprctl"
        hyprctl.write_text("#!/bin/sh\necho 'broken JSON'\n")
        hyprctl.chmod(0o755)
        result = subprocess.run(
            ["bash", str(self.script), "refresh"],
            env={**self.env, "HYPRLAND_INSTANCE_SIGNATURE": "fixture"},
            capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot read monitor geometry", result.stderr)
        self.assertFalse(self.calls.exists())

    def run_bar(self, action, **env):
        return subprocess.run(["bash", str(self.script), action], env={**self.env, **env},
                              capture_output=True, text=True, timeout=10)

    def eww_calls(self):
        if not self.calls.exists():
            return []
        return [json.loads(line)[2:] for line in self.calls.read_text().splitlines()]

    def recorded_screen(self):
        files = list((self.root / "runtime/smplos").glob("bar-*.screen"))
        if not files:
            return None
        self.assertEqual(len(files), 1, files)
        return files[0].read_text()

    def without_boot_background_jobs(self):
        self.script.write_text(self.script.read_text().replace(
            '( sleep 2; "$0" refresh "$BAR_NAME" ) 8>&- 9>&- >/dev/null 2>&1 &',
            ': # Boot geometry timer is outside this fixture.'))
        pgrep = self.root / "bin/pgrep"
        pgrep.write_text("#!/bin/sh\nexit 0\n")
        pgrep.chmod(0o755)

    def fake_monitors(self, name="HDMI-A-1"):
        monitors = self.root / "monitors"
        monitors.write_text(json.dumps([dict(name=name, width=1920, height=1080, scale=1,
                                             transform=0, x=0, y=0)]))
        hyprctl = self.root / "bin/hyprctl"
        hyprctl.write_text('#!/bin/sh\ncat "$MONITORS"\n')
        hyprctl.chmod(0o755)
        return {"HYPRLAND_INSTANCE_SIGNATURE": "fixture", "MONITORS": str(monitors)}

    def test_start_opens_the_bar_on_the_primary_monitor_and_records_it(self):
        self.without_boot_background_jobs()
        result = self.run_bar("start", PRIMARY="DP-3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.eww_calls()[0], ["open", "bar", "--screen", "DP-3"])
        self.assertEqual(self.recorded_screen(), "DP-3\n")

    def test_start_without_a_primary_keeps_the_default_monitor(self):
        self.without_boot_background_jobs()
        result = self.run_bar("start")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.eww_calls()[0], ["open", "bar"])
        self.assertEqual(self.recorded_screen(), "\n")

    def test_unaddressable_primary_falls_back_and_is_retried_by_the_next_refresh(self):
        self.without_boot_background_jobs()
        env = self.fake_monitors()
        result = self.run_bar("start", PRIMARY="DP-3", FAIL_SCREEN="1", **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.eww_calls()[:2], [["open", "bar", "--screen", "DP-3"], ["open", "bar"]])
        self.assertEqual(self.recorded_screen(), "\n")
        self.calls.unlink()
        result = self.run_bar("refresh", PRIMARY="DP-3", **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call[0] for call in self.eww_calls()], ["close", "open", "update"])
        self.assertEqual(self.eww_calls()[1], ["open", "bar", "--screen", "DP-3"])
        self.assertEqual(self.recorded_screen(), "DP-3\n")

    def test_refresh_moves_the_bar_only_when_the_primary_changes(self):
        env = self.fake_monitors()

        def refresh(primary):
            self.calls.unlink(missing_ok=True)
            result = self.run_bar("refresh", PRIMARY=primary, **env)
            self.assertEqual(result.returncode, 0, result.stderr)
            return self.eww_calls()

        for primary, expected_open in (("HDMI-A-1", ["open", "bar", "--screen", "HDMI-A-1"]),
                                       ("DP-3", ["open", "bar", "--screen", "DP-3"]),
                                       ("", ["open", "bar"])):
            with self.subTest(primary=primary):
                calls = refresh(primary)
                self.assertEqual([call[0] for call in calls], ["close", "open", "update"])
                self.assertEqual(calls[1], expected_open)
                self.assertEqual(self.recorded_screen(), f"{primary}\n")
                self.assertEqual(refresh(primary), [])

    def test_reload_keeps_the_recorded_monitor_because_it_does_not_move_the_bar(self):
        env = self.fake_monitors()
        self.assertEqual(self.run_bar("refresh", PRIMARY="DP-3", **env).returncode, 0)
        self.calls.unlink()
        self.assertEqual(self.run_bar("reload", PRIMARY="HDMI-A-1", **env).returncode, 0)
        self.assertEqual([call[0] for call in self.eww_calls()], ["reload", "update"])
        self.assertEqual(self.recorded_screen(), "DP-3\n")
        self.calls.unlink()
        self.assertEqual(self.run_bar("refresh", PRIMARY="HDMI-A-1", **env).returncode, 0)
        self.assertEqual(self.eww_calls()[1], ["open", "bar", "--screen", "HDMI-A-1"])

    def test_toggle_shows_the_bar_on_the_primary_monitor_and_falls_back_without_it(self):
        self.assertEqual(self.run_bar("toggle", PRIMARY="DP-3").returncode, 0)
        self.assertEqual(self.eww_calls(), [["open", "--toggle", "bar", "--screen", "DP-3"]])
        self.assertEqual(self.recorded_screen(), "DP-3\n")
        self.calls.unlink()
        self.assertEqual(self.run_bar("toggle", PRIMARY="DP-3", FAIL_SCREEN="1").returncode, 0)
        self.assertEqual(self.eww_calls(), [["open", "--toggle", "bar", "--screen", "DP-3"],
                                            ["open", "--toggle", "bar"]])
        self.assertEqual(self.recorded_screen(), "\n")
        self.calls.unlink()
        (self.root / "runtime/smplos").joinpath(
            next((self.root / "runtime/smplos").glob("bar-*.screen")).name).unlink()
        self.assertEqual(self.run_bar("toggle").returncode, 0)
        self.assertEqual(self.eww_calls(), [["open", "--toggle", "bar"]])
        self.assertIsNone(self.recorded_screen())

    def test_failed_open_on_the_primary_never_applies_preferences_or_records_a_monitor(self):
        for action in ("start", "redraw"):
            with self.subTest(action=action):
                self.calls.unlink(missing_ok=True)
                result = self.run_bar(action, PRIMARY="DP-3", FAIL_EWW="1")
                self.assertNotEqual(result.returncode, 0)
                calls = self.eww_calls()
                self.assertNotIn("update", [call[0] for call in calls])
                self.assertEqual([call for call in calls if call[0] == "open"],
                                 [["open", "bar", "--screen", "DP-3"], ["open", "bar"]])
                self.assertIsNone(self.recorded_screen())


if __name__ == "__main__":
    unittest.main()
