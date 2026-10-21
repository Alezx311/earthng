-- Grass and loose rocks around the camera, in whole 32 m cells: a cell's objects appear
-- and go together (TSStatic without collision), at most two cells a frame. Each kind has
-- its own reach and total cap (tune.grassM / grassBudget, rockM / rockBudget).
local M = {}
M.CELL = 32
M.KINDS = {'grass', 'rock'}

function M.kind(it)
  local s = it and it.shape
  if it and it.kind ~= 'proc' and type(s) == 'string' then
    -- grass tufts, and the clover, daisy and fern patches beside them (all East Coast
    -- groundcover): placed per tile as TSStatics they cost ~3 ms a frame in Obolon (vegab-obolon)
    if s:find('3d_grass', 1, true) or s:find('/groundcover/', 1, true) then return 'grass' end
    if s:find('/rocks/', 1, true) then return 'rock' end
  end
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
    if not cell then
      cell = {key = key, kind = kind, parts = {}, n = 0, rev = 0, x = (x + .5) * CELL, y = (y + .5) * CELL, zSum = 0}
      self.cells[key] = cell
    end
    return cell
  end

  function self:add(tile, it)
    local kind = M.kind(it)
    if not kind then return false end
    local cell = cellOf(kind, math.floor(it.pos[1] / CELL), math.floor(it.pos[2] / CELL))
    local part = cell.parts[tile]
    if not part then
      self.serial = self.serial + 1
      part = {tile = tile, serial = self.serial, n = 0, x = {}, y = {}, z = {}, yaw = {}, scale = {}, shape = {}}
      cell.parts[tile] = part
      tile.detailCells = tile.detailCells or {}
      tile.detailCells[#tile.detailCells + 1] = cell.key
    end
    local n, rot, z = part.n + 1, it.rot, it.pos[3] or 0
    part.n = n
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
        local zs = 0
        for k = 1, part.n do zs = zs + part.z[k] end
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
          local limit = (self.tune[kind .. 'M'] or 0) + CELL * .71
          if not self.live[cell.key] and self.cells[cell.key] == cell and cell.n > 0
              and self.count[kind] + cell.n <= (self.tune[kind .. 'Budget'] or 0) and distance(cell, self.focus) <= limit * limit then
            local parts, n = {}, 0
            for _, part in pairs(cell.parts) do
              if not part.tile.dropped then parts[#parts + 1] = part; n = n + part.n end
            end
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
