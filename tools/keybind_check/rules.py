"""Static keybinding rules: everything that can be decided without a compositor.

A rule reports a finding only when a bind is certainly broken: the loader drops or
rewrites it, Hyprland rejects its keys, the scrolling layout does not know its message,
or it runs a command nothing ships. The rules work on the loader's own view of each bind
(an `Entry`), so they judge what Hyprland actually receives, not just what the file says.
"""
from __future__ import annotations

import dataclasses
import re
import shlex
import shutil
from pathlib import Path

from . import model, xkb
from .loader import CLOSURE

BIN_DIR = model.ROOT / "src/shared/bin"
APP_BUNDLE = model.ROOT / "src/shared/lib/smplos-app-bundle.sh"
PACKAGE_LISTS = (
    model.ROOT / "src/shared/packages.txt",
    model.ROOT / "src/shared/packages-aur.txt",
    model.ROOT / "src/compositors/hyprland/packages.txt",
)

DIRECTIONS = frozenset(("l", "r", "u", "d", "left", "right", "up", "down"))
FIT_TARGETS = frozenset(("active", "expand", "all", "toend", "tobeg", "visible"))
NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)\Z")
INT_PAIR = re.compile(r"-?\d+\s+-?\d+\Z", re.ASCII)
SIGNED_NUMBER = re.compile(r"[+-]\d+\Z")
WORKSPACE = re.compile(
    r"(?:\d+|[+-]\d+|[emr](?:[+-]|~)\d+|previous|previous_per_monitor|empty[nm]*"
    r"|special(?::\S+)?|name:\S.*)\Z")
MOUSE_BUTTONS = range(272, 288)  # BTN_MOUSE (0x110) up to, but excluding, BTN_JOYSTICK

# What the scrolling layout accepts, from CScrollingAlgorithm::layoutMsg in Hyprland 0.56.
_COLUMN_STEP = ("+col", "-col", "col")
LAYOUT_GRAMMAR = {
    "move": (lambda a: len(a) == 1 and (a[0] in _COLUMN_STEP or bool(NUMBER.match(a[0]))),
             "+col | -col | col | <number>"),
    "colresize": (lambda a: (len(a) == 2 and a[0] == "all" and bool(NUMBER.match(a[1])))
                  or (len(a) == 1 and (a[0] in ("+conf", "-conf") or bool(NUMBER.match(a[0])))),
                  "all <width> | +conf | -conf | [+-]<number> | <width>"),
    "fit": (lambda a: len(a) == 1 and a[0] in FIT_TARGETS, "|".join(sorted(FIT_TARGETS))),
    "focus": (lambda a: len(a) == 1 and a[0][:1] in tuple("lrudtb"), "l | r | u | d | t | b"),
    "promote": (lambda a: not a, "no argument"),
    "consume": (lambda a: not a, "no argument"),
    "expel": (lambda a: not a, "no argument"),
    "center": (lambda a: not a, "no argument"),
    "fit_into_view": (lambda a: not a, "no argument"),
    "consume_or_expel": (lambda a: len(a) == 1 and a[0] in ("prev", "next"), "prev | next"),
    "swapcol": (lambda a: len(a) == 1 and a[0] in ("l", "r"), "l | r"),
    "inhibit_scroll": (lambda a: len(a) <= 1, "at most one argument"),
}

# Commands every install has; anything else must be provided by this repository.
BASE_COMMANDS = frozenset("""
    sh bash env echo printf true false test [ sleep kill pkill pgrep cat grep sed awk cut tr
    date mkdir rm cp mv ln ls touch readlink dirname basename xargs timeout nohup setsid
    command exec nice stdbuf
""".split())
# Commands whose package is not named after them (the usual case needs no entry).
PACKAGE_FOR_COMMAND = {
    "hyprctl": "hyprland", "dunstctl": "dunst-smplos", "dunst": "dunst-smplos",
    "nemo": "nemo-smpl",
    "wl-copy": "wl-clipboard", "wl-paste": "wl-clipboard", "rofi": "rofi-wayland",
}

