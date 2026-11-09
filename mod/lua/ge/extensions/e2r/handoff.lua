-- Real cars round the player in place of flow cars (flow.lua). A flow car has no collision; when it
-- is about to come near the player's car it becomes one of SIZE real cars (the game's
-- simple_traffic, ~1.5 ms of the frame each, traffic-07) driven by the game's AI, and once it is
-- past LEAVE_R and going away it goes back into the flow on the lane it is on, at its speed. The
-- real cars are a pool spawned once (a spawn is a ~0.1-0.6 s frame), parked inactive (setActive 0)
-- until a flow car needs one. The pool holds SPARE more cars than may drive at once (an inactive
-- car has no physics): a flow car then mostly finds a free car of its own body.
--   - The pool holds the flow's bodies in the flow's shares (sedan, hatch, crossover, van: each
--     pool car is a stock simple_traffic config of that shape, M.bodyOf). A flow car takes a free
--     car of its own body; another body only when it is about to reach the player (URGENT_R).
--   - The real car is repainted to the flow car's paint as it takes its place, so the swap keeps
--     the colour whatever car of the pool it is.
--   - Which flow cars first: by how near they come to the player's car in the next LOOK s
--     (both moving), not by where they are now. A car that drives away is left in the flow; a car
--     about to reach the player takes a real car that is far and going away, when none is free.
--   - A flow car right by the player's car (PLAYER_R) or by another real car (CLEAR_R) is not
--     swapped: the teleport would put two cars in one place.
--   - The game's AI does not see the flow's traffic lights: a real car on a lit approach is held
--     (api.hold, a speed limit of 0) while its light is red, as the flow car in its place would be.
-- The game calls go through `api` (M.gameApi below), so earthng/test_flow.py runs this in lupa.
local M = {}

M.SIZE, M.ENTER_R, M.LEAVE_R = 8, 90, 130
M.SPARE = .5              -- the pool's inactive spares, a share of the cars that may drive at once
local CLEAR_R = 12        -- m between real cars a swap needs: the teleport would put two in one place
local PLAYER_R = 8        -- m from the player's car: a car's length and a margin (12 left a flow car
                          -- queued right ahead of a stopped player a ghost one could drive through)
local EVERY = .25         -- s between hand-off checks
local SPAWN_EVERY = .5    -- s between two pool spawns
local SWAPS = 2           -- flow cars made real a check: a woken car's first physics frames cost (flow-10)
local LOOK = 4            -- s ahead the closest approach to the player's car is judged over
local REACH = 2.5         -- s of the player's speed added to ENTER_R where flow cars are looked at
local MAX_R = 170         -- m: the farthest a flow car is looked at, and a real car kept
local URGENT_R = 45       -- m: a flow car coming this near takes any free body, or a far real car
local AWAY_R = 35         -- m: a flow car going away beyond this stays in the flow
local SPARE_R = 70        -- m: a real car coming no nearer than this may give its place to an urgent one

-- the stock simple_traffic configs by the flow's bodies (flow.BODIES: sedan, hatch, suv, van),
-- from their names; sizes from the jbeam bodies (L x H): covet 3.7 x 1.2, vivace 4.1 x 1.3,
-- bastion 4.7 x 1.3, roamer 4.7 x 1.4, lansdale 4.8 x 1.5, van 5.2 x 1.8
local BODY_OF = {
  ardente = 2, covet = 2, vivace = 2, bx = 2,
  bastion = 1, etk800 = 1, etkc = 1, etki = 1, fullsize = 1, legran = 1, midsize = 1, pessima = 1,
  sunburst2 = 1, wendover = 1,
  roamer = 3, tograc = 3, lansdale = 3, pickup = 3,
  van = 4,
}
-- a body's stand-ins when the pool has none of it free, nearest shape first
local NEAR_BODY = {{1, 2, 3, 4}, {2, 1, 3, 4}, {3, 4, 1, 2}, {4, 3, 1, 2}}
-- stock configs for a body the game's group did not give (a region filter, few configs)
M.STOCK = {{'bastion_base', 'sunburst2_eu_sedan_base', 'etki_eu_facelift', 'legran_sedan_pre_regulier'},
  {'covet_base', 'vivace_base', 'bx_base_hatch'}, {'roamer_base', 'etk800_eu_xc', 'tograc_base'},
  {'van_passenger', 'van_delivery'}}

