# shellcheck shell=bash
# smplos-session-env.sh — resolve the invoking user's graphical session
#
# SOURCE THIS FILE, DO NOT EXECUTE IT.
#
# ── Why this exists ──────────────────────────────────────────────────────────
# Legacy updaters elevated the entire orchestration with pkexec. pkexec
# sanitizes the environment: XDG_RUNTIME_DIR, WAYLAND_DISPLAY, DISPLAY,
# DBUS_SESSION_BUS_ADDRESS and HYPRLAND_INSTANCE_SIGNATURE are all dropped.
# `smplos-os-update` restores HOME/USER/LOGNAME and exports SMPLOS_INVOKER_*,
# then runs migrations under `runuser -u $SMPLOS_INVOKER_USER`. runuser
# restores the *identity* but cannot restore variables that no longer exist in
# the parent environment — so migrations run as the right user with no
# graphical session attached.
# Current Update OS stays in the desktop user's tty and elevates individual
# operations; this helper still supports legacy callers and session recovery.
#
# Consequences observed on real machines:
#   * session clients derive IPC sockets from XDG_RUNTIME_DIR. Unsetting it can
#     make a management command address a different runtime transport.
#     compositor ("Failed to initialize GTK"). The user was left with no bar.
#   * `hyprctl` aborts with "HYPRLAND_INSTANCE_SIGNATURE not set!".
#   * `systemctl --user` aborts with "Failed to connect to user scope bus via
#     local transport: $DBUS_SESSION_BUS_ADDRESS and $XDG_RUNTIME_DIR not
#     defined".
#
# ── Usage ────────────────────────────────────────────────────────────────────
#   source .../smplos-session-env.sh
#
#   if smplos_have_session; then
#       smplos_run_as_user bar-ctl start
#   else
#       echo "  No graphical session — restart the bar manually."
#   fi
#
#   smplos_have_hyprland && smplos_run_as_user hyprctl reload
#
# Safety contract: NEVER tear down a piece of the user's session (bar, daemon,
# plugin) unless `smplos_have_session` has already returned success. Leaving a
# user with no status bar is far worse than deferring a restart.
#
# This file is `set -euo pipefail` safe: every expansion is guarded and the
# predicate helpers are designed to be used inside `if`/`&&`/`||`, which
# suspends `errexit`. Do not call them bare under `set -e`.

# Idempotent source guard — migrations may source this more than once.
if [[ -n "${_SMPLOS_SESSION_ENV_LOADED:-}" ]]; then
    return 0 2>/dev/null || true
fi
_SMPLOS_SESSION_ENV_LOADED=1

# Populated by smplos_resolve_session_env(). Declared up front so `set -u`
# never trips on a caller that reads them before resolving.
SMPLOS_SESSION_UID=""
SMPLOS_SESSION_USER=""
SMPLOS_SESSION_HOME=""
SMPLOS_SESSION_RUNTIME_DIR=""
SMPLOS_SESSION_WAYLAND_DISPLAY=""
SMPLOS_SESSION_DISPLAY=""
SMPLOS_SESSION_XAUTHORITY=""
SMPLOS_SESSION_DBUS=""
SMPLOS_SESSION_HIS=""
_SMPLOS_SESSION_RESOLVED=""

# ── Internal: newest matching path ───────────────────────────────────────────
# Prints the most recently modified path from stdin-free glob arguments that
# satisfy `test $1 <path>`. Empty output when nothing matches.
_smplos_newest() {
    local test_op="$1"; shift
    local candidate newest=""
    for candidate in "$@"; do
        # Unmatched globs arrive as the literal pattern; the test rejects them.
        [[ -e "$candidate" ]] || continue
        test "$test_op" "$candidate" || continue
        if [[ -z "$newest" || "$candidate" -nt "$newest" ]]; then
            newest="$candidate"
        fi
    done
    [[ -n "$newest" ]] && printf '%s' "$newest"
    return 0
}

