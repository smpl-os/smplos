#include "HudDecoration.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <optional>
#include <span>
#include <vector>

#include <hyprland/src/Compositor.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/helpers/MiscFunctions.hpp>
#include <hyprland/src/helpers/time/Time.hpp>
#include <hyprland/src/layout/LayoutManager.hpp>
#include <hyprland/src/managers/SessionLockManager.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>
#include <hyprland/src/managers/fullscreen/FullscreenController.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopTimer.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/decorations/DecorationPositioner.hpp>

#include "HudPassElement.hpp"
#include "ScannerDecoration.hpp"
#include "globals.hpp"
#include "place.hpp"
#include "stamp.hpp"

namespace {
    using smplhud::Paint;

    SHudSettings                 g_settings;
    smplhud::Extents             g_extents;
    std::vector<CHudDecoration*> g_decorations;
    PHLWINDOWREF                 g_focus; // the window last given focus

    // Windows waiting for the compositor to finish moving them to another
    // workspace before they are placed, and the callback that does it.
    std::vector<PHLWINDOWREF> g_placeQueue;
    UP<SEventLoopDoLaterLock> g_placeLater;
    // One timer moves the travelling glow of the focused window, or its lamps
    // and falling characters, and fades out those of the one that lost focus.
    // It runs only while the theme asks for them, and while nothing could be
    // seen moving it backs off to a slow poll.
    SP<CEventLoopTimer>                 g_sweepTimer;
    Time::steady_tp                     g_sweepLast;
    bool                                g_sweepIdle = true; // on the slow poll
    constexpr std::chrono::milliseconds kSweepIdlePoll{250};
    constexpr std::chrono::milliseconds kSweepFadeStep{33}; // a fade shows steps the glow's own pace hides
    constexpr double                    kSweepMaxStep   = 0.25; // s; a long stall must not make the glow jump
    constexpr double                    kSweepFade      = 0.5;  // s for the glow to fade in or out
    constexpr int                       kSweepWaitSteps = 8;    // how long a focused glow waits for its first draw

    // The speed, in logical px a second, of the fastest thing the HUD moves:
    // the glow, the dots of a panel, which run ahead of it, or the characters
    // that fall. It sets how often the timer steps.
    double motionSpeed() {
        const auto*  style   = g_settings.style;
        const double fastest = style ? std::max({1.0, double(style->runnerSpeed), double(style->glyphFall)}) : 1.0;
        return g_settings.theme.sweepSpeed * fastest;
    }

    void sweepTick(SP<CEventLoopTimer> self, void*) {
        const auto   now = Time::steadyNow();
        const double dt  = std::min(std::chrono::duration<double>(now - g_sweepLast).count(), kSweepMaxStep);
        g_sweepLast      = now;

        syncHudFocus(); // focus can move without anyone being told

        CHudDecoration::SSweepStep all;
        if (!g_pSessionLockManager || !g_pSessionLockManager->isSessionLocked()) {
            for (auto* deco : g_decorations) {
                const auto step = deco->advanceSweep(dt);
                all.moved       = all.moved || step.moved;
                all.fading      = all.fading || step.fading;
            }
        }

        g_sweepIdle = !all.moved;

        // The scanners move on the beats of the glow: a picture of their own in
        // between would only make the compositor draw one more.
        if (all.moved)
            stepHudScanners();

        std::chrono::duration<double> next = kSweepIdlePoll;
        if (all.moved) {
            next = std::chrono::duration<double>(smplhud::sweepInterval(motionSpeed()));
            if (all.fading)
                next = std::min(next, std::chrono::duration<double>(kSweepFadeStep));
        }
        self->updateTimeout(std::chrono::duration_cast<Time::steady_dur>(next));
    }

    // Has the timer step soon: a window has just been given focus.
    void wakeHudSweep() {
        if (!g_sweepTimer)
            return;

        if (g_sweepIdle) {
            g_sweepLast = Time::steadyNow(); // not the whole time it slept
            g_sweepIdle = false;
        }
        g_sweepTimer->updateTimeout(std::chrono::duration_cast<Time::steady_dur>(std::chrono::milliseconds{1}));
    }

    void syncHudSweep() {
        if (g_settings.sweeping()) {
            if (!g_sweepTimer) {
                g_sweepLast  = Time::steadyNow();
                g_sweepIdle  = true;
                g_sweepTimer = makeShared<CEventLoopTimer>(std::chrono::duration_cast<Time::steady_dur>(kSweepIdlePoll), sweepTick, nullptr);
                g_pEventLoopManager->addTimer(g_sweepTimer);
            }
            return;
        }

        stopHudSweep();
        for (auto* deco : g_decorations)
            deco->dropSweep();
    }

    // The gradients a theme can set turning in a loop. The compositor starts
    // each loop when a window maps and, when a lap ends, calls its own function
    // to start the next; that call is all the focus has to take away or give back.
    using LoopEnd = void (Desktop::View::CWindow::*)(WP<Hyprutils::Animation::CBaseAnimatedVariable>);

