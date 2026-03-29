/* See LICENSE file for copyright and license details. */

/*
 * appearance
 *
 * font: see http://freedesktop.org/software/fontconfig/fontconfig-user.html
 */

#define DEFAULTFONTSIZE 13

#if FONT2_PATCH
/* Spare fonts */
static char *font2[] = {
/*	"Inconsolata for Powerline:pixelsize=12:antialias=true:autohint=true", */
/*	"Hack Nerd Font Mono:pixelsize=11:antialias=true:autohint=true", */
};
#endif // FONT2_PATCH

#if BACKGROUND_IMAGE_PATCH
/*
 * background image
 * expects farbfeld format
 * pseudo transparency fixes coordinates to the screen origin
 */
static const char *bgfile = "/path/to/image.ff";
static const int pseudotransparency = 0;
#endif // BACKGROUND_IMAGE_PATCH

#if RELATIVEBORDER_PATCH
/* borderperc: percentage of cell width to use as a border
 *             0 = no border, 100 = border width is same as cell width */
int borderperc = 20;
#else
static int borderpx = 2;
#endif // RELATIVEBORDER_PATCH

#if OPENURLONCLICK_PATCH
/* modkey options: MOD_MASK_CTRL, MOD_MASK_SHIFT or MOD_MASK_ANY */
static uint url_opener_modkey = MOD_MASK_ANY;
static char *url_opener = "xdg-open";
#endif // OPENURLONCLICK_PATCH

/*
 * What program is execed by st-wl depends of these precedence rules:
 * 1: program passed with -e
 * 2: scroll and/or utmp
 * 3: SHELL environment variable
 * 4: value of shell in /etc/passwd
 * 5: value of shell in config.h
 */
static char *shell = "/bin/sh";
char *utmp = NULL;
/* scroll program: to enable use a string like "scroll" */
char *scroll = NULL;
char *stty_args = "stty raw pass8 nl -echo -iexten -cstopb 38400";

/* identification sequence returned in DA and DECID */
#if SIXEL_PATCH
char *vtiden = "\033[?62;4c"; /* VT200 family (62) with sixel (4) */

/* sixel rgb byte order: LSBFirst or MSBFirst (X11 only, unused on Wayland) */
//int const sixelbyteorder = LSBFirst;
#else
char *vtiden = "\033[?6c";
#endif

/* Kerning / character bounding-box multipliers */
static float cwscale = 1.0;
static float chscale = 1.0;

/*
 * word delimiter string
 *
 * More advanced example: L" `'\"()[]{}"
 */
wchar_t *worddelimiters = L" │┃|:`'\"()[]{}┃";
wchar_t *snap_line_delimiters = L"│┃";

#if KEYBOARDSELECT_PATCH && REFLOW_PATCH
/* Word delimiters for short and long jumps in the keyboard select patch */
wchar_t *kbds_sdelim = L"!\"#$%&'()*+,-./:;<=>?@[\\]^`{|}~ ";
wchar_t *kbds_ldelim = L" ";
#endif // KEYBOARDSELECT_PATCH

/* selection timeouts (in milliseconds) */
static unsigned int doubleclicktimeout = 300;
static unsigned int tripleclicktimeout = 600;

/* alt screens */
int allowaltscreen = 1;

/* key repeat timeouts (in milliseconds)
 * Overridden at runtime by compositor via wl_keyboard::repeat_info */
static unsigned int keyrepeatdelay = 500;
static unsigned int keyrepeatinterval = 25;

/* allow certain non-interactive (insecure) window operations such as:
   setting the clipboard text */
int allowwindowops = 1;

/*
 * draw latency range in ms - from new content/keypress/etc until drawing.
 * within this range, st draws when content stops arriving (idle). mostly it's
 * near minlatency, but it waits longer for slow updates to avoid partial draw.
 * low minlatency will tear/flicker more, as it can "detect" idle too early.
 */
static double minlatency = 2;
static double maxlatency = 33;

#if SYNC_PATCH
/*
 * Synchronized-Update timeout in ms
 * https://gitlab.com/gnachman/iterm2/-/wikis/synchronized-updates-spec
 */
static uint su_timeout = 200;
#endif // SYNC_PATCH

/*
 * blinking timeout (set to 0 to disable blinking) for the terminal blinking
 * attribute.
 */
static unsigned int blinktimeout = 800;

/*
 * thickness of underline and bar cursors
 */
static unsigned int cursorthickness = 2;

#if HIDECURSOR_PATCH
/* Hide the X cursor whenever a key is pressed. 0: off, 1: on */
int hidecursor = 1;
#endif // HIDECURSOR_PATCH

#if BOXDRAW_PATCH
/*
 * 1: render most of the lines/blocks characters without using the font for
 *    perfect alignment between cells (U2500 - U259F except dashes/diagonals).
 *    Bold affects lines thickness if boxdraw_bold is not 0. Italic is ignored.
 * 0: disable (render all U25XX glyphs normally from the font).
 */
const int boxdraw = 0;
const int boxdraw_bold = 0;

/* braille (U28XX):  1: render as adjacent "pixels",  0: use font */
const int boxdraw_braille = 0;
#endif // BOXDRAW_PATCH

/*
 * bell volume. It must be a value between -100 and 100. Use 0 for disabling
 * it
 */
static int bellvolume = 0;

/* default TERM value */
char *termname = "st-256color";

/* default class */
char *termclass = "terminal";

/*
 * spaces per tab
 *
 * When you are changing this value, don't forget to adapt the »it« value in
 * the st-wl.info and appropriately install the st-wl.info in the environment where
 * you use this st-wl version.
 *
 *	it#$tabspaces,
 *
 * Secondly make sure your kernel is not expanding tabs. When running `stty
 * -a` »tab0« should appear. You can tell the terminal to not expand tabs by
 *  running following command:
 *
 *	stty tabs
 */
unsigned int tabspaces = 8;

#if ALPHA_PATCH
/* bg opacity — default fallback. wl.c loads term_opacity_active from the
 * active smplOS theme when available, so this is only used as a last resort. */
