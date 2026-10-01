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


def native_chrome_window():
    window = Gtk.Window()
    window.set_default_size(500, 200)
    window.get_style_context().add_class("nemo-window")
    window.get_style_context().add_class("smplos-native-alpha")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    window.add(box)
    toolbar = Gtk.Toolbar()
    toolbar.get_style_context().add_class("primary-toolbar")
    toolitem = Gtk.ToolItem()
    tool_box = Gtk.Box()
    toggle = Gtk.ToggleButton()
    toggle.get_style_context().add_class("flat")
    toggle.add(Gtk.Image.new_from_icon_name("view-list-symbolic", Gtk.IconSize.SMALL_TOOLBAR))
    tool_box.add(toggle)
    toolitem.add(tool_box)
    toolbar.insert(toolitem, -1)
    box.add(toolbar)
    pathbar = Gtk.Box()
    pathbar.get_style_context().add_class("path-bar")
    pathbar.get_style_context().add_class("linked")
    breadcrumb = Gtk.ToggleButton(label="Home")
    pathbar.add(breadcrumb)
    box.add(pathbar)
    tree = Gtk.TreeView(model=Gtk.ListStore(str))
    column = Gtk.TreeViewColumn("Name", Gtk.CellRendererText(), text=0)
    column.set_clickable(True)
    tree.append_column(column)
    box.add(tree)
    window.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    controls = (column.get_button(), breadcrumb, toggle)
    for widget in controls:
        assert isinstance(widget, Gtk.Button), widget.__gtype__.name
    return window, controls


def native_split_window():
    window = Gtk.Window()
    window.set_default_size(600, 240)
    window.get_style_context().add_class("nemo-window")
    window.get_style_context().add_class("smplos-native-alpha")
    row = Gtk.Box()
    window.add(row)
    sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    sidebar.get_style_context().add_class("sidebar")
    sidebar.set_size_request(120, -1)
    row.add(sidebar)
    paned = Gtk.Paned()
    row.pack_start(paned, True, True, 0)
    panes = [Gtk.Box(orientation=Gtk.Orientation.VERTICAL) for _ in range(2)]
    paned.pack1(panes[0], True, False)
    paned.pack2(panes[1], True, False)
    views = []
    for parent in (sidebar, *panes):
        scroll = Gtk.ScrolledWindow()
        tree = Gtk.TreeView(model=Gtk.ListStore(str))
        tree.append_column(Gtk.TreeViewColumn("Name", Gtk.CellRendererText(), text=0))
        scroll.add(tree)
        parent.pack_start(scroll, True, True, 0)
        views.append(tree)
    views[0].get_style_context().add_class("places-treeview")
    for pane in panes:
        pane.get_style_context().add_class("nemo-window-pane")
    window.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    return window, panes, views


