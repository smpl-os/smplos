#!/usr/bin/env bash
set -euo pipefail

# Always start from a valid directory to avoid getcwd errors if caller cwd vanished.
cd /
#
# dev-apply.sh -- Apply all pushed files inside the running VM
#
# Usage:  sudo bash /mnt/dev-apply.sh          (everything except st)
#         sudo bash /mnt/dev-apply.sh st        (also install st-wl binary)
#

SHARE="/mnt"
USER_HOME="$HOME"
DEV_APPLY_VERSION="2026-02-21.1"

# If running as root, find the real user
if [[ "$EUID" -eq 0 ]]; then
    REAL_USER=$(logname 2>/dev/null || echo "${SUDO_USER:-}")
    if [[ -n "$REAL_USER" && "$REAL_USER" != "root" ]]; then
        USER_HOME="/home/$REAL_USER"
        USER_ID=$(id -u "$REAL_USER")
    fi
fi

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[apply]${NC} $*"; }
warn() { echo -e "${YELLOW}[apply]${NC} $*"; }

log "dev-apply version: $DEV_APPLY_VERSION"

# Run a command as the real user with Wayland/Hyprland env
# Uses runuser instead of su to avoid PAM login sessions that break sudo
run_as_user() {
    local cmd="$1"
    local safe_home="${USER_HOME:-/tmp}"
    [[ -d "$safe_home" ]] || safe_home="/tmp"

    if [[ "$EUID" -eq 0 && -n "${REAL_USER:-}" ]]; then
        local xdg_dir="/run/user/$USER_ID"
        local env_vars="XDG_RUNTIME_DIR=$xdg_dir"

        # Detect WAYLAND_DISPLAY
        for sock in "$xdg_dir"/wayland-*; do
            [[ -S "$sock" ]] || continue
            env_vars+=" WAYLAND_DISPLAY=$(basename "$sock")"
            break
        done

        # Detect HYPRLAND_INSTANCE_SIGNATURE
        local hypr_sig=""
        [[ -d /tmp/hypr ]] && hypr_sig=$(ls -1 /tmp/hypr/ 2>/dev/null | head -n1)
        [[ -z "$hypr_sig" && -d "$xdg_dir/hypr" ]] && hypr_sig=$(ls -1 "$xdg_dir/hypr/" 2>/dev/null | head -n1)
        if [[ -z "$hypr_sig" ]]; then
            local child_pid=$(pgrep -u "$REAL_USER" -f 'eww|hyprctl' 2>/dev/null | head -n1)
            [[ -n "$child_pid" ]] && hypr_sig=$(tr '\0' '\n' < /proc/"$child_pid"/environ 2>/dev/null | grep ^HYPRLAND_INSTANCE_SIGNATURE= | cut -d= -f2)
        fi
        [[ -n "$hypr_sig" ]] && env_vars+=" HYPRLAND_INSTANCE_SIGNATURE=$hypr_sig"

        cd /
        runuser -u "$REAL_USER" -- env $env_vars HOME="$safe_home" USER="$REAL_USER" LOGNAME="$REAL_USER" bash --noprofile --norc -c "cd '$safe_home' >/dev/null 2>&1 || cd /; $cmd"
    else
        cd /
        bash --noprofile --norc -c "cd '$safe_home' >/dev/null 2>&1 || cd /; $cmd"
    fi
}

# Check mount
if [[ ! -f "$SHARE/dev-apply.sh" ]]; then
    echo "Shared folder not mounted. Run:"
    echo "  sudo mount -t 9p -o trans=virtio hostshare /mnt"
    exit 1
fi

restart_eww=false
restart_hypr=false

own() { chown -R "$(stat -c '%U:%G' "$USER_HOME")" "$1" 2>/dev/null || true; }

# ── EWW configs ─────────────────────────────────────────────
if [[ -d "$SHARE/eww" && "$(ls -A "$SHARE/eww" 2>/dev/null)" ]]; then
    log "Applying EWW configs..."
    mkdir -p "$USER_HOME/.config/eww"
    # Do not remove the top-level directory itself: if the caller's cwd is
    # ~/.config/eww, deleting it causes noisy getcwd errors in subsequent commands.
    find "$USER_HOME/.config/eww" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
    cp -a "$SHARE/eww/." "$USER_HOME/.config/eww/"
    find "$USER_HOME/.config/eww/scripts" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
    own "$USER_HOME/.config/eww/"
    restart_eww=true
    log "  done"
fi

