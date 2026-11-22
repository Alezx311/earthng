-- Shorelines: where a water body ends, what its bank is made of and how the ground meets the
-- water. generator.lua (WATER.shore) shapes the ground lattice with it and draws the banks; it
-- has no engine calls and no state of its own, so the tests run it as the game does.
--
-- The water stands DROP m under the level its DEM gives (a DEM holds the water's surface, and
-- its banks are no higher than that for tens of metres: the water lay 0.3 m over its own bank).
-- Round it the ground is shaped by the distance to the shoreline: a bank rises to `rise` m over
-- the water within `riseAt` m, the bed falls `slope` m a metre to DEEP m. Both are straight
-- lines through the waterline, so the lattice (12.5 m) crosses the water's level near the mapped
-- shore whichever of its nodes are wet. A bank's own material lies between `lo` and `hi` m over
-- the water, `out` m from the shoreline at most; under `lo` the bed is the one plain bed of all
-- water (two banks' beds met under the water along the lattice's triangles).
local M = {}
local floor, sqrt, max, min, abs = math.floor, math.sqrt, math.max, math.min, math.abs
local NONE = {}

M.REACH = 36    -- m from a shoreline the ground is shaped in (a tile holds its cells 40 m past its edge)
M.DEEP = 2.5    -- m: every bed ends this deep, so a point past REACH needs no shoreline
M.DROP = .35    -- m the water stands under its DEM level
M.BIN = 20      -- m: bins of the shoreline's pieces
M.PIECE = 16    -- m: the longest piece of an edge (a long edge may be a shore along a part of it)
M.PAD = 6       -- m a water's cover reaches past its mapped edge; the ground decides where it shows
M.ABOVE = .03   -- m a bank's material lies over the ground it is draped on

