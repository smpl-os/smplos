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

smplos_app_binaries_valid() {
    local dir="$1" app
    for app in "${SMPLOS_APP_BINS[@]}"; do
        if ! smplos_app_is_elf "$dir/$app"; then
            echo "smpl-apps: missing or invalid binary: $dir/$app" >&2
            return 1
        fi
    done
}

smplos_calendar_service_valid() {
    [[ -f "$1" && ! -L "$1" ]] &&
        grep -qxF 'ExecStart=/usr/local/bin/smpl-calendar-alertd --foreground' "$1" &&
        grep -qxF 'WantedBy=default.target' "$1"
}

smplos_app_bundle_valid() {
    smplos_app_binaries_valid "$1" || return 1
    if ! smplos_calendar_service_valid "$1/smpl-calendar-alertd.service"; then
        echo "smpl-apps: missing or incompatible calendar reminder service: $1" >&2
        return 1
    fi
}

# Install for the desktop user, without starting a new daemon or changing a
# user's existing enablement, mask, custom unit, or live database.
smplos_install_calendar_service() {
    local source="$1" unit=smpl-calendar-alertd.service
    smplos_calendar_service_valid "$source" || return 1
    if [[ $EUID -eq 0 ]]; then
        local uid="${SMPLOS_INVOKER_UID:-${PKEXEC_UID:-${SUDO_UID:-}}}" entry user home
        if [[ -z "$uid" || "$uid" == 0 ]]; then
            echo "smpl-apps: calendar service installation requires a desktop user" >&2
            return 1
        fi
        entry=$(getent passwd "$uid") || return 1
        user=$(cut -d: -f1 <<< "$entry")
        home=$(cut -d: -f6 <<< "$entry")
        runuser -u "$user" -- env HOME="$home" XDG_CONFIG_HOME="$home/.config" \
            XDG_STATE_HOME="$home/.local/state" bash -c \
            "$(declare -f smplos_calendar_service_valid smplos_install_calendar_service)
temporary=\$(mktemp) || exit 1
trap 'rm -f -- \"\$temporary\"' EXIT
cat > \"\$temporary\" || exit 1
smplos_install_calendar_service \"\$temporary\"" < "$source"
        return $?
    fi
    local dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    local state="${XDG_STATE_HOME:-$HOME/.local/state}/smplos/calendar-service"
    local destination="$dir/$unit" previous="$state/last-installed.service"
    local fresh=false staged existing
    if [[ ! -e "$destination" && ! -L "$destination" ]]; then
        for existing in \
            "${XDG_RUNTIME_DIR:-/run/user/$UID}/systemd/user/$unit" \
            "/etc/systemd/user/$unit" "/run/systemd/user/$unit" \
            "/usr/local/lib/systemd/user/$unit" "/usr/lib/systemd/user/$unit"; do
            if [[ -e "$existing" || -L "$existing" ]]; then
                echo "smpl-apps: preserving existing calendar service or mask: $existing" >&2
                return 0
            fi
        done
    fi
    if [[ -e "$destination" || -L "$destination" ]]; then
        if [[ -L "$destination" ]] ||
            { ! cmp -s "$source" "$destination" && ! cmp -s "$previous" "$destination"; }; then
            echo "smpl-apps: preserving custom or masked calendar service: $destination" >&2
            return 0
        fi
    elif [[ -e "$previous" ]]; then
        echo "smpl-apps: preserving removed calendar service: $destination" >&2
        return 0
    else
        fresh=true
    fi
    mkdir -p "$dir" "$state" || return 1
    staged=$(mktemp "$dir/.calendar-service.XXXXXX") || return 1
    if ! { install -m644 "$source" "$staged" && mv -f -- "$staged" "$destination"; }; then
        rm -f -- "$staged"
        return 1
    fi
    install -m644 "$source" "$previous" || return 1
    if $fresh; then
        mkdir -p "$dir/default.target.wants" || return 1
        if [[ ! -e "$dir/default.target.wants/$unit" && ! -L "$dir/default.target.wants/$unit" ]]; then
            ln -s "../$unit" "$dir/default.target.wants/$unit" || return 1
        fi
    fi
    echo "smpl-apps: calendar reminder service installed; log out/in to load it (no daemon restarted)"
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
    install -m644 "$unpacked/smpl-calendar-alertd.service" \
        "$destination/smpl-calendar-alertd.service" || return 1
)

smplos_download_app_bundle() (
    local url="$1" destination="$2" archive
    archive=$(mktemp) || return 1
    trap 'rm -f -- "$archive"' EXIT
    curl -fSL --connect-timeout 30 --max-time 300 --retry 3 \
        -o "$archive" "$url" || return 1
    smplos_stage_app_bundle "$archive" "$destination"
)
