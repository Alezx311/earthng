"""World Editor adapter contract (editor/earthngSave.lua) against a mock scene.

The mock covers the engine calls the adapter makes; the real World Editor, gizmo,
undo and file system still need the in-game probe (earthng/probe/editor_save.lua).
"""
import math
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'mod/lua/ge/extensions/editor/earthngSave.lua'
DATA = ROOT / 'mod/lua/ge/extensions/e2r/manual_editor.lua'
BENCH = '/levels/east_coast_usa/art/shapes/clutter/clutter_city_bench_wood.dae'

SCENE = r'''
  disk, writes, failWrite, notifications, uuids = nil, 0, false, {}, 0
  FS = {fileExists=function() return disk ~= nil end}
  function jsonReadFile() return disk end
  function jsonWriteFile(path, doc, pretty, precision, atomic)
    assert(atomic == true, 'editor objects must be written atomically')
    writes = writes + 1
    if failWrite then return false end
    disk = doc; return true
  end
  function quat(q) return q end
  function vec(x, y, z) return {x=x, y=y, z=z} end
  Engine = {generateUUID=function()
    uuids = uuids + 1
    return string.format('{a07fe504-2403-4129-81b7-%012x}', uuids)
  end}
  level = 'e2r_world'
  function getCurrentLevelIdentifier() return level end
  -- scene
  local nextId, all = 1, {}
  scenetree = {}
  function scenetree.findObjectById(id) return all[id] end
  function scenetree.findObject(name)
    for _, o in pairs(all) do if o.name == name and name ~= '' then return o end end
  end
  local function base(cls, name, parent)
    local o = {id=nextId, cls=cls, name=name or '', children={}, canSave=true}
    nextId = nextId + 1
    function o:getID() return self.id end
    function o:getName() return self.name end
    function o:setName(n) self.name = n end
    function o:getClassName() return self.cls end
    function o:getGroup() return self.parent end
    function o:getCount() return #self.children end
    function o:getObject(i) return self.children[i + 1] end
    function o:addObject(child)
      if child.parent then
        for i, c in ipairs(child.parent.children) do
          if c == child then table.remove(child.parent.children, i); break end
        end
      end
      child.parent = self; self.children[#self.children + 1] = child
    end
    function o:registerObject(n) self.name = n or ''; all[self.id] = self end
    all[o.id] = o
    if parent then parent:addObject(o) end
    return o
  end
  function group(name, parent) return base('SimGroup', name, parent) end
  function createObject(cls) local o = base(cls); all[o.id] = nil; return o end
  function remove(o)
    all[o.id] = nil
    for i, c in ipairs(o.parent.children) do if c == o then table.remove(o.parent.children, i); break end end
  end
  function mesh(parent, x, y, opts)
    opts = opts or {}
    local o = base(opts.cls or 'TSStatic', opts.name, parent)
    o.pos, o.rot, o.scale, o.shape = vec(x, y, opts.z or 30), opts.rot or {x=0, y=0, z=0, w=1}, vec(1, 1, 1), opts.shape or BENCH
    function o:getPosition() return self.pos end
    function o:getRotation() return self.rot end
    function o:getScale() return self.scale end
    function o:getWorldBox()
      return {minExtents=vec(self.pos.x - 1, self.pos.y - .5, 0), maxExtents=vec(self.pos.x + 1, self.pos.y + .5, 1)}
    end
    function o:getField(f) return f == 'shapeName' and self.shape or '' end
    return o
  end
  BENCH = ...
  scenetree.MissionGroup = group('MissionGroup')
  levelObject = mesh(scenetree.MissionGroup, 0, 0, {name='levelBench'})
  tile = group('E2RS_0_0', scenetree.MissionGroup)
  generated = mesh(tile, 5, 5, {name='e2rl_0_0_bench_7'})
  editor = {selection={object={}}, dirty=true,
    showNotification=function(s) notifications[#notifications + 1] = s end,
    addWindowMenuItem=function() end, resetDirty=function() editor.dirty = false end}
  savedLevel, autosaved = 0, 0
  editor.saveLevel = function() savedLevel = savedLevel + 1 end
  editor.doSaveLevel = function() editor.saveLevel() end
  editor.autoSaveLevel = function() editor.autosavingNow = true; editor.saveLevel(); editor.autosavingNow = false; autosaved = autosaved + 1 end
'''

