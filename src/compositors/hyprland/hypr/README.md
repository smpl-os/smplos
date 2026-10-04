# Hyprland configuration (Lua + hyprlang)

This directory holds **two parallel config trees** for Hyprland 0.55+. They
describe the same compositor state; only one is read at any time.

## Layouts

```
hyprland.lua          ←  Lua entry point (preferred by Hyprland 0.55+)
├ envs.lua
├ input.lua
├ looknfeel.lua       ←  general / decoration / animations / cursor / misc
├ windows.lua         ←  layer + window rules, opacity model, messengers
├ apps.lua            ←  loads apps/*.lua
│  └ apps/
│     ├ browser.lua  jetbrains.lua  pip.lua  qemu.lua  steam.lua
│     └ system.lua   terminals.lua
├ autostart.lua       ←  hl.on("hyprland.start", …) — 16 exec_cmd entries
├ theme.lua           ←  parses ~/.config/hypr/theme.conf $vars into a Lua table
├ monitors_loader.lua ←  parses ~/.config/hypr/monitors.conf → hl.monitor calls
└ bindings_loader.lua ←  parses ~/.config/smplos/bindings.conf  → hl.bind calls
                         + ~/.config/hypr/messenger-bindings.conf (auto-gen)

hyprland.conf         ←  classic hyprlang entry point (still functional)
├ envs.conf  input.conf  looknfeel.conf  windows.conf
├ apps.conf  → apps/*.conf  (same set as above)
└ autostart.conf
```

The shared cross-compositor files (single source of truth, **do not duplicate
into Lua**):

```
~/.config/hypr/theme.conf                ←  written by theme-set
~/.config/hypr/monitors.conf             ←  written by Settings → Display
~/.config/hypr/messenger-bindings.conf   ←  written by generate-messenger-bindings
~/.config/smplos/bindings.conf           ←  shared with DWM-X11 + keybind-help
```

## Why both formats?

* **Lua is the new default.** Upstream 0.55+ ships `example/hyprland.lua`
  (no longer `example/hyprland.conf`) and runs auto-generated configs in Lua.
* **smplOS has external consumers** that parse the hyprlang format:
  * The DWM-X11 build (planned) will parse `bindings.conf` into C structs.
  * `keybind-help` renders the EWW overlay from `bindings.conf`.
  * The Settings app writes `monitors.conf` in hyprlang.
  * `theme-set` writes `theme.conf` in hyprlang.
* We keep the existing `.conf` files **untouched** so reverting is one rename
  away. The Lua side bridges to these files via `theme.lua`,
  `monitors_loader.lua`, and `bindings_loader.lua`.

## Which provider is active?

```bash
hyprctl systeminfo | grep configProvider
# → configProvider: hyprlang     ← reading hyprland.conf
# → configProvider: lua          ← reading hyprland.lua
```

Hyprland selects the provider **once at startup** and offers no live swap.
`hyprctl reload` re-runs the chosen provider only. Switching between the two
requires a fresh Hyprland session (log out / log back in).

## Switch to Lua

```bash
# 1. Move hyprland.conf out of the way so Hyprland falls back to hyprland.lua
mv ~/.config/hypr/hyprland.conf ~/.config/hypr/hyprland.conf.disabled

# 2. Log out and log back in (greetd)

# 3. Verify
hyprctl systeminfo | grep configProvider     # → configProvider: lua
hyprctl binds | wc -l                        # should match the .conf count
```

If anything breaks:

```bash
mv ~/.config/hypr/hyprland.conf.disabled ~/.config/hypr/hyprland.conf
# Log out / back in. You're back on hyprlang in exactly the previous state.
```

## Editing rules

* **Idle preferences**: `hypridle.conf` belongs to hypridle, not either
  compositor configuration tree. Never include/source it from Hyprland.
  Updates preserve existing user files and only bootstrap a missing file.
  Known command-syntax migrations retain timers/custom content, back up before
  atomic replacement, and apply through `hypridle.service`; compositor reload
  alone does not apply idle rules. Stock DPMS commands use `smplos-hypr-dpms`,
  which selects syntax from the running provider rather than package version.
* **Session services**: hypridle, voxtype and the XR watcher are
  `WantedBy=graphical-session.target`. Hyprland starts without a session
  manager, so both autostart trees run `smplos-session-services`, which
  imports the environment and starts `smplos-session.target` (bound to
  `graphical-session.target`). It then restarts any enabled session service
  that is not running and notifies when one still fails (power timers at
  every login). Never start these daemons bare from autostart.
