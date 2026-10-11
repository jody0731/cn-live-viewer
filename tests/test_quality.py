import json
import math
import unittest

from cn_live_viewer import douyin, quality as q

TIERS = [q.Tier(str(r), f'{r / 1000:g} Mbps', r / 1000, f'url-{r}') for r in (20000, 8000, 4000, 2000, 500)]


class ChoiceTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(q.parse(None), q.AUTO)
        self.assertEqual(q.parse('Auto'), q.AUTO)
        self.assertEqual(q.parse('8'), 8.0)                 # Mbps
        self.assertEqual(q.parse('2000'), 2.0)              # kbps, the old form
        self.assertEqual(q.parse('hd'), 'hd')               # a Douyin quality name

    def test_pick(self):
        self.assertEqual(q.pick(TIERS, q.AUTO).id, '20000')
        self.assertEqual(q.pick(TIERS, q.AUTO, cap=5).id, '4000')        # Auto after stepping down
        self.assertEqual(q.pick(TIERS, 8.0).id, '8000')
        self.assertEqual(q.pick(TIERS, 3.0).id, '2000')                  # the best at or below the cap
        self.assertEqual(q.pick(TIERS, 0.1).id, '500')                   # nothing that low: the lowest
        self.assertEqual(q.pick(TIERS, 'hd').id, '20000')                # a name the room doesn't have: the best
        with self.assertRaises(LookupError):
            q.pick([], q.AUTO)


class AutoTest(unittest.TestCase):
    def test_stalls_while_filling_the_buffer_dont_count(self):
        a = q.Auto(); a.changed(100)
        self.assertFalse(a.stall_started(105))
        self.assertFalse(a.stall_long(109))

    def test_a_second_stall_within_a_minute_steps_down(self):
        a = q.Auto(); a.changed(0)
        self.assertFalse(a.stall_started(100))
        self.assertTrue(a.stall_started(150))

    def test_a_long_stall_steps_down(self):
        a = q.Auto(); a.changed(0)
        a.stall_started(100)
        self.assertTrue(a.stall_long(104))

    def test_calm_then_try_up_and_back_off_if_it_fails(self):
        a = q.Auto(); a.changed(0)
        self.assertFalse(a.may_step_up(200))                # not calm long enough
        self.assertTrue(a.may_step_up(301))
        a.changed(301, probing=True)
        self.assertTrue(a.stall_started(330))               # the try upwards stalled: down again ...
        a.changed(331)
        self.assertFalse(a.may_step_up(331 + 600))          # ... and no new try for 20 minutes
        self.assertTrue(a.may_step_up(330 + q.Auto.HOLD + 1))

    def test_cap_starts_open(self):
        self.assertEqual(q.Auto().cap, math.inf)


class DouyinTierTest(unittest.TestCase):
    def test_label_from_sdk_params(self):
        main = {'flv': 'u', 'sdk_params': json.dumps({'vbitrate': 5200000, 'resolution': '1920x1080'})}
        t = douyin.tier('origin', main)
        self.assertEqual((t.label, t.mbps, t.url), ('Original · 1080p · 5.2 Mbps', 5.2, 'u'))

    def test_audio_only_is_offered_but_never_picked_by_auto_or_a_cap(self):
        ao = douyin.tier('ao', {'flv': 'a'})
        self.assertEqual((ao.label, ao.video), ('Audio only', False))
        tiers = TIERS + [ao]
        self.assertEqual(q.pick(tiers, 0.05).id, '500')                  # the lowest video level, not audio only
        self.assertEqual(q.pick(tiers, q.AUTO, cap=0.05).id, '500')
        self.assertEqual(q.pick(tiers, 'ao').id, 'ao')                   # chosen by name, it plays

    def test_label_without_sdk_params(self):
        t = douyin.tier('hd', {'flv': 'u'})
        self.assertEqual((t.label, t.mbps), ('HD', douyin.GUESS_MBPS['hd']))


if __name__ == '__main__':
    unittest.main()
