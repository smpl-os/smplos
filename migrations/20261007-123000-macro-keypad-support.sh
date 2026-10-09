#!/bin/bash
# Migration: Macro keypad support (CH552 keypads, Settings > Keypad).
#
# Context: smplOS supports cheap CH552 macro keypads (USB 1189:8890): udev
#          rules, the control-surface user unit, a bar icon and keypad-ctl.
#          See KEYPAD.md.
#
#          Nothing keypad related runs while no keypad is plugged in: udev
#          starts control-surface.service on plug-in, BindsTo= stops it on
#          unplug, and the bar icon is an EWW variable the unit sets.
#
#          smplos-os-update already delivers keypad-ctl (sync_scripts), the EWW
#          config (sync_configs) and drops the unit file when the user has none.
#          This migration does what those generic steps can't:
#            1. Install the udev rules into /etc/udev/rules.d (root).
#            2. Bake the tray icon with the current theme (theme-set only bakes
#               templates it already has).
#            3. Update an unmodified earlier smplOS unit, and remove an old
#               enablement link: the unit must not start at login on its own.
#               Any other unit of the same name (e.g. a developer install of
#               control-surface) is left alone.
#
#            4. Install (or update) the keypad app, the control-surface
#               package: a pinned smpl-apps release asset, packaged by
#               src/shared/pkgbuilds/control-surface. Fresh installs get it
#               from the ISO. Nothing runs until a keypad is plugged in; the
#               unit's ConditionPathExists keeps it inert until it's there.
#               Validate its runtime before changing working keypad units.
#
# Safe to re-run: every step checks state before acting. If the package can't
# be installed now (offline or incompatible runtime), rules/icons are updated,
# working units are preserved, and the migration defers (exit 75) for retry.

set -euo pipefail

# shellcheck source=../src/shared/lib/smplos-session-env.sh
source "$(dirname "${BASH_SOURCE[0]}")/../src/shared/lib/smplos-session-env.sh" 2>/dev/null || {
    echo "  WARNING: smplos-session-env.sh not found — skipping session-scoped steps"
    smplos_have_session()  { return 1; }
    smplos_have_hyprland() { return 1; }
    smplos_have_user_bus() { return 1; }
    smplos_run_as_user()   { return 1; }
}

SMPLOS_PATH="${SMPLOS_PATH:-$HOME/.local/share/smplos}"
REPO="${SMPLOS_REPO:-$SMPLOS_PATH/repo}"
UDEV_DIR="${SMPLOS_UDEV_RULES_DIR:-/etc/udev/rules.d}"
SYSFS="${SMPLOS_KEYPAD_SYSFS:-/sys/bus/usb/devices}"
UINPUT_SYSFS="${SMPLOS_KEYPAD_UINPUT_SYSFS:-/sys/devices/virtual/misc/uinput}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/smplos/keypad-units"
source "$REPO/src/shared/lib/smplos-keypad-units.sh"

n_changes=0
changed() { echo "  $*"; ((n_changes++)) || true; }

# ── 1. udev rules → /etc/udev/rules.d (+ targeted reload) ────────────────────
rules_changed=0
# 70-smplos-keypads.rules is generated from src/shared/keypads/registry.json.
# It replaces an earlier draft's two files, removed when they are ours.
for rule in 70-ch552-macropad.rules 71-wch-isp-bootloader.rules; do
    if [[ -f "$UDEV_DIR/$rule" ]] && grep -q 'KEYPAD.md' "$UDEV_DIR/$rule"; then
        backup=$(sudo mktemp -d "$UDEV_DIR/smplos-keypad-backup.XXXXXX")
        sudo cp -a "$UDEV_DIR/$rule" "$backup/$rule"
        sudo cmp -s "$UDEV_DIR/$rule" "$backup/$rule"
        sudo rm "$UDEV_DIR/$rule"
        changed "Removed $rule (replaced by 70-smplos-keypads.rules)"
        rules_changed=1
    fi
