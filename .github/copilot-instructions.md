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

## For AI Assistants: Debugging UI Code Efficiently

Hard-won lessons from a 3-hour session that should have taken 30 minutes.

### Rule 1 — Verify the exact widget target before writing any code

When the user mentions a UI element by name (e.g. "the Alt+F1 menu"), do NOT
assume which widget it maps to based on the first plausible code you find.
**Always identify the GType/widget name first.**

- Ask for a screenshot, or
- Run `GTK_DEBUG=interactive nemo` / `GDK_BACKEND=x11 GTK_DEBUG=interactive`
  to open the GTK Inspector and click the widget, or
- Grep for the keybinding handler:
  ```bash
  grep -rn "GDK_KEY_F1\|<Alt>F1\|alt.*f1" src/ --include="*.c"
  ```
  Then read what that handler actually shows — before writing anything.

**Why:** "The Alt+F1 menu" could mean the app menubar (File/Edit/View/Go) OR
a custom popup. They are completely different widgets with different APIs.
Patching the wrong one wastes N build cycles with zero visible effect.

### Rule 2 — Add a one-line probe BEFORE building the real fix

When a GTK/GLib API call might silently no-op (returns void, no error code),
verify the precondition with `g_warning()` before committing to a fix:

```c
// Before the real fix:
g_warning ("toplevel type: %s  is-window: %d",
           G_OBJECT_TYPE_NAME (gtk_widget_get_toplevel (menu)),
           GTK_IS_WINDOW (gtk_widget_get_toplevel (menu)));
```

Build, run, check `journalctl -f` or stderr. If the output disproves the
assumption, iterate on the probe — NOT on increasingly elaborate "real" fixes.
One extra build cycle with a probe saves three blind fix cycles.

Common silent failure patterns in GTK:
- `gtk_widget_get_toplevel()` on a `GtkMenu` returns the menu itself (not a
  `GtkWindow`) — `GTK_IS_WINDOW()` is always `FALSE`
- `gtk_window_set_mnemonics_visible()` called before `map` is reset to FALSE
  by GTK's own map-time handler
- `g_settings_set_*()` where a dconf value exists and no `changed::` signal fires
- Signal handlers connected before the widget is realized never fire

### Rule 3 — After 3 failed attempts using framework APIs, route around them

If you've tried 3+ variations of the same GTK/GLib API and the behavior never
changes, that API is the wrong tool for the job. Stop and ask:

> "What does this framework feature actually do mechanically?
>  Can I implement just that behaviour myself in 20 lines?"

The answer is often yes and the result is simpler:

| Problem | Wrong approach (fought framework) | Right approach (routed around) |
|---|---|---|
| Underlines in popup menu | `mnemonics_visible`, `select_first`, map signal | `gtk_label_set_markup("<u>c</u>har")` — Pango renders unconditionally |
| Key activation in popup menu | GTK mnemonic scanning (needs `GtkWindow`) | `key-press-event` + `g_object_set_data` + manual `activate_item()` |

Framework APIs are designed for the common case. Programmatically spawned popups,
non-hardware-triggered events, and non-standard widget hierarchies are edge cases
where the framework's assumptions break silently.

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
  apps/              ← git submodule → github.com/smpl-os/smpl-apps
    Cargo.toml       ← workspace root (shared deps, renderer-femtovg)
    smpl-common/     ← shared init library for all apps
    start-menu/      ← app crates (use workspace deps via smpl-common)
    notif-center/
    settings/
    app-center/
    webapp-center/
    sync-center/
    calendar/
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

### Logseq Theming (REGRESSION-PRONE — READ BEFORE TOUCHING)

`theme-set` applies Logseq themes via two mechanisms:

1. **`:custom-css-url` in `~/.logseq/config/config.edn`** — This is the PRIMARY mechanism for DB-based graphs (Logseq 0.10+, current). Logseq's `add-style!` function takes the `:custom-css-url` value and embeds it **directly as CSS text content** in a `data:text/css` URL injected into the DOM as `<link id="logseq-custom-theme-id">`. **It does NOT fetch it as a URL** — `file://` and `assets://` URLs passed here are embedded as literal CSS text (which does nothing). The correct approach is to embed the actual CSS content directly as the value. `theme-set` reads the CSS file, escapes it, and writes it inline into config.edn. This requires a Logseq restart to take effect (config.edn is not live-reloaded).

