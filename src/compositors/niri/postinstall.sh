#!/bin/bash
# smplOS Niri Post-installation Script
# Runs after packages are installed to configure niri environment.
# Mirrors src/compositors/hyprland/postinstall.sh — only the bits that
# would differ for niri are duplicated; the rest is the same baseline.

set -e

echo "Configuring niri environment..."

# Enable essential services
systemctl enable NetworkManager
systemctl enable bluetooth

# Set default shell to fish for the user
if id "smplos" &>/dev/null; then
    chsh -s /usr/bin/fish smplos 2>/dev/null || true
fi

# Create XDG directories
sudo -u smplos mkdir -p /home/smplos/{Desktop,Documents,Downloads,Music,Pictures,Videos}
sudo -u smplos mkdir -p /home/smplos/Pictures/Screenshots
sudo -u smplos mkdir -p /home/smplos/Pictures/Wallpapers
sudo -u smplos mkdir -p /home/smplos/.config

chown -R smplos:smplos /home/smplos

# GTK theme (settings.ini) — same as hyprland postinstall
for ver in 3.0 4.0; do
  sudo -u smplos mkdir -p "/home/smplos/.config/gtk-$ver"
  cat > "/home/smplos/.config/gtk-$ver/settings.ini" << 'GTKEOF'
[Settings]
gtk-theme-name=Adwaita
gtk-icon-theme-name=Adwaita
gtk-font-name=JetBrains Mono 11
gtk-cursor-theme-name=Adwaita
gtk-application-prefer-dark-theme=1
gtk-overlay-scrolling=0
gtk-enable-mnemonics=0
gtk-auto-mnemonics=1
GTKEOF
  chown smplos:smplos "/home/smplos/.config/gtk-$ver/settings.ini"
done

# dconf (Wayland GTK reads from here)
sudo -u smplos mkdir -p /home/smplos/.config/dconf
_dconf_dir=$(mktemp -d)
mkdir -p "$_dconf_dir/user.d"
cat > "$_dconf_dir/user.d/00-smplos" << 'DCONF'
[org/gnome/desktop/interface]
gtk-theme='Adwaita-dark'
color-scheme='prefer-dark'
icon-theme='Adwaita'
cursor-theme='Adwaita'
font-name='JetBrains Mono 11'
DCONF
dconf compile /home/smplos/.config/dconf/user "$_dconf_dir/user.d"
chown smplos:smplos /home/smplos/.config/dconf/user
rm -rf "$_dconf_dir"

# Ensure GTK_THEME reaches systemd user services
sudo -u smplos mkdir -p /home/smplos/.config/environment.d
cat > /home/smplos/.config/environment.d/gtk.conf << 'ENVD'
GTK_THEME=Adwaita:dark
ENVD
chown smplos:smplos /home/smplos/.config/environment.d/gtk.conf

# Qt
echo "export QT_QPA_PLATFORMTHEME=qt5ct" >> /etc/environment

# XDG identity — niri uses its own value
cat >> /etc/environment << 'ENVEOF'
XDG_CURRENT_DESKTOP=niri
XDG_SESSION_TYPE=wayland
XDG_SESSION_DESKTOP=niri
ENVEOF

# xdg-desktop-portal-gnome is the recommended portal for niri (handles
# file-pickers, screen-sharing). Make sure its service starts on session.
# (Enabled per-user by xdg-desktop-portal.service automatically.)

echo "niri configuration complete!"
