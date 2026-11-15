#pragma once

// Compositor-free HUD geometry.
//
// A HUD style plus a window size becomes a list of shapes (concentric
// chamfered border rings and flat fills) in physical pixels, relative to the
// top-left corner of the window box. Nothing here touches Hyprland, so it can
// be unit tested with a plain compiler.

#include <optional>
#include <span>
#include <string_view>
#include <vector>

namespace smplhud {

struct IBox {
    int  x = 0, y = 0, w = 0, h = 0;
    bool operator==(const IBox&) const = default;
};

struct Vec2 {
    double x = 0, y = 0;
    bool   operator==(const Vec2&) const = default;
};

// How far the HUD paints past each side of the window box, in logical px.
struct Extents {
    int  left = 0, top = 0, right = 0, bottom = 0;
    bool operator==(const Extents&) const = default;
};

// Which colour set a shape takes. The plugin maps these onto the window's own
// border / glow gradients so the HUD follows the active theme and animations.
enum class Paint {
    Line,   // the window's border gradient
    Glow,   // the window's glow gradient
    Bright, // border gradient mixed towards white (brackets, tabs)
};

// A band drawn with the compositor's border shader.
struct Ring {
    IBox  inner;               // inner edge of the band
    int   borderSize  = 1;     // logical px; the renderer turns it into physical px
    int   thickness   = 1;     // the same thickness in physical px
    int   round       = 1;     // inner-edge corner leg, measured from the inner box
    int   outerRound  = 1;     // outer-edge corner leg, measured from the outer box
    Paint paint       = Paint::Line;
    float alpha       = 1.f;
    bool  clipped     = false; // only the part inside `clip` is drawn
    IBox  clip;
};

// A flat chamfered rectangle (edge tabs and their glow).
struct Fill {
    IBox  box;
    int   round = 1;
    Paint paint = Paint::Line;
    float alpha = 1.f;
};

// How a style is drawn.
enum class Kind {
    Rings, // concentric chamfered bands round the window, drawn with the compositor's border shader
    Panel, // a notched outline with traces and beads, drawn from small baked images (panel.hpp)
};

// How many columns of characters a glyph style can have along each straight side of the outline.
constexpr int kGlyphColumns = 3;

// A look. New HUDs are new entries in the registry in geometry.cpp.
struct Style {
    const char* name;

    float lineAlpha;

    // Glow halos on both sides of the line, drawn as bands with a quadratic
    // alpha falloff.
    float haloAlpha;       // alpha of the brightest band
    float haloReach;       // logical px the halo extends past the line
    float floatBoost;      // brightness factor for floating windows
    float haloInnerReach;  // logical px of halo on the window side of the line
    float haloInnerFactor; // inner halo brightness relative to the outer one

    // Corner brackets: the line, thicker and brighter, near each corner.
    float bracketLen; // logical px of each arm; 0 disables brackets
    int   bracketExtra;      // logical px thicker than the line on each side
    int   bracketGlowReach;  // logical px of glow around the brackets
    float bracketGlowAlpha;

    // Tabs in the middle of each edge.
    float tabLen; // logical px; 0 disables tabs
    int   tabExtra;
    float tabAlpha;
    int   tabGlowGrow[2];
    float tabGlowAlpha[2];

    // How far the bright colours are mixed towards white.
    float brightWhiten;

    // The glow that slowly travels along the line (theme `hud_sweep`).
    float sweepAlpha;  // peak opacity at its centre; 0 turns the sweep off for this style
    float sweepWhiten; // how far its core is mixed towards white

    // Panel styles only (Kind::Panel). They use lineAlpha, haloAlpha, haloReach
    // and floatBoost like the ring styles do.
    Kind  kind        = Kind::Rings;
    float notchDepth  = 0; // logical px the outline steps towards the window at a notch
    float traceOffset = 0; // logical px the outer traces run beyond the outline
    float beadRadius  = 0; // logical px; 0 draws no beads and no runners
    float runnerSpeed = 1; // speed of the runner dots relative to the travelling glow

    // Glyph styles let characters fall along the straight sides of the outline,
    // in columns on the line and beyond it, inside its glow (panel.hpp).
    float glyphHeight  = 0; // logical px; 0 has no characters
    float glyphPitch   = 0; // logical px between two characters of a column
    float glyphFall    = 0; // how fast they fall, relative to the travelling glow
    float glyphGlow    = 0; // how far the glow round a character reaches past its strokes, in character heights
    float glyphKnock   = 0; // how dark a plate behind a character is, 0..1: it dims the line it stands on
    int   glyphColumns = 1; // 1 to kGlyphColumns: each column beyond the first is smaller, dimmer, softer and slower than the one before, which looks further away

