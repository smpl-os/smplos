#!/bin/bash
# Migration: Add CtrlUnderscore → DeleteWordLeft to micro bindings
#
# The st terminal sends \x1f (Ctrl+_) for Ctrl+Backspace after the st-smpl fix
# that changed the key from \x17 (Ctrl+W) to \x1f (Ctrl+Underscore).
# Micro recognises \x1f as "CtrlUnderscore", so we bind it to DeleteWordLeft.

set -euo pipefail

BINDINGS="$HOME/.config/micro/bindings.json"

if [[ ! -f "$BINDINGS" ]]; then
    echo "  micro bindings.json not found — skipping"
    exit 0
fi

if grep -q '"CtrlUnderscore"' "$BINDINGS" 2>/dev/null; then
    echo "  CtrlUnderscore binding already present — nothing to do"
    exit 0
fi

# Inject after the CtrlBackspace line (or any DeleteWordLeft line)
if grep -q '"CtrlBackspace"' "$BINDINGS"; then
    sed -i 's/"CtrlBackspace":  "DeleteWordLeft",/"CtrlBackspace":  "DeleteWordLeft",\n    "CtrlUnderscore": "DeleteWordLeft",/' "$BINDINGS"
    echo "  Added CtrlUnderscore → DeleteWordLeft to micro bindings.json"
else
    echo "  CtrlBackspace binding not found — manually add CtrlUnderscore to $BINDINGS"
fi
