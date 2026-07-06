#!/bin/bash
# Migration: Add the scrolling-layout side-by-side (column width) keybinds.
#
# Context: the scrolling layout (niri/PaperWM style) can show two windows side
#          by side by shrinking every column to a fraction of the screen, but no
#          key was bound to it — so Super+drag only ever moved a window, never
#          tiled two 50/50. These binds ship in the ISO's stock bindings.conf,
#          which is user/Settings-owned, so smplos-os-update never overwrites it.
#          EXISTING installs would miss the binds; this migration adds them once.
#
# Safety:  Append-only and idempotent. If the binds are already present (by the
#          `colresize` marker) it does nothing. It never edits or removes any
#          existing line.

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

# Idempotent: already migrated / user already has column-resize binds.
if grep -q 'colresize' "$BINDS" 2>/dev/null; then
    echo "  $BINDS already has side-by-side (colresize) binds, skipping"
    exit 0
fi

cat >> "$BINDS" << 'EOF'

# ── Scrolling side-by-side / column widths (added by smplOS migration) ───────
# The scrolling layout tiles windows on a horizontal tape. Super+- shrinks every
# column to 50% so two windows sit side by side; Super+= restores full columns.
# Super+Shift+-/= cycle the focused column through preset widths
# (0.333 / 0.5 / 0.667 / 1.0). This is the keyboard equivalent of a drag-snap:
# Hyprland's Super+drag (movewindow) has no drop-snap hook without a plugin.
bindd = SUPER, minus, Side-by-side (50/50 columns), layoutmsg, colresize all 0.5
bindd = SUPER, equal, Restore full-width columns, layoutmsg, colresize all 0.95
bindd = SUPER SHIFT, minus, Narrow focused column, layoutmsg, colresize -conf
bindd = SUPER SHIFT, equal, Widen focused column, layoutmsg, colresize +conf
EOF

echo "  Added scrolling side-by-side binds to $BINDS"

# Reload Hyprland so the new binds take effect immediately.
if hyprctl version &>/dev/null 2>&1; then
    hyprctl reload &>/dev/null 2>&1 && echo "  Reloaded Hyprland" || true
fi

exit 0
