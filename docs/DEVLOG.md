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

### Adapting to other screens

A review of how cn-live-viewer behaves on screens unlike the development machine. Most of it already adapts:
- **Picture:** mpv renders at the window's own resolution. A 1080p stream on a 1080p screen is shown at its native
  size; the upscaler only runs when the window is bigger than the video, as on a 4K screen.
- **UI:** the chat overlay and the control bar draw in the window's real pixels, so they are sharp at any
  resolution and any HiDPI scale.
- **Refresh rate:** chat moves on every display refresh, up to 240 Hz, and follows the window to another monitor.
- **Fonts:** a Simplified Chinese font is picked per OS.
- **Decoding:** GPU decoding falls back to the CPU where the GPU can't decode.

Two things didn't adapt, both visible on a portrait (1440x2560) monitor:
- **Scale:** both scaled by window height alone, so a tall window made the bar and the chat text 2.3 times
  normal size. They now scale by width or height, whichever is smaller.
- **Chat position:** chat started at the window's top. With a 16:9 stream in a tall window, that is a black bar.
  It now starts at the picture's top edge (mpv's `osd-dimensions` margins). It uses as many rows as fit in the
  picture's upper half, at most 14.

### Empty room list after a failed start

When the room played on start was offline, the room list (Tab) was empty. The list only reached the menu script in
two ways, and both failed here:
- after a room started playing, which never happened;
- through a "ready" message the script sends when it loads. It sends that before cn-live-viewer has connected to
  mpv's socket, so nobody received it.

The controller now keeps the list in an mpv property (`user-data/cnlv/rooms`) instead, and sets it before trying the
first room. The script observes the property, so it sees the list whenever it loads. The error message also says
to press Tab for another room.

### App launcher

`cn-live-viewer desktop` writes `~/.local/share/applications/cn-live-viewer.desktop`. With it the program is in the
app menu and search, can be pinned, and starts without a terminal.
- **Icon:** mpv's (`Icon=mpv`).
- **Opening:** it opens the default room. A Huya or Douyin link dropped on it is opened instead (`%u`).
- **Install:** `install.sh` adds it on Linux.

So the running window groups under the launcher, not under mpv's own icon, cn-live-viewer gives mpv the window id
`cn-live-viewer` (`--x11-name`, `--wayland-app-id`). Older mpv refuses to start on an option it doesn't know, so
`--wayland-app-id` is only passed when `mpv --list-options` lists it.

With no terminal, the "no rooms saved" error would go nowhere. So when the launcher starts it (a hidden `--launcher`
flag) and no rooms are saved, the player opens anyway with "No rooms saved yet. Press Tab, then Add a room".

### macOS and Windows

What differed by platform, and what changed:
- **Talking to mpv:** mpv's JSON IPC is a Unix socket on Linux and macOS and a named pipe (`\\.\pipe\...`) on
  Windows. On Windows the controller connects with asyncio's `create_pipe_connection` and retries until mpv has
  opened the pipe.
- **Finding mpv:** an app started from the Finder or a Start menu shortcut gets a short PATH. So mpv is also looked
  for where Homebrew, Scoop and Chocolatey put it.
- **Window names:** the Linux window-name options (`--x11-name`, `--wayland-app-id`) are only passed on Linux.
- **Room list:** `%APPDATA%\cn-live-viewer` on Windows. macOS keeps `~/.config`, as mpv does there.
- **Console:** started without a console on Windows, `sys.stdout` is `None`, so output goes to `os.devnull`. A pipe
  that can't take Chinese text replaces the characters instead of crashing. Colour codes are turned on in the
  Windows console.
- **Launcher:**
  - macOS: `~/Applications/CN Live Viewer.app`, a small bundle whose starter runs `python -m cn_live_viewer`, with
    mpv's icon when an mpv.app is found;
  - Windows: a Start menu shortcut to `pythonw.exe` (no console window), with mpv.exe's icon.
- **Installer:** `install.ps1` for Windows. It installs from GitHub's zip, so git isn't needed.
- **Fonts:** already mapped: PingFang SC on macOS, Microsoft YaHei on Windows.

**Tests:** none of this can run on the Linux development machine, so CI does it.
- The unit tests now run on Windows too, and the launcher test checks each system's own launcher.
- A new smoke test (`tests/test_mpv_smoke.py`) starts the real mpv without a window over the real IPC (socket or
  pipe). It checks that the three scripts load without errors and react: the chat overlay's state, and the room
  list reaching the right-click menu. CI installs mpv with apt, Homebrew and Chocolatey to run it.
