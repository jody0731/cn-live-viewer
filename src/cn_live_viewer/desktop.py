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
    """How the launcher starts cn-live-viewer: this copy's command (beside its Python, so not another copy that comes
    first on PATH), else the one on PATH, else this Python running the package."""
    here = os.path.join(os.path.dirname(sys.executable), 'cn-live-viewer')
    exe = here if os.path.isfile(here) and os.access(here, os.X_OK) else shutil.which('cn-live-viewer')
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

APP_USER_MODEL_ID = 'jody0731.CNLiveViewer'


def _windows_target() -> str:
    # pythonw.exe runs without a console window (python.exe would open one)
    pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    return pythonw if os.path.exists(pythonw) else sys.executable


def windows_relaunch(hwnd: int, mpv: str) -> None:
    """Make the taskbar treat mpv's window as cn-live-viewer's: its own button (not mpv's), and "new window" and
    pinning start cn-live-viewer again, a second window beside the first, not a bare mpv. Windows reads this from the
    window's property store (System.AppUserModel.ID and the Relaunch* keys), which another process may set.
    Raises OSError when Windows refuses."""
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [('raw', ctypes.c_ubyte * 16)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [('fmtid', GUID), ('pid', wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [('vt', ctypes.c_ushort), ('r1', ctypes.c_ushort), ('r2', ctypes.c_ushort), ('r3', ctypes.c_ushort),
                    ('value', ctypes.c_void_p), ('extra', ctypes.c_void_p)]

    def guid(text):
        g = GUID()
        ctypes.memmove(g.raw, uuid.UUID(text).bytes_le, 16)
        return g

    APPID_KEYS = '9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3'      # PKEY_AppUserModel_*
    VT_LPWSTR = 31
    ole32, shell32 = ctypes.windll.ole32, ctypes.windll.shell32
    ole32.CoInitializeEx(None, 2)                    # COINIT_APARTMENTTHREADED, on this (worker) thread
    store = ctypes.c_void_p()
    try:
        hr = shell32.SHGetPropertyStoreForWindow(wintypes.HWND(hwnd), ctypes.byref(guid('886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99')),
                                                 ctypes.byref(store))
        if hr != 0 or not store:
            raise OSError(f'SHGetPropertyStoreForWindow failed: {hr & 0xFFFFFFFF:#x}')
        vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                       ctypes.POINTER(PROPVARIANT))(vtbl[6])        # IPropertyStore::SetValue
        commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[7])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        keep = []                                    # the strings must outlive the calls
        # the ID last: Windows reads the Relaunch* keys when the ID is set
        for pid, value in ((2, f'"{_windows_target()}" -m cn_live_viewer --launcher'),   # RelaunchCommand
                           (3, f'{mpv},0'),                                                # RelaunchIconResource
                           (4, NAME),                                                      # RelaunchDisplayNameResource
                           (5, APP_USER_MODEL_ID)):                                        # ID
            text = ctypes.create_unicode_buffer(value)
            keep.append(text)
            pv = PROPVARIANT(vt=VT_LPWSTR, value=ctypes.cast(text, ctypes.c_void_p))
            hr = set_value(store, ctypes.byref(PROPERTYKEY(guid(APPID_KEYS), pid)), ctypes.byref(pv))
            if hr != 0:
                raise OSError(f'setting taskbar property {pid} failed: {hr & 0xFFFFFFFF:#x}')
        commit(store)
        release(store)
    finally:
        ole32.CoUninitialize()


def _windows_shortcut(lnk: str) -> None:
    target = _windows_target()
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
