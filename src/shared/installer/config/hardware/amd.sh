#!/bin/bash
# Hardware detection: AMD GPU
# Installs Vulkan + video-acceleration drivers for AMD GPUs (RDNA, GCN, APU)
# from the bundled offline repo.  Runs during post-install while pacman.conf
# still points to the offline mirror — no internet required.

AMD="$(lspci 2>/dev/null | grep -iE '(VGA|3D|Display).*(AMD|ATI|Radeon)|(AMD|ATI|Radeon).*(VGA|3D|Display)')"

if [[ -z "$AMD" ]]; then
    echo "  [GPU] No AMD GPU detected, skipping"
    exit 0
fi

echo "  [GPU] AMD GPU detected: $AMD"

# mesa:             OpenGL/EGL base library + amdgpu DRM userspace
# vulkan-radeon:    AMD Vulkan via Mesa RADV (required by Hyprland)
# libva-mesa-driver: VAAPI hardware video decode (VDPAU/NVDEC equivalent for AMD)
PACKAGES=(mesa lib32-mesa vulkan-radeon lib32-vulkan-radeon libva-mesa-driver)

echo "  [GPU] Installing: ${PACKAGES[*]}"
sudo pacman -S --noconfirm --needed "${PACKAGES[@]}"

echo "  [GPU] AMD driver setup complete"
