-- Grass (8 m cells) and loose rocks (32 m cells) around the camera: cell objects appear
-- and go together (TSStatic without collision), at most two cells a frame. Each kind has
-- its own reach and total cap (tune.grassM / grassBudget, rockM / rockBudget).
local M = {}
M.CELL = 32
M.GRASS_CELL = 8
local function cellSize(kind) return kind == 'grass' and M.GRASS_CELL or M.CELL end
M.KINDS = {'grass', 'rock'}
-- A kept grass patch holds its samples as one float array (FFI): as a Lua array they were ~2 million numbers round
-- a town that every full collection of the game's Lua scanned (most of a 250 ms freeze). Without FFI: Lua arrays.
local okFfi, ffi = pcall(require, 'ffi')
if not okFfi then ffi = nil end
local NONE = {}

function M.kind(it)
  local s = it and it.shape
  if it and it.kind ~= 'proc' and type(s) == 'string' then
    -- grass tufts, and the clover, daisy and fern patches beside them (all East Coast
    -- groundcover): placed per tile as TSStatics they cost ~3 ms a frame in Obolon (vegab-obolon)
    if s:find('3d_grass', 1, true) or s:find('/groundcover/', 1, true) then return 'grass' end
    if s:find('/rocks/', 1, true) then return 'rock' end
  end
end


