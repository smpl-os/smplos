-- Must load after apps.*: safety exemptions win over browser/messenger rules.
-- fullscreen is a boolean matcher (not fullscreen_state's numeric enum).
local neutral = "1.0 override 1.0 override 1.0 override"
hl.window_rule({ match = { tag = "self-managed-alpha" }, opacity = neutral })
hl.window_rule({ match = { tag = "compositor-opaque" }, opacity = neutral })
hl.window_rule({ match = { tag = "pip" }, opacity = neutral })
hl.window_rule({ match = { class = "^steam_app_[0-9]+$" }, opacity = neutral })
hl.window_rule({ match = { content = "^(photo|video|game)$" }, opacity = neutral })
hl.window_rule({ match = { fullscreen = 1 }, opacity = neutral })
