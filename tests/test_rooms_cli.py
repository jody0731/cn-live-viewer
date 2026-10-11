import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

from cn_live_viewer import cli, player, rooms


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
        for path in player.SCRIPTS:
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
