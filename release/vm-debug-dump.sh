#!/usr/bin/env bash
# smplOS VM Debug Dump
# Run this INSIDE the VM to collect all logs and configs,
# then share them with the host via 9p virtio mount.
#
# Usage:  sudo ./vm-debug-dump.sh
#         (or just: vm-debug-dump  if installed to PATH)

set -euo pipefail

# ── Colors ──────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}▸${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
err()   { echo -e "${RED}✗${NC} $*"; }
header(){ echo -e "\n${BOLD}═══ $* ═══${NC}"; }

# ── Must run as root (for journalctl, dmesg, etc.) ──────────
if [[ $EUID -ne 0 ]]; then
    echo "Re-running with sudo..."
    exec sudo "$0" "$@"
fi

# Detect the real user (even under sudo)
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo root)}"
REAL_HOME=$(eval echo "~$REAL_USER")

# ── Mount the shared folder ──────────────────────────────────
MOUNT_POINT="/mnt/hostshare"
DUMP_DIR="$MOUNT_POINT/debug-$(date +%Y%m%d-%H%M%S)"

header "Mounting host shared folder"

mkdir -p "$MOUNT_POINT"

if mountpoint -q "$MOUNT_POINT"; then
    info "Already mounted at $MOUNT_POINT"
else
    # Try VVFAT disk first (/dev/vdb), fall back to 9p
    if mount /dev/vdb "$MOUNT_POINT" 2>/dev/null; then
        ok "Mounted VVFAT share at $MOUNT_POINT"
    elif mount -t 9p -o trans=virtio,version=9p2000.L hostshare "$MOUNT_POINT" 2>/dev/null; then
        ok "Mounted 9p share at $MOUNT_POINT"
    else
        err "Failed to mount shared folder. Are you running inside the QEMU VM?"
        err "Try: lsblk   to find the shared disk device."
        exit 1
    fi
fi

mkdir -p "$DUMP_DIR"
info "Dumping to: $DUMP_DIR"

# ── Helper: safe copy ──────────────────────────────────────
dump_file() {
    local src="$1"
    local dest="$DUMP_DIR/$2"
    mkdir -p "$(dirname "$dest")"
    if [[ -e "$src" ]]; then
        cp -rL "$src" "$dest" 2>/dev/null && ok "  $2" || err "  $2 (copy failed)"
    else
        err "  $2 (not found: $src)"
    fi
}

dump_cmd() {
    local label="$1"
    shift
    local dest="$DUMP_DIR/$label"
    mkdir -p "$(dirname "$dest")"
    if "$@" > "$dest" 2>&1; then
        ok "  $label"
    else
        err "  $label (command failed, partial output saved)"
    fi
}

# ════════════════════════════════════════════════════════════
# SYSTEM INFO
# ════════════════════════════════════════════════════════════
header "System Info"

dump_cmd "system/uname.txt"        uname -a
dump_cmd "system/os-release.txt"   cat /etc/os-release
dump_cmd "system/hostname.txt"     hostname
dump_cmd "system/uptime.txt"       uptime
dump_cmd "system/free.txt"         free -h
dump_cmd "system/lsblk.txt"        lsblk -f
dump_cmd "system/df.txt"           df -h
dump_cmd "system/mount.txt"        mount
dump_cmd "system/lspci.txt"        lspci
dump_cmd "system/lsmod.txt"        lsmod
dump_cmd "system/env.txt"          env
dump_cmd "system/locale.txt"       locale
dump_cmd "system/timedatectl.txt"  timedatectl

# ════════════════════════════════════════════════════════════
# JOURNAL / DMESG
# ════════════════════════════════════════════════════════════
header "Logs"

dump_cmd "logs/dmesg.txt"                dmesg --color=never
dump_cmd "logs/journal-boot.txt"         journalctl -b --no-pager
dump_cmd "logs/journal-errors.txt"       journalctl -b -p err --no-pager
dump_cmd "logs/journal-warnings.txt"     journalctl -b -p warning --no-pager
dump_cmd "logs/journal-hyprland.txt"     journalctl -b --user -u hyprland --no-pager

