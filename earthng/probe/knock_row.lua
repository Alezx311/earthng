-- Cars through knockable props (knock.lua, docs/KNOCKDOWN.md), for test_world.py --knock or
--   python earthng/probe.py --user <out>/user -f earthng/probe/knock_row.lua --timeout 420
-- On the longest straight flat edge of the road graph near the player, props planted as the
-- generator's would be (world.knockPlant), one run after another (each its own fake tile, taken away
-- after it). Every car here is a spawned stock car, not the player's: it is the hitter knock.step gets
-- from pedhit.gameHitters like any traffic or hand-off car.
--   ai     ROW mixed props 3 m apart on the lane, a car under the game's script AI at SPEED1
--   fling  a fresh row, a car flung to SPEED2 (150 km/h) and coasting into it
--   crawl  four cars at 3 km/h side by side: three under script AI holding it, into a planter, into
--          a bin, into nothing (the control), and one coasting into a planter
--   inside a car spawned standing on a bin and a bench
--   wall   a car flung across the road at a building with a bin in front of it
--   swarm  90 bins in a 5 x 18 block, a car at 30 m/s through it (the most in the air at once)
-- Reports per run: knocked, missed, contacts, wall bounces, the car's speed before and after, its
-- damage and least upright, the most debris flying, knock.step ms (mean, max, max while 40+ fly),
-- frame times, how far each prop went. Stills e2r_probe/knock_<run>.png.
local W = extensions.e2r_world
if not W or not W.knockPlant then return {error = 'no world.knockPlant'} end
local SPEED1, SPEED2 = _G.e2r_knock_speed1 or 15, _G.e2r_knock_speed2 or 41.7
local CRAWL = .83
local ROW, GAP = 24, 3
local BIN = '/levels/west_coast_usa/art/shapes/objects/garbage_bin_a.dae'
local BENCH = '/levels/east_coast_usa/art/shapes/clutter/clutter_city_bench_wood.dae'
local PLANTER = '/levels/west_coast_usa/art/shapes/objects/planterbox.dae'
local KIND = {BIN, BENCH, '/art/shapes/objects/bollard_yellow.dae', PLANTER,
  '/art/shapes/garage_and_dealership/Clutter/italy_clutter_metal_bin.DAE',
  '/levels/west_coast_usa/art/shapes/objects/bollard_hoop_grey.dae'}
local up = vec3(0, 0, 1)
local R = {speed1 = SPEED1, speed2 = SPEED2, crawl = CRAWL}
local playerId = be:getPlayerVehicleID(0)

-- the straight edge
local player = be:getPlayerVehicle(0):getPosition()
local best, bestScore
for _, n in pairs(map.getMap().nodes) do
  if n.pos:distance(player) < 600 then
    for other in pairs(n.links or {}) do
      local m = map.getMap().nodes[other]
      if m then
        local len = n.pos:distance(m.pos)
        if len > 150 and math.abs(n.pos.z - m.pos.z) < 3 then
          local score = len - n.pos:distance(player) * .05
          if not bestScore or score > bestScore then best, bestScore = {n.pos, m.pos}, score end
        end
      end
    end
  end
end
if not best then return {error = 'no straight edge'} end
local a, b = best[1], best[2]
local len = vec3(b.x - a.x, b.y - a.y, 0):length()
local dir = vec3(b.x - a.x, b.y - a.y, 0):normalized()
local side = vec3(-dir.y, dir.x, 0)
local yaw = math.atan2(dir.x, dir.y)
local function ground(p)
  local z = be:getSurfaceHeightBelow(vec3(p.x, p.y, p.z + 4))
  return (z and z > -1e6) and z or p.z
end
local function at(s, l)
  local p = a + (b - a) * (s / len) + side * (l or 0)
  return vec3(p.x, p.y, ground(p))
end
R.edge = {len = math.floor(len), x = math.floor(a.x), y = math.floor(a.y)}
local rowStart = len - 18 - ROW * GAP

