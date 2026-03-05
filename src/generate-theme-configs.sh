#!/bin/bash
# smplOS Dev Tool: Generate all config files for every theme
# Reads colors.toml from each theme, expands _templates, writes results into the theme dir
# Run this whenever you change a template or add a new theme.
#
# Variable naming: colors.toml defines WHAT each color DOES (semantic roles),
# not what it looks like. The terminal palette (ANSI slots 0-15) is auto-derived.
# Override with explicit term_N if a slot needs to differ from its semantic source.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
THEMES_DIR="$SCRIPT_DIR/shared/themes"
TEMPLATES_DIR="$THEMES_DIR/_templates"

if [[ ! -d "$TEMPLATES_DIR" ]]; then
  echo "ERROR: Templates directory not found: $TEMPLATES_DIR"
  exit 1
fi

hex_to_rgb() {
  local hex="${1#\#}"
  printf "%d,%d,%d" "0x${hex:0:2}" "0x${hex:2:2}" "0x${hex:4:2}"
}

# Add a key+value to the sed script with plain, _strip, and _rgb variants
emit_sed_entry() {
  local key="$1" value="$2" out="$3"
  [[ -n "$value" ]] || return 0
  printf 's|{{ %s }}|%s|g\n' "$key" "$value" >> "$out"
  printf 's|{{ %s_strip }}|%s|g\n' "$key" "${value#\#}" >> "$out"
  if [[ $value =~ ^# ]]; then
    local rgb
    rgb=$(hex_to_rgb "$value")
    printf 's|{{ %s_rgb }}|%s|g\n' "$key" "$rgb" >> "$out"
  fi
}

generate_theme() {
  local theme_dir="$1"
  local name="$(basename "$theme_dir")"
  local colors_file="$theme_dir/colors.toml"

  if [[ ! -f "$colors_file" ]]; then
    echo "  SKIP $name (no colors.toml)"
    return
  fi

  # Parse colors.toml into associative array
  declare -A pairs=()
  while IFS='=' read -r key value; do
    key="${key//[\"\' ]/}"
    [[ $key && $key != \#* ]] || continue
    value="${value#*[\"\']}"
    value="${value%%[\"\']*}"
    pairs["$key"]="$value"
  done < "$colors_file"

  # --- Derive terminal palette (ANSI 0-15) from semantic names ---
  # Each slot maps to a semantic variable. Themes can override with term_N.
  local -a term_sources=(
    surface danger success warning accent accent_alt
    info fg_alt muted danger_bright success_bright warning_bright
    accent_bright accent_alt_bright info_bright fg_dim
  )

  for slot in {0..15}; do
    local tkey="term_${slot}"
    if [[ -z "${pairs[$tkey]:-}" ]]; then
      pairs["$tkey"]="${pairs[${term_sources[$slot]}]:-}"
    fi
  done

  # Build sed script from all pairs
  local sed_script
  sed_script=$(mktemp)

  for key in "${!pairs[@]}"; do
    emit_sed_entry "$key" "${pairs[$key]}" "$sed_script"
  done

  # Decoration defaults (applied only if theme didn't set them)
  for pair in "rounding:10" "gaps_in:2" "gaps_out:4" "border_size:2" "blur_size:6" "blur_passes:3" "opacity_active:1.0" "opacity_inactive:1.0" "popup_opacity:0.60" "messenger_opacity:0.85" "browser_opacity:1.0"; do
    local dkey="${pair%%:*}" dval="${pair#*:}"
    if ! grep -q "{{ ${dkey} }}" "$sed_script"; then
      printf 's|{{ %s }}|%s|g\n' "$dkey" "$dval" >> "$sed_script"
    fi
  done

  # Border color defaults: derive from accent/muted if not explicitly set
  if [[ -z "${pairs[border_active]:-}" ]]; then
    local a_hex="${pairs[accent]:-}"
    a_hex="${a_hex#\#}"
    printf 's|{{ border_active }}|rgb(%s)|g\n' "$a_hex" >> "$sed_script"
  fi
  if [[ -z "${pairs[border_inactive]:-}" ]]; then
    local m_hex="${pairs[muted]:-}"
    m_hex="${m_hex#\#}"
    printf 's|{{ border_inactive }}|rgba(%saa)|g\n' "$m_hex" >> "$sed_script"
  fi

  # Autosuggestion default: derive from muted if not explicitly set
  if [[ -z "${pairs[autosuggestion]:-}" ]]; then
    local as_val="${pairs[muted]:-}"
    if [[ -n "$as_val" ]]; then
      emit_sed_entry "autosuggestion" "$as_val" "$sed_script"
    fi
  fi

  # Expand each template into the theme directory
  local count=0
  for tpl in "$TEMPLATES_DIR"/*.tpl; do
    local filename
    filename=$(basename "$tpl" .tpl)
    sed -f "$sed_script" "$tpl" > "$theme_dir/$filename"
    count=$((count + 1))
  done

  rm "$sed_script"
  echo "  OK   $name ($count files generated)"
}

echo "Generating theme configs from templates..."
echo ""

for theme_dir in "$THEMES_DIR"/*/; do
  [[ "$(basename "$theme_dir")" == _* ]] && continue
  generate_theme "$theme_dir"
done

echo ""
echo "Done. All themes now have pre-baked config files."
