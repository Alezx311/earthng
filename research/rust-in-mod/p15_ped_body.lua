-- The light physical pedestrian (research/rust-in-mod/ped_body.py, generated into <user>/current/vehicles/e2r_ped):
-- spawn time, does it stand, frame cost of active / switched-off bodies, wake + place cost, and a hit by the
-- player's car at ~30 km/h (does it fall). Writes a still of the hit: e2r_probe/ped_hit.png.
local MODEL = 'e2r_ped'
local N = tonumber(_G.__pedBodies or 8)
local PHASE = 150
local veh = be:getPlayerVehicle(0)
local c0, d0 = veh:getPosition(), veh:getDirectionVector()
local f = vec3(d0.x, d0.y, 0):normalized()
local side = vec3(-f.y, f.x, 0)
local up = vec3(0, 0, 1)
local REF_Z = .99  -- setPositionRotation places the ref node (pelvis front, 0.97 m) plus a margin
local out = {spawnMs = {}, wakeMs = {}}

local function ground(p)
  local z = be:getSurfaceHeightBelow(vec3(p.x, p.y, p.z + 3))
  return (z and z > -1e6) and z or p.z
end
local function spawnAt(p, dir, look)
  local t = hptimer()
  local q = quatFromDir(-dir, up)
  local ok, v = pcall(core_vehicles.spawnNewVehicle, MODEL, {
    pos = vec3(p.x, p.y, ground(p) + REF_Z), rot = q, autoEnterVehicle = false, cling = false,
    config = 'vehicles/' .. MODEL .. '/base.pc'})
  local ms = t:stop()
  if not ok or not v then return nil, tostring(v) end
  v:setPositionRotation(p.x, p.y, ground(p) + REF_Z, q.x, q.y, q.z, q.w)
  pcall(function() v.playerUsable = false end)
  if look then
    local fields = {'color', 'colorPalette0', 'colorPalette1'}
    for i, rgb in ipairs(look) do
      pcall(function() v[fields[i]] = ColorF(rgb[1], rgb[2], rgb[3], 1):asLinear4F() end)
    end
  end
  return v, ms
end
-- vertical extent of the body's box: ~1.75 standing, well under 1 lying
local function height(v)
  local ok, box = pcall(v.getSpawnWorldOOBB, v)
  if not ok or not box then return -1 end
  local h = box:getHalfExtents()
  local z = 0
  for k = 0, 2 do z = z + math.abs(box:getAxis(k).z) * ({h.x, h.y, h.z})[k + 1] end
  return 2 * z
end
local LOOKS = {{{.75, .1, .1}, {.08, .1, .2}, {.86, .68, .55}}, {{.1, .2, .5}, {.12, .12, .13}, {.72, .53, .4}},
  {{.2, .45, .25}, {.35, .3, .22}, {.93, .78, .66}}, {{.85, .65, .2}, {.25, .27, .3}, {.55, .38, .27}}}

local bodies = {}
local p, frame, acc = 0, 0, nil
local function metrics()
  local m = {}
  pcall(Engine.Debug.getLastPerformanceMetrics, m)
  return m
