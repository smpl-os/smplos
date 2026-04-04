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

# --check mode: regenerate into a clean git work tree, then diff.
# Uses git to detect any stale/manually-edited generated file.
if $CHECK_MODE; then
  echo "Checking theme files are up to date..."
  echo ""

  # Run the generators (they write in-place)
  bash "$SCRIPT_DIR/generate-theme-configs.sh" > /dev/null
  python3 "$SCRIPT_DIR/regen-nemo-css.py" > /dev/null

  # Ask git if anything changed
  cd "$SCRIPT_DIR/.."
  if git diff --quiet -- src/shared/themes/; then
    echo "✓ All theme files are up to date."
    exit 0
  else
    echo "✗ Generated theme files are out of sync with their generators!"
    echo "  The following files differ from what the generators would produce:"
    echo ""
    git diff --name-only -- src/shared/themes/
    echo ""
    echo "  Run:  cd src && bash regen-all-themes.sh"
    echo "  Then commit the result."
    exit 1
  fi
fi

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
