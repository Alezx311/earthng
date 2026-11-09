-- The mod's own pedestrians (walkers.lua) and hit pool (pedhit.lua) in a running test game
-- (test_world.py --walkers N --probe): the player's car, under the game's script AI, drives at
-- SPEED over the sidewalk through the nearest walker ahead of it. Reports what the pool did
-- (placed, hit, missed), the body's broken beams and throw; stills e2r_probe/walk_hit_<n>.png.
local SPEED = 8.3      -- replaced by the caller
local world = extensions.e2r_world
local function upvalue(fn, name)
  for i = 1, 300 do
    local n, v = debug.getupvalue(fn, i)
    if not n then return end
    if n == name then return v end
  end
end
local S = upvalue(world.walkersStep, 'S')
if not (S and S.walk) then return {error = 'walkers off'} end
local W, H = S.walk.W, S.walk.P
local car = be:getPlayerVehicle(0)
if not car or car.JBeam == 'e2r_ped' then return {error = 'player car', jbeam = car and car.JBeam} end
local cp = car:getPosition()
-- the walker to run into: within 300 m, on a sidewalk line (not a transit leg) with 45 m of it behind
local function along(line, cum, d)
  local n = #cum
  d = math.max(0, math.min(cum[n], d))
  local k = 1
  while k < n - 1 and cum[k + 1] < d do k = k + 1 end
  local j = 3 * (k - 1) + 1
  local len = cum[k + 1] - cum[k]
  local f = len > 1e-6 and (d - cum[k]) / len or 0
  return vec3(line[j] + (line[j + 3] - line[j]) * f, line[j + 1] + (line[j + 4] - line[j + 1]) * f, line[j + 2])
end
local best, bestD
for _, w in pairs(W.slots) do
  if not w.free and not w.taken and not w.transit and w.s > 45 then
    local cum = w.seg.cums[w.side]
    local d = math.sqrt((w.x - cp.x) ^ 2 + (w.y - cp.y) ^ 2)
    if cum[#cum] - w.s > 20 and d < 300 and (not bestD or d < bestD) then best, bestD = w, d end
  end
end
if not best then return {error = 'no walker near', count = W.count} end
local w = best
w.speed = 0.01   -- the test aims at a standing walker
local line, cum = w.seg.lines[w.side], w.seg.cums[w.side]
local target = vec3(w.x, w.y, w.z)
local start = along(line, cum, w.s - 40)
local dir = (along(line, cum, w.s - 36) - start):normalized()
local ACC = 3
local ramp = SPEED * SPEED / (2 * ACC)
local path, d = {}, 2
while d < 60 do
  local p = along(line, cum, w.s - 40 + d)
  local z = be:getSurfaceHeightBelow(vec3(p.x, p.y, p.z + 4))
  local t = d < ramp and math.sqrt(2 * d / ACC) or SPEED / ACC + (d - ramp) / SPEED
  path[#path + 1] = {x = p.x, y = p.y, z = (z and z > -1e6) and z or p.z, t = t}
  d = d + 2
end
local gz = be:getSurfaceHeightBelow(vec3(start.x, start.y, start.z + 4))
if gz and gz > -1e6 then start.z = gz end
local before = {placed = H.stats.placed, hit = H.stats.hit, missed = H.stats.missed, noBody = H.stats.noBody}
local q = quatFromDir(dir, vec3(0, 0, 1))
car:setPositionRotation(start.x, start.y, start.z + .3, q.x, q.y, q.z, q.w)
car:queueLuaCommand('recovery.saveHome() ai.startFollowing(' .. serialize({path = path}) .. ')')
-- the camera beside the walker
local camPos = target + vec3(-dir.y, dir.x, 0) * 9 + vec3(0, 0, 2.5) - dir * 6
local cq = quatFromDir((target + vec3(0, 0, .8) - camPos):normalized(), vec3(0, 0, 1))
commands.setFreeCamera()
core_camera.setPosRot(0, camPos.x, camPos.y, camPos.z, cq.x, cq.y, cq.z, cq.w)
createScreenshot2({filename = 'e2r_probe/walk_hit_0', writeJPG = false, superSampling = 1})
local t0 = os.clock()
local shots, shot, bodyId, hitAt = {}, 0, nil, nil
-- every body placed during the drive: its greatest speed change and nearest approach of the car's box
local trace, last = {}, {}
for _, e in ipairs(H.pool) do last[e.id] = e.state end
return P.task(function()
  local now = os.clock() - t0
  local box = car:getSpawnWorldOOBB()
  local c = box:getCenter()
  for _, e in ipairs(H.pool) do
    local tr = trace[e.id]
    if e.state == 'placed' then
      if not tr or tr.done then tr = {at = now, dv = 0, d = 1e9}; trace[e.id] = tr end
      local o = be:getObjectByID(e.id)
      local bp, bv = o:getPosition(), o:getVelocity()
      tr.dv = math.max(tr.dv, math.sqrt((bv.x - e.vx) ^ 2 + (bv.y - e.vy) ^ 2))
      tr.d = math.min(tr.d, math.sqrt((bp.x - c.x) ^ 2 + (bp.y - c.y) ^ 2))
    elseif tr and not tr.done and last[e.id] == 'placed' then
      tr.done, tr.to, tr.after = true, e.state, now - tr.at
    end
    last[e.id] = e.state
  end
  for _, e in ipairs(H.pool) do
    if e.walker == w and not bodyId then bodyId = e.id end
  end
  if not hitAt and H.stats.hit > before.hit then hitAt = now end
  local wantShot = hitAt and ({0, .25, .6, 1.5})[shot + 1]
  if wantShot and now - hitAt >= wantShot then
    shot = shot + 1
    createScreenshot2({filename = 'e2r_probe/walk_hit_' .. shot, writeJPG = false, superSampling = 1})
    shots[#shots + 1] = 'walk_hit_' .. shot
  end
  if (hitAt and now - hitAt > 3) or now > 25 then
    car:queueLuaCommand('ai.stopFollowing() ai.setMode("stop")')
    local body = bodyId and be:getObjectByID(bodyId)
    local bp = body and body:getPosition()
    local state
    for _, e in ipairs(H.pool) do if e.id == bodyId then state = e.state end end
    return {walkerAt = {target.x, target.y, target.z}, dist = bestD, body = bodyId, state = state,
      bodyAt = bp and {bp.x, bp.y, bp.z}, throw = bp and math.sqrt((bp.x - target.x) ^ 2 + (bp.y - target.y) ^ 2),
      placed = H.stats.placed - before.placed, hit = H.stats.hit - before.hit, missed = H.stats.missed - before.missed,
      noBody = H.stats.noBody - before.noBody, hitAt = hitAt, shots = shots, walkers = W.count, pool = #H.pool,
      carSpeed = car:getVelocity():length(), trace = trace}
  end
end)
