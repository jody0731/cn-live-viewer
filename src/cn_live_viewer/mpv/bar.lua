-- A slim control bar for live streams, in place of mpv's own (cn-live-viewer starts mpv with --osc=no). Left:
-- play/pause and the room name, which opens the room list. Right: the chat overlay, volume and fullscreen.
-- It shows when the mouse moves over the window and hides when the mouse rests. Each button has a tooltip.
-- Loaded only for cn-live-viewer's mpv sessions.

local ICON_FONT = "mpv-osd-symbols"         -- mpv's built-in icon font, the one its own control bar uses
local ICONS = {
    play = "\238\132\129", pause = "\238\128\130", chat = "\238\132\135", mute = "\238\132\138",
    volume = { "\238\132\139", "\238\132\140", "\238\132\141", "\238\132\142" },
    fullscreen = "\238\132\136", exit_fullscreen = "\238\132\137",
}
local PLATFORM_FONTS = { linux = "Noto Sans CJK SC", darwin = "PingFang SC", windows = "Microsoft YaHei" }
local FONT = PLATFORM_FONTS[mp.get_property("platform", "")] or "sans-serif"

-- sizes for a 1080-pixel-high window; they scale with the window
local BAR_H, PAD, ICON, TEXT, HIDE_AFTER = 64, 22, 34, 28, 1.5

local W, H, k = 1920, 1080, 1
local visible, hovered = false, nil
local mouse = { x = -1, y = -1 }
local areas = {}                            -- {name, x0, x1} of each button, in screen pixels
local bar_top = H
local hide_timer
local overlay = mp.create_osd_overlay("ass-events")
overlay.z = 500                             -- above the chat overlay

local function esc(s)
    return (s:gsub("\\", "＼"):gsub("{", "｛"):gsub("}", "｝"):gsub("\n", " "))
end

