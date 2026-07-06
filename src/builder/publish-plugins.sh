#!/usr/bin/env bash
set -euo pipefail
#
# publish-plugins.sh — Publish the ABI-correct compositor plugin(s) built by the
# ISO builder as GitHub Release assets, so already-running machines pick them up
# on their next full `smplos-update`.
#
# WHY
# ───
# Hyprland plugins are ABI-locked to the exact hyprland they were built against.
# build.sh compiles them inside the ISO container against the *pinned* hyprland
# and exports the resulting *.so to  release/plugins/  (host-visible). This
# script uploads those exact binaries to the plugin's own `hyprtasking` repo
# release — which fetch-org.sh already scans for *.so assets — so no smplOS
# update code needs to change. The plugin lands in /usr/local/lib/smplos/
# via the existing critical-bundle → install_compositor_plugins path.
#
# AUTH
# ────
# Uses the `gh` CLI's own stored credentials (run `gh auth login` once). No token
# is read from the environment.
#
# USAGE
#   ./publish-plugins.sh                     # publish release/plugins/*.so
#   ./publish-plugins.sh --dir <path>        # publish *.so from a custom dir
#   ./publish-plugins.sh --repo owner/name   # override target repo
#   ./publish-plugins.sh --tag <tag>         # override release tag
#   ./publish-plugins.sh --dry-run           # show what would happen, do nothing

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

REPO="smpl-os/hyprtasking"
TAG="smplos-build"
PLUGINS_DIR="$PROJECT_ROOT/release/plugins"
DRY_RUN=false

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[publish-plugins]${NC} $*"; }
warn() { echo -e "${YELLOW}[publish-plugins]${NC} $*"; }
die()  { echo -e "${RED}[publish-plugins]${NC} $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir)     PLUGINS_DIR="$2"; shift 2 ;;
        --repo)    REPO="$2"; shift 2 ;;
        --tag)     TAG="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Unknown option: $1 (see --help)" ;;
    esac
done

command -v gh >/dev/null 2>&1 || die "gh (GitHub CLI) is required. Install it and run: gh auth login"
gh auth status >/dev/null 2>&1 || die "gh is not authenticated. Run: gh auth login"

[[ -d "$PLUGINS_DIR" ]] || die "Plugins dir not found: $PLUGINS_DIR (build an ISO first, or pass --dir)"

# Collect the .so assets to publish.
shopt -s nullglob
assets=("$PLUGINS_DIR"/*.so)
shopt -u nullglob
[[ ${#assets[@]} -gt 0 ]] || die "No *.so files in $PLUGINS_DIR"

# ABI provenance (which hyprland these were built against), recorded by build.sh.
hl_ver="unknown"
[[ -f "$PLUGINS_DIR/HYPRLAND_VERSION" ]] && hl_ver="$(tr -d '[:space:]' < "$PLUGINS_DIR/HYPRLAND_VERSION")"

local_title="Compositor plugins (hyprland $hl_ver)"
notes="Prebuilt Hyprland compositor plugins for smplOS, ABI-matched to hyprland \`$hl_ver\`.

Installed to \`/usr/local/lib/smplos/\` on the fleet by the critical-bundle step
of \`smplos-update\` (via \`fetch-org.sh --plugins-only\`). These binaries are the
exact ones the matching ISO ships, so they load cleanly on the pinned hyprland.

Assets:
$(printf '  - %s\n' "${assets[@]##*/}")"

log "Target : $REPO  (tag: $TAG)"
log "Source : $PLUGINS_DIR"
log "ABI    : hyprland $hl_ver"
log "Assets : ${assets[*]##*/}"

if [[ "$DRY_RUN" == "true" ]]; then
    warn "Dry run — no release created or assets uploaded."
    exit 0
fi

# Ensure the release exists (create it if missing), then upload/refresh assets.
if gh release view "$TAG" -R "$REPO" >/dev/null 2>&1; then
    log "Updating existing release $TAG"
    gh release edit "$TAG" -R "$REPO" --title "$local_title" --notes "$notes" --latest >/dev/null
else
    log "Creating release $TAG"
    gh release create "$TAG" -R "$REPO" --title "$local_title" --notes "$notes" --latest >/dev/null
fi

# --clobber overwrites same-named assets so re-publishing a rebuilt .so works.
gh release upload "$TAG" "${assets[@]}" -R "$REPO" --clobber >/dev/null
[[ -f "$PLUGINS_DIR/HYPRLAND_VERSION" ]] \
    && gh release upload "$TAG" "$PLUGINS_DIR/HYPRLAND_VERSION" -R "$REPO" --clobber >/dev/null || true

log "Published ${#assets[@]} plugin asset(s) to $REPO ($TAG)."
log "Fleet installs them on the next full 'smplos-update'."
