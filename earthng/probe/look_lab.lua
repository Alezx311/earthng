-- Look lab: the same views under variants of sky, fog and material fields, without a rebuild
-- (a --manual --probe session of test_world.py; earthng/look_lab.py drives it).
--
-- Set LAB in an earlier command, then run this file:
--   LAB = {views = {{'street', lat, lon, agl, atLat, atLon, atAgl, fov},
--                   {'g1', car = {7, 0, 1.9, -45, 0, 1.2}, fov = 60}, ...},   -- car: back, side, up of camera, target
--          variants = {{name = 'base'}, {name = 'warm', env = {sunsky = {skyBrightness = '40'}},
--                       mats = {e2rf_sidewalk = {baseColorFactor = '0.745 0.745 0.745 1'}}}},
--          settle = 2.5, viewSettle = 25, prefix = 'lab'}
-- A variant's mul = {e2rf_x = {r, g, b}} multiplies a material's baseColorFactor (a palette lab).
-- The CEF UI is hidden while the lab runs and shown again at the end.
-- A height ending in 'a' is absolute (z), otherwise it is over the ground under the point. A
-- target's height ending in 'c' is over the camera (a look at the horizon over tiles not loaded).
-- The views are the outer loop: a camera jump streams tiles in, a variant only changes fields.
-- Every field is put back after its variant. Shots: <user>/current/screenshots/<prefix>-<view>-<variant>.png
local W = extensions.e2r_world
local dbg = W and W.dbg and W.dbg()
local native = dbg and dbg.native
if not (LAB and native and native.localPoint) then return 'set LAB and land first' end

local function ground(x, y)
  local d = castRayStatic(vec3(x, y, 6000), vec3(0, 0, -1), 12000)
  return d and d < 12000 and 6000 - d or 0
end

local function point(lat, lon, agl, cam)
  local x, y = native.localPoint(lat, lon)
  if not x then return nil end
  local s = tostring(agl)
  if s:sub(-1) == 'a' then return vec3(x, y, tonumber(s:sub(1, -2))) end
  if s:sub(-1) == 'c' and cam then return vec3(x, y, cam.z + tonumber(s:sub(1, -2))) end
  return vec3(x, y, ground(x, y) + (tonumber(s) or 2))
end

local function apply(fields, restore)
  for objName, set in pairs(fields or {}) do
    local obj = scenetree.findObject(objName)
    if obj then
      restore[objName] = restore[objName] or {}
      for field, value in pairs(set) do
        if restore[objName][field] == nil then restore[objName][field] = obj:getField(field, 0) end
        obj:setField(field, 0, tostring(value))
      end
      if obj.reload and obj:getClassName() == 'Material' then obj:reload() end
      pcall(function() obj:postApply() end)
    end
  end
end

local function scale(muls, restore)
  for objName, m in pairs(muls or {}) do
    local obj = scenetree.findObject(objName)
    if obj then
      restore[objName] = restore[objName] or {}
      local cur = obj:getField('baseColorFactor', 0)
      if restore[objName].baseColorFactor == nil then restore[objName].baseColorFactor = cur end
      local c = {}
      for x in tostring(cur):gmatch('[^%s]+') do c[#c + 1] = tonumber(x) end
      if #c < 3 then c = {1, 1, 1, 1} end
      obj:setField('baseColorFactor', 0, string.format('%.4f %.4f %.4f %s', c[1] * m[1], c[2] * m[2], c[3] * m[3], c[4] or 1))
      if obj.reload then obj:reload() end
    end
  end
end

local function undo(restore)
  for objName, set in pairs(restore) do
    local obj = scenetree.findObject(objName)
    if obj then
      for field, value in pairs(set) do obj:setField(field, 0, value) end
      if obj.reload and obj:getClassName() == 'Material' then obj:reload() end
      pcall(function() obj:postApply() end)
    end
  end
end

local views, variants = LAB.views or {}, LAB.variants or {{name = 'base'}}
local settle, viewSettle, prefix = LAB.settle or 2.5, LAB.viewSettle or 25, LAB.prefix or 'lab'
local vi, ki, phase, at, restore, done = 1, 0, 'move', 0, nil, {}
pcall(function() commands.setFreeCamera() end)
pcall(function() extensions.ui_visibility.setCef(false) end)

return P.task(function()
  local now = P.now()
  local v = views[vi]
  if not v then
    pcall(function() extensions.ui_visibility.setCef(true) end)
    return {shots = done}
  end
  if phase == 'move' then
    local cam, look
    if v.car then
      -- round the player's car, as the gallery's g-views: {back, side, up} of the camera and the target
      local veh = getPlayerVehicle(0)
      if veh then
        local p, d = veh:getPosition(), veh:getDirectionVector()
        local f = vec3(d.x, d.y, 0):normalized()
        local r = vec3(f.y, -f.x, 0)
        local function at(b, s, u) return vec3(p.x - f.x * b + r.x * s, p.y - f.y * b + r.y * s, p.z + u) end
        cam, look = at(v.car[1], v.car[2], v.car[3]), at(v.car[4], v.car[5], v.car[6])
      end
    else
      cam = point(v[2], v[3], v[4])
      look = cam and point(v[5], v[6], v[7], cam)
    end
    if not (cam and look) then vi = vi + 1; return end
    local q = quatFromDir(look - cam, vec3(0, 0, 1))
    core_camera.setPosRot(0, cam.x, cam.y, cam.z, q.x, q.y, q.z, q.w)
    if v[8] or v.fov then pcall(function() core_camera.setFOV(0, v[8] or v.fov) end) end
    phase, at = 'load', now
  elseif phase == 'load' then
    -- tiles round the new camera: wait until the scheduler is quiet or the time is up
    local st = dbg.S and dbg.S.status and dbg.S.status.stream or {}
    local queue = dbg.S and #(dbg.S.queue or {}) or 0
    local quiet = queue == 0 and (st.pending or 0) == 0
    if (quiet and now - at > 6) or now - at > viewSettle then
      -- a geo view over the ground: the ray at the jump may have missed tiles not yet streamed
      -- (the camera stood under the ground), so it is put over the ground again
      if not v.car then
        local cam = point(v[2], v[3], v[4])
        local look = cam and point(v[5], v[6], v[7], cam)
        if cam and look then
          local q = quatFromDir(look - cam, vec3(0, 0, 1))
          core_camera.setPosRot(0, cam.x, cam.y, cam.z, q.x, q.y, q.z, q.w)
        end
      end
      phase, ki = 'variant', 0
    end
  elseif phase == 'variant' then
    if restore then undo(restore) end
    ki = ki + 1
    local k = variants[ki]
    if not k then restore, vi, phase = nil, vi + 1, 'move'; return end
    restore = {}
    apply(k.env, restore)
    apply(k.mats, restore)
    scale(k.mul, restore)
    phase, at = 'settle', now
  elseif phase == 'settle' then
    if now - at > settle then
      local name = prefix .. '-' .. v[1] .. '-' .. variants[ki].name
      createScreenshot2({filename = 'screenshots/' .. name, writeJPG = false, superSampling = 1})
      done[#done + 1] = name
      phase, at = 'shot', now
    end
  elseif phase == 'shot' then
    if now - at > 0.6 then phase = 'variant' end
  end
end)
