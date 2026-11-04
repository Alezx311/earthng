-- Traffic flow: hundreds of cars without physics on the navgraph of the loaded tiles (S.nav).
-- The game's AI cars cost ~1.5 ms of the frame each (traffic-07), so a jam is drawn by this
-- layer instead: Lua moves the cars, a TSStatic without collision shows each one.
--   - The graph: every nav segment {id, a, b, lanes '--++', speed m/s, half width, drive, x,y,z...}
--     is a link a->b with its '+' lanes and one b->a with its '-' lanes.
--   - A car follows its leader on its lane by the intelligent driver model (IDM); the last car of
--     a link follows the first one of its next link, or waits at the stop line.
--   - A node where three or more roads meet lets one car in at a time, HEADWAY s apart, first come
--     first served: that is the capacity a junction has, and queues grow behind it.
--   - A junction with mapped traffic lights (OSM highway=traffic_signals on it or on the last
--     LIGHT_APPROACH m of a road into it) runs on a clock instead: the approaches along its
--     biggest road and those across take turns, GREEN, YELLOW, then CLEAR s all red. The
--     junctions within CLUSTER m of each other (a dual carriageway's two halves) are one crossing.
--   - The player's car (and the game's AI cars) are obstacles on the lane they are on.
--   - Cars keep to the graph round the focus: a car whose link has gone, that left the graph or
--     drove out of KEEP_R is taken away, and a new one starts at least HIDE_R from the focus.
-- Pure Lua apart from M.view (the TSStatic side), so earthng/test_flow.py runs it in lupa.
local M = {}

local LEN, S0, T, AMAX, BRAKE = 4.6, 2.2, 1.4, 1.6, 2.4  -- car length, IDM jam gap, headway, comfortable accel/brake
local HEADWAY = 1.9      -- s between two cars let into a junction of equal roads (all stop)
local GAP_ACCEPT = 4.0   -- s a side road car needs before the next main road car arrives
local SIDE_CLEAR = 2.4   -- s the main road waits while a side road car crosses it
local SIDE_FORCE = 40    -- s: a side road car waiting that long pushes in
local TURN_SPEED = 8     -- m/s round a corner sharper than 30 degrees
local STOP_GAP = 1.0     -- m before the end of a link a waiting car stops
local KEEP_R, HIDE_R, SPAWN_R = 1100, 280, 950
local WAIT_GIVE_UP = 90  -- s: a car stuck that long (a gridlock on the edge of the graph) is taken away
local MAX_DT = 0.1
local FILL_PER_STEP = 25
-- traffic lights: the timing of the lights of issue #23 (signals.lua there), slot * CYCLE / SLOTS
-- the offset of a crossing, so that the two can share one clock later
local GREEN, YELLOW, CLEAR, SLOTS = 24, 3, 2, 3
local CYCLE = 2 * (GREEN + YELLOW + CLEAR)
local LIGHT_NODE_R = 14     -- m: a light this near a junction is its light
local LIGHT_APPROACH = 45   -- m: a light on the last of a road into a junction is that junction's
local LIGHT_SIDE = 12       -- m off the road's line a light of it may stand
local CLUSTER = 40          -- m: lit junctions this near each other are one crossing

M.LEN = LEN
-- the shapes' paints (earthng/flow_art.py PAINTS) and their shares among the cars
M.PAINTS = {'white', 'black', 'silver', 'grey', 'blue', 'red', 'beige', 'green'}
M.SHARE = {24, 20, 18, 14, 8, 7, 5, 4}
-- the shapes' bodies (flow_art.py BODIES) and their shares
M.BODIES = {'sedan', 'hatch', 'suv', 'van'}
M.BODY_SHARE = {40, 30, 22, 8}
-- their sRGB, for the real cars that take a flow car's place (handoff.lua)
M.PAINT_RGB = {{.86, .86, .84}, {.05, .05, .06}, {.62, .63, .65}, {.33, .34, .36}, {.10, .17, .35}, {.55, .07, .06},
  {.70, .64, .52}, {.12, .24, .16}}
-- countries (pack ids) that drive on the left
local LEFT = {'^uk$', '^uk%-', '^united%-kingdom', 'ireland', 'zanzibar', 'tanzania', 'kenya', 'uganda',
  'south%-africa', 'malta', 'cyprus', 'japan', 'australia', 'new%-zealand', 'india', 'thailand', 'indonesia',
  'malaysia', 'singapore', 'hong%-kong', 'sri%-lanka', 'bangladesh', 'pakistan', 'jamaica'}
function M.leftHand(country)
  country = tostring(country or ''):lower()
  for _, pattern in ipairs(LEFT) do if country:find(pattern) then return true end end
  return false
end

-- the colour of an approach of axis 0/1 at a crossing with this offset (s), now
function M.colour(offset, axis, now)
  local at = (now + offset + axis * CYCLE / 2) % CYCLE
  if at < GREEN then return 'green' end
  if at < GREEN + YELLOW then return 'yellow' end
  return 'red'
end
M.CYCLE = CYCLE

local function hashRandom(seed)
  local state = seed or 12345
  return function(a, b)
    state = (state * 1103515245 + 12345) % 2147483648
    local r = state / 2147483648
    if a then return a + math.floor(r * (b - a + 1)) end
    return r
  end
end

