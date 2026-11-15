# Printing and print queues

**Settings > Printing** requires a compatible native Settings release from
[smpl-apps](https://github.com/smpl-os/smpl-apps), plus the OS printing helper.
`smplos-settings printing` opens the panel on either X11 or Wayland.
Updating scripts alone does not deliver the native panel.

The base ISO embeds `cups`, `cups-filters`, `python-pycups` and `avahi` and
their package dependencies in the existing offline mirror. Fresh live/install
environments enable `cups.socket` (local scheduler activation on demand) and
`avahi-daemon.service` (DNS-SD resolution). No cups-browsed, additional printer
GUI, online install requirement, or printer-specific driver collection is added.
Driverless IPP/AirPrint is preferred; older devices may still require an
appropriate driver. Existing printers and drivers remain supported.

Full **Update OS** installs missing dependencies only after the complete
official system upgrade. Its retryable core migration enables services only
when their package was newly installed by this enrollment, preserving existing
disabled/masked service policy. It never rewrites CUPS configuration, defaults,
printer names, jobs, retention, VPN or firewall rules. A machine that already
had Avahi disabled can therefore report discovery unavailable after updating;
review that policy explicitly rather than expecting an updater to override it.

## What the panel knows

Each CUPS queue has its own exact ID and optional friendly display name.
Aliases are not evidence of duplicate hardware: smplOS never merges, renames,
adds or removes queues while reading status. CUPS-known temporary queues and
classes are marked/reported separately; jobs remain visible even when their
queue is no longer listed. Discovery here means destinations already known to
CUPS, not an exhaustive network scan or an add-printer wizard.
Use local CUPS administration at `http://localhost:631` to configure queues.

Active jobs are shown separately from retained terminal history (completed,
canceled and aborted). Read limits are 500 active jobs, 100 history jobs and
64 queues; flags/warnings explicitly identify truncation. History is scoped to
records visible under CUPS authorization/retention policy, not all documents
ever printed. Privacy policy may hide other users' job details. Documents not
yet submitted by an application, direct-to-printer jobs and purged records
cannot be reconstructed. Nothing changes history retention or preserves spool
documents behind your back.

**Idle means CUPS's queue is idle, not that the physical printer is reachable.
Completed means CUPS completed processing, not proof that paper came out.**
State reasons/messages come from CUPS. A connection warning advises checking the
network, saved printer address and VPN/firewall policy without claiming which
one caused the failure. Stale information is replaced only by successful
refreshes, never by a failure-shaped empty queue.

Mullvad's local-network policy is queried read-only with a short deadline and
without querying account data. A blocked policy produces a warning that LAN
printing/discovery can fail while VPN protection applies. If you trust the
network, review **Local network sharing** in Mullvad yourself. smplOS does not
disconnect a VPN or weaken its policy, open firewall ports, or retry a stalled
document. Other VPN/firewall restrictions may exist even without this warning.

## Job controls and safety

Only the current local user's jobs expose controls. Hold is available for
pending jobs, release for held jobs, and cancel for active jobs. The backend
re-reads ownership, queue, UUID identity and state immediately before requesting
one change, and CUPS still enforces its authorization. Missing/redacted UUIDs
disable actions without hiding the row. A stale selection, terminal job,
authorization failure or missing job produces an explicit error.
Privacy-redacted queue identity/user fields may be empty; those jobs remain
visible with a warning and no controls rather than breaking all other rows.

Cancellation requires a native confirmation and the helper's `--confirm`
flag. It cancels just the selected job without purging history. It cannot
recall pages already printed or guarantee that a device stopped immediately.
There is no cancel-all, purge, restart/resend, implicit privilege elevation or
automatic action retry. Release resumes the existing held job, not a new copy.
Concurrent CUPS clients can change state after preflight: IPP has no
compare-and-swap job mutation, so the server makes the final decision.

The helper kills a blocked CUPS worker after 15 seconds. An unacknowledged
action is **outcome unknown**, not a failed action safe to repeat. Refresh
before deciding what to do. The UI uses a longer deadline and does not retry.
Status queries never connect to saved device URIs or create temporary queues.

## JSON protocol v1

`smplos-printing status --json` returns one compact JSON object on stdout.
It uses Python's maintained `cups` bindings and structured IPP attributes over
`/run/cups/cups.sock`; remote CUPS environment settings cannot redirect actions.
No localized `lpstat` output is parsed. CUPS password prompts are disabled.
The bounded all-jobs queries are enriched with current-user queries: pycups
only sends `requesting-user-name` for `my_jobs=True`, which is necessary for
CUPS to reveal the caller's own document/owner fields under default privacy
policy. Details are merged only when the exact job UUID identity matches.
Device URIs and raw exception text are not returned; URI credentials in status
messages are redacted. Job titles/users are private display data: do not log
or publish real status output in bug reports.

Success has `protocol_version: 1`, `ok: true`, `server: "local"`,
`printers`, `jobs`, `warnings`, `active_complete`, `history_complete`, and
`history_limit: 100`. Completeness means within the visible CUPS query scope,
not full historical retention. History follows CUPS's completed-job ordering.

| Record | Fields |
|---|---|
| Printer | `id`, `display_name`, `uri`, `state`, `accepting_jobs`, `is_default`, `is_temporary`, `state_reasons`, `state_message` |
| Job | `id`, `printer_id`, `printer_uri`, `identity`, `title`, `user`, `state`, `state_reasons`, `own`, `can_hold`, `can_release`, `can_cancel`, `created_at`, `completed_at` |
| Warning | `code`, `message` |

Printer states: `idle`, `processing`, `stopped`, `unknown`. Job states:
`pending`, `held`, `processing`, `stopped`, `canceled`, `aborted`, `completed`,
`unknown`. Timestamps are epoch seconds or null. URI fields identify local
CUPS queues, not physical devices. `identity` is an opaque string, possibly
empty for a non-actionable job; consumers must not derive or parse it.

Actions:

```text
smplos-printing job hold|release|cancel --id N --printer QUEUE --identity TOKEN --json
```

Cancel additionally requires `--confirm`. Use an argument array, not a shell
command string. Success: `{"protocol_version":1,"ok":true,"action":"hold","id":42}`.
Refresh after every attempt. Never automatically repeat a mutation.

Failures exit nonzero with
`{"protocol_version":1,"ok":false,"printers":[],"jobs":[],"error":{"code":"...","message":"..."}}`.
Empty arrays on errors are not an empty-queue success. Codes include
`dependency_missing`, `cups_unavailable`, `permission_denied`, `not_found`,
`cups_error`, `cups_http_error`, `invalid_response`, `invalid_request`,
`stale_job`, `state_changed`, `confirmation_required`, `timeout`,
`outcome_unknown`, and `backend_failed`. Do not show raw worker stderr in the
native UI; report the structured message.

For development, `python3 src/shared/bin/smplos-printing status --json` is
read-only and uses the checkout's module. Tests use synthetic CUPS, package and
service fixtures; no real queue, VPN, spool, service or package is mutated:

```bash
python3 -m unittest discover -s tests -p test_printing.py -v
```
