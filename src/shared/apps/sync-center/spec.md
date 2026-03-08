# sync-center - Specification

**Status:** Draft v1.0  
**Author:** smplOS Team  
**Date:** March 7, 2026

---

## 1. Overview

`sync-center` is a lightweight, event-driven local directory synchronization tool for smplOS. It automatically detects when external drives (USB, HDD, etc.) are connected and syncs pre-configured directory pairs to those drives based on profiles.

**Problem Statement:** Users want simple, automatic backup of important directories (Photos, Documents, Logseq, etc.) to external drives without complex configuration or continuous background syncing overhead.

**Solution:** A systemd user service + GTK4 GUI that:
- Monitors volume mounts via GIO
- Matches drives by label/UUID/marker file
- Executes configured rsync operations
- Shows progress and notifications
- Integrates into Start Menu, system tray (Eww), and Nemo

---

## 2. Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         sync-center                              │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ sync-center-daemon (Rust binary)                                 │
│  - Runs as systemd user service                                 │
│  - Monitors GVolumeMonitor for mount/unmount events            │
│  - Matches drives against config profiles                       │
│  - Spawns rsync child processes with progress tracking         │
│  - Emits D-Bus signals for status updates                      │
└─────────────────────────────────────────────────────────────────┘
    │                           │                          │
    ├──→ D-Bus Interface       ├──→ Config File          └──→ Notifications
    │    (org.smpl.SyncCenter)  │    (~/.config/          (libnotify)
    │                           │     sync-center/)
    │
┌─────────────────────────────────────────────────────────────────┐
│ sync-center-gui (GTK4 + Libadwaita)                             │
│  - Manages sync profiles                                        │
│  - Shows sync status                                            │
│  - Triggers manual sync                                         │
│  - D-Bus client listening to daemon                             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Eww Integration (System Tray)                                    │
│  - Icon: sync-center app icon                                   │
│  - Indicator: Pulsing/spinning animation when sync active       │
│  - Click: Opens sync-center-gui                                 │
│  - Tooltip: Current sync progress or "Ready"                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Start Menu Integration                                           │
│  - Desktop entry: sync-center.desktop                           │
│  - Category: Utilities                                          │
│  - Icon: syncing/folder icon                                    │
│  - Launch: Opens sync-center-gui                                │
└─────────────────────────────────────────────────────────────────┘
```

### Communication Flow

```
Device Mount Event
    ↓
[GVolumeMonitor] (GIO)
    ↓
[sync-center-daemon] checks volume label/UUID
    ↓
Match found in ~/.config/sync-center/profiles.json?
    ├─ YES → Spawn rsync processes, emit D-Bus signals
    │         ├→ [Eww] receives D-Bus signal, shows pulsing animation
    │         ├→ [sync-center-gui] (if open) shows progress
    │         └→ [libnotify] shows notifications
    │
    └─ NO → Log event, continue monitoring
