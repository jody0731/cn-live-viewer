"""The saved-room list: one room per line, `platform  room  name`; the first line is the default."""
import os
import re

from . import douyin, huya

PLATFORMS = ('huya', 'douyin')
EXAMPLE = """\
# cn-live-viewer rooms: one per line as  platform  room  name
# platform is huya or douyin; room is the number in the room's address; the name is free text.
# The first room is the default when cn-live-viewer starts without a room. In the player, Tab opens this list,
# where rooms can also be added, saved, renamed and removed.
# Examples:
#   huya     333003           Some Huya room
#   douyin   286658238204     Some Douyin room
"""


def default_path() -> str:
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'cn-live-viewer', 'rooms.conf')


def ensure(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(EXAMPLE)


def load(path: str) -> list:
    rooms = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(None, 2)
                if len(parts) >= 2 and parts[0] in PLATFORMS:
                    rooms.append({'platform': parts[0], 'room': parts[1],
                                  'name': parts[2] if len(parts) > 2 else f'{parts[0]} {parts[1]}'})
    except FileNotFoundError:
        pass
    return rooms


def line(platform: str, room: str, name: str = None) -> str:
    name = ' '.join((name or '').split()) or f'{platform} {room}'
    return f'{platform:<8} {room:<16} {name}\n'


def append(path: str, platform: str, room: str, name: str = None) -> None:
    ensure(path)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(line(platform, room, name))


def _rewrite(path: str, platform: str, room: str, new_line: str = None) -> None:
    """Replace (or with new_line None, drop) the room's line; comments and the other lines stay as they are."""
    with open(path, encoding='utf-8') as f:
        lines = f.readlines()
    out = []
    for old in lines:
        if not old.lstrip().startswith('#') and old.split(None, 2)[:2] == [platform, room]:
            if new_line:
                out.append(new_line)
            continue
        out.append(old)
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.writelines(out)
    os.replace(tmp, path)


def rename(path: str, platform: str, room: str, name: str) -> None:
    _rewrite(path, platform, room, line(platform, room, name))


def remove(path: str, platform: str, room: str) -> None:
    _rewrite(path, platform, room)


def parse_target(arg: str, rooms: list):
    """A room number or link -> (platform, room). Bare numbers are Huya unless saved as a Douyin room."""
    if 'douyin.com' in arg:
        return 'douyin', douyin.room_id(arg)
    if 'huya.com' in arg:
        return 'huya', huya.room_id(arg)
    if not re.fullmatch(r'[\w-]+', arg):
        raise ValueError(f'not a Huya/Douyin room number or link: {arg}')
    for r in rooms:
        if r['room'] == arg:
            return r['platform'], arg
    return 'huya', arg