# ── Internal: which uid owns the graphical session we should target? ─────────
# Order: SMPLOS_INVOKER_UID (set by smplos-update/smplos-os-update after
# pkexec) → PKEXEC_UID → SUDO_UID → our own uid when unprivileged. As a last
# resort (root shell with no invoker hint at all, e.g. `su -` then
# smplos-migrate) probe /run/user/* and accept it only when exactly one user
# has a live Wayland or X11 session, so we can never guess wrong on a
# multi-seat box.
_smplos_resolve_uid() {
    local cand uid=""
    for cand in "${SMPLOS_INVOKER_UID:-}" "${PKEXEC_UID:-}" "${SUDO_UID:-}"; do
        if [[ -n "$cand" && "$cand" != "0" ]]; then
            uid="$cand"
            break
        fi
    done

    if [[ -z "$uid" ]]; then
        local self_uid
        self_uid="$(id -u 2>/dev/null || echo 0)"
        [[ "$self_uid" != "0" ]] && uid="$self_uid"
    fi

    if [[ -z "$uid" ]]; then
        local dir sock found=() n=0
        for dir in /run/user/*; do
            [[ -d "$dir" ]] || continue
            n="${dir##*/}"
            [[ "$n" =~ ^[0-9]+$ && "$n" != "0" ]] || continue
            for sock in "$dir"/wayland-*; do
                if [[ -S "$sock" ]]; then
                    found+=("$n")
                    break
                fi
            done
        done
        [[ ${#found[@]} -eq 1 ]] && uid="${found[0]}"
    fi

    printf '%s' "$uid"
    return 0
}

# ── Resolve the invoker's graphical session ──────────────────────────────────
# Populates the SMPLOS_SESSION_* variables above. Returns 0 when a usable
# graphical session (Wayland or X11) was found, 1 otherwise. Results are
# memoized; unset _SMPLOS_SESSION_RESOLVED to force a re-probe.
smplos_resolve_session_env() {
    if [[ -n "$_SMPLOS_SESSION_RESOLVED" ]]; then
        [[ "$_SMPLOS_SESSION_RESOLVED" == "yes" ]] && return 0
        return 1
    fi
    _SMPLOS_SESSION_RESOLVED="no"

    SMPLOS_SESSION_UID="$(_smplos_resolve_uid)"
    [[ -n "$SMPLOS_SESSION_UID" ]] || return 1

    local ent
    ent="$(getent passwd "$SMPLOS_SESSION_UID" 2>/dev/null || true)"
    if [[ -n "$ent" ]]; then
        SMPLOS_SESSION_USER="$(cut -d: -f1 <<<"$ent")"
        SMPLOS_SESSION_HOME="$(cut -d: -f6 <<<"$ent")"
    else
        SMPLOS_SESSION_USER="${SMPLOS_INVOKER_USER:-}"
        SMPLOS_SESSION_HOME="${SMPLOS_INVOKER_HOME:-}"
    fi

    # ── XDG_RUNTIME_DIR ──────────────────────────────────────────────────────
    # Prefer the canonical /run/user/<uid>. Only trust an inherited value when
    # it actually belongs to the target uid — under `sudo` it is often still
    # /run/user/0, which has no compositor in it.
    local rt="/run/user/$SMPLOS_SESSION_UID"
    if [[ ! -d "$rt" ]]; then
        rt=""
        if [[ -n "${XDG_RUNTIME_DIR:-}" && -d "${XDG_RUNTIME_DIR}" ]]; then
            local owner
            owner="$(stat -c %u "$XDG_RUNTIME_DIR" 2>/dev/null || echo "")"
            [[ "$owner" == "$SMPLOS_SESSION_UID" ]] && rt="$XDG_RUNTIME_DIR"
        fi
    fi
    SMPLOS_SESSION_RUNTIME_DIR="$rt"
    [[ -n "$rt" ]] || return 1

    # ── Wayland ──────────────────────────────────────────────────────────────
    # `-S` matters: it accepts wayland-1 (a socket) and rejects wayland-1.lock
    # (a regular file) and the literal glob when nothing matches.
    if [[ -n "${WAYLAND_DISPLAY:-}" && -S "$rt/${WAYLAND_DISPLAY}" ]]; then
        SMPLOS_SESSION_WAYLAND_DISPLAY="$WAYLAND_DISPLAY"
    else
        local wl
        wl="$(_smplos_newest -S "$rt"/wayland-*)"
        [[ -n "$wl" ]] && SMPLOS_SESSION_WAYLAND_DISPLAY="${wl##*/}"
    fi

    # ── Hyprland instance ────────────────────────────────────────────────────
    # Require .socket.sock so a stale directory left behind by a crashed
    # session can never be selected over the live one.
    if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" \
          && -S "$rt/hypr/${HYPRLAND_INSTANCE_SIGNATURE}/.socket.sock" ]]; then
        SMPLOS_SESSION_HIS="$HYPRLAND_INSTANCE_SIGNATURE"
    elif [[ -d "$rt/hypr" ]]; then
        local inst newest="" d
        for d in "$rt"/hypr/*; do
            [[ -S "$d/.socket.sock" ]] || continue
            if [[ -z "$newest" || "$d" -nt "$newest" ]]; then
                newest="$d"
            fi
        done
        if [[ -n "$newest" ]]; then
            inst="${newest##*/}"
            SMPLOS_SESSION_HIS="$inst"
        fi
    fi

    # ── D-Bus session bus ────────────────────────────────────────────────────
    if [[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
        SMPLOS_SESSION_DBUS="$DBUS_SESSION_BUS_ADDRESS"
    elif [[ -S "$rt/bus" ]]; then
        SMPLOS_SESSION_DBUS="unix:path=$rt/bus"
    fi

    # ── X11 (DWM edition, and XWayland under Hyprland) ───────────────────────
    if [[ -n "${DISPLAY:-}" ]]; then
        SMPLOS_SESSION_DISPLAY="$DISPLAY"
    else
        local s n owner
        for s in /tmp/.X11-unix/X*; do
            [[ -S "$s" ]] || continue
            n="${s##*/X}"
            # Skip X0_ and friends — only bare display numbers are valid.
            [[ "$n" =~ ^[0-9]+$ ]] || continue
            owner="$(stat -c %u "$s" 2>/dev/null || echo "")"
            [[ "$owner" == "$SMPLOS_SESSION_UID" ]] || continue
            SMPLOS_SESSION_DISPLAY=":$n"
            break
        done
    fi

    if [[ -n "${XAUTHORITY:-}" && -f "${XAUTHORITY}" ]]; then
        SMPLOS_SESSION_XAUTHORITY="$XAUTHORITY"
    elif [[ -n "$SMPLOS_SESSION_HOME" && -f "$SMPLOS_SESSION_HOME/.Xauthority" ]]; then
        SMPLOS_SESSION_XAUTHORITY="$SMPLOS_SESSION_HOME/.Xauthority"
    fi

    if [[ -n "$SMPLOS_SESSION_WAYLAND_DISPLAY" || -n "$SMPLOS_SESSION_DISPLAY" ]]; then
        _SMPLOS_SESSION_RESOLVED="yes"
        return 0
    fi
    return 1
}

# ── Predicates ───────────────────────────────────────────────────────────────
# True when a Wayland or X11 session belonging to the invoker was found.
smplos_have_session() {
    smplos_resolve_session_env
}

# True when a live Hyprland instance was found (implies have_session).
smplos_have_hyprland() {
    smplos_resolve_session_env || return 1
    [[ -n "$SMPLOS_SESSION_HIS" ]]
}

# True when the user's systemd --user manager is reachable.
smplos_have_user_bus() {
    smplos_resolve_session_env || return 1
    [[ -n "$SMPLOS_SESSION_RUNTIME_DIR" ]]
}

# One-line summary for logs / debugging.
smplos_session_summary() {
    smplos_resolve_session_env || true
    printf 'uid=%s user=%s runtime=%s wayland=%s display=%s hypr=%s bus=%s\n' \
        "${SMPLOS_SESSION_UID:-none}" \
        "${SMPLOS_SESSION_USER:-none}" \
        "${SMPLOS_SESSION_RUNTIME_DIR:-none}" \
        "${SMPLOS_SESSION_WAYLAND_DISPLAY:-none}" \
        "${SMPLOS_SESSION_DISPLAY:-none}" \
        "${SMPLOS_SESSION_HIS:-none}" \
        "${SMPLOS_SESSION_DBUS:-none}"
}

# ── Run a command inside the invoker's graphical session ─────────────────────
# Restores the variables pkexec stripped and, when we are root, drops back to
# the invoking user with runuser. When already unprivileged it execs directly,
# so a migration behaves identically whether it was reached through pkexec or
# straight from a user shell.
#
# Returns the command's exit status. Returns 1 without running anything when no
# session could be resolved — callers that tear something down MUST gate on
# smplos_have_session first rather than relying on this.
smplos_run_as_user() {
    [[ $# -gt 0 ]] || return 0
    smplos_resolve_session_env || return 1

    local envs=("XDG_RUNTIME_DIR=$SMPLOS_SESSION_RUNTIME_DIR")
    [[ -n "$SMPLOS_SESSION_HOME" ]] && envs+=("HOME=$SMPLOS_SESSION_HOME")
    [[ -n "$SMPLOS_SESSION_USER" ]] && envs+=(
        "USER=$SMPLOS_SESSION_USER" "LOGNAME=$SMPLOS_SESSION_USER")
    [[ -n "$SMPLOS_SESSION_WAYLAND_DISPLAY" ]] && \
        envs+=("WAYLAND_DISPLAY=$SMPLOS_SESSION_WAYLAND_DISPLAY")
    [[ -n "$SMPLOS_SESSION_DISPLAY" ]] && envs+=("DISPLAY=$SMPLOS_SESSION_DISPLAY")
    [[ -n "$SMPLOS_SESSION_XAUTHORITY" ]] && \
        envs+=("XAUTHORITY=$SMPLOS_SESSION_XAUTHORITY")
    [[ -n "$SMPLOS_SESSION_DBUS" ]] && \
        envs+=("DBUS_SESSION_BUS_ADDRESS=$SMPLOS_SESSION_DBUS")
    [[ -n "$SMPLOS_SESSION_HIS" ]] && \
        envs+=("HYPRLAND_INSTANCE_SIGNATURE=$SMPLOS_SESSION_HIS")

    # pkexec replaces PATH with a minimal default that may omit /usr/local/bin,
    # where every smplOS script (bar-ctl, theme-set, …) lives.
    local path="${PATH:-/usr/local/bin:/usr/bin:/bin}"
    [[ ":$path:" == *":/usr/local/bin:"* ]] || path="/usr/local/bin:$path"
    envs+=("PATH=$path")

    if [[ "$(id -u)" == "0" && -n "$SMPLOS_SESSION_USER" \
          && "$SMPLOS_SESSION_UID" != "0" ]]; then
        if command -v runuser &>/dev/null; then
            runuser -u "$SMPLOS_SESSION_USER" -- env "${envs[@]}" "$@"
            return $?
        fi
        if command -v sudo &>/dev/null; then
            sudo -u "$SMPLOS_SESSION_USER" env "${envs[@]}" "$@"
            return $?
        fi
        return 1
    fi

    env "${envs[@]}" "$@"
}
