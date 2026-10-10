# Changelog

## 0.2.0 (2026-10-11)

- Add, rename and remove rooms in the player's room list (R). Adding takes a room number or link.
- Rooms you add or save are named after the streamer, and the window title shows the streamer's name.
- Smoother chat overlay: text moves on every display refresh again (default `max_fps` 240).

## 0.1.0 (2026-10-10)

First release. Linux; macOS should work but is untested; Windows is not supported yet.

- Huya and Douyin live rooms in one mpv window, no ads.
- Huya at 20 Mbps by default (`ratio=20000`, the web player's top option); Douyin at the streamer's original upload.
- Scrolling chat over the video and in the terminal. C toggles the overlay.
- Room list inside mpv (R): switch rooms in the same window, save the current room.
- Reconnects when a stream drops.
- Smooth playback on high-refresh displays; the window opens maximized.
