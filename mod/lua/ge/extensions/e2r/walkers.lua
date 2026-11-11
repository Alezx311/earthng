-- Pedestrians: walkers on the sidewalks of the navgraph of the loaded tiles (S.nav), as flow.lua
-- drives cars on its lanes. A walker is a plain table; it is drawn as POSES static shapes
-- (earthng/people_art.py), one shown, the pose picked by the distance walked: the game instances
-- static shapes, a skinned or animated one costs ~30 us of the frame each (docs/CROWDS_AND_PACKS.md).
--   - The walk graph: every road slower than MAX_SPEED (no motorways) has a sidewalk line on each
--     side, SIDE_GAP m beyond its edge. The edge is the road's half width or the outer edge of the
--     flow's lanes, whichever is further out (the flow gives a lane 2.6 m at least, so a street
--     tagged with more lanes than its width holds has cars beyond its drawn edge).
--   - A sidewalk is cut wherever it would lie in another road: at a crossing, at the mouth of a
--     side street that joins in the middle of the road (the graph has no node there), beside the
--     other carriageway. What is left are pieces; walkers were run over 12-15 times a minute on the
--     uncut lines (load-06, load-07).
--   - At the end of a piece a walker goes on to an end linked to it (linkEnds): round the corner,
--     straight on across a side street, or square across its own road; with none it turns back.
--   - A leg across a road waits at the kerb while a moving car (a flow car
--     or one with physics) would reach it before the walker is over, WAIT_MAX s at most; walkers on
--     such a leg are W.onRoad, which the flow takes as obstacles (its cars stop for them).
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
local NEW_PER_FRAME = 4   -- walkers given their shapes in a frame: 200 at once were a 204 ms frame (walk-01)
local MAX_DT = .1
local SAMPLE = 2          -- m between the points of a sidewalk line looked at for another road
local PIECE_MIN = 4       -- m: a shorter piece of sidewalk is left out
local CLIP_SLACK = .3     -- m: a sidewalk ends this far inside the crossing road's sidewalk line
local CORNER_R = 3        -- m: sidewalk ends this close are one corner
local LINK_R = 30         -- m: how far an end looks for the end across a road
local BEND_R = 15         -- m: and for the next sidewalk round the outside of a bend
local GRID = 50           -- m: cells of the roads' middle lines
local BOX_PAD = 25        -- m round a road that came or went: the sidewalks there are built again
local Z_APART = 4         -- m: a road this much higher or lower (a bridge) cuts no sidewalk
local CROSS_MARGIN = 2    -- s a car must still be away when the walker has crossed
local WAIT_MAX = 25       -- s at the kerb, then the walker goes (a street that never clears)
M.POSES = 8               -- walk poses; shape POSES + 1 is the standing one (a walker waiting)
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
  return {random = hashRandom(opts.seed), target = 0, slots = {}, segs = {}, roads = {}, list = {}, lengths = {}, length = 0,
    version = 0,
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

-- how far from its middle line a road's cars go: its half width, or the flow's lanes (flow.lua
-- makeLink and laneOffset: a lane is the road's width shared, 2.6..3.8 m)
local function roadEdge(s)
  local half = s[6] or 3.5
  local lanes = tostring(s[4] or '+-')
  local fwd, back = select(2, lanes:gsub('%+', '')), select(2, lanes:gsub('%-', ''))
  local total = fwd + back
  if total == 0 then return half end
  local w = math.max(2.6, math.min(3.8, 2 * half / total))
  -- one way: the lanes lie round the middle line; two ways: each direction on its side
  local reach = (fwd == 0 or back == 0) and total * w / 2 or math.max(fwd, back) * w
  return math.max(half, reach)
end
M.roadEdge = roadEdge

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

local function cellOf(x, y, size)
  return (math.floor(x / size) + 32768) * 65536 + math.floor(y / size) + 32768
end

-- a road's box, BOX_PAD m wider: what a change of this road can cut or link
local function boxOf(s)
  local x0, y0, x1, y1 = math.huge, math.huge, -math.huge, -math.huge
  for k = 8, #s - 2, 3 do
    x0, y0, x1, y1 = math.min(x0, s[k]), math.min(y0, s[k + 1]), math.max(x1, s[k]), math.max(y1, s[k + 1])
  end
  return {x0 - BOX_PAD, y0 - BOX_PAD, x1 + BOX_PAD, y1 + BOX_PAD}
end

-- whether (x, y, z) is where another road's cars go (its lanes and SIDE_GAP beside them): grid
-- holds every road's middle line in pieces {x1, y1, x2, y2, reach, road, z}
-- (inside: m less than that reach: the carriageway alone is SIDE_GAP - CLIP_SLACK inside it)
local function inRoad(grid, x, y, z, own, inside)
  for _, q in ipairs(grid[cellOf(x, y, GRID)] or {}) do
    if q[6] ~= own and math.abs(q[7] - z) < Z_APART then
      local dx, dy = q[3] - q[1], q[4] - q[2]
      local l2 = dx * dx + dy * dy
      local f = l2 > 0 and math.max(0, math.min(1, ((x - q[1]) * dx + (y - q[2]) * dy) / l2)) or 0
      local ex, ey = q[1] + dx * f - x, q[2] + dy * f - y
      local reach = q[5] - (inside or 0)
      if ex * ex + ey * ey < reach * reach then return true end
    end
  end
  return false
end

-- the sidewalks of road s: on each side the pieces of its offset line that lie clear of every other
-- road (a side street's mouth, a crossing road, the other carriageway of an avenue cut it)
local function sidewalks(rec, s, grid)
  local pts = {}
  for k = 8, #s - 2, 3 do pts[#pts + 1], pts[#pts + 2], pts[#pts + 3] = s[k], s[k + 1], s[k + 2] end
  local off = roadEdge(s) + SIDE_GAP
  rec.pieces = {}
  for _, side in ipairs({1, -1}) do
    local line, cum = offsetLine(pts, off * side)
    local len = cum[#cum]
    local n = math.max(1, math.ceil(len / SAMPLE))
    local from, last, hint
    for i = 0, n do
      local d = len * i / n
      local x, y, z, _, _, h = along(line, cum, d, hint)
      hint = h
      local clear = not inRoad(grid, x, y, z, s)
      if clear then
        from, last = from or d, d
      end
      if from and (not clear or i == n) then
        if last - from >= PIECE_MIN then
          local l, c = cutLine(line, cum, from, last)
          rec.pieces[#rec.pieces + 1] = {line = l, cum = c, len = c[#c], rec = rec, side = side, ends = {}}
        end
        from = nil
      end
    end
  end
end

-- Where a walker can go on from each end of each piece (piece.ends[1] at its far end, [-1] at its
-- start): an end within CORNER_R is the same corner (no road between); further, up to LINK_R, a leg
-- across a road, either straight on to a piece that faces this one (the next piece of the same
-- sidewalk beyond a side street) or square across its own road to the other side's end there. The
-- outside of a bend made by two roads end to end leaves their sidewalks a few metres apart with no
-- road between: an end ahead within BEND_R whose leg crosses no carriageway is linked as a corner.
local function linkEnds(W)
  local all, egrid = {}, {}
  for _, piece in ipairs(W.list) do
    for _, e in ipairs({1, -1}) do
      local x, y, z, hx, hy = along(piece.line, piece.cum, e > 0 and piece.len or 0)
      local E = {piece = piece, e = e, x = x, y = y, z = z, ox = hx * e, oy = hy * e, links = {}}
      piece.ends[e] = E
      all[#all + 1] = E
      local key = cellOf(x, y, LINK_R)
      local cell = egrid[key]
      if not cell then cell = {}; egrid[key] = cell end
      cell[#cell + 1] = E
    end
  end
  for _, E in ipairs(all) do
    for gx = -1, 1 do
      for gy = -1, 1 do
        for _, F in ipairs(egrid[cellOf(E.x + gx * LINK_R, E.y + gy * LINK_R, LINK_R)] or {}) do
          if F.piece ~= E.piece and math.abs(F.z - E.z) < Z_APART then
            local dx, dy = F.x - E.x, F.y - E.y
            local d = math.sqrt(dx * dx + dy * dy)
            if d < CORNER_R then
              E.links[#E.links + 1] = {to = F, len = d, weight = 2}
            elseif d < LINK_R then
              local turn = (dx * E.ox + dy * E.oy) / d          -- 1: straight on, 0: square to the side
              local facing = F.ox * E.ox + F.oy * E.oy          -- -1: the pieces face each other
              if turn > .8 and facing < -.5 then
                E.links[#E.links + 1] = {to = F, len = d, weight = 3, cross = true}
              elseif math.abs(turn) < .45 and facing > .5 and F.piece.rec == E.piece.rec and F.piece.side ~= E.piece.side then
                E.links[#E.links + 1] = {to = F, len = d, weight = 1, cross = true}
              elseif d < BEND_R and turn > .5 then
                local clear = true
                for _, f in ipairs({.25, .5, .75}) do
                  if inRoad(W.grid, E.x + dx * f, E.y + dy * f, E.z, nil, SIDE_GAP - CLIP_SLACK) then clear = false end
                end
                if clear then E.links[#E.links + 1] = {to = F, len = d, weight = 2} end
              end
            end
          end
        end
      end
    end
  end
end

-- The roads round (fx, fy): segments = {[sid] = {s = {id, a, b, lanes, speed, half width, drive,
-- x, y, z, ...}, x, y}} (world.lua S.nav). Sidewalks are built for the new roads and built again for
-- those beside a road that came or went (its box). Returns whether anything changed.
function M.sync(W, segments, fx, fy)
  local roads = {}
  for sid, seg in pairs(segments) do
    local s = seg.s or seg
    local mx, my = seg.x or s[8], seg.y or s[9]
    if #s >= 13 and (not fx or (mx - fx) ^ 2 + (my - fy) ^ 2 < (KEEP_R + 300) ^ 2) then roads[sid] = s end
  end
  local boxes = {}
  for sid, s in pairs(W.roads) do if roads[sid] ~= s then boxes[#boxes + 1] = boxOf(s) end end
  for sid, s in pairs(roads) do if W.roads[sid] ~= s then boxes[#boxes + 1] = boxOf(s) end end
  if #boxes == 0 then return false end
  W.roads = roads
  -- every road's middle line (fast roads too: they have no sidewalk but cut the others')
  local grid = {}
  for _, s in pairs(roads) do
    local reach = roadEdge(s) + SIDE_GAP - CLIP_SLACK
    for k = 8, #s - 5, 3 do
      local x1, y1, x2, y2 = s[k], s[k + 1], s[k + 3], s[k + 4]
      local q = {x1, y1, x2, y2, reach, s, (s[k + 2] + s[k + 5]) / 2}
      for gx = math.floor((math.min(x1, x2) - reach) / GRID), math.floor((math.max(x1, x2) + reach) / GRID) do
        for gy = math.floor((math.min(y1, y2) - reach) / GRID), math.floor((math.max(y1, y2) + reach) / GRID) do
          local key = (gx + 32768) * 65536 + gy + 32768
          local cell = grid[key]
          if not cell then cell = {}; grid[key] = cell end
          cell[#cell + 1] = q
        end
      end
    end
  end
  W.grid = grid
  local function touched(box)
    for _, c in ipairs(boxes) do
      if box[1] <= c[3] and box[3] >= c[1] and box[2] <= c[4] and box[4] >= c[2] then return true end
    end
    return false
  end
  local function retire(rec)
    for _, piece in ipairs(rec.pieces) do piece.dead = true end
  end
  for sid, rec in pairs(W.segs) do
    local s = roads[sid]
    if s ~= rec.src or (s[5] or 13) > MAX_SPEED then
      retire(rec)
      W.segs[sid] = nil
    elseif touched(rec.box) then
      retire(rec)
      sidewalks(rec, s, grid)
      W.stats.rebuilt = (W.stats.rebuilt or 0) + 1
    end
  end
  for sid, s in pairs(roads) do
    if not W.segs[sid] and (s[5] or 13) <= MAX_SPEED then
      local rec = {id = sid, src = s, box = boxOf(s)}
      sidewalks(rec, s, grid)
      W.segs[sid] = rec
    end
  end
  -- the pieces in a fixed order (the same walk from the same seed), with their lengths summed for
  -- a spawn point picked by length
  local recs = {}
  for _, rec in pairs(W.segs) do recs[#recs + 1] = rec end
  table.sort(recs, function(a, b) return tostring(a.id) < tostring(b.id) end)
  W.list, W.lengths, W.length = {}, {}, 0
  for _, rec in ipairs(recs) do
    for _, piece in ipairs(rec.pieces) do
      W.length = W.length + piece.len
      W.list[#W.list + 1], W.lengths[#W.lengths + 1] = piece, W.length
    end
  end
  linkEnds(W)
  W.version = W.version + 1
  return true
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
  local x, y, z, hx, hy, hint = along(w.piece.line, w.piece.cum, w.s, w.hint)
  w.x, w.y, w.z, w.hint = x, y, z, hint
  w.hx, w.hy = hx * w.dir, hy * w.dir
end

local function newWalker(W, slot, piece, dir, s)
  local r = W.random
  local w = W.slots[slot]
  w.free, w.taken, w.waiting = nil, nil, nil
  w.piece, w.dir, w.s, w.hint, w.transit = piece, dir, s, nil, nil
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
  w.free, w.piece, w.transit, w.taken, w.waiting = true, nil, nil, nil, nil
  W.stats.removed = W.stats.removed + 1
  if why then W.stats[why] = (W.stats[why] or 0) + 1 end
end

-- a new walker somewhere on the sidewalks between minR and maxR from the focus
local function spawnSomewhere(W, slot, fx, fy, minR, maxR)
  local r = W.random
  local n = #W.list
  if n == 0 then return false end
  for _ = 1, 24 do
    -- a point by length: the piece whose summed length first reaches it
    local at = r() * W.length
    local lo, hi = 1, n
    while lo < hi do
      local mid = math.floor((lo + hi) / 2)
      if W.lengths[mid] < at then lo = mid + 1 else hi = mid end
    end
    local piece = W.list[lo]
    local s = r() * piece.len
    local x, y = along(piece.line, piece.cum, s)
    local d2 = (x - fx) ^ 2 + (y - fy) ^ 2
    if d2 >= minR * minR and d2 <= maxR * maxR then
      newWalker(W, slot, piece, r() < .5 and 1 or -1, s)
      return true
    end
  end
  return false
end

-- the end of a walker's piece reached: on along one of the ends it is linked to (linkEnds), by a
-- straight transit leg; with none (a dead end, a road that ends in a field) back the way it came
local function turnAt(W, w)
  local r = W.random
  local E = w.piece.ends[w.dir]
  local total = 0
  for _, link in ipairs(E.links) do if not link.to.piece.dead then total = total + link.weight end end
  if total == 0 then
    w.dir = -w.dir
    W.stats.turned = W.stats.turned + 1
    return
  end
  local pick, chosen = r() * total, nil
  for _, link in ipairs(E.links) do
    if not link.to.piece.dead then
      pick = pick - link.weight
      chosen = link
      if pick <= 0 then break end
    end
  end
  local F = chosen.to
  -- it comes in at end F.e of that piece and walks away from it
  w.piece, w.dir, w.s, w.hint = F.piece, -F.e, F.e > 0 and F.piece.len or 0, nil
  local dx, dy = F.x - w.x, F.y - w.y
  local len = math.sqrt(dx * dx + dy * dy)
  if len > .2 then
    w.transit = {x0 = w.x, y0 = w.y, z0 = w.z, x1 = F.x, y1 = F.y, z1 = F.z, len = len, s = 0, cross = chosen.cross,
      hx = dx / len, hy = dy / len}
    W.stats.transits = W.stats.transits + 1
  end
end

-- whether a moving car would be on the leg t before a walker at `speed` is over it. cars: lists of
-- {x, y, vx, vy} (vehicles with physics) or of flow cars as drawn ({drawnX, drawnY, drawnYaw, v})
local function carComing(W, t, speed)
  local mx, my = (t.x0 + t.x1) / 2, (t.y0 + t.y1) / 2
  local T = t.len / speed + CROSS_MARGIN
  for _, list in ipairs(W.cars) do
    for _, c in pairs(list) do
      local x, y, vx, vy = c.x, c.y, c.vx, c.vy
      if not x and c.drawnX and c.drawnYaw then
        x, y, vx, vy = c.drawnX, c.drawnY, math.cos(c.drawnYaw) * c.v, math.sin(c.drawnYaw) * c.v
      end
      if x then
        local v = math.sqrt(vx * vx + vy * vy)
        if v > .5 then
          local dx, dy = mx - x, my - y
          local along, side = (dx * vx + dy * vy) / v, math.abs(dx * vy - dy * vx) / v
          if along > -4 and along < v * T + 4 and side < t.len / 2 + 2 then return true end
        end
      end
    end
  end
  return false
end

local function advance(W, w, dt)
  local d = w.speed * dt
  w.walked = w.walked + d
  local guard = 0
  while d > 1e-6 and guard < 4 do
    guard = guard + 1
    if w.transit then
      local t = w.transit
      if t.cross and not t.go then
        -- at the kerb: the look is taken every 0.3 s
        t.waited = (t.waited or 0) + dt
        t.lookAt = (t.lookAt or 0) - dt
        if t.lookAt <= 0 then
          t.lookAt = .3
          if t.waited > WAIT_MAX or not carComing(W, t, w.speed) then t.go = true end
        end
        if not t.go then
          w.walked, w.waiting = w.walked - d, true
          W.stats.waits = (W.stats.waits or 0) + (t.waited == dt and 1 or 0)
          break
        end
        w.waiting = nil
      end
      if t.cross then W.onRoad[#W.onRoad + 1] = w end
      local left = t.len - t.s
      if d < left then t.s = t.s + d; d = 0 else d = d - left; w.transit = nil end
    else
      local target = w.dir > 0 and w.piece.len or 0
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
-- cars: up to two lists of moving cars a walker waits for before it crosses (carComing)
function M.step(W, dt, fx, fy, cars, flowCars)
  dt = math.min(dt or 0, MAX_DT)
  W.cars = {cars or {}, flowCars or {}}
  W.onRoad = {}
  local fill = 0
  for slot = 1, W.target do
    local w = W.slots[slot]
    if not w then
      w = {free = true, slot = slot}
      W.slots[slot] = w
    end
    if not w.free and not w.taken then
      if w.piece.dead and not w.transit then
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
  for q = 0, M.POSES do
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
  local moved, made = 0, 0
  for slot = 1, math.max(W.target, #V.slots) do
    local w = W.slots[slot]
    local objs = V.slots[slot]
    if not w or w.free or w.taken or slot > W.target then
      if objs then hideSlot(objs) end
    else
      if not objs and made < NEW_PER_FRAME then
        made = made + 1
        objs = slotObjects(V, slot)
      end
    end
    if objs and w and not (w.free or w.taken or slot > W.target) then
      if objs.look ~= w.look then
        objs.look = w.look
        local shirt, pants, skin = linear(M.SHIRTS[w.shirt]), linear(M.PANTS[w.pants]), linear(M.SKIN[w.skin])
        for q = 0, M.POSES do
          local o = objs[q]
          pcall(function() o.instanceColor = shirt; o.instanceColor1 = pants; o.instanceColor2 = skin end)
        end
      end
      local near = (w.x - fx) ^ 2 + (w.y - fy) ^ 2 < FAR_R * FAR_R
      if near or (slot + V.frame) % FAR_EVERY == 0 or objs.pose < 0 then
        local pose = w.waiting and M.POSES or math.floor((w.walked % STRIDE) / STRIDE * M.POSES) % M.POSES
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
    for q = 0, M.POSES do if objs[q] then objs[q]:delete() end end
  end
  if V then V.slots = {} end
  W.slots, W.target = {}, 0
end

return M
