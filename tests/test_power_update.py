import importlib.util
import os
import json
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock

from test_workspace_rollout import function


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "src/shared/bin"
LIB = ROOT / "src/shared/lib"
MIGRATION = "20260930-120000-preserve-idle-preferences.sh"
SPEC = importlib.util.spec_from_file_location("idle_migrate", LIB / "smplos-hypridle-migrate.py")
MIGRATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATE)

CUSTOM = """# Never lock, custom screen and suspend times
source = ./extra.conf
# hyprctl dispatch dpms off is mentioned, not executed
general {
    lock_cmd = my-lock
}
listener {
    timeout = 347
    on-timeout = systemd-detect-virt -q || hyprctl dispatch dpms off # screen
    on-resume = notify-send "custom resume"
}
listener {
    timeout = 925
    on-timeout = my-custom-suspend --keep
}
# smpl-settings-disabled: listener {
# smpl-settings-disabled:     timeout = 1207
# smpl-settings-disabled:     on-timeout = hyprctl dispatch "hl.dsp.dpms({state='off'})"
# smpl-settings-disabled: }
"""


class PowerUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home with spaces"
        self.config = self.home / ".config/hypr/hypridle.conf"
        self.pending = self.home / ".local/state/smplos/hypridle-apply-pending"
        self.repo = self.root / "repo"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls"
        self.log.touch()
        self.env = {
            **os.environ, "HOME": str(self.home), "PATH": f"{self.bin}:{os.environ['PATH']}",
            "SMPLOS_REPO": str(self.repo), "TEST_LOG": str(self.log),
            "HAVE_SESSION": "yes", "SERVICE_FAIL": "", "BARE_PID": "",
            "PARSE_FAIL": "", "PROBE": "lua",
        }
        self.write(self.config, CUSTOM)
        self.write(self.config.parent / "extra.conf", "# custom include\n")
        self.write(self.repo / "src/shared/lib/smplos-session-env.sh", """
SMPLOS_SESSION_UID=1234
smplos_have_hyprland() { [[ "$HAVE_SESSION" == yes ]]; }
smplos_have_user_bus() { [[ "$HAVE_SESSION" == yes ]]; }
smplos_run_as_user() {
    printf 'as-user %s\\n' "$*" >> "$TEST_LOG"
    "$@"
}
""")
        for name in ("smplos-hypridle.sh", "smplos-hypridle-migrate.py"):
            self.write(self.repo / "src/shared/lib" / name, (LIB / name).read_text())
        for name in (MIGRATION, "20260707-210000-hypridle-legacy-dpms-syntax.sh",
                     "20260720-120000-enable-hypridle-service.sh"):
            self.write(self.repo / "migrations" / name, (ROOT / "migrations" / name).read_text())
        self.write(self.bin / "smplos-hypr-dpms", (BIN / "smplos-hypr-dpms").read_text(), executable=True)
        self.write(self.bin / "hypridle", """#!/bin/bash
[[ "$WAYLAND_DISPLAY" == "$XDG_RUNTIME_DIR/no-compositor" ]] || exit 99
[[ -z "${WAYLAND_SOCKET:-}" ]] || exit 98
[[ -f "$XDG_CONFIG_HOME/hypr/hypridle.conf" ]] || exit 97
if [[ "$PARSE_FAIL" == yes ]]; then
    echo 'Config has errors: invalid timeout'
elif [[ "$PARSE_FAIL" == never ]]; then
    printf 'Config has errors:\\nNo rules configured\\nProceeding ignoring faulty entries\\n'
fi
echo "Couldn't connect to a wayland compositor"
exit 1
""", executable=True)
        self.write(self.bin / "systemctl", """#!/bin/bash
[[ "$*" != *"$SERVICE_FAIL"* || -z "$SERVICE_FAIL" ]] || exit 1
case "$*" in
  *LoadState*) echo loaded ;;
  *MainPID*) echo 123 ;;
esac
""", executable=True)
        self.write(self.bin / "pgrep", """#!/bin/bash
echo "${BARE_PID:-123}"
""", executable=True)
        self.write(self.bin / "hyprctl", """#!/bin/bash
printf 'hyprctl %s\\n' "$*" >> "$TEST_LOG"
case "$1" in
 eval)
    case "$PROBE" in
      lua) echo ok ;;
      legacy) echo 'eval is only supported with the lua config manager' ;;
      old) echo 'unknown request' ;;
      missing) echo 'connection failed'; exit 1 ;;
      *) echo 'unknown capability' ;;
    esac ;;
 version)
    case "$PROBE" in
      old) echo 'Hyprland 0.54.2 built from branch main' ;;
      missing) echo 'connection failed'; exit 1 ;;
      *) echo 'Hyprland 0.99.0 built from branch main' ;;
    esac ;;
 dispatch) echo "${DISPATCH_REPLY:-ok}"; exit "${DISPATCH_STATUS:-0}" ;;
esac
""", executable=True)

    def write(self, path, text, executable=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if executable:
            path.chmod(0o755)
        return path

    def run_shell(self, script, check=True):
        return subprocess.run(["bash", "-c", script], env=self.env, text=True,
                              capture_output=True, check=check, timeout=15)

    def migration(self, name=MIGRATION, check=True):
        return self.run_shell(f'bash "$SMPLOS_REPO/migrations/{name}"', check)

    def sync_script(self):
        return """
set -euo pipefail
header() { :; }; log() { :; }; ok() { :; }
warn() { echo "$*" >&2; }
die() { echo "$*" >&2; exit 1; }
as_invoker() { "$@"; }
""" + function("copy_user_config") + function("sync_hypr_configs") + function("sync_hypridle_config")

    def test_exact_preferences_custom_content_and_disabled_markers_survive(self):
        self.migration()
        updated = self.config.read_text()
        self.assertEqual(updated, MIGRATE.migrate(CUSTOM))
        for content in ("timeout = 347", "timeout = 925", "timeout = 1207",
                        "source = ./extra.conf", 'notify-send "custom resume"',
                        "# hyprctl dispatch dpms off is mentioned"):
            self.assertIn(content, updated)
        self.assertIn("# smpl-settings-disabled:     on-timeout = smplos-hypr-dpms off", updated)
        backups = list(self.config.parent.glob("hypridle.conf.pre-dpms-helper.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), CUSTOM)
        self.assertFalse(self.pending.exists())
        self.assertIn("as-user systemctl --user restart hypridle.service", self.log.read_text())
        self.assertNotIn("hyprctl dispatch", self.log.read_text())
        self.assertNotIn("kill", self.log.read_text())
        previous = self.log.read_text()
        self.migration()
        self.assertEqual(self.log.read_text(), previous)
        self.assertEqual(len(list(self.config.parent.glob("*.pre-dpms-helper.*"))), 1)

    def test_custom_shell_commands_are_not_reinterpreted(self):
        for command in ("echo 'hyprctl dispatch dpms off'", "hyprctl dispatch dpms off DP-1",
                        "hyprctl dispatch dpms off; custom-action", 'sh -c "hyprctl dispatch dpms off"'):
            text = f"listener {{\n timeout = 999\n on-timeout = {command}\n}}\n"
            self.assertEqual(MIGRATE.migrate(text), text)
        wake = 'after_sleep_cmd = loginctl lock-session; sleep 0.5; hyprctl dispatch dpms on; sleep 0.2; hyprctl reload; sleep 0.2; hyprctl dispatch "hl.dsp.dpms({state=\'on\'})"\n'
        self.assertEqual(MIGRATE.migrate(wake).count("smplos-hypr-dpms on"), 2)
        self.assertEqual(MIGRATE.migrate(CUSTOM.replace("\n", "\r\n")),
                         MIGRATE.migrate(CUSTOM).replace("\n", "\r\n"))

    def test_sync_preserves_symlinks_and_bootstraps_only_missing_idle_file(self):
        stock = self.repo / "src/compositors/hyprland/hypr"
        self.write(stock / "hypridle.conf", "# stock idle\n")
        self.write(stock / "windows.lua", "-- new OS rules\n")
        self.write(self.config.parent / "windows.lua", "-- old OS rules\n")
        script = self.sync_script() + "\nsync_hypr_configs\n"
        self.run_shell(script)
        self.assertEqual(self.config.read_text(), CUSTOM)
        self.assertEqual((self.config.parent / "windows.lua").read_text(), "-- new OS rules\n")
        self.assertFalse(self.pending.exists())
        target = self.config.parent / "my-idle"
        self.config.rename(target)
        self.config.symlink_to(target.name)
        self.run_shell(script)
        self.assertTrue(self.config.is_symlink())
        self.assertEqual(target.read_text(), CUSTOM)
        target.unlink()
        self.run_shell(script)
        self.assertTrue(self.config.is_symlink())
        self.assertFalse(target.exists())
        self.config.unlink()
        self.run_shell(script)
        self.assertEqual(self.config.read_text(), "# stock idle\n")
        self.assertTrue(self.pending.exists())

    def test_symlink_migration_preserves_link_mode_and_backup(self):
        target = self.config.parent / "my preferences"
        self.config.rename(target)
        target.chmod(0o600)
        self.config.symlink_to(target.name)
        self.migration()
        self.assertTrue(self.config.is_symlink())
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(next(target.parent.glob("my preferences.pre-dpms-helper.*")).read_text(), CUSTOM)

    def test_cross_directory_symlink_preflight_uses_logical_config_parent(self):
        target = self.root / "dotfiles/idle.conf"
        target.parent.mkdir()
        self.config.rename(target)
        self.config.symlink_to(target)
        checked = []
        def check_candidate(path):
            checked.append(path)
            self.assertEqual(path.parent, self.config.parent)
            self.assertEqual(path.read_text(), MIGRATE.migrate(CUSTOM))
        with mock.patch.dict(os.environ, self.env), mock.patch.object(
                MIGRATE, "validate", side_effect=check_candidate):
            MIGRATE.migrate_file(self.config, self.pending)
        self.assertTrue(checked)
        self.assertTrue(all(not path.exists() for path in checked))
        self.assertEqual(self.config.readlink(), target)
        self.assertEqual(target.read_text(), MIGRATE.migrate(CUSTOM))
        self.assertEqual(next(target.parent.glob("idle.conf.pre-dpms-helper.*")).read_text(), CUSTOM)

    def test_missing_config_noop_dangling_link_explicit_failure(self):
        self.config.unlink()
        self.migration()
        self.assertEqual(self.log.read_text(), "")
        self.config.symlink_to("missing")
        self.assertNotEqual(self.migration(check=False).returncode, 0)
        self.assertTrue(self.config.is_symlink())

    def test_failed_validation_never_replaces_config_or_restarts_service(self):
        self.env["PARSE_FAIL"] = "yes"
        result = self.migration(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("validation failed", result.stderr)
        self.assertEqual(self.config.read_text(), CUSTOM)
        self.assertFalse(list(self.config.parent.glob("*.pre-dpms-helper.*")))
        self.assertFalse(self.pending.exists())
        self.assertEqual(self.log.read_text(), "")

    def test_backup_and_publication_failures_preserve_original(self):
        real_mkstemp = tempfile.mkstemp
        def fail_backup(*args, **kwargs):
            if ".pre-dpms-helper." in kwargs.get("prefix", ""):
                raise PermissionError("backup denied")
            return real_mkstemp(*args, **kwargs)
        with mock.patch.dict(os.environ, self.env), mock.patch.object(MIGRATE, "validate"):
            with mock.patch.object(MIGRATE.tempfile, "mkstemp", side_effect=fail_backup):
                with self.assertRaisesRegex(PermissionError, "backup denied"):
                    MIGRATE.migrate_file(self.config, self.pending)
            self.assertEqual(self.config.read_text(), CUSTOM)
            self.assertFalse(self.pending.exists())
            with mock.patch.object(MIGRATE.os, "replace", side_effect=PermissionError("rename denied")):
                with self.assertRaisesRegex(PermissionError, "rename denied"):
                    MIGRATE.migrate_file(self.config, self.pending)
            self.assertEqual(self.config.read_text(), CUSTOM)
            self.assertTrue(self.pending.exists())
            self.assertEqual(next(self.config.parent.glob("*.pre-dpms-helper.*")).read_text(), CUSTOM)
            self.assertFalse(list(self.config.parent.glob(".hypridle.conf.*")))

    def test_concurrent_user_edit_is_not_overwritten(self):
        with mock.patch.dict(os.environ, self.env), mock.patch.object(
                MIGRATE, "validate", side_effect=lambda _: self.config.write_text("# new user choice\n")):
            with self.assertRaisesRegex(RuntimeError, "changed during migration"):
                MIGRATE.migrate_file(self.config, self.pending)
        self.assertEqual(self.config.read_text(), "# new user choice\n")
        self.assertFalse(self.pending.exists())

    def test_missing_helper_rejects_migration_and_bootstrap_application(self):
        (self.bin / "smplos-hypr-dpms").unlink()
        # Isolate lookup rather than accidentally finding an installed helper.
        with mock.patch.dict(os.environ, self.env), mock.patch.object(
                MIGRATE.os, "get_exec_path", return_value=[str(self.bin)]):
            with self.assertRaisesRegex(RuntimeError, "is missing"):
                MIGRATE.migrate_file(self.config, self.pending)
            self.config.write_text(MIGRATE.migrate(CUSTOM))
            self.pending.parent.mkdir(parents=True)
            self.pending.touch()
            with self.assertRaisesRegex(RuntimeError, "is missing"):
                MIGRATE.migrate_file(self.config, self.pending)
        self.assertTrue(self.pending.exists())

    def test_all_never_without_rules_is_preserved(self):
        text = "general {\n lock_cmd = lock-screen\n}\n"
        self.config.write_text(text)
        self.pending.parent.mkdir(parents=True)
        self.pending.touch()
        self.env["PARSE_FAIL"] = "never"
        self.migration()
        self.assertEqual(self.config.read_text(), text)
        self.assertFalse(self.pending.exists())

    def test_deferred_and_failed_apply_remain_pending_and_retry(self):
        self.pending.parent.mkdir(parents=True)
        self.pending.touch()
        for failure, value in (("HAVE_SESSION", "no"), ("SERVICE_FAIL", "restart"),
                               ("SERVICE_FAIL", "is-active"), ("SERVICE_FAIL", "enable"),
                               ("BARE_PID", "456")):
            with self.subTest(failure=failure, value=value):
                self.env[failure] = value
                result = self.migration(check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(self.pending.exists())
                self.env[failure] = "yes" if failure == "HAVE_SESSION" else ""
        self.migration()
        self.assertFalse(self.pending.exists())
        self.assertEqual(self.config.read_text(), MIGRATE.migrate(CUSTOM))

    def test_migration_runner_does_not_mark_failed_or_deferred_work_done(self):
        migration_dir = self.repo / "migrations"
        for path in migration_dir.glob("202607*.sh"):
            path.unlink()
        self.env.update(SMPLOS_PATH=str(self.root), HAVE_SESSION="no")
        result = self.run_shell(f'bash "{BIN / "smplos-migrate"}"', check=False)
        marker = self.home / ".local/state/smplos/migrations" / MIGRATION
        self.assertFalse(marker.exists())
        self.assertEqual(result.returncode, 0)
        self.assertIn("leaving unmarked", result.stdout)
        self.env["HAVE_SESSION"] = "yes"
        result = self.run_shell(f'bash "{BIN / "smplos-migrate"}"')
        self.assertEqual(result.returncode, 0)
        self.assertTrue(marker.exists())
        self.run_shell(f'bash "{BIN / "smplos-migrate"}"')
        marker.unlink()
        self.pending.parent.mkdir(parents=True, exist_ok=True)
        self.pending.touch()
        self.env["SERVICE_FAIL"] = "restart"
        result = self.run_shell(f'bash "{BIN / "smplos-migrate"}"', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())

    def test_old_migrations_no_longer_spawn_or_kill_unmanaged_daemons(self):
        for name in ("20260707-210000-hypridle-legacy-dpms-syntax.sh",
                     "20260720-120000-enable-hypridle-service.sh"):
            self.env["BARE_PID"] = "456"
            result = self.migration(name, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("restart", self.log.read_text())
            self.assertNotIn("pkill", self.log.read_text())
            self.env["BARE_PID"] = ""
            self.migration(name)
            self.log.write_text("")

    def test_every_update_rechecks_commands_even_without_new_commits(self):
        main = (BIN / "smplos-os-update").read_text().split("# ── Main", 1)[1].split("\n", 1)[1]
        stubs = """
CHECK_ONLY=0; MIGRATE_ONLY=0; SCRIPTS_ONLY=0; QUIET=1
SELF_UPDATED=1; SELF_CANONICAL="$HOME/not-installed"
pull_updates() { return 1; }
sync_scripts() { :; }; sync_configs() { :; }; sync_themes() { :; }
sync_apps() { :; }; sync_user_units() { :; }; run_migrations() { :; }; cleanup_shadow_bins() { :; }
post_deploy() { :; }; rebuild-app-cache() { :; }
"""
        script = self.sync_script() + stubs + main
        self.run_shell(script)
        self.assertEqual(self.config.read_text(), MIGRATE.migrate(CUSTOM))
        previous = self.log.read_text()
        self.run_shell(script)
        self.assertEqual(self.log.read_text(), previous)
        self.config.write_text(CUSTOM)  # older Settings saved direct syntax again
        self.run_shell(script)
        self.assertEqual(self.config.read_text(), MIGRATE.migrate(CUSTOM))

    def test_offline_bootstrap_is_deferred_without_blocking_other_config_updates(self):
        self.config.unlink()
        stock = self.repo / "src/compositors/hyprland/hypr"
        self.write(stock / "hypridle.conf", "general {\n lock_cmd = lock-screen\n}\n")
        self.write(stock / "windows.conf", "# updated OS rules\n")
        self.env["HAVE_SESSION"] = "no"
        result = self.run_shell(self.sync_script() + "\nsync_hypr_configs\nsync_hypridle_config\n")
        self.assertIn("remains pending", result.stderr)
        self.assertTrue(self.pending.exists())
        self.assertEqual((self.config.parent / "windows.conf").read_text(), "# updated OS rules\n")
        self.assertEqual(self.log.read_text(), "")

    def test_failed_unrelated_migration_still_reconciles_power_before_reporting_failure(self):
        main = (BIN / "smplos-os-update").read_text().split("# ── Main", 1)[1].split("\n", 1)[1]
        # Run the real migration runner twice: successful and unrelated failure.
        self.env["SMPLOS_PATH"] = str(self.root)
        stubs = f"""
CHECK_ONLY=0; MIGRATE_ONLY=0; SCRIPTS_ONLY=0; QUIET=1
SELF_UPDATED=1; SELF_CANONICAL="$HOME/not-installed"
pull_updates() {{ return 1; }}
sync_scripts() {{ :; }}; sync_configs() {{ :; }}; sync_themes() {{ :; }}
sync_apps() {{ :; }}; sync_user_units() {{ :; }}; cleanup_shadow_bins() {{ :; }}
post_deploy() {{ :; }}; rebuild-app-cache() {{ :; }}
run_migrations() {{ bash "{BIN / 'smplos-migrate'}"; }}
"""
        script = self.sync_script() + stubs + main
        self.run_shell(script)
        self.assertFalse(self.pending.exists())
        self.write(self.repo / "migrations/99999999-000000-fails.sh", "exit 1\n")
        self.config.write_text(CUSTOM)
        result = self.run_shell(script, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("idle reconciliation was attempted", result.stderr)
        self.assertEqual(self.config.read_text(), MIGRATE.migrate(CUSTOM))
        self.assertFalse(self.pending.exists())

    def test_iso_and_updater_include_helper_and_migration_support(self):
        source = self.root / "iso-source"
        self.write(source / "shared/bin/smplos-hypr-dpms", (BIN / "smplos-hypr-dpms").read_text())
        for name in ("smplos-hypridle.sh", "smplos-hypridle-migrate.py"):
            self.write(source / "shared/lib" / name, (LIB / name).read_text())
        image = self.root / "image"
        (image / "usr/local/bin").mkdir(parents=True)
        builder = (ROOT / "src/builder/build.sh").read_text()
        block = builder.split("    # Copy shared bin scripts\n", 1)[1].split(
            "    # Deploy shared web app", 1)[0]
        self.env.update(SRC_DIR=str(source), airootfs=str(image))
        self.run_shell("set -e\nlog_info() { :; }\n" + block)
        for prefix in ("usr/local", "root/smplos"):
            installed = image / prefix / "bin/smplos-hypr-dpms"
            self.assertEqual(installed.read_bytes(), (BIN / "smplos-hypr-dpms").read_bytes())
            self.assertTrue(os.access(installed, os.X_OK))
        for prefix in ("usr/local/lib/smplos", "root/smplos/lib"):
            for name in ("smplos-hypridle.sh", "smplos-hypridle-migrate.py"):
                self.assertEqual((image / prefix / name).read_bytes(), (LIB / name).read_bytes())
        installer = (ROOT / "src/shared/installer/automated_script.sh").read_text()
        install_block = installer.split("  # Deploy sourceable shell libraries", 1)[1].split(
            "  # Copy AppImages", 1)[0]
        install_block = "  # Deploy sourceable shell libraries" + install_block
        destination = self.root / "installed-system"
        install_block = install_block.replace("/root/smplos", str(image / "root/smplos")).replace(
            "/mnt", str(destination))
        self.run_shell("set -e\ninstall_fixture() {\n" + install_block + "\n}\ninstall_fixture\n")
        self.assertEqual((destination / "usr/local/lib/smplos/smplos-hypridle-migrate.py").read_bytes(),
                         (LIB / "smplos-hypridle-migrate.py").read_bytes())
        # Redirect comparisons as well as writes, even when the host is current.
        self.env["LIB_DEST"] = str(self.root / "installed-libs")
        script = r"""
set -euo pipefail
ok() { :; }; warn() { echo "$*" >&2; }
sudo() {
    [[ "$1" == mkdir || "$1" == install ]] || return 99
    [[ "${@: -1}" == "$LIB_DEST" || "${@: -1}" == "$LIB_DEST/"* ]] || return 99
    "$@"
}
""" + function("sync_libs").replace(
            'local dest_dir="/usr/local/lib/smplos"', 'local dest_dir="$LIB_DEST"'
        ) + "\nsync_libs\n"
        self.run_shell(script)
        self.assertEqual((Path(self.env["LIB_DEST"]) / "smplos-hypridle-migrate.py").read_bytes(),
                         (LIB / "smplos-hypridle-migrate.py").read_bytes())
        for entrypoint in ("hyprland.conf", "hyprland.lua"):
            self.assertNotIn("hypridle.conf",
                             (ROOT / "src/compositors/hyprland/hypr" / entrypoint).read_text())

    def test_runtime_helper_uses_running_provider_and_checks_reply(self):
        for provider, expected in (("lua", "hl.dsp.dpms({state='off'})"),
                                   ("legacy", "dpms off"), ("old", "dpms off")):
            with self.subTest(provider=provider):
                self.env["PROBE"] = provider
                self.log.write_text("")
                self.run_shell("smplos-hypr-dpms --check")
                self.assertNotIn("hyprctl dispatch", self.log.read_text())
                self.run_shell("smplos-hypr-dpms off")
                self.assertIn(f"hyprctl dispatch {expected}", self.log.read_text())
        for provider in ("missing", "unknown"):
            self.env["PROBE"] = provider
            self.log.write_text("")
            self.assertNotEqual(self.run_shell("smplos-hypr-dpms off", False).returncode, 0)
            self.assertNotIn("hyprctl dispatch", self.log.read_text())
        self.env.update(PROBE="lua", DISPATCH_REPLY="Invalid dispatcher")
        self.assertNotEqual(self.run_shell("smplos-hypr-dpms on", False).returncode, 0)
        self.env.update(DISPATCH_REPLY="ok", DISPATCH_STATUS="1")
        self.assertNotEqual(self.run_shell("smplos-hypr-dpms on", False).returncode, 0)
        self.assertNotEqual(self.run_shell("smplos-hypr-dpms bogus", False).returncode, 0)

    @unittest.skipUnless(shutil.which("hypridle"), "real hypridle is not installed")
    def test_real_parser_uses_symlink_parent_includes_not_target_includes(self):
        real_hypridle = shutil.which("hypridle")
        (self.bin / "hypridle").unlink()
        (self.bin / "hypridle").symlink_to(real_hypridle)
        target = self.root / "dotfiles/idle.conf"
        target.parent.mkdir()
        self.config.rename(target)
        self.config.symlink_to(target)
        valid = "listener {\n timeout = 888\n on-timeout = NEVER_EXECUTE\n}\n"
        invalid = "listener {\n timeout = abc\n on-timeout = NEVER_EXECUTE\n}\n"
        logical_include = self.write(self.config.parent / "extra.conf", valid)
        target_include = self.write(target.parent / "extra.conf", invalid)
        self.migration()
        self.assertEqual(self.config.readlink(), target)
        self.assertEqual(target.read_text(), MIGRATE.migrate(CUSTOM))
        self.assertEqual(logical_include.read_text(), valid)
        self.assertEqual(target_include.read_text(), invalid)
        self.assertFalse(self.pending.exists())
        self.assertFalse(list(self.config.parent.glob(".hypridle-validate.*")))

        # A valid unrelated include beside the target must not mask a broken
        # include that the real daemon will load beside the symlink.
        target.write_text(CUSTOM)
        logical_include.write_text(invalid)
        target_include.write_text(valid)
        result = self.migration(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Category has a missing timeout setting", result.stderr)
        self.assertEqual(target.read_text(), CUSTOM)
        self.assertFalse(self.pending.exists())
        self.assertFalse(list(self.config.parent.glob(".hypridle-validate.*")))

    @unittest.skipUnless(shutil.which("hypridle"), "real hypridle is not installed")
    def test_real_hypridle_parser_isolated_from_desktop(self):
        self.env["PATH"] = os.environ["PATH"]
        real_config = ROOT / "src/compositors/hyprland/hypr/hypridle.conf"
        self.config.write_text(real_config.read_text())
        code = f"import runpy; m = runpy.run_path({str(LIB / 'smplos-hypridle-migrate.py')!r}); m['validate'](__import__('pathlib').Path({str(self.config)!r}))"
        result = subprocess.run(["python3", "-c", code], env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.config.write_text("general {\n lock_cmd = lock-screen\n}\n")
        result = subprocess.run(["python3", "-c", code], env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.config.write_text("listener {\n timeout = abc\n on-timeout = NEVER_EXECUTE\n}\n")
        result = subprocess.run(["python3", "-c", code], env=self.env, text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot parse", result.stderr)


if __name__ == "__main__":
    unittest.main()


class SessionServicesTests(unittest.TestCase):
    """Session services must run after every login, not only after a restart.

    hypridle (power timers), voxtype (dictation) and the XR watcher are
    WantedBy=graphical-session.target, which a plain start-hyprland session
    never activated: they ran only after Settings or an update restarted
    them, so saved screen-off and suspend timeouts silently stopped working
    after every reboot.
    """

    HYPR = ROOT / "src/compositors/hyprland/hypr"
    SCRIPT = ROOT / "src/shared/bin/smplos-session-services"
    TARGET = ROOT / "src/shared/configs/systemd/user/smplos-session.target"

    # Fake systemctl keeping unit states in $STATE (JSON). BROKEN units never
    # become active; START_FAILS makes the first target start fail.
    SYSTEMCTL = textwrap.dedent("""\
        #!/usr/bin/env python3
        import json, os, sys
        path = os.environ["STATE"]
        state = json.load(open(path))
        args = [a for a in sys.argv[1:] if a != "--user"]
        with open(os.environ["CALLS"], "a") as out:
            out.write(" ".join(args) + "\\n")
        broken = os.environ.get("BROKEN", "").split()
        units = state["units"]
        def save():
            json.dump(state, open(path, "w"))
        if args[0] == "is-active":
            sys.exit(0 if state["graphical"] else 3)
        if args[0] == "stop":
            state["graphical"] = False
        elif args[0] == "start":
            if state.get("start_fails", 0) > 0:
                state["start_fails"] -= 1
                save()
                sys.exit(1)
            state["graphical"] = True
            for name, unit in units.items():
                if not unit.get("skip"):
                    unit["active"] = name not in broken
        elif args[0] == "restart":
            units[args[1]]["active"] = args[1] not in broken
        elif args[0] == "show":
            unit = units.get(args[1], {})
            value = {"ActiveState": "active" if unit.get("active") else "failed",
                     "ConditionResult": "no" if unit.get("skip") else "yes",
                     "ConditionTimestamp": "Sun 2026-10-04" if unit.get("skip") else "",
                     "Result": "exit-code", "Description": args[1]}[args[3]]
            print(value)
        save()
        """)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        (bin_dir / "systemctl").write_text(self.SYSTEMCTL)
        (bin_dir / "notify-send").write_text(f'#!/bin/sh\necho "$*" >> {root}/notified\n')
        for tool in ("systemctl", "notify-send"):
            (bin_dir / tool).chmod(0o755)
        wants = root / "config/systemd/user/graphical-session.target.wants"
        wants.mkdir(parents=True)
        for unit in ("hypridle.service", "voxtype.service", "xr-glasses.service"):
            (wants / unit).touch()
        self.root = root
        self.calls = root / "calls"
        self.notified = root / "notified"
        self.state = root / "state.json"
        self.env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", STATE=str(self.state),
                        CALLS=str(self.calls), XDG_CONFIG_HOME=str(root / "config"),
                        XDG_STATE_HOME=str(root / "state"),
                        XDG_CACHE_HOME=str(root / "cache"), SMPLOS_SYSTEM_USER_UNITS=str(root / "none"),
                        SMPLOS_SESSION_SETTLE="0", SMPLOS_SESSION_RETRY="0")

    def run_login(self, graphical=False, start_fails=0, skip=(), **env):
        units = {u: {"active": False, "skip": u in skip}
                 for u in ("hypridle.service", "voxtype.service", "xr-glasses.service")}
        self.state.write_text(json.dumps({"graphical": graphical, "start_fails": start_fails, "units": units}))
        result = subprocess.run(["bash", str(self.SCRIPT)], env=dict(self.env, **env),
                                capture_output=True, text=True, timeout=20)
        calls = self.calls.read_text().splitlines()
        return result, calls

    def test_both_config_trees_start_the_session_services_at_login(self):
        lua = re.findall(r'hl\.exec_cmd\("smplos-session-services"\)', (self.HYPR / "autostart.lua").read_text())
        conf = re.findall(r"^exec-once = smplos-session-services$",
                          (self.HYPR / "autostart.conf").read_text(), re.MULTILINE)
        self.assertEqual((len(lua), len(conf)), (1, 1))

    def test_no_bare_idle_daemon_competes_with_the_service(self):
        for name in ("autostart.lua", "autostart.conf"):
            for line in (self.HYPR / name).read_text().splitlines():
                code = line.split("--", 1)[0] if name.endswith(".lua") else line.split("#", 1)[0]
                self.assertNotRegex(code, r"(exec_cmd\(\"|exec-once = )hypridle\b", name)

    def test_target_activates_the_graphical_session(self):
        lines = self.TARGET.read_text().splitlines()
        self.assertIn("BindsTo=graphical-session.target", lines)
        self.assertNotIn("RefuseManualStart=yes", lines)

    def test_fresh_login_imports_the_environment_and_starts_everything(self):
        result, calls = self.run_login()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0], "import-environment")
        self.assertNotIn("stop graphical-session.target", calls)
        self.assertIn("reset-failed hypridle.service voxtype.service xr-glasses.service", calls)
        self.assertLess(calls.index("import-environment"), calls.index("start smplos-session.target"))
        self.assertFalse(self.notified.exists())

    def test_target_left_from_the_previous_login_is_restarted_for_this_session(self):
        _, calls = self.run_login(graphical=True)
        self.assertLess(calls.index("stop graphical-session.target"), calls.index("start smplos-session.target"))

    def test_a_target_installed_after_the_manager_started_is_loaded(self):
        result, calls = self.run_login(start_fails=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.count("start smplos-session.target"), 2)
        self.assertIn("daemon-reload", calls)

    def test_a_service_that_will_not_run_is_retried_and_reported(self):
        result, calls = self.run_login(BROKEN="hypridle.service")
        self.assertEqual(result.returncode, 1)
        self.assertIn("restart hypridle.service", calls)
        self.assertIn("Power timers", self.notified.read_text())
        self.assertIn("journalctl --user -u hypridle.service", self.notified.read_text())

    def test_other_failures_are_announced_once_per_change_power_every_login(self):
        state = dict(XDG_STATE_HOME=str(self.root / "state"))
        self.run_login(BROKEN="voxtype.service", **state)
        self.assertIn("Dictation", self.notified.read_text())
        self.notified.unlink()
        self.run_login(BROKEN="voxtype.service", **state)
        self.assertFalse(self.notified.exists(), "an unchanged non-power failure must not nag")
        for _ in range(2):
            self.run_login(BROKEN="hypridle.service voxtype.service", **state)
            self.assertIn("Power timers", self.notified.read_text())
            self.notified.unlink()
        result, _ = self.run_login(**state)
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.root / "state/smplos/session-services.failed").exists())

    def test_a_service_skipped_by_its_own_condition_is_not_an_error(self):
        result, calls = self.run_login(skip=("xr-glasses.service",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("restart xr-glasses.service", calls)
        self.assertFalse(self.notified.exists())

    def test_update_installs_the_target_and_starts_it_in_the_running_session(self):
        repo = self.root / "repo"
        unit_dir = repo / "src/shared/configs/systemd/user"
        unit_dir.mkdir(parents=True)
        (unit_dir / "smplos-session.target").write_text(self.TARGET.read_text())
        home = self.root / "home"
        script = "\n".join([
            "set -euo pipefail", "log() { :; }", "warn() { echo \"$*\" >&2; }", 'die() { exit 1; }',
            'as_invoker() { "$@"; }', 'smplos_have_hyprland() { [[ "${SESSION:-1}" == 1 ]]; }',
            'smplos_run_as_user() { echo "$*" >> "$CALLS"; }',
            function("copy_user_config"), function("sync_user_units"),
            "sync_user_units", "sync_user_units",
        ])
        env = dict(self.env, SMPLOS_REPO=str(repo), HOME=str(home))
        subprocess.run(["bash", "-c", script], env=env, check=True, timeout=10)
        installed = home / ".config/systemd/user/smplos-session.target"
        self.assertEqual(installed.read_text(), self.TARGET.read_text())
        self.assertEqual(installed.stat().st_mode & 0o777, 0o644)
        # Reload only after a change; start in the running session each time.
        self.assertEqual(self.calls.read_text().splitlines(), [
            "systemctl --user daemon-reload", "systemctl --user start smplos-session.target",
            "systemctl --user start smplos-session.target"])
        self.calls.unlink()
        subprocess.run(["bash", "-c", script], env=dict(env, SESSION="0"), check=True, timeout=10)
        self.assertFalse(self.calls.exists())
