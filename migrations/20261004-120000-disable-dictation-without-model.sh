#!/bin/bash
# Migration: Stop starting dictation (voxtype) at login without its model.
#
# Context: The installer enabled voxtype.service but primed only the
#          faster-whisper cache; voxtype loads ggml models from
#          ~/.local/share/voxtype/models, which nothing installed. The unit
#          never started before smplOS activated graphical-session.target;
#          now it would fail and be reported at every login.
# Safety:  Removes only this user's enable links, and only when no voxtype
#          model exists. dictation-toggle still starts it on demand, and
#          dictation-setup enables it again after downloading a model.
set -uo pipefail

for entry in "${XDG_DATA_HOME:-$HOME/.local/share}/voxtype/models"/*; do
    if [[ -e "$entry" && "${entry##*/}" != CACHEDIR.TAG ]]; then
        echo "  voxtype has a model - dictation autostart kept"
        exit 0
    fi
done

links=()
for wants in graphical-session.target.wants default.target.wants; do
    link="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$wants/voxtype.service"
    [[ -L "$link" ]] && links+=("$link")
done
if [[ ${#links[@]} -eq 0 ]]; then
    echo "  dictation autostart not enabled - nothing to do"
    exit 0
fi

rm -f -- "${links[@]}"
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user stop voxtype.service 2>/dev/null || true
echo "  Dictation no longer starts at login until a model is downloaded (dictation-setup)"