-- the flow body (1..4) of a simple_traffic config name or path; nil for one the flow has no shape
-- for (the small robot van)
function M.bodyOf(config)
  if type(config) ~= 'string' then return end
  local name = config:match('([%w_%-]+)%.pc$') or config:match('([%w_%-]+)$') or config
  name = name:lower()
  if name:find('_xc') then return 3 end            -- the ETK 800 on stilts
  if name:find('^bx_.*hatch') then return 2 end
  if name:find('^bx_') then return 2 end           -- the short coupe: nearer a hatch than a sedan
  local model = name:match('^([%a%d]+)')
  return model and BODY_OF[model]
end

-- the game's vehicle group as entries by body: {[body] = {entry, ...}}
function M.byBody(group)
  local out = {{}, {}, {}, {}}
  for _, entry in ipairs(group or {}) do
    local b = M.bodyOf(entry.config)
    if b then table.insert(out[b], entry) end
  end
  return out
end

function M.new(opts)
  opts = opts or {}
  return {pool = {}, size = opts.size or M.SIZE, spare = opts.spare or M.SPARE, bodies = opts.bodies or {1},
    at = -1, spawnAt = -1, stats = {promoted = 0, demoted = 0, dropped = 0, lost = 0, mismatched = 0, preempted = 0}}
end

function M.activeCount(H)
  local n = 0
  for _, e in ipairs(H.pool) do if e.active then n = n + 1 end end
  return n
end

-- how many cars the pool holds: H.size may drive at once, the spares wait
function M.target(H)
  return H.size > 0 and H.size + math.ceil(H.size * H.spare) or 0
end

