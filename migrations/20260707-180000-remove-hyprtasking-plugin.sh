#!/bin/bash
# Migration: Remove the abandoned hyprtasking overview plugin.
#
# Context: hyprtasking was the niri-style workspace-overview plugin bound to
#          Super+TAB. It has been dropped from the smplOS build/update chain
#          because its rendering doesn't cope with rotated portrait monitors
#          combined with the native scrolling layout, and we don't want to keep
#          maintaining a fork. Newer ISOs don't build/install/load it and use
#          plain workspace navigation on Super+TAB. Existing installs still
#          carry the .so at /usr/local/lib/smplos/libhyprtasking.so, an
#          autostart exec-once that loads it, and Super+TAB bound to
#          hyprtasking:toggle in ~/.config/smplos/bindings.conf.
#
# Safety:  Removes only the stale system plugin binary, comments the autostart
#          loader out of ~/.config/hypr/autostart.conf (leaving anything else
#          untouched), and rewrites the Super+TAB line in the user's
#          bindings.conf to plain `workspace, +1`. Idempotent: skips work that
#          is already done. Always exits 0 so it never blocks other migrations.

set -uo pipefail

SO="/usr/local/lib/smplos/libhyprtasking.so"
SO_BAK_GLOB="/usr/local/lib/smplos/libhyprtasking.so.bak-*"

# 1) Remove the system plugin binary and any leftover backups.
if [[ -e "$SO" ]] || compgen -G "$SO_BAK_GLOB" >/dev/null 2>&1; then
    if sudo rm -f "$SO" $SO_BAK_GLOB 2>/dev/null; then
        echo "  Removed hyprtasking plugin binary(ies)"
    else
        echo "  WARNING: could not remove $SO (no privileges?) — re-run later:"
        echo "           smplos-os-update --migrate"
    fi
else
    echo "  hyprtasking plugin binary already absent"
fi

# 2) Comment out any exec-once line that loads the plugin from autostart.conf.
AUTOSTART="$HOME/.config/hypr/autostart.conf"
if [[ -f "$AUTOSTART" ]] && grep -q 'libhyprtasking\.so' "$AUTOSTART" 2>/dev/null; then
    sed -i -E 's|^([[:space:]]*)(exec-once[[:space:]]*=.*libhyprtasking\.so.*)$|\1# removed (hyprtasking dropped): \2|' "$AUTOSTART"
    echo "  Disabled hyprtasking loader in $AUTOSTART"
fi

# 3) Replace the hyprtasking:toggle Super+TAB bind with plain workspace,+1.
BINDS=""
for candidate in "$HOME/.config/smplos/bindings.conf" "$HOME/.config/hypr/bindings.conf"; do
    if [[ -f "$candidate" ]]; then BINDS="$candidate"; break; fi
done

if [[ -n "$BINDS" ]] && grep -q 'hyprtasking' "$BINDS" 2>/dev/null; then
    # Replace the toggle bind with a plain next-workspace bind. Any other
    # hyprtasking:* binds get commented out (they were opt-in extras).
    sed -i -E \
        -e 's|^([[:space:]]*)bindd[[:space:]]*=[[:space:]]*SUPER[[:space:]]*,[[:space:]]*TAB[[:space:]]*,[^,]*,[[:space:]]*hyprtasking:toggle[[:space:]]*,.*$|\1bindd = SUPER, TAB, Next workspace, workspace, +1|' \
        -e 's|^([[:space:]]*)(bindd[[:space:]]*=.*hyprtasking:.*)$|\1# removed (hyprtasking dropped): \2|' \
        "$BINDS"
    echo "  Rewrote hyprtasking binds in $BINDS"
fi

# 4) If the plugin is still loaded in the running session, unload it.
if command -v hyprctl >/dev/null 2>&1; then
    if hyprctl plugin list 2>/dev/null | grep -qi 'Hyprtasking'; then
        hyprctl plugin unload "$SO" >/dev/null 2>&1 || true
        echo "  Unloaded hyprtasking from live Hyprland session"
    fi
fi

exit 0
