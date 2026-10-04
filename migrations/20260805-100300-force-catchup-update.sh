#!/bin/bash
# Migration: One-click fleet catch-up — force pacman -Syu with the FRESH
#            critical-packages.txt ignore list + apply the current bundle
#            baseline (linux-lts, nvidia-open-dkms, kernel-modules-hook,
#            xdg-desktop-portal-hyprland, hyprland=0.56.0-2).
#
# Context: smplos-update loads critical-packages.txt into memory at line
#          ~296 (load_critical_packages) BEFORE it calls smplos-os-update
#          (which does the `git pull` that refreshes the file on disk).
#          Result: on ANY given "Update OS" click, the pacman -Syu ignore
#          list used is the STALE version from the PREVIOUS click. New
#          entries — or in our case, the newly-slimmed ignore list — only
#          take effect two clicks later. That is exactly the reason a
#          customer machine can click Update OS repeatedly and still not
#          upgrade hyprland, mesa, linux-lts, etc.
#
#          Migrations run FRESH from the just-pulled repo, so this
#          migration:
#            1. Reads the FRESH critical-packages.txt to build the current
#               --ignore list.
#            2. Re-runs `pacman -Syu` with that fresh list, catching up any
#               packages the parent smplos-update skipped with its stale
#               list. In particular this rolls forward the packages that
#               used to be frozen: kernels, microcode, nvidia stack,
#               mkinitcpio (which triggers initramfs rebuild for the NVIDIA
#               suspend/resume fix), grub, mesa, xdg-desktop-portal (base),
#               hyprpaper/hypridle/hyprlock, hyprsunset/hyprpicker.
#            3. Applies the current critical-bundle.conf baseline via
#               `pacman -S --needed`. This covers customers whose installed
#               smplos-update predates the bundle-prompt logic (introduced
#               fd2944e, 2026-06-28) and would otherwise never install
#               linux-lts / nvidia-open-dkms / kernel-modules-hook /
#               xdg-desktop-portal-hyprland / the hyprland=0.56.0-2 pin.
#            4. Writes the bundle-applied marker so post-fd2944e customers'
#               smplos-update doesn't then prompt for the same bundle.
#            5. Rebuilds the initramfs so the NVIDIA modprobe options
#               (see 20260701-011500-nvidia-suspend-resume.sh) load early.
#
# Safety: every step is idempotent and exits 0 on failure so downstream
#         migrations still run. Skips gracefully offline.

set -uo pipefail

SMPLOS_PATH="${SMPLOS_PATH:-$HOME/.local/share/smplos}"
POLICY_DIR="$SMPLOS_PATH/repo/src/shared/update-policy"
CRITICAL_LIST_FILE="$POLICY_DIR/critical-packages.txt"
CRITICAL_BUNDLE_FILE="$POLICY_DIR/critical-bundle.conf"
STATE_DIR="$HOME/.local/state/smplos/update"
APPLIED_BUNDLE_FILE="$STATE_DIR/critical-bundle-applied"

# ── Prerequisites ────────────────────────────────────────────────────────────
if [[ ! -f "$CRITICAL_LIST_FILE" ]] || [[ ! -f "$CRITICAL_BUNDLE_FILE" ]]; then
    echo "  WARNING: update-policy files missing at $POLICY_DIR — skipping"
    exit 0
fi

if ! curl -fsSL --connect-timeout 5 --max-time 8 https://archlinux.org >/dev/null 2>&1; then
    echo "  WARNING: no network — skipping (will retry on next smplos-migrate)"
    exit 0
fi

fix_qemu_gluster_blocker() {
    if ! pacman -Qq qemu-block-gluster >/dev/null 2>&1; then
        return 0
    fi

    echo "  Checking qemu-block-gluster update blocker..."
    sudo pacman -Sy --noconfirm >/dev/null 2>&1 || {
        echo "  WARNING: could not refresh package database before QEMU preflight"
        return 0
    }

    if ! pacman -Si qemu-common 2>/dev/null | grep -qE '^Conflicts With.*qemu-block-gluster'; then
        echo "  qemu-block-gluster does not conflict with current qemu-common"
        return 0
    fi

    if pacman -Qq qemu-full >/dev/null 2>&1; then
        echo "  Removing old qemu-full meta-package and obsolete qemu-block-gluster"
        if sudo pacman -R --noconfirm qemu-full qemu-block-gluster; then
            sudo pacman -S --needed --noconfirm qemu-full \
                && echo "  Restored qemu-full meta-package without qemu-block-gluster" \
                || echo "  WARNING: qemu-full restore failed; concrete QEMU packages remain installed"
        else
            echo "  WARNING: could not remove qemu-full/qemu-block-gluster"
        fi
    elif sudo pacman -R --noconfirm qemu-block-gluster; then
        echo "  Removed obsolete qemu-block-gluster"
    else
        echo "  WARNING: could not remove qemu-block-gluster"
    fi
}

