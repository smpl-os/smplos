#!/bin/bash
# Migration: Replace the hyprshell Alt+Tab switcher with a native window cycler.
#
# Context: Alt+Tab shipped as `exec hyprshell switch ...` binds that drive the
#          hyprshell GUI daemon. hyprshell's GTK grid stack-overflows and
#          core-dumps when rendering many window previews (~20+), so Alt+Tab
#          silently does nothing on machines with lots of windows open. There is
#          no scale/items_per_row value that fixes it — the crash is driven by
#          window COUNT. We replace it with a native, crash-proof `windowcycle`
#          dispatcher (implemented in bindings_loader.lua, synced by
#          smplos-os-update before this migration runs) that steps focus through
#          every window across workspaces. hyprshell is then disabled.
#
#          The active binds file (~/.config/smplos/bindings.conf) is user/
#          Settings-owned, so smplos-os-update never overwrites it — existing
#          installs would keep the crashing binds forever without this migration.
#
# Safety:  Idempotent (skips once `windowcycle` is present). Only rewrites the
#          ALT/TAB lines that exec hyprshell; every other bind is left untouched.
#          If the hyprshell binds aren't found (already customized), it appends
#          the native binds instead — last matching bind wins in Hyprland.

set -uo pipefail

# Primary binds file loaded by bindings_loader.lua; fall back to the hypr one.
BINDS=""
for candidate in "$HOME/.config/smplos/bindings.conf" "$HOME/.config/hypr/bindings.conf"; do
    if [[ -f "$candidate" ]]; then BINDS="$candidate"; break; fi
done

if [[ -z "$BINDS" ]]; then
    echo "  No bindings.conf found — nothing to do (new installs get these from the ISO)"
else
    # Idempotent: already migrated / user already has the native cycler.
    if grep -q 'windowcycle' "$BINDS" 2>/dev/null; then
        echo "  $BINDS already uses the native window cycler, skipping bind rewrite"
    else
        # Rewrite the hyprshell ALT/TAB binds in place; drop the now-dead
        # "close switcher" release bind and its comment. Only lines that mention
        # hyprshell on these exact keys are touched.
        sed -i -E \
            -e 's|^bindd = ALT, TAB,.*hyprshell.*|bindd = ALT, TAB, Cycle windows, windowcycle|' \
            -e 's|^bindd = ALT SHIFT, TAB,.*hyprshell.*|bindd = ALT SHIFT, TAB, Cycle windows (reverse), windowcycle, prev|' \
            -e '/^bindrtd = ALT, Alt_L,.*hyprshell.*/d' \
            -e '/^# Cycle through windows \(Alt-Tab via hyprshell\)/d' \
            "$BINDS"

        # If the exact hyprshell binds weren't present (user-customized file),
        # append the native cycler so Alt+Tab still gets it (last bind wins).
        if ! grep -q 'windowcycle' "$BINDS" 2>/dev/null; then
            cat >> "$BINDS" << 'EOF'

# ── Native Alt+Tab window cycler (added by smplOS migration) ─────────────────
# Crash-proof replacement for the hyprshell GUI switcher. Steps focus through
# every window across workspaces in a stable order (Shift reverses).
bindd = ALT, TAB, Cycle windows, windowcycle
bindd = ALT SHIFT, TAB, Cycle windows (reverse), windowcycle, prev
EOF
            echo "  Appended native Alt+Tab cycler to $BINDS"
        else
            echo "  Rewrote hyprshell Alt+Tab binds -> native windowcycle in $BINDS"
        fi
    fi
fi

# Disable the hyprshell daemon: it is no longer used and crash-loops under
# systemd when triggered with many windows. Stops it for the current user now;
# fresh installs are covered by the compositor postinstall (--global disable).
if systemctl --user list-unit-files hyprshell.service &>/dev/null; then
    if systemctl --user is-enabled --quiet hyprshell.service 2>/dev/null \
       || systemctl --user is-active --quiet hyprshell.service 2>/dev/null; then
        systemctl --user disable --now hyprshell.service 2>/dev/null \
            && echo "  Disabled hyprshell.service" || true
    else
        echo "  hyprshell.service already inactive, nothing to disable"
    fi
fi

# Reload Hyprland so the new bind takes effect immediately.
if hyprctl version &>/dev/null 2>&1; then
    hyprctl reload &>/dev/null 2>&1 && echo "  Reloaded Hyprland" || true
fi

exit 0
