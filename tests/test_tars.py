import unittest

from cn_live_viewer import tars


class TarsTest(unittest.TestCase):
    def test_ints_round_trip_in_the_smallest_type(self):
        for value, size in ((0, 1), (5, 2), (-100, 2), (300, 3), (70000, 5), (2**40, 9), (-2**40, 9)):
            data = tars.int_(3, value)
            self.assertEqual(len(data), size, value)
            self.assertEqual(tars.decode(data), {3: value})

    def test_strings_short_and_long(self):
        short, long = 'hello 666', 'x' * 300
        self.assertEqual(tars.decode(tars.string(1, short) + tars.string(2, long)), {1: short, 2: long})

    def test_tag_above_14_uses_a_second_byte(self):
        data = tars.int_(20, 7)
        self.assertEqual(data[0] >> 4, 15)
        self.assertEqual(tars.decode(data), {20: 7})

    def test_bytes_list_and_struct(self):
        body = tars.string_list(0, ['live:1', 'chat:1']) + tars.int_(1, 9)
        data = tars.bytes_(0, b'\x01\x02') + tars.struct_(1, body)
        self.assertEqual(tars.decode(data), {0: b'\x01\x02', 1: {0: ['live:1', 'chat:1'], 1: 9}})

    def test_truncated_data_raises(self):
        with self.assertRaises(ValueError):
            tars.decode(tars.string(0, 'hello')[:-2])


if __name__ == '__main__':
    unittest.main()
