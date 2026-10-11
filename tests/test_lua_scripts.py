"""Checks on the mpv Lua scripts that need no mpv. A `local function` is only visible below its definition: a call
from code above it reaches a nil global, at runtime and only when that path runs (this bit twice)."""
import glob
import os
import re
import unittest

from cn_live_viewer import player


class LuaScriptTest(unittest.TestCase):
    def test_no_local_function_is_used_before_it_is_defined(self):
        scripts = glob.glob(os.path.join(os.path.dirname(player.SCRIPTS[0]), '*.lua'))
        self.assertTrue(scripts)
        for path in scripts:
            with open(path, encoding='utf-8') as f:
                lines = f.read().splitlines()
            defined = {m.group(1): i for i, line in enumerate(lines) if (m := re.match(r'local function (\w+)', line))}
            for name, at in defined.items():
                for i, line in enumerate(lines[:at]):
                    code = line.split('--', 1)[0]
                    with self.subTest(script=os.path.basename(path), function=name):
                        self.assertNotRegex(code, rf'(?<![\w.:]){name}\(',
                                            f'{name}() is called on line {i + 1}, above its definition on line {at + 1}')


if __name__ == '__main__':
    unittest.main()
