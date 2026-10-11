"""The player: one mpv window, the current room's stream and chat, and switching rooms from inside mpv."""
import asyncio
import logging
import math
import os
import re
import sys
import threading
import time
import zlib

from . import douyin, huya, quality as q, rooms as roomlist
from .mpv import Mpv

log = logging.getLogger(__name__)
SCRIPTS = [os.path.join(os.path.dirname(__file__), 'mpv', n) for n in ('danmaku.lua', 'picker.lua', 'bar.lua')]
# smooth 60 fps on high-refresh monitors, sharper upscaling, GPU decoding, a maximized (not fullscreen) window,
# and a bigger rewind buffer for the seek bar (512 MiB: about 3.5 minutes at 20 Mbps, used only as it fills);
# your own mpv.conf still applies, and --mpv-args overrides these
DEFAULT_MPV_ARGS = ['--profile=high-quality', '--hwdec=auto-safe', '--video-sync=display-resample',
                    '--interpolation', '--tscale=oversample', '--window-maximized=yes', '--demuxer-max-back-bytes=512MiB']
# Emoji: the chat font has none, so they fall back to the colour emoji font, whose glyphs are pictures, not outlines.
# The overlay draws them as unreadable shapes, and while any are on screen video frames drop (measured: 12-55 a second
# for each 🤡x7 message, until it scrolled off). The overlay leaves them out; the terminal still shows them.
EMOJI = re.compile('[\U0001F000-\U0001FAFF\U000E0000-\U000E007F\uFE0E\uFE0F\u200D\u20E3]')
COLORS = ['\033[96m', '\033[93m', '\033[92m', '\033[95m', '\033[94m', '\033[91m']


def overlay_text(text: str) -> str:
    """Chat text for the overlay: no emoji, spaces tidied. Empty when nothing else is left."""
    return ' '.join(EMOJI.sub('', text).split())


def print_chat(nick: str, text: str, color: bool) -> None:
    if color:
        c = COLORS[zlib.crc32(nick.encode()) % len(COLORS)]
        print(f'{c}{nick}\033[0m: {text}', flush=True)
    else:
        print(f'{nick}: {text}', flush=True)


def levels(platform: str, room: str):
    """-> (quality levels best first, referer, a function making the chat generator, streamer name or None)"""
    if platform == 'huya':
        tiers, uid, name = huya.streams(room)
        return tiers, huya.REFERER, lambda: huya.chat(room, uid), name
    tiers, internal, name = douyin.streams(room)
    return tiers, douyin.REFERER, lambda: douyin.chat(room, internal), name


def streamer_name(platform: str, room: str):
    """The streamer's name (a network lookup). Raises LookupError for an unknown room."""
    return huya.room_info(room)[1] if platform == 'huya' else douyin.streamer_name(room)


