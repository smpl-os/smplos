-- Autostart entries — run once at Hyprland startup.
-- Mirrors src/compositors/hyprland/hypr/autostart.conf.

hl.on("hyprland.start", function()
    -- Core services
    -- NOTE: hypridle is now managed by the packaged systemd user unit
    -- (hypridle.service, enabled via /etc/skel + migration). Launching it
    -- here as well spawns a second BARE hypridle from every session start;
    -- both fight over logind Lock/Sleep signals, and the bare one loads
    -- whatever config was on disk at boot time so Settings-driven changes
    -- silently no-op until the next reboot. Never uncomment.
    -- hl.exec_cmd("hypridle")
    hl.exec_cmd("dunst")

    -- Sync saved keyboard layouts to compositor (before EWW bar starts)
    hl.exec_cmd("kb-sync")

    -- Generate messenger toggle keybindings (auto-detects installed apps)
    hl.exec_cmd("generate-messenger-bindings")

    -- Restore last wallpaper (must run before bar to generate colors)
    hl.exec_cmd("bash -c 'theme-bg-init'")

    -- Status bar (EWW) - launch after a short delay to ensure theme is ready
    hl.exec_cmd("bash -c 'sleep 0.5 && bar-ctl start'")
    -- Keep a hidden Start Menu running so Super shows it instantly (no-op for
    -- start-menu builds without resident support).
    hl.exec_cmd("bash -c 'sleep 2 && toggle-start-menu --preload'")

    -- Window guard — snap floating windows that end up off-screen back into view
    hl.exec_cmd("window-guard")

    -- Restore workspace-group monitor assignments
    hl.exec_cmd("bash -c 'sleep 1 && workspace-session-init'")

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
    -- and start the graphical session's user services (hypridle power timers,
    -- dictation, XR watcher); a plain start-hyprland session never activates
    -- graphical-session.target on its own. Reports services that fail.
    hl.exec_cmd("smplos-session-services")
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
