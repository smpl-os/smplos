#!/bin/bash
# SMPLOS_UPDATE_PRIORITY=core
# The transaction is loaded per click; existing Dunst needs no restart.
set -uo pipefail

REPO="${SMPLOS_REPO:-${SMPLOS_PATH:-$HOME/.local/share/smplos}/repo}"
DIR="$REPO/src/shared/pkgbuilds/dunst-smplos"
source "$REPO/src/shared/lib/smplos-pkgbuild.sh" || exit 1

required=$(smplos_pkgbuild_version "$DIR") || exit 1
if [[ "$(smplos_pkg_version dunst-smplos)" != "$required" ]]; then
    smplos_pkgbuild_install "$DIR" --ask 4 || {
        echo "  ERROR: Signal notification dispatcher repair failed; retry Update OS."
        exit 1
    }
fi
[[ "$(smplos_pkg_version dunst-smplos)" == "$required" ]] || {
    echo "  ERROR: Signal notification dispatcher revision was not installed; retry Update OS."
    exit 1
}
echo "  Signal notification dispatcher repaired; existing Dunst loads it on the next click."
