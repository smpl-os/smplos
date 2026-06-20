#!/bin/bash
# EWW battery listener
# Output: single-line JSON {"present","level","status","icon","low"}
#
# Hardware detection: scans /sys/class/power_supply/* for entries whose
# `type` is exactly "Battery" (filters out AC adapters, USB-PD chargers, and
# peripheral batteries like wireless mice/keyboards). If no system battery is
# present we emit one "absent" line and exit -- the tray widget is gated by
# `present == "yes"` so it stays hidden forever with zero overhead on desktops.
#
# Icon glyph is delegated to `sysinfo --battery-icon` to avoid duplicating
# Nerd Font codepoints in two places. Shape carries state (filled bolt =
# charging, increasingly-filled body = level, alert = low) and the `low` flag
# triggers a CSS color shift -- shape + color, never color alone.

set -u

# -- Detect the first real system battery ------------------------------------
BAT_PATH=""
for d in /sys/class/power_supply/*/; do
  [[ -r "$d/type" ]] || continue
  t=$(cat "$d/type" 2>/dev/null) || continue
  [[ "$t" == "Battery" ]] || continue
  # Skip peripheral batteries -- they live under a hid scope, not the AC root
  case "$(basename "$d")" in
    hid-*|hidpp_battery_*) continue ;;
  esac
  BAT_PATH="${d%/}"
  break
done

# No battery -> emit one absent line and exit. EWW keeps last value, widget hides.
if [[ -z "$BAT_PATH" ]]; then
  printf '{"present":"no","level":"0","status":"Unknown","icon":"","low":"no"}\n'
  exit 0
fi

emit() {
  local lvl="0" st="Unknown" low="no" icon
  [[ -r "$BAT_PATH/capacity" ]] && lvl=$(cat "$BAT_PATH/capacity" 2>/dev/null || echo 0)
  [[ -r "$BAT_PATH/status"   ]] && st=$(cat "$BAT_PATH/status"   2>/dev/null || echo Unknown)
  # Clamp to 0..100 (some firmware briefly reports >100 during calibration)
  [[ "$lvl" =~ ^[0-9]+$ ]] || lvl=0
  (( lvl > 100 )) && lvl=100
  # Low-battery flag: <=15% AND not charging -> CSS .low triggers warning color
  if (( lvl <= 15 )) && [[ "$st" != "Charging" && "$st" != "Full" ]]; then
    low="yes"
  fi
  # Delegate icon selection to sysinfo for proven-working glyph bytes
  icon=$(sysinfo --battery-icon 2>/dev/null)
  printf '{"present":"yes","level":"%s","status":"%s","icon":"%s","low":"%s"}\n' \
    "$lvl" "$st" "$icon" "$low"
}

emit

# Poll: 10 s is enough -- battery changes are slow and there's no reliable
# kernel uevent for capacity updates on most laptops.
while sleep 10; do emit; done
