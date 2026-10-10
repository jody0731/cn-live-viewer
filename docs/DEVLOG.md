# Development log

What was tried, measured and decided, oldest first. Development machine: Kubuntu (Linux 7.0), mpv 0.41,
an RTX 3080, a 4K 160 Hz monitor and a 1440p 240 Hz monitor.

## 2026-10-10

### Why

Huya's web player shows ads. The goal: watch live rooms in a local player, ad-free, at the best quality the room
offers, without giving up the chat.

### A direct link in a desktop player loops

A Huya stream link opened in a desktop player (Haruna) played a few seconds and then repeated them. Most likely
Huya's servers cut the direct link early and the player restarted it. Streamlink fixed this: it knows Huya, keeps
the connection alive and reconnects, then hands the video to a player.

### mpv, not VLC

Streamlink's default player is VLC, which wasn't installed. mpv was chosen instead: it starts faster, has lower
delay, decodes on the GPU, and is what Streamlink recommends. A 20 s test held a steady stream with no early cut-off.

### Quality: Huya's `ratio` parameter

Streamlink lists Huya streams up to about 8 Mbps, but the web player also offers 20 Mbps. Huya picks the bitrate
from a `ratio=<kbps>` parameter in the stream address. Asking for `ratio=20000` gave 1080p60 at 20 Mbps, so it is
the default. That is about 9 GB per hour of watching. mpv's `high-quality` profile (sharper upscaling, debanding)
and GPU decoding (`hwdec=auto-safe`) were added at the same time.

### Chat in the terminal

Huya's chat runs over its own websocket (`wss://cdnws.api.huya.com`) in Tencent's TARS encoding. The client
registers for the room's `live:` and `chat:` groups and decodes `MessageNotice` pushes (uri 1400). It prints
text chat only, not gifts or entry notices, with one colour per viewer. See [PROTOCOLS.md](PROTOCOLS.md).

### Chat over the video

An mpv Lua script draws messages right to left in lanes across the top half of the picture. It uses an ASS OSD
overlay, and C toggles it. The chat client feeds it through mpv's JSON IPC socket. When every lane is busy, new
messages are skipped rather than drawn over each other.

The first run crashed with an SSL handshake timeout. The client was fetching the room page only to learn the
streamer's id, so now:
- the id is taken from the stream address, which carries it;
- page fetches retry;
- the websocket ignores the system proxy.

### Smoothness, round 1

Two separate problems:
- **Text stepping:** the overlay redrew 30 times a second.
- **Video judder:** 60 fps video on 160/240 Hz displays, with no sync between the two.

Fixes:
- redraw the overlay at the display's refresh rate, placing text by the clock;
- `video-sync=display-resample`, `interpolation` and `tscale=oversample` in mpv;
- smaller text: font 46 → 32 and 11 → 14 lanes over the same area.

### Douyin

The stream comes from `/webcast/room/web/enter`, using only the visitor cookie (`ttwid`) that the room page sets.
Its `stream_data` lists `origin/hd/sd/ld/md`. `origin` is the streamer's own upload; tested at 1080p60, about 5 Mbps.

Chat: Douyin's websocket feed needs a request signature, but the polling endpoint `/webcast/im/fetch` does not.
It returns protobuf with a cursor and is polled at the interval the server asks for.

### Player behaviour

Click-to-pause is removed; Space pauses. Volume and window size are left to the user's own mpv.conf. The package
ships no personal settings.

### One controller and a room picker

One controller process owns a single mpv window (`--idle`, IPC socket), looks up stream addresses itself, and
runs the chat. mpv fetches the stream directly, and that held steady on both sites.

R opens a room list inside mpv (`mp.input.select`): Enter switches the video and chat in 1–3 s in the same window,
and the first entry saves the current room.

Memory besides mpv: about 70 MB, against about 110 MB for the earlier Streamlink + chat-client pair.

### Packaging as cn-live-viewer

- **Layout:** the scripts became one Python package (src layout).
- **Dependencies:** Streamlink as a library, only for Huya's stream address; `websockets` for Huya's chat; the
  standard library for everything else.
- **mpv scripts:** shipped inside the package and loaded with `--script=` into cn-live-viewer's own mpv only.
  Nothing is installed into the user's mpv folder. Message names carry a `cnlv-` prefix.
- **Platforms:** Linux first, macOS should work as is. Windows needs a named pipe instead of a Unix socket for
  mpv's IPC, so it comes later.

### Stutter under busy chat (round 2)

The video stuttered now and then while the overlay was on: a 4K window at 160 Hz, with interpolation and the
`high-quality` profile.

The measures below are mpv's `vo-delayed-frame-count` (frames shown late) and `frame-drop-count`. The demuxer cache
stayed near 6 s in every run, which rules out the network.

| Run | Late | Dropped | mpv CPU |
|---|---|---|---|
| Real chat, overlay off, 30 s | 7 | 5 | 12% |
| Real chat, overlay on, 30 s | 145 | 808 | 25% |
| Overlay on, interpolation off | 0 | — | — |

Synthetic chat with the same message repeated, 15 s per step:

