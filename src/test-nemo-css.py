#!/usr/bin/env python3
"""Render Nemo's generated GTK styles: xvfb-run -a python3 src/test-nemo-css.py."""

import importlib.util
import itertools
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("nemo_css", ROOT / "regen-nemo-css.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

# CSS gadgets (check indicators, troughs, headers) are not public GtkWidgets.
# Exercise their documented node paths in addition to live widget trees below.
SURFACES = (
    ("button", "label"),
    ("button.suggested-action", "label"),
    ("button.destructive-action", "label"),
    ("toolbar.primary-toolbar button", "image"),
    ("box.toolbar button", "image"),
    ("box.path-bar.linked button", "label"),
    ("box.path-bar.linked button.slider-button", "image"),
    ("treeview.view header button", "label"),
    ("combobox box.linked button.combo", "cellview"),
    ("combobox box.linked button.combo", "arrow"),
    ("headerbar", "label"),
    ("popover.background", "label"),
    ("infobar.warning", "label"),
    ("infobar.error", "label"),
    ("expander", "label"),
    ("expander", "arrow"),
    ("iconview.view", None),
    ("entry", None),
    ("spinbutton", None),
    ("spinbutton button.up", "image"),
    ("checkbutton check", None),
    ("radiobutton radio", None),
    ("switch", None),
    ("switch slider", None),
    ("scale trough", None),
    ("scale trough slider", None),
    ("progressbar trough", None),
    ("progressbar", "text"),
    ("notebook header tab", "label"),
    ("headerbar button", "image"),
    ("searchbar entry", None),
    ("searchbar button", "image"),
    ("popover.background button", "label"),
    ("popover.background modelbutton", "label"),
    ("stackswitcher button", "label"),
    ("textview text", None),
    ("textview text selection", None),
    ("listbox row", "label"),
    ("menu menuitem", "label"),
    ("menu menuitem", "arrow"),
    ("menu menuitem", "accelerator"),
    ("menu menuitem menu menuitem", "label"),
    ("menu.context-menu menuitem", "label"),
    ("menu.context-menu menuitem menu menuitem", "label"),
    ("tooltip.background", "label"),
    ("box.floating-bar", "label"),
)
NORMAL_FILLS = {
    "combobox box.linked button.combo": "bg_light",
    "treeview.view header button": "bg_light",
    "entry": "bg_light",
    "spinbutton": "bg_light",
    "checkbutton check": "bg_light",
    "radiobutton radio": "bg_light",
    "headerbar": "bg_light",
    "popover.background": "background",
    "infobar.warning": "bg_light",
    "infobar.error": "bg_light",
    "iconview.view": "background",
}
STATES = {
    "normal": Gtk.StateFlags.NORMAL,
    "hover": Gtk.StateFlags.PRELIGHT,
    "active": Gtk.StateFlags.ACTIVE,
    "checked": Gtk.StateFlags.CHECKED,
    "selected": Gtk.StateFlags.SELECTED,
    "focus": Gtk.StateFlags.FOCUSED,
    "backdrop": Gtk.StateFlags.BACKDROP,
    "backdrop-checked": Gtk.StateFlags.BACKDROP | Gtk.StateFlags.CHECKED,
    "hover-checked": Gtk.StateFlags.PRELIGHT | Gtk.StateFlags.CHECKED,
    "focus-checked": Gtk.StateFlags.FOCUSED | Gtk.StateFlags.CHECKED,
    "backdrop-hover": Gtk.StateFlags.BACKDROP | Gtk.StateFlags.PRELIGHT,
    "inconsistent": Gtk.StateFlags.INCONSISTENT,
    "disabled": Gtk.StateFlags.INSENSITIVE,
    "disabled-checked": Gtk.StateFlags.INSENSITIVE | Gtk.StateFlags.CHECKED,
}


def rgb(color):
    return tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))


def contrast(first, second):
    def luminance(channels):
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
                  for v in channels]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    low, high = sorted((luminance(first), luminance(second)))
    return (high + 0.05) / (low + 0.05)


def node(parent, name, state, direction):
    path = parent.get_path().copy() if parent else Gtk.WidgetPath()
    index = path.append_type(Gtk.Widget)
    element, *classes = name.split(".")
    path.iter_set_object_name(index, element)
    path.iter_set_state(index, state | direction)
    for css_class in classes:
        path.iter_add_class(index, css_class)
    context = Gtk.StyleContext()
    context.set_path(path)
    if parent:
        context.set_parent(parent)
    context.set_state(state | direction)
    return context


