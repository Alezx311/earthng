-- Routes over the regions' routing graphs (routing/<region>.bin, earthng/routing_format.py).
-- The game's navgraph covers only NAV_R round the car (world.lua navBuild); this graph covers
-- the pack and carries the same junctions (OSM node ids), so a route found here is handed to the
-- game as navgraph nodes 'e2r_n<id>'. Everything a search touches lives in ffi arrays: the GC
-- never walks them (Lua tables of this size cost frames, native-perf-gc).
local M = {}
local ffi = require('ffi')
local bit = require('bit')
local byte, sub, floor, sqrt, atan2, huge = string.byte, string.sub, math.floor, math.sqrt, math.atan2, math.huge

local MAGIC, VERSION, SCALE = 'EGR1', 1, 10
local CLASSES = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential', 'living_street'}
-- generator.lua SPEED (km/h): an edge without maxspeed
local SPEED = {110, 90, 60, 60, 50, 50, 40, 20}
local LINK, ONEWAY, RING = 8, 16, 32
local TOP_SPEED = 130 / 3.6        -- m/s: keeps the A* heuristic admissible
M.CLASSES, M.LINK, M.ONEWAY, M.RING = CLASSES, LINK, ONEWAY, RING

local function noPause() end

-- --- decoding -------------------------------------------------------------------------------------
-- One region: its nodes (ascending OSM id) and edges, in region-local metres turned to the world
-- by toWorld(x, y). Geometry stays in the file's bytes and is read when a route is drawn.
function M.decode(data, toWorld, pause)
  pause = pause or noPause
  if type(data) ~= 'string' or sub(data, 1, 4) ~= MAGIC then error('not an EarthNG routing file') end
  local pos, last = 5, #data
  local function u()
    local value, mul = 0, 1
    while true do
      if pos > last or mul > 2 ^ 49 then error('truncated routing file') end
      local b = byte(data, pos)
      pos = pos + 1
      if b < 128 then return value + b * mul end
      value, mul = value + (b - 128) * mul, mul * 128
    end
  end
  local function s()
    local v = u()
    if v % 2 == 0 then return v / 2 end
    return -(v + 1) / 2
  end
  if u() ~= VERSION then error('unsupported routing version') end
  -- the names stay in the file's bytes until a route step needs one: 10 k Lua strings made at
  -- once took 101 ms in the game (its 380 MB heap), all of it in one stretch without a pause
  local count = u()
  local strPos, strLen = ffi.new('int32_t[?]', count + 1), ffi.new('int32_t[?]', count + 1)
  for k = 1, count do
    local n = u()
    strPos[k], strLen[k] = pos, n
    pos = pos + n
    if k % 2048 == 0 then pause() end
  end
  local n = u()
  local r = {data = data, strPos = strPos, strLen = strLen, n = n, toWorld = toWorld,
    id = ffi.new('double[?]', n), x = ffi.new('double[?]', n), y = ffi.new('double[?]', n),
    lx = ffi.new('int32_t[?]', n), ly = ffi.new('int32_t[?]', n)}
  local id, qx, qy = 0, 0, 0
  for k = 0, n - 1 do
    id, qx, qy = id + u(), qx + s(), qy + s()
    r.id[k], r.lx[k], r.ly[k] = id, qx, qy
    local wx, wy = qx / SCALE, qy / SCALE
    if toWorld then wx, wy = toWorld(wx, wy) end
    r.x[k], r.y[k] = wx, wy
    if k % 1024 == 0 then pause() end
  end
  local e = u()
  r.e = e
  r.a, r.b = ffi.new('int32_t[?]', e), ffi.new('int32_t[?]', e)
  r.len, r.flags, r.speed = ffi.new('float[?]', e), ffi.new('uint8_t[?]', e), ffi.new('uint8_t[?]', e)
  r.names = ffi.new('int32_t[?]', 4 * e)          -- name, name:uk, name:en, ref (1-based, 0 none)
  r.geo, r.geoN = ffi.new('int32_t[?]', e), ffi.new('int32_t[?]', e)
  local a = 0
  for k = 0, e - 1 do
    a = a + u()
    r.a[k], r.b[k] = a, a + s()
    r.len[k], r.flags[k], r.speed[k] = u() / SCALE, u(), u()
    for f = 0, 3 do r.names[4 * k + f] = u() end
    local count = u()
    r.geo[k], r.geoN[k] = pos, count
    for _ = 1, 2 * count do u() end
    if k % 512 == 0 then pause() end
  end
  if u() ~= 0 or u() ~= 0 or pos ~= last + 1 then error('unexpected routing tail') end
  return r
