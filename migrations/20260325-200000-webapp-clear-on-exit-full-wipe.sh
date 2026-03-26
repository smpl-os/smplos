#!/bin/bash
# Migration: Fix webapp clear-on-exit — full profile wipe instead of partial file delete
#
# Previously, --clear-on-exit only removed specific files (cookies, history, cache)
# but left behind Chromium's session/tab restore files AND wrote exit_type=Crashed.
# This caused tabs to be restored on every relaunch despite the flag being set.
#
# Fix: replace partial removal with a full profile dir wipe (rm -rf + mkdir).
# This update patches the user-local copy at ~/.local/share/smplos/bin/launch-webapp.
# The /usr/local/bin/ copy is already updated by the OS update sync_scripts step.

set -euo pipefail

USER_BIN="${SMPLOS_PATH:-$HOME/.local/share/smplos}/bin"
SCRIPT="$USER_BIN/launch-webapp"

if [[ ! -f "$SCRIPT" ]]; then
    echo "  launch-webapp not found at $SCRIPT — skipping"
    exit 0
fi

# Check if the fix is already applied (look for full-wipe pattern)
if grep -q 'wiped profile for' "$SCRIPT" 2>/dev/null; then
    echo "  launch-webapp already has full-wipe clear-on-exit — nothing to do"
    exit 0
fi

# Copy the updated script from the repo
REPO_SCRIPT="${SMPLOS_PATH:-$HOME/.local/share/smplos}/repo/src/shared/bin/launch-webapp"
if [[ ! -f "$REPO_SCRIPT" ]]; then
    echo "  Repo script not found at $REPO_SCRIPT — skipping"
    exit 0
fi

cp "$REPO_SCRIPT" "$SCRIPT"
chmod +x "$SCRIPT"
echo "  Updated launch-webapp: clear-on-exit now does full profile wipe"
