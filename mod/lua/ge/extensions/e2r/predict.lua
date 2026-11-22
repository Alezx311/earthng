-- Where the car can be in the next seconds: native.lua wants the tiles these
-- points fall in, and nothing else round the car but a small bubble. The points run along the
-- roads the renderer already has (world.lua S.nav: the segments of the loaded tiles) from the
-- car's own road in its direction of travel, branching at every junction; the planned route, when
-- there is one, comes first. Each point carries its cost: metres along the road times the weight
-- of the turns taken to get there (straight on 1, a turn TURN), so a tile the car reaches sooner
-- and more surely ranks first. Past the last known road the path goes on straight for EXTEND m
-- (or the `extend` the caller gives: a fast car reads further than the roads it has): the next
-- tile's roads are not loaded yet, but the road itself does not end at the tile's edge.
-- Pure Lua over plain tables: earthng/test_predict.py runs it in lupa.
local M = {}

M.SNAP = 30          -- m: the car farther than this from every road is off-road (its heading only)
M.STEP = 40          -- m between path points (a 500 m tile gets at least a dozen)
M.TURN = 1.6         -- weight of a turn at a junction (straight on: 1); a U-turn is never taken
M.STRAIGHT = .7      -- cos of the angle within which a way out counts as straight on
M.EXTEND = 400       -- m straight on past a road's loose end
M.MAX_POINTS = 2000  -- points of one call at most (a dense grid branches fast)

local sqrt, floor, min, max, huge = math.sqrt, math.floor, math.min, math.max, math.huge

