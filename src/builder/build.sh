#!/bin/bash
#
# smplOS ISO Builder - Container Build Script
# Runs inside a privileged Podman/Docker container (archlinux:latest).
# Supports: Official repos, AUR (via prebuilt), Flatpak, AppImages
#
set -euo pipefail

###############################################################################
# Configuration
###############################################################################

BUILD_DIR="/build"
SRC_DIR="$BUILD_DIR/src"
RELEASE_DIR="$BUILD_DIR/release"
PREBUILT_DIR="$BUILD_DIR/prebuilt"
CACHE_DIR="/var/cache/smplos"
OFFLINE_MIRROR_DIR="$CACHE_DIR/mirror/offline"
WORK_DIR="$CACHE_DIR/work"
PROFILE_DIR="$CACHE_DIR/profile"

# From environment
COMPOSITOR="${COMPOSITOR:-hyprland}"
EDITIONS="${EDITIONS:-}"
VERBOSE="${VERBOSE:-}"
SKIP_AUR="${SKIP_AUR:-}"
SKIP_FLATPAK="${SKIP_FLATPAK:-}"
SKIP_APPIMAGE="${SKIP_APPIMAGE:-}"
RELEASE="${RELEASE:-}"
NO_CACHE="${NO_CACHE:-}"

# ISO metadata
ISO_NAME="smplos"
ISO_VERSION="$(date +%y%m%d-%H%M)"
ISO_LABEL="SMPLOS_$(date +%Y%m)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
log_step()  { echo -e "${BLUE}==>${NC} $*"; }
log_sub()   { echo -e "${CYAN}  ->${NC} $*"; }

# Package arrays
declare -a ALL_PACKAGES=()
declare -a AUR_PACKAGES=()
declare -a GPU_PACKAGES=()   # offline-repo-only: not installed into live squashfs
declare -a FLATPAK_PACKAGES=()
declare -a APPIMAGE_PACKAGES=()

###############################################################################
# Helpers
###############################################################################

# Retry a command up to 3 times with backoff
retry() {
    local n=0
    while true; do
        "$@" && return 0
        ((n++))
        [[ $n -ge 3 ]] && { log_error "Failed after 3 attempts: $*"; return 1; }
        log_warn "Retry $n/3: $*"
        sleep $((n * 5))
    done
}

# Read a package list file, skipping comments and blank lines
read_package_list() {
    local file="$1"
    local -n arr="$2"
    [[ -f "$file" ]] || return 0
    while IFS= read -r line; do
        line="${line%%#*}"   # strip inline comments
        line="${line%% *}"   # take first word only (package name)
        line="${line## }"    # trim leading spaces
        [[ -z "$line" ]] && continue
        arr+=("$line")
    done < "$file"
}

###############################################################################
# System Setup (runs in Docker container)
###############################################################################

setup_build_env() {
    log_step "Setting up build environment"

    # ── Network connectivity check ──────────────────────────────────────
    # Fail fast with actionable advice instead of hanging on DNS timeouts.
    log_step "Checking network connectivity"
    if curl -sf --max-time 10 --head https://archlinux.org > /dev/null 2>&1; then
        log_info "Network OK"
    elif curl -sf --max-time 10 --head http://archlinux.org > /dev/null 2>&1; then
        log_warn "HTTPS failed but HTTP works -- possible TLS/proxy issue"
    else
        log_error "No network connectivity from inside the build container."
        log_error ""
        log_error "Troubleshooting:"
        log_error "  1. Check your internet connection"
        log_error "  2. Check DNS: run 'host archlinux.org' on the host"
        log_error "  3. If using Podman, try: podman run --rm --network=host archlinux:latest curl -I https://archlinux.org"
        log_error "  4. If using Docker, try: docker run --rm archlinux:latest curl -I https://archlinux.org"
        log_error "  5. Firewall/VPN may be blocking container traffic"
        log_error "  6. Corporate proxy? Set HTTP_PROXY/HTTPS_PROXY env vars"
        die "Cannot proceed without network access"
    fi

    # ── Ensure pacman cache directory exists ────────────────────────────
    # The archlinux:latest container image may not have /var/cache/pacman/pkg/.
    # Without it, pacman warns: "couldn't find or create package cache".
    mkdir -p /var/cache/pacman/pkg

    # ── Bootstrap mirrorlist ────────────────────────────────────────────
    # Minimal reliable mirrors to bootstrap pacman + install reflector.
    cat > /etc/pacman.d/mirrorlist << 'MIRRORS'
Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch
Server = https://mirror.rackspace.com/archlinux/$repo/os/$arch
Server = https://mirrors.kernel.org/archlinux/$repo/os/$arch
MIRRORS
    
    # Enable multilib repo (needed for lib32-* Wine/audio packages)
    if ! grep -q '^\[multilib\]' /etc/pacman.conf; then
        echo -e '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist' >> /etc/pacman.conf
    fi

    # Disable pacman's 10-second download timeout.  Containers and CI runners
    # often have slow DNS; the default timeout is too aggressive and causes
    # "Resolving timed out" on perfectly reachable mirrors.
    if ! grep -q '^DisableDownloadTimeout' /etc/pacman.conf; then
        sed -i '/^\[options\]/a DisableDownloadTimeout' /etc/pacman.conf
    fi

    # Initialize pacman keyring and populate trust database
    pacman-key --init
    pacman-key --populate archlinux
    retry pacman --noconfirm -Sy --needed archlinux-keyring
    # Re-populate after update so newly-shipped keys are trusted
    pacman-key --populate archlinux

    # Install reflector first so we can find the fastest mirrors
    retry pacman --noconfirm -S reflector

    # ── Reflector: find 20 best mirrors ───────────────────────────────
    # --sort age  = most recently synced mirrors (metadata-only, no download
    #              speed tests, finishes in seconds).
    # --fastest N = download-tests candidates and is SLOW -- do NOT use it.
    # 30s timeout prevents reflector from hanging on flaky networks.
    # Falls back to the bootstrap mirrors on failure.
    log_step "Finding fastest mirrors with reflector"
    if timeout 30 reflector \
        --protocol https \
        --age 6 \
        --latest 20 \
        --sort age \
        --save /etc/pacman.d/mirrorlist 2>&1; then
        log_info "Reflector: $(grep -c '^Server' /etc/pacman.d/mirrorlist) mirrors selected"
    else
        log_warn "Reflector timed out or failed, continuing with bootstrap mirrors"
    fi

    # Re-sync databases with the optimized mirrorlist
    retry pacman --noconfirm -Sy
    
    # Install build dependencies (these go in the build container, not the ISO)
    retry pacman --noconfirm -S archiso git sudo base-devel jq
    
    # Create build user for any AUR packages we need to compile
    if ! id "builder" &>/dev/null; then
        useradd -m -G wheel builder
        echo "builder ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers
    fi
    
    log_info "Build environment ready"
}

###############################################################################
# Package Collection
###############################################################################

