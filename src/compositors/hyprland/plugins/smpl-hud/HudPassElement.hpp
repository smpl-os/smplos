#pragma once

#define WLR_USE_UNSTABLE

#include <array>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <hyprland/src/config/shared/complex/ComplexDataTypes.hpp>
#include <hyprland/src/render/Texture.hpp>
#include <hyprland/src/render/pass/PassElement.hpp>

#include "geometry.hpp"
#include "gradient.hpp"
#include "panel.hpp"
#include "scanner.hpp"
#include "sweep.hpp"

// The colours one shape kind (smplhud::Paint) is drawn with, mid-fade or not.
struct SHudPaint {
    Config::CGradientValueData to;
    Config::CGradientValueData from; // only meaningful while fading
    bool                       fading = false;
    float                      lerp   = 1.F;
};

// The glow image uploaded to the GPU, kept from frame to frame: it changes
// only when the glow moves or its colour visibly changes, not every time the
// window repaints.
struct SHudSweepCache {
    std::shared_ptr<const smplhud::Path> path; // what the texture was drawn for
    double                               at    = -1;
    int                                  texel = 0;
    smplhud::SweepShape                  shape;
    smplhud::IBox                        limit;
    std::array<uint8_t, 4>               colour{}; // quantised r, g, b, strength
    smplhud::IBox                        box;      // where the texture goes, window-relative physical px
    SP<Render::ITexture>                 texture;
};

// One travelling glow of one window at one moment.
struct SHudSweep {
    std::shared_ptr<const smplhud::Path> path;
    smplhud::SweepShape                  shape;
    smplhud::IBox                        limit; // window-relative physical px the glow must stay inside
    int                                  texel = 1;
    double                               at    = 0; // distance along the path, physical px
    std::shared_ptr<SHudSweepCache>      cache;   // the glow's own: two glows never share one
    float                                intensity = 1.F; // fades the glow in and out, and a lamp's pulse; never part of the cached image
};

// The colours a theme gives the characters of a glyph style in place of those of
// the line. Each keeps the opacity the line has where it stands.
struct SHudGlyphColour {
    smplhud::Rgba line;   // the characters, and the glow around them
    smplhud::Rgba bright; // a character that is hot: the same colour, lighter
};

// Everything one frame of one window's HUD needs. It is copied out of the
// window when the pass element is queued, so drawing never touches the window
// or its decoration again.
struct SHudFrame {
    std::shared_ptr<const smplhud::Layout> layout;
    std::array<SHudPaint, 3>               paints; // indexed by smplhud::Paint
    std::vector<SHudSweep>                 sweeps; // one glow going round the line, or the lamps of a lamp style
    std::vector<smplhud::RunnerPose>       runners; // one per layout->panel.runners; their opacity already includes the fade with the focus, their glow says how much of the flare goes over them
    std::vector<smplhud::GlyphDraw>        glyphs;  // the falling characters of a glyph style
    std::optional<SHudGlyphColour>         glyphColour;
    float                                  alpha         = 1.F;
    float                                  glowAlpha     = 1.F;
    float                                  roundingPower = 1.F;
    CBox                                   window;  // window box, monitor-local physical px
    CBox                                   bounds;  // everything the HUD can touch, monitor-local logical px
};

// Drops the baked line, dot and character images a panel style keeps on the GPU,
// shared by all windows. They are baked again when next needed.
void clearHudStamps();

// Drops the frames of the scanner's loop that are kept on the GPU, shared by all
// windows. They are baked again when next needed.
void clearScannerFrames();

class CHudPassElement : public IPassElement {
  public:
    explicit CHudPassElement(SHudFrame frame);
    ~CHudPassElement() override = default;

    std::vector<UP<IPassElement>> draw() override;
    bool                          needsLiveBlur() override;
    bool                          needsPrecomputeBlur() override;
    std::optional<CBox>           boundingBox() override;

    const char* passName() override {
        return kPassName;
    }

    ePassElementType type() override {
        return EK_CUSTOM;
    }

    static constexpr const char* kPassName = "CSmplHudPassElement";

  private:
    SHudFrame m_frame;
};

// The scanner image uploaded to the GPU, kept for as long as the spec it was
// drawn for stays the same: a frozen scanner is drawn from it again and again.
// A moving one takes each frame from the loop that all windows share, or bakes
// its own while its colours are on the move. The plate under it is kept the same
// way as the picture; it changes only with the colours.
struct SScannerCache {
    smplhud::ScannerSpec spec;
    std::string          look; // what the frames of the loop depend on, as of the last frame drawn
    SP<Render::ITexture> texture;
    smplhud::PlateSpec   plateSpec;
    SP<Render::ITexture> plate;
};

// Everything one frame of the scanner of one window needs. Like a frame of the
// HUD it is copied out of the window when the pass element is queued.
struct SScannerFrame {
    std::array<SHudPaint, 3>               paints;    // indexed by smplhud::Paint
    smplhud::IBox                          sampleBox; // window-relative physical px: what the paints are spread over
    CBox                                   window;    // window box, monitor-local physical px
    CBox                                   box;       // where the picture goes, monitor-local physical px
    CBox                                   bounds;    // everything it can touch, plate and picture, monitor-local logical px
    smplhud::ScannerSize                   size;
    long                                   frame = 0; // the frame of the animation it shows
    uint32_t                               seed  = 0;
    float                                  alpha = 1.F;
    std::shared_ptr<const smplhud::Layout> layout;    // the frame's layout, for the pod: its plate goes under the picture; none: the bare picture
    double                                 scale = 1;
    bool                                   blur  = false; // whether the glass of the plate may blur what it covers
    std::shared_ptr<SScannerCache>         cache;     // the scanner's own: two scanners never share one
};

class CScannerPassElement : public IPassElement {
  public:
    explicit CScannerPassElement(SScannerFrame frame);
    ~CScannerPassElement() override = default;

    std::vector<UP<IPassElement>> draw() override;
    bool                          needsLiveBlur() override;
    bool                          needsPrecomputeBlur() override;
    std::optional<CBox>           boundingBox() override;

    const char* passName() override {
        return kPassName;
    }

    ePassElementType type() override {
        return EK_CUSTOM;
    }

    static constexpr const char* kPassName = "CSmplHudScannerPassElement";

  private:
    SScannerFrame m_frame;
};
