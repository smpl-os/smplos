#!/bin/bash
# Migration: Macro keypad support (CH552 keypads, Settings > Keypad).
#
# Context: smplOS gained support for cheap CH552 macro keypads (USB 1189:8890):
#          udev access + hotplug rules, the control-surface user unit, an EWW
#          tray icon and the keypad-ctl helper. See KEYPAD.md.
#
#          smplos-os-update already delivers keypad-ctl (sync_scripts), the
#          EWW widget/listener (sync_configs) and drops the unit file when the
#          user has none. Three things need a one-time action:
#            1. The udev rules must reach /etc/udev/rules.d (root).
#            2. The new tray icons must be baked with the current theme
#               (theme-set only bakes templates it already has).
#            3. The user unit must be enabled. A different unit of the same
#               name (e.g. a developer install of control-surface) is left
#               alone and not enabled: it may lack the keypad-present condition.
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
WANTS="$UNIT_DIR/graphical-session.target.wants/$UNIT_NAME"

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
    # Re-apply access only to connected keypads and /dev/uinput, not every device.
    for dev in "$SYSFS"/*; do
        [[ "$(cat "$dev/idVendor" 2>/dev/null)" == 1189 && "$(cat "$dev/idProduct" 2>/dev/null)" == 8890 ]] || continue
        sudo udevadm trigger --action=change --parent-match="$(readlink -f "$dev")" 2>/dev/null || true
    done
    sudo udevadm trigger --action=change /sys/devices/virtual/misc/uinput 2>/dev/null || true
fi

# ── 2. Tray icons: templates + bake with the current theme's accent ──────────
TPL_DIR="$HOME/.local/share/smplos/icons/status"
EWW_ICONS="$HOME/.config/eww/icons/status"
accent=$(grep '^accent' "$HOME/.config/smplos/current/theme/colors.toml" 2>/dev/null | head -1 | sed 's/.*"\(#[^"]*\)".*/\1/' || true)
for icon in keypad.svg keypad-bootloader.svg; do
    src="$REPO/src/shared/icons/status/$icon"
    [[ -f "$src" ]] || continue
    if ! cmp -s "$src" "$TPL_DIR/$icon" 2>/dev/null; then
        mkdir -p "$TPL_DIR"
        cp "$src" "$TPL_DIR/$icon"
        changed "Installed icon template $icon"
    fi
    if [[ -d "$EWW_ICONS" || -d "$HOME/.config/eww" ]]; then
        mkdir -p "$EWW_ICONS"
        baked=$(sed "s/{{accent}}/${accent:-#888888}/g" "$src")
        if [[ "$baked" != "$(cat "$EWW_ICONS/$icon" 2>/dev/null)" ]]; then
            printf '%s\n' "$baked" > "$EWW_ICONS/$icon"
            changed "Baked tray icon $icon"
        fi
    fi
done

# ── 3. Install + enable the user unit ────────────────────────────────────────
if [[ ! -f "$UNIT_SRC" ]]; then
    echo "  $UNIT_NAME not found in repo, skipping"
else
    if [[ ! -f "$UNIT" ]]; then
        mkdir -p "$UNIT_DIR"
        cp "$UNIT_SRC" "$UNIT"
        changed "Installed $UNIT_NAME"
    fi
    if ! cmp -s "$UNIT_SRC" "$UNIT"; then
        echo "  $UNIT is a custom unit; left as is and not enabled"
    elif [[ -L "$WANTS" ]]; then
        echo "  $UNIT_NAME already enabled"
    else
        mkdir -p "$(dirname "$WANTS")"
        ln -sf "../$UNIT_NAME" "$WANTS"
        changed "Enabled $UNIT_NAME (starts while a keypad is plugged in)"
        # Best effort for the running session; inert without the daemon/keypad.
        if smplos_have_user_bus; then
            smplos_run_as_user systemctl --user daemon-reload 2>/dev/null || true
            smplos_run_as_user systemctl --user start "$UNIT_NAME" 2>/dev/null || true
        fi
    fi
fi

if [[ $n_changes -gt 0 ]]; then
    echo "  Macro keypad support configured ($n_changes change(s))"
else
    echo "  Macro keypad support already configured"
fi
