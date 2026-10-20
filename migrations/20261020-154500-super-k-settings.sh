#!/bin/bash
# Migration: Super+K opens Settings on the Keybindings tab.
#
# Context: Super+K used to run the keybind-help overlay. Settings has a
#          Keybindings tab that lists, filters and edits every shortcut, so the
#          stock bind now opens it directly (settings --tab keybindings).
#          bindings.conf is user/Settings-owned and Update OS never rewrites it,
#          so existing installs keep the old bind. This repoints it.
#
# Safety:  Only the stock line (bindd = SUPER, K, Show keybindings, exec,
#          keybind-help) in the global scope is rewritten. A bind with another
#          description, flag, command or chord is the user's and stays, and so
#          does any second bind on SUPER+K. The stock comment above the line is
#          refreshed only when it is verbatim stock. A changed file gets a
#          verified backup first, and a symlinked file is left alone.
set -euo pipefail

python3 - <<'PY'
import os
from pathlib import Path
import re
import stat
import tempfile

# Both comments that ever shipped above the bind.
OLD_COMMENTS = (
    "# Keybinding help (fuzzy searchable list of all shortcuts)",
    "# Keybinding help (substring-searchable list of all shortcuts)",
)
NEW_COMMENT = "# Keybinding help: Settings on the Keybindings tab, filter box focused"
NEW_BIND = "bindd = SUPER, K, Show keybindings, exec, settings --tab keybindings &"


def ending_of(line):
    return line[len(line.rstrip("\r\n")):]


def stock_binds(lines):
    scope = "reset"
    for index, line in enumerate(lines):
        submap = re.fullmatch(r"\s*submap\s*=\s*(\S+)\s*", line)
        if submap:
            scope = submap[1]
        match = re.match(r"\s*(bind[a-z]*)\s*=\s*(.*)", line)
        if scope != "reset" or not match or match[1] != "bindd":
            continue
        fields = [part.strip() for part in match[2].split(",")]
        if [field.lower() for field in fields[:4]] == ["super", "k", "show keybindings", "exec"] \
                and fields[4:] == ["keybind-help"]:
            yield index


def repointed(lines, found):
    lines = list(lines)
    for index in found:
        line = lines[index]
        lines[index] = line[:len(line) - len(line.lstrip())] + NEW_BIND + ending_of(line)
        if index and lines[index - 1].rstrip("\r\n") in OLD_COMMENTS:
            lines[index - 1] = NEW_COMMENT + ending_of(lines[index - 1])
    return lines


def replace_safely(path, original, updated):
    before = path.stat()
    mode = stat.S_IMODE(before.st_mode)
    descriptor, backup = tempfile.mkstemp(prefix=path.name + ".pre-super-k-settings.", dir=path.parent)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(original)
        stream.flush()
        os.fchmod(stream.fileno(), mode)
        os.fsync(stream.fileno())
    if Path(backup).read_bytes() != original:
        raise SystemExit(f"ERROR: binding backup verification failed: {backup}")
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".tmp.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        if path.stat() != before or path.read_bytes() != original:
            raise SystemExit(f"ERROR: bindings changed during migration; not overwriting {path}")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return backup


def repoint(path):
    original = path.read_bytes()
    lines = original.decode("utf-8", errors="surrogateescape").splitlines(keepends=True)
    found = list(stock_binds(lines))
    if not found:
        print(f"  {path}: SUPER+K is not the stock keybind-help bind, nothing to do")
        return
    if path.is_symlink():
        print(f"  WARNING: {path} is a symlink; not modifying it. "
              f"Change its SUPER+K bind to '{NEW_BIND}' by hand.")
        return
    updated = "".join(repointed(lines, found)).encode("utf-8", errors="surrogateescape")
    backup = replace_safely(path, original, updated)
    print(f"  SUPER+K now opens Settings on the Keybindings tab in {path} (verified backup: {backup})")


seen = False
for relative in (".config/smplos/bindings.conf", ".config/hypr/bindings.conf"):
    path = Path.home() / relative
    if path.exists():
        seen = True
        repoint(path)
if not seen:
    print("  No bindings.conf found, nothing to do (new installs already have the new bind)")
PY
