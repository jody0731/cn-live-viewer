-- A slim control bar for live streams, in place of mpv's own (cn-live-viewer starts mpv with --osc=no).
-- Top: a seek strip over what mpv has buffered; click or drag to go back, the right end is live.
-- Bottom row, left: mpv's menu, play/pause, the LIVE badge (how far behind live; click to catch up) and the room
-- name, which opens the room list. Right: the chat overlay, volume and fullscreen.
-- It shows when the mouse moves over the window and hides when the mouse rests. Each control has a tooltip.
-- Loaded only for cn-live-viewer's mpv sessions.

local ICON_FONT = "mpv-osd-symbols"         -- mpv's built-in icon font, the one its own control bar uses
local ICONS = {
    menu = "\238\132\130", play = "\238\132\129", pause = "\238\128\130", chat = "\238\132\135",
    mute = "\238\132\138", volume = { "\238\132\139", "\238\132\140", "\238\132\141", "\238\132\142" },
    fullscreen = "\238\132\136", exit_fullscreen = "\238\132\137",
}
local PLATFORM_FONTS = { linux = "Noto Sans CJK SC", darwin = "PingFang SC", windows = "Microsoft YaHei" }
local FONT = PLATFORM_FONTS[mp.get_property("platform", "")] or "sans-serif"

-- sizes for a 1080-pixel-high window; they scale with the window
local SEEK_H, ROW_H, PAD, ICON, TEXT = 26, 60, 22, 34, 28
local HIDE_AFTER = 0.5                      -- seconds without mouse movement
local LIVE_SLACK = 10                       -- seconds behind the newest video that still count as live
local LIVE_TARGET = 4                       -- "go live" lands this far behind the newest video, to keep a buffer

local W, H, k = 1920, 1080, 1
local visible, hovered, dragging = false, nil, false
local mouse = { x = -1, y = -1 }
local areas = {}                            -- {name, x0, x1} of each button in the bottom row, in screen pixels
local bar_top, row_top, strip_x0, strip_x1 = H, H, 0, W
local hide_timer, refresh_timer, last_seek = nil, nil, 0
local overlay = mp.create_osd_overlay("ass-events")
overlay.z = 500                             -- above the chat overlay

