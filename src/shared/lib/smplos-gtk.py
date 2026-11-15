"""Apply standard GTK preferences without global theme overrides or lost settings."""

import argparse
import ast
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


SCHEMA = "org.gnome.desktop.interface"
STOCK_WIDGET_THEMES = {"Adwaita", "Adwaita-dark"}


def gsettings(action, key, value=None):
    command = ["gsettings", action, SCHEMA, key]
    if value is not None:
        command.append(value)
    result = subprocess.run(command, check=True, text=True, capture_output=True, timeout=10)
    if action == "get":
        value = ast.literal_eval(result.stdout.strip())
        if not isinstance(value, str):
            raise ValueError(f"{key} is not a string")
        return value


def backup(original, label):
    directory = Path.home() / ".local/state/smplos/backups/gtk"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    digest = hashlib.sha256(original).hexdigest()
    path = directory / f"{label}.{digest}.bak"
    if not path.exists():
        with path.open("xb") as saved:
            os.fchmod(saved.fileno(), 0o600)
            saved.write(original)
            saved.flush()
            os.fsync(saved.fileno())
    if path.read_bytes() != original:
        raise RuntimeError(f"backup verification failed: {path}")
    return path


def write_config(path, transform):
    target = path.resolve(strict=path.exists() or path.is_symlink())
    original = b""
    mode = 0o600
    if target.exists():
        info = target.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError(f"refusing non-regular or non-user-owned settings: {target}")
        original = target.read_bytes()
        mode = stat.S_IMODE(info.st_mode)
    updated = transform(original.decode("utf-8")).encode("utf-8")
    if original == updated:
        return
    saved = backup(original, path.parent.name + "-" + path.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stage:
            stage.write(updated)
            stage.flush()
            os.fsync(stage.fileno())
            os.fchmod(stage.fileno(), mode)
        if path.resolve() != target or (target.read_bytes() if target.exists() else b"") != original:
            raise RuntimeError(f"settings changed during publication: {path}; retry")
        os.replace(temporary, target)
        print(f"gtk: updated {path}; original saved at {saved}")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def settings_ini(text, dark, icons, version):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    values = dict(parser["Settings"]) if parser.has_section("Settings") else {}
    updates = {
        "gtk-application-prefer-dark-theme": str(int(dark)),
        "gtk-icon-theme-name": icons,
    }
    for key, default in (
        ("gtk-theme-name", "Adwaita"),
        ("gtk-font-name", "JetBrains Mono 11"),
        ("gtk-cursor-theme-name", "Adwaita"),
    ):
        if key not in values or (key == "gtk-theme-name" and values[key] in STOCK_WIDGET_THEMES):
            updates[key] = default
    remove = {"gtk-enable-mnemonics", "gtk-auto-mnemonics"} if version == 4 else set()
    lines = []
    in_settings = False
    pending = dict(updates)
    for line in text.splitlines(keepends=True):
        if re.match(r"\s*\[", line):
            if in_settings:
                lines.extend(f"{key}={value}\n" for key, value in pending.items())
                pending.clear()
            in_settings = line.strip() == "[Settings]"
        match = re.match(r"\s*([\w-]+)\s*=", line) if in_settings else None
        if match:
            key = match[1]
            if key in remove:
                continue
            if key in pending:
                line = f"{key}={pending.pop(key)}\n"
        lines.append(line)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    if not parser.has_section("Settings"):
        lines.append("[Settings]\n")
    lines.extend(f"{key}={value}\n" for key, value in pending.items())
    updated = "".join(lines)
    parser.read_string(updated)
    return updated


def icon_theme_available(name):
    if not name or name in {".", ".."} or "/" in name:
        return False
    home = Path.home()
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    roots = [data_home / "icons", home / ".icons"]
    roots.extend(Path(root) / "icons" for root in data_dirs if root and Path(root).is_absolute())
    return any((root / name / "index.theme").is_file() for root in roots)


def environment_file(text):
    return "".join(
        line for line in text.splitlines(keepends=True)
        if not re.fullmatch(r"\s*GTK_THEME\s*=\s*[\"']?Adwaita(?::dark|-dark)?[\"']?\s*", line)
    )


def compositor_file(text, kind):
    patterns = {
        "conf": r"""\s*env\s*=\s*GTK_THEME\s*,\s*Adwaita(?::dark|-dark)?\s*""",
        "lua": r"""\s*hl\.env\(\s*["']GTK_THEME["']\s*,\s*["']Adwaita(?::dark|-dark)?["']\s*\)\s*""",
        "kdl": r"""\s*GTK_THEME\s+"Adwaita(?::dark|-dark)?"\s*;?\s*""",
    }
    return "".join(line for line in text.splitlines(keepends=True)
                   if not re.fullmatch(patterns[kind], line))


def configure(dark):
    current = {key: gsettings("get", key) for key in ("gtk-theme", "icon-theme", "color-scheme")}
    icons = current["icon-theme"]
    if not icon_theme_available(icons):
        if not icon_theme_available("Adwaita"):
            raise RuntimeError("Adwaita icons are missing; install adwaita-icon-theme before applying preferences")
        print(f"gtk: icon theme {icons!r} is unavailable; using installed Adwaita", file=sys.stderr)
        icons = "Adwaita"
    desired = {"icon-theme": icons, "color-scheme": "prefer-dark" if dark else "prefer-light"}
    if current["gtk-theme"] in STOCK_WIDGET_THEMES:
        desired["gtk-theme"] = "Adwaita-dark" if dark else "Adwaita"
    changes = {key: value for key, value in desired.items() if current[key] != value}
    if changes:
        original = (json.dumps(current, sort_keys=True, indent=2) + "\n").encode()
        saved = backup(original, "gsettings-interface")
        print(f"gtk: original interface preferences saved at {saved}")
        for key, value in changes.items():
            gsettings("set", key, value)
            if gsettings("get", key) != value:
                raise RuntimeError(f"GTK preference was not applied: {key}")
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    for version in (3, 4):
        write_config(config / f"gtk-{version}.0/settings.ini",
                     lambda text, version=version: settings_ini(text, dark, icons, version))
    environment = config / "environment.d/gtk.conf"
    if environment.exists() or environment.is_symlink():
        write_config(environment, environment_file)
    smplos = Path(os.environ.get("SMPLOS_PATH", Path.home() / ".local/share/smplos"))
    for path in (
        config / "hypr/envs.conf", config / "hypr/envs.lua",
        config / "niri/config.kdl",
        smplos / "configs/niri/base.kdl", smplos / "configs/niri/config.kdl",
    ):
        if path.exists() or path.is_symlink():
            write_config(path, lambda text, kind=path.suffix[1:]: compositor_file(text, kind))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dark", action="store_true")
    mode.add_argument("--light", action="store_true")
    args = parser.parse_args()
    try:
        configure(args.dark)
    except (OSError, ValueError, SyntaxError, RuntimeError, configparser.Error,
            subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        print(f"gtk: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
