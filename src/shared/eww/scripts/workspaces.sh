#!/bin/bash
# EWW workspaces listener (Hyprland)
# Emits the sorted list of occupied workspace GROUP numbers (1-10).
# Secondary-monitor workspaces (11-20) are normalized to their group (1-10)
# and deduplicated, so the bar always shows a single set of group dots.

emit() {
  if command -v hyprctl &>/dev/null && command -v jq &>/dev/null; then
    hyprctl workspaces -j 2>/dev/null \
      | jq -c '[.[].id | ((. - 1) % 10) + 1] | unique | sort' \
      || echo '[]'
  else
    echo '[]'
  fi
}

emit

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
