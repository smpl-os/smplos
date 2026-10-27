#!/usr/bin/env bash
set -euo pipefail
#
# dev-local.sh -- Build & apply source changes on the installed system
#
# Usage:  sudo ./dev-local.sh [component...]
#
# Components:  eww bin hypr themes configs apps icons plugins rust st all
#   (default: all except st and rust -- use 'st' or 'rust' explicitly)
#
# 'plugins' compiles the Hyprland plugins in src/compositors/hyprland/plugins
# against the installed Hyprland (as the real user; only the install is root)
# and reloads them in the running session when a build changed.
#
# Examples:
#   sudo ./dev-local.sh              # configs + scripts + eww + themes
#   sudo ./dev-local.sh eww          # just EWW
#   sudo ./dev-local.sh plugins      # rebuild + reload the HUD plugin
#   sudo ./dev-local.sh rust         # rebuild all Rust apps
#   sudo ./dev-local.sh eww rust     # EWW configs + rebuild Rust apps
#   sudo ./dev-local.sh all          # everything including st + Rust
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(dirname "$SCRIPT_DIR")/src"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${GREEN}[local]${NC} $*"; }
warn() { echo -e "${YELLOW}[local]${NC} $*"; }
err()  { echo -e "${RED}[local]${NC} $*" >&2; }

# ── Require root ────────────────────────────────────────────
if [[ "$EUID" -ne 0 ]]; then
    err "Run with sudo:  sudo $0 $*"
    exit 1
fi

# ── Find the real user ──────────────────────────────────────
REAL_USER=$(logname 2>/dev/null || echo "${SUDO_USER:-}")
if [[ -z "$REAL_USER" || "$REAL_USER" == "root" ]]; then
    err "Cannot determine real user. Run with: sudo ./dev-local.sh"
    exit 1
fi
USER_HOME="/home/$REAL_USER"
USER_ID=$(id -u "$REAL_USER")

own() { chown -R "$REAL_USER:$REAL_USER" "$1" 2>/dev/null || true; }

# Run a command as the real user with Wayland/Hyprland env
run_as_user() {
    local cmd="$1"
    local xdg_dir="/run/user/$USER_ID"
    local env_vars="XDG_RUNTIME_DIR=$xdg_dir"

    for sock in "$xdg_dir"/wayland-*; do
        [[ -S "$sock" ]] || continue
        env_vars+=" WAYLAND_DISPLAY=$(basename "$sock")"
        break
    done

    local hypr_sig=""
    [[ -d /tmp/hypr ]] && hypr_sig=$(ls -1 /tmp/hypr/ 2>/dev/null | head -n1)
    [[ -z "$hypr_sig" && -d "$xdg_dir/hypr" ]] && hypr_sig=$(ls -1 "$xdg_dir/hypr/" 2>/dev/null | head -n1)
    if [[ -z "$hypr_sig" ]]; then
        local child_pid
        child_pid=$(pgrep -u "$REAL_USER" -f 'eww|hyprctl' 2>/dev/null | head -n1) || true
        [[ -n "$child_pid" ]] && hypr_sig=$(tr '\0' '\n' < /proc/"$child_pid"/environ 2>/dev/null | grep ^HYPRLAND_INSTANCE_SIGNATURE= | cut -d= -f2)
    fi
    [[ -n "$hypr_sig" ]] && env_vars+=" HYPRLAND_INSTANCE_SIGNATURE=$hypr_sig"

    cd /
    runuser -u "$REAL_USER" -- env $env_vars HOME="$USER_HOME" USER="$REAL_USER" LOGNAME="$REAL_USER" \
        bash --noprofile --norc -c "cd '$USER_HOME' >/dev/null 2>&1 || cd /; $cmd"
}