- Watching a real stream on macOS and Windows is still untried.

**Pre-push checks for 0.8.0:**
- **Unit tests:** all 32 pass, including the new mpv smoke test on Linux.
- **Tall window (720x1280):** chat starts at the picture's top edge and the bar is sized by the width.
- **Failed start:** with a bogus default room, the room list and the right-click menu showed the saved rooms. Choosing
  another room from there loaded it.
- **Launcher with no rooms saved:** the player opened, idle.
- **Playback:** a live Huya room played with 0 dropped frames.

The checks also turned up two problems, both fixed:
- **Raw error on screen:** a Huya room number with no room made Streamlink raise its own validation error, which
  appeared on screen as a 10-line dump. Streamlink errors now become "offline or not found".
- **Traceback on quit:** quitting mpv while a room was loading printed a traceback (a write to the closed
  connection). Commands to an mpv that has closed are now ignored.

### Choosing the quality, with Auto

The quality can now be chosen in the player, and Auto is the default. This was the parked "adaptive bitrate" idea.

**Levels:**
- **Huya:** the room's own bitrates, which Streamlink names `hs_8000k` and so on, plus the 20 Mbps top level, each
  as the source address with that `ratio`.
- **Douyin:** its named qualities, labelled from each quality's `sdk_params` (bitrate, resolution) when present.

**Auto** (`quality.Auto`, rules kept free of I/O so they are unit-tested):
- **Stall signal:** mpv's `paused-for-cache` means the buffer ran dry.
- **Step down:** when one stall lasts more than 4 s, or two stalls come within 60 s.
- **First 15 s:** stalls at the start of a level don't count, while the buffer fills.
- **Step up:** after 5 minutes with no stall, try one level up.
- **Back off:** if that try stalls within 2 minutes, step down again and don't try for 20 minutes.

**Switching levels:** only the video address changes (`loadfile`). The chat keeps running. A fixed choice is kept
as a bitrate cap, so it carries over sensibly between Huya's Mbps levels and Douyin's named ones.

**Menus:**
- The control bar has a quality button: "Auto · 20 Mbps", or the fixed level. It opens a list.
- The right-click menu has a Quality submenu.
- Both read `user-data/cnlv/quality`, which the controller keeps current.

### README screenshots

The README now shows the player and the right-click menu, taken from a Douyin room Jody was watching. A first set
was made from a demo instead, a generated picture with sample chat, to keep a streamer's face and footage out of
the public repo. Jody preferred real screenshots.

Taking them turned up two things:
- **Tooltips:** they were about 50% wider than their text. The bar estimated text widths from character counts,
  which runs wide for Latin text. Tooltips are now measured by libass in a hidden overlay (`compute_bounds`), as
  mpv's console does.
- **Audio-only level:** Douyin also lists "ao", an audio-only stream. It showed as "ao", and Auto could even step
  down to it. It is now labelled "Audio only" and stays in the menu as a manual choice. Auto's steps and bitrate
  caps only consider video levels.

### Start order, launcher by default, one-command install

**Start order.** cn-live-viewer remembers the last 10 rooms watched (`recent`, next to `rooms.conf`). Started
without a room, it tries, until one is live:
1. the default room;
2. the recent rooms, newest first;
3. the rest of the saved list in order.

`rooms.start_order` builds the list, at most 8 rooms. Each failure shows "✗ … is offline, trying …". A room given
on the command line is played alone, as before.

**Launcher by default.** The launcher was only added by the install scripts. Now cn-live-viewer adds it the first
time it plays, so pipx installs get it too. A `launcher` marker file next to `rooms.conf` records "added" or
"removed", so a launcher removed with `desktop remove` isn't added back.

**One-command install.** The install scripts also install what the system is missing, asking first (`--yes` /
`-Yes` to skip):
- **Linux:** checks for mpv, a Simplified Chinese font (`fc-list :lang=zh-cn`), Python 3.10+ and its venv module,
  and installs them with apt, dnf, pacman or zypper.
- **macOS:** mpv and Python with Homebrew.
- **Windows:** Python and mpv (`shinchiro.mpv`) with winget. The script reads PATH again afterwards, since winget's
  change only reaches new sessions.

Both scripts run on their own (`curl … | sh`, `irm … | iex`) and install from GitHub's zip, so git isn't needed.

### Live / offline markers

The room lists (Tab and right-click → Rooms) mark who is live: ● live, ○ offline, ▶ playing.