def painted_background(context, background):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 80, 32)
    cr = cairo.Context(surface)
    cr.set_source_rgb(*background)
    cr.paint()
    Gtk.render_background(context, cr, 0, 0, 80, 32)
    surface.flush()
    pixel = bytes(surface.get_data()[16 * surface.get_stride() + 40 * 4:][:4])
    return tuple(v / 255 for v in (pixel[2], pixel[1], pixel[0]))


def check_pair(name, context, text_context, background, failures, minimum=4.5):
    painted = painted_background(context, background)
    color = text_context.get_color(text_context.get_state())
    foreground = tuple(v * color.alpha + b * (1 - color.alpha)
                       for v, b in zip((color.red, color.green, color.blue), painted))
    ratio = contrast(painted, foreground)
    if ratio < minimum:
        failures.append(f"{name}: contrast {ratio:.2f}:1; bg={painted}, fg={foreground}")


def check_native_alpha(colors, failures):
    samples = 0
    alpha = float(generator.app_background_opacity(colors))
    paths = (
        "", "box", "scrolledwindow viewport iconview.view",
        "scrolledwindow treeview.view", "box.sidebar treeview.places-treeview",
        "box.nemo-preview-pane", "headerbar", "scrollbar trough", "decoration",
    )
    for root, state, path in itertools.product(
        ("window.background.nemo-window", "window.background.nemo-quick-preview"),
        (Gtk.StateFlags.NORMAL, Gtk.StateFlags.BACKDROP), paths,
    ):
        context = node(None, root + ".smplos-native-alpha", state, Gtk.StateFlags.DIR_LTR)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 80, 32)
        cr = cairo.Context(surface)
        Gtk.render_background(context, cr, 0, 0, 80, 32)
        for part in path.split():
            context = node(context, part, state, Gtk.StateFlags.DIR_LTR)
            Gtk.render_background(context, cr, 0, 0, 80, 32)
        surface.flush()
        pixel = bytes(surface.get_data()[16 * surface.get_stride() + 40 * 4:][:4])
        # cairo ARGB32 is native-endian, including on big-endian test hosts.
        actual = int.from_bytes(pixel, sys.byteorder) >> 24
        if abs(actual - alpha * 255) > 1:
            failures.append(f"native/{root}/{path}/{state}: alpha {actual}, expected {alpha * 255}")
        samples += 1
    for root in ("window.background.nemo-window", "window.background.nemo-quick-preview"):
        context = node(None, root + ".smplos-native-alpha", Gtk.StateFlags.NORMAL, Gtk.StateFlags.DIR_LTR)
        context = node(context, "label.dim-label", Gtk.StateFlags.SELECTED, Gtk.StateFlags.DIR_LTR)
        color = context.get_color(Gtk.StateFlags.SELECTED | Gtk.StateFlags.DIR_LTR)
        expected = rgb(generator.selection_foreground(colors))
        if color.alpha != 1 or any(abs(a - b) > 1 / 255 for a, b in zip(
                (color.red, color.green, color.blue), expected)):
            failures.append(f"native/{root}/selected dim label: incorrect or translucent foreground")
        samples += 1
    return samples


