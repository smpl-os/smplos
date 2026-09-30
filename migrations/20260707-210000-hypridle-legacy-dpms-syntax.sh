#!/bin/bash
# Keep old pending migrations safe across both Hyprland config providers.
set -euo pipefail
lib="$(dirname "${BASH_SOURCE[0]}")/../src/shared/lib"
source "$lib/smplos-session-env.sh"
source "$lib/smplos-hypridle.sh"
smplos_migrate_hypridle
