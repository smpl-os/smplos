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
XR_SCRIPTS = ("xrctl", "xr-game", "xr-glasses-hotplugd")
CALENDAR_SERVICE = "smpl-calendar-alertd.service"
SERVICE_CONTENT = """[Unit]
Description=smplOS Calendar reminders
After=dbus.socket
[Service]
Type=exec
ExecStart=/usr/local/bin/smpl-calendar-alertd --foreground
Restart=on-failure
[Install]
WantedBy=default.target
"""


def function(path, name):
    source = path.read_text()
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}", source, re.M | re.S)
    if match is None:
        raise AssertionError(f"Function {name} not found in {path}")
    return match.group()


def xr_module(version):
    return {
        "xr-workspace": b"\x7fELF" + version.encode(),
        **{name: f'#!/usr/bin/env bash\nprintf "{version}-{name}" > "$HOME/xr-was-executed"\n'.encode()
           for name in XR_SCRIPTS},
    }


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
                     "src/shared/lib/smplos-app-bundle.sh",
                     "src/shared/lib/smplos-update-entry.sh",
                     "src/shared/lib/smplos-session-env.sh",
                     "src/shared/bin/smplos-update-handoff",
                     "src/shared/update-policy/legacy-update-runners.sha256"):
            target = self.project / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target)
        self.library = self.project / "src/shared/lib/smplos-app-bundle.sh"
        self.library.write_text(self.isolate_unit_paths(self.library.read_text()))
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "LC_ALL": "C",
            "PROJECT_ROOT": str(self.project),
            "RELEASE_JSON": str(self.release),
            "ARCHIVE": str(self.archive),
            "REQUEST_LOG": str(self.requests),
            "XDG_RUNTIME_DIR": str(self.base / "runtime"),
        }
        self.mock("curl", MOCK_CURL)
        self.mock("gh", "#!/bin/bash\nexit 1\n")
        # Any accidental real update/build operation must fail, not touch the host.
        for name in ("sudo", "pkill", "pacman", "makepkg", "podman", "docker", "nohup"):
            self.mock(name, f'#!/bin/bash\necho "FORBIDDEN: {name}" >&2\nexit 99\n')
        self.mock("pgrep", "#!/bin/bash\nexit 1\n")
        self.mock("ldd", "#!/bin/bash\necho 'libc.so.6 => /usr/lib/libc.so.6'\n")
        self.mock("systemctl", '#!/bin/bash\necho "FORBIDDEN: systemctl" >&2\nexit 99\n')
        self.publish()

    def mock(self, name, contents):
        path = self.bin / name
        path.write_text(contents)
        path.chmod(0o755)

    def isolate_unit_paths(self, source):
        for path in ("/etc/systemd/user", "/run/systemd/user",
                     "/usr/local/lib/systemd/user", "/usr/lib/systemd/user"):
            source = source.replace(path, str(self.base / "system-units") + path)
        return source

    def publish(self, missing=None, corrupt=None, asset=True, xr_script=None, xr_files=None):
        url = "https://github.com/smpl-os/smpl-apps/releases/download/v0.8.23/smpl-apps-0.8.23-x86_64.tar.gz"
        self.release.write_text(json.dumps({
            "tag_name": "v0.8.23",
            "assets": [{"browser_download_url": url}] if asset else [],
        }, indent=2))
        with tarfile.open(self.archive, "w:gz") as archive:
            files = {app: b"\x7fELFnew-" + app.encode() for app in (*APPS, "xrctl")}
            files.update(xr_files or {})
            for app, data in files.items():
                if app == missing:
                    continue
                if app == corrupt:
                    data = b"broken"
                if app == "xrctl" and xr_script is not None:
                    data = xr_script
                info = tarfile.TarInfo(app)
                info.size = len(data)
                info.mode = 0o755
                archive.addfile(info, io.BytesIO(data))
            if missing != CALENDAR_SERVICE:
                data = (b"ExecStart=smpl-calendar-alertd\n"
                        if corrupt == CALENDAR_SERVICE else SERVICE_CONTENT.encode())
                info = tarfile.TarInfo(CALENDAR_SERVICE)
                info.size = len(data)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(data))

    def seed(self, directory, marker=None, version="v0.8.22"):
        directory.mkdir(parents=True, exist_ok=True)
        for app in APPS:
            (directory / app).write_bytes(b"\x7fELFold-" + app.encode())
        (directory / CALENDAR_SERVICE).write_text(SERVICE_CONTENT)
        if marker:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(version + "\n")

    def shell(self, script, **env):
        script = script.replace(f'source "{LIB}"', f'source "{self.library}"')
        script = self.isolate_unit_paths(script)
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

    def assert_service(self, directory):
        service = directory / CALENDAR_SERVICE
        self.assertEqual(service.read_text(), SERVICE_CONTENT)
        self.assertEqual(service.stat().st_mode & 0o777, 0o644)

    def test_fetch_apps_and_iso_share_one_marker_and_skip_current_download(self):
        result = self.run_fetcher("fetch-apps.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_new_bundle(self.cache)
        self.assert_service(self.cache)
        self.assertEqual((self.cache / ".smpl-apps-version").read_text(), "v0.8.23\n")
        self.assertFalse((self.cache / "smpl-apps.fetched-version").exists())
        result = self.iso_download()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests.read_text().count("/releases/download/"), 1)

    def test_fetchers_preserve_all_published_xr_wrappers_without_executing_them(self):
        module = xr_module("new")
        self.publish(xr_files=module)
        for fetcher, directory in (
            ("fetch-apps.sh", self.cache),
            ("fetch-org.sh", self.project / ".cache/org-binaries/bin"),
        ):
            with self.subTest(fetcher=fetcher):
                result = self.run_fetcher(fetcher)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assert_new_bundle(directory)
                for name, data in module.items():
                    self.assertEqual((directory / name).read_bytes(), data)
                    self.assertTrue(os.access(directory / name, os.X_OK))
                self.assertFalse((self.home / "xr-was-executed").exists())
        result = self.iso_download()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, data in module.items():
            self.assertEqual((self.cache / name).read_bytes(), data)

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

    def test_missing_service_repairs_matching_cached_tag_in_all_fetchers(self):
        for fetcher, directory, marker in (
            ("fetch-apps.sh", self.cache, self.cache / ".smpl-apps-version"),
            ("fetch-org.sh", self.project / ".cache/org-binaries/bin",
             self.project / ".cache/org-binaries/.versions/smpl-apps"),
        ):
            with self.subTest(fetcher=fetcher):
                self.seed(directory, marker, "v0.8.23")
                (directory / CALENDAR_SERVICE).unlink()
                result = self.run_fetcher(fetcher)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_service(directory)

    def test_missing_or_incompatible_service_rejects_release_before_staging(self):
        marker = self.cache / ".smpl-apps-version"
        self.seed(self.cache, marker)
        for problem in ("missing", "corrupt"):
            with self.subTest(problem=problem):
                self.publish(**{problem: CALENDAR_SERVICE})
                result = self.run_fetcher("fetch-apps.sh")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("calendar reminder service", result.stderr)
                self.assertEqual(marker.read_text(), "v0.8.22\n")
                self.assertEqual((self.cache / "smpl-calendar").read_bytes(),
                                 b"\x7fELFold-smpl-calendar")

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
        self.assert_service(self.cache)

    def test_app_updater_validates_before_install_or_version_write(self):
        path = ROOT / "src/shared/bin/smplos-update-apps"
        state = self.home / ".local/state/smplos/app-versions"
        state.mkdir(parents=True)
        (state / "smpl-apps").write_text("v0.8.22\n")
        script = f'source "{LIB}"\n'
        script += "\n".join(function(path, name) for name in
                            ("_gh_api", "_version_gt", "_cached_ver",
                             "repair_release_allowed", "update_smpl_apps"))
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

    def app_updater_fixture(self):
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
                            ("_gh_api", "_version_gt", "_cached_ver",
                             "component_files_current", "record_component_files",
                             "repair_release_allowed"))
        script += "\n" + source + """
STATE_DIR="$HOME/.local/state/smplos/app-versions"
CHECK_ONLY=0; QUIET=0; n_updated=0
log() { :; }; ok() { :; }; warn() { echo "$*" >&2; }
update_smpl_apps
"""
        return state, installed, pins, script

    def test_app_updater_installs_complete_release_without_modifying_pins(self):
        state, installed, pins, script = self.app_updater_fixture()
        result = self.shell(script, FAIL_INSTALL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((state / "smpl-apps").read_text(), "v0.8.22\n")
        for app in APPS:
            self.assertEqual((installed / app).read_bytes(), b"\x7fELFold-" + app.encode())
        self.assertEqual(sorted(path.name for path in installed.iterdir()),
                         sorted((*APPS, CALENDAR_SERVICE)))
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_new_bundle(installed)
        self.assert_service(self.home / ".config/systemd/user")
        self.assertEqual((state / "smpl-apps").read_text(), "v0.8.23\n")
        self.assertEqual(pins.read_text(), '"grafium"\ncustom --command\n')
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests.read_text().count("/releases/download/"), 2)
        (installed / "settings").write_bytes(b"\x7fELFtampered")
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_new_bundle(installed)
        self.assertEqual(self.requests.read_text().count("/releases/download/"), 3)
        (installed / "settings").chmod(0o644)
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_new_bundle(installed)
        receipt = state / "smpl-apps.sha256"
        receipt.write_text(receipt.read_text().splitlines()[0] + "\n")
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(receipt.read_text().splitlines()), len(APPS) + 1)
        self.assertIn(str(installed / "xrctl"), receipt.read_text())
        optional = installed / "xrctl"
        original_optional = optional.read_bytes()
        self.publish(missing="xrctl")
        (state / "smpl-apps").write_text("v0.8.22\n")
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not upgraded", result.stderr)
        self.assertEqual(optional.read_bytes(), original_optional)
        retained = state / "smpl-apps-retained.sha256"
        self.assertIn(str(optional), retained.read_text())
        self.assertNotIn(str(optional), receipt.read_text())
        downloads = self.requests.read_text().count("/releases/download/")
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests.read_text().count("/releases/download/"), downloads)
        retained.unlink()
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(optional), retained.read_text())
        self.assertEqual(self.requests.read_text().count("/releases/download/"), downloads + 1)
        optional.write_bytes(b"\x7fELFtampered-optional")
        result = self.shell(script)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("differs from its checksum receipt", result.stderr)
        optional.write_bytes(original_optional)
        receipt.unlink()
        retained.unlink()
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(str(optional), receipt.read_text())
        self.assertIn(str(optional), retained.read_text())
        optional.unlink()
        result = self.shell(script)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot safely retain", result.stderr)
        self.publish()
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(retained.read_text(), "")
        downloads = self.requests.read_text().count("/releases/download/")
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests.read_text().count("/releases/download/"), downloads)
        workspace = installed / "xr-workspace"
        workspace.write_bytes(b"\x7fELFold-workspace")
        workspace.chmod(0o755)
        self.publish(corrupt="xrctl")
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(optional.read_bytes(), original_optional)
        self.assertEqual(workspace.read_bytes(), b"\x7fELFold-workspace")
        self.assertEqual(len(retained.read_text().splitlines()), 2)
        self.mock("ldd", """#!/bin/bash
if [[ "$1" == */xr-workspace ]]; then
    echo 'libmissing.so => not found'
    exit 1
fi
echo 'libc.so.6 => /usr/lib/libc.so.6'
""")
        (state / "smpl-apps").write_text("v0.8.22\n")
        result = self.shell(script)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("libmissing.so", result.stderr)
        self.assertIn("cannot safely retain", result.stderr)
        (state / "smpl-apps").write_text("v99.0.0\n")
        receipt.unlink()
        result = self.shell(script)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing a downgrade", result.stderr)
        self.assert_new_bundle(installed)

    def test_app_updater_retains_or_delivers_xrctl_bash_without_executing_it(self):
        state, installed, _, script = self.app_updater_fixture()
        optional = installed / "xrctl"
        legacy = b'#!/usr/bin/env bash\nprintf bad > "$HOME/xr-was-executed"\n'
        optional.write_bytes(legacy)
        optional.chmod(0o755)
        self.publish(missing="xrctl")
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_new_bundle(installed)
        self.assertEqual(optional.read_bytes(), legacy)
        self.assertIn(str(optional), (state / "smpl-apps-retained.sha256").read_text())
        self.assertNotIn(str(optional), (state / "smpl-apps.sha256").read_text())
        self.assertFalse((self.home / "xr-was-executed").exists())
        downloads = self.requests.read_text().count("/releases/download/")
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.requests.read_text().count("/releases/download/"), downloads)
        optional.write_bytes(legacy + b"# changed\n")
        result = self.shell(script)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("differs from its checksum receipt", result.stderr)
        fresh = b'#!/bin/bash\nprintf fresh > "$HOME/xr-was-executed"\n'
        self.publish(xr_script=fresh)
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(optional.read_bytes(), fresh)
        self.assertTrue(os.access(optional, os.X_OK))
        self.assertIn(str(optional), (state / "smpl-apps.sha256").read_text())
        self.assertEqual((state / "smpl-apps-retained.sha256").read_text(), "")
        self.assertFalse((self.home / "xr-was-executed").exists())

    def test_app_updater_repairs_legacy_install_with_complete_mixed_xr_module(self):
        state, installed, pins, script = self.app_updater_fixture()
        for name, data in xr_module("old").items():
            (installed / name).write_bytes(data)
            (installed / name).chmod(0o755)
        module = xr_module("new")
        self.publish(xr_files=module)
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_new_bundle(installed)
        self.assertEqual((state / "smpl-apps").read_text(), "v0.8.23\n")
        self.assertEqual((state / "smpl-apps-retained.sha256").read_text(), "")
        receipt = (state / "smpl-apps.sha256").read_text()
        self.assertEqual(len(receipt.splitlines()), len(APPS) + len(module))
        for name, data in module.items():
            binary = installed / name
            self.assertEqual(binary.read_bytes(), data)
            self.assertTrue(os.access(binary, os.X_OK))
            self.assertIn(f"{hashlib.sha256(data).hexdigest()}  {binary}\n", receipt)
        downloads = self.requests.read_text().count("/releases/download/")
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.requests.read_text().count("/releases/download/"), downloads)
        (installed / "xr-game").unlink()
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((installed / "xr-game").read_bytes(), module["xr-game"])
        self.assertEqual(pins.read_text(), '"grafium"\ncustom --command\n')
        self.assertFalse((self.home / "xr-was-executed").exists())

    def test_app_updater_retains_whole_script_module_and_rejects_tampering(self):
        state, installed, _, script = self.app_updater_fixture()
        module = xr_module("old")
        for name, data in module.items():
            (installed / name).write_bytes(data)
            (installed / name).chmod(0o755)
        self.publish(missing="xrctl")
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        retained = state / "smpl-apps-retained.sha256"
        self.assertEqual(len(retained.read_text().splitlines()), len(module))
        for name, data in module.items():
            binary = installed / name
            self.assertEqual(binary.read_bytes(), data)
            self.assertIn(str(binary), retained.read_text())
            self.assertNotIn(str(binary), (state / "smpl-apps.sha256").read_text())
        for name in XR_SCRIPTS:
            with self.subTest(tampered=name):
                (installed / name).write_bytes(module[name] + b"# changed\n")
                result = self.shell(script)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("differs from its checksum receipt", result.stderr)
                (installed / name).write_bytes(module[name])
        self.publish(xr_files=xr_module("new"))
        (state / "smpl-apps").write_text("v0.8.22\n")
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(retained.read_text(), "")
        for name, data in xr_module("new").items():
            self.assertEqual((installed / name).read_bytes(), data)
        self.assertFalse((self.home / "xr-was-executed").exists())

    def test_xr_script_validation_is_narrow_and_never_executes_input(self):
        directory = self.base / "validation"
        directory.mkdir()
        for name in (*XR_SCRIPTS, "xr-workspace", "settings", "unknown"):
            path = directory / name
            for data, valid in (
                (b'#!/bin/bash\nprintf bad > "$HOME/xr-was-executed"\n', name in XR_SCRIPTS),
                (b"#!/usr/bin/env bash\nif then\n", False),
                (b"#!/usr/bin/python3\npass\n", False),
            ):
                with self.subTest(name=name, data=data):
                    path.write_bytes(data)
                    result = self.shell(f'source "{LIB}"\nsmplos_xr_file_valid "{path}"')
                    self.assertEqual(result.returncode == 0, valid, result.stdout + result.stderr)
                    self.assertFalse((self.home / "xr-was-executed").exists())
        target = directory / "target"
        target.write_text("#!/bin/bash\nexit 0\n")
        for name in XR_SCRIPTS:
            path = directory / name
            path.unlink()
            path.symlink_to(target)
            result = self.shell(f'source "{LIB}"\nsmplos_xr_file_valid "{path}"')
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

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
        for target in ("etc/skel/.config/systemd/user", "root/smplos/config/systemd/user"):
            units = profile / "airootfs" / target
            self.assert_service(units)
            link = units / "default.target.wants" / CALENDAR_SERVICE
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.readlink(), Path("..") / CALENDAR_SERVICE)
            self.assertEqual(link.read_text(), SERVICE_CONTENT)

    def install_service(self):
        source = self.base / CALENDAR_SERVICE
        source.write_text(SERVICE_CONTENT)
        return self.shell(f'source "{LIB}"\nsmplos_install_calendar_service "{source}"')

    def test_service_first_install_enables_login_without_live_operations(self):
        result = self.install_service()
        self.assertEqual(result.returncode, 0, result.stderr)
        units = self.home / ".config/systemd/user"
        self.assert_service(units)
        self.assertTrue((units / "default.target.wants" / CALENDAR_SERVICE).is_symlink())
        self.assertFalse((self.home / ".local/share/smplos/calendar/events.db").exists())

    def test_service_reinstall_preserves_disabled_and_removed_choices(self):
        self.assertEqual(self.install_service().returncode, 0)
        units = self.home / ".config/systemd/user"
        link = units / "default.target.wants" / CALENDAR_SERVICE
        link.unlink()
        self.assertEqual(self.install_service().returncode, 0)
        self.assertFalse(link.exists())
        (units / CALENDAR_SERVICE).unlink()
        result = self.install_service()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("preserving removed", result.stderr)
        self.assertFalse((units / CALENDAR_SERVICE).exists())

    def test_service_preserves_custom_units_and_masks(self):
        units = self.home / ".config/systemd/user"
        units.mkdir(parents=True)
        target = units / CALENDAR_SERVICE
        target.write_text("custom service\n")
        result = self.install_service()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_text(), "custom service\n")
        target.unlink()
        target.symlink_to("/dev/null")
        result = self.install_service()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.readlink(), Path("/dev/null"))
        self.assertFalse((units / "default.target.wants" / CALENDAR_SERVICE).exists())

    def test_service_does_not_override_runtime_mask(self):
        runtime = self.base / "runtime/systemd/user"
        runtime.mkdir(parents=True)
        (runtime / CALENDAR_SERVICE).symlink_to("/dev/null")
        result = self.install_service()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("preserving existing", result.stderr)
        self.assertFalse((self.home / ".config/systemd/user" / CALENDAR_SERVICE).exists())

    def test_service_does_not_override_system_wide_unit(self):
        units = self.base / "system-units/usr/local/lib/systemd/user"
        units.mkdir(parents=True)
        (units / CALENDAR_SERVICE).write_text("custom system-wide unit\n")
        result = self.install_service()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("preserving existing", result.stderr)
        self.assertFalse((self.home / ".config/systemd/user" / CALENDAR_SERVICE).exists())

    def test_service_updates_owned_unit_but_keeps_enabled_state(self):
        self.assertEqual(self.install_service().returncode, 0)
        units = self.home / ".config/systemd/user"
        old = SERVICE_CONTENT.replace("Restart=on-failure", "Restart=always")
        (units / CALENDAR_SERVICE).write_text(old)
        (self.home / ".local/state/smplos/calendar-service/last-installed.service").write_text(old)
        result = self.install_service()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_service(units)

    def test_elevated_service_install_passes_private_source_to_desktop_user(self):
        source = self.base / CALENDAR_SERVICE
        source.write_text(SERVICE_CONTENT)
        source.chmod(0o600)
        self.mock("getent", '#!/bin/bash\nprintf "desktop:x:1001:1001::%s:/bin/bash\\n" "$HOME"\n')
        self.mock("runuser", '''#!/bin/bash
[[ "$1 $2 $3" == "-u desktop --" ]] || exit 99
shift 3
export SIMULATE_ROOT=0
exec "$@"
''')
        helpers = LIB.read_text().replace(
            'if [[ $EUID -eq 0 ]]; then', 'if [[ "${SIMULATE_ROOT:-0}" == 1 ]]; then')
        result = self.shell(helpers + f'\nsmplos_install_calendar_service "{source}"',
                            SIMULATE_ROOT="1", SMPLOS_INVOKER_UID="1001")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_service(self.home / ".config/systemd/user")

    def test_org_updater_never_installs_service_as_an_executable(self):
        stage = self.project / ".cache/org-binaries/bin"
        self.seed(stage)
        (self.project / "src/fetch-org.sh").write_text("#!/bin/bash\nexit 0\n")
        library = self.project / "src/shared/lib/smplos-app-bundle.sh"
        with library.open("a") as output:
            output.write('''\nsmplos_install_app_binary() {
    echo "$2" >> "$HOME/binary-installs"
}
''')
        script = function(ROOT / "src/shared/bin/smplos-os-update", "sync_apps")
        script += '''
SMPLOS_REPO="$PROJECT_ROOT"
header() { :; }; ok() { :; }; warn() { echo "$*" >&2; }
die() { echo "$*" >&2; exit 1; }
sync_apps
'''
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(CALENDAR_SERVICE, (self.home / "binary-installs").read_text())
        self.assert_service(self.home / ".config/systemd/user")

    def test_os_update_delivers_launcher_scripts_cache_and_volume_widget(self):
        scripts = ("smplos-settings", "rebuild-app-cache")
        for relative in (*(f"bin/{name}" for name in scripts),
                         "eww/eww.yuck", "eww/eww.scss"):
            target = self.project / "src/shared" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "src/shared" / relative, target)
        installed = self.base / "installed-bin"
        installed.mkdir()
        for name in scripts:
            (installed / name).write_text("#!/bin/bash\nexit 97\n")
        eww = self.home / ".config/eww/eww.yuck"
        eww.parent.mkdir(parents=True)
        eww.write_text("old widget\n")
        cache = self.home / ".cache/smplos/app_index"
        cache.parent.mkdir(parents=True)
        cache.write_text("old cache\n")
        self.mock("find", """#!/bin/bash
[[ "$1" == /var/lib/flatpak/* ]] && exit 0
exec /usr/bin/find "$@"
""")
        updater = ROOT / "src/shared/bin/smplos-os-update"
        sync = function(updater, "sync_scripts")
        self.assertIn('dest="/usr/local/bin/$name"', sync)
        sync = sync.replace('dest="/usr/local/bin/$name"', 'dest="$FIXTURE_BIN/$name"')
        script = """
SMPLOS_REPO="$PROJECT_ROOT"
header() { :; }; ok() { echo "$*"; }; die() { echo "$*" >&2; exit 1; }
as_invoker() { "$@"; }
sudo() {
    [[ "$1" == install || "$1" == mktemp || "$1" == mv || "$1" == rm ]] || return 99
    [[ "${@: -1}" == "$FIXTURE_BIN/"* ]] || return 99
    "$@"
}
sync_libs() { :; }; sync_config_defaults() { :; }
"""
        script += "\n".join((function(updater, "install_system_file"), sync,
                              function(updater, "copy_user_config"),
                              function(updater, "sync_configs")))
        script += "\nsync_scripts\nsync_configs\nrebuild-app-cache\n" * 2
        result = self.shell(
            script, FIXTURE_BIN=str(installed), PATH=f"{installed}:{self.env['PATH']}",
            XDG_DATA_HOME=str(self.base / "data-home"),
            XDG_DATA_DIRS=str(self.base / "data-dirs"),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        script_count = len(list((self.project / "src/shared/bin").iterdir()))
        self.assertIn(f"All {script_count} scripts are current", result.stdout)
        self.assertIn("All configs are current", result.stdout)
        for name in scripts:
            self.assertEqual((installed / name).read_bytes(),
                             (ROOT / "src/shared/bin" / name).read_bytes())
            self.assertEqual((installed / name).stat().st_mode & 0o777, 0o755)
        self.assertEqual(eww.read_bytes(), (ROOT / "src/shared/eww/eww.yuck").read_bytes())
        self.assertEqual(eww.stat().st_mode & 0o777, 0o644)
        rows = {row[0]: row for row in
                (line.split(";") for line in cache.read_text().splitlines())}
        for name in ("Volume", "Sound", "Speakers", "Output Device", "Input Device"):
            self.assertEqual(rows[name][1], "smplos-settings audio")
            self.assertEqual(rows[name][-1], "1")

    def test_update_mains_refresh_even_without_new_binaries_and_report_failure(self):
        for name in ("smplos-os-update", "smplos-update-apps"):
            path = ROOT / "src/shared/bin" / name
            main = path.read_text().split("# ── Main", 1)[1].split("\n", 1)[1]
            stubs = """
CHECK_ONLY=0; MIGRATE_ONLY=0; SCRIPTS_ONLY=0; DEPLOY_ONLY=0; FINALIZE_ONLY=0; QUIET=1; n_updated=0
STATE_DIR="$HOME/state"; SMPLOS_PATH="$HOME/data"; SMPLOS_APP_BINS=()
SMPLOS_REPO="$PROJECT_ROOT"
REPORT_FILE="$HOME/apps.json"; REPORT_WORK="$HOME/results"
mkdir -p "$REPORT_WORK"
installed_component_version() { :; }; record_app_result() { :; }; log() { :; }
SELF_UPDATED=1; SELF_CANONICAL="$HOME/no-installed-script"
header() { :; }; ok() { :; }; warn() { echo "$*" >&2; }
die() { echo "$*" >&2; exit 1; }
pull_updates() { return 1; }
sync_scripts() { echo scripts-synced; }; sync_configs() { echo configs-synced; }; sync_themes() { :; }
sync_apps() { :; }; sync_hypr_configs() { :; }; sync_user_units() { :; }; run_migrations() { :; }
sync_plugins() { :; }
sync_keypad_support() { :; }
sync_mouse_support() { :; }
sync_hypridle_config() { :; }
cleanup_shadow_bins() { :; }; post_deploy() { :; }
update_smpl_apps() { :; }; update_st_smpl() { :; }; update_nemo_smpl() { :; }
update_micro_smpl() { :; }; update_control_surface() { :; }
rebuild-app-cache() { echo refreshed; return "$CACHE_STATUS"; }
"""
            for status in ("0", "1"):
                with self.subTest(updater=name, status=status):
                    result = self.shell(stubs + main, CACHE_STATUS=status)
                    self.assertEqual(result.stdout.count("refreshed"), 1)
                    self.assertEqual(result.returncode, int(status), result.stderr)
                    if name == "smplos-os-update":
                        self.assertEqual(result.stdout.count("scripts-synced"), 1)
                        self.assertEqual(result.stdout.count("configs-synced"), 1)
            if name == "smplos-os-update":
                result = self.shell(stubs + "\nSCRIPTS_ONLY=1\n" + main, CACHE_STATUS="0")
                self.assertEqual(result.stdout.count("refreshed"), 1)
            else:
                result = self.shell(stubs + "\nCHECK_ONLY=1\n" + main, CACHE_STATUS="0")
                self.assertNotIn("refreshed", result.stdout)

    def test_new_user_cache_is_generated_not_shipped(self):
        builder = (ROOT / "src/builder/build.sh").read_text()
        self.assertIn('install -m644 "$lib" "$airootfs/usr/local/lib/smplos/"',
                      builder)
        self.assertIn('install -m644 "$lib" "$airootfs/root/smplos/lib/"',
                      builder)
        self.assertIn('in "$SRC_DIR/shared/lib/"*.sh "$SRC_DIR/shared/lib/"*.py', builder)
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
-Q) if [[ -f "$HOME/package-version" ]]; then echo "$2 $(cat "$HOME/package-version")";
    else [[ -n "${INSTALLED_VERSION:-}" ]] || exit 1; echo "$2 $INSTALLED_VERSION"; fi;;
