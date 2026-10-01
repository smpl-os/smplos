"""Evaluate window-rule sequences from both actual compositor entrypoints."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from test_theme_alpha import SRC, read_colors

HYPR = SRC / "compositors/hyprland/hypr"
KEYS = ("class", "tag", "title", "initial_title", "fullscreen", "content", "xwayland", "float", "pin")


def variables(colors):
    return {
        "themeOpacityActive": colors["opacity_active"],
        "themeOpacityInactive": colors["opacity_inactive"],
        "themeBrowserOpacity": colors["browser_opacity"],
        "themeMessengerOpacity": colors["messenger_opacity"],
    }


def conf_rules(colors):
    rules = []
    loaded = []
    values = variables(colors)

    def load(path):
        loaded.append(path.name)
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith("source = ~/.config/hypr/"):
                child = HYPR / line.split("~/.config/hypr/", 1)[1]
                if child.is_file():
                    load(child)
            elif line.startswith("windowrule = "):
                match = {}
                effects = {}
                for part in line.removeprefix("windowrule = ").split(", "):
                    key, _, value = part.partition(" ")
                    if key.startswith("match:"):
                        match[key.removeprefix("match:")] = value
                    elif key in ("opacity", "tag"):
                        effects[key] = re.sub(r"\$(\w+)", lambda m: values[m[1]], value)
                if effects:
                    rules.append((match, effects))
    load(HYPR / "hyprland.conf")
    return rules, loaded


def lua_rules(colors):
    serialized = ",".join(f'["{key}"]={json.dumps(value)}' for key, value in variables(colors).items())
    harness = r'''
local root = arg[1]
package.path = root .. "/?.lua;" .. package.path
package.preload.theme = function() return THEME end
for _, name in ipairs({"workspace_policy", "envs", "input", "looknfeel",
                      "aspect_column", "popup_watchers", "autostart"}) do
    package.preload[name] = function() return {} end
end
for _, name in ipairs({"monitors_loader", "bindings_loader"}) do
    package.preload[name] = function() return {load=function() end} end
end
hl = {monitor=function() end, layer_rule=function() end,
      window_rule=function(rule)
    if not rule.tag and not rule.opacity then return end
    local output = {}
    for _, key in ipairs({"class","tag","title","initial_title","fullscreen",
                           "content","xwayland","float","pin"}) do
        output[#output+1] = tostring(rule.match[key] or "")
    end
    output[#output+1] = rule.tag or ""
    output[#output+1] = rule.opacity or ""
    print(table.concat(output, "\t"))
end}
-- The real entrypoint prepends HOME's package.path; override HOME only here.
local getenv = os.getenv
os.getenv = function(name) if name == "HOME" then return "/nonexistent-fixture-home" end return getenv(name) end
dofile(root .. "/hyprland.lua")
'''
    result = subprocess.run(
        ["lua", "-", str(HYPR)], input=harness.replace("THEME", "{" + serialized + "}"),
        text=True, capture_output=True, timeout=5,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return [
        (dict(zip(KEYS, fields[:len(KEYS)])), {"tag": fields[-2], "opacity": fields[-1]})
        for fields in (line.split("\t") for line in result.stdout.splitlines())
    ]


def evaluate(rules, app, **properties):
    tags = set(properties.pop("tags", ()))
    props = {"class": app, "title": "", "initial_title": "", "fullscreen": "0",
             "content": "none", "xwayland": "0", "float": "0", "pin": "0", **properties}
    opacity = None
    for match, effects in rules:
        applies = True
        for key, value in match.items():
            if not value:
                continue
            if key == "tag":
                applies &= value in tags
            elif key in ("fullscreen", "xwayland", "float", "pin"):
                applies &= str(props[key]) == str(value)
            else:
                flags = re.I if "(?i)" in value else 0
                applies &= re.fullmatch(value.replace("(?i)", ""), props.get(key, ""), flags) is not None
        if not applies:
            continue
        if effects.get("tag"):
            tags.add(effects["tag"].removeprefix("+"))
        if effects.get("opacity"):
            opacity = effects["opacity"]
    return opacity


class FullOpacityPolicyTests(unittest.TestCase):
    def test_iso_copies_entire_compositor_tree_to_live_and_installer_payload(self):
        builder = (SRC / "builder/build.sh").read_text()
        self.assertIn('cp -r "$compositor_dir/hypr/"* "$skel/.config/hypr/"', builder)
        self.assertIn('cp -r "$compositor_dir/hypr/"* "$airootfs/root/smplos/config/hypr/"', builder)

    def test_final_policy_loaded_last_in_both_entrypoints(self):
        self.assertEqual((HYPR / "hyprland.lua").read_text().strip().splitlines()[-1],
                         'require("opacity-policy")')
        self.assertEqual((HYPR / "hyprland.conf").read_text().strip().splitlines()[-1],
                         "source = ~/.config/hypr/opacity-policy.conf")

    def test_conf_sequence_stock_and_custom_roles_and_safety(self):
        self.check_sequences(("conf",))

    @unittest.skipUnless(shutil.which("lua"), "Lua runtime unavailable")
    def test_lua_sequence_stock_and_custom_roles_and_safety(self):
        self.check_sequences(("lua",))

    def check_sequences(self, providers):
        palettes = [read_colors(path) for path in (SRC / "shared/themes").glob("*/colors.toml")]
        palettes.append({"opacity_active": "0.3", "opacity_inactive": "0.3",
                         "browser_opacity": "0.6", "messenger_opacity": "0.7"})
        native = ("settings", "app-center", "webapp-center", "sync-center", "start-menu",
                  "notif-center", "smpl-calendar", "smpl-calendar-details", "hints-overlay",
                  "nemo", "org.Nemo.nemo-float", "grafium", "st", "st-256color", "terminal", "rofi")
        for index, colors in enumerate(palettes):
            for provider in providers:
                rules = conf_rules(colors)[0] if provider == "conf" else lua_rules(colors)
                with self.subTest(palette=index, provider=provider):
                    for app, key in (("code", "opacity_active"), ("third-party-editor", "opacity_active"),
                                     ("brave-browser", "browser_opacity"), ("firefox", "browser_opacity"),
                                     ("signal", "messenger_opacity"), ("brave-discord", "messenger_opacity"),
                                     ("brave-github.com", "messenger_opacity")):
                        self.assertEqual(evaluate(rules, app),
                                         f'{colors[key]} override {colors[key]} override', app)
                    neutral = "1.0 override 1.0 override 1.0 override"
                    for app in native:
                        self.assertEqual(evaluate(rules, app), neutral, app)
                        self.assertEqual(evaluate(rules, app, fullscreen="1"), neutral, app)
                        self.assertEqual(evaluate(rules, app, tags=("chromium-based-browser",)), neutral, app)
                    for app in ("mpv", "imv", "vlc", "steam", "steam_app_1234"):
                        self.assertEqual(evaluate(rules, app), neutral, app)
                        self.assertEqual(evaluate(rules, app, tags=("chromium-based-browser",)), neutral, app)
                    for app in ("code", "brave-browser", "firefox", "signal", "brave-discord"):
                        self.assertEqual(evaluate(rules, app, fullscreen="1"), neutral, app)
                    for content in ("photo", "video", "game"):
                        self.assertEqual(evaluate(rules, "brave-browser", content=content), neutral)
                    self.assertEqual(evaluate(rules, "brave-browser", title="Picture-in-Picture"), neutral)
                    self.assertEqual(evaluate(rules, "brave-browser",
                                             initial_title="youtube.com_/"), neutral)


if __name__ == "__main__":
    unittest.main()
