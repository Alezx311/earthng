import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

SOURCE = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/gc.lua'


class CollectorStep(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        # each read of a timer is 0.1 ms later; the collector's step and full collection are counted,
        # the rest (setstepmul) is the real one
        self.lua.execute('''
          -- the frame's clock (stopAndReset) reads frameMs
          frameMs = 16
          hptimer = function() local t = 0
            return {stop = function() t = t + 0.1; return t end, stopAndReset = function() return frameMs end} end
          real = collectgarbage
          steps, collects, cycleEnds = 0, 0, false
          collectgarbage = function(what, arg)
            if what == 'step' then steps = steps + 1; return cycleEnds end
            if what == 'collect' then collects = collects + 1; return 0 end
            return real(what, arg)
          end
          real('setstepmul', 200)
          heap = 300 * 1024
        ''')
        self.lua.globals().gc = self.lua.execute(SOURCE.read_text(encoding='utf8'))
        self.lua.execute('gc.count = function() return heap end')

    def stepmul(self):
        return self.lua.eval("(function() local m = real('setstepmul', 200); real('setstepmul', m); return m end)()")

    def drive(self, mb, frame_ms=16):
        """One driving frame at this heap, after a frame of frame_ms; the collector steps it took."""
        self.lua.execute(f'steps = 0; frameMs = {frame_ms}; heap = {mb} * 1024; gc.step(true, .016)')
        return self.lua.eval('steps')

    def test_lowered_in_the_level_and_restored_outside(self):
        self.lua.execute('gc.step(true, .016)')
        self.assertEqual(self.stepmul(), 100)
        self.assertTrue(self.lua.eval('gc.lowered()'))
        self.lua.execute('gc.step(false)')
        self.assertEqual(self.stepmul(), 200)
        self.assertFalse(self.lua.eval('gc.lowered()'))

    def test_restores_what_was_set_before_entering(self):
        self.lua.execute("real('setstepmul', 300); gc.step(true, .016)")
        self.assertEqual(self.stepmul(), 100)
        self.lua.execute('gc.step(false)')
        self.assertEqual(self.stepmul(), 300)

    def test_no_slice_while_the_heap_is_near_the_live_heap(self):
        self.drive(300)
        self.assertEqual(self.drive(305), 0)
        self.assertEqual(self.drive(325), 0)   # a third of the room (SPAN while no engine's collection is seen)

    def test_the_slice_grows_with_the_garbage(self):
        self.drive(300)
        some = self.drive(335)     # under half of the room
        more = self.drive(350)     # two thirds
        rush = self.drive(380)     # over PACE_FULL
        self.assertGreater(some, 0)
        self.assertGreater(more, some)
        self.assertGreater(rush, more)
        # the slices stay within their budgets (0.1 ms a timer read)
        self.assertLessEqual(rush, self.lua.eval('gc.PACE_RUSH_MS') / 0.1 + 1)

    def test_a_cycle_that_ends_measures_from_the_heap_it_leaves(self):
        self.drive(300)
        self.lua.execute('cycleEnds = true')
        self.assertEqual(self.drive(340), 1)      # one step ended the cycle
        self.lua.execute('cycleEnds = false')
        self.assertEqual(self.drive(342), 0)      # 340 MB is the live heap now
        self.assertEqual(self.lua.eval('gc.cycles'), 1)
        self.assertEqual(self.lua.eval('gc.report().cycleLog[1]'), '0.0 s 340 MB')

    def test_the_engines_full_collection_sets_the_room(self):
        self.drive(300)
        self.drive(390)
        # the heap fell in a long frame: the engine collected (to 310 MB)
        self.assertEqual(self.drive(310, frame_ms=400), 0)
        self.assertEqual(self.lua.eval('gc.engineCollections'), 1)
        # the room is up to MARGIN under its 4/3 of 310 MB (389 MB)
        self.assertEqual(self.drive(330), 0)
        self.assertGreater(self.drive(355), 0)

    def test_a_fall_in_an_ordinary_frame_is_a_sweep_not_the_engine(self):
        self.drive(300)
        self.drive(390)
        self.drive(310, frame_ms=170)   # a slow scene object: under ENGINE_MS_PER_MB x 310
        self.assertIsNone(self.lua.eval('gc.engineCollections'))
        self.assertEqual(self.lua.eval('gc.report().sweepLog[1]'), '0.0 s 310 MB from 390, frame 170 ms, LuaGC -')

    def test_the_engines_own_collector_time_tells_its_collection(self):
        self.lua.execute('Engine = {Debug = {getLastPerformanceMetrics = function(t) t.LuaGC = luaGC end}}; luaGC = 0.3')
        self.drive(300)
        self.drive(390)
        self.drive(310, frame_ms=400)     # a long frame, but the engine's collector took 0.3 ms
        self.assertIsNone(self.lua.eval('gc.engineCollections'))
        self.drive(390)
        self.lua.execute('luaGC = 420')
        self.drive(310, frame_ms=90)      # the metric decides, not the frame
        self.assertEqual(self.lua.eval('gc.engineCollections'), 1)

    def test_the_landing_steps_little_until_the_heap_is_over_its_cap(self):
        self.lua.execute('gc.step(true, .016); heap = 700 * 1024; gc.step(true, .016, true)')
        self.assertEqual(self.stepmul(), 10)
        self.lua.execute('heap = 1400 * 1024; gc.step(true, .016, true)')
        self.assertEqual(self.stepmul(), 200)
        self.lua.execute('heap = 900 * 1024; gc.step(true, .016, true)')
        self.assertEqual(self.stepmul(), 10)
        # the landing takes no slices; the drive starts from what it left: that is the live heap
        self.assertEqual(self.lua.eval('steps'), 0)
        self.assertEqual(self.drive(900), 0)
        self.assertEqual(self.stepmul(), 100)

    def test_the_touch_down_holds_an_array_through_the_engines_collection(self):
        self.lua.execute('gc.step(true, .016, true)')
        self.lua.execute('gc.nudge()')
        self.assertEqual(self.lua.eval('collects'), 0)
        held = self.lua.eval('gc.nudgeMb.held')
        self.assertAlmostEqual(held, 300 * self.lua.eval('gc.HELD'))
        # the arrays are garbage for the engine to free, not a reason to slice
        self.assertEqual(self.drive(420), 0)
        # the engine's full collection came in the second frame; it left 280 MB and the held array
        self.drive(280 + held, frame_ms=400)
        self.assertEqual(self.lua.eval('gc.nudgeFrames'), 1)
        self.assertEqual(self.lua.eval('collects'), 0)
        # it counts from both, the drive from 280 MB: 50 MB of garbage is a quarter of the room
        self.assertEqual(self.drive(330), 0)
        self.assertLess(self.lua.eval('gc.used'), self.lua.eval('gc.PACE_FROM'))

    def test_the_landings_collection_sizes_the_garbage(self):
        self.lua.execute('gc.step(true, .016, true); heap = 500 * 1024; gc.step(true, .016, true)')
        self.lua.execute('frameMs = 400; heap = 300 * 1024; gc.step(true, .016, true)')
        self.lua.execute('frameMs = 16; heap = 350 * 1024; gc.step(true, .016, true); gc.nudge()')
        self.assertEqual(self.lua.eval('gc.nudgeMb.landingRef'), 300)
        # 350 MB and the held array are over 4/3 of 300 MB already: the least garbage
        self.assertAlmostEqual(self.lua.eval('gc.nudgeMb.garbage'), 350 * self.lua.eval('gc.NUDGE_MIN'))

    def test_without_the_engines_collection_the_touch_down_collects_itself(self):
        self.lua.execute('gc.step(true, .016, true); gc.nudge()')
        frames = self.lua.eval('gc.NUDGE_FRAMES')
        for _ in range(frames):
            self.drive(420)
        self.assertEqual(self.lua.eval('collects'), 0)
        self.drive(420)
        self.assertEqual(self.lua.eval('collects'), 1)


if __name__ == '__main__':
    unittest.main()
