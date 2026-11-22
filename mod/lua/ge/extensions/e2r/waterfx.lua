-- The water's look by the weather (world.lua M.waterfx). A lake is glass in a calm, runs in
-- small waves under a wind and is rough and foaming in a storm; rain pocks it with fine ripples
-- and takes the sky's mirror off it; under cloud and at night it is darker and greyer.
--
-- look(kind, w) is the whole look of a water object as engine fields, from the kind of water
-- ('sea', 'lake', 'pond', 'river') and the weather w = {wind, rain, cloud, night, cold}, each
-- 0..1. weather() reads w from the game's environment. track() / step() keep the water
-- objects of the loaded tiles on the weather of the moment, a few a frame.
local M = {}
local max, min, floor = math.max, math.min, math.floor

-- A calm, clear day's water. color: the body's own (sRGB 0..255). wave: the swell's height by
-- the wind (calm, and what a storm adds). foam: its opacity (calm, storm). fog: the depth fog.
-- pond: a lake of 600 m at most, clear enough to see its shelf (the old lakeFog).
M.KINDS = {
  sea = {color = {18, 48, 52}, wave = {.05, .4}, ripple = .28, foam = {.5, .5}, foamDepth = {.5, .7},
    reflect = .28, fog = .3, gradient = 80, fresnel = 10, scale = {{10, 10}, {12, 16}, {50, 50}}, speed = {-.015, .015, .01}},
  lake = {color = {20, 64, 72}, wave = {.03, .2}, ripple = .28, foam = {.3, .6}, foamDepth = {.35, .5},
    reflect = .18, fog = .9, gradient = 12, fresnel = 10, scale = {{10, 10}, {12, 16}, {50, 50}}, speed = {-.015, .015, .01}},
  river = {color = {28, 52, 56}, wave = {.02, .07}, ripple = .35, foam = {.55, .4}, foamDepth = {.4, .3},
    reflect = .18, fog = 1.2, gradient = 6, fresnel = 10, scale = {{4, 12}, {12, 16}, {50, 50}}, speed = {.05, .015, .01}},
}
M.KINDS.pond = {}
for k, v in pairs(M.KINDS.lake) do M.KINDS.pond[k] = v end
-- (0.3 while a lake's bed fell 2.5 m at its shore and 0.9 drew that as a dark band. With a bed
-- that shelves, the shallows are clear by themselves, and a pond a metre deep needs its water
-- thick and its depth colours over 3 m, not 12, to be seen from above: tried in game at Kyiv.)
M.KINDS.pond.fog = 1.5
M.KINDS.pond.gradient = 3
-- the weather with no environment to read: a light breeze under a clear sky
M.FAIR = {wind = .3, rain = 0, cloud = .1, night = 0, cold = 0}

local function clamp01(v)
  v = tonumber(v) or 0
  return v < 0 and 0 or (v > 1 and 1 or v)
end
local function num(v) return string.format('%.4g', v) end

-- The body's colour under a sky: greyer under cloud and rain (the sky it mirrors is), darker
-- at night, a cold steel in frost.
function M.color(K, w)
  local grey = max(.55 * w.cloud, .7 * w.rain, .5 * w.cold)
  local dark = (1 - .22 * max(w.cloud, w.rain)) * (1 - .6 * w.night)
  local c = K.color
  local mean = (c[1] + c[2] + c[3]) / 3
  local out = {}
  for k = 1, 3 do
    local v = c[k] + (mean - c[k]) * grey
    if w.cold > 0 then v = v + ((k == 3 and 8 or -4)) * w.cold end
    out[k] = max(0, min(255, floor(v * dark + .5)))
  end
  return out
end

