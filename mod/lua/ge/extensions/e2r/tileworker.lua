-- A tile built off the game thread. Runs only inside a worker VM: the Lua of a small hidden vehicle
-- (workers.lua spawns a pool of them). The engine runs every vehicle's Lua on its own thread beside
-- the frame, so N workers build N tiles at once while GE Lua only hands out jobs and loads results
-- (research/fast-tiles: 8 VMs at 16 ms of Lua each a frame cost the frame ~2 ms).
--
-- A worker builds with the game's own code: it reads the pack's cell blocks through the VFS and
-- decodes them with cellformat.lua as native.lua does, calls generator.build with the options
-- native.lua made for the tile, packs each layer's meshes into compiled shapes (tileshapes.lua)
-- and writes them and the rest of the layer (bridge_codec) to files GE Lua loads.
--
-- GE Lua drives it with queued commands: job(args), tick(ms) every frame, cancel(id). A tick
-- resumes the build for about `ms`: the frame waits for a vehicle's Lua, so a slice stays under
-- the frame's own length. Answers go back by obj:queueGameEngineLua(<notify>(worker, id, ...)).
--
-- A tile is built in stages, and the worker is free between them (24.11). A job with args.park
-- stops once its scene is out: it says "parked" and waits, its build suspended in this VM (what
-- it holds beyond the VM's cell cache is a few MB), until go(id) asks for the rest, the grass
-- layer. Meanwhile the worker takes other jobs. Before, a worker went on to the grass of a tile
-- 800 m from the car, a third of the tile's time, while a road the car was driving towards
-- waited for a worker; and when the game gave the grass up, the whole job was thrown away and
-- the tile built again later for its grass alone. The worker runs one job at a time: a new job
-- first, then a parked one that has been told to go. It says "free" with the count of the
-- commands it has taken when it has nothing to run, so GE Lua knows whether that answer is
-- older than the last command it sent.
local M = {}
local clock = os.clock   -- a vehicle VM has no hptimer; os.clock is the wall clock on Windows

-- A vehicle VM has a fifth of GE Lua's trace cache (maxtrace 2000, maxmcode 4000: the game's
-- lua/vehicle/main.lua). That is enough for the generator: a Kyiv tile takes the same 850-910 ms
-- with these limits, GE Lua's and larger ones, against 3.3 s with LuaJIT's defaults
-- (research/fast-tiles/tile_to_shapes.py --jit). So the limits are left as the game set them.

if rawget(_G, 'hptimer') == nil then
  rawset(_G, 'hptimer', function()
    local t0 = clock()
    return {stop = function() return (clock() - t0) * 1000 end,
      stopAndReset = function() local now = clock(); local ms = (now - t0) * 1000; t0 = now; return ms end}
  end)
end

-- the mod's modules by the names GE Lua requires them (lua/ge is not on a vehicle VM's path)
local function searcher(name)
  if type(name) ~= 'string' or name:sub(1, 18) ~= 'ge/extensions/e2r/' then return nil end
  local chunk, err = loadfile('/lua/' .. name .. '.lua')
  return chunk or ('\n\t' .. tostring(err))
end
do
  local loaders = package.loaders or package.searchers
  local have = false
  for _, f in ipairs(loaders) do if f == M.searcher then have = true end end
  if not have then table.insert(loaders, 2, searcher) end
  M.searcher = searcher
end

local cellformat, generator, shapes, codec
local function modules()
  if generator then return end
  codec = require('ge/extensions/e2r/bridge_codec')
  cellformat = require('ge/extensions/e2r/cellformat')
  shapes = require('ge/extensions/e2r/tileshapes')
  generator = require('ge/extensions/e2r/generator')
end

local regions = {}
local blocks, blockClock, grids = {}, 0, {}
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

local function region(manifest)
  local d = regions[manifest]
  if d then return d end
  d = jsonReadFile(manifest)
  if type(d) ~= 'table' or type(d.blocks) ~= 'table' then error('e2r worker: region manifest: ' .. tostring(manifest)) end
  regions[manifest] = d
  return d
end

local function readBytes(path, pause)
  local f = io.open(path, 'rb')
  if not f then error('e2r worker: cannot open ' .. tostring(path)) end
  local parts = {}
  while true do
    local s = f:read(262144)
    if not s then break end
    parts[#parts + 1] = s
    if #s < 262144 then break end
    pause()
  end
  f:close()
  return table.concat(parts)
end

local function loadBlock(block, pause)
  blockClock = blockClock + 1
  local hit = blocks[block.path]
  if hit then hit.used = blockClock; return hit end
  local data = readBytes(block.path, pause)
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

-- native.lua loadCell for the region's own schemaVersion 2 cell (GE Lua sends only tiles whose
-- cells are all its own region's, none live or a neighbour's)
local function loadCell(d, key, i, j, keep, pause, lows)
  local b, s = blocksOf(d), d.cellSize
  local block = d.blocks[keyOf(math.floor(i / b), math.floor(j / b))]
  if block.memory then error('e2r worker: live block') end
  local loaded = loadBlock(block, pause)
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

