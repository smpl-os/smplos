#!/usr/bin/env bash
set -euo pipefail
#
# fetch-org.sh — Fetch the latest pre-built binaries from EVERY repo in the
# smpl-os GitHub org, automatically. Add a repo to the org that publishes a
# release with binary assets and it gets installed on the next system update —
# no code changes here.
#
# Usage:
#   ./fetch-org.sh            # fetch anything newer than what's cached
#   ./fetch-org.sh --force    # re-fetch everything
#
# Staging output (consumed by smplos-os-update):
#   .cache/org-binaries/bin/          ← executables  → /usr/local/bin/
#   .cache/org-binaries/lib/          ← *.so plugins → /usr/local/lib/smplos/
#   .cache/org-binaries/.versions/    ← per-repo "latest tag" markers
#
# WHY THIS EXISTS
# ───────────────
# smplOS pulls its custom apps/plugins straight from the org's GitHub Releases.
# Each repo owns its own build/CI; smplos just installs whatever they published.
# This replaces per-app hardcoded lists with one convention-based path.
#
# ASSET CONVENTION (per release, uploaded assets only — GitHub's auto-generated
# source tarballs are never touched):
#   *.so                                   → installed to /usr/local/lib/smplos/
#   *-x86_64.tar.gz | *-linux64.tar.gz     → extracted; ELF execs → bin,
#     *.tgz | *.tar.xz | *.tar.bz2 (bundle)  *.so → lib
#   everything else (pkg.tar.zst, rootfs,   → skipped (installed via pacman or
#     *.sha/*.sig, loose version-named ELF)   not meant for /usr/local)

ORG="smpl-os"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

STAGE="$PROJECT_ROOT/.cache/org-binaries"
BIN_STAGE="$STAGE/bin"
LIB_STAGE="$STAGE/lib"
VER_DIR="$STAGE/.versions"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[fetch-org]${NC} $*"; }
warn() { echo -e "${YELLOW}[fetch-org]${NC} $*"; }
die()  { echo -e "${RED}[fetch-org]${NC} $*" >&2; exit 1; }

FORCE=false
for arg in "$@"; do
    [[ "$arg" == "--force" ]] && FORCE=true
done

command -v curl >/dev/null 2>&1 || die "curl is required"
mkdir -p "$BIN_STAGE" "$LIB_STAGE" "$VER_DIR"

api() { curl -fsSL -H "Accept: application/vnd.github+json" "$@"; }

# ── Is this asset ELF? ────────────────────────────────────────────────────────
is_elf() { head -c4 "$1" 2>/dev/null | grep -q $'\x7fELF'; }

# ── Classify + stage a single downloaded file under its real asset name ───────
stage_file() {
    local f="$1" name="$2"
    case "$name" in
        *.so|*.so.[0-9]*)
            install -Dm755 "$f" "$LIB_STAGE/$name"
            log "  lib/$name" ;;
        *)
            if is_elf "$f"; then
                install -Dm755 "$f" "$BIN_STAGE/$name"
                log "  bin/$name"
            fi ;;
    esac
}

# ── Extract a binary bundle and stage its ELF contents ────────────────────────
stage_bundle() {
    local archive="$1" tmp
    tmp="$(mktemp -d)"
    if ! tar -xf "$archive" -C "$tmp" 2>/dev/null; then
        warn "  could not extract $(basename "$archive")"
        rm -rf "$tmp"; return
    fi
    # Only copy out ELF regular files by basename (paths stripped → no traversal)
    local f name
    while IFS= read -r -d '' f; do
        name="$(basename "$f")"
        case "$name" in
            *.so|*.so.[0-9]*) install -Dm755 "$f" "$LIB_STAGE/$name"; log "  lib/$name" ;;
            *) if is_elf "$f"; then install -Dm755 "$f" "$BIN_STAGE/$name"; log "  bin/$name"; fi ;;
        esac
    done < <(find "$tmp" -type f -print0)
    rm -rf "$tmp"
}

# ── Process one asset URL ─────────────────────────────────────────────────────
handle_asset() {
    local url="$1" name tmp
    name="$(basename "$url")"
    case "$name" in
        # Skip: pacman packages, rootfs images, checksums/signatures
        *.pkg.tar.*|*-rootfs.tar.*|*.sha|*.sha256|*.sha512|*.sig|*.asc|*.md5)
            return ;;
        *.so|*.so.[0-9]*)
            ;;  # loose shared object → download + stage
        *-x86_64.tar.gz|*-linux64.tar.gz|*-linux-x86_64.tar.gz|*.tgz|*.tar.xz|*.tar.bz2)
            ;;  # binary bundle → download + extract
        *)
            return ;;  # loose version-named binaries etc. → skip (ambiguous)
    esac

    tmp="$(mktemp)"
    if ! curl -fsSL --connect-timeout 15 --max-time 300 -o "$tmp" "$url"; then
        warn "  download failed: $name"; rm -f "$tmp"; return
    fi
    case "$name" in
        *.so|*.so.[0-9]*) stage_file "$tmp" "$name" ;;
        *)                stage_bundle "$tmp" ;;
    esac
    rm -f "$tmp"
}

# ── List org repositories (public) ────────────────────────────────────────────
log "Enumerating $ORG repositories..."
REPOS="$(api "https://api.github.com/orgs/$ORG/repos?per_page=100&type=public" \
    | grep '"full_name"' | sed -E 's/.*"full_name": *"'"$ORG"'\/([^"]+)".*/\1/')"
[[ -n "$REPOS" ]] || die "Could not list repositories for org $ORG"

n_repos=0; n_updated=0
while IFS= read -r repo; do
    [[ -n "$repo" ]] || continue
    ((n_repos++)) || true

    rel="$(api "https://api.github.com/repos/$ORG/$repo/releases/latest" 2>/dev/null)" || rel=""
    [[ -n "$rel" ]] || continue

    tag="$(grep -m1 '"tag_name"' <<< "$rel" | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')"
    [[ -n "$tag" ]] || continue

    marker="$VER_DIR/$repo"
    if [[ "$FORCE" == "false" && -f "$marker" && "$(cat "$marker")" == "$tag" ]]; then
        continue
    fi

    urls="$(grep '"browser_download_url"' <<< "$rel" \
        | sed -E 's/.*"browser_download_url": *"([^"]+)".*/\1/' || true)"
    [[ -n "$urls" ]] || { echo "$tag" > "$marker"; continue; }

    log "$repo $tag"
    while IFS= read -r url; do
        [[ -n "$url" ]] && handle_asset "$url"
    done <<< "$urls"

    echo "$tag" > "$marker"
    ((n_updated++)) || true
done <<< "$REPOS"

log "Scanned $n_repos repos; $n_updated with new binaries staged."
