#!/bin/bash
# Catch up machines where the old DPMS/service migrations were already marked
# done. Also invoked each normal OS update to handle older Settings writers.
set -euo pipefail
lib="$(dirname "${BASH_SOURCE[0]}")/../src/shared/lib"
source "$lib/smplos-session-env.sh"
source "$lib/smplos-hypridle.sh"
smplos_migrate_hypridle
