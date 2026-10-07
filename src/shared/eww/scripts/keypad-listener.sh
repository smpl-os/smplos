#!/bin/bash
# EWW macro keypad listener
# Output: single-line JSON from `keypad-ctl watch`, re-emitted on USB hotplug:
# {"present","state":"ready|bootloader|absent","count","tooltip","devices":[...],"bootloaders":[...]}
# Detection reads sysfs only (see KEYPAD.md); the keypad is never opened here.

if command -v keypad-ctl &>/dev/null; then
  exec keypad-ctl watch
fi

echo '{"present":"no","state":"absent","count":"0","tooltip":"","devices":[],"bootloaders":[]}'
exec sleep infinity
