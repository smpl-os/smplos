-- Environment variables exported to spawned processes by Hyprland.
-- Mirrors src/compositors/hyprland/hypr/envs.conf.

-- Terminal
hl.env("TERMINAL", "terminal")

-- smplOS user scripts (workspace-group, window-to-group, etc.)
hl.env("PATH", (os.getenv("HOME") or "") .. "/.local/share/smplos/bin:" .. (os.getenv("PATH") or ""))

-- Cursor
hl.env("XCURSOR_SIZE",    "24")
hl.env("HYPRCURSOR_SIZE", "24")
hl.env("XCURSOR_THEME",   "Adwaita")

-- Force all apps to use Wayland
hl.env("GDK_BACKEND",                "wayland,x11,*")
hl.env("QT_QPA_PLATFORM",            "wayland;xcb")
hl.env("QT_STYLE_OVERRIDE",          "kvantum")
hl.env("SDL_VIDEODRIVER",            "wayland")
hl.env("MOZ_ENABLE_WAYLAND",         "1")
hl.env("ELECTRON_OZONE_PLATFORM_HINT", "wayland")
hl.env("OZONE_PLATFORM",             "wayland")
hl.env("XDG_SESSION_TYPE",           "wayland")

-- GTK file dialogs (rendered by xdg-desktop-portal-gtk) -- force dark Adwaita.
-- theme-set overrides this at runtime for light themes.
hl.env("GTK_THEME", "Adwaita:dark")

-- Allow better support for screen sharing (Google Meet, Discord, etc.)
hl.env("XDG_CURRENT_DESKTOP", "Hyprland")
hl.env("XDG_SESSION_DESKTOP", "Hyprland")

-- Use XCompose file
hl.env("XCOMPOSEFILE", "~/.XCompose")

-- Compositor-level settings that live in the same conceptual block as envs.
hl.config({
    xwayland  = { force_zero_scaling = true },
    ecosystem = { no_update_news     = true },
})
