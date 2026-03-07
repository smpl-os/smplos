# sync-center - Event-Driven Directory Synchronization

**sync-center** is a lightweight, automatic backup tool for smplOS that syncs your important directories to external drives when they're connected.

## Features

- 🔌 **Automatic Detection** - Detects when USB drives are plugged in
- 📁 **Profile-Based** - Create sync profiles for different drives
- 🚀 **Simple** - No complex configuration, just point and go
- 🔔 **Notifications** - Get notified when syncs complete
- 🎨 **Integration** - Appears in Start Menu and system tray with Eww
- ⚡ **Fast** - Uses rsync for efficient syncing

## Quick Start

1. Open **Sync Center** from the Start Menu
2. Click **+ New Profile**
3. Name your profile (e.g., "My Backup Drive")
4. Set drive identifier (Label: `BACKUP`, or marker file: `.sync-backup`)
5. Add directories to sync (e.g., `~/Pictures`, `~/Documents/Logseq`)
6. Save and plug in your drive!

## How It Works

```
[Plug in USB] 
    ↓
[sync-center detects mount]
    ↓
[Matches against your profiles]
    ↓
[Runs rsync automatically]
    ↓
[Shows notification when done]
```

## Configuration

Profiles are stored in `~/.config/sync-center/config.json`

Example profile:
```json
{
  "name": "My Backup Drive",
  "identifier": {"type": "label", "value": "BACKUP"},
  "syncs": [
    {"source": "~/Pictures", "destination": "Pictures/"},
    {"source": "~/Documents/Logseq", "destination": "Logseq/"}
  ]
}
```

## Project Structure

See [spec.md](spec.md) for complete specification including:
- Architecture overview
- D-Bus interface
- UI mockups
- Integration points (Start Menu, Eww, Nemo)
- Implementation phases
- D-Bus interface specification

## Development

**Building:**
```bash
cargo build --release
```

**Running daemon:**
```bash
./target/release/sync-center-daemon
```

**Running GUI:**
```bash
./target/release/sync-center-gui
```

## Status

- **Phase 1 (Core)**: In progress
  - [x] Project structure
  - [x] Configuration system
  - [ ] Volume monitoring
  - [ ] rsync execution
  - [ ] D-Bus interface
  - [ ] Basic GUI

- **Phase 2 (Integration)**: Planned
  - [ ] Eww system tray
  - [ ] Start Menu entry
  - [ ] Sync history
  - [ ] Dry-run mode

- **Phase 3 (Advanced)**: Future
  - [ ] Nemo extension
  - [ ] Scheduled syncs
  - [ ] Bidirectional sync
  - [ ] Network shares

## Dependencies

- Rust 1.70+
- gtk4
- libadwaita
- GIO
- libnotify

## License

GPL-3.0-or-later

## Contributing

This is part of the smplOS project. All work done here is for the smplOS distribution.
