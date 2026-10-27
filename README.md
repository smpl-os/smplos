<p align="center">
  <img src="src/shared/configs/smplos/branding/plymouth/logo.png" alt="smplOS" width="300">
</p>

<h3 align="center">A simple OS that just works.</h3>

<p align="center">
  Minimal &bull; Lightweight &bull; Offline-first &bull; Cross-compositor
</p>

<p align="center">
  <a href="DEVELOPMENT.md">Development Guide</a>
   &nbsp;&bull;&nbsp;
   <a href="CREATING_MODIFYING_A_THEME.md">Theme Authoring Guide</a>
   &nbsp;&bull;&nbsp;
   <a href="RELEASE_NOTES.md">Release Notes</a>
</p>

<p align="center">
  <strong>Latest release: v0.7.0</strong>
  &nbsp;&bull;&nbsp;
  <a href="https://archive.org/download/smplos_260313-0458/smplos_260313-0458.iso"><strong>⬇ Download Base ISO</strong></a>
</p>

---

## What's new in v0.7.0

- **Start-menu Enter key launches top search result.** Pressing Enter while
  typing a search query now immediately launches the first result. Previously
  the search `FocusScope` (needed for arrow-key navigation) had no `Key.Return`
  handler so Enter silently did nothing.

- **Settings card deep-links restored in start-menu search.** Clicking a
  keyword result like "Airplane Mode", "WiFi", "Resolution", or "Bluetooth
  Devices" in start-menu now opens Settings and highlights (blinks) the
  relevant card. The `rebuild-app-cache` script was generating
  `smplos-settings wifi` style execs for search-only entries instead of the
  `settings --tab wifi --highlight "Airplane Mode"` deep-link format — so
  Settings opened on the right tab but never highlighted the card.

- **"Airplane Mode" and other missing keywords added.** `settings_search_index`
  was missing "Airplane Mode" along with several other WiFi/Bluetooth card
  entries. All are now present and searchable.

- **Deployment no longer leaves search keywords stale.** `deploy-local.sh`
  now calls `rebuild-app-cache` after `settings --export-index` so keywords
  are immediately live after every deploy.

- **Alt-Shift keyboard layout switching fixed.** The `kb_variant` line in
  `input.conf` was written as `phonetic` (no leading comma), which applied
  the phonetic variant to the first layout (`us`) — an invalid combination
  that caused Hyprland to reject the whole multi-layout config and load only
  `us` with no XKB options. Fixed to use the positional form `,phonetic`.
  Alt-Shift now reliably switches between layouts.

- **Regression guardrails in smpl-apps CI.** Four new CI checks prevent
  the above regressions from returning undetected in future syncs:
  - Enter-key handler present in search FocusScope
  - `Airplane Mode` / `Wi-Fi` / `Bluetooth` present in settings search index
  - `rebuild-app-cache` called in `deploy-local.sh`

For previous releases, see [RELEASE_NOTES.md](RELEASE_NOTES.md).

---

## What is smplOS?

smplOS is a minimal Arch Linux distro built around one idea: **simplicity**.

