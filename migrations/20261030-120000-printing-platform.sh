#!/bin/bash
# SMPLOS_UPDATE_PRIORITY=core
# Enroll missing printing support without editing printers, jobs or network policy.
set -euo pipefail

state="${XDG_STATE_HOME:-$HOME/.local/state}/smplos/printing-enrollment"
packages=(cups cups-filters python-pycups avahi)
missing=()
for package in "${packages[@]}"; do
    pacman -Q "$package" >/dev/null 2>&1 || missing+=("$package")
done
if (( ${#missing[@]} )); then
    if [[ "${SMPLOS_SYSTEM_UPGRADED:-0}" != 1 ]]; then
        echo "  Printing support deferred until the full system upgrade"
        exit 75
    fi
    # Record before installing so a failed service enrollment remains retryable.
    # Existing packages' disabled/masked services are deliberately preserved.
    mkdir -p "$state"
    for package in "${missing[@]}"; do
        case "$package" in
            cups) touch "$state/cups.socket" ;;
            avahi) touch "$state/avahi-daemon.service" ;;
        esac
    done
    # The per-update executable embeds dependency-aware pins/holds and its
    # transaction plan; pkexec need not preserve caller environment variables.
    pkexec "${SMPLOS_UPDATE_PACMAN:-/usr/bin/pacman}" -S --needed --noconfirm "${missing[@]}"
    for package in "${packages[@]}"; do
        pacman -Q "$package" >/dev/null
    done
fi

for unit in cups.socket avahi-daemon.service; do
    [[ -f "$state/$unit" ]] || continue
    if [[ "$(systemctl is-enabled "$unit" 2>/dev/null || true)" == masked* ]]; then
        echo "  Printing service $unit is masked; preserving explicit policy"
        continue
    fi
    pkexec systemctl enable --now "$unit"
    systemctl is-active --quiet "$unit"
    rm -- "$state/$unit"
done
echo "  Printing platform installed; existing queues/defaults/jobs and service opt-outs preserved"