_KEYWORDS = frozenset(("if", "then", "else", "elif", "do", "while", "until", "!", "{", "time"))
_CLOSERS = frozenset(("fi", "done", "esac", "}"))
_WRAPPERS = frozenset(("exec", "env", "command", "nohup", "setsid", "timeout", "nice", "stdbuf"))
_SHELLS = frozenset(("sh", "bash", "dash", "zsh"))
_PUNCTUATION = frozenset("&|;()<>")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


ERROR, WARNING = "error", "warning"
# Rules whose problem is silent or cosmetic rather than a bind that certainly fails.
WARNING_RULES = frozenset((
    "flags", "description", "modifiers-repeat", "ignored-argument", "exec-args", "exec-parse",
))


@dataclasses.dataclass(frozen=True)
class Finding:
    rule: str
    where: str
    message: str
    label: str = ""
    severity: str = ERROR

    def __str__(self):
        label = f" {self.label}:" if self.label else ""
        return f"{self.where}:{label} {self.severity}[{self.rule}] {self.message}"


def finding(rule, where, message, label="", severity=None):
    return Finding(rule, where, message, label, severity or (WARNING if rule in WARNING_RULES else ERROR))


def errors(findings):
    return [item for item in findings if item.severity == ERROR]


# ── Shell commands ──────────────────────────────────────────────────────────

