-- aspect_column.lua — set scrolling:column_width per monitor at runtime.
--
-- Hyprland's scrolling layout exposes a single global column_width. On a
-- normal 16:9 monitor 0.95 gives the intended "sliver of the neighbor visible
-- on the edge" hint. On an ultrawide (21:9 or wider) that same 0.95 reveals
-- a large slab of the neighbour without any of its content — the worst of both
-- worlds. This module watches the focused monitor and rewrites
-- scrolling:column_width live so the geometry is aspect-appropriate:
--
--     aspect >= 2.8   (super-ultrawide, 32:9)   → 0.50   true 50/50 split
--     aspect >= 2.0   (ultrawide, 21:9)         → 0.65   big single + peek
--     otherwise       (16:9, portrait, square)  → 0.95   sliver hint (default)
--
-- Existing columns keep whatever width they were opened at (scrolling stores a
-- per-column width, so changing the layout-wide default only affects the NEXT
-- column). Combined with fullscreen_on_one_column = false in looknfeel, this
-- means opening a new window on any monitor never resizes anything already on
-- screen — the newcomer just slides in at the width that fits its monitor.

local M = {}

-- Compute the visible aspect ratio for a monitor, accounting for rotation.
-- Hyprland reports width/height as the physical panel dimensions; transform
-- 1 and 3 are 90°/270° rotations that swap the logical axes.
local function visible_aspect(mon)
    if not mon or not mon.width or not mon.height or mon.height == 0 then
        return 16 / 9
    end
    local w, h = mon.width, mon.height
    if mon.transform == 1 or mon.transform == 3 then
        w, h = h, w
    end
    return w / h
end

local function width_for_aspect(aspect)
    if aspect >= 2.8 then return 0.50 end
    if aspect >= 2.0 then return 0.65 end
    return 0.95
end

-- Cache the last applied value so a stream of monitor.focused events (e.g.
-- cursor drifting between two identical 16:9 panels) doesn't spam the setter.
local last_applied

local function apply(mon)
    if not mon then return end
    local width = width_for_aspect(visible_aspect(mon))
    if last_applied == width then return end
    last_applied = width
    -- Set the option in-process via the Lua API. We cannot shell out to
    -- `hyprctl keyword` from here: Hyprland 0.55+ refuses that command when
    -- the active config parser is Lua ("keyword can't work with non-legacy
    -- parsers. Use eval."). hl.config() accepts a partial config table and
    -- applies it live, which is the supported path.
    hl.config({ scrolling = { column_width = width } })
end

local function apply_active()
    apply(hl.get_active_monitor())
end

-- The monitor.focused callback receives the newly focused HL.Monitor. Fall
-- back to hl.get_active_monitor() if the payload shape is unexpected on a
-- particular Hyprland version.
hl.on("monitor.focused", function(mon)
    if type(mon) == "table" and mon.width then
        apply(mon)
    else
        apply_active()
    end
end)

-- Monitors aren't guaranteed to be enumerable before hyprland.start fires,
-- layout_changed covers live rotation/scale updates from Settings, and
-- config.reloaded fires on `hyprctl reload` so the width is re-asserted
-- after any config re-parse.
hl.on("hyprland.start",         apply_active)
hl.on("config.reloaded",        apply_active)
hl.on("monitor.added",          apply_active)
hl.on("monitor.layout_changed", apply_active)

return M