2. **`<graph-dir>/logseq/custom.css`** — For file-based graphs (legacy format). Live-reloaded by Logseq's file watcher. `theme-set` scans for these via `find ~ -name config.edn -path "*/logseq/config.edn" -not -path "~/.logseq/*"` and writes to each. `~/.logseq/custom.css` is also written as a fallback but is never auto-watched.

3. **`~/.logseq/preferences.json`** — Plugin theme metadata (`name`, `url`, `pid`). Only read at Logseq startup. Only written when a matching Logseq plugin is installed.

**Critical guard — NEVER remove this:**
```bash
if [[ -n "$_lq_pid" && -f "$_lq_css" ]]; then
```
The `-f "$_lq_css"` check is mandatory. If a plugin is listed in the `case` block but not installed on the user's system, `_lq_css` points to a non-existent file. Without the guard, `preferences.json` gets a broken `assets://` URL, Logseq silently fails to load the plugin theme. This was the matrix regression: the `logseq-matrixamoled-theme` plugin was listed but not installed.

**How to test Logseq theming before committing:**
1. Run `theme-set matrix` then **fully restart Logseq** (config.edn change requires restart)
2. Check `~/.logseq/preferences.json` — should have `"mode": "dark"` only (no `url`/`pid` if plugin not installed)
3. Check `~/.logseq/config/config.edn` — `:custom-css-url` value should be the full CSS text (not a file path)
4. Logseq should show green-on-black matrix colors
5. To debug: open Logseq DevTools (Ctrl+Shift+I) → Console → run `document.getElementById('logseq-custom-theme-id')?.outerHTML` — the `href` should be a `data:text/css` URL containing your CSS rules, not a file path

**`preferences.json` is NOT live-reloaded** — plugin theme changes only take full effect after Logseq restart. `config.edn` is also NOT live-reloaded — restart required after `theme-set`.

**NEVER do these — each one silently breaks Logseq theming with no error:**
- NEVER set `:custom-css-url` to a `file://` path — Logseq embeds it as literal CSS text, not a URL to fetch
- NEVER set `:custom-css-url` to an `assets://` path — same problem, treated as literal text
- NEVER write only to `~/.logseq/custom.css` without also updating `:custom-css-url` in config.edn — Logseq never watches that file automatically
- NEVER skip the `-f "$_lq_css"` guard — missing plugin CSS file → broken `assets://` URL in preferences.json → silent failure
- NEVER expect config.edn changes to live-reload — always restart Logseq after `theme-set`

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

All smplOS GUI apps (`start-menu`, `notif-center`, `settings`, `app-center`,
`webapp-center`, `sync-center`, `smpl-calendar`) share one architecture for
transparency + blur. **Deviating from any of these points silently breaks the
look with NO error message.**

#### Source of Truth: smpl-apps Workspace

