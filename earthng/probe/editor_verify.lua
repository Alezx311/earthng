-- Run after landing in a fresh test_world profile seeded from editor_save.lua
-- (--seed-editor-objects). Checks the objects the tiles spawned, not just the JSON.
local path = 'settings/earthng-editor-objects.json'
local data = require('ge/extensions/e2r/manual_editor')
local doc = assert(jsonReadFile(path), 'seeded file missing')
assert(doc.schema == data.schema and #doc.objects >= 1, 'unexpected seed')
local native = require('ge/extensions/e2r/native')
local start = P.now()

return P.task(function()
  local records = native.editorObjects()
  local found = {}
  for _, record in ipairs(records) do
    local obj = scenetree.findObject(data.objectName(record.id))
    if obj then
      local p, s, q = obj:getPosition(), obj:getScale(), quat(obj:getRotation())
      local x, y = native.localPoint(record.lat, record.lon)
      assert(x and y, 'active projection unavailable')
      assert(math.abs(p.x - x) < .25 and math.abs(p.y - y) < .25 and math.abs(p.z - record.z) < .25,
        'restored position mismatch')
      assert(math.abs(s.x - record.scale[1]) < .001 and math.abs(s.y - record.scale[2]) < .001
        and math.abs(s.z - record.scale[3]) < .001, 'restored scale mismatch')
      local r = record.rotation
      assert(math.abs(math.abs(q.x * r[1] + q.y * r[2] + q.z * r[3] + q.w * r[4]) - 1) < .001, 'restored rotation mismatch')
      assert(obj:getField('shapeName', 0) == record.shape, 'restored shape mismatch')
      local g = obj:getGroup()
      found[#found + 1] = {id = record.id, group = g and g:getName(), x = p.x, y = p.y, z = p.z}
    end
  end
  if #records == #doc.objects and #found == #records then
    return {status = 'passed', found = found, frames = P.frames(300)}
  end
  if P.now() - start > 180 then return {error = 'restored objects not found', records = #records, found = found} end
end)
