-- Does a hit snap the light pedestrian's locks (ped_body.py) into a loose body? The player's car is repaired
-- where it stands; one body is put 3 m from its side and thrown at it at SPEED m/s (the relative speed is
-- what the beams feel; pushing the parked car itself wrecked it on whatever stood ahead). Reports broken
-- beams, the body's height after and how far it went; stills e2r_probe/ped_hit_<km/h>_<n>.png.
local SPEED = 8.3   -- replaced by the caller
local MODEL = 'e2r_ped'
for i = be:getObjectCount() - 1, 0, -1 do
  local o = be:getObject(i)
  if o and o.JBeam == MODEL then o:delete() end
end
local veh = be:getPlayerVehicle(0)
veh:queueLuaCommand('obj:requestReset(RESET_PHYSICS)')
local up = vec3(0, 0, 1)
local c0, f, side, pos, gz, q             -- read once the reset has put the car back (frame 15)
local hold = veh:getPosition() + vec3(0, 0, 40)
local body = core_vehicles.spawnNewVehicle(MODEL, {pos = hold, rot = quat(0, 0, 0, 1), autoEnterVehicle = false,
  config = 'vehicles/' .. MODEL .. '/base.pc'})
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
local out = {speed = SPEED}
local t, frames, shots = 0, 0, 0
_G.e2r_ped_broken = nil
return P.task(function(dt)
  frames = frames + 1
  if frames < 15 then
    body:setPositionRotation(hold.x, hold.y, hold.z, 0, 0, 0, 1)   -- held aside while the car resets
    return nil
  end
  if frames == 15 then
    local d0 = veh:getDirectionVector()
    c0, f = veh:getPosition(), vec3(d0.x, d0.y, 0):normalized()
    side = vec3(-f.y, f.x, 0)
    pos = c0 + side * 3
    gz = be:getSurfaceHeightBelow(vec3(pos.x, pos.y, pos.z + 3))
    q = quatFromDir(f, up)            -- walking along the car, its side to the car
    local cam = c0 + side * 7 + f * 5 + up * 1.6
    local cq = quatFromDir(c0 + side * 1.5 + up * .6 - cam, up)
    commands.setFreeCamera()
    core_camera.setPosRot(0, cam.x, cam.y, cam.z, cq.x, cq.y, cq.z, cq.w)
    body:setPositionRotation(pos.x, pos.y, gz + 1.0, q.x, q.y, q.z, q.w)
    return nil
  end
  if frames == 17 then
    out.height0 = height(body)
    body:applyClusterVelocityScaleAdd(body:getRefNodeId(), 0, -side.x * SPEED, -side.y * SPEED, .3)
  end
  t = t + (dt or 0)
  if shots < 3 and t > ({.15, .4, 1.5})[shots + 1] then
    shots = shots + 1
    createScreenshot2({filename = string.format('e2r_probe/ped_hit_%d_%d', math.floor(SPEED * 3.6 + .5), shots),
      writeJPG = false, superSampling = 1})
  end
  if t > 2.5 and not out.asked then
    out.asked = true
    body:queueLuaCommand([[local n = 0
for i = 0, obj:getBeamCount() - 1 do if obj:beamIsBroken(i) then n = n + 1 end end
obj:queueGameEngineLua('e2r_ped_broken = ' .. n)]])
  end
  if t > 2.8 then
    local bp = body:getPosition()
    out.broken, out.height = _G.e2r_ped_broken, height(body)
    out.bounced = (vec3(bp.x, bp.y, 0) - vec3(pos.x, pos.y, 0)):dot(side)   -- + back off the car
    return out
  end
end)