#define DEFAULT_ALPHA 1.0
float alpha = DEFAULT_ALPHA;
uint8_t term_alpha = (uint8_t)(DEFAULT_ALPHA*255.0);
#if ALPHA_GRADIENT_PATCH
float grad_alpha = 0.54; //alpha value that'll change
float stat_alpha = 0.46; //constant alpha value that'll get added to grad_alpha
#endif // ALPHA_GRADIENT_PATCH
#if ALPHA_FOCUS_HIGHLIGHT_PATCH
float alphaUnfocused = 0.6;
#endif // ALPHA_FOCUS_HIGHLIGHT_PATCH
#endif // ALPHA_PATCH

#if DRAG_AND_DROP_PATCH
/*
 * drag and drop escape characters
 *
 * this will add a '\' before any characters specified in the string.
 */
char *xdndescchar = " !\"#$&'()*;<>?[\\]^`{|}~";
#endif // DRAG_AND_DROP_PATCH

/* Terminal colors (16 first used in escape sequence)
 * These are compile-time defaults — theme-set-st overrides them at runtime
 * via OSC escape sequences.  Keep these neutral/dark so new terminals look
 * reasonable for the brief moment before OSC sequences arrive. */
static const char *colorname[] = {
	/* 8 normal colors — standard ANSI */
	[0] = "#000000", /* black   */
	[1] = "#cc0000", /* red     */
	[2] = "#4e9a06", /* green   */
	[3] = "#c4a000", /* yellow  */
	[4] = "#3465a4", /* blue    */
	[5] = "#75507b", /* magenta */
	[6] = "#06989a", /* cyan    */
	[7] = "#d3d7cf", /* white   */

	/* 8 bright colors */
	[8]  = "#555753", /* black   */
	[9]  = "#ef2929", /* red     */
	[10] = "#8ae234", /* green   */
	[11] = "#fce94f", /* yellow  */
	[12] = "#729fcf", /* blue    */
	[13] = "#ad7fa8", /* magenta */
	[14] = "#34e2e2", /* cyan    */
	[15] = "#eeeeec", /* white   */

	[255] = 0,

	/* more colors can be added after 255 to use with DefaultXX */
	"#d3d7cf", /* 256 -> cursor */
	"#555753", /* 257 -> rev cursor*/
	"#000000", /* 258 -> bg */
	"#d3d7cf", /* 259 -> fg */
};


/*
 * Default colors (colorname index)
 * foreground, background, cursor, reverse cursor
 */
#if ALPHA_PATCH && ALPHA_FOCUS_HIGHLIGHT_PATCH
unsigned int defaultbg = 0;
unsigned int bg = 17, bgUnfocused = 16;
#else
unsigned int defaultbg = 258;
#endif // ALPHA_FOCUS_HIGHLIGHT_PATCH
unsigned int defaultfg = 259;
unsigned int defaultcs = 256;
unsigned int defaultrcs = 257;
#if SELECTION_COLORS_PATCH
unsigned int selectionfg = 258;
unsigned int selectionbg = 259;
#endif // SELECTION_COLORS_PATCH
#if KEYBOARDSELECT_PATCH && REFLOW_PATCH
/* Foreground and background color of search results */
unsigned int highlightfg = 15;
unsigned int highlightbg = 160;
#endif // KEYBOARDSELECT_PATCH

#if BLINKING_CURSOR_PATCH
/*
 * https://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h4-Functions-using-CSI-_-ordered-by-the-final-character-lparen-s-rparen:CSI-Ps-SP-q.1D81
 * Default style of cursor
 * 0: Blinking block
 * 1: Blinking block (default)
 * 2: Steady block ("â–ˆ")
 * 3: Blinking underline
 * 4: Steady underline ("_")
 * 5: Blinking bar
 * 6: Steady bar ("|")
 * 7: Blinking st cursor
 * 8: Steady st cursor
 */
static unsigned int cursorstyle = 1;
static Rune stcursor = 0x2603; /* snowman (U+2603) */
#else
/*
 * Default shape of cursor
 * 2: Block ("█")
 * 4: Underline ("_")
 * 6: Bar ("|")
 * 7: Snowman ("☃")
 */
static unsigned int cursorshape = 2;
#endif // BLINKING_CURSOR_PATCH

/*
 * Default columns and rows numbers
 */

static unsigned int cols = 140;
static unsigned int rows = 40;

#if ANYGEOMETRY_PATCH
/*
 * Whether to use pixel geometry or cell geometry
 */

static Geometry geometry = CellGeometry; // or PixelGeometry to use the below size
static unsigned int width = 564;
static unsigned int height = 364;
#endif // ANYGEOMETRY_PATCH

/*
 * Default shape of the mouse cursor
 */
static char* mouseshape = "xterm";

/*
 * Color used to display font attributes when fontconfig selected a font which
 * doesn't match the ones requested.
 */
static unsigned int defaultattr = 11;

/*
 * Force mouse select/shortcuts while mask is active (when MODE_MOUSE is set).
 * Note that if you want to use MOD_MASK_SHIFT with selmasks, set this to an other
 * modifier, set to 0 to not use it.
 */
static uint forcemousemod = MOD_MASK_SHIFT;

/*
 * Scrollwheel up/down shortcuts.
 */
