# Changelog

## 0.13.0 (2026-10-16)

- **Fast motion in High quality:** High quality times the video to the display. When the display's timing as mpv
  sees it is off, as on laptops whose separate graphics chip draws for a screen wired to the built-in one, the
  picture kept falling behind the sound and caught up by skipping frames, which looks like fast-forward. Racing
  is now caught sooner (15% fast for 2 s, or sound and picture 0.3 s apart), and when it keeps coming back (twice
  in two minutes), High quality times the video to the sound for the rest of that run: the sharper scaling stays,
  the frame blending goes, and a message says so.
- **The window moves only by its title bar.** Clicking or dragging on the picture no longer drags the window.
- **A log when started from the app launcher:** with no terminal to print to, what it would print (rooms, quality
  changes, re-syncs, errors; not the chat) goes to `cn-live-viewer.log` beside the room list, started afresh each
  time.

## 0.12.0 (2026-10-12)

- **Switching rooms or levels:** after a switch the picture sometimes played fast, out of step with the sound, until
  the buffer ran dry, and Auto then lowered the quality although the connection was fine. Auto now steps down only
  when the stream arrives slower than real time, and a picture racing ahead of or drifting from the sound is put
  back in step at once.
- Switching rooms quickly could play an earlier choice after the later one, when its lookup finished last.
- **Video Decoder** replaces Picture (right-click). New default **Auto** picks a mode at each start: Efficient on
  battery, on a busy computer or with only built-in graphics; High quality on mains power with a separate graphics
  card. On computers with two graphics chips (most gaming laptops), Efficient runs on the built-in chip and High
  quality on the separate one, switching at once; before, both ran wherever the system put mpv, often the weak chip,
  and High quality stuttered there. The chips are detected once per install or update; `cn-live-viewer check` lists
  them. A Picture choice made in 0.11 is kept.
- **Remembers your settings:** volume and mute, the chat overlay on or off, and a quality you chose (Auto stays
  Auto) come back at the next start, with the Video Decoder and the window: fullscreen, maximized, or its size.
  The window no longer resizes itself when you switch rooms.
  `-q` now applies to that start only.
