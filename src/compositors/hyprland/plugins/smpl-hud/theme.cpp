#include "theme.hpp"

#include <algorithm>
#include <cctype>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string_view>

namespace smplhud {

namespace {

std::string_view trim(std::string_view s) {
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.front())))
        s.remove_prefix(1);
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.back())))
        s.remove_suffix(1);
    return s;
}

bool parseNumber(std::string_view text, double lo, double hi, double& out) {
    const std::string copy(text);
    if (copy.empty())
        return false;

    char* end = nullptr;
    errno     = 0;
    const double v = std::strtod(copy.c_str(), &end);
    if (errno != 0 || end != copy.c_str() + copy.size() || !std::isfinite(v))
        return false;

    out = std::clamp(v, lo, hi);
    return true;
}

bool parseBool(std::string_view text, bool& out) {
    std::string v(text);
    std::ranges::transform(v, v.begin(), [](unsigned char c) { return char(std::tolower(c)); });

    if (v == "1" || v == "true" || v == "yes" || v == "on") {
        out = true;
        return true;
    }
    if (v == "0" || v == "false" || v == "no" || v == "off") {
        out = false;
        return true;
    }
    return false;
}

bool isStyleName(std::string_view s) {
    return !s.empty() && std::ranges::all_of(s, [](unsigned char c) { return std::isalnum(c) || c == '_' || c == '-'; });
}

// `rgb(rrggbb)`, Hyprland's own spelling of a colour without opacity.
bool parseColour(std::string_view text, Rgb8& out) {
    constexpr std::string_view open = "rgb(";
    if (text.size() != open.size() + 6 + 1 || !text.starts_with(open) || text.back() != ')')
        return false;

    const std::string digits(text.substr(open.size(), 6));
    if (!std::ranges::all_of(digits, [](unsigned char c) { return std::isxdigit(c); }))
        return false;

    const unsigned long v = std::strtoul(digits.c_str(), nullptr, 16);
    out                   = {uint8_t(v >> 16), uint8_t(v >> 8), uint8_t(v)};
    return true;
}

void apply(Theme& t, std::string_view key, std::string_view value) {
    if (key == "themeHudFrame")
        parseBool(value, t.frame);
    else if (key == "themeHudGap")
        parseNumber(value, 0, 64, t.gap);
    else if (key == "themeHudLineWidth")
        parseNumber(value, 1, 16, t.lineWidth);
    else if (key == "themeHudChamfer")
        parseNumber(value, 0, 96, t.chamfer);
    else if (key == "themeHudFloatGlowRange")
        parseNumber(value, 0, 64, t.floatGlowRange);
    else if (key == "themeHudGlowRange")
        parseNumber(value, 0, 64, t.glowRange);
    else if (key == "themeHudGlowAlpha") {
        double alpha = 0;
        if (value == "style")
            t.glowAlpha.reset();
        else if (parseNumber(value, 0, 1, alpha))
            t.glowAlpha = alpha;
    }
    else if (key == "themeHudStyle" && isStyleName(value))
        t.style = std::string(value);
    else if (key == "themeHudSweep")
        parseBool(value, t.sweep);
    else if (key == "themeHudSweepSpeed")
        parseNumber(value, 10, 400, t.sweepSpeed);
    else if (key == "themeHudSweepLength")
        parseNumber(value, 40, 600, t.sweepLength);
    else if (key == "themeHudGlowFocusedOnly")
        parseBool(value, t.glowFocusedOnly);
    else if (key == "themeHudHideBorder")
        parseBool(value, t.hideBorder);
    else if (key == "themeHudSideOpacity")
        parseNumber(value, 0, 1, t.sideOpacity);
    else if (key == "themeHudEdgeOpacity")
        parseNumber(value, 0, 1, t.edgeOpacity);
    else if (key == "themeHudUnderglow")
        parseNumber(value, 0, 1, t.underglow);
    else if (key == "themeHudScanner")
        parseNumber(value, 0, 160, t.scanner);
    else if (key == "themeHudScannerBlur")
        parseBool(value, t.scannerBlur);
    else if (key == "themeHudGlyphColor") {
        if (Rgb8 colour; parseColour(value, colour))
            t.glyphColour = colour;
        else if (value == "none")
            t.glyphColour.reset();
    }
}

} // namespace

Theme parseTheme(const std::string& text) {
    Theme              theme;
    std::istringstream in(text);
    std::string        raw;

    while (std::getline(in, raw)) {
        std::string_view line = trim(raw);
        if (line.empty() || line.front() != '$')
            continue;

        const auto eq = line.find('=');
        if (eq == std::string_view::npos)
            continue;

        const auto key   = trim(line.substr(1, eq - 1));
        auto       value = line.substr(eq + 1);
        if (const auto hash = value.find('#'); hash != std::string_view::npos)
            value = value.substr(0, hash);

        apply(theme, key, trim(value));
    }

    return theme;
}

std::string themePath() {
    if (const char* xdg = std::getenv("XDG_CONFIG_HOME"); xdg && *xdg)
        return std::string(xdg) + "/hypr/theme.conf";
    if (const char* home = std::getenv("HOME"); home && *home)
        return std::string(home) + "/.config/hypr/theme.conf";
    return {};
}

Theme loadTheme() {
    const std::string path = themePath();
    if (path.empty())
        return {};

    std::ifstream file(path);
    if (!file)
        return {};

    std::stringstream buf;
    buf << file.rdbuf();
    return parseTheme(buf.str());
}

} // namespace smplhud
