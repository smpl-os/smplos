"""EWW repair delivery; native tests use a private HOME, socket and X server."""

import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "src/shared/pkgbuilds/eww-smplos"
MIGRATION = ROOT / "migrations/20261018-060000-eww-ipc-deadlines.sh"
PREFLIGHT_MIGRATION = ROOT / "migrations/20261018-072000-eww-preflight-relative-paths.sh"


class EwwDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        recipe = self.repo / "src/shared/pkgbuilds/eww-smplos"
        shutil.copytree(RECIPE, recipe)
        library = self.repo / "src/shared/lib"
        library.mkdir(parents=True)
        (library / "smplos-pkgbuild.sh").write_text("""
smplos_pkg_version() { cat "$VERSION"; }
smplos_pkgbuild_install() {
    printf '%s\\n' "$*" > "$CALLS"
    [[ -s "$1/ipc-repair.patch" ]] || return 1
    [[ "${BUILD_FAIL:-0}" == 0 ]] || return 1
    printf '%s\\n' "${DELIVERED:-0.6.0.r721.g0eb4604-5}" > "$VERSION"
}
""")
        self.version = self.root / "version"
        self.version.write_text("0.6.0.r721.g0eb4604-1\n")
        self.calls = self.root / "calls"
        self.env = {**os.environ, "SMPLOS_REPO": str(self.repo),
                    "SMPLOS_PATH": str(self.root), "HOME": str(self.root / "home"),
                    "VERSION": str(self.version), "CALLS": str(self.calls)}

    def migrate(self, **env):
        return subprocess.run(["bash", str(MIGRATION)], env={**self.env, **env},
                              capture_output=True, text=True, timeout=5)

    def test_old_same_commit_package_receives_the_patch_without_restarting_the_session(self):
        result = self.migrate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--ask 4", self.calls.read_text())
        self.assertEqual(self.version.read_text().strip(), "0.6.0.r721.g0eb4604-5")
        self.assertNotIn("bar-ctl", MIGRATION.read_text())
        self.calls.unlink()
        self.assertEqual(self.migrate().returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_current_and_newer_revisions_are_not_rebuilt(self):
        for revision in (5, 6, 10):
            self.version.write_text(f"0.6.0.r721.g0eb4604-{revision}\n")
            self.assertEqual(self.migrate().returncode, 0)
            self.assertFalse(self.calls.exists())

    def test_failed_build_is_required_and_keeps_the_old_package(self):
        result = self.migrate(BUILD_FAIL="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("migration remains pending", result.stdout)
        self.assertEqual(self.version.read_text(), "0.6.0.r721.g0eb4604-1\n")

    def test_wrong_delivery_and_missing_package_are_not_success(self):
        self.assertNotEqual(self.migrate(DELIVERED="0.6.0.r721.g0eb4604-1").returncode, 0)
        self.version.write_text("")
        self.assertNotEqual(self.migrate().returncode, 0)

    def test_preflight_repair_runs_after_the_ipc_migration_was_already_completed(self):
        migrations = self.repo / "migrations"
        migrations.mkdir()
        for migration in (MIGRATION, PREFLIGHT_MIGRATION):
            shutil.copy2(migration, migrations / migration.name)
        state = Path(self.env["HOME"]) / ".local/state/smplos/migrations"
        state.mkdir(parents=True)
        (state / MIGRATION.name).touch()
        self.version.write_text("0.6.0.r721.g0eb4604-4\n")
        command = ["bash", str(ROOT / "src/shared/bin/smplos-migrate"), "--phase", "core"]

        failed = subprocess.run(command, env={**self.env, "BUILD_FAIL": "1"},
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        self.assertFalse((state / PREFLIGHT_MIGRATION.name).exists())
        self.assertEqual(self.version.read_text(), "0.6.0.r721.g0eb4604-4\n")

        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--ask 4", self.calls.read_text())
        self.assertEqual(self.version.read_text(), "0.6.0.r721.g0eb4604-5\n")
        self.assertTrue((state / MIGRATION.name).is_file())
        self.assertTrue((state / PREFLIGHT_MIGRATION.name).is_file())
        self.calls.unlink()
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.calls.exists())

    def test_patch_checksum_and_real_pkgver_prevent_makepkg_resetting_revision_to_one(self):
        recipe = (RECIPE / "PKGBUILD").read_text()
        self.assertIn("pkgver=0.6.0.r721.g0eb4604\npkgrel=5\n", recipe)
        self.assertIn(hashlib.sha256((RECIPE / "ipc-repair.patch").read_bytes()).hexdigest(), recipe)
        self.assertIn("cargo test --frozen --release -p eww ipc_repair", recipe)
        for source in ("src/shared/lib/smplos-pkgbuild.sh",
                       "migrations/20260805-100000-eww-smplos-fork-install.sh"):
            self.assertIn('/." "$', (ROOT / source).read_text())

    def test_failed_finalization_retries_even_after_all_files_already_match(self):
        text = (ROOT / "src/shared/bin/smplos-os-update").read_text()
        begin = text.index('    # A failed finalization must retry')
        end = text.index('    [[ $migrations_failed -eq 0 ]]', begin)
        self.assertNotIn("if [[", text[begin:end])
        self.assertIn("post_deploy || migrations_failed=1", text[begin:end])

    @unittest.skipIf(os.geteuid() == 0, "makepkg helper deliberately refuses root")
    def test_package_helper_copies_and_validates_local_patch_assets(self):
        mock_bin = self.root / "bin"
        mock_bin.mkdir()
        scratch = self.root / "scratch"
        scratch.mkdir()
        for name, body in {
            "makepkg": 'test -s ipc-repair.patch || exit 51\n'
                       'echo patch-present >> "$CALLS"\n'
                       'echo "build-pacman $PACMAN" >> "$CALLS"\n'
                       'touch eww-smplos-test-x86_64.pkg.tar.zst\n',
            "fakeroot": "exit 0\n",
            "sudo": 'echo "install $*" >> "$CALLS"\n',
        }.items():
            tool = mock_bin / name
            tool.write_text("#!/bin/sh\n" + body)
            tool.chmod(0o755)
        result = subprocess.run(
            ["bash", "-c", 'source "$1"; PACMAN=original-pacman; '
             'smplos_pkgbuild_install "$2" --ask 4 && [[ "$PACMAN" == original-pacman ]]', "fixture",
             str(ROOT / "src/shared/lib/smplos-pkgbuild.sh"),
             str(self.repo / "src/shared/pkgbuilds/eww-smplos")],
            env={**self.env, "PATH": f"{mock_bin}:{os.environ['PATH']}", "TMPDIR": str(scratch),
                 "SMPLOS_UPDATE_PACMAN": str(mock_bin / "guarded-pacman")},
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("patch-present", self.calls.read_text())
        self.assertIn(f"build-pacman {mock_bin / 'guarded-pacman'}", self.calls.read_text())
        self.assertIn("pacman -U --noconfirm --ask 4", self.calls.read_text())
        self.assertEqual(list(scratch.iterdir()), [])


@unittest.skipUnless(os.environ.get("SMPLOS_EWW_TEST_BINARY") and shutil.which("Xvfb"),
                     "requires the privately built repaired EWW and Xvfb")
class EwwNativeReloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eww-repair-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.config = self.home / ".config/eww"
        (self.config / "scripts").mkdir(parents=True)
        (self.config / "quick-settings.yuck").write_text(
            '(defvar ws-count 4)\n(defvar ws-position "center")\n'
            '(defvar ws-spacing 1)\n(defvar ws-style "numbers")\n')
        (self.config / "eww.yuck").write_text(
            '(include "./quick-settings.yuck")\n'
            '(defwindow bar :namespace "eww-repair-test"'
            ' :geometry (geometry :width "100%" :height "24px" :anchor "top center")'
            ' (label :text ws-count))\n')
        (self.config / "eww.scss").write_text('@import "theme-colors";\n')
        (self.config / "theme-colors.scss").write_text('* { color: #ffffff; background: #000000; }\n')
        for name in ("runtime", "cache", "bin"):
            (self.root / name).mkdir(mode=0o700)
        self.binary = Path(os.environ["SMPLOS_EWW_TEST_BINARY"]).resolve()
        (self.root / "bin/eww").symlink_to(self.binary)
        self.controller = self.root / "bar-ctl"
        self.controller.write_text((ROOT / "src/shared/bin/bar-ctl").read_text().replace(
            '( sleep 2; "$0" refresh "$BAR_NAME" ) 8>&- 9>&- >/dev/null 2>&1 &', ':'))
        self.controller.chmod(0o755)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.env = {**os.environ, "HOME": str(self.home),
                    "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}",
                    "DISPLAY": f"127.0.0.1:{port - 6000}",
                    "GDK_BACKEND": "x11", "XDG_SESSION_TYPE": "x11", "NO_AT_BRIDGE": "1",
                    "XDG_CONFIG_HOME": str(self.home / ".config"),
                    "XDG_STATE_HOME": str(self.home / ".local/state"),
                    "XDG_RUNTIME_DIR": str(self.root / "runtime"),
                    "XDG_CACHE_HOME": str(self.root / "cache")}
        for name in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "NIRI_SOCKET",
                     "DBUS_SESSION_BUS_ADDRESS", "GTK_MODULES", "GTK3_MODULES"):
            self.env.pop(name, None)
        self.log_path = self.root / "native.log"
        self.log = self.log_path.open("w+")
        self.addCleanup(self.log.close)
        self.xvfb = subprocess.Popen(
            ["Xvfb", f":{port - 6000}",
             "-screen", "0", "1280x720x24", "-listen", "tcp", "-nolisten", "unix", "-ac"],
            stdout=self.log, stderr=subprocess.STDOUT)
        self.addCleanup(self.stop, self.xvfb)
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.02)
        else:
            self.fail("Private X server did not become ready")
        self.daemons = []
        self.addCleanup(self.clean_daemons)

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def clean_daemons(self):
        self.eww("kill", check=False)
        for process in self.daemons:
            self.stop(process)

    def eww(self, *args, check=True):
        return subprocess.run([str(self.binary), "--config", str(self.config), *args],
                              env=self.env, cwd=self.root,
                              capture_output=True, text=True, timeout=20, check=check)

    def start(self, binary=None):
        process = subprocess.Popen(
            [str(binary or self.binary), "--config", str(self.config), "--no-daemonize", "daemon"],
            env=self.env, stdout=self.log, stderr=subprocess.STDOUT)
        self.daemons.append(process)
        for _ in range(100):
            if process.poll() is not None:
                self.fail(self.log_path.read_text())
            if self.eww("ping", check=False).returncode == 0:
                break
            time.sleep(0.02)
        else:
            self.fail("Private EWW daemon did not become ready")
        self.eww("open", "bar")
        time.sleep(0.6)
        return process

    def bar(self, action):
        return subprocess.run(["bash", str(self.controller), action], env=self.env,
                              capture_output=True, text=True, timeout=20)

    def test_check_config_resolves_includes_from_config_not_caller_or_decoy_files(self):
        for decoy in (False, True):
            with self.subTest(decoy=decoy):
                if decoy:
                    (self.root / "quick-settings.yuck").write_text("(invalid caller-owned configuration\n")
                result = self.eww("check-config", check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Configuration and stylesheet valid", result.stdout)
        self.assertNotEqual(self.eww("ping", check=False).returncode, 0)

    def test_full_stock_amber_preflight_does_not_start_scripts_or_a_daemon(self):
        shutil.copytree(ROOT / "src/shared/eww", self.config, dirs_exist_ok=True)
        shutil.copy2(ROOT / "src/shared/themes/amber/eww-colors.scss",
                     self.config / "theme-colors.scss")
        marker = self.root / "must-not-run"
        with (self.config / "eww.yuck").open("a") as yuck:
            yuck.write(f'\n(defpoll preflight-poll :interval "1s" "touch {marker}")\n'
                       f'(deflisten preflight-listener "touch {marker}")\n')
        (self.root / "quick-settings.yuck").write_text("(invalid caller-owned configuration\n")
        result = self.eww("check-config", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(marker.exists(), "Preflight executed a poll/listener")
        self.assertNotEqual(self.eww("ping", check=False).returncode, 0)

    def test_missing_include_cannot_use_a_caller_decoy_or_stop_the_old_daemon(self):
        old = self.root / "old/eww"
        old.parent.mkdir()
        shutil.copy2(self.binary, old)
        process = self.start(old)
        with (self.config / ".smplos-reload.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            include = self.config / "quick-settings.yuck"
            shutil.copy2(include, self.root / include.name)
            include.unlink()
            result = self.eww("check-config", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Included file", result.stderr)
            result = self.bar("reload")
            self.assertNotEqual(result.returncode, 0)
            self.assertIsNone(process.poll())
            self.assertIn("bar: bar", self.eww("active-windows").stdout)

    def test_batched_files_reload_exactly_once_and_ensure_does_not_blink(self):
        self.start()
        offset = self.log_path.stat().st_size
        with (self.config / ".smplos-reload.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for color in ("#112233", "#224466", "#336699"):
                (self.config / "theme-colors.scss").write_text(f"* {{ background: {color}; }}\n")
                time.sleep(0.2)
            time.sleep(0.7)
            self.assertNotIn("Reloading windows", self.log_path.read_bytes()[offset:].decode())
            result = self.bar("reload")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = self.bar("ensure")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        time.sleep(0.7)
        log = self.log_path.read_bytes()[offset:].decode()
        self.assertEqual(log.count("Reloading windows"), 1, log)
        self.assertNotIn("channel closed", log)
        self.assertIn("bar: bar", self.eww("active-windows").stdout)
        (self.config / "theme-colors.scss").write_text("* { background: #445566; }\n")
        time.sleep(0.8)
        log = self.log_path.read_bytes()[offset:].decode()
        self.assertEqual(log.count("Reloading windows"), 2, "Direct edits must still auto-reload:\n" + log)

    def test_invalid_scss_remains_a_required_failure(self):
        self.start()
        with (self.config / ".smplos-reload.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            (self.config / "theme-colors.scss").write_text("* { background: ; invalid\n")
            result = self.bar("reload")
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("bar-ctl apply:", result.stderr)

    def test_replaced_binary_is_activated_once_and_the_bar_is_verified(self):
        old = self.root / "old/eww"
        old.parent.mkdir()
        shutil.copy2(self.binary, old)
        process = self.start(old)
        result = self.bar("reload")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        process.wait(timeout=5)
        self.assertIn("bar: bar", self.eww("active-windows").stdout)
        log = self.home / ".local/state/smplos/eww-startup.log"
        self.assertEqual(log.read_text().count("Activating replaced EWW binary"), 1)
        self.assertEqual(self.bar("ensure").returncode, 0)
        self.assertEqual(log.read_text().count("Activating replaced EWW binary"), 1)

    def test_invalid_replacement_configuration_keeps_the_old_daemon_and_bar(self):
        old = self.root / "old/eww"
        old.parent.mkdir()
        shutil.copy2(self.binary, old)
        process = self.start(old)
        marker = self.root / "must-not-run"
        yuck = self.config / "eww.yuck"
        with (self.config / ".smplos-reload.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yuck.write_text(yuck.read_text() + f'\n(defpoll probe :interval "1s" "touch {marker}")\n')
            stylesheet = self.config / "theme-colors.scss"
            stylesheet.write_text("* { background: ; invalid\n")
            result = self.bar("reload")
            self.assertNotEqual(result.returncode, 0)
            self.assertIsNone(process.poll())
            self.assertFalse(marker.exists(), "Preflight executed a polling command")
            self.assertIn("bar: bar", self.eww("active-windows").stdout)

    def test_auto_started_old_daemon_is_detected_despite_retaining_open_arguments(self):
        from test_app_delivery import function

        old = self.root / "old/eww"
        old.parent.mkdir()
        shutil.copy2(os.environ.get("SMPLOS_EWW_OLD_TEST_BINARY", str(self.binary)), old)
        with self.log_path.open("a") as log:
            subprocess.run([str(old), "--config", str(self.config), "open", "bar"],
                           env=self.env, stdout=log, stderr=subprocess.STDOUT, timeout=10, check=True)
        for _ in range(50):
            if self.eww("active-windows", check=False).stdout.strip() == "bar: bar":
                break
            time.sleep(0.05)
        probe = function(ROOT / "src/shared/bin/bar-ctl", "eww_stale_pid")
        result = subprocess.run(["bash", "-c", probe + '\nEWW_CONFIG="$HOME/.config/eww"\neww_stale_pid'],
                                env=self.env, capture_output=True, text=True, timeout=5)
        pid = result.stdout.strip()
        self.assertTrue(pid.isdigit(), result.stdout + result.stderr)
        self.assertTrue(Path(f"/proc/{pid}/exe").exists())
        result = self.bar("reload")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(Path(f"/proc/{pid}/exe").exists())
        self.assertIn("bar: bar", self.eww("active-windows").stdout)


if __name__ == "__main__":
    unittest.main()
