-- Room picker for cn-live-viewer: R opens the saved rooms; Enter switches.
-- The first entry saves the room you're watching. Loaded only for cn-live-viewer's mpv sessions.
local utils = require "mp.utils"
local has_input, input = pcall(require, "mp.input")   -- input.select needs mpv 0.39 or newer

local rooms = {}

mp.register_script_message("cnlv-rooms", function(json)
    rooms = utils.parse_json(json) or {}
end)

mp.add_key_binding("r", "cnlv-picker", function()
    if not has_input or not input.select then
        mp.osd_message("The room list needs mpv 0.39 or newer", 3)
        return
    end
    if #rooms == 0 then
        mp.osd_message("No room list (start it with cn-live-viewer)", 2)
        return
    end
    local items, default = { "+  Save the current room to the list" }, 2
    for i, r in ipairs(rooms) do
        items[#items + 1] = string.format("%s%s   ·   %s %s", r.current and "▶ " or "   ", r.name, r.platform, r.room)
        if r.current then default = i + 1 end
    end
    input.select({
        prompt = "Room:",
        items = items,
        default_item = default,
        submit = function(i)
            if i == 1 then
                mp.commandv("script-message", "cnlv-save")
            else
                mp.commandv("script-message", "cnlv-switch", tostring(i - 1))
            end
        end,
    })
end)

-- ask the controller for the list in case this script loaded after it was sent
mp.commandv("script-message", "cnlv-ready")
