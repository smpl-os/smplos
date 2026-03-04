#!/usr/bin/env bash
set -euo pipefail

# notif-center build helper for Arch Linux
# - Installs required system packages
# - Builds release binary
# - Optionally installs to /usr/local/bin

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Redirect cargo output outside the source tree so src/ stays clean.
# PROJECT_ROOT is 3 levels up: notif-center/ -> shared/ -> src/ -> project root
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
export CARGO_TARGET_DIR="$PROJECT_ROOT/build/target"
mkdir -p "$CARGO_TARGET_DIR"

if ! command -v pacman >/dev/null 2>&1; then
  echo "Error: this script is intended for Arch Linux (pacman not found)." >&2
  exit 1
fi

ARCH_PKGS=(
  base-devel
  rust
  cargo
  pkgconf
  cmake
  fontconfig
  freetype2
  libxkbcommon
  wayland
  libglvnd
  mesa
)

RUNTIME_PKGS=(
  dunst
  jq
)

install_missing_pkgs() {
  local label="$1"
  shift
  local -a requested=("$@")
  local -a missing=()

  for pkg in "${requested[@]}"; do
    if ! pacman -Q "$pkg" >/dev/null 2>&1; then
      missing+=("$pkg")
    fi
  done

  if (( ${#missing[@]} == 0 )); then
    echo "==> $label: already satisfied"
    return
  fi

  echo "==> Installing missing $label: ${missing[*]}"
  sudo pacman -S --needed --noconfirm "${missing[@]}"
}

install_missing_pkgs "build dependencies" "${ARCH_PKGS[@]}"

install_missing_pkgs "runtime dependencies" "${RUNTIME_PKGS[@]}"

echo "==> Building notif-center (release)..."
cargo build --release

BIN_PATH="$CARGO_TARGET_DIR/release/notif-center"
if [[ ! -x "$BIN_PATH" ]]; then
  echo "Error: build finished but binary not found at $BIN_PATH" >&2
  exit 1
fi

echo "==> Build complete: $BIN_PATH"

action="${1:-}"
if [[ "$action" == "--install" ]]; then
  echo "==> Installing to /usr/local/bin/notif-center"
  sudo install -Dm755 "$BIN_PATH" /usr/local/bin/notif-center
  echo "Installed: /usr/local/bin/notif-center"
elif [[ "$action" == "--run" ]]; then
  echo "==> Running notif-center"
  exec "$BIN_PATH"
else
  echo "Tip: run './build.sh --install' to install globally, or './build.sh --run' to launch."
fi
