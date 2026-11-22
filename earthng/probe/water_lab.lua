-- Water lab: the same views of a shore under several weathers, without a rebuild (a --manual
-- --probe session of test_world.py).
--
-- Set LAB in an earlier command, then run this file:
--   LAB = {views = {{'beach', lat, lon, agl, atLat, atLon, atAgl, fov}, ...},
--          weathers = {{name = 'fair'}, {name = 'storm', state = {windSpeed = 9, cloudCover = 1, numOfDrops = 3000}},
--                      {name = 'night', time = .5}},
--          settle = 4, viewSettle = 30, prefix = 'water'}
-- state goes to core_environment.setState, time to setTimeOfDay (0 noon, 0.5 midnight). After
-- `settle` seconds (waterfx.lua reads the weather once a second and dresses a few objects a
-- frame) the view is shot. Each shot also notes the water objects that follow the weather, one
-- object's fields as the engine holds them, and the frames since the weather changed.
-- Shots: <user>/current/screenshots/<prefix>-<view>-<weather>.png. The first weather's state is
-- put back at the end.
local W = extensions.e2r_world
local dbg = W and W.dbg and W.dbg()
local native = dbg and dbg.native
if not (LAB and native and native.localPoint) then return 'set LAB and land first' end

local function ground(x, y)
  local d = castRayStatic(vec3(x, y, 6000), vec3(0, 0, -1), 12000)
  return d and d < 12000 and 6000 - d or 0
end
local function point(lat, lon, agl)
  local x, y = native.localPoint(lat, lon)
  if not x then return nil end
  return vec3(x, y, ground(x, y) + (tonumber(agl) or 2))
end
local function place(v)
  local cam = point(v[2], v[3], v[4])
  local look = cam and point(v[5], v[6], v[7])
  if not (cam and look) then return false end
  local q = quatFromDir(look - cam, vec3(0, 0, 1))
  -- (the game hands the camera back to the car some seconds after a landing: free it every time)
  pcall(function() if not commands.isFreeCamera() then commands.setFreeCamera() end end)
  core_camera.setPosRot(0, cam.x, cam.y, cam.z, q.x, q.y, q.z, q.w)
  if v[8] then pcall(function() core_camera.setFOV(0, v[8]) end) end
  return true
end
-- what the engine holds for the first tracked water object that still exists
local FIELDS = {'baseColor', 'overallWaveMagnitude', 'overallRippleMagnitude', 'overallFoamOpacity', 'specularPower',
  'reflectivity', 'waterFogDensity'}
local function sample()
  local fx = W.waterfx
  local out = {tracked = fx and #fx.objects or -1, queue = fx and #fx.queue or -1, key = fx and fx.nowKey or '?'}
  for _, o in ipairs(fx and fx.objects or {}) do
    local obj = scenetree.findObjectById(o.id)
    if obj then
      out.kind, out.class = o.kind, obj:getClassName()
      for _, f in ipairs(FIELDS) do out[f] = obj:getField(f, 0) end
      break
    end
  end
  return out
end

local views, weathers = LAB.views or {}, LAB.weathers or {{name = 'fair'}}
local settle, viewSettle, prefix = LAB.settle or 4, LAB.viewSettle or 30, LAB.prefix or 'water'
local vi, ki, phase, at, done = 1, 0, 'move', 0, {}
local okState, first = pcall(function() return core_environment.getState() end)
pcall(function() commands.setFreeCamera() end)
pcall(function() extensions.ui_visibility.setCef(false) end)

local timeSet = false
local function weather(k)
  if k.state then pcall(function() core_environment.setState(k.state) end) end
  if k.time then
    pcall(function() core_environment.setTimeOfDay({time = k.time}) end)
    timeSet = true
  elseif timeSet and okState and first then
    -- (a weather with no hour of its own is shot at the hour the session began with)
    pcall(function() core_environment.setTimeOfDay({time = first.time}) end)
    timeSet = false
  end
end

return P.task(function()
  local now = P.now()
  local v = views[vi]
  if not v then
    if okState and first then
      pcall(function() core_environment.setState({windSpeed = first.windSpeed, cloudCover = first.cloudCover, numOfDrops = first.numOfDrops}) end)
      pcall(function() core_environment.setTimeOfDay({time = first.time}) end)
    end
    pcall(function() extensions.ui_visibility.setCef(true) end)
    return {shots = done}
  end
  if phase == 'move' then
    if not place(v) then vi = vi + 1; return end
    phase, at = 'load', now
  elseif phase == 'load' then
    local st = dbg.S and dbg.S.status and dbg.S.status.stream or {}
    local quiet = (dbg.S and #(dbg.S.queue or {}) or 0) == 0 and (st.pending or 0) == 0
    if (quiet and now - at > 6) or now - at > viewSettle then
      place(v)   -- over the ground as it is now that the tiles are in
      phase, ki = 'weather', 0
    end
  elseif phase == 'weather' then
    ki = ki + 1
    local k = weathers[ki]
    if not k then vi, phase = vi + 1, 'move'; return end
    weather(k)
    phase, at = 'settle', now
  elseif phase == 'settle' then
    if now - at > settle then
      place(v)
      local name = prefix .. '-' .. v[1] .. '-' .. weathers[ki].name
      local note = sample()
      note.name, note.frames = name, P.frames(math.floor(settle * 30))
      createScreenshot2({filename = 'screenshots/' .. name, writeJPG = false, superSampling = 1})
      done[#done + 1] = note
      phase, at = 'shot', now
    end
  elseif phase == 'shot' then
    if now - at > 0.8 then phase = 'weather' end
  end
end)
