-- monitors_loader.lua — parse the user's monitors.conf (written by Settings →
-- Display) and emit equivalent hl.monitor() calls.
--
-- monitors.conf is still maintained in hyprlang format because the smplOS
-- Settings app writes it. Parsing here keeps the settings app unchanged and
-- preserves on-the-fly monitor updates: Settings rewrites the file then
-- `hyprctl reload` re-runs this Lua and the new layout takes effect.
--
-- Supported line formats (subset that Settings emits):
--   monitor = <output>, <mode>, <position>, <scale>
--   monitor = <output>, <mode>, <position>, <scale>, transform, <n>
--   monitor = <output>, disable
--   monitor = <output>, addreserved, <top>, <bottom>, <left>, <right>

local M = {}

local function trim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end

local function split_csv(s)
    local out = {}
    for field in (s .. ","):gmatch("([^,]*),") do
        table.insert(out, trim(field))
    end
    return out
end

function M.load(path)
    local f = io.open(path, "r")
    if not f then return end
    for raw in f:lines() do
        local line = trim(raw)
        if line ~= "" and not line:match("^#") then
            local rhs = line:match("^monitor%s*=%s*(.+)$")
            if rhs then
                local parts = split_csv(rhs)
                local output = parts[1] or ""
                if parts[2] == "disable" then
                    hl.monitor({ output = output, disabled = true })
                elseif parts[2] == "addreserved" then
                    -- top, bottom, left, right
                    hl.monitor({
                        output = output,
                        reserved = {
                            top    = tonumber(parts[3]) or 0,
                            bottom = tonumber(parts[4]) or 0,
                            left   = tonumber(parts[5]) or 0,
                            right  = tonumber(parts[6]) or 0,
                        },
                    })
                else
                    local spec = {
                        output   = output,
                        mode     = parts[2] or "preferred",
                        position = parts[3] or "auto",
                        scale    = parts[4] or "auto",
                    }
                    -- Optional trailing "transform, N"
                    for i = 5, #parts - 1 do
                        if parts[i] == "transform" then
                            spec.transform = tonumber(parts[i + 1])
                        end
                    end
                    -- Scale is "auto" or a number string; hl.monitor accepts both.
                    if spec.scale ~= "auto" then
                        local n = tonumber(spec.scale)
                        if n then spec.scale = n end
                    end
                    hl.monitor(spec)
                end
            end
        end
    end
    f:close()
end

return M
