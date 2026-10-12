"""Start mpv and talk to it over its JSON IPC: a Unix socket on Linux and macOS, a named pipe on Windows."""
import asyncio
import json
import os
import shutil
import sys
import tempfile

APP_ID = 'cn-live-viewer'     # the window's app id / class: the desktop groups the window under the app launcher
WINDOWS = os.name == 'nt'
LINE_LIMIT = 2 ** 20          # longest line read from mpv (asyncio's default, 64 KiB, is tight for big replies)

# where mpv usually is when it isn't on PATH: apps started from a launcher or the Finder get a short PATH
MPV_PLACES = {
    'darwin': ['/opt/homebrew/bin/mpv', '/usr/local/bin/mpv', '/Applications/mpv.app/Contents/MacOS/mpv'],
    'win32': [os.path.expandvars(r'%USERPROFILE%\scoop\apps\mpv\current\mpv.exe'),
              os.path.expandvars(r'%ProgramData%\chocolatey\lib\mpvio.install\tools\mpv.exe'),   # choco install mpv
              os.path.expandvars(r'%ProgramData%\chocolatey\bin\mpv.exe'),
              os.path.expandvars(r'%ProgramFiles%\mpv\mpv.exe'),
              os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\WinGet\Links\mpv.exe'),        # winget
              os.path.expandvars(r'%LOCALAPPDATA%\Programs\mpv\mpv.exe'),
              os.path.expandvars(r'%LOCALAPPDATA%\cn-live-viewer\mpv\mpv.exe')],   # downloaded by install.ps1
}


def find_mpv() -> str:
    """The mpv program. Raises FileNotFoundError when it isn't installed."""
    found = shutil.which('mpv')
    if found:
        return found
    for place in MPV_PLACES.get(sys.platform, []):
        if os.path.isfile(place):
            return place
    raise FileNotFoundError('mpv')


async def supported_options(mpv: str, names) -> set:
    """Which of these options this mpv knows; mpv refuses to start on an option it doesn't know."""
    try:
        proc = await asyncio.create_subprocess_exec(mpv, '--list-options', stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), 5)
    except (OSError, asyncio.TimeoutError):
        return set()
    return {n for n in names if f'--{n} '.encode() in out}


async def open_pipe(path: str):
    """Connect to a Windows named pipe as an asyncio (reader, writer) pair."""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=LINE_LIMIT)
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await loop.create_pipe_connection(lambda: protocol, path)
    return reader, asyncio.StreamWriter(transport, protocol, reader, loop)


class Mpv:
    def __init__(self, scripts=(), extra_args=()):
        if WINDOWS:
            self.ipc = rf'\\.\pipe\cn-live-viewer-{os.getpid()}'
        else:
            runtime = os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir()
            self.ipc = os.path.join(runtime, f'cn-live-viewer-{os.getpid()}.sock')
        self.scripts, self.extra_args = list(scripts), list(extra_args)
        self.proc = self.reader = self.writer = None
        self._rid = 0
        self._replies = {}                           # request id -> future, for get()

    async def window_id_args(self, mpv: str) -> list:
        """Name the window after cn-live-viewer, so Linux desktops group it under the app launcher (Windows and
        macOS group windows by program instead)."""
        if WINDOWS or sys.platform == 'darwin':
            return []
        names = ('x11-name', 'wayland-app-id')
        known = await supported_options(mpv, names)
        return [f'--{n}={APP_ID}' for n in names if n in known]

    async def start(self):
        mpv = find_mpv()
        self.proc = await asyncio.create_subprocess_exec(
            mpv, '--idle=yes', '--force-window=yes', f'--input-ipc-server={self.ipc}',
            '--user-agent=Mozilla/5.0', '--title=${media-title}', '--osc=no',   # bar.lua replaces mpv's control bar
            *await self.window_id_args(mpv),
            *[f'--script={s}' for s in self.scripts], *self.extra_args,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        self.reader, self.writer = await self._connect()

    async def _connect(self):
        """Wait for mpv to open its socket or pipe, then connect."""
        for _ in range(150):
            if self.proc.returncode is not None:
                raise RuntimeError('mpv exited at start (try running mpv on its own to see why)')
            try:
                if WINDOWS:
                    return await open_pipe(self.ipc)
                if os.path.exists(self.ipc):
                    return await asyncio.open_unix_connection(self.ipc, limit=LINE_LIMIT)
            except OSError:
                pass                                 # not there yet
            await asyncio.sleep(0.1)
        raise RuntimeError('mpv did not open its control connection')

    async def _send(self, args) -> int:
        self._rid += 1
        try:
            self.writer.write((json.dumps({'command': list(args), 'request_id': self._rid}, ensure_ascii=False) + '\n').encode())
            await self.writer.drain()
        except (ConnectionError, OSError):           # mpv has closed (e.g. quit while a room was loading): nothing to tell
            pass
        return self._rid

    async def command(self, *args):
        await self._send(args)

    async def get(self, name: str, timeout: float = 2):
        """A property's value, or None when mpv doesn't have it (yet). The reply arrives through events(), which
        must be running."""
        fut = asyncio.get_running_loop().create_future()
        self._replies[self._rid + 1] = fut
        rid = await self._send(['get_property', name])
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._replies.pop(rid, None)

    async def show(self, text: str, seconds: float = 3):
        await self.command('show-text', text, int(seconds * 1000))

    async def events(self):
        """Yield mpv events (dicts with an 'event' key) until mpv closes."""
        while True:
            try:
                line = await self.reader.readline()
            except ValueError:                       # a line over LINE_LIMIT: asyncio drops it; read on
                continue
            except OSError:                          # the connection broke
                return
            if not line:
                return
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if 'event' in msg:
                yield msg
            elif msg.get('request_id') in self._replies:
                fut = self._replies.pop(msg['request_id'])
                if not fut.done():
                    fut.set_result(msg.get('data') if msg.get('error') == 'success' else None)

    async def close(self):
        if self.writer:
            self.writer.close()
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.kill()
        if not WINDOWS:                              # a named pipe goes away with mpv
            try:
                os.remove(self.ipc)
            except OSError:
                pass