-- a building beside the road for the wall run: static rays across the road at 0.6, 1.2 and 2 m that
-- meet a surface at the same distance (a vertical wall, not a rising bank)
local wall
for _, sg in ipairs({1, -1}) do
  for s = len * .1, len * .9, 4 do
    local p = at(s)
    local d1 = castRayStatic(p + up * .6, side * sg, 45)
    local d2 = castRayStatic(p + up * 1.2, side * sg, 45)
    local d3 = castRayStatic(p + up * 2, side * sg, 45)
    if not wall and d1 and d1 > 14 and d1 < 40 and math.abs(d1 - d2) < .3 and math.abs(d1 - d3) < .3 then
      wall = {s = s, sg = sg, d = d1}
    end
  end
end
R.wall = wall and {at = math.floor(wall.s), side = wall.sg, d = math.floor(wall.d * 10) / 10} or 'none within 14..40 m'

-- does a TSStatic with the item's quaternion stand as the item does
do
  local m = MatrixF(true)
  m:setFromEuler(vec3(0, 0, .6))
  local q = m:toQuatF()
  local o = createObject('TSStatic')
  o:setField('shapeName', 0, KIND[1])
  o:registerObject('')
  o:setPosRot(a.x, a.y, a.z - 50, q.x, q.y, q.z, q.w)
  local c1, c2 = m:getColumn(0), o:getTransform():getColumn(0)
  R.rotationMatches = math.abs(c1.x - c2.x) + math.abs(c1.y - c2.y) < 1e-3
  o:delete()
end

local K = W.knockState().K
local knock = W.knock
local function spawn(p, heading)
  return core_vehicles.spawnNewVehicle('covet', {pos = p + up * .5, rot = quatFromDir(heading or dir, up),
    autoEnterVehicle = false})
end
local function speedOf(id)
  local o = be:getObjectByID(id)
  local v = o and o:getVelocity()
  return v and math.sqrt(v.x * v.x + v.y * v.y) or 0
