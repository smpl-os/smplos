#!/bin/bash
# EWW active workspace listener (Hyprland)
# Reports the workspace GROUP number (1-10) of the focused workspace.
# With grouped workspaces, each monitor has its own slot inside a group:
#   right/primary  → workspace N      (N = 1-10)
#   left/secondary → workspace N+10   (N = 11-20)
# Both normalize to the same group number: ((id - 1) % 10) + 1

emit() {
  if command -v hyprctl &>/dev/null && command -v jq &>/dev/null; then
    id=$(hyprctl activeworkspace -j 2>/dev/null | jq -r '.id // 1')
    # Normalize: ws 1→1, ws 11→1, ws 2→2, ws 12→2, ...
    echo $(( (id - 1) % 10 + 1 ))
  else
    echo "1"
  fi
}

emit

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
