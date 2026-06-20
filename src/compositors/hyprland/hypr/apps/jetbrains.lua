-- JetBrains IDE quirks (splash screens, find popups, autocomplete).
-- Mirrors src/compositors/hyprland/hypr/apps/jetbrains.conf.

-- Splash screen — fix weird positioning, prevent annoying focus takeovers
hl.window_rule({
    match = { class = "^(jetbrains-.*)$", title = "^(splash)$", float = 1 },
    tag = "+jetbrains-splash",
})
hl.window_rule({ match = { tag = "jetbrains-splash" }, center = true, no_focus = true, border_size = 0 })

-- Popups / find windows: center them
hl.window_rule({
    match = { class = "^(jetbrains-.*)", title = "^()$", float = 1 },
    tag = "+jetbrains",
})
hl.window_rule({ match = { tag = "jetbrains" }, center = true })

-- Allow typing in popup dialogs (search window, new file, etc.)
hl.window_rule({ match = { tag = "jetbrains" }, stay_focused = true, border_size = 0 })

-- min_size — for some reason tag:jetbrains doesn't work here, match class directly
hl.window_rule({
    match = { class = "^(jetbrains-.*)", title = "^()$", float = 1 },
    min_size = "(monitor_w*0.5) (monitor_h*0.5)",
})

-- Disable flicker when autocomplete or tooltips appear
hl.window_rule({
    match = { class = "^(jetbrains-.*)$", title = "^(win.*)$", float = 1 },
    no_initial_focus = true,
})

-- Disable mouse focus (JetBrains tooltips steal focus on hover)
hl.window_rule({ match = { class = "^(jetbrains-.*)$" }, no_follow_mouse = true })
