#!/bin/bash
# Migration: Remove EWW button click sleep workarounds
# Context: The EWW button widget had a pointer-grab bug on Wayland where
#          clicking a button that opens a window would leave the pointer grab
#          stuck, requiring the user to wiggle the mouse before clicking again.
#          We added "sleep 0.05 &&" workarounds to all tray button onclick
#          handlers. With the patched EWW binary (eww-0.6.0-2, which replaces
#          emit_activate() with manual CSS state management), the root cause
#          is fixed and the workarounds should be removed.

set -euo pipefail

EWW_YUCK="$HOME/.config/eww/eww.yuck"

if [[ ! -f "$EWW_YUCK" ]]; then
    echo "  eww.yuck not found, skipping"
    exit 0
fi

# Check if any sleep workarounds exist
if ! grep -q 'sleep 0\.05' "$EWW_YUCK"; then
    echo "  No sleep workarounds found in eww.yuck, already clean"
    exit 0
fi

# Remove "sleep 0.05 && " prefix and trailing " &" from onclick handlers
# Pattern: :onclick "sleep 0.05 && <command> &"  →  :onclick "<command>"
sed -i 's/:onclick "sleep 0\.05 && \(.*\) &"/:onclick "\1"/g' "$EWW_YUCK"

n_remaining=$(grep -c 'sleep 0\.05' "$EWW_YUCK" 2>/dev/null || echo "0")
if [[ "$n_remaining" -gt 0 ]]; then
    echo "  WARNING: $n_remaining sleep workaround(s) remain — manual check needed"
else
    echo "  Removed sleep workarounds from eww.yuck"
fi

# Restart EWW bar to pick up changes
if pgrep -x eww &>/dev/null; then
    eww --config "$HOME/.config/eww" kill 2>/dev/null || true
    sleep 0.5
    bar-ctl start 2>/dev/null || true
    echo "  Restarted EWW bar"
fi
