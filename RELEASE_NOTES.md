# smplOS Release Notes

Full changelog for all smplOS releases. For the latest release, see the [README](README.md).

---

## v0.6.52

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