-- native.lua loadTerrain: a vista block needs the cell's elevation grid alone
local function loadTerrain(d, key, i, j, pause, lows)
  local b, s = blocksOf(d), d.cellSize
  local block = d.blocks[keyOf(math.floor(i / b), math.floor(j / b))]
  if block.memory then error('e2r worker: live block') end
  local loaded = loadBlock(block, pause)
  local range = loaded.slots[i % b + (j % b) * b]
  if not range then error('source block lacks cell: ' .. key) end
  local cell = cellformat.terrain(loaded.data, range[1], range[2], {i * s, j * s, (i + 1) * s, (j + 1) * s}, pause)
  if lows[key] == nil then lows[key] = cell.low end
  return cell
end

local function writeFile_(path, bytes)
  local f = io.open(path, 'wb')
  if not f then error('e2r worker: cannot write ' .. tostring(path)) end
  f:write(bytes)
  f:close()
end

local function say(job, fmt, ...)
  obj:queueGameEngineLua(string.format('%s(%d, %d, ' .. fmt .. ')', job.notify, job.worker, job.id, ...))
end

-- The collector of this VM. The engine runs a full collection in a Lua VM whose heap has grown by
-- a third since the last one (gc.lua found it in GE Lua, 12.11), and the frame waits for it as for
-- any Lua of a vehicle: the first drives with the pool had 12-14 frames of 100-200 ms spent
-- waiting for vehicles, with no worker slice over 54 ms (23.11). So the heap is kept from that
-- line: a held array raises it (the engine counts a third of the heap it found, array included),
-- and the garbage of a build is collected in steps inside the worker's own slices, a share of
-- each once the heap has grown, and to the end of a cycle after every tile.
local GC = {heldMB = 160, rise = 48 * 1024, share = .3, floor = nil, running = false, steps = 0, cycles = 0}
local function gcStep(ms)
  local t = clock()
  repeat
    GC.steps = GC.steps + 1
    if collectgarbage('step', 0) then
      GC.running, GC.cycles = false, GC.cycles + 1
      GC.floor = collectgarbage('count')
      return true
    end
  until (clock() - t) * 1000 >= ms
  return false
end
local function gcPace(ms)
  if not GC.held then
    -- (an FFI array is one object to the collector: nothing to walk)
    local ok, array = pcall(function() return require('ffi').new('uint8_t[?]', GC.heldMB * 1024 * 1024) end)
    GC.held = ok and array or false
    GC.floor = collectgarbage('count')
  end
  if GC.running or collectgarbage('count') > (GC.floor or 0) + GC.rise then
    GC.running = true
    gcStep(ms * GC.share)
  end
end

