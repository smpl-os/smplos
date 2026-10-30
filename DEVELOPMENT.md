# smplOS Development Guide

How to extend, modify, and contribute to smplOS.

---

## Table of Contents

- [Known-Good Commits](#known-good-commits)
- [How the Build Works](#how-the-build-works)
- [Development Iteration](#development-iteration)
- [VM Testing](#vm-testing)
- [Testing Keybindings](#testing-keybindings)
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

**Why two containers?** AUR packages (eww, brave-bin, yay-bin, etc.) must be packaged
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
                        (auto-builds from AUR if no prebuilt found)
download_flatpaks     → (optional) write Flathub install list
download_appimages    → (optional) download AppImages
cache_whisper_models  → download Whisper models (base.en + base multilingual, ~300 MB total)
                        for offline dictation; persisted in build/dictation/
create_repo_database  → build a local pacman repo from the offline mirror
setup_pacman_conf     → write pacman.conf for the ISO environment
update_package_list   → generate profiledef package list for mkarchiso
update_profiledef     → set ISO name, version, compression
setup_airootfs        → copy dotfiles, configs, scripts, themes, installer,
                        bundle Whisper model + voxtype config to airootfs
build_st              → compile st (suckless terminal) from source
build_notif_center    → compile notif-center (Rust+Slint)
build_kb_center       → compile kb-center (Rust+Slint)
build_disp_center     → compile disp-center (Rust+Slint)
build_app_center      → compile app-center (Rust+Slint)
build_hyprland_plugins → compile the Hyprland plugins (smpl-hud, smpl-scroll)
                        against the hyprland package the ISO ships
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

### Hyprland Plugin Compilation (inside the container)

The Hyprland plugins are native C++ (`src/compositors/hyprland/plugins/<name>`, see
each README): `smpl-hud` draws the HUD window frames and `smpl-scroll` lets
scrolling-layout columns grow wider than the monitor. A Hyprland plugin
only loads into the exact Hyprland build it was compiled against, so it is never
shipped as a prebuilt binary:

1. `build_hyprland_plugins` installs the `hyprland` package **from the offline
   mirror** (the very file the ISO ships) into the container, so the headers match
   what the installed system will run.
2. `smplos-plugins sync` compiles every `plugins/<name>/` out of tree (the
   read-only `/build/src` mount is never written) and stores
   `<name>.<abi-key>.so` under `usr/local/lib/smplos/plugins` in the image. The live
   session loads it from there and the installer copies the directory to the target.
3. A failure only warns: the ISO still builds, windows keep Hyprland's stock
   borders, and Update OS compiles the plugin on the installed system.

After a Hyprland update the ABI key changes: Update OS (`sync_plugins` in
`smplos-os-update`) rebuilds for the installed Hyprland and swaps the new binary
into the running session, and `smplos-plugins load`, run from `autostart`, only
ever loads the binary that matches the running compositor.

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

## Offline Dictation Pipeline

smplOS bundles Whisper speech-to-text models into the ISO so dictation works without
internet in any language. Here's the full flow from build to first use.

### Build Time (`cache_whisper_models` + `setup_airootfs`)

1. `cache_whisper_models()` downloads two models from HuggingFace:
   - **`base.en`** (English-optimized, ~148 MB) from `Systran/faster-whisper-base.en`
   - **`base`** (multilingual, 99 languages incl. Chinese, Japanese, etc., ~148 MB) from `Systran/faster-whisper-base`
   
   Each model consists of 4 files: `config.json`, `model.bin`, `tokenizer.json`, `vocabulary.txt`.
   The build container's `$CACHE_DIR/models/whisper/` is volume-mounted to `build/dictation/`
   on the host — so models persist across builds and can be pre-populated manually
   (place files in `build/dictation/base.en/` or `build/dictation/base/`). Non-fatal on
   failure — if download fails, dictation just won't be pre-cached.
2. `setup_airootfs()` copies all cached models to two places in the ISO:
   - `/usr/share/smplos/models/whisper/<model>/` — system-wide, read by `dictation-prime`
   - `/root/smplos/models/whisper/<model>/` — staging area, copied to installed system
     by `install.sh`
3. A default `config.toml` for voxtype is placed in `/etc/skel/.config/voxtype/` and
   staged for the installer. Defaults to `model = "base"` with `language = "auto"` for
   multilingual support.
4. A `voxtype.service` systemd user unit is placed in `/etc/skel/.config/systemd/user/`.

### Install Time (`install.sh`)

The installer calls `dictation-prime` after `rebuild-app-cache`. This primes the new
user's HuggingFace cache from all bundled models so dictation works on first login.

### First Use (`dictation-prime`)

`dictation-prime` is an idempotent script that:
1. Iterates over all models in `/usr/share/smplos/models/whisper/` and copies each into
   the HuggingFace cache at `~/.cache/huggingface/hub/models--Systran--faster-whisper-<model>/snapshots/smplos-bundled/`.
2. Sets `refs/main` → `smplos-bundled` for each model so voxtype resolves them.
3. Writes `~/.config/voxtype/config.toml` if missing (defaults to multilingual `base` model).
4. Creates and enables the `voxtype.service` systemd user unit.
5. Writes marker `~/.config/smplos/.dictation-primed` so subsequent calls are instant no-ops.

Won't overwrite if user has already downloaded their own model snapshot.

### AUR Package Auto-Build

`process_aur_packages()` in `build.sh` has a defense-in-depth fallback: if no prebuilt
`.pkg.tar.zst` is found for an AUR package (including `voxtype-bin`), it clones the AUR
repo, imports required PGP keys, and runs `makepkg` inside the build container. This
means contributors don't need to manually pre-compile AUR packages.

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

On an installed development machine, `release/dev-local.sh` accepts the same
component names (run it elevated from the intended checkout). EWW deployment
preserves the active palette and custom extra files, then reloads the existing
daemon instead of killing it and independently opening another bar. Theme or
compositor reload failures are visible and return a nonzero status; "All done"
is printed only after those steps succeed. Bar startup, reload and geometry
redraws share a config-scoped lock; daemon/listener children do not inherit it.
An already-running older `bar-ctl watch` must be restarted or replaced at next
login to use the new serialized redraw entrypoint.

Compositor plugins (`src/compositors/hyprland/plugins/`, the HUD frames) are
native code that only loads into the exact Hyprland build it was compiled
against, so both workflows compile them on the target machine instead of
copying a binary: `dev-push.sh` stages the sources, `dev-apply.sh` builds them in
the VM, and `sudo ./dev-local.sh plugins` builds them as your user and installs
them into `/usr/local/lib/smplos/plugins`. A rebuilt plugin is reloaded in the
running session; an unchanged one is only loaded if it is not already. The build
needs the Hyprland headers (part of the `hyprland` package) and `base-devel`;
`dev-local.sh` skips the component with a warning when the headers are missing
and stops with an error if a build fails. `smplos-plugins status` shows what is
installed and loaded. The plugins' compositor-free unit tests run anywhere with
`make -C src/compositors/hyprland/plugins/<name> test`.

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

## Testing Keybindings

A shortcut that raises a Lua error or does nothing is easy to ship and hard to notice, so every
stock bind is checked automatically. `tools/keybind-check` runs the checks, and
`tests/test_keybindings.py` runs the same ones as one named test per bind. Run them whenever you
change `bindings.conf`, `messengers.conf`, `bindings_loader.lua`, `popup_watchers.lua`, or a
script or package that a bind relies on.

```bash
tools/keybind-check check                                   # everything, in a couple of seconds
PYTHONPATH=tests python3 -m unittest test_keybindings -v    # the same, as tests
tools/keybind-check doctor                                  # which checks can run on this machine
```

Python 3 and Lua are required. `libxkbcommon` makes chord matching exact, and Hyprland adds the
native pass; without them those parts are skipped (`KEYBIND_CHECK_REQUIRE=lua,xkbcommon,hyprland`
makes a missing tool a failure instead). For every stock bind, with the workspace policy both off
and on, `check` covers:

- **Static rules.** The chord has modifiers and a key that exist. No chord is bound twice, counting
  the messenger, XR and emergency binds and `popup_watchers.lua`. Each dispatcher gets arguments it
  accepts, including the `layoutmsg` verbs the scrolling layout knows. An `exec` command is a
  script in `src/shared/bin`, a packaged program or a shell builtin. This is what finds
  `layoutmsg orientationnext`, which scrolling does not have and which raised
  `no such layoutmsg for scrolling` on Super+J.
- **Loader parity.** `bindings_loader.lua` runs under plain Lua against a recording `hl`, so what
  each line becomes is compared with what the line says it should do.
- **Native.** Each bind is loaded alone, through the real loader, by `Hyprland --verify-config`, so
  Hyprland's own parser judges the key, the modifiers and the dispatcher, and a failure names the
  one bind. Run as root, as CI containers are, it passes Hyprland's root override, which is safe
  because verifying a config never starts a session.
- **Snapshot.** `tests/fixtures/keybindings.snapshot.txt` records what every stock bind does.
  Changing a bind, or how the loader translates one, fails the test until you read the difference
  and run `tools/keybind-check snapshot --update`, so a shortcut never changes unnoticed.

### One bind, or a group

```bash
tools/keybind-check check --only SUPER+TAB                  # one chord
tools/keybind-check check --only "window management"        # a group, or words from a description
tools/keybind-check list --only workspaces                  # what the binds do, without checking
PYTHONPATH=tests python3 -m unittest test_keybindings -v -k SUPER_TAB          # one bind
PYTHONPATH=tests python3 -m unittest test_keybindings -v -k window_management   # one group
PYTHONPATH=tests python3 -m unittest test_keybindings -v -k NativeBindTests     # one kind of check
```

Per-bind tests are named `test_<group>__<chord>`, for example `test_workspaces__SUPER_TAB`, and
`-k` matches any part of the name (case-sensitively). The groups are `application`,
`window_management`, `workspaces`, `utilities`, `media_keys`, `exit`, `xr` and `emergency`. To run
one in GitHub Actions, start the **Keybindings** workflow by hand and type the same text into its
`filter` box.

### A machine that misbehaves

`bindings.conf` is protected from Update OS, so an installed copy can be older than the stock one,
which is how a shortcut fixed long ago can still raise an error on one machine. To audit it:

```bash
tools/keybind-check check --live      # the binds this user's session loads, judged as Hyprland sees them
tools/keybind-check diff --live       # how that file differs from stock: missing, changed, extra
tools/keybind-check check --bindings /path/to/bindings.conf    # a file someone sent you
```

A stale copy is repaired by a migration the next time that user runs Update OS, for example
`20261018-054000-scrolling-shortcut-conflicts.sh` and
`20261019-153100-remove-duplicate-popup-click-bind.sh`, so run Update OS first and audit again. A
change to a stock bind needs such a migration too; see
[Writing a Migration](UPDATING.md#5-writing-a-migration).

### The lab

The lab starts a throwaway headless Hyprland and types every chord through a virtual keyboard. It
therefore also finds a chord that another bind shadows, a bind that fires twice, and a dispatcher
that fails or does the wrong thing when it runs, none of which a parser can see.

```bash
tools/keybind-check lab                         # every bind, about 35 seconds
tools/keybind-check lab --only SUPER+TAB        # one chord
tools/keybind-check lab --policy on             # with the workspace policy on (workspace-ctl is stubbed)
tools/keybind-check lab --keep                  # keep its logs and print where they are
KEYBIND_LAB=1 PYTHONPATH=tests python3 -m unittest test_keybindings -v -k LabTests   # the same, as tests
```

It cannot reach your session: it has its own runtime directory and `HOME`, `/dev/input` is hidden,
and only stub programs are on `PATH`. It does need a DRM render node and PyGObject with GTK 3, so it
runs on a developer machine and not on GitHub's runners, and not as root. Pointer binds and
**Exit Hyprland**, which would end the lab's own compositor, are not pressed; the lab lists every
skip with its reason. Run it before a release, and after changing `bindings.conf`, the loader or
the Hyprland version.

### CI and releases

`.github/workflows/keybindings.yml` runs on every push to `main`, every pull request, every Monday,
and on demand:

- `static` has only Lua and libxkbcommon: the static rules and loader parity.
- `native` adds `Hyprland --verify-config` for every bind on the approved stack. It reads
  `src/shared/update-policy/ci-baseline.json` after checkout, checks the exact package against
  `HYPRLAND_SERIES` in `critical-bundle.conf`, and starts a digest-pinned disposable Arch container.
  The **whole container system**, not just Hyprland, is synchronized (including downgrades) against
  the dated Arch Linux Archive's core/extra repositories only. Every installed package must match
  that snapshot, the exact Hyprland package and executable must match policy, and the complete
  package inventory is logged. Missing policy, unavailable snapshots/images, dependency errors or
  version drift fail the gate; there is no fallback to current mirrors.

The initial baseline is the **2026/10/28** archive, containing **hyprland 0.56.2-4**,
matching the passing [native run 40747213246](https://github.com/smpl-os/smplos/actions/runs/40747213246).
The official Arch bootstrap image is version `20261025.0.616225`, pinned by digest in the JSON.
The archive's `extra.db` records the Hyprland package SHA-256 as
`163bc740241880192d90027fad39ddb809b1705b04800a1f0185a58f3ce0884a`;
pacman still requires package signatures. `critical-packages.txt` remains the broad installed-stack
transition-root policy, **not** a list of exact CI versions. This CI baseline does not change
live-system updates or ISO build repositories.

To reproduce the required native job without touching host packages or the running compositor:

```bash
python3 tools/ci_baseline.py --check                    # policy validation only
python3 tools/ci_baseline.py                            # disposable Docker container
python3 tools/ci_baseline.py --runtime podman            # rootless Podman alternative
python3 tools/ci_baseline.py --runtime podman --filter CheckerSelfTests
PYTHONPATH=tests python3 -m unittest test_ci_baseline -v
```

When approving a new stack, update `HYPRLAND_SERIES` and the baseline JSON together. Verify the
dated archive actually contains the selected exact Hyprland package and coherent dependencies,
resolve and verify the official bootstrap image digest, then run the native job in full. Merely
changing the series or using an individual old package with newest libraries is not sufficient.

`.github/workflows/keybindings-forward.yml` separately checks **latest Arch** on pull requests,
weekly and on demand. Its `forward compatibility (non-blocking)` job reports upstream drift
without blocking approved releases; it is not called by Auto Release and must not be a required
branch-protection check. Its rejection assertions are intentionally unchanged: a changed upstream
diagnostic remains visible rather than being hidden to make the approved gate green.

`auto-release.yml` calls this workflow and its version bump `needs` it, so every automatic release
waits for both jobs and a failing shortcut stops the release. Fix it and push, or re-run the failed
jobs if it was a mirror hiccup (`gh run rerun <id> --failed`); the release goes out once they pass.
Marking both jobs as required status checks in the branch protection rules for `main` would also
keep a failing pull request from merging; the workflow has no path filter, so a required check
never sits pending. The lab is the one check left to run by hand before a release.

---

## Adding a Settings Entry

The start menu has a **Settings** category. Each entry there launches a system tool -- Appearance opens the theme picker, Audio opens an installed mixer, etc. Here's how to add a new one.

Audio prefers `pavucontrol`, `pwvucontrol`, `pavucontrol-qt`, `qasmixer`, then
`alsamixergui`. Without a graphical mixer, it opens `wiremix`, `pulsemixer`,
`ncpamixer`, `pamix`, or finally `alsamixer` through `terminal -e`.
No package installation or audio configuration changes happen on launch.
ALSA mixers expose hardware controls such as microphone boost; PipeWire and
PulseAudio mixers additionally expose device and application-stream routing.
Missing mixers or a missing terminal launcher produce an actionable error;
a selected tool's launch/runtime failure is not concealed by opening another.
Focused headless checks: `python -m unittest discover -s tests -p 'test_audio_settings.py' -v`.

Searching for Volume, Sound, Speakers, Output Device or Input Device and
right-clicking the bar's volume icon use this same Audio dispatcher. The aliases
are search-only; Audio remains the browsable Settings entry. Normal Update OS
syncs both scripts and the EWW widget, then rebuilds the app cache.

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
    command -v my-tui &>/dev/null && term my-tui
    die "my-tui not found"
    ;;
```

`term` is a shell function that execs `terminal -e`; do not write `exec term`.
Display's Wayland `wlr-randr`, Network's `nmtui` and Bluetooth's `bluetuith`
fallbacks use this helper when their preferred graphical tool is unavailable.

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
