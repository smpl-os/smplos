#include "../theme.hpp"
#include "check.hpp"

using namespace smplhud;

namespace {

void testDefaults() {
    const Theme t = parseTheme("");
    CHECK(!t.frame);
    CHECK_NEAR(t.gap, 5, 1e-9);
    CHECK_NEAR(t.lineWidth, 3, 1e-9);
    CHECK_NEAR(t.chamfer, 10, 1e-9);
    CHECK_NEAR(t.floatGlowRange, 0, 1e-9);
    CHECK(t.style == "scifi");
    CHECK(!t.sweep);
    CHECK_NEAR(t.sweepSpeed, 80, 1e-9);
    CHECK_NEAR(t.sweepLength, 180, 1e-9);
    CHECK(!t.hideBorder);
    CHECK_NEAR(t.sideOpacity, 1, 1e-9);
    CHECK_NEAR(t.edgeOpacity, 1, 1e-9);
    CHECK_NEAR(t.underglow, 0, 1e-9);
    CHECK_NEAR(t.scanner, 0, 1e-9);
    CHECK(t.scannerBlur);
    CHECK(!t.glyphColour);
    CHECK(t == Theme{});
}

void testNeonBlock() {
    const Theme t = parseTheme("$themeRounding = 42\n"
                               "$themeHudFrame = 1\n"
                               "$themeHudGap = 6\n"
                               "$themeHudChamfer = 10\n"
                               "$themeHudLineWidth = 3\n"
                               "$themeHudFloatGlowRange = 14\n"
                               "$themeHudStyle = scifi\n"
                               "$themeHudSweep = 1\n"
                               "$themeHudSweepSpeed = 70\n"
                               "$themeHudSweepLength = 200\n"
                               "$themeHudHideBorder = 1\n"
                               "$themeHudSideOpacity = 0.15\n"
                               "$themeHudEdgeOpacity = 0.1\n"
                               "$themeHudUnderglow = 0.3\n"
                               "$themeHudScanner = 48\n"
                               "$themeHudScannerBlur = 0\n"
                               "$themeHudGlyphColor = rgb(46ff3c)\n");
    CHECK(t.frame);
    CHECK_NEAR(t.gap, 6, 1e-9);
    CHECK_NEAR(t.lineWidth, 3, 1e-9);
    CHECK_NEAR(t.chamfer, 10, 1e-9);
    CHECK_NEAR(t.floatGlowRange, 14, 1e-9);
    CHECK(t.style == "scifi");
    CHECK(t.sweep);
    CHECK_NEAR(t.sweepSpeed, 70, 1e-9);
    CHECK_NEAR(t.sweepLength, 200, 1e-9);
    CHECK(t.hideBorder);
    CHECK_NEAR(t.sideOpacity, 0.15, 1e-9);
    CHECK_NEAR(t.edgeOpacity, 0.1, 1e-9);
    CHECK_NEAR(t.underglow, 0.3, 1e-9);
    CHECK_NEAR(t.scanner, 48, 1e-9);
    CHECK(!t.scannerBlur);
    const Rgb8 green{0x46, 0xff, 0x3c};
    CHECK(t.glyphColour == green);
}

void testLaterLinesWinAndWhitespace() {
    const Theme t = parseTheme("$themeHudGap=4\n   $themeHudGap   =   9   \n$themeHudFrame = true\n$themeHudFrame = off\n");
    CHECK_NEAR(t.gap, 9, 1e-9);
    CHECK(!t.frame);
}

void testComments() {
    const Theme t = parseTheme("# $themeHudFrame = 1\n"
                               "$themeHudGap = 8 # eight\n"
                               "general {\n  $themeHudChamfer = 12\n}\n");
    CHECK(!t.frame);
    CHECK_NEAR(t.gap, 8, 1e-9);
    CHECK_NEAR(t.chamfer, 12, 1e-9);
}

void testBooleans() {
    for (const char* on : {"1", "true", "TRUE", "yes", "On"})
        CHECK(parseTheme(std::string("$themeHudFrame = ") + on).frame);
    for (const char* off : {"0", "false", "no", "OFF"})
        CHECK(!parseTheme(std::string("$themeHudFrame = 1\n$themeHudFrame = ") + off).frame);
    // garbage leaves the previous value alone
    CHECK(parseTheme("$themeHudFrame = 1\n$themeHudFrame = maybe").frame);

    for (const char* on : {"1", "true", "yes", "on"})
        CHECK(parseTheme(std::string("$themeHudSweep = ") + on).sweep);
    CHECK(!parseTheme("$themeHudSweep = 1\n$themeHudSweep = off").sweep);
    CHECK(parseTheme("$themeHudSweep = 1\n$themeHudSweep = maybe").sweep);
    CHECK(!parseTheme("$themeHudSweep = maybe").sweep);

    // The hidden-border flag parses like the others and is not the same as the frame flag.
    for (const char* on : {"1", "true", "yes", "on"})
        CHECK(parseTheme(std::string("$themeHudHideBorder = ") + on).hideBorder);
    CHECK(!parseTheme("$themeHudHideBorder = 1\n$themeHudHideBorder = off").hideBorder);
    CHECK(parseTheme("$themeHudHideBorder = 1\n$themeHudHideBorder = maybe").hideBorder);
    CHECK(!parseTheme("$themeHudHideBorder = maybe").hideBorder);
    CHECK(!parseTheme("$themeHudHideBorder = 1").frame);
    CHECK(!parseTheme("$themeHudFrame = 1").hideBorder);
}

void testClamping() {
    const Theme hi = parseTheme("$themeHudGap = 500\n$themeHudLineWidth = 99\n$themeHudChamfer = 1000\n$themeHudFloatGlowRange = 900\n"
                                "$themeHudSweepSpeed = 5000\n$themeHudSweepLength = 9000\n");
    CHECK_NEAR(hi.gap, 64, 1e-9);
    CHECK_NEAR(hi.lineWidth, 16, 1e-9);
    CHECK_NEAR(hi.chamfer, 96, 1e-9);
    CHECK_NEAR(hi.floatGlowRange, 64, 1e-9);
    CHECK_NEAR(hi.sweepSpeed, 400, 1e-9);
    CHECK_NEAR(hi.sweepLength, 600, 1e-9);

    const Theme lo = parseTheme("$themeHudGap = -3\n$themeHudLineWidth = 0\n$themeHudChamfer = -1\n$themeHudFloatGlowRange = -5\n"
                                "$themeHudSweepSpeed = 0\n$themeHudSweepLength = -20\n");
    CHECK_NEAR(lo.gap, 0, 1e-9);
    CHECK_NEAR(lo.lineWidth, 1, 1e-9);
    CHECK_NEAR(lo.chamfer, 0, 1e-9);
    CHECK_NEAR(lo.floatGlowRange, 0, 1e-9);
    CHECK_NEAR(lo.sweepSpeed, 10, 1e-9);
    CHECK_NEAR(lo.sweepLength, 40, 1e-9);
}

void testInvalidValuesKeepDefaults() {
    const Theme t = parseTheme("$themeHudGap = abc\n$themeHudLineWidth = 3px\n$themeHudChamfer =\n$themeHudFloatGlowRange = nan\n$themeHudStyle = bad style!\n"
                               "$themeHudSweepSpeed = fast\n$themeHudSweepLength = inf\n");
    CHECK_NEAR(t.gap, 5, 1e-9);
    CHECK_NEAR(t.lineWidth, 3, 1e-9);
    CHECK_NEAR(t.chamfer, 10, 1e-9);
    CHECK_NEAR(t.floatGlowRange, 0, 1e-9);
    CHECK(t.style == "scifi");
    CHECK_NEAR(t.sweepSpeed, 80, 1e-9);
    CHECK_NEAR(t.sweepLength, 180, 1e-9);
}

void testFractionalAndStyle() {
    const Theme t = parseTheme("$themeHudGap = 2.5\n$themeHudStyle = minimal\n");
    CHECK_NEAR(t.gap, 2.5, 1e-9);
    CHECK(t.style == "minimal");
}

void testIgnoresUnrelatedLines() {
    const Theme t = parseTheme("windowrule = float\n$themeHudFrameX = 1\nmisc:foo = 1\n$noequals\n$themeHudHideBorderX = 1\n$themeHudGlyphColorX = rgb(ffffff)\n$themeHudSideOpacityX = 0.5\n"
                               "$themeHudEdgeOpacityX = 0.5\n$themeHudUnderglowX = 0.5\n$themeHudScannerX = 48\n$themeHudScannerBlurX = 0\n");
    CHECK(!t.frame);
    CHECK(!t.hideBorder);
    CHECK(!t.glyphColour);
    CHECK_NEAR(t.sideOpacity, 1, 1e-9);
    CHECK_NEAR(t.edgeOpacity, 1, 1e-9);
    CHECK_NEAR(t.underglow, 0, 1e-9);
    CHECK_NEAR(t.scanner, 0, 1e-9);
    CHECK(t.scannerBlur);
}

// A setting that is a fraction, 0 to 1, as it is written, and `fallback` when nothing says otherwise.
void checkFraction(const char* key, double Theme::*member, double fallback) {
    const std::string line = std::string("$themeHud") + key + " = ";
    const auto        read = [&](const std::string& text) { return parseTheme(text).*member; };

    CHECK_NEAR(read(line + "0.15"), 0.15, 1e-9);
    CHECK_NEAR(read(std::string("  $themeHud") + key + "=0.5   # dark"), 0.5, 1e-9);
    CHECK_NEAR(read(line + "0"), 0, 1e-9);
    CHECK_NEAR(read(line + "1"), 1, 1e-9);
    CHECK_NEAR(read(line + "0.3\n" + line + "0.7"), 0.7, 1e-9);

    // More or less than it can be is as much as it can be.
    CHECK_NEAR(read(line + "7"), 1, 1e-9);
    CHECK_NEAR(read(line + "-0.5"), 0, 1e-9);

    // Anything but a number leaves what was there.
    for (const char* bad : {"", "dark", "0.5x", "nan", "inf", "-inf", "50%"}) {
        CHECK_NEAR(read(line + bad), fallback, 1e-9);
        CHECK_NEAR(read(line + "0.2\n" + line + bad), 0.2, 1e-9);
    }

    // It is a setting of its own: setting it turns nothing else on and changes no other setting.
    Theme same;
    same.*member = 0.15;
    CHECK(parseTheme(line + "0.15") == same);
}

// How visible the sides of the outline are, how visible its top and bottom, and how strong the glow
// under the window is.
void testSideOpacity() { checkFraction("SideOpacity", &Theme::sideOpacity, 1); }
void testEdgeOpacity() { checkFraction("EdgeOpacity", &Theme::edgeOpacity, 1); }
void testUnderglow() { checkFraction("Underglow", &Theme::underglow, 0); }

// The three settings are read apart: each one keeps its own value.
void testFractionsAreIndependent() {
    const Theme t = parseTheme("$themeHudSideOpacity = 0.2\n$themeHudEdgeOpacity = 0.4\n$themeHudUnderglow = 0.6\n");
    CHECK_NEAR(t.sideOpacity, 0.2, 1e-9);
    CHECK_NEAR(t.edgeOpacity, 0.4, 1e-9);
    CHECK_NEAR(t.underglow, 0.6, 1e-9);

    const Theme u = parseTheme("$themeHudUnderglow = 0.6");
    CHECK_NEAR(u.sideOpacity, 1, 1e-9);
    CHECK_NEAR(u.edgeOpacity, 1, 1e-9);
}

// The width of the scanner in the corner of each window, as it is written. A width is read like the
// other numbers; what is drawn for it (24 at least, 160 at most) is up to scanner.hpp.
void testScanner() {
    const auto read = [](const std::string& text) { return parseTheme(text).scanner; };

    CHECK_NEAR(read("$themeHudScanner = 48"), 48, 1e-9);
    CHECK_NEAR(read("  $themeHudScanner=96   # wide"), 96, 1e-9);
    CHECK_NEAR(read("$themeHudScanner = 0"), 0, 1e-9);
    CHECK_NEAR(read("$themeHudScanner = 48\n$themeHudScanner = 64"), 64, 1e-9);
    CHECK_NEAR(read("$themeHudScanner = 48\n$themeHudScanner = 0"), 0, 1e-9);

    // More or less than it can be is as much as it can be.
    CHECK_NEAR(read("$themeHudScanner = 500"), 160, 1e-9);
    CHECK_NEAR(read("$themeHudScanner = -20"), 0, 1e-9);

    // Anything but a number leaves what was there.
    for (const char* bad : {"", "big", "48px", "nan", "inf", "-inf", "50%"}) {
        CHECK_NEAR(read(std::string("$themeHudScanner = ") + bad), 0, 1e-9);
        CHECK_NEAR(read(std::string("$themeHudScanner = 48\n$themeHudScanner = ") + bad), 48, 1e-9);
    }

    // It is a setting of its own: setting it turns nothing else on and changes no other setting.
    Theme same;
    same.scanner = 48;
    CHECK(parseTheme("$themeHudScanner = 48") == same);
    CHECK(parseTheme("$themeHudFrame = 1\n$themeHudUnderglow = 0.3").scanner == 0);
}

// Whether the glass of the scanner blurs what is under it: on unless a theme says otherwise.
void testScannerBlur() {
    const auto read = [](const std::string& text) { return parseTheme(text).scannerBlur; };

    CHECK(read(""));
    for (const char* on : {"1", "true", "TRUE", "yes", "On"})
        CHECK(read(std::string("$themeHudScannerBlur = 0\n$themeHudScannerBlur = ") + on));
    for (const char* off : {"0", "false", "no", "OFF"})
        CHECK(!read(std::string("$themeHudScannerBlur = ") + off));
    CHECK(!read("  $themeHudScannerBlur=0   # clear glass"));
    CHECK(read("$themeHudScannerBlur = 0\n$themeHudScannerBlur = 1"));
    CHECK(!read("$themeHudScannerBlur = 1\n$themeHudScannerBlur = 0"));

    // Anything but a flag leaves what was there.
    for (const char* bad : {"", "maybe", "2", "-1", "nan", "0.5"}) {
        CHECK(read(std::string("$themeHudScannerBlur = ") + bad));
        CHECK(!read(std::string("$themeHudScannerBlur = 0\n$themeHudScannerBlur = ") + bad));
    }

    // It is a setting of its own: neither the scanner nor the rest of the frame follows it.
    Theme same;
    same.scannerBlur = false;
    CHECK(parseTheme("$themeHudScannerBlur = 0") == same);
    CHECK_NEAR(parseTheme("$themeHudScannerBlur = 0").scanner, 0, 1e-9);
    CHECK_NEAR(parseTheme("$themeHudScanner = 48").scanner, 48, 1e-9);
    CHECK(parseTheme("$themeHudScanner = 48").scannerBlur);
}

void testGlyphColour() {
    const Rgb8 black{0, 0, 0}, mixed{0xff, 0xa0, 0x01}, matrix{0x1f, 0xe8, 0x6a};
    CHECK(parseTheme("$themeHudGlyphColor = rgb(000000)").glyphColour == black);
    CHECK(parseTheme("$themeHudGlyphColor = rgb(FfA001)").glyphColour == mixed);
    CHECK(parseTheme("  $themeHudGlyphColor=rgb(1fe86a)   # matrix green").glyphColour == matrix);

    // Anything but a colour leaves what was there; `none` takes the colour away.
    const Theme set = parseTheme("$themeHudGlyphColor = rgb(1fe86a)");
    for (const char* bad : {"", "green", "#1fe86a", "1fe86a", "rgb(1fe86a", "rgb(1fe86)", "rgb(1fe86aa)", "rgb(1fe86g)", "rgba(1fe86aff)", "rgb( 1fe86a)", "NONE"})
        CHECK(parseTheme(std::string("$themeHudGlyphColor = rgb(1fe86a)\n$themeHudGlyphColor = ") + bad).glyphColour == set.glyphColour);
    for (const char* bad : {"", "green", "rgb(1fe86g)", "rgba(1fe86aff)"})
        CHECK(!parseTheme(std::string("$themeHudGlyphColor = ") + bad).glyphColour);
    CHECK(!parseTheme("$themeHudGlyphColor = rgb(1fe86a)\n$themeHudGlyphColor = none").glyphColour);
    CHECK(!parseTheme("$themeHudGlyphColor = none").glyphColour);

    // It is a setting of its own: setting it turns nothing else on.
    const Theme only = parseTheme("$themeHudGlyphColor = rgb(1fe86a)");
    CHECK(only.glyphColour && !only.frame && !only.sweep && !only.hideBorder);
}

void testFocusedHalo() {
    CHECK(!parseTheme("").glowFocusedOnly);
    CHECK(parseTheme("$themeHudGlowFocusedOnly = 1").glowFocusedOnly);
    CHECK(!parseTheme("$themeHudGlowFocusedOnly = 1\n$themeHudGlowFocusedOnly = false").glowFocusedOnly);
    CHECK(parseTheme("$themeHudGlowFocusedOnly = 1\n$themeHudGlowFocusedOnly = invalid").glowFocusedOnly);
}

void testHaloOverrides() {
    const Theme t = parseTheme("$themeHudGlowRange = 16\n$themeHudGlowAlpha = 0.8\n");
    CHECK_NEAR(t.glowRange, 16, 1e-9);
    CHECK(t.glowAlpha && *t.glowAlpha == 0.8);
    CHECK_NEAR(parseTheme("$themeHudGlowRange = 999").glowRange, 64, 1e-9);
    CHECK_NEAR(parseTheme("$themeHudGlowRange = -1").glowRange, 0, 1e-9);
    CHECK(parseTheme("$themeHudGlowAlpha = 0").glowAlpha == 0);
    CHECK(parseTheme("$themeHudGlowAlpha = 2").glowAlpha == 1);
    CHECK(!parseTheme("$themeHudGlowAlpha = 0.8\n$themeHudGlowAlpha = style").glowAlpha);
    for (const char* bad : {"", "nan", "inf", "bright", "0.8px"})
        CHECK(parseTheme(std::string("$themeHudGlowAlpha = 0.8\n$themeHudGlowAlpha = ") + bad).glowAlpha == 0.8);
    CHECK(!Theme{}.glowAlpha);
}

} // namespace

int main() {
    testDefaults();
    testNeonBlock();
    testLaterLinesWinAndWhitespace();
    testComments();
    testBooleans();
    testClamping();
    testInvalidValuesKeepDefaults();
    testFractionalAndStyle();
    testIgnoresUnrelatedLines();
    testGlyphColour();
    testSideOpacity();
    testEdgeOpacity();
    testUnderglow();
    testFractionsAreIndependent();
    testScanner();
    testScannerBlur();
    testFocusedHalo();
    testHaloOverrides();
    return finish("test_theme");
}
