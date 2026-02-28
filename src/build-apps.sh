#!/usr/bin/env bash
set -euo pipefail
#
# build-apps.sh -- Build all Rust apps + st-wl in a Podman container
#
# Usage:  ./build-apps.sh                    # build all apps (incremental)
#         ./build-apps.sh start-menu         # build one app
#         ./build-apps.sh disp-center st     # build specific apps + st-wl
#         ./build-apps.sh --clean            # wipe build cache, full rebuild
#         ./build-apps.sh --clean all        # clean + rebuild everything
#
# Outputs binaries to: .cache/app-binaries/
# Build cache persists at .cache/build-cache/ so cargo and make do incremental
# builds automatically on subsequent runs. Pass --clean to force a full rebuild.
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
CLEAN_BUILD=false
REQUESTED_APPS=()

for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN_BUILD=true ;;
        st|st-wl) BUILD_ST=true ;;
        all) REQUESTED_APPS=("${ALL_APPS[@]}"); BUILD_ST=true ;;
        *) REQUESTED_APPS+=("$arg") ;;
    esac
done

# Default: build all Rust apps (no-arg, or --clean with no specific apps)
if [[ ${#REQUESTED_APPS[@]} -eq 0 && "$BUILD_ST" == "false" ]]; then
    REQUESTED_APPS=("${ALL_APPS[@]}")
fi

# ── Main ──
detect_runtime

BIN_OUTPUT="$PROJECT_ROOT/.cache/app-binaries"
BUILD_CACHE="$PROJECT_ROOT/.cache/build-cache"
mkdir -p "$BIN_OUTPUT" "$BUILD_CACHE/cargo" "$BUILD_CACHE/st-build"

if [[ "$CLEAN_BUILD" == "true" ]]; then
    warn "Clean build requested — wiping build cache"
    rm -rf "$BUILD_CACHE"
    mkdir -p "$BUILD_CACHE/cargo" "$BUILD_CACHE/st-build"
fi

# Build script that runs inside the container
INNER_SCRIPT=$(cat << 'INNER'
#!/bin/bash
set -euo pipefail

SRC_DIR="/build/src"
OUT_DIR="/build/out"
CACHE_DIR="/build/cache"

# Install all build deps in one shot
pacman -Sy --noconfirm --needed \
    base-devel rust cargo cmake pkgconf \
    fontconfig freetype2 harfbuzz imlib2 \
    libxkbcommon wayland wayland-protocols pixman \
    libglvnd mesa openssl 2>/dev/null

# Build each requested Rust app
for app in $APPS; do
    app_src="$SRC_DIR/shared/$app"
    if [[ ! -f "$app_src/Cargo.toml" ]]; then
        echo "[build] $app: source not found, skipping"
        continue
    fi

    echo "[build] Building $app..."
    target_dir="$CACHE_DIR/cargo/$app"
    src_copy="$CACHE_DIR/src/$app"
    mkdir -p "$target_dir" "$src_copy"

    # Copy source to writable location (so cargo can update Cargo.lock)
    # target/ stays in persistent cache via CARGO_TARGET_DIR for incremental builds
    cp -r "$app_src/." "$src_copy/"

    CARGO_TARGET_DIR="$target_dir" cargo build --release \
        --manifest-path "$src_copy/Cargo.toml" 2>&1 | tail -5

    bin_path="$target_dir/release/$app"
    if [[ -x "$bin_path" ]]; then
        strip "$bin_path"
        cp "$bin_path" "$OUT_DIR/$app"
        echo "[build] $app: OK ($(du -h "$OUT_DIR/$app" | cut -f1))"
    else
        echo "[build] $app: FAILED"
    fi
done

# Build st-wl if requested
if [[ "$BUILD_ST" == "true" ]]; then
    echo "[build] Building st-wl..."
    ST_SRC="$SRC_DIR/compositors/hyprland/st"
    BUILD_DIR="$CACHE_DIR/st-build"
    if [[ -f "$ST_SRC/st.c" ]]; then
        # Sync source into persistent build dir so make sees file changes
        mkdir -p "$BUILD_DIR"
        cp -r "$ST_SRC/." "$BUILD_DIR/"
        cd "$BUILD_DIR"
        rm -f config.h patches.h  # always regenerate from .def.h
        [[ "$CLEAN_BUILD" == "true" ]] && make clean
        make -j"$(nproc)" 2>&1 | tail -5
        if [[ -f "$BUILD_DIR/st-wl" ]]; then
            strip "$BUILD_DIR/st-wl"
            cp "$BUILD_DIR/st-wl" "$OUT_DIR/st-wl"
            echo "[build] st-wl: OK"
        else
            echo "[build] st-wl: FAILED"
            exit 1
        fi
    fi
fi

echo ""
echo "[build] Done! Binaries in /build/out/:"
ls -lh "$OUT_DIR/"
INNER
)

run_args=(--rm --network=host)
run_args+=(-v "$SCRIPT_DIR:/build/src:ro")
run_args+=(-v "$BIN_OUTPUT:/build/out")
run_args+=(-v "$BUILD_CACHE:/build/cache")
if [[ -d /var/cache/pacman/pkg ]]; then
    run_args+=(-v "/var/cache/pacman/pkg:/var/cache/pacman/pkg:ro")
fi

run_args+=(-e "APPS=${REQUESTED_APPS[*]:-}")
run_args+=(-e "BUILD_ST=$BUILD_ST")
run_args+=(-e "CLEAN_BUILD=$CLEAN_BUILD")

log "Building: ${REQUESTED_APPS[*]:-}${BUILD_ST:+ st-wl}${CLEAN_BUILD:+ (clean)}"
log "Container: archlinux:latest via ${CTR}"
log "Cache:     $BUILD_CACHE/"
log "Output:    $BIN_OUTPUT/"
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
