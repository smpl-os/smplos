import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from theme_opacity import app_background_opacity, read_colors

spec = importlib.util.spec_from_file_location("nemo_css", SRC / "regen-nemo-css.py")
nemo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nemo)


class AlphaContractTests(unittest.TestCase):
    def test_precedence_and_opaque_unknown_theme(self):
        for colors, expected in (
            ({}, "1.0"),
            ({"popup_opacity": "0.7"}, "0.7"),
            ({"popup_opacity": ".9", "app_background_opacity": "0.4"}, "0.4"),
            ({"popup_opacity": "0.9", "app_background_opacity": "0.4"}, "0.4"),
            ({"app_background_opacity": 0}, "0"),
            ({"app_background_opacity": 1.0}, "1.0"),
            ({"app_background_opacity": 0.0000001}, "0.0000001"),
        ):
            with self.subTest(colors=colors):
                self.assertEqual(app_background_opacity(colors), expected)

    def test_invalid_explicit_values_never_fall_through(self):
        for value in ("nan", "inf", "-0.1", "1.01", "", "oops", True, None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    app_background_opacity(
                        {"app_background_opacity": value, "popup_opacity": "0.8"}
                    )

    def test_all_stock_palettes_apply_equal_ordinary_alpha_without_focus_fade(self):
        palettes = list((SRC / "shared/themes").glob("*/colors.toml"))
        self.assertEqual(len(palettes), 17)
        for path in palettes:
            with self.subTest(theme=path.parent.name):
                colors = read_colors(path)
                self.assertEqual(colors["app_background_opacity"], colors["popup_opacity"])
                for key in ("opacity_active", "opacity_inactive", "browser_opacity", "messenger_opacity"):
                    self.assertEqual(colors[key], colors["app_background_opacity"])
                if path.parent.name in ("matrix", "amber", "grafium"):
                    self.assertEqual(app_background_opacity(colors), "1.0")

    def test_nemo_single_owner_and_capability_gate_preserve_legacy_css(self):
        colors = read_colors(SRC / "shared/themes/catppuccin/colors.toml")
        for alpha in ("0", "0.50", "1.0", "0.50"):
            colors["app_background_opacity"] = alpha
            css = nemo.make_nemo_css(colors)
            legacy, native = css.split("/* Native-alpha capability:", 1)
            self.assertIn("menuitem:hover > menu menuitem", legacy)
            self.assertIn("menu menuitem:hover > label:dir(ltr)", legacy)
            self.assertIn("background-color: #1e1e2e", legacy)
            self.assertEqual(native.count(f"alpha(#1e1e2e, {alpha})"), 1)
            self.assertIn(".nemo-secondary-label", native)
            self.assertIn(".dim-label:not(:selected)", native)
            self.assertIn(".dim-label:selected", native)
            self.assertIn("opacity: 1;", native)
            for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]+)\}", native):
                if "opacity:" in declarations:
                    self.assertIn("label", selectors)
                    self.assertEqual(re.findall(r"opacity:\s*([^;]+);", declarations), ["1"])
            for selectors in re.findall(r"([^{}]+)\{[^{}]+\}", native):
                selectors = selectors.split("*/")[-1]
                for selector in selectors.split(","):
                    self.assertIn(".smplos-native-alpha", selector)
            self.assertIn(".nemo-desktop-window", native)
            self.assertIn(".view:not(:selected)", native)
            self.assertIn("box:not(.floating-bar)", native)
            self.assertIn(".smplos-native-alpha decoration", native)
            self.assertNotIn("menuitem", native)

    def test_compositor_passthrough_and_rofi_native_background(self):
        hypr = SRC / "compositors/hyprland/hypr"
        for suffix in ("conf", "lua"):
            text = (hypr / f"windows.{suffix}").read_text()
            self.assertIn("hints-overlay", text)
            self.assertIn("grafium|nemo|org", text)
            self.assertIn("self-managed-alpha", text)
            self.assertIn("1.0 override 1.0 override", text)
            self.assertNotIn("themePopupOpacity", text)
        rofi = (SRC / "shared/themes/_templates/smplos-launcher.rasi.tpl").read_text()
        self.assertIn("rgba({{ background_rgb }},{{ popup_opacity }})", rofi)
        self.assertIn("foreground:                  {{ foreground }};", rofi)

    @unittest.skipUnless(shutil.which("lua"), "Lua runtime unavailable")
    def test_owned_apps_remain_neutral_with_translucent_custom_compositor_theme(self):
        harness = """
package.preload.theme = function()
    return {themeOpacityActive="0.3", themeOpacityInactive="0.2",
            themeMessengerOpacity="0.4"}
end
hl = {layer_rule=function(_) end, window_rule=function(rule)
    local match = rule.match
    if (rule.tag or rule.opacity) and not match.title and
       not match.initial_title and not match.fullscreen then
        print(table.concat({match.class or "", match.tag or "",
                            rule.tag or "", rule.opacity or ""}, "\\t"))
    end
end}
dofile(arg[1])
"""
        result = subprocess.run(
            ["lua", "-", str(SRC / "compositors/hyprland/hypr/windows.lua")],
            input=harness, text=True, capture_output=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rules = [line.split("\t") for line in result.stdout.splitlines()]
        for app in (
            "nemo", "org.Nemo.nemo-float", "grafium", "rofi", "hints-overlay",
            "settings", "app-center", "webapp-center", "sync-center",
            "start-menu", "notif-center", "smpl-calendar", "smpl-calendar-details",
        ):
            with self.subTest(app=app):
                tags = set()
                opacity = None
                for class_pattern, tag_match, tag_set, alpha in rules:
                    if class_pattern and not re.search(class_pattern, app):
                        continue
                    if tag_match and tag_match not in tags:
                        continue
                    if tag_set:
                        tags.add(tag_set.removeprefix("+"))
                    if alpha:
                        opacity = alpha
                self.assertIn("self-managed-alpha", tags)
                self.assertEqual(opacity, "1.0 override 1.0 override")

    def test_iso_seeds_native_palette_and_nemo_css_before_first_switch(self):
        source = (SRC / "builder/build.sh").read_text()
        fragment = source.split("# Link pre-baked configs into app config dirs for live session", 1)[1]
        fragment = fragment.split("# Bake SVG icon templates", 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                ["bash", "-c", 'set -e; SRC_DIR=$1; skel=$2; seed() {\n'
                 + fragment + '\n}; seed', "seed", str(SRC), temporary],
                text=True, capture_output=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for source_name, target_name in (
                ("eww-colors.scss", "eww/theme-colors.scss"),
                ("nemo.css", "smplos/nemo-theme.css"),
            ):
                self.assertEqual(
                    (Path(temporary) / ".config" / target_name).read_bytes(),
                    (SRC / "shared/themes/catppuccin" / source_name).read_bytes(),
                )


class GenerationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name)
        for name in (
            "regen-all-themes.sh", "generate-theme-configs.sh", "regen-nemo-css.py",
            "theme_opacity.py", "check-theme-generation.py",
        ):
            shutil.copy2(SRC / name, self.source / name)
        self.themes = self.source / "shared/themes"
        shutil.copytree(SRC / "shared/themes/_templates", self.themes / "_templates")
        self.theme = self.themes / "fixture"
        self.theme.mkdir()
        self.palette = self.theme / "colors.toml"
        shutil.copy2(SRC / "shared/themes/catppuccin/colors.toml", self.palette)

    def generate(self, *args):
        return subprocess.run(
            ["bash", str(self.source / "regen-all-themes.sh"), *args],
            text=True, capture_output=True, timeout=30,
        )

    def snapshot(self):
        return {
            str(path.relative_to(self.themes)): path.read_bytes()
            for path in self.themes.rglob("*") if path.is_file()
        }

    def test_clean_check_and_drift_detection_never_write(self):
        result = self.generate()
        self.assertEqual(result.returncode, 0, result.stderr)
        before = self.snapshot()
        result = self.generate("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)
        target = self.theme / "nemo.css"
        target.write_text(target.read_text() + "/* local edit */\n")
        before = self.snapshot()
        result = self.generate("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("fixture/nemo.css", result.stderr)
        self.assertEqual(self.snapshot(), before)
        target.unlink()
        result = self.generate("--check")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(target.exists())

    def test_invalid_palette_fails_before_any_output_changes(self):
        self.assertEqual(self.generate().returncode, 0)
        self.palette.write_text(self.palette.read_text().replace(
            'app_background_opacity = "0.50"', 'app_background_opacity = "nan"'
        ))
        before = self.snapshot()
        for args in ((), ("--check",)):
            result = self.generate(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("app_background_opacity", result.stderr)
            self.assertEqual(self.snapshot(), before)

    def test_old_custom_themes_fallback_and_opaque_reversibility(self):
        original = self.palette.read_text()
        for app, popup, expected in (
            (None, '"0.50"', "0.50"),
            (None, None, "1.0"),
            ('"1.0"', '"0.50"', "1.0"),
            ("0.25", '"0.50"', "0.25"),
            ('"0.50"', '"0.50"', "0.50"),
        ):
            with self.subTest(app=app, popup=popup):
                text = re.sub(r"(?m)^(app_background_opacity|popup_opacity).*\n", "", original)
                if app is not None:
                    text += f"\napp_background_opacity = {app}\n"
                if popup is not None:
                    text += f"\npopup_opacity = {popup}\n"
                self.palette.write_text(text)
                result = self.generate()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(
                    f"$theme-app-background-opacity: {expected};",
                    (self.theme / "eww-colors.scss").read_text(),
                )
                self.assertIn(
                    f"alpha(#1e1e2e, {expected})",
                    (self.theme / "nemo.css").read_text(),
                )

    def test_nemo_generation_errors_exit_nonzero(self):
        self.palette.write_text(re.sub(
            r"(?m)^bg_lighter.*\n", "", self.palette.read_text()
        ))
        result = self.generate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bg_lighter", result.stderr)


if __name__ == "__main__":
    unittest.main()
