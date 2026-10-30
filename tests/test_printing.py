"""Printing protocol and delivery tests; all mutations use isolated fakes."""

import argparse
from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "src/shared/bin/smplos-printing"
MODULE = ROOT / "src/shared/lib/smplos-printing.py"
MIGRATION = ROOT / "migrations/20261030-120000-printing-platform.sh"
spec = importlib.util.spec_from_file_location("printing", MODULE)
printing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(printing)


def job(state=3, owner="demo", queue="Office"):
    return {
        "job-uuid": "urn:uuid:11111111-2222-3333-4444-555555555555",
        "job-printer-uri": f"ipp://localhost/printers/{queue}",
        "job-name": "Example document", "job-originating-user-name": owner,
        "job-state": state, "job-state-reasons": ["none"],
        "time-at-creation": 1800000000, "time-at-completed": 0,
    }


class Connection:
    def __init__(self):
        self.jobs = {42: job()}
        self.active = self.jobs
        self.history = {}
        self.calls = []
        self.queries = []

    def getPrinters(self):
        return {"Office": {}, "OfficeAlias": {}, "Temporary": {}}

    def getClasses(self):
        return {"Team": ["Office"]}

    def getDefault(self):
        return "Office"

    def getPrinterAttributes(self, **kwargs):
        self.queries.append(kwargs)
        name = printing.queue_id(kwargs["uri"])
        return {
            "printer-info": "Friendly name", "printer-state": 3,
            "printer-is-accepting-jobs": True, "printer-is-temporary": name == "Temporary",
            "printer-state-reasons": ["none"],
            "printer-state-message": "Connecting ipp://private:password@device/print",
            "device-uri": "ipp://private:password@device/print",
        }

    def getJobs(self, **kwargs):
        self.queries.append(kwargs)
        result = self.active if kwargs["which_jobs"] == "not-completed" else self.history
        if "first_job_id" in kwargs:
            result = {key: value for key, value in result.items() if key >= kwargs["first_job_id"]}
            result = dict(list(result.items())[:kwargs["limit"]])
        if kwargs["my_jobs"]:
            result = {key: value for key, value in result.items()
                      if value.get("job-originating-user-name") == "demo"}
        return result

    def getJobAttributes(self, ident, **kwargs):
        return copy.deepcopy(self.jobs[ident])

    def cancelJob(self, ident, **kwargs):
        self.calls.append(("cancel", ident, kwargs))
        self.jobs[ident]["job-state"] = 7

    def setJobHoldUntil(self, ident, value):
        self.calls.append(("hold", ident, value))
        self.jobs[ident]["job-state"] = 4 if value == "indefinite" else 3


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.connection = Connection()

    def args(self, action="cancel", **kwargs):
        row = printing.job_record(42, self.connection.jobs[42], "demo")
        return argparse.Namespace(
            id=kwargs.get("id", 42), printer=kwargs.get("printer", "Office"),
            identity=kwargs.get("identity", row["identity"]),
            action=action, confirm=kwargs.get("confirm", True),
        )

    def rejects(self, code, args):
        with self.assertRaises(printing.PrintingError) as error:
            printing.act(self.connection, "demo", args)
        self.assertEqual(error.exception.code, code)
        self.assertEqual(self.connection.calls, [])

    def test_status_preserves_aliases_classes_temporary_and_orphan_jobs(self):
        self.connection.active[43] = job(queue="Removed")
        self.connection.history[20] = job(state=9)
        result = printing.status(self.connection, "demo", [])
        self.assertTrue(result["ok"])
        self.assertEqual(result["protocol_version"], 1)
        self.assertEqual([p["id"] for p in result["printers"]], ["Office", "OfficeAlias", "Team", "Temporary"])
        self.assertEqual([p["id"] for p in result["printers"] if p["is_default"]], ["Office"])
        self.assertTrue(result["printers"][-1]["is_temporary"])
        self.assertEqual([j["id"] for j in result["jobs"]], [43, 42, 20])
        self.assertEqual(result["jobs"][0]["printer_id"], "Removed")
        self.assertEqual(result["jobs"][-1]["state"], "completed")
        self.assertTrue(result["active_complete"])
        self.assertTrue(result["history_complete"])
        encoded = json.dumps(result)
        self.assertNotIn("password", encoded)
        self.assertNotIn("private:", encoded)
        self.assertNotIn("device-uri", encoded)
        self.assertIn("cups_scope", encoded)
        self.assertEqual(self.connection.calls, [])

    def test_caps_history_limit_and_incomplete_flags_are_honest(self):
        self.connection.active = {i: job() for i in range(1, 502)}
        self.connection.history = {i: job(state=9) for i in range(1000, 1101)}
        result = printing.status(self.connection, "demo", [])
        self.assertFalse(result["active_complete"])
        self.assertFalse(result["history_complete"])
        self.assertEqual(result["history_limit"], 100)
        self.assertEqual(len(result["jobs"]), 600)
        queries = [q for q in self.connection.queries if "which_jobs" in q]
        self.assertEqual([q["limit"] for q in queries], [501, 501, 101, 101])
        self.assertEqual([q["my_jobs"] for q in queries], [False, True, False, True])

    def test_printer_limit(self):
        self.connection.getPrinters = lambda: {str(i): {} for i in range(80)}
        result = printing.status(self.connection, "demo", [])
        self.assertEqual(len(result["printers"]), 64)
        self.assertIn("printers_truncated", [w["code"] for w in result["warnings"]])

    def test_empty_success_is_distinct_from_cups_failure(self):
        self.connection.getPrinters = lambda: {}
        self.connection.getClasses = lambda: {}
        self.connection.active = {}
        self.connection.history = {}
        result = printing.status(self.connection, "demo", [])
        self.assertTrue(result["ok"])
        self.assertEqual(result["printers"], [])
        self.assertEqual(result["jobs"], [])
        self.assertTrue(result["active_complete"])

    def test_connectivity_reason_is_actionable_without_claiming_vpn_is_cause(self):
        read = self.connection.getPrinterAttributes

        def disconnected(**kwargs):
            return {**read(**kwargs), "printer-state-reasons": ["connecting-to-device"]}

        self.connection.getPrinterAttributes = disconnected
        result = printing.status(self.connection, "demo", [])
        messages = [w["message"] for w in result["warnings"] if w["code"] == "printer_connectivity"]
        self.assertTrue(messages)
        self.assertIn("If this persists", messages[0])
        self.assertIn("Do not resend", messages[0])

    def test_single_cancel_does_not_purge_and_repeat_is_rejected(self):
        args = self.args()
        result = printing.act(self.connection, "demo", args)
        self.assertEqual(result, {"protocol_version": 1, "ok": True, "id": 42, "action": "cancel"})
        self.assertEqual(self.connection.calls, [("cancel", 42, {"purge_job": False})])
        with self.assertRaises(printing.PrintingError):
            printing.act(self.connection, "demo", args)
        self.assertEqual(len(self.connection.calls), 1)

    def test_hold_release_only_changes_one_job(self):
        printing.act(self.connection, "demo", self.args("hold"))
        printing.act(self.connection, "demo", self.args("release"))
        self.assertEqual(self.connection.calls, [("hold", 42, "indefinite"), ("hold", 42, "no-hold")])

    def test_confirmation_is_required(self):
        self.rejects("confirmation_required", self.args(confirm=False))

    def test_foreign_owner_is_denied_even_when_identity_is_known(self):
        self.connection.jobs[42]["job-originating-user-name"] = "someone-else"
        self.rejects("permission_denied", self.args())

    def test_queue_mismatch_is_denied(self):
        self.rejects("stale_job", self.args(printer="OfficeAlias"))

    def test_reused_id_and_missing_uuid_are_denied(self):
        args = self.args()
        self.connection.jobs[42]["job-uuid"] = "urn:uuid:new"
        self.rejects("stale_job", args)
        del self.connection.jobs[42]["job-uuid"]
        row = printing.job_record(42, self.connection.jobs[42], "demo")
        self.assertFalse(row["can_cancel"])
        self.assertEqual(row["identity"], "")
        self.rejects("stale_job", self.args())

    def test_state_changes_are_checked_before_mutation(self):
        self.rejects("state_changed", self.args("release"))
        self.connection.jobs[42]["job-state"] = 5
        self.rejects("state_changed", self.args("hold"))

    def test_global_zero_negative_and_overflow_ids_are_denied(self):
        for value in (0, -1, 2147483648):
            self.rejects("invalid_request", self.args(id=value))

    def test_unknown_states_and_foreign_jobs_have_no_controls(self):
        for value in (0, 7, 8, 9):
            row = printing.job_record(42, job(state=value), "demo")
            self.assertFalse(any(row[key] for key in ("can_hold", "can_release", "can_cancel")))
        row = printing.job_record(42, job(owner="other"), "demo")
        self.assertFalse(row["own"])
        self.assertFalse(row["can_cancel"])

    def test_unicode_names_encoded_queue_and_redaction(self):
        attrs = job(queue="Office%20one")
        attrs["job-name"] = "Document \u00e9\nnext"
        row = printing.job_record(42, attrs, "demo")
        self.assertEqual(row["printer_id"], "Office one")
        self.assertEqual(row["title"], "Document \u00e9next")
        self.assertEqual(row["printer_uri"], "ipp://localhost/printers/Office%20one")
        with self.assertRaises(printing.PrintingError):
            printing.job_record(42, {"job-printer-uri": "ipp://localhost/jobs/42"}, "demo")
        self.assertNotIn("secret", printing.text("ipp://user:secret@secret@host/path"))

    def test_privacy_redacted_job_remains_visible_without_controls(self):
        self.connection.active[99] = {"job-state": 5}
        result = printing.status(self.connection, "demo", [])
        row = result["jobs"][0]
        self.assertEqual(row["id"], 99)
        self.assertEqual(row["printer_id"], "")
        self.assertEqual(row["identity"], "")
        self.assertFalse(row["own"])
        self.assertFalse(row["can_cancel"])
        self.assertIn("job_details_unavailable", [w["code"] for w in result["warnings"]])

    def test_owned_query_recovers_private_details_only_for_same_uuid(self):
        redacted = job()
        del redacted["job-originating-user-name"]
        del redacted["job-name"]
        merged = printing.merge_private_details({42: redacted}, {42: job()}, "demo")
        self.assertEqual(merged[42]["job-name"], "Example document")
        self.assertEqual(merged[42]["job-originating-user-name"], "demo")
        replaced = job()
        replaced["job-uuid"] = "urn:uuid:replacement"
        merged = printing.merge_private_details({42: redacted}, {42: replaced}, "demo")
        self.assertNotIn("job-name", merged[42])

    def test_action_recovers_redacted_owner_and_checks_latest_state(self):
        real_read = self.connection.getJobAttributes

        def redacted(ident, **kwargs):
            result = real_read(ident, **kwargs)
            del result["job-originating-user-name"]
            return result

        self.connection.getJobAttributes = redacted
        printing.act(self.connection, "demo", self.args("hold"))
        self.assertEqual(self.connection.calls, [("hold", 42, "indefinite")])

    def test_stale_owned_snapshot_cannot_override_new_terminal_state(self):
        read = self.connection.getJobAttributes

        def completed(ident, **kwargs):
            result = read(ident, **kwargs)
            result["job-state"] = 9
            result.pop("job-originating-user-name")
            return result

        self.connection.getJobAttributes = completed
        self.rejects("state_changed", self.args("hold"))

    def test_mullvad_warning_accepts_real_cli_format_and_never_changes_policy(self):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "Local network sharing setting: block\n", "")

        with patch.object(printing.shutil, "which", return_value="/usr/bin/mullvad"), \
             patch.object(printing.subprocess, "run", side_effect=run):
            result = printing.system_warnings()
        self.assertIn("vpn_lan_blocked", [w["code"] for w in result])
        self.assertEqual(calls, [
            ["systemctl", "is-active", "--quiet", "avahi-daemon.service"],
            ["mullvad", "lan", "get"],
        ])

    def test_diagnostics_failures_are_explicit_warnings(self):
        with patch.object(printing.shutil, "which", return_value="/usr/bin/mullvad"), \
             patch.object(printing.subprocess, "run", side_effect=subprocess.TimeoutExpired("fake", 1)):
            result = printing.system_warnings()
        self.assertEqual([w["code"] for w in result], ["discovery_status_unknown", "vpn_status_unknown"])

    def test_invalid_cli_emits_json_nonzero(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = printing.main(["job", "cancel", "--id", "0"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], "invalid_request")

    def test_missing_pycups_is_explicit_not_an_empty_queue(self):
        output = io.StringIO()
        with patch.dict("sys.modules", {"cups": None}), redirect_stdout(output):
            code = printing.main(["status", "--json"])
        self.assertEqual(code, 1)
        result = json.loads(output.getvalue())
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "dependency_missing")

    def test_cups_errors_are_explicit_and_never_expose_raw_details(self):
        class IPPError(Exception):
            pass

        class HTTPError(Exception):
            pass

        fake = argparse.Namespace(IPPError=IPPError, HTTPError=HTTPError,
                                  setUser=lambda _: None, setPasswordCB=lambda _: None)
        for error, expected in [
            (IPPError(0x0403, "private credential"), "permission_denied"),
            (IPPError(0x0406, "private credential"), "not_found"),
            (IPPError(0x0500, "private credential"), "cups_error"),
            (RuntimeError("private credential"), "cups_unavailable"),
        ]:
            fake.Connection = lambda **kwargs: (_ for _ in ()).throw(error)
            output = io.StringIO()
            with patch.dict("sys.modules", {"cups": fake}), redirect_stdout(output):
                code = printing.main(["status", "--json"])
            self.assertEqual(code, 1)
            result = json.loads(output.getvalue())
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], expected)
            self.assertNotIn("private credential", output.getvalue())

    def test_unacknowledged_action_is_unknown_and_never_retried(self):
        class IPPError(Exception):
            pass

        class HTTPError(Exception):
            pass

        import pwd
        username = pwd.getpwuid(os.getuid()).pw_name
        self.connection.jobs[42]["job-originating-user-name"] = username
        owned = {42: copy.deepcopy(self.connection.jobs[42])}
        self.connection.getJobs = lambda **kwargs: owned
        calls = []

        def unacknowledged(*args, **kwargs):
            calls.append(args)
            raise HTTPError(500)

        self.connection.cancelJob = unacknowledged
        fake = argparse.Namespace(
            IPPError=IPPError, HTTPError=HTTPError,
            setUser=lambda _: None, setPasswordCB=lambda _: None,
            Connection=lambda **kwargs: self.connection,
        )
        identity = printing.job_record(42, owned[42], username)["identity"]
        output = io.StringIO()
        with patch.dict("sys.modules", {"cups": fake}), redirect_stdout(output):
            code = printing.main([
                "job", "cancel", "--id", "42", "--printer", "Office",
                "--identity", identity, "--confirm", "--json",
            ])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], "outcome_unknown")
        self.assertEqual(calls, [(42,)])

    def test_launcher_timeout_has_no_automatic_action_retry(self):
        spec = importlib.util.spec_from_loader(
            "printing_launcher", importlib.machinery.SourceFileLoader("printing_launcher", str(HELPER))
        )
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        for command, expected in (("job", "outcome_unknown"), ("status", "timeout")):
            output = io.StringIO()
            with patch.object(launcher.sys, "argv", [str(HELPER), command, "--json"]), \
                 patch.object(launcher.subprocess, "run", side_effect=subprocess.TimeoutExpired("cups", 15)) as run, \
                 redirect_stdout(output):
                self.assertEqual(launcher.main(), 1)
            run.assert_called_once()
            self.assertEqual(json.loads(output.getvalue())["error"]["code"], expected)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.installed = self.directory / "installed"
        self.installed.write_text("")
        self.calls = self.directory / "calls"
        self.env = {
            **os.environ, "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.directory), "XDG_STATE_HOME": str(self.directory / "state"),
            "SMPLOS_SYSTEM_UPGRADED": "1", "PACKAGES": str(self.installed),
            "CALLS": str(self.calls),
            "SMPLOS_UPDATE_PACMAN": str(self.bin / "pacman"),
        }
        self.tool("pkexec", 'printf "privileged %s\\n" "$*" >> "$CALLS"\nexec "$@"')
        self.tool("pacman", '''
if [[ "$1" == -Q ]]; then grep -qx "$2" "$PACKAGES"; exit; fi
printf "packages %s\\n" "$*" >> "$CALLS"
[[ "${FAIL_INSTALL:-0}" == 0 ]] || exit 1
for arg in "$@"; do [[ "$arg" == -* ]] || echo "$arg" >> "$PACKAGES"; done
''')
        self.tool("systemctl", '''
printf "service %s\\n" "$*" >> "$CALLS"
if [[ "$1" == is-enabled ]]; then echo "${UNIT_POLICY:-disabled}"; exit; fi
[[ "${FAIL_SERVICE:-0}" == 0 ]]
''')

    def tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + body + "\n")
        path.chmod(0o755)

    def migrate(self):
        return subprocess.run(
            ["bash", str(MIGRATION)], env=self.env, capture_output=True,
            text=True, timeout=5,
        )

    def call_text(self):
        return self.calls.read_text() if self.calls.exists() else ""

    def test_missing_packages_defer_without_a_complete_system_upgrade(self):
        self.env["SMPLOS_SYSTEM_UPGRADED"] = "0"
        result = self.migrate()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.call_text(), "")

    def test_new_install_enrolls_only_selected_services(self):
        result = self.migrate()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.call_text()
        self.assertIn("packages -S --needed --noconfirm cups cups-filters python-pycups avahi", calls)
        self.assertIn("service enable --now cups.socket", calls)
        self.assertIn("service enable --now avahi-daemon.service", calls)
        self.assertNotIn("cups-browsed", calls)
        self.assertNotIn("mullvad", calls)
        self.assertNotIn("lpadmin", calls)
        self.calls.unlink()
        self.assertEqual(self.migrate().returncode, 0)
        self.assertEqual(self.call_text(), "")

    def test_existing_disabled_services_are_preserved(self):
        self.installed.write_text("cups\ncups-filters\npython-pycups\navahi\n")
        self.assertEqual(self.migrate().returncode, 0)
        self.assertEqual(self.call_text(), "")

    def test_managed_update_uses_its_pin_guard_not_unguarded_pacman(self):
        guarded = self.bin / "guarded-pacman"
        self.tool("guarded-pacman", 'printf "guarded\\n" >> "$CALLS"\nexec pacman "$@"')
        self.env["SMPLOS_UPDATE_PACMAN"] = str(guarded)
        self.assertEqual(self.migrate().returncode, 0)
        self.assertIn("guarded\n", self.call_text())

    def test_only_new_cups_service_is_enrolled_when_avahi_existed(self):
        self.installed.write_text("avahi\n")
        self.assertEqual(self.migrate().returncode, 0)
        self.assertIn("service enable --now cups.socket", self.call_text())
        self.assertNotIn("avahi-daemon.service", self.call_text())

    def test_install_failure_is_not_success_and_retry_retains_enrollment(self):
        self.env["FAIL_INSTALL"] = "1"
        self.assertNotEqual(self.migrate().returncode, 0)
        self.assertNotIn("service enable", self.call_text())
        self.env["FAIL_INSTALL"] = "0"
        self.assertEqual(self.migrate().returncode, 0)
        self.assertIn("service enable --now cups.socket", self.call_text())

    def test_service_failure_remains_retryable_after_packages_install(self):
        self.env["FAIL_SERVICE"] = "1"
        self.assertNotEqual(self.migrate().returncode, 0)
        self.calls.unlink()
        self.env["FAIL_SERVICE"] = "0"
        self.assertEqual(self.migrate().returncode, 0)
        self.assertNotIn("packages -S", self.call_text())
        self.assertIn("service enable --now cups.socket", self.call_text())

    def test_mask_is_not_removed(self):
        self.env["UNIT_POLICY"] = "masked"
        result = self.migrate()
        self.assertEqual(result.returncode, 0)
        self.assertIn("preserving explicit policy", result.stdout)
        self.assertNotIn("service enable", self.call_text())
        self.assertNotIn("unmask", self.call_text())

    def test_iso_installer_and_update_ship_same_base_dependencies(self):
        package_lines = (ROOT / "src/shared/packages.txt").read_text().splitlines()
        for name in ("cups", "cups-filters", "python-pycups", "avahi"):
            self.assertIn(name, package_lines)
            self.assertIn(name, MIGRATION.read_text())
        builder = (ROOT / "src/builder/build.sh").read_text()
        installer = (ROOT / "src/shared/installer/install.sh").read_text()
        for unit in ("cups.socket", "avahi-daemon.service"):
            self.assertIn(unit, builder)
            self.assertIn(f"chrootable_systemctl_enable {unit}", installer)
        self.assertIn('shared/lib/"*.py', builder)
        self.assertIn("sync_libs", (ROOT / "src/shared/bin/smplos-os-update").read_text())

    def test_iso_printing_service_links_are_staged_under_the_profile_only(self):
        builder = (ROOT / "src/builder/build.sh").read_text()
        snippet = builder.split("setup_services() {", 1)[1].split("# Enable NetworkManager", 1)[0]
        profile = self.directory / "profile"
        script = 'log_info() { :; }\nsetup_services() {' + snippet + '\n}\nsetup_services "$1"'
        result = subprocess.run(
            ["bash", "-eu", "-c", script, "--", str(profile)],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for target, unit in (("sockets", "cups.socket"), ("multi-user", "avahi-daemon.service")):
            path = profile / f"etc/systemd/system/{target}.target.wants/{unit}"
            self.assertTrue(path.is_symlink())
            self.assertEqual(os.readlink(path), f"/usr/lib/systemd/system/{unit}")

    def test_installer_enables_without_starting_services_in_chroot(self):
        self.tool("sudo", 'exec "$@"')
        installer = (ROOT / "src/shared/installer/install.sh").read_text()
        snippet = installer.split("chrootable_systemctl_enable() {", 1)[1]
        snippet = snippet.split('echo "==> Configuring desktop environment..."', 1)[0]
        for chroot in ("1", ""):
            self.env["SMPLOS_CHROOT_INSTALL"] = chroot
            result = subprocess.run(
                ["bash", "-eu", "-c", "chrootable_systemctl_enable() {" + snippet],
                env=self.env, capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            option = "" if chroot else "--now "
            self.assertEqual(
                self.call_text(),
                f"service enable {option}cups.socket\nservice enable {option}avahi-daemon.service\n",
            )
            self.calls.unlink()

    def test_settings_shortcuts_use_native_tab(self):
        self.tool("settings", 'printf "%s\\n" "$*"')
        for alias in ("printing", "printers"):
            result = subprocess.run(
                ["bash", str(ROOT / "src/shared/bin/smplos-settings"), alias],
                env=self.env, text=True, capture_output=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "--tab printing")


if __name__ == "__main__":
    unittest.main()
