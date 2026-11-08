-- Run with probe.py after test_world.py --manual --probe has landed (fresh profile).
-- Goes through the user's path in the World Editor without input devices:
-- place (no selection) -> Ctrl+S's function -> move -> save -> place a second ->
-- delete it the editor's way -> save -> undo the delete -> save.
-- It never writes the live player profile; the result seeds editor_verify.lua.
local shape = '/levels/east_coast_usa/art/shapes/clutter/clutter_city_bench_wood.dae'
local path = 'settings/earthng-editor-objects.json'
assert(FS:fileExists(shape), 'test mesh missing from VFS')
assert(not FS:fileExists(path), 'test profile must start without editor objects')
assert(editor_main and editor_main.setEditorActive, 'World Editor is unavailable')
editor_main.setEditorActive(true, false)
local data = require('ge/extensions/e2r/manual_editor')
local stage, start, log = 'place', P.now(), {}
local first, second, firstId

local function place(dx)
  local veh = assert(be:getPlayerVehicle(0), 'no player vehicle')
  local p = veh:getPosition()
  local object = createObject('TSStatic')
  object:setField('shapeName', 0, shape)
  object:setField('collisionType', 0, 'Collision Mesh')
  object:setField('decalType', 0, 'None')
  object:setPosRot(p.x + 8 + dx, p.y + 8, p.z + 1, 0, 0, 0, 1)
  object:setScale(vec3(1, 1, 1))
  object:registerObject('')
  local group = assert(editor.resolveAddGroup and editor.resolveAddGroup(scenetree.MissionGroup) or scenetree.MissionGroup)
  group:addObject(object)
  extensions.hook('onEditorObjectAdded', object:getID())
  return object
end

local function saved()
  local doc = jsonReadFile(path)
  assert(doc and doc.schema == data.schema and type(doc.objects) == 'table', 'no saved file')
  return doc.objects
end

return P.task(function()
  if P.now() - start > 120 then return {error = 'editor test timed out', stage = stage, log = log} end
  if not editor_main.isEditorActive() or not extensions.editor_earthngSave then return end
  if stage == 'place' then
    first = place(0)
    editor.doSaveLevel() -- what Ctrl+S and File > Save Level call
    local rows = saved()
    assert(#rows == 1, 'first save: ' .. #rows)
    firstId = rows[1].id
    assert(first:getName() == data.objectName(firstId), 'saved object not renamed')
    assert(first:getGroup():getName() == 'E2R_editor', 'saved object not adopted')
    assert(#require('ge/extensions/e2r/native').editorObjects() == 1, 'world did not reload the record')
    log[#log + 1] = {stage = stage, lat = rows[1].lat, lon = rows[1].lon}
    stage = 'move'
    return
  end
  if stage == 'move' then
    local p = first:getPosition()
    first:setPosRot(p.x + 2, p.y, p.z, 0, 0, 0.3826834, 0.9238795) -- +2 m, 45 degrees
    editor.doSaveLevel()
    local rows = saved()
    assert(#rows == 1 and rows[1].id == firstId, 'move must update the same record')
    assert(math.abs(rows[1].lon - log[1].lon) > 1e-6, 'moved position not saved')
    log[#log + 1] = {stage = stage, lon = rows[1].lon}
    second = place(6)
    editor.doSaveLevel()
    assert(#saved() == 2, 'second object not added')
    stage = 'delete'
    return
  end
  if stage == 'delete' then
    editor.selectObjects({second:getID()})
    stage = 'deleting'
    return
  end
  if stage == 'deleting' then
    editor.deleteSelection() -- the Delete key's function
    stage = 'deleted'
    return
  end
  if stage == 'deleted' then
    editor.doSaveLevel()
    local rows = saved()
    assert(#rows == 1 and rows[1].id == firstId, 'editor delete not saved: ' .. #rows)
    editor.undo()
    stage = 'undone'
    return
  end
  if stage == 'undone' then
    editor.doSaveLevel()
    local rows = saved()
    assert(#rows == 2, 'undone delete not saved again: ' .. #rows)
    local pending = extensions.editor_earthngSave.pending()
    editor_main.setEditorActive(false, false)
    return {status = 'passed', objects = rows, pending = pending, log = log,
      editorCallback = 'editor.doSaveLevel'}
  end
end)
