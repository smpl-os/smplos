#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# 0. Parse arguments
# ------------------------------------------------------------

RESET_VM=0
if [[ "${1:-}" == "--reset" || "${1:-}" == "-r" ]]; then
    RESET_VM=1
    echo "Resetting VM state (removing disk and UEFI vars)..."
fi

# ------------------------------------------------------------
# 1. Check prerequisites
# ------------------------------------------------------------

need() {
    # $1 = binary name, $2 = package name (optional, defaults to $1)
    if ! command -v "$1" >/dev/null 2>&1; then
        local pkg="${2:-$1}"
        echo "Missing dependency: $1"
        echo "Install it with: sudo pacman -S $pkg"
        exit 1
    fi
}

# Binary is qemu-system-x86_64, but the Arch package is qemu-system-x86
need qemu-system-x86_64 qemu-system-x86
need qemu-img
need wmctrl

# Check KVM support
if [[ ! -e /dev/kvm ]]; then
    echo "Warning: /dev/kvm not found. QEMU will run slowly."
    echo "Enable virtualization in BIOS or load kvm modules."
fi

# ------------------------------------------------------------
# 2. Detect OVMF firmware
# ------------------------------------------------------------

OVMF_CODE_CANDIDATES=(
    "/usr/share/edk2/x64/OVMF_CODE.4m.fd"
    "/usr/share/edk2-ovmf/x64/OVMF_CODE.fd"
    "/usr/share/ovmf/x64/OVMF_CODE.fd"
)

OVMF_VARS_CANDIDATES=(
    "/usr/share/edk2/x64/OVMF_VARS.4m.fd"
    "/usr/share/edk2-ovmf/x64/OVMF_VARS.fd"
    "/usr/share/ovmf/x64/OVMF_VARS.fd"
)

OVMF_CODE=""
OVMF_VARS=""

for f in "${OVMF_CODE_CANDIDATES[@]}"; do
    [[ -f "$f" ]] && OVMF_CODE="$f" && break
done

for f in "${OVMF_VARS_CANDIDATES[@]}"; do
    [[ -f "$f" ]] && OVMF_VARS="$f" && break
done

if [[ -z "$OVMF_CODE" || -z "$OVMF_VARS" ]]; then
    echo "Could not find OVMF firmware on this system."
    echo "Install it with: sudo pacman -S edk2-ovmf"
    exit 1
fi

echo "Using OVMF firmware:"
echo "  CODE: $OVMF_CODE"
echo "  VARS: $OVMF_VARS"

# ------------------------------------------------------------
# 3. Handle VM state files
# ------------------------------------------------------------

LOCAL_VARS="./OVMF_VARS.fd"
DISK="./smplos-test.qcow2"

if [[ "$RESET_VM" -eq 1 ]]; then
    rm -f "$LOCAL_VARS" "$DISK"
    echo "VM state cleared."
fi

if [[ ! -f "$DISK" ]]; then
    echo "Creating $DISK (20G)..."
    qemu-img create -f qcow2 "$DISK" 20G
    rm -f "$LOCAL_VARS"
fi

if [[ ! -f "$LOCAL_VARS" ]]; then
    echo "Creating writable local copy of OVMF_VARS..."
    cp "$OVMF_VARS" "$LOCAL_VARS"
fi

# ------------------------------------------------------------
# 4. Find newest ISO
# ------------------------------------------------------------

ISO=$(find . -maxdepth 1 -type f -name "*.iso" | sort | tail -n 1)

if [[ -z "$ISO" ]]; then
    echo "No ISO found in current directory."
    exit 1
fi

echo "Launching QEMU with ISO: $ISO"

# ------------------------------------------------------------
# 5. Create shared folder
# ------------------------------------------------------------

SHARE_DIR="./vmshare"

if [[ ! -d "$SHARE_DIR" ]]; then
    echo "Creating shared folder at $SHARE_DIR ..."
    mkdir -p "$SHARE_DIR"
fi

# ------------------------------------------------------------
# 6. Launch QEMU
# ------------------------------------------------------------

# boot.log captures all serial console output (kernel + initramfs + systemd)
# The debug boot entry sends output to ttyS0 — readable even after a crash
BOOT_LOG="./boot-$(date +%Y%m%d-%H%M%S).log"
echo "Boot log: $BOOT_LOG"

qemu-system-x86_64 \
  -enable-kvm \
  -cpu host \
  -m 8192 \
  -smp "$(nproc)" \
  -machine q35 \
  -serial file:"$BOOT_LOG" \
  -drive if=pflash,format=raw,unit=0,readonly=on,file="$OVMF_CODE" \
  -drive if=pflash,format=raw,unit=1,file="$LOCAL_VARS" \
  -drive file="$DISK",format=qcow2,if=none,id=drive0 \
  -device virtio-blk-pci,drive=drive0,bootindex=1 \
  -drive file="$ISO",media=cdrom,if=none,format=raw,id=cdrom0 \
  -device ide-cd,drive=cdrom0,bootindex=2 \
  -virtfs local,path="$SHARE_DIR",mount_tag=hostshare,security_model=mapped-xattr,id=hostshare \
  -vga virtio \
  -display gtk,zoom-to-fit=on \
  -usb \
  -device usb-tablet \
  -boot menu=on \
  -name "smplOS Test VM",process=on &

# Give QEMU a moment to appear
sleep 2

# Bring VM window to front
wmctrl -a "smplOS Test VM" 2>/dev/null || true

# ------------------------------------------------------------
# 9. Print VM instructions
# ------------------------------------------------------------

cat << 'INSTRUCTIONS'

╔══════════════════════════════════════════════════════════════╗
║                    smplOS Test VM                           ║
╠══════════════════════════════════════════════════════════════╣
║                                                             ║
║  Mount shared folder (inside VM):                           ║
║                                                             ║
║    sudo mount -t 9p -o trans=virtio hostshare /mnt          ║
║                                                             ║
║  Hot-reload workflow (on host):                             ║
║    cd release && ./dev-push.sh eww                          ║
║                                                             ║
║  Then inside VM:                                            ║
║    sudo bash /mnt/dev-apply.sh                              ║
║                                                             ║
║  (9p is live -- no remount needed after dev-push!)          ║
║                                                             ║
╚══════════════════════════════════════════════════════════════╝

INSTRUCTIONS

echo "Done."
