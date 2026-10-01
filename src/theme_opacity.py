"""Shared build-time validation for native background opacity."""

from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys
import tomllib


def opacity(value, key):
    text = str(value)
    if not isinstance(value, (int, float)) and not re.fullmatch(
        r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", text
    ):
        raise ValueError(f"{key} must be a finite decimal in [0,1], got {value!r}")
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"Invalid {key}: {value!r}") from error
    if not number.is_finite() or not 0 <= number <= 1:
        raise ValueError(f"{key} must be in [0,1], got {value!r}")
    return format(number, "f")


def app_background_opacity(colors):
    for key in ("app_background_opacity", "popup_opacity"):
        if key in colors:
            opacity(colors[key], key)
    key = "app_background_opacity" if "app_background_opacity" in colors else "popup_opacity"
    return opacity(colors.get(key, "1.0"), key)


def read_colors(path):
    with open(path, "rb") as source:
        return tomllib.load(source)


if __name__ == "__main__":
    for name in sys.argv[1:]:
        try:
            print(app_background_opacity(read_colors(Path(name))))
        except (OSError, ValueError) as error:
            sys.exit(f"{name}: {error}")
