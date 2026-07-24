#!/bin/bash
# Migration: Seed VS Code keybindings.json with Ctrl+Alt+C → focus Copilot Chat.
#
# Context: Companion to the nvidia+Hyprland black-screen recovery workflow.
#          The user needs a blind-typable way to reach the assistant when
#          DPMS wake leaves the display dark. Hyprland can't grab the key
#          (because if it did, VS Code would never see it). VS Code itself
#          binds Ctrl+Alt+C → workbench.action.chat.open, focusing the
#          Copilot chat input where blind typing lands correctly.
#
# Fix:     Copy the shipped keybindings.json into the user's VS Code config
#          IF they don't already have one. Never merges — user customisation
#          wins. Handles the fact that VS Code may not be installed yet.
#
# Safety:  Idempotent. Skips cleanly if:
#            - keybindings.json already exists (user has their own bindings)
#            - shipped template is missing (fleet not yet updated)
#            - VS Code isn't installed at all
#          Always exits 0.

set -uo pipefail

VSCODE_USER_DIR="$HOME/.config/Code/User"
KEYBINDINGS="$VSCODE_USER_DIR/keybindings.json"
# build.sh copies src/shared/configs/Code/User/keybindings.json into
# /etc/skel/.config/Code/User/keybindings.json (via its generic
# `cp -r src/shared/configs/* /etc/skel/.config/` at line ~1017), so
# on any smplOS install we can pick it up from there.
SHIPPED="/etc/skel/.config/Code/User/keybindings.json"

# Skip if template not shipped yet
if [[ ! -f "$SHIPPED" ]]; then
    echo "  keybindings.json template not shipped ($SHIPPED missing) — skipping"
    exit 0
fi

# Skip if user already has keybindings — respect their customisations
if [[ -f "$KEYBINDINGS" ]]; then
    if grep -q "workbench.action.chat.open" "$KEYBINDINGS" 2>/dev/null; then
        echo "  keybindings.json already has chat.open binding — nothing to do"
    else
        echo "  keybindings.json exists — leaving user customisations alone"
        echo "  (to get the black-screen shortcut, add this to the array:"
        echo "     { \"key\": \"ctrl+alt+c\", \"command\": \"workbench.action.chat.open\", \"when\": \"chatIsEnabled\" }"
        echo "  )"
    fi
    exit 0
fi

# Seed the file
mkdir -p "$VSCODE_USER_DIR" 2>/dev/null
if cp "$SHIPPED" "$KEYBINDINGS" 2>/dev/null; then
    echo "  seeded $KEYBINDINGS with Ctrl+Alt+C → focus Copilot Chat"
else
    echo "  WARNING: could not seed $KEYBINDINGS"
fi

exit 0
