#!/bin/bash
# Migration: Fix window positioning + add window-guard daemon
# Context: Hyprland 0.54 replaced the old '100%' percentage syntax in move
#          windowrules with expression variables (monitor_w, monitor_h, etc.).
#          All move rules using '100%' silently fail and windows get centered.
#          This migration updates windows.conf + autostart.conf and ensures
#          the new window-guard daemon is running.
#
# Affected apps: start-menu, notif-center, smpl-calendar, and all messengers
#                (signal, telegram, slack, discord, brave webapps).

set -euo pipefail

HYPR_DIR="$HOME/.config/hypr"
WINDOWS_CONF="$HYPR_DIR/windows.conf"
AUTOSTART_CONF="$HYPR_DIR/autostart.conf"
DISPLAY_CONF="$HOME/.config/smplos/display.conf"

n_changes=0

# ── 1. Fix move rules: 100% → monitor_w / monitor_h ──────────────────────────
if [[ -f "$WINDOWS_CONF" ]]; then
    if grep -q '100%' "$WINDOWS_CONF"; then
        # Replace 100% used in X-axis context (followed by -window_w or -NNN)
        # and Y-axis context (followed by -window_h or -NNN)
        # The repo source file is already correct, so just copy it
        REPO_SRC="${SMPLOS_PATH:-$HOME/.local/share/smplos}/repo/src/compositors/hyprland/hypr/windows.conf"
        if [[ -f "$REPO_SRC" ]]; then
            cp "$REPO_SRC" "$WINDOWS_CONF"
            echo "  Replaced windows.conf with corrected move rules (100% -> monitor_w/monitor_h)"
            ((n_changes++)) || true
        else
            # Fallback: in-place sed if repo file is not available
            sed -i \
                -e 's/move \(.*\)100%-window_w/move \1monitor_w-window_w/g' \
                -e 's/move \(.*\)100%-window_h/move \1monitor_h-window_h/g' \
                -e 's/move 100%-\([0-9]\)/move (monitor_w-\1/g' \
                -e 's/ 100%-\([0-9]\)/ (monitor_h-\1/g' \
                "$WINDOWS_CONF"
            # Add missing closing parens for the sed-converted expressions
            sed -i \
                -e 's/(monitor_w-\([0-9]*\)),/(monitor_w-\1),/g' \
                -e 's/(monitor_h-\([0-9]*\)),/(monitor_h-\1),/g' \
                "$WINDOWS_CONF"
            echo "  Patched windows.conf in-place (100% -> monitor_w/monitor_h)"
            ((n_changes++)) || true
        fi
    else
        echo "  windows.conf already uses monitor_w/monitor_h syntax"
    fi
else
    echo "  windows.conf not found — skipping"
fi

# ── 2. Add window-guard to autostart ─────────────────────────────────────────
if [[ -f "$AUTOSTART_CONF" ]]; then
    if ! grep -q 'window-guard' "$AUTOSTART_CONF"; then
        # Insert after bar-ctl start line
        if grep -q 'bar-ctl start' "$AUTOSTART_CONF"; then
            sed -i '/bar-ctl start/a\\n# Window guard — snap floating windows that end up off-screen back into view\nexec-once = window-guard' "$AUTOSTART_CONF"
        else
            # Fallback: append
            printf '\n# Window guard — snap floating windows that end up off-screen back into view\nexec-once = window-guard\n' >> "$AUTOSTART_CONF"
        fi
        echo "  Added window-guard to autostart.conf"
        ((n_changes++)) || true
    else
        echo "  window-guard already in autostart.conf"
    fi
else
    echo "  autostart.conf not found — skipping"
fi

# ── 3. Create display.conf with default settings ─────────────────────────────
if [[ ! -f "$DISPLAY_CONF" ]]; then
    mkdir -p "$(dirname "$DISPLAY_CONF")"
    echo "window_guard=true" > "$DISPLAY_CONF"
    echo "  Created display.conf with window_guard=true"
    ((n_changes++)) || true
else
    # Ensure window_guard key exists
    if ! grep -q '^window_guard=' "$DISPLAY_CONF"; then
        echo "window_guard=true" >> "$DISPLAY_CONF"
        echo "  Added window_guard=true to existing display.conf"
        ((n_changes++)) || true
    fi
fi

# ── 4. Start window-guard if not already running ─────────────────────────────
if command -v window-guard &>/dev/null; then
    if ! pgrep -f 'window-guard' &>/dev/null; then
        bash -c 'window-guard &' 2>/dev/null
        echo "  Started window-guard daemon"
        ((n_changes++)) || true
    else
        echo "  window-guard already running"
    fi
fi

# ── 5. Reload Hyprland to pick up windows.conf changes ───────────────────────
if command -v hyprctl &>/dev/null && [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
    hyprctl reload &>/dev/null && echo "  Reloaded Hyprland config"
fi

if [[ $n_changes -eq 0 ]]; then
    echo "  Already up to date, nothing to do"
else
    echo "  Applied $n_changes change(s)"
fi
