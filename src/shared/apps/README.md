# smpl-apps

Rust GUI apps for [smplOS](https://github.com/smpl-os/smplos).

All apps use [Slint](https://slint.dev) with the software renderer + Winit/Wayland backend for composited transparency.

| App | Description |
|-----|-------------|
| `start-menu` | App launcher |
| `notif-center` | Notification center |
| `settings` | Settings panel |
| `app-center` | Package manager UI |
| `webapp-center` | Web-app manager |
| `sync-center` | File sync & backup |

## Building

```bash
cargo build --release --workspace
```

Requires Arch Linux (or equivalent) with: `fontconfig freetype2 libxkbcommon wayland gtk4 gtk4-layer-shell libadwaita`

## Releases

Pre-built binaries are published to [Releases](../../releases) and consumed by the smplOS ISO builder.

```bash
# Download all binaries for the ISO build:
curl -fSL https://github.com/smpl-os/smpl-apps/releases/latest/download/smpl-apps-x86_64.tar.gz \
  | tar -xz -C ~/.cache/smpl-apps/
```
