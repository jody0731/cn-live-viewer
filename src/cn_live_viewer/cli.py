"""Command line: cn-live-viewer [room] | chat <room> | url <room> | rooms"""
import argparse
import asyncio
import logging
import os
import shlex
import sys

from . import __version__, douyin, huya, rooms as roomlist
from .player import Player, print_chat

USAGE = """\
cn-live-viewer [options] [ROOM]        watch a room in mpv (default: the first saved room)
cn-live-viewer chat ROOM               print a room's live chat in the terminal
cn-live-viewer url  ROOM               print the stream address (for another player)
cn-live-viewer rooms                   list saved rooms and where the list is

ROOM is a Huya or Douyin room number or link. Bare numbers are Huya rooms unless saved as Douyin.
In mpv:  Tab  room list: Enter switches; the entries after the rooms add, save, rename or remove rooms
         C    chat overlay on/off
         mouse: the bar at the bottom (click the room name for the room list), right-click for a menu
"""


def main(argv=None):
    p = argparse.ArgumentParser(prog='cn-live-viewer', usage=USAGE, add_help=True)
    p.add_argument('words', nargs='*', help=argparse.SUPPRESS)
    p.add_argument('-q', '--quality', help='Huya: bitrate in kbps (default 20000); Douyin: origin/hd/sd/ld/md')
    p.add_argument('--no-overlay', action='store_true', help='no chat over the video (chat still prints here)')
    p.add_argument('--rooms', default=roomlist.default_path(), help='room list file (default: %(default)s)')
    p.add_argument('--mpv-args', default='', help='extra mpv options as one argument, e.g. --mpv-args="--volume=70 --fs"')
    p.add_argument('-v', '--verbose', action='store_true', help='log connection details')
    p.add_argument('-V', '--version', action='version', version=f'cn-live-viewer {__version__}')
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format='-- %(message)s')

    roomlist.ensure(a.rooms)
    rooms = roomlist.load(a.rooms)
    words = a.words
    cmd = words[0] if words and words[0] in ('chat', 'url', 'rooms') else None

    if cmd == 'rooms':
        print(f'# {a.rooms}')
        for r in rooms:
            print(f"{r['platform']:<8} {r['room']:<16} {r['name']}")
        return 0

    target = (words[1] if cmd and len(words) > 1 else None) if cmd else (words[0] if words else None)
    if target is None:
        if cmd or not rooms:
            p.print_usage()
            print(f'\nNo room given and none saved yet: add rooms to {a.rooms}', file=sys.stderr)
            return 2
        platform, room = rooms[0]['platform'], rooms[0]['room']
    else:
        try:
            platform, room = roomlist.parse_target(target, rooms)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2

    try:
        if cmd == 'url':
            if platform == 'huya':
                url = huya.stream_url(room, int(a.quality) if (a.quality or '').isdigit() else huya.DEFAULT_RATIO)[0]
            else:
                url = douyin.stream_url(room, a.quality or 'origin')[0]
            print(url)
            return 0
        if cmd == 'chat':
            async def chat_only():
                gen = huya.chat(room) if platform == 'huya' else douyin.chat(room)
                async for nick, text in gen:
                    print_chat(nick, text, sys.stdout.isatty())
            asyncio.run(chat_only())
            return 0
        player = Player(a.rooms, a.quality, overlay=not a.no_overlay, mpv_args=shlex.split(a.mpv_args))
        asyncio.run(player.run(platform, room))
        return 0
    except LookupError as e:
        print(e, file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        if 'mpv' in str(e):
            print('mpv is not installed (Debian/Ubuntu: sudo apt install mpv)', file=sys.stderr)
            return 1
        raise
    except BrokenPipeError:                      # output piped into a command that stopped reading, e.g. head
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
