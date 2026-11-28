"""Focused contracts for the opt-in native smpl-bar integration."""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BAR_CTL = ROOT / "src/shared/bin/bar-ctl"
POPUP = ROOT / "src/shared/bin/popup-toggle"
SESSION_START = ROOT / "src/shared/bin/bar-session-start"
CONTROL_RUN = ROOT / "src/shared/bin/control-surface-run"
CLICK_CHECK = ROOT / "src/shared/bin/smpl-bar-click-check"


class SmplBarIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".smpl-bar-test-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.home = self.root / "home"
        (self.home / ".config/smplos").mkdir(parents=True)
        self.calls = self.root / "calls.jsonl"
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "CALLS": str(self.calls),
            "XDG_RUNTIME_DIR": str(self.root / "runtime"),
            "XDG_STATE_HOME": str(self.root / "state"),
        }
        self.tool("eww", "#!/bin/sh\nprintf 'eww %s\\n' \"$*\" >> \"$CALLS\"\nexit 0\n")
        self.tool(
            "smpl-bar",
            """#!/usr/bin/env python3
import json, os, pathlib, sys, time
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as out:
    out.write(json.dumps(["smpl-bar", *args]) + "\\n")
ready = pathlib.Path(os.environ["READY"])
if args == ["--resident"]:
    ready.touch()
    sys.exit(0)
if args == ["status"] and not ready.exists():
    sys.exit(1)
if args == ["status"]:
    kind = "niri" if os.environ.get("NIRI_SOCKET") else (
        "hyprland" if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") else "x11"
    )
    print(json.dumps({
        "resident": True,
        "compositor": kind,
        "config": {
            "mode": os.environ.get("MOCK_PANEL_MODE", "pinned"),
            "edge": os.environ.get("MOCK_PANEL_EDGE", "bottom"),
            "margin": 2,
        },
        "panel": {
            "active": os.environ.get("MOCK_PANEL_ACTIVE", "1") == "1",
            "transport": "wayland-layer-shell",
        },
    }))
""",
        )
        self.tool(
            "toggle-start-menu",
            "#!/bin/sh\nprintf 'start-menu:%s\\n' \"$*\" >> \"$CALLS\"\n",
        )
        self.ready = self.root / "ready"
        self.env["READY"] = str(self.ready)

    def tool(self, name, source):
        path = self.bin / name
        path.write_text(source)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def invoke(self, script, *arguments, **updates):
        return subprocess.run(
            ["bash", str(script), *arguments],
            env={**self.env, **updates},
            capture_output=True,
            text=True,
            timeout=10,
        )

    def recorded(self):
        if not self.calls.exists():
            return []
        rows = []
        for line in self.calls.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append(line)
        return rows

    def test_backend_is_mandatory_native(self):
        self.assertEqual(self.invoke(BAR_CTL, "backend").stdout, "smpl-bar\n")
        conf = self.home / ".config/smplos/bar.conf"
        conf.write_text("backend=eww\nws_count=7\n")
        self.assertEqual(self.invoke(BAR_CTL, "backend").stdout, "smpl-bar\n")
        self.assertEqual(self.invoke(BAR_CTL, "backend", BAR_BACKEND="eww").stdout, "smpl-bar\n")

    def test_native_preflight_rejects_duplicate_taskbar_values(self):
        conf = self.home / ".config/smplos/bar.conf"
        conf.write_text("bar_edge=top\n bar_edge=bottom\n")
        result = self.invoke(BAR_CTL, "apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate bar_edge", result.stderr)

    def test_native_commands_use_ipc_without_touching_eww(self):
        self.ready.touch()
        for action, expected in (
            ("toggle", ["smpl-bar", "toggle"]),
            ("stop", ["smpl-bar", "stop"]),
            ("reload", ["smpl-bar", "apply"]),
            ("refresh", ["smpl-bar", "apply"]),
            ("watch", None),
            ("apply", ["smpl-bar", "apply"]),
            ("identify", ["smpl-bar", "identify"]),
            ("close-popups", ["smpl-bar", "close-popups"]),
            ("telemetry-sample", ["smpl-bar", "telemetry-sample"]),
        ):
            with self.subTest(action=action):
                self.calls.unlink(missing_ok=True)
                result = self.invoke(BAR_CTL, action, BAR_BACKEND="smpl-bar")
                self.assertEqual(result.returncode, 0, result.stderr)
                native = [row for row in self.recorded() if isinstance(row, list)]
                if expected is None:
                    self.assertEqual(native, [])
                else:
                    self.assertIn(expected, native)
                self.assertFalse(any(str(row).startswith("eww ") for row in self.recorded()))

    def test_native_apply_preserves_managed_workspace_range(self):
        conf = self.home / ".config/smplos/bar.conf"
        conf.write_text("backend=smpl-bar\nws_count=11\nws_spacing=1\n")
        result = self.invoke(BAR_CTL, "apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid ws_count", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_native_apply_validates_panel_contract_values(self):
        conf = self.home / ".config/smplos/bar.conf"
        self.ready.touch()
        conf.write_text("bar_edge=top\nbar_mode=floating\nbar_margin=24\n")
        result = self.invoke(BAR_CTL, "apply", BAR_BACKEND="smpl-bar")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["smpl-bar", "apply"], self.recorded())
        self.calls.unlink()
        for contents, message in (
            ("bar_edge=side\n", "Invalid bar_edge"),
            ("bar_mode=overlay\n", "Invalid bar_mode"),
            ("bar_margin=25\n", "Invalid bar_margin"),
            ("bar_edge=top\nbar_edge=bottom\n", "Duplicate bar_edge"),
        ):
            with self.subTest(contents=contents):
                conf.write_text(contents)
                result = self.invoke(BAR_CTL, "apply", BAR_BACKEND="smpl-bar")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse(self.calls.exists())

    def test_native_start_owns_resident_lifecycle_and_keypad_payloads(self):
        result = self.invoke(BAR_CTL, "start", BAR_BACKEND="smpl-bar")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.recorded()
        self.assertIn(["smpl-bar", "--resident"], rows)
        self.assertIn(["smpl-bar", "show"], rows)
        for arguments, expected in (
            (("set-keypad-present", "yes"), ["smpl-bar", "set-keypad-present", "yes"]),
            (("keypad-sheet", '{"visible":true,"options":{"clickThrough":true}}'),
             ["smpl-bar", "keypad-sheet",
              '{"visible":true,"options":{"clickThrough":true}}']),
        ):
            self.calls.unlink(missing_ok=True)
            result = self.invoke(BAR_CTL, *arguments, BAR_BACKEND="smpl-bar")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, self.recorded())

    def test_native_start_timeout_terminates_the_unready_resident(self):
        resident_pid = self.root / "resident.pid"
        self.tool(
            "smpl-bar",
            """#!/bin/sh
if [ "$1" = "--resident" ]; then
    echo $$ > "$RESIDENT_PID"
    sleep 30
fi
exit 1
""",
        )
        result = self.invoke(
            BAR_CTL, "start", BAR_BACKEND="smpl-bar", RESIDENT_PID=str(resident_pid)
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not become ready", result.stderr)
        pid = int(resident_pid.read_text())
        self.assertFalse(Path(f"/proc/{pid}").exists())

    def test_native_bar_starts_on_niri_with_layer_reservation(self):
        result = self.invoke(
            BAR_CTL, "start", BAR_BACKEND="smpl-bar", NIRI_SOCKET="/tmp/niri.sock"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["smpl-bar", "--resident"], self.recorded())
        self.assertIn(["smpl-bar", "show"], self.recorded())

    def test_native_bar_anchors_visible_hyprland_window_to_reservation(self):
        self.tool(
            "hyprctl",
            """#!/bin/sh
case "$1" in
  clients)
    printf '%s\\n' '[{"class":"smpl-bar","title":"smpl-bar","address":"0xabc","size":[1600,24],"floating":false,"pinned":false},{"class":"github","address":"0xdef","focusHistoryID":1,"mapped":true,"hidden":false}]'
    ;;
  layers)
    printf '%s\\n' '{"foo":[{"namespace":"smpl-bar-reservation","x":0,"y":1406,"w":2560,"h":32}]}'
    ;;
  activewindow)
    printf '%s\\n' '{"class":"smpl-bar"}'
    ;;
  dispatch)
    printf 'dispatch %s\\n' "$2" >> "$CALLS"
    ;;
esac
""",
        )
        result = self.invoke(
            BAR_CTL,
            "start",
            BAR_BACKEND="smpl-bar",
            HYPRLAND_INSTANCE_SIGNATURE="test",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.recorded()
        self.assertIn(
            'dispatch hl.dsp.window.float({ window = "address:0xabc", action = "toggle" })',
            calls,
        )
        self.assertIn(
            'dispatch hl.dsp.window.resize({ window = "address:0xabc", x = 2556, y = 32, relative = false })',
            calls,
        )
        self.assertIn(
            'dispatch hl.dsp.window.pin({ window = "address:0xabc" })',
            calls,
        )
        self.assertIn(
            'dispatch hl.dsp.window.move({ window = "address:0xabc", x = 2, y = 1406 })',
            calls,
        )
        self.assertIn(
            'dispatch hl.dsp.focus({ window = "address:0xdef" })',
            calls,
        )
        self.assertGreaterEqual(
            calls.count(
                'dispatch hl.dsp.window.move({ window = "address:0xabc", x = 2, y = 1406 })'
            ),
            1,
        )

    def test_native_apply_reanchors_after_async_theme_remap(self):
        self.tool(
            "hyprctl",
            """#!/bin/sh
case "$1" in
  clients)
    printf '%s\\n' '[{"class":"smpl-bar","title":"smpl-bar","address":"0xabc","size":[1600,24],"floating":true,"pinned":true}]'
    ;;
  layers)
    printf '%s\\n' '{"foo":[{"namespace":"smpl-bar-reservation","x":0,"y":1406,"w":2560,"h":32}]}'
    ;;
  activewindow)
    printf '%s\\n' '{"class":"app"}'
    ;;
  dispatch)
    printf 'dispatch %s\\n' "$2" >> "$CALLS"
    ;;
esac
""",
        )
        self.ready.touch()
        result = self.invoke(
            BAR_CTL,
            "apply",
            BAR_BACKEND="smpl-bar",
            HYPRLAND_INSTANCE_SIGNATURE="test",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.recorded()
        self.assertEqual(
            calls.count(
                'dispatch hl.dsp.window.move({ window = "address:0xabc", x = 2, y = 1406 })'
            ),
            2,
        )

    def test_native_bar_anchors_vertical_reservation_without_reorienting_margins(self):
        self.tool(
            "hyprctl",
            """#!/bin/sh
case "$1" in
  clients)
    printf '%s\\n' '[{"class":"smpl-bar","title":"smpl-bar:panel-left-pinned","address":"0xabc","floating":true,"pinned":true}]'
    ;;
  layers)
    printf '%s\\n' '{"foo":[{"namespace":"smpl-bar-reservation","x":0,"y":0,"w":32,"h":1440}]}'
    ;;
  activewindow)
    printf '%s\\n' '{"class":"app"}'
    ;;
  dispatch)
    printf 'dispatch %s\\n' "$2" >> "$CALLS"
    ;;
esac
""",
        )
        self.ready.touch()
        result = self.invoke(
            BAR_CTL,
            "start",
            BAR_BACKEND="smpl-bar",
            HYPRLAND_INSTANCE_SIGNATURE="test",
            MOCK_PANEL_EDGE="left",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            'dispatch hl.dsp.window.resize({ window = "address:0xabc", x = 32, y = 1436, relative = false })',
            self.recorded(),
        )
        self.assertIn(
            'dispatch hl.dsp.window.move({ window = "address:0xabc", x = 0, y = 2 })',
            self.recorded(),
        )

    def test_native_popup_click_outside_closes_on_bar_or_desktop_but_not_inside_popup(self):
        self.tool(
            "bar-ctl",
            "#!/bin/sh\nprintf '[\"bar-ctl\",\"%s\"]\\n' \"$1\" >> \"$CALLS\"\n",
        )
        self.tool(
            "hyprctl",
            """#!/bin/sh
case "$1" in
  clients)
    printf '%s\\n' '[{"class":"smpl-bar","title":"smpl-bar","at":[0,1400],"size":[1600,40]},{"class":"smpl-bar","title":"smpl-bar:quick-settings","at":[1200,900],"size":[430,340]}]'
    ;;
  cursorpos)
    printf '{"x":%s,"y":%s}\\n' "${CX:-100}" "${CY:-500}"
    ;;
esac
""",
        )
        result = self.invoke(CLICK_CHECK)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.recorded()
        self.assertIn(["bar-ctl", "close-popups"], rows)
        for x, y, should_close in ((1250, 950, False), (100, 1420, True)):
            with self.subTest(x=x, y=y):
                self.calls.unlink(missing_ok=True)
                result = self.invoke(CLICK_CHECK, CX=str(x), CY=str(y))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    ["bar-ctl", "close-popups"] in self.recorded(),
                    should_close,
                )

    def test_popup_compatibility_uses_verified_native_commands(self):
        self.ready.touch()
        self.tool("toggle-notif-center", "#!/bin/sh\nprintf 'notification\\n' >> \"$CALLS\"\n")
        self.tool("toggle-calendar", "#!/bin/sh\nprintf 'calendar\\n' >> \"$CALLS\"\n")
        common = dict(BAR_BACKEND="smpl-bar", BAR_CTL=str(BAR_CTL))
        for window, expected in (
            ("start-menu", "start-menu:"),
            ("quick-settings", ["smpl-bar", "popup", "quick-settings"]),
            ("usb-popup", ["smpl-bar", "popup", "usb"]),
            ("workspace-overview", ["smpl-bar", "popup", "workspace-overview"]),
            ("notification-hub", "notification"),
            ("calendar-popup", "calendar"),
        ):
            with self.subTest(window=window):
                self.calls.unlink(missing_ok=True)
                result = self.invoke(POPUP, window, **common)
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = self.recorded()
                self.assertIn(expected, rows)
                if isinstance(expected, list):
                    self.assertIn(["smpl-bar", "close-popups"], rows)
                else:
                    self.assertIn(["smpl-bar", "close-popups"], rows)
                if window != "start-menu":
                    self.assertIn("start-menu:--hide", rows)
        result = self.invoke(POPUP, "--close", **common)
        self.assertEqual(result.returncode, 0)
        self.assertIn(["smpl-bar", "close-popups"], self.recorded())
        self.calls.unlink(missing_ok=True)
        self.assertEqual(self.invoke(POPUP, "quick-settings", **common).returncode, 0)
        self.assertEqual(self.invoke(POPUP, "quick-settings", **common).returncode, 0)
        rows = self.recorded()
        self.assertIn(["smpl-bar", "popup", "quick-settings"], rows)
        self.assertIn(["smpl-bar", "close-popups"], rows)

    def test_session_start_requires_the_native_bar_without_fallback(self):
        control = self.tool("bar-ctl-mock", """#!/bin/sh
printf '%s|%s\n' "$1" "$FAIL_NATIVE" >> "$CALLS"
[ "$FAIL_NATIVE" != 1 ]
""")
        result = self.invoke(SESSION_START, BAR_CTL=str(control))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ensure|", self.calls.read_text())
        self.calls.unlink()
        result = self.invoke(SESSION_START, BAR_CTL=str(control), FAIL_NATIVE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.calls.read_text().endswith("ensure|1\n"))
        self.assertFalse(any("remove" in str(row) or "uninstall" in str(row)
                             for row in self.recorded()))

    def test_native_resident_requires_a_pinned_wayland_reservation(self):
        self.ready.touch()
        result = self.invoke(
            BAR_CTL, "start", BAR_BACKEND="smpl-bar",
            NIRI_SOCKET="/tmp/niri.sock", MOCK_PANEL_ACTIVE="0",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("panel transport is unavailable", result.stderr)
        self.assertIn(["smpl-bar", "show"], self.recorded())
        self.assertIn(["smpl-bar", "hide"], self.recorded())

    def test_floating_wayland_panel_does_not_require_exclusive_reservation(self):
        result = self.invoke(
            BAR_CTL, "start", BAR_BACKEND="smpl-bar",
            HYPRLAND_INSTANCE_SIGNATURE="fixture", WAYLAND_DISPLAY="wayland-1",
            MOCK_PANEL_MODE="floating", MOCK_PANEL_ACTIVE="0",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["smpl-bar", "show"], self.recorded())

    def test_control_surface_uses_only_native_bar_sink(self):
        daemon = self.tool("control-surfaced", """#!/bin/sh
printf 'daemon:%s\n' "$*" >> "$CALLS"
if [ "$1" = cheatsheet ]; then
  printf '%s\n' '{"visible":true,"options":{"clickThrough":true}}'
else
  sleep 0.2
fi
""")
        control = self.tool("bar-ctl-mock", """#!/bin/sh
if [ "$1" = keypad-sheet ] && [ "$2" = - ]; then
  payload=$(cat); printf 'sheet:%s\n' "$payload" >> "$CALLS"
fi
""")
        result = self.invoke(CONTROL_RUN, BAR_CTL=str(control), SMPLOS_CONTROL_SURFACED=str(daemon))
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.calls.read_text()
        self.assertIn("daemon:run --quiet", text)
        self.assertNotIn("--eww-", text)
        self.assertIn('"clickThrough":true', text)

    def test_compositor_and_session_rules_cover_native_window_contract(self):
        paths = [
            ROOT / "src/compositors/hyprland/hypr/windows.conf",
            ROOT / "src/compositors/hyprland/hypr/windows.lua",
        ]
        for path in paths:
            text = path.read_text()
            self.assertIn("smpl-bar", text)
            self.assertIn("quick-settings", text)
            self.assertIn("workspace-overview", text)
            self.assertIn("keypad-cheatsheet", text)
            self.assertIn("tray-menu", text)
            self.assertIn("panel-(top|bottom|left|right)-(pinned|floating)", text)
            self.assertIn("smpl-bar-preview", text)
            self.assertIn("smpl-bar-reservation", text)
            self.assertIn("stay_focused", text)
        niri = (ROOT / "src/compositors/niri/window-rules.kdl").read_text()
        self.assertIn('app-id="^smpl-bar$"', niri)
        self.assertIn("panel-(top|bottom|left|right)-(pinned|floating)", niri)
        self.assertIn("tray-menu", niri)
        self.assertIn("identify(:.*)?", niri)
        self.assertIn("open-focused false", niri)
        self.assertIn(
            'namespace="smpl-bar-reservation"',
            (ROOT / "src/compositors/niri/layer-rules.kdl").read_text(),
        )
        self.assertIn("no_focus", "\n".join(
            path.read_text() for path in paths
        ))
        for path in (
            ROOT / "src/compositors/hyprland/hypr/autostart.conf",
            ROOT / "src/compositors/hyprland/hypr/autostart.lua",
            ROOT / "src/compositors/niri/config.kdl",
        ):
            text = path.read_text()
            self.assertIn("bar-session-start", text)
            self.assertNotIn("bar-ctl start'", text)
        self.assertNotIn("backend=", (ROOT / "src/shared/configs/smplos/bar.conf").read_text())

    def test_keypad_unit_replaces_only_the_selected_bar_sink(self):
        unit = (ROOT / "src/shared/configs/systemd/user/control-surface.service").read_text()
        self.assertIn("ExecStart=/usr/local/bin/control-surface-run", unit)
        self.assertIn("ExecStartPost=-/usr/local/bin/bar-ctl set-keypad-present yes", unit)
        self.assertIn("ExecStopPost=-/usr/local/bin/bar-ctl set-keypad-present no", unit)
        self.assertNotIn("ExecStart=/usr/bin/control-surfaced", unit)
        migration = (ROOT / "migrations/20261121-000000-native-bar-keypad-sink.sh").read_text()
        self.assertIn("smplos_keypad_sync_units", migration)

    def test_release_contract_requires_smpl_bar(self):
        bundle = self.root / "bundle"
        bundle.mkdir()
        library = ROOT / "src/shared/lib/smplos-app-bundle.sh"
        names = subprocess.run(["bash", "-c", f'source "{library}"; printf "%s\n" "${{SMPLOS_APP_BINS[@]}}"'], capture_output=True, text=True, check=True).stdout.splitlines()
        self.assertIn("smpl-bar", names)
        for name in names:
            (bundle / name).write_bytes(b"\x7fELFfixture")
        (bundle / "smpl-calendar-alertd.service").write_text("ExecStart=/usr/local/bin/smpl-calendar-alertd --foreground\nWantedBy=default.target\n")
        check = ["bash", "-c", 'source "$1"; smplos_app_bundle_valid "$2"', "_", str(library), str(bundle)]
        self.assertEqual(subprocess.run(check, capture_output=True, text=True).returncode, 0)
        (bundle / "smpl-bar").unlink()
        self.assertNotEqual(subprocess.run(check, capture_output=True, text=True).returncode, 0)
        for path in (ROOT / "src/build-iso.sh", ROOT / "src/builder/build.sh", ROOT / "src/shared/bin/smplos-update-apps"):
            self.assertNotIn("SMPLOS_APP_OPTIONAL_BINS", path.read_text())
        self.assertNotIn("optional", (ROOT / "src/builder/build.sh").read_text())


if __name__ == "__main__":
    unittest.main()
