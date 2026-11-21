#!/bin/bash
# Reconcile the stock keypad unit with the bar backend bridge.
set -euo pipefail

SMPLOS_PATH="${SMPLOS_PATH:-$HOME/.local/share/smplos}"
REPO="${SMPLOS_REPO:-$SMPLOS_PATH/repo}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/smplos/keypad-units"

source "$REPO/src/shared/lib/smplos-keypad-units.sh"
source "$REPO/src/shared/lib/smplos-session-env.sh"

smplos_keypad_sync_units \
    "$REPO/src/shared/configs/systemd/user" "$UNIT_DIR" "$UNIT_STATE"

if [[ $SMPLOS_KEYPAD_UNITS_CHANGED -eq 1 ]]; then
    echo "  Native bar keypad bridge installed; custom units remain untouched"
    if smplos_have_user_bus; then
        smplos_run_as_user systemctl --user daemon-reload
    fi
fi
