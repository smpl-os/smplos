#!/usr/bin/env bash
#
# smplOS — left-click repair & diagnostic tool
# ---------------------------------------------
# Symptom this targets: cursor moves, RIGHT-click works, but LEFT-click does
# nothing anywhere, after a Hyprland 0.55+ install/upgrade.
#
# What it does (in order, safest first):
#   1. Collects a baseline diagnostic.
#   2. Tests each theory and, if it matches, APPLIES a reversible fix and asks
#      you to try left-clicking.
#   3. If a fix works, it stops (and tells you whether it's permanent).
#   4. If nothing works, it writes a full log file so it can be analysed.
#
# SAFE: user-level only. No sudo. Every edited config file is backed up first
#       (<file>.leftclick-bak-<timestamp>). Nothing is deleted.
#
# Run it with:   bash leftclick-fix.sh
#
set -uo pipefail

TS="$(date +%Y%m%d-%H%M%S)"
# Write the log next to this script (so when run from a USB/Ventoy stick the
# log lands on the stick too). Fall back to $HOME if the script dir isn't
# writable (e.g. a read-only mount).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
[[ -z "$SCRIPT_DIR" ]] && SCRIPT_DIR="$PWD"
if [[ -w "$SCRIPT_DIR" ]]; then
    LOG="$SCRIPT_DIR/smplos-leftclick-debug-$TS.log"
else
    LOG="$HOME/smplos-leftclick-debug-$TS.log"
fi
BAK_SUFFIX="leftclick-bak-$TS"
FIXED=0

have()   { command -v "$1" >/dev/null 2>&1; }
line()   { printf '%s\n' "$*"; }
both()   { printf '%s\n' "$*" | tee -a "$LOG" >/dev/null; printf '%s\n' "$*"; }
section(){ printf '\n===== %s =====\n' "$*" | tee -a "$LOG" >/dev/null; printf '\n\033[1m===== %s =====\033[0m\n' "$*"; }
logonly(){ printf '%s\n' "$*" >>"$LOG"; }

# --- prerequisites ----------------------------------------------------------
if ! have hyprctl; then
    line "ERROR: 'hyprctl' not found. Run this from inside a Hyprland session."
    exit 1
fi
HAVE_JQ=0; have jq && HAVE_JQ=1

{
    echo "smplOS left-click debug log"
    echo "date: $(date)"
    echo "host: $(hostname 2>/dev/null)"
    echo "user: $USER"
    echo "jq available: $HAVE_JQ"
} >"$LOG"

# --- click test helper ------------------------------------------------------
ask_fixed() {
    local ans
    printf '\n\033[1;33m>>> Now try LEFT-CLICKING a few things (window, menu, desktop).\033[0m\n'
    read -rp ">>> Did left-click start working? [y/N] " ans
    logonly "click-test after '$1': answer='${ans:-}'"
    [[ "${ans:-}" =~ ^[Yy] ]]
}

reload_hypr() { hyprctl reload >/dev/null 2>&1 || true; sleep 1; }

HOME_COPY=""
finish() {
    # Always keep a copy on the local disk too, and flush to disk so a USB
    # stick doesn't lose the data if it's removed without a clean unmount.
    local home_copy="$HOME/$(basename "$LOG")"
    if [[ "$LOG" != "$home_copy" ]]; then
        if cp -f "$LOG" "$home_copy" 2>/dev/null; then HOME_COPY="$home_copy"; fi
    fi
    sync 2>/dev/null || true
}

# ============================================================================
# 1. BASELINE DIAGNOSTIC
# ============================================================================
section "Baseline diagnostic"

VERSION="$(hyprctl version 2>/dev/null | head -1)"
PROVIDER="$(hyprctl systeminfo 2>/dev/null | grep -i configprovider | head -1 | sed 's/^[[:space:]]*//')"
[[ -z "$PROVIDER" ]] && PROVIDER="(configProvider not reported — likely older Hyprland)"

if [[ $HAVE_JQ -eq 1 ]]; then
    LEFT_HANDED="$(hyprctl getoption input:left_handed -j 2>/dev/null | jq -r '.int // "?"')"
    FOLLOW="$(hyprctl getoption input:follow_mouse -j 2>/dev/null | jq -r '.int // "?"')"
    CONSUME_CNT="$(hyprctl binds -j 2>/dev/null | jq -r '[.[]|select(.key=="mouse:272" and .modmask==0 and .non_consuming==false)] | length')"
else
    LEFT_HANDED="$(hyprctl getoption input:left_handed 2>/dev/null | grep -oE 'int: *[0-9]+' | grep -oE '[0-9]+')"
    FOLLOW="$(hyprctl getoption input:follow_mouse 2>/dev/null | grep -oE 'int: *[0-9]+' | grep -oE '[0-9]+')"
    CONSUME_CNT="?"
