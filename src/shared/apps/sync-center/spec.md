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
- `uuid` - Filesystem UUID
- `marker` - Look for file at root (e.g., ".sync-backup")

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

## 13. Non-Goals (Out of Scope for v1.0)

- Network sync (SMB, NFS, S3, etc.)
- Selective file encryption
- Cloud backup integration (Google Drive, Nextcloud API)
- Mobile app integration
- Remote sync between two machines
- Version control/file history
- File deduplication

---

## 14. References

- [rsync man page](https://man.archlinux.org/man/rsync.1.en)
- [GTK4 Rust bindings](https://gtk-rs.org/gtk4-rs/)
- [Libadwaita](https://libadwaita.gnome.org/)
- [D-Bus specification](https://dbus.freedesktop.org/)
- [systemd user services](https://wiki.archlinux.org/title/Systemd/User)
- [GIO volume monitoring](https://developer.gnome.org/gio/stable/GVolumeMonitor.html)

---

## 15. Open Questions / TBD

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