    struct SLoop {
        PHLANIMVAR<float> Desktop::View::CWindow::* var;
        LoopEnd                                     end;
    };

    constexpr std::array<SLoop, 3> kLoops = {{
        {&Desktop::View::CWindow::m_borderAngleAnimationProgress, &Desktop::View::CWindow::onBorderAngleAnimEnd},
        {&Desktop::View::CWindow::m_glowAngleAnimationProgress, &Desktop::View::CWindow::onGlowAngleAnimEnd},
        {&Desktop::View::CWindow::m_shadowAngleAnimationProgress, &Desktop::View::CWindow::onShadowAngleAnimEnd},
    }};

    // The windows whose loops this plugin has taken a hook from or given one
    // to. Kept apart from the decorations: a window that is unmapped, or whose
    // decoration is gone, must still be given back when the plugin unloads.
    std::vector<PHLWINDOWREF> g_scoped;

    void remember(const PHLWINDOW& window) {
        std::erase_if(g_scoped, [](const PHLWINDOWREF& ref) { return ref.expired(); });
        if (std::ranges::none_of(g_scoped, [&](const PHLWINDOWREF& ref) { return ref == window; }))
            g_scoped.emplace_back(window);
    }

    bool looping(const PHLANIMVAR<float>& var) {
        return var->enabled() && var->getStyle() == "loop";
    }

    // Fullscreen has no border, glow or frame, so nothing is left to turn. Asked
    // of the controller: the window's cached border size is not yet updated when
    // the fullscreen event arrives.
    bool fullscreen(const PHLWINDOW& window) {
        return Fullscreen::controller()->getFullscreenModes(window).internal == Fullscreen::FSMODE_FULLSCREEN;
    }

    // Whether the window gets a frame: when it has a border to replace. A theme
    // that hides Hyprland's border (so the frame is the only line) has none left
    // to ask, so there only the window's own opt-outs count: fullscreen,
    // decorations off and a border size rule of 0.
    bool framed(const PHLWINDOW& window) {
        if (window->getRealBorderSize() >= 1)
            return true;
        if (!g_settings.theme.hideBorder)
            return false;

        const auto& rules = window->m_ruleApplicator;
        return rules->decorate().valueOrDefault() && !fullscreen(window) && rules->borderSize().valueOr(1) >= 1;
    }

    // Only the focused window's gradients turn. A loop runs lap after lap, each
    // lap's end starting the next: the focused window keeps that going, the
    // others finish the lap they are on and then rest, which looks the same as
    // a gradient that never turned (a whole lap is one full turn).
    void scopeLoops(const PHLWINDOW& window, bool focused) {
        remember(window);

        for (const auto& loop : kLoops) {
            const auto& var = (*window).*loop.var;
            if (!var)
                continue;

            if (!focused) {
                var->setCallbackOnEnd(nullptr); // first: warping runs the hook
                if (var->isBeingAnimated() && var->value() < 0.02F)
                    var->setValueAndWarp(1.F); // a lap only just begun is nothing to wait for
                continue;
            }

            if (!looping(var))
                continue;

            // At the end of a lap the compositor's own function starts the next
            // and puts its own hook back. On a gradient at rest that is at once.
            var->setCallbackOnEnd(
                [ref = PHLWINDOWREF(window), end = loop.end](WP<Hyprutils::Animation::CBaseAnimatedVariable> self) {
                    if (const auto target = ref.lock())
                        ((*target).*end)(self);
                },
                true);
        }
    }

    // The room the scanner takes in the corner of a window, for a theme and a
    // monitor scale: the frame is laid out round it.
    smplhud::ScannerSize scannerSizeOf(const SHudSettings& settings, double scale) {
        return smplhud::scannerSize(smplhud::scannerWidthOf(settings.theme.scanner), scale);
    }

    // Every window registers the same extents, so a theme change is one
    // re-registration. They only have to cover the widest look (floating).
    smplhud::Extents canonicalExtents(const SHudSettings& settings) {
        if (!settings.active())
            return {};

        const auto size = scannerSizeOf(settings, 1.0);

        smplhud::Params params;
        params.scale          = 1.F;
        params.floating       = true;
        params.gap            = settings.theme.gap;
        params.lineWidth      = settings.theme.lineWidth;
        params.chamfer        = settings.theme.chamfer;
        params.floatGlowRange = settings.theme.floatGlowRange;
        params.glowRange      = settings.theme.glowRange;
        params.glowAlpha      = settings.theme.glowAlpha;
        params.scannerW       = size.w;
        params.scannerH       = size.h;
        return smplhud::extentsFor(*settings.style, params);
    }

    // The window box in global logical coordinates, moved by whatever
    // animations the compositor is applying right now.
    CBox windowBoxGlobal(const PHLWINDOW& window) {
        CBox       box       = window->getWindowMainSurfaceBox();
        const auto workspace = window->m_workspace;
        if (workspace && workspace->m_renderOffset->isBeingAnimated() && !window->m_pinned)
            box.translate(workspace->m_renderOffset->value());
        box.translate(window->m_floatingOffset);
        return box;
    }

