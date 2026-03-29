# st version
VERSION = 1.0.14

# Uncomment for debug builds (adds fprintf tracing, disables strip)
# DEBUGFLAGS = -g -O0 -DSTWL_DEBUG

# Customize below to fit your system

# paths
PREFIX = /usr/local
MANPREFIX = $(PREFIX)/share/man
ICONPREFIX = $(PREFIX)/share/pixmaps
ICONNAME = st.png

PKG_CONFIG = pkg-config
PKGCFG = fontconfig wayland-client wayland-cursor xkbcommon pixman-1
XDG_SHELL_PROTO = `$(PKG_CONFIG) --variable=pkgdatadir wayland-protocols`/stable/xdg-shell/xdg-shell.xml
XDG_DECORATION_PROTO = `$(PKG_CONFIG) --variable=pkgdatadir wayland-protocols`/unstable/xdg-decoration/xdg-decoration-unstable-v1.xml

PKG_CONFIG = pkg-config

# Ligatures patch / LIGATURES_PATCH
LIGATURES_C = hb.c
LIGATURES_H = hb.h
LIGATURES_INC = `$(PKG_CONFIG) --cflags harfbuzz`
LIGATURES_LIBS = `$(PKG_CONFIG) --libs harfbuzz`

# Uncomment this for the SIXEL patch / SIXEL_PATCH
SIXEL_C = sixel.c sixel_hls.c
SIXEL_LIBS = `$(PKG_CONFIG) --libs imlib2`

# Uncomment for the netwmicon patch / NETWMICON_PATCH
#NETWMICON_LIBS = `$(PKG_CONFIG) --libs gdlib`

# includes and libs, uncomment harfbuzz for the ligatures patch
INCS = -I. -I/usr/include `$(PKG_CONFIG) --cflags ${PKGCFG}` \
       `$(PKG_CONFIG) --cflags fontconfig` \
       `$(PKG_CONFIG) --cflags freetype2` \
       $(LIGATURES_INC)
LIBS = -L/usr/lib -lc -lm -lutil `$(PKG_CONFIG) --libs ${PKGCFG}`\
       `$(PKG_CONFIG) --libs fontconfig` \
       `$(PKG_CONFIG) --libs freetype2` \
       $(LIGATURES_LIBS) \
       $(SIXEL_LIBS) \
       $(NETWMICON_LIBS)

# flags
STCPPFLAGS = -DVERSION=\"$(VERSION)\" -DICON=\"$(ICONPREFIX)/$(ICONNAME)\" -D_XOPEN_SOURCE=700
STCFLAGS = $(DEBUGFLAGS) -O3 -flto $(INCS) $(STCPPFLAGS) $(CPPFLAGS) $(CFLAGS)
STLDFLAGS = -flto -s wld/libwld.a $(LIBS) $(LDFLAGS)

# OpenBSD:
#CPPFLAGS = $(STCPPFLAGS) -D_XOPEN_SOURCE=600
#MANPREFIX = ${PREFIX}/man

# compiler and linker
# CC = c99
