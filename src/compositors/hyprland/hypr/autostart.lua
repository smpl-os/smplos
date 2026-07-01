-- Autostart entries — run once at Hyprland startup.
-- Mirrors src/compositors/hyprland/hypr/autostart.conf.

hl.on("hyprland.start", function()
    -- Scrolling layout plugin (niri/PaperWM) -- load before windows tile.
    -- SMPLSCROLL DISABLED 2026-06-30 (paused for Hyprland 0.55+ upgrade). Re-enable:
    -- uncomment the line below + set looknfeel.lua layout = "scroll".
    -- hl.exec_cmd("hyprctl plugin load /usr/local/lib/smplos/smplscroll.so")

    -- Core services
    hl.exec_cmd("hypridle")
    hl.exec_cmd("dunst")

    -- Sync saved keyboard layouts to compositor (before EWW bar starts)
    hl.exec_cmd("kb-sync")

    -- Generate messenger toggle keybindings (auto-detects installed apps)
    hl.exec_cmd("generate-messenger-bindings")

    -- Restore last wallpaper (must run before bar to generate colors)
    hl.exec_cmd("bash -c 'theme-bg-init'")

    -- Status bar (EWW) - launch after a short delay to ensure theme is ready
    hl.exec_cmd("bash -c 'sleep 0.5 && bar-ctl start'")

    -- Window guard — snap floating windows that end up off-screen back into view
    hl.exec_cmd("window-guard")

    -- Restore workspace-group monitor assignments
    hl.exec_cmd("bash -c 'sleep 1 && workspace-group 1'")

    -- Auto-mount USB, CD, HDD (notify on mount/unmount)
    hl.exec_cmd("automount")

    -- Credential storage (VS Code, Brave, git, etc.)
    -- Pipe empty password to --unlock so the keyring auto-unlocks on autologin
    -- (PAM can't unlock it because greetd autologin never prompts for a password)
    hl.exec_cmd([[bash -c 'echo "" | gnome-keyring-daemon --start --unlock --components=secrets,pkcs11,ssh']])

    -- Polkit agent for authentication dialogs
    hl.exec_cmd("/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1")

    -- Clean stale browser locks (VM force-shutdown leaves these behind)
    hl.exec_cmd("bash -c 'pgrep -x brave >/dev/null || rm -f ~/.config/BraveSoftware/Brave-Browser/Singleton*'")

    -- Propagate full environment to systemd/dbus (portals, gnome-keyring, etc.)
    hl.exec_cmd("systemctl --user import-environment")
    hl.exec_cmd("dbus-update-activation-environment --systemd --all")

    -- Welcome notification with essential keybindings (first boot only)
    hl.exec_cmd("smplos-first-run")

    -- Remind user to reboot if a critical update is pending (self-clears after reboot)
    hl.exec_cmd("bash -c 'sleep 3 && smplos-reboot-notify'")

    -- Setup AppImage desktop entries (offline, first boot)
    hl.exec_cmd("smplos-appimage-setup")

    -- Install Flatpak apps from bundled list (needs internet, first boot)
    hl.exec_cmd("smplos-flatpak-setup")
end)
