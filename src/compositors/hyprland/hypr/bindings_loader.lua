-- bindings_loader.lua — parses hyprlang `bindXXX = …` files and emits the
-- equivalent hl.bind() / hl.define_submap() calls.
--
-- Why we parse hyprlang from Lua:
--   • src/shared/configs/smplos/bindings.conf is the **single source of truth**
--     for keybindings. The DWM build (future) parses the same file into C
--     structs, and src/shared/bin/keybind-help renders an EWW overlay from it.
--     Keeping it hyprlang preserves that invariant.
--   • messenger-bindings.conf is generated at runtime by
--     `generate-messenger-bindings`. Same parser handles it.
--
-- Supported variants (the suffix letters control bind options):
--   bindd     — description present
--   bindeld   — desc + locked + repeating
--   bindld    — desc + locked
--   bindde    — desc + repeating
--   bindmd    — desc + mouse
--   bindr     — release (no description)
--
-- Submap blocks:
--   submap = NAME   — start collecting binds into a submap
--   submap = reset  — close the most recent submap (registered via
--                     hl.define_submap so the binds activate only when the
--                     submap is entered)

local M = {}

local function trim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end

-- Split "a, b, c, d, ..." into a list of trimmed fields.
local function split_csv(s)
    local out = {}
    -- gsub trick: append a sentinel comma so the loop captures the final field.
    for field in (s .. ","):gmatch("([^,]*),") do
        table.insert(out, trim(field))
    end
    return out
end

-- ── Combo builder ──────────────────────────────────────────────────────────
-- Hyprland's Lua API expects "MOD + MOD + KEY" (or just "KEY" if no mods).
local function build_combo(mods, key)
    mods = trim(mods)
    if mods == "" then return key end
    local parts = {}
    for tok in mods:gmatch("%S+") do table.insert(parts, tok) end
    table.insert(parts, key)
    return table.concat(parts, " + ")
end

-- ── Key translation ────────────────────────────────────────────────────────
-- The hyprlang config language accepts `code:NN` as a layout-agnostic keycode
-- binding (e.g. `code:10` = physical "1" key on any layout). The Hyprland
-- Lua API (`hl.bind`) does NOT understand this syntax — it only accepts
-- keysym names. Passing `code:10` to hl.bind silently registers a bind with
-- empty key + keycode=0, so the bind never fires.
--
-- We map the digit-row keycodes 10..19 to "1".."0" (US layout). This means
-- non-US layouts where Shift+digit produces non-digits will type the wrong
-- keysym on the digit row — accepted trade-off because smplOS ships US as
-- the default and bindings.conf is the single source of truth for both
-- compositors. If Hyprland ever exposes keycode binds via Lua, swap this
-- table for the proper API call.
local CODE_TO_KEYSYM = {
    ["code:10"] = "1", ["code:11"] = "2", ["code:12"] = "3",
    ["code:13"] = "4", ["code:14"] = "5", ["code:15"] = "6",
    ["code:16"] = "7", ["code:17"] = "8", ["code:18"] = "9",
    ["code:19"] = "0",
}

local function translate_key(key)
    return CODE_TO_KEYSYM[key] or key
end

-- ── Bind-option flags ──────────────────────────────────────────────────────
-- The flag letters appear between literal "bind" and "=".
local function parse_flags(prefix)
    -- prefix like "bindeld" → after stripping "bind" → "eld"
    local letters = prefix:sub(5)
    local opts, has_desc = {}, false
    for i = 1, #letters do
        local c = letters:sub(i, i)
        if     c == "d" then has_desc = true
        elseif c == "e" then opts.repeating = true
        elseif c == "l" then opts.locked    = true
        elseif c == "m" then opts.mouse       = true
        elseif c == "r" then opts.release     = true
        elseif c == "i" then opts.ignore_mods = true
        -- Other Hyprland flags (n/non-consuming, p/dont-inhibit, t/transparent,
        -- s/multi-key, c/click) — uncommon in our config; add here if we ever
        -- use them.
        end
    end
    return opts, has_desc
