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

from . import douyin, hardware, huya, quality as q, rooms as roomlist, settings
from .mpv import WINDOWS, Mpv, find_mpv

log = logging.getLogger(__name__)
SCRIPTS = [os.path.join(os.path.dirname(__file__), 'mpv', n) for n in ('danmaku.lua', 'picker.lua', 'bar.lua')]
PROFILES_FILE = os.path.join(os.path.dirname(__file__), 'mpv', 'cnlv.conf')
PROFILES = {'efficient': 'cnlv-efficient', 'high': 'cnlv-high-quality'}   # the Video Decoder's modes, in PROFILES_FILE
# hardware decoding (the video chip uses far less power than decoding on the CPU), the window, volume and mute kept
# from the last start (window_args), a bigger rewind buffer for the seek bar (512 MiB: about 3.5 minutes at 20 Mbps, used only as it fills),
# and the Video Decoder's modes; your own mpv.conf still applies, and --mpv-args overrides these
DEFAULT_MPV_ARGS = ['--hwdec=auto-safe', '--demuxer-max-back-bytes=512MiB',
                    f'--include={PROFILES_FILE}']
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


WINDOW_PROPS = ('fullscreen', 'window-maximized', 'osd-dimensions', 'display-width', 'display-height')


def window_args(w: dict) -> list:
    """mpv options for the window as it was last time (settings.window): fullscreen, maximized (the first start), or
    the size it had, as a share of the screen so it's the same on any screen scale."""
    args = [f'--window-maximized={"yes" if w["maximized"] else "no"}']
    if w['size']:
        args.append(f'--geometry={w["size"][0]:g}%x{w["size"][1]:g}%')
    if w['fullscreen']:
        args.append('--fullscreen=yes')
    return args


