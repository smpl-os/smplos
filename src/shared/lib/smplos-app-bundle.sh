# shellcheck shell=bash
# Shared smpl-apps release contract for OTA and ISO consumers.
SMPLOS_APP_BINS=(
    start-menu notif-center settings app-center webapp-center
    sync-center-daemon sync-center-gui smpl-calendar smpl-calendar-alertd
    smpl-hints smpl-hintsd
)

smplos_install_app_binary() {
    local source="$1" destination="$2" staged
    staged=$(sudo mktemp "${destination}.XXXXXX") || return 1
    if sudo install -m755 "$source" "$staged" &&
        sudo mv -f -- "$staged" "$destination" &&
        cmp -s "$source" "$destination"; then
        return 0
    fi
    sudo rm -f -- "$staged"
    echo "smpl-apps: failed to install $destination; retry Update OS" >&2
    return 1
}

smplos_app_is_elf() {
    [[ -f "$1" && ! -L "$1" ]] &&
        [[ "$(head -c 4 -- "$1")" == $'\x7fELF' ]]
}

smplos_app_bundle_valid() {
    local dir="$1" app
    for app in "${SMPLOS_APP_BINS[@]}"; do
        if ! smplos_app_is_elf "$dir/$app"; then
            echo "smpl-apps: missing or invalid binary: $dir/$app" >&2
            return 1
        fi
    done
}

# Validate a fresh extraction, never a mixture of old and new cached files.
smplos_stage_app_bundle() (
    local archive="$1" destination="$2" unpacked file
    unpacked=$(mktemp -d) || return 1
    trap 'rm -rf -- "$unpacked"' EXIT
    tar -xzf "$archive" --no-same-owner --no-same-permissions -C "$unpacked" || return 1
    smplos_app_bundle_valid "$unpacked" || return 1
    mkdir -p "$destination" || return 1
    for file in "$unpacked"/*; do
        smplos_app_is_elf "$file" || continue
        install -m755 "$file" "$destination/${file##*/}" || return 1
    done
)

smplos_download_app_bundle() (
    local url="$1" destination="$2" archive
    archive=$(mktemp) || return 1
    trap 'rm -f -- "$archive"' EXIT
    curl -fSL --connect-timeout 30 --max-time 300 --retry 3 \
        -o "$archive" "$url" || return 1
    smplos_stage_app_bundle "$archive" "$destination"
)
