-- Fast tiles, probe 2: are vehicle Lua VMs a pool of worker threads? N small vehicles each burn X ms
-- of Lua a frame (a queued command); the frame time and the work each did tell whether they ran on
-- their own cores beside the frame. Also: what a vehicle VM may read and write (files for shapes).
local N = P2_N or 8
local veh = getPlayerVehicle(0)
local at = veh:getPosition()
local R = {order = {}}
_G.e2rW = {}          -- [worker] = {loops, burns}: reported by the VMs
_G.e2rWInfo = {}

local SETUP = [[
e2rLoops, e2rBurns, e2rMs = 0, 0, 0
function e2rBurn(ms, id)
  -- a vehicle VM has no hptimer; os.clock is the wall clock on Windows
  local t0 = os.clock()
  local x, loops = 0, 0
  while (os.clock() - t0) * 1000 < ms do
    for i = 1, 2000 do x = x + i % 7 end
    loops = loops + 1
  end
  e2rLoops, e2rBurns, e2rMs = e2rLoops + loops, e2rBurns + 1, e2rMs + (os.clock() - t0) * 1000
end
function e2rReport(id)
  obj:queueGameEngineLua(string.format('e2rW[%d] = {loops = %d, burns = %d, ms = %.1f}', id, e2rLoops, e2rBurns, e2rMs))
  e2rLoops, e2rBurns, e2rMs = 0, 0, 0
end
function e2rInfo(id)
  local info = {}
  local function try(name, fn) local ok, v = pcall(fn); info[name] = ok and tostring(v) or ('ERR ' .. tostring(v)) end
  try('FS', function() return FS ~= nil end)
  try('ffi', function() return require('ffi') ~= nil end)
  try('jit', function() return jit.version .. ' ' .. tostring(jit.status()) end)
  try('write', function()
    local f = io.open('e2r_tiles/vm_' .. id .. '.bin', 'wb'); f:write(string.rep('\0\1\2\255', 1024)); f:close(); return 'ok' end)
  try('readBack', function() local f = io.open('e2r_tiles/vm_' .. id .. '.bin', 'rb'); local s = f:read('*a'); f:close(); return #s end)
  try('readFile', function() return #(readFile('/e2r_tiles/g20k_m1.cdae') or '') end)
  try('readModLua', function() return #(readFile('/lua/ge/extensions/e2r/quality.lua') or '') end)
  try('fsExists', function() return FS:fileExists('/lua/ge/extensions/e2r/generator.lua') end)
  try('loadGenerator', function() local f, e = loadfile('/lua/ge/extensions/e2r/fifo.lua'); return f and 'loaded' or e end)
  try('loadstring', function() return loadstring('return 41 + 1')() end)
  try('coroutine', function() return coroutine.wrap(function() return 7 end)() end)
  try('ffiNew', function() local ffi = require('ffi'); local a = ffi.new('float[4]'); a[1] = 2.5; return #ffi.string(a, 16) end)
  try('mem', function() return collectgarbage('count') end)
  local parts = {}
  for k, v in pairs(info) do parts[#parts + 1] = string.format('%s = %q', k, v) end
  obj:queueGameEngineLua('e2rWInfo[' .. id .. '] = {' .. table.concat(parts, ', ') .. '}')
end
]]

local workers = {}
local function spawn()
  for k = 1, N do
    local ok, v = pcall(core_vehicles.spawnNewVehicle, P2_MODEL or 'ball', {
      pos = vec3(at.x + 40 + k * 3, at.y + 40, at.z + 1), rot = quat(0, 0, 0, 1),
      autoEnterVehicle = false, canSpawnAnotherVehicleCheck = false, vehicleName = 'e2r_worker_' .. k})
    if ok and v then workers[#workers + 1] = v; v:queueLuaCommand(SETUP) else R.spawnError = tostring(v) end
  end
  R.spawned = #workers
end

-- {name, workers burning, ms each, frames}
local runs = {
  {'base', 0, 0}, {'w1_4ms', 1, 4}, {'w1_8ms', 1, 8}, {'w1_16ms', 1, 16},
  {'w2_8ms', 2, 8}, {'w4_8ms', 4, 8}, {'w8_8ms', 8, 8}, {'w8_4ms', 8, 4}, {'w8_16ms', 8, 16},
  {'w4_16ms', 4, 16}, {'base2', 0, 0},
}
local FRAMES = P2_FRAMES or 150
local stage, frame, run, sum, worst, list = 'spawn', 0, 0, 0, 0, {}
local wait = 0
return P.task(function(dt, ms)
  frame = frame + 1
  if stage == 'spawn' then
    spawn()
    stage, frame = 'settle', 0
  elseif stage == 'settle' then
    if frame == 60 then for k, v in ipairs(workers) do v:queueLuaCommand('e2rInfo(' .. k .. ')') end end
    if frame > 120 then R.info = e2rWInfo[1]; R.infoCount = tableSize(e2rWInfo); stage, frame = 'next', 0 end
  elseif stage == 'next' then
    run = run + 1
    if not runs[run] then
      for _, v in ipairs(workers) do v:delete() end
      return R
    end
    for k, v in ipairs(workers) do v:queueLuaCommand('e2rReport(' .. k .. ')') end
    _G.e2rW = {}
    stage, frame, sum, worst, list = 'run', 0, 0, 0, {}
  elseif stage == 'run' then
    local r = runs[run]
    if frame > 10 then sum, worst = sum + ms, math.max(worst, ms); list[#list + 1] = ms end
    for k = 1, math.min(r[2], #workers) do workers[k]:queueLuaCommand('e2rBurn(' .. r[3] .. ',' .. k .. ')') end
    if frame >= FRAMES + 10 then
      _G.e2rW = {}
      for k, v in ipairs(workers) do v:queueLuaCommand('e2rReport(' .. k .. ')') end
      stage, frame = 'collect', 0
    end
  elseif stage == 'collect' then
    if frame >= 6 then
      local r = runs[run]
      table.sort(list)
      local loops, burns, busy, per = 0, 0, 0, {}
      for k, w in pairs(_G.e2rW) do loops, burns, busy = loops + w.loops, burns + w.burns, busy + w.ms; per[#per + 1] = w.loops end
      R[r[1]] = {frame = math.floor(sum / #list * 100) / 100, p50 = math.floor(list[math.ceil(#list * .5)] * 100) / 100,
        p99 = math.floor(list[math.ceil(#list * .99)] * 100) / 100, worst = math.floor(worst * 10) / 10,
        loops = loops, burns = burns, busyMsPerFrame = math.floor(busy / #list * 10) / 10,
        loopsPerBusyMs = busy > 0 and math.floor(loops / busy) or 0, perWorker = table.concat(per, ' ')}
      R.order[#R.order + 1] = r[1]
      stage, frame = 'next', 0
    end
  end
end)
