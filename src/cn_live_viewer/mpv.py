"""Start mpv and talk to it over its JSON IPC socket (Linux and macOS; Windows needs a named pipe, not yet)."""
import asyncio
import json
import os
import tempfile


class Mpv:
    def __init__(self, scripts=(), extra_args=()):
        runtime = os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir()
        self.sock = os.path.join(runtime, f'cn-live-viewer-{os.getpid()}.sock')
        self.scripts, self.extra_args = list(scripts), list(extra_args)
        self.proc = self.reader = self.writer = None
        self._rid = 0

    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            'mpv', '--idle=yes', '--force-window=yes', f'--input-ipc-server={self.sock}',
            '--user-agent=Mozilla/5.0', '--title=${media-title}',
            *[f'--script={s}' for s in self.scripts], *self.extra_args,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        for _ in range(150):
            if os.path.exists(self.sock):
                break
            if self.proc.returncode is not None:
                raise RuntimeError('mpv exited at start (try running mpv on its own to see why)')
            await asyncio.sleep(0.1)
        self.reader, self.writer = await asyncio.open_unix_connection(self.sock)

    async def command(self, *args):
        self._rid += 1
        self.writer.write((json.dumps({'command': list(args), 'request_id': self._rid}, ensure_ascii=False) + '\n').encode())
        await self.writer.drain()

    async def show(self, text: str, seconds: float = 3):
        await self.command('show-text', text, int(seconds * 1000))

    async def events(self):
        """Yield mpv events (dicts with an 'event' key) until mpv closes."""
        while True:
            line = await self.reader.readline()
            if not line:
                return
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if 'event' in msg:
                yield msg

    async def close(self):
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.kill()
        try:
            os.remove(self.sock)
        except OSError:
            pass
