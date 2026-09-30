"""Migrate only known smplOS DPMS commands; never regenerate idle preferences."""

import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


DPMS = re.compile(
    r"""hyprctl\s+dispatch\s+(?:dpms\s+(on|off)|"hl\.dsp\.dpms\(\{state='(on|off)'\}\)")"""
)
ASSIGNMENT = re.compile(
    r"^(\s*(?:# smpl-settings-disabled: )?\s*"
    r"(?:on-timeout|on-resume|after_sleep_cmd)\s*=\s*)(.*?)(\s*(?:#.*)?)(\r?\n)?$"
)
SIMPLE = re.compile(r"(?:systemd-detect-virt -q \|\| )?smplos-hypr-dpms (?:on|off)")
WAKE = re.compile(
    r"(?:loginctl lock-session; sleep 0\.5; )?smplos-hypr-dpms on;"
    r" sleep 0\.2; hyprctl reload; sleep 0\.2; smplos-hypr-dpms on"
)


def migrate(text):
    lines = []
    for line in text.splitlines(keepends=True):
        match = ASSIGNMENT.fullmatch(line)
        if match:
            prefix, command, comment, newline = match.groups()
            updated = DPMS.sub(lambda m: f"smplos-hypr-dpms {m[1] or m[2]}", command)
            if SIMPLE.fullmatch(updated) or WAKE.fullmatch(updated):
                line = prefix + updated + comment + (newline or "")
        lines.append(line)
    return "".join(lines)


def validate(path):
    # hypridle 0.1.7 has no --verify-config. It parses before connecting to
    # Wayland; a private nonexistent socket prevents ALL listener execution.
    with tempfile.TemporaryDirectory(prefix="smplos-hypridle-check-") as runtime:
        # 0.1.7 resolves a default config even with -c, for include bookkeeping.
        default = Path(runtime) / "hypr/hypridle.conf"
        default.parent.mkdir()
        default.symlink_to(path.resolve())
        env = dict(os.environ, XDG_RUNTIME_DIR=runtime,
                   XDG_CONFIG_HOME=runtime,
                   WAYLAND_DISPLAY=f"{runtime}/no-compositor",
                   DBUS_SESSION_BUS_ADDRESS=f"unix:path={runtime}/no-bus")
        env.pop("WAYLAND_SOCKET", None)
        env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
        result = subprocess.run(
            ["hypridle", "-c", str(path)], env=env, capture_output=True,
            text=True, timeout=5,
        )
    output = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + result.stderr)
    # All-Never is valid policy; hypridle logs this harmless diagnostic but
    # still runs its general lock/sleep handlers with zero listeners.
    output = re.sub(
        r"Config has errors:\s*No rules configured\s*Proceeding ignoring faulty entries",
        "", output,
    )
    if (result.returncode != 1 or "Couldn't connect to a wayland compositor" not in output
            or "Config has errors:" in output or "ConfigManager threw:" in output):
        raise RuntimeError(f"hypridle validation failed; configuration not applied:\n{output}")


def migrate_file(config, pending):
    if not config.exists() and not config.is_symlink():
        return
    target = config.resolve(strict=True)
    original_stat = target.stat()
    if not stat.S_ISREG(original_stat.st_mode) or original_stat.st_uid != os.getuid():
        raise RuntimeError(f"refusing to replace non-regular or non-user-owned config: {target}")
    original = target.read_bytes()
    updated = migrate(original.decode("utf-8", errors="surrogateescape")).encode(
        "utf-8", errors="surrogateescape")
    if b"smplos-hypr-dpms" in updated and not any(
            (Path(p) / "smplos-hypr-dpms").is_file()
            and os.access(Path(p) / "smplos-hypr-dpms", os.X_OK) for p in os.get_exec_path()):
        raise RuntimeError("smplos-hypr-dpms is missing; update OS scripts before migrating")
    if updated == original:
        if pending.exists():
            validate(config)
        return
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stage:
            stage.write(updated)
            stage.flush()
            os.fsync(stage.fileno())
            os.fchmod(stage.fileno(), stat.S_IMODE(original_stat.st_mode))
        validate(Path(temporary))
        current_stat = target.stat()
        if (config.resolve(strict=True) != target
                or any(getattr(current_stat, field) != getattr(original_stat, field)
                       for field in ("st_dev", "st_ino", "st_mtime_ns", "st_ctime_ns"))
                or target.read_bytes() != original):
            raise RuntimeError("idle config changed during migration; retry without editing it")
        backup_fd, backup = tempfile.mkstemp(prefix=f"{target.name}.pre-dpms-helper.", dir=target.parent)
        with os.fdopen(backup_fd, "wb") as saved:
            saved.write(original)
            saved.flush()
            os.fsync(saved.fileno())
            os.fchmod(saved.fileno(), stat.S_IMODE(original_stat.st_mode))
        if Path(backup).read_bytes() != original:
            raise RuntimeError(f"backup verification failed: {backup}")
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.touch()
        os.replace(temporary, target)
        print(f"hypridle: migrated known DPMS commands; original saved at {backup}")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    home = Path.home()
    try:
        migrate_file(home / ".config/hypr/hypridle.conf",
                     home / ".local/state/smplos/hypridle-apply-pending")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"hypridle: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