collect_packages() {
    log_step "Collecting package lists"
    
    local compositor_dir="$SRC_DIR/compositors/$COMPOSITOR"
    
    # Official packages (installed into live squashfs)
    read_package_list "$compositor_dir/packages.txt" ALL_PACKAGES
    read_package_list "$SRC_DIR/shared/packages.txt" ALL_PACKAGES

    # GPU packages (offline-repo-only: downloaded for post-install hw detection,
    # NOT added to packages.x86_64 — the live ISO is a TUI, needs no GPU driver)
    read_package_list "$SRC_DIR/shared/packages-gpu.txt" GPU_PACKAGES
    
    # Edition extra official packages (iterate all stacked editions)
    if [[ -n "${EDITIONS:-}" ]]; then
        IFS=',' read -ra _eds <<< "$EDITIONS"
        for _ed in "${_eds[@]}"; do
            read_package_list "$SRC_DIR/editions/$_ed/packages-extra.txt" ALL_PACKAGES
        done
    fi

    # AUR packages
    if [[ -z "$SKIP_AUR" ]]; then
        read_package_list "$compositor_dir/packages-aur.txt" AUR_PACKAGES
        read_package_list "$SRC_DIR/shared/packages-aur.txt" AUR_PACKAGES
        # Edition AUR extras (iterate all stacked editions)
        if [[ -n "${EDITIONS:-}" ]]; then
            IFS=',' read -ra _eds <<< "$EDITIONS"
            for _ed in "${_eds[@]}"; do
                read_package_list "$SRC_DIR/editions/$_ed/packages-aur-extra.txt" AUR_PACKAGES
            done
        fi
    fi
    
    # Flatpak packages
    if [[ -z "$SKIP_FLATPAK" ]]; then
        read_package_list "$compositor_dir/packages-flatpak.txt" FLATPAK_PACKAGES
        read_package_list "$SRC_DIR/shared/packages-flatpak.txt" FLATPAK_PACKAGES
    fi
    
    # AppImage packages
    if [[ -z "$SKIP_APPIMAGE" ]]; then
        read_package_list "$compositor_dir/packages-appimage.txt" APPIMAGE_PACKAGES
        read_package_list "$SRC_DIR/shared/packages-appimage.txt" APPIMAGE_PACKAGES
    fi
    
    # Remove duplicates
    ALL_PACKAGES=($(printf '%s\n' "${ALL_PACKAGES[@]}" | sort -u))
    [[ ${#AUR_PACKAGES[@]} -gt 0 ]] && AUR_PACKAGES=($(printf '%s\n' "${AUR_PACKAGES[@]}" | sort -u))
    
    log_info "Package counts:"
    log_info "  Official (live squashfs): ${#ALL_PACKAGES[@]}"
    log_info "  GPU (offline-repo-only):  ${#GPU_PACKAGES[@]}"
    log_info "  AUR: ${#AUR_PACKAGES[@]}"
    log_info "  Flatpak: ${#FLATPAK_PACKAGES[@]}"
    log_info "  AppImage: ${#APPIMAGE_PACKAGES[@]}"
}

###############################################################################
# Profile Setup - copy releng as base, then add our configs
###############################################################################

setup_profile() {
    log_step "Setting up archiso profile"
    
    # Create directories
    mkdir -p "$CACHE_DIR"
    mkdir -p "$OFFLINE_MIRROR_DIR"
    mkdir -p "$WORK_DIR"
    mkdir -p "$PROFILE_DIR"
    
    # We base our ISO on the official arch ISO (releng) config
    cp -r /usr/share/archiso/configs/releng/* "$PROFILE_DIR/"
    
    # Use linux-zen instead of the default linux kernel
    sed -i 's/^linux$/linux-zen/' "$PROFILE_DIR/packages.x86_64"
    
    # Remove reflector service (we'll use our offline mirror)
    rm -rf "$PROFILE_DIR/airootfs/etc/systemd/system/multi-user.target.wants/reflector.service" 2>/dev/null || true
    rm -rf "$PROFILE_DIR/airootfs/etc/systemd/system/reflector.service.d" 2>/dev/null || true
    rm -rf "$PROFILE_DIR/airootfs/etc/xdg/reflector" 2>/dev/null || true
    
    # Remove the default motd
    rm -f "$PROFILE_DIR/airootfs/etc/motd" 2>/dev/null || true
    
    log_info "Base releng profile copied"
}

###############################################################################
# Download All Packages to Offline Mirror
###############################################################################

download_packages() {
    log_step "Downloading packages to offline mirror"
    
    # If --no-cache was passed, wipe the offline mirror to force fresh downloads
    if [[ -n "$NO_CACHE" ]]; then
        log_warn "--no-cache: clearing offline mirror (full re-download)"
        rm -rf "$OFFLINE_MIRROR_DIR"/*
    fi
    
    # Get packages from the base releng packages.x86_64
    local releng_packages=()
    read_package_list "$PROFILE_DIR/packages.x86_64" releng_packages
    
    # Combine all packages: releng base + ours + GPU-only (offline repo only)
    local all_download_packages=("${releng_packages[@]}" "${ALL_PACKAGES[@]}" "${GPU_PACKAGES[@]}")
    
    # Remove duplicates
    all_download_packages=($(printf '%s\n' "${all_download_packages[@]}" | sort -u))
    
    # Count existing cached packages
    local cached_count=0
    cached_count=$(find "$OFFLINE_MIRROR_DIR" -name '*.pkg.tar.*' ! -name '*.sig' 2>/dev/null | wc -l)
    log_info "Cached packages: $cached_count, requested: ${#all_download_packages[@]}"
    
    # pacman -Syw skips packages already present in --cachedir,
    # so only new/updated packages are actually downloaded
    mkdir -p /tmp/offlinedb
    retry pacman --noconfirm -Sy --dbpath /tmp/offlinedb
    retry pacman --noconfirm -Syw "${all_download_packages[@]}" \
        --cachedir "$OFFLINE_MIRROR_DIR/" \
        --dbpath /tmp/offlinedb
    
    local new_count
    new_count=$(find "$OFFLINE_MIRROR_DIR" -name '*.pkg.tar.*' ! -name '*.sig' 2>/dev/null | wc -l)
    log_info "Packages after sync: $new_count (downloaded $((new_count - cached_count)) new)"
    
    # Clean stale package versions: if foo-1.0 and foo-1.1 both exist, remove foo-1.0
    # paccache keeps only the latest version per package (-rk1), matching our cachedir
    if command -v paccache &>/dev/null; then
        log_info "Cleaning stale package versions..."
        paccache -rk1 -c "$OFFLINE_MIRROR_DIR" 2>/dev/null || true
    fi
    
    # Remove .sig files from offline mirror.  With SigLevel = Optional TrustAll,
    # pacman skips verification when no .sig exists.  But if a .sig IS present,
    # pacman verifies it against the container's keyring — which may lack the
    # signing key, causing "corrupted package (PGP signature)" errors.
    # Deleting .sig files avoids this entirely.
    local sig_count
    sig_count=$(find "$OFFLINE_MIRROR_DIR" -name '*.sig' 2>/dev/null | wc -l)
    if [[ $sig_count -gt 0 ]]; then
        log_info "Removing $sig_count .sig files (not needed with TrustAll)..."
        find "$OFFLINE_MIRROR_DIR" -name '*.sig' -delete
    fi
    
    # Validate package integrity: remove any corrupted files now so they don't
    # cause checksum errors later during mkarchiso's pacstrap
    log_info "Validating package integrity..."
    local bad=0
    for pkg_file in "$OFFLINE_MIRROR_DIR"/*.pkg.tar.{zst,xz}; do
        [[ -f "$pkg_file" ]] || continue
        if ! bsdtar -tf "$pkg_file" &>/dev/null; then
            log_warn "Removing corrupted package: $(basename "$pkg_file")"
            rm -f "$pkg_file" "${pkg_file}.sig"
            ((bad++)) || true
        fi
    done
    if [[ $bad -gt 0 ]]; then
        log_warn "Removed $bad corrupted package(s), re-downloading..."
        retry pacman --noconfirm -Syw "${all_download_packages[@]}" \
            --cachedir "$OFFLINE_MIRROR_DIR/" \
            --dbpath /tmp/offlinedb
    fi
}

###############################################################################
# Prepare Flatpak Install List
###############################################################################

download_flatpaks() {
    if [[ -n "$SKIP_FLATPAK" || ${#FLATPAK_PACKAGES[@]} -eq 0 ]]; then
        return
    fi

    log_step "Preparing Flatpak install list"

    # Flatpak offline bundling inside a build container is fragile (needs
    # full runtime downloads, D-Bus, etc.).  Instead we embed a simple list
    # of app IDs.  smplos-flatpak-setup installs them from Flathub on first
    # login when internet is available.
    for app_id in "${FLATPAK_PACKAGES[@]}"; do
        log_info "Queued for first-boot install: $app_id"
    done

    log_info "${#FLATPAK_PACKAGES[@]} Flatpak(s) will install on first boot (requires internet)"
}

###############################################################################
# Download AppImages
###############################################################################

download_appimages() {
    if [[ -n "$SKIP_APPIMAGE" || ${#APPIMAGE_PACKAGES[@]} -eq 0 ]]; then
        return
    fi

    log_step "Downloading AppImages"

    local appimage_cache="$CACHE_DIR/appimages"
    mkdir -p "$appimage_cache"

    for entry in "${APPIMAGE_PACKAGES[@]}"; do
        local name="${entry%%|*}"
        local url="${entry##*|}"

        if [[ -z "$name" || -z "$url" || "$name" == "$url" ]]; then
            log_warn "Invalid AppImage entry (expected name|url): $entry"
            continue
        fi

        local dest="$appimage_cache/${name}.AppImage"
        if [[ -f "$dest" ]]; then
            log_info "Cached: $name"
        else
            log_info "Downloading: $name from $url"
            if retry curl -L -o "$dest" "$url" 2>&1 | tail -3; then
                chmod +x "$dest"
                log_info "Downloaded: $name ($(du -h "$dest" | cut -f1))"
            else
                log_warn "Failed to download AppImage: $name"
                rm -f "$dest"
            fi
        fi
    done

    log_info "AppImages ready"
}

###############################################################################
# Handle AUR Packages (use prebuilt or build)
###############################################################################

process_aur_packages() {
    log_step "Processing AUR packages"
    
    if [[ ${#AUR_PACKAGES[@]} -eq 0 ]]; then
        log_info "No AUR packages to process"
        return
    fi
    
    for pkg in "${AUR_PACKAGES[@]}"; do
        log_sub "Processing: $pkg"
        
        # Check for prebuilt package first
        local found=0
        if [[ -d "$PREBUILT_DIR" ]]; then
            shopt -s nullglob
            for prebuilt_file in "$PREBUILT_DIR"/${pkg}-[0-9]*.pkg.tar.{zst,xz}; do
                if [[ -f "$prebuilt_file" && ! "$prebuilt_file" == *"-debug-"* ]]; then
                    log_info "Using prebuilt: $(basename "$prebuilt_file")"
                    cp "$prebuilt_file" "$OFFLINE_MIRROR_DIR/"
                    found=1
                    break
                fi
            done
            shopt -u nullglob
        fi
        
        if [[ $found -eq 0 ]]; then
            log_warn "No prebuilt package found for $pkg"
            log_warn "Run the prebuilt script first to build AUR packages"
        fi
    done
    
    log_info "AUR packages processed"
    
    # AUR packages have dependencies on official repo packages (e.g. eww needs
    # gtk-layer-shell, logseq needs nodejs, vscode needs lsof).  Extract those
    # deps from the prebuilt .PKGINFO and download them to the offline mirror.
    log_info "Resolving AUR package dependencies..."
    local aur_deps=()
    for pkg in "${AUR_PACKAGES[@]}"; do
        shopt -s nullglob
        for pkg_file in "$OFFLINE_MIRROR_DIR"/${pkg}-[0-9]*.pkg.tar.{zst,xz}; do
            [[ -f "$pkg_file" ]] || continue
            while IFS=' = ' read -r key val; do
                [[ "$key" == "depend" ]] && aur_deps+=("${val%%[><=]*}")
            done < <(bsdtar -xOf "$pkg_file" .PKGINFO 2>/dev/null || true)
        done
        shopt -u nullglob
    done
    
    if [[ ${#aur_deps[@]} -gt 0 ]]; then
        # Deduplicate
        aur_deps=($(printf '%s\n' "${aur_deps[@]}" | sort -u))
        log_info "Downloading ${#aur_deps[@]} dependencies of AUR packages..."
        # Download deps (skips already-cached ones); ignore errors for
        # deps that are already satisfied by packages in the mirror
        pacman --noconfirm -Syw "${aur_deps[@]}" \
            --cachedir "$OFFLINE_MIRROR_DIR/" \
            --dbpath /tmp/offlinedb 2>&1 || true
        
        # Remove any .sig files from the new downloads
        find "$OFFLINE_MIRROR_DIR" -name '*.sig' -delete 2>/dev/null || true
    fi
}

###############################################################################
# Create Repository Database
###############################################################################

create_repo_database() {
    log_step "Creating offline repository database"
    
    cd "$OFFLINE_MIRROR_DIR"
    
    # Count packages
    local pkg_count=$(ls -1 *.pkg.tar.* 2>/dev/null | wc -l || echo 0)
    
    if [[ $pkg_count -eq 0 ]]; then
        log_error "No packages found in offline mirror!"
        exit 1
    fi
    
    # Create repo database (match .zst and .xz, exclude .sig files)
    log_info "Creating repository database with $pkg_count packages..."
    local pkg_files=()
    for f in "$OFFLINE_MIRROR_DIR/"*.pkg.tar.{zst,xz}; do
        [[ -f "$f" ]] && pkg_files+=("$f")
    done
    if [[ ${#pkg_files[@]} -eq 0 ]]; then
        log_error "No .pkg.tar.zst or .pkg.tar.xz files found!"
        exit 1
    fi
    repo-add --new "$OFFLINE_MIRROR_DIR/offline.db.tar.gz" "${pkg_files[@]}" || {
        log_error "Failed to create repo database"
        exit 1
    }
    
    log_info "Repository database created"
}

###############################################################################
# Create pacman.conf for the ISO
###############################################################################

setup_pacman_conf() {
    log_step "Setting up pacman configuration"
    
    # Create pacman.conf that uses our offline mirror.
    # ONLY the offline repo is listed here -- online repos are intentionally
    # excluded.  Including [core]/[extra]/[multilib] causes mkarchiso's
    # pacstrap to pull newer versions from the internet whose PGP signatures
    # may not match the container's keyring, leading to intermittent
    # "corrupted package (PGP signature)" failures.  All packages we need
    # are already downloaded into the offline mirror by download_packages().
    cat > "$PROFILE_DIR/pacman.conf" << 'PACMANCONF'
[options]
HoldPkg     = pacman glibc
Architecture = auto
ParallelDownloads = 5
SigLevel    = Optional TrustAll
LocalFileSigLevel = Optional
# CacheDir MUST be set to the offline mirror.  Without it, mkarchiso's
# _make_pacman_conf() falls back to the system CacheDir (the host's
# /var/cache/pacman/pkg mounted read-only).  Those host packages have PGP
# signatures that don't match the container's keyring, causing "corrupted
# package (PGP signature)" errors during pacstrap.
CacheDir    = /var/cache/smplos/mirror/offline/

[offline]
SigLevel = Optional TrustAll
Server = file:///var/cache/smplos/mirror/offline/
PACMANCONF

    # Create a symlink so mkarchiso can access the offline mirror
    mkdir -p /var/cache/smplos/mirror
    if [[ ! -L /var/cache/smplos/mirror/offline && "$OFFLINE_MIRROR_DIR" != "/var/cache/smplos/mirror/offline" ]]; then
        ln -sf "$OFFLINE_MIRROR_DIR" /var/cache/smplos/mirror/offline
    fi
    
    # The live ISO's pacman.conf uses ONLY the offline repo.  All packages are
    # pre-downloaded into /var/cache/smplos/mirror/offline/ with a repo-add'd
    # database.  No internet required for installation.
    # Post-install, install.sh restores a standard config with online mirrors.
    mkdir -p "$PROFILE_DIR/airootfs/etc"
    cat > "$PROFILE_DIR/airootfs/etc/pacman.conf" << 'LIVECONF'
[options]
HoldPkg     = pacman glibc
Architecture = auto
ParallelDownloads = 5
SigLevel    = Optional TrustAll
LocalFileSigLevel = Optional

[offline]
SigLevel = Optional TrustAll
Server = file:///var/cache/smplos/mirror/offline/
LIVECONF
    
    log_info "pacman.conf configured"
}

###############################################################################
# Update packages.x86_64
###############################################################################

update_package_list() {
    log_step "Updating package list"
    
    # Add our packages to the existing packages.x86_64
    printf '%s\n' "${ALL_PACKAGES[@]}" >> "$PROFILE_DIR/packages.x86_64"
    
    # Add AUR packages (they're in our offline repo now)
    if [[ ${#AUR_PACKAGES[@]} -gt 0 ]]; then
        printf '%s\n' "${AUR_PACKAGES[@]}" >> "$PROFILE_DIR/packages.x86_64"
    fi
    
    # Remove duplicates while preserving order
    local temp_file=$(mktemp)
    awk '!seen[$0]++' "$PROFILE_DIR/packages.x86_64" > "$temp_file"
    mv "$temp_file" "$PROFILE_DIR/packages.x86_64"
    
    log_info "Package list updated: $(wc -l < "$PROFILE_DIR/packages.x86_64") packages"
}

###############################################################################
# Update profiledef.sh
###############################################################################

update_profiledef() {
    log_step "Updating profile definition"
    
    cat > "$PROFILE_DIR/profiledef.sh" << PROFILEDEF
#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="$ISO_NAME"
iso_label="$ISO_LABEL"
iso_publisher="smplOS"
iso_application="smplOS Live/Installer"
iso_version="$ISO_VERSION"
install_dir="arch"
buildmodes=('iso')
bootmodes=('bios.syslinux'
           'uefi.systemd-boot')
arch="x86_64"
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
$(if [[ -n "$RELEASE" ]]; then
    echo "airootfs_image_tool_options=('-comp' 'xz' '-Xbcj' 'x86' '-Xdict-size' '1M' '-b' '1M')"
else
    echo "airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' '15' '-b' '1M')"
fi)
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/root"]="0:0:750"
  ["/root/.automated_script.sh"]="0:0:755"
  ["/usr/local/bin/"]="0:0:755"
  ["/var/cache/smplos/mirror/offline/"]="0:0:775"
)
PROFILEDEF
    chmod +x "$PROFILE_DIR/profiledef.sh"
    
    log_info "Profile definition updated"
}

###############################################################################
# Build st (suckless terminal) from source
###############################################################################

build_st() {
    log_step "Building st from source"

    local airootfs="$PROFILE_DIR/airootfs"
    local st_src="$SRC_DIR/compositors/$COMPOSITOR/st"

    if [[ ! -f "$st_src/Makefile" ]]; then
        log_info "No st source found for $COMPOSITOR, skipping"
        return 0
    fi

    local bin_name
    if [[ "$COMPOSITOR" == "hyprland" ]]; then
        bin_name="st-wl"
    else
        bin_name="st"
    fi

    # ── Source-hash cache: skip build if source hasn't changed ──
    local bin_cache="/var/cache/smplos/binaries"
    local src_hash
    src_hash=$(find "$st_src" -type f \( -name '*.c' -o -name '*.h' -o -name '*.def.h' -o -name 'Makefile' -o -name 'config.mk' \) \
        -exec sha256sum {} + 2>/dev/null | sort | sha256sum | cut -d' ' -f1)
    local cache_key="st-${COMPOSITOR}-${src_hash}"

    if [[ -f "$bin_cache/$cache_key" ]]; then
        log_info "st source unchanged, using cached binary ($cache_key)"
        install -Dm755 "$bin_cache/$cache_key" "$airootfs/usr/local/bin/$bin_name"
        install -Dm755 "$bin_cache/$cache_key" "$airootfs/root/smplos/bin/$bin_name"
        # Install terminfo from source (tiny, no compilation needed)
        if [[ -f "$st_src/${bin_name}.info" ]]; then
            tic -sx "$st_src/${bin_name}.info" -o "$airootfs/usr/share/terminfo" 2>/dev/null || true
        elif [[ -f "$st_src/st.info" ]]; then
            tic -sx "$st_src/st.info" -o "$airootfs/usr/share/terminfo" 2>/dev/null || true
        fi
        if [[ -f "$st_src/${bin_name}.desktop" ]]; then
            install -Dm644 "$st_src/${bin_name}.desktop" "$airootfs/usr/share/applications/${bin_name}.desktop"
        fi
        return 0
    fi

    # Install build dependencies on the build host
    local st_deps=()
    if [[ "$COMPOSITOR" == "hyprland" ]]; then
        st_deps=(wayland wayland-protocols libxkbcommon pixman fontconfig freetype2 harfbuzz pkg-config)
    else
        st_deps=(libx11 libxft libxrender libxcursor fontconfig freetype2 harfbuzz imlib2 gd pkg-config)
    fi
    pacman --noconfirm --needed -S "${st_deps[@]}" 2>/dev/null || true

    # Build in a temp dir to avoid polluting the source tree
    local build_dir="/tmp/st-build"
    rm -rf "$build_dir"
    cp -r "$st_src" "$build_dir"
    cd "$build_dir"

    log_info "Compiling st ($COMPOSITOR)..."
    # Always regenerate from .def.h (config.def.h is the source of truth)
    rm -f "$build_dir/config.h" "$build_dir/patches.h"
    make -j"$(nproc)"

    install -Dm755 "$bin_name" "$airootfs/usr/local/bin/$bin_name"
    # Only strip release builds; debug builds need symbols for crash analysis
    if ! grep -q 'STWL_DEBUG' "$build_dir/config.mk"; then
        strip "$airootfs/usr/local/bin/$bin_name"
    else
        log_info "Debug build detected, skipping strip"
    fi

    # Also stage for the installer to deploy to the installed system
    install -Dm755 "$bin_name" "$airootfs/root/smplos/bin/$bin_name"
    if ! grep -q 'STWL_DEBUG' "$build_dir/config.mk"; then
        strip "$airootfs/root/smplos/bin/$bin_name"
    fi

    # Save to cache for future builds
    mkdir -p "$bin_cache"
    cp "$airootfs/usr/local/bin/$bin_name" "$bin_cache/$cache_key"
    log_info "Cached st binary as $cache_key"

    # Install terminfo
    if [[ -f "$build_dir/${bin_name}.info" ]]; then
        tic -sx "$build_dir/${bin_name}.info" -o "$airootfs/usr/share/terminfo" 2>/dev/null || true
    elif [[ -f "$build_dir/st.info" ]]; then
        tic -sx "$build_dir/st.info" -o "$airootfs/usr/share/terminfo" 2>/dev/null || true
    fi

    # Install desktop file for xdg-terminal-exec
    if [[ -f "$st_src/${bin_name}.desktop" ]]; then
        install -Dm644 "$st_src/${bin_name}.desktop" "$airootfs/usr/share/applications/${bin_name}.desktop"
    fi

    cd "$SRC_DIR"
    rm -rf "$build_dir"

    log_info "st built and installed successfully"
}

###############################################################################
# Build notif-center (Rust+Slint notification center) from source
###############################################################################

build_notif_center() {
    log_step "Building notif-center from source"

    local airootfs="$PROFILE_DIR/airootfs"
    local nc_src="$SRC_DIR/shared/notif-center"

    if [[ ! -f "$nc_src/Cargo.toml" ]]; then
        log_warn "notif-center source not found at $nc_src, skipping"
        return
    fi

    # ── Source-hash cache: skip build if source hasn't changed ──
    local bin_cache="/var/cache/smplos/binaries"
    local src_hash
    src_hash=$({ find "$nc_src/src" "$nc_src/ui" -type f -exec sha256sum {} + 2>/dev/null; \
        sha256sum "$nc_src/Cargo.toml" "$nc_src/Cargo.lock" "$nc_src/build.rs" 2>/dev/null; \
    } | sort | sha256sum | cut -d' ' -f1)
    local cache_key="notif-center-${src_hash}"

    if [[ -f "$bin_cache/$cache_key" ]]; then
        log_info "notif-center source unchanged, using cached binary ($cache_key)"
        install -Dm755 "$bin_cache/$cache_key" "$airootfs/usr/local/bin/notif-center"
        install -Dm755 "$bin_cache/$cache_key" "$airootfs/root/smplos/bin/notif-center"
        return 0
    fi

    # Install Rust toolchain and build deps
    pacman --noconfirm --needed -S rust cargo cmake pkgconf fontconfig freetype2 \
        libxkbcommon wayland libglvnd mesa 2>/dev/null || true

    # Build in a temp dir to avoid polluting the source tree
    local build_dir="/tmp/notif-center-build"
    rm -rf "$build_dir"
    cp -r "$nc_src" "$build_dir"
    cd "$build_dir"

    log_info "Compiling notif-center (release)..."
    cargo build --release

    local bin_path="$build_dir/target/release/notif-center"
    if [[ ! -x "$bin_path" ]]; then
        log_warn "notif-center binary not found after build, skipping"
        cd "$SRC_DIR"
        rm -rf "$build_dir"
        return
    fi

    # Install binary into the ISO
    install -Dm755 "$bin_path" "$airootfs/usr/local/bin/notif-center"
    strip "$airootfs/usr/local/bin/notif-center"

    # Also stage for the installer to deploy to the installed system
    install -Dm755 "$bin_path" "$airootfs/root/smplos/bin/notif-center"
    strip "$airootfs/root/smplos/bin/notif-center"

    # Save to cache for future builds
    mkdir -p "$bin_cache"
    cp "$airootfs/usr/local/bin/notif-center" "$bin_cache/$cache_key"
    log_info "Cached notif-center binary as $cache_key"

    cd "$SRC_DIR"
    rm -rf "$build_dir"

    log_info "notif-center built and installed successfully"
}

###############################################################################
# Build kb-center (Rust+Slint keyboard layout manager) from source
###############################################################################

build_kb_center() {
    log_step "Building kb-center from source"

    local airootfs="$PROFILE_DIR/airootfs"
    local kc_src="$SRC_DIR/shared/kb-center"

    if [[ ! -f "$kc_src/Cargo.toml" ]]; then
        log_warn "kb-center source not found at $kc_src, skipping"
        return
    fi

    # ── Source-hash cache: skip build if source hasn't changed ──
    local bin_cache="/var/cache/smplos/binaries"
    local src_hash
    src_hash=$({ find "$kc_src/src" "$kc_src/ui" -type f -exec sha256sum {} + 2>/dev/null; \
        sha256sum "$kc_src/Cargo.toml" "$kc_src/Cargo.lock" "$kc_src/build.rs" 2>/dev/null; \
    } | sort | sha256sum | cut -d' ' -f1)
    local cache_key="kb-center-${src_hash}"

    if [[ -f "$bin_cache/$cache_key" ]]; then
        log_info "kb-center source unchanged, using cached binary ($cache_key)"
        install -Dm755 "$bin_cache/$cache_key" "$airootfs/usr/local/bin/kb-center"
        install -Dm755 "$bin_cache/$cache_key" "$airootfs/root/smplos/bin/kb-center"
        return 0
    fi

    # Install Rust toolchain and build deps (likely already installed by notif-center)
    pacman --noconfirm --needed -S rust cargo cmake pkgconf fontconfig freetype2 \
        libxkbcommon wayland libglvnd mesa 2>/dev/null || true

    # Build in a temp dir to avoid polluting the source tree
    local build_dir="/tmp/kb-center-build"
    rm -rf "$build_dir"
    cp -r "$kc_src" "$build_dir"
    cd "$build_dir"

    log_info "Compiling kb-center (release)..."
    cargo build --release

    local bin_path="$build_dir/target/release/kb-center"
    if [[ ! -x "$bin_path" ]]; then
        log_warn "kb-center binary not found after build, skipping"
        cd "$SRC_DIR"
        rm -rf "$build_dir"
        return
    fi

    # Install binary into the ISO
    install -Dm755 "$bin_path" "$airootfs/usr/local/bin/kb-center"
    strip "$airootfs/usr/local/bin/kb-center"

    # Also stage for the installer to deploy to the installed system
    install -Dm755 "$bin_path" "$airootfs/root/smplos/bin/kb-center"
    strip "$airootfs/root/smplos/bin/kb-center"

    # Save to cache for future builds
    mkdir -p "$bin_cache"
    cp "$airootfs/usr/local/bin/kb-center" "$bin_cache/$cache_key"
    log_info "Cached kb-center binary as $cache_key"

    cd "$SRC_DIR"
    rm -rf "$build_dir"

    log_info "kb-center built and installed successfully"
}

###############################################################################
# Build disp-center (Rust+Slint display manager) from source
###############################################################################

build_disp_center() {
    log_step "Building disp-center from source"

    local airootfs="$PROFILE_DIR/airootfs"
    local dc_src="$SRC_DIR/shared/disp-center"

    if [[ ! -f "$dc_src/Cargo.toml" ]]; then
        log_warn "disp-center source not found at $dc_src, skipping"
        return
    fi

    # ── Source-hash cache: skip build if source hasn't changed ──
    local bin_cache="/var/cache/smplos/binaries"
    local src_hash
    src_hash=$({ find "$dc_src/src" "$dc_src/ui" -type f -exec sha256sum {} + 2>/dev/null; \
        sha256sum "$dc_src/Cargo.toml" "$dc_src/Cargo.lock" "$dc_src/build.rs" 2>/dev/null; \
    } | sort | sha256sum | cut -d' ' -f1)
    local cache_key="disp-center-${src_hash}"

    if [[ -f "$bin_cache/$cache_key" ]]; then
        log_info "disp-center source unchanged, using cached binary ($cache_key)"
        install -Dm755 "$bin_cache/$cache_key" "$airootfs/usr/local/bin/disp-center"
        install -Dm755 "$bin_cache/$cache_key" "$airootfs/root/smplos/bin/disp-center"
        return 0
    fi

    # Install Rust toolchain and build deps (likely already installed by notif-center)
    pacman --noconfirm --needed -S rust cargo cmake pkgconf fontconfig freetype2 \
        libxkbcommon wayland libglvnd mesa 2>/dev/null || true

    # Build in a temp dir to avoid polluting the source tree
    local build_dir="/tmp/disp-center-build"
    rm -rf "$build_dir"
    cp -r "$dc_src" "$build_dir"
    cd "$build_dir"

    log_info "Compiling disp-center (release)..."
    cargo build --release

    local bin_path="$build_dir/target/release/disp-center"
    if [[ ! -x "$bin_path" ]]; then
        log_warn "disp-center binary not found after build, skipping"
        cd "$SRC_DIR"
        rm -rf "$build_dir"
        return
    fi

    # Install binary into the ISO
    install -Dm755 "$bin_path" "$airootfs/usr/local/bin/disp-center"
    strip "$airootfs/usr/local/bin/disp-center"

    # Also stage for the installer to deploy to the installed system
    install -Dm755 "$bin_path" "$airootfs/root/smplos/bin/disp-center"
    strip "$airootfs/root/smplos/bin/disp-center"

    # Save to cache for future builds
    mkdir -p "$bin_cache"
    cp "$airootfs/usr/local/bin/disp-center" "$bin_cache/$cache_key"
    log_info "Cached disp-center binary as $cache_key"

    cd "$SRC_DIR"
    rm -rf "$build_dir"

    log_info "disp-center built and installed successfully"
}

build_app_center() {
    log_step "Building app-center from source"

    local airootfs="$PROFILE_DIR/airootfs"
    local ac_src="$SRC_DIR/shared/app-center"

    if [[ ! -f "$ac_src/Cargo.toml" ]]; then
        log_warn "app-center source not found at $ac_src, skipping"
        return
    fi

    # ── Source-hash cache: skip build if source hasn't changed ──
    local bin_cache="/var/cache/smplos/binaries"
    local src_hash
    src_hash=$({ find "$ac_src/src" "$ac_src/ui" -type f -exec sha256sum {} + 2>/dev/null; \
        sha256sum "$ac_src/Cargo.toml" "$ac_src/Cargo.lock" "$ac_src/build.rs" 2>/dev/null; \
    } | sort | sha256sum | cut -d' ' -f1)
    local cache_key="app-center-${src_hash}"

    if [[ -f "$bin_cache/$cache_key" ]]; then
        log_info "app-center source unchanged, using cached binary ($cache_key)"
        install -Dm755 "$bin_cache/$cache_key" "$airootfs/usr/local/bin/app-center"
        install -Dm755 "$bin_cache/$cache_key" "$airootfs/root/smplos/bin/app-center"
        return 0
    fi

    # Install Rust toolchain and build deps (likely already installed by other builds)
    pacman --noconfirm --needed -S rust cargo cmake pkgconf fontconfig freetype2 \
        libxkbcommon wayland libglvnd mesa openssl 2>/dev/null || true

    # Build in a temp dir to avoid polluting the source tree
    local build_dir="/tmp/app-center-build"
    rm -rf "$build_dir"
    cp -r "$ac_src" "$build_dir"
    cd "$build_dir"

    log_info "Compiling app-center (release)..."
    cargo build --release

    local bin_path="$build_dir/target/release/app-center"
    if [[ ! -x "$bin_path" ]]; then
        log_warn "app-center binary not found after build, skipping"
        cd "$SRC_DIR"
        rm -rf "$build_dir"
        return
    fi

    # Install binary into the ISO
    install -Dm755 "$bin_path" "$airootfs/usr/local/bin/app-center"
    strip "$airootfs/usr/local/bin/app-center"

    # Also stage for the installer to deploy to the installed system
    install -Dm755 "$bin_path" "$airootfs/root/smplos/bin/app-center"
    strip "$airootfs/root/smplos/bin/app-center"

    # Save to cache for future builds
    mkdir -p "$bin_cache"
    cp "$airootfs/usr/local/bin/app-center" "$bin_cache/$cache_key"
    log_info "Cached app-center binary as $cache_key"

    cd "$SRC_DIR"
    rm -rf "$build_dir"

    log_info "app-center built and installed successfully"
}

###############################################################################
# Configure Airootfs
###############################################################################

setup_airootfs() {
    log_step "Configuring airootfs"
    
    local airootfs="$PROFILE_DIR/airootfs"
    local skel="$airootfs/etc/skel"
    
    # Create directories
    mkdir -p "$skel/.config"
    mkdir -p "$airootfs/usr/local/bin"

    # 1. Populate /etc/skel from src/shared/skel (dotfiles)
    if [[ -d "$SRC_DIR/shared/skel" ]]; then
       log_info "Populating /etc/skel from src/shared/skel..."
       cp -r "$SRC_DIR/shared/skel/"* "$skel/" 2>/dev/null || true
    fi

    # 2. Populate /etc/skel/.config from src/shared/configs
    if [[ -d "$SRC_DIR/shared/configs" ]]; then
        log_info "Populating /etc/skel/.config from src/shared/configs..."
        cp -r "$SRC_DIR/shared/configs/"* "$skel/.config/" 2>/dev/null || true
    fi

    mkdir -p "$airootfs/root/smplos/install/helpers"
    mkdir -p "$airootfs/root/smplos/config"
    mkdir -p "$airootfs/root/smplos/branding/plymouth"
    mkdir -p "$airootfs/opt/appimages"
    mkdir -p "$airootfs/opt/flatpaks"
    mkdir -p "$airootfs/var/cache/smplos/mirror"

    # Copy cached AppImages into airootfs
    local appimage_cache="$CACHE_DIR/appimages"
    if [[ -d "$appimage_cache" ]] && ls "$appimage_cache"/*.AppImage &>/dev/null; then
        log_info "Copying AppImages into ISO..."
        cp "$appimage_cache"/*.AppImage "$airootfs/opt/appimages/"
        chmod +x "$airootfs/opt/appimages/"*.AppImage
        local ai_count
        ai_count=$(ls -1 "$airootfs/opt/appimages/"*.AppImage 2>/dev/null | wc -l)
        log_info "Bundled $ai_count AppImage(s)"
    fi

    # Copy Flatpak online-install list (offline bundles are complex;
    # for now we install from Flathub on first boot when internet is available)
    local flatpak_cache="$CACHE_DIR/flatpaks"
    if [[ -f "$flatpak_cache/install-online.txt" ]]; then
        cp "$flatpak_cache/install-online.txt" "$airootfs/opt/flatpaks/install-online.txt"
    fi
    # Write the flatpak list directly from our package array
    if [[ ${#FLATPAK_PACKAGES[@]} -gt 0 ]]; then
        printf '%s\n' "${FLATPAK_PACKAGES[@]}" > "$airootfs/opt/flatpaks/install-online.txt"
        log_info "Flatpak install list: ${#FLATPAK_PACKAGES[@]} app(s)"
    fi
    
    # Copy offline mirror into airootfs
    # Uses --reflink=auto for CoW on supported filesystems (avoids real duplication)
    # Can't use symlinks — mkarchiso rejects paths outside airootfs
    log_info "Copying offline repository into airootfs..."
    cp -r --reflink=auto "$OFFLINE_MIRROR_DIR" "$airootfs/var/cache/smplos/mirror/offline"
    
    # Copy shared bin scripts
    if [[ -d "$SRC_DIR/shared/bin" ]]; then
        log_info "Copying shared scripts"
        cp -r "$SRC_DIR/shared/bin/"* "$airootfs/usr/local/bin/" 2>/dev/null || true
        chmod +x "$airootfs/usr/local/bin/"* 2>/dev/null || true
        
        # Also stage scripts for the installer to deploy to the installed system
        mkdir -p "$airootfs/root/smplos/bin"
        cp -r "$SRC_DIR/shared/bin/"* "$airootfs/root/smplos/bin/" 2>/dev/null || true
        chmod +x "$airootfs/root/smplos/bin/"* 2>/dev/null || true
    fi
    
    # Deploy shared web app .desktop files and icons (available in all editions)
    if [[ -d "$SRC_DIR/shared/applications" ]]; then
        log_info "Deploying shared web app entries"
        mkdir -p "$skel/.local/share/applications"
        cp "$SRC_DIR/shared/applications/"*.desktop "$skel/.local/share/applications/" 2>/dev/null || true
        mkdir -p "$airootfs/root/smplos/applications"
        cp "$SRC_DIR/shared/applications/"*.desktop "$airootfs/root/smplos/applications/" 2>/dev/null || true
        if [[ -d "$SRC_DIR/shared/applications/icons/hicolor" ]]; then
            mkdir -p "$airootfs/usr/share/icons"
            cp -r "$SRC_DIR/shared/applications/icons/hicolor" "$airootfs/usr/share/icons/"
            mkdir -p "$airootfs/root/smplos/icons/hicolor"
            cp -r "$SRC_DIR/shared/applications/icons/hicolor/"* "$airootfs/root/smplos/icons/hicolor/"
        fi
    fi
    
    # Deploy custom os-release (so fastfetch shows "smplOS" not "Arch Linux")
    if [[ -f "$SRC_DIR/shared/system/os-release" ]]; then
        log_info "Deploying custom os-release"
        mkdir -p "$airootfs/etc"
        cp "$SRC_DIR/shared/system/os-release" "$airootfs/etc/os-release"
        # Also stage for installer to deploy to installed system
        mkdir -p "$airootfs/root/smplos/system"
        cp "$SRC_DIR/shared/system/os-release" "$airootfs/root/smplos/system/os-release"
    fi
    
    # Copy EWW configs
    if [[ -d "$SRC_DIR/shared/eww" ]]; then
        log_info "Copying EWW configuration"
        mkdir -p "$skel/.config/eww"
        cp -r "$SRC_DIR/shared/eww/"* "$skel/.config/eww/" 2>/dev/null || true
        # Ensure EWW listener scripts are executable (archiso skel copy may strip +x)
        find "$skel/.config/eww/scripts" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
        # Also copy to smplos install path so install.sh deploys it to the installed system
        mkdir -p "$airootfs/root/smplos/config/eww"
        cp -r "$SRC_DIR/shared/eww/"* "$airootfs/root/smplos/config/eww/" 2>/dev/null || true
        find "$airootfs/root/smplos/config/eww/scripts" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
    fi

    # Copy shared icons (SVG status icons for EWW bar)
    if [[ -d "$SRC_DIR/shared/icons" ]]; then
        log_info "Copying shared icons"
        mkdir -p "$skel/.config/eww/icons"
        cp -r "$SRC_DIR/shared/icons/"* "$skel/.config/eww/icons/" 2>/dev/null || true
        # Also to smplos install path (for install.sh → ~/.config/eww/icons/)
        mkdir -p "$airootfs/root/smplos/config/eww/icons"
        cp -r "$SRC_DIR/shared/icons/"* "$airootfs/root/smplos/config/eww/icons/" 2>/dev/null || true
        # SVG templates for theme-set to bake on theme switch
        # theme-set reads from ~/.local/share/smplos/icons/status/
        mkdir -p "$airootfs/root/smplos/icons"
        cp -r "$SRC_DIR/shared/icons/"* "$airootfs/root/smplos/icons/" 2>/dev/null || true
    fi

    # Deploy default wallpaper (catppuccin theme)
    if [[ -d "$SRC_DIR/shared/themes/catppuccin/backgrounds" ]]; then
        log_info "Deploying default wallpaper"
        local default_bg=$(find "$SRC_DIR/shared/themes/catppuccin/backgrounds" -maxdepth 1 -type f \( -name '*.jpg' -o -name '*.png' \) | sort | head -1)
        if [[ -n "$default_bg" ]]; then
            local ext="${default_bg##*.}"
            # To skel (for live ISO session)
            mkdir -p "$skel/Pictures/Wallpapers"
            cp "$default_bg" "$skel/Pictures/Wallpapers/default.$ext"
            # To smplos install path (for installed system via install.sh)
            mkdir -p "$airootfs/root/smplos/wallpapers"
            cp "$default_bg" "$airootfs/root/smplos/wallpapers/default.$ext"
        fi
    fi

    # Deploy theme system
    if [[ -d "$SRC_DIR/shared/themes" ]]; then
        log_info "Deploying theme system"
        
        # Stock themes — each is self-contained with pre-baked configs
        # Skip _templates (dev-only, not needed at runtime)
        local smplos_data="$airootfs/root/smplos"
        mkdir -p "$smplos_data/themes"
        for theme_dir in "$SRC_DIR/shared/themes"/*/; do
            [[ "$(basename "$theme_dir")" == _* ]] && continue
            cp -r "$theme_dir" "$smplos_data/themes/"
        done
        
        # Also to skel for live session
        local smplos_skel_data="$skel/.local/share/smplos"
        mkdir -p "$smplos_skel_data/themes"
        cp -r "$smplos_data/themes/"* "$smplos_skel_data/themes/"

        # Deploy DC highlighters bundle (stock syntax colors for theme-set-dc)
        if [[ -f "$SRC_DIR/shared/configs/smplos/dc-highlighters.json" ]]; then
            log_info "Deploying DC highlighters bundle"
            cp "$SRC_DIR/shared/configs/smplos/dc-highlighters.json" "$smplos_data/dc-highlighters.json"
            cp "$SRC_DIR/shared/configs/smplos/dc-highlighters.json" "$smplos_skel_data/dc-highlighters.json"
        fi
        
        # Pre-set catppuccin as the active theme for live session
        # Each theme ships all its configs pre-baked, just copy the whole dir
        mkdir -p "$skel/.config/smplos/current/theme"
        echo "catppuccin" > "$skel/.config/smplos/current/theme.name"
        cp -r "$SRC_DIR/shared/themes/catppuccin/"* "$skel/.config/smplos/current/theme/"
        
        # Link pre-baked configs into app config dirs for live session
        local theme_src="$SRC_DIR/shared/themes/catppuccin"
        cp "$theme_src/eww-colors.scss" "$skel/.config/eww/theme-colors.scss" 2>/dev/null || true
        # Bake SVG icon templates with catppuccin colors for live session
        if [[ -d "$SRC_DIR/shared/icons/status" ]]; then
            # Install templates to smplos data dir
            mkdir -p "$skel/.local/share/smplos/icons/status"
            cp "$SRC_DIR/shared/icons/status/"*.svg "$skel/.local/share/smplos/icons/status/"
            # Bake for the default theme
            local _accent _fg_dim _fg _bg
            _accent=$(grep '^accent' "$theme_src/colors.toml" | head -1 | sed 's/.*"\(#[^"]*\)".*/\1/')
            _fg_dim=$(grep '^color15\|^foreground' "$theme_src/colors.toml" | head -1 | sed 's/.*"\(#[^"]*\)".*/\1/')
            _fg=$(grep '^foreground' "$theme_src/colors.toml" | head -1 | sed 's/.*"\(#[^"]*\)".*/\1/')
            _bg=$(grep '^background' "$theme_src/colors.toml" | head -1 | sed 's/.*"\(#[^"]*\)".*/\1/')
            _accent=${_accent:-#89b4fa}; _fg_dim=${_fg_dim:-#a6adc8}
            _fg=${_fg:-#cdd6f4}; _bg=${_bg:-#1e1e2e}
            mkdir -p "$skel/.config/eww/icons/status"
            for svg in "$skel/.local/share/smplos/icons/status/"*.svg; do
                sed "s/{{accent}}/$_accent/g; s/{{fg-dim}}/$_fg_dim/g; s/{{fg}}/$_fg/g; s/{{bg}}/$_bg/g" "$svg" \
                    > "$skel/.config/eww/icons/status/$(basename "$svg")"
            done
        fi
        mkdir -p "$skel/.config/hypr" && cp "$theme_src/hyprland.conf" "$skel/.config/hypr/theme.conf" 2>/dev/null || true
        cp "$theme_src/hyprlock.conf" "$skel/.config/hypr/hyprlock-theme.conf" 2>/dev/null || true
        mkdir -p "$skel/.config/foot" && cp "$theme_src/foot.ini" "$skel/.config/foot/theme.ini" 2>/dev/null || true
        # Rofi theme (single file used by launcher + all dialogs)
        mkdir -p "$skel/.config/rofi"
        cp "$theme_src/smplos-launcher.rasi" "$skel/.config/rofi/smplos-launcher.rasi" 2>/dev/null || true
        # st -- no config file to copy, colors applied at runtime via OSC escape sequences
        mkdir -p "$skel/.config/btop/themes" && cp "$theme_src/btop.theme" "$skel/.config/btop/themes/current.theme" 2>/dev/null || true
        # Fish shell theme colors
        mkdir -p "$skel/.config/fish" && cp "$theme_src/fish.theme" "$skel/.config/fish/theme.fish" 2>/dev/null || true
        # Double Commander -- pre-generate colors.json with catppuccin palette
        if [[ -f "$airootfs/usr/local/bin/theme-set-dc" ]]; then
            log_info "Pre-generating DC colors.json for catppuccin"
            SMPLOS_BUILD=1 \
            CURRENT_THEME_PATH="$skel/.config/smplos/current/theme" \
            DC_CONFIG_DIR="$skel/.config/doublecmd" \
            SMPLOS_PATH="$smplos_skel_data" \
              bash "$airootfs/usr/local/bin/theme-set-dc" 2>/dev/null || true
        fi
        # Browser (Brave/Chromium) -- set toolbar color via managed policy
        local browser_bg
        browser_bg=$(grep '^background' "$theme_src/colors.toml" | sed 's/.*"\(#[0-9a-fA-F]*\)".*/\1/')
        if [[ -n "$browser_bg" ]]; then
            local policy="{\"BrowserThemeColor\": \"$browser_bg\", \"BackgroundModeEnabled\": false}"
            mkdir -p "$airootfs/etc/brave/policies/managed"
            echo "$policy" > "$airootfs/etc/brave/policies/managed/color.json"
            mkdir -p "$airootfs/etc/chromium/policies/managed"
            echo "$policy" > "$airootfs/etc/chromium/policies/managed/color.json"
        fi
        # Dunst: concatenate core settings + theme colors
        local dunst_core="$SRC_DIR/shared/configs/dunst/dunstrc"
        if [[ -f "$SRC_DIR/compositors/$COMPOSITOR/configs/dunst/dunstrc" ]]; then
            dunst_core="$SRC_DIR/compositors/$COMPOSITOR/configs/dunst/dunstrc"
        fi
        if [[ -f "$dunst_core" ]]; then
            mkdir -p "$skel/.config/dunst"
            cat "$dunst_core" "$theme_src/dunstrc.theme" > "$skel/.config/dunst/dunstrc.active"
        fi
    fi
    
    # Copy compositor configurations
    local compositor_dir="$SRC_DIR/compositors/$COMPOSITOR"
    if [[ -d "$compositor_dir" ]]; then
        if [[ -d "$compositor_dir/hypr" ]]; then
            log_info "Copying Hyprland configuration"
            mkdir -p "$skel/.config/hypr"
            cp -r "$compositor_dir/hypr/"* "$skel/.config/hypr/"
        fi
        
        if [[ -d "$compositor_dir/configs" ]]; then
            cp -r "$compositor_dir/configs/"* "$skel/.config/" 2>/dev/null || true
        fi
    fi

    # Copy shared bindings.conf into the compositor config dir
    # This file is the single source of truth for keybindings across compositors
    if [[ -f "$SRC_DIR/shared/configs/smplos/bindings.conf" ]]; then
        log_info "Copying shared bindings.conf"
        mkdir -p "$skel/.config/hypr" "$skel/.config/smplos"
        cp "$SRC_DIR/shared/configs/smplos/bindings.conf" "$skel/.config/hypr/bindings.conf"
        cp "$SRC_DIR/shared/configs/smplos/bindings.conf" "$skel/.config/smplos/bindings.conf"
    fi

    # Copy messengers.conf (default messenger apps for toggle keybindings)
    if [[ -f "$SRC_DIR/shared/configs/smplos/messengers.conf" ]]; then
        log_info "Copying messengers.conf"
        mkdir -p "$skel/.config/smplos"
        cp "$SRC_DIR/shared/configs/smplos/messengers.conf" "$skel/.config/smplos/messengers.conf"
        # Create empty placeholder so Hyprland source doesn't fail before generator runs
        touch "$skel/.config/hypr/messenger-bindings.conf"
    fi
    
    # Copy installer (gum-based configurator + helpers)
    if [[ -d "$SRC_DIR/shared/installer" ]]; then
        log_info "Copying smplOS installer stack"
        
        # Copy configurator
        cp "$SRC_DIR/shared/installer/configurator" "$airootfs/root/configurator"
        chmod +x "$airootfs/root/configurator"
        
        # Copy helpers
        cp -r "$SRC_DIR/shared/installer/helpers/"* "$airootfs/root/smplos/install/helpers/"

        # Copy hardware detection scripts (run post-install for GPU driver setup)
        if [[ -d "$SRC_DIR/shared/installer/config/hardware" ]]; then
            mkdir -p "$airootfs/root/smplos/install/config/hardware"
            cp "$SRC_DIR/shared/installer/config/hardware/"*.sh \
                "$airootfs/root/smplos/install/config/hardware/"
            chmod +x "$airootfs/root/smplos/install/config/hardware/"*.sh
        fi
        
        # Copy post-install script
        cp "$SRC_DIR/shared/installer/install.sh" "$airootfs/root/smplos/install.sh"
        chmod +x "$airootfs/root/smplos/install.sh"
        
        # Copy automated script
        cp "$SRC_DIR/shared/installer/automated_script.sh" "$airootfs/root/.automated_script.sh"
        chmod +x "$airootfs/root/.automated_script.sh"
    fi

    # Copy package lists so the configurator can read them at install time
    # Merge shared + compositor packages into a single list (the configurator reads one file)
    local compositor_dir="$SRC_DIR/compositors/$COMPOSITOR"
    log_info "Merging shared + compositor package lists for installer"
    : > "$airootfs/root/smplos/packages.txt"  # start empty
    if [[ -f "$SRC_DIR/shared/packages.txt" ]]; then
        cat "$SRC_DIR/shared/packages.txt" >> "$airootfs/root/smplos/packages.txt"
    fi
    if [[ -f "$compositor_dir/packages.txt" ]]; then
        cat "$compositor_dir/packages.txt" >> "$airootfs/root/smplos/packages.txt"
    fi
    # Merge shared + compositor AUR package lists
    : > "$airootfs/root/smplos/packages-aur.txt"  # start empty
    if [[ -f "$SRC_DIR/shared/packages-aur.txt" ]]; then
        cat "$SRC_DIR/shared/packages-aur.txt" >> "$airootfs/root/smplos/packages-aur.txt"
    fi
    if [[ -f "$compositor_dir/packages-aur.txt" ]]; then
        cat "$compositor_dir/packages-aur.txt" >> "$airootfs/root/smplos/packages-aur.txt"
    fi
    # Copy edition extra packages if building with editions (merge all stacked editions)
    if [[ -n "${EDITIONS:-}" ]]; then
        : > "$airootfs/root/smplos/packages-extra.txt"
        IFS=',' read -ra _eds <<< "$EDITIONS"
        for _ed in "${_eds[@]}"; do
            if [[ -f "$SRC_DIR/editions/$_ed/packages-extra.txt" ]]; then
                log_info "Merging edition ($_ed) extra packages"
                cat "$SRC_DIR/editions/$_ed/packages-extra.txt" >> "$airootfs/root/smplos/packages-extra.txt"
            fi
        done
    fi
    # Append edition AUR extras to merged AUR list
    if [[ -n "${EDITIONS:-}" ]]; then
        IFS=',' read -ra _eds <<< "$EDITIONS"
        for _ed in "${_eds[@]}"; do
            if [[ -f "$SRC_DIR/editions/$_ed/packages-aur-extra.txt" ]]; then
                log_info "Appending edition ($_ed) AUR packages"
                cat "$SRC_DIR/editions/$_ed/packages-aur-extra.txt" >> "$airootfs/root/smplos/packages-aur.txt"
            fi
        done
    fi

    # Deploy edition-specific .desktop files and icons
    if [[ -n "${EDITIONS:-}" ]]; then
        IFS=',' read -ra _eds <<< "$EDITIONS"
        for _ed in "${_eds[@]}"; do
            local ed_dir="$SRC_DIR/editions/$_ed"
            # .desktop files → skel + smplos data
            if [[ -d "$ed_dir/applications" ]]; then
                log_info "Deploying edition ($_ed) desktop entries"
                mkdir -p "$skel/.local/share/applications"
                cp "$ed_dir/applications/"*.desktop "$skel/.local/share/applications/" 2>/dev/null || true
                mkdir -p "$airootfs/root/smplos/applications"
                cp "$ed_dir/applications/"*.desktop "$airootfs/root/smplos/applications/" 2>/dev/null || true
            fi
            # Icons → system icon theme (hicolor)
            if [[ -d "$ed_dir/icons/hicolor" ]]; then
                log_info "Deploying edition ($_ed) icons"
                mkdir -p "$airootfs/usr/share/icons"
                cp -r "$ed_dir/icons/hicolor" "$airootfs/usr/share/icons/"
                # Also to smplos data for installer to deploy
                mkdir -p "$airootfs/root/smplos/icons/hicolor"
                cp -r "$ed_dir/icons/hicolor/"* "$airootfs/root/smplos/icons/hicolor/"
            fi
        done
    fi
    
    # Copy Plymouth theme
    local branding_plymouth="$SRC_DIR/shared/configs/smplos/branding/plymouth"
    if [[ -d "$branding_plymouth" ]]; then
        log_info "Copying Plymouth theme"
        cp -r "$branding_plymouth/"* "$airootfs/root/smplos/branding/plymouth/"
        
        # Install smplOS Plymouth theme into the airootfs overlay
        # mkarchiso applies airootfs BEFORE installing packages, then runs
        # pacstrap which triggers our hook to set the theme properly.
        
        # 1. Pre-place the theme files (they'll survive pacstrap)
        mkdir -p "$airootfs/usr/share/plymouth/themes/smplos"
        cp -r "$branding_plymouth/"* "$airootfs/usr/share/plymouth/themes/smplos/"
        
        # 2. Store logo for watermark replacement
        mkdir -p "$airootfs/usr/share/smplos"
        cp "$branding_plymouth/logo.png" "$airootfs/usr/share/smplos/logo.png"
        
        # 3. Pacman hook: runs after plymouth install, BEFORE mkinitcpio (89 < 90)
        #    Sets our theme as default and replaces spinner watermark as fallback
        mkdir -p "$airootfs/etc/pacman.d/hooks"
        cat > "$airootfs/etc/pacman.d/hooks/89-smplos-plymouth.hook" << 'HOOKEOF'
[Trigger]
Type = Package
Operation = Install
Operation = Upgrade
Target = plymouth

[Action]
Description = Setting up smplOS Plymouth theme...
When = PostTransaction
Exec = /usr/local/bin/setup-plymouth
HOOKEOF
        
        # 4. Setup script called by the hook
        cat > "$airootfs/usr/local/bin/setup-plymouth" << 'SETUPEOF'
#!/bin/bash
# Install and activate smplOS Plymouth theme
THEME_SRC="/usr/share/plymouth/themes/smplos"
SPINNER_DIR="/usr/share/plymouth/themes/spinner"

# Set smplOS as default Plymouth theme
if [[ -f "$THEME_SRC/smplos.plymouth" ]]; then
    plymouth-set-default-theme smplos 2>/dev/null || true
fi

# Also replace spinner watermark as fallback
if [[ -f /usr/share/smplos/logo.png && -d "$SPINNER_DIR" ]]; then
    cp /usr/share/smplos/logo.png "$SPINNER_DIR/watermark.png"
fi
SETUPEOF
        chmod +x "$airootfs/usr/local/bin/setup-plymouth"
        log_info "Plymouth theme and pacman hook installed"
    fi
    
    # Font cache hook: rebuild fc-cache after font packages install
    # This eliminates the ~3s cold-start penalty on first terminal launch
    mkdir -p "$airootfs/etc/pacman.d/hooks"
    cat > "$airootfs/etc/pacman.d/hooks/90-fc-cache.hook" << 'FCHOOK'
[Trigger]
Type = Package
Operation = Install
Operation = Upgrade
Target = ttf-*
Target = otf-*
Target = noto-fonts*

[Action]
Description = Rebuilding font cache...
When = PostTransaction
Exec = /usr/bin/fc-cache -f
FCHOOK
    log_info "Font cache pacman hook installed"
    
    # Copy configs for post-install
    if [[ -d "$SRC_DIR/shared/configs" ]]; then
        cp -r "$SRC_DIR/shared/configs/"* "$airootfs/root/smplos/config/" 2>/dev/null || true
    fi
    if [[ -d "$compositor_dir/hypr" ]]; then
        mkdir -p "$airootfs/root/smplos/config/hypr"
        cp -r "$compositor_dir/hypr/"* "$airootfs/root/smplos/config/hypr/" 2>/dev/null || true
    fi
    # Copy shared bindings.conf into post-install hypr config
    if [[ -f "$SRC_DIR/shared/configs/smplos/bindings.conf" ]]; then
        mkdir -p "$airootfs/root/smplos/config/hypr" "$airootfs/root/smplos/config/smplos"
        cp "$SRC_DIR/shared/configs/smplos/bindings.conf" "$airootfs/root/smplos/config/hypr/bindings.conf"
        cp "$SRC_DIR/shared/configs/smplos/bindings.conf" "$airootfs/root/smplos/config/smplos/bindings.conf"
    fi
    # Copy messengers.conf into post-install store
    if [[ -f "$SRC_DIR/shared/configs/smplos/messengers.conf" ]]; then
        cp "$SRC_DIR/shared/configs/smplos/messengers.conf" "$airootfs/root/smplos/config/smplos/messengers.conf"
        touch "$airootfs/root/smplos/config/hypr/messenger-bindings.conf"
    fi
    # Copy shared configs (dunst, etc.) into post-install store
    if [[ -d "$SRC_DIR/shared/configs/dunst" ]]; then
        mkdir -p "$airootfs/root/smplos/config/dunst"
        cp -r "$SRC_DIR/shared/configs/dunst/"* "$airootfs/root/smplos/config/dunst/" 2>/dev/null || true
    fi
    # Copy other compositor configs (share-picker, etc.)
    if [[ -d "$compositor_dir/configs" ]]; then
        cp -r "$compositor_dir/configs/"* "$airootfs/root/smplos/config/" 2>/dev/null || true
    fi
    
    # Setup systemd services
    setup_services "$airootfs"
    
    # Setup helper scripts
    setup_helper_scripts "$airootfs"
    
    log_info "Airootfs configured"
}

setup_services() {
    local airootfs="$1"
    
    log_info "Setting up systemd services"
    
    mkdir -p "$airootfs/etc/systemd/system/multi-user.target.wants"
    mkdir -p "$airootfs/etc/systemd/system/getty@tty1.service.d"
    
    # Enable NetworkManager
    ln -sf /usr/lib/systemd/system/NetworkManager.service \
        "$airootfs/etc/systemd/system/multi-user.target.wants/NetworkManager.service" 2>/dev/null || true
    
    # Auto-login on tty1
    cat > "$airootfs/etc/systemd/system/getty@tty1.service.d/autologin.conf" << 'AUTOLOGIN'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I 38400 linux
AUTOLOGIN

    echo "smplos" > "$airootfs/etc/hostname"
    echo "LANG=en_US.UTF-8" > "$airootfs/etc/locale.conf"
    echo "en_US.UTF-8 UTF-8" >> "$airootfs/etc/locale.gen"

    # Boot log service: auto-saves dmesg + journal to Ventoy partition after boot
    # Only activates when /dev/disk/by-label/Ventoy exists (i.e. booted from Ventoy USB)
    cat > "$airootfs/etc/systemd/system/smplos-boot-log.service" << 'BOOTLOGSVC'
[Unit]
Description=Save boot log to Ventoy disk (smplOS debug)
After=local-fs.target systemd-journald.service
ConditionPathExists=/dev/disk/by-label/Ventoy

[Service]
Type=oneshot
ExecStart=/usr/local/bin/smplos-boot-log
StandardOutput=journal
StandardError=journal
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
BOOTLOGSVC
    ln -sf /etc/systemd/system/smplos-boot-log.service \
        "$airootfs/etc/systemd/system/multi-user.target.wants/smplos-boot-log.service" 2>/dev/null || true

    # Enable systemd user units (app cache builder)
    local skel="$airootfs/etc/skel"
    local user_wants="$skel/.config/systemd/user/default.target.wants"
    mkdir -p "$user_wants"
    ln -sf ../smplos-app-cache.service "$user_wants/smplos-app-cache.service" 2>/dev/null || true
    ln -sf ../smplos-app-cache.path "$user_wants/smplos-app-cache.path" 2>/dev/null || true
}

setup_helper_scripts() {
    local airootfs="$1"
    
    # Flatpak first-boot setup: add Flathub remote and install listed apps
    cat > "$airootfs/usr/local/bin/smplos-flatpak-setup" << 'FLATPAKSETUP'
#!/bin/bash
# Install Flatpak apps from the bundled list (requires internet)

FLATPAK_LIST="/opt/flatpaks/install-online.txt"
MARKER="$HOME/.config/smplos-flatpak-done"
LOG="$HOME/.cache/smplos/flatpak-setup.log"

mkdir -p "$(dirname "$LOG")"
exec &> >(tee -a "$LOG")

[[ -f "$MARKER" ]] && { echo "Flatpak setup already done"; exit 0; }
[[ -f "$FLATPAK_LIST" ]] || { echo "No flatpak list at $FLATPAK_LIST"; exit 0; }

echo "==> smplos-flatpak-setup starting at $(date)"

# Wait for network (up to 30s)
for i in $(seq 1 30); do
    if ping -c1 -W1 flathub.org &>/dev/null; then
        echo "Network available"
        break
    fi
    [[ $i -eq 30 ]] && { echo "No network after 30s, will retry next login"; exit 0; }
    sleep 1
done

flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo || {
    echo "ERROR: Failed to add Flathub remote"
    exit 0
}

installed=0
failed=0
while IFS= read -r app_id; do
    [[ -z "$app_id" || "$app_id" == \#* ]] && continue
    echo "Installing Flatpak: $app_id"
    if flatpak install --noninteractive --user flathub "$app_id" 2>&1; then
        installed=$((installed + 1))
        # Rename the desktop entry to include (Flatpak) suffix
        local_desktop="$HOME/.local/share/flatpak/exports/share/applications/${app_id}.desktop"
        override_desktop="$HOME/.local/share/applications/${app_id}.desktop"
        if [[ -f "$local_desktop" ]]; then
            mkdir -p "$HOME/.local/share/applications"
            sed 's/^Name=\(.*\)/Name=\1 (Flatpak)/' "$local_desktop" > "$override_desktop"
        fi
    else
        echo "Warning: Failed to install $app_id"
        failed=$((failed + 1))
    fi
done < "$FLATPAK_LIST"

echo "==> Flatpak setup complete: $installed installed, $failed failed"

# Only mark done if all succeeded
if [[ $failed -eq 0 ]]; then
    mkdir -p "$(dirname "$MARKER")"
    touch "$MARKER"
else
    echo "Some apps failed — will retry next login"
fi
FLATPAKSETUP
    chmod +x "$airootfs/usr/local/bin/smplos-flatpak-setup"
    
    # AppImage setup: create desktop entries for bundled AppImages
    cat > "$airootfs/usr/local/bin/smplos-appimage-setup" << 'APPIMAGESETUP'
#!/bin/bash
# Create desktop entries for bundled AppImages
set -euo pipefail

mkdir -p "$HOME/.local/share/applications"
mkdir -p "$HOME/.local/share/icons"

for appimage in /opt/appimages/*.AppImage; do
    [[ -f "$appimage" ]] || continue
    name=$(basename "$appimage" .AppImage)
    desktop_file="$HOME/.local/share/applications/${name}-appimage.desktop"

    # Skip if already created
    [[ -f "$desktop_file" ]] && continue

    # Try to extract icon from the AppImage
    icon_name="application-x-executable"
    tmpdir=$(mktemp -d)
    if cd "$tmpdir" && "$appimage" --appimage-extract '*.png' &>/dev/null; then
        icon_src=$(find "$tmpdir/squashfs-root" -name '*.png' -size +1k 2>/dev/null | head -1)
        if [[ -n "$icon_src" ]]; then
            cp "$icon_src" "$HOME/.local/share/icons/${name}-appimage.png"
            icon_name="${name}-appimage"
        fi
    fi
    rm -rf "$tmpdir"

    cat > "$desktop_file" << EOF
[Desktop Entry]
Type=Application
Name=${name} (AppImage)
Exec=${appimage} --no-sandbox %U
Icon=${icon_name}
Terminal=false
Categories=Utility;
EOF
    echo "Created desktop entry: ${name} (AppImage)"
done
APPIMAGESETUP
    chmod +x "$airootfs/usr/local/bin/smplos-appimage-setup"

    # Boot log helper: writes dmesg + journal to the Ventoy data partition
    # Useful for diagnosing live-session boot failures (black screen, hangs, etc.)
    # The matching systemd service is enabled in setup_services()
    cat > "$airootfs/usr/local/bin/smplos-boot-log" << 'BOOTLOG'
#!/bin/bash
# smplos-boot-log: save boot logs to the Ventoy data partition for debugging.
# Each boot run gets its own timestamped subdirectory under smplos-boot-logs/
# so you can always tell which log is the most recent.
set -euo pipefail

LOG_ROOT="smplos-boot-logs"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Find Ventoy data partition by its well-known label
VENTOY_DEV=$(blkid -L Ventoy 2>/dev/null || true)
if [[ -z "$VENTOY_DEV" ]]; then
    echo "smplos-boot-log: Ventoy partition not found (label 'Ventoy') — skipping"
    exit 0
fi

MNT=$(mktemp -d /run/smplos-ventoy-XXXXXX)
trap 'umount "$MNT" 2>/dev/null; rmdir "$MNT" 2>/dev/null' EXIT

if ! mount -o rw,noatime "$VENTOY_DEV" "$MNT" 2>/dev/null; then
    echo "smplos-boot-log: could not mount $VENTOY_DEV rw — is it write-protected?"
    exit 1
fi

# Each run gets its own subdirectory: YYYYMMDD-HHMMSS/
RUN_DIR="$MNT/$LOG_ROOT/$TIMESTAMP"
mkdir -p "$RUN_DIR"

# ── Run summary: first thing to open when investigating a boot failure ────
cat > "$RUN_DIR/summary.txt" << EOF
=== smplOS Boot Log ===
Timestamp : $TIMESTAMP
Kernel    : $(uname -r)
Cmdline   : $(cat /proc/cmdline)
Hostname  : $(cat /etc/hostname 2>/dev/null || echo unknown)
Uptime    : $(uptime -p 2>/dev/null || uptime)
$(lspci 2>/dev/null | grep -iE 'vga|3d|display|nvidia|amd|intel' | sed 's/^/GPU       : /')
======================
EOF

dmesg > "$RUN_DIR/dmesg.log"
journalctl -b 0 --no-pager > "$RUN_DIR/journal.log" 2>/dev/null || true
sync

echo "smplos-boot-log: logs saved → $LOG_ROOT/$TIMESTAMP/{summary.txt,dmesg.log,journal.log}"
BOOTLOG
    chmod +x "$airootfs/usr/local/bin/smplos-boot-log"
}

###############################################################################
# Setup Boot Configuration
###############################################################################

setup_boot() {
    log_step "Configuring boot"

    # ── systemd-boot for UEFI ─────────────────────────────────────────
    # systemd-boot copies kernel+initramfs INTO the EFI FAT partition,
    # making it self-contained.  This is what official Arch, EndeavourOS,
    # and CachyOS all use.  Unlike GRUB, there is no fragile search for
    # the ISO9660 filesystem -- it just works on all UEFI firmware.
    mkdir -p "$PROFILE_DIR/efiboot/loader/entries"

    # Remove every entry that releng shipped — Arch install medium, speech,
    # memtest — so the user only sees our 3 smplOS entries.
    rm -f "$PROFILE_DIR/efiboot/loader/entries/"*.conf
    # Wipe memtest EFI binary copied by mkarchiso so firmware scanners don't surface it
    rm -rf "$PROFILE_DIR/efiboot/memtest86+" 2>/dev/null || true

    cat > "$PROFILE_DIR/efiboot/loader/loader.conf" << 'LOADERCONF'
timeout 5
default 01-smplos.conf
LOADERCONF

    cat > "$PROFILE_DIR/efiboot/loader/entries/01-smplos.conf" << 'ENTRY1'
title    smplOS
sort-key 01
linux    /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux-zen
initrd   /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux-zen.img
# nomodeset: EFI framebuffer works on every GPU (NVIDIA/AMD/Intel) for the TUI
# installer. No proprietary driver needed. The installed system gets the correct
# GPU driver via hardware detection (install/config/hardware/*.sh) post-install.
options  archisobasedir=%INSTALL_DIR% archisosearchuuid=%ARCHISO_UUID% quiet plymouth.nolog loglevel=3 rd.udev.log_level=3 rd.systemd.show_status=false systemd.show_status=false vt.global_cursor_default=0 console=tty1 mce=dont_log_ce nomodeset
ENTRY1

    cat > "$PROFILE_DIR/efiboot/loader/entries/02-smplos-safe.conf" << 'ENTRY2'
title    smplOS (Safe Mode)
sort-key 02
linux    /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux-zen
initrd   /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux-zen.img
options  archisobasedir=%INSTALL_DIR% archisosearchuuid=%ARCHISO_UUID% nomodeset mce=dont_log_ce
ENTRY2

    cat > "$PROFILE_DIR/efiboot/loader/entries/03-smplos-debug.conf" << 'ENTRY3'
title    smplOS (Debug)
sort-key 03
linux    /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux-zen
initrd   /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux-zen.img
# Full verbose boot: shows all kernel/initramfs/systemd messages on screen
# Select this entry to diagnose black-screen or hang failures
options  archisobasedir=%INSTALL_DIR% archisosearchuuid=%ARCHISO_UUID% nvidia-drm.modeset=1 rd.debug rd.udev.log_level=7 systemd.log_level=info earlyprintk=efi,keep mce=dont_log_ce
ENTRY3

    # ── GRUB loopback.cfg for Ventoy / loopback booting ───────────────
    # When systemd-boot is the primary UEFI bootloader, mkarchiso still
    # copies grub/loopback.cfg to the ISO9660 for tools like Ventoy that
    # chain-load GRUB in loopback mode.
    #
    # IMPORTANT: loopback.cfg must set timeout + timeout_style=menu or
    # Ventoy's inherited timeout=0 will auto-boot with no menu visible.
    # Use the modern img_dev/img_loop format (not archisosearchuuid) so
    # the initramfs can find the ISO when it is loop-mounted by Ventoy.
    mkdir -p "$PROFILE_DIR/grub"
    cat > "$PROFILE_DIR/grub/loopback.cfg" << 'LOOPBACKCFG'
# https://www.supergrubdisk.org/wiki/Loopback.cfg

# Locate the device that holds the ISO image and capture its UUID.
# ${iso_path} is set by Ventoy before sourcing this file.
search --no-floppy --set=archiso_img_dev --file "${iso_path}"
probe --set archiso_img_dev_uuid --fs-uuid "${archiso_img_dev}"

set default=smplos
set timeout=10
set timeout_style=menu

menuentry "smplOS" --id smplos --class arch --class gnu-linux --class gnu --class os {
    set gfxpayload=keep
    # nomodeset: EFI framebuffer works on every GPU for the TUI installer.
    # Post-install hardware detection installs the correct GPU driver offline.
    linux /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux-zen archisobasedir=%INSTALL_DIR% img_dev=UUID=${archiso_img_dev_uuid} img_loop="${iso_path}" quiet plymouth.nolog loglevel=3 rd.udev.log_level=3 rd.systemd.show_status=false systemd.show_status=false vt.global_cursor_default=0 console=tty1 mce=dont_log_ce nomodeset
    initrd /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux-zen.img
}

menuentry "smplOS (Safe Mode)" --id smplos-safe --class arch --class gnu-linux --class gnu --class os {
    set gfxpayload=keep
    linux /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux-zen archisobasedir=%INSTALL_DIR% img_dev=UUID=${archiso_img_dev_uuid} img_loop="${iso_path}" nomodeset mce=dont_log_ce
    initrd /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux-zen.img
}

menuentry "smplOS (Debug)" --id smplos-debug --class arch --class gnu-linux --class gnu --class os {
    set gfxpayload=keep
    # Full verbose boot: shows all kernel/initramfs/systemd messages on screen
    # Select this entry to diagnose black-screen or hang failures
    linux /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux-zen archisobasedir=%INSTALL_DIR% img_dev=UUID=${archiso_img_dev_uuid} img_loop="${iso_path}" nvidia-drm.modeset=1 rd.debug rd.udev.log_level=7 systemd.log_level=info earlyprintk=efi,keep mce=dont_log_ce
    initrd /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux-zen.img
}
LOOPBACKCFG

    # ── Syslinux for BIOS boot ────────────────────────────────────────
    mkdir -p "$PROFILE_DIR/syslinux"
    cat > "$PROFILE_DIR/syslinux/syslinux.cfg" << 'SYSLINUXCFG'
DEFAULT select

LABEL select
COM32 whichsys.c32
APPEND -pxe- pxe -sys- sys -iso- sys

LABEL pxe
CONFIG archiso_pxe.cfg

LABEL sys
CONFIG archiso_sys.cfg
SYSLINUXCFG

    # Overwrite the releng head so the menu title says smplOS, not Arch Linux
    cat > "$PROFILE_DIR/syslinux/archiso_head.cfg" << 'SYSHEAD'
SERIAL 0 115200
UI vesamenu.c32
MENU TITLE smplOS
MENU BACKGROUND splash.png

MENU WIDTH 78
MENU MARGIN 4
MENU ROWS 7
MENU VSHIFT 10
MENU TABMSGROW 14
MENU CMDLINEROW 14
MENU HELPMSGROW 16
MENU HELPMSGENDROW 29

MENU COLOR border       30;44   #40ffffff #a0000000 std
MENU COLOR title        1;36;44 #9033ccff #a0000000 std
MENU COLOR sel          7;37;40 #e0ffffff #20ffffff all
MENU COLOR unsel        37;44   #50ffffff #a0000000 std
MENU COLOR help         37;40   #c0ffffff #a0000000 std
MENU COLOR timeout_msg  37;40   #80ffffff #00000000 std
MENU COLOR timeout      1;37;40 #c0ffffff #00000000 std
MENU COLOR msg07        37;40   #90ffffff #a0000000 std
MENU COLOR tabmsg       31;40   #30ffffff #00000000 std

MENU CLEAR
MENU IMMEDIATE
SYSHEAD

    # Overwrite the releng tail — remove memtest, HDT, chain-boot; keep only reboot/poweroff
    cat > "$PROFILE_DIR/syslinux/archiso_tail.cfg" << 'SYSTAIL'
LABEL reboot
MENU LABEL Reboot
COM32 reboot.c32

LABEL poweroff
MENU LABEL Power Off
COM32 poweroff.c32
SYSTAIL

    cat > "$PROFILE_DIR/syslinux/archiso_sys.cfg" << 'ARCHISOSYS'
DEFAULT arch
PROMPT 1
TIMEOUT 50

UI vesamenu.c32
MENU TITLE smplOS Boot Menu

LABEL arch
    MENU LABEL smplOS
    LINUX /%INSTALL_DIR%/boot/x86_64/vmlinuz-linux-zen
    INITRD /%INSTALL_DIR%/boot/x86_64/initramfs-linux-zen.img
    # nomodeset: EFI framebuffer works on every GPU for the TUI installer.
    # Post-install hardware detection installs the correct GPU driver offline.
    APPEND archisobasedir=%INSTALL_DIR% archisosearchuuid=%ARCHISO_UUID% quiet plymouth.nolog loglevel=3 rd.udev.log_level=3 rd.systemd.show_status=false systemd.show_status=false vt.global_cursor_default=0 console=tty1 mce=dont_log_ce nomodeset

LABEL arch_safe
    MENU LABEL smplOS (Safe Mode)
    LINUX /%INSTALL_DIR%/boot/x86_64/vmlinuz-linux-zen
    INITRD /%INSTALL_DIR%/boot/x86_64/initramfs-linux-zen.img
    APPEND archisobasedir=%INSTALL_DIR% archisosearchuuid=%ARCHISO_UUID% nomodeset mce=dont_log_ce

LABEL arch_debug
    MENU LABEL smplOS (Debug)
    LINUX /%INSTALL_DIR%/boot/x86_64/vmlinuz-linux-zen
    INITRD /%INSTALL_DIR%/boot/x86_64/initramfs-linux-zen.img
    # Full verbose boot: shows all kernel/initramfs/systemd messages on screen
    APPEND archisobasedir=%INSTALL_DIR% archisosearchuuid=%ARCHISO_UUID% nvidia-drm.modeset=1 rd.debug rd.udev.log_level=7 systemd.log_level=info earlyprintk=efi,keep mce=dont_log_ce
ARCHISOSYS

    log_info "Boot configuration updated"
}

###############################################################################
# Build ISO
###############################################################################

build_iso() {
    log_step "Building ISO image"
    
    mkdir -p "$RELEASE_DIR"
    
    mkarchiso -v -w "$WORK_DIR" -o "$RELEASE_DIR" "$PROFILE_DIR"
    
    local iso_file
    iso_file=$(find "$RELEASE_DIR" -maxdepth 1 -name "*.iso" -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)
    
    if [[ -n "$iso_file" && -f "$iso_file" ]]; then
        local new_name="${ISO_NAME}-${COMPOSITOR}"
        if [[ -n "$EDITIONS" ]]; then
            # Join edition names with + (e.g., productivity+development)
            local ed_slug="${EDITIONS//,/+}"
            new_name="${new_name}-${ed_slug}"
        fi
        new_name="${new_name}-${ISO_VERSION}.iso"
        
        mv "$iso_file" "$RELEASE_DIR/$new_name"
        
        log_info ""
        log_info "ISO built successfully!"
        log_info "File: $new_name"
        log_info "Size: $(du -h "$RELEASE_DIR/$new_name" | cut -f1)"
    else
        log_error "ISO file not found!"
        exit 1
    fi
    
    if [[ -n "${HOST_UID:-}" && -n "${HOST_GID:-}" ]]; then
        chown -R "$HOST_UID:$HOST_GID" "$RELEASE_DIR/"
    fi
}

###############################################################################
# Main
###############################################################################

main() {
    log_info "smplOS ISO Builder"
    log_info "=================="
    log_info "Compositor: $COMPOSITOR"
    [[ -n "$EDITIONS" ]] && log_info "Editions: $EDITIONS"
    [[ -n "$RELEASE" ]] && log_info "Release mode: max xz compression"
    [[ -n "$SKIP_AUR" ]] && log_info "AUR: disabled"
    [[ -n "$SKIP_FLATPAK" ]] && log_info "Flatpak: disabled"
    [[ -n "$SKIP_APPIMAGE" ]] && log_info "AppImage: disabled"
    log_info ""
    
    setup_build_env
    collect_packages
    setup_profile
    download_packages
    process_aur_packages
    download_flatpaks
    download_appimages
    create_repo_database
    setup_pacman_conf
    update_package_list
    update_profiledef
    setup_airootfs
    build_st
    build_notif_center
    build_kb_center
    build_disp_center
    build_app_center
    setup_boot
    build_iso
    
    log_info ""
    log_info "Build completed successfully!"
}

main "$@"
