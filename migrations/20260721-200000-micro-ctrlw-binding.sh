#!/bin/bash
# Migration: Add CtrlW → DeleteWordLeft to micro bindings
#
# st-wl now emits \x17 (Ctrl+W) for Ctrl+Backspace (was \x1f in the previous
# revision). This matches readline's unix-word-rubout and is what Copilot CLI,
# opencode, Claude Code and other modern TUIs expect. To keep Ctrl+Backspace
# still deleting words inside micro, we also bind CtrlW to DeleteWordLeft
# (which happens to override micro's default CtrlW = NextSplit).
#
# Idempotent: skips if CtrlW binding already present.

set -euo pipefail

BINDINGS="$HOME/.config/micro/bindings.json"

if [[ ! -f "$BINDINGS" ]]; then
    echo "  micro bindings.json not found — skipping"
    exit 0
fi

if grep -q '"CtrlW"' "$BINDINGS" 2>/dev/null; then
    echo "  CtrlW binding already present — nothing to do"
    exit 0
fi

# Inject after the CtrlUnderscore line (or CtrlBackspace as fallback)
if grep -q '"CtrlUnderscore"' "$BINDINGS"; then
    sed -i 's/"CtrlUnderscore": "DeleteWordLeft",/"CtrlUnderscore": "DeleteWordLeft",\n    "CtrlW":          "DeleteWordLeft",/' "$BINDINGS"
    echo "  Added CtrlW → DeleteWordLeft to micro bindings.json"
elif grep -q '"CtrlBackspace"' "$BINDINGS"; then
    sed -i 's/"CtrlBackspace":  "DeleteWordLeft",/"CtrlBackspace":  "DeleteWordLeft",\n    "CtrlW":          "DeleteWordLeft",/' "$BINDINGS"
    echo "  Added CtrlW → DeleteWordLeft to micro bindings.json"
else
    echo "  No existing DeleteWordLeft binding — manually add CtrlW to $BINDINGS"
fi
