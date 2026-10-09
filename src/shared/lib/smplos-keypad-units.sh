# shellcheck shell=bash
# Canonical keypad units for OS updates, live ISO users and installed users.

smplos_keypad_check_runtime() {
    local daemon="$1" home rc
    home=$(mktemp -d "${TMPDIR:-/tmp}/smplos-keypad-runtime.XXXXXX") || return 1
    if env HOME="$home" XDG_CONFIG_HOME="$home/config" XDG_STATE_HOME="$home/state" \
        XDG_CACHE_HOME="$home/cache" "$daemon" features --json >/dev/null; then
        rc=0
    else
        rc=1
    fi
    # The read-only features command should leave its isolated home empty.
    rmdir "$home" || return 1
    return "$rc"
}

smplos_keypad_known_unit() {
    local digest
    [[ -f "$1" && ! -L "$1" ]] || return 1
    digest=$(sha256sum "$1") || return 1
    case "${1##*/}:${digest%% *}" in
        # Published stock unit and the unmodified live-install unit.
        control-surface.service:7d62b1a499c372362e1941dfc687884f67c0e1bf828743db3bfc22346dbbb495|\
        control-surface.service:ea6f35d910bc9b67f2d3601a27d08910693a8029e09891d879036638f1dc86f9) return 0 ;;
        # Original coldplug helper and its RemainAfterExit repair.
        smplos-keypad-login.service:1dad7fdb11158b3d732695a92d84ae4a3b50333c811b61840104e685ae6ebeff|\
        smplos-keypad-login.service:b8d149479eebfe132679ef2939d921ba2e1522e250272e0f297ddca0e511a8ed) return 0 ;;
    esac
    return 1
}

smplos_keypad_backup() {
    local file="$1" state="$2" backup
    mkdir -p "$state"
    backup=$(mktemp -d "$state/backup.XXXXXX") || return 1
    cp -a "$file" "$backup/preimage" || return 1
    if [[ -L "$file" ]]; then
        [[ "$(readlink "$file")" == "$(readlink "$backup/preimage")" ]] || return 1
    else
        cmp -s "$file" "$backup/preimage" || return 1
    fi
    printf '%s\n' "$file" > "$backup/path"
    echo "  Backed up $file to $backup"
}

smplos_keypad_drop_links() {
    local dir="$1" name="$2" state="$3" link
    for link in "$dir"/*.wants/"$name"; do
        [[ -L "$link" ]] || continue
        # Never remove an enablement link to somebody else's unit.
        [[ "$(readlink -m "$link")" == "$(readlink -m "$dir/$name")" ]] || continue
        smplos_keypad_backup "$link" "$state" || return 1
        rm "$link" || return 1
        SMPLOS_KEYPAD_UNITS_CHANGED=1
        echo "  Removed obsolete keypad login link $link"
    done
}

smplos_keypad_sync_units() {
    local src="$1" dir="$2" state="$3"
    local name=control-surface.service unit="$2/control-surface.service"
    local stamp="$state/last-installed.service" tmp owned=1
    SMPLOS_KEYPAD_UNITS_CHANGED=0
    [[ -f "$src/$name" ]] || { echo "  ERROR: $src/$name missing" >&2; return 1; }
    mkdir -p "$dir" "$state" || return 1
    if [[ -L "$unit" ]]; then
        owned=0
    elif [[ -e "$unit" ]] && ! cmp -s "$src/$name" "$unit" \
        && ! cmp -s "$stamp" "$unit" && ! smplos_keypad_known_unit "$unit"; then
        owned=0
    fi
    if [[ $owned -eq 0 ]]; then
        echo "  $unit is a custom unit; left as is (including its enablement and drop-ins)"
    else
        if ! cmp -s "$src/$name" "$unit"; then
            if [[ -e "$unit" ]]; then
                smplos_keypad_backup "$unit" "$state" || return 1
            fi
            tmp=$(mktemp "$dir/.$name.XXXXXX") || return 1
            install -m644 "$src/$name" "$tmp" && mv -f "$tmp" "$unit" || return 1
            SMPLOS_KEYPAD_UNITS_CHANGED=1
            echo "  Installed $name (device-triggered; recovered by the session login hook)"
        fi
        install -m644 "$src/$name" "$stamp" || return 1
        smplos_keypad_drop_links "$dir" "$name" "$state" || return 1
    fi

    unit="$dir/smplos-keypad-login.service"
    if smplos_keypad_known_unit "$unit" \
        && ! compgen -G "$unit.d/*.conf" >/dev/null; then
        smplos_keypad_drop_links "$dir" smplos-keypad-login.service "$state" || return 1
        smplos_keypad_backup "$unit" "$state" || return 1
        rm "$unit" || return 1
        SMPLOS_KEYPAD_UNITS_CHANGED=1
        echo "  Retired the temporary keypad login helper; smplos-session-services owns coldplug startup"
    elif [[ -e "$unit" || -L "$unit" ]]; then
        echo "  $unit is a custom login helper; left as is"
    fi
}