# ── 1. Build fresh ignore list from the just-pulled critical-packages.txt ────
FRESH_IGNORE_ARR=()
while IFS= read -r line; do
    line="${line%%#*}"
    line="${line//[[:space:]]/}"
    [[ -z "$line" ]] && continue
    FRESH_IGNORE_ARR+=("$line")
done < "$CRITICAL_LIST_FILE"

# Comma-join for pacman --ignore.
FRESH_IGNORE=""
for p in "${FRESH_IGNORE_ARR[@]}"; do
    FRESH_IGNORE="${FRESH_IGNORE:+$FRESH_IGNORE,}$p"
done
echo "  Fresh ignore list: ${FRESH_IGNORE:-<empty>}"

# ── 2. Second-pass pacman -Syu with the fresh (short) ignore list ────────────
# This catches every package the parent smplos-update skipped with its
# stale in-memory ignore list.
fix_qemu_gluster_blocker
echo "  Running pacman -Syu with fresh ignore list..."
_syu_ok=1
if [[ -n "$FRESH_IGNORE" ]]; then
    if ! sudo pacman -Syu --noconfirm --ignore "$FRESH_IGNORE"; then
        echo "  WARNING: catch-up pacman -Syu failed"
        _syu_ok=0
    fi
else
    if ! sudo pacman -Syu --noconfirm; then
        echo "  WARNING: catch-up pacman -Syu failed"
        _syu_ok=0
    fi
fi

# ── 3. Apply critical-bundle.conf baseline ───────────────────────────────────
# Parse BUNDLE_ID and PACKAGES out of the conf file in a sandboxed subshell so
# nothing else in the migration script gets tainted by variable expansion.
_bundle_meta=$(
    # shellcheck disable=SC1090
    . "$CRITICAL_BUNDLE_FILE" 2>/dev/null || true
    printf '%s\n%s\n' "${BUNDLE_ID:-}" "${PACKAGES:-}"
)
BUNDLE_ID=$(printf '%s' "$_bundle_meta" | sed -n '1p')
BUNDLE_PACKAGES=$(printf '%s' "$_bundle_meta" | sed -n '2p')

_bundle_ok=1
if [[ $_syu_ok -eq 0 ]]; then
    # Arch builds the stack against the current system libraries (e.g. a newer
    # libstdc++ symbol version that pacman does not track). Installing it on a
    # partially updated system can leave Hyprland unable to start.
    echo "  Skipping critical bundle: the system upgrade above did not complete"
    _bundle_ok=0
elif [[ -z "$BUNDLE_ID" ]] || [[ -z "$BUNDLE_PACKAGES" ]]; then
    echo "  ERROR: could not parse critical-bundle.conf — will retry on next update"
    _bundle_ok=0
else
    # shellcheck disable=SC2086
    read -ra _bundle_arr <<< "$BUNDLE_PACKAGES"
    echo "  Applying critical bundle $BUNDLE_ID (${#_bundle_arr[@]} packages)..."
    if sudo pacman -S --noconfirm --needed "${_bundle_arr[@]}"; then
        echo "  Bundle applied"
        # ── 4. Write bundle marker ───────────────────────────────────────────
        mkdir -p "$STATE_DIR"
        printf '%s\n' "$BUNDLE_ID" > "$APPLIED_BUNDLE_FILE"
        echo "  Marked bundle $BUNDLE_ID as applied"
    else
        echo "  ERROR: bundle apply failed — will retry on next update"
        _bundle_ok=0
    fi
fi

# ── 5. Rebuild initramfs so NVIDIA modprobe options take effect ──────────────
# The nvidia-suspend-resume migration writes /etc/modprobe.d/nvidia.conf, but
# if the kernel was frozen for months, the initramfs may still be stale. This
# is a cheap belt-and-suspenders — mkinitcpio is a no-op when everything's
# already current.
if lspci 2>/dev/null | grep -qi 'nvidia' && command -v mkinitcpio &>/dev/null; then
    echo "  Rebuilding initramfs to pick up NVIDIA power-management options..."
    if ! sudo mkinitcpio -P >/dev/null 2>&1; then
        echo "  WARNING: mkinitcpio -P failed — run manually before next reboot"
    fi
fi

# Exit non-zero if either the catch-up sync OR the bundle apply failed, so
# smplos-migrate leaves this migration unmarked and retries on the next
# Update OS click. The old behavior of exit 0 masked failures and the whole
# fleet appeared "done" while still stale on hyprland / linux-lts / nvidia.
if [[ $_syu_ok -eq 0 || $_bundle_ok -eq 0 ]]; then
    echo "  Fleet catch-up encountered errors — will retry on next update."
    exit 1
fi

echo "  Fleet catch-up complete."
exit 0
