-- Engine-native EarthNG provider. Country ZIPs contain source cells; the Lua
-- generator creates the same road/scene manifests as the streaming renderer.
-- A place with no pack can still be played: live.lua downloads OSM and
-- elevation in this process and keeps the cells in memory. No companion.
local M = {}
local catalog = require('ge/extensions/e2r/countries')
local generator = require('ge/extensions/e2r/generator')
local coordinates = require('ge/extensions/e2r/coordinates')
local cellformat = require('ge/extensions/e2r/cellformat')
local liveOk, liveMod = pcall(require, 'ge/extensions/e2r/live')
local live = liveOk and type(liveMod) == 'table' and type(liveMod.sync) == 'function' and liveMod or nil
-- TILE_LIMIT holds the whole wanted set (1 km near plus the 3 km far ring, ~130 tiles): a
-- delivered tile keeps only flags, while undelivered geometry is bounded by triangles/vertices.
-- At 32 the far ring evicted itself and was rebuilt after every 250 m.
local CELL_LIMIT, TILE_LIMIT, TRIANGLE_LIMIT, VERTEX_LIMIT, LAND_RADIUS = 32, 160, 80000, 240000, 500
-- 8: at a seam a tile reads its own region's blocks and a neighbour's (foreignCell)
local BLOCK_LIMIT = 8
-- Prepared horizon meshes, separate from the near/far triangle budget above. The 5 km ring
-- is the one that is scheduled; 15 km and 30 km stay off until an in-game check.
local HORIZON_RADIUS, HORIZON_TILE_LIMIT, HORIZON_TRIANGLE_LIMIT = 5000, 96, 250000
local HORIZON_STEP, HORIZON_BLOCK = 100, 1000
-- The vista: from a summit or a pass the land past 5 km is in view. When the camera stands
-- VISTA_RELIEF over the lowest ground known round it and moves slower than VISTA_SPEED, the
-- horizon runs on to VISTA_RADIUS in 4 km blocks of 400 m steps, read from the cells' elevation
-- grids alone (cellformat.terrain). Driving never schedules it.
local VISTA_RADIUS, VISTA_BLOCK, VISTA_STEP, VISTA_RELIEF, VISTA_SPEED = 24000, 4000, 400, 250, 15
-- The road ahead at speed (night 26.10: a central Kyiv near tile took ~1 s of Lua, ~4 s at the
-- frame's budget, and at 300 km/h the car ran off the built roads). A near tile's priority is the
-- time the car takes to reach it: along its heading, a step sideways counting `across` times
-- (a step back `back` times), blended in from `slow` to `fast` m/s; below that the old distance.
-- Past the near radius the tiles a `corridor` s drive ahead (within `half` m of the heading line,
-- `reach` m at most) are near too. A tile's road goes out before its scene (generator.lua
-- roadReady): its scene waits `lag` s plus `lagPerMs` s for every m/s over `slow`, in at most
-- `parked` suspended builds. Under `urgent` s from a missing road the frame gives the generator
-- `urgentMs`.
local AHEAD = {across = 3, back = 3, slow = 10, fast = 30, corridor = 15, half = 150, reach = 2000,
  lag = 3, lagPerMs = .1, parked = 3, urgent = 6, urgentMs = 6}
local FORMATS = {['earthng-features-v1'] = 1, ['earthng-features-v2'] = 2}
-- the climate under the vista's far plane (generator.lua loads the same module)
local okBiome, biomeModule = pcall(require, 'ge/extensions/e2r/biome')
local BIOME = okBiome and type(biomeModule) == 'table' and type(biomeModule.at) == 'function' and biomeModule or nil
local PLANE_GROUND = {desert = 'desert', steppe = 'steppe', mediterranean = 'dry_grass', savanna = 'dry_grass',
  tundra = 'tundra', ice = 'snow'}
local NONE_LIST = {}
local state, regions, active

local function finite(v)
  return type(v) == 'number' and v == v and v ~= math.huge and v ~= -math.huge
end

local function array(v)
  if type(v) ~= 'table' then return false end
  local n = 0
  for k in pairs(v) do
    if type(k) ~= 'number' or k < 1 or k % 1 ~= 0 then return false end
    n = n + 1
  end
  return n == #v
end

local function vector(v, n)
  if not array(v) or #v ~= n then return false end
  for _, x in ipairs(v) do if not finite(x) then return false end end
  return true
end

local function rect(v)
  return vector(v, 4) and v[1] < v[3] and v[2] < v[4]
end

local function geoBox(v)
  return rect(v) and v[1] >= -180 and v[3] <= 180 and v[2] >= -90 and v[4] <= 90
end

local function inside(b, x, y)
  return x >= b[1] and x <= b[3] and y >= b[2] and y <= b[4]
end

local function insideAny(boxes, x, y)
  for _, b in ipairs(boxes or {}) do if inside(b, x, y) then return true end end
  return false
end

local function pathIn(path, prefix, extension)
  extension = extension or '.json'
  if type(path) ~= 'string' or path:sub(1, #prefix) ~= prefix
    or path:find('[%z\1-\31\\:%?%#%%]') or path:find('//', 1, true) then return false end
  for p in path:gmatch('[^/]+') do if p == '.' or p == '..' then return false end end
  return path:sub(-#extension) == extension
end

local function exists(path)
  local ok, found = pcall(function() return FS:fileExists(path) end)
  return ok and found == true
end

local function read(path)
  if not exists(path) then error('missing mounted source: ' .. path) end
  local ok, value = pcall(jsonReadFile, path)
  if not ok or type(value) ~= 'table' then error('invalid source JSON: ' .. path) end
  return value
end

local function keyOf(i, j) return string.format('%d_%d', i, j) end

-- Raw bytes through the game's VFS (country ZIPs are mounted, never unpacked).
local function readBytes(path)
  if not exists(path) then error('missing mounted source: ' .. path) end
  local f = io.open(path, 'rb')
  if not f then error('cannot open mounted source: ' .. path) end
  local data = f:read('*a')
  f:close()
  if type(data) ~= 'string' then error('cannot read mounted source: ' .. path) end
  return data
end

-- A country pack stores 8 x 8 km blocks. A live window stores one cell per block
-- (blockCells 1, held in memory) so a cell can appear later without rewriting its neighbour.
local function blocksOf(d)
  local b = type(d) == 'table' and d.blockCells
  if type(b) ~= 'number' or b ~= b or b < 1 or b > cellformat.BLOCK or b % 1 ~= 0 then return cellformat.BLOCK end
  return b
end

-- v1 lists every cell in its manifest; v2 keeps a 64-bit presence mask per block,
-- so a whole country's manifest stays small and nothing is enumerated at startup.
local function ownCell(r, i, j)
  local d = r.data
  if d.schemaVersion ~= 2 then return d.cells[keyOf(i, j)] ~= nil end
  local b = blocksOf(d)
  local block = d.blocks[keyOf(math.floor(i / b), math.floor(j / b))]
  return block ~= nil and cellformat.present(block.mask, i % b + (j % b) * b)
end

-- The landing region also has the cells a neighbour region can give it (foreignOf, below):
-- the drive goes on past its edge.
local foreignOf
local function hasCell(r, i, j)
  if ownCell(r, i, j) then return true end
  return active ~= nil and r == active.region and foreignOf(i, j) ~= nil
end

local function geographic(r, x, y)
  if r.projection then return r.projection.geographic(x, y) end
  local g = r.data.geo
  local dx, dy = x - g[1], y - g[2]
  return g[3] + g[5] * dx + g[6] * dy, g[4] + g[7] * dx + g[8] * dy
end

local function localPoint(r, lat, lon)
  if r.projection then return r.projection.localPoint(lat, lon) end
  local g = r.data.geo
  local dx, dy = lon - g[3], lat - g[4]
  local determinant = g[5] * g[8] - g[6] * g[7]
  return g[1] + (dx * g[8] - dy * g[6]) / determinant,
    g[2] + (dy * g[5] - dx * g[7]) / determinant
end

local function affineAt(r, x, y)
  return r.projection and r.projection.affineAt(x, y) or r.data.geo
end

-- --- neighbour regions ----------------------------------------------------------------------------
-- The world is the landing region's frame, and the drive may leave the region (a route of 100 km
-- crosses two or three of them). A cell the landing region lacks comes from a neighbour region
-- that has all of the cell (docs/NAVIGATION.md «Сусідні регіони»): its features move into this
-- frame by an affine fitted on the cell's corners (a translation within one UTM zone, a turn of
-- ~2 degrees across a zone border), its elevation is resampled onto this cell's own grid (one grid
-- a cell, so the tiles at a seam agree), and its roads, numbered per region, get the region's id
-- as a prefix. New lookups are capped a frame: each projects a few points.
local FOREIGN_NEW = 48

foreignOf = function(i, j)
  local a = active
  if not a or not a.foreign then return nil end
  local k = (i + 1048576) * 2097152 + (j + 1048576)
  local hit = a.foreign[k]
  if hit ~= nil then return hit or nil end
  if a.foreignNew >= FOREIGN_NEW then a.foreignShort = true; return nil end
  a.foreignNew = a.foreignNew + 1
  local r0 = a.region
  local s = r0.data.cellSize
  local x0, y0, x1, y1 = i * s, j * s, (i + 1) * s, (j + 1) * s
  local lon, lat = geographic(r0, (x0 + x1) / 2, (y0 + y1) / 2)
  local found = false
  for _, r in ipairs(regions) do
    if r ~= r0 and r.data.schemaVersion == 2 and r.country.id ~= 'live' and insideAny(r.descriptor.coverage, lon, lat) then
      local fx0, fy0, fx1, fy1 = math.huge, math.huge, -math.huge, -math.huge
      for _, c in ipairs({{x0, y0}, {x1, y0}, {x0, y1}, {x1, y1}}) do
        local clon, clat = geographic(r0, c[1], c[2])
        local fx, fy = localPoint(r, clat, clon)
        fx0, fy0, fx1, fy1 = math.min(fx0, fx), math.min(fy0, fy), math.max(fx1, fx), math.max(fy1, fy)
      end
      local fs, cells, whole = r.data.cellSize, {}, true
      for fi = math.floor(fx0 / fs), math.ceil(fx1 / fs) - 1 do
        for fj = math.floor(fy0 / fs), math.ceil(fy1 / fs) - 1 do
          if not ownCell(r, fi, fj) then whole = false end
          cells[#cells + 1] = {fi, fj}
        end
      end
      if whole then
        -- r's frame -> this one on three corners of the box: X = m1 + m3 dx + m5 dy, Y = m2 + m4 dx + m6 dy
        local function here(x, y) local lo, la = geographic(r, x, y); return localPoint(r0, la, lo) end
        local ax, ay = here(fx0, fy0)
        local bx, by = here(fx1, fy0)
        local cx, cy = here(fx0, fy1)
        local w, h = fx1 - fx0, fy1 - fy0
        local m = {ax, ay, (bx - ax) / w, (by - ay) / w, (cx - ax) / h, (cy - ay) / h, fx0, fy0}
        local det = m[3] * m[6] - m[5] * m[4]
        found = {region = r, cells = cells, m = m, inv = {m[6] / det, -m[4] / det, -m[5] / det, m[3] / det},
          prefix = 'f' .. tostring(r.descriptor.id) .. ':'}
        break
      end
    end
  end
  a.foreign[k] = found
  return found or nil
end

-- this frame -> the neighbour's (the inverse of foreignOf's affine)
local function toForeign(f, x, y)
  local m, inv = f.m, f.inv
  local dx, dy = x - m[1], y - m[2]
  return m[7] + inv[1] * dx + inv[3] * dy, m[8] + inv[2] * dx + inv[4] * dy
end

