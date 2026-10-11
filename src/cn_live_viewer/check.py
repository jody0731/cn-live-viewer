"""cn-live-viewer check: is everything it needs in place? The install scripts run it last."""
import os
import re
import shutil
import subprocess
import sys

from . import __version__, desktop, settings
from .mpv import find_mpv

MIN_MPV = (0, 39)          # the room list and the quality list (mp.input); older mpv plays, without them
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)   # Windows: no console flashing up


def mpv_version(mpv: str):
    """(major, minor) of this mpv, or None when it can't tell."""
    try:
        out = subprocess.run([mpv, '--no-config', '--version'], capture_output=True, text=True, errors='replace',
                             timeout=20, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'\bmpv v?(\d+)\.(\d+)', out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def chinese_font():
    """Whether there is a Simplified Chinese font for the chat: True/False on Linux, None elsewhere (macOS and
    Windows come with one) or when fontconfig isn't there to ask."""
    if not sys.platform.startswith('linux') or not shutil.which('fc-list'):
        return None
    try:
        out = subprocess.run(['fc-list', ':lang=zh-cn', 'family'], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(out.strip())


def run(rooms_path: str) -> int:
    """Print what's in place and what's missing. 0 when it's ready to play, 1 when something it needs is missing."""
    ready = True
    print(f'cn-live-viewer {__version__}, Python {sys.version.split()[0]} ({sys.executable})')
    try:
        import streamlink
        import websockets
        print(f'  ok       Streamlink {streamlink.__version__}, websockets {websockets.__version__}')
    except ImportError as e:
        ready = False
        print(f'  MISSING  {e.name}: install cn-live-viewer again')
    try:
        mpv = find_mpv()
    except FileNotFoundError:
        ready = False
        print('  MISSING  mpv: install it (the install script does, or see https://mpv.io/installation/)')
    else:
        version = mpv_version(mpv)
        shown = '.'.join(map(str, version)) if version else 'version unknown'
        if version and version < MIN_MPV:
            print(f'  old      mpv {shown} at {mpv}: it plays, but the room list and the quality list need '
                  f'mpv {".".join(map(str, MIN_MPV))} or newer')
        else:
            print(f'  ok       mpv {shown} at {mpv}')
    font = chinese_font()
    if font is False:
        print('  MISSING  a Simplified Chinese font: chat shows boxes (e.g. sudo apt install fonts-noto-cjk)')
    elif font:
        print('  ok       a Simplified Chinese font for the chat')
    config_dir = os.path.dirname(os.path.abspath(rooms_path))
    picture = settings.load(config_dir)['picture']
    print(f'  ok       picture: {settings.PICTURES[picture]} (right-click, Picture, to change)')
    print(f'  ok       room list: {rooms_path}')
    launcher = desktop.path()
    print(f'  {"ok      " if os.path.exists(launcher) else "none    "} app launcher: {launcher}')
    print('Ready to play.' if ready else 'Not ready: see MISSING above.')
    return 0 if ready else 1