```

---

## 3. Features

### Phase 1 (MVP)

- [x] Daemon monitors volume mounts
- [x] Profile-based sync configuration
- [x] Drive identification (label, UUID, marker file)
- [x] Rsync-based directory sync
- [x] Desktop notifications (start, complete, error)
- [x] GTK4 GUI for profile management
- [x] D-Bus interface for IPC
- [x] Systemd user service auto-start

### Phase 2 (v1.5)

- [ ] Eww system tray icon with animation
- [ ] Start Menu integration
- [ ] Nemo extension showing sync status
- [ ] Dry-run preview before sync
- [ ] Sync history/log viewer

### Phase 3 (v2.0)

- [ ] Conflict resolution strategies
- [ ] Scheduled syncs (e.g., daily)
- [ ] Bidirectional sync option
- [ ] Exclude patterns UI
- [ ] Compression during sync
- [ ] Network share support (SMB, NFS)

---

## 4. Configuration Format

**File:** `~/.config/sync-center/config.json`

```json
{
  "version": "1.0",
  "general": {
    "auto_start": true,
    "show_notifications": true,
    "log_level": "info"
  },
  "profiles": [
    {
      "id": "backup-drive-1",
      "name": "My Backup Drive",
      "enabled": true,
      "identifier": {
        "type": "label",
        "value": "BACKUP"
      },
      "syncs": [
        {
          "source": "~/Pictures",
          "destination": "Pictures/",
          "bidirectional": false,
          "delete_missing": false,
          "exclude": [".cache", "*.tmp"]
        },
        {
          "source": "~/Documents/Logseq",
          "destination": "Logseq/",
          "bidirectional": false,
          "delete_missing": false,
          "exclude": []
        }
      ],
      "post_sync_action": "notify"
    },
    {
      "id": "portable-media",
      "name": "Portable Media Device",
      "enabled": true,
      "identifier": {
        "type": "marker",
        "path": ".sync-media"
      },
      "syncs": [
        {
          "source": "~/Music",
          "destination": "Music/",
          "bidirectional": false,
          "delete_missing": false,
          "exclude": ["*.m3u"]
        }
      ],
      "post_sync_action": "eject"
    }
  ]
}
```

**Drive Identifier Types:**
- `label` - Volume display name (e.g., "BACKUP")
  - Simple and user-friendly, but not unique
  - Best for single-volume USB drives
- `uuid` - Filesystem UUID
  - Unique and permanent identifier
  - More reliable but requires finding UUID (use `lsblk -o NAME,UUID`)
- `marker` - Look for specific file at volume root (e.g., ".sync-backup")
  - **Best for multi-partition USB drives** where label/UUID would be ambiguous
  - Daemon scans all mounted volumes, finds the one containing this marker file
  - Example: USB HDD with multiple partitions → place `.backup-marker.txt` on the specific partition you want to sync to
  - User creates this file manually: `touch /path/to/usb/.sync-backup`

---

## 5. UI/UX Design

### Main Window (GTK4 Libadwaita)

```
┌─ sync-center ────────────────────────────────────┐
│ [← Back] Sync Profiles                      [+ New] │
├──────────────────────────────────────────────────┤
│                                                  │
│ ✓ My Backup Drive                          [Edit] │
│   Status: Ready                                  │
│   Connected: No                                  │
│   Last Sync: 2 hours ago                         │
│   ───────────────────────────────────────────   │
│   • Pictures → Pictures/                        │
│   • Documents/Logseq → Logseq/                  │
│                                                  │
│ ✓ Portable Media Device                    [Edit] │
│   Status: Ready                                  │
│   Connected: Yes (40 GB available)              │
│   Last Sync: 1 hour ago                         │
│   [Sync Now] [Edit]                             │
│                                                  │
├──────────────────────────────────────────────────┤
│ [Preferences] [Help]                            │
└──────────────────────────────────────────────────┘
```

### New/Edit Profile Dialog

```
┌─ Create Sync Profile ────────────────────────────┐
│                                                  │
│ Name: [Backup Drive                         ]   │
│ Identifier Type: [Label              ▼]         │
│ Label/UUID/Path: [BACKUP           ]            │
│                                                  │
│ ── Directories to Sync ──────────────────────  │
│                                                  │
│ + Add Directory                                 │
│                                                  │
│ Source: ~/Pictures                              │
│ Destination: Pictures/           [Remove]       │
│ Options: [Exclude patterns ▼]                   │
│                                                  │
│ Source: ~/Documents/Logseq                      │
│ Destination: Logseq/             [Remove]       │
│                                                  │
│ ── Sync Options ──────────────────────────────  │
│ ☐ Bidirectional sync                            │
│ ☐ Delete files missing in source                │
│ ☐ Eject drive after sync                        │
│                                                  │
│ [Cancel] [Create]                               │
└──────────────────────────────────────────────────┘
```

### Sync In Progress (Notification + Eww)

**Desktop Notification:**
```
🔄 Syncing: My Backup Drive
  Pictures: 45 of 234 files
  [       ███████░░░] 32%
