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
SCRIPTS = [os.path.join(os.path.dirname(__file__), 'mpv', n) for n in ('danmaku.lua', 'picker.lua')]
# smooth 60 fps on high-refresh monitors, sharper upscaling, GPU decoding, a maximized (not fullscreen) window;
# your own mpv.conf still applies, and --mpv-args overrides these
DEFAULT_MPV_ARGS = ['--profile=high-quality', '--hwdec=auto-safe', '--video-sync=display-resample',
                    '--interpolation', '--tscale=oversample', '--window-maximized=yes']
COLORS = ['\033[96m', '\033[93m', '\033[92m', '\033[95m', '\033[94m', '\033[91m']


def print_chat(nick: str, text: str, color: bool) -> None:
    if color:
        c = COLORS[zlib.crc32(nick.encode()) % len(COLORS)]
        print(f'{c}{nick}\033[0m: {text}', flush=True)
    else:
        print(f'{nick}: {text}', flush=True)


async def resolve(platform: str, room: str, quality: str = None):
    """-> (stream url, referer, chat async generator)"""
    if platform == 'huya':
        ratio = int(quality) if quality and quality.isdigit() else huya.DEFAULT_RATIO
        url, uid = await asyncio.to_thread(huya.stream_url, room, ratio)
        return url, huya.REFERER, huya.chat(room, uid)
    q = quality if quality in douyin.QUALITIES else 'origin'
    url, internal = await asyncio.to_thread(douyin.stream_url, room, q)
    return url, douyin.REFERER, douyin.chat(room, internal)


class Player:
    def __init__(self, rooms_path: str, quality: str = None, overlay: bool = True, mpv_args=None):
        self.rooms_path, self.quality, self.overlay = rooms_path, quality, overlay
        self.rooms = roomlist.load(rooms_path)
        self.mpv = Mpv(SCRIPTS, DEFAULT_MPV_ARGS + list(mpv_args or []))
        self.current = None
        self.chat_task = None
        self.switching = False
        self.color = sys.stdout.isatty()

    def name_of(self, platform, room):
        for r in self.rooms:
            if (r['platform'], r['room']) == (platform, room):
                return r['name']
        return f'{platform} {room}'

    async def send_rooms(self):
        data = [dict(r, current=(r['platform'], r['room']) == self.current) for r in self.rooms]
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
            url, referer, chat = await resolve(platform, room, self.quality)
        except Exception as e:
            await self.mpv.show(f'✗ {e}', 4)
            print(f'-- {e}', file=sys.stderr, flush=True)
            self.switching = False
            return False
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

    async def save_current(self):
        if not self.current:
            return
        if any((r['platform'], r['room']) == self.current for r in self.rooms):
            await self.mpv.show('Already in the room list', 2)
            return
        roomlist.append(self.rooms_path, *self.current)
        self.rooms = roomlist.load(self.rooms_path)
        await self.send_rooms()
        await self.mpv.show(f'Saved. Rename it in {self.rooms_path}', 3)

    async def _events(self):
        async for ev in self.mpv.events():
            name = ev.get('event')
            if name == 'client-message':
                args = ev.get('args') or []
                if args[:1] == ['cnlv-switch'] and len(args) > 1 and args[1].isdigit():
                    i = int(args[1]) - 1
                    if 0 <= i < len(self.rooms):
                        r = self.rooms[i]
                        asyncio.create_task(self.play(r['platform'], r['room']))
                elif args[:1] == ['cnlv-save']:
                    asyncio.create_task(self.save_current())
                elif args[:1] == ['cnlv-ready']:
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
