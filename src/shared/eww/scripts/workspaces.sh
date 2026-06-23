#!/bin/bash
# EWW workspaces listener (Hyprland + niri)
# Emits the sorted list of occupied workspace GROUP numbers (1-10).
# Secondary-monitor workspaces (11-20) are normalized to their group (1-10)
# and deduplicated, so the bar always shows a single set of group dots.

emit_hyprland() {
  hyprctl workspaces -j 2>/dev/null \
    | jq -c '[.[].id | ((. - 1) % 10) + 1] | unique | sort' \
    || echo '[]'
}

emit_niri() {
  # On niri we predeclare workspaces "g1".."g10" (see compositors/niri/
  # config.kdl). The bar shows a dot for any workspace that has windows.
  # Filter to our predeclared "g<digit>" names, strip the prefix, return
  # the sorted unique list. Anonymous/dynamic workspaces are ignored.
  niri msg --json workspaces 2>/dev/null \
    | jq -c '[.[]
              | select(.active_window_id != null)
              | (.name // "" | capture("^g(?<n>[0-9]+)$").n // empty)
              | tonumber]
             | unique | sort' \
    || echo '[]'
}

emit() {
  if [[ -n "$NIRI_SOCKET" ]] && command -v niri &>/dev/null; then
    emit_niri
  elif command -v hyprctl &>/dev/null && command -v jq &>/dev/null; then
    emit_hyprland
  else
    echo '[]'
  fi
}

emit

if [[ -n "$NIRI_SOCKET" ]] && command -v niri &>/dev/null; then
  # niri event-stream uses debug-print, not JSON. We don't parse the event
  # body — we just re-poll whenever a workspace or window event fires.
  niri msg event-stream 2>/dev/null | while read -r line; do
    case "$line" in
      "Workspaces changed:"*|"Workspace activated:"*|"Window opened"*|"Window closed"*|"Windows changed:"*|"Window 0"*) emit ;;
    esac
  done
else
  sock="$XDG_RUNTIME_DIR/hypr/${HYPRLAND_INSTANCE_SIGNATURE}/.socket2.sock"
  if [[ -S "$sock" ]] && command -v socat &>/dev/null; then
    socat -u UNIX-CONNECT:"$sock" - 2>/dev/null | while read -r line; do
      case "$line" in
        workspace*|focusedmon*|createworkspace*|destroyworkspace*|moveworkspace*) emit ;;
      esac
    done
  else
    while sleep 1; do emit; done
  fi
fi
