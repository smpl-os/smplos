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
#            3. Update a unit file that an earlier smplOS version installed
#               (recognised by its Documentation= line), and remove an old
#               enablement link: the unit must not start at login on its own.
#               Any other unit of the same name (e.g. a developer install of
#               control-surface) is left alone.
#
#          The daemon itself arrives as the control-surface package; the unit's
#          ConditionPathExists keeps it inert until then.
#
# Safe to re-run: every step checks state before acting.

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
UNIT_NAME=control-surface.service
UNIT_SRC="$REPO/src/shared/configs/systemd/user/$UNIT_NAME"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/$UNIT_NAME"
OURS="Documentation=https://github.com/smpl-os/smplos/blob/main/KEYPAD.md"

n_changes=0
changed() { echo "  $*"; ((n_changes++)) || true; }

# ── 1. udev rules → /etc/udev/rules.d (+ targeted reload) ────────────────────
rules_changed=0
for rule in 70-ch552-macropad.rules 71-wch-isp-bootloader.rules; do
    src="$REPO/src/shared/system/udev/$rule"
    dst="$UDEV_DIR/$rule"
    if [[ ! -f "$src" ]]; then
        echo "  $rule not found in repo, skipping"
    elif [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
        echo "  $rule already current"
    elif sudo install -Dm644 "$src" "$dst" 2>/dev/null; then
        changed "Installed udev rule $rule"
        rules_changed=1
    else
        echo "  WARNING: could not install $rule (sudo required)"
    fi
done
if [[ $rules_changed -eq 1 ]]; then
    sudo udevadm control --reload-rules 2>/dev/null || true
    # Re-apply the rules only to connected keypads and /dev/uinput, not every device.
    for dev in "$SYSFS"/*; do
        [[ "$(cat "$dev/idVendor" 2>/dev/null)" == 1189 && "$(cat "$dev/idProduct" 2>/dev/null)" == 8890 ]] || continue
        sudo udevadm trigger --action=change --parent-match="$(readlink -f "$dev")" 2>/dev/null || true
    done
    sudo udevadm trigger --action=change /sys/devices/virtual/misc/uinput 2>/dev/null || true
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

# ── 3. User unit: install or update ours, never enable it ────────────────────
if [[ ! -f "$UNIT_SRC" ]]; then
    echo "  $UNIT_NAME not found in repo, skipping"
elif [[ -f "$UNIT" ]] && ! grep -qxF "$OURS" "$UNIT"; then
    echo "  $UNIT is a custom unit; left as is"
else
    if ! cmp -s "$UNIT_SRC" "$UNIT" 2>/dev/null; then
        mkdir -p "$UNIT_DIR"
        cp "$UNIT_SRC" "$UNIT"
        changed "Installed $UNIT_NAME (started by udev while a keypad is plugged in)"
    fi
    for wants in "$UNIT_DIR"/*.wants/"$UNIT_NAME"; do
        [[ -L "$wants" ]] || continue
        rm -f "$wants"
        changed "Removed the old login start of $UNIT_NAME (${wants#"$UNIT_DIR"/})"
    done
    if [[ $n_changes -gt 0 ]] && smplos_have_user_bus; then
        smplos_run_as_user systemctl --user daemon-reload 2>/dev/null || true
    fi
fi

if [[ $n_changes -gt 0 ]]; then
    echo "  Macro keypad support configured ($n_changes change(s))"
else
    echo "  Macro keypad support already configured"
fi
