#!/usr/bin/env bash
#
# smplOS — scrolling column_width / aspect-column debug tool
# ----------------------------------------------------------
# Symptom this targets: after `smplos-update` (or "Update OS" in App Center),
# new windows still open at ~95% of an ultrawide screen instead of the
# aspect-aware ~55% split that aspect_column.lua is supposed to apply.
#
# What it does:
#   • Reads every relevant piece of state and writes it to ONE big log file
#     next to this script (so it lands on your Ventoy stick / wherever this
#     was copied to).
#   • Runs a live smplos-os-update in "dry" mode (git fetch + diff only, no
#     changes) and also captures a real one if you pass --run-update.
#   • Compares shipped repo config with the currently deployed ~/.config/hypr
#     files line by line.
#   • Reloads Hyprland and re-probes state to see if a plain reload picks up
#     the new lua module or not.
#
# SAFE: read-only by default. No sudo. `--run-update` opt-in actually runs
#       `smplos-os-update` which touches the user's ~/.config/hypr/.
#
# Usage:
#   bash debug-scrolling-column.sh                # collect logs only
#   bash debug-scrolling-column.sh --run-update   # ALSO run smplos-os-update
#
# Hand me the resulting  smplos-scrolling-debug-<timestamp>.log  file.
#

set -uo pipefail

RUN_UPDATE=0
for arg in "$@"; do
    case "$arg" in
        --run-update) RUN_UPDATE=1 ;;
        *) ;;
    esac
done

TS="$(date +%Y%m%d-%H%M%S)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
[[ -z "$SCRIPT_DIR" ]] && SCRIPT_DIR="$PWD"
if [[ -w "$SCRIPT_DIR" ]]; then
    LOG="$SCRIPT_DIR/smplos-scrolling-debug-$TS.log"
else
    LOG="$HOME/smplos-scrolling-debug-$TS.log"
fi

have() { command -v "$1" >/dev/null 2>&1; }
sec()  { printf '\n===== %s =====\n' "$*" | tee -a "$LOG" >/dev/null; printf '\n\033[1m===== %s =====\033[0m\n' "$*"; }
run()  {
    # run "<label>" <cmd...> — logs the command line, its stdout+stderr, and
    # its exit code. Never fails the script.
    local label="$1"; shift
    {
        echo "--- $label ---"
        echo "\$ $*"
        "$@" 2>&1
        echo "(exit: $?)"
    } >>"$LOG" 2>&1
    printf '  · %s\n' "$label"
}
runsh() {
    # runsh "<label>" '<shell-string>' — same as run but for pipelines / shell
    # constructs that need a subshell.
    local label="$1"; shift
    {
        echo "--- $label ---"
        echo "\$ $*"
        bash -c "$*" 2>&1
        echo "(exit: $?)"
    } >>"$LOG" 2>&1
    printf '  · %s\n' "$label"
}
dump_file() {
    # dump_file "<label>" <path> — dump full file contents with a header.
    local label="$1" path="$2"
    {
        echo "--- $label ($path) ---"
        if [[ -f "$path" ]]; then
            echo "  size=$(stat -c%s "$path" 2>/dev/null) mtime=$(stat -c%y "$path" 2>/dev/null) sha256=$(sha256sum "$path" 2>/dev/null | awk '{print $1}')"
            echo "----BEGIN----"
            cat "$path"
            echo "----END----"
        else
            echo "MISSING"
        fi
    } >>"$LOG" 2>&1
    printf '  · %s\n' "$label"
}

# ── Header ─────────────────────────────────────────────────────────────────
{
    echo "smplOS scrolling / aspect-column debug log"
    echo "date          : $(date '+%Y-%m-%d %H:%M:%S %z')"
    echo "hostname      : $(hostname 2>/dev/null)"
    echo "user          : $USER (uid=$UID)"
    echo "kernel        : $(uname -r)"
    echo "arch          : $(uname -m)"
    echo "script path   : ${BASH_SOURCE[0]}"
    echo "script dir    : $SCRIPT_DIR"
    echo "log path      : $LOG"
    echo "flags         : run-update=$RUN_UPDATE"
    echo "PATH          : $PATH"
    echo "HOME          : $HOME"
    echo "XDG_RUNTIME_DIR : ${XDG_RUNTIME_DIR:-}"
    echo "WAYLAND_DISPLAY : ${WAYLAND_DISPLAY:-}"
    echo "HYPRLAND_INSTANCE_SIGNATURE : ${HYPRLAND_INSTANCE_SIGNATURE:-}"
} >"$LOG"