# ── Shared icons (SVG templates for EWW bar) ───────────────
if [[ -d "$SHARE/icons" && "$(ls -A "$SHARE/icons" 2>/dev/null)" ]]; then
    log "Applying icon templates..."
    ICONS_DEST="$USER_HOME/.local/share/smplos/icons"
    mkdir -p "$ICONS_DEST"
    cp -r "$SHARE/icons/"* "$ICONS_DEST/"
    own "$ICONS_DEST"
    log "  done (theme-set will bake colors into these)"
fi

# ── Hicolor app icons (system icon theme for Rust apps) ────
if [[ -d "$SHARE/icons/hicolor" ]]; then
    log "Installing hicolor app icons..."
    cp -r "$SHARE/icons/hicolor/"* /usr/share/icons/hicolor/
    gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true
    log "  done"
fi

# ── Bin scripts ─────────────────────────────────────────────
if [[ -d "$SHARE/bin" && "$(ls -A "$SHARE/bin" 2>/dev/null)" ]]; then
    log "Applying bin scripts..."
    for existing in /usr/local/bin/*; do
        [[ -f "$existing" ]] || continue
        name=$(basename "$existing")
        [[ -f "$SHARE/bin/$name" ]] || {
            head -5 "$existing" 2>/dev/null | grep -qi 'smplos\|smplOS' && rm -f "$existing" && log "  Removed stale: $name"
        }
    done
    cp -r "$SHARE/bin/"* /usr/local/bin/
    for f in "$SHARE/bin/"*; do
        chmod +x "/usr/local/bin/$(basename "$f")" 2>/dev/null || true
    done
    log "  $(ls "$SHARE/bin" | wc -l) scripts installed"
fi

# ── Shared configs ──────────────────────────────────────────
if [[ -d "$SHARE/configs" && "$(ls -A "$SHARE/configs" 2>/dev/null)" ]]; then
    log "Applying shared configs..."
    for f in "$SHARE/configs/"*; do
        [[ -f "$f" ]] && cp "$f" "$USER_HOME/.config/"
    done
    for d in "$SHARE/configs/"*/; do
        [[ -d "$d" ]] || continue
        name=$(basename "$d")
        mkdir -p "$USER_HOME/.config/$name"
        cp -r "$d"* "$USER_HOME/.config/$name/" 2>/dev/null || true
    done
    own "$USER_HOME/.config/"
    log "  done"
fi

# ── Systemd user units ──────────────────────────────────────
if [[ -d "$USER_HOME/.config/systemd/user" ]]; then
    log "Enabling systemd user units..."
    USER_WANTS="$USER_HOME/.config/systemd/user/default.target.wants"
    mkdir -p "$USER_WANTS"
    for unit in smplos-app-cache.service smplos-app-cache.path; do
        if [[ -f "$USER_HOME/.config/systemd/user/$unit" ]]; then
            ln -sf "../$unit" "$USER_WANTS/$unit"
            log "  enabled $unit"
        fi
    done
    own "$USER_HOME/.config/systemd"
    # Reload systemd user daemon so it picks up new units
    run_as_user "systemctl --user daemon-reload" 2>/dev/null || true
    run_as_user "systemctl --user restart smplos-app-cache.path" 2>/dev/null || true
fi

# ── Applications (.desktop files) ───────────────────────────
if [[ -d "$SHARE/applications" && "$(ls -A "$SHARE/applications" 2>/dev/null)" ]]; then
    log "Applying .desktop files..."
    mkdir -p "$USER_HOME/.local/share/applications"
    cp "$SHARE/applications/"*.desktop "$USER_HOME/.local/share/applications/" 2>/dev/null || true
    own "$USER_HOME/.local/share/applications/"
    update-desktop-database "$USER_HOME/.local/share/applications" 2>/dev/null || true
    log "  $(ls "$SHARE/applications/"*.desktop 2>/dev/null | wc -l) desktop entries installed"
fi

# ── Remove deprecated .desktop files ────────────────────────
deprecated_desktops=(
    create-webapp.desktop
    manage-webapps.desktop
    youtube.desktop
)
for f in "${deprecated_desktops[@]}"; do
    rm -f "$USER_HOME/.local/share/applications/$f" 2>/dev/null
done

# ── Remove deprecated scripts ───────────────────────────────
deprecated_scripts=(
    create-webapp
    create-webapp-open
    manage-webapps
    manage-webapps-open
)
for f in "${deprecated_scripts[@]}"; do
    rm -f "/usr/local/bin/$f" 2>/dev/null
done

# ── App cache (populate for launcher) ───────────────────────
if command -v rebuild-app-cache &>/dev/null; then
    log "Building app cache..."
    run_as_user "rebuild-app-cache" 2>/dev/null && log "  done" || warn "  failed"
