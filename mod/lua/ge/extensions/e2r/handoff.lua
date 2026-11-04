-- Real cars round the player in place of flow cars (flow.lua). A flow car has no collision; within
-- ENTER_R of the player it becomes one of SIZE real cars (the game's simple_traffic, ~1.5 ms of the
-- frame each, traffic-07) driven by the game's AI, and past LEAVE_R it goes back into the flow on
-- the lane it is on, at its speed. The real cars are a pool spawned once (a spawn is a ~0.1 s
-- frame), parked inactive (setActive 0) until a flow car needs one.
--   - The pool has one car of each flow paint; a flow car takes one of its own paint if it is free.
--   - A flow car right by the player's car (CLEAR_R) or by another real car is not swapped: the
--     teleport would put two cars in one place.
--   - A real car the player has wrecked stays real until it is out of LEAVE_R.
-- The game calls go through `api` (H.gameApi below), so earthng/test_flow.py runs this in lupa.
local M = {}

M.SIZE, M.ENTER_R, M.LEAVE_R = 8, 90, 130
local CLEAR_R = 12        -- m from the player's car (and between real cars) a swap needs
local EVERY = .25         -- s between hand-off checks
local SPAWN_EVERY = .5    -- s between two pool spawns

function M.new(opts)
  opts = opts or {}
  return {pool = {}, size = opts.size or M.SIZE, paints = opts.paints or 1, at = -1, spawnAt = -1,
    stats = {promoted = 0, demoted = 0, dropped = 0, lost = 0}}
end

local function free(H, paint)
  local any
  for _, e in ipairs(H.pool) do
    if not e.active and e.ready then
      if e.paint == paint then return e end
      any = any or e
    end
  end
  return any
end