    // The same box in logical coordinates relative to `monitor`, from the live
    // animated geometry the window surface itself is drawn with.
    CBox windowBoxLocal(const PHLWINDOW& window, const PHLMONITOR& monitor) {
        const auto workspace = window->m_workspace;
        const auto offset    = workspace && !window->m_pinned ? workspace->m_renderOffset->value() : Vector2D();
        CBox       box       = {window->position(Desktop::View::IGeometric::GEOMETRIC_CURRENT), window->size(Desktop::View::IGeometric::GEOMETRIC_CURRENT)};
        box.translate(-monitor->m_position + offset + window->m_floatingOffset);
        return box;
    }

    CBox grown(const CBox& box, const smplhud::Extents& e, int slack) {
        return {box.x - e.left - slack, box.y - e.top - slack, box.width + e.left + e.right + 2 * slack, box.height + e.top + e.bottom + 2 * slack};
    }

    bool visible(const Config::CGradientValueData& gradient) {
        return std::ranges::any_of(gradient.m_colors, [](const CHyprColor& c) { return c.a >= 0.01; });
    }

    // Mirrors what the compositor's own border and glow decorations do with a
    // window's gradient, on a copy so the window's state stays untouched.
    template <typename AnimVar>
    SHudPaint animatedPaint(const Config::CGradientValueData& current, Config::CGradientValueData previous, const AnimVar& angle, const AnimVar& fade) {
        SHudPaint paint;
        paint.to = current;

        if (angle->enabled()) {
            paint.to.m_angle += angle->value() * M_PI * 2;
            paint.to.m_angle = normalizeAngleRad(paint.to.m_angle);
            previous.m_angle = paint.to.m_angle; // a rotating gradient should not also fade between two angles
        }

        if (fade->isBeingAnimated()) {
            paint.fading = true;
            paint.lerp   = fade->value();
            paint.from   = std::move(previous);
        }
        return paint;
    }

    SHudPaint whitened(const SHudPaint& source, float amount) {
        const auto whiten = [amount](const Config::CGradientValueData& gradient) {
            std::vector<CHyprColor> colors;
            colors.reserve(gradient.m_colors.size());
            for (const auto& c : gradient.m_colors)
                colors.emplace_back(c.r + (1.0 - c.r) * amount, c.g + (1.0 - c.g) * amount, c.b + (1.0 - c.b) * amount, c.a);
            return Config::CGradientValueData(std::move(colors), gradient.m_angle);
        };

        SHudPaint out = source;
        out.to        = whiten(source.to);
        out.from      = whiten(source.from);
        return out;
    }

    // The colours of a window's frame as it is now, mid-fade or not: the
    // border gradient for the line, the glow gradient for the glow (the line's
    // where the theme has none) and the line's, lightened, for what is bright.
    // None while the window has no border colour yet.
    std::optional<std::array<SHudPaint, 3>> paintsOf(const PHLWINDOW& window) {
        std::array<SHudPaint, 3> paints;

        auto& line = paints[size_t(Paint::Line)];
        line       = animatedPaint(window->m_realBorderColor, window->m_realBorderColorPrevious, window->m_borderAngleAnimationProgress, window->m_borderFadeAnimationProgress);
        if (line.to.m_colorsOkLabA.empty())
            return std::nullopt;

        auto& glow = paints[size_t(Paint::Glow)];
        glow       = animatedPaint(window->m_realGlowColor, window->m_realGlowColorPrevious, window->m_glowAngleAnimationProgress, window->m_glowFadeAnimationProgress);
        if (!visible(glow.to))
            glow = line;

        paints[size_t(Paint::Bright)] = whitened(line, g_settings.style->brightWhiten);
        return paints;
    }

    // The colour a theme gives the characters of a glyph style, and the same
    // `amount` lighter for the ones that are hot.
    SHudGlyphColour glyphColourOf(const smplhud::Rgb8& colour, float amount) {
        const smplhud::Rgba line{colour.r / 255.F, colour.g / 255.F, colour.b / 255.F, 1.F};
        const auto          lighter = [amount](float v) { return v + (1.F - v) * amount; };
        return {line, {lighter(line.r), lighter(line.g), lighter(line.b), 1.F}};
    }

    // Adds to `region` the boxes, in global logical px, of the dots of `panel`
    // that are visible once they have travelled `travelled`. `origin` is the
    // window's box.
    void addRunnerBoxes(CRegion& region, const smplhud::Panel& panel, double travelled, const CBox& origin, double scale) {
        const auto poses = smplhud::runnerPoses(panel, travelled);
        for (size_t i = 0; i < poses.size(); ++i) {
            const auto& pose = poses[i];
            if (pose.alpha <= 0.F)
                continue;

            // A dot that glows is drawn with the flare over it.
            int size = smplhud::beadSize(smplhud::lookOf(panel.runners[i].look));
            if (pose.glow > 0.F)
                size = std::max(size, smplhud::beadSize(smplhud::lookOf(panel.flare)));

            const double half = size / 2.0 + 1;
            CBox         box  = {origin.x + (pose.pos.x - half) / scale, origin.y + (pose.pos.y - half) / scale, 2 * half / scale, 2 * half / scale};
            region.add(CRegion(box.expand(2)));
        }
    }

