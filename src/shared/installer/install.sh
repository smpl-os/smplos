#!/bin/bash

# smplOS Post-Install Script
# Runs inside the chroot after archinstall completes
# Based on Omarchy installer architecture

set -eEo pipefail

# Define smplOS locations
export SMPLOS_PATH="$HOME/.local/share/smplos"
export SMPLOS_INSTALL="$SMPLOS_PATH/install"
export SMPLOS_INSTALL_LOG_FILE="/var/log/smplos-install.log"
export PATH="$SMPLOS_PATH/bin:$PATH"

# Load helpers
source "$SMPLOS_INSTALL/helpers/all.sh"

# Start install timer
SMPLOS_START_EPOCH=$(date +%s)
echo "=== smplOS Installation Started: $(date '+%Y-%m-%d %H:%M:%S') ===" >>"$SMPLOS_INSTALL_LOG_FILE" 2>/dev/null || true

# Chroot-aware systemctl enable (don't use --now in chroot)
chrootable_systemctl_enable() {
  if [[ -n "${SMPLOS_CHROOT_INSTALL:-}" ]]; then
    sudo systemctl enable "$1"
  else
    sudo systemctl enable --now "$1"
  fi
}

echo "==> Configuring desktop environment..."

# Install AUR packages from the offline mirror
# Reads the merged packages-aur.txt (shared + compositor, written by build.sh)
if [[ -d /var/cache/smplos/mirror/offline ]]; then
  aur_list="$HOME/.local/share/smplos/packages-aur.txt"
  if [[ -f "$aur_list" ]]; then
    echo "==> Installing AUR packages from offline mirror..."
    while IFS= read -r pkg; do
      [[ "$pkg" =~ ^#.*$ || -z "$pkg" ]] && continue
      local_pkg=$(find /var/cache/smplos/mirror/offline -name "${pkg}-[0-9]*.pkg.tar.*" ! -name "*-debug-*" 2>/dev/null | head -1)
      if [[ -n "$local_pkg" ]]; then
        echo "    Installing: $(basename "$local_pkg")"
        sudo pacman -U --noconfirm --needed "$local_pkg" 2>/dev/null || true
      fi
    done < "$aur_list"
  fi
fi

# Copy configs to user home
if [[ -d "$SMPLOS_PATH/config" ]]; then
  mkdir -p "$HOME/.config"
  cp -r "$SMPLOS_PATH/config/"* "$HOME/.config/" 2>/dev/null || true
  # Ensure EWW listener scripts are executable (cp from skel may strip +x)
  find "$HOME/.config/eww/scripts" -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
  echo "==> Config files deployed:"
  ls -la "$HOME/.config/eww/" 2>/dev/null || echo "    WARNING: eww config dir missing!"
fi

# Configure extra keyboard layout (if user chose one during install)
if [[ -n "${SMPLOS_EXTRA_LAYOUT:-}" ]]; then
  echo "==> Configuring extra keyboard layout: ${SMPLOS_EXTRA_LAYOUT}${SMPLOS_EXTRA_VARIANT:+ ($SMPLOS_EXTRA_VARIANT)}..."

  # Use the primary XKB layout passed from the configurator
  primary_xkb="${SMPLOS_PRIMARY_XKB:-us}"

  # Build layout list with us always first.
  # Hyprland resolves keybinds against layout #1 by default, so putting us
  # first means Super+W etc. work regardless of which layout is active.
  layouts=""
  variants=""
  if [[ "$primary_xkb" == "us" ]]; then
    # Primary is US, extra goes second
    layouts="us,${SMPLOS_EXTRA_LAYOUT}"
    variants=",${SMPLOS_EXTRA_VARIANT:-}"
  elif [[ "${SMPLOS_EXTRA_LAYOUT}" == "us" ]]; then
    # Extra is US — swap so US is first, primary goes second
    layouts="us,${primary_xkb}"
    variants="${SMPLOS_EXTRA_VARIANT:-},"
  else
    # Neither is US — prepend us so keybinds always work
    layouts="us,${primary_xkb},${SMPLOS_EXTRA_LAYOUT}"
    variants=",,${SMPLOS_EXTRA_VARIANT:-}"
  fi

  # Update Hyprland input.conf with the layout list
  input_conf="$HOME/.config/hypr/input.conf"
  if [[ -f "$input_conf" ]]; then
    sed -i "s/^    kb_layout = .*/    kb_layout = ${layouts}/" "$input_conf"
    sed -i "s/^    kb_variant = .*/    kb_variant = ${variants}/" "$input_conf"
    # Add grp:alt_shift_toggle to kb_options (keep existing options like compose:caps)
    current_opts=$(grep '^\s*kb_options' "$input_conf" | sed 's/.*= *//')
    if [[ -n "$current_opts" && "$current_opts" != *"grp:"* ]]; then
      sed -i "s/^    kb_options = .*/    kb_options = ${current_opts},grp:alt_shift_toggle/" "$input_conf"
    elif [[ -z "$current_opts" ]]; then
      sed -i "s/^    kb_options = .*/    kb_options = grp:alt_shift_toggle/" "$input_conf"
    fi
    echo "    Hyprland input.conf updated"
  fi

  # Add Alt+Shift keybinding for layout switching to bindings.conf
  bindings_conf="$HOME/.config/hypr/bindings.conf"
  if [[ -f "$bindings_conf" ]] && ! grep -q "switchxkblayout" "$bindings_conf"; then
    cat >> "$bindings_conf" <<'KBBIND'

# Keyboard layout switching (also available via Alt+Shift through XKB options)
bindd = ALT, SHIFT_L, Switch keyboard layout, exec, hyprctl switchxkblayout current next
KBBIND
    echo "    Keybinding added to bindings.conf"
  fi
fi

# Deploy theme system
# Always ensure all stock themes are deployed (skel may only have partial data)
if [[ -d "$SMPLOS_PATH/themes" ]]; then
  echo "==> Deploying theme system..."
  :  # themes already in place
fi

# Deploy edition desktop entries (web app wrappers like Discord)
if [[ -d "$SMPLOS_PATH/applications" ]]; then
  echo "==> Deploying edition desktop entries..."
  mkdir -p "$HOME/.local/share/applications"
  cp "$SMPLOS_PATH/applications/"*.desktop "$HOME/.local/share/applications/" 2>/dev/null || true
fi
# Deploy edition icons
if [[ -d "$SMPLOS_PATH/icons/hicolor" ]]; then
  echo "==> Deploying edition icons..."
  sudo cp -r "$SMPLOS_PATH/icons/hicolor" /usr/share/icons/
  sudo gtk-update-icon-cache /usr/share/icons/hicolor 2>/dev/null || true
fi

# Deploy custom os-release (smplOS branding)
if [[ -f "$SMPLOS_PATH/system/os-release" ]]; then
  echo "==> Setting os-release..."
  sudo cp "$SMPLOS_PATH/system/os-release" /etc/os-release
fi

# Apply default theme (catppuccin) to generate all config files
echo "==> Setting default theme..."
theme-set catppuccin || echo "    WARNING: theme-set failed (exit $?)"

# Set Fish as default shell
if command -v fish &>/dev/null; then
  echo "==> Setting Fish as default shell..."
  sudo chsh -s /usr/bin/fish "$USER"
fi

# Verify EWW theme colors were deployed
if [[ -f "$HOME/.config/eww/theme-colors.scss" ]]; then
  echo "    EWW theme-colors.scss: OK"
else
  echo "    WARNING: EWW theme-colors.scss not found after theme-set!"
fi

# Deploy default wallpaper
default_wp=$(find "$SMPLOS_PATH/wallpapers/" -maxdepth 1 -type f \( -name '*.jpg' -o -name '*.png' \) 2>/dev/null | head -1)
if [[ -n "$default_wp" ]]; then
  echo "==> Deploying default wallpaper..."
  mkdir -p "$HOME/Pictures/Wallpapers"
  cp "$default_wp" "$HOME/Pictures/Wallpapers/$(basename "$default_wp")"
fi

# Configure VS Code / VSCodium to use gnome-libsecret for credential storage
# Without this, Electron may fail to auto-detect the keyring on Wayland
for argv_dir in "$HOME/.vscode" "$HOME/.vscode-oss"; do
  mkdir -p "$argv_dir"
  cat > "$argv_dir/argv.json" <<'ARGVEOF'
{
  "password-store": "gnome-libsecret"
}
ARGVEOF
done

# Configure PAM for gnome-keyring auto-unlock
# Without this, gnome-keyring-daemon starts but the keyring stays locked,
# causing VS Code/Brave/git to show "no keyring found" errors
echo "==> Configuring PAM for gnome-keyring auto-unlock..."
for pam_file in /etc/pam.d/login /etc/pam.d/greetd; do
  if [[ -f "$pam_file" ]]; then
    grep -q pam_gnome_keyring "$pam_file" || {
      # auth: unlock the keyring with the login password
      echo "auth       optional     pam_gnome_keyring.so" | sudo tee -a "$pam_file" >/dev/null
      # session: auto-start the daemon
      echo "session    optional     pam_gnome_keyring.so auto_start" | sudo tee -a "$pam_file" >/dev/null
    }
  fi
done

# Set the default keyring password to empty so it auto-unlocks on autologin.
# Since we use LUKS disk encryption, the keyring password is redundant --
# the disk encryption IS the security boundary.
echo "==> Setting empty keyring password for autologin..."
keyring_dir="$HOME/.local/share/keyrings"
mkdir -p "$keyring_dir"
if [[ ! -f "$keyring_dir/default" ]]; then
  # Create the default keyring with an empty password
  cat > "$keyring_dir/Default_keyring.keyring" << 'KEYRING'
[keyring]
display-name=Default keyring
ctime=0
mtime=0
lock-on-idle=false
lock-after=false
KEYRING
  echo 'Default_keyring' > "$keyring_dir/default"
fi

# ── GPU hardware detection ────────────────────────────────────────────────────
# Must run while pacman.conf still points to the offline repo (before it is
# restored to standard online mirrors below).  Detects the installed GPU
# vendor/architecture and installs only the correct driver subset from the
# packages bundled in the ISO — fully offline.
echo "==> Detecting GPU hardware and installing drivers..."
for _hw_script in \
    "$SMPLOS_INSTALL/config/hardware/nvidia.sh" \
    "$SMPLOS_INSTALL/config/hardware/amd.sh" \
    "$SMPLOS_INSTALL/config/hardware/intel.sh"; do
  if [[ -f "$_hw_script" ]]; then
    bash "$_hw_script" || echo "    WARNING: $_hw_script exited with error $?"
  fi
done

# Setup greetd with autologin
echo "==> Setting up greetd autologin..."
sudo mkdir -p /etc/greetd

cat <<EOF | sudo tee /etc/greetd/config.toml
[terminal]
# Keep greeter off tty1 so Plymouth handoff does not flash console text
vt = "next"

[default_session]
command = "tuigreet --remember-session --cmd start-hyprland"
user = "greeter"

[initial_session]
command = "start-hyprland"
user = "$USER"
EOF

# Enable greetd
sudo systemctl enable greetd.service

# Setup Plymouth if installed
if command -v plymouth-set-default-theme &>/dev/null; then
  echo "==> Configuring Plymouth..."
  
  plymouth_dir="$HOME/.config/smplos/branding/plymouth"
  if [[ -d "$plymouth_dir" ]]; then
    sudo mkdir -p /usr/share/plymouth/themes/smplos
    sudo cp -r "$plymouth_dir/"* /usr/share/plymouth/themes/smplos/
    sudo plymouth-set-default-theme smplos
    
    # Replace Arch Linux watermark in spinner fallback theme with our logo
    if [[ -f "$plymouth_dir/logo.png" && -d /usr/share/plymouth/themes/spinner ]]; then
      sudo cp "$plymouth_dir/logo.png" /usr/share/plymouth/themes/spinner/watermark.png
    fi
  fi
  
  sudo mkdir -p /etc/mkinitcpio.conf.d
  sudo tee /etc/mkinitcpio.conf.d/smplos_hooks.conf <<EOF >/dev/null
HOOKS=(base udev plymouth autodetect microcode modconf kms keyboard keymap consolefont block encrypt filesystems fsck)
EOF

  # Configure silent boot in GRUB
  if [[ -f /etc/default/grub ]]; then
    # Ensure cleaner boot logs (always enforce missing params)
    current_cmdline=$(grep '^GRUB_CMDLINE_LINUX_DEFAULT=' /etc/default/grub | sed -E 's/^GRUB_CMDLINE_LINUX_DEFAULT="(.*)"/\1/' || true)
    # Force a quiet Plymouth→greeter transition (no status text flash)
    for arg in quiet splash plymouth.nolog loglevel=3 rd.udev.log_level=3 rd.systemd.show_status=false systemd.show_status=false vt.global_cursor_default=0 console=tty1 mce=dont_log_ce; do
      [[ " $current_cmdline " == *" $arg "* ]] || current_cmdline+=" $arg"
    done
    current_cmdline=$(echo "$current_cmdline" | xargs)
    sudo sed -i "s|^GRUB_CMDLINE_LINUX_DEFAULT=.*|GRUB_CMDLINE_LINUX_DEFAULT=\"$current_cmdline\"|" /etc/default/grub
    
    # Branding: Set GRUB Distributor to smplOS
    sudo sed -i 's/^GRUB_DISTRIBUTOR=.*/GRUB_DISTRIBUTOR="smplOS"/' /etc/default/grub

    sudo grub-mkconfig -o /boot/grub/grub.cfg
  fi

  # Delay plymouth-quit to ensure smooth transition
  sudo mkdir -p /etc/systemd/system/plymouth-quit.service.d/
  sudo tee /etc/systemd/system/plymouth-quit.service.d/wait-for-graphical.conf <<'EOF' >/dev/null
[Unit]
# Quit only after greeter/session handoff to avoid a text frame between splash and login
After=greetd.service systemd-user-sessions.service

[Service]
ExecStart=
ExecStart=/usr/bin/plymouth quit --retain-splash
EOF
  sudo systemctl mask plymouth-quit-wait.service

  # Rebuild initramfs to include plymouth and new hooks
  sudo mkinitcpio -P
fi

# Restore standard pacman.conf (remove offline mirror, point to real repos)
echo "==> Restoring standard pacman configuration..."
sudo tee /etc/pacman.conf > /dev/null << 'PACMANEOF'
[options]
HoldPkg     = pacman glibc brave-bin
Architecture = auto
ParallelDownloads = 5
SigLevel    = Required DatabaseOptional
LocalFileSigLevel = Optional
Color
VerbosePkgLists

[core]
Include = /etc/pacman.d/mirrorlist

[extra]
Include = /etc/pacman.d/mirrorlist

[multilib]
Include = /etc/pacman.d/mirrorlist
PACMANEOF

# Initialize mirrorlist with reliable defaults
if [[ ! -s /etc/pacman.d/mirrorlist ]] || grep -q 'file://' /etc/pacman.d/mirrorlist; then
  echo "==> Setting up mirrors..."
  sudo tee /etc/pacman.d/mirrorlist > /dev/null << 'MIRROREOF'
Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch
Server = https://mirror.rackspace.com/archlinux/$repo/os/$arch
Server = https://mirrors.kernel.org/archlinux/$repo/os/$arch
MIRROREOF
fi

# Run reflector to find the fastest mirrors for this user's location.
# Non-blocking: falls back to the defaults above if no internet or reflector fails.
if command -v reflector &>/dev/null; then
  echo "==> Finding fastest mirrors with reflector..."
  if timeout 30 sudo reflector \
      --protocol https \
      --age 6 \
      --latest 20 \
      --sort age \
      --save /etc/pacman.d/mirrorlist 2>/dev/null; then
    echo "    $(grep -c '^Server' /etc/pacman.d/mirrorlist) mirrors selected"
  else
    echo "    Reflector failed or timed out, using default mirrors"
  fi
fi

# Surface hardware: install linux-surface kernel + drivers online.
# The ISO ships with linux-zen only (keeps ISO size down). On Surface devices
# we add the linux-surface kernel alongside it so touch/pen/wifi work properly.
# Both kernels remain in GRUB — linux-surface as default, linux-zen as fallback.
# Requires internet; if offline, the system still works with linux-zen (no touch/pen).
# Runs AFTER mirrorlist is established so pacman can resolve dependencies.
if [[ "$(cat /sys/devices/virtual/dmi/id/sys_vendor 2>/dev/null)" == "Microsoft Corporation" ]] \
  && [[ "$(cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null)" == Surface* ]]; then
  echo "==> Surface device detected, setting up Surface-optimized kernel..."

  # Always configure the linux-surface repo + key, even if we can't install
  # right now. This way the user can install later with just `pacman -Sy`.
  if ! grep -q '^\[linux-surface\]' /etc/pacman.conf; then
    curl -s https://raw.githubusercontent.com/linux-surface/linux-surface/master/pkg/keys/surface.asc \
      | sudo pacman-key --add - 2>/dev/null || true
    sudo pacman-key --lsign-key 56C464BAAC421453 2>/dev/null || true
    echo -e '\n[linux-surface]\nServer = https://pkg.surfacelinux.com/arch/' \
      | sudo tee -a /etc/pacman.conf > /dev/null
  fi

  if curl -sf --max-time 10 --head https://pkg.surfacelinux.com >/dev/null 2>&1; then
    # Install Surface kernel + drivers (keeps linux-zen as fallback)
    if sudo pacman --noconfirm -Sy linux-surface linux-surface-headers iptsd linux-firmware-marvell; then
      # Enable touch/pen input daemon
      chrootable_systemctl_enable iptsd || echo "    WARNING: failed to enable iptsd service"
      # Rebuild GRUB config so linux-surface appears in the boot menu.
      # Set GRUB_DEFAULT=saved so we can make linux-surface the default
      # regardless of version-sort ordering.
      if [[ -f /boot/grub/grub.cfg ]]; then
        sudo sed -i 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT=saved/' /etc/default/grub 2>/dev/null || true
        sudo grub-mkconfig -o /boot/grub/grub.cfg || echo "    WARNING: grub-mkconfig failed"
        # Set the default to the first linux-surface entry
        sudo grub-set-default "$(grep -m1 'menuentry.*linux-surface' /boot/grub/grub.cfg | sed "s/menuentry '\\([^']*\\)'.*/\\1/")" 2>/dev/null || true
      fi
      echo "    Surface kernel installed successfully (linux-zen kept as fallback)"
    else
      echo "    WARNING: Surface package install failed, continuing with linux-zen"
    fi
  else
    echo "    No internet -- skipping Surface kernel install (linux-zen still works)"
    echo "    Run after connecting: sudo pacman -Sy linux-surface linux-surface-headers iptsd linux-firmware-marvell"
  fi
