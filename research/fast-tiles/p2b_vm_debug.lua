-- Fast tiles, probe 2b: one worker VM, step by step: does a queued burn run, what timer it has.
local veh = getPlayerVehicle(0)
local at = veh:getPosition()
_G.e2rDbg = {}
local ok, v = pcall(core_vehicles.spawnNewVehicle, P2_MODEL or 'ball', {
  pos = vec3(at.x + 40, at.y + 44, at.z + 1), rot = quat(0, 0, 0, 1),
  autoEnterVehicle = false, canSpawnAnotherVehicleCheck = false, vehicleName = 'e2r_worker_dbg'})
if not ok or not v then return 'spawn failed ' .. tostring(v) end
local function ask(tag, code)
  v:queueLuaCommand(string.format([[
    local ok, value = pcall(function() %s end)
    obj:queueGameEngineLua(string.format('e2rDbg[%%q] = %%q', %q, tostring(ok) .. ' ' .. tostring(value)))
  ]], code, tag))
end
local n = 0
return P.task(function()
  n = n + 1
  if n == 30 then
    ask('timerType', "return type(hptimer) .. ' ' .. type(HighPerfTimer)")
    ask('timer', "local t = hptimer(); local x = 0; for i = 1, 3e6 do x = x + i % 7 end; return tostring(t:stop())")
    ask('clock', "local c = os.clock(); local x = 0; for i = 1, 3e6 do x = x + i % 7 end; return (os.clock() - c) * 1000")
    ask('burn', [[
      local t = hptimer(); local loops, x = 0, 0
      while t:stop() < 8 do for i = 1, 2000 do x = x + i % 7 end; loops = loops + 1 end
      return loops .. ' loops in ' .. t:stop()]])
    ask('active', "return tostring(obj:getId and obj:getId())")
    ask('thread', "return tostring(Engine and Engine.Platform and 'engine' or 'none')")
  end
  if n == 90 then
    local out = {}
    for k, val in pairs(_G.e2rDbg) do out[k] = val end
    v:delete()
    return out
  end
end)