    // The falling characters of a glyph style, `level` of the way into the fade
    // with the focus, once the columns have fallen `travelled`. None is lit while
    // the window has no focus.
    std::vector<smplhud::GlyphDraw> glyphsAt(const smplhud::Panel& panel, double travelled, double level, unsigned seed) {
        if (!panel.glyphs.on())
            return {};

        return smplhud::glyphDraws(panel, travelled, smplhud::sweepIntensity(level), seed);
    }

    // The shape of the glow of a lamp in `pose`: the theme's `shape`, longer or
    // shorter by the pose's length.
    smplhud::SweepShape lampShape(smplhud::SweepShape shape, const smplhud::LampPose& pose) {
        shape.halfLength *= pose.length;
        return shape;
    }

    // Adds to `region` the boxes, in global logical px, of the characters
    // `glyphs` of `panel`. `origin` is the window's box.
    void addGlyphBoxes(CRegion& region, const smplhud::Panel& panel, std::span<const smplhud::GlyphDraw> glyphs, const CBox& origin, double scale) {
        std::array<smplhud::GlyphSize, smplhud::kGlyphColumns> sizes;
        for (size_t column = 0; column < sizes.size(); ++column)
            sizes[column] = smplhud::glyphSize(panel.face(int(column)));
        for (const auto& glyph : glyphs) {
            const auto   size = sizes[size_t(std::clamp(glyph.column, 0, smplhud::kGlyphColumns - 1))];
            const double w    = size.w + 2;
            const double h    = size.h + 2;
            CBox         box  = {origin.x + (glyph.x - w / 2) / scale, origin.y + (glyph.y - h / 2) / scale, w / scale, h / scale};
            region.add(CRegion(box.expand(2)));
        }
    }
}

const SHudSettings& hudSettings() {
    return g_settings;
}

bool hudFramed(const PHLWINDOW& window) {
    return framed(window);
}

bool hudFullscreen(const PHLWINDOW& window) {
    return fullscreen(window);
}

CBox hudWindowBoxGlobal(const PHLWINDOW& window) {
    return windowBoxGlobal(window);
}

CBox hudWindowBoxLocal(const PHLWINDOW& window, const PHLMONITOR& monitor) {
    return windowBoxLocal(window, monitor);
}

float hudFadeOf(const PHLWINDOW& window, float a) {
    const float windowOpacity = window->m_ruleApplicator->opaque().valueOrDefault() ? 1.F : window->alphaValue(Desktop::View::WINDOW_ALPHA_ACTIVE);
    return std::clamp(a / std::max(windowOpacity, 0.001F), 0.F, 1.F);
}

std::optional<SHudColours> hudColoursOf(const PHLWINDOW& window) {
    for (const auto* deco : g_decorations) {
        if (deco->window() == window)
            return deco->colours();
    }
    return std::nullopt;
}

std::optional<SHudLayout> hudLayoutOf(const PHLWINDOW& window) {
    for (const auto* deco : g_decorations) {
        if (deco->window() == window)
            return deco->layout();
    }
    return std::nullopt;
}

bool hudSweepBeating() {
    return g_sweepTimer && !g_sweepIdle;
}

void placeHudWindow(const PHLWINDOW& window) {
    if (!g_settings.active() || !validMapped(window) || !window->m_isFloating || window->m_group || window->m_wantsInitialFullscreen || window->m_X11DoesntWantBorders ||
        window->isX11OverrideRedirect())
        return;

    const auto target  = window->layoutTarget();
    const auto monitor = window->m_monitor.lock();
    if (!target || !monitor || !framed(window) || Fullscreen::controller()->getFullscreenModes(window).internal != Fullscreen::FSMODE_NONE)
        return;

    // A window being dragged or resized is where the user puts it.
    if (g_layoutManager->dragController()->target() == target)
        return;

    // The usable area, not the work area: that one keeps a gap of its own
    // from the edge, which the frame would be laid over.
    const CBox box    = target->position();
    const CBox usable = monitor->logicalBoxMinusReserved();
    const auto fitted = smplhud::fitWithFrame({box.x, box.y, box.w, box.h}, g_extents, {usable.x, usable.y, usable.w, usable.h});

    constexpr double kTolerance = 0.5; // the compositor rounds boxes to whole px
    if (std::abs(fitted.x - box.x) < kTolerance && std::abs(fitted.y - box.y) < kTolerance && std::abs(fitted.w - box.w) < kTolerance && std::abs(fitted.h - box.h) < kTolerance)
        return;

    target->setPositionGlobal(CBox{fitted.x, fitted.y, fitted.w, fitted.h});
}