- **Volume starts at 50%** (was mpv's 100%, or your `mpv.conf`).
- **Calmer chat:** messages cross the screen in 18 s instead of 9, so each redraw moves them half as far and they
  glide. High quality redraws the chat up to 120 times a second (was 240); up to 100 messages show at once (was 60).
- **Several windows:** on Windows, the player's taskbar button is now cn-live-viewer's own, so "new window" and
  pinning start cn-live-viewer again (they started a bare mpv).

## 0.11.0 (2026-10-11)

- **Light by default.** A new Efficient picture mode is the default: hardware decoding, mpv's standard scaling,
  a new frame only when the video has one, and the chat moving up to 60 times a second. Measured on a 4K 160 Hz
  desktop: about half the CPU and a third of the extra GPU power of before. The old settings (sharper upscaling,
  frames blended to the display's refresh rate) are the High quality mode. Right-click, Picture, switches at once,
  and the choice is kept in `settings.json`. Both modes now override the same few options in your `mpv.conf`.
- **Windows install, redone:** "Python was not found" no longer stops it. That message comes from the Microsoft
  Store placeholder that Windows ships as `python.exe`, and Windows PowerShell 5.1 turned it into an error that
  ended the script. Python is now looked for in more places (the py launcher, PATH, installs that aren't on PATH)
  and, when missing, installed with winget, or with python.org's installer for your user only if winget fails. One
  question covers everything missing.
- **Linux and macOS install:** finds a Python 3.10+ among versioned ones too (`python3.12` and so on), installs a
  newer Python where the system's is older (RHEL and openSUSE Leap), skips macOS's own Python 3.9, and offers to
  install Homebrew on a Mac without it.
- **`cn-live-viewer check`** lists what's in place and what's missing: Python, its libraries, mpv and its version,
  the Chinese font. The install scripts run it last.
- The Linux launcher points at the copy that added it, not another copy that comes first on PATH.
- CI installs from scratch on Windows (in Windows PowerShell 5.1, with Python and winget hidden), Linux and macOS.
- README: the picture modes and measured resource use; tidier tables and lists.

## 0.10.3 (2026-10-11)

- Windows install: mpv's release zip holds another zip with the program; the installer now unpacks both
  (0.10.2 downloaded mpv but couldn't find `mpv.exe`).

## 0.10.2 (2026-10-11)

- Windows install: if winget is missing or fails (seen: 0x80073cfc, a broken winget source), `install.ps1` now
  downloads mpv's official build from its GitHub release into cn-live-viewer's folder, where the player finds it.
  winget failures come with the likely fix, and the end of the install says plainly if mpv is still missing.
- CI runs the whole Windows installer and checks the installed copy finds the downloaded mpv.

## 0.10.1 (2026-10-11)

- The control bar scales with the window's height again (as before 0.8.0). The chat still fits the picture.
- In a narrow window the room name no longer overlaps the quality button; if it can't fit, it's left out.

## 0.10.0 (2026-10-11)

- The room lists start each room with its status: ● Live, ○ Offline, ▶ Playing / ▶ Waiting. All saved rooms are
  checked at start, every 5 minutes and when a room list opens, with one small request per room. On start, live
  rooms are tried first.
- Switching to an offline room waits for it: its chat runs and the video starts by itself when it goes live.
- A room you add is switched to straight away.
- Fixed: an offline Huya room couldn't be added ("not found") and its chat didn't start. Huya rooms are now looked
  up through the room-profile API, which works offline, instead of the mobile room page.
- Douyin requests ask for gzip: the room data is about 7x smaller.

## 0.9.0 (2026-10-11)

- On start, an offline default room falls back to the rooms watched lately (newest first), then the rest of the
  list; the first live one plays. The screen says which room it tries next.
- The app launcher is added on the first start, so every install has it, pipx too. A launcher removed with
  `cn-live-viewer desktop remove` stays removed.
- The install scripts also install what the system is missing, asking first:
  - Linux (apt, dnf, pacman, zypper): mpv, a Chinese font and Python's venv;
  - macOS (Homebrew): mpv and Python;
  - Windows (winget): Python and mpv.
  They work without a clone (`curl … | sh`, `irm … | iex`) and no longer need git.
- README screenshots of the player and the right-click menu.
- Douyin's audio-only level shows as "Audio only" (it was "ao"). You can choose it, but Auto and bitrate caps never
  pick it.
- Tooltips are sized to their text: libass measures it, instead of an estimate that ran wide.
- Quality choice. The new default, Auto, starts at the best level and steps down when the connection can't keep
  up, then tries upwards again after a calm stretch. Pick a fixed level with the quality button in the control bar
  or right-click, Quality. Huya offers 20 Mbps plus the room's own bitrates; Douyin offers its named qualities,
  with resolution and bitrate where given. `-q` takes `auto`, a cap in Mbps (`-q 8`) or a Douyin name.
  The old kbps form (`-q 2000`) still works.

## 0.8.1 (2026-10-11)

- Windows: find mpv installed with Chocolatey (`choco install mpv`) even before it is on PATH.
- CI: the mpv smoke test must run on every system; it fails instead of skipping when mpv isn't found.

## 0.8.0 (2026-10-11)

- Fixed: a Huya room number with no room showed Streamlink's raw validation error on screen; it now says
  "offline or not found". Quitting while a room is loading no longer prints a traceback.
- macOS and Windows support:
  - **Connection:** mpv is reached through a named pipe on Windows.
  - **Finding mpv:** Homebrew, Scoop and Chocolatey installs are found even without PATH.
  - **Room list:** kept in `%APPDATA%` on Windows.
  - **Launcher:** an app in `~/Applications` on macOS, a Start menu shortcut without a console on Windows.
  - **Installer:** `install.ps1` for Windows.
  - **Tests:** CI runs on all three, including a test that starts the real mpv with the scripts.
- App launcher for Linux desktops: `cn-live-viewer desktop` adds CN Live Viewer (with mpv's icon) to the app menu,
  so it starts without a terminal and can be pinned. `install.sh` adds it. Started from the launcher with no rooms
  saved yet, the player opens anyway and asks you to add one.
- Fixed: when the room played on start was offline or unknown, the room list (Tab) was empty. It now always
  shows the saved rooms, and the error says to press Tab for another room.
- Chat and the control bar scale to fit the window by width or height, whichever is smaller, so tall or narrow
  windows (e.g. a portrait monitor) no longer get oversized text. Chat starts at the picture's top edge, not
  over a black bar, and uses as many rows as fit in the picture's upper half.

## 0.7.0 (2026-10-11)

- The control bar is slimmer (three quarters of its old height) and mostly see-through.
- The seek row shows the playback time on the left and the seconds buffered ahead on the right ("Cache", as
  mpv's own bar). On the strip, red is what's played and light grey is what's received but not yet played.
- The chat overlay leaves out emoji. They showed as unreadable shapes and made the video drop frames while on
  screen. The terminal still shows them.

## 0.6.0 (2026-10-11)

- Seek strip in the control bar: click or drag to go back within what mpv has buffered (up to about 3.5 minutes at
  20 Mbps: the rewind buffer is now 512 MiB). A LIVE badge shows how far behind you are; click it to catch up.
- A ☰ button opens mpv's own menu: key bindings, stream info, statistics, help.
- The control bar hides 0.5 s after the mouse stops (was 1.5 s).

## 0.5.0 (2026-10-11)

- Mouse controls. A slim control bar for live streams replaces mpv's own: play/pause, the room name (click it for
  the room list), chat overlay, volume and fullscreen, with tooltips. Subtitles, audio tracks, playlist, chapters
  and seeking are gone.
- Right-click menu: switch rooms, chat overlay, fullscreen, quit. Right-click no longer pauses.

## 0.4.0 (2026-10-11)

- Set the default room (the one played on start) from the room list. The list marks it.
- The room list's search box is labelled as one ("Search rooms:"), and the room pickers say what they are for,
  such as "Remove which room?".

## 0.3.0 (2026-10-11)

- The room list opens with Tab instead of R.

## 0.2.0 (2026-10-11)

- Add, rename and remove rooms in the player's room list (R). Adding takes a room number or link.
- Rooms you add or save are named after the streamer. A room that isn't saved shows the streamer's name as the
  window title.

## 0.1.0 (2026-10-10)

First release. Linux; macOS should work but is untested; Windows is not supported yet.

- Huya and Douyin live rooms in one mpv window, no ads.
- Huya at 20 Mbps by default (`ratio=20000`, the web player's top option); Douyin at the streamer's original upload.
- Scrolling chat over the video and in the terminal. C toggles the overlay.
- Room list inside mpv (R): switch rooms in the same window, save the current room.
- Reconnects when a stream drops.
- Smooth playback on high-refresh displays; the window opens maximized.
