#!/bin/bash
# EWW active workspace listener (Hyprland + niri)
# Reports the workspace GROUP number (1-10) of the focused workspace.
# With grouped workspaces, each monitor has its own slot inside a group:
#   right/primary  → workspace N      (N = 1-10)
#   left/secondary → workspace N+10   (N = 11-20)
# Both normalize to the same group number: ((id - 1) % 10) + 1

emit_hyprland() {
  id=$(hyprctl activeworkspace -j 2>/dev/null | jq -r '.id // 1')
  echo $(( (id - 1) % 10 + 1 ))
}

emit_niri() {
  # 1-based position of the focused workspace among non-scratchpad
  # workspaces (sorted by idx). Matches the dot order emitted by
  # workspaces.sh. Defaults to 1 if focused on scratchpad / nothing.
  niri msg --json workspaces 2>/dev/null \
    | jq -r '[.[] | select(.name != "scratchpad")]
             | sort_by(.idx)
             | (to_entries[] | select(.value.is_focused) | .key + 1)
             // 1' \
    || echo "1"
}

emit() {
  if [[ -n "$NIRI_SOCKET" ]] && command -v niri &>/dev/null; then
    emit_niri
  elif command -v hyprctl &>/dev/null && command -v jq &>/dev/null; then
    emit_hyprland
  else
    echo "1"
  fi
}

emit

if [[ -n "$NIRI_SOCKET" ]] && command -v niri &>/dev/null; then
  niri msg event-stream 2>/dev/null | while read -r line; do
    case "$line" in
      "Workspaces changed:"*|"Workspace activated:"*|"Window focus changed:"*) emit ;;
    esac
  done
else
  sock="$XDG_RUNTIME_DIR/hypr/${HYPRLAND_INSTANCE_SIGNATURE}/.socket2.sock"
  if [[ -S "$sock" ]] && command -v socat &>/dev/null; then
    socat -u UNIX-CONNECT:"$sock" - 2>/dev/null | while read -r line; do
      case "$line" in
        workspace*|focusedmon*) emit ;;
      esac
    done
  else
    while sleep 1; do emit; done
  fi
fi
