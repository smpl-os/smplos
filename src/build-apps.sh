#!/usr/bin/env bash
set -euo pipefail
#
# build-apps.sh -- Build all Rust apps + st-wl + micro in a Podman container
#
# Usage:  ./build-apps.sh                    # build all Rust apps (incremental)
#         ./build-apps.sh st                  # build st-wl terminal only
#         ./build-apps.sh micro               # build micro editor only
#         ./build-apps.sh all                 # build Rust apps + st-wl + micro
#         ./build-apps.sh --clean             # wipe build cache, full rebuild
#         ./build-apps.sh --clean all         # clean + rebuild everything
#
# All Rust apps are built as a single Cargo workspace (shared/apps/). This
# ensures smpl-common (transparency + Wayland init) is compiled identically
# for every app. Individual app builds are NOT supported — the workspace is
# the single source of truth.
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
BUILD_ST=false
BUILD_MICRO=false
CLEAN_BUILD=false

for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN_BUILD=true ;;
        st|st-wl) BUILD_ST=true ;;
        micro) BUILD_MICRO=true ;;
        all) BUILD_ST=true; BUILD_MICRO=true ;;
        *) ;; # Individual app args ignored — workspace builds everything
    esac
done

# ── Main ──
detect_runtime

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

# All Rust apps are built as a single workspace — check the entire workspace
# directory for changes, not individual app subdirs.
APPS_REL="src/shared/apps"
BUILD_RUST_APPS=true

# Skip up-to-date builds (skips pacman + container overhead).
# In clean builds we skip this and let cargo decide what to recompile.
if [[ "$CLEAN_BUILD" == "false" ]]; then
    # Check if any Rust app binary is missing
    any_missing=false
    for bin in start-menu notif-center settings app-center webapp-center \
               sync-center-gui sync-center-daemon smpl-calendar smpl-calendar-alertd; do
        if [[ ! -f "$BIN_OUTPUT/$bin" ]]; then
            any_missing=true
            break
        fi
    done

    if [[ "$any_missing" == "false" ]]; then
        # All binaries exist — check if workspace source changed
        current_hash=$(git_tree_hash "$APPS_REL")
        stored_hash=$(cat "$BIN_OUTPUT/workspace.built-at" 2>/dev/null || echo "")
        if [[ -n "$current_hash" && "$current_hash" == "$stored_hash" ]] \
           && git_tree_clean "$APPS_REL"; then
            log "Rust apps: up to date"
            BUILD_RUST_APPS=false
        fi
    fi

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
fi

if [[ "$BUILD_RUST_APPS" == "false" && "$BUILD_ST" == "false" && "$BUILD_MICRO" == "false" ]]; then
    log "All apps up to date — nothing to build"
    exit 0
fi

# ── Guardrail: renderer-femtovg is MANDATORY for transparency ──
# The software renderer uses softbuffer which hardcodes wl_shm::Format::Xrgb8888
# on Wayland — alpha is completely ignored. FemtoVG uses OpenGL/EGL with ARGB
# visuals, so the compositor sees real alpha. Never use renderer-software or skia.
# Check workspace Cargo.toml (single source of truth for all apps).
_ws_toml="$PROJECT_ROOT/src/shared/apps/Cargo.toml"
if [[ -f "$_ws_toml" ]] && grep -q 'renderer-software\|renderer-skia' "$_ws_toml"; then
    die "Workspace Cargo.toml uses wrong renderer — transparency will break!
  The Slint feature MUST be 'renderer-femtovg', not 'renderer-software' or 'renderer-skia'.
  renderer-software uses softbuffer which hardcodes XRGB on Wayland (no alpha).
  See .github/copilot-instructions.md § 'Transparent Rust Apps' for why."
fi
# Also check smpl-common init code — the femtovg renderer string must match.
_common_lib="$PROJECT_ROOT/src/shared/apps/smpl-common/src/lib.rs"
if [[ -f "$_common_lib" ]] && ! grep -q 'with_renderer_name("femtovg")' "$_common_lib"; then
    die "smpl-common/src/lib.rs is missing .with_renderer_name(\"femtovg\")!
  This is required for transparency. Someone removed or changed it."
