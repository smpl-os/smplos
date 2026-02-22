#!/bin/bash
# Hardware detection: Intel GPU
# Installs Vulkan + VAAPI drivers for Intel iGPUs from the bundled offline repo.
# Runs during post-install while pacman.conf still points to the offline mirror.
#
# Driver selection:
#   intel-media-driver (iHD):  Broadwell (2014) and newer — HD/UHD/Iris/Xe
#   libva-intel-driver (i965): Sandybridge–Haswell (2011–2013) and GMA

INTEL="$(lspci 2>/dev/null | grep -iE '(VGA|3D|Display).*Intel')"

if [[ -z "$INTEL" ]]; then
    echo "  [GPU] No Intel GPU detected, skipping"
    exit 0
fi

echo "  [GPU] Intel GPU detected: $INTEL"

INTEL_LOWER="${INTEL,,}"

# Broadwell (5th gen) and newer: HD Graphics 5xxx+, UHD, Iris, Xe
# Pattern: "hd graphics 5", "hd graphics 6", "uhd", "iris", "xe", or any
# explicit generation marker (8th gen+).
if echo "$INTEL_LOWER" | grep -qE "uhd|iris|xe graphics|hd graphics [5-9]|[6-9][0-9]{3}"; then
    PACKAGES=(mesa lib32-mesa vulkan-intel lib32-vulkan-intel intel-media-driver)
    echo "  [GPU] Using intel-media-driver (iHD) for Broadwell+ iGPU"

# Legacy GMA or pre-Broadwell (Haswell and older HD Graphics)
elif echo "$INTEL_LOWER" | grep -qE "gma|hd graphics [1-4]|sandybridge|ivybridge|haswell"; then
    PACKAGES=(mesa lib32-mesa libva-intel-driver)
    echo "  [GPU] Using libva-intel-driver (i965) for legacy Intel iGPU"

else
    # Safe default: intel-media-driver works on most modern Intel iGPUs
    PACKAGES=(mesa lib32-mesa vulkan-intel lib32-vulkan-intel intel-media-driver)
    echo "  [GPU] Defaulting to intel-media-driver (iHD)"
fi

echo "  [GPU] Installing: ${PACKAGES[*]}"
sudo pacman -S --noconfirm --needed "${PACKAGES[@]}"

echo "  [GPU] Intel driver setup complete"
