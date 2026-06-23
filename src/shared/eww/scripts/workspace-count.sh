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
  local v=4
  if [[ -f "$bar_conf" ]]; then
    local _ws
    _ws=$(grep -m1 '^ws_count=' "$bar_conf" 2>/dev/null | cut -d= -f2 || true)
    [[ -n "$_ws" && "$_ws" =~ ^[0-9]+$ ]] && v=$_ws
  fi
  [[ $v -lt 1 ]] && v=1
  [[ $v -gt 10 ]] && v=10
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
