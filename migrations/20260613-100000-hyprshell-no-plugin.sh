#!/bin/bash
# Migration: Suppress hyprshell "Unable to load hyprland plugin" notification
# Context: Since Hyprland 0.55, hyprshell tries to build its plugin at runtime
#          against the current Hyprland headers, but the build fails because
#          of include-path mismatches in upstream Hyprland headers. Hyprshell
#          falls back to default keybinds and Alt-Tab still works fine, but
#          the user sees a scary notification on every boot and config reload.
#
#          Setting HYPRSHELL_NO_USE_PLUGIN=1 tells hyprshell to skip the plugin
#          attempt entirely. This is the upstream-supported way to silence it.
#          We ship this as a system-wide systemd user drop-in.

set -euo pipefail

DROPIN_DIR="/etc/systemd/user/hyprshell.service.d"
DROPIN="$DROPIN_DIR/no-plugin.conf"

if [[ -f "$DROPIN" ]] && grep -q "HYPRSHELL_NO_USE_PLUGIN=1" "$DROPIN"; then
    echo "  hyprshell no-plugin drop-in already present, skipping"
    exit 0
fi

echo "  Writing $DROPIN"
sudo mkdir -p "$DROPIN_DIR"
sudo tee "$DROPIN" >/dev/null << 'EOF'
[Service]
Environment=HYPRSHELL_NO_USE_PLUGIN=1
EOF

echo "  Reloading systemd user units"
systemctl --user daemon-reload 2>/dev/null || true

if systemctl --user is-active --quiet hyprshell.service 2>/dev/null; then
    echo "  Restarting hyprshell"
    systemctl --user restart hyprshell.service || true
fi

echo "  Done — the plugin warning will no longer appear"