fi

# Clean up offline mirror cache
sudo rm -rf /var/cache/smplos/mirror 2>/dev/null || true

# Allow passwordless reboot after install - cleaned up on first boot
sudo tee /etc/sudoers.d/99-smplos-installer-reboot >/dev/null <<EOF
$USER ALL=(ALL) NOPASSWD: /usr/bin/reboot
EOF
sudo chmod 440 /etc/sudoers.d/99-smplos-installer-reboot

echo "==> smplOS installation complete!"

# Calculate installation duration
SMPLOS_END_EPOCH=$(date +%s)
SMPLOS_DURATION=$((SMPLOS_END_EPOCH - SMPLOS_START_EPOCH))
SMPLOS_MINS=$((SMPLOS_DURATION / 60))
SMPLOS_SECS=$((SMPLOS_DURATION % 60))

# Also try to get archinstall duration from its log
ARCH_TIME_STR=""
if [[ -f /var/log/archinstall/install.log ]]; then
  ARCH_START=$(grep -m1 '^\[' /var/log/archinstall/install.log 2>/dev/null | sed 's/^\[\([^]]*\)\].*/\1/' || true)
  ARCH_END=$(grep 'Installation completed without any errors' /var/log/archinstall/install.log 2>/dev/null | sed 's/^\[\([^]]*\)\].*/\1/' || true)
  if [[ -n "$ARCH_START" && -n "$ARCH_END" ]]; then
    ARCH_START_EPOCH=$(date -d "$ARCH_START" +%s 2>/dev/null || true)
    ARCH_END_EPOCH=$(date -d "$ARCH_END" +%s 2>/dev/null || true)
    if [[ -n "$ARCH_START_EPOCH" && -n "$ARCH_END_EPOCH" ]]; then
      ARCH_DURATION=$((ARCH_END_EPOCH - ARCH_START_EPOCH))
      ARCH_MINS=$((ARCH_DURATION / 60))
      ARCH_SECS=$((ARCH_DURATION % 60))
      ARCH_TIME_STR="Archinstall: ${ARCH_MINS}m ${ARCH_SECS}s"
      TOTAL_DURATION=$((ARCH_DURATION + SMPLOS_DURATION))
      TOTAL_MINS=$((TOTAL_DURATION / 60))
      TOTAL_SECS=$((TOTAL_DURATION % 60))
    fi
  fi
