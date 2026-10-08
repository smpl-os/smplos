#!/bin/sh
# Click on the keypad cheatsheet overlay (see KEYPAD.md): ask the keypad app to
# hide it; with no app to answer, close both overlay windows in this EWW.
busctl --user --timeout=2 call org.smplos.ControlSurface /org/smplos/ControlSurface \
    org.smplos.ControlSurface1 HideCheatsheet >/dev/null 2>&1 && exit 0
config=$(cd "$(dirname "$0")/.." && pwd)
timeout 5 eww --config "$config" close pad-cheatsheet pad-cheatsheet-passthrough >/dev/null 2>&1
timeout 5 eww --config "$config" update 'pad_sheet={"visible":false}' >/dev/null 2>&1
exit 0