NATIVE = r'''
  data = ...
  -- a frame turned 10 degrees against north, so the north-up rotation is tested
  local turn = math.rad(10)
  local c, s = math.cos(turn), math.sin(turn)
  local function project(lat, lon)
    local e, n = (lon - 30) * 1000, (lat - 50) * 1000
    return c * e - s * n, s * e + c * n
  end
  local records, rev = {}, 0
  reloads = 0
  package.loaded['ge/extensions/e2r/native'] = {
    toGeo=function(x, y)
      local e, n = c * x + s * y, -s * x + c * y
      return 50 + n / 1000, 30 + e / 1000
    end,
    localPoint=project,
    editorObjects=function() return records end,
    reloadEditorObjects=function()
      reloads = reloads + 1
      local loaded, err = data.load(project)
      records, rev = data.reconcile(records, loaded, rev)
      return #records, err
    end,
  }
  package.loaded['ge/extensions/e2r/manual_editor'] = data
'''


class EditorAdapterTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(SCENE, BENCH)
        self.data = self.lua.execute(DATA.read_text(encoding='utf8'))
        self.lua.execute(NATIVE, self.data)
        self.mod = self.lua.execute(MODULE.read_text(encoding='utf8'))
        self.g = self.lua.globals()
        self.mod.onEditorInitialized()
        self.mod.onEditorActivated()

    def ctrl_s(self):
        self.g.editor.doSaveLevel()

    def objects(self):
        return list(self.g.disk.objects.values()) if self.g.disk else []

    def test_ctrl_s_saves_placed_object_without_selection_and_adopts_it(self):
        obj = self.lua.eval('mesh(scenetree.MissionGroup, 100, 200)')
        self.ctrl_s()
        rows = self.objects()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(self.g.savedLevel, 0, 'the level itself must not be serialized')
        self.assertEqual(row.id, 'a07fe504-2403-4129-81b7-000000000001')
        self.assertEqual(obj.name, 'earthng_obj_a07fe504_2403_4129_81b7_000000000001')
        self.assertEqual(obj.parent.name, 'E2R_editor')
        self.assertFalse(obj.canSave)
        self.assertEqual(self.g.reloads, 1)
        self.assertFalse(self.g.editor.dirty)
        self.assertAlmostEqual(row.radius, math.hypot(1, .5))
        # the saved record comes back exactly where the object stands
        p = self.g.package.loaded['ge/extensions/e2r/native'].editorObjects()[1]
        self.assertAlmostEqual(p.x, 100, places=6)
        self.assertAlmostEqual(p.y, 200, places=6)
        # a second Ctrl+S has nothing to write
        writes = self.g.writes
        self.ctrl_s()
        self.assertEqual(self.g.writes, writes)
        self.assertIn('Nothing to save', self.g.notifications[len(self.g.notifications)])

    def test_rotation_is_stored_north_up_and_restored_in_the_landing_frame(self):
        self.lua.execute('''
          local a = math.rad(30)
          obj = mesh(scenetree.MissionGroup, 10, 20, {rot={x=0, y=0, z=math.sin(a/2), w=math.cos(a/2)}})
        ''')
        self.ctrl_s()
        row = self.objects()[0]
        yaw = 2 * math.atan2(row.rotation[3], row.rotation[4])
        self.assertAlmostEqual(math.degrees(yaw), 20, places=4)  # 30 in a frame turned 10 from north
        p = self.g.package.loaded['ge/extensions/e2r/native'].editorObjects()[1]
        self.assertAlmostEqual(math.degrees(2 * math.atan2(p.rotation[3], p.rotation[4])), 30, places=4)

    def test_generated_level_and_non_mesh_objects_are_not_saved(self):
        self.lua.execute('''
          editor.selection.object = {generated.id, levelObject.id}
          light = mesh(scenetree.MissionGroup, 1, 1, {cls='PointLight'})
        ''')
        self.mod.onEditorObjectAdded(self.g.light.id)
        self.ctrl_s()
        self.assertEqual(self.objects(), [])
        self.assertIn('Only meshes', self.g.notifications[len(self.g.notifications)])

    def test_moved_saved_object_updates_its_record(self):
        obj = self.lua.eval('mesh(scenetree.MissionGroup, 100, 200)')
        self.ctrl_s()
        first = self.objects()[0]
        self.lua.execute('function move(o) o.pos = vec(103, 204, 31); o.scale = vec(2, 2, 2) end')
        self.g.move(obj)
        self.assertEqual(self.mod.pending(), 1)
        self.ctrl_s()
        rows = self.objects()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].id, first.id)
        self.assertEqual(rows[0].z, 31)
        self.assertEqual([rows[0].scale[i] for i in (1, 2, 3)], [2, 2, 2])
        self.assertNotAlmostEqual(rows[0].lat, first.lat)

    def test_restored_object_in_a_tile_can_be_moved_and_deleted(self):
        self.lua.execute('a = mesh(scenetree.MissionGroup, 100, 200); b = mesh(scenetree.MissionGroup, 50, 60)')
        self.ctrl_s()
        # a restart: the tile draws both records, the editor's copies are gone
        self.lua.execute('''
          for _, o in ipairs({a, b}) do
            local name = o.name; remove(o)
            local copy = mesh(tile, o.pos.x, o.pos.y, {name=name}); copy.canSave = false
            restored = restored or {}; restored[#restored + 1] = copy
          end
        ''')
        self.mod.onEditorActivated()
        self.assertEqual(self.mod.pending(), 0)
        # delete the first the stock way: selected, gone, selection emptied with no hook
        self.lua.execute('editor.selection.object = {restored[1].id}')
        self.mod.onEditorObjectSelectionChanged()
        self.lua.execute('remove(restored[1]); editor.selection = {}')
        self.assertEqual(self.mod.pending(), 1)
        self.ctrl_s()
        rows = self.objects()
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.g.package.loaded['ge/extensions/e2r/native'].editorObjects()[1].id, rows[0].id)

    def test_undone_delete_and_a_leaving_tile_remove_nothing(self):
        self.lua.execute('a = mesh(scenetree.MissionGroup, 100, 200)')
        self.ctrl_s()
        self.lua.execute('''
          name = a.name; remove(a)
          copy = mesh(tile, 100, 200, {name=name})
          editor.selection.object = {copy.id}
        ''')
        self.mod.onEditorObjectSelectionChanged()
        # undo: the object is back under its name before the save
        self.lua.execute('remove(copy); editor.selection.object = {}')
        self.mod.onEditorObjectSelectionChanged()
        self.lua.execute('back = mesh(tile, 100, 200, {name=name})')
        self.ctrl_s()
        self.assertEqual(len(self.objects()), 1)
        # the tile leaves (buried: its group loses the name) while the object is selected
        self.lua.execute('editor.selection.object = {back.id}')
        self.mod.onEditorObjectSelectionChanged()
        self.lua.execute('tile.name = ""; remove(back); editor.selection.object = {}')
        self.mod.onEditorObjectSelectionChanged()
        writes = self.g.writes
        self.ctrl_s()
        self.assertEqual(self.g.writes, writes)
        self.assertEqual(len(self.objects()), 1)

    def test_undo_after_a_saved_delete_saves_the_object_again_under_its_id(self):
        self.lua.execute('a = mesh(scenetree.MissionGroup, 100, 200)')
        self.ctrl_s()
        rid = self.objects()[0].id
        self.lua.execute('editor.selection.object = {a.id}')
        self.mod.onEditorObjectSelectionChanged()
        self.lua.execute('group0 = a.parent; name = a.name; remove(a); editor.selection.object = {}')
        self.mod.onEditorObjectSelectionChanged()
        self.ctrl_s()
        self.assertEqual(self.objects(), [])
        back = self.lua.eval('mesh(group0, 100, 200, {name=name})')
        self.mod.onEditorObjectAdded(back.id)  # the editor's undo fires this
        self.assertEqual(self.mod.pending(), 1)
        self.ctrl_s()
        self.assertEqual([r.id for r in self.objects()], [rid])

    def test_duplicate_of_a_restored_object_inside_a_tile_is_new(self):
        self.lua.execute('a = mesh(scenetree.MissionGroup, 100, 200)')
        self.ctrl_s()
        self.lua.execute('''
          dup = mesh(tile, 104, 200, {name=a.name .. '1'})
          editor.selection.object = {dup.id}
        ''')
        self.mod.onEditorObjectSelectionChanged()
        self.ctrl_s()
        rows = self.objects()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0].id, rows[1].id)
        self.assertEqual(self.g.dup.parent.name, 'E2R_editor')

    def test_failed_write_leaves_objects_new_and_untouched(self):
        obj = self.lua.eval('mesh(scenetree.MissionGroup, 100, 200)')
        self.g.failWrite = True
        self.ctrl_s()
        self.assertIsNone(self.g.disk)
        self.assertEqual(obj.name, '')
        self.assertTrue(obj.canSave)
        self.assertEqual(self.g.reloads, 0)
        self.assertIn('Save failed', self.g.notifications[len(self.g.notifications)])
        self.assertEqual(self.mod.pending(), 1)

    def test_other_levels_keep_the_editor_save_and_autosave_is_skipped_here(self):
        self.g.editor.autoSaveLevel()
        self.assertEqual(self.g.savedLevel, 0)
        self.g.level = 'west_coast_usa'
        self.ctrl_s()
        self.g.editor.autoSaveLevel()
        self.assertEqual(self.g.savedLevel, 2)
        self.assertIsNone(self.g.disk)


if __name__ == '__main__':
    unittest.main()
