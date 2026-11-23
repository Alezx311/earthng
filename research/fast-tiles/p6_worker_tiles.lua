-- Fast tiles, probe 6: the real generator in a pool of worker VMs. N small vehicles each build
-- tiles of the square round the car (tileworker.lua: cells, generator.build, shapes), the game
-- thread only ticks them and reads what they wrote. Reports: each tile's time in its worker and
-- on the wall, the frame while the pool works against the frame before, and what loading the
-- finished shapes costs. The shapes are stood P6_LIFT m over the world (default 250), to be looked
-- at. Needs the mod's worker files where the VFS finds them (the planet, or the profile's lua/).
local N = P6_N or 8
local RADIUS = P6_RADIUS or 1          -- tiles each way round the car's own
local SLICE = P6_SLICE or 0.6          -- of the last frame, a worker's slice
local SLICE_MS = P6_SLICE_MS            -- or a fixed slice, ms
local LOAD = P6_LOAD ~= false          -- load the finished shapes (false: only build)
local LIFT = P6_LIFT or 250
local veh = getPlayerVehicle(0)
local at = veh:getPosition()
local d = extensions.e2r_world.dbg()
local native = d.native
local st = native.status()
local stream = st.stream or {}
local manifest
for _, country in ipairs(st.countries or {}) do
  if country.id == stream.country then
    for _, region in ipairs(country.regions or {}) do
      if region.id == stream.region then manifest = region.manifest end
    end
  end
end
if not manifest then return 'no region manifest for ' .. tostring(stream.country) .. '/' .. tostring(stream.region) end
local region = jsonReadFile(manifest)
local size = region.tileSize
local i0, j0 = math.floor(at.x / size), math.floor(at.y / size)
local codec = require('ge/extensions/e2r/bridge_codec')

