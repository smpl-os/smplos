#include "geometry.hpp"

#include "panel.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numbers>
#include <vector>

namespace smplhud {

namespace {

const Style kStyles[] = {
    {
        .name            = "scifi",
        .lineAlpha       = 0.90f,
        .haloAlpha       = 0.76f,
        .haloReach       = 14.f,
        .floatBoost      = 1.45f,
        .haloInnerReach  = 4.f,
        .haloInnerFactor = 0.70f,
        .bracketLen      = 30.f,
        .bracketExtra    = 2,
        .bracketGlowReach = 3,
        .bracketGlowAlpha = 0.28f,
        .tabLen          = 56.f,
        .tabExtra        = 2,
        .tabAlpha        = 0.95f,
        .tabGlowGrow     = {5, 2},
        .tabGlowAlpha    = {0.10f, 0.14f},
        .brightWhiten    = 0.32f,
        .sweepAlpha      = 0.80f,
        .sweepWhiten     = 0.55f,
    },
    {
        .name            = "minimal",
        .lineAlpha       = 0.85f,
        .haloAlpha       = 0.30f,
        .haloReach       = 8.f,
        .floatBoost      = 1.30f,
        .haloInnerReach  = 3.f,
        .haloInnerFactor = 0.60f,
        .bracketLen      = 0.f,
        .bracketExtra    = 0,
        .bracketGlowReach = 0,
        .bracketGlowAlpha = 0.f,
        .tabLen          = 0.f,
        .tabExtra        = 0,
        .tabAlpha        = 0.f,
        .tabGlowGrow     = {0, 0},
        .tabGlowAlpha    = {0.f, 0.f},
        .brightWhiten    = 0.f,
        .sweepAlpha      = 0.55f,
        .sweepWhiten     = 0.30f,
    },
    {
        .name            = "panel",
        .lineAlpha       = 0.95f,
        .haloAlpha       = 0.55f,
        .haloReach       = 9.f,
        .floatBoost      = 1.30f,
        .haloInnerReach  = 0.f,
        .haloInnerFactor = 0.f,
        .bracketLen      = 0.f,
        .bracketExtra    = 0,
        .bracketGlowReach = 0,
        .bracketGlowAlpha = 0.f,
        .tabLen          = 0.f,
        .tabExtra        = 0,
        .tabAlpha        = 0.f,
        .tabGlowGrow     = {0, 0},
        .tabGlowAlpha    = {0.f, 0.f},
        .brightWhiten    = 0.55f,
        .sweepAlpha      = 0.70f,
        .sweepWhiten     = 0.45f,
        .kind            = Kind::Panel,
        .notchDepth      = 9.f,
        .traceOffset     = 7.5f,
        .beadRadius      = 2.5f,
        .runnerSpeed     = 0.8f,
    },
    {
        // The panel's outline alone, standing on the window's edge, with a rain
        // of characters falling down both sides in three columns outside it, inside
        // its glow, and glows going slowly to and fro along the top and the
        // bottom: the Matrix HUD.
        .name            = "matrix",
        .lineAlpha       = 0.90f,
        .haloAlpha       = 0.85f,
        .haloReach       = 22.f,
        .floatBoost      = 1.30f,
        .haloInnerReach  = 0.f,
        .haloInnerFactor = 0.f,
        .bracketLen      = 0.f,
        .bracketExtra    = 0,
        .bracketGlowReach = 0,
        .bracketGlowAlpha = 0.f,
        .tabLen          = 0.f,
        .tabExtra        = 0,
        .tabAlpha        = 0.f,
        .tabGlowGrow     = {0, 0},
        .tabGlowAlpha    = {0.f, 0.f},
        .brightWhiten    = 0.55f,
        .sweepAlpha      = 0.95f,
        .sweepWhiten     = 0.22f,
        .kind            = Kind::Panel,
        .notchDepth      = 9.f,
        .glyphHeight     = 14.f,
        .glyphPitch      = 16.f,
        .glyphFall       = 0.6f,
        .glyphGlow       = 0.45f,
        .glyphColumns    = 3,
        .lamps           = 2,
    },
};

// Mirrors the renderer, which turns a logical border size into physical
// pixels with std::round on a float product.
int physPx(int logical, float scale) {
    return int(std::round(float(logical) * scale));
}

int roundInt(double v) {
    return int(std::lround(v));
}

struct Pt {
    double x, y;
};

// Point on a window-corner curve |a|^p + |b|^p = 1 for the top-left corner,
// where `leg` is how far the curve starts from the corner along each edge.
Pt cornerPoint(double originX, double originY, double leg, double exponent, double phi) {
    return {originX + leg * (1 - std::pow(std::cos(phi), exponent)), originY + leg * (1 - std::pow(std::sin(phi), exponent))};
}

double distanceToSegment(Pt p, Pt a, Pt b) {
    const double dx = b.x - a.x, dy = b.y - a.y;
    const double len2 = dx * dx + dy * dy;
    const double t    = len2 > 0 ? std::clamp(((p.x - a.x) * dx + (p.y - a.y) * dy) / len2, 0.0, 1.0) : 0.0;
    return std::hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

class Builder {
  public:
    Builder(const Style& st, const Params& p, Layout& out) :
        m_st(st), m_p(p), m_out(out), m_w(p.width), m_h(p.height), m_s(p.scale), m_k(concentricFactor(p.roundingPower)) {}

    void build() {
        const int bs = std::max(1, roundInt(m_p.lineWidth));
        const int T  = physPx(bs, m_s);
        m_gap        = m_p.gap * m_s;
        m_legAtGap   = std::max(m_p.chamfer * m_s, m_p.cut + m_gap * m_k);

        const int io = std::max(0, roundInt(m_gap - T / 2.0));
        const int oo = io + T;

        const int haloEnd = outerHalo(oo);
        innerHalo(io);
        m_out.rings.push_back(ring(io, bs, Paint::Line, m_st.lineAlpha));
        brackets(io, bs);
        tabs(io, oo, T);

        const double c        = io + T / 2.0;
        const double trackLeg = (leg(io) + leg(oo)) / 2.0;
        const double inward   = std::min(c, windowClearance(c, trackLeg) + 0.5);
        m_out.centre          = {-c, -c, m_w + 2 * c, m_h + 2 * c, trackLeg, std::max(1.0, double(m_p.roundingPower)), std::max(0.0, inward - 1.0), std::max(0.0, haloEnd - c)};

        m_out.sampleBox = {-oo, -oo, m_w + 2 * oo, m_h + 2 * oo};
        extents();
        m_out.valid = true;
    }

  private:
    const Style&  m_st;
    const Params& m_p;
    Layout&       m_out;
    int           m_w, m_h;
    float         m_s;
    double        m_k;
    double        m_gap       = 0;
    double        m_legAtGap  = 0;

    // Corner leg at `off` px outside the window box: concentric with the
    // window's own cut corner, clamped so it fits the box.
    int leg(int off) const {
        const int cap = std::max(1, std::min(m_w, m_h) / 2 + off);
        return std::clamp(roundInt(m_legAtGap + (off - m_gap) * m_k), 1, cap);
    }

    // Whether a window-relative point is inside the window's own (cut) corner,
    // for points near the top-left corner.
    bool insideWindow(Pt p, double cut, double power) const {
        if (p.x < 0 || p.y < 0)
            return false;
        if (p.x >= cut || p.y >= cut)
            return true;
        const double a = (cut - p.x) / cut, b = (cut - p.y) / cut;
        return std::pow(a, power) + std::pow(b, power) <= 1.0;
    }

    // How far the centre track stays from the window itself at the top-left
    // corner, in px (0 if it cuts into the window). The track is concentric
    // with the window's corner everywhere except where the theme's chamfer
    // floor makes it cut deeper than the window does.
    double windowClearance(double c, double trackLeg) const {
        constexpr int kTrackSteps = 16, kWindowSteps = 32;

        const double cut   = std::clamp<double>(m_p.cut, 0.0, std::min(m_w, m_h) / 2.0);
        const double power = std::max(1.0, double(m_p.roundingPower));
        const double e     = 2.0 / power;

        // the window's boundary over the top-left quadrant, starting and ending mid-edge
        std::vector<Pt> boundary{{0, m_h / 2.0}, {0, cut}};
        for (int i = 1; i < kWindowSteps && cut > 0; ++i)
            boundary.push_back(cornerPoint(0, 0, cut, e, (std::numbers::pi / 2) * i / kWindowSteps));
        boundary.push_back({cut, 0});
        boundary.push_back({m_w / 2.0, 0});

        double best = std::numeric_limits<double>::infinity();
        for (int j = 0; j <= kTrackSteps; ++j) {
            const Pt track = cornerPoint(-c, -c, trackLeg, e, (std::numbers::pi / 2) * j / kTrackSteps);
            if (insideWindow(track, cut, power))
                return 0;
            for (size_t i = 0; i + 1 < boundary.size(); ++i)
                best = std::min(best, distanceToSegment(track, boundary[i], boundary[i + 1]));
        }
        return best;
    }

    Ring ring(int innerOffset, int borderSize, Paint paint, float alpha) const {
        Ring r;
        r.borderSize = borderSize;
        r.thickness  = physPx(borderSize, m_s);
        r.inner      = {-innerOffset, -innerOffset, m_w + 2 * innerOffset, m_h + 2 * innerOffset};
        r.round      = leg(innerOffset);
        r.outerRound = leg(innerOffset + r.thickness);
        r.paint      = paint;
        r.alpha      = alpha;
        return r;
    }

    // Splits `reach` logical px into `n` bands of whole logical px (band j of n).
    static int bandSize(int reach, int n, int j) {
        return reach * j / n - reach * (j - 1) / n;
    }

    // Offset (px outside the window box) where the outer halo ends.
    int outerHalo(int startOffset) {
        const double reachD = m_p.floating ? std::max<double>(m_st.haloReach, m_p.floatGlowRange) : m_st.haloReach;
        const int    reach  = std::max(0, roundInt(reachD));
        if (reach < 2 || m_st.haloAlpha <= 0.f)
            return startOffset;

        const float boost = m_p.floating ? m_st.floatBoost : 1.f;
        const int   n     = std::clamp(roundInt(reach / 2.0), 2, std::min(8, reach));

        int offset = startOffset;
        for (int j = 1; j <= n; ++j) {
            const int   size = bandSize(reach, n, j);
            const float fall = 1.f - (j - 0.5f) / n;
            m_out.rings.push_back(ring(offset, size, Paint::Glow, m_st.haloAlpha * boost * fall * fall));
            offset += physPx(size, m_s);
        }
        return offset;
    }

    // Glow on the window side of the line, between it and the window.
    void innerHalo(int lineInnerOffset) {
        const int reach = std::max(0, roundInt(m_st.haloInnerReach));
        if (reach < 1 || lineInnerOffset <= 0 || m_st.haloInnerFactor <= 0.f || m_st.haloAlpha <= 0.f)
            return;

        const int n = std::clamp(roundInt(reach / 2.0), 1, std::min(3, reach));

        int outerOffset = lineInnerOffset;
        for (int j = 1; j <= n; ++j) {
            const int size  = bandSize(reach, n, j);
            const int inner = outerOffset - physPx(size, m_s);
            if (inner < 0)
                break;
            const float fall = 1.f - (j - 0.5f) / n;
            m_out.rings.push_back(ring(inner, size, Paint::Glow, m_st.haloAlpha * m_st.haloInnerFactor * fall * fall));
            outerOffset = inner;
        }
    }

    void brackets(int lineInnerOffset, int lineSize) {
        if (m_st.bracketLen <= 0.f)
            return;

        const int extra     = physPx(m_st.bracketExtra, m_s);
        const int size      = lineSize + 2 * m_st.bracketExtra;
        const int offset    = std::max(0, lineInnerOffset - extra);
        const int thick     = physPx(size, m_s);
        const int glowSize  = size + 2 * m_st.bracketGlowReach;
        const int glowOff   = std::max(0, offset - physPx(m_st.bracketGlowReach, m_s));
        const int glowOuter = glowOff + physPx(glowSize, m_s);

        const int centre = offset + thick / 2;
        const int arm    = std::min({roundInt(m_st.bracketLen * m_s), m_w / 3, m_h / 3});
        const int far    = -centre + leg(centre) + arm; // arm end, measured from the corner along the edge
        const int lo     = -(glowOuter + 1);

        // One clip box per corner, from just outside the glow to the arm end.
        const int  span = far - lo;
        const IBox corner[4] = {
            {lo, lo, span, span},
            {m_w - far, lo, span, span},
            {lo, m_h - far, span, span},
            {m_w - far, m_h - far, span, span},
        };

        for (const auto& c : corner) {
            Ring r   = ring(glowOff, glowSize, Paint::Glow, m_st.bracketGlowAlpha);
            r.clipped = true;
            r.clip    = c;
            m_out.rings.push_back(r);
        }
        for (const auto& c : corner) {
            Ring r   = ring(offset, size, Paint::Bright, 1.f);
            r.clipped = true;
            r.clip    = c;
            m_out.rings.push_back(r);
        }
    }

    void tabs(int lineInnerOffset, int lineOuterOffset, int lineThickness) {
        if (m_st.tabLen <= 0.f)
            return;

        const int len   = roundInt(m_st.tabLen * m_s);
        const int extra = physPx(m_st.tabExtra, m_s);
        const int thick = lineThickness + 2 * extra;
        const int round = std::max(1, thick / 2);

        // Centred on each edge; skipped where the edge is too short to carry one.
        std::vector<IBox> tabs;
        if (m_w >= 3 * len) {
            const int x = roundInt(m_w / 2.0 - len / 2.0);
            tabs.push_back({x, -(lineOuterOffset + extra), len, thick});
            tabs.push_back({x, m_h + lineInnerOffset - extra, len, thick});
        }
        if (m_h >= 3 * len) {
            const int y = roundInt(m_h / 2.0 - len / 2.0);
            tabs.push_back({-(lineOuterOffset + extra), y, thick, len});
            tabs.push_back({m_w + lineInnerOffset - extra, y, thick, len});
        }

        for (int g = 0; g < 2; ++g) {
            const int grow = physPx(m_st.tabGlowGrow[g], m_s);
            if (grow <= 0 || m_st.tabGlowAlpha[g] <= 0.f)
                continue;
            for (const auto& t : tabs)
                m_out.fills.push_back({{t.x - grow, t.y - grow, t.w + 2 * grow, t.h + 2 * grow}, round + grow, Paint::Glow, m_st.tabGlowAlpha[g]});
        }
        for (const auto& t : tabs)
            m_out.fills.push_back({t, round, Paint::Bright, m_st.tabAlpha});
    }

    void extents() {
        int left = 0, top = 0, right = 0, bottom = 0;
        const auto grow = [&](const IBox& b) {
            left   = std::max(left, -b.x);
            top    = std::max(top, -b.y);
            right  = std::max(right, b.x + b.w - m_w);
            bottom = std::max(bottom, b.y + b.h - m_h);
        };

        for (const auto& r : m_out.rings)
            grow({r.inner.x - r.thickness, r.inner.y - r.thickness, r.inner.w + 2 * r.thickness, r.inner.h + 2 * r.thickness});
        for (const auto& f : m_out.fills)
            grow(f.box);

        const auto logical = [&](int phys) { return phys <= 0 ? 0 : int(std::ceil(phys / m_s)) + 2; };
        m_out.extents      = {logical(left), logical(top), logical(right), logical(bottom)};
    }
};

} // namespace

double concentricFactor(double roundingPower) {
    return 1.0 - (std::sqrt(2.0) - 1.0) * std::max(2.0 - roundingPower, 0.0);
}

const Style* styleFor(std::string_view name) {
    for (const auto& s : kStyles) {
        if (name == s.name)
            return &s;
    }
    return nullptr;
}

std::span<const Style> allStyles() {
    return kStyles;
}

Layout buildLayout(const Style& style, const Params& params) {
    Layout out;
    if (params.width < kMinWindow || params.height < kMinWindow || params.scale <= 0.f)
        return out;

    Style effective = style;
    if (params.glowRange > 0)
        effective.haloReach = float(params.glowRange);
    if (params.glowAlpha)
        effective.haloAlpha = float(*params.glowAlpha);
    if (effective.kind == Kind::Panel)
        buildPanel(effective, params, out);
    else
        Builder(effective, params, out).build();
    return out;
}

Extents extentsFor(const Style& style, const Params& params) {
    Params nominal = params;
    nominal.width  = 2000;
    nominal.height = 2000;
    return buildLayout(style, nominal).extents;
}

} // namespace smplhud
