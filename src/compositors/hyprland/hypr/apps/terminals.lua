-- Terminal-specific rules.
-- Mirrors src/compositors/hyprland/hypr/apps/terminals.conf.

-- st-wl sets app_id to "terminal" (see config.h termclass)
hl.window_rule({
    match = { class = "(terminal|com.mitchellh.ghostty)" },
    tag = "+terminal",
})

-- st-wl uses ALPHA_PATCH — it manages its own per-pixel alpha.
-- Compositor opacity must be exactly 1.0 so it doesn't multiply on top of the
-- terminal's own transparency and dim text. This explicit class-based override
-- is belt-and-suspenders on top of the self-managed-alpha tag in windows.lua,
-- and is placed here (loaded after windows.lua via apps.lua) so it wins last.
hl.window_rule({
    match = { class = "^(terminal|com\\.mitchellh\\.ghostty)$" },
    opacity = "1.0 override 1.0 override",
})
