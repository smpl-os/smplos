# smpl-hud

A Hyprland plugin that draws HUD window frames around every window, from the
active theme: either a chamfered, glowing outline with corner brackets and edge
tabs (the look of the `neon` theme), or a notched panel outline with circuit
traces, dots that circle the outline and dots that bounce along the traces (the
look of `amber-hud`), or a plain outline right at the window's edge, with three
columns of Matrix characters falling beside each of its sides, each further one
smaller, dimmer and softer, as if it were further away, and slow green glows
drifting along its top and bottom (the look of `matrix-hud`). Any of them can add
a small animated scanner, like the radar of a space game, in the bottom right
corner of every window (`hud_scanner`, which `amber-hud` uses). In a panel the
outline bulges out round it, so that the corner is a small pod for it, and the
dots that circle the outline skirt it.

It is a **window decoration inside the compositor's own render pass**. It moves,
resizes, animates, fades and stacks together with its window, so it never lags
behind a dragged window, and it creates no surfaces and takes no input, so it
cannot make anything unclickable. A separate overlay process had both problems.

Without `hud_frame = "true"` in the theme it draws nothing, and without the plugin
a theme only loses the frames: windows keep Hyprland's own cut corners, border,
glow and shadow. The exception is a theme that hides Hyprland's border so that the
frame is the only line (`hud_hide_border`, as `matrix-hud` does): without the plugin
it has no border line at all.

## Source layout

| File | Role |
|------|------|
| `geometry.{hpp,cpp}` | Compositor-free. The **style registry** (`kStyles[]`) and `buildLayout()`, which turns a style plus a window size into a list of concentric border rings and flat fills (ring styles) or a `Panel` of polylines and dots (panel styles), in physical pixels, and the centre line of the outline the travelling glow follows. |
| `gradient.{hpp,cpp}` | Compositor-free. CPU port of Hyprland's `gradient.glsl`, so flat shapes (edge tabs, the lines of a panel) take the colour the border shader would paint at that point. Keep it in step with the shader. |
| `sweep.{hpp,cpp}` | Compositor-free. The travelling glow, which is also what a lamp of the `matrix` style is drawn with: the outline's centre path (`buildPath` for a rounded rectangle or a polyline, `pointAt`), the sprite rasteriser (`renderSweep`), its bounds, and the speed, tick-rate and fade-in/out maths. |
| `panel.{hpp,cpp}` | Compositor-free. The notched outline of a `Kind::Panel` style (`buildPanel`), which bulges out round the scanner at the bottom right corner when the theme has one (`measurePod`, the `Pod` of the `Layout`), and, for `amber-hud`, its traces and dots: where each dot is once it has travelled so far and how much it glows (`runnerPoses`). For the `matrix` style, the columns the characters fall in (`RainLane`), which characters are lit and how brightly (`glyphDraws`, `glyphChanges`), and where each lamp is, how long and how strong (`lampPose`). |
| `glyph.{hpp,cpp}` | Compositor-free. The characters of the `matrix` style: sixty half-width katakana, digits and signs, each a few strokes on a 4 × 6 grid, so no font is needed. |
| `stamp.{hpp,cpp}` | Compositor-free. Turns the lines, dots and characters of a panel into small images the compositor can draw as textured quads: cuts a stroke into strips and tiles (`cutStroke`), bakes them (`bakeStrip`, `bakeTile`, `bakeBead`, `bakeGlyph`) and gives each a cache key. |
| `place.{hpp,cpp}` | Compositor-free. `fitWithFrame()`: where the box of a floating window has to go so that its whole frame stays inside a monitor's usable area. It moves the box in from the edges and shrinks it only when it cannot fit. `parseFitRequest()` reads the window address out of a `hyprctl smplhud fit` request. The compositor side is `placeHudWindow()` and `runHudCommand()` (see "Floating windows"). |
| `theme.{hpp,cpp}` | Compositor-free. Reads the `$themeHud*` variables from the generated `theme.conf`. |
| `scanner.{hpp,cpp}` | Compositor-free. The scanner of a window (`hud_scanner`): its size and layout (`scannerSize`, `scannerLayout`), what a frame depends on (`ScannerSpec`, which the compositor side compares to know when to repaint) and the rasteriser (`renderScanner`): the rings, the ship, the sweeping arm and the contacts, as one premultiplied RGBA image. The animation is a loop of `kScannerLoop` (22 s, 660 frames): `scannerLoopFrame` says which frame a spec shows, `scannerLookOf` what the frames depend on besides that, and `renderScannerClock` draws a moment of the loop by its clock. Also the plate under that picture where the outline has made a pod for it (`plateOf`, `renderPlate`): dark glass, a halo and a bezel. |
| `flipbook.hpp` | Compositor-free, header only. `Flipbook<Frame>`: the frames of a picture that comes round again, kept by number for every window that shows it, within a budget of bytes. A picture that nobody has asked for in a while makes room for another; one that is being asked for never does. |
| `HudDecoration.{hpp,cpp}` | `IHyprWindowDecoration` on every window: reports the HUD's extents, caches the layout, collects the window's live (animated) border and glow gradients and queues a pass element. Owns the one timer that advances the focused window's travelling glow, dots, lamps and falling characters, and decides whose `border_animation` loops keep turning (see "Focus only"). Also keeps floating windows' frames on screen (see "Floating windows"). |
| `ScannerDecoration.{hpp,cpp}` | A second `IHyprWindowDecoration` on every window, on the layer over the window, which reserves no room: the scanner (see "The scanner"), in the pod of the frame where the window has one. Owns its own timer, which advances the focused window's scanner, fades it between focus and rest and steps it aside from the pointer. |
| `HudPassElement.{hpp,cpp}` | Draws the layout with the compositor's border shader and plain rects, or the panel's cached images, then the travelling glow's (or each lamp's) cached sprite and the dots or characters. Its second element draws the plate under a scanner, blurring what lies under its glass where the theme and the compositor allow it, and then the scanner's frame, taken from the loop of frames that every window shares. |
| `main.cpp` | Plugin entry points: ABI check, event listeners (window open, floating, moved to another workspace, active window, fullscreen, config reload, tick), the `hyprctl smplhud` command, cleanup. |
| `tests/` | Unit tests for the compositor-free parts, and `preview.cpp`, which renders a panel, a matrix frame or the character set to a PPM image so a look can be judged without a compositor. |

