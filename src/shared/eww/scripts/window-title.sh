#!/bin/bash
# EWW active window title listener (Hyprland + niri)

emit_hyprland() {
  hyprctl activewindow -j 2>/dev/null | jq -r '.title // ""'
}

emit_niri() {
  # focused-window is the cleanest direct query niri provides.
  niri msg --json focused-window 2>/dev/null | jq -r '.title // ""'
}

emit() {
  if [[ -n "$NIRI_SOCKET" ]] && command -v niri &>/dev/null; then
    emit_niri
  elif command -v hyprctl &>/dev/null && command -v jq &>/dev/null; then
    emit_hyprland
  else
    echo ""
  fi
}

emit

if [[ -n "$NIRI_SOCKET" ]] && command -v niri &>/dev/null; then
  niri msg event-stream 2>/dev/null | while read -r line; do
    case "$line" in
      "Window focus changed:"*|"Window 0"*|"Windows changed:"*) emit ;;
    esac
  done
else
  sock="$XDG_RUNTIME_DIR/hypr/${HYPRLAND_INSTANCE_SIGNATURE}/.socket2.sock"
  if [[ -S "$sock" ]] && command -v socat &>/dev/null; then
    socat -u UNIX-CONNECT:"$sock" - 2>/dev/null | while read -r line; do
      case "$line" in
        activewindow*|closewindow*|movewindow*|fullscreen*) emit ;;
      esac
    done
  else
    while sleep 1; do emit; done
  fi
fi
