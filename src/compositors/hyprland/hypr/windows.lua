-- smplOS window + layer rules.
-- Mirrors src/compositors/hyprland/hypr/windows.conf, but expresses the
-- repetitive messenger rules as Lua loops to demonstrate the new system's
-- DRY benefits.

local theme = require("theme")

-- ============================================================================
-- Layer rules: EWW bar + popups + Rofi
-- ============================================================================

-- Apply the same blur profile to every smplOS EWW layer surface.
local eww_namespaces = {
    "eww-bar", "eww-calendar-popup", "eww-quick-settings",
    "eww-notification-hub", "eww-usb-popup",
}
for _, ns in ipairs(eww_namespaces) do
    hl.layer_rule({ match = { namespace = ns }, blur = true })
    hl.layer_rule({ match = { namespace = ns }, blur_popups = true })
    hl.layer_rule({ match = { namespace = ns }, ignore_alpha = 0.1 })
    hl.layer_rule({ match = { namespace = ns }, xray = false })
end

-- Rofi launcher (layer surface; needs layer rules not window rules)
hl.layer_rule({ match = { namespace = "rofi" }, animation = "slide left" })
hl.layer_rule({ match = { namespace = "rofi" }, order = -1 })
hl.layer_rule({ match = { namespace = "rofi" }, blur = true })
hl.layer_rule({ match = { namespace = "rofi" }, blur_popups = true })
hl.layer_rule({ match = { namespace = "rofi" }, ignore_alpha = 0.1 })

-- Rofi dialogs (keybind-help, theme-picker use -normal-window for popin animation)
local popup_opacity_str = theme.themePopupOpacity .. " override "
                       .. theme.themePopupOpacity .. " override"
hl.window_rule({
    match = { class = "^(rofi)$" },
    float = true, center = true, pin = true,
    animation = "popin",
    opacity = popup_opacity_str,
})

-- ============================================================================
-- Window rules
-- ============================================================================

-- Prevent maximize from apps
hl.window_rule({ match = { class = ".*" }, suppress_event = "maximize" })

-- ── Opacity model ──────────────────────────────────────────────────────────
--
-- Windows fall into one of three opacity classes, expressed as tags:
--
--   (untagged)         — regular apps. Theme active/inactive opacity. Default.
--   compositor-opaque  — Hyprland forces 1.0 (media, video webapps, pip, fs).
--   self-managed-alpha — App owns its own alpha channel (st ALPHA_PATCH, Slint
--                        ARGB surfaces). Hyprland must pass 1.0 override so the
--                        two don't compound (e.g. 0.85×0.85≈0.72). Adding a new
--                        Slint app? Append it to the slint_apps list below.

-- ── Tag assignment ────────────────────────────────────────────────────────

-- Terminals (st ALPHA_PATCH renders its own semi-transparent background)
hl.window_rule({
    match = { class = "^(terminal|st|st-256color|com\\.mitchellh\\.ghostty)$" },
    tag = "+self-managed-alpha",
})

-- Rust/Slint popup apps (ARGB surface, opacity set in-app)
local slint_apps = {
    "start-menu", "notif-center", "settings",
    "app-center", "webapp-center", "sync-center", "smpl-calendar",
}
hl.window_rule({
    match = { class = "^(" .. table.concat(slint_apps, "|") .. ")$" },
    tag = "+self-managed-alpha",
})

-- Media and special — always fully opaque
hl.window_rule({
    match = { class = "^(mpv|imv|vlc|zoom|org\\.kde\\.kdenlive|com\\.obsproject\\.Studio|com\\.github\\.PintaProject\\.Pinta|org\\.gnome\\.NautilusPreviewer|steam|qemu)$" },
    tag = "+compositor-opaque",
})
hl.window_rule({ match = { tag = "pip" },           tag = "+compositor-opaque" })
hl.window_rule({ match = { fullscreen = 1 },        tag = "+compositor-opaque" })

-- Wine/Proton apps (DAWs, creative tools) — always fully opaque.
-- Wine window classes can be "foo.exe", "foo.Exe", "Wine", "wine", or just
-- the app name. Catch them all with .exe (case-insensitive) + "wine" class.
hl.window_rule({ match = { class = "(?i)\\.exe$" }, tag = "+compositor-opaque" })
hl.window_rule({ match = { class = "(?i)^wine$" }, tag = "+compositor-opaque" })

-- FL Studio spawns a blank 800x800 XWayland surface with no title — hide it.
hl.window_rule({
    match = { class = "^(fl64\\.exe|FL64\\.exe)$", title = "^$" },
    opacity = "0.0 override 0.0 override",
})

-- Video webapps
hl.window_rule({
    match = { initial_title = "((?i)(?:[a-z0-9-]+\\.)*youtube\\.com_/|app\\.zoom\\.us_/wc/home)" },
    tag = "+compositor-opaque",
})

-- ── Opacity rules (one per class, nothing else sets opacity) ────────────────

local default_opacity = theme.themeOpacityActive .. " override "
                     .. theme.themeOpacityInactive .. " override"

-- Default: theme opacity for all windows
hl.window_rule({ match = { class = ".*" }, opacity = default_opacity })

-- Browsers: force same value active & inactive (override prevents focus-dim)
hl.window_rule({ match = { tag = "chromium-based-browser" }, opacity = default_opacity })
hl.window_rule({ match = { tag = "firefox-based-browser" },  opacity = default_opacity })

