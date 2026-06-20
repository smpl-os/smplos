#!/usr/bin/env bash
# smplOS — translate bindings.conf → niri binds.kdl
#
# Reads src/shared/configs/smplos/bindings.conf (Hyprland bindd format,
# the project-wide single source of truth) and emits a niri KDL
# binds {} block to src/compositors/niri/binds.kdl (or to stdout).
#
# Usage:
#   bindings-to-niri.sh                       # write to default path
#   bindings-to-niri.sh /path/to/bindings.conf /path/to/binds.kdl
#   bindings-to-niri.sh - -                   # read stdin, write stdout
#
# Lines that have no niri equivalent (submap, togglegroup, mouse-scroll
# binds, etc.) are emitted as KDL comments so nothing is silently dropped.
#
# IMPORTANT: this script does NOT modify bindings.conf. To change a
# binding, edit bindings.conf and rerun this translator.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

SRC_DEFAULT="$REPO_ROOT/src/shared/configs/smplos/bindings.conf"
DST_DEFAULT="$REPO_ROOT/src/compositors/niri/binds.kdl"

SRC="${1:-$SRC_DEFAULT}"
DST="${2:-$DST_DEFAULT}"

# ── helpers ────────────────────────────────────────────────────────────────

# Translate Hyprland mod set ("SUPER SHIFT", "SUPER CTRL ALT") to niri form.
# Niri's modifier names: Mod (Super), Ctrl, Shift, Alt, ISO_Level3_Shift.
# Always emits in stable order: Mod, Ctrl, Shift, Alt.
mods_to_niri() {
  local raw="$1" mods=""
  [[ "$raw" =~ SUPER ]] && mods+="Mod+"
  [[ "$raw" =~ CTRL  ]] && mods+="Ctrl+"
  [[ "$raw" =~ SHIFT ]] && mods+="Shift+"
  [[ "$raw" =~ ALT   ]] && mods+="Alt+"
  printf '%s' "$mods"
}

# Translate Hyprland key spec to niri keysym.
# Returns empty string if untranslatable (caller should skip + comment).
key_to_niri() {
  local k="$1"
  # Physical keycodes — handle BEFORE case normalization since `code:` is
  # lowercase by convention and would be CODE: after ${k^^}.
  case "$k" in
    code:10) echo 1; return ;;
    code:11) echo 2; return ;;
    code:12) echo 3; return ;;
    code:13) echo 4; return ;;
    code:14) echo 5; return ;;
    code:15) echo 6; return ;;
    code:16) echo 7; return ;;
    code:17) echo 8; return ;;
    code:18) echo 9; return ;;
    code:19) echo 0; return ;;
    # Mouse buttons + scroll wheel — niri uses Mouse{Left,Right,Middle} but
    # these are NOT keybindable; niri handles drag/scroll via dedicated
    # mouse-bindings config (out of scope here). Mark as skip.
    mouse_down|mouse_up|mouse:272|mouse:273|mouse:274) echo ""; return ;;
  esac
  # Normalize common named keys to uppercase so mixed-case input
  # (e.g. "Escape", "BackSpace") matches the same case arm.
  local ku="${k^^}"
  case "$ku" in
    RETURN)    echo Return ;;
    SPACE)     echo Space ;;
    ESCAPE)    echo Escape ;;
    TAB)       echo Tab ;;
    PRINT)     echo Print ;;
    BACKSPACE) echo BackSpace ;;
    LEFT)      echo Left ;;
    RIGHT)     echo Right ;;
    UP)        echo Up ;;
    DOWN)      echo Down ;;
    COMMA)     echo comma ;;
    # SUPER_L is Hyprland's "lone Super tap" — niri has no equivalent.
    SUPER_L)   echo "" ;;
    # XF86 media/brightness keys pass through verbatim (same naming).
    XF86*)     echo "$k" ;;
    # Pre-translated keysyms (already in correct form)
    F1|F2|F3|F4|F5|F6|F7|F8|F9|F10|F11|F12) echo "$k" ;;
    # Single ASCII letter / digit / printable — niri uses lowercase
    [a-zA-Z])  echo "${k,,}" ;;
    [0-9])     echo "$k" ;;
    EQUAL|MINUS|PLUS|PERIOD|SLASH|BACKSLASH|SEMICOLON|APOSTROPHE|GRAVE|BRACKETLEFT|BRACKETRIGHT)
               echo "${ku,,}" ;;
    equal|minus|plus|period|slash|backslash|semicolon|apostrophe|grave|bracketleft|bracketright)
               echo "$k" ;;
    # Unknown — caller handles
    *)         echo "" ;;
  esac
}

