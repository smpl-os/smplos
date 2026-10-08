# shellcheck shell=bash
# Build and install a package from one of smplOS's local PKGBUILDs
# (src/shared/pkgbuilds/*). For migrations that deliver or update such a
# package on installed systems; the ISO builds them in build-iso.sh instead.

# The installed version of a package, or nothing.
smplos_pkg_version() {
    { pacman -Q "$1" 2>/dev/null || true; } | awk '{print $2}'
}

# smplos_pkgbuild_install DIR: makepkg a scratch copy of DIR/PKGBUILD as the
# invoking user, then `sudo pacman -U` the package. Non-zero on any failure
# (offline, build error); the installed package, if any, is left as it was.
smplos_pkgbuild_install() {
    local dir="$1" build pkg rc=1
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
    cp "$dir/PKGBUILD" "$build/"
    if (cd "$build" && makepkg -s --noconfirm --skippgpcheck); then
        pkg=$(find "$build" -maxdepth 1 -name '*.pkg.tar.*' ! -name '*-debug-*' | head -1)
        [[ -n "$pkg" ]] && sudo pacman -U --noconfirm "$pkg" && rc=0
    fi
    rm -rf "$build"
    return $rc
}