def _tokens(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def _is_checkable(word):
    return not (word == "$" or word.startswith(("$", "~", "/", ".")) or "/" in word)


def command_words(command, paths=False):
    """Command names a shell would run for `command`; raises ValueError if it will not parse.

    Words that are paths or variables ("/usr/bin/x", "$EDITOR") are left out unless `paths`.
    """
    tokens = _tokens(command)
    found, expect, wrapper = [], True, None
    for index, token in enumerate(tokens):
        if set(token) <= _PUNCTUATION:
            expect, wrapper = True, None
            continue
        if not expect or token in _KEYWORDS or token in _CLOSERS or _ASSIGNMENT.match(token):
            continue
        if wrapper and (token.startswith("-") or (wrapper == "timeout" and re.fullmatch(r"\d+[smhd]?", token))):
            continue
        if paths or _is_checkable(token):
            found.append(token)
        if token in _WRAPPERS:
            wrapper = token
            continue
        expect = False
        if token in _SHELLS:
            rest = []
            for follower in tokens[index + 1:]:
                if set(follower) <= _PUNCTUATION:
                    break
                rest.append(follower)
            for position, follower in enumerate(rest[:-1]):
                if re.fullmatch(r"-[a-z]*c[a-z]*", follower):
                    found.extend(command_words(rest[position + 1], paths))
                    break
    return found


def hyprctl_expressions(command):
    """(verb, Lua expression) pairs `hyprctl dispatch` / `hyprctl eval` receive inside a command."""
    tokens, found, expect = _tokens(command), [], True
    for index, token in enumerate(tokens):
        if set(token) <= _PUNCTUATION:
            expect = True
        elif expect and token == "hyprctl":
            for offset in range(index + 1, len(tokens)):
                if set(tokens[offset]) <= _PUNCTUATION:
                    break
                if tokens[offset] in ("dispatch", "eval") and offset + 1 < len(tokens):
                    found.append((tokens[offset], tokens[offset + 1]))
                    break
            expect = False
        else:
            expect = False
    return found


def _read_packages(paths):
    names = set()
    for path in paths:
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                parts = line.split("#", 1)[0].split()
                if parts:
                    names.add(parts[0])
    return names


def _bundle_names():
    text = APP_BUNDLE.read_text(encoding="utf-8") if APP_BUNDLE.is_file() else ""
    apps = re.search(r"SMPLOS_APP_BINS=\(([^)]*)\)", text)
    xr = re.search(r"smplos_xr_script_name\(\)\s*\{\s*case[^\n]*\n\s*([\w|-]+)\)", text)
    return (set(apps.group(1).split()) if apps else set(),
            set(xr.group(1).split("|")) if xr else set())


class RepoResolver:
    """Resolves command names against what this repository ships or installs."""

    severity = ERROR

    def __init__(self):
        self.scripts = {
            path.name for path in BIN_DIR.iterdir()
            if path.is_file() and path.read_bytes()[:2] == b"#!"
        } if BIN_DIR.is_dir() else set()
        self.apps, self.xr = _bundle_names()
        self.packages = _read_packages(PACKAGE_LISTS)

    def resolve(self, word):
        if word in BASE_COMMANDS:
            return "base command"
        if word in self.scripts:
            return f"script src/shared/bin/{word}"
        if word in self.apps:
            return "smpl-apps binary"
        if word in self.xr:
            return "XR script"
        package = PACKAGE_FOR_COMMAND.get(word, word)
        if package in self.packages:
            return f"package {package}"
        return None

    def missing(self, word):
        package = PACKAGE_FOR_COMMAND.get(word, word)
        return (f"'{word}' is not a script in src/shared/bin, an smpl-apps or XR binary, or "
                f"provided by package '{package}' (add that package to a packages*.txt list, "
                f"or map the command in PACKAGE_FOR_COMMAND)")


class HostResolver:
    """Resolves command names on this machine, for auditing a live bind file."""

    # The checker's PATH can differ from the compositor session's, so a miss is only a hint.
    severity = WARNING

    def resolve(self, word):
        return "on PATH" if shutil.which(word) else None

    def missing(self, word):
        return f"'{word}' is not on this machine's PATH"


# ── Per-bind rules ──────────────────────────────────────────────────────────

def _modifier_problems(bind):
    problems, seen = [], set()
    for token in model.words(bind.mods):
        canonical = model.MOD_NAMES.get(token)
        if canonical is None:
            hint = " (modifier names are case-sensitive)" if token.upper() in model.MOD_NAMES else ""
            if token.startswith("$"):
                hint = " (bindings_loader.lua does not expand hyprlang variables)"
            problems.append(("modifiers", f"unknown modifier '{token}'{hint}"))
        elif canonical in seen:
            problems.append(("modifiers-repeat", f"modifier '{token}' is listed twice"))
        else:
            seen.add(canonical)
    return problems


def _key_problem(bind):
    key = bind.key_name
    lowered = key.lower()
    if not key:
        return "empty key"
    if re.search(r"[\s+]", key):
        return f"key '{key}' contains whitespace or '+'"
    if lowered in model.SPECIAL_KEYS:
        return None
    if lowered.startswith("mouse:"):
        button = lowered[6:]
        if not button.isdigit() or int(button) not in MOUSE_BUTTONS:
            return f"'{key}' is not a mouse button (expected mouse:272 to mouse:287)"
        return None
    if lowered.startswith("switch:"):
        return None if len(lowered) > 7 else "switch: needs a device name"
    if lowered.startswith("code:"):
        return None if lowered[5:].isdigit() else f"'{key}' is not a keycode (code:<number>)"
    if lowered == "catchall":
        return None if bind.submap else "catchall is only valid inside a submap"
    if xkb.available() and not xkb.keysym(key):
        return f"unknown key '{key}' (not a libxkbcommon keysym)"
    return None


def _hygiene_problems(bind):
    problems = []
    for name, field in (("modifiers", bind.mods), ("key", bind.key), ("dispatcher", bind.dispatcher or "")):
        if "#" in field:
            problems.append(("comment", f"'#' in the {name} field: the loader does not strip comments"))
    if bind.dispatcher != "exec" and "#" in bind.raw_arg:
        problems.append(("comment", "inline '#' comment becomes part of the argument "
                                    "(bindings_loader.lua only skips whole-line comments)"))
    return problems


def syntax_problems(bind):
    problems = []
    unknown = sorted(set(bind.flags) - set(model.LOADER_FLAGS))
    if unknown:
        problems.append(("flags", f"flag letter(s) {', '.join(unknown)} in '{bind.keyword}' are "
                                  f"silently ignored by bindings_loader.lua"))
    if "e" in bind.flags and "r" in bind.flags:
        problems.append(("flags", "repeat (e) cannot be combined with release (r)"))
    if not bind.registered:
        need = "mods, key, description, dispatcher" if bind.has_desc else "mods, key, dispatcher"
        problems.append(("fields", f"expected {need}; bindings_loader.lua silently drops this bind"))
        return problems
    if bind.has_desc and not bind.desc:
        problems.append(("description", f"'{bind.keyword}' needs a non-empty description"))
    problems += _modifier_problems(bind)
    key = _key_problem(bind)
    if key:
        problems.append(("key", key))
    return problems + _hygiene_problems(bind)


def layout_problem(message):
    parts = message.split(" ")
    if "" in parts:
        return f"layout message {message!r} has an empty word (stray space)"
    verb, args = parts[0], parts[1:]
    if verb not in LAYOUT_GRAMMAR:
        return (f"'{verb}' is not a scrolling layout message "
                f"(known: {', '.join(sorted(LAYOUT_GRAMMAR))})")
    accepts, usage = LAYOUT_GRAMMAR[verb]
    if not accepts(args):
        return f"'{verb}' takes {usage}, not '{' '.join(args)}'"
    return None


ARG_RULES = {}


def _rule(*dispatchers):
    def register(function):
        for name in dispatchers:
            ARG_RULES[name] = function
        return function
    return register


@_rule("exec")
def _exec_dispatcher(bind, call):
    return []  # judged by the shell-command rules


@_rule("killactive", "togglefloating", "pseudo", "pin", "togglegroup", "moveoutofgroup", "exit")
def _takes_no_argument(bind, call):
    return [("ignored-argument", f"'{bind.dispatcher}' takes no argument; '{bind.raw_arg}' is ignored")] \
        if bind.raw_arg else []


@_rule("fullscreen")
def _fullscreen(bind, call):
    return [] if bind.raw_arg in ("", "0", "1", "2") else \
        [("argument", f"fullscreen mode '{bind.raw_arg}' must be 0, 1 or 2")]


@_rule("fullscreenstate", "resizeactive")
def _integer_pair(bind, call):
    return [] if INT_PAIR.match(bind.raw_arg) else \
        [("argument", f"'{bind.dispatcher}' needs two integers ('<a> <b>'); "
                      f"the loader silently uses defaults for '{bind.raw_arg}'")]


def _mouse_bound(bind):
    return bind.key_name.lower().startswith("mouse:")


@_rule("movewindow")
def _movewindow(bind, call):
    arg = bind.raw_arg
    if not arg:
        return [] if _mouse_bound(bind) else \
            [("argument", "'movewindow' without an argument is the mouse drag; bind it to a mouse button")]
    if arg.startswith("mon:"):
        return [] if len(arg) > 4 else [("argument", "'mon:' needs a monitor")]
    return [] if arg in DIRECTIONS else \
        [("argument", f"'{arg}' is not a direction (l r u d) or mon:<monitor>")]


@_rule("resizewindow")
def _resizewindow(bind, call):
    if not bind.raw_arg:
        return [] if _mouse_bound(bind) else \
            [("argument", "'resizewindow' without an argument is the mouse resize; bind it to a mouse button")]
    return _integer_pair(bind, call)


@_rule("changegroupactive")
def _changegroupactive(bind, call):
    return [] if bind.raw_arg in ("", "f", "b") else \
        [("argument", f"'{bind.raw_arg}' must be f (forward) or b (back)")]


@_rule("moveintogroup", "movefocus", "swapwindow")
def _direction(bind, call):
    return [] if bind.raw_arg in DIRECTIONS else \
        [("argument", f"'{bind.raw_arg}' is not a direction (l r u d)")]


@_rule("movecurrentworkspacetomonitor")
def _monitor(bind, call):
    return [] if bind.raw_arg else [("argument", "needs a monitor or direction")]


@_rule("togglespecialworkspace")
def _special(bind, call):
    return []


@_rule("layoutmsg", "togglesplit")
def _layout(bind, call):
    message = call.args[0] if call.name == "layout" and call.args else bind.raw_arg
    problem = layout_problem(message if isinstance(message, str) else "")
    return [("layout", problem)] if problem else []


@_rule("workspace", "movetoworkspace", "movetoworkspacesilent")
def _workspace(bind, call):
    arg = bind.raw_arg
    if not WORKSPACE.match(arg):
        return [("workspace", f"'{arg}' is not a workspace selector "
                              f"(N, +N, -N, e+N, m+N, r+N, previous, empty, special[:name], name:x)")]
    if call.name in ("focus", "window.move") and call.args and SIGNED_NUMBER.match(arg):
        selector = call.args[0].get("workspace") if isinstance(call.args[0], dict) else None
        if selector != arg:
            return [("workspace", f"relative workspace '{arg}' reaches Hyprland as {selector!r}, "
                                  f"which selects an absolute workspace")]
    return []


@_rule("submap")
def _submap(bind, call):
    return [] if bind.raw_arg else [("argument", "'submap' needs a name or 'reset'")]


@_rule("windowcycle")
def _windowcycle(bind, call):
    return [] if bind.raw_arg in ("", "prev") else \
        [("argument", f"'{bind.raw_arg}' must be empty or 'prev'")]


def _exec_problems(bind, call, resolver):
    command = call.args[0] if call.args and isinstance(call.args[0], str) else ""
    problems = []
    if bind.dispatcher == "exec" and call.name == "exec_cmd" and command != bind.raw_arg:
        problems.append(("exec-args", f"the loader rewrites the command: the file has "
                                      f"{bind.raw_arg!r} but hl.exec_cmd receives {command!r} "
                                      f"(it re-joins comma-separated fields)"))
    if not command.strip():
        return problems + [("exec-empty", "empty command")]
    try:
        words = command_words(command)
        expressions = hyprctl_expressions(command)
    except ValueError as error:
        return problems + [("exec-parse", f"command does not parse as shell: {error}")]
    if not words:
        problems.append(("exec-empty", "command runs nothing"))
    for word in dict.fromkeys(words):
        if resolver.resolve(word) is None:
            problems.append(("exec-target", resolver.missing(word), resolver.severity))
    for verb, expression in expressions:
        if verb == "dispatch" and not expression.lstrip().startswith("hl."):
            problems.append(("hyprctl-expression", f"'hyprctl dispatch' takes a Lua expression "
                                                   f"starting with hl.; got {expression!r}"))
    return problems


def check_bind(bind, call, resolver):
    """Findings for one bind line; `call` is None when the loader dropped the line."""
    problems = syntax_problems(bind)
    if call is not None:
        if call.name == "no_op":
            problems.append(("dispatcher", f"unmapped dispatcher '{bind.dispatcher}': "
                                           f"bindings_loader.lua binds it as a no-op"))
        rule = ARG_RULES.get(bind.dispatcher)
        if rule:
            problems += rule(bind, call)
        if call.name == "exec_cmd":
            problems += _exec_problems(bind, call, resolver)
    return [finding(name, bind.where, message, bind.label, *severity)
            for name, message, *severity in problems]


# ── Set-level rules ─────────────────────────────────────────────────────────

def _place(call, where):
    return where.get(id(call)) or model.display_path(model.POPUP_WATCHERS)


def _describe(call, where):
    return f"{_place(call, where)}, {call.name}"


def duplicate_chords(recording, entries):
    """The same chord bound twice would run both actions."""
    where = {id(entry.call): entry.bind.where for entry in entries}
    first, findings = {}, []
    for call in recording.calls:
        earlier = first.setdefault(call.chord, call)
        if earlier is call:
            continue
        findings.append(finding(
            "duplicate-chord", _place(call, where),
            f"'{call.label}' is already bound at {_describe(earlier, where)}; both would run",
            call.label))
    return findings


def submap_problems(parsed):
    binds = model.all_binds(parsed)
    blocks = [block for item in parsed for block in item.submaps]
    defined = {block.name for block in blocks}
    findings = []
    for block in blocks:
        if not block.closed:
            findings.append(finding("submap", f"line {block.line}",
                                    f"submap '{block.name}' is not closed with 'submap = reset'"))
    for bind in binds:
        if bind.dispatcher == "submap" and bind.arg not in defined | {"reset"}:
            findings.append(finding("submap", bind.where, f"enters undefined submap '{bind.arg}'",
                                    bind.label))
    for name in sorted(defined):
        inside = [bind for bind in binds if bind.submap == name]
        if not any(b.dispatcher == "submap" and b.arg == name and not b.submap for b in binds):
            findings.append(finding("submap", name, f"submap '{name}' is never entered"))
        if not any(b.dispatcher == "submap" and b.arg == "reset" for b in inside):
            findings.append(finding("submap", name, f"submap '{name}' has no 'submap, reset' exit"))
    return findings


# ── Repository wiring ───────────────────────────────────────────────────────

EMERGENCY_BINDS = {
    ("CTRL", "ALT", "T"): "terminal",
    ("CTRL", "ALT", "U"): "smplos-update --mode full",
    ("CTRL", "ALT", "R"): "hyprctl reload",
    ("SUPER", "CTRL", "D"): "screen-recover",
    ("CTRL", "ALT", "A"): "app-center",
}


def loader_dispatchers():
    text = model.LOADER.read_text(encoding="utf-8")
    return set(re.findall(r'dispatcher == "(\w+)"', text))


def hyprland_load_order():
    """Basenames hyprland.lua loads as bind files, in order, then popup_watchers."""
    text = re.sub(r"--[^\n]*", "", model.HYPRLAND_LUA.read_text(encoding="utf-8"))
    paths = dict(re.findall(r'^local (\w+)\s*=\s*(?:home\s*\.\.\s*)?"([^"]+)"', text, re.M))
    order = []
    for match in re.finditer(r'bindings\.load\((\w+)\)|require\("popup_watchers"\)', text):
        if match.group(1):
            order.append(Path(paths.get(match.group(1), match.group(1))).name)
        else:
            order.append("popup_watchers")
    return order


def repo_problems():
    findings = []
    where = model.display_path(model.HYPRLAND_LUA)
    expected = ["bindings.conf", "bindings.conf", "messenger-bindings.conf",
                "xr-workspace.conf", "emergency.conf", "popup_watchers"]
    actual = hyprland_load_order()
    if actual != expected:
        findings.append(finding("load-order", where,
                                f"bind files load as {actual}, expected {expected}: emergency.conf "
                                f"must load after every other bind file, popup_watchers last"))
    looknfeel = model.LOOKNFEEL_LUA.read_text(encoding="utf-8")
    if not re.search(r'^\s*layout\s*=\s*"scrolling"', looknfeel, re.M):
        findings.append(finding("layout", model.display_path(model.LOOKNFEEL_LUA),
                                "general.layout is not \"scrolling\", but the binds send "
                                "scrolling layout messages"))
    covered, handled = loader_dispatchers(), set(ARG_RULES)
    for name in sorted(covered - handled):
        findings.append(finding("coverage", model.display_path(model.LOADER),
                                f"loader dispatcher '{name}' has no argument rule in "
                                f"tools/keybind_check/rules.py"))
    for name in sorted(handled - covered):
        findings.append(finding("coverage", "tools/keybind_check/rules.py",
                                f"argument rule for '{name}' but bindings_loader.lua has no such "
                                f"dispatcher"))
    return findings


def emergency_problems(parsed):
    found = {}
    for item in parsed:
        if item.source.name == "emergency":
            for bind in item.binds:
                found[tuple(sorted(model.MOD_NAMES.get(m, m) for m in model.words(bind.mods))
                            + [bind.key])] = bind.arg
    findings = []
    for chord, command in EMERGENCY_BINDS.items():
        key = tuple(sorted(chord[:-1]) + [chord[-1]])
        if found.get(key) != command:
            findings.append(finding("emergency", "emergency.conf",
                                    f"{'+'.join(chord)} must run '{command}', found "
                                    f"{found.get(key)!r}"))
    return findings


def check_set(parsed, recording, entries, resolver, with_repo=True):
    """Every finding for a loaded bind set (one policy variant)."""
    by_bind = {id(entry.bind): entry.call for entry in entries}
    findings = []
    for bind in model.all_binds(parsed):
        findings += check_bind(bind, by_bind.get(id(bind)), resolver)
    findings += duplicate_chords(recording, entries)
    findings += submap_problems(parsed)
    if with_repo:
        findings += repo_problems() + emergency_problems(parsed)
    return findings
