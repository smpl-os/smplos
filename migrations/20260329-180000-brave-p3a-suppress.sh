#!/bin/bash
# Migration: Suppress Brave P3A analytics dialog on webapp launch
# Context: When --clear-on-exit is enabled, the profile is wiped every launch,
# so Brave shows its "completely private product analytics" notice repeatedly.
# The launch-webapp script now pre-seeds Brave preferences and always passes
# --no-first-run to suppress this. This migration updates the user-local copy.

set -euo pipefail

USER_BIN="${SMPLOS_PATH:-$HOME/.local/share/smplos}/bin"
SCRIPT="$USER_BIN/launch-webapp"

if [[ ! -f "$SCRIPT" ]]; then
    echo "  launch-webapp not found at $SCRIPT — skipping"
    exit 0
fi

# Check if the fix is already applied (look for P3A pre-seed pattern)
if grep -q 'p3a' "$SCRIPT" 2>/dev/null; then
    echo "  launch-webapp already has P3A suppression — nothing to do"
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
echo "  Updated launch-webapp: suppress Brave P3A dialog + always pass --no-first-run"
