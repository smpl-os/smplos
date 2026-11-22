# DWM / X11 Port -- Future Plan

> Status: **Planned** -- Hyprland (Wayland) ships first. This doc tracks
> everything needed to bring DWM (X11) to feature parity.

smplOS is designed cross-compositor from day one. Most shared code already
has runtime detection (`$WAYLAND_DISPLAY`). This document catalogs every gap,
assigns effort, and defines a rough execution order.

---

## Table of Contents

- [Architecture Recap](#architecture-recap)
- [Effort Legend](#effort-legend)
- [1. DWM Build from Source](#1-dwm-build-from-source)
- [2. bindings.conf to config.def.h](#2-bindingsconf-to-configdefh)
- [3. Window Rules](#3-window-rules)
- [4. EWW Listener Scripts](#4-eww-listener-scripts)
- [5. Shared Bin Scripts](#5-shared-bin-scripts)
- [6. Terminal (st X11)](#6-terminal-st-x11)
- [7. Theme System](#7-theme-system)
- [8. Lock Screen & Idle](#8-lock-screen--idle)
- [9. Autostart & Environment](#9-autostart--environment)
- [10. Input Config](#10-input-config)
- [11. Packages](#11-packages)
- [12. Slint Apps (kb-center, notif-center, disp-center, webapp-center)](#12-slint-apps-kb-center-notif-center-disp-center-webapp-center)
- [12b. Messenger System](#12b-messenger-system)
- [13. Installer](#13-installer)
- [14. Build System](#14-build-system)
- [15. Already Working](#15-already-working)
- [Execution Order](#execution-order)

---

## Architecture Recap

```
src/shared/              <-- works on ALL compositors (bin/, eww/, themes/, configs/)
src/compositors/hyprland/<-- Hyprland-only (hypr/, st-wl, packages.txt)
src/compositors/dwm/     <-- DWM-only (TO BE CREATED)
```

The compositor layer should be as thin as possible. Everything that can live in
`src/shared/` already does.

---

## Effort Legend

| Tag | Meaning |
|-----|---------|
| **Works** | No changes needed -- already cross-platform |
| **Minor** | Runtime detection tweak or trivial config swap |
| **Moderate** | Needs an X11-specific implementation or alternative tool |
| **Major** | Significant new code, build tooling, or architectural work |

---

## 1. DWM Build from Source

**Effort: Major**

DWM is compiled from source with patches baked in. We need:

```
src/compositors/dwm/
  dwm/
    config.def.h       <-- generated from bindings.conf + window rules
    config.mk
    dwm.c
    patches/            <-- selected patches as .diff files
  packages.txt          <-- X11-specific packages
  autostart.sh          <-- replaces Hyprland exec-once
```

### Required DWM Patches

| Patch | Purpose | Hyprland Equivalent |
|-------|---------|---------------------|
| `dwm-autostart` | Run commands on startup | `exec-once` in autostart.conf |
| `dwm-fakefullscreen` | Fullscreen within tile | `fullscreenstate` dispatcher |
| `dwm-pertag` | Per-tag layout memory | Hyprland does this natively |
| `dwm-systray` | System tray in bar | EWW fallback or native smpl-bar SNI/DBusMenu host |
| `dwm-swallow` | Terminal swallows GUI apps | Not needed but nice to have |
| `dwm-cfacts` | Resize slaves | `resizeactive` dispatcher |
| `dwm-vanitygaps` | Gaps between windows | `general:gaps_in/gaps_out` |
| `dwm-attachbottom` | New windows open at bottom | Hyprland default behavior |
| `dwm-restartsig` | Restart DWM in-place (SIGHUP) | `hyprctl reload` |
| `dwm-scratchpad` | Toggleable scratchpad workspace | `togglespecialworkspace` |
| `dwm-ipc` | IPC for external tools (EWW) | Hyprland socket IPC |

### Compositor (picom)

DWM needs a separate compositor for transparency, shadows, and animations.

```
src/compositors/dwm/
  picom.conf            <-- shadows, opacity, fading, blur (limited vs Hyprland)
```

`picom` provides:
- Window shadows and rounded corners
- Opacity rules (per window class)
- Fade animations (open/close)
- Background blur (experimental `picom-ftlabs` fork only)

**Does NOT provide:** per-window blur like Hyprland's `layerrule = blur`, smooth
window move/resize animations, or slide/popin transitions.

---

## 2. bindings.conf to config.def.h

**Effort: Major**

`bindings.conf` is the single source of truth (Hyprland `bindd` format). DWM
needs a build-time parser that generates C structs for `config.def.h`.

### Input Format (bindings.conf)

```
bindd = SUPER, RETURN, Terminal, exec, st
bindd = SUPER, W, Close window, killactive,
bindd = SUPER, code:10, Switch to workspace 1, workspace, 1
```

### Output Format (config.def.h Key[] array)

```c
static const Key keys[] = {
    /* modifier         key        function        argument */
    { MODKEY,           XK_Return, spawn,          {.v = termcmd} },
    { MODKEY,           XK_w,      killclient,     {0} },
    { MODKEY,           XK_1,      view,           {.ui = 1 << 0} },
};
```

### Translation Challenges

| Hyprland Concept | DWM Equivalent | Difficulty |
|------------------|----------------|------------|
| `exec, command` | `spawn, {.v = cmd}` | Straightforward |
| `killactive` | `killclient` | Direct mapping |
| `workspace, N` | `view, {.ui = 1 << (N-1)}` | Bitmask conversion |
| `movetoworkspace, N` | `tag, {.ui = 1 << (N-1)}` | Bitmask conversion |
| `togglefloating` | `togglefloating` | Direct mapping |
| `fullscreen, 0` | `togglefullscr` (patch) | Needs patch |
| `movefocus, l/r/u/d` | `focusdir` (patch) or `focusstack` | Partial -- DWM is stack-based not directional |
| `resizeactive, W H` | `setmfact` / `setcfact` | Different model -- ratio not pixels |
| `togglesplit` | N/A | Hyprland dwindle-specific |
| `pseudo` | N/A | Hyprland dwindle-specific |
| `togglegroup` / `moveintogroup` | `tabbed` patch | Different paradigm |
| `cyclenext` (Alt-Tab) | `focusstack, {.i = +1}` | Close enough |
| `movewindow` (mouse) | `movemouse` | Direct mapping |
| `resizewindow` (mouse) | `resizemouse` | Direct mapping |
| `togglespecialworkspace` | Scratchpad patch | Needs patch |

### Parser Script

Create `src/builder/generate-dwm-keys.sh`:
- Read `bindings.conf`
- Map Hyprland dispatchers to DWM functions
- Map `code:NN` keycodes to `XK_` keysyms
- Map modifier names (`SUPER` -> `MODKEY`, `ALT` -> `Mod1Mask`, etc.)
- Output C struct array
- Called during `build-iso.sh` when `COMPOSITOR=dwm`

Bindings that have no DWM equivalent (e.g., `togglesplit`, `pseudo`) should
emit a comment: `/* NO DWM EQUIVALENT: togglesplit */`

---

## 3. Window Rules

**Effort: Major**

Hyprland's `windows.conf` has ~130 lines of window rules. DWM uses a `rules[]`
array in `config.def.h`.

### Hyprland Format

```
windowrulev2 = float, class:^(Signal)$
windowrulev2 = size 900 700, class:^(Signal)$
windowrulev2 = center, class:^(Signal)$
```

### DWM Format

```c
static const Rule rules[] = {
    /* class      instance  title  tags  isfloating  monitor */
    { "Signal",   NULL,     NULL,  0,    1,          -1 },
};
```

### Gaps

DWM `rules[]` supports:
- Float (yes/no)
- Tag assignment (workspace)
- Monitor assignment

DWM `rules[]` does NOT support:
- Window size constraints (no `size 900 700`)
- Center positioning (window just floats wherever)
- Per-window opacity (need picom rules instead)
- Per-window animation type
- Layer rules (EWW blur, etc.)

### Picom Opacity Rules (supplement)

```
opacity-rule = [
    "95:class_g = 'st'",
    "90:class_g = 'kb-center'",
];
```

### Plan

Add window rules to the `generate-dwm-keys.sh` parser (or a separate
`generate-dwm-rules.sh`), reading from a shared window-rules config or
directly from `windows.conf` with format translation. Size/center rules
can be approximated with DWM patches (`dwm-center`, `dwm-floatrules`).

---

## 4. EWW Listener Scripts

**Effort: Major (workspace), Moderate (window title), Minor (keyboard)**

EWW runs on X11 natively (GTK3). The bar, widgets, and dialogs all work. Only
the listener scripts that talk to Hyprland IPC need X11 backends.

### workspace-listener.sh

**Current:** `hyprctl workspaces -j` + `socat` to Hyprland socket for events.

**X11 plan:** Use EWMH properties:
```bash
# Initial state
wmctrl -d | awk '{print $1, $2, $NF}'

# Watch for changes
xprop -spy -root _NET_CURRENT_DESKTOP _NET_NUMBER_OF_DESKTOPS
```

With `dwm-ipc` patch, could also use a Unix socket like Hyprland.

**Alternative:** `dwm-ipc` patch exposes a JSON IPC socket. If applied, the
listener can use the same `socat` pattern with different event names.

### active-window-listener.sh

**Current:** `hyprctl activewindow -j` + Hyprland socket `activewindow` event.

**X11 plan:**
```bash
# Watch active window changes
xprop -spy -root _NET_ACTIVE_WINDOW | while read -r _; do
    wid=$(xdotool getactivewindow 2>/dev/null) || continue
    class=$(xprop -id "$wid" WM_CLASS 2>/dev/null | awk -F'"' '{print $4}')
    title=$(xdotool getwindowname "$wid" 2>/dev/null)
    printf '{"class":"%s","title":"%s"}\n' "$class" "$title"
done
```

### keyboard-listener.sh

**Current:** Already has X11 fallback using `setxkbmap` and `xkb-switch -W`.
**Status: Minor** -- just needs testing on actual X11.

### Workspace Click Handler (eww.yuck)

The workspace button calls `hyprctl dispatch workspace N`. On X11:
```bash
if [[ -n "$WAYLAND_DISPLAY" ]]; then
    hyprctl dispatch workspace "$1"
else
    xdotool set_desktop "$((${1} - 1))"  # 0-indexed
fi
```

This should be a shared helper script (e.g., `workspace-switch`) rather than
inline in the yuck file.

---

## 5. Shared Bin Scripts

Most shared scripts already work. These need attention:

### focus-or-launch

**Effort: Moderate**

Currently 100% Hyprland (`hyprctl -j clients`, `hyprctl dispatch focuswindow`).

X11 equivalent:
```bash
wid=$(xdotool search --class "$class" | head -1)
if [[ -n "$wid" ]]; then
    xdotool windowactivate "$wid"
else
    exec "$@" &
fi
```

### app-or-focus

**Effort: Moderate**

Same pattern as `focus-or-launch` -- uses `hyprctl clients -j` for window search.

### theme-set

**Effort: Minor**

Uses `hyprctl reload` and `hyprctl setcursor` -- both already guarded behind
`command -v hyprctl`. DWM equivalents:
- Cursor: `xsetroot -cursor_name left_ptr` or `xrdb` merge
- Reload: `kill -HUP $(pidof dwm)` (with `restartsig` patch)
- Border colors: Recompile DWM (or use `dwm-ipc` `setbordercol` if patched)

### keybind-help

**Effort: Minor**

The parser reads `bindings.conf` which stays in Hyprland format (it's the
source of truth). The parser already works -- the only concern is that some
Hyprland-only dispatchers (e.g., `togglesplit`) will show in the help even
though they don't exist in DWM. Options:
1. Filter them out at display time based on compositor
2. Accept it (they just won't do anything)

### vm-debug-dump.sh

**Effort: Minor**

Uses `hyprctl monitors/clients/layers`. X11 path: `xdpyinfo`, `xprop`,
`xdotool search --name ''`.

---

## 6. Terminal (st X11)

**Effort: Major**

`st-wl` is the Wayland port of st (marchaesen/stk-wl). It links against
`libwayland`, `wld`, `libxkbcommon` and has `wl.c` instead of `x.c`.

DWM needs the standard X11 `st` from `suckless.org/st`. The source trees are
fundamentally different.

### Plan

```
src/compositors/dwm/
  st/
    config.def.h    <-- same settings/colors as st-wl where possible
    st.c
    x.c
    patches/        <-- equivalent patches to what st-wl has
```

### Patch Parity

| st-wl Patch | X11 st Equivalent | Status |
|-------------|-------------------|--------|
| SIXEL (inline images) | `st-sixel` | Available |
| Scrollback | `st-scrollback` | Available |
| Keyboard select | `st-keyboard_select` | Available |
| Alpha/transparency | `st-alpha` | Available |
| Font2 (fallback fonts) | `st-font2` | Available |
| Ligatures | `st-ligatures` | Available (different patch) |
| Boxdraw | `st-boxdraw` | Available |
| Undercurl | `st-undercurl` | Available |
| Wide glyph | `st-wide-glyphs` | Available |
| OpenURL on click | `st-openurl` | Available |
| Fix keyboard input | X11 handles natively | Not needed |

The build system already handles `st-wl` vs `st` binary name and detects
`COMPOSITOR` to choose the right build. Just need the X11 source tree.

---

## 7. Theme System

**Effort: Moderate**

### Currently Hyprland-only Templates

| Template | DWM Equivalent |
|----------|----------------|
| `hyprland.conf.tpl` | `picom.conf.tpl` (opacity, shadow, fade) + DWM border color in `config.def.h` |
| `hyprlock.conf.tpl` | `i3lock-color` args script or `slock` (no theming) |

### New Templates Needed

```
src/shared/themes/_templates/
  picom.conf.tpl          <-- shadow, opacity, fade, corner-radius
  dwm-colors.h.tpl        <-- border colors as C #defines
  i3lock-theme.sh.tpl      <-- themed i3lock-color command (optional)
```

### generate-theme-configs.sh

Needs to also generate:
- `picom.conf` per theme (from `picom.conf.tpl` + `colors.toml`)
- `dwm-colors.h` per theme (border active/inactive colors)

### theme-set Script

Already mostly cross-platform. Needs:
- Copy `picom.conf` instead of `hyprland.conf` when on DWM
- Reload picom: `killall picom; picom --config ~/.config/picom/picom.conf &`
- Reload DWM borders: recompile or IPC (if `dwm-ipc` patched)

---

## 8. Lock Screen & Idle

**Effort: Moderate**

### Lock Screen

| Wayland | X11 Option 1 | X11 Option 2 |
|---------|-------------|-------------|
| hyprlock (full theming: clock, password field, background image) | i3lock-color (similar: clock, indicator ring, background) | slock (minimal, no theming) |

Recommendation: **i3lock-color** -- closest feature parity to hyprlock.
Theme integration via a generated lock script with color args from `colors.toml`.

### Idle Management

| Wayland | X11 |
|---------|-----|
| hypridle (lock after 5 min, DPMS off after 10, suspend after 30) | xidlehook (same cascade, Rust-based, inhibitor-aware) |

```bash
xidlehook \
    --not-when-audio \
    --timer 300 'lock-screen' '' \
    --timer 600 'xset dpms force off' '' \
    --timer 1800 'systemctl suspend' ''
```

### Config Location

```
src/compositors/dwm/
  idle.conf             <-- or just args in autostart.sh
  lock-screen.sh        <-- themed i3lock-color wrapper
```

---

## 9. Autostart & Environment

**Effort: Moderate**

### Hyprland: autostart.conf + env.conf

Hyprland uses `exec-once` and `env` directives in config files.

### DWM: autostart.sh (with dwm-autostart patch)

```bash
#!/bin/bash
# src/compositors/dwm/autostart.sh

# Compositor
picom --config ~/.config/picom/picom.conf &

# Wallpaper
feh --bg-fill "$(cat ~/.config/smplos/current/wallpaper)" &

# Bar
eww --config ~/.config/eww daemon &
eww --config ~/.config/eww open bar &

# Notifications
dunst &

# Idle management
xidlehook --not-when-audio \
    --timer 300 'lock-screen' '' \
    --timer 600 'xset dpms force off' '' &

# Polkit
/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1 &

# Automount
automount-watch &

# Keyboard
setxkbmap -option compose:caps,grp:alt_shift_toggle

# Cursor
xsetroot -cursor_name left_ptr
```

### Environment

Hyprland's `env.conf` sets `GDK_BACKEND=wayland`, `QT_QPA_PLATFORM=wayland`,
etc. On X11, none of these are needed -- X11 is the default for all toolkits.

A `.xprofile` or `.xinitrc` addition may be needed for:
```bash
export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=dwm
```

---

## 10. Input Config

**Effort: Moderate**

### Hyprland: input.conf

```
input {
    kb_layout = us
    kb_options = compose:caps, grp:alt_shift_toggle
    repeat_rate = 50
    repeat_delay = 300
    follow_mouse = 0
    touchpad { natural_scroll = false }
}
```

### DWM: xinput / xorg.conf.d

```bash
# In autostart.sh or /etc/X11/xorg.conf.d/
setxkbmap -layout us -option compose:caps,grp:alt_shift_toggle
xset r rate 300 50   # delay, rate

# Touchpad (via xorg.conf.d snippet)
# /etc/X11/xorg.conf.d/30-touchpad.conf
```

kb-center already uses `setxkbmap` on X11, so keyboard layout management works.

---

## 11. Packages

### New: src/compositors/dwm/packages.txt

```
# ── X11 Core ────────────────────────────────────────────────
xorg-server
xorg-xinit
xorg-xsetroot
xorg-xset
xorg-xrandr
xorg-xprop
xorg-xdpyinfo

# ── Window Manager ──────────────────────────────────────────
# dwm built from source (not a package)

# ── Compositor ──────────────────────────────────────────────
picom

# ── Lock & Idle ─────────────────────────────────────────────
i3lock-color
xidlehook

# ── Screenshot ──────────────────────────────────────────────
maim
slop

# ── Clipboard ───────────────────────────────────────────────
xclip

# ── Input Simulation ────────────────────────────────────────
xdotool

# ── Display Management ──────────────────────────────────────
arandr

# ── Wallpaper ───────────────────────────────────────────────
feh

# ── Portal ──────────────────────────────────────────────────
xdg-desktop-portal-gtk

# ── Fonts & Cursor (shared, but may need X11-specific) ──────
xorg-mkfontscale

# ── EWW workspace integration ──────────────────────────────
wmctrl
```

### Packages to Remove (Wayland-only, not needed)

`hyprland`, `hypridle`, `hyprlock`, `hyprpaper`, `xdg-desktop-portal-hyprland`,
`grim`, `slurp`, `wl-clipboard`, `swappy`, `wtype`, `wlr-randr`, `swaybg`,
`qt5-wayland`, `qt6-wayland`, `rofi-wayland` (use `rofi` instead)

---

## 12. Slint Apps (kb-center, notif-center, disp-center, webapp-center)

**Effort: Moderate (kb-center, notif-center, webapp-center), Major (disp-center)**

All four apps use `winit` (via Slint) as the window backend. On Wayland, they
set `app_id` via platform-specific extensions for window rule matching. On X11,
they need to set `WM_CLASS` instead.

### Current (Wayland only)

```rust
use winit::platform::wayland::WindowAttributesExtWayland;
attrs = attrs.with_name("kb-center", "kb-center");
```

### Needed (conditional)

```rust
#[cfg(feature = "wayland")]
{
    use winit::platform::wayland::WindowAttributesExtWayland;
    attrs = attrs.with_name("kb-center", "kb-center");
}
#[cfg(feature = "x11")]
{
    use winit::platform::x11::WindowAttributesExtX11;
    attrs = attrs.with_class("kb-center", "kb-center");
}
```

Or use runtime detection based on the `winit` backend being used.

### Build Dependencies

Add to `Cargo.toml`:
```toml
[target.'cfg(target_os = "linux")'.dependencies]
# Already has wayland deps; also need:
x11-dl = "2"  # or rely on winit's x11 feature
```

### kb-center Specifics

- `sync_to_compositor()` already handles X11 via `setxkbmap` -- works
- `load_from_compositor()` already handles X11 via `setxkbmap -query` -- works
- Manual drag (`set_position`) should work on X11 via winit -- needs testing

### notif-center Specifics

- Uses `dunstctl` only -- fully cross-platform
- Just needs the `WM_CLASS` fix above

### disp-center Specifics

**Effort: Major** -- The app has a `CompositorBackend` trait with runtime
detection (`HYPRLAND_INSTANCE_SIGNATURE` -> Hyprland, `DISPLAY` -> future
xrandr). The architecture is ready for DWM/X11 but only the Hyprland backend
is implemented. Needs:

- **New `XrandrBackend`** implementing the `CompositorBackend` trait:
  - `list_monitors()` -> `xrandr --query` parser
  - `apply_config()` -> `xrandr --output ... --mode ... --pos ...` commands
  - `get_current_config()` -> `xrandr --query` parser
- The Hyprland backend uses `hyprctl monitors -j`, `hyprctl keyword monitor`,
  `hyprctl dispatch dpms` -- none of these exist on X11
- Config persistence: currently writes to `~/.config/hypr/monitors.conf` --
  X11 should write to `~/.config/smplos/monitors.sh` or similar (a script
  sourced from autostart)

### webapp-center Specifics

- Manages `.desktop` files and web app profiles -- **fully cross-platform**
- No compositor-specific code whatsoever
- Just needs the `WM_CLASS` fix above for window rule matching

---

## 12b. Messenger System

**Effort: Major**

The messenger system (`messenger-toggle`, `messenger-keybinds`) is entirely
Hyprland IPC with no X11 fallback. These are 100% Hyprland-only today.

### messenger-toggle

Uses `hyprctl dispatch movetoworkspacesilent`, `hyprctl dispatch focuswindow`,
`hyprctl dispatch togglefloating`, `hyprctl -j clients` -- all Hyprland IPC.

**X11 plan:** Replace with `xdotool` + `wmctrl` equivalents:
```bash
# Find window
wid=$(xdotool search --class "$class" | head -1)
# Toggle visibility (map/unmap or move to/from scratchpad tag)
xdotool windowactivate "$wid"  # or windowminimize + windowactivate
# Float
wmctrl -i -r "$wid" -b toggle,above
```

DWM scratchpad patch may be better suited -- toggle windows to/from a hidden
tag rather than the Hyprland workspace shuffle.

### messenger-keybinds

Generates Hyprland `bindd` format keybindings to
`~/.config/hypr/messenger-bindings.conf`. For DWM, this would need to generate
C key structs (or use `dwm-ipc` commands). This is tightly coupled to the
bindings.conf parser work (Section 2).

### focus-notification-app

Uses `hyprctl dispatch focuswindow` -- needs `xdotool windowactivate` on X11.

---

## 13. Installer

**Effort: Moderate**

### Current State

The installer (`src/installer/`) has several Hyprland assumptions:

| File | Issue | Fix |
|------|-------|-----|
| `install-packages.sh` | Hardcoded `hyprland hypridle hyprlock` | Read from `src/compositors/$COMPOSITOR/packages.txt` |
| `install-configs.sh` | Copies `~/.config/hypr` | Conditional per compositor |
| `install-keyboard.sh` | Appends to `hyprland.conf` + uses `hyprctl` | X11: write to `~/.xinitrc` + use `setxkbmap` |
| `install-greetd.sh` | `tuigreet --cmd start-hyprland` | Needs `start-dwm` or `startx ~/.xinitrc` |

### Compositor Selection

The installer should ask which compositor to install (or auto-detect from the
ISO edition). This could be as simple as:

```bash
COMPOSITOR=$(cat /etc/smplos/compositor 2>/dev/null || echo "hyprland")
```

Set during ISO build based on `COMPOSITOR` env var.

---

## 14. Build System

**Effort: Minor**

The build system is already parameterized with `COMPOSITOR="${COMPOSITOR:-hyprland}"`.

### What Works

- `build.sh` reads `src/compositors/$COMPOSITOR/packages.txt` -- works
- st binary name switches on `COMPOSITOR` -- works
- Shared configs copied unconditionally -- works

### What Needs Adding

| Task | Detail |
|------|--------|
| DWM compilation | `build_dwm()` function in `build.sh` -- `cd src/compositors/dwm/dwm && make clean install` |
| X11 st compilation | `build_st_x11()` -- standard suckless `make` against X11 libs |
| bindings.conf parser | Run `generate-dwm-keys.sh` before DWM compile to produce `config.def.h` |
| Theme files | Run `generate-theme-configs.sh` with DWM templates |
| picom config | Copy `picom.conf` into skel |
| Greetd config | Use `startx` instead of `start-hyprland` |

---

## 15. Already Working

These need zero changes for DWM/X11:

### Shared Scripts (23 scripts)
- `screenshot` -- has X11 path (maim/slop/xclip)
- `lock-screen` -- has X11 path (i3lock/slock)
- `powermenu` -- has X11 path (dmenu/pkill)
- `theme-bg-set` -- has X11 path (feh)
- `theme-bg-next` -- has X11 path (feh/xsetroot)
- `display-settings` -- has X11 path (arandr)
- `open-terminal` -- falls back to st/xterm
- `volume-ctl`, `brightness-ctl` -- hardware layer (pamixer/brightnessctl)
- `automount-watch`, `usb-eject` -- hardware layer (udisksctl)
- `wifi-ctl`, `bluetooth-ctl`, `network-menu` -- hardware layer (nmcli/rfkill)
- `nightlight-ctl` -- gammastep works on both
- `airplane-ctl` -- rfkill
- `toggle-notif-center` -- process toggle, no compositor API
- `bar-ctl` -- EWW by default; opt-in smpl-bar backend through one Unix socket
- `theme-picker` -- rofi (works on X11)
- `dc-theme` -- Double Commander JSON config
- `st-theme` -- OSC escape sequences
- `rebuild-app-cache` -- reads .desktop files
- `battery-notify` -- reads /sys
- `welcome-message` -- reads a text file
- `theme-bg-list` -- lists directories
- `open-url` -- launches browser

### EWW Listener Scripts (10 scripts)
- `volume-listener.sh` -- pactl subscribe
- `network-listener.sh` -- nmcli monitor
- `bluetooth-listener.sh` -- bluetoothctl
- `notification-listener.sh` -- dunstctl
- `notification-history.sh` -- dunstctl history
- `brightness-listener.sh` -- brightnessctl + inotifywait
- `usb-listener.sh` -- udevadm monitor
- `nightlight-listener.sh` -- rfkill + pgrep
- `clock-listener.sh` -- date/cal
- `printer-listener.sh` -- lpstat

### EWW Widgets
- All EWW widgets render on X11 (GTK3). `:namespace` attributes are harmless
  (unused on X11, no errors).

### Editions
- All editions (ai, communication, creators, development, lite, productivity)
  are compositor-agnostic -- just package lists and .desktop files.

### Other
- Dunst notification daemon -- works on both
- Rofi launcher -- X11 version uses same config format
- All 14 themes -- universal (EWW, st, btop, dunst, foot, fish, rofi, logseq,
  neovim, vscode colors all compositor-independent)

---

## Execution Order

Recommended implementation sequence, roughly ordered by dependency and impact:

### Phase 1: Minimal Bootable DWM Desktop

1. **Create `src/compositors/dwm/` directory structure**
2. **X11 `st` terminal** -- get a themed terminal working
3. **DWM source + essential patches** (autostart, vanitygaps, pertag,
   restartsig, scratchpad)
4. **`dwm/packages.txt`** -- X11 package list
5. **Autostart script** -- picom, feh, dunst, EWW bar, polkit
6. **Input config** -- setxkbmap in autostart
7. **Basic `config.def.h`** -- hand-written initially, matching key bindings

### Phase 2: Feature Parity

8. **`bindings.conf` parser** -- auto-generate `config.def.h` keybinds
9. **Window rules parser** -- auto-generate DWM `rules[]`
10. **EWW workspace listener** -- X11 backend (xprop -spy or dwm-ipc)
11. **EWW active-window listener** -- X11 backend (xdotool)
12. **`focus-or-launch` / `app-or-focus`** -- X11 backend (xdotool/wmctrl)
13. **Theme system** -- picom.conf template, dwm-colors.h template
14. **Lock screen** -- i3lock-color wrapper with theme colors
15. **Idle management** -- xidlehook config

### Phase 2b: New Features (added since initial plan)

15b. **disp-center XrandrBackend** -- implement `CompositorBackend` trait for xrandr
15c. **messenger-toggle X11** -- rewrite with xdotool/wmctrl or DWM scratchpad
15d. **messenger-keybinds X11** -- integrate with bindings.conf parser (Section 2)
15e. **focus-notification-app X11** -- xdotool windowactivate fallback

### Phase 3: Polish & Build Integration

16. **Slint apps WM_CLASS** -- all 4 apps (kb-center, notif-center, disp-center, webapp-center)
17. **Installer compositor selection** -- ask user or detect from ISO
18. **Build system** -- `build_dwm()`, `build_st_x11()` functions
19. **ISO build** -- `COMPOSITOR=dwm ./build-iso.sh`
20. **Testing matrix** -- verify every shared script on X11

---

## Testing Checklist

Once implemented, verify each item works on DWM/X11:

- [ ] Cold boot < 800 MB RAM
- [ ] EWW bar renders correctly
- [ ] Workspace switching (click + keybind)
- [ ] Active window title in bar
- [ ] Keyboard layout indicator + Alt+Shift switching
- [ ] All 14 themes apply correctly
- [ ] Lock screen themed
- [ ] Screenshots (region + fullscreen)
- [ ] Clipboard copy/paste
- [ ] Notification center open/close
- [ ] kb-center open/close, layout changes persist
- [ ] Volume/brightness controls
- [ ] WiFi/Bluetooth toggles
- [ ] USB automount
- [ ] Nightlight toggle
- [ ] App launcher (rofi)
- [ ] focus-or-launch works
- [ ] Floating window rules (messengers, calculators)
- [ ] Wallpaper set + cycle
- [ ] Super+K keybind help shows correct bindings
- [ ] disp-center detects and configures monitors via xrandr
- [ ] webapp-center creates/launches/manages web apps
- [ ] Messenger toggle (show/hide Signal, Discord, etc.)
- [ ] Notification click focuses the source app
- [ ] st terminal themed, SIXEL images work
- [ ] Idle -> lock -> DPMS -> suspend cascade
- [ ] Multi-monitor support
