"""Local CUPS protocol v1. No discovery writes, privilege escalation or retries."""

import argparse
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
from urllib.parse import quote, unquote, urlsplit


HISTORY_LIMIT = 100
ACTIVE_LIMIT = 500
PRINTER_LIMIT = 64
JOB_ATTRIBUTES = [
    "job-id", "job-uuid", "job-uri", "job-printer-uri", "job-name",
    "job-originating-user-name", "job-state", "job-state-reasons",
    "time-at-creation", "time-at-completed",
]
PRINTER_ATTRIBUTES = [
    "printer-name", "printer-info", "printer-uri-supported", "printer-state",
    "printer-is-accepting-jobs", "printer-is-temporary", "printer-state-reasons",
    "printer-state-message",
]
JOB_STATES = {
    3: "pending", 4: "held", 5: "processing", 6: "stopped",
    7: "canceled", 8: "aborted", 9: "completed",
}


class PrintingError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def failure(code, message):
    return {
        "protocol_version": 1, "ok": False, "printers": [], "jobs": [],
        "error": {"code": code, "message": message},
    }


def text(value):
    value = str(value or "")
    value = re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s]+@", r"\1[redacted]@", value)
    return "".join(c for c in value if c >= " " and c != "\x7f")[:1024]


def reasons(value):
    return [text(item) for item in (value if isinstance(value, (list, tuple)) else [value]) if item]


def queue_id(uri):
    parsed = urlsplit(uri)
    parts = parsed.path.split("/")
    if len(parts) != 3 or parts[1] not in ("printers", "classes") or not parts[2]:
        raise PrintingError("invalid_response", "CUPS returned an invalid queue identity.")
    return unquote(parts[2])


def local_uri(uri):
    queue_id(uri)
    return "ipp://localhost" + urlsplit(uri).path