fi
[[ -z "$LEFT_HANDED" ]] && LEFT_HANDED="?"
[[ -z "$FOLLOW" ]] && FOLLOW="?"

both "Hyprland version : $VERSION"
both "config provider  : $PROVIDER"
both "input:left_handed: $LEFT_HANDED   (1 = swaps L/R buttons)"
both "input:follow_mouse: $FOLLOW"
both "consuming no-mod mouse:272 binds (runtime): $CONSUME_CNT"

section "All mouse:272 binds (runtime)"
if [[ $HAVE_JQ -eq 1 ]]; then
    hyprctl binds -j 2>/dev/null \
      | jq -r '.[]|select(.key=="mouse:272")|"modmask=\(.modmask) nonconsuming=\(.non_consuming) mouse=\(.mouse) desc=\(.description) arg=\(.arg)"' \
      | tee -a "$LOG"
else
    hyprctl binds 2>/dev/null | grep -B1 -A6 'mouse:272' | tee -a "$LOG"
fi

section "Pointer / keyboard devices"
if [[ $HAVE_JQ -eq 1 ]]; then
    { echo "-- mice --";      hyprctl devices -j 2>/dev/null | jq -r '.mice[].name';
      echo "-- keyboards --"; hyprctl devices -j 2>/dev/null | jq -r '.keyboards[].name'; } | tee -a "$LOG"
else
    hyprctl devices 2>/dev/null | tee -a "$LOG" >/dev/null
    hyprctl devices 2>/dev/null | grep -iE 'Mouse|Keyboard|^\s+\S' | tee -a "$LOG"
fi

# Record any mouse:272 references in config files (for later analysis).
section "mouse:272 references in config files"
CFG_DIRS=("$HOME/.config/hypr" "$HOME/.config/smplos")
grep -rnHE 'mouse:272' "${CFG_DIRS[@]}" 2>/dev/null | tee -a "$LOG" || logonly "(none found)"

# ============================================================================
# 2. FIX ATTEMPTS
# ============================================================================

# ---- Fix A: left-handed mode ----------------------------------------------
if [[ "$LEFT_HANDED" == "1" ]]; then
    section "Theory 3: left_handed is ON — disabling it"
    hyprctl keyword input:left_handed false >/dev/null 2>&1
    both "Applied: input:left_handed = false (runtime)."
    if ask_fixed "disable left_handed"; then
        FIXED=1
        both "FIXED by disabling left_handed."
        both "NOTE: this is a runtime change. To make it permanent, ensure your"
        both "      Hyprland input config has:  left_handed = false"
    fi
fi