-- The segments by their end nodes. segments: world.lua S.nav ({[id] = {s = {id, a, b, lanes,
-- speed, radius, drive, x, y, z, ...}, box = {x0, y0, x1, y1}}}).
function M.index(segments)
  local ends, list = {}, {}
  for _, seg in pairs(segments) do
    local s = seg.s
    if type(s) == 'table' and #s >= 13 then
      list[#list + 1] = seg
      local a, b = s[2], s[3]
      ends[a] = ends[a] or {}
      ends[a][#ends[a] + 1] = seg
      ends[b] = ends[b] or {}
      ends[b][#ends[b] + 1] = seg
    end
  end
  return {ends = ends, list = list}
end

-- may a car drive this segment from a to b (dir 1) or from b to a (dir -1): the lanes string has
-- '+' lanes a -> b and '-' lanes b -> a (fast.nav_segments); none given, both ways
local function allowed(s, dir)
  local lanes = s[4]
  if type(lanes) ~= 'string' or lanes == '' then return true end
  return lanes:find(dir > 0 and '+' or '-', 1, true) ~= nil
end

-- the car's road: the segment piece nearest (x, y) within SNAP, and the direction along it that
-- agrees with the heading (ux, uy); without a heading both directions
local function snap(index, x, y, ux, uy)
  local best, bestScore
  for _, seg in ipairs(index.list) do
    local box = seg.box
    if not box or (x >= box[1] - M.SNAP and x <= box[3] + M.SNAP and y >= box[2] - M.SNAP and y <= box[4] + M.SNAP) then
      local s = seg.s
      for k = 8, #s - 5, 3 do
        local ax, ay, bx, by = s[k], s[k + 1], s[k + 3], s[k + 4]
        local dx, dy = bx - ax, by - ay
        local l2 = dx * dx + dy * dy
        local f = l2 > 1e-6 and max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / l2)) or 0
        local ex, ey = ax + f * dx - x, ay + f * dy - y
        local d = sqrt(ex * ex + ey * ey)
        if d <= M.SNAP then
          local l = sqrt(l2)
          local cos = l > 1e-3 and (dx * ux + dy * uy) / l or 0
          -- a road across the heading at the same distance loses to the one along it
          local score = d + 15 * (1 - math.abs(cos))
          if not bestScore or score < bestScore then
            best, bestScore = {seg = seg, k = k, f = f, cos = cos}, score
          end
        end
      end
    end
  end
  return best
end

-- A point into out (x, y, cost triples); false once the call's budget of points is spent.
local function emit(out, state, x, y, cost)
  if state.points >= M.MAX_POINTS then return false end
  out[#out + 1], out[#out + 2], out[#out + 3] = x, y, cost
  state.points = state.points + 1
  return true
end

-- From (x, y) to (nx, ny), d m along the road at (x, y): a point at every multiple of STEP
-- (nextAt is the next one). Returns d and nextAt at (nx, ny), or nil when the walk ends here.
local function piece(out, state, x, y, nx, ny, d, nextAt, weight)
  local dx, dy = nx - x, ny - y
  local l = sqrt(dx * dx + dy * dy)
  if l < 1e-3 then return d, nextAt end
  while nextAt <= d + l do
    if nextAt * weight > state.length then return nil end
    local t = nextAt - d
    if not emit(out, state, x + dx / l * t, y + dy / l * t, nextAt * weight) then return nil end
    nextAt = nextAt + M.STEP
  end
  return d + l, nextAt
end

-- straight on from (x, y) along (ux, uy) for len m (a loose end)
local function extend(out, state, x, y, ux, uy, d, nextAt, weight, len)
  piece(out, state, x, y, x + ux * len, y + uy * len, d, nextAt, weight)
end

local walk

-- the ways on from node, arriving along (ux, uy): straight on keeps the weight, a turn costs TURN
local function junction(out, state, index, node, from, x, y, ux, uy, d, nextAt, weight)
  local outs, bestCos = {}, nil
  for _, seg in ipairs(index.ends[node] or {}) do
    if seg ~= from then
      local s = seg.s
      local dir = s[2] == node and 1 or -1
      if allowed(s, dir) then
        local k = dir > 0 and 8 or #s - 2         -- the node's own point
        local dx, dy = s[k + 3 * dir] - s[k], s[k + 1 + 3 * dir] - s[k + 1]
        local l = sqrt(dx * dx + dy * dy)
        local cos = l > 1e-3 and (dx * ux + dy * uy) / l or 1
        if cos > -M.STRAIGHT then
          outs[#outs + 1] = {seg = seg, dir = dir, cos = cos}
          if not bestCos or cos > bestCos then bestCos = cos end
        end
      end
    end
  end
  if #outs == 0 then
    extend(out, state, x, y, ux, uy, d, nextAt, weight, max(0, min(state.extend, state.length / weight - d)))
    return
  end
  for _, o in ipairs(outs) do
    local w = (o.cos >= M.STRAIGHT and o.cos >= bestCos - 1e-6) and weight or weight * M.TURN
    local k = o.dir > 0 and 8 or #o.seg.s - 2
    walk(out, state, index, o.seg, o.dir, o.seg.s[k], o.seg.s[k + 1], k + 3 * o.dir, d, nextAt, w)
  end
end

-- Along seg in dir (1: towards its node s[3]) from (x, y), heading for its point at index `to`;
-- d m along the road at (x, y). A (segment, direction) entered at a lower cost already is not
-- walked again.
walk = function(out, state, index, seg, dir, x, y, to, d, nextAt, weight)
  local slot = state.seen[seg]
  if not slot then slot = {}; state.seen[seg] = slot end
  local cost = d * weight
  if slot[dir] and slot[dir] <= cost + 1 then return end
  slot[dir] = cost
  local s = seg.s
  local last = #s - 2
  local ux, uy = 0, 0
  local k = to
  while k >= 8 and k <= last do
    local nx, ny = s[k], s[k + 1]
    local l = sqrt((nx - x) ^ 2 + (ny - y) ^ 2)
    if l > 1e-3 then ux, uy = (nx - x) / l, (ny - y) / l end
    d, nextAt = piece(out, state, x, y, nx, ny, d, nextAt, weight)
    if not d then return end
    x, y = nx, ny
    k = k + 3 * dir
  end
  if d * weight >= state.length then return end
  junction(out, state, index, dir > 0 and s[3] or s[2], seg, x, y, ux, uy, d, nextAt, weight)
end

-- The points ahead of a car at (x, y) moving along (ux, uy) (a unit vector, or 0, 0 when it
-- stands), up to a cost of `length` (m of road straight on; a turned branch ends sooner, so a
-- city grid does not branch without end). index: M.index of the renderer's segments, or nil.
-- straight: m straight on past a road's loose end (EXTEND when not given).
-- Returns a flat array {x, y, cost, ...} and whether the car is on a known road.
function M.ahead(index, x, y, ux, uy, length, straight)
  local out = {x, y, 0}
  local state = {points = 1, seen = {}, length = length, extend = straight or M.EXTEND}
  local hit = index and snap(index, x, y, ux, uy)
  local moving = ux ~= 0 or uy ~= 0
  if not hit then
    if moving then extend(out, state, x, y, ux, uy, 0, M.STEP, 1, length) end
    return out, false
  end
  local s, k, f = hit.seg.s, hit.k, hit.f
  local px, py = s[k] + (s[k + 3] - s[k]) * f, s[k + 1] + (s[k + 4] - s[k + 1]) * f
  if not moving or hit.cos >= 0 then walk(out, state, index, hit.seg, 1, px, py, k + 3, 0, M.STEP, 1) end
  if not moving or hit.cos < 0 then
    -- the same segment the other way: a fresh entry, not the one just walked
    state.seen[hit.seg] = state.seen[hit.seg] and {[1] = state.seen[hit.seg][1]} or nil
    walk(out, state, index, hit.seg, -1, px, py, k, 0, M.STEP, 1)
  end
  return out, true
end

-- A route's next `length` m as points (the navigator's or the autopilot's line): pts is a flat
-- {x, y, x, y, ...} array, from the point nearest the car on.
function M.along(pts, x, y, length)
  local out = {}
  local n = floor(#pts / 2)
  if n < 2 then return out end
  local best, at, atF = huge, 1, 0
  for k = 1, n - 1 do
    local ax, ay, bx, by = pts[2 * k - 1], pts[2 * k], pts[2 * k + 1], pts[2 * k + 2]
    local dx, dy = bx - ax, by - ay
    local l2 = dx * dx + dy * dy
    local f = l2 > 1e-6 and max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / l2)) or 0
    local ex, ey = ax + f * dx - x, ay + f * dy - y
    local d = ex * ex + ey * ey
    if d < best then best, at, atF = d, k, f end
  end
  local px, py = pts[2 * at - 1] + (pts[2 * at + 1] - pts[2 * at - 1]) * atF,
    pts[2 * at] + (pts[2 * at + 2] - pts[2 * at]) * atF
  local d, carry = 0, 0
  out[1], out[2], out[3] = px, py, 0
  for k = at + 1, n do
    local nx, ny = pts[2 * k - 1], pts[2 * k]
    local dx, dy = nx - px, ny - py
    local l = sqrt(dx * dx + dy * dy)
    if l > 1e-3 then
      local t = M.STEP - carry
      while t <= l do
        if d + t > length then return out end
        out[#out + 1], out[#out + 2], out[#out + 3] = px + dx / l * t, py + dy / l * t, d + t
        t = t + M.STEP
      end
      carry = l - (t - M.STEP)
      d = d + l
      px, py = nx, ny
    end
  end
  return out
end

return M
