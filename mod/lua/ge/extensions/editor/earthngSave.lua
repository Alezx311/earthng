-- EarthNG objects in the World Editor.
--
-- In an EarthNG world Ctrl+S (File > Save Level) saves the user's own objects into
-- settings/earthng-editor-objects.json instead of serializing the level: placed,
-- duplicated or pasted meshes are added, saved ones that were moved, rotated, scaled
-- or given another shape are updated, saved ones deleted in the editor are removed.
-- Nothing has to be selected and nothing needs a restart: the running world reloads
-- the records, and every later tile, landing or game start brings them back.
-- Generated scenery (streets, buildings, trees, props) is not saved here.
local M = {}
local data = require('ge/extensions/e2r/manual_editor')
local native = require('ge/extensions/e2r/native')
local LEVEL = 'e2r_world'
local WINDOW = 'earthngObjects'
local GROUP = 'E2R_editor'

local baseline, baselineMission = nil, nil -- objects in the scene when editing began here
local fresh = {}    -- ids the editor created, duplicated or pasted (or selected while new)
local watched = {}  -- id -> {rid, group}: saved objects in the current selection
local removed = {}  -- record id -> true: deleted in the editor, not saved yet
local summary, summaryAt = nil, -math.huge
local sweep -- defined below collect's helpers
local hinted = false
local original = {}

local function notify(message)
  if editor and editor.showNotification then editor.showNotification('EarthNG: ' .. message) end
  if type(log) == 'function' then log('I', 'editor_earthngSave', message) end
end

local function inLevel()
  return type(getCurrentLevelIdentifier) == 'function' and getCurrentLevelIdentifier() == LEVEL
end

local function clock()
  return type(os) == 'table' and os.clock and os.clock() or 0
end

local function nameOf(obj) return obj:getName() or '' end
local function generatedName(obj) return nameOf(obj):lower():sub(1, 3) == 'e2r' end
local function alive(group)
  local name = group and group:getName()
  return group ~= nil and name ~= nil and name ~= ''
end

