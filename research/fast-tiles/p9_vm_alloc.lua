-- Fast tiles, probe 9: why does the frame wait ~3 times a worker's slice when the worker runs the
-- generator, and not when it runs a plain loop (p2)? Eight VMs burn 8 ms a frame: a plain loop,
-- a loop that makes garbage as the generator does (tables), the same with the collector stopped,
-- and a loop that only keeps a large heap alive. PhysicsAndVLUA is the engine's own wait.
local N = 8
local veh = getPlayerVehicle(0)
local at = veh:getPosition()
_G.e2rA = {}
local SETUP = [[
e2rKeep = {}
function e2rBurn(ms, mode)
  local t0 = os.clock()
  local x = 0
  if mode == 'plain' then
    while (os.clock() - t0) * 1000 < ms do for i = 1, 2000 do x = x + i % 7 end end
  else
    local ring, at = e2rKeep, 0
    while (os.clock() - t0) * 1000 < ms do
      for i = 1, 500 do
        at = at % 20000 + 1
        ring[at] = {i, i + 1, i + 2, x = i}
      end
    end
  end
  e2rUsed = (e2rUsed or 0) + (os.clock() - t0) * 1000
  e2rN = (e2rN or 0) + 1
end
function e2rSay(id) obj:queueGameEngineLua(string.format('e2rA[%d] = {ms = %.2f, heapMB = %.0f}', id, (e2rUsed or 0) / math.max(1, e2rN or 1), collectgarbage('count') / 1024)); e2rUsed, e2rN = 0, 0 end
]]
local workers = {}
for k = 1, N do
  local ok, v = pcall(core_vehicles.spawnNewVehicle, 'ball', {
    pos = vec3(at.x + 30 + k * 3, at.y + 36, at.z + 1), rot = quat(0, 0, 0, 1),
    autoEnterVehicle = false, canSpawnAnotherVehicleCheck = false, vehicleName = 'e2r_worker_a' .. k})
  if ok and v then workers[#workers + 1] = v; v:queueLuaCommand(SETUP) end
end
local runs = {{'idle', nil}, {'plain', 'plain'}, {'garbage', 'alloc'}, {'garbageGcStopped', 'alloc', 'stop'},
  {'garbageRestarted', 'alloc', 'restart'}, {'idle2', nil}}
local FRAMES = 200
local m = {}
local stage, frame, run, sums, list = 'settle', 0, 0, {}, {}
local R = {order = {}}
return P.task(function(dt, ms)
  frame = frame + 1
  if stage == 'settle' then
    if frame > 90 then stage, frame = 'next', 0 end
  elseif stage == 'next' then
    run = run + 1
    if not runs[run] then for _, v in ipairs(workers) do v:delete() end; return R end
    local r = runs[run]
    for k, v in ipairs(workers) do
      if r[3] then v:queueLuaCommand("collectgarbage('" .. r[3] .. "')") end
      v:queueLuaCommand('e2rSay(' .. k .. ')')
    end
    stage, frame, sums, list = 'run', 0, {}, {}
  elseif stage == 'run' then
    local r = runs[run]
    if frame > 10 then
      list[#list + 1] = ms
      Engine.Debug.getLastPerformanceMetrics(m)
      for k, v in pairs(m) do if type(v) == 'number' and v < 1e6 then sums[k] = (sums[k] or 0) + v end end
    end
    if r[2] then for _, v in ipairs(workers) do v:queueLuaCommand("e2rBurn(8, '" .. r[2] .. "')") end end
    if frame >= FRAMES + 10 then
      _G.e2rA = {}
      for k, v in ipairs(workers) do v:queueLuaCommand('e2rSay(' .. k .. ')') end
      stage, frame = 'collect', 0
    end
  elseif stage == 'collect' then
    if frame < 6 then return end
    local r = runs[run]
    table.sort(list)
    local total = 0
    for k = 1, #list do total = total + list[k] end
    local used, heap, count = 0, 0, 0
    for _, w in pairs(_G.e2rA) do used, heap, count = used + w.ms, math.max(heap, w.heapMB), count + 1 end
    R[r[1]] = {frame = math.floor(total / #list * 100) / 100, p99 = math.floor(list[math.ceil(#list * .99)] * 10) / 10,
      vlua = math.floor((sums.PhysicsAndVLUA or 0) / #list * 100) / 100, sliceMs = count > 0 and math.floor(used / count * 100) / 100 or 0,
      heapMB = heap}
    R.order[#R.order + 1] = r[1]
    stage, frame = 'next', 0
  end
end)
