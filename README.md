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
</p>

<p align="center">
  <strong>Latest release: v0.6.0</strong>
  &nbsp;&bull;&nbsp;
  <a href="https://archive.org/download/smplos_260313-0458/smplos_260313-0458.iso"><strong>⬇ Download Base ISO</strong></a>
</p>

---

## What's new in v0.6.0

- **Offline dictation out of the box.** The Whisper `base.en` speech-to-text model (~150 MB) is bundled into the ISO and primed into the HuggingFace cache on first boot. Press <kbd>Super</kbd>+<kbd>Ctrl</kbd>+<kbd>X</kbd> to start dictating immediately — no internet, no downloads, no setup. Run `dictation-setup` to switch languages or model sizes later.
- **Language Settings (kb-center) — Dictation tab.** kb-center now has a full Dictation tab for setting up speech-to-text via Voxtype/Whisper. Pick a language, choose a model size, and install with a single click. Supports 100+ languages, English-alongside mode, 3-tier package fallback (pacman, paru, manual PKGBUILD), and live progress tracking. The keyboard tab is unchanged.
- **Fix post-install black screen on Hyprland 0.54+.** Hyprland migrated from wlroots to the Aquamarine backend, silently breaking `WLR_NO_HARDWARE_CURSORS` and `WLR_RENDERER_ALLOW_SOFTWARE` env vars. The VM cursor workaround now uses the native `cursor:no_hardware_cursors` config option. Fixes black screen after login in QEMU/VirtualBox.
- **Transparent kb-center.** Added `no-frame: true` and proper alpha background to the Language Settings window, matching all other Slint apps.
- **Dictation quick-settings pill.** EWW bar quick-settings panel shows a dictation status pill with themed mic SVG — toggle the service or jump to settings.
- **Dictation keybinding.** <kbd>Super</kbd>+<kbd>Ctrl</kbd>+<kbd>X</kbd> toggles dictation globally (matches Omarchy).
- **AUR package auto-build fallback.** The ISO builder now automatically builds any missing AUR package from source if no prebuilt `.pkg.tar.zst` is found — no manual pre-compilation required.
- **Logseq theme fix.** Theme switching now works on fresh installs where `~/.logseq/` doesn't exist yet.
- **Neovim live theme reload.** `theme-set` now broadcasts colorscheme changes to all running Neovim instances via `--remote-expr` over server sockets.

---

## What was new in v0.5.0

- **Transparent GUI apps** — All Rust/Slint apps (notif-center, kb-center, disp-center, start-menu, webapp-center) now use the software renderer, enabling proper alpha transparency and blur through Hyprland. Previously only app-center had working transparency.
- **Reliable Hyprland session startup** — greetd now launches via the real `start-hyprland` watchdog binary, which restarts Hyprland in safe mode on crash instead of leaving a black screen.
- **Faster dev iteration** — `build-apps.sh` skips the container entirely for apps whose git tree hash hasn't changed since last build.

---

## What is smplOS?

smplOS is a minimal Arch Linux distro built around one idea: **simplicity**.

