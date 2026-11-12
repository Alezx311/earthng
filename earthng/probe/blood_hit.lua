-- Blood stains of a pedestrian hit (world.lua BLOOD) placed as pedhit places them, for
--   test_world.py --manual --probe --walkers 20 ... then
--   python earthng/probe.py --user <out>/user -f earthng/probe/blood_hit.lua --timeout 120
-- The player's car is put 3.5 m short of the nearest wall within 60 m (a building before a tree),
-- facing it; three hits across its front (ground, sprays, the wall, the car) and a pool 5 m to its
-- side. Then: stills (e2r_probe/blood_<view>.png), the car rolled back about 3 m (its stains go with it,
-- the ground ones stay) and reset (its stains go). Reports the stains by kind, how high each ground
-- stain lies over the surface below it, the wall rays, and how far the car and its stains moved.
local W = extensions.e2r_world
if not W or not W.bloodSplat then return {error = 'no world.bloodSplat'} end
local veh = be:getPlayerVehicle(0)
if not veh then return {error = 'no player vehicle'} end
local up = vec3(0, 0, 1)
local R = {rays = {}}
local id = veh:getID()
local box = W.pedHit.vehicleBox({}, veh)
local hl, hw, off = box[1], box[2], box[3]

local function ground(x, y, z)
  local h = be:getSurfaceHeightBelow(vec3(x, y, z + 2))
  return (h and h > -1e6) and h or z
end

-- the nearest wall: level rays at 1.1 m, 60 m out, against static collision (castRayStatic); a wall
-- answers three neighbouring rays (2.5 degrees apart) within a metre, a post or a tree does not
local p0 = veh:getPosition()
local best
local s0 = vec3(p0.x, p0.y, ground(p0.x, p0.y, p0.z) + 1.1)
local dists = {}
for k = 0, 143 do
  local a = k / 144 * 2 * math.pi
  local ok, dist = pcall(castRayStatic, s0, vec3(math.cos(a), math.sin(a), 0), 60)
  dists[k] = ok and type(dist) == 'number' and dist < 60 and dist or nil
end
for k = 0, 143 do
  local d0, dl, dr = dists[k], dists[(k + 143) % 144], dists[(k + 1) % 144]
  if d0 and dl and dr and d0 > 6 and math.abs(dl - d0) < 1 and math.abs(dr - d0) < 1 and (not best or d0 < best.dist) then
    local a = k / 144 * 2 * math.pi
    local d = vec3(math.cos(a), math.sin(a), 0)
    best = {dist = d0, d = d, pt = s0 + d * d0}
  end
end
if best then
  R.wall = {dist = best.dist}
  -- face the wall, the front 3.5 m from it
  local f = best.d
  local c = best.pt - f * (hl + 3.5)
  local refAt = c - f * off
  -- a vehicle's forward is its -y (pedhit.gameApi place)
  local q = quatFromDir(-f, up)
  veh:setPositionRotation(refAt.x, refAt.y, ground(refAt.x, refAt.y, p0.z) + .6, q.x, q.y, q.z, q.w)
end
R.wallFound = best and true or false

local stage, frame, t0 = 'settle', 0, 0
local carBefore, hits = nil, nil

local function hitter()
  local p, d = veh:getPosition(), veh:getDirectionVector()
  local l = math.sqrt(d.x * d.x + d.y * d.y)
  local fx, fy = d.x / l, d.y / l
  return {id = id, x = p.x + fx * off, y = p.y + fy * off, z = p.z, fx = fx, fy = fy, hl = hl, hw = hw,
    vx = fx * 8, vy = fy * 8}
end

local function camera(eye, at)
  pcall(function() commands.setFreeCamera() end)
  core_camera.setPosition(0, eye)
  core_camera.setRotation(0, quatFromDir((at - eye):normalized(), up))
end

local function shot(name)
  pcall(createScreenshot2, {filename = 'e2r_probe/blood_' .. name, writeJPG = false, superSampling = 1})
end