def descendants(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        children = []
        widget.forall(children.append)
        for child in children:
            yield from descendants(child)


def live_windows():
    window = Gtk.Window()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    window.add(box)
    combo = Gtk.ComboBoxText()
    combo.append_text("Date Modified")
    combo.set_active(0)
    tree = Gtk.TreeView()
    column = Gtk.TreeViewColumn("Name", Gtk.CellRendererText(), text=0)
    column.set_clickable(True)
    tree.append_column(column)
    tree.set_model(Gtk.ListStore(str))
    for widget in (combo, Gtk.Button(label="Browse"), Gtk.Entry(),
                   Gtk.CheckButton(label="Show hidden files"),
                   Gtk.RadioButton(label="List view"), tree):
        box.add(widget)
    dialog = Gtk.Dialog(title="File operation")
    dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
    dialog.add_button("Continue", Gtk.ResponseType.OK)
    windows = [window, dialog]
    # Explicit opt-in avoids silently reading an unrelated checkout.
    preferences = os.environ.get("NEMO_PREFERENCES_UI")
    if preferences:
        gi.require_version("XApp", "1.0")
        from gi.repository import XApp
        XApp.StackSidebar  # Register the builder's custom widget type.
        builder = Gtk.Builder()
        builder.add_from_file(str(preferences))
        windows.append(builder.get_object("file_management_dialog"))
    for item in windows:
        item.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    return windows


def run_variant():
    Gtk.init([])
    Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
    screen = Gdk.Screen.get_default()
    windows = live_windows()
    themes = sorted((ROOT / "shared/themes").glob("*/colors.toml"))
    # Revisit light and dark palettes in the same widgets, without changing GTK_THEME.
    themes += [ROOT / f"shared/themes/{name}/colors.toml"
               for name in ("catppuccin-latte", "matrix", "flexoki-light", "catppuccin")]
    provider = None
    failures = []
    samples = 0
    for palette in themes:
        colors = generator.read_toml_simple(palette)
        css = generator.make_nemo_css(colors)
        assert palette.with_name("nemo.css").read_text() == css, f"Stale CSS: {palette.parent.name}"
        if provider:
            Gtk.StyleContext.remove_provider_for_screen(screen, provider)
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        Gtk.StyleContext.reset_widgets(screen)
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        background = rgb(colors["background"])
        roots = ("window.background.nemo-window", "window.background",
                 "dialog.background", "window.background.nemo-quick-preview")
        for root, direction in itertools.product(roots, (Gtk.StateFlags.DIR_LTR, Gtk.StateFlags.DIR_RTL)):
            for path, text in SURFACES:
                for state_name, state in STATES.items():
                    current = node(None, root, state & Gtk.StateFlags.BACKDROP, direction)
                    painted = background
                    parts = path.split()
                    for index, part in enumerate(parts):
                        node_state = state if index == len(parts) - 1 else state & (
                            Gtk.StateFlags.BACKDROP | Gtk.StateFlags.INSENSITIVE)
                        if part == "menuitem" and parts[index + 1:index + 2] == ["menu"]:
                            node_state = Gtk.StateFlags.PRELIGHT | (state & Gtk.StateFlags.BACKDROP)
                        current = node(current, part, node_state, direction)
                        if index < len(parts) - 1:
                            painted = painted_background(current, painted)
                    text_context = node(current, text, state, direction) if text else current
                    # A switch's trough has no text; its slider is the visible control.
                    minimum = 3.0 if state & Gtk.StateFlags.INSENSITIVE else 4.5
                    name = f"{palette.parent.name}/{root}/{path}/{state_name}/{direction.value_nicks[-1]}"
                    if state == Gtk.StateFlags.NORMAL and path in NORMAL_FILLS:
                        actual = painted_background(current, painted)
                        fill = "bg_lighter" if root == "dialog.background" and path == "headerbar" else NORMAL_FILLS[path]
                        expected = rgb(colors[fill])
                        if any(abs(a - e) > 2 / 255 for a, e in zip(actual, expected)):
                            failures.append(f"{name}: stale background {actual}; expected {expected}")
                    check_pair(name,
                               current, text_context, painted, failures, minimum)
                    samples += 1
        for window in windows:
            for widget in descendants(window):
                if isinstance(widget, (Gtk.Button, Gtk.Entry, Gtk.CellView)):
                    context = widget.get_style_context()
                    child = widget.get_child() if isinstance(widget, Gtk.Button) else None
                    foreground = child.get_style_context() if isinstance(child, Gtk.Label) else context
                    check_pair(f"{palette.parent.name}/live/{context.get_path().to_string()}",
                               context, foreground, background, failures, 3.0 if not widget.is_sensitive() else 4.5)
                    samples += 1
        samples += check_native_alpha(colors, failures)
    for window in windows:
        window.destroy()
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(f"{len(failures)} of {samples} rendered checks failed ({os.environ['GTK_THEME']})")
    print(f"{os.environ['GTK_THEME']}: {samples} rendered checks passed; {len(themes)} live palette loads")


def main():
    if "--variant" in sys.argv:
        run_variant()
        return
    for variant in ("Adwaita", "Adwaita:dark"):
        with tempfile.TemporaryDirectory(prefix="nemo-css-test-") as temporary:
            env = os.environ.copy()
            env.update(GTK_THEME=variant, GDK_BACKEND="x11", GSETTINGS_BACKEND="memory",
                       NO_AT_BRIDGE="1", GIO_USE_VFS="local", GIO_USE_VOLUME_MONITOR="unix",
                       PYTHONDONTWRITEBYTECODE="1", G_DEBUG="fatal-criticals",
                       DBUS_SESSION_BUS_ADDRESS=f"unix:path={temporary}/no-session-bus")
            for key in ("HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
                directory = Path(temporary) / key.lower()
                directory.mkdir(mode=0o700)
                env[key] = str(directory)
            subprocess.run([sys.executable, __file__, "--variant"], env=env, check=True)


if __name__ == "__main__":
    main()