fi

# ── notif-center ─────────────────────────────────────────────
if [[ -f "$SHARE/notif-center/notif-center" ]]; then
    log "Applying notif-center binary..."
    # Kill running instance first — Linux won't let cp overwrite an in-use binary
    run_as_user "pkill -x notif-center" 2>/dev/null || true
    sleep 0.3
    # If a directory exists (from previous bug), remove it
    if [[ -d "/usr/local/bin/notif-center" ]]; then
        rm -rf "/usr/local/bin/notif-center"
    fi
    cp "$SHARE/notif-center/notif-center" "/usr/local/bin/"
    chmod +x "/usr/local/bin/notif-center"
    own "/usr/local/bin/notif-center"
    log "  done"
fi

# ── kb-center ────────────────────────────────────────────────
if [[ -f "$SHARE/kb-center/kb-center" ]]; then
    log "Applying kb-center binary..."
    if [[ -d "/usr/local/bin/kb-center" ]]; then
        rm -rf "/usr/local/bin/kb-center"
    fi
    cp "$SHARE/kb-center/kb-center" "/usr/local/bin/"
    chmod +x "/usr/local/bin/kb-center"
    own "/usr/local/bin/kb-center"
    log "  done"
fi

# ── disp-center ──────────────────────────────────────────────
if [[ -f "$SHARE/disp-center/disp-center" ]]; then
    log "Applying disp-center binary..."
    if [[ -d "/usr/local/bin/disp-center" ]]; then
        rm -rf "/usr/local/bin/disp-center"
    fi
    cp "$SHARE/disp-center/disp-center" "/usr/local/bin/"
    chmod +x "/usr/local/bin/disp-center"
    own "/usr/local/bin/disp-center"
    log "  done"
fi

# ── webapp-center ────────────────────────────────────────────
if [[ -f "$SHARE/webapp-center/webapp-center" ]]; then
    log "Applying webapp-center binary..."
    run_as_user "pkill -x webapp-center" 2>/dev/null || true
    sleep 0.3
    if [[ -d "/usr/local/bin/webapp-center" ]]; then
        rm -rf "/usr/local/bin/webapp-center"
    fi
    cp "$SHARE/webapp-center/webapp-center" "/usr/local/bin/"
    chmod +x "/usr/local/bin/webapp-center"
    own "/usr/local/bin/webapp-center"
    log "  done"
fi

# ── app-center ───────────────────────────────────────────────
if [[ -f "$SHARE/app-center/app-center" ]]; then
    log "Applying app-center binary..."
    run_as_user "pkill -x app-center" 2>/dev/null || true
    sleep 0.3
    if [[ -d "/usr/local/bin/app-center" ]]; then
        rm -rf "/usr/local/bin/app-center"
    fi
    cp "$SHARE/app-center/app-center" "/usr/local/bin/"
    chmod +x "/usr/local/bin/app-center"
    own "/usr/local/bin/app-center"
    log "  done"
fi

# ── start-menu ───────────────────────────────────────────────
if [[ -f "$SHARE/start-menu/start-menu" ]]; then
    log "Applying start-menu binary..."
    run_as_user "pkill -x start-menu" 2>/dev/null || true
    sleep 0.3
    if [[ -d "/usr/local/bin/start-menu" ]]; then
        rm -rf "/usr/local/bin/start-menu"
    fi
    cp "$SHARE/start-menu/start-menu" "/usr/local/bin/"
    chmod +x "/usr/local/bin/start-menu"
    own "/usr/local/bin/start-menu"
    if [[ -x "/usr/local/bin/start-menu" ]]; then
        sm_ver=$(/usr/local/bin/start-menu --version 2>/dev/null || true)
        [[ -n "$sm_ver" ]] && log "  installed: $sm_ver"
    fi
    log "  done"
fi

# ── Hyprland configs ────────────────────────────────────────
if [[ -d "$SHARE/hypr" && "$(ls -A "$SHARE/hypr" 2>/dev/null)" ]]; then
    log "Applying Hyprland configs..."
    mkdir -p "$USER_HOME/.config/hypr"
    # Overwrite all hypr configs including input.conf
    cp -r "$SHARE/hypr/"* "$USER_HOME/.config/hypr/"
    # Ensure messenger-bindings.conf exists (generated at login, may not exist yet)
    touch "$USER_HOME/.config/hypr/messenger-bindings.conf"
    own "$USER_HOME/.config/hypr/"
    if [[ -f "$SHARE/hypr/bindings.conf" ]]; then
        mkdir -p "$USER_HOME/.config/smplos"
        cp "$SHARE/hypr/bindings.conf" "$USER_HOME/.config/smplos/bindings.conf"
        own "$USER_HOME/.config/smplos/"
    fi
    restart_hypr=true
    log "  done"