## Theme keys

The plugin reads `$XDG_CONFIG_HOME/hypr/theme.conf`, else `~/.config/hypr/theme.conf`
(generated by `theme-set` from the theme's `colors.toml`), when it loads and on every
Hyprland config reload, which `theme-set` triggers. Values are clamped.

| Variable | `colors.toml` key | Default | Range |
|----------|-------------------|---------|-------|
| `$themeHudFrame` | `hud_frame` | `false` | `true` / `false` |
| `$themeHudHideBorder` | `hud_hide_border` | `false` | `true` / `false`; the theme generator gives Hyprland's own border size 0 so that the frame's line is the only one (it needs `hud_frame`, and the plugin then frames a window although it has no border; see Limits) |
| `$themeHudStyle` | `hud_style` | `scifi` | a registered style name (`scifi`, `minimal`, `panel`, `matrix`); an unknown one shows a notification and draws nothing |
| `$themeHudGap` | `hud_gap` | `5` | 0 to 64 px between window edge and outline |
| `$themeHudChamfer` | `hud_chamfer` | `10` | 0 to 96 px minimum corner cut |
| `$themeHudLineWidth` | `hud_line_width` | `3` | 1 to 16 px |
| `$themeHudFloatGlowRange` | `hud_float_glow_range` | `0` | 0 to 64 px; floating windows' halo reaches at least this far |
| `$themeHudSweep` | `hud_sweep` | `false` | `true` / `false`; a soft glow drifts along the focused window's outline, the dots of a `panel` move along its lines, and the characters of a `matrix` fall and its lamps drift along its top and bottom; `false` keeps all of them still, so a `matrix` shows only its outline and halo |
| `$themeHudSweepSpeed` | `hud_sweep_speed` | `80` | 10 to 400 px per second (the dots of a `panel` run 0.8 times as fast, the characters of a `matrix` fall 0.6 times as fast) |
| `$themeHudSweepLength` | `hud_sweep_length` | `180` | 40 to 600 px along the line; for a `matrix`, the longest a lamp gets, which also decides how many fit on an edge |
| `$themeHudGlowFocusedOnly` | `hud_glow_focused_only` | `false` | `true` hides the halo on unfocused windows; the border line stays visible. Static halos need no animation timer (`blueprint`) |
| `$themeHudGlowRange` | `hud_glow_range` | `0` | 0 keeps the style's outer halo width; 1 to 64 sets its reach in logical px for tiled and floating windows. `hud_float_glow_range` can still enlarge floating halos |
| `$themeHudGlowAlpha` | `hud_glow_alpha` | `style` | `style` keeps the style's halo strength; 0 to 1 overrides it before spatial falloff and floating boost. Does not change the crisp border |
| `$themeHudGlyphColor` | `hud_glyph_color` | `none` | `rgb(rrggbb)` or `none`; the colour of the characters of a glyph style such as `matrix` and of its lamps (the heads are it lightened, the glow of the characters it too); `none` leaves them the colours of the line. Anything else is ignored |
| `$themeHudSideOpacity` | `hud_side_opacity` | `1` | 0 to 1; how visible the outline of a `panel` or `matrix` is down its left and right sides, its halo beside it with it, and the corners fade between that and the top and the bottom edge's (`hud_edge_opacity`). A theme whose characters fall there dims it so that they stand out: `0.1` leaves it almost unseen, `0` none at all, `1` as strong as the rest. The ring styles ignore it; not a number, it is ignored |
| `$themeHudEdgeOpacity` | `hud_edge_opacity` | `1` | 0 to 1; the same along the top and the bottom edge of a `panel` or `matrix` outline: `1` is the full line, `0.1` as dark as the sides of `matrix-hud`, `0` none at all (the lamps of a `matrix`, which have a track of their own, and the underglow are not dimmed by it). The ring styles ignore it; not a number, it is ignored |
| `$themeHudUnderglow` | `hud_underglow` | `0` | 0 to 1; how bright a glow is along the window's own top and bottom edge that fades out away from the window, so that the light seems to come from under it. It has no line, reaches as far out as the outline's halo, dies away towards the corners and is as still as the outline. `0` has none; the ring styles ignore it; not a number, it is ignored |
| `$themeHudScanner` | `hud_scanner` | `0` | `0` or 24 to 160 px; how wide the scanner in the bottom right corner of every framed window is (three quarters as high), or `0` for none. `amber-hud` has 72. See "The scanner"; not a number, it is ignored |
| `$themeHudScannerBlur` | `hud_scanner_blur` | `true` | `true` / `false`; whether the glass of the pod round the scanner blurs what lies under it, so that the window's text does not show through. It blurs only while the compositor's own blur is on (`decoration:blur:enabled`) and is not `xray`; otherwise, and with `false`, the glass is flat and more opaque. A scanner with no pod has no glass. Anything else is ignored |

Frame and glow colours are not keys of their own: the plugin paints with each
window's own border gradient (`border_active` / `border_inactive`) and glow gradient
(`glow_color`), including their focus fades and `border_animation` rotation. The one
exception is the characters of a glyph style and its lamps, which can have a colour
of their own (`hud_glyph_color`). See
"Glow, Shadow and Animated Borders" in `CREATING_MODIFYING_A_THEME.md` for how the
keys interact with `gaps_in`, `rounding` and `rounding_power`.

## Focus only

Every window gets the frame, but only the focused window moves. The frame's motion
lives in `HudDecoration.cpp`, the scanner's in `ScannerDecoration.cpp`:

- **The static halo**, with `hud_glow_focused_only`, disappears immediately on
  focus loss without affecting the crisp border. This flag starts no timer and
  schedules no periodic repaints. Other themes retain their existing halos.
- **The travelling glow** (below) drifts along the focused window's outline, and
  with it the dots of a `panel`, and the lamps and falling characters of a `matrix`,
  move. When focus moves it fades out on the old window and in on the new one, half
  a second each.
- **`border_animation`'s rotation.** The theme's looping `borderangle`, `glowangle`
  and `shadowangle` animations make Hyprland turn the border, glow and shadow
  gradients forever, on every window, by starting the next lap whenever one ends.
  With the frame on, the plugin does that for the focused window only.
  A window that loses focus finishes the lap it is on (8 s at Neon's speed) and
  rests, which looks like a gradient that never turned, because a lap is one full
  turn; a lap that has only just begun is stopped at once. A fullscreen window has
  no border, so its loops are stopped too and start again when it leaves
  fullscreen (a maximised window keeps its border and keeps turning). With
  `hud_frame` off, or with the plugin unloaded, Hyprland's own loops return on
  every window.
- **The scanner** (see "The scanner") sweeps and drifts only in the focused window.
  The others show it where it stopped, at 40 % of its strength, and it comes up to
  full and goes back down in half a second as focus moves.

`hud_sweep` and `border_animation` independently control travelling light and
rotation. `hud_scanner` alone decides the scanner
(`hud_sweep = "false"` does not still it); `hud_scanner_blur` only decides whether
its glass blurs what is under it. Motion cost does not grow with unfocused windows.

## Floating windows

The compositor places a floating window by its box alone and knows nothing of a
frame that reaches past it. A window a rule puts against an edge (the start menu,
the notification centre, Signal), one made floating (`Super+T`) at a size the
monitor cannot hold and one sent to a smaller monitor would lose part of its
frame, and the halo with it, beyond the screen. `placeHudWindow()` in
`HudDecoration.cpp` prevents that at the moments a window is placed:

- when it opens (`window.open`, before its open animation starts),
- when it becomes floating (`window.floating`),
- after it is moved to another workspace or monitor (`window.moveToWorkspace`).
  The compositor does its own placement after it sends that event, so the plugin
  runs once that is done (`placeHudWindowLater()`),
- on request: `hyprctl smplhud fit <window address>` (`runHudCommand()`). The
  compositor sends nothing when a window is put at a position, so a script that
  does that asks for the fit once it is done. `toggle-messenger` does: it brings
  its window back from the hidden workspace and pins it 2 px from the monitor's
  right edge and 34 px above its bottom, inside the frame's reach, and then asks.
  The reply is `ok`, `no such window` or a usage line. The request changes nothing
  for a window that already fits and for a theme without a frame, and without the
  plugin hyprctl answers `unknown request`, which a script can ignore,
- for every open window when the frame's extent changes, which is when the plugin
  loads or a theme change makes the frame wider. A config reload that keeps the
  extent changes nothing.

`fitWithFrame()` (`place.cpp`, a pure function with its own tests) moves the box in
from each edge of the monitor's usable area (the monitor minus what bars reserve)
by the frame's extent on that side, and makes it smaller only if it fits no other
way. A window whose frame is already inside is not touched. The extent used is that
of the widest look (floating, with its halo), so a window does not shift when
focus or its floating state changes the frame.

Left alone: a window being dragged or resized; every move or resize the user makes
(nothing is checked after it, so a window put half off-screen stays there); tiled,
fullscreen and grouped windows; windows without a frame (see Limits); and a monitor
too small to hold the frame around a 40 px window, where the compositor's placement
stands. Tiled windows are placed by the layout inside the margin `gaps_out` leaves,
so a theme's `gaps_out` has to be at least as wide as the frame's reach (the
outline's distance plus its halo) for the frames of tiled windows at the screen
edge to show whole.

## Travelling glow

With `hud_sweep = "true"` a soft ellipse of light drifts along the focused window's
outline, around the corners and cuts, and fades in and out of the line's own
colours (its core is the outline's gradient colour at that spot, mixed towards
white; `sweepAlpha` / `sweepWhiten` in the style set how strong). It fades in over
half a second when a window gets focus and out when it loses it. Every window has
its own place on its line, so a glow reappears where that window's last one faded,
and two windows never start in step. It is meant to be almost subliminal: the
default 80 px/s takes a typical window tens of seconds for a lap.

A `matrix` has no glow going round its outline. Its lamps (below) are the same
sprite, one for each lamp, on a track of their own, in the colour of the
characters (`hud_glyph_color`, else the line's).

It is built to cost very little:

- **One shared timer**, running only while the theme asks for the glow, at
  `sweepInterval()`: about 23 steps per second at 80 px/s, 20 at Neon's 70 (a
  step is never more than about 3.5 px, a small move for a soft glow well over a
  hundred px long), and a step every 33 ms while a glow fades. While nothing is
  visible to move (no window focused, the focused one fullscreen or on a hidden
  workspace, monitors asleep) it backs off to a 4 Hz poll, and it stands still
  while the session is locked. A step longer than a quarter of a second, such
  as after a stall, is clamped so the glow never jumps.
- **A small sprite, not a shader pass.** `renderSweep()` rasterises the
  ellipse into a premultiplied RGBA texture only as big as the glow, with one
  texel per two logical px (about 2,600 texels, 0.06 ms; the GPU's bilinear
  filter smooths the upscale), cached per window and rebuilt only when its
  position or quantised colour changes.
- **Damage-limited.** Each step damages just the box the glow left and the box
  it entered, which lies in the margin and gaps around the window, so the rest
  of the screen is not repainted by it. The sprite is clipped to the HUD's own
  extents and never covers the window itself.
- **Nothing on windows that cannot show it**: fullscreen, borderless, hidden
  or off-screen windows, and monitors that are off, do not advance or draw it.

Measured in a software-rendered test compositor (no GPU, three windows, so far
costlier than a real session), the glow of the focused window cost about 1% of one
CPU core and nothing without it. `border_animation` costs more than the glow,
because Hyprland repaints a turning border every frame: about 4% for the focused
window's, against about 7% when every window turned and glowed, as it did before
the plugin limited the motion to the focused window. The cost does not grow with the
number of windows, since only one moves. A fullscreen window, an empty workspace or
a sleeping monitor brings it back to zero.

A theme without `hud_sweep = "true"`, or a style with `sweepAlpha = 0`, creates
no timer and no sprites. Unloading the plugin removes the timer.

Limit: if the theme's `hud_chamfer` is deeper than the window's own corner (for
instance `rounding = "0"` with a large chamfer), the outline crosses the window's
corner and the glow shows only on the outer side of the line there; it never
paints over the window's content.

## Styles

A style is one entry in `kStyles[]` in `geometry.cpp`; the fields are documented in
`struct Style` (`geometry.hpp`).

| Style | Look |
|-------|------|
| `scifi` | Outline, halos on both sides, corner brackets, mid-edge tabs |
| `minimal` | Outline and halos only |
| `panel` | Notched outline with a step, a ghost line and a cut corner, circuit traces ending in beads, two dots circling the outline in opposite directions and a dot bouncing along each trace; the circling dots glow as they near a bouncing dot or each other (`amber-hud`) |
| `matrix` | The `panel`'s outline alone, hugging the window, as one line with its glow: Matrix characters fall down both sides in three columns on each, the first on the line itself, as if they slid along it, and the others beyond it, inside its glow, each further one smaller, dimmer and softer than the one before and partly under it, so that the rain looks deep, each a bright head that glides down keeping one shape for four or five rows and a tail of other characters it leaves behind, and a few slow green glows (lamps) pulse and drift to and fro along the top and the bottom (`matrix-hud`) |

For the ring styles (`scifi`, `minimal`) the corner shape is not part of the
style: the outline follows the window's own `rounding` and `rounding_power` at a
constant distance. `rounding_power = "1"` gives straight 45° cuts (the octagon of
`neon`), `2` circular corners, 4 and above squircle-like ones, and `rounding = "0"`
square ones. A `panel` has its own polyline outline instead (below). A different
outline of either kind is new geometry in `Builder` (rings) or `panel.cpp`, plus an
entry in `kStyles[]`.

### The `panel` style

A style with `kind = Kind::Panel` is not made of rings. `buildPanel()` (`panel.cpp`)
gives a `Panel`: strokes (polylines of straight and 45° runs, snapped to whole
pixels), beads and runners (`amber-hud`), and the columns of characters and the
track of the lamps (`matrix-hud`), all in physical px from the window's top-left
corner.

- **The outline** (`strokes[0]`, closed) stands `hud_gap` off the window. It has
  chamfered corners, a notch and a step on the top edge, a raised line and a ghost
  line that fades out on the bottom edge, and a bigger cut at the bottom left.
  The notches are 9 px deep with `hud_gap` 13 or more, shrink below that and are
  gone under 7. The bottom-left cut is limited by the window's own corner cut
  (`rounding`), so a window with a larger `rounding` gets a deeper one.
- **The pod.** With a scanner (`hud_scanner`, see "The scanner") the corner at the
  bottom right is not chamfered: the outline steps out from the right side, runs
  down the right edge of a plate for the scanner's picture, round its corner and
  back along its bottom, and steps in to the bottom edge again (`bottomRight()`).
  The dots that go round the outline skirt it, and the trace on the right side
  ends 4 px above it. At scale 1 it pokes 8 px beyond the frame, its outer corner
  is cut 14 px, the plate reaches 3 px beyond the picture all round and its bezel,
  the edge on the window's side, has a corner cut 9 px (`measurePod()`,
  `Layout::pod`). It is also in the plain outline of a small frame. A window gets
  one only if it is five times as wide, and as high, as the picture and the plate
  fits inside the frame without crowding the notches (a pod that would leave them
  no room gives way to them); otherwise it keeps the chamfer, and the scanner
  stands in the corner by itself. The frame's extents, which do not depend on the
  window's size, always have room for the pod, and the gradient the lines take
  their colour from is measured over a box that holds the pod too.
- **Three traces** run beyond the outline and end in beads (a style with a
  `traceOffset` of 0, like `matrix`, has none). A window whose frame
  (the window plus the outline's clearance) is smaller than 480 × 160 logical px,
  or that has no room for the notches, gets a plain chamfered outline (with two dots
  in `amber-hud`) and no traces.
- **Runners**: while the window has focus, dots move along the outline and the
  traces, at `hud_sweep_speed` times the style's `runnerSpeed`, each with its own
  offset and speed. A runner on the closed outline goes round it (fading out
  where the ghost line does), and the two of them go in opposite directions (a
  negative `Runner::speed` runs the other way). A runner on a trace goes back and
  forth between the beads at its ends, slowing down into each end and turning
  there, and never fades. They stay as long as the focused window's travelling
  glow does, which also decides the timer's pace and the damage. The beads at the
  ends of the traces are always there. Where a dot is, is a pure function of how
  far the dots have travelled (`runnerPoses`), which is what the tests and the
  preview use.
- **Glow.** A dot going round lights up as it nears a dot bouncing on a trace
  (straight-line distance, `Panel::touch`: fully lit within 14 px, not at all from
  70 px, at scale 1) and as it nears the other dot going round (distance along the
  outline, `Panel::merge`: from 12% of the outline's length away, but from
  no less than 200 and no more than 500 px at scale 1 and never from more than
  35% of the outline, and fully lit within a tenth of that), so both of the two
  swell and brighten as they close in on each other, are brightest as they pass and
  die down as they part. `runnerPoses` returns the amount
  (`RunnerPose::glow`, 0 to 1) and the compositor draws the flare, `Panel::flare`,
  a bigger and brighter bead (1.7 times the radius, 3 times the glow), over the dot
  with that much opacity. Dots on traces
  do not glow, a dot that cannot be seen lights nothing and a half-visible one
  lights half. A `flare` of radius 0 turns the glow off.
- **How it is drawn.** The compositor can only draw textured quads, so `stamp.cpp`
  cuts every stroke into straight strips and small tiles where the line turns,
  and bakes each piece once: a strip is a 2-texel image stretched along its run
  (the GPU's bilinear filter blends the colours of its two ends, so one image
  serves a run of any length), a tile is a bitmap drawn 1:1, a bead a soft round
  sprite. They are kept on the GPU in a cache shared by all windows (at most 2048
  images; a full cache is emptied and refilled from the next frame), keyed on
  everything an image depends on, colours rounded to 5 bits a channel. Pieces never
  overlap, and only the frame's damage is painted. A dot that glows is drawn twice,
  as its own bead and with the flare over it: the glow is only the flare's opacity,
  so it costs one more quad and no image of its own for each value.
- **`border_animation`.** A turning gradient recolours every piece at each step, so
  the cache bakes new images and the whole outline is repainted: keep it off in a
  panel theme, as `amber-hud` does, and let the dots and the travelling glow move
  the frame.
- **Preview.** `make preview && build/preview panel 1280 720 1 2 0 0 > panel.ppm`
  draws a panel the way the compositor will, without one (arguments at the top of
  `tests/preview.cpp`).

### The `matrix` style

A `matrix` style is a `Kind::Panel` style with `glyphHeight` and `lamps` above 0
and no beads, runners or traces (`beadRadius` and `traceOffset` are 0): the
`panel`'s outline as one line with its glow, and light that moves inside that
glow. `buildPanel()` adds to the `Panel` up to three `GlyphFace`s (character height,
stroke weight, glow reach, pitch, fall speed, plate opacity, `dim`, how bright the
characters are at most, and `soft`, how much softer than a pixel the edge of a
stroke is, derived from the style and the scale; `Panel::face(column)` gives the
one of a column): `glyphs` for the column on the line, `farGlyphs` for the
second and `deepGlyphs` for the third. It also adds the columns the characters fall
in (`placeRain()`, `Panel::lanes`) and the track and lamps of the top and bottom
edges (`placeLamps()`, `Panel::track` and `Panel::lamps`).

- **One line.** The theme sets `hud_hide_border = "true"`, so Hyprland's own
  border is not drawn (the generator gives it a size of 0), and turns its glow and
  shadow off (`glow = "false"`, `shadow_range = "0"`). The outline and its halo
  (`haloAlpha`, `haloReach`: 22 px, enough for all the columns of characters to
  stand in it) are then the window's only line and glow, and `hud_float_glow_range`
  widens the halo on floating windows. The theme's `hud_gap` of 3 puts the line as
  close to the window as a 2 px line gets, which leaves no room for the notches,
  so it is the plain chamfered outline that follows the window's cut corners. The
  plugin still frames such a window unless it opts out itself (fullscreen,
  `decorate` off or a `border_size 0` rule, as the JetBrains and picture-in-picture
  windows have); see Limits.
- **Characters.** `glyph.cpp` holds sixty half-width katakana, digits and signs,
  each a few straight strokes on a 4 × 6 grid, mirrored like the film's. Drawing
  them from strokes, not from a font, keeps the HUD free of a font or text
  library and every machine rendering the same glyph; `stamp.cpp` bakes them with
  the same bright core and soft halo as the lines.
- **Columns.** Only the straight runs of the two sides get characters, none on the
  top or the bottom (`placeLanes()`). On each side the first column is on the line
  itself, its characters centred on it (to the whole px), as if they slid along
  it, and the others lie beyond it, in its glow (`Style::glyphColumns` says how
  many there are, up to `kGlyphColumns`, which is 3): each of them lies partly
  under the one before it, with only 0.4 of the width of one of its characters
  beyond that column's outer edge (`kColumnPeek`), as things at different
  distances overlap. Each further column's characters are
  smaller, dimmer and softer than the one before's (`kFurther`): the second's half
  the size, 0.55 as bright, with the edges of their strokes 0.6 px soft; the
  third's a third of the size, 0.38 as bright and 0.9 px soft, a faint haze behind
  the rest. The first is 0.8 as bright (`kNearDim`), so a little see-through: the
  line shows through its characters, and the second shows through where it lies
  under it. A further column's pitch is in
  proportion to its size, and it falls as many rows a second, which are fewer px, so
  it looks slower too. A column begins and ends a pitch short of its straight run,
  and one of fewer than three characters is dropped, together with any beyond it
  (the compact outline of a small window has short sides): there is no further
  column where there is no first. They depend on the style and the scale, never on
  the window's size. At scale 1 the columns stand 0, 5 and 8 px from the
  middle of the line and the outermost one's glow reaches 13 px, so the lines of
  tiled neighbours need to be about twice that apart, and a window needs about 16
  px between its edge and the screen's (see Limits). The frame is drawn under the
  window, so the part of the first column's characters that lies over the window
  box, a fifth of each at the default `hud_gap` of 3, is hidden by it, or shows
  through as faintly as the window is see-through. For fewer columns, set
  `glyphColumns` to 1 or 2.
- **Dark outline and underglow.** What a `matrix` shows down its sides is the
  characters, and along its top and bottom edge the lamps, so the theme can let
  the line almost vanish everywhere (`hud_side_opacity` and `hud_edge_opacity`,
  both 0.1 in `matrix-hud`; `Params::sideOpacity` and `Params::edgeOpacity`).
  `dimOutline()` scales the alpha of the outline's vertices that stand on the two
  sides by the first and the others by the second; a vertex's alpha scales the
  line and its halo alike and fades smoothly along the cut corners, from one to
  the other. At 0 the straight runs of the sides (or of the edges) are not drawn
  at all and the corners' diagonals fade out to nothing. Nothing else moves or
  changes colour: the characters' own colours do not depend on either, the lamps'
  track is made from the outline as it was before it was dimmed (with its sides
  masked), so the lamps are as bright as ever, and the layout, the columns and
  the damage boxes are the same. It dims the outline of every window, focused or
  not. The defaults of 1 change nothing.
  The **underglow** (`hud_underglow`, 0.3 in `matrix-hud`; `Params::underglow`)
  puts light back, as if it shone from under the window: the last two strokes of
  `Panel::strokes`, made with `underglowRun()`, are glows with no line (a core
  alpha of 0, the underglow as the halo's) along the window's own top and bottom
  edge, which is not where the outline is. They reach as far as the outline's halo
  does, a floating window's boosted like its halo (`floatBoost`), and are
  strongest between the corners, dying away towards them over `kUnderglowTaper`,
  1.5 times that reach, where the characters fall. The frame is drawn under the
  window, so the half of the glow that lies over the window box is hidden by an
  opaque window and shows through a see-through one. It never changes by itself:
  it is baked once with the outline and, like it, repainted only where a lamp or a
  character leaves or enters. One too faint to see, or with no reach, has no
  stroke at all.
- **Rain.** `glyphDraws()` is a pure function of how far the columns have fallen,
  how far the window has focus (`intensity`, 0 to 1) and a per-window seed, so the
  tests and `make preview` can ask for any moment. Each column has one to three
  falls (one for every twenty characters), the second column, whose characters
  are half as tall, up to six, and the third, whose are a third as tall and only a
  faint haze, up to four (every character is a draw for the compositor). A fall is
  a **head**, one bright character that
  glides down the column smoothly, never up, and keeps its shape for four or five
  rows before it turns into another one (over about two thirds of a row, the old
  shape fading as the new one comes up), and a **tail** behind it: every cell the
  head passes is given a character of its own, different from the head's, which
  comes up as the head gets clear of the cell and then dims, more slowly the
  longer the tail. The next head to reach a cell replaces whatever is in it, and
  nothing ever changes by itself. A fall fades in at the top of the column and out
  at the bottom, runs off the end, and after a pause begins again at the top.
  Every fall has its own speed (0.75 to 1.35 times the column's) and pause, and
  every pass a tail of its own length, eight to twenty-eight rows (a column of
  fewer than 47 allows three fifths of its length, and never fewer than three). A
  pass lasts as long as the longest tail needs, so a short tail only rests longer,
  and no pass is cut off by the next. Two heads that come within a row of each
  other do not run together: one of the pair (always the same one) fades out as
  they close in, and is gone when they are less than a third of a row apart. No
  two characters are quite alike: every head and every character left behind has
  a brightness (a head at least 85% of the full one, the others at least 70% of
  their own) and one of three sizes (84%, 92% or 100% of the face's, for 30%, 40%
  and 30% of them), too little to look like another font. The face's `dim` scales
  all of it, so each column is dimmer than the one before (a head of the first up
  to 0.8 of the full brightness, of the second up to 0.55, of the third up to 0.38).
  The nearest rows behind a head are overdrawn in the Bright colour. The whole
  rain is as slow as the lamps (the heads of the first column fall 0.6 times as
  fast as `hud_sweep_speed`, those of the second half as many px a second, those of
  the third a third as many, each fall at 0.75 to 1.35 times that), so that it stays
  at the edge of the eye and
  does not draw it from the work. Characters that no fall lights are not drawn,
  and at intensity 0 none are.
- **Lamps.** The glows along the top and the bottom are up to two ellipses on each
  edge (`placeLamps()`, `lampPose()`), as many as fit in the edge at one and a half
  times `hud_sweep_length` each, none if the edge is shorter than one. Each goes to
  and fro between the ends of its edge, slowing down into each end like a dot on a
  trace, pulses every four to six seconds between 35% and full strength while its
  length swells and shrinks by an eighth, and every one has its own length, speed,
  direction and pulse. The track they follow (`Panel::track`) is the outline with
  its two sides dark, so that no glow runs where the characters fall. A lamp is
  tinted with the colour of the characters (`hud_glyph_color`, else the line's) and
  whitens only a little at its core (`sweepWhiten` of 0.22), so that it stays
  green and does not turn white at full strength.
- **How it is drawn.** A lit character is one textured quad from the shared stamp
  cache, keyed on the glyph, its alpha and heat step (32 and 8 of them), size and
  colours; the characters are the most numerous images, which is why the cache
  holds 2048. Each is baked in the size it was given (`glyphFaceOf()`), with the
  face of its column (`GlyphDraw::column` is 0 for `glyphs`, 1 for `farGlyphs` and 2
  for `deepGlyphs`; see `Panel::face()`), and the face's `soft` softens the edges
  of its strokes (`Look::soft16`), so that the further columns are out of focus
  too. The columns are drawn furthest first (`glyphOrder()`), so that the nearer
  ones, which are a little see-through, lie over them.
  (A style with a `glyphKnock` above 0 also bakes a dark plate behind each character that
  dims the line it stands on; `matrix` has none, so that the line shows through the
  characters of its first column, which stand on it.) The colours are those of the line where the
  character stands and of the glow, or, with `hud_glyph_color`, that colour for
  the character (at the opacity the line's gradient has there, which neither
  `hud_side_opacity` nor `hud_edge_opacity` dims), the same for its glow, and
  that colour lightened by the style's `brightWhiten` for what is overdrawn in the
  Bright colour. A lamp is the travelling glow's sprite, with a cache of its own
  and its own length and strength. The characters a head has left stay where they
  are and only light up and fade; a head glides, a whole pixel at a time, and while
  it turns into another character it is two entries, the one it is turning from
  and the one it has (`kGlyphHeadId`). `glyphChanges()` lists what differs between
  two moments (a character that has moved is listed as it was and as it is), and
  at each step of the one shared timer only those characters' boxes are damaged,
  and the boxes a lamp leaves and enters.
- **Focus and cost.** Only the focused window moves, fading in and out over half a
  second like the travelling glow; the others keep their outline and halo. The
  timer steps at the pace of `hud_sweep_speed` (the characters fall 0.6 times as
  fast and the lamps go up to 0.8 times as fast) and backs off to a slow poll when
  nothing could be seen moving. With `hud_sweep = "false"` there is no timer, no
  lamps and no characters, only the outline and its halo. Keep `border_animation`
  off in a `matrix` theme, as `matrix-hud` does: a turning gradient would repaint
  the whole outline at every step (see the `panel` style). The cost is the number
  of characters repainted: each is a draw of a cached image, about 25 µs of the
  compositor's time on a real session, and a step repaints those that changed and
  those that overlap them. At the default pace a focused 1920x1080 window with
  three columns does that about 180 times in each of the 20 steps a second, which
  is some 9% of one core, and with two columns about 115 times, some 5%. That is
  why the third column, which is only a haze, has at most four falls
  (`kLaneMaxStreams`), and why `glyphColumns` is the way to make a style cheaper.
  The windows that are not focused stand still and cost nothing per step.
- **Preview.** `build/preview matrix 900 560 1 1 0 700 3.0 matrix 1 3 3 0.1 0.1 0.3 > matrix.ppm`
  draws a focused frame with the rain 700 px of travel into its fall (the seventh
  argument, which alone decides where the characters are), the lamps three
  seconds into their run (the eighth), the outline 3 px off the window (the
  twelfth; without it the gap is 15 and the notches are back), a tenth as
  visible down its sides and along its top and bottom (the thirteenth and the
  fourteenth; without them the whole line shows) and a glow of 0.3 under it (the
  last; without it there is none), like `matrix-hud`'s, and
  `build/preview glyphs 4 matrix > glyphs.ppm` every character.

### Adding a style

To add a look:

1. Add an entry to `kStyles[]`. The name is lowercase letters, digits, `-` and `_`
   (what the theme generator accepts) and unique. Setting `bracketLen` / `tabLen`
   to `0` drops the corner brackets / edge tabs, and a `Kind::Panel` style with
   `glyphHeight` above 0 draws characters falling in columns along the straight
   sides (`glyphPitch`, `glyphFall`, `glyphGlow`, `glyphKnock`, and `glyphColumns`,
   one to three columns beside each side, each further one smaller, dimmer and
   softer) and, with
   `lamps` above 0, glows drifting along the top and the bottom (`beadRadius` and
   `traceOffset` at 0 leave out the dots and the traces).
2. `make test`. The tests walk `allStyles()`, so the new style is checked for a
   valid name, shapes that stay inside the extents the compositor was told about,
   and concentric rings without editing them. Add a test for anything particular
   to the look.
3. A look that needs a new kind of ring-based shape goes into `Builder` in
   `geometry.cpp`; a new polyline outline is a `Kind::Panel` style built in
   `panel.cpp` (its vertices sit on whole or half pixels and 45° apart, which
   `cutStroke` relies on, and `tests/test_panel.cpp` checks). Keep the paint
   roles to `Line`, `Glow` and `Bright`, which map onto the window's own
   gradients.
4. Select it from a theme with `hud_style = "<name>"`, and add it to the
   `hud_style` rows in `README.md` and `CREATING_MODIFYING_A_THEME.md`.

## The scanner

With `hud_scanner` above 0 every framed window gets a small scanner in its bottom
right corner: a flat disc seen at a slant, like the radar of a space game, with
three rings inside a brighter rim, a bright arrow for the ship in the middle, an
arm that sweeps round and lights the contacts it passes (up to four small markers
that float above or below the disc on thin stalks and drift across it). It is
`hud_scanner` px wide and three quarters of that high; `amber-hud` has 72.

- **A picture, not geometry.** `renderScanner()` (`scanner.cpp`) makes the whole
  frame on the CPU from its `ScannerSpec` alone (size, frame of the clock, seed
  and three colours rounded to 5 bits a channel), so a frame is always the same
  and `tests/test_scanner.cpp` can check it. The animation is a loop: the arm, the
  pulse, the ship's sway and the flights of the contacts all come round again
  every 22 s (`kScannerLoop`; 660 frames at 30 a second), so a frame is made once
  and kept as a GPU texture (`flipbook.hpp`) for every window that shows it, at
  whatever point of the loop that window is. The seed only puts the scanners of
  different windows out of step with each other. While the colours it is drawn in
  change (a fade, a drifting `border_animation` gradient) a frame is made for that
  moment alone and not kept.
- **Colours.** The rim, rings and stalks take the colour of the window's `Line`
  paint where the scanner is, the ship, arm and markers its `Bright` paint and the
  halo its `Glow` paint, so it follows the theme, the focus fade and
  `border_animation`'s rotation like the frame does. While those animate the
  scanner is repainted with them.
- **Where.** In a `panel` style it stands in the pod the frame has made for it (see
  "The `panel` style"), a plate in the bottom right corner whose right and bottom
  edge are the outline itself, so that the corner is a part of the frame and not
  something laid over it. Where there is no pod (the ring styles, a window too small
  for one) it stands in the corner of the window, `max(6, 0.3 * rounding + 2)`
  logical px in from both edges, clear of the rounding of the corner, with no
  plate. Either way it is a decoration on the layer over the window
  (`DECORATION_LAYER_OVER`), drawn right after the window's own picture, so it lies
  on the window's content; windows above it and popups still cover it. It reserves
  no room around the window and takes no input.
- **The glass.** The plate of a pod is a picture of its own (`plateOf()`,
  `renderPlate()`), drawn under the scanner's: dark glass over the window, tinted a
  little with the line's colour and held by the outline along the right and bottom
  edge, with a bezel along the sides that are on the window: a line as thick as the
  outline's, a halo outside it on the window and a faint rim lit just inside. It
  depends on nothing but the pod's shape, the scale and the colours of the line and
  the glow where it stands, so it is made again only when one of those changes, and
  is kept for each window. The glass is 85 % opaque, or 62 % where it blurs what
  lies under it: with `hud_scanner_blur` on (the default), the compositor's
  `decoration:blur:enabled` on and `decoration:blur:xray` off, `drawBlurred()` lays
  the frame so far, blurred, under every px of the plate that is more opaque than
  its halo, so the window's text does not show through (the halo stays clear);
  without any of those it is flat glass. The blur uses the compositor's own blur
  settings, as for a translucent window. A scanner with no pod has no glass.
- **Where not.** Windows without a frame, fullscreen windows, and windows less
  than five times as wide, or as high, as the scanner have none. A window on a
  screen that is off, or on a locked session, advances nothing.
- **Focus.** Only the scanner of the focused window moves. The others stand where
  they stopped at 40 % of their strength, and moving the focus fades one down and
  the other up over half a second.
- **The pointer.** The scanner lies over the window's content, so it gives way:
  while the pointer is within 0.4 of the scanner's width of it (of its plate, where
  it has one), it fades out in 0.15 s, and when the pointer has gone it fades back in over 0.6 s,
  slowly so that a pointer passing by does not make it flicker. Nothing is drawn or
  repainted while it is out of the way. It steps aside for the pointer only, not
  for the keyboard: a status line in the corner of a terminal is under it (turn it
  off with `hud_scanner = 0` if that is in the way).
- **Cost.** One timer (`ScannerDecoration.cpp`) runs only while the theme has a
  scanner. It steps 30 times a second while a scanner moves or fades (on the beats
  of the glow's timer where that is running, so that one frame is not drawn twice)
  and polls ten times a second otherwise, which is also how it sees the pointer
  come near. A scanner at rest repaints nothing, and only the focused window's
  moves, so the cost does not grow with the number of windows. A frame of the loop
  is made (about a millisecond of CPU) the first time any window shows it and is a
  lookup from then on: the 660 frames are all made within about 75 s of a scanner
  moving, after which a beat is one textured draw. The frames of
  a loop are 10 MiB of GPU memory at the default width and 41 MiB at twice the
  scale. All loops together are held to 128 MiB (a dozen looks of the scanner, or
  three at twice the scale), a loop that nothing has shown for 10 s makes room for
  another, and they are all freed when the theme no longer has a scanner or the
  plugin is unloaded.
  Measured in a throwaway headless Hyprland on a desktop GPU shared with a compute
  job, with three windows and one of them focused: the scanner's draw took 2.2 ms
  of CPU per second with the blur and 0.3 ms with `hud_scanner_blur = false`
  (14 ms when every beat made its picture afresh), and by GPU timer queries 0.9 ms
  and 0.03 ms of GPU time per second. The compositor as a whole, in % of one CPU
  core (six runs of 20 s for each case, mean ± standard error), took 1.08 ± 0.05
  with `hud_scanner = 0` (the rest of the frame still drawn), 1.23 ± 0.03 with the
  flat glass and 1.53 ± 0.04 with the blur: 0.15 and 0.45 points more, about 0.01
  and 0.02 % of a 20-core machine. Each is more than twice the error of the
  difference, so it is real, and it is small. Those two were run with a build that
  held the picture still but drew it at every beat, a stand-in for a lookup;
  making it afresh at every beat took 2.79 ± 0.09. The blur is the dearest part.
- **Preview.** `build/preview scanner 4 amber 72 1 0 0 8 3 0.4 > scanner.ppm`
  draws a 72 px scanner at 4 times its size, eight moments 0.4 s apart over a dark,
  a grey and a light window, to judge the look without a compositor, and
  `build/preview scanner 3 amber 72 1 0 0 16 1 1.375 > loop.ppm` sixteen moments
  1.375 s apart, which is the whole of the 22 s loop. The pod it
  stands in is drawn by `build/preview panel 1280 720 1 1 0 0 0 amber 1 0 15 1 1 0 72 > pod.ppm`
  (the last 72 is the scanner's width; the arguments are listed at the top of
  `tests/preview.cpp`).

## ABI and delivery

A Hyprland plugin only loads into the exact Hyprland build it was compiled against;
on a mismatch `PLUGIN_INIT` shows a notification and refuses to load. smplOS
therefore never ships a prebuilt binary of it. `src/shared/bin/smplos-plugins`
compiles it and keeps `smpl-hud.<abi-key>.so` in `/usr/local/lib/smplos/plugins`, where
the key is derived from the installed `hyprland` headers:

| When | What happens |
|------|--------------|
| ISO build | `build_hyprland_plugins` (`src/builder/build.sh`) compiles it against the `hyprland` package the ISO ships. A failure only warns. |
| Install | `automated_script.sh` copies the plugin directory from the live system to the target. |
| Login | `autostart` runs `smplos-plugins load`, which loads the binary that matches the running Hyprland. If only binaries for another build exist it loads nothing and shows one notification. |
| Update OS | `sync_plugins` in `smplos-os-update` rebuilds for the installed Hyprland, so a Hyprland update gets a matching binary, and swaps it into the running session. |
| Development | `sudo release/dev-local.sh plugins`, or `release/dev-push.sh` + `dev-apply.sh` in a VM. |

`smplos-plugins status` shows the ABI keys, the installed binaries and what is loaded;
`smplos-plugins reload` swaps a rebuilt binary into the session.

A crash cannot lock the user out: `start-hyprland` restarts a crashed Hyprland in
safe mode, which does not load the user config and with it the `autostart` loader.

## Build and test

```bash
make            # build/smpl-hud.so against the installed Hyprland
make test       # unit tests; plain g++, no Hyprland headers, runs anywhere
make preview    # build/preview: draws a panel or matrix style, or the scanner, as a PPM image, no compositor needed
make clean
```

`make` needs the Hyprland development headers (the `hyprland` package ships them),
the libraries `pkg-config` looks for (its dependencies bring them), `base-devel` and
a C++23 compiler. CI runs `make test` on every change to this directory.

A plugin fault takes the whole compositor, and every open window, down. Try changes
in a throwaway Hyprland instance (a VM or a nested instance) rather than in the
session you work in, and load a build by path with
`hyprctl plugin load "$PWD/build/smpl-hud.so"`. Because the plugin reads
`$XDG_CONFIG_HOME/hypr/theme.conf`, such an instance can point it at a scratch
`theme.conf`.

## Limits

- No frame on fullscreen windows, borderless windows (`border_size = 0`,
  `noborder` rules), X11 override-redirect windows (menus, tooltips) and windows
  under 40 physical px. Layer surfaces (bars, launchers) and popups are not
  windows and get none. A theme that hides Hyprland's own border
  (`hud_hide_border`) gives every window a border size of 0, so there a window
  counts as borderless only if it opts out itself: fullscreen, `decorate` off or a
  `border_size 0` rule.
- The frame is drawn under the window, so it only shows in the margin around it
  and in its cut corners, never over its content (the characters that stand on a
  `matrix` line are cut by the window's edge the same way).
- It needs room: tiled neighbours' outlines are
  `2 * (gaps_in + border_size) - 2 * hud_gap` apart (see the theme guide), and
  with small gaps the lines and halos touch. With `hud_hide_border` the border
  size here is 0: `matrix-hud` has 50 px between the lines (`2 * 28 - 2 * 3`)
  where `amber-hud` has 22, and the three columns of characters on each side of the
  gap, which reach 13 px from their line, need about half of it.
- Without the plugin, a theme with `hud_hide_border` has no border line at all
  (the others keep Hyprland's own border).
- A `panel` or `matrix` is a frame, not a window shape: the window itself stays a uniformly
  chamfered rectangle (`rounding`, `rounding_power`), and the notches, the step, the
  bottom-left cut and the pod are lines drawn in the margin around it. Only the glass
  of the pod lies on the window's corner (see "The scanner").
- The scanner lies over the window's content (see "The scanner"), so it can hide
  what is in the bottom right corner of a window, such as a status line or the
  last button of a toolbar. It steps aside for the pointer, not for the keyboard,
  and a window is only given one when it is at least five times its size.
- A floating window is kept on screen only when it is placed (see "Floating
  windows"): a client with a minimum size the monitor cannot hold, or a window you
  drag out by hand, can still show less than its whole frame.