```

**Eww System Tray Icon:**
- Static icon with pulsing/spinning animation overlay
- Color: accent color (primary brand color)
- Animation: 1.5s rotation loop (like Material Design spinner)
- Click: Focus sync-center-gui
- Tooltip: "Syncing My Backup Drive (32%)"

---

## 6. Technical Stack

**Language:** Rust  
**GUI Framework:** GTK4 + Libadwaita bindings  
**IPC:** D-Bus (zbus crate)  
**Volume Monitoring:** GIO bindings  
**Sync Engine:** rsync CLI (child process)  
**Notifications:** libnotify bindings  
**Build System:** Cargo  
**Packaging:** PKGBUILD for Arch  

**Key Dependencies:**
```toml
[dependencies]
gtk4 = { version = "0.7", features = ["v4_6"] }
libadwaita = "0.6"
glib = "0.18"
gio = { version = "0.18", features = ["v2_70"] }
zbus = { version = "3.0", features = ["tokio"] }
tokio = { version = "1", features = ["full"] }
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
tracing = "0.1"
uuid = { version = "1.0", features = ["serde", "v4"] }
notify-rust = "4.10"
```

---

## 7. Integration Points

### Start Menu

**Desktop Entry:** `/usr/share/applications/sync-center.desktop`

```ini
[Desktop Entry]
Type=Application
Name=Sync Center
Comment=Manage automatic directory sync to external drives
Exec=sync-center-gui
Icon=sync-center
Categories=Utilities;
Keywords=sync;backup;usb;drive;

# smplOS specific
X-GNOME-Autostart-enabled=true
X-smplOS-Panel-Position=system-tray
```

### Eww System Tray Integration

**Eww Widget:** Added to `src/shared/eww/widgets/sync_center.yuck`

```lisp
(defwidget sync-center-indicator []
  (box :class "sync-center-indicator"
       :tooltip {sync_center_tooltip}
       :onclick "sync-center-gui"
    (image :image-size 24
           :class {sync_center_active ? "pulsing" : ""}
           :path "/usr/share/icons/sync-center.svg")))

