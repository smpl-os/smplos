-- Input configuration.
-- Mirrors src/compositors/hyprland/hypr/input.conf.
-- See https://wiki.hyprland.org/Configuring/Variables/#input

hl.config({
    input = {
        kb_layout  = "us",
        kb_variant = "",
        kb_model   = "",
        kb_options = "compose:caps",
        kb_rules   = "evdev",

        -- Key repeat: 50 Hz (20ms interval), 300ms delay before repeat starts.
        repeat_rate  = 50,
        repeat_delay = 300,

        follow_mouse = 0,  -- 0 = click to focus only (no focus-follows-mouse)
        sensitivity  = 0,  -- -1.0 - 1.0, 0 means no modification

        touchpad = {
            natural_scroll = false,
        },
    },
})
