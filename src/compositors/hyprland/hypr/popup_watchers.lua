-- Permanent non-consuming outside-click dispatcher for native popup apps.
local bind = hl.bind("mouse:272", hl.dsp.exec_cmd("popup-click-check"), {
    non_consuming = true,
    description = "_popup_click_check",
})
if bind and type(bind.set_enabled) == "function" then
    bind:set_enabled(true)
end