fi
# Validate Cargo.toml is syntactically valid TOML before spending minutes on
# container setup + pacman. Python 3.11+ (always on Arch) has tomllib builtin.
if [[ -f "$_ws_toml" ]] && command -v python3 &>/dev/null; then
    if ! python3 -c "
import sys
try:
    import tomllib
except ImportError:
    sys.exit(0)  # old python, skip check
with open(sys.argv[1], 'rb') as f:
    tomllib.load(f)
" "$_ws_toml" 2>/dev/null; then
        die "Workspace Cargo.toml has invalid TOML syntax!
  Common cause: missing or mismatched quotes in the features array.
  Fix the syntax in: src/shared/apps/Cargo.toml"
    fi
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
    base-devel rust cargo cmake pkgconf rsync \
    fontconfig freetype2 harfbuzz imlib2 \
    libxkbcommon wayland wayland-protocols pixman \
    libglvnd mesa openssl mold go 2>/dev/null

# Use mold linker -- significantly faster than GNU ld for Rust link step
export RUSTFLAGS="-C link-arg=-fuse-ld=mold"

# ── Workspace build ──────────────────────────────────────────────────────────
# All smplOS Rust apps live in a single Cargo workspace under shared/apps/.
# Building the whole workspace at once lets Cargo share the dependency graph
# and ensures smpl-common (shared init code for transparency + Wayland setup)
# is compiled once and linked into every app identically.
#
# Binary names to collect after build:
#   start-menu, notif-center, settings, app-center, webapp-center,
#   sync-center-gui, sync-center-daemon,
#   smpl-calendar, smpl-calendar-alertd

if [[ "$BUILD_RUST_APPS" == "true" ]]; then
    WS_SRC="$SRC_DIR/shared/apps"
    WS_COPY="$CACHE_DIR/src/workspace"
    WS_TARGET="$CACHE_DIR/cargo/workspace"
    mkdir -p "$WS_COPY" "$WS_TARGET"

    # Sync workspace source to writable location
    rsync -a --delete "$WS_SRC/" "$WS_COPY/"

    echo "[build] Building Rust workspace..."
    CARGO_TARGET_DIR="$WS_TARGET" cargo build --release \
        --manifest-path "$WS_COPY/Cargo.toml" \
        --workspace

    # Collect all expected binaries
    ALL_BINS="start-menu notif-center settings app-center webapp-center sync-center-gui sync-center-daemon smpl-calendar smpl-calendar-alertd"

    for bin in $ALL_BINS; do
        bin_path="$WS_TARGET/release/$bin"
        if [[ -x "$bin_path" ]]; then
            strip "$bin_path"
            cp "$bin_path" "$OUT_DIR/$bin"
            echo "[build] $bin: OK ($(du -h "$OUT_DIR/$bin" | cut -f1))"
        else
            echo "[build] WARNING: $bin not found in release/"
        fi
    done
fi

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

run_args+=(-e "BUILD_RUST_APPS=$BUILD_RUST_APPS")
run_args+=(-e "BUILD_ST=$BUILD_ST")
run_args+=(-e "BUILD_MICRO=$BUILD_MICRO")
run_args+=(-e "CLEAN_BUILD=$CLEAN_BUILD")

log "Building:${BUILD_RUST_APPS:+ Rust workspace}${BUILD_ST:+ st-wl}${BUILD_MICRO:+ micro}${CLEAN_BUILD:+ (clean)}"
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

# Save the git tree-object SHA for the workspace so the next run can skip it.
# Only written when the working tree is clean — dirty local edits stay stale
# until committed, forcing a rebuild after the commit.
if [[ "$BUILD_RUST_APPS" == "true" ]] && git_tree_clean "$APPS_REL"; then
    git_tree_hash "$APPS_REL" > "$BIN_OUTPUT/workspace.built-at"
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

echo ""
log "${BOLD}Binaries ready:${NC}"
ls -lh "$BIN_OUTPUT/"
