#!/bin/bash
# Stop the retired EWW bar process without uninstalling eww-smplos or deleting
# the user's ~/.config/eww directory.
set -uo pipefail

SMPLOS_PATH="${SMPLOS_PATH:-$HOME/.local/share/smplos}"
source "$SMPLOS_PATH/repo/src/shared/lib/smplos-session-env.sh" 2>/dev/null || true

if declare -F smplos_run_as_user >/dev/null; then
    smplos_run_as_user sh -c \
        'command -v eww >/dev/null 2>&1 && eww --config "$HOME/.config/eww" kill >/dev/null 2>&1 || true'
    smplos_run_as_user bar-ctl ensure
else
    command -v eww >/dev/null 2>&1 &&
        eww --config "$HOME/.config/eww" kill >/dev/null 2>&1 || true
    bar-ctl ensure
fi
