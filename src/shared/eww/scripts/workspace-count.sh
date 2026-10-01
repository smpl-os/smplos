#!/bin/bash
# EWW workspace-count listener
# Emits the number of workspace slots the bar should render.
#
# Under niri: live count of non-scratchpad workspaces (which always includes
# a trailing empty, so the bar grows when the user spawns a window on the
# last slot and niri appends a new empty workspace).
#
# Under Hyprland: static ws_count from ~/.config/smplos/bar.conf, re-emitted
# whenever bar.conf changes. bar-ctl also pushes ws-count directly so this
# script is just the initial seed + safety net under Hyprland.

bar_conf="$HOME/.config/smplos/bar.conf"

read_static_count() {
  local v=4 key val seen=false
  if [[ -e "$bar_conf" && ( ! -f "$bar_conf" || ! -r "$bar_conf" ) ]]; then
    echo "workspace-count: Cannot read $bar_conf" >&2
    return 1
  fi
  if [[ -f "$bar_conf" ]]; then
    while IFS='=' read -r key val || [[ -n "$key" ]]; do
      key="${key#"${key%%[![:space:]]*}"}"
      key="${key%"${key##*[![:space:]]}"}"
      [[ "$key" == ws_count ]] || continue
      if $seen; then
        echo "workspace-count: Duplicate ws_count in bar.conf" >&2
        return 1
      fi
      seen=true
      val="${val#"${val%%[![:space:]]*}"}"
      val="${val%"${val##*[![:space:]]}"}"
      if [[ ! "$val" =~ ^[0-9]+$ ]]; then
        echo "workspace-count: Invalid ws_count in bar.conf: expected a decimal integer" >&2
        return 1
      fi
      # Clamp legacy slots without octal interpretation or integer overflow.
      val="${val#"${val%%[!0]*}"}"
      if [[ -z "$val" ]]; then
        v=1
      elif [[ ${#val} -gt 2 ]]; then
        v=10
      else
        v=$((10#$val))
        if [[ $v -gt 10 ]]; then v=10; fi
      fi
    done < "$bar_conf" || { echo "workspace-count: Cannot read $bar_conf" >&2; return 1; }
  fi
  echo "$v"
}

emit_niri() {
  niri msg --json workspaces 2>/dev/null \
    | jq -r '[.[] | select(.name != "scratchpad")] | length' 2>/dev/null \
    || echo "1"
}

if [[ -n "$NIRI_SOCKET" ]] && command -v niri &>/dev/null; then
  emit_niri
  niri msg event-stream 2>/dev/null | while read -r line; do
    case "$line" in
      "Workspaces changed:"*|"Workspace activated:"*) emit_niri ;;
    esac
  done
else
  # Parse errors are logged without emitting a replacement for the last good
  # value. Keep watching so correcting bar.conf recovers without an EWW reload.
  read_static_count
  if command -v inotifywait &>/dev/null && [[ -d "$(dirname "$bar_conf")" ]]; then
    inotifywait -m -e modify -e create -e moved_to "$(dirname "$bar_conf")" 2>/dev/null \
      | while read -r _dir _events file; do
          [[ "$file" == "bar.conf" ]] && read_static_count
        done
  else
    while sleep 10; do read_static_count; done
  fi
fi
