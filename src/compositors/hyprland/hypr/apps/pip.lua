-- Picture-in-picture overlays.
-- Mirrors src/compositors/hyprland/hypr/apps/pip.conf.

hl.window_rule({
    match = { title = "(Picture.?in.?[Pp]icture)" },
    tag = "+pip",
})

hl.window_rule({
    match = { tag = "pip" },
    float = true, pin = true,
    size = "600 338",
    keep_aspect_ratio = true,
    border_size = 0,
    move = "(100%-window_w-40) (100%*0.04)",
})
