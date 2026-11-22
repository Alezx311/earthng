-- A walker run down by the player's car, as a strip of stills and a trace of the body, for
--   test_world.py --manual --probe --walkers 600 ... then
--   python earthng/probe.py --user <out>/user "_G.__hit = {speed = 13.9, name = 'a'} return 1"
--   python earthng/probe.py --user <out>/user -f earthng/probe/ped_hit.lua --timeout 90
-- The car is put a few metres short of the nearest walker on a sidewalk line and given `speed`
-- m/s towards it at once (no driver). A camera beside the walker follows it until its body takes its place (pedhit.lua),
-- then stands still. Stills e2r_probe/hit_<name>_<n>.png: every frame from just before the swap
-- until 0.5 s after the hit, then every sixth for 3 s (earthng/probe/strip.py makes one sheet of
-- them). The trace has, for every frame from the swap on, how far the body's lowest and highest
-- node stand over the ground it was placed on and its speed: a body that is lifted, thrown up or
-- sunk at the swap shows there. Options: speed (m/s), name, stand (the walker stands still),
-- side (m, the camera's distance), after (s of stills after the hit), brake (s after the hit the car
-- brakes hard; nil: it rolls on), alone (m round the walker without another), run (m of the car's run-up).
local O = _G.__hit or {}
local SPEED = O.speed or 13.9
local NAME = O.name or 'a'
local world = extensions.e2r_world
if not (world and world.dbg) then return {error = 'no world'} end
local S = world.dbg().S
if not (S and S.walk and S.walk.W and S.walk.P) then return {error = 'walkers off'} end
local W, H = S.walk.W, S.walk.P
local car = be:getPlayerVehicle(0)
if not car or car.JBeam == 'e2r_ped' then return {error = 'player car', jbeam = car and car.JBeam} end
local up = vec3(0, 0, 1)
local cp = car:getPosition()

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
local function ground(p)
  local h = be:getSurfaceHeightBelow(vec3(p.x, p.y, p.z + 3))
  return (h and h > -1e6) and h or p.z
end

-- the walker: within 300 m, walking a sidewalk line with 45 m of it behind and 30 m ahead
local best, bestD
-- alone on its stretch if one is: nobody else within 9 m, else 6, 4, 2 (the strip shows one body)
for _, ALONE in ipairs({O.alone or 9, 6, 4, 2, 0}) do
  for _, w in pairs(W.slots) do
    if not w.free and not w.taken and not w.transit and not w.stay and not w.inside and w.piece and w.s and w.s > 45 then
      local cum = w.piece.cum
      local d = math.sqrt((w.x - cp.x) ^ 2 + (w.y - cp.y) ^ 2)
      local alone = true
      for _, o in pairs(W.slots) do
        if o ~= w and not o.free and not o.inside and (o.x - w.x) ^ 2 + (o.y - w.y) ^ 2 < ALONE * ALONE then alone = false break end
      end
      if alone and cum[#cum] - w.s > 30 and d < 300 and (not bestD or d < bestD) then best, bestD = w, d end
    end
  end
  if best then break end
end
if not best then return {error = 'no walker near', count = W.count} end
local w = best
-- the walker all but stands (its pose stays the step it was in), unless asked to walk on
if not O.walk then w.speed = .01 end
local line, cum = w.piece.line, w.piece.cum
-- the car: reset, put RUN m short of the walker along its line, then given its speed at once (no
-- driver: the AI's way along a sidewalk ends at the first bench)
local RUN = O.run or (10 + SPEED * .35)
local target = vec3(w.x, w.y, w.z)
local back = along(line, cum, w.s - RUN)
local dir = (target - back):normalized()
dir.z = 0
dir = dir:normalized()
local start = target - dir * RUN
start.z = ground(start)
local before = {placed = H.stats.placed, hit = H.stats.hit, missed = H.stats.missed, noBody = H.stats.noBody,
  ghost = H.stats.ghost}
car:queueLuaCommand('obj:requestReset(RESET_PHYSICS)')
local launched = false
local function launch(frame)
  if frame == 20 then
    local q = quatFromDir(-dir, up)
    car:setPositionRotation(start.x, start.y, start.z + .25, q.x, q.y, q.z, q.w)
  elseif frame == 55 then
    car:queueLuaCommand("input.event('parkingbrake', 0, 2)")
    car:applyClusterVelocityScaleAdd(car:getRefNodeId(), 0, dir.x * SPEED, dir.y * SPEED, 0)
    launched = true
  end
end

local SIDE = O.side or (6 + SPEED * .25)
local AFTER = O.after or 3
local side = vec3(-dir.y, dir.x, 0)
pcall(function() commands.setFreeCamera() end)
local camAt
local function camera(at, eye)
  core_camera.setPosition(0, eye)
  core_camera.setRotation(0, quatFromDir((at - eye):normalized(), up))
end
local function follow()
  local p = vec3(w.x, w.y, (w.gz or w.z + .12))
  camAt = p
  camera(p + up * .9 + dir * 1.5, p + side * SIDE + up * 1.5 + dir * 2.5)
end
follow()

local R = {speed = SPEED, walker = {look = w.look, figure = world.walkSim.charOf and world.walkSim.charOf(w) and world.walkSim.charOf(w).name},
  shots = {}, trace = {}}
local frame, shots, placedAt, hitAt, body, z0, t = 0, 0, nil, nil, nil, nil, 0
local wasPose
return P.task(function(dt)
  frame = frame + 1
  t = t + (dt or 1 / 60)
  launch(frame)
  local c = car:getPosition()
  local gap = (vec3(w.x, w.y, c.z) - c):dot(dir)
  if not placedAt then
    follow()
    wasPose = world.walkSim.poseOf(w)
    for _, e in ipairs(H.pool) do
      if e.walker == w and e.state ~= 'idle' then
        body, placedAt, z0 = e, t, world.walkSim.standZ(w)
        R.pose = wasPose
        R.walkerAt = {w.x, w.y, z0}
        R.gapAtSwap = gap
      end
    end
  end
  if not hitAt and body and body.state == 'down' then hitAt = t end
  -- the stills: from 0.35 s short of the touch
  local near = launched and gap < SPEED * .35 + 3
  -- (a still every frame is more than the game writes: some never reach the disk)
  local every = (not hitAt or t - hitAt < .6) and 2 or 8
  if (near or placedAt) and frame % every == 0 and shots < 90 and (not hitAt or t - hitAt < AFTER) then
    shots = shots + 1
    pcall(createScreenshot2, {filename = string.format('e2r_probe/hit_%s_%03d', NAME, shots), writeJPG = false, superSampling = 1})
    R.shots[shots] = {t = math.floor(t * 1000) / 1000, placed = placedAt and true or false, hit = hitAt and true or false}
  end
  -- the driver brakes hard a moment after the hit (O.brake: s after it)
  if hitAt and O.brake and not R.braked and t - hitAt >= O.brake then
    R.braked = true
    car:queueLuaCommand("input.event('parkingbrake', 1, 2)")
  end
  if body then
    local o = getObjectByID(body.id)
    if o then
      local lo, hi = 1e9, -1e9
      local op = o:getPosition()
      -- the camera: beside the place of the swap until just after the hit, then with the body, from
      -- ahead of it and above (the car comes towards it, the body is not behind the car)
      if hitAt and t - hitAt > .12 then
        camera(op + up * -.1, op + side * (SIDE * .8) + dir * (SIDE * .9) + up * 2.6)
      end
      for n = 0, o:getNodeCount() - 1 do
        local z = o:getNodePosition(n).z + op.z
        if z < lo then lo = z end
        if z > hi then hi = z end
      end
      local v = o:getVelocity()
      if #R.trace < 400 then
        R.trace[#R.trace + 1] = {math.floor((t - placedAt) * 1000) / 1000, math.floor((lo - z0) * 1000) / 1000,
          math.floor((hi - z0) * 1000) / 1000, math.floor(v.z * 100) / 100,
          math.floor(math.sqrt(v.x * v.x + v.y * v.y) * 100) / 100, body.state}
      end
    end
  end
  if (hitAt and t - hitAt > AFTER + .3) or t > 40 or (placedAt and not hitAt and t - placedAt > 4) then
    local o = body and getObjectByID(body.id)
    local bp = o and o:getPosition()
    R.placed, R.hit, R.missed = H.stats.placed - before.placed, H.stats.hit - before.hit, H.stats.missed - before.missed
    R.ghost, R.noBody = H.stats.ghost - before.ghost, H.stats.noBody - before.noBody
    R.placedAt, R.hitAt, R.frames, R.state = placedAt, hitAt, frame, body and body.state
    R.throw = bp and R.walkerAt and math.sqrt((bp.x - R.walkerAt[1]) ^ 2 + (bp.y - R.walkerAt[2]) ^ 2)
    R.carSpeed = car:getVelocity():length()

    R.blood = world.bloodState and world.bloodState().kinds
    return R
  end
end)
