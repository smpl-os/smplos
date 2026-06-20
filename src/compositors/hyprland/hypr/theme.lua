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

return M
