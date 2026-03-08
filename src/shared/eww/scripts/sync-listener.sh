#!/bin/bash
# EWW sync-center state listener
# Polls the sync-center daemon's IsActive D-Bus property every 2s.
# Emits one JSON line per state change: {"active":"yes/no"}
#
# The sync-center daemon exposes:
#   Bus:    session  (--user)
#   Name:   org.smpl.SyncCenter
#   Object: /org/smpl/SyncCenter
#   Iface:  org.smpl.SyncCenter
#   Prop:   IsActive (bool)

DAEMON="org.smpl.SyncCenter"
OBJECT="/org/smpl/SyncCenter"
IFACE="org.smpl.SyncCenter"

emit() {
    printf '{"active":"%s"}\n' "$1"
}

# ── Check if daemon is on the bus ─────────────────────────────────────────────
daemon_running() {
    busctl --user status "$DAEMON" &>/dev/null 2>&1
}

# ── Query IsActive property ───────────────────────────────────────────────────
get_active() {
    local val
    val=$(busctl --user get-property "$DAEMON" "$OBJECT" "$IFACE" IsActive \
          2>/dev/null | awk '{print $2}')
    [[ "$val" == "true" ]] && echo "yes" || echo "no"
}

# ── Main loop ─────────────────────────────────────────────────────────────────
last=""

emit "no"   # initial output so eww never starts with stale data

while true; do
    if daemon_running; then
        active=$(get_active)
    else
        active="no"
    fi

    # Only emit on state transitions to avoid flooding eww
    if [[ "$active" != "$last" ]]; then
        emit "$active"
        last="$active"
    fi

    sleep 2
done
