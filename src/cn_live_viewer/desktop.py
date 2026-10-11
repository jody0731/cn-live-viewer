"""The app launcher, so cn-live-viewer starts without a terminal and can be pinned, with mpv's icon:
- Linux: a .desktop file, in the app menu and search;
- macOS: CN Live Viewer.app in ~/Applications, in Launchpad and Spotlight;
- Windows: a Start menu shortcut, which runs without a console window."""
import glob
import os
import plistlib
import shlex
import shutil
import stat
import subprocess
import sys

from . import __version__
from .mpv import APP_ID, find_mpv

NAME = 'CN Live Viewer'
COMMENT = 'Watch Huya and Douyin live rooms in mpv, with the chat'


def path() -> str:
    if os.name == 'nt':
        base = os.environ.get('APPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming')
        return os.path.join(base, 'Microsoft', 'Windows', 'Start Menu', 'Programs', f'{NAME}.lnk')
    if sys.platform == 'darwin':
        return os.path.join(os.path.expanduser('~'), 'Applications', f'{NAME}.app')
    base = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(base, 'applications', 'cn-live-viewer.desktop')


def ensure(config_dir: str) -> None:
    """Add the launcher the first time cn-live-viewer plays, so every install has it (not only the install scripts).
    A marker file remembers that it was added, or removed with `cn-live-viewer desktop remove`, so a removed
    launcher stays removed. Best effort: a launcher that can't be made never stops playback."""
    marker = os.path.join(config_dir, 'launcher')
    if os.path.exists(marker):
        return
    try:
        install()
        mark(config_dir, 'added')
    except Exception:                                # noqa: BLE001 - e.g. no PowerShell, a read-only folder
        pass


def mark(config_dir: str, state: str) -> None:
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, 'launcher'), 'w', encoding='utf-8') as f:
        f.write(state + '\n')


def install() -> str:
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if os.name == 'nt':
        _windows_shortcut(p)
    elif sys.platform == 'darwin':
        _mac_app(p)
    else:
        with open(p, 'w', encoding='utf-8') as f:
            f.write(desktop_entry(command()))
        _refresh(os.path.dirname(p))
    return p


def remove() -> bool:
    p = path()
    if not os.path.exists(p):
        return False
    if os.path.isdir(p):
        shutil.rmtree(p)
    else:
        os.remove(p)
    if os.name != 'nt' and sys.platform != 'darwin':
        _refresh(os.path.dirname(p))
    return True


# ---------------------------------------------------------------- Linux

def command() -> str:
    """How the launcher starts cn-live-viewer: the installed command, or this Python running the package."""
    exe = shutil.which('cn-live-viewer')
    return f'"{exe}"' if exe else f'"{sys.executable}" -m cn_live_viewer'


def desktop_entry(cmd: str) -> str:
    # %u: a Huya or Douyin link dropped on the launcher is opened; started from the menu, the default room plays
    return f"""[Desktop Entry]
Type=Application
Name={NAME}
GenericName=Live Stream Viewer
Comment={COMMENT}
Exec={cmd} --launcher %u
Icon=mpv
Terminal=false
Categories=AudioVideo;Video;Player;
Keywords=huya;douyin;live;stream;danmaku;
StartupWMClass={APP_ID}
"""


def _refresh(folder: str) -> None:
    """Most desktops notice the change by themselves; this nudges the ones that keep a cache."""
    for cmd in (['update-desktop-database', folder], ['kbuildsycoca6'], ['kbuildsycoca5']):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


# ---------------------------------------------------------------- macOS

def _mac_icon():
    """mpv's icon, from an mpv.app if there is one (Homebrew's mpv may not have it)."""
    for pattern in ('/Applications/mpv.app/Contents/Resources/*.icns',
                    '/opt/homebrew/opt/mpv/*.app/Contents/Resources/*.icns',
                    '/usr/local/opt/mpv/*.app/Contents/Resources/*.icns'):
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    return None


def _mac_app(bundle: str) -> None:
    if os.path.exists(bundle):
        shutil.rmtree(bundle)
    macos, resources = os.path.join(bundle, 'Contents', 'MacOS'), os.path.join(bundle, 'Contents', 'Resources')
    os.makedirs(macos)
    os.makedirs(resources)
    info = {'CFBundleName': NAME, 'CFBundleDisplayName': NAME, 'CFBundleIdentifier': 'io.github.jody0731.cn-live-viewer',
            'CFBundleExecutable': 'cn-live-viewer', 'CFBundlePackageType': 'APPL', 'CFBundleVersion': __version__,
            'CFBundleShortVersionString': __version__,
            'LSUIElement': True}                     # no Dock icon for this starter; mpv's window has its own
    icon = _mac_icon()
    if icon:
        shutil.copyfile(icon, os.path.join(resources, 'mpv.icns'))
        info['CFBundleIconFile'] = 'mpv'
    with open(os.path.join(bundle, 'Contents', 'Info.plist'), 'wb') as f:
        plistlib.dump(info, f)
    starter = os.path.join(macos, 'cn-live-viewer')
    with open(starter, 'w', encoding='utf-8') as f:
        f.write(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -m cn_live_viewer --launcher "$@"\n')
    os.chmod(starter, os.stat(starter).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------------------- Windows

def _windows_shortcut(lnk: str) -> None:
    # pythonw.exe runs without a console window (python.exe would open one)
    folder = os.path.dirname(sys.executable)
    pythonw = os.path.join(folder, 'pythonw.exe')
    target = pythonw if os.path.exists(pythonw) else sys.executable
    try:
        icon = find_mpv()
    except FileNotFoundError:
        icon = None
    q = lambda s: s.replace("'", "''")            # inside a PowerShell '...' string
    script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}'); "
              f"$s.TargetPath = '{q(target)}'; $s.Arguments = '-m cn_live_viewer --launcher'; "
              f"$s.WorkingDirectory = '{q(os.path.expanduser('~'))}'; $s.Description = '{q(COMMENT)}'; "
              + (f"$s.IconLocation = '{q(icon)},0'; " if icon else '') + "$s.Save()")
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
