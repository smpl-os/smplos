#!/usr/bin/env bash
# clock-bot.sh — emit the secondary clock line (day / date), or nothing.
# Reads ~/.config/smplos/bar.conf:
#   clock_format=time|dow|date   (default: time → empty output)
#   clock_date_fmt=M/D|D/M|ISO|Mon D  (default: auto from locale)

CONF="$HOME/.config/smplos/bar.conf"

clock_format="time"
clock_date_fmt="auto"

if [[ -f "$CONF" ]]; then
    v=$(grep '^clock_format=' "$CONF" 2>/dev/null | cut -d= -f2)
    [[ -n "$v" ]] && clock_format="$v"
    v=$(grep '^clock_date_fmt=' "$CONF" 2>/dev/null | cut -d= -f2)
    [[ -n "$v" ]] && clock_date_fmt="$v"
fi

if [[ "$clock_date_fmt" == "auto" ]]; then
    lc="${LC_TIME:-${LC_ALL:-${LANG:-en_US.UTF-8}}}"
    if [[ "$lc" == en_US* ]]; then
        clock_date_fmt="M/D"
    else
        clock_date_fmt="D/M"
    fi
fi

case "$clock_format" in
    dow)
        date +"%a"
        ;;
    date)
        case "$clock_date_fmt" in
            M/D)    date +"%-m/%-d"     ;;
            D/M)    date +"%-d/%-m"     ;;
            ISO)    date +"%Y-%m-%d"    ;;
            "Mon D") date +"%b %-d"     ;;
            *)      date +"%-m/%-d"     ;;
        esac
        ;;
    *)
        echo ""
        ;;
esac
