#!/bin/bash
# Migration: Set micro as default editor, remove nvim hardcoding
# Context: smplOS switched from neovim/LazyVim to micro as the default text
#          editor. This migration updates existing installs:
#          - mimeapps.list: add text/plain and source MIME types → micro.desktop
#          - bash aliases: n() uses $EDITOR instead of hardcoded nvim
#          - fish n.fish: uses $EDITOR instead of hardcoded nvim
#          - dictation-settings: uses $EDITOR instead of nvim/nano chain

set -euo pipefail

n_changes=0

# ── mimeapps.list: add text MIME types for micro ─────────────────────────────
MIMEAPPS="$HOME/.config/mimeapps.list"
if [[ -f "$MIMEAPPS" ]]; then
    if ! grep -q 'text/plain=micro.desktop' "$MIMEAPPS"; then
        # Append text MIME types under [Default Applications]
        cat >> "$MIMEAPPS" << 'MIME'
text/plain=micro.desktop
text/x-csrc=micro.desktop
text/x-chdr=micro.desktop
text/x-c++src=micro.desktop
text/x-c++hdr=micro.desktop
text/x-java=micro.desktop
text/x-python=micro.desktop
text/x-shellscript=micro.desktop
text/x-script.python=micro.desktop
text/x-makefile=micro.desktop
text/x-markdown=micro.desktop
text/css=micro.desktop
text/xml=micro.desktop
application/json=micro.desktop
application/x-yaml=micro.desktop
application/toml=micro.desktop
application/x-shellscript=micro.desktop
MIME
        echo "  Added text MIME types → micro.desktop in mimeapps.list"
        ((n_changes++)) || true
    fi
else
    echo "  mimeapps.list not found, skipping MIME defaults"
fi

# ── bash aliases: n() → $EDITOR ─────────────────────────────────────────────
BASH_ALIASES="$HOME/.config/bash/aliases"
if [[ -f "$BASH_ALIASES" ]]; then
    if grep -q 'nvim' "$BASH_ALIASES"; then
        sed -i 's|n() { if \[ "\$#" -eq 0 \]; then nvim \.; else nvim "\$@"; fi; }|n() { if [ "$#" -eq 0 ]; then ${EDITOR:-micro} .; else ${EDITOR:-micro} "$@"; fi; }|' "$BASH_ALIASES"
        echo "  Updated bash n() alias: nvim → \$EDITOR"
        ((n_changes++)) || true
    fi
fi

# ── fish n.fish: → $EDITOR ──────────────────────────────────────────────────
FISH_N="$HOME/.config/fish/functions/n.fish"
if [[ -f "$FISH_N" ]]; then
    if grep -q 'nvim' "$FISH_N"; then
        cat > "$FISH_N" << 'FISH'
function n --description 'Open editor (current dir if no args)'
    set -l ed (command -v $EDITOR; or echo micro)
    if test (count $argv) -eq 0
        $ed .
    else
        $ed $argv
    end
end
FISH
        echo "  Updated fish n function: nvim → \$EDITOR"
        ((n_changes++)) || true
    fi
fi

# ── dictation-settings: → $EDITOR ───────────────────────────────────────────
DICTATION="/usr/local/bin/dictation-settings"
if [[ -f "$DICTATION" ]] && grep -q 'nvim' "$DICTATION"; then
    # This script is managed by smplos-os-update (bin/ sync), so it will
    # be overwritten on next OS update anyway. Patch it for immediate effect.
    sudo sed -i '/command -v nvim/,/^fi$/c\terminal -e ${EDITOR:-micro} "$cfg"' "$DICTATION" 2>/dev/null \
        && { echo "  Updated dictation-settings: nvim → \$EDITOR"; ((n_changes++)) || true; } \
        || echo "  dictation-settings: could not patch (will be fixed on next OS update)"
fi

if [[ $n_changes -eq 0 ]]; then
    echo "  Already migrated, nothing to do"
else
    echo "  Applied $n_changes change(s)"
fi
