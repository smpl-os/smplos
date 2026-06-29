#!/usr/bin/env bash
set -euo pipefail
#
# build-apps.sh -- Fetch smpl-apps binaries + build st-wl / micro in a container
#
# Usage:  ./build-apps.sh                    # fetch latest smpl-apps + incremental st/micro
#         ./build-apps.sh st                  # build st-wl terminal only
#         ./build-apps.sh micro               # build micro editor only
#         ./build-apps.sh xr                  # build xr-workspace XR renderer only
#         ./build-apps.sh all                 # fetch apps + build st-wl + micro + xr-workspace
#         ./build-apps.sh --clean             # force re-fetch apps, clean rebuild st/micro/xr
#
# Rust GUI apps (start-menu, settings, etc.) are fetched from GitHub Releases
# via fetch-apps.sh — no container or local Rust toolchain needed for them.
# Only st-wl, micro and xr-workspace are built locally in a container (native
# C/C++/Go apps). xr-workspace source is an independent repo auto-detected as a
# sibling of smpl-os (override with XR_WORKSPACE_REPO=/path/to/xr-workspace).
#
# Outputs binaries to: .cache/app-binaries/
# Build cache persists at .cache/build-cache/ (make/cargo incremental for st/micro).
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
BUILD_ST=false
BUILD_MICRO=false
BUILD_XR=false
CLEAN_BUILD=false

for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN_BUILD=true ;;
        st|st-wl) BUILD_ST=true ;;
        micro) BUILD_MICRO=true ;;
        xr|xr-workspace) BUILD_XR=true ;;
        all) BUILD_ST=true; BUILD_MICRO=true; BUILD_XR=true ;;
        *) ;; # Individual app args ignored — workspace builds everything
    esac
done

# ── Main ──
BIN_OUTPUT="$PROJECT_ROOT/.cache/app-binaries"
BUILD_CACHE="$PROJECT_ROOT/.cache/build-cache"
mkdir -p "$BIN_OUTPUT" "$BUILD_CACHE/cargo" "$BUILD_CACHE/st-build" "$BUILD_CACHE/micro-build"

if [[ "$CLEAN_BUILD" == "true" ]]; then
    warn "Clean build requested — wiping build cache"
    rm -rf "$BUILD_CACHE"
    mkdir -p "$BUILD_CACHE/cargo" "$BUILD_CACHE/st-build"
fi

# ── Git-based staleness check ──
# Use git's own tree-object SHA for a repo-relative path at HEAD.
# This is what git already computed — no manual file hashing needed.
git_tree_hash() {
    git -C "$PROJECT_ROOT" rev-parse "HEAD:$1" 2>/dev/null || echo ""
}
# Exit 0 if the working tree is clean for the given repo-relative path.
git_tree_clean() {
    git -C "$PROJECT_ROOT" diff --quiet HEAD -- "$1" 2>/dev/null
}

# Locate the xr-workspace source repo. Override with XR_WORKSPACE_REPO, else try
# the usual sibling locations (sibling of smpl-os, or inside it).
find_xr_repo() {
    local candidates=(
        "${XR_WORKSPACE_REPO:-}"
        "$PROJECT_ROOT/../../xr-workspace"   # sibling of smpl-os meta-dir
        "$PROJECT_ROOT/../xr-workspace"       # inside smpl-os meta-dir
    )
    local c
    for c in "${candidates[@]}"; do
        [[ -n "$c" && -f "$c/CMakeLists.txt" ]] && { (cd "$c" && pwd); return 0; }
    done
    echo ""
}

# ── Fetch Rust app binaries from GitHub ──────────────────────────────────────
# fetch-apps.sh checks the latest GitHub release and skips the download if the
# binaries are already current. Pass --force (via --clean) to re-fetch anyway.
FETCH_FLAG=""
[[ "$CLEAN_BUILD" == "true" ]] && FETCH_FLAG="--force"
bash "$SCRIPT_DIR/fetch-apps.sh" $FETCH_FLAG

