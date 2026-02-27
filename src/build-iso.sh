#!/bin/bash
#
# smplOS ISO Builder
# Builds the ISO in a clean Arch Linux container for reproducibility.
# Uses Podman (preferred, daemonless) or Docker as the container runtime.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Build log directory (persists across runs for debugging)
LOG_DIR="$PROJECT_ROOT/.cache/logs"
mkdir -p "$LOG_DIR"
BUILD_LOG="$LOG_DIR/build-$(date +%Y%m%d-%H%M%S).log"

# Tee all output (stdout + stderr) to the log file AND the terminal for the
# entire script lifetime.  Using exec here avoids the external pipe approach
# (./build-iso.sh | tee ...) which gets killed by SIGINT when you run any
# monitoring command in the same terminal session.
exec > >(tee -a "$BUILD_LOG") 2>&1

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
log_step()  { echo -e "\n${BLUE}${BOLD}==>${NC}${BOLD} $*${NC}"; }

die() { log_error "$@"; exit 1; }

###############################################################################
# Help
###############################################################################

show_help() {
    cat << 'EOF'
smplOS ISO Builder

Usage: build-iso.sh [EDITIONS...] [OPTIONS]

Editions (stackable):
    -p, --productivity      Office & workflow (Logseq, LibreOffice, etc.)
    -c, --creators          Design & media (OBS, Kdenlive, GIMP)
    -m, --communication     Chat & calls (Discord, Signal, Slack, etc.)
    -d, --development       Developer tools (VSCode, LazyVim, lazygit)
    -a, --ai                AI tools (ollama, etc.)
    --all                   All editions (equivalent to -p -c -m -d -a)

Options:
    --compositor NAME       Compositor to build (hyprland, dwm) [default: hyprland]
    -r, --release           Release build: max xz compression (slow, smallest ISO)
    -n, --no-cache          Force fresh package downloads
    -v, --verbose           Verbose output
    --skip-aur              Skip AUR packages (faster, no Rust compilation)
    --skip-flatpak          Skip Flatpak packages
    --skip-appimage         Skip AppImages
    -h, --help              Show this help

Examples:
    ./build-iso.sh                        # Base build (no editions)
    ./build-iso.sh -p                     # Productivity edition
    ./build-iso.sh --all                  # All editions
    ./build-iso.sh --all --skip-aur       # All editions, skip AUR
    ./build-iso.sh --release              # Max compression for release
EOF
}

###############################################################################
# Arguments
###############################################################################

COMPOSITOR="hyprland"
EDITIONS=""
RELEASE=""
NO_CACHE=""
VERBOSE=""
SKIP_AUR=""
SKIP_FLATPAK=""
SKIP_APPIMAGE=""

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -p|--productivity)  EDITIONS="${EDITIONS:+$EDITIONS,}productivity"; shift ;;
            -c|--creators)      EDITIONS="${EDITIONS:+$EDITIONS,}creators"; shift ;;
            -m|--communication) EDITIONS="${EDITIONS:+$EDITIONS,}communication"; shift ;;
            -d|--development)   EDITIONS="${EDITIONS:+$EDITIONS,}development"; shift ;;
            -a|--ai)            EDITIONS="${EDITIONS:+$EDITIONS,}ai"; shift ;;
            --all)              EDITIONS="productivity,creators,communication,development,ai"; shift ;;
            --compositor)       COMPOSITOR="$2"; shift 2 ;;
            -r|--release)       RELEASE="1"; shift ;;
            -n|--no-cache)      NO_CACHE="1"; shift ;;
            -v|--verbose)       VERBOSE="1"; shift ;;
            --skip-aur)         SKIP_AUR="1"; shift ;;
            --skip-flatpak)     SKIP_FLATPAK="1"; shift ;;
            --skip-appimage)    SKIP_APPIMAGE="1"; shift ;;
            -h|--help)          show_help; exit 0 ;;
            *) die "Unknown option: $1 (see --help)" ;;
        esac
    done
}

###############################################################################
# Container Runtime Detection
###############################################################################

# Container command -- set by detect_runtime()
CTR=""