-- the body the next pool car should have: the one furthest below its share of the pool
function M.nextBody(H)
  local have, total = {}, 0
  for _, w in ipairs(H.bodies) do total = total + w end
  for _, e in ipairs(H.pool) do have[e.body] = (have[e.body] or 0) + 1 end
  local best, gap = 1, -math.huge
  local size = math.max(M.target(H), #H.pool + 1)
  for b, w in ipairs(H.bodies) do
    local g = size * w / math.max(total, 1e-9) - (have[b] or 0)
    if g > gap + 1e-9 then best, gap = b, g end
  end
  return best
end

local function addCar(H, api, fx, fy)
  local body = M.nextBody(H)
  local id = api.spawn(body, fx, fy)
  if id then H.pool[#H.pool + 1] = {id = id, body = body, ready = true} end
  return id
end

-- a free pool car for a flow car of body: one of that body, else the nearest shape; and whether
-- the body is its own
local function free(H, body)
  if M.activeCount(H) >= H.size then return end
  local order = NEAR_BODY[body or 1] or NEAR_BODY[1]
  local best, rank
  for _, e in ipairs(H.pool) do
    if not e.active and e.ready then
      local r = 9
      for k, b in ipairs(order) do if b == e.body then r = k; break end end
      if not rank or r < rank then best, rank = e, r end
      if r == 1 then break end
    end
  end
  return best, rank == 1
end

-- the whole pool at once (when the flow is switched on: one wait there instead of hitches while
-- driving; a spawn is 0.1-0.6 s of the frame)
function M.prewarm(H, api, fx, fy)
  while #H.pool < M.target(H) do
    if not addCar(H, api, fx, fy) then break end
  end
end

-- How near a thing at (x, y) moving (vx, vy) comes to the player's car at (fx, fy) moving
-- (pvx, pvy) within LOOK s, and whether the two are drawing apart now.
local function approach(x, y, vx, vy, fx, fy, pvx, pvy)
  local px, py = x - fx, y - fy
  local wx, wy = vx - pvx, vy - pvy
  local dot, w2 = px * wx + py * wy, wx * wx + wy * wy
  local t = w2 > 1e-6 and math.max(0, math.min(LOOK, -dot / w2)) or 0
  local cx, cy = px + wx * t, py + wy * t
  return math.sqrt(cx * cx + cy * cy), dot > 0
end
M.approach = approach

-- a real car goes back into the flow, or out of the game when no lane takes it; keep: then it stays
-- real instead (returns false), as a car vanishing in plain sight is worse than one more real car
local function demote(H, flow, F, api, e, x, y, vx, vy, hx, hy, keep)
  local car = flow.put(F, x, y, hx, hy, math.sqrt(vx * vx + vy * vy), e.paint, e.flowBody or e.body, keep)
  if not car and keep then
    -- counted once a car: it is tried again every check
    if not e.kept then H.stats.kept = (H.stats.kept or 0) + 1; e.kept = true end
    return false
  end
  e.kept = nil
  if car then H.stats.demoted = H.stats.demoted + 1 else H.stats.dropped = H.stats.dropped + 1 end
  api.deactivate(e.id)
  e.active, e.held = false, false
  return true
end

-- the far real car going away (a.spare) that gives its place to an urgent flow car: of body when
-- given, the farthest first; it must find a lane to go back to
local function preempt(H, flow, F, api, active, fx, fy, body)
  local list = {}
  for _, a in ipairs(active) do
    if a.spare and a.e.active and (not body or a.e.body == body) then list[#list + 1] = a end
  end
  table.sort(list, function(a, b) return (a.x - fx) ^ 2 + (a.y - fy) ^ 2 > (b.x - fx) ^ 2 + (b.y - fy) ^ 2 end)
  for _, a in ipairs(list) do
    a.spare = false
    if demote(H, flow, F, api, a.e, a.x, a.y, a.vx, a.vy, a.hx, a.hy, true) then
      H.stats.preempted = H.stats.preempted + 1
      return a.e
    end
  end
end

-- one step at time now; (fx, fy) the player's car, (pvx, pvy) its velocity; flow the flow module,
-- F its state
function M.step(H, flow, F, fx, fy, now, api, pvx, pvy)
  pvx, pvy = pvx or 0, pvy or 0
  -- a smaller pool (the widget's setting): parked cars go first, a driving one back into the flow
  while #H.pool > M.target(H) do
    local k = #H.pool
    for i = #H.pool, 1, -1 do if not H.pool[i].active then k = i; break end end
    local e = table.remove(H.pool, k)
    if e.active and api.alive(e.id) then
      local x, y, vx, vy, hx, hy = api.pose(e.id)
      demote(H, flow, F, api, e, x, y, vx, vy, hx, hy)
    elseif e.active then
      flow.forget(F)
    end
    api.delete(e.id)
  end
  -- fewer may drive at once: the farthest go back into the flow
  while M.activeCount(H) > H.size do
    local worst, wd
    for _, e in ipairs(H.pool) do
      if e.active and api.alive(e.id) then
        local x, y = api.pose(e.id)
        local d = (x - fx) ^ 2 + (y - fy) ^ 2
        if not worst or d > wd then worst, wd = e, d end
      end
    end
    if not worst then break end
    local x, y, vx, vy, hx, hy = api.pose(worst.id)
    demote(H, flow, F, api, worst, x, y, vx, vy, hx, hy)
  end
  -- the pool fills one car at a time
  if #H.pool < M.target(H) and now >= H.spawnAt then
    H.spawnAt = now + SPAWN_EVERY
    addCar(H, api, fx, fy)
  end
  if now - H.at < EVERY then return end
  H.at = now
  -- real cars that drove away go back into the flow; one still coming back is kept
  local active = {}
  for k = #H.pool, 1, -1 do
    local e = H.pool[k]
    if not api.alive(e.id) then
      table.remove(H.pool, k)
      if e.active then flow.forget(F); H.stats.lost = H.stats.lost + 1 end
    elseif e.active then
      local x, y, vx, vy, hx, hy = api.pose(e.id)
      local d2 = (x - fx) ^ 2 + (y - fy) ^ 2
      local soon, away = approach(x, y, vx, vy, fx, fy, pvx, pvy)
      local gone = d2 > M.LEAVE_R * M.LEAVE_R and (away or d2 > MAX_R * MAX_R) and
        demote(H, flow, F, api, e, x, y, vx, vy, hx, hy, d2 < MAX_R * MAX_R)
      if not gone then
        active[#active + 1] = {x = x, y = y, vx = vx, vy = vy, hx = hx, hy = hy, e = e,
          spare = away and soon > SPARE_R}
        local v = math.sqrt(vx * vx + vy * vy)
        local hold = flow.holdAt and flow.holdAt(F, x, y, hx, hy, v) or false
        if hold ~= (e.held or false) then
          api.hold(e.id, hold)
          e.held = hold
          H.stats.held = (H.stats.held or 0) + (hold and 1 or 0)
        end
      end
    end
  end
  if #H.pool == 0 then return end
  -- the flow cars that will come near, the soonest first
  local speed = math.sqrt(pvx * pvx + pvy * pvy)
  local reach = math.min(MAX_R, M.ENTER_R + speed * REACH)
  local list = {}
  for _, c in ipairs(flow.near(F, fx, fy, reach)) do
    local v = c.car.v or 0
    c.vx, c.vy = math.cos(c.yaw) * v, math.sin(c.yaw) * v
    local soon, away = approach(c.x, c.y, c.vx, c.vy, fx, fy, pvx, pvy)
    c.soon = soon
    if soon < M.ENTER_R and not (away and c.d > AWAY_R) then list[#list + 1] = c end
  end
  table.sort(list, function(a, b) if a.soon ~= b.soon then return a.soon < b.soon end return a.d < b.d end)
  local swaps = 0
  for _, c in ipairs(list) do
    if swaps >= SWAPS then break end
    local clear = c.d > PLAYER_R
    for _, a in ipairs(active) do
      if clear and (a.x - c.x) ^ 2 + (a.y - c.y) ^ 2 < CLEAR_R * CLEAR_R then clear = false end
    end
    if clear then
      local urgent = c.soon < URGENT_R
      local e, own = free(H, c.car.body)
      if urgent and not own then
        -- no free car of its body: a far real car of its body going away gives its place, else a
        -- free car of another body, else any far real car going away
        local mine = preempt(H, flow, F, api, active, fx, fy, c.car.body)
        if mine then e, own = mine, true
        elseif not e and preempt(H, flow, F, api, active, fx, fy) then
          -- a place to drive is free now: a spare of its body takes it, if the pool has one
          e, own = free(H, c.car.body)
        end
      end
      -- another body only for a car about to reach the player: a wait for its own is better
      -- than a sedan turning into a van in plain sight
      if e and (own or urgent) then
        local v = c.car.v
        e.flowBody, e.paint = c.car.body, c.car.paint   -- the flow car it comes back as
        flow.take(F, c.car)
        api.activate(e.id, c.x, c.y, c.z, c.yaw, v, c.car.paint)
        e.active, e.held = true, false
        if flow.holdAt and flow.holdAt(F, c.x, c.y, math.cos(c.yaw), math.sin(c.yaw), v) then
          api.hold(e.id, true)
          e.held = true
        end
        active[#active + 1] = {x = c.x, y = c.y, vx = c.vx, vy = c.vy, hx = math.cos(c.yaw), hy = math.sin(c.yaw), e = e}
        H.stats.promoted = H.stats.promoted + 1
        if not own then H.stats.mismatched = H.stats.mismatched + 1 end
        swaps = swaps + 1
      end
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

function M.clear(H, api)
  for _, e in ipairs(H.pool) do api.delete(e.id) end
  H.pool = {}
end

-- --- the game side ------------------------------------------------------------------------------
-- rgb: list of {r, g, b} by paint (flow.PAINT_RGB, sRGB); group(body): a vehicle group entry
-- {model, config} of the game's simple cars of that flow body
function M.gameApi(rgb, group)
  local api = {}
  local function paintOf(c)
    return createVehiclePaint({x = c[1], y = c[2], z = c[3], w = 1}, {.4, .35, 1, .05})
  end
  function api.spawn(body, fx, fy)
    local entry = group and group(body) or nil
    local model = entry and entry.model or 'simple_traffic'
    local ok, veh = pcall(core_vehicles.spawnNewVehicle, model, {
      config = entry and entry.config, pos = vec3(fx, fy, -2000), rot = quat(0, 0, 0, 1),
      paint = paintOf(rgb[1] or {.5, .5, .5}),
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
  -- the flow car's paint on the real car (as core_vehicle_manager.liveUpdateVehicleColors does;
  -- both 0.39 and 0.40 have these)
  function api.repaint(obj, paint)
    local c = rgb[paint]
    if not c then return end
    pcall(function()
      obj.color = ColorF(c[1], c[2], c[3], 1):asLinear4F()
      obj:setMetallicPaintData({paintOf(c)})
    end)
  end
  function api.activate(id, x, y, z, yaw, v, paint)
    local obj = getObjectByID(id)
    obj:setActive(1)
    if paint then api.repaint(obj, paint) end
    local rot = quatFromDir(vec3(math.cos(yaw), math.sin(yaw), 0), vec3(0, 0, 1))
    -- the bounding box's centre over the lane; safeTeleport puts it on the ground
    spawn.safeTeleport(obj, vec3(x, y, z + .8), rot, nil, nil, false, true)
    obj:queueLuaCommand('ai.setMode("traffic")')
    obj:queueLuaCommand('ai.setAggression(0.3)')
    obj:queueLuaCommand('ai.setSpeedMode("legal")')
    obj:queueLuaCommand('ai.setSpeed()')
    obj:queueLuaCommand('ai.driveInLane("on")')
    obj:queueLuaCommand('ai.reset()')
    if v > 1 then
      obj:queueLuaCommand(string.format('thrusters.applyVelocity(obj:getDirectionVector() * %.2f, 0.25)', v))
    end
  end
  -- stand for a red light (on) or drive on: a speed limit of 0 brakes on the AI's own plan
  function api.hold(id, on)
    local obj = getObjectByID(id)
    if not obj then return end
    if on then
      obj:queueLuaCommand('ai.setSpeedMode("limit")')
      obj:queueLuaCommand('ai.setSpeed(0)')
    else
      obj:queueLuaCommand('ai.setSpeedMode("legal")')
      obj:queueLuaCommand('ai.setSpeed()')
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