# ---- Fix B: consuming no-mod mouse:272 binds in hyprlang config files ------
if [[ $FIXED -eq 0 ]]; then
    section "Theory 1/2: consuming no-modifier mouse:272 bind in config files"
    CHANGED_FILES=()
    while IFS= read -r file; do
        [[ -z "$file" ]] && continue
        # Find line numbers of offending binds:
        #   key == mouse:272, empty modifier field, and bind keyword NOT
        #   containing 'n' (non-consuming). Catches `bind = , mouse:272, ...`
        #   and `bindm = , mouse:272, ...` (plain-left drag), skips the legit
        #   `bindm = SUPER, mouse:272` and any `bindn = , mouse:272`.
        mapfile -t LN < <(awk '
            /mouse:272/ {
                kw=$0; sub(/[ \t]*=.*/,"",kw); gsub(/[ \t]/,"",kw)
                rhs=$0; sub(/^[^=]*=[ \t]*/,"",rhs)
                n=split(rhs,a,","); mods=a[1]; key=a[2]
                gsub(/[ \t]/,"",mods); gsub(/[ \t]/,"",key)
                if (key=="mouse:272" && mods=="" && kw ~ /^bind/ && kw !~ /n/) print NR
            }' "$file" 2>/dev/null)
        if [[ ${#LN[@]} -gt 0 ]]; then
            both "Found consuming left-click bind(s) in: $file (lines: ${LN[*]})"
            cp -f "$file" "$file.$BAK_SUFFIX"
            for n in "${LN[@]}"; do
                sed -i "${n}s|^|# [leftclick-fix disabled] |" "$file"
                logonly "commented $file:$n"
            done
            CHANGED_FILES+=("$file")
        fi
    done < <(grep -rlIE 'mouse:272' "${CFG_DIRS[@]}" 2>/dev/null)

    if [[ ${#CHANGED_FILES[@]} -gt 0 ]]; then
        reload_hypr
        both "Commented out the bind(s) and reloaded Hyprland."
        if ask_fixed "comment consuming hyprlang bind"; then
            FIXED=1
            both "FIXED by removing consuming hyprlang mouse:272 bind(s)."
            both "PERMANENT: edited config file(s); backups at *.$BAK_SUFFIX"
        fi
    else
        both "No consuming no-mod mouse:272 bind found in hyprlang config files."
    fi
fi

# ---- Fix B2: bindings_loader.lua ignores the `n` (non-consuming) flag -------
# This is the real root cause of the "left-click dead everywhere" bug: a
# `bindn = , mouse:272, exec, popup-click-check` directive is meant to be
# NON-consuming, but if bindings_loader.lua's parse_flags() has no handler for
# the `n` flag it registers the bind as CONSUMING and swallows every left-click.
# Fix = teach the loader to honor `n`, then reload so the bind re-registers as
# non-consuming.
if [[ $FIXED -eq 0 && "$CONSUME_CNT" != "0" ]]; then
    section "Theory (root cause): bindings_loader.lua drops the non-consuming 'n' flag"
    BL="$HOME/.config/hypr/bindings_loader.lua"
    if [[ -f "$BL" ]]; then
        if grep -q 'non_consuming' "$BL"; then
            both "bindings_loader.lua already handles non_consuming — skipping."
        elif grep -q 'ignore_mods' "$BL"; then
            cp -f "$BL" "$BL.$BAK_SUFFIX"
            sed -i '/ignore_mods[[:space:]]*=[[:space:]]*true/a\        elseif c == "n" then opts.non_consuming = true' "$BL"
            logonly "patched $BL to add n-flag handler"
            if grep -q 'opts.non_consuming = true' "$BL"; then
                reload_hypr
                both "Patched bindings_loader.lua to honor the 'n' (non-consuming)"
                both "flag and reloaded Hyprland. The mouse:272 popup-click-check"
                both "bind should now be non-consuming."
                if ask_fixed "patch bindings_loader.lua n-flag"; then
                    FIXED=1
                    both "FIXED — bindings_loader.lua now honors non-consuming binds."
                    both "PERMANENT: edited $BL ; backup at $BL.$BAK_SUFFIX"
                fi
            else
                both "Patch did not apply cleanly (unexpected loader format)."
            fi
        else
            both "Could not locate the flag-parsing block in bindings_loader.lua."
            both "Falling back to commenting the offending bindn line (Fix B3)."
        fi
    else
        both "bindings_loader.lua not found at $BL (not a Lua-provider install)."
    fi
fi

# ---- Fix B3: fallback — comment the redundant inline bindn popup-click line -
# If we couldn't patch the loader, neutralise the consuming bind by commenting
# the `bindn = , mouse:272, exec, popup-click-check` line directly. The Lua
# popup_watchers.lua still provides non-consuming click-outside dismissal.
if [[ $FIXED -eq 0 && "$CONSUME_CNT" != "0" ]]; then
    CHANGED_B3=()
    while IFS= read -r file; do
        [[ -z "$file" ]] && continue
        mapfile -t LN < <(awk '/mouse:272/ && /popup-click-check/ && /^[[:space:]]*bindn?[[:space:]]*=/{print NR}' "$file" 2>/dev/null)
        if [[ ${#LN[@]} -gt 0 ]]; then
            [[ -f "$file.$BAK_SUFFIX" ]] || cp -f "$file" "$file.$BAK_SUFFIX"
            for n in "${LN[@]}"; do
                sed -i "${n}s|^|# [leftclick-fix disabled] |" "$file"
                logonly "B3 commented $file:$n"
            done
            CHANGED_B3+=("$file")
        fi
    done < <(grep -rlIE 'mouse:272' "${CFG_DIRS[@]}" 2>/dev/null)
    if [[ ${#CHANGED_B3[@]} -gt 0 ]]; then
        section "Fallback: commented the inline bindn popup-click-check line(s)"
        reload_hypr
        both "Commented the redundant popup-click-check bindn line and reloaded."
        both "(Click-outside dismissal still works via popup_watchers.lua.)"
        if ask_fixed "comment inline bindn popup line"; then
            FIXED=1
            both "FIXED by removing the redundant consuming bindn line."
            both "PERMANENT: edited ${CHANGED_B3[*]} ; backups at *.$BAK_SUFFIX"
        fi
    fi
fi

# ---- Fix C: Lua popup watcher missing non_consuming ------------------------
if [[ $FIXED -eq 0 ]]; then
    PW="$HOME/.config/hypr/popup_watchers.lua"
    if [[ -f "$PW" ]] && grep -q 'mouse:272' "$PW" && ! grep -q 'non_consuming' "$PW"; then
        section "Theory 1 (Lua): popup_watchers.lua binds mouse:272 WITHOUT non_consuming"
        cp -f "$PW" "$PW.$BAK_SUFFIX"
        # Insert non_consuming = true after the hl.bind("mouse:272", ... line's opts table open.
        # Robust approach: replace the options-table open brace on the mouse:272 bind.
        awk '
            /hl%.bind%("mouse:272"/ || /hl\.bind\("mouse:272"/ { inbind=1 }
            inbind && /\{[[:space:]]*$/ && !done { print; print "    non_consuming = true,"; done=1; inbind=0; next }
            { print }
        ' "$PW" > "$PW.tmp" && mv "$PW.tmp" "$PW"
        reload_hypr
        both "Patched popup_watchers.lua to add non_consuming = true and reloaded."
        if ask_fixed "patch lua popup watcher"; then
            FIXED=1
            both "FIXED by making the Lua popup watcher non-consuming."
            both "PERMANENT: edited $PW ; backup at $PW.$BAK_SUFFIX"
        fi
    fi
fi

# ---- Fix D: best-effort runtime unbind (hyprlang parser only) --------------
if [[ $FIXED -eq 0 ]]; then
    section "Theory 1/2: best-effort runtime unbind of mouse:272"
    OUT="$(hyprctl keyword unbind ,mouse:272 2>&1)"
    logonly "unbind result: $OUT"
    both "Attempted: hyprctl keyword unbind ,mouse:272"
    both "  -> $OUT"
    if [[ "$OUT" == *"ok"* ]]; then
        if ask_fixed "runtime unbind mouse:272"; then
            FIXED=1
            both "FIXED by runtime unbind."
            both "WARNING: runtime unbind is LOST on next reload/restart. Reboot"
            both "         from the new smplOS ISO (or re-run this) for a lasting fix."
        fi
    fi
fi

# ============================================================================
# 3. RESULT
# ============================================================================
if [[ $FIXED -eq 1 ]]; then
    section "RESULT: left-click restored"
    finish
    both "A diagnostic log was still written to:"
    both "  $LOG"
    [[ -n "$HOME_COPY" ]] && both "  (backup copy: $HOME_COPY)"
    both "Log flushed to disk. Safe to remove the USB stick now."
    exit 0
fi

section "RESULT: not fixed — collecting full diagnostic"
{
    echo; echo "===== FULL: hyprctl binds -j ====="
    hyprctl binds -j 2>/dev/null
    echo; echo "===== FULL: hyprctl devices -j ====="
    hyprctl devices -j 2>/dev/null
    echo; echo "===== FULL: hyprctl getoption input:* ====="
    for o in left_handed follow_mouse sensitivity accel_profile force_no_accel natural_scroll; do
        echo "--- input:$o ---"; hyprctl getoption "input:$o" 2>/dev/null
    done
    echo; echo "===== active window / cursor / submap ====="
    echo "-- activewindow --"; hyprctl activewindow 2>/dev/null
    echo "-- cursorpos --";    hyprctl cursorpos 2>/dev/null
    echo "-- current submap (empty = default) --"; hyprctl -j activeworkspace 2>/dev/null
    echo; echo "===== layers (a grabbing layer/lockscreen can eat clicks) ====="
    hyprctl layers 2>/dev/null
    echo; echo "===== clients (count + floating/fullscreen state) ====="
    hyprctl clients 2>/dev/null
    echo; echo "===== ls ~/.config/hypr ====="
    ls -la "$HOME/.config/hypr" 2>/dev/null
    echo; echo "===== ls ~/.config/smplos ====="
    ls -la "$HOME/.config/smplos" 2>/dev/null
    echo; echo "===== hyprland.conf present? ====="
    [[ -f "$HOME/.config/hypr/hyprland.conf" ]] && echo "YES (hyprlang candidate)" || echo "no"
    [[ -f "$HOME/.config/hypr/hyprland.lua"  ]] && echo "hyprland.lua present" || echo "hyprland.lua absent"
    echo; echo "===== full grep mouse:272 in configs ====="
    grep -rnHE 'mouse:272' "${CFG_DIRS[@]}" 2>/dev/null
    echo; echo "===== grep any mouse / bind lines in configs ====="
    grep -rnHE 'mouse:|left_handed|^bind|submap' "${CFG_DIRS[@]}" 2>/dev/null
    echo; echo "===== tail of Hyprland log ====="
    HYPRLOG="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hypr/${HYPRLAND_INSTANCE_SIGNATURE:-}/hyprland.log"
    [[ -f "$HYPRLOG" ]] && tail -n 150 "$HYPRLOG" || echo "(hyprland.log not found at $HYPRLOG)"
} >>"$LOG" 2>&1

finish
both ""
both "Could not auto-fix it. A full diagnostic log was written to:"
both ""
both "    $LOG"
[[ -n "$HOME_COPY" ]] && both "    (backup copy on local disk: $HOME_COPY)"
both ""
both "The log has been flushed to disk (sync). It is SAFE to remove the USB"
both "stick now and bring it back for analysis."
both ""
both "Any config files changed were backed up as *.$BAK_SUFFIX and can be"
both "restored by removing the '# [leftclick-fix disabled]' prefix."
exit 2
