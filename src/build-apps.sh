#!/usr/bin/env bash
set -euo pipefail
#
# build-apps.sh -- Build all Rust apps in a Podman container (same as ISO build)
#
# This ensures dev builds use the exact same environment as the ISO,
# and the host machine never needs Rust/cargo installed.
#
# Usage:  ./build-apps.sh                    # build all apps
#         ./build-apps.sh start-menu         # build one app
#         ./build-apps.sh disp-center st     # build specific apps + st-wl
#
# Outputs binaries to: .cache/binaries/<app-name>-latest
# These are consumed by dev-push.sh and dev-local.sh
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${GREEN}[build-apps]${NC} $*"; }
warn() { echo -e "${YELLOW}[build-apps]${NC} $*"; }
die()  { echo -e "${RED}[build-apps]${NC} $*" >&2; exit 1; }

# ── Container runtime detection (shared with build-iso.sh) ──
CTR=""
detect_runtime() {
    if command -v podman &>/dev/null; then
        CTR="sudo podman"
    elif command -v docker &>/dev/null; then
        if docker info &>/dev/null 2>&1; then
            CTR="docker"
        elif sudo -n docker info &>/dev/null 2>&1; then
            CTR="sudo docker"
        else
            die "Docker daemon not running"
        fi
    else
        die "No container runtime found. Install podman: https://podman.io/docs/installation"
    fi
}

# ── Parse arguments ──
ALL_APPS=(start-menu notif-center kb-center disp-center app-center webapp-center)
BUILD_ST=false
REQUESTED_APPS=()

if [[ $# -eq 0 ]]; then
    REQUESTED_APPS=("${ALL_APPS[@]}")
else
    for arg in "$@"; do
        if [[ "$arg" == "st" || "$arg" == "st-wl" ]]; then
            BUILD_ST=true
        elif [[ "$arg" == "all" ]]; then
            REQUESTED_APPS=("${ALL_APPS[@]}")
            BUILD_ST=true
        else
            REQUESTED_APPS+=("$arg")
        fi
    done
fi

# ── Main ──
detect_runtime

# Persistent binary output dir (same as ISO build uses)
BIN_OUTPUT="$PROJECT_ROOT/.cache/app-binaries"
mkdir -p "$BIN_OUTPUT"

# Build script that runs inside the container
INNER_SCRIPT=$(cat << 'INNER'
#!/bin/bash
set -euo pipefail

SRC_DIR="/build/src"
OUT_DIR="/build/out"

# Install common build deps once
pacman -Sy --noconfirm --needed rust cargo cmake pkgconf fontconfig freetype2 \
    libxkbcommon wayland libglvnd mesa openssl 2>/dev/null

# Build each requested Rust app
for app in $APPS; do
    app_src="$SRC_DIR/shared/$app"
    if [[ ! -f "$app_src/Cargo.toml" ]]; then
        echo "[build] $app: source not found, skipping"
        continue
    fi

    echo "[build] Building $app..."
    build_dir="/tmp/${app}-build"
    rm -rf "$build_dir"
    cp -r "$app_src" "$build_dir"
    cd "$build_dir"
    cargo build --release 2>&1 | tail -5

    bin_path="$build_dir/target/release/$app"
    if [[ -x "$bin_path" ]]; then
        strip "$bin_path"
        cp "$bin_path" "$OUT_DIR/$app"
        echo "[build] $app: OK ($(du -h "$OUT_DIR/$app" | cut -f1))"
    else
        echo "[build] $app: FAILED"
    fi
    rm -rf "$build_dir"
done

# Build st-wl if requested
if [[ "$BUILD_ST" == "true" ]]; then
    echo "[build] Building st-wl..."
    ST_SRC="$SRC_DIR/compositors/hyprland/st"
    if [[ -f "$ST_SRC/st.c" ]]; then
        pacman --noconfirm --needed -S wayland wayland-protocols libxkbcommon \
            pixman fontconfig freetype2 harfbuzz pkg-config 2>/dev/null
        build_dir="/tmp/st-build"
        rm -rf "$build_dir"
        cp -r "$ST_SRC" "$build_dir"
        cd "$build_dir"
        rm -f config.h
        make clean && make -j"$(nproc)" 2>&1 | tail -3
        if [[ -f "$build_dir/st-wl" ]]; then
            strip "$build_dir/st-wl"
            cp "$build_dir/st-wl" "$OUT_DIR/st-wl"
            echo "[build] st-wl: OK"
        else
            echo "[build] st-wl: FAILED"
        fi
        rm -rf "$build_dir"
    fi
fi

echo ""
echo "[build] Done! Binaries in /build/out/:"
ls -lh "$OUT_DIR/"
INNER
)

# Mount host pacman cache if on Arch (speeds up pacman -Sy enormously)
run_args=(--rm --network=host)
run_args+=(-v "$SCRIPT_DIR:/build/src:ro")
run_args+=(-v "$BIN_OUTPUT:/build/out")
if [[ -d /var/cache/pacman/pkg ]]; then
    run_args+=(-v "/var/cache/pacman/pkg:/var/cache/pacman/pkg:ro")
fi

# Pass the app list and st flag as env vars
run_args+=(-e "APPS=${REQUESTED_APPS[*]}")
run_args+=(-e "BUILD_ST=$BUILD_ST")

log "Building: ${REQUESTED_APPS[*]}${BUILD_ST:+ st-wl}"
log "Container: archlinux:latest via ${CTR}"
log "Output: $BIN_OUTPUT/"
echo ""

$CTR pull archlinux:latest 2>/dev/null

$CTR run "${run_args[@]}" archlinux:latest \
    bash -c "$INNER_SCRIPT"

rc=$?
if [[ $rc -ne 0 ]]; then
    die "Container build failed (exit $rc)"
fi

echo ""
log "${BOLD}Binaries ready:${NC}"
ls -lh "$BIN_OUTPUT/"
