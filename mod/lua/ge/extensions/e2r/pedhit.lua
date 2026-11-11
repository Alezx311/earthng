-- A physical body in a walker's place just before a vehicle hits it, as handoff.lua makes flow cars
-- real round the player. Walkers (walkers.lua) have no collision; the body (earthng/ped_body.py,
-- vehicle e2r_ped: a 41-node soft body whose joints are breakable beams) falls when a car strikes it.
--   - A pool of SIZE bodies is spawned once (a spawn is ~0.2 s of the frame, p15) and parked switched
--     off (setActive 0: no physics, no cost).
--   - Every step, for every vehicle with physics that moves (the player's car, the real cars of the
--     hand-off, the game's traffic), the walkers near its path (walkers.near: the walkers' grid, not
--     every walker: 1000 walkers x 20 vehicles) are swept against its box: a walker it
--     will touch within LEAD s gets a body from the pool, standing where the walker stands, walking
--     its way, in its colours; the walker is hidden. A body stands on a sloped street for ~1 s at most
--     (it is a statue, p15), so LEAD is short.
--   - Not hit within MISS_T s (the driver braked or swerved): the body goes back to the pool and the
--     walker walks on. Hit: it lies; out of FREE_R from the player (or after FREE_T s) it is reset
--     and parked, and the walker's slot fills again elsewhere.
-- The game calls go through `api` (M.gameApi), so earthng/test_walkers.py runs this in lupa.
local M = {}