-- Runtime objects belong to generated groups (E2R*). Never traverse them: a tile
-- holds thousands of objects, and none of them is the user's.
local function snapshot(group, ids, visited, out)
  if visited[group:getID()] then return end
  visited[group:getID()] = true
  if generatedName(group) then return end
  for i = 0, group:getCount() - 1 do
    local obj = group:getObject(i)
    -- getObject returns a bare SimObject: a child group has no getCount until upcast
    if obj and type(Sim) == 'table' and Sim.upcast then obj = Sim.upcast(obj) end
    if obj then
      local cls = obj:getClassName()
      if cls == 'SimGroup' or cls == 'SimSet' then
        snapshot(obj, ids, visited, out)
      else
        ids[obj:getID()] = true
        if out then out[#out + 1] = obj end
      end
    end
  end
end

local function inGeneratedGroup(obj)
  local current = obj:getGroup()
  for _ = 1, 64 do
    if not current then return false end
    if generatedName(current) then return true end
    current = current:getGroup()
  end
  return true -- malformed/cyclic ancestry: fail closed
end

local function finite(n)
  return type(n) == 'number' and n == n and math.abs(n) < math.huge
end

-- A new object of the user's: a mesh that is not generated scenery and not a saved
-- object itself. Inside a generated group only a copy of a saved object (or one the
-- editor itself created there) counts: grass and stones there are nameless too.
local function isNew(obj, id)
  if baseline and baseline[id] then return false end
  if obj:getClassName() ~= 'TSStatic' or generatedName(obj) or data.idOfName(nameOf(obj)) then return false end
  return not inGeneratedGroup(obj) or fresh[id] == true
end

local function shapeOf(obj)
  local s = tostring(obj:getField('shapeName', 0) or ''):gsub('\\', '/')
  if s ~= '' and s:sub(1, 1) ~= '/' then s = '/' .. s end
  return s
end

local function makeRecord(obj, id)
  local p = obj:getPosition()
  local q = quat(obj:getRotation())
  local scale = obj:getScale()
  local box = obj:getWorldBox()
  if not (p and q and scale and box and box.minExtents and box.maxExtents) then
    return nil, 'cannot read the transform or bounds of ' .. obj:getID()
  end
  local bmin, bmax = box.minExtents, box.maxExtents
  for _, n in ipairs({p.x, p.y, p.z, q.x, q.y, q.z, q.w, scale.x, scale.y, scale.z, bmin.x, bmin.y, bmax.x, bmax.y}) do
    if not finite(n) then return nil, 'invalid transform or bounds of ' .. obj:getID() end
  end
  if bmin.x > bmax.x or bmin.y > bmax.y then return nil, 'invalid bounds of ' .. obj:getID() end
  local dx = math.max(math.abs(bmin.x - p.x), math.abs(bmax.x - p.x))
  local dy = math.max(math.abs(bmin.y - p.y), math.abs(bmax.y - p.y))
  local lat, lon = native.toGeo(p.x, p.y)
  if not (finite(lat) and finite(lon)) then return nil, 'the EarthNG region is not loaded' end
  local north = data.northAngle(native.localPoint, lat, lon)
  if not north then return nil, 'the EarthNG region is not loaded' end
  return {id = id or tostring(Engine.generateUUID()):lower():gsub('[{}]', ''), lat = lat, lon = lon, z = p.z,
    shape = shapeOf(obj), rotation = data.turn({q.x, q.y, q.z, q.w}, -north),
    scale = {scale.x, scale.y, scale.z}, radius = math.max(.01, math.min(100, math.sqrt(dx * dx + dy * dy)))}
end

-- A saved object differs from its record (both in this landing's frame).
local function changed(obj, p)
  local pos, q, s = obj:getPosition(), quat(obj:getRotation()), obj:getScale()
  if math.abs(pos.x - p.x) > .01 or math.abs(pos.y - p.y) > .01 or math.abs(pos.z - p.z) > .01 then return true end
  if math.abs(s.x - p.scale[1]) > 1e-4 or math.abs(s.y - p.scale[2]) > 1e-4 or math.abs(s.z - p.scale[3]) > 1e-4 then return true end
  local r = p.rotation
  if math.abs(q.x * r[1] + q.y * r[2] + q.z * r[3] + q.w * r[4]) < 1 - 1e-6 then return true end
  return shapeOf(obj) ~= p.shape
end

-- Deleting clears the selection before any hook sees it (and the stock delete does not
-- even report the cleared selection), so the saved objects that were selected are
-- watched: one gone while its group still stands was deleted by the user. A tile
-- leaving buries or drops its whole group instead. Undo brings it back by name.
function sweep()
  for id, w in pairs(watched) do
    if not scenetree.findObjectById(id) then
      if alive(scenetree.findObjectById(w.group)) then removed[w.rid] = true end
      watched[id] = nil
    end
  end
end

-- What Ctrl+S would write now.
local function collect()
  local ch = {adds = {}, addIds = {}, updates = {}, removes = {}, unsupported = 0}
  if not scenetree or not scenetree.MissionGroup then return ch end
  sweep()
  local ids, objects = {}, {}
  snapshot(scenetree.MissionGroup, {}, {}, objects)
  for _, obj in ipairs(objects) do ids[obj:getID()] = true end
  for id in pairs(fresh) do ids[id] = true end
  for _, id in ipairs(editor and editor.selection and editor.selection.object or {}) do ids[id] = true end
  local saved = {}
  for _, p in ipairs(native.editorObjects()) do saved[p.id] = true end
  local sorted = {}
  for id in pairs(ids) do sorted[#sorted + 1] = id end
  table.sort(sorted)
  for _, id in ipairs(sorted) do
    local obj = scenetree.findObjectById(id)
    if obj then
      local rid = data.idOfName(nameOf(obj))
      if rid and not saved[rid] and fresh[id] and obj:getClassName() == 'TSStatic' then
        -- a saved deletion undone: the object is back under its own name, keep its id
        ch.adds[#ch.adds + 1] = obj
        ch.addIds[#ch.adds] = rid
      elseif isNew(obj, id) then
        ch.adds[#ch.adds + 1] = obj
      elseif fresh[id] and obj:getClassName() ~= 'TSStatic'
        and obj:getClassName() ~= 'SimGroup' and obj:getClassName() ~= 'SimSet' then
        ch.unsupported = ch.unsupported + 1
      end
    end
  end
  for _, p in ipairs(native.editorObjects()) do
    local obj = scenetree.findObject(data.objectName(p.id))
    if obj and alive(obj:getGroup()) and changed(obj, p) then ch.updates[#ch.updates + 1] = {obj = obj, record = p} end
  end
  for rid in pairs(removed) do
    if scenetree.findObject(data.objectName(rid)) or not saved[rid] then
      removed[rid] = nil -- undone, or not a record of this landing
    else
      ch.removes[#ch.removes + 1] = rid
    end
  end
  table.sort(ch.removes)
  return ch
end

local function editorGroup()
  local g = scenetree.findObject(GROUP)
  if g then return g end
  g = createObject('SimGroup')
  g:registerObject(GROUP)
  g.canSave = false
  scenetree.MissionGroup:addObject(g)
  return g
end

local function save()
  if not inLevel() then return notify('Open an EarthNG region first.') end
  local ch = collect()
  if #ch.adds + #ch.updates + #ch.removes == 0 then
    if editor.resetDirty then editor.resetDirty() end
    return notify(ch.unsupported > 0 and 'Nothing to save. Only meshes (TSStatic) are kept in EarthNG.'
      or 'Nothing to save.')
  end
  local adds, updates = {}, {}
  for i, obj in ipairs(ch.adds) do
    local ok, record, err = pcall(makeRecord, obj, ch.addIds[i])
    if not ok then return notify('Save failed: ' .. tostring(record)) end
    if not record then return notify('Save failed: ' .. err) end
    adds[#adds + 1] = record
  end
  for _, u in ipairs(ch.updates) do
    local ok, record, err = pcall(makeRecord, u.obj, u.record.id)
    if not ok then return notify('Save failed: ' .. tostring(record)) end
    if not record then return notify('Save failed: ' .. err) end
    updates[#updates + 1] = record
  end
  local called, ok, err = pcall(data.apply, {add = adds, update = updates, remove = ch.removes})
  if not called then return notify('Save failed: ' .. tostring(ok)) end
  if not ok then return notify('Save failed: ' .. tostring(err)) end
  -- Saved. A new object takes its record's name and joins the EarthNG group: tiles do not
  -- draw a second copy while it stands, and a new landing clears the group.
  local group = editorGroup()
  for i, obj in ipairs(ch.adds) do
    pcall(function()
      obj:setName(data.objectName(adds[i].id))
      obj.canSave = false
      group:addObject(obj)
    end)
    fresh[obj:getID()] = nil
  end
  for _, rid in ipairs(ch.removes) do removed[rid] = nil end
  local reloaded, reloadErr = native.reloadEditorObjects()
  if editor.resetDirty then editor.resetDirty() end
  summaryAt = -math.huge
  local parts = {}
  if #adds > 0 then parts[#parts + 1] = #adds .. ' new' end
  if #updates > 0 then parts[#parts + 1] = #updates .. ' changed' end
  if #ch.removes > 0 then parts[#parts + 1] = #ch.removes .. ' removed' end
  if not reloaded then
    return notify('Saved (' .. table.concat(parts, ', ') .. '), but the world did not reload them: '
      .. tostring(reloadErr) .. '. They come back after the next landing.')
  end
  notify('Saved ' .. table.concat(parts, ', ') .. '.')
end

local function summarize()
  local now = clock()
  if not summary or now - summaryAt > 1 then
    local ok, ch = pcall(collect)
    summary = ok and {new = #ch.adds, changed = #ch.updates, removed = #ch.removes, unsupported = ch.unsupported,
      saved = #native.editorObjects()} or {error = tostring(ch)}
    summaryAt = now
  end
  return summary
end

local function pending()
  local s = summarize()
  return (s.new or 0) + (s.changed or 0) + (s.removed or 0)
end

-- Ctrl+S, File > Save Level and the save prompt all reach editor.doSaveLevel or
-- editor.saveLevel. In an EarthNG world they save EarthNG objects: serializing the
-- level would write the generated world into the user's levels/e2r_world/main and
-- shadow the planet's level. Level autosave is skipped here for the same reason.
local wrapped = {
  saveLevel = function(...)
    if not inLevel() then return original.saveLevel(...) end
    if editor.autosavingNow then return end
    save()
  end,
  doSaveLevel = function(...)
    if not inLevel() then return original.doSaveLevel(...) end
    save()
  end,
  autoSaveLevel = function(...)
    if inLevel() then return end
    return original.autoSaveLevel(...)
  end,
}
local function hookSave()
  if type(editor) ~= 'table' then return end
  for name, fn in pairs(wrapped) do
    -- (re)install over the editor's own function; it may be defined later or re-created
    if type(editor[name]) == 'function' and editor[name] ~= fn then
      original[name] = editor[name]
      editor[name] = fn
    end
  end
end

local function onEditorActivated()
  if not inLevel() then return end
  hookSave()
  local mission = scenetree and scenetree.MissionGroup and scenetree.MissionGroup:getID()
  if not baseline or baselineMission ~= mission then
    local ids = {}
    local ok, err = pcall(snapshot, scenetree.MissionGroup, ids, {})
    if not ok then return notify('Could not inspect the scene: ' .. tostring(err)) end
    baseline, baselineMission, fresh, watched, removed = ids, mission, {}, {}, {}
  end
  summaryAt = -math.huge
  if not hinted then
    hinted = true
    if editor.showWindow then editor.showWindow(WINDOW) end
    notify('place meshes as usual; Ctrl+S saves them into EarthNG.')
  end
end

local function onEditorDeactivated()
  if not inLevel() or not baseline then return end
  local ok, n = pcall(pending)
  if ok and n > 0 then
    local message = 'EarthNG: ' .. n .. ' object change(s) are not saved. Open the editor (F11) and press Ctrl+S.'
    if type(ui_message) == 'function' then ui_message(message, 10, 'earthng') end
    if type(log) == 'function' then log('W', 'editor_earthngSave', message) end
  end
end

local function onEditorObjectAdded(id)
  if inLevel() and id then fresh[id] = true; summaryAt = -math.huge end
end

local function onEditorDeleteSelection()
  if inLevel() and baseline then sweep(); summaryAt = -math.huge end
end

-- Watch the saved objects in the new selection (see sweep); remember new ones.
local function onEditorObjectSelectionChanged()
  if not inLevel() or not baseline then return end
  sweep()
  watched = {}
  for _, id in ipairs(editor.selection and editor.selection.object or {}) do
    local obj = scenetree.findObjectById(id)
    if obj then
      local rid, g = data.idOfName(nameOf(obj)), obj:getGroup()
      if rid and g then
        watched[id] = {rid = rid, group = g:getID()}
      elseif obj:getClassName() == 'TSStatic' and not baseline[id] and not generatedName(obj)
        and (not inGeneratedGroup(obj) or nameOf(obj):sub(1, #data.prefix) == data.prefix) then
        fresh[id] = true -- a duplicate or paste the editor has selected
      end
    end
  end
  summaryAt = -math.huge
end

local function onEditorGui()
  if not inLevel() or not editor.beginWindow then return end
  if editor.beginWindow(WINDOW, 'EarthNG objects') then
    local im = ui_imgui
    local s = summarize()
    if s.error then
      im.TextWrapped('Cannot read the scene: ' .. s.error)
    else
      im.Text('Saved here: ' .. s.saved)
      local n = s.new + s.changed + s.removed
      if n > 0 then
        im.TextColored(im.ImVec4(1, .8, .3, 1),
          string.format('Not saved: %d new, %d changed, %d removed', s.new, s.changed, s.removed))
      else
        im.Text('All changes are saved.')
      end
      if s.unsupported > 0 then
        im.TextWrapped(s.unsupported .. ' placed object(s) are not meshes (TSStatic) and are not kept.')
      end
      if im.Button('Save to EarthNG  (Ctrl+S)') then save() end
    end
    im.Separator()
    im.TextWrapped('Place stock meshes from the Asset Browser or Create Object. Move, rotate, scale, '
      .. 'duplicate and delete them as usual; Ctrl+S keeps the change in EarthNG at once, for every '
      .. 'landing and after a restart. Generated streets, buildings and trees are not saved.')
  end
  editor.endWindow()
end

local function onEditorInitialized()
  if editor.registerWindow and ui_imgui then editor.registerWindow(WINDOW, ui_imgui.ImVec2(380, 210)) end
  editor.addWindowMenuItem('EarthNG objects', function()
    if editor.showWindow then editor.showWindow(WINDOW) end
  end)
  hookSave()
end

M.onEditorActivated = onEditorActivated
M.onEditorDeactivated = onEditorDeactivated
M.onEditorInitialized = onEditorInitialized
M.onEditorObjectAdded = onEditorObjectAdded
M.onEditorObjectSelectionChanged = onEditorObjectSelectionChanged
M.onEditorDeleteSelection = onEditorDeleteSelection
M.onEditorGui = onEditorGui
M.save = save
M.saveSelection = save -- the first slice's menu callback, kept for probes
M.collect = collect
M.pending = pending
return M
