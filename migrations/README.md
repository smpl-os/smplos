# smplOS Migrations

Migrations are timestamped shell scripts that run **exactly once** per user.
They handle breaking changes from upstream packages (Hyprland, EWW, etc.)
and smplOS config format changes.

## Naming Convention

```
YYYYMMDD-HHMMSS-description.sh
```

The timestamp prefix ensures migrations run in chronological order.
Use the date/time of the commit, not the event.

## Writing a Migration

```bash
#!/bin/bash
# Migration: Brief description of what this fixes
# Context: Why this migration exists (upstream change, config rename, etc.)

set -euo pipefail

# Check if migration is needed (idempotent guard)
if [[ ! -f "$HOME/.config/hypr/hyprland.conf" ]]; then
    echo "  Hyprland config not found, skipping"
    exit 0
fi

# Do the actual migration work
sed -i 's/old_setting/new_setting/' "$HOME/.config/hypr/hyprland.conf"

echo "  Updated hyprland.conf: old_setting -> new_setting"
```

## Rules

1. **Always be idempotent.** Check if the change is needed before applying.
2. **Never delete user data.** Rename or back up instead.
3. **Keep it focused.** One migration per breaking change.
4. **Exit 0 on success**, non-zero on failure.
5. **Print what you did** so the user sees it in the update log.
6. **Test both paths** — fresh install (migration not needed) and upgrade
   (migration needed).

## How It Works

`smplos-migrate` runs all pending migrations in order. State is tracked in
`~/.local/state/smplos/migrations/` — an empty file per completed migration.
Skipped migrations go in `~/.local/state/smplos/migrations/skipped/`.

Migrations are triggered by `smplos-os-update` after `git pull`, before
the pinned packages (Hyprland, EWW) are updated by `smplos-update`.
