#!/bin/bash
# Migration: Remove the abandoned smplscroll compositor plugin.
#
# Context: smplscroll was smplOS's old custom niri/PaperWM scrolling-layout
#          Hyprland plugin. Hyprland 0.55 ships a native `scrolling` layout that
#          fully replaces it, so the plugin is no longer built, shipped, or
#          loaded (autostart only loads libhyprtasking.so). The upstream repo
#          (smpl-os/smplscroll) has been deleted. Current ISOs no longer contain
#          smplscroll.so, but machines installed from an older ISO still carry a
#          stale /usr/local/lib/smplos/smplscroll.so that nothing references.
#
# Safety:  Removes ONLY the stale system plugin binary — never any user data.
#          Idempotent (skips if already gone). Privileged step is best-effort and
#          the migration always exits 0 so it can never abort the update chain.

set -uo pipefail   # deliberately no -e: the privileged step may fail offline

SO="/usr/local/lib/smplos/smplscroll.so"

if [[ ! -e "$SO" ]]; then
    echo "  smplscroll.so already absent, nothing to do"
    exit 0
fi

if sudo rm -f "$SO" 2>/dev/null; then
    echo "  Removed abandoned plugin: $SO"
else
    echo "  WARNING: could not remove $SO (no privileges?) — harmless, it is"
    echo "           never loaded. Re-run later: smplos-os-update --migrate"
fi

exit 0
