-- Runs only inside a worker VM of the experimental Rust bridge (research/native-bridge/bridge),
-- never in GE Lua. The game sends this file with generator.lua and its modules, so a worker
-- builds a near tile with exactly the game's code: it reads the pack's cell blocks from the ZIPs
-- on disk (host_read), decodes them with cellformat.lua as native.lua does, calls
-- generator.build with the options native.lua made for that tile, and sends the manifests back
-- (bridge_codec). Host functions (Rust): host_read(vfsPath) -> bytes | nil, err;
-- host_region(id) -> encoded region data; host_clock() -> ms; host_cancelled() -> bool.
local ffi = require('ffi')
-- the game's vec3 is an FFI struct of three doubles; with it the generator writes mesh cdata
pcall(ffi.cdef, 'struct __luaVec3_t { double x, y, z; };')
if rawget(_G, 'vec3') == nil then rawset(_G, 'vec3', ffi.typeof('struct __luaVec3_t')) end

-- FS:fileExists: the pack's and planet's files are answered from the ZIPs; the game's own
-- content (stock shapes, textures) is assumed present and reported, and GE Lua checks every
-- reported path before it accepts the tile (a false one sends FS_FALSE and resets the VMs).
local assumed, assumedList = {}, {}
local packCache = {}
local function packFile(path)
  local hit = packCache[path]
  if hit == nil then
    local data = host_read(path)
    hit = data or false
    packCache[path] = hit
  end
  return hit
