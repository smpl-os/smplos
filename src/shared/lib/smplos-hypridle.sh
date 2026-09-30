# shellcheck shell=bash
# Source after smplos-session-env.sh.

smplos_apply_hypridle() {
    if ! smplos_have_hyprland || ! smplos_have_user_bus; then
        echo "hypridle: no Hyprland user session; deferred until Update OS in a graphical session." >&2
        return 75
    fi
    local loaded main_pid pids pid
    loaded=$(smplos_run_as_user systemctl --user show hypridle.service -p LoadState --value) || return 1
    if [[ "$loaded" != loaded ]]; then
        echo "hypridle: packaged user service unavailable; install hypridle and retry." >&2
        return 1
    fi
    # Enable for next login even if an old unmanaged instance must be left
    # running until logout. This does not start a second daemon.
    smplos_run_as_user systemctl --user enable hypridle.service || return 1
    main_pid=$(smplos_run_as_user systemctl --user show hypridle.service -p MainPID --value) || return 1
    pids=$(smplos_run_as_user pgrep -u "$SMPLOS_SESSION_UID" -x hypridle) || {
        local status=$?
        [[ $status == 1 ]] || return "$status"
    }
    for pid in $pids; do
        if [[ "$pid" != "$main_pid" ]]; then
            echo "hypridle: unmanaged daemon PID $pid; after a normal Update OS, log out/in and retry. No process was killed." >&2
            return 75
        fi
    done
    smplos_run_as_user systemctl --user import-environment WAYLAND_DISPLAY HYPRLAND_INSTANCE_SIGNATURE || return 1
    smplos_run_as_user systemctl --user restart hypridle.service || return 1
    sleep 0.2
    smplos_run_as_user systemctl --user is-active --quiet hypridle.service || {
        echo "hypridle: user service did not stay active; inspect journalctl --user -u hypridle.service." >&2
        return 1
    }
    echo "hypridle: user service restarted and active (not an acknowledgement of each idle rule)."
}

smplos_migrate_hypridle() {
    local lib_dir
    lib_dir=$(dirname "${BASH_SOURCE[0]}")
    if [[ -e "$HOME/.config/hypr/hypridle.conf" || -L "$HOME/.config/hypr/hypridle.conf" ]] \
        && ! smplos_have_hyprland; then
        echo "hypridle: no Hyprland session; configuration migration deferred until a graphical update." >&2
        return 75
    fi
    python3 "$lib_dir/smplos-hypridle-migrate.py" || return 1
    local pending="$HOME/.local/state/smplos/hypridle-apply-pending"
    if [[ -e "$pending" ]]; then
        smplos_apply_hypridle || return $?
        rm -- "$pending" || return 1
    fi
}
