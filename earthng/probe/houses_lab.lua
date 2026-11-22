-- Houses lab: the same views of the same streets as one region's houses after another
-- (a --manual --probe session of test_world.py on the proving ground or any pack).
--
-- Set LAB in an earlier command, then run this file:
--   LAB = {views = {{'a6-street', lat, lon, agl, atLat, atLon, atAgl, fov},
--                   {'left', car = {-2, 0, 2.2, -25, -18, 2.5}, fov = 60}, ...},
--          variants = {{name = 'ukraine'}, {name = 'japan', block = 'east-asia', country = 'japan'},
--                      {name = 'khata', style = 'ua_khata'}},
--          tiles = {'-7_0'}, viewSettle = 40, prefix = 'houses'}
-- A variant sets the lab's world values (look.block, houseCountry, houseStyle; what it does not
-- name goes back to its default), the tiles are built again, and every view is shot once the
-- stream is quiet. The variants are the outer loop: a rebuild is the slow part.
-- Shots: <user>/current/screenshots/<prefix>-<variant>-<view>.png
local W = extensions.e2r_world
local dbg = W and W.dbg and W.dbg()
local native = dbg and dbg.native
if not (LAB and native and native.localPoint and native.lab) then return 'set LAB and land first' end

local function ground(x, y)
  local d = castRayStatic(vec3(x, y, 6000), vec3(0, 0, -1), 12000)
  return d and d < 12000 and 6000 - d or 0
end
local function point(lat, lon, agl)
  local x, y = native.localPoint(lat, lon)
  if not x then return nil end
  return vec3(x, y, ground(x, y) + (tonumber(agl) or 2))
end
local function aim(v)
  local cam, look
  if v.car then
    -- round the player's car: {back, side, up} of the camera and of its target (side: to the right)
    local veh = getPlayerVehicle(0)
    if veh then
      local p, d = veh:getPosition(), veh:getDirectionVector()
      local f = vec3(d.x, d.y, 0):normalized()
      local r = vec3(f.y, -f.x, 0)
      local function at(back, side, up) return vec3(p.x - f.x * back + r.x * side, p.y - f.y * back + r.y * side, p.z + up) end
      cam, look = at(v.car[1], v.car[2], v.car[3]), at(v.car[4], v.car[5], v.car[6])
    end
  else
    cam = point(v[2], v[3], v[4])
    look = cam and point(v[5], v[6], v[7])
  end
  if not (cam and look) then return false end
  local q = quatFromDir(look - cam, vec3(0, 0, 1))
  core_camera.setPosRot(0, cam.x, cam.y, cam.z, q.x, q.y, q.z, q.w)
  if v[8] or v.fov then pcall(function() core_camera.setFOV(0, v[8] or v.fov) end) end
  return true
end

local views, variants = LAB.views or {}, LAB.variants or {{name = 'base'}}
local viewSettle, prefix = LAB.viewSettle or 40, LAB.prefix or 'houses'
local ki, vi, phase, at, done = 0, 0, 'variant', 0, {}
pcall(function() commands.setFreeCamera() end)
pcall(function() extensions.ui_visibility.setCef(false) end)

return P.task(function()
  local now = P.now()
  if phase == 'variant' then
    ki = ki + 1
    local k = variants[ki]
    if not k then
      pcall(function() extensions.ui_visibility.setCef(true) end)
      return {shots = done}
    end
    local lab = native.lab
    local want = {['look.block'] = k.block, houseCountry = k.country, houseStyle = k.style}
    for _, key in ipairs({'look.block', 'houseCountry', 'houseStyle'}) do
      if want[key] ~= nil then lab.set(key, want[key]) else lab.reset(key) end
    end
    -- LAB.tiles: only these tiles are built again (their neighbours keep the look they had)
    if LAB.tiles then for _, key in ipairs(LAB.tiles) do W.tileAgain(key) end else W.tileAgain(nil) end
    vi, phase, at = 0, 'view', now
  elseif phase == 'view' then
    vi = vi + 1
    local v = views[vi]
    if not v then phase = 'variant'; return end
    if not aim(v) then return end
    phase, at = 'load', now
  elseif phase == 'load' then
    local st = dbg.S and dbg.S.status and dbg.S.status.stream or {}
    local queue = dbg.S and #(dbg.S.queue or {}) or 0
    local quiet = queue == 0 and (st.pending or 0) == 0
    if (quiet and now - at > 8) or now - at > viewSettle then
      aim(views[vi])      -- over the ground as it is now
      phase, at = 'settle', now
    end
  elseif phase == 'settle' then
    if now - at > 2 then
      local name = prefix .. '-' .. variants[ki].name .. '-' .. views[vi][1]
      createScreenshot2({filename = 'screenshots/' .. name, writeJPG = false, superSampling = 1})
      done[#done + 1] = name
      phase, at = 'shot', now
    end
  elseif phase == 'shot' then
    if now - at > .8 then phase = 'view' end
  end
end)
