-- The climate of a place for the generator: which ground and which plants an untagged hill
-- gets in a desert, a steppe, the tropics, a Mediterranean scrub, a boreal forest or the
-- tundra, and where the tree line and the snow line run. Köppen-Geiger 1991-2020 (Beck et
-- al. 2023, CC BY 4.0) at one arc minute ships in the planet (earthng/build_climate.py); the
-- belts above the tree line come from the pack's DEM in the generator.
-- These are artistic rules on a measured climate map, not a measured map of vegetation.
local M = {}
M.ROOT = '/earthng/planet/climate/'
local floor, abs, max, min = math.floor, math.abs, math.max, math.min

local blocks = {}
local function block(col, row)
  local key = col * 100 + row
  local b = blocks[key]
  if b ~= nil then return b end
  b = false
  local path = M.ROOT .. col .. '_' .. row .. '.bin'
  local ok, data = pcall(function()
    if FS and not FS:fileExists(path) then return nil end
    local f = io.open(path, 'rb')
    if not f then return nil end
    local d = f:read('*a')
    f:close()
    return d
  end)
  if ok and type(data) == 'string' and #data >= 8 and data:sub(1, 4) == 'EKG1' then
    local w, h = data:byte(5) + data:byte(6) * 256, data:byte(7) + data:byte(8) * 256
    if w > 0 and h > 0 and #data == 8 + w * h then b = {w = w, h = h, data = data} end
  end
  blocks[key] = b
  return b
end

-- Is the planet's climate grid there at all (an older planet, or a test outside the game)?
function M.available()
  if M.present == nil then
    M.present = false
    for _, probe in ipairs({{21, 13}, {6, 12}, {30, 8}, {24, 14}}) do   -- Kyiv, California, Zanzibar, Nepal
      if block(probe[1], probe[2]) then M.present = true; break end
    end
  end
  return M.present
end

-- Köppen class 1..30 at a point (legend of the source), 0 for the sea or no data.
function M.class(lon, lat)
  lon = (lon + 180) % 360 - 180
  lat = max(-89.9999, min(89.9999, lat))
  local col, row = floor((lon + 180) / 10), floor((lat + 90) / 10)
  local b = block(col, row)
  if not b then return 0 end
  local x = min(b.w - 1, floor((lon + 180 - col * 10) / 10 * b.w))
  local y = min(b.h - 1, floor((lat + 90 - row * 10) / 10 * b.h))
  return b.data:byte(9 + y * b.w + x)
end

local HMOD = 2147483647
local function hash(a, b, seed)
  local h = (seed * 1000003 + a) % HMOD
  h = (h * 1000003 + b) % HMOD
  h = (h * 48271 + 11) % HMOD
  return (h * 48271 + 7) % HMOD % 1000 / 1000
end
-- Smooth 0..1 value noise over degrees, with `size` degree features.
local function noise(lon, lat, size, seed)
  local fx, fy = lon / size, lat / size
  local gx, gy = floor(fx), floor(fy)
  local tx, ty = fx - gx, fy - gy
  tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
  local a = hash(gx, gy, seed) + (hash(gx + 1, gy, seed) - hash(gx, gy, seed)) * tx
  local b = hash(gx, gy + 1, seed) + (hash(gx + 1, gy + 1, seed) - hash(gx, gy + 1, seed)) * tx
  return a + (b - a) * ty
end
M.noise = noise

-- A climate border drawn as the grid has it is a staircase of 1.85 km squares: the class is
-- read about a kilometre and a half off the point, the offset a smooth noise.
local JITTER, JITTER_SIZE = .016, .04
function M.dithered(lon, lat)
  local dx = (noise(lon, lat, JITTER_SIZE, 41) - .5) * 2 * JITTER
  local dy = (noise(lon, lat, JITTER_SIZE, 43) - .5) * 2 * JITTER
  return M.class(lon + dx, lat + dy)
end

-- The tundra and ice classes of mid-latitude mountains (the Sierra Nevada, the Alps, the
-- Himalaya) are the altitude belts the DEM draws anyway: such a summit takes the climate of
-- the slopes round it, its most common other class within ~50 km.
-- A shore or an island the 1.85 km grid counts as sea (class 0) takes the climate round it the
-- same way: Zanzibar's beaches fell back to the temperate rules and grew oaks.
local RINGS = {.04, .1, .2, .35, .5}
local regionalCache = {}
function M.regional(lon, lat, class)
  class = class or M.dithered(lon, lat)
  if class ~= 0 and ((class ~= 29 and class ~= 30) or abs(lat) >= 60) then return class end
  local key = floor(lon * 20) * 100000 + floor(lat * 20)
  local known = regionalCache[key]
  if known then return known end
  local count, best, bestN = {}, class, 0
  local polar = abs(lat) >= 60          -- a polar shore takes the tundra or ice round it
  for _, r in ipairs(RINGS) do
    for k = 0, 15 do
      local a = k * math.pi / 8
      local c = M.class(lon + r * math.cos(a) / max(.2, math.cos(math.rad(lat))), lat + r * math.sin(a))
      if c ~= 0 and (polar or (c ~= 29 and c ~= 30)) then
        count[c] = (count[c] or 0) + 1
        if count[c] > bestN or (count[c] == bestN and c < best) then best, bestN = c, count[c] end
      end
    end
    if bestN >= 6 then break end
  end
  regionalCache[key] = best
  return best
