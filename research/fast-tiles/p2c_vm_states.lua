-- Fast tiles, probe 2c: when does a worker VM run what is queued to it? Active, switched off
-- (setActive 0), hidden, and with the simulation paused. Each stage queues 60 burns of 2 ms.
local veh = getPlayerVehicle(0)
local at = veh:getPosition()
_G.e2rSt = {}
local ok, v = pcall(core_vehicles.spawnNewVehicle, P2_MODEL or 'ball', {
  pos = vec3(at.x + 40, at.y + 48, at.z + 1), rot = quat(0, 0, 0, 1),
  autoEnterVehicle = false, canSpawnAnotherVehicleCheck = false, vehicleName = 'e2r_worker_st'})
if not ok or not v then return 'spawn failed ' .. tostring(v) end
v:queueLuaCommand([[
e2rN = 0
function e2rBurn(ms) local t0 = os.clock(); local x = 0; while (os.clock() - t0) * 1000 < ms do for i = 1, 500 do x = x + i % 7 end end; e2rN = e2rN + 1 end
function e2rSay(tag) obj:queueGameEngineLua(string.format('e2rSt[%q] = %d', tag, e2rN)); e2rN = 0 end
]])
local stages = {
  {'active', function() end},
  {'inactive', function() v:setActive(0) end},
  {'activeAgain', function() v:setActive(1) end},
  {'hidden', function() v:setHidden(true) end},
  {'paused', function() v:setHidden(false); simTimeAuthority.pause(true) end},
  {'resumed', function() simTimeAuthority.pause(false) end},
}
local n, k, R = 0, 0, {}
return P.task(function(dt, ms)
  n = n + 1
  if n < 30 then return end
  local at_ = (n - 30) % 80
  if at_ == 0 then
    k = k + 1
    if not stages[k] then
      v:delete()
      for tag, count in pairs(_G.e2rSt) do R[tag] = count end
      return R
    end
    local okk, err = pcall(stages[k][2])
    if not okk then R[stages[k][1] .. 'Error'] = tostring(err) end
  elseif at_ <= 60 then
    v:queueLuaCommand('e2rBurn(2)')
  elseif at_ == 70 then
    v:queueLuaCommand('e2rSay("' .. stages[k][1] .. '")')
  end
end)
