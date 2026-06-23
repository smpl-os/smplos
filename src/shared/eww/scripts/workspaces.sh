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
  # niri is dynamic. Emit 1-based bar positions of non-scratchpad
  # workspaces that have at least one window. Scratchpad is filtered out
  # so toggle-messenger's stash never shows up as a dot.
  niri msg --json workspaces 2>/dev/null \
    | jq -c '[.[] | select(.name != "scratchpad")]
             | sort_by(.idx)
             | to_entries
             | map(select(.value.active_window_id != null) | .key + 1)
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
