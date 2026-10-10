# cn-live-viewer

Watch [Huya](https://www.huya.com) and [Douyin](https://live.douyin.com) live rooms in [mpv](https://mpv.io):
- no ads;
- the highest bitrate the room offers;
- live chat scrolling over the video;
- switch rooms without leaving the player.

```
cn-live-viewer 333003
cn-live-viewer https://live.douyin.com/286658238204
```

## Features

- **Huya at 20 Mbps.** That's the web player's top option, which other tools don't list. Douyin plays the
  streamer's original upload.
- **Chat over the video**, scrolling right to left in the top half of the picture, and in the terminal.
- **Room list inside the player.** Press Tab, pick a room, and video and chat switch in the same window. Add, save,
  rename and remove rooms, and set the default room, from the same menu; new rooms are named after the streamer.
- **Reconnects** by itself when a stream drops.
- **Smooth on high-refresh monitors:** 60 fps streams are resampled to the display, so motion doesn't judder at
  144/160/240 Hz.
- **No login and no browser.** Only the public endpoints the sites' own web players use.

## Requirements

| | |
|---|---|
| OS | Linux. macOS should work but is untested. Windows is not supported yet. |
| Python | 3.10 or newer |
| mpv | 0.39 or newer for the room list. Older versions play and show chat but have no room list. |
| Font | A Simplified Chinese font for the chat: Noto Sans CJK SC on Linux, PingFang SC on macOS (built in) |

Install the system packages first:

```bash
sudo apt install mpv pipx fonts-noto-cjk
```

| System | Command |
|---|---|
| Fedora | `sudo dnf install mpv pipx google-noto-sans-cjk-fonts` (mpv comes from RPM Fusion) |
| Arch | `sudo pacman -S mpv python-pipx noto-fonts-cjk` |
| macOS | `brew install mpv pipx` |

## Install

```bash
pipx install git+https://github.com/jody0731/cn-live-viewer
```

From a clone, `./install.sh` does the same. Without pipx it installs into a private virtual environment and links
the command into `~/.local/bin`.

Update with `pipx upgrade cn-live-viewer`. Uninstall with `pipx uninstall cn-live-viewer`.

## Use

| Command | What it does |
|---|---|
| `cn-live-viewer [ROOM]` | Watch a room. With no room, the first saved room plays. |
| `cn-live-viewer chat ROOM` | Print a room's chat in the terminal only |
| `cn-live-viewer url ROOM` | Print the stream address, for another player |
| `cn-live-viewer rooms` | List the saved rooms and show where the list is |

ROOM is a room number or a link. A bare number is a Huya room unless it's saved as a Douyin room.

Options:

| Option | Meaning |
|---|---|
| `-q`, `--quality` | Huya: bitrate in kbps (default 20000). Douyin: `origin` (default), `hd`, `sd`, `ld` or `md`. |
| `--no-overlay` | No chat over the video. It still prints in the terminal. |
| `--mpv-args="..."` | Extra mpv options, e.g. `--mpv-args="--volume=50 --fs"` |
| `--rooms FILE` | Use another room list |
| `-v` | Log connection details |

Keys in the player:

| Key | Action |
|---|---|
| Tab | Room list. Enter switches; typing searches the list. The entries after the rooms add, save, rename and remove rooms and set the default room. |
| C | Chat overlay on/off |
| Space | Pause |
| F | Fullscreen |
| Q | Quit |

All of mpv's usual keys work too.

## The room list

`~/.config/cn-live-viewer/rooms.conf`, created on the first run. One room per line:

```
# platform  room            name
huya        333003          A Huya room
douyin      286658238204    A Douyin room
```

- The first line is the default room, played when cn-live-viewer starts without a room. Change it in the player (Tab,
  Set the default room).
- The name is free text.
- The room is the number in the room's address.
- Rooms you add or save in the player are named after the streamer. Rename them in the player (Tab, Rename a room)
  or in the file.

## Data use

At 20 Mbps, Huya uses about **9 GB per hour**. On a metered connection, ask for less:

```bash
cn-live-viewer 333003 -q 4000
```

Douyin's original upload measured about 5 Mbps in testing, but it depends on the streamer.

## Settings

cn-live-viewer starts its own mpv with these options:

```
--profile=high-quality --hwdec=auto-safe --video-sync=display-resample --interpolation --tscale=oversample --window-maximized=yes
```

They are passed on the command line, so they win over the same options in your `mpv.conf`. Everything else in
your `mpv.conf` and `input.conf` still applies. Change them with `--mpv-args`, which comes last, for example:

```bash
cn-live-viewer --mpv-args="--no-interpolation --window-maximized=no"
```

The chat overlay has three options:

| Option | Default | Meaning |
|---|---|---|
| `font` | depends on the OS | Font for the chat |
| `max_on_screen` | 60 | Most messages shown at once. Extra messages are skipped. |
| `max_fps` | 240 | Most redraws per second. Text moves on every display refresh up to this rate. |

Set them through `--script-opts`, prefixed with `cnlv-danmaku-`:

```bash
cn-live-viewer --mpv-args="--script-opts=cnlv-danmaku-max_on_screen=30,cnlv-danmaku-font='Noto Sans CJK SC'"
```

[`examples/`](examples) has a sample room list and optional `mpv.conf` and `input.conf` additions.

## Troubleshooting

- **"offline or not found":** the room isn't live, or the number is wrong. Try the room's full link.
- **No chat:**
  - run with `-v` to see the connection log;
  - chat and Douyin's room lookups connect directly and ignore proxy settings;
  - the video goes through mpv, which has its own `--http-proxy` option.
- **Video stutters when chat is busy:**
  - lower `max_on_screen`, or `max_fps` (moving text then looks less sharp);
  - or try `--mpv-args="--no-interpolation"`;
  - C turns the overlay off to check whether it's the cause.
- **Chat shows boxes instead of characters:** install a Simplified Chinese font (see Requirements).
- **mpv isn't found:** install it with your system's package manager.

## How it works

- **Huya:**
  - Streamlink finds the stream address, and cn-live-viewer raises its bitrate;
  - chat comes from Huya's websocket, in Tencent's TARS encoding.
- **Douyin:**
  - stream and chat come from the web player's endpoints, with only the visitor cookie;
  - chat is polled.
- **The player:**
  - one mpv window, controlled through its IPC socket;
  - two small Lua scripts draw the chat and the room list.

The details are in [docs/PROTOCOLS.md](docs/PROTOCOLS.md). [docs/DEVLOG.md](docs/DEVLOG.md) records what was tried
and measured.

## Disclaimer

An unofficial tool, not affiliated with Huya or Douyin. It uses the same public endpoints the sites' web players
use, and the sites can change them at any time. It only plays streams anyone can open in a browser without signing
in.

## License

[MIT](LICENSE)
