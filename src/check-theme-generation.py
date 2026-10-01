#!/usr/bin/env python3
"""Regenerate only theme sources in isolation; never modify the checkout."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    source = Path(__file__).resolve().parent
    themes = source / "shared/themes"
    with tempfile.TemporaryDirectory(prefix="smplos-theme-check-") as temporary:
        fixture = Path(temporary)
        for name in (
            "regen-all-themes.sh", "generate-theme-configs.sh",
            "regen-nemo-css.py", "theme_opacity.py",
        ):
            shutil.copy2(source / name, fixture / name)
        generated = fixture / "shared/themes"
        shutil.copytree(themes / "_templates", generated / "_templates")
        for palette in themes.glob("*/colors.toml"):
            if palette.parent.name.startswith("_"):
                continue
            destination = generated / palette.parent.name
            destination.mkdir()
            shutil.copy2(palette, destination / palette.name)
        result = subprocess.run(
            ["bash", str(fixture / "regen-all-themes.sh")],
            stdout=subprocess.DEVNULL,
        )
        if result.returncode:
            return result.returncode
        stale = []
        for path in sorted(generated.glob("*/*")):
            if path.parent.name.startswith("_") or path.name == "colors.toml":
                continue
            relative = path.relative_to(generated)
            current = themes / relative
            if not current.is_file() or current.read_bytes() != path.read_bytes():
                stale.append(str(relative))
        if stale:
            print("Generated theme files are out of sync:", *stale, sep="\n", file=sys.stderr)
            print("Run: cd src && bash regen-all-themes.sh", file=sys.stderr)
            return 1
        print("All theme files match their generators.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
