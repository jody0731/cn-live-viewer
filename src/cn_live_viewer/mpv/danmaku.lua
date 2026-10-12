-- Scrolling chat ("danmaku") over the video, fed by cn-live-viewer through mpv's IPC socket:
--   script-message cnlv-danmaku "<text>"
-- C toggles it on/off. Idle (no drawing) when no messages arrive, so it costs nothing for other videos.
-- Loaded by cn-live-viewer for its own mpv sessions only (--script=...).
--
-- Cost: libass draws the overlay inside mpv's video thread, and it rasterizes each glyph (with its outline) again
-- for every sub-pixel offset it lands on. Real chat brings new characters all the time, so text at fractional
-- positions made video frames late. Hence positions on whole screen pixels: each glyph is drawn once, then reused.
-- Text moves on every display refresh, up to max_fps in the Video Decoder's High quality mode and efficient_fps in
-- Efficient: each move redraws the whole picture, and fewer moves make moving text look doubled and blurry.
-- Options (--script-opts=cnlv-danmaku-font=...,cnlv-danmaku-max_on_screen=...):

local options = { font = "", max_on_screen = 100, max_fps = 120, efficient_fps = 60 }
require("mp.options").read_options(options, "cnlv-danmaku")

-- a font with Simplified Chinese glyphs, so Han characters do not fall back to a Japanese-style font
local PLATFORM_FONTS = { linux = "Noto Sans CJK SC", darwin = "PingFang SC", windows = "Microsoft YaHei" }
local FONT = options.font ~= "" and options.font or PLATFORM_FONTS[mp.get_property("platform", "")] or "sans-serif"

-- sizes for a 1920x1080 window; they scale to fit the window (by its width or height, whichever is smaller)
local BASE_H = 1080
local FONT_SIZE = 32
local LANES = 14                        -- rows at most, from the top of the picture (about its upper half)
local LANE_H = 38
local TOP = 14
local DURATION = 18                     -- seconds to cross the screen: slow, so each redraw moves text only a
                                        -- couple of pixels and it glides instead of jumping

local enabled = true
local items = {}                        -- {text, t0, lane, w, speed}; w and speed in 1080-high units
local lane_free_at = {}                 -- per lane: time the previous message's tail has entered the screen
local overlay = mp.create_osd_overlay("ass-events")
local W, H, k = 1920, 1080, 1           -- overlay size in screen pixels, and its scale against 1920x1080
local top, lanes = 0, LANES             -- the picture's top edge (below any black bar) and the rows that fit
local timer

local function resize(_, d)
    if d and d.w and d.h and d.w > 0 and d.h > 0 then
        W, H = d.w, d.h
        k = math.min(W / 1920, H / BASE_H)         -- a tall or narrow window doesn't make the text huge
        -- start at the picture, not the window: a 16:9 stream in a tall window has black bars above and below
        local pic_h = H - (d.mt or 0) - (d.mb or 0)
        if pic_h <= 0 then pic_h = H end
        top = d.mt or 0
        lanes = math.max(3, math.min(LANES, math.floor((pic_h / 2 - TOP * k) / (LANE_H * k))))
    end
    overlay.res_x, overlay.res_y = W, H
end
mp.observe_property("osd-dimensions", "native", resize)

local function interval()
    local d = mp.get_property_number("display-fps", 60) or 60
    if d <= 0 then d = 60 end
    local high = (mp.get_property_native("user-data/cnlv/decoder") or {}).mode == "high"
    local cap = high and options.max_fps or math.min(options.max_fps, options.efficient_fps)
    return math.ceil(d / cap) / d               -- every refresh up to the cap, else every 2nd, 3rd, ...
end

local function text_width(s)
    -- rough rendered width: CJK and emoji ~1 em, ASCII ~0.55 em
    local w = 0
    for ch in s:gmatch("[%z\1-\127\194-\244][\128-\191]*") do   -- one UTF-8 character at a time (no utf8 lib in mpv's Lua)
        w = w + ((#ch == 1 or (#ch == 2)) and 0.55 or 1.0)
    end
    return w * FONT_SIZE
end

local function escape(s)
    return (s:gsub("\\", "＼"):gsub("{", "｛"):gsub("}", "｝"):gsub("\n", " "))
end

local function render()
    if not enabled or #items == 0 then
        overlay:remove()
        if timer then timer:kill(); timer = nil end
        return
    end
    local now = mp.get_time()
    local style = string.format("\\an7\\fn%s\\fs%d\\bord%.1f\\shad0\\3c&H000000&\\1c&HFFFFFF&\\alpha&H10&",
                                FONT, math.floor(FONT_SIZE * k + 0.5), 1.6 * k)
    local out, keep = {}, {}
    for _, it in ipairs(items) do
        local x = math.floor(W - it.speed * k * (now - it.t0) + 0.5)
        if x + it.w * k > 0 then
            keep[#keep + 1] = it
            out[#out + 1] = string.format("{\\pos(%d,%d)%s}%s",
                                          x, math.floor(top + (TOP + (it.lane - 1) * LANE_H) * k + 0.5), style, it.text)
        end
    end
    items = keep
    overlay.data = table.concat(out, "\n")
    overlay:update()
end

local function add(text)
    if not enabled or not text or text == "" or #items >= options.max_on_screen then return end
    text = escape(text)
    local w = text_width(text)
    local speed = (W / k + w) / DURATION
    local now = mp.get_time()
    -- first lane whose previous message has fully entered the screen (plus a gap)
    local lane
    for i = 1, lanes do
        if (lane_free_at[i] or 0) <= now then lane = i; break end
    end
    if not lane then return end         -- screen full: drop rather than overlap
    lane_free_at[lane] = now + (w + 60) / speed
    items[#items + 1] = { text = text, t0 = now, lane = lane, w = w, speed = speed }
    if not timer then timer = mp.add_periodic_timer(interval(), render) end
end

-- the window moved to a display with another refresh rate, or the Video Decoder's mode changed: restart the timer
local function retime()
    if timer then timer:kill(); timer = mp.add_periodic_timer(interval(), render) end
end
mp.observe_property("display-fps", "number", retime)
mp.observe_property("user-data/cnlv/decoder", "native", retime)

mp.register_script_message("cnlv-danmaku", add)
mp.register_script_message("cnlv-danmaku-clear", function() items = {}; lane_free_at = {}; render() end)

-- the on/off state, for the control bar and the right-click menu
local function publish()
    mp.set_property_native("user-data/cnlv/chat", enabled)
end
publish()

mp.add_key_binding("c", "cnlv-toggle-danmaku", function()
    enabled = not enabled
    if not enabled then items = {}; lane_free_at = {}; render() end
    publish()
    mp.osd_message(enabled and "Chat overlay on" or "Chat overlay off", 1.2)
end)
