# Macro keypads (CH552) in smplOS

Status: **implemented, flashing is a dry run.** The keypad daemon lives in
`smpl-os/smpl-apps` (`control-surface/`) and is released with the apps; smplOS
installs it as the `control-surface` package. The daemon has since delivered the Settings API that this design asked for
(`org.smplos.ControlSurface1`, see its `docs/dbus-settings-api.md`); Settings
already uses its live input, identify mode, feature list and Kdenlive catalog.
See [open decisions](#open-decisions) and the
[daemon API requests](#daemon-api-requests).

smplOS supports the family of cheap CH552 macro keypads (3 to 16 keys, 0 to 3
knobs; USB `1189:8890`). Plug one in and:

* it works: udev starts the keypad app (`control-surfaced`), which applies your
  mapping. Unplug it and the app stops again. **With no keypad plugged in,
  nothing keypad related runs** (see [footprint](#lifecycle-and-footprint));
* a keypad icon appears in the EWW bar while it is connected. Click it to open
  **Settings → Keypad**;
* Settings maps keys and knobs at three levels:
  1. **Generic mapping:** keyboard shortcuts, media keys, commands, and mouse
     buttons once the daemon supports them.
  2. **Per-app profiles:** while an app has focus, its own mapping applies;
     unset controls fall back to Global.
  3. **API plugins:** apps with a real control API are driven through it, not
     through fake keystrokes. Kdenlive is first, over its D-Bus
     `org.kde.kdenlive.ControlSurface1` interface. Plugins are code in the
     daemon, not key remaps.
* a step-by-step wizard installs the open firmware: unplug, hold the top-left
  key, plug in, flash, replug, test every input.

## Which keypads work

Only **CH552-based macro keypads with USB ID `1189:8890`**: the inexpensive
"MINI KeyBoard"-style pads sold under many names, with 3 to 16 keys and up to 3
knobs, usually configured on Windows with a "MINI KeyBoard" vendor app. To tell
whether yours is one, plug it in and open **Settings → Keypad**: a supported
keypad shows as connected (and the bar shows the keypad icon). In a terminal:

```bash
keypad-ctl present && echo "supported keypad connected"
# or, with usbutils installed (not part of smplOS by default):
lsusb -d 1189:8890
```

`lsusb` lists it as `1189:8890` (vendor "Acer Communications & Multimedia" in
the USB ID database; the product name varies). The ID is what counts. Pads with other IDs
(for example the CH57x-based `1189:8840`/`8842` boards, QMK/VIA keypads or
Stream Deck-style devices) are not handled and don't appear in Settings. The
Settings tab states this at the top and links here.


### The keypad registry

`src/shared/keypads/registry.json` lists every keypad family smplOS knows,
with USB vendor and product IDs, a `status` and its backend:

* `supported` (the CH552 pads, backend `control-surface`): udev grants the
  seated user access, tags the device for systemd under the one alias
  `/smplos/keypad` (`smplos-keypad.device`, "a supported keypad is present")
  and starts the backend's user service. The bar shows the icon while it
  runs.
* `planned` (Elgato Stream Deck, vendor `0fd9`, no backend yet): nothing
  happens on plug-in, no access, no service, no icon. `keypad-ctl status`
  lists it under `planned`; Settings names it in its scope note.
* `bootloaders`: the ROM bootloaders, which only get `uaccess` for flashing.

`python3 src/shared/keypads/gen.py --apps <smpl-apps>` regenerates
`70-smplos-keypads.rules`, the IDs block in `keypad-ctl` and Settings'
`settings/src/keypad/registry.rs`; `--check` fails when one is stale (a test
runs it). A second backend will get its own alias next to `/smplos/keypad`
so each service binds to its own devices.

## Architecture

```mermaid
flowchart LR
  pad["CH552 keypad\n1189:8890"] -- "udev: uaccess, smplos-keypad.device,\nSYSTEMD_USER_WANTS" --> unit["control-surface.service\n(BindsTo the device)"]
  unit --> daemon["control-surfaced\n(control-surface repo)"]
  unit -- "ExecStartPost / ExecStopPost:\neww update keypad-present" --> eww["EWW tray icon"]
  sync["scripts/keypad-bar-sync.sh\n(eww deflisten, bar open/reload)"] -- "once: is-active?" --> eww
  daemon -- "evdev grab" --> pad
  daemon -- "uinput keys" --> desktop[Focused app]
  daemon -- "D-Bus ControlSurface1" --> kdenlive[Kdenlive]
  hypr[Hyprland IPC] -- focused window --> daemon
  cfg["~/.config/control-surface/config.jsonc"] -- hot reload --> daemon
  eww -- click --> settings["Settings > Keypad\n(smpl-apps)"]
  settings -- "sysfs scan (while open)" --> pad
  settings -- "check-config, example-config,\nfeatures, list-actions" --> daemon
  daemon -- "D-Bus InputEvent, GetLayout\n(SetIdentify held)" --> settings
  settings -- "validated write + backup" --> cfg
  settings -- "firmware flash (dry run)" --> ctl["keypad-ctl\n(on demand)"]
  ctl -- "wchisp info / flash" --> loader["WCH ROM bootloader\n4348:55e0"]
```

| Piece | Lives in | Role |
|---|---|---|
| `control-surfaced` | control-surface repository (separate) | Grabs only `1189:8890`, follows the focused window, applies JSONC profiles, Kdenlive plugin |
| Open firmware | control-surface `firmware/` (fork of CH552-OpenMacroPad, CC BY-SA 3.0) | Self-describing keypad firmware, same VID:PID |
| `keypad-ctl` | `src/shared/bin/keypad-ctl` | On-demand tool: detection (`status`, `present`) and firmware list and flash. Never runs in the background |
| Keypad registry | `src/shared/keypads/registry.json`, `gen.py` | The one list of keypads (supported or planned) and bootloaders; generates the udev rules, `keypad-ctl`'s IDs and Settings' IDs and scope text |
| udev rules | `src/shared/system/udev/70-smplos-keypads.rules` (generated) | Access, the `smplos-keypad.device` unit, start on plug-in |
| User unit | `src/shared/configs/systemd/user/control-surface.service` | Runs the keypad app only while a keypad is plugged in; sets the bar icon |
| Bar icon | `src/shared/eww/eww.yuck` (`keypad-present`, `tray-keypad`), `scripts/keypad-bar-sync.sh`, `icons/status/keypad.svg` | Visible only while the keypad app runs |
| Settings tab | smpl-apps `settings/src/keypad/`, `settings/ui/main.slint` (tab 11) | Status, layout, mapping editor, firmware wizard |
| Packaging | `src/shared/pkgbuilds/control-surface/`, `packages-aur.txt` (`wchisp`) | The daemon (a pinned smpl-apps release asset) and the flasher |
| Migration | `migrations/20261007-123000-macro-keypad-support.sh` | Existing installs: udev rules, icon, unit (never enabled) |

Settings code lives in smpl-apps, like every native app. This repository
carries the system integration only, and never vendors the daemon's source.

## Detection and firmware identity

Detection reads sysfs attributes only (`/sys/bus/usb/devices`): it never opens
a keypad and never touches any other device. Settings does it itself while its
Keypad tab is open; `keypad-ctl status` does the same for scripts:

```json
{"state":"ready",
 "devices":[{"path":"1-5","vid":"1189","pid":"8890","manufacturer":"OpenMacroPad",
   "product":"Control Surface 15+3","serial":"key153","bcd":"0200","firmware":"open",
   "firmware_type":"control-surface","firmware_label":"Open firmware (control-surface)",
   "layout":{"board":"sy181-15k3e","keys":15,"knobs":3}}],
 "bootloaders":[]}
```

The rules are the daemon's own (`usbinfo.cpp`):

| Firmware (daemon name) | How it's recognized | Layout |
|---|---|---|
| `control-surface` (ours) | manufacturer `OpenMacroPad`, product `Control Surface K+N` | Self-described: `K+N` in the product string (`15+3` is `sy181-15k3e`); version from bcdDevice |
| `openmacropad` | manufacturer `SY181` (EpicLPer's builds) | Chosen in Settings |
| `stock` | manufacturer `wch.cn` (product `CH552`) | Chosen in Settings |
| `unknown` | any other `1189:8890` | Chosen in Settings |

bcdDevice carries major and minor only, so sysfs says 2.0 for firmware 2.0.1.
Settings shows the full version from the running keypad app (`GetDevice`,
read over HID); `control-surfaced firmware-info` reads it too.

The WCH ROM bootloader (`4348:55e0`; newer WCH parts use `1a86:55e0`) is
detected by the firmware wizard only. The bar doesn't show it.

## Lifecycle and footprint

smplOS stays light, so the keypad support adds **no always-on process**. With
no keypad plugged in, nothing keypad related runs: no watcher, no listener, no
daemon. Everything is driven by the device:

1. **Plug in.** `70-smplos-keypads.rules` matches the USB device `1189:8890`
   only. It tags it `systemd` and gives it `SYSTEMD_ALIAS=/smplos/keypad`, so
   the user manager tracks it as `smplos-keypad.device`
   (`systemd-escape --path --suffix=device /smplos/keypad`).
   `SYSTEMD_USER_WANTS=control-surface.service` starts the keypad app when that
   device appears.
2. **Running.** `control-surface.service` has `BindsTo=smplos-keypad.device`
   and `After=smplos-keypad.device`. `ExecStartPost` runs
   `eww update keypad-present=yes`, and the bar shows the icon.
3. **Unplug.** The device unit goes away, `BindsTo=` stops the service, and
   `ExecStopPost` runs `eww update keypad-present=no`.

The unit has no `[Install]` section and is never enabled for a target. udev is
the only thing that starts it (Settings' Start button and the login step below
only act while a keypad is present).

Two one-shot checks cover the cases the events can't:

* **Bar starts or reloads after the keypad app** (login with the keypad already
  plugged in, `theme-set`'s reload, which resets EWW variables):
  `keypad-present` is a `deflisten` of `scripts/keypad-bar-sync.sh`, which
  prints `systemctl --user is-active control-surface.service` once and exits
  (after 2 s, so EWW reads the line first). EWW runs it when the bar opens or
  reloads and never restarts a script that ended; `eww update` from the unit
  overrides it. Nothing polls, and `bar-ctl` has nothing keypad related.
* **Keypad plugged in before login.** udev starts the app when the user manager
  comes up, before the session's environment is imported. At login,
  `smplos-session-services` restarts it once, only if `smplos-keypad.device` is
  active, so `command` bindings run in the session.

`ExecStartPost`/`ExecStopPost` are `-` prefixed: with no bar running, `eww
update` fails in about a second and never starts an EWW daemon.

Measured on the development machine:

| | Processes | Memory |
|---|---|---|
| No keypad plugged in | **0** | 0 |
| Keypad plugged in | 1 (`control-surfaced`) | about 5.5–5.9 MB RSS, almost all shared library pages (320 kB or less anonymous) |
| For comparison, the first draft (EWW `deflisten` → `keypad-ctl watch` + `udevadm monitor`) | 2, on every machine | about 31.9 MB RSS |

The "no keypad" row was measured by starting the bar config on a private Xvfb
display and listing the EWW daemon's descendants: the old config started
`keypad-ctl watch` (25.4 MB) and `udevadm monitor` (6.4 MB); the new one starts
no keypad processes.

Access rules, in the same file, apply to `1189:8890` only:

* `TAG+="uaccess"` on the USB device and its `hidraw` and `input` nodes, so the
  seat user's keypad app reads the keypad without the `input` group;
* `uaccess` on `/dev/uinput`, because the app types through one virtual
  keyboard (Steam's and xr-workspace's rules make the same grant).

The same generated file grants `uaccess` on the ROM bootloaders only.

With two keypads plugged in, both carry the same alias; unplugging one may stop
the app until the other is replugged. The app drives one keypad anyway.

## Bar icon

`(defvar keypad-present "no")`; `tray-keypad` is visible only while it is
`"yes"`. The unit and `bar-ctl` set it as described above. Clicking the icon
runs `smplos-settings keypad`, which opens `settings --tab keypad`. There is no
bootloader icon: the firmware wizard detects update mode itself.

## Cheatsheet overlay

A key or knob press mapped to `{"cheatsheet": "toggle"}` (or `"hold"`: shown
while held) shows what every key and knob does right now: the focused app's
profile, Kdenlive's context layers and mode states. It follows focus changes
while shown, and hides itself after 8 s without keypad input unless the config
says otherwise (a held "hold" key keeps it up).

It follows the same rule as the bar icon: **no listener process**. The daemon
pushes its content into the running EWW, and only while it runs, which is only
while a keypad is plugged in:

* `(defvar pad_sheet '{"visible":false}')` holds the daemon's cheatsheet JSON
  (`GetCheatsheet`; see its `docs/dbus-settings-api.md`).
* On show, change and hide the daemon runs `eww update pad_sheet=…`. On show
  and hide it also runs `eww open WINDOW --anchor …` and `eww close WINDOW`;
  a failed update skips the open, so the daemon never starts an EWW.
* `pad-cheatsheet` is an `overlay` layer surface (namespace
  `eww-pad-cheatsheet`, not focusable, blurred like the other EWW popups). It
  is sized to its content and anchored by the `position` option.
* Keys sit in their real rows and columns; each knob lists turn left, press and
  turn right. State is shown by shape: a solid border means the binding does
  something now; a dashed border with dim text means it would do nothing now
  (for example, Kdenlive's interface is off, explained in a notice line); no
  border and a dot means unbound.

**See-through, never faded text.** Only the background is translucent: the
`opacity` option picks `.pad-sheet.o1` to `.o20` (5% steps) on the background
box, the overlay's only translucent color. Text, key borders and the outline
stay fully opaque, with a halo in the background color so labels stay legible
over anything. Without an `opacity` in the content, EWW falls back to 0.35.
Hyprland blurs what's behind it (`blur on`, `ignore_alpha 0.1` so the clear
rounded corners aren't blurred, `xray off`); no layer rule changes its alpha.
Measured on a private X server with an RGBA visual: background alpha 0.349 at
0.35 (0.851 at the old 0.85 default, which looked solid), text and borders
1.0.

**Dismissing it.** The overlay never takes keyboard focus, so a click is the
way to close it:

* A click anywhere on `pad-cheatsheet` runs `scripts/pad-sheet-hide.sh`
  from the EWW config (EWW runs commands there, so it ships with the overlay
  and needs nothing else on `PATH`). It calls the daemon's `HideCheatsheet`;
  if no daemon answers within 2 s it runs
  `eww close pad-cheatsheet pad-cheatsheet-passthrough` on its own EWW config
  and sets `pad_sheet` to hidden itself. A "Click to close" line says so.
* Unless a hold key holds it, the daemon hides the sheet after `autoHideMs`
  without pad input. Unset means 8 s (daemon 738e334 and newer); 0 means until
  hidden. That covers toggle keys and the `ShowCheatsheet` D-Bus call.
* Settings' **Show on screen** hides the sheet itself after 8 s when the saved
  setting is "until hidden", so a preview never stays up.
* The cheatsheet key itself (toggle) hides it.

**Click-through (optional, off by default).** `pad-cheatsheet-passthrough` is
the same overlay with `:passthrough true`, an EWW property of the smplOS
fork (`smpl-os/eww` 0eb4604, in `eww-smplos` since pkgrel 2; an empty input
region: the XShape input region on X11, `wl_surface.set_input_region` on
Wayland). **Verified on X11 only; Wayland is pending.** Clicks
reach the window below, so its hint reads "Hides after N s or with your
cheatsheet key" instead. Settings' **Click-through overlay** toggle sets
`"cheatsheet": {"eww": {"window": "pad-cheatsheet-passthrough"}}`. The daemon
closes the old window when that changes. Settings never combines it with
"until hidden". An EWW without it only warns about the unknown property and
keeps the window clickable. Migration `20261008-120000-eww-smplos-passthrough`
rebuilds an older eww-smplos; the running bar keeps the old binary until the
next login.

### Icons

Every key and knob action on the overlay shows an **outline icon**, large,
with its label under it in small type; knob lines start with outline
turn-left, press and turn-right marks. All icons come from one outline set,
so they look alike, and are drawn as text in the theme's accent: fully
opaque, recoloured by the theme like any label.

* **Set:** [Tabler Icons](https://tabler.io/icons) 3.49.0, outline style
  (MIT, copyright Paweł Kuna). `src/shared/fonts/keypad-icons/icons.txt` lists
  the 256 icons smplOS bundles, by category; `build.py` there downloads the
  pinned npm packages (checked by sha256), subsets the outline font to them
  and writes everything below. The outputs are committed, so builds need
  neither the network nor fontTools:
  * `src/shared/fonts/smplos-keypad-icons.ttf`: family "smplOS Keypad Icons"
    (70 KB);
  * `src/shared/fonts/keypad-icons.json`: name, codepoint, category, tags;
  * `src/shared/eww/pad-icons.yuck`: `(defvar pad_icons '{name: glyph}')`;
  * `src/shared/fonts/keypad-icons/LICENSE-tabler-icons.txt`, installed beside
    the font;
  * with `--apps DIR`, the same font, JSON and licence for Settings
    (smpl-apps `settings/ui/assets/`). Regenerate both repositories together.
* **Names:** the keypad app's `"icon"` per key and knob event is a Tabler
  name (`player-play`, `brand-github`, `folder`). A binding may set
  `"icon": "player-play"` or `"icon": "none"`; without it the keypad app picks
  one automatically. The overlay looks the name up in `pad_icons`. An empty or
  unknown name shows the label alone. The keypad app has done this since
  a920ddd (R11). `daemon-auto.txt` pins its `features.cheatsheet.icons.auto`
  (121 names as of af559d1), and a test fails unless `icons.txt`
  covers them all; with a keypad app on `PATH` (or `SMPLOS_CONTROL_SURFACED`)
  the test checks its live list too. A daemon update that adds automatic
  icons means: add them to `icons.txt`, run `build.py --apps …`, refresh
  `daemon-auto.txt`.
* **Font delivery:** `~/.local/share/fonts/smplos/`, from the ISO's skel,
  `install.sh` and `smplos-os-update` (which runs `fc-cache` when the font
  changes). EWW finds it by family name. A running EWW never sees a font
  installed after it started, and other fonts would draw wrong glyphs for its
  codepoints. So the overlay draws icons only when `pad_icons_font` is `yes`.
  The bar's one-shot `keypad-bar-sync.sh` sets that when the bar opens or
  reloads, if the font file is older than the EWW daemon; until then the overlay shows labels and `< o >`.
  Nothing polls.

Settings (Keypad → Cheatsheet) edits the config's
`"cheatsheet": {"opacity", "autoHideMs", "position"}` and the click-through
window, and keeps any other key there. Options the config leaves out show
what the daemon uses (its `features`). It also adds:

* **Show the cheatsheet** as a binding kind, with Toggle and Hold modes. It is
  offered only for keys and knob presses, and only when the installed daemon's
  `features --json` lists cheatsheet support.
* a **Sheet label** for every binding (the binding's `"label"`, at most 40
  characters). Short forms become objects when a label is set, such as
  `{"keys": "ctrl+z", "label": "Undo"}`. Fields Settings doesn't edit, like a
  Kdenlive action's `fallback`, are kept.
* an **Icon** for every binding that has a label: "Automatic" (no `"icon"`;
  the row names what the keypad app chose, from the preview), "No icon"
  (`"none"`), or one picked from a searchable grid of the bundled outline icons
  (name first, then Tabler's tags: "git" finds the GitHub icons). Settings
  embeds the same font, and shows the icons in the layout, the binding list
  and the preview. With a keypad app that doesn't draw icons yet
  (`features` has no `cheatsheet.icons`), Settings says that chosen icons are
  saved for later; that app ignores the field.
* a **live preview** of the selected profile, including unsaved edits. It runs
  `control-surfaced cheatsheet --json --window CLASS -c COPY` on a temporary
  copy next to the config and falls back to the running app's
  `GetCheatsheetFor`. Kdenlive profiles have a "Preview in" context picker
  (timeline, monitors, colour wheels, effect parameter).
* **Show on screen**, which calls the running app's `ShowCheatsheet` (it uses
  the saved config) and takes the sheet down after 8 s if the saved setting
  is "until hidden".

The unit turns the push on with
`ExecStart=/usr/bin/control-surfaced run --quiet --eww-window pad-cheatsheet --eww-config %h/.config/eww`
(daemon b83980e or newer; the PKGBUILD refuses older sources). The daemon opens
the window with `--anchor` from the `position` option and reopens it when the
position changes. A keypad app started by hand without those flags doesn't
push; Settings' **Show on screen** says so (it reads `GetStatus().cheatsheet.eww`).
The config can still override the flags: `"cheatsheet": {"eww": false}` turns
the push off.

## Settings > Keypad

```mermaid
flowchart TD
  open[Open tab] --> status["Scope note, device card (sysfs),\nkeypad app state + Start, variant"]
  status --> layout["Layout: keys grid + knobs,\nbinding summaries"]
  layout -- "click, or press on the keypad\n(Press to identify)" --> select[Selected control / knob event]
  select --> editor["Action: Not set, Do nothing, Shortcut,\nMedia key, Mouse*, Command, Kdenlive action*"]
  editor -- "Apply to control" --> dirty[In-memory config, Unsaved]
  profiles["Profile: Global, app profiles,\nAdd app (running windows), Remove,\nwindow class, API plugin"] --> select
  dirty -- Save --> validate{"Settings' own checks, then\ncontrol-surfaced check-config\non a temp file in the same dir"}
  validate -- invalid --> err["'Not saved: <daemon message>'\nfile untouched"]
  validate -- ok --> write["backup to backups/config-<time>-NNN.jsonc\n(keep 10), atomic rename"]
  write --> reload[Daemon hot-reloads]
```

\* Mouse buttons appear once the installed daemon accepts a `{"mouse": ...}`
binding. Settings asks `check-config` once, with a probe file. Kdenlive actions
appear in profiles with the Kdenlive plugin on.

* **Scope.** The top of the tab says which keypads are supported and links to
  [Which keypads work](#which-keypads-work).
* **Keypad and app status.** The device card shows what sysfs reports: whether
  a CH552 keypad is plugged in, its firmware and version. Under it is the
  keypad app's state, from all of: the session bus name
  `org.smplos.ControlSurface`, a `control-surfaced run` process, and
  `control-surface.service`'s state (the process is matched by `argv[0]`, as
  `/proc/PID/comm` holds only 15 characters). So an app started by hand shows
  as "running (started outside systemd)". With the app on the bus, the firmware
  version is the full one from the keypad (`2.0.1`), else bcdDevice's (`2.0`). **Start** (`systemctl --user start
  control-surface.service`) appears only when a keypad is plugged in and the
  app isn't running. A missing package, a failed unit or a missing unit each
  get their own message.
* **Variant.** A keypad with our firmware names its layout; the tab shows it as
  "Detected from the keypad", read-only, with **Override…**. For other
  firmware, a dropdown lists the daemon's board profiles (`features --json`,
  else the built-in list): `sy181-15k3e`, `generic-3k`, `generic-3k1e`,
  `generic-6k1e`, `generic-10k`, `generic-12k2e`, `generic-12k3e`,
  `generic-16k3e`. Each entry has a small schematic. **Custom…** sets keys
  (1–16), knobs (0–3) and columns (1–8). The choice is the config's
  `"layout"` (`"generic-12k2e"` or `{"keys", "knobs", "columns"}`); "Automatic"
  removes it. The config's layout wins over a self-described one (daemon
  ebeabe8 or newer); with an older keypad app the tab says the override has no
  effect yet. A custom grid may have 0 keys when it has knobs; without
  `"columns"` the daemon uses 5 columns for 10 or more keys, else up to 4.
* **Config source.** The file is `~/.config/control-surface/config.jsonc`
  (`$XDG_CONFIG_HOME` if set). With no file, Settings shows the daemon's
  built-in example (`control-surfaced example-config`), because that is what
  the daemon runs. Without the daemon, Settings shows a minimal Global profile.
  The first Save creates the file.
* **What Settings edits.** Base bindings of a profile, in the simple forms:
  `"ctrl+z"`, `"playpause"`, `"none"`, `{"command": [...]}`,
  `{"action": "mark_in"}`, `{"mouse": "left"}`, `{"cheatsheet": "hold"}`, each
  with an optional `"label"`, `"icon"` and `"ifInstalled"` ("Only if
  installed": programs or app ids, a string or a list as the file had it).
  It also edits the profile header: name, `match.class`, `match.title`
  (optional window-title pattern), `fallthrough` ("unset controls use
  Global"), `kdenlive` and `keyFallback`. It adds and removes app profiles;
  they go before Global, because the first match wins.
* **Advanced** (collapsed card), for what users otherwise edited by hand:
  * **Input mode:** Automatic, Keymap (compatible) or Raw (fastest, firmware
    2.0.2+), saved as `device.input` (`auto`, `evdev`, `raw`; Automatic
    adds no key). Under it:
    * a check mark, or an exclamation mark when raw input lost events it
      couldn't restore or dropped out of raw mode;
    * the mode in use (`GetStatus().input.mode`);
    * a health line from its counters since the app started: events, lost
      and restored, raw-mode drops, late heartbeats.

    When raw was chosen but the keymap is in use, the line says why: the
    stock firmware, firmware older than 2.0.2 (`GetStatus` has the full
    version), a layout that doesn't match the firmware (the config's
    `layout:` warning), or not saved yet. The keypad app switches modes on
    reload, without a restart.
  * **Knobs:** acceleration (`accelFactor`, 1 = off), fast-turn window
    (`accelWindowMs`) and key rate (`keyRateHz`).
  * **Kdenlive (API plugin):** update spacing (`coalesceMs`), answer timeout
    (`ackTimeoutMs`) and edit gesture (`gestureIdleMs`, 50–590 like the
    daemon). These are sliders over the config's `"settings"`, showing the
    keypad app's built-in defaults when unset; Reset to defaults removes them.
  * **Overlay switch:** "Draw the cheatsheet overlay through the bar"
    (`cheatsheet.eww`: off writes `false`, or `"enabled": false` beside a
    click-through window).
  * **Straight to the keypad app.** When the keypad app is on the bus with
    `SetOption` (control-surface c266f02) and runs on the same file
    (`GetStatus().config.path`), the simple options apply at once, without
    Save:
    * `input`;
    * `cheatsheet.opacity`, `cheatsheet.autoHideMs`, `cheatsheet.position`
      and `cheatsheet.eww`;
    * `settings.accelFactor`, `settings.accelWindowMs` and
      `settings.keyRateHz`.

    The keypad app changes that one value in place, keeps comments, writes
    `.bak`, validates the whole file and applies it; sliders send once a
    drag pauses. Everything else keeps the file path and Save: options it
    doesn't list (`features.options`), click-through (a window name), the
    Kdenlive timings, an older keypad app or none. A refused value stays an
    unsaved change with the keypad app's reason. The file `SetOption` wrote
    becomes Save's baseline, so Save still refuses to overwrite someone
    else's edit.
* **What Settings keeps.** Everything else is kept verbatim, in its key order
  and number spelling: layers, modes, continuous controls with their `scale`
  and `accel`, cycles, requests, hardware and unknown keys. Such bindings show
  as "Advanced (edit in file)". Applying a binding keeps the file's key order,
  so an unchanged binding is written back byte for byte. A custom auto-hide
  value shows as itself in the Hide list. Comments are not kept, but the
  previous file is backed up first. `device.serial` stays in the file: every
  pad of this family reports the same serial (`key153`), so there is nothing
  to choose.
* **Knobs.** Knobs offer Turn left, Turn right and Press. Setting left or right
  removes the knob's continuous `turn` at that level, which would otherwise win,
  and says so. "Turn while pressed" (`shift`) bindings are shown, but marked:
  the firmware ignores turns while a knob is pressed, so they never fire, and
  they delay that knob's press until release. Settings flags them in the
  binding list with "!" and "never fires", and explains them per profile
  (own bindings and layers) with **Remove them**. This holds while
  `features --json` reports `slots.shiftSupported: false` or nothing. On
  knobs 1 and 2 of this pad, press-and-turn is physically impossible
  (pressing pins an encoder line), so holding a key replaces it (next
  point).
* **While holding a key.** With a keypad app that has held layers
  (`features.heldLayers`), a profile can have layers that apply while a key
  (or knob press) is held. They are written as `"when": {"held": "key1"}`.
  `"held"` is a condition like any other (control-surface d78e2bf): layers
  apply in list order, and the first matching one that maps an input wins,
  then the profile's own bindings, then Global's. So Global's held layers
  cover only what an app profile leaves unbound.
  * **Layer list:** "Normal (no key held)" plus one entry per held layer.
    **Hold a key…** then a click on the layout, or a press while
    identifying, adds the layer for that key, or opens the one there is.
  * **Editing:** the editor, binding list and layout show that layer. The
    held control reads "held" and can't be mapped in its own layer.
    Controls left unset do what the next layer or their normal binding
    says. The cheatsheet preview asks the keypad app with `"$held"` in its
    context. On the normal layout, controls that have layers carry a small
    outline hand (an app profile's layout marks Global's too).
  * **Order:** a new held layer goes before the profile's context layers,
    after any held layers already at the top. The layer note names layers
    listed before it, which win where they map the same input while
    active, and offers **Move first**.
  * **What this pad can hold:** key 1 has its own pin; keys 2–15 and the
    knob presses go through the TM1650, which reads one at a time (the
    layout's `oneAtATime`). So only a layer held on key 1 combines with
    every other key; one held on key 5 takes key 1 and the knob turns.
    **Hold a key…** marks and recommends key 1. In a layer held on another
    key, the keys that can't fire read "can't, held", with an editor hint
    and a layer note. Settings runs `check-config --json` on the config as
    edited (a temporary copy, only when it changed) and shows its warnings
    on the binding rows and layers they name.
  * **Converting shift bindings:** **Convert** moves turn-while-pressed
    bindings into "turn while holding key N" (Key 1 by default). A context
    layer's bindings (for example Kdenlive's timeline) go to a held layer
    with the same conditions, listed first: it is the more specific one.
    Knobs the target layer maps already keep theirs, and Settings says so.
  * **Hand-written forms:** alternatives (`["key1", "key13"]`), chords
    (`"key1+knob3"`) and extra conditions are shown with a readable title
    and kept as written.
* **Kdenlive plugin.** "API plugin: Kdenlive (D-Bus API)" sets
  `"kdenlive": true`. "Load recommended layout" copies the Kdenlive profile,
  with its context layers, from the daemon's example. A toggle maps
  `keyFallback`, which types plain shortcuts while Kdenlive's interface is off.
  The action list comes from a running Kdenlive (`list-capabilities --json`),
  or from a built-in copy of the curated contract.
* **Press to identify.** Pressing a key or turning a knob selects it, and the
  control flashes. Settings only listens to the daemon's `InputEvent` signal;
  it never opens the keypad. While identifying (and during the wizard's input
  test) it holds `SetIdentify(true)` on one long-lived bus connection, so
  mapped actions are paused. Leaving the tab or closing Settings ends it; the
  daemon also ends it when that connection closes. Without the keypad app on
  the bus, the tab says live input needs it running.
* **Limits and catalogs.** `control-surfaced features --json` gives the
  addressable keys and knobs (16 and 3 today) and whether mouse bindings exist.
  Older daemons fall back to 15 keys, 3 knobs and a `check-config` probe.
  Kdenlive actions come from a running Kdenlive, else `list-actions --json`,
  else a built-in copy.
* **Concurrent edits.** Save refuses to overwrite a file that changed on disk
  since Settings read it, and asks you to Revert first.

## Firmware wizard

The stock firmware can't be read out, so it can't be backed up. Flashing is
one-way. The ROM bootloader can't be erased, so the keypad can always be
reflashed.

| Step | Waits for | Notes |
|---|---|---|
| 1 Before you start | Toggle: "I understand that the stock firmware can't be restored" | Explains stock vs open, the license, and dry-run mode |
| 2 Choose the firmware | An image whose manifest checksum matches | Lists `/usr/share/control-surface/firmware/*.bin` and `~/.local/share/control-surface/firmware/*.bin` with `<name>.json` manifests |
| 3 Unplug | No keypad and no bootloader | Moves on by itself |
| 4 Enter update mode | Exactly one `4348:55e0` | "Hold the top-left key (P1.5) while plugging in"; tells you if the keypad booted normally instead |
| 5 Flash | `keypad-ctl firmware flash IMAGE --json` succeeding | Streams preflight, chip, erase, program, verify, done |
| 6 Plug it back in | A keypad and no bootloader | Shows the detected firmware |
| 7 Test every input | Each key, and each knob's left, right and press | Check marks need live input (R1) |

`keypad-ctl firmware flash` checks the image exists, is `.bin`, is 1 to 14336
bytes (CH552 code flash) and matches its manifest's sha256. It requires exactly
one bootloader. The command is a **dry run by default**: it reports the steps
and runs nothing. With `--execute` it runs `wchisp info` and refuses unless the
chip is a CH552, then runs `wchisp flash IMAGE`, which erases, writes and
verifies. A single function is the only way to run wchisp. It allows only `info`
and `flash` and rejects every `--no-*` flag, so it never runs `config`,
`eeprom` or a flash without verify. Config registers are never written.

Settings passes `--execute` only when `SMPLOS_KEYPAD_REAL_FLASH=1` is set; it
shows a **Dry run** badge otherwise. Nothing in development touches the real
keypad or runs wchisp against hardware.

While the keypad app reads the pad raw it holds the firmware's raw session,
and its own flash-and-verify refuses to start. So from "Unplug the keypad"
on, the wizard switches the keypad app to Keymap input
(`SetOption("input", "evdev")`). It puts the previous mode back
(`auto` when unset) when the wizard closes or finishes. Without the keypad
app on the bus there is nothing to switch.

## Packaging

* **Daemon:** source, CI (CMake + ctest) and releases are in `smpl-os/smpl-apps`
  (`control-surface/`). Each smpl-apps release publishes
  `control-surface-<version>-x86_64.tar.gz`, a `usr/` tree with
  `/usr/bin/control-surfaced`, `/usr/bin/ch552-padprog`, the example config,
  docs, licences and the current firmware images with their manifests.
  `src/shared/pkgbuilds/control-surface/PKGBUILD` repackages one pinned
  release (`pkgver` = the smpl-apps version, `sha256sums` pinned; no
  `_gh_owner`/`_gh_repo`, so `build-iso.sh` doesn't move it to the latest
  release). `packages-aur.txt` puts it on the ISO; the keypad migration
  installs or updates it on existing installs (`src/shared/lib/smplos-pkgbuild.sh`,
  deferring with exit 75 when offline). To ship a newer daemon: bump `pkgver`
  and `sha256sums`, and add a migration that reruns that package step.
* **wchisp:** from the AUR (`wchisp` 0.3.0, GPL-2.0), listed in
  `packages-aur.txt` so the offline ISO carries it.
* **udev rules:** deployed by the generic udev step of `build.sh` and
  `install.sh`, and by the migration on existing installs, with a targeted
  `udevadm trigger` for connected keypads and `/dev/uinput`.
* **User unit:** copied to skel with the shared configs and never enabled. For
  existing users, `smplos-os-update`'s `sync_configs` adds it when it's missing
  (that step copies any file from `src/shared/configs` the user doesn't have).
  The migration installs or updates a unit an earlier smplOS draft installed
  (recognised by its `Documentation=` line) and removes that draft's
  `*.wants` link. A different unit of the same name, such as a developer's
  `install-user.sh` unit, is left alone.
* **Bar and scripts:** delivered by `smplos-os-update` (scripts, EWW config).
  The migration bakes the tray icon with the current theme's accent.
* **Settings tab:** ships in the next smpl-apps release. There is no new
  binary.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Where the UI lives | Settings tab in smpl-apps; system glue here | smplOS rule: app code only in smpl-apps; one settings app |
| Detection | sysfs strings only, with the daemon's rules; in Settings while it's open, and `keypad-ctl` on demand | No device I/O, so it's safe with the daemon's grab |
| Watcher | None. The unit sets an EWW variable on start/stop; a one-shot script checks once when the bar opens or reloads | Zero processes without a keypad (the first draft's watcher cost about 32 MB on every machine) |
| Supported devices | One registry (`src/shared/keypads/registry.json`) generates the udev rules, `keypad-ctl`'s IDs and Settings' IDs and scope text; `planned` devices (Elgato Stream Deck) get nothing until a backend exists | Adding a keypad family is a data change plus a backend; nothing can start or show an icon for a device the backend can't drive |
| Lifecycle | udev `SYSTEMD_USER_WANTS`, `SYSTEMD_ALIAS` and `BindsTo=` on the alias device unit | Starts on plug-in and stops on unplug, without a resident process |
| Variant | The config's `"layout"`, from the daemon's board profiles or a custom grid | One source of truth that the daemon reads; no smplOS-only override file |
| Access | `uaccess` for this VID:PID and `/dev/uinput` | No group membership; other keyboards untouched |
| Config format | Edit the daemon's JSONC directly | No second config; the daemon validates and hot-reloads |
| Validation | Settings' checks and `check-config` before writing; backup; atomic rename | An invalid file is never written; the old one is always recoverable |
| Comments | Dropped on save, previous file backed up (10 kept) | A comment-preserving JSONC editor is far more code for little gain |
| Flasher | wchisp through a two-command allowlist, dry run by default | Never touches config registers; nothing can flash by accident |
| Daemon packaging | Lives in smpl-apps (`control-surface/`, history kept); smplOS installs a pinned release asset with pacman | Built and tested once, by the apps' CI; the package owns `/usr/bin` and the firmware path keypad-ctl reads; not in the app bundle, which would also copy it to `/usr/local/bin` |
| Sidebar | "Keypad" right after "Keyboard"; tab index 11 | Related settings stay together; existing indices are unchanged |
| Cheatsheet look | 35% background with blur; text and borders opaque | Shows what's behind it without fading the labels |
| Dismissing the cheatsheet | Click anywhere, the 8 s auto-hide, or the key; no Escape | The overlay never takes keyboard focus, so it can't steal keys from the app |
| Click-through cheatsheet | Optional second window with EWW `:passthrough`, off by default | Hyprland 0.56 has no input-passthrough layer rule; clicking to close stays the simple default |
| Cheatsheet icons | Tabler Icons outline, subset to a 70 KB font, drawn as text | One consistent outline style, MIT, theme colour through CSS, opaque like labels; SVGs can't be recoloured by eww (`fill-svg` replaces fills, Tabler strokes) |
| Icon names | Tabler's names, no mapping layer | eww, Settings and the keypad app share one vocabulary |
| Font not yet seen by EWW | Labels only, flag set once when the bar opens | No misleading fallback glyphs and no bar restart from the updater |

## Open decisions

| # | Question | Recommended default |
|---|---|---|
| 1 | Public home of the daemon repository | Decided: `smpl-os/smpl-apps`, `control-surface/` (imported with its history); the PKGBUILD is unparked |
| 2 | When to enable real flashing | After firmware 2.0.0 passes on the user's keypad: default `--execute` on, keep the acknowledgement toggle |
| 3 | The bootloader leaves update mode after a few seconds | Add an "arm, then plug in" mode that flashes as soon as `4348:55e0` appears; decide after a real attempt |
| 4 | Bundle wchisp in every ISO | Yes (offline-first, small); the alternative is installing it on demand from the wizard |
| 5 | `uaccess` on `/dev/uinput` | Keep (same as Steam); the alternative is `input` group membership |
| 6 | Default mapping without a config | The daemon's built-in example (Kdenlive, FL Studio, Global media keys), because the daemon runs it anyway |
| 7 | Should a config `"layout"` override a self-described layout in the daemon? | Yes; done in the daemon (ebeabe8) |
| 8 | Ship EWW `:passthrough` | Done: `smpl-os/eww` master 0eb4604, `eww-smplos` pkgrel 2, migration `20261008-120000-eww-smplos-passthrough`. Verified on X11 only; confirm on Wayland (Hyprland) before relying on it there |
| 9 | Cheatsheet opacity default | 0.35 in the daemon (requested); Settings and EWW already show 0.35 when the daemon reports none |
| 10 | Brave and Kdenlive have no Tabler brand icon | `world` for browsers and `movie` for Kdenlive; revisit if Tabler adds them |
| 11 | Icons on installs updated while the bar runs | They appear after the next login or `bar-ctl start` with a fresh EWW; an explicit bar restart from the updater was rejected as risky |

## Daemon API requests

Sent to the keypad daemon's owner. R1 to R9 are in the daemon's source since
`5f420d0`; R10 is partly done. Settings works with older and newer daemons.

| # | Request | Daemon now | Settings |
|---|---|---|---|
| R1 | Live input and an identify mode that pauses actions | `InputEvent` signal, `SetIdentify(b)` (ends when the caller leaves the bus, 10-minute safety net), `monitor --json` | Uses the signal and holds `SetIdentify`. It doesn't use `monitor`, because without a daemon that command grabs the keypad itself |
| R2 | Machine-readable validation | `check-config --json`, `ValidateConfig` | Still parses the text form (works with old and new daemons); next step |
| R3 | Mouse bindings | `{"mouse": "left|right|middle|back|forward|wheel-up|wheel-down|wheel-left|wheel-right"}` | Offered when `features` lists mouse names |
| R4 | Layouts for the family | `key16`, `"layout"` in the config, built-in board profiles, `GetLayout` | Variant picker writes `"layout"`; limits from `features`; detected layout from sysfs or `GetLayout` |
| R5 | Any pad, raw-HID input | Empty `device.serial` drives the first pad; raw report-5 backend | Nothing to do |
| R6 | Start before the compositor, idle without a keypad | Waits for Hyprland, a valid config and uinput | Matches the udev start; the unit now also stops on unplug |
| R7 | Offline Kdenlive catalog | `list-actions --json`, `GetCatalog` | Used when no Kdenlive is running |
| R8 | Firmware delivery | Release images with metadata, `firmware-info`, `enter-bootloader`, `StartFlash` (dry run always; real flash only with `--allow-flash`) | The wizard still flashes through `keypad-ctl` (follow-up below) |
| R9 | Feature discovery | `features --json`, `GetFeatures` | Used |

| R10 | Cheatsheet defaults for a light overlay | 738e334: unset `autoHideMs` = 8 s, `HideCheatsheet` always clears EWW. Still requested: opacity default 0.35 (now 0.85) and a structured `features.cheatsheet.defaults` | Reads the structured defaults when present, else the option descriptions |
| R11 | Icons | Done in a920ddd, as proposed: binding `"icon"` (Tabler outline name or `"none"`, never rejected), `"icon"` on every cheatsheet key and knob event (resolved, or empty), automatic icons (media, mouse, launchers by command word, common shortcuts, Kdenlive actions), and `features.cheatsheet.icons` `{set, version, auto}` (87 names, plus more Kdenlive actions) | Picker, layout, list and preview use it; `auto` must stay inside `icons.txt` (tested) |

Follow-ups now that the API exists, in order:

1. Save through `ValidateConfig` and `SetConfig(text, expectedHash)` when the
   daemon is on the bus. It is hash-checked and leaves `<path>.bak`. Keep the
   direct write for when the daemon isn't running.
2. Drive the wizard through `StartFlash` and `FlashProgress` when the daemon
   runs. It releases its grab and enters the bootloader by itself on the open
   firmware. Keep `keypad-ctl firmware flash` for when no daemon is running.
   Both keep dry run as the default until real flashing is enabled.

## Development and testing

| Variable | Effect |
|---|---|
| `SMPLOS_KEYPAD_SYSFS=DIR` | Settings and `keypad-ctl` read a fake `/sys/bus/usb/devices` |
| `SMPLOS_KEYPAD_PROC=DIR` | Settings looks for a hand-started keypad app in a fake `/proc` |
| `SMPLOS_KEYPAD_FIRMWARE_DIRS=A:B` | Firmware image directories |
| `SMPLOS_WCHISP=PATH` | wchisp binary (tests use a fake) |
| `SMPLOS_KEYPAD_CTL=PATH` | `keypad-ctl` used by Settings |
| `SMPLOS_CONTROL_SURFACED=PATH` | Daemon binary used by Settings |
| `SMPLOS_KEYPAD_EVENTS=FILE` | Mock live input: append lines like `{"slot":"knob2","event":"cw"}` |
| `SMPLOS_KEYPAD_REAL_FLASH=1` | Let the wizard run a real flash (leave unset in development) |

Tests:

```bash
cd tests && python3 -m unittest test_keypad          # keypad-ctl, wiring, migration
cd smpl-apps && cargo test -p settings --bin settings  # keypad::{json,config,…}, UI contract
```

`test_keypad.py` uses a fake sysfs, a fake wchisp and a private HOME. It covers
detection of each firmware, dry-run flashing (wchisp is never called), refusal
of a missing or second bootloader, a bad size, a bad checksum and a non-CH552
chip, and the wchisp allowlist. Its lifecycle tests check that the udev alias
and the unit's `BindsTo=`/`After=` name the same device unit (via
`systemd-escape`), that the unit has no `[Install]` and passes `systemd-analyze
verify`, that no EWW `deflisten`/`defpoll` or script is keypad related, the
bar's one-shot sync script and the login step, and the migration paths (fresh, an earlier
draft's enabled unit, a custom unit). Its overlay tests check both cheatsheet
windows (only the click-through one has `:passthrough`), the click-to-close
handler, the 0.35 fallback and that the background is the only translucent
color. `pad-sheet-hide.sh` is tested with a fake `busctl` and `eww`.

Icon tests check that `icons.txt`, the JSON and `pad-icons.yuck` agree, that the
font has every codepoint under its family name, that the keypad app's
automatic icons are bundled (pinned list, and a live keypad app when one is
installed), that every glyph lookup in the overlay is gated, the
sync script's font flag (font older or newer than EWW, no font) and that the updater
installs the font and table before `eww.yuck`.

Done by hand on a private X server, never the desktop: the patched EWW's
click-through window has an empty XShape input region, and an XTEST click
reaches the window below it (a normal window still catches it). With a
stand-in compositor selection, GTK picks the RGBA visual, and the window's own
pixels give the alpha numbers above. Wayland wasn't run: the only compositor
here is the live Hyprland. GTK 3.24 sends an empty `wl_surface.set_input_region`
for an empty input shape (`gdk_wayland_set_input_region_if_empty`).

To test live input and identify mode end to end, run the daemon's
`mock-control-surfaced` on a private session bus (`dbus-daemon --session
--address=unix:path=...`). Point Settings at that bus, then drive inputs with
its `org.smplos.ControlSurface1.Mock` methods (`Press`, `Turn`) and read the
`Identifying` property with `busctl`.

For a visual check, run Settings or EWW on a private Xvfb display. Use a
temporary `HOME` and `XDG_RUNTIME_DIR`, no `WAYLAND_DISPLAY` or
`XDG_SESSION_TYPE`, and the variables above. Never preview on the live
desktop.
