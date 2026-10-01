# smplOS Update System

How to prepare and ship updates for smplOS. Written for both human
contributors and AI assistants (Copilot, etc.).

## Architecture Overview

smplOS uses a **git-based update system**. The repo is cloned to
`~/.local/share/smplos/repo/` on each user's machine. When they run
"Update OS" (from app-center or `smplos-update --mode full`), the system:

1. `git pull` the latest repo
2. Syncs scripts from `src/shared/bin/` to `/usr/local/bin/`
3. Runs pending migrations from `migrations/`
4. Bumps `/etc/os-release` from `src/VERSION`
5. Reapplies the current theme + reloads Hyprland
6. Updates system packages in one transaction (temporarily unpins Hyprland/EWW after migrations)
7. Updates forked apps from GitHub releases
8. Updates AUR + Flatpak packages

OS-owned changes reach users after merging to `main` and running the updater.
Changes to independently built apps also require a release in their own repo.

---

## Quick Reference: What Goes Where

| What you changed | Where it lives | How it reaches users |
|---|---|---|
| Script (bin) | `src/shared/bin/` | `smplos-os-update` syncs to `/usr/local/bin/` |
| EWW widget | `src/shared/eww/` | OS-owned entry point, overview, styles and scripts sync automatically |
| Hyprland config | `src/compositors/hyprland/hypr/` | OS-owned `.conf`/`.lua` files sync automatically; user-owned exceptions below |
| Theme | `src/shared/themes/` | `post_deploy()` reapplies current theme automatically |
| Keybindings | `src/shared/configs/smplos/bindings.conf` | Needs migration if format changed |
| smpl-apps (Rust) | `smpl-os/smpl-apps` repo | `smplos-update-apps` downloads from GitHub releases |
| st-smpl | `smpl-os/st-smpl` repo | `smplos-update-apps` downloads from GitHub releases |
| nemo-smpl | `smpl-os/nemo-smpl` repo | `smplos-update-apps` downloads from GitHub releases |
| Breaking change | `migrations/` | `smplos-migrate` runs it exactly once per user |
| OS version | `src/VERSION` | `sync_version()` updates `/etc/os-release` |

---

## 1. Updating Scripts

Scripts in `src/shared/bin/` are automatically deployed to `/usr/local/bin/`
on every update. No migration needed.

**Steps:**
1. Edit the script in `src/shared/bin/`
2. Test it locally
3. Commit and push to `main`

**That's it.** On next `smplos-update --mode full`, the script syncs.

For example, Super+K search behavior lives in `src/shared/bin/keybind-help`, not
in the user's Rofi configuration. Script updates replace `/usr/local/bin/keybind-help`;
the next invocation rebuilds its per-user cached list when the script is newer.
No config refresh, migration, logout, or ISO rebuild is needed once the change
reaches `main`.

The workspace-local Nemo shortcut also changes `bindings.conf`, which is
user-managed and normally preserved during updates. Migration
`20260929-143800-nemo-current-workspace.sh` backs up and changes only the stock
Super+Shift+F command in existing Hyprland/shared bindings and niri configs;
custom commands and other shortcuts remain untouched. New ISO builds ship the
updated binding and both launcher scripts through the existing shared-file copy.

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

### Option A: Non-breaking change (additive)
For an OS-owned config, commit the change and normal updates deliver it.
For a user-owned config, users who explicitly want the new defaults can run:
```bash
smplos-refresh-config hypr/hyprlock.conf
```
This backs up their version and copies the new default.

### Option B: Breaking change (must update or things break)
Write a migration. See section 5 below.

### Power preferences and command compatibility

Settings and the user own `~/.config/hypr/hypridle.conf`: updates retain exact
seconds, Never/disabled listeners, custom commands, source includes and comments.
This is **hypridle's grammar**, not a Hyprland compositor config: never source it
from `hyprland.conf` or `hyprland.lua`. A Hyprland reload does not reload hypridle.
Previously overwritten choices cannot be recovered reliably; users must
reselect those choices rather than have the updater guess them.

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

---

## 3. Updating Themes

Theme files in `src/shared/themes/` are automatically reapplied after
every update via `theme-set <current-theme>` in the post-deploy hook.
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

### Background-only transparency delivery

This feature crosses independently released binaries. OS source alone is
**not** delivery of native alpha support. Keep normal apps at compositor
opacity 1.0: lowering whole-window opacity fades text and images too.

1. Ship the OS palette/template/CSS and both Hyprland rule trees together.
   `app_background_opacity` is explicit in all 17 stock palettes; it generates
   `$theme-app-background-opacity` for native readers. `sync_themes()` copies
   stock data, preserves user overrides, and `post_deploy()` reapplies the active
   theme as the desktop user. No one-time migration is required.
2. Publish compatible **nemo-smpl** and **smpl-apps** binary releases from their
   own repositories. Nemo CSS gates root alpha and transparent descendants with
   `.smplos-native-alpha`, so an older Nemo remains opaque. Old smpl-apps keeps
   its legacy popup behavior; a new regular-role reader falls back to explicit
   popup alpha for old generated custom palettes, then safe opaque 1.0.