(defvar sync_center_active false)
(defvar sync_center_tooltip "Sync Center - Ready")
```

**CSS Animation:** (in Eww theme)

```css
.sync-center-indicator.pulsing image {
  animation: spin 1.5s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
```

### Nemo Extension (Phase 2)

**Feature:** Show sync status indicator on synced directories in Nemo

- Add emblem/badge to folders being synced
- Right-click menu: "View sync profiles for this folder"
- Sidebar: Show connected sync devices with progress

---

## 8. D-Bus Interface

**Service Name:** `org.smpl.SyncCenter`  
**Object Path:** `/org/smpl/SyncCenter`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<node name="/org/smpl/SyncCenter">
  <interface name="org.smpl.SyncCenter">
    <!-- Properties -->
    <property name="IsActive" type="b" access="read"/>
    <property name="CurrentProfile" type="s" access="read"/>
    <property name="Progress" type="(ii)" access="read"/>
    <property name="StatusMessage" type="s" access="read"/>
    
    <!-- Methods -->
    <method name="GetProfiles">
      <arg name="profiles" type="a(ssbii)" direction="out"/>
    </method>
    
    <method name="GetProfile">
      <arg name="id" type="s" direction="in"/>
      <arg name="profile" type="(ssaa(ssbb))" direction="out"/>
    </method>
    
    <method name="SaveProfile">
      <arg name="profile" type="(ssaa(ssbb))" direction="in"/>
    </method>
    
    <method name="DeleteProfile">
      <arg name="id" type="s" direction="in"/>
    </method>
    
    <method name="SyncNow">
      <arg name="profile_id" type="s" direction="in"/>
      <arg name="success" type="b" direction="out"/>
    </method>
    
    <method name="CancelSync">
      <arg name="success" type="b" direction="out"/>
    </method>
    
    <!-- Signals -->
    <signal name="SyncStarted">
      <arg name="profile_id" type="s"/>
      <arg name="profile_name" type="s"/>
    </signal>
    
    <signal name="SyncProgress">
      <arg name="profile_id" type="s"/>
      <arg name="current" type="i"/>
      <arg name="total" type="i"/>
      <arg name="message" type="s"/>
    </signal>
    
    <signal name="SyncCompleted">
      <arg name="profile_id" type="s"/>
      <arg name="success" type="b"/>
      <arg name="message" type="s"/>
    </signal>
    
    <signal name="VolumeConnected">
      <arg name="volume_id" type="s"/>
      <arg name="volume_name" type="s"/>
    </signal>
    
    <signal name="VolumeDisconnected">
      <arg name="volume_id" type="s"/>
    </signal>
  </interface>
</node>
```

---

## 9. Data Structures

### In-Memory State

```rust
struct SyncCenterState {
    profiles: HashMap<String, SyncProfile>,
    active_sync: Option<ActiveSync>,
    connected_volumes: HashMap<String, ConnectedVolume>,
    history: Vec<SyncEvent>,
}

struct SyncProfile {
    id: String,
    name: String,
    enabled: bool,
    identifier: VolumeIdentifier,
    syncs: Vec<DirectorySync>,
    post_sync_action: PostSyncAction,
}

struct DirectorySync {
    source: PathBuf,
    destination: String,
    bidirectional: bool,
    delete_missing: bool,
    exclude: Vec<String>,
}

enum VolumeIdentifier {
    Label(String),
    UUID(String),
    Marker(String),
}

struct ConnectedVolume {
    id: String,
    mount_point: PathBuf,
    size_bytes: u64,
    available_bytes: u64,
    identifier: VolumeIdentifier,
}

struct ActiveSync {
    profile_id: String,
    started_at: SystemTime,
    current_file: String,
    progress: (u64, u64), // (current, total)
    child_process: Child,
}

struct SyncEvent {
    timestamp: SystemTime,
    profile_id: String,
    profile_name: String,
    success: bool,
    message: String,
    duration_secs: u64,
}
```

---

## 10. Implementation Phases

### Phase 1: Core Functionality (Weeks 1-2)

**Deliverables:**
- [ ] Daemon binary with GIO volume monitoring
- [ ] Config file parsing and validation
- [ ] Rsync execution with progress tracking
- [ ] D-Bus interface implementation
- [ ] Basic GTK4 GUI
- [ ] Systemd user service file
- [ ] Desktop entry
- [ ] Basic notifications (libnotify)

**Testing:**
- Mock mount/unmount events
- Test rsync with various directory sizes
- Verify D-Bus communication

---

### Phase 2: Polish & Integration (Weeks 3-4)

**Deliverables:**
- [ ] Eww system tray widget + animation
- [ ] Start Menu integration verified
- [ ] Sync history/log viewer
- [ ] Dry-run mode
- [ ] Profile import/export
- [ ] Error recovery and retry logic
- [ ] Comprehensive logging

**Testing:**
- Real USB drive testing
- Long-running sync stress test
- Multiple profile management
- Conflict scenarios

---

### Phase 3: Advanced Features (Future)

**Deliverables:**
- [ ] Nemo extension
- [ ] Scheduled syncs
- [ ] Bidirectional sync
- [ ] Network share support
- [ ] Compression options
- [ ] Conflict resolution UI

---

## 11. File Structure

```
src/shared/apps/sync-center/
├── spec.md                          # This file
├── Cargo.toml
├── src/
│   ├── bin/
│   │   ├── sync-center-daemon.rs    # Main daemon process
│   │   └── sync-center-gui.rs       # GTK4 UI
│   ├── lib.rs
│   ├── config.rs                    # Config parsing/validation
│   ├── dbus.rs                      # D-Bus interface
│   ├── volume_monitor.rs            # GIO volume monitoring
│   ├── rsync_runner.rs              # Rsync execution
│   ├── notification.rs              # libnotify wrapper
│   └── models.rs                    # Data structures
├── data/
│   ├── sync-center.desktop          # Start Menu entry
│   ├── org.smpl.SyncCenter.service  # D-Bus service file
│   └── sync-center.service          # Systemd user service
├── po/                              # i18n translations
└── PKGBUILD                         # Arch packaging
```

---

## 12. Success Criteria

- [x] User can create sync profiles with GUI
- [x] Daemon automatically detects connected drives
- [x] Sync executes on mount without user intervention
- [x] Progress shown in notifications and GUI
- [x] Can cancel running sync
- [x] Reliable rsync execution (no data loss)
- [x] D-Bus interface working
- [x] Eww system tray integration
- [x] Start Menu launch working
- [x] No memory leaks
- [x] <500ms daemon startup time

---

## 13. Error Handling & Corner Cases

### Critical Pre-flight Checks

**Before every sync:**

1. **rsync Installation Check**
   - Verify `rsync` binary exists and is executable: `which rsync`
   - If missing: Emit SyncError signal, notify user "rsync not installed", suggest installation
   - Action: Fail fast, do not attempt sync
   - Notification: "rsync is not installed. Install with: sudo pacman -S rsync"

2. **Source/Destination Validation**
   - Source path must exist and be readable
   - Destination parent directory must exist and be writable
   - If either fails: Emit SyncError, notify user with specific path
   - Example: "Source /home/user/Photos is not readable (permission denied)"

3. **Disk Space Check**
   - Calculate total size of source
   - Verify destination has 110% of source size available (10% buffer)
   - If insufficient: Emit SyncError, notify "Insufficient disk space on [drive]: need X GB, have Y GB"
   - Do NOT proceed with sync

4. **Volume Stability Check**
   - Monitor if USB volume is still mounted after profile match
   - If disconnected between match and rsync start: Emit SyncError, skip this sync
   - Notification: "USB drive disconnected before sync could start"

5. **Permission Validation**
   - Test write permission on destination: `touch /dest/.sync-test-XXXX && rm`
   - If fails: Emit SyncError with reason (permission denied, read-only FS, etc)

### Merge Conflict Strategies

**For bidirectional sync (Phase 2+):**

#### Text Files (`.md`, `.txt`, `.rs`, `.json`, `.yaml`, `.csv`, `.sh`, etc.)
- Use `git-style` conflict markers when both sides have different content
- Markers format:
  ```
  <<<<<<< source
  [content from source]
  =======
  [content from destination]
  >>>>>>> dest
  ```
- File is marked with `.CONFLICT` suffix: `myfile.md.CONFLICT`
- Original is backed up as `.md.source` and `.md.dest`
- User must manually merge and remove `.CONFLICT` suffix
- Notification: "Merge conflict in Photos.md on [drive]. Resolve manually and rename to remove .CONFLICT"
- Log: Record conflicted file path, size, source vs dest modification times

#### Binary Files (`.png`, `.jpg`, `.zip`, `.exe`, `.bin`, etc.)
- **Strategy 1 (Default):** Skip binary conflicts entirely
  - Skip writing conflicted binary, log it, continue with rest of sync
  - Notification: "Skipped binary file MyPhoto.jpg (conflict detected). Source and destination differ."
  - User can manually resolve later
  
- **Strategy 2 (Alternative - Phase 2):** Add conflict dialog
  - Show GTK4 dialog: "Binary file conflict"
  - Options: [Keep Source] [Keep Destination] [Skip] [Cancel All]
  - User chooses, apply to similar future conflicts
  - Log decision for audit trail

#### Recommendation (Phase 1)
- Text files: Use conflict markers
- Binary files: Skip with notification, log to ~/.config/sync-center/conflicts.log
- User reviews conflicts.log and resolves manually

### Handle Missing rsync Gracefully

```rust
// In rsync_runner.rs
match Command::new("rsync").arg("--version").output() {
    Ok(output) if output.status.success() => {
        // rsync is installed, proceed
    }
    _ => {
        // rsync not found
        let error = SyncError::RsyncNotInstalled(
            "rsync not found in PATH".to_string()
        );
        emit_dbus_signal(SyncError(error));
        notify_user("rsync is not installed.\n\nInstall with: sudo pacman -S rsync");
        return Err(error);
    }
}
```

### Runtime Error Scenarios

| Scenario | Behavior | Notification | Log Level |
|----------|----------|--------------|-----------|
| **Disk full during sync** | Cancel immediately, report consumed bytes | "Sync cancelled: destination disk full" | ERROR |
| **Source file deleted mid-sync** | rsync skips it gracefully, log warning | "Some source files were deleted during sync" | WARN |
| **Permission denied on file** | rsync skips that file, continue | "Skipped X files due to permission errors" | WARN |
| **File locked (in use)** | rsync skips, try again next sync | "Skipped X files (currently in use)" | WARN |
| **Symlink encountered** | Follow symlinks by default (`-L` flag) | - | INFO |
| **Special files (socket, FIFO, device)** | Skip with warning | "Skipped special files (socket, device, etc)" | WARN |
| **Concurrent sync to same dest** | Lock file `~/.config/sync-center/.sync.lock` | "Another sync is running for this profile" | ERROR |
| **Config file corrupted** | Load defaults, emit warning, attempt repair | "Config corrupted, reverting to defaults" | ERROR |
| **D-Bus unavailable** | Continue daemon, queue signals, retry when available | - | WARN |
| **USB disconnected mid-sync** | rsync detects I/O error, abort gracefully | "USB drive disconnected during sync" | ERROR |
| **Network share timeout (Phase 2)** | rsync timeout 60s, emit timeout error | "Network share timeout" | ERROR |
| **Insufficient inode space** | Detected in pre-check, emit error | "Destination has insufficient inodes" | ERROR |
| **Read-only filesystem** | Detected in pre-check | "Destination is read-only" | ERROR |

### State Recovery

**Daemon Startup:**
- Check for stale `.sync.lock` files older than 24h, remove them
- Load config, validate all paths exist (warn if missing)
- Check for incomplete syncs from previous session
  - Log: "Found incomplete sync: profile X (started at Y)"
  - Option: Resume on next mount of same volume

**GUI Startup:**
- Query daemon for current sync state
- If daemon not responding, show "Daemon not running, start with: systemctl --user start sync-center"
- Cache last known state in `~/.config/sync-center/gui-state.json`

### Logging Strategy

**Log File:** `~/.local/share/sync-center/sync-center.log`

**Log Format:**
```
[2026-03-07 14:23:15.456] [sync-center-daemon] [INFO] Mounted volume: Photos (UUID: ABC123)
[2026-03-07 14:23:16.123] [sync-center-daemon] [INFO] Starting sync: profile "Daily Photos" → /media/usb1
[2026-03-07 14:23:45.678] [sync-center-daemon] [WARN] Skipped 3 files due to permission errors
[2026-03-07 14:24:02.901] [sync-center-daemon] [WARN] Merge conflict: Photos.md (conflict markers added)
[2026-03-07 14:24:30.234] [sync-center-daemon] [INFO] Sync completed: 45 files, 1.2 GB in 44 seconds
```

**Tracing Integration (using `tracing` crate):**
- `RUST_LOG=sync_center=debug` for debugging
- `RUST_LOG=sync_center::rsync_runner=trace` for rsync details
- Structured logs for easy parsing

---

## 14. Non-Goals (Out of Scope for v1.0)

- Network sync (SMB, NFS, S3, etc.)
- Selective file encryption
- Cloud backup integration (Google Drive, Nextcloud API)
- Mobile app integration
- Remote sync between two machines
- Version control/file history
- File deduplication

---

## 15. References

- [rsync man page](https://man.archlinux.org/man/rsync.1.en)
- [GTK4 Rust bindings](https://gtk-rs.org/gtk4-rs/)
- [Libadwaita](https://libadwaita.gnome.org/)
- [D-Bus specification](https://dbus.freedesktop.org/)
- [systemd user services](https://wiki.archlinux.org/title/Systemd/User)
- [GIO volume monitoring](https://developer.gnome.org/gio/stable/GVolumeMonitor.html)

---

## 16. Open Questions / TBD

- [ ] Should we support rsync over SSH for remote drives?
- [ ] Max profile limit or infinite?
- [ ] Should sync history be persistent (SQLite)?
- [ ] Should we add bandwidth limiting options?
- [ ] Should failed syncs auto-retry?
- [ ] Encryption of config file (for password storage)?

---

**Next Steps:**  
1. Review and approve spec
2. Set up Cargo project scaffold
3. Begin Phase 1 implementation
4. Gather user feedback on UI mockups
