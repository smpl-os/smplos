#!/usr/bin/env python3
"""Exercise GTK defaults and live libadwaita color changes in a private profile/bus."""

import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent
HELPER = ROOT / "shared/lib/smplos-gtk.py"
SCHEMA = "org.gnome.desktop.interface"


def run(*args):
    result = subprocess.run(args, check=True, text=True, capture_output=True, timeout=20)
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return result.stdout.strip()


def probe(version):
    import gi
    gi.require_version("Gtk", version)
    if version == "3.0":
        from gi.repository import Gtk
        Gtk.init([])
        settings = Gtk.Settings.get_default()
        icons = Gtk.IconTheme.get_default()
        assert icons.has_icon("image-missing")
        print(f"GTK3 dark preference: {settings.props.gtk_application_prefer_dark_theme}")
        return
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Gtk
    Adw.init()
    manager = Adw.StyleManager.get_default()
    icons = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    assert icons.has_icon("image-missing")
    assert manager.get_system_supports_color_schemes(), "desktop color-scheme preference is unavailable"
    print("ready", flush=True)
    for mode in sys.stdin:
        expected = mode.strip() == "dark"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            if manager.get_dark() == expected:
                break
            time.sleep(0.01)
        assert manager.get_dark() == expected, f"libadwaita did not apply {mode.strip()}"
        print(mode.strip(), flush=True)


def worker():
    local_index = Path.home() / ".local/share/icons/hicolor/index.theme"
    local_index.parent.mkdir(parents=True)
    original = "[Icon Theme]\nName=Hicolor\nDirectories=48x48/apps\n\n[48x48/apps]\nSize=48\nType=Fixed\n"
    local_index.write_text(original)
    config = Path.home() / ".config"
    portal = config / "xdg-desktop-portal/portals.conf"
    portal.parent.mkdir(parents=True)
    portal.write_text("[preferred]\ndefault=gtk\n")
    run("gsettings", "set", SCHEMA, "icon-theme", "Yaru-yellow")
    print(run(sys.executable, str(HELPER), "--dark"))
    with tempfile.TemporaryFile(mode="w+") as errors:
        process = subprocess.Popen(
            [sys.executable, __file__, "--probe", "4.0"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=errors, text=True,
        )
        try:
            assert select.select([process.stdout], [], [], 20)[0], "GTK4 startup timed out"
            assert process.stdout.readline().strip() == "ready", "GTK4 failed to initialize"
            for mode in ("dark", "light", "dark"):
                print(run(sys.executable, str(HELPER), f"--{mode}"))
                process.stdin.write(mode + "\n")
                process.stdin.flush()
                assert select.select([process.stdout], [], [], 10)[0], "GTK4 change timed out"
                assert process.stdout.readline().strip() == mode, "GTK4 color-scheme mismatch"
                print(f"GTK4/libadwaita live appearance: {mode}")
                gtk3 = run(sys.executable, __file__, "--probe", "3.0")
                assert gtk3.endswith(str(mode == "dark")), gtk3
                print(gtk3)
            process.stdin.close()
            assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            errors.seek(0)
            diagnostics = errors.read()
            if diagnostics:
                print(diagnostics, file=sys.stderr)
            assert "Unknown key" not in diagnostics
    assert run("gsettings", "get", SCHEMA, "icon-theme") == "'Adwaita'"
    assert local_index.read_text() == original, "personal icon index was changed"
    print("GTK defaults: installed icons, preserved local index, live dark/light/dark passed.")


def isolated():
    with tempfile.TemporaryDirectory(prefix="smplos-gtk-defaults-") as home:
        runtime = Path(home) / "runtime"
        runtime.mkdir(mode=0o700)
        env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=f"{home}/.config",
                   XDG_DATA_HOME=f"{home}/.local/share", XDG_CACHE_HOME=f"{home}/.cache",
                   XDG_STATE_HOME=f"{home}/.local/state", XDG_RUNTIME_DIR=str(runtime),
                   XDG_DATA_DIRS="/usr/local/share:/usr/share",
                   XDG_CURRENT_DESKTOP="smplos-gtk-test", XDG_SESSION_DESKTOP="smplos-gtk-test",
                   GSETTINGS_BACKEND="dconf", GIO_USE_VFS="local", GTK_THEME="")
        wayland = os.environ.get("WAYLAND_DISPLAY", "")
        if wayland and not Path(wayland).is_absolute():
            env["WAYLAND_DISPLAY"] = str(Path(os.environ["XDG_RUNTIME_DIR"]) / wayland)
        for key in ("DBUS_SESSION_BUS_ADDRESS", "DBUS_STARTER_ADDRESS",
                    "DBUS_STARTER_BUS_TYPE", "HYPRLAND_INSTANCE_SIGNATURE"):
            env.pop(key, None)
        subprocess.run(["dbus-run-session", "--", sys.executable, __file__, "--worker"],
                       env=env, check=True, timeout=100)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--probe"]:
        probe(sys.argv[2])
    elif sys.argv[1:] == ["--worker"]:
        worker()
    else:
        isolated()
