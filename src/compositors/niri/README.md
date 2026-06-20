# smplOS Niri Compositor

Parallel Wayland session that ships alongside Hyprland for A/B comparison and
optional permanent use. **Hyprland remains the default**; nothing in
`src/compositors/hyprland/` is modified.

## Files

```
config.kdl             ← base config (input, layout, animations, gestures, env)
binds.kdl              ← generated from src/shared/configs/smplos/bindings.conf
window-rules.kdl       ← float/position/opacity per app_id
layer-rules.kdl        ← blur/shadow for EWW namespaces
theme.kdl              ← colors/borders/shadow (overwritten by theme-set)
packages.txt           ← niri + xwayland-satellite + swaylock-effects + swayidle
postinstall.sh         ← niri-specific system setup
```

## Generated vs hand-written

| File | Generator | Edit it? |
|---|---|---|
| `binds.kdl` | `src/shared/bin/bindings-to-niri.sh` | NO — edit `bindings.conf` |
| `theme.kdl` | `theme-set` (from per-theme `niri-theme.kdl`) | NO — edit `_templates/niri-theme.kdl.tpl` |
| `config.kdl` | hand-written | YES |
| `window-rules.kdl` | hand-written | YES |
| `layer-rules.kdl` | hand-written | YES |

## Known divergences from Hyprland behavior

These are intentional — niri's model differs from Hyprland's:

1. **Workspaces are per-output** (niri-native). `workspace-group` style "switch
   ALL monitors together to workspace N" doesn't exist. `Super+1..0` switches
   the focused output's workspace only.
2. **No runtime binding changes.** Popup click-out dismissal that Hyprland
   does via `hyprctl keyword bindn ", mouse:272, ..."` isn't possible.
   EWW popups dismiss on `Esc` only.
3. **Lock/idle:** `swaylock` + `swayidle` instead of `hyprlock`/`hypridle`
   (the latter are Hyprland-protocol-specific and won't run reliably on niri).
4. **Window positioning by formula** (`monitor_w-window_w-2`) isn't supported;
   niri uses `default-window-position` per rule (relative anchor).
5. **Scrolling layout actions** (`focus-column-left`, `consume-window-into-column`)
   replace Hyprland dwindle dispatchers. Mapped to nearest keys.

## How to switch sessions

From inside any session: `switch-compositor [hyprland|niri]` (no arg toggles).
Writes `~/.config/smplos/compositor`, exits the current compositor, and greetd
re-launches into the chosen one. See `src/shared/bin/switch-compositor`.