static Axiskey ashortcuts[] = {
    /* mask axis         direction   function arg screen */
	#if OPEN_SELECTED_TEXT_PATCH
	{ ControlMask,          Button2, selopen,        {.i = 0},      1 },
	#endif // OPEN_SELECTED_TEXT_PATCH
	#if SCROLLBACK_MOUSE_PATCH
	{ MOD_MASK_SHIFT, AXIS_VERTICAL, +1, kscrolldown , {.i = 3}, S_PRI},
	{ MOD_MASK_SHIFT, AXIS_VERTICAL, -1, kscrollup   , {.i = 3}, S_PRI},
	#elif UNIVERSCROLL_PATCH
	{ MOD_MASK_ANY, AXIS_VERTICAL,   +1, ttysend, {.s = "\033[5;2~"}, S_PRI},
	{ MOD_MASK_ANY, AXIS_VERTICAL,   -1, ttysend, {.s = "\033[6;2~"}, S_PRI},
	#else
	{ MOD_MASK_SHIFT, AXIS_VERTICAL, +1, ttysend, {.s = "\033[5;2~"} },
	{ MOD_MASK_SHIFT, AXIS_VERTICAL, -1, ttysend, {.s = "\033[6;2~"} },
	#endif // SCROLLBACK_MOUSE_PATCH
	#if SCROLLBACK_MOUSE_ALTSCREEN_PATCH || REFLOW_PATCH
	{ MOD_MASK_ANY, AXIS_VERTICAL,   +1, kscrolldown, {.i = 3}, S_PRI},
	{ MOD_MASK_ANY, AXIS_VERTICAL,   -1, kscrollup,   {.i = 3}, S_PRI},
	{ MOD_MASK_ANY, AXIS_VERTICAL,   +1, ttysend, {.s = "\031"}, S_ALT},
	{ MOD_MASK_ANY, AXIS_VERTICAL,   -1, ttysend, {.s = "\005"}, S_ALT},
	#else
	{ MOD_MASK_ANY, AXIS_VERTICAL,   +1, ttysend, {.s = "\031"}},
	{ MOD_MASK_ANY, AXIS_VERTICAL,   -1, ttysend, {.s = "\005"}},
	#endif // SCROLLBACK_MOUSE_ALTSCREEN_PATCH
};

/* Internal keyboard shortcuts. */
#define MODKEY MOD_MASK_ALT
#define TERMMOD (MOD_MASK_CTRL|MOD_MASK_SHIFT)

#if EXTERNALPIPE_PATCH // example command
static char *openurlcmd[] = { "/bin/sh", "-c",
	"xurls | dmenu -l 10 -w $WINDOWID | xargs -r open",
	"externalpipe", NULL };

#if EXTERNALPIPEIN_PATCH // example command
static char *setbgcolorcmd[] = { "/bin/sh", "-c",
	"printf '\033]11;#008000\007'",
	"externalpipein", NULL };
#endif // EXTERNALPIPEIN_PATCH
#endif // EXTERNALPIPE_PATCH

static Shortcut shortcuts[] = {
	/* mask                 keysym          function         argument   screen */
	{ MOD_MASK_ANY,           XKB_KEY_Break,       sendbreak,       {.i =  0} },
	{ MOD_MASK_CTRL,          XKB_KEY_Print,       toggleprinter,   {.i =  0} },
	{ MOD_MASK_SHIFT,            XKB_KEY_Print,       printscreen,     {.i =  0} },
	{ MOD_MASK_ANY,           XKB_KEY_Print,       printsel,        {.i =  0} },
	{ TERMMOD,              XKB_KEY_Prior,       zoom,            {.f = +1} },
	{ TERMMOD,              XKB_KEY_Next,        zoom,            {.f = -1} },
	{ TERMMOD,              XKB_KEY_Home,        zoomreset,       {.f =  0} },
	{ TERMMOD,              XKB_KEY_C,           clipcopy,        {.i =  0} },
	{ TERMMOD,              XKB_KEY_V,           clippaste,       {.i =  0} },
	#if ALPHA_PATCH
	{ TERMMOD,              XKB_KEY_O,           changealpha,     {.f = +0.05} },
	{ TERMMOD,              XKB_KEY_P,           changealpha,     {.f = -0.05} },
	#if ALPHA_FOCUS_HIGHLIGHT_PATCH
	//{ TERMMOD,              XKB_KEY_,           changealphaunfocused, {.f = +0.05} },
	//{ TERMMOD,              XKB_KEY_,           changealphaunfocused, {.f = -0.05} },
	#endif // ALPHA_FOCUS_HIGHLIGHT_PATCH
	#endif // ALPHA_PATCH
	#if FULLSCREEN_PATCH
	{ MOD_MASK_NONE,            XKB_KEY_F11,         fullscreen,      {.i =  0} },
	#endif // FULLSCREEN_PATCH
	#if SCROLLBACK_PATCH || REFLOW_PATCH
	{ MOD_MASK_NONE,             XKB_KEY_Page_Up,     kscrollup,       {.i = -100}, S_PRI },
	{ MOD_MASK_NONE,             XKB_KEY_Page_Down,   kscrolldown,     {.i = -100}, S_PRI },
	{ MOD_MASK_SHIFT,            XKB_KEY_Page_Up,     kscrollup,       {.i = -100}, S_PRI },
	{ MOD_MASK_SHIFT,            XKB_KEY_Page_Down,   kscrolldown,     {.i = -100}, S_PRI },
	#endif // SCROLLBACK_PATCH || REFLOW_PATCH
	#if CLIPBOARD_PATCH
	{ TERMMOD,              XKB_KEY_Y,           clippaste,       {.i =  0} },
	{ MOD_MASK_SHIFT,            XKB_KEY_Insert,      clippaste,       {.i =  0} },
	{ MOD_MASK_CTRL,          XKB_KEY_Insert,      clipcopy,        {.i =  0} },
	#else
	{ TERMMOD,              XKB_KEY_Y,           selpaste,        {.i =  0} },
	{ MOD_MASK_SHIFT,            XKB_KEY_Insert,      selpaste,        {.i =  0} },
	#endif // CLIPBOARD_PATCH
	{ TERMMOD,              XKB_KEY_Num_Lock,    numlock,         {.i =  0} },
	#if COPYURL_PATCH || COPYURL_HIGHLIGHT_SELECTED_URLS_PATCH
	{ MODKEY,               XKB_KEY_l,           copyurl,         {.i =  0} },
	#endif // COPYURL_PATCH
	#if OPENCOPIED_PATCH
	{ MODKEY,               XKB_KEY_o,           opencopied,      {.v = "xdg-open"} },
	#endif // OPENCOPIED_PATCH
	#if NEWTERM_PATCH
	{ TERMMOD,              XKB_KEY_Return,      newterm,         {.i =  0} },
	#endif // NEWTERM_PATCH
	#if EXTERNALPIPE_PATCH
	{ TERMMOD,              XKB_KEY_U,           externalpipe,    { .v = openurlcmd } },
	#if EXTERNALPIPEIN_PATCH
	{ TERMMOD,              XKB_KEY_M,           externalpipein,  { .v = setbgcolorcmd } },
	#endif // EXTERNALPIPEIN_PATCH
	#endif // EXTERNALPIPE_PATCH
	#if KEYBOARDSELECT_PATCH
	{ TERMMOD,              XKB_KEY_Escape,      keyboard_select, { 0 } },
	#endif // KEYBOARDSELECT_PATCH
	#if KEYBOARDSELECT_PATCH && REFLOW_PATCH
	{ TERMMOD,              XKB_KEY_F,           searchforward,   { 0 } },
	{ TERMMOD,              XKB_KEY_B,           searchbackward,  { 0 } },
	#endif // KEYBOARDSELECT_PATCH
	#if ISO14755_PATCH
	{ TERMMOD,              XKB_KEY_I,           iso14755,        {.i =  0} },
	#endif // ISO14755_PATCH
	#if INVERT_PATCH
	{ TERMMOD,              XKB_KEY_X,           invert,          { 0 } },
	#endif // INVERT_PATCH
	#if OSC133_PATCH
	{ MOD_MASK_CTRL,          XKB_KEY_Page_Up,     scrolltoprompt,  {.i = -1}, S_PRI },
	{ MOD_MASK_CTRL,          XKB_KEY_Page_Down,   scrolltoprompt,  {.i =  1}, S_PRI },
	#endif // OSC133_PATCH
};