printf '\033[1mCollecting logs to:\033[0m %s\n' "$LOG"

# ── Section 1: System / OS identity ────────────────────────────────────────
sec "1. System identity"
runsh "os-release"           'cat /etc/os-release 2>/dev/null; cat /etc/smplos-release 2>/dev/null; cat /etc/smplos-version 2>/dev/null'
run   "uname -a"              uname -a
runsh "pacman-hyprland"      'pacman -Q hyprland 2>/dev/null; pacman -Q hyprland-git 2>/dev/null; true'
run   "hyprctl-version"       hyprctl version
runsh "hyprctl-systeminfo"   'hyprctl systeminfo 2>/dev/null | head -60'
runsh "loginctl-session"     'loginctl show-session $(loginctl | awk "/$USER/ {print \$1; exit}") 2>/dev/null || true'
runsh "processes-hypr-eww"   'pgrep -a Hyprland; pgrep -a eww; pgrep -a hyprctl; true'
runsh "uptime-users"         'uptime; who -a'

# ── Section 2: smplOS repo state ───────────────────────────────────────────
sec "2. smplOS repo state"

# The repo can be in a few conventional places — probe them all so we always
# grab something.
SMPLOS_REPO=""
for candidate in \
    "${SMPLOS_REPO:-}" \
    "${SMPLOS_PATH:-}/repo" \
    "$HOME/.local/share/smplos/repo" \
    "$HOME/smplos" \
    "$HOME/Documents/source/smpl-os/smplos" \
    "/opt/smplos" \
    "/usr/local/share/smplos/repo" \
    "/var/lib/smplos/repo"
do
    [[ -n "$candidate" && -d "$candidate/.git" ]] && SMPLOS_REPO="$candidate" && break
done

if [[ -z "$SMPLOS_REPO" ]]; then
    runsh "repo-search"      'find / -maxdepth 6 -type d -name .git 2>/dev/null | xargs -I{} dirname {} | xargs -I{} bash -c "cd {} && git remote get-url origin 2>/dev/null | grep -qi smpl-os/smplos && echo {} || true" | head -5'
    {
        echo "SMPLOS_REPO could not be auto-detected."
    } >>"$LOG"
else
    {
        echo "SMPLOS_REPO detected at: $SMPLOS_REPO"
    } >>"$LOG"
    run   "repo-remote"       git -C "$SMPLOS_REPO" remote -v
    run   "repo-branch"       git -C "$SMPLOS_REPO" branch -vv
    run   "repo-status"       git -C "$SMPLOS_REPO" status --short --branch
    runsh "repo-log-last-20" "git -C '$SMPLOS_REPO' log --oneline -20"
    runsh "repo-log-tags"    "git -C '$SMPLOS_REPO' log --oneline --decorate=short -10"
    runsh "repo-fetch"       "git -C '$SMPLOS_REPO' fetch --dry-run origin 2>&1; git -C '$SMPLOS_REPO' fetch origin 2>&1"
    runsh "repo-ahead-behind" "git -C '$SMPLOS_REPO' rev-list --left-right --count HEAD...origin/main 2>&1"
    runsh "repo-diff-a0dba42-in-log" "git -C '$SMPLOS_REPO' log --oneline a0dba42 2>&1 | head -3"
    runsh "repo-VERSION"     "cat '$SMPLOS_REPO/src/VERSION' 2>/dev/null"
fi

# ── Section 3: Shipped config vs deployed config ───────────────────────────
sec "3. Config files: shipped in repo vs deployed to ~/.config/hypr"

HYPR_DST="$HOME/.config/hypr"
if [[ -n "$SMPLOS_REPO" ]]; then
    HYPR_SRC="$SMPLOS_REPO/src/compositors/hyprland/hypr"
