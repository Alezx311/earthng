"""The engine's grass on a hidden terrain block (mod/lua/ge/extensions/e2r/turf.lua, earthng/turf_art.py):
what can be checked outside the game. Needs lupa."""
import json
import struct
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import turf_art

try:
    from lupa.luajit21 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA = HERE.parent / 'mod/lua/ge/extensions/e2r'


class LevelFilesTests(unittest.TestCase):
    def test_the_level_has_a_material_for_every_layer_and_their_maps(self):
        files = turf_art.level_files('e2r_world')
        defs = json.loads(files['levels/e2r_world/art/terrains/main.materials.json'])
        names = [name for name, _ in turf_art.LAYERS]
        self.assertEqual(names[0], 'e2rTurfNone')
        for name, ground in turf_art.LAYERS:
            m = defs[name]
            self.assertEqual((m['class'], m['internalName'], m['groundmodelName']), ('TerrainMaterial', name, ground))
            for key, value in m.items():
                if key.endswith('Tex'):
                    self.assertIn(value.lstrip('/'), files, key)
        texture_set = defs[turf_art.TEXTURE_SET]
        self.assertEqual(texture_set['class'], 'TerrainMaterialTextureSet')
        self.assertEqual(texture_set['baseTexSize'], [turf_art.SIZE] * 2)
        # every object keeps its id from build to build
        again = json.loads(turf_art.level_files('e2r_world')['levels/e2r_world/art/terrains/main.materials.json'])
        self.assertEqual({k: v['persistentId'] for k, v in defs.items()}, {k: v['persistentId'] for k, v in again.items()})
        self.assertEqual(len({v['persistentId'] for v in defs.values()}), len(defs))

    def test_the_planet_carries_them(self):
        import build_mod
        files = build_mod.level_files('en')
        self.assertIn('levels/e2r_world/art/terrains/main.materials.json', files)
        self.assertIn('levels/e2r_world/art/terrains/turf_b.png', files)