local function moveFeatures(cell, f, pause)
  local m, moved = f.m, 0
  local function move(p)
    local dx, dy = p[1] - m[7], p[2] - m[8]
    p[1], p[2] = m[1] + m[3] * dx + m[5] * dy, m[2] + m[4] * dx + m[6] * dy
    moved = moved + 1
    if moved % 512 == 0 then pause() end
  end
  for _, road in ipairs(cell.roads or NONE_LIST) do
    road.id = f.prefix .. tostring(road.id)
    for _, p in ipairs(road.points or NONE_LIST) do move(p) end
  end
  for _, kind in ipairs({'junctions', 'buildings', 'areas'}) do
    for _, feature in ipairs(cell[kind] or NONE_LIST) do
      for _, ring in ipairs(feature.rings or NONE_LIST) do
        for _, p in ipairs(ring) do move(p) end
      end
    end
  end
  for _, line in ipairs(cell.lines or NONE_LIST) do
    for _, p in ipairs(line.points or NONE_LIST) do move(p) end
  end
  for _, point in ipairs(cell.points or NONE_LIST) do
    if point.pos then move(point.pos) end
  end
end

local function gridHeight(grid, x, y)
  local box = grid.rect
  local gx = math.max(0, math.min(grid.nx - 1, (x - box[1]) / (box[3] - box[1]) * (grid.nx - 1)))
  local gy = math.max(0, math.min(grid.ny - 1, (y - box[2]) / (box[4] - box[2]) * (grid.ny - 1)))
  local ix, iy = math.min(grid.nx - 2, math.floor(gx)), math.min(grid.ny - 2, math.floor(gy))
  local tx, ty = gx - ix, gy - iy
  local h, row = grid.heights, iy * grid.nx + ix + 1
  return (h[row] * (1 - tx) + h[row + 1] * tx) * (1 - ty) + (h[row + grid.nx] * (1 - tx) + h[row + grid.nx + 1] * tx) * ty
end

