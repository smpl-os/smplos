-- Always-on click-outside-to-dismiss watcher for smplOS popup apps
-- (start-menu, smpl-calendar). Registers a single non-consuming bind on
-- the left mouse button so every click triggers popup-click-check, which
-- in turn dismisses any open popup whose window the click missed.
--
-- Why this lives separately from bindings.conf:
--   • It's a system mechanism, not a user-visible keybinding.
--   • Keeping it out of bindings.conf means it doesn't show up in the
--     keybind-help overlay or any future DWM C-struct dump.
--
-- Why this replaces toggle-start-menu / toggle-calendar's old runtime
-- bind/unbind dance:
--   Hyprland 0.55's non-legacy parser rejects `hyprctl keyword bindn` and
--   `hyprctl keyword unbind` at runtime ("keyword can't work with
--   non-legacy parsers. Use eval."), so the runtime bind was silently
--   never registered → click-outside never dismissed → only Esc closed.
--   See: src/shared/bin/popup-click-check, toggle-start-menu, toggle-calendar.
--
-- Key format note:
--   hl.bind() expects just the key (no leading hyprlang "MODS," prefix);
--   for a non-modded bind we pass "mouse:272" — passing ", mouse:272"
--   trips "Unknown keysym" in the Lua parser.

hl.bind("mouse:272", hl.dsp.exec_cmd("popup-click-check"), {
    non_consuming = true,
    description   = "_popup_click_check",  -- _-prefix marks as internal
})