end

local GROUP = {'rainforest', 'rainforest', 'savanna', 'desert', 'desert', 'steppe', 'steppe',
  'mediterranean', 'mediterranean', 'mediterranean',
  'temperate', 'temperate', 'temperate', 'temperate', 'temperate', 'temperate',
  'temperate', 'temperate', 'boreal', 'boreal', 'temperate', 'temperate', 'boreal', 'boreal',
  'temperate', 'temperate', 'boreal', 'boreal', 'tundra', 'ice'}
M.GROUP = GROUP
-- Tree line and snow line (the lowest permanent snow) by latitude, metres above the sea: the
-- Himalaya's 4000 / 5300 m, the Sierra Nevada's 3350 / 4400, the Pyrenees' 2400, the Alps'
-- 1800-2000 / 3000, the Făgăraș' 1950 and the Carpathians' 1700 (in game a hotel lawn at Bâlea
-- Lac, 2034 m, stood among oaks under a 2230 m line), the Tatras' 1600, Scandinavia's 800 / 1500.
local LATS = {0, 15, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90}
local TREE = {3800, 3900, 4000, 3900, 3500, 3000, 2050, 1500, 1000, 800, 500, 200, 0, 0, 0}
local SNOW = {4900, 5000, 5300, 5300, 4700, 3900, 3100, 2600, 2000, 1500, 1100, 700, 400, 200, 0}
local function byLat(table_, lat)
  lat = abs(lat)
  for k = 2, #LATS do
    if lat <= LATS[k] then
      local t = (lat - LATS[k - 1]) / (LATS[k] - LATS[k - 1])
      return table_[k - 1] + (table_[k] - table_[k - 1]) * t
    end
  end
  return table_[#table_]
end

-- The climate of the place: one shared table per class and tenth of a degree of latitude.
local places = {}
function M.place(lon, lat)
  local raw = M.dithered(lon, lat)
  if raw == 0 then raw = M.class(lon, lat) end
  local class = M.regional(lon, lat, raw)
  local west = lon < -30
  -- The grid's own tundra on a mid-latitude ridge measures what the latitude table guesses: the
  -- warmest month under 10 °C, the tree line's climate. Such a ridge (the Carpathians' polonyny,
  -- the Făgăraș, the Cairngorms) has its tree line 400 m under the table's.
  local ridge = (raw == 29 or raw == 30) and class ~= raw
  local key = class * 4000 + floor((lat + 90) * 10) * 2 + (west and 1 or 0) + (ridge and 1e7 or 0)
  local p = places[key]
  if p then return p end
  local group = GROUP[class] or 'temperate'
  local treeline, snowline = byLat(TREE, lat), byLat(SNOW, lat)
  if group == 'desert' or group == 'steppe' then treeline, snowline = treeline + 200, snowline + 500 end
  if class == 15 or class == 16 then treeline, snowline = treeline - 300, snowline - 300 end   -- Cfb, Cfc: oceanic
  if ridge then treeline = treeline - 400 end
  local alat = abs(lat)
  -- town palms: the tropics, hot deserts and steppes, Mediterranean coasts, the humid subtropics
  local palms = group == 'rainforest' or group == 'savanna'
    or ((class == 4 or class == 6) and alat < 38) or (class == 8 and alat < 44) or (class == 9 and alat < 40)
    or ((class == 11 or class == 14) and alat < 32)
  p = {class = class, group = group, raw = raw, west = west, south = lat < 0,
    hot = class == 4 or class == 6 or class <= 3,
    australia = lon > 112 and lon < 155 and lat < -10 and lat > -45,
    treeline = treeline, snowline = max(treeline + 300, snowline), palms = palms,
    arid = group == 'desert' or group == 'steppe'}
  places[key] = p
  return p
end

-- The place at a point of a region frame: geo is the pack's affine (x0, y0, lon0, lat0,
-- dlon/dx, dlon/dy, dlat/dx, dlat/dy), good to ~200 m over a region, plenty for climate.
function M.lonlat(geo, x, y)
  local dx, dy = x - geo[1], y - geo[2]
  return geo[3] + geo[5] * dx + geo[6] * dy, geo[4] + geo[7] * dx + geo[8] * dy
end
function M.at(geo, x, y)
  return M.place(M.lonlat(geo, x, y))
end

-- Is a point far inland: land on the climate grid all round it, ~3 km out? Ground under the sea
-- level there is a depression (Death Valley, the Dead Sea's shore, an inland polder), not sea.
-- Near any coast the answer is no, so the sea plane stays where the sea is.
function M.inland(geo, x, y)
  local lon, lat = M.lonlat(geo, x, y)
  local r = .03
  local rx = r / max(.2, math.cos(math.rad(lat)))
  for a = -1, 1 do
    for b = -1, 1 do
      if M.class(lon + a * rx, lat + b * r) == 0 then return false end
    end
  end
  return true
end

return M