fi

# Log the timing summary
{
  echo "=== Installation Time Summary ==="
  [[ -n "$ARCH_TIME_STR" ]] && echo "$ARCH_TIME_STR"
  echo "smplOS:      ${SMPLOS_MINS}m ${SMPLOS_SECS}s"
  [[ -n "${TOTAL_MINS:-}" ]] && echo "Total:       ${TOTAL_MINS}m ${TOTAL_SECS}s"
  echo "================================="
} >>"$SMPLOS_INSTALL_LOG_FILE" 2>/dev/null || true

# Show reboot prompt (matching Omarchy's finished.sh)
clear
echo
gum style --foreground 2 --bold --padding "1 0 1 $PADDING_LEFT" "smplOS Installation Complete!"
echo

# Display installation time
if [[ -n "${TOTAL_MINS:-}" ]]; then
  gum style --foreground 6 --padding "0 0 0 $PADDING_LEFT" "Installed in ${TOTAL_MINS}m ${TOTAL_SECS}s (archinstall: ${ARCH_MINS}m ${ARCH_SECS}s + smplOS: ${SMPLOS_MINS}m ${SMPLOS_SECS}s)"
else
  gum style --foreground 6 --padding "0 0 0 $PADDING_LEFT" "Installed in ${SMPLOS_MINS}m ${SMPLOS_SECS}s"
fi
echo
gum style --foreground 3 --padding "0 0 1 $PADDING_LEFT" "Please remove the installation media (USB/CD) before rebooting."
echo

# Only prompt if using gum is available, otherwise just mark complete
if gum confirm --padding "0 0 0 $PADDING_LEFT" --show-help=false --default --affirmative "Reboot Now" --negative "" ""; then
  clear
  
  # If running in chroot, just mark complete and exit - outer script handles reboot
  if [[ -n "${SMPLOS_CHROOT_INSTALL:-}" ]]; then
    # Create marker BEFORE removing sudoers (while we still have NOPASSWD)
    sudo touch /var/tmp/smplos-install-completed
    # Remove installer sudoers override
    sudo rm -f /etc/sudoers.d/99-smplos-installer
    exit 0
  else
    # Not in chroot - cleanup and reboot directly
    sudo rm -f /etc/sudoers.d/99-smplos-installer
    sudo reboot 2>/dev/null
  fi
else
  # User declined reboot, just cleanup
  sudo rm -f /etc/sudoers.d/99-smplos-installer
fi
