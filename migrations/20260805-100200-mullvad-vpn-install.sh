#!/bin/bash
# SMPLOS_UPDATE_PRIORITY=optional
# Migration: Install Mullvad VPN on existing customer machines
#
# Context: mullvad-vpn-bin is registered as a default AUR-style package in
#          src/shared/packages-aur.txt (installed on every edition at ISO
#          build time). Customer machines built from older ISOs — before
#          the mullvad-vpn-bin PKGBUILD landed on main — never got it, and
#          `smplos-update` only runs `pacman -Syu`, which cannot install
#          new packages (only upgrade existing ones).
#
#          This migration builds src/shared/pkgbuilds/mullvad-vpn-bin/ from
#          the local repo clone and installs it. The PKGBUILD verifies the
#          upstream .deb by pinned SHA-256 + pinned Mullvad PGP fingerprint,
#          so the trust chain matches the ISO build.
#
# Safety:  Idempotent — exits 0 if mullvad-vpn-bin is already installed.
#          Prerequisite failures remain unmarked for the optional phase to
#          retry; they do not block core OS completion. The
#          bundled .install hook enables mullvad-daemon.service on first
#          install; no separate systemctl call needed here.

set -uo pipefail

# ── Idempotency guards ───────────────────────────────────────────────────────
if pacman -Q mullvad-vpn-bin &>/dev/null; then
    echo "  mullvad-vpn-bin already installed — nothing to do"
    exit 0
fi

# ── Prerequisites ────────────────────────────────────────────────────────────
SMPLOS_PATH="${SMPLOS_PATH:-$HOME/.local/share/smplos}"
PKGBUILD_DIR="$SMPLOS_PATH/repo/src/shared/pkgbuilds/mullvad-vpn-bin"

if [[ ! -f "$PKGBUILD_DIR/PKGBUILD" ]]; then
    echo "  WARNING: $PKGBUILD_DIR/PKGBUILD not found — skipping"
    echo "  Re-run smplos-migrate after the next 'Update OS'."
    exit 1
fi

# Bootstrap build tools if missing (customer machines may not have base-devel).
_need_bootstrap=()
command -v makepkg &>/dev/null || _need_bootstrap+=(base-devel)
command -v gpg     &>/dev/null || _need_bootstrap+=(gnupg)
command -v curl    &>/dev/null || _need_bootstrap+=(curl)
if [[ ${#_need_bootstrap[@]} -gt 0 ]]; then
    echo "  Bootstrapping build tools: ${_need_bootstrap[*]}"
    if ! sudo pacman -S --needed --noconfirm "${_need_bootstrap[@]}"; then
        echo "  ERROR: could not install build tools — will retry on next update"
        exit 1
    fi
fi

for dep in makepkg gpg curl; do
    if ! command -v "$dep" &>/dev/null; then
        echo "  ERROR: $dep not found even after bootstrap — will retry on next update"
        exit 1
    fi
done

# The PKGBUILD downloads the .deb from cdn.mullvad.net; skip if offline.
if ! curl -fsSL --connect-timeout 5 --max-time 8 https://cdn.mullvad.net >/dev/null 2>&1; then
    echo "  WARNING: cdn.mullvad.net unreachable — will retry on next update"
    exit 1
fi

# ── Build in a scratch dir owned by the invoking user ────────────────────────
BUILD_DIR=$(mktemp -d /tmp/mullvad-vpn-bin-build.XXXXXX)
trap 'rm -rf "$BUILD_DIR"' EXIT

# Copy the whole pkgbuild dir (need the embedded gpg key + .install alongside).
cp -a "$PKGBUILD_DIR"/. "$BUILD_DIR/"
# Drop any stale build artifacts the source dir might carry.
rm -rf "$BUILD_DIR/pkg" "$BUILD_DIR/src" "$BUILD_DIR"/*.pkg.tar.* 2>/dev/null || true

echo "  Building mullvad-vpn-bin (fetch + verify signed .deb from cdn.mullvad.net)..."
if [[ $EUID -eq 0 ]]; then
    sudo useradd -m -r _mvbuild 2>/dev/null || true
    sudo chown -R _mvbuild:_mvbuild "$BUILD_DIR"
    if ! sudo -u _mvbuild bash -c "cd '$BUILD_DIR' && makepkg -s --noconfirm"; then
        echo "  ERROR: makepkg failed — will retry on next update"
        sudo userdel -r _mvbuild 2>/dev/null || true
        exit 1
    fi
    sudo userdel -r _mvbuild 2>/dev/null || true
else
    if ! (cd "$BUILD_DIR" && PACMAN="${SMPLOS_UPDATE_PACMAN:-${PACMAN:-pacman}}" makepkg -s --noconfirm); then
        echo "  ERROR: makepkg failed — will retry on next update"
        exit 1
    fi
fi

# ── Install the freshly built package ────────────────────────────────────────
PKG_FILE=$(ls "$BUILD_DIR"/mullvad-vpn-bin-*.pkg.tar.* 2>/dev/null | head -1)
if [[ ! -f "$PKG_FILE" ]]; then
    echo "  ERROR: makepkg produced no package file — will retry on next update"
    exit 1
fi

if ! sudo pacman -U --noconfirm "$PKG_FILE"; then
    echo "  ERROR: pacman -U failed — will retry on next update"
    exit 1
fi

echo "  Installed $(pacman -Q mullvad-vpn-bin 2>/dev/null | awk '{print $1" "$2}')"
echo "  mullvad-daemon.service enabled by the pkgbuild's .install hook."
echo "  Next step for the user: 'mullvad account login' + 'mullvad connect'."
exit 0