3. Release/package the compatible **Grafium** Linux build separately.
   `grafium-bin` extracts the upstream `.deb`; updating OS theme files or a
   repository submodule cannot update its native Tauri/WebKit window.
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

**ISO boundary:** the builder copies pre-generated theme files and OS scripts
into the live image, user skeleton and installer payload. It seeds the default
Nemo CSS path and EWW palette before the first theme switch. Native app builds
consume published binary bundles by default; `--build-apps` builds the pinned app source.
Only update the smpl-apps submodule pointer after its commit is reachable in
the app repository. Confirm cached/prebuilt Nemo, smpl-apps and Grafium packages
actually contain the compatible binaries before advertising native alpha on an
ISO. Installation itself remains offline. Do not point at an unpublished local
commit or claim a release version that has not been published.

**Scope/limitations:** regular native backgrounds use the new key; popup apps,
EWW/Rofi and terminals retain their existing controls. Matrix, Amber and
Grafium themes remain intentionally opaque. Nemo desktop, separate menus and
dialogs remain opaque; selections and media retain their own paint. Foreign
GTK/Qt/Electron apps and existing messenger/browser whole-window policies are
not converted. Alpha can work cross-compositor, but blur depends on compositor
support. See the [ownership/audit table](CREATING_MODIFYING_A_THEME.md#stock-palette-audit).

Before coordinated publication, run:

```bash
bash src/regen-all-themes.sh --check
python3 -m unittest discover -s tests -p 'test_theme*.py' -v
```

On a test desktop with compatible binaries, check Catppuccin, Latte, Ethereal,
Matrix and a custom theme across icon/list/split views, previews and dialogs;
focused/unfocused text must remain opaque. Verify old Nemo without the
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

### Checking migration status

```bash
smplos-migrate --list       # show all migrations and their status
smplos-migrate --pending    # show only pending migrations
smplos-migrate --dry-run    # show what would run without executing
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

**Grafium packaging is a separate boundary.** `grafium-bin` is bundled through
`src/shared/packages-aur.txt` and `src/shared/pkgbuilds/grafium-bin/PKGBUILD`.
The PKGBUILD extracts the upstream `Grafium_<VERSION>_amd64.deb` unchanged;
smplOS does not synthesize its application icon. Correct user icon precedence
does not fix a blue image already contained in that package on a machine with
no good override. A corrected, accessible stable Grafium `.deb` release is
still required. The release API returned no Grafium releases when this fix was
prepared; do not package a developer's personal icon as a substitute.

Focused, offline regression coverage (temporary homes and mocked downloads;
no real updates, installs, or ISO builds):

```bash
python3 -m unittest discover -s tests -p 'test_app_*.py' -v
```

---

## 7. Hyprland/EWW Update Strategy

Many users pin Hyprland/EWW in `IgnorePkg` inside `/etc/pacman.conf`.
`smplos-update` handles this safely by:

1. Running migrations first (`smplos-os-update`)
2. Temporarily removing `hyprland`/`eww` from `IgnorePkg`
3. Running a single `pacman -Syu` transaction
4. Restoring the original `/etc/pacman.conf`

### Why?

Hyprland and EWW frequently ship breaking config changes. Without
`IgnorePkg`, a user running `pacman -Syu` could update Hyprland before
a migration has fixed their config — resulting in a broken desktop.

### When a new Hyprland/EWW version drops

1. Check the release notes for breaking config changes
2. If breaking: write a migration (section 5)
3. Commit the migration + any updated default configs
4. Push to `main`

Users will get: migration runs → config fixed → full pacman transaction.

### Important: manual `pacman -Syu`

If you run `pacman -Syu` manually while Hyprland is pinned, you can hit
dependency conflicts (`aquamarine`/`hyprutils` ABI bumps). Use
`smplos-update --mode full` for normal OS updates.

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

── smplOS System Files ──
  Checking for updates...
  ✓ 3 files changed, 42 insertions(+), 12 deletions(-)

── Syncing scripts ──
  ✓ 2 of 47 scripts updated

── Migrations ──
  ── Migration 20260316-120000-hyprland-blur-rename ──
    Updated decoration:blur -> decoration:blur:enabled
  Ran 1 migration(s).

── Post-deploy ──
  ✓ smplOS version: 0.6.48 -> 0.6.49
  Reapplying theme (catppuccin)...
  Reloading Hyprland config...

── Pacman ──
  [standard pacman output]

── smplOS Apps ──
  ✓ smpl-apps: updated to v0.2.0
  ✓ st-smpl: up to date (v1.0.9)
  ✓ nemo-smpl: up to date (v1.4.2)

── AUR ──
  [paru output]

── Flatpak ──
  [flatpak output]

══════════════════════════════════════
  Update complete!
  Reboot recommended to apply kernel/driver changes.
══════════════════════════════════════
```

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
