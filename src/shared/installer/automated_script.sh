#!/usr/bin/env bash
#
# smplOS live-session entry point
# Modelled after the vanilla Arch releng automated_script.sh:
#   1. If kernel cmdline has script=<url|path>, download/run it (automated install).
#   2. Otherwise launch the interactive smplOS gum configurator.
#
# Chain: getty autologin → zsh → /root/.zlogin → this script
#

# ── Vanilla Arch: automated install via kernel cmdline ──────────────────────
# Pass script=https://... or script=/path/to/script on the kernel cmdline to
# run an unattended install (CI, PXE, etc.).  Matches vanilla Arch behaviour.

script_cmdline() {
    local param
    for param in $(</proc/cmdline); do
        case "${param}" in
            script=*)
                echo "${param#*=}"
                return 0
                ;;
        esac
    done
}

automated_script() {
    local script rt
    script="$(script_cmdline)"
    if [[ -n "${script}" && ! -x /tmp/startup_script ]]; then
        if [[ "${script}" =~ ^((http|https|ftp|tftp)://) ]]; then
            printf '%s: waiting for network-online.target\n' "$0"
            until systemctl --quiet is-active network-online.target; do
                sleep 1
            done
            printf '%s: downloading %s\n' "$0" "${script}"
            curl "${script}" --location --retry-connrefused --retry 10 --fail -s \
                -o /tmp/startup_script
            rt=$?
        else
            cp "${script}" /tmp/startup_script
            rt=$?
        fi
        if [[ ${rt} -eq 0 ]]; then
            chmod +x /tmp/startup_script
            printf '%s: executing automated script\n' "$0"
            /tmp/startup_script
        fi
        return 0   # automated path done, skip interactive installer
    fi
    return 1       # no script= param, caller should run interactive installer
}

# ── smplOS installer helpers ─────────────────────────────────────────────────

use_smplos_helpers() {
  export SMPLOS_PATH="/root/smplos"
  export SMPLOS_INSTALL="/root/smplos/install"
  export SMPLOS_INSTALL_LOG_FILE="/var/log/smplos-install.log"
  source /root/smplos/install/helpers/all.sh
}

run_configurator() {
  chmod +x /root/configurator 2>/dev/null || true
  /root/configurator
  export SMPLOS_USER="$(jq -r '.users[0].username' user_credentials.json)"
}

install_arch() {
  clear_logo
  gum style --foreground 3 --padding "1 0 0 $PADDING_LEFT" "Installing smplOS..."
  echo

  touch /var/log/smplos-install.log

  start_log_output

  CURRENT_SCRIPT="install_base_system"
  install_base_system > >(sed -u 's/\x1b\[[0-9;]*[a-zA-Z]//g' >>/var/log/smplos-install.log) 2>&1
  unset CURRENT_SCRIPT
  stop_log_output
}

install_smplos() {
  # Install gum in chroot for any additional prompts
  chroot_bash -lc "sudo pacman -S --noconfirm --needed gum" >/dev/null 2>&1 || true
  
  # Run the smplOS installer script (matching Omarchy's approach exactly)
  # The || bash fallback ensures we don't exit on error
  chroot_bash -lc "source /home/$SMPLOS_USER/.local/share/smplos/install.sh || bash"

  # Reboot if installation completed successfully (matching Omarchy exactly)
  if [[ -f /mnt/var/tmp/smplos-install-completed ]]; then
    # Ensure GRUB is first in the UEFI boot order
    # archinstall creates the entry but may not set it as first
    if command -v efibootmgr &>/dev/null && efibootmgr &>/dev/null 2>&1; then
      # Find the GRUB boot entry number
      local grub_bootnum=$(efibootmgr | grep -i "grub\|smplos\|arch" | grep -vi "USB\|CD\|DVD" | head -1 | sed 's/Boot\([0-9A-Fa-f]*\).*/\1/')
      if [[ -n "$grub_bootnum" ]]; then
        # Get current boot order
        local current_order=$(efibootmgr | grep "BootOrder" | sed 's/BootOrder: //')
        # Put GRUB first in boot order if it's not already
        if [[ "$current_order" != "$grub_bootnum"* ]]; then
          # Remove grub_bootnum from current order and prepend it
          local new_order="$grub_bootnum"
          for entry in ${current_order//,/ }; do
            [[ "$entry" != "$grub_bootnum" ]] && new_order="$new_order,$entry"
          done
          efibootmgr --bootorder "$new_order" >/dev/null 2>&1 || true
        fi
      fi
    fi
    reboot
  fi
}

# Set Catppuccin Mocha color scheme for the terminal
set_catppuccin_colors() {
  if [[ $(tty) == "/dev/tty"* ]]; then
    # Catppuccin Mocha color palette
    echo -en "\e]P01e1e2e" # black (background - base)
    echo -en "\e]P1f38ba8" # red
    echo -en "\e]P2a6e3a1" # green
    echo -en "\e]P3f9e2af" # yellow
    echo -en "\e]P489b4fa" # blue
    echo -en "\e]P5cba6f7" # magenta (mauve)
    echo -en "\e]P694e2d5" # cyan (teal)
    echo -en "\e]P7cdd6f4" # white (text)
    echo -en "\e]P8585b70" # bright black (surface2)
    echo -en "\e]P9f38ba8" # bright red
    echo -en "\e]PAa6e3a1" # bright green
    echo -en "\e]PBf9e2af" # bright yellow
    echo -en "\e]PC89b4fa" # bright blue
    echo -en "\e]PDcba6f7" # bright magenta
    echo -en "\e]PE94e2d5" # bright cyan
    echo -en "\e]PFcdd6f4" # bright white (text)

    echo -en "\033[0m"
    clear
  fi
}

# Set Matrix-style color scheme for the terminal (bright green on black)
set_matrix_colors() {
  if [[ $(tty) == "/dev/tty"* ]]; then
    # Set a Unicode-capable console font (box-drawing characters)
    setfont ter-v22n 2>/dev/null || true

    # Matrix color palette - bright green on pure black
    echo -en "\e]P0000000" # black (background - pure black)
    echo -en "\e]P100ff00" # red -> green
    echo -en "\e]P200ff00" # green (bright green)
    echo -en "\e]P300ff00" # yellow -> green
    echo -en "\e]P400ff00" # blue -> green
    echo -en "\e]P500ff00" # magenta -> green
    echo -en "\e]P600ff00" # cyan -> green
    echo -en "\e]P700ff00" # white (text - bright green)
    echo -en "\e]P8003300" # bright black (dim green)
    echo -en "\e]P900ff00" # bright red -> green
    echo -en "\e]PA00ff00" # bright green
    echo -en "\e]PB00ff00" # bright yellow -> green
    echo -en "\e]PC00ff00" # bright blue -> green
    echo -en "\e]PD00ff00" # bright magenta -> green
    echo -en "\e]PE00ff00" # bright cyan -> green
    echo -en "\e]PF00ff00" # bright white (bright green)

    echo -en "\033[0m"
    clear
  fi
}

install_base_system() {
  # Fix GPG homedir permissions to suppress warnings
  mkdir -p /root/.gnupg
  chmod 700 /root/.gnupg
  
  # Initialize and populate the keyring
  pacman-key --init
  pacman-key --populate archlinux

  # Sync the offline database so pacman can find packages
  pacman -Sy --noconfirm

  # Ensure that no mounts exist from past install attempts
  findmnt -R /mnt >/dev/null && umount -R /mnt

  # Install using files generated by the ./configurator
  archinstall \
    --config user_configuration.json \
    --creds user_credentials.json \
    --silent \
    --skip-ntp \
    --skip-wkd \
    --skip-wifi-check

  # Copy pacman.conf to installed system
  cp /etc/pacman.conf /mnt/etc/pacman.conf

  # Mount the offline mirror so it's accessible in the chroot
  mkdir -p /mnt/var/cache/smplos/mirror/offline
  mount --bind /var/cache/smplos/mirror/offline /mnt/var/cache/smplos/mirror/offline

  # No need to ask for sudo during the installation
  mkdir -p /mnt/etc/sudoers.d
  cat >/mnt/etc/sudoers.d/99-smplos-installer <<EOF
root ALL=(ALL:ALL) NOPASSWD: ALL
%wheel ALL=(ALL:ALL) NOPASSWD: ALL
$SMPLOS_USER ALL=(ALL:ALL) NOPASSWD: ALL
EOF
  chmod 440 /mnt/etc/sudoers.d/99-smplos-installer

  # Copy the local smplos config to the user's home directory
  mkdir -p /mnt/home/$SMPLOS_USER/.local/share/
  cp -r /root/smplos /mnt/home/$SMPLOS_USER/.local/share/

  chown -R 1000:1000 /mnt/home/$SMPLOS_USER/.local/

  # Ensure all necessary scripts are executable
  find /mnt/home/$SMPLOS_USER/.local/share/smplos -type f -path "*/bin/*" -exec chmod +x {} \;
  find /mnt/home/$SMPLOS_USER/.local/share/smplos -type f -path "*/scripts/*.sh" -exec chmod +x {} \;
  chmod +x /mnt/home/$SMPLOS_USER/.local/share/smplos/install.sh 2>/dev/null || true

  # Deploy smplOS scripts to the installed system's /usr/local/bin/
  # These are our custom scripts (theme-picker, theme-set, bar-ctl, etc.)
  if [[ -d /root/smplos/bin ]]; then
    cp -r /root/smplos/bin/* /mnt/usr/local/bin/ 2>/dev/null || true
    chmod +x /mnt/usr/local/bin/* 2>/dev/null || true
  fi

  # Copy AppImages to installed system
  if ls /opt/appimages/*.AppImage &>/dev/null; then
    mkdir -p /mnt/opt/appimages
    cp /opt/appimages/*.AppImage /mnt/opt/appimages/
    chmod +x /mnt/opt/appimages/*.AppImage
  fi

  # Copy Flatpak install list to installed system
  if [[ -f /opt/flatpaks/install-online.txt ]]; then
    mkdir -p /mnt/opt/flatpaks
    cp /opt/flatpaks/install-online.txt /mnt/opt/flatpaks/
  fi
}

chroot_bash() {
  HOME=/home/$SMPLOS_USER \
    arch-chroot -u $SMPLOS_USER /mnt/ \
    env SMPLOS_CHROOT_INSTALL=1 \
    SMPLOS_PRIMARY_XKB="$(<user_primary_xkb.txt)" \
    SMPLOS_EXTRA_LAYOUT="$(<user_extra_layout.txt)" \
    SMPLOS_EXTRA_VARIANT="$(<user_extra_variant.txt)" \
    USER="$SMPLOS_USER" \
    HOME="/home/$SMPLOS_USER" \
    /bin/bash "$@"
}

if [[ $(tty) == "/dev/tty1" ]]; then
  # Vanilla Arch: run automated script if script= was passed on kernel cmdline
  if automated_script; then
    # Automated path ran — don't start the interactive installer
    exit 0
  fi

  # Interactive path — launch the smplOS gum configurator
  use_smplos_helpers
  set_matrix_colors
  run_configurator
  install_arch
  install_smplos
fi
