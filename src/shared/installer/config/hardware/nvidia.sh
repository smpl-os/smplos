#!/bin/bash
# Hardware detection: NVIDIA GPU
# Detects the NVIDIA GPU architecture and installs the correct driver from the
# bundled offline repo.  Runs during post-install while pacman.conf still
# points to the offline mirror — no internet required.
#
# Based on Omarchy's install/config/hardware/nvidia.sh

NVIDIA="$(lspci 2>/dev/null | grep -i 'nvidia')"

if [[ -z "$NVIDIA" ]]; then
    echo "  [GPU] No NVIDIA GPU detected, skipping"
    exit 0
fi

echo "  [GPU] NVIDIA detected: $NVIDIA"

# Detect which kernel is installed and select matching headers package
KERNEL_HEADERS="$(pacman -Qqs '^linux(-zen|-lts|-hardened)?$' 2>/dev/null | head -1)-headers"
[[ "$KERNEL_HEADERS" == "-headers" ]] && KERNEL_HEADERS="linux-lts-headers"

# ── Turing+ (GTX 16xx, RTX 20xx–50xx, Ada RTX 40xx, Quadro RTX) ─────────────
# These have NVIDIA GSP firmware and support the open-source kernel module.
if echo "$NVIDIA" | grep -qE \
    "GTX 16[0-9]{2}|RTX [2-5][0-9]{3}|RTX PRO|Quadro RTX|RTX A[0-9]{4}|A[1-9][0-9]{2}|H[1-9][0-9]{2}|T[1-9][0-9]{2}|L[0-9]+"; then
    PACKAGES=(nvidia-open-dkms nvidia-utils lib32-nvidia-utils)
    GPU_ARCH="turing_plus"
    echo "  [GPU] Architecture: Turing+ (open-source kernel module)"

# ── Maxwell (GTX 9xx), Pascal (GTX/GT 10xx, MX series, Quadro P), Volta ──────
# No GSP firmware — use the legacy nvidia-580xx-dkms driver (AUR, prebuilt).
elif echo "$NVIDIA" | grep -qE \
    "GTX (9[0-9]{2}|10[0-9]{2})|GT 10[0-9]{2}|Quadro [PM][0-9]{3,4}|Quadro GV100|MX *[0-9]+|Titan (X|Xp|V)|Tesla V100"; then
    # Only proceed if the prebuilt legacy driver is in our offline repo
    if pacman -Si nvidia-580xx-dkms &>/dev/null 2>&1; then
        PACKAGES=(nvidia-580xx-dkms nvidia-580xx-utils lib32-nvidia-580xx-utils)
        GPU_ARCH="maxwell_pascal_volta"
        echo "  [GPU] Architecture: Maxwell/Pascal/Volta (nvidia-580xx-dkms)"
    else
        echo "  [GPU] WARNING: legacy NVIDIA GPU detected but nvidia-580xx-dkms is not in the offline repo"
        echo "  [GPU] GPU: $NVIDIA"
        echo "  [GPU] After connecting to the internet, run:"
        echo "  [GPU]   sudo pacman -S nvidia-580xx-dkms nvidia-580xx-utils lib32-nvidia-580xx-utils"
        echo "  [GPU] See also: build/prebuilt/ for prebuilt AUR packages"
        exit 0
    fi

else
    echo "  [GPU] NVIDIA GPU found but no compatible driver matched"
    echo "  [GPU] GPU: $NVIDIA"
    echo "  [GPU] See: https://wiki.archlinux.org/title/NVIDIA"
    exit 0
fi

echo "  [GPU] Installing: $KERNEL_HEADERS ${PACKAGES[*]}"
sudo pacman -S --noconfirm --needed "$KERNEL_HEADERS" "${PACKAGES[@]}"

# Configure modprobe for early KMS — required by Hyprland's DRM backend
sudo mkdir -p /etc/modprobe.d
sudo tee /etc/modprobe.d/nvidia.conf >/dev/null << 'EOF'
options nvidia_drm modeset=1
EOF

# Configure mkinitcpio for early NVIDIA module loading
# (Plymouth's mkinitcpio -P at the end of install.sh will pick this up)
sudo mkdir -p /etc/mkinitcpio.conf.d
sudo tee /etc/mkinitcpio.conf.d/nvidia.conf >/dev/null << 'EOF'
MODULES+=(nvidia nvidia_modeset nvidia_uvm nvidia_drm)
EOF

# Add NVIDIA-specific Hyprland environment variables (if envs.conf exists)
ENVS_CONF="$HOME/.config/hypr/envs.conf"
if [[ -f "$ENVS_CONF" ]]; then
    if [[ "$GPU_ARCH" == "turing_plus" ]]; then
        cat >> "$ENVS_CONF" << 'ENVEOF'

# NVIDIA (Turing+ with GSP firmware)
env = NVD_BACKEND,direct
env = LIBVA_DRIVER_NAME,nvidia
env = __GLX_VENDOR_LIBRARY_NAME,nvidia
ENVEOF
    elif [[ "$GPU_ARCH" == "maxwell_pascal_volta" ]]; then
        cat >> "$ENVS_CONF" << 'ENVEOF'

# NVIDIA (Maxwell/Pascal/Volta without GSP firmware)
env = NVD_BACKEND,egl
env = __GLX_VENDOR_LIBRARY_NAME,nvidia
ENVEOF
    fi
    echo "  [GPU] Hyprland envs.conf updated"
fi

echo "  [GPU] NVIDIA driver setup complete"
echo "  [GPU] Note: initramfs will be rebuilt by the Plymouth setup step"
