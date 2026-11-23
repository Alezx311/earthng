"""The flora in a tile: a wood's trees come from its stands, with undergrowth, deadwood, a floor and a fill."""
from collections import Counter
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

import test_generator as harness

ROOT = Path(__file__).resolve().parents[1]
# a region frame whose origin is a place: metres east and north of it (biome.lua's affine)
POLISSIA = [0, 0, 30.73, 50.87, 1 / 70250, 0, 0, 1 / 111320]       # the Desna-Dnipro pinewoods
STEPPE_EDGE = [0, 0, 30.508, 49.6, 1 / 72100, 0, 0, 1 / 111320]    # forest-steppe south of Kyiv
PARIS = [0, 0, 2.35, 48.85, 1 / 73200, 0, 0, 1 / 111320]


def patch(kind, rect=(0, 0, 500, 500), tags=None):
    x0, y0, x1, y1 = rect
    return {'id': kind, 'kind': kind, 'tags': tags or {}, 'rings': [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]]}


def terrain(z=120):
    return {'rect': [-100, -100, 1100, 1100], 'nx': 2, 'ny': 2, 'heights': [z] * 4}


class FloraTileTest(unittest.TestCase):
    def setUp(self):
        self.g = harness.GeneratorTests()
        self.g.lua = LuaRuntime(unpack_returned_tuples=True)
        # the generator finds flora.lua (and biome.lua) as the game does
        self.g.lua.execute(f"package.path = '{(ROOT / 'mod/lua').as_posix()}/?.lua;' .. package.path")
        self.g.generator = self.g.lua.execute(harness.SOURCE.read_text(encoding='utf8'))

    def statics(self, cell, layer=1, **options):
        options.setdefault('geo', POLISSIA)
        manifest = self.g.build([cell], **options)[layer]
        return [i for i in manifest['items'].values() if i.kind == 'static']

    @staticmethod
    def layer(items, prefix):
        return [i for i in items if i.name.split('_', 3)[3].startswith(prefix) or f'_{prefix}_' in i.name]

    def trees(self, items):
        return [i for i in items if '_tree_' in i.name]

    def heights(self, items):
        """Metres of each item: its stock model's own height (flora.lua STOCK) by its scale."""
        flora = self.g.lua.eval("require('ge/extensions/e2r/flora')")
        own = {}
        for models in flora.STOCK.values():
            for model in models.values():
                own[model.shape] = model.height
        return [own[i.shape] * i.scale for i in items]

    def test_a_polissia_pinewood_is_pine_with_birch_and_oak_in_it(self):
        cell = {'terrain': terrain(), 'areas': [patch('forest', tags={'leaf_type': 'needleleaved'})]}
        trees = [i for i in self.trees(self.statics(cell)) if not i.fill]
        self.assertGreater(len(trees), 700)   # the default cap is 800 (a third of 2400, VEG.thin)
        shapes = Counter('pine' if 'scots_pine' in i.shape else 'other' for i in trees)
        self.assertGreater(shapes['pine'] / len(trees), .6)
        self.assertGreater(shapes['other'] / len(trees), .08, 'a pinewood has birch, oak and aspen in it')
        self.assertTrue(all(.6 <= i.scale <= 1.1 for i in trees))

    def test_an_untagged_wood_of_the_forest_steppe_is_mostly_broadleaves(self):
        cell = {'terrain': terrain(160), 'areas': [patch('forest')]}
        trees = self.trees(self.statics(cell, geo=STEPPE_EDGE))
        pine = sum('scots_pine' in i.shape for i in trees)
        self.assertLess(pine / len(trees), .35)
        self.assertGreater(len({i.shape for i in trees}), 8)

    def test_stands_make_patches_not_salt_and_pepper(self):
        # in an untagged Polissia wood, a tree's nearest neighbours are mostly of its own kind
        cell = {'terrain': terrain(), 'areas': [patch('forest')]}
        trees = [(i.pos[1], i.pos[2], 'scots_pine' in i.shape) for i in self.trees(self.statics(cell)) if not i.fill]
        conifer = sum(t[2] for t in trees) / len(trees)
        self.assertTrue(.3 < conifer < .9, conifer)
        cells = {}
        for x, y, pine in trees:
            cells.setdefault((int(x // 50), int(y // 50)), []).append(pine)
        shares = [sum(v) / len(v) for v in cells.values() if len(v) >= 8]
        # most 50 m squares are clearly one or the other
        clear = sum(1 for s in shares if s < .3 or s > .7) / len(shares)
        self.assertGreater(clear, .6, shares)

    def test_far_trees_are_a_subset_of_the_near_ones(self):
        cell = {'terrain': terrain(), 'areas': [patch('forest')]}
        key = lambda i: (i.shape, round(i.pos[1], 3), round(i.pos[2], 3), round(i.scale, 4))
        near = {key(i) for i in self.statics(cell)}
        far = [key(i) for i in self.statics(cell, layer=2, far=True)]
        self.assertGreater(len(far), 100)
        self.assertTrue(set(far) <= near)

    def test_the_fill_is_the_rest_of_the_lattice_marked_for_a_standing_car(self):
        cell = {'terrain': terrain(), 'areas': [patch('forest')]}
        items = self.trees(self.statics(cell, maxTrees=600))
        base = [i for i in items if not i.fill]
        fill = [i for i in items if i.fill]
        self.assertEqual(len(base), 600)
        self.assertEqual(len(fill), 1200)
        self.assertEqual(len({(i.pos[1], i.pos[2]) for i in items}), len(items), 'no point is planted twice')
        self.assertFalse(any(i.fill for i in self.statics(cell, layer=2, far=True, maxTrees=600)))
        self.assertFalse(any(i.fill for i in self.statics(cell, maxTrees=600, fill=False)))

    def test_under_the_canopy_stand_shrubs_young_trees_and_deadwood(self):
        cell = {'terrain': terrain(), 'areas': [patch('forest', tags={'leaf_type': 'needleleaved'})]}
        items = self.statics(cell)
        under = [i for i in items if '_bush_' in i.name]
        dead = [i for i in items if '_dead_' in i.name]
        # a third of the understory's lattice and of its cap of 900 (VEG.thin)
        self.assertGreater(len(under), 200)
        self.assertLessEqual(len(under), 300)
        self.assertTrue(any('Juniper' in i.shape for i in under), 'juniper stands under Polissia pines')
        self.assertTrue(any('bush' in i.shape for i in under))
        self.assertGreater(len(dead), 20)
        self.assertTrue(all(i.pos[3] > 100 for i in under + dead))

    def test_a_woods_floor_is_flagged_by_its_stand(self):
        def flags(tags):
            cell = {'terrain': terrain(), 'areas': [patch('forest', tags=tags)]}
            seen = Counter()
            for item in self.statics(cell):
                if item.grassPatch:
                    samples = list(item.grassPatch.samples.values())
                    for value in samples[::4]:
                        seen[int(value) - int(value) % 16] += 1
            return seen
        conifer = flags({'leaf_type': 'needleleaved'})
        broad = flags({'leaf_type': 'broadleaved'})
        self.assertEqual(set(conifer), {1024})
        self.assertEqual(set(broad), {512})
        self.assertGreater(conifer[1024], 40000)
        cell = {'terrain': terrain(), 'areas': [patch('forest')]}
        self.assertFalse(any(i.grassPatch for i in self.statics(cell, woodFloor=False)))

    def test_by_the_water_the_pines_give_way_to_alder_and_willow(self):
        cell = {'terrain': terrain(), 'areas': [patch('forest', (0, 0, 500, 500), {'leaf_type': 'needleleaved'}),
                                                patch('water', (240, 0, 260, 500))]}
        trees = [i for i in self.trees(self.statics(cell)) if not i.fill]
        bank = [i for i in trees if 215 < i.pos[1] < 285]
        away = [i for i in trees if i.pos[1] < 150 or i.pos[1] > 350]
        self.assertGreater(len(bank), 20)
        self.assertEqual(sum('scots_pine' in i.shape for i in bank), 0)
        self.assertGreater(sum('scots_pine' in i.shape for i in away) / len(away), .6)

    def test_a_bog_has_stunted_pine_and_a_marsh_almost_nothing(self):
        bog = {'terrain': terrain(), 'areas': [patch('wetland', tags={'wetland': 'bog'})]}
        marsh = {'terrain': terrain(), 'areas': [patch('wetland', tags={'wetland': 'marsh'})]}
        bog_trees = self.trees(self.statics(bog))
        marsh_trees = self.trees(self.statics(marsh))
        self.assertGreater(len(bog_trees), 100)   # a third of the lattice (VEG.thin): 410 before 23.11
        self.assertGreater(sum('scots_pine' in i.shape for i in bog_trees) / len(bog_trees), .6)
        wood = {'terrain': terrain(), 'areas': [patch('forest', tags={'leaf_type': 'needleleaved'})]}
        grown = self.heights([i for i in self.trees(self.statics(wood)) if 'scots_pine' in i.shape])
        stunted = self.heights([i for i in bog_trees if 'scots_pine' in i.shape])
        self.assertLess(sum(stunted) / len(stunted), .65 * sum(grown) / len(grown))
        self.assertLess(len(marsh_trees), len(bog_trees) / 2)

    def test_a_row_of_trees_is_one_species_along_the_street(self):
        row = {'id': 'row', 'kind': 'tree_row', 'tags': {}, 'points': [[20, 250], [480, 250]]}
        cell = {'terrain': terrain(160), 'areas': [patch('meadow')], 'lines': [row]}
        trees = [i for i in self.statics(cell, geo=STEPPE_EDGE) if '_tree_row_' in i.name]
        self.assertGreater(len(trees), 40)
        # one species' models (its stock stand-ins may lie in two of the game's folders)
        flora = self.g.lua.eval("require('ge/extensions/e2r/flora')")
        best = max(sum(i.shape in {m.shape for m in models.values()} for i in trees)
                   for models in flora.STOCK.values())
        self.assertGreater(best / len(trees), .8)

    def test_outside_the_region_and_switched_off_the_old_sets_stand(self):
        cell = {'terrain': terrain(), 'areas': [patch('forest', tags={'leaf_type': 'needleleaved'})]}
        for options in ({'geo': PARIS}, {'flora': False}):
            with self.subTest(options=options):
                items = self.statics(cell, **options)
                trees = self.trees(items)
                self.assertTrue(all('scots_pine' in i.shape for i in trees), Counter(i.shape for i in trees))
                self.assertFalse(any(i.fill for i in items))
                self.assertLessEqual(sum('_bush_' in i.name for i in items), 220)
                self.assertFalse(any('_dead_' in i.name for i in items))


if __name__ == '__main__':
    unittest.main()
