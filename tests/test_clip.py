"""Shell-independent clip argument handling and FFmpeg status propagation."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIP = ROOT / "src/shared/bin/clip"


class ClipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="smplos-clip-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.capture = self.home / "args.json"
        mock = self.home / "ffmpeg"
        mock.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['CAPTURE']).write_text(json.dumps(sys.argv[1:]))\n"
            "sys.exit(int(os.environ.get('FFMPEG_STATUS', '0')))\n"
        )
        mock.chmod(0o755)
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "PATH": f"{self.home}:{CLIP.parent}:{os.environ['PATH']}",
            "CAPTURE": str(self.capture),
        }

    def clip(self, *args):
        return subprocess.run(
            [str(CLIP), *args],
            env=self.env, capture_output=True, text=True, timeout=10,
        )

    def test_quoted_paths_preserve_exact_ffmpeg_arguments(self):
        result = self.clip("274.09", "276.33", "input video.mp4", "output video.mp4")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.capture.read_text()), [
            "-ss", "274.09", "-to", "276.33", "-i", "input video.mp4",
            "-c", "copy", "output video.mp4",
        ])

    def test_wrong_argument_counts_print_usage_without_running_ffmpeg(self):
        for args in ((), ("1",), ("1", "2", "in.mp4"),
                     ("1", "2", "in.mp4", "out.mp4", "extra")):
            with self.subTest(args=args):
                result = self.clip(*args)
                self.assertEqual(result.returncode, 1)
                self.assertIn("Usage: clip", result.stderr)
                self.assertFalse(self.capture.exists())

    def test_ffmpeg_failure_is_returned(self):
        self.env["FFMPEG_STATUS"] = "23"
        result = self.clip("1", "2", "in.mp4", "out.mp4")
        self.assertEqual(result.returncode, 23)

    def test_times_and_paths_are_not_hardcoded(self):
        result = self.clip("00:01:02.5", "00:01:05", "other.mov", "cut.mov")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.capture.read_text()), [
            "-ss", "00:01:02.5", "-to", "00:01:05", "-i", "other.mov",
            "-c", "copy", "cut.mov",
        ])

    def test_command_is_available_from_bash_and_fish(self):
        for shell, options in (("bash", ["--noprofile", "--norc"]),
                               ("fish", ["--no-config"])):
            if not shutil.which(shell):
                continue
            with self.subTest(shell=shell):
                result = subprocess.run(
                    [shell, *options, "-c", 'clip 1 2 "input video.mp4" "output video.mp4"'],
                    env=self.env, capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(self.capture.read_text()), [
                    "-ss", "1", "-to", "2", "-i", "input video.mp4",
                    "-c", "copy", "output video.mp4",
                ])


if __name__ == "__main__":
    unittest.main()
