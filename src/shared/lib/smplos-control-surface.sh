# shellcheck shell=bash
# Resolve one published input-device release for both OTA and offline ISO builds.
smplos_control_surface_prepare() {
    local recipe="$1" metadata="$2" destination="$3"
    mkdir -p "$destination" && cp -a "$recipe/." "$destination/" || return 1
    python3 - "$metadata" "$destination/PKGBUILD" <<'PY'
import json
from pathlib import Path
import re
import sys

try:
    release = json.loads(Path(sys.argv[1]).read_text())
    if not isinstance(release, dict):
        raise ValueError("release metadata must be an object")
    tag = release["tag_name"]
    if (release.get("draft") or release.get("prerelease") or not isinstance(tag, str)
            or not re.fullmatch(r"v[0-9]+(?:\.[0-9]+)+", tag)):
        raise ValueError("expected a stable numeric release tag")
    version = tag[1:]
    name = f"control-surface-{version}-x86_64.tar.gz"
    if not isinstance(release["assets"], list) or not all(isinstance(asset, dict) for asset in release["assets"]):
        raise ValueError("invalid release asset inventory")
    assets = [asset for asset in release["assets"] if asset.get("name") == name]
    if len(assets) != 1:
        raise ValueError(f"expected exactly one {name} asset")
    asset = assets[0]
    expected_url = f"https://github.com/smpl-os/smpl-apps/releases/download/{tag}/{name}"
    if asset.get("browser_download_url") != expected_url:
        raise ValueError("unexpected control-surface download URL")
    digest = asset.get("digest", "")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("published control-surface asset has no valid SHA256 digest")
    path = Path(sys.argv[2])
    recipe = path.read_text()
    for pattern, replacement in (
        (r"^pkgver=.*$", f"pkgver={version}"),
        (r"^sha256sums=.*$", f"sha256sums=('{digest[7:]}')"),
    ):
        recipe, count = re.subn(pattern, replacement, recipe, flags=re.MULTILINE)
        if count != 1:
            raise ValueError(f"invalid package recipe: {pattern}")
    path.write_text(recipe)
except (OSError, ValueError, KeyError, TypeError) as error:
    sys.exit(f"control-surface: cannot resolve published release: {error}")
PY
}

smplos_control_surface_current() {
    local target="$1" have comparison daemon
    have=$(smplos_pkg_version control-surface)
    [[ -n "$have" ]] || return 1
    comparison=$(vercmp "$have" "$target") || return 2
    if [[ $comparison -ge 0 ]] && pacman -Qkk control-surface >/dev/null 2>&1; then
        local intact=1
        for daemon in "${SMPLOS_KEYPAD_DAEMON:-/usr/bin/control-surfaced}" \
                      "${SMPLOS_MOUSE_DAEMON:-/usr/bin/mouse-remapperd}"; do
            if [[ ! -f "$daemon" || -L "$daemon" || ! -x "$daemon" ]] ||
                [[ "$(pacman -Qqo "$daemon" 2>/dev/null)" != control-surface ]]; then
                intact=0
            fi
        done
        [[ $intact -eq 1 ]] && return 0
    fi
    if [[ $comparison -gt 0 ]]; then
        echo "  ERROR: control-surface $have needs repair, but target $target is older; refusing downgrade" >&2
        return 2
    fi
    return 1
}

smplos_control_surface_install() {
    local recipe="$1" target mouse_daemon="${SMPLOS_MOUSE_DAEMON:-/usr/bin/mouse-remapperd}"
    local install_flags=()
    target=$(smplos_pkgbuild_version "$recipe") || return 1
    if [[ -e "$mouse_daemon" || -L "$mouse_daemon" ]] &&
        ! pacman -Qqo "$mouse_daemon" >/dev/null 2>&1; then
        if [[ ! -f "$mouse_daemon" || -L "$mouse_daemon" || ! -x "$mouse_daemon" ]] ||
            ! smplos_mouse_check_runtime "$mouse_daemon"; then
            echo "  ERROR: unowned $mouse_daemon is not a recognized mouse remapper; left untouched. Resolve the file conflict before retrying Update OS." >&2
            return 1
        fi
        install_flags=(--overwrite "${mouse_daemon#/}")
        echo "  Adopting standalone $mouse_daemon into control-surface; saved mappings are unchanged"
    fi
    smplos_pkgbuild_install "$recipe" "${install_flags[@]}" || return 1
    if [[ "$(smplos_pkg_version control-surface)" != "$target" ]] ||
        ! smplos_control_surface_current "$target"; then
        echo "  ERROR: control-surface installation did not reach intact package $target; retry Update OS" >&2
        return 1
    fi
    smplos_keypad_check_runtime "${SMPLOS_KEYPAD_DAEMON:-/usr/bin/control-surfaced}" &&
        smplos_mouse_check_runtime "$mouse_daemon" || {
            echo "  ERROR: installed input-device release cannot run; retry after a compatible release/runtime is available" >&2
            return 1
        }
}