fi

# ── Themes ──────────────────────────────────────────────────
if [[ -d "$SHARE/themes" && "$(ls -A "$SHARE/themes" 2>/dev/null)" ]]; then
    THEMES_DEST="$USER_HOME/.local/share/smplos/themes"
    log "Applying themes..."
    mkdir -p "$THEMES_DEST"
    cp -r "$SHARE/themes/"* "$THEMES_DEST/"
    own "$THEMES_DEST"
    log "  done"
fi

# ── st-wl terminal ──────────────────────────────────────────
if [[ -f "$SHARE/st/st-wl" ]]; then
    log "Installing st-wl binary..."
    cp "$SHARE/st/st-wl" /usr/local/bin/st-wl
    chmod +x /usr/local/bin/st-wl
    if [[ -f "$SHARE/st/st-wl.desktop" ]]; then
        cp "$SHARE/st/st-wl.desktop" /usr/local/share/applications/st-wl.desktop 2>/dev/null || \
        cp "$SHARE/st/st-wl.desktop" /usr/share/applications/st-wl.desktop 2>/dev/null || true
        update-desktop-database /usr/local/share/applications 2>/dev/null || true
    fi
    log "  done"
fi

# ── Logseq theme plugins ────────────────────────────────────
if [[ -d "$SHARE/.logseq/plugins" ]]; then
    log "Applying Logseq theme plugins..."
    mkdir -p "$USER_HOME/.logseq/plugins" "$USER_HOME/.logseq/settings"
    cp -r "$SHARE/.logseq/plugins/"* "$USER_HOME/.logseq/plugins/"
    [[ -d "$SHARE/.logseq/settings" ]] && cp -r "$SHARE/.logseq/settings/"* "$USER_HOME/.logseq/settings/"
    own "$USER_HOME/.logseq"
    log "  $(ls "$SHARE/.logseq/plugins" | wc -l) plugins installed"
fi

# ── Restart xdg-desktop-portal (picks up portals.conf changes) ──
if [[ -f "$USER_HOME/.config/xdg-desktop-portal/portals.conf" ]]; then
    log "Restarting xdg-desktop-portal..."
    run_as_user "systemctl --user restart xdg-desktop-portal" 2>/dev/null || warn "  portal restart failed"
    log "  done"
fi

# ── Pacman HoldPkg safety (for testing installer behavior) ──
if [[ -f /etc/pacman.conf ]]; then
    if grep -q '^HoldPkg' /etc/pacman.conf; then
        if ! grep -Eq '^HoldPkg.*\bbrave-bin\b' /etc/pacman.conf; then
            log "Adding brave-bin to pacman HoldPkg..."
            sed -i '/^HoldPkg/s/$/ brave-bin/' /etc/pacman.conf
            log "  done"
        fi
    else
        log "Adding HoldPkg with brave-bin to pacman.conf..."
        awk '
            /^\[options\]$/ { print; print "HoldPkg     = pacman glibc brave-bin"; next }
            { print }
        ' /etc/pacman.conf > /etc/pacman.conf.tmp && mv /etc/pacman.conf.tmp /etc/pacman.conf
        log "  done"
    fi
fi

