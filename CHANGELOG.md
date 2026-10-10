# Changelog

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
