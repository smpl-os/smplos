#!/bin/bash
# Migration: Remove 32-bit GStreamer packages that Arch dropped from multilib.
#
# Context: Arch removed lib32-gstreamer, its lib32-gst-plugins-* packages and
#          the lib32-libcap/pam/audit/libnsl/libtirpc chain they pulled in
#          (lib32-libnsl pins libnsl=2.0.1 the same way). The
#          leftover lib32-audit pins audit=4.1.4, so `pacman -Syu --noconfirm`
#          aborts ("installing audit (4.2.1-1) breaks dependency 'audit=4.1.4'
#          required by lib32-audit") and every regular system update fails.
# Safety:  Removes only packages from that list that are installed and no
#          longer provided by any sync repository. Another installed package
#          may still require one of them only if its current repository
#          version no longer does (old lib32-systemd needed lib32-libcap); the
#          system update right after the migrations upgrades it. Otherwise
#          nothing is removed and the migration is deferred (exit 75), so a
#          refusal never stops the rest of the update.
#
# Named to sort before the 20260805 Hyprland pin and catch-up migrations, whose
# own system upgrade this blocker would otherwise fail on the same run.
set -uo pipefail

DROPPED=(
    lib32-gst-plugins-good lib32-gst-plugins-base lib32-gst-plugins-base-libs
    lib32-gstreamer lib32-libcap lib32-pam lib32-audit lib32-libnsl lib32-libtirpc
)

installed=()
for pkg in "${DROPPED[@]}"; do
    pacman -Qq "$pkg" >/dev/null 2>&1 && installed+=("$pkg")
done
if [[ ${#installed[@]} -eq 0 ]]; then
    echo "  No dropped 32-bit GStreamer packages installed - nothing to do"
    exit 0
fi

if ! curl -fsSL --connect-timeout 5 --max-time 8 https://archlinux.org >/dev/null 2>&1; then
    echo "  WARNING: no network - will retry on next update"
    exit 75
fi
if ! sudo pacman -Sy --noconfirm >/dev/null 2>&1; then
    echo "  ERROR: could not refresh package database - will retry on next update"
    exit 1
fi

remove=()
for pkg in "${installed[@]}"; do
    if pacman -Si "$pkg" >/dev/null 2>&1; then
        echo "  $pkg is still provided by a repository - keeping it"
    else
        remove+=("$pkg")
    fi
done
if [[ ${#remove[@]} -eq 0 ]]; then
    echo "  All of them are still provided by repositories - nothing to do"
    exit 0
fi

repo_requires() {
    pacman -Si "$1" 2>/dev/null | sed -n 's/^Depends On *: //p' | tr -s ' ' '\n' \
        | sed 's/[<>=].*//' | grep -qx "$2"
}

skip_dependency_check=0
for pkg in "${remove[@]}"; do
    while read -r dependent; do
        [[ -z "$dependent" || "$dependent" == None ]] && continue
        [[ " ${remove[*]} " == *" $dependent "* ]] && continue
        if ! pacman -Si "$dependent" >/dev/null 2>&1 || repo_requires "$dependent" "$pkg"; then
            echo "  $pkg is still required by $dependent - nothing removed, will retry"
            exit 75
        fi
        echo "  $dependent no longer requires $pkg in its current version"
        skip_dependency_check=1
    done < <(pacman -Qi "$pkg" | sed -n 's/^Required By *: //p' | tr -s ' ' '\n')
done

flags=(-R --noconfirm)
[[ $skip_dependency_check -eq 1 ]] && flags=(-Rdd --noconfirm)
echo "  Removing packages Arch dropped from multilib: ${remove[*]}"
if ! sudo pacman "${flags[@]}" "${remove[@]}"; then
    echo "  ERROR: removal failed - will retry on next update"
    exit 1
fi
echo "  Removed dropped 32-bit GStreamer packages"
