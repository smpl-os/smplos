-- Must load after apps.*: safety exemptions win over browser/messenger rules.
-- fullscreen is a boolean matcher (not fullscreen_state's numeric enum).
-- Keep class=".*": Hyprland 0.56 replays CLASS rules on title changes.
-- Without that dependency, a tag-only exemption can lose to the default alpha.
local neutral = "1.0 override 1.0 override 1.0 override"
hl.window_rule({ match = { class = ".*", tag = "self-managed-alpha" }, opacity = neutral })
hl.window_rule({ match = { class = ".*", tag = "compositor-opaque" }, opacity = neutral })
hl.window_rule({ match = { class = ".*", tag = "pip" }, opacity = neutral })
hl.window_rule({ match = { class = "^steam_app_[0-9]+$" }, opacity = neutral })
hl.window_rule({ match = { class = ".*", content = "^(photo|video|game)$" }, opacity = neutral })
hl.window_rule({ match = { class = ".*", fullscreen = 1 }, opacity = neutral })