`src/shared/apps/` is a **git submodule** pointing to the
[smpl-apps](https://github.com/smpl-os/smpl-apps) repo. It contains:

```
src/shared/apps/   ← git submodule (smpl-os/smpl-apps)
  Cargo.toml          ← workspace root (version, shared deps)
  Cargo.lock
  smpl-common/        ← shared init library (transparency + Wayland setup)
  start-menu/
  notif-center/
  settings/
  app-center/
  webapp-center/
  sync-center/
  calendar/           ← builds smpl-calendar + smpl-calendar-alertd
```

**smpl-common** is the single source of truth for backend init. Every app
calls `smpl_common::init(app_id, w, h)` which sets the FemtoVG renderer,
disables decorations, and configures the Wayland app_id. **NO app should
inline this init code or have its own Backend::builder() calls.**

⚠️ **STOP — Read this if you need to change app code:**

**RULE 1: ALL changes go in the smpl-apps repo.**
`src/shared/apps/` is a read-only submodule. NEVER commit app code changes
directly in smplos — they belong in the smpl-apps repo. After pushing to
smpl-apps, update the submodule pointer:
```bash
cd smplos && git submodule update --remote src/shared/apps && git add src/shared/apps && git commit -m "chore: update smpl-apps submodule"
```

**RULE 2: NEVER create standalone Cargo.toml files for individual apps.**
Apps use `workspace = true` for all shared dependencies. The workspace
`Cargo.toml` declares `renderer-femtovg` once; individual apps inherit it.

**RULE 3: build-iso.sh downloads pre-built binaries by default.**
The default build path downloads release binaries from GitHub. Only when
`--build-apps` is passed does it compile from the submodule source.
`build-apps.sh` runs `cargo build --release --workspace` inside a container.

```toml
# ✅ CORRECT — in workspace Cargo.toml (ONE place, inherited by all apps):
slint = { version = "1.8", default-features = false, features = ["backend-winit", "renderer-femtovg", "compat-1-2"] }

# ❌ WRONG — NEVER use these (destroys transparency with no error):
# renderer-software (softbuffer hardcodes XRGB on Wayland — alpha ignored)
# renderer-skia, or omitting the renderer feature entirely
```

**smpl-common init code** (in `smpl-common/src/lib.rs`):

```rust
let backend = i_slint_backend_winit::Backend::builder()
    .with_renderer_name("femtovg")           // MUST match Cargo.toml feature
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

- **`renderer-femtovg` in BOTH Cargo.toml AND runtime code.** The Cargo.toml
  feature flag controls what gets compiled in. The runtime `.with_renderer_name()`
  selects it. FemtoVG uses OpenGL/EGL with ARGB visuals on Wayland, so the
  compositor sees real alpha. NEVER use `renderer-software` — softbuffer
  hardcodes `wl_shm::Format::Xrgb8888` on Wayland, making alpha completely
  ignored regardless of what the app writes.
- **`with_decorations(false)` is mandatory.** CSD adds an opaque frame, destroying the
  borderless transparent look.
- **`with_name(app_id, instance)` is mandatory.** Without it the Wayland `app_id` is
  empty/generic and `windowrulev2` in `windows.conf` can't target the window for
  float/opacity/blur rules. Convention: both args match the binary name.
- **Background alpha comes from the theme palette.** Each `.slint` Window uses
  `background: Theme.bg.transparentize(1.0 - Theme.opacity)`. The `opacity`
  value is read from `$theme-popup-opacity` in `theme-colors.scss` at runtime.
  Never hardcode a fully-opaque `#rrggbb` background on a Window.
- **Hyprland rules** in `windows.conf` target `initialClass` matching the `app_id`:
  `windowrulev2 = float, initialClass:start-menu`.

**NEVER do these — each one silently kills transparency with no error:**
- NEVER put `renderer-software` or `renderer-skia` in the workspace Cargo.toml
- NEVER remove the `renderer-femtovg` feature from a Cargo.toml
- NEVER set `with_decorations(true)` or omit the decorations call
- NEVER hardcode an opaque `#rrggbb` background on a `.slint` Window (use theme alpha)
- NEVER create standalone per-app Cargo.toml files with their own slint dependency
- NEVER commit app code changes directly in smplos — edit smpl-apps, then update submodule
- NEVER inline Backend::builder() in individual apps — use `smpl_common::init()`

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
| `bebe972` | 2026-03-01 | **LKG** | Live boot + post-install desktop working in QEMU. All fixes: start-hyprland, Plymouth DRM ordering, gfxpayload. |
| `29e37e5` | 2026-02-25 | Good | Live boot + installer working on Ventoy. 2-entry menu (smplOS + Safe Mode). All fixes: Plymouth, HiDPI auto-scale, start-menu, webapp-center, TTY font. |
| `7b6416c` | 2026-02-25 | Good | First working Ventoy UEFI boot (uefi.grub + vanilla Arch releng grub configs) |

**What broke boot last time (2026-03-04):** `plymouth quit --retain-splash` in the
plymouth-quit and plymouth-quit-wait service drop-ins. `--retain-splash` keeps the
DRM master fd open so the splash stays visible until the next graphical app. But
Hyprland needs DRM master to start — it can't acquire it while Plymouth holds it →
crash → black screen on all VTs. Confirmed by testing: text-mode Plymouth (serial
console) releases DRM immediately and Hyprland boots fine; graphical Plymouth with
`--retain-splash` always causes black screen. Fix: use `plymouth deactivate` (which
explicitly releases DRM and drops to text mode) followed by `plymouth quit`. This
is deterministic — no race. NEVER use `--retain-splash` in the quit command.
Also: never mask `plymouth-quit-wait.service` — it is greetd's ordering anchor.

**What also broke boot (2026-03-04):** `console=tty2` in GRUB_CMDLINE_LINUX_DEFAULT.
The intent was to redirect boot messages away from VT1 so `plymouth deactivate`
would reveal a blank screen instead of text. But Plymouth uses the kernel console
for its password prompt — moving it to tty2 caused Plymouth to lose its graphical
splash and drop to a raw TTY password prompt. Fix: keep `console=tty1`. The VT1
palette blanking trick (reprogramming all 16 colors to black via `\033]PX` escape
sequences before `plymouth deactivate`) was also tried but didn't help because the
palette reset happens too late — Plymouth has already written text. NEVER change
`console=` away from `tty1`.

### Plymouth → Hyprland Text Flash (KNOWN ISSUE — TODO)

**Status:** Cosmetic issue, not a blocker. Revisit when time permits.

After `plymouth deactivate` releases DRM and before Hyprland renders its first
frame, VT1 briefly shows boot text (login prompt, systemd messages). This flash
lasts ~0.5-1s and is purely cosmetic — boot completes successfully.

**Current working boot chain:**
1. Plymouth shows splash (holds DRM, handles LUKS password if needed)
2. `plymouth-quit-wait` drop-in runs: `plymouth deactivate` (releases DRM) →
   `plymouth quit --wait` (blocks until daemon exits)
3. greetd starts (After=plymouth-quit-wait.service) → `start-hyprland` → Hyprland
4. Brief text flash visible between steps 2 and 3

**What has been tried and failed:**
- `--retain-splash` → keeps DRM fd open → Hyprland can't start → **black screen**
- `console=tty2` → Plymouth loses graphical splash → **raw TTY password prompt**
- `chvt 7` (switch to empty VT) → interferes with greetd VT allocation → **black screen**
- `printf "\033c" > /dev/tty1` (clear VT1) → text still flashes
- VT1 palette blanking (`\033]P0..PF` all black) → too late, text already rendered

**Potential future solutions to explore:**
- **SDDM** instead of greetd — Omarchy (basecamp/omarchy) uses SDDM with autologin
  + `hyprland-uwsm` session. SDDM handles Plymouth→DRM handoff natively as a
  graphical display manager. Adds Qt dependency but eliminates the flash entirely.
- **UWSM** (Universal Wayland Session Manager) — can be used with greetd or SDDM,
  handles session lifecycle more cleanly. Omarchy uses `hyprland-uwsm` session.
- **Plymouth VT handoff protocol** — investigate if Plymouth supports handing its
  DRM fd directly to the next graphical process (like `--retain-splash` was supposed
  to do but for a non-DM greeter chain).

**What broke boot last time (2026-03-01):** `After=greetd.service` in the
`plymouth-quit.service.d` override. greetd is `Type=simple` so systemd marks
it active immediately, but Hyprland fires instantly and races Plymouth for the
DRM master — Plymouth still holds it. Hyprland crashes. Black screen on all
TTYs. Fix: **always use `After=multi-user.target`** in that drop-in. The
`--retain-splash` flag covers the visual gap until Hyprland renders.
Do NOT change this to `After=greetd.service`.

**What broke boot last time (2026-02-25):** Adding `grub-mkfont -s 32` to
generate a custom HiDPI font in the live ISO. mkarchiso's `grub-mkstandalone`
embeds its own `unicode.pf2`; overriding it caused "syntax error" on Ventoy
Normal mode. Fix: removed custom font from live ISO (commit `3257b39`), kept
HiDPI font only for installed system in `install.sh`.
