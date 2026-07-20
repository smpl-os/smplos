#!/bin/bash
# Migration: Enable the packaged hypridle systemd user service.
#
# Context: Historically smplOS relied on Hyprland's `exec-once = hypridle` in
#          the autostart config to launch the idle daemon. That works for the
#          first Hyprland session per boot — but if hypridle ever dies (crash,
#          manual kill during debugging, Wayland reconnect failure) it stays
#          dead until the next full logout/login. Users then see the Settings
#          app cheerfully advertising "Lock 5m / Screen off 5m / Suspend 10m"
#          while nothing actually fires, because there is no daemon running to
#          arm those timeouts. Two people burned by this in the same week
#          triggered the fix.
#
# Fix:     Enable the packaged `hypridle.service` user unit (shipped by the
#          `hypridle` Arch package). The unit has `Restart=on-failure` and is
#          wanted by `graphical-session.target`, so it starts every session and
#          respawns automatically on crash. Enabling it does NOT conflict with
#          the exec-once launch: hypridle refuses to bind Wayland twice, so
#          whichever wins first stays alive and the second exits quietly.
#
# Safety:  Idempotent — `systemctl --user enable` on an already-enabled unit
#          is a no-op. Skips cleanly on systems without the hypridle package
#          (e.g. mid-migration recovery images). Never touches user config.
#          Always exits 0 so a hiccup here can't halt Update OS.

set -uo pipefail

UNIT_SRC="/usr/lib/systemd/user/hypridle.service"

if [[ ! -f "$UNIT_SRC" ]]; then
    echo "  hypridle package not installed ($UNIT_SRC missing) — skipping"
    exit 0
fi

# Kill any bare `hypridle` process that came from the OLD
# `exec-once = hypridle` line in autostart.conf. Same-release sync_hypr_configs
# removes that line from the file, but the running Hyprland session already
# spawned the daemon at session start, so it survives until logout. Leaving it
# alive means the systemd-managed instance and the exec-once instance both
# respond to logind Lock/Sleep signals, doubling every after_sleep_cmd. Kill
# only bare-name matches so we don't touch the /usr/bin/hypridle from systemd.
if pgrep -x hypridle >/dev/null 2>&1; then
    # -f matches command line; pgrep -x on the bare name catches the exec-once
    # invocation (argv[0] = "hypridle") without hitting the fullpath one.
    pkill -x hypridle 2>/dev/null || true
    sleep 0.3
    echo "  killed stale bare hypridle (was likely from exec-once)"
fi

# Check if already enabled (idempotent guard)
if systemctl --user is-enabled hypridle.service >/dev/null 2>&1; then
    echo "  hypridle.service already enabled — nothing to do"
    # Make sure it's actually running too, in case a prior session left it dead
    if ! systemctl --user is-active hypridle.service >/dev/null 2>&1; then
        systemctl --user start hypridle.service >/dev/null 2>&1 || true
        echo "  started hypridle.service (was inactive)"
    fi
    exit 0
fi

if systemctl --user enable --now hypridle.service >/dev/null 2>&1; then
    echo "  enabled and started hypridle.service"
else
    echo "  WARNING: could not enable hypridle.service — Settings app will fall back to setsid spawn"
fi

exit 0