end

-- --- the merged graph ---------------------------------------------------------------------------
local function findId(r, id)
  local lo, hi = 0, r.n - 1
  while lo <= hi do
    local mid = floor((lo + hi) / 2)
    local v = r.id[mid]
    if v == id then return mid end
    if v < id then lo = mid + 1 else hi = mid - 1 end
  end
end

-- Regions share the nodes on their borders (the same OSM id) and the edges that cross them
-- (stored in both): one node per id, one arc per (from, to, length).
function M.graph(regions, pause)
  pause = pause or noPause
  local g = {regions = regions, n = 0}
  local canon = {}
  for ri, r in ipairs(regions) do
    local map = ffi.new('int32_t[?]', r.n)
    for k = 0, r.n - 1 do
      local found
      for rj = 1, ri - 1 do
        local hit = findId(regions[rj], r.id[k])
        if hit then found = canon[rj][hit]; break end
      end
      if found then map[k] = found else map[k] = g.n; g.n = g.n + 1 end
      if k % 1024 == 0 then pause() end
    end
    canon[ri] = map
  end
  local n, edges = g.n, 0
  for _, r in ipairs(regions) do edges = edges + r.e end
  g.x, g.y, g.id = ffi.new('double[?]', n), ffi.new('double[?]', n), ffi.new('double[?]', n)
  for ri, r in ipairs(regions) do
    for k = 0, r.n - 1 do
      local c = canon[ri][k]
      g.x[c], g.y[c], g.id[c] = r.x[k], r.y[k], r.id[k]
    end
  end
  -- arcs: a -> b always, b -> a unless one-way; counted, then filled (CSR)
  local degree = ffi.new('int32_t[?]', n + 1)
  for ri, r in ipairs(regions) do
    local map = canon[ri]
    for k = 0, r.e - 1 do
      degree[map[r.a[k]]] = degree[map[r.a[k]]] + 1
      if bit.band(r.flags[k], ONEWAY) == 0 then degree[map[r.b[k]]] = degree[map[r.b[k]]] + 1 end
    end
  end
  local first = ffi.new('int32_t[?]', n + 1)
  for k = 0, n - 1 do first[k + 1] = first[k] + degree[k] end
  local arcs = first[n]
  local fill = ffi.new('int32_t[?]', n)
  g.first, g.to, g.cost, g.len = first, ffi.new('int32_t[?]', arcs), ffi.new('float[?]', arcs), ffi.new('float[?]', arcs)
  g.region, g.edge, g.back = ffi.new('uint16_t[?]', arcs), ffi.new('int32_t[?]', arcs), ffi.new('uint8_t[?]', arcs)
  g.from = ffi.new('int32_t[?]', arcs)
  local used = ffi.new('int32_t[?]', n + 1)
  local function add(from, to, ri, k, back, r)
    local length = r.len[k]
    for q = first[from], first[from] + used[from] - 1 do
      if g.to[q] == to and math.abs(g.len[q] - length) < .15 then return end    -- the same edge, from a neighbour
    end
    local q = first[from] + used[from]
    used[from] = used[from] + 1
    local cls = bit.band(r.flags[k], 7) + 1
    local speed = r.speed[k] > 0 and r.speed[k] or SPEED[cls]
    g.to[q], g.from[q], g.len[q], g.cost[q] = to, from, length, length / (speed / 3.6)
    g.region[q], g.edge[q], g.back[q] = ri, k, back and 1 or 0
  end
  for ri, r in ipairs(regions) do
    local map = canon[ri]
    for k = 0, r.e - 1 do
      local a, b = map[r.a[k]], map[r.b[k]]
      add(a, b, ri, k, false, r)
      if bit.band(r.flags[k], ONEWAY) == 0 then add(b, a, ri, k, true, r) end
      if k % 512 == 0 then pause() end
    end
  end
  g.used, g.arcs = used, arcs
  g.stamp, g.search = ffi.new('int32_t[?]', n), 0
  g.dist, g.via, g.done = ffi.new('double[?]', n), ffi.new('int32_t[?]', n), ffi.new('uint8_t[?]', n)
  g.heapCap = 4096
  g.heapF, g.heapN = ffi.new('double[?]', g.heapCap), ffi.new('int32_t[?]', g.heapCap)
  return g