It started as an attempt to build a lighter version of Omarchy - same keybindings, same themes, but without the bloat. That contribution was rejected, so we forked and built our own distro. Along the way we rewrote most of the stack: a [suite of lightweight GUI apps in Rust](#rust-app-suite), a [patched suckless terminal](#terminal-st-wl) that renders inline images at a fraction of Kitty's footprint, a cross-compositor architecture, and a theme system that touches every app on the desktop. What came out the other side isn't Omarchy lite - it's a different OS.

### Why smplOS?

- **Lightweight.** Under 800 MB of RAM on a cold boot (Omarchy idles at 1.7 GB). Every package earns its place.
- **Fast installs.** Fully offline - no internet required. A fresh install completes in under 2 minutes.
- **Cross-compositor.** Built from the ground up to support multiple compositors. Hyprland (Wayland) ships first, [DWM (X11) is next](DWM-X11.md). Shared configs, shared themes, shared keybindings - the compositor is just a thin layer.
- **One UI toolkit.** EWW powers the bar, widgets, and dialogs. It runs on both X11 and Wayland. No waybar, no polybar, no redundant tools.
- **21 built-in themes.** One command switches colors across the entire system - terminal, bar, notifications, borders, lock screen, and editor.

---

#### Start Menu

A native start menu built with Rust and Slint, themed to match the active system colors. Tap <kbd>Super</kbd> to open it - browse apps by category, search across all installed apps (including Flatpak, AppImage, and web apps), or jump to Settings. Full keyboard navigation with Tab, Shift+Tab, arrow keys, and Enter. No dock, no taskbar, no wasted pixels.

<a href="images/1-start-menu.png"><img src="images/1-start-menu.png" width="720" /></a>

#### Memory Footprint

A cold boot sits under 800 MB of RAM with the full desktop running - bar, notifications, compositor, and all background services. Unlike other lightweight distros that sacrifice usability to hit low numbers, smplOS keeps quality-of-life features like auto-mount, theme switching, a notification center, and a full app launcher. Light enough for a 2 GB VM, comfortable enough for daily driving.

<a href="images/2-mem.png"><img src="images/2-mem.png" width="720" /></a>

#### Terminal (st-wl)

st is our terminal of choice - a suckless terminal patched for the features that matter. It starts in milliseconds and idles at around 25 MB of RAM. We added SIXEL image support, scrollback, clipboard integration, Page Up/Down, and alpha transparency. The result is a terminal that can display inline images just like Kitty (~350 MB), but at a fraction of the footprint. Every fix was made in `config.def.h` following the suckless philosophy: if you don't need it, it doesn't exist.

We also fixed several upstream bugs in the suckless st codebase:

- **History buffer allocation** - the default scrollback patch pre-allocates the entire buffer (HISTSIZE x columns) at startup, wasting tens of MB. We rewrote it to use page-based lazy allocation (256-line pages, allocated on demand).
- **Page Up/Down not working** - the scrollback patch only bound Shift+PageUp/Down but left plain PageUp/Down doing nothing. Added `MOD_MASK_NONE` bindings so both work.
- **Unnecessary X11 libraries on Wayland** - the SIXEL patch links against imlib2, which drags in the entire X11 library chain (libX11, libxcb, libXext, etc.) into a Wayland-only binary. Stripped the dependency tree from 29 to 21 libraries, cutting ~5 MB of RSS.
- **X11-only patches breaking Wayland** - several patches (e.g. `sixelbyteorder = LSBFirst`, boxdraw, openurlonclick) use X11 macros and structs that don't exist in the Wayland build. Identified and disabled them.
- **Font fallback crash** - st-wl crashed on launch when no `-f` flag was given. Fixed the default font fallback path.
- **SIXEL linker errors** - enabling the SIXEL patch in `patches.def.h` alone wasn't enough; the SIXEL source files and imlib2 libs also need uncommenting in `config.mk`.

<a href="images/4.term.png"><img src="images/4.term.png" width="720" /></a>

#### Text Editor (micro)

micro is our default text editor — a modern, intuitive terminal editor that works like a desktop app (Ctrl+S to save, Ctrl+C/V for clipboard, Ctrl+Z to undo). We maintain a [lightweight fork](https://github.com/smpl-os/micro) that adds **dynamic config reloading** — when `theme-set` switches the system theme, micro picks up the new colorscheme instantly without restarting. The fork stays fully compatible with upstream micro and is synced periodically.

Our patch adds:

- **Live colorscheme reload** — watches `~/.config/micro/colorschemes/*.micro` for changes and reloads on the fly. When `theme-set` writes a new theme file, every running micro instance updates immediately.
- **Live settings reload** — watches `settings.json` and `bindings.json` for changes.

This is the same pattern we use everywhere: the theme system writes config files, and each app watches for changes. No restart, no manual reload.

#### Themes

smplOS ships with 21 themes inherited and expanded from the Omarchy project. A single `theme-set` command applies colors system-wide - terminal, EWW bar, notifications, Hyprland borders, lock screen, btop, neovim, and VS Code. Themes are generated from a single `colors.toml` source of truth.

Native transparency is **background-only**: capable Nemo, Grafium in Auto mode,
and regular smpl-apps windows use `app_background_opacity`, while text, icons,
selections, and content remain readable. Popup apps retain `popup_opacity`;
terminals retain their separate background controls. Hyprland passes native
alpha through without fading the entire window. Matrix, Amber, and Grafium
themes intentionally keep regular native backgrounds opaque.

This needs the coordinated native app releases, not just updated theme files.
Old Nemo remains opaque safely. Other ordinary GTK/Qt/Electron apps receive
theme-controlled **whole-window** transparency on Hyprland: text and icons fade
too, an intentional tradeoff. Known media, games, picture-in-picture and
fullscreen windows are exempt from added compositor fading. Native app alpha
is still app-owned even in fullscreen; blur depends on compositor support.
See the [theme alpha ownership guide](CREATING_MODIFYING_A_THEME.md#opacity-keys-in-colorstoml)
and [release sequence](UPDATING.md#background-only-transparency-delivery).
Normal **Update OS** must install the published native releases as well as
theme/config changes; source pushes and cached tags alone are insufficient.
Reopen apps when ready after updating. Grafium is independently installed and
updated; Update OS does not deliver its binary or inspect custom Grafium launchers.

<a href="images/5-themes.png"><img src="images/5-themes.png" width="720" /></a>

#### Keybindings

smplOS uses the same keybindings as [Omarchy](https://omakub.org/), so migrating from that project is seamless - your muscle memory carries over. Press <kbd>Super</kbd>+<kbd>K</kbd> to open the keybinding cheatsheet overlay at any time. The overlay is **dynamically generated** by parsing `bindings.conf` at runtime, so any keybinding you add or change shows up in the help automatically - no manual docs to maintain.

Hyprland's scrolling layout keeps window and column operations separate:
**Super+Shift+arrows** swaps the focused window; **Super+Ctrl+Shift+Left/Right**
moves the entire column. **Super+R** expands the column into available space,
while **Super+Ctrl+R** enters arrow-key resize mode (Escape/Enter exits).
With the `smpl-scroll` plugin a column can grow up to four monitor-widths wide
(Hyprland itself stops at one): keep pressing the arrows, then pan the view across
it with **Super+Shift+]** / **Super+Shift+[** (or move focus with **Super+]** / **[**);
see [`smpl-scroll`](src/compositors/hyprland/plugins/smpl-scroll/README.md).
The size presets (**Super+-**, **Super+=**, **Super+R**) bring a column back to at
most one monitor.
Scrolling does not support orientation rotation, so the old Super+J shortcut
is no longer shipped. Update OS repairs only the known stock entries in
existing binding files, saving a verified backup beside each changed file;
custom actions and occupied destination shortcuts are preserved.
**Super+S** toggles Signal; **Super+Ctrl+S** toggles the scratchpad.
An explicit messenger shortcut in `bindings.conf` takes precedence over
automatic messenger key assignment.

<a href="images/6-keybindings.png"><img src="images/6-keybindings.png" width="720" /></a>

---

### Rust App Suite

Linux has no shortage of CLI tools, but when it comes to graphical settings panels that are lightweight, Wayland-native, and theme-aware, the options are slim. Most existing tools are either GTK/Qt monoliths that pull in hundreds of megabytes, Electron wrappers, or they just don't exist for tiling Wayland compositors. So we wrote our own.

The smplOS app suite is a set of purpose-built GUI apps written in **Rust** with the **Slint** UI framework. Each app is a single static binary under 5 MB, starts in milliseconds, integrates with the smplOS theme system, and works on both X11 and Wayland. They replace functionality that mainstream desktops take for granted but that tiling WM users have historically gone without.

#### Notification Center

A notification hub that collects and groups desktop notifications by app. Supports dismiss, clear-all, and scrollable history. Integrates with Dunst over D-Bus. We built this because every existing notification center was either Electron-based (heavy), GNOME-only, or lacked grouping. Ours idles at under 10 MB of RAM.

<a href="images/3-notif-center.png"><img src="images/3-notif-center.png" width="720" /></a>

#### Display Manager

A graphical display configuration panel. Detects connected monitors via Hyprland IPC, shows resolution, refresh rate, scale, and position for each display, and lets you apply changes live. **Make primary** chooses the primary monitor and the taskbar moves with it (see [Monitor-owned workspaces](#monitor-owned-workspaces)). No external dependencies - just `hyprctl` under the hood. Replaces the need for `wlr-randr` CLI or a full KDE/GNOME settings app just to rearrange monitors.

<a href="images/7-displaymgr.png"><img src="images/7-displaymgr.png" width="720" /></a>

#### Keyboard Manager

A keyboard layout and input configuration panel with two tabs. The **Keyboard** tab shows active layouts, lets you add/remove languages, and includes a live key-cap preview that updates as you switch layouts. The **Dictation** tab sets up speech-to-text via Voxtype/Whisper — pick a language, choose a model size, and install with one click. English (`base.en`) works offline out of the box — the model is bundled into the ISO. Supports 100+ languages, 3-tier package fallback, and live progress. All changes are applied live via `hyprctl keyword`.

<a href="images/8-keyboard.png"><img src="images/8-keyboard.png" width="720" /></a>

#### Macro Keypads

Cheap CH552 macro keypads (USB `1189:8890`, 3 to 16 keys, up to 3 knobs) work as soon as they're plugged in. A keypad icon appears in the bar while one is connected; click it to open **Settings → Keypad**. There you can map keys and knobs to shortcuts, media keys or commands, give apps their own profiles, and turn on API plugins such as Kdenlive's control-surface interface. A guided wizard installs the open firmware. See [KEYPAD.md](KEYPAD.md).

#### Mouse

**Settings → Mouse** sets pointer speed, acceleration (system default, flat or adaptive), natural scrolling and scroll speed. Changes apply live and are saved to `~/.config/hypr/pointer.conf`, which Hyprland reads again at login.

With the matching native Settings and `mouse-remapperd` build, **Razer Naga V2
HyperSpeed (`1532:00b4`)** button assignments are applied rather than just saved.
The guided setup learns actual inputs for the highlighted diagram positions:
primary buttons, wheel/tilt, extra buttons and the 12-button side grid.
Arm each capture, press and release the requested control, then confirm before
continuing. Retry mistakes or skip unavailable controls; skipped positions keep
existing mappings. Review and save the complete setup, or cancel without
replacing saved mappings. No factory input codes are assumed.
You can also learn an individual button's actual signal, then use
**Identify buttons** to press a button, highlight/select it on the map, and edit
its assignment. Identify also reports wheel/tilt directions and suppresses
scrolling and non-primary button output while active; pointer movement and
primary clicks remain usable. Controls that emit no Linux input event cannot
be identified or learned through this backend. Global remapping uses Linux
input/uinput independently of the compositor; automatic per-app profiles
require the Hyprland focus backend.
Application API actions, including Kdenlive, use the keypad's shared action
catalog and execution engine, not substituted keyboard shortcuts.
Other mouse models retain the saved preview until a backend supports them.

The mouse backend has its own device-triggered service, separate from macro
keypads. It does not read other keyboards, enable the keypad tray icon, or
require membership in the input group. Existing mouse/keypad mappings are
preserved. This requires the native binary delivery described in
[mouse remapping delivery](UPDATING.md#mouse-remapping-delivery); updating OS
scripts alone does not turn an older Settings preview into live remapping.

---

### Design Decisions

Every tool in smplOS was chosen to work across compositors (Wayland and X11) so the OS feels identical regardless of which one you run.

| Component | Choice | Why |
|-----------|--------|-----|
| **Bar & widgets** | EWW | GTK3-based, runs natively on both X11 and Wayland. One codebase for bar, widgets, theme picker, and keybind help. Replaces waybar and polybar. |
| **Start Menu** | Rust + Slint | Native GPU-rendered app launcher with categories, search, source badges (AUR/Flatpak/AppImage/Web App), and Settings tab. Theme-aware, keyboard-driven, under 5 MB. |
| **Terminal** | st / st-wl | Suckless st has an X11 build and a Wayland port (marchaesen/st-wl). Same config.h, same patches, same look. Starts in ~5ms and uses ~4 MB of RAM - critical for staying under the 850 MB cold-boot target. |
| **Text Editor** | micro (fork) | Fork of [micro-editor/micro](https://github.com/micro-editor/micro) with dynamic config reloading for live theme switching. Single static binary, no dependencies. Fully compatible with upstream. |
| **Notifications** | Dunst | Works on both X11 and Wayland with the same config. Lightweight, themeable, no dependencies on a specific compositor. |

The rule is simple: if a tool only works on one display server, it doesn't ship in `src/shared/`. Compositor-specific code stays in `src/compositors/<name>/` and is kept as thin as possible.

### Editions

smplOS ships in focused editions that **stack on top of each other**. Pick the ones you need - they all merge cleanly:

| Flag | Edition | Focus | Example apps |
|------|---------|-------|-------------|
| `-p` | **Productivity** | Office & workflow | LibreOffice, KeePassXC |
| `-c` | **Creators** | Design & media | OBS, Kdenlive, GIMP |
| `-m` | **Communication** | Chat & calls | Discord, Signal, Slack |
| `-d` | **Development** | Developer tools | VSCode, LazyVim (neovim), lazygit |
| `-a` | **AI** | AI tools | Ollama, open-webui |

Build with any combination:

```bash
./build-iso.sh -p -d          # Productivity + Development
./build-iso.sh -p -d -c -m    # Stack all four
./build-iso.sh                 # Base only (browser, terminal, file manager)
```

Every edition installs offline, in under 2 minutes, from the same ISO.

Grafium is temporarily excluded from **all ISO editions**, including Base and
All, until its AUR package is published. Its future package updates belong in
App Center's application updates, not **Update OS**. Existing installations,
notes, settings and custom launchers are preserved.

---

## Download

**smplOS v0.6.8 — Base edition** (browser, terminal, file manager, full native app suite, OTA updates — under 800 MB RAM at idle)

[![ISO IMAGE download](https://img.shields.io/badge/ISO%20IMAGE-download-0567ff?style=for-the-badge)](https://archive.org/details/smplos_260313-0458)
[![TORRENT download](https://img.shields.io/badge/TORRENT-download-00b4d8?style=for-the-badge)](https://archive.org/download/smplos_260313-0458/smplos_260313-0458_archive.torrent)

> Both buttons open the archive.org page — click **ISO IMAGE download** or **TORRENT download** there to get the file.

Other editions (Productivity, Development, Creators, AI, etc.) must be built from source — see [Building](#building).

---

## Getting Started

On first boot, a notification shows the essential keybindings. Here they are for reference:

| Shortcut | Action |
|----------|--------|
| <kbd>Super</kbd> (tap) | Start menu |
| <kbd>Super</kbd>+<kbd>Enter</kbd> | Terminal |
| <kbd>Super</kbd>+<kbd>A</kbd> | App Center |
| <kbd>Super</kbd>+<kbd>W</kbd> | Close window |
| <kbd>Super</kbd>+<kbd>F</kbd> | Fullscreen |
| <kbd>Super</kbd>+<kbd>T</kbd> | Toggle floating |
| <kbd>Super</kbd>+<kbd>1-9</kbd> | Switch workspace |
| <kbd>Super</kbd>+<kbd>K</kbd> | Keybinding cheatsheet |
| <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd> | File manager |
| <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>B</kbd> | Web browser |
| <kbd>Print</kbd> | Screenshot |
| <kbd>Super</kbd>+<kbd>Ctrl</kbd>+<kbd>X</kbd> | Toggle dictation |
| <kbd>Super</kbd>+<kbd>Escape</kbd> | Power menu |

Press <kbd>Super</kbd>+<kbd>K</kbd> anytime to see all bindings in an overlay.
Search matches case-insensitive substrings in shortcuts and descriptions; multiple
words must all match. Shorter shortcuts come first, so `Super+S` appears before
`Super+Shift` variants. The app launcher and theme picker still use fuzzy matching.

<kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd> focuses the most recently used Nemo
window on the focused monitor's current workspace, or opens a new window there.
Nemo windows on other workspaces are left in place. Repeated presses while a
window is opening do not launch duplicates. The floating-file-manager shortcut
and other apps' global focus-or-launch behavior are unchanged.

On Hyprland, messenger shortcuts such as <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd>
for Signal open on the keyboard-focused monitor, even if the mouse is elsewhere.
Hiding the messenger returns focus to the previous window if it still exists on
that workspace; it does not bring back a window you moved or closed.

#### Monitor-owned workspaces

Supported Hyprland Lua configurations give numbered workspaces monitor homes
without switching all monitors as a set. OS updates and first login enable automatic spatial
assignment when no saved workspace preference exists. Existing mappings and
explicit opt-outs are preserved; niri and X11 keep their existing behavior.

To choose fixed homes that preserve the current layout instead:

```bash
workspace-ctl init --preserve
```

Existing workspaces keep their current monitor. Unused slots from `bar.conf`
are distributed across connected monitors. Monitor identities (`M1`, `M2`, ...)
remain stable when their positions change; unique hardware identities also
survive connector changes. Identical displays without unique identities use
their connectors to avoid guessing.

The single EWW bar shows the keyboard-focused monitor's workspaces using the
Numbers or compact two-row Squares style from Settings > Taskbar. Spacing and
Left/Center position also apply to both styles. Squares keep the real workspace
IDs (including gaps); hover for their identities or open the numbered overview.
Its monitor button opens a spatial overview of all displays, including rotated,
stacked, and disconnected monitors. Filled chips indicate keyboard focus,
outlines indicate visibility, and dots indicate occupied workspaces. Escape
closes the overview on supported Hyprland versions without consuming Escape
in other applications once the overview is closed.

The **primary monitor** is the one that owns workspace 1. The bar and its
popups (calendar, quick settings, notifications, USB, workspace overview) open
on it, and the bar moves as soon as the primary monitor changes. Choose it with
**Make primary** in Settings > Display, or from a terminal:

```bash
workspace-ctl primary             # print the primary monitor's connector
workspace-ctl set-primary DP-3    # a connector or a monitor identity such as M2
```

In automatic spatial mode the primary monitor comes first and the others follow
left to right; choosing a new one also clears explicit workspace transfers. In
fixed-home mode the new primary swaps workspaces with the old one.
`workspace-ctl primary` reports the monitor that owns workspace 1 right now, so
moving workspace 1 by hand changes it without rewriting the saved choice.
Without the stable workspace policy, or on niri and X11, the bar and popups stay
on EWW's default monitor.

The Taskbar workspace count is a **total across all monitors**, not a per-monitor
count. Changing it updates the shared pool through the workspace listener.
Automatic mode provides at least one workspace per connected monitor, and
occupied or visible workspaces remain available even above the configured count.
Changing style, spacing or position does not reassign homes or move focus.
`bar-ctl apply` validates the saved workspace preferences together and reports
invalid values, duplicate workspace keys or EWW failures instead of silently
claiming success. `bar.conf` uses literal `key=value` lines; surrounding whitespace
and full-line comments are supported.

Keyboard workspace selection, bar clicks, and existing-app shortcuts follow a
workspace to its home instead of swapping it onto another monitor. Local
next/previous navigation stays within the focused monitor's homes. Window
transfer uses physical monitor geometry and the destination's visible workspace;
an explicit whole-workspace transfer changes that workspace's saved home.
In fixed-home mode, disconnected homes fall back to a connected display without
forgetting their ownership, and return when their home reconnects.

Alternatively, assign workspaces in physical monitor order and keep that order
automatic when displays move, connect, or disconnect:

```bash
workspace-ctl arrange --auto
```

Monitors are ordered left-to-right, then top-to-bottom when their horizontal
positions match. Workspace 1 goes to the first monitor, 2 to the next, and so on,
wrapping around for later numbers. With two monitors this puts odd numbers on
the left and even numbers on the right. Existing workspaces and their windows
move to the assigned screens; monitor identities themselves are not renumbered.
Explicit workspace moves are retained until the next monitor-layout change.
Automatic mode always supplies at least one workspace per connected monitor.
Use `workspace-ctl arrange` without `--auto` for a one-time arrangement.

The saved mapping is `~/.config/smplos/workspace-policy.json`. Generated
`workspace-rules.lua` is not an editing surface. Inspect or disable the trial with:

```bash
workspace-ctl status
workspace-ctl disable
```

Disabling restores the previous controls and saved bar style without closing
windows or deleting the saved mapping. Re-enable with `workspace-ctl init`.
Use `workspace-ctl init --preserve` to stop automatic reassignment and keep the
current saved homes. An opt-out is preserved across updates and logins, even if
`disable` is run before the first automatic setup.

### Themes

Switch the system theme (terminal, bar, borders, lock screen, editor) with a single command:

```bash
theme-set catppuccin     # or: dracula, nord, gruvbox, rose-pine, ...
```

Or open the theme picker from the start menu's Settings tab.

#### OpenChamber live themes (requires a compatible OpenChamber build)

`theme-set-openchamber` translates the active `colors.toml` into an OpenChamber
custom theme named `smplos-<theme>`, then uses the local `theme.set` control API
to notify its windows. Amber keeps its actual black/orange palette, not a
nearest built-in substitute. Light/dark variant follows `light.mode`;
background-only opacity follows `app_background_opacity`, then explicit
`popup_opacity`, then 1.0. Foreground colors stay opaque.

The compatible fork release is
[OpenChamber 2.5.2](https://github.com/KonTy/openchamber/releases/tag/v2.5.2),
with Linux packages for Arch, Ubuntu and Nobara. Its packaged two-window
integration was verified with the actual bridge through Amber, Catppuccin and
back, including native alpha 1.0, 0.5 and 1.0. Older/upstream builds without
the protocol are rejected before file changes. Live background alpha requires
the fork's Linux frameless desktop launcher to enable its native transparent
window; framed and explicitly opaque launches cannot apply translucent themes.
The adapter neither restarts nor launches the app, and does not change that
environment globally. Hyprland treats
`openchamber` as self-managed alpha so compositor fading cannot dim its text.

Before backing up settings or publishing a theme file, the bridge requests
authenticated `theme.capabilities` on the control endpoint. Protocol 1 must
confirm custom-theme and background-opacity support, the supported range
`0 < opacity <= 1`, and freshly probed live windows. Translucent themes require
every target window to report native transparency readiness. Unsupported apps,
closed windows or an opaque launch warn without changing their files.

The helper runs in `theme-set`'s optional app stage, including the existing
**Super+Shift+T** picker path. It discovers the local port and optional client
token read-only from `$OPENCHAMBER_DATA_DIR/settings.json`, defaulting to
`~/.config/openchamber/settings.json`. No installed config means no work.
For an isolated instance, `~/.config/smplos/openchamber-data-dirs` can list
absolute data directories, one per line (blank lines and `#` comments allowed).
That list **replaces** the default target, so a demo need not touch the real app.
Remove the override after the demo.

Only custom themes with the `smplos-` prefix are written. Existing matching
files and settings receive verified, private backups under
`~/.local/state/smplos/openchamber-theme-backups/` before publication or the
API request. Other themes, sessions and settings are not edited by the helper;
OpenChamber saves the selected theme through its own API. Generated themes
remain visible in its Settings. API refusal, unsupported versions and missing
windows warn without blocking other integrations. `theme.set` must acknowledge
successful persistence and renderer application for every probed window, with
the exact theme ID and background opacity. A broadcast-only `delivered` count
is rejected. Requests use a 15-second HTTP timeout for the app's at-most-10-second
acknowledgment deadline; timeouts, window-set changes or mismatched responses
report application as unconfirmed and potentially partial, never success.
These acknowledgments do not measure compositor output; visual/native-alpha
verification remains a separate release check. Zero background opacity is unsupported
by this interface and is reported rather than silently changed.

#### Copilot desktop theme sync (experimental, opt-in)

`theme-set-copilot` maps the active smplOS theme to a built-in GitHub Copilot
**desktop app** palette without restarting the app or its sessions. It uses
Copilot's own Settings controls through AT-SPI, not the CLI theme or database
writes. This was exercised with desktop version 1.1.21 on Linux.

**This briefly opens Settings and can move keyboard focus or interrupt typing.**
Only enable it if that tradeoff is acceptable. It closes the dialog it opened
and attempts to restore keyboard focus; restoration is not guaranteed. An
already-open Settings dialog is left alone. Matching saved palette and
appearance settings are a no-op, so repeated theme applications do not open it.

With the updated `theme-set` and `theme-set-copilot` installed, enable:

```bash
mkdir -p ~/.config/smplos
touch ~/.config/smplos/copilot-theme-sync.enabled
```

Subsequent selections with **Super+Shift+T** apply automatically to the running
app. To try only this integration against the current theme, run
`theme-set-copilot`. Disable it by removing that single opt-in file. The app
must already be running, with Linux `python-gobject` and `at-spi2-core`
available. The integration never installs dependencies or launches the app.

| smplOS | Copilot built-in palette |
|--------|--------------------------|
| Amber, Amber HUD | IC Orange PPL |
| Catppuccin, Catppuccin Latte | Catppuccin Mocha |
| Ethereal | Light purple |
| Everforest, Osaka Jade | Selene Selenized |
| Flexoki Light | Flexoki |
| Grafium | GitHub |
| Gruvbox | Gruvbox Material |
| Hackerman, Matrix, Matrix HUD | Homebrew |
| Kanagawa | Kanso Ink |
| Matte Black | Monochrome |
| Nord | Nord Midnight |
| Ristretto | Espresso |
| Rose Pine | Rosé Pine |
| Tokyo Night | Tokyo Night |

These are nearest built-in choices, not exact smplOS palettes. Both app and
terminal appearance use Light when the active theme has `light.mode`, otherwise
Dark. In particular, Catppuccin Latte uses the Catppuccin Mocha palette with
Light appearance. Unknown/custom theme names use GitHub with a warning.
Fonts, contrast/color mode, other settings and opacity are not set; Copilot
updates its own recent-palette history normally.

The adapter confirms the selected UI controls and checks the app's saved theme
row read-only. Missing/filtered palette controls, unsupported settings formats,
unavailable accessibility or an absent app produce warnings without aborting
the rest of `theme-set`. Reset the palette filter in Copilot Settings if a mapped
palette is hidden. Future Copilot UI changes may require updating this
experimental adapter. It is not a supported Copilot settings API.

---

## Architecture

smplOS separates shared infrastructure from compositor-specific config. The goal is maximum code reuse - compositors are a thin layer on top of a shared foundation.

```
src/
  build-iso.sh              Entry point — detects Docker, launches builder
  bootstrap.sh              One-shot host bootstrap (installs Docker if absent)
  regen-all-themes.sh       Single entry point for templates and Nemo CSS generation

  shared/                   Everything here works on ALL compositors
    bin/                    User-facing scripts (installed to /usr/local/bin/)
                            Includes: dictation-prime, dictation-toggle, dictation-setup,
                            theme-set, rebuild-app-cache, smplos-settings, bar-ctl, ...
    eww/                    EWW bar and widgets (GTK3 — works on X11 + Wayland)
    configs/
      smplos/               Cross-compositor configs (bindings.conf, messengers.conf, branding)
      <app>/                Per-app default configs (btop, dunst, fish, foot, nvim, …)
    themes/                 21 themes — each a self-contained directory with pre-baked configs
    icons/                  SVG status icon templates (baked with accent colors by theme-set)
    applications/           Shared web-app .desktop entries and hicolor icons
    skel/                   Default user home skeleton (copied to /etc/skel in the ISO)
    system/                 System-level files (os-release, …)
    start-menu/             Start menu launcher (Rust + Slint)
    app-center/             App center — install/manage packages (Rust + Slint)
    notif-center/           Notification center — dunst history viewer (Rust + Slint)
    disp-center/            Display manager — monitor layout/resolution (Rust + Slint)
    kb-center/              Keyboard manager — layouts, repeat rate (Rust + Slint)
    webapp-center/          Web app manager — sandboxed browser shortcuts (Rust + Slint)
    packages.txt            Shared package list (all compositors)
    packages-aur.txt        AUR packages (prebuilt, injected into offline mirror)
    packages-flatpak.txt    Flatpak apps (installed on first boot)
    packages-appimage.txt   AppImages (bundled into the ISO)

  compositors/
    hyprland/               Hyprland-specific config
      hypr/                 hyprland.conf (sources shared bindings.conf)
      configs/              Hyprland-only app configs (hyprlock, hyprpaper, …)
      st/                   st-wl patched terminal (config.def.h, patches.def.h)
      packages.txt          Wayland-specific packages
      postinstall.sh        Hyprland post-install steps
    dwm/                    DWM-specific config (X11, planned)
      st/                   st patched terminal
      packages.txt          X11-specific packages
      postinstall.sh        DWM post-install steps

  editions/                 Optional edition overlays (stack on top of base)
    lite/                   Lite edition — reduced package set
    productivity/           Productivity — LibreOffice, KeePassXC
    creators/               Creators — OBS, Kdenlive, GIMP
    communication/          Communication — Discord, Signal, Slack
    development/            Development — VSCode, LazyVim, lazygit
    ai/                     AI — Ollama, open-webui

  installer/                smplOS interactive installer (smplos-install)
  builder/                  ISO build pipeline (runs inside Docker/Podman)
  custom-pkgbuilds/         In-tree PKGBUILDs for packages not in AUR

release/                    VM testing tools (dev-push.sh, dev-apply.sh, test-iso.sh, QEMU scripts)
build/
  prebuilt/                 Pre-compiled AUR packages (.pkg.tar.zst) bundled into the ISO

# Sibling repos (separate git repositories in the smpl-os GitHub org):
../micro/                   Fork of micro-editor with dynamic config reloading (live themes)
../st-smpl/                 Fork of suckless st-wl with SIXEL, scrollback, transparency
../nemo-smpl/               Fork of Nemo file manager with smplOS patches
../eww/                     Fork of ElKowars wacky widgets (EWW) with pointer grab fix
../smpl-apps/               Rust app suite (start-menu, notif-center, settings, etc.)
```

## Design Principles

- **Simple over opinionated.** Provide good defaults, not forced workflows.
- **Cross-compositor first.** Every feature must work across Hyprland (Wayland) and DWM (X11). Compositor-specific code stays in `src/compositors/<name>/`.
- **EWW is the UI layer.** Bar, widgets, dialogs - all EWW. It runs on both GTK3/X11 and GTK3/Wayland.
- **One theme system.** `theme-set` applies colors to EWW, terminals, btop, notifications, compositor borders, lock screen, and neovim.
- **bindings.conf is the single source of truth** for keybindings across all compositors.
- **Minimal packages.** One terminal, one launcher, one bar. No redundant tools.
- **Offline-first.** The ISO carries everything needed. No downloads during install.

## Compositors

| Compositor | Display Server | Terminal | Status |
|------------|---------------|----------|--------|
| Hyprland   | Wayland       | st-wl    | Active |
| DWM        | X11           | st       | Planned |

## Start Menu

A native start menu built with Rust and [Slint](https://slint.dev). It appears at the bottom-left of the screen (like a Plasma/Windows start menu) with a slide-left animation, blur, and theme-aware colors.

**Open it:** Press <kbd>Super</kbd> (tap and release) or click the logo in the EWW bar.

### Categories

The left sidebar shows category tabs with Nerd Font icons:

| Category | Icon | Contents |
|----------|------|----------|
| All Apps | 󰀻 | Everything |
| Internet | 󰇧 | Browsers, email, chat, web apps |
| Development | 󰅨 | IDEs, editors, git tools |
| Multimedia | 󰝚 | Media players, recorders |
| Graphics | 󰃣 | Image editors, viewers |
| Office | 󰈙 | Documents, spreadsheets |
| Settings | 󰒓 | System settings, App Center, Web Apps |

Click a category or use <kbd>Tab</kbd> / <kbd>Shift+Tab</kbd> to move between the sidebar, search, and app list. Arrow keys navigate within each area.

### Source Badges

Each app shows a source badge indicating where it came from:

| Badge | Meaning |
|-------|---------|
| AUR | Installed from official repos or AUR |
| Flatpak | Installed via Flatpak |
| AppImage | Portable AppImage |
| Web App | Sandboxed web app created via Web App Center |

### How it works

- **[`smpl-os/smpl-apps/start-menu`](https://github.com/smpl-os/smpl-apps/tree/main/start-menu)** - Independently built Rust + Slint application. Reads the app index, resolves icons (SVG/PNG from hicolor, Flatpak exports, and user icon dirs), renders a GPU-accelerated UI.
- **`toggle-start-menu`** - wrapper script that toggles the menu open/closed. Manages focus capture (`stay_focused`, `pin`, temporary `follow_mouse=3`).
- **Hyprland window rules** - `float`, `move 2 (monitor_h-window_h-37)`, `animation slide left`, `opacity 1.0 override`.

### App Cache

The start menu reads from a pre-built app index at `~/.cache/smplos/app_index`. This is automatically rebuilt by a systemd path unit (`smplos-app-cache.path`) whenever `.desktop` files, Flatpak apps, or AppImages change. You can also rebuild manually:

```bash
rebuild-app-cache
```

Desktop entries are resolved by desktop-file ID: `$XDG_DATA_HOME/applications`
(default `~/.local/share/applications`) overrides `$XDG_DATA_DIRS` in order
(default `/usr/local/share:/usr/share`). A user `Hidden=true` or `NoDisplay=true`
entry also masks the system entry, even if its name differs. Flatpak exports
and AppImages remain included. Rebuilds are serialized and published atomically;
normal OS and app updates refresh the index even when no binary changed.
The cache stays at `~/.cache/smplos/app_index` for compatibility with existing
menu and legacy launcher consumers; `XDG_CACHE_HOME` does not relocate it.
The path watcher covers the default directories; after changes in custom XDG
directories, run `rebuild-app-cache` manually.

The menu binary's icon lookup and pin matching are released separately from
these scripts. See [application icon delivery](UPDATING.md#application-icon-delivery)
for the required release sequence and the independently packaged Grafium icon.

## GTK Theming & Credential Storage

smplOS configures the system so GTK dialogs (file pickers, VS Code popups, etc.) follow the dark/light theme automatically:

- **GTK settings.ini** - written during install for X11 fallback
- **dconf/GSettings** - written during install via `dbus-run-session` for Wayland (GTK on Wayland ignores `settings.ini`)
- **`theme-set`** - updates both `gsettings color-scheme` and `gtk-theme` on every theme switch

Credential storage (for VS Code, Brave, git, etc.) is fully configured:

- **gnome-keyring** - installed, started via Hyprland autostart, PAM-integrated for auto-unlock at login
- **VS Code argv.json** - pre-configured with `"password-store": "gnome-libsecret"` to eliminate the keyring detection dialog

## Notification Center

A custom notification center built with Rust and [Slint](https://slint.dev), accessible from the bell icon in the EWW bar. It reads dunst's notification history and displays cards with dynamic heights - long messages word-wrap naturally instead of being truncated.

**Open it:** Click the bell icon in the bar, or press <kbd>Super</kbd> + <kbd>N</kbd>.

### Features

- **Dynamic card layout** - each notification card grows to fit its content. No fixed heights, no wasted space.
- **Word-wrapped body text** - long notification bodies wrap cleanly instead of being clipped with an ellipsis.
- **Double-click to open** - double-click any notification to launch the associated app. Uses the desktop entry from dunst metadata, with a fallback to the app name.
- **Actionable notifications** - well-known notifications (like "System Update") map to specific commands. Double-click the System Update notification to open a full system update in your terminal.
- **Dismiss** - click the X button on any card to dismiss it.
- **Scrollable** - notifications overflow into a smooth-scrolling list.

### Architecture

```
dunst (notification daemon)
  +-- dunstctl history --> notif-center (Rust + Slint)
                              |-- Parses JSON history
                              |-- Maps app names to nerd font icons
                              |-- Maps summaries to actions (e.g. "System Update" -> smplos-update)
                              +-- Renders scrollable card list via Slint UI
```

## Dictation (Speech-to-Text)

smplOS ships with **fully offline speech-to-text** powered by [Voxtype](https://github.com/Vypxl/voxtype) and [Whisper](https://github.com/openai/whisper). The English `base.en` model (~150 MB) is bundled into the ISO — dictation works immediately on first boot with no internet connection.

**Toggle dictation:** <kbd>Super</kbd>+<kbd>Ctrl</kbd>+<kbd>X</kbd>

When active, a microphone icon appears in the EWW bar. Speak naturally and text is typed into the focused window via `wtype`.

### How It Works

```
dictation-toggle          Toggle the voxtype systemd user service on/off
       |
dictation-prime           (runs once) Primes HuggingFace cache from bundled model,
       |                  writes default config, creates+enables systemd service
       |
voxtype.service           Systemd user service — listens to mic, runs Whisper,
                          types results via wtype
```

- **`dictation-prime`** — Idempotent first-run script. Copies the bundled Whisper model from `/usr/share/smplos/models/whisper/base.en/` into the HuggingFace cache at `~/.cache/huggingface/hub/`, writes a default `~/.config/voxtype/config.toml`, and creates + enables the systemd user service. Runs automatically on first toggle or during post-install. Writes a marker file so subsequent calls are instant no-ops.
- **`dictation-toggle`** — Starts or stops the voxtype service. Calls `dictation-prime` on first use. Emits JSON status for the EWW bar listener.
- **`dictation-setup`** — Interactive setup wizard (uses `gum`). Pick from 100+ languages, choose a model size (tiny/base/small/medium/large), and download. Detects pre-installed state and skips redundant steps.

### Changing Language or Model

The bundled `base.en` model covers English. To switch to another language or a larger model:

```bash
dictation-setup
```

This opens an interactive picker. Larger models (small, medium, large) give better accuracy but use more RAM and are slower to transcribe.

### EWW Bar Integration

The quick-settings panel in the EWW bar shows a dictation pill with a themed microphone icon. Click it to toggle the service or long-press to open settings. The bar icon reflects the current state: filled mic when active, outline when inactive.

## System Updates

smplOS has a **git-based over-the-air update system**. The OS repo is cloned to `~/.local/share/smplos/repo/` on each machine. When you update, it pulls the latest changes and applies them — no re-imaging required.

Use **App Center → Update OS** for a full update. The terminal command is:

```bash
smplos-update
```

A full update runs through these stages:

1. **Bootstrap** — check external power, authenticate once, safely fast-forward upstream source, refresh and verify all updater commands/helpers.
2. **Pacman** — complete the official base upgrade, including compositor, libraries and drivers; unsupported stack versions stop the transaction.
3. **Required AUR** — enroll prebuilt Yay, then update foreign drivers, public shared libraries and dependencies of the core stack.
4. **Core desktop** — deliver smpl-apps, st, Nemo and micro; deploy essential configs/themes and core migrations, then verify the core before ordinary apps run.
5. **Optional apps** — attempt application configs/integrations, optional migrations, ordinary AUR apps and user/system Flatpaks.
6. **Final verification** — check core integrity again, save local reports, and publish the OS version when required work succeeds.

Ordinary app failures do not prevent core delivery or OS version completion.
They remain logged and retryable, with **Update complete with warnings** rather
than a false claim that every app updated. Required system/native/configuration
failures still produce **Update incomplete**. Official packages stay together in
one complete Arch transaction; the priority split never creates partial library
upgrades.

The update lock is released before the terminal's final Enter-to-close prompt
and reboot notification, so a completed window cannot masquerade as an active
update. If a verified update needs a reboot, **Update OS** instead explains
**Reboot required** and refuses another full update until restarting. Incomplete
update repairs and scripts-only enrollment remain available. Click the red
reboot notification to review restarting, then click the separate confirmation
to restart; dismissing either notification never reboots.
App Center releases supporting [per-update completion receipts](UPDATING.md#completion-receipts-and-app-center)
can offer **Restart App Center** after verifying completion and that their
installed executable actually changed. An already-running older App Center
still needs closing/reopening after its first successful native update.
Flatpak remote-fetch fallbacks refresh metadata and retry once; unresolved refs
remain visible optional warnings rather than a false claim that all apps updated.

Supported older Git-based updaters automatically stop their old runner and
reopen the current updater from the same button click; no separate enrollment
command is required. The first migration from a Polkit-based updater asks once
more for administrator authentication; subsequent updates authenticate once.
See [legacy handoff, compatibility limits and diagnostic reports](UPDATING.md#bringing-older-fleet-machines-onto-this-updater).

### What can be updated

| Component | How it's updated | Automatic? |
|-----------|-----------------|------------|
| Scripts (`/usr/local/bin/`) | Synced from repo on every update | ✅ |
| Themes | Reapplied automatically | ✅ |
| OS version | Bumped from `src/VERSION` | ✅ |
| Forked apps (start-menu, st, nemo, etc.) | Downloaded from GitHub releases | ✅ |
| System packages (pacman/AUR/Flatpak) | Standard package manager updates | ✅ |
| Breaking config changes | One-shot migrations in `migrations/` | ✅ |
| OS-owned EWW/Hyprland configs | Synced on every normal OS update | ✅ |
| User-owned configs (including idle preferences) | Preserved; focused migrations for known syntax changes | ✅ |

Power settings in `~/.config/hypr/hypridle.conf` survive OS updates, including
Never and custom durations. Updates bootstrap a missing file but do not replace
existing preferences with defaults. Known stock DPMS commands receive focused,
backed-up compatibility migrations; other Hyprland rules/modules still update
normally. See [power update behavior](UPDATING.md#power-preferences-and-command-compatibility)
for daemon application, deferred updates and the coordinated Settings release.

### Migrations

Breaking changes (upstream Hyprland renames, config format changes, etc.) are handled by **migration scripts** in `migrations/`. Each migration runs exactly once per user, is idempotent, and never deletes user data. Check status with:

```bash
smplos-migrate --list       # show all migrations and their status
smplos-migrate --pending    # show only pending migrations
smplos-migrate --pending --phase optional  # app work awaiting retry
```

For contributors: see [UPDATING.md](UPDATING.md) for how to write and ship updates.

## Building

The build system is designed to work on **first run, on any Linux distro**. It runs inside an Arch Linux container for reproducibility. The only host requirement is a container runtime — **Podman** (preferred, daemonless) or **Docker**.

### Quick Start

```bash
cd src && ./build-iso.sh
```

This produces a bootable Arch Linux ISO in `release/`. First build takes ~15-20 minutes (downloads packages); subsequent same-day builds reuse the package cache and finish much faster.

### Prerequisites

**Podman** is the preferred container runtime — it's daemonless and needs no background service. **Docker** works too and is auto-detected as a fallback.

If neither is installed, the build script will offer to install Podman automatically:

```
[WARN] No container runtime found (podman or docker)
Install Podman automatically? [Y/n]
```

To install Podman manually:

<details>
<summary><b>Arch / EndeavourOS / Manjaro / Garuda / CachyOS</b></summary>

```bash
sudo pacman -S --needed podman
```
</details>

<details>
<summary><b>Ubuntu / Debian / Pop!_OS / Linux Mint / Zorin</b></summary>

```bash
sudo apt-get update && sudo apt-get install -y podman
```
</details>

<details>
<summary><b>Fedora / Nobara</b></summary>

```bash
sudo dnf install -y podman
```
</details>

<details>
<summary><b>openSUSE</b></summary>

```bash
sudo zypper install -y podman
```
</details>

<details>
<summary><b>Void Linux</b></summary>

```bash
sudo xbps-install -y podman
```
</details>

> **No group setup needed.** The build script runs `sudo podman` automatically — `mkarchiso` requires real root for loop devices and mounts, so there's no rootless option regardless of runtime.

You also need **~10 GB of free disk space**. The script checks this and warns you if you're low.

### Build Options

```
Usage: build-iso.sh [EDITIONS...] [OPTIONS]

Editions (stackable):
    -p, --productivity      Office & workflow (LibreOffice, KeePassXC)
    -c, --creators          Design & media (OBS, Kdenlive, GIMP)
    -m, --communication     Chat & calls (Discord, Signal, Slack)
    -d, --development       Developer tools (VSCode, LazyVim, lazygit)
    -a, --ai                AI tools (Ollama, open-webui)
    --all                   All editions (equivalent to -p -c -m -d -a)

Options:
    --compositor NAME       Compositor to build (hyprland, dwm) [default: hyprland]
    -r, --release           Release build: max xz compression (slow, smallest ISO)
    -n, --no-cache          Force fresh package downloads
    -v, --verbose           Verbose output
    --skip-aur              Skip AUR packages (faster, no Rust compilation)
    --skip-flatpak          Skip Flatpak packages
    --skip-appimage         Skip AppImages
    -h, --help              Show this help
```

#### Common Workflows

```bash
# Base build (Hyprland, browser, terminal, file manager)
./build-iso.sh

# Productivity + Development
./build-iso.sh -p -d

# All editions
./build-iso.sh --all

# Fast iteration (skip AUR packages like EWW that take ages to compile)
./build-iso.sh --skip-aur

# Release build with max compression
./build-iso.sh --all --release

# Full verbose output for debugging
./build-iso.sh -v
```

### What the Build Does

1. **Checks prerequisites** - detects your distro, ensures Podman (or Docker) is installed, checks disk space, pre-authenticates `sudo`.
2. **Builds AUR packages** (unless `--skip-aur`) - compiles packages like EWW in a temporary container. Results are cached in `build/prebuilt/` so they only build once.
3. **Pulls `archlinux:latest`** - the build runs in a fresh Arch container for reproducibility.
4. **Downloads packages** - pacman downloads all packages into a dated local mirror. On Arch-based hosts, your system's pacman cache is mounted read-only for instant hits.
5. **Builds the ISO** - copies configs, themes, scripts, and the offline package mirror into an Arch ISO profile, then runs `mkarchiso`.
6. **Outputs** - the final `.iso` lands in `release/`. The full build log is saved to `.cache/logs/build-TIMESTAMP.log`.

### Caching

Builds use a **dated cache** (`build_YYYY-MM-DD/`) under `.cache/`. Same-day rebuilds reuse downloaded packages. Old caches are automatically pruned (keeps the last 3 days). To force a completely fresh build:

```bash
./build-iso.sh --no-cache
```

Custom packages such as `nemo-smpl` resolve the latest GitHub release on each
build. Cached package selection uses pacman's version ordering, including
epochs and package revisions, rather than filename order. Older archives can
remain cached without being selected by the ISO's offline repository or
installer. Do not use `--skip-aur` when building an ISO with `nemo-smpl`.

### Troubleshooting

| Problem | Solution |
|---------|----------|
| `sudo` password prompt mid-build | Expected — `mkarchiso` needs real root for loop devices and mounts. The script pre-authenticates `sudo` at startup and keeps it alive throughout the build. |
| DNS errors inside container | The build uses `--network=host`, so the container shares your host's network stack. If you still get DNS errors, check that your host can reach `archlinux.org` and that your firewall allows container traffic. |
| `no space left on device` | Need ~10 GB free. Run `podman system prune` (or `docker system prune`) to reclaim container disk space. |
| AUR build fails | Try `--skip-aur` to skip it. Pre-built AUR packages are cached in `build/prebuilt/` and reused on the next run. |
| Slow builds | First build downloads ~2 GB of packages. After that, the dated cache makes same-day rebuilds much faster. On Arch hosts, your system pacman cache is reused automatically. |
| Build log | All output is automatically saved to `.cache/logs/build-TIMESTAMP.log` for post-mortem inspection. |

### Development & Testing

See the [Development Guide](DEVELOPMENT.md) for hot-reload iteration, VM testing with QEMU, and how to extend smplOS (add settings entries, etc.).

## Themes

21 built-in themes. Press <kbd>Super</kbd> + <kbd>Shift</kbd> + <kbd>T</kbd> to open the theme picker and switch instantly.

Amber, Amber HUD, Catppuccin Mocha, Catppuccin Latte, Ethereal, Everforest, Flexoki Light, Frosted, Grafium, Gruvbox, Hackerman, Kanagawa, Matrix, Matrix HUD, Matte Black, Neon, Nord, Osaka Jade, Ristretto, Rose Pine, Tokyo Night.

One command - `theme-set <name>` - applies colors across the entire system: terminal, bar, notifications, compositor borders, lock screen, launcher, system monitor, editor, fish shell, Grafium, and browser chrome.

Grafium theme compatibility remains available for independently installed copies;
the app itself is not bundled or updated by the OS. Logseq is no longer selected
for AUR, Flatpak or AppImage builds. Updates remove Logseq's installed packages and
the OS-bundled AppImage without deleting existing graphs, preferences, plugins
or Flatpak application data. Theme switching no longer reads or changes Logseq.

For a full step-by-step authoring workflow, see [CREATING_MODIFYING_A_THEME.md](CREATING_MODIFYING_A_THEME.md).

### How It Works

The theme system is a **build-time template pipeline** plus a **runtime switcher**:

```
colors.toml --> regen-all-themes.sh --> templates + dedicated Nemo CSS
                  (alpha validation)             |
                                                 v
                                      theme-set publishes active files
                                      and notifies/reloads consumers
```

Each theme is a directory under `src/shared/themes/<name>/` containing:

| File | Source | Purpose |
|------|--------|---------|
| `colors.toml` | Hand-authored | Single source of truth - all colors and decoration variables |
| `btop.theme` | Generated | btop color scheme |
| `dunstrc.theme` | Generated | Dunst notification colors |
| `eww-colors.scss` | Generated | EWW bar/widget SCSS variables |
| `eww-colors.yuck` | Generated | EWW yuck variables (for SVG fills) |
| `fish.theme` | Generated | Fish shell syntax highlighting and pager colors |
| `foot.ini` | Generated | Foot terminal colors |
| `hyprland.conf` | Generated | Hyprland border colors, rounding, blur, opacity, shadow, glow |
| `niri-theme.kdl` | Generated | niri border colors and geometry |
| `hyprlock.conf` | Generated | Lock screen colors |
| `micro.theme` | Generated | Micro editor colors |
| `smplos-launcher.rasi` | Generated | Rofi native RGBA backgrounds and opaque foreground |
| `nemo.css` | Generated by Python | Nemo native controls, live light/dark contrast and capability-gated background alpha |
| `neovim.lua` | Hand-authored | Lazy.nvim colorscheme spec |
| `vscode.json` | Hand-authored | VS Code/Codium/Cursor theme name + extension ID |
| `icons.theme` | Hand-authored | Legacy metadata; stock value is `Adwaita` |
| `light.mode` | Hand-authored (optional) | Marker file - if present, GTK + browser use light mode |
| `tide.theme` | Hand-authored | Tide prompt colors (git, pwd, vi-mode segments) |
| `backgrounds/` | Hand-authored | Wallpapers bundled with the theme |
| `preview.png` | Hand-authored | Theme preview screenshot for the picker |

### colors.toml Reference

Every theme defines its values in a single `colors.toml` file. Core variables
are summarized here; see the [complete semantic palette guide](CREATING_MODIFYING_A_THEME.md).

#### Colors

| Variable | Description | Example |
|----------|-------------|---------|
| `accent` | Primary accent color (bar icons, active borders, highlights) | `"#89b4fa"` |
| `cursor` | Terminal cursor color | `"#f5e0dc"` |
| `foreground` | Default text color | `"#cdd6f4"` |
| `background` | Window/terminal background | `"#1e1e2e"` |
| `selection_foreground` | Text color in selections | `"#1e1e2e"` |
| `selection_background` | Background color of selections | `"#f5e0dc"` |
| `term_0` - `term_15` | Optional overrides for terminal slots derived from semantic roles | `"#45475a"` |

Terminal templates derive their palette from semantic roles such as `surface`,
`danger` and `fg_dim`. The separate legacy `theme-set-st` reader still uses
`colorN`; see the theme guide's audit limitations.

#### Decoration

| Variable | Default | Description |
|----------|---------|-------------|
| `rounding` | `"10"` | Window corner size in pixels (see `rounding_power` for the shape) |
| `app_rounding` | same as `rounding` | Circular corner radius in pixels for what Hyprland does not clip: the rofi launcher and dialogs, the Nemo quick preview and niri windows. A theme with `rounding_power = "1"` keeps it tiny (`neon`, `amber-hud`, `matrix-hud`: `"2"`) so that Hyprland's 45° cuts remain the corner shape |
| `blur_size` | `"6"` | Background blur kernel size |
| `blur_passes` | `"3"` | Number of blur passes (higher = smoother, more GPU) |
| `opacity_active` | `"1.0"` if absent | Third-party ordinary whole-window opacity, including text/icons. Stock values follow theme background intensity. |
| `opacity_inactive` | `"1.0"` if absent | Keep equal to active to avoid focus-dependent fading. |
| `app_background_opacity` | Explicit popup value, otherwise `"1.0"` | Background-only alpha for capable Nemo, Grafium Auto and regular smpl-apps. |
| `term_opacity_active` | `"0.85"` | st-wl **background-only** alpha. Text is always 100% opaque — only the background pixels carry this alpha in the ARGB surface. |
| `browser_opacity` | `"1.0"` | Opacity of browsers (Brave, Firefox, Chrome, etc.) |
| `messenger_opacity` | `"0.85"` | Opacity of messengers (Signal, Telegram, Slack, Discord, Teams, WhatsApp) |
| `popup_opacity` | `"0.60"` when absent during generation | Background alpha of popup-role apps (start-menu, notif-center, calendar), EWW popups and Rofi. |

Each opacity class is owned exactly once — no value is applied twice. See [Opacity Architecture](#opacity-architecture) for details.

#### Effects (optional, Hyprland only)

Every key may be omitted: absent keys give the classic look (small dark shadow, no glow, static borders), so existing themes are unchanged. Other compositors ignore these keys. `neon` is the reference theme (style `scifi`), `amber-hud` the one for the `panel` style and `matrix-hud` the one for the `matrix` style.

| Variable | Default | Description |
|----------|---------|-------------|
| `rounding_power` | `"2.0"` | Window corner shape, a number from 1 to 10. `2` is Hyprland's circular corner; `1` turns `rounding` into straight 45° cuts with legs of `rounding` / 2 − 1 px (rounded down: `rounding = "42"` cuts 20 px), so every window becomes an octagon (8 corners instead of 4) |
| `shadow_range`, `shadow_render_power` | `"2"`, `"3"` | Drop-shadow size and falloff sharpness |
| `shadow_color`, `shadow_color_inactive` | `"rgba(1a1a1aee)"`, same as active | Shadow tint. Hyprland shadows take a single color, not a gradient |
| `glow` | `"false"` | `"true"` draws an inner glow along the window edge |
| `glow_range`, `glow_render_power` | `"10"`, `"3"` | Glow depth and falloff sharpness |
| `glow_color`, `glow_color_inactive` | accent at 69% alpha, same as active | Single color or gradient, e.g. `"rgba(00f0ffb0) rgba(2f7bff80) 45deg"` |
| `border_animation` | `"false"` | `"true"` continuously rotates the border (and, on Hyprland 0.56+, glow) gradient. On its own only windows opened after the theme is applied animate; with `smpl-hud` only the focused window turns |
| `hud_frame` | `"false"` | `"true"` turns on HUD frames, drawn by the `smpl-hud` Hyprland plugin: a chamfered, glowing outline just outside every window, with corner brackets and edge tabs (`scifi`), notches, circuit traces and running dots (`panel`) or a plain outline at the window's edge with three columns of Matrix characters falling beside each side and glows drifting along its top and bottom (`matrix`) |
| `hud_hide_border` | `"false"` | `"true"` hides Hyprland's own border so that the frame's outline is the only line (the generator gives Hyprland a border size of 0, and `border_size` stays what compositors without the frame draw; `matrix-hud` uses it). Needs `hud_frame = "true"`; without the plugin such a theme has no border line |
| `hud_style` | `"scifi"` | Which HUD look the plugin draws: `scifi` (outline, halos, corner brackets, edge tabs), `minimal` (outline and halos only), `panel` (notched outline with a step, a ghost line and a cut corner, circuit traces ending in beads, and dots that run along the lines) or `matrix` (the same outline as one line with its glow, Matrix characters falling beside both sides in three columns on each, each further one smaller, dimmer and softer, and glows drifting along the top and the bottom). Lowercase letters, digits, `-` and `_`; an unknown name shows a notification and draws nothing |
| `hud_gap`, `hud_chamfer` | `"5"`, `"10"` | Pixels between the window edge and the outline, and the size of its 45° corner cuts. With `rounding_power = "1"` the outline stays concentric with the window's own cuts, so `hud_chamfer` only sets a minimum. The notches of a `panel` or `matrix` frame are 9 px deep with a `hud_gap` of 13 or more, shrink below that and are gone under 7 (`matrix-hud` uses `"3"`: a plain outline right at the window's edge) |
| `hud_line_width` | `"3"` | Thickness of the outline in pixels, a number from 1 to 9.99. Corner brackets and edge tabs follow it |
| `hud_float_glow_range` | `"0"` | Floating windows glow brighter than tiled ones and their halo reaches at least this many pixels; `"0"` keeps the style's own reach (14 px for `scifi`) |
| `hud_sweep` | `"false"` | `"true"` lets a soft glow drift slowly along the focused window's outline, in the outline's own colours (in the `panel` style it also sets the dots running along the lines, in the `matrix` style the falling characters and the drifting glows) |
| `hud_sweep_speed`, `hud_sweep_length` | `"80"`, `"180"` | How fast the glow travels, in px per second (10 to 400; the dots of a `panel` run 0.8 times as fast and the characters of a `matrix` fall 0.6 times as fast), and how long it is along the line, in px (40 to 600; the longest a glow of a `matrix` gets) |
| `hud_glyph_color` | `"none"` | `"rgb(rrggbb)"` (hex digits, no `#`) or `"none"`: the colour of the characters of a glyph style such as `matrix` and of its lamps; their heads and glow are derived from it (the heads are the same colour lightened). `"none"` gives them the colours of the outline and its glow (`matrix-hud` uses `"rgb(3cff28)"`, a yellower green than its outline). Styles without characters ignore it |
| `hud_side_opacity` | `"1"` | A decimal from `"0"` to `"1"`: how visible the outline of a `panel` or `matrix` frame is down its left and right sides, its halo beside it with it, the corners fading between that and the top and the bottom edge's (`hud_edge_opacity`). A theme whose characters fall there dims it so that they stand out (`matrix-hud` uses `"0.1"`, almost unseen); `"1"` is as strong as the rest. The ring styles ignore it |
| `hud_edge_opacity` | `"1"` | A decimal from `"0"` to `"1"`: the same along the top and the bottom edge of a `panel` or `matrix` frame. `"1"` is the full line; `matrix-hud` uses `"0.1"`, as dark as its sides, and leaves the light to its lamps and its underglow. The ring styles ignore it |
| `hud_underglow` | `"0"` | A decimal from `"0"` to `"1"`: how bright a glow is along the top and the bottom edge of a `panel` or `matrix` window that fades out away from it, as if the light shone from under the window (an opaque window hides the half of it that lies under it; a see-through one shows it). It has no line of its own and is as still as the outline. `matrix-hud` uses `"0.3"`; `"0"` has none. The ring styles ignore it |
| `hud_scanner` | `"0"` | `"0"` (none) or an integer from `"24"` to `"160"`: the width in px of a small animated scanner in the bottom right corner of every framed window, like the radar of a space game: a flat disc seen at a slant with three rings, the ship in the middle and an arm that sweeps round and lights the contacts it passes. In a `panel` frame the outline bulges out into a pod to hold it, in place of the bottom right cut, and the dots that circle the outline skirt the pod; elsewhere it stands in the corner of the window. It is painted over the window's content in the colours of the frame, moves only in the focused window (the others show it dimmed, where it stopped), steps aside while the pointer is near it, and is left out of fullscreen and unframed windows and of windows smaller than five times its size. Its animation is a loop of 22 s whose frames are made once and shared by every window (about 10 MiB of GPU memory), which adds roughly 0.2 to 0.5 % of one CPU core while a window has focus. `amber-hud` uses `"72"` |
| `hud_scanner_blur` | `"true"` | `"true"` or `"false"`: whether the glass of the scanner's pod blurs what lies under it, as a translucent window does. It blurs only while the compositor's own blur (`decoration:blur:enabled`) is on and `xray` is off; with `"false"`, or without a pod, the glass is flat and more opaque, which also costs a little less. `amber-hud` uses `"true"` |

`glow`, `border_animation`, `hud_frame`, `hud_hide_border`, `hud_sweep` and `hud_scanner_blur` must be `"true"` or `"false"` (`hud_hide_border` needs `hud_frame = "true"`), `hud_gap`, `hud_chamfer` and `hud_float_glow_range` must be non-negative integers, `hud_sweep_speed` and `hud_sweep_length` integers inside their ranges, `hud_line_width` a number from 1 to 9.99, `hud_style` a style name, `hud_glyph_color` `"none"` or `"rgb(rrggbb)"`, `hud_side_opacity`, `hud_edge_opacity` and `hud_underglow` a decimal from 0 to 1, `hud_scanner` `0` or an integer from 24 to 160 and `rounding_power` a number from 1 to 10; the generator rejects anything else. The glow is painted inside the window edge, over its content, so keep it short and translucent.

Hyprland has a single global `glow_range`, so it cannot give floating windows a deeper glow than tiled ones. `neon` sets `glow_range = "12"` and `hud_float_glow_range = "24"`; without the plugin loaded, floating windows simply keep 12 px.

**Frame and glow take different colors.** The window border and the plugin's outline, corner brackets and edge tabs use `border_active` / `border_inactive`; the shadow, the native inner glow and the halos the plugin paints around its outline use `glow_color` / `glow_color_inactive` and `shadow_color`. Choosing a related but different hue for the glow (`neon`: a cyan-to-azure frame, a violet glow) keeps the frame crisp and lets the glow read as light spilling around it.

#### HUD frames (`smpl-hud` plugin)

Hyprland draws every window as a rectangle with rounded or, with `rounding_power = "1"`, 45°-cut corners and a plain border, so the sci-fi frame is drawn by `smpl-hud`, a Hyprland plugin ([`src/compositors/hyprland/plugins/smpl-hud`](src/compositors/hyprland/plugins/smpl-hud/README.md), C++). It is a window decoration inside the compositor's own render pass: it moves, resizes, animates and stacks together with its window, so it never lags behind, and it adds no surfaces and never touches input. With `hud_frame = "true"` it paints, around every ordinary window, an outline that follows the window's cuts at a constant distance, halos on both sides of it and (style `scifi`) corner brackets and mid-edge tabs, in the window's own border and glow gradients, so focus changes and `border_animation` carry over (only the focused window's gradients turn; the others finish their lap and rest). It reads the `hud_*` keys from the generated `~/.config/hypr/theme.conf` and picks up a change on the next Hyprland config reload (`theme-set` triggers one); a theme without `hud_frame = "true"` draws nothing. Neighbouring tiled outlines sit `2 * (gaps_in + border) - 2 * hud_gap` apart, where `border` is `border_size`, or 0 with `hud_hide_border` (Hyprland then draws no border): that has to exceed `hud_line_width` so the lines do not touch, and should reach `hud_line_width + 13` so their halos stay separate (`neon`: `gaps_in = "18"` leaves 28 px; `amber-hud`: `gaps_in = "24"` with a `hud_gap` of 15 leaves 22 px; `matrix-hud`: `gaps_in = "28"` and a `hud_gap` of 3 with its border hidden leave 50 px, the room the three columns of characters on each side of the gap need).

With `hud_sweep = "true"` a soft glow also drifts around the focused window's outline, past corners and cuts, in the outline's own gradient colours, fading in over half a second when a window gets focus and out when it loses it. It is deliberately cheap: one small sprite, rebuilt about 20 times a second only while it moves, with damage limited to the few pixels it leaves and enters (no full-window or full-screen redraws), so it costs about one percent of a CPU core in a software-rendered test compositor however many windows are open, and it stops for hidden windows, fullscreen windows, sleeping monitors and the lock screen. The outline of the ring styles follows the window's `rounding` and `rounding_power`, so a theme gets chamfered (`1`), circular (`2`) or squircle (`4` and up) frames without further work; another outline needs a new style in the plugin ([README](src/compositors/hyprland/plugins/smpl-hud/README.md#styles)).

The `panel` style (`amber-hud`) draws a fixed outline of straight and 45° lines instead: chamfered corners, a notch and a step on the top edge, a raised line and a fading ghost line along the bottom, a bigger cut at the bottom left and three circuit traces ending in glowing beads, all standing `hud_gap` off the window. With a `hud_scanner`, the bottom right corner is a pod round the scanner instead of a cut, and the dots skirt it. While a window has focus, dots run along its outline and traces, at 0.8 times `hud_sweep_speed`, and fade with the travelling glow; two dots that pass each other swell and brighten for a moment. The window itself stays a chamfered rectangle: the shape lives in the lines around it, and the bottom-left cut can only be as deep as the window's own corner cut. Because the compositor can only draw textured quads, each line is baked once into a small image kept in a GPU cache, so a panel costs next to nothing between changes. It needs room: a frame under 480 × 160 logical px, or a `hud_gap` under 7, gets a plain chamfered outline with two dots, and the notches reach their full 9 px at a `hud_gap` of 13. Keep `border_animation` off in a panel theme, since a turning gradient recolours, and so repaints, every line. `make preview` in the plugin draws a panel as an image without a compositor.

The `matrix` style (`matrix-hud`) keeps the panel's outline and nothing else of its line work: one line with its glow, which with a `hud_gap` of 3 hugs the window as a plain chamfered outline. `hud_hide_border = "true"` hides Hyprland's own border and the theme turns its glow and shadow off, so the plugin's outline and halo are all there is. Matrix characters fall down the left and right edges in three columns on each side: the first on the line itself, as if the characters slid along it, the second tucked partly under it, beyond it and inside its glow, and the third under that, each smaller, dimmer and softer than the one before (the second half as tall, the third a third as tall and only a faint haze), which makes them look further and further away. They are sixty half-width katakana, digits and signs, each drawn from a few strokes (no font is involved), mirrored like the film's and given the line's own bright core and a slight glow of their own. Each fall is a bright head with a tail of characters fading behind it, going from the top to the bottom and pausing before it starts again; every pass has a tail of its own length, from short to long. The rain is as slow as the glows along the top and the bottom (a few rows a second at the theme's speed), so that it stays at the edge of the eye and does not draw it from the work. Along the top and the bottom, up to two ellipses of light per edge drift slowly to and fro and pulse, in the green of the characters, over a soft glow along the window's own edge that seems to shine from under the window (`hud_underglow = "0.3"`; an opaque window hides the half of it that lies under it and a see-through one shows it). The line itself is almost unseen, so that the characters and these lights are what the eye sees: down the two sides (`hud_side_opacity = "0.1"`) and along the top and the bottom (`hud_edge_opacity = "0.1"`), the corners fading between the two. Only the focused window moves; the others keep their outline, halo and underglow. Characters never move: they light up, change and fade where they stand, so each look is a small image baked once into the same GPU cache, and only the characters whose step changed, and the pixels a glow leaves and enters, are repainted, about 20 times a second at most. Every repainted character is one draw of a cached image (about 25 µs of the compositor's time): a focused full-HD window with all three columns repaints roughly 180 of them at each step, which comes to around 9 % of one core, against roughly 5 % with two columns, and the windows that are not focused cost nothing per step. That is why the third column, a mere haze, has only a few falls. Frames that are small, or have a `hud_gap` under 7, get the plain chamfered outline, as the panel does. Keep `hud_sweep = "true"` in a matrix theme, since every moving part is driven by it (`"false"` leaves the outline and its halo), and `border_animation` off. Without the plugin a theme that hides the border has no border line at all.

**Floating windows.** Hyprland places a floating window by its box alone, so a window that a rule puts against a screen edge (the start menu, the notification centre, Signal), one made floating with `Super+T` at a size its monitor cannot hold, or one sent to a smaller monitor would lose part of its frame and halo beyond the screen. `smpl-hud` keeps each floating window's whole frame inside its monitor's usable area (the monitor less what bars reserve) at the moments a window is placed: when it opens, when it becomes floating, when it is moved to another workspace or monitor and, for the windows already open, when the plugin loads or a theme change makes the frame wider. It moves the window in from the edge by the frame's reach and shrinks it only if it cannot fit otherwise. A window that already fits is not touched, and nothing is checked after you move or resize a window yourself, so you can still put one half off-screen on purpose. A script that puts a window at a position of its own (the messenger toggle pins Signal into the corner of the monitor) calls `hyprctl smplhud fit <window address>` afterwards to get the same placement. Tiled windows are placed by the layout inside the margin `gaps_out` leaves, so keep `gaps_out` at least as wide as the frame's reach for the frames of windows at the screen edge to show whole.

**Delivery.** A Hyprland plugin only loads into the exact Hyprland build it was compiled against, so smplOS compiles its plugins (`smpl-hud` and `smpl-scroll`) against the Hyprland it ships instead of shipping a binary. The ISO build compiles them against the bundled Hyprland package, so the live session and the installed system have them; Update OS rebuilds them after a Hyprland update and swaps them into the running session; every login runs `smplos-plugins load`, which loads the binaries that match the running compositor. If none matches, for example Hyprland was just updated and the rebuild failed, windows keep Hyprland's own cut corners, border, glow and shadow (and columns Hyprland's width limit) and a one-time notification says so; run Update OS again to retry. A plugin that crashes Hyprland cannot lock you out: `start-hyprland` relaunches it in safe mode, which skips the user config and with it the loader.

```bash
smplos-plugins status               # installed builds, their Hyprland ABI keys, what is loaded
smplos-plugins load                 # load the build that matches the running Hyprland
smplos-plugins unload               # switch the frames off for this session
smplos-plugins sync [--rebuild]     # rebuild from source for the installed Hyprland
```

Limits: Hyprland only; fullscreen windows, X11 override-redirect windows (menus, tooltips) and windows under 40 px get no frame, because Hyprland draws no decorations on them or they are too small to carry one.

#### App Theme Selectors (single-file control)

Each `colors.toml` can also choose which app-specific preset to use:

| Variable | Description | Example |
|----------|-------------|---------|
| `app_theme_nvim` | Which theme's `neovim.lua` preset to apply | `"tokyo-night"` |
| `app_theme_vscode` | Which theme's `vscode.json` preset to apply | `"tokyo-night"` |

By default, each built-in theme points these to itself. You can mix and match (e.g. keep `colors.toml` from one theme but reuse VS Code preset from another).

#### Example: Catppuccin Mocha

Excerpt; copy the complete shipped palette when creating a theme:

```toml
accent = "#89b4fa"
cursor = "#f5e0dc"
foreground = "#cdd6f4"
background = "#1e1e2e"
selection_foreground = "#1e1e2e"
selection_background = "#f5e0dc"

rounding = "8"
blur_size = "14"
blur_passes = "3"
opacity_active = "0.50"
opacity_inactive = "0.50"
browser_opacity = "0.50"
messenger_opacity = "0.50"
popup_opacity = "0.50"
app_background_opacity = "0.50"
```

### Template System

Templates live in `src/shared/themes/_templates/` and use `{{ variable }}` placeholders.

The generator provides three variants of each color variable:

| Variant | Example input | Output | Use case |
|---------|--------------|--------|----------|
| `{{ accent }}` | `"#89b4fa"` | `#89b4fa` | CSS, config files |
| `{{ accent_strip }}` | `"#89b4fa"` | `89b4fa` | Hyprland `rgb()`, btop, foot |
| `{{ accent_rgb }}` | `"#89b4fa"` | `137,180,250` | Hyprlock `rgba()` |

### Creating a New Theme

1. **Create the directory:**
   ```bash
   mkdir src/shared/themes/my-theme
   ```

2. **Write `colors.toml`** with all color and decoration values. Copy an existing theme as a starting point:
   ```bash
   cp src/shared/themes/catppuccin/colors.toml src/shared/themes/my-theme/
   ```

3. **Add optional hand-authored files:**
   - `neovim.lua` - Lazy.nvim colorscheme plugin spec
   - `vscode.json` - `{"name": "Theme Name", "extension": "publisher.extension-id"}`
   - `icons.theme` - legacy icon metadata (`Adwaita`); palettes no longer select icon packs
   - `light.mode` - Create this empty file if the theme is light
   - `backgrounds/` - Add wallpapers (named `1-name.png`, `2-name.png`, etc.)
   - `preview.png` - Screenshot for the theme picker

4. **Generate configs:**
   ```bash
   cd src && bash regen-all-themes.sh && bash regen-all-themes.sh --check
   ```
   This validates native alpha, expands the templates, and generates Nemo CSS.
   The check compares temporary outputs without rewriting your working tree.

5. **Test it:**
   ```bash
   theme-set my-theme
   ```

### What theme-set Does

When you run `theme-set <name>`, it:

1. Resolves the theme (user themes in `~/.config/smplos/themes/` take precedence over stock themes)
2. Stages a complete theme, replaces `~/.config/smplos/current/theme/`, and only then records the selected name. Switches are serialized; an old root-owned theme is preserved in a recovery directory rather than blocking the switch.
3. Copies pre-baked configs to their target locations:
   - `eww-colors.scss` -> `~/.config/eww/theme-colors.scss`
   - `nemo.css` -> `~/.config/smplos/nemo-theme.css` (both this and the EWW palette publish by atomic rename)
   - `hyprland.conf` -> `~/.config/hypr/theme.conf`
   - `hyprlock.conf` -> `~/.config/hypr/hyprlock-theme.conf`
   - `foot.ini` -> `~/.config/foot/theme.ini`
   - `btop.theme` -> `~/.config/btop/themes/current.theme`
   - `fish.theme` -> `~/.config/fish/theme.fish`
   - `tide.theme` -> applied via `fish -c "source ...; tide reload"`
   - `dunstrc.theme` -> composed with `dunstrc.base` into `~/.config/dunst/dunstrc`
   - `neovim.lua` -> `~/.config/nvim/lua/plugins/colorscheme.lua`
4. Bakes accent/fg colors into SVG icon templates for the EWW bar
5. Sets the wallpaper from `backgrounds/`
6. Refreshes supported consumers (not every application can reload live):
   - EWW bar: `bar-ctl reload` (re-compiles SCSS without killing the bar)
   - Hyprland: `hyprctl reload`
   - st/st-wl: OSC escape sequences (live, no restart)
   - Foot: `SIGUSR1`
   - Fish: sources `theme.fish` in all running sessions
   - Tide prompt: `tide reload` (updates git, pwd, vi-mode segment colors)
   - Dunst: `dunstctl reload`
   - btop: `SIGUSR2`
   - Nemo and native smpl-apps: watch/reopen atomically replaced theme files
   - Grafium Auto: watches active theme content and directory replacement
   - GTK: `gsettings` (dark/light mode)
   - Brave/Chromium: managed policy + flags file

Full OS updates replace bundled theme trees and matching personal overrides
with the latest stock contents, removing obsolete files. Changed installed
themes receive verified backups in `~/.local/state/smplos/theme-backups/`;
custom-only theme names remain untouched. Legacy Logseq CSS and selector
assets are inert compatibility files, not an active integration.

### Opacity Architecture

Owned native apps apply alpha only to background paint. Their compositor
multiplier is neutral, so foregrounds do not fade. Third-party ordinary apps,
including browsers/messengers, intentionally receive whole-window theme alpha.
Their text/icons fade too; stock focused/unfocused values are equal.

#### Opacity classes (tags)

| Class | Tag | Who controls opacity | `colors.toml` key |
|-------|-----|----------------------|-------------------|
| Foreign regular apps | *(untagged)* | Hyprland whole-window theme multiplier | `opacity_active` / `opacity_inactive` |
| Browsers | `chromium-based-browser` / `firefox-based-browser` | Hyprland compositor | `browser_opacity` |
| Messengers | `messenger` | Hyprland compositor | `messenger_opacity` |
| smplOS Rust popups | `self-managed-alpha` | App itself (Slint ARGB surface) | `popup_opacity` |
| Regular smpl-apps, capable Nemo, Grafium Auto | `self-managed-alpha` | Native background paint only | `app_background_opacity` |
| Rofi windows | `self-managed-alpha` | Rasi RGBA background | `popup_opacity` |
| Terminals | `self-managed-alpha` | App itself (st ALPHA_PATCH per-pixel) | `term_opacity_active` / `term_opacity_inactive` |
| Known media, games, PiP / fullscreen | `compositor-opaque` or final direct matcher | Hyprland compositor (forced 1.0) | — |

#### Why `self-managed-alpha` windows use `1.0 override`

Slint, capable Nemo, Grafium Auto, Rofi and st render their own semi-transparent
background pixels. If the compositor also applies opacity, the two multiply,
and even an opaque text pixel becomes translucent:

```
background: 0.85 (app alpha) * 0.85 (compositor) = 0.7225
text:       1.00 (app alpha) * 0.85 (compositor) = 0.85 (incorrect)
```

To prevent this, all `self-managed-alpha` windows receive `opacity 1.0 override` from Hyprland, so the compositor passes pixels through untouched and the app's ARGB alpha is the sole controller.

`opacity-policy.lua` / `.conf` loads last, after browser and messenger rules,
and protects native/media/fullscreen surfaces with neutral active, inactive
and fullscreen multipliers. This removes added whole-window fading, not an
app's existing per-pixel alpha. Unknown windowed media/games need a matching
class/content type or an explicit `compositor-opaque` tag.

Opacity rules also match `class = ".*"` when their role is selected by tag,
content or fullscreen state. This is an intentional dependency, not redundant
filtering: Hyprland 0.56 replays class rules on title changes and can otherwise
reapply ordinary alpha without replaying a tag-only exemption. Check window
`opacity`, `opacity_inactive` and `opacity_fullscreen` with `hyprctl getprop`;
global decoration opacity and the presence of a tag alone are not proof.

#### Per-app messenger overrides

All messengers default to `messenger_opacity` from the active theme, but individual apps can be pinned to a specific value by uncommenting the override lines in `windows.conf`:

```properties
# windowrule = opacity 0.70 override 0.70 override, match:class ^(signal)$
# windowrule = opacity 0.80 override 0.80 override, match:class ^(brave-teams\.microsoft\.com)(.*)$
```

These lines come *after* the tag-level rule, so they win (Hyprland last-match-wins). No theme rebuild needed — reload Hyprland config with `hyprctl reload`.

#### Adding a new Slint app

If you add a new Rust/Slint app, give it the proper shared regular/popup role
and add its verified native app ID to `self-managed-alpha` in **both**
`windows.lua` and `windows.conf`:

```properties
windowrule = tag +self-managed-alpha, match:class ^(my-new-app)$
```

The `opacity 1.0 override` rule then protects its foreground. Background paint
and live file-replacement handling must still be implemented in the app;
tagging an opaque buffer cannot make only its background transparent.

## License

MIT License. See [LICENSE](LICENSE) for details.

Terminal emulators (st, st-wl) are under their own licenses - see their respective directories.

---

## 🏅 Contributors

Thanks to everyone who has contributed to smplOS!

[![Contributors](https://contrib.rocks/image?repo=KonTy/smplos)](https://github.com/KonTy/smplos/graphs/contributors)

## 📊 GitHub Stats

![Stars](https://img.shields.io/github/stars/KonTy/smplos?style=for-the-badge&color=%230567ff)
![Forks](https://img.shields.io/github/forks/KonTy/smplos?style=for-the-badge&color=%2300b4d8)
![Issues](https://img.shields.io/github/issues/KonTy/smplos?style=for-the-badge&color=%23e63946)
![Last Commit](https://img.shields.io/github/last-commit/KonTy/smplos?style=for-the-badge&color=%2338b000)
![License](https://img.shields.io/github/license/KonTy/smplos?style=for-the-badge&color=%23a855f7)
![Repo Size](https://img.shields.io/github/repo-size/KonTy/smplos?style=for-the-badge&color=%23f97316)
