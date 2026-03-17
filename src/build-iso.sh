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
    --clean-apps            Wipe app build cache before compiling (full rebuild)
    --download-apps         Download app binaries from GitHub releases (default)
    --build-apps            Compile app binaries locally via build-apps.sh
    -h, --help              Show this help

Examples:
    ./build-iso.sh                        # Base build (downloads apps from GitHub)
    ./build-iso.sh -p                     # Productivity edition
    ./build-iso.sh --all                  # All editions
    ./build-iso.sh --all --skip-aur       # All editions, skip AUR
    ./build-iso.sh --release              # Max compression for release
    ./build-iso.sh --build-apps           # Compile apps locally instead of downloading
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
CLEAN_APPS=""
DOWNLOAD_APPS="1"   # Default: download pre-built binaries from GitHub releases

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
            --clean-apps)       CLEAN_APPS="1"; shift ;;
            --download-apps)    DOWNLOAD_APPS="1"; shift ;;
            --build-apps)       DOWNLOAD_APPS=""; shift ;;
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
# Build Custom Packages from local PKGBUILDs (src/shared/pkgbuilds/*)
###############################################################################

build_custom_packages() {
    local prebuilt_dir="$PROJECT_ROOT/build/prebuilt"
    local pkgbuild_dir="$SCRIPT_DIR/shared/pkgbuilds"
    mkdir -p "$prebuilt_dir"

    [[ -d "$pkgbuild_dir" ]] || return 0

    local need_build=()
    for dir in "$pkgbuild_dir"/*/; do
        [[ -f "$dir/PKGBUILD" ]] || continue
        local pkg
        pkg=$(basename "$dir")

        # Read the expected version from the PKGBUILD
        local pkgver pkgrel
        pkgver=$(grep -E '^pkgver=' "$dir/PKGBUILD" | head -1 | cut -d= -f2 | tr -d '"'"'"' ')
        pkgrel=$(grep -E '^pkgrel=' "$dir/PKGBUILD" | head -1 | cut -d= -f2 | tr -d '"'"'"' ')

        # If the PKGBUILD defines _gh_owner/_gh_repo, query GitHub for the
        # latest release so we always build the newest version automatically.
        local gh_owner gh_repo
        gh_owner=$(grep -E '^_gh_owner=' "$dir/PKGBUILD" | head -1 | cut -d= -f2 | tr -d '"'"'"' ')
        gh_repo=$(grep -E '^_gh_repo=' "$dir/PKGBUILD" | head -1 | cut -d= -f2 | tr -d '"'"'"' ')
        if [[ -n "$gh_owner" && -n "$gh_repo" ]]; then
            local latest
            latest=$(curl -fsSL "https://api.github.com/repos/${gh_owner}/${gh_repo}/releases/latest" \
                     2>/dev/null | grep -oP '"tag_name"\s*:\s*"\Kv?[^"]+' | sed 's/^v//' || true)
            if [[ -n "$latest" && "$latest" != "$pkgver" ]]; then
                log_info "GitHub has $pkg $latest (PKGBUILD says $pkgver) — will rebuild"
                pkgver="$latest"
            fi
        fi

        if [[ -n "$pkgver" && -n "$pkgrel" ]] && \
           ls "$prebuilt_dir"/${pkg}-${pkgver}-${pkgrel}-*.pkg.tar.* &>/dev/null 2>&1; then
            log_info "Found prebuilt custom package: $pkg ($pkgver-$pkgrel)"
        else
            # Evict any stale older version so it doesn't get injected into the ISO
            if ls "$prebuilt_dir"/${pkg}-[0-9]*-*-*.pkg.tar.* &>/dev/null 2>&1; then
                log_info "Evicting stale prebuilt for $pkg (want $pkgver-$pkgrel)"
                rm -f "$prebuilt_dir"/${pkg}-[0-9]*-*-*.pkg.tar.*
            fi
            need_build+=("$pkg")
        fi
    done

    [[ ${#need_build[@]} -eq 0 ]] && return 0

    log_step "Building custom packages: ${need_build[*]}"

    for pkg in "${need_build[@]}"; do
        log_info "Building $pkg..."
        $CTR run --rm \
            --network=host \
            -v "$pkgbuild_dir/$pkg:/build/pkg:ro" \
            -v "$prebuilt_dir:/output" \
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
                useradd -m builder
                echo 'builder ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers
                cp -r /build/pkg /home/builder/$pkg
                chown -R builder:builder /home/builder/$pkg
                cd /home/builder/$pkg
                sudo -u builder makepkg -s --noconfirm
                cp *.pkg.tar.* /output/
                echo \"==> $pkg done\"
            " || die "Failed to build custom package: $pkg"
    done

    log_info "Custom packages saved to: $prebuilt_dir"
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
        if ! ls "$prebuilt_dir"/${pkg}-[0-9]*-*-*.pkg.tar.* &>/dev/null; then
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
# Download Pre-built App Binaries from GitHub Releases (with local cache)
###############################################################################

# Resolution order for each app repo (smpl-apps, st-smpl, nemo):
#
#   1. Query GitHub API for the latest release tag.
#   2. If GitHub is reachable and the remote version is NEWER than the local
#      cache, download and update the cache.
#   3. If GitHub is unreachable or the cached version is already up-to-date,
#      use the cached binaries.
#   4. If nothing is cached either, fall back to build/prebuilt-apps/ where
#      the user can manually drop pre-built binaries (offline / air-gapped).
#
# Cache layout:
#   build/prebuilt-apps/           ← manual / user-provided fallback (checked into git or
#                                    populated by hand before offline builds)
#   build/prebuilt/                ← pacman packages (nemo-smpl .pkg.tar.zst)
#   .cache/app-binaries/           ← auto-managed download cache (gitignored)
#   .cache/app-binaries/.smpl-apps-version   ← e.g. "v0.1.1"
#   .cache/app-binaries/.st-smpl-version     ← e.g. "v1.0.0"
#   .cache/app-binaries/.nemo-smpl-version   ← e.g. "v1.4.2"

# Compare two semver tags (with optional leading 'v'). Returns 0 if $1 > $2.
_version_gt() {
    local a="${1#v}" b="${2#v}"
    [[ "$a" == "$b" ]] && return 1
    # Sort and check if a comes second (= greater)
    local highest
    highest=$(printf '%s\n%s\n' "$a" "$b" | sort -V | tail -1)
    [[ "$highest" == "$a" ]]
}

# Try to fetch JSON from GitHub API. Sets _gh_json and returns 0 on success.
_gh_api() {
    local url="$1"
    _gh_json=""
    _gh_json=$(curl -fsSL --connect-timeout 15 --max-time 30 "$url" 2>/dev/null) || return 1
    [[ -n "$_gh_json" ]]
}

download_prebuilt_apps() {
    local cache_dir="$PROJECT_ROOT/.cache/app-binaries"
    local fallback_dir="$PROJECT_ROOT/build/prebuilt-apps"
    mkdir -p "$cache_dir"

    log_step "Resolving pre-built app binaries"

    # ── smpl-apps ────────────────────────────────────────────────────────────
    local cached_apps_ver="" remote_apps_ver="" need_apps_download=false
    local apps_ver_file="$cache_dir/.smpl-apps-version"

    # Read cached version
    [[ -f "$apps_ver_file" ]] && cached_apps_ver=$(cat "$apps_ver_file")

    # Query GitHub
    if _gh_api "https://api.github.com/repos/smpl-os/smpl-apps/releases/latest"; then
        remote_apps_ver=$(echo "$_gh_json" | grep -oP '"tag_name"\s*:\s*"\K[^"]+' || true)

        if [[ -n "$remote_apps_ver" ]]; then
            if [[ -z "$cached_apps_ver" ]]; then
                log_info "smpl-apps: no local cache, will download $remote_apps_ver"
                need_apps_download=true
            elif _version_gt "$remote_apps_ver" "$cached_apps_ver"; then
                log_info "smpl-apps: newer release $remote_apps_ver (cached: $cached_apps_ver)"
                need_apps_download=true
            else
                log_info "smpl-apps: cache is up-to-date ($cached_apps_ver)"
            fi
        else
            log_warn "smpl-apps: could not parse remote tag"
        fi
    else
        log_warn "smpl-apps: GitHub unreachable, using cached/fallback binaries"
    fi

    if $need_apps_download; then
        local tarball_url
        tarball_url=$(echo "$_gh_json" \
            | grep -oP '"browser_download_url"\s*:\s*"\K[^"]*smpl-apps-[^"]*x86_64\.tar\.gz')
        if [[ -n "$tarball_url" ]]; then
            log_info "Downloading $tarball_url"
            if curl -fSL --connect-timeout 30 --retry 3 "$tarball_url" \
                | tar -xz -C "$cache_dir"; then
                echo "$remote_apps_ver" > "$apps_ver_file"
                log_info "smpl-apps $remote_apps_ver cached"
            else
                log_warn "smpl-apps: download failed, falling back to cache"
            fi
        else
            log_warn "smpl-apps: no tarball asset in release $remote_apps_ver"
        fi
    fi

    # Verify we have the apps (either from download or cache)
    local have_apps=false
    if [[ -f "$cache_dir/start-menu" ]]; then
        have_apps=true
    fi

    # Fallback: check user-provided directory
    if ! $have_apps && [[ -d "$fallback_dir" ]] && ls "$fallback_dir"/start-menu &>/dev/null 2>&1; then
        log_info "smpl-apps: using manually-provided binaries from build/prebuilt-apps/"
        cp -a "$fallback_dir"/start-menu "$fallback_dir"/notif-center \
              "$fallback_dir"/settings "$fallback_dir"/app-center \
              "$fallback_dir"/webapp-center "$fallback_dir"/sync-center-daemon \
              "$fallback_dir"/sync-center-gui "$cache_dir/" 2>/dev/null || true
        have_apps=true
    fi

    if ! $have_apps; then
        die "No smpl-apps binaries available (GitHub unreachable + no cache + no fallback).
Place binaries in build/prebuilt-apps/ or use --build-apps to compile locally."
    fi

    # ── st-smpl (optional) ───────────────────────────────────────────────────
    local cached_st_ver="" remote_st_ver="" need_st_download=false
    local st_ver_file="$cache_dir/.st-smpl-version"

    [[ -f "$st_ver_file" ]] && cached_st_ver=$(cat "$st_ver_file")

    if _gh_api "https://api.github.com/repos/smpl-os/st-smpl/releases/latest"; then
        remote_st_ver=$(echo "$_gh_json" | grep -oP '"tag_name"\s*:\s*"\K[^"]+' || true)

        if [[ -n "$remote_st_ver" ]]; then
            if [[ -z "$cached_st_ver" ]]; then
                need_st_download=true
            elif _version_gt "$remote_st_ver" "$cached_st_ver"; then
                log_info "st-smpl: newer release $remote_st_ver (cached: $cached_st_ver)"
                need_st_download=true
            else
                log_info "st-smpl: cache is up-to-date ($cached_st_ver)"
            fi
        fi
    else
        log_warn "st-smpl: GitHub unreachable"
    fi

    if $need_st_download; then
        local st_asset_url
        st_asset_url=$(echo "$_gh_json" \
            | grep -oP '"browser_download_url"\s*:\s*"\K[^"]*st[^"]*x86_64[^"]*' \
            | head -1 || true)
        if [[ -n "$st_asset_url" ]]; then
            log_info "Downloading st-smpl $remote_st_ver"
            if curl -fSL --connect-timeout 30 --retry 3 \
                "$st_asset_url" -o "$cache_dir/st-wl"; then
                chmod +x "$cache_dir/st-wl"
                echo "$remote_st_ver" > "$st_ver_file"
                log_info "st-smpl $remote_st_ver cached"
            else
                log_warn "st-smpl: download failed"
            fi
        fi
    fi

    # Fallback: user-provided st-wl
    if [[ ! -f "$cache_dir/st-wl" ]] && [[ -f "$fallback_dir/st-wl" ]]; then
        log_info "st-smpl: using manually-provided binary from build/prebuilt-apps/"
        cp -a "$fallback_dir/st-wl" "$cache_dir/st-wl"
    fi

    if [[ ! -f "$cache_dir/st-wl" ]]; then
        log_warn "st-smpl: no binary available (will use system terminal fallback)"
    fi

    # ── nemo-smpl pacman package ──────────────────────────────────────────
    # nemo-smpl is a pacman package (.pkg.tar.zst), not a standalone binary.
    # It goes into build/prebuilt/ alongside other AUR/custom packages so
    # build_custom_packages() can skip the container build when it exists.
    local prebuilt_dir="$PROJECT_ROOT/build/prebuilt"
    mkdir -p "$prebuilt_dir"
    local cached_nemo_ver="" remote_nemo_ver="" need_nemo_download=false
    local nemo_ver_file="$cache_dir/.nemo-smpl-version"

    [[ -f "$nemo_ver_file" ]] && cached_nemo_ver=$(cat "$nemo_ver_file")

    if _gh_api "https://api.github.com/repos/smpl-os/nemo-smpl/releases/latest"; then
        remote_nemo_ver=$(echo "$_gh_json" | grep -oP '"tag_name"\s*:\s*"\K[^"]+' || true)

        if [[ -n "$remote_nemo_ver" ]]; then
            if [[ -z "$cached_nemo_ver" ]]; then
                log_info "nemo-smpl: no local cache, will download $remote_nemo_ver"
                need_nemo_download=true
            elif _version_gt "$remote_nemo_ver" "$cached_nemo_ver"; then
                log_info "nemo-smpl: newer release $remote_nemo_ver (cached: $cached_nemo_ver)"
                need_nemo_download=true
            else
                log_info "nemo-smpl: cache is up-to-date ($cached_nemo_ver)"
            fi
        fi
    else
        log_warn "nemo-smpl: GitHub unreachable"
    fi

    if $need_nemo_download; then
        local nemo_pkg_url
        nemo_pkg_url=$(echo "$_gh_json" \
            | grep -oP '"browser_download_url"\s*:\s*"\K[^"]*nemo-smpl-[^"]*x86_64\.pkg\.tar\.zst' \
            | head -1 || true)
        if [[ -n "$nemo_pkg_url" ]]; then
            # Evict old versions before downloading
            rm -f "$prebuilt_dir"/nemo-smpl-[0-9]*-*-*.pkg.tar.*
            local nemo_pkg_name
            nemo_pkg_name=$(basename "$nemo_pkg_url")
            log_info "Downloading $nemo_pkg_url"
            if curl -fSL --connect-timeout 30 --retry 3 \
                "$nemo_pkg_url" -o "$prebuilt_dir/$nemo_pkg_name"; then
                echo "$remote_nemo_ver" > "$nemo_ver_file"
                log_info "nemo-smpl $remote_nemo_ver cached in $prebuilt_dir"
            else
                log_warn "nemo-smpl: download failed, falling back to existing prebuilt"
            fi
        else
            log_warn "nemo-smpl: no .pkg.tar.zst asset in release $remote_nemo_ver (rootfs only)"
            log_info "nemo-smpl: will be built from PKGBUILD by build_custom_packages()"
        fi
    fi

    # Fallback: user-provided nemo-smpl package
    if ! ls "$prebuilt_dir"/nemo-smpl-[0-9]*-*-*.pkg.tar.* &>/dev/null 2>&1; then
        if ls "$fallback_dir"/nemo-smpl-*.pkg.tar.* &>/dev/null 2>&1; then
            log_info "nemo-smpl: using manually-provided package from build/prebuilt-apps/"
            cp -a "$fallback_dir"/nemo-smpl-*.pkg.tar.* "$prebuilt_dir/"
        else
            log_info "nemo-smpl: no prebuilt package — build_custom_packages() will build it"
        fi
    fi

    # Make all binaries executable
    chmod +x "$cache_dir"/* 2>/dev/null || true

    log_info "App binaries ready in $cache_dir:"
    ls -lh "$cache_dir"
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
    # Use sudo because the container creates root-owned files inside these dirs
    if [[ -d "$PROJECT_ROOT/.cache" ]]; then
        find "$PROJECT_ROOT/.cache" -maxdepth 1 -name 'build_*' -type d \
            | sort | head -n -3 | xargs -r sudo rm -rf
    fi

    local prebuilt_dir="$PROJECT_ROOT/build/prebuilt"

    # Persistent whisper model cache — survives across builds and can be
    # pre-populated manually (place model files in build/dictation/base.en/).
    local dictation_dir="$PROJECT_ROOT/build/dictation"
    mkdir -p "$dictation_dir"

    # ── Get app binaries ─────────────────────────────────────────────────────
    # Default: download pre-built releases from GitHub (fast, no Rust toolchain needed).
    # Pass --build-apps to compile locally via build-apps.sh instead.
    local app_bin_dir="$PROJECT_ROOT/.cache/app-binaries"
    if [[ -n "$DOWNLOAD_APPS" ]]; then
        download_prebuilt_apps
    else
        log_info "Building apps locally via build-apps.sh..."
        local build_apps_args=(all)
        [[ -n "$CLEAN_APPS" ]] && build_apps_args=(--clean all)
        "$SCRIPT_DIR/build-apps.sh" "${build_apps_args[@]}"
    fi

    local run_args=(
        --rm --privileged
        --network=host
        -v "$SCRIPT_DIR:/build/src:ro"
        -v "$release_dir:/build/release"
        -v "$cache_dir/offline-repo:/var/cache/smplos/mirror/offline"
        -v "$cache_dir/pacman:/var/cache/smplos/pacman-cache"
        -v "$app_bin_dir:/build/app-binaries:ro"
        -v "$dictation_dir:/var/cache/smplos/models/whisper"
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
        build_custom_packages
        build_missing_aur_packages
    fi

    run_build
}

main "$@"