It started as an attempt to build a lighter version of Omarchy - same keybindings, same themes, but without the bloat. That contribution was rejected, so we forked and built our own distro. Along the way we rewrote most of the stack: a [suite of lightweight GUI apps in Rust](#rust-app-suite), a [patched suckless terminal](#terminal-st-wl) that renders inline images at a fraction of Kitty's footprint, a cross-compositor architecture, and a theme system that touches every app on the desktop. What came out the other side isn't Omarchy lite - it's a different OS.

### Why smplOS?

- **Lightweight.** Under 800 MB of RAM on a cold boot (Omarchy idles at 1.7 GB). Every package earns its place.
- **Fast installs.** Fully offline - no internet required. A fresh install completes in under 2 minutes.
- **Cross-compositor.** Built from the ground up to support multiple compositors. Hyprland (Wayland) ships first, [DWM (X11) is next](DWM-X11.md). Shared configs, shared themes, shared keybindings - the compositor is just a thin layer.
- **One UI toolkit.** EWW powers the bar, widgets, and dialogs. It runs on both X11 and Wayland. No waybar, no polybar, no redundant tools.
- **14 built-in themes.** One command switches colors across the entire system - terminal, bar, notifications, borders, lock screen, and editor.

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

#### Themes

smplOS ships with 14 themes inherited and expanded from the Omarchy project. A single `theme-set` command applies colors system-wide - terminal, EWW bar, notifications, Hyprland borders, lock screen, btop, neovim, and VS Code. Every theme includes matching wallpapers and is generated from a single `colors.toml` source of truth.

<a href="images/5-themes.png"><img src="images/5-themes.png" width="720" /></a>

#### Keybindings

smplOS uses the same keybindings as [Omarchy](https://omakub.org/), so migrating from that project is seamless - your muscle memory carries over. Press <kbd>Super</kbd>+<kbd>K</kbd> to open the keybinding cheatsheet overlay at any time. The overlay is **dynamically generated** by parsing `bindings.conf` at runtime, so any keybinding you add or change shows up in the help automatically - no manual docs to maintain.

<a href="images/6-keybindings.png"><img src="images/6-keybindings.png" width="720" /></a>

---

### Rust App Suite

Linux has no shortage of CLI tools, but when it comes to graphical settings panels that are lightweight, Wayland-native, and theme-aware, the options are slim. Most existing tools are either GTK/Qt monoliths that pull in hundreds of megabytes, Electron wrappers, or they just don't exist for tiling Wayland compositors. So we wrote our own.

The smplOS app suite is a set of purpose-built GUI apps written in **Rust** with the **Slint** UI framework. Each app is a single static binary under 5 MB, starts in milliseconds, integrates with the smplOS theme system, and works on both X11 and Wayland. They replace functionality that mainstream desktops take for granted but that tiling WM users have historically gone without.

#### Notification Center

A notification hub that collects and groups desktop notifications by app. Supports dismiss, clear-all, and scrollable history. Integrates with Dunst over D-Bus. We built this because every existing notification center was either Electron-based (heavy), GNOME-only, or lacked grouping. Ours idles at under 10 MB of RAM.

<a href="images/3-notif-center.png"><img src="images/3-notif-center.png" width="720" /></a>

#### Display Manager

A graphical display configuration panel. Detects connected monitors via Hyprland IPC, shows resolution, refresh rate, scale, and position for each display, and lets you apply changes live. No external dependencies - just `hyprctl` under the hood. Replaces the need for `wlr-randr` CLI or a full KDE/GNOME settings app just to rearrange monitors.

<a href="images/7-displaymgr.png"><img src="images/7-displaymgr.png" width="720" /></a>

#### Keyboard Manager

A keyboard layout and input configuration panel with two tabs. The **Keyboard** tab shows active layouts, lets you add/remove languages, and includes a live key-cap preview that updates as you switch layouts. The **Dictation** tab sets up speech-to-text via Voxtype/Whisper — pick a language, choose a model size, and install with one click. English (`base.en`) works offline out of the box — the model is bundled into the ISO. Supports 100+ languages, 3-tier package fallback, and live progress. All changes are applied live via `hyprctl keyword`.

<a href="images/8-keyboard.png"><img src="images/8-keyboard.png" width="720" /></a>

---

### Design Decisions

Every tool in smplOS was chosen to work across compositors (Wayland and X11) so the OS feels identical regardless of which one you run.

| Component | Choice | Why |
|-----------|--------|-----|
| **Bar & widgets** | EWW | GTK3-based, runs natively on both X11 and Wayland. One codebase for bar, widgets, theme picker, and keybind help. Replaces waybar and polybar. |
| **Start Menu** | Rust + Slint | Native GPU-rendered app launcher with categories, search, source badges (AUR/Flatpak/AppImage/Web App), and Settings tab. Theme-aware, keyboard-driven, under 5 MB. |
| **Terminal** | st / st-wl | Suckless st has an X11 build and a Wayland port (marchaesen/st-wl). Same config.h, same patches, same look. Starts in ~5ms and uses ~4 MB of RAM - critical for staying under the 850 MB cold-boot target. |
| **Notifications** | Dunst | Works on both X11 and Wayland with the same config. Lightweight, themeable, no dependencies on a specific compositor. |

The rule is simple: if a tool only works on one display server, it doesn't ship in `src/shared/`. Compositor-specific code stays in `src/compositors/<name>/` and is kept as thin as possible.

### Editions

smplOS ships in focused editions that **stack on top of each other**. Pick the ones you need - they all merge cleanly:

| Flag | Edition | Focus | Example apps |
|------|---------|-------|-------------|
| `-p` | **Productivity** | Office & workflow | Logseq, LibreOffice, KeePassXC |
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

---

## Download

**smplOS v0.6.0 — Base edition** (browser, terminal, file manager, full native app suite — under 800 MB RAM at idle)

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

### Themes

Switch the system theme (terminal, bar, borders, lock screen, editor) with a single command:

```bash
theme-set catppuccin     # or: dracula, nord, gruvbox, rose-pine, ...
```

Or open the theme picker from the start menu's Settings tab.

---

## Architecture

smplOS separates shared infrastructure from compositor-specific config. The goal is maximum code reuse - compositors are a thin layer on top of a shared foundation.

```
src/
  build-iso.sh              Entry point — detects Docker, launches builder
  bootstrap.sh              One-shot host bootstrap (installs Docker if absent)
  generate-theme-configs.sh Re-generates pre-baked theme configs from colors.toml templates

  shared/                   Everything here works on ALL compositors
    bin/                    User-facing scripts (installed to /usr/local/bin/)
                            Includes: dictation-prime, dictation-toggle, dictation-setup,
                            theme-set, rebuild-app-cache, smplos-settings, bar-ctl, ...
    eww/                    EWW bar and widgets (GTK3 — works on X11 + Wayland)
    configs/
      smplos/               Cross-compositor configs (bindings.conf, messengers.conf, branding)
      <app>/                Per-app default configs (btop, dunst, fish, foot, nvim, …)
    themes/                 14 themes — each a self-contained directory with pre-baked configs
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
    productivity/           Productivity — Logseq, LibreOffice, KeePassXC
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

- **`src/shared/apps/start-menu/`** - Rust + Slint application. Reads the app index, resolves icons (SVG/PNG from hicolor, Flatpak exports, and user icon dirs), renders a GPU-accelerated UI.
- **`toggle-start-menu`** - wrapper script that toggles the menu open/closed. Manages focus capture (`stay_focused`, `pin`, temporary `follow_mouse=3`).
- **Hyprland window rules** - `float`, `move 2 (monitor_h-window_h-37)`, `animation slide left`, `opacity 1.0 override`.

### App Cache

The start menu reads from a pre-built app index at `~/.cache/smplos/app_index`. This is automatically rebuilt by a systemd path unit (`smplos-app-cache.path`) whenever `.desktop` files, Flatpak apps, or AppImages change. You can also rebuild manually:

```bash
rebuild-app-cache
```

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

smplOS includes a built-in update system. On first boot, a persistent "System Update" notification appears. Double-click it in the notification center to run a full update, or run it manually:

```bash
smplos-update
```

The update script opens in your terminal and runs through:

1. **Pacman** - official repo packages (`pacman -Syu --noconfirm`)
2. **AUR** - if paru is installed, AUR packages (`paru -Sua --noconfirm`)
3. **Flatpak** - if Flatpak apps are installed (`flatpak update -y --noninteractive`)
4. **AppImages** - reminds you to check for updates manually

Terminal auto-detection makes sure it works regardless of which terminal is installed: `xdg-terminal-exec` -> `st-wl` (Wayland) -> `st` (X11) -> `foot` -> `xterm`.

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
    -p, --productivity      Office & workflow (Logseq, LibreOffice, KeePassXC)
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

14 built-in themes. Press <kbd>Super</kbd> + <kbd>Shift</kbd> + <kbd>T</kbd> to open the theme picker and switch instantly.

Catppuccin Mocha, Catppuccin Latte, Ethereal, Everforest, Flexoki Light, Gruvbox, Hackerman, Kanagawa, Matte Black, Nord, Osaka Jade, Ristretto, Rose Pine, Tokyo Night.

One command - `theme-set <name>` - applies colors across the entire system: terminal, bar, notifications, compositor borders, lock screen, launcher, system monitor, editor, fish shell, Logseq, and browser chrome.

For a full step-by-step authoring workflow, see [CREATING_MODIFYING_A_THEME.md](CREATING_MODIFYING_A_THEME.md).

### How It Works

The theme system is a **build-time template pipeline** plus a **runtime switcher**:

```
colors.toml --> generate-theme-configs.sh --> 9 pre-baked configs per theme
                      (sed templates)
                                               theme-set copies them to
                                               their target locations and
                                               restarts/reloads each app
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
| `hyprland.conf` | Generated | Hyprland border colors, rounding, blur, opacity |
| `hyprlock.conf` | Generated | Lock screen colors |
| `logseq-custom.css` | Generated | Logseq editor colors (backgrounds, text, links, highlights) |
| `neovim.lua` | Hand-authored | Lazy.nvim colorscheme spec |
| `vscode.json` | Hand-authored | VS Code/Codium/Cursor theme name + extension ID |
| `icons.theme` | Hand-authored | GTK icon theme name |
| `light.mode` | Hand-authored (optional) | Marker file - if present, GTK + browser use light mode |
| `tide.theme` | Hand-authored | Tide prompt colors (git, pwd, vi-mode segments) |
| `backgrounds/` | Hand-authored | Wallpapers bundled with the theme |
| `preview.png` | Hand-authored | Theme preview screenshot for the picker |

### colors.toml Reference

Every theme defines all its values in a single `colors.toml` file. Here's the full set of variables:

#### Colors

| Variable | Description | Example |
|----------|-------------|---------|
| `accent` | Primary accent color (bar icons, active borders, highlights) | `"#89b4fa"` |
| `cursor` | Terminal cursor color | `"#f5e0dc"` |
| `foreground` | Default text color | `"#cdd6f4"` |
| `background` | Window/terminal background | `"#1e1e2e"` |
| `selection_foreground` | Text color in selections | `"#1e1e2e"` |
| `selection_background` | Background color of selections | `"#f5e0dc"` |
| `color0` - `color15` | Standard 16-color terminal palette | `"#45475a"` |

> **Note:** `color7` and `color15` are the colors terminals actually display for normal text in most shells. If terminal text looks dim, brighten these to match `foreground`.

#### Decoration

| Variable | Default | Description |
|----------|---------|-------------|
| `rounding` | `"10"` | Window corner radius in pixels |
| `blur_size` | `"6"` | Background blur kernel size |
| `blur_passes` | `"3"` | Number of blur passes (higher = smoother, more GPU) |
| `opacity_active` | `"0.92"` | Opacity of focused windows (all regular apps) |
| `opacity_inactive` | `"0.85"` | Opacity of unfocused windows |
| `term_opacity_active` | `"0.85"` | st-wl **background-only** alpha. Text is always 100% opaque — only the background pixels carry this alpha in the ARGB surface. |
| `browser_opacity` | `"1.0"` | Opacity of browsers (Brave, Firefox, Chrome, etc.) |
| `messenger_opacity` | `"0.85"` | Opacity of messengers (Signal, Telegram, Slack, Discord, Teams, WhatsApp) |
| `popup_opacity` | `"0.85"` | Opacity of smplOS Rust popup apps (start-menu, notif-center, kb-center, disp-center) |

Each opacity class is owned exactly once — no value is applied twice. See [Opacity Architecture](#opacity-architecture) for details.

#### App Theme Selectors (single-file control)

Each `colors.toml` can also choose which app-specific preset to use:

| Variable | Description | Example |
|----------|-------------|---------|
| `app_theme_nvim` | Which theme's `neovim.lua` preset to apply | `"tokyo-night"` |
| `app_theme_vscode` | Which theme's `vscode.json` preset to apply | `"tokyo-night"` |
| `app_theme_logseq` | Which Logseq mapping preset to apply | `"tokyo-night"` |

By default, each built-in theme points these to itself. You can mix and match (e.g. keep `colors.toml` from one theme but reuse VS Code preset from another).

#### Example: Catppuccin Mocha

```toml
accent = "#89b4fa"
cursor = "#f5e0dc"
foreground = "#cdd6f4"
background = "#1e1e2e"
selection_foreground = "#1e1e2e"
selection_background = "#f5e0dc"

color0 = "#45475a"
color1 = "#f38ba8"
color2 = "#a6e3a1"
color3 = "#f9e2af"
color4 = "#89b4fa"
color5 = "#f5c2e7"
color6 = "#94e2d5"
color7 = "#cdd6f4"
color8 = "#585b70"
color9 = "#f38ba8"
color10 = "#a6e3a1"
color11 = "#f9e2af"
color12 = "#89b4fa"
color13 = "#f5c2e7"
color14 = "#94e2d5"
color15 = "#cdd6f4"

rounding = "12"
blur_size = "14"
blur_passes = "3"
opacity_active = "0.60"
opacity_inactive = "0.50"
browser_opacity = "1.0"
messenger_opacity = "0.85"
popup_opacity = "0.85"
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
   - `icons.theme` - GTK icon theme name (e.g., `Papirus-Dark`)
   - `light.mode` - Create this empty file if the theme is light
   - `backgrounds/` - Add wallpapers (named `1-name.png`, `2-name.png`, etc.)
   - `preview.png` - Screenshot for the theme picker

4. **Generate configs:**
   ```bash
   cd src && bash generate-theme-configs.sh
   ```
   This reads your `colors.toml`, expands all 9 templates, and writes the results into your theme directory.

5. **Test it:**
   ```bash
   theme-set my-theme
   ```

### What theme-set Does

When you run `theme-set <name>`, it:

1. Resolves the theme (user themes in `~/.config/smplos/themes/` take precedence over stock themes)
2. Atomically swaps the active theme directory at `~/.config/smplos/current/theme/`
3. Copies pre-baked configs to their target locations:
   - `eww-colors.scss` -> `~/.config/eww/theme-colors.scss`
   - `hyprland.conf` -> `~/.config/hypr/theme.conf`
   - `hyprlock.conf` -> `~/.config/hypr/hyprlock-theme.conf`
   - `foot.ini` -> `~/.config/foot/theme.ini`
   - `btop.theme` -> `~/.config/btop/themes/current.theme`
   - `fish.theme` -> `~/.config/fish/theme.fish`
   - `tide.theme` -> applied via `fish -c "source ...; tide reload"`
   - `logseq-custom.css` -> `~/.logseq/config/custom.css` + plugin theme via `preferences.json`
   - `dunstrc.theme` -> appended to `~/.config/dunst/dunstrc.active`
   - `neovim.lua` -> `~/.config/nvim/lua/plugins/colorscheme.lua`
4. Bakes accent/fg colors into SVG icon templates for the EWW bar
5. Sets the wallpaper from `backgrounds/`
6. Restarts/reloads all running apps:
   - EWW bar: kill + restart (re-compiles SCSS)
   - Hyprland: `hyprctl reload`
   - st/st-wl: OSC escape sequences (live, no restart)
   - Foot: `SIGUSR1`
   - Fish: sources `theme.fish` in all running sessions
   - Tide prompt: `tide reload` (updates git, pwd, vi-mode segment colors)
   - Dunst: `dunstctl reload`
   - btop: `SIGUSR2`
   - Logseq: writes `preferences.json` (Logseq watches this file)
   - GTK: `gsettings` (dark/light mode)
   - Brave/Chromium: managed policy + flags file

### Opacity Architecture

Every window belongs to exactly one opacity class. The value for each class lives in `colors.toml` and is never applied in more than one place — no compounding.

#### Opacity classes (tags)

| Class | Tag | Who controls opacity | `colors.toml` key |
|-------|-----|----------------------|-------------------|
| Regular apps | *(untagged)* | Hyprland compositor | `opacity_active` / `opacity_inactive` |
| Browsers | `chromium-based-browser` / `firefox-based-browser` | Hyprland compositor | `browser_opacity` |
| Messengers | `messenger` | Hyprland compositor | `messenger_opacity` |
| smplOS Rust popups | `self-managed-alpha` | App itself (Slint ARGB surface) | `popup_opacity` |
| Terminals | `self-managed-alpha` | App itself (st ALPHA_PATCH per-pixel) | `term_opacity_active` |
| Media / fullscreen | `compositor-opaque` | Hyprland compositor (forced 1.0) | — |

#### Why `self-managed-alpha` windows use `1.0 override`

Slint (smplOS Rust apps) and st with ALPHA_PATCH render their own semi-transparent pixels directly into an ARGB Wayland surface. If the compositor *also* applies opacity, the two multiply together:

```
0.85 (app alpha) × 0.85 (compositor) ≈ 0.72 opaque → only 28% see-through
```

To prevent this, all `self-managed-alpha` windows receive `opacity 1.0 override` from Hyprland, so the compositor passes pixels through untouched and the app's ARGB alpha is the sole controller.

#### Per-app messenger overrides

All messengers default to `messenger_opacity` from the active theme, but individual apps can be pinned to a specific value by uncommenting the override lines in `windows.conf`:

```properties
# windowrule = opacity 0.70 override 0.70 override, match:class ^(signal)$
# windowrule = opacity 0.80 override 0.80 override, match:class ^(brave-teams\.microsoft\.com)(.*)$
```

These lines come *after* the tag-level rule, so they win (Hyprland last-match-wins). No theme rebuild needed — reload Hyprland config with `Super+R`.

#### Adding a new Slint app

If you add a new Rust/Slint app, add one line to `windows.conf` in the `self-managed-alpha` tag block:

```properties
windowrule = tag +self-managed-alpha, match:class ^(my-new-app)$
```

The `opacity 1.0 override` rule fires automatically from the tag. Nothing else to change.

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