# Escape a string for KDL — backslash and double-quote.
kdl_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  printf '%s' "$s"
}

# Emit a niri spawn action from a shell command string.
# We do NOT split args — niri's `spawn` takes multiple args, but parsing
# a shell command line (with quotes/pipes/&&) is unreliable. Wrap the
# whole thing in `sh -c "..."` instead. This is more portable and
# preserves the original Hyprland behaviour (which also runs via sh).
emit_spawn() {
  local cmd="$1"
  printf 'spawn "sh" "-c" "%s";' "$(kdl_escape "$cmd")"
}

# Translate a single Hyprland dispatcher (without `exec`) into niri actions.
# Returns:
#   stdout = niri action(s)  (e.g. "close-window;")
#   exit 1 = no translation (caller emits a comment)
translate_dispatcher() {
  local disp="$1" args="$2"

  case "$disp" in
    exec)
      emit_spawn "$args"
      ;;
    killactive)
      printf 'close-window;'
      ;;
    togglefloating)
      printf 'toggle-window-floating;'
      ;;
    fullscreen)
      # `fullscreen` no arg = full screen; `fullscreen, 0` = full screen
      # `fullscreen, 1` = full width (niri: maximize-column)
      case "$args" in
        1)    printf 'maximize-column;' ;;
        *)    printf 'fullscreen-window;' ;;
      esac
      ;;
    fullscreenstate)
      # `fullscreenstate, 0 2` = tiled fullscreen — niri has no exact
      # equivalent; expand-column-to-available-width is closest.
      printf 'expand-column-to-available-width;'
      ;;
    movefocus)
      case "$args" in
        l|left)  printf 'focus-column-left;' ;;
        r|right) printf 'focus-column-right;' ;;
        u|up)    printf 'focus-window-up;' ;;
        d|down)  printf 'focus-window-down;' ;;
        *)       return 1 ;;
      esac
      ;;
    swapwindow)
      case "$args" in
        l|left)  printf 'move-column-left;' ;;
        r|right) printf 'move-column-right;' ;;
        u|up)    printf 'move-window-up;' ;;
        d|down)  printf 'move-window-down;' ;;
        *)       return 1 ;;
      esac
      ;;
    workspace)
      case "$args" in
        previous) printf 'focus-workspace-previous;' ;;
        +1|e+1)   printf 'focus-workspace-down;' ;;
        -1|e-1)   printf 'focus-workspace-up;' ;;
        [0-9]*)   printf 'focus-workspace %s;' "$args" ;;
        *)        return 1 ;;
      esac
      ;;
    movetoworkspacesilent|movetoworkspace)
      # `special:scratchpad` etc. — niri has no special workspaces.
      case "$args" in
        special:*) return 1 ;;
        [0-9]*)    printf 'move-column-to-workspace %s;' "$args" ;;
        *)         return 1 ;;
      esac
      ;;
    movecurrentworkspacetomonitor)
      case "$args" in
        l|left)  printf 'move-workspace-to-monitor-left;' ;;
        r|right) printf 'move-workspace-to-monitor-right;' ;;
        u|up)    printf 'move-workspace-to-monitor-up;' ;;
        d|down)  printf 'move-workspace-to-monitor-down;' ;;
        *)       return 1 ;;
      esac
      ;;
    pseudo)
      # Hyprland pseudo = window stays at one size when split.
      # Closest niri equivalent: center current column.
      printf 'center-column;'
      ;;
    togglesplit)
      # Cycle through preset column widths (1/3, 1/2, 2/3 by default).
      printf 'switch-preset-column-width;'
      ;;
    resizeactive)
      # `resizeactive, X Y` — width delta, height delta.
      # Niri: set-column-width "+X"; set-window-height "+Y"
      # Only emit the non-zero axis to keep output clean.
      local dx dy
      dx="${args%% *}"
      dy="${args##* }"
      local out=""
      [[ "$dx" != "0" && -n "$dx" ]] && out+="set-column-width \"$dx\"; "
      [[ "$dy" != "0" && -n "$dy" ]] && out+="set-window-height \"$dy\";"
      [[ -n "$out" ]] || return 1
      printf '%s' "$out"
      ;;
    exit)
      printf 'quit;'
      ;;
    # ── No niri equivalent — caller should emit as comment ────────────
    submap|togglespecialworkspace|togglegroup|moveoutofgroup|moveintogroup|\
    changegroupactive|pin|setprop|movewindow|resizewindow)
      return 1
      ;;
    *)
      return 1
      ;;
  esac
  return 0
}

