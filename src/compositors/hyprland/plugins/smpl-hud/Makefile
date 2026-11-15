# smpl-hud: a Hyprland plugin that draws HUD window frames inside the
# compositor render pass. Build needs the Hyprland development headers
# (the `hyprland` package ships them) and a C++23 compiler.
#
#   make        build build/smpl-hud.so against the installed Hyprland
#   make test   compositor-free unit tests (plain g++, no Hyprland headers)
#   make preview  build/preview, which draws a panel style as an image
#   make clean

CXX      ?= g++
BUILD    := build
PLUGIN   := $(BUILD)/smpl-hud.so

ifeq ($(CXX),g++)
EXTRA_FLAGS := -fno-gnu-unique
else
EXTRA_FLAGS :=
endif

LIB_SRC    := geometry.cpp gradient.cpp theme.cpp sweep.cpp stamp.cpp glyph.cpp panel.cpp place.cpp scanner.cpp
PLUGIN_SRC := $(LIB_SRC) HudDecoration.cpp ScannerDecoration.cpp HudPassElement.cpp main.cpp
TESTS      := test_geometry test_gradient test_theme test_sweep test_stamp test_glyph test_panel test_place test_scanner test_flipbook

CXXFLAGS ?= -O2
PLUGIN_CXXFLAGS := $(CXXFLAGS) -shared -fPIC -std=c++2b -Wall -Wextra
TEST_CXXFLAGS   := -O1 -g -std=c++20 -Wall -Wextra -Werror

HYPR_PKGS := pixman-1 libdrm hyprland pangocairo libinput libudev wayland-server xkbcommon

.PHONY: all test preview clean
all: $(PLUGIN)

$(PLUGIN): $(PLUGIN_SRC) $(wildcard *.hpp)
	@mkdir -p $(BUILD)
	$(CXX) $(PLUGIN_CXXFLAGS) $(LDFLAGS) $(EXTRA_FLAGS) $(PLUGIN_SRC) -o $@ `pkg-config --cflags $(HYPR_PKGS)`

test: $(addprefix $(BUILD)/,$(TESTS))
	@set -e; for t in $(TESTS); do $(BUILD)/$$t; done

$(BUILD)/test_%: tests/test_%.cpp $(LIB_SRC) $(wildcard *.hpp) tests/check.hpp
	@mkdir -p $(BUILD)
	$(CXX) $(TEST_CXXFLAGS) $< $(LIB_SRC) -o $@

# A tool for tuning a style by eye: it draws a panel as a PPM image on stdout;
# the arguments are listed at the top of tests/preview.cpp.
preview: $(BUILD)/preview
$(BUILD)/preview: tests/preview.cpp $(LIB_SRC) $(wildcard *.hpp)
	@mkdir -p $(BUILD)
	$(CXX) $(TEST_CXXFLAGS) $< $(LIB_SRC) -o $@

clean:
	rm -rf $(BUILD)