void placeHudWindowLater(const PHLWINDOW& window) {
    if (!window || !g_settings.active())
        return;

    g_placeQueue.emplace_back(window);
    if (g_placeLater)
        return;

    g_placeLater = g_pEventLoopManager->doLaterLock([] {
        auto queue = std::move(g_placeQueue);
        g_placeQueue.clear();
        g_placeLater.reset();

        for (const auto& ref : queue)
            placeHudWindow(ref.lock());
    });
}

void stopHudPlacement() {
    g_placeLater.reset(); // takes a callback that has not run out of the compositor
    g_placeQueue.clear();
}

std::string runHudCommand(const std::string& request) {
    const auto address = smplhud::parseFitRequest(request);
    if (!address)
        return "usage: hyprctl smplhud fit <window address>";

    for (const auto& window : Desktop::windowState()->windows()) {
        if (reinterpret_cast<uintptr_t>(window.get()) != *address)
            continue;

        placeHudWindow(window);
        return "ok";
    }
    return "no such window";
}

void setHudTheme(const smplhud::Theme& theme) {
    for (auto* deco : g_decorations)
        deco->damageEntire();
    damageAllScanners();

    const auto previousExtents = g_extents;

    g_settings.theme = theme;
    g_settings.style = smplhud::styleFor(theme.style);
    g_settings.revision++;
    g_extents = canonicalExtents(g_settings);

    if (theme.frame && !g_settings.style)
        HyprlandAPI::addNotification(PHANDLE, "[smpl-hud] unknown hud_style '" + theme.style + "'", CHyprColor{1.0, 0.6, 0.2, 1.0}, 5000);

    for (auto* deco : g_decorations)
        deco->reposition();
    for (auto* deco : g_decorations)
        deco->damageEntire();
    damageAllScanners();

    // Windows that are open were placed for another frame, or for none. A
    // reload that keeps the frame must not undo where the user put a window.
    if (g_extents != previousExtents) {
        for (const auto& window : Desktop::windowState()->windows())
            placeHudWindow(window);
    }

    syncHudSweep();
    syncHudScanners();

    // Focus-only motion is the HUD's: without a HUD the compositor's loops are left alone.
    if (g_settings.active())
        syncHudFocus(true);
    else
        restoreHudLoops();
}

void stopHudSweep() {
    if (!g_sweepTimer)
        return;

    if (g_pEventLoopManager)
        g_pEventLoopManager->removeTimer(g_sweepTimer);
    g_sweepTimer.reset();
    g_sweepIdle = true;
}

void syncHudFocus(bool force) {
    const PHLWINDOW focused = Desktop::focusState()->window();
    if (!force && g_focus.lock() == focused)
        return;

    g_focus = focused;
    if (!g_settings.active())
        return;

    for (auto* deco : g_decorations)
        deco->syncFocus(focused, force);
    syncScannerFocus(focused);
}

void restoreHudLoops() {
    // At shutdown the windows are going anyway and nothing may be started.
    const bool shuttingDown = g_pCompositor && g_pCompositor->m_isShuttingDown;

    for (const auto& ref : g_scoped) {
        const auto window = ref.lock();
        if (!window)
            continue;

        for (const auto& loop : kLoops) {
            const auto& var = (*window).*loop.var;
            if (!var)
                continue;

            var->setCallbackOnEnd(nullptr); // whatever the state: none of this plugin's code may stay in a window
            if (!shuttingDown && looping(var))
                ((*window).*loop.end)(WP<Hyprutils::Animation::CBaseAnimatedVariable>(var));
        }
    }

    g_scoped.clear();
    g_focus.reset();
}

void damageAnimatedHuds() {
    for (auto* deco : g_decorations)
        deco->damageIfAnimated();
    damageAnimatedScanners();
}

void damageAllHuds() {
    for (auto* deco : g_decorations)
        deco->damageEntire();
    damageAllScanners();
}

CHudDecoration::CHudDecoration(PHLWINDOW window) : IHyprWindowDecoration(window), m_window(window) {
    // Windows start at different points of their lines, spread by the golden
    // ratio, and their characters each keep a time of their own.
    static unsigned s_decorations = 0;
    m_sweep.phase                 = std::fmod(s_decorations * 0.6180339887498949, 1.0);
    m_seed                        = s_decorations++ * 2654435761U;

    g_decorations.push_back(this);
}

CHudDecoration::~CHudDecoration() {
    std::erase(g_decorations, this);
}

SDecorationPositioningInfo CHudDecoration::getPositioningInfo() {
    m_extents = g_extents;

    // Absolute and non-solid: the HUD only tells the compositor how far it
    // paints, so damage and culling cover it, and reserves no space.
    SDecorationPositioningInfo info;
    info.policy         = DECORATION_POSITION_ABSOLUTE;
    info.edges          = DECORATION_EDGE_TOP | DECORATION_EDGE_BOTTOM | DECORATION_EDGE_LEFT | DECORATION_EDGE_RIGHT;
    info.desiredExtents = {{double(m_extents.left), double(m_extents.top)}, {double(m_extents.right), double(m_extents.bottom)}};
    return info;
}

