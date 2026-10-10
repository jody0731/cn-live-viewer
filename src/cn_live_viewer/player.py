"""The player: one mpv window, the current room's stream and chat, and switching rooms from inside mpv."""
import asyncio
import json
import logging
import os
import sys
import zlib

from . import douyin, huya, rooms as roomlist
from .mpv import Mpv

log = logging.getLogger(__name__)
SCRIPTS = [os.path.join(os.path.dirname(__file__), 'mpv', n) for n in ('danmaku.lua', 'picker.lua', 'bar.lua')]
# smooth 60 fps on high-refresh monitors, sharper upscaling, GPU decoding, a maximized (not fullscreen) window,
# and a bigger rewind buffer for the seek bar (512 MiB: about 3.5 minutes at 20 Mbps, used only as it fills);
# your own mpv.conf still applies, and --mpv-args overrides these
DEFAULT_MPV_ARGS = ['--profile=high-quality', '--hwdec=auto-safe', '--video-sync=display-resample',
                    '--interpolation', '--tscale=oversample', '--window-maximized=yes', '--demuxer-max-back-bytes=512MiB']
COLORS = ['\033[96m', '\033[93m', '\033[92m', '\033[95m', '\033[94m', '\033[91m']


def print_chat(nick: str, text: str, color: bool) -> None:
    if color:
        c = COLORS[zlib.crc32(nick.encode()) % len(COLORS)]
        print(f'{c}{nick}\033[0m: {text}', flush=True)
    else:
        print(f'{nick}: {text}', flush=True)


async def resolve(platform: str, room: str, quality: str = None):
    """-> (stream url, referer, chat async generator, streamer name or None)"""
    if platform == 'huya':
        ratio = int(quality) if quality and quality.isdigit() else huya.DEFAULT_RATIO
        url, uid, name = await asyncio.to_thread(huya.stream_url, room, ratio)
        return url, huya.REFERER, huya.chat(room, uid), name
    q = quality if quality in douyin.QUALITIES else 'origin'
    url, internal, name = await asyncio.to_thread(douyin.stream_url, room, q)
    return url, douyin.REFERER, douyin.chat(room, internal), name


def streamer_name(platform: str, room: str):
    """The streamer's name (a network lookup). Raises LookupError for an unknown room."""
    return huya.room_info(room)[1] if platform == 'huya' else douyin.streamer_name(room)


class Player:
    def __init__(self, rooms_path: str, quality: str = None, overlay: bool = True, mpv_args=None):
        self.rooms_path, self.quality, self.overlay = rooms_path, quality, overlay
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

    async def send_rooms(self):
        data = {'playing': self.current is not None,
                'rooms': [dict(r, current=(r['platform'], r['room']) == self.current) for r in self.rooms]}
        await self.mpv.command('script-message', 'cnlv-rooms', json.dumps(data, ensure_ascii=False))

    async def _chat(self, gen):
        try:
            async for nick, text in gen:
                print_chat(nick, text, self.color)
                if self.overlay:
                    await self.mpv.command('script-message', 'cnlv-danmaku', text)
        except asyncio.CancelledError:
            raise
        except Exception as e:                       # chat is best effort; the video keeps playing
            log.warning('chat stopped: %s', e)

    async def play(self, platform: str, room: str, quiet: bool = False) -> bool:
        self.switching = True
        name = self.name_of(platform, room)
        if not quiet:
            await self.mpv.show(f'→ {name} …', 2)
        try:
            url, referer, chat, streamer = await resolve(platform, room, self.quality)
        except Exception as e:
            await self.mpv.show(f'✗ {e}', 4)
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
        await self.mpv.command('loadfile', url, 'replace')
        self.current = (platform, room)
        print(f'======== {name} ({platform} {room}) ========', flush=True)
        self.chat_task = asyncio.create_task(self._chat(chat))
        await self.send_rooms()
        self.switching = False
        return True

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
                    asyncio.create_task(self.play(*args))
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
                elif msg == 'cnlv-ready':
                    await self.send_rooms()
            elif name == 'end-file' and ev.get('reason') in ('eof', 'error') and self.current and not self.switching:
                await self.mpv.show('Stream dropped, reconnecting …', 2)
                await asyncio.sleep(2)
                asyncio.create_task(self.play(*self.current, quiet=True))

    async def run(self, platform: str, room: str):
        await self.mpv.start()
        events = asyncio.create_task(self._events())
        try:
            await self.play(platform, room)
            await asyncio.wait([events, asyncio.create_task(self.mpv.proc.wait())],
                               return_when=asyncio.FIRST_COMPLETED)
        finally:
            if self.chat_task:
                self.chat_task.cancel()
            events.cancel()
            await self.mpv.close()
