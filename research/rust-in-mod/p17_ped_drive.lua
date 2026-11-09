-- A car drives through the light physical pedestrian (ped_body.py), as the hand-off would meet it: a stock
-- car under the game's script AI (ai.startFollowing, timed points) speeds up along a straight edge of the
-- road graph near the player and holds SPEED; the body is put on the road, crossing, LEAD s before the
-- car's front reaches it. Reports the car's speed at the hit and after, the body's broken beams, height
-- and throw; stills e2r_probe/ped_drive_<km/h>_<n>.png. The camera stands beside the point of impact.
local SPEED = 8.3      -- replaced by the caller
local BRAKE = true     -- the driver brakes BRAKE_AFTER s after the hit (no braking: the body rides the bonnet)
local BRAKE_AFTER = .3
local LEAD = .3
local CAR = 'covet'
local up = vec3(0, 0, 1)
for _, id in ipairs({_G.e2r_drive_car, _G.e2r_drive_ped}) do
  local o = id and be:getObjectByID(id)
  if o then o:delete() end
end
for i = be:getObjectCount() - 1, 0, -1 do
  local o = be:getObject(i)
  if o and o.JBeam == 'e2r_ped' then o:delete() end
end

-- a long straight edge near the player: two graph nodes 90+ m apart, flat, the widest
local player = be:getPlayerVehicle(0):getPosition()
local best, bestScore
for name, n in pairs(map.getMap().nodes) do
  if n.pos:distance(player) < 400 then
    for other in pairs(n.links or {}) do
      local m = map.getMap().nodes[other]
      if m and name < other then
        local len = n.pos:distance(m.pos)
        if len > 90 and math.abs(n.pos.z - m.pos.z) < 3 then
          local score = math.min(n.radius, m.radius) * 10 + len * .1 - n.pos:distance(player) * .01
          if not bestScore or score > bestScore then best, bestScore = {n.pos, m.pos, math.min(n.radius, m.radius)}, score end
        end
      end
    end
  end
end
if not best then return {error = 'no straight edge'} end
local a, b = best[1], best[2]
local dir = vec3(b.x - a.x, b.y - a.y, 0):normalized()
local side = vec3(-dir.y, dir.x, 0)
local len = vec3(b.x - a.x, b.y - a.y, 0):length()
local function ground(p)
  local z = be:getSurfaceHeightBelow(vec3(p.x, p.y, p.z + 4))
  return (z and z > -1e6) and z or p.z
end
local function at(s)
  local p = a + (b - a) * (s / len)
  return vec3(p.x, p.y, ground(p))
