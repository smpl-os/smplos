local function require_live(pid, start, parent)
    local file = assert(io.open("/proc/" .. pid .. "/stat", "r"), "activation process unavailable")
    local stat = file:read("*a")
    file:close()
    local rest = assert(stat:match("^%d+ %(.+%) (.+)$"), "activation process invalid")
    local fields = {}
    for field in rest:gmatch("%S+") do fields[#fields + 1] = field end
    assert(fields[1] ~= "Z" and fields[1] ~= "X" and fields[1] ~= "x"
        and fields[20] == start and (not parent or fields[2] == tostring(parent)),
        "activation process stale")
end

local function checked(dispatcher)
    local result = dispatcher()
    assert(type(result) == "table" and result.ok == true, "activation dispatcher failed")
end

return function(helper, start, parent, parent_start, pid, pid_start)
    -- This guard runs on the compositor thread, not when the socket request queues.
    require_live(helper, start, parent)
    require_live(parent, parent_start)
    require_live(pid, pid_start)
    local signal
    for _, window in ipairs(hl.get_windows()) do
        local class = window.class:lower()
        if window.mapped and window.pid == pid
            and (class == "signal" or class == "org.signal.signal") then
            assert(not signal, "activation recipient ambiguous")
            signal = window
        end
    end
    assert(signal, "activation recipient unavailable")
    local active = hl.get_active_window()
    assert(active and active.mapped and not active.hidden and not active.pinned,
        "activation target unavailable")
    local target = active.workspace
    assert(target and not target.special and target.id > 0 and target.monitor,
        "activation target must be normal")
    local old = assert(signal.workspace, "activation source unavailable")
    local old_monitor = old.monitor
    if old.id ~= target.id then
        assert(not signal.group and not signal.pinned and not signal.swallowing,
            "activation recipient grouped, pinned or swallowing")
        local auto_group = hl.get_config("group.group_on_movetoworkspace")
        assert(auto_group ~= nil, "activation grouping policy unavailable")
        if auto_group ~= false and auto_group ~= 0 then
            for _, window in ipairs(hl.get_windows()) do
                assert(not (window.mapped and window.workspace and
                    window.workspace.id == target.id and window.group),
                    "activation destination grouped")
            end
        end
        if old.special then
            assert(old_monitor and type(old.windows) == "number",
                "activation source monitor unavailable")
            local auto_close = hl.get_config("misc.close_special_on_empty")
            assert(auto_close ~= nil, "activation special policy unavailable")
            local visible = old_monitor.active_special_workspace
            assert(not (auto_close ~= false and auto_close ~= 0 and old.windows <= 1
                and visible and visible.id ~= old.id), "activation would close another special")
        end
        checked(hl.dsp.window.move({window = signal, workspace = target.id, silent = true}))
        assert(signal.workspace and signal.workspace.id == target.id and not signal.group,
            "activation move incomplete")
        if old.special and old_monitor and old_monitor.active_special_workspace
            and old_monitor.active_special_workspace.id == old.id and old.is_empty then
            old_monitor:set_special_workspace({})
            assert(not old_monitor.active_special_workspace, "activation cleanup incomplete")
        end
    end
    checked(hl.dsp.focus({window = signal}))
    local focused = hl.get_active_window()
    assert(focused and focused.address == signal.address and focused.workspace
        and focused.workspace.id == target.id, "activation focus incomplete")
end