def window_state(props: dict, before: dict) -> dict:
    """The window settings from mpv's properties; the size only from a window that is neither fullscreen nor
    maximized (else the last such size stays)."""
    w = dict(before, fullscreen=bool(props.get('fullscreen')), maximized=bool(props.get('window-maximized')))
    osd, dw, dh = props.get('osd-dimensions') or {}, props.get('display-width'), props.get('display-height')
    if not w['fullscreen'] and not w['maximized'] and osd.get('w') and osd.get('h') and dw and dh:
        size = [round(min(100, max(10, 100 * osd['w'] / dw)), 1), round(min(100, max(10, 100 * osd['h'] / dh)), 1)]
        w['size'] = size
    return w


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
        self.auto = q.Auto()
        self.flow, self.resynced = q.Flow(), -math.inf   # how the stream arrives and plays; the last re-sync
        self.tiers, self.tier = [], None             # the current room's levels and the one playing
        self.stalled_since = None
        self.live = {}                               # (platform, room) -> True/False: online markers in the room lists
        self.live_checked = -math.inf
        self.douyin_session, self.douyin_lock = None, threading.Lock()
        self.waiting_task = None                     # waiting for an offline room to go live
        self.rooms = roomlist.load(rooms_path)
        self.config_dir = os.path.dirname(os.path.abspath(rooms_path))
        saved = settings.load(self.config_dir)
        self.decoder = saved['decoder']              # Auto, Efficient or High quality
        # AUTO, a cap in Mbps, or a Douyin quality name: -q for this start only, else the last one chosen in the player
        self.choice = q.parse(quality if quality is not None else saved['quality'])
        self.chat_on = saved['chat']
        self.kept = {k: saved[k] for k in ('volume', 'mute', 'chat', 'window')}   # as last saved: save only changes
        self.window_props = {}                       # mpv's window properties, as they change
        self.pending, self.save_task = {}, None
        try:
            gpus = hardware.known_gpus(self.config_dir, find_mpv())
        except FileNotFoundError:                    # Mpv.start() says so
            gpus = []
        self.gpus = gpus
        self.gpu_for = dict(zip(('efficient', 'high'), hardware.split(gpus)))   # chips per mode, if there are two
        self.mode, self.mode_why = self.resolve(self.decoder)
        self.vo_alt = False                          # see use_mode()
        kept = [f'--volume={saved["volume"]:g}', f'--mute={"yes" if saved["mute"] else "no"}'] + window_args(saved['window'])
        # the window keeps its size when a room or level starts (mpv would size it to each video)
        self.mpv = Mpv(SCRIPTS, DEFAULT_MPV_ARGS + kept + self.mode_args(self.mode) + list(mpv_args or []),
                       optional_args=['--auto-window-resize=no'])
        self.current = None
        self.names = {}                              # (platform, room) -> streamer name, for rooms not saved yet
        self.chat_task = None
        self.switching = False
        self.gen = 0                                 # counts loads: a room lookup overtaken by a newer choice gives up
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
        self.gen += 1
        gen = self.gen
        name = self.name_of(platform, room)
        if not quiet:
            await self.mpv.show(f'→ {name} …', 2)
        try:
            tiers, referer, chat, streamer = await asyncio.to_thread(levels, platform, room)
            tier = q.pick(tiers, self.choice, self.auto.cap)
        except Exception as e:
            if gen != self.gen:                      # another room or level was chosen meanwhile
                return True
            if wait and isinstance(e, LookupError):
                try:
                    status = await asyncio.to_thread(self._status, platform, room)
                except Exception:                    # noqa: BLE001 - can't tell: assume offline, keep waiting
                    status = 'offline'
                if gen != self.gen:
                    return True
                if status != 'missing':
                    await self.wait_for(platform, room, name)
                    if gen == self.gen:
                        self.switching = False
                    return True
            hint = f'Trying {self.name_of(*next_room)} …' if next_room else 'Tab: choose another room'
            await self.mpv.show(f'✗ {e}\n{hint}', 3 if next_room else 6)
            print(f'-- {e}', file=sys.stderr, flush=True)
            if gen == self.gen:
                self.switching = False
            return False
        if gen != self.gen:                          # chosen again meanwhile: the newer choice plays, not this one
            return True
        if streamer:
            self.names[(platform, room)] = streamer
            name = self.name_of(platform, room)
        if self.chat_task:
            self.chat_task.cancel()
        await self.mpv.command('script-message', 'cnlv-danmaku-clear')
        await self.mpv.command('set_property', 'http-header-fields', [f'Referer: {referer}'])
        await self.mpv.command('set_property', 'force-media-title', name)
        await self.mpv.command('loadfile', tier.url, 'replace')
        self.flow.reset()
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
        if gen == self.gen:
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
        self.gen += 1
        gen = self.gen
        await self.mpv.command('loadfile', tier.url, 'replace')
        self.flow.reset()
        self.tier = tier
        self.auto.changed(time.monotonic(), probing)
        await self.send_quality()
        await self.mpv.show(message, 3)
        print(f'-- {message}', flush=True)
        await asyncio.sleep(1)                       # the replaced stream's end-file isn't a dropped stream
        if gen == self.gen:
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
        self.save(quality=self.choice if isinstance(self.choice, str) else f'{self.choice:g}')
        if tier is not self.tier:
            await self.use_tier(tier, f'Quality: {tier.label}' + (' (Auto)' if self.choice == q.AUTO else ''))
        else:
            await self.send_quality()
            await self.mpv.show('Quality: Auto' if self.choice == q.AUTO else f'Quality: {tier.label}', 2)

    def connection_behind(self) -> bool:
        """Is an empty buffer the connection's fault? Not when the stream kept arriving in real time: then playback
        ran ahead (see quality.Flow), and a lower level wouldn't help."""
        if self.flow.arriving_in_time():
            print('-- The buffer ran dry, but the stream arrives in time: quality kept', flush=True)
            return False
        return True

    async def on_cache_pause(self, paused: bool):
        """mpv paused because the buffer ran dry (paused-for-cache), or resumed. Auto steps down when it keeps up,
        and the connection is what can't keep up."""
        if not paused:
            self.stalled_since = None
            return
        now = time.monotonic()
        self.stalled_since = now
        if self.choice != q.AUTO or not self.connection_behind():
            return
        if self.auto.stall_started(now):
            await self.step_down()
            return
        await asyncio.sleep(q.Auto.STALL_LONG)
        if (self.stalled_since == now and self.choice == q.AUTO and self.auto.stall_long(time.monotonic())
                and self.connection_behind()):
            await self.step_down()

    async def step_down(self):
        lower = [t for t in self.tiers if t.video and self.tier and t.mbps < self.tier.mbps - 0.01]
        if not lower:
            return
        self.auto.cap = lower[0].mbps
        await self.use_tier(lower[0], f'The connection can\'t keep up: {lower[0].label} (Auto)')

    async def watch_flow(self):
        """Once a second: how the stream arrives and plays (quality.Flow). A picture racing ahead of the sound, or
        drifting apart from it, is put back in step by a seek to where it is (mpv restarts both together)."""
        while True:
            await asyncio.sleep(1)
            if not self.tier or self.switching:
                self.flow.reset()
                continue
            gen = self.gen
            cache = await self.mpv.get('demuxer-cache-state') or {}
            pos, speed, avsync = [await self.mpv.get(n) for n in ('time-pos', 'speed', 'avsync')]
            stopped = await self.mpv.get('pause') or await self.mpv.get('paused-for-cache')
            if gen != self.gen:                      # a switch happened while we asked
                continue
            now = time.monotonic()
            self.flow.sample(now, cache.get('cache-end'), pos, not stopped and speed == 1, avsync)
            if self.flow.out_of_step() and now - self.resynced > 10:
                self.resynced = now
                self.flow.restart_play()
                await self.mpv.command('seek', 0, 'relative+exact')
                print('-- Picture and sound out of step: re-synced', flush=True)

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

    # ---------------------------------------------------------------- the Video Decoder

    def resolve(self, decoder: str) -> tuple:
        """-> (mode, why): a fixed mode as it is; Auto from the power source, the load and the graphics chips."""
        if decoder != 'auto':
            return decoder, 'chosen'
        return hardware.auto_mode(self.gpus, hardware.on_battery(), hardware.cpu_busy())

    def mode_args(self, mode: str) -> list:
        args = [f'--profile={PROFILES[mode]}']
        args += [f'--{k}={v}' for k, v in hardware.gpu_options(self.gpu_for.get(mode)).items()]
        if self.gpu_for.get(mode) and not WINDOWS:
            args.append('--vo=gpu-next')             # see use_mode()
        return args

    async def send_decoder(self):
        gpu = lambda m: self.gpu_for[m].name if self.gpu_for.get(m) else None
        await self.mpv.command('set_property', 'user-data/cnlv/decoder',
                               {'choice': self.decoder, 'mode': self.mode, 'why': self.mode_why,
                                'gpus': {'efficient': gpu('efficient'), 'high': gpu('high')}})

    async def use_mode(self, mode: str):
        """Switch mpv to a mode: its profile, and on a computer with two graphics chips, that mode's chip."""
        before, self.mode = self.gpu_for.get(self.mode), mode
        await self.mpv.command('apply-profile', PROFILES[mode])
        chip = self.gpu_for.get(mode)
        if chip != before:
            for k, v in hardware.gpu_options(chip).items():
                await self.mpv.command('set_property', k, v)
            # Windows: mpv rebuilds its video output by itself when d3d11-adapter changes. Vulkan's device isn't
            # read again until the output is rebuilt, which setting vo does, but only to a different value (mpv
            # ignores a write of the same one): so it alternates between two lists that both mean gpu-next.
            if not WINDOWS:
                self.vo_alt = not self.vo_alt
                await self.mpv.command('set_property', 'vo', 'gpu-next,gpu' if self.vo_alt else 'gpu-next')
        await self.send_decoder()

    async def set_decoder(self, decoder: str):
        """From the right-click menu: 'auto', 'efficient' or 'high'. Takes effect at once, and is kept for the next
        start."""
        if decoder not in settings.DECODERS:
            return
        self.decoder = decoder
        mode, self.mode_why = await asyncio.to_thread(self.resolve, decoder)
        await self.use_mode(mode)
        chip = self.gpu_for.get(mode)
        text = f'Video Decoder: {settings.DECODERS[decoder]}'
        if decoder == 'auto':
            text += f' · {settings.MODES[mode]} ({self.mode_why})'
        await self.mpv.show(text + (f'\n{chip.name}' if chip else ''), 3)
        self.save(decoder=decoder)

    def save(self, **changes):
        try:
            settings.save(self.config_dir, **changes)
        except OSError as e:
            log.warning('could not save the settings: %s', e)

    def on_setting(self, name: str, value):
        """Volume, mute, the chat overlay or the window changed in the player: kept for the next start, once it
        settles (a scroll on the volume, or dragging the window's edge, sends many changes)."""
        if name in WINDOW_PROPS:
            self.window_props[name] = value
            self.pending['window'] = None            # worked out when it settles: see flush()
            if self.save_task is None or self.save_task.done():
                self.save_task = asyncio.create_task(self._save_later())
            return
        key = {'volume': 'volume', 'mute': 'mute', 'user-data/cnlv/chat': 'chat'}[name]
        if value is None or (key == 'volume') == isinstance(value, bool):
            return
        self.pending[key] = round(value) if key == 'volume' else value
        if self.save_task is None or self.save_task.done():
            self.save_task = asyncio.create_task(self._save_later())

    async def _save_later(self):
        await asyncio.sleep(1)
        self.flush()

    def flush(self):
        if 'window' in self.pending:
            self.pending['window'] = window_state(self.window_props, self.kept['window'])
        changed = {k: v for k, v in self.pending.items() if self.kept.get(k) != v}
        self.pending = {}
        if changed:
            self.kept.update(changed)
            self.save(**changed)

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
                elif msg == 'cnlv-decoder' and len(args) == 1:
                    asyncio.create_task(self.set_decoder(args[0]))
                elif msg == 'cnlv-refresh-live':
                    asyncio.create_task(self.refresh_live())
            elif name in ('seek', 'playback-restart'):
                self.flow.restart_play()            # a jump in the position isn't playing fast
            elif name == 'property-change' and ev.get('name') in ('volume', 'mute', 'user-data/cnlv/chat') + WINDOW_PROPS:
                self.on_setting(ev['name'], ev.get('data'))
            elif name == 'property-change' and ev.get('name') == 'paused-for-cache':
                asyncio.create_task(self.on_cache_pause(bool(ev.get('data'))))
            elif name == 'end-file' and ev.get('reason') in ('eof', 'error') and self.current and not self.switching:
                await self.mpv.show('Stream dropped, reconnecting …', 2)
                await asyncio.sleep(2)
                asyncio.create_task(self.play(*self.current, quiet=True))

    async def windows_taskbar(self):
        """Windows: the taskbar button is cn-live-viewer's, so "new window" opens another cn-live-viewer (desktop.py)."""
        from . import desktop
        for _ in range(20):                          # the window appears shortly after mpv starts
            hwnd = await self.mpv.get('window-id')
            if hwnd:
                try:
                    await asyncio.to_thread(desktop.windows_relaunch, int(hwnd), find_mpv())
                except Exception as e:               # noqa: BLE001 - the window still works, under mpv's button
                    log.warning('taskbar button: %s', e)
                return
            await asyncio.sleep(0.5)

    async def run(self, candidates):
        """Open the player and play the first live room among candidates ([(platform, room)], in order)."""
        await self.mpv.start()
        events = asyncio.create_task(self._events())
        if WINDOWS:
            asyncio.create_task(self.windows_taskbar())
        await self.mpv.command('observe_property', 1, 'paused-for-cache')
        if not self.chat_on:                         # off at the last start: off again (before the first message)
            await self.mpv.command('set_property', 'user-data/cnlv/chat', False)
        for i, prop in enumerate(('volume', 'mute', 'user-data/cnlv/chat') + WINDOW_PROPS, 2):
            await self.mpv.command('observe_property', i, prop)
        stepping_up = asyncio.create_task(self.auto_up())
        watching = asyncio.create_task(self.watch_flow())
        live_checks = asyncio.create_task(self.live_loop())
        try:
            await self.send_decoder()
            chip = self.gpu_for.get(self.mode)
            print(f'-- Video Decoder: {settings.DECODERS[self.decoder]} · {settings.MODES[self.mode]} ({self.mode_why})'
                  + (f' on {chip.name}' if chip else ''), flush=True)
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
            watching.cancel()
            live_checks.cancel()
            self.flush()                             # a change in the last second before quitting
            await self.mpv.close()