end

-- ── Dispatcher translation ────────────────────────────────────────────────
-- Map hyprlang dispatchers to native hl.dsp calls.
--
-- IMPORTANT: in Hyprland 0.55 lua-config mode there is NO working fallback to
-- `hyprctl dispatch <name> <arg>` — hyprctl reinterprets its argument as Lua
-- (`hl.dispatch(...)`), so legacy dispatcher names fail silently ("ok" but no
-- effect). Every dispatcher used by bindings.conf MUST therefore have an
-- explicit native mapping below; unknown ones bind to a logged no-op.
local DIR = { l = "left", r = "right", u = "up", d = "down" }

-- Workspace selector: numeric → number; otherwise pass the hyprland selector
-- string verbatim (e+1, e-1, previous, special:scratchpad, …).
local function ws_arg(arg)
    return tonumber(arg) or arg
end

local function make_dispatcher(dispatcher, arg)
    arg = arg or ""

    if dispatcher == "exec" then
        return hl.dsp.exec_cmd(arg)

    elseif dispatcher == "killactive" then
        return hl.dsp.window.close()

    elseif dispatcher == "togglefloating" then
        return hl.dsp.window.float({ action = "toggle" })

    elseif dispatcher == "pseudo" then
        return hl.dsp.window.pseudo()

    elseif dispatcher == "pin" then
        return hl.dsp.window.pin()

    elseif dispatcher == "fullscreen" then
        return hl.dsp.window.fullscreen(tonumber(arg) or 0)

    elseif dispatcher == "fullscreenstate" then
        -- arg: "<internal> <client>" (e.g. "0 2")
        local a, b = arg:match("^(%-?%d+)%s+(%-?%d+)$")
        return hl.dsp.window.fullscreen_state({
            internal = tonumber(a) or -1,
            client   = tonumber(b) or -1,
        })

    elseif dispatcher == "togglegroup" then
        return hl.dsp.group.toggle()

    elseif dispatcher == "changegroupactive" then
        -- f = forward (next window in group), b = back (previous)
        if arg == "b" then return hl.dsp.group.prev() end
        return hl.dsp.group.next()

    elseif dispatcher == "moveintogroup" then
        return hl.dsp.group.move_window({ direction = DIR[arg] or arg })

    elseif dispatcher == "moveoutofgroup" then
        return hl.dsp.group.move_window()

    elseif dispatcher == "togglespecialworkspace" then
        return hl.dsp.workspace.toggle_special(arg)

    elseif dispatcher == "togglesplit" then
        return hl.dsp.layout("togglesplit")

    elseif dispatcher == "workspace" then
        return hl.dsp.focus({ workspace = ws_arg(arg) })

    elseif dispatcher == "movetoworkspace" then
        return hl.dsp.window.move({ workspace = ws_arg(arg) })

    elseif dispatcher == "movetoworkspacesilent" then
        return hl.dsp.window.move({ workspace = ws_arg(arg), silent = true })

    elseif dispatcher == "movecurrentworkspacetomonitor" then
        return hl.dsp.workspace.move({ monitor = DIR[arg] or arg })

    elseif dispatcher == "movefocus" then
        return hl.dsp.focus({ direction = DIR[arg] or arg })

    elseif dispatcher == "swapwindow" then
        return hl.dsp.window.swap({ direction = DIR[arg] or arg })

    elseif dispatcher == "resizeactive" then
        -- arg: "<dx> <dy>" relative pixels (e.g. "-20 0")
        local dx, dy = arg:match("^(%-?%d+)%s+(%-?%d+)$")
        return hl.dsp.window.resize({
            x = tonumber(dx) or 0,
            y = tonumber(dy) or 0,
            relative = true,
        })

    elseif dispatcher == "movewindow" then
        if arg == "" then return hl.dsp.window.drag() end            -- mouse drag
        local mon = arg:match("^mon:(.+)$")
        if mon then return hl.dsp.window.move({ monitor = DIR[mon] or mon }) end
        return hl.dsp.window.move({ direction = DIR[arg] or arg })

    elseif dispatcher == "resizewindow" then
        if arg == "" then return hl.dsp.window.resize() end          -- mouse resize
        local dx, dy = arg:match("^(%-?%d+)%s+(%-?%d+)$")
        return hl.dsp.window.resize({
            x = tonumber(dx) or 0,
            y = tonumber(dy) or 0,
            relative = true,
        })

    elseif dispatcher == "submap" then
        return hl.dsp.submap(arg)

    elseif dispatcher == "exit" then
        return hl.dsp.exit()
    end

    -- Unknown dispatcher: there is no working shell fallback in lua mode, so
    -- log it (visible in the Hyprland log) and bind a no-op so the rest of
    -- the config still loads. Add a native mapping above if a new dispatcher
    -- starts being used in bindings.conf.
    io.stderr:write(string.format(
        "[bindings_loader] unmapped dispatcher '%s' (arg='%s') — bound as no-op\n",
        dispatcher, arg))
    return hl.dsp.no_op()