-- The neighbour's elevation on this cell's grid (as fine as the neighbour's own)
local function resampled(f, parts, i, j)
  local s = active.region.data.cellSize
  local nx, ny = parts[1].terrain.nx, parts[1].terrain.ny
  local x0, y0 = i * s, j * s
  local heights, low = {}, math.huge
  for gj = 0, ny - 1 do
    for gi = 0, nx - 1 do
      local fx, fy = toForeign(f, x0 + gi * s / (nx - 1), y0 + gj * s / (ny - 1))
      local best, bestD
      for _, part in ipairs(parts) do
        local b = part.terrain.rect
        local d = math.max(b[1] - fx, fx - b[3], 0) + math.max(b[2] - fy, fy - b[4], 0)
        if not bestD or d < bestD then best, bestD = part.terrain, d end
      end
      local z = gridHeight(best, fx, fy)
      heights[#heights + 1] = z
      if z < low then low = z end
    end
    if gj % 16 == 15 then active.pause() end
  end
  return {rect = {x0, y0, x0 + s, y0 + s}, nx = nx, ny = ny, heights = heights}, low
end

-- Source metadata is an exact metric grid. Geographic bounding boxes alone are
-- insufficient: projected neighbouring cells have overlapping geographic boxes.
local function covered(r, x0, y0, x1, y1)
  local s = r.data.cellSize
  local i0, j0 = math.floor((x0 + 0.000001) / s), math.floor((y0 + 0.000001) / s)
  local i1, j1 = math.ceil((x1 - 0.000001) / s) - 1, math.ceil((y1 - 0.000001) / s) - 1
  for i = i0, i1 do
    for j = j0, j1 do if not hasCell(r, i, j) then return false end end
  end
  return true
end

local function geoRect(r, b)
  local w, s, e, n = math.huge, math.huge, -math.huge, -math.huge
  for _, p in ipairs({{b[1], b[2]}, {b[3], b[2]}, {b[1], b[4]}, {b[3], b[4]}}) do
    local lon, lat = geographic(r, p[1], p[2])
    w, s, e, n = math.min(w, lon), math.min(s, lat), math.max(e, lon), math.max(n, lat)
  end
  return {w, s, e, n}
end

local function addIssue(country, region, message)
  state.errors[#state.errors + 1] = {id = country.id, region = region and region.id,
    path = region and region.manifest or country.manifest, code = 'native-source', message = tostring(message)}
end

-- A landing point is safe when its 500 m tile and LAND_RADIUS round it have source cells.
local function safeAt(r, x, y)
  local t = r.data.tileSize
  local i, j = math.floor(x / t), math.floor(y / t)
  return covered(r, i * t - LAND_RADIUS, j * t - LAND_RADIUS, (i + 1) * t + LAND_RADIUS, (j + 1) * t + LAND_RADIUS)
end

local function validateBlocks(country, d)
  if d.blockCells ~= cellformat.BLOCK or type(d.blocks) ~= 'table' then error('invalid source block grid') end
  if not array(d.coverage) or #d.coverage == 0 then error('region coverage must be a nonempty array') end
  for _, box in ipairs(d.coverage) do if not geoBox(box) then error('invalid region coverage box') end end
  local count = 0
  for key, block in pairs(d.blocks) do
    local i, j
    if type(key) == 'string' then i, j = key:match('^(-?%d+)_(-?%d+)$') end
    i, j = tonumber(i), tonumber(j)
    if not i or not j or math.abs(i) > 1000000 or math.abs(j) > 1000000 or key ~= keyOf(i, j) or type(block) ~= 'table'
      or type(block.mask) ~= 'string' or #block.mask ~= 16 or block.mask:find('[^0-9a-f]')
      or not pathIn(block.path, country.namespace, '.bin') then error('invalid source block: ' .. tostring(key)) end
    count = count + 1
  end
  if count == 0 then error('region has no source blocks') end
end

local function validateRegion(country, descriptor)
  local d = read(descriptor.manifest)
  if (d.schemaVersion ~= 1 and d.schemaVersion ~= 2) or d.id ~= descriptor.id or d.runtime ~= 'lua' then
    error('region must use schemaVersion 1 or 2, its declared id and runtime lua')
  end
  if d.schemaVersion == 2 and d.sourceFormat ~= 'earthng-features-v2' then error('schemaVersion 2 needs earthng-features-v2') end
  if d.tileSize ~= 500 or not finite(d.cellSize) or d.cellSize < d.tileSize
    or d.cellSize > 10000 or d.cellSize % d.tileSize ~= 0 then error('invalid tileSize/cellSize grid') end
  if not geoBox(d.bounds) or not vector(d.geo, 8) then error('invalid region bounds/geo affine') end
  if math.abs(d.geo[5] * d.geo[8] - d.geo[6] * d.geo[7]) < 1e-18 then error('singular geo affine') end
  local r = {country = country, descriptor = descriptor, data = d, coverage = {},
    projection = type(coordinates.frame) == 'function' and coordinates.frame(d.frame) or nil}
  if d.schemaVersion == 2 then
    validateBlocks(country, d)
    -- The author picked a road cell with a full neighbourhood; checked here against the masks.
    if not vector(d.landing, 2) or not safeAt(r, d.landing[1], d.landing[2]) then
      error('no complete landing neighbourhood in exported source cells')
    end
    local b = cellformat.BLOCK
    local first = d.blocks[keyOf(math.floor(math.floor(d.landing[1] / d.cellSize) / b),
      math.floor(math.floor(d.landing[2] / d.cellSize) / b))]
    if not exists(first.path) then error('missing mounted source block: ' .. first.path) end
    r.landing, r.coverage = {d.landing[1], d.landing[2]}, d.coverage
    return r
  end
  if type(d.cells) ~= 'table' then error('region cells must be an object') end
  local prefix, count = country.namespace, 0
  for key, cell in pairs(d.cells) do
    local i, j
    if type(key) == 'string' then i, j = key:match('^(-?%d+)_(-?%d+)$') end
    i, j = tonumber(i), tonumber(j)
    if not i or not j or math.abs(i) > 1000000 or math.abs(j) > 1000000 or key ~= keyOf(i, j) or type(cell) ~= 'table' or not rect(cell.bounds)
      or not pathIn(cell.path, prefix) or not exists(cell.path) then error('invalid or missing source cell: ' .. tostring(key)) end
    local expected = {i * d.cellSize, j * d.cellSize, (i + 1) * d.cellSize, (j + 1) * d.cellSize}
    for k = 1, 4 do if math.abs(cell.bounds[k] - expected[k]) > 0.001 then error('source cell bounds do not match grid: ' .. key) end end
    count = count + 1
  end
  if count == 0 then error('region has no mounted source cells') end
  r.safe = {}
  -- Erode the exported cell union by the startup radius. Each advertised rectangle
  -- can land with the full 1 km neighbourhood, including at holes and outer edges.
  for _, cell in pairs(d.cells) do
    local b, t = cell.bounds, d.tileSize
    for x = b[1], b[3] - t, t do
      for y = b[2], b[4] - t, t do
        if covered(r, x - LAND_RADIUS, y - LAND_RADIUS, x + t + LAND_RADIUS, y + t + LAND_RADIUS) then
          local safe = {x, y, x + t, y + t}
          r.safe[#r.safe + 1] = safe
          r.coverage[#r.coverage + 1] = geoRect(r, safe)
        end
      end
    end
  end
  table.sort(r.safe, function(a, b) return a[1] == b[1] and a[2] < b[2] or a[1] < b[1] end)
  if #r.safe == 0 then error('no complete landing neighbourhood in exported source cells') end
  r.landing = {(r.safe[1][1] + r.safe[1][3]) / 2, (r.safe[1][2] + r.safe[1][4]) / 2}
  return r
end

local function refresh()
  local countries, errors = catalog.refresh()
  regions, active = {}, nil
  state = {provider = 'native', native = true, countries = countries, errors = {}, coverage = {}, regions = {},
    countryCount = 0, job = nil, stream = nil}
  for _, issue in ipairs(errors or {}) do state.errors[#state.errors + 1] = issue end
  for _, country in ipairs(countries) do
    local accepted = 0
    if country.runtime == 'native' and FORMATS[country.sourceFormat] then
      local requested = country.landing
      country.landing = nil
      for _, descriptor in ipairs(country.regions) do
        local ok, r = pcall(validateRegion, country, descriptor)
        if ok then
          regions[#regions + 1] = r
          accepted = accepted + 1
          local lon, lat = geographic(r, r.landing[1], r.landing[2])
          if not country.landing then country.landing = {lat = lat, lon = lon} end
          -- A grid region has no title of its own. The country name there made one button per
          -- cell, all labelled the same. A section zip names its county and is the only jump.
          local section = descriptor.section == true
          local entry = {id = descriptor.id, country = country.id,
            title = section and (descriptor.title or descriptor.id) or (descriptor.title or country.title),
            bounds = r.data.bounds, coverage = r.coverage, landing = {lat = lat, lon = lon}}
          if section then entry.section = true end
          state.regions[#state.regions + 1] = entry
          for _, box in ipairs(r.coverage) do
            state.coverage[#state.coverage + 1] = box
            local b = state.packageBox
            state.packageBox = b and {math.min(b[1], box[1]), math.min(b[2], box[2]), math.max(b[3], box[3]), math.max(b[4], box[4])}
              or {box[1], box[2], box[3], box[4]}
          end
        else
          addIssue(country, descriptor, r)
        end
      end
      -- The author's button point (e.g. the capital) wins when it is landable here.
      if type(requested) == 'table' and finite(requested.lat) and finite(requested.lon) then
        for _, r in ipairs(regions) do
          if r.country == country and insideAny(r.descriptor.coverage, requested.lon, requested.lat) then
            local x, y = localPoint(r, requested.lat, requested.lon)
            if safeAt(r, x, y) then country.landing = {lat = requested.lat, lon = requested.lon}; break end
          end
        end
      end
    elseif country.runtime ~= 'source' then
      addIssue(country, nil, 'country requires runtime native and sourceFormat earthng-features-v1 or v2')
    end
    country.available = accepted > 0
    country.reason = country.available and nil or (country.runtime == 'source' and 'source-only' or 'no-playable-source')
    if country.available then state.countryCount = state.countryCount + 1 end
  end
  state.catalog = {countries = state.countries, errors = state.errors}
  return state
end

local function ensure() if not state then refresh() end end

local function at(lat, lon)
  ensure()
  if not finite(lat) or not finite(lon) or lat < -90 or lat > 90 or lon < -180 or lon > 180 then return nil end
  for _, r in ipairs(regions) do
    if insideAny(r.country.coverage, lon, lat) and insideAny(r.descriptor.coverage, lon, lat) then
      local x, y = localPoint(r, lat, lon)
      if safeAt(r, x, y) and covered(r, x - LAND_RADIUS, y - LAND_RADIUS, x + LAND_RADIUS, y + LAND_RADIUS) then
        return r.country, r.descriptor, x, y, r
      end
    end
  end
  if live then
    local r = live.sync()
    if r and insideAny(r.coverage, lon, lat) then
      local x, y = localPoint(r, lat, lon)
      if safeAt(r, x, y) and covered(r, x - LAND_RADIUS, y - LAND_RADIUS, x + LAND_RADIUS, y + LAND_RADIUS) then
        return r.country, r.descriptor, x, y, r
      end
    end
  end
end

local function touch() active.clock = active.clock + 1; return active.clock end

local function evict(cache, limit, protected, onRemove)
  local count = 0
  for _ in pairs(cache) do count = count + 1 end
  while count > limit do
    local oldest, oldestAt
    for key, entry in pairs(cache) do
      if not (protected and protected[key]) and (not oldestAt or entry.used < oldestAt) then oldest, oldestAt = key, entry.used end
    end
    if not oldest then break end
    cache[oldest] = nil
    if onRemove then onRemove(oldest) end
    count = count - 1
  end
end

-- A block file (2-3 MB in central Kyiv) in 256 KB reads with a pause between them: one read
-- was a 44 ms stretch of the generator (a zip entry inflates as it is read). Only in the
-- generation coroutine.
local function readPaused(path)
  if not exists(path) then error('missing mounted source: ' .. path) end
  local f = io.open(path, 'rb')
  if not f then error('cannot open mounted source: ' .. path) end
  local parts = {}
  while true do
    local s = f:read(262144)
    if not s then break end
    parts[#parts + 1] = s
    if #s < 262144 then break end
    active.pause()
  end
  f:close()
  return table.concat(parts)
end

local function loadBlock(key, block)
  local hit = active.blocks[key]
  if hit then hit.used = touch(); return hit end
  local data = readPaused(block.path)
  active.pause()
  hit = {data = data, slots = cellformat.block(data), used = touch()}
  active.blocks[key] = hit
  -- One live cell is one block file. The country-pack limit of 6 would reread every tile.
  evict(active.blocks, blocksOf(active.region.data) == 1 and 64 or BLOCK_LIMIT)
  return hit
end

-- A cell of the landing region's grid made of a neighbour's (foreignOf). memo holds the
-- neighbour's cells decoded for this tile, moved already: the 2-4 of them under a cell are
-- shared by the tile's cells, and the generator drops the copies by id.
local function foreignCell(f, key, i, j, keep, memo, terrainOnly)
  local r = f.region
  local fs, fb = r.data.cellSize, blocksOf(r.data)
  local keepF
  if keep then
    local x0, y0, x1, y1 = math.huge, math.huge, -math.huge, -math.huge
    for _, c in ipairs({{keep[1], keep[2]}, {keep[3], keep[2]}, {keep[1], keep[4]}, {keep[3], keep[4]}}) do
      local fx, fy = toForeign(f, c[1], c[2])
      x0, y0, x1, y1 = math.min(x0, fx), math.min(y0, fy), math.max(x1, fx), math.max(y1, fy)
    end
    keepF = {x0, y0, x1, y1}
  end
  memo = memo or {}
  local parts = {}
  local margin = cellformat.ROAD_MARGIN
  for _, c in ipairs(f.cells) do
    local rect = {c[1] * fs, c[2] * fs, (c[1] + 1) * fs, (c[2] + 1) * fs}
    -- A feature is stored in every cell it touches: one reaching the tile is in a cell that
    -- meets the tile's box, ROAD_MARGIN out. The other parts under this cell give elevation only
    -- (the grid, not the features: a tile parsed up to nine neighbour cells instead of 1-4).
    local whole = not terrainOnly and (not keepF or rect[1] <= keepF[3] + margin and rect[3] >= keepF[1] - margin
      and rect[2] <= keepF[4] + margin and rect[4] >= keepF[2] - margin)
    local base = f.prefix .. c[1] .. '_' .. c[2]
    local cell = memo[base] or (not whole and memo[base .. ':t'])
    if not cell then
      local blockKey = keyOf(math.floor(c[1] / fb), math.floor(c[2] / fb))
      local loaded = loadBlock(f.prefix .. blockKey, r.data.blocks[blockKey])
      local range = loaded.slots[c[1] % fb + (c[2] % fb) * fb]
      if not range then error('neighbour block lacks cell: ' .. base) end
      if whole then
        cell = cellformat.cell(loaded.data, range[1], range[2], rect[1], rect[2], rect, active.pause, keepF)
        moveFeatures(cell, f, active.pause)
        memo[base] = cell
      else
        cell = cellformat.terrain(loaded.data, range[1], range[2], rect)
        memo[base .. ':t'] = cell
      end
    end
    parts[#parts + 1] = cell
  end
  local terrain, low = resampled(f, parts, i, j)
  active.lows[key] = active.lows[key] or low
  local out = {terrain = terrain, low = low, foreign = r.descriptor.id}
  for _, kind in ipairs({'roads', 'junctions', 'buildings', 'areas', 'lines', 'points'}) do
    local list = {}
    if not terrainOnly then
      for _, part in ipairs(parts) do
        for _, feature in ipairs(part[kind] or NONE_LIST) do list[#list + 1] = feature end
      end
    end
    out[kind] = list
  end
  return out
end

-- keep: the tile's rectangle. A v2 cell is decoded for one tile and never cached: only the
-- features reaching the tile become tables, and decoded points are the bulk of the Lua heap the
-- game's collector walks every cycle (a dense 1 km cell is 6-10 MB of them). The block bytes
-- stay cached; a string costs the collector nothing.
local function loadCell(key, i, j, keep, memo)
  local hit = active.cells[key]
  if hit then hit.used = touch(); return hit.data end
  local d = active.region.data
  if d.schemaVersion == 2 then
    local b, s = blocksOf(d), d.cellSize
    local blockKey = keyOf(math.floor(i / b), math.floor(j / b))
    local block = d.blocks[blockKey]
    if not ownCell(active.region, i, j) then
      local f = foreignOf(i, j)
      if not f then error('missing source cell: ' .. key) end
      return foreignCell(f, key, i, j, keep, memo)
    end
    if block.memory and live and type(live.cell) == 'function' then
      local cell = live.cell(i, j)
      if type(cell) ~= 'table' or type(cell.terrain) ~= 'table' then error('missing live cell: ' .. key) end
      if not active.lows[key] then
        local low = math.huge
        for _, h in ipairs(cell.terrain.heights) do if h < low then low = h end end
        active.lows[key] = low
      end
      return cell
    end
    local loaded = loadBlock(blockKey, block)
    local range = loaded.slots[i % b + (j % b) * b]
    if not range then error('source block lacks cell: ' .. key) end
    local cell = cellformat.cell(loaded.data, range[1], range[2], i * s, j * s,
      {i * s, j * s, (i + 1) * s, (j + 1) * s}, active.pause, keep)
    if not active.lows[key] then
      local low = math.huge
      for _, h in ipairs(cell.terrain.heights) do if h < low then low = h end end
      active.lows[key] = low
    end
    return cell
  end
  local descriptor = d.cells[key]
  if not descriptor then error('missing source cell: ' .. key) end
  local cell = read(descriptor.path)
  for _, field in ipairs({'roads', 'junctions', 'buildings', 'areas', 'lines', 'points'}) do
    if cell[field] ~= nil and not array(cell[field]) then error('source cell ' .. field .. ' must be an array') end
  end
  local terrain = cell.terrain
  if type(terrain) ~= 'table' or not rect(terrain.rect) or not finite(terrain.nx) or not finite(terrain.ny)
    or terrain.nx % 1 ~= 0 or terrain.ny % 1 ~= 0 or terrain.nx < 2 or terrain.ny < 2
    or terrain.nx > 257 or terrain.ny > 257 or not array(terrain.heights)
    or #terrain.heights ~= terrain.nx * terrain.ny then error('invalid source elevation grid') end
  for _, height in ipairs(terrain.heights) do if not finite(height) then error('invalid source elevation sample') end end
  local checked = 0
  local function coordinates(points, minimum)
    if not array(points) or #points < minimum then error('invalid source geometry coordinates') end
    for _, p in ipairs(points) do
      if not array(p) or (#p ~= 2 and #p ~= 3) then error('invalid source geometry point') end
      for _, v in ipairs(p) do if not finite(v) or math.abs(v) > 1e12 then error('non-finite source geometry point') end end
      checked = checked + 1
      if checked % 128 == 0 then coroutine.yield() end
    end
  end
  for _, field in ipairs({'roads', 'junctions', 'buildings', 'areas', 'lines', 'points'}) do
    for _, feature in ipairs(cell[field] or {}) do
      if type(feature) ~= 'table' or (feature.tags ~= nil and type(feature.tags) ~= 'table') then error('invalid source feature') end
      for _, n in ipairs({'width', 'height', 'minHeight'}) do
        if feature[n] ~= nil and not finite(feature[n]) then error('non-finite source feature ' .. n) end
      end
      if field == 'roads' or field == 'lines' then
        coordinates(feature.points, 2)
      elseif field == 'points' then
        coordinates({feature.pos}, 1)
      else
        if not array(feature.rings) or #feature.rings == 0 then error('invalid source polygon rings') end
        for _, ring in ipairs(feature.rings) do coordinates(ring, 3) end
      end
    end
  end
  active.cells[key] = {data = cell, used = touch()}
  evict(active.cells, CELL_LIMIT)
  if not active.lows[key] then
    local low = math.huge
    for _, h in ipairs(terrain.heights) do if h < low then low = h end end
    active.lows[key] = low
  end
  return cell
end

local function tileCovered(r, i, j)
  local t = r.data.tileSize
  return covered(r, i * t, j * t, (i + 1) * t, (j + 1) * t)
end

-- A horizon tile may end past the package. Any overlapping source cell is enough: the mesh
-- omits samples the DEM does not cover and skirts that edge.
local function touchesCell(r, x0, y0, x1, y1)
  local s = r.data.cellSize
  for i = math.floor(x0 / s), math.ceil(x1 / s) - 1 do
    for j = math.floor(y0 / s), math.ceil(y1 / s) - 1 do
      if hasCell(r, i, j) then return true end
    end
  end
  return false
end

local function needSquare(r, x, y)
  local out, t = {}, r.data.tileSize
  for i = math.floor((x - LAND_RADIUS) / t), math.ceil((x + LAND_RADIUS) / t) - 1 do
    for j = math.floor((y - LAND_RADIUS) / t), math.ceil((y + LAND_RADIUS) / t) - 1 do
      if not tileCovered(r, i, j) then return nil end
      out[keyOf(i, j)] = {i, j}
    end
  end
  return out
end

local function fail(message)
  if state.job then state.job.state, state.job.stage, state.job.message = 'error', 'source', tostring(message) end
end

local function spawnValid(manifest)
  local sp = manifest and manifest.spawn
  return manifest and manifest.drivable == true and type(sp) == 'table' and vector(sp.pos, 3) and finite(sp.yaw)
end

local function completeLanding()
  local land = active and active.landing
  if not land or state.job.state ~= 'working' then return end
  local done, total = 0, 0
  for key in pairs(land.required) do total = total + 1; if active.tiles[key] then done = done + 1 end end
  state.job.progress = total > 0 and done / total or 0
  if done < total then return end
  if not land.selected then
    local best, distance
    for key in pairs(land.required) do
      local entry = active.tiles[key]
      if entry and spawnValid(entry.road) then
        local p = entry.road.spawn.pos
        local sq = needSquare(active.region, p[1], p[2])
        if sq then
          local d = (p[1] - land.x) ^ 2 + (p[2] - land.y) ^ 2
          if not distance or d < distance then best, distance = {key = key, square = sq}, d end
        end
      end
    end
    -- No road within reach (a summit, a desert, the tundra): the car stands on the ground at the
    -- point itself. Every tile's spawn there is that point on the DEM (its build centre is the
    -- landing); a road nearby still wins.
    if not best then
      local t = active.region.data.tileSize
      local key = keyOf(math.floor(land.x / t), math.floor(land.y / t))
      local entry = active.tiles[key]
      local sp = entry and entry.road and entry.road.spawn
      if sp and vector(sp.pos, 3) and finite(sp.yaw) and land.required[key] then
        best = {key = key, square = needSquare(active.region, sp.pos[1], sp.pos[2]) or {}}
        entry.road.offRoad = true
      end
    end
    if not best then fail('no_drivable_spawn: no road with a complete source neighbourhood'); return end
    land.selected = best.key
    for key, ij in pairs(best.square) do land.required[key] = ij end
    active.prioritiesDirty = true
    completeLanding()
    return
  end
  local entry = active.tiles[land.selected]
  local job, p = state.job, entry.road.spawn.pos
  job.state, job.stage, job.progress, job.manifest = 'ready', 'ready', 1, entry.road
  job.tile = entry.road.tile
  -- The DEM horizon replaces the spawn-minus-40 plane. A companion job that still
  -- passes a numeric horizonZ keeps that plane (world.lua skips it only when this is nil).
  job.horizonDem = true
  job.horizonZ = nil
  job.timings = {native = true}
  active.pose = {x = p[1], y = p[2], vx = 0, vy = 0}
  active.prioritiesDirty = true
end

-- Shared quality policy; fresh profiles start at Balanced, saved settings win.
local quality = require('ge/extensions/e2r/quality')
local pendingTune = quality.preset(50)

local function clampTune(tune)
  return quality.clamp(tune)
end

local function land(req)
  ensure()
  req = type(req) == 'table' and req or {}
  state.job = {seq = req.seq, lat = req.lat, lon = req.lon, state = 'working', stage = 'source', progress = 0}
  local country, descriptor, x, y, r = at(req.lat, req.lon)
  if not r then fail('no_data: this point has no complete mounted source neighbourhood'); return state.job end
  active = {region = r, cells = {}, blocks = {}, tiles = {}, horizon = {}, failed = {}, clock = 0, everBuilt = {}, desired = {}, evicted = {}, epoch = 1,
    parked = {},   -- tile key -> {co}: a near tile whose road is out and whose scene waits (update)
    lows = {},   -- cell key -> its lowest ground (world z), for the vista's relief
    foreign = {}, foreignNew = 0,   -- cells from neighbour regions (foreignOf)
    epochPoint = {x, y}, prioritiesDirty = true, startupPinned = true,
    manifests = setmetatable({}, {__mode = 'v'}),
    landing = {x = x, y = y, required = needSquare(r, x, y)}, pose = {x = x, y = y, vx = 0, vy = 0}}
  -- Generation hands the frame back only when update()'s budget is spent. A yield at every
  -- pause point (thousands per tile) capped the work per frame by the number of resumes and
  -- broke LuaJIT's traces in every hot loop; the clock is read at every 8th point.
  local a, calls = active, 0
  active.pause = function()
    calls = calls + 1
    if calls % 8 == 0 and a.timer and a.timer:stop() >= a.budget then coroutine.yield() end
  end
  state.stream = {region = descriptor.id, country = country.id, live = country.id == 'live' or nil,
    tile = r.data.tileSize, generator = 'earthng-lua-v1',
    geo = affineAt(r, x, y), bounds = r.data.bounds, ready = {}, scenes = {}, far = {}, horizon = {}, wanted = {}, readyCount = 0,
    building = 0, queued = 0, failed = active.failed, built = 0, rebuilds = 0, horizonBuilt = 0, horizonRebuilds = 0,
    meanBuildSeconds = 0, loadRadius = 1000, farRadius = 3000, farFast = 25,
    horizonRadius = HORIZON_RADIUS, horizonDem = true}
  if pendingTune then
    active.tune = pendingTune
    state.stream.loadRadius = pendingTune.nearM
    state.stream.farRadius = pendingTune.farM
  end
  state.job.region, state.job.country, state.job.tileSize = descriptor.id, country.id, r.data.tileSize
  state.job.generator = state.stream.generator
  return state.job
end

local function priorities()
  local a, out = active, {}
  if not a then return out end
  local p, t, st = a.pose, a.region.data.tileSize, state.stream
  local speed = math.sqrt((p.vx or 0) ^ 2 + (p.vy or 0) ^ 2)
  local ahead = math.min(speed * 3, 2000)
  local ax, ay = p.x + (speed > 0 and (p.vx or 0) / speed * ahead or 0),
    p.y + (speed > 0 and (p.vy or 0) / speed * ahead or 0)
  local tune = a.tune or {}
  local radius, farRadius = tune.nearM or 1000, tune.farM or 3000
  st.loadRadius, st.farRadius = radius, farRadius
  -- the heading, the corridor's end and the weight of the heading in a near tile's arrival time
  local ux, uy = speed > 0 and (p.vx or 0) / speed or 0, speed > 0 and (p.vy or 0) / speed or 0
  local reach = speed >= 15 and math.min(speed * AHEAD.corridor, AHEAD.reach) or 0
  local ex, ey = p.x + ux * reach, p.y + uy * reach
  local w = math.max(0, math.min(1, (speed - AHEAD.slow) / (AHEAD.fast - AHEAD.slow)))
  local ext = t / 2 * (math.abs(ux) + math.abs(uy))
  local span = math.max(radius, AHEAD.half + t)
  for i = math.floor(math.min(p.x - farRadius, ax - radius, ex - span) / t), math.floor(math.max(p.x + farRadius, ax + radius, ex + span) / t) do
    for j = math.floor(math.min(p.y - farRadius, ay - radius, ey - span) / t), math.floor(math.max(p.y + farRadius, ay + radius, ey + span) / t) do
      local cx, cy = (i + 0.5) * t, (j + 0.5) * t
      local d = math.min(math.sqrt((cx - p.x) ^ 2 + (cy - p.y) ^ 2), math.sqrt((cx - ax) ^ 2 + (cy - ay) ^ 2))
      local farD = math.sqrt((cx - p.x) ^ 2 + (cy - p.y) ^ 2)
      -- the renderer drops tiles well behind the car at speed (world.lua updateTiles, behind());
      -- wanting them back here rebuilt each one after it was dropped
      local behind = speed >= 15 and ((cx - p.x) * p.vx + (cy - p.y) * p.vy) < 0 and farD > radius * 0.6 + 250
      local along = (cx - p.x) * ux + (cy - p.y) * uy
      local alongE = math.max(0, math.abs(along) - ext)
      local acrossE = math.max(0, math.abs((cx - p.x) * uy - (cy - p.y) * ux) - ext)
      local corridor = reach > 0 and along > 0 and alongE <= reach and acrossE <= AHEAD.half
      if tileCovered(a.region, i, j) then
        if (d <= radius or corridor) and not behind then
          local iso = d / math.max(speed, 5)
          local arrival = ((along < 0 and AHEAD.back or 1) * alongE + AHEAD.across * acrossE) / math.max(speed, 5)
          out[keyOf(i, j)] = {i = i, j = j, priority = iso + (arrival - iso) * w, size = t}
        elseif farD <= farRadius then
          -- Ground stays wanted at any speed. Buildings and trees are the part that used to
          -- churn the far ring above 90 km/h; they wait until the car slows down.
          out[keyOf(i, j)] = {i = i, j = j, far = true, decor = speed <= st.farFast,
            priority = 1e6 + farD, size = t}
        end
      end
    end
  end
  -- DEM-only horizon past the far ring. A 1000 m block is one mesh when all four of its
  -- 500 m quadrants sit in the annulus, so it shares edges with the far tiles and does not
  -- cover them. A ragged quadrant is its own 500 m mesh. Past 5 km only the vista (above).
  local function centreDistance(cx, cy)
    return math.sqrt((cx - p.x) ^ 2 + (cy - p.y) ^ 2)
  end
  -- The vista's relief: the camera over the lowest ground of the cells decoded within 5 km.
  local outer = HORIZON_RADIUS
  if p.z and speed < VISTA_SPEED then
    local low, cs = math.huge, a.region.data.cellSize
    for key, h in pairs(a.lows) do
      local ci, cj = key:match('^(-?%d+)_(-?%d+)$')
      ci, cj = tonumber(ci), tonumber(cj)
      if ci and h < low and centreDistance((ci + .5) * cs, (cj + .5) * cs) <= HORIZON_RADIUS then low = h end
    end
    if p.z - low >= VISTA_RELIEF then outer = VISTA_RADIUS end
  end
  st.horizonRadius, st.vista = outer, outer > HORIZON_RADIUS and outer or nil
  -- Past the vista the land is a plane at the lowest ground it has found, in that place's ground
  -- (the sea where it is the sea), for world.lua to lay out under the haze
  st.vistaLow, st.vistaGround = nil, nil
  if st.vista then
    local low, lowKey, cs = math.huge, nil, a.region.data.cellSize
    for key, h in pairs(a.lows) do
      local ci, cj = key:match('^(-?%d+)_(-?%d+)$')
      ci, cj = tonumber(ci), tonumber(cj)
      if ci and h < low and centreDistance((ci + .5) * cs, (cj + .5) * cs) <= outer then low, lowKey = h, {ci, cj} end
    end
    if lowKey then
      local sea = finite(a.region.data.seaLevel) and a.region.data.seaLevel or 20
      local cx, cy, geo = (lowKey[1] + .5) * cs, (lowKey[2] + .5) * cs, a.region.data.geo
      local wet = low <= sea + .5 and not (BIOME and BIOME.inland(geo, cx, cy))
      local place = BIOME and BIOME.available() and BIOME.at(geo, cx, cy)
      st.vistaLow = wet and sea + .3 or low - 15
      st.vistaGround = wet and 'water' or (place and PLANE_GROUND[place.group]) or 'forest'
    end
  end
  -- 4 km vista blocks whose 500 m quadrants all lie past 5 km and within the vista
  -- 4 km vista blocks: every 500 m quadrant past 5 km, the block reaching into the vista (the
  -- outer edge goes out a little past VISTA_RADIUS in whole blocks: 1 km tiles there were ~600)
  local vistaBlocks = {}
  if outer > HORIZON_RADIUS then
    local half = t / 2
    for vi = math.floor((p.x - outer) / VISTA_BLOCK), math.floor((p.x + outer) / VISTA_BLOCK) do
      for vj = math.floor((p.y - outer) / VISTA_BLOCK), math.floor((p.y + outer) / VISTA_BLOCK) do
        local x0, y0 = vi * VISTA_BLOCK, vj * VISTA_BLOCK
        -- the quadrant centre nearest the camera
        local nx = math.max(x0 + half, math.min(x0 + VISTA_BLOCK - half, p.x))
        local ny = math.max(y0 + half, math.min(y0 + VISTA_BLOCK - half, p.y))
        local near = centreDistance(nx, ny)
        if near > HORIZON_RADIUS and near <= outer and touchesCell(a.region, x0, y0, x0 + VISTA_BLOCK, y0 + VISTA_BLOCK) then
          vistaBlocks[vi * 100000 + vj] = true
          local cx, cy = x0 + VISTA_BLOCK / 2, y0 + VISTA_BLOCK / 2
          out[string.format('v4000:%d_%d', vi, vj)] = {i = vi, j = vj, horizon = true, vista = true, far = true,
            decor = false, size = VISTA_BLOCK, step = VISTA_STEP, priority = 3e6 + centreDistance(cx, cy), x = cx, y = cy}
        end
      end
    end
  end
  -- Each 500 m quadrant outside the far ring is horizon to 5 km (full cells, as before) and vista
  -- past it (elevation only): a 1 km block whose four quadrants are alike is one mesh, else one
  -- mesh a quadrant. Quadrants inside a vista block are left to it.
  local minX, maxX = p.x - outer, p.x + outer
  local minY, maxY = p.y - outer, p.y + outer
  for bi = math.floor(minX / HORIZON_BLOCK), math.floor(maxX / HORIZON_BLOCK) do
    for bj = math.floor(minY / HORIZON_BLOCK), math.floor(maxY / HORIZON_BLOCK) do
      local inVista = vistaBlocks[math.floor(bi * HORIZON_BLOCK / VISTA_BLOCK) * 100000 + math.floor(bj * HORIZON_BLOCK / VISTA_BLOCK)]
      local quads = {{2 * bi, 2 * bj}, {2 * bi + 1, 2 * bj}, {2 * bi, 2 * bj + 1}, {2 * bi + 1, 2 * bj + 1}}
      local horizon, vista = {}, {}
      for _, q in ipairs(inVista and NONE_LIST or quads) do
        local cx, cy = (q[1] + 0.5) * t, (q[2] + 0.5) * t
        local dist = centreDistance(cx, cy)
        if dist > farRadius and dist <= HORIZON_RADIUS then
          horizon[#horizon + 1] = {i = q[1], j = q[2], d = dist, x = cx, y = cy}
        elseif dist > HORIZON_RADIUS and dist <= outer then
          vista[#vista + 1] = {i = q[1], j = q[2], d = dist, x = cx, y = cy}
        end
      end
      for _, set in ipairs({{horizon, 'h', 2e6, false, HORIZON_STEP}, {vista, 'v', 3e6, true, 200}}) do
        local list, prefix, base, isVista, coarse = set[1], set[2], set[3], set[4], set[5]
        if #list == 4 then
          local cx, cy = (bi + 0.5) * HORIZON_BLOCK, (bj + 0.5) * HORIZON_BLOCK
          local x0, y0 = bi * HORIZON_BLOCK, bj * HORIZON_BLOCK
          if touchesCell(a.region, x0, y0, x0 + HORIZON_BLOCK, y0 + HORIZON_BLOCK) then
            out[string.format('%s1000:%d_%d', prefix, bi, bj)] = {i = bi, j = bj, horizon = true, vista = isVista or nil,
              far = true, decor = false, size = HORIZON_BLOCK, step = coarse, priority = base + centreDistance(cx, cy), x = cx, y = cy}
          end
        else
          for _, q in ipairs(list) do
            local x0, y0 = q.i * t, q.j * t
            if touchesCell(a.region, x0, y0, x0 + t, y0 + t) then
              out[string.format('%s500:%d_%d', prefix, q.i, q.j)] = {i = q.i, j = q.j, horizon = true, vista = isVista or nil,
                far = true, decor = false, size = t, step = isVista and 100 or HORIZON_STEP, priority = base + q.d, x = q.x, y = q.y}
            end
          end
        end
      end
    end
  end
  if a.landing and state.job.state == 'working' then
    for key, ij in pairs(a.landing.required) do
      local dx, dy = (ij[1] + 0.5) * t - a.landing.x, (ij[2] + 0.5) * t - a.landing.y
      out[key] = {i = ij[1], j = ij[2], priority = -1e12 + dx * dx + dy * dy}
    end
  end
  st.wanted = {}
  local tiles, horizons = 0, 0
  for key, wanted in pairs(out) do
    st.wanted[key] = wanted.priority
    if not wanted.horizon then tiles = tiles + 1 else horizons = horizons + 1 end
  end
  a.horizonWanted = horizons
  -- The cache holds the whole wanted set. At OASIS (1.4 km near, 4 km far) that is ~230 tiles,
  -- over TILE_LIMIT: the far ring evicted itself, and a parked camera kept the holes for good
  -- (Innsbruck's Nordkette floated over the town as a ribbon of horizon).
  a.tileLimit = math.max(TILE_LIMIT, tiles + 16)
  a.desired = out
  a.prioritiesDirty = false
  return out
end

local function geometrySize(manifest)
  local triangles, vertices = 0, 0
  if not manifest then return triangles, vertices end
  for _, item in ipairs(manifest.items or {}) do
    if type(item.meshes) == 'table' then
      triangles = triangles + (finite(item.triangles) and item.triangles or 0)
      for _, mesh in ipairs(item.meshes) do vertices = vertices + #(mesh.verts or {}) end
    end
  end
  return triangles, vertices
end

-- Geometry still held only here. A layer the renderer has taken (manifest()) is queued for
-- spawning there: evicting it frees nothing and made the next update build the tile again.
local function entrySize(entry)
  local triangles, vertices = 0, 0
  for _, layer in ipairs({'road', 'scene', 'far', 'horizon'}) do
    if not entry[layer .. 'Taken'] then
      local t, v = geometrySize(entry[layer])
      triangles, vertices = triangles + t, vertices + v
    end
  end
  return triangles, vertices
end

local function inRenderer(entry)
  return (entry.roadTaken and not entry.roadDelivered) or (entry.sceneTaken and not entry.sceneDelivered)
    or (entry.farTaken and not entry.farDelivered)
end

local function trimTiles()
  local a, st = active, state.stream
  local count, triangles, vertices, cellCount = 0, 0, 0, 0
  for _ in pairs(a.cells) do cellCount = cellCount + 1 end
  for _, entry in pairs(a.tiles) do
    count, triangles, vertices = count + 1, triangles + entry.triangles, vertices + entry.vertices
  end
  local limit = a.tileLimit or TILE_LIMIT
  while count > limit or triangles > TRIANGLE_LIMIT or vertices > VERTEX_LIMIT do
    -- Over the geometry budget only an entry that holds geometry helps. Delivered layers weigh
    -- nothing: evicting them freed no triangles, dropped the whole far ring's bookkeeping and
    -- rebuilt it at the next epoch while its meshes were still on screen.
    local anyEntry = count > limit
    local worst, worstPriority, oldest
    for key, entry in pairs(a.tiles) do
      local required = a.landing and a.startupPinned and a.landing.required[key]
      local selected = a.startupPinned and a.landing and a.landing.selected == key
      local priority = a.desired[key] and a.desired[key].priority or 1e20
      local helps = anyEntry or entry.triangles > 0 or entry.vertices > 0
      -- a tile whose road is out and whose scene is being built or parked (update) stays
      local building = (a.parked and a.parked[key]) or (a.work and a.workKey == key and not a.workFar and not a.workHorizon)
      if helps and not required and not selected and not building and not inRenderer(entry) and (not worst or priority > worstPriority or (priority == worstPriority and entry.used < oldest)) then
        worst, worstPriority, oldest = key, priority, entry.used
      end
    end
    if not worst then break end -- The startup neighbourhood is the minimum working set.
    local removed = a.tiles[worst]
    count, triangles, vertices = count - 1, triangles - removed.triangles, vertices - removed.vertices
    a.tiles[worst] = nil
    if removed.road then a.evicted[worst .. ':road'] = a.epoch end
    if removed.far then a.evicted[worst .. ':far'] = a.epoch end
    st.ready[worst], st.scenes[worst], st.far[worst] = nil, nil, nil
  end
  local readyCount = 0
  for _, entry in pairs(a.tiles) do if entry.road then readyCount = readyCount + 1 end end
  st.readyCount, st.cachedTiles, st.cachedCells = readyCount, count, cellCount
  st.cachedTriangles, st.cachedVertices = triangles, vertices
  st.cacheLimits = {tiles = limit, cells = CELL_LIMIT, triangles = TRIANGLE_LIMIT, vertices = VERTEX_LIMIT}
  st.cacheOverBudget = count > limit or triangles > TRIANGLE_LIMIT or vertices > VERTEX_LIMIT
end

local function trimHorizon()
  local a, st = active, state.stream
  if not a then return end
  local count, triangles = 0, 0
  for _, entry in pairs(a.horizon) do
    count, triangles = count + 1, triangles + (entry.triangles or 0)
  end
  local limit = math.max(HORIZON_TILE_LIMIT, (a.horizonWanted or 0) + 16)
  while count > limit or triangles > HORIZON_TRIANGLE_LIMIT * (limit > HORIZON_TILE_LIMIT and 2 or 1) do
    local worst, worstPriority, oldest
    for key, entry in pairs(a.horizon) do
      local priority = a.desired[key] and a.desired[key].priority or 1e20
      local held = entry.horizonTaken and not entry.horizonDelivered
      if not held and (not worst or priority > worstPriority or (priority == worstPriority and entry.used < oldest)) then
        worst, worstPriority, oldest = key, priority, entry.used
      end
    end
    if not worst then break end
    local removed = a.horizon[worst]
    count, triangles = count - 1, triangles - (removed.triangles or 0)
    a.horizon[worst], st.horizon[worst] = nil, nil
    a.evicted[worst .. ':horizon'] = a.epoch
  end
  st.horizonTiles, st.horizonTriangles = count, triangles
  st.horizonResident = st.horizonResident or 0
end

-- A cell's elevation grid alone, for a vista block (16 cells of 1 km): nothing else decoded.
local function loadTerrain(key, i, j, memo)
  local d = active.region.data
  if d.schemaVersion ~= 2 then return loadCell(key, i, j) end
  if not ownCell(active.region, i, j) then
    local f = foreignOf(i, j)
    if not f then error('missing source cell: ' .. key) end
    return foreignCell(f, key, i, j, nil, memo, true)
  end
  local b, s = blocksOf(d), d.cellSize
  local blockKey = keyOf(math.floor(i / b), math.floor(j / b))
  local block = d.blocks[blockKey]
  if block and block.memory and live and type(live.cell) == 'function' then
    local cell = live.cell(i, j)
    if type(cell) ~= 'table' or type(cell.terrain) ~= 'table' then error('missing live cell: ' .. key) end
    if not cell.low then
      local low = math.huge
      for _, h in ipairs(cell.terrain.heights) do if h < low then low = h end end
      cell.low = low
    end
    active.lows[key] = active.lows[key] or cell.low
    return {terrain = cell.terrain, low = cell.low, roads = {}, junctions = {}, buildings = {},
      areas = {}, lines = {}, points = {}}
  end
  local loaded = loadBlock(blockKey, block)
  local range = loaded.slots[i % b + (j % b) * b]
  if not range then error('source block lacks cell: ' .. key) end
  local cell = cellformat.terrain(loaded.data, range[1], range[2], {i * s, j * s, (i + 1) * s, (j + 1) * s})
  active.lows[key] = active.lows[key] or cell.low
  return cell
end

local function buildTile(key, wanted)
  local r = active.region
  local size = wanted.size or r.data.tileSize
  local x0, y0 = wanted.i * size, wanted.j * size
  local tileRect = {x0, y0, x0 + size, y0 + size}
  local s, cells, seen, memo = r.data.cellSize, {}, {}, {}
  local function addCell(i, j, yield)
    if not hasCell(r, i, j) then return end
    local cellKey = keyOf(i, j)
    if seen[cellKey] then return end
    seen[cellKey] = true
    cells[#cells + 1] = wanted.vista and loadTerrain(cellKey, i, j, memo) or loadCell(cellKey, i, j, tileRect, memo)
    if yield then active.pause() end
  end
  for i = math.floor(x0 / s), math.ceil((x0 + size) / s) - 1 do
    for j = math.floor(y0 / s), math.ceil((y0 + size) / s) - 1 do addCell(i, j, true) end
  end
  -- One terrain step past the tile, so an edge normal can sample the neighbour grid
  -- instead of becoming one-sided. These few cells do not take their own pause: the
  -- tile's own cells already yield, and an extra yield rebuilt a neighbour after landing.
  local pad = 40
  for i = math.floor((x0 - pad) / s), math.ceil((x0 + size + pad) / s) - 1 do
    for j = math.floor((y0 - pad) / s), math.ceil((y0 + size + pad) / s) - 1 do addCell(i, j, false) end
  end
  -- At a seam both regions have the roads crossing it, under different ids: the landing
  -- region's copy stays, a neighbour's road with the same two OSM end nodes goes.
  local anyForeign, anyOwn = false, false
  for _, cell in ipairs(cells) do
    if cell.foreign then anyForeign = true else anyOwn = true end
  end
  if anyForeign and anyOwn then
    local own = {}
    for _, cell in ipairs(cells) do
      if not cell.foreign then
        for _, road in ipairs(cell.roads or NONE_LIST) do
          local n = road.nodes
          if n and n[1] then own[tostring(n[1]) .. '|' .. tostring(n[#n])] = true end
        end
      end
    end
    for _, cell in ipairs(cells) do
      if cell.foreign then
        local kept = {}
        for _, road in ipairs(cell.roads) do
          local n = road.nodes
          local a, b = n and tostring(n[1]), n and tostring(n[#n])
          if not (a and (own[a .. '|' .. b] or own[b .. '|' .. a])) then kept[#kept + 1] = road end
        end
        cell.roads = kept
      end
    end
  end
  local center = active.landing and {active.landing.x, active.landing.y} or nil
  local tune = active.tune or {}
  local st = state.stream
  local function stamp(road, nav)
    if road.spawn and not finite(road.spawn.yaw) and vector(road.spawn.dir, 3) then
      road.spawn.yaw = math.atan2(-road.spawn.dir[1], road.spawn.dir[2])
    end
    road.tile, road.source = {wanted.i, wanted.j}, r.descriptor.id
    road.materials = '/earthng/planet/materials.json'
    road.packs = '/e2r_stream/fast-art/v10/packs.json'
    road.navSegments = type(nav) == 'table' and nav.segments or {}
  end
  -- While driving a near tile's road goes out as soon as it is built (AHEAD), and the build
  -- yields AHEAD to update(), which parks it until the scene's turn. The landing builds whole.
  local early
  local roadReady = not wanted.far and not wanted.horizon and not active.startupPinned and function(road, nav)
    local entry = active.tiles[key] or {}
    if entry.road and entry.sceneLost then
      -- a rebuild for the scene alone: the renderer has this road already
      entry.sceneLost = nil
    else
      stamp(road, nav)
      entry.road, entry.nav, entry.scene = road, nav, nil
      entry.roadTaken, entry.roadDelivered, entry.sceneTaken, entry.sceneDelivered = nil, nil, nil, nil
      active.manifests[key .. ':road'] = road
      entry.used = touch()
      entry.triangles, entry.vertices = entrySize(entry)
      active.tiles[key] = entry
      st.ready[key], st.scenes[key], st.far[key] = true, nil, nil
      active.nearKnownAt = nil
      trimTiles()
    end
    early = true
    coroutine.yield(AHEAD)
  end
  local road, scene, far, nav = generator.build(cells, wanted.i, wanted.j,
    {tileSize = size, regionId = r.descriptor.id, center = center, pause = active.pause,
      materials = '/earthng/planet/materials.json', packs = '/e2r_stream/fast-art/v10/packs.json',
      far = wanted.far, horizon = wanted.horizon, vista = wanted.vista, farDecor = wanted.decor and true or false,
      -- a vista block's edge at 100 m (4x faster, its skirts hide the seam with the 25 m horizon)
      terrainStep = wanted.vista and 100 or nil,
      farStep = 100, horizonStep = wanted.step or 100,
      latitude = r.data.geo and r.data.geo[4], geo = r.data.geo, nature = r.data.nature,
      look = r.data.look, country = r.country and r.country.id,
      seaLevel = finite(r.data.seaLevel) and r.data.seaLevel or nil,
      maxTrees = tune.maxTrees, maxFarTrees = tune.maxFarTrees, maxGrass = tune.maxGrass,
      maxRocks = tune.maxRocks, forestSpacing = tune.forestSpacing, groundSpacing = tune.groundSpacing,
      groundTrees = tune.groundTrees, parkedCars = tune.parkedCars, propSpacing = tune.propSpacing,
      detail = tune.detail, roadReady = roadReady or nil})
  if type(road) ~= 'table' or type(road.items) ~= 'table' or type(road.mats) ~= 'table'
    or type(scene) ~= 'table' or type(scene.items) ~= 'table' then error('generator returned an invalid tile manifest') end
  if wanted.far and (type(far) ~= 'table' or type(far.items) ~= 'table') then error('generator returned an invalid far manifest') end
  if not early then stamp(road, nav) end
  scene.source, scene.materials = r.descriptor.id, '/earthng/planet/materials.json'
  if wanted.horizon then
    far.source, far.materials = r.descriptor.id, '/earthng/planet/materials.json'
    far.tileSize = size
    local entry = active.horizon[key] or {}
    entry.horizon, entry.decor = far, false
    entry.horizonTaken, entry.horizonDelivered = nil, nil
    entry.serial = (entry.serial or 0) + 1
    entry.used = touch()
    entry.triangles, entry.vertices = geometrySize(far)
    active.horizon[key] = entry
    active.manifests[key .. ':horizon'] = far
    st.horizon[key] = {serial = entry.serial, i = wanted.i, j = wanted.j, size = size,
      x = (wanted.i + 0.5) * size, y = (wanted.j + 0.5) * size}
    st.horizonBuilt = (st.horizonBuilt or 0) + 1
    local layerKey = key .. ':horizon'
    if active.everBuilt[layerKey] then st.horizonRebuilds = (st.horizonRebuilds or 0) + 1 end
    active.everBuilt[layerKey] = true
    trimHorizon()
    return
  end
  local entry = active.tiles[key] or {}
  if wanted.far then
    far.source, far.materials = r.descriptor.id, '/earthng/planet/materials.json'
    entry.far, entry.decor = far, wanted.decor and true or false
    entry.farTaken, entry.farDelivered = nil, nil
    entry.serial = (entry.serial or 0) + 1
    active.manifests[key .. ':far'] = far
    st.far[key] = entry.serial
  elseif early then
    -- the road went out already (roadReady): only the scene is new
    entry.scene, entry.sceneTaken, entry.sceneDelivered = scene, nil, nil
    active.manifests[key .. ':scene'] = scene
  else
    entry.road, entry.scene, entry.nav = road, scene, nav
    active.manifests[key .. ':road'], active.manifests[key .. ':scene'] = road, scene
    entry.roadTaken, entry.sceneTaken, entry.roadDelivered, entry.sceneDelivered = nil, nil, nil, nil
  end
  entry.used = touch()
  entry.triangles, entry.vertices = entrySize(entry)
  active.tiles[key] = entry
  st.ready[key], st.scenes[key] = entry.road and true or nil, entry.scene and true or nil
  if not wanted.far then st.far[key] = nil end
  st.built = st.built + 1
  local layerKey = key .. (wanted.far and ':far' or ':road')
  if active.everBuilt[layerKey] then st.rebuilds = st.rebuilds + 1 end
  active.everBuilt[layerKey] = true
  trimTiles()
end

-- After the landing, a frame with no near tile waiting builds the far ring and the horizon
-- on a smaller budget: they can wait, the frame cannot (central Kyiv spent 5.3 ms a frame
-- here while driving). A near tile coming due gets the whole budget back at once.
local FAR_BUDGET_MS = 2
-- pending: a near tile without its road, or one whose scene the car left before it was built
-- and is near again; urgent: such a road due within AHEAD.urgent s
local function nearPending(wanted)
  local pending, urgent = false, false
  for key, entry in pairs(wanted) do
    if not entry.far and not entry.horizon and not active.failed[key] then
      local cached = active.tiles[key]
      if not (cached and cached.road) then
        pending, urgent = true, urgent or entry.priority < AHEAD.urgent
      elseif cached.sceneLost then
        pending = true
      end
    end
  end
  return pending, urgent
end

-- A parked scene build given up (the car has left its tile, or a road ahead needs the room): the
-- road stays, and the tile is built again for its scene if it is wanted near once more.
local function loseScene(key)
  active.parked[key] = nil
  local entry = active.tiles[key]
  if entry and not entry.scene then entry.sceneLost = true end
end

local function update(dt, budgetMs, farBudgetMs)
  ensure()
  if not active then return end
  if live and active.region.country.id == 'live' and live.absorb(active.region) then
    active.prioritiesDirty = true
  end
  active.parked, active.parkedFar = active.parked or {}, active.parkedFar or {}
  -- neighbour cells left unlooked-at last frame (FOREIGN_NEW): the wanted set again
  active.foreignNew = 0
  if active.foreignShort then active.foreignShort, active.prioritiesDirty = false, true end
  local dirty = active.prioritiesDirty
  local wanted, best, bestKey, bestPriority = dirty and priorities() or active.desired, nil, nil, nil
  local timer = hptimer()
  -- farBudgetMs: the far ring's own budget instead of FAR_BUDGET_MS (showcase stills; the
  -- game passes none), and then the frame may take up to 50 ms
  budgetMs = finite(budgetMs) and math.max(0.1, math.min(farBudgetMs and 50 or 8, budgetMs)) or 2
  if dirty or active.nearKnownAt ~= state.stream.built then
    active.nearWaiting, active.nearUrgent = nearPending(wanted)
    active.nearKnownAt = state.stream.built
  end
  local nearWork = active.nearWaiting or next(active.parked) ~= nil
    or (active.work and not active.workFar and not active.workHorizon)
  if not active.startupPinned and not nearWork then budgetMs = math.min(budgetMs, farBudgetMs or FAR_BUDGET_MS) end
  -- the road the car reaches within seconds is missing: the frame pays for it rather than the car
  if not active.startupPinned and not farBudgetMs and active.nearUrgent then budgetMs = math.max(budgetMs, AHEAD.urgentMs) end
  state.stream.budgetMs = budgetMs
  active.timer, active.budget = timer, budgetMs
  local p = active.pose
  local speed = math.sqrt((p.vx or 0) ^ 2 + (p.vy or 0) ^ 2)
  local lag = AHEAD.lag + math.max(0, speed - AHEAD.slow) * AHEAD.lagPerMs
  local steps = 0
  repeat
    -- At the frame's first step a scene build (its road is out) goes back among the parked, and a
    -- far one too when a road is urgent: a road that came due since then goes first, and the
    -- build's own turn resumes it where it stopped.
    if active.work and steps == 0 and not active.startupPinned then
      if active.workScene then
        active.parked[active.workKey] = {co = active.work}
        active.work = nil
      elseif (active.workFar or active.workHorizon) and active.nearUrgent then
        active.parkedFar[active.workKey] = {co = active.work, far = active.workFar, horizon = active.workHorizon}
        active.work = nil
      end
    end
    if not active.work then
      best, bestKey, bestPriority = nil, nil, nil
      local queued = 0
      -- Far tiles wait while far geometry the renderer has not taken fills half the budget:
      -- a generator ahead of the renderer (a stills budget, a fast drive) built them only to
      -- evict them, and an evicted tile stays a hole until the next epoch. Near tiles and the
      -- startup set always build.
      -- Only tiles wanted as far now count: a far layer left behind by a camera jump, or one under
      -- a near tile, is never taken and would hold the ring still (eviction removes it later).
      local farTriangles, farVertices = 0, 0
      if not active.startupPinned then
        for key, e in pairs(active.tiles) do
          local want = wanted[key]
          if e.far and not e.farTaken and want and want.far and not want.horizon then
            farTriangles, farVertices = farTriangles + e.triangles, farVertices + e.vertices
          end
        end
      end
      local full = farTriangles > TRIANGLE_LIMIT * .5 or farVertices > VERTEX_LIMIT * .5
      for key, entry in pairs(wanted) do
        local cached = entry.horizon and active.horizon[key] or active.tiles[key]
        local ready, priority = nil, entry.priority
        if entry.horizon then ready = cached and cached.horizon
        elseif entry.far then ready = cached and cached.far and (not entry.decor or cached.decor)
        else
          ready = cached and cached.road and not cached.sceneLost
          -- a scene owed comes after the roads due before it, as a parked one does
          if cached and cached.road then priority = priority + lag end
        end
        local layerKey = key .. (entry.horizon and ':horizon' or (entry.far and ':far' or ':road'))
        if not ready and not active.failed[key] and active.evicted[layerKey] ~= active.epoch then
          queued = queued + 1
          -- one far build at a time: a parked one is finished before another starts
          local farWaits = (entry.far or entry.horizon) and next(active.parkedFar) ~= nil
          if not (full and entry.far) and not farWaits and (not best or priority < bestPriority or (priority == bestPriority and key < bestKey)) then
            best, bestKey, bestPriority = entry, key, priority
          end
        end
      end
      -- Parked scene builds (their roads are out): the nearest goes on when it is due before the
      -- best road; one the car has left is given up.
      local parkedKey, parkedPriority, worstKey, worstPriority, parkedCount = nil, nil, nil, nil, 0
      for key in pairs(active.parked) do
        local want = wanted[key]
        if not want or want.far or want.horizon then
          loseScene(key)
        else
          local priority = want.priority + lag
          parkedCount = parkedCount + 1
          if not parkedPriority or priority < parkedPriority then parkedKey, parkedPriority = key, priority end
          if not worstPriority or priority > worstPriority then worstKey, worstPriority = key, priority end
        end
      end
      local farKey, farPriority
      for key, slot in pairs(active.parkedFar) do
        local want = wanted[key]
        if not want or not want.far or (want.horizon and true or false) ~= slot.horizon then
          active.parkedFar[key] = nil
        elseif not farPriority or want.priority < farPriority then
          farKey, farPriority = key, want.priority
        end
      end
      state.stream.queued, state.stream.parked = queued, parkedCount
      if farKey and (not best or farPriority < bestPriority) and (not parkedKey or farPriority < parkedPriority) then
        local slot = active.parkedFar[farKey]
        active.parkedFar[farKey] = nil
        active.work, active.workKey, active.workScene = slot.co, farKey, false
        active.workFar, active.workHorizon = slot.far, slot.horizon
      elseif parkedKey and (not best or parkedPriority <= bestPriority) then
        active.work = active.parked[parkedKey].co
        active.parked[parkedKey] = nil
        active.workKey, active.workFar, active.workHorizon, active.workScene = parkedKey, false, false, true
      elseif best then
        -- a road due before every parked scene, and no room for one more: the latest scene goes
        if parkedCount >= AHEAD.parked and not best.far and not best.horizon then loseScene(worstKey) end
        local key, entry = bestKey, best
        active.workKey = key
        active.workFar = entry.far and not entry.horizon or false
        active.workHorizon = entry.horizon and true or false
        active.workScene = false
        active.work = coroutine.create(function() buildTile(key, entry) end)
      else
        break
      end
      state.stream.building = 1
      if state.job and state.job.state == 'working' then state.job.stage = 'Generating roads and scenery in Lua' end
    end
    local resumeTimer = hptimer()
    local ok, message = coroutine.resume(active.work)
    local resumeMs = resumeTimer:stop()
    -- a resume far over the budget (a block read, a big sort) for the automation report
    if resumeMs > 30 then
      local slow = state.stream.slowResumes or {}
      state.stream.slowResumes = slow
      if #slow < 40 then slow[#slow + 1] = {active.workKey, active.workHorizon and 'horizon' or (active.workFar and 'far' or 'near'), math.floor(resumeMs)} end
    end
    steps = steps + 1
    if not ok then
      active.failed[active.workKey] = tostring(message)
      if active.landing and active.landing.required[active.workKey] and state.job.state == 'working' then fail(message) end
      active.work = nil
    elseif message == AHEAD and coroutine.status(active.work) == 'suspended' then
      -- the road is out (buildTile's roadReady): the scene waits for its turn
      active.parked[active.workKey] = {co = active.work}
      active.work = nil
    elseif coroutine.status(active.work) == 'dead' then
      active.work = nil
      completeLanding()
      trimTiles()
    end
    state.stream.building = active.work and 1 or 0
  until steps >= 10000 or timer:stop() >= budgetMs
end

local function pose(p)
  if not active or type(p) ~= 'table' or not finite(p.x) or not finite(p.y) then return end
  if math.abs(p.x) > 1e12 or math.abs(p.y) > 1e12 then return end
  if p.region and p.region ~= active.region.descriptor.id then return end
  if p.country and p.country ~= active.region.country.id then return end
  local old = active.pose
  active.pose = {x = p.x, y = p.y, z = finite(p.z) and p.z or nil,
    vx = finite(p.vx) and math.max(-10000, math.min(10000, p.vx)) or 0,
    vy = finite(p.vy) and math.max(-10000, math.min(10000, p.vy)) or 0}
  -- The wanted set depends on the car's tile, the look-ahead point's tile and the far switch;
  -- recomputing it (~170 tiles) for every pose made garbage in every frame.
  local t = active.region.data.tileSize
  local speed = math.sqrt(active.pose.vx ^ 2 + active.pose.vy ^ 2)
  local ahead = math.min(speed * 3, 2000)
  local ax = speed > 0 and p.x + active.pose.vx / speed * ahead or p.x
  local ay = speed > 0 and p.y + active.pose.vy / speed * ahead or p.y
  -- and the corridor's end and the speed in 10 m/s steps: a near tile's priority is a time
  local reach = speed >= 15 and math.min(speed * AHEAD.corridor, AHEAD.reach) or 0
  local ex = speed > 0 and p.x + active.pose.vx / speed * reach or p.x
  local ey = speed > 0 and p.y + active.pose.vy / speed * reach or p.y
  local signature = string.format('%d_%d_%d_%d_%d_%d_%d_%s_%s_%d', math.floor(p.x / t), math.floor(p.y / t),
    math.floor(ax / t), math.floor(ay / t), math.floor(ex / t), math.floor(ey / t), math.floor(speed / 10),
    tostring(speed <= state.stream.farFast), tostring(speed < VISTA_SPEED),
    finite(p.z) and math.floor(p.z / 100) or 0)
  if signature ~= active.poseSignature then active.poseSignature, active.prioritiesDirty = signature, true end
  local ep = active.epochPoint
  if (p.x - ep[1]) ^ 2 + (p.y - ep[2]) ^ 2 >= 250 * 250 then
    active.epoch, active.epochPoint = active.epoch + 1, {p.x, p.y}
  end
  -- A ready job starts the renderer's warm-up and descent. Keep every startup
  -- road/scene until the renderer confirms that the car has reached the ground.
  if p.state == 'driving' and active.startupPinned then
    active.startupPinned, active.prioritiesDirty = false, true
    active.epoch = active.epoch + 1
    trimTiles()
  end
  local lon, lat = geographic(active.region, p.x, p.y)
  if live and active.region.country.id == 'live' then live.note(lat, lon) end
  state.stream.car = {lon, lat}
  state.stream.geo = affineAt(active.region, p.x, p.y)
  -- the edge of the land the packs have, the neighbours' too: the first point within 3 km in one
  -- of eight directions that no region of a mounted pack covers
  local function covers(plon, plat)
    if inside(active.region.data.bounds, plon, plat) then return true end
    for _, r in ipairs(regions) do
      if r.data.schemaVersion == 2 and inside(r.data.bounds, plon, plat) then return true end
    end
    return false
  end
  local edge, k = 99, math.cos(math.rad(lat)) * 111.2
  for _, km in ipairs({.5, 1, 2, 3}) do
    for d = 0, 7 do
      local angle = d * math.pi / 4
      if km < edge and not covers(lon + km * math.cos(angle) / k, lat + km * math.sin(angle) / 111.2) then edge = km end
    end
  end
  state.stream.edgeKm = covers(lon, lat) and edge or 0
end

local function recount(entry)
  entry.triangles, entry.vertices = entrySize(entry)
end

local function layerEntry(key)
  if not active then return nil end
  return active.tiles[key] or active.horizon[key]
end

local function manifest(key, layer)
  local entry = layerEntry(key)
  if entry then
    layer = layer or 'road'
    entry.used = touch()
    if entry[layer] then entry[layer .. 'Taken'] = true; recount(entry) end
    return entry[layer]
  end
end


-- createMesh has copied these arrays to the engine. The renderer calls this only
-- after the entire layer has spawned, so its queue can no longer need the tables.
local function release(key, layer)
  layer = layer or 'road'
  if layer ~= 'road' and layer ~= 'scene' and layer ~= 'far' and layer ~= 'horizon' then return false end
  local entry = layerEntry(key)
  local data = entry and entry[layer] or active and active.manifests[key .. ':' .. layer]
  if not data then return false end
  -- Delivered: the engine holds the meshes, the Forest commit and the grass cells keep
  -- what they still need. These item tables were most of the Lua heap that the game's
  -- collector walks (the far ring's crowns alone were ~78k tables), so only the count stays.
  data.itemCount = #(data.items or {})
  data.items = {}
  if entry then
    entry[layer .. 'Delivered'] = true
    entry.used = touch()
    if layer == 'horizon' then entry.triangles, entry.vertices = 0, 0 else recount(entry) end
  end
  if layer == 'horizon' then trimHorizon() else trimTiles() end
  return true
end

-- Resident GPU meshes have gone. Removing the corresponding ready bit makes the
-- next visit rebuild from the compact source cells instead of reusing empty data.
local function unload(key, layer)
  if not active or (layer ~= nil and layer ~= 'road' and layer ~= 'scene' and layer ~= 'far' and layer ~= 'horizon') then return false end
  local entry, st = layerEntry(key), state.stream
  local farOnly = layer == 'far'
  local horizonOnly = layer == 'horizon'
  if active.workKey == key and ((horizonOnly and active.workHorizon) or (farOnly and active.workFar) or (not farOnly and not horizonOnly and not active.workFar and not active.workHorizon)) then
    active.work, active.workKey, st.building = nil, nil, 0
  end
  if (farOnly or horizonOnly) and active.parkedFar then active.parkedFar[key] = nil end
  if horizonOnly then
    if entry then entry.horizon, entry.horizonDelivered, entry.horizonTaken = nil, nil, nil end
    st.horizon[key], active.evicted[key .. ':horizon'] = nil, nil
    active.manifests[key .. ':horizon'] = nil
    active.horizon[key] = nil
    active.failed[key] = nil
    active.prioritiesDirty = true
    trimHorizon()
    return entry ~= nil
  elseif farOnly then
    if entry then entry.far, entry.farDelivered, entry.farTaken = nil, nil, nil end
    st.far[key], active.evicted[key .. ':far'] = nil, nil
    active.manifests[key .. ':far'] = nil
  else
    if active.parked then active.parked[key] = nil end
    if entry then
      entry.road, entry.scene, entry.nav, entry.sceneLost = nil, nil, nil, nil
      entry.roadDelivered, entry.sceneDelivered, entry.roadTaken, entry.sceneTaken = nil, nil, nil, nil
    end
    st.ready[key], st.scenes[key], active.evicted[key .. ':road'] = nil, nil, nil
    active.manifests[key .. ':road'], active.manifests[key .. ':scene'] = nil, nil
  end
  active.failed[key] = nil
  if entry then
    if not entry.road and not entry.scene and not entry.far then active.tiles[key] = nil else recount(entry) end
  end
  active.prioritiesDirty = true
  trimTiles()
  return entry ~= nil
end

-- Streets on the picker map before any landing: road centre lines straight from the
-- mounted v2 blocks under the view, decoded a little per frame and cached per block.
-- Rank 1: motorway..secondary, 2: tertiary/residential/unclassified, 3: the rest.
local MAP_BLOCKS, MAP_CACHE = 48, 96
local RANK = {motorway = 1, trunk = 1, primary = 1, secondary = 1, tertiary = 2, residential = 2,
  unclassified = 2, living_street = 2}
local mapCache, mapClock, mapWork = {}, 0, nil

local function mapBlock(r, key, block)
  if block and block.memory then
    if coroutine.running() then coroutine.yield() end
    local lines = {}
    if not (live and type(live.cell) == 'function') then return lines end
    local i, j = key:match('^(-?%d+)_(-?%d+)$')
    i, j = tonumber(i), tonumber(j)
    if not i or not j then return lines end
    local cell = live.cell(i, j)
    if type(cell) ~= 'table' then return lines end
    local s = r.data.cellSize
    local g = affineAt(r, (i + .5) * s, (j + .5) * s)
    local seen = {}
    for _, road in ipairs(cell.roads or {}) do
      if road.id and not seen[road.id] then
        seen[road.id] = true
        local highway = tostring((road.tags and road.tags.highway) or ''):gsub('_link$', '')
        local geo, lastX, lastY = {}, nil, nil
        local box = {math.huge, math.huge, -math.huge, -math.huge}
        local pts = road.points or {}
        for n, p in ipairs(pts) do
          local x, y = p[1], p[2]
          if n == 1 or n == #pts or (lastX and (x - lastX) ^ 2 + (y - lastY) ^ 2 >= 225) then
            local dx, dy = x - g[1], y - g[2]
            local lat = g[4] + g[7] * dx + g[8] * dy
            local lon = g[3] + g[5] * dx + g[6] * dy
            geo[#geo + 1], geo[#geo + 2] = lat, lon
            box[1], box[2] = math.min(box[1], lat), math.min(box[2], lon)
            box[3], box[4] = math.max(box[3], lat), math.max(box[4], lon)
            lastX, lastY = x, y
          end
        end
        if #geo >= 4 then lines[#lines + 1] = {rank = RANK[highway] or 3, geo = geo, box = box} end
      end
    end
    return lines
  end
  local data = readBytes(block.path)
  coroutine.yield()
  local b, s = blocksOf(r.data), r.data.cellSize
  local bi, bj = key:match('^(-?%d+)_(-?%d+)$')
  bi, bj = tonumber(bi), tonumber(bj)
  local cx, cy = (bi + .5) * b * s, (bj + .5) * b * s
  local g = affineAt(r, cx, cy)
  local lines, seen = {}, {}
  for slot, range in pairs(cellformat.block(data)) do
    local i, j = bi * b + slot % b, bj * b + math.floor(slot / b)
    for _, road in ipairs(cellformat.roads(data, range[1], range[2], i * s, j * s)) do
      if not seen[road.id] then
        seen[road.id] = true
        local highway = (road.highway or ''):gsub('_link$', '')
        local geo, xy, lastX, lastY = {}, road.xy, nil, nil
        local box = {math.huge, math.huge, -math.huge, -math.huge}  -- lat/lon: south, west, north, east
        for n = 1, #xy, 2 do
          local x, y = xy[n], xy[n + 1]
          -- every bend of 15 m or more; the map never needs the 20 m profile knots
          if n == 1 or n == #xy - 1 or (x - lastX) ^ 2 + (y - lastY) ^ 2 >= 225 then
            local dx, dy = x - g[1], y - g[2]
            local lat, lon = g[4] + g[7] * dx + g[8] * dy, g[3] + g[5] * dx + g[6] * dy
            geo[#geo + 1], geo[#geo + 2] = lat, lon
            box[1], box[2] = math.min(box[1], lat), math.min(box[2], lon)
            box[3], box[4] = math.max(box[3], lat), math.max(box[4], lon)
            lastX, lastY = x, y
          end
        end
        lines[#lines + 1] = {rank = RANK[highway] or 3, geo = geo, box = box}
      end
    end
    coroutine.yield()
  end
  return lines
end

local function mapRoads(view, budgetMs)
  ensure()
  if type(view) ~= 'table' or not finite(view.w) or not finite(view.s) or not finite(view.e) or not finite(view.n) then return {} end
  local wanted, out, listed = {}, {}, regions
  if live then
    local extra = live.sync()
    if extra then
      listed = {extra}
      for i = 1, #regions do listed[#listed + 1] = regions[i] end
    end
  end
  for _, r in ipairs(listed) do
    local b = r.data.bounds
    if r.data.schemaVersion == 2 and b[1] <= view.e and b[3] >= view.w and b[2] <= view.n and b[4] >= view.s then
      local x0, y0, x1, y1 = math.huge, math.huge, -math.huge, -math.huge
      for _, p in ipairs({{view.s, view.w}, {view.s, view.e}, {view.n, view.w}, {view.n, view.e}}) do
        local x, y = localPoint(r, p[1], p[2])
        x0, y0, x1, y1 = math.min(x0, x), math.min(y0, y), math.max(x1, x), math.max(y1, y)
      end
      local size = blocksOf(r.data) * r.data.cellSize
      local bi0, bj0, bi1, bj1 = math.floor(x0 / size), math.floor(y0 / size), math.floor(x1 / size), math.floor(y1 / size)
      if (bi1 - bi0 + 1) * (bj1 - bj0 + 1) <= MAP_BLOCKS * 4 then
        for bj = bj0, bj1 do
          for bi = bi0, bi1 do
            local key = keyOf(bi, bj)
            if r.data.blocks[key] then wanted[#wanted + 1] = {r = r, key = key, id = r.descriptor.id .. ':' .. key} end
          end
        end
      end
    end
  end
  if #wanted > MAP_BLOCKS then return out end -- zoomed too far out for streets
  mapClock = mapClock + 1
  local missing
  for _, w in ipairs(wanted) do
    local hit = mapCache[w.id]
    if hit then hit.used = mapClock; out[#out + 1] = hit.lines elseif not missing then missing = w end
  end
  if mapWork and mapWork.id ~= (missing and missing.id) and mapCache[mapWork.id] == nil then
    -- keep finishing a block still in view; drop one the player panned away from
    local still = false
    for _, w in ipairs(wanted) do if w.id == mapWork.id then still = true end end
    if not still then mapWork = nil end
  end
  if not mapWork and missing then
    local w = missing
    mapWork = {id = w.id, co = coroutine.create(function() return mapBlock(w.r, w.key, w.r.data.blocks[w.key]) end)}
  end
  local timer = hptimer()
  budgetMs = finite(budgetMs) and budgetMs or 3
  while mapWork and timer:stop() < budgetMs do
    local ok, lines = coroutine.resume(mapWork.co)
    if not ok then
      mapCache[mapWork.id], mapWork = {lines = {}, used = mapClock, error = tostring(lines)}, nil
    elseif coroutine.status(mapWork.co) == 'dead' then
      mapCache[mapWork.id] = {lines = lines, used = mapClock}
      out[#out + 1] = lines
      mapWork = nil
      local count, oldest, oldestAt = 0, nil, nil
      for id, entry in pairs(mapCache) do
        count = count + 1
        if not oldestAt or entry.used < oldestAt then oldest, oldestAt = id, entry.used end
      end
      if count > MAP_CACHE then mapCache[oldest] = nil end
    end
  end
  return out
end

-- Which horizon meshes to show. A coarser tile stays until every finer tile that overlaps
-- it is ready, then the swap is the whole set: no hole and no second surface on the same
-- ground. rank 0 is the finest. Aligned rings give each fine tile one parent.
function M.horizonShow(candidates, ready)
  candidates, ready = candidates or {}, ready or {}
  local hidden = {}
  local function overlaps(a, b)
    return a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]
  end
  for _, coarse in ipairs(candidates) do
    local children = {}
    for _, fine in ipairs(candidates) do
      if fine.rank < coarse.rank and fine.rect and coarse.rect and overlaps(fine.rect, coarse.rect) then
        children[#children + 1] = fine
      end
    end
    if #children > 0 then
      local allReady = true
      for _, fine in ipairs(children) do
        if not ready[fine.key] then allReady = false; break end
      end
      if allReady then hidden[coarse.key] = true
      else for _, fine in ipairs(children) do hidden[fine.key] = true end end
    end
  end
  local show = {}
  for _, candidate in ipairs(candidates) do
    if ready[candidate.key] and not hidden[candidate.key] then show[#show + 1] = candidate.key end
  end
  return show
end

-- Jump buttons for a country: county zips only. Grid regions stay in the catalog (coverage,
-- landing) and are not places. A section with no landing is skipped; one with no title uses its id.
function M.sectionPlaces(regions)
  local places = {}
  if type(regions) ~= 'table' then return places end
  for _, region in ipairs(regions) do
    local at = type(region) == 'table' and region.section == true and region.landing
    if type(at) == 'table' and type(at.lat) == 'number' and type(at.lon) == 'number' then
      local title = region.title or region.id
      places[#places + 1] = {title, at.lat, at.lon, region.country, title}
    end
  end
  return places
end

M.refresh = refresh
M.mapRoads = mapRoads
M.at = at
M.land = land
M.update = update
M.pose = pose
M.manifest = manifest
M.release = release
local function setTune(tune)
  ensure()
  local out = clampTune(tune)
  local changed = false
  for _, key in ipairs({'maxTrees','maxFarTrees','maxGrass','maxRocks','forestSpacing','groundSpacing','groundTrees','propSpacing'}) do
    if out[key] ~= pendingTune[key] then changed = true end
  end
  -- the game's parked cars on or off: box cars come or go
  if (out.parkedCars > 0) ~= ((pendingTune.parkedCars or 0) > 0) then changed = true end
  pendingTune = out
  if active then
    active.tune = out
    active.prioritiesDirty = true
    if changed then
      -- Also invalidate prepared tiles which have not reached the renderer yet.
      -- Otherwise a preset change leaves a ring built with the previous density.
      if active.work and not active.workHorizon then active.work, active.workKey, state.stream.building = nil, nil, 0 end
      local keys = {}
      for key in pairs(active.tiles) do keys[#keys+1] = key end
      for _, key in ipairs(keys) do unload(key); unload(key, 'far') end
    end
  end
  if state.stream then
    state.stream.loadRadius = out.nearM
    state.stream.farRadius = out.farM
    state.stream.tune = out
  end
  return out
end

M.unload = unload
M.setTune = setTune
M.localPoint = function(lat, lon) if active then return localPoint(active.region, lat, lon) end end
M.nav = function(key) local entry = active and active.tiles[key]; return entry and entry.nav end
-- The routing graph of the region driven now (routing/<region>.bin beside regions/, from
-- earthng/build_routing.py; a companion zip may bring it): path, a key that changes with the region.
-- The world frame is that region's own, so its graph needs no transform.
M.routing = function()
  if not active then return nil end
  local d = active.region.descriptor
  local root = type(d.manifest) == 'string' and d.manifest:match('^(.*)/regions/')
  local path = root and (root .. '/routing/' .. tostring(d.id) .. '.bin')
  if path and exists(path) then return path, active.region.country.id .. '/' .. tostring(d.id) end
end
M.readBytes = readBytes
-- The routing graphs of the pack regions round a box (lat/lon), each with the move into the
-- driven region's frame (nil for that region itself): the route goes as far as the land that
-- foreignOf streams in.
M.routingRegions = function(south, west, north, east)
  if not active then return {} end
  local out, r0 = {}, active.region
  for _, r in ipairs(regions) do
    local b, d = r.data.bounds, r.descriptor
    if r.data.schemaVersion == 2 and b[1] <= east and b[3] >= west and b[2] <= north and b[4] >= south then
      local root = type(d.manifest) == 'string' and d.manifest:match('^(.*)/regions/')
      local path = root and (root .. '/routing/' .. tostring(d.id) .. '.bin')
      if path and exists(path) then
        local toWorld
        local f, f0 = r.data.frame, r0.data.frame
        if r == r0 then
          toWorld = nil
        elseif type(f) == 'table' and type(f0) == 'table' and f.crs == f0.crs and vector(f.origin, 2) and vector(f0.origin, 2) then
          -- one UTM zone: the frames differ by their origins alone
          local dx, dy = f.origin[1] - f0.origin[1], f.origin[2] - f0.origin[2]
          toWorld = function(x, y) return x + dx, y + dy end
        else
          toWorld = function(x, y)
            local lon, lat = geographic(r, x, y)
            return localPoint(r0, lat, lon)
          end
        end
        out[#out + 1] = {path = path, key = r.country.id .. '/' .. tostring(d.id), toWorld = toWorld}
      end
    end
  end
  table.sort(out, function(p, q) return p.key < q.key end)
  return out
end
-- world x, y -> lat, lon by the region's own projection (the stream's geo is an affine at the car)
M.toGeo = function(x, y)
  if not active then return nil end
  local lon, lat = geographic(active.region, x, y)
  return lat, lon
end
M.status = function() ensure(); state.heartbeat = os.time(); return state end
return M