-- Every field of the look: {name, index, value} rows in a fixed order.
function M.look(kind, w)
  local K = M.KINDS[kind] or M.KINDS.lake
  w = w or M.FAIR
  local wind, rain, cloud = clamp01(w.wind), clamp01(w.rain), clamp01(w.cloud)
  w = {wind = wind, rain = rain, cloud = cloud, night = clamp01(w.night), cold = clamp01(w.cold)}
  local gust = wind ^ 1.5
  local rows = {}
  local function set(name, value, index) rows[#rows + 1] = {name, index or 0, type(value) == 'number' and num(value) or value} end
  local c = M.color(K, w)
  set('baseColor', string.format('%d %d %d 255', c[1], c[2], c[3]))
  set('fresnelBias', .1)
  set('fresnelPower', K.fresnel)
  -- a broken surface has no sharp sun on it
  set('specularPower', 200 * (1 - .6 * max(.6 * cloud, rain)) * (1 - .35 * gust))
  set('overallWaveMagnitude', K.wave[1] + K.wave[2] * gust + .03 * rain)
  set('overallRippleMagnitude', min(1.3, K.ripple * (.55 + 1.5 * wind) + .5 * rain))
  set('overallFoamOpacity', min(1, (K.foam[1] + K.foam[2] * gust) * (1 - .6 * w.cold) + .2 * rain))
  set('foamMaxDepth', K.foamDepth[1] + K.foamDepth[2] * gust)
  set('reflectivity', K.reflect * (1 - .4 * rain - .15 * cloud))
  set('viscosity', .001)
  -- rain and a storm stir the bed up
  set('waterFogDensity', K.fog * (1 + .6 * rain + .3 * gust))
  set('depthGradientMax', K.gradient)
  -- rain's ripples are fine and quick; the wind drives all three layers faster
  local fine, quick = 1 - .5 * rain, (1 + 2.2 * wind) * (1 + .8 * rain)
  for k = 1, 3 do
    set('rippleSpeed', K.speed[k] * quick, k - 1)
    set('rippleTexScale', num(K.scale[k][1] * fine) .. ' ' .. num(K.scale[k][2] * fine), k - 1)
    set('waveMagnitude', .2, k - 1)
    set('waveSpeed', .7 + 1.3 * wind, k - 1)
  end
  return rows
end

-- The weather from the game's environment (core_environment.getState()) and the pack's own
-- (rain or snow falling round the camera, a winter pack). wind: the clouds' 0..10 and the
-- ground wind's m/s. time: the game's 0..1 with 0 at noon.
function M.weather(state, pack)
  local w = {wind = M.FAIR.wind, rain = 0, cloud = M.FAIR.cloud, night = 0, cold = 0}
  state = type(state) == 'table' and state or {}
  local cloudWind = tonumber(state.windSpeed)
  local ground = state.groundWind
  local groundSpeed
  if type(ground) == 'number' then groundSpeed = ground
  elseif type(ground) == 'table' or type(ground) == 'userdata' then
    local ok, v = pcall(function()
      local x, y = tonumber(ground.x or ground[1]) or 0, tonumber(ground.y or ground[2]) or 0
      return math.sqrt(x * x + y * y)
    end)
    groundSpeed = ok and v or nil
  end
  if cloudWind or groundSpeed then w.wind = clamp01(max((cloudWind or 0) / 8, (groundSpeed or 0) / 18)) end
  if tonumber(state.cloudCover) then w.cloud = clamp01(state.cloudCover) end
  local drops = tonumber(state.numOfDrops) or 0
  local snow = type(pack) == 'table' and pack.snow
  if drops > 0 and not snow then w.rain = clamp01(.25 + drops / 4000) end
  if type(pack) == 'table' and pack.rain and not snow then w.rain = max(w.rain, .7) end
  -- rain falls from a covered sky and comes with wind
  if w.rain > 0 then w.cloud, w.wind = max(w.cloud, .5 + .4 * w.rain), max(w.wind, .25 + .3 * w.rain) end
  local time = tonumber(state.time)
  if time then
    -- 0 noon, 0.5 midnight: dark from a little after sunset to a little before sunrise
    local fromNoon = math.abs(((time + .5) % 1) - .5)
    w.night = clamp01((fromNoon - .24) / .06)
  end
  local t = tonumber(state.temperatureC)
  if snow or (t and t < -2) then w.cold = snow and 1 or clamp01((-2 - t) / 6) end
  return w
end

-- two weathers the eye cannot tell apart share a key
function M.key(w)
  return string.format('%d:%d:%d:%d:%d', floor(w.wind * 10 + .5), floor(w.rain * 5 + .5), floor(w.cloud * 5 + .5),
    floor(w.night * 5 + .5), floor(w.cold * 2 + .5))
end

-- --- the engine side -------------------------------------------------------------------------
M.objects, M.queue = {}, {}

function M.apply(obj, kind, w)
  for _, row in ipairs(M.look(kind, w)) do obj:setField(row[1], row[2], row[3]) end
end

-- A water object a tile is making: dress() gives it the look of the moment (before it is
-- registered, with its other fields), track() notes it for every change of the weather after
-- (once it is registered: an object has no id before that).
function M.dress(obj, kind)
  M.apply(obj, kind, M.now or M.FAIR)
end
function M.track(obj, kind)
  local ok, id = pcall(function() return obj:getID() end)
  if ok and tonumber(id) and tonumber(id) > 0 then M.objects[#M.objects + 1] = {id = id, kind = kind} end
end

function M.reset()
  M.objects, M.queue, M.now, M.nowKey, M.readAt = {}, {}, nil, nil, nil
end

-- Once a second the weather is read; when it has changed, every tracked object takes the new
-- look, `perFrame` of them a frame (a coast tile holds dozens of blocks). read: function() ->
-- state, pack. find: function(id) -> the object or nil (a tile's water goes with the tile).
function M.step(clock, read, find, perFrame)
  if not M.readAt or clock - M.readAt >= 1 then
    M.readAt = clock
    local state, pack = read()
    local w = M.weather(state, pack)
    local key = M.key(w)
    -- (the list is also weeded as it grows: a long drive leaves the water of unloaded tiles in it)
    if key ~= M.nowKey or #M.objects > (M.weedAt or 300) then
      local alive, queue = {}, {}
      for _, o in ipairs(M.objects) do
        if find(o.id) then alive[#alive + 1] = o; queue[#queue + 1] = o end
      end
      M.objects, M.weedAt = alive, #alive * 2 + 300
      if key ~= M.nowKey then M.now, M.nowKey, M.queue = w, key, queue end
    end
  end
  local done = 0
  while done < (perFrame or 6) and #M.queue > 0 do
    local o = table.remove(M.queue)
    local obj = find(o.id)
    if obj then
      M.apply(obj, o.kind, M.now)
      pcall(function() if obj.postApply then obj:postApply() end end)
      done = done + 1
    end
  end
  return done
end

return M
