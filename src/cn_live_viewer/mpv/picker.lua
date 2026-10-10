-- Room picker for cn-live-viewer. Tab opens the saved rooms; Enter switches to one. The entries after the rooms
-- add a room by number or link, save the room you're watching, or rename or remove a saved room.
-- cn-live-viewer looks rooms up and keeps the list file. Loaded only for cn-live-viewer's mpv sessions.
local utils = require "mp.utils"
local has_input, input = pcall(require, "mp.input")   -- input.select needs mpv 0.39 or newer

local rooms, playing = {}, false

mp.register_script_message("cnlv-rooms", function(json)
    local data = utils.parse_json(json) or {}
    rooms, playing = data.rooms or {}, data.playing
end)

local function send(...)
    mp.commandv("script-message", ...)
end

-- Open a follow-up prompt only after the current one has closed: mp.input's late "closed" event would
-- otherwise drop the new prompt's callbacks.
local function later(fn)
    mp.add_timeout(0.1, fn)
end

local function label(r)
    return string.format("%s%s   ·   %s %s", r.current and "▶ " or "   ", r.name, r.platform, r.room)
end

-- choose a saved room, then fn(room)
local function choose(prompt, fn)
    if #rooms == 0 then
        mp.osd_message("No saved rooms", 2)
        return
    end
    local items = {}
    for i, r in ipairs(rooms) do items[i] = label(r) end
    later(function()
        input.select({ prompt = prompt, items = items, submit = function(i) fn(rooms[i]) end })
    end)
end

-- type one line, then fn(text)
local function ask(prompt, default, fn)
    later(function()
        input.get({
            prompt = prompt,
            default_text = default,
            submit = function(text)
                input.terminate()
                if text:match("%S") then fn(text) end
            end,
        })
    end)
end

local actions = {
    { "+  Add a room…", function()
        ask("Room number or link:", "", function(text) send("cnlv-add", text) end)
    end },
    { "+  Save the current room", function() send("cnlv-save") end, unsaved_only = true },
    { "   Rename a room…", function()
        choose("Rename:", function(r)
            ask("New name:", r.name, function(text) send("cnlv-rename", r.platform, r.room, text) end)
        end)
    end },
    { "-  Remove a room…", function()
        choose("Remove:", function(r) send("cnlv-remove", r.platform, r.room) end)
    end },
}

mp.add_key_binding("TAB", "cnlv-picker", function()
    if not has_input or not input.select then
        mp.osd_message("The room list needs mpv 0.39 or newer", 3)
        return
    end
    local items, handlers, default, saved = {}, {}, nil, false
    for _, r in ipairs(rooms) do
        items[#items + 1] = label(r)
        handlers[#handlers + 1] = function() send("cnlv-switch", r.platform, r.room) end
        if r.current then default, saved = #items, true end
    end
    for _, a in ipairs(actions) do
        if not (a.unsaved_only and (saved or not playing)) then
            items[#items + 1] = a[1]
            handlers[#handlers + 1] = a[2]
        end
    end
    input.select({
        prompt = "Room:",
        items = items,
        default_item = default or 1,
        submit = function(i) handlers[i]() end,
    })
end)

-- ask the controller for the list in case this script loaded after it was sent
send("cnlv-ready")