def timestamp(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def job_record(job_id, attrs, username):
    uri = attrs.get("job-printer-uri", "")
    printer_id = queue_id(uri) if uri else ""
    state = JOB_STATES.get(attrs.get("job-state"), "unknown")
    own = attrs.get("job-originating-user-name") == username
    # UUIDs survive UI refreshes but not ID reuse after a CUPS reset. Without
    # one the row is still visible; mutations fail closed.
    uuid = attrs.get("job-uuid")
    identity = hashlib.sha256(
        json.dumps([job_id, uri, uuid], separators=(",", ":")).encode()
    ).hexdigest() if uri and isinstance(uuid, str) and uuid.startswith("urn:uuid:") else ""
    allowed = own and bool(identity)
    return {
        "id": job_id, "printer_id": printer_id, "printer_uri": local_uri(uri) if uri else "",
        "identity": identity, "title": text(attrs.get("job-name")),
        "user": text(attrs.get("job-originating-user-name")), "state": state,
        "state_reasons": reasons(attrs.get("job-state-reasons", [])), "own": own,
        "can_hold": allowed and state == "pending",
        "can_release": allowed and state == "held",
        "can_cancel": allowed and state in ("pending", "held", "processing", "stopped"),
        "created_at": timestamp(attrs.get("time-at-creation")),
        "completed_at": timestamp(attrs.get("time-at-completed")),
    }


def warning(code, message):
    return {"code": code, "message": message}


def merge_private_details(jobs, owned, username):
    result = dict(jobs)
    for job_id, attrs in jobs.items():
        private = owned.get(job_id)
        if not private or private.get("job-originating-user-name") != username:
            continue
        visible_identity = job_record(job_id, attrs, username)["identity"]
        private_identity = job_record(job_id, private, username)["identity"]
        if visible_identity and visible_identity == private_identity:
            result[job_id] = {**attrs, **private}
    return result


def read_jobs(connection, which, limit, username):
    kwargs = dict(which_jobs=which, limit=limit + 1, requested_attributes=JOB_ATTRIBUTES)
    visible = connection.getJobs(my_jobs=False, **kwargs)
    # pycups adds requesting-user-name only with my_jobs=True. CUPS normally
    # redacts even our own job titles/owner in the all-jobs response.
    owned = connection.getJobs(my_jobs=True, **kwargs)
    return merge_private_details(visible, owned, username)


def system_warnings():
    result = []
    for unit, code, message in [
        ("avahi-daemon.service", "discovery_unavailable",
         "Avahi is not active. DNS-SD discovery and dnssd printer addresses may be unavailable."),
    ]:
        try:
            check = subprocess.run(
                ["systemctl", "is-active", "--quiet", unit],
                capture_output=True, timeout=1, check=False,
            )
            if check.returncode:
                result.append(warning(code, message))
        except (OSError, subprocess.TimeoutExpired):
            result.append(warning("discovery_status_unknown", "Could not check the Avahi discovery service."))
    if shutil.which("mullvad"):
        try:
            check = subprocess.run(
                ["mullvad", "lan", "get"], capture_output=True,
                timeout=2, text=True, check=False, env={**os.environ, "LC_ALL": "C"},
            )
            value = check.stdout.strip().lower().removeprefix("local network sharing setting: ")
            if check.returncode or value not in ("allow", "block"):
                result.append(warning("vpn_status_unknown", "Could not determine Mullvad local-network policy."))
            elif value == "block":
                result.append(warning(
                    "vpn_lan_blocked",
                    "Mullvad local-network access is blocked. This can prevent LAN printing and discovery "
                    "when VPN protection is active. Review Local network sharing in Mullvad if you trust "
                    "this network; smplOS never changes VPN or firewall policy automatically.",
                ))
        except (OSError, subprocess.TimeoutExpired):
            result.append(warning("vpn_status_unknown", "Could not determine Mullvad local-network policy."))
    return result


def status(connection, username, warnings):
    # getPrinters reports queues, not physical devices. Do not merge aliases
    # or probe a device URI (which may contain private credentials).
    names = [(name, "printers") for name in connection.getPrinters()]
    names += [(name, "classes") for name in connection.getClasses()]
    default = connection.getDefault()
    printers = []
    if len(names) > PRINTER_LIMIT:
        warnings.append(warning("printers_truncated", "Only the first 64 CUPS queues are shown."))
    for name, kind in sorted(names)[:PRINTER_LIMIT]:
        uri = "ipp://localhost/" + kind + "/" + quote(name, safe="")
        attrs = connection.getPrinterAttributes(uri=uri, requested_attributes=PRINTER_ATTRIBUTES)
        printers.append({
            "id": name, "display_name": text(attrs.get("printer-info") or name), "uri": uri,
            "state": {3: "idle", 4: "processing", 5: "stopped"}.get(attrs.get("printer-state"), "unknown"),
            "accepting_jobs": bool(attrs.get("printer-is-accepting-jobs", False)),
            "is_default": name == default, "is_temporary": bool(attrs.get("printer-is-temporary", False)),
            "state_reasons": reasons(attrs.get("printer-state-reasons", [])),
            "state_message": text(attrs.get("printer-state-message")),
        })
        if any(reason.startswith(("connecting-to-device", "offline", "cups-waiting-for-job-completed",
                                  "printer-unreachable", "cups-remote-pending"))
               for reason in printers[-1]["state_reasons"]):
            warnings.append(warning(
                "printer_connectivity",
                "CUPS is connecting to or waiting for a printer response. If this persists, check that the printer "
                "and computer share a reachable network, its saved address is current, and "
                "VPN/firewall policy allows the connection. Do not resend a job while its outcome is uncertain.",
            ))
    active = read_jobs(connection, "not-completed", ACTIVE_LIMIT, username)
    history = read_jobs(connection, "completed", HISTORY_LIMIT, username)
    jobs = {key: value for key, value in list(active.items())[:ACTIVE_LIMIT]}
    jobs.update(dict(list(history.items())[:HISTORY_LIMIT]))
    records = [job_record(key, value, username) for key, value in sorted(jobs.items(), reverse=True)]
    if any(not row["printer_id"] or not row["user"] or not row["identity"] for row in records):
        warnings.append(warning(
            "job_details_unavailable",
            "Some job details are absent or hidden by CUPS privacy policy. Unidentifiable jobs "
            "remain visible but cannot be controlled; empty details do not mean the job is yours.",
        ))
    warnings.append(warning(
        "cups_scope",
        "Status is reported by local CUPS, not a live printer reachability test. "
        "Only queues and jobs known and visible to CUPS are shown; application-side unsent "
        "documents and direct printer jobs are not included. History depends on CUPS retention "
        "and privacy policy; completed does not prove paper output. Queues are not merged or auto-added.",
    ))
    return {
        "protocol_version": 1, "ok": True, "server": "local", "printers": printers,
        "jobs": records,
        "warnings": warnings, "active_complete": len(active) <= ACTIVE_LIMIT,
        "history_complete": len(history) <= HISTORY_LIMIT, "history_limit": HISTORY_LIMIT,
    }


def act(connection, username, args):
    if args.id <= 0 or args.id > 2147483647:
        raise PrintingError("invalid_request", "Select one valid CUPS job.")
    if args.action == "cancel" and not args.confirm:
        raise PrintingError("confirmation_required", "Confirm cancellation of this specific job first.")
    owned = connection.getJobs(
        which_jobs="not-completed", my_jobs=True, first_job_id=args.id, limit=1,
        requested_attributes=JOB_ATTRIBUTES,
    )
    attrs = connection.getJobAttributes(args.id, requested_attributes=JOB_ATTRIBUTES)
    merged = merge_private_details({args.id: attrs}, owned, username)[args.id]
    # Recover only a missing owner, never overwrite the latest preflight state.
    if "job-originating-user-name" not in attrs:
        attrs = {**attrs, "job-originating-user-name": merged.get("job-originating-user-name", "")}
    job = job_record(args.id, attrs, username)
    if not args.identity or args.identity != job["identity"] or args.printer != job["printer_id"]:
        raise PrintingError("stale_job", "The selected job changed or is no longer identifiable. Refresh the queue.")
    if not job["own"]:
        raise PrintingError("permission_denied", "Only your own print jobs can be controlled here.")
    if not job["can_" + args.action]:
        raise PrintingError("state_changed", "This action is not available in the job's current state. Refresh the queue.")
    if args.action == "cancel":
        connection.cancelJob(args.id, purge_job=False)
    else:
        connection.setJobHoldUntil(args.id, "indefinite" if args.action == "hold" else "no-hold")
    return {"protocol_version": 1, "ok": True, "action": args.action, "id": args.id}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise PrintingError("invalid_request", "Invalid printing command. Use status --json or job --help.")


def parse_args(argv):
    parser = Parser(description="Read local CUPS status or explicitly control one owned job.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    read = commands.add_parser("status")
    read.add_argument("--json", action="store_true", required=True)
    job = commands.add_parser("job")
    job.add_argument("action", choices=("hold", "release", "cancel"))
    job.add_argument("--id", type=int, required=True)
    job.add_argument("--printer", required=True)
    job.add_argument("--identity", required=True)
    job.add_argument("--confirm", action="store_true")
    job.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        try:
            import cups
        except ImportError:
            raise PrintingError("dependency_missing", "Printing support is missing python-pycups. Run Update OS.") from None
        username = pwd.getpwuid(os.getuid()).pw_name
        cups.setUser(username)
        cups.setPasswordCB(lambda prompt: "")
        try:
            try:
                connection = cups.Connection(host="/run/cups/cups.sock")
            except (RuntimeError, OSError):
                raise PrintingError("cups_unavailable", "Cannot communicate with local CUPS. Check cups.socket/cups.service and local socket permissions.") from None
            result = status(connection, username, system_warnings()) if args.command == "status" else act(connection, username, args)
        except cups.IPPError as error:
            code = error.args[0] if error.args else None
            if code in (0x0401, 0x0402, 0x0403):
                raise PrintingError("permission_denied", "CUPS denied access. Check job ownership and CUPS authorization; no credentials were requested.") from None
            if code in (0x0406, 0x0407):
                raise PrintingError("not_found", "CUPS no longer has this queue or job. Refresh the queue.") from None
            raise PrintingError("cups_error", "CUPS rejected the request. Check printer state and the local CUPS log.") from None
        except cups.HTTPError:
            raise PrintingError(
                "outcome_unknown" if args.command == "job" else "cups_http_error",
                "Local CUPS did not acknowledge the request. Check its service and authorization. "
                "Refresh the queue before another action; do not retry automatically.",
            ) from None
        except (RuntimeError, OSError):
            raise PrintingError(
                "outcome_unknown" if args.command == "job" else "cups_unavailable",
                "Communication with local CUPS failed. Refresh the queue before another action; "
                "do not retry automatically.",
            ) from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise PrintingError("invalid_response", "CUPS returned an unsupported response. Refresh the queue or check the CUPS log.") from None
    except PrintingError as error:
        result = failure(error.code, error.message)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
