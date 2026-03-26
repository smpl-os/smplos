#!/bin/bash
# Migration: Configure micro with smplOS theme, Windows-like shortcuts, autocomplete
# Applies: colorscheme from current theme, quality-of-life settings, keyboard shortcuts

set -euo pipefail

MICRO_CONFIG="$HOME/.config/micro"
MICRO_COLORSCHEMES="$MICRO_CONFIG/colorschemes"
COLORS_TOML="$HOME/.config/smplos/current/theme/colors.toml"
MICRO_THEME_SRC="$HOME/.config/smplos/current/theme/micro.theme"

mkdir -p "$MICRO_CONFIG" "$MICRO_COLORSCHEMES"

n_changes=0

# ── settings.json ────────────────────────────────────────────────────────────
if ! grep -q '"colorscheme"' "$MICRO_CONFIG/settings.json" 2>/dev/null; then
    cat > "$MICRO_CONFIG/settings.json" << 'EOF'
{
    "colorscheme": "smplos",
    "truecolor": "on",
    "autoclose": true,
    "autocomplete": true,
    "autoindent": true,
    "tabsize": 4,
    "tabstospaces": false,
    "softwrap": true,
    "syntax": true,
    "ruler": true,
    "savecursor": true,
    "saveundo": true,
    "statusline": true,
    "diffgutter": true,
    "scrollmargin": 5,
    "mouse": true,
    "clipboard": "external"
}
EOF
    echo "  Wrote micro settings.json"
    ((n_changes++)) || true
fi

# ── bindings.json — Windows-like shortcuts ───────────────────────────────────
if [[ "$(cat "$MICRO_CONFIG/bindings.json" 2>/dev/null | tr -d '[:space:]')" == "{}" ]] \
    || ! grep -q '"CtrlBackspace"' "$MICRO_CONFIG/bindings.json" 2>/dev/null; then
    cat > "$MICRO_CONFIG/bindings.json" << 'EOF'
{
    "CtrlLeft":       "WordLeft",
    "CtrlRight":      "WordRight",
    "CtrlBackspace":  "DeleteWordLeft",
    "CtrlDelete":     "DeleteWordRight",
    "ShiftUp":        "SelectUp",
    "ShiftDown":      "SelectDown",
    "ShiftEnd":       "SelectToEndOfLine",
    "ShiftHome":      "SelectToStartOfLine",
    "CtrlShiftLeft":  "SelectWordLeft",
    "CtrlShiftRight": "SelectWordRight",
    "CtrlShiftZ":     "Redo",
    "CtrlY":          "Redo"
}
EOF
    echo "  Wrote micro bindings.json"
    ((n_changes++)) || true
fi

# ── Colorscheme — from pre-baked micro.theme or inline from colors.toml ──────

toml_get() {
    local file="$1" key="$2"
    grep -E "^${key}[[:space:]]*=" "$file" 2>/dev/null | head -1 \
        | sed 's/.*"\(#[^"]*\)".*/\1/'
}

deploy_colorscheme() {
    local colors_file="$1"
    local bg fg bg_light accent accent_alt fg_alt muted sel_bg sel_fg
    local danger success warning info accent_bright

    bg=$(toml_get "$colors_file" "background")
    fg=$(toml_get "$colors_file" "foreground")
    bg_light=$(toml_get "$colors_file" "bg_light")
    accent=$(toml_get "$colors_file" "accent")
    accent_alt=$(toml_get "$colors_file" "accent_alt")
    accent_bright=$(toml_get "$colors_file" "accent_bright")
    fg_alt=$(toml_get "$colors_file" "fg_alt")
    muted=$(toml_get "$colors_file" "muted")
    sel_bg=$(toml_get "$colors_file" "selection_background")
    sel_fg=$(toml_get "$colors_file" "selection_foreground")
    danger=$(toml_get "$colors_file" "danger")
    success=$(toml_get "$colors_file" "success")
    warning=$(toml_get "$colors_file" "warning")
    info=$(toml_get "$colors_file" "info")

    # Fallback for optional fields
    [[ -z "$accent_bright" ]] && accent_bright="$accent"
    [[ -z "$sel_bg" ]]        && sel_bg="$accent"
    [[ -z "$sel_fg" ]]        && sel_fg="$bg"

    cat > "$MICRO_COLORSCHEMES/smplos.micro" << EOF
# smplOS micro colorscheme — generated from $(cat "$HOME/.config/smplos/current/theme.name" 2>/dev/null || echo "active theme")

# ── Base ────────────────────────────────────────────────────────────────────
color-link default "${fg},${bg}"
color-link background "${bg},${bg}"

# ── UI chrome ──────────────────────────────────────────────────────────────
color-link line-number "${fg_alt},${bg}"
color-link current-line-number "${accent},${bg}"
color-link cursor-line ",${bg_light}"
color-link colorcolumn ",${bg_light}"
color-link statusline "${bg},${accent}"
color-link tabbar "${fg_alt},${bg_light}"
color-link indent-char "${muted},"
color-link scrollbar "${muted},"

# ── Selection ──────────────────────────────────────────────────────────────
color-link selection "${sel_fg},${sel_bg}"

# ── Gutter / diff ──────────────────────────────────────────────────────────
color-link gutter-error "${danger},"
color-link gutter-warning "${warning},"
color-link diff-added "${success},"
color-link diff-modified "${warning},"
color-link diff-deleted "${danger},"

# ── Syntax ─────────────────────────────────────────────────────────────────
color-link comment "${fg_alt}"
color-link todo "${warning},bold"

color-link keyword "${danger}"
color-link keyword.control "${accent_alt}"
color-link keyword.operator "${fg}"

color-link type "${success}"
color-link type.keyword "${success}"

color-link constant "${accent_bright}"
color-link constant.string "${success}"
color-link constant.number "${warning}"
color-link constant.bool "${accent_alt}"
color-link constant.character "${success}"

color-link identifier "${accent}"
color-link function "${accent}"

color-link statement "${danger}"
color-link preproc "${accent}"
color-link special "${warning}"
color-link underlined "${info}"
color-link error "${danger},bold"
EOF
}

# Prefer the pre-baked micro.theme; fall back to generating from colors.toml
if [[ -f "$MICRO_THEME_SRC" ]]; then
    cp "$MICRO_THEME_SRC" "$MICRO_COLORSCHEMES/smplos.micro"
    echo "  Deployed colorscheme from current theme"
    ((n_changes++)) || true
elif [[ -f "$COLORS_TOML" ]]; then
    deploy_colorscheme "$COLORS_TOML"
    echo "  Generated colorscheme from colors.toml"
    ((n_changes++)) || true
else
    echo "  WARNING: No theme colors found — colorscheme not deployed"
    echo "  Run 'theme-set <your-theme>' once to apply the colorscheme"
fi

if [[ $n_changes -eq 0 ]]; then
    echo "  Already configured, nothing to do"
else
    echo "  Applied $n_changes change(s)"
fi
