#!/bin/bash
# EWW dictation state listener
# Output: single-line JSON {"installed":true/false,"recording":true/false}
# Follows voxtype status --follow for live recording state updates.

emit() {
    printf '{"installed":%s,"recording":%s}\n' "$1" "$2"
}

# If voxtype is not installed, emit not-installed and keep polling
# (recheck every 10 s so the pill updates if the user runs dictation-setup)
if ! command -v voxtype &>/dev/null; then
    emit "false" "false"
    while sleep 10; do
        if command -v voxtype &>/dev/null; then
            exec "$0"
        fi
        emit "false" "false"
    done
    exit 0
fi

# Initial state (idle)
emit "true" "false"

# Follow mode: voxtype emits one JSON line per state change
voxtype status --follow --format json 2>/dev/null | while IFS= read -r line; do
    class=$(printf '%s' "$line" | grep -o '"class":"[^"]*"' | cut -d'"' -f4)
    recording="false"
    [[ "$class" == "recording" ]] && recording="true"
    emit "true" "$recording"
done

# Daemon exited — fall back to slow polling so EWW stays alive
while sleep 5; do
    emit "true" "false"
done