# Hyprland log (if it writes one)
for log in /tmp/hypr/*/hyprland.log; do
    [[ -f "$log" ]] || continue
    instance=$(basename "$(dirname "$log")")
    dump_file "$log" "logs/hyprland-$instance.log"
done


# ════════════════════════════════════════════════════════════
# PACKAGES
# ════════════════════════════════════════════════════════════
header "Packages"

dump_cmd "packages/installed.txt"    pacman -Q
dump_cmd "packages/explicit.txt"     pacman -Qe
dump_cmd "packages/foreign.txt"      pacman -Qm

# ════════════════════════════════════════════════════════════
# CONFIG FILES
# ════════════════════════════════════════════════════════════
header "Config Files"


# Hyprland
dump_file "$REAL_HOME/.config/hypr"                   "config/hypr"

# Theme system
dump_file "$REAL_HOME/.config/smplos"                 "config/smplos"

# Terminal configs
dump_file "$REAL_HOME/.config/foot/foot.ini"          "config/foot/foot.ini"
dump_file "$REAL_HOME/.config/foot/theme.ini"         "config/foot/theme.ini"
dump_file "$REAL_HOME/.config/alacritty"              "config/alacritty"

# Notifications
dump_file "$REAL_HOME/.config/mako"                   "config/mako"

# btop
dump_file "$REAL_HOME/.config/btop/btop.conf"         "config/btop/btop.conf"
dump_file "$REAL_HOME/.config/btop/themes"            "config/btop/themes"

# Fastfetch
dump_file "$REAL_HOME/.config/fastfetch"              "config/fastfetch"

# Branding
dump_file "$REAL_HOME/.config/smplos/branding"        "config/smplos-branding"

# GTK
dump_file "$REAL_HOME/.config/gtk-3.0/settings.ini"   "config/gtk-3.0/settings.ini"
dump_file "$REAL_HOME/.config/gtk-4.0/settings.ini"   "config/gtk-4.0/settings.ini"

# ════════════════════════════════════════════════════════════
# THEME STATE
# ════════════════════════════════════════════════════════════
header "Theme State"

dump_cmd "theme/current-name.txt"  cat "$REAL_HOME/.config/smplos/current/theme.name"

# List available themes
dump_cmd "theme/available.txt"     ls -1 "$REAL_HOME/.local/share/smplos/themes/"


# Active theme dir contents
if [[ -d "$REAL_HOME/.config/smplos/current/theme" ]]; then
    dump_cmd "theme/current-contents.txt"  ls -la "$REAL_HOME/.config/smplos/current/theme/"
fi

# ════════════════════════════════════════════════════════════
# RUNTIME STATE
# ════════════════════════════════════════════════════════════
header "Runtime State"

dump_cmd "runtime/processes.txt"          ps auxf
dump_cmd "runtime/hyprctl-monitors.txt"  su -c "hyprctl monitors" "$REAL_USER" 2>&1 || true
dump_cmd "runtime/hyprctl-clients.txt"   su -c "hyprctl clients" "$REAL_USER" 2>&1 || true
dump_cmd "runtime/hyprctl-layers.txt"    su -c "hyprctl layers" "$REAL_USER" 2>&1 || true
dump_cmd "runtime/hyprctl-binds.txt"     su -c "hyprctl binds" "$REAL_USER" 2>&1 || true
dump_cmd "runtime/smplos-themes.json"    cat /tmp/smplos-themes.json 2>&1 || true

# ════════════════════════════════════════════════════════════
# INSTALLER STATE (if installation was attempted)
# ════════════════════════════════════════════════════════════
header "Installer State"

dump_file "/root/smplos"                              "installer/smplos-payload"
dump_file "/var/log/install.log"                       "installer/install.log"

# ════════════════════════════════════════════════════════════
# SCRIPTS (what's actually on PATH)
# ════════════════════════════════════════════════════════════
header "Scripts on PATH"

for cmd in theme-set theme-picker theme-list theme-current theme-bg-next \
           bar-ctl launcher vm-debug-dump; do
    path=$(which "$cmd" 2>/dev/null || echo "NOT FOUND")
    echo "$cmd → $path" >> "$DUMP_DIR/scripts/path-locations.txt"
    if [[ "$path" != "NOT FOUND" && -f "$path" ]]; then
        dump_file "$path" "scripts/$cmd"
    fi
done
ok "  scripts/path-locations.txt"

# ════════════════════════════════════════════════════════════
# DONE
# ════════════════════════════════════════════════════════════

# Summary
FILE_COUNT=$(find "$DUMP_DIR" -type f | wc -l)
TOTAL_SIZE=$(du -sh "$DUMP_DIR" | cut -f1)

header "Debug dump complete"
echo ""
echo -e "  ${BOLD}Location:${NC} $DUMP_DIR"
echo -e "  ${BOLD}Files:${NC}    $FILE_COUNT"
echo -e "  ${BOLD}Size:${NC}     $TOTAL_SIZE"
echo ""
echo -e "  On the ${BOLD}host${NC}, find the dump at:"
echo -e "  ${CYAN}./vmshare/$(basename "$DUMP_DIR")/${NC}"
echo ""