end

-- the node nearest to a world point that has a way out
function M.nearest(g, x, y)
  local best, at = huge, nil
  for k = 0, g.n - 1 do
    if g.used[k] > 0 then
      local dx, dy = g.x[k] - x, g.y[k] - y
      local d = dx * dx + dy * dy
      if d < best then best, at = d, k end
    end
  end
  return at, at and sqrt(best)
end

-- --- search -------------------------------------------------------------------------------------
-- A* on travel time. pause() is the caller's coroutine budget (native.lua active.pause).
function M.search(g, from, to, pause)
  pause = pause or noPause
  g.search = g.search + 1
  local stamp, search, dist, via, done = g.stamp, g.search, g.dist, g.via, g.done
  local first, used, target, cost = g.first, g.used, g.to, g.cost
  local tx, ty, gx, gy = g.x[to], g.y[to], g.x, g.y
  local heapF, heapN, size = g.heapF, g.heapN, 0
  local function push(f, node)
    if size >= g.heapCap then
      local cap = g.heapCap * 2
      local nf, nn = ffi.new('double[?]', cap), ffi.new('int32_t[?]', cap)
      ffi.copy(nf, heapF, 8 * size); ffi.copy(nn, heapN, 4 * size)
      heapF, heapN, g.heapF, g.heapN, g.heapCap = nf, nn, nf, nn, cap
    end
    local k = size
    size = size + 1
    while k > 0 do
      local parent = floor((k - 1) / 2)
      if heapF[parent] <= f then break end
      heapF[k], heapN[k] = heapF[parent], heapN[parent]
      k = parent
    end
    heapF[k], heapN[k] = f, node
  end
  local function pop()
    local node = heapN[0]
    size = size - 1
    local f, last = heapF[size], heapN[size]
    local k = 0
    while true do
      local c = 2 * k + 1
      if c >= size then break end
      if c + 1 < size and heapF[c + 1] < heapF[c] then c = c + 1 end
      if heapF[c] >= f then break end
      heapF[k], heapN[k] = heapF[c], heapN[c]
      k = c
    end
    heapF[k], heapN[k] = f, last
    return node
  end
  local function h(node)
    local dx, dy = gx[node] - tx, gy[node] - ty
    return sqrt(dx * dx + dy * dy) / TOP_SPEED
  end
  stamp[from], dist[from], via[from], done[from] = search, 0, -1, 0
  push(h(from), from)
  local expanded = 0
  while size > 0 do
    local node = pop()
    if done[node] == 0 then
      if node == to then return dist[to], expanded end
      done[node] = 1
      expanded = expanded + 1
      local d = dist[node]
      for q = first[node], first[node] + used[node] - 1 do
        local next = target[q]
        local nd = d + cost[q]
        if stamp[next] ~= search then
          stamp[next], dist[next], via[next], done[next] = search, nd, q, 0
          push(nd + h(next), next)
        elseif done[next] == 0 and nd < dist[next] then
          dist[next], via[next] = nd, q
          push(nd + h(next), next)
        end
      end
      if expanded % 256 == 0 then pause() end
    end
  end
  return nil, expanded
end

-- --- the found route ----------------------------------------------------------------------------
local function text(r, k)
  if k <= 0 then return nil end
  local at = r.strPos[k]
  return sub(r.data, at, at + r.strLen[k] - 1)
