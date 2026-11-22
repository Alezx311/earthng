-- The flow's cars and the walkers up close, for
--   test_world.py --manual --probe --flow 400 --flow-real 0 --walkers 1000 ... then
--   python earthng/probe.py --user <out>/user -f earthng/probe/traffic_look.lua --timeout 180
-- Stills in e2r_probe/look_<name>.png: flow cars of different bodies (the camera rides beside a
-- moving one), a standing queue, walkers of different figures in step, one at a place to stop and
-- the street from above. With --flow-real 0 no car near the player becomes a real one, so what is
-- framed is the model without physics. Reports what each still shows.
local W = extensions.e2r_world
if not W or not W.dbg then return {error = 'no world'} end
local S = W.dbg().S
if not (S.flow and S.walk and S.walk.W) then return {error = 'the flow and the walkers must be on'} end
local veh = be:getPlayerVehicle(0)
if not veh then return {error = 'no player vehicle'} end
local up = vec3(0, 0, 1)
local fs, F, Wk = W.flowSim, S.flow.F, S.walk.W
local here = veh:getPosition()

local function carPose(car)
  local x, y, z, yaw = fs.pose(F, car.link, car.s, car.lane)
  return vec3(x, y, z), vec3(math.cos(yaw), math.sin(yaw), 0)
end

-- flow cars by distance from the player, at least 12 m away
local cars = {}
for _, car in pairs(F.cars) do
  local p = carPose(car)
  local d = (p - here):length()
  if d > 12 and d < 400 then cars[#cars + 1] = {car = car, d = d} end
end
table.sort(cars, function(a, b) return a.d < b.d end)
-- The walkers are posed within 60 m of the focus, which is the player's car: the focus is put by
-- the nearest walker for their stills (the replay's pose, which world.lua's focus() reads first).
local nearest, nd
for slot = 1, Wk.target do
  local w = Wk.slots[slot]
  if w and not w.free and not w.taken and not w.inside then
    local d = math.sqrt((w.x - here.x) ^ 2 + (w.y - here.y) ^ 2)
    if not nd or d < nd then nearest, nd = w, d end
  end
end
local spot = nearest and vec3(nearest.x, nearest.y, nearest.z) or here
local function walkersAt(at)
  local list = {}
  for slot = 1, Wk.target do
    local w = Wk.slots[slot]
    if w and not w.free and not w.taken and not w.inside then
      local d = math.sqrt((w.x - at.x) ^ 2 + (w.y - at.y) ^ 2)
      if d < 45 then list[#list + 1] = {w = w, d = d} end
    end
  end
  table.sort(list, function(a, b) return a.d < b.d end)
  return list
end
local walkers = {}

local R = {cars = #cars, walkers = #walkers, shots = {}}
local plan = {}
-- one moving car of each model seen (body, variant), then a standing one
local seen, moving, standing = {}, 0, nil
for _, c in ipairs(cars) do
  local key = (c.car.body or 0) .. '_' .. (c.car.variant or 0)
  if c.car.v > 3 and not seen[key] and moving < 5 then
    seen[key] = true
    moving = moving + 1
    plan[#plan + 1] = {name = 'car' .. moving, car = c.car, side = moving % 2 == 0 and -1 or 1, ahead = moving % 3 == 0 and -6 or 6}
  elseif c.car.v < .3 and not standing then
    standing = c.car
  end
end
if standing then plan[#plan + 1] = {name = 'queue', car = standing, side = 1, ahead = 9, high = 3.2, wide = true} end
plan[#plan + 1] = {name = 'move'}
local function walkerPlan()
  walkers = walkersAt(spot)
  R.walkers = #walkers
  local figures, n, add = {}, 0, {}
  for _, q in ipairs(walkers) do
    local char = W.walkSim.charOf and W.walkSim.charOf(q.w)
    local key = char and char.name or ('look' .. (q.w.skin or 0))
    if not q.w.stay and not figures[key] and n < 5 then
      figures[key] = true
      n = n + 1
      add[#add + 1] = {name = 'walker' .. n, w = q.w, figure = key, front = n % 2 == 1}
    end
  end
  for _, q in ipairs(walkers) do
    if q.w.stay then add[#add + 1] = {name = q.w.sit and 'seated' or 'standing', w = q.w, front = true}; break end
  end
  add[#add + 1] = {name = 'crowd'}
  return add
end
plan[#plan + 1] = {name = 'street'}

local function camera(eye, at)
  pcall(function() commands.setFreeCamera() end)
  core_camera.setPosition(0, eye)
  core_camera.setRotation(0, quatFromDir((at - eye):normalized(), up))
end

local function frameUp(item)
  if item.car then
    if item.car.dead then return false end
    local p, f = carPose(item.car)
    local l = vec3(-f.y, f.x, 0)
    camera(p + f * item.ahead + l * (item.side * (item.wide and 7 or 4.6)) + up * (item.high or 1.5), p + up * .7 + (item.wide and f * -8 or vec3(0, 0, 0)))
    return true
  elseif item.w then
    local w = item.w
    if w.free or w.taken then return false end
    local z = (w.gz or w.z + .12)
    local p = vec3(w.x, w.y, z)
    local h = math.sqrt((w.hx or 1) ^ 2 + (w.hy or 0) ^ 2)
    local f = vec3((w.hx or 1) / h, (w.hy or 0) / h, 0)
    local l = vec3(-f.y, f.x, 0)
    local eye = item.front and (p + f * 3.2 + l * .8 + up * 1.45) or (p + l * 3.2 + f * .6 + up * 1.3)
    camera(eye, p + up * .95)
    return true
  end
  if item.name == 'crowd' then
    camera(spot + vec3(9, 7, 4.5), spot + up)
    return true
  end
  local d = veh:getDirectionVector()
  local f = vec3(d.x, d.y, 0):normalized()
  camera(here - f * 25 + up * 14, here + f * 45)
  return true
end

local at, frame, shotAt = 1, 0, nil
return P.task(function(dt)
  frame = frame + 1
  local item = plan[at]
  if not item then
    S.replayPose = nil
    pcall(function() extensions.ui_visibility.setCef(true) end)
    pcall(function() commands.setGameCamera() end)
    return R
  end
  if frame == 1 and at == 1 then pcall(function() extensions.ui_visibility.setCef(false) end) end
  if item.name == 'move' then
    -- the focus by the walkers; a second for their copies to become the posed ones
    S.replayPose = {p = vec3(spot.x, spot.y, spot.z), v = vec3(0, 0, 0)}
    if frame < 70 then return end
    for k, extra in ipairs(walkerPlan()) do table.insert(plan, at + k, extra) end
    at, frame, shotAt = at + 1, 0, nil
    return
  end
  local ok = frameUp(item)
  if not ok then at, frame, shotAt = at + 1, 0, nil; return end
  if frame == 25 and not shotAt then
    pcall(createScreenshot2, {filename = 'e2r_probe/look_' .. item.name, writeJPG = false, superSampling = 1})
    shotAt = frame
    local c = item.car
    R.shots[#R.shots + 1] = item.name .. (c and (': body ' .. tostring(c.body) .. ' model ' .. tostring(c.variant) .. ' paint ' .. tostring(c.paint)
      .. string.format(' %.1f m/s', c.v)) or (item.figure and (': ' .. item.figure) or ''))
  end
  if shotAt and frame > shotAt + 12 then at, frame, shotAt = at + 1, 0, nil end
end)