# ── Parse components ────────────────────────────────────────
components=("$@")
if [[ ${#components[@]} -eq 0 ]]; then
    # Default: everything except st and rust (those are slow)
    components=(eww bin hypr themes configs apps icons plugins)
fi

do_component() {
    local c
    for c in "${components[@]}"; do
        [[ "$c" == "$1" || "$c" == "all" ]] && return 0
    done
    return 1
}

restart_eww=false
restart_hypr=false
plugin_action=""

log "${BOLD}Applying from:${NC} $SRC_DIR"
log "${BOLD}Target user:${NC}  $REAL_USER ($USER_HOME)"
echo ""

# ── EWW ─────────────────────────────────────────────────────
if do_component eww; then
    log "Applying EWW configs..."
    mkdir -p "$USER_HOME/.config/eww"
    for file in "$SRC_DIR/shared/eww/"*; do
        name=$(basename "$file")
        case "$name" in
            theme-colors.scss|theme-colors.yuck)
                [[ -f "$USER_HOME/.config/eww/$name" ]] && continue ;;
        esac
        cp -a "$file" "$USER_HOME/.config/eww/"
    done
    find "$USER_HOME/.config/eww/scripts" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
    own "$USER_HOME/.config/eww/"
    restart_eww=true
    log "  $(find "$SRC_DIR/shared/eww" -type f | wc -l) files"
fi

# ── Icons ───────────────────────────────────────────────────
if do_component icons; then
    if [[ -d "$SRC_DIR/shared/icons" ]]; then
        log "Applying icon templates..."
        ICONS_DEST="$USER_HOME/.local/share/smplos/icons"
        mkdir -p "$ICONS_DEST"
        cp -r "$SRC_DIR/shared/icons/"* "$ICONS_DEST/"
        own "$ICONS_DEST"
        # Hicolor app icons
        if [[ -d "$SRC_DIR/shared/icons/hicolor" ]]; then
            cp -r "$SRC_DIR/shared/icons/hicolor/"* /usr/share/icons/hicolor/
            gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true
        fi
        log "  done"
    fi
fi

# ── Bin scripts ─────────────────────────────────────────────
if do_component bin; then
    log "Applying bin scripts..."
    # Remove stale smplos scripts not in source
    for existing in /usr/local/bin/*; do
        [[ -f "$existing" ]] || continue
        name=$(basename "$existing")
        [[ -f "$SRC_DIR/shared/bin/$name" ]] || {
            head -5 "$existing" 2>/dev/null | grep -qi 'smplos\|smplOS' && rm -f "$existing" && log "  Removed stale: $name"
        }
    done
    cp -r "$SRC_DIR/shared/bin/"* /usr/local/bin/
    for f in "$SRC_DIR/shared/bin/"*; do
        chmod +x "/usr/local/bin/$(basename "$f")" 2>/dev/null || true
    done
    log "  $(ls "$SRC_DIR/shared/bin" | wc -l) scripts installed"
fi

# ── Shared shell libraries ──────────────────────────────────
if do_component bin; then
    if [[ -d "$SRC_DIR/shared/lib" ]]; then
        log "Applying shell libraries..."
        mkdir -p /usr/local/lib/smplos
        for lib in "$SRC_DIR/shared/lib/"*.sh "$SRC_DIR/shared/lib/"*.py; do
            [[ -f "$lib" ]] || continue
            install -m644 "$lib" /usr/local/lib/smplos/ || exit 1
        done
        log "  $(ls "$SRC_DIR/shared/lib" | wc -l) libraries installed"
    fi
fi

# ── Shared configs ──────────────────────────────────────────
if do_component configs; then
    log "Applying shared configs..."
    for f in "$SRC_DIR/shared/configs/"*; do
        [[ -f "$f" ]] && cp "$f" "$USER_HOME/.config/"
    done
    for d in "$SRC_DIR/shared/configs/"*/; do
        [[ -d "$d" ]] || continue
        name=$(basename "$d")
        mkdir -p "$USER_HOME/.config/$name"
        cp -r "$d"* "$USER_HOME/.config/$name/" 2>/dev/null || true
    done
    own "$USER_HOME/.config/"
    log "  done"
fi

# ── Applications (.desktop files) ───────────────────────────
if do_component apps; then
    if [[ -d "$SRC_DIR/shared/applications" ]]; then
        log "Applying .desktop files..."
        mkdir -p "$USER_HOME/.local/share/applications"
        cp "$SRC_DIR/shared/applications/"*.desktop "$USER_HOME/.local/share/applications/" 2>/dev/null || true
        own "$USER_HOME/.local/share/applications/"
        update-desktop-database "$USER_HOME/.local/share/applications" 2>/dev/null || true
        log "  done"
    fi
fi

# ── Hyprland configs ────────────────────────────────────────
if do_component hypr; then
    log "Applying Hyprland configs..."
    mkdir -p "$USER_HOME/.config/hypr"
    cp -r "$SRC_DIR/compositors/hyprland/hypr/"* "$USER_HOME/.config/hypr/"
    # Copy shared bindings.conf into hypr dir
    [[ -f "$SRC_DIR/shared/configs/smplos/bindings.conf" ]] && \
        cp "$SRC_DIR/shared/configs/smplos/bindings.conf" "$USER_HOME/.config/hypr/bindings.conf"
    # Also copy to smplos config dir
    mkdir -p "$USER_HOME/.config/smplos"
    [[ -f "$SRC_DIR/shared/configs/smplos/bindings.conf" ]] && \
        cp "$SRC_DIR/shared/configs/smplos/bindings.conf" "$USER_HOME/.config/smplos/bindings.conf"
    touch "$USER_HOME/.config/hypr/messenger-bindings.conf"
    own "$USER_HOME/.config/hypr/"
    own "$USER_HOME/.config/smplos/"
    restart_hypr=true
    log "  done"
fi

# ── Themes ──────────────────────────────────────────────────
if do_component themes; then
    log "Applying themes..."
    THEMES_DEST="$USER_HOME/.local/share/smplos/themes"
    mkdir -p "$THEMES_DEST"
    cp -r "$SRC_DIR/shared/themes/"* "$THEMES_DEST/"
    own "$THEMES_DEST"
    log "  $(ls -1d "$SRC_DIR/shared/themes/"*/ 2>/dev/null | wc -l) themes"
fi

# ── Compositor plugins ──────────────────────────────────────
# Compiled against the installed Hyprland by the same tool Update OS uses. It
# builds as the real user and installs as root; the session is reached below.
if do_component plugins; then
    PLUGIN_TOOL="$SRC_DIR/shared/bin/smplos-plugins"
    PLUGIN_SRC="$SRC_DIR/compositors/hyprland/plugins"
    PLUGIN_DIR="${SMPLOS_PLUGIN_DIR:-/usr/local/lib/smplos/plugins}"
    if [[ ! -r "${SMPLOS_HYPRLAND_VERSION_H:-/usr/include/hyprland/src/version.h}" ]]; then
        warn "Skipping compositor plugins: the Hyprland headers are not installed"
    elif [[ -d "$PLUGIN_SRC" ]]; then
        log "Building compositor plugins..."
        plugin_state() { { stat -c '%n %Y %i' "$PLUGIN_DIR"/* 2>/dev/null || true; } | sort | sha256sum; }
        plugins_before=$(plugin_state)
        SMPLOS_INVOKER_USER="$REAL_USER" bash "$PLUGIN_TOOL" sync --src "$PLUGIN_SRC" || {
            err "Plugin build failed; deployment is incomplete."
            exit 1
        }
        # A rebuilt binary must replace the one the compositor has mapped.
        if [[ "$(plugin_state)" == "$plugins_before" ]]; then
            plugin_action=load
        else
            plugin_action=reload
        fi
    fi
fi

# ── Rust apps (use container-built binaries -- only with 'rust' or 'all') ──
if do_component rust; then
    BIN_DIR="$(dirname "$SCRIPT_DIR")/.cache/app-binaries"
    RUST_APPS=(notif-center settings webapp-center app-center start-menu)

    # Auto-build if any binary is missing OR source is newer than binary
    stale_apps=()
    for app in "${RUST_APPS[@]}"; do
        if [[ ! -f "$BIN_DIR/$app" ]]; then
            log "$app: binary missing"
            stale_apps+=("$app"); continue
        fi
        # All Rust apps live under shared/apps/
        app_src="$SRC_DIR/shared/apps/$app"
        if [[ -d "$app_src" ]]; then
            newest_src=$(find "$app_src" -path '*/target' -prune -o \( -name '*.rs' -o -name '*.slint' -o -name 'Cargo.toml' \) -print | xargs stat -c '%Y' 2>/dev/null | sort -rn | head -1)
            bin_time=$(stat -c '%Y' "$BIN_DIR/$app" 2>/dev/null || echo 0)
            if [[ -n "$newest_src" && "$newest_src" -gt "$bin_time" ]]; then
                log "$app: source newer than binary"
                stale_apps+=("$app")
            fi
        fi
    done
    if [[ ${#stale_apps[@]} -gt 0 ]]; then
        log "Rebuilding: ${stale_apps[*]}"
        "$SRC_DIR/build-apps.sh" "${stale_apps[@]}"
    fi

    for app in "${RUST_APPS[@]}"; do
        if [[ -f "$BIN_DIR/$app" ]]; then
            run_as_user "pkill -x '$app'" 2>/dev/null || true
            sleep 0.3
            [[ -d "/usr/local/bin/$app" ]] && rm -rf "/usr/local/bin/$app"
            cp "$BIN_DIR/$app" "/usr/local/bin/$app"
            chmod +x "/usr/local/bin/$app"
            log "  $app installed"
        else
            warn "  $app: binary not found (run: src/build-apps.sh)"
        fi
    done
fi

# ── st-wl terminal (use container-built binary -- only with 'st' or 'all') ──
if do_component st; then
    BIN_DIR="$(dirname "$SCRIPT_DIR")/.cache/app-binaries"
    if [[ -f "$BIN_DIR/st-wl" ]]; then
        log "Installing st-wl..."
        cp "$BIN_DIR/st-wl" /usr/local/bin/st-wl
        chmod +x /usr/local/bin/st-wl
        ST_DIR="$SRC_DIR/compositors/hyprland/st"
        [[ -f "$ST_DIR/st-wl.desktop" ]] && {
            cp "$ST_DIR/st-wl.desktop" /usr/local/share/applications/st-wl.desktop 2>/dev/null || \
            cp "$ST_DIR/st-wl.desktop" /usr/share/applications/st-wl.desktop 2>/dev/null || true
            update-desktop-database /usr/local/share/applications 2>/dev/null || true
        }
        log "  st-wl installed"
    else
        warn "  st-wl: binary not found (run: src/build-apps.sh all)"
    fi
fi

# ── App cache ───────────────────────────────────────────────
if do_component apps || do_component bin; then
    if command -v rebuild-app-cache &>/dev/null; then
        log "Rebuilding app cache..."
        run_as_user "rebuild-app-cache" 2>/dev/null && log "  done" || warn "  failed"
    fi
fi

# ── Restart services ────────────────────────────────────────
current_theme=$(cat "$USER_HOME/.config/smplos/current/theme.name" 2>/dev/null || true)

if [[ -n "${current_theme:-}" ]] && ($restart_eww || $restart_hypr || do_component themes); then
    log "Re-applying theme '$current_theme'..."
    run_as_user "theme-set '$current_theme'" || {
        err "Theme re-apply failed; deployment is incomplete. EWW was not restarted."
        exit 1
    }

    # Browser policies (need root)
    THEME_DIR="$USER_HOME/.config/smplos/current/theme"
    BROWSER_BG=$(grep '^background' "$THEME_DIR/colors.toml" 2>/dev/null | head -1 | sed 's/.*"\(#[^"]*\)".*/\1/')
    if [[ -n "${BROWSER_BG:-}" ]]; then
        BROWSER_POLICY="{\"BrowserThemeColor\": \"$BROWSER_BG\", \"BackgroundModeEnabled\": false}"
        for browser in chromium brave; do
            command -v "$browser" &>/dev/null || continue
            mkdir -p "/etc/$browser/policies/managed" 2>/dev/null
            echo "$BROWSER_POLICY" > "/etc/$browser/policies/managed/color.json" 2>/dev/null
        done
    fi
elif $restart_eww; then
    log "Reloading EWW without restarting the daemon..."
    run_as_user "bar-ctl reload" || {
        err "EWW reload failed; deployment is incomplete."
        exit 1
    }
fi

if $restart_hypr; then
    log "Generating messenger bindings..."
    run_as_user "generate-messenger-bindings" 2>/dev/null || warn "  messenger bindings generation failed"
    log "Reloading Hyprland..."
    run_as_user "pkill rofi" 2>/dev/null || true
    run_as_user "hyprctl reload" || {
        err "Hyprland reload failed; deployment is incomplete."
        exit 1
    }
    log "  done"
fi

if [[ -n "$plugin_action" ]]; then
    log "Plugins: $plugin_action..."
    run_as_user "bash '$SRC_DIR/shared/bin/smplos-plugins' $plugin_action" || {
        err "Plugin $plugin_action failed; deployment is incomplete."
        exit 1
    }
fi

echo ""
log "${BOLD}All done!${NC}"
