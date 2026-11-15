#!/bin/bash
# Migration: Install eww-smplos (fork with Wayland button-grab fixes)
#
# Context: Vanilla AUR `eww` (upstream tag v0.6.0) has a bug where clicking
#          a button on the eww bar frequently no-ops until the mouse is moved
#          — GTK's default button-press handler installs an implicit pointer
#          grab that Wayland never sees released. The smplOS fork at
#          github.com/smpl-os/eww adds two commits on top of upstream master
#          that fix this (78105f3, 169e47a). Every customer machine currently
#          has vanilla `eww` and hits this bug.
#
#          This migration builds eww-smplos from src/shared/pkgbuilds/eww-smplos/
#          and installs it. The PKGBUILD's provides=/conflicts=/replaces=eww
#          make pacman -U swap the two cleanly.
#
# Safety:  Idempotent — exits early if eww-smplos is already installed. Never
#          uninstalls the running eww if the build/install fails (the old
#          package stays functional). Failed delivery remains unmarked and
#          makes the update incomplete while unrelated migrations continue.

set -uo pipefail

# ── Session env (see src/shared/lib/smplos-session-env.sh) ──────────────────
# pkexec strips XDG_RUNTIME_DIR / WAYLAND_DISPLAY / HYPRLAND_INSTANCE_SIGNATURE,
# so session-scoped commands must be re-attached to the invoker's session.
# shellcheck source=../src/shared/lib/smplos-session-env.sh
source "$(dirname "${BASH_SOURCE[0]}")/../src/shared/lib/smplos-session-env.sh" 2>/dev/null || {
    echo "  WARNING: smplos-session-env.sh not found — skipping session-scoped steps"
    smplos_have_session()  { return 1; }
    smplos_have_hyprland() { return 1; }
    smplos_have_user_bus() { return 1; }
    smplos_run_as_user()   { return 1; }
}

# ── Idempotency guards ───────────────────────────────────────────────────────
if pacman -Q eww-smplos &>/dev/null; then
    echo "  eww-smplos already installed — nothing to do"
    exit 0
fi

# ── Prerequisites ────────────────────────────────────────────────────────────
SMPLOS_PATH="${SMPLOS_PATH:-$HOME/.local/share/smplos}"
PKGBUILD_DIR="$SMPLOS_PATH/repo/src/shared/pkgbuilds/eww-smplos"

if [[ ! -f "$PKGBUILD_DIR/PKGBUILD" ]]; then
    echo "  WARNING: $PKGBUILD_DIR/PKGBUILD not found — skipping"
    echo "  Re-run smplos-migrate after the next 'Update OS'."
    exit 1
fi

