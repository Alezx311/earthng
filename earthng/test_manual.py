"""Manual point override validation and native generator integration (LuaJIT)."""
import math
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'mod/lua/ge/extensions/e2r/manual.lua'
GENERATOR = ROOT / 'mod/lua/ge/extensions/e2r/generator.lua'
BENCH = '/levels/east_coast_usa/art/shapes/clutter/clutter_city_bench_wood.dae'
ID = 'a07fe504-2403-4129-81b7-53724bf21874'


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.manual = self.lua.execute(MODULE.read_text(encoding='utf8'))
        self.lua.globals().manual = self.manual

    def table(self, v):
        if isinstance(v, dict):
            return self.lua.table_from({k: self.table(x) for k, x in v.items()})
        if isinstance(v, list):
            return self.lua.table_from([self.table(x) for x in v])
        return v

    def object(self, **extra):
        return dict(id=ID, lat=50.46, lon=30.34, shape=BENCH,
                    altitude=dict(mode='terrain', meters=.5), yaw_degrees=90, scale=1, **extra)

    def document(self, objects):
        return self.table(dict(schema='earthng-object-overrides-v1', objects=objects))

    def test_validate_is_strict_and_all_or_nothing(self):
        valid, err = self.manual.validate(self.document([self.object()]))
        self.assertIsNone(err)
        self.assertEqual(len(valid), 1)
        bad = self.object()
        bad['scale'] = float('inf')
        for objects in [[self.object(), bad], [self.object(), self.object()], [self.object(extra='lost')]]:
            records, error = self.manual.validate(self.document(objects))
            self.assertIsNone(records)
            self.assertTrue(error)
        records, error = self.manual.validate(self.table({'schema': 'unknown', 'objects': []}))
        self.assertIsNone(records)
        self.assertTrue(error)

    def test_missing_invalid_and_projection_failures_are_safe(self):
        self.lua.execute('FS={fileExists=function() return false end}; jsonReadFile=function() error("unexpected") end')
        records, err = self.manual.load(lambda lat, lon: (1, 2))
        self.assertEqual(len(records), 0)
        self.assertIsNone(err)
        self.lua.execute('FS={fileExists=function() return true end}; jsonReadFile=function() error("bad JSON") end')
        records, err = self.manual.load(lambda lat, lon: (1, 2))
        self.assertEqual(len(records), 0)
        self.assertIn('cannot read', err)
        self.lua.globals().document = self.document([self.object()])
        self.lua.execute('jsonReadFile=function() return document end')
        records, err = self.manual.load(lambda lat, lon: (float('nan'), 2))
        self.assertEqual(len(records), 0)
        self.assertEqual(err, 'coordinate projection failed')

    def test_clearance_rejects_roads_buildings_water_and_existing_static(self):
        self.lua.globals().doc = self.document([self.object()])
        self.lua.execute('records=assert(manual.validate(doc)); records[1].x=250; records[1].y=250')
        rect = self.table([0, 0, 500, 500])
        records = self.lua.globals().records
        empty = self.table({})
        def plan(lists=None, segments=None, scene=None):
            return self.manual.plan(records, rect, self.table(lists or {}),
                                    self.table(segments or []), self.table(scene or {}), empty)[0]
        self.assertEqual(len(plan()), 1)
        road = {'a': [0, 250], 'b': [500, 250], 'width': 6, 'surface': True}
        self.assertEqual(len(plan(segments=[road])), 0)
        square = [[[245, 245], [255, 245], [255, 255], [245, 255]]]
        self.assertEqual(len(plan(lists={'buildings': [{'rings': square}]})), 0)
        self.assertEqual(len(plan(lists={'areas': [{'kind': 'water', 'rings': square}]})), 0)
        self.assertEqual(len(plan(scene={'items': [{'kind': 'static', 'pos': [251, 250, 0]}]})), 0)

    def test_boundary_scene_ready_and_reload_are_deterministic(self):
        generator = self.lua.execute(GENERATOR.read_text(encoding='utf8'))
        self.lua.globals().doc = self.document([self.object()])
        self.lua.execute('''
          records=assert(manual.validate(doc)); records[1].x=500; records[1].y=250
          options={tileSize=500, terrainStep=100, maxTrees=0, maxGrass=0, propSpacing=0, relief=false,
            manualPlan=function(rect, lists, segments, scene, signs)
              return manual.plan(records, rect, lists, segments, scene, signs)
            end,
            sceneReady=function(scene) early=scene end}
        ''')
        cell = self.table([{'terrain': {'rect': [0, 0, 1000, 500], 'nx': 2, 'ny': 2, 'heights': [20] * 4}}])
        options = self.lua.globals().options
        def build(i):
            self.lua.globals().early = None
            result = generator.build(cell, i, 0, options)
            early = self.lua.globals().early
            self.assertIsNotNone(early)
            return [item for item in early['items'].values()
                    if item.kind == 'static' and item.shape == BENCH]
        self.assertEqual(build(0), [])
        east = build(1)
        again = build(1)
        self.assertEqual(len(east), 1)
        self.assertEqual(len(again), 1)
        self.assertEqual((east[0].pos[1], east[0].pos[2]), (500, 250))
        self.assertAlmostEqual(east[0].rot[3], math.sin(math.pi / 4))
        self.assertAlmostEqual(east[0].pos[3], 20.25)
        self.assertEqual(east[0].name, again[0].name)

    def test_accepted_bench_reserves_space_against_vegetation(self):
        generator = self.lua.execute(GENERATOR.read_text(encoding='utf8'))
        cell = self.table([{
            'terrain': {'rect': [0, 0, 500, 500], 'nx': 2, 'ny': 2, 'heights': [20] * 4},
            'areas': [{'id': 'forest', 'kind': 'forest',
                       'rings': [[[0, 0], [500, 0], [500, 500], [0, 500]]]}],
        }])
        opts = self.table({'tileSize': 500, 'terrainStep': 100, 'maxTrees': 300, 'maxGrass': 0,
                           'propSpacing': 0, 'look': {'statics': 'none'}})
        baseline = generator.build(cell, 0, 0, opts)[1]
        trees = [i for i in baseline['items'].values() if i.kind == 'static' and i.pos
                 and 30 < i.pos[1] < 470 and 30 < i.pos[2] < 470]
        self.assertTrue(trees, 'fixture should scatter at least one tree')
        x, y = trees[0].pos[1], trees[0].pos[2]
        self.lua.globals().doc = self.document([self.object()])
        self.lua.globals().x, self.lua.globals().y = x, y
        self.lua.execute('''
          records=assert(manual.validate(doc)); records[1].x=x; records[1].y=y
          plan=function(rect, lists, segments, scene, signs)
            return manual.plan(records, rect, lists, segments, scene, signs)
          end
        ''')
        opts.manualPlan = self.lua.globals().plan
        changed = generator.build(cell, 0, 0, opts)[1]
        statics = [i for i in changed['items'].values() if i.kind == 'static' and i.pos]
        benches = [i for i in statics if i.shape == BENCH]
        self.assertEqual(len(benches), 1)
        self.assertFalse(any(i.shape != BENCH and math.hypot(i.pos[1]-x, i.pos[2]-y) < 1.463
                             for i in statics))


if __name__ == '__main__':
    unittest.main()