else
    HYPR_SRC=""
fi

for f in hyprland.lua looknfeel.lua looknfeel.conf aspect_column.lua autostart.lua bindings_loader.lua monitors_loader.lua windows.lua; do
    if [[ -n "$HYPR_SRC" ]]; then
        dump_file "SRC $f" "$HYPR_SRC/$f"
    fi
    dump_file "DST $f" "$HYPR_DST/$f"
    if [[ -n "$HYPR_SRC" && -f "$HYPR_SRC/$f" && -f "$HYPR_DST/$f" ]]; then
        runsh "diff $f" "diff -u '$HYPR_SRC/$f' '$HYPR_DST/$f' | head -200"
    fi
done

runsh "hypr-dir-listing"    "ls -la '$HYPR_DST' 2>/dev/null"
runsh "hypr-dir-lua-files"  "ls -la '$HYPR_DST'/*.lua 2>/dev/null"

# Sanity: does hyprland.lua actually contain the require line?
runsh "grep-require-aspect_column" "grep -n aspect_column '$HYPR_DST/hyprland.lua' '$HYPR_SRC/hyprland.lua' 2>/dev/null"
runsh "grep-fullscreen_on_one_column" "grep -n fullscreen_on_one_column '$HYPR_DST/looknfeel.lua' '$HYPR_DST/looknfeel.conf' '$HYPR_SRC/looknfeel.lua' '$HYPR_SRC/looknfeel.conf' 2>/dev/null"

# Are both hyprland.lua AND hyprland.conf being loaded? Hyprland prefers .lua
# when present but this ends up biting people, so verify.
runsh "hyprland-conf-present"   "ls -la '$HYPR_DST/hyprland.conf' 2>/dev/null; wc -l '$HYPR_DST/hyprland.conf' 2>/dev/null"
runsh "hyprland-conf-scroll-block" "grep -n -A6 'scrolling {' '$HYPR_DST/hyprland.conf' 2>/dev/null"

# ── Section 4: Live Hyprland state ─────────────────────────────────────────
sec "4. Live Hyprland state"

if ! have hyprctl; then
    echo "hyprctl not on PATH — skipping live probe" >>"$LOG"
else
    runsh "monitors-json"       'hyprctl -j monitors 2>&1'
    runsh "monitors-plain"      'hyprctl monitors 2>&1'
    runsh "active-window"       'hyprctl activewindow 2>&1'
    runsh "active-workspace"    'hyprctl activeworkspace 2>&1'
    runsh "workspaces"          'hyprctl workspaces 2>&1'
    runsh "cursor-pos"          'hyprctl cursorpos 2>&1'
    runsh "layers"              'hyprctl layers 2>&1 | head -80'
    runsh "clients-brief"       'hyprctl clients 2>&1 | grep -E "^Window|monitor:|workspace:|at:|size:" | head -120'

    for k in scrolling:column_width scrolling:fullscreen_on_one_column scrolling:focus_fit_method scrolling:follow_focus general:layout; do
        runsh "getoption $k"    "hyprctl getoption $k 2>&1"
    done

    runsh "configerrors-before"    'hyprctl configerrors 2>&1'
    runsh "instances"              'hyprctl instances 2>&1'
    runsh "splash"                 'hyprctl splash 2>&1'
fi

# ── Section 5: Compute what aspect_column WOULD apply right now ────────────
sec "5. What aspect_column.lua should be computing"
runsh "aspect-compute" 'python3 - <<PYEOF 2>&1 || bash -c "echo python3 missing"
import json, subprocess
try:
    out = subprocess.check_output(["hyprctl","-j","monitors"], text=True)
    mons = json.loads(out)
except Exception as e:
    print("hyprctl -j monitors failed:", e); raise SystemExit
def wid(a):
    if a >= 2.8: return 0.50
    if a >= 2.0: return 0.55
    return 0.95