-- compositor-opaque: always fully opaque
hl.window_rule({ match = { tag = "compositor-opaque" },  opacity = "1.0 override 1.0 override" })

-- self-managed-alpha: pass through untouched — app owns its ARGB alpha
hl.window_rule({ match = { tag = "self-managed-alpha" }, opacity = "1.0 override 1.0 override" })

-- Fix some dragging issues with XWayland
hl.window_rule({
    match = {
        class    = "^$",
        title    = "^$",
        xwayland = 1,
        float    = 1,
        fullscreen = 0,
        pin      = 0,
    },
    no_focus = true,
})

-- ============================================================================
-- Application-specific rules
-- ============================================================================

-- File picker dialogs
hl.window_rule({ match = { title = "^(Open File)(.*)$" }, float = true, center = true })
hl.window_rule({ match = { title = "^(Save File)(.*)$" }, float = true, center = true })
hl.window_rule({ match = { title = "^(Select)(.*)$"   }, float = true })

-- Calculator
hl.window_rule({
    match = { class = "^(gnome-calculator)$" },
    float = true, size = "400 500",
})

-- Image viewer
hl.window_rule({ match = { class = "^(imv)$" }, float = true, center = true })

-- Pavucontrol
hl.window_rule({
    match = { class = "^(pavucontrol)$" },
    float = true, size = "800 600",
})

-- Network Manager
hl.window_rule({ match = { class = "^(nm-connection-editor)$" }, float = true })

-- Polkit
hl.window_rule({
    match = { class = "^(polkit-gnome-authentication-agent-1)$" },
    float = true, center = true,
})

-- Floating terminal windows (theme picker, etc.)
hl.window_rule({
    match = { class = "^(floating)$" },
    float = true, center = true, size = "500 600",
})

-- Start Menu (bottom-left, above bar)
hl.window_rule({
    match = { class = "^(start-menu)$" },
    float = true,
    move = "2 (monitor_h-window_h-37)",
    no_shadow = true,
    animation = "slide left",
    stay_focused = true,
})

-- Notification Center
hl.window_rule({
    match = { class = "^(notif-center)$" },
    float = true,
    move = "(monitor_w-window_w-2) (monitor_h-window_h-34)",
    no_shadow = true,
    animation = "slide",
})

-- Settings
hl.window_rule({
    match = { class = "^(settings)$" },
    float = true, center = true,
    no_shadow = true,
    animation = "popin",
})

-- smpl Calendar (bottom-right, above bar)
hl.window_rule({
    match = { class = "^(smpl-calendar)$" },
    float = true,
    move = "(monitor_w-window_w-2) (monitor_h-window_h-34)",
    no_shadow = true,
    animation = "slide",
    stay_focused = true,
})

-- ============================================================================
-- Messengers — float + center at a comfortable chat size
-- ============================================================================
--
-- One table drives ALL messenger rules: tag assignment, opacity, float layout.
-- To add a new messenger app, just append its match-class regex to this list.

local messengers = {
    -- Native apps
    "^(signal)$",
    "^(org\\.telegram\\.desktop|telegramdesktop)$",
    "^(Slack|slack)$",
    "^(discord|WebCord|vesktop)$",
    -- Chromium --app webapps (class = "brave-<domain>-Default")
    "^(brave-discord)(.*)$",
    "^(brave-web\\.whatsapp)(.*)$",
    "^(brave-web\\.telegram)(.*)$",
    "^(brave-teams\\.microsoft\\.com)(.*)$",
}
-- github.com is a special case (centered + larger) — handled below.

-- Tag assignment + default float layout
for _, class in ipairs(messengers) do
    hl.window_rule({ match = { class = class }, tag = "+messenger" })
    hl.window_rule({
        match = { class = class },
        float = true,
        move  = "(monitor_w-482) (monitor_h-754)",
        size  = "480 720",
    })
end
-- GitHub webapp also belongs to +messenger tag (per windows.conf)
hl.window_rule({ match = { class = "^(brave-github\\.com)(.*)$" }, tag = "+messenger" })
hl.window_rule({
    match = { class = "^(brave-github\\.com)(.*)$" },
    float = true, center = true, size = "1200 800",
})

-- Default opacity for all messenger windows
local messenger_opacity = theme.themeMessengerOpacity .. " override "
                       .. theme.themeMessengerOpacity .. " override"
hl.window_rule({ match = { tag = "messenger" }, opacity = messenger_opacity })

-- Per-app opacity overrides (last matching rule wins, so these come after the
-- tag rule). Uncomment by adding entries to this table.
local opacity_overrides = {
    -- ["^(signal)$"]                                   = "0.70 override 0.70 override",
    -- ["^(org\\.telegram\\.desktop|telegramdesktop)$"] = "0.75 override 0.75 override",
    -- ["^(Slack|slack)$"]                              = "0.80 override 0.80 override",
    -- ["^(discord|WebCord|vesktop)$"]                  = "0.65 override 0.65 override",
    -- ["^(brave-teams\\.microsoft\\.com)(.*)$"]        = "0.80 override 0.80 override",
    -- ["^(brave-web\\.whatsapp)(.*)$"]                 = "0.75 override 0.75 override",
    ["^(brave-discord)(.*)$"]  = "0.90 override 0.70 override",
    ["^(brave-github\\.com)(.*)$"] = "0.90 override 0.70 override",
}
for class, opacity in pairs(opacity_overrides) do
    hl.window_rule({ match = { class = class }, opacity = opacity })
end