    // Glow lamps: slow glows that pulse and go to and fro along the top and the
    // bottom edge, a few on each edge, in place of the one glow round the outline.
    int lamps = 0; // at most this many on an edge; 0 has no lamps
};

struct Params {
    int    width  = 0; // window size in physical px
    int    height = 0;
    float  scale  = 1.f;
    int    cut    = 0;   // corner leg of the window itself, physical px
    float  roundingPower = 1.f;
    bool   floating = false;

    // theme knobs
    double gap            = 6;
    double lineWidth      = 3;
    double chamfer        = 10;
    double floatGlowRange = 14;
    double glowRange      = 0;
    std::optional<double> glowAlpha;
    double sweepLength    = 180; // logical px: how long a lamp is at most, which decides how many fit on an edge
    double sideOpacity    = 1;   // 0..1: how visible the outline of a panel style is down its left and right sides (1: as everywhere else); the corners fade between a side and an edge
    double edgeOpacity    = 1;   // 0..1: the same along its top and bottom edge
    double underglow      = 0;   // 0..1: how bright a glow is that lies along the top and the bottom edge and fades out away from the window, as if it shone from under it; 0 has none

    // The size, in physical px, of the scanner's picture (the theme's `hud_scanner`): a panel style
    // bulges its outline out at the bottom right corner to hold it. 0 has no scanner, so no pod.
    int scannerW = 0;
    int scannerH = 0;
};

// The rounded rectangle through the middle of the line: the track the sweep
// follows, in the same window-relative physical px as the rings.
struct Centreline {
    double x = 0, y = 0, w = 0, h = 0;
    double leg      = 0; // corner leg
    double power    = 1; // corner rounding power
    double reachIn  = 0; // room for glow on the window side, without covering the window
    double reachOut = 0; // room for glow outside, up to where the outer halo ends
};

// A point of a stroke; `alpha` fades the line along its length.
struct Vertex {
    double x = 0, y = 0;
    float  alpha = 1.f;
};

// A straight run of a stroke, drawn as a 2 x N image stretched along it: the
// first texel column holds the colour at one end, the second the colour at the
// other, and N rows hold what the line looks like across itself.
struct StripPiece {
    IBox   box;        // along the run and, across it, at natural size
    bool   vertical = false;
    Vec2   a, b;       // the ends of the run on the centre line
    float  alphaA = 1.f, alphaB = 1.f;
    double centre = 0; // coordinate of the centre line across the run
};

// A piece of a stroke inside a tile, with the line's opacity at both ends.
struct TileSeg {
    Vec2  a, b;
    float alphaA = 1.f, alphaB = 1.f;
};

// A small image of a stroke where it turns: the part of the stroke near
// `box`, running out to the box's edges.
struct TilePiece {
    IBox                 box;
    std::vector<TileSeg> segs;
};

// A line made of straight and 45 degree runs, in window-relative physical px.
// A closed stroke is cut open where it is invisible, or else half way along
// its longest straight run.
struct Stroke {
    std::vector<Vertex> pts;
    bool                closed = false;
    float               alpha  = 1.f; // overall opacity of the line; 0 for a glow with no line
    Paint               core   = Paint::Line;
    Paint               halo   = Paint::Glow;
    double              halfWidth = 1; // half the line's thickness, px
    double              reach     = 0; // how far the halo reaches past the line's edge, px
    float               haloAlpha = 0; // halo opacity at the line's edge

    // Where the stroke is cut into drawable pieces (see stamp.hpp).
    std::vector<StripPiece> strips;
    std::vector<TilePiece>  tiles;
};

// A dot: a bright core with a soft halo.
struct Bead {
    Vec2   pos;
    double radius    = 1;
    double reach     = 0;
    float  haloAlpha = 0;
    float  alpha     = 1.f;
};

// A dot that travels along a stroke while its window has focus: round and round
// a closed stroke, back and forth on an open one.
struct Runner {
    int    stroke = 0;   // index into Panel::strokes
    double offset = 0;   // where it starts, as a fraction of the stroke (of one way, on an open one)
    double speed  = 1;   // relative to the other runners; a negative one runs the other way
    Bead   look;         // `pos` is unused
};

// How far apart two dots light each other up: fully within `near` px, not at
// all from `far` px on, smoothly in between.
struct Proximity {
    double near = 0;
    double far  = 0;
};

// The characters of a glyph style.
struct GlyphFace {
    double height    = 0; // px; 0 has no characters
    double halfWidth = 0; // half the thickness of a stroke of a character, px
    double reach     = 0; // how far the glow reaches past a stroke's edge, px
    float  haloAlpha = 0;
    double pitch     = 0; // px between two characters of a column
    double fall      = 0; // how fast a column falls, in the units of `travelled` (see glyphDraws)
    float  knock     = 0; // opacity of the dark plate behind a character, 0..1
    float  dim       = 1; // how bright its characters are at most, 0..1 of what they would be
    double soft      = 0; // how much softer than a pixel the edge of a stroke is, px; the columns further away are out of focus

