#!/usr/bin/env python3
"""Bake shared SVG color roles consistently during builds, updates and switches."""

import argparse
import os
from pathlib import Path
import re
import sys
import tempfile
import tomllib


def bake(palette, template, destination):
    with palette.open("rb") as stream:
        colors = tomllib.load(stream)
    roles = {
        "fg": colors.get("foreground", "#888888"),
        "bg": colors.get("background", "#1e1e2e"),
        "accent": colors.get("accent", "#888888"),
        "fg-dim": colors.get("fg_dim", colors.get("foreground", "#888888")),
    }
    if colors.get("glass") in ("true", True):
        for role, key in (("fg", "glass_foreground"), ("accent", "glass_accent"),
                          ("fg-dim", "glass_fg_dim")):
            roles[role] = colors.get(key, roles[role])
    text = template.read_text()
    for role, color in roles.items():
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError(f"{palette}: invalid {role} color {color!r}")
        text = text.replace("{{" + role + "}}", color)
    if re.search(r"\{\{[^{}]+\}\}", text):
        raise ValueError(f"{template}: unresolved SVG color role")
    if destination.is_file() and destination.read_text() == text:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=destination.parent,
                                         prefix=destination.name + ".", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            os.fchmod(stream.fileno(), 0o644)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("palette", "template", "destination"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    try:
        bake(args.palette, args.template, args.destination)
    except (OSError, ValueError) as error:
        print(f"smplos-theme-svg: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
