import unittest

from cn_live_viewer import huya, tars


def notice(nick, text):
    """A MessageNotice (uri 1400): sender info {2: nick}, tid, sid, content."""
    return tars.struct_(0, tars.string(2, nick)) + tars.int_(1, 1) + tars.int_(2, 2) + tars.string(3, text)


class HuyaTest(unittest.TestCase):
    def test_room_id_from_number_or_link(self):
        for arg in ('333003', 'https://www.huya.com/333003', 'https://www.huya.com/333003/?from=x', 'huya.com/333003'):
            self.assertEqual(huya.room_id(arg), '333003', arg)

    def test_ratio_is_replaced_or_added(self):
        self.assertEqual(huya.with_ratio('https://a/src/1-2.flv?wsTime=1&ratio=4000&fm=x', 20000),
                         'https://a/src/1-2.flv?wsTime=1&ratio=20000&fm=x')
        self.assertEqual(huya.with_ratio('https://a/src/1-2.flv?wsTime=1', 20000), 'https://a/src/1-2.flv?wsTime=1&ratio=20000')
        self.assertEqual(huya.with_ratio('https://a/src/1-2.flv', 2000), 'https://a/src/1-2.flv?ratio=2000')

    def test_uid_from_stream_path(self):
        self.assertEqual(huya.uid_from_url('https://al.flv.huya.com/src/1199561386374-1199561386374-5152.flv?x=1'),
                         1199561386374)
        self.assertIsNone(huya.uid_from_url('https://al.flv.huya.com/other.flv'))

    def test_owner_from_the_room_profile(self):
        data = {'status': 200, 'data': {'liveStatus': 'OFF', 'profileInfo': {'uid': 2367547387, 'nick': 'Some nick'}}}
        self.assertEqual(huya.parse_owner(data), (2367547387, 'Some nick'))       # offline rooms have it too
        self.assertEqual(huya.parse_owner({'status': 200, 'data': {'profileInfo': {'uid': '5', 'nick': ''}}}), (5, None))
        with self.assertRaises(LookupError):
            huya.parse_owner({'status': 422, 'message': 'no room'})

    def test_live_status_from_the_room_profile(self):
        self.assertEqual(huya.parse_profile({'status': 200, 'data': {'liveStatus': 'ON'}}), 'live')
        self.assertEqual(huya.parse_profile({'status': 200, 'data': {'liveStatus': 'OFF'}}), 'offline')
        self.assertEqual(huya.parse_profile({'status': 200, 'data': {'liveStatus': 'REPLAY'}}), 'offline')
        self.assertEqual(huya.parse_profile({'status': 422, 'message': 'no room'}), 'missing')

    def test_register_frame(self):
        cmd = tars.decode(huya.register_frame(42))
        self.assertEqual(cmd[0], 16)
        self.assertEqual(tars.decode(cmd[1]), {0: ['live:42', 'chat:42'], 1: ''})

    def test_push_v1(self):
        push = tars.int_(0, 1) + tars.int_(1, 1400) + tars.bytes_(2, notice('viewer', ' 666 '))
        frame = tars.int_(0, 7) + tars.bytes_(1, push)
        self.assertEqual(huya.parse_frame(frame), [('viewer', '666')])

    def test_push_v2_keeps_chat_and_skips_other_uris(self):
        items = (tars.head(1, tars.LIST) + tars.int_(0, 2)
                 + tars.struct_(0, tars.int_(0, 6501) + tars.bytes_(1, b'gift'))
                 + tars.struct_(0, tars.int_(0, 1400) + tars.bytes_(1, notice('nick', 'hello'))))
        frame = tars.int_(0, 22) + tars.bytes_(1, tars.string(0, 'chat:42') + items)
        self.assertEqual(huya.parse_frame(frame), [('nick', 'hello')])

    def test_other_commands_are_ignored(self):
        self.assertEqual(huya.parse_frame(huya.HEARTBEAT), [])


if __name__ == '__main__':
    unittest.main()
