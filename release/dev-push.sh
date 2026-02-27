#!/usr/bin/env bash
set -euo pipefail
#
# dev-push.sh -- Push all source files into vmshare/ for the VM
#
# Usage:  ./dev-push.sh
#
# In the VM:  sudo bash /mnt/dev-apply.sh
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(dirname "$SCRIPT_DIR")/src"
SHARE="$SCRIPT_DIR/vmshare"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[push]${NC} $*"; }

# Clean and recreate
rm -rf "$SHARE"/{eww,bin,hypr,themes,configs,icons,st,notif-center,kb-center,disp-center,webapp-center,app-center,start-menu,applications}
mkdir -p "$SHARE"/{eww,bin,hypr,themes,configs,icons,st,notif-center,kb-center,disp-center,webapp-center,app-center,start-menu,applications}

# EWW
cp -r "$SRC_DIR/shared/eww/"* "$SHARE/eww/"
find "$SHARE/eww/scripts" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
log "EWW: $(find "$SHARE/eww" -type f | wc -l) files"

# Shared icons (SVG status icons for EWW bar)
if [[ -d "$SRC_DIR/shared/icons" ]]; then
    cp -r "$SRC_DIR/shared/icons/"* "$SHARE/icons/"
    log "Icons: $(find "$SHARE/icons" -type f | wc -l) files"
fi

# Bin scripts
cp -r "$SRC_DIR/shared/bin/"* "$SHARE/bin/"
chmod +x "$SHARE/bin/"* 2>/dev/null || true
log "Bin: $(find "$SHARE/bin" -type f | wc -l) files"

# Shared configs
cp -r "$SRC_DIR/shared/configs/"* "$SHARE/configs/"
log "Configs: $(find "$SHARE/configs" -type f | wc -l) files"

# Applications (.desktop files)
if [[ -d "$SRC_DIR/shared/applications" ]]; then
    cp "$SRC_DIR/shared/applications/"*.desktop "$SHARE/applications/" 2>/dev/null || true
    log "Applications: $(find "$SHARE/applications" -type f | wc -l) files"
fi

# Hyprland configs + shared bindings.conf
cp -r "$SRC_DIR/compositors/hyprland/hypr/"* "$SHARE/hypr/"
[[ -f "$SRC_DIR/shared/configs/smplos/bindings.conf" ]] && \
    cp "$SRC_DIR/shared/configs/smplos/bindings.conf" "$SHARE/hypr/bindings.conf"
log "Hypr: $(find "$SHARE/hypr" -type f | wc -l) files"

# Themes
cp -r "$SRC_DIR/shared/themes/"* "$SHARE/themes/"
log "Themes: $(find "$SHARE/themes" -type f | wc -l) files"

# ── Rust apps + st-wl (use container-built binaries from build-apps.sh) ──
BIN_DIR="$(dirname "$SCRIPT_DIR")/.cache/app-binaries"
RUST_APPS=(notif-center kb-center disp-center webapp-center app-center start-menu)

# Auto-build if any binary is missing
needs_build=false
for app in "${RUST_APPS[@]}"; do
    [[ -f "$BIN_DIR/$app" ]] || { needs_build=true; break; }
done
if $needs_build; then
    log "Binaries missing -- running build-apps.sh in container..."
    "$SRC_DIR/../src/build-apps.sh" all
fi

for app in "${RUST_APPS[@]}"; do
    mkdir -p "$SHARE/$app"
    if [[ -f "$BIN_DIR/$app" ]]; then
        cp "$BIN_DIR/$app" "$SHARE/$app/"
        log "$app: binary staged"
    else
        log "$app: binary not found (run: src/build-apps.sh)"
    fi
done

if [[ -f "$BIN_DIR/st-wl" ]]; then
    cp "$BIN_DIR/st-wl" "$SHARE/st/"
    log "st-wl: binary staged"
    ST_DIR="$SRC_DIR/compositors/hyprland/st"
    [[ -f "$ST_DIR/st-wl.desktop" ]] && cp "$ST_DIR/st-wl.desktop" "$SHARE/st/" 2>/dev/null || true
fi

# Copy the apply script itself
cp "$SCRIPT_DIR/dev-apply.sh" "$SHARE/dev-apply.sh"
chmod +x "$SHARE/dev-apply.sh"

log ""
log "Done! In the VM run:  ${YELLOW}sudo bash /mnt/dev-apply.sh${NC}"
