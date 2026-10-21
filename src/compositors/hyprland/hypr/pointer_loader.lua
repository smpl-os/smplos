-- pointer_loader.lua — apply ~/.config/hypr/pointer.conf under the Lua
-- provider.
--
-- pointer.conf is hyprlang, like monitors.conf, because Settings → Mouse
-- writes it. Settings also changes the running compositor as its controls
-- move, so the file matters when Hyprland starts or reloads: input.lua has
-- just set its defaults and this puts the saved choices back on top. The
-- contract shared with Settings is documented in README.md
-- ("pointer.conf contract").
--
--   input {
--       sensitivity    = N                      -1 .. 1
--       accel_profile  = flat | adaptive | custom STEP POINT...
--       natural_scroll = true | false           (yes/no, on/off, 1/0 too)
--       scroll_factor  = N                      0.1 .. 10
--   }
--
-- Only those four options of a top-level input block are read, the way
-- Settings reads them; every other line, nested blocks such as touchpad { }
-- and the flat `input:option =` form are ignored. '#' starts a comment. The
-- last valid assignment of an option wins, and an option the file does not
-- set is left alone. A number outside its range is clamped to it. Anything
-- else that is not a valid value is logged and skipped instead of being
-- handed to Hyprland, so a hand edit cannot raise a config-error banner.

local M = {}

local ORDER = { "sensitivity", "accel_profile", "natural_scroll", "scroll_factor" }

local BOOLEANS = { ["true"] = true, yes = true, on = true, ["1"] = true,
                   ["false"] = false, no = false, off = false, ["0"] = false }

local function trim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end

local function report(path, lineno, message)
    print(string.format("pointer_loader: %s:%d: %s", path, lineno, message))
end

-- A plain decimal (0.4, -1, .5). tonumber() alone would also take 0x10 and 1e3.
local function to_number(text)
    if text:match("^[+-]?%d*%.?%d*$") and text:find("%d") then return tonumber(text) + 0.0 end
end

-- Each reader returns the value for hl.config(), plus an optional note for the
-- log; or nil and the reason the value is skipped.
local function number_reader(low, high)
    return function(text)
        local n = to_number(text)
        if not n then return nil, "'" .. text .. "' is not a number" end
        if n < low or n > high then
            local kept = math.max(low, math.min(high, n))
            return kept, string.format("%s is outside %g..%g; using %g", text, low, high, kept)
        end
        return n
    end
end

local function boolean_reader(text)
    local value = BOOLEANS[text:lower()]
    if value == nil then return nil, "'" .. text .. "' is not true or false" end
    return value
end

-- Hyprland understands "flat", "adaptive" and "custom STEP POINT..." (its
-- parser wants single spaces) and only logs anything else; empty is libinput's
-- own choice, which Hyprland spells [[EMPTY]] when it reads one back.
local function accel_reader(text)
    if text == "" or text == "[[EMPTY]]" then return "" end
    if text == "flat" or text == "adaptive" then return text end
    local words = {}
    for word in text:gmatch("%S+") do words[#words + 1] = word end
    if words[1] == "custom" and #words >= 3 then
        local numeric = true
        for i = 2, #words do numeric = numeric and to_number(words[i]) ~= nil end
        if numeric then return table.concat(words, " ") end
    end
    return nil, "'" .. text .. "' is not flat, adaptive or custom STEP POINT..."
end

local READERS = {
    sensitivity    = number_reader(-1, 1),
    accel_profile  = accel_reader,
    natural_scroll = boolean_reader,
    scroll_factor  = number_reader(0.1, 10),
}

-- "open" and the block name, "close", "option" and its key and value, or "other".
local function classify(raw)
    local line = trim((raw:gsub("#.*$", "")))
    if line == "}" then return "close" end
    local key, value = line:match("^([^=]*)=(.*)$")
    if key then return "option", trim(key), trim(value) end
    local name = line:match("^(.-)%s*{$")
    if name then return "open", name end
    return "other"
end

local function parse(path, f)
    local options, blocks, lineno = {}, {}, 0
    for raw in f:lines() do
        lineno = lineno + 1
        local ok, err = pcall(function()
            local kind, key, value = classify(raw)
            if kind == "open" then
                blocks[#blocks + 1] = key
            elseif kind == "close" then
                blocks[#blocks] = nil
            elseif kind == "option" and #blocks == 1 and blocks[1] == "input" and READERS[key] then
                local typed, note = READERS[key](value)
                if typed == nil then
                    report(path, lineno, key .. ": " .. note .. "; skipped")
                else
                    options[key] = typed
                    if note then report(path, lineno, key .. ": " .. note) end
                end
            end
        end)
        if not ok then report(path, lineno, tostring(err)) end
    end
    return options
end

function M.load(path)
    local f = io.open(path, "r")
    if not f then return end
    local ok, options = pcall(parse, path, f)
    f:close()
    if not ok then
        print("pointer_loader: " .. path .. ": " .. tostring(options))
        return
    end
    -- One call per option, so a value Hyprland refuses cannot hold back the rest.
    for _, key in ipairs(ORDER) do
        if options[key] ~= nil then
            local applied, err = pcall(hl.config, { input = { [key] = options[key] } })
            if not applied then print("pointer_loader: " .. key .. ": " .. tostring(err)) end
        end
    end
end

return M