    bool on() const { return height > 0; }
};

// A column of characters on a straight side of the outline. Its cells are where
// the characters a head leaves behind stay and fade; the heads themselves glide
// between them.
struct RainLane {
    int x       = 0; // whole px, the middle of the characters
    int y0      = 0; // whole px, the middle of the first (topmost) cell; the rest are the face's pitch apart
    int cells   = 0; // how many cells the column has
    int streams = 1; // how many falls it has at once
    int column  = 0; // 0 for the column on the line, 1 for the one beyond it, 2 for the one beyond that: see Panel::face
};

// A glow that goes slowly to and fro along an edge of the outline and pulses
// while it does. It is drawn with the travelling glow of the Neon HUD (sweep.hpp).
struct Lamp {
    double from   = 0; // the stretch of Panel::track its middle moves along: px from the start of the track
    double to     = 0;
    double length = 1; // relative to the theme's glow length
    double speed  = 1; // relative to the travelling glow's; a negative one starts the other way
    double offset = 0; // where it starts, as a fraction of a trip there and back
    double period = 5; // seconds one pulse takes
    double phase  = 0; // where in its pulse it starts, 0..1
    double step   = 1; // px: its place is a multiple of this, so that it is redrawn only when it has gone this far
};

struct Panel {
    std::vector<Stroke> strokes; // strokes[0] is the closed outline round the window; the underglow, if any, is the last two: glows with no line along its top and its bottom edge
    std::vector<Bead>   beads;   // dots that stay where they are
    std::vector<Runner> runners;

    // A dot going round a closed stroke swells into `flare` (drawn over it) when
    // another dot is near: one running on an open stroke (`touch`, measured in a
    // straight line) or the other one going round (`merge`, measured along the
    // stroke). A flare of radius 0 turns this off.
    Bead      flare = {{}, 0.0, 0.0, 0.f, 1.f}; // no radius: none
    Proximity touch;
    Proximity merge;

    // A glyph style lets characters fall in columns along the straight sides:
    // `glyphs` are those of the column on the line, `farGlyphs` those of the
    // second column, beyond it, and `deepGlyphs` those of the third, beyond that,
    // as far as the style has them (each a smaller, dimmer, softer and slower face
    // than the one before).
    GlyphFace             glyphs;
    GlyphFace             farGlyphs;
    GlyphFace             deepGlyphs;
    std::vector<RainLane> lanes; // top to bottom of the left side's columns, then of the right side's

    // The face of column `column` of the lanes, 0 to kGlyphColumns - 1 (anything else
    // is clamped). A column the panel has none of has a face that is not on.
    const GlyphFace& face(int column) const { return column <= 0 ? glyphs : column == 1 ? farGlyphs : deepGlyphs; }

    // A lamp style has glows on the top and the bottom edge. They follow `track`,
    // the outline with its sides masked out (alpha 0), so that no glow runs where
    // the characters fall.
    std::vector<Vertex> track;
    std::vector<Lamp>   lamps;

    bool empty() const { return strokes.empty(); }
};

// The pod: where the outline of a panel style bulges out at the bottom right corner, in place of the
// chamfer, to hold the scanner. The outline itself goes round it, so the dots that travel along the outline
// skirt it; the scanner draws the plate inside and a bezel on the window's side of it (scanner.hpp).
struct Pod {
    bool on = false; // false: no pod, the corner is chamfered like the others

    IBox picture; // where the scanner's picture goes, window-relative physical px

    // The plate, a convex shape clockwise, window-relative physical px, with the lines of the outline running
    // along it: its first `bezel` edges (from the first vertex) are the bezel, which is on the window and
    // has no outline of its own; the rest lie on the centre line of the outline.
    std::vector<Vec2> plate;
    int               bezel     = 3;
    double            halfWidth = 1; // half the thickness of the line, px
};

struct Layout {
    bool              valid = false;
    std::vector<Ring> rings;  // drawn in order
    std::vector<Fill> fills;  // drawn after all rings, in order
    Panel             panel;  // the shapes of a Kind::Panel style; empty for ring styles
    Pod               pod;    // the scanner's place in a Kind::Panel style that makes room for one
    IBox              sampleBox; // box the line gradient is normalised over
    Centreline        centre;
    Extents           extents;
};

constexpr int kMinWindow = 40; // physical px; smaller windows get no HUD

// Corner-leg change per pixel of outward offset (1 for round corners,
// 2 - sqrt(2) for 45 degree chamfers), the same rule Hyprland's own border uses.
double concentricFactor(double roundingPower);

// Looks up a style by name; nullptr when unknown.
const Style* styleFor(std::string_view name);

// Every registered style, so the tests cover a new look without being edited.
std::span<const Style> allStyles();

Layout  buildLayout(const Style& style, const Params& params);

// Extents do not depend on the window size, only on style, scale and theme.
Extents extentsFor(const Style& style, const Params& params);

} // namespace smplhud
