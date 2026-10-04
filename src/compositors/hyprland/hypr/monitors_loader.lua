-- monitors_loader.lua — apply ~/.config/hypr/monitors.conf under the Lua
-- provider with the same meaning the hyprlang provider gives it.
--
-- monitors.conf stays in hyprlang syntax because Settings → Display writes it
-- and hyprland.conf sources it directly. Settings applies a saved layout with
-- `hyprctl reload`, which clears Hyprland's monitor rules and re-runs this file.
-- The full contract shared with Settings is documented in README.md
-- ("monitors.conf contract").
--
--   monitor = SEL, MODE, POSITION, SCALE[, KEY, VALUE]...  fresh rule
--   monitor = SEL, disable | disabled                     fresh disabled rule
--   monitor = SEL, transform, N           changes an existing SEL rule only
--   monitor = SEL, addreserved, TOP, BOTTOM, LEFT, RIGHT
--
-- SEL is a connector (DP-3), desc:<description prefix>, or empty (catch-all).
-- '#' starts a comment anywhere on a line and '##' is a literal '#'.
-- Hyprland uses the LAST rule matching a display, so every selector becomes one
-- hl.monitor() call, ordered by its last full/disable/transform definition.
-- Other keywords, $variables and source= are not supported in this file.
-- Invalid or unknown KEY/VALUE options are logged and skipped instead of being
-- handed to Hyprland, so an OS update never turns a line the previous loader
-- ignored into a config-error banner. MODE and POSITION pass through as-is.

local M = {}

-- hyprlang's monitor options and the values hl.monitor() accepts for them.
local INTEGER_RANGES = { transform = { 0, 7 }, bitdepth = {}, vrr = { -1, 3 } }
local NUMBER_KEYS = { sdrbrightness = true, sdrsaturation = true }
local STRING_KEYS = { mirror = true, icc = true }
-- NCMType::fromString in Hyprland 0.56.
local CM_VALUES = { auto = true, srgb = true, wide = true, edid = true, hdr = true,
                    hdredid = true, dcip3 = true, dp3 = true, adobe = true }

local function trim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end

-- hyprlang only accepts plain decimal integers here (isNumber without floats).
local function to_integer(value)
    if type(value) ~= "string" or not value:match("^%-?%d+$") then return nil end
    local n = tonumber(value)
    return math.tointeger and math.tointeger(n) or n
end

-- Mirrors hyprlang's CConfig::parseLine comment handling, including the way
-- the search resumes two characters after an escaped "##".
local function strip_comment(line)
    line = trim(line)
    local pos = line:find("#", 1, true)
    if pos == 1 then return "" end
    while pos do
        if line:sub(pos + 1, pos + 1) == "#" then
            local resume = pos + 2
            line = line:sub(1, pos) .. line:sub(pos + 2)
            pos = line:find("#", resume, true)
        else
            line = line:sub(1, pos - 1)
            break
        end
    end
    return trim(line)
end

local function split_fields(rhs)
    local out = {}
    for field in (rhs .. ","):gmatch("([^,]*),") do
        out[#out + 1] = trim(field)
    end
    return out
end

-- Returns the value hl.monitor() expects (Hyprland rejects integers given as
-- Lua floats or strings), or nil when the option must be skipped.
local function typed_value(key, value)
    local range = INTEGER_RANGES[key]
    if range then
        local n = to_integer(value)
        if n and (not range[1] or (n >= range[1] and n <= range[2])) then return n end
        return nil
    end
    if NUMBER_KEYS[key] then return tonumber(value) end
    if key == "cm" then return CM_VALUES[value] and value or nil end
    if STRING_KEYS[key] and value ~= "" then return value end
    return nil
end

local function report(path, lineno, message)
    print(string.format("monitors_loader: %s:%d: %s", path, lineno, message))
end

local function parse(path, f)
    local rules, order = {}, {}

    local function move_to_end(sel)
        for i = #order, 1, -1 do
            if order[i] == sel then table.remove(order, i) end
        end
        order[#order + 1] = sel
    end

    local lineno = 0
    for raw in f:lines() do
        lineno = lineno + 1
        local ok, err = pcall(function()
            local line = strip_comment(raw)
            local rhs = line:match("^monitor%s*=(.*)$")
            if not rhs then return end
            local p = split_fields(rhs)
            local sel, action = p[1] or "", p[2] or ""

            if action == "disable" or action == "disabled" then
                rules[sel] = { disabled = true }
                move_to_end(sel)
            elseif action == "transform" then
                local transform = to_integer(p[3])
                if not rules[sel] and sel ~= "" then
                    report(path, lineno, "transform for '" .. sel .. "' has no earlier rule; ignored as in hyprlang")
                elseif not transform or transform < 0 or transform > 7 then
                    report(path, lineno, "invalid transform; previous value kept as in hyprlang")
                else
                    -- hyprland.lua/hyprland.conf define the catch-all before
                    -- this file, so hyprlang always finds an earlier "" rule.
                    rules[sel] = rules[sel] or {}
                    rules[sel].transform = transform
                    move_to_end(sel)
                end
            elseif action == "addreserved" then
                local top, bottom = to_integer(p[3]), to_integer(p[4])
                local left, right = to_integer(p[5]), to_integer(p[6])
                if not (top and bottom and left and right) then
                    report(path, lineno, "invalid addreserved values; ignored")
                    return
                end
                local reserved = { top = top, bottom = bottom, left = left, right = right }
                if rules[sel] then
                    rules[sel].reserved = reserved
                else
                    rules[sel] = { reserved = reserved }
                    order[#order + 1] = sel
                end
            else
                local rule = {
                    full = true,
                    mode = p[2] or "",
                    position = p[3] or "",
                    scale = p[4] or "",
                    transform = 0,
                    extras = {},
                }
                -- hyprlang stops at the first empty KEY; an empty VALUE is an error.
                local i = 5
                while p[i] and p[i] ~= "" do
                    local key, value = p[i], p[i + 1] or ""
                    local typed = typed_value(key, value)
                    if typed == nil then
                        report(path, lineno, "skipped invalid option '" .. key .. ", " .. value .. "'")
                    elseif key == "transform" then
                        rule.transform = typed
                    else
                        rule.extras[#rule.extras + 1] = { key, typed }
                    end
                    i = i + 2
                end
                rules[sel] = rule
                move_to_end(sel)
            end
        end)
        if not ok then report(path, lineno, tostring(err)) end
    end
    return rules, order
end

local function spec_for(sel, rule)
    local spec = { output = sel }
    if rule.full then
        -- Numeric scales are normalised as the previous loader did, so
        -- spellings like ".5" keep working; "auto"/"" pass through.
        spec.mode, spec.position = rule.mode, rule.position
        spec.scale = tonumber(rule.scale) or rule.scale
        spec.disabled = false
        for _, pair in ipairs(rule.extras) do spec[pair[1]] = pair[2] end
    elseif rule.disabled then
        spec.disabled = true
    end
    if rule.transform ~= nil then spec.transform = rule.transform end
    if rule.reserved then spec.reserved = rule.reserved end
    return spec
end

function M.load(path)
    local f = io.open(path, "r")
    if not f then return end
    local ok, rules, order = pcall(parse, path, f)
    f:close()
    if not ok then
        print("monitors_loader: " .. tostring(rules))
        return
    end
    for _, sel in ipairs(order) do
        local applied, err = pcall(hl.monitor, spec_for(sel, rules[sel]))
        if not applied then print("monitors_loader: " .. sel .. ": " .. tostring(err)) end
    end
end

return M
