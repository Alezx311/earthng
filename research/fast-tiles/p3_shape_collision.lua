-- Fast tiles, probe 3: what one shape file costs whatever its size, twenty materials when they are
-- warm, and the collision of a TSStatic made at run time: does be:reloadCollision take it, and does
-- hiding it for the rebuild leave it out (the trick collision.lua plays on ProceduralMesh).
local veh = getPlayerVehicle(0)
local at = veh:getPosition()
local R = {order = {}}
local made = {}

local function shape(file, pos, collision)
  local t = hptimer()
  local obj = createObject('TSStatic')
  obj:setField('shapeName', 0, file)
  obj:setField('collisionType', 0, collision or 'None')
  obj:setField('decalType', 0, 'None')
  obj.canSave = false
  obj:registerObject('')
  obj:setPosRot(pos.x, pos.y, pos.z, 0, 0, 0, 1)
  made[#made + 1] = obj
  return obj, math.floor(t:stop() * 100 + .5) / 100
end

-- a ray straight down onto the square's centre from 10 m over it: the distance, or -1
local function ray(pos)
  local d = castRayStatic(vec3(pos.x, pos.y, pos.z + 10), vec3(0, 0, -1), 14)
  return d and math.floor(d * 100) / 100 or -1
end

local A = vec3(at.x + 300, at.y, at.z + 120)
local B = vec3(at.x + 300, at.y + 150, at.z + 120)
local C = vec3(at.x + 300, at.y - 150, at.z + 120)
local hidden
local steps = {
  {'tiny', function() local _, ms = shape('/e2r_tiles/tiny.cdae', vec3(at.x, at.y, at.z + 60)); return {call = ms} end},
  {'tiny2', function() local _, ms = shape('/e2r_tiles/tiny_b.cdae', vec3(at.x, at.y, at.z + 62)); return {call = ms} end},
  {'m20_warm', function() local _, ms = shape('/e2r_tiles/g50k_m20_b.cdae', vec3(at.x + 150, at.y + 300, at.z + 8)); return {call = ms} end},
  {'m20_same20', function() local _, ms = shape('/e2r_tiles/g50k_s20.cdae', vec3(at.x + 150, at.y + 420, at.z + 8)); return {call = ms} end},
  {'solid', function()
    local _, ms = shape('/e2r_tiles/g20k_m1_c.cdae', A, 'Visible Mesh')
    local _, ms2 = shape('/e2r_tiles/g20k_m1_c.cdae', B, 'None')
    hidden = shape('/e2r_tiles/g20k_m1_c.cdae', C, 'Visible Mesh')
    return {call = ms, none = ms2, rayBefore = ray(A)}
  end},
  {'reload', function()
    hidden:setHidden(true)
    local t = hptimer(); be:reloadCollision(); local ms = t:stop()
    hidden:setHidden(false)
    return {call = math.floor(ms)}
  end},
  {'rays', function() return {solid = ray(A), none = ray(B), hiddenAtReload = ray(C)} end},
}
local WAIT = 14
local phase, frame, frames, current = 0, WAIT, {}, nil
return P.task(function(dt, ms)
  frame = frame + 1
  if current then frames[#frames + 1] = math.floor(ms * 10 + .5) / 10 end
  if frame < WAIT then return end
  if current then current.frames = table.concat(frames, ' ') end
  frames, frame = {}, 0
  phase = phase + 1
  local step = steps[phase]
  if not step then
    for _, obj in ipairs(made) do obj:delete() end
    return R
  end
  local ok, value = pcall(step[2])
  current = ok and value or {error = tostring(value)}
  R[step[1]] = current
  R.order[#R.order + 1] = step[1]
end)
