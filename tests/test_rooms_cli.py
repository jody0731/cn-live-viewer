import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

from cn_live_viewer import check, cli, player, rooms, settings


class RoomsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, 'sub', 'rooms.conf')

    def tearDown(self):
        self.dir.cleanup()

    def test_default_path(self):
        key = 'APPDATA' if os.name == 'nt' else 'XDG_CONFIG_HOME'      # Windows: %APPDATA%; elsewhere XDG / ~/.config
        with mock.patch.dict(os.environ, {key: os.path.join('x', 'config')}):
            self.assertEqual(rooms.default_path(), os.path.join('x', 'config', 'cn-live-viewer', 'rooms.conf'))

    def test_new_list_has_only_comments(self):
        rooms.ensure(self.path)
        self.assertEqual(rooms.load(self.path), [])

    def test_append_and_load(self):
        rooms.append(self.path, 'huya', '333003', 'First')
        rooms.append(self.path, 'douyin', '286658238204')
        self.assertEqual(rooms.load(self.path), [
            {'platform': 'huya', 'room': '333003', 'name': 'First'},
            {'platform': 'douyin', 'room': '286658238204', 'name': 'douyin 286658238204'}])

    def test_rename_and_remove_keep_comments_and_order(self):
        rooms.ensure(self.path)
        for room, name in (('1', 'One'), ('2', 'Two'), ('3', 'Three')):
            rooms.append(self.path, 'huya', room, name)
        rooms.rename(self.path, 'huya', '2', '  New\nname ')
        rooms.remove(self.path, 'huya', '1')
        self.assertEqual([(r['room'], r['name']) for r in rooms.load(self.path)], [('2', 'New name'), ('3', 'Three')])
        with open(self.path, encoding='utf-8') as f:
            self.assertTrue(f.read().startswith(rooms.EXAMPLE))

    def test_make_default_moves_the_room_above_the_others(self):
        rooms.ensure(self.path)
        for room in ('1', '2', '3'):
            rooms.append(self.path, 'huya', room)
        rooms.make_default(self.path, 'huya', '3')
        self.assertEqual([r['room'] for r in rooms.load(self.path)], ['3', '1', '2'])
        rooms.make_default(self.path, 'huya', '9')              # not saved: nothing changes
        self.assertEqual([r['room'] for r in rooms.load(self.path)], ['3', '1', '2'])
        with open(self.path, encoding='utf-8') as f:
            self.assertTrue(f.read().startswith(rooms.EXAMPLE))

    def test_bad_lines_are_skipped(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('twitch 1 nope\nhuya\n\n  # comment\nhuya 1 a name with spaces\n')
        self.assertEqual(rooms.load(self.path), [{'platform': 'huya', 'room': '1', 'name': 'a name with spaces'}])

    def test_recent_rooms_newest_first(self):
        for room in ('1', '2', '1', '3'):
            rooms.remember(self.path, 'huya', room)
        self.assertEqual(rooms.load_recent(self.path), [('huya', '3'), ('huya', '1'), ('huya', '2')])

    def test_start_order(self):
        saved = [{'platform': 'huya', 'room': r, 'name': r} for r in ('A', 'B', 'C')]
        recent = [('douyin', 'X'), ('huya', 'C'), ('huya', 'A')]
        # the default room, then the recent ones (newest first), then the rest of the list; each once
        self.assertEqual(rooms.start_order(saved, recent),
                         [('huya', 'A'), ('douyin', 'X'), ('huya', 'C'), ('huya', 'B')])
        self.assertEqual(rooms.start_order([], []), [])

    def test_live_first_keeps_offline_rooms_last(self):
        order = [('huya', 'A'), ('douyin', 'X'), ('huya', 'C'), ('huya', 'B')]
        live = {('huya', 'A'): False, ('huya', 'C'): True}
        self.assertEqual(rooms.live_first(order, live), [('huya', 'C'), ('douyin', 'X'), ('huya', 'B'), ('huya', 'A')])

    def test_parse_target(self):
        saved = [{'platform': 'douyin', 'room': '555', 'name': 'x'}]
        self.assertEqual(rooms.parse_target('333003', saved), ('huya', '333003'))
        self.assertEqual(rooms.parse_target('555', saved), ('douyin', '555'))
        self.assertEqual(rooms.parse_target('https://live.douyin.com/777', saved), ('douyin', '777'))
        self.assertEqual(rooms.parse_target('https://www.huya.com/lpl', saved), ('huya', 'lpl'))
        with self.assertRaises(ValueError):
            rooms.parse_target('not a room!', saved)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, 'rooms.conf')

    def tearDown(self):
        self.dir.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(['--rooms', self.path, *args])
        return code, out.getvalue(), err.getvalue()

    def test_rooms_lists_saved_rooms(self):
        rooms.append(self.path, 'huya', '333003', 'First')
        code, out, _ = self.run_cli('rooms')
        self.assertEqual(code, 0)
        self.assertIn('333003', out)

    def test_no_room_and_none_saved(self):
        code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn('none saved', err)

    def test_bad_room(self):
        code, _, err = self.run_cli('url', 'not a room!')
        self.assertEqual(code, 2)
        self.assertIn('not a Huya/Douyin room', err)

    def test_check_says_what_is_missing(self):
        with mock.patch.object(check, 'find_mpv', side_effect=FileNotFoundError('mpv')):
            code, out, _ = self.run_cli('check')
        self.assertEqual(code, 1)
        self.assertIn('MISSING  mpv', out)
        with mock.patch.object(check, 'find_mpv', return_value='/x/mpv'), \
                mock.patch.object(check, 'mpv_version', return_value=(0, 41)), \
                mock.patch.object(check, 'chinese_font', return_value=True):
            code, out, _ = self.run_cli('check')
        self.assertEqual(code, 0, out)
        self.assertIn('mpv 0.41 at /x/mpv', out)
        self.assertIn('Video Decoder: Auto', out)

    def test_check_reads_mpv_versions(self):
        for text, version in [('mpv v0.41.0 Copyright', (0, 41)), ('mpv 0.35.1 Copyright', (0, 35)),
                              ('mpv v0.40.0-dirty Copyright', (0, 40)), ('nothing', None)]:
            with mock.patch.object(check.subprocess, 'run', return_value=mock.Mock(stdout=text)):
                self.assertEqual(check.mpv_version('mpv'), version, text)