| Messages/s | 0 | 2 | 5 | 10 | 20 |
|---|---|---|---|---|---|
| Late | 2 | 4 | 6 | 5 | 13 |
| Dropped | 0 | 0 | 1 | 0 | 2 |
| mpv CPU | 27% | 36% | 43% | 54% | 49% |

Repeated text did not reproduce the problem. Varied text did: random Chinese characters plus emoji, 10 messages/s,
20 s gave **135 late, 75 dropped, 188% CPU**.

**Cause:** new glyphs.
- libass draws the overlay inside mpv's video output thread.
- It rasterizes every glyph, outline included, separately for each sub-pixel offset it lands on.
- Drawn 160 times a second at fractional positions, each message's characters were rasterized again and again, and
  frames waited for it.
- Repeated text only hit the glyph cache, which is why it looked fine.

**Fix**, in `danmaku.lua`:
- The overlay works in real screen pixels, and positions are rounded to whole pixels.
- It redraws at most 80 times a second, at an even fraction of the display rate: every 2nd refresh at 160 Hz.
- At most 60 messages on screen (was 90).
- An explicit Simplified Chinese font: Noto Sans CJK SC on Linux, PingFang SC on macOS, Microsoft YaHei on Windows.
  This also stops Han characters from falling back to Japanese glyph forms.
- All three limits can be changed through `--script-opts`.

**After**, with the same varied load: **8 late, 0 dropped**. CPU stays high (171%) under a 10 messages/s flood of
never-seen characters, but frames are no longer late. Real rooms are usually slower than that.

The window now opens maximized by default (`--window-maximized=yes`).

### Packaging checks

**Clean install.** `install.sh` was run into an empty home directory, as on a new machine:
- no pipx, so it took the virtual-environment path;
- no personal mpv configuration;
- Python 3.14, which resolved Streamlink 8.6.2 and websockets 17.2.

Results:
- The mpv scripts shipped inside the installed package.
- All 26 unit tests passed against the installed copy.
- `rooms` created the example room list.
- `url` and `chat` worked for both Huya and Douyin.

**Playback.** A Huya room at 2 Mbps (1280×720, 30 fps), for about 16 s:
- GPU decoding (Vulkan), `display-resample` and interpolation were active;
- the `--script-opts` from `--mpv-args` reached the overlay, and the chat used Noto Sans CJK SC;
- the window opened maximized;
- quitting mpv ended the program.

**Found and fixed:**
- A Huya link ending in `/?...` gave an empty room number.
- Piping `chat` into a command that stops reading, such as `head`, printed a traceback.
- `--mpv-args` was split on spaces, which broke values like a font name. It now follows shell quoting.
- The room list uses `mp.input.select`, which needs mpv 0.39. Older mpv now shows a message on R, where it used to
  fail loading the script. Video and chat work either way.

**Where it runs:**

| Platform | Status |
|---|---|
| Linux | Tested on Kubuntu: x86_64, Wayland (KWin), NVIDIA, mpv 0.41 |
| macOS | CI installs it and runs the unit tests on Python 3.10 and 3.14. Never run on a real Mac. |
| Windows | Not supported yet: mpv's IPC there is a named pipe, not a Unix socket |

Older long-term-support releases ship an older mpv, Ubuntu 24.04 for example has 0.37. There, everything works except
the room list.

### Blurry chat (round 3)

After the round 2 fix, moving chat text looked blurry on the 160 Hz monitor. The overlay was sharp: it drew at
the window's real pixels (3839×2113). The cause was the 80 redraws a second:
- each position stayed on screen for two refreshes, so the text jumped about 5.6 px at a time instead of 2.8 px;
- an eye following the text sees that as a doubled, soft edge.

The overlay now moves text on every refresh again, keeping the whole-pixel positions. The default `max_fps` is now
240. Same varied load as round 2, 10 messages/s for 20 s:

| Redraws | Late | Dropped | mpv CPU |
|---|---|---|---|
| 80/s (round 2) | 8 | 0 | 171% |
| every refresh, 160/s | 6 | 0 | 88% |

So the whole-pixel positions were what fixed the stutter, and the lower redraw rate wasn't needed.

In both runs the player's regular overlay was also drawing real chat. In the round 2 run that overlay was still the
old version, which explains most of the CPU difference.

## 2026-10-11

### Managing rooms in the player

The room list (R) can now add, rename and remove rooms as well as save the current one.
- **Menu:** these are entries after the rooms in the same menu. Adding and renaming open mpv's text prompt
  (`mp.input.get`).
- **Names:** rooms you add or save are named after the streamer, because Chinese names are awkward to type into
  mpv. Douyin's room data has the name. Huya's mobile room page has it even when the room is offline.
- **Lookups:** adding a room looks it up first, so an unknown room is refused.
- **Room file:** renaming and removing rewrite only that room's line, so comments and order stay.

**One snag:** opening a second prompt from inside the first prompt's Enter handler silently failed. mp.input sends
the first prompt's "closed" event after Enter, and that event removed the new prompt's callbacks. Follow-up prompts
now open 0.1 s later.

