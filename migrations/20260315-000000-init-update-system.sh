#!/bin/bash
# Migration: Initialize smplOS update system state directories
# Context: First migration — sets up the directory structure that the
#          git-based update system needs. This runs on systems that
#          were installed before the migration system existed.

set -euo pipefail

# Create state directories if they don't exist
mkdir -p "$HOME/.local/state/smplos/migrations/skipped"
mkdir -p "$HOME/.local/state/smplos/app-versions"

# Record current installed versions of forked apps so smplos-update-apps
# doesn't re-download what's already installed.
STATE_DIR="$HOME/.local/state/smplos/app-versions"

# smpl-apps: check if any of our apps are installed
if command -v start-menu &>/dev/null; then
    ver=$(start-menu --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' || echo "")
    if [[ -n "$ver" && ! -f "$STATE_DIR/smpl-apps" ]]; then
        echo "v$ver" > "$STATE_DIR/smpl-apps"
        echo "  Recorded smpl-apps version: v$ver"
    fi
fi

# st-smpl: check if st-wl is installed
if command -v st-wl &>/dev/null; then
    ver=$(st-wl -v 2>/dev/null | grep -oP '\d+\.\d+\.\d+' || echo "")
    if [[ -n "$ver" && ! -f "$STATE_DIR/st-smpl" ]]; then
        echo "v$ver" > "$STATE_DIR/st-smpl"
        echo "  Recorded st-smpl version: v$ver"
    fi
fi

# nemo-smpl: check pacman for installed version
if pacman -Qi nemo-smpl &>/dev/null 2>&1; then
    ver=$(pacman -Qi nemo-smpl 2>/dev/null | grep -oP '(?<=Version\s:\s)\S+' || echo "")
    if [[ -n "$ver" && ! -f "$STATE_DIR/nemo-smpl" ]]; then
        echo "v$ver" > "$STATE_DIR/nemo-smpl"
        echo "  Recorded nemo-smpl version: v$ver"
    fi
fi

echo "  Update system state initialized"
