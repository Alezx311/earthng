-- Experiment (exp/rust-in-mod): the EGB3 source cell, written by rust/crates/pack/src/fixed.rs.
-- Same walk and same tables as cellformat.cell (generated from it by research/rust-in-mod/make_v3.py);
-- only the numbers after the string table come from a uint32_t[] that ffi.copy fills in one call.
-- The game's sandbox allows ffi.new arrays and ffi.copy from a string (not pointers, casts or ffi.load).
local ffi = require('ffi')
local CF = require('e2r/cellformat')
local M = {}
local byte, sub, floor = string.byte, string.sub, math.floor
local KINDS = CF.KINDS
M.ROAD_MARGIN, M.MARGIN, M.DETAIL_MARGIN, M.DETAILS = CF.ROAD_MARGIN, CF.MARGIN, CF.DETAIL_MARGIN, CF.DETAILS

-- Byte ranges of the cells in an EGB3 block (the header is the EGB2 header).
function M.block(data)
  if type(data) ~= 'string' or sub(data, 1, 4) ~= 'EGB3' then error('not an EGB3 source block') end
  return CF.block('EGB2' .. sub(data, 5))
end

function M.cell(data, first, last, ox, oy, rect, pause, keep, grid)
  pause = pause or function() end
  local pos = first
  local function bu()
    local value, mul = 0, 1
    while true do
      if pos > last or mul > 2 ^ 49 then error('truncated source cell') end
      local b = byte(data, pos)
      pos = pos + 1
      if b < 128 then return value + b * mul end
      value, mul = value + (b - 128) * mul, mul * 128
    end
  end
  local vals, vi, vn
  local function u()
    if vi >= vn then error('truncated source cell') end
    local v = vals[vi]
    vi = vi + 1
    return v
  end
  local function s()
    local v = u()
    if v % 2 == 0 then return v / 2 end
    return -(v + 1) / 2
  end
  local strings = {}
  for k = 1, bu() do
    local n = bu()
    if pos + n - 1 > last then error('truncated source string') end
    strings[k] = sub(data, pos, pos + n - 1)
    pos = pos + n
  end
  -- the fixed-width part: count, then count little-endian u32 values (EGB3)
  if pos + 3 > last then error('truncated source cell') end
  local b1, b2, b3, b4 = byte(data, pos, pos + 3)
  vn = b1 + b2 * 256 + b3 * 65536 + b4 * 16777216
  pos = pos + 4
  if pos + 4 * vn - 1 ~= last then error('source cell size mismatch') end
  -- M.values (optional {first = array}): a cell read by several tiles is copied once
  vals = M.values and M.values[first]
  if not vals then
    vals = ffi.new('uint32_t[?]', vn)
    ffi.copy(vals, sub(data, pos, last), 4 * vn)
    if M.values then M.values[first] = vals end
  end
  vi = 0
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
  local ocx, ocy = floor(ox * 100 + .5), floor(oy * 100 + .5)
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
  local nx, ny, heights
  if grid and grid.heights then
    nx, ny, heights, vi = grid.nx, grid.ny, grid.heights, grid.after
  else
    nx, ny = u(), u()
    if nx < 2 or ny < 2 or nx > 257 or ny > 257 then error('invalid source elevation grid') end
    local h = 0
    heights = {}
    for k = 1, nx * ny do
      h = h + s(); heights[k] = h / 10
      if k % 8192 == 0 then pause() end
    end
    if grid then grid.nx, grid.ny, grid.heights, grid.after = nx, ny, heights, vi end
  end
  local cell = {terrain = {rect = rect, nx = nx, ny = ny, heights = heights}}
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
  if vi ~= vn then error('trailing values after source cell') end
  return cell
end


return M
