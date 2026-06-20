-- smplOS Hyprland configuration entry point (Lua).
--
-- This is the modern equivalent of hyprland.conf. Both files can coexist;
-- Hyprland 0.55+ prefers hyprland.lua when present, so we keep hyprland.conf
-- around as a one-rename rollback path.
--
-- Module load order intentionally matches the source order of hyprland.conf:
--   monitors → theme variables → envs → input → looknfeel → windows →
--   bindings (shared + messenger) → apps → autostart

-- Allow `require("…")` to find modules in this directory and apps/.
package.path = (os.getenv("HOME") or "") .. "/.config/hypr/?.lua;"
            .. (os.getenv("HOME") or "") .. "/.config/hypr/?/init.lua;"
            .. package.path

-- ── Monitors ───────────────────────────────────────────────────────────────
-- Fallback so first boot (no monitors.conf yet) still gets a usable layout.
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = "auto" })
-- User-saved overrides (written by Settings → Display)
require("monitors_loader").load((os.getenv("HOME") or "") .. "/.config/hypr/monitors.conf")

-- ── Configuration modules ──────────────────────────────────────────────────
require("envs")
require("input")
require("looknfeel")
require("windows")

-- ── Keybindings ────────────────────────────────────────────────────────────
-- bindings.conf is the cross-compositor source of truth; the loader translates
-- hyprlang bind directives into hl.bind() calls. messenger-bindings.conf is
-- regenerated at startup by generate-messenger-bindings (autostart), so on the
-- very first reload after boot it may be empty — that's fine, the next reload
-- will pick it up.
local bindings = require("bindings_loader")
local home     = os.getenv("HOME") or ""

local primary_bindings = home .. "/.config/smplos/bindings.conf"
local fallback_bindings = home .. "/.config/hypr/bindings.conf"
local f = io.open(primary_bindings, "r")
if f then f:close(); bindings.load(primary_bindings)
else            bindings.load(fallback_bindings) end

local mb = home .. "/.config/hypr/messenger-bindings.conf"
local fm = io.open(mb, "r")
if fm then fm:close(); bindings.load(mb) end

-- ── App-specific rules + autostart (last, so apps win opacity overrides) ──
require("apps")
require("autostart")