-- the whole pool at once (when the flow is switched on: one wait there instead of hitches while
-- driving; a spawn is 0.1-0.6 s of the frame)
function M.prewarm(H, api, fx, fy)
  while #H.pool < H.size do
    local paint = (#H.pool % H.paints) + 1
    local id = api.spawn(paint, fx, fy)
    if not id then break end
    H.pool[#H.pool + 1] = {id = id, paint = paint, ready = true}
  end
end

-- one step at time now; (fx, fy) the player's car; flow the flow module, F its state
function M.step(H, flow, F, fx, fy, now, api)
  -- the pool fills one car at a time
  if #H.pool < H.size and now >= H.spawnAt then
    H.spawnAt = now + SPAWN_EVERY
    local paint = (#H.pool % H.paints) + 1
    local id = api.spawn(paint, fx, fy)
    if id then H.pool[#H.pool + 1] = {id = id, paint = paint, ready = true} end
  end
  if now - H.at < EVERY then return end
  H.at = now
  -- real cars that drove away go back into the flow
  local active = {}
  for k = #H.pool, 1, -1 do
    local e = H.pool[k]
    if not api.alive(e.id) then
      table.remove(H.pool, k)
      if e.active then flow.forget(F); H.stats.lost = H.stats.lost + 1 end
    elseif e.active then
      local x, y, vx, vy, hx, hy = api.pose(e.id)
      if (x - fx) ^ 2 + (y - fy) ^ 2 > M.LEAVE_R * M.LEAVE_R then
        local car = flow.put(F, x, y, hx, hy, math.sqrt(vx * vx + vy * vy), e.paint)
        if car then H.stats.demoted = H.stats.demoted + 1 else H.stats.dropped = H.stats.dropped + 1 end
        api.deactivate(e.id)
        e.active = false
      else
        active[#active + 1] = {x, y}
      end
    end
  end
  -- flow cars that came near become real ones while the pool has cars
  if not free(H) then return end
  for _, c in ipairs(flow.near(F, fx, fy, M.ENTER_R)) do
    local e = free(H, c.car.paint)
    if not e then break end
    local clear = c.d > CLEAR_R
    for _, a in ipairs(active) do
      if clear and (a[1] - c.x) ^ 2 + (a[2] - c.y) ^ 2 < CLEAR_R * CLEAR_R then clear = false end
    end
    if clear then
      local v = c.car.v
      flow.take(F, c.car)
      api.activate(e.id, c.x, c.y, c.z, c.yaw, v)
      e.active = true
      active[#active + 1] = {c.x, c.y}
      H.stats.promoted = H.stats.promoted + 1
    end
  end
end

-- the real cars now driving: list of {x, y, vx, vy} (obstacles for the flow)
function M.obstacles(H, api, out)
  out = out or {}
  for _, e in ipairs(H.pool) do
    if e.active and api.alive(e.id) then
      local x, y, vx, vy = api.pose(e.id)
      out[#out + 1] = {x = x, y = y, vx = vx, vy = vy}
    end
  end
  return out
end

function M.activeCount(H)
  local n = 0
  for _, e in ipairs(H.pool) do if e.active then n = n + 1 end end
  return n
end

function M.clear(H, api)
  for _, e in ipairs(H.pool) do api.delete(e.id) end
  H.pool = {}
end

-- --- the game side ------------------------------------------------------------------------------
-- rgb: list of {r, g, b} by paint (flow.PAINT_RGB); group: a function returning a vehicle group
-- entry {model, config} of the game's simple cars
function M.gameApi(rgb, group)
  local api = {}
  function api.spawn(paint, fx, fy)
    local entry = group and group() or nil
    local model = entry and entry.model or 'simple_traffic'
    local c = rgb[paint] or {.5, .5, .5}
    local ok, veh = pcall(core_vehicles.spawnNewVehicle, model, {
      config = entry and entry.config, pos = vec3(fx, fy, -2000), rot = quat(0, 0, 0, 1),
      paint = createVehiclePaint({x = c[1], y = c[2], z = c[3], w = 1}, {.4, .35, 1, .05}),
      autoEnterVehicle = false, canSpawnAnotherVehicleCheck = false, vehicleName = 'e2r_flow_real'})
    if not ok or not veh then return end
    veh:setActive(0)
    veh.playerUsable = false
    return veh:getID()
  end
  function api.alive(id) return getObjectByID(id) ~= nil end
  function api.pose(id)
    local obj = getObjectByID(id)
    local p, v, d = obj:getPosition(), obj:getVelocity(), obj:getDirectionVector()
    local h = math.sqrt(d.x * d.x + d.y * d.y)
    return p.x, p.y, v.x, v.y, h > 0 and d.x / h or 1, h > 0 and d.y / h or 0
  end
  function api.activate(id, x, y, z, yaw, v)
    local obj = getObjectByID(id)
    obj:setActive(1)
    local rot = quatFromDir(vec3(math.cos(yaw), math.sin(yaw), 0), vec3(0, 0, 1))
    -- the bounding box's centre over the lane; safeTeleport puts it on the ground
    spawn.safeTeleport(obj, vec3(x, y, z + .8), rot, nil, nil, false, true)
    obj:queueLuaCommand('ai.setMode("traffic")')
    obj:queueLuaCommand('ai.setAggression(0.3)')
    obj:queueLuaCommand('ai.setSpeedMode("legal")')
    obj:queueLuaCommand('ai.driveInLane("on")')
    obj:queueLuaCommand('ai.reset()')
    if v > 1 then
      obj:queueLuaCommand(string.format('thrusters.applyVelocity(obj:getDirectionVector() * %.2f, 0.25)', v))
    end
  end
  function api.deactivate(id)
    local obj = getObjectByID(id)
    if obj then
      obj:queueLuaCommand('ai.setMode("disabled")')
      obj:setActive(0)
    end
  end
  function api.delete(id)
    local obj = getObjectByID(id)
    if obj then obj:delete() end
  end
  -- the slowest call of each kind, ms (result.flow.handoffMs), and every spawn's time
  api.ms, api.spawns = {}, {}
  for _, name in ipairs({'spawn', 'activate', 'deactivate'}) do
    local fn = api[name]
    api[name] = function(...)
      local t = hptimer()
      local a, b = fn(...)
      local ms = t:stop()
      api.ms[name] = math.max(api.ms[name] or 0, ms)
      if name == 'spawn' then api.spawns[#api.spawns + 1] = math.floor(ms * 10 + .5) / 10 end
      return a, b
    end
  end
  return api
end

return M
