#!/usr/bin/env bash
set -euo pipefail
#
# fetch-apps.sh — Fetch the latest pre-built smpl-apps binaries from GitHub.
#
# Usage:
#   ./fetch-apps.sh              # fetch the latest smpl-apps release
#   ./fetch-apps.sh --force      # re-fetch even if already current
#
# Outputs binaries to: .cache/app-binaries/
# This is the same output path as the old container build so the ISO builder
# (build.sh) and CI pipelines work without modification.
#
# WHY THIS EXISTS
# ───────────────
# smpl-apps is a fully independent repo with its own CI that builds and
# publishes stripped, tested binaries to GitHub Releases on every tag.
# There is no reason to embed the source here (as a submodule or otherwise) —
# doing so creates two copies that inevitably drift apart and cause bugs like
# settings/src/main.rs being fixed in one copy but not the other.
#
# Integration contract: smplos always uses whatever smpl-apps just released.
# smpl-apps owns the build. smplos owns the integration.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

REPO="smpl-os/smpl-apps"
BIN_OUTPUT="$PROJECT_ROOT/.cache/app-binaries"
MARKER="$BIN_OUTPUT/smpl-apps.fetched-version"

EXPECTED_BINS=(
    start-menu notif-center settings app-center webapp-center
    sync-center-gui sync-center-daemon smpl-calendar smpl-calendar-alertd
)

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[fetch-apps]${NC} $*"; }
warn() { echo -e "${YELLOW}[fetch-apps]${NC} $*"; }
die()  { echo -e "${RED}[fetch-apps]${NC} $*" >&2; exit 1; }

FORCE=false
for arg in "$@"; do
    [[ "$arg" == "--force" ]] && FORCE=true
done

mkdir -p "$BIN_OUTPUT"

# ── Resolve latest release version ───────────────────────────────────────────
log "Checking latest smpl-apps release..."
if command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
    LATEST=$(gh release view --repo "$REPO" --json tagName -q .tagName 2>/dev/null)
else
    LATEST=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
        | grep '"tag_name"' | head -1 | grep -oP 'v[\d.]+')
fi
[[ -n "$LATEST" ]] || die "Could not determine latest release from $REPO"

# ── Skip if already up to date ────────────────────────────────────────────────
if [[ "$FORCE" == "false" && -f "$MARKER" && "$(cat "$MARKER")" == "$LATEST" ]]; then
    all_present=true
    for bin in "${EXPECTED_BINS[@]}"; do
        [[ -f "$BIN_OUTPUT/$bin" ]] || { all_present=false; break; }
    done
    if [[ "$all_present" == "true" ]]; then
        log "Already at latest ($LATEST) — nothing to do"
        exit 0
    fi
    warn "Marker says $LATEST but some binaries are missing — re-fetching"
fi

# ── Download ──────────────────────────────────────────────────────────────────
VERSION_BARE="${LATEST#v}"
TARBALL="smpl-apps-${VERSION_BARE}-x86_64.tar.gz"
DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${LATEST}/${TARBALL}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log "Downloading smpl-apps $LATEST..."
if command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
    gh release download "$LATEST" --repo "$REPO" \
        --pattern "$TARBALL" --dir "$TMP" --clobber
else
    curl -fsSL --progress-bar -o "$TMP/$TARBALL" "$DOWNLOAD_URL" \
        || die "Download failed: $DOWNLOAD_URL"
fi

# ── Extract ───────────────────────────────────────────────────────────────────
log "Extracting to $BIN_OUTPUT/"
tar -xzf "$TMP/$TARBALL" -C "$BIN_OUTPUT/"

# Ensure all expected binaries are present and executable
missing=()
for bin in "${EXPECTED_BINS[@]}"; do
    if [[ -f "$BIN_OUTPUT/$bin" ]]; then
        chmod +x "$BIN_OUTPUT/$bin"
    else
        missing+=("$bin")
    fi
done
[[ ${#missing[@]} -gt 0 ]] && warn "Missing from release tarball: ${missing[*]}"

# ── Record installed version ──────────────────────────────────────────────────
echo "$LATEST" > "$MARKER"

log "smpl-apps $LATEST installed:"
ls -lh "$BIN_OUTPUT/"