void CHudDecoration::onPositioningReply(const SDecorationPositioningReply&) {
    ;
}

void CHudDecoration::updateWindow(PHLWINDOW) {
    ;
}

eDecorationType CHudDecoration::getDecorationType() {
    return DECORATION_CUSTOM;
}

uint64_t CHudDecoration::getDecorationFlags() {
    return DECORATION_NON_SOLID;
}

eDecorationLayer CHudDecoration::getDecorationLayer() {
    return DECORATION_LAYER_UNDER;
}

std::string CHudDecoration::getDisplayName() {
    return kHudDisplayName;
}

void CHudDecoration::reposition() {
    if (validMapped(m_window.lock()))
        g_pDecorationPositioner->repositionDeco(this);
}

void CHudDecoration::damageEntire() {
    const auto window = m_window.lock();
    if (!validMapped(window))
        return;

    g_pHyprRenderer->damageBox(grown(windowBoxGlobal(window), m_extents, 2));
}

void CHudDecoration::damageIfAnimated() {
    const auto window = m_window.lock();
    if (!g_settings.active() || !validMapped(window))
        return;

    const bool animated = window->m_borderAngleAnimationProgress->isBeingAnimated() || window->m_borderFadeAnimationProgress->isBeingAnimated() ||
        window->m_glowAngleAnimationProgress->isBeingAnimated() || window->m_glowFadeAnimationProgress->isBeingAnimated();
    if (!animated || !g_pHyprRenderer->shouldRenderWindow(window))
        return;

    // The margin around the window plus the places where the HUD reaches into
    // the window box: the corner squares of a ring style, the pieces of a
    // panel's lines. Nothing else repaints.
    const CBox box = windowBoxGlobal(window);
    CRegion    region(grown(box, m_extents, 2));
    region.subtract(CRegion(box));

    if (m_layout && !m_layout->panel.empty()) {
        const double scale = m_layoutKey.scale;
        const auto   add   = [&](const smplhud::IBox& piece) {
            region.add(CRegion(CBox{box.x + piece.x / scale - 1, box.y + piece.y / scale - 1, piece.w / scale + 2, piece.h / scale + 2}));
        };
        for (const auto& stroke : m_layout->panel.strokes) {
            for (const auto& strip : stroke.strips)
                add(strip.box);
            for (const auto& tile : stroke.tiles)
                add(tile.box);
        }
        addGlyphBoxes(region, m_layout->panel, m_glyphs, box, scale); // their colours follow the gradient too
    } else {
        const double corner = window->rounding() + 2;
        for (const double cx : {box.x, box.x + box.width - corner}) {
            for (const double cy : {box.y, box.y + box.height - corner})
                region.add(CRegion(CBox{cx, cy, corner, corner}));
        }
    }

    g_pHyprRenderer->damageRegion(region);
}

std::optional<SHudColours> CHudDecoration::colours() const {
    const auto window = m_window.lock();
    if (!g_settings.active() || !validMapped(window) || !m_layout || !m_layout->valid)
        return std::nullopt;

    const auto paints = paintsOf(window);
    if (!paints)
        return std::nullopt;

    return SHudColours{*paints, m_layout->sampleBox};
}

std::optional<SHudLayout> CHudDecoration::layout() const {
    if (!g_settings.active() || !m_layout || !m_layout->valid)
        return std::nullopt;

    return SHudLayout{m_layout, m_layoutKey.scale, m_layoutKey.width, m_layoutKey.height};
}

void CHudDecoration::buildSweep(float scale) {
    if (m_sweep.path || !m_layout)
        return;

    // A panel's glow runs along its outline; the lamps of a lamp style run along
    // their track, which is that outline with the sides of the window masked.
    const auto& layout = *m_layout;
    const auto& panel  = layout.panel;
    auto        path   = std::make_shared<const smplhud::Path>(panel.empty() ? smplhud::buildPath(layout.centre) : smplhud::buildPath(panel.track.empty() ? panel.strokes.front().pts : panel.track));
    if (!path->valid())
        return;

    const auto& theme  = g_settings.theme;
    const auto& style  = *g_settings.style;
    const auto& e      = m_layout->extents;
    const int   left   = int(std::ceil(e.left * scale));
    const int   top    = int(std::ceil(e.top * scale));
    const int   right  = int(std::ceil(e.right * scale));
    const int   bottom = int(std::ceil(e.bottom * scale));

    m_sweep.limit = {-left, -top, m_layoutKey.width + left + right, m_layoutKey.height + top + bottom};
    m_sweep.shape = {theme.sweepLength * scale / 2, m_layout->centre.reachOut, m_layout->centre.reachIn, style.sweepWhiten, style.sweepAlpha};
    m_sweep.texel = smplhud::sweepTexel(scale);
    m_sweep.scale = scale;
    m_sweep.cache.reset();
    m_lamps.assign(panel.lamps.size(), {});
    m_sweep.path = std::move(path);
}