-Qkk) exit "${MISSING_FILES:-0}";;
-U) echo "$*" >> "$HOME/pacman.log"
    if [[ "${INSTALL_FAIL:-0}" = 0 && "${INSTALL_NOOP:-0}" = 0 ]]; then echo "${PACKAGE_TARGET:-1.4.72-1}" > "$HOME/package-version"; fi
    exit "${INSTALL_FAIL:-0}";;
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

    def test_nemo_success_exit_without_installation_does_not_record_the_target(self):
        self.nemo_release()
        self.package_mocks()
        result = self.nemo_update(INSTALLED_VERSION="1.4.71-1", INSTALL_NOOP="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not reach intact package", result.stderr)
        self.assertFalse((self.home / "state/nemo-smpl").exists())

    def test_nemo_package_revision_is_not_hidden_by_unchanged_release_tag(self):
        self.nemo_release()
        self.package_mocks()
        release = Path(self.env["NEMO_RELEASE_JSON"])
        release.write_text(release.read_text().replace("1.4.72-1-", "1.4.72-2-"))
        checksums = Path(self.env["CHECKSUMS"])
        checksums.write_text(checksums.read_text().replace("1.4.72-1-", "1.4.72-2-"))
        result = self.nemo_update(INSTALLED_VERSION="1.4.72-1", PACKAGE_TARGET="1.4.72-2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / "pacman.log").exists())
        self.assertEqual((self.home / "package-version").read_text().strip(), "1.4.72-2")

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

    def test_legacy_optional_group_is_empty_without_authentication_or_downloads(self):
        report = self.home / "optional.json"
        result = subprocess.run(
            ["bash", str(ROOT / "src/shared/bin/smplos-update-apps"),
             "--group", "optional", "--report", str(report)],
            env=self.env, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No OS-managed optional native apps", result.stdout)
        self.assertEqual(json.loads(report.read_text())["components"], {})
        self.assertFalse(self.requests.exists())
        self.assertNotIn("FORBIDDEN", result.stdout + result.stderr)

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
REPORT_FILE="$HOME/apps.json"; REPORT_WORK="$HOME/results"
mkdir -p "$REPORT_WORK"
installed_component_version() { :; }; record_app_result() { :; }; log() { :; }
n_updated=0
warn() { echo "$*" >&2; }; ok() { :; }
update_smpl_apps() { echo native-start; false; echo must-not-reach; }
update_st_smpl() { echo terminal; }
update_nemo_smpl() { echo nemo; }
update_micro_smpl() { echo editor; }
update_control_surface() { echo mouse-keypad; }
update_grafium() { echo forbidden-grafium; return 99; }
rebuild-app-cache() { echo cache; }
"""
        result = self.shell(script + main)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("must-not-reach", result.stdout)
        for name in ("terminal", "nemo", "editor", "cache"):
            self.assertIn(name, result.stdout)
        self.assertNotIn("forbidden-grafium", result.stdout)
        self.assertIn("incomplete", result.stderr)

    def test_native_results_persist_each_target_and_failure_instead_of_trusting_old_markers(self):
        path = ROOT / "src/shared/bin/smplos-update-apps"
        main = path.read_text().split("# ── Main", 1)[1].split("\n", 1)[1]
        script = function(path, "record_app_result") + """
STATE_DIR="$HOME/state"; SMPLOS_PATH="$HOME/data"; CHECK_ONLY=0; QUIET=1; SMPLOS_APP_BINS=()
REPORT_FILE="$HOME/apps.json"; REPORT_WORK="$HOME/results"; n_updated=0
mkdir -p "$REPORT_WORK"
installed_component_version() { echo v1.0; }
warn() { echo "$*" >&2; }; log() { :; }
release_target() { echo '{"tag_name":"v2.0"}' > "$SMPLOS_APP_RESULT_FILE"; }
update_smpl_apps() { release_target; echo attempted-new-suite; false; echo must-not-reach; }
update_st_smpl() { release_target; n_updated=1; }
update_nemo_smpl() { release_target; }
update_micro_smpl() { release_target; }
update_control_surface() { release_target; }
update_grafium() { echo forbidden-grafium; return 99; }
rebuild-app-cache() { echo refreshed; }
""" + main
        result = self.shell(script)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("must-not-reach", result.stdout)
        report = json.loads((self.home / "apps.json").read_text())
        self.assertEqual(set(report["components"]),
                         {"smpl-apps", "st-smpl", "nemo-smpl", "micro-smpl", "control-surface"})
        self.assertNotIn("forbidden-grafium", result.stdout)
        self.assertEqual(report["components"]["smpl-apps"],
                         {"before": "v1.0", "after": "v1.0", "target": "v2.0", "status": "failed"})
        # Same-version repairs must be reported as updated, not already current.
        self.assertEqual(report["components"]["st-smpl"]["status"], "updated")
        self.assertEqual(report["components"]["micro-smpl"]["status"], "current")
        self.assertIn("refreshed", result.stdout)

    def test_native_package_holds_skip_release_install_without_pinning_standalone_apps(self):
        path = ROOT / "src/shared/bin/smplos-update-apps"
        main = path.read_text().split("# ── Main", 1)[1].split("\n", 1)[1]
        script = function(path, "record_app_result") + """
STATE_DIR="$HOME/state"; SMPLOS_PATH="$HOME/data"; CHECK_ONLY=0; QUIET=1; SMPLOS_APP_BINS=()
REPORT_FILE="$HOME/apps.json"; REPORT_WORK="$HOME/results"; n_updated=0
export SMPLOS_UPDATE_PIN_IGNORE="nemo-smpl,control-surface,smpl-apps"
mkdir -p "$REPORT_WORK"
installed_component_version() { echo 1.0-1; }
warn() { echo "$*" >&2; }; log() { :; }
release_target() { echo '{"tag_name":"v2.0"}' > "$SMPLOS_APP_RESULT_FILE"; }
update_smpl_apps() { release_target; echo standalone-delivered; }
update_st_smpl() { release_target; }
update_micro_smpl() { release_target; }
update_nemo_smpl() { echo forbidden-held-package; return 99; }
update_control_surface() { echo forbidden-held-package; return 99; }
rebuild-app-cache() { :; }
""" + main
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("forbidden-held-package", result.stdout)
        self.assertIn("standalone-delivered", result.stdout)
        components = json.loads((self.home / "apps.json").read_text())["components"]
        for component in ("nemo-smpl", "control-surface"):
            self.assertEqual(components[component]["status"], "pinned")
            self.assertIsNone(components[component]["target"])

    def test_native_groups_do_not_run_unrelated_components_or_overwrite_their_reports(self):
        path = ROOT / "src/shared/bin/smplos-update-apps"
        self.assertNotIn("grafium", path.read_text().lower())
        personal = {
            ".local/bin/grafium": b"#!/bin/sh\nexec custom-notes-build\n",
            ".local/share/applications/Grafium.desktop": b"Exec=custom-notes-build\n",
            ".config/smplos/pinned-apps.txt": b'"custom-notes-build"\n',
            ".config/grafium/preferences.json": b'{"keep":"personal"}\n',
            ".local/state/smplos/app-versions/grafium": b"old-os-marker\n",
            "notes/graph.json": b'{"notes":"irreplaceable"}\n',
        }
        for relative, data in personal.items():
            target = self.home / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        main = path.read_text().split("# ── Main", 1)[1].split("\n", 1)[1]
        script = function(path, "record_app_result") + """
STATE_DIR="$HOME/state"; SMPLOS_PATH="$HOME/data"; CHECK_ONLY=0; QUIET=1; SMPLOS_APP_BINS=()
REPORT_FILE="$HOME/$GROUP.json"; REPORT_WORK="$HOME/results-$GROUP"; n_updated=0
mkdir -p "$REPORT_WORK"
installed_component_version() { echo v1.0; }
warn() { echo "$*" >&2; }; log() { :; }
release_target() { echo '{"tag_name":"v1.0"}' > "$SMPLOS_APP_RESULT_FILE"; }
update_smpl_apps() { release_target; }
update_st_smpl() { release_target; }
update_nemo_smpl() { release_target; }
update_micro_smpl() { release_target; }
update_control_surface() { release_target; }
update_grafium() { echo forbidden-grafium; return 99; }
rebuild-app-cache() { :; }
"""
        for group in ("all", "core"):
            with self.subTest(group=group):
                result = self.shell(script + main, GROUP=group)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("forbidden-grafium", result.stdout)
                self.assertEqual(set(json.loads((self.home / f"{group}.json").read_text())["components"]),
                                 {"smpl-apps", "st-smpl", "nemo-smpl", "micro-smpl", "control-surface"})
        original = (self.home / "core.json").read_bytes()
        optional = self.shell(script + main, GROUP="optional")
        self.assertEqual(optional.returncode, 0, optional.stderr)
        self.assertEqual((self.home / "core.json").read_bytes(), original)
        results = json.loads((self.home / "optional.json").read_text())["components"]
        self.assertEqual(results, {})
        for relative, data in personal.items():
            self.assertEqual((self.home / relative).read_bytes(), data, relative)

    def test_full_wrapper_records_deployment_and_native_failures(self):
        source = (ROOT / "src/shared/bin/smplos-update").read_text()
        apps_phase = source.split('# ── Step 4:', 1)[1].split('update_stage desktop', 1)[0].split("\n", 1)[1]
        os_phase = source.split('update_stage desktop', 1)[1].split('update_stage core-verification', 1)[0]
        result = self.shell("""
UPDATE_MODE=full; NETWORK_OK=1; UPDATE_FAILED=0; SYSTEM_UPGRADED=1
LOG_FILE="$HOME/update.log"
load_critical_packages() { :; }
update_stage() { :; }
check_update_power() { :; }
critical_bundle_prompt_and_apply() { :; }
smplos-os-update() { echo refreshed > "$HOME/script-version"; return 1; }
smplos-update-apps() { return 1; }
""" + apps_phase + os_phase + '\n[[ "$UPDATE_FAILED" -eq 0 ]]\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn("smplos-os-update failed", result.stdout)
        self.assertIn("smplos-update-apps failed", result.stdout)
        self.assertIn('set -o pipefail', source)
        self.assertIn('[[ "$UPDATE_FAILED" -eq 0 ]]\n} 2>&1 | tee', source)

    def test_resumed_theme_only_update_reapplies_and_invalid_resume_flags_fail(self):
        source = (ROOT / "src/shared/bin/smplos-os-update").read_text()
        finalization = source.split("    # A failed finalization must retry", 1)[1]
        finalization = finalization.split("\n", 1)[1].split('    [[ $migrations_failed -eq 0 ]]', 1)[0]
        for self_updated, themes_changed in ((1, 0), (0, 1), (0, 0)):
            result = self.shell(f"""
had_updates=0; SELF_UPDATED={self_updated}; THEMES_CHANGED={themes_changed}
HYPR_CONFIGS_CHANGED=0; APPS_CHANGED=0
header() {{ :; }}; post_deploy() {{ echo reapplied; }}
""" + finalization)
            self.assertEqual(result.stdout, "reapplied\n", result.stderr)
        result = self.shell("migrations_failed=0\nheader() { :; }; post_deploy() { return 1; }\n" +
                            finalization + '\n[[ $migrations_failed -eq 0 ]]')
        self.assertNotEqual(result.returncode, 0)
        validation = source.split('case "$SELF_UPDATED:', 1)[1].split("esac", 1)[0]
        validation = 'case "$SELF_UPDATED:' + validation + "esac"
        result = self.shell('SELF_UPDATED=1; SMPLOS_OS_HAD_UPDATES=not-a-boolean\n' + validation)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid updater resume flags", result.stderr)


if __name__ == "__main__":
    unittest.main()
