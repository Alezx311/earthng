"""Mapped Kyiv model substitutions retain the native road and occupancy planners."""
import math
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

import test_generator


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'mod/lua/ge/extensions/e2r/city3d.lua'
GENERATOR = ROOT / 'mod/lua/ge/extensions/e2r/generator.lua'


class City3DTests(unittest.TestCase):
    def setUp(self):
        self.h = test_generator.GeneratorTests()
        self.lua = self.h.lua = LuaRuntime(unpack_returned_tuples=True)
        self.city = self.lua.execute(MODULE.read_text(encoding='utf8'))
        self.lua.globals().city = self.city
        self.lua.execute("package.loaded['ge/extensions/e2r/city3d']=city")
        self.h.generator = self.lua.execute(GENERATOR.read_text(encoding='utf8'))
        self.lua.execute("FS={fileExists=function(self,p) return p:find('/art/shapes/earthng/kyiv3d/',1,true)==1 end}")

    def table(self, value):
        return self.h.table(value)

    def building(self, ident='641265722:0', x=100, y=100, width=6.5, depth=3.6, **extra):
        return {'id': ident, 'tags': {'building': 'kiosk'},
                'rings': [[[x-width/2, y-depth/2, 20], [x+width/2, y-depth/2, 20],
                           [x+width/2, y+depth/2, 20], [x-width/2, y+depth/2, 20]]], **extra}

    def build(self, buildings, **opts):
        road = {'id': 'r', 'width': 8, 'tags': {'highway': 'residential'},
                'points': [[0, 80, 20], [1000, 80, 20]]}
        cells = [{'buildings': buildings, 'roads': [road], 'terrain': {'rect': [0, 0, 1000, 500],
                  'nx': 2, 'ny': 2, 'heights': [20]*4}}]
        return self.h.build(cells, 0, 0, maxTrees=0, maxGrass=0, propSpacing=0, **opts)

    def models(self, scene):
        return [item for item in scene['items'].values() if item.city3d]

    def context(self, building, rect=None, **options):
        return self.table({'options': options, 'rect': rect or [0, 0, 500, 500],
                           'lists': {'buildings': [building]}, 'ground': self.lua.eval('function() return 20 end')})

    def test_replacement_removes_old_shell_retains_road_and_real_collision(self):
        block = self.build([self.building()], city3d=False)
        changed = self.build([self.building()])
        self.assertEqual(self.h.plain(block[0]), self.h.plain(changed[0]))
        self.assertTrue(list(self.h.triangles(block[1], 'e2rf_col_bldg')))
        self.assertFalse(list(self.h.triangles(changed[1], 'e2rf_col_bldg')))
        models = self.models(changed[1])
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].collision, 'Visible Mesh')
        self.assertIsNone(models[0].prop)
        self.assertEqual(models[0].shape, '/art/shapes/earthng/kyiv3d/bakery/bakery.dae')
        self.assertIn('/art/shapes/earthng/kyiv3d/bakery/main.materials.json', list(changed[1].stockMaterials.values()))
        self.assertIsNone(models[0].decor, 'building collision must remain in the normal scene group')
        self.assertEqual(models[0].city3dAsset, 'bakery')
        self.assertEqual(models[0].city3dRole, 'pavilion')
        self.assertEqual(changed[1].city3d.pavilions, 1)

    def test_missing_shape_or_material_keeps_original_complete_building(self):
        baseline = self.build([self.building()], city3d=False)
        for missing in ('.dae', 'main.materials.json'):
            self.lua.globals().missing = missing
            self.lua.execute('FS.fileExists=function(self,p) return p:find(missing,1,true)==nil end')
            changed = self.build([self.building()])
            self.assertFalse(self.models(changed[1]))
            self.assertEqual(self.h.plain(baseline[0]), self.h.plain(changed[0]))
            self.assertTrue(list(self.h.triangles(changed[1], 'e2rf_col_bldg')))

    def test_off_nonreal_far_and_unrelated_buildings_keep_old_results(self):
        for options in ({'realStyle': False}, {'far': True}, {'horizon': True}):
            baseline = self.build([self.building()], city3d=False, **options)
            changed = self.build([self.building()], **options)
            self.assertEqual(self.h.plain(baseline[0]), self.h.plain(changed[0]))
            self.assertEqual(self.h.plain(baseline[1]), self.h.plain(changed[1]))
        unrelated = self.build([self.building(ident='another-kiosk')])
        self.assertFalse(self.models(unrelated[1]))
        self.assertTrue(list(self.h.triangles(unrelated[1], 'e2rf_col_bldg')))

    def test_half_open_tile_ownership_has_one_complete_module(self):
        west = self.city.plan(self.context(self.building(x=500), rect=[0, 0, 500, 500]))
        east = self.city.plan(self.context(self.building(x=500), rect=[500, 0, 1000, 500]))
        self.assertTrue(west.replaced['641265722:0'])
        self.assertTrue(east.replaced['641265722:0'])
        self.assertEqual((len(west['items']), len(east['items'])), (0, 1))
        again = self.city.plan(self.context(self.building(x=500), rect=[500, 0, 1000, 500]))
        self.assertEqual(self.h.plain(again['items']), self.h.plain(east['items']))

    def test_mapped_footprint_retained_and_unknown_market_row_not_rebranded(self):
        building = self.table(self.building(ident='792923346:0', width=14.137, depth=7.657))
        ctx = self.table({'options': {}, 'rect': [0, 0, 500, 500], 'lists': {'buildings': [building]},
                          'ground': self.lua.eval('function() return 20 end')})
        original = self.h.plain(ctx.lists.buildings)
        plan = self.city.plan(ctx)
        self.assertEqual(len(plan['items']), 2)
        self.assertEqual(self.h.plain(ctx.lists.buildings), original)
        row = self.city.plan(self.context(self.building(ident='825250514:0', width=73.35, depth=5.17)))
        self.assertFalse(row.replaced['825250514:0'])
        self.assertEqual(len(row['items']), 0)

    def test_displays_clear_roads_paths_other_buildings_water_parking_and_signs(self):
        ctx = self.context(self.building(ident='617382424:0', width=44, depth=20))
        plan = self.city.plan(ctx)
        candidate = plan.candidates[1]
        x, y = candidate.x, candidate.y
        plan.candidates = self.table([candidate])
        square = [[[x-1, y-1], [x+1, y-1], [x+1, y+1], [x-1, y+1]]]

        def reserve(extra=None, segments=None, signs=None, existing=None):
            lists = {'buildings': [candidate.owner], **(extra or {})}
            scene = self.table({'items': []})
            accepted, rejected = self.city.reserve(plan, self.table(lists), self.table(segments or []),
                scene, self.table(signs or []), self.table(existing or []))
            return accepted, rejected, scene

        accepted, rejected, scene = reserve()
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(scene['items']), 1)
        self.assertEqual(scene['items'][1].collision, 'Visible Mesh')
        # All four oriented corners remain beyond their own retail footprint,
        # even though the conservative circular reservation reaches behind them.
        owner = self.h.plain(candidate.owner)['rings'][0]
        for corner in candidate.footprint.values():
            self.assertTrue(corner[1] < min(p[0] for p in owner) - .15 or
                            corner[1] > max(p[0] for p in owner) + .15 or
                            corner[2] < min(p[1] for p in owner) - .15 or
                            corner[2] > max(p[1] for p in owner) + .15)
        cases = [({'segments': [{'a': [x-10, y], 'b': [x+10, y], 'width': 6, 'surface': True}]}, 'road'),
                 ({'extra': {'lines': [{'kind': 'path', 'points': [[x-10, y], [x+10, y]]}]}}, 'path'),
                 ({'extra': {'buildings': [candidate.owner, {'rings': square}]}}, 'building'),
                 ({'extra': {'areas': [{'kind': 'water', 'rings': square}]}}, 'area'),
                 ({'extra': {'areas': [{'kind': 'parking', 'rings': square}]}}, 'area'),
                 ({'signs': [[x, y]]}, 'sign'),
                 ({'existing': [{'x': x, 'y': y, 'radius': 1}]}, 'authored object')]
        for options, reason in cases:
            with self.subTest(reason=reason):
                accepted, rejected, scene = reserve(**options)
                self.assertEqual(len(accepted), 0)
                self.assertEqual(rejected[1].reason, reason)
                self.assertEqual(len(scene['items']), 0)

    def test_halo_displays_reserve_both_tiles_and_only_owner_draws(self):
        ctx = self.context(self.building(ident='617382424:0'))
        west = self.city.plan(ctx)
        candidate = self.table({'id': 'seam', 'asset': 'flower_display', 'x': 500, 'y': 250,
                                'radius': 1, 'yaw': 0})
        west.candidates = self.table([candidate])
        east = self.city.plan(self.context(self.building(ident='617382424:0'), rect=[500, 0, 1000, 500]))
        east.candidates = self.table([candidate])
        def draw(plan):
            scene = self.table({'items': []})
            accepted, _ = self.city.reserve(plan, self.table({}), self.table([]), scene, self.table([]), self.table([]))
            return len(accepted), len(scene['items'])
        self.assertEqual(draw(west), (1, 0))
        self.assertEqual(draw(east), (1, 1))

    def test_fal_ac_substitutes_existing_grid_without_duplicate_boxes(self):
        block = self.building(ident='97578072:0', width=100, depth=12, height=48)
        block['tags'] = {'building': 'apartments', 'building:material': 'panel', 'height': '48'}
        baseline = self.build([block], city3d=False, experimentalDetail=True)
        changed = self.build([block], experimentalDetail=True)
        self.assertTrue(list(self.h.triangles(baseline[1], 'e2rf_ac_unit')))
        self.assertFalse(list(self.h.triangles(changed[1], 'e2rf_ac_unit')))
        units = [item for item in self.models(changed[1]) if '/aircon/' in item.shape]
        self.assertGreater(len(units), 0)
        self.assertTrue(all(item.collision == 'None' for item in units))
        self.assertEqual(self.h.plain(baseline[0]), self.h.plain(changed[0]))


if __name__ == '__main__':
    unittest.main()
