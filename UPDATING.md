# smplOS Update System

How to prepare and ship updates for smplOS. Written for both human
contributors and AI assistants (Copilot, etc.).

## Architecture Overview

smplOS uses a **git-based update system**. The repo is cloned to
`~/.local/share/smplos/repo/` on each user's machine. When they run
"Update OS" (from app-center or `smplos-update --mode full`), the system:

1. Opens a terminal as the desktop user and requires external power on laptops.
2. Authenticates with sudo once; keeps that tty's authorization alive, without
   saving passwords or installing passwordless sudo rules.
3. Fast-forwards a clean `main` checkout, atomically syncs scripts/libraries,
   and re-executes the refreshed wrapper before package/config deployment.
4. Inventories installed versions and performs the complete official package
   upgrade, including the supported Hyprland series, libraries and drivers.
5. Enrolls compatible Yay and updates required foreign drivers, public shared
   libraries and transitive dependencies of the core stack.
6. Delivers core native releases (smpl-apps, st, Nemo and micro), deploys essential
   desktop configs/themes and core migrations, reconciles services and checks
   that the EWW bar is open. Persists a verified core checkpoint.
7. Attempts ordinary application configs/integrations and optional migrations,
   ordinary AUR apps, and user/system Flatpak apps/runtimes.
8. Verifies the core again and writes a local installed-state report. Required
   success records the OS version; optional failures produce **Update complete
   with warnings**, not **Update incomplete**.

The priority split applies to foreign/native apps and config migrations, not
individual official packages: all official packages still upgrade together in
one complete Arch transaction. `--mode apps` delivers the same core native
releases and scoped Flatpak updates, without claiming a base-system or
desktop-config upgrade.

Run as the desktop user, **not** through sudo/pkexec. Root orchestration and
later `runuser` contexts were responsible for repeated password prompts and lost
graphical-session state. Subsequent privileged commands use noninteractive
sudo: lost authorization is an explicit error, not another password prompt.
Shared helper libraries are installed into an explicitly mode-0755 directory,
with mode-0644 files, even when recovery runs with `umask 077`. Existing
root-only library-directory permissions are corrected before installing files.
Failed installs report the operation, destination, exit status and underlying
command error instead of hiding verification failures behind a silent comparison.
An enclosing recovery launcher may set `SMPLOS_UPDATE_NO_HOLD=1` to suppress
startup/bootstrap Enter-to-close prompts and handle the final error display itself.
`--mode apps` updates native/Flatpak apps only, without an official/AUR host
package upgrade or desktop configuration deployment. A release needing newer
host libraries can fail validation; use a full Update OS instead.

The update lock is per user, not machine-wide; do not run other users' updates
or a separate package manager concurrently. Logs remain on the machine; there
is no report upload. AC checks reduce the risk of interruption but **do not
make Arch updates or installation power-loss-safe**. No disk-layout changes,
automatic rollback or boot recovery are provided by this flow.

OS-owned changes reach users after merging to `main` and running the updater.
Changes to independently built apps also require a release in their own repo.

### Standalone mouse-remapper adoption

Older development installs can have an unowned `/usr/bin/mouse-remapperd`
before the `control-surface` package starts shipping it. The repeated keypad
package reconciliation checks ownership and the daemon's read-only feature API
in an isolated profile. A recognized, regular standalone executable can be
adopted with an exact-path pacman overwrite in the validated package transaction.
Other packages' files retain normal pacman conflict checks; unrecognized files,
directories and symlinks are left untouched with an explicit retry error.
Mouse/keypad mappings, custom units and other user data are not removed.

If a required deployment fails, optional AUR work is skipped. Final verification
only requests a Brave target report when target capture was actually attempted,
so a skipped stage does not generate a misleading missing-report warning.

### Standard GTK defaults and missing-icon repair

Stock palettes no longer select Yaru icon packs that smplOS does not ship.
Adwaita and hicolor icon packages are explicit ISO dependencies; a required core
migration installs missing packages only after the complete system upgrade.
The shared GTK preference helper repairs an unavailable icon-theme selection to
installed Adwaita, retains installed personal icon themes, and keeps GSettings
and GTK3/GTK4 settings.ini icon selections consistent. Theme switching ignores
legacy `icons.theme` metadata, including in custom palettes.

Light/dark changes use standard GSettings and GTK preferences, not a global
`GTK_THEME` override. GTK4 settings no longer contain GTK3-only mnemonic keys.
Fonts, cursors, other personal settings and app-local CSS are preserved; Nemo's
native CSS/theme delivery is unchanged. Before changing existing settings, the
helper saves and verifies originals under
`~/.local/state/smplos/backups/gtk/` (private directory/files, content-addressed
backups retained across retries). GSettings originals are readable JSON.

Update OS delivers the helper and migration, refreshes stock themes through the
existing verified-backup path, and reapplies the active palette. Known stock
overrides are also removed from environment.d and existing Hyprland/Niri config
files, including Niri's stored assembly input. Finalization clears the systemd
and D-Bus activation overrides and Hyprland's launcher environment. Running apps
and terminals retain their inherited environment; log out/in after updating
before comparing apps on either machine. No installed app is forcibly closed.
Custom explicit `GTK_THEME` configuration on disk is not removed.

For the Mission Center regression, after Update OS and a new login, check
`gsettings get org.gnome.desktop.interface icon-theme` (normally `Adwaita`),
then launch the unmodified pacman `missioncenter` package. Switch between a
light and a dark smplOS palette and repeat: icon selection must remain installed,
GTK4 must not emit unknown-mnemonic-setting warnings, and startup must not
stack-overflow. The updater does not install or replace Mission Center or btop.
An unavailable icon theme alone may still fall back successfully on a clean
profile. The reproduced crash also used a user-local `hicolor/index.theme`
listing only application-icon directories, hiding the standard status-icon
fallback directories. The repair preserves that user file and supplies a valid
selected theme instead.

`src/test-gtk-defaults.py` exercises a private profile and bus, including a
shortened local hicolor index, actual GTK3 settings and live libadwaita
dark/light/dark transitions. Run it with the system Python/GTK introspection
packages, or through `xvfb-run -a /usr/bin/python3 src/test-gtk-defaults.py`.

### OpenChamber theme bridge delivery

The bridge is OS-owned; OpenChamber's renderer and local control API are
independently released. Publish and verify the compatible OpenChamber release
**before** publishing the OS bridge. A successful broadcast or a custom JSON
file on disk is not proof that a window applied the palette or background alpha.
Keep the bridge unpublished until the app's capability and renderer-acknowledgment
contract and per-app transparent-window launcher have been verified together.
The bridge requires protocol 1 from authenticated `theme.capabilities`, live
window probes, custom themes, background alpha in `(0,1]` and a bounded
acknowledgment deadline. Translucent themes require each target's actual native
transparent readiness. `theme.set` must return matching renderer-applied theme
IDs and alpha for the same windows after persistence; broadcast delivery alone
is rejected. Each HTTP request allows 15 seconds for the app's 10-second bound.
Failure after publication can be partial and must remain explicitly unconfirmed.
Do not infer compositor properties from renderer acknowledgment.