void CHudDecoration::dropSweep() {
    m_sweep.path.reset();
    m_sweep.cache.reset();
    m_lamps.clear();
    m_sweepLevel = 0;
}

void CHudDecoration::syncFocus(const PHLWINDOW& focused, bool force) {
    setFocused(focused && m_window.lock() == focused, force);
}

void CHudDecoration::setFocused(bool focused, bool force) {
    const bool changed = focused != m_focused;
    m_focused          = focused;

    if (changed || force) {
        if (const auto window = m_window.lock())
            scopeLoops(window, focused && !fullscreen(window));
    }

    if (!changed)
        return;

    m_waiting = 0;
    wakeHudSweep();
    if (focused || g_settings.theme.glowFocusedOnly)
        damageEntire(); // the draw it causes builds the glow's path
}

CHudDecoration::SSweepStep CHudDecoration::advanceSweep(double seconds) {
    if (!m_focused && m_sweepLevel <= 0)
        return {};

    const auto window = m_window.lock();
    if (!g_settings.sweeping() || !validMapped(window) || !framed(window))
        return {};

    const auto monitor = window->m_monitor.lock();
    if (!monitor || !monitor->m_enabled || !monitor->m_dpmsStatus || !g_pHyprRenderer->shouldRenderWindow(window, monitor)) {
        if (!m_focused)
            dropSweep(); // out of sight: nothing to fade out
        return {};
    }

    if (!m_sweep.path || !m_layout) // the first draw builds it; stay quick for a little while to start on time
        return {.moved = m_focused && m_waiting++ < kSweepWaitSteps};

    const double levelBefore = m_sweepLevel;
    m_sweepLevel             = smplhud::sweepFade(m_sweepLevel, m_focused, seconds, kSweepFade);

    // A lamp style has lamps on its track, not a glow going round the outline.
    const auto&  panel  = m_layout->panel;
    const auto&  path   = *m_sweep.path;
    const bool   lamps  = !panel.track.empty();
    const double before = m_sweep.phase * path.length;
    if (!lamps)
        m_sweep.phase = smplhud::sweepAdvance(m_sweep.phase, seconds, g_settings.theme.sweepSpeed, m_sweep.scale, path.length);
    const double after = m_sweep.phase * path.length;

    const double dotsBefore = m_dotPos;
    m_dotPos += seconds * g_settings.theme.sweepSpeed * g_settings.style->runnerSpeed * m_sweep.scale;
    m_clock += seconds;

    // The glow leaves one box and enters another, and so does each dot, lamp or
    // character that changes; nothing else repaints.
    const CBox origin = windowBoxGlobal(window);
    CRegion    region;
    const auto addGlow = [&](double at, const smplhud::SweepShape& shape) {
        const auto box = smplhud::sweepBounds(path, at, shape, m_sweep.texel, m_sweep.limit);
        if (box.w <= 0 || box.h <= 0)
            return;

        CBox logical = {origin.x + box.x / m_sweep.scale, origin.y + box.y / m_sweep.scale, box.w / m_sweep.scale, box.h / m_sweep.scale};
        region.add(CRegion(logical.expand(2)));
    };

    if (lamps) {
        // A lamp is redrawn when it has gone a step further, pulsed a step, or
        // while the lamps fade in or out.
        const bool fadeStep = m_sweepLevel != levelBefore;
        for (size_t i = 0; i < m_lamps.size(); ++i) {
            const auto pose = smplhud::lampPose(panel, i, m_dotPos, m_clock, m_seed);
            if (pose == m_lamps[i].pose && !fadeStep)
                continue;

            addGlow(m_lamps[i].pose.at, lampShape(m_sweep.shape, m_lamps[i].pose));
            addGlow(pose.at, lampShape(m_sweep.shape, pose));
            m_lamps[i].pose = pose;
        }
    } else {
        for (const double at : {before, after})
            addGlow(at, m_sweep.shape);
    }

    if (panel.glyphs.on()) {
        auto now = glyphsAt(panel, m_dotPos, m_sweepLevel, m_seed);
        addGlyphBoxes(region, panel, smplhud::glyphChanges(m_glyphs, now), origin, m_sweep.scale);
        m_glyphs = std::move(now);
    }

    if (!panel.runners.empty()) {
        addRunnerBoxes(region, panel, dotsBefore, origin, m_sweep.scale);
        addRunnerBoxes(region, panel, m_dotPos, origin, m_sweep.scale);
    }

    // Steps are fine enough to be several to a step of a lamp, so most change
    // nothing; the timer must still go on as often while something is moving,
    // and a falling head moves a little at every one of them.
    SSweepStep step;
    step.fading = m_sweepLevel > 0 && m_sweepLevel < 1;
    step.moved  = !lamps || !m_lamps.empty() || !panel.lanes.empty();

    if (!m_focused && m_sweepLevel <= 0)
        dropSweep(); // faded out; the damage below repaints without it

    if (!region.empty())
        g_pHyprRenderer->damageRegion(region);
    return step;
}