**Is it a lot of overhead?** Not if the checks aren't real-time. Each check is one request per room:
- **Huya:** the room-profile API (`mp.huya.com ... profileRoom`), 1.6–11 KB.
- **Douyin:** the same room-data request the player already uses, about 100 KB once it is asked for gzip. Unpacked
  it is about 750 KB, so all Douyin requests now ask for gzip. One visitor cookie serves all checks.

**When it checks:**
- every saved room, all at once, at start;
- every 5 minutes;
- when a room list opens, reusing results under 2 minutes old.

With 4 rooms that is a few MB an hour against about 9 GB an hour of video.

**Faster start:** the start order now tries live rooms first, then unknown ones, then rooms that looked offline,
still tried last in case a check was wrong.

**Limit:** mpv's menus can't change while open, so a refresh shows the next time a list is opened.

**Follow-up (Jody):**
- **Status position:** the status goes at the front, in words: "● Live · Gus", "○ Offline · …".
- **Dimming:** not possible. mpv's Tab list escapes every item, so there are no per-item colours. The right-click
  menu can only grey an item out by disabling it, and offline rooms should stay switchable.
- **Switching to an offline room:** cn-live-viewer goes there and waits for the stream:
  - the video stops and the room's chat runs;
  - the room is checked every 30 s, and plays once it is live;
  - a room that doesn't exist (`missing`) still fails, so the status checks return live, offline or missing.
- **On start:** with no room live, cn-live-viewer waits for the default room.
- **Added rooms:** a room you add is switched to straight away.

**A Lua trap, twice in one day:** a `local function` is only visible below its definition. A call from code above it
reaches a nil global, at runtime and only when that path runs. A unit test (`tests/test_lua_scripts.py`) now
scans the mpv scripts for use-before-define.

**Found in the pre-push run:** switching to the offline Huya room logged "chat stopped: Huya room 333003 not found".
The mobile room page, where the streamer's id came from, doesn't have it while the room is offline. That also
meant an offline Huya room couldn't be added at all. The room-profile API, already used for the live markers, has
the id and the name either way, so `huya.room_info` uses it now and the page scraping is gone.

### The bar scales with the window's height again

In 0.8.0 the control bar started scaling by the window's width or height, whichever was smaller, so a tall window
wouldn't make it huge. Jody preferred the earlier behaviour: the bar follows the window's height, like the rest of
mpv's on-screen controls. It's back to that. The chat overlay keeps fitting the picture.

The pre-push check of this change turned up an overlap. In a narrow window, scaled by height, the room name and the
quality button collided: the name was shortened to one character but never dropped. Now a name that can't fit at
all is left out (the Tab list still has it).

### First real Windows install

Jody ran `irm …/install.ps1 | iex` on a Windows PC:
- **Worked:** Python was found, cn-live-viewer installed, and the Start menu entry was added.
- **Failed:** mpv didn't install. winget failed with "Failed when searching source: winget" and 0x80073cfc ("The
  application cannot be started"), a broken winget source on that PC rather than anything in the script.

**Changes to install.ps1:**
- **Fallback:** if winget is missing or fails, it offers to download mpv's official Windows build from mpv's latest
  GitHub release: the x86_64 mingw zip, about 37 MB, or the ARM64 build on ARM. It goes into
  `%LOCALAPPDATA%\cn-live-viewer\mpv`, which needs no admin rights, and `find_mpv()` looks there.
- **winget hint:** a winget failure now names the likely fix: update App Installer from the Microsoft Store, or run
  `winget source reset --force` as admin.
- **Plain ending:** if mpv is still missing at the end, the installer says so, instead of a plain "Installed".
- **Download speed:** `$ProgressPreference = 'SilentlyContinue'`, because Windows PowerShell's progress bar slows
  `Invoke-WebRequest` a lot.

**New CI job (`install-windows`):** it runs `install.ps1 -Yes` on GitHub's Windows machine with winget skipped
(`CNLV_NO_WINGET`), so the download path runs. Then the installed copy must find that mpv by itself and pass the
mpv smoke test over the named pipe.

**The first CI run of it failed, usefully.** mpv's Windows release zip doesn't hold the program directly: it holds
another zip (`mpv-git-<date>-<commit>-x86_64.zip`). The installer unpacked only the outer one and then found no
`mpv.exe`. It now unpacks nested zips as well, and fails loudly if `mpv.exe` still isn't there. The zip's layout was
read from its table of contents: the last 150 KB, fetched with an HTTP range instead of the whole 37 MB.

### Efficient by default, and the installers redone (0.11.0)