# Strip leading/trailing whitespace
trim() {
  local s="$*"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

# ── header ─────────────────────────────────────────────────────────────────

if [[ "$DST" == "-" ]]; then
  exec >&1
else
  exec >"$DST"
fi

if [[ "$SRC" == "-" ]]; then
  : # read from stdin
else
  exec <"$SRC"
fi

cat <<'EOF'
// smplOS niri keybindings — AUTO-GENERATED. DO NOT EDIT.
//
// Generated by: src/shared/bin/bindings-to-niri.sh
// Source:      src/shared/configs/smplos/bindings.conf
//
// To change a binding: edit bindings.conf (the single source of truth across
// all compositors), then re-run bindings-to-niri.sh to regenerate this file.

binds {
EOF

# ── parse loop ─────────────────────────────────────────────────────────────

in_submap=""

while IFS= read -r line || [[ -n "$line" ]]; do
  # Skip empty + comment lines
  stripped="$(trim "$line")"
  [[ -z "$stripped" ]] && continue
  [[ "$stripped" == \#* ]] && continue

  # submap directive — niri has no submaps. Track for context, emit comment.
  if [[ "$stripped" =~ ^submap[[:space:]]*=[[:space:]]*(.+)$ ]]; then
    in_submap="${BASH_REMATCH[1]}"
    in_submap="$(trim "$in_submap")"
    if [[ "$in_submap" == "reset" ]]; then
      echo "    // ── end submap ──"
      in_submap=""
    else
      echo "    // ── submap '$in_submap' (niri has no submaps — these binds are skipped) ──"
    fi
    continue
  fi

  # Binding line. Format:
  #   bindFLAGS = MODS, KEY, [DESCRIPTION,] DISPATCHER[, ARGS]
  # Where bindd has description, bind/bindr does not.
  if [[ "$stripped" =~ ^bind([a-z]*)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
    flags="${BASH_REMATCH[1]}"
    rest="${BASH_REMATCH[2]}"
  else
    continue
  fi

  # Skip everything inside an active submap (niri can't represent them).
  if [[ -n "$in_submap" ]]; then
    echo "    // (submap '$in_submap') $stripped"
    continue
  fi

  # Split on commas — but only the first 4 splits matter; the rest is args
  # that may legitimately contain commas (e.g. `exec, cmd a, b`).
  IFS=',' read -r f_mods f_key f_3 f_4 f_rest <<<"$rest"
  f_mods="$(trim "$f_mods")"
  f_key="$(trim "$f_key")"
  f_3="$(trim "$f_3")"
  f_4="$(trim "$f_4")"
  f_rest="$(trim "${f_rest:-}")"

  # Has description? bindd / bindde / bindeld / bindmd / bindld / bindle.
  # The `d` flag means: 3rd field IS the description (NOT the dispatcher).
  has_desc=false
  [[ "$flags" == *d* ]] && has_desc=true

  if $has_desc; then
    desc="$f_3"
    disp="$f_4"
    args="$f_rest"
  else
    desc=""
    disp="$f_3"
    args="$(trim "$f_4${f_rest:+,$f_rest}")"
  fi

  # Build niri key spec
  mods="$(mods_to_niri "$f_mods")"
  key="$(key_to_niri "$f_key")"

  if [[ -z "$key" ]]; then
    echo "    // SKIP (untranslatable key '$f_key'): $stripped"
    continue
  fi

  # Translate dispatcher
  if action="$(translate_dispatcher "$disp" "$args")"; then
    if [[ -n "$desc" ]]; then
      printf '    %s%s hotkey-overlay-title="%s" { %s }\n' \
        "$mods" "$key" "$(kdl_escape "$desc")" "$action"
    else
      printf '    %s%s { %s }\n' "$mods" "$key" "$action"
    fi
  else
    echo "    // SKIP (no niri equivalent for '$disp $args'): $stripped"
  fi
done

cat <<'EOF'
}
EOF
