#!/bin/bash
# smplOS Hyprland Post-installation Script
# Runs after packages are installed to configure Hyprland environment

set -e

echo "Configuring Hyprland environment..."

# Enable essential services
systemctl enable NetworkManager
systemctl enable bluetooth

# Enable pipewire for user
# This is typically done via user services, enabled by default

# Set default shell to fish for the user
if id "smplos" &>/dev/null; then
    chsh -s /usr/bin/fish smplos 2>/dev/null || true
fi

# Create XDG directories
sudo -u smplos mkdir -p /home/smplos/{Desktop,Documents,Downloads,Music,Pictures,Videos}
sudo -u smplos mkdir -p /home/smplos/Pictures/Screenshots
sudo -u smplos mkdir -p /home/smplos/Pictures/Wallpapers

# Ensure .config directory exists
sudo -u smplos mkdir -p /home/smplos/.config

# Set proper permissions
chown -R smplos:smplos /home/smplos

# Configure GTK3 theme (settings.ini)
sudo -u smplos mkdir -p /home/smplos/.config/gtk-3.0
cat > /home/smplos/.config/gtk-3.0/settings.ini << 'GTKEOF'
[Settings]
gtk-theme-name=Adwaita
gtk-icon-theme-name=Adwaita
gtk-font-name=JetBrains Mono 11
gtk-cursor-theme-name=Adwaita
gtk-application-prefer-dark-theme=1
gtk-overlay-scrolling=0
gtk-enable-mnemonics=1
gtk-auto-mnemonics=1
GTKEOF
chown smplos:smplos /home/smplos/.config/gtk-3.0/settings.ini

# Configure GTK4 theme (separate settings.ini — GTK4 ignores gtk-3.0's)
sudo -u smplos mkdir -p /home/smplos/.config/gtk-4.0
cat > /home/smplos/.config/gtk-4.0/settings.ini << 'GTKEOF'
[Settings]
gtk-theme-name=Adwaita
gtk-icon-theme-name=Adwaita
gtk-font-name=JetBrains Mono 11
gtk-cursor-theme-name=Adwaita
gtk-application-prefer-dark-theme=1
gtk-overlay-scrolling=0
gtk-enable-mnemonics=1
gtk-auto-mnemonics=1
GTKEOF
chown smplos:smplos /home/smplos/.config/gtk-4.0/settings.ini

# Configure dconf for Wayland (GTK3/4 on Wayland prefer dconf over settings.ini)
# Use dconf compile — works in chroot without dbus (unlike gsettings).
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
# Compile keyfile -> binary dconf database
dconf compile /home/smplos/.config/dconf/user "$_dconf_dir/user.d"
chown smplos:smplos /home/smplos/.config/dconf/user
rm -rf "$_dconf_dir"

# Ensure GTK_THEME reaches systemd user services (portals, etc.) on first boot.
# Hyprland's envs.conf sets it, but portal-gtk may D-Bus activate before
# autostart.conf runs 'systemctl --user import-environment'.
sudo -u smplos mkdir -p /home/smplos/.config/environment.d
cat > /home/smplos/.config/environment.d/gtk.conf << 'ENVD'
GTK_THEME=Adwaita:dark
ENVD
chown smplos:smplos /home/smplos/.config/environment.d/gtk.conf

# Configure Qt to use kvantum
echo "export QT_QPA_PLATFORMTHEME=qt5ct" >> /etc/environment

# Enable XDG portal environment variables
cat >> /etc/environment << 'ENVEOF'
XDG_CURRENT_DESKTOP=Hyprland
XDG_SESSION_TYPE=wayland
XDG_SESSION_DESKTOP=Hyprland
ENVEOF

echo "Hyprland configuration complete!"
