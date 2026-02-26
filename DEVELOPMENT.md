# smplOS Development Guide

How to extend, modify, and contribute to smplOS.

---

## Table of Contents

- [Known-Good Commits](#known-good-commits)
- [How the Build Works](#how-the-build-works)
- [Development Iteration](#development-iteration)
- [VM Testing](#vm-testing)
- [Adding a Settings Entry](#adding-a-settings-entry)

---

## Known-Good Commits

Rollback points for critical milestones. If something breaks, `git checkout <hash>`.

| Commit | Date | Milestone |
|--------|------|-----------|
| `7b6416c` | 2026-02-25 | Ventoy UEFI boot working (uefi.grub + vanilla Arch releng grub configs) |

---

## How the Build Works

Running `./src/build-iso.sh` produces a bootable Arch-based ISO. The whole thing is
containerized for reproducibility — you don't need an Arch host and your system never
gets touched.

### Two-Stage Container Architecture

The build uses **two separate Podman containers** in sequence.

```
build-iso.sh  (host orchestrator)
│
├─ Stage 1 ─ AUR builder container  (archlinux:latest)
│             Builds AUR packages that can't be fetched from official repos.
│             Output: .pkg.tar.zst files → build/prebuilt/
│             Skipped automatically if all packages already exist there.
│
└─ Stage 2 ─ ISO builder container  (archlinux:latest, --privileged)
              Downloads all packages, compiles Rust apps, runs mkarchiso.
              Output: .iso → release/
```

**Why `sudo podman`?** `mkarchiso` (the Arch ISO tool) requires real root to create
loop devices, run `mount`, and call `mksquashfs`. Rootless Podman's `--privileged`
only grants unprivileged-user capabilities, which isn't enough. So the outer script
runs the container with `sudo podman run --privileged`, but Podman itself requires no
daemon or background service.

**Why two containers?** AUR packages (eww, brave-bin, paru-bin, etc.) must be compiled
with `makepkg` as a non-root user, which is incompatible with the `--privileged` ISO
builder. Separating them also means you only rebuild AUR packages when their
`PKGBUILD` changes — subsequent runs reuse the cached `.pkg.tar.zst` files in
`build/prebuilt/`.

---

### Stage 1: AUR Package Builder

Triggered by: `build_missing_aur_packages()` in `src/build-iso.sh`

For each AUR package listed in `packages-aur.txt`:
1. Checks `build/prebuilt/` for an existing `<pkg>-*.pkg.tar.zst` — **skips if found**.
2. Spins up a fresh `archlinux:latest` container (no `--privileged`, `--network=host`).
3. Creates a non-root `builder` user, clones the AUR git repo, imports required PGP
   keys, and runs `makepkg -s`.
4. Copies the resulting `.pkg.tar.zst` to `/output`, which is bind-mounted to
   `build/prebuilt/` on the host.

If any package needs Rust (e.g. `eww`), `rustup` is installed inside the container
before building.

---

### Stage 2: ISO Builder Container

Triggered by: `run_build()` in `src/build-iso.sh`

The container runs `src/builder/build.sh` as root inside `archlinux:latest
--privileged`. Volume mounts wired in from the host:

| Host path | Container path | Access |
|---|---|---|
| `src/` | `/build/src` | read-only |
| `release/` | `/build/release` | read-write (ISO lands here) |
| `build/prebuilt/` | `/build/prebuilt` | read-only (AUR .pkg.tar.zst) |
| `.cache/build_YYYY-MM-DD/pacman/` | `/var/cache/smplos/pacman-cache` | read-write |
| `.cache/build_YYYY-MM-DD/offline-repo/` | `/var/cache/smplos/mirror/offline` | read-write |
| `.cache/binaries/` | `/var/cache/smplos/binaries` | read-write (Rust binary cache) |
| `/var/cache/pacman/pkg/` *(Arch hosts only)* | `/var/cache/pacman/pkg` | read-only (speeds up downloads) |

The build script inside the container runs these stages in order:

```
setup_build_env       → set paths, parse env vars
collect_packages      → merge shared + compositor + edition package lists
setup_profile         → populate the mkarchiso profile directory
download_packages     → pacstrap ~875 packages into the airootfs
process_aur_packages  → install prebuilt .pkg.tar.zst from /build/prebuilt
download_flatpaks     → (optional) write Flathub install list
download_appimages    → (optional) download AppImages
create_repo_database  → build a local pacman repo from the offline mirror
setup_pacman_conf     → write pacman.conf for the ISO environment
update_package_list   → generate profiledef package list for mkarchiso
update_profiledef     → set ISO name, version, compression
setup_airootfs        → copy dotfiles, configs, scripts, themes, installer
build_st              → compile st (suckless terminal) from source
build_notif_center    → compile notif-center (Rust+Slint)
build_kb_center       → compile kb-center (Rust+Slint)
build_disp_center     → compile disp-center (Rust+Slint)
build_app_center      → compile app-center (Rust+Slint)
setup_boot            → write systemd-boot + GRUB loopback + Syslinux configs
build_iso             → run mkarchiso → xorriso → .iso
```

---

### Rust App Compilation (inside the container)

The four Rust/Slint GUI apps (`notif-center`, `kb-center`, `disp-center`,
`app-center`) are compiled from source **inside the ISO builder container**, not on
the host. Each follows the same pattern:

1. **Source-hash cache check** — hashes all `.rs` files, `Cargo.toml`, `Cargo.lock`,
   and `build.rs`. If the hash matches a file in `/var/cache/smplos/binaries/`, the
   cached binary is reused and the Rust compile is skipped entirely. This makes
   repeated builds fast when the Rust source hasn't changed.
2. **Copy to temp dir** — source is copied to `/tmp/<app>-build/` so the build never
   touches the read-only `/build/src` mount.
3. **`cargo build --release`** — compiled inside the temp dir.
4. **Install + strip** — binary installed to both `/usr/local/bin/` (for the live ISO
   session) and `/root/smplos/bin/` (for the post-install deployer).
5. **Cache** — binary saved to `/var/cache/smplos/binaries/<app>-<hash>` for future runs.

The `/var/cache/smplos/binaries/` path inside the container is bind-mounted from
`.cache/binaries/` on the host, so the cache persists across builds.

---

### Artifact Locations

All build output lands **outside `src/`** — the source tree stays clean:

| What | Where |
|---|---|
| **Final ISO** | `release/smplos-hyprland-YYMMDD-HHmm.iso` |
| **AUR packages** | `build/prebuilt/*.pkg.tar.zst` |
| **Rust binary cache** | `.cache/binaries/<app>-<src-hash>` |
| **Pacman package cache** | `.cache/build_YYYY-MM-DD/pacman/` (dated, kept 3 days) |
| **Offline repo mirror** | `.cache/build_YYYY-MM-DD/offline-repo/` (dated, kept 3 days) |
| **Build logs** | `.cache/logs/build-YYYYMMDD-HHMMSS.log` |

The `build/` and `.cache/` directories are git-ignored. `release/` contains only the
ISO and the helper scripts that ship with the project (`test-iso.sh`, `dev-push.sh`,
etc.) — only `.iso` files are git-ignored there.

For **local development builds** of the Rust apps (running `build.sh` directly on
your host without going through the container), `cargo` output goes to
`build/target/` via `CARGO_TARGET_DIR` — not into `src/shared/<app>/target/`.

---

### Log Files

Every run writes a timestamped log to `.cache/logs/`:

```
.cache/logs/
└── build-20260222-104400.log   ← stdout + stderr of the entire build
```

The log is written by `exec > >(tee -a "$BUILD_LOG") 2>&1` at the top of
`build-iso.sh`, so output goes to **both the terminal and the log file
simultaneously**, without any external pipe. This means you can safely run the build
in the background (`bash src/build-iso.sh & disown`) and tail the log separately:

```bash
# Start build in background
cd ~/Documents/sources/smplos
bash src/build-iso.sh &

# Follow the log without interfering with the build process
tail -f .cache/logs/build-$(ls -t .cache/logs/ | head -1)
```

To scan a completed log for errors:

```bash
grep -E "ERROR|FAILED|error:|die" .cache/logs/build-*.log | cat
```

Logs older than the three most recent dated cache directories are pruned automatically
on each build run.

---

### Caching and Re-runs

| Scenario | What gets reused |
|---|---|
| Same day, nothing changed | AUR packages, Rust binaries, downloaded `.pkg` files |
| New day, same packages | AUR packages, Rust binaries (new dated pacman cache) |
| AUR package already in `build/prebuilt/` | Skipped, container never spawned |
| Rust source unchanged (same hash) | Cached binary from `.cache/binaries/` |
| `--no-cache` flag | Forces fresh package downloads |

---

## Development Iteration

For config/script changes, avoid full ISO rebuilds (~15 min). Instead, push changes directly to a running VM:

```bash
# Host: push changes to VM shared folder
cd release && ./dev-push.sh eww    # or: bin, hypr, themes, all

# VM: apply changes to the live system
sudo bash /mnt/dev-apply.sh
```

ISO rebuilds are only needed when adding or removing **packages**.

## VM Testing

Use QEMU for testing -- it provides a `virtio-gpu` device that Hyprland works with out of the box:

```bash
cd release && ./test-iso.sh
```

This launches a QEMU VM with KVM acceleration, UEFI firmware, a 20 GB virtual disk, and a 9p shared folder for live hot-reloading. The script auto-detects OVMF, finds the newest ISO in `release/`, and opens the VM window.

Once the VM boots, mount the shared folder to enable hot-reload:

```bash
# Inside the VM:
sudo mount -t 9p -o trans=virtio hostshare /mnt
```

Then iterate without rebuilding the ISO:

```bash
# Host: push changes to the shared folder
cd release && ./dev-push.sh

# VM: apply them to the live system
sudo bash /mnt/dev-apply.sh
```

The 9p mount is live -- `dev-push.sh` writes to `release/vmshare/` and changes are immediately visible inside the VM. No remount needed.

Use `--reset` to wipe the VM disk and start fresh:

```bash
./test-iso.sh --reset
```

> **VirtualBox is not supported.** Hyprland requires a working DRM/KMS device with OpenGL support. VirtualBox's virtual GPU (`VBoxVGA` / `VMSVGA`) does not provide this -- Hyprland will crash immediately on startup. Use QEMU with KVM (`test-iso.sh`) or VMware with 3D acceleration instead.

---

## Adding a Settings Entry

The start menu has a **Settings** category. Each entry there launches a system tool -- Appearance opens the theme picker, Audio opens pavucontrol, etc. Here's how to add a new one.

### Overview

Settings entries involve two pieces:

| File | Role |
|------|------|
| `src/shared/bin/rebuild-app-cache` | Registers the entry in the app index |
| `src/shared/bin/smplos-settings` | Dispatches the entry to the right tool |

The flow:

```
rebuild-app-cache          builds ~/.cache/smplos/app_index
       |
start-menu                 reads app_index, shows entries by category
       |
user clicks an entry       start-menu executes the command
       |
smplos-settings <category> dispatches to the right tool
```

### Step 1: Register the entry in the app cache

Open `src/shared/bin/rebuild-app-cache` and find the `emit_settings()` function. Add a line in the heredoc:

```bash
emit_settings() {
  cat <<'EOF'
App Center;toggle-app-center;settings;system-software-install
Web Apps;webapp-center;settings;applications-internet
Appearance;smplos-settings appearance;settings;preferences-desktop-theme
Display;smplos-settings display;settings;preferences-desktop-display
Keyboard;smplos-settings keyboard;settings;preferences-desktop-keyboard
Network;smplos-settings network;settings;preferences-system-network
Bluetooth;smplos-settings bluetooth;settings;bluetooth
Audio;smplos-settings audio;settings;audio-volume-high
My New Entry;smplos-settings my-entry;settings;my-icon-name    # <-- add here
Power Menu;smplos-settings power;settings;system-shutdown
About smplOS;smplos-settings about;settings;help-about
EOF
}
```

The format is semicolon-delimited:

```
Name;Command;Category;Icon
```

| Field | Description |
|-------|-------------|
| **Name** | What the user sees in the start menu |
| **Command** | What gets executed when the entry is selected |
| **Category** | Must be `settings` to appear in the Settings tab |
| **Icon** | A freedesktop icon name (from your icon theme) or leave empty |

> **Tip:** Browse available icon names with `gtk3-icon-browser` or check `/usr/share/icons/`. Common settings icons: `preferences-desktop-*`, `preferences-system-*`, `audio-*`, `network-*`, `input-keyboard`, `bluetooth`.

### Step 2: Add the dispatcher case

Open `src/shared/bin/smplos-settings` and add a `case` branch for your new category:

```bash
  my-entry)
    command -v my-tool &>/dev/null && exec my-tool
    die "my-tool not found (install my-tool-package)"
    ;;
```

**Cross-compositor pattern:** If the tool differs between Wayland and X11, detect at runtime:

```bash
  my-entry)
    if [[ -n "$WAYLAND_DISPLAY" ]]; then
      command -v wayland-tool &>/dev/null && exec wayland-tool
    else
      command -v x11-tool &>/dev/null && exec x11-tool
    fi
    die "No tool found for my-entry"
    ;;
```

**Terminal-based tools:** If the tool is a TUI (runs in a terminal), use the `term()` helper:

```bash
  my-entry)
    command -v my-tui &>/dev/null && exec term my-tui
    die "my-tui not found"
    ;;
```

Don't forget to update the usage string at the bottom of the file:

```bash
  *)
    echo "Usage: smplos-settings {appearance|display|keyboard|...|my-entry|...}" >&2
    exit 1
    ;;
```

### Step 3: Rebuild the cache and test

```bash
# Rebuild the app index
rebuild-app-cache

# Open the start menu and click the Settings category
```

Your new entry should appear in the list. Click it (or press Enter) to launch.

If you're iterating in a VM:

```bash
# Host
cd release && ./dev-push.sh bin

# VM
sudo bash /mnt/dev-apply.sh
rebuild-app-cache
```

### Example: the Keyboard entry

Here's the real commit that added the Keyboard Center to the settings menu:

**`rebuild-app-cache` -- `emit_settings()`:**
```
Keyboard;smplos-settings keyboard;settings;preferences-desktop-keyboard
```

**`smplos-settings` -- new case:**
```bash
  keyboard)
    command -v kb-center &>/dev/null && exec kb-center
    die "Keyboard Center not found"
    ;;
```

Two lines of code, and Keyboard Center appears in the start menu's Settings category.
