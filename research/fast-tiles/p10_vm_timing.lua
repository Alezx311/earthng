-- Fast tiles, probe 10: when does a vehicle's VM run what GE Lua queues to it, and what of it
-- does the frame wait for? The drive's ledger (24.11) showed frames in which the game thread was
-- busy for 20 ms of its own (a new shape file) with no wait for the vehicles at all, while a plain
-- frame waited 6.5 ms for the workers' 4 ms slices. So: does a queued command start at once,
-- beside GE Lua's own update, and which kind of work in a VM makes the frame wait?
--
-- Eight small vehicles; every frame GE Lua queues each a run of `ms` in a `mode` with its own
-- clock, then may keep itself busy for `ge` ms (a plain loop, as a long step of the game thread
-- would). A VM notes how long after the queueing it started and how long it ran. Modes:
--   stamp   nothing: only when it starts
--   plain   a loop without allocation
--   small   small tables into a ring (the generator's kind of garbage)
--   big     arrays grown to 60 000 numbers and dropped (blocks over the allocator's direct-map size)
--   string  1 MB strings built by concat
-- gc: the VM's collector for the run: 'stop', 'restart', or a step multiplier.
-- Before the runs it waits for the pool to be idle and stops the generator; it puts it back.
local N = 8
local FRAMES = rawget(_G, 'P10_FRAMES') or 150
local veh = getPlayerVehicle(0)
local at = veh:getPosition()
_G.e2rA = {}
local SETUP = [[
e2rKeep = {}
e2rAcc = {n = 0, delay = 0, dur = 0, late = 0}
function e2rRun(t0, ms, mode)
  local s = os.clock()
  local x = 0
  if mode == 'plain' then
    while (os.clock() - s) * 1000 < ms do for i = 1, 2000 do x = x + i % 7 end end
  elseif mode == 'small' then
    local ring, k = e2rKeep, 0
    while (os.clock() - s) * 1000 < ms do
      for i = 1, 500 do
        k = k % 20000 + 1
        ring[k] = {i, i + 1, i + 2, x = i}
      end
    end
  elseif mode == 'big' then
    while (os.clock() - s) * 1000 < ms do
      local t = {}
      for i = 1, 60000 do t[i] = i end
      e2rKeep[1] = t
    end
  elseif mode == 'string' then
    local piece = string.rep('x', 4096)
    while (os.clock() - s) * 1000 < ms do
      local parts = {}
      for i = 1, 256 do parts[i] = piece end
      e2rKeep[1] = table.concat(parts)
    end
  end
  local e = os.clock()
  local a = e2rAcc
  a.n, a.delay, a.dur = a.n + 1, a.delay + (s - t0), a.dur + (e - s)
  if (s - t0) * 1000 > 2 then a.late = a.late + 1 end
end
function e2rSay(id)
  local a = e2rAcc
  obj:queueGameEngineLua(string.format('e2rA[%d] = {n = %d, delay = %.3f, dur = %.3f, late = %d, heapMB = %.0f}', id, a.n,
    a.n > 0 and a.delay / a.n * 1000 or 0, a.n > 0 and a.dur / a.n * 1000 or 0, a.late, collectgarbage('count') / 1024))
  e2rAcc = {n = 0, delay = 0, dur = 0, late = 0}
end
]]
local workers = {}
for k = 1, N do
  local ok, v = pcall(core_vehicles.spawnNewVehicle, 'ball', {
    pos = vec3(at.x + 30 + k * 3, at.y + 36, at.z + 1), rot = quat(0, 0, 0, 1),
    autoEnterVehicle = false, canSpawnAnotherVehicleCheck = false, vehicleName = 'e2r_probe_b' .. k})
  if ok and v then workers[#workers + 1] = v; v:queueLuaCommand(SETUP) end
end
-- {name, mode, ms in the VM, ms GE Lua keeps itself busy, the VM's collector}
local runs = {
  {'idle'},
  {'stamp', 'stamp', 0, 0},
  {'geBusy20', nil, 0, 20},
  {'stamp+geBusy20', 'stamp', 0, 20},
  {'plain15+geBusy20', 'plain', 15, 20},
  {'plain8', 'plain', 8, 0},
  {'plain16', 'plain', 16, 0},
  {'small8', 'small', 8, 0},
  {'small8+geBusy20', 'small', 8, 20},
  {'small4', 'small', 4, 0},
  {'big8', 'big', 8, 0},
  {'string8', 'string', 8, 0},
  {'small8 stepmul1', 'small', 8, 0, 1},
  {'small8 stepmul1000', 'small', 8, 0, 1000},
  {'small8 gc stopped', 'small', 8, 0, 'stop'},
  {'idle2'},
}
local world = extensions.e2r_world and extensions.e2r_world.dbg and extensions.e2r_world.dbg()
local native = world and world.native
local m = {}
local stage, frame, run, sums, list = 'wait', 0, 0, {}, {}
local R = {order = {}, waited = 0}
local function restore()
  for _, v in ipairs(workers) do pcall(function() v:delete() end) end
  if native and rawget(_G, 'P10_GEN') then native.update = rawget(_G, 'P10_GEN'); rawset(_G, 'P10_GEN', nil) end
end
return P.task(function(dt, ms)
  frame = frame + 1
  if stage == 'wait' then
    -- the pool idle and nothing queued (or five minutes): the world has settled
    local pool = native and native.pool and native.pool() or {}
    local idle = (pool.workers or 0) == 0 or pool.free == pool.workers
    R.waited = frame
    if frame > 120 and (idle or frame > 18000) then
      if native and not rawget(_G, 'P10_GEN') then
        rawset(_G, 'P10_GEN', native.update)
        native.update = function() end
      end
      R.poolIdle = idle
      stage, frame = 'settle', 0
    end
  elseif stage == 'settle' then
    if frame > 120 then stage, frame = 'next', 0 end
  elseif stage == 'next' then
    run = run + 1
    if not runs[run] then restore(); return R end
    local r = runs[run]
    for k, v in ipairs(workers) do
      if r[5] == 'stop' then v:queueLuaCommand("collectgarbage('stop')")
      elseif type(r[5]) == 'number' then v:queueLuaCommand("e2rWasStep = collectgarbage('setstepmul', " .. r[5] .. ")") end
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
    local t0 = os.clock()
    if r[2] then
      local command = string.format('e2rRun(%.4f, %d, %q)', t0, r[3], r[2])
      for _, v in ipairs(workers) do v:queueLuaCommand(command) end
    end
    if (r[4] or 0) > 0 then
      local x = 0
      while (os.clock() - t0) * 1000 < r[4] do for i = 1, 2000 do x = x + i % 7 end end
    end
    if frame >= FRAMES + 10 then
      _G.e2rA = {}
      for k, v in ipairs(workers) do
        v:queueLuaCommand('e2rSay(' .. k .. ')')
        if r[5] == 'stop' then v:queueLuaCommand("collectgarbage('restart')")
        elseif type(r[5]) == 'number' then v:queueLuaCommand("collectgarbage('setstepmul', e2rWasStep or 200)") end
      end
      stage, frame = 'collect', 0
    end
  elseif stage == 'collect' then
    if frame < 8 then return end
    local r = runs[run]
    table.sort(list)
    local total = 0
    for k = 1, #list do total = total + list[k] end
    local delay, dur, heap, late, count = 0, 0, 0, 0, 0
    for _, w in pairs(_G.e2rA) do
      delay, dur, heap, late, count = delay + w.delay, dur + w.dur, math.max(heap, w.heapMB), late + w.late, count + 1
    end
    local function part(name) return math.floor((sums[name] or 0) / #list * 100) / 100 end
    R[r[1]] = {frame = math.floor(total / #list * 100) / 100, p99 = math.floor(list[math.ceil(#list * .99)] * 10) / 10,
      vlua = part('PhysicsAndVLUA'), lua = part('Lua'), luaGC = part('LuaGC'), render = part('Render'), shadows = part('RenderShadows'),
      nodes = part('PhysicsNodes'), present = part('FramePresent'), ticking = part('Ticking'),
      vmStartMs = count > 0 and math.floor(delay / count * 100) / 100 or nil,
      vmRunMs = count > 0 and math.floor(dur / count * 100) / 100 or nil,
      vmLateStarts = count > 0 and late or nil, vmHeapMB = count > 0 and heap or nil, vms = count}
    R.order[#R.order + 1] = r[1]
    stage, frame = 'next', 0
  end
end)
