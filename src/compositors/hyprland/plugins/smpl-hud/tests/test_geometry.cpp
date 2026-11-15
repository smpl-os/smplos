#include "../geometry.hpp"
#include "check.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>
#include <vector>

using namespace smplhud;

namespace {

// Neon at 1x: rounding 42 at power 1 gives a 21 px cut.
Params neon(float scale = 1.f, bool floating = false) {
    Params p;
    p.width          = int(std::lround(1200 * scale));
    p.height         = int(std::lround(800 * scale));
    p.scale          = scale;
    p.cut            = int(std::lround(21 * scale));
    p.roundingPower  = 1.f;
    p.floating       = floating;
    p.floatGlowRange = 18; // Neon's hud_float_glow_range
    return p;
}

const Style& scifi() {
    return *styleFor("scifi");
}

const Ring* findLine(const Layout& l) {
    for (const auto& r : l.rings) {
        if (r.paint == Paint::Line)
            return &r;
    }
    return nullptr;
}

void testRegistry() {
    CHECK(styleFor("scifi") != nullptr);
    CHECK(styleFor("minimal") != nullptr);
    CHECK(styleFor("nope") == nullptr);
    CHECK(styleFor("") == nullptr);

    // A name has to survive the theme generator (lowercase letters, digits,
    // '-' and '_') and be unique, or styleFor() could not find the style.
    const auto styles = allStyles();
    CHECK(styles.size() >= 2);
    for (const Style& st : styles) {
        const std::string_view name = st.name;
        CHECK(!name.empty());
        CHECK(std::ranges::all_of(name, [](char c) { return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '_'; }));
        CHECK(styleFor(name) == &st);
    }
}

void testConcentricFactor() {
    CHECK_NEAR(concentricFactor(1.0), 2.0 - std::sqrt(2.0), 1e-12);
    CHECK_NEAR(concentricFactor(2.0), 1.0, 1e-12);
    CHECK_NEAR(concentricFactor(4.0), 1.0, 1e-12);
    CHECK(concentricFactor(1.5) > concentricFactor(1.0) && concentricFactor(1.5) < 1.0);
}

void testLineRing() {
    const Layout l = buildLayout(scifi(), neon());
    CHECK(l.valid);

    const Ring* line = findLine(l);
    CHECK(line != nullptr);
    if (!line)
        return;

    // gap 6, line 3: the band spans offsets 5..8 around the window box
    CHECK(line->inner.x == -5 && line->inner.y == -5);
    CHECK(line->inner.w == 1200 + 10 && line->inner.h == 800 + 10);
    CHECK(line->borderSize == 3 && line->thickness == 3);

    // concentric 45 degree chamfers: the leg grows by (2 - sqrt 2) per px outwards
    CHECK(line->round >= 20 && line->round <= 28);
    CHECK(line->outerRound - line->round >= 1 && line->outerRound - line->round <= 3);
    CHECK(line->alpha > 0.5f);
}

void testChamferFloor() {
    Params p = neon();
    p.cut    = 0; // square window
    const Layout l = buildLayout(scifi(), p);
    const Ring*  line = findLine(l);
    CHECK(line != nullptr);
    if (!line)
        return;
    // the theme chamfer (10) wins over the window's own cut
    CHECK(line->round >= 8 && line->round <= 12);
}

void testHaloBandsAreContiguous() {
    for (float s : {1.f, 1.25f, 1.5f, 2.f, 3.f}) {
        for (bool floating : {false, true}) {
            const Layout l = buildLayout(scifi(), neon(s, floating));
            CHECK(l.valid);

            const Ring* line = findLine(l);
            CHECK(line != nullptr);
            if (!line)
                continue;
            const int lineIn  = -line->inner.x;
            const int lineOut = lineIn + line->thickness;

            // Unclipped glow bands by distance from the window, nearest first.
            std::vector<const Ring*> bands;
            for (const auto& r : l.rings)
                if (r.paint == Paint::Glow && !r.clipped)
                    bands.push_back(&r);
            std::ranges::sort(bands, {}, [](const Ring* r) { return -r->inner.x; });

            int outerChain = 0, innerChain = 0;
            int expectOuter = lineOut; // next outer band starts where the line ends
            for (const Ring* r : bands) {
                const int in = -r->inner.x;
                if (in >= lineOut) {
                    CHECK(in == expectOuter);
                    expectOuter = in + r->thickness;
                    ++outerChain;
                } else {
                    // window-side bands must stay clear of the line itself
                    CHECK(in + r->thickness <= lineIn);
                    ++innerChain;
                }
            }
            CHECK(outerChain >= 2);
            CHECK(innerChain >= 1);

            // window-side bands chain up to the line
            int expectEnd = lineIn;
            for (auto it = bands.rbegin(); it != bands.rend(); ++it) {
                const int in = -(*it)->inner.x;
                if (in >= lineOut)
                    continue;
                CHECK(in + (*it)->thickness == expectEnd);
                expectEnd = in;
            }
        }
    }
}

void testFloatingIsBrighterAndWider() {
    // The fixture only proves "wider" if the theme asks for more than the style's own reach.
    CHECK(neon(1.f, true).floatGlowRange > scifi().haloReach);

    const Layout tiled = buildLayout(scifi(), neon(1.f, false));
    const Layout flt   = buildLayout(scifi(), neon(1.f, true));
    CHECK(flt.extents.left > tiled.extents.left);

    float tiledPeak = 0, floatPeak = 0;
    for (const auto& r : tiled.rings)
        if (r.paint == Paint::Glow && !r.clipped)
            tiledPeak = std::max(tiledPeak, r.alpha);
    for (const auto& r : flt.rings)
        if (r.paint == Paint::Glow && !r.clipped)
            floatPeak = std::max(floatPeak, r.alpha);
    CHECK(floatPeak > tiledPeak);
}

void testWiderHaloKeepsBorderCrispAndFivePixelsVisible() {
    for (float scale : {1.f, 1.5f, 2.f}) {
        for (bool floating : {false, true}) {
            Params p = neon(scale, floating);
            p.gap = 1;
            p.lineWidth = 2;
            p.floatGlowRange = 0;
            const auto baseline = buildLayout(*styleFor("minimal"), p);
            p.glowRange = 18;
            p.glowAlpha = 0.9;
            const auto layout = buildLayout(*styleFor("minimal"), p);
            const auto* line = findLine(layout);
            const auto* original = findLine(baseline);
            CHECK(line && original);
            if (!line || !original)
                continue;
            CHECK(line->inner == original->inner);
            CHECK(line->thickness == original->thickness);
            CHECK(line->alpha == original->alpha);
            CHECK(layout.extents.left > baseline.extents.left);
            const int outer = -line->inner.x + line->thickness;
            const int fifthPixel = outer + int(std::lround(4 * scale));
            int reach = 0;
            float fifthAlpha = 0;
            for (const auto& ring : layout.rings) {
                if (ring.paint != Paint::Glow || -ring.inner.x < outer)
                    continue;
                const int start = -ring.inner.x;
                reach = std::max(reach, start + ring.thickness - outer);
                if (start <= fifthPixel && fifthPixel < start + ring.thickness)
                    fifthAlpha = ring.alpha;
            }
            CHECK(std::abs(reach - 18 * scale) <= 1);
            CHECK(fifthAlpha >= 0.35f);
        }
    }
}

void testShapesStayInsideExtents() {
    for (const Style& st : allStyles()) {
        for (float s : {1.f, 1.25f, 1.5f, 2.f}) {
            for (bool floating : {false, true}) {
                Params       p  = neon(s, floating);
                const Layout l  = buildLayout(st, p);
                CHECK(l.valid);

                const int left   = int(std::ceil(l.extents.left * s));
                const int top    = int(std::ceil(l.extents.top * s));
                const int right  = int(std::ceil(l.extents.right * s));
                const int bottom = int(std::ceil(l.extents.bottom * s));

                const auto inside = [&](const IBox& b) {
                    return b.x >= -left && b.y >= -top && b.x + b.w <= p.width + right && b.y + b.h <= p.height + bottom;
                };

                for (const auto& r : l.rings)
                    CHECK(inside({r.inner.x - r.thickness, r.inner.y - r.thickness, r.inner.w + 2 * r.thickness, r.inner.h + 2 * r.thickness}));
                for (const auto& f : l.fills)
                    CHECK(inside(f.box));
            }
        }
    }
}

void testExtentsIgnoreWindowSize() {
    Params a = neon();
    Params b = neon();
    b.width  = 300;
    b.height = 200;
    CHECK(extentsFor(scifi(), a) == extentsFor(scifi(), b));
    CHECK(buildLayout(scifi(), a).extents == buildLayout(scifi(), neon()).extents);
}

void testTooSmallWindow() {
    Params p = neon();
    p.width  = kMinWindow - 1;
    CHECK(!buildLayout(scifi(), p).valid);
    p.width  = kMinWindow;
    CHECK(buildLayout(scifi(), p).valid);
    p        = neon();
    p.scale  = 0.f;
    CHECK(!buildLayout(scifi(), p).valid);
}

void testBracketsAndTabs() {
    const Layout l = buildLayout(scifi(), neon());

    int clipped = 0, bright = 0, glowClipped = 0;
    for (const auto& r : l.rings) {
        if (r.clipped) {
            ++clipped;
            if (r.paint == Paint::Bright)
                ++bright;
            if (r.paint == Paint::Glow)
                ++glowClipped;
            CHECK(r.clip.w > 0 && r.clip.h > 0);
        }
    }
    CHECK(clipped == 8 && bright == 4 && glowClipped == 4);

    int tabs = 0;
    for (const auto& f : l.fills)
        if (f.paint == Paint::Bright)
            ++tabs;
    CHECK(tabs == 4);

    // tabs sit centred on their edge
    for (const auto& f : l.fills) {
        if (f.paint != Paint::Bright)
            continue;
        const bool horizontal = f.box.w > f.box.h;
        if (horizontal)
            CHECK(std::abs((f.box.x + f.box.w / 2) - 600) <= 1);
        else
            CHECK(std::abs((f.box.y + f.box.h / 2) - 400) <= 1);
    }
}

void testClipBoxesAreDisjointCorners() {
    const Layout l = buildLayout(scifi(), neon());
    std::vector<IBox> boxes;
    for (const auto& r : l.rings)
        if (r.clipped && r.paint == Paint::Bright)
            boxes.push_back(r.clip);
    CHECK(boxes.size() == 4);

    for (size_t i = 0; i < boxes.size(); ++i) {
        for (size_t j = i + 1; j < boxes.size(); ++j) {
            const IBox &a = boxes[i], &b = boxes[j];
            const bool overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
            CHECK(!overlap);
        }
    }
}

void testNarrowWindowsDropTabs() {
    Params p = neon();
    p.width  = 150; // less than three tab lengths
    const Layout l = buildLayout(scifi(), p);
    CHECK(l.valid);
    for (const auto& f : l.fills) {
        const bool horizontal = f.box.w > f.box.h;
        CHECK(!horizontal); // top and bottom tabs are dropped, side tabs stay
    }
}

void testMinimalHasNoOrnaments() {
    const Layout l = buildLayout(*styleFor("minimal"), neon());
    CHECK(l.valid);
    CHECK(l.fills.empty());
    for (const auto& r : l.rings)
        CHECK(!r.clipped);
}

void testRingsStayConcentric() {
    // Every ring's outer edge corner leg exceeds its inner one by about
    // (2 - sqrt 2) * thickness, so the bands keep a constant width on the diagonal.
    for (const Style& st : allStyles()) {
        if (st.kind != Kind::Rings)
            continue;
        for (float s : {1.f, 2.f}) {
            const Layout l = buildLayout(st, neon(s));
            for (const auto& r : l.rings) {
                if (r.clipped)
                    continue;
                const double expected = concentricFactor(1.0) * r.thickness;
                CHECK_NEAR(r.outerRound - r.round, expected, 1.01);
            }
        }
    }
}

void testCentrelineIsMiddleOfLine() {
    for (const Style& st : allStyles()) {
        if (st.kind != Kind::Rings)
            continue; // panels have no ring to measure against; test_panel covers them
        for (float s : {1.f, 1.25f, 2.f}) {
            for (bool floating : {false, true}) {
                const Params p = neon(s, floating);
                const Layout l = buildLayout(st, p);
                const Ring*  line = findLine(l);
                CHECK(line != nullptr);
                if (!line)
                    continue;

                const Centreline& c = l.centre;
                const double      half = line->thickness / 2.0;

                // the rounded rectangle through the middle of the line band
                CHECK_NEAR(c.x, line->inner.x - half, 1e-9);
                CHECK_NEAR(c.y, line->inner.y - half, 1e-9);
                CHECK_NEAR(c.w, line->inner.w + 2 * half, 1e-9);
                CHECK_NEAR(c.h, line->inner.h + 2 * half, 1e-9);
                CHECK(c.leg >= line->round && c.leg <= line->outerRound);
                CHECK_NEAR(c.power, 1.0, 1e-9);
            }
        }
    }
}

void testCentrelineReach() {
    for (const Style& st : allStyles()) {
        if (st.kind != Kind::Rings)
            continue;
        for (float s : {1.f, 1.5f, 2.f}) {
            for (bool floating : {false, true}) {
                const Params p = neon(s, floating);
                const Layout l = buildLayout(st, p);
                const Ring*  line = findLine(l);
                CHECK(line != nullptr);
                if (!line)
                    continue;

                const Centreline& c = l.centre;

                // room inside stops short of the window box (and of the window's own edge)
                CHECK(c.reachIn >= 0 && c.reachIn < -c.x);
                CHECK_NEAR(c.reachIn, -c.x - 1.0, 1e-9);

                // room outside ends exactly where the outermost halo band ends
                double haloEnd = -c.x;
                for (const auto& r : l.rings)
                    if (r.paint == Paint::Glow && !r.clipped)
                        haloEnd = std::max(haloEnd, double(-r.inner.x + r.thickness));
                CHECK_NEAR(c.reachOut, haloEnd + c.x, 1e-9);
                CHECK(c.reachOut > 0);
            }
        }
    }

    // floating windows get a wider halo, so more room for the glow outside
    CHECK(buildLayout(scifi(), neon(1.f, true)).centre.reachOut > buildLayout(scifi(), neon(1.f, false)).centre.reachOut);
}

void testCentrelineStaysInsideExtents() {
    for (const Style& st : allStyles()) {
        for (float s : {1.f, 1.25f, 1.5f, 2.f}) {
            for (bool floating : {false, true}) {
                const Params p = neon(s, floating);
                const Layout l = buildLayout(st, p);
                const Centreline& c = l.centre;

                const double left   = std::ceil(l.extents.left * s);
                const double top    = std::ceil(l.extents.top * s);
                const double right  = std::ceil(l.extents.right * s);
                const double bottom = std::ceil(l.extents.bottom * s);

                // the sweep's glow may reach `reachOut` outside the track
                CHECK(-c.x + c.reachOut <= left + 1e-9);
                CHECK(-c.y + c.reachOut <= top + 1e-9);
                CHECK(c.x + c.w + c.reachOut <= p.width + right + 1e-9);
                CHECK(c.y + c.h + c.reachOut <= p.height + bottom + 1e-9);
            }
        }
    }
}

void testCentrelineFollowsRoundingPower() {
    Params p = neon();
    p.roundingPower = 2.f;
    p.cut           = 21;
    CHECK_NEAR(buildLayout(scifi(), p).centre.power, 2.0, 1e-9);
    p.roundingPower = 4.f;
    CHECK_NEAR(buildLayout(scifi(), p).centre.power, 4.0, 1e-9);
    // Hyprland treats a power below 1 as 1; the track must stay a valid superellipse
    p.roundingPower = 0.f;
    CHECK(buildLayout(scifi(), p).centre.power >= 1.0);
}

void testEveryStyleCanSweep() {
    for (const Style& st : allStyles()) {
        CHECK(st.sweepAlpha > 0.f && st.sweepAlpha <= 1.f);
        CHECK(st.sweepWhiten >= 0.f && st.sweepWhiten <= 1.f);
    }
}

// Distance from `track` to the window's boundary near its top-left corner,
// found by brute force over a dense sampling of the boundary.
double bruteDistanceToWindow(double px, double py, double cut, double power) {
    double best = 1e18;
    const auto consider = [&](double x, double y) { best = std::min(best, std::hypot(px - x, py - y)); };
    for (int i = 0; i <= 4000; ++i) {
        consider(0, cut + i * 0.1);
        consider(cut + i * 0.1, 0);
    }
    for (int i = 0; i <= 4000; ++i) {
        const double phi = (std::numbers::pi / 2) * i / 4000;
        consider(cut * (1 - std::pow(std::cos(phi), 2 / power)), cut * (1 - std::pow(std::sin(phi), 2 / power)));
    }
    return best;
}

void testInnerReachNeverTouchesWindow() {
    struct Case {
        double cut;
        float  power;
        double chamfer;
        bool   cutsIntoWindow; // the theme chamfer is so big the line crosses the window's corner
    };
    const Case cases[] = {
        {21, 1.f, 10, false}, // Neon: the line is concentric with the window's cut
        {0, 1.f, 10, false},  // square window, chamfer floor close to the corner
        {0, 1.f, 30, true},   // chamfer floor deep inside the window
        {21, 2.f, 10, false}, // round
        {0, 2.f, 10, false},
        {30, 4.f, 10, false}, // squircle
    };

    for (const Case& cs : cases) {
        for (float s : {1.f, 2.f}) {
            Params p        = neon(s);
            p.cut           = int(std::lround(cs.cut * s));
            p.roundingPower = cs.power;
            p.chamfer       = float(cs.chamfer);

            const Layout l = buildLayout(scifi(), p);
            const Centreline& c = l.centre;
            CHECK(l.valid);

            if (cs.cutsIntoWindow) {
                CHECK(c.reachIn == 0);
                continue;
            }

            // every point of the track's corner stays at least reachIn (plus the
            // 1 px margin) away from the window
            const double e = 2.0 / c.power;
            for (int i = 0; i <= 64; ++i) {
                const double phi = (std::numbers::pi / 2) * i / 64;
                const double x   = c.x + c.leg * (1 - std::pow(std::cos(phi), e));
                const double y   = c.y + c.leg * (1 - std::pow(std::sin(phi), e));
                CHECK(c.reachIn + 0.5 <= bruteDistanceToWindow(x, y, p.cut, c.power) + 1e-6);
            }
            CHECK(c.reachIn > 0);
        }
    }
}

} // namespace

int main() {
    testRegistry();
    testConcentricFactor();
    testLineRing();
    testChamferFloor();
    testHaloBandsAreContiguous();
    testFloatingIsBrighterAndWider();
    testWiderHaloKeepsBorderCrispAndFivePixelsVisible();
    testShapesStayInsideExtents();
    testExtentsIgnoreWindowSize();
    testTooSmallWindow();
    testBracketsAndTabs();
    testClipBoxesAreDisjointCorners();
    testNarrowWindowsDropTabs();
    testMinimalHasNoOrnaments();
    testRingsStayConcentric();
    testCentrelineIsMiddleOfLine();
    testCentrelineReach();
    testCentrelineStaysInsideExtents();
    testCentrelineFollowsRoundingPower();
    testEveryStyleCanSweep();
    testInnerReachNeverTouchesWindow();
    return finish("test_geometry");
}
