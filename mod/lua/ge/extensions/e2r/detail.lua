-- Grass (8 m cells) and loose rocks (32 m cells) around the camera: cell objects appear
-- and go together (TSStatic without collision), at most two cells a frame. Each kind has
-- its own reach and total cap (tune.grassM / grassBudget, rockM / rockBudget).
--
-- The lawn carpet comes in four rings, so it has no edge 25 m from the camera: every 2 m
-- square of a patch holds nine tufts, of which the far ring ('grass', out to grassM) shows one
-- broad tuft in every other square, the middle ring ('grassMid') one or two more, the inner
-- ring ('grassInner') two more and the near ring ('grassNear') the other five: 9, 4, 2 and
-- 1/2 a square, no step over x2.25 (three rings stepped 9 -> 2, a wall of grass at 26 m).
-- A ring only adds to the ones outside it: nothing is swapped as the camera comes closer. The
-- four share grassBudget, the near rings first.
local M = {}
M.CELL = 32
M.GRASS_CELL = 8
local GROUP = {grass = 'grass', grassMid = 'grass', grassInner = 'grass', grassNear = 'grass', rock = 'rock'}
local function cellSize(kind) return kind == 'rock' and M.CELL or M.GRASS_CELL end
-- the order budgets are given in: the nearest ring first
M.KINDS = {'grassNear', 'grassInner', 'grassMid', 'grass', 'rock'}
-- ring: the patch level it shows, its reach as a share of grassM and its share of grassBudget
-- (Balanced, 100 m / 9000: ~22, ~34, ~52 and ~74 m)
M.RINGS = {grassNear = {level = 0, reach = .22, min = 12, share = .2},
  grassInner = {level = 1, reach = .34, min = 16, share = .2},
  grassMid = {level = 2, reach = .55, min = 22, share = .36},
  grass = {level = 3, reach = 1, min = 0, share = 1}}
-- stray: an outer ring's tuft stands anywhere in its square (on the 2 m grid they stood in rows)
M.TUFT = {far = {wide = 1.9, tall = 1.45}, mid = {wide = 1.6, tall = 1.3}, corner = {wide = 1.3, tall = 1.15},
  inner = {wide = 1.15, tall = 1.08}, long = {low = .5, high = .85, wide = 1.5}, near = 5, inner2 = 2, thin = 2,
  stray = 1.7}
-- the ring (level) that owns each of a square's nine tufts, (ix, iy) from -1 to 1; the middle
-- one is the far ring's in every other square (OWN[0] is nil: centre)
local OWN = {[-1] = {[-1] = 0, [0] = 0, [1] = 1}, [0] = {[-1] = 0, [1] = 0}, [1] = {[-1] = 1, [0] = 0, [1] = 2}}

function M.kind(it)
  local s = it and it.shape
  if it and it.kind ~= 'proc' and type(s) == 'string' then
    -- grass tufts, and the clover, daisy and fern patches beside them (all East Coast
    -- groundcover): placed per tile as TSStatics they cost ~3 ms a frame in Obolon (vegab-obolon)
    if s:find('3d_grass', 1, true) or s:find('/groundcover/', 1, true) then return 'grass' end
    if s:find('/rocks/', 1, true) then return 'rock' end
  end
end

-- reach (m) and cap (objects) of a kind under a tune
function M.limits(kind, tune)
  local ring = M.RINGS[kind]
  if not ring then return tune.rockM or 0, tune.rockBudget or 0 end
  local reach, cap = tune.grassM or 0, tune.grassBudget or 0
  if reach <= 0 or cap <= 0 then return 0, 0 end
  return math.min(reach, math.max(ring.min, reach * ring.reach)), math.floor(cap * ring.share)
end