class SettingsTest(unittest.TestCase):
    def test_defaults_save_and_bad_values(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(settings.load(d)['decoder'], 'auto')             # nothing saved yet
            settings.save(d, decoder='high')
            self.assertEqual(settings.load(d)['decoder'], 'high')
            with open(settings.path(d), 'w', encoding='utf-8') as f:
                f.write('{"decoder": "ultra"}')
            self.assertEqual(settings.load(d)['decoder'], 'auto')             # an unknown choice
            with open(settings.path(d), 'w', encoding='utf-8') as f:
                f.write('not json')
            self.assertEqual(settings.load(d)['decoder'], 'auto')

    def test_kept_settings_and_their_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            s = settings.load(d)
            self.assertEqual((s['volume'], s['mute'], s['chat'], s['quality']), (50, False, True, 'auto'))
            settings.save(d, volume=35, mute=True, chat=False, quality='8')
            s = settings.load(d)
            self.assertEqual((s['volume'], s['mute'], s['chat'], s['quality']), (35, True, False, '8'))
            with open(settings.path(d), 'w', encoding='utf-8') as f:
                f.write('{"volume": "loud", "mute": "yes", "chat": 1, "quality": ""}')
            s = settings.load(d)
            self.assertEqual((s['volume'], s['mute'], s['chat'], s['quality']), (50, False, True, 'auto'))

    def test_window_settings(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(settings.load(d)['window'], {'fullscreen': False, 'maximized': True, 'size': None})
            with open(settings.path(d), 'w', encoding='utf-8') as f:
                f.write('{"window": {"fullscreen": "yes", "maximized": false, "size": [5, 50]}}')
            self.assertEqual(settings.load(d)['window'], {'fullscreen': False, 'maximized': False, 'size': None})
        self.assertEqual(player.window_args({'fullscreen': False, 'maximized': True, 'size': None}),
                         ['--window-maximized=yes'])
        self.assertEqual(player.window_args({'fullscreen': True, 'maximized': False, 'size': [50, 62.5]}),
                         ['--window-maximized=no', '--geometry=50%x62.5%', '--fullscreen=yes'])

    def test_window_size_only_from_a_normal_window(self):
        before = {'fullscreen': False, 'maximized': True, 'size': None}
        props = {'fullscreen': False, 'window-maximized': False, 'osd-dimensions': {'w': 1920, 'h': 1080},
                 'display-width': 3840, 'display-height': 2160}
        self.assertEqual(player.window_state(props, before), {'fullscreen': False, 'maximized': False, 'size': [50, 50]})
        full = dict(props, fullscreen=True, **{'osd-dimensions': {'w': 3840, 'h': 2160}})
        self.assertEqual(player.window_state(full, {'fullscreen': False, 'maximized': False, 'size': [50, 50]}),
                         {'fullscreen': True, 'maximized': False, 'size': [50, 50]})   # the normal size stays

    def test_the_old_picture_choice_carries_over(self):
        with tempfile.TemporaryDirectory() as d:
            with open(settings.path(d), 'w', encoding='utf-8') as f:
                f.write('{"picture": "high"}')
            self.assertEqual(settings.load(d)['decoder'], 'high')
            self.assertNotIn('picture', settings.load(d))

    def test_every_decoder_mode_has_a_profile(self):
        self.assertEqual(set(settings.MODES), set(player.PROFILES))
        with open(player.PROFILES_FILE, encoding='utf-8') as f:
            text = f.read()
        for profile in player.PROFILES.values():
            self.assertIn(f'[{profile}]', text)


class DesktopTest(unittest.TestCase):
    """The app launcher, on whichever system runs the tests (CI covers Linux, macOS and Windows)."""

    def setUp(self):
        from cn_live_viewer import desktop
        self.desktop = desktop
        self.dir = tempfile.TemporaryDirectory()
        env = {'APPDATA': self.dir.name, 'XDG_DATA_HOME': self.dir.name, 'HOME': self.dir.name}
        self.patches = [mock.patch.dict(os.environ, env),
                        mock.patch.object(desktop, '_refresh')]    # don't touch the real desktop's menu cache
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.dir.cleanup()

    def test_launcher_is_added_and_removed(self):
        p = self.desktop.install()
        self.assertTrue(p.startswith(self.dir.name), p)
        self.assertTrue(os.path.exists(p), p)
        if os.name == 'nt':
            self.assertTrue(p.endswith('CN Live Viewer.lnk'))
        elif sys.platform == 'darwin':
            import plistlib
            with open(os.path.join(p, 'Contents', 'Info.plist'), 'rb') as f:
                self.assertEqual(plistlib.load(f)['CFBundleExecutable'], 'cn-live-viewer')
            self.assertTrue(os.access(os.path.join(p, 'Contents', 'MacOS', 'cn-live-viewer'), os.X_OK))
        else:
            with open(p, encoding='utf-8') as f:
                text = f.read()
            for line in ('Icon=mpv', 'Terminal=false', 'StartupWMClass=cn-live-viewer'):
                self.assertIn(line, text.splitlines())
            self.assertRegex(text, r'(?m)^Exec=".+" .*--launcher %u$')
        self.assertTrue(self.desktop.remove())
        self.assertFalse(os.path.exists(p))
        self.assertFalse(self.desktop.remove())


class PackageTest(unittest.TestCase):
    def test_mpv_scripts_ship_with_the_package(self):
        for path in player.SCRIPTS + [player.PROFILES_FILE]:
            self.assertTrue(os.path.isfile(path), path)

    def test_overlay_leaves_out_emoji(self):
        self.assertEqual(player.overlay_text('\U0001F921\U0001F921 nice  \u2764\ufe0f 666'), 'nice \u2764 666')
        self.assertEqual(player.overlay_text('\U0001F921' * 7), '')
        self.assertEqual(player.overlay_text('\u4e2d\u6587 \uff1f\uff1f'), '\u4e2d\u6587 \uff1f\uff1f')

    def test_chat_line_without_colour(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            player.print_chat('nick', 'text', color=False)
        self.assertEqual(out.getvalue(), 'nick: text\n')


if __name__ == '__main__':
    unittest.main()
