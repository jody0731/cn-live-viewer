-- Room picker for cn-live-viewer. Tab opens the saved rooms; Enter switches to one. The entries after the rooms
-- add a room by number or link, save the room you're watching, rename or remove a saved room, or set the default
-- room (the first in the list, played on start). Typing filters the list.
-- It also fills mpv's right-click menu: the rooms, the quality, the chat overlay, fullscreen and quit.
-- cn-live-viewer looks rooms up and keeps the list file. Loaded only for cn-live-viewer's mpv sessions.
local has_input, input = pcall(require, "mp.input")   -- input.select needs mpv 0.39 or newer

local rooms, playing = {}, false

-- the quality submenu, from cn-live-viewer's user-data/cnlv/quality: Auto, then the room's levels, best first
local function quality_items()
    local qd = mp.get_property_native("user-data/cnlv/quality") or {}
    local items = { { title = qd.auto and qd.label ~= "" and ("Auto (now " .. qd.label .. ")") or "Auto",
                      cmd = "script-message cnlv-quality auto", state = qd.auto and { "checked" } or nil } }
    if qd.tiers and #qd.tiers > 0 then items[#items + 1] = { type = "separator" } end
    for _, t in ipairs(qd.tiers or {}) do
        items[#items + 1] = { title = t.label, cmd = "script-message cnlv-quality " .. t.id,
                              state = (not qd.auto and t.id == qd.current) and { "checked" } or nil }
    end
    return items
end

-- the right-click menu (mpv's menu-data); rebuilt when the rooms, the quality, the chat overlay or fullscreen change
local function update_menu()
    local room_items = {}
    for _, r in ipairs(rooms) do
        room_items[#room_items + 1] = { title = r.name, state = r.current and { "checked" } or nil,
                                        cmd = string.format("script-message cnlv-switch %s %s", r.platform, r.room) }
    end
    if #room_items > 0 then room_items[#room_items + 1] = { type = "separator" } end
    room_items[#room_items + 1] = { title = "Manage rooms…", cmd = "script-binding picker/cnlv-picker", shortcut = "Tab" }
    local chat = mp.get_property_native("user-data/cnlv/chat") ~= false
    mp.set_property_native("menu-data", {
        { type = "submenu", title = "Rooms", submenu = room_items },
        { type = "submenu", title = "Quality", submenu = quality_items() },
        { title = "Chat overlay", cmd = "script-binding danmaku/cnlv-toggle-danmaku", shortcut = "C",
          state = chat and { "checked" } or nil },
        { type = "separator" },
        { title = "Fullscreen", cmd = "cycle fullscreen", shortcut = "F",
          state = mp.get_property_bool("fullscreen") and { "checked" } or nil },
        { title = "Quit", cmd = "quit", shortcut = "Q" },
    })
end
mp.observe_property("user-data/cnlv/chat", "native", update_menu)
mp.observe_property("user-data/cnlv/quality", "native", update_menu)
mp.observe_property("fullscreen", "bool", update_menu)

-- right-click opens that menu in cn-live-viewer's window (it would otherwise pause, or do nothing)
mp.add_forced_key_binding("MBTN_RIGHT", "cnlv-context-menu", function()
    if mp.get_property_bool("load-context-menu") then
        mp.commandv("script-message-to", "context_menu", "open")   -- mpv's own drawn menu (Linux)
    else
        mp.commandv("context-menu")                                 -- the system's menu (Windows, macOS)
    end
end)

-- cn-live-viewer keeps the room list in this property ({playing, rooms}); it's there whenever this script loads
mp.observe_property("user-data/cnlv/rooms", "native", function(_, data)
    data = data or {}
    rooms, playing = data.rooms or {}, data.playing
    update_menu()
end)

local function send(...)
    mp.commandv("script-message", ...)
end

-- Open a follow-up prompt only after the current one has closed: mp.input's late "closed" event would
-- otherwise drop the new prompt's callbacks.
local function later(fn)
    mp.add_timeout(0.1, fn)
end

local function label(i, r)
    return string.format("%s%s   ·   %s %s%s", r.current and "▶ " or "   ", r.name, r.platform, r.room,
                         i == 1 and "   ·   default" or "")
end

-- choose a saved room, then fn(room)
local function choose(prompt, fn)
    if #rooms == 0 then
        mp.osd_message("No saved rooms", 2)
        return
    end
    local items = {}
    for i, r in ipairs(rooms) do items[i] = label(i, r) end
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
        choose("Rename which room?   Search:", function(r)
            ask("New name:", r.name, function(text) send("cnlv-rename", r.platform, r.room, text) end)
        end)
    end },
    { "★  Set the default room…", function()
        choose("Play which room on start?   Search:", function(r) send("cnlv-default", r.platform, r.room) end)
    end, min_rooms = 2 },
    { "-  Remove a room…", function()
        choose("Remove which room?   Search:", function(r) send("cnlv-remove", r.platform, r.room) end)
    end },
}

mp.add_key_binding("TAB", "cnlv-picker", function()
    if not has_input or not input.select then
        mp.osd_message("The room list needs mpv 0.39 or newer", 3)
        return
    end
    local items, handlers, default, saved = {}, {}, nil, false
    for i, r in ipairs(rooms) do
        items[#items + 1] = label(i, r)
        handlers[#handlers + 1] = function() send("cnlv-switch", r.platform, r.room) end
        if r.current then default, saved = #items, true end
    end
    for _, a in ipairs(actions) do
        if not (a.unsaved_only and (saved or not playing)) and #rooms >= (a.min_rooms or 0) then
            items[#items + 1] = a[1]
            handlers[#handlers + 1] = a[2]
        end
    end
    input.select({
        prompt = "Search rooms:",
        items = items,
        default_item = default or 1,
        submit = function(i) handlers[i]() end,
    })
end)

