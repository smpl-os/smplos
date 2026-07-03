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
        -- Native scrolling layout (Hyprland 0.55+). Replaces the old custom
        -- smplscroll plugin, which the 0.55 layout-API rewrite obsoleted.
        layout           = "scrolling",
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

    -- Scrolling (niri/PaperWM-style) layout tuning.
    -- Goal: never resize a window when another opens. Every column is a fixed
    -- 95% of the screen, so an app like Blender keeps its exact aspect ratio for
    -- its whole lifetime. Opening a second window slides it in flush to the
    -- right edge, leaving a thin sliver of the previous window on the left.
    scrolling = {
        -- ON: a lone window fills the whole work area (no dead space on the
        -- sides). When a second window opens, the first snaps to column_width
        -- (a small 5% adjustment at 0.95) so the newcomer can slide in.
        fullscreen_on_one_column = true,
        -- Fixed width for every column once there is more than one. 0.95 = 95%
        -- of the work area, so the remaining 5% shows the neighbouring window's
        -- sliver as the tape scrolls.
        column_width             = 0.95,
        -- 1 = fit the focused column flush into view (touches an edge) rather
        -- than centering it, so the newest window sits against the right edge.
        focus_fit_method         = 1,
        -- Auto-scroll so the focused window is brought into view.
        follow_focus             = true,
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

-- ── Hyprtasking overview plugin (niri-style workspace overview) ─────────────
-- Styling for the workspace overview (Super+Tab). Wrapped in pcall so that if
-- the plugin is not loaded yet at parse time the rest of the config is safe.
--   layout=grid, cols=1  -> workspaces stack vertically as rows, each row's
--                           windows appear as columns (niri-like).
--   bg_color 0xff000000  -> opaque black backdrop (matrix theme; avoids the
--                           plugin's default blue).
--   select_button 0x110  -> LEFT mouse click enters a workspace (navigate).
--   drag_button   0x117  -> VIEW-ONLY: pointed at BTN_TASK, an unused button
--                           on ordinary mice, so left/right drag no longer
--                           grabs and rearranges windows. The overview stays a
--                           navigation surface — click a workspace to enter it.
pcall(function()
    hl.config({
        plugin = {
            hyprtasking = {
                layout          = "grid",
                bg_color        = 0xff000000,
                gap_size        = 8,
                border_size     = 2,
                exit_on_hovered = true,
                drag_button     = 0x117,  -- BTN_TASK (unused) → disables drag-rearrange
                select_button   = 0x110,  -- left mouse: enter workspace
                grid = {
                    rows = 3,
                    cols = 1,
                },
            },
        },
    })
end)

-- Scroll wheel navigates workspace rows while the overview is open.
-- The grid layout ignores the mouse wheel (only the linear layout pans on
-- scroll), so without this the wheel falls through to the window content under
-- the cursor. These binds are NON-CONSUMING and gated on is_active(): when the
-- overview is closed they do nothing and normal scrolling in apps is untouched;
-- when it's open, wheel-down/up step to the workspace row below/above.
pcall(function()
    local function ht_scroll(dir)
        return function()
            if hl.plugin.hyprtasking.is_active() then
                hl.plugin.hyprtasking.move(dir)
            end
        end
    end
    hl.bind("mouse_down", ht_scroll("down"), { non_consuming = true })
    hl.bind("mouse_up",   ht_scroll("up"),   { non_consuming = true })
    -- Ctrl+wheel pans the scrolling-layout column tape (the windows) side to
    -- side while the overview is open. hyprtasking's grid is workspace-level
    -- only, so "windows horizontally" maps to the scrolling layout, not to
    -- grid columns (which would just show empty phantom workspaces).
    local function ht_col(msg)
        return function()
            if hl.plugin.hyprtasking.is_active() then
                hl.dsp.layout(msg)
            end
        end
    end
    hl.bind("CTRL + mouse_down", ht_col("move +col"), { non_consuming = true })
    hl.bind("CTRL + mouse_up",   ht_col("move -col"), { non_consuming = true })
end)