**Test:** an end-to-end run in an empty home directory, driving the menu with simulated key presses. Save, remove,
add by link (named after the streamer automatically), adding a duplicate (refused), rename and switch rooms all changed the
room file and the player as expected.

### Room list on Tab

The room list moved from R to Tab. mpv's default key bindings don't use Tab.

### Default room, clearer search box

The text field at the top of the room list only filters the list, but its label "Room:" read like a place to enter
a room. Every picker's field now says "Search", after a question saying what the list is for: "Search rooms:",
"Remove which room?   Search:".

The room list can now set the default room, the one played on start. This moves the room's line to the top of
the room file, and the list marks it.

A custom menu without the search field was tried and dropped: the field is useful for finding a room.

Not fixed: mpv sizes this menu from the item with the most bytes, not the widest one, and measures it slightly
short. The widest row can lose its last character, often the last digit of a Douyin room number.

### Mouse controls

Everything was keyboard-only, so mouse controls were added.

**Control bar.** mpv's own control bar can't hide single buttons, and most of them do nothing for a live stream:
subtitles, audio tracks, playlist, chapters, seeking. cn-live-viewer now starts mpv with `--osc=no`, and `bar.lua`
draws a slim bar instead:
- play/pause;
- the room name, which opens the room list when clicked;
- the chat overlay, volume (click to mute, scroll to change) and fullscreen.

The bar shows on mouse movement, hides after 1.5 s, and has tooltips. It uses mpv's built-in icon font, so the
icons match mpv's own. It takes clicks only inside its own area (an mpv mouse area), so clicks elsewhere still go to
mpv.

**Right-click menu.** It has Rooms (click to switch), Chat overlay with a tick when on, Fullscreen and Quit. It is
mpv's own menu, filled through the `menu-data` property:
- On Linux, mpv draws it with its `context_menu` script, which opens on a script message.
- The `context-menu` command only opens the system menu on Windows and macOS.

Right-click is bound only in cn-live-viewer's window, so it overrides `MBTN_RIGHT ignore` (or pause) there and
nowhere else.

**Test:** offline, on a test pattern with simulated mouse moves and clicks, every button did its job and the
right-click menu showed the rooms and states. Then a short run on a live room in a 4K window confirmed the bar's
scaling, the Chinese room name and the room entries in the menu.

### Seek strip, LIVE badge, mpv's menu

The control bar gained a seek strip.
- **Range:** a live stream has no fixed length, so the strip spans mpv's buffer (the newest seekable range of
  `demuxer-cache-state`), and its right end is the newest video received.
- **Seeking:** clicking or dragging seeks within the buffer. mpv reports the stream as not seekable but still seeks
  inside its cache. Before the change, a 10 s jump back worked at the default settings.
- **Rewind buffer:** mpv's default back buffer (50 MiB) holds only about 20 s at 20 Mbps. cn-live-viewer now sets
  `--demuxer-max-back-bytes=512MiB`, about 3.5 minutes at 20 Mbps.

The LIVE badge shows how far playback is behind the newest video:
- Within 10 s counts as live. mpv normally plays about 5–6 s behind what it has received.
- Otherwise it shows e.g. −0:42, and clicking it jumps to 4 s behind the newest video.

A ☰ button opens mpv's own menu (`select/menu`): key bindings, stream info, statistics, help.

The bar now hides 0.5 s after the mouse stops.

**Test:** on a live room with a 30 s buffer, clicking a quarter of the way along the strip put playback 22.5 s
behind live. Clicking the badge brought it back to 7 s.

**Simulated clicks:** they arrive as a single "press" event, not as separate down and up events. The bar handles
both, so dragging works with a real mouse and clicks work from scripts.

### Emoji in the chat made the video stutter

On Huya rooms, unreadable shapes showed up in the chat and the video stuttered.

**Overlay A/B:** while it happened, 46 and 107 frames dropped per 5 s with the overlay on, and 0 with it off.

**Matching drops to messages:** a second chat client listened to the same room while frame drops were counted
once a second for 40 s.
- Chinese text, "？？？" included: no drops.
- Each "🤡🤡🤡🤡🤡🤡🤡" message: 12–55 drops a second, until it had scrolled off about 9–12 s later.

**Cause:** the chat font (Noto Sans CJK SC) has no emoji, so they fall back to the colour emoji font. Its glyphs are
pictures, not outlines. libass draws them as unreadable shapes, and the cost repeats on every redraw while they are
on screen, not just the first time.

**Fix:** the overlay leaves emoji out (`overlay_text()` in player.py), and messages left empty are not shown. The
terminal still prints them in full. Other characters the font lacks fall back to outline fonts, which are drawn
once and reused, so they stay.

### A slimmer bar, with time and buffer readouts

After trying a few sizes, the control bar ended at three quarters of its first height, with a 75% see-through
background. A faint dark outline keeps the text readable over bright video.

The seek row now has mpv's own readouts: the playback time on the left and "Cache", the seconds buffered ahead, on
the right. The strip shows played (red) and received but not yet played (light grey).