-- args: {id, worker, notify, manifest, i, j, size, options (native.lua's options without its
-- functions), roadEarly, sceneEarly, out (the path the files' names start with), shapes (false:
-- meshes stay tables)}
local function run(job, pause)
  modules()
  local args = job
  local t0 = clock()
  local d = region(args.manifest)
  local stageMs, last, lastStage = {}, clock(), 'cells'
  local size, s = args.size or d.tileSize, d.cellSize
  local x0, y0 = args.i * size, args.j * size
  local tileRect = {x0, y0, x0 + size, y0 + size}
  local cells, seen, lows = {}, {}, {}
  local function addCell(i, j)
    if not ownCell(d, i, j) then return end
    local cellKey = keyOf(i, j)
    if seen[cellKey] then return end
    seen[cellKey] = true
    cells[#cells + 1] = args.vista and loadTerrain(d, cellKey, i, j, pause, lows)
      or loadCell(d, cellKey, i, j, tileRect, pause, lows)
  end
  for i = math.floor(x0 / s), math.ceil((x0 + size) / s) - 1 do
    for j = math.floor(y0 / s), math.ceil((y0 + size) / s) - 1 do addCell(i, j) end
  end
  local pad = 40
  for i = math.floor((x0 - pad) / s), math.ceil((x0 + size + pad) / s) - 1 do
    for j = math.floor((y0 - pad) / s), math.ceil((y0 + size + pad) / s) - 1 do addCell(i, j) end
  end
  local function mark(stage)
    local now = clock()
    stageMs[lastStage] = (stageMs[lastStage] or 0) + (now - last) * 1000
    last, lastStage = now, stage
    job.where = stage
  end
  mark('cells')
  local options = args.options or {}
  options.pause, options.mark = pause, mark
  -- the far view's colour maps a far or horizon tile is draped in, from their files (farmap.lua)
  if options.farMapData then
    options.farMap = require('ge/extensions/e2r/farmap').make(options.farMapData)
    options.farMapData = nil
  end
  local key = keyOf(args.i, args.j)
  local packMs, bytesOut, shapeCount, serial = 0, 0, 0, 0
  -- a layer's meshes into shapes, in place
  local function pack(manifest, layer)
    if args.shapes == false or type(manifest) ~= 'table' then return end
    manifest.key = key
    local t = clock()
    local was = job.where
    job.where = 'pack-' .. layer
    local stats = shapes.pack(manifest, layer,
      function(class) return string.format('%s_%s_%s.cdae', args.out, layer, class) end,
      writeFile_, pause)
    job.where = was
    packMs = packMs + (clock() - t) * 1000
    if stats then bytesOut, shapeCount = bytesOut + stats.bytes, shapeCount + stats.shapes end
  end
  local function send(kind, value)
    local t = clock()
    local bytes = codec.encode(value)
    local encodeMs = (clock() - t) * 1000
    if encodeMs > (job.encodeMs or 0) then job.encodeMs = encodeMs end
    serial = serial + 1
    local path = string.format('%s_part%d.emc', args.out, serial)
    writeFile_(path, bytes)
    packMs = packMs + (clock() - t) * 1000
    bytesOut = bytesOut + #bytes
    say(job, '%q, %q, %d, %.1f', kind, path, #bytes, (clock() - t0) * 1000)
  end
  if args.roadEarly then
    options.roadReady = function(road, nav)
      pack(road, 'road')
      send('road', {road = road, nav = nav})
    end
    if args.sceneEarly then
      options.sceneReady = function(scene)
        pack(scene, 'scene')
        send('scene', {scene = scene})
        -- the rest (the grass layer) when it is asked for: the worker is free meanwhile
        if args.park and not job.go then
          mark('parked')
          job.where = 'parked'
          job.stop()
          mark('grass-start')
        end
      end
    end
  end
  local road, scene, far, nav, grass = generator.build(cells, args.i, args.j, options)
  mark('done')
  local final = {far = far, grass = grass, lows = lows}
  if not args.roadEarly then final.road, final.nav = road, nav; pack(road, 'road') end
  if not (args.roadEarly and args.sceneEarly) or not grass then final.scene = scene; pack(scene, 'scene') end
  pack(far, options.horizon and 'horizon' or 'far')
  pack(grass, 'grass')
  send('final', final)
  -- the tile is out: let go of it and finish a collector cycle before the next one starts
  local cellCount = #cells
  road, scene, far, nav, grass, final, cells, options = nil, nil, nil, nil, nil, nil, nil, nil
  job.options = nil
  job.where = 'collect'
  GC.running = true
  while not gcStep(1) do pause() end
  -- the job's own ms by the stage a slice began in (job.stageBusy: the clock between two marks
  -- also counts the frames between slices, three to five times the work)
  local stages = {}
  for name, ms in pairs(job.stageBusy or stageMs) do stages[#stages + 1] = string.format('%s=%.0f', name, ms) end
  -- (ticks: how long this VM was held a tick, the build and the collector's share together, in
  -- frames of the tick's own slice: up to 1.5 of it, to 3, to 6, over 6; gcMs: the collector's)
  local h = job.ticks
  say(job, '"done", %q, %d, %.1f, {ms = %.1f, packMs = %.1f, shapes = %d, cells = %d, heapMB = %.0f, slices = %d, longest = %.1f, longestAt = %q, encodeMs = %.1f, over50 = %q, gcMs = %.1f, askedMs = %.1f, ticks = {%d, %d, %d, %d}}',
    table.concat(stages, ' '), bytesOut, (clock() - t0) * 1000, job.busyMs, packMs, shapeCount, cellCount,
    collectgarbage('count') / 1024, job.slices, job.longest, tostring(job.longestAt), job.encodeMs or 0, table.concat(job.over, ' '),
    job.gcMs, job.askedMs, h[1], h[2], h[3], h[4])
end

-- The job being built, the new ones waiting for it to end or park, the parked ones by id, the
-- commands taken so far and the count the last "free" was said with.
local current
local queue, parked, seen, saidFree = {}, {}, 0, nil
local PARK = {}   -- a job's yield at the end of a stage
local who         -- {notify, worker}: where "free" is said (from the first job)

-- the next job to run: a new one, else a parked one that was told to go
local function nextJob()
  if #queue > 0 then return table.remove(queue, 1) end
  for id, job in pairs(parked) do
    if job.go then
      parked[id] = nil
      return job
    end
  end
end

-- say "free" once there is nothing to run (GE Lua holds it against the commands it has sent)
local function settle()
  if not current then current = nextJob() end
  if not current and who and saidFree ~= seen then
    saidFree = seen
    local count = 0
    for _ in pairs(parked) do count = count + 1 end
    obj:queueGameEngineLua(string.format('%s(%d, 0, "free", %d, %d)', who.notify, who.worker, seen, count))
  end
end

-- A new job. It runs when the one in hand has ended or parked.
function M.job(args)
  seen = seen + 1
  local job = args
  who = who or {notify = job.notify, worker = job.worker}
  job.busyMs, job.slices, job.longest, job.over = 0, 0, 0, {}
  job.gcMs, job.askedMs, job.ticks = 0, 0, {0, 0, 0, 0}
  local deadline = 0
  local function pause()
    if clock() >= deadline then
      coroutine.yield()
    end
  end
  job.setDeadline = function(t) deadline = t end
  job.stop = function() coroutine.yield(PARK) end   -- (args.park is the job's own switch)
  job.co = coroutine.create(function() run(job, pause) end)
  queue[#queue + 1] = job
  settle()
end

-- The rest of a parked job is wanted (one that has not reached its stop yet will not make it).
function M.go(id)
  seen = seen + 1
  local job = parked[id]
  if job then
    job.go = true
  elseif current and current.id == id then
    current.go = true
  else
    for _, waiting in ipairs(queue) do
      if waiting.id == id then waiting.go = true end
    end
  end
  settle()
end

function M.cancel(id)
  seen = seen + 1
  if current and (id == nil or current.id == id) then current = nil end
  if id == nil then
    queue, parked = {}, {}
  else
    parked[id] = nil
    for k = #queue, 1, -1 do
      if queue[k].id == id then table.remove(queue, k) end
    end
  end
  settle()
end

-- Resume the job in hand for about `ms`.
function M.tick(ms)
  local job = current
  if not job then settle(); return end
  local t = clock()
  job.setDeadline(t + ms / 1000)
  local before = job.where
  -- (builds of several tiles take turns in this VM: the generator keeps each one's scratch state)
  local ok, err = (generator and generator.resumeBuild or coroutine.resume)(job.co)
  local used = (clock() - t) * 1000
  job.busyMs, job.slices = job.busyMs + used, job.slices + 1
  local busy = job.stageBusy
  if not busy then busy = {}; job.stageBusy = busy end
  local at = tostring(before or 'start')
  busy[at] = (busy[at] or 0) + used
  if ok and job.where ~= 'collect' then gcPace(ms) end
  -- the whole tick against what was asked (the frame waits for the longest of the pool's)
  local held = (clock() - t) * 1000
  local share = held / math.max(ms, .5)
  local h = job.ticks
  local bin = share <= 1.5 and 1 or (share <= 3 and 2 or (share <= 6 and 3 or 4))
  h[bin] = h[bin] + 1
  job.gcMs, job.askedMs = job.gcMs + (held - used), job.askedMs + ms
  if used > job.longest then job.longest, job.longestAt = used, tostring(before) .. '>' .. tostring(job.where) end
  -- a slice far over what was asked: where it began and ended, for the report
  if used > ms + 50 and #job.over < 12 then job.over[#job.over + 1] = string.format('%s>%s:%.0f', tostring(before), tostring(job.where), used) end
  if current ~= job then
    -- (cancelled from inside its own slice: nothing to do)
  elseif not ok then
    current = nil
    say(job, '"error", %q, 0, 0', tostring(err) .. '\n' .. debug.traceback(job.co))
  elseif coroutine.status(job.co) == 'dead' then
    current = nil
  elseif err == PARK then
    if job.go then
      -- told to go on before it got here: no stop
    else
      current = nil
      parked[job.id] = job
      say(job, '"parked", "", 0, %.1f', job.busyMs)
    end
  end
  if not current then settle() end
end

function M.idle() return current == nil and #queue == 0 end
-- (for the tests: the jobs parked here)
function M.parkedCount()
  local n = 0
  for _ in pairs(parked) do n = n + 1 end
  return n
end

return M
