-- Browser-specific window rules.
-- Mirrors src/compositors/hyprland/hypr/apps/browser.conf.

local theme = require("theme")

-- Browser type tags
hl.window_rule({
    match = { class = "((google-)?[cC]hrom(e|ium)|[bB]rave-browser|[mM]icrosoft-edge|Vivaldi-stable|helium)" },
    tag = "+chromium-based-browser",
})
hl.window_rule({
    match = { class = "([fF]irefox|zen|librewolf)" },
    tag = "+firefox-based-browser",
})

-- Stock browser alpha follows the theme; authors can set browser_opacity.
-- Override so focus/unfocus uses the same value (no dim on blur).
local browser_opacity = theme.themeBrowserOpacity .. " override "
                     .. theme.themeBrowserOpacity .. " override"
hl.window_rule({ match = { class = ".*", tag = "chromium-based-browser" }, opacity = browser_opacity })
hl.window_rule({ match = { class = ".*", tag = "firefox-based-browser"  }, opacity = browser_opacity })

-- Force chromium-based browsers into a tile to deal with --app bug
hl.window_rule({ match = { tag = "chromium-based-browser" }, tile = true })
