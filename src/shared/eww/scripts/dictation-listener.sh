#!/bin/bash
# EWW dictation state listener
# Output: single-line JSON {"installed":"yes/no","recording":"yes/no"}
# Follows voxtype status --follow for live recording state updates.
# Falls back to polling if the daemon exits unexpectedly.

emit() {
    printf '{"installed":"%s","recording":"%s"}\n' "$1" "$2"
}

# ── Not installed: poll until it appears ──────────────────────────────────────
wait_for_install() {
    emit "no" "no"
    while sleep 10; do
        if command -v voxtype &>/dev/null; then
            return 0
        fi
        emit "no" "no"
    done
}

# ── Main loop: reconnect if daemon dies ───────────────────────────────────────
while true; do
    # Wait until voxtype is installed
    if ! command -v voxtype &>/dev/null; then
        wait_for_install
    fi

    # Ensure the service is running before trying --follow
    if ! systemctl --user is-active --quiet voxtype.service 2>/dev/null; then
        emit "yes" "no"
        # Poll until it starts (user might toggle it via keybind which auto-starts)
        while ! systemctl --user is-active --quiet voxtype.service 2>/dev/null; do
            sleep 3
        done
    fi

    # Initial state
    emit "yes" "no"

    # Follow mode: voxtype emits one JSON line per state change
    voxtype status --follow --format json 2>/dev/null | while IFS= read -r line; do
        class=$(printf '%s' "$line" | grep -o '"class":"[^"]*"' | cut -d'"' -f4)
        recording="no"
        [[ "$class" == "recording" ]] && recording="yes"
        emit "yes" "$recording"
    done

    # Daemon exited or pipe broke — reset to idle and retry after a pause
    emit "yes" "no"
    sleep 3
done