local function carStains()
  local st, out = W.bloodState(), {}
  for _, s in ipairs(st.list) do
    if s.kind == 'car' then out[#out + 1] = vec3(s.x, s.y, s.z) end
  end
  return out
end

local views
return P.task(function(dt)
  frame = frame + 1
  local h = hitter()
  local front = vec3(h.x + h.fx * (hl + .3), h.y + h.fy * (hl + .3), 0)
  front.z = ground(front.x, front.y, h.z)
  if stage == 'settle' and frame > 90 then
    veh:queueLuaCommand("input.event('parkingbrake', 1, 2)")
    hits = {}
    -- the wall straight ahead of the front as the hits will see it
    local okR, dR = pcall(castRayStatic, vec3(front.x, front.y, front.z + 1.1), vec3(h.fx, h.fy, 0), 4)
    R.frontRay = okR and dR or tostring(dR)
    for k, across in ipairs({-.55, 0, .55}) do
      local x, y = front.x - h.fy * across, front.y + h.fx * across
      hits[k] = W.bloodSplat(x, y, front.z, h)
    end
    local side = vec3(-h.fy, h.fx, 0)
    local pool = front - vec3(h.fx, h.fy, 0) * 2 + side * 5
    hits.pool = W.bloodSplat(pool.x, pool.y, ground(pool.x, pool.y, h.z), nil, 'pool')
    stage, t0 = 'grow', frame
    local f, l = vec3(h.fx, h.fy, 0), side
    local c = vec3(h.x, h.y, h.z)
    views = {
      side = {c + l * 3.5 + f * (hl + 1.2) + up * 1.5, c + f * (hl - .3) + up * .4},
      above = {c + f * (hl + 1.5) + up * 7 + l * .5, c + f * (hl + 1.5)},
      hood = {c + f * (hl + 2.2) + up * 2 + l * 1.5, c + f * (hl - .8) + up * .8},
      wall = {c + f * (hl + 1.2) + l * 3.5 + up * 1.8, front + f * 3.2 + up * 1.1},
      pool = {pool + l * 3 + up * 3, pool},
    }
  elseif stage == 'grow' and frame - t0 > 9 * 60 then
    local st = W.bloodState()
    R.hits, R.n, R.kinds, R.err = hits, st.n, st.kinds, st.err
    R.lift = {}
    for _, s in ipairs(st.list) do
      if s.kind == 'ground' then
        R.lift[#R.lift + 1] = math.floor((s.z - ground(s.x, s.y, s.z)) * 1000) / 1000
      end
    end
    R.list = st.list
    carBefore = carStains()
    stage, t0 = 'views', frame
    R.shots = {}
  elseif stage == 'views' then
    local names = {'side', 'above', 'hood', 'wall', 'pool'}
    local k = math.floor((frame - t0) / 40) + 1
    local name = names[k]
    if not name then
      -- rolled back (a teleport is a reset to the game): the car's stains go with it
      R.carAt = veh:getPosition()
      veh:queueLuaCommand("input.event('parkingbrake', 0, 2)")
      veh:applyClusterVelocityScaleAdd(veh:getRefNodeId(), 0, -h.fx * 4, -h.fy * 4, 0)
      stage, t0 = 'moved', frame
    else
      local phase = (frame - t0) % 40
      if phase == 0 then camera(views[name][1], views[name][2]) end
      if phase == 30 then shot(name); R.shots[#R.shots + 1] = name end
    end
  elseif stage == 'moved' and frame - t0 == 50 then
    veh:queueLuaCommand("input.event('parkingbrake', 1, 2)")
  elseif stage == 'moved' and frame - t0 > 120 then
    R.carMoved = math.floor((veh:getPosition() - R.carAt):length() * 100) / 100
    R.carAt = nil
    local after = carStains()
    R.carTravel = {}
    for i, a in ipairs(after) do
      local b = carBefore[i]
      if b then R.carTravel[i] = math.floor((a - b):length() * 100) / 100 end
    end
    local st = W.bloodState()
    R.afterMove, R.walls, R.resets, R.err = st.kinds, st.walls, st.resets, st.err
    camera(views.side[1] - vec3(h.fx, h.fy, 0) * 3, views.side[2] - vec3(h.fx, h.fy, 0) * 3)
    stage, t0 = 'movedShot', frame
  elseif stage == 'movedShot' and frame - t0 == 30 then
    shot('moved')
    veh:queueLuaCommand('obj:requestReset(RESET_PHYSICS)')
    stage, t0 = 'reset', frame
  elseif stage == 'reset' and frame - t0 > 60 then
    local st = W.bloodState()
    R.afterReset, R.resetsAfter = st.kinds, st.resets
    return R
  end
end)