-- A sample of a patch: its 2 m square (0..15) with flags, 16: a lush hollow's long grass,
-- 32: thin grass on dry ground, 64: a field of ripe wheat, 128: a field's crop rows, 256:
-- those rows run along y (generator.lua lawnCarpet, FIELD). crop: nil, 'wheat', 'rows' or 'rowsY'.
local function sampleOf(value)
  local slot = value % 16
  local flags = (value - slot) / 16
  local crop = math.floor(flags / 4) % 2 == 1 and 'wheat' or nil
  if math.floor(flags / 8) % 2 == 1 then crop = math.floor(flags / 16) % 2 == 1 and 'rowsY' or 'rows' end
  return slot, flags % 2 == 1, math.floor(flags / 2) % 2 == 1, crop
end

-- A field's standing crop near the road: wheat as dense dry tufts to the knee (the game's dry
-- grass, the patch's dry set), the rows of sunflower or maize as long green tufts on the 2/3 m
-- grid, straight across the rows and loose along them (the field's texture has its rows on the
-- same grid, generator FIELD, fast_photo field_sheet). Even everywhere: a field is sown, not wild.
M.CROP = {wheat = {low = .62, high = .88, stray = .9}, rows = {low = .45, high = .7, across = .06, along = 1.2}}

-- The lawn is not one mown carpet (seen from a parked car it was): its height sways in patches
-- (tall: 0..1 of noise over 9 and 23 m, a square's tufts from low to high of their height),
-- it thins out to bare ground in places (gap: under from .. to of noise over 6 and 15 m, a tuft
-- kept with the share of that ramp) and coarse weeds stand in clumps (weed: noise over 5 m above
-- `from`, the long grass of lush hollows at its own height). All from the square's place, so
-- every ring shows the same lawn.
M.WILD = {tall = {low = .62, high = 1.5, power = 1.3}, gap = {from = .16, to = .34}, weed = {from = .8, low = .55, high = 1}}
local HMOD = 2147483647
local function knot(seed, a, b)
  local h = (seed * 1000003 + a) % HMOD
  h = (h * 1000003 + b) % HMOD
  h = (h * 48271 + 11) % HMOD
  return (h * 48271 + 7) % HMOD % 1000 / 1000
end
-- smooth 0..1 noise with `size` m features (generator.lua RELIEF.noise)
function M.noise(x, y, size, seed)
  local fx, fy = x / size, y / size
  local gx, gy = math.floor(fx), math.floor(fy)
  local tx, ty = fx - gx, fy - gy
  tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
  local a = knot(seed, gx, gy) + (knot(seed, gx + 1, gy) - knot(seed, gx, gy)) * tx
  local b = knot(seed, gx, gy + 1) + (knot(seed, gx + 1, gy + 1) - knot(seed, gx, gy + 1)) * tx
  return a + (b - a) * ty
end
-- a square's height factor, the share of its tufts kept and whether weeds stand there
function M.wild(x, y)
  local W = M.WILD
  local tall = M.noise(x, y, 9, 11) * .6 + M.noise(x, y, 23, 12) * .4
  local height = W.tall.low + (W.tall.high - W.tall.low) * tall ^ W.tall.power
  local gap = M.noise(x, y, 6, 13) * .55 + M.noise(x, y, 15, 14) * .45
  local keep = math.max(0, math.min(1, (gap - W.gap.from) / (W.gap.to - W.gap.from)))
  return height, keep, M.noise(x, y, 5, 15) > W.weed.from
end

-- tufts of a patch in a ring's level, and the sum of their heights (the cell's mean z). An upper
-- bound: expand drops the tufts of the lawn's bare gaps (M.WILD.gap), not counted here (the noise
-- per square cost more at a tile's build than the few tufts of budget it frees)
function M.patchCount(patch, level)
  local n, zs = 0, 0
  for k = 1, #patch.samples, 4 do
    local slot, _, thin = sampleOf(patch.samples[k])
    local even = (slot % 4 + math.floor(slot / 4)) % 2 == 0
    local T, c = M.TUFT
    -- thin: the first two of the near and inner tufts (both near ones, in expand's order)
    if level == 3 then c = even and 1 or 0
    elseif level == 2 then c = even and 1 or 2
    elseif level == 1 then c = thin and 0 or T.inner2
    elseif level == 0 then c = thin and T.thin or T.near
    else c = 2 + (thin and T.thin or T.near + T.inner2) end
    n, zs = n + c, zs + c * patch.samples[k + 1]
  end
  return n, zs
end

-- Compact 8 m patches carry only the accepted 2 m squares and their local ground planes.
-- Expand only a live cell, never every blade of every loaded 500 m tile. Nine short tufts
-- stand in each square on a 2/3 m grid, so neighbouring squares meet; part.level picks the
-- ring's share of them (nil: all nine). The far tufts are broad and a little taller: one of
-- them covers its square from 60 m.
function M.expand(part, pause)
  if not part.patches or #part.patches == 0 then return part end
  local out = {tile = part.tile, n = 0, x = {}, y = {}, z = {}, yaw = {}, scale = {}, wide = {}, shape = {}}
  local function put(x,y,z,yaw,scale,shape,wide)
    local n = out.n + 1; out.n = n
    out.x[n],out.y[n],out.z[n],out.yaw[n],out.scale[n],out.shape[n],out.wide[n] = x,y,z,yaw,scale,shape,wide or scale
  end
  for k = 1, part.staticN do put(part.x[k],part.y[k],part.z[k],part.yaw[k],part.scale[k],part.shape[k]) end
  local level, T = part.level, M.TUFT
  for _, patch in ipairs(part.patches) do
    local long, dry = patch.tall, patch.dry
    for k = 1, #patch.samples, 4 do
      local slot, lush, thin, crop = sampleOf(patch.samples[k])
      local z, gx, gy = patch.samples[k+1], patch.samples[k+2], patch.samples[k+3]
      local sx, sy = slot % 4, math.floor(slot / 4)
      local even = (sx + sy) % 2 == 0
      local x = patch.x + sx * 2 + 1
      local y = patch.y + sy * 2 + 1
      local kept = 0
      local wildHeight, wildKeep, weeds = M.wild(x, y)
      for iy = -1, 1 do for ix = -1, 1 do
        -- which ring owns this tuft (OWN): the square's middle is the far ring's in every other
        -- square and the middle ring's in the rest
        local own, shapeOf = OWN[ix][iy], T
        if not own then own = even and 3 or 2; shapeOf = even and T.far or T.mid
        elseif own == 2 then shapeOf = T.corner
        elseif own == 1 then shapeOf = T.inner end
        local show = level == nil or level == own
        -- thin grass keeps two of the near and inner tufts (the near ring's, by this order)
        if own <= 1 and thin then
          kept = kept + 1
          show = show and kept <= T.thin
        end
        -- Lua 5.1 leaves a negative remainder; a cell west or south of the origin is negative.
        local h = math.floor(x) * 73856093 + math.floor(y) * 19349663 + (ix + 2) * 83492791 + (iy + 2) * 2654435761
        h = h % 2147483647
        if h < 0 then h = h + 2147483647 end
        -- thinned to bare ground (M.WILD.gap): the same tufts go in every ring; a field is not
        if show and wildKeep < 1 and not crop then show = (math.floor(h / 1030301) % 997) / 997 < wildKeep end
        if show then
          local stray = own > 0 and T.stray or .12
          local jx, jy = (h % 101) / 100 - .5, (math.floor(h / 101) % 101) / 100 - .5
          local dx, dy = ix * (2 / 3) + jx * stray, iy * (2 / 3) + jy * stray
          local r = (math.floor(h / 10201) % 101) / 100
          local shape, span, bottom, height, wide
          if crop == 'wheat' then
            local C, set = M.CROP.wheat, dry or patch
            local model = h % #set.shapes + 1
            shape, span, bottom = set.shapes[model], set.spans[model], set.bottoms[model]
            dx, dy = ix * (2 / 3) + jx * C.stray, iy * (2 / 3) + jy * C.stray
            height, wide = C.low + r * (C.high - C.low), 1
            if own > 0 then wide = shapeOf.wide end
          elseif crop and long then
            -- rows across x (rows: lines of constant y) or across y (rowsY)
            local C, model = M.CROP.rows, h % #long.shapes + 1
            shape, span, bottom = long.shapes[model], long.spans[model], long.bottoms[model]
            if crop == 'rowsY' then dx, dy = ix * (2 / 3) + jx * C.across, iy * (2 / 3) + jy * C.along
            else dx, dy = ix * (2 / 3) + jx * C.along, iy * (2 / 3) + jy * C.across end
            height, wide = C.low + r * (C.high - C.low), own > 0 and T.long.wide or 1
          elseif lush and long and own > 0 then
            local model = h % #long.shapes + 1
            shape, span, bottom = long.shapes[model], long.spans[model], long.bottoms[model]
            height, wide = T.long.low + r * (T.long.high - T.long.low), T.long.wide
          elseif weeds and long and not thin and own > 0 then
            -- a clump of coarse weeds in the short grass (M.WILD.weed)
            local W, model = M.WILD.weed, h % #long.shapes + 1
            shape, span, bottom = long.shapes[model], long.spans[model], long.bottoms[model]
            height, wide = W.low + r * (W.high - W.low), T.long.wide
          elseif thin and dry then
            -- dry land's own tufts (the game's dry grass), not green ones on a yellow slope
            local model = h % #dry.shapes + 1
            shape, span, bottom = dry.shapes[model], dry.spans[model], dry.bottoms[model]
            height, wide = (.3 + r * .2) * wildHeight, 1
            if own > 0 then height, wide = height * shapeOf.tall, shapeOf.wide end
          else
            local model = h % 3 + 1
            shape, span, bottom = patch.shapes[model], patch.spans[model], patch.bottoms[model]
            height, wide = (.27 + r * .28) * wildHeight, 1
            if own > 0 then height, wide = height * shapeOf.tall, shapeOf.wide
            elseif lush then height = height * 1.35 end
          end
          local scale = height / span
          -- XY scale is independent of the height multiplier: a far tuft is broader than tall
          put(x + dx, y + dy, z + gx * dx + gy * dy - bottom * scale, h % 6283 / 1000, scale, shape,
            own > 0 and scale * wide or scale)
        end
      end end
    end
    if pause then pause() end
  end
  return out
end

-- create(parts, pause) -> handle builds one cell (it may call pause() between pieces);
-- destroy(handle) removes it. Both run inside step()'s time-sliced coroutine.
-- A part is one tile's objects of one kind in one cell as plain arrays (x, y, z, yaw,
-- scale, shape, n): a table per tuft kept ~200k tables alive for the game's collector.
function M.new(create, destroy)
  -- count: live objects by group (every grass ring is 'grass')
  local self = {cells = {}, live = {}, count = {grass = 0, rock = 0}, cellsLive = 0, serial = 0, revision = 0}

  local function cellOf(kind, x, y)
    local key = kind .. ':' .. x .. ':' .. y
    local cell = self.cells[key]
    local CELL = cellSize(kind)
    if not cell then
      cell = {key = key, kind = kind, parts = {}, n = 0, rev = 0, x = (x + .5) * CELL, y = (y + .5) * CELL, zSum = 0}
      self.cells[key] = cell
    end
    return cell
  end

  local function partOf(kind, tile, x, y)
    local width = cellSize(kind)
    local cell = cellOf(kind, math.floor(x / width), math.floor(y / width))
    local part = cell.parts[tile]
    if not part then
      self.serial = self.serial + 1
      part = {tile = tile, serial = self.serial, n = 0, staticN = 0, zSum = 0, patches = {}, x = {}, y = {}, z = {}, yaw = {}, scale = {}, shape = {},
        level = M.RINGS[kind] and M.RINGS[kind].level}
      cell.parts[tile] = part
      tile.detailCells = tile.detailCells or {}
      tile.detailCells[#tile.detailCells + 1] = cell.key
    end
    return cell, part
  end

  function self:add(tile, it)
    local kind = M.kind(it)
    if not kind then return false end
    if it.grassPatch then
      -- one patch, a share of its tufts in each ring's cell
      local patch = it.grassPatch
      for ring, def in pairs(M.RINGS) do
        local n, zs = M.patchCount(patch, def.level)
        if n > 0 then
          local cell, part = partOf(ring, tile, it.pos[1], it.pos[2])
          part.patches[#part.patches + 1] = patch
          part.n, part.zSum = part.n + n, part.zSum + zs
          cell.n, cell.rev, cell.zSum = cell.n + n, cell.rev + 1, cell.zSum + zs
        end
      end
      self.revision = self.revision + 1
      return true
    end
    local cell, part = partOf(kind, tile, it.pos[1], it.pos[2])
    local n, rot, z = part.staticN + 1, it.rot, it.pos[3] or 0
    part.staticN, part.n, part.zSum = n, part.n + 1, part.zSum + z
    part.x[n], part.y[n], part.z[n] = it.pos[1], it.pos[2], z
    part.yaw[n] = rot and 2 * math.atan2(rot[3] or 0, rot[4] or 1) or 0
    part.scale[n], part.shape[n] = it.scale or 1, it.shape
    cell.n, cell.rev, cell.zSum = cell.n + 1, cell.rev + 1, cell.zSum + z
    self.revision = self.revision + 1
    return true
  end

  function self:remove(tile)
    for _, key in ipairs(tile.detailCells or {}) do
      local cell = self.cells[key]
      local part = cell and cell.parts[tile]
      if part then
        cell.parts[tile] = nil
        local zs = part.zSum
        cell.n, cell.rev, cell.zSum = cell.n - part.n, cell.rev + 1, cell.zSum - zs
        if cell.n <= 0 and not self.live[cell.key] then self.cells[cell.key] = nil end
      end
    end
    tile.detailCells = nil
    self.revision = self.revision + 1
  end

  local function drop(key)
    local entry = self.live[key]
    if not entry then return end
    destroy(entry.handle)
    self.live[key] = nil
    local group = GROUP[entry.kind]
    self.count[group], self.cellsLive = self.count[group] - entry.n, self.cellsLive - 1
    local cell = self.cells[key]
    if cell and cell.n <= 0 then self.cells[key] = nil end
  end

  function self:clear()
    for key in pairs(self.live) do drop(key) end
    self.cells, self.live, self.work = {}, {}, nil
    self.count, self.cellsLive = {grass = 0, rock = 0}, 0
    self.revision = self.revision + 1
  end

  local function distance(cell, p)
    local z = cell.n > 0 and cell.zSum / cell.n or (p.z or 0)
    return (cell.x - p.x) ^ 2 + (cell.y - p.y) ^ 2 + (z - (p.z or z)) ^ 2
  end

  function self:step(p, tune, now, timer, budget)
    if not p then return end
    self.focus, self.tune = p, tune
    if not self.work then
      if self.last and now - self.last < .25 and self.seen == self.revision
        and self.lastP and (p.x - self.lastP.x) ^ 2 + (p.y - self.lastP.y) ^ 2 + ((p.z or 0) - (self.lastP.z or 0)) ^ 2 < 16 then return end
      self.last, self.seen, self.lastP = now, self.revision, {x = p.x, y = p.y, z = p.z}
      self.work = coroutine.create(function()
        local checks, made, dropped = 0, 0, 0
        local function pause(force)
          checks = checks + 1
          if force or checks % 16 == 0 then
            if self.timer:stop() >= self.budget then coroutine.yield(); made, dropped = 0, 0 end
          end
        end
        -- however cheap the clock says a frame was: at most two new cells and 16 removals
        local function mutated(what)
          if what == 'made' then made = made + 1 else dropped = dropped + 1 end
          if made >= 2 or dropped >= 16 then coroutine.yield(); made, dropped = 0, 0 end
        end
        -- Whole cells, nearest first, while the kind's total stays under its cap. A live cell
        -- keeps its place out to 10% past the radius so it does not flicker on the edge.
        local wanted, ordered, taken = {}, {}, {grass = 0, rock = 0}
        for _, kind in ipairs(M.KINDS) do
          local CELL = cellSize(kind)
          local radius, cap = M.limits(kind, tune)
          -- the rings share one budget: a ring takes its share of what the nearer ones left
          local group = GROUP[kind]
          local whole = group == 'grass' and (tune.grassBudget or 0) or cap
          cap = math.min(cap, whole - taken[group])
          if radius > 0 and cap > 0 then
            local reach = radius * 1.1 + CELL * .71
            local candidates = {}
            for x = math.floor((p.x - reach) / CELL), math.floor((p.x + reach) / CELL) do
              for y = math.floor((p.y - reach) / CELL), math.floor((p.y + reach) / CELL) do
                local cell = self.cells[kind .. ':' .. x .. ':' .. y]
                if cell and cell.n > 0 then
                  local d = distance(cell, p)
                  local limit = (self.live[cell.key] and radius * 1.1 or radius) + CELL * .71
                  if d <= limit * limit then candidates[#candidates + 1] = {cell = cell, d = d * (self.live[cell.key] and .85 or 1)} end
                end
                pause()
              end
            end
            table.sort(candidates, function(a, b) return a.d == b.d and a.cell.key < b.cell.key or a.d < b.d end)
            local total = 0
            for _, c in ipairs(candidates) do
              if total + c.cell.n > cap then break end
              total = total + c.cell.n
              wanted[c.cell.key] = true
              ordered[#ordered + 1] = c.cell
            end
            taken[group] = taken[group] + total
          end
        end
        -- Remove before creating, so the caps also hold while the camera moves. A cell whose
        -- objects changed (a tile came or went) is rebuilt.
        local keys = {}
        for key in pairs(self.live) do keys[#keys + 1] = key end
        for _, key in ipairs(keys) do
          local entry, cell = self.live[key], self.cells[key]
          if not wanted[key] or not cell or entry.rev ~= cell.rev then drop(key); mutated('dropped'); pause(true) end
        end
        for _, cell in ipairs(ordered) do
          -- the camera may have moved since the selection (this pass spans frames)
          local kind = cell.kind
          local CELL = cellSize(kind)
          local group = GROUP[kind]
          local limit = M.limits(kind, self.tune) + CELL * .71
          local whole = group == 'grass' and (self.tune.grassBudget or 0) or (self.tune.rockBudget or 0)
          if not self.live[cell.key] and self.cells[cell.key] == cell and cell.n > 0
              and self.count[group] + cell.n <= whole and distance(cell, self.focus) <= limit * limit then
            local parts, n = {}, 0
            for _, part in pairs(cell.parts) do
              if not part.tile.dropped then parts[#parts + 1] = part; n = n + part.n end
            end
            table.sort(parts, function(a, b) return a.serial < b.serial end)
            local rev = cell.rev
            local handle = create(parts, function() pause(true) end)
            -- the cell may have changed while create() yielded; the next pass rebuilds it
            self.live[cell.key] = {handle = handle, n = n, rev = rev, kind = kind}
            self.count[group], self.cellsLive = self.count[group] + n, self.cellsLive + 1
            mutated('made')
            pause(true)
          end
        end
      end)
    end
    -- The closure's clock must be the current frame, including after a yield.
    self.timer, self.budget = timer, budget
    local ok, err = coroutine.resume(self.work)
    if not ok then self.work = nil; error(err) end
    if coroutine.status(self.work) == 'dead' then self.work = nil end
  end
  return self
end
return M
