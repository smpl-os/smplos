#!/bin/bash
# SMPLOS_UPDATE_PRIORITY=core
# Install only. Running Dunst keeps its history and old executable until the
# user separately agrees to activate the replacement.
set -uo pipefail

REPO="${SMPLOS_REPO:-${SMPLOS_PATH:-$HOME/.local/share/smplos}/repo}"
DIR="$REPO/src/shared/pkgbuilds/dunst-smplos"
source "$REPO/src/shared/lib/smplos-pkgbuild.sh" || exit 1

required=$(smplos_pkgbuild_version "$DIR") || exit 1
installed=$(smplos_pkg_version dunst-smplos)
if [[ "$installed" == "$required" ]]; then
    echo "  Signal notification bridge package is current; no daemon restart."
    exit 0
fi
smplos_pkgbuild_install "$DIR" --ask 4 || {
    echo "  ERROR: Signal notification package installation failed; retry Update OS."
    exit 1
}
[[ "$(smplos_pkg_version dunst-smplos)" == "$required" ]] || {
    echo "  ERROR: Signal notification package revision was not installed."
    exit 1
}
echo "  Signal notification bridge installed, NOT activated."
echo "  Keep Dunst running; agree separately when its replacement may start."
