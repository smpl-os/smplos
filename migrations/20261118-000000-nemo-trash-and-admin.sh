#!/bin/bash
# SMPLOS_UPDATE_PRIORITY=core
# Repair stock shortcuts while preserving explicit custom assignments.
set -euo pipefail

python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, Gtk


def backup(original, label):
    directory = Path.home() / ".local/state/smplos/backups/nemo-shortcuts"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = directory / f"{label}.{hashlib.sha256(original).hexdigest()}.bak"
    if not path.exists():
        with path.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
    if path.read_bytes() != original:
        raise RuntimeError(f"Nemo shortcut backup verification failed: {path}")
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return path


def publish_binding(path, original, updated):
    if path.is_symlink():
        raise SystemExit(f"ERROR: Refusing to replace symlinked bindings: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    before = path.stat() if path.exists() else None
    saved = backup(original, "bindings-" + path.name)
    fd, temporary = tempfile.mkstemp(prefix=".nemo-admin.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fchmod(stream.fileno(), stat.S_IMODE(before.st_mode) if before else 0o600)
            os.fsync(stream.fileno())
        if (path.stat() if path.exists() else None) != before \
                or (path.read_bytes() if path.exists() else b"") != original:
            raise SystemExit(f"ERROR: Bindings changed during migration; retry Update OS: {path}")
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print(f"  Added administrator Nemo shortcut in {path} (verified backup: {saved})")


schema = Gio.SettingsSchemaSource.get_default().lookup("org.nemo.keybindings", True)
if schema is None:
    raise SystemExit("ERROR: Nemo keybinding schema is missing; retry Update OS after native delivery")
settings = Gio.Settings.new_full(schema, None, None)
keys = schema.list_keys()
snapshot = {key: {"user": settings.get_user_value(key).print_(True)
                  if settings.get_user_value(key) is not None else None,
                  "effective": settings.get_value(key).print_(True)}
            for key in keys}
updates = {}
for key, wanted in (("trash-alt", "Delete"),
                    ("delete-permanently", "<Shift>Delete"),
                    ("delete-permanently-alt", "<Shift>F8")):
    user = settings.get_user_value(key)
    current = settings.get_string(key)
    if current == wanted:
        continue
    if user is not None:
        print(f"  Preserving customized Nemo {key}")
        continue
    updates[key] = wanted

# Do not assign a shortcut already used by another action, including a custom
# permanent Delete binding. Discard dependent plans if a planned move conflicts.
while True:
    conflicts = {
        key for key, wanted in updates.items()
        if any(other != key and Gtk.accelerator_parse(updates.get(other, settings.get_string(other)))
               == Gtk.accelerator_parse(wanted)
               for other in keys)
    }
    if not conflicts:
        break
    for key in conflicts:
        print(f"  WARNING: Nemo {updates[key]} is already assigned; preserving it instead of changing {key}")
        del updates[key]

if updates:
    saved = backup(json.dumps(snapshot, sort_keys=True, indent=2).encode(), "gsettings")
    for key in keys:
        user = settings.get_user_value(key)
        if (user.print_(True) if user is not None else None) != snapshot[key]["user"]:
            raise SystemExit("ERROR: Nemo shortcuts changed during migration; retry Update OS")
    settings.delay()
    for key, value in updates.items():
        if not settings.is_writable(key) or not settings.set_string(key, value):
            settings.revert()
            raise SystemExit(f"ERROR: Cannot set Nemo {key}; retry Update OS")
    settings.apply()
    Gio.Settings.sync()
    verify = Gio.Settings.new_full(schema, None, None)
    if any(verify.get_string(key) != value for key, value in updates.items()):
        raise SystemExit("ERROR: Nemo shortcut persistence failed; retry Update OS")
    print(f"  Repaired Nemo shortcuts (verified backup: {saved})")


binding = "bindd = SUPER CTRL SHIFT, F, File manager (administrator), exec, nemo-admin\n"
paths = [Path.home() / ".config/smplos/bindings.conf",
         Path.home() / ".config/hypr/bindings.conf"]
existing = [path for path in paths if path.exists()]
occupied = False
for path in existing:
    scope = "reset"
    for line in path.read_text().splitlines():
        submap = re.fullmatch(r"\s*submap\s*=\s*(\S+)\s*", line)
        if submap:
            scope = submap[1]
        match = re.match(r"\s*bind[a-z]*\s*=\s*([^,]*),\s*([^,]+),", line)
        if scope == "reset" and match and set(match[1].upper().split()) == {"SUPER", "CTRL", "SHIFT"} \
                and match[2].strip().upper() == "F":
            occupied = True
if occupied:
    print("  Preserving existing Super+Ctrl+Shift+F assignment")
else:
    path = existing[0] if existing else paths[0]
    original = path.read_bytes() if path.exists() else b""
    # Explicit reset prevents an unterminated user submap capturing the new bind.
    updated = original + (b"\n" if original and not original.endswith(b"\n") else b"") \
        + b"\nsubmap = reset\n" + binding.encode()
    publish_binding(path, original, updated)

niri_paths = [
    Path(os.environ.get("SMPLOS_PATH", Path.home() / ".local/share/smplos")) / "configs/niri/binds.kdl",
    Path.home() / ".config/niri/binds.kdl",
    Path.home() / ".config/niri/config.kdl",
]
niri_binding = ('    Mod+Ctrl+Shift+f hotkey-overlay-title="File manager (administrator)" '
                '{ spawn "sh" "-c" "nemo-admin"; }\n')
for path in niri_paths:
    if not path.exists():
        continue
    original = path.read_bytes()
    text = original.decode()
    occupied = any(
        set(match[1].lower().split("+")) == {"mod", "ctrl", "shift", "f"}
        for match in re.finditer(r"(?m)^\s*([\w+]+)\s+[^{}\n]*\{", text)
    )
    if occupied:
        print(f"  Preserving existing niri Super+Ctrl+Shift+F in {path}")
        continue
    updated, count = re.subn(r"(?m)^([ \t]*binds[ \t]*\{)[ \t]*\n",
                            lambda match: match[0] + niri_binding, text, count=1)
    if not count:
        raise SystemExit(f"ERROR: Cannot find niri binds block in {path}; retry Update OS")
    publish_binding(path, original, updated.encode())
PY