# Bootstrap build tools if missing. On customer machines that never touched
# AUR, base-devel isn't installed and this migration silently no-op'd until
# we started exiting non-zero on missing deps. Install just what we need so
# the whole update is self-healing.
_need_bootstrap=()
command -v makepkg &>/dev/null || _need_bootstrap+=(base-devel)
command -v git     &>/dev/null || _need_bootstrap+=(git)
command -v curl    &>/dev/null || _need_bootstrap+=(curl)
if [[ ${#_need_bootstrap[@]} -gt 0 ]]; then
    echo "  Bootstrapping build tools: ${_need_bootstrap[*]}"
    if ! sudo pacman -S --needed --noconfirm "${_need_bootstrap[@]}"; then
        echo "  ERROR: could not install build tools — will retry on next update"
        exit 1
    fi
fi

for dep in makepkg git curl; do
    if ! command -v "$dep" &>/dev/null; then
        echo "  ERROR: $dep not found even after bootstrap — will retry on next update"
        exit 1
    fi
done

# Basic connectivity probe — git clone of the fork needs network.
if ! curl -fsSL --connect-timeout 5 --max-time 8 https://github.com >/dev/null 2>&1; then
    echo "  WARNING: no network — will retry on next update"
    exit 1
fi

# ── Build in a scratch dir owned by the invoking user ────────────────────────
BUILD_DIR=$(mktemp -d /tmp/eww-smplos-build.XXXXXX)
trap 'rm -rf "$BUILD_DIR"' EXIT

cp -a "$PKGBUILD_DIR/." "$BUILD_DIR/" || exit 1
cd "$BUILD_DIR"

# makepkg refuses to run as root. Migrations normally run as the invoking
# user, so a plain makepkg call is fine; guard against the rare case of a
# manual root run by falling back to a temp system user.
echo "  Building eww-smplos from source (this takes ~5-10 minutes)..."
if [[ $EUID -eq 0 ]]; then
    sudo useradd -m -r _ewwbuild 2>/dev/null || true
    sudo chown -R _ewwbuild:_ewwbuild "$BUILD_DIR"
    if ! sudo -u _ewwbuild bash -c "cd '$BUILD_DIR' && makepkg -s --noconfirm"; then
        echo "  ERROR: makepkg failed — will retry on next update"
        sudo userdel -r _ewwbuild 2>/dev/null || true
        exit 1
    fi
    sudo userdel -r _ewwbuild 2>/dev/null || true
else
    if ! PACMAN="${SMPLOS_UPDATE_PACMAN:-${PACMAN:-pacman}}" makepkg -s --noconfirm; then
        echo "  ERROR: makepkg failed — will retry on next update"
        exit 1
    fi
fi

# ── Install the freshly built package ────────────────────────────────────────
PKG_FILE=$(ls "$BUILD_DIR"/eww-smplos-*.pkg.tar.* 2>/dev/null | head -1)
if [[ ! -f "$PKG_FILE" ]]; then
    echo "  ERROR: makepkg produced no package file — will retry on next update"
    exit 1
fi

# ALPM question bit 4 accepts the declared eww conflict in this transaction.
# Never remove the working package in a separate transaction before installing.
if ! sudo pacman -U --noconfirm --ask 4 "$PKG_FILE"; then
    echo "  ERROR: eww replacement transaction failed; existing package retained"
    exit 1
fi

# Keep the old daemon alive if the replacement cannot load this host's libs.
source "$SMPLOS_PATH/repo/src/shared/lib/smplos-app-bundle.sh" || exit 1
smplos_app_linkage_valid /usr/bin/eww || exit 1

# ── Restart the bar so the user picks up the fixed binary immediately ────────
# SAFETY INVARIANT: never tear the bar down unless we can bring it back up.
#
# This block used to call `bar-ctl stop` + `bar-ctl start` unconditionally.
# Migrations run under pkexec, which strips XDG_RUNTIME_DIR and
# WAYLAND_DISPLAY, so `stop` closed the user's working bar and every `start`
# afterwards created its IPC socket under /tmp instead of /run/user/<uid> and
# then died with "Failed to initialize GTK" — no compositor to talk to. The
# user was left with no status bar and no way for the migration to restore it.
#
# Two changes: gate on smplos_have_session BEFORE touching anything, and run
# through smplos_run_as_user so the commands land in the real session.
#
# Also note `bar-ctl stop` only runs `eww close bar` — the daemon, and
# therefore the OLD eww binary, survives. Kill the daemon so the freshly
# installed eww-smplos is actually the process that comes back.
restart_bar() {
    local eww_config="${SMPLOS_SESSION_HOME:-$HOME}/.config/eww"
    smplos_run_as_user eww --config "$eww_config" kill &>/dev/null || true

    # Wait for the daemon to actually exit; starting while the old process is
    # still holding the socket would just re-attach us to the old binary.
    local waited=0
    while pgrep -x eww &>/dev/null && [[ $waited -lt 30 ]]; do
        sleep 0.1
        waited=$((waited + 1))
    done

    smplos_run_as_user bar-ctl start &>/dev/null
}

if ! command -v bar-ctl &>/dev/null; then
    echo "  bar-ctl not found — restart your bar to pick up eww-smplos"
elif ! smplos_have_session; then
    echo "  No graphical session detected — NOT restarting the bar"
    echo "  (tearing it down here would leave you with no bar until re-login)."
    echo "  Run 'bar-ctl start', or log out and back in, to load eww-smplos."
elif restart_bar; then
    echo "  Bar restarted with fixed eww binary"
else
    echo "  WARNING: bar restart failed — run 'bar-ctl start' to load eww-smplos"
    exit 1
fi

echo "  Installed eww-smplos $(pacman -Q eww-smplos 2>/dev/null | awk '{print $2}')"
exit 0
