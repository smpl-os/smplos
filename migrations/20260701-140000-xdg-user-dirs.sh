#!/bin/bash
# Migration: Define XDG user directories (fixes broken browser downloads)
# Context: smplOS never shipped a ~/.config/user-dirs.dirs, and the minimal
#          Hyprland session does not run xdg-user-dirs' login autostart. With no
#          user-dirs.dirs, `xdg-user-dir DOWNLOAD` (and the xdg-desktop-portal
#          GTK file chooser that Brave/Chromium use on Wayland) resolve every
#          XDG dir to $HOME itself instead of ~/Downloads, ~/Documents, etc.
#
#          Symptom this fixes: downloading a file in Brave (which uses the
#          Wayland portal "Save as" dialog) silently fails to land in
#          ~/Downloads — the file appears nowhere, Brave records no history
#          entry, yet re-downloading appends "(1)" because the in-session path
#          reservation persists. Root cause is the undefined XDG Download dir.
#
#          From this version on the file ships in /etc/skel/.config for fresh
#          installs (src/shared/configs/user-dirs.dirs). This migration brings
#          already-installed systems up to date.

set -euo pipefail

USER_DIRS="$HOME/.config/user-dirs.dirs"

# Idempotent guard: only act when the file is missing. Never clobber a user's
# existing (possibly customized) user-dirs.dirs.
if [[ -f "$USER_DIRS" ]]; then
    echo "  user-dirs.dirs already exists — nothing to do"
    exit 0
fi

mkdir -p "$HOME/.config"

# Prefer the canonical copy from the cloned repo; fall back to writing inline.
SMPLOS_PATH="${SMPLOS_PATH:-$HOME/.local/share/smplos}"
REPO_SRC="$SMPLOS_PATH/repo/src/shared/configs/user-dirs.dirs"

if [[ -f "$REPO_SRC" ]]; then
    cp "$REPO_SRC" "$USER_DIRS"
else
    cat > "$USER_DIRS" <<'EOF'
# This file is written by xdg-user-dirs-update
# If you want to change or add directories, just edit the line you're
# interested in. All local changes will be retained on the next run.
# Format is XDG_xxx_DIR="$HOME/yyy", where yyy is a shell-escaped
# homedir-relative path, or XDG_xxx_DIR="/yyy", where /yyy is an
# absolute path. No other format is supported.
#
XDG_DESKTOP_DIR="$HOME/Desktop"
XDG_DOWNLOAD_DIR="$HOME/Downloads"
XDG_TEMPLATES_DIR="$HOME/Templates"
XDG_PUBLICSHARE_DIR="$HOME/Public"
XDG_DOCUMENTS_DIR="$HOME/Documents"
XDG_MUSIC_DIR="$HOME/Music"
XDG_PICTURES_DIR="$HOME/Pictures"
XDG_VIDEOS_DIR="$HOME/Videos"
EOF
fi
chmod 0644 "$USER_DIRS"

# Create the standard directories so the file chooser targets exist.
mkdir -p "$HOME/Desktop" "$HOME/Downloads" "$HOME/Documents"

echo "  Created $USER_DIRS — XDG Downloads now resolves to ~/Downloads"
echo "  (fixes Brave/Chromium downloads silently missing on Wayland)"