# ── Plymouth smooth handoff (reduce post-splash text flash) ──
if command -v plymouth-set-default-theme &>/dev/null; then
    log "Applying Plymouth handoff tuning..."

    # 1) Ensure silent boot args on GRUB systems
    if [[ -f /etc/default/grub ]]; then
        current_cmdline=$(grep '^GRUB_CMDLINE_LINUX_DEFAULT=' /etc/default/grub | sed -E 's/^GRUB_CMDLINE_LINUX_DEFAULT="(.*)"/\1/' || true)
        # Keep transition silent and avoid greetd/Plymouth text flash on tty handoff
        for arg in quiet splash plymouth.nolog loglevel=3 rd.udev.log_level=3 rd.systemd.show_status=false systemd.show_status=false vt.global_cursor_default=0 console=tty1 mce=dont_log_ce; do
            [[ " $current_cmdline " == *" $arg "* ]] || current_cmdline+=" $arg"
        done
        current_cmdline=$(echo "$current_cmdline" | xargs)
        sed -i "s|^GRUB_CMDLINE_LINUX_DEFAULT=.*|GRUB_CMDLINE_LINUX_DEFAULT=\"$current_cmdline\"|" /etc/default/grub
        if command -v grub-mkconfig &>/dev/null && [[ -d /boot/grub ]]; then
            grub-mkconfig -o /boot/grub/grub.cfg >/dev/null 2>&1 || true
        fi
    fi

    # 2) Ensure silent boot args on systemd-boot entries
    if [[ -d /boot/loader/entries ]]; then
        for entry in /boot/loader/entries/*.conf; do
            [[ -f "$entry" ]] || continue
            line=$(grep '^options ' "$entry" 2>/dev/null || true)
            [[ -n "$line" ]] || continue
            opts=${line#options }
            # Keep transition silent and avoid greetd/Plymouth text flash on tty handoff
            for arg in quiet splash plymouth.nolog loglevel=3 rd.udev.log_level=3 rd.systemd.show_status=false systemd.show_status=false vt.global_cursor_default=0 console=tty1 mce=dont_log_ce; do
                [[ " $opts " == *" $arg "* ]] || opts+=" $arg"
            done
            opts=$(echo "$opts" | xargs)
            sed -i "s|^options .*|options  $opts|" "$entry"
        done
    fi

    # Plymouth must fully quit before greetd starts Hyprland.
    # After=greetd.service races: greetd fires initial_session immediately
    # (Type=simple) so Hyprland tries to open DRM while Plymouth still holds
    # it -> Hyprland crashes -> black screen.
    # --retain-splash keeps the last Plymouth frame on screen until Hyprland
    # renders, so no visible flash despite Plymouth quitting first.
    mkdir -p /etc/systemd/system/plymouth-quit.service.d/
    cat > /etc/systemd/system/plymouth-quit.service.d/wait-for-graphical.conf <<'EOF'
[Unit]
After=multi-user.target

[Service]
ExecStart=
ExecStart=/usr/bin/plymouth quit --retain-splash
EOF
    systemctl mask plymouth-quit-wait.service >/dev/null 2>&1 || true
    systemctl daemon-reload >/dev/null 2>&1 || true

    log "  done (reboot required to fully test)"
fi

# ── Ensure essential services ───────────────────────────────
systemctl is-active --quiet NetworkManager 2>/dev/null || {
    log "Starting NetworkManager..."
    systemctl start NetworkManager 2>/dev/null && log "  NetworkManager started" || warn "  Failed to start NetworkManager"
}

# ── Restart services ────────────────────────────────────────

# Re-apply current theme (copies theme-colors.scss, bakes SVG icons, etc.)
current_theme=$(cat "$USER_HOME/.config/smplos/current/theme.name" 2>/dev/null || true)
if [[ -n "${current_theme:-}" ]] && ($restart_eww || $restart_hypr); then
    log "Killing EWW before theme re-apply..."
    run_as_user "eww --config ~/.config/eww kill 2>/dev/null; killall -9 eww 2>/dev/null" || true
    sleep 0.5
    log "Re-applying theme '$current_theme'..."
    # Re-bake theme assets (SVG icons, eww colors, app themes)
    run_as_user "theme-set '$current_theme'" 2>/dev/null || warn "  theme-set failed"
    # theme-set skips bar restart since we killed eww above — start it once here.
    # Use timeout to avoid hanging dev-apply if eww IPC stalls.
    sleep 0.3
    log "Starting EWW bar..."
    run_as_user "timeout 8s bar-ctl start >/tmp/eww-startup.log 2>&1 || true"

    # Browser policies need root -- theme-set skips them when non-root,
    # so we handle them here directly (we're already root)
    THEME_DIR="$USER_HOME/.local/share/smplos/themes/$current_theme"
    BROWSER_BG=$(grep '^background' "$THEME_DIR/colors.toml" 2>/dev/null | head -1 | sed 's/.*"\(#[^"]*\)".*/\1/')
    if [[ -n "${BROWSER_BG:-}" ]]; then
        BROWSER_POLICY="{\"BrowserThemeColor\": \"$BROWSER_BG\", \"BackgroundModeEnabled\": false}"
        for browser in chromium brave; do
            command -v "$browser" &>/dev/null || continue
            mkdir -p "/etc/$browser/policies/managed" 2>/dev/null
            echo "$BROWSER_POLICY" > "/etc/$browser/policies/managed/color.json" 2>/dev/null
        done
    fi
fi

if $restart_hypr; then
    log "Generating messenger bindings..."
    run_as_user "generate-messenger-bindings" 2>/dev/null || warn "  messenger bindings generation failed"
    log "Reloading Hyprland..."
    run_as_user "pkill rofi" 2>/dev/null || true
    run_as_user "hyprctl reload" 2>/dev/null || warn "  hyprctl reload failed"
    log "  Hyprland reloaded"
fi

log ""
log "All done!"
