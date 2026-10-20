"""Migrations that bring existing installs in line with the stock keybinding changes."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
BINDINGS = ROOT / "src/shared/configs/smplos/bindings.conf"
HYPR = ROOT / "src/compositors/hyprland/hypr"
MIGRATE = ROOT / "src/shared/bin/smplos-migrate"
HYPRPICKER = ROOT / "migrations/20261019-153000-install-hyprpicker.sh"
POPUP = ROOT / "migrations/20261019-153100-remove-duplicate-popup-click-bind.sh"
SUPER_K = ROOT / "migrations/20261020-154500-super-k-settings.sh"

INSTALL = "-S --needed --noconfirm hyprpicker"
BIND = "bindn = , mouse:272, exec, popup-click-check"
BANNER = "# " + "=" * 76
NOTE = (
    "# Popup click-outside-to-dismiss (popup-click-check on every left click) is not",
    "# a keybinding: hypr/popup_watchers.lua registers it. Binding mouse:272 here as",
    "# well would run it twice per click.",
)
# The two comment headers that shipped above the bind, as literals on purpose: CI
# clones are shallow, and the migration must match what real files contain.
_HEAD = (BANNER, "# Popup click-outside-to-dismiss (start-menu, calendar)", BANNER,
         "# Non-consuming left-click watcher: every click runs popup-click-check, which")
SHIPPED_HEADERS = (
    _HEAD + ("# closes any open popup if the click landed outside it. Lives here (not in the",
             "# .lua loader) because Hyprland 0.54 loads the .conf config; the .lua mirror is",
             "# only used after the 0.55 migration. Internal \u2014 not shown in keybind-help."),
    _HEAD + ("# closes any open popup if the click landed outside it. Declared in bindings.conf",
             "# (the single source of truth); the .lua loader parses it into an hl.bind on",
             "# Hyprland 0.55+. Internal \u2014 not shown in keybind-help."),
)

# Super+K before and after the Settings repoint, as literals for the same reason.
OLD_K_BIND = "bindd = SUPER, K, Show keybindings, exec, keybind-help"
NEW_K_BIND = "bindd = SUPER, K, Show keybindings, exec, settings --tab keybindings &"
NEW_K_COMMENT = "# Keybinding help: Settings on the Keybindings tab, filter box focused"
OLD_K_COMMENTS = (
    "# Keybinding help (fuzzy searchable list of all shortcuts)",
    "# Keybinding help (substring-searchable list of all shortcuts)",
)

# Fake pacman: $STATE lists the installed packages and every call except -Q is logged
# to $CALLS. FAIL_INSTALL=1 fails the install, NO_EFFECT=1 "succeeds" without installing.
PACMAN = textwrap.dedent("""\
    #!/bin/bash
    case "$1" in
      -Q)  grep -qx -- "$2" "$STATE" && echo "$2 0.4.7-4" ;;
      -S*) echo "$*" >> "$CALLS"
           [[ "${FAIL_INSTALL:-0}" == 1 ]] && exit 1
           [[ "${NO_EFFECT:-0}" == 1 ]] && exit 0
           printf '%s\\n' "${@:2}" | grep -v '^-' >> "$STATE" ;;
      *)   echo "UNEXPECTED pacman $*" >> "$CALLS"; exit 99 ;;
    esac
    """)
SUDO = textwrap.dedent("""\
    #!/bin/bash
    [[ "$1" == pacman ]] || { echo "UNEXPECTED sudo $*" >> "$CALLS"; exit 99; }
    exec "$@"
    """)


def read(path):
    return path.read_text(encoding="utf-8")


def write(path, text):
    path.write_text(text, encoding="utf-8")


def block(*lines):
    return "".join(line + "\n" for line in lines)


def stock_with(replacement):
    """The current stock file with its popup note swapped for `replacement`."""
    note = block("#", *NOTE)
    text = read(BINDINGS)
    assert text.count(note) == 1, "the stock popup note moved; update this test"
    return text.replace(note, replacement)


def shipped(header=SHIPPED_HEADERS[1]):
    """The stock file as it looked while it still bound the popup watcher."""
    return stock_with("\n" + block(*header, BIND))


def before_super_k(comment=OLD_K_COMMENTS[1]):
    """The stock file as it looked while Super+K still ran keybind-help."""
    new = block(NEW_K_COMMENT, NEW_K_BIND)
    text = read(BINDINGS)
    assert text.count(new) == 1, "the stock Super+K bind moved; update this test"
    return text.replace(new, block(comment, OLD_K_BIND))


class PacmanHarness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home with spaces"
        self.home.mkdir()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        for name, body in (("pacman", PACMAN), ("sudo", SUDO)):
            write(bin_dir / name, body)
            (bin_dir / name).chmod(0o755)
        self.calls = self.root / "calls"
        self.state = self.root / "installed"
        write(self.state, "hyprland\nwl-clipboard\n")
        self.env = {key: value for key, value in os.environ.items() if key != "SMPLOS_SYSTEM_UPGRADED"}
        self.env.update(HOME=str(self.home), PATH=f"{bin_dir}:{os.environ['PATH']}",
                        CALLS=str(self.calls), STATE=str(self.state))

    def run_script(self, command, upgraded=None, **env):
        environment = {**self.env, **env}
        if upgraded is not None:
            environment["SMPLOS_SYSTEM_UPGRADED"] = upgraded
        return subprocess.run(command, env=environment, capture_output=True, text=True, timeout=20)

    def pacman_calls(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []


class HyprpickerMigrationTests(PacmanHarness):
    def migrate(self, **kwargs):
        return self.run_script(["bash", str(HYPRPICKER)], **kwargs)

    def test_an_installed_hyprpicker_is_left_alone(self):
        write(self.state, "hyprpicker\n")
        for upgraded in (None, "0", "1"):
            with self.subTest(upgraded=upgraded):
                result = self.migrate(upgraded=upgraded)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("already installed", result.stdout)
                self.assertEqual(self.pacman_calls(), [])

    def test_it_waits_for_the_complete_system_upgrade_instead_of_failing(self):
        for upgraded in (None, "", "0", "yes"):
            with self.subTest(upgraded=upgraded):
                result = self.migrate(upgraded=upgraded)
                self.assertEqual(result.returncode, 75, result.stdout + result.stderr)
                self.assertIn("deferred", result.stdout)
                self.assertEqual(self.pacman_calls(), [])

    def test_it_installs_only_hyprpicker_once_the_system_is_upgraded(self):
        result = self.migrate(upgraded="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.pacman_calls(), [INSTALL])
        self.assertIn("hyprpicker", self.state.read_text().split())
        self.assertEqual(self.migrate(upgraded="1").returncode, 0)
        self.assertEqual(self.pacman_calls(), [INSTALL])

    def test_a_failed_install_is_retried_on_the_next_update(self):
        for env in ({"FAIL_INSTALL": "1"}, {"NO_EFFECT": "1"}):
            with self.subTest(env=env):
                result = self.migrate(upgraded="1", **env)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("will retry", result.stdout)


class MigrationRunnerTests(PacmanHarness):
    """The real smplos-migrate runner, with both migrations in a fixture repository."""

    def setUp(self):
        super().setUp()
        self.data = self.home / "data"
        migrations = self.data / "repo/migrations"
        migrations.mkdir(parents=True)
        for path in (HYPRPICKER, POPUP, SUPER_K):
            shutil.copy(path, migrations / path.name)
        self.markers = self.home / ".local/state/smplos/migrations"

    def runner(self, phase, *options, **kwargs):
        return self.run_script(["bash", str(MIGRATE), "--phase", phase, *options],
                               SMPLOS_PATH=str(self.data), **kwargs)

    def test_hyprpicker_is_optional_and_the_popup_cleanup_is_core(self):
        optional = self.runner("optional", "--pending").stdout
        core = self.runner("core", "--pending").stdout
        self.assertIn(HYPRPICKER.stem, optional)
        self.assertNotIn(POPUP.stem, optional)
        self.assertIn(POPUP.stem, core)
        self.assertNotIn(HYPRPICKER.stem, core)

    def test_a_deferred_hyprpicker_is_not_a_failure_and_installs_after_the_upgrade(self):
        result = self.runner("optional")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("deferred", result.stdout)
        self.assertFalse((self.markers / HYPRPICKER.name).exists())
        self.assertEqual(self.pacman_calls(), [])
        result = self.runner("optional", upgraded="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.markers / HYPRPICKER.name).is_file())
        self.assertEqual(self.pacman_calls(), [INSTALL])

    def test_the_popup_cleanup_runs_in_the_core_phase_and_is_marked_done(self):
        result = self.runner("core")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.markers / POPUP.name).is_file())
        self.assertFalse((self.markers / HYPRPICKER.name).exists())
        self.assertEqual(self.pacman_calls(), [])

    def test_the_super_k_repoint_is_a_core_migration_that_runs_once(self):
        self.assertIn(SUPER_K.stem, self.runner("core", "--pending").stdout)
        self.assertNotIn(SUPER_K.stem, self.runner("optional", "--pending").stdout)
        bindings = self.home / ".config/smplos/bindings.conf"
        bindings.parent.mkdir(parents=True)
        old = before_super_k()
        write(bindings, old)
        result = self.runner("core")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(read(bindings), read(BINDINGS))
        self.assertTrue((self.markers / SUPER_K.name).is_file())
        write(bindings, old)
        self.runner("core")
        self.assertEqual(read(bindings), old)


class PopupClickBindMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home with spaces"
        self.hypr = self.home / ".config/hypr"
        self.primary = self.home / ".config/smplos/bindings.conf"
        self.fallback = self.hypr / "bindings.conf"
        self.primary.parent.mkdir(parents=True)
        self.hypr.mkdir(parents=True)
        self.install_lua()
        self.env = {**os.environ, "HOME": str(self.home)}
        self.current = read(BINDINGS)

    def install_lua(self):
        for name in ("hyprland.lua", "popup_watchers.lua"):
            shutil.copy(HYPR / name, self.hypr / name)

    def migrate(self, check=True):
        result = subprocess.run(["bash", str(POPUP)], env=self.env, capture_output=True,
                                text=True, timeout=20)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def backups(self):
        return sorted(self.home.rglob("*.pre-popup-bind.*"))

    def test_every_shipped_header_becomes_the_current_stock_file_with_a_verified_backup(self):
        for number, header in enumerate(SHIPPED_HEADERS, 1):
            with self.subTest(header=number):
                old = shipped(header)
                self.assertNotEqual(old, self.current)
                for path in (self.primary, self.fallback):
                    write(path, old)
                    path.chmod(0o640)
                result = self.migrate()
                self.assertEqual(result.stdout.count("Removed the duplicate popup click bind"), 2)
                for path in (self.primary, self.fallback):
                    self.assertEqual(read(path), self.current)
                    self.assertEqual(path.stat().st_mode & 0o777, 0o640)
                    saved = list(path.parent.glob("bindings.conf.pre-popup-bind.*"))
                    self.assertEqual([read(backup) for backup in saved], [old])
                    self.assertEqual(saved[0].stat().st_mode & 0o777, 0o640)
                self.assertEqual(self.migrate().stdout.count("nothing to do"), 2)
                self.assertEqual(len(self.backups()), 2)
                for backup in self.backups():
                    backup.unlink()

    def test_the_current_stock_file_and_missing_files_need_no_change(self):
        self.assertIn("No bindings.conf found", self.migrate().stdout)
        write(self.primary, self.current)
        self.assertIn("nothing to do", self.migrate().stdout)
        self.assertEqual(read(self.primary), self.current)
        self.assertEqual(self.backups(), [])

    def test_each_file_is_migrated_on_its_own(self):
        write(self.primary, self.current)
        write(self.fallback, shipped())
        self.migrate()
        self.assertEqual(read(self.fallback), self.current)
        self.assertEqual([path.parent for path in self.backups()], [self.hypr])

    def test_a_customized_header_is_kept_and_only_the_bind_is_replaced(self):
        edited = list(SHIPPED_HEADERS[1])
        edited[1] = "# My own popup notes"
        for header in (("# my notes on closing popups",), tuple(edited)):
            with self.subTest(header=header[0]):
                write(self.primary, shipped(header))
                self.migrate()
                self.assertEqual(read(self.primary), stock_with("\n" + block(*header, *NOTE)))

    def test_the_bind_is_found_anywhere_and_in_any_spacing(self):
        for line in (BIND, "bindn=,mouse:272,exec,popup-click-check", "bindn = , MOUSE:272, EXEC, popup-click-check"):
            with self.subTest(line=line):
                write(self.primary, self.current + "\n" + line + "\n")
                self.migrate()
                self.assertEqual(read(self.primary), self.current + "\n" + block(*NOTE))

    def test_every_matching_line_is_handled(self):
        write(self.primary, shipped() + "\n" + BIND + "\n")
        self.migrate()
        self.assertEqual(read(self.primary), self.current + "\n" + block(*NOTE))

    def test_customized_binds_are_kept(self):
        for line in (
            "bind = , mouse:272, exec, popup-click-check",
            "bindn = SUPER, mouse:272, exec, popup-click-check",
            "bindn = , mouse:272, exec, popup-click-check --verbose",
            "bindn = , mouse:272, exec, popup-click-check # mine",
            "bindn = , mouse:272, exec, other-command",
            "bindn = , mouse:273, exec, popup-click-check",
            "bindd = , mouse:272, Close popups, exec, popup-click-check",
        ):
            with self.subTest(line=line):
                write(self.primary, self.current + line + "\n")
                self.migrate()
                self.assertEqual(read(self.primary), self.current + line + "\n")
        self.assertEqual(self.backups(), [])

    def test_a_bind_inside_a_submap_is_kept_but_one_after_it_is_not(self):
        scoped = "submap = custom\n" + BIND + "\nsubmap = reset\n"
        write(self.primary, self.current + scoped)
        self.migrate()
        self.assertEqual(read(self.primary), self.current + scoped)
        write(self.primary, self.current + scoped + BIND + "\n")
        self.migrate()
        self.assertEqual(read(self.primary), self.current + scoped + block(*NOTE))

    def test_the_bind_stays_unless_the_lua_watcher_really_replaces_it(self):
        entry, watcher = self.hypr / "hyprland.lua", self.hypr / "popup_watchers.lua"
        require = 'require("popup_watchers")'
        entry_text, watcher_text = read(HYPR / "hyprland.lua"), read(HYPR / "popup_watchers.lua")
        self.assertEqual(entry_text.count(require), 1)
        broken = {
            "watcher module missing": lambda: watcher.unlink(),
            "entry point missing": lambda: entry.unlink(),
            "require commented out": lambda: write(entry, entry_text.replace(require, "-- " + require)),
            "require in a block comment": lambda: write(entry, entry_text.replace(require, f"--[==[ {require} ]==]")),
            "require removed": lambda: write(entry, entry_text.replace(require, "")),
            "bind in a block comment": lambda: write(watcher, f"--[==[\n{watcher_text}\n]==]\n"),
            "watcher on another button": lambda: write(watcher, watcher_text.replace('"mouse:272"', '"mouse:273"')),
            "watcher without the bind": lambda: write(watcher, "-- popup-click-check is only mentioned\n"),
        }
        old = shipped()
        for name, damage in broken.items():
            with self.subTest(name):
                self.install_lua()
                damage()
                write(self.primary, old)
                result = self.migrate()
                self.assertIn("keeping", result.stdout)
                self.assertEqual(read(self.primary), old)
                self.assertEqual(self.backups(), [])

    def test_equivalent_ways_to_load_the_watcher_count(self):
        entry = self.hypr / "hyprland.lua"
        text = read(HYPR / "hyprland.lua")
        for loader in ('pcall(require, "popup_watchers")', 'require "popup_watchers"',
                       "require( 'popup_watchers' )"):
            with self.subTest(loader=loader):
                write(entry, text.replace('require("popup_watchers")', loader))
                write(self.primary, shipped())
                self.migrate()
                self.assertEqual(read(self.primary), self.current)

    def test_crlf_line_endings_and_a_missing_final_newline_are_preserved(self):
        self.primary.write_bytes(shipped().replace("\n", "\r\n").encode())
        self.migrate()
        self.assertEqual(self.primary.read_bytes(), self.current.replace("\n", "\r\n").encode())
        write(self.primary, self.current + "\n" + BIND)
        self.migrate()
        self.assertEqual(read(self.primary), self.current + "\n" + "\n".join(NOTE))
        self.primary.write_bytes((self.current + "\n" + BIND).replace("\n", "\r\n").encode())
        self.migrate()
        self.assertEqual(self.primary.read_bytes(),
                         (self.current + "\n" + "\n".join(NOTE)).replace("\n", "\r\n").encode())

    def test_bytes_that_are_not_utf8_survive(self):
        tail = b"# caf\xe9 in latin-1\n"
        self.primary.write_bytes(shipped().encode() + tail)
        self.migrate()
        self.assertEqual(self.primary.read_bytes(), self.current.encode() + tail)

    def test_other_binding_files_are_not_touched(self):
        for name in ("messenger-bindings.conf", "emergency.conf"):
            write(self.hypr / name, shipped())
        self.migrate()
        for name in ("messenger-bindings.conf", "emergency.conf"):
            self.assertEqual(read(self.hypr / name), shipped())
        self.assertEqual(self.backups(), [])

    def test_symlinked_bindings_are_left_alone_without_failing_the_update(self):
        target = self.home / "dotfiles.conf"
        write(target, shipped())
        self.primary.symlink_to(target)
        result = self.migrate()
        self.assertIn("symlink", result.stdout)
        self.assertTrue(self.primary.is_symlink())
        self.assertEqual(read(target), shipped())
        self.assertEqual(self.backups(), [])

    @unittest.skipIf(os.geteuid() == 0, "root bypasses fixture directory permissions")
    def test_a_backup_failure_keeps_the_original_config(self):
        write(self.primary, shipped())
        self.primary.parent.chmod(0o500)
        try:
            result = self.migrate(check=False)
        finally:
            self.primary.parent.chmod(0o700)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(read(self.primary), shipped())
        self.assertEqual(list(self.primary.parent.glob("*.tmp.*")), [])


class SuperKSettingsMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home with spaces"
        self.hypr = self.home / ".config/hypr"
        self.primary = self.home / ".config/smplos/bindings.conf"
        self.fallback = self.hypr / "bindings.conf"
        self.primary.parent.mkdir(parents=True)
        self.hypr.mkdir(parents=True)
        self.env = {**os.environ, "HOME": str(self.home)}
        self.current = read(BINDINGS)

    def migrate(self, check=True):
        result = subprocess.run(["bash", str(SUPER_K)], env=self.env, capture_output=True,
                                text=True, timeout=20)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def backups(self):
        return sorted(self.home.rglob("*.pre-super-k-settings.*"))

    def kept(self, text):
        """Migrating `text` changes nothing and leaves no backup."""
        write(self.primary, text)
        self.migrate()
        self.assertEqual(read(self.primary), text)
        self.assertEqual(self.backups(), [])

    def test_every_shipped_comment_becomes_the_current_stock_file_with_a_verified_backup(self):
        for comment in OLD_K_COMMENTS:
            with self.subTest(comment=comment):
                old = before_super_k(comment)
                self.assertNotEqual(old, self.current)
                for path in (self.primary, self.fallback):
                    write(path, old)
                    path.chmod(0o640)
                result = self.migrate()
                self.assertEqual(result.stdout.count("SUPER+K now opens Settings"), 2)
                for path in (self.primary, self.fallback):
                    self.assertEqual(read(path), self.current)
                    self.assertEqual(path.stat().st_mode & 0o777, 0o640)
                    saved = list(path.parent.glob("bindings.conf.pre-super-k-settings.*"))
                    self.assertEqual([read(backup) for backup in saved], [old])
                    self.assertEqual(saved[0].stat().st_mode & 0o777, 0o640)
                self.assertEqual(self.migrate().stdout.count("nothing to do"), 2)
                self.assertEqual(len(self.backups()), 2)
                for backup in self.backups():
                    backup.unlink()

    def test_the_current_stock_file_and_missing_files_need_no_change(self):
        self.assertIn("No bindings.conf found", self.migrate().stdout)
        write(self.primary, self.current)
        self.assertIn("nothing to do", self.migrate().stdout)
        self.assertEqual(read(self.primary), self.current)
        self.assertEqual(self.backups(), [])

    def test_each_file_is_migrated_on_its_own(self):
        write(self.primary, self.current)
        write(self.fallback, before_super_k())
        self.migrate()
        self.assertEqual(read(self.fallback), self.current)
        self.assertEqual([path.parent for path in self.backups()], [self.hypr])

    def test_a_customized_comment_is_kept_and_only_the_bind_is_repointed(self):
        for comment in ("# my own help shortcut", OLD_K_COMMENTS[0] + " (edited)", ""):
            with self.subTest(comment=comment):
                write(self.primary, before_super_k(comment))
                self.migrate()
                self.assertEqual(read(self.primary), self.current.replace(NEW_K_COMMENT, comment))

    def test_a_bind_on_the_first_line_never_borrows_the_comment_from_the_last_line(self):
        write(self.primary, block(OLD_K_BIND, OLD_K_COMMENTS[1]))
        self.migrate()
        self.assertEqual(read(self.primary), block(NEW_K_BIND, OLD_K_COMMENTS[1]))

    def test_the_bind_is_found_anywhere_and_in_any_spacing(self):
        for line, repointed in (
            (OLD_K_BIND, NEW_K_BIND),
            ("bindd=SUPER,K,Show keybindings,exec,keybind-help", NEW_K_BIND),
            ("bindd = SUPER, k, show keybindings, EXEC, keybind-help", NEW_K_BIND),
            ("  " + OLD_K_BIND, "  " + NEW_K_BIND),
        ):
            with self.subTest(line=line):
                write(self.primary, self.current + "\n" + line + "\n")
                self.migrate()
                self.assertEqual(read(self.primary), self.current + "\n" + repointed + "\n")

    def test_every_matching_line_is_handled(self):
        write(self.primary, before_super_k() + "\n" + OLD_K_BIND + "\n")
        self.migrate()
        self.assertEqual(read(self.primary), self.current + "\n" + NEW_K_BIND + "\n")

    def test_customized_binds_are_kept(self):
        for line in (
            "bind = SUPER, K, exec, keybind-help",
            "bindd = SUPER SHIFT, K, Show keybindings, exec, keybind-help",
            "bindd = SUPER, J, Show keybindings, exec, keybind-help",
            "bindd = SUPER, K, Show the shortcuts, exec, keybind-help",
            "bindd = SUPER, K, Show keybindings, exec, keybind-help --verbose",
            "bindd = SUPER, K, Show keybindings, exec, keybind-help # mine",
            "bindd = SUPER, K, Show keybindings, exec, my-own-help",
            "bindd = SUPER, K, Show keybindings, exec, settings --tab keyboard &",
            "bindd = SUPER, K, Show keybindings, killactive",
        ):
            with self.subTest(line=line):
                self.kept(self.current + line + "\n")

    def test_a_bind_inside_a_submap_is_kept_but_one_after_it_is_not(self):
        scoped = "submap = custom\n" + OLD_K_BIND + "\nsubmap = reset\n"
        self.kept(self.current + scoped)
        write(self.primary, self.current + scoped + OLD_K_BIND + "\n")
        self.migrate()
        self.assertEqual(read(self.primary), self.current + scoped + NEW_K_BIND + "\n")

    def test_crlf_line_endings_and_a_missing_final_newline_are_preserved(self):
        self.primary.write_bytes(before_super_k().replace("\n", "\r\n").encode())
        self.migrate()
        self.assertEqual(self.primary.read_bytes(), self.current.replace("\n", "\r\n").encode())
        write(self.primary, self.current + "\n" + OLD_K_BIND)
        self.migrate()
        self.assertEqual(read(self.primary), self.current + "\n" + NEW_K_BIND)
        self.primary.write_bytes((self.current + "\n" + OLD_K_BIND).replace("\n", "\r\n").encode())
        self.migrate()
        self.assertEqual(self.primary.read_bytes(),
                         (self.current + "\n" + NEW_K_BIND).replace("\n", "\r\n").encode())

    def test_bytes_that_are_not_utf8_survive(self):
        tail = b"# caf\xe9 in latin-1\n"
        self.primary.write_bytes(before_super_k().encode() + tail)
        self.migrate()
        self.assertEqual(self.primary.read_bytes(), self.current.encode() + tail)

    def test_other_binding_files_are_not_touched(self):
        old = before_super_k()
        for name in ("messenger-bindings.conf", "emergency.conf"):
            write(self.hypr / name, old)
        self.migrate()
        for name in ("messenger-bindings.conf", "emergency.conf"):
            self.assertEqual(read(self.hypr / name), old)
        self.assertEqual(self.backups(), [])

    def test_symlinked_bindings_are_left_alone_without_failing_the_update(self):
        target = self.home / "dotfiles.conf"
        write(target, before_super_k())
        self.primary.symlink_to(target)
        result = self.migrate()
        self.assertIn("symlink", result.stdout)
        self.assertIn(NEW_K_BIND, result.stdout)
        self.assertTrue(self.primary.is_symlink())
        self.assertEqual(read(target), before_super_k())
        self.assertEqual(self.backups(), [])

    @unittest.skipIf(os.geteuid() == 0, "root bypasses fixture directory permissions")
    def test_a_backup_failure_keeps_the_original_config(self):
        write(self.primary, before_super_k())
        self.primary.parent.chmod(0o500)
        try:
            result = self.migrate(check=False)
        finally:
            self.primary.parent.chmod(0o700)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(read(self.primary), before_super_k())
        self.assertEqual(list(self.primary.parent.glob("*.tmp.*")), [])


if __name__ == "__main__":
    unittest.main()
