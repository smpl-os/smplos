#!/bin/bash
# Migration: Enable the VITURE XR glasses module on existing installs.
#
# Context: smplOS gained the xr-workspace virtual-monitor renderer + its
#          auto-launch glue (udev uaccess rule, xr-glasses.service user unit,
#          Hyprland keybinds, default config, Settings → Glasses tab).
#
#          Fresh installs get all of this from /etc/skel via the ISO builder.
#          Existing installs receive the *files* automatically through
#          smplos-os-update:
#            - systemd user unit + default config → sync_configs
#            - Hyprland snippet + source line     → sync_hypr_configs
#          ...but two things still need an explicit, one-time action that the
#          generic sync steps do not perform:
#            1. The udev rule must be copied into /etc/udev/rules.d and the
#               udev DB reloaded (system file, needs root).
#            2. The user service must be *enabled* (sync only drops the file).
#
#          This migration does exactly that, idempotently. The renderer binary
#          itself arrives via smplos-update-apps; the service carries
#          ConditionPathExists=/usr/local/bin/xr-glasses-hotplugd so enabling it
#          before the binary lands is harmless (it simply stays inert).
#
# Safe to re-run: every step checks state before acting.

set -euo pipefail

SMPLOS_PATH="${SMPLOS_PATH:-$HOME/.local/share/smplos}"
REPO="$SMPLOS_PATH/repo"

n_changes=0

# ── 1. udev rule → /etc/udev/rules.d (+ reload) ──────────────────────────────
UDEV_SRC="$REPO/src/shared/system/udev/99-viture-xr.rules"
UDEV_DST="/etc/udev/rules.d/99-viture-xr.rules"
if [[ -f "$UDEV_SRC" ]]; then
    if [[ ! -f "$UDEV_DST" ]] || ! sudo cmp -s "$UDEV_SRC" "$UDEV_DST" 2>/dev/null; then
        if sudo install -Dm644 "$UDEV_SRC" "$UDEV_DST" 2>/dev/null; then
            sudo udevadm control --reload-rules 2>/dev/null || true
            sudo udevadm trigger --subsystem-match=usb 2>/dev/null || true
            echo "  Installed VITURE udev rule + reloaded udev"
            ((n_changes++)) || true
        else
            echo "  WARNING: could not install udev rule (sudo required)"
        fi
    else
        echo "  udev rule already current"
    fi
else
    echo "  udev rule not found in repo, skipping"
fi

# ── 2. Enable the xr-glasses user service ────────────────────────────────────
# sync_configs already dropped the unit file at ~/.config/systemd/user/. We just
# need to enable it so it auto-starts. enable (without --now) writes the wants
# symlink and survives reboots; --now is best-effort for the live session.
UNIT="$HOME/.config/systemd/user/xr-glasses.service"
WANTS="$HOME/.config/systemd/user/default.target.wants/xr-glasses.service"
if [[ -f "$UNIT" ]]; then
    if [[ ! -L "$WANTS" ]]; then
        if command -v systemctl &>/dev/null; then
            systemctl --user daemon-reload 2>/dev/null || true
            if systemctl --user enable xr-glasses.service 2>/dev/null; then
                echo "  Enabled xr-glasses.service (auto-starts on login)"
            else
                # Fall back to a manual wants symlink if there is no user bus
                # (e.g. running inside the elevated updater with no session).
                mkdir -p "$(dirname "$WANTS")"
                ln -sf ../xr-glasses.service "$WANTS"
                echo "  Linked xr-glasses.service into default.target.wants"
            fi
            # Best-effort immediate start (no-op while the binary is absent).
            systemctl --user start xr-glasses.service 2>/dev/null || true
            ((n_changes++)) || true
        else
            mkdir -p "$(dirname "$WANTS")"
            ln -sf ../xr-glasses.service "$WANTS"
            echo "  Linked xr-glasses.service into default.target.wants"
            ((n_changes++)) || true
        fi
    else
        echo "  xr-glasses.service already enabled"
    fi
else
    echo "  xr-glasses.service unit not present yet (will be synced), skipping enable"
fi

# ── 3. Ensure Hyprland sources the xr-workspace snippet ──────────────────────
# sync_hypr_configs already refreshes hyprland.conf from the repo (which carries
# the source line). This is belt-and-suspenders for hand-customised configs.
HYPR_CONF="$HOME/.config/hypr/hyprland.conf"
if [[ -f "$HYPR_CONF" ]]; then
    if ! grep -q 'xr-workspace.conf' "$HYPR_CONF"; then
        printf '\n# XR glasses (VITURE) integration\nsource = ~/.config/hypr/xr-workspace.conf\n' >> "$HYPR_CONF"
        echo "  Added xr-workspace.conf source line to hyprland.conf"
        ((n_changes++)) || true
    else
        echo "  hyprland.conf already sources xr-workspace.conf"
    fi
fi

# ── 4. If glasses are already plugged in, start the workspace now ─────────────
# Best-effort: only when the binary exists and a VITURE device is present.
if command -v xr-glasses-hotplugd &>/dev/null; then
    if grep -riqs '35ca' /sys/bus/usb/devices/*/idVendor 2>/dev/null; then
        echo "  VITURE device detected — starting watcher once"
        xr-glasses-hotplugd --once 2>/dev/null || true
    fi
fi

if [[ $n_changes -gt 0 ]]; then
    echo "  XR glasses module enabled ($n_changes change(s))"
else
    echo "  XR glasses module already configured"
fi
