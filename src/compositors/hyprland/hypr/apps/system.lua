-- Generic floating-window / pop / noidle tags.
-- Mirrors src/compositors/hyprland/hypr/apps/system.conf.

-- All windows tagged +floating-window get a uniform centered float layout
hl.window_rule({
    match = { tag = "floating-window" },
    float = true, center = true, size = "875 600",
})

-- Apps that should always float
hl.window_rule({
    match = { class = "(org.gnome.NautilusPreviewer|org.gnome.Evince|com.gabm.satty|About|TUI.float|imv|mpv|org.Nemo.nemo-float)" },
    tag = "+floating-window",
})

-- File picker dialogs from Sublime/OnlyOffice/Nautilus
hl.window_rule({
    match = {
        class = "(xdg-desktop-portal-gtk|sublime_text|DesktopEditors|org.gnome.Nautilus)",
        title = "^(Open.*Files?|Open [F|f]older.*|Save.*Files?|Save.*As|Save|All Files|.*wants to [open|save].*|[C|c]hoose.*)",
    },
    tag = "+floating-window",
})

hl.window_rule({ match = { class = "org.gnome.Calculator" }, float = true })

-- Popped window rounding
hl.window_rule({ match = { tag = "pop" }, rounding = 8 })

-- Prevent idle while open
hl.window_rule({ match = { tag = "noidle" }, idle_inhibit = "always" })