The first compatible published app is
[KonTy/openchamber v2.5.2](https://github.com/KonTy/openchamber/releases/tag/v2.5.2),
source `506a35feeabd4dfb95917bf533cb1ceb6332aff9`, built and tested by
[Linux release workflow 40133651791](https://github.com/KonTy/openchamber/actions/runs/40133651791).
Its public `provenance.json` and `SHA256SUMS` identify the independent packages;
the bridge does not download them. Packaged isolated two-window runs exercised
the actual bridge through Amber, Catppuccin and Amber, checked exact palette,
alpha, acknowledgments and durable selection, and rejected translucent themes
before writes on framed/explicitly opaque launches. Bearer-only local control
was verified with UI password authentication still enabled. Native readiness
and renderer CSS were checked; compositor output remains unmeasured by these
packaged tests.

Normal script synchronization installs `theme-set-openchamber` alongside
`theme-set`, and normal Hyprland config synchronization delivers the native-alpha
tag in both `windows.lua` and `windows.conf`. The existing final opacity policy
must remain last. The ISO copies the same script and compositor trees; no
separate migration or hardcoded installer list is necessary. The optional app
phase invokes `theme-set --apps`; the core-only phase does not contact
OpenChamber. Bridge errors are visible but do not abort other theme consumers.

This does not enroll OpenChamber as a core OS binary or install an app package.
Its independent compatible release must already be installed and running.
Never launch/restart it from `theme-set`, rewrite personal desktop launchers,
set transparent-window environment flags globally, or point production users
at a temporary demo data directory. Package/release installation is separate
from bridge delivery. Test delivery against an isolated HOME and local server,
not the maintainer's real settings or sessions.

Settings backups can contain the local API bearer token. Keep backup roots
and target directories mode 0700 and files mode 0600; never include their
contents in logs, CI artifacts or release uploads. Preserve backups and
custom-only themes. Remove only the temporary demo target override after a
demo, not the app's settings or session data.

### Completion receipts and App Center

The coordinator explicitly unlocks the stable `update.lock` file before its
final terminal acknowledgement and reboot notification. Detached notifications
never inherit descriptor 9. A terminal waiting for Enter is not an active
package transaction and must not prevent a retry. Do not delete/recreate the
lock or infer lock ownership from a stale PID file.

After a successfully verified update, a reboot marker matching the current
kernel boot ID deliberately blocks another full **Update OS** with **Reboot
required**. This is separate from the running-update lock. Failed/interrupted
updates remain retryable, scripts-only enrollment and apps mode are not blocked,
and a marker from a previous boot does not prevent updating. The refusal releases
the lock before its final prompt and does not publish a success receipt.
It also re-shows the actionable reboot reminder without retaining the lock.

The red reboot notification has a default click action. Clicking it opens a
second **Restart smplOS now?** confirmation notification: save your work, then
click that confirmation to restart. Dismissing either step cancels; there is no
automatic reboot timer. A refused restart is reported, and the marker remains.
Confirmed restarts also refuse while the updater holds its lock, rather than
interrupting an active transaction.

A client may choose a fresh, unique absolute `SMPLOS_UPDATE_LOG_FILE` path in
the desktop user's private update-state directory. The environment value
survives terminal launch and updater refresh. After final verification,
version finalization and lock release, the coordinator atomically publishes
`<log-path>.result` using this key/value protocol:

```text
protocol=1
status=complete
stage=finished
log=<exact requested absolute log path>
mode=full
core_verified=1
optional_phase_warnings=0
lock_released=1
```

Other statuses are `complete-with-warnings`, `failed` and `interrupted`.
Interruption retains its last stage; a historical core checkpoint is not
success. Bootstrap failures, old updaters and abrupt power loss may leave no
receipt. Absence is unverified completion, never success. The shared `status`
journal is written while still holding the lock and is not a client completion
receipt: a new update can replace it independently.

Terminal-server launchers can return before their window exits. Clients should
reap their own launcher without interpreting exit zero as OS completion and
watch their unique receipt independently of launcher/terminal lifetime. Only
a correlated, successful full-update receipt and an actually changed installed
App Center executable justify offering restart. Restart must wait for an idle
App Center, close inherited lock descriptors, and remove updater authentication,
handoff and coordinator environment flags. Closing/reopening after successful
installation also adopts the new binary; replacing a file does not change the
already-running executable.

### Flatpak remote failures

User and system installations update separately after the required core.
Flatpak can exit zero while keeping installed refs whose remote fetch failed.
The coordinator retains each attempt's complete output in
`<log-path>.flatpak-<scope>-<attempt>.log`, refreshes remote metadata with
`remote-ls`, and retries once. Continued unresolved refs or metadata failures
become retryable optional warnings, not an unqualified app-update success and
not a failed core update. Remote URLs, enabled/filter settings, signature
verification, installed app data and runtime ownership are not rewritten.

After a successful full base upgrade, cleanup retires `lib32-mpg123` only if
Pacman confirms it is still an unneeded dependency and no configured repository
ships it. Explicitly installed, required or repository-provided copies stay
installed. This avoids rebuilding the retired orphan with an AUR recipe that
requires JACK2 in conflict with PipeWire's JACK provider; it never replaces
PipeWire, removes other orphans, or recursively removes dependencies.

---

## Quick Reference: What Goes Where

| What you changed | Where it lives | How it reaches users |
|---|---|---|
| Script (bin) | `src/shared/bin/` | `smplos-os-update` syncs to `/usr/local/bin/` |
| EWW widget | `src/shared/eww/` | All stock Yuck/SCSS fragments and scripts sync; generated palettes stay theme-owned |
| Hyprland config | `src/compositors/hyprland/hypr/` | OS-owned `.conf`/`.lua` files sync automatically; user-owned exceptions below |
| Theme | `src/shared/themes/` | `post_deploy()` reapplies current theme automatically |
| Keybindings | `src/shared/configs/smplos/bindings.conf` | Needs migration if format changed |
| smpl-apps (Rust) | `smpl-os/smpl-apps` repo | `smplos-update-apps` downloads from GitHub releases |
| st-smpl | `smpl-os/st-smpl` repo | `smplos-update-apps` downloads from GitHub releases |
| nemo-smpl | `smpl-os/nemo-smpl` repo | `smplos-update-apps` downloads from GitHub releases |
| Breaking change | `migrations/` | `smplos-migrate` runs it exactly once per user |
| OS version | `src/VERSION` | `sync_version()` updates `/etc/os-release` |

The EWW package remains pinned to `smpl-os/eww` commit `0eb4604`. As checked on
2026-10-18, upstream lacks both button-grab fixes and the fork's cross-backend
`:passthrough`. [elkowar/eww#1428](https://github.com/elkowar/eww/pull/1428)
contains only the first click fix, not the second, and remains open.
[elkowar/eww#1437](https://github.com/elkowar/eww/pull/1437) is open and
Wayland-only, not a substitute for verified X11 keypad click-through.
Do not switch to unpatched upstream until all required behavior is present.
The OTA local-package helper does not bypass source PGP verification; EWW release builds
disable the inapplicable debug subpackage instead of running debug indexing on
a binary without debug symbols. Compiler diagnostics remain visible.

EWW package revision 4 adds the local `ipc-repair.patch`: its server waits up to
10 seconds for an application acknowledgement and the client allows 15 seconds,
instead of discarding both ends after 100 ms. Missing required replies and
expired deadlines are explicit failures, including delayed stylesheet errors.
The pinned `pkgver` matches the actual source version so makepkg does not reset
the package revision to 1. A required, retryable core migration builds and
installs the repair; a failed build leaves the old package installed.

Revision 5 corrects the `check-config` preflight to enter the EWW config directory,
just like daemon startup, before resolving relative Yuck includes. Revision 4
could incorrectly reject stock files such as `./quick-settings.yuck` when called
from the updater's working directory. A separate required core migration delivers
the correction even when the earlier IPC migration is already marked complete.

Config and palette publishers hold `.config/eww/.smplos-reload.lock`; the
repaired file watcher defers their intermediate changes to one checked explicit
reload. Direct edits outside a publication batch retain normal automatic reload.
Unchanged palettes are not rewritten, `bar-ctl ensure` verifies an existing bar
without reloading it, and geometry events redraw only when monitor geometry
actually changes. A replaced running EWW executable is activated once during
finalization, after validating the new configuration and GTK stylesheet without
executing polling/listener commands or touching the working daemon. This restarts EWW,
not the desktop or application windows; transient EWW popups close. The first
delivery can still show automatic refreshes from the old, unpatched daemon.
Finalization retries even if a previous attempt already copied every file, and
an incomplete reload still prevents successful update completion.

Required smpl-apps executables and `xr-workspace` remain ELF-only. The optional
XR module also contains the Bash wrappers `xrctl`, `xr-game` and
`xr-glasses-hotplugd`. Only those filenames accept `#!/usr/bin/env bash` or
`#!/bin/bash`; syntax is checked without execution. Bundle staging, installation
and the final audit preserve and validate all three, with installed/retained
checksum receipts still required. A complete release must not lose its wrappers
during extraction or be misreported as omitting the XR module.
Missing XR peers retain the whole validated old module, not a mixture of releases.

---

## 1. Updating Scripts

Scripts in `src/shared/bin/` are automatically deployed to `/usr/local/bin/`
on every update. No migration needed.

**Steps:**
1. Edit the script in `src/shared/bin/`
2. Test it locally
3. Commit and push to `main`

**That's it.** On next `smplos-update --mode full`, the script syncs.

For example, the screenshot capture flow lives in `src/shared/bin/screenshot`,
not in the user's Hyprland configuration. Script updates replace
`/usr/local/bin/screenshot`, and the next capture uses the new script.
No config refresh, migration, logout, or ISO rebuild is needed once the change
reaches `main`.

The workspace-local Nemo shortcut also changes `bindings.conf`, which is
user-managed and normally preserved during updates. Migration
`20260929-143800-nemo-current-workspace.sh` backs up and changes only the stock
Super+Shift+F command in existing Hyprland/shared bindings and niri configs;
custom commands and other shortcuts remain untouched. New ISO builds ship the
updated binding and both launcher scripts through the existing shared-file copy.

Super+K follows the same pattern. It opens the Settings app on its Keybindings
tab (`settings --tab keybindings`) instead of the `keybind-help` list, and
migration `20261020-154500-super-k-settings.sh` backs up and repoints only the
stock bind in existing `~/.config/smplos/bindings.conf` and
`~/.config/hypr/bindings.conf`. A bind with another command or description, a
second bind on the same chord and a symlinked file are left alone. The tab and
its focused filter box come from the Settings app, so they arrive with the
matching smpl-apps release. niri's `binds.kdl` is only refreshed by new ISO
builds, so an existing niri install keeps calling `keybind-help` until its
configs are redeployed.

The Mouse tab saves pointer speed, acceleration and scroll options to
`~/.config/hypr/pointer.conf`, and `pointer_loader.lua` restores them when
Hyprland starts or reloads (it runs right after `input.lua`). The loader comes
with the normal Hyprland config sync and the tab with the matching smpl-apps
release. Updates never replace the file (it is protected in `smplos-os-update`
and `smplos-update-check`) and the ISO ships none. `hyprland.conf` does not
source it, so after a rollback to hyprlang the options still apply live but
are not restored at login; see the
[pointer.conf contract](src/compositors/hyprland/hypr/README.md#pointerconf-contract).

### Monitor-owned workspace rollout

`workspace-ctl` and the EWW monitor overview are OS-owned scripts/configs; they
do not require a separate smpl-apps release. Python is an explicit shared
package and is already a dependency of the shipped `archinstall` package.

The updater publishes the overview fragment before `eww.yuck`, and Hyprland
modules before the configuration entry points. These files are atomically
replaced as the invoking user, avoiding partial includes and root-owned user
configuration files during live reload.

Migration `20260929-195600-monitor-owned-workspaces.sh` reconnects to the user's
Hyprland session, reloads the complete configuration, and runs
`workspace-ctl enroll`. Enrollment creates automatic left-to-right round-robin
homes only when no saved preference exists. Existing mappings, fixed-home
choices, and opt-outs are never overwritten. It reloads an already-running bar
without killing it. Without a live Hyprland session, setup is deferred to login.

`workspace-session-init` performs the same first-login enrollment on fresh
ISOs, applies enabled saved mappings, and preserves disabled preferences.
Niri/X11 do not enroll. The ISO builder already copies all shared scripts,
EWW fragments, and Hyprland Lua modules into both the live system and installer
payload. Monitor identities and workspace assignments are generated on the
target machine; no developer profile is shipped.

Plain Super+number bindings use Hyprland's native workspace focus, with homes
provided by the generated workspace rules. The binding itself does not invoke
policy reconciliation, reload configuration, or dispatch window/workspace moves.
Relative/previous navigation still resolves monitor-local IDs through
`workspace-ctl`; modified send/move shortcuts remain explicit moves.

---

## 2. Updating Configs (EWW, Hyprland, foot, etc.)

Config ownership determines update behavior. EWW's OS-owned entry point,
overview fragment, stylesheet and scripts are refreshed. Hyprland's OS-owned
`.conf`/`.lua` files and `apps/` rules are refreshed on every normal update,
even when no new commits were pulled. Modules are published atomically before
entry points, so includes never refer to a module not yet installed.

Existing `hypridle.conf`, `monitors.conf`, `bindings.conf`,
`messenger-bindings.conf`, `theme.conf` and `hyprlock-theme.conf` are protected
from default-file replacement. Only a truly absent `hypridle.conf` is
bootstrapped; symlinks (including dangling links) are not treated as missing.
Other application configs are not automatically refreshed unless an updater
step or migration explicitly owns them.

Because `bindings.conf` is protected, a fix to a stock bind reaches existing
installs only as a [migration](#5-writing-a-migration); fresh installs get the
new file. `tests/fixtures/keybindings.snapshot.txt` pins what every stock bind
does, so changing one fails `test_keybindings` until the snapshot is updated,
which is the cue to write that migration (`migrations/20261019-153100-remove-duplicate-popup-click-bind.sh`
is a worked example). `tools/keybind-check check --live` and
`diff --live` audit what a machine really loads (see
[Testing Keybindings](DEVELOPMENT.md#testing-keybindings)).

### Option A: Non-breaking change (additive)
For an OS-owned config, commit the change and normal updates deliver it.
For a user-owned config, users who explicitly want the new defaults can run:
```bash
smplos-refresh-config hypr/hyprlock.conf
```
This backs up their version and copies the new default.

### Option B: Breaking change (must update or things break)
Write a migration. See section 5 below.

### Device-triggered keypad delivery

Normal OS updates reconcile keypad integration on every run, not only once
per migration: the canonical `control-surface.service`, udev rules and pinned
`control-surface` package from **smpl-apps v0.8.35** must all be available.
That release builds the keypad daemon on its Qt 6.11 baseline, compatible with
the installed Qt 6.11.2 runtime; v0.8.27 incorrectly required Qt 6.12.
The catch-up migration `20261009-010000-keypad-login-recovery.sh` covers
already-marked installs. Package/build/privilege failures remain explicit
and retryable; a missing recipe is an error, not a pending placeholder.
The package smoke-tests both `control-surfaced features --json` and
`mouse-remapperd features --json` against the build host's runtime. Updates also
check the installed binary before replacing a
working unit or retiring its login helper. Offline or ABI-incompatible delivery
retains those units and leaves the update incomplete.

`src/shared/lib/smplos-keypad-units.sh` is shared by updates, ISO skel staging
and post-install setup. It tracks the last installed unit, verifies backups
before changes, retires only exact known temporary login helpers, and leaves
custom units, symlinks, drop-ins and keypad mappings alone. The daemon is never
enabled for a login target: udev starts it and its device binding stops it.
The existing session login hook imports the environment before recovering a
connected coldplug keypad. No device means no keypad daemon or watcher.

Session verification runs after delivery, includes the device-triggered app
when a keypad is present, and accepts genuinely completed successful
one-shots. It retries and reports real failures and does not restart a healthy
keypad during an update. Existing running daemons adopt changed unit paths
on the next login or plug-in. Fresh ISOs carry the same unit and hook and
install the daemon from their offline mirror; rebuilding smpl-apps is not
required for this OS-only fix. See [keypad lifecycle](KEYPAD.md#lifecycle-and-footprint).

### Mouse remapping delivery

The Razer Naga V2 HyperSpeed (`1532:00b4`) backend lives alongside the keypad
backend in **smpl-apps**, sharing remapping infrastructure rather than a second
OS-local implementation. Its executable is `mouse-remapperd`, not
`control-surfaced`. It reads the existing `$HOME/.config/smplos/mouse.json`
(the legacy Settings location, independent of `XDG_CONFIG_HOME`) and
exposes a separate `org.smplos.MouseRemapper1` session D-Bus API for Settings.
Learn/Identify require the matching native Settings release; other mouse models
remain preview-only. Global mappings work through uinput; per-app selection
currently requires the Hyprland focus tracker.
Mouse and keypad assignments must share the action catalog and execution
engine, including Kdenlive API discovery, availability and dispatch. An API
action must never silently fall back to a keyboard shortcut.

`70-smplos-mice.rules` grants the seated user access only to this USB device's
input interfaces and starts `mouse-remap.service` through `smplos-mouse.device`.
The service has no enablement link or keypad/EWW dependency. Unplug stops it;
the shared login hook recovers coldplug after importing the graphical
environment. Verification never restarts a healthy running remapper.
The existing backed-up unit reconciliation also handles the mouse unit, with a
separate `mouse-units` ownership stamp. Custom units, links, drop-ins and saved
mouse/keypad profiles are preserved.

**Native delivery:** the pinned **control-surface v0.8.35** package includes
`mouse-remapperd`, and the matching published **smpl-apps v0.8.35** bundle
delivers Settings with complete guided setup. Both archives were built and
validated on the pinned Qt 6.11.2/glibc 2.44 baseline. The package checksum pins
the actual published archive, not a local development build.
The mouse migration and
every normal update probe `mouse-remapperd features --json` in an isolated home,
requiring learning, identify (including wheel/tilt), guided side-grid
calibration, complete guided setup (`guidedSetup`), single-gesture tilt
navigation (`tiltNavigationGestures`), Kdenlive API and passthrough capabilities,
before replacing the unit or granting device access. Missing, incompatible or
broken binaries explicitly defer integration; an ordinary OS update reports
the missing delivery instead of silently claiming remapping is installed.
Local development deployment can install the validated build directly.

Horizontal tilt resolved to mouse Back/Forward emits one navigation action
per gesture, including when held. A 100 ms quiet gap re-arms it because this
mouse reports repeated scroll events rather than a tilt release; very fast
consecutive tilts can merge, while reversing direction acts immediately.
Other mapped actions and ordinary scrolling remain detent-based.

The backend also provides guarded, explicitly confirmed onboard DPI-button
backup/apply/restore commands. These are one-shot operations, not a resident
vendor service or firmware flashing. Normal OS updates never run them or
rewrite onboard assignments. Users opting into F23/F24 emission must retain
their verified original backup; the receiver's independent Hypershift
assignments cannot be verified. See the native release's
`control-surface/docs/mouse-remapping.md` for the command and restore contract.

### Power preferences and command compatibility

Settings and the user own `~/.config/hypr/hypridle.conf`: updates retain exact
seconds, Never/disabled listeners, custom commands, source includes and comments.
This is **hypridle's grammar**, not a Hyprland compositor config: never source it
from `hyprland.conf` or `hyprland.lua`. A Hyprland reload does not reload hypridle.
Previously overwritten choices cannot be recovered reliably; users must
reselect those choices rather than have the updater guess them.

Settings → Power edits the file in place and refuses what it cannot reason about.
Each listener's `on-timeout` must be a lock, screen-off (`smplos-hypr-dpms off` or
the legacy dispatcher form), `systemctl suspend` or `systemctl poweroff` command.
Lock → Never (and back) also rewrites `before_sleep_cmd` and `after_sleep_cmd`:
the first must be empty or `loginctl lock-session`; the second an optional
`loginctl lock-session; sleep 0.5; ` prefix plus a wake chain of
`smplos-hypr-dpms on`, `hyprctl reload` and `sleep N` steps. Anything else fails
with a generic save error (the reason goes only to Settings' stderr). The stock
file must therefore stay inside that grammar, and a Settings release that
understands a new shape must ship **before** the stock file uses it. Settings
releases that accepted a single wake command refuse the stock nvidia chain and
cannot set Lock → Never. `IdleSettingsContractTests` in
`tests/test_power_update.py` pins the stock file to this grammar; the editor's
side is `settings/src/power.rs` in smpl-apps. Stock comments never state
timeouts, because Settings changes the values but not the comments.

Screen off always takes precedence over the lock screen. `lock-screen` (the
`lock_cmd`, also behind Super+L and the power menu) never wakes the display:
monitors that are asleep when the lock starts stay asleep, and Hyprland wakes
them on the next key press or mouse move (`misc:key_press_enables_dpms`,
`misc:mouse_move_enables_dpms`) with hyprlock already on screen. It used to run
`dpms on` first, which lit the monitors with only the lock-screen clock and
nothing turned them off again until the next input. Only the wake after suspend
(`after_sleep_cmd`) turns the display on, after the re-lock. The log line
`outputs at lock: HDMI-A-1=off DP-3=on` in `~/.cache/smplos/lock-screen.log`
records which outputs were asleep. `LockScreenTests` in
`tests/test_power_update.py` pins this.

Saved timers only work while `hypridle.service` runs. It is
`WantedBy=graphical-session.target`, which nothing activated before
`smplos-session.target`: the daemon ran only after Settings or an update
restarted it, so timers silently stopped after every reboot. Every update
installs the target into `~/.config/systemd/user` and starts it in a running
session; at login `smplos-session-services` starts it and warns when power
timers are not active (log: `~/.cache/smplos/session-services.log`). Verify
power changes after a **reboot**, not only in the session that applied them.

Known stock legacy/Lua DPMS commands are migrated to `smplos-hypr-dpms on|off`.
The helper probes the **running** config provider with a bounded read-only
request, including legacy pre-Lua sessions. It checks both IPC exit status and
reply; `--check` performs no DPMS action. It does not infer the active parser
from the installed package, which may have been upgraded since login, and
unknown capabilities fail explicitly. Future upstream syntax changes still
need tested, targeted compatibility changes; preserving preferences cannot
guarantee compatibility with unknown future releases.

Migration `20260930-120000-preserve-idle-preferences.sh` catches up already-marked
July migrations and runs on every normal update, because older Settings
releases can write direct dispatcher syntax again. It edits only recognized
whole stock command values (including reversible `# smpl-settings-disabled: `
lines), never arbitrary shell commands or sourced files. A unique adjacent
backup precedes atomic publication; symlink targets retain the symlink, owner
and permissions. Preflight resolves relative source includes beside the original
config pathname, not beside a cross-directory symlink target. Custom command
syntax and includes remain the user's responsibility. Changing stock timeout
defaults does not change saved choices.

Before publication, the installed hypridle parser runs against a private,
nonexistent Wayland socket. Parser diagnostics fail the migration, except
`No rules configured` for all-Never; no idle actions execute during this check.
The parser is not a complete semantic validator (unknown fields may be ignored
by upstream). Applying changed/bootstrap configs uses the invoking user's
`hypridle.service`, checks restart and active status, and never kills processes
by name or spawns an unmanaged daemon. Active status is not acknowledgement
that every individual rule has fired.

Interrupted/failed application retains
`~/.local/state/smplos/hypridle-apply-pending`. Unchanged repeated updates do not
restart the daemon/reset its countdown. No graphical session or an unmanaged
daemon defers application and leaves migrations unmarked, without blocking
unrelated/non-Hyprland updates. A service or parse failure is reported as an
incomplete update. For an old bare autostart daemon, run a **normal Update OS**
(not only `--migrate`) to refresh OS-owned autostart, log out/in, then retry.
The existing process is deliberately left running until logout.

**Release order:** deliver the OS helper/scripts before the Settings release
that writes helper commands. New Settings must report a missing helper rather
than generate an obsolete fallback. OS preservation alone does not fix older
Settings' value parsing/writing; the coordinated smpl-apps release is required
for the complete Power UI fix.

### Taskbar settings and app binary delivery

App Center's **Update OS** action launches `smplos-update --mode full`. Its OS
phase refreshes `bar-ctl`, `workspace-ctl`, the EWW entry point, overview,
stylesheet and workspace-count listener. Existing `bar.conf` and saved
workspace mappings are not replaced. The theme hook reloads the bar and
reapplies its saved preferences.

The monitor-owned bar's Squares/Numbers and spacing fixes ship from this OS
repository. Settings' safe count handling, checked saves and responsive
controls ship separately in **smpl-apps v0.8.23**, together with the previously
unreleased Power and typography fixes. Push the OS changes first, then publish
the complete versioned smpl-apps binary release; a push to smpl-apps `main`
alone does not update installed apps.

Both `fetch-org.sh` (used by `smplos-os-update`) and `smplos-update-apps`
consume GitHub's latest published binary bundle. They validate the required
apps before recording its version. Confirm the release contains
`smpl-apps-<version>-x86_64.tar.gz` with the new Settings binary, not just source
archives or a standalone local build. A complete update therefore needs the
published release to be available, network access and successful installation;
do not report source publication alone as completed binary delivery.

### Calendar release and ISO delivery

The native release bundle must contain all 11 required app binaries **and**
the root `smpl-calendar-alertd.service` file (mode `0644`). The unit is owned by
smpl-apps and runs `/usr/local/bin/smpl-calendar-alertd --foreground` under the
user's `default.target`. A bare daemon invocation is not a substitute for
installing this service.

Both normal `src/build-iso.sh` builds and `--build-apps` use the latest published
smpl-apps release, not a local Rust checkout. The standard build compares its
tag with `.cache/app-binaries/.smpl-apps-version`; `--build-apps` calls
`fetch-apps.sh`. Both validate the complete bundle, retain the service, and
repair incomplete matching-tag caches. A known newer but incomplete release
fails the build rather than silently using stale binaries. Offline builds
need a complete cache or manually extracted bundle in `build/prebuilt-apps/`.

The ISO builder installs the binaries for the live system and installer
payload, and the unit plus its login-enable symlink into both `/etc/skel`
and the installer configuration payload. New users therefore receive calendar
reminders without first opening the calendar. No font or weather-icon download
is needed; those assets are embedded in the native calendar binary.

Existing-system app updates also install the release's user unit, preserving
custom units, masks and previously disabled/removed managed units. They do not
start/restart reminder daemons, run a database migration, or stop open editors.
Log out/in after updating to load the new daemon and its additive tracking
migration. The targeted smpl-apps development deploy separately performs a
verified database backup and exact-identity cleanup of legacy duplicate daemons;
the normal OS updater deliberately leaves live processes alone.

---

## 3. Updating Themes

Theme files in `src/shared/themes/` are automatically reapplied after
an update that changes OS source, stock themes, native apps or compositor
configuration, via `theme-set <current-theme>` in the post-deploy hook.
The hook must run as the desktop user (with their graphical session environment),
not as root with the user's `HOME`: root-owned active theme directories prevent
subsequent theme changes. `theme-set` rejects that elevated invocation.

**Steps:**
1. Edit `src/shared/themes/<name>/colors.toml`, shared templates in
   `src/shared/themes/_templates/`, or `src/regen-nemo-css.py` for Nemo CSS.
2. Run `bash src/regen-all-themes.sh`, then
   `bash src/regen-all-themes.sh --check` (non-mutating drift comparison).
3. Exercise isolated tests, then test theme application on an authorized
   test desktop. Commit both sources and generated outputs.

Users get the updated theme automatically on next update.
Both stock trees in `~/.local/share/smplos/themes/` and existing matching
overrides in `~/.config/smplos/themes/` are replaced with the exact current
bundled contents, including removal of obsolete files. Each changed tree is
copied and byte-verified in `${XDG_STATE_HOME:-$HOME/.local/state}/smplos/theme-backups/`
before publication; its `path` file identifies the original location.
Custom-only theme names are preserved. Publication shares the theme-switch
lock and restores the old tree if the final rename fails. Protected old files
that cannot be cleaned are retained with an explicit warning, not discarded.

Grafium is temporarily excluded from **every ISO edition**, including Base,
Productivity and All, until its AUR package is published. The OS-local
`grafium-bin` recipe and GitHub-release delivery have been removed. Update OS
does not install, upgrade or audit Grafium's binary, launchers or old release
markers; installed `grafium-bin` remains explicitly excluded from both OS AUR
transactions. Existing installations, notes, settings and custom launchers stay
untouched. Future delivery will use the published AUR package, prebuilt into
the appropriate ISO edition for offline installation, with application updates
owned by App Center rather than a separate OS-native updater. Do not claim AUR
availability before that package is published. Theme and compositor support
remain for independently installed copies.

Migration
`20261017-180000-replace-logseq-with-grafium.sh` retires installed Logseq package
variants, user/system Flatpaks and the OS-bundled AppImage. It never uses
recursive dependency removal, Flatpak `--delete-data` or `--unused`, and never
touches notes, graphs, `~/.logseq`, plugins or Flatpak application data.
Managed AppImage/Flatpak launcher overrides receive verified backups before
retirement; custom launchers remain untouched. The old first-boot Flatpak list
is backed up and atomically filtered so another login cannot reinstall Logseq.
`theme-set` no longer configures Logseq,
so preserved old preferences/EDN cannot fail an otherwise successful update.
New builds remove all three Logseq formats, prune cached Logseq and unbundled
Grafium package/repo records, and stage only selected AppImages/Flatpaks rather
than stale cache lists. This only prunes disposable build artifacts, not any
installed application or personal files.

### Background-only transparency delivery

This feature crosses independently released binaries. OS source alone is
**not** delivery of native alpha support. Keep owned native apps at compositor
opacity 1.0. Other ordinary apps intentionally use theme-controlled whole-window
alpha, which fades text and images too; stock active/inactive values are equal.

1. Ship the OS palette/template/CSS and both Hyprland rule trees together.
   Publish the final `opacity-policy.lua` / `.conf` modules before the entry
   points that load them last, after all browser/messenger/app rules. This
   guarantees native/media/PiP/known-game/fullscreen exemptions win. Ordinary
   browser/messenger stock keys follow the theme; optional author overrides
   cannot bypass the final safety policy.
   Keep the explicit class wildcard on role-based opacity rules: Hyprland 0.56
   needs that dependency to replay exemptions and browser/messenger overrides
   after title changes. Verify per-window `opacity`, `opacity_inactive` and
   `opacity_fullscreen`, including after navigation/title updates; a visible
   `self-managed-alpha*` tag and neutral global settings are insufficient.
   `app_background_opacity` is explicit in all 17 stock palettes; it generates
   `$theme-app-background-opacity` for native readers. `sync_themes()` copies
   stock data and matching overrides after verified backups, and `post_deploy()` reapplies the active
   theme as the desktop user. No one-time migration is required.
2. Publish compatible **nemo-smpl** and **smpl-apps** binary releases from their
   own repositories. Nemo CSS gates root alpha and transparent descendants with
   `.smplos-native-alpha`, so an older Nemo remains opaque. Capable Nemo also
   requires a composited screen and tracks compositor loss/restoration; merely
   having an RGBA visual must not enable alpha on noncomposited X11.
   Old smpl-apps keeps
   its legacy popup behavior; a new regular-role reader falls back to explicit
   popup alpha for old generated custom palettes, then safe opaque 1.0.
3. Release/package the compatible **Grafium** Linux build separately, outside
   the OS update. Updating OS theme files or a source checkout cannot update
   its native Tauri/WebKit window. ISO inclusion is deferred until AUR publication.
   Grafium consumes active `colors.toml` only in Auto mode; explicit built-in
   palettes remain opaque.
4. After installing the new binaries, reopen the affected apps once so their
   native RGBA-capable windows are created. Further theme switches are live.
   Do not restart the whole desktop or close user documents as part of theme
   generation. Repeated transparent -> opaque -> transparent switches must work.

The active `current/theme` directory is replaced during switching, while
`nemo-theme.css` and EWW's `theme-colors.scss` are atomically renamed into place.
Watch parent directories/reopen paths rather than keeping stale file watches.
Invalid explicit alpha reports an error; it must not silently fall through to
another transparency control.

smpl-apps honors an absolute XDG palette location but falls back to the deployed
HOME path only when that preferred file is absent; existing invalid/unreadable
files log an error and retain the last good palette. Discovery is retried on
every poll. This is consumer compatibility, not a migration of `theme-set`'s
canonical `$HOME/.config` writer.

Nemo's CSS reader uses the same absolute-XDG preference and absent-only HOME
fallback for `smplos/nemo-theme.css`. It watches both directory hierarchies for
creation, replacement and removal. Empty/malformed/unreadable preferred CSS
retains the last good provider with a reported error; both candidates absent
restores stock GTK. Include this reader and the compositor-availability gate
in the compatible Nemo release, not just the initial RGBA visual change.

**ISO boundary:** the builder copies pre-generated theme files and OS scripts
into the live image, user skeleton and installer payload. It seeds the default
Nemo CSS path and EWW palette before the first theme switch. Native app builds
consume published binary bundles. There is no tracked smpl-apps submodule in
this repository: `--build-apps` calls `build-apps.sh`, which also fetches the
smpl-apps release via `fetch-apps.sh`; it does not compile unpublished Rust
changes. Build and publish those in the independent smpl-apps repository.
Confirm cached/prebuilt Nemo and smpl-apps packages
actually contain the compatible binaries before advertising native alpha on an
ISO. Installation itself remains offline. Do not point at an unpublished local
commit or claim a release version that has not been published.

### Native delivery checks and recovery

For a coordinated rollout, publish and verify the native release assets before
advertising the complete OS update. The OS integration is backward-compatible,
but source pushes alone are not binary delivery. A latest release must not be a
draft, prerelease or source-only tag:

| Consumer | Published artifact | Installed destination |
|----------|--------------------|-----------------------|
| smpl-apps OTA and ISO | `smpl-apps-<version>-x86_64.tar.gz`, flat ELF apps, calendar unit and optional XR module | `/usr/local/bin/` (also installer payload on ISO) |
| Nemo OTA | `nemo-smpl-<version>-1-x86_64.pkg.tar.zst` | Pacman-managed `/usr/bin/nemo` and `/usr/libexec/` helpers |
| Nemo ISO fallback | `nemo-smpl-<version>-arch-x86_64-rootfs.tar.zst` | Repackaged with current runtime dependencies |

The smpl-apps bundle contract requires all **11** binaries, including
`smpl-hints` and `smpl-hintsd`. Sync Center's executable is `sync-center-gui`
but its window app ID is `sync-center`; `smpl-calendar-details` is a window
from the calendar binary, and `hints-overlay` is owned by `smpl-hintsd`.
A matching version marker does not bypass missing-binary checks, either in
the download cache or installed bundle. Optional XR binaries remain optional.
When included in the installed bundle, they receive the same linkage preflight
and checksum receipt as the required apps. If a new release omits any installed
optional XR binary, the installed XR module is retained together rather than
mixing old/new peers or blocking the 11 required apps. Retained executables
must be executable ELF files with valid runtime linkage, or one of the three
syntax-verified Bash wrappers above, and match prior checksums when recorded.
Missing/broken/tampered retained files still fail explicitly.
Only delivered binaries enter `smpl-apps.sha256`; `smpl-apps-retained.sha256`
separately covers bytes **not upgraded** by the new suite release. Both are
required to cover every present/previously recorded optional executable. The
audit reports `delivery: retained-not-upgraded` and a warning, not a false
claim of new XR delivery. A subsequent complete XR release clears that record.

Nemo downloads validate `.PKGINFO`, the application and document/archive
worker paths before installation/cache publication. When the same release
advertises `SHA256SUMS-x86_64`, its basename checksum must match; a missing,
duplicate or incorrect listed checksum fails the update. Older releases
without that asset explicitly report metadata-only validation. The ISO keeps
prior package archives until a replacement is validated, and fails instead of
silently using stale Nemo after a known newer download fails.
The rootfs PKGBUILD includes md4c, poppler-glib, mupdf-tools, bubblewrap,
libarchive, sqlite and libisofs, in addition to GTK/GStreamer dependencies;
pacman and the offline ISO dependency resolver deliver them with the app.

Nemo compares the actual installed pacman version and file presence,
not only the updater's cached tag. Missing same-version packages/files retry;
newer installed packages are never silently downgraded. A newer broken install
reports that its own version needs repair.

Native GUI replacement is atomic for the smpl-apps suite. Neither OS app sync
nor the native Nemo update closes user windows to force adoption.
Reopen affected apps once when ready, and log out/in for resident background
daemons. Independent app components continue after a failure, with no
version stamp for a failed install. Standalone `smplos-update-apps` returns
nonzero for any component failure. The normal OS coordinator calls
`--group core`; all four native components are required. The legacy
`--group optional` selector remains a no-op that writes an empty report,
without authentication, downloads or cache refresh. An already-running *old* outer update
wrapper may still print its old final banner; use its component errors and
retry with the refreshed wrapper rather than treating that banner as proof.

The OS updater installs refreshed scripts/libraries and re-executes its new
code before native sync. Boolean resume state carries the source-change flag,
and resumed or theme-only repairs still reapply the current theme as the user.
The normal app phase then resolves the newly installed `smplos-update-apps`.
`rebuild-app-cache` already serializes writers on `.app-cache.lock`, uses a
unique adjacent temporary file and atomically publishes `app_index`; no
second cache writer or migration is needed. A legacy `.tmp` race indicates
an older installed cache script, which the OS script-sync phase replaces.

**Scope/limitations:** regular native backgrounds use the new key; popup apps,
EWW/Rofi and terminals retain their existing controls. Matrix, Amber and
Grafium themes remain intentionally opaque. Nemo desktop, separate menus and
dialogs remain opaque; selections and media retain their own paint. Foreign
GTK/Qt/Electron apps use whole-window theme opacity on Hyprland, including faded
foregrounds. Known media/games/PiP/fullscreen are exempt from this added fade;
native fullscreen backgrounds still retain app-provided alpha. Unrecognized
windowed games/media need explicit class/content matching or an opaque tag.
Native alpha can work cross-compositor, but blur depends on compositor
support. See the [ownership/audit table](CREATING_MODIFYING_A_THEME.md#stock-palette-audit).

Before coordinated publication, run:

```bash
bash src/regen-all-themes.sh --check
python3 -m unittest discover -s tests -p 'test_theme*.py' -v
```

On a test desktop with compatible binaries, check Catppuccin, Latte, Ethereal,
Matrix and a custom theme across icon/list/split views, previews and dialogs;
owned native focused/unfocused text must remain opaque; ordinary app text is
intentionally faded equally in both states. Verify old Nemo without the
capability class remains readable, then test atomic palette/directory replacement
and restoration to alpha 1.0. This repository's static/fixture checks are not
a substitute for native rendering verification.

---

## 4. Bumping the smplOS Version

The `Auto Release` workflow calls the org's shared version-bump workflow on
pushes to `main`. It increments `src/VERSION` and creates the OS release/tag.
Do not pre-bump a fix branch just to trigger delivery; that would be bumped
again on merge.

On next update, `sync_version()` reads the new version, regenerates
`/etc/os-release` from the template, and tools like `fastfetch` and
`smplos-settings about` show the new version.

**Convention:** Use semantic versioning `MAJOR.MINOR.PATCH`.
Bump patch for fixes, minor for features, major for breaking changes.

---

## 5. Writing a Migration

Migrations handle **breaking changes** — things that will break if the
user doesn't update their local config. Examples:
- Hyprland renamed a config keyword
- EWW changed a widget structure
- A keybinding format changed
- A file moved to a different location

### Creating a migration

1. **Create the file** in `migrations/`:
   ```
   migrations/YYYYMMDD-HHMMSS-description.sh
   ```
   Use the current date/time. The timestamp determines run order.

2. **Write the script:**
   ```bash
   #!/bin/bash
   # Migration: Hyprland 0.46 renamed 'decoration:blur' to 'decoration:blur:enabled'
   # Context: https://github.com/hyprwm/Hyprland/releases/tag/v0.46.0

   set -euo pipefail

   conf="$HOME/.config/hypr/hyprland.conf"

   # Guard: skip if not applicable
   if [[ ! -f "$conf" ]] || ! grep -q 'decoration:blur ' "$conf"; then
       echo "  Already migrated or not applicable"
       exit 0
   fi

   # Do the migration
   sed -i 's/decoration:blur /decoration:blur:enabled /g' "$conf"
   echo "  Updated decoration:blur -> decoration:blur:enabled"
   ```

3. **Make it executable:**
   ```bash
   chmod +x migrations/YYYYMMDD-HHMMSS-description.sh
   ```

4. **Test both paths:**
   - On a system that NEEDS the migration (has the old config)
   - On a fresh install (migration should skip gracefully)

5. **Commit and push.**

### Migration rules

- **Always be idempotent** — check before modifying
- **Never delete user data** — rename or back up instead
- **Exit 0 on success**, non-zero on failure
- **Print what you did** — output is visible in the update log
- **One migration per breaking change** — keep them focused
- **Guard with file existence checks** — not every user has every config
- **Core by default** — unannotated/new migrations remain required. Only ordinary
  app work may declare `# SMPLOS_UPDATE_PRIORITY=optional` in its first 12 lines;
  kernel/driver/runtime/desktop compatibility work must not be demoted. Invalid
  or duplicate priority declarations are errors.
- **Package changes wait for the system upgrade** — installing or removing a
  package before the full upgrade has succeeded can leave a partial upgrade, so
  exit `75` until `SMPLOS_SYSTEM_UPGRADED=1` (Update OS sets it once the upgrade
  worked), then use `pacman -S --needed` and never `-Sy`. See
  `migrations/20261019-153000-install-hyprpicker.sh`.
- **Edit user-owned configs conservatively** — change only a line that is still
  exactly what the OS shipped, keep a verified backup, and leave customized
  lines and symlinks alone. See
  `migrations/20261019-153100-remove-duplicate-popup-click-bind.sh`, with its
  tests in `tests/test_keybinding_migrations.py`.

### Checking migration status

```bash
smplos-migrate --list       # show all migrations and their status
smplos-migrate --pending    # show only pending migrations
smplos-migrate --dry-run    # show what would run without executing
smplos-migrate --pending --phase core
smplos-migrate --pending --phase optional
```

State is in `~/.local/state/smplos/migrations/` (one empty file per
completed migration, `skipped/` subdirectory for skipped ones).

Exit `0` only for completed/not-applicable work. Exit `75` for an explicitly
deferred migration (for example no graphical session): it remains unmarked
and is retried, while unrelated updates can continue. Other nonzero statuses
count as failures. The runner attempts remaining migrations and returns
nonzero if any failed; `SMPLOS_MIGRATE_STRICT=1` aborts on the first failure.
The OS updater still attempts pending idle reconciliation before reporting
aggregate migration failure.

`--phase all|core|optional` filters listing and execution; standalone default
`all` preserves chronological behavior. Normal Update OS uses core first and
optional after its checkpoint. Optional failure still returns nonzero from the
runner and leaves the migration unmarked; only the coordinator converts that
failure into a visible warning. Never return success on an app failure merely
to keep the OS update running.

---

## 6. Updating Forked Apps (smpl-apps, st-smpl, nemo-smpl)

These apps live in separate repos and are distributed as GitHub releases.
`smplos-update-apps` downloads them automatically.

### Publishing a new release

**smpl-apps** (Rust workspace — start-menu, notif-center, app-center, etc.):
1. Merge the app changes in `smpl-os/smpl-apps`.
2. Dispatch its manual `Release` workflow (`.github/workflows/release.yml`).
3. The workflow increments the workspace patch version, builds the release
   workspace, and publishes `v<VERSION>` with
   `smpl-apps-<VERSION>-x86_64.tar.gz` plus individual binary assets.
4. Confirm the complete tarball is attached before treating the release as
   available. An OS release alone does not rebuild or publish `start-menu`.

**st-smpl** (C — terminal emulator):
1. Build: `make` in the st-smpl repo
2. Create a GitHub release with tag `v1.1.0`
3. Attach the binary (named to contain `st` and `x86_64`)

**nemo-smpl** (C — file manager):
1. Build the Arch package: `makepkg -s`
2. Create a GitHub release with tag `v1.5.0`
3. Attach the `.pkg.tar.zst` file (named `nemo-smpl-*x86_64.pkg.tar.zst`)

**Note:** Release triggers differ by repository. In particular, smpl-apps
requires the manual workflow dispatch, not merely an OS merge or tag.

### Checking app update status

```bash
smplos-update-apps --check    # report available updates (no download)
smplos-update-apps            # download and install updates
```

Version state is in `~/.local/state/smplos/app-versions/`.

### Application icon delivery

The OS cache builder resolves user desktop overrides before system entries,
including hidden overrides by desktop-file ID. It preserves the existing
`Name;Exec;Category;Icon[;1]` format and `~/.cache/smplos/` paths. Concurrent
watcher/manual refreshes use a lock, unique temporary files, and atomic
replacement. Elevated updater refreshes drop back to the invoking user.
Neither refresh nor update migrates or resets `pinned-apps.txt`.

Both update routes must remain supported:

- `smplos-os-update` syncs scripts/libraries, uses `src/fetch-org.sh` to stage
  app releases in `.cache/org-binaries/bin`, and installs to `/usr/local/bin`.
  Its fetch marker is `.cache/org-binaries/.versions/smpl-apps`.
- `smplos-update-apps` fetches the smpl-apps release tarball directly and records
  the installed version in `~/.local/state/smplos/app-versions/smpl-apps`.

Both refresh the app index even when the app binaries are already current.
Refresh failures are reported rather than hidden.

`src/shared/lib/smplos-app-bundle.sh` defines the shared required-binary set.
Downloads are extracted and checked separately before touching cached binaries;
incomplete releases cannot be completed accidentally with old cached files or
advance a version marker. A matching marker with a missing/invalid binary
triggers a retry. `fetch-apps.sh` and `build-iso.sh` now share
`.cache/app-binaries/.smpl-apps-version`; the old `smpl-apps.fetched-version`
marker is ignored.

Future ISO builds consume the same release tarball. The container installs
the required binaries into both the live `/usr/local/bin` and
`/root/smplos/bin` installation payload. Shared scripts/libraries are copied
to both locations, and the user skeleton enables the app-cache service/path
units. The installer generates the index for the new user rather than
shipping a developer's generated cache. Offline build preparation can use a
complete cached or manually supplied bundle; when a newer release is known
but fails download/validation, the build stops instead of silently embedding
old apps. Installation from the finished ISO remains fully offline.

For the coordinated menu fix, merge and release the smpl-apps icon-precedence
and safe pin-matching changes **as well as** merging the OS changes. The app
baseline inspected for this fix is v0.8.22; a release from that baseline
would become v0.8.23, but consumers follow the actual published latest tag.
No unreleased version is pinned or claimed as shipped here.

**Grafium packaging is a separate boundary.** Grafium is no longer bundled
or repackaged by smplOS while AUR publication is pending. Independently
installed releases own their application icon; smplOS does not synthesize it.
Correct user icon precedence
does not fix a blue image already contained in that package on a machine with
no good override. Use a corrected, accessible Grafium release; do not package a
developer's personal icon as a substitute.

Focused, offline regression coverage (temporary homes and mocked downloads;
no real updates, installs, or ISO builds):

```bash
python3 -m unittest discover -s tests -p 'test_app_*.py' -v
```

---

## 7. Hyprland/EWW Update Strategy

`smplos-update` upgrades the whole system, the Hyprland stack included, in
**one** pacman transaction (`pacman -Sy`, then `pacman -Su`). Arch rebuilds
Hyprland's libraries against new sonames in lockstep, so holding `hyprland`
back while they move is a partial upgrade: it fails (`installing aquamarine
(0.15.0-2) breaks dependency 'libaquamarine.so=12-64' required by hyprland`,
which blocked every system update for a month), and installing the stack
separately later can pair it with older system libraries than it was built
against (current builds need `GLIBCXX_3.4.36`), so Hyprland cannot start.

`HYPRLAND_SERIES` in `src/shared/update-policy/critical-bundle.conf` is the
validated series (for example `0.56`): patch releases of it arrive with the
normal upgrade. If Arch ships a newer series, or the available version cannot
be established, **the entire official upgrade stops**. It does not hold the
compositor and advance its libraries. Other custom `IgnorePkg`/`IgnoreGroup`
holds also block the upgrade until the user resolves them. A failed refresh
or upgrade marks the update incomplete, and a changed
compositor, kernel or graphics driver triggers the reboot reminder.

The old Hyprland-pin, force-catch-up and QEMU-removal migrations no longer
start independent upgrades. They acknowledge a completed managed base upgrade,
or defer standalone. QEMU replacement conflicts are accepted inside the full
upgrade rather than removing QEMU and trying to restore it later. The EWW fork
similarly replaces vanilla EWW in one package transaction, never a separate
uninstall followed by an install.

The critical bundle only re-asserts baseline packages (`linux-lts`,
`kernel-modules-hook`, and the NVIDIA open driver where it is installed under
that exact name) once per `BUNDLE_ID`, and only after that run's system
upgrade succeeded.

### When a new Hyprland/EWW version drops

1. Check the release notes for breaking config changes
2. If breaking: write a migration (section 5)
3. Commit the migration + any updated default configs
4. Raise `HYPRLAND_SERIES` once the new series works with smplOS
   (`tests/test_critical_bundle.py` covers the update rules)
5. Push to `main`

Users get: refreshed updater → complete base upgrade → required AUR dependencies
→ core native/config/migration delivery → core verification → optional apps
→ final verification → reboot reminder.

### Important: manual `pacman -Syu`

A plain `pacman -Syu` also upgrades to an unvalidated Hyprland series, before
migrations have run. Use `smplos-update --mode full` for normal OS updates.

### Hyprland config format note

smplOS ships parallel Lua and Hyprlang compositor trees. The running provider,
chosen at session startup, determines the accepted runtime dispatcher syntax.
Keep OS-owned modules/rules current in both trees; do not freeze all configs
to preserve one user-owned setting. Validate breaking compositor changes with
the supported Hyprland version and inspect `hyprctl configerrors` after reload.
Keep daemon-specific files such as `hypridle.conf` out of the compositor's
source/include tree. See `src/compositors/hyprland/hypr/README.md`.

---

## 8. Full Update Flow (What Users See)

When a user clicks "Update OS" in app-center or runs `smplos-update --mode full`:

```
══════════════════════════════════════
  smplOS Full System Update
══════════════════════════════════════

  Power check: OK
  [one sudo authentication; updater bootstrap and inventory]

── Pacman ──
  [complete official upgrade]

── Migrations ──
  ── Migration 20260316-120000-hyprland-blur-rename ──
    Updated decoration:blur -> decoration:blur:enabled
  Ran 1 migration(s).

── Post-deploy ──
  Reapplying theme (catppuccin)...
  [bar-ctl ensure: recover/verify the bar and apply saved preferences]
  Reloading Hyprland config...

── smplOS Apps ──
  ✓ smpl-apps: updated to v0.2.0
  ✓ st-smpl: up to date (v1.0.9)
  ✓ nemo-smpl: up to date (v1.4.2)

── AUR ──
  [Yay output]

── Flatpak ──
  [flatpak output]

  [installed files, package versions, native receipts and shared libraries]
  Critical apps, update tools and runtime libraries (before -> installed; repository target; status):
  glibc: 2.41-1 -> 2.42-1; target=2.42-1; current
  pacman: 7.0.0-1 -> 7.0.0-1; target=7.0.0-1; current
  [all installed package comparisons are retained in JSON]
  Native smpl-apps: v0.1.9 -> v0.2.0; target=v0.2.0; updated
  Verification report: ~/.local/state/smplos/update/update-....log.after.json
  ✓ smplOS version: 0.6.48 -> 0.6.49

══════════════════════════════════════
  Update complete!
  Reboot recommended to apply kernel/driver changes.
══════════════════════════════════════
```

Required failures produce **Update incomplete**, a nonzero exit status, and a terminal
that waits for Enter rather than closing over the error. A failed base upgrade
skips desktop/native/AUR deployment; independent deployment failures still
attempt desktop reconciliation and final verification. Updated native windows
are not killed: reopen them when work is saved, and log out/in for changed
background daemons.

Optional failures produce **Update complete with warnings** and overall exit
status `0`, after both core checks succeed. The OS version is finalized while
failed ordinary app work remains pending for retry. Optional work cannot start
when required delivery or its checkpoint failed. The final check still catches
core damage caused by an optional package operation; a historical checkpoint
alone never certifies the final state.

### One administrator authentication

The supported entrypoint is `smplos-update` as the desktop user, without
`sudo` or `pkexec` around the whole command. It authenticates once with
`sudo -v`, refreshes that credential during the update, and stops refreshing
before the terminal waits or closes. It never stores the password or creates
a passwordless sudoers rule.

Subsequent elevation uses `sudo -n`; Yay also receives explicit noninteractive
sudo flags instead of starting its own credential loop. User Flatpak apps and
runtimes update as the user; system Flatpaks update through the same cached sudo
authorization, not a separate Polkit password dialog. If authorization expires
or is revoked, the affected operation fails visibly rather than asking for the
password again mid-update. Required work and final privileged verification
remain blocking; an optional operation never silently reauthenticates.

### Local diagnostics and retry

`~/.local/state/smplos/update/` contains each update's transcript,
`*.before.json`, `*.aur.json` (foreign-package priority inventory),
`*.apps.json` (core native outcomes), `*.core.json` (core checkpoint),
`*.brave.json`, `*.after.json`, and an
atomically published `status` file.
The status records the stage and complete/complete-with-warnings/failed/interrupted
state, `core_verified`, and the count of coordinator `optional_phase_warnings`.
That count is not the final audit's `optional_failures` array. A
power cut cannot execute a trap: a leftover `running` stage is also reported
as a previous interrupted update on the next run. Bootstrap failures remain
in the transcript; the stage journal begins after bootstrap.

The final report covers the whole upgrade, not just the bar:

- **Every installed pacman package**, including libraries: before/installed
  versions, configured repository target and `current`, `pending`,
  `newer-local`, `not-in-repositories` or `unknown` status. The first configured
  repository wins; a newer package in a lower-priority repository is not the
  target. An unchanged version can legitimately mean already current. A
  pending package or failed repository comparison makes verification fail.
- **Stability and update-critical packages:** kernels, firmware, GPU/compositor
  libraries, systemd/login, authentication, networking, Pacman/Yay, Python,
  Git/Curl, GTK/Qt/WebKit and audio. The audit also discovers package owners
  of the actual shared libraries resolved by the core apps/update tools,
  checks those packages' file presence and records their installed versions.
- **Native releases:** smpl-apps (all 11 required binaries and delivered XR
  binaries), st, micro and Nemo get per-component before/after/target
  results. Failed API checks or downloads cannot masquerade as current just
  because an old marker still exists. Same-version repairs are `updated`.
  Native checksums, executability and runtime library resolution are verified;
  the installed version must independently satisfy this run's release target.
- **Brave:** Update OS captures the stable `brave-bin` AUR target before the
  optional AUR transaction in `*.brave.json`. The final check requires the installed
  package to be **equal to or newer than that recorded target**, using Arch's
  version comparison including package release numbers. An older/missing
  package, failed target lookup or unreadable record produces an optional
  failure, not a core update failure. Its package-owned browser ELF, shared libraries and actual
  `--version` output are also checked against the installed package version,
  so a new package record with an old browser binary does not pass.
- **Managed files:** scripts, shared helpers, desktop fragments, stock themes
  and matching personal theme overrides, and installed-compositor configuration
  are compared with fetched source. Obsolete managed theme entries fail verification.
  Active theme identity/cache and generated EWW palette, Nemo CSS, Hyprland
  theme/lock colors, micro colors and the managed session target are also
  compared with their deployed targets. Core theming runs with `theme-set --core`;
  `theme-set --apps` applies editor/browser integrations later, under the same
  theme lock, without replacing the active theme or core outputs.
  Package database/dependency consistency and remaining repo upgrades are
  checked separately.

Native reports are written after each required component, including failures.
Old optional native reports cannot overwrite core outcomes. The final JSON includes
`package_status`, `package_changes`, `app_version_changes`,
`runtime_library_packages`, `native_updates`, `native_files`, `linkage`,
`errors`, `warnings` and actionable `optional_failures` (schema 3).
Required phase errors are forwarded into the final report too.
The terminal/transcript ends with the critical-package
and native-component comparison. The `status` file is the overall orchestrator
result; the final JSON describes installed-state verification, not proof that
every preceding phase succeeded.

Full updates also compare stock boot kernel images with installed
module trees, inspect initramfs contents for that kernel version, and verify
NVIDIA modules for installed kernels, including DKMS. A running old kernel
alone is not proof of a failed update.
Critical `pacman -Qk` checks, boot metadata/digests and initramfs reads use cached
`sudo -n` authorization. A private `/boot` remains private; neither its mode
nor the audit's desktop-user/report ownership changes. Lost authorization and
read errors are reported explicitly, never interpreted as missing boot files.
Both installed Linux Surface and stock kernel layouts are checked.
Retained trees from `kernel-modules-hook` are excluded using the installed
kernel package's file list. NVIDIA module version and kernel vermagic must
match the installed driver/kernel, not merely be present on disk.

These are installed-state checks, **not a boot test**. Kernel checks target
smplOS's stock `/boot/vmlinuz-*` / `initramfs-*.img` layout, not arbitrary UKIs
or custom boot layouts. Missing images/modules are an incomplete update:
repair the reported problem **before rebooting**. No graphical session means
live bar/Hyprland checks are explicitly deferred. User-owned monitor, idle,
and binding preferences are not compared to stock defaults; generated theme
outputs are checked against the selected active theme, not a stock selection.

Repository comparisons use local Pacman databases refreshed by the upgrade;
the verifier itself makes no network calls. Packages outside those databases
are explicitly identified as AUR/local, not certified as latest by that
comparison. The managed native releases have their separate captured targets;
other AUR and Flatpak failures remain visible in the transcript, final optional
failures and overall warning status. No diagnostic data is uploaded.

To rerun diagnostics after repairing a full update (no network/package changes):

```bash
sudo -v
smplos-update-check --mode full \
  --output "$HOME/.local/state/smplos/update/manual-check.json"
```

To include the release targets/outcomes of a particular update, add
`--apps-report /path/to/that-update.log.apps.json`. A standalone check without
that argument verifies installed native files/receipts, not today's online
release versions. The legacy `--optional-apps-report` option is accepted but
explicitly ignored; it cannot reintroduce Grafium checks or overwrite core results.
The standalone verifier returns `1` for required errors, `2` for optional-only
failures, and `0` otherwise. The coordinator recognizes `2` as warning-only;
do not treat it as a successful all-apps audit. `--core-only` skips optional apps
for the intermediate checkpoint.

For Brave, also add `--brave-report /path/to/that-update.log.brave.json`.
`brave` and `brave_runtime` in the final JSON record the target comparison and
actual browser version. The browser and its profiles are not closed, reset or
replaced by diagnostics; restart Brave yourself to use an updated binary in
already-open windows. Apps-only mode does not upgrade AUR host packages:
use Update OS for Brave.

### AUR helper: prebuilt Yay, not Paru rebuilds

Update OS uses Yay and removes the old Paru rebuild hook **before** the base
transaction. After validating the supported base version, old Paru packages
are removed before upgrading pacman/libalpm: otherwise their old, exact
libalpm dependency can block the base transaction itself. Removal is
nonrecursive; unrelated dependencies and both helpers' user configuration and
caches are preserved. A removal failure stops the base upgrade.

After the base upgrade, `smplos-ensure-yay` installs/repairs the helper and
verifies both `--version` and a real `-Q pacman` database query. If a later
required step fails, the update is incomplete and must be retried; Paru is not
restored or rebuilt as a fallback. Ordinary AUR app failures are optional.

`smplos-update-check --classify-aur --output PATH` classifies the local installed
inventory without network access. Core stack roots, public shared libraries,
kernel modules/DKMS sources and their transitive package/provider dependencies
are required; ordinary foreign apps are optional. Private browser/editor
libraries and debug source trees do not make those apps core. Independently
managed Nemo/EWW releases are excluded from Yay transactions. Grafium is
separately recorded under `app_updates_only` and excluded from both OS AUR groups.
Incomplete
or unresolved dependency metadata fails classification explicitly, never
silently treating unknown packages as optional. Core and optional Yay invocations
exclude the opposite group; `critical-packages.txt` remains the existing
compositor hold policy, not a severity manifest.

If a configured package repository supplies `yay`, enrollment uses pacman to
install it. Stock Arch's official repositories do not supply Yay, so smplOS
also ships a pinned `yay-bin` recipe. It downloads the upstream precompiled
13.0.1 release, validates its SHA256, and packages it for `pacman -U`.
There is **no Go or Rust compilation** on the target machine; the local
`makepkg` step only assembles the binary package. Existing usable, sufficiently
new `yay-bin` installations are reused, and repairs never downgrade a newer
installed binary package to an older pinned release.

Fresh ISOs package that same recipe into their offline mirror, so installation
still needs no internet. Legacy `rebuild-paru` is an explicit no-op in case an
old hook invokes it during enrollment; `heal-paru` reports that it is retired
instead of rebuilding anything. Neither command is an alias for Yay.

Yay still needs usable pacman/libalpm APIs; changing helpers is not a guarantee
against every future ABI change. Failed binary/runtime checks stop AUR work
and remain in the overall update status. The AUR transaction disables Yay's
own sudo loop (`--sudoloop=false`) and uses the update's cached, noninteractive
sudo context. Native App Center/Settings must also be delivered from
**smpl-apps v0.8.29** or newer, with their Yay callers, before the migration
is considered complete. That coordinated release includes the pinned keypad
package above.

### Bringing older fleet machines onto this updater

The customer-facing procedure is **App Center → Update OS**, including on
supported older Git-based installations. No separate enrollment command is
required once this implementation is published on upstream `main`.

Start with one bootable test machine and a verified backup of its important
user data. Connect AC, click **Update OS**, and confirm the update.

Legacy App Center versions already start `smplos-update --mode full`. Their
installed Git updater fetches fresh source and reaches a refreshed helper,
native fetcher or migration runner. Those entry points recognize the actual
historical generated Bash runner by its loaded script, ownership, complete
SHA256 and process start time. A detached supervisor stops that runner and its
intervening helper processes, then automatically reopens the current updater
as the desktop user. It does not kill applications by name or stop the desktop.
The new coordinator verifies the old processes are gone before power checks,
authentication or package transactions. Failed replacement acquisition or
terminal launch does not resume the stopped legacy package sequence.

The old terminal may close and a new one appear. A Polkit-based old updater
has already authenticated before fetching new code, so this first migration
requires **one additional sudo prompt**. Later updates authenticate once.
Passwords are neither stored nor forwarded, and no passwordless grant is
installed. Handoff diagnostics are retained in the desktop-user-owned
`/tmp/smplos-handoff-*.log` file identified in the terminal or failure notification.

The privileged bridge retains the log's original descriptor after assigning it
to the desktop user. It never reopens that `/tmp` file for creation as root:
Linux's `fs.protected_regular` correctly rejects that pattern. The safeguard
remains enabled. Root-to-user behavior is checked separately in CI with real
privilege separation, not only command stubs.

Before dropping privileges, the bridge restores root-owned updater state
directories and the fixed set of version/lock markers left by old root runners.
It records ownership changes, preserves file contents and historical logs, and
does not recursively chown the home directory. Symlinks, hardlinked markers and
unexpected owners are rejected rather than followed or guessed.

The ordinary coordinator performs the same bounded repair after verifying and
refreshing its scripts, before any package transaction. A retry that already
installed the v0.8.118 coordinator therefore does not need another legacy
handoff or a support script to repair version markers. The new coordinator
also repairs unwritable state directories/locks before trying to acquire its
lock, after checking external power and authenticating. Both paths reuse the
same sudo context; the lock inode and old logs are preserved.

This bridge covers the shipped Git-based runner families, including the early
Git updater and versions with broken helper self-reexecution. It cannot change
old local actions performed **before** fresh code is fetched. Offline fetch
failures, locally modified/unrecognized runners, and pre-Git images without a
reachable fresh-script checkpoint are not retroactively protected by publishing
source. Do not certify those images as first-click safe. A machine that no
longer boots requires local recovery; no fleet machine is contacted automatically.

In particular, the already-published v0.8.118 launcher opens its local state lock
before authentication or fetching. If that directory or lock is unwritable on
a machine that already installed that launcher, it cannot acquire this repair
from a source publication. A retry from v0.8.118 is covered only when it can
reach its existing fetch checkpoint. Do not call this a universally remote
repair or ask customers to retry without establishing which path they reach.

The replacement bootstrap checks the origin and clean `main` checkout, refuses
unfinished Git operations and only fast-forwards. It preserves local changes
and divergent commits by stopping rather than resetting them. Every subsequent
Update OS repeats the complete script/helper verification gate before package
work. A missing, stale or nonexecutable managed command stops the update.

After a full update, retain its transcript, `*.before.json`, `*.after.json`,
`*.apps.json`, `*.brave.json`, `*.bootstrap.json` and `status` under
`~/.local/state/smplos/update/`. Repair reported kernel/initramfs errors before
rebooting. This is not transactional rollback or a guarantee against interruption
during package writes.

#### Optional scripts-only support enrollment

Support can refresh only the updater commands without starting an OS update.
This is **not required before the normal Update OS button**. From the desktop
user's terminal, without sudo, download the published support script locally:

```bash
(
  set -euo pipefail
  enrollment=$(mktemp /tmp/smplos-enroll.XXXXXX)
  trap 'rm -f -- "$enrollment"' EXIT
  curl --fail --location --proto '=https' --tlsv1.2 \
    https://raw.githubusercontent.com/smpl-os/smplos/main/src/shared/bin/smplos-update-bootstrap \
    --output "$enrollment"
  bash "$enrollment"
)
```

This support enrollment takes the normal update lock, checks the origin and clean `main`
checkout, refuses unfinished Git operations, and only fast-forwards. It never
runs the installed legacy wrapper/helper. A missing checkout is cloned from
upstream. The new repository wrapper then checks external power, authenticates
once, installs scripts/helpers and verifies their bytes and command permissions
against the fetched source. `--bootstrap-only` is preserved through terminal
launch and self-reexecution.

Enrollment does **not** upgrade packages, install native GUI binaries, deploy
desktop configuration, run migrations or change the recorded OS version. It
does refresh the user app index. Its local transcript and
`*.bootstrap.json` report live under `~/.local/state/smplos/update/`; the JSON
records the exact source commit and any managed-file failures. Bootstrap
verification does not require the old machine's native apps to already work.
It runs before the base upgrade and does not require Python 3.11-only hashing.

After **"Updater enrollment verified"**, the support operation is complete.
Use App Center's normal Update OS button when ready for the full update.
If inspection, fast-forward or verification fails, preserve and resolve the
reported problem rather than bypassing the gate.

---

## 9. Testing Updates Locally

### Without an ISO build

```bash
# Simulate the repo structure
export SMPLOS_PATH="$HOME/.local/share/smplos"
ln -sf /path/to/your/smplos-checkout "$SMPLOS_PATH/repo"

# Test script sync (dry run — just see what would change)
diff /usr/local/bin/smplos-update src/shared/bin/smplos-update

# Test migrations
smplos-migrate --dry-run
smplos-migrate --list

# Test app update check (no downloads)
smplos-update-apps --check

# Test config refresh
smplos-refresh-config hypr/hyprlock.conf
```

### With a VM (via dev-push)

```bash
# On host — push scripts to VM shared folder
cd release && ./dev-push.sh bin

# In VM — deploy to /usr/local/bin/
sudo bash /mnt/dev-apply.sh

# Test the full update
smplos-update --mode full
```

### With a full ISO build

```bash
./src/build-iso.sh
# Boot the ISO in QEMU, install, then run smplos-update
```

---

## 10. Checklist for Contributors

Before pushing an update:

- [ ] Does the change need a migration? (Breaking config change → yes)
- [ ] Is the migration idempotent? (Run it twice — same result?)
- [ ] Does the migration skip gracefully on fresh installs?
- [ ] Did you bump `src/VERSION`? (For any user-visible change)
- [ ] Are new scripts in `src/shared/bin/` executable? (`chmod +x`)
- [ ] For forked app updates: is the GitHub release published with correct asset names?

---

## 11. For AI Assistants (Copilot, etc.)

When the user asks you to prepare an update:

1. **Identify what changed** — scripts, configs, themes, app code?
2. **Determine if a migration is needed** — does the change break existing user configs?
3. **Make the changes** in the appropriate locations (see "What Goes Where" table)
4. **Write a migration** if needed (timestamped shell script in `migrations/`)
5. **Bump `src/VERSION`** if it's a user-visible change
6. **Commit** with a descriptive message following conventional commits (`feat:`, `fix:`, `refactor:`)

### Example: Hyprland config keyword rename

```
User: "Hyprland 0.47 renamed `general:gaps_in` to `general:gaps_inner`"
```

You would:
1. Update `src/compositors/hyprland/hypr/hyprland.conf` (default config)
2. Create `migrations/20260316-150000-hyprland-gaps-rename.sh`:
   ```bash
   #!/bin/bash
   set -euo pipefail
   conf="$HOME/.config/hypr/hyprland.conf"
   [[ -f "$conf" ]] && grep -q 'gaps_in' "$conf" || exit 0
   sed -i 's/gaps_in/gaps_inner/g' "$conf"
   echo "  Renamed gaps_in -> gaps_inner in hyprland.conf"
   ```
3. `chmod +x` the migration
4. Bump `src/VERSION`
5. Commit: `fix: migrate Hyprland 0.47 gaps_in -> gaps_inner`

### Example: New script

```
User: "Add a script that toggles night mode"
```

You would:
1. Create `src/shared/bin/night-mode-toggle` with the script
2. `chmod +x` the script
3. Bump `src/VERSION`
4. Commit: `feat: add night-mode-toggle script`

No migration needed — scripts are synced automatically.

### Example: New smpl-apps feature

```
User: "Add a battery widget to the settings app"
```

You would:
1. Make the code changes in the `smpl-os/smpl-apps` repo
2. Bump the version in `Cargo.toml`
3. Push and let CI build + create a GitHub release
4. Users get it on next `smplos-update-apps`

No changes needed in this repo unless the feature needs new configs or scripts.