/*
 * Special keys (change & recompile st.info accordingly)
 *
 * Mask value:
 * * Use MOD_MASK_ANY to match the key no matter modifiers state
 * * Use MOD_MASK_NONE to match the key alone (no modifiers)
 * appkey value:
 * * 0: no value
 * * > 0: keypad application mode enabled
 * *   = 2: term.numlock = 1
 * * < 0: keypad application mode disabled
 * appcursor value:
 * * 0: no value
 * * > 0: cursor application mode enabled
 * * < 0: cursor application mode disabled
 *
 * Be careful with the order of the definitions because st searches in
 * this table sequentially, so any MOD_MASK_ANY must be in the last
 * position for a key.
 */

#if !FIXKEYBOARDINPUT_PATCH
/*
 * If you want keys other than the X11 function keys (0xFD00 - 0xFFFF)
 * to be mapped below, add them to this array.
 */
static xkb_keysym_t mappedkeys[] = { -1 };
#endif // FIXKEYBOARDINPUT_PATCH

/*
 * State bits to ignore when matching key or button events.  By default,
 * numlock (Mod2Mask) and keyboard layout (XK_SWITCH_MOD) are ignored.
 */
static uint ignoremod = 0; // MH!!Mod2Mask|XK_SWITCH_MOD;

/*
 * Override mouse-select while mask is active (when MODE_MOUSE is set).
 * Note that if you want to use MOD_MASK_SHIFT with selmasks, set this to an other
 * modifier, set to 0 to not use it.
 */
static uint forceselmod = MOD_MASK_SHIFT;

#if !FIXKEYBOARDINPUT_PATCH
/*
 * This is the huge key array which defines all compatibility to the Linux
 * world. Please decide about changes wisely.
 */
