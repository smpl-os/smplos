"""Terminal syntax and ANSI colors stay legible across every stock theme."""

import importlib.util
from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
THEMES = ROOT / "src/shared/themes"
SPEC = importlib.util.spec_from_file_location(
    "theme_terminal_colors",
    ROOT / "src/shared/lib/theme_terminal_colors.py",
)
COLORS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLORS)


class TerminalThemeContrastTests(unittest.TestCase):
    def palettes(self):
        return sorted(THEMES.glob("*/colors.toml"))

    def generated_fish(self, theme):
        values = {}
        for line in (theme / "fish.theme").read_text().splitlines():
            match = re.match(r"set -g (fish_(?:color|pager_color)_\S+)\s+(\S+)", line)
            if match:
                values[match[1]] = match[2].lstrip("#")
        return values

    def test_ansi_palette_is_readable_for_every_theme(self):
        for path in self.palettes():
            with self.subTest(theme=path.parent.name):
                with path.open("rb") as source:
                    palette = tomllib.load(source)
                derived = COLORS.derive(palette)
                for slot in range(16):
                    self.assertGreaterEqual(
                        COLORS.contrast(derived[f"term_{slot}"], palette["background"]),
                        5.0,
                    )
                self.assertGreaterEqual(
                    COLORS.contrast(derived["terminal_foreground"], palette["background"]),
                    7.0,
                )

    def test_available_and_unavailable_commands_are_distinct(self):
        for path in self.palettes():
            with self.subTest(theme=path.parent.name):
                with path.open("rb") as source:
                    palette = tomllib.load(source)
                derived = COLORS.derive(palette)
                self.assertGreaterEqual(
                    COLORS.contrast(derived["fish_command"], palette["background"]),
                    6.0,
                )
                self.assertGreaterEqual(
                    COLORS.contrast(derived["fish_error"], palette["background"]),
                    6.0,
                )
                self.assertGreaterEqual(
                    COLORS.distance(derived["fish_command"], derived["fish_error"]),
                    72,
                )

    def test_comments_and_autosuggestions_are_not_dimmed_below_aa(self):
        for path in self.palettes():
            with self.subTest(theme=path.parent.name):
                with path.open("rb") as source:
                    palette = tomllib.load(source)
                derived = COLORS.derive(palette)
                self.assertGreaterEqual(
                    COLORS.contrast(derived["fish_comment"], palette["background"]),
                    4.8,
                )
                self.assertGreaterEqual(
                    COLORS.contrast(derived["fish_autosuggestion"], palette["background"]),
                    4.5,
                )

    def test_legacy_terminal_colors_are_adjusted_before_delivery(self):
        palette = {
            "background": "#111c18",
            "foreground": "#c1c497",
            "surface": "#111c18",
            "color4": "#123456",
            "term_12": "#62b5ff",
        }
        derived = COLORS.derive(palette)
        self.assertGreaterEqual(
            COLORS.contrast(derived["term_4"], palette["background"]), 5.0
        )
        self.assertGreaterEqual(
            COLORS.contrast(derived["term_12"], palette["background"]), 5.0
        )
        self.assertNotEqual(derived["term_4"], palette["color4"])

    def test_generated_fish_and_foot_files_use_derived_colors(self):
        for path in self.palettes():
            with self.subTest(theme=path.parent.name):
                with path.open("rb") as source:
                    palette = tomllib.load(source)
                derived = COLORS.derive(palette)
                fish = self.generated_fish(path.parent)
                self.assertEqual(fish["fish_color_command"], derived["fish_command"][1:])
                self.assertEqual(fish["fish_color_error"], derived["fish_error"][1:])
                self.assertEqual(fish["fish_color_comment"], derived["fish_comment"][1:])
                foot = (path.parent / "foot.ini").read_text()
                foreground = re.search(r"^foreground=(\w+)$", foot, re.M).group(1)
                self.assertEqual(f"#{foreground}".lower(),
                                 derived["terminal_foreground"])
                for slot in range(16):
                    match = re.search(rf"^{slot}=(\w+)$", foot, re.M)
                    self.assertEqual(f"#{match.group(1)}".lower(),
                                     derived[f"term_{slot}"])


if __name__ == "__main__":
    unittest.main()
