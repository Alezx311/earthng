"""22.11: the lawn up to the road (generator.lua VEG.verge), a far tile's trees as cards
(VEG.CARD) and the ground cover's sets by climate (turf.lua M.SETS); needs lupa."""
import math
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

LUA = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r'


def line(x0, y0, x1, y1, z=20):
    n = math.ceil(math.hypot(x1 - x0, y1 - y0) / 20)
    return [[x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n, z] for k in range(n + 1)]


class Tile(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.generator = self.lua.execute((LUA / 'generator.lua').read_text(encoding='utf8'))

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def build(self, cells, **options):
        options.setdefault('relief', False)
        options.setdefault('land', False)
        options['tune'] = {'lanes': 0, 'crown': 0, 'ruts': 0, **(options.get('tune') or {})}
        return self.generator.build(self.table(cells), 0, 0, self.table(options))


class VergeLawnTests(Tile):
    """A service road along y = 250, 4 m wide: its edges at y = 248 and 252."""

    def squares(self, **options):
        cell = {'roads': [{'id': 'r', 'width': 4, 'points': line(-100, 250, 600, 250), 'tags': {'highway': 'service'}}],
                'terrain': {'rect': [-500, -500, 1000, 1000], 'nx': 2, 'ny': 2, 'heights': [20] * 4}}
        scene = self.build([cell], **options)[1]
        out = {}
        for item in scene['items'].values():
            patch = item.grassPatch
            if patch:
                samples = list(patch.samples.values())
                for k in range(0, len(samples), 4):
                    slot = int(samples[k]) % 16
                    x, y = patch.x + (slot % 4) * 2 + 1, patch.y + (slot // 4) * 2 + 1
                    out[(round(x), round(y))] = (int(samples[k]) - slot, samples[k + 1], samples[k + 2], samples[k + 3])
        return out

    def test_without_the_turf_the_lawn_stands_off_the_road_as_before(self):
        squares = self.squares()
        row = [squares.get((x, 253)) for x in range(101, 400, 2)]
        self.assertFalse(any(row))
        self.assertTrue(all(squares.get((x, 255)) for x in range(101, 400, 2)))
        self.assertTrue(all(flag < 2048 for flag, _, _, _ in squares.values()))

    def test_with_the_turf_the_lawn_comes_to_the_road_and_leans_down_to_it(self):
        squares = self.squares(turf=True)
        V = self.generator.verge
        for x in range(101, 400, 2):
            near, far = squares.get((x, 253)), squares.get((x, 257))
            self.assertIsNotNone(near, x)
            # a metre from the edge: the roadside's own layer, leaning down to the road
            flag, z, gx, gy = near
            self.assertEqual(flag, V.flag)
            self.assertGreater(gy, .08)
            self.assertLess(abs(gx), .02)
            # its corner at the road is under the surface, its far corner about on it
            self.assertLess(z - gy, 20 - .15)
            self.assertAlmostEqual(z + gy, 20, delta=.12)
            # past the band: the common lawn on the ground as it lies
            self.assertEqual(far[0], 0)
            self.assertLess(abs(far[3]), .05)
        # the other side leans the other way; nothing on the carriageway
        self.assertLess(squares[(201, 247)][3], -.08)
        self.assertFalse(any(squares.get((x, y)) for x in range(101, 400, 2) for y in (249, 251)))

    def test_the_nearest_edge_and_its_side(self):
        g = self.generator
        strip = self.lua.eval('''function()
          local points = {{0, 0, 5}, {100, 0, 5}}
          return {surface = true, points = points, hw = 3, walk = {kerb = {}, {}},
            edge = function(k, offset, top) return {points[k][1], offset, 5 + (top or 0)} end}
        end''')()
        tune = self.lua.table_from({'sidewalk': 2, 'vergeSink': 0})
        bins = g.roadEdges(self.lua.table_from([strip]), self.lua.table_from([0, -50, 100, 50]), tune)
        d, nx, ny, z = g.roadside(bins, 50, 4.5, 6.5)
        self.assertAlmostEqual(d, 1.5)
        self.assertEqual((nx, ny, z), (0, 1, 5))
        d, nx, ny, _ = g.roadside(bins, 50, -3.2, 6.5)
        self.assertAlmostEqual(d, .2)
        self.assertEqual(ny, -1)
        # on the carriageway: the paving's side of its nearest edge
        self.assertLess(g.roadside(bins, 50, 2, 6.5)[0], 0)
        self.assertIsNone(g.roadside(bins, 50, 20, 6.5))


class FarCardTests(Tile):
    WOOD = [{'areas': [{'id': 'wood', 'kind': 'forest', 'rings': [[[0, 0], [500, 0], [500, 500], [0, 500]]]}]}]

    def test_a_far_tiles_trees_are_cards_in_one_mesh(self):
        plain = self.build(self.WOOD, far=True)[2]
        crowns = sum(1 for item in plain['items'].values() if item.kind == 'static')
        far = self.build(self.WOOD, far=True, farCards=True)[2]
        self.assertFalse(any(item.kind == 'static' for item in far['items'].values()))
        cards = [item for item in far['items'].values() if item.cards]
        self.assertTrue(cards)
        triangles = sum(item.triangles for item in cards)
        # two crossed quads a tree, and twice the Forest's far crowns
        self.assertEqual(triangles % 4, 0)
        self.assertGreater(triangles // 4, crowns)
        self.assertLessEqual(triangles // 4, 1600)
        for item in cards:
            self.assertEqual([m for m in item.mats.values()], ['e2rf_far_tree'])
            self.assertEqual((item.layer, item.collision), ('far', 'None'))

    def test_a_far_tile_marks_what_stands_on_it_as_only_drawn(self):
        # A far building is the box of its bounds (this one, turned 45 degrees, is twice its
        # footprint and lies across the street beside it), a card is a sheet as wide as the tree
        # is tall: the car met both, the box unseen once the near tile's road had replaced it.
        house = {'id': 'b', 'height': 12, 'tags': {'building': 'apartments'},
                 'rings': [[[200, 150], [250, 200], [200, 250], [150, 200]]]}
        fence = {'id': 'f', 'kind': 'fence', 'tags': {'barrier': 'fence'}, 'points': [[300, 100, 0], [340, 100, 0]]}
        street = {'id': 'r', 'width': 8, 'points': line(-100, 260, 600, 260), 'tags': {'highway': 'secondary'}}
        cell = {'buildings': [house], 'lines': [fence], 'roads': [street],
                'terrain': {'rect': [-500, -500, 1000, 1000], 'nx': 2, 'ny': 2, 'heights': [20] * 4}}
        far = self.build([cell], far=True, farCards=True)[2]
        drawn, met = set(), set()
        for item in far['items'].values():
            if item.kind != 'proc':
                continue
            marks = {bool(mesh.quiet) for mesh in item.meshes.values()}
            # an object is in a collision rebuild whole or not at all
            self.assertEqual(len(marks), 1, list(item.mats.values()))
            self.assertEqual(bool(item.quiet), marks == {True})
            (drawn if marks == {True} else met).update(item.mats.values())
        self.assertTrue(any(m.startswith(('e2rf_wall_', 'e2rf_hw_', 'e2rf_kw_', 'e2rf_clad_')) for m in drawn), drawn)
        self.assertTrue(any(m.startswith('e2rf_fence') for m in drawn), drawn)
        self.assertTrue(any(m.startswith('e2rf_roof') for m in drawn), drawn)
        # the ground and the far road stay what the car stands on
        self.assertTrue(any(m.startswith('e2rf_road') for m in met), met)
        self.assertFalse(any(m.startswith(('e2rf_wall_', 'e2rf_hw_', 'e2rf_fence', 'e2rf_roof', 'e2rf_plinth')) for m in met), met)
        self.assertFalse(drawn & met)
        # a near tile keeps its shell: the proxies of its building's walls
        near = self.build([cell])[1]
        self.assertTrue(any(item.proxy for item in near['items'].values() if item.kind == 'proc'))

    def test_the_cards_stand_while_a_far_tiles_buildings_wait(self):
        far = self.build(self.WOOD, far=True, farDecor=False, farCards=True)[2]
        self.assertTrue(any(item.cards for item in far['items'].values()))
        bare = self.build(self.WOOD, far=True, farDecor=False)[2]
        self.assertFalse(any(item.cards or item.kind == 'static' for item in bare['items'].values()))

    def test_a_card_is_two_upright_quads_of_its_cell(self):
        g = self.generator
        self.assertEqual(g.cardClass('/art/shapes/earthng/flora/trees/spruce/spruce_s1_a60.dae'), 'spruce')
        self.assertEqual(g.cardClass('/levels/x/art/shapes/trees/scots_pine/pine_large.dae'), 'pine')
        self.assertEqual(g.cardClass('/levels/x/art/shapes/trees/oak/tree_oak_large_b.dae'), 'broad')
        self.assertIsNone(g.cardClass('/levels/x/art/shapes/trees/bush/generibush_a.dae'))
        tris = self.lua.eval('function(g) local got = {}; g.card({triangle = function(kind, a, b, c) got[#got + 1] = {kind, a, b, c} end}, '
                             '"spruce", 10, 20, 5, 0, 12, 3); return got end')(g)
        self.assertEqual(len(tris), 4)
        zs, us = set(), set()
        for t in tris.values():
            self.assertEqual(t[1], 'far_tree')
            for k in (2, 3, 4):
                p = t[k]
                zs.add(round(p[3], 3))
                us.add(round(p[4], 4))
                self.assertEqual((p[6], p[7], p[8]), (0, 0, 1))
        self.assertEqual(zs, {5 - g.CARD.sink, 5 - g.CARD.sink + 12})
        self.assertTrue(all(.75 <= u <= 1 for u in us))


class TurfSetTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.turf = self.lua.execute((LUA / 'turf.lua').read_text(encoding='utf8'))
        self.turf.readyState = True

    def test_every_set_grows_every_layer_at_speed(self):
        layers = set(self.turf.LAYERS.values()) - {'e2rTurfNone'}
        self.assertEqual(len(list(self.turf.SETS.keys())), 10)
        for name, defs in self.turf.SETS.items():
            rows = list(defs.values())
            self.assertEqual({d.layer for d in rows if not d.still}, layers, name)
            names = [d.name or d.src for d in rows]
            self.assertEqual(len(names), len(set(names)), name)
            for d in rows:
                self.assertIsNotNone(self.turf.SOURCES[d.source], (name, d.source))
                self.assertGreater(d.share, 0)

    def test_the_set_of_a_climate(self):
        place = self.lua.table_from
        of = self.turf.setOf
        self.assertEqual(of(None), 'temperate')
        self.assertEqual(of(place({'group': 'temperate', 'class': 26})), 'temperate')
        self.assertEqual(of(place({'group': 'temperate', 'class': 15})), 'atlantic')
        self.assertEqual(of(place({'group': 'temperate', 'class': 14})), 'subtropic')
        self.assertEqual(of(place({'group': 'mediterranean', 'west': True})), 'pacific')
        self.assertEqual(of(place({'group': 'mediterranean'})), 'mediterranean')
        for group, name in (('rainforest', 'tropics'), ('savanna', 'savanna'), ('desert', 'desert'), ('steppe', 'steppe'),
                            ('boreal', 'taiga'), ('tundra', 'taiga')):
            self.assertEqual(of(place({'group': group})), name)

    def test_a_new_place_puts_its_set_in_force_and_the_density_setter_stays(self):
        turf = self.turf
        temperate = turf.DEFS
        same = self.lua.eval('function(a, b) return a == b end')
        self.assertFalse(turf.setPlace('temperate'))
        self.assertTrue(turf.setPlace('steppe'))
        self.assertFalse(same(turf.DEFS, temperate))
        self.assertEqual(turf.stats.set, 'steppe')
        self.assertTrue(callable(turf.set))
        self.assertTrue(turf.setPlace('no such set'))
        self.assertTrue(same(turf.DEFS, temperate))
        turf.setPlace('desert')
        turf.reset()
        self.assertTrue(same(turf.DEFS, temperate))
        self.assertTrue(callable(turf.set))

    def test_the_roadside_is_a_layer_of_its_own(self):
        turf = self.turf
        self.assertEqual(turf.LAYERS[turf.layerOf(2048) + 1], 'e2rTurfVerge')
        verge = [d for d in turf.DEFS.values() if d.layer == 'e2rTurfVerge']
        self.assertTrue(any(not d.still for d in verge))
        # an older planet has no such layer: the common lawn, and none of its covers
        turf.vergeLayer = False
        self.assertEqual(turf.LAYERS[turf.layerOf(2048) + 1], 'e2rTurfGrass')
        self.assertFalse(any(turf.wanted(d) for d in verge))


if __name__ == '__main__':
    unittest.main()