def check_pane_transitions(window, panes, views, colors, failures):
    alpha = float(generator.app_background_opacity(colors))
    expected = tuple(round(channel * alpha * 255) for channel in rgb(colors["background"]))
    baseline = None
    for cycle in range(12):
        active = cycle % 2
        for index, pane in enumerate(panes):
            context = pane.get_style_context()
            if index == active:
                context.remove_class("nemo-inactive-pane")
            else:
                context.add_class("nemo-inactive-pane")
        views[active + 1].grab_focus()
        for index, view in enumerate(views):
            view.set_state_flags(Gtk.StateFlags.PRELIGHT if index == active + 1 else Gtk.StateFlags.NORMAL, True)
        window.queue_draw()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        window.set_state_flags(Gtk.StateFlags.BACKDROP if cycle >= 8 else Gtk.StateFlags.NORMAL, True)
        window.check_resize()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, window.get_allocated_width(), window.get_allocated_height())
        window.draw(cairo.Context(surface))
        surface.flush()
        data = bytes(surface.get_data())
        samples = []
        for view in views:
            x, y = view.translate_coordinates(window, view.get_allocated_width() // 2,
                                              view.get_allocated_height() // 2)
            pixel = int.from_bytes(data[y * surface.get_stride() + x * 4:][:4], sys.byteorder)
            actual = ((pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255, pixel >> 24)
            samples.append(actual)
            target = (*expected, round(alpha * 255))
            if any(abs(a - b) > 1 for a, b in zip(actual, target)):
                failures.append(f"pane transition {cycle}/{view.get_style_context().get_path().to_string()}: {actual}, expected {target}")
        if baseline is not None and samples != baseline:
            failures.append(f"pane transition {cycle}: empty backgrounds changed from {baseline} to {samples}")
        baseline = samples
    window.set_state_flags(Gtk.StateFlags.NORMAL, True)
    return 36


def check_native_chrome(window, controls, colors, failures, theme):
    samples = 0
    alpha = float(generator.app_background_opacity(colors))
    proofs = []
    for role, widget in zip(("Column header", "Breadcrumb", "View toggle"), controls):
        context = widget.get_style_context()
        state_faces = {}
        for name, state in STATES.items():
            context.save()
            context.set_state(state | Gtk.StateFlags.DIR_LTR)
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 80, 32)
            cr = cairo.Context(surface)
            Gtk.render_background(window.get_style_context(), cr, 0, 0, 80, 32)
            Gtk.render_background(context, cr, 0, 0, 80, 32)
            Gtk.render_frame(context, cr, 0, 0, 80, 32)
            if state & Gtk.StateFlags.FOCUSED:
                Gtk.render_focus(context, cr, 0, 0, 80, 32)
            surface.flush()
            state_faces[name] = bytes(surface.get_data())
            pixel = bytes(surface.get_data()[16 * surface.get_stride() + 40 * 4:][:4])
            actual = int.from_bytes(pixel, sys.byteorder) >> 24
            path = context.get_path().to_string()
            if abs(actual - alpha * 255) > 1:
                failures.append(f"native chrome/{path}/{name}: alpha {actual}, expected {alpha * 255}")
            if context.get_color(context.get_state()).alpha != 1:
                failures.append(f"native chrome/{path}/{name}: translucent foreground")
            context.restore()
            original = widget.get_state_flags()
            widget.set_state_flags(state, True)
            window.check_resize()
            width, height = widget.get_allocated_width(), widget.get_allocated_height()
            control = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            widget.draw(cairo.Context(control))
            control.flush()
            data = bytes(control.get_data())
            face = int.from_bytes(data[4 * control.get_stride() + 4 * 4:][:4], sys.byteorder) >> 24
            if face != 0:
                failures.append(f"native chrome/{path}/{name}: control repaints its face (alpha {face})")
            painted = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            painter = cairo.Context(painted)
            Gtk.render_background(window.get_style_context(), painter, 0, 0, width, height)
            painter.set_source_surface(control)
            painter.paint()
            painted.flush()
            glyph_alpha = max(
                int.from_bytes(data[y * control.get_stride() + x * 4:][:4], sys.byteorder) >> 24
                for y in range(5, height - 5) for x in range(5, width - 5)
            )
            if glyph_alpha != 255:
                failures.append(f"native chrome/{path}/{name}: glyph interior alpha {glyph_alpha}, expected 255")
            if name in ("normal", "hover", "checked", "focus", "backdrop-checked"):
                proofs.append((f"{role}: {name} (background {alpha}, glyph A255)", painted))
            widget.set_state_flags(original, True)
            samples += 1
        for state in ("hover", "checked", "focus"):
            if state_faces[state] == state_faces["normal"]:
                failures.append(f"native chrome/{context.get_path().to_string()}: no visible {state} indicator")
    proof_dir = os.environ.get("NEMO_CHROME_PROOFS_DIR")
    if proof_dir and theme in ("catppuccin", "catppuccin-latte", "tokyo-night", "matrix"):
        width = max(image.get_width() for _, image in proofs) + 20
        height = sum(image.get_height() + 30 for _, image in proofs)
        proof = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        cr = cairo.Context(proof)
        cr.set_source_rgb(0.85, 0.85, 0.85)
        cr.paint()
        y = 0
        for title, image in proofs:
            cr.set_source_rgb(0.1, 0.1, 0.1)
            cr.set_font_size(12)
            cr.move_to(10, y + 16)
            cr.show_text(title)
            y += 22
            for row in range(0, image.get_height(), 8):
                for col in range(0, image.get_width(), 8):
                    value = 0.4 if (row // 8 + col // 8) % 2 else 0.65
                    cr.set_source_rgb(value, value, value)
                    cr.rectangle(col + 10, row + y, min(8, image.get_width() - col),
                                 min(8, image.get_height() - row))
                    cr.fill()
            cr.set_source_surface(image, 10, y)
            cr.paint()
            y += image.get_height() + 8
        destination = Path(proof_dir)
        destination.mkdir(parents=True, exist_ok=True)
        proof.write_to_png(str(destination / f"{theme}-{os.environ['GTK_THEME'].replace(':', '-')}.png"))
    return samples


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
    chrome_window, chrome_controls = native_chrome_window()
    split_window, panes, pane_views = native_split_window()
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
        samples += check_native_chrome(chrome_window, chrome_controls, colors, failures, palette.parent.name)
        samples += check_pane_transitions(split_window, panes, pane_views, colors, failures)
    for window in windows:
        window.destroy()
    chrome_window.destroy()
    split_window.destroy()
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