end
local hitT, target
local phases = {
  {'base', function() end},
  {'active', function()
    for k = 1, N do
      local pos = c0 + f * (14 + 2.2 * k) + side * ((k % 2 == 0) and 4 or -4)
      local v, ms = spawnAt(pos, side, LOOKS[k % #LOOKS + 1])
      if v then bodies[#bodies + 1] = v; out.spawnMs[#out.spawnMs + 1] = ms else out.spawnErr = ms end
    end
  end},
  {'standing', function()
    out.heights = {}
    for _, v in ipairs(bodies) do out.heights[#out.heights + 1] = height(v) end
  end},
  {'off', function() for _, v in ipairs(bodies) do v:setActive(0) end end},
  {'wake', function()
    for k, v in ipairs(bodies) do
      local t = hptimer()
      v:setActive(1)
      local pos = c0 + f * (14 + 2.2 * k) + side * ((k % 2 == 0) and 4 or -4)
      local q = quatFromDir(-side, up)
      v:setPositionRotation(pos.x, pos.y, ground(pos) + REF_Z, q.x, q.y, q.z, q.w)
      out.wakeMs[#out.wakeMs + 1] = t:stop()
    end
  end},
  {'woken', function()
    out.heightsWoken = {}
    for _, v in ipairs(bodies) do out.heightsWoken[#out.heightsWoken + 1] = height(v) end
  end},
  {'hit', function()
    -- one body right in the car's path, 10 m ahead; the car pushed to 8.3 m/s toward it
    target = bodies[1]
    local pos = c0 + f * 10
    local q = quatFromDir(-side, up)
    target:setPositionRotation(pos.x, pos.y, ground(pos) + REF_Z, q.x, q.y, q.z, q.w)
    out.targetHeight0 = nil
    hitT = 0
  end, 'hit'},
}
local function finish()
  local l = acc.frames
  table.sort(l)
  local total = 0
  for _, ms in ipairs(l) do total = total + ms end
  local r = {mean = total / #l, p99 = l[math.ceil(#l * .99)]}
  for k, v in pairs(acc.m) do r['m_' .. k] = v / #l end
  out[phases[p][1]] = r
end
local warm = 30
return P.task(function(dt, ms)
  if p > 0 and phases[p][3] == 'hit' then
    hitT = hitT + (dt or 0)
    if frame == 20 then
      out.targetHeight0 = height(target)
      local cam = c0 + side * 9 + f * 7 + up * 2.2
      local q = quatFromDir(c0 + f * 10 - cam, up)
      commands.setFreeCamera()
      core_camera.setPosRot(0, cam.x, cam.y, cam.z, q.x, q.y, q.z, q.w)
      hitT = 0
    end
    -- pushed every frame until the hit: the parked car brakes
    if frame >= 20 and hitT < 1.3 then veh:applyClusterVelocityScaleAdd(veh:getRefNodeId(), 0, f.x * 8.3, f.y * 8.3, 0) end
    if frame > 20 and hitT > .8 and not out.carSpeed then
      local cv = veh:getVelocity()
      out.carSpeed = math.sqrt(cv.x ^ 2 + cv.y ^ 2)
    end
    frame = frame + 1
    if frame > 20 and hitT > 1.6 and not out.shot then
      out.shot = true
      createScreenshot2({filename = 'e2r_probe/ped_hit', writeJPG = false, superSampling = 1})
    end
    if frame > 20 and hitT > 3.4 and not out.askedBroken then
      out.askedBroken = true
      _G.e2r_ped_broken = nil
      target:queueLuaCommand([[local n = 0
for i = 0, obj:getBeamCount() - 1 do if obj:beamIsBroken(i) then n = n + 1 end end
obj:queueGameEngineLua('e2r_ped_broken = ' .. n)]])
    end
    if frame > 20 and hitT > 4 then
      out.brokenBeams = _G.e2r_ped_broken
      out.targetHeight = height(target)
      local tv = target:getVelocity()
      out.targetSpeedAfter = math.sqrt(tv.x ^ 2 + tv.y ^ 2 + tv.z ^ 2)
      local tp = target:getPosition()
      out.targetMoved = math.sqrt((tp.x - (c0 + f * 10).x) ^ 2 + (tp.y - (c0 + f * 10).y) ^ 2)
      return out
    end
    return nil
  end
  if p == 0 or frame >= PHASE + warm then
    if p > 0 then finish() end
    p = p + 1
    phases[p][2]()
    frame, acc = 0, {frames = {}, m = {}}
    return nil
  end
  frame = frame + 1
  if frame > warm then
    acc.frames[#acc.frames + 1] = ms
    for k, v in pairs(metrics()) do
      if type(v) == 'number' then acc.m[k] = (acc.m[k] or 0) + v end
    end
  end
end)