-- kind: the material of the bank (fast_style KINDS). plants: what grows in its shallows
-- (generator: reed is the flora's bank layer, stone the loose rock of the place).
-- The bed's slope is the bank's own rise over half a lattice cell or so: a steeper bed under a
-- bank that the lattice cannot draw as steep moved the waterline metres out onto the land.
M.TYPES = {
  sand = {rise = .5, riseAt = 8, slope = .075, steep = .15, lo = -1.3, hi = .9, out = 12, kind = 'beach'},
  shingle = {rise = .55, riseAt = 5, slope = .09, steep = .3, lo = -1.1, hi = .7, out = 6, kind = 'scree', plants = 'stone', every = 7},
  rock = {rise = .9, riseAt = 3, slope = .15, lo = -1.3, hi = 1.3, out = 5, kind = 'bare_rock', plants = 'stone', every = 3.5},
  bank = {rise = .45, riseAt = 3.5, slope = .08, steep = .35, lo = -1.4, hi = .12, out = 3, kind = 'wetland', plants = 'reed', every = 5},
  reed = {rise = .3, riseAt = 5, slope = .055, steep = .15, lo = -1.2, hi = .28, out = 6, kind = 'wetland', plants = 'reed', every = 1.3},
  quay = {rise = .8, riseAt = 1.5, slope = .14, lo = -1., hi = .85, out = 2.5, kind = 'paved'},
}
for name, T in pairs(M.TYPES) do T.name = name end
M.DEFAULT = M.TYPES.bank
-- water that was dug and lined
M.MADE = {canal = true, basin = true, reflecting_pool = true, fountain = true, pool = true, dock = true,
  harbour = true, lock = true, moat = true, wastewater = true, swimming_pool = true}

-- steep: the most a bank of the kind rises a metre from its waterline (nil: as the DEM has it, a
-- rock or a quay). A 30 m DEM under trees stands 6-8 m over a river 10 m from its beach: the
-- lattice then met the water at its own wet nodes, in teeth of a cell, with the bank's grass
-- between the water and the mapped sand. The cap holds for CAP m from the water and gives way
-- to the DEM by REACH.
M.CAP = 20
function M.cap(T, d, z)
  if not T.steep then return z end
  local cap = .1 + T.steep * d
  if z <= cap then return z end
  if d <= M.CAP then return cap end
  local t = (d - M.CAP) / (M.REACH - M.CAP)
  if t >= 1 then return z end
  return cap + (z - cap) * t * t * (3 - 2 * t)
end
-- The bank's least height over the water `d` m outside the shoreline, and the bed's depth `d` m
-- inside it.
function M.rise(T, d)
  if d >= T.riseAt then return T.rise end
  return d > 0 and T.rise * d / T.riseAt or 0
end
-- (the bank's own slope for SHELF m, then evenly down to DEEP at REACH: a gentle reed bank and
-- a quay end at the same depth where no shoreline is in reach)
-- least: the least slope of this body's bed (M.pond: a pond 30 m across with a beach's bed was
-- 0.4 m of clear water over sand at its middle, and read as dry sand).
M.SHELF = 12
function M.depth(T, d, least)
  if d <= 0 then return 0 end
  if d >= M.REACH then return M.DEEP end
  local slope = least and least > T.slope and least or T.slope
  -- (a pond's bank drops STEP m at the waterline: its few nodes are all near its shore)
  local step = least and M.STEP or 0
  local shelf = min(M.DEEP, step + slope * M.SHELF)
  if d <= M.SHELF then return min(M.DEEP, step + slope * d) end
  return shelf + (M.DEEP - shelf) * (d - M.SHELF) / (M.REACH - M.SHELF)
end
-- (in game, 21.11: water under ~0.7 m is clear from above whatever its fog, and a pond whose
-- bed lay 0.2-0.7 m down was a patch of sand: its bank drops a metre into it)
M.STEP = 1
-- The least slope of the bed of a pond or a small lake `across` m wide (the shorter side of its
-- box): its middle lies POND m deep at least. nil for a body wide enough for its bank's own bed.
M.POND = 1.8
function M.pond(across)
  local least = M.POND / max(1, across * .3)
  if least <= .09 then return nil end
  return least > .4 and .4 or least
end

local function binKey(gx, gy) return (gx + 32768) * 65536 + gy + 32768 end

-- The shoreline of a tile: the edges of its water bodies with land on one side. A pack clips a
-- body to each of its cells, 100 m past the cell, so most bodies come in overlapping parts: an
-- edge with water on both sides is a cut, not a shore. waters: {rings, bounds, ...} (generator
-- ROADS.waters). wet(x, y): is the point under any of them. rect: only edges within `margin` m
-- of it are kept. Each piece has its body (water), its ends, its length and the unit normal
-- (nx, ny) pointing to the land.
function M.index(waters, wet, rect, margin, pause)
  local S = {bins = {}, pieces = {}, types = {}, count = 0}
  local x0, y0, x1, y1 = rect[1] - margin, rect[2] - margin, rect[3] + margin, rect[4] + margin
  local E, done = .4, 0
  for _, water in ipairs(waters) do
    local b = water.bounds
    if b[3] >= x0 and b[1] <= x1 and b[4] >= y0 and b[2] <= y1 then
      for _, ring in ipairs(water.rings) do
        local n = #ring
        for k = 1, n do
          local a, c = ring[k], ring[k % n + 1]
          local ax, ay, dx, dy = a[1], a[2], c[1] - a[1], c[2] - a[2]
          local len = sqrt(dx * dx + dy * dy)
          if len > 1e-3 and max(ax, c[1]) >= x0 and min(ax, c[1]) <= x1 and max(ay, c[2]) >= y0 and min(ay, c[2]) <= y1 then
            local ux, uy = dx / len, dy / len
            local parts = max(1, math.ceil(len / M.PIECE))
            for p = 0, parts - 1 do
              local s0, s1 = len * p / parts, len * (p + 1) / parts
              local mx, my = ax + ux * (s0 + s1) * .5, ay + uy * (s0 + s1) * .5
              if mx >= x0 and mx <= x1 and my >= y0 and my <= y1 then
                -- the left of the edge's direction is (-uy, ux)
                local left, right = wet(mx - uy * E, my + ux * E), wet(mx + uy * E, my - ux * E)
                if left ~= right then
                  local piece = {water = water, ax = ax + ux * s0, ay = ay + uy * s0, ux = ux, uy = uy, len = s1 - s0,
                    nx = left and uy or -uy, ny = left and -ux or ux}
                  S.count = S.count + 1
                  S.pieces[S.count] = piece
                  local bx, by = piece.ax + ux * piece.len, piece.ay + uy * piece.len
                  for gy = floor(min(piece.ay, by) / M.BIN), floor(max(piece.ay, by) / M.BIN) do
                    for gx = floor(min(piece.ax, bx) / M.BIN), floor(max(piece.ax, bx) / M.BIN) do
                      local key = binKey(gx, gy)
                      local bin = S.bins[key]
                      if not bin then bin = {}; S.bins[key] = bin end
                      bin[#bin + 1] = piece
                    end
                  end
                end
              end
              done = done + 1
              if pause and done % 64 == 0 then pause() end
            end
          end
        end
      end
    end
  end
  return S
end

-- The nearest point of the shoreline within `reach` m (REACH) of (x, y): its distance, piece
-- and place, or nil.
function M.near(S, x, y, reach)
  reach = reach or M.REACH
  local best, piece, bx, by = reach * reach, nil, nil, nil
  local bins, B = S.bins, M.BIN
  for gy = floor((y - reach) / B), floor((y + reach) / B) do
    for gx = floor((x - reach) / B), floor((x + reach) / B) do
      local bin = bins[binKey(gx, gy)]
      if bin then
        for k = 1, #bin do
          local p = bin[k]
          local t = (x - p.ax) * p.ux + (y - p.ay) * p.uy
          if t < 0 then t = 0 elseif t > p.len then t = p.len end
          local px, py = p.ax + p.ux * t, p.ay + p.uy * t
          local d = (x - px) * (x - px) + (y - py) * (y - py)
          if d < best then best, piece, bx, by = d, p, px, py end
        end
      end
    end
  end
  if piece then return sqrt(best), piece, bx, by end
end

-- What a bank is at a point of the shoreline. ctx: coverAt(x, y) -> the mapped cover kind,
-- demAt(x, y), builtAt(x, y) -> the built-up share, group(x, y) -> the climate's group
-- (biome.lua GROUP) or nil, noise(x, y, size, seed) -> 0..1. level: the water's there.
-- What is mapped decides first (a beach, rock, a marsh, a quay in a town), then how steep the
-- land beyond is, then the climate; along a lowland shore the kinds take turns over ~90 m.
function M.classify(ctx, piece, x, y, level)
  local nx, ny = piece.nx, piece.ny
  local tags = piece.water.tags or NONE
  local w = tags.water or tags.waterway or tags.leisure or tags.landuse or ''
  local c1, c2 = ctx.coverAt(x + nx * 5, y + ny * 5), ctx.coverAt(x + nx * 13, y + ny * 13)
  if c1 == 'beach' or c2 == 'beach' then return 'sand' end
  if c1 == 'bare_rock' or c1 == 'glacier' then return 'rock' end
  if c1 == 'scree' then return 'shingle' end
  if c1 == 'wetland' or c2 == 'wetland' then return 'reed' end
  local built = ctx.builtAt and ctx.builtAt(x + nx * 10, y + ny * 10) or 0
  if M.MADE[w] or c1 == 'paved' or built > .1 then return 'quay' end
  local far = ctx.demAt(x + nx * 14, y + ny * 14)
  local steep = far and (far - level) / 14 or 0
  if steep > .45 then return 'rock' end
  local group = ctx.group and ctx.group(x, y) or nil
  local n = ctx.noise(x, y, 90, 71)
  if group == 'ice' or group == 'tundra' then return steep > .2 and 'rock' or 'shingle' end
  if group == 'desert' or group == 'steppe' then return n < .68 and 'sand' or 'shingle' end
  if steep > .25 then return n < .5 and 'rock' or 'shingle' end
  if group == 'boreal' then return n < .36 and 'rock' or (n < .52 and 'shingle' or (n < .68 and 'bank' or 'reed')) end
  if group == 'mediterranean' then return n < .42 and 'shingle' or (n < .6 and 'sand' or 'bank') end
  if group == 'rainforest' or group == 'savanna' then return n < .4 and 'sand' or (n < .62 and 'bank' or 'reed') end
  if w == 'river' or w == 'riverbank' or w == 'stream' or w == 'oxbow' then
    return n < .36 and 'sand' or (n < .6 and 'bank' or 'reed')
  end
  return n < .32 and 'sand' or (n < .56 and 'bank' or 'reed')
end

-- The bank's kind at a point of the shoreline, kept per 6 m of it
function M.typeAt(S, ctx, piece, x, y, level)
  local key = binKey(floor(x / 6), floor(y / 6))
  local name = S.types[key]
  if not name then
    name = M.classify(ctx, piece, x, y, level)
    S.types[key] = name
  end
  return M.TYPES[name] or M.DEFAULT
end

-- The open sea has no polygon: its shore is where the DEM leaves the sea plane. The coast's
-- kind at a point by the mapped cover there, the slope (m a metre) and the climate.
function M.coast(ctx, x, y, steep)
  local cover = ctx.coverAt(x, y)
  if cover == 'beach' then return M.TYPES.sand end
  if cover == 'bare_rock' or cover == 'glacier' then return M.TYPES.rock end
  if cover == 'scree' then return M.TYPES.shingle end
  if cover == 'wetland' then return M.TYPES.reed end
  if cover == 'paved' then return M.TYPES.quay end
  if steep > .4 then return M.TYPES.rock end
  local group = ctx.group and ctx.group(x, y) or nil
  local n = ctx.noise(x, y, 160, 73)
  if group == 'ice' or group == 'tundra' then return steep > .15 and M.TYPES.rock or M.TYPES.shingle end
  if steep > .18 then return n < .5 and M.TYPES.rock or M.TYPES.shingle end
  if group == 'boreal' then return n < .45 and M.TYPES.shingle or (n < .6 and M.TYPES.rock or M.TYPES.sand) end
  return n < .3 and M.TYPES.shingle or M.TYPES.sand
end

-- Clip a convex polygon of points {x, y, z, h, d, ...} to where field i is at least (below:
-- at most) `bound`; the points on the cut are interpolated in every field.
local function clipBy(pts, i, bound, below)
  local out, n, m = {}, #pts, 0
  for k = 1, n do
    local a, b = pts[k], pts[k % n + 1]
    local fa, fb = a[i] - bound, b[i] - bound
    if below then fa, fb = -fa, -fb end
    if fa >= 0 then m = m + 1; out[m] = a end
    if (fa > 0 and fb < 0) or (fa < 0 and fb > 0) then
      local t = fa / (fa - fb)
      local p = {}
      for j = 1, #a do p[j] = a[j] + (b[j] - a[j]) * t end
      m = m + 1
      out[m] = p
    end
  end
  return out
end
M.clipBy = clipBy

local function area2(pts)
  local s = 0
  for k = 1, #pts do
    local p, q = pts[k], pts[k % #pts + 1]
    s = s + p[1] * q[2] - q[1] * p[2]
  end
  return abs(s)
end
M.area2 = area2

-- The part of a ground triangle that is a bank of kind T: corners {x, y, z, h, d}, h the height
-- over the water and d the distance outside the shoreline (negative under the water's polygon).
-- lo: the band's lower height where it is not the kind's own (generator WATER.bank).
-- Returns the piece and whether it is the whole triangle, or nil.
function M.band(T, tri, lo)
  local p = clipBy(tri, 4, lo or T.lo, false)
  if #p >= 3 then p = clipBy(p, 4, T.hi, true) end
  if #p >= 3 then p = clipBy(p, 5, T.out, true) end
  if #p < 3 then return nil end
  local whole, part = area2(tri), area2(p)
  if part < 2e-3 then return nil end
  return p, part > whole - 1e-3
end

return M