detect_runtime() {
    if command -v podman &>/dev/null; then
        # mkarchiso needs real root (loop devices, mount, mksquashfs).
        # Rootless podman --privileged only grants unprivileged-user caps,
        # which is not enough.  So we need sudo for the actual container runs,
        # but podman itself needs no daemon or background service.
        CTR="sudo podman"
        log_info "Container runtime: Podman ($(podman --version 2>/dev/null | head -1))"
    elif command -v docker &>/dev/null; then
        CTR="docker"
        # Docker needs its daemon running and the user in the docker group
        if ! docker info &>/dev/null 2>&1; then
            if sudo -n docker info &>/dev/null 2>&1; then
                CTR="sudo docker"
            else
                die "Docker daemon not running. Start it: sudo systemctl start docker"
            fi
        fi
        log_info "Container runtime: Docker ($(docker --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' | head -1))"
        # Docker's daemon architecture needs SIGPIPE protection
        trap '' PIPE
    else
        return 1
    fi
}

install_runtime() {
    local distro="$1"
    log_step "Installing Podman"

    case "$distro" in
        arch|endeavouros|manjaro|garuda|cachyos)
            sudo pacman -S --noconfirm --needed podman
            ;;
        ubuntu|debian|pop|linuxmint|zorin)
            sudo apt-get update
            sudo apt-get install -y podman
            ;;
        fedora|nobara)
            sudo dnf install -y podman
            ;;
        opensuse*|sles)
            sudo zypper install -y podman
            ;;
        void)
            sudo xbps-install -y podman
            ;;
        *)
            die "Unknown distro '$distro'. Install podman manually: https://podman.io/docs/installation"
            ;;
    esac
}

###############################################################################
# Prerequisites
###############################################################################

detect_distro() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        echo "${ID:-unknown}"
    elif command -v lsb_release &>/dev/null; then
        lsb_release -si | tr '[:upper:]' '[:lower:]'
    else
        echo "unknown"
    fi
}

check_prerequisites() {
    log_step "Checking prerequisites"
    local distro
    distro=$(detect_distro)
    log_info "Detected distro: $distro"

    # Container runtime installed?
    if ! detect_runtime; then
        log_warn "No container runtime found (podman or docker)"
        read -rp "Install Podman automatically? [Y/n] " answer
        if [[ "${answer,,}" != "n" ]]; then
            install_runtime "$distro"
            detect_runtime || die "Podman installation failed"
        else
            die "A container runtime is required. Install podman: https://podman.io/docs/installation"
        fi
    fi

    # Disk space check (need ~10GB)
    local free_gb
    free_gb=$(df --output=avail -BG "$PROJECT_ROOT" 2>/dev/null | tail -1 | tr -dc '0-9')
    if [[ -n "$free_gb" && "$free_gb" -lt 10 ]]; then
        log_warn "Low disk space: ${free_gb}GB free (10GB+ recommended)"
        read -rp "Continue anyway? [y/N] " answer
        [[ "${answer,,}" == "y" ]] || exit 1
    fi

    log_info "Prerequisites OK"

    # Pre-authenticate sudo so the password prompt happens here with context,
    # not mid-build with no explanation.  mkarchiso requires real root for
    # loop devices, mount, and mksquashfs -- rootless containers can't do that.
    if [[ "$CTR" == sudo* ]]; then
        log_info "sudo is required: mkarchiso needs root for loop devices and mounts"
        sudo -v || die "sudo authentication failed"
    fi
}

###############################################################################
# Build Missing AUR Packages (with retries and proper DNS)
###############################################################################