end
-- timed points: speed up at 3 m/s2, then hold SPEED
local ACC = 3
local ramp = SPEED * SPEED / (2 * ACC)
local pedS = math.min(len - 15, ramp + 20)
local path, s = {}, 2
while s < len - 2 do
  local d = s - 2
  local t = d < ramp and math.sqrt(2 * d / ACC) or SPEED / ACC + (d - ramp) / SPEED
  local p = at(s)
  path[#path + 1] = {x = p.x, y = p.y, z = p.z, t = t}
  s = s + 2
end
local start = at(2)
local carQ = quatFromDir(dir, up)
local car = core_vehicles.spawnNewVehicle(CAR, {pos = start + up * .5, rot = carQ, autoEnterVehicle = false})
_G.e2r_drive_car = car:getID()
local pedPos = at(pedS)
local park = pedPos + side * 40 + up * 30
local body = core_vehicles.spawnNewVehicle('e2r_ped', {pos = park, rot = quat(0, 0, 0, 1), autoEnterVehicle = false,
  config = 'vehicles/e2r_ped/base.pc'})
_G.e2r_drive_ped = body:getID()
pcall(function() body.playerUsable = false end)
local look = {{.75, .1, .1}, {.08, .1, .2}, {.86, .68, .55}}
for i, k in ipairs({'color', 'colorPalette0', 'colorPalette1'}) do
  pcall(function() body[k] = ColorF(look[i][1], look[i][2], look[i][3], 1):asLinear4F() end)
end
local function height(v)
  local box = v:getSpawnWorldOOBB()
  local h = box:getHalfExtents()
  local z = 0
  for k = 0, 2 do z = z + math.abs(box:getAxis(k).z) * ({h.x, h.y, h.z})[k + 1] end
  return 2 * z
end
local cam = pedPos + side * 7 + dir * 1 + up * 1.6
local cq = quatFromDir(pedPos + dir * 5 + up * .6 - cam, up)
commands.setFreeCamera()
core_camera.setPosRot(0, cam.x, cam.y, cam.z, cq.x, cq.y, cq.z, cq.w)
local out = {speed = SPEED, road = {len = len, radius = best[3], pedAt = pedS}}
local frames, t, hitT, shots = 0, 0, nil, 0
local tag = math.floor(SPEED * 3.6 + .5)
_G.e2r_ped_broken = nil
return P.task(function(dt)
  frames = frames + 1
  if frames < 20 then
    body:setPositionRotation(park.x, park.y, park.z, 0, 0, 0, 1)
    return nil
  end
  if frames == 20 then
    car:queueLuaCommand('ai.startFollowing(' .. serialize({path = path}) .. ')')
    return nil
  end
  t = t + (dt or 0)
  if not out.placedAt then
    body:setPositionRotation(park.x, park.y, park.z, 0, 0, 0, 1)
    local box = car:getSpawnWorldOOBB()
    local c, he = box:getCenter(), box:getHalfExtents()
    local front = (pedPos - vec3(c.x, c.y, pedPos.z)):dot(dir) - math.max(he.x, he.y)
    local cv = car:getVelocity()
    local v = math.sqrt(cv.x ^ 2 + cv.y ^ 2)
    if front < math.max(v, 1) * LEAD then
      local q = quatFromDir(-side, up)
      body:setPositionRotation(pedPos.x, pedPos.y, pedPos.z + .99, q.x, q.y, q.z, q.w)
      out.placedAt, out.frontAtPlace, out.carSpeedAtPlace = t, front, v
      return nil
    end
    if t > 25 then out.timeout = true; return out end
    return nil
  end
  if not hitT then
    local bv = body:getVelocity()
    if t > out.placedAt + .03 and math.sqrt(bv.x ^ 2 + bv.y ^ 2) > 2 then
      hitT = t
      out.hitAfterPlace = t - out.placedAt
      out.height0 = height(body)
    elseif t > out.placedAt + 2 then
      out.noHit = true
      out.height = height(body)
      return out
    end
    return nil
  end
  local since = t - hitT
  if BRAKE and since > BRAKE_AFTER and not out.braked then
    out.braked = true
    car:queueLuaCommand('ai.stopFollowing() ai.setMode("stop")')
  end
  if shots < 4 and since > ({.1, .4, .9, 2.2})[shots + 1] then
    shots = shots + 1
    createScreenshot2({filename = string.format('e2r_probe/ped_drive_%d_%d', tag, shots), writeJPG = false, superSampling = 1})
  end
  if since > .5 and not out.carSpeedAfter then
    local cv = car:getVelocity()
    out.carSpeedAfter = math.sqrt(cv.x ^ 2 + cv.y ^ 2)
  end
  if since > 2.6 and not out.asked then  -- (beams counted before the camera moves)
    out.asked = true
    body:queueLuaCommand([[local n = 0
for i = 0, obj:getBeamCount() - 1 do if obj:beamIsBroken(i) then n = n + 1 end end
obj:queueGameEngineLua('e2r_ped_broken = ' .. n)]])
  end
  if since > 2.9 and not out.restShot then
    -- a close look at where the body came to rest
    out.restShot = true
    local bp = body:getPosition()
    local rc = vec3(bp.x, bp.y, bp.z) + side * 3.2 - dir * 1.5 + up * 1.4
    local rq = quatFromDir(vec3(bp.x, bp.y, bp.z) - rc, up)
    core_camera.setPosRot(0, rc.x, rc.y, rc.z, rq.x, rq.y, rq.z, rq.w)
    return nil
  end
  if since > 3.1 and not out.rested then
    out.rested = true
    createScreenshot2({filename = string.format('e2r_probe/ped_drive_%d_rest', tag), writeJPG = false, superSampling = 1})
    return nil
  end
  if since > 3.4 then
    local bp = body:getPosition()
    out.broken, out.height = _G.e2r_ped_broken, height(body)
    out.thrown = vec3(bp.x - pedPos.x, bp.y - pedPos.y, 0):length()
    return out
  end
end)
