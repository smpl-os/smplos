# shellcheck shell=bash
# Verify release metadata and payload before pacman or the ISO cache consumes it.
smplos_nemo_package_valid() {
    local archive="$1" version="${2#v}" metadata files required
    [[ "$version" =~ ^[0-9]+(\.[0-9]+)*$ ]] || return 1
    metadata=$(tar -xOf "$archive" .PKGINFO) || return 1
    grep -qx 'pkgname = nemo-smpl' <<< "$metadata" || return 1
    grep -qE "^pkgver = ${version//./\\.}-[0-9]+$" <<< "$metadata" || return 1
    files=$(tar -tf "$archive") || return 1
    for required in usr/bin/nemo usr/libexec/nemo-document-renderer usr/libexec/nemo-archive-create-worker; do
        if ! grep -qx "$required" <<< "$files"; then
            echo "nemo-smpl: release package missing $required" >&2
            return 1
        fi
    done
}

smplos_verify_release_checksum() {
    local archive="$1" asset_url="$2" release_json="$3" url sums expected actual
    url=$(grep -oP '"browser_download_url"\s*:\s*"\K[^"]*/SHA256SUMS-x86_64(?=")' <<< "$release_json") || true
    if [[ -z "$url" ]]; then
        echo "nemo-smpl: older release has no SHA256SUMS-x86_64; validating package metadata and payload only" >&2
        return 0
    fi
    sums=$(curl -fsSL --connect-timeout 15 --max-time 30 "$url") || return 1
    expected=$(awk -v name="${asset_url##*/}" '$2 == name { print $1 }' <<< "$sums")
    [[ "$expected" =~ ^[[:xdigit:]]{64}$ ]] || {
        echo "nemo-smpl: missing/duplicate/invalid checksum for ${asset_url##*/}" >&2
        return 1
    }
    actual=$(sha256sum "$archive") || return 1
    [[ "${actual%% *}" == "$expected" ]] || {
        echo "nemo-smpl: checksum mismatch for ${asset_url##*/}" >&2
        return 1
    }
}

smplos_package_current() {
    local package="$1" release="${2#v}" installed comparison
    installed=$(pacman -Q "$package" 2>/dev/null) || return 1
    installed="${installed#* }"
    comparison=$(vercmp "$installed" "$release-1") || return 2
    if [[ $comparison -ge 0 ]] && pacman -Qk "$package" >/dev/null 2>&1; then
        return 0
    fi
    if [[ $comparison -gt 0 ]]; then
        echo "$package: newer installed $installed has missing files; repair that version, refusing downgrade to $release" >&2
        return 2
    fi
    return 1
}