end
rawset(_G, 'FS', {fileExists = function(_, path)
  if type(path) ~= 'string' then return false end
  if __bridge_fs_false[path] then return false end
  if path:sub(1, 9) == '/earthng/' then return packFile(path) ~= false end
  if not assumed[path] then assumed[path] = true; assumedList[#assumedList + 1] = path end
  return true
end})
-- io.open for the pack and planet (biome.lua's climate grid); nothing else is readable
local realOpen = io.open
io.open = function(path, mode)
  if type(path) == 'string' and path:sub(1, 9) == '/earthng/' then
    local data = packFile(path)
    if not data then return nil end
    local pos = 1
    return {read = function(_, n)
      if n == '*a' or n == nil then local c = data:sub(pos); pos = #data + 1; return c end
      if pos > #data then return nil end
      local last = math.min(#data, pos + n - 1)
      local c = data:sub(pos, last); pos = last + 1
      return c
    end, close = function() end}
  end
  return nil, 'not readable in a bridge worker'
end
local logs = {}
rawset(_G, 'log', function(level, tag, msg)
  if #logs < 64 then logs[#logs + 1] = tostring(level) .. ' ' .. tostring(tag) .. ' ' .. tostring(msg) end
end)

local codec = require('ge/extensions/e2r/bridge_codec')
local cellformat = require('ge/extensions/e2r/cellformat')
local generator = require('ge/extensions/e2r/generator')

local M = {}
local regions = {}
local blocks, blockClock, grids = {}, 0, {}
local NONE = {}

local function keyOf(i, j) return string.format('%d_%d', i, j) end
local function blocksOf(d)
  local b = type(d) == 'table' and d.blockCells
  return type(b) == 'number' and b >= 1 and b or cellformat.BLOCK
end
local function ownCell(d, i, j)
  local b = blocksOf(d)
  local block = d.blocks[keyOf(math.floor(i / b), math.floor(j / b))]
  return block ~= nil and cellformat.present(block.mask, i % b + (j % b) * b)
end
local function evict(cache, limit)
  local n, oldest, oldestKey = 0, nil, nil
  for k, v in pairs(cache) do
    n = n + 1
    if not oldest or v.used < oldest then oldest, oldestKey = v.used, k end
  end
  if n > limit and oldestKey then cache[oldestKey] = nil end
end

local function region(id)
  local r = regions[id]
  if r then return r end
  local bytes = host_region(id)
  if not bytes then error('e2r-bridge: region not sent: ' .. tostring(id)) end
  r = codec.decode(bytes)
  regions[id] = r
  return r
end

local function loadBlock(blockKey, block, pause)
  blockClock = blockClock + 1
  local hit = blocks[block.path]
  if hit then hit.used = blockClock; return hit end
  local data, err = host_read(block.path)
  if not data then error('e2r-bridge: ' .. tostring(err)) end
  pause()
  hit = {data = data, slots = cellformat.block(data), used = blockClock}
  blocks[block.path] = hit
  evict(blocks, 8)
  return hit
end

local function minimumHeight(heights, pause)
  local low = math.huge
  for i, h in ipairs(heights) do
    if h < low then low = h end
    if i % 8192 == 0 then pause() end
  end
  return low
end

-- native.lua loadCell for an own schemaVersion 2 cell (GE Lua sends only tiles whose cells are
-- all its own region's, none live or foreign)
local function loadCell(d, key, i, j, keep, pause, lows)
  local b, s = blocksOf(d), d.cellSize
  local blockKey = keyOf(math.floor(i / b), math.floor(j / b))
  local block = d.blocks[blockKey]
  if block.memory then error('e2r-bridge: live block') end
  local loaded = loadBlock(blockKey, block, pause)
  local range = loaded.slots[i % b + (j % b) * b]
  if not range then error('source block lacks cell: ' .. key) end
  blockClock = blockClock + 1
  local grid = grids[block.path .. '|' .. key]
  if grid then grid.used = blockClock else
    grid = {data = {}, used = blockClock}
    grids[block.path .. '|' .. key] = grid
    evict(grids, 16)
  end
  local cell = cellformat.cell(loaded.data, range[1], range[2], i * s, j * s,
    {i * s, j * s, (i + 1) * s, (j + 1) * s}, pause, keep, grid.data)
  if lows[key] == nil then lows[key] = minimumHeight(cell.terrain.heights, pause) end
  return cell
end

-- args: {regionId, i, j, size, options (native.lua's data options), roadEarly, sceneEarly}
function M.run(argsBytes, flags, emit)
  local t0 = host_clock()
  local args = codec.decode(argsBytes)
  local d = region(args.regionId)
  local stageMs, last, lastStage = {}, host_clock(), 'cells'
  local calls = 0
  local function pause()
    calls = calls + 1
    if calls % 32 == 0 and host_cancelled() then error('e2r-bridge-cancelled', 0) end
  end
  local size, s = args.size, d.cellSize
  local x0, y0 = args.i * size, args.j * size
  local tileRect = {x0, y0, x0 + size, y0 + size}
  local cells, seen, lows = {}, {}, {}
  local function addCell(i, j)
    if not ownCell(d, i, j) then return end
    local cellKey = keyOf(i, j)
    if seen[cellKey] then return end
    seen[cellKey] = true
    cells[#cells + 1] = loadCell(d, cellKey, i, j, tileRect, pause, lows)
  end
  for i = math.floor(x0 / s), math.ceil((x0 + size) / s) - 1 do
    for j = math.floor(y0 / s), math.ceil((y0 + size) / s) - 1 do addCell(i, j) end
  end
  local pad = 40
  for i = math.floor((x0 - pad) / s), math.ceil((x0 + size + pad) / s) - 1 do
    for j = math.floor((y0 - pad) / s), math.ceil((y0 + size + pad) / s) - 1 do addCell(i, j) end
  end
  local function mark(stage)
    local now = host_clock()
    stageMs[lastStage] = (stageMs[lastStage] or 0) + now - last
    last, lastStage = now, stage
  end
  mark('cells')
  local options = args.options
  options.pause, options.mark = pause, mark
  local encodeMs, bytesOut = 0, 0
  local function send(kind, value)
    local t = host_clock()
    local bytes = codec.encode(value)
    encodeMs = encodeMs + host_clock() - t
    bytesOut = bytesOut + #bytes
    emit(kind, bytes)
  end
  if args.roadEarly then
    options.roadReady = function(road, nav) send(1, {road = road, nav = nav}) end
    if args.sceneEarly then
      options.sceneReady = function(scene) send(2, {scene = scene}) end
    end
  end
  local road, scene, far, nav, grass = generator.build(cells, args.i, args.j, options)
  mark('done')
  local final = {far = far, grass = grass, lows = lows, assumed = assumedList}
  if not args.roadEarly then final.road, final.nav = road, nav end
  if not (args.roadEarly and args.sceneEarly) or not grass then final.scene = scene end
  send(3, final)
  return codec.encode({ms = host_clock() - t0, stageMs = stageMs, encodeMs = encodeMs, bytes = bytesOut,
    cells = #cells, logs = #logs > 0 and logs or nil, heapKb = collectgarbage('count')})
end

return M