# ── Staleness checks for container-built binaries (st-wl, micro) ─────────────
if [[ "$CLEAN_BUILD" == "false" ]]; then
    if [[ "$BUILD_ST" == "true" ]]; then
        st_current=$(git_tree_hash "src/compositors/hyprland/st")
        st_stored=$(cat "$BIN_OUTPUT/st-wl.built-at" 2>/dev/null || echo "")
        if [[ -f "$BIN_OUTPUT/st-wl" && -n "$st_current" \
              && "$st_current" == "$st_stored" ]] \
           && git_tree_clean "src/compositors/hyprland/st"; then
            log "st-wl: up to date"
            BUILD_ST=false
        fi
    fi

    # micro: the source lives in the micro/ sibling repo (separate git root).
    # We use the micro-patched binary's mtime or a stored hash for staleness.
    if [[ "$BUILD_MICRO" == "true" ]]; then
        MICRO_REPO="$PROJECT_ROOT/../micro"
        if [[ -d "$MICRO_REPO/.git" ]]; then
            micro_current=$(git -C "$MICRO_REPO" rev-parse HEAD 2>/dev/null || echo "")
            micro_stored=$(cat "$BIN_OUTPUT/micro.built-at" 2>/dev/null || echo "")
            if [[ -f "$BIN_OUTPUT/micro" && -n "$micro_current" \
                  && "$micro_current" == "$micro_stored" ]]; then
                log "micro: up to date"
                BUILD_MICRO=false
            fi
        fi
    fi

    # xr-workspace: VITURE XR virtual-monitor renderer (C++/CMake). Its source
    # is an independent repo; we auto-detect it as a sibling of smpl-os (or of
    # smplos) and use its git HEAD for staleness, exactly like micro.
    if [[ "$BUILD_XR" == "true" ]]; then
        XR_REPO="$(find_xr_repo)"
        if [[ -n "$XR_REPO" && -d "$XR_REPO/.git" ]]; then
            xr_current=$(git -C "$XR_REPO" rev-parse HEAD 2>/dev/null || echo "")
            xr_stored=$(cat "$BIN_OUTPUT/xr-workspace.built-at" 2>/dev/null || echo "")
            if [[ -f "$BIN_OUTPUT/xr-workspace" && -n "$xr_current" \
                  && "$xr_current" == "$xr_stored" ]]; then
                log "xr-workspace: up to date"
                BUILD_XR=false
            fi
        elif [[ -z "$XR_REPO" ]]; then
            warn "xr-workspace: source repo not found (set XR_WORKSPACE_REPO) — skipping"
            BUILD_XR=false
        fi
    fi
fi

if [[ "$BUILD_ST" == "false" && "$BUILD_MICRO" == "false" && "$BUILD_XR" == "false" ]]; then
    log "st-wl, micro and xr-workspace are up to date — container not needed"
    log "${BOLD}Binaries ready:${NC}"
    ls -lh "$BIN_OUTPUT/"
    exit 0
fi

# ── Container build for st-wl and micro ──────────────────────────────────────
detect_runtime

# Build script that runs inside the container
INNER_SCRIPT=$(cat << 'INNER'
#!/bin/bash
set -euo pipefail

SRC_DIR="/build/src"
OUT_DIR="/build/out"
CACHE_DIR="/build/cache"

# Install build deps for st-wl and micro only (no Rust/cargo needed)
pacman -Sy --noconfirm --needed \
    base-devel cmake pkgconf rsync \
    fontconfig freetype2 harfbuzz imlib2 \
    libxkbcommon wayland wayland-protocols pixman \
    libglvnd mesa openssl go 2>/dev/null

# (xr-workspace shares these deps: wayland + wayland-protocols provide
#  wayland-scanner; mesa provides EGL/GLES/GBM; cmake/pkgconf cover the rest.)

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
        make -j"$(nproc)"
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

# Build micro editor if requested
if [[ "$BUILD_MICRO" == "true" ]]; then
    echo "[build] Building micro editor..."
    MICRO_SRC="/build/micro-src"
    MICRO_BUILD="$CACHE_DIR/micro-build"
    if [[ -d "$MICRO_SRC" ]]; then
        mkdir -p "$MICRO_BUILD"
        rsync -a --delete "$MICRO_SRC/" "$MICRO_BUILD/"
        cd "$MICRO_BUILD"
        make generate
        make build-release
        if [[ -f "$MICRO_BUILD/micro" ]]; then
            strip "$MICRO_BUILD/micro"
            cp "$MICRO_BUILD/micro" "$OUT_DIR/micro"
            echo "[build] micro: OK ($(du -h "$OUT_DIR/micro" | cut -f1))"
        else
            echo "[build] micro: FAILED"
            exit 1
        fi
    else
        echo "[build] micro: source not found at $MICRO_SRC (skipping)"
    fi
fi

# Build xr-workspace (VITURE XR virtual-monitor renderer) if requested
if [[ "$BUILD_XR" == "true" ]]; then
    echo "[build] Building xr-workspace..."
    XR_SRC="/build/xr-src"
    XR_BUILD="$CACHE_DIR/xr-build"
    if [[ -f "$XR_SRC/CMakeLists.txt" ]]; then
        mkdir -p "$XR_BUILD"
        rsync -a --delete --exclude build/ "$XR_SRC/" "$XR_BUILD/"
        cd "$XR_BUILD"
        [[ "$CLEAN_BUILD" == "true" ]] && rm -rf build
        cmake -B build -DCMAKE_BUILD_TYPE=Release
        cmake --build build -j"$(nproc)"
        if [[ -f "$XR_BUILD/build/xr-workspace" ]]; then
            strip "$XR_BUILD/build/xr-workspace" || true
            cp "$XR_BUILD/build/xr-workspace" "$OUT_DIR/xr-workspace"
            # Control clients + hotplug launcher.
            cp "$XR_BUILD/xrctl" "$OUT_DIR/xrctl"
            cp "$XR_BUILD/xr-game" "$OUT_DIR/xr-game"
            cp "$XR_BUILD/packaging/hotplug/xr-glasses-hotplugd" "$OUT_DIR/xr-glasses-hotplugd"
            # Stage packaging artifacts (udev/systemd/hypr/config) for the ISO
            # builder to install — keeps xr-workspace the single source of truth.
            rm -rf "$OUT_DIR/xr-packaging"
            mkdir -p "$OUT_DIR/xr-packaging"
            cp -r "$XR_BUILD/packaging/udev"    "$OUT_DIR/xr-packaging/"
            cp -r "$XR_BUILD/packaging/systemd" "$OUT_DIR/xr-packaging/"
            cp -r "$XR_BUILD/packaging/hypr"    "$OUT_DIR/xr-packaging/"
            cp "$XR_BUILD/config.example.json"  "$OUT_DIR/xr-packaging/config.example.json" 2>/dev/null || true
            chmod +x "$OUT_DIR/xrctl" "$OUT_DIR/xr-game" "$OUT_DIR/xr-glasses-hotplugd"
            echo "[build] xr-workspace: OK ($(du -h "$OUT_DIR/xr-workspace" | cut -f1))"
        else
            echo "[build] xr-workspace: FAILED"
            exit 1
        fi
    else
        echo "[build] xr-workspace: source not found at $XR_SRC (skipping)"
    fi
fi

echo ""
echo "[build] Done! Binaries in /build/out/:"
ls -lh "$OUT_DIR/"
INNER
)

