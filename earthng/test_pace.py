"""The gate (pace.lua): a scene-changing frame only after calm frames, one a frame.

The engine smooths the frame time it moves the world by, so a lone slow frame is dropped while
two in a row make the game run slow and then fast. These tests drive the gate with frame times.
"""
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/pace.lua'


class GateTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.globals().pace = self.lua.execute(ROOT.read_text(encoding='utf8'))
        self.lua.execute('g = pace.newGate()')
        self.g = self.lua.globals().g

    def frame(self, ms, paused=False, want=True, cost=None):
        """One frame: returns True when the gate let a step run (the step then costs `cost` ms next frame)."""
        self.lua.execute(f'g:beginFrame({ms}, {str(paused).lower()})')
        if want and self.lua.eval('g:open()'):
            self.lua.execute('g:done()')
            return True
        return False

    def test_steps_stand_alone_between_calm_frames(self):
        for _ in range(70):
            self.frame(10, want=False)
        ran, gaps, last = [], [], None
        ms = 10
        for k in range(300):
            went = self.frame(ms)
            # a step frame is slow (its engine cost lands in it), the next ones are calm
            ms = 40 if went else 10
            if went:
                if last is not None:
                    gaps.append(k - last)
                last = k
                ran.append(k)
        self.assertGreater(len(ran), 50)
        self.assertGreaterEqual(min(gaps), 3, 'two scene changes closer than two calm frames')

    def test_one_step_a_frame(self):
        for _ in range(70):
            self.frame(10, want=False)
        self.lua.execute('g:beginFrame(10, false)')
        self.assertTrue(self.lua.eval('g:open()'))
        self.lua.execute('g:done()')
        self.assertFalse(self.lua.eval('g:open()'))

    def test_a_slow_uneven_pc_still_streams(self):
        went = sum(self.frame(30 + (k % 7) * 9) for k in range(400))
        self.assertGreater(went, 40)

    def test_the_timeout_opens_a_gate_that_never_sees_calm(self):
        for _ in range(70):
            self.frame(10, want=False)
        # something else makes every frame slow now: no calm frame for the old median
        went = [self.frame(40) for _ in range(30)]
        self.assertTrue(any(went))
        self.assertGreater(int(self.lua.eval('g.timeouts')), 0)

    def test_open_while_paused(self):
        self.assertTrue(self.frame(200, paused=True))
        self.assertTrue(self.lua.eval('g:open()'))


if __name__ == '__main__':
    unittest.main()
