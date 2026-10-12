import os
import tempfile
import unittest
from unittest import mock

from cn_live_viewer import hardware as hw

VULKAN = """Available vulkan devices:
  'NVIDIA GeForce RTX 4060 Laptop GPU' (GPU 0, PCI ID 10de:28a0, UUID 1)
  'Intel(R) UHD Graphics 770 (ADL-S GT1)' (GPU 1, PCI ID 8086:4680, UUID 2)
  'llvmpipe (LLVM 21.1.8, 256 bits)' (GPU 2, PCI ID 10005:0, UUID 3)
"""
DXGI = """Available DXGI adapters:
Adapter 0: vendor: 32902, description: Intel(R) Iris(R) Xe Graphics
Adapter 1: vendor: 4318, description: NVIDIA GeForce RTX 3050 Laptop GPU
Adapter 2: vendor: 5140, description: Microsoft Basic Render Driver
"""


class GpuTest(unittest.TestCase):
    def test_vulkan_list(self):
        gpus = hw.parse_vulkan(VULKAN)
        self.assertEqual([(g.vendor, g.discrete) for g in gpus], [('nvidia', True), ('intel', False)])   # no llvmpipe

    def test_dxgi_list(self):
        gpus = hw.parse_dxgi(DXGI)
        self.assertEqual([g.name for g in gpus], ['Intel(R) Iris(R) Xe Graphics', 'NVIDIA GeForce RTX 3050 Laptop GPU'])

    def test_built_in_or_separate(self):
        for name, vendor, discrete in [('Intel(R) Arc(TM) A770 Graphics', 'intel', True),
                                       ('Intel(R) Arc(TM) Graphics', 'intel', False),       # Meteor Lake, built in
                                       ('AMD Radeon RX 7600', 'amd', True),
                                       ('AMD Radeon(TM) 780M', 'amd', False),
                                       ('AMD Radeon(TM) Graphics', 'amd', False)]:
            self.assertEqual(hw.is_discrete(name, vendor), discrete, name)

    def test_two_chips_get_one_mode_each_one_chip_gets_none(self):
        gpus = hw.parse_dxgi(DXGI)
        efficient, high = hw.split(gpus)
        self.assertEqual((efficient.vendor, high.vendor), ('intel', 'nvidia'))
        self.assertEqual(hw.split(gpus[1:]), (None, None))
        self.assertEqual(hw.split([]), (None, None))

    def test_options_name_the_chip(self):
        g = hw.parse_dxgi(DXGI)[1]
        with mock.patch.object(hw, 'WINDOWS', True):
            self.assertEqual(hw.gpu_options(g), {'d3d11-adapter': g.name})
        with mock.patch.object(hw, 'WINDOWS', False):
            self.assertEqual(hw.gpu_options(g), {'gpu-api': 'vulkan', 'vulkan-device': g.name})
        self.assertEqual(hw.gpu_options(None), {})


class AutoModeTest(unittest.TestCase):
    def test_rules(self):
        laptop = hw.parse_dxgi(DXGI)
        with mock.patch.object(hw.sys, 'platform', 'win32'):
            self.assertEqual(hw.auto_mode(laptop, True, False)[0], 'efficient')    # on battery
            self.assertEqual(hw.auto_mode(laptop, False, True)[0], 'efficient')    # busy
            self.assertEqual(hw.auto_mode(laptop, False, False)[0], 'high')        # plugged in
            self.assertEqual(hw.auto_mode(laptop, None, False)[0], 'high')         # a desktop
            self.assertEqual(hw.auto_mode(laptop[:1], False, False)[0], 'efficient')   # built-in chip only


class BatteryTest(unittest.TestCase):
    def supplies(self, d, devices):
        for name, values in devices.items():
            os.makedirs(os.path.join(d, name))
            for k, v in values.items():
                with open(os.path.join(d, name, k), 'w') as f:
                    f.write(v + '\n')

    def test_a_headset_battery_is_not_the_computer_s(self):
        with tempfile.TemporaryDirectory() as d:
            self.supplies(d, {'hidpp_battery_0': {'type': 'Battery', 'scope': 'Device', 'status': 'Discharging'}})
            self.assertIsNone(hw.linux_on_battery(d))

    def test_laptop_unplugged_and_plugged_in(self):
        with tempfile.TemporaryDirectory() as d:
            self.supplies(d, {'BAT0': {'type': 'Battery', 'status': 'Discharging'},
                              'AC': {'type': 'Mains', 'online': '0'}})
            self.assertIs(hw.linux_on_battery(d), True)
            with open(os.path.join(d, 'AC', 'online'), 'w') as f:
                f.write('1\n')
            self.assertIs(hw.linux_on_battery(d), False)


if __name__ == '__main__':
    unittest.main()
