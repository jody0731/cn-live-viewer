import contextlib
import io
import os
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

    def test_default_path_follows_xdg(self):
        with mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': '/x/config'}):
            self.assertEqual(rooms.default_path(), os.path.join('/x/config', 'cn-live-viewer', 'rooms.conf'))

    def test_new_list_has_only_comments(self):
        rooms.ensure(self.path)
        self.assertEqual(rooms.load(self.path), [])

    def test_append_and_load(self):
        rooms.append(self.path, 'huya', '333003', 'First')
        rooms.append(self.path, 'douyin', '123456789012')
        self.assertEqual(rooms.load(self.path), [
            {'platform': 'huya', 'room': '333003', 'name': 'First'},
            {'platform': 'douyin', 'room': '123456789012', 'name': 'douyin 123456789012'}])

    def test_bad_lines_are_skipped(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('twitch 1 nope\nhuya\n\n  # comment\nhuya 1 a name with spaces\n')
        self.assertEqual(rooms.load(self.path), [{'platform': 'huya', 'room': '1', 'name': 'a name with spaces'}])

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


class PackageTest(unittest.TestCase):
    def test_mpv_scripts_ship_with_the_package(self):
        for path in player.SCRIPTS:
            self.assertTrue(os.path.isfile(path), path)

    def test_chat_line_without_colour(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            player.print_chat('nick', 'text', color=False)
        self.assertEqual(out.getvalue(), 'nick: text\n')


if __name__ == '__main__':
    unittest.main()