build_missing_aur_packages() {
    local prebuilt_dir="$PROJECT_ROOT/build/prebuilt"
    mkdir -p "$prebuilt_dir"

    # Collect AUR package names from all package lists
    local aur_packages=()
    for f in "$SCRIPT_DIR/shared/packages-aur.txt" "$SCRIPT_DIR/compositors/${COMPOSITOR}/packages-aur.txt"; do
        [[ -f "$f" ]] || continue
        while IFS= read -r line; do
            [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
            aur_packages+=("$line")
        done < "$f"
    done
    # Edition AUR extras (iterate all stacked editions)
    if [[ -n "${EDITIONS:-}" ]]; then
        IFS=',' read -ra _eds <<< "$EDITIONS"
        for _ed in "${_eds[@]}"; do
            local _aur_file="$SCRIPT_DIR/editions/${_ed}/packages-aur-extra.txt"
            [[ -f "$_aur_file" ]] || continue
            while IFS= read -r line; do
                [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
                aur_packages+=("$line")
            done < "$_aur_file"
        done
    fi
    [[ ${#aur_packages[@]} -eq 0 ]] && return 0

    # Check which need building
    local need_build=()
    for pkg in "${aur_packages[@]}"; do
        if ! ls "$prebuilt_dir"/${pkg}-[0-9]*.pkg.tar.* &>/dev/null; then
            need_build+=("$pkg")
        else
            log_info "Found prebuilt: $pkg"
        fi
    done
    [[ ${#need_build[@]} -eq 0 ]] && { log_info "All AUR packages already built"; return 0; }

    log_step "Building AUR packages: ${need_build[*]}"
    log_info "This may take a while on first run..."

    # Detect if any package needs Rust (avoid installing rustup otherwise)
    local rust_line=""
    for pkg in "${need_build[@]}"; do
        case "$pkg" in eww|eww-git|eww-wayland|*-rs|*-rust)
            rust_line="retry pacman -S --noconfirm --needed rustup && rustup default stable"
            break ;;
        esac
    done

    # Write package list to file (avoids shell quoting bugs in heredoc)
    local pkg_list_file
    pkg_list_file=$(mktemp)
    printf '%s\n' "${need_build[@]}" > "$pkg_list_file"

    $CTR run --rm \
        --network=host \
        -v "$prebuilt_dir:/output" \
        -v "$pkg_list_file:/tmp/packages.txt:ro" \
        archlinux:latest bash -c "
            set -e
            retry() {
                local n=0
                while true; do
                    \"\$@\" && return 0
                    ((n++))
                    [[ \$n -ge 3 ]] && { echo \"FAILED after 3 tries: \$*\"; return 1; }
                    echo \"RETRY \$n/3: \$*\"
                    sleep \$((n * 5))
                done
            }
            retry pacman -Syu --noconfirm
            retry pacman -S --noconfirm --needed base-devel git
            ${rust_line}
            useradd -m builder
            echo 'builder ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers
            cd /home/builder
            while IFS= read -r pkg; do
                [[ -z \"\$pkg\" ]] && continue
                echo \"==> Building \$pkg...\"
                retry sudo -u builder git clone \"https://aur.archlinux.org/\$pkg.git\"
                cd \"\$pkg\"
                # Import any PGP keys required by the package
                if grep -q 'validpgpkeys' PKGBUILD; then
                    grep -A 20 'validpgpkeys=' PKGBUILD \
                        | grep -oP '[0-9A-F]{16,}' \
                        | while read -r key; do
                            echo \"==> Importing GPG key: \$key\"
                            sudo -u builder gpg --keyserver keyserver.ubuntu.com --recv-keys \"\$key\" 2>/dev/null \
                                || sudo -u builder gpg --keyserver keys.openpgp.org --recv-keys \"\$key\" 2>/dev/null \
                                || echo \"WARN: could not import key \$key\"
                        done
                fi
                sudo -u builder makepkg -s --noconfirm
                cp *.pkg.tar.* /output/
                cd ..
                echo \"==> \$pkg done\"
            done < /tmp/packages.txt
            echo '==> All AUR packages built!'
        " || die "AUR package build failed"

    rm -f "$pkg_list_file"
    log_info "AUR packages saved to: $prebuilt_dir"
}

###############################################################################
# Container Build
###############################################################################

run_build() {
    log_step "Starting ISO build"
    log_info "Compositor: $COMPOSITOR"
    [[ -n "$EDITIONS" ]]  && log_info "Editions: $EDITIONS"
    [[ -n "$RELEASE" ]]  && log_info "Release: max xz compression"
    [[ -n "$SKIP_AUR" ]] && log_info "Skipping: AUR"

    local release_dir="$PROJECT_ROOT/release"
    mkdir -p "$release_dir"

    # Dated build cache: same-day rebuilds reuse packages, new day = fresh
    local build_date
    build_date=$(date +%Y-%m-%d)
    local cache_dir="$PROJECT_ROOT/.cache/build_${build_date}"
    mkdir -p "$cache_dir/pacman" "$cache_dir/offline-repo"

    # Prune old caches (keep last 3 days)
    if [[ -d "$PROJECT_ROOT/.cache" ]]; then
        find "$PROJECT_ROOT/.cache" -maxdepth 1 -name 'build_*' -type d \
            | sort | head -n -3 | xargs -r rm -rf
    fi

    local prebuilt_dir="$PROJECT_ROOT/build/prebuilt"

    # ── Build all apps first (single source of truth) ──
    # build-apps.sh builds Rust apps + st-wl in a container,
    # outputs to .cache/app-binaries/. Same script used by dev-push.sh.
    local app_bin_dir="$PROJECT_ROOT/.cache/app-binaries"
    log_info "Building apps via build-apps.sh..."
    "$SCRIPT_DIR/build-apps.sh" all

    local run_args=(
        --rm --privileged
        --network=host
        -v "$SCRIPT_DIR:/build/src:ro"
        -v "$release_dir:/build/release"
        -v "$cache_dir/offline-repo:/var/cache/smplos/mirror/offline"
        -v "$cache_dir/pacman:/var/cache/smplos/pacman-cache"
        -v "$app_bin_dir:/build/app-binaries:ro"
        -e "COMPOSITOR=$COMPOSITOR"
        -e "HOST_UID=$(id -u)"
        -e "HOST_GID=$(id -g)"
    )

    # Mount host pacman cache if on Arch-based system (huge speedup)
    if [[ -d /var/cache/pacman/pkg ]]; then
        log_info "Mounting host pacman cache (Arch detected)"
        run_args+=(-v "/var/cache/pacman/pkg:/var/cache/pacman/pkg:ro")
    fi

    # Mount prebuilt AUR packages
    if [[ -d "$prebuilt_dir" ]] && ls "$prebuilt_dir"/*.pkg.tar.* &>/dev/null 2>&1; then
        log_info "Mounting prebuilt AUR packages"
        run_args+=(-v "$prebuilt_dir:/build/prebuilt:ro")
    fi

    run_args+=(-e "BUILD_VERSION=${BUILD_VERSION:-0.1.0}")
    [[ -n "$EDITIONS" ]]       && run_args+=(-e "EDITIONS=$EDITIONS")
    [[ -n "$RELEASE" ]]       && run_args+=(-e "RELEASE=1")
    [[ -n "$NO_CACHE" ]]      && run_args+=(-e "NO_CACHE=1")
    [[ -n "$VERBOSE" ]]       && run_args+=(-e "VERBOSE=1")
    [[ -n "$SKIP_AUR" ]]      && run_args+=(-e "SKIP_AUR=1")
    [[ -n "$SKIP_FLATPAK" ]]  && run_args+=(-e "SKIP_FLATPAK=1")
    [[ -n "$SKIP_APPIMAGE" ]] && run_args+=(-e "SKIP_APPIMAGE=1")

    log_info "Pulling Arch Linux image..."
    $CTR pull archlinux:latest

    log_info "Build log: $BUILD_LOG"

    $CTR run "${run_args[@]}" archlinux:latest \
        /build/src/builder/build.sh 2>&1 | tee -a "$BUILD_LOG"

    local rc="${PIPESTATUS[0]}"
    if [[ "$rc" -ne 0 ]]; then
        die "ISO build failed (exit $rc, log: $BUILD_LOG)"
    fi

    echo ""
    log_info "Build complete! (log: $BUILD_LOG)"
    ls -lh "$release_dir"/*.iso 2>/dev/null || log_warn "No ISO found in output"
}

###############################################################################
# Main
###############################################################################

main() {
    echo -e "${BOLD}smplOS ISO Builder${NC}\n"

    parse_args "$@"
    check_prerequisites

    # Increment build version (patch segment) and export for the container
    local version_file="$SCRIPT_DIR/VERSION"
    if [[ -f "$version_file" ]]; then
        local current major minor patch
        current=$(cat "$version_file")
        major="${current%%.*}"; rest="${current#*.}"; minor="${rest%%.*}"; patch="${rest##*.}"
        patch=$((patch + 1))
        BUILD_VERSION="${major}.${minor}.${patch}"
        echo "$BUILD_VERSION" > "$version_file"
    else
        BUILD_VERSION="0.1.0"
        echo "$BUILD_VERSION" > "$version_file"
    fi
    export BUILD_VERSION
    log_info "Build version: v${BUILD_VERSION}"

    # Keep sudo alive in the background (build takes 15+ min, default sudo
    # timeout is ~5 min).  Killed automatically when this script exits.
    if [[ "$CTR" == sudo* ]]; then
        ( while true; do sudo -v; sleep 60; done ) &
        SUDO_KEEPALIVE_PID=$!
        trap 'kill $SUDO_KEEPALIVE_PID 2>/dev/null' EXIT
    fi

    if [[ -z "$SKIP_AUR" ]]; then
        build_missing_aur_packages
    fi

    run_build
}

main "$@"