done
for rule in 70-smplos-keypads.rules; do
    src="$REPO/src/shared/system/udev/$rule"
    dst="$UDEV_DIR/$rule"
    if [[ ! -f "$src" ]]; then
        echo "  ERROR: $rule not found in repo" >&2
        exit 1
    elif [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
        echo "  $rule already current"
    else
        if [[ -e "$dst" ]]; then
            backup=$(sudo mktemp -d "$UDEV_DIR/smplos-keypad-backup.XXXXXX")
            sudo cp -a "$dst" "$backup/$rule"
            sudo cmp -s "$dst" "$backup/$rule"
        fi
        sudo install -Dm644 "$src" "$dst"
        changed "Installed udev rule $rule"
        rules_changed=1
    fi
done
if [[ $rules_changed -eq 1 ]]; then
    sudo udevadm control --reload-rules
    # Re-apply the rules only to connected keypads and /dev/uinput, not every device.
    for dev in "$SYSFS"/*; do
        [[ "$(cat "$dev/idVendor" 2>/dev/null)" == 1189 && "$(cat "$dev/idProduct" 2>/dev/null)" == 8890 ]] || continue
        sudo udevadm trigger --action=change --parent-match="$(readlink -f "$dev")"
    done
    # No node exists before the uinput module loads; the rule still covers it.
    if [[ -e "$UINPUT_SYSFS" ]]; then
        sudo udevadm trigger --action=change "$UINPUT_SYSFS"
    fi
fi

# ── 2. Tray icon: template + bake with the current theme's accent ─────────────
TPL_DIR="$HOME/.local/share/smplos/icons/status"
EWW_ICONS="$HOME/.config/eww/icons/status"
accent=$(grep '^accent' "$HOME/.config/smplos/current/theme/colors.toml" 2>/dev/null | head -1 | sed 's/.*"\(#[^"]*\)".*/\1/' || true)
src="$REPO/src/shared/icons/status/keypad.svg"
if [[ -f "$src" ]]; then
    if ! cmp -s "$src" "$TPL_DIR/keypad.svg" 2>/dev/null; then
        mkdir -p "$TPL_DIR"
        cp "$src" "$TPL_DIR/keypad.svg"
        changed "Installed icon template keypad.svg"
    fi
    if [[ -d "$HOME/.config/eww" ]]; then
        mkdir -p "$EWW_ICONS"
        baked=$(sed "s/{{accent}}/${accent:-#888888}/g" "$src")
        if [[ "$baked" != "$(cat "$EWW_ICONS/keypad.svg" 2>/dev/null)" ]]; then
            printf '%s\n' "$baked" > "$EWW_ICONS/keypad.svg"
            changed "Baked tray icon keypad.svg"
        fi
    fi
fi

# ── 3. The keypad app: deliver and validate before switching units ──────────
deferred=0
PKG_DIR="$REPO/src/shared/pkgbuilds/control-surface"
want=$(sed -n 's/^pkgver=//p' "$PKG_DIR/PKGBUILD" 2>/dev/null | head -1 || true)
# shellcheck source=../src/shared/lib/smplos-pkgbuild.sh
if [[ -z "$want" ]] || ! source "$REPO/src/shared/lib/smplos-pkgbuild.sh" 2>/dev/null; then
    echo "  ERROR: control-surface package recipe or installer not found in repo" >&2
    exit 1
else
    have=$(smplos_pkg_version control-surface)
    if [[ -n "$have" ]] && (( $(vercmp "$have" "$want") >= 0 )); then
        echo "  control-surface $have already installed"
    elif smplos_pkgbuild_install "$PKG_DIR"; then
        changed "Installed control-surface $(smplos_pkg_version control-surface) (the keypad app)"
    else
        echo "  Could not install control-surface now; will retry on the next update"
        deferred=1
    fi
fi

if [[ $deferred -eq 1 ]]; then
    echo "  Existing keypad units retained until the package is available"
    exit 75
fi
if ! smplos_keypad_check_runtime "${SMPLOS_KEYPAD_DAEMON:-/usr/bin/control-surfaced}"; then
    echo "  ERROR: packaged keypad app cannot run with this system's runtime; existing units retained. Retry Update OS after a compatible release/runtime is available." >&2
    exit 75
fi

# ── 4. User units: install or update ours, never enable the daemon ───────────
smplos_keypad_sync_units "$REPO/src/shared/configs/systemd/user" "$UNIT_DIR" "$UNIT_STATE"
if [[ $SMPLOS_KEYPAD_UNITS_CHANGED -eq 1 ]]; then
    changed "Keypad user units reconciled (custom units and mappings preserved)"
    if smplos_have_user_bus; then
        smplos_run_as_user systemctl --user daemon-reload
    fi
fi

if [[ $n_changes -gt 0 ]]; then
    echo "  Macro keypad support configured ($n_changes change(s))"
else
    echo "  Macro keypad support already configured"
fi