class Player:
    def __init__(self, rooms_path: str, quality: str = None, overlay: bool = True, mpv_args=None):
        self.rooms_path, self.overlay = rooms_path, overlay
        self.choice = q.parse(quality)               # AUTO, a cap in Mbps, or a Douyin quality name
        self.auto = q.Auto()
        self.tiers, self.tier = [], None             # the current room's levels and the one playing
        self.stalled_since = None
        self.live = {}                               # (platform, room) -> True/False: online markers in the room lists
        self.live_checked = -math.inf
        self.douyin_session, self.douyin_lock = None, threading.Lock()
        self.waiting_task = None                     # waiting for an offline room to go live
        self.rooms = roomlist.load(rooms_path)
        self.mpv = Mpv(SCRIPTS, DEFAULT_MPV_ARGS + list(mpv_args or []))
        self.current = None
        self.names = {}                              # (platform, room) -> streamer name, for rooms not saved yet
        self.chat_task = None
        self.switching = False
        self.color = sys.stdout.isatty()

    def saved(self, platform, room):
        return any((r['platform'], r['room']) == (platform, room) for r in self.rooms)

    def name_of(self, platform, room):
        for r in self.rooms:
            if (r['platform'], r['room']) == (platform, room):
                return r['name']
        return self.names.get((platform, room)) or f'{platform} {room}'

    # ---------------------------------------------------------------- online / offline

    LIVE_EVERY, LIVE_REUSE = 300, 120                # refresh every 5 minutes; a room list opened reuses < 2 min

    def _status(self, platform: str, room: str) -> str:
        """One status check: 'live', 'offline' or 'missing' (a few KB for Huya, ~100 KB gzipped for Douyin).
        Raises when it can't tell."""
        if platform == 'huya':
            return huya.status(room)
        with self.douyin_lock:                       # one visitor session (cookie) for all Douyin checks
            if self.douyin_session is None:
                self.douyin_session = douyin.Session(room)
        return douyin.status(room, self.douyin_session)

    async def refresh_live(self, pairs=None, max_age: float = LIVE_REUSE):
        """Check which rooms are live (the saved ones, or pairs), all at once, and update the room lists."""
        now = time.monotonic()
        if pairs is None:
            if now - self.live_checked < max_age:
                return
            self.live_checked = now
            pairs = [(r['platform'], r['room']) for r in self.rooms]
        results = await asyncio.gather(*(asyncio.to_thread(self._status, *p) for p in pairs), return_exceptions=True)
        for pair, result in zip(pairs, results):
            if isinstance(result, str):
                self.live[pair] = result == 'live'
            else:
                log.info('live check for %s %s failed: %s', *pair, result)
        if self.current and self.tier:
            self.live[self.current] = True           # it's playing
        await self.send_rooms()

    async def live_loop(self):
        while True:
            await asyncio.sleep(self.LIVE_EVERY)
            await self.refresh_live(max_age=0)

    async def send_rooms(self):
        # a property, not a message: picker.lua reads it whenever it loads, so it can't miss the list (a message
        # sent before it loaded, or one it sent before we connected, was lost, and the room list stayed empty)
        data = {'playing': self.current is not None,
                'rooms': [dict(r, current=(r['platform'], r['room']) == self.current,
                               live=self.live.get((r['platform'], r['room']))) for r in self.rooms]}
        await self.mpv.command('set_property', 'user-data/cnlv/rooms', data)

    async def _chat(self, gen):
        try:
            async for nick, text in gen:
                print_chat(nick, text, self.color)
                shown = overlay_text(text) if self.overlay else ''
                if shown:
                    await self.mpv.command('script-message', 'cnlv-danmaku', shown)
        except asyncio.CancelledError:
            raise
        except Exception as e:                       # chat is best effort; the video keeps playing
            log.warning('chat stopped: %s', e)

    async def play(self, platform: str, room: str, quiet: bool = False, next_room=None, wait: bool = False) -> bool:
        """Play a room. next_room: on start, the room tried next if this one isn't live (the message says so).
        wait: if the room is offline, switch to it anyway and wait for it to go live (chosen rooms, added rooms)."""
        if self.waiting_task and self.waiting_task is not asyncio.current_task():
            self.waiting_task.cancel()               # a room we were waiting for: not any more
        self.waiting_task = None
        self.switching = True
        name = self.name_of(platform, room)
        if not quiet:
            await self.mpv.show(f'→ {name} …', 2)
        try:
            tiers, referer, chat, streamer = await asyncio.to_thread(levels, platform, room)
            tier = q.pick(tiers, self.choice, self.auto.cap)
        except Exception as e:
            if wait and isinstance(e, LookupError):
                try:
                    status = await asyncio.to_thread(self._status, platform, room)
                except Exception:                    # noqa: BLE001 - can't tell: assume offline, keep waiting
                    status = 'offline'
                if status != 'missing':
                    await self.wait_for(platform, room, name)
                    self.switching = False
                    return True
            hint = f'Trying {self.name_of(*next_room)} …' if next_room else 'Tab: choose another room'
            await self.mpv.show(f'✗ {e}\n{hint}', 3 if next_room else 6)
            print(f'-- {e}', file=sys.stderr, flush=True)
            self.switching = False
            return False
        if streamer:
            self.names[(platform, room)] = streamer
            name = self.name_of(platform, room)
        if self.chat_task:
            self.chat_task.cancel()
        await self.mpv.command('script-message', 'cnlv-danmaku-clear')
        await self.mpv.command('set_property', 'http-header-fields', [f'Referer: {referer}'])
        await self.mpv.command('set_property', 'force-media-title', name)
        await self.mpv.command('loadfile', tier.url, 'replace')
        self.current, self.tiers, self.tier = (platform, room), tiers, tier
        self.live[(platform, room)] = True
        try:
            roomlist.remember(self.rooms_path, platform, room)
        except OSError:
            pass
        self.auto.changed(time.monotonic())
        print(f'======== {name} ({platform} {room}) · {tier.label} ========', flush=True)
        self.chat_task = asyncio.create_task(self._chat(chat()))
        await self.send_rooms()
        await self.send_quality()
        self.switching = False
        return True

    # ---------------------------------------------------------------- an offline room, waiting for it to go live

    WAIT_EVERY = 30                                  # seconds between checks while waiting

    async def wait_for(self, platform: str, room: str, name: str):
        """Switch to an offline room: its chat runs, the video stops, and it plays by itself once it goes live."""
        if self.chat_task:
            self.chat_task.cancel()
        await self.mpv.command('stop')               # the window stays (--idle)
        await self.mpv.command('script-message', 'cnlv-danmaku-clear')
        await self.mpv.command('set_property', 'force-media-title', name)
        self.current, self.tiers, self.tier = (platform, room), [], None
        self.live[(platform, room)] = False
        print(f'======== {name} ({platform} {room}) · offline, waiting for the stream ========', flush=True)
        chat = huya.chat(room) if platform == 'huya' else douyin.chat(room)   # they look the room up themselves
        self.chat_task = asyncio.create_task(self._chat(chat))
        await self.send_rooms()
        await self.send_quality()
        self.waiting_task = asyncio.create_task(self._wait_loop(platform, room, name))

    async def _wait_loop(self, platform: str, room: str, name: str):
        while self.current == (platform, room):
            await self.mpv.show(f'○ {name} is offline\nWaiting for the stream · Tab: choose another room',
                                self.WAIT_EVERY + 5)
            await asyncio.sleep(self.WAIT_EVERY)
            try:
                status = await asyncio.to_thread(self._status, platform, room)
            except Exception:                        # noqa: BLE001 - a failed check: try again next time
                continue
            if status == 'live' and self.current == (platform, room):
                self.waiting_task = None             # play() would otherwise cancel this task, which is running it
                await self.play(platform, room)
                return

    # ---------------------------------------------------------------- quality

    async def send_quality(self):
        """The quality menu's contents, for picker.lua (right-click menu) and bar.lua (the quality button)."""
        data = {'auto': self.choice == q.AUTO, 'current': self.tier.id if self.tier else '',
                'label': self.tier.label if self.tier else '',
                'tiers': [{'id': t.id, 'label': t.label} for t in self.tiers]}
        await self.mpv.command('set_property', 'user-data/cnlv/quality', data)

    async def use_tier(self, tier, message: str, probing: bool = False):
        """Switch the playing room to another level. The chat keeps running."""
        self.switching = True
        await self.mpv.command('loadfile', tier.url, 'replace')
        self.tier = tier
        self.auto.changed(time.monotonic(), probing)
        await self.send_quality()
        await self.mpv.show(message, 3)
        print(f'-- {message}', flush=True)
        await asyncio.sleep(1)                       # the replaced stream's end-file isn't a dropped stream
        self.switching = False

    async def set_quality(self, choice: str):
        """From the menus: 'auto', or a level's id."""
        if not self.tiers:
            return
        if choice == q.AUTO:
            self.choice, self.auto.cap = q.AUTO, math.inf
            tier = self.tiers[0]
        else:
            tier = next((t for t in self.tiers if t.id == choice), None)
            if tier is None:
                return
            # a fixed level carries over to other rooms as a bitrate cap; audio only by name, where a room has it
            self.choice = tier.mbps if tier.video else tier.id
        if tier is not self.tier:
            await self.use_tier(tier, f'Quality: {tier.label}' + (' (Auto)' if self.choice == q.AUTO else ''))
        else:
            await self.send_quality()
            await self.mpv.show('Quality: Auto' if self.choice == q.AUTO else f'Quality: {tier.label}', 2)

    async def on_cache_pause(self, paused: bool):
        """mpv paused because the buffer ran dry (paused-for-cache), or resumed. Auto steps down when it keeps up."""
        if not paused:
            self.stalled_since = None
            return
        now = time.monotonic()
        self.stalled_since = now
        if self.choice == q.AUTO and self.auto.stall_started(now):
            await self.step_down()
            return
        await asyncio.sleep(q.Auto.STALL_LONG)
        if self.stalled_since == now and self.choice == q.AUTO and self.auto.stall_long(time.monotonic()):
            await self.step_down()

    async def step_down(self):
        lower = [t for t in self.tiers if t.video and self.tier and t.mbps < self.tier.mbps - 0.01]
        if not lower:
            return
        self.auto.cap = lower[0].mbps
        await self.use_tier(lower[0], f'The connection can\'t keep up: {lower[0].label} (Auto)')

    async def auto_up(self):
        """Every 30 s: after a calm stretch, Auto tries one level up."""
        while True:
            await asyncio.sleep(30)
            if self.choice != q.AUTO or not self.tier or self.switching:
                continue
            higher = [t for t in self.tiers if t.video and t.mbps > self.tier.mbps + 0.01]
            if higher and self.auto.may_step_up(time.monotonic()):
                self.auto.cap = higher[-1].mbps
                await self.use_tier(higher[-1], f'Trying {higher[-1].label} (Auto)', probing=True)

    async def reload(self, message: str):
        self.rooms = roomlist.load(self.rooms_path)
        await self.send_rooms()
        await self.mpv.show(message, 3)

    async def save_current(self):
        if not self.current:
            return
        if self.saved(*self.current):
            await self.mpv.show('Already in the room list', 2)
            return
        name = self.name_of(*self.current)
        roomlist.append(self.rooms_path, *self.current, name)
        await self.reload(f'Saved: {name}')

    async def add(self, text: str):
        try:
            platform, room = roomlist.parse_target(text.strip(), self.rooms)
        except ValueError as e:
            await self.mpv.show(f'✗ {e}', 4)
            return
        if self.saved(platform, room):
            await self.mpv.show(f'Already in the room list: {self.name_of(platform, room)}', 3)
            return
        await self.mpv.show(f'Looking up {platform} {room} …', 10)
        try:
            name = await asyncio.to_thread(streamer_name, platform, room)
        except LookupError as e:
            await self.mpv.show(f'✗ {e}', 4)
            return
        except Exception as e:                       # the name is a nicety; save the room without it
            log.warning('name lookup failed: %s', e)
            name = None
        roomlist.append(self.rooms_path, platform, room, name)
        await self.reload(f'Added: {name or f"{platform} {room}"}')
        await self.play(platform, room, wait=True)  # switch to the new room (or wait for it, if it's offline)

    async def rename(self, platform: str, room: str, name: str):
        if not self.saved(platform, room) or not name.strip():
            return
        roomlist.rename(self.rooms_path, platform, room, name)
        await self.reload(f'Renamed: {" ".join(name.split())}')
        if self.current == (platform, room):
            await self.mpv.command('set_property', 'force-media-title', self.name_of(platform, room))

    async def make_default(self, platform: str, room: str):
        if not self.saved(platform, room):
            return
        roomlist.make_default(self.rooms_path, platform, room)
        await self.reload(f'Default room: {self.name_of(platform, room)}')

    async def remove(self, platform: str, room: str):
        if not self.saved(platform, room):
            return
        name = self.name_of(platform, room)
        roomlist.remove(self.rooms_path, platform, room)
        await self.reload(f'Removed: {name}')

    async def _events(self):
        async for ev in self.mpv.events():
            name = ev.get('event')
            if name == 'client-message':
                msg, args = (ev.get('args') or [''])[0], (ev.get('args') or [])[1:]
                if msg == 'cnlv-switch' and len(args) == 2 and args[0] in roomlist.PLATFORMS:
                    asyncio.create_task(self.play(*args, wait=True))
                elif msg == 'cnlv-save':
                    asyncio.create_task(self.save_current())
                elif msg == 'cnlv-add' and len(args) == 1:
                    asyncio.create_task(self.add(args[0]))
                elif msg == 'cnlv-rename' and len(args) == 3:
                    asyncio.create_task(self.rename(*args))
                elif msg == 'cnlv-default' and len(args) == 2:
                    asyncio.create_task(self.make_default(*args))
                elif msg == 'cnlv-remove' and len(args) == 2:
                    asyncio.create_task(self.remove(*args))
                elif msg == 'cnlv-quality' and len(args) == 1:
                    asyncio.create_task(self.set_quality(args[0]))
                elif msg == 'cnlv-refresh-live':
                    asyncio.create_task(self.refresh_live())
            elif name == 'property-change' and ev.get('name') == 'paused-for-cache':
                asyncio.create_task(self.on_cache_pause(bool(ev.get('data'))))
            elif name == 'end-file' and ev.get('reason') in ('eof', 'error') and self.current and not self.switching:
                await self.mpv.show('Stream dropped, reconnecting …', 2)
                await asyncio.sleep(2)
                asyncio.create_task(self.play(*self.current, quiet=True))

    async def run(self, candidates):
        """Open the player and play the first live room among candidates ([(platform, room)], in order)."""
        await self.mpv.start()
        events = asyncio.create_task(self._events())
        await self.mpv.command('observe_property', 1, 'paused-for-cache')
        stepping_up = asyncio.create_task(self.auto_up())
        live_checks = asyncio.create_task(self.live_loop())
        try:
            await self.send_rooms()                  # before the first room, so the list is there even if it fails
            if len(candidates) > 1:
                # check them all at once (and the saved rooms, for the markers), then try live rooms first
                saved = [(r['platform'], r['room']) for r in self.rooms]
                try:
                    await asyncio.wait_for(self.refresh_live(list(dict.fromkeys(candidates + saved))), 8)
                    self.live_checked = time.monotonic()
                except asyncio.TimeoutError:
                    pass
                candidates = roomlist.live_first(candidates, self.live)
            if not candidates:
                await self.mpv.show('No rooms saved yet. Press Tab, then "Add a room…"', 30)
            if len(candidates) == 1:                 # a room asked for by name: play it, or wait for it
                await self.play(*candidates[0], wait=True)
            else:
                for i, (platform, room) in enumerate(candidates):
                    after = candidates[i + 1] if i + 1 < len(candidates) else None
                    if await self.play(platform, room, quiet=i > 0, next_room=after):
                        break
                else:
                    if candidates:                   # none is live: wait for the first (the default room)
                        await self.play(*candidates[0], wait=True)
            await asyncio.wait([events, asyncio.create_task(self.mpv.proc.wait())],
                               return_when=asyncio.FIRST_COMPLETED)
        finally:
            if self.chat_task:
                self.chat_task.cancel()
            events.cancel()
            stepping_up.cancel()
            live_checks.cancel()
            await self.mpv.close()