# Persist downloaded packages across container runs -- pacman reuses cached tarballs
mkdir -p "$BUILD_CACHE/pacman-pkg"

run_args=(--rm --network=host --cpus "$(nproc)")
run_args+=(-v "$SCRIPT_DIR:/build/src:ro")
run_args+=(-v "$BIN_OUTPUT:/build/out")
run_args+=(-v "$BUILD_CACHE:/build/cache")
run_args+=(-v "$BUILD_CACHE/pacman-pkg:/var/cache/pacman/pkg")

# Mount the micro source repo (sibling directory) if building micro
MICRO_REPO="$PROJECT_ROOT/../micro"
if [[ "$BUILD_MICRO" == "true" && -d "$MICRO_REPO" ]]; then
    run_args+=(-v "$(cd "$MICRO_REPO" && pwd):/build/micro-src:ro")
fi

# Mount the xr-workspace source repo (independent repo) if building it
XR_REPO="$(find_xr_repo)"
if [[ "$BUILD_XR" == "true" && -n "$XR_REPO" ]]; then
    run_args+=(-v "$XR_REPO:/build/xr-src:ro")
fi

run_args+=(-e "BUILD_ST=$BUILD_ST")
run_args+=(-e "BUILD_MICRO=$BUILD_MICRO")
run_args+=(-e "BUILD_XR=$BUILD_XR")
run_args+=(-e "CLEAN_BUILD=$CLEAN_BUILD")

log "Building:${BUILD_ST:+ st-wl}${BUILD_MICRO:+ micro}${BUILD_XR:+ xr-workspace}${CLEAN_BUILD:+ (clean)}"
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

if [[ "$BUILD_ST" == "true" && -f "$BIN_OUTPUT/st-wl" ]]; then
    if git_tree_clean "src/compositors/hyprland/st"; then
        git_tree_hash "src/compositors/hyprland/st" > "$BIN_OUTPUT/st-wl.built-at"
    fi
fi
if [[ "$BUILD_MICRO" == "true" && -f "$BIN_OUTPUT/micro" ]]; then
    MICRO_REPO="$PROJECT_ROOT/../micro"
    if [[ -d "$MICRO_REPO/.git" ]]; then
        git -C "$MICRO_REPO" rev-parse HEAD > "$BIN_OUTPUT/micro.built-at" 2>/dev/null || true
    fi
fi
if [[ "$BUILD_XR" == "true" && -f "$BIN_OUTPUT/xr-workspace" ]]; then
    XR_REPO="$(find_xr_repo)"
    if [[ -n "$XR_REPO" && -d "$XR_REPO/.git" ]]; then
        git -C "$XR_REPO" rev-parse HEAD > "$BIN_OUTPUT/xr-workspace.built-at" 2>/dev/null || true
    fi
fi

echo ""
log "${BOLD}Binaries ready:${NC}"
ls -lh "$BIN_OUTPUT/"
