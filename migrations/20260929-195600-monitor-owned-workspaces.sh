#!/bin/bash
# Enable the spatial workspace default once; saved choices and opt-outs win.
set -euo pipefail

# Python is a base runtime (also required by the shipped archinstall package).
# Do not start a partial pacman upgrade from a desktop configuration migration.
if ! command -v python3 >/dev/null; then
    echo "  ERROR: Python is missing; install the python package and rerun Update OS" >&2
    exit 1
fi
if ! command -v workspace-ctl >/dev/null; then
    echo "  ERROR: workspace-ctl is missing; sync OS scripts before retrying" >&2
    exit 1
fi

# shellcheck source=../src/shared/lib/smplos-session-env.sh
source "$(dirname "${BASH_SOURCE[0]}")/../src/shared/lib/smplos-session-env.sh"

if ! smplos_have_hyprland; then
    echo "  No live Hyprland session; workspace setup will run at the next Hyprland login"
    exit 0
fi

smplos_run_as_user hyprctl reload config-only
smplos_run_as_user workspace-ctl enroll
smplos_run_as_user bar-ctl reload
echo "  Workspace scripts, monitor overview and saved preference are applied"
