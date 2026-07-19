#!/bin/bash
# Migration: install nvidia-container-toolkit on existing NVIDIA installs.
#
# Context: smplOS now ships nvidia-container-toolkit on all NVIDIA machines so
#          that podman/docker can pass the GPU into AI containers via the
#          Container Device Interface. Without it, every GPU-accelerated
#          container image (NGC PyTorch, Ollama, vLLM, LocalAI, HuggingFace
#          TGI, llama.cpp CUDA, …) fails with "no such device: nvidia.com/gpu".
#
#          This migration installs the toolkit on machines that already have
#          an NVIDIA driver loaded, then generates /etc/cdi/nvidia.yaml so
#          the very first `podman run --device nvidia.com/gpu=all <image>`
#          just works.
#
# Safe to re-run: --needed makes install a no-op if already present; CDI spec
# regeneration is idempotent. Skips non-NVIDIA hosts entirely. Best-effort:
# never fails the update chain.

set -uo pipefail   # deliberately no -e — pacman/nvidia-ctk failures must not abort updates

# ── 1. Only run on NVIDIA hosts ──────────────────────────────────────────────
if ! lspci 2>/dev/null | grep -qi 'nvidia'; then
    echo "  No NVIDIA GPU detected — skipping"
    exit 0
fi

# ── 2. Only run if an NVIDIA driver is actually installed ────────────────────
# We do NOT want to pull in the container toolkit on a host that somehow ended
# up with an NVIDIA card but never got the driver — that would leave the
# toolkit orphaned. The driver install path (installer/config/hardware/
# nvidia.sh) is authoritative for that case on fresh installs.
if ! pacman -Q nvidia-open-dkms nvidia-580xx-dkms &>/dev/null; then
    if ! pacman -Qqs '^nvidia-.*-dkms$' 2>/dev/null | grep -q .; then
        echo "  No NVIDIA driver installed — skipping (toolkit needs a driver to be useful)"
        exit 0
    fi
fi

# ── 3. Install nvidia-container-toolkit ──────────────────────────────────────
if pacman -Q nvidia-container-toolkit &>/dev/null; then
    echo "  nvidia-container-toolkit already installed"
else
    echo "  Installing nvidia-container-toolkit (enables GPU containers)..."
    if sudo pacman -S --needed --noconfirm nvidia-container-toolkit 2>&1; then
        echo "  ✓ nvidia-container-toolkit installed"
    else
        echo "  WARNING: could not install nvidia-container-toolkit; will retry on next update"
        exit 0
    fi
fi

# ── 4. Generate / refresh CDI spec so podman auto-discovers the GPU ──────────
if command -v nvidia-ctk &>/dev/null; then
    sudo mkdir -p /etc/cdi 2>/dev/null || true
    # Only regenerate if the GPU is actually enumerable right now. If nvidia
    # module isn't loaded (e.g. host booted with `nomodeset` or driver
    # upgrade pending reboot), skip — the toolkit's own ALPM hook will
    # retry on next kernel boot.
    if [[ -e /dev/nvidia0 ]] || nvidia-smi &>/dev/null; then
        if sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml 2>/dev/null; then
            echo "  ✓ CDI spec generated at /etc/cdi/nvidia.yaml"
            echo "    Test with: podman run --rm --device nvidia.com/gpu=all docker.io/nvidia/cuda:12.9.0-base-ubuntu22.04 nvidia-smi"
        else
            echo "  WARNING: nvidia-ctk cdi generate failed — retry manually after reboot"
        fi
    else
        echo "  GPU not enumerable right now (module not loaded / reboot pending) — CDI spec deferred"
    fi
fi

exit 0
