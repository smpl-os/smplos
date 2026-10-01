import io
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "src/shared/lib/smplos-app-bundle.sh"
APPS = (
    "start-menu", "notif-center", "settings", "app-center", "webapp-center",
    "sync-center-daemon", "sync-center-gui", "smpl-calendar", "smpl-calendar-alertd",
    "smpl-hints", "smpl-hintsd",
)


def function(path, name):
    source = path.read_text()
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}", source, re.M | re.S)
    if match is None:
        raise AssertionError(f"Function {name} not found in {path}")
    return match.group()


MOCK_CURL = """#!/usr/bin/python3
import os, pathlib, shutil, sys
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith("https://"))
with open(os.environ["REQUEST_LOG"], "a") as log:
    log.write(url + "\\n")
if "/orgs/" in url:
    print('[{"full_name": "smpl-os/smpl-apps"}]')
elif "/releases/latest" in url:
    if "/nemo-smpl/" in url and os.environ.get("NEMO_RELEASE_JSON"):
        print(pathlib.Path(os.environ["NEMO_RELEASE_JSON"]).read_text())
        sys.exit(0)
    if "/smpl-apps/" not in url or os.environ.get("OFFLINE") == "1":
        sys.exit(22)
    print(pathlib.Path(os.environ["RELEASE_JSON"]).read_text())
else:
    if os.environ.get("FAIL_DOWNLOAD") == "1":
        sys.exit(22)
    if url.endswith("/SHA256SUMS-x86_64"):
        print(pathlib.Path(os.environ["CHECKSUMS"]).read_text())
        sys.exit(0)
    archive = pathlib.Path(os.environ.get("NEMO_ARCHIVE", os.environ["ARCHIVE"])
                           if "/nemo-smpl/" in url else os.environ["ARCHIVE"])
    if "-o" in args:
        shutil.copyfile(archive, args[args.index("-o") + 1])
    else:
        sys.stdout.buffer.write(archive.read_bytes())
"""


class AppDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.project = self.base / "project"
        self.home = self.base / "home"
        self.home.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.cache = self.project / ".cache/app-binaries"
        self.cache.mkdir(parents=True)
        self.archive = self.base / "release.tar.gz"
        self.release = self.base / "release.json"
        self.requests = self.base / "requests.log"
        for path in ("src/fetch-apps.sh", "src/fetch-org.sh",
                     "src/shared/lib/smplos-app-bundle.sh"):
            target = self.project / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target)
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "LC_ALL": "C",
            "PROJECT_ROOT": str(self.project),
            "RELEASE_JSON": str(self.release),
            "ARCHIVE": str(self.archive),
            "REQUEST_LOG": str(self.requests),
        }
        self.mock("curl", MOCK_CURL)
        self.mock("gh", "#!/bin/bash\nexit 1\n")
        # Any accidental real update/build operation must fail, not touch the host.
        for name in ("sudo", "pkill", "pacman", "makepkg", "podman", "docker", "nohup"):
            self.mock(name, f'#!/bin/bash\necho "FORBIDDEN: {name}" >&2\nexit 99\n')
        self.mock("pgrep", "#!/bin/bash\nexit 1\n")
        self.publish()

    def mock(self, name, contents):
        path = self.bin / name
        path.write_text(contents)
        path.chmod(0o755)

    def publish(self, missing=None, corrupt=None, asset=True):
        url = "https://github.com/smpl-os/smpl-apps/releases/download/v0.8.23/smpl-apps-0.8.23-x86_64.tar.gz"
        self.release.write_text(json.dumps({
            "tag_name": "v0.8.23",
            "assets": [{"browser_download_url": url}] if asset else [],
        }, indent=2))
        with tarfile.open(self.archive, "w:gz") as archive:
            for app in (*APPS, "xrctl"):
                if app == missing:
                    continue
                data = b"broken" if app == corrupt else b"\x7fELFnew-" + app.encode()
                info = tarfile.TarInfo(app)
                info.size = len(data)
                info.mode = 0o755
                archive.addfile(info, io.BytesIO(data))

    def seed(self, directory, marker=None, version="v0.8.22"):
        directory.mkdir(parents=True, exist_ok=True)
        for app in APPS:
            (directory / app).write_bytes(b"\x7fELFold-" + app.encode())
        if marker:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(version + "\n")

    def shell(self, script, **env):
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", script],
            env={**self.env, **env}, text=True, capture_output=True, timeout=15,
        )
        self.assertNotIn("FORBIDDEN:", result.stderr)
        return result

    def run_fetcher(self, name, **env):
        return self.shell(f'bash "$PROJECT_ROOT/src/{name}"', **env)

    def iso_download(self, **env):
        path = ROOT / "src/build-iso.sh"
        script = f'source "{LIB}"\nsource "{ROOT}/src/shared/lib/smplos-release-package.sh"\n'
        script += "\n".join(function(path, name) for name in
                            ("_gh_api", "_version_gt", "download_prebuilt_apps"))
        script += """
log_step() { :; }
log_info() { echo "$*"; }
log_warn() { echo "$*" >&2; }
die() { echo "$*" >&2; exit 1; }
download_prebuilt_apps
"""
        return self.shell(script, **env)

    def assert_new_bundle(self, directory):
        for app in APPS:
            self.assertEqual((directory / app).read_bytes(), b"\x7fELFnew-" + app.encode())
            self.assertTrue(os.access(directory / app, os.X_OK))

    def test_fetch_apps_and_iso_share_one_marker_and_skip_current_download(self):
        result = self.run_fetcher("fetch-apps.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_new_bundle(self.cache)
        self.assertEqual((self.cache / ".smpl-apps-version").read_text(), "v0.8.23\n")
        self.assertFalse((self.cache / "smpl-apps.fetched-version").exists())
        result = self.iso_download()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests.read_text().count("/releases/download/"), 1)

    def test_fetch_apps_rejects_missing_or_corrupt_binary_without_blessing_old_file(self):
        marker = self.cache / ".smpl-apps-version"
        self.seed(self.cache, marker)
        for problem in ("missing", "corrupt"):
            with self.subTest(problem=problem):
                self.publish(**{problem: "start-menu"})
                result = self.run_fetcher("fetch-apps.sh")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("missing or invalid binary", result.stderr)
                self.assertEqual(marker.read_text(), "v0.8.22\n")
                for app in APPS:
                    self.assertEqual((self.cache / app).read_bytes(),
                                     b"\x7fELFold-" + app.encode())

    def test_matching_marker_with_missing_binary_is_repaired(self):
        marker = self.cache / ".smpl-apps-version"
        self.seed(self.cache, marker, "v0.8.23")
        (self.cache / "settings").unlink()
        result = self.run_fetcher("fetch-apps.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_new_bundle(self.cache)

    def test_old_nine_binary_cache_cannot_skip_new_hints_at_matching_tag(self):
        for fetcher, directory, marker in (
            ("fetch-apps.sh", self.cache, self.cache / ".smpl-apps-version"),
            ("fetch-org.sh", self.project / ".cache/org-binaries/bin",
             self.project / ".cache/org-binaries/.versions/smpl-apps"),
        ):
            with self.subTest(fetcher=fetcher):
                self.seed(directory, marker, "v0.8.23")
                for app in ("smpl-hints", "smpl-hintsd"):
                    (directory / app).unlink()
                result = self.run_fetcher(fetcher)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_new_bundle(directory)

    def test_org_failed_download_does_not_advance_marker_and_retry_succeeds(self):
        stage = self.project / ".cache/org-binaries"
        marker = stage / ".versions/smpl-apps"
        self.seed(stage / "bin", marker)
        result = self.run_fetcher("fetch-org.sh", FAIL_DOWNLOAD="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(marker.read_text(), "v0.8.22\n")
        result = self.run_fetcher("fetch-org.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_new_bundle(stage / "bin")
        self.assertEqual(marker.read_text(), "v0.8.23\n")

    def test_org_incomplete_asset_does_not_overwrite_cache_or_marker(self):
        stage = self.project / ".cache/org-binaries"
        marker = stage / ".versions/smpl-apps"
        self.seed(stage / "bin", marker)
        self.publish(missing="settings")
        result = self.run_fetcher("fetch-org.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(marker.read_text(), "v0.8.22\n")
        self.assertEqual((stage / "bin/start-menu").read_bytes(), b"\x7fELFold-start-menu")

    def test_org_matching_marker_missing_binary_is_repaired(self):
        stage = self.project / ".cache/org-binaries"
        marker = stage / ".versions/smpl-apps"
        self.seed(stage / "bin", marker, "v0.8.23")
        (stage / "bin/start-menu").unlink()
        result = self.run_fetcher("fetch-org.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_new_bundle(stage / "bin")

    def test_org_missing_asset_does_not_mark_release_fetched(self):
        self.publish(asset=False)
        result = self.run_fetcher("fetch-org.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.project / ".cache/org-binaries/.versions/smpl-apps").exists())

    def test_iso_refuses_known_new_but_incomplete_release_instead_of_old_cache(self):
        marker = self.cache / ".smpl-apps-version"
        self.seed(self.cache, marker)
        self.publish(missing="start-menu")
        result = self.iso_download()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to build with stale apps", result.stderr)
        self.assertEqual(marker.read_text(), "v0.8.22\n")
        self.assertEqual((self.cache / "start-menu").read_bytes(), b"\x7fELFold-start-menu")

    def test_iso_can_use_complete_offline_cache_but_not_just_start_menu(self):
        self.seed(self.cache)
        result = self.iso_download(OFFLINE="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.cache / "settings").unlink()
        result = self.iso_download(OFFLINE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No smpl-apps binaries available", result.stderr)

    def test_iso_accepts_complete_manual_offline_bundle_without_stale_marker(self):
        marker = self.cache / ".smpl-apps-version"
        marker.write_text("v0.8.22\n")
        fallback = self.project / "build/prebuilt-apps"
        self.seed(fallback)
        result = self.iso_download(OFFLINE="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        for app in APPS:
            self.assertEqual((self.cache / app).read_bytes(), (fallback / app).read_bytes())

    def test_app_updater_validates_before_install_or_version_write(self):
        path = ROOT / "src/shared/bin/smplos-update-apps"
        state = self.home / ".local/state/smplos/app-versions"
        state.mkdir(parents=True)
        (state / "smpl-apps").write_text("v0.8.22\n")
        script = f'source "{LIB}"\n'
        script += "\n".join(function(path, name) for name in
                            ("_gh_api", "_version_gt", "_cached_ver", "update_smpl_apps"))
        script += """
STATE_DIR="$HOME/.local/state/smplos/app-versions"
CHECK_ONLY=0; QUIET=0; n_updated=0
log() { :; }
ok() { :; }
warn() { echo "$*" >&2; }
update_smpl_apps
"""
        self.publish(missing="start-menu")
        result = self.shell(script)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((state / "smpl-apps").read_text(), "v0.8.22\n")
        self.assertIn("version not recorded", result.stderr)

    def test_app_updater_installs_complete_release_without_modifying_pins(self):
        path = ROOT / "src/shared/bin/smplos-update-apps"
        state = self.home / ".local/state/smplos/app-versions"
        installed = self.home / "installed"
        installed.mkdir()
        state.mkdir(parents=True)
        self.seed(installed, state / "smpl-apps")
        pins = self.home / ".config/smplos/pinned-apps.txt"
        pins.parent.mkdir(parents=True)
        pins.write_text('"grafium"\ncustom --command\n')
        self.mock("sudo", """#!/bin/bash
case "$1" in
install|mktemp|mv|rm)
    [[ "${@: -1}" == "$HOME/installed/"* ]] || exit 99
    [[ "$1" != install || "${FAIL_INSTALL:-0}" != 1 ]] || exit 1
    exec "$@" ;;
*) exit 99 ;;
esac
""")
        self.mock("systemctl", "#!/bin/bash\nexit 0\n")
        source = function(path, "update_smpl_apps").replace("/usr/local/bin", str(installed))
        script = f'source "{LIB}"\n'
        script += "\n".join(function(path, name) for name in
                            ("_gh_api", "_version_gt", "_cached_ver"))
        script += "\n" + source + """
STATE_DIR="$HOME/.local/state/smplos/app-versions"
CHECK_ONLY=0; QUIET=0; n_updated=0
log() { :; }; ok() { :; }; warn() { echo "$*" >&2; }
update_smpl_apps
"""
        result = self.shell(script, FAIL_INSTALL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((state / "smpl-apps").read_text(), "v0.8.22\n")
        for app in APPS:
            self.assertEqual((installed / app).read_bytes(), b"\x7fELFold-" + app.encode())
        self.assertEqual(sorted(path.name for path in installed.iterdir()), sorted(APPS))
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_new_bundle(installed)
        self.assertEqual((state / "smpl-apps").read_text(), "v0.8.23\n")
        self.assertEqual(pins.read_text(), '"grafium"\ncustom --command\n')
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests.read_text().count("/releases/download/"), 2)

    def test_iso_assembly_installs_same_bundle_for_live_and_installed_system(self):
        binaries = self.base / "app-binaries"
        profile = self.base / "profile"
        self.seed(binaries)
        source = function(ROOT / "src/builder/build.sh", "install_prebuilt_apps")
        # Only redirect the container mount; all installation logic is unchanged.
        source = source.replace('local bin_dir="/build/app-binaries"',
                                f'local bin_dir="{binaries}"')
        script = f'source "{LIB}"\n{source}\n'
        script += f'PROFILE_DIR="{profile}"\n'
        script += """
log_step() { :; }; log_info() { :; }; log_warn() { :; }; log_error() { echo "$*" >&2; }
install_prebuilt_apps
"""
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        for app in APPS:
            for target in ("usr/local/bin", "root/smplos/bin"):
                self.assertEqual((profile / "airootfs" / target / app).read_bytes(),
                                 (binaries / app).read_bytes())

    def test_update_mains_refresh_even_without_new_binaries_and_report_failure(self):
        for name in ("smplos-os-update", "smplos-update-apps"):
            path = ROOT / "src/shared/bin" / name
            main = path.read_text().split("# ── Main", 1)[1].split("\n", 1)[1]
            stubs = """
CHECK_ONLY=0; MIGRATE_ONLY=0; SCRIPTS_ONLY=0; QUIET=1; n_updated=0
STATE_DIR="$HOME/state"; SMPLOS_PATH="$HOME/data"; SMPLOS_APP_BINS=()
SELF_UPDATED=1; SELF_CANONICAL="$HOME/no-installed-script"
header() { :; }; ok() { :; }; warn() { echo "$*" >&2; }
die() { echo "$*" >&2; exit 1; }
pull_updates() { return 1; }
sync_scripts() { :; }; sync_configs() { :; }; sync_themes() { :; }
sync_apps() { :; }; sync_hypr_configs() { :; }; run_migrations() { :; }
sync_hypridle_config() { :; }
cleanup_shadow_bins() { :; }; post_deploy() { :; }
update_smpl_apps() { :; }; update_st_smpl() { :; }; update_nemo_smpl() { :; }
update_micro_smpl() { :; }; update_grafium() { :; }
rebuild-app-cache() { echo refreshed; return "$CACHE_STATUS"; }
"""
            for status in ("0", "1"):
                with self.subTest(updater=name, status=status):
                    result = self.shell(stubs + main, CACHE_STATUS=status)
                    self.assertEqual(result.stdout.count("refreshed"), 1)
                    self.assertEqual(result.returncode, int(status), result.stderr)
            if name == "smplos-os-update":
                result = self.shell(stubs + "\nSCRIPTS_ONLY=1\n" + main, CACHE_STATUS="0")
                self.assertEqual(result.stdout.count("refreshed"), 1)
            else:
                result = self.shell(stubs + "\nCHECK_ONLY=1\n" + main, CACHE_STATUS="0")
                self.assertNotIn("refreshed", result.stdout)

    def test_new_user_cache_is_generated_not_shipped(self):
        builder = (ROOT / "src/builder/build.sh").read_text()
        self.assertIn('cp "$SRC_DIR/shared/lib/"*.sh "$airootfs/usr/local/lib/smplos/"',
                      builder)
        self.assertIn('cp "$SRC_DIR/shared/lib/"*.sh "$airootfs/root/smplos/lib/"',
                      builder)
        self.assertIn('ln -sf ../smplos-app-cache.service', builder)
        self.assertIn('ln -sf ../smplos-app-cache.path', builder)
        installer = (ROOT / "src/shared/installer/install.sh").read_text()
        self.assertIn('rebuild-app-cache || echo', installer)
        self.assertFalse(list((ROOT / "src/shared").rglob("app_index")))

    def test_os_updater_reexec_preserves_quiet_flag(self):
        source = (ROOT / "src/shared/bin/smplos-os-update").read_text()
        reexec = source.split('    if [[ "$SELF_UPDATED" != "1" ]]', 1)[1]
        reexec = 'if [[ "$SELF_UPDATED" != "1" ]]' + reexec.split("\n    sync_configs", 1)[0]
        canonical = self.home / "new-updater"
        canonical.write_text('#!/bin/bash\nprintf "resumed=%s changed=%s args=%s\\n" "$SMPLOS_OS_UPDATE_RESUMED" "$SMPLOS_OS_HAD_UPDATES" "$*"\n')
        canonical.chmod(0o755)
        script = f'SELF_CANONICAL="{canonical}"\n'
        script += """
SELF_UPDATED=0; QUIET=1; had_updates=1; _pre_sync_hash=old; _post_sync_hash=new
header() { :; }; warn() { :; }
""" + reexec
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "resumed=1 changed=1 args=--quiet\n")

    def nemo_release(self, missing=None):
        archive = self.base / "nemo.pkg.tar.zst"
        # tar auto-detects compression, so an uncompressed tiny fixture suffices.
        with tarfile.open(archive, "w") as output:
            for name in (".PKGINFO", "usr/bin/nemo", "usr/libexec/nemo-document-renderer",
                         "usr/libexec/nemo-archive-create-worker"):
                if name == missing:
                    continue
                data = (b"pkgname = nemo-smpl\npkgver = 1.4.72-1\n" if name == ".PKGINFO"
                        else b"\x7fELFnative")
                item = tarfile.TarInfo(name)
                item.size = len(data)
                output.addfile(item, io.BytesIO(data))
        name = "nemo-smpl-1.4.72-1-x86_64.pkg.tar.zst"
        base_url = "https://github.com/smpl-os/nemo-smpl/releases/download/v1.4.72"
        release = self.base / "nemo.json"
        release.write_text(json.dumps({
            "tag_name": "v1.4.72", "assets": [
                {"browser_download_url": base_url + "/" + name},
                {"browser_download_url": base_url + "/SHA256SUMS-x86_64"},
            ],
        }, indent=2))
        checksums = self.base / "checksums"
        checksums.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + name + "\n")
        self.env.update(NEMO_ARCHIVE=str(archive), NEMO_RELEASE_JSON=str(release),
                        CHECKSUMS=str(checksums))
        return archive

    def package_mocks(self):
        self.mock("pacman", """#!/bin/bash
case "$1" in
-Q) [[ -n "${INSTALLED_VERSION:-}" ]] || exit 1; echo "$2 $INSTALLED_VERSION";;
-Qk) exit "${MISSING_FILES:-0}";;
-U) echo "$*" >> "$HOME/pacman.log"; exit "${INSTALL_FAIL:-0}";;
*) exit 99;;
esac
""")
        self.mock("sudo", """#!/bin/bash
[[ "$1" == pacman && "$2" == -U ]] || exit 99
exec "$@"
""")
        self.mock("vercmp", """#!/usr/bin/python3
import re,sys
a,b=(tuple(map(int,re.findall(r'\\d+',v))) for v in sys.argv[1:])
print((a>b)-(a<b))
""")

    def nemo_update(self, **env):
        path = ROOT / "src/shared/bin/smplos-update-apps"
        script = f'source "{ROOT}/src/shared/lib/smplos-release-package.sh"\n'
        script += "\n".join(function(path, name) for name in
                            ("_gh_api", "_cached_ver", "update_nemo_smpl"))
        script += """
STATE_DIR="$HOME/state"; mkdir -p "$STATE_DIR"
CHECK_ONLY=0; QUIET=0; n_updated=0
log() { echo "$*"; }; ok() { echo "$*"; }; warn() { echo "$*" >&2; }
update_nemo_smpl
"""
        return self.shell(script, **env)

    def test_nemo_download_checks_checksum_payload_and_canonical_package_install(self):
        self.nemo_release()
        self.package_mocks()
        result = self.nemo_update(INSTALLED_VERSION="1.4.71-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.home / "state/nemo-smpl").read_text(), "v1.4.72\n")
        self.assertIn("-U --noconfirm /tmp/nemo-smpl.", (self.home / "pacman.log").read_text())
        self.assertIn("No running windows were stopped", result.stdout)

    def test_nemo_cached_tag_missing_install_repairs_but_newer_never_downgrades(self):
        self.nemo_release()
        self.package_mocks()
        state = self.home / "state"
        state.mkdir()
        (state / "nemo-smpl").write_text("v1.4.72\n")
        result = self.nemo_update(INSTALLED_VERSION="1.4.73-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / "pacman.log").exists())
        result = self.nemo_update(INSTALLED_VERSION="1.4.73-1", MISSING_FILES="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing downgrade", result.stderr)
        self.assertFalse((self.home / "pacman.log").exists())
        result = self.nemo_update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / "pacman.log").exists())

    def test_nemo_checksum_missing_worker_or_install_failure_never_records_version(self):
        self.package_mocks()
        for scenario in ("checksum", "worker", "install"):
            with self.subTest(scenario=scenario):
                self.nemo_release(missing="usr/libexec/nemo-archive-create-worker"
                                  if scenario == "worker" else None)
                if scenario == "checksum":
                    Path(self.env["CHECKSUMS"]).write_text("0" * 64 + "  nemo-smpl-1.4.72-1-x86_64.pkg.tar.zst\n")
                result = self.nemo_update(INSTALL_FAIL="1" if scenario == "install" else "0")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.home / "state/nemo-smpl").exists())

    def test_older_nemo_release_without_checksums_reports_metadata_only_validation(self):
        self.nemo_release()
        self.package_mocks()
        release = Path(self.env["NEMO_RELEASE_JSON"])
        data = json.loads(release.read_text())
        data["assets"] = data["assets"][:1]
        release.write_text(json.dumps(data))
        result = self.nemo_update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("metadata and payload only", result.stderr)

    def test_iso_nemo_missing_cached_artifact_repairs_and_failure_keeps_old_archive(self):
        archive = self.nemo_release()
        self.seed(self.cache, self.cache / ".smpl-apps-version", "v0.8.23")
        (self.cache / ".nemo-smpl-version").write_text("v1.4.72\n")
        prebuilt = self.project / "build/prebuilt"
        prebuilt.mkdir(parents=True)
        old = prebuilt / "nemo-smpl-1.4.71-1-x86_64.pkg.tar.zst"
        old.write_bytes(b"previous archive")
        result = self.iso_download(FAIL_DOWNLOAD="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(old.read_bytes(), b"previous archive")
        result = self.iso_download()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((prebuilt / "nemo-smpl-1.4.72-1-x86_64.pkg.tar.zst").read_bytes(), archive.read_bytes())
        self.assertEqual(old.read_bytes(), b"previous archive")

    def test_iso_refuses_source_only_nemo_release(self):
        self.nemo_release()
        self.seed(self.cache, self.cache / ".smpl-apps-version", "v0.8.23")
        release = Path(self.env["NEMO_RELEASE_JSON"])
        release.write_text(json.dumps({"tag_name": "v1.4.72", "assets": []}))
        result = self.iso_download()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no package or rootfs asset", result.stderr)

    def test_grafium_build_drops_root_to_exact_invoker_home_without_sudo_makepkg(self):
        path = ROOT / "src/shared/bin/smplos-update-apps"
        build = self.home / "build"
        build.mkdir()
        self.mock("getent", '#!/bin/bash\nprintf "desktop:x:1001:1001::%s:/bin/bash\\n" "$HOME"\n')
        self.mock("chown", '#!/bin/bash\n[[ "$*" == "-R 1001 $HOME/build" ]]\n')
        self.mock("runuser", '''#!/bin/bash
printf '%s\\n' "$@" > "$HOME/runuser.log"
[[ "$1 $2 $3" == "-u desktop --" ]] || exit 99
shift 3
exec "$@"
''')
        self.mock("makepkg", '''#!/bin/bash
[[ "$USER" == desktop && "$XDG_CONFIG_HOME" == "$HOME/.config" && "$PKGVER_OVERRIDE" == 0.0.148 ]] || exit 99
echo "$*" > "$HOME/makepkg.log"
''')
        source = function(path, "build_grafium_package").replace('[[ $EUID -eq 0 ]]', '[[ 1 -eq 1 ]]')
        result = self.shell(source + '\nwarn() { echo "$*" >&2; }\nSMPLOS_INVOKER_UID=1001\n'
                            'build_grafium_package "$HOME/build" 0.0.148')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.home / "makepkg.log").read_text(), "-c --noconfirm\n")
        self.assertIn(f"HOME={self.home}", (self.home / "runuser.log").read_text())
        result = self.shell(source + '\nwarn() { echo "$*" >&2; }\nSMPLOS_INVOKER_UID=0\n'
                            'build_grafium_package "$HOME/build" 0.0.148')
        self.assertNotEqual(result.returncode, 0)

    def test_grafium_custom_launchers_and_pins_preserved_report_incomplete(self):
        wrapper = self.home / ".local/bin/grafium"
        pins = self.home / ".config/smplos/pinned-apps.txt"
        desktop = self.home / ".local/share/applications/grafium.desktop"
        for target, text in ((wrapper, "#!/bin/sh\nexec ~/.local/lib/grafium/test/grafium-bin\n"),
                             (pins, f'"{wrapper}"\n'), (desktop, f"Exec={wrapper}\n")):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        before = [path.read_bytes() for path in (wrapper, pins, desktop)]
        source = function(ROOT / "src/shared/bin/smplos-update-apps", "grafium_launchers_current")
        result = self.shell(source + '\nwarn() { echo "$*" >&2; }\ngrafium_launchers_current')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("delivery incomplete", result.stderr)
        self.assertEqual(before, [path.read_bytes() for path in (wrapper, pins, desktop)])

    def test_grafium_update_accepts_canonical_migration_without_modifying_launchers(self):
        self.package_mocks()
        links = [self.home / suffix for suffix in (
            ".local/bin/grafium", ".local/bin/grafium-bin",
            ".local/share/smplos/bin/grafium", "bin/grafium",
        )]
        for link in links:
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to("/usr/bin/grafium")
        targets = [self.home / ".local/share/applications" / (name + ".desktop")
                   for name in ("grafium", "grafium-bin", "Grafium")]
        for target, command in zip(targets, (f'"{links[0]}" %U', f'"{links[1]}"', str(links[0]))):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f'[Desktop Entry]\nExec={command}\n')
        pins = self.home / ".config/smplos/pinned-apps.txt"
        pins.parent.mkdir(parents=True, exist_ok=True)
        pins.write_text(f'"/usr/bin/grafium"\n"{links[0]}"\n"{links[1]}"\ncustom --command\n')
        targets.append(pins)
        before = {path: path.read_bytes() for path in targets}
        self.mock("curl", """#!/bin/bash
[[ "$*" == *https://api.github.com/repos/KonTy/grafium/releases/latest* ]] || exit 99
printf '{"tag_name":"v0.0.149","assets":[]}\\n'
""")
        updater = ROOT / "src/shared/bin/smplos-update-apps"
        source = f'source "{ROOT}/src/shared/lib/smplos-release-package.sh"\n'
        source += "\n".join(function(updater, name) for name in (
            "_gh_api", "_cached_ver", "grafium_launchers_current", "update_grafium",
        ))
        source += """
STATE_DIR="$HOME/state"; mkdir -p "$STATE_DIR"
warn() { echo "$*" >&2; }; ok() { echo "$*"; }
update_grafium
"""
        result = self.shell(source, INSTALLED_VERSION="0.0.149-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("installed package is current", result.stdout)
        self.assertNotIn("delivery incomplete", result.stderr)
        self.assertFalse((self.home / "pacman.log").exists())
        self.assertEqual(before, {path: path.read_bytes() for path in targets})
        self.assertTrue(all(link.is_symlink() and os.readlink(link) == "/usr/bin/grafium"
                            for link in links))

    def test_grafium_alias_reference_allowance_does_not_accept_custom_paths_or_proxies(self):
        alias = self.home / ".local/bin/grafium"
        alias.parent.mkdir(parents=True)
        alias.symlink_to("/usr/bin/grafium")
        pins = self.home / ".config/smplos/pinned-apps.txt"
        pins.parent.mkdir(parents=True)
        source = function(ROOT / "src/shared/bin/smplos-update-apps", "grafium_launchers_current")
        script = source + '\nwarn() { echo "$*" >&2; }\ngrafium_launchers_current'
        for target in (str(alias) + "-custom", str(alias) + "/child",
                       str(alias) + ".backup", str(alias) + "%U",
                       "sh -c " + str(alias),
                       str(self.home / ".local/lib/grafium/build/grafium-bin")):
            with self.subTest(target=target):
                pins.write_text(f'"{target}"\n')
                result = self.shell(script)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("delivery incomplete", result.stderr)
                self.assertEqual(pins.read_text(), f'"{target}"\n')
        desktop = self.home / ".local/share/applications/grafium.desktop"
        desktop.parent.mkdir(parents=True)
        pins.write_text(f'"{alias}"\n')
        desktop.write_text(f'[Desktop Entry]\nExec=sh -c "{alias}"\n')
        result = self.shell(script)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("preserved custom launch target", result.stderr)
        desktop.write_text(f"[Desktop Entry]\nExec={alias}\n")
        for destination in ("/usr/bin/false", str(self.home / "missing-grafium")):
            with self.subTest(destination=destination):
                alias.unlink()
                alias.symlink_to(destination)
                result = self.shell(script)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("preserved local launcher", result.stderr)
                self.assertIn("preserved custom launch target", result.stderr)
        alias.unlink()
        alias.write_text('#!/bin/sh\nexec /usr/bin/grafium "$@"\n')
        pins.write_text(f'"{alias}"\n')
        result = self.shell(script)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("preserved local launcher", result.stderr)
        self.assertIn("preserved custom launch target", result.stderr)
        self.assertEqual(alias.read_text(), '#!/bin/sh\nexec /usr/bin/grafium "$@"\n')

    @unittest.skipUnless(shutil.which("bsdtar") and shutil.which("ar"), "Debian archive tools unavailable")
    def test_grafium_pkgbuild_downloads_versioned_deb_and_installs_expected_paths(self):
        rootfs = self.base / "deb-root"
        binary = rootfs / "usr/bin/grafium"
        desktop = rootfs / "usr/share/applications/Grafium.desktop"
        library = rootfs / "usr/lib/Grafium/libllama.so.0"
        for path, data in ((binary, b"\x7fELFgrafium"),
                           (desktop, b"[Desktop Entry]\nExec=grafium\n"),
                           (library, b"\x7fELFbundled-ai")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        bundled_sonames = ("libllama-common.so.0", "libggml.so.0", "libggml-cpu.so.0",
                           "libggml-vulkan.so.0", "libggml-base.so.0")
        for name in bundled_sonames:
            versioned = library.parent / (name + ".1")
            versioned.write_bytes(b"\x7fELF" + name.encode())
            (library.parent / name).symlink_to(versioned.name)
        data_archive = self.base / "data.tar.gz"
        with tarfile.open(data_archive, "w:gz") as archive:
            archive.add(rootfs / "usr", arcname="usr")
        (self.base / "debian-binary").write_text("2.0\n")
        deb = self.base / "Grafium_0.0.148_amd64.deb"
        subprocess.run(["ar", "rc", str(deb), "debian-binary", "data.tar.gz"],
                       cwd=self.base, check=True, capture_output=True)
        srcdir = self.base / "source"
        pkgdir = self.base / "package"
        srcdir.mkdir()
        pkgdir.mkdir()
        result = self.shell(f"""
source "{ROOT}/src/shared/pkgbuilds/grafium-bin/PKGBUILD"
srcdir="{srcdir}"; pkgdir="{pkgdir}"; PKGVER_OVERRIDE=0.0.148
prepare
[[ "$(pkgver)" == 0.0.148 ]]
package
""", ARCHIVE=str(deb))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/releases/download/v0.0.148/Grafium_0.0.148_amd64.deb", self.requests.read_text())
        self.assertEqual((pkgdir / "usr/bin/grafium").read_bytes(), b"\x7fELFgrafium")
        self.assertEqual((pkgdir / "usr/lib/Grafium/libllama.so.0").read_bytes(), library.read_bytes())
        for name in bundled_sonames:
            installed = pkgdir / "usr/lib/Grafium" / name
            self.assertTrue(installed.is_symlink())
            self.assertEqual(os.readlink(installed), name + ".1")
            self.assertEqual(installed.read_bytes(), b"\x7fELF" + name.encode())
        self.assertFalse((pkgdir / "usr/lib/grafium").exists())
        self.assertEqual((pkgdir / "usr/share/applications/Grafium.desktop").read_bytes(), desktop.read_bytes())

    def test_nemo_rootfs_package_declares_new_worker_dependencies(self):
        source = ROOT / "src/shared/pkgbuilds/nemo-smpl/PKGBUILD"
        result = self.shell(f'source "{source}"; printf "%s\\n" "${{depends[@]}}"')
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("md4c", "poppler-glib", "mupdf-tools", "bubblewrap", "libarchive", "sqlite", "libisofs"):
            self.assertIn(name, result.stdout.splitlines())

    def test_independent_app_failures_continue_but_final_status_is_nonzero(self):
        main = (ROOT / "src/shared/bin/smplos-update-apps").read_text().split("# ── Main", 1)[1].split("\n", 1)[1]
        script = """
STATE_DIR="$HOME/state"; SMPLOS_PATH="$HOME/data"; CHECK_ONLY=0; QUIET=1; SMPLOS_APP_BINS=()
n_updated=0
warn() { echo "$*" >&2; }; ok() { :; }
update_smpl_apps() { echo native-start; false; echo must-not-reach; }
update_st_smpl() { echo terminal; }
update_nemo_smpl() { echo nemo; }
update_micro_smpl() { echo editor; }
update_grafium() { echo grafium; }
rebuild-app-cache() { echo cache; }
"""
        result = self.shell(script + main)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("must-not-reach", result.stdout)
        for name in ("terminal", "nemo", "editor", "grafium", "cache"):
            self.assertIn(name, result.stdout)
        self.assertIn("incomplete", result.stderr)

    def test_full_wrapper_records_component_failures_and_executes_new_app_script_after_os(self):
        source = (ROOT / "src/shared/bin/smplos-update").read_text()
        os_phase = source.split('# ── Step 1:', 1)[1].split('# ── Step 2:', 1)[0].split("\n", 1)[1]
        apps_phase = source.split('# ── Step 4:', 1)[1].split('# ── Step 5:', 1)[0].split("\n", 1)[1]
        result = self.shell("""
UPDATE_MODE=full; NETWORK_OK=1; UPDATE_FAILED=0
load_critical_packages() { :; }
smplos-os-update() { echo refreshed > "$HOME/script-version"; return 1; }
smplos-update-apps() { [[ "$(cat "$HOME/script-version")" == refreshed ]]; return 1; }
""" + os_phase + apps_phase + '\n[[ "$UPDATE_FAILED" -eq 0 ]]\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn("smplos-os-update failed", result.stdout)
        self.assertIn("smplos-update-apps failed", result.stdout)
        self.assertIn('set -o pipefail', source)
        self.assertIn('[[ "$UPDATE_FAILED" -eq 0 ]]\n} 2>&1 | tee', source)

    def test_resumed_theme_only_update_reapplies_and_invalid_resume_flags_fail(self):
        source = (ROOT / "src/shared/bin/smplos-os-update").read_text()
        condition = re.search(r'    if \[\[ \$had_updates.*?\n    fi', source, re.S).group()
        result = self.shell("""
had_updates=0; SELF_UPDATED=1; THEMES_CHANGED=0; HYPR_CONFIGS_CHANGED=0; APPS_CHANGED=0
header() { :; }; post_deploy() { echo reapplied; }
""" + condition)
        self.assertEqual(result.stdout, "reapplied\n")
        result = self.shell("""
had_updates=0; SELF_UPDATED=0; THEMES_CHANGED=1; HYPR_CONFIGS_CHANGED=0; APPS_CHANGED=0
header() { :; }; post_deploy() { echo reapplied; }
""" + condition)
        self.assertEqual(result.stdout, "reapplied\n")
        validation = source.split('case "$SELF_UPDATED:', 1)[1].split("esac", 1)[0]
        validation = 'case "$SELF_UPDATED:' + validation + "esac"
        result = self.shell('SELF_UPDATED=1; SMPLOS_OS_HAD_UPDATES=not-a-boolean\n' + validation)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid updater resume flags", result.stderr)


if __name__ == "__main__":
    unittest.main()
