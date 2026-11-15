"""Web-app DNS visibility without changing VPNs or real browser profiles."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "src/shared/bin/launch-webapp"


class WebappDnsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="webapp-dns-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.mocks = self.home / "bin"
        self.mocks.mkdir()
        self.browser = self.tool("browser-probe", "exit 0\n")
        self.tool("xdg-settings", "printf '%s\\n' brave-browser.desktop\n")
        for name in ("notify-send", "zenity"):
            self.tool(name, "exit 0\n")
        applications = self.home / ".local/share/applications"
        applications.mkdir(parents=True)
        (applications / "brave-browser.desktop").write_text(
            f"[Desktop Entry]\nType=Application\nName=DNS probe\nExec={self.browser}\n"
        )
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "XDG_CACHE_HOME": str(self.home / "cache"),
            "XDG_RUNTIME_DIR": "",
            "HYPRLAND_INSTANCE_SIGNATURE": "",
            "WAYLAND_DISPLAY": "",
            "DISPLAY": "",
            "WEBAPP_FLOAT": "0",
            "WEBAPP_SECURE": "0",
            "PATH": f"{self.mocks}:{os.environ['PATH']}",
        }

    def tool(self, name, body):
        path = self.mocks / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        return path

    def launch(self, path=LAUNCHER):
        result = subprocess.run(
            ["bash", str(path), "--name", self.home.name, "https://example.invalid"],
            env=self.env, capture_output=True, text=True, timeout=15,
        )
        log = self.home / "cache/smplos/launch-webapp.log"
        details = log.read_text() if log.exists() else "(no launcher log)"
        self.assertEqual(result.returncode, 0, result.stderr + details)
        return details

    def test_resolver_bind_and_host_network_preserve_the_existing_profile(self):
        for resolved in (True, False):
            with self.subTest(resolved=resolved):
                resolver = self.home / f"resolver-{resolved}"
                if resolved:
                    resolver.mkdir()
                    (resolver / "stub-resolv.conf").write_text("nameserver 127.0.0.53\n")
                launcher = self.home / "launch-webapp"
                launcher.write_text(LAUNCHER.read_text().replace("/run/systemd/resolve", str(resolver)))
                capture = self.home / "bwrap.json"
                mock = self.mocks / "bwrap"
                mock.write_text(
                    "#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n"
                    f"Path({str(capture)!r}).write_text(json.dumps(sys.argv[1:]))\n"
                )
                mock.chmod(0o755)
                profile = self.home / ".local/share/webapps" / self.home.name
                profile.mkdir(parents=True, exist_ok=True)
                cookies = profile / "Cookies"
                cookies.write_bytes(b"keep existing login data exactly")
                self.launch(launcher)
                args = json.loads(capture.read_text())
                mounts = [args[i:i+3] for i, value in enumerate(args) if value == "--ro-bind"]
                expected = ["--ro-bind", str(resolver), str(resolver)]
                self.assertEqual(expected in mounts, resolved)
                self.assertIn(["--ro-bind", "/etc", "/etc"], mounts)
                self.assertIn("--share-net", args)
                self.assertNotIn("--unshare-net", args)
                self.assertEqual(cookies.read_bytes(), b"keep existing login data exactly")

    @unittest.skipUnless(
        shutil.which("bwrap")
        and Path("/etc/resolv.conf").resolve().parent == Path("/run/systemd/resolve"),
        "requires Bubblewrap and a systemd-resolved resolver link",
    )
    def test_resolver_link_is_readable_through_a_real_read_only_mount(self):
        probe = subprocess.run(
            ["bwrap", "--ro-bind", "/", "/", "--unshare-all", "--share-net", "/usr/bin/true"],
            capture_output=True, text=True, timeout=10,
        )
        if probe.returncode:
            self.skipTest(f"Bubblewrap namespaces unavailable: {probe.stderr.strip()}")
        self.tool(
            "browser-probe",
            "set -eu\n"
            "test -r /etc/resolv.conf\n"
            "awk '$5 == \"/run/systemd/resolve\" && "
            "$6 ~ /(^|,)ro(,|$)/ { found=1 } "
            "END { exit !found }' /proc/self/mountinfo\n"
            "printf 'Resolver available through a read-only mount\\n'\n",
        )
        self.assertIn("Resolver available through a read-only mount", self.launch())


if __name__ == "__main__":
    unittest.main()
