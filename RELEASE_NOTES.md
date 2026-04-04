# smplOS Release Notes

Full changelog for all smplOS releases. For the latest release, see the [README](README.md).

---

## v0.7.2

- **kb-sync simplified — settings app now owns layout validation.** Removed
  `clean_csv` and `clean_variants_csv` workaround code (~40 lines) from
  `kb-sync`. The settings app now validates layout:variant pairs and runs an
  XKB compile check before writing `input.conf`, so `kb-sync` can apply the
  config as-is without second-guessing it.

- **Picks up smpl-apps v0.7.1** with idle shutdown via hypridle, Sleep in
  the start-menu power popup, and keyboard layout variant validation.

---

## v0.7.0

- **Start-menu Enter key launches top search result.** Pressing Enter while
  typing a search query now immediately launches the first result. The search
  `FocusScope` (needed for arrow-key navigation) had no `Key.Return` handler
  so Enter silently did nothing.

- **Settings card deep-links restored.** Clicking a keyword result like
  "Airplane Mode", "WiFi", "Resolution", or "Bluetooth Devices" in
  start-menu now opens Settings and highlights the relevant card.
  `rebuild-app-cache` was generating `smplos-settings wifi` exec format for
  search-only entries instead of `settings --tab wifi --highlight "Airplane Mode"`
  deep-link format — Settings opened on the right tab but never blinked the card.

- **"Airplane Mode" and other missing keywords added to settings search index.**
  `settings_search_index` was missing Airplane Mode and several other
  WiFi/Bluetooth entries.

- **Deployment no longer leaves search keywords stale.** `deploy-local.sh`
  now calls `rebuild-app-cache` after `settings --export-index` so keywords
  are immediately searchable after every deploy.

- **Alt-Shift keyboard layout switching fixed.** `kb_variant` was written
  without a leading comma (`phonetic` instead of `,phonetic`), applying the
  phonetic variant to `us` — an invalid XKB combination that caused Hyprland
  to reject the multi-layout config entirely and load only `us` with no
  options. Alt-Shift now reliably switches between `us` and `ru (phonetic)`.

- **CI regression guardrails.** Four new checks in smpl-apps CI block future
  regressions for the Enter key, settings keyword completeness, and
  `deploy-local.sh` rebuild step before merging.

---

## v0.6.8

- **Window positioning fixed for Hyprland 0.54.** All `move` window rules updated from the deprecated `100%` percentage syntax to Hyprland 0.54's `monitor_w`/`monitor_h` expression variables. Fixes start-menu, notification center, calendar, and all messenger windows launching in the center of the screen instead of their configured positions.
- **Window guard daemon.** New `window-guard` background service that monitors Hyprland IPC events and snaps floating windows back on-screen if they end up partially or fully outside the visible area. Three-layer approach: event-driven (200ms settle), deferred recheck (1.5s for Electron apps), and periodic sweep (every 5s). Toggle it from Settings → Display → "Keep windows on-screen", or via `~/.config/smplos/display.conf`.
- **Settings: window guard toggle.** New "Keep windows on-screen" toggle switch in the Settings app Display tab. Starts/stops the window-guard daemon in real time and persists the preference to `display.conf`.
- **Messenger toggle fix.** Fixed Signal Desktop (and other messenger windows launched via Super+Shift+hotkey) appearing off-screen on multi-monitor setups. The `toggle-messenger` script now correctly separates monitor-relative coordinates (for `exec [move]`) from compositor-absolute coordinates (for `movewindowpixel exact`), preventing double-counting of monitor offset.
- **Migration script.** Automatic migration (`20260329-200000-window-positioning-fixes.sh`) patches existing installations: updates `windows.conf` move rules, adds window-guard to autostart, creates `display.conf` defaults, and reloads Hyprland.

---

## v0.6.62

- **Webapp sandbox: cookie clearing fixed.** The "clear all data on exit" checkbox in Webapp Center now actually works. Cookies, login tokens, local storage, and session data are wiped on both launch and exit. Previously, data persisted indefinitely due to a pipe-handling bug in the sandbox wrapper.
- **Webapp duplicate launch fixed.** Opening a webapp that's already running now focuses the existing window instead of spawning error dialogs. Added `--class` passthrough to Chromium for correct WM class matching, plus a lockfile guard as a safety net.
- **Webapp sandbox improvements.** GPU acceleration (`/dev/dri`), D-Bus access, and writable XDG runtime directory are now available inside the bubblewrap sandbox — eliminates GPU crashes, dconf errors, and broken portal dialogs.
- **Terminal key sequence fix (st-wl).** Shift+Home, Shift+End, and Ctrl+End now work correctly in micro and other tcell-based apps. Changed from xterm F/H-style sequences to tilde-style sequences that match tcell's built-in `st-256color` terminfo. Terminfo is now installed alongside the binary during OTA updates.
- **Reliable OTA updates.** Single sudo prompt for the entire update session — no more double password prompts. The keepalive interval was tightened to 30s, child scripts detect the parent's cached credentials via `SMPLOS_SUDO_READY`, and paru uses `--sudoloop`. Running apps (smpl-apps GUI, nemo) are automatically restarted after update.
- **Script sync fix.** `smplos-os-update` now syncs scripts to both `/usr/local/bin/` and `~/.local/share/smplos/bin/` (which takes PATH priority), preventing stale user-local copies from shadowing system updates.
- **Nemo file manager theming.** Full CSS theming for nemo — breadcrumbs, toolbars, dialogs, list-view defaults, inactive pane outlines, and tooltip fixes all match the active smplOS theme.
- **EWW two-line clock.** The bar clock now shows time and date on two lines with configurable format scripts (`clock-top`, `clock-bot`), fitting within the existing bar height.
- **Workspace squares.** EWW bar workspace indicators now support a squares display mode with tighter spacing and configurable count.
- **Settings: display identify.** The Display tab's "Identify monitors" feature now uses EWW overlay windows — no cursor tricks, simultaneous labels on all monitors.
- **Per-app launch options.** New `launch-with-options` wrapper script lets webapps and desktop entries specify per-app environment variables.
- **Cursor warp fixes.** Disabled cursor warp on workspace change (`no_warps = true`) and fixed `wl_pointer.enter` re-synthesis after window close.
- **Theme submenu fix.** CSS hover selectors use direct-child combinators to prevent black-on-black text in nested menus.