void CHudDecoration::draw(PHLMONITOR monitor, const float& a) {
    const auto window = m_window.lock();
    if (!g_settings.active() || !monitor || !validMapped(window) || !framed(window))
        return;

    const float scale    = monitor->m_scale;
    const CBox  local    = windowBoxLocal(window, monitor);
    const CBox  physical = local.copy().scale(scale).round();
    if (physical.width < smplhud::kMinWindow || physical.height < smplhud::kMinWindow) {
        dropSweep();
        return;
    }

    const SLayoutKey key = {
        .width         = int(physical.width),
        .height        = int(physical.height),
        .cut           = int(window->rounding() * scale),
        .scale         = scale,
        .roundingPower = window->roundingPower(),
        .floating      = window->m_isFloating,
        .revision      = g_settings.revision,
    };

    if (!m_layout || !(key == m_layoutKey)) {
        const auto& theme   = g_settings.theme;
        const auto  scanner = scannerSizeOf(g_settings, key.scale);

        smplhud::Params params;
        params.width          = key.width;
        params.height         = key.height;
        params.scale          = key.scale;
        params.cut            = key.cut;
        params.roundingPower  = key.roundingPower;
        params.floating       = key.floating;
        params.gap            = theme.gap;
        params.lineWidth      = theme.lineWidth;
        params.chamfer        = theme.chamfer;
        params.floatGlowRange = theme.floatGlowRange;
        params.glowRange      = theme.glowRange;
        params.glowAlpha      = theme.glowAlpha;
        params.sweepLength    = theme.sweepLength;
        params.sideOpacity    = theme.sideOpacity;
        params.edgeOpacity    = theme.edgeOpacity;
        params.underglow      = theme.underglow;
        params.scannerW       = scanner.w;
        params.scannerH       = scanner.h;

        m_layout    = std::make_shared<const smplhud::Layout>(smplhud::buildLayout(*g_settings.style, params));
        m_layoutKey = key;
        m_sweep.path.reset(); // the path follows the layout
        m_lamps.clear();      // and so do the lamps on it
        m_glyphs.clear();     // and the places of the characters
    }

    if (!m_layout->valid)
        return;

    if (g_settings.sweeping() && (m_focused || m_sweepLevel > 0))
        buildSweep(scale);
    else
        dropSweep();

    SHudFrame frame;
    frame.layout = m_layout;

    const auto paints = paintsOf(window);
    if (!paints)
        return;
    frame.paints = *paints;

    if (const auto& own = g_settings.theme.glyphColour)
        frame.glyphColour = glyphColourOf(*own, g_settings.style->brightWhiten);

    frame.alpha         = hudFadeOf(window, a);
    if (g_settings.theme.glowFocusedOnly && !m_focused)
        frame.glowAlpha = 0;
    frame.roundingPower = key.roundingPower;
    frame.window        = physical;
    frame.bounds        = grown(local, m_extents, 2);

    const float intensity = float(smplhud::sweepIntensity(m_sweepLevel));
    const auto& panel     = m_layout->panel;
    if (m_sweep.path && intensity > 0.002F) {
        if (!panel.track.empty()) {
            // The lamps, each in the pose it is in now and with a glow of its own.
            for (size_t i = 0; i < m_lamps.size(); ++i) {
                auto& lamp = m_lamps[i];
                lamp.pose  = smplhud::lampPose(panel, i, m_dotPos, m_clock, m_seed);
                if (!lamp.cache)
                    lamp.cache = std::make_shared<SHudSweepCache>();
                frame.sweeps.push_back(SHudSweep{m_sweep.path, lampShape(m_sweep.shape, lamp.pose), m_sweep.limit, m_sweep.texel, lamp.pose.at, lamp.cache, intensity * lamp.pose.strength});
            }
        } else {
            if (!m_sweep.cache)
                m_sweep.cache = std::make_shared<SHudSweepCache>();
            frame.sweeps.push_back(SHudSweep{m_sweep.path, m_sweep.shape, m_sweep.limit, m_sweep.texel, m_sweep.phase * m_sweep.path->length, m_sweep.cache, intensity});
        }

        if (!panel.runners.empty()) {
            frame.runners = smplhud::runnerPoses(panel, m_dotPos);
            for (auto& pose : frame.runners)
                pose.alpha *= intensity;
        }
    }

    // The characters are worked out from the same state the steps of the timer
    // compare with. None is lit while the window has no focus.
    if (panel.glyphs.on()) {
        frame.glyphs = glyphsAt(panel, m_dotPos, m_sweepLevel, m_seed);
        m_glyphs     = frame.glyphs;
    }

    g_pHyprRenderer->addPassElement(makeUnique<CHudPassElement>(std::move(frame)));
}
