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


def matches(match, props, tags):
    for key, value in match.items():
        if not value:
            continue
        if key == "tag":
            if value not in tags and value + "*" not in tags:
                return False
        elif key in ("fullscreen", "xwayland", "float", "pin"):
            if str(props[key]) != str(value):
                return False
        else:
            flags = re.I if "(?i)" in value else 0
            if re.fullmatch(value.replace("(?i)", ""), props.get(key, ""), flags) is None:
                return False
    return True


class RuleState:
    """Hyprland 0.56 opacity dependency-mask replay, not just last-match order.

    Window::refreshTitleClass reports TITLE|CLASS even for a title-only change.
    WindowRuleApplicator::propertiesChanged replays rules whose mask changed or
    whose effects were reset by the previously winning rule's property mask.
    """

    def __init__(self, rules, app, **properties):
        self.rules = rules
        self.tags = set(properties.pop("tags", ()))
        self.props = {"class": app, "title": "", "initial_title": "", "fullscreen": "0",
                      "content": "none", "xwayland": "0", "float": "0", "pin": "0", **properties}
        self.opacity = None
        self.opacity_mask = set()
        self.reapply(set(KEYS))

    def reapply(self, changed, **properties):
        self.props.update(properties)
        reset_opacity = bool(self.opacity_mask & changed)
        if reset_opacity:
            self.opacity = None
        for match, effects in self.rules:
            mask = {key for key, value in match.items() if value}
            if not (mask & changed or (reset_opacity and effects.get("opacity"))):
                continue
            if not matches(match, self.props, self.tags):
                continue
            self.apply(mask, effects)
        return self.opacity

    def apply(self, mask, effects):
        if effects.get("tag"):
            self.tags.add(effects["tag"].removeprefix("+") + "*")
        if effects.get("opacity"):
            self.opacity = effects["opacity"]
            self.opacity_mask = mask


def evaluate(rules, app, **properties):
    return RuleState(rules, app, **properties).opacity


class FullOpacityPolicyTests(unittest.TestCase):
    def test_opacity_rules_include_class_change_dependency(self):
        colors = {"opacity_active": "0.7", "opacity_inactive": "0.7",
                  "browser_opacity": "0.6", "messenger_opacity": "0.8"}
        providers = [conf_rules(colors)[0]]
        if shutil.which("lua"):
            providers.append(lua_rules(colors))
        for rules in providers:
            for match, effects in rules:
                if effects.get("opacity"):
                    self.assertTrue(match.get("class"), (match, effects))

    def test_incremental_model_reproduces_tag_only_title_regression(self):
        state = RuleState([
            ({"class": "^nemo$"}, {"tag": "+self-managed-alpha"}),
            ({"class": ".*"}, {"opacity": "0.7"}),
            ({"tag": "self-managed-alpha"}, {"opacity": "1.0"}),
        ], "nemo")
        self.assertEqual(state.opacity, "1.0")
        self.assertEqual(state.reapply({"title", "class"}, title="new folder"), "0.7")
        self.assertIn("self-managed-alpha*", state.tags)

    def test_conf_incremental_opacity_survives_title_and_theme_changes(self):
        self.check_incremental("conf")

    @unittest.skipUnless(shutil.which("lua"), "Lua runtime unavailable")
    def test_lua_incremental_opacity_survives_title_and_theme_changes(self):
        self.check_incremental("lua")

    def check_incremental(self, provider):
        neutral = "1.0 override 1.0 override 1.0 override"
        native = ("settings", "app-center", "webapp-center", "sync-center", "start-menu",
                  "notif-center", "smpl-calendar", "smpl-calendar-details", "hints-overlay",
                  "nemo", "org.Nemo.nemo-float", "grafium", "st", "st-256color", "terminal", "rofi")
        cases = [(app, {}, neutral) for app in native]
        cases += [(app, props, neutral) for app, props in (
            ("mpv", {}), ("steam_app_1234", {}),
            ("brave-browser", {"title": "Picture-in-Picture"}),
            ("brave-browser", {"fullscreen": "1"}),
            ("brave-browser", {"content": "video"}),
        )]
        cases += [(app, {}, key) for app, key in (
            ("third-party-editor", "opacity_active"), ("brave-browser", "browser_opacity"),
            ("firefox", "browser_opacity"), ("signal", "messenger_opacity"),
        )]
        for app, props, expected in cases:
            state = None
            for alpha in ("0.7", "1.0", "0.3", "0.7"):
                colors = {"opacity_active": alpha, "opacity_inactive": alpha,
                          "browser_opacity": "0.6", "messenger_opacity": "0.8"}
                rules = conf_rules(colors)[0] if provider == "conf" else lua_rules(colors)
                target = (f"{colors[expected]} override {colors[expected]} override"
                          if expected in colors else expected)
                with self.subTest(provider=provider, app=app, props=props, alpha=alpha):
                    fresh = RuleState(rules, app, **props)
                    self.assertEqual(fresh.opacity, target)
                    if state is None:
                        state = fresh
                    else:
                        state.rules = rules
                        self.assertEqual(state.reapply(set(KEYS)), target)
                    for window in (state, fresh):
                        for index in range(4):
                            # PiP title stays matched; native titles can change freely.
                            title = props.get("title", f"folder-{index}")
                            self.assertEqual(window.reapply({"title", "class"}, title=title), target)
                            self.assertEqual(window.reapply({"focus"}), target)

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
