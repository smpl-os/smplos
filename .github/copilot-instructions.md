# smplOS Development Principles

## For AI Assistants: How to Handle Guideline Conflicts

These instructions exist to prevent regressions and enforce hard-won decisions.
**However:** if you believe a guideline is wrong, outdated, or that a better
approach exists, **do not silently comply or silently avoid the better path.**

Instead, explicitly flag it:

> "The copilot instructions say X, but I think Y would be better because Z.
> Want me to proceed with Y, or stick with the guidelines?"

Examples of when to flag:
- You know a newer API/pattern that would improve on an established one
- A guideline would cause a bug in the current context
- Two guidelines conflict with each other
- You're about to do something the instructions prohibit but the user seems to want it

**Never silently do the "wrong" thing to comply with instructions, and never
silently skip a better solution because it conflicts with instructions. Always
ask first.**

---

## Architecture: Cross-Compositor First

smplOS supports multiple compositors (Hyprland/Wayland, DWM/X11). Every feature
must be designed with this in mind. The goal is maximum code reuse — compositors
are a thin layer on top of a shared foundation.

### Directory Structure

```
src/shared/          ← Everything here works on ALL compositors
  bin/               ← User-facing scripts (installed to /usr/local/bin/)
  eww/               ← EWW bar, launcher, theme picker, keybind help (GTK3, works on X11 + Wayland)
  configs/smplos/    ← Cross-compositor configs (bindings.conf = single source of truth)
  themes/            ← 14 themes with templates for all apps
  installer/         ← OS installer

src/compositors/hyprland/   ← ONLY Hyprland-specific config
  hypr/                     ← hyprland.conf sources shared bindings.conf
  packages.txt              ← Wayland-specific packages

src/compositors/dwm/        ← ONLY DWM-specific config (future)
  config.h                  ← Will be generated from shared bindings.conf
  packages.txt              ← X11-specific packages
```

### Rules

1. **Shared by default.** New scripts go in `src/shared/bin/`. Only put code in
   `src/compositors/<name>/` if it literally cannot work elsewhere.

2. **No unnecessary dependencies.** Before adding a tool (fuzzel, rofi, wofi),
   ask: can EWW do this? EWW works on both X11 and Wayland. One fewer package
   to maintain per compositor.

3. **Compositor detection, not hardcoding.** When a script needs compositor-specific
   behavior, detect at runtime:
   ```bash
   if [[ -n "$WAYLAND_DISPLAY" ]]; then
       # Wayland path (Hyprland)
   else
       # X11 path (DWM)
   fi
   ```

4. **bindings.conf is the single source of truth** for keybindings.
   - Lives at `src/shared/configs/smplos/bindings.conf`
   - Uses Hyprland `bindd` format (human-readable, comma-delimited)
   - Build pipeline copies it as-is for Hyprland
   - DWM build will parse it and generate C structs for `config.h`
   - `get-keybindings.sh` parses it for the EWW keybind-help overlay

5. **EWW is the UI layer.** Bar, launcher, theme picker, keybind help — all EWW.
   No waybar, no polybar. EWW runs on both GTK3/X11 and GTK3/Wayland.

6. **Theme system is universal.** One `theme-set` script applies colors to:
   EWW, st, foot, btop, mako, Hyprland borders, hyprlock, neovim.
   Adding a compositor means adding one more template, not rewriting themes.

### EWW Guidelines

- **Single-line JSON for `deflisten`.** EWW reads stdout line-by-line. Multi-line
  JSON breaks `deflisten` variables. Always output compact single-line JSON.
- **No `@charset` triggers.** Avoid non-ASCII characters (em-dashes `—`, curly
  quotes, etc.) in `.scss` files. The grass SCSS compiler inserts
  `@charset "UTF-8"` which GTK3's CSS parser rejects silently → white unstyled bar.
- **Script permissions.** Always `chmod +x` EWW scripts in build pipeline AND at
  runtime (archiso/useradd can strip execute bits).
- **`--config $HOME/.config/eww`** on every `eww` CLI call.
- **Every `defwindow` must have an explicit `:namespace`.** Without it, the
  Wayland layer surface gets the default namespace `"gtk-layer-shell"`, which
  means Hyprland `layerrule` (blur, opacity, animations) cannot target individual
  windows. Use the convention `:namespace "eww-<window-name>"` (e.g.
  `"eww-bar"`, `"eww-calendar-popup"`). Then match in `windows.conf`:
  `layerrule = blur on, match:namespace eww-<window-name>`.
- **Use the shared dialog system for overlays.** Theme picker, keybind help, and
  any future overlay (settings, about, etc.) use the same pattern:
  - **CSS:** `.dialog`, `.dialog-header`, `.dialog-title`, `.dialog-close`,
    `.dialog-search`, `.dialog-scroll` -- shared classes in `eww.scss`.
  - **Script:** `dialog-toggle <window> [submap] [--pre-cmd CMD] [--post-cmd CMD]`
    handles toggle, daemon, open/close, submap. New dialogs are thin wrappers.
  - **Yuck:** Each widget uses the `.dialog` container and `.dialog-header` box.
    Only the item-specific content (e.g. theme-card, kb-row) is unique.

