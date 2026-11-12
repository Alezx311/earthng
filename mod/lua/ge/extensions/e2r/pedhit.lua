-- A physical body in a walker's place just before a vehicle hits it, as handoff.lua makes flow cars
-- real round the player. Walkers (walkers.lua) have no collision; the body (earthng/ped_body.py,
-- vehicle e2r_ped: a 41-node soft body whose joints are breakable beams) falls when a car strikes it.
--   - A pool of up to SIZE bodies: 4 at switch-on, then one more every 2 s at most, only when fewer
--     than 2 are idle or a hit found none, and only near a stop (a spawn is ~0.2 s, p15; two a frame
--     at speed was ~4 s of 3 fps), parked switched
--     off (setActive 0: no physics, no cost). Crowds used to exhaust SIZE=6 (verify: hundreds of
--     noBody); a larger pool plus reclaiming far 'down' bodies and a ghost hit (no body) keep every
--     struck walker from walking through a car.
--   - Every step, for every vehicle with physics that moves (the player's car, the real cars of the
--     hand-off, the game's traffic), the walkers near its path (walkers.near) are swept against its
--     box: a walker it will touch within LEAD s gets a body. The body is placed outside the vehicle
--     box (never inside the mesh) with a kick along the contact normal so soft-body nodes do not
--     embed. Hit, or already overlapping the box after settle: eject + blood (api.splat: on
--     the ground, along the way, on a wall ahead and on the car, world.lua BLOOD).
--   - Not hit within MISS_T s (the driver braked or swerved): the body goes back to the pool and the
--     walker walks on. Hit: it lies, and once still (POOL_T, POOL_V) a pool of blood spreads under
--     it (api.splat kind 'pool'); out of FREE_R from the player (or after FREE_T s) it is reset
--     and parked, and the walker's slot fills again elsewhere.
-- The game calls go through `api` (M.gameApi), so earthng/test_walkers.py runs this in lupa.
local M = {}

M.SIZE = 24             -- bodies in the pool (was 6: crowds left most walkers without a hit)
M.LEAD = .45            -- s before the touch the body takes the walker's place
local MISS_T = .9       -- s a placed body waits for the hit (a statue on a slope tips over in ~1 s)
local FREE_R = 120      -- m from the player beyond which a lying body goes back to the pool
local FREE_T = 90       -- s a body lies at most
local RESET_T = .35     -- s for a reset (the vehicle's own Lua) before the body is parked again
local MIN_SPEED = .8    -- m/s: a vehicle slower than this hits nobody
local MAX_SPEED = 70    -- m/s: faster is a teleport (its velocity is the jump over one frame, p18)
local SETTLE_T = .08    -- s after the placing before the body's velocity means anything (it was at z -2000)
local HIT_DV = 1.0      -- m/s over its walk: a placed body moving this much faster was struck...
local TOUCH_R = 1.8     -- m: ...when a vehicle's box is this near (not a statue tipping over by itself)
local CLEAR_R = .75     -- m: no body is put where another one stands
local OUT_PAD = .22     -- m outside the vehicle box when placing / ejecting (soft body thickness)
local KICK_MIN = 2.5    -- m/s outward kick on place, so the body is not born inside the bumper
local EJECT_GAIN = .55  -- share of closing speed added on a confirmed hit
local EJECT_LIFT = .35  -- upward share of eject speed
local RECLAIM_R = 55    -- m: a 'down' body this far from the player may be recycled for a new hit
local GHOST_LEAD = .12  -- s: within this of touch, a walker with no free body is still struck (ghost)
local POOL_T, POOL_V = 1.5, .6   -- s after the hit and m/s below which a body lies still: its pool of blood

function M.new(opts)
  opts = opts or {}
  return {size = opts.size or M.SIZE, pool = {},
    stats = {placed = 0, hit = 0, missed = 0, noBody = 0, freed = 0, ghost = 0, reclaimed = 0, eject = 0}}
end

-- one body into the pool (world.lua: on demand near a stop, so a large SIZE does not hitch)
function M.prewarmOne(P, api, fx, fy)
  if #P.pool >= P.size then return false end
  local id = api.spawn(fx, fy)
  if not id then return false end
  P.pool[#P.pool + 1] = {id = id, state = 'idle'}
  return true
end

-- the whole pool at once (tests; the game prefers prewarmOne)
function M.prewarm(P, api, fx, fy)
  while M.prewarmOne(P, api, fx, fy) do end
end

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

-- Contact of point (x, y) with vehicle box h, expanded by r: whether inside, outward normal, depth.
-- Normal points from the car toward the point (the face that owns the larger normalised overlap).
function M.boxHit(x, y, r, h)
  local dx, dy = x - h.x, y - h.y
  local u, w = dx * h.fx + dy * h.fy, -dx * h.fy + dy * h.fx
  local hl, hw = h.hl + r, h.hw + r
  local au, aw = math.abs(u), math.abs(w)
  local inside = au < hl and aw < hw
  local nx, ny, depth
  if au / math.max(hl, .1) >= aw / math.max(hw, .1) then
    local sg = u >= 0 and 1 or -1
    nx, ny, depth = h.fx * sg, h.fy * sg, hl - au
  else
    local sg = w >= 0 and 1 or -1
    nx, ny, depth = -h.fy * sg, h.fx * sg, hw - aw
  end
  return inside, nx, ny, depth, u, w
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

-- recycle a lying body far from the player so a crowd hit still gets a soft body
local function reclaim(P, walkers, W, api, px, py)
  local best, bestD = nil, -1
  local need = RECLAIM_R * RECLAIM_R
  for _, e in ipairs(P.pool) do
    if e.state == 'down' then
      local bx, by = api.pose(e.id)
      local d = (not bx or not px) and (need + 1) or ((bx - px) ^ 2 + (by - py) ^ 2)
      if d >= need and d > bestD then best, bestD = e, d end
    end
  end
  if not best then return end
  if best.walker then walkers.release(W, best.walker) end
  best.walker, best.hitter = nil, nil
  api.reset(best.id)
  api.park(best.id)
  best.state = 'idle'
  P.stats.freed = P.stats.freed + 1
  P.stats.reclaimed = P.stats.reclaimed + 1
  return best
end

local function touching(hitters, x, y)
  for _, h in ipairs(hitters) do
    if M.sweep(x, y, 0, 0, TOUCH_R, h.x, h.y, h.fx, h.fy, h.hl, h.hw, 0, 0, 0) then return h end
  end
end

local function markHit(P, e, now, info)
  e.state, e.at = 'down', now
  P.stats.hit = P.stats.hit + 1
  P.log = P.log or {}
  if #P.log >= 24 then table.remove(P.log, 1) end
  P.log[#P.log + 1] = info or e.info
end

local function ejectBody(P, e, api, nx, ny, vn)
  if not (api and api.eject) then return end
  local speed = math.max(KICK_MIN, math.abs(vn) * EJECT_GAIN + KICK_MIN)
  api.eject(e.id, nx * speed, ny * speed, math.max(1.2, speed * EJECT_LIFT))
  P.stats.eject = P.stats.eject + 1
end

local function splatAt(api, x, y, z, h, kind)
  if api and api.splat then api.splat(x, y, z, h, kind) end
end

-- ghost hit: no free soft body left, but the walker still dies so the car never passes "through" it
local function ghostHit(P, walkers, W, w, h, now, api)
  walkers.take(W, w)
  walkers.release(W, w)
  splatAt(api, w.x, w.y, walkers.standZ(w), h)
  P.stats.hit = P.stats.hit + 1
  P.stats.ghost = P.stats.ghost + 1
  P.stats.noBody = P.stats.noBody + 1
  P.log = P.log or {}
  if #P.log >= 24 then table.remove(P.log, 1) end
  local dx, dy = w.x - h.x, w.y - h.y
  P.log[#P.log + 1] = {at = math.floor(now), where = 'ghost', player = h.player,
    kmh = math.floor(math.sqrt(h.vx * h.vx + h.vy * h.vy) * 3.6),
    ahead = math.floor((dx * h.fx + dy * h.fy) * 10) / 10, left = math.floor((-dx * h.fy + dy * h.fx) * 10) / 10}
end

function M.step(P, walkers, W, hitters, now, api, px, py)
  -- the bodies out there
  for _, e in ipairs(P.pool) do
    if e.state == 'placed' then
      local bx, by, vx, vy = api.pose(e.id)
      local dv = bx and math.sqrt((vx - e.vx) ^ 2 + (vy - e.vy) ^ 2) or 0
      if not bx then
        e.state = 'idle'
      else
        local h = e.hitter and touching({e.hitter}, bx, by) or touching(hitters, bx, by)
        local inside, nx, ny, depth = false, e.nx or 0, e.ny or 0, 0
        if h then
          inside, nx, ny, depth = M.boxHit(bx, by, walkers.RADIUS, h)
        end
        local struck = now - e.at > SETTLE_T and (
          (dv > HIT_DV and h) or
          (h and inside and depth > .05) or
          (h and inside))
        if struck then
          markHit(P, e, now, e.info)
          local rvx = (h and h.vx or 0) - (e.vx or 0)
          local rvy = (h and h.vy or 0) - (e.vy or 0)
          local vn = rvx * nx + rvy * ny
          if vn < 1 then vn = math.max(math.sqrt((h and h.vx or 0) ^ 2 + (h and h.vy or 0) ^ 2) * .4, KICK_MIN) end
          -- push out of the mesh first when already embedded
          if inside and depth > 0 and api.nudge then
            api.nudge(e.id, bx + nx * (depth + OUT_PAD), by + ny * (depth + OUT_PAD))
          end
          ejectBody(P, e, api, nx, ny, vn)
          splatAt(api, bx, by, e.z or 0, h or e.hitter)
        elseif now - e.at > MISS_T then
          -- not hit: the walker walks on, the body goes back
          walkers.untake(W, e.walker)
          e.walker, e.hitter = nil, nil
          api.reset(e.id)
          e.state, e.at = 'reset', now
          P.stats.missed = P.stats.missed + 1
        end
      end
    elseif e.state == 'down' then
      local bx, by, bvx, bvy, bz = api.pose(e.id)
      local far = not bx or not px or (bx - px) ^ 2 + (by - py) ^ 2 > FREE_R * FREE_R
      -- come to rest: a pool of blood under it, once
      if bx and not e.pooled and now - e.at > POOL_T and bvx * bvx + bvy * bvy < POOL_V * POOL_V then
        e.pooled = true
        splatAt(api, bx, by, bz or e.z or 0, nil, 'pool')
      end
      if far or now - e.at > FREE_T then
        walkers.release(W, e.walker)
        e.walker, e.hitter = nil, nil
        api.reset(e.id)
        e.state, e.at = 'reset', now
        P.stats.freed = P.stats.freed + 1
      end
    elseif e.state == 'reset' and now - e.at > RESET_T then
      api.park(e.id)
      e.state = 'idle'
    end
  end
  -- the walkers about to be touched (nearest touch first so the pool goes to real hits)
  local pending, pn = P.pending, 0
  if not pending then pending = {}; P.pending = pending end
  for _, h in ipairs(hitters) do
    local carSpeed = math.sqrt(h.vx * h.vx + h.vy * h.vy)
    if carSpeed > MIN_SPEED and carSpeed < MAX_SPEED then
      local reach = math.sqrt(h.hl * h.hl + h.hw * h.hw) + (carSpeed + 2) * M.LEAD + 1
      local near, n = walkers.near(W, h.x, h.y, reach, P.near)
      P.near = near
      for k = 1, n or #near do
        local w = near[k]
        local speed = w.waiting and 0 or w.speed
        local wvx, wvy = w.hx * speed, w.hy * speed
        local t = M.sweep(w.x, w.y, wvx, wvy, walkers.RADIUS, h.x, h.y, h.fx, h.fy, h.hl, h.hw, h.vx, h.vy, M.LEAD)
        if t then
          pn = pn + 1
          local row = pending[pn]
          if not row then row = {}; pending[pn] = row end
          row.t, row.w, row.h, row.wvx, row.wvy, row.speed = t, w, h, wvx, wvy, speed
        end
      end
    end
  end
  for k = pn + 1, #(pending) do pending[k] = nil end
  -- insertion sort by time-to-touch (pn is small: a car meets a handful of walkers)
  for i = 2, pn do
    local row = pending[i]
    local j = i - 1
    while j >= 1 and pending[j].t > row.t do pending[j + 1] = pending[j]; j = j - 1 end
    pending[j + 1] = row
  end
  for i = 1, pn do
    local row = pending[i]
    local w, h = row.w, row.h
    if not w.taken and not w.free then
      local e = free(P)
      if not e then e = reclaim(P, walkers, W, api, px, py) end
      if not e then
        if row.t <= GHOST_LEAD then
          ghostHit(P, walkers, W, w, h, now, api)
        else
          P.stats.noBody = P.stats.noBody + 1   -- still far; a body may free before the touch
        end
      elseif not standingAt(P, api, w.x, w.y) then
        local inside, nx, ny, depth = M.boxHit(w.x, w.y, walkers.RADIUS, h)
        local sx, sy = w.x, w.y
        if inside and depth > 0 then
          sx = w.x + nx * (depth + OUT_PAD)
          sy = w.y + ny * (depth + OUT_PAD)
        elseif depth > -OUT_PAD then
          sx = w.x + nx * (depth + OUT_PAD)
          sy = w.y + ny * (depth + OUT_PAD)
        end
        local carSpeed = math.sqrt(h.vx * h.vx + h.vy * h.vy)
        local kick = math.max(KICK_MIN, carSpeed * .2)
        local ivx = row.wvx + nx * kick + h.vx * .15
        local ivy = row.wvy + ny * kick + h.vy * .15
        walkers.take(W, w)
        api.place(e.id, sx, sy, walkers.standZ(w), w.hx, w.hy, row.speed, w, {vx = ivx, vy = ivy, vz = .4})
        e.state, e.at, e.walker, e.pooled = 'placed', now, w, nil
        e.vx, e.vy, e.nx, e.ny, e.z = ivx, ivy, nx, ny, walkers.standZ(w)
        e.hitter = {x = h.x, y = h.y, vx = h.vx, vy = h.vy, fx = h.fx, fy = h.fy, hl = h.hl, hw = h.hw,
          id = h.id, player = h.player, z = h.z}
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
      e.state, e.walker, e.hitter = 'idle', nil, nil
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
    return p.x, p.y, v.x, v.y, p.z
  end
  -- shirt, pants and skin are the vehicle's paints 1-3 (the palette masks of ped_body.py)
  -- opts: optional {vx, vy, vz} absolute velocity (else heading * walk speed)
  function api.place(id, x, y, z, hx, hy, v, w, opts)
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
    local vx = opts and opts.vx or (hx * v)
    local vy = opts and opts.vy or (hy * v)
    local vz = opts and opts.vz or 0
    obj:applyClusterVelocityScaleAdd(obj:getRefNodeId(), 0, vx, vy, vz)
  end
  -- slide the body in XY without a full re-place (out of an embedded car mesh)
  function api.nudge(id, x, y)
    local obj = getObjectByID(id)
    if not obj then return end
    local p = obj:getPosition()
    local d = obj:getDirectionVector()
    local q = quatFromDir(vec3(d.x, d.y, 0), vec3(0, 0, 1))
    obj:setPositionRotation(x, y, p.z, q.x, q.y, q.z, q.w)
  end
  function api.eject(id, dvx, dvy, dvz)
    local obj = getObjectByID(id)
    if obj then obj:applyClusterVelocityScaleAdd(obj:getRefNodeId(), 0, dvx, dvy, dvz or 0) end
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