end

-- ── File loader ────────────────────────────────────────────────────────────

function M.load(path)
    local f = io.open(path, "r")
    if not f then return end

    -- Submap state: when current_submap is non-nil, binds accumulate into
    -- submap_binds instead of being registered immediately. Closing the
    -- submap (submap = reset) flushes them via hl.define_submap.
    local current_submap = nil
    local submap_binds = {}

    local function emit_bind(keys, dispatcher, opts)
        if current_submap then
            table.insert(submap_binds, { keys = keys, dispatcher = dispatcher, opts = opts })
        else
            hl.bind(keys, dispatcher, opts)
        end
    end

    local function close_submap()
        if not current_submap then return end
        local name  = current_submap
        local binds = submap_binds
        hl.define_submap(name, function()
            for _, b in ipairs(binds) do
                hl.bind(b.keys, b.dispatcher, b.opts)
            end
        end)
        current_submap = nil
        submap_binds   = {}
    end

    for raw in f:lines() do
        local line = trim(raw)
        if line ~= "" and not line:match("^#") then
            -- submap = NAME  or  submap = reset
            local submap_target = line:match("^submap%s*=%s*(.+)$")
            if submap_target then
                submap_target = trim(submap_target)
                if submap_target == "reset" then
                    close_submap()
                else
                    -- Closing the previous submap (if any) is defensive — bindings.conf
                    -- always uses an explicit `submap = reset` before opening a new one.
                    close_submap()
                    current_submap = submap_target
                    submap_binds   = {}
                end
            else
                -- bindXXX = MODS, KEY, [DESC,] DISPATCHER[, ARG]
                local prefix, rhs = line:match("^(bind[a-z]*)%s*=%s*(.+)$")
                if prefix and rhs then
                    local opts, has_desc = parse_flags(prefix)
                    local fields         = split_csv(rhs)
                    local mods, key      = fields[1], fields[2]
                    local desc, disp, arg
                    if has_desc then
                        desc = fields[3]
                        disp = fields[4]
                        -- Arg may itself contain commas (e.g. exec with shell pipeline).
                        -- Rejoin everything after the dispatcher field.
                        if fields[5] then
                            arg = table.concat({ table.unpack(fields, 5) }, ",")
                            arg = trim(arg)
                        else
                            arg = ""
                        end
                    else
                        disp = fields[3]
                        if fields[4] then
                            arg = table.concat({ table.unpack(fields, 4) }, ",")
                            arg = trim(arg)
                        else
                            arg = ""
                        end
                    end
                    if mods and key and disp then
                        if desc and desc ~= "" then opts.description = desc end
                        local combo      = build_combo(mods, translate_key(key))
                        local dispatcher = make_dispatcher(disp, arg)
                        emit_bind(combo, dispatcher, opts)
                    end
                end
            end
        end
    end

    close_submap()  -- in case the file ends without an explicit reset
    f:close()
end

return M