M.SIZE = 6
M.LEAD = .3             -- s before the touch the body takes the walker's place
local MISS_T = .8       -- s a placed body waits for the hit (a statue on a slope tips over in ~1 s)
local FREE_R = 120      -- m from the player beyond which a lying body goes back to the pool
local FREE_T = 90       -- s a body lies at most
local RESET_T = .4      -- s for a reset (the vehicle's own Lua) before the body is parked again
local MIN_SPEED = .8    -- m/s: a vehicle slower than this hits nobody
local MAX_SPEED = 70    -- m/s: faster is a teleport (its velocity is the jump over one frame, p18)
local SETTLE_T = .1     -- s after the placing before the body's velocity means anything (it was at z -2000)
local HIT_DV = 1.2      -- m/s over its walk: a placed body moving this much faster was struck...
local TOUCH_R = 1.5     -- m: ...when a vehicle's box is this near (not a statue tipping over by itself)
local CLEAR_R = .9      -- m: no body is put where another one stands

function M.new(opts)
  opts = opts or {}
  return {size = opts.size or M.SIZE, pool = {}, stats = {placed = 0, hit = 0, missed = 0, noBody = 0, freed = 0}}
end

-- the whole pool at once, when the walkers are switched on (one wait instead of hitches while driving)
function M.prewarm(P, api, fx, fy)
  while #P.pool < P.size do
    local id = api.spawn(fx, fy)
    if not id then break end
    P.pool[#P.pool + 1] = {id = id, state = 'idle'}
  end
end

-- When a point at (px, py) moving (vx, vy) first touches a box (vehicle) within T s: the box at
-- (bx, by), unit forward (fx, fy), half length hl and half width hw, moving (bvx, bvy); the point
-- has radius r. nil when it does not.
-- the slab [-h, h] of one axis (position p, velocity d) cut into [t0, t1]; nil when it misses
local function slab(p, d, h, t0, t1)
  if math.abs(d) < 1e-9 then
    if math.abs(p) > h then return nil end
    return t0, t1
  end
  local ta, tb = (-h - p) / d, (h - p) / d
  if ta > tb then ta, tb = tb, ta end
  t0, t1 = math.max(t0, ta), math.min(t1, tb)
  if t0 > t1 then return nil end
  return t0, t1
end

function M.sweep(px, py, vx, vy, r, bx, by, fx, fy, hl, hw, bvx, bvy, T)
  -- in the box's frame: u along its forward, w to its left (no tables: this runs per walker near a car)
  local dx, dy = px - bx, py - by
  local rvx, rvy = vx - bvx, vy - bvy
  local u, w = dx * fx + dy * fy, -dx * fy + dy * fx
  local du, dw = rvx * fx + rvy * fy, -rvx * fy + rvy * fx
  local t0, t1 = slab(u, du, hl + r, 0, T)
  if not t0 then return nil end
  t0 = slab(w, dw, hw + r, t0, t1)
  return t0
end

local function free(P)
  for _, e in ipairs(P.pool) do if e.state == 'idle' then return e end end
end

local function standingAt(P, api, x, y)
  for _, e in ipairs(P.pool) do
    if e.state == 'placed' or e.state == 'down' then
      local bx, by = api.pose(e.id)
      if bx and (bx - x) ^ 2 + (by - y) ^ 2 < CLEAR_R * CLEAR_R then return true end
    end
  end
  return false
end

-- one step at time now. walkers: the walkers module, W its state; hitters: list of {x, y, vx, vy,
-- fx, fy, hl, hw} (centre, velocity, unit forward, half length and width) of the vehicles that can
-- hit; (px, py) the player's car.
local function touching(hitters, x, y)
  for _, h in ipairs(hitters) do
    if M.sweep(x, y, 0, 0, TOUCH_R, h.x, h.y, h.fx, h.fy, h.hl, h.hw, 0, 0, 0) then return true end
  end
  return false
end

function M.step(P, walkers, W, hitters, now, api, px, py)
  -- the bodies out there
  for _, e in ipairs(P.pool) do
    if e.state == 'placed' then
      local bx, by, vx, vy = api.pose(e.id)
      local dv = bx and math.sqrt((vx - e.vx) ^ 2 + (vy - e.vy) ^ 2) or 0
      if not bx then
        e.state = 'idle'
      elseif now - e.at > SETTLE_T and dv > HIT_DV and touching(hitters, bx, by) then
        e.state, e.at = 'down', now
        P.stats.hit = P.stats.hit + 1
        -- what was hit and by whom, for the report (the last 24)
        P.log = P.log or {}
        if #P.log >= 24 then table.remove(P.log, 1) end
        P.log[#P.log + 1] = e.info
      elseif now - e.at > MISS_T then
        -- not hit: the walker walks on, the body goes back
        walkers.untake(W, e.walker)
        e.walker = nil
        api.reset(e.id)
        e.state, e.at = 'reset', now
        P.stats.missed = P.stats.missed + 1
      end
    elseif e.state == 'down' then
      local bx, by = api.pose(e.id)
      local far = not bx or not px or (bx - px) ^ 2 + (by - py) ^ 2 > FREE_R * FREE_R
      if far or now - e.at > FREE_T then
        walkers.release(W, e.walker)
        e.walker = nil
        api.reset(e.id)
        e.state, e.at = 'reset', now
        P.stats.freed = P.stats.freed + 1
      end
    elseif e.state == 'reset' and now - e.at > RESET_T then
      api.park(e.id)
      e.state = 'idle'
    end
  end
  -- the walkers about to be touched
  for _, h in ipairs(hitters) do
    local carSpeed = math.sqrt(h.vx * h.vx + h.vy * h.vy)
    if carSpeed > MIN_SPEED and carSpeed < MAX_SPEED then
      local reach = math.sqrt(h.hl * h.hl + h.hw * h.hw) + (carSpeed + 2) * M.LEAD + 1
      -- the walkers' grid round the car (walkers.near), into a list the pool keeps
      local near, n = walkers.near(W, h.x, h.y, reach, P.near)
      P.near = near
      for k = 1, n or #near do
        local w = near[k]
        local speed = w.waiting and 0 or w.speed   -- one waiting at the kerb stands
        local wvx, wvy = w.hx * speed, w.hy * speed
        local t = M.sweep(w.x, w.y, wvx, wvy, walkers.RADIUS, h.x, h.y, h.fx, h.fy, h.hl, h.hw, h.vx, h.vy, M.LEAD)
        if t then
          local e = free(P)
          if not e then
            P.stats.noBody = P.stats.noBody + 1
          elseif not standingAt(P, api, w.x, w.y) then
            walkers.take(W, w)
            api.place(e.id, w.x, w.y, walkers.standZ(w), w.hx, w.hy, speed, w)
            e.state, e.at, e.walker, e.vx, e.vy = 'placed', now, w, wvx, wvy
            -- where the walker was: on a leg across a road (how far along it), waiting at the kerb or on
            -- its sidewalk; the vehicle: the player's or another, its speed, the walker's place in its
            -- frame (ahead, to its left)
            local dx, dy = w.x - h.x, w.y - h.y
            local leg = w.transit
            e.info = {at = math.floor(now), where = leg and (leg.cross and 'crossing' or 'corner') or 'sidewalk',
              leg = leg and math.floor(leg.s * 10) / 10, legLen = leg and math.floor(leg.len * 10) / 10, waiting = w.waiting,
              player = h.player, kmh = math.floor(carSpeed * 3.6),
              ahead = math.floor((dx * h.fx + dy * h.fy) * 10) / 10, left = math.floor((-dx * h.fy + dy * h.fx) * 10) / 10}
            P.stats.placed = P.stats.placed + 1
          end
        end
      end
    end
  end
end

function M.activeCount(P)
  local n = 0
  for _, e in ipairs(P.pool) do if e.state ~= 'idle' then n = n + 1 end end
  return n
end

-- the pool's own vehicles (not hitters, not obstacles of their own)
function M.owns(P, id)
  for _, e in ipairs(P.pool) do if e.id == id then return true end end
  return false
end

function M.clear(P, api)
  for _, e in ipairs(P.pool) do api.delete(e.id) end
  P.pool = {}
end

-- every body out there back to the pool at once (the walkers went: a new landing), the pool kept
function M.parkAll(P, api)
  for _, e in ipairs(P.pool) do
    if e.state ~= 'idle' then
      api.reset(e.id)
      api.park(e.id)
      e.state, e.walker = 'idle', nil
    end
  end
end

-- --- the game side ------------------------------------------------------------------------------
-- looks: the walkers module (its SHIRTS, PANTS, SKIN palettes)
local REF_Z = .99   -- setPositionRotation places the ref node (the front of the pelvis, 0.97 m) + 2 cm

-- a vehicle's half length and width, from its spawn box (once per vehicle, kept in boxes)
-- {half length, half width, offset of the box's centre along the heading from getPosition}: the
-- position is the ref node, which on a pickup stands 1.06 m ahead of the middle (p18)
function M.vehicleBox(boxes, o)
  local id = o:getID()
  local b = boxes[id]
  if b then return b end
  b = {2.3, .95, 0}
  pcall(function()
    local box, p, d = o:getSpawnWorldOOBB(), o:getPosition(), o:getDirectionVector()
    local h, c = box:getHalfExtents(), box:getCenter()
    local hl, hw = 0, 0
    for k, half in ipairs({h.x, h.y, h.z}) do
      local axis = box:getAxis(k - 1)
      if math.abs(axis.z) < .5 then
        if math.abs(axis.x * d.x + axis.y * d.y) > .7 then hl = half else hw = half end
      end
    end
    if hl > .5 and hw > .3 then b = {hl, math.min(hw, 1.6), (c.x - p.x) * d.x + (c.y - p.y) * d.y} end
  end)
  boxes[id] = b
  return b
end

-- The vehicles that can hit, for M.step and the walkers' wait at the kerb: every active vehicle
-- with physics within R m of (px, py) moving faster than 0.7 m/s (or any, where slow(x, y) says so),
-- but the pool's own bodies. H is the caller's state; the list returned (H.list, refilled in place)
-- holds {x, y, vx, vy, fx, fy, hl, hw, player, z} (the box's centre; z the position's height) and nothing else (the walkers read it with pairs). be:getObject and getDirectionVector allocate, so the vehicle list is read
-- again every LIST_EVERY calls and a heading every DIR_EVERY; positions and velocities come by id.
-- knock.lua passes slow = a function (x, y) -> true near something a slow or still vehicle could push:
-- then those within it are listed as well (their heading read every SLOW_DIR_EVERY calls).
local LIST_EVERY, DIR_EVERY, HIT_R, SLOW_DIR_EVERY = 30, 4, 300, 16
function M.gameHitters(H, P, boxes, px, py, slow)
  H.frame = (H.frame or 0) + 1
  H.ids, H.pool, H.dirs, H.n, H.list = H.ids or {}, H.pool or {}, H.dirs or {}, H.n or 0, H.list or {}
  local list = H.list
  if H.frame >= (H.listAt or 0) then
    H.listAt = H.frame + LIST_EVERY
    local n = 0
    for i = 0, be:getObjectCount() - 1 do
      local o = be:getObject(i)
      local id = o and o:getID()
      if id and not M.owns(P, id) then n = n + 1; H.ids[n] = id end
    end
    for k = n + 1, #H.ids do H.ids[k] = nil end
    if H.xyz == nil then H.xyz = n > 0 and pcall(function() return be:getObjectVelocityXYZ(H.ids[1]) end) or nil end
  end
  local player = be:getPlayerVehicleID(0)
  local n = 0
  for k = 1, #H.ids do
    local id = H.ids[k]
    if be:getObjectActive(id) then
      local x, y, z = be:getObjectPositionXYZ(id)
      local vx, vy
      if H.xyz then
        vx, vy = be:getObjectVelocityXYZ(id)
      else
        local o = getObjectByID(id)
        local v = o and o:getVelocity()
        if v then vx, vy = v.x, v.y end
      end
      local v2 = vx and vx * vx + vy * vy
      if x and vx and (v2 > .5 or slow and slow(x, y)) and (x - px) ^ 2 + (y - py) ^ 2 < HIT_R * HIT_R then
        local dir = H.dirs[id]
        if not dir then dir = {0, 0, -1}; H.dirs[id] = dir end
        local b = boxes[id]
        if H.frame - dir[3] >= (v2 > .5 and DIR_EVERY or SLOW_DIR_EVERY) or not b then
          local o = getObjectByID(id)
          if o then
            local d = o:getDirectionVector()
            local l = math.sqrt(d.x * d.x + d.y * d.y)
            if l > 1e-3 then dir[1], dir[2], dir[3] = d.x / l, d.y / l, H.frame end
            b = M.vehicleBox(boxes, o)
          end
        end
        if b and dir[3] >= 0 then
          n = n + 1
          local h = H.pool[n]
          if not h then h = {}; H.pool[n] = h end
          -- the box's centre: the position is the ref node, b[3] m from the middle along the heading
          local fx, fy = dir[1], dir[2]
          h.x, h.y, h.vx, h.vy, h.fx, h.fy, h.hl, h.hw = x + fx * b[3], y + fy * b[3], vx, vy, fx, fy, b[1], b[2]
          h.id, h.player, h.z = id, id == player or nil, z
          list[n] = h
        end
      end
    end
  end
  for k = n + 1, H.n do list[k] = nil end
  H.n = n
  return list
end

function M.gameApi(looks)
  local api = {}
  function api.spawn(fx, fy)
    local ok, veh = pcall(core_vehicles.spawnNewVehicle, 'e2r_ped', {
      config = 'vehicles/e2r_ped/base.pc', pos = vec3(fx, fy, -2000), rot = quat(0, 0, 0, 1),
      autoEnterVehicle = false, canSpawnAnotherVehicleCheck = false, vehicleName = 'e2r_ped_body'})
    if not ok or not veh then return end
    veh:setActive(0)
    pcall(function() veh.playerUsable = false end)
    return veh:getID()
  end
  function api.pose(id)
    local obj = getObjectByID(id)
    if not obj then return end
    local p, v = obj:getPosition(), obj:getVelocity()
    return p.x, p.y, v.x, v.y
  end
  -- shirt, pants and skin are the vehicle's paints 1-3 (the palette masks of ped_body.py)
  function api.place(id, x, y, z, hx, hy, v, w)
    local obj = getObjectByID(id)
    if not obj then return end
    obj:setActive(1)
    local cols = {looks.SHIRTS[w.shirt], looks.PANTS[w.pants], looks.SKIN[w.skin]}
    for k, field in ipairs({'color', 'colorPalette0', 'colorPalette1'}) do
      local c = cols[k]
      if c then pcall(function() obj[field] = ColorF(c[1], c[2], c[3], 1):asLinear4F() end) end
    end
    -- the body faces -y (vehicle space): its forward along the walker's heading
    local q = quatFromDir(vec3(-hx, -hy, 0), vec3(0, 0, 1))
    obj:setPositionRotation(x, y, z + REF_Z, q.x, q.y, q.z, q.w)
    obj:applyClusterVelocityScaleAdd(obj:getRefNodeId(), 0, hx * v, hy * v, 0)
  end
  -- back to its standing shape (the vehicle's Lua does it in a frame or two)
  function api.reset(id)
    local obj = getObjectByID(id)
    if obj then obj:queueLuaCommand('obj:requestReset(RESET_PHYSICS)') end
  end
  function api.park(id)
    local obj = getObjectByID(id)
    if not obj then return end
    local p = obj:getPosition()
    obj:setPositionRotation(p.x, p.y, -2000, 0, 0, 0, 1)
    obj:setActive(0)
  end
  function api.delete(id)
    local obj = getObjectByID(id)
    if obj then obj:delete() end
  end
  return api
end

return M
