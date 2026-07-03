#!/bin/bash
# Migration: Make linux-lts the default boot kernel.
#
# Context: suspend/resume ("sleep") is broken on the mainline `linux` kernel on
#          affected hardware — the machine either refuses to suspend or wakes to
#          a black, unrecoverable screen. The linux-lts kernel does not carry the
#          regression, so smplOS now boots linux-lts by default.
#
#          This ONLY changes which GRUB entry boots by default. Mainline and any
#          other installed kernels are LEFT IN PLACE as fallbacks in the GRUB
#          menu — the migration never removes a kernel, so the machine can always
#          boot something.
#
# Safety:  GRUB-only (guarded on /boot/grub/grub.cfg). No -e, every privileged
#          step tolerates failure, and the migration always exits 0 so it can
#          never abort the update chain. Surface devices keep linux-surface as
#          their default (it is the correct kernel there). Idempotent and safe to
#          re-run. Takes effect on the next reboot.

set -uo pipefail   # deliberately no -e: individual steps are allowed to fail

GRUB_CFG="/boot/grub/grub.cfg"

# ── Surface devices: linux-surface is the correct kernel, don't override ──────
sys_vendor="$(cat /sys/devices/virtual/dmi/id/sys_vendor 2>/dev/null || true)"
product="$(cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null || true)"
if [[ "$sys_vendor" == "Microsoft Corporation" && "$product" == Surface* ]]; then
    echo "  Surface device — linux-surface stays the default kernel, skipping"
    exit 0
fi

# ── GRUB only ────────────────────────────────────────────────────────────────
if [[ ! -f "$GRUB_CFG" ]]; then
    echo "  No GRUB config at $GRUB_CFG (non-GRUB bootloader?), skipping"
    exit 0
fi

# ── 1. Ensure linux-lts + headers are installed (best effort) ────────────────
if ! pacman -Q linux-lts &>/dev/null; then
    echo "  Installing linux-lts + linux-lts-headers…"
    if sudo pacman -S --noconfirm --needed linux-lts linux-lts-headers >/dev/null 2>&1; then
        echo "  linux-lts installed"
        # New kernel → regenerate grub so its menu entry exists.
        sudo grub-mkconfig -o "$GRUB_CFG" >/dev/null 2>&1 || true
    else
        echo "  WARNING: could not install linux-lts (offline or no privileges)."
        echo "           Install it, then re-run: smplos-os-update --migrate"
        exit 0
    fi
else
    echo "  linux-lts already installed"
fi

# ── 2. Make GRUB honour a saved default ──────────────────────────────────────
if ! grep -q '^GRUB_DEFAULT=saved' /etc/default/grub 2>/dev/null; then
    if sudo sed -i 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT=saved/' /etc/default/grub 2>/dev/null; then
        echo "  Set GRUB_DEFAULT=saved"
        sudo grub-mkconfig -o "$GRUB_CFG" >/dev/null 2>&1 || true
    else
        echo "  WARNING: could not set GRUB_DEFAULT=saved in /etc/default/grub"
    fi
fi

# ── 3. Point the saved default at the linux-lts menu entry ───────────────────
# Same idiom the installer uses for linux-surface: pull the menuentry title out
# of grub.cfg and hand it to grub-set-default.
lts_entry="$(grep -m1 'menuentry.*linux-lts' "$GRUB_CFG" 2>/dev/null \
    | sed -n "s/.*menuentry '\([^']*\)'.*/\1/p")"

if [[ -z "$lts_entry" ]]; then
    echo "  WARNING: no linux-lts entry found in $GRUB_CFG — default left unchanged"
    exit 0
fi

if sudo grub-set-default "$lts_entry" 2>/dev/null; then
    echo "  Default boot kernel set to: $lts_entry"
    echo "  (mainline and other kernels remain available in the GRUB menu)"
else
    echo "  WARNING: grub-set-default failed — default kernel unchanged"
fi

exit 0