@unittest.skipIf(LuaRuntime is None, 'needs lupa.luajit21')
class TurfTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.turf = self.lua.execute((LUA / 'turf.lua').read_text(encoding='utf8'))
        # outside the game: the level's layers are taken as there
        self.turf.readyState = True
        self.lua.execute('function HEX(s) return (s:gsub(".", function(c) return string.format("%02x", c:byte()) end)) end')

    def patch(self, x, y, samples):
        """A lawn patch as generator.lua lawnCarpet makes it: (slot + flags, z, gx, gy) a square."""
        flat = [v for sample in samples for v in sample]
        return self.lua.table_from({'x': x, 'y': y, 'samples': self.lua.table_from(flat)})

    def test_layers_are_the_levels_materials_in_order(self):
        self.assertEqual(list(self.turf.LAYERS.values()), [name for name, _ in turf_art.LAYERS])
        self.assertEqual(self.turf.TEXTURE_SET, turf_art.TEXTURE_SET)

    def test_a_samples_flags_pick_its_layer(self):
        layer = self.turf.layerOf
        self.assertEqual([layer(f) for f in (0, 16, 32, 64, 128, 128 + 256, 16 + 32)], [1, 2, 3, 4, 2, 2, 3])

    def test_the_block_sits_on_the_lawns_lattice_round_the_car(self):
        x0, y0 = self.turf.originFor(1234.5, -987.0)
        self.assertEqual((x0 % 8, y0 % 8), (0, 0))
        span = (self.turf.N - 1) * self.turf.SQUARE
        self.assertLess(abs(x0 + span / 2 - 1234.5), 4.01)
        self.assertLess(abs(y0 + span / 2 + 987.0), 4.01)

    def gather(self, x0, y0):
        read = self.lua.eval('''function(turf, x0, y0)
          local heights, layers, base, range, squares = turf.gather(x0, y0)
          if not heights then return nil end
          local N = turf.N
          return {base = base, range = range, squares = squares,
            h = function(cx, cy) return heights[cy * N + cx] end, l = function(cx, cy) return layers[cy * N + cx] end,
            ter = function() return HEX(turf.terBytes(heights, layers)) end}
        end''')
        return read(self.turf, x0, y0)

    def test_a_patch_becomes_squares_of_its_layer_at_the_grounds_height(self):
        tile = self.lua.table()
        # two squares of a patch at (800, 400): the common lawn on a slope to the east, a lush one
        self.assertTrue(self.turf.take(tile, self.patch(800, 400, [(0, 100.0, .1, 0), (5 + 16, 101.0, 0, 0)])))
        out = self.gather(0, 0)
        self.assertEqual(out.squares, 2)
        cx, cy = 400, 200
        self.assertEqual(out.l(cx, cy), 1)
        self.assertEqual(out.l(cx + 1, cy + 1), 2)
        self.assertEqual(out.l(cx + 2, cy), 0)
        self.assertEqual(out.l(cx - 1, cy), 0)

        def z(v):
            return out.base + v * out.range / 65535
        sink = self.turf.SINK
        # the first square's corners lie on its plane: 10 % up to the east, a square is 2 m
        self.assertAlmostEqual(z(out.h(cx, cy)), 100 - .1 - sink, delta=.01)
        self.assertAlmostEqual(z(out.h(cx, cy + 1)), 100 - .1 - sink, delta=.01)
        # the corner it shares with the lush square takes the lower of the two (100.1 and 101)
        self.assertAlmostEqual(z(out.h(cx + 1, cy + 1)), 100 + .1 - sink, delta=.01)
        self.assertAlmostEqual(z(out.h(cx + 2, cy + 2)), 101 - sink, delta=.01)
        # nothing is over the ground, and where there is no lawn the block lies far under it
        self.assertEqual(out.h(cx + 5, cy + 5), 0)
        self.assertLessEqual(out.base, 100 - self.turf.DEEP)
        self.assertGreater(out.base + out.range, 101)

    def test_the_range_grows_with_the_relief_and_patches_outside_are_left(self):
        tile = self.lua.table()
        self.turf.take(tile, self.patch(80, 80, [(0, 10.0, 0, 0)]))
        self.turf.take(tile, self.patch(400, 400, [(0, 290.0, 0, 0)]))
        self.turf.take(tile, self.patch(-64, 80, [(0, 5000.0, 0, 0)]))     # west of the block
        self.turf.take(tile, self.patch(1016, 80, [(0, 5000.0, 0, 0)]))    # across its east edge
        out = self.gather(0, 0)
        self.assertEqual(out.squares, 2)
        self.assertEqual(out.range, 512)
        self.assertEqual(self.gather(4000, 4000), None)

    def test_a_tile_that_goes_takes_its_lawn_with_it(self):
        a, b = self.lua.table(), self.lua.table()
        self.turf.take(a, self.patch(80, 80, [(0, 10.0, 0, 0)]))
        self.turf.take(b, self.patch(160, 80, [(0, 10.0, 0, 0), (1, 10.0, 0, 0)]))
        self.assertEqual(self.gather(0, 0).squares, 3)
        self.turf.remove(a)
        self.assertEqual(self.gather(0, 0).squares, 2)
        self.turf.remove(b)
        self.assertIsNone(self.gather(0, 0))

    def test_the_terrain_file_is_the_games_format(self):
        tile = self.lua.table()
        self.turf.take(tile, self.patch(8, 16, [(0, 50.0, 0, 0)]))
        out = self.gather(0, 0)
        data = bytes.fromhex(out.ter())
        n = self.turf.N
        # version 9, size, heights (2 bytes a sample), layers (1), the material names (a stock level's file)
        self.assertEqual(data[0], 9)
        self.assertEqual(struct.unpack_from('<I', data, 1)[0], n)
        at = 5 + n * n * 3
        self.assertEqual(struct.unpack_from('<I', data, at)[0], len(turf_art.LAYERS))
        at += 4
        names = []
        for _ in turf_art.LAYERS:
            names.append(data[at + 1:at + 1 + data[at]].decode())
            at += 1 + data[at]
        self.assertEqual(names, [name for name, _ in turf_art.LAYERS])
        self.assertEqual(at, len(data))
        # the square (4, 8): its layer, and its south-west corner's height in the row-by-row maps
        cx, cy = 4, 8
        self.assertEqual(data[5 + n * n * 2 + cy * n + cx], 1)
        self.assertEqual(struct.unpack_from('<H', data, 5 + 2 * (cy * n + cx))[0], out.h(cx, cy))
        self.assertGreater(out.h(cx, cy), 0)

    def test_stock_ground_cover_is_bound_to_our_layer_and_thinned(self):
        null = object()
        stock = self.lua.table_from({
            'name': 'small_grass_close', 'class': 'GroundCover', 'maxElements': 306000, 'radius': 50, 'dissolveRadius': 30,
            'material': 'm_grass_green_short_01', 'position': self.lua.table_from([1, 2, 3]),
            'Types': self.lua.table_from([
                self.lua.table_from({'layer': 'Grass', 'sizeMax': .3, 'billboardUVs': self.lua.table_from([0, .5, 1, .25])}),
                self.lua.table_from({'layer': 'RockyDirt', 'sizeMax': .5}),
                self.lua.table_from({'layer': '', 'sizeMax': .1})])})
        calls = self.turf.fieldsFor(stock, 'e2rTurfGrass', .25, 1.5, null)
        got = {(c[1], c[2]): c[3] for c in calls.values()}
        self.assertEqual(got[('maxElements', 0)], '76500')
        self.assertEqual(got[('radius', 0)], '75')
        self.assertEqual(got[('dissolveRadius', 0)], '45')
        self.assertEqual(got[('material', 0)], 'm_grass_green_short_01')
        # every type that grew on some stock layer grows on ours; an empty one stays empty
        self.assertEqual((got[('layer', 0)], got[('layer', 1)], got[('layer', 2)]), ('e2rTurfGrass', 'e2rTurfGrass', ''))
        self.assertEqual(got[('billboardUVs', 0)], '0 0.5 1 0.25')
        # the stock object's own name and place are not copied
        self.assertNotIn(('name', 0), got)
        self.assertNotIn(('position', 0), got)

    def test_off_or_without_the_levels_layers_the_lawn_keeps_its_tufts(self):
        tile = self.lua.table()
        self.turf.readyState = False
        self.assertFalse(self.turf.take(tile, self.patch(8, 16, [(0, 50.0, 0, 0)])))
        self.turf.readyState = True
        self.turf.enabled = False
        self.assertFalse(self.turf.take(tile, self.patch(8, 16, [(0, 50.0, 0, 0)])))
        self.assertFalse(self.turf.active())

    def test_only_the_real_pack_grows_it(self):
        self.lua.execute('scenetree = {findObject = function() return nil end}')
        tile = self.lua.table()
        self.assertTrue(self.turf.take(tile, self.patch(8, 16, [(0, 50.0, 0, 0)])))
        # another texture pack: the lawn held is let go (its tiles are built again as tufts)
        self.turf.setReal(False)
        self.assertFalse(self.turf.active())
        self.assertIsNone(self.gather(0, 0))
        self.assertFalse(self.turf.take(tile, self.patch(8, 16, [(0, 50.0, 0, 0)])))
        self.turf.setReal(True)
        self.assertTrue(self.turf.take(tile, self.patch(8, 16, [(0, 50.0, 0, 0)])))
        self.assertEqual(self.gather(0, 0).squares, 1)

    def test_new_lawn_counts_only_near_the_car(self):
        tile = self.lua.table()
        self.assertFalse(self.turf.freshNear(100, 100))
        self.turf.take(tile, self.patch(400, 96, [(0, 50.0, 0, 0)]))
        # 300 m away: the grass does not reach it, the block's next move will take it
        self.assertFalse(self.turf.freshNear(100, 100))
        self.assertTrue(self.turf.freshNear(300, 100))
        self.turf.take(tile, self.patch(-64, 96, [(0, 50.0, 0, 0)]))
        self.assertTrue(self.turf.freshNear(100, 100))

    def test_the_qualitys_grass_settings_scale_it(self):
        f = self.turf.factors
        self.assertEqual(f(self.lua.table_from({'grassM': 100, 'grassBudget': 9000})), (1, 1))
        density, distance = f(self.lua.table_from({'grassM': 45, 'grassBudget': 600}))
        self.assertAlmostEqual(density, .3)
        self.assertAlmostEqual(distance, .6)
        density, distance = f(self.lua.table_from({'grassM': 220, 'grassBudget': 14000}))
        self.assertAlmostEqual(density, 1.5)
        self.assertAlmostEqual(distance, 1.4)
        # no grass asked for at all
        self.assertEqual(f(self.lua.table_from({'grassM': 0, 'grassBudget': 9000})), (0, 0))


if __name__ == '__main__':
    unittest.main()
