#!/bin/bash
# Migration: install kernel-modules-hook on existing installs.
#
# Context: Arch's default pacman behaviour is to *delete* the old kernel's
#          module tree in /usr/lib/modules the moment linux-lts is upgraded.
#          The currently-running kernel then loses the ability to load any
#          module it has not already loaded — overlay, nvidia_uvm, dkms
#          modules for new hardware, VirtualBox, etc. Podman/Docker/DKMS all
#          break silently until reboot, and there is no user-visible warning
#          at upgrade time.
#
#          `kernel-modules-hook` (Arch extra/) installs an ALPM hook that
#          copies the outgoing kernel's module tree into a preserved location
#          before pacman removes it, so the running kernel keeps working
#          until the user chooses to reboot. On reboot the new kernel takes
#          over normally and old preserved trees are pruned.
#
#          This closes the fleet-wide window in which Update OS (or any manual
#          `pacman -Syu` that bypasses the critical-package ignore-list) could
#          leave a machine unable to load modules until reboot.
#
# Safe to re-run: --needed makes install a no-op if already present. Only
# runs pacman when the package is missing. Never removes anything, never
# alters the running kernel or any user data. Best-effort — exits 0 even on
# failure so it can never abort the update chain.

set -uo pipefail   # deliberately no -e — pacman failures must not abort updates

pkg="kernel-modules-hook"

if pacman -Q "$pkg" &>/dev/null; then
    echo "  $pkg already installed — skipping"
    exit 0
fi

echo "  Installing $pkg (preserves running kernel modules across upgrades)..."
if sudo pacman -S --needed --noconfirm "$pkg" 2>&1; then
    echo "  ✓ $pkg installed"
else
    echo "  WARNING: could not install $pkg (network/mirror issue?); will retry on next update"
fi

exit 0