static Key key[] = {
	/* keysym           mask            string      appkey appcursor */
	{ XKB_KEY_KP_Home,       MOD_MASK_SHIFT,      "\033[1;2~",     0,    0},
	{ XKB_KEY_KP_Home,       MOD_MASK_ANY,     "\033[H",        0,   -1},
	{ XKB_KEY_KP_Home,       MOD_MASK_ANY,     "\033[1~",       0,   +1},
	{ XKB_KEY_KP_Up,         MOD_MASK_ANY,     "\033Ox",       +1,    0},
	{ XKB_KEY_KP_Up,         MOD_MASK_ANY,     "\033[A",        0,   -1},
	{ XKB_KEY_KP_Up,         MOD_MASK_ANY,     "\033OA",        0,   +1},
	{ XKB_KEY_KP_Down,       MOD_MASK_ANY,     "\033Or",       +1,    0},
	{ XKB_KEY_KP_Down,       MOD_MASK_ANY,     "\033[B",        0,   -1},
	{ XKB_KEY_KP_Down,       MOD_MASK_ANY,     "\033OB",        0,   +1},
	{ XKB_KEY_KP_Left,       MOD_MASK_ANY,     "\033Ot",       +1,    0},
	{ XKB_KEY_KP_Left,       MOD_MASK_ANY,     "\033[D",        0,   -1},
	{ XKB_KEY_KP_Left,       MOD_MASK_ANY,     "\033OD",        0,   +1},
	{ XKB_KEY_KP_Right,      MOD_MASK_ANY,     "\033Ov",       +1,    0},
	{ XKB_KEY_KP_Right,      MOD_MASK_ANY,     "\033[C",        0,   -1},
	{ XKB_KEY_KP_Right,      MOD_MASK_ANY,     "\033OC",        0,   +1},
	{ XKB_KEY_KP_Prior,      MOD_MASK_SHIFT,      "\033[5;2~",     0,    0},
	{ XKB_KEY_KP_Prior,      MOD_MASK_ANY,     "\033[5~",       0,    0},
	{ XKB_KEY_KP_Begin,      MOD_MASK_ANY,     "\033[E",        0,    0},
	{ XKB_KEY_KP_End,        MOD_MASK_CTRL,    "\033[4;5~",    0,     0},
	{ XKB_KEY_KP_End,        MOD_MASK_SHIFT,      "\033[4;2~",    0,     0},
	{ XKB_KEY_KP_End,        MOD_MASK_ANY,     "\033[4~",       0,    0},
	{ XKB_KEY_KP_Next,       MOD_MASK_SHIFT,      "\033[6;2~",     0,    0},
	{ XKB_KEY_KP_Next,       MOD_MASK_ANY,     "\033[6~",       0,    0},
	{ XKB_KEY_KP_Insert,     MOD_MASK_SHIFT,      "\033[2;2~",    +1,    0},
	{ XKB_KEY_KP_Insert,     MOD_MASK_SHIFT,      "\033[4l",      -1,    0},
	{ XKB_KEY_KP_Insert,     MOD_MASK_CTRL,    "\033[L",       -1,    0},
	{ XKB_KEY_KP_Insert,     MOD_MASK_CTRL,    "\033[2;5~",    +1,    0},
	{ XKB_KEY_KP_Insert,     MOD_MASK_ANY,     "\033[4h",      -1,    0},
	{ XKB_KEY_KP_Insert,     MOD_MASK_ANY,     "\033[2~",      +1,    0},
	{ XKB_KEY_KP_Delete,     MOD_MASK_CTRL,    "\033[M",       -1,    0},
	{ XKB_KEY_KP_Delete,     MOD_MASK_CTRL,    "\033[3;5~",    +1,    0},
	{ XKB_KEY_KP_Delete,     MOD_MASK_SHIFT,      "\033[2K",      -1,    0},
	{ XKB_KEY_KP_Delete,     MOD_MASK_SHIFT,      "\033[3;2~",    +1,    0},
	#if DELKEY_PATCH
	{ XKB_KEY_KP_Delete,     MOD_MASK_ANY,     "\033[3~",      -1,    0},
	#else
	{ XKB_KEY_KP_Delete,     MOD_MASK_ANY,     "\033[P",       -1,    0},
	#endif // DELKEY_PATCH
	{ XKB_KEY_KP_Delete,     MOD_MASK_ANY,     "\033[3~",      +1,    0},
	{ XKB_KEY_KP_Multiply,   MOD_MASK_ANY,     "\033Oj",       +2,    0},
	{ XKB_KEY_KP_Add,        MOD_MASK_ANY,     "\033Ok",       +2,    0},
	{ XKB_KEY_KP_Enter,      MOD_MASK_ANY,     "\033OM",       +2,    0},
	{ XKB_KEY_KP_Enter,      MOD_MASK_ANY,     "\r",           -1,    0},
	{ XKB_KEY_KP_Subtract,   MOD_MASK_ANY,     "\033Om",       +2,    0},
	{ XKB_KEY_KP_Decimal,    MOD_MASK_ANY,     "\033On",       +2,    0},
	{ XKB_KEY_KP_Divide,     MOD_MASK_ANY,     "\033Oo",       +2,    0},
	{ XKB_KEY_KP_0,          MOD_MASK_ANY,     "\033Op",       +2,    0},
	{ XKB_KEY_KP_1,          MOD_MASK_ANY,     "\033Oq",       +2,    0},
	{ XKB_KEY_KP_2,          MOD_MASK_ANY,     "\033Or",       +2,    0},
	{ XKB_KEY_KP_3,          MOD_MASK_ANY,     "\033Os",       +2,    0},
	{ XKB_KEY_KP_4,          MOD_MASK_ANY,     "\033Ot",       +2,    0},
	{ XKB_KEY_KP_5,          MOD_MASK_ANY,     "\033Ou",       +2,    0},
	{ XKB_KEY_KP_6,          MOD_MASK_ANY,     "\033Ov",       +2,    0},
	{ XKB_KEY_KP_7,          MOD_MASK_ANY,     "\033Ow",       +2,    0},
	{ XKB_KEY_KP_8,          MOD_MASK_ANY,     "\033Ox",       +2,    0},
	{ XKB_KEY_KP_9,          MOD_MASK_ANY,     "\033Oy",       +2,    0},
	{ XKB_KEY_Up,            MOD_MASK_SHIFT,      "\033[1;2A",     0,    0},
	{ XKB_KEY_Up,            MOD_MASK_ALT,       "\033[1;3A",     0,    0},
	{ XKB_KEY_Up,         MOD_MASK_SHIFT|MOD_MASK_ALT,"\033[1;4A",     0,    0},
	{ XKB_KEY_Up,            MOD_MASK_CTRL,    "\033[1;5A",     0,    0},
	{ XKB_KEY_Up,      MOD_MASK_SHIFT|MOD_MASK_CTRL,"\033[1;6A",     0,    0},
	{ XKB_KEY_Up,       MOD_MASK_CTRL|MOD_MASK_ALT,"\033[1;7A",     0,    0},
	{ XKB_KEY_Up,MOD_MASK_SHIFT|MOD_MASK_CTRL|MOD_MASK_ALT,"\033[1;8A",  0,    0},
	{ XKB_KEY_Up,            MOD_MASK_ANY,     "\033[A",        0,   -1},
	{ XKB_KEY_Up,            MOD_MASK_ANY,     "\033OA",        0,   +1},
	{ XKB_KEY_Down,          MOD_MASK_SHIFT,      "\033[1;2B",     0,    0},
	{ XKB_KEY_Down,          MOD_MASK_ALT,       "\033[1;3B",     0,    0},
	{ XKB_KEY_Down,       MOD_MASK_SHIFT|MOD_MASK_ALT,"\033[1;4B",     0,    0},
	{ XKB_KEY_Down,          MOD_MASK_CTRL,    "\033[1;5B",     0,    0},
	{ XKB_KEY_Down,    MOD_MASK_SHIFT|MOD_MASK_CTRL,"\033[1;6B",     0,    0},
	{ XKB_KEY_Down,     MOD_MASK_CTRL|MOD_MASK_ALT,"\033[1;7B",     0,    0},
	{ XKB_KEY_Down,MOD_MASK_SHIFT|MOD_MASK_CTRL|MOD_MASK_ALT,"\033[1;8B",0,    0},
	{ XKB_KEY_Down,          MOD_MASK_ANY,     "\033[B",        0,   -1},
	{ XKB_KEY_Down,          MOD_MASK_ANY,     "\033OB",        0,   +1},
	{ XKB_KEY_Left,          MOD_MASK_SHIFT,      "\033[1;2D",     0,    0},
	{ XKB_KEY_Left,          MOD_MASK_ALT,       "\033[1;3D",     0,    0},
	{ XKB_KEY_Left,       MOD_MASK_SHIFT|MOD_MASK_ALT,"\033[1;4D",     0,    0},
	{ XKB_KEY_Left,          MOD_MASK_CTRL,    "\033[1;5D",     0,    0},
	{ XKB_KEY_Left,    MOD_MASK_SHIFT|MOD_MASK_CTRL,"\033[1;6D",     0,    0},
	{ XKB_KEY_Left,     MOD_MASK_CTRL|MOD_MASK_ALT,"\033[1;7D",     0,    0},
	{ XKB_KEY_Left,MOD_MASK_SHIFT|MOD_MASK_CTRL|MOD_MASK_ALT,"\033[1;8D",0,    0},
	{ XKB_KEY_Left,          MOD_MASK_ANY,     "\033[D",        0,   -1},
	{ XKB_KEY_Left,          MOD_MASK_ANY,     "\033OD",        0,   +1},
	{ XKB_KEY_Right,         MOD_MASK_SHIFT,      "\033[1;2C",     0,    0},
	{ XKB_KEY_Right,         MOD_MASK_ALT,       "\033[1;3C",     0,    0},
	{ XKB_KEY_Right,      MOD_MASK_SHIFT|MOD_MASK_ALT,"\033[1;4C",     0,    0},
	{ XKB_KEY_Right,         MOD_MASK_CTRL,    "\033[1;5C",     0,    0},
	{ XKB_KEY_Right,   MOD_MASK_SHIFT|MOD_MASK_CTRL,"\033[1;6C",     0,    0},
	{ XKB_KEY_Right,    MOD_MASK_CTRL|MOD_MASK_ALT,"\033[1;7C",     0,    0},
	{ XKB_KEY_Right,MOD_MASK_SHIFT|MOD_MASK_CTRL|MOD_MASK_ALT,"\033[1;8C",0,   0},
	{ XKB_KEY_Right,         MOD_MASK_ANY,     "\033[C",        0,   -1},
	{ XKB_KEY_Right,         MOD_MASK_ANY,     "\033OC",        0,   +1},
	{ XKB_KEY_ISO_Left_Tab,  MOD_MASK_SHIFT,      "\033[Z",        0,    0},
	{ XKB_KEY_Return,        MOD_MASK_ALT,       "\033\r",        0,    0},
	{ XKB_KEY_Return,        MOD_MASK_ANY,     "\r",            0,    0},
	{ XKB_KEY_Insert,        MOD_MASK_SHIFT,      "\033[4l",      -1,    0},
	{ XKB_KEY_Insert,        MOD_MASK_SHIFT,      "\033[2;2~",    +1,    0},
	{ XKB_KEY_Insert,        MOD_MASK_CTRL,    "\033[L",       -1,    0},
	{ XKB_KEY_Insert,        MOD_MASK_CTRL,    "\033[2;5~",    +1,    0},
	{ XKB_KEY_Insert,        MOD_MASK_ANY,     "\033[4h",      -1,    0},
	{ XKB_KEY_Insert,        MOD_MASK_ANY,     "\033[2~",      +1,    0},
	{ XKB_KEY_Delete,        MOD_MASK_CTRL,    "\033[M",       -1,    0},
	{ XKB_KEY_Delete,        MOD_MASK_CTRL,    "\033[3;5~",    +1,    0},
	{ XKB_KEY_Delete,        MOD_MASK_SHIFT,      "\033[2K",      -1,    0},
	{ XKB_KEY_Delete,        MOD_MASK_SHIFT,      "\033[3;2~",    +1,    0},
	#if DELKEY_PATCH
	{ XKB_KEY_Delete,        MOD_MASK_ANY,     "\033[3~",      -1,    0},
	#else
	{ XKB_KEY_Delete,        MOD_MASK_ANY,     "\033[P",       -1,    0},
	#endif // DELKEY_PATCH
	{ XKB_KEY_Delete,        MOD_MASK_ANY,     "\033[3~",      +1,    0},
	{ XKB_KEY_BackSpace,     MOD_MASK_NONE,      "\177",          0,    0},
	{ XKB_KEY_BackSpace,     MOD_MASK_ALT,       "\033\177",      0,    0},
	{ XKB_KEY_BackSpace,     MOD_MASK_CTRL,    "\037",          0,    0},  /* \x1f = CtrlUnderscore — micro binds this to DeleteWordLeft */
	{ XKB_KEY_Home,          MOD_MASK_SHIFT,      "\033[1;2~",     0,    0},
	{ XKB_KEY_Home,          MOD_MASK_ANY,     "\033[H",        0,   -1},
	{ XKB_KEY_Home,          MOD_MASK_ANY,     "\033[1~",       0,   +1},
	{ XKB_KEY_End,           MOD_MASK_CTRL,    "\033[4;5~",    0,     0},
	{ XKB_KEY_End,           MOD_MASK_SHIFT,      "\033[4;2~",    0,     0},
	{ XKB_KEY_End,           MOD_MASK_ANY,     "\033[4~",       0,    0},
	{ XKB_KEY_Prior,         MOD_MASK_CTRL,    "\033[5;5~",     0,    0},
	{ XKB_KEY_Prior,         MOD_MASK_SHIFT,      "\033[5;2~",     0,    0},
	{ XKB_KEY_Prior,         MOD_MASK_ANY,     "\033[5~",       0,    0},
	{ XKB_KEY_Next,          MOD_MASK_CTRL,    "\033[6;5~",     0,    0},
	{ XKB_KEY_Next,          MOD_MASK_SHIFT,      "\033[6;2~",     0,    0},
	{ XKB_KEY_Next,          MOD_MASK_ANY,     "\033[6~",       0,    0},
	{ XKB_KEY_F1,            MOD_MASK_NONE,      "\033OP" ,       0,    0},
	{ XKB_KEY_F1, /* F13 */  MOD_MASK_SHIFT,      "\033[1;2P",     0,    0},
	{ XKB_KEY_F1, /* F25 */  MOD_MASK_CTRL,    "\033[1;5P",     0,    0},
	{ XKB_KEY_F1, /* F37 */  MOD_MASK_LOGO,       "\033[1;6P",     0,    0},
	{ XKB_KEY_F1, /* F49 */  MOD_MASK_ALT,       "\033[1;3P",     0,    0},
//MH!!	{ XKB_KEY_F1, /* F61 */  Mod3Mask,       "\033[1;4P",     0,    0},
	{ XKB_KEY_F2,            MOD_MASK_NONE,      "\033OQ" ,       0,    0},
	{ XKB_KEY_F2, /* F14 */  MOD_MASK_SHIFT,      "\033[1;2Q",     0,    0},
	{ XKB_KEY_F2, /* F26 */  MOD_MASK_CTRL,    "\033[1;5Q",     0,    0},
	{ XKB_KEY_F2, /* F38 */  MOD_MASK_LOGO,       "\033[1;6Q",     0,    0},
	{ XKB_KEY_F2, /* F50 */  MOD_MASK_ALT,       "\033[1;3Q",     0,    0},
//MH!!	{ XKB_KEY_F2, /* F62 */  Mod3Mask,       "\033[1;4Q",     0,    0},
	{ XKB_KEY_F3,            MOD_MASK_NONE,      "\033OR" ,       0,    0},
	{ XKB_KEY_F3, /* F15 */  MOD_MASK_SHIFT,      "\033[1;2R",     0,    0},
	{ XKB_KEY_F3, /* F27 */  MOD_MASK_CTRL,    "\033[1;5R",     0,    0},
	{ XKB_KEY_F3, /* F39 */  MOD_MASK_LOGO,       "\033[1;6R",     0,    0},
	{ XKB_KEY_F3, /* F51 */  MOD_MASK_ALT,       "\033[1;3R",     0,    0},
//MH!!	{ XKB_KEY_F3, /* F63 */  Mod3Mask,       "\033[1;4R",     0,    0},
	{ XKB_KEY_F4,            MOD_MASK_NONE,      "\033OS" ,       0,    0},
	{ XKB_KEY_F4, /* F16 */  MOD_MASK_SHIFT,      "\033[1;2S",     0,    0},
	{ XKB_KEY_F4, /* F28 */  MOD_MASK_CTRL,    "\033[1;5S",     0,    0},
	{ XKB_KEY_F4, /* F40 */  MOD_MASK_LOGO,       "\033[1;6S",     0,    0},
	{ XKB_KEY_F4, /* F52 */  MOD_MASK_ALT,       "\033[1;3S",     0,    0},
	{ XKB_KEY_F5,            MOD_MASK_NONE,      "\033[15~",      0,    0},
	{ XKB_KEY_F5, /* F17 */  MOD_MASK_SHIFT,      "\033[15;2~",    0,    0},
	{ XKB_KEY_F5, /* F29 */  MOD_MASK_CTRL,    "\033[15;5~",    0,    0},
	{ XKB_KEY_F5, /* F41 */  MOD_MASK_LOGO,       "\033[15;6~",    0,    0},
	{ XKB_KEY_F5, /* F53 */  MOD_MASK_ALT,       "\033[15;3~",    0,    0},
	{ XKB_KEY_F6,            MOD_MASK_NONE,      "\033[17~",      0,    0},
	{ XKB_KEY_F6, /* F18 */  MOD_MASK_SHIFT,      "\033[17;2~",    0,    0},
	{ XKB_KEY_F6, /* F30 */  MOD_MASK_CTRL,    "\033[17;5~",    0,    0},
	{ XKB_KEY_F6, /* F42 */  MOD_MASK_LOGO,       "\033[17;6~",    0,    0},
	{ XKB_KEY_F6, /* F54 */  MOD_MASK_ALT,       "\033[17;3~",    0,    0},
	{ XKB_KEY_F7,            MOD_MASK_NONE,      "\033[18~",      0,    0},
	{ XKB_KEY_F7, /* F19 */  MOD_MASK_SHIFT,      "\033[18;2~",    0,    0},
	{ XKB_KEY_F7, /* F31 */  MOD_MASK_CTRL,    "\033[18;5~",    0,    0},
	{ XKB_KEY_F7, /* F43 */  MOD_MASK_LOGO,       "\033[18;6~",    0,    0},
	{ XKB_KEY_F7, /* F55 */  MOD_MASK_ALT,       "\033[18;3~",    0,    0},
	{ XKB_KEY_F8,            MOD_MASK_NONE,      "\033[19~",      0,    0},
	{ XKB_KEY_F8, /* F20 */  MOD_MASK_SHIFT,      "\033[19;2~",    0,    0},
	{ XKB_KEY_F8, /* F32 */  MOD_MASK_CTRL,    "\033[19;5~",    0,    0},
	{ XKB_KEY_F8, /* F44 */  MOD_MASK_LOGO,       "\033[19;6~",    0,    0},
	{ XKB_KEY_F8, /* F56 */  MOD_MASK_ALT,       "\033[19;3~",    0,    0},
	{ XKB_KEY_F9,            MOD_MASK_NONE,      "\033[20~",      0,    0},
	{ XKB_KEY_F9, /* F21 */  MOD_MASK_SHIFT,      "\033[20;2~",    0,    0},
	{ XKB_KEY_F9, /* F33 */  MOD_MASK_CTRL,    "\033[20;5~",    0,    0},
	{ XKB_KEY_F9, /* F45 */  MOD_MASK_LOGO,       "\033[20;6~",    0,    0},
	{ XKB_KEY_F9, /* F57 */  MOD_MASK_ALT,       "\033[20;3~",    0,    0},
	{ XKB_KEY_F10,           MOD_MASK_NONE,      "\033[21~",      0,    0},
	{ XKB_KEY_F10, /* F22 */ MOD_MASK_SHIFT,      "\033[21;2~",    0,    0},
	{ XKB_KEY_F10, /* F34 */ MOD_MASK_CTRL,    "\033[21;5~",    0,    0},
	{ XKB_KEY_F10, /* F46 */ MOD_MASK_LOGO,       "\033[21;6~",    0,    0},
	{ XKB_KEY_F10, /* F58 */ MOD_MASK_ALT,       "\033[21;3~",    0,    0},
	{ XKB_KEY_F11,           MOD_MASK_NONE,      "\033[23~",      0,    0},
	{ XKB_KEY_F11, /* F23 */ MOD_MASK_SHIFT,      "\033[23;2~",    0,    0},
	{ XKB_KEY_F11, /* F35 */ MOD_MASK_CTRL,    "\033[23;5~",    0,    0},
	{ XKB_KEY_F11, /* F47 */ MOD_MASK_LOGO,       "\033[23;6~",    0,    0},
	{ XKB_KEY_F11, /* F59 */ MOD_MASK_ALT,       "\033[23;3~",    0,    0},
	{ XKB_KEY_F12,           MOD_MASK_NONE,      "\033[24~",      0,    0},
	{ XKB_KEY_F12, /* F24 */ MOD_MASK_SHIFT,      "\033[24;2~",    0,    0},
	{ XKB_KEY_F12, /* F36 */ MOD_MASK_CTRL,    "\033[24;5~",    0,    0},
	{ XKB_KEY_F12, /* F48 */ MOD_MASK_LOGO,       "\033[24;6~",    0,    0},
	{ XKB_KEY_F12, /* F60 */ MOD_MASK_ALT,       "\033[24;3~",    0,    0},
	{ XKB_KEY_F13,           MOD_MASK_NONE,      "\033[1;2P",     0,    0},
	{ XKB_KEY_F14,           MOD_MASK_NONE,      "\033[1;2Q",     0,    0},
	{ XKB_KEY_F15,           MOD_MASK_NONE,      "\033[1;2R",     0,    0},
	{ XKB_KEY_F16,           MOD_MASK_NONE,      "\033[1;2S",     0,    0},
	{ XKB_KEY_F17,           MOD_MASK_NONE,      "\033[15;2~",    0,    0},
	{ XKB_KEY_F18,           MOD_MASK_NONE,      "\033[17;2~",    0,    0},
	{ XKB_KEY_F19,           MOD_MASK_NONE,      "\033[18;2~",    0,    0},
	{ XKB_KEY_F20,           MOD_MASK_NONE,      "\033[19;2~",    0,    0},
	{ XKB_KEY_F21,           MOD_MASK_NONE,      "\033[20;2~",    0,    0},
	{ XKB_KEY_F22,           MOD_MASK_NONE,      "\033[21;2~",    0,    0},
	{ XKB_KEY_F23,           MOD_MASK_NONE,      "\033[23;2~",    0,    0},
	{ XKB_KEY_F24,           MOD_MASK_NONE,      "\033[24;2~",    0,    0},
	{ XKB_KEY_F25,           MOD_MASK_NONE,      "\033[1;5P",     0,    0},
	{ XKB_KEY_F26,           MOD_MASK_NONE,      "\033[1;5Q",     0,    0},
	{ XKB_KEY_F27,           MOD_MASK_NONE,      "\033[1;5R",     0,    0},
	{ XKB_KEY_F28,           MOD_MASK_NONE,      "\033[1;5S",     0,    0},
	{ XKB_KEY_F29,           MOD_MASK_NONE,      "\033[15;5~",    0,    0},
	{ XKB_KEY_F30,           MOD_MASK_NONE,      "\033[17;5~",    0,    0},
	{ XKB_KEY_F31,           MOD_MASK_NONE,      "\033[18;5~",    0,    0},
	{ XKB_KEY_F32,           MOD_MASK_NONE,      "\033[19;5~",    0,    0},
	{ XKB_KEY_F33,           MOD_MASK_NONE,      "\033[20;5~",    0,    0},
	{ XKB_KEY_F34,           MOD_MASK_NONE,      "\033[21;5~",    0,    0},
	{ XKB_KEY_F35,           MOD_MASK_NONE,      "\033[23;5~",    0,    0},
};
#endif // FIXKEYBOARDINPUT_PATCH

