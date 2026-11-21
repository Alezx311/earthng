"""The wood's floor and the still mode: turf.lua's layers and definitions, detail.lua's tufts."""
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

LUA = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r'


class TurfLayersTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.turf = self.lua.execute((LUA / 'turf.lua').read_text(encoding='utf8'))
        self.turf.readyState = True
        self.point = self.lua.eval('function(x, y, z) return {x = x, y = y, z = z or 0} end')

    def test_a_woods_floor_has_its_own_layers(self):
        layer = self.turf.layerOf
        self.assertEqual([layer(f) for f in (512, 1024, 512 + 16, 1024 + 32)], [5, 6, 5, 6])
        self.assertEqual(self.turf.LAYERS[layer(512) + 1], 'e2rTurfForest')
        self.assertEqual(self.turf.LAYERS[layer(1024) + 1], 'e2rTurfPine')
        # a planet without those layers: the floor is no layer at all
        self.turf.woodLayers = False
        self.assertEqual(layer(512), 0)
        self.assertEqual(layer(1024), 0)
        self.assertEqual(layer(16), 2)

    def test_every_definition_names_a_layer_and_a_source(self):
        layers = set(self.turf.LAYERS.values())
        names = set()
        for d in self.turf.DEFS.values():
            self.assertIn(d.layer, layers)
            self.assertIsNotNone(self.turf.SOURCES[d.source], d.source)
            name = d.name or d.src
            self.assertNotIn(name, names, 'two objects of one name would replace each other')
            names.add(name)
            self.assertGreater(d.share, 0)

    def test_every_layer_that_grows_has_something_to_drive_past(self):
        moving = {d.layer for d in self.turf.DEFS.values() if not d.still}
        self.assertEqual(moving, set(self.turf.LAYERS.values()) - {'e2rTurfNone'})

    def test_standing_still_adds_definitions_and_moving_takes_them_back(self):
        defs = list(self.turf.DEFS.values())
        moving = [d for d in defs if self.turf.wanted(d)]
        self.assertTrue(all(not d.still for d in moving))
        self.turf.still = True
        standing = [d for d in defs if self.turf.wanted(d)]
        self.assertEqual(len(standing), len(defs))
        self.assertGreater(len(standing), 2 * len(moving))
        # an older planet: the wood's definitions wait for its layers
        self.turf.woodLayers = False
        old = [d for d in defs if self.turf.wanted(d)]
        self.assertTrue(all(d.layer not in ('e2rTurfForest', 'e2rTurfPine') for d in old))
        self.assertLess(len(old), len(standing))

    def test_a_car_is_still_after_a_moment_of_standing_and_not_while_it_crawls(self):
        motion, point = self.turf.motion, self.point
        t = 0.0
        # driving at 14 m/s
        for k in range(20):
            t += .05
            self.assertFalse(motion(point(k * .7, 0), t))
        # stopped where the last step left it: still only after STILL.after seconds
        x = 19 * .7
        self.assertFalse(motion(point(x, 0), t + .5))
        self.assertFalse(motion(point(x, 0), t + 1.0))
        self.assertTrue(motion(point(x, 0), t + 1.8))
        # crawling at 1.5 m/s keeps what it has; driving off ends it
        self.assertTrue(motion(point(x + .15, 0), t + 1.9))
        self.assertFalse(motion(point(x + .65, 0), t + 2.0))

    def test_a_cameras_jump_is_not_a_drive(self):
        motion, point = self.turf.motion, self.point
        motion(point(0, 0), 0)
        motion(point(0, 0), 1)
        self.assertTrue(motion(point(0, 0), 2.5))
        # a view 300 m away, in one frame: the layers stay
        self.assertTrue(motion(point(300, 40), 2.52))
        self.assertTrue(motion(point(300, 40), 3))


class DetailWoodTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path = '{(LUA.parents[2]).as_posix()}/?.lua;' .. package.path")
        self.detail = self.lua.execute((LUA / 'detail.lua').read_text(encoding='utf8'))

    def patch(self, flags):
        samples = []
        for slot in range(16):
            samples += [slot + flags, 100.0, 0.0, 0.0]
        return self.lua.table_from({'x': 0, 'y': 0, 'samples': self.lua.table_from(samples)})

    def test_the_tufts_leave_a_woods_floor_to_the_engines_grass(self):
        for flags in (512, 1024):
            for level in (0, 1, 2, 3):
                self.assertEqual(self.detail.patchCount(self.patch(flags), level)[0], 0)
        self.assertGreater(self.detail.patchCount(self.patch(0), 0)[0], 0)
        slot, lush, thin, crop, wood = self.detail.sampleOf(5 + 1024)
        self.assertEqual((slot, lush, thin, crop, wood), (5, False, False, None, True))
        self.assertFalse(self.detail.sampleOf(5 + 256 + 128)[4])


if __name__ == '__main__':
    unittest.main()
