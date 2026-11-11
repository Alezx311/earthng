-- Binary source cells of native country packages (earthng-features-v2). The format and its
-- reference encoder live in earthng/country_format.py: LEB128 varints, zigzag for signed
-- values, centimetre coordinates as deltas from the cell origin, decimetre terrain heights.
-- The decoder builds exactly the tables the v1 JSON cells held, so the generator is shared.
--
-- Blocks with magic 'EGB3' (country_format.transcode_cell) keep each cell's string table and hold
-- every later number as u16 words (0xffff, low, high for a larger value), with the elevation grid
-- after them as u16 decimetres above the cell's lowest point. Each part is copied into an FFI array
-- with one ffi.copy, so the walk below reads array elements instead of decoding varints byte by
-- byte: the same tables, 2-2.7 times faster (docs/RUST_IN_MOD.md). The game's sandbox allows
-- ffi.new arrays and ffi.copy from a string; without FFI (another Lua) the words are read by hand.
local M = {}
local byte, sub, floor = string.byte, string.sub, math.floor
local KINDS = {'roads', 'junctions', 'buildings', 'areas', 'lines', 'points'}
M.BLOCK = 8
M.KINDS = KINDS
local ffi
do
  local ok, lib = pcall(require, 'ffi')
  if ok and type(lib) == 'table' and type(lib.new) == 'function' and type(lib.copy) == 'function' then ffi = lib end
end
M.ffi = ffi ~= nil
local ESCAPE = 65535

-- Is this block file EGB3 (fixed-width cells)? M.block has checked the magic.
local function fixed(data)
  local a, b, c, d = byte(data, 1, 4)
  return d == 51 and c == 66 and b == 71 and a == 69
end
M.fixed = fixed

-- The n u16 little-endian words at data[pos..], as a 0-based array (FFI) or table.
local function words(data, pos, n)
  if ffi then
    local w = ffi.new('uint16_t[?]', n + 1)
    if n > 0 then ffi.copy(w, sub(data, pos, pos + 2 * n - 1), 2 * n) end
    return w
  end
  local w = {}
  for k = 0, n - 1 do
    local lo, hi = byte(data, pos + 2 * k, pos + 2 * k + 1)
    w[k] = lo + hi * 256
  end
  return w
end

-- The word part of an EGB3 cell whose string table ends before pos: words, their count and
-- where the elevation grid starts.
local function wordPart(data, pos, last)
  if pos + 3 > last then error('truncated source cell') end
  local a, b, c, d = byte(data, pos, pos + 3)
  local n = a + b * 256 + c * 65536 + d * 16777216
  pos = pos + 4
  if pos + 2 * n - 1 > last then error('truncated source cell') end
  return words(data, pos, n), n, pos + 2 * n
end

-- The elevation grid of an EGB3 cell: count decimetre offsets above base at data[at..last].
local function fixedHeights(data, at, last, count, base, pause)
  if at + 2 * count - 1 ~= last then error('source cell size mismatch') end
  local w, heights, low = words(data, at, count), {}, math.huge
  for k = 1, count do
    local h = (base + w[k - 1]) / 10
    heights[k] = h
    if h < low then low = h end
    if pause and k % 8192 == 0 then pause() end
  end
  return heights, low
end

-- Byte ranges {slot = {first, last}} of the cells in a block file (1-based, inclusive).
function M.block(data)
  local magic = type(data) == 'string' and sub(data, 1, 4)
  if magic ~= 'EGB2' and magic ~= 'EGB3' then error('not an EarthNG source block') end
  local pos, size = 5, #data
  local function u()
    local value, mul = 0, 1
    while true do
      if pos > size or mul > 2 ^ 49 then error('truncated source block') end
      local b = byte(data, pos)
      pos = pos + 1
      if b < 128 then return value + b * mul end
      value, mul = value + (b - 128) * mul, mul * 128
    end
  end
  local count, entries = u(), {}
  if count > M.BLOCK * M.BLOCK then error('too many cells in a source block') end
  for k = 1, count do entries[k] = {u(), u()} end
  local out, at = {}, pos
  for _, e in ipairs(entries) do
    if e[1] >= M.BLOCK * M.BLOCK or out[e[1]] then error('invalid source block slot') end
    out[e[1]] = {at, at + e[2] - 1}
    at = at + e[2]
  end
  if at ~= size + 1 then error('source block size mismatch') end
  return out
