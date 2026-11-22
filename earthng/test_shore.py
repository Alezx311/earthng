"""Shorelines: the water stands under its banks, the ground meets it at the mapped shore, each
bank has its material (shore.lua, generator.lua WATER.shape / banks / fill)."""
import math
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

import test_generator as harness

ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / 'mod/lua'


def ring(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def flat(z=10, rect=(-100, -100, 1100, 1100)):
    return {'rect': list(rect), 'nx': 2, 'ny': 2, 'heights': [z] * 4}


def water(ident, rings, **tags):
    return {'id': ident, 'kind': 'water', 'tags': tags, 'rings': rings}


class ShoreModuleTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path = '{LUA.as_posix()}/?.lua;' .. package.path")
        self.shore = self.lua.eval("require('ge/extensions/e2r/shore')")

    def index(self, bodies):
        build = self.lua.eval('''function(shore, bodies)
          local function inside(rings, x, y)
            local filled = false
            for _, ring in ipairs(rings) do
              local q = ring[#ring]
              for _, p in ipairs(ring) do
                if (p[2] > y) ~= (q[2] > y) and x < (q[1] - p[1]) * (y - p[2]) / (q[2] - p[2]) + p[1] then filled = not filled end
                q = p
              end
            end
            return filled
          end
          local waters = {}
          for _, rings in ipairs(bodies) do
            local b = {math.huge, math.huge, -math.huge, -math.huge}
            for _, ring in ipairs(rings) do
              for _, p in ipairs(ring) do
                b[1], b[2], b[3], b[4] = math.min(b[1], p[1]), math.min(b[2], p[2]), math.max(b[3], p[1]), math.max(b[4], p[2])
              end
            end
            waters[#waters + 1] = {rings = rings, bounds = b}
          end
          local function wet(x, y)
            for _, w in ipairs(waters) do if inside(w.rings, x, y) then return true end end
            return false
          end
          return shore.index(waters, wet, {0, 0, 500, 500}, 100), wet
        end''')
        table = self.lua.table_from([self.lua.table_from([self.lua.table_from([self.lua.table_from(p) for p in r])
                                                           for r in rings]) for rings in bodies])
        return build(self.shore, table)

    def test_a_body_cut_in_two_by_its_cells_has_no_shore_along_the_cut(self):
        """A pack clips a lake to each cell, 100 m past it: the parts overlap, their cut edges are water."""
        whole, _ = self.index([[ring(100, 100, 400, 300)]])
        halves, _ = self.index([[ring(100, 100, 300, 300)], [ring(200, 100, 400, 300)]])
        # the cut edges (x = 300 of the first part, x = 200 of the second) are not a shore
        self.assertIsNone(self.shore.near(halves, 300, 200, 20))
        self.assertIsNone(self.shore.near(halves, 200, 200, 20))
        for x, y in ((100, 200), (400, 200), (250, 100), (250, 300)):
            d, piece, px, py = self.shore.near(halves, x + 3, y + 3, 20)
            self.assertLess(d, 3.01)
            d2 = self.shore.near(whole, x + 3, y + 3, 20)[0]
            self.assertAlmostEqual(d, d2)

    def test_the_normal_of_a_piece_points_to_the_land(self):
        index, wet = self.index([[ring(100, 100, 400, 300), ring(200, 150, 260, 220)]])
        self.assertGreater(index.count, 20)
        for k in range(1, index.count + 1):
            p = index.pieces[k]
            mx, my = p.ax + p.ux * p.len / 2, p.ay + p.uy * p.len / 2
            self.assertFalse(wet(mx + p.nx, my + p.ny), 'land a metre outside')
            self.assertTrue(wet(mx - p.nx, my - p.ny), 'water a metre inside (an island counts as land)')

    def test_a_bed_falls_from_the_waterline_to_one_depth_for_every_bank(self):
        for name, T in self.shore.TYPES.items():
            with self.subTest(bank=name):
                self.assertEqual(self.shore.depth(T, 0), 0)
                self.assertAlmostEqual(self.shore.depth(T, self.shore.REACH), self.shore.DEEP)
                depths = [self.shore.depth(T, d / 2) for d in range(0, 80)]
                self.assertEqual(depths, sorted(depths))
                self.assertEqual(self.shore.rise(T, 0), 0)
                self.assertAlmostEqual(self.shore.rise(T, 30), T.rise)
                self.assertGreater(T.rise, 0)

    def test_a_band_is_the_part_of_a_triangle_between_its_heights(self):
        T = self.shore.TYPES.sand
        tri = lambda *pts: self.lua.table_from([self.lua.table_from(p) for p in pts])
        # a slope from 1 m under the water to 2 m over it: the sand ends at T.hi
        piece, whole = self.shore.band(T, tri([0, 0, 9, -1, -5], [10, 0, 12, 2, 5], [0, 10, 9, -1, -5]))
        self.assertFalse(whole)
        self.assertAlmostEqual(max(piece[k][4] for k in range(1, len(piece) + 1)), T.hi)
        # all of it in the band
        piece, whole = self.shore.band(T, tri([0, 0, 9, -.2, -1], [10, 0, 9.5, .3, 2], [0, 10, 9, -.2, -1]))
        self.assertTrue(whole)
        # too far from the shoreline however low it lies
        self.assertIsNone(self.shore.band(T, tri([0, 0, 9, .2, 40], [10, 0, 9, .2, 50], [0, 10, 9, .2, 40])))


class ShoreTileTest(unittest.TestCase):
    def setUp(self):
        self.g = harness.GeneratorTests()
        self.g.lua = LuaRuntime(unpack_returned_tuples=True)
        self.g.lua.execute(f"package.path = '{LUA.as_posix()}/?.lua;' .. package.path")
        self.g.generator = self.g.lua.execute(harness.SOURCE.read_text(encoding='utf8'))
        self.shore = self.g.lua.eval("require('ge/extensions/e2r/shore')")

    def build(self, cell, i=0, j=0, **options):
        options.setdefault('maxTrees', 0)
        options.setdefault('maxGrass', 0)
        return self.g.build([cell], i, j, **options)

    def blocks(self, scene):
        return [it for it in self.g.water_items(scene) if it.kind == 'water']

    def ground(self, road, scene=None):
        """Every triangle of the drawn ground: the lattice (road layer) in any land material."""
        found = []
        for manifest in (road,):
            for item, mesh in self.g.meshes(manifest):
                name = str(mesh.material)
                if name.startswith('e2rf_col_') or name in ('e2rf_road', 'e2rf_road_major'):
                    continue
                found += list(self.g.triangles(manifest, name))
        return found

    def height(self, triangles, x, y):
        return self.g.surface_at(triangles, x, y)

    def test_the_water_of_a_lake_stands_under_its_banks(self):
        lake = water('lake', [ring(150, 150, 350, 350)], water='lake')
        road, scene = self.build({'terrain': flat(10), 'areas': [lake]})[:2]
        blocks = self.blocks(scene)
        self.assertTrue(blocks)
        level = blocks[0].pos[3]
        self.assertTrue(all(abs(b.pos[3] - level) < 1e-9 for b in blocks))
        self.assertAlmostEqual(level, 10 - self.shore.DROP)
        ground = self.ground(road)
        # the land round the lake is over the water, the bed under it
        for x, y in ((140, 250), (360, 250), (250, 140), (250, 360), (120, 120), (380, 380)):
            self.assertGreater(self.height(ground, x, y), level + .05, (x, y))
        for x, y in ((160, 250), (340, 250), (250, 160), (250, 340), (250, 250)):
            self.assertLess(self.height(ground, x, y), level - .05, (x, y))
        self.assertAlmostEqual(self.height(ground, 250, 250), level - self.shore.DEEP, delta=.1)

    def test_the_waterline_follows_the_mapped_shore(self):
        """Where the drawn ground crosses the water's level, a few metres from the polygon at most."""
        lake = water('lake', [[[130, 130], [372, 141], [361, 368], [147, 352]]], water='lake')
        road, scene = self.build({'terrain': flat(10), 'areas': [lake]})[:2]
        level = self.blocks(scene)[0].pos[3]
        ground = self.ground(road)
        worst = 0
        for y in range(160, 340, 7):
            row = [(x / 2, self.height(ground, x / 2, y)) for x in range(200, 800)]
            wet = [x for x, z in row if z is not None and z < level]
            # the mapped shore on this row (the polygon's west and east edges)
            west = 130 + (147 - 130) * (y - 130) / (352 - 130)
            east = 372 + (361 - 372) * (y - 141) / (368 - 141)
            worst = max(worst, abs(min(wet) - west), abs(max(wet) - east))
        self.assertLess(worst, 4.5)

    def test_the_cover_shows_water_only_where_the_ground_is_under_it(self):
        lake = water('lake', [[[130, 130], [372, 141], [361, 368], [147, 352]]], water='lake')
        road, scene = self.build({'terrain': flat(10), 'areas': [lake]})[:2]
        blocks = self.blocks(scene)
        level = blocks[0].pos[3]
        ground = self.ground(road)

        def covered(x, y):
            return any(abs(x - b.pos[1]) <= b.scale[1] / 2 and abs(y - b.pos[2]) <= b.scale[2] / 2 for b in blocks)
        missed = flooded = 0
        for gy in range(100, 400, 3):
            for gx in range(100, 400, 3):
                z = self.height(ground, gx + .5, gy + .5)
                if z is None:
                    continue
                # (a dip of a few centimetres between a cell's nine samples is not seen as a hole)
                if z < level - .05 and not covered(gx + .5, gy + .5):
                    missed += 1
                # a block may lie under the land (it does not show there), never far from the water
                if covered(gx + .5, gy + .5) and z > level + self.shore.TYPES.rock.rise + .3:
                    flooded += 1
        self.assertEqual(missed, 0, 'ground under the water with no water over it')
        self.assertEqual(flooded, 0)

    def test_a_pond_narrower_than_the_lattice_still_has_its_bed(self):
        pond = water('pond', [ring(203, 204, 211, 210)], water='pond')
        road, scene = self.build({'terrain': flat(10), 'areas': [pond]})[:2]
        blocks = self.blocks(scene)
        self.assertTrue(blocks)
        level = blocks[0].pos[3]
        self.assertLess(level, 10)
        ground = self.ground(road)
        self.assertLess(self.height(ground, 207, 207), level - .05)
        # and the land a lattice cell away is dry
        for x, y in ((185, 207), (229, 207), (207, 186), (207, 228)):
            self.assertGreater(self.height(ground, x, y), level, (x, y))

    def test_a_low_bank_is_raised_over_the_water(self):
        """The DEM dips under a reservoir's level behind its dam: the bank is at least its rise."""
        heights = [10 if x < 2 else 6 for y in range(3) for x in range(3)]
        grid = {'rect': [0, 0, 500, 500], 'nx': 3, 'ny': 3, 'heights': heights}
        lake = water('res', [ring(60, 100, 240, 400)], water='reservoir', ele='10')
        road, scene = self.build({'terrain': grid, 'areas': [lake]}, seaLevel=0)[:2]
        level = self.blocks(scene)[0].pos[3]
        self.assertAlmostEqual(level, 10)
        ground = self.ground(road)
        for x in (242, 246, 252, 262):
            self.assertGreater(self.height(ground, x, 250), level, x)
        # far from the shore the land is the DEM's again
        self.assertLess(self.height(ground, 400, 250), 8)

    def test_neighbour_tiles_agree_on_the_ground_of_a_shared_shore(self):
        lake = water('lake', [[[380, 120], [640, 150], [610, 380], [420, 340]]], water='lake', ele='9.8')
        cell = {'terrain': flat(10, (-100, -100, 1100, 600)), 'areas': [lake]}
        west = self.ground(self.build(cell, 0, 0, seaLevel=0)[0])
        east = self.ground(self.build(cell, 1, 0, seaLevel=0)[0])
        # (the shore crosses the shared edge: the test is of shaped ground, not of flat land)
        self.assertLess(min(self.height(west, 499.99, y) for y in range(150, 350, 10)), 9.5)
        for y in range(5, 500, 10):
            a, b = self.height(west, 499.99, y), self.height(east, 500.01, y)
            self.assertAlmostEqual(a, b, delta=.02, msg=y)

    def test_a_far_tile_meets_the_near_tile_along_a_shore(self):
        """The far ring shapes the same nodes: no step in the ground where a near tile ends in a lake."""
        lake = water('lake', [[[380, 120], [640, 150], [610, 380], [420, 340]]], water='lake', ele='9.8')
        cell = {'terrain': flat(10, (-100, -100, 1100, 600)), 'areas': [lake]}
        near = self.ground(self.build(cell, 0, 0, seaLevel=0)[0])
        built = self.build(cell, 1, 0, seaLevel=0, far=True)
        far = []
        for manifest in built[:3]:
            for item, mesh in self.g.meshes(manifest):
                if not str(mesh.material).startswith('e2rf_col_'):
                    far += list(self.g.triangles(manifest, str(mesh.material)))
        self.assertTrue(far)
        self.assertFalse(self.g.water_items(built[2]), 'a far tile draws no water objects')
        for y in range(0, 501, 25):
            a, b = self.height(near, 499.99, y + .01), self.height(far, 500.01, y + .01)
            if a is not None and b is not None:
                self.assertAlmostEqual(a, b, delta=.05, msg=y)

    def test_banks_are_drawn_in_their_own_material(self):
        beach = {'id': 'beach', 'kind': 'beach', 'tags': {'natural': 'beach'}, 'rings': [ring(120, 120, 380, 150)]}
        rock = {'id': 'rock', 'kind': 'bare_rock', 'tags': {'natural': 'bare_rock'}, 'rings': [ring(350, 120, 400, 380)]}
        marsh = {'id': 'marsh', 'kind': 'wetland', 'tags': {'natural': 'wetland'}, 'rings': [ring(100, 150, 150, 380)]}
        lake = water('lake', [ring(150, 150, 350, 350)], water='lake')
        road, scene = self.build({'terrain': flat(10), 'areas': [lake, beach, rock, marsh]})[:2]
        level = self.blocks(scene)[0].pos[3]

        def material_at(x, y):
            found = set()
            for manifest in (road, scene):
                for item, mesh in self.g.meshes(manifest):
                    name = str(mesh.material)
                    if name.startswith('e2rf_col_'):
                        continue
                    if self.g.surface_at(list(self.g.triangles(manifest, name)), x, y) is not None:
                        found.add(name)
            return found
        # the bed under the south shore's shallows is the beach's sand, the east shore's is rock
        self.assertIn('e2rf_beach', material_at(250, 153))
        self.assertIn('e2rf_bare_rock', material_at(347, 250))
        self.assertIn('e2rf_wetland', material_at(153, 250))
        # deep water keeps the plain bed
        self.assertEqual(material_at(250, 250), {'e2rf_bare_ground'})

    def coast(self):
        """Land in the west at 22 m to x = 150, the sea's bed east of it at 18 m (the sea plane is 20.3)."""
        size = 21
        heights = [22. if x <= 6 else 18. for y in range(size) for x in range(size)]
        return {'rect': [0, 0, 500, 500], 'nx': size, 'ny': size, 'heights': heights}

    def test_a_tidal_harbour_is_the_seas_own_water(self):
        """Its DEM lies under the sea plane: no lake 2 m under the sea, and no bank where it opens to the sea."""
        harbour = water('harbour', [ring(150, 150, 300, 350)], water='harbour')
        road, scene = self.build({'terrain': self.coast(), 'areas': [harbour]}, seaLevel=20)[:2]
        items = self.g.water_items(scene)
        self.assertTrue(items)
        self.assertEqual({it.look for it in items}, {'sea'})
        self.assertTrue(all(abs(it.pos[3] - 20.3) < 1e-9 for it in items))
        ground = self.ground(road)
        # the harbour's basin is cut into the land, under the sea plane
        self.assertLess(self.height(ground, 180, 250), 20.3 - .3)
        # its quay on the land's side stands over the water
        self.assertGreater(self.height(ground, 140, 250), 20.3 + .3)
        # where the basin opens onto the sea the bed goes on: no mole raised along the polygon's edge
        for x in (270, 290, 305, 320):
            self.assertLess(self.height(ground, x, 250), 20.3 - .3, x)

    def test_the_seas_cover_ends_where_the_ground_comes_out(self):
        road, scene = self.build({'terrain': self.coast()}, seaLevel=20)[:2]
        blocks = [it for it in self.g.water_items(scene) if it.look == 'sea']
        self.assertTrue(blocks)
        ground = self.ground(road)

        def covered(x, y):
            return any(abs(x - b.pos[1]) <= b.scale[1] / 2 and abs(y - b.pos[2]) <= b.scale[2] / 2 for b in blocks)
        for y in range(20, 480, 23):
            for x in range(100, 300, 3):
                z = self.height(ground, x + .5, y + .5)
                if z is not None and z < 20.3 - .05:
                    self.assertTrue(covered(x + .5, y + .5), (x, y, z))
        # the coast has its own material where the land comes out of the sea
        shore = [m for m in ('e2rf_beach', 'e2rf_scree', 'e2rf_bare_rock')
                 if list(self.g.triangles(road, m)) or list(self.g.triangles(scene, m))]
        self.assertTrue(shore)

    def test_shorelines_off_keeps_the_water_on_its_dem(self):
        lake = water('lake', [ring(150, 150, 350, 350)], water='lake')
        for options in ({'shore': False}, {'realStyle': False}):
            with self.subTest(**options):
                scene = self.build({'terrain': flat(10), 'areas': [lake]}, **options)[1]
                self.assertAlmostEqual(self.blocks(scene)[0].pos[3], 10.3)

    def test_a_river_lies_under_its_banks_all_along(self):
        """A narrow river: a River whose nodes follow the level of each place, under the bank there."""
        size = 21
        # the valley falls 4 m to the east over 1 km
        heights = [20 - x * .2 for y in range(size) for x in range(size)]
        grid = {'rect': [0, 0, 1000, 1000], 'nx': size, 'ny': size, 'heights': heights}
        river = water('river', [ring(0, 225, 1000, 265)], water='river')
        road, scene = self.build({'terrain': grid, 'areas': [river]})[:2]
        rivers = [it for it in self.g.water_items(scene) if it.kind == 'river']
        self.assertTrue(rivers)
        ground = self.ground(road)
        for node in self.g.plain(rivers[0].nodes):
            x, y, z = node[0], node[1], node[2]
            if 20 < x < 480:
                self.assertGreater(self.height(ground, x, 210), z, x)
                self.assertGreater(self.height(ground, x, 280), z, x)
                self.assertLess(self.height(ground, x, 245), z, x)


if __name__ == '__main__':
    unittest.main()
