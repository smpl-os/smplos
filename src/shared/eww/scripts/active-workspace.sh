#!/bin/bash
# EWW active workspace listener (Hyprland + niri)
# Reports the workspace number (1-10) that the bar should highlight.
#
# Highlight follows the focused WINDOW, not the focused MONITOR. The eww bar
# is a :focusable false layer surface: clicking a workspace button moves
# Hyprland's active monitor to the bar's monitor (following the cursor) but
# leaves keyboard focus on the window you were using. So `activeworkspace`
# (monitor/cursor based) would wrongly report the bar's monitor, while
# `activewindow` (keyboard based) reports the workspace you actually switched
# to on the other monitor. Fall back to the focused monitor's workspace only
# when nothing is focused (e.g. switching to an empty workspace).

emit_hyprland() {
  id=$(hyprctl activewindow -j 2>/dev/null | jq -r '.workspace.id // empty')
  [[ -z "$id" ]] && id=$(hyprctl activeworkspace -j 2>/dev/null | jq -r '.id // 1')
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
        workspace*|focusedmon*|activewindow*) emit ;;
      esac
    done
  else
    while sleep 1; do emit; done
  fi
fi
