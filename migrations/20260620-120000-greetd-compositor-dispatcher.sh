#!/bin/bash
# Migration: Repoint greetd at the smplos-start-session dispatcher.
#
# Context: Prior to niri support, /etc/greetd/config.toml had:
#     [default_session] command = "tuigreet --remember-session --cmd start-hyprland"
#     [initial_session] command = "start-hyprland"
#
# That hardcodes Hyprland for every login, so `switch-compositor niri`
# wrote ~/.config/smplos/compositor=niri but greetd ignored the marker
# and kept launching Hyprland on every login after the first.
#
# v0.7.20 introduces smplos-start-session, a tiny dispatcher that reads
# the marker file and exec's either start-hyprland or start-niri.
# install.sh now writes both [default_session] and [initial_session] to
# call it. This migration patches existing installs so their compositor
# choice is actually honoured without a reinstall.
#
# Safe to re-run: idempotent sed substitutions.

set -euo pipefail

CFG=/etc/greetd/config.toml

if [[ ! -f "$CFG" ]]; then
    echo "greetd config not present, skipping"
    exit 0
fi

# Verify the dispatcher is installed before rewiring greetd (sync_scripts
# in smplos-os-update copies it into /usr/local/bin/ before migrations run).
if [[ ! -x /usr/local/bin/smplos-start-session ]]; then
    echo "smplos-start-session dispatcher missing — refusing to patch greetd" >&2
    exit 1
fi

changed=0

# default_session: tuigreet --cmd ...
if sudo grep -qE '^command = "tuigreet --remember-session --cmd start-hyprland"' "$CFG"; then
    sudo sed -i 's|tuigreet --remember-session --cmd start-hyprland|tuigreet --remember-session --cmd smplos-start-session|' "$CFG"
    changed=1
fi

# initial_session: bare start-hyprland (only match the exact legacy line so
# we don't touch a hand-customised setup that already runs the dispatcher
# or some third-party launcher).
if sudo grep -qE '^command = "start-hyprland"' "$CFG"; then
    sudo sed -i 's|command = "start-hyprland"|command = "smplos-start-session"|' "$CFG"
    changed=1
fi

if (( changed )); then
    echo "greetd repointed at smplos-start-session"
    # No reload needed: greetd reads its config on next greetd restart /
    # next logout. The change takes effect on next login.
else
    echo "greetd already uses dispatcher (or has been hand-customised), no change"
fi
