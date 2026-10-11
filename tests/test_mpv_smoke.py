"""Start the real mpv with cn-live-viewer's scripts, without a window or sound, and talk to it over the same IPC
the player uses (a Unix socket, or a named pipe on Windows). Skipped when mpv isn't installed; CI installs it on
Linux, macOS and Windows."""
import asyncio
import json
import os
import re
import tempfile
import unittest

from cn_live_viewer import player
from cn_live_viewer.mpv import Mpv, find_mpv

try:
    find_mpv()
    HAVE_MPV = True
except FileNotFoundError:
    HAVE_MPV = False


async def get(mpv: Mpv, prop: str):
    """Ask mpv for a property and wait for the answer (nothing else reads from mpv in this test)."""
    await mpv.command('get_property', prop)
    rid = mpv._rid
    while True:
        msg = json.loads(await asyncio.wait_for(mpv.reader.readline(), 10))
        if msg.get('request_id') == rid:
            return msg.get('data')


@unittest.skipUnless(HAVE_MPV or os.environ.get('CNLV_REQUIRE_MPV'), 'mpv is not installed')
class MpvSmokeTest(unittest.TestCase):
    def test_scripts_load_and_ipc_works(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, 'mpv.log')

            async def run():
                # the player's own options (so the picture modes' file must ship with the package), without a window
                mpv = Mpv(player.SCRIPTS, player.DEFAULT_MPV_ARGS + ['--profile=cnlv-efficient', '--vo=null', '--ao=null',
                                                                     f'--log-file={log}'])
                await mpv.start()
                try:
                    rooms = {'playing': False, 'rooms': [{'platform': 'huya', 'room': '1', 'name': 'One'},
                                                         {'platform': 'huya', 'room': '2', 'name': 'Two', 'live': False}]}
                    await mpv.command('set_property', 'user-data/cnlv/rooms', rooms)
                    levels = {'auto': True, 'current': '20000', 'label': '20 Mbps',
                              'tiers': [{'id': '20000', 'label': '20 Mbps'}, {'id': '2000', 'label': '2 Mbps'}]}
                    await mpv.command('set_property', 'user-data/cnlv/quality', levels)
                    await mpv.command('set_property', 'user-data/cnlv/picture', 'high')
                    await mpv.command('script-message', 'cnlv-danmaku', 'hello 666')
                    efficient = [await get(mpv, p) for p in ('video-sync', 'interpolation')]
                    await mpv.command('apply-profile', player.PROFILES['high'])     # switching picture modes
                    high = [await get(mpv, p) for p in ('video-sync', 'interpolation')]
                    await asyncio.sleep(1.5)
                    return await get(mpv, 'user-data/cnlv/chat'), await get(mpv, 'menu-data'), efficient, high
                finally:
                    await mpv.close()

            chat, menu, efficient, high = asyncio.run(run())
            self.assertIs(chat, True)                                   # danmaku.lua runs
            self.assertEqual(efficient, ['audio', False])
            self.assertEqual(high, ['display-resample', True])
            if menu is not None:                                        # older mpv has no right-click menu
                self.assertEqual(menu[0]['title'], 'Rooms')             # picker.lua runs and read the room list
                self.assertEqual([i.get('title') for i in menu[0]['submenu'][:2]], ['One', '○ Offline  ·  Two'])
                self.assertEqual(menu[1]['title'], 'Quality')
                self.assertEqual([i.get('title') for i in menu[1]['submenu']], ['Auto (now 20 Mbps)', None, '20 Mbps', '2 Mbps'])
                self.assertEqual(menu[2]['title'], 'Picture')
                self.assertEqual([bool(i.get('state')) for i in menu[2]['submenu']], [False, True])   # High quality
            with open(log, encoding='utf-8', errors='replace') as f:
                text = f.read()
            for script in ('danmaku', 'picker', 'bar'):
                self.assertIn(f'[{script}]', text, f'{script}.lua did not load')
            errors = re.findall(r'.*\[(?:danmaku|picker|bar)\].*(?:error|traceback).*', text, re.I)
            self.assertEqual(errors, [], '\n'.join(errors))


if __name__ == '__main__':
    unittest.main()
