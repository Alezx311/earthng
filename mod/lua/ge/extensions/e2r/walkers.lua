-- Pedestrians: walkers on the sidewalks of the navgraph of the loaded tiles (S.nav), as flow.lua
-- drives cars on its lanes. A walker is a plain table; it is drawn as POSES static shapes
-- (earthng/people_art.py), one shown, the pose picked by the distance walked: the game instances
-- static shapes, a skinned or animated one costs ~30 us of the frame each (docs/CROWDS_AND_PACKS.md).
--   - The walk graph: every nav segment slower than MAX_SPEED (no motorways) has a sidewalk line on
--     each side, SIDE_GAP m beyond its half width, offset with mitred corners.
--   - At the end of its line a walker goes on along another segment of that node, to the end of its
--     sidewalk that is nearest, in a straight TRANSIT leg (round a corner, or across a side road).
--     A dead end turns it back, on the same or the other side.
--   - Walkers keep round the focus: one further than KEEP_R, or whose segment has gone, is taken
--     away; a new one appears at least HIDE_R from the focus, so nobody pops up in plain sight.
--   - Clothes and skin are colours per walker (TSStatic instanceColor*), from the LOOK palettes.
-- No collision: pedhit.lua puts a physical body (earthng/ped_body.py) in a walker's place just before
-- a car hits it. Pure Lua apart from M.view / M.draw, so earthng/test_walkers.py runs it in lupa.
local M = {}

local SIDE_GAP = 1.7      -- m beyond the road's half width: the middle of the sidewalk
local MAX_SPEED = 16.7    -- m/s (60 km/h): faster roads have no walkers
local MITRE_MAX = 2.5     -- a sharp corner's offset is clipped to this many offsets
local KEEP_R, HIDE_R, SPAWN_R = 320, 90, 300
local FILL_PER_STEP = 12
local STRIDE = 1.45       -- m walked per full cycle (two steps): the poses' gait
local CURB = .12          -- m: a sidewalk over the road's surface, when the ground is not read
local FAR_R, FAR_EVERY = 90, 4   -- walkers further than FAR_R are drawn every FAR_EVERY frames
local MAX_DT = .1
M.POSES = 8
M.STRIDE = STRIDE
M.RADIUS = .3             -- m: a walker's half width, for the hit test
-- clothes and skin, sRGB: a walker's look is one of each, picked at random
M.SHIRTS = {{.75, .1, .1}, {.1, .2, .5}, {.9, .9, .88}, {.15, .15, .17}, {.2, .45, .25}, {.85, .65, .2},
  {.5, .5, .52}, {.45, .12, .35}, {.3, .5, .7}, {.6, .4, .25}}
M.PANTS = {{.08, .1, .2}, {.12, .12, .13}, {.35, .3, .22}, {.25, .27, .3}, {.05, .05, .06}, {.4, .38, .35}}
M.SKIN = {{.86, .68, .55}, {.72, .53, .4}, {.55, .38, .27}, {.93, .78, .66}, {.4, .27, .18}}

local function hashRandom(seed)
  local state = seed or 12345
  return function(a, b)
    state = (state * 1103515245 + 12345) % 2147483648
    local r = state / 2147483648
    if a then return a + math.floor(r * (b - a + 1)) end
    return r
  end
end

-- W = M.new{seed = n}
function M.new(opts)
  opts = opts or {}
  return {random = hashRandom(opts.seed), target = 0, slots = {}, segs = {}, nodes = {}, list = {}, version = 0,
    stats = {spawned = 0, removed = 0, transits = 0, turned = 0}}
end

