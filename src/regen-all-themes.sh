#!/bin/bash
# smplOS theme regeneration — single entry point for ALL theme file generation.
#
# This is the ONE script to run when changing any theme template or colors.toml.
# Never run generate-theme-configs.sh or regen-nemo-css.py directly — always
# use this script so both generators run in the correct order.
#
# Usage:
#   ./regen-all-themes.sh            — regenerate all theme files
#   ./regen-all-themes.sh --check    — verify generated files are up to date
#                                      (exits 1 if any file is out of sync)
#
# Generators and their outputs:
#   generate-theme-configs.sh  →  *.{theme,conf,ini,scss,yuck,rasi,css,lua}
#                                  (all templates EXCEPT nemo.css)
#   regen-nemo-css.py          →  nemo.css  (GTK CSS with correct specificity
#                                  and submenu reset blocks — cannot be done
#                                  with simple sed template expansion)
#
# Why nemo.css has its own generator — see copilot-instructions.md:
#   "Nemo CSS Theming (REGRESSION-PRONE)"
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHECK_MODE=false

for arg in "$@"; do
  case "$arg" in
    --check) CHECK_MODE=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

# --check compares isolated outputs with the working tree, not the git baseline.
if $CHECK_MODE; then
  exec python3 "$SCRIPT_DIR/check-theme-generation.py"
fi

# Reject invalid alpha before either generator publishes any theme.
python3 "$SCRIPT_DIR/theme_opacity.py" "$SCRIPT_DIR"/shared/themes/*/colors.toml >/dev/null

# Normal regeneration mode
echo "=== smplOS theme regeneration ==="
echo ""

echo "Step 1/2 — Template expansion (generate-theme-configs.sh)..."
bash "$SCRIPT_DIR/generate-theme-configs.sh"
echo ""

echo "Step 2/2 — Nemo GTK CSS (regen-nemo-css.py)..."
python3 "$SCRIPT_DIR/regen-nemo-css.py"
echo ""

echo "Done. All theme files regenerated."
echo "Tip: run with --check to verify files match generators (for CI / pre-commit)."
