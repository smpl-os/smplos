#!/usr/bin/env python3
"""Derive readable terminal and Fish colors from a smplOS palette."""

from __future__ import annotations

import colorsys
import re
import sys
import tomllib
from pathlib import Path


HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
TERM_SOURCES = (
    "surface",
    "danger",
    "success",
    "warning",
    "accent",
    "accent_alt",
    "info",
    "fg_alt",
    "muted",
    "danger_bright",
    "success_bright",
    "warning_bright",
    "accent_bright",
    "accent_alt_bright",
    "info_bright",
    "fg_dim",
)


def rgb(value: str) -> tuple[int, int, int]:
    if not HEX.fullmatch(value):
        raise ValueError(f"expected #rrggbb color, got {value!r}")
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def luminance(value: str) -> float:
    channels = [channel / 255 for channel in rgb(value)]
    linear = [
        channel / 12.92 if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def adjusted(value: str, background: str, target: float) -> str:
    if contrast(value, background) >= target:
        return value.lower()

    start = rgb(value)
    candidates: list[tuple[float, str]] = []
    for destination in ((0, 0, 0), (255, 255, 255)):
        for step in range(1, 101):
            amount = step / 100
            mixed = tuple(
                round(channel + (end - channel) * amount)
                for channel, end in zip(start, destination)
            )
            candidate = "#" + "".join(f"{channel:02x}" for channel in mixed)
            if contrast(candidate, background) >= target:
                change = sum(abs(left - right) for left, right in zip(start, mixed))
                candidates.append((change, candidate))
                break
    if not candidates:
        raise ValueError(f"cannot make {value} meet {target}:1 against {background}")
    return min(candidates)[1]


def distance(first: str, second: str) -> float:
    return sum((left - right) ** 2 for left, right in zip(rgb(first), rgb(second))) ** 0.5


def hue(value: str) -> float:
    red, green, blue = (channel / 255 for channel in rgb(value))
    return colorsys.rgb_to_hsv(red, green, blue)[0]


def derive(colors: dict[str, object]) -> dict[str, str]:
    palette = {
        key: value for key, value in colors.items()
        if isinstance(value, str) and HEX.fullmatch(value)
    }
    if "background" not in palette or "foreground" not in palette:
        raise ValueError("theme needs hexadecimal background and foreground colors")

    background = palette["background"]
    output: dict[str, str] = {}
    for slot, source in enumerate(TERM_SOURCES):
        value = palette.get(
            f"term_{slot}",
            palette.get(f"color{slot}", palette.get(source, palette["foreground"])),
        )
        output[f"term_{slot}"] = adjusted(value, background, 5.0)

    foreground = adjusted(palette["foreground"], background, 7.0)
    error = adjusted(
        palette.get("danger_bright", palette.get("danger", foreground)),
        background,
        6.0,
    )
    command = adjusted(
        palette.get("accent_bright", palette.get("accent", foreground)),
        background,
        6.0,
    )

    # Monochrome/HUD palettes often reuse one accent for command and danger.
    if distance(command, error) < 72:
        candidates = []
        for key in (
            "info_bright", "success_bright", "accent_alt_bright",
            "warning_bright", "info", "success", "foreground",
        ):
            if key in palette:
                candidate = adjusted(palette[key], background, 6.0)
                candidates.append((distance(candidate, error), hue(candidate), candidate))
        if candidates:
            command = max(candidates)[2]

    keyword = adjusted(
        palette.get("accent_alt_bright", palette.get("accent_alt", command)),
        background,
        6.0,
    )
    if distance(keyword, command) < 48:
        keyword = adjusted(
            palette.get("warning_bright", palette.get("warning", error)),
            background,
            6.0,
        )

    output.update({
        "terminal_foreground": foreground,
        "fish_normal": foreground,
        "fish_command": command,
        "fish_keyword": keyword,
        "fish_quote": adjusted(
            palette.get("success_bright", palette.get("success", foreground)),
            background,
            6.0,
        ),
        "fish_redirection": adjusted(
            palette.get("info_bright", palette.get("info", foreground)),
            background,
            5.5,
        ),
        "fish_end": adjusted(
            palette.get("warning_bright", palette.get("warning", keyword)),
            background,
            5.5,
        ),
        "fish_error": error,
        "fish_param": foreground,
        "fish_comment": adjusted(
            palette.get("muted", foreground),
            background,
            4.8,
        ),
        "fish_operator": adjusted(
            palette.get("info_bright", palette.get("info", foreground)),
            background,
            5.5,
        ),
        "fish_escape": keyword,
        "fish_autosuggestion": adjusted(
            palette.get("autosuggestion", palette.get("muted", foreground)),
            background,
            4.5,
        ),
    })
    return output


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} COLORS_TOML", file=sys.stderr)
        return 2
    with Path(sys.argv[1]).open("rb") as source:
        colors = tomllib.load(source)
    try:
        derived = derive(colors)
    except ValueError as error:
        print(f"terminal color error: {error}", file=sys.stderr)
        return 1
    for key, value in derived.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
