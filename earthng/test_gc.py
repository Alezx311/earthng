import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

SOURCE = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/gc.lua'


class CollectorStep(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().gc = self.lua.execute(SOURCE.read_text(encoding='utf8'))
        self.lua.execute("collectgarbage('setstepmul', 200); heap = 300 * 1024; gc.count = function() return heap end")

    def stepmul(self):
        return self.lua.eval("(function() local m = collectgarbage('setstepmul', 200); collectgarbage('setstepmul', m); return m end)()")

    def test_lowered_in_the_level_and_restored_outside(self):
        self.lua.execute('gc.step(true, .016)')
        self.assertEqual(self.stepmul(), 100)
        self.assertTrue(self.lua.eval('gc.lowered()'))
        self.lua.execute('heap = 340 * 1024; gc.step(true, .016)')
        self.assertEqual(self.stepmul(), 100)
        self.lua.execute('gc.step(false)')
        self.assertEqual(self.stepmul(), 200)
        self.assertFalse(self.lua.eval('gc.lowered()'))

    def test_garbage_piling_over_the_floor_gets_the_default_back(self):
        self.lua.execute('gc.step(true, .016); heap = 410 * 1024; gc.step(true, .016)')
        self.assertEqual(self.stepmul(), 200)
        # still over BACK_MB: the default stays
        self.lua.execute('heap = 360 * 1024; gc.step(true, .016)')
        self.assertEqual(self.stepmul(), 200)
        # a sweep brought the heap down to the floor
        self.lua.execute('heap = 310 * 1024; gc.step(true, .016)')
        self.assertEqual(self.stepmul(), 100)

    def test_the_floor_follows_a_live_heap_that_grows_slowly(self):
        # 200 MB more live data over ten minutes is not garbage piling up
        self.lua.execute('gc.step(true, .016); for k = 1, 600 do heap = (300 + k / 3) * 1024; gc.step(true, 1) end')
        self.assertEqual(self.stepmul(), 100)

    def test_restores_what_was_set_before_entering(self):
        self.lua.execute("collectgarbage('setstepmul', 300); gc.step(true, .016); heap = 500 * 1024; gc.step(true, .016)")
        self.assertEqual(self.stepmul(), 300)
        self.lua.execute('gc.step(false)')
        self.assertEqual(self.stepmul(), 300)


if __name__ == '__main__':
    unittest.main()