for m in mons:
    w, h, t = m.get("width",0), m.get("height",0), m.get("transform",0)
    if t in (1,3):
        w, h = h, w
    a = (w / h) if h else 0
    print(f"  {m.get(\"name\")}: physical={m.get(\"width\")}x{m.get(\"height\")} transform={t} scale={m.get(\"scale\")} focused={m.get(\"focused\")} → visible_wxh={w}x{h} aspect={a:.3f} → column_width={wid(a):.2f}")
PYEOF'

# ── Section 6: Hyprland logs (lua errors, config errors) ───────────────────
sec "6. Hyprland session logs"

# Hyprland writes logs under $XDG_RUNTIME_DIR/hypr/<HIS>/hyprland.log
HIS="${HYPRLAND_INSTANCE_SIGNATURE:-}"
if [[ -n "$HIS" && -n "${XDG_RUNTIME_DIR:-}" ]]; then
    HYPR_LOG="$XDG_RUNTIME_DIR/hypr/$HIS/hyprland.log"
    dump_file "hyprland.log (last 400 lines)" /dev/null  # placeholder header
    {
        echo "--- hyprland.log tail 400 ($HYPR_LOG) ---"
        if [[ -f "$HYPR_LOG" ]]; then
            tail -400 "$HYPR_LOG"
        else
            echo "MISSING"
        fi
    } >>"$LOG"
else
    echo "HIS or XDG_RUNTIME_DIR not set — scanning all instance logs" >>"$LOG"
    runsh "all-hyprland-logs" 'for f in "$XDG_RUNTIME_DIR"/hypr/*/hyprland.log; do echo "== $f =="; tail -200 "$f" 2>/dev/null; done'
fi

runsh "hyprland-log-grep-lua"    'grep -n -i "lua\|aspect_column\|require\|error\|attempt to call\|nil value" "$XDG_RUNTIME_DIR"/hypr/*/hyprland.log 2>/dev/null | tail -80'
runsh "hyprland-log-grep-scroll" 'grep -n -i "scrolling\|column_width\|fullscreen_on_one" "$XDG_RUNTIME_DIR"/hypr/*/hyprland.log 2>/dev/null | tail -40'
runsh "journal-user-hypr"        'journalctl --user -b --no-pager -o cat 2>/dev/null | grep -iE "hyprland|aspect_column|smplos" | tail -80'
runsh "journal-user-smplos"      'journalctl --user -b --no-pager -o cat 2>/dev/null | grep -iE "smplos-update|smplos-os-update|sync_hypr" | tail -80'
runsh "journal-system-smplos"    'journalctl -b --no-pager -o cat 2>/dev/null | grep -iE "smplos" | tail -60'

# ── Section 7: Bar / EWW status ────────────────────────────────────────────
sec "7. Bar / EWW status"
runsh "bar-ctl-status"       'bar-ctl status 2>&1 || true'
runsh "eww-state"            'eww state 2>&1 | head -60 || true'
runsh "eww-active-windows"   'eww active-windows 2>&1 || true'

# ── Section 8: A/B — force a reload and re-probe ───────────────────────────
sec "8. Force reload, then re-probe"
if have hyprctl; then
    {
        echo "BEFORE reload:"
        echo "  column_width: $(hyprctl getoption scrolling:column_width 2>/dev/null | head -1)"
        echo "  fullscreen_on_one_column: $(hyprctl getoption scrolling:fullscreen_on_one_column 2>/dev/null | head -1)"
    } >>"$LOG"

    run "hyprctl-reload"  hyprctl reload
    sleep 1

    {
        echo "AFTER reload:"
        echo "  column_width: $(hyprctl getoption scrolling:column_width 2>/dev/null | head -1)"
        echo "  fullscreen_on_one_column: $(hyprctl getoption scrolling:fullscreen_on_one_column 2>/dev/null | head -1)"
        echo "  configerrors:"
        hyprctl configerrors 2>&1 | sed 's/^/    /'
    } >>"$LOG"

    run "reload-log-tail-after" bash -c 'tail -80 "$XDG_RUNTIME_DIR"/hypr/*/hyprland.log 2>/dev/null'

    # Try setting column_width manually to confirm the option is actually
    # writable at runtime. Hyprland 0.55+ with a Lua config REJECTS
    # `hyprctl keyword`; the supported path is `hyprctl eval hl.config(...)`.
    run "manual-keyword-0.55 (legacy path, expected to fail on lua)" hyprctl keyword scrolling:column_width 0.55
    sleep 1
    {
        echo "AFTER manual keyword 0.55 (legacy attempt):"
        echo "  column_width: $(hyprctl getoption scrolling:column_width 2>/dev/null | head -1)"
    } >>"$LOG"
    run "manual-eval-0.55 (lua path, expected to succeed)" hyprctl eval "hl.config({ scrolling = { column_width = 0.55 } })"
    sleep 1
    {
        echo "AFTER manual eval hl.config(0.55):"
        echo "  column_width: $(hyprctl getoption scrolling:column_width 2>/dev/null | head -1)"
    } >>"$LOG"
    # Trigger a reload so aspect_column re-applies the correct value for the
    # currently focused monitor (undoes the manual override above).
    run "reload-to-restore" hyprctl reload
    sleep 1
    {
        echo "AFTER reload (aspect_column should have re-applied):"
        echo "  column_width: $(hyprctl getoption scrolling:column_width 2>/dev/null | head -1)"
    } >>"$LOG"