-- Compact 8 m patches carry only the accepted 2 m squares and their local ground planes.
-- Expand only a live cell, never every blade of every loaded 500 m tile. Nine short tufts
-- fill each square on a 2/3 m grid, so neighbouring squares meet. The descriptor's n already
-- counts those nine, so selection enforces the actual TSStatic budget.
function M.expand(part, pause)
  if not part.psamples and not (part.patches and #part.patches > 0) then
    if not part.x then part.x, part.y, part.z, part.yaw, part.scale, part.shape = {}, {}, {}, {}, {}, {} end
    return part
  end
  local out = {tile = part.tile, n = 0, x = {}, y = {}, z = {}, yaw = {}, scale = {}, shape = {}}
  local function put(x,y,z,yaw,scale,shape)
    local n = out.n + 1; out.n = n
    out.x[n],out.y[n],out.z[n],out.yaw[n],out.scale[n],out.shape[n] = x,y,z,yaw,scale,shape
  end
  for k = 1, part.staticN do put(part.x[k],part.y[k],part.z[k],part.yaw[k],part.scale[k],part.shape[k]) end
  -- a part keeps its one patch in p* fields, more in part.patches
  local function expandPatch(px, py, shapes, spans, bottoms, samples, count)
    -- samples: slot, z, gx, gy per accepted square (a float array from 0 with its count, or a Lua array from 1)
    local base = count and 0 or 1
    for k = base, (count or #samples) - 1 + base, 4 do
      local slot, z, gx, gy = samples[k], samples[k+1], samples[k+2], samples[k+3]
      local x = px + (slot % 4) * 2 + 1
      local y = py + math.floor(slot / 4) * 2 + 1
      for iy = -1, 1 do for ix = -1, 1 do
        -- Lua 5.1 leaves a negative remainder; a cell west or south of the origin is negative.
        local h = math.floor(x) * 73856093 + math.floor(y) * 19349663 + (ix + 2) * 83492791 + (iy + 2) * 2654435761
        h = h % 2147483647
        if h < 0 then h = h + 2147483647 end
        local dx = ix * (2 / 3) + ((h % 101) / 100 - .5) * .12
        local dy = iy * (2 / 3) + ((math.floor(h / 101) % 101) / 100 - .5) * .12
        local model = h % 3 + 1
        local height = .32 + (math.floor(h / 10201) % 101) / 100 * .18
        local scale = height / spans[model]
        put(x + dx, y + dy, z + gx * dx + gy * dy - bottoms[model] * scale,
          h % 6283 / 1000, scale, shapes[model])
      end end
    end
  end
  if part.psamples then
    expandPatch(part.px, part.py, part.pshapes, part.pspans, part.pbottoms, part.psamples, part.pcount)
    if pause then pause() end
  end
  for _, p in ipairs(part.patches or NONE) do
    expandPatch(p.x, p.y, p.shapes, p.spans, p.bottoms, p.samples, p.count)
    if pause then pause() end
  end
  return out
end

-- create(parts, pause) -> handle builds one cell (it may call pause() between pieces);
-- destroy(handle) removes it. Both run inside step()'s time-sliced coroutine.
-- A part is one tile's objects of one kind in one cell as plain arrays (x, y, z, yaw,
-- scale, shape, n): a table per tuft kept ~200k tables alive for the game's collector.
function M.new(create, destroy)
  local self = {cells = {}, live = {}, count = {grass = 0, rock = 0}, cellsLive = 0, serial = 0, revision = 0}
  local CELL = M.CELL

  local function cellOf(kind, x, y)
    local key = kind .. ':' .. x .. ':' .. y
    local cell = self.cells[key]
    local CELL = cellSize(kind)
    if not cell then
      -- a cell keeps its first tile's part inline (tile1, part1): a map of one tile per 8 m cell was a table each
      cell = {key = key, kind = kind, n = 0, rev = 0, x = (x + .5) * CELL, y = (y + .5) * CELL, zSum = 0}
      self.cells[key] = cell
    end
    return cell
  end

  local function partOf(cell, tile)
    if cell.tile1 == tile then return cell.part1 end
    return cell.parts and cell.parts[tile]
  end

  function self:add(tile, it)
    local kind = M.kind(it)
    if not kind then return false end
    local width = cellSize(kind)
    local cell = cellOf(kind, math.floor(it.pos[1] / width), math.floor(it.pos[2] / width))
    local part = partOf(cell, tile)
    if not part then
      self.serial = self.serial + 1
      -- the arrays come with the part's first item of their sort: an 8 m grass cell is patches only, and seven empty
      -- tables for each of the ~30k cells round a town were most of what the game's full collections walked
      part = {tile = tile, serial = self.serial, n = 0, staticN = 0, zSum = 0}
      if cell.part1 == nil then cell.tile1, cell.part1 = tile, part
      else cell.parts = cell.parts or {}; cell.parts[tile] = part end
      tile.detailCells = tile.detailCells or {}
      tile.detailCells[#tile.detailCells + 1] = cell.key
    end
    if it.grassPatch then
      local patch = it.grassPatch
      local samples = patch.samples
      local count = patch.count or #samples
      local n, zs = count / 4 * 9, 0
      local base = patch.count and 0 or 1
      for k = 0, count - 1, 4 do zs = zs + samples[k + base + 1] * 9 end
      if ffi and not patch.count and count > 0 then
        local packed = ffi.new('float[?]', count)
        for k = 1, count do packed[k - 1] = samples[k] end
        samples = packed
      else
        count = patch.count
      end
      -- a part's one patch lives in the part (p* fields), more go to part.patches: a patch table per 8 m cell
      if not part.psamples and not part.patches then
        part.px, part.py, part.pshapes, part.pspans, part.pbottoms = patch.x, patch.y, patch.shapes, patch.spans, patch.bottoms
        part.psamples, part.pcount = samples, count
      else
        if part.psamples then
          part.patches = {{x = part.px, y = part.py, shapes = part.pshapes, spans = part.pspans, bottoms = part.pbottoms,
            samples = part.psamples, count = part.pcount}}
          part.px, part.py, part.pshapes, part.pspans, part.pbottoms, part.psamples, part.pcount = nil, nil, nil, nil, nil, nil, nil
        end
        patch.samples, patch.count = samples, count
        part.patches[#part.patches + 1] = patch
      end
      part.n, part.zSum = part.n + n, part.zSum + zs
      cell.n, cell.rev, cell.zSum = cell.n + n, cell.rev + 1, cell.zSum + zs
      self.revision = self.revision + 1
      return true
    end
    if not part.x then part.x, part.y, part.z, part.yaw, part.scale, part.shape = {}, {}, {}, {}, {}, {} end
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
      local part = cell and partOf(cell, tile)
      if part then
        if cell.tile1 == tile then cell.tile1, cell.part1 = nil, nil else cell.parts[tile] = nil end
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
    self.count[entry.kind], self.cellsLive = self.count[entry.kind] - entry.n, self.cellsLive - 1
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
        local wanted, ordered = {}, {}
        for _, kind in ipairs(M.KINDS) do
          local CELL = cellSize(kind)
          local radius, cap = tune[kind .. 'M'] or 0, tune[kind .. 'Budget'] or 0
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
          local limit = (self.tune[kind .. 'M'] or 0) + CELL * .71
          if not self.live[cell.key] and self.cells[cell.key] == cell and cell.n > 0
              and self.count[kind] + cell.n <= (self.tune[kind .. 'Budget'] or 0) and distance(cell, self.focus) <= limit * limit then
            local parts, n = {}, 0
            local function take(part)
              if not part.tile.dropped then parts[#parts + 1] = part; n = n + part.n end
            end
            if cell.part1 then take(cell.part1) end
            for _, part in pairs(cell.parts or NONE) do take(part) end
            table.sort(parts, function(a, b) return a.serial < b.serial end)
            local rev = cell.rev
            local handle = create(parts, function() pause(true) end)
            -- the cell may have changed while create() yielded; the next pass rebuilds it
            self.live[cell.key] = {handle = handle, n = n, rev = rev, kind = kind}
            self.count[kind], self.cellsLive = self.count[kind] + n, self.cellsLive + 1
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
