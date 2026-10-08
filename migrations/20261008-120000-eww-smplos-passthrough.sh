#!/bin/bash
# Migration: eww-smplos with the :passthrough window property.
#
# Context: smpl-os/eww 0eb4604 adds `:passthrough` to defwindow (an empty
#          input region). The keypad cheatsheet's optional click-through
#          window uses it (KEYPAD.md); verified on X11 only, Wayland pending.
#          eww-smplos pkgrel 2 builds that commit. This rebuilds an installed
#          eww-smplos that predates it; machines without eww-smplos get the
#          current one from 20260805-100000-eww-smplos-fork-install.
#
#          The bar is not restarted: it keeps the old binary until the next
#          login, and until then the click-through window stays clickable.
#
# Safe to re-run: nothing to do once eww-smplos is at the PKGBUILD's commit.
# A failed build (offline, no space) keeps the installed eww-smplos and
# defers (exit 75), so the next update retries.

set -uo pipefail

SMPLOS_PATH="${SMPLOS_PATH:-$HOME/.local/share/smplos}"
REPO="${SMPLOS_REPO:-$SMPLOS_PATH/repo}"
DIR="$REPO/src/shared/pkgbuilds/eww-smplos"

# shellcheck source=../src/shared/lib/smplos-pkgbuild.sh
source "$REPO/src/shared/lib/smplos-pkgbuild.sh" 2>/dev/null || {
    echo "  WARNING: smplos-pkgbuild.sh not found; retry after the next update"
    exit 75
}

installed=$(smplos_pkg_version eww-smplos)
if [[ -z "$installed" ]]; then
    echo "  eww-smplos not installed; the eww-smplos install migration provides it"
    exit 0
fi
commit=$(sed -n 's/^_commit=\([0-9a-f]\{7\}\).*/\1/p' "$DIR/PKGBUILD" 2>/dev/null)
if [[ -z "$commit" ]]; then
    echo "  WARNING: no _commit in $DIR/PKGBUILD; retry after the next update"
    exit 75
fi
if [[ "$installed" == *".g$commit-"* ]]; then
    echo "  eww-smplos already at $commit"
    exit 0
fi

echo "  Rebuilding eww-smplos $installed at $commit (about 5-10 minutes)..."
if smplos_pkgbuild_install "$DIR"; then
    echo "  Installed eww-smplos $(smplos_pkg_version eww-smplos); it loads at the next login"
    exit 0
fi
echo "  eww-smplos build failed; $installed stays installed. Will retry on the next update."
exit 75
