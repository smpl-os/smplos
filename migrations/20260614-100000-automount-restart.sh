#!/bin/bash
# Migration: Restart the running automount daemon after the fix in v0.7.19.
# Context: Until v0.7.18, src/shared/bin/automount only listened to udev `add`
#          events and silently bailed when blkid had not yet populated
#          ID_FS_TYPE for a freshly-plugged USB / HDD. The drive would appear
#          in nemo's sidebar (GVFS volume monitor lists unmounted volumes too)
#          but no actual filesystem mount happened, so other apps could not
#          read the files until the user clicked the drive in nemo - which
#          made GVFS issue udisks2.Mount() on their behalf.
#
#          v0.7.19 rewrites automount to also handle `change` events, do an
#          initial scan at startup, gate on ID_FS_USAGE=filesystem, and log
#          mount attempts.
#
#          smplos-os-update already runs sync_scripts which copies the new
#          /usr/local/bin/automount into place, but the daemon spawned by
#          Hyprland's exec-once is still running the OLD code from memory.
#          This migration restarts it so the fix takes effect without
#          forcing the user to log out / restart Hyprland.

set -euo pipefail

# Only do this if Hyprland (or some session) actually started automount.
# If automount isn't running, there's nothing to restart - the next session
# will pick up the new code via exec-once.
if ! pgrep -f '/usr/local/bin/automount' >/dev/null 2>&1; then
    echo "automount not running, nothing to restart"
    exit 0
fi

echo "stopping old automount daemon..."
pkill -f '/usr/local/bin/automount' 2>/dev/null || true
sleep 1

# Belt-and-suspenders: if any survived (unlikely), force-kill.
if pgrep -f '/usr/local/bin/automount' >/dev/null 2>&1; then
    pkill -9 -f '/usr/local/bin/automount' 2>/dev/null || true
    sleep 1
fi

echo "starting new automount daemon..."
# Detach fully so it survives this migration script exiting.
setsid /usr/local/bin/automount </dev/null >/dev/null 2>&1 &
disown 2>/dev/null || true

sleep 1
if pgrep -f '/usr/local/bin/automount' >/dev/null 2>&1; then
    echo "automount restarted successfully"
else
    echo "warning: automount did not start - it will start on next Hyprland session"
fi
