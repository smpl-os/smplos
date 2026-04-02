#!/bin/bash
# EWW keyboard layout listener
# Output: single-line JSON {"code":"EN","layout":"English (US)","xkb_layout":"us","xkb_variant":"","visible":"yes"}
# Only emits visible=yes when multiple layouts are configured.

# Check if multiple layouts are configured
has_multi_layout() {
  if [[ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]]; then
    local layouts
    layouts=$(hyprctl getoption input:kb_layout -j 2>/dev/null | jq -r '.str' 2>/dev/null)
    if [[ "$layouts" == *","* ]]; then
      return 0
    fi
  elif [[ -n "$DISPLAY" ]]; then
    local count
    count=$(setxkbmap -query 2>/dev/null | awk '/layout/{n=split($2,a,","); print n}')
    if (( count > 1 )); then
      return 0
    fi
  fi

  # Fallback 1: check Hyprland input.conf (persistent source)
  local input_conf="$HOME/.config/hypr/input.conf"
  if [[ -f "$input_conf" ]]; then
    local cfg_layouts
    cfg_layouts=$(sed -n 's/^\s*kb_layout\s*=\s*//p' "$input_conf" | head -n1 | tr -d '[:space:]' 2>/dev/null)
    if [[ "$cfg_layouts" == *","* ]]; then
      return 0
    fi
  fi

  return 1
}

# Map XKB layout name to short code
layout_to_code() {
  case "$1" in
    *English*|*US*|*UK*)    echo "EN" ;;
    *French*)               echo "FR" ;;
    *German*)               echo "DE" ;;
    *Spanish*)              echo "ES" ;;
    *Italian*)              echo "IT" ;;
    *Portuguese*)           echo "PT" ;;
    *Russian*)              echo "RU" ;;
    *Ukrainian*)            echo "UA" ;;
    *Polish*)               echo "PL" ;;
    *Czech*)                echo "CZ" ;;
    *Slovak*)               echo "SK" ;;
    *Hungarian*)            echo "HU" ;;
    *Romanian*)             echo "RO" ;;
    *Bulgarian*)            echo "BG" ;;
    *Croatian*)             echo "HR" ;;
    *Serbian*)              echo "RS" ;;
    *Slovenian*)            echo "SI" ;;
    *Bosnian*)              echo "BA" ;;
    *Macedonian*)           echo "MK" ;;
    *Dutch*)                echo "NL" ;;
    *Belgian*)              echo "BE" ;;
    *Danish*)               echo "DK" ;;
    *Norwegian*)            echo "NO" ;;
    *Swedish*)              echo "SE" ;;
    *Finnish*)              echo "FI" ;;
    *Icelandic*)            echo "IS" ;;
    *Estonian*)             echo "ET" ;;
    *Lithuanian*)           echo "LT" ;;
    *Latvian*)              echo "LV" ;;
    *Greek*)                echo "GR" ;;
    *Turkish*)              echo "TR" ;;
    *Hebrew*)               echo "HE" ;;
    *Arabic*)               echo "AR" ;;
    *Japanese*)             echo "JP" ;;
    *Korean*)               echo "KR" ;;
    *Chinese*)              echo "ZH" ;;
    *Georgian*)             echo "GE" ;;
    *Persian*)              echo "FA" ;;
    *Thai*)                 echo "TH" ;;
    *Vietnamese*)           echo "VI" ;;
    *Kazakh*)               echo "KZ" ;;
    *Uzbek*)                echo "UZ" ;;
    *Belarusian*)           echo "BY" ;;
    *Mongolian*)            echo "MN" ;;
    *)                      echo "${1:0:2}" ;;
  esac
}

