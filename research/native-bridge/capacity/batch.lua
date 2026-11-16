-- DynamicShapeBatch: the engine has a scene class that draws many instances of one shape set by
-- index (setInstance(i, pos, rot, scale, ColorF) was accepted in October, nothing was seen).
-- This lists what its Lua binding offers, tries it the ways the names suggest, times setInstance
-- and takes a still with and without it in front of the camera.
-- Run after common.lua: python earthng/probe.py --user <user> -f research/native-bridge/capacity/batch.lua --timeout 300
local out = {calls = {}, tries = {}}
local N = 4000
local SHAPE = CAP.ROCK
local cx, cy, cz = CAP.origin()

local function names(t)
  local list = {}
  if type(t) ~= 'table' then return list end
  for k, v in pairs(t) do list[#list + 1] = tostring(k) .. ':' .. type(v) end
  table.sort(list)
  return list
end

local ok, b = pcall(createObject, 'DynamicShapeBatch')
out.create = ok and 'ok' or tostring(b)
if not ok or not b then return out end
-- the binding's class table (lua/common/luaBinding.lua): string keys are methods, [1] getters,
-- [2] setters, [3] super; its own __index calls the engine, so read it raw
local function members(o)
  local mt = getmetatable(o)
  local m, g, s = {}, {}, {}
  if type(mt) ~= 'table' then return m, g, s end
  for k, v in next, mt do if type(k) == 'string' then m[k] = type(v) end end
  for k in next, (rawget(mt, 1) or {}) do g[tostring(k)] = true end
  for k in next, (rawget(mt, 2) or {}) do s[tostring(k)] = true end
  return m, g, s
end
local function sorted(set)
  local list = {}
  for k in pairs(set) do list[#list + 1] = k end
  table.sort(list)
  return list
end
local bm, bg, bs = members(b)
local okRef, ref = pcall(createObject, 'TSStatic')
local rm, rg, rs = {}, {}, {}
if okRef and ref then rm, rg, rs = members(ref) end
local onlyM, onlyG, onlyS = {}, {}, {}
for k in pairs(bm) do if not rm[k] then onlyM[k] = true end end
for k in pairs(bg) do if not rg[k] then onlyG[k] = true end end
for k in pairs(bs) do if not rs[k] then onlyS[k] = true end end
out.methodsNotInTSStatic = sorted(onlyM)
out.gettersNotInTSStatic = sorted(onlyG)
out.settersNotInTSStatic = sorted(onlyS)
out.methodCount = #sorted(bm)
out.methods = sorted(bm)
if okRef and ref then pcall(function() ref:delete() end) end

-- reflection the SimObject binding may have
for _, fn in ipairs({'getFields', 'getFieldsForEditor', 'getClassName'}) do
  local okF, value = pcall(function() return b[fn](b) end)
  if okF then
    if type(value) == 'table' then
      local list = {}
      for k, v in pairs(value) do list[#list + 1] = tostring(k) .. '=' .. (type(v) == 'table' and '{..}' or tostring(v)) end
      table.sort(list)
      value = list
    end
    out.calls[fn] = value
  end
end

-- try: shape fields, register, a count, instances in front of the camera
local function try(label, fn)
  local okR, value = pcall(fn)
  out.tries[#out.tries + 1] = {label, okR, okR and tostring(value) or tostring(value)}
  return okR, value
end
for _, field in ipairs({'shapeName', 'shapeFile', 'shape'}) do
  try('setField ' .. field, function() b:setField(field, 0, SHAPE); return b:getField(field, 0) end)
end
b.canSave = false
try('registerObject', function() return b:registerObject('e2rcap_batch') end)
try('addToMissionGroup', function() return scenetree.MissionGroup and scenetree.MissionGroup:addObject(b) end)
for _, m in ipairs({'setShape', 'setShapeName', 'loadShape'}) do try(m, function() return b[m](b, SHAPE) end) end
for _, m in ipairs({'setInstanceCount', 'resize', 'setCount', 'reserve', 'setNumInstances', 'allocate'}) do
  try(m, function() return b[m](b, N) end)
end

local cam = core_camera.getPosition()
local fwd = core_camera.getForward()
local timer = hptimer()
local rot, scale, colour = quat(0, 0, 0, 1), vec3(1, 1, 1), ColorF and ColorF(1, 1, 1, 1) or nil
local okI, err = pcall(function()
  local p = vec3(0, 0, 0)
  timer:stopAndReset()
  for i = 0, N - 1 do
    local d = 15 + (i % 40) * 3
    local side = (math.floor(i / 40) - 50) * 2.5
    p.x = cam.x + fwd.x * d - fwd.y * side
    p.y = cam.y + fwd.y * d + fwd.x * side
    p.z = cz
    b:setInstance(i, p, rot, scale, colour)
  end
  out.setInstanceUs = timer:stop() * 1000 / N
end)
out.setInstance = okI and 'ok' or tostring(err)
for _, m in ipairs({'update', 'rebuild', 'commit', 'flush', 'updateBatch', 'setDirty'}) do try(m, function() return b[m](b) end) end
local okBox, box = pcall(function() return b:getWorldBox() end)
if okBox and box then out.worldBox = tostring(box.minExtents) .. ' .. ' .. tostring(box.maxExtents) end

-- stills: with the batch, then hidden
local steps, frame = {}, 0
steps[1] = function() frame = frame + 1; return frame > 30 end
steps[2] = function()
  pcall(createScreenshot2, {filename = 'e2r_probe/cap_batch_on', writeJPG = false, superSampling = 1})
  return true
end
steps[3] = CAP.measure(out, 'batch-on', 60, 10)
steps[4] = function() pcall(function() b:setHidden(true) end); frame = 0; return true end
steps[5] = function() frame = frame + 1; return frame > 10 end
steps[6] = function()
  pcall(createScreenshot2, {filename = 'e2r_probe/cap_batch_off', writeJPG = false, superSampling = 1})
  return true
end
steps[7] = CAP.measure(out, 'batch-off', 60, 10)
steps[8] = function() pcall(function() b:delete() end); return true end
return CAP.run(steps, out)
