-- Steam window rules.
-- Mirrors src/compositors/hyprland/hypr/apps/steam.conf.

hl.window_rule({ match = { class = "steam" }, float = true })
hl.window_rule({
    match = { class = "steam", title = "Steam" },
    center = true, size = "1100 700",
})
hl.window_rule({
    match = { class = "steam", title = "Friends List" },
    size = "460 800",
})
hl.window_rule({ match = { class = "steam" }, idle_inhibit = "fullscreen" })