* **Keybindings**: edit `src/shared/configs/smplos/bindings.conf` (hyprlang).
  The Lua side reads the exact same file via `bindings_loader.lua`.
* **Theme variables**: edit by running `theme-set <name>`. Both providers pick
  up the new values on next reload / restart.
* **Window/layer rules**: edit either `windows.conf` *or* `windows.lua`,
  depending on which provider is active. If you want a change to apply to
  both providers (the normal case during the transition), edit both. The Lua
  file is intentionally a one-to-one translation, so a diff between
  `windows.conf` and `windows.lua` should show only translation noise.

## monitors.conf contract

`~/.config/hypr/monitors.conf` is the saved display layout. Settings → Display
and `monitors_loader.lua` both follow this contract, so the saved file, the
Settings UI and the live layout cannot disagree silently.

* **Location and ownership**: always `$HOME/.config/hypr/monitors.conf`
  (`hyprland.conf` and `hyprland.lua` hard-code it; `XDG_CONFIG_HOME` is not
  consulted). The user and Settings own it. Updates never replace it, the
  ISO ships none, and a missing file means Hyprland's preferred defaults.
* **Grammar**: hyprlang `monitor =` lines only. `#` starts a comment anywhere
  on a line and `##` is a literal `#`. Fields are split on commas and trimmed.
  `$variables`, `source =`, `monitorv2` blocks and other keywords are not
  supported in this file.
  * `SEL, MODE, POSITION, SCALE[, KEY, VALUE]...` creates a fresh rule.
    KEY is `transform` (0–7), `mirror`, `bitdepth`, `cm`, `sdrbrightness`,
    `sdrsaturation`, `vrr` or `icc`; reading stops at the first empty KEY.
  * `SEL, disable` or `SEL, disabled` creates a fresh disabled rule.
  * `SEL, transform, N` changes an earlier rule with the identical selector
    (the built-in catch-all counts) and is ignored when there is none.
  * `SEL, addreserved, TOP, BOTTOM, LEFT, RIGHT` changes an earlier rule in
    place or creates one with that reserved area. (hyprlang drops the area
    when no rule exists; the Lua loader keeps it.)
* **Selectors and precedence**: SEL is a connector (`DP-3`), `desc:` followed
  by a description prefix (`desc:Dell Inc. DELL P2412H KG49T35D59GU`), or
  empty for the catch-all. Hyprland uses the **last** rule that matches a
  display; the catch-all applies only when no named rule matches. A full or
  disable line replaces an earlier rule with the identical selector and moves
  it to the end, as does a standalone `transform`.
* **What Settings writes**: one full line per enabled physical display, keyed
  by `desc:<make model serial>` when that description is unique and not a
  prefix of another display's description (so the rule survives connector
  renames such as DP-3 becoming DP-4), otherwise by connector. Scale keeps up
  to six decimals and transform keeps the exact value 0–7. Lines for displays
  that are disconnected, disabled, mirrored or virtual (`HEADLESS-*` outputs
  created for XR glasses), comments and the catch-all are preserved; valid
  extra options (except `mirror`) and `addreserved` lines of a rewritten
  display are carried over. Apply refuses when the displays or the file
  changed since editing began. The file is replaced atomically after a
  timestamped `monitors.conf.bak-*` copy (newest five kept), then Settings
  runs `hyprctl reload` and re-reads the live state to verify what Hyprland
  applied.
* **Loading**: under Lua, `monitors_loader.lua` turns the file into exactly
  one `hl.monitor()` call per selector, in last-definition order, with
  hyprlang's fresh-rule semantics (a later full line re-enables a display and
  resets its transform). Numeric scales are normalised as before. Invalid or
  unknown options and malformed modifier lines are logged and skipped rather
  than handed to Hyprland, so an update cannot turn previously ignored content
  into a config-error banner. `hyprland.lua` isolates loader failures so
  bindings and autostart still load. The hyprlang entry point sources the same
  file after its catch-all, so a catch-all saved in `monitors.conf` wins under
  both providers.
* **Login guard**: `start-hyprland` runs `monitors-guard` first. Only a file
  that would leave every connected display disabled is treated as corrupt
  and restored from the newest usable backup or moved aside.

## Long-term plan

Once Lua has been verified stable across the install base (a release or two),
the `.conf` files can be deleted and `bindings.conf` can stay as the sole
shared format. Until then, keep both in sync.
