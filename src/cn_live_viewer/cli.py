"""Command line: cn-live-viewer [room] | chat <room> | url <room> | rooms | desktop [remove] | check"""
import argparse
import asyncio
import logging
import os
import shlex
import subprocess
import sys

from . import __version__, check, desktop, douyin, huya, quality, rooms as roomlist
from .player import Player, print_chat

USAGE = """\
cn-live-viewer [options] [ROOM]        watch a room in mpv (default: the first saved room)
cn-live-viewer chat ROOM               print a room's live chat in the terminal
cn-live-viewer url  ROOM               print the stream address (for another player)
cn-live-viewer rooms                   list saved rooms and where the list is
cn-live-viewer desktop [remove]        add again (or remove) the app launcher; it's added on the first start
cn-live-viewer check                   check that mpv and everything else it needs is in place

ROOM is a Huya or Douyin room number or link. Bare numbers are Huya rooms unless saved as Douyin.
In mpv:  Tab  room list: Enter switches; the entries after the rooms add, save, rename or remove rooms
         C    chat overlay on/off
         mouse: the bar at the bottom (click the room name for the room list), right-click for a menu
"""


MPV_HINTS = {
    'darwin': 'brew install mpv',
    'win32': 'see https://mpv.io/installation/ (e.g. scoop install extras/mpv, or choco install mpv)',
}


def setup_console() -> None:
    """Make printing safe everywhere: started from a launcher on Windows there is no console at all, and a pipe
    or a file may not take Chinese text in the system's encoding."""
    for name in ('stdout', 'stderr'):
        stream = getattr(sys, name)
        if stream is None:
            setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))
        elif hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')
    if os.name == 'nt' and sys.stdout.isatty():
        os.system('')                                # turns on colour codes in the Windows console


def main(argv=None):
    setup_console()
    p = argparse.ArgumentParser(prog='cn-live-viewer', usage=USAGE, add_help=True)
    p.add_argument('words', nargs='*', help=argparse.SUPPRESS)
    p.add_argument('-q', '--quality', default=None,
                   help='auto (the best the connection keeps up with), a bitrate cap in Mbps (e.g. 8), '
                        'or for Douyin origin/hd/sd/ld/md; default: the last one chosen in the player, else auto')
    p.add_argument('--no-overlay', action='store_true', help='no chat over the video (chat still prints here)')
    p.add_argument('--rooms', default=roomlist.default_path(), help='room list file (default: %(default)s)')
    p.add_argument('--mpv-args', default='', help='extra mpv options as one argument, e.g. --mpv-args="--fs"')
    p.add_argument('-v', '--verbose', action='store_true', help='log connection details')
    p.add_argument('-V', '--version', action='version', version=f'cn-live-viewer {__version__}')
    p.add_argument('--launcher', action='store_true', help=argparse.SUPPRESS)   # started from the app launcher
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format='-- %(message)s')

    roomlist.ensure(a.rooms)
    rooms = roomlist.load(a.rooms)
    words = a.words
    cmd = words[0] if words and words[0] in ('chat', 'url', 'rooms', 'desktop', 'check') else None

    if cmd == 'check':
        return check.run(a.rooms)

    if cmd == 'desktop':
        config_dir = os.path.dirname(os.path.abspath(a.rooms))
        if words[1:2] == ['remove']:
            print('App launcher removed' if desktop.remove() else 'There was no app launcher to remove')
            desktop.mark(config_dir, 'removed')      # so it isn't added back on the next start
            return 0
        try:
            where = desktop.install()
            desktop.mark(config_dir, 'added')
        except (OSError, subprocess.CalledProcessError) as e:
            print(f'Could not add the app launcher: {e}', file=sys.stderr)
            return 1
        place = {'win32': 'the Start menu', 'darwin': 'Launchpad and Spotlight'}.get(sys.platform, 'your app menu')
        print(f'App launcher added: {where}\nFind "CN Live Viewer" in {place}.')
        return 0

    if cmd == 'rooms':
        print(f'# {a.rooms}')
        for r in rooms:
            print(f"{r['platform']:<8} {r['room']:<16} {r['name']}")
        return 0

    target = (words[1] if cmd and len(words) > 1 else None) if cmd else (words[0] if words else None)
    if target is None:
        if cmd or (not rooms and not a.launcher):
            p.print_usage()
            print(f'\nNo room given and none saved yet: add rooms to {a.rooms}', file=sys.stderr)
            return 2
        # the default room; if it's offline, the rooms watched lately, then the rest of the list (see start_order).
        # From the launcher with no rooms saved, the player opens anyway, ready to add one (there's no terminal).
        candidates = roomlist.start_order(rooms, roomlist.load_recent(a.rooms))
        platform, room = candidates[0] if candidates else (None, None)
    else:
        try:
            platform, room = roomlist.parse_target(target, rooms)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        candidates = [(platform, room)]              # a room asked for by name: just that one

    try:
        if cmd == 'url':
            tiers = (huya.streams(room) if platform == 'huya' else douyin.streams(room))[0]
            print(quality.pick(tiers, quality.parse(a.quality)).url)
            return 0
        if cmd == 'chat':
            async def chat_only():
                gen = huya.chat(room) if platform == 'huya' else douyin.chat(room)
                async for nick, text in gen:
                    print_chat(nick, text, sys.stdout.isatty())
            asyncio.run(chat_only())
            return 0
        desktop.ensure(os.path.dirname(os.path.abspath(a.rooms)))   # the app launcher, the first time
        player = Player(a.rooms, a.quality, overlay=not a.no_overlay, mpv_args=shlex.split(a.mpv_args))
        asyncio.run(player.run(candidates))
        return 0
    except LookupError as e:
        print(e, file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        if 'mpv' in str(e):
            hint = MPV_HINTS.get(sys.platform, 'e.g. sudo apt install mpv, sudo dnf install mpv or sudo pacman -S mpv')
            print(f'mpv is not installed ({hint})', file=sys.stderr)
            return 1
        raise
    except BrokenPipeError:                      # output piped into a command that stopped reading, e.g. head
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