### Build & Iteration

- **ISO builds are expensive** (~15 min). Only rebuild for package changes.
- **Use `dev-push.sh` + `dev-apply.sh`** for config/script iteration:
  ```bash
  # Host:
  cd release && ./dev-push.sh eww    # or: bin, hypr, themes, all

  # VM:
  sudo bash /mnt/dev-apply.sh
  ```
- **QEMU VMs can't handle DPMS off or suspend.** `hypridle.conf` skips these
  inside VMs via `systemd-detect-virt -q`.

### Code Quality: Modular & DRY

- **Shapes over colors for state.** Never rely on color alone to indicate state
  (connected/disconnected, notifications/none, etc.). Use distinct icon shapes
  (filled vs outline, with/without X or slash). This ensures accessibility for
  users with color blindness. Color should reinforce the theme, not carry meaning.

- **Extract reusable functions.** If a pattern appears twice, make it a function.
  Bash scripts should define helper functions (`log()`, `die()`, `emit()`) at the
  top rather than repeating inline logic.
- **One responsibility per script.** A script does one thing well. Compose scripts
  together rather than building monoliths.
- **Shared helpers over copy-paste.** Common patterns (logging, JSON output,
  compositor detection, EWW daemon checks) should live in a shared library or
  consistent helper functions, not be duplicated across scripts.
- **Keep it concise.** Prefer short, readable code. Avoid verbose boilerplate,
  redundant comments that restate the code, or unnecessary wrapper layers.
- **Consistent patterns.** All EWW listener scripts should follow the same
  structure: setup, emit function, initial emit, watch loop. All `src/shared/bin/`
  scripts should follow the same error-handling and logging conventions.

### Suckless-style Programs (st, dwm, etc.)

- **ALWAYS edit `config.def.h`, NOT `config.h`.** The Makefile has a rule:
  `config.h: config.def.h` → `cp config.def.h config.h`. This means `config.h`
  is auto-generated and will be **overwritten** on every build. All persistent
  configuration changes MUST go in `config.def.h`.
- Same applies to `patches.def.h` → `patches.h`.
- After editing `config.def.h`, delete `config.h` to force regeneration:
  `rm -f config.h && make clean && make`
- The `termname` variable sets the `$TERM` value. Use standard entries like
  `st-256color` or `xterm-256color` — custom names like `st-wl-256color` will
  break `clear`, `ncurses`, and other terminfo-dependent tools unless you also
  install a matching terminfo entry.

### Transparent Rust Apps (Slint + Winit) — NEVER REGRESS THIS

All smplOS GUI apps (`start-menu`, `notif-center`, `kb-center`, `disp-center`,
`app-center`, `webapp-center`) share one architecture for transparency + blur.
**Deviating from any of these points silently breaks the look.**

```rust
let backend = i_slint_backend_winit::Backend::builder()
    .with_renderer_name("software")          // MUST be "software" — see below
    .with_window_attributes_hook(|attrs| {
        use i_slint_backend_winit::winit::platform::wayland::WindowAttributesExtWayland;
        use i_slint_backend_winit::winit::dpi::LogicalSize;
        attrs
            .with_name("app-id", "app-id")   // sets Wayland app_id for windowrulev2
            .with_decorations(false)          // MUST be false
            .with_inner_size(LogicalSize::new(W as f64, H as f64))
    })
    .build()?;
slint::platform::set_platform(Box::new(backend))
    .map_err(|e| slint::PlatformError::Other(e.to_string()))?;
```

**Rules — each one has caused a regression:**

- **`renderer-software` is mandatory.** `femtovg`, `skia`, and other GPU renderers
  composite to an opaque surface before passing pixels to the compositor — alpha is
  destroyed. The software renderer outputs raw RGBA pixels that Hyprland can blur through.
- **`with_decorations(false)` is mandatory.** CSD adds an opaque frame, destroying the
  borderless transparent look.
- **`with_name(app_id, instance)` is mandatory.** Without it the Wayland `app_id` is
  empty/generic and `windowrulev2` in `windows.conf` can't target the window for
  float/opacity/blur rules. Convention: both args match the binary name.
- **Background alpha comes from the theme palette.** The `bg` color in `theme-colors.scss`
  carries an alpha component (e.g. `rgba(20,20,20,0.85)`). `apply_theme()` reads it and
  sets it on the Slint `Theme` struct. Never hardcode a fully-opaque `#rrggbb` background
  in a `.slint` file — always pull from the palette so themes control opacity.
- **Hyprland rules** in `windows.conf` target `initialClass` matching the `app_id`:
  `windowrulev2 = float, initialClass:start-menu`.

### Packages