emit() {
  local layout code visible xkb_layout xkb_variant

  if ! has_multi_layout; then
    echo '{"code":"","layout":"","xkb_layout":"","xkb_variant":"","visible":"no"}'
    return
  fi

  visible="yes"
  xkb_layout=""
  xkb_variant=""

  if [[ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]]; then
    layout=$(hyprctl devices -j 2>/dev/null | jq -r '
      [.keyboards[] | select(.name | test("power|button"; "i") | not)] |
      first | .active_keymap // "Unknown"' 2>/dev/null)

    # Resolve XKB layout/variant from config + active index
    local layouts variants active_idx
    layouts=$(hyprctl getoption input:kb_layout -j 2>/dev/null | jq -r '.str' 2>/dev/null)
    variants=$(hyprctl getoption input:kb_variant -j 2>/dev/null | jq -r '.str' 2>/dev/null)
    # Use active_layout_index (the correct field name in Hyprland)
    active_idx=$(hyprctl devices -j 2>/dev/null | jq -r '
      [.keyboards[] | select(.name | test("power|button"; "i") | not)] |
      first | .active_layout_index // 0' 2>/dev/null)

    # Split comma-separated lists and pick active index
    IFS=',' read -ra layout_arr <<< "$layouts"
    IFS=',' read -ra variant_arr <<< "$variants"
    # Strip empty entries (e.g. ",ru" -> ["ru"])
    local clean_layouts=() clean_variants=()
    for i in "${!layout_arr[@]}"; do
      local l="${layout_arr[$i]// /}"
      [[ -z "$l" ]] && continue
      clean_layouts+=("$l")
      clean_variants+=("${variant_arr[$i]:-}")
    done
    layout_arr=("${clean_layouts[@]}")
    variant_arr=("${clean_variants[@]}")
    xkb_layout="${layout_arr[$active_idx]:-${layout_arr[0]:-}}"
    xkb_variant="${variant_arr[$active_idx]:-}"
    xkb_layout="${xkb_layout// /}"
    xkb_variant="${xkb_variant// /}"
  elif [[ -n "$DISPLAY" ]]; then
    layout=$(setxkbmap -query 2>/dev/null | awk '/layout/{print $2}')
    xkb_layout="$layout"
  fi

  layout="${layout:-Unknown}"
  code=$(layout_to_code "$layout")

  jq -nc --arg code "$code" --arg layout "$layout" --arg xkb_layout "$xkb_layout" --arg xkb_variant "$xkb_variant" --arg visible "$visible" \
    '{code: $code, layout: $layout, xkb_layout: $xkb_layout, xkb_variant: $xkb_variant, visible: $visible}'
}

# Fast emit when we already know the layout name from an activelayout event.
# Parses xkb_layout/variant by matching the active_layout_index after the switch.
emit_from_event() {
  local event_layout="$1"

  if ! has_multi_layout; then
    echo '{"code":"","layout":"","xkb_layout":"","xkb_variant":"","visible":"no"}'
    return
  fi

  local code active_idx xkb_layout xkb_variant
  code=$(layout_to_code "$event_layout")

  # Resolve xkb code/variant using the (now-updated) active_layout_index
  local layouts variants
  layouts=$(hyprctl getoption input:kb_layout -j 2>/dev/null | jq -r '.str' 2>/dev/null)
  variants=$(hyprctl getoption input:kb_variant -j 2>/dev/null | jq -r '.str' 2>/dev/null)
  active_idx=$(hyprctl devices -j 2>/dev/null | jq -r '
    [.keyboards[] | select(.name | test("power|button"; "i") | not)] |
    first | .active_layout_index // 0' 2>/dev/null)

  IFS=',' read -ra layout_arr <<< "$layouts"
  IFS=',' read -ra variant_arr <<< "$variants"
  local clean_layouts=() clean_variants=()
  for i in "${!layout_arr[@]}"; do
    local l="${layout_arr[$i]// /}"
    [[ -z "$l" ]] && continue
    clean_layouts+=("$l")
    clean_variants+=("${variant_arr[$i]:-}")
  done
  layout_arr=("${clean_layouts[@]}")
  variant_arr=("${clean_variants[@]}")
  xkb_layout="${layout_arr[$active_idx]:-${layout_arr[0]:-}}"
  xkb_variant="${variant_arr[$active_idx]:-}"
  xkb_layout="${xkb_layout// /}"
  xkb_variant="${xkb_variant// /}"

  jq -nc --arg code "$code" --arg layout "$event_layout" --arg xkb_layout "$xkb_layout" --arg xkb_variant "$xkb_variant" \
    '{code: $code, layout: $layout, xkb_layout: $xkb_layout, xkb_variant: $xkb_variant, visible: "yes"}'
}

# Initial emit
emit

# Watch for layout changes
if [[ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]]; then
  socat -U - "UNIX-CONNECT:$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket2.sock" 2>/dev/null | \
    while IFS= read -r line; do
      if [[ "$line" == activelayout* ]]; then
        # Event format: activelayout>>DEVICE_NAME,LAYOUT_DISPLAY_NAME
        # Parse the layout name directly from the event — no re-query race.
        _payload="${line#*>>}"
        _name="${_payload#*,}"
        emit_from_event "$_name"
      fi
    done
elif [[ -n "$DISPLAY" ]] && command -v xkb-switch &>/dev/null; then
  xkb-switch -W 2>/dev/null | while IFS= read -r _; do emit; done
else
  # Fallback: poll
  while sleep 5; do emit; done
fi