local R = {order = {}, tiles = {}, manifest = manifest}
_G.e2rFT = {parts = {}}
function e2rFT.onPart(worker, id, kind, a, bytes, ms, stats)
  e2rFT.parts[#e2rFT.parts + 1] = {worker = worker, id = id, kind = kind, a = a, bytes = bytes, ms = ms, stats = stats}
end

local jobs = {}
for dj = -RADIUS, RADIUS do
  for di = -RADIUS, RADIUS do
    jobs[#jobs + 1] = {id = #jobs + 1, notify = 'e2rFT.onPart', manifest = manifest, i = i0 + di, j = j0 + dj, size = size,
      roadEarly = true, sceneEarly = false, out = string.format('/e2r_tiles/p6/%d_%d_%d', i0 + di, j0 + dj, os.time() % 100000),
      options = {tileSize = size, regionId = region.id, materials = '/earthng/planet/materials.json',
        packs = '/e2r_stream/fast-art/v10/packs.json', seaLevel = region.seaLevel, latitude = region.geo and region.geo[4],
        geo = region.geo, nature = region.nature, look = region.look, realStyle = true, cellSize = region.cellSize,
        farStep = 100, adaptiveFar = true, hyper = true}}
  end
end
R.jobs = #jobs

local workers, queue, running, done = {}, 1, {}, 0
local stage, frame = 'spawn', 0
local base, work = {}, {}
local startAt, lastMs = 0, 20
local loads, made = {}, {}
local timer = hptimer()
local pending = {}   -- finished part files waiting to be loaded, one a frame
local metrics, split = {}, {}

local function stat(list)
  if #list == 0 then return {} end
  table.sort(list)
  local sum = 0
  for k = 1, #list do sum = sum + list[k] end
  return {n = #list, mean = math.floor(sum / #list * 100) / 100, p50 = math.floor(list[math.ceil(#list * .5)] * 100) / 100,
    p99 = math.floor(list[math.ceil(#list * .99)] * 100) / 100, worst = math.floor(list[#list] * 10) / 10}
end

local function loadPart(part)
  local t = hptimer()
  local f = io.open(part.a, 'rb')
  local bytes = f and f:read('*a')
  if f then f:close() end
  if not bytes then return {error = 'unreadable ' .. tostring(part.a)} end
  local read = t:stopAndReset()
  local value = codec.decode(bytes)
  local decode = t:stopAndReset()
  local out = {kind = part.kind, readMs = read, decodeMs = decode, shapes = {}, kinds = {}}
  for _, name in ipairs({'road', 'scene', 'far', 'grass'}) do
    local m = value[name]
    if type(m) == 'table' and type(m.items) == 'table' then
      for _, it in ipairs(m.items) do
        local k = name .. '.' .. tostring(it.kind)
        out.kinds[k] = (out.kinds[k] or 0) + 1
        if it.kind == 'shape' then
          local ts = hptimer()
          local obj = createObject('TSStatic')
          obj:setField('shapeName', 0, it.file)
          obj:setField('collisionType', 0, 'None')
          obj:setField('decalType', 0, 'None')
          obj.canSave = false
          obj:registerObject('')
          obj:setPosRot(it.pos[1], it.pos[2], (it.pos[3] or 0) + LIFT, 0, 0, 0, 1)
          made[#made + 1] = obj
          out.shapes[#out.shapes + 1] = {file = it.file:match('[^/]+$'), ms = math.floor(ts:stop() * 100) / 100,
            triangles = it.triangles, materials = #(it.mats or {})}
        end
      end
    end
  end
  return out
end

return P.task(function(dt, ms)
  frame = frame + 1
  if stage == 'spawn' then
    for k = 1, N do
      local ok, v = pcall(core_vehicles.spawnNewVehicle, 'ball', {
        pos = vec3(at.x + 30 + k * 3, at.y + 30, at.z + 1), rot = quat(0, 0, 0, 1),
        autoEnterVehicle = false, canSpawnAnotherVehicleCheck = false, vehicleName = 'e2r_worker_' .. k})
      if ok and v then
        workers[#workers + 1] = v
        v:queueLuaCommand("e2rTileWorker = assert(loadfile('/lua/ge/extensions/e2r/tileworker.lua'))()")
      else R.spawnError = tostring(v) end
    end
    stage, frame = 'base', 0
  elseif stage == 'base' then
    if frame > 60 then base[#base + 1] = ms end
    if frame >= 240 then stage, frame, startAt = 'work', 0, 0; timer:stopAndReset() end
  elseif stage == 'work' then
    work[#work + 1] = ms
    Engine.Debug.getLastPerformanceMetrics(metrics)
    for k, v in pairs(metrics) do if type(v) == 'number' and v < 1e6 then split[k] = (split[k] or 0) + v end end
    lastMs = lastMs + (ms - lastMs) * .2
    -- what the workers said since the last frame
    local parts = e2rFT.parts
    e2rFT.parts = {}
    for _, part in ipairs(parts) do
      local job = jobs[part.id]
      local row = R.tiles[job.i .. '_' .. job.j] or {}
      R.tiles[job.i .. '_' .. job.j] = row
      if part.kind == 'done' then
        row.wallMs, row.stages, row.stats = math.floor(timer:stop() - job.startedAt), part.a, part.stats
        running[part.worker] = nil
        done = done + 1
      elseif part.kind == 'error' then
        row.error = part.a
        running[part.worker] = nil
        done = done + 1
      else
        row[part.kind .. 'AtMs'] = math.floor(part.ms)
        pending[#pending + 1] = {part = part, row = row}
      end
    end
    -- one finished part loaded a frame
    if pending[1] and not LOAD then pending = {} end
    if pending[1] then
      local p = table.remove(pending, 1)
      local t = hptimer()
      local ok, out = pcall(loadPart, p.part)
      loads[#loads + 1] = {tile = jobs[p.part.id].i .. '_' .. jobs[p.part.id].j, ms = math.floor(t:stop() * 10) / 10,
        detail = ok and out or tostring(out)}
    end
    for k, v in ipairs(workers) do
      if not running[k] and jobs[queue] then
        local job = jobs[queue]
        queue = queue + 1
        job.worker, job.startedAt = k, timer:stop()
        running[k] = job
        v:queueLuaCommand('e2rTileWorker.job(' .. serialize(job) .. ')')
      end
      if running[k] then v:queueLuaCommand(string.format('e2rTileWorker.tick(%.2f)', SLICE_MS or math.max(2, math.min(30, lastMs * SLICE)))) end
    end
    if done >= #jobs and not pending[1] then
      R.wallS = math.floor(timer:stop()) / 1000
      stage, frame = 'after', 0
    end
    if frame > 20000 then R.timeout = true; stage, frame = 'after', 0 end
  elseif stage == 'after' then
    if frame < 30 then return end
    R.base, R.work = stat(base), stat(work)
    R.split = {}
    for k, v in pairs(split) do if v / #work >= .3 then R.split[k] = math.floor(v / #work * 10) / 10 end end
    R.sliceMs = SLICE_MS or ('frame x ' .. SLICE)
    R.loads = loads
    for _, v in ipairs(workers) do v:delete() end
    _G.e2rFTMade = made
    return R
  end
end)
