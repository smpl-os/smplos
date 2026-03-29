#!/bin/bash
# Migration: Add ShiftDelete → Cut|CutLine to micro bindings
#
# Shift-Delete should cut the selection (or current line) to the clipboard,
# matching standard Windows/Linux editor behavior.

set -euo pipefail

BINDINGS="$HOME/.config/micro/bindings.json"

if [[ ! -f "$BINDINGS" ]]; then
    echo "  micro bindings.json not found — skipping"
    exit 0
fi

if grep -q '"ShiftDelete"' "$BINDINGS" 2>/dev/null; then
    echo "  ShiftDelete binding already present — nothing to do"
    exit 0
fi

# Insert ShiftDelete binding before the closing brace
# Find the last non-brace line, ensure it has a trailing comma, then add the new binding
if python3 -c "
import json, sys
with open('$BINDINGS') as f:
    data = json.load(f)
data['ShiftDelete'] = 'Cut|CutLine'
with open('$BINDINGS', 'w') as f:
    json.dump(data, f, indent=4)
    f.write('\n')
" 2>/dev/null; then
    echo "  Added ShiftDelete → Cut|CutLine to micro bindings.json"
else
    echo "  Failed to update bindings.json — manually add ShiftDelete binding"
    exit 1
fi
