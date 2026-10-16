# cn-live-viewer

Watch [Huya](https://www.huya.com) and [Douyin](https://live.douyin.com) live rooms in [mpv](https://mpv.io):

- no ads
- the highest bitrate the room offers
- live chat scrolling over the video
- switch rooms without leaving the player

![cn-live-viewer playing a Douyin room: the live chat scrolling over the video, and the control bar with the seek strip, LIVE badge, room name and quality](docs/images/player.jpg)

## Features

- **Huya at 20 Mbps.** That's the web player's top option, which other tools don't list. Douyin plays the
  streamer's original upload.
- **Chat over the video.** It scrolls right to left in the top half of the picture, and prints in the terminal.
- **Room list inside the player.** Press Tab, pick a room, and video and chat switch in the same window. Add, save,
  rename and remove rooms, and set the default room, from the same menu; new rooms are named after the streamer.
- **Reconnects by itself** when a stream drops.
- **Video Decoder that fits the computer.** Auto picks at each start: Efficient on battery, on a busy computer or
  with built-in graphics; High quality (sharper scaling, smooth motion on 144 Hz and faster monitors) on mains power
  with a separate graphics card. On laptops with two graphics chips, each mode runs on its own chip.
- **Several windows at once.** Start it again, or use "new window" on its taskbar button, to watch two rooms.
- **No login and no browser.** Only the public endpoints the sites' own web players use.

## Install

One command. It installs what your system is missing (mpv, a Chinese font for the chat, Python 3.10+), asking before
it does, then cn-live-viewer itself, and adds **CN Live Viewer** to your apps.

Linux and macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/jody0731/cn-live-viewer/main/install.sh | sh
```

Windows, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/jody0731/cn-live-viewer/main/install.ps1 | iex
```

What they use:

- **System packages:** apt, dnf, pacman or zypper on Linux, and Homebrew on macOS (on a Mac without it, the script
  offers to install Homebrew first).
- **Windows:** winget. If winget is missing or fails, Python comes from python.org's installer (for your user only,
  no admin rights needed) and mpv from its official build on GitHub, into cn-live-viewer's own folder.
- **cn-live-viewer itself:** pipx when you have it, otherwise a private Python environment. Git isn't needed.
- **A last check:** the installed copy runs `cn-live-viewer check` and lists anything still missing.
- **No questions:** from a clone, `./install.sh --yes` or `install.ps1 -Yes` installs without asking.

To update, run the install command again.

### The app

**CN Live Viewer** comes with mpv's icon, added on install or on the first start:

| System | Where it is |
|---|---|
| Linux | The app menu and search. Pin it to a panel or dock. A Huya or Douyin link dropped on it opens that room. |
| macOS | `~/Applications`, so it's in Launchpad and Spotlight. |
| Windows | The Start menu. It runs without a console window. |

Started from there, chat shows only on the video, as there is no terminal. `cn-live-viewer desktop remove` removes
it for good, and `cn-live-viewer desktop` adds it back.

## Requirements

| Needs | Version |
|---|---|
| OS | Linux, macOS or Windows |
| Python | 3.10 or newer |
| mpv | 0.39 or newer for the room list. Older versions play and show chat but have no room list. |
| Font | A Simplified Chinese font for the chat: Noto Sans CJK SC on Linux. macOS (PingFang SC) and Windows (Microsoft YaHei) have one built in. |

It's developed on Linux. On macOS and Windows, automated tests install it on a fresh machine, start mpv and load its
scripts, but nobody has watched a stream there yet.

The install command above installs all of this for you. To install it yourself instead:

