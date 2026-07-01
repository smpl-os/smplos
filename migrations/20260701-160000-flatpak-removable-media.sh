#!/bin/bash
# Migration: Grant Flatpak apps access to removable media (/run/media, /media).
# Context: Flatpak runs each app in a sandbox with its own mount namespace and a
#          private /run. USB sticks that udisks mounts under /run/media are
#          therefore invisible inside the sandbox — the drive looks empty. Apps
#          that lack even --filesystem=host (e.g. KeePassXC) never see removable
#          media at all; apps that have host still can't see a drive plugged in
#          after they launched. Granting --filesystem=/run/media binds the real
#          removable-media tree into every Flatpak sandbox.
#
#          From this version on smplos-flatpak-setup applies the same global
#          override on fresh installs. This migration brings existing systems up
#          to date.
#
#          Limitation: a Flatpak app already running when a drive is plugged in
#          must still be relaunched to see the new mount (the sandbox snapshots
#          its mount view at startup). Native apps see it live.

set -euo pipefail

if ! command -v flatpak &>/dev/null; then
    echo "  flatpak not installed — nothing to do"
    exit 0
fi

# Global (all-app) user override. flatpak override merges, so re-running is
# harmless and idempotent.
for path in /run/media /media; do
    flatpak override --user --filesystem="$path" \
        && echo "  granted Flatpak access to $path" \
        || echo "  WARNING: could not grant Flatpak access to $path"
done

echo "  Note: relaunch any running Flatpak app (Blender, KeePassXC, …) to pick this up."
