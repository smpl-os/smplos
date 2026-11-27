from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
KB_SYNC = ROOT / "src/shared/bin/kb-sync"


class KeyboardLayoutSyncTests(unittest.TestCase):
    def test_preserves_configured_options_when_adding_layout_switching(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            config = root / "home/.config/hypr/input.conf"
            config.parent.mkdir(parents=True)
            config.write_text(
                "input {\n"
                "    kb_layout = us,ru\n"
                "    kb_variant = ,phonetic\n"
                "    kb_options = ctrl:nocaps,altwin:menu_win\n"
                "}\n"
            )
            calls = root / "calls"
            hyprctl = bin_dir / "hyprctl"
            hyprctl.write_text(
                "#!/bin/bash\n"
                "if [[ $1 == -j && $2 == devices ]]; then\n"
                "  echo '{\"keyboards\":[{\"name\":\"usb-keyboard\",\"main\":true,\"active_layout_index\":0}]}'\n"
                "elif [[ $1 == dispatch ]]; then\n"
                "  printf '%s\\n' \"$2\" > \"$CALLS\"\n"
                "elif [[ $1 == switchxkblayout ]]; then\n"
                "  exit 0\n"
                "fi\n"
            )
            hyprctl.chmod(0o755)
            jq = bin_dir / "jq"
            jq.write_text("#!/bin/sh\nif [ \"$1\" = -r ]; then echo usb-keyboard; else cat; fi\n")
            jq.chmod(0o755)
            result = subprocess.run(
                ["timeout", "3s", "bash", str(KB_SYNC)],
                env={
                    "HOME": str(root / "home"),
                    "WAYLAND_DISPLAY": "wayland-1",
                    "HYPRLAND_INSTANCE_SIGNATURE": "fixture",
                    "PATH": f"{bin_dir}:/usr/bin:/bin",
                    "CALLS": str(calls),
                    "XDG_RUNTIME_DIR": str(root / "runtime"),
                },
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 124)
            expression = calls.read_text()
            self.assertIn(
                "kb_options='ctrl:nocaps,altwin:menu_win,grp:alt_shift_toggle'",
                expression,
            )


if __name__ == "__main__":
    unittest.main()
