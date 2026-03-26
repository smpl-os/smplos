#!/usr/bin/env bash
# clock-top.sh — emit the primary clock line (time).
# Reads ~/.config/smplos/bar.conf:   clock_24h=true|false
# Falls back to locale detection when key is absent ("auto").

CONF="$HOME/.config/smplos/bar.conf"

clock_24h="auto"
if [[ -f "$CONF" ]]; then
    v=$(grep '^clock_24h=' "$CONF" 2>/dev/null | cut -d= -f2)
    [[ -n "$v" ]] && clock_24h="$v"
fi

if [[ "$clock_24h" == "auto" ]]; then
    lc="${LC_TIME:-${LC_ALL:-${LANG:-en_US.UTF-8}}}"
    if [[ "$lc" == en_US* ]]; then
        clock_24h="false"
    else
        clock_24h="true"
    fi
fi

if [[ "$clock_24h" == "true" ]]; then
    date +"%H:%M"
else
    date +"%-I:%M %p"
fi
