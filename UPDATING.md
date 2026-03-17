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
6. Updates system packages (Hyprland/EWW held back until after migrations)
7. Updates forked apps from GitHub releases
8. Updates AUR + Flatpak packages

**All you need to do is commit to `main`.** Users get your changes on
their next update.

---

## Quick Reference: What Goes Where

| What you changed | Where it lives | How it reaches users |
|---|---|---|
| Script (bin) | `src/shared/bin/` | `smplos-os-update` syncs to `/usr/local/bin/` |
| EWW widget | `src/shared/eww/` | User must run `smplos-refresh-config eww/...` (or migration) |
| Hyprland config | `src/compositors/hyprland/hypr/` | User must run `smplos-refresh-config hypr/...` (or migration) |
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

---

## 2. Updating Configs (EWW, Hyprland, foot, etc.)

Config files are NOT automatically overwritten — users may have customized
them. You have two options:

### Option A: Non-breaking change (additive)
Just commit the change. Users who want the new default can run:
```bash
smplos-refresh-config hypr/hyprlock.conf
```
This backs up their version and copies the new default.

### Option B: Breaking change (must update or things break)
Write a migration. See section 5 below.

---

## 3. Updating Themes

Theme files in `src/shared/themes/` are automatically reapplied after
every update via `theme-set <current-theme>` in the post-deploy hook.

**Steps:**
1. Edit the theme template(s) in `src/shared/themes/<name>/`
2. Test with `theme-set <name>` locally
3. Commit and push

Users get the updated theme automatically on next update.

---

## 4. Bumping the smplOS Version

**Steps:**
1. Edit `src/VERSION` — increment the version number
2. Commit and push

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

---

## 6. Updating Forked Apps (smpl-apps, st-smpl, nemo-smpl)

These apps live in separate repos and are distributed as GitHub releases.
`smplos-update-apps` downloads them automatically.

### Publishing a new release

**smpl-apps** (Rust workspace — start-menu, notif-center, app-center, etc.):
1. Build: `cargo build --release` in the smpl-apps repo
2. Create a tarball: `tar -czf smpl-apps-v0.2.0-x86_64.tar.gz -C target/release start-menu notif-center settings app-center webapp-center sync-center-daemon sync-center-gui`
3. Create a GitHub release with tag `v0.2.0`
4. Attach the tarball as a release asset

**st-smpl** (C — terminal emulator):
1. Build: `make` in the st-smpl repo
2. Create a GitHub release with tag `v1.1.0`
3. Attach the binary (named to contain `st` and `x86_64`)

**nemo-smpl** (C — file manager):
1. Build the Arch package: `makepkg -s`
2. Create a GitHub release with tag `v1.5.0`
3. Attach the `.pkg.tar.zst` file (named `nemo-smpl-*x86_64.pkg.tar.zst`)

**Note:** Each repo has CI workflows that automate the build + release.
Just push a tag and the workflow creates the release with assets.

### Checking app update status

```bash
smplos-update-apps --check    # report available updates (no download)
smplos-update-apps            # download and install updates
```

Version state is in `~/.local/state/smplos/app-versions/`.

---

## 7. Pinned Packages (Hyprland, EWW)

Hyprland and EWW are held back by `IgnorePkg` in `/etc/pacman.conf`.
This means `pacman -Syu` won't update them. They're updated explicitly
by `smplos-update` in step 3, AFTER migrations have run.

### Why?

Hyprland and EWW frequently ship breaking config changes. Without
`IgnorePkg`, a user running `pacman -Syu` could update Hyprland before
a migration has fixed their config — resulting in a broken desktop.

### When a new Hyprland/EWW version drops

1. Check the release notes for breaking config changes
2. If breaking: write a migration (section 5)
3. Commit the migration + any updated default configs
4. Push to `main`

Users will get: migration runs → config fixed → Hyprland/EWW updates.

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

── Pinned packages (Hyprland, EWW) ──
  [updates hyprland and eww]

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