local UTF8_CHAR = "[%z\1-\127\194-\244][\128-\191]*"      -- one UTF-8 character (no utf8 library in mpv's Lua)

local function px(n)
    return math.floor(n + 0.5)
end

local function width(s, fs)
    local w = 0
    for ch in s:gmatch(UTF8_CHAR) do
        w = w + (#ch == 1 and 0.56 or #ch == 2 and 0.6 or 1.0)
    end
    return w * fs
end

local function chat_on()
    return mp.get_property_native("user-data/cnlv/chat") ~= false
end

-- what each button shows and does
local function volume_icon()
    local v = mp.get_property_number("volume", 100)
    if mp.get_property_bool("mute") then return ICONS.mute end
    return ICONS.volume[v <= 0 and 1 or v <= 33 and 2 or v <= 66 and 3 or 4]
end

local BUTTONS = {
    pause = {
        tip = function() return mp.get_property_bool("pause") and "Play (Space)" or "Pause (Space)" end,
        click = function() mp.commandv("cycle", "pause") end,
    },
    title = {
        tip = function() return "Switch room (Tab)" end,
        click = function() mp.commandv("script-binding", "picker/cnlv-picker") end,
    },
    chat = {
        tip = function() return chat_on() and "Chat overlay is on: click to hide (C)" or "Chat overlay is off: click to show (C)" end,
        click = function() mp.commandv("script-binding", "danmaku/cnlv-toggle-danmaku") end,
    },
    volume = {
        tip = function()
            return mp.get_property_bool("mute") and "Muted: click to unmute, scroll to change"
                   or "Click to mute, scroll to change"
        end,
        click = function() mp.commandv("cycle", "mute") end,
    },
    fullscreen = {
        tip = function() return mp.get_property_bool("fullscreen") and "Exit fullscreen (F)" or "Fullscreen (F)" end,
        click = function() mp.commandv("cycle", "fullscreen") end,
    },
}

local function render()
    if not visible then
        overlay:remove()
        mp.disable_key_bindings("cnlv-bar")
        return
    end
    local h = math.floor(BAR_H * k)
    local y0, cy = H - h, H - h / 2
    local icon_fs, text_fs, pad = math.floor(ICON * k), math.floor(TEXT * k), PAD * k
    local out = {}
    areas = {}
    bar_top = y0

    local function colour(name, dim)
        if dim then return hovered == name and "BBBBBB" or "888888" end
        return hovered == name and "FFFFFF" or "DDDDDD"
    end
    -- one button: an icon and/or a label, anchored left (an4) or right (an6) at x; returns its width
    local function button(name, x, align, icon, label, dim)
        local c = colour(name, dim)
        local iw = icon and icon_fs * 1.05 or 0
        local lw = label and width(label, text_fs) or 0
        local gap = (icon and label) and 8 * k or 0
        local w = iw + gap + lw
        local left = align == "left" and x or x - w
        if icon then
            out[#out + 1] = string.format("{\\an4\\pos(%d,%d)\\fn%s\\fs%d\\bord0\\shad0\\1c&H%s&}%s",
                                          px(left), px(cy), ICON_FONT, icon_fs, c, icon)
        end
        if label then
            out[#out + 1] = string.format("{\\an4\\pos(%d,%d)\\fn%s\\fs%d\\bord0\\shad0\\1c&H%s&}%s",
                                          px(left + iw + gap), px(cy), FONT, text_fs, c, esc(label))
        end
        areas[#areas + 1] = { name, left - pad / 2, left + w + pad / 2 }
        return w
    end

    -- the bar: ASS colours are &HBBGGRR&, alpha 00 = opaque
    out[#out + 1] = string.format("{\\an7\\pos(0,%d)\\bord0\\shad0\\1c&H000000&\\1a&H30&\\p1}m 0 0 l %d 0 %d %d 0 %d{\\p0}",
                                  y0, W, W, h, h)

    -- right side, from the edge inwards
    local x = W - pad
    local fs = mp.get_property_bool("fullscreen")
    x = x - button("fullscreen", x, "right", fs and ICONS.exit_fullscreen or ICONS.fullscreen) - 2 * pad
    local vol = string.format("%d", math.floor(mp.get_property_number("volume", 100) + 0.5))
    x = x - button("volume", x, "right", volume_icon(), vol, mp.get_property_bool("mute")) - 2 * pad
    x = x - button("chat", x, "right", ICONS.chat, "Chat", not chat_on()) - 2 * pad
    local right_edge = x

    -- left side: play/pause, then the room name, shortened to fit
    x = pad
    x = x + button("pause", x, "left", mp.get_property_bool("pause") and ICONS.play or ICONS.pause) + 1.5 * pad
    local name, room_w = mp.get_property("media-title", ""), right_edge - x - 2 * pad
    local title = name .. "  ▾"
    if width(title, text_fs) > room_w then
        local chars = {}
        for ch in name:gmatch(UTF8_CHAR) do chars[#chars + 1] = ch end
        repeat
            table.remove(chars)
            title = table.concat(chars) .. "…  ▾"
        until #chars <= 1 or width(title, text_fs) <= room_w
    end
    button("title", x, "left", nil, title)

    -- tooltip above the hovered button
    if hovered and BUTTONS[hovered] then
        for _, a in ipairs(areas) do
            if a[1] == hovered then
                local tip = BUTTONS[hovered].tip()
                local tfs = math.floor(TEXT * 0.8 * k)
                local tw = width(tip, tfs) * 0.92 + 24 * k
                local tx = math.max(8 * k, math.min((a[2] + a[3]) / 2 - tw / 2, W - tw - 8 * k))
                local ty = y0 - 12 * k - tfs * 1.6
                local th = px(tfs * 1.6)
                out[#out + 1] = string.format("{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H000000&\\1a&H30&\\p1}m 0 0 l %d 0 %d %d 0 %d{\\p0}",
                                              px(tx), px(ty), px(tw), px(tw), th, th)
                out[#out + 1] = string.format("{\\an4\\pos(%d,%d)\\fn%s\\fs%d\\bord0\\shad0\\1c&HFFFFFF&}%s",
                                              px(tx + 12 * k), px(ty + th / 2), FONT, tfs, esc(tip))
            end
        end
    end

    overlay.res_x, overlay.res_y = W, H
    overlay.data = table.concat(out, "\n")
    overlay:update()
    -- take mouse clicks and the wheel over the bar only; elsewhere mpv's own bindings apply
    mp.set_mouse_area(0, y0, W, H, "cnlv-bar")
    mp.enable_key_bindings("cnlv-bar")
end

local function under_mouse()
    if not visible or mouse.y < bar_top then return nil end
    for _, a in ipairs(areas) do
        if mouse.x >= a[2] and mouse.x <= a[3] then return a[1] end
    end
    return nil
end

local function hide_later(seconds)
    if hide_timer then hide_timer:kill() end
    hide_timer = mp.add_timeout(seconds, function()
        if visible and mouse.y >= bar_top and mouse.x >= 0 then
            hide_later(HIDE_AFTER)                       -- the mouse rests on the bar: keep it
            return
        end
        visible, hovered = false, nil
        render()
    end)
end

mp.set_key_bindings({
    { "MBTN_LEFT", function()
        local name = under_mouse()
        if name then BUTTONS[name].click() end
    end },
    { "MBTN_LEFT_DBL", "ignore" },                       -- a quick second click shouldn't toggle fullscreen
    { "WHEEL_UP", function() mp.commandv("add", "volume", 5) end },
    { "WHEEL_DOWN", function() mp.commandv("add", "volume", -5) end },
}, "cnlv-bar", "force")

mp.observe_property("mouse-pos", "native", function(_, m)
    if not m then return end
    if not m.hover then
        mouse.x, mouse.y = -1, -1
        if visible then hide_later(0.3) end
        return
    end
    local moved = m.x ~= mouse.x or m.y ~= mouse.y
    mouse.x, mouse.y = m.x, m.y
    if moved then
        local was = visible
        visible = true
        hide_later(HIDE_AFTER)
        local h = under_mouse()
        if not was or h ~= hovered then
            hovered = h
            render()
        end
    end
end)

mp.observe_property("osd-dimensions", "native", function(_, d)
    if d and d.w and d.h and d.w > 0 and d.h > 0 then
        W, H = d.w, d.h
        k = math.max(0.6, H / 1080)
    end
    render()
end)

for _, p in ipairs({ "pause", "mute", "volume", "fullscreen", "media-title", "user-data/cnlv/chat" }) do
    mp.observe_property(p, "native", function() if visible then render() end end)
end
