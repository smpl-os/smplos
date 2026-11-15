#!/bin/bash
# SMPLOS_UPDATE_PRIORITY=core
# Repair palette-selected missing icons and retire global GTK theme overrides.
set -euo pipefail

lib="$(dirname "${BASH_SOURCE[0]}")/../src/shared/lib"
source "$lib/smplos-session-env.sh"

missing=()
for package in adwaita-icon-theme hicolor-icon-theme; do
    pacman -Q "$package" &>/dev/null || missing+=("$package")
done
if (( ${#missing[@]} )); then
    if [[ "${SMPLOS_SYSTEM_UPGRADED:-0}" != 1 ]]; then
        echo "  GTK icon package installation deferred until the full system upgrade"
        exit 75
    fi
    pkexec pacman -S --needed --noconfirm "${missing[@]}"
    for package in "${missing[@]}"; do
        pacman -Q "$package"
    done
fi

if ! smplos_have_user_bus; then
    echo "  GTK preference repair deferred until the user's desktop bus is available"
    exit 75
fi
mode=--dark
[[ ! -f "$HOME/.config/smplos/current/theme/light.mode" ]] || mode=--light
smplos_run_as_user python3 "$lib/smplos-gtk.py" "$mode"
echo "  Standard GTK defaults repaired; theme-set clears session overrides during finalization"
