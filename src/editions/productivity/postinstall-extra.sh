#!/usr/bin/env bash
# smplOS Productivity Edition -- extra post-install hooks
# Runs after the main postinstall.sh

# SiYuan — pre-create the theme directory so the smplOS theme is available
# on first launch. theme-set will keep it updated on every theme switch.
_SIYUAN_WS="$HOME/SiYuan"
_SIYUAN_THEME_DIR="$_SIYUAN_WS/conf/appearance/themes/smplos"
mkdir -p "$_SIYUAN_THEME_DIR"

cat > "$_SIYUAN_THEME_DIR/theme.json" << 'EOJSON'
{
  "name": "smplos",
  "author": "smplOS",
  "url": "",
  "version": "1.0.0",
  "minAppVersion": "2.0.0",
  "displayName": {"default": "smplOS", "en_US": "smplOS"},
  "description": {"default": "Dynamic theme controlled by smplOS theme switcher"},
  "readme": {"default": ""},
  "modes": ["light", "dark"]
}
EOJSON

# Deploy initial theme CSS from the current smplOS theme
# (theme-set has already run by this point in the install flow)
if [[ -f "$HOME/.config/smplos/current/theme/siyuan-theme.css" ]]; then
  cp "$HOME/.config/smplos/current/theme/siyuan-theme.css" "$_SIYUAN_THEME_DIR/theme.css"
fi
