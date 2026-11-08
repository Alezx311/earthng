"""User-authored World Editor layer: persistence, projection and tile ownership."""
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / 'mod/lua/ge/extensions/e2r'
ID = 'a07fe504-2403-4129-81b7-53724bf21874'
OTHER_ID = 'b07fe504-2403-4129-81b7-53724bf21874'
SHAPE = '/levels/east_coast_usa/art/shapes/clutter/clutter_city_bench_wood.dae'


class EditorLayerTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.editor = self.lua.execute((LUA / 'manual_editor.lua').read_text(encoding='utf8'))
        self.lua.globals().editor = self.editor
        self.lua.execute('''
          disk=nil; writes=0; failWrite=false
          FS={fileExists=function(_, path) return disk ~= nil end}
          jsonReadFile=function(path) return disk end
          jsonWriteFile=function(path, data, pretty, precision, atomic)
            writes=writes+1; assert(atomic == true)
            if failWrite then return false end
            disk=data; return true
          end
        ''')

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def record(self, **kw):
        rec = dict(id=ID, lat=50.46, lon=30.34, z=100, shape=SHAPE,
                   rotation=[0, 0, 0, 1], scale=[1, 2, 1], radius=2.5)
        rec.update(kw)
        return rec

    def test_append_preserves_prior_records_and_rejects_bad_data(self):
        self.assertTrue(self.editor.append(self.table([self.record()]))[0])
        self.assertTrue(self.editor.append(self.table([self.record(id=OTHER_ID)]))[0])
        self.assertEqual(len(self.lua.globals().disk.objects), 2)
        writes = self.lua.globals().writes
        for bad in (self.record(), self.record(id=OTHER_ID, shape='/x/../asset.dae'),
                    self.record(id=OTHER_ID, radius=float('nan')),
                    self.record(id=OTHER_ID, rotation=[0, 0, 0, 0])):
            ok, error = self.editor.append(self.table([bad]))
            self.assertIsNone(ok)
            self.assertTrue(error)
        self.assertEqual(self.lua.globals().writes, writes)
        self.assertEqual(len(self.lua.globals().disk.objects), 2)

    def test_malformed_existing_file_and_failed_write_do_not_replace_it(self):
        original = self.table({'schema': 'wrong', 'objects': []})
        self.lua.globals().disk = original
        self.assertIsNone(self.editor.append(self.table([self.record()]))[0])
        self.assertEqual(self.lua.globals().disk.schema, 'wrong')
        self.assertEqual(self.lua.globals().writes, 0)
        self.lua.globals().disk = None
        self.lua.globals().failWrite = True
        self.assertIsNone(self.editor.append(self.table([self.record()]))[0])
        self.assertIsNone(self.lua.globals().disk)

    def test_projection_and_measured_large_bound_cross_tile_seam(self):
        self.assertTrue(self.editor.append(self.table([self.record(radius=30)]))[0])
        records, error = self.editor.load(lambda lat, lon: (510 + (lon - 30.34) * 1e5, 250 + (lat - 50.46) * 1e5))
        self.assertIsNone(error)
        self.assertEqual(len(self.editor.plan(records, self.table([0, 0, 500, 500]))), 1)
        self.assertEqual(len(self.editor.plan(records, self.table([500, 0, 1000, 500]))), 1)
        self.assertEqual(len(self.editor.plan(records, self.table([-500, 0, 0, 500]))), 0)

    def test_failed_remote_projection_does_not_hide_other_records(self):
        self.assertTrue(self.editor.append(self.table([self.record(),
                         self.record(id=OTHER_ID, lat=-33)]))[0])
        def project(lat, lon):
            if lat < 0:
                raise ValueError('projection is not available')
            return (510 + (lon - 30.34) * 1e5, 250 + (lat - 50.46) * 1e5)
        records, error = self.editor.load(project)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[1].id, ID)
        self.assertIn('1 object', error)
        self.assertEqual(len(self.lua.globals().disk.objects), 2)

    def test_generator_owns_object_in_one_tile_and_preserves_transform(self):
        self.lua.globals().doc = self.table({'schema': 'earthng-editor-objects-v1',
                                             'objects': [self.record(radius=30)]})
        self.lua.execute('''
          records=assert(editor.validate(doc)); records[1].x=500; records[1].y=250
          for _, p in ipairs(records) do p.editorObject=true end
          options={tileSize=500, terrainStep=100, maxTrees=0, maxGrass=0, propSpacing=0,
            editorPlan=function(rect) return editor.plan(records, rect) end,
            sceneReady=function(scene) early=scene end}
        ''')
        gen = self.lua.execute((LUA / 'generator.lua').read_text(encoding='utf8'))
        cells = self.table([{'terrain': {'rect': [0, 0, 1000, 500], 'nx': 2, 'ny': 2,
                                          'heights': [20] * 4}}])
        def build(i):
            self.lua.globals().early = None
            gen.build(cells, i, 0, self.lua.globals().options)
            return [item for item in self.lua.globals().early['items'].values() if item.editorObject]
        self.assertEqual(len(build(0)), 0)
        item = build(1)[0]
        self.assertEqual([item.pos[i] for i in range(1, 4)], [500, 250, 100])
        self.assertEqual([item.scale[i] for i in range(1, 4)], [1, 2, 1])
        self.assertEqual([item.rot[i] for i in range(1, 5)], [0, 0, 0, 1])
        self.assertEqual(item.collision, 'Collision Mesh')
        self.assertEqual(item.name, 'earthng_obj_' + ID.replace('-', '_'))
        self.assertEqual(item.editorId, ID)
        self.assertFalse(item.decor, 'the scene group collides and is pickable in the editor')

    def test_apply_updates_and_removes_by_id_and_refuses_lost_updates(self):
        self.assertTrue(self.editor.append(self.table([self.record(), self.record(id=OTHER_ID)]))[0])
        ok, err = self.editor.apply(self.table({'update': [self.record(z=105)], 'remove': [OTHER_ID]}))
        self.assertTrue(ok, err)
        rows = list(self.lua.globals().disk.objects.values())
        self.assertEqual([(r.id, r.z) for r in rows], [(ID, 105)])
        writes = self.lua.globals().writes
        ok, err = self.editor.apply(self.table({'update': [self.record(id=OTHER_ID)]}))
        self.assertIsNone(ok)
        self.assertIn('no longer', err)
        self.assertIsNone(self.editor.apply(self.table({}))[0])
        self.assertEqual(self.lua.globals().writes, writes)

    def test_object_names_round_trip_and_copies_are_not_owned(self):
        name = self.editor.objectName(ID)
        self.assertEqual(self.editor.idOfName(name), ID)
        for other in (name + '1', name + '_1', 'e2rl_0_0_bench', '', None):
            self.assertIsNone(self.editor.idOfName(other))

    def test_rotation_is_north_up_on_disk_and_turned_into_the_landing_frame(self):
        import math
        a = math.radians(30)
        self.assertTrue(self.editor.append(self.table([self.record(
            rotation=[0, 0, math.sin(a / 2), math.cos(a / 2)])]))[0])
        t = math.radians(-7)
        def project(lat, lon):
            e, n = (lon - 30) * 1000, (lat - 50) * 1000
            return math.cos(t) * e - math.sin(t) * n, math.sin(t) * e + math.cos(t) * n
        records, error = self.editor.load(project)
        self.assertIsNone(error)
        q = records[1].rotation
        self.assertAlmostEqual(math.degrees(2 * math.atan2(q[3], q[4])), 23, places=4)

    def test_points_outside_the_frame_are_skipped_without_error(self):
        self.assertTrue(self.editor.append(self.table([self.record(), self.record(id=OTHER_ID, lat=-33)]))[0])
        records, error = self.editor.load(lambda lat, lon: (None, None) if lat < 0 else (lat * 10, lon * 10))
        self.assertIsNone(error)
        self.assertEqual(len(records), 1)

    def test_reconcile_keeps_unchanged_tables_and_numbers_new_versions(self):
        self.assertTrue(self.editor.append(self.table([self.record(), self.record(id=OTHER_ID)]))[0])
        project = lambda lat, lon: (lon * 10, lat * 10)
        first, rev = self.editor.reconcile(None, self.editor.load(project)[0], 0)
        self.assertEqual(rev, 2)
        self.assertTrue(self.editor.apply(self.table({'update': [self.record(id=OTHER_ID, z=120)]}))[0])
        second, rev = self.editor.reconcile(first, self.editor.load(project)[0], rev)
        self.assertEqual(rev, 3)
        self.assertTrue(self.lua.eval('function(a, b) return rawequal(a, b) end')(first[1], second[1]))
        self.assertEqual(second[2].rev, 3)


if __name__ == '__main__':
    unittest.main()
