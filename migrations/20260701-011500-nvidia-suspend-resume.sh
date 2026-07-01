#!/bin/bash
# Migration: Fix NVIDIA suspend/resume + DPMS black-screen on existing installs.
#
# Context: smplOS's installer configured `nvidia_drm modeset=1` but never set
#          up NVIDIA's power-management path. On wake from DPMS-off or suspend
#          the GPU had lost its framebuffer/VRAM contents, so the monitors lit
#          up (backlight on) but stayed black and unrecoverable — the user had
#          to hard power-cycle.
#
#          The fix (now also baked into the installer for fresh installs):
#            1. /etc/modprobe.d/nvidia.conf gains:
#                 options nvidia_drm modeset=1 fbdev=1
#                 options nvidia NVreg_PreserveVideoMemoryAllocations=1
#               fbdev=1 gives a real nvidia fbcon (clean DPMS/VT handoff);
#               PreserveVideoMemoryAllocations=1 keeps VRAM across power
#               transitions so the display returns instead of a black screen.
#            2. nvidia-suspend/resume/hibernate services enabled — these save
#               and restore VRAM around systemd sleep.
#            3. initramfs rebuilt so the new module options take effect (the
#               nvidia modules load early from the initramfs).
#
# Only runs on machines with an NVIDIA GPU. Idempotent and safe to re-run:
# every step checks state first and the initramfs is only rebuilt when the
# modprobe config actually changed. Takes effect on the next reboot.

set -euo pipefail

# ── Guard: NVIDIA GPU only ───────────────────────────────────────────────────
if ! lspci 2>/dev/null | grep -qi 'nvidia'; then
    echo "  No NVIDIA GPU detected, skipping"
    exit 0
fi

n_changes=0
conf_changed=0

# ── 1. modprobe power-management options ─────────────────────────────────────
MODPROBE="/etc/modprobe.d/nvidia.conf"
DESIRED='options nvidia_drm modeset=1 fbdev=1
options nvidia NVreg_PreserveVideoMemoryAllocations=1'

if [[ ! -f "$MODPROBE" ]] || [[ "$(cat "$MODPROBE" 2>/dev/null)" != "$DESIRED" ]]; then
    if printf '%s\n' "$DESIRED" | sudo tee "$MODPROBE" >/dev/null 2>&1; then
        echo "  Updated $MODPROBE (fbdev + PreserveVideoMemoryAllocations)"
        conf_changed=1
        ((n_changes++)) || true
    else
        echo "  WARNING: could not write $MODPROBE (sudo required)"
    fi
else
    echo "  $MODPROBE already current"
fi

# ── 2. Enable NVIDIA sleep helper services ───────────────────────────────────
for svc in nvidia-suspend.service nvidia-resume.service nvidia-hibernate.service; do
    if ! systemctl is-enabled "$svc" >/dev/null 2>&1; then
        if sudo systemctl enable "$svc" >/dev/null 2>&1; then
            echo "  Enabled $svc"
            ((n_changes++)) || true
        else
            echo "  WARNING: could not enable $svc"
        fi
    fi
done

# ── 3. Rebuild initramfs so the new module options load early ────────────────
# Only when the modprobe config changed (the nvidia modules are pulled into the
# initramfs via MODULES+=, so their options must live there too).
if [[ "$conf_changed" -eq 1 ]]; then
    if command -v mkinitcpio >/dev/null 2>&1; then
        echo "  Rebuilding initramfs (mkinitcpio -P)…"
        if sudo mkinitcpio -P >/dev/null 2>&1; then
            echo "  initramfs rebuilt"
            ((n_changes++)) || true
        else
            echo "  WARNING: mkinitcpio -P failed — run it manually before rebooting"
        fi
    fi
fi

if [[ "$n_changes" -gt 0 ]]; then
    echo "  NVIDIA suspend/resume fix applied — takes effect after next reboot"
else
    echo "  NVIDIA suspend/resume already configured, nothing to do"
fi

exit 0
