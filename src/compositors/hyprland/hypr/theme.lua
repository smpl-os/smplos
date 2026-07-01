-- smplOS Hyprland Theme bridge
--
-- theme-set writes hyprlang $var = value lines into theme.conf on every
-- theme switch. We parse those lines here and return a Lua table so the
-- Lua config modules can interpolate the values just like hyprlang would.
--
-- Note: hyprctl reload re-runs this Lua file, so theme switches still
-- propagate after running `theme-set <name>`.

local M = {}

local function parse(path)
    local f = io.open(path, "r")
    if not f then return end
    for line in f:lines() do
        local k, v = line:match("^%s*%$([%w_]+)%s*=%s*(.-)%s*$")
        if k and v and v ~= "" then M[k] = v end
    end
    f:close()
end

parse(os.getenv("HOME") .. "/.config/hypr/theme.conf")

-- Defaults (mirror src/compositors/hyprland/hypr/theme.conf) so the config
-- never starts with nil values if theme.conf is missing on first run.
M.activeBorderColor        = M.activeBorderColor        or "rgb(89b4fa)"
M.inactiveBorderColor      = M.inactiveBorderColor      or "rgba(585b70aa)"
M.themeRounding            = M.themeRounding            or "3"
M.themeGapsIn              = M.themeGapsIn              or "2"
M.themeGapsOut             = M.themeGapsOut             or "4"
M.themeBorderSize          = M.themeBorderSize          or "2"
M.themeBlurSize            = M.themeBlurSize            or "14"
M.themeBlurPasses          = M.themeBlurPasses          or "3"
M.themeOpacityActive       = M.themeOpacityActive       or "1.0"
M.themeOpacityInactive     = M.themeOpacityInactive     or "0.95"
M.themeTermOpacityActive   = M.themeTermOpacityActive   or "1.0"
M.themeTermOpacityInactive = M.themeTermOpacityInactive or "0.95"
M.themePopupOpacity        = M.themePopupOpacity        or "0.60"
M.themeMessengerOpacity    = M.themeMessengerOpacity    or "0.85"
M.themeBrowserOpacity      = M.themeBrowserOpacity      or "1.0"

-- Convert a hyprlang color/gradient string into the value the Hyprland Lua
-- config API (hl.config) expects.
--
-- The hyprlang text parser accepts a multi-stop gradient as one string, e.g.
--   "rgb(89b4fa) rgb(a6e3a1) 45deg"
-- but the Lua gradient parser runs parseColor() on the whole string and rejects
-- it ("invalid color"). Under Lua a gradient must be a table:
--   { colors = { "rgb(89b4fa)", "rgb(a6e3a1)" }, angle = 45 }
-- A single color is still passed through as a plain string.
function M.color(value)
    if type(value) ~= "string" then return value end

    local tokens = {}
    for tok in value:gmatch("%S+") do tokens[#tokens + 1] = tok end
    if #tokens <= 1 then return value end  -- single color: pass through

    -- A trailing "<n>deg" token is the gradient angle, not a color.
    local angle
    local deg = tokens[#tokens]:match("^(%-?%d+)deg$")
    if deg then
        angle = tonumber(deg)
        tokens[#tokens] = nil
    end

    if #tokens == 1 and angle == nil then return tokens[1] end

    return { colors = tokens, angle = angle or 0 }
end

return M
