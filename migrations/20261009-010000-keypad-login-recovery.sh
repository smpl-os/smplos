#!/bin/bash
# Catch up installs that already marked the original keypad migration complete.
# The same idempotent reconciliation also runs on every normal OS update.
set -euo pipefail
bash "$(dirname "${BASH_SOURCE[0]}")/20261007-123000-macro-keypad-support.sh"