| System | Command |
|---|---|
| Debian, Ubuntu | `sudo apt install mpv pipx fonts-noto-cjk` |
| Fedora | `sudo dnf install mpv pipx google-noto-sans-cjk-fonts` (mpv comes from RPM Fusion) |
| Arch | `sudo pacman -S mpv python-pipx noto-fonts-cjk` |
| macOS | `brew install mpv pipx` |
| Windows | `winget install Python.Python.3.14 shinchiro.mpv`, or Python from [python.org](https://www.python.org/downloads/) and mpv from [mpv.io](https://mpv.io/installation/) |

Then `pipx install https://github.com/jody0731/cn-live-viewer/archive/refs/heads/main.zip`, and
`cn-live-viewer check` to see that everything is in place.

## Use

| Command | What it does |
|---|---|
| `cn-live-viewer [ROOM]` | Watch a room. With no room, the first saved room plays. |
| `cn-live-viewer chat ROOM` | Print a room's chat in the terminal only |
| `cn-live-viewer url ROOM` | Print the stream address, for another player |
| `cn-live-viewer rooms` | List the saved rooms and show where the list is |
| `cn-live-viewer desktop [remove]` | Add (or remove) the app launcher |
| `cn-live-viewer check` | Check that mpv and everything else it needs is in place |

ROOM is a room number or a link. A bare number is a Huya room unless it's saved as a Douyin room.

### Options

| Option | Meaning |
|---|---|
| `-q`, `--quality` | `auto`, a bitrate cap in Mbps such as `8`, or for Douyin `origin`, `hd`, `sd`, `ld` or `md`, for this start only. Without it, the quality last chosen in the player (else Auto). See Quality. |
| `--no-overlay` | No chat over the video. It still prints in the terminal. |
| `--mpv-args="..."` | Extra mpv options, e.g. `--mpv-args="--fs"` |
| `--rooms FILE` | Use another room list |
| `-v` | Log connection details |

### Keys in the player

| Key | Action |
|---|---|
| Tab | Room list. Enter switches; typing searches the list. The entries after the rooms add, save, rename and remove rooms and set the default room. |
| C | Chat overlay on/off |
| Space | Pause |
| F | Fullscreen |
| Q | Quit |

All of mpv's usual keys work too.

### With the mouse

- **Control bar:** moving the mouse shows a slim bar at the bottom, in place of mpv's own. It hides 0.5 s after
  the mouse stops. Hover anything to see what it does.
  - **Seek row:** the playback time, a strip over the part of the stream mpv has buffered, and how many seconds are
    buffered ahead (Cache). On the strip, red is played and light grey is received but not yet played. Click or
    drag to go back; the right end is live.
  - **Left:** mpv's menu ☰ (key bindings, stream info, statistics, help), play/pause, and the LIVE badge. When
    you're behind, the badge shows how far (e.g. −0:42); click it to catch up. Then the room name: click it for the
    room list.
  - **Right:** the quality (e.g. "Auto · 20 Mbps"; click to choose), the chat overlay, volume (click to mute,
    scroll to change) and fullscreen.
- **Right-click menu:** Rooms (click one to switch), Quality, Video Decoder, Chat overlay, Fullscreen and Quit.
  Right-click never pauses in cn-live-viewer's window.

![The right-click menu with the Quality submenu open on a Douyin room: Auto, then Original down to Smooth with resolution and bitrate](docs/images/menu.png)

## The room list

`~/.config/cn-live-viewer/rooms.conf` (Windows: `%APPDATA%\cn-live-viewer\rooms.conf`), created on the first
run. `cn-live-viewer rooms` shows where it is. One room per line:

```text
# platform  room            name
huya        333003          A Huya room
douyin      286658238204    A Douyin room
```

- **Room:** the number in the room's address.
- **Name:** free text. Rooms you add or save in the player are named after the streamer. Rename them in the player
  (Tab, Rename a room) or in the file.
- **Default room:** the first line, played when cn-live-viewer starts without a room. Change it in the player (Tab,
  Set the default room).
- **On start:** if the default room is offline, cn-live-viewer tries the rooms you watched lately, newest first,
  then the rest of the list, and plays the first one that's live.
- **Status:** the room lists start each room with ● Live, ○ Offline, ▶ Playing (or ▶ Waiting).
  - All saved rooms are checked at once when cn-live-viewer starts, every 5 minutes, and when you open a room list,
    reusing results under 2 minutes old. Each check is one small request per room: a few MB an hour for a handful
    of rooms, against about 9 GB an hour of video.
  - A list that is already open doesn't update until you open it again.
- **Offline rooms:** you can switch to one. Its chat runs, and the video starts by itself when it goes live
  (checked every 30 s).
- **Added rooms:** a room you add is switched to straight away, or waited for if it's offline.

## Quality and data use

**Auto (the default)** starts at the best quality the room offers:
- **Step down:** if the buffer runs dry for more than 4 s, or twice within a minute, Auto steps down one level.
  Only when the connection is the cause: if the stream kept arriving in real time, the quality stays.
- **Picture and sound in step:** if the picture races ahead or drifts away from the sound (it can happen right after
  a switch), the player puts them back in step.
- **Step up:** after 5 calm minutes, it tries one level up.
- **Backing off:** if that try stalls too, it waits 20 minutes before trying again.
- **Notices:** every change shows on screen.

To fix a level, use the quality button in the control bar or right-click, then Quality. A fixed level carries over
to other rooms as a bitrate cap: "8 Mbps" picks the best level at or below 8 Mbps.

| Site | Levels |
|---|---|
| Huya | 20 Mbps, plus the room's own bitrates, usually 8, 4, 2 and 0.5 Mbps |
| Douyin | Original, HD, SD, Low and Smooth, with resolution and bitrate when the room gives them. Also Audio only, a manual choice that Auto never picks. |

At 20 Mbps, Huya uses about **9 GB per hour**. On a metered connection, cap it from the start:

```bash
cn-live-viewer 333003 -q 4
```

Douyin's original upload measured about 5 Mbps in testing, but it depends on the streamer.

## Video Decoder and resource use

Right-click, Video Decoder, switches at once. The choice is kept for the next start.

| Choice | What it does |
|---|---|
| **Auto** (default) | Picks one of the two modes at each start. Efficient on battery, when the CPU is already busy (over 70%), or with only built-in graphics. High quality on mains power with a separate graphics card, and on Macs. |
| **Efficient** | mpv's standard picture. A new frame is drawn only when the video has one (30 or 60 a second), and the chat moves up to 60 times a second. |
| **High quality** | Sharper upscaling (`ewa_lanczossharp`). The video is timed to the display and frames are blended in between, so 30 and 60 fps streams move smoothly at 144 Hz and up. The chat moves up to 120 times a second. If the picture keeps running ahead of the sound (the display's timing is off), it times the video to the sound instead for the rest of that run. |

**Two graphics chips** (most gaming laptops: a built-in Intel or AMD chip and a separate NVIDIA or AMD one):
Efficient runs on the built-in chip and High quality on the separate one, so High quality doesn't stutter on the
weak chip and Efficient doesn't wake the strong one. With one chip, the two modes are only different settings. The
chips are detected once per install or update (`cn-live-viewer check` shows them); macOS picks its chip by itself.

Both decode the video on the graphics chip's video engine (hardware decoding), which takes a fraction of the power
the CPU would need. mpv falls back to the CPU when the chip can't decode a stream.

Measured on a desktop (RTX 3080, 4K 160 Hz monitor, a 1080p60 15 Mbps video, busy chat):

| | Efficient | High quality | Efficient, CPU decoding |
|---|---|---|---|
| mpv's CPU use (one core = 100%) | about 20% | about 35% | about 60% |
| Extra GPU power | about 4 W | about 11 W | about 4 W |
| mpv's memory | about 350 MB | about 360 MB | about 480 MB |

The chat overlay accounts for about 10% of a core. Turn it off with C to save that.

Memory grows by the rewind buffer as it fills: up to 512 MiB, about 3.5 minutes at 20 Mbps (see below). The
cn-live-viewer program itself (Python) uses about 60 MB of memory and almost no CPU. On disk it takes about 80 MB, plus
mpv and, on Windows, Python.

## Settings

**Kept between starts** (in `settings.json`, next to the room list): the volume (50% at first) and mute, the chat
overlay on or off, the quality you chose (Auto stays Auto), the Video Decoder, and the window: fullscreen, maximized
(the first start), or the size you gave it. The window keeps its size when you switch rooms. Change them in the player; they come
back at the next start.

cn-live-viewer starts its own mpv with these options:

```text
--hwdec=auto-safe --demuxer-max-back-bytes=512MiB --volume=<kept> --mute=<kept> --window-maximized=<kept> --geometry=<kept size> --fullscreen=<kept> --auto-window-resize=no --include=<the Video Decoder modes> --window-dragging=no --profile=<the mode>
```

- `--demuxer-max-back-bytes=512MiB` keeps up to 512 MiB of watched video in memory, so you can go back about 3.5
  minutes at 20 Mbps (longer at lower bitrates). The memory is only used as it fills. Lower it with e.g.
  `--mpv-args="--demuxer-max-back-bytes=128MiB"`.
- The Video Decoder's modes are in [`cnlv.conf`](src/cn_live_viewer/mpv/cnlv.conf). They set only the scaling and
  timing options listed there. On a computer with two graphics chips, cn-live-viewer also names the chip:
  `--d3d11-adapter` on Windows, `--gpu-api=vulkan --vulkan-device` (and `--vo=gpu-next`) elsewhere. Your choice and
  the detected chips are kept in `settings.json`, next to the room list.
- cn-live-viewer also turns off mpv's own control bar (`--osc=no`) and draws its own.

These options are passed on the command line, so they win over the same options in your `mpv.conf`. Everything else
in your `mpv.conf` and `input.conf` still applies. Change them with `--mpv-args`, which comes last, for example:

```bash
cn-live-viewer --mpv-args="--window-maximized=no --fs"
```

The chat overlay has four options:

| Option | Default | Meaning |
|---|---|---|
| `font` | depends on the OS | Font for the chat |
| `max_on_screen` | 100 | Most messages shown at once. Extra messages are skipped. |
| `max_fps` | 120 | Most redraws per second in High quality. Text moves on every display refresh up to this rate. |
| `efficient_fps` | 60 | Most redraws per second in Efficient |

Messages take 18 seconds to cross the screen: slow enough that each redraw moves them only a couple of pixels.

Set them through `--script-opts`, prefixed with `cnlv-danmaku-`:

```bash
cn-live-viewer --mpv-args="--script-opts=cnlv-danmaku-max_on_screen=30,cnlv-danmaku-font='Noto Sans CJK SC'"
```

[`examples/`](examples) has a sample room list and optional `mpv.conf` and `input.conf` additions.

## Troubleshooting

- **Something's missing, or it doesn't start:** run `cn-live-viewer check`. It lists what's in place and what's
  missing.
- **Started from the app launcher, what happened?** `cn-live-viewer.log` beside the room list (Windows
  `%APPDATA%\cn-live-viewer`, others `~/.config/cn-live-viewer`) has what the terminal would show, from the
  last start.
- **"offline or not found":** the room isn't live, or the number is wrong. Try the room's full link.
- **No chat:**
  - run with `-v` to see the connection log;
  - chat and Douyin's room lookups connect directly and ignore proxy settings;
  - the video goes through mpv, which has its own `--http-proxy` option.
- **Video stutters when chat is busy:**
  - use Efficient (right-click, Video Decoder);
  - lower `max_on_screen`;
  - C turns the overlay off to check whether it's the cause.
- **High CPU use, a hot laptop or a short battery:**
  - use Efficient (Auto picks it on battery);
  - check that hardware decoding works: Shift+I shows mpv's statistics, whose Video line names the hardware
    decoder in use, e.g. nvdec, vaapi, d3d11va or videotoolbox. If there is none, the CPU decodes. On Linux with
    Intel or AMD graphics, that usually means the VA-API driver is missing (`intel-media-va-driver` or
    `mesa-va-drivers`);
  - a lower quality (e.g. 4 Mbps) is also less work to decode.
- **Chat shows boxes instead of characters:** install a Simplified Chinese font (see Requirements).
- **mpv isn't found:** install it with your system's package manager, or run the install command again.

## How it works

- **Huya:**
  - Streamlink finds the stream address, and cn-live-viewer raises its bitrate;
  - chat comes from Huya's websocket, in Tencent's TARS encoding.
- **Douyin:**
  - stream and chat come from the web player's endpoints, with only the visitor cookie;
  - chat is polled.
- **The player:**
  - one mpv window, controlled through its IPC socket;
  - three small Lua scripts draw the chat, the room list and the control bar.

The details are in [docs/PROTOCOLS.md](docs/PROTOCOLS.md). [docs/DEVLOG.md](docs/DEVLOG.md) records what was tried
and measured.

## Disclaimer

An unofficial tool, not affiliated with Huya or Douyin. It uses the same public endpoints the sites' web players
use, and the sites can change them at any time. It only plays streams anyone can open in a browser without signing
in.

## License

[MIT](LICENSE)
