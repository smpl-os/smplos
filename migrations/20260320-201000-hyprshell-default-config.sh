#!/bin/bash
# Migration: Deploy default hyprshell config
# Context: hyprshell (Alt-Tab window switcher) was spamming "config not found"
#          errors on boot because we never shipped a config.ron. This creates
#          the default config with switch mode (Alt-Tab) enabled and overview
#          (launcher) disabled since smplOS uses its own EWW-based start-menu.

set -euo pipefail

HYPRSHELL_DIR="$HOME/.config/hyprshell"

# Only deploy if no config exists yet (don't overwrite user customizations)
if [[ -f "$HYPRSHELL_DIR/config.ron" ]]; then
    echo "  hyprshell config already exists, skipping"
    exit 0
fi

mkdir -p "$HYPRSHELL_DIR"

cat > "$HYPRSHELL_DIR/config.ron" << 'EOF'
// smplOS hyprshell config — Alt-Tab window switcher only
// Overview/launcher disabled (smplOS uses its own EWW-based start-menu)
// Edit with `hyprshell config edit`
(
    version: 3,
    windows: (
        scale: 8.5,
        items_per_row: 5,
        switch: (
            modifier: "alt",
        ),
    ),
)
EOF

echo "  Created hyprshell config at $HYPRSHELL_DIR/config.ron"

# Restart hyprshell if running so it picks up the new config
if pgrep -x hyprshell &>/dev/null; then
    pkill -x hyprshell 2>/dev/null || true
    sleep 0.3
    nohup hyprshell run &>/dev/null &
    disown
    echo "  Restarted hyprshell"
fi
