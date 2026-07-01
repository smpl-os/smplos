-- Look-and-feel: general, decoration, group, dwindle, master, misc, cursor,
-- animations + curves. Mirrors src/compositors/hyprland/hypr/looknfeel.conf.

local theme = require("theme")
local n = tonumber  -- shorthand for converting theme string values to numbers

hl.config({
    general = {
        gaps_in     = n(theme.themeGapsIn),
        gaps_out    = n(theme.themeGapsOut),
        border_size = n(theme.themeBorderSize),

        col = {
            active_border   = theme.color(theme.activeBorderColor),
            inactive_border = theme.color(theme.inactiveBorderColor),
        },

        resize_on_border = true,
        allow_tearing    = false,
        -- SMPLSCROLL DISABLED 2026-06-30 (paused for Hyprland 0.55+ upgrade) -- was: layout = "scroll"
        layout           = "dwindle",
    },

    decoration = {
        rounding = n(theme.themeRounding),

        -- Opacity is controlled entirely via windowrules in windows.lua.
        -- Decoration opacity must be 1.0 (neutral) to avoid double-multiplication
        -- with the windowrule opacity (e.g. 0.75 × 0.75 = 0.56 instead of 0.75).
        active_opacity     = 1.0,
        inactive_opacity   = 1.0,
        fullscreen_opacity = 1.0,

        shadow = {
            enabled      = true,
            range        = 2,
            render_power = 3,
            color        = "rgba(1a1a1aee)",
        },

        blur = {
            enabled           = true,
            size              = n(theme.themeBlurSize),
            passes            = n(theme.themeBlurPasses),
            special           = true,
            new_optimizations = true,
            brightness        = 1.0,
            contrast          = 1.0,
            vibrancy          = 1.0,
            vibrancy_darkness = 1.0,
            noise             = 0.02,
            popups            = true,
            xray              = false,
        },
    },

    group = {
        col = {
            border_active   = theme.color(theme.activeBorderColor),
            border_inactive = theme.color(theme.inactiveBorderColor),
            -- border_locked_active / border_locked_inactive are intentionally
            -- omitted: Hyprland's text parser accepts -1 as a sentinel meaning
            -- "fall back to border_active/inactive", but the Lua API rejects -1
            -- as an invalid color. Omitting yields the same fallback behaviour.
        },

        groupbar = {
            font_size            = 12,
            font_family          = "monospace",
            font_weight_active   = "ultraheavy",
            font_weight_inactive = "normal",

            indicator_height = 0,
            indicator_gap    = 5,
            height           = 22,
            gaps_in          = 5,
            gaps_out         = 0,

            text_color          = "rgb(ffffff)",
            text_color_inactive = "rgba(ffffff90)",

            col = {
                active   = "rgba(00000040)",
                inactive = "rgba(00000020)",
            },

            gradients                = true,
            gradient_rounding        = 8,
            gradient_round_only_edges = false,
        },
    },

    dwindle = {
        -- pseudotile (true in looknfeel.conf) is omitted: the Lua schema doesn't
        -- expose dwindle:pseudotile. It defaults off here; toggle with SUPER+P.
        preserve_split = true,
        force_split    = 2,     -- always split on the right
    },

    master = {
        new_status = "slave",
    },

    misc = {
        disable_hyprland_logo    = true,
        disable_splash_rendering = true,
        focus_on_activate        = true,
        anr_missed_pings         = 3,
        key_press_enables_dpms   = true,
        mouse_move_enables_dpms  = true,
    },

    cursor = {
        hide_on_key_press        = true,
        warp_on_change_workspace = false,
        no_warps                 = true,
        -- Force software cursors. virtio-gpu (QEMU/VMs) doesn't support hardware
        -- cursor planes reliably, causing crashes or invisible cursors.
        no_hardware_cursors = 1,
    },

    animations = { enabled = true },
})

-- Bezier curves
hl.curve("easeOutQuint",   { type = "bezier", points = { {0.23, 1},    {0.32, 1} } })
hl.curve("easeInOutCubic", { type = "bezier", points = { {0.65, 0.05}, {0.36, 1} } })
hl.curve("linear",         { type = "bezier", points = { {0, 0},       {1, 1}    } })
hl.curve("almostLinear",   { type = "bezier", points = { {0.5, 0.5},   {0.75, 1} } })
hl.curve("quick",          { type = "bezier", points = { {0.15, 0},    {0.1, 1}  } })

-- Animation entries
local animations = {
    { leaf = "global",        speed = 10,   bezier = "default"      },
    { leaf = "border",        speed = 5.39, bezier = "easeOutQuint" },
    { leaf = "windows",       speed = 4.79, bezier = "easeOutQuint" },
    { leaf = "windowsIn",     speed = 4.1,  bezier = "easeOutQuint", style = "popin 20%" },
    { leaf = "windowsOut",    speed = 1.49, bezier = "linear",       style = "popin 20%" },
    { leaf = "fadeIn",        speed = 1.73, bezier = "almostLinear" },
    { leaf = "fadeOut",       speed = 1.46, bezier = "almostLinear" },
    { leaf = "fade",          speed = 3.03, bezier = "quick"        },
    { leaf = "layers",        speed = 3.81, bezier = "easeOutQuint" },
    { leaf = "layersIn",      speed = 4,    bezier = "easeOutQuint", style = "popin 20%" },
    { leaf = "layersOut",     speed = 1.5,  bezier = "linear",       style = "popin 20%" },
    { leaf = "fadeLayersIn",  speed = 1.79, bezier = "almostLinear" },
    { leaf = "fadeLayersOut", speed = 1.39, bezier = "almostLinear" },
    { leaf = "workspaces",    speed = 4,    bezier = "easeOutQuint", style = "slide" },
}
for _, a in ipairs(animations) do
    a.enabled = true
    hl.animation(a)
end

-- Style Gum confirm prompts to match terminal theme
hl.env("GUM_CONFIRM_PROMPT_FOREGROUND",     "6")  -- cyan
hl.env("GUM_CONFIRM_SELECTED_FOREGROUND",   "0")  -- black
hl.env("GUM_CONFIRM_SELECTED_BACKGROUND",   "2")  -- green
hl.env("GUM_CONFIRM_UNSELECTED_FOREGROUND", "0")  -- black
hl.env("GUM_CONFIRM_UNSELECTED_BACKGROUND", "8")  -- dark grey