-- a sidewalk line `off` m to the right of the polyline pts (x, y, z flat): mitred corners
local function offsetLine(pts, off)
  local n = #pts / 3
  local out, cum = {}, {0}
  for k = 1, n do
    local j = 3 * (k - 1) + 1
    local nx, ny, cnt = 0, 0, 0
    for _, d in ipairs({-1, 1}) do
      local a, b = k + (d < 0 and -1 or 0), k + (d < 0 and 0 or 1)
      if a >= 1 and b <= n then
        local ja, jb = 3 * (a - 1) + 1, 3 * (b - 1) + 1
        local dx, dy = pts[jb] - pts[ja], pts[jb + 1] - pts[ja + 1]
        local l = math.sqrt(dx * dx + dy * dy)
        if l > 1e-6 then nx, ny, cnt = nx + dy / l, ny - dx / l, cnt + 1 end
      end
    end
    local l = math.sqrt(nx * nx + ny * ny)
    local scale = 0
    if l > 1e-6 then
      nx, ny = nx / l, ny / l
      -- a mitre: the corner's offset grows by 1 / cos(half the turn), clipped
      scale = cnt == 2 and math.min(MITRE_MAX, 2 / l) or 1
    end
    out[#out + 1], out[#out + 2], out[#out + 3] = pts[j] + nx * off * scale, pts[j + 1] + ny * off * scale, pts[j + 2]
    if k > 1 then
      local dx, dy = out[j] - out[j - 3], out[j + 1] - out[j - 2]
      cum[k] = cum[k - 1] + math.sqrt(dx * dx + dy * dy)
    end
  end
  return out, cum
end

-- the part of a line from s0 to s1 along it
local function cutLine(line, cum, s0, s1)
  local out, c = {}, {0}
  local function add(x, y, z)
    local n = #out
    if n > 0 then c[#c + 1] = c[#c] + math.sqrt((x - out[n - 2]) ^ 2 + (y - out[n - 1]) ^ 2) end
    out[n + 1], out[n + 2], out[n + 3] = x, y, z
  end
  local n = #cum
  local x, y, z = 0, 0, 0
  local k = 1
  while k < n and cum[k + 1] <= s0 do k = k + 1 end
  local function at(s, i)
    local j = 3 * (i - 1) + 1
    local len = cum[i + 1] - cum[i]
    local f = len > 1e-6 and (s - cum[i]) / len or 0
    return line[j] + (line[j + 3] - line[j]) * f, line[j + 1] + (line[j + 4] - line[j + 1]) * f,
      line[j + 2] + (line[j + 5] - line[j + 2]) * f
  end
  x, y, z = at(s0, math.min(k, n - 1))
  add(x, y, z)
  for i = k + 1, n do
    if cum[i] >= s1 then break end
    local j = 3 * (i - 1) + 1
    add(line[j], line[j + 1], line[j + 2])
  end
  local i = 1
  while i < n - 1 and cum[i + 1] < s1 do i = i + 1 end
  x, y, z = at(s1, i)
  add(x, y, z)
  return out, c
end

-- the segments of the graph round (fx, fy): segments = {[sid] = {s = {id, a, b, lanes, speed,
-- half width, drive, x, y, z, ...}, x, y}} (world.lua S.nav). Returns whether it changed.
function M.sync(W, segments, fx, fy)
  local want, widest = {}, {}
  for sid, seg in pairs(segments) do
    local s = seg.s or seg
    local mx, my = seg.x or s[8], seg.y or s[9]
    if #s >= 13 and (s[5] or 13) <= MAX_SPEED and (not fx or (mx - fx) ^ 2 + (my - fy) ^ 2 < (KEEP_R + 300) ^ 2) then
      want[sid] = s
    end
  end
  -- at a node of several roads a sidewalk stops where the crossing road's sidewalk runs (the corner),
  -- not in the middle of the junction: its end is cut back by the widest other road there
  local at = {}
  for sid, s in pairs(want) do
    for _, id in ipairs({tostring(s[2]), tostring(s[3])}) do
      at[id] = at[id] or {}
      table.insert(at[id], s)
    end
  end
  local function trim(id, s)
    local w = 0
    for _, o in ipairs(at[id] or {}) do if o ~= s then w = math.max(w, (o[6] or 3.5) + SIDE_GAP) end end
    return w
  end
  local changed = false
  for sid, rec in pairs(W.segs) do
    if want[sid] ~= rec.src then
      W.segs[sid] = nil
      rec.dead = true
      changed = true
    end
  end
  for sid, s in pairs(want) do
    if not W.segs[sid] then
      local pts = {}
      for k = 8, #s - 2, 3 do pts[#pts + 1], pts[#pts + 2], pts[#pts + 3] = s[k], s[k + 1], s[k + 2] end
      local off = (s[6] or 3.5) + SIDE_GAP
      local right, cumR = offsetLine(pts, off)
      local left, cumL = offsetLine(pts, -off)
      local ta, tb = trim(tostring(s[2]), s), trim(tostring(s[3]), s)
      local lenR, lenL = cumR[#cumR], cumL[#cumL]
      -- a short segment keeps at least a fifth of its sidewalk
      local k = math.min(1, .8 * math.min(lenR, lenL) / math.max(ta + tb, 1e-6))
      ta, tb = ta * k, tb * k
      if ta + tb > 0 then
        right, cumR = cutLine(right, cumR, ta, lenR - tb)
        left, cumL = cutLine(left, cumL, ta, lenL - tb)
      end
      if cumR[#cumR] > 3 then
        W.segs[sid] = {id = sid, src = s, a = tostring(s[2]), b = tostring(s[3]),
          lines = {[1] = right, [-1] = left}, cums = {[1] = cumR, [-1] = cumL}}
        changed = true
      end
    end
  end
  if changed then
    W.nodes, W.list = {}, {}
    for _, rec in pairs(W.segs) do
      W.list[#W.list + 1] = rec
      for _, id in ipairs({rec.a, rec.b}) do
        W.nodes[id] = W.nodes[id] or {}
        table.insert(W.nodes[id], rec)
      end
    end
    table.sort(W.list, function(a, b) return tostring(a.id) < tostring(b.id) end)
    W.version = W.version + 1
  end
  return changed
end

-- the point at distance s along a sidewalk line, its heading along the line, and the hint (index)
local function along(line, cum, s, hint)
  local n = #cum
  s = math.max(0, math.min(cum[n], s))
  local k = hint and hint >= 1 and hint < n and hint or 1
  while k > 1 and cum[k] > s do k = k - 1 end
  while k < n - 1 and cum[k + 1] < s do k = k + 1 end
  local j = 3 * (k - 1) + 1
  local seg = cum[k + 1] - cum[k]
  local f = seg > 1e-6 and (s - cum[k]) / seg or 0
  local dx, dy = line[j + 3] - line[j], line[j + 4] - line[j + 1]
  local l = math.sqrt(dx * dx + dy * dy)
  return line[j] + dx * f, line[j + 1] + dy * f, line[j + 2] + (line[j + 5] - line[j + 2]) * f,
    l > 1e-6 and dx / l or 1, l > 1e-6 and dy / l or 0, k
end

-- where a walker is now: x, y, z (the road's surface), heading hx, hy
local function place(w)
  if w.transit then
    local t = w.transit
    local f = t.len > 1e-6 and math.min(1, t.s / t.len) or 1
    w.x, w.y, w.z = t.x0 + (t.x1 - t.x0) * f, t.y0 + (t.y1 - t.y0) * f, t.z0 + (t.z1 - t.z0) * f
    w.hx, w.hy = t.hx, t.hy
    return
  end
  local line, cum = w.seg.lines[w.side], w.seg.cums[w.side]
  local x, y, z, hx, hy, hint = along(line, cum, w.s, w.hint)
  w.x, w.y, w.z, w.hint = x, y, z, hint
  w.hx, w.hy = hx * w.dir, hy * w.dir
end

local function newWalker(W, slot, rec, side, dir, s)
  local r = W.random
  local w = W.slots[slot]
  w.free, w.taken = nil, nil
  w.seg, w.side, w.dir, w.s, w.hint, w.transit = rec, side, dir, s, nil, nil
  w.speed = 1.1 + r() * .5
  w.walked = r() * STRIDE
  w.shirt, w.pants, w.skin = r(1, #M.SHIRTS), r(1, #M.PANTS), r(1, #M.SKIN)
  w.look = (w.look or 0) + 1      -- the view repaints a walker whose look changed
  w.gz, w.gzAt = nil, nil
  place(w)
  W.stats.spawned = W.stats.spawned + 1
  return w
end

local function freeSlot(W, w, why)
  w.free, w.seg, w.transit, w.taken = true, nil, nil, nil
  W.stats.removed = W.stats.removed + 1
  if why then W.stats[why] = (W.stats[why] or 0) + 1 end
end

-- a new walker somewhere on the graph between minR and maxR from the focus
local function spawnSomewhere(W, slot, fx, fy, minR, maxR)
  local r = W.random
  if #W.list == 0 then return false end
  for _ = 1, 24 do
    local rec = W.list[r(1, #W.list)]
    local side = r() < .5 and 1 or -1
    local cum = rec.cums[side]
    local s = r() * cum[#cum]
    local x, y = along(rec.lines[side], cum, s)
    local d2 = (x - fx) ^ 2 + (y - fy) ^ 2
    if d2 >= minR * minR and d2 <= maxR * maxR then
      newWalker(W, slot, rec, side, r() < .5 and 1 or -1, s)
      return true
    end
  end
  return false
end

-- the end of a walker's line reached: on along another segment of the node, from its sidewalk end
-- nearest to where the walker stands, by a straight transit leg
local function turnAt(W, w)
  local rec, r = w.seg, W.random
  local node = w.dir > 0 and rec.b or rec.a
  local options = {}
  for _, other in ipairs(W.nodes[node] or {}) do
    if other ~= rec and not other.dead then options[#options + 1] = other end
  end
  local nextRec, nextDir, nextSide, nextS
  if #options == 0 then
    -- a dead end: back the way it came, on this side or across the road
    nextRec, nextDir = rec, -w.dir
    nextSide = r() < .5 and w.side or -w.side
    nextS = w.dir > 0 and rec.cums[nextSide][#rec.cums[nextSide]] or 0
    W.stats.turned = W.stats.turned + 1
  else
    nextRec = options[r(1, #options)]
    nextDir = nextRec.a == node and 1 or -1
    local best
    for _, side in ipairs({1, -1}) do
      local cum = nextRec.cums[side]
      local s = nextDir > 0 and 0 or cum[#cum]
      local x, y = along(nextRec.lines[side], cum, s)
      local d2 = (x - w.x) ^ 2 + (y - w.y) ^ 2
      if not best or d2 < best then best, nextSide, nextS = d2, side, s end
    end
  end
  local x1, y1, z1 = along(nextRec.lines[nextSide], nextRec.cums[nextSide], nextS)
  local dx, dy = x1 - w.x, y1 - w.y
  local len = math.sqrt(dx * dx + dy * dy)
  w.seg, w.dir, w.side, w.s, w.hint = nextRec, nextDir, nextSide, nextS, nil
  if len > .2 then
    w.transit = {x0 = w.x, y0 = w.y, z0 = w.z, x1 = x1, y1 = y1, z1 = z1, len = len, s = 0,
      hx = dx / len, hy = dy / len}
    W.stats.transits = W.stats.transits + 1
  end
end

local function advance(W, w, dt)
  local d = w.speed * dt
  w.walked = w.walked + d
  local guard = 0
  while d > 1e-6 and guard < 4 do
    guard = guard + 1
    if w.transit then
      local t = w.transit
      local left = t.len - t.s
      if d < left then t.s = t.s + d; d = 0 else d = d - left; w.transit = nil end
    else
      local cum = w.seg.cums[w.side]
      local len = cum[#cum]
      local target = w.dir > 0 and len or 0
      local left = math.abs(target - w.s)
      if d < left then
        w.s = w.s + d * w.dir
        d = 0
      else
        d = d - left
        w.s = target
        place(w)
        turnAt(W, w)
      end
    end
  end
  place(w)
end

-- One step: walkers move, those far away or off the graph go, new ones fill up to the target.
function M.step(W, dt, fx, fy)
  dt = math.min(dt or 0, MAX_DT)
  local fill = 0
  for slot = 1, W.target do
    local w = W.slots[slot]
    if not w then
      w = {free = true, slot = slot}
      W.slots[slot] = w
    end
    if not w.free and not w.taken then
      if w.seg.dead and not w.transit then
        freeSlot(W, w, 'lostRoad')
      else
        advance(W, w, dt)
        if (w.x - fx) ^ 2 + (w.y - fy) ^ 2 > KEEP_R * KEEP_R then freeSlot(W, w, 'far') end
      end
    end
    if w.free and fill < FILL_PER_STEP then
      fill = fill + 1
      -- the first fill may start anywhere in range (the walkers are being made); later ones out of sight
      local minR = W.filled and HIDE_R or 0
      spawnSomewhere(W, slot, fx, fy, minR, SPAWN_R)
    end
  end
  local busy = 0
  for slot = 1, W.target do if not W.slots[slot].free then busy = busy + 1 end end
  W.count = busy
  if busy >= W.target then W.filled = true end
end

function M.setTarget(W, n)
  for slot = n + 1, #W.slots do
    local w = W.slots[slot]
    if w and not w.free then freeSlot(W, w) end
  end
  W.target = n
end

-- walkers within r of (x, y) that are walking (not taken by a body)
function M.near(W, x, y, r)
  local out, r2 = {}, r * r
  for slot = 1, W.target do
    local w = W.slots[slot]
    if w and not w.free and not w.taken and (w.x - x) ^ 2 + (w.y - y) ^ 2 < r2 then out[#out + 1] = w end
  end
  return out
end

-- a physical body has taken the walker's place (pedhit.lua): not drawn, not moved
function M.take(W, w) w.taken = true end
-- the body was not hit after all: the walker walks on from where it was (unless its slot went meanwhile)
function M.untake(W, w) if w and w.taken then w.taken = nil end end
-- the body lay and is gone: the walker's slot fills again elsewhere
function M.release(W, w) if w and w.taken then freeSlot(W, w, 'hit') end end

-- the shapes' rotation for heading (hx, hy): +x of the shape along it (flow.quat's convention)
function M.quat(hx, hy)
  local yaw = math.atan2(hy, hx)
  return 0, 0, -math.sin(yaw / 2), math.cos(yaw / 2)
end

-- --- the game side ------------------------------------------------------------------------------
-- shapes: the POSES walk shapes; group: the scene group. Every slot owns POSES objects, one shown.
function M.view(W, shapes, group)
  return {slots = {}, frame = 0, shapes = shapes, group = group}
end

local function linear(rgb) return ColorF(rgb[1], rgb[2], rgb[3], 1):asLinear4F() end

local function slotObjects(V, slot)
  local objs = V.slots[slot]
  if objs then return objs end
  objs = {pose = -1}
  for q = 0, M.POSES - 1 do
    local o = createObject('TSStatic')
    o:setField('shapeName', 0, V.shapes[q + 1])
    o:setField('collisionType', 0, 'None')
    o:setField('decalType', 0, 'None')
    o.useInstanceRenderData = true
    o.canSave = false
    o:setPosRot(0, 0, -5000, 0, 0, 0, 1)
    o:registerObject('')
    o:setHidden(true)
    if V.group then V.group:addObject(o) end
    objs[q] = o
  end
  V.slots[slot] = objs
  return objs
end

local function hideSlot(objs)
  if objs.pose >= 0 then objs[objs.pose]:setHidden(true) end
  objs.pose = -1
end

-- the ground under a walker, read again every 2 m (a raised sidewalk, a kerb), else the road + CURB
local function groundZ(w, ground)
  if ground and (not w.gzAt or math.abs(w.walked - w.gzAt) > 2) then
    w.gzAt = w.walked
    local z = ground(w.x, w.y, w.z)
    w.gz = (z and math.abs(z - w.z) < 1.5) and z or nil
  end
  return w.gz or (w.z + CURB)
end

-- ground(x, y, z): the surface under a point, or nil (be:getSurfaceHeightBelow in the game)
function M.draw(W, V, fx, fy, ground)
  V.frame = V.frame + 1
  local moved = 0
  for slot = 1, math.max(W.target, #V.slots) do
    local w = W.slots[slot]
    local objs = V.slots[slot]
    if not w or w.free or w.taken or slot > W.target then
      if objs then hideSlot(objs) end
    else
      objs = objs or slotObjects(V, slot)
      if objs.look ~= w.look then
        objs.look = w.look
        local shirt, pants, skin = linear(M.SHIRTS[w.shirt]), linear(M.PANTS[w.pants]), linear(M.SKIN[w.skin])
        for q = 0, M.POSES - 1 do
          local o = objs[q]
          pcall(function() o.instanceColor = shirt; o.instanceColor1 = pants; o.instanceColor2 = skin end)
        end
      end
      local near = (w.x - fx) ^ 2 + (w.y - fy) ^ 2 < FAR_R * FAR_R
      if near or (slot + V.frame) % FAR_EVERY == 0 or objs.pose < 0 then
        local pose = math.floor((w.walked % STRIDE) / STRIDE * M.POSES) % M.POSES
        if pose ~= objs.pose then
          if objs.pose >= 0 then objs[objs.pose]:setHidden(true) end
          objs[pose]:setHidden(false)
          objs.pose = pose
        end
        local qx, qy, qz, qw = M.quat(w.hx, w.hy)
        objs[pose]:setPosRot(w.x, w.y, groundZ(w, ground), qx, qy, qz, qw)
        moved = moved + 1
      end
    end
  end
  return moved
end

-- the ground height a walker stands on (for the body that takes its place)
function M.standZ(w) return w.gz or (w.z + CURB) end

function M.clear(W, V)
  for _, objs in pairs(V and V.slots or {}) do
    for q = 0, M.POSES - 1 do if objs[q] then objs[q]:delete() end end
  end
  if V then V.slots = {} end
  W.slots, W.target = {}, 0
end

return M