end
local function r2(x) return x and math.floor(x * 100 + .5) / 100 end
local function aiPath(car, s0, s1, speed, lane)
  local path, s, ACC = {}, s0, 3
  local ramp = speed * speed / (2 * ACC)
  while s < s1 do
    local d = s - s0 + .5
    local t = d < ramp and math.sqrt(2 * d / ACC) or speed / ACC + (d - ramp) / speed
    local p = at(s, lane)
    path[#path + 1] = {x = p.x, y = p.y, z = p.z, t = t}
    s = s + (speed < 2 and .5 or 2)
  end
  car:queueLuaCommand('ai.startFollowing(' .. serialize({path = path}) .. ')')
end
local function fling(car, v, d)
  d = d or dir
  car:applyClusterVelocityScaleAdd(car:getRefNodeId(), 0, d.x * v, d.y * v, 0)
end

-- each run: plant(tile) -> props {id, x, y}; cars(); go(); done after `frames` drive frames
local RUNS
local run, phase, frame, tile, stats, cars, props, cur = 0, 'plant', 0, nil, nil, nil, nil, nil
local function plantAt(shape, p, y)
  local id = W.knockPlant(tile, shape, p.x, p.y, p.z, y or yaw)
  if id then props[#props + 1] = {id = id, x = p.x, y = p.y, shape = shape:match('([^/]+)$')} end
  return id
end

RUNS = {
  {name = 'ai', frames = 1000, rowAt = rowStart - 6, plant = function()
      for k = 1, ROW do plantAt(KIND[(k - 1) % #KIND + 1], at(rowStart + k * GAP, ((k % 3) - 1) * .5)) end
    end,
    cars = function() return {spawn(at(4))} end,
    go = function() aiPath(cars[1], 6, len - 4, SPEED1) end,
    cam = function() return rowStart + ROW * GAP * .5 end},
  {name = 'fling', frames = 420, rowAt = rowStart - 6, plant = function()
      for k = 1, ROW do plantAt(KIND[(k - 1) % #KIND + 1], at(rowStart + k * GAP, ((k % 3) - 1) * .5)) end
    end,
    cars = function() return {spawn(at(rowStart - 60))} end,
    go = function() fling(cars[1], SPEED2) end,
    cam = function() return rowStart + ROW * GAP * .5 end},
  {name = 'crawl', frames = 600, plant = function()
      local s = len * .5
      plantAt(PLANTER, at(s + 4, -5.25))
      plantAt(BIN, at(s + 4, -1.75))
      plantAt(PLANTER, at(s + 4, 5.25))
    end,
    cars = function()
      local s = len * .5
      -- three under script AI holding 3 km/h (into a planter, a bin, nothing: the control), one
      -- coasting at 3 km/h into a planter from just short of it
      return {spawn(at(s - 4, -5.25)), spawn(at(s - 4, -1.75)), spawn(at(s - 4, 1.75)), spawn(at(s + 1.1, 5.25))}
    end,
    go = function()
      local s = len * .5
      aiPath(cars[1], s - 3.5, s + 16, CRAWL, -5.25)
      aiPath(cars[2], s - 3.5, s + 16, CRAWL, -1.75)
      aiPath(cars[3], s - 3.5, s + 16, CRAWL, 1.75)
      fling(cars[4], CRAWL)
    end,
    cam = function() return len * .5 + 4 end},
  {name = 'inside', frames = 150, plant = function()
      local s = len * .5
      plantAt(BIN, at(s - .2, .3))
      plantAt(BENCH, at(s - 1.8, -.2), yaw + math.pi / 2)
    end,
    cars = function() return {spawn(at(len * .5 - 1))} end,
    go = function() end,
    cam = function() return len * .5 end},
  {name = 'wall', frames = 300, skip = not wall, plant = function()
      plantAt(BIN, at(wall.s, wall.sg * (wall.d - 10)))
    end,
    cars = function() return {spawn(at(wall.s, wall.sg * (wall.d - 14.5)), side * wall.sg)} end,
    go = function() fling(cars[1], 15, side * wall.sg) end,
    cam = function() return wall.s end},
  {name = 'swarm', frames = 360, rowAt = rowStart + 14, plant = function()
      for i = 0, 17 do
        for j = 0, 4 do plantAt(BIN, at(rowStart + 20 + i * 1.1, (j - 2) * .9)) end
      end
    end,
    cars = function() return {spawn(at(rowStart - 40))} end,
    go = function() fling(cars[1], 30) end,
    cam = function() return rowStart + 30 end},
}

local function camera(s)
  local p = at(s)
  local cam = p + side * 14 + up * 6 - dir * 6
  pcall(function() commands.setFreeCamera() end)
  core_camera.setPosition(0, cam)
  core_camera.setRotation(0, quatFromDir((p - cam):normalized(), up))
end

local function nextRun()
  run = run + 1
  cur = RUNS[run]
  while cur and cur.skip do
    R[cur.name] = 'skipped'
    run = run + 1
    cur = RUNS[run]
  end
  if not cur then return false end
  tile, props = {knockProbe = run}, {}
  cur.plant()
  stats = {planted = #props, knocked0 = K.stats.knocked, missed0 = K.stats.missed, contacts0 = K.stats.contacts or 0,
    walls0 = K.stats.walls or 0, rays0 = K.stats.rays or 0, flyMax = 0, stepMs = 0, stepMax = 0, stepMax40 = 0,
    steps = 0, frames = {}, upright = 1, speedMax = {}, start = {}, travel = {},
    part = {arm = 0, ray = 0, ground = 0}}
  -- a spawn can fail (returns nil or a non-vehicle): keep the cars that came
  local got = cur.cars()
  cars = {}
  for k = 1, 8 do
    local c = got[k]
    if type(c) ~= 'nil' and type(c.getID) == 'function' then cars[#cars + 1] = c
    elseif k <= 4 and got[k] == nil and k <= #got then stats.spawnFailed = (stats.spawnFailed or 0) + 1 end
  end
  stats.cars = #cars
  R.at = cur.name
  camera(cur.cam())
  phase, frame = 'settle', 0
  return true
end

local function finish()
  stats.speedAfter = {}
  for k, car in ipairs(cars) do
    stats.speedAfter[k] = r2(speedOf(car:getID()))
    stats.speedMax[k] = r2(stats.speedMax[k])
    pcall(function() stats.damage = (stats.damage or 0) + (map.objects[car:getID()].damage or 0) end)
    stats.nonPlayer = (stats.nonPlayer ~= false) and car:getID() ~= playerId
  end
  stats.knocked = K.stats.knocked - stats.knocked0
  stats.missed = K.stats.missed - stats.missed0
  stats.contacts = (K.stats.contacts or 0) - stats.contacts0
  stats.walls = (K.stats.walls or 0) - stats.walls0
  stats.rays = (K.stats.rays or 0) - stats.rays0
  stats.stepMean = stats.steps > 0 and stats.stepMs / stats.steps or 0
  stats.upright = r2(stats.upright)
  stats.start = nil
  for key, v in pairs(stats.part) do stats.part[key] = math.floor(v * 1000 + .5) / 1000 end
  -- how far each prop went from where it stood
  stats.moved = {}
  for _, p in ipairs(props) do
    local s = K.SLOT[p.id]
    if s then
      stats.moved[#stats.moved + 1] = p.shape .. ' ' .. math.floor(math.sqrt((K.PX[s] - p.x) ^ 2 + (K.PY[s] - p.y) ^ 2) * 100) / 100
    else
      stats.moved[#stats.moved + 1] = p.shape .. ' standing'
    end
  end
  if cur.name == 'inside' then
    -- each prop's place in the car's box frame (|along| < 2.3 and |across| < 0.95 would be inside)
    local o = be:getObjectByID(cars[1]:getID())
    local c, f = o:getPosition(), o:getDirectionVector()
    -- the box's centre and half sizes as knock sees them (pedhit.vehicleBox)
    local box = W.pedHit.vehicleBox({}, o)
    c = vec3(c.x + f.x * box[3], c.y + f.y * box[3], c.z)
    stats.box = string.format('half %.2f x %.2f', box[1], box[2])
    stats.inBox = {}
    for _, p in ipairs(props) do
      local s = K.SLOT[p.id]
      if s then
        local dx, dy = K.PX[s] - c.x, K.PY[s] - c.y
        stats.inBox[#stats.inBox + 1] = string.format('%s along %.2f across %.2f', p.shape, dx * f.x + dy * f.y, -dx * f.y + dy * f.x)
      end
    end
  end
  if cur.name == 'wall' and wall then
    -- the bin's distance across the road from the edge vs the wall's
    local p = props[1]
    local s = p and K.SLOT[p.id]
    if s then
      local o = at(wall.s)
      stats.binAcross = r2(((K.PX[s] - o.x) * side.x + (K.PY[s] - o.y) * side.y) * wall.sg)
      stats.wallAcross = r2(wall.d)
    end
  end
  table.sort(stats.frames)
  local fr = stats.frames
  stats.frameP50, stats.frameMax = fr[math.ceil(#fr * .5)], fr[#fr]
  stats.frames = nil
  R[cur.name] = stats
end

local function body(dt, ms)
  frame = frame + 1
  if phase == 'settle' and frame > 90 then
    cur.go()
    phase, frame = 'drive', 0
  elseif phase == 'drive' or phase == 'after' then
    local st = K.stats
    stats.frames[#stats.frames + 1] = math.floor(ms * 10) / 10
    if ms > 45 then
      stats.slow = stats.slow or {}
      if #stats.slow < 8 then
        stats.slow[#stats.slow + 1] = string.format('%.0f ms at frame %d, knocked %d, flying %d', ms, #stats.frames,
          st.knocked - stats.knocked0, st.flying or 0)
      end
    end
    stats.flyMax = math.max(stats.flyMax, st.flying or 0)
    stats.stepMs, stats.steps = stats.stepMs + (st.ms or 0), stats.steps + 1
    stats.stepMax = math.max(stats.stepMax, st.ms or 0)
    if (st.flying or 0) >= 40 then stats.stepMax40 = math.max(stats.stepMax40, st.ms or 0) end
    for key, v in pairs(K.part or {}) do stats.part[key] = math.max(stats.part[key] or 0, v) end
    for k, car in ipairs(cars) do
      local o = be:getObjectByID(car:getID())
      if o then
        local u = o:getDirectionVectorUp()
        local p = o:getPosition()
        local along = (p.x - a.x) * dir.x + (p.y - a.y) * dir.y
        stats.start[k] = stats.start[k] or along
        stats.travel[k] = r2(along - stats.start[k])
        stats.upright = math.min(stats.upright, u.z)
        stats.speedMax[k] = math.max(stats.speedMax[k] or 0, speedOf(car:getID()))
        stats.speedBefore = stats.speedBefore or {}
        if not stats.speedBefore[k] and phase == 'drive' then
          local p = o:getPosition()
          local along = (p.x - a.x) * dir.x + (p.y - a.y) * dir.y
          if cur.rowAt and along > cur.rowAt or not cur.rowAt and frame == 3 then
            stats.speedBefore[k] = r2(speedOf(car:getID()))
          end
        end
      end
    end
    -- the wall run's driver brakes at the hit (the car is not what it is about)
    if cur.name == 'wall' and phase == 'drive' and (st.contacts or 0) > stats.contacts0 and not stats.braked then
      stats.braked = frame
      cars[1]:applyClusterVelocityScaleAdd(cars[1]:getRefNodeId(), 0, 0, 0, 0)
    end
    if phase == 'drive' and frame == 40 then pcall(createScreenshot2, {filename = 'e2r_probe/knock_' .. cur.name .. 'a', writeJPG = false, superSampling = 1}) end
    if phase == 'drive' and frame >= cur.frames then
      phase, frame = 'after', 0
      for _, car in ipairs(cars) do car:queueLuaCommand('ai.stopFollowing() ai.setMode("stop")') end
    elseif phase == 'after' and frame == 90 then
      pcall(createScreenshot2, {filename = 'e2r_probe/knock_' .. cur.name, writeJPG = false, superSampling = 1})
      finish()
      for _, car in ipairs(cars) do car:delete() end
      knock.unregisterTile(K, tile, W.knockState().api)
      if not nextRun() then phase, frame = 'lamp', 0 end
    end
  elseif phase == 'lamp' then
    -- a lamp1 pole knocked where it stands: its light (the pool, placed at the nearest lamps)
    -- must leave it. The touch is a still box on the pole given to knock.step with dt 0.
    if frame == 1 then
      local lights = {}
      for k = 1, 64 do
        local l = scenetree.findObject('e2r_light_' .. k)
        if l then lights[#lights + 1] = l end
      end
      R.lamp = {lights = #lights}
      if #lights == 0 then R.lamp.note = 'no light pool (day or lights off)'; R.status = W.knockStatus(); return R end
      local bestId, bestD
      for id, shape in pairs(K.SHAPE) do
        if K.STATE[id] == knock.STAND and shape:lower():find('lamp1.dae', 1, true) then
          for _, l in ipairs(lights) do
            local p = l:getPosition()
            local d = (p.x - K.X[id]) ^ 2 + (p.y - K.Y[id]) ^ 2
            if not bestD or d < bestD then bestId, bestD = id, d end
          end
        end
      end
      if not bestId or bestD > 1 then R.lamp.note = 'no lit knockable lamp1 near'; R.status = W.knockStatus(); return R end
      R.lamp.id = bestId
      R.lamp.lightBefore = r2(math.sqrt(bestD))
      local fake = {id = -1, x = K.X[bestId], y = K.Y[bestId], vx = 0, vy = 0, fx = 1, fy = 0, hl = 1, hw = 1, mass = 1500}
      for k = 1, knock.STILL_EVERY do knock.step(K, {fake}, 1, K.now or 0, 0, W.knockState().api) end
      R.lamp.state = K.STATE[bestId]
    elseif frame == 30 then
      local id, nearest = R.lamp.id, nil
      for k = 1, 64 do
        local l = scenetree.findObject('e2r_light_' .. k)
        if l then
          local p = l:getPosition()
          local d = math.sqrt((p.x - K.X[id]) ^ 2 + (p.y - K.Y[id]) ^ 2)
          if not nearest or d < nearest then nearest = d end
        end
      end
      R.lamp.lightAfter = r2(nearest)
      R.status = W.knockStatus()
      return R
    end
  end
end

nextRun()
-- an error in one run still reports the runs before it
return P.task(function(dt, ms)
  local ok, res = pcall(body, dt, ms)
  if ok then return res end
  R.error = tostring(res)
  pcall(function() R.status = W.knockStatus() end)
  return R
end)
