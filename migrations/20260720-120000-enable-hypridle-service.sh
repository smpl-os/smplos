#!/bin/bash
# Fail/defer visibly rather than marking an unstarted service migration done.
# OS config sync removes stock bare-daemon autostart commands; do not kill a
# possibly custom unmanaged daemon (or the managed service) by process name.
set -euo pipefail
lib="$(dirname "${BASH_SOURCE[0]}")/../src/shared/lib"
source "$lib/smplos-session-env.sh"
source "$lib/smplos-hypridle.sh"
[[ -e "$HOME/.config/hypr/hypridle.conf" || -L "$HOME/.config/hypr/hypridle.conf" ]] || exit 0
mkdir -p "$HOME/.local/state/smplos"
touch "$HOME/.local/state/smplos/hypridle-apply-pending"
smplos_migrate_hypridle