-- F = M.new{leftHand = bool, seed = n, paints = {weights}}
function M.new(opts)
  opts = opts or {}
  return {links = {}, nodes = {}, segs = {}, cars = {}, nextId = 1, now = 0, target = 0, version = 0,
    leftHand = opts.leftHand, random = hashRandom(opts.seed), paints = opts.paints or {1}, bodies = opts.bodies or {1},
    obstacles = {}, grid = {}, gridCell = 30, stats = {spawned = 0, removed = 0, gaveUp = 0}}
end

local function countChar(s, c)
  local n = 0
  for k = 1, #s do if s:sub(k, k) == c then n = n + 1 end end
  return n
end

local function node(F, id)
  local n = F.nodes[id]
  if not n then
    n = {id = id, out = {}, inn = {}, segs = 0, busyUntil = -1, queue = {}}
    F.nodes[id] = n
  end
  return n
end

local function makeLink(F, sid, dir, s, lanes, total, halfWidth)
  local n = (#s - 7) / 3
  local pts, cum = {}, {0}
  for k = 1, n do
    local o = 8 + 3 * ((dir > 0 and k or (n - k + 1)) - 1)
    pts[#pts + 1], pts[#pts + 2], pts[#pts + 3] = s[o], s[o + 1], s[o + 2]
    if k > 1 then
      local j = 3 * (k - 1) + 1
      local dx, dy = pts[j] - pts[j - 3], pts[j + 1] - pts[j - 2]
      cum[k] = cum[k - 1] + math.sqrt(dx * dx + dy * dy)
    end
  end
  local width = 2 * halfWidth / math.max(1, total)
  width = math.max(2.6, math.min(3.8, width))
  local from, to = dir > 0 and s[2] or s[3], dir > 0 and s[3] or s[2]
  local link = {id = sid .. (dir > 0 and '+' or '-'), sid = sid, dir = dir, from = tostring(from), to = tostring(to),
    pts = pts, cum = cum, len = cum[n], lanes = lanes, laneWidth = width, oneWay = total == lanes,
    speed = math.max(4, s[5] or 13), drive = s[7] or .7, cars = {}}
  link.weight = link.drive * lanes * link.speed
  for l = 1, lanes do link.cars[l] = {} end
  return link
end

-- lateral offset of a lane to the right of the link's direction
local function laneOffset(F, link, lane)
  local w = link.laneWidth
  local r
  if link.oneWay then r = -link.lanes * w / 2 + (lane - .5) * w
  else r = (lane - .5) * w end
  if F.leftHand then r = -r end
  return r
end
M.laneOffset = laneOffset

-- '+ 0': floor(-0.3) is -0, and tostring(-0) is '-0', another cell than '0'
local function cellKey(F, x, y)
  return (math.floor(x / F.gridCell) + 0) .. ':' .. (math.floor(y / F.gridCell) + 0)
end

local function gridAdd(F, link)
  local c = F.gridCell
  local pts = link.pts
  link.cells = {}
  for k = 1, #pts / 3 - 1 do
    local j = 3 * (k - 1) + 1
    local x0, y0, x1, y1 = pts[j], pts[j + 1], pts[j + 3], pts[j + 4]
    local steps = math.max(1, math.ceil(math.sqrt((x1 - x0) ^ 2 + (y1 - y0) ^ 2) / c))
    for t = 0, steps do
      local x, y = x0 + (x1 - x0) * t / steps, y0 + (y1 - y0) * t / steps
      local key = cellKey(F, x, y)
      local cell = F.grid[key]
      if not cell then cell = {}; F.grid[key] = cell end
      if not cell[link] then cell[link] = true; link.cells[#link.cells + 1] = key end
    end
  end
end

local function removeCar(F, car, why)
  car.dead = true
  local list = car.link and car.link.cars[car.lane]
  if list then
    for k = #list, 1, -1 do if list[k] == car then table.remove(list, k); break end end
  end
  F.cars[car.id] = nil
  F.stats[why or 'removed'] = (F.stats[why or 'removed'] or 0) + 1
  if F.onRemove then F.onRemove(car) end
end

local function removeLink(F, link)
  for _, list in ipairs(link.cars) do
    for k = #list, 1, -1 do removeCar(F, list[k]) end
  end
  F.links[link.id] = nil
  local a, b = F.nodes[link.from], F.nodes[link.to]
  if a then for k = #a.out, 1, -1 do if a.out[k] == link then table.remove(a.out, k) end end end
  if b then for k = #b.inn, 1, -1 do if b.inn[k] == link then table.remove(b.inn, k) end end end
  for _, key in ipairs(link.cells or {}) do
    local cell = F.grid[key]
    if cell then
      cell[link] = nil
      if next(cell) == nil then F.grid[key] = nil end
    end
  end
end

local function pickNext(F, link)
  local n = F.nodes[link.to]
  if not n then return end
  local total, options = 0, {}
  for _, out in ipairs(n.out) do
    if out.sid ~= link.sid then
      options[#options + 1] = out
      total = total + out.weight
    end
  end
  if #options == 0 then
    -- a dead end turns round on its own road; the end of the graph has no way on
    for _, out in ipairs(n.out) do if out.sid == link.sid and n.segs == 1 and #n.inn == 1 then return out end end
    return
  end
  local r = F.random() * total
  for _, out in ipairs(options) do
    r = r - out.weight
    if r <= 0 then return out end
  end
  return options[#options]
end

local function gated(F, link)
  local n = F.nodes[link.to]
  return n and n.segs >= 3
end

-- a junction's main road: the strongest in-links when at most two roads (both ways of one
-- street) have that weight; otherwise all roads are equal and every car stops
local function mainRoad(F, n)
  if n.mainAt == F.version then return n.main end
  local best, sids, count = 0, {}, 0
  for _, link in ipairs(n.inn) do best = math.max(best, link.weight) end
  for _, link in ipairs(n.inn) do
    if link.weight >= best * .999 and not sids[link.sid] then sids[link.sid] = true; count = count + 1 end
  end
  local others = false
  for _, link in ipairs(n.inn) do if not sids[link.sid] then others = true end end
  n.main = (count <= 2 and others) and sids or nil
  n.mainAt = F.version
  return n.main
end

-- heading change from the end of link to the start of next, radians
local function turn(link, next)
  local p, q = link.pts, next.pts
  local j = #p - 5
  local a = math.atan2(p[j + 4] - p[j + 1], p[j + 3] - p[j])
  local b = math.atan2(q[5] - q[2], q[4] - q[1])
  local d = math.abs(b - a) % (2 * math.pi)
  return d > math.pi and 2 * math.pi - d or d
end

-- whether car stops at the end of its link: at a junction a car waits for its turn, but the
-- main road goes on unless a side road car is crossing it or there is no room on the way out
local room
local function mustStop(F, car)
  if car.granted then return false end
  local link = car.link
  local light = link.light
  if light then
    -- a lit crossing: red stops, yellow stops a car that can, green goes when there is room;
    -- the roads inside a crossing (between its two halves) go on when there is room
    if light ~= true then
      local c = M.colour(light.c.offset, light.axis, F.now)
      if c == 'red' then return true end
      if c == 'yellow' then
        -- only a car at speed runs a yellow: one creeping up to the line would crawl across into
        -- the other road's green
        if car.v > 3 and link.len - car.s - STOP_GAP < car.v * car.v / (2 * BRAKE) then car.granted = true; return false end
        return true
      end
    end
    return not room(car)
  end
  if not gated(F, link) then return false end
  local n = F.nodes[link.to]
  local main = mainRoad(F, n)
  if main and main[car.link.sid] then
    return F.now < (n.sideUntil or -1) or not room(car)
  end
  return true
end

-- segments: sid -> seg (seg.s the nav array, seg.x/seg.y its middle). Links within KEEP_R of
-- (fx, fy) come and go with the segments; a car on a link that went is taken away.
local planLights
function M.sync(F, segments, fx, fy, lights)
  local want = {}
  for sid, seg in pairs(segments) do
    local s = seg.s or seg
    local mx, my = seg.x or s[8], seg.y or s[9]
    if not fx or (mx - fx) ^ 2 + (my - fy) ^ 2 < (KEEP_R + 300) ^ 2 then want[sid] = s end
  end
  local changed = false
  for sid, s in pairs(F.segs) do
    if want[sid] ~= s then
      for _, dir in ipairs({1, -1}) do
        local link = F.links[sid .. (dir > 0 and '+' or '-')]
        if link then removeLink(F, link) end
      end
      local a, b = F.nodes[tostring(s[2])], F.nodes[tostring(s[3])]
      if a then a.segs = a.segs - 1 end
      if b then b.segs = b.segs - 1 end
      F.segs[sid] = nil
      changed = true
    end
  end
  for sid, s in pairs(want) do
    if not F.segs[sid] and #s >= 13 then
      local lanes = tostring(s[4] or '+-')
      local fwd, back = countChar(lanes, '+'), countChar(lanes, '-')
      local total = fwd + back
      if total > 0 then
        F.segs[sid] = s
        node(F, tostring(s[2])).segs = node(F, tostring(s[2])).segs + 1
        node(F, tostring(s[3])).segs = node(F, tostring(s[3])).segs + 1
        for _, d in ipairs({{1, fwd}, {-1, back}}) do
          if d[2] > 0 then
            local link = makeLink(F, tostring(sid), d[1], s, d[2], total, s[6] or 3.5)
            if link.len > 1 then
              F.links[link.id] = link
              table.insert(node(F, link.from).out, link)
              table.insert(node(F, link.to).inn, link)
              gridAdd(F, link)
            end
          end
        end
        changed = true
      end
    end
  end
  for id, n in pairs(F.nodes) do
    if #n.out == 0 and #n.inn == 0 then F.nodes[id] = nil end
  end
  if changed then
    F.linkList = nil
    F.version = (F.version or 0) + 1
    -- a car whose way on went (or a new road joined its junction) picks again
    for _, car in pairs(F.cars) do
      local stale = car.next and F.links[car.next.id] ~= car.next
      if stale or (not car.granted and (not car.next or gated(F, car.link))) then
        car.next, car.granted, car.turn = pickNext(F, car.link), nil, nil
        car.nextLane = car.next and math.min(car.next.lanes, F.random(1, car.next.lanes))
      end
    end
  end
  if lights then F.lights = lights end
  if changed or lights then planLights(F) end
  return changed
end

-- where a link ends, and its heading there
local function linkEnd(link)
  local p = link.pts
  local j = #p - 5
  local dx, dy = p[j + 3] - p[j], p[j + 4] - p[j + 1]
  local h = math.sqrt(dx * dx + dy * dy)
  return p[j + 3], p[j + 4], h > 0 and dx / h or 1, h > 0 and dy / h or 0
end

-- whether light (x, y) stands on the last LIGHT_APPROACH m of link, beside its line
local function onApproach(link, x, y)
  local pts, cum = link.pts, link.cum
  for k = #cum - 1, 1, -1 do
    if link.len - cum[k + 1] > LIGHT_APPROACH then break end
    local j = 3 * (k - 1) + 1
    local dx, dy = pts[j + 3] - pts[j], pts[j + 4] - pts[j + 1]
    local l2 = dx * dx + dy * dy
    if l2 > 0 then
      local f = math.max(0, math.min(1, ((x - pts[j]) * dx + (y - pts[j + 1]) * dy) / l2))
      local ex, ey = pts[j] + f * dx - x, pts[j + 1] + f * dy - y
      if ex * ex + ey * ey < LIGHT_SIDE * LIGHT_SIDE and link.len - (cum[k] + f * math.sqrt(l2)) <= LIGHT_APPROACH then
        return true
      end
    end
  end
  return false
end

-- The lit junctions of the graph from F.lights. Only a junction of three or more roads is lit:
-- the flow has no stop line in the middle of a road (a lit pedestrian crossing).
function planLights(F)
  for _, n in pairs(F.nodes) do n.signal = nil end
  for _, link in pairs(F.links) do link.light = nil end
  local lit = {}
  for _, q in ipairs(F.lights or {}) do
    local x, y = q[1] or q.x, q[2] or q.y
    local seen = {}
    for gx = -2, 2 do
      for gy = -2, 2 do
        for link in pairs(F.grid[cellKey(F, x + gx * F.gridCell, y + gy * F.gridCell)] or {}) do
          if not seen[link] then
            seen[link] = true
            local n = F.nodes[link.to]
            if n and n.segs >= 3 and not lit[n] then
              local ex, ey = linkEnd(link)
              if (ex - x) ^ 2 + (ey - y) ^ 2 < LIGHT_NODE_R * LIGHT_NODE_R or onApproach(link, x, y) then
                lit[n] = {x = ex, y = ey}
              end
            end
          end
        end
      end
    end
  end
  -- a fixed order: two syncs of one graph light it the same way
  local order = {}
  for n in pairs(lit) do order[#order + 1] = n end
  table.sort(order, function(a, b) return a.id < b.id end)
  local crossings = 0
  for _, seed in ipairs(order) do
    if not seed.signal then
      -- the crossing: lit junctions within CLUSTER of each other
      local members, head, c = {seed}, 1, {nodes = {}}
      seed.signal, c.nodes[seed.id] = c, true
      while members[head] do
        local pa = lit[members[head]]
        head = head + 1
        for _, b in ipairs(order) do
          local pb = lit[b]
          if not b.signal and (pa.x - pb.x) ^ 2 + (pa.y - pb.y) ^ 2 < CLUSTER * CLUSTER then
            b.signal, c.nodes[b.id] = c, true
            members[#members + 1] = b
          end
        end
      end
      -- its axis is the heading of its biggest road in; its slot is fixed by its smallest node id
      local lead
      for _, n in ipairs(members) do
        for _, link in ipairs(n.inn) do
          if not c.nodes[link.from] and (not lead or link.weight > lead.weight or
              (link.weight == lead.weight and link.id < lead.id)) then lead = link end
        end
      end
      local slot = 0
      for k = 1, #seed.id do slot = slot + seed.id:byte(k) end
      c.offset = (slot % SLOTS) * CYCLE / SLOTS
      local _, _, lx, ly = linkEnd(lead or members[1].inn[1])
      for _, n in ipairs(members) do
        for _, link in ipairs(n.inn) do
          if c.nodes[link.from] then
            link.light = true
          else
            local _, _, hx, hy = linkEnd(link)
            link.light = {c = c, axis = math.abs(hx * lx + hy * ly) >= .7071 and 0 or 1}
          end
        end
      end
      crossings = crossings + 1
    end
  end
  F.crossings = crossings
end

-- the colour a link's cars see at its end: 'green', 'yellow', 'red'; nil when it has no light
function M.lightOf(F, link)
  local light = link.light
  if not light then return nil end
  if light == true then return 'green' end
  return M.colour(light.c.offset, light.axis, F.now)
end

-- position, heading and pitch of a car (or of link, s, lane)
function M.pose(F, link, s, lane, hint)
  local cum, pts = link.cum, link.pts
  local k = hint or 1
  if k > #cum - 1 or cum[k] > s then k = 1 end
  while k < #cum - 1 and cum[k + 1] < s do k = k + 1 end
  local j = 3 * (k - 1) + 1
  local seg = cum[k + 1] - cum[k]
  local f = seg > 0 and math.max(0, math.min(1, (s - cum[k]) / seg)) or 0
  local dx, dy, dz = pts[j + 3] - pts[j], pts[j + 4] - pts[j + 1], pts[j + 5] - pts[j + 2]
  local h = math.sqrt(dx * dx + dy * dy)
  local ux, uy = h > 0 and dx / h or 1, h > 0 and dy / h or 0
  local r = laneOffset(F, link, lane)
  return pts[j] + dx * f + uy * r, pts[j + 1] + dy * f - ux * r, pts[j + 2] + dz * f,
    math.atan2(dy, dx), h > 0 and math.atan2(dz, h) or 0, k
end

local function insertCar(list, car)
  local k = 1
  while k <= #list and list[k].s < car.s do k = k + 1 end
  table.insert(list, k, car)
end

-- an index into weights, picked by them
local function pick(F, weights)
  local total = 0
  for _, w in ipairs(weights) do total = total + w end
  local r = F.random() * total
  for k, w in ipairs(weights) do
    r = r - w
    if r <= 0 then return k end
  end
  return 1
end

-- a new car on link at s (nil: a free place picked at random); returns it or nil when another car
-- is within room m (default the length, the jam gap and 3 m)
function M.spawn(F, link, s, lane, v, paint, room, body)
  lane = lane or F.random(1, link.lanes)
  local list = link.cars[lane]
  if not s then
    s = F.random() * math.max(0, link.len - LEN) + LEN / 2
  end
  room = room or LEN + S0 + 3
  for _, other in ipairs(list) do
    if math.abs(other.s - s) < room then return end
  end
  local car = {id = F.nextId, link = link, lane = lane, s = s, v = v or link.speed * .6,
    want = .85 + F.random() * .3, paint = paint or pick(F, F.paints), body = body or pick(F, F.bodies), wait = 0}
  F.nextId = F.nextId + 1
  car.next = pickNext(F, link)
  car.nextLane = car.next and math.min(car.next.lanes, F.random(1, car.next.lanes))
  insertCar(list, car)
  F.cars[car.id] = car
  F.stats.spawned = F.stats.spawned + 1
  if F.onSpawn then F.onSpawn(car) end
  return car
end

-- every lane under (x, y) heading along (hx, hy) (a unit vector; nil: any heading): fn(link,
-- lane, s, along, miss) with miss the distance from the lane's middle (under 0.6 of a lane)
local function locate(F, x, y, hx, hy, fn)
  -- the cells hold a link's centre line; a lane lies up to a few metres off it, maybe in the next
  -- cell: the 3 x 3 cells round the point
  local seen, list, c = {}, {}, F.gridCell
  for gx = -1, 1 do
    for gy = -1, 1 do
      for link in pairs(F.grid[cellKey(F, x + gx * c, y + gy * c)] or {}) do
        if not seen[link] then seen[link] = true; list[#list + 1] = link end
      end
    end
  end
  for _, link in ipairs(list) do
    local pts, cum = link.pts, link.cum
    for k = 1, #cum - 1 do
      local j = 3 * (k - 1) + 1
      local dx, dy = pts[j + 3] - pts[j], pts[j + 4] - pts[j + 1]
      local l2 = dx * dx + dy * dy
      if l2 > 0 then
        local f = ((x - pts[j]) * dx + (y - pts[j + 1]) * dy) / l2
        if f >= 0 and f <= 1 then
          local h = math.sqrt(l2)
          -- signed distance to the right of the link
          local right = ((x - pts[j]) * dy - (y - pts[j + 1]) * dx) / h
          local along = hx and (hx * dx + hy * dy) / h or 1
          if along > .5 then
            for lane = 1, link.lanes do
              local miss = math.abs(right - laneOffset(F, link, lane))
              if miss < link.laneWidth * .6 then fn(link, lane, cum[k] + f * h, along, miss) end
            end
          end
        end
      end
    end
  end
end

-- obstacles: list of {x, y, vx, vy}; each lands on the lane it is on (same heading when moving)
local function placeObstacles(F, list)
  F.obstacles = {}
  for _, o in ipairs(list or {}) do
    local speed = math.sqrt((o.vx or 0) ^ 2 + (o.vy or 0) ^ 2)
    local hx, hy = speed > 1 and o.vx / speed or nil, speed > 1 and o.vy / speed or nil
    locate(F, o.x, o.y, hx, hy, function(link, lane, s, along)
      local key = link.id .. '#' .. lane
      F.obstacles[key] = F.obstacles[key] or {}
      table.insert(F.obstacles[key], {s = s, v = speed * math.max(0, along)})
    end)
  end
end

-- --- hand-off to real cars (handoff.lua) --------------------------------------------------------
-- whether a real car at (x, y) heading (hx, hy) at v m/s must stand for a light: it is on a lit
-- approach within its braking reach of a red one, or of a yellow one it can stop for
function M.holdAt(F, x, y, hx, hy, v)
  local hold = false
  locate(F, x, y, hx, hy, function(link, lane, s)
    local light = link.light
    if light and light ~= true then
      local c = M.colour(light.c.offset, light.axis, F.now)
      local toEnd = link.len - s
      local brake = v * v / (2 * BRAKE)
      if toEnd > .5 and toEnd < brake + 8 and (c == 'red' or (c == 'yellow' and toEnd > brake)) then hold = true end
    end
  end)
  return hold
end

-- flow cars within r of (fx, fy), nearest first, each {car, x, y, z, yaw, d}
function M.near(F, fx, fy, r)
  local out = {}
  for _, car in pairs(F.cars) do
    local x, y, z, yaw, _, hint = M.pose(F, car.link, car.s, car.lane, car.hint)
    car.hint = hint
    local d = math.sqrt((x - fx) ^ 2 + (y - fy) ^ 2)
    if d < r then out[#out + 1] = {car = car, x = x, y = y, z = z, yaw = yaw, d = d} end
  end
  table.sort(out, function(a, b) return a.d < b.d end)
  return out
end

-- a flow car becomes a real one: it leaves the lanes, but still counts towards the target
function M.take(F, car)
  removeCar(F, car, 'promoted')
  F.promoted = (F.promoted or 0) + 1
end

-- a real car is gone (deleted by someone else): it no longer counts towards the target
function M.forget(F)
  F.promoted = math.max(0, (F.promoted or 0) - 1)
end

-- a real car comes back: onto the lane under (x, y) along its heading (hx, hy), at speed v, with
-- paint. Returns the flow car, or nil when no lane is there or it has no room (it is dropped then;
-- the fill puts another one out of sight).
function M.put(F, x, y, hx, hy, v, paint, body)
  F.promoted = math.max(0, (F.promoted or 0) - 1)
  local best
  locate(F, x, y, hx, hy, function(link, lane, s, along, miss)
    if along > .7 and (not best or miss < best.miss) then best = {link = link, lane = lane, s = s, miss = miss} end
  end)
  if not best then F.stats.dropped = (F.stats.dropped or 0) + 1; return end
  local car = M.spawn(F, best.link, math.min(best.s, best.link.len - .1), best.lane, v, paint, LEN, body)
  if not car then F.stats.dropped = (F.stats.dropped or 0) + 1 end
  return car
end

local function idm(car, v0, gap, dv)
  local v = car.v
  local free = 1 - (v / math.max(.1, v0)) ^ 4
  if not gap then return AMAX * free end
  local star = S0 + math.max(0, v * T + v * dv / (2 * math.sqrt(AMAX * BRAKE)))
  return AMAX * (free - (star / math.max(.1, gap)) ^ 2)
end

-- the nearest thing ahead of car within its link and the next one: gap (m), its speed
local function ahead(F, car, list, k)
  local link, gap, v = car.link
  local leader = list[k + 1]
  if leader then gap, v = leader.s - car.s - LEN, leader.v end
  local obs = F.obstacles[link.id .. '#' .. car.lane]
  if obs then
    for _, o in ipairs(obs) do
      local g = o.s - car.s - LEN
      if g > -LEN * .5 and (not gap or g < gap) then gap, v = math.max(.1, g), o.v end
    end
  end
  if gap then return gap, v end
  local toEnd = link.len - car.s
  if not car.next then return nil end
  if mustStop(F, car) then return toEnd - STOP_GAP, 0 end
  local nextList = car.next.cars[car.nextLane]
  local first = nextList and nextList[1]
  if first then return toEnd + first.s - LEN, first.v end
  local nobs = F.obstacles[car.next.id .. '#' .. car.nextLane]
  if nobs then
    local best
    for _, o in ipairs(nobs) do if not best or o.s < best.s then best = o end end
    if best then return toEnd + best.s - LEN, best.v end
  end
end

-- a car near a junction asks for its turn: the first in the node's queue gets it once the node is
-- free and its next lane has room
local function request(F, car)
  local n = F.nodes[car.link.to]
  if not n then return end
  local queued = false
  for _, c in ipairs(n.queue) do if c == car then queued = true; break end end
  if not queued then n.queue[#n.queue + 1] = car end
end

-- room on the way out: the last car in has cleared the junction or is moving off it
function room(car)
  local list = car.next and car.next.cars[car.nextLane]
  local first = list and list[1]
  return not first or first.s > LEN + S0 or (first.v > 1 and first.s > LEN + .5)
end

-- seconds until the nearest main road car reaches the junction
local function mainArrival(n, main)
  local best = math.huge
  for _, link in ipairs(n.inn) do
    if main[link.sid] then
      for _, list in ipairs(link.cars) do
        local car = list[#list]
        if car then best = math.min(best, (link.len - car.s) / math.max(car.v, 1)) end
      end
    end
  end
  return best
end

local function grant(car, n)
  car.granted = true
  n.holder = car
  for k, c in ipairs(n.queue) do if c == car then table.remove(n.queue, k); break end end
end

-- the last car let in has gone through (or away): the junction takes the next one
local function clearOf(n)
  local h = n.holder
  return not h or h.dead or h.link.to ~= n.id
end

local function serveNodes(F)
  for _, n in pairs(F.nodes) do
    local q = n.queue
    for k = #q, 1, -1 do
      local c = q[k]
      if c.dead or c.granted or c.link.to ~= n.id then table.remove(q, k) end
    end
    if n.signal then
      for k = #q, 1, -1 do q[k] = nil end
    elseif #q > 0 then
      local main = mainRoad(F, n)
      if not main then
        -- equal roads: one car at a time, first come first served
        local car = q[1]
        if F.now >= n.busyUntil and clearOf(n) and room(car) then
          grant(car, n)
          n.busyUntil = F.now + HEADWAY
        end
      else
        -- main road cars do not queue (mustStop); a side road car goes into a gap of the main
        -- road, or pushes in after a long wait
        local side
        for _, car in ipairs(q) do
          if not main[car.link.sid] and (not side or car.wait > side.wait) then side = car end
        end
        if side and F.now >= (n.sideUntil or -1) and clearOf(n) and room(side) then
          local gap = mainArrival(n, main) > GAP_ACCEPT and F.now - (n.mainPassAt or -10) > 1.2
          if gap or side.wait > SIDE_FORCE then
            grant(side, n)
            n.sideUntil = F.now + SIDE_CLEAR
          end
        end
      end
    end
  end
end

local function advance(F, car, dt, list, k)
  local link = car.link
  local gap, lv = ahead(F, car, list, k)
  local v0 = link.speed * car.want
  -- slow down round a corner
  if car.next and link.len - car.s < 30 then
    car.turn = car.turn or turn(link, car.next)
    if car.turn > .52 then v0 = math.min(v0, TURN_SPEED) end
  end
  local a = idm(car, v0, gap, gap and (car.v - (lv or 0)) or 0)
  a = math.max(-9, math.min(AMAX, a))
  car.v = math.max(0, car.v + a * dt)
  -- never into the leader within a step
  if gap then car.v = math.min(car.v, math.max(0, gap - .3) / math.max(dt, .016)) end
  car.s = car.s + car.v * dt
  car.wait = car.v < .5 and car.wait + dt or 0
  if car.next and gated(F, link) and not car.granted and not link.light then
    local reach = math.max(20, car.v * car.v / (2 * BRAKE) + 12)
    if link.len - car.s < reach then
      local main = mainRoad(F, F.nodes[link.to])
      if main and main[link.sid] then
        if link.len - car.s < 8 then F.nodes[link.to].mainPassAt = F.now end
      else
        request(F, car)
      end
    end
  end
end

local function cross(F, car)
  while car.s >= car.link.len and not car.dead do
    local link, next = car.link, car.next
    if not next then removeCar(F, car); return end
    -- two links into one lane: the one that would land on another car waits at its end
    local first = next.cars[car.nextLane][1]
    if first and first.s - (car.s - link.len) < LEN then
      car.s, car.v = link.len - .01, math.min(car.v, first.v)
      return
    end
    local list = link.cars[car.lane]
    for i = #list, 1, -1 do if list[i] == car then table.remove(list, i); break end end
    car.s = car.s - link.len
    car.link, car.lane, car.granted, car.hint, car.turn = next, car.nextLane, nil, nil, nil
    insertCar(next.cars[car.lane], car)
    car.next = pickNext(F, next)
    car.nextLane = car.next and math.min(car.next.lanes, F.random(1, car.next.lanes))
  end
end

-- the links in a fixed order with their running weight (length x lanes x class), for spawns
local function links(F)
  if not F.linkList then
    local list, acc, total = {}, {}, 0
    for _, link in pairs(F.links) do list[#list + 1] = link end
    table.sort(list, function(a, b) return a.id < b.id end)
    for k, link in ipairs(list) do
      total = total + link.len * link.lanes * link.drive
      acc[k] = total
    end
    F.linkList, F.linkAcc, F.linkWeight = list, acc, total
  end
  return F.linkList, F.linkWeight, F.linkAcc
end

-- a random link by its length, lanes and class, its middle between minR and maxR of the focus
local function spawnSomewhere(F, fx, fy, minR, maxR)
  local list, total, acc = links(F)
  if #list == 0 then return end
  for _ = 1, 12 do
    local r = F.random() * total
    local lo, hi = 1, #list
    while lo < hi do
      local mid = math.floor((lo + hi) / 2)
      if acc[mid] < r then lo = mid + 1 else hi = mid end
    end
    local pick = list[lo]
    local s = F.random() * pick.len
    local x, y = M.pose(F, pick, s, 1)
    local d2 = fx and ((x - fx) ^ 2 + (y - fy) ^ 2) or 0
    if not fx or (d2 >= minR * minR and d2 <= maxR * maxR) then
      local car = M.spawn(F, pick, s)
      if car then return car end
    end
  end
end

-- one step: dt s, focus (fx, fy), obstacles {x, y, vx, vy}
function M.step(F, dt, fx, fy, obstacles)
  dt = math.min(dt or 0, MAX_DT)
  F.now = F.now + dt
  placeObstacles(F, obstacles)
  -- leaders first along each lane, so a follower sees where its leader is now
  for _, link in pairs(F.links) do
    for _, list in ipairs(link.cars) do
      for k = #list, 1, -1 do
        local car = list[k]
        if car then advance(F, car, dt, list, k) end
      end
    end
  end
  serveNodes(F)
  local count = 0
  -- the distance check once a second: a car moves 30 m in it at most
  local keep = fx and F.now - (F.keepAt or -1) >= 1
  local atRed = 0
  if keep then F.keepAt = F.now end
  for _, car in pairs(F.cars) do
    -- the cars standing at lights that are not green, once a second (result.flow.atRed)
    local light = keep and car.v < .5 and car.link.light
    if light and light ~= true and M.colour(light.c.offset, light.axis, F.now) ~= 'green' then atRed = atRed + 1 end
    if car.s >= car.link.len then cross(F, car) end
    if not car.dead then
      if car.wait > WAIT_GIVE_UP then removeCar(F, car, 'gaveUp')
      elseif keep then
        local x, y, _, _, _, hint = M.pose(F, car.link, car.s, car.lane, car.hint)
        car.hint = hint
        if (x - fx) ^ 2 + (y - fy) ^ 2 > KEEP_R * KEEP_R then removeCar(F, car) else count = count + 1 end
      else
        count = count + 1
      end
    end
  end
  if keep then F.atRed = atRed end
  count = count + (F.promoted or 0)
  -- fill up to the target: the first fill anywhere, later ones out of sight; a few a frame (each
  -- new car is a TSStatic, and 200 at once were a 78 ms frame, flow-01)
  local fresh = not F.filled
  local budget = fresh and FILL_PER_STEP or 6
  while count < F.target and budget > 0 do
    budget = budget - 1
    local car = spawnSomewhere(F, fx, fy, fresh and 0 or HIDE_R, SPAWN_R)
    if car then count = count + 1 end
  end
  if count >= F.target then F.filled = true end
  F.count = count
  return count
end

function M.setTarget(F, n)
  F.target = n
  if n == 0 then
    for _, car in pairs(F.cars) do removeCar(F, car) end
    F.filled = false
  end
  local extra = 0
  for _ in pairs(F.cars) do extra = extra + 1 end
  extra = extra - n
  if extra > 0 then
    for _, car in pairs(F.cars) do
      if extra <= 0 then break end
      removeCar(F, car); extra = extra - 1
    end
  end
end

function M.clear(F)
  M.setTarget(F, 0)
  F.links, F.nodes, F.segs, F.grid, F.linkList = {}, {}, {}, {}, nil
end

-- --- the game side: one TSStatic a car ----------------------------------------------------------
-- shapes: list of shape paths by paint. Cars within NEAR_R move every frame, the rest every
-- FAR_EVERY frames (a car at 500 m moves a pixel a frame).
local NEAR_R, FAR_EVERY = 250, 3
-- The rotation of a car shape (forward +x) heading yaw about z, its nose pitch up, as setPosRot
-- takes it. BeamNG's quaternions turn the other way round from the textbook (mathlib.lua
-- LuaVec3:setRotate is v - w t + q x t), so this is the conjugate of Rz(yaw) Ry(-pitch). The
-- textbook one put a car on a diagonal street at -yaw: across its lane, sliding sideways.
function M.quat(yaw, pitch)
  local cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
  local ca, sa = math.cos(-(pitch or 0) / 2), math.sin(-(pitch or 0) / 2)
  return sy * sa, -cy * sa, -sy * ca, cy * ca
end

function M.view(F, shapes, group)
  local V = {objs = {}, frame = 0, shapes = shapes, warm = {}}
  -- one hidden copy of every shape while the flow runs: the first car of a shape no longer
  -- loads it in a driving frame (32 shapes in the first fill were a 261 ms step, flow-08)
  for _, byPaint in ipairs(shapes) do
    for _, path in ipairs(byPaint) do
      local obj = createObject('TSStatic')
      obj:setField('shapeName', 0, path)
      obj:setField('collisionType', 0, 'None')
      obj:setField('decalType', 0, 'None')
      obj.canSave = false
      obj:setPosRot(0, 0, -5000, 0, 0, 0, 1)
      obj:registerObject('')
      obj:setHidden(true)
      if group then group:addObject(obj) end
      V.warm[#V.warm + 1] = obj
    end
  end
  F.onSpawn = function(car)
    local obj = createObject('TSStatic')
    -- shapes[body][paint]
    local byPaint = shapes[car.body or 1] or shapes[1]
    obj:setField('shapeName', 0, byPaint[car.paint] or byPaint[1])
    obj:setField('collisionType', 0, 'None')
    obj:setField('decalType', 0, 'None')
    obj.useInstanceRenderData = true
    obj.canSave = false
    local x, y, z, yaw, pitch = M.pose(F, car.link, car.s, car.lane)
    local qx, qy, qz, qw = M.quat(yaw, pitch)
    obj:setPosRot(x, y, z, qx, qy, qz, qw)
    car.drawnYaw, car.drawnPitch = yaw, pitch
    obj:registerObject('')
    if group then group:addObject(obj) end
    V.objs[car.id] = obj
  end
  F.onRemove = function(car)
    local obj = V.objs[car.id]
    if obj then obj:delete() end
    V.objs[car.id] = nil
  end
  return V
end

function M.draw(F, V, fx, fy)
  V.frame = V.frame + 1
  local moved = 0
  for id, car in pairs(F.cars) do
    local obj = V.objs[id]
    if obj then
      local x, y, z, yaw, pitch, hint = M.pose(F, car.link, car.s, car.lane, car.hint)
      car.hint = hint
      local near = not fx or (x - fx) ^ 2 + (y - fy) ^ 2 < NEAR_R * NEAR_R
      if near or (id + V.frame) % FAR_EVERY == 0 then
        local qx, qy, qz, qw = M.quat(yaw, pitch)
        obj:setPosRot(x, y, z, qx, qy, qz, qw)
        car.drawnYaw, car.drawnPitch = yaw, pitch
        moved = moved + 1
      end
    end
  end
  return moved
end

-- The game test's look at the shapes: for up to n cars, the angle (deg) between the shape's +x as
-- the scene has it and the heading it was last drawn with (a far car is drawn every third frame,
-- and may have turned a corner since), and the same for its nose up. The largest of each
-- (result.flow.poseErr).
function M.poseCheck(F, V, n)
  local worst, nose, seen = 0, 0, 0
  for id, car in pairs(F.cars) do
    local obj = V.objs[id]
    if obj and car.drawnYaw then
      local yaw, pitch = car.drawnYaw, car.drawnPitch
      local ax = obj:getTransform():getColumn(0)
      local h = math.sqrt(ax.x * ax.x + ax.y * ax.y)
      local d = math.abs(math.atan2(ax.y, ax.x) - yaw) % (2 * math.pi)
      worst = math.max(worst, math.deg(math.min(d, 2 * math.pi - d)))
      nose = math.max(nose, math.abs(math.deg(math.atan2(ax.z, h) - (pitch or 0))))
      seen = seen + 1
      if seen >= n then break end
    end
  end
  return worst, nose, seen
end

return M
