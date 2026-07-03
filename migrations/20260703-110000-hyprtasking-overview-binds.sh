#!/bin/bash
# Migration: Add the hyprtasking overview + native-scrolling keybinds.
#
# Context: the workspace overview (Super+Tab, hyprtasking plugin) and the
#          scrolling-layout column pan binds (Super+]/[/\) ship in the ISO's
#          ~/.config/smplos/bindings.conf. That file is user/Settings-owned, so
#          smplos-os-update never overwrites it — meaning EXISTING installs would
#          miss these binds. This migration adds them, once, without clobbering
#          anything the user already has.
#
# Safety:  Append-only and idempotent. If the binds are already present (by the
#          hyprtasking marker) it does nothing. It never edits or removes any
#          existing line. If a Super+Tab bind already exists, the appended
#          overview bind is added after it and wins (Hyprland uses the last
#          matching bind) — which is the intended behaviour here.

set -uo pipefail

# Primary binds file loaded by bindings_loader.lua; fall back to the hypr one.
BINDS=""
for candidate in "$HOME/.config/smplos/bindings.conf" "$HOME/.config/hypr/bindings.conf"; do
    if [[ -f "$candidate" ]]; then BINDS="$candidate"; break; fi
done

if [[ -z "$BINDS" ]]; then
    echo "  No bindings.conf found — nothing to do (new installs get these from the ISO)"
    exit 0
fi

# Idempotent: already migrated / user already has hyprtasking binds.
if grep -q 'hyprtasking' "$BINDS" 2>/dev/null; then
    echo "  $BINDS already has hyprtasking binds, skipping"
    exit 0
fi

cat >> "$BINDS" << 'EOF'

# ── Hyprtasking overview + native scrolling (added by smplOS migration) ──────
# Super+Tab opens the niri-style workspace overview (hyprtasking plugin). While
# it is open the mouse wheel navigates rows and Ctrl+wheel pans columns (see the
# is_active-gated binds in looknfeel.lua). Super+]/[ pan the scrolling-layout
# column tape; Super+\ centres the focused column.
bindd = SUPER, TAB, Overview (all workspaces), exec, hyprctl eval 'hl.plugin.hyprtasking.toggle("all")'
bindd = SUPER, bracketright, Scroll to next column, layoutmsg, move +col
bindd = SUPER, bracketleft, Scroll to previous column, layoutmsg, move -col
bindd = SUPER, backslash, Center focused column in view, layoutmsg, center
EOF

echo "  Added hyprtasking overview + scrolling binds to $BINDS"

# Reload Hyprland so the new binds take effect immediately.
if hyprctl version &>/dev/null 2>&1; then
    hyprctl reload &>/dev/null 2>&1 && echo "  Reloaded Hyprland" || true
fi

exit 0
