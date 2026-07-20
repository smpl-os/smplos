#!/bin/bash
# Migration: NVIDIA telemetry blocklist for existing installs.
#
# smplOS promises full privacy. This migration null-routes known NVIDIA
# telemetry endpoints via /etc/hosts on machines that already have an
# NVIDIA driver installed. Fresh installs get the same block via the
# installer (src/shared/installer/config/hardware/nvidia.sh).
#
# What we block and why it is safe on Linux:
#   - GeForce Experience (Windows-only) analytics + auth endpoints
#   - NvTelemetryContainer service endpoints (Windows-only)
#   All are unused by the Linux driver + userspace + container toolkit.
#
# What we deliberately DO NOT block:
#   - nvcr.io (NGC container registry)
#   - developer.download.nvidia.com / download.nvidia.com
#   - authn.nvidia.com
#
# Idempotent: skips if the marked block is already present.
# Reversible: delete the block between BEGIN/END markers in /etc/hosts.

set -uo pipefail

# ── 1. Only on NVIDIA hosts ──────────────────────────────────────────────────
if ! lspci 2>/dev/null | grep -qi 'nvidia'; then
    echo "  No NVIDIA GPU detected — skipping"
    exit 0
fi

# ── 2. Skip if already installed ─────────────────────────────────────────────
if grep -qF "smplOS NVIDIA telemetry blocklist BEGIN" /etc/hosts 2>/dev/null; then
    echo "  NVIDIA telemetry blocklist already installed in /etc/hosts"
    exit 0
fi

# ── 3. Append blocklist ──────────────────────────────────────────────────────
echo "  Installing NVIDIA telemetry blocklist in /etc/hosts..."
sudo tee -a /etc/hosts >/dev/null << 'HOSTS_BLOCK'

# === smplOS NVIDIA telemetry blocklist BEGIN ===
# Managed by migrations/20260719-120000-nvidia-privacy-hardening.sh
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

# ── 4. Verify block took effect ──────────────────────────────────────────────
if getent hosts telemetry.nvidia.com 2>/dev/null | grep -qE '^(0\.0\.0\.0|::1)'; then
    echo "  ✓ telemetry.nvidia.com now resolves to sink hole"
else
    RESOLVED=$(getent hosts telemetry.nvidia.com 2>/dev/null | awk '{print $1}')
    echo "  WARNING: telemetry.nvidia.com resolves to '$RESOLVED' — NSS may be bypassing /etc/hosts"
    echo "           (check /etc/nsswitch.conf 'hosts:' line — 'files' should come first)"
fi

echo "  Audit anytime with: smplos-nvidia-privacy-audit"
exit 0
