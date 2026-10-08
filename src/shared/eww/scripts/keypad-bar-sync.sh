#!/bin/sh
# One-shot, run by EWW when the bar opens or reloads (deflisten keypad-present;
# see KEYPAD.md). Prints whether the keypad app runs, and turns the cheatsheet
# icons on when this EWW started after the icon font was installed (a running
# EWW never sees a font added later). Then it exits: nothing watches anything.
# control-surface.service keeps keypad-present current afterwards.
config=$(cd "$(dirname "$0")/.." && pwd)
if systemctl --user is-active --quiet control-surface.service; then echo yes; else echo no; fi
font=$(fc-list -f '%{file}\n' 'smplOS Keypad Icons' 2>/dev/null | head -n1)
pid=$(pgrep -o -u "$(id -u)" -x eww 2>/dev/null)
age=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ')
if [ -f "$font" ] && [ -n "$age" ] && [ "$(stat -c %Y "$font")" -lt "$(( $(date +%s) - age ))" ]; then
    eww --config "$config" update pad_icons_font=yes >/dev/null 2>&1
fi
# EWW reads the line while this runs; exiting at once could race it.
sleep "${KEYPAD_SYNC_LINGER:-2}"