**Resource use.** Jody's laptop, on battery, played poorly. The cause wasn't GPU decoding: decoding on the graphics
chip's video engine is the cheap part. It was everything drawn on top. Measured on this desktop (RTX 3080, 4K 160 Hz,
a 1080p60 15 Mbps H.264 test clip, maximized, synthetic chat at 4 messages a second, 20 s per mode, GPU board power
against the idle desktop's 87 W):

| Mode | mpv CPU (one core = 100%) | Extra GPU power | mpv memory |
|---|---|---|---|
| 0.10.3 (high-quality, display-resample, interpolation) | 36% | 13.7 W | 364 MB |
| High quality (the same, as a profile) | 35% | 11.1 W | 363 MB |
| Efficient, chat at every refresh (160/s) | 22% | 5.4 W | 351 MB |
| Efficient, chat at 60/s | 18-20% | 3.6-5.0 W | 355 MB |
| Efficient with `fast` (bilinear), chat at 60/s | 18% | 1.4 W | 361 MB |
| Efficient, no chat | 10% | 3.8 W | 350 MB |
| Efficient, CPU decoding | 62% | 3.2 W | 479 MB |
| High quality, CPU decoding | 76% | 10.9 W | 490 MB |

- **What costs what:** interpolation and display-resample redraw every display refresh, and ewa_lanczossharp is a
  heavy scaler. The chat overlay costs about 10% of a core. CPU decoding triples mpv's CPU use and adds 130 MB.
- **Bilinear or lanczos:** in a laptop-sized 1920x1020 window the two measured the same (0.6 and 0.9 W, noise).
  They differ only when upscaling to a big screen, where lanczos looks clearly better. Efficient keeps mpv's
  default lanczos.
- **Chat rate:** capped at 60/s in Efficient. Each move of the chat redraws the whole picture, and without
  interpolation nothing else redraws faster than the video.

**The picture modes** are two profiles in `mpv/cnlv.conf`, loaded with `--include` and chosen with `--profile` at
start or `apply-profile` while playing. A first try used `profile-restore=copy` to switch back. It worked, but
"back" meant whatever `mpv.conf` had, and Jody's `mpv.conf` sets the same high-quality options, so Efficient would
have looked identical there. Both profiles now set the options explicitly.

**"Python was not found" on a second Windows PC.** Windows ships `python.exe` in WindowsApps as a placeholder for
the Microsoft Store. Run, it prints "Python was not found; run without arguments to install from the Microsoft
Store" to stderr. Windows PowerShell 5.1 turns a native program's redirected stderr into an error record, and with
`$ErrorActionPreference = 'Stop'` that ended the installer at the very first check. CI didn't catch it because it
ran the installer in PowerShell 7 with Python already installed.
- **The check** runs with 'Continue' and asks Python for its own path, without double quotes in the code passed to
  it (Windows PowerShell passes embedded quotes to programs wrongly).
- **Where it looks:** the py launcher, `python`/`python3` on PATH, then `%LOCALAPPDATA%\Programs\Python\Python3*`
  and `%ProgramFiles%\Python3*`, where python.org's installer puts Python without adding it to PATH.
- **Installing:** winget (`Python.Python.3.14`, user scope), else python.org's installer for the latest 3.14,
  found through python.org's release list, installed quietly for the user with PrependPath.
- **CI:** the Windows install job now runs in Windows PowerShell 5.1 without setup-python, with a stand-in for the
  Store placeholder first on PATH, and `CNLV_NO_SYSTEM_PYTHON` making the installer ignore the Pythons the runner
  already has.


### Video Decoder, kept settings, steadier switching (0.12.0)

- **Auto stepped down for the wrong reason.** After a room or level switch the picture sometimes ran fast, out of
  step with the sound, until the buffer was empty; Auto read that stall as a slow connection. It wasn't reproduced
  (six quick switches at up to 2 Mbps stayed in sync), so the handling changed instead: the player samples mpv's
  `demuxer-cache-state` `cache-end` once a second and steps down only when the stream arrives below 95% of real
  time over the last 20 s. A picture running over 25% faster than the clock for 3 s, or `avsync` above 0.5 s, gets
  `seek 0 relative+exact`, which restarts audio and video together. Live check: 11 samples in 14 s, "in time".