- Keep the package list minimal. Audit regularly for bloat.
- Known bloat candidates: wofi, fuzzel, rofi-wayland (3 redundant launchers),
  alacritty + foot (unused terminals alongside st), nwg-look (unused GUI tool).

### Offline-First Installation (CRITICAL)

The ISO must support **fully offline installation** — no internet required.
This is a hard requirement. Every package type is embedded in the ISO:

- **Official repo packages** → downloaded to `/var/cache/smplos/mirror/offline/`
  during build, served via `[offline]` repo with `file://` URL + `repo-add` DB.
- **AUR packages** → prebuilt as `.pkg.tar.zst`, injected into the offline mirror.
- **Flatpaks** → bundled into the ISO (future).
- **AppImages** → copied into the ISO at `/opt/appimages/`.

**Two-phase pacman config:**

1. **Live ISO + install** → `pacman.conf` uses ONLY `[offline]` repo:
   ```
   [offline]
   SigLevel = Optional TrustAll
   Server = file:///var/cache/smplos/mirror/offline/
   ```
   No `[core]`/`[extra]`/`[multilib]` — no internet dependency.
   The `configurator`'s archinstall JSON must have empty `custom_servers: []`
   so archinstall doesn't override the mirrorlist with online URLs.

2. **Post-install** (`install.sh`) → restores standard online repos:
   ```
   [core] / [extra] / [multilib] → Include = /etc/pacman.d/mirrorlist
   ```
   Runs `reflector` (with timeout + fallback) to find fastest mirrors.
   Cleans up offline mirror cache.

**Rules to prevent regression:**

- NEVER put online mirror URLs in the live ISO's `pacman.conf`.
- NEVER put online mirror URLs in archinstall's `mirror_config.custom_servers`.
- Build container changes (reflector, bootstrap mirrors, etc.) must NEVER leak
  into `$PROFILE_DIR/airootfs/` — the build container and the live ISO have
  **separate** pacman configs.
- The build container's `$PROFILE_DIR/pacman.conf` (for mkarchiso) and
  `$PROFILE_DIR/airootfs/etc/pacman.conf` (for the live ISO) must both use
  the `[offline]` repo exclusively.

### Boot & Ventoy Compatibility (CRITICAL)

The ISO uses **two bootmodes**: `bios.syslinux` (legacy BIOS) + `uefi.grub` (UEFI).

- **NEVER use `uefi.systemd-boot`.** It is incompatible with Ventoy. Ventoy uses
  GRUB to chainload ISOs via `loopback.cfg`, which only works with `uefi.grub`.
- **grub.cfg and loopback.cfg must match vanilla Arch releng** character-for-character,
  with only these allowed changes: menu entry titles, default ID, and added entries
  (e.g. Safe Mode). Do NOT deviate from vanilla Arch's quoting (single quotes),
  terminal mode (`terminal_output console`), or platform detection logic.
- The `grub/` directory in the profile contains both configs. mkarchiso's
  `_make_common_bootmode_grub_cfg()` substitutes `%ARCH%`, `%INSTALL_DIR%`,
  and `%ARCHISO_UUID%` at build time.
- `loopback.cfg` uses `img_dev=UUID=` + `img_loop=` instead of `archisosearchuuid`
  because Ventoy loop-mounts the ISO.

### Known-Good Commits (CRITICAL — READ THIS FIRST)

**When live boot breaks**, do NOT spend time hunting through git. The answer is
here. Check the **Last Known Good (LKG)** row — that is the most recent commit
where the full live boot + installer flow was verified working on real hardware
via Ventoy USB.

**How to revert:**
```bash
# 1. See what changed since LKG
git diff <LKG_HASH> HEAD -- src/builder/build.sh

# 2. If boot configs diverged, restore ONLY the setup_boot() function:
git show <LKG_HASH>:src/builder/build.sh | sed -n '/^setup_boot()/,/^[a-z_]*() {/p'
# Then replace setup_boot() in current build.sh with that output.
# Keep everything else (build functions, install.sh fixes, etc).
```

**The boot configs live in `setup_boot()` inside `src/builder/build.sh`.**
That function writes: `grub.cfg`, `loopback.cfg`, and all `syslinux/*.cfg` files.

| Commit | Date | Status | Milestone |
|--------|------|--------|-----------|
| `29e37e5` | 2026-02-25 | **LKG** | Live boot + installer working on Ventoy. 2-entry menu (smplOS + Safe Mode). All fixes: Plymouth, HiDPI auto-scale, start-menu, webapp-center, TTY font. |
| `7b6416c` | 2026-02-25 | Good | First working Ventoy UEFI boot (uefi.grub + vanilla Arch releng grub configs) |

**What broke boot last time (2026-02-25):** Adding `grub-mkfont -s 32` to
generate a custom HiDPI font in the live ISO. mkarchiso's `grub-mkstandalone`
embeds its own `unicode.pf2`; overriding it caused "syntax error" on Ventoy
Normal mode. Fix: removed custom font from live ISO (commit `3257b39`), kept
HiDPI font only for installed system in `install.sh`.
