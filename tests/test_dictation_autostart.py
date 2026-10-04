"""Dictation only starts at login once voxtype has a model to load."""

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations/20261004-120000-disable-dictation-without-model.sh"
PRIME = ROOT / "src/shared/bin/dictation-prime"


class DictationAutostartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.home.mkdir()
        bin_dir = Path(self.temp.name) / "bin"
        bin_dir.mkdir()
        self.calls = Path(self.temp.name) / "calls"
        (bin_dir / "systemctl").write_text(f'#!/bin/sh\necho "$*" >> {self.calls}\n')
        (bin_dir / "voxtype").write_text("#!/bin/sh\nexit 1\n")
        for tool in ("systemctl", "voxtype"):
            (bin_dir / tool).chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{bin_dir}:{os.environ['PATH']}")
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            self.env.pop(key, None)
        self.units = self.home / ".config/systemd/user"
        self.models = self.home / ".local/share/voxtype/models"
        self.models.mkdir(parents=True)
        (self.models / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55\n")

    def enable(self):
        self.units.mkdir(parents=True, exist_ok=True)
        (self.units / "voxtype.service").write_text("[Service]\nExecStart=/usr/bin/voxtype daemon\n")
        for wants in ("graphical-session.target.wants", "default.target.wants"):
            (self.units / wants).mkdir(exist_ok=True)
            (self.units / wants / "voxtype.service").symlink_to(self.units / "voxtype.service")

    def calls_made(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_migration_disables_login_start_without_a_model(self):
        self.enable()
        subprocess.run(["bash", str(MIGRATION)], env=self.env, check=True, timeout=10)
        for wants in ("graphical-session.target.wants", "default.target.wants"):
            self.assertFalse((self.units / wants / "voxtype.service").is_symlink())
        self.assertTrue((self.units / "voxtype.service").exists(), "the unit stays for on-demand use")
        self.assertIn("--user stop voxtype.service", self.calls_made())

    def test_migration_keeps_a_working_setup(self):
        self.enable()
        (self.models / "ggml-base.bin").write_bytes(b"model")
        subprocess.run(["bash", str(MIGRATION)], env=self.env, check=True, timeout=10)
        self.assertTrue((self.units / "graphical-session.target.wants/voxtype.service").is_symlink())
        self.assertEqual(self.calls_made(), [])

    def prime(self):
        (self.units).mkdir(parents=True, exist_ok=True)
        (self.units / "voxtype.service").write_text("[Service]\n")
        subprocess.run(["bash", str(PRIME)], env=self.env, check=True, timeout=10, capture_output=True)

    def test_prime_enables_the_service_only_with_a_model(self):
        self.prime()
        self.assertNotIn("--user enable voxtype.service", self.calls_made())
        (self.home / ".config/smplos/.dictation-primed").unlink()
        (self.models / "ggml-base.bin").write_bytes(b"model")
        self.prime()
        self.assertIn("--user enable voxtype.service", self.calls_made())


if __name__ == "__main__":
    unittest.main()