fi

# ── Section 9: Run smplos-os-update (if opted in) ──────────────────────────
sec "9. smplos-os-update dry / real run"

run "which-smplos-os-update"  which smplos-os-update
run "which-smplos-update"     which smplos-update
runsh "smplos-os-update --check" 'smplos-os-update --check 2>&1 || true'

if [[ $RUN_UPDATE -eq 1 ]]; then
    echo "Running actual smplos-os-update — this will pull + sync configs." >>"$LOG"
    runsh "smplos-os-update-real" 'smplos-os-update 2>&1'
    sleep 2

    {
        echo "POST-update file mtimes:"
    } >>"$LOG"
    for f in hyprland.lua looknfeel.lua looknfeel.conf aspect_column.lua; do
        runsh "post-update stat $f" "stat -c '%y %n' '$HYPR_DST/$f' 2>/dev/null"
    done

    run "hyprctl-reload-post-update" hyprctl reload
    sleep 1
    {
        echo "POST-update + reload:"
        echo "  column_width: $(hyprctl getoption scrolling:column_width 2>/dev/null | head -1)"
        echo "  fullscreen_on_one_column: $(hyprctl getoption scrolling:fullscreen_on_one_column 2>/dev/null | head -1)"
        echo "  configerrors:"
        hyprctl configerrors 2>&1 | sed 's/^/    /'
    } >>"$LOG"
else
    echo "Skipped actual update — pass --run-update to include it." >>"$LOG"
fi

# ── Section 10: Filesystem sanity ──────────────────────────────────────────
sec "10. Filesystem sanity"
runsh "df-h"                  'df -h | head -20'
runsh "smplos-state-dir"      'ls -la "$HOME/.local/share/smplos" 2>/dev/null; ls -la "$HOME/.local/state/smplos" 2>/dev/null'
runsh "config-hypr-tree"      'find "$HOME/.config/hypr" -maxdepth 2 -printf "%TY-%Tm-%Td %TH:%TM %p\n" 2>/dev/null | sort'
runsh "pkexec-agent"          'pgrep -a polkit; test -e /usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1 && echo present || echo missing'

# ── Trailer ────────────────────────────────────────────────────────────────
sec "Done"
sync 2>/dev/null || true

# Also drop a copy in $HOME so the log survives even if the USB was pulled
# without unmounting.
if [[ "$LOG" != "$HOME/$(basename "$LOG")" ]]; then
    cp -f "$LOG" "$HOME/$(basename "$LOG")" 2>/dev/null && \
        printf '  · Copied to %s\n' "$HOME/$(basename "$LOG")"
fi

{
    echo
    echo "== end =="
    echo "log size: $(stat -c%s "$LOG") bytes"
} >>"$LOG"

printf '\n\033[1;32mLog written to:\033[0m %s\n' "$LOG"
printf '\033[1mHand this file back for analysis.\033[0m\n'