end

-- Margins round a tile for M.cell's keep filter: a road shapes the ground up to 70 m from its
-- edge (generator PULL), so roads are kept 120 m out (half of an 80 m road + 70 m + slack);
-- everything else only matters inside the tile (parked cars reach 3 m past it).
M.ROAD_MARGIN, M.MARGIN = 120, 5
-- road details at a way node (fast_style.ROAD_DETAILS): a zebra or a turning circle reaches
-- into the tile from up to this far outside it
M.DETAIL_MARGIN = 30
M.DETAILS = {crossing = true, give_way = true, stop_sign = true, mini_roundabout = true, turning_circle = true,
  signal = true, traffic_sign = true}

-- The features of a cell after its grid, into cell[kind]: u reads the next unsigned number, s the
-- next signed one; ocx, ocy: the cell's corner in centimetres. Each format has its own u and its
-- own copy of this function (below): an upvalue that switched from the varint reader to the word
-- reader mid-cell, or one function fed both readers, kept LuaJIT's traces of these loops on the
-- first reader, and EGB3 decoded 7 % faster instead of 4.3 times (four central Kyiv blocks under
-- lupa, 2145 -> 500 ms). It has no upvalues, so string.dump can copy it.
local function features(M, cell, u, s, strings, ocx, ocy, pause, keep)
  local KINDS = M.KINDS
  local function ref()
    local v = strings[u() + 1]
    if v == nil then error('invalid source string reference') end
    return v
  end
  -- tags and node ids are read into scratch, and become tables only for a kept feature
  local tagBuf, nodeBuf = {}, {}
  local function readTags()
    local n = u()
    for k = 1, 2 * n do tagBuf[k] = ref() end
    return n
  end
  local function tags(n)
    local out = {}
    for k = 1, n do out[tagBuf[2 * k - 1]] = tagBuf[2 * k] end
    return out
  end
  -- Coordinates go to a scratch buffer first (bounds while reading); tables only when kept.
  local buf, nbuf, bx0, by0, bx1, by1, work = {}, 0, 0, 0, 0, 0, 0
  local function read(minimum)
    local n = u()
    if n < minimum then error('too few source coordinates') end
    local px, py, pz = ocx, ocy, 0
    for _ = 1, n do
      px, py, pz = px + s(), py + s(), pz + s()
      local x, y = px / 100, py / 100
      buf[nbuf + 1], buf[nbuf + 2], buf[nbuf + 3] = x, y, pz / 100
      nbuf = nbuf + 3
      work = work + 1
      if work >= 1024 then work = 0; pause() end
      if x < bx0 then bx0 = x end
      if x > bx1 then bx1 = x end
      if y < by0 then by0 = y end
      if y > by1 then by1 = y end
    end
    return n
  end
  local function start() nbuf, bx0, by0, bx1, by1 = 0, math.huge, math.huge, -math.huge, -math.huge end
  local function wanted(margin)
    return not keep or (bx0 <= keep[3] + margin and bx1 >= keep[1] - margin and by0 <= keep[4] + margin and by1 >= keep[2] - margin)
  end
  local function points(from, n)
    local out = {}
    for k = 1, n do
      local at = from + 3 * (k - 1)
      out[k] = {buf[at + 1], buf[at + 2], buf[at + 3]}
    end
    return out
  end
  local function rings()
    local n = u()
    if n < 1 then error('source polygon without rings') end
    local counts = {}
    for k = 1, n do counts[k] = read(3) end
    return counts
  end
  local function ringTables(counts)
    local out, at = {}, 0
    for k = 1, #counts do out[k] = points(at, counts[k]); at = at + 3 * counts[k] end
    return out
  end
  local done = 0
  -- a feature's fields are set in the order the tables always had (pairs() order is unchanged)
  for _, kind in ipairs(KINDS) do
    local list = {}
    for _ = 1, u() do
      local id = ref()
      start()
      local f
      if kind == 'roads' then
        local width = u() / 100
        local nt = readTags()
        local nn = u()
        for n = 1, nn do nodeBuf[n] = ref() end
        local n = read(2)
        if wanted(M.ROAD_MARGIN) then
          f = {id = id}
          f.width = width; f.tags = tags(nt)
          local nodes = {}
          for k = 1, nn do nodes[k] = nodeBuf[k] end
          f.nodes = nodes
          f.points = points(0, n)
        end
      elseif kind == 'junctions' then
        local height = s() / 100
        local counts = rings()
        if wanted(M.MARGIN) then
          f = {id = id}
          f.height = height
          f.rings = ringTables(counts)
        end
      elseif kind == 'buildings' then
        local bkind, height, minHeight = ref(), u() / 100, u() / 100
        local nt = readTags()
        local counts = rings()
        if wanted(M.MARGIN) then
          f = {id = id}
          f.kind = bkind; f.height = height; f.minHeight = minHeight
          f.tags = tags(nt)
          f.rings = ringTables(counts)
        end
      elseif kind == 'areas' then
        local akind = ref()
        local nt = readTags()
        local counts = rings()
        if wanted(M.MARGIN) then
          f = {id = id}
          f.kind = akind; f.tags = tags(nt)
          f.rings = ringTables(counts)
        end
      elseif kind == 'lines' then
        local lkind = ref()
        local nt = readTags()
        local n = read(2)
        if wanted(M.MARGIN) then
          f = {id = id}
          f.kind = lkind; f.tags = tags(nt)
          f.points = points(0, n)
        end
      else
        local pkind = ref()
        local nt = readTags()
        read(1)
        if wanted(M.DETAILS[pkind] and M.DETAIL_MARGIN or M.MARGIN) then
          f = {id = id}
          f.kind = pkind; f.tags = tags(nt)
          f.pos = points(0, 1)[1]
        end
      end
      if f then list[#list + 1] = f end
      done = done + 1
      if done % 128 == 0 then pause() end
    end
    cell[kind] = list
  end
  return cell
end

-- The EGB3 copy of features: the same bytecode as its own prototype, so its traces are its own.
-- Without string.dump or binary load (another sandbox) both formats share the one function.
local fixedFeatures = features
do
  local ok, copy = pcall(function() return load(string.dump(features), '=cellformat.features3', 'b') end)
  if ok and type(copy) == 'function' then fixedFeatures = copy end
end
M.ownFixedFeatures = fixedFeatures ~= features

-- The string table of the cell at data[pos..last]: the strings and where the numbers start.
local function stringTable(data, pos, last)
  local function u()
    local value, mul = 0, 1
    while true do
      if pos > last or mul > 2 ^ 49 then error('truncated source cell') end
      local b = byte(data, pos)
      pos = pos + 1
      if b < 128 then return value + b * mul end
      value, mul = value + (b - 128) * mul, mul * 128
    end
  end
  local strings = {}
  for k = 1, u() do
    local n = u()
    if pos + n - 1 > last then error('truncated source string') end
    strings[k] = sub(data, pos, pos + n - 1)
    pos = pos + n
  end
  return strings, pos
end

-- M.cell of an EGB3 block: the numbers come from the word array.
local function fixedCell(data, first, last, ox, oy, rect, pause, keep, grid)
  local strings, pos = stringTable(data, first, last)
  -- the word array goes into the shared grid too: four tiles read a cell, and each copy is
  -- garbage the size of the cell that the engine's collector pays for
  local w, wn, gridAt
  if grid and grid.words then
    w, wn, gridAt = grid.words, grid.wordCount, grid.gridAt
  else
    w, wn, gridAt = wordPart(data, pos, last)
    if grid then grid.words, grid.wordCount, grid.gridAt = w, wn, gridAt end
  end
  local wi = 0
  local function u()
    if wi >= wn then error('truncated source cell') end
    local v = w[wi]
    if v == ESCAPE then
      if wi + 2 >= wn then error('truncated source cell') end
      v = w[wi + 1] + w[wi + 2] * 65536
      wi = wi + 3
      return v
    end
    wi = wi + 1
    return v
  end
  local function s()
    local v = u()
    if v % 2 == 0 then return v / 2 end
    return -(v + 1) / 2
  end
  local nx, ny, heights
  if grid and grid.heights then
    nx, ny, heights, wi = grid.nx, grid.ny, grid.heights, grid.after
  else
    nx, ny = u(), u()
    if nx < 2 or ny < 2 or nx > 257 or ny > 257 then error('invalid source elevation grid') end
    heights = fixedHeights(data, gridAt, last, nx * ny, s(), pause)
    if grid then grid.nx, grid.ny, grid.heights, grid.after = nx, ny, heights, wi end
  end
  local cell = fixedFeatures(M, {terrain = {rect = rect, nx = nx, ny = ny, heights = heights}}, u, s, strings,
    floor(ox * 100 + .5), floor(oy * 100 + .5), pause, keep)
  if wi ~= wn then error('trailing values after source cell') end
  return cell
end

-- One cell from data[first..last]; ox, oy: its south-west corner in region metres.
-- keep (optional {x0, y0, x1, y1}): only features whose bounds reach it (with the margins above)
-- become tables; the rest are read past. A tile needs a quarter of a 1 km cell, and decoded
-- points are what the game's collector walks, so a tile's cell is not decoded whole.
-- grid (optional table): empty, it is filled with the cell's elevation grid; filled by an earlier
-- call for the same cell, that grid is shared instead of decoded again (up to 66k numbers, read by
-- four tiles and their edges). The generator only reads the grid.
function M.cell(data, first, last, ox, oy, rect, pause, keep, grid)
  pause = pause or function() end
  if fixed(data) then return fixedCell(data, first, last, ox, oy, rect, pause, keep, grid) end
  local strings, pos = stringTable(data, first, last)
  local function u()
    local value, mul = 0, 1
    while true do
      if pos > last or mul > 2 ^ 49 then error('truncated source cell') end
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
  local nx, ny, heights
  if grid and grid.heights then
    nx, ny, heights, pos = grid.nx, grid.ny, grid.heights, grid.after
  else
    nx, ny = u(), u()
    if nx < 2 or ny < 2 or nx > 257 or ny > 257 then error('invalid source elevation grid') end
    local h = 0
    heights = {}
    for k = 1, nx * ny do
      h = h + s(); heights[k] = h / 10
      if k % 8192 == 0 then pause() end
    end
    if grid then grid.nx, grid.ny, grid.heights, grid.after = nx, ny, heights, pos end
  end
  local cell = features(M, {terrain = {rect = rect, nx = nx, ny = ny, heights = heights}}, u, s, strings,
    floor(ox * 100 + .5), floor(oy * 100 + .5), pause, keep)
  if pos ~= last + 1 then error('trailing bytes after source cell') end
  return cell
end

-- Only the elevation grid of a cell, for the distant vista ring: {terrain = .., roads = {}, ...}.
-- The strings are skipped by length and nothing after the grid is read.
function M.terrain(data, first, last, rect, pause)
  local pos = first
  local function u()
    local value, mul = 0, 1
    while true do
      if pos > last or mul > 2 ^ 49 then error('truncated source cell') end
      local b = byte(data, pos)
      pos = pos + 1
      if b < 128 then return value + b * mul end
      value, mul = value + (b - 128) * mul, mul * 128
    end
  end
  for _ = 1, u() do pos = pos + u() end
  if fixed(data) then
    -- nx, ny and the zigzagged base are the first values (read by hand: copying every word of
    -- a city cell for three of them would be waste); the grid is the u16 tail
    if pos + 3 > last then error('truncated source cell') end
    local a, b, c, d = byte(data, pos, pos + 3)
    local n = a + b * 256 + c * 65536 + d * 16777216
    local at, wi = pos + 4 + 2 * n, 0
    if at - 1 > last then error('truncated source cell') end
    local function word(k)
      local lo, hi = byte(data, pos + 4 + 2 * k, pos + 5 + 2 * k)
      return lo + hi * 256
    end
    local vals = {}
    for k = 1, 3 do
      if wi >= n then error('invalid source elevation grid') end
      local v = word(wi)
      if v == ESCAPE then
        if wi + 2 >= n then error('truncated source cell') end
        v, wi = word(wi + 1) + word(wi + 2) * 65536, wi + 3
      else wi = wi + 1 end
      vals[k] = v
    end
    local nx, ny, zb = vals[1], vals[2], vals[3]
    if nx < 2 or ny < 2 or nx > 257 or ny > 257 then error('invalid source elevation grid') end
    local heights, low = fixedHeights(data, at, last, nx * ny, zb % 2 == 0 and zb / 2 or -(zb + 1) / 2, pause)
    local cell = {terrain = {rect = rect, nx = nx, ny = ny, heights = heights}, low = low}
    for _, kind in ipairs(KINDS) do cell[kind] = {} end
    return cell
  end
  local nx, ny = u(), u()
  if nx < 2 or ny < 2 or nx > 257 or ny > 257 then error('invalid source elevation grid') end
  local heights, h, low = {}, 0, math.huge
  for k = 1, nx * ny do
    local v = u()
    h = h + (v % 2 == 0 and v / 2 or -(v + 1) / 2)
    heights[k] = h / 10
    if heights[k] < low then low = heights[k] end
    -- Terrain-only cells can have the same 257×257 grid as full cells. Yield at the
    -- same interval so one vista or foreign cell cannot monopolise a frame.
    if pause and k % 8192 == 0 then pause() end
  end
  local cell = {terrain = {rect = rect, nx = nx, ny = ny, heights = heights}, low = low}
  for _, kind in ipairs(KINDS) do cell[kind] = {} end
  return cell
end

-- Only the road centre lines of a cell, for the map: {id = .., highway = .., xy = {x1, y1, ...}}.
-- Terrain and every later section are skipped; nothing else is built.
function M.roads(data, first, last, ox, oy)
  local pos = first
  local function u()
    local value, mul = 0, 1
    while true do
      if pos > last or mul > 2 ^ 49 then error('truncated source cell') end
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
  local strings = {}
  for k = 1, u() do
    local n = u()
    strings[k] = sub(data, pos, pos + n - 1)
    pos = pos + n
  end
  if fixed(data) then
    local w, wn = wordPart(data, pos, last)
    local wi = 0
    u = function()
      if wi >= wn then error('truncated source cell') end
      local v = w[wi]
      if v == ESCAPE then v = w[wi + 1] + w[wi + 2] * 65536; wi = wi + 3 else wi = wi + 1 end
      return v
    end
    u(); u(); u()       -- nx, ny, base: the grid itself is after the words
  else
    local nx, ny = u(), u()
    for _ = 1, nx * ny do u() end
  end
  local out, ocx, ocy = {}, floor(ox * 100 + .5), floor(oy * 100 + .5)
  for k = 1, u() do
    local road = {id = strings[u() + 1]}
    u()
    for _ = 1, u() do
      local key, value = strings[u() + 1], strings[u() + 1]
      if key == 'highway' then road.highway = value end
    end
    for _ = 1, u() do u() end
    local xy, px, py = {}, ocx, ocy
    for n = 1, u() do
      px, py = px + s(), py + s()
      s()
      xy[2 * n - 1], xy[2 * n] = px / 100, py / 100
    end
    road.xy = xy
    out[k] = road
  end
  return out
end

-- Is slot k (0..63) present in a 16-hex-digit block mask? Digit d holds slots 4d..4d+3.
function M.present(mask, k)
  local digit = tonumber(sub(mask, floor(k / 4) + 1, floor(k / 4) + 1), 16)
  return digit ~= nil and floor(digit / 2 ^ (k % 4)) % 2 == 1
end

return M
