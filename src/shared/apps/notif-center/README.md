# notif-center (Rust + Slint)

Notification center application for smplOS.

## Build

From this directory:

- `cargo build`
- `cargo run`

## Backend actions

- Fetch: `dunstctl history`
- Dismiss one: `dunstctl history-rm <id>`
- Clear all: `dunstctl history-clear`
- Open: `gtk-launch <desktop_entry>` fallback to app name command
- Summary actions:
	- `System Update` → `smplos-update`
	- `Web App Launch Error` → open `~/.cache/smplos/launch-webapp.log` via `xdg-open`

## Theme source

Reads EWW theme variables from:

- `~/.config/eww/theme-colors.scss`

Supported variables:

- `$theme-bg`
- `$theme-fg`
- `$theme-accent`
- `$theme-bg-light`
- `$theme-bg-lighter`
- `$theme-red`
- `$theme-green`
- `$theme-yellow`
- `$theme-cyan`
- `$theme-popup-opacity`
