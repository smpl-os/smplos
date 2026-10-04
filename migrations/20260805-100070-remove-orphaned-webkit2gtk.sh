#!/bin/bash
# Migration: Remove the orphaned webkit2gtk (WebKitGTK 4.0 API for GTK 3).
#
# Context: Arch no longer ships webkit2gtk. Systems that installed it from
#          the AUR as a dependency keep it after the app that needed it is
#          gone, and the libjxl 0.12 update removed libjxl.so.0.11 it links
#          against, so the leftover copy cannot even load.
# Safety:  Removes it only when it is an orphan (installed as a dependency and
#          required by nothing) and no sync repository provides it.
#
# Named to run with the other cleanup before the 20260805 catch-up migrations.
set -uo pipefail

pkg=webkit2gtk
if ! pacman -Qq "$pkg" >/dev/null 2>&1; then
    echo "  $pkg not installed - nothing to do"
    exit 0
fi
if ! pacman -Qdtq "$pkg" >/dev/null 2>&1; then
    echo "  $pkg is used by another package or was installed explicitly - kept"
    exit 0
fi
if ! pacman -Qmq "$pkg" >/dev/null 2>&1; then
    echo "  $pkg is provided by a repository - kept"
    exit 0
fi

echo "  Removing orphaned $pkg (no longer shipped by Arch)"
if ! sudo pacman -R --noconfirm "$pkg"; then
    echo "  ERROR: removal failed - will retry on next update"
    exit 1
fi
echo "  Removed $pkg"