- **Choosing a graphics chip in mpv.** mpv lists chips with `--d3d11-adapter=help` (Windows, "Adapter N: vendor:
  4318, description: ...", matched by case-insensitive prefix) and `--vulkan-device=help` (elsewhere).
  `d3d11-adapter` carries mpv's UPDATE_VO flag, so changing it at runtime rebuilds the video output; `vulkan-device`
  doesn't, and setting `vo` to the value it already has does nothing (mpv skips writes of equal values), so on Linux
  the player alternates `vo` between `gpu-next` and `gpu-next,gpu`.
- **Window size.** `--geometry` with decimal percentages (`30.5%x32.2%`) makes mpv refuse to start, and on Wayland
  with two monitors `display-width`/`display-height` reported 5040x2681, matching neither monitor, while `40%x40%`
  meant 40% of the 4K one. Pixel sizes behave: `--geometry=1536x864` gives a 1536x864 (physical) window at 1.8x
  scaling, the same numbers `osd-dimensions` reports. So the window size is kept in pixels.

### Fast motion in High quality on Windows (0.13.0)

- **Report:** on the Windows laptop (a separate and a built-in graphics chip), the picture still ran fast at
  times, above all in High quality.
- **Why High quality:** it uses `video-sync=display-resample`, where mpv shows each frame for a number of display
  refreshes. In `handle_display_sync_frame` (player/video.c), when the picture is behind the sound by at least one
  refresh it takes `av_diff / vsync` refreshes away, up to the frame's whole share, so frames are skipped as fast as
  they decode: fast-forward until it has caught up. With the display's timing wrong as mpv sees it (likely when the
  separate chip draws for a panel wired to the built-in one, where DXGI's frame statistics can't be read), the
  picture falls behind again and again. Not confirmed on the laptop yet.
- **Changes:**
  - racing is caught sooner: 15% faster than the clock over 2 s (was 25% over 3 s; display-resample's own
    correction is about 1%), or `avsync` above 0.3 s throughout (was 0.5 s);
  - a jump in the position by more than the clock plus 5 s is a timestamp jump in the stream, not racing, even
    without mpv's `seek` event;
  - two re-syncs within two minutes while `display-sync-active` switch High quality to `video-sync=audio` without
    interpolation for the rest of the run, and log mpv's `display-fps`, `estimated-display-fps`, `vsync-jitter`,
    `container-fps`, `current-gpu-context` and `hwdec-current`, to tell what the laptop's display timing was;
  - started from the launcher (no terminal), that output goes to `cn-live-viewer.log` beside the room list.
- **Window dragging:** mpv moves the window when the picture is dragged (`window-dragging`), which got in the way of
  the seek strip and clicks; it's off, so the title bar moves the window.

### Stalls instead of re-syncs in High quality (0.13.1)

- **Report:** Windows desktop, RTX 3080, 160 Hz HDR display, Huya 20 Mbps at 1080p60. In High quality the log
  showed one re-sync, then "The buffer ran dry, but the stream arrives in time" over and over.
- **Measured:** 95 s gave 49 `Enter buffering` (about 0.7 s of play, then 1 s waiting), and mpv warned of A/V
  desync. mpv's own `estimated-display-fps` was 159.9 with no `vsync-jitter`, but libplacebo's interpolation logged
  display FPS estimates of 3200 and 4800. Same with `--target-colorspace-hint=no` (25 stalls in 50 s);
  `--video-sync=audio` gave none.
- **Why the 0.13.0 fallback missed it:** `Flow.out_of_step` needs 2 s of steady play, and every stall restarts it,
  so with a stall every 1.7 s racing was caught about once.
- **Change:** a stall while the stream arrives in time, with `display-sync-active`, counts toward the same
  two-in-two-minutes limit as a re-sync (`Player.display_ran_ahead`). Re-test: smooth motion went off at 7.7 s,
  3 stalls in 90 s.

### Fullscreen that wouldn't leave on Windows (0.13.2)

- **Report:** after a double-click into fullscreen, it wouldn't go back to a window.
- **Measured:** the double-click does reach mpv both times (`MBTN_LEFT_DBL` -> `cycle fullscreen`, entering then
  leaving). Maximized, the window's client area was 3840x2036 at y=40 (title bar and taskbar); after leaving
  fullscreen it stayed at `0:0:3840:2160` with no title bar. Plain mpv 0.41.0-dev with `--no-config
  --window-maximized=yes` does the same, so it's mpv's win32 window code, not cn-live-viewer's options.
- **Change:** bar.lua, on Windows, sets `window-maximized` to false and 50 ms later back to true when fullscreen
  ends on a maximized window. Set straight back, mpv sees no change and nothing happens (tried: the window stayed
  full-screen-sized). Re-test through the app over IPC, twice: 3840x2036 again after leaving; the saved window
  settings unchanged.
