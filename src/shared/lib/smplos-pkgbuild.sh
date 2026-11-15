# shellcheck shell=bash
# Build and install a package from one of smplOS's local PKGBUILDs
# (src/shared/pkgbuilds/*). For migrations that deliver or update such a
# package on installed systems; the ISO builds them in build-iso.sh instead.

# The installed version of a package, or nothing.
smplos_pkg_version() {
    { pacman -Q "$1" 2>/dev/null || true; } | awk '{print $2}'
}

smplos_pkgbuild_version() {
    local version revision
    version=$(sed -n 's/^pkgver=\([0-9][0-9.]*\)$/\1/p' "$1/PKGBUILD") || return 1
    revision=$(sed -n 's/^pkgrel=\([0-9][0-9.]*\)$/\1/p' "$1/PKGBUILD") || return 1
    [[ -n "$version" && -n "$revision" && "$version$revision" != *$'\n'* ]] || {
        echo "  ERROR: cannot read full package version from $1/PKGBUILD" >&2
        return 1
    }
    printf '%s-%s\n' "$version" "$revision"
}

smplos_remove_retired_orphan() {
    local pkg="$1"
    if [[ ",${SMPLOS_UPDATE_PIN_IGNORE:-}," == *",$pkg,"* ]]; then
        echo "  $pkg is intentionally held - kept"
        return 0
    fi
    if ! pacman -Qq "$pkg" >/dev/null 2>&1; then
        echo "  $pkg not installed - nothing to do"
        return 0
    fi
    if ! pacman -Qdtq "$pkg" >/dev/null 2>&1; then
        echo "  $pkg is used by another package or was installed explicitly - kept"
        return 0
    fi
    if ! pacman -Qmq "$pkg" >/dev/null 2>&1 || pacman -Si "$pkg" >/dev/null 2>&1; then
        echo "  $pkg is provided by a repository - kept"
        return 0
    fi
    echo "  Removing orphaned $pkg (no longer shipped by Arch)"
    if ! sudo pacman -R --noconfirm "$pkg"; then
        echo "  ERROR: removal failed - will retry on next update"
        return 1
    fi
    echo "  Removed $pkg"
}

# smplos_pkgbuild_install DIR [PACMAN_FLAGS...]: package a scratch copy as the
# invoking user, then `sudo pacman -U` the package. Non-zero on any failure
# (offline, build error); the installed package, if any, is left as it was.
smplos_pkgbuild_install() {
    local dir="$1" build pkg rc=1
    shift
    [[ -f "$dir/PKGBUILD" ]] || { echo "  $dir/PKGBUILD not found"; return 1; }
    if [[ $EUID -eq 0 ]]; then
        echo "  makepkg can't run as root; run smplos-migrate as your user"
        return 1
    fi
    if ! command -v makepkg &>/dev/null || ! command -v fakeroot &>/dev/null; then
        echo "  Installing build tools (base-devel)"
        sudo pacman -S --needed --noconfirm base-devel git || return 1
    fi
    build=$(mktemp -d "${TMPDIR:-/tmp}/smplos-pkgbuild.XXXXXX") || return 1
    cp -a "$dir/." "$build/" || { rm -rf "$build"; return 1; }
    if (cd "$build" && PACMAN="${SMPLOS_UPDATE_PACMAN:-${PACMAN:-pacman}}" makepkg -s --noconfirm); then
        pkg=$(find "$build" -maxdepth 1 -name '*.pkg.tar.*' ! -name '*-debug-*' | head -1)
        [[ -n "$pkg" ]] && sudo pacman -U --noconfirm "$@" "$pkg" && rc=0
    fi
    rm -rf "$build"
    return $rc
}
