import unittest

from cn_live_viewer import douyin, pb


def varint(n):
    out = bytearray()
    while True:
        out.append((n & 0x7F) | (0x80 if n > 0x7F else 0))
        n >>= 7
        if not n:
            return bytes(out)


def field(number, value):
    """One protobuf field: ints as varints, str/bytes as length-delimited."""
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode()
    return varint(number << 3 | 2) + varint(len(value)) + value


def message(method, payload, mid):
    return field(1, field(1, method) + field(2, payload) + field(3, mid))


def chat(nick, text):
    return field(1, b'') + field(2, field(1, 7) + field(3, nick)) + field(3, text)


class DouyinTest(unittest.TestCase):
    def test_room_id_from_number_or_link(self):
        for arg in ('123456789012', 'https://live.douyin.com/123456789012', 'https://live.douyin.com/123456789012?a=1',
                    'https://www.douyin.com/live/123456789012'):
            self.assertEqual(douyin.room_id(arg), '123456789012', arg)

    def test_varints(self):
        for n in (0, 1, 127, 128, 300, 2**35):
            self.assertEqual(pb.varint(varint(n), 0), (n, len(varint(n))))

    def test_parse_fetch(self):
        data = (message('WebcastChatMessage', chat('viewer', ' hi there '), 11)
                + message('WebcastGiftMessage', b'\x08\x01', 12)
                + message('WebcastChatMessage', chat('empty', '  '), 13)
                + field(2, 'cursor-1') + field(3, 1500) + field(5, 'ext-1'))
        chats, cursor, ext, interval = douyin.parse_fetch(data)
        self.assertEqual(chats, [(11, 'viewer', 'hi there')])
        self.assertEqual((cursor, ext, interval), ('cursor-1', 'ext-1', 1.5))

    def test_poll_interval_is_clamped(self):
        self.assertEqual(douyin.parse_fetch(field(3, 60000))[3], 5)
        self.assertEqual(douyin.parse_fetch(field(3, 10))[3], 0.5)
        self.assertEqual(douyin.parse_fetch(b'')[3], 1.0)


if __name__ == '__main__':
    unittest.main()