- **Over-the-air updates.** smplOS can now update itself. The OS repo is cloned to each machine and a `git pull` brings in new scripts, configs, themes, and migrations — no re-imaging required. Run `smplos-update` for a full update (OS configs + system packages + forked apps), or let the App Center trigger it. Scripts, themes, and bindings are synced automatically; breaking changes are handled by one-shot migrations that run exactly once per user. See [UPDATING.md](UPDATING.md) for the full architecture.
- **Migration system.** Timestamped migration scripts in `migrations/` handle breaking changes from upstream packages and smplOS config changes. `smplos-migrate` runs pending migrations in order, tracks state in `~/.local/state/smplos/migrations/`, and never runs the same migration twice. Current migrations: update system bootstrap, EWW button grab fix, Hyprshell default config, and micro default editor.
- **Modular updates.** The update system has separate stages you can run independently:
  - `smplos-os-update` — pull latest repo, sync scripts/configs, run migrations, bump OS version
  - `smplos-update-apps` — download latest smpl-apps, st-smpl, nemo-smpl, and micro binaries from GitHub releases (with smart caching + offline fallback)
  - `smplos-update` — orchestrates everything: OS update → app update → pacman/AUR/Flatpak
  - `smplos-refresh-config` — selectively restore a default config file (e.g. `smplos-refresh-config hypr/hyprlock.conf`)
- **Calendar app.** New `smpl-calendar` app with popup calendar + `smpl-calendar-alertd` daemon for desktop notifications on upcoming events. Integrates with the EWW bar clock — click the time to open it. Supports local ICS files, live theme refresh, and positioned at the bottom-right corner matching the notification center.
- **Settings: Keybindings tab.** The Settings app now has a full Keybindings tab — browse, search, and edit all system keybindings. Features 1-click capture (press the key combo you want) with auto-save back to `bindings.conf`. Keybinding logic extracted to `smpl-common` for reuse across apps.
- **Webapp Center: hotkey support.** Webapp Center now supports a Super+key hotkey column — assign a global shortcut to any web app.
- **App Center: auto-close after update.** The App Center window now closes automatically after launching a system update, so you're not left with a stale window behind the terminal.
- **GitHub release downloads.** Forked app binaries (smpl-apps, st-smpl, nemo-smpl, micro) are now downloaded from GitHub releases instead of being compiled locally. Smart caching compares the latest release tag to a local version file — only downloads when there's a new release. Falls back to cached binaries when offline.
- **Hyprshell alt-tab.** Alt-Tab window switching via Hyprshell, with a default config deployed by migration.
- **BambuStudio for Creators edition.** The Creators edition now includes BambuStudio for 3D printer management.
- **micro as default editor.** Replaced neovim with micro as the default text editor in the Dev edition. More approachable for new users; neovim is still installable. Existing installs get a migration.
- **Compact bar clock.** EWW bar clock now shows time only, with the full date in a tooltip — saves horizontal space.
- **EWW pointer grab fix.** Fixed the GTK pointer grab bug on system tray buttons that caused the bar to become unresponsive. Replaced all sleep-based workarounds with a proper root-window pointer grab fix.
- **SiYuan theme pre-configuration.** SiYuan notes app now launches with the smplOS theme on first run.
- **Single sudo prompt.** The update system now asks for your password once at the start, not repeatedly during each phase.

---

## v0.6.0

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

## v0.5.0

- **Transparent GUI apps** — All Rust/Slint apps (notif-center, kb-center, disp-center, start-menu, webapp-center) now use the software renderer, enabling proper alpha transparency and blur through Hyprland. Previously only app-center had working transparency.
- **Reliable Hyprland session startup** — greetd now launches via the real `start-hyprland` watchdog binary, which restarts Hyprland in safe mode on crash instead of leaving a black screen.
- **Faster dev iteration** — `build-apps.sh` skips the container entirely for apps whose git tree hash hasn't changed since last build.

---

## v0.2-alpha

- Initial theme system and EWW bar implementation.
- 14 built-in themes with live switching.
- Cross-compositor architecture (Hyprland Wayland + DWM X11 planned).