end

local function nameOf(r, k, lang)
  local base = 4 * k
  local local_ = lang == 'uk' and r.names[base + 1] or lang == 'en' and r.names[base + 2] or 0
  return text(r, local_ > 0 and local_ or r.names[base]), text(r, r.names[base + 3])
end

-- the inner points of an edge in the world, in the direction it is driven
local function inner(r, k, back)
  local data, pos = r.data, r.geo[k]
  local function u()
    local value, mul = 0, 1
    while true do
      local b = byte(data, pos)
      pos = pos + 1
      if b < 128 then return value + b * mul end
      value, mul = value + (b - 128) * mul, mul * 128
    end
  end
  local out, qx, qy = {}, r.lx[r.a[k]], r.ly[r.a[k]]
  for _ = 1, r.geoN[k] do
    local v = u(); qx = qx + (v % 2 == 0 and v / 2 or -(v + 1) / 2)
    v = u(); qy = qy + (v % 2 == 0 and v / 2 or -(v + 1) / 2)
    local wx, wy = qx / SCALE, qy / SCALE
    if r.toWorld then wx, wy = r.toWorld(wx, wy) end
    out[#out + 1] = {wx, wy}
  end
  if back then
    for i = 1, floor(#out / 2) do out[i], out[#out - i + 1] = out[#out - i + 1], out[i] end
  end
  return out
end

local function heading(ax, ay, bx, by) return atan2(by - ay, bx - ax) end

-- {ids = {'<osm id>', ...}, at = {m along the route at each id}, points = {x1, y1, ...},
-- length = m, time = s, steps = {...}}
-- A step is a junction where the way turns (> TURN degrees) or the name changes:
-- {at = m from the start, turn = degrees (+ left), name = .., ref = .., ring = bool}.
local TURN = 35
function M.route(g, from, to, lang, pause)
  local time = M.search(g, from, to, pause)
  if not time then return nil end
  local arcs = {}
  local node = to
  while node ~= from do
    local q = g.via[node]
    arcs[#arcs + 1] = q
    node = g.from[q]
    if #arcs > g.n then error('routing: broken path') end
  end
  local out = {ids = {}, at = {0}, points = {}, length = 0, time = time, steps = {}}
  local function point(x, y)
    local p = out.points
    p[#p + 1], p[#p + 2] = x, y
  end
  local fromNode = from
  out.ids[1] = string.format('%.0f', g.id[from])
  point(g.x[from], g.y[from])
  local lastHeading, lastName
  for i = #arcs, 1, -1 do
    local q = arcs[i]
    local r, k, back = g.regions[g.region[q]], g.edge[q], g.back[q] == 1
    local toNode = g.to[q]
    local bends = inner(r, k, back)
    local fx, fy = g.x[fromNode], g.y[fromNode]
    local first = bends[1] or {g.x[toNode], g.y[toNode]}
    local inHeading = heading(fx, fy, first[1], first[2])
    local name, ref = nameOf(r, k, lang)
    if lastHeading then
      local turn = math.deg(inHeading - lastHeading)
      turn = (turn + 540) % 360 - 180
      local junction = g.used[fromNode] > 2 or (g.used[fromNode] == 2 and bit.band(r.flags[k], ONEWAY) ~= 0)
      if junction and (math.abs(turn) > TURN or name ~= lastName) then
        out.steps[#out.steps + 1] = {at = out.length, turn = turn, name = name, ref = ref,
          ring = bit.band(r.flags[k], RING) ~= 0, node = out.ids[#out.ids]}
      end
    end
    for _, p in ipairs(bends) do point(p[1], p[2]) end
    point(g.x[toNode], g.y[toNode])
    out.length = out.length + g.len[q]
    out.ids[#out.ids + 1] = string.format('%.0f', g.id[toNode])
    out.at[#out.at + 1] = out.length
    local lastP = bends[#bends] or {fx, fy}
    lastHeading = heading(lastP[1], lastP[2], g.x[toNode], g.y[toNode])
    lastName = name
    fromNode = toNode
  end
  return out
end

return M