/*
 * Selection types' masks.
 * Use the same masks as usual.
 * Button1Mask is always unset, to make masks match between ButtonPress.
 * ButtonRelease and MotionNotify.
 * If no match is found, regular selection is used.
 */
static uint selmasks[] = {
	[SEL_RECTANGULAR] = MOD_MASK_ALT,
};

/*
 * Printable characters in ASCII, used to estimate the advance width
 * of single wide characters.
 */
static char ascii_printable[] =
	" !\"#$%&'()*+,-./0123456789:;<=>?"
	"@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_"
	"`abcdefghijklmnopqrstuvwxyz{|}~";

#if RIGHTCLICKTOPLUMB_PATCH
/*
 * plumb_cmd is run on mouse button 3 click, with argument set to
 * current selection and with cwd set to the cwd of the active shell
 */
static char *plumb_cmd = "plumb";
#endif // RIGHTCLICKTOPLUMB_PATCH

#if UNDERCURL_PATCH
/**
 * Undercurl style. Set UNDERCURL_STYLE to one of the available styles.
 *
 * Curly: Dunno how to draw it *shrug*
 *  _   _   _   _
 * ( ) ( ) ( ) ( )
 *	 (_) (_) (_) (_)
 *
 * Spiky:
 * /\  /\   /\	/\
 *   \/  \/	  \/
 *
 * Capped:
 *	_     _     _
 * / \   / \   / \
 *    \_/   \_/
 */
// Available styles
#define UNDERCURL_CURLY 0
#define UNDERCURL_SPIKY 1
#define UNDERCURL_CAPPED 2
// Active style
#define UNDERCURL_STYLE UNDERCURL_SPIKY
#endif // UNDERCURL_PATCH
