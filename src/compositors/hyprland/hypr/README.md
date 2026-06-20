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

* **Keybindings**: edit `src/shared/configs/smplos/bindings.conf` (hyprlang).
  The Lua side reads the exact same file via `bindings_loader.lua`.
* **Theme variables**: edit by running `theme-set <name>`. Both providers pick
  up the new values on next reload / restart.
* **Window/layer rules**: edit either `windows.conf` *or* `windows.lua`,
  depending on which provider is active. If you want a change to apply to
  both providers (the normal case during the transition), edit both. The Lua
  file is intentionally a one-to-one translation, so a diff between
  `windows.conf` and `windows.lua` should show only translation noise.

## Long-term plan

Once Lua has been verified stable across the install base (a release or two),
the `.conf` files can be deleted and `bindings.conf` can stay as the sole
shared format. Until then, keep both in sync.
