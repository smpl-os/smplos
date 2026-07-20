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
    PACKAGES=(nvidia-open-dkms nvidia-utils lib32-nvidia-utils nvidia-container-toolkit)
    GPU_ARCH="turing_plus"
    echo "  [GPU] Architecture: Turing+ (open-source kernel module)"

# ── Maxwell (GTX 9xx), Pascal (GTX/GT 10xx, MX series, Quadro P), Volta ──────
# No GSP firmware — use the legacy nvidia-580xx-dkms driver (AUR, prebuilt).
elif echo "$NVIDIA" | grep -qE \
    "GTX (9[0-9]{2}|10[0-9]{2})|GT 10[0-9]{2}|Quadro [PM][0-9]{3,4}|Quadro GV100|MX *[0-9]+|Titan (X|Xp|V)|Tesla V100"; then
    # Only proceed if the prebuilt legacy driver is in our offline repo
    if pacman -Si nvidia-580xx-dkms &>/dev/null 2>&1; then
        PACKAGES=(nvidia-580xx-dkms nvidia-580xx-utils lib32-nvidia-580xx-utils nvidia-container-toolkit)
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

# Configure modprobe for early KMS — required by Hyprland's DRM backend.
# fbdev=1 gives a proper nvidia framebuffer console (smoother handoff, avoids
# "backlight on / screen black" during DPMS and VT transitions).
# NVreg_PreserveVideoMemoryAllocations=1 preserves VRAM across suspend/resume
# and DPMS so the display comes back instead of a black screen on wake.
sudo mkdir -p /etc/modprobe.d
sudo tee /etc/modprobe.d/nvidia.conf >/dev/null << 'EOF'
options nvidia_drm modeset=1 fbdev=1
options nvidia NVreg_PreserveVideoMemoryAllocations=1
EOF

# Enable NVIDIA's suspend/resume/hibernate helper services. Without these the
# GPU loses its VRAM contents on sleep and wakes to a black screen.
sudo systemctl enable nvidia-suspend.service nvidia-resume.service nvidia-hibernate.service 2>/dev/null || true

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

# ── Container Device Interface (CDI) spec ────────────────────────────────────
# Generates /etc/cdi/nvidia.yaml describing the GPU + all libraries podman/
# docker need to mount into a container. With this file present, users can
# run any NGC / Ollama / vLLM / llama.cpp container against the GPU with:
#
#     podman run --device nvidia.com/gpu=all <image>
#
# The spec is regenerated automatically after driver upgrades (see the
# ALPM hook installed by nvidia-container-toolkit). Best-effort here — if
# the toolkit is not yet resolvable in the live nvidia_uvm chain (nvidia
# module needs an initial load to enumerate GPUs), the hook will retry on
# first boot.
if command -v nvidia-ctk &>/dev/null; then
    sudo mkdir -p /etc/cdi
    if sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml 2>/dev/null; then
        echo "  [GPU] Container Device Interface spec written to /etc/cdi/nvidia.yaml"
    else
        echo "  [GPU] CDI spec generation deferred (GPU not yet enumerable) — will retry on first boot"
    fi
fi

# ── Privacy hardening: null-route NVIDIA telemetry endpoints ─────────────────
# smplOS promises full privacy. The Linux NVIDIA userspace stack does not
# currently phone home to any of the hosts below — they are exclusively used
# by the Windows GeForce Experience client + NvTelemetryContainer service.
# Blocking them defensively costs nothing on Linux and protects against any
# future NVIDIA userspace tool that might contact them (Nsight, potential
# future Linux GFE, …).
#
# Explicitly NOT blocked: nvcr.io (NGC container registry — legit),
# developer.download.nvidia.com (CUDA/driver downloads — legit),
# download.nvidia.com (DLSS/NGX assets — user-triggered).
#
# Audit with: /usr/local/bin/smplos-nvidia-privacy-audit
# Reverse:    delete the marked block between BEGIN/END in /etc/hosts
if ! grep -qF "smplOS NVIDIA telemetry blocklist BEGIN" /etc/hosts 2>/dev/null; then
    sudo tee -a /etc/hosts >/dev/null << 'HOSTS_BLOCK'

# === smplOS NVIDIA telemetry blocklist BEGIN ===
# Managed by src/shared/installer/config/hardware/nvidia.sh
# See:      /usr/local/bin/smplos-nvidia-privacy-audit
# Reverse:  delete this entire marked block
0.0.0.0 telemetry.nvidia.com
0.0.0.0 services.gfe.nvidia.com
0.0.0.0 gfe.nvidia.com
0.0.0.0 events.gfe.nvidia.com
0.0.0.0 rds.nvidia.com
0.0.0.0 gfwsl.geforce.com
0.0.0.0 assets1.gfe.nvidia.com
0.0.0.0 assets2.gfe.nvidia.com
0.0.0.0 images.nvidia.com
::1 telemetry.nvidia.com
::1 services.gfe.nvidia.com
::1 gfe.nvidia.com
::1 events.gfe.nvidia.com
::1 rds.nvidia.com
::1 gfwsl.geforce.com
::1 assets1.gfe.nvidia.com
::1 assets2.gfe.nvidia.com
::1 images.nvidia.com
# === smplOS NVIDIA telemetry blocklist END ===
HOSTS_BLOCK
    echo "  [GPU] Installed NVIDIA telemetry blocklist in /etc/hosts"
else
    echo "  [GPU] NVIDIA telemetry blocklist already present in /etc/hosts"
fi

echo "  [GPU] NVIDIA driver setup complete"
echo "  [GPU] Note: initramfs will be rebuilt by the Plymouth setup step"
echo "  [GPU] Audit privacy anytime with: smplos-nvidia-privacy-audit"
