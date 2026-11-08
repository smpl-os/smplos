"""Exercise the real Unix-socket protocol without host administrator privileges."""

import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock


HELPER = Path(__file__).resolve().parents[1] / "src/shared/bin/smplos-update-privileged"
LOADER = importlib.machinery.SourceFileLoader("update_privileged", str(HELPER))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
AUTH = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(AUTH)


class PrivilegedChannelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.channel = self.directory / "broker/socket"
        self.errors = []
        uid, _, start = AUTH.identity(os.getpid())

        def serve():
            try:
                AUTH.serve(self.directory, os.getpid(), uid, start)
            except Exception as error:
                self.errors.append(error)

        self.server = threading.Thread(target=serve)
        self.server.start()
        deadline = time.monotonic() + 3
        while not self.channel.is_socket() and not self.errors and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.errors, [])
        self.assertTrue(self.channel.is_socket())

    def tearDown(self):
        if self.channel.is_socket():
            AUTH.request(self.channel, server_uid=os.geteuid())
        self.server.join(timeout=3)
        self.assertFalse(self.server.is_alive())
        self.assertEqual(self.errors, [])
        self.temp.cleanup()

    def request(self, arguments, incoming=b""):
        stdin = io.TextIOWrapper(io.BytesIO(incoming))
        stdout = io.TextIOWrapper(io.BytesIO())
        stderr = io.TextIOWrapper(io.BytesIO())
        with mock.patch.object(sys, "stdin", stdin), \
                mock.patch.object(sys, "stdout", stdout), \
                mock.patch.object(sys, "stderr", stderr):
            result = AUTH.request(self.channel, arguments, server_uid=os.geteuid())
        return result, stdout.buffer.getvalue(), stderr.buffer.getvalue()

    def test_repeated_commands_stream_binary_output_stdin_and_real_exit_codes(self):
        for _ in range(3):
            result, output, error = self.request(
                [sys.executable, "-c", "import sys; "
                 "sys.stdout.buffer.write(sys.stdin.buffer.read() + b'\\xff' * 100000); "
                 "sys.stderr.write('diagnostic'); sys.exit(7)"],
                incoming=b"configuration",
            )
            self.assertEqual(result, 7)
            self.assertEqual(output, b"configuration" + b"\xff" * 100000)
            self.assertEqual(error, b"diagnostic")
        self.assertTrue(self.server.is_alive())

    def test_missing_command_is_explicit_and_channel_remains_available(self):
        result, _, error = self.request(["/nonexistent/smplos-update-command"])
        self.assertEqual(result, 1)
        self.assertIn(b"No such file", error)
        result, output, _ = self.request([sys.executable, "-c", "print('ready')"])
        self.assertEqual((result, output), (0, b"ready\n"))

    def test_stale_owner_and_unrelated_processes_are_rejected(self):
        uid, _, start = AUTH.identity(os.getpid())
        self.assertTrue(AUTH.authorized(os.getpid(), uid, os.getpid(), start))
        self.assertFalse(AUTH.authorized(os.getpid(), uid, os.getpid(), "stale"))
        self.assertFalse(AUTH.authorized(os.getppid(), uid, os.getpid(), start))
        self.assertFalse(AUTH.authorized(os.getpid(), uid + 1, os.getpid(), start))

    def test_client_refuses_an_unauthenticated_server(self):
        with self.assertRaises(PermissionError):
            AUTH.request(self.channel, server_uid=os.geteuid() + 1)

    def test_relative_executable_is_rejected_without_execution(self):
        result, _, error = self.request(["python3", "-c", "print('must not execute')"])
        self.assertEqual(result, 1)
        self.assertIn(b"absolute executable", error)

    def test_stop_removes_the_socket_and_root_helper_directory(self):
        self.assertEqual(AUTH.request(self.channel, server_uid=os.geteuid()), 0)
        self.server.join(timeout=3)
        self.assertFalse((self.directory / "broker").exists())
        self.assertFalse(self.directory.exists())

    def test_coordinator_exit_closes_an_idle_channel(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            directory.mkdir(mode=0o700)
            with subprocess.Popen([sys.executable, "-c", "import time; time.sleep(15)"]) as owner:
                uid, _, start = AUTH.identity(owner.pid)
                errors = []
                def serve():
                    try:
                        AUTH.serve(directory, owner.pid, uid, start)
                    except Exception as error:
                        errors.append(error)
                server = threading.Thread(target=serve, daemon=True)
                server.start()
                deadline = time.monotonic() + 3
                while not (directory / "broker/socket").is_socket() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue((directory / "broker/socket").is_socket())
                owner.terminate()
                owner.wait(timeout=3)
                server.join(timeout=3)
                self.assertFalse(server.is_alive())
                self.assertEqual(errors, [])
                self.assertFalse(directory.exists())

    def test_server_cli_requires_polkit_authorization(self):
        with mock.patch.object(sys, "argv", [
                str(HELPER), "--serve", str(self.directory), str(os.getpid()),
                str(os.getuid()), AUTH.identity(os.getpid())[2]]), \
                mock.patch.object(AUTH.os, "geteuid", return_value=1000), \
                mock.patch.object(AUTH, "serve") as serve, \
                mock.patch.object(sys, "stderr", io.StringIO()):
            self.assertEqual(AUTH.main(), 1)
        serve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