local UTF8_CHAR = "[%z\1-\127\194-\244][\128-\191]*"      -- one UTF-8 character (no utf8 library in mpv's Lua)

local function esc(s)
    return (s:gsub("\\", "＼"):gsub("{", "｛"):gsub("}", "｝"):gsub("\n", " "))
end

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

local function clock(sec)
    sec = math.floor(sec + 0.5)
    if sec >= 3600 then
        return string.format("%d:%02d:%02d", math.floor(sec / 3600), math.floor(sec / 60) % 60, sec % 60)
    end
    return string.format("%d:%02d", math.floor(sec / 60), sec % 60)
end

local function chat_on()
    return mp.get_property_native("user-data/cnlv/chat") ~= false
end

-- the buffered stretch that can be sought: (start, end) in stream time, or nil while there is none
local function seek_range()
    local cache = mp.get_property_native("demuxer-cache-state")
    local best
    for _, r in ipairs(cache and cache["seekable-ranges"] or {}) do
        if not best or r["end"] > best["end"] then best = r end
    end
    if best and best["end"] - best.start > 1 then return best.start, best["end"] end
end

-- seconds between what's playing and the newest received video, or nil
local function behind_live()
    local _, newest = seek_range()
    local t = mp.get_property_number("time-pos")
    if newest and t then return math.max(0, newest - t) end
end

local function go_live()
    local _, newest = seek_range()
    if newest then mp.commandv("seek", tostring(newest - LIVE_TARGET), "absolute+keyframes") end
end

local function seek_to_mouse()
    local first, newest = seek_range()
    if not first then return end
    local f = math.max(0, math.min(1, (mouse.x - strip_x0) / (strip_x1 - strip_x0)))
    local target = math.min(first + f * (newest - first), newest - 1)
    mp.commandv("seek", tostring(target), "absolute+keyframes")
    last_seek = mp.get_time()
end

local function volume_icon()
    local v = mp.get_property_number("volume", 100)
    if mp.get_property_bool("mute") then return ICONS.mute end
    return ICONS.volume[v <= 0 and 1 or v <= 33 and 2 or v <= 66 and 3 or 4]
end

-- each control's tooltip and click
local CONTROLS = {
    menu = {
        tip = function() return "mpv menu: key bindings, stream info, statistics, help" end,
        click = function() mp.commandv("script-binding", "select/menu") end,
    },
    pause = {
        tip = function() return mp.get_property_bool("pause") and "Play (Space)" or "Pause (Space)" end,
        click = function() mp.commandv("cycle", "pause") end,
    },
    live = {
        tip = function()
            local b = behind_live()
            if not b or b <= LIVE_SLACK then return "Watching live" end
            return clock(b) .. " behind live: click to catch up"
        end,
        click = go_live,
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
    seek = {
        tip = function()
            local first, newest = seek_range()
            if not first then return "Seeking works once the stream has buffered" end
            local f = math.max(0, math.min(1, (mouse.x - strip_x0) / (strip_x1 - strip_x0)))
            local b = (1 - f) * (newest - first)
            return b <= LIVE_SLACK and "Live" or clock(b) .. " behind live"
        end,
    },
}

-- ASS drawing helpers; colours are &HBBGGRR&, alpha 00 = opaque
local function rect(x, y, w, h, colour, alpha)
    return string.format("{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\1a&H%s&\\p1}m 0 0 l %d 0 %d %d 0 %d{\\p0}",
                         px(x), px(y), colour, alpha or "00", px(w), px(w), px(h), px(h))
end

local function circle(cx, cy, r, colour)
    local d, c = px(2 * r), px(r * 0.5523)
    local m = px(r)
    return string.format("{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\p1}m 0 %d b 0 %d %d 0 %d 0 b %d 0 %d %d %d %d " ..
                         "b %d %d %d %d %d %d b %d %d 0 %d 0 %d{\\p0}",
                         px(cx - r), px(cy - r), colour,
                         m, m - c, m - c, m, m + c, d, m - c, d, m, d, m + c, m + c, d, m, d, m - c, d, m + c, m)
end

local function text(x, y, s, font, fs, colour)
    return string.format("{\\an4\\pos(%d,%d)\\fn%s\\fs%d\\bord0\\shad0\\1c&H%s&}%s", px(x), px(y), font, fs, colour, s)
end

local function render()
    if not visible then
        overlay:remove()
        mp.disable_key_bindings("cnlv-bar")
        return
    end
    local seek_h, row_h = px(SEEK_H * k), px(ROW_H * k)
    local y0 = H - seek_h - row_h
    local cy = H - row_h / 2
    local icon_fs, text_fs, pad = px(ICON * k), px(TEXT * k), PAD * k
    local out = {}
    areas = {}
    bar_top, row_top = y0, H - row_h

    local function colour(name, dim)
        if dim then return hovered == name and "BBBBBB" or "888888" end
        return hovered == name and "FFFFFF" or "DDDDDD"
    end
    -- one button: an icon and/or a label, anchored at x on the left or right; returns its width
    local function button(name, x, align, icon, label, dim)
        local c = colour(name, dim)
        local iw = icon and icon_fs * 1.05 or 0
        local lw = label and width(label, text_fs) or 0
        local gap = (icon and label) and 8 * k or 0
        local w = iw + gap + lw
        local left = align == "left" and x or x - w
        if icon then out[#out + 1] = text(left, cy, icon, ICON_FONT, icon_fs, c) end
        if label then out[#out + 1] = text(left + iw + gap, cy, esc(label), FONT, text_fs, c) end
        areas[#areas + 1] = { name, left - pad / 2, left + w + pad / 2 }
        return w
    end

    out[#out + 1] = rect(0, y0, W, H - y0, "000000", "30")

    -- seek strip: the buffered stretch, the part already played, and a handle at the playing position
    strip_x0, strip_x1 = pad, W - pad
    local sy = y0 + seek_h / 2 + 2 * k
    local strip_hover = hovered == "seek" or dragging
    local th = (strip_hover and 6 or 4) * k
    local first, newest = seek_range()
    local t = mp.get_property_number("time-pos")
    out[#out + 1] = rect(strip_x0, sy - th / 2, strip_x1 - strip_x0, th, "707070", "40")
    if first and t then
        local f = math.max(0, math.min(1, (t - first) / (newest - first)))
        local hx = strip_x0 + f * (strip_x1 - strip_x0)
        out[#out + 1] = rect(strip_x0, sy - th / 2, hx - strip_x0, th, "4848E8")
        out[#out + 1] = circle(hx, sy, (strip_hover and 9 or 7) * k, "FFFFFF")
    end

    -- right side, from the edge inwards
    local x = W - pad
    local fs = mp.get_property_bool("fullscreen")
    x = x - button("fullscreen", x, "right", fs and ICONS.exit_fullscreen or ICONS.fullscreen) - 2 * pad
    local vol = string.format("%d", px(mp.get_property_number("volume", 100)))
    x = x - button("volume", x, "right", volume_icon(), vol, mp.get_property_bool("mute")) - 2 * pad
    x = x - button("chat", x, "right", ICONS.chat, "Chat", not chat_on()) - 2 * pad
    local right_edge = x

    -- left side: menu, play/pause, LIVE badge, then the room name, shortened to fit
    x = pad
    x = x + button("menu", x, "left", ICONS.menu) + 1.5 * pad
    x = x + button("pause", x, "left", mp.get_property_bool("pause") and ICONS.play or ICONS.pause) + 1.5 * pad
    local behind = behind_live()
    local live = not behind or behind <= LIVE_SLACK
    local badge = live and "LIVE" or "−" .. clock(behind)
    local dot_r = 6 * k
    out[#out + 1] = circle(x + dot_r, cy, dot_r, live and "3C3CFF" or "888888")
    local bw = 2 * dot_r + 8 * k + width(badge, text_fs * 0.85)
    out[#out + 1] = text(x + 2 * dot_r + 8 * k, cy, badge, FONT, px(text_fs * 0.85), colour("live", not live))
    areas[#areas + 1] = { "live", x - pad / 2, x + bw + pad / 2 }
    x = x + bw + 2 * pad
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

    -- tooltip above the hovered control (above the mouse for the seek strip)
    if hovered and CONTROLS[hovered] then
        local cx
        if hovered == "seek" then
            cx = mouse.x
        else
            for _, a in ipairs(areas) do
                if a[1] == hovered then cx = (a[2] + a[3]) / 2 end
            end
        end
        if cx then
            local tip = CONTROLS[hovered].tip()
            local tfs = px(TEXT * 0.8 * k)
            local tw, tht = width(tip, tfs) * 0.85 + 24 * k, px(tfs * 1.6)
            local tx = math.max(8 * k, math.min(cx - tw / 2, W - tw - 8 * k))
            local ty = y0 - 10 * k - tht
            out[#out + 1] = rect(tx, ty, tw, tht, "000000", "30")
            out[#out + 1] = text(tx + 12 * k, ty + tht / 2, esc(tip), FONT, tfs, "FFFFFF")
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
    if mouse.y < row_top then return "seek" end
    for _, a in ipairs(areas) do
        if mouse.x >= a[2] and mouse.x <= a[3] then return a[1] end
    end
    return nil
end

local function set_visible(v)
    if v == visible then return end
    visible = v
    if not v then hovered, dragging = nil, false end
    -- while shown, refresh a few times a second: the playing position and the buffer keep moving
    if refresh_timer then refresh_timer:kill(); refresh_timer = nil end
    if v then refresh_timer = mp.add_periodic_timer(0.25, render) end
    render()
end

local function hide_later(seconds)
    if hide_timer then hide_timer:kill() end
    hide_timer = mp.add_timeout(seconds, function()
        if visible and (dragging or (mouse.y >= bar_top and mouse.x >= 0)) then
            hide_later(HIDE_AFTER)                       -- the mouse rests on the bar: keep it
            return
        end
        set_visible(false)
    end)
end

-- button down: press a control, or start dragging along the seek strip; button up ends the drag
local function press()
    local name = under_mouse()
    if name == "seek" then
        dragging = true
        seek_to_mouse()
    elseif name then
        CONTROLS[name].click()
    end
end

local function release()
    dragging = false
end

mp.set_key_bindings({
    -- a real mouse sends down and up; a click without separate events (e.g. from a script) comes as one press
    { "MBTN_LEFT", function() press(); release() end, press, release },
    { "MBTN_LEFT_DBL", "ignore" },                       -- a quick second click shouldn't toggle fullscreen
    { "WHEEL_UP", function() mp.commandv("add", "volume", 5) end },
    { "WHEEL_DOWN", function() mp.commandv("add", "volume", -5) end },
}, "cnlv-bar", "force")

mp.observe_property("mouse-pos", "native", function(_, m)
    if not m then return end
    if not m.hover then
        mouse.x, mouse.y, dragging = -1, -1, false
        if visible then hide_later(0.3) end
        return
    end
    local moved = m.x ~= mouse.x or m.y ~= mouse.y
    mouse.x, mouse.y = m.x, m.y
    if not moved then return end
    hide_later(HIDE_AFTER)
    if not visible then
        set_visible(true)
    end
    if dragging and mp.get_time() - last_seek > 0.1 then seek_to_mouse() end
    local h = under_mouse()
    if h ~= hovered or h == "seek" then              -- the seek tooltip follows the mouse
        hovered = h
        render()
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
