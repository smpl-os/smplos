#!/bin/bash

# smplOS Installer Helpers
# Based on Omarchy helpers

export PADDING_LEFT=2
export PADDING_LEFT_SPACES="  "

# GUM styling for matrix-green theme - ensure selected items have contrast
# Selected items: black text on cyan background (visible against green text)
export GUM_CONFIRM_SELECTED_FOREGROUND="0"   # Black text
export GUM_CONFIRM_SELECTED_BACKGROUND="6"   # Cyan background
export GUM_CONFIRM_UNSELECTED_FOREGROUND="2" # Green text (matches theme)
export GUM_CONFIRM_UNSELECTED_BACKGROUND="0" # Black background
export GUM_CHOOSE_CURSOR_FOREGROUND="0"      # Black text for cursor
export GUM_CHOOSE_SELECTED_FOREGROUND="0"    # Black text when selected
export GUM_CHOOSE_CURSOR_BACKGROUND="6"      # Cyan background for cursor
export GUM_CHOOSE_SELECTED_BACKGROUND="6"    # Cyan background when selected

# Error handling
set -eE
trap 'error_handler $? "$BASH_COMMAND" $LINENO' ERR

error_handler() {
  local exit_code=$1
  local command=$2
  local line_number=$3
  
  echo
  echo "Error: Command '$command' failed with exit code $exit_code at line $line_number"
  echo "Script: ${CURRENT_SCRIPT:-unknown}"
  echo
  
  if [[ -f "$SMPLOS_INSTALL_LOG_FILE" ]]; then
    echo "Last 20 lines of log:"
    tail -20 "$SMPLOS_INSTALL_LOG_FILE"
  fi
}

# Logging
run_logged() {
  local script="$1"
  local script_name=$(basename "$script" .sh)
  
  export CURRENT_SCRIPT="$script_name"
  
  if [[ -n "${SMPLOS_INSTALL_LOG_FILE:-}" ]]; then
    source "$script" >> "$SMPLOS_INSTALL_LOG_FILE" 2>&1
  else
    source "$script"
  fi
  
  unset CURRENT_SCRIPT
}

# Background log output using tail
LOG_PID=""

start_log_output() {
  if [[ -f "$SMPLOS_INSTALL_LOG_FILE" ]]; then
    tail -f "$SMPLOS_INSTALL_LOG_FILE" 2>/dev/null &
    LOG_PID=$!
  fi
}

stop_log_output() {
  if [[ -n "$LOG_PID" ]]; then
    kill $LOG_PID 2>/dev/null || true
    LOG_PID=""
  fi
}

# Display the smplOS logo
show_logo() {
  local version
  version=$(grep '^VERSION_ID=' /etc/os-release 2>/dev/null | head -1 | cut -d'=' -f2 | tr -d '"')
  [[ -z "$version" ]] && version="dev"

  local logo
  logo=$(cat <<EOF
╭──────────╮
│   _____  │
│ / _____/ │
│ \______  │
│ _______/ │
│          │
╰──────────╯ smplOS v${version}  
EOF
  )

  gum style \
    --foreground "#00ff00" \
    --padding "1 $PADDING_LEFT" \
    "$logo"
}

clear_logo() {
  clear
  show_logo
}

# Check if running in chroot
is_chroot() {
  [[ "${SMPLOS_CHROOT_INSTALL:-}" == "1" ]]
}

# Run command with or without chroot prefix
chrootable() {
  if is_chroot; then
    sudo "$@"
  else
    "$@"
  fi
}
