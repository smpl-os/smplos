#!/bin/bash
# Migration: Rewrite hypridle.conf that still holds the legacy
#            `hyprctl dispatch dpms off/on` DPMS syntax.
#
# Context: Hyprland 0.55 (the version smplOS pins) treats every argument to
#          `hyprctl dispatch` as a Lua expression via `hl.dispatch(...)`.
#          Legacy dispatcher names like `dpms off` fail parse:
#              error: [string "return hl.dispatch(dpms on)"]:1: ')' expected
#                     near 'on'
#          The dispatcher must be written as
#              hyprctl dispatch "hl.dsp.dpms({state='off'})"
#          smpl-apps v0.8.10+ ships a Settings-side writer that emits the new
#          syntax whenever the user re-saves Power settings, but users who
#          NEVER opened Power → Save since the fix landed still have the old
#          on-disk file that hypridle happily loads and silently errors out on
#          every timeout — screens never blank, computer never suspends.
#
# Fix:     If ~/.config/hypr/hypridle.conf contains the legacy `hyprctl
#          dispatch dpms <state>` invocation anywhere, replace it in-place
#          with the modern `hyprctl dispatch "hl.dsp.dpms({state='<state>'})"`
#          form. Timeouts and every other line are preserved. Restart hypridle
#          so the fix takes effect immediately without waiting for the next
#          logout.
#
# Safety:  Idempotent — grep guard means re-runs are no-ops. Bails out cleanly
#          if the file doesn't exist (users who never touched Power keep
#          whatever config sync_hypr_configs deposited). Always exits 0.

set -uo pipefail

CONF="$HOME/.config/hypr/hypridle.conf"

if [[ ! -f "$CONF" ]]; then
    echo "  hypridle.conf not present (fresh install or never customized) — skipping"
    exit 0
fi

# Legacy syntax we're hunting for. Match `hyprctl dispatch dpms off` /
# `hyprctl dispatch dpms on` regardless of surrounding whitespace so we catch
# both raw and `foo || hyprctl dispatch dpms off` forms.
if ! grep -qE 'hyprctl[[:space:]]+dispatch[[:space:]]+dpms[[:space:]]+(on|off)([^"]|$)' "$CONF"; then
    echo "  hypridle.conf already uses modern dpms syntax — nothing to do"
    exit 0
fi

# Back up before rewriting so a bad regex can't strand the user.
BAK="$CONF.pre-dpms-syntax-fix.$(date +%s)"
cp -f "$CONF" "$BAK" 2>/dev/null || {
    echo "  WARNING: could not back up $CONF — aborting rewrite"
    exit 0
}

# Two substitutions cover every legacy call site: the on-timeout / on-resume
# lines inside listener blocks AND the after_sleep_cmd chain in the general
# block. We deliberately keep the substitution narrow so lines that just
# happen to mention "dpms" in a comment are untouched.
sed -i -E \
    -e 's|hyprctl[[:space:]]+dispatch[[:space:]]+dpms[[:space:]]+off|hyprctl dispatch "hl.dsp.dpms({state='"'"'off'"'"'})"|g' \
    -e 's|hyprctl[[:space:]]+dispatch[[:space:]]+dpms[[:space:]]+on|hyprctl dispatch "hl.dsp.dpms({state='"'"'on'"'"'})"|g' \
    "$CONF"

# Verify the rewrite left NO legacy occurrences behind. If any survived, roll
# back — we'd rather leave the file untouched than half-migrated.
if grep -qE 'hyprctl[[:space:]]+dispatch[[:space:]]+dpms[[:space:]]+(on|off)([^"]|$)' "$CONF"; then
    echo "  ERROR: rewrite left legacy syntax behind — restoring backup"
    cp -f "$BAK" "$CONF"
    exit 0
fi

echo "  hypridle.conf DPMS calls rewritten to hl.dsp.dpms syntax (backup: $BAK)"

# Restart hypridle so the fix takes effect without waiting for the next login.
# Match the same pattern Settings uses on Save so behavior is identical.
if pgrep -x hypridle >/dev/null 2>&1; then
    pkill -x hypridle 2>/dev/null || true
    sleep 0.2
fi
setsid hypridle </dev/null >/dev/null 2>&1 &
disown 2>/dev/null || true
echo "  hypridle restarted — screen-off timer will fire correctly on next idle"

exit 0
