-- Pedestrians: walkers on the sidewalks of the navgraph of the loaded tiles (S.nav), as flow.lua
-- drives cars on its lanes. A walker is a plain table; it is drawn as POSES static shapes
-- (earthng/people_art.py), one shown, the pose picked by the distance walked: the game instances
-- static shapes, a skinned or animated one costs ~30 us of the frame each (docs/CROWDS_AND_PACKS.md).
--   - The walk graph: every road slower than MAX_SPEED (no motorways) has a sidewalk line on each
--     side the tile drew one (the nav segment's walk flags, generator.lua WALK), SIDE_GAP m beyond
--     its edge; a village or yard street with none is walked VERGE_GAP m past its edge. The edge is
--     the road's half width or the outer edge of the flow's lanes, whichever is further out (the
--     flow gives a lane 2.6 m at least, so a street tagged with more lanes than its width holds has
--     cars beyond its drawn edge). Without flags (an older graph, a test) every side has one.
--   - The side of a one-way carriageway that faces the other way's within MEDIAN_R is a median:
--     no walk there whatever the flags say (walkers strolled between the carriageways of divided
--     roads out of town, 18.11).
--   - The mapped paths (footways, paths, pedestrian streets, steps) and the driveways of built-up
--     places (generator WALK.lines) are walked too: a path on its middle, a driveway just inside
--     both edges, each stopping PATH_CLEAR past a street's carriageway. A path's end or the crossing
--     of two paths splits every walk line within JOIN_R there (joints), so a walker on a sidewalk
--     can turn into a yard path at its mouth and back.
--   - Places to stop (generator WALK.spots, the scene's walkSpots): a walker passing one may go to
--     it, sit on a bench, wait at a bus stop, watch a playground, look at a kiosk, or go in at a door
--     (hidden a while, then out the same door), and walks back to where it left its way (SPOT).
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
--     Where the game has DynamicShapeBatch a walker is one copy in the batch of its pose and skin
--     instead (batchDraw, shapebatch.lua): the shirt is the copy's colour, the skin and trousers
--     baked materials put in by remaps, the trousers following the skin (BATCH_PANTS). A new pose
--     is another batch; the previous copy stays through the next frame so the step does not blank.
--   - Up to M.MAX walkers. How many walk is the count asked, or fewer where there is little
--     sidewalk: one per SPACING m of weighted sidewalk round the focus (M.counts). A sidewalk's
--     weight is how many roads lie round it (WEIGHT_*): a lone road through fields gets few people,
--     a city block many; motorways and fast roads none.
--   - Cost by distance (1000 walkers, docs/CROWDS_AND_PACKS.md): within EVERY_R a walker moves and
--     is drawn every frame, further every floor(d / RING) frames (PERIOD_MAX at most), unseen beyond
--     DRAW_R every HIDDEN_PERIOD frames; a skipped walker walks the time it missed at its next turn.
--   - Shapes by distance: within NEAR_R a walker has its own set of SHAPES shapes (one shown, the
--     pose swapped as it walks; NEAR_SETS sets at most), to DRAW_R one shape (FAR_POSE), beyond none.
--     Sets and shapes go back to pools and are repainted for the next walker, so the scene holds
--     ~1.5 objects a walker instead of 9.
--   - No garbage while walking: transit legs, lists and the cell grid of walkers (M.near) are
--     tables reused in place; colours are made once per palette entry.
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
local MAX_DT = .1
local MAX_ACC = .5        -- s walked in one turn at most (a walker far away moves every few frames)
local EVERY_R = 40        -- m: moved and drawn every frame within
local RING = 20           -- m: further, every floor(d / RING) frames...
local PERIOD_MAX = 10     -- ...at most this many
local HIDDEN_PERIOD = 20  -- frames between the turns of a walker beyond DRAW_R (not drawn)
local NEAR_R, NEAR_OUT = 60, 70     -- m: posed within NEAR_R, back to one shape beyond NEAR_OUT
local DRAW_R, DRAW_OUT = 200, 215   -- m: one shape within DRAW_R, none beyond DRAW_OUT
local SOLID_R, SOLID_OUT = 38, 46   -- m: a figure's copy within is a solid one (shapebatch.lua: it casts a shadow)
local NEAR_SETS = 96      -- posed walkers at most (SHAPES objects each)
local FAR_POSE = 0        -- the shape of a walker between NEAR_R and DRAW_R (left leg mid swing)
local MAKE_PER_FRAME = 10 -- objects created in a frame: 200 walkers' 1800 at once were a 204 ms frame (walk-01)
local TRIM_PER_FRAME = 10 -- spare objects deleted in a frame (one posed set)...
local SPARE_FAR, SPARE_SETS, TRIM_AFTER = 48, 6, 180   -- ...beyond these, 180 frames after the last was needed
local CELL = 32           -- m: cells of the walkers' grid (M.near)
local SPACING = 3.5       -- m of weighted sidewalk round the focus per walker at most (Kyiv centre ~1000)
local WEIGHT_R = 2        -- cells of the roads' grid (GRID m) each way round a piece counted for its weight
local WEIGHT_FULL, WEIGHT_MIN = 20, .05   -- roads round a piece for the full weight; the least weight
local CAND_EVERY = 30     -- frames between the refreshes of the spawn pieces and the capacity
local JUMP = 500          -- m the focus moved in a step: a teleport (the next fill may start in sight)
M.MAX = 1000
local EMPTY = {}         -- a list with nothing in it (no new table per miss)
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
local WAIT_HIDDEN = 2     -- s at the kerb of a walker beyond DRAW_R (no look for cars)
local VERGE_GAP = .8      -- m beyond the edge: where people walk a village street that has no sidewalk
local MEDIAN_R = 35       -- m: a one-way side facing the other way's carriageway this near is a median
local MEDIAN_EVERY = 10   -- m of sidewalk between two looks for a median
local PATH_CLEAR = .4     -- m beyond a carriageway's edge: where a path or a driveway stops at a street
local PATH_MIN = 1        -- m: a shorter piece of path is left out
local JOIN_R = 2.5        -- m: a path's end or crossing this near a walk line splits it there
local JCELL = 20          -- m: cells of the joints and of the paths' segments
local SPLIT_MIN = .5      -- m: a split this near a piece's end or another split is not made
local SPLIT_W = 4         -- weight of walking on through a split (a turn into the path there is 2)
local SCELL = 25          -- m: cells of the pieces' segments when places to stop are attached
-- places to stop (generator WALK.spots): reach, m from the walk; chance of a walker passing going
-- there; stay, s; cap, walkers at once; sit (the seated pose), inside (hidden: gone in at a door),
-- here (stood at from the walk itself, facing it), front / outside: the walk must lie in front of
-- the seat / outside the door (not through its own building)
M.SPOT = {
  bench = {reach = 12, chance = .35, stay = {25, 100}, cap = 2, sit = true, front = true},
  stop = {reach = 12, chance = .45, stay = {30, 140}, cap = 6},
  door = {reach = 25, chance = .12, stay = {20, 120}, cap = 99, inside = true, outside = true},
  play = {reach = 20, chance = .3, stay = {20, 90}, cap = 4},
  look = {reach = 8, chance = .15, stay = {3, 10}, cap = 2, here = true},
}
-- where the walkers of a place stand, m across its facing (a bench's two seats, a stop's queue)
local SEATS = {bench = {-.45, .45}, stop = {0, -1.5, 1.5, -3, 3, .8}, play = {0, -2, 2, -4}, look = {0, .7}, door = {}}
local REST = {40, 120}    -- s after a visit before the next
local SPAWN_SPOT = .3     -- of the new walkers on a piece with places to stop start at one
M.POSES = 8               -- walk poses; shape POSES + 1 is the standing one (a walker waiting)
M.STAND, M.SIT = M.POSES, M.POSES + 1   -- the standing and the seated pose (0-based)
M.SHAPES = M.POSES + 2    -- shapes a posed walker has: the walk, standing, seated
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

-- W = M.new{seed = n, spacing = m of weighted sidewalk per walker (0: no cap; default SPACING)}
function M.new(opts)
  opts = opts or {}
  return {random = hashRandom(opts.seed), target = 0, slots = {}, segs = {}, roads = {}, list = {}, lengths = {}, length = 0,
    grid = {}, gridOf = {}, paths = {}, psegs = {}, pgrid = {}, jgrid = {}, flagsOf = {}, spotLists = {}, spotsOf = {},
    version = 0, count = 0, cap = M.MAX, frame = 0, clock = 0, vx = 0, vy = 0,
    cars = {}, onRoad = {}, onRoadN = 0, cells = {}, cellPool = {}, cand = {}, candCum = {}, candN = 0, candTotal = 0,
    candAt = 0, candVersion = -1, spacing = opts.spacing, staying = 0, inside = 0,
    stats = {spawned = 0, removed = 0, transits = 0, turned = 0,
      visit = {bench = 0, stop = 0, door = 0, play = 0, look = 0}}}
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

-- the walkers' grid: every walking walker is in the list of its CELL m cell (M.near), lists reused
local function cellAdd(W, w)
  local key = cellOf(w.x, w.y, CELL)
  local list = W.cells[key]
  if not list then
    local pool = W.cellPool
    list = pool[#pool]
    if list then pool[#pool] = nil else list = {n = 0} end
    W.cells[key] = list
  end
  local n = list.n + 1
  list.n, list[n] = n, w
  w.cell, w.ci = key, n
end

local function cellDrop(W, w)
  local key = w.cell
  local list = key and W.cells[key]
  w.cell = nil
  if not list then return end
  local n = list.n
  local last = list[n]
  list[w.ci], last.ci = last, w.ci
  list[n], list.n = nil, n - 1
  if n == 1 then
    W.cells[key] = nil
    W.cellPool[#W.cellPool + 1] = list
  end
end

local function cellMove(W, w)
  if cellOf(w.x, w.y, CELL) ~= w.cell then
    cellDrop(W, w)
    cellAdd(W, w)
  end
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
  for _, q in ipairs(grid[cellOf(x, y, GRID)] or EMPTY) do
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

-- --- joints: where a walk line is split (a path's end, two paths crossing) -----------------------
-- W.jgrid: JCELL m cells of {x, y, z, self}; rec.joints lists a line's own (taken out with it).
-- self: the line whose end it is (it does not split that line); nil for a crossing (splits both).
local function jointAdd(W, rec, x, y, z, self)
  local J = {x, y, z, self}
  local key = cellOf(x, y, JCELL)
  local cell = W.jgrid[key]
  if not cell then cell = {}; W.jgrid[key] = cell end
  cell[#cell + 1] = J
  rec.joints = rec.joints or {}
  rec.joints[#rec.joints + 1] = J
end

local function jointsDrop(W, rec)
  for _, J in ipairs(rec.joints or EMPTY) do
    local key = cellOf(J[1], J[2], JCELL)
    local cell = W.jgrid[key]
    if cell then
      for k = #cell, 1, -1 do
        if cell[k] == J then cell[k] = cell[#cell]; cell[#cell] = nil; break end
      end
      if #cell == 0 then W.jgrid[key] = nil end
    end
  end
  rec.joints = nil
end

-- the pieces of line from s0 to s1 (a stretch clear of other roads) into rec.pieces, split at the
-- joints within JOIN_R of it: each piece knows which of its ends is a split (piece.split[e])
local function addPieces(W, rec, side, line, cum, s0, s1)
  local cuts
  local n = #cum
  -- the line's points in the stretch, and their box grown by JOIN_R
  local x0, y0, x1, y1 = math.huge, math.huge, -math.huge, -math.huge
  local k0, k1 = n, 1
  for k = 1, n do
    if cum[k] >= s0 - JOIN_R and cum[k] <= s1 + JOIN_R then
      local j = 3 * (k - 1) + 1
      x0, y0, x1, y1 = math.min(x0, line[j]), math.min(y0, line[j + 1]), math.max(x1, line[j]), math.max(y1, line[j + 1])
      k0, k1 = math.min(k0, k), math.max(k1, k)
    end
  end
  k0, k1 = math.max(1, k0 - 1), math.min(n, k1 + 1)
  if x0 <= x1 then
    for gx = math.floor((x0 - JOIN_R) / JCELL), math.floor((x1 + JOIN_R) / JCELL) do
      for gy = math.floor((y0 - JOIN_R) / JCELL), math.floor((y1 + JOIN_R) / JCELL) do
        for _, J in ipairs(W.jgrid[(gx + 32768) * 65536 + gy + 32768] or EMPTY) do
          if J[4] ~= rec and math.abs(J[3] - line[3 * (k0 - 1) + 3]) < Z_APART then
            -- the nearest point of the stretch
            local best, at = JOIN_R * JOIN_R, nil
            for k = k0, k1 - 1 do
              local j = 3 * (k - 1) + 1
              local dx, dy = line[j + 3] - line[j], line[j + 4] - line[j + 1]
              local l2 = dx * dx + dy * dy
              local f = l2 > 1e-9 and math.max(0, math.min(1, ((J[1] - line[j]) * dx + (J[2] - line[j + 1]) * dy) / l2)) or 0
              local d2 = (line[j] + dx * f - J[1]) ^ 2 + (line[j + 1] + dy * f - J[2]) ^ 2
              if d2 < best then best, at = d2, cum[k] + (cum[k + 1] - cum[k]) * f end
            end
            if at and at > s0 + SPLIT_MIN and at < s1 - SPLIT_MIN then
              cuts = cuts or {}
              cuts[#cuts + 1] = at
            end
          end
        end
      end
    end
  end
  if cuts then table.sort(cuts) end
  local from, headSplit = s0, false
  for c = 1, (cuts and #cuts or 0) + 1 do
    local to = cuts and cuts[c] or s1
    if to - from >= SPLIT_MIN or to == s1 then
      local tail = cuts and cuts[c] ~= nil
      local l, cc = cutLine(line, cum, from, to)
      local bx0, by0, bx1, by1 = math.huge, math.huge, -math.huge, -math.huge
      for k = 1, #l - 2, 3 do
        bx0, by0, bx1, by1 = math.min(bx0, l[k]), math.min(by0, l[k + 1]), math.max(bx1, l[k]), math.max(by1, l[k + 1])
      end
      rec.pieces[#rec.pieces + 1] = {line = l, cum = cc, len = cc[#cc], rec = rec, side = side, ends = {},
        x0 = bx0, y0 = by0, x1 = bx1, y1 = by1, weight = 1, split = {[-1] = headSplit, [1] = tail}}
      from, headSplit = to, true
    end
  end
end

-- which line a sidewalk sample is on: 1 the sidewalk, 2 the verge, 0 none, from the tile's flags at
-- u (0..1 along the road): '1' a sidewalk, 'v' a verge, anything else none; no flags: a sidewalk
local function flagAt(flags, u)
  if not flags then return 1 end
  local n = #flags
  if n == 0 then return 0 end
  local ch = flags:byte(math.max(1, math.min(n, math.floor(u * n) + 1)))
  return ch == 49 and 1 or ch == 118 and 2 or 0
end

local function oneWay(s) return not tostring(s[4] or '+-'):find('-', 1, true) end

-- whether side `side` of one-way road s at (x, y) (heading hx, hy) faces a one-way carriageway
-- going the other way within MEDIAN_R: a divided road's median
local function median(grid, s, x, y, z, hx, hy, side)
  -- offsetLine puts a positive offset to the right of the heading: (hy, -hx)
  local nx, ny = hy * side, -hx * side
  for gx = math.floor((x - MEDIAN_R) / GRID), math.floor((x + MEDIAN_R) / GRID) do
    for gy = math.floor((y - MEDIAN_R) / GRID), math.floor((y + MEDIAN_R) / GRID) do
      for _, q in ipairs(grid[(gx + 32768) * 65536 + gy + 32768] or EMPTY) do
        local o = q[6]
        if o ~= s and math.abs(q[7] - z) < Z_APART then
          local dx, dy = q[3] - q[1], q[4] - q[2]
          local l2 = dx * dx + dy * dy
          if l2 > 1e-6 and (dx * hx + dy * hy) < -.8 * math.sqrt(l2) and oneWay(o) then
            local f = math.max(0, math.min(1, ((x - q[1]) * dx + (y - q[2]) * dy) / l2))
            local ex, ey = q[1] + dx * f - x, q[2] + dy * f - y
            local lateral = ex * nx + ey * ny
            if lateral > 0 and lateral < MEDIAN_R and math.abs(ex * hx + ey * hy) < 20 then return true end
          end
        end
      end
    end
  end
  return false
end

-- the sidewalks of road s: on each side the pieces of its offset line that lie clear of every other
-- road (a side street's mouth, a crossing road, the other carriageway of an avenue cut it), where
-- the tile drew a sidewalk (the verge line where it says a verge), split at the joints
local function sidewalks(W, rec, s, grid)
  local pts = {}
  for k = 8, #s - 2, 3 do pts[#pts + 1], pts[#pts + 2], pts[#pts + 3] = s[k], s[k + 1], s[k + 2] end
  local edge = roadEdge(s)
  rec.pieces = {}
  local flags, divided = s.walk, oneWay(s)
  for _, side in ipairs({1, -1}) do
    -- side 1 is the right of the road's direction: the flags' second string
    local f = flags and flags[side == 1 and 2 or 1]
    -- [1] the sidewalk line, [2] the verge's. A bridge or tunnel names the outer edge of its deck
    -- (navSegment.deck): a line past it would hang in the air beside a deck with no pavement.
    local lines, base = {}, nil
    for kind = 1, 2 do
      local off = edge + (kind == 1 and SIDE_GAP or VERGE_GAP)
      if not (s.deck and off > s.deck - .2) then
        local line, cum = offsetLine(pts, off * side)
        lines[kind] = {line = line, cum = cum, len = cum[#cum]}
        base = base or lines[kind]
      end
    end
    if base then
      local n = math.max(1, math.ceil(base.len / SAMPLE))
      local runKind, from, last = 0, 0, 0
      local hints, medianAt, isMedian = {}, -1e9, false
      for i = 0, n + 1 do
        local u = i / n
        local kind = i <= n and flagAt(f, u) or 0
        local L = lines[kind]
        local clear = false
        if L then
          local x, y, z, hx, hy, h = along(L.line, L.cum, L.len * u, hints[kind])
          hints[kind] = h
          clear = not inRoad(grid, x, y, z, s)
          if clear and divided then
            if math.abs(base.len * u - medianAt) >= MEDIAN_EVERY then
              medianAt, isMedian = base.len * u, median(grid, s, x, y, z, hx, hy, side)
            end
            clear = not isMedian
          end
        end
        if not clear then kind = 0 end
        if kind ~= runKind then
          -- the run of one line ends: its stretch becomes pieces
          local R = lines[runKind]
          if R and (last - from) * R.len >= PIECE_MIN then addPieces(W, rec, side, R.line, R.cum, from * R.len, last * R.len) end
          runKind, from = kind, u
        end
        last = u
      end
    end
  end
end

-- the segments of the walk lines (W.pgrid, JCELL m cells of {x1, y1, x2, y2, rec, z}): the paths
-- crossing each other are found there
local function pgridAdd(W, rec)
  local entries = {}
  for _, L in ipairs(rec.lines) do
    local l = L.line
    for k = 1, #l - 5, 3 do
      local q = {l[k], l[k + 1], l[k + 3], l[k + 4], rec, (l[k + 2] + l[k + 5]) / 2}
      for gx = math.floor(math.min(q[1], q[3]) / JCELL), math.floor(math.max(q[1], q[3]) / JCELL) do
        for gy = math.floor(math.min(q[2], q[4]) / JCELL), math.floor(math.max(q[2], q[4]) / JCELL) do
          local key = (gx + 32768) * 65536 + gy + 32768
          local cell = W.pgrid[key]
          if not cell then cell = {}; W.pgrid[key] = cell end
          cell[#cell + 1] = q
          entries[#entries + 1], entries[#entries + 2] = key, q
        end
      end
    end
  end
  rec.pentries = entries
end

local function pgridDrop(W, rec)
  local entries = rec.pentries
  if not entries then return end
  for i = 1, #entries, 2 do
    local key, q = entries[i], entries[i + 1]
    local cell = W.pgrid[key]
    if cell then
      for j = #cell, 1, -1 do
        if cell[j] == q then cell[j] = cell[#cell]; cell[#cell] = nil; break end
      end
      if #cell == 0 then W.pgrid[key] = nil end
    end
  end
  rec.pentries = nil
end

-- A walk line's stretches (rec.lines: {line, cum, side, ranges}): a path's middle line, or a line
-- just inside each edge of a driveway, cut where a street's carriageway is (PATH_CLEAR past its
-- edge). The ends of the stretches are joints: a sidewalk or another path there is split for them.
local function pathStretches(W, rec, s, grid)
  local pts = {}
  for k = 8, #s - 2, 3 do pts[#pts + 1], pts[#pts + 2], pts[#pts + 3] = s[k], s[k + 1], s[k + 2] end
  local hw = s[6] or 1
  local offs = (s[2] == 's' and hw >= 1.6) and {hw - .5, .5 - hw} or {0}
  local inside = SIDE_GAP - CLIP_SLACK - PATH_CLEAR
  rec.lines = {}
  for k, off in ipairs(offs) do
    local line, cum = offsetLine(pts, off)
    local len = cum[#cum]
    local n = math.max(1, math.ceil(len / SAMPLE))
    local ranges, from, last, hint = {}, nil, nil, nil
    for i = 0, n do
      local d = len * i / n
      local x, y, z, _, _, h = along(line, cum, d, hint)
      hint = h
      local clear = not inRoad(grid, x, y, z, nil, inside)
      if clear then from, last = from or d, d end
      if from and (not clear or i == n) then
        if last - from >= PATH_MIN then
          ranges[#ranges + 1], ranges[#ranges + 2] = from, last
          for _, e in ipairs({from, last}) do
            local ex, ey, ez = along(line, cum, e)
            jointAdd(W, rec, ex, ey, ez, rec)
          end
        end
        from = nil
      end
    end
    rec.lines[k] = {line = line, cum = cum, side = k == 1 and 1 or -1, ranges = ranges}
  end
end

-- the crossings of rec's lines with the other walk lines (W.pgrid): a joint each, splitting both
local function pathCrossings(W, rec)
  for _, L in ipairs(rec.lines) do
    local l = L.line
    for k = 1, #l - 5, 3 do
      local ax, ay, bx, by = l[k], l[k + 1], l[k + 3], l[k + 4]
      local z = (l[k + 2] + l[k + 5]) / 2
      for gx = math.floor(math.min(ax, bx) / JCELL), math.floor(math.max(ax, bx) / JCELL) do
        for gy = math.floor(math.min(ay, by) / JCELL), math.floor(math.max(ay, by) / JCELL) do
          for _, q in ipairs(W.pgrid[(gx + 32768) * 65536 + gy + 32768] or EMPTY) do
            if q[5] ~= rec and math.abs(q[6] - z) < Z_APART then
              -- segments a-b and c-d: a + t (b - a) = c + u (d - c)
              local rx, ry, sx, sy = bx - ax, by - ay, q[3] - q[1], q[4] - q[2]
              local den = rx * sy - ry * sx
              if math.abs(den) > 1e-9 then
                local t = ((q[1] - ax) * sy - (q[2] - ay) * sx) / den
                local u = ((q[1] - ax) * ry - (q[2] - ay) * rx) / den
                if t >= 0 and t <= 1 and u >= 0 and u <= 1 then jointAdd(W, rec, ax + rx * t, ay + ry * t, z, nil) end
              end
            end
          end
        end
      end
    end
  end
end

-- boxes {x0, y0, x1, y1} grown by pad, listed by the TOUCH m cells they cover (what a change reaches)
local TOUCH = 100
local function boxIndex(boxes, pad)
  local idx = {}
  for _, b in ipairs(boxes) do
    local c = {b[1] - pad, b[2] - pad, b[3] + pad, b[4] + pad}
    for gx = math.floor(c[1] / TOUCH), math.floor(c[3] / TOUCH) do
      for gy = math.floor(c[2] / TOUCH), math.floor(c[4] / TOUCH) do
        local key = (gx + 32768) * 65536 + gy + 32768
        local list = idx[key]
        if not list then list = {}; idx[key] = list end
        list[#list + 1] = c
      end
    end
  end
  return idx
end

-- whether the box x0..x1, y0..y1 meets one of the boxes of idx
local function touches(idx, x0, y0, x1, y1)
  for gx = math.floor(x0 / TOUCH), math.floor(x1 / TOUCH) do
    for gy = math.floor(y0 / TOUCH), math.floor(y1 / TOUCH) do
      local list = idx[(gx + 32768) * 65536 + gy + 32768]
      if list then
        for _, c in ipairs(list) do
          if x0 <= c[3] and x1 >= c[1] and y0 <= c[4] and y1 >= c[2] then return true end
        end
      end
    end
  end
  return false
end

-- Where a walker can go on from each end of each piece (piece.ends[1] at its far end, [-1] at its
-- start): an end within CORNER_R is the same corner (no road between); further, up to LINK_R, a leg
-- across a road, either straight on to a piece that faces this one (the next piece of the same
-- sidewalk beyond a side street) or square across its own road to the other side's end there. The
-- outside of a bend made by two roads end to end leaves their sidewalks a few metres apart with no
-- road between: an end ahead within BEND_R whose leg crosses no carriageway is linked as a corner.
-- near (an index of boxIndex): only the pieces there (and new ones) are linked again, against every
-- end in reach; nil: every piece. The new ends replace the old
-- ones at the end, so a walker turning meanwhile still finds whole links.
local function linkEnds(W, list, near, pause)
  local egrid, pending, wanted = {}, {}, {}
  local function put(E)
    local key = cellOf(E.x, E.y, LINK_R)
    local cell = egrid[key]
    if not cell then cell = {}; egrid[key] = cell end
    cell[#cell + 1] = E
  end
  -- the ends linked again: new pieces and those near the change; the cells round them are wanted
  for k, piece in ipairs(list) do
    if pause and k % 128 == 0 then pause() end
    if not piece.ends[1] or not near or touches(near, piece.x0, piece.y0, piece.x1, piece.y1) then
      piece.relink = true
      for e = -1, 1, 2 do
        local x, y, z, hx, hy = along(piece.line, piece.cum, e > 0 and piece.len or 0)
        local E = {piece = piece, e = e, x = x, y = y, z = z, ox = hx * e, oy = hy * e, links = {},
          split = piece.split and piece.split[e] or nil}
        pending[#pending + 1] = E
        put(E)
        local gx, gy = math.floor(x / LINK_R), math.floor(y / LINK_R)
        for dx = -1, 1 do for dy = -1, 1 do wanted[(gx + dx + 32768) * 65536 + gy + dy + 32768] = true end end
      end
    end
  end
  -- the ends kept that lie in reach of those
  for k, piece in ipairs(list) do
    if pause and k % 256 == 0 then pause() end
    if piece.relink then
      piece.relink = nil
    else
      for e = -1, 1, 2 do
        local E = piece.ends[e]
        if wanted[cellOf(E.x, E.y, LINK_R)] then put(E) end
      end
    end
  end
  for k, E in ipairs(pending) do
    if pause and k % 32 == 0 then pause() end
    for gx = -1, 1 do
      for gy = -1, 1 do
        for _, F in ipairs(egrid[cellOf(E.x + gx * LINK_R, E.y + gy * LINK_R, LINK_R)] or EMPTY) do
          if F.piece ~= E.piece and math.abs(F.z - E.z) < Z_APART then
            local dx, dy = F.x - E.x, F.y - E.y
            local d = math.sqrt(dx * dx + dy * dy)
            if d < CORNER_R then
              -- on through a split of the same line is likelier than a turn into the path there
              local through = E.split and F.split and d < .2 and F.piece.rec == E.piece.rec and F.piece.side == E.piece.side
              E.links[#E.links + 1] = {to = F, len = d, weight = through and SPLIT_W or 2}
            elseif d < LINK_R then
              local turn = (dx * E.ox + dy * E.oy) / d          -- 1: straight on, 0: square to the side
              local facing = F.ox * E.ox + F.oy * E.oy          -- -1: the pieces face each other
              if turn > .8 and facing < -.5 then
                E.links[#E.links + 1] = {to = F, len = d, weight = 3, cross = true}
              elseif math.abs(turn) < .45 and facing > .5 and F.piece.rec == E.piece.rec and F.piece.side ~= E.piece.side then
                E.links[#E.links + 1] = {to = F, len = d, weight = 1, cross = true}
              elseif d < BEND_R and turn > .5 then
                local clear = true
                for f = .25, .75, .25 do
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
  for _, E in ipairs(pending) do E.piece.ends[E.e] = E end
end

-- the roads' grid (W.grid, GRID m cells of {x1, y1, x2, y2, reach, road, z}) kept from sync to
-- sync: a road that came is added, one that went is taken out (W.gridOf: its cells and pieces)
local function gridAdd(W, s)
  local grid, entries = W.grid, {}
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
        entries[#entries + 1], entries[#entries + 2] = key, q
      end
    end
  end
  W.gridOf[s] = entries
end

local function gridDrop(W, s)
  local grid, entries = W.grid, W.gridOf[s]
  if not entries then return end
  for i = 1, #entries, 2 do
    local key, q = entries[i], entries[i + 1]
    local cell = grid[key]
    if cell then
      local n = #cell
      for j = n, 1, -1 do
        if cell[j] == q then cell[j] = cell[n]; cell[n] = nil; break end
      end
      if #cell == 0 then grid[key] = nil end
    end
  end
  W.gridOf[s] = nil
end

-- a piece's weight: the roads within WEIGHT_R cells of its middle (a block of streets or one road)
local function weigh(W, piece)
  W.markStamp = (W.markStamp or 0) + 1
  local stamp, mark, grid = W.markStamp, W.mark, W.grid
  local gx0, gy0 = math.floor((piece.x0 + piece.x1) / 2 / GRID), math.floor((piece.y0 + piece.y1) / 2 / GRID)
  local roadsNear = 0
  for gx = gx0 - WEIGHT_R, gx0 + WEIGHT_R do
    for gy = gy0 - WEIGHT_R, gy0 + WEIGHT_R do
      for _, q in ipairs(grid[(gx + 32768) * 65536 + gy + 32768] or EMPTY) do
        if mark[q[6]] ~= stamp then mark[q[6]] = stamp; roadsNear = roadsNear + 1 end
      end
    end
  end
  -- squared: a village (5-6 roads round) gets a tenth of a city block's people per metre
  piece.weight = math.max(WEIGHT_MIN, math.min(1, (roadsNear - 1) / WEIGHT_FULL) ^ 2)
end

-- --- places to stop ----------------------------------------------------------------------------
-- The spots of the scenes (generator WALK.spots: {kind, x, y, z, hx, hy} lists by tile), each
-- attached to the nearest point of a piece within its reach (M.SPOT): spot.piece, spot.s and the
-- tap point (tx, ty, tz) where a walker leaves its way; piece.spots lists them by s.
local function spotDetach(sp)
  local piece = sp.piece
  local list = piece and piece.spots
  if list then
    for k = #list, 1, -1 do
      if list[k] == sp then table.remove(list, k); break end
    end
    if #list == 0 then piece.spots = nil end
  end
  sp.piece = nil
end

-- the spots of lists that came, gone for those that went; returns whether any did
local function spotLists(W, lists)
  local any = false
  for key, list in pairs(W.spotLists) do
    if not lists or lists[key] ~= list then
      for _, sp in ipairs(W.spotsOf[key] or EMPTY) do spotDetach(sp); sp.dead = true end
      W.spotLists[key], W.spotsOf[key], any = nil, nil, true
    end
  end
  for key, list in pairs(lists or EMPTY) do
    if W.spotLists[key] ~= list then
      local spots = {}
      for _, e in ipairs(list) do
        local def = M.SPOT[e[1]]
        if def and e[2] and e[3] then
          local hx, hy = e[5] or 0, e[6] or 0
          local l = math.sqrt(hx * hx + hy * hy)
          if l > 1e-6 then hx, hy = hx / l, hy / l else hx, hy = 0, 0 end
          spots[#spots + 1] = {kind = e[1], def = def, x = e[2], y = e[3], z = e[4] or 0, hx = hx, hy = hy, users = 0, seat = {}}
        end
      end
      W.spotLists[key], W.spotsOf[key], any = list, spots, true
    end
  end
  return any
end

-- attach the spots that need it: new ones, those whose piece went, those round a change (near, an
-- index of boxIndex; nil: none but those). A spot nothing reaches stays unattached (piece false)
-- until a change near it.
local function spotsAttach(W, near, pause)
  local todo = {}
  for _, spots in pairs(W.spotsOf) do
    for _, sp in ipairs(spots) do
      if sp.piece == nil or (sp.piece and sp.piece.dead) or (near and touches(near, sp.x, sp.y, sp.x, sp.y)) then
        todo[#todo + 1] = sp
      end
    end
  end
  if #todo == 0 then return end
  -- the cells round them, then the pieces' segments in those cells
  local wanted, cells = {}, {}
  for _, sp in ipairs(todo) do
    local r = sp.def.reach
    for gx = math.floor((sp.x - r) / SCELL), math.floor((sp.x + r) / SCELL) do
      for gy = math.floor((sp.y - r) / SCELL), math.floor((sp.y + r) / SCELL) do
        wanted[(gx + 32768) * 65536 + gy + 32768] = true
      end
    end
  end
  for k, piece in ipairs(W.list) do
    if pause and k % 256 == 0 then pause() end
    local l, c = piece.line, piece.cum
    for j = 1, #c - 1 do
      local i = 3 * (j - 1) + 1
      for gx = math.floor(math.min(l[i], l[i + 3]) / SCELL), math.floor(math.max(l[i], l[i + 3]) / SCELL) do
        for gy = math.floor(math.min(l[i + 1], l[i + 4]) / SCELL), math.floor(math.max(l[i + 1], l[i + 4]) / SCELL) do
          local key = (gx + 32768) * 65536 + gy + 32768
          if wanted[key] then
            local cell = cells[key]
            if not cell then cell = {}; cells[key] = cell end
            cell[#cell + 1], cell[#cell + 2] = piece, j
          end
        end
      end
    end
  end
  local inside = SIDE_GAP - CLIP_SLACK - PATH_CLEAR
  for n, sp in ipairs(todo) do
    if pause and n % 64 == 0 then pause() end
    spotDetach(sp)
    local def, r = sp.def, sp.def.reach
    local best, bp, bs, bx, by, bz = r * r, nil, 0, 0, 0, 0
    for gx = math.floor((sp.x - r) / SCELL), math.floor((sp.x + r) / SCELL) do
      for gy = math.floor((sp.y - r) / SCELL), math.floor((sp.y + r) / SCELL) do
        local cell = cells[(gx + 32768) * 65536 + gy + 32768]
        for q = 1, cell and #cell or 0, 2 do
          local piece, j = cell[q], cell[q + 1]
          local l, c = piece.line, piece.cum
          local i = 3 * (j - 1) + 1
          local dx, dy = l[i + 3] - l[i], l[i + 4] - l[i + 1]
          local l2 = dx * dx + dy * dy
          local f = l2 > 1e-9 and math.max(0, math.min(1, ((sp.x - l[i]) * dx + (sp.y - l[i + 1]) * dy) / l2)) or 0
          local x, y = l[i] + dx * f, l[i + 1] + dy * f
          local d2 = (x - sp.x) ^ 2 + (y - sp.y) ^ 2
          local z = l[i + 2] + (l[i + 5] - l[i + 2]) * f
          if d2 < best and math.abs(z - sp.z) < Z_APART then
            local ox, oy = x - sp.x, y - sp.y
            local ok = true
            -- a door is reached from outside its wall, a seat from before it
            if def.outside and ox * sp.hx + oy * sp.hy > .5 then ok = false end
            if def.front and ox * sp.hx + oy * sp.hy < -.3 then ok = false end
            -- the way there crosses no carriageway
            if ok and not def.here then
              for t = .25, .75, .25 do
                if inRoad(W.grid, sp.x + ox * t, sp.y + oy * t, sp.z, nil, inside) then ok = false; break end
              end
            end
            if ok then best, bp, bs, bx, by, bz = d2, piece, c[j] + (c[j + 1] - c[j]) * f, x, y, z end
          end
        end
      end
    end
    if bp then
      sp.piece, sp.s, sp.tx, sp.ty, sp.tz = bp, bs, bx, by, bz
      local list = bp.spots
      if not list then list = {}; bp.spots = list end
      local at = #list + 1
      while at > 1 and list[at - 1].s > bs do at = at - 1 end
      table.insert(list, at, sp)
    else
      sp.piece = false
    end
  end
end

-- what the walk is made of now, for the result: path pieces, places to stop and those reached
local function tally(W)
  local pieces, spots, on = 0, 0, 0
  for _, rec in pairs(W.psegs) do pieces = pieces + #rec.pieces end
  for _, list in pairs(W.spotsOf) do
    for _, sp in ipairs(list) do
      spots = spots + 1
      if sp.piece then on = on + 1 end
    end
  end
  W.stats.pathPieces, W.stats.spots, W.stats.spotsOn = pieces, spots, on
end

-- The roads round (fx, fy): segments = {[sid] = {s = {id, a, b, lanes, speed, half width, drive,
-- x, y, z, ...}, x, y}} (world.lua S.nav; s.walk: the tile's sidewalk flags, generator WALK).
-- walks: the paths and driveways ({[id] = {s = {id, kind, 0, 0, 0, half width, 0, x, y, z, ...}}},
-- world.lua S.walks); spots: the places to stop by tile ({[key] = list}). Sidewalks and paths are
-- built for what is new and built again round what came or went (its box); ends are linked again
-- round them, spots attached again. Returns whether anything changed. pause (optional) is called
-- every few roads and pieces: world.lua runs this in a coroutine whose pause yields when the
-- frame's budget is spent. The walkers walk on meanwhile: the list of pieces and the new ends
-- replace the old ones at the end.
function M.sync(W, segments, fx, fy, pause, walks, spots)
  local keep2 = (KEEP_R + 300) ^ 2
  local roads, paths, flagsOf = {}, {}, {}
  for sid, seg in pairs(segments) do
    local s = seg.s or seg
    local mx, my = seg.x or s[8], seg.y or s[9]
    if #s >= 13 and (not fx or (mx - fx) ^ 2 + (my - fy) ^ 2 < keep2) then roads[sid], flagsOf[sid] = s, s.walk or false end
  end
  for id, wl in pairs(walks or EMPTY) do
    local s = wl.s or wl
    local mx, my = wl.x or s[8], wl.y or s[9]
    if #s >= 13 and (not fx or (mx - fx) ^ 2 + (my - fy) ^ 2 < keep2) then paths[id] = s end
  end
  local old, oldPaths, oldFlags = W.roads, W.paths, W.flagsOf
  local boxes = {}
  for sid, s in pairs(old) do if roads[sid] ~= s then boxes[#boxes + 1] = boxOf(s) end end
  for sid, s in pairs(roads) do
    -- a road that came, or whose flags another tile filled in (world.lua navRead)
    if old[sid] ~= s or oldFlags[sid] ~= flagsOf[sid] then boxes[#boxes + 1] = boxOf(s) end
  end
  for id, s in pairs(oldPaths) do if paths[id] ~= s then boxes[#boxes + 1] = boxOf(s) end end
  for id, s in pairs(paths) do if oldPaths[id] ~= s then boxes[#boxes + 1] = boxOf(s) end end
  local spotsChanged = spotLists(W, spots)
  if #boxes == 0 then
    if spotsChanged then spotsAttach(W, nil, pause); tally(W) end
    return spotsChanged
  end
  W.roads, W.paths, W.flagsOf = roads, paths, flagsOf
  W.mark = {}
  -- every road's middle line (fast roads too: they have no sidewalk but cut the others')
  for sid, s in pairs(old) do if roads[sid] ~= s then gridDrop(W, s) end end
  local n = 0
  for sid, s in pairs(roads) do
    if old[sid] ~= s then
      gridAdd(W, s)
      n = n + 1
      if pause and n % 16 == 0 then pause() end
    end
  end
  local changed = boxIndex(boxes, 0)
  local built = {}     -- boxes of the lines whose pieces are new: their ends and those round them link again
  for _, b in ipairs(boxes) do built[#built + 1] = b end
  local grid = W.grid
  -- the walk lines first: their stretches and joints split the sidewalks built after them
  local again = {}
  for id, rec in pairs(W.psegs) do
    local s = paths[id]
    if s ~= rec.src then
      for _, piece in ipairs(rec.pieces) do piece.dead = true end
      jointsDrop(W, rec)
      pgridDrop(W, rec)
      W.psegs[id] = nil
    elseif touches(changed, rec.box[1], rec.box[2], rec.box[3], rec.box[4]) then
      again[#again + 1] = rec
    end
  end
  for id, s in pairs(paths) do
    if not W.psegs[id] then
      local rec = {id = id, key = 'w' .. tostring(id), src = s, box = boxOf(s), pieces = {}}
      W.psegs[id] = rec
      again[#again + 1] = rec
    end
  end
  table.sort(again, function(a, b) return a.key < b.key end)
  for k, rec in ipairs(again) do
    jointsDrop(W, rec)
    pgridDrop(W, rec)
    pathStretches(W, rec, rec.src, grid)
    pgridAdd(W, rec)
    if pause and k % 16 == 0 then pause() end
  end
  for k, rec in ipairs(again) do
    pathCrossings(W, rec)
    if pause and k % 16 == 0 then pause() end
  end
  for k, rec in ipairs(again) do
    for _, piece in ipairs(rec.pieces) do piece.dead = true end
    rec.pieces = {}
    for _, L in ipairs(rec.lines) do
      local r = L.ranges
      for i = 1, #r - 1, 2 do addPieces(W, rec, L.side, L.line, L.cum, r[i], r[i + 1]) end
    end
    for _, piece in ipairs(rec.pieces) do weigh(W, piece) end
    built[#built + 1] = rec.box
    if pause and k % 8 == 0 then pause() end
  end
  for sid, rec in pairs(W.segs) do
    local s = roads[sid]
    if s ~= rec.src or (s[5] or 13) > MAX_SPEED then
      for _, piece in ipairs(rec.pieces) do piece.dead = true end
      W.segs[sid] = nil
    elseif touches(changed, rec.box[1], rec.box[2], rec.box[3], rec.box[4]) then
      for _, piece in ipairs(rec.pieces) do piece.dead = true end
      sidewalks(W, rec, s, grid)
      for _, piece in ipairs(rec.pieces) do weigh(W, piece) end
      built[#built + 1] = rec.box
      W.stats.rebuilt = (W.stats.rebuilt or 0) + 1
      if pause then pause() end
    end
  end
  for sid, s in pairs(roads) do
    if not W.segs[sid] and (s[5] or 13) <= MAX_SPEED then
      local rec = {id = sid, key = tostring(sid), src = s, box = boxOf(s)}
      sidewalks(W, rec, s, grid)
      for _, piece in ipairs(rec.pieces) do weigh(W, piece) end
      W.segs[sid] = rec
      built[#built + 1] = rec.box
      if pause then pause() end
    end
  end
  -- the pieces in a fixed order (the same walk from the same seed), with their lengths summed
  local recs = {}
  for _, rec in pairs(W.segs) do recs[#recs + 1] = rec end
  for _, rec in pairs(W.psegs) do recs[#recs + 1] = rec end
  table.sort(recs, function(a, b) return a.key < b.key end)
  local list, lengths, length = {}, {}, 0
  for _, rec in ipairs(recs) do
    for _, piece in ipairs(rec.pieces) do
      length = length + piece.len
      list[#list + 1], lengths[#lengths + 1] = piece, length
    end
  end
  if pause then pause() end
  linkEnds(W, list, boxIndex(built, LINK_R), pause)
  W.list, W.lengths, W.length = list, lengths, length
  spotsAttach(W, boxIndex(built, 25), pause)
  tally(W)
  W.version = W.version + 1
  return true
end

-- where a walker is now: x, y, z (the road's surface), heading hx, hy
local function place(w)
  if w.stay then
    -- at a place to stop: where it stands there, facing the way the place does
    w.x, w.y, w.z, w.hx, w.hy = w.sx, w.sy, w.sz, w.shx, w.shy
    return
  end
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
  -- the view repaints a shape whose look changed (numbered over all walkers: shapes move between them)
  W.lookSeq = (W.lookSeq or 0) + 1
  w.look = W.lookSeq
  w.gz, w.gzAt = nil, nil
  w.visit, w.stay, w.inside, w.seat, w.held = nil, nil, nil, nil, nil
  -- a new walker passes a place or two before it stops at one (no draw: the walk of a seed stays)
  w.restAt = W.clock + 8 + (slot * 7) % 13
  w.at, w.dirty = W.clock, true
  place(w)
  cellAdd(W, w)
  W.count = W.count + 1
  W.stats.spawned = W.stats.spawned + 1
  return w
end

-- the walker leaves its place to stop: its seat and its count there are free again
local function leaveSpot(W, w)
  local sp = w.visit
  if w.held and sp then
    sp.users = sp.users - 1
    if w.seat and sp.seat[w.seat] == w then sp.seat[w.seat] = nil end
  end
  if w.stay then W.staying = W.staying - 1 end
  if w.inside then W.inside = W.inside - 1 end
  w.held, w.seat, w.stay, w.inside = nil, nil, nil, nil
end

local function freeSlot(W, w, why)
  if w.free then return end
  if w.visit then leaveSpot(W, w); w.visit = nil end
  cellDrop(W, w)
  w.free, w.piece, w.transit, w.taken, w.waiting = true, nil, nil, nil, nil
  W.count = W.count - 1
  W.stats.removed = W.stats.removed + 1
  if why then W.stats[why] = (W.stats[why] or 0) + 1 end
end

-- a walker's leg table with every field it will hold (filled again at each corner: no rehash).
-- visit: 0 a corner or a crossing, 1 the way to a place to stop, 3 the way back from it
local function newLeg()
  return {x0 = 0, y0 = 0, z0 = 0, x1 = 0, y1 = 0, z1 = 0, len = 0, s = 0, cross = false, hx = 1, hy = 0, go = false,
    waited = 0, lookAt = 0, visit = 0}
end

-- the walker's leg from where it is to (x, y, z), its own table filled again; false when it is there
local function legTo(w, x, y, z, visit)
  local dx, dy = x - w.x, y - w.y
  local len = math.sqrt(dx * dx + dy * dy)
  if len <= .2 then return false end
  local t = w.tr
  if not t then t = newLeg(); w.tr = t end
  t.x0, t.y0, t.z0, t.x1, t.y1, t.z1, t.len, t.s = w.x, w.y, w.z, x, y, z, len, 0
  t.cross, t.hx, t.hy, t.go, t.waited, t.lookAt, t.visit = false, dx / len, dy / len, true, 0, 0, visit
  w.transit = t
  return true
end

-- at the place: it sits, stands or goes in for its stay
local function arrive(W, w)
  local sp, r = w.visit, W.random
  local def = sp.def
  w.transit, w.stay = nil, true
  w.stayLeft = def.stay[1] + r() * (def.stay[2] - def.stay[1])
  w.sit = def.sit or nil
  W.staying = W.staying + 1
  if def.inside then w.inside = true; W.inside = W.inside + 1 end
  w.waiting = nil
  place(w)
end

-- A walker at the tap point of place sp (on its piece at sp.s) goes there: a seat that is free, a
-- place in the queue; false when the place is full. here: stood at from the walk, facing it.
local function startVisit(W, w, sp)
  local def = sp.def
  if sp.users >= def.cap then return false end
  local seats = SEATS[sp.kind] or EMPTY
  local seat
  for i = 1, #seats do
    if not sp.seat[i] then seat = i; break end
  end
  if #seats > 0 and not seat then return false end
  if seat then sp.seat[seat] = w end
  sp.users = sp.users + 1
  w.visit, w.seat, w.held = sp, seat, true
  W.stats.visit[sp.kind] = (W.stats.visit[sp.kind] or 0) + 1
  if def.here then
    -- where it stands on its way, beside the one before it by the seat's offset, facing the place
    local dx, dy = sp.x - w.x, sp.y - w.y
    local l = math.sqrt(dx * dx + dy * dy)
    local o = (seat and seats[seat] or 0) / math.max(l, 1e-6)
    w.sx, w.sy, w.sz = w.x + o * dy, w.y - o * dx, w.z
    if l > 1e-3 then w.shx, w.shy = dx / l, dy / l else w.shx, w.shy = w.hx, w.hy end
  else
    -- across its facing by the seat's offset
    local o = seat and seats[seat] or 0
    w.sx, w.sy, w.sz = sp.x - sp.hy * o, sp.y + sp.hx * o, sp.z
    w.shx, w.shy = sp.hx, sp.hy
    if w.shx == 0 and w.shy == 0 then w.shx, w.shy = w.hx, w.hy end
  end
  if not legTo(w, w.sx, w.sy, w.sz, 1) then arrive(W, w) end
  return true
end

-- the stay is over: out of the door, up from the bench, and back to where it left its way
local function endStay(W, w)
  local sp = w.visit
  leaveSpot(W, w)
  -- its piece rebuilt meanwhile: the place's new one
  if w.piece.dead and sp.piece and not sp.piece.dead then w.piece, w.s, w.hint = sp.piece, sp.s, nil end
  local x, y, z = along(w.piece.line, w.piece.cum, w.s)
  if not legTo(w, x, y, z, 3) then w.visit = nil end
  w.restAt = W.clock + REST[1] + W.random() * (REST[2] - REST[1])
end

-- the first place to stop on the walker's piece ahead of it within reach m (piece.spots by s)
local function spotAhead(w, reach)
  local list = w.piece.spots
  local best, bd = nil, reach
  for k = 1, list and #list or 0 do
    local sp = list[k]
    local ahead = (sp.s - w.s) * w.dir
    if ahead > .01 and ahead <= bd and not sp.dead then best, bd = sp, ahead end
  end
  return best, bd
end

-- The pieces a walker may appear on (their box within SPAWN_R of the focus), with their weighted
-- lengths summed, and the capacity: one walker per SPACING m of weighted sidewalk within KEEP_R.
-- Arrays reused; every CAND_EVERY frames and after a sync.
local function refreshCandidates(W, fx, fy)
  W.candAt, W.candVersion = W.frame + CAND_EVERY, W.version
  local cand, cum = W.cand, W.candCum
  local n, total, room = 0, 0, 0
  local keep2, spawn2 = KEEP_R * KEEP_R, SPAWN_R * SPAWN_R
  local list = W.list
  for k = 1, #list do
    local piece = list[k]
    local dx = math.max(piece.x0 - fx, 0, fx - piece.x1)
    local dy = math.max(piece.y0 - fy, 0, fy - piece.y1)
    local d2 = dx * dx + dy * dy
    if d2 < keep2 then
      -- a long piece counts only for the part that can lie within the circle
      local weighted = math.min(piece.len, 2 * KEEP_R) * piece.weight
      room = room + weighted
      if d2 < spawn2 then
        n = n + 1
        total = total + weighted
        cand[n], cum[n] = piece, total
      end
    end
  end
  for k = n + 1, W.candN do cand[k], cum[k] = nil, nil end
  W.candN, W.candTotal, W.room = n, total, room
  local spacing = W.spacing or SPACING
  W.cap = spacing > 0 and math.min(M.MAX, math.floor(room / spacing)) or M.MAX
end

-- a new walker somewhere on the sidewalks between minR and maxR from the focus; while the focus
-- moves, the first tries keep to the half ahead of it (walkers are recycled ahead of the car)
local function spawnSomewhere(W, slot, fx, fy, minR, maxR)
  local r = W.random
  local n = W.candN
  if n == 0 then return false end
  local cum, cand = W.candCum, W.cand
  local vx, vy = W.vx, W.vy
  local ahead = vx * vx + vy * vy > 9
  for try = 1, 10 do
    -- a point by weighted length: the piece whose summed length first reaches it
    local at = r() * W.candTotal
    local lo, hi = 1, n
    while lo < hi do
      local mid = math.floor((lo + hi) / 2)
      if cum[mid] < at then lo = mid + 1 else hi = mid end
    end
    local piece = cand[lo]
    local s = r() * piece.len
    local x, y = along(piece.line, piece.cum, s)
    local dx, dy = x - fx, y - fy
    local d2 = dx * dx + dy * dy
    -- (a piece retired by a sync still running is left out)
    if not piece.dead and d2 >= minR * minR and d2 <= maxR * maxR and not (ahead and try <= 6 and dx * vx + dy * vy < 0) then
      local spots = piece.spots
      local sp = spots and r() < SPAWN_SPOT and spots[r(1, #spots)]
      if sp and not sp.dead and sp.users < sp.def.cap then s = sp.s else sp = nil end
      local w = newWalker(W, slot, piece, r() < .5 and 1 or -1, s)
      -- some start at a place to stop, part of their stay gone (a door's: still inside)
      if sp and startVisit(W, w, sp) then
        if not w.stay then arrive(W, w) end
        w.stayLeft = w.stayLeft * r()
        place(w)
        cellMove(W, w)
      end
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
    -- the walker's own leg table, filled again (no garbage per corner)
    local t = w.tr
    if not t then t = newLeg(); w.tr = t end
    t.x0, t.y0, t.z0, t.x1, t.y1, t.z1, t.len, t.s = w.x, w.y, w.z, F.x, F.y, F.z, len, 0
    t.cross, t.hx, t.hy, t.go, t.waited, t.lookAt, t.visit = chosen.cross or false, dx / len, dy / len, false, 0, 0, 0
    w.transit = t
    W.stats.transits = W.stats.transits + 1
  end
end

-- whether a moving car would be on the leg t before a walker at `speed` is over it. cars: lists of
-- {x, y, vx, vy} (vehicles with physics) or of flow cars as drawn ({drawnX, drawnY, drawnYaw, v})
local function carComing(W, t, speed)
  local mx, my = (t.x0 + t.x1) / 2, (t.y0 + t.y1) / 2
  local T = t.len / speed + CROSS_MARGIN
  local side2 = (t.len / 2 + 2) ^ 2
  for _, list in ipairs(W.cars) do
    for _, c in pairs(list) do
      local x, y, vx, vy = c.x, c.y, c.vx, c.vy
      if not x and c.drawnX and c.drawnYaw then
        -- a flow car out of reach is left before its heading is worked out (400 cars, a look each 0.3 s)
        local reach = (c.v or 0) * T + 4
        if (mx - c.drawnX) ^ 2 + (my - c.drawnY) ^ 2 < reach * reach + side2 then
          x, y, vx, vy = c.drawnX, c.drawnY, math.cos(c.drawnYaw) * c.v, math.sin(c.drawnYaw) * c.v
        end
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

-- dt: the time since the walker's last turn; period: frames between its turns (periodOf)
local function advance(W, w, dt, period)
  local d = w.speed * dt
  w.walked = w.walked + d
  local guard = 0
  while d > 1e-6 and guard < 5 do
    guard = guard + 1
    if w.stay then
      -- at a place to stop: the time passes (d back to seconds), no step
      local left = w.stayLeft * w.speed
      if d < left then
        w.stayLeft = w.stayLeft - d / w.speed
        w.walked = w.walked - d
        break
      end
      d = d - left
      w.walked = w.walked - left
      endStay(W, w)
    elseif w.transit then
      local t = w.transit
      if t.cross and not t.go then
        -- at the kerb: the look is taken every 0.3 s
        t.waited = (t.waited or 0) + dt
        t.lookAt = (t.lookAt or 0) - dt
        if t.lookAt <= 0 then
          -- the look each 0.3 s in sight, each second further; one nobody sees goes after a short wait
          local hidden = period == HIDDEN_PERIOD
          t.lookAt = (period or 1) <= 3 and .3 or 1
          if t.waited > (hidden and WAIT_HIDDEN or WAIT_MAX) or (not hidden and not carComing(W, t, w.speed)) then t.go = true end
        end
        if not t.go then
          w.walked, w.waiting = w.walked - d, true
          W.stats.waits = (W.stats.waits or 0) + (t.waited == dt and 1 or 0)
          break
        end
        w.waiting = nil
      end
      local left = t.len - t.s
      if d < left then
        t.s = t.s + d
        d = 0
      else
        d = d - left
        w.transit = nil
        if t.visit == 1 then
          arrive(W, w)
        elseif t.visit == 3 then
          -- back on its way: on either way along it
          w.visit = nil
          if W.random() < .5 then w.dir = -w.dir end
        end
      end
    else
      local target = w.dir > 0 and w.piece.len or 0
      local left = math.abs(target - w.s)
      -- a place to stop on the way: a walker that rested long enough may go there
      local sp, ahead
      if w.piece.spots and not w.visit and W.clock >= (w.restAt or 0) then sp, ahead = spotAhead(w, math.min(d, left)) end
      if sp and W.random() < sp.def.chance and sp.users < sp.def.cap then
        w.s = sp.s
        d = d - ahead
        place(w)
        if not startVisit(W, w, sp) then w.restAt = W.clock + 5 end
      elseif d < left then
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

-- frames between a walker's turns at d2 (squared m) from the focus
local EVERY2, DRAW2 = EVERY_R * EVERY_R, DRAW_R * DRAW_R
local function periodOf(d2)
  if d2 < EVERY2 then return 1 end
  if d2 > DRAW2 then return HIDDEN_PERIOD end
  return math.min(PERIOD_MAX, math.floor(math.sqrt(d2) / RING))
end
M.periodOf = periodOf


-- One step: walkers move, those far away or off the graph go, new ones fill up to the count asked
-- (no more than the sidewalks round the focus hold: W.cap). A walker's turn comes every
-- periodOf(distance) frames; it then walks the time since its last turn. W.onRoad lists the walkers
-- on a leg across a road (the flow's cars stop for them). cars: up to two lists of moving cars a
-- walker waits for before it crosses (carComing).
function M.step(W, dt, fx, fy, cars, flowCars)
  dt = math.min(dt or 0, MAX_DT)
  W.frame, W.clock = W.frame + 1, W.clock + dt
  -- the focus's velocity (spawns ahead of it) and a jump (a teleport: the next fill may be in sight)
  if W.fx then
    local jx, jy = fx - W.fx, fy - W.fy
    if jx * jx + jy * jy > JUMP * JUMP then
      W.filled, W.vx, W.vy, W.candAt = false, 0, 0, 0
    elseif dt > 0 then
      W.vx, W.vy = W.vx * .9 + jx / dt * .1, W.vy * .9 + jy / dt * .1
    end
  end
  W.fx, W.fy = fx, fy
  W.cars[1], W.cars[2] = cars or EMPTY, flowCars or EMPTY
  if W.candVersion ~= W.version or W.frame >= W.candAt then refreshCandidates(W, fx, fy) end
  local want = math.min(W.target, W.cap)
  local onRoad, nOn = W.onRoad, 0
  local keep2, frame, clock = KEEP_R * KEEP_R, W.frame, W.clock
  local fill = 0
  -- the first fill may start anywhere in range (the walkers are being made); later ones out of sight
  local minR = W.filled and HIDE_R or 0
  local slots = W.slots
  for slot = 1, W.target do
    local w = slots[slot]
    if not w then
      w = {free = true, slot = slot, tr = newLeg()}
      slots[slot] = w
    end
    if not w.free and not w.taken then
      if w.piece.dead and not w.transit and not w.visit then
        freeSlot(W, w, 'lostRoad')
      else
        local dx, dy = w.x - fx, w.y - fy
        local d2 = dx * dx + dy * dy
        if d2 > keep2 then
          freeSlot(W, w, 'far')
        else
          local period = periodOf(d2)
          if period == 1 or (slot + frame) % period == 0 then
            advance(W, w, math.min(clock - w.at, MAX_ACC), period)
            w.at, w.dirty = clock, true
            cellMove(W, w)
          end
          local t = w.transit
          if t and t.cross and t.go then
            nOn = nOn + 1
            onRoad[nOn] = w
          end
        end
      end
    end
    if w.free and fill < FILL_PER_STEP and W.count < want then
      fill = fill + 1
      spawnSomewhere(W, slot, fx, fy, minR, SPAWN_R)
    end
  end
  for k = nOn + 1, W.onRoadN do onRoad[k] = nil end
  W.onRoadN = nOn
  if W.count >= want then W.filled = true end
end

-- the count asked, 0..M.MAX: walkers over it go at once, new ones come FILL_PER_STEP a step
function M.setTarget(W, n)
  n = math.max(0, math.min(M.MAX, math.floor(tonumber(n) or 0)))
  for slot = n + 1, #W.slots do
    local w = W.slots[slot]
    if w and not w.free then freeSlot(W, w) end
  end
  W.target = n
end

-- asked, walking, and how many the sidewalks round the focus hold
function M.counts(W) return W.target, W.count, W.cap end

-- Walkers within r of (x, y) that are walking (not taken by a body) and drawn (within DRAW_OUT of
-- the focus), from the grid of cells: into `out` (reused, cleared past the last one), returned
-- with their number.
function M.near(W, x, y, r, out)
  out = out or {}
  local n, r2 = 0, r * r
  local fx, fy, draw2 = W.fx or x, W.fy or y, DRAW_OUT * DRAW_OUT
  local cells = W.cells
  for gx = math.floor((x - r) / CELL), math.floor((x + r) / CELL) do
    for gy = math.floor((y - r) / CELL), math.floor((y + r) / CELL) do
      local list = cells[(gx + 32768) * 65536 + gy + 32768]
      if list then
        for k = 1, list.n do
          local w = list[k]
          if not w.taken and not w.inside and (w.x - x) ^ 2 + (w.y - y) ^ 2 < r2 and (w.x - fx) ^ 2 + (w.y - fy) ^ 2 < draw2 then
            n = n + 1
            out[n] = w
          end
        end
      end
    end
  end
  for k = n + 1, out.n or 0 do out[k] = nil end
  out.n = n
  return out, n
end

-- a physical body has taken the walker's place (pedhit.lua): not drawn, not moved
function M.take(W, w) w.taken = true end
-- the body was not hit after all: the walker walks on from where it was (unless its slot went meanwhile)
function M.untake(W, w) if w and w.taken then w.taken, w.at, w.dirty = nil, W.clock, true end end
-- the body lay and is gone: the walker's slot fills again elsewhere
function M.release(W, w) if w and w.taken then freeSlot(W, w, 'hit') end end

-- the shapes' rotation for heading (hx, hy): +x of the shape along it (flow.quat's convention)
function M.quat(hx, hy)
  local yaw = math.atan2(hy, hx)
  return 0, 0, -math.sin(yaw / 2), math.cos(yaw / 2)
end

-- --- the game side ------------------------------------------------------------------------------
-- shapes: the M.SHAPES shapes (walk poses, then the standing one, then the seated one); group: the
-- scene group. V.far[slot]: the one shape of a walker between NEAR_R and DRAW_R; V.near[slot]: the
-- set of M.SHAPES shapes of a walker within NEAR_R. Both come from pools (V.farFree, V.nearFree) and
-- go back hidden; V.objects counts every object made and not deleted.
-- batches: a shapebatch.lua pool instead (walkers.batchDraw): one copy a walker in the batch of
-- its pose and its trousers and skin, nothing more in the scene.
function M.view(W, shapes, group, batches)
  return {frame = 0, shapes = shapes, group = group, far = {}, near = {}, farFree = {}, nearFree = {}, top = 0,
    objects = 0, sets = 0, needAt = 0, colours = {{}, {}, {}}, farUsed = 0, nearUsed = 0, shown = {}, farLook = {},
    batches = batches, kinds = {}, shirts = {}, bmode = {}, bkind = {}, bb = {}, bi = {}, blook = {}, bsolid = {},
    retireN = 0, retireB = {}, retireI = {}}
end

local function linear(rgb) return ColorF(rgb[1], rgb[2], rgb[3], 1):asLinear4F() end

-- the palette entry as the engine's linear colour, made once per entry (no garbage per repaint)
local PALETTES = {M.SHIRTS, M.PANTS, M.SKIN}
local function colourOf(V, k, i)
  local c = V.colours[k][i]
  if not c then c = linear(PALETTES[k][i]); V.colours[k][i] = c end
  return c
end

local function setColours(o, shirt, pants, skin)
  o.instanceColor, o.instanceColor1, o.instanceColor2 = shirt, pants, skin
end

local function paint(V, o, w)
  pcall(setColours, o, colourOf(V, 1, w.shirt), colourOf(V, 2, w.pants), colourOf(V, 3, w.skin))
end

local function makeObject(V, q)
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
  V.objects = V.objects + 1
  return o
end

-- the pose a walker shows: seated or standing at a place to stop, standing at the kerb, else the
-- step of its walk
local function poseOf(w)
  if w.stay then return w.sit and M.SIT or M.STAND end
  if w.waiting then return M.STAND end
  return math.floor((w.walked % STRIDE) / STRIDE * M.POSES) % M.POSES
end
M.poseOf = poseOf

local function makeSet(V)
  local set = {pose = -1}
  for q = 0, M.SHAPES - 1 do set[q] = makeObject(V, q) end
  V.sets = V.sets + 1
  return set
end

local function dropSet(V, slot, set)
  if set.pose >= 0 then set[set.pose]:setHidden(true) end
  set.pose = -1
  V.near[slot] = nil
  V.nearFree[#V.nearFree + 1] = set
end

local function dropFar(V, slot, o)
  if V.shown[o] then o:setHidden(true); V.shown[o] = nil end
  V.far[slot] = nil
  V.farFree[#V.farFree + 1] = o
end

-- the ground under a walker, read again every 2 m (a raised sidewalk, a kerb), else the road + CURB.
-- By a bench the read would land on its seat: the place's own ground (the tile's) there.
local function groundZ(w, ground)
  local sp = w.visit
  if sp and sp.def.sit and (w.x - w.sx) ^ 2 + (w.y - w.sy) ^ 2 < 2.25 then return w.sz end
  if ground and (not w.gzAt or math.abs(w.walked - w.gzAt) > 2) then
    w.gzAt = w.walked
    local z = ground(w.x, w.y, w.z)
    w.gz = (z and math.abs(z - w.z) < 1.5) and z or nil
  end
  return w.gz or (w.z + CURB)
end

-- --- the batches (DynamicShapeBatch, shapebatch.lua) ---------------------------------------------
-- A batch copy takes one colour, the first palette slot: the shirt. Trousers and skin are put in
-- by material remaps (people_art.py e2r_ped_pants_<k>, e2r_ped_skin_<k>, the PANTS and SKIN
-- palettes baked). Each batch costs 13-25 ms of finalizeShape (shapebatch.lua), so a kind is a pose
-- and a skin, the trousers following the skin (BATCH_PANTS): M.SHAPES x 5 = 50 batches at most,
-- one made a frame as walkers need them (a walker waits unseen for its kind's). Distances, poses
-- and the look by w.look are the TSStatic side's.
M.PANTS_MAT, M.SKIN_MAT = 'e2r_ped_pants', 'e2r_ped_skin'
M.BATCH_PANTS = {1, 2, 3, 4, 5}    -- the trousers of each skin in the batches
local function kindOf(V, pose, skin)
  local byPose = V.kinds[pose]
  if not byPose then byPose = {}; V.kinds[pose] = byPose end
  local K = byPose[skin]
  if not K then
    local pants = M.BATCH_PANTS[skin] or 1
    K = V.batches:kind(V.shapes[pose + 1], {M.PANTS_MAT, M.PANTS_MAT .. '_' .. pants, M.SKIN_MAT, M.SKIN_MAT .. '_' .. skin},
      'ped' .. pose .. '_' .. skin)
    byPose[skin] = K
  end
  return K
end

-- The fal people (earthng/traffic_art.py; M.CHARS, set by world.lua where the planet has them and
-- the game has batches): a walker is one of the figures, by its look's number, and its copy is the
-- figure's own shape of the pose with the figure's own map (no colour, no remap). A walker
-- further than NEAR_R walks as the figure's far shape (a third of the triangles).
local POSE_KEYS = {}
for q = 0, M.POSES - 1 do POSE_KEYS[q] = 'walk' .. q end
POSE_KEYS[M.POSES], POSE_KEYS[M.POSES + 1] = 'stand', 'sit'
function M.charOf(w)
  local chars = M.CHARS
  return chars and chars[(w.look or 0) % #chars + 1] or nil
end
-- the colours of the body that takes w's place (pedhit.lua): its figure's, else its palettes'
function M.coloursOf(w)
  local char = M.charOf(w)
  local look = char and char.look
  if look then return look.shirt, look.pants, look.skin end
  return M.SHIRTS[w.shirt], M.PANTS[w.pants], M.SKIN[w.skin]
end
local function charKind(V, char, key)
  local shape = char.shapes[key]
  local K = V.kinds[shape]
  if not K then
    -- the batch of a pose first, the solid copies of it after (shapebatch.lua)
    K = V.batches:kind(shape, nil, shape, true)
    V.kinds[shape] = K
  end
  return K
end

-- the shirt as one ColorF per palette entry (sRGB, as the engine's ColorF), made once
local function shirtOf(V, i)
  local c = V.shirts[i]
  if not c then
    local rgb = M.SHIRTS[i]
    c = ColorF(rgb[1], rgb[2], rgb[3], 1)
    V.shirts[i] = c
  end
  return c
end

local function batchDraw(W, V, fx, fy, ground)
  V.frame = V.frame + 1
  local P = V.batches
  P:tick()
  -- copies retired last frame (the pose before this one): gone now that the new one has been drawn
  local n = V.retireN
  if n > 0 then
    local rb, ri = V.retireB, V.retireI
    for k = 1, n do
      P:drop(rb[k], ri[k])
      rb[k], ri[k] = nil, nil
    end
    V.retireN = 0
  end
  local near2, nearOut2, draw2, drawOut2 = NEAR_R * NEAR_R, NEAR_OUT * NEAR_OUT, DRAW_R * DRAW_R, DRAW_OUT * DRAW_OUT
  local solid2, solidOut2 = SOLID_R * SOLID_R, SOLID_OUT * SOLID_OUT
  local slots, bmode, bkind, bb, bi, blook, bsolid = W.slots, V.bmode, V.bkind, V.bb, V.bi, V.blook, V.bsolid
  local moved, top, farUsed, nearUsed, solidUsed = 0, 0, 0, 0, 0
  for slot = 1, math.max(W.target, V.top) do
    local w = slots[slot]
    local was = bmode[slot] or 0
    -- 0: none, 1: the one pose, 2: posed as it walks, 3: posed, a solid copy (a figure near the focus)
    local mode = 0
    if w and not w.free and not w.taken and not w.inside and slot <= W.target then
      local d2 = (w.x - fx) ^ 2 + (w.y - fy) ^ 2
      if V.chars and d2 < (was == 3 and solidOut2 or solid2) then mode = 3
      elseif d2 < (was >= 2 and nearOut2 or near2) then mode = 2
      elseif d2 < (was > 0 and drawOut2 or draw2) then mode = 1 end
    end
    if mode == 0 then
      if bb[slot] then P:drop(bb[slot], bi[slot]) end
      bb[slot], bi[slot], bkind[slot], blook[slot], bsolid[slot] = nil, nil, nil, nil, nil
    else
      top = slot
      if mode >= 2 then nearUsed = nearUsed + 1 else farUsed = farUsed + 1 end
      local posed = mode >= 2 or w.stay
      local pose = posed and poseOf(w) or FAR_POSE
      local char = V.chars and M.charOf(w)
      local K
      if char then
        K = charKind(V, char, posed and POSE_KEYS[pose] or 'far')
      else
        K = kindOf(V, pose, w.skin)
      end
      local solid = mode == 3 and char and true or nil
      if solid then solidUsed = solidUsed + 1 end
      local hx, hy = w.hx or 1, w.hy or 0
      local len = math.sqrt(hx * hx + hy * hy)
      if len > 1e-9 then hx, hy = hx / len, hy / len else hx, hy = 1, 0 end
      if K ~= bkind[slot] or blook[slot] ~= w.look or bsolid[slot] ~= solid then
        local B, i
        if solid then
          B, i = P:addSolid(K, w.x, w.y, groundZ(w, ground), -hy, hx, 0)
        else
          B, i = P:add(K, w.x, w.y, groundZ(w, ground), -hy, hx, 0, not char and shirtOf(V, w.shirt) or nil)
        end
        -- the kind's batch not made yet (one a frame): the old copy stays until it is
        if B then
          -- keep the previous pose one frame: dropping it here left a blank frame every step
          if bb[slot] then
            local r = V.retireN + 1
            V.retireN, V.retireB[r], V.retireI[r] = r, bb[slot], bi[slot]
          end
          bb[slot], bi[slot], bkind[slot], blook[slot], bsolid[slot] = B, i, K, w.look, solid
          moved = moved + 1
        elseif bb[slot] and blook[slot] ~= w.look then
          -- another walker in the slot: the old one's copy goes now
          P:drop(bb[slot], bi[slot])
          bb[slot], bi[slot], bkind[slot], blook[slot], bsolid[slot] = nil, nil, nil, nil, nil
        end
      elseif w.dirty then
        P:move(bb[slot], bi[slot], w.x, w.y, groundZ(w, ground), -hy, hx, 0)
        moved = moved + 1
      end
    end
    bmode[slot] = mode
    if w then w.dirty = nil end
  end
  V.top, V.farUsed, V.nearUsed, V.solidUsed, V.objects = top, farUsed, nearUsed, solidUsed, P.objects + P.solidObjects
  return moved
end

-- Every frame after M.step. ground(x, y, z): the surface under a point, or nil
-- (be:getSurfaceHeightBelow in the game). A walker is placed again only when its turn moved it
-- (w.dirty) or it got its shape this frame. Returns how many were placed.
function M.draw(W, V, fx, fy, ground)
  if V.batches then return batchDraw(W, V, fx, fy, ground) end
  V.frame = V.frame + 1
  local shown, farLook = V.shown, V.farLook
  local moved, budget = 0, MAKE_PER_FRAME
  local near2, nearOut2, draw2, drawOut2 = NEAR_R * NEAR_R, NEAR_OUT * NEAR_OUT, DRAW_R * DRAW_R, DRAW_OUT * DRAW_OUT
  local slots, farOf, nearOf = W.slots, V.far, V.near
  local top, farUsed, nearUsed = 0, 0, 0
  for slot = 1, math.max(W.target, V.top) do
    local w = slots[slot]
    local far, set = farOf[slot], nearOf[slot]
    -- 0: no shape, 1: the one shape, 2: the posed set
    local mode = 0
    if w and not w.free and not w.taken and not w.inside and slot <= W.target then
      local d2 = (w.x - fx) ^ 2 + (w.y - fy) ^ 2
      if d2 < (set and nearOut2 or near2) then mode = 2
      elseif d2 < ((far or set) and drawOut2 or draw2) then mode = 1 end
    end
    if mode == 2 and not set then
      local free = V.nearFree
      set = free[#free]
      if set then
        free[#free] = nil
      elseif V.sets < NEAR_SETS and budget >= M.SHAPES then
        budget = budget - M.SHAPES
        set = makeSet(V)
      end
      if set then nearOf[slot] = set; V.needAt = V.frame else mode = 1 end
    end
    if mode ~= 2 and set then dropSet(V, slot, set); set = nil end
    if mode == 1 and not far then
      local free = V.farFree
      far = free[#free]
      if far then
        free[#free] = nil
      elseif budget > 0 then
        budget = budget - 1
        far = makeObject(V, FAR_POSE)
      end
      if far then farOf[slot] = far; V.needAt = V.frame else mode = 0 end
    end
    if mode ~= 1 and far then dropFar(V, slot, far); far = nil end
    if mode == 2 then
      nearUsed, top = nearUsed + 1, slot
      if set.lookN ~= w.look then
        set.lookN = w.look
        for q = 0, M.SHAPES - 1 do paint(V, set[q], w) end
        if set.pose >= 0 then set[set.pose]:setHidden(true) end
        set.pose = -1
      end
      if w.dirty or set.pose < 0 then
        local pose = poseOf(w)
        local qx, qy, qz, qw = M.quat(w.hx, w.hy)
        set[pose]:setPosRot(w.x, w.y, groundZ(w, ground), qx, qy, qz, qw)
        if pose ~= set.pose then
          if set.pose >= 0 then set[set.pose]:setHidden(true) end
          set[pose]:setHidden(false)
          set.pose = pose
        end
        moved = moved + 1
      end
    elseif mode == 1 then
      farUsed, top = farUsed + 1, slot
      local fresh = not shown[far]
      if farLook[far] ~= w.look then farLook[far] = w.look; paint(V, far, w); fresh = true end
      if w.dirty or fresh then
        local qx, qy, qz, qw = M.quat(w.hx, w.hy)
        far:setPosRot(w.x, w.y, groundZ(w, ground), qx, qy, qz, qw)
        if not shown[far] then far:setHidden(false); shown[far] = true end
        moved = moved + 1
      end
    end
    if w then w.dirty = nil end
  end
  V.top, V.farUsed, V.nearUsed = top, farUsed, nearUsed
  -- spare objects (the count went down, the car left a town) go a few a frame, a while after the
  -- pools were last drawn from
  if V.frame - V.needAt > TRIM_AFTER then
    local cut = TRIM_PER_FRAME
    local free = V.farFree
    while cut > 0 and #free > SPARE_FAR do
      local o = free[#free]
      free[#free] = nil
      farLook[o] = nil
      o:delete()
      V.objects, cut = V.objects - 1, cut - 1
    end
    free = V.nearFree
    while cut >= M.SHAPES and #free > SPARE_SETS do
      local set = free[#free]
      free[#free] = nil
      for q = 0, M.SHAPES - 1 do set[q]:delete() end
      V.objects, V.sets, cut = V.objects - M.SHAPES, V.sets - 1, cut - M.SHAPES
    end
  end
  return moved
end

-- the ground height a walker stands on (for the body that takes its place)
function M.standZ(w) return w.gz or (w.z + CURB) end

-- Every object deleted and every walker gone (W keeps its sidewalks; the count asked becomes 0).
function M.clear(W, V)
  if V and V.batches then
    V.batches:clear()
    V.bmode, V.bkind, V.bb, V.bi, V.blook, V.top, V.objects, V.farUsed, V.nearUsed = {}, {}, {}, {}, {}, 0, 0, 0, 0
    V.bsolid = {}
    V.retireN = 0
  elseif V then
    for _, o in pairs(V.far) do o:delete() end
    for _, o in ipairs(V.farFree) do o:delete() end
    for _, set in pairs(V.near) do for q = 0, M.SHAPES - 1 do set[q]:delete() end end
    for _, set in ipairs(V.nearFree) do for q = 0, M.SHAPES - 1 do set[q]:delete() end end
    V.far, V.near, V.farFree, V.nearFree, V.top, V.objects, V.sets = {}, {}, {}, {}, 0, 0, 0
    V.shown, V.farLook, V.farUsed, V.nearUsed = {}, {}, 0, 0
  end
  for slot = 1, #W.slots do freeSlot(W, W.slots[slot]) end
  W.slots, W.target, W.count, W.cells, W.cellPool = {}, 0, 0, {}, {}
  for k = 1, W.onRoadN do W.onRoad[k] = nil end
  W.onRoadN, W.filled = 0, nil
end

return M
