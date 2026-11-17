-- Optional OSM map sidecars, independent of generated driving geometry. A refreshed planet
-- can supply maps/<country>/ for old country ZIPs; new country ZIPs carry their own map/.
local M = {revision = 0}
local signature, pending, catalogs, cache, clock = '', {}, {}, {}, 0
local function read(path)
  local ok, value = pcall(jsonReadFile, path)
  return ok and type(value) == 'table' and value or nil
end
local function overlaps(a, b)
  return a[1] <= b.e and a[3] >= b.w and a[2] <= b.n and a[4] >= b.s
end

function M.step(countries)
  local ids, current = {}, {}
  for _, c in ipairs(countries or {}) do
    if c.available then
      ids[#ids + 1] = c.id .. ':' .. tostring(c.version) .. ':' .. c.title
      current[#current + 1] = c
    end
  end
  table.sort(ids)
  local key = table.concat(ids, '|')
  if key ~= signature then
    signature, pending, catalogs, cache = key, current, {}, {}
    M.revision = M.revision + 1
  end
  -- At most one country's index/settlements per frame; no geometry decoding or network.
  local c = table.remove(pending, 1)
  if not c then return end
  local root = '/earthng/countries/' .. c.id .. '/map/'
  if not FS:fileExists(root .. 'index.json') then root = '/earthng/planet/maps/' .. c.id .. '/' end
  if not FS:fileExists(root .. 'index.json') then return end
  local index = read(root .. 'index.json')
  if not index or index.version ~= 1 or type(index.tiles) ~= 'table' then return end
  local places = read(root .. 'places.json') or {}
  for _, p in ipairs(places) do p.context = c.title .. (p[10] and p[10] ~= '' and (' · ' .. p[10]) or '') end
  catalogs[#catalogs + 1] = {root = root, index = index, places = places, title = c.title}
  M.revision = M.revision + 1
end

-- The named points whose names hold `needle` (planetMap's normal form, 3 letters or more): the
-- sidecar's pois.tsv (build_map.py: key, lat, lon, category, name, English name, one line each)
-- read on a country's first search and kept as one string, so the collector has one object to
-- walk, not a table per point. Exact names first, then names that start with it, then the rest;
-- within each, the nearest to `near` ({lat, lon}: the map's centre) first, so "Хрещатик" seen
-- over Kyiv is the station there, not a spring of the same name across the country.
M.POI_SCAN = 4000
-- a sidecar's text file read once and kept on its catalog (false: none): pois.tsv as c.pois,
-- poi_tags.tsv (build_map.py GENERATION 3, the OSM facts of each point, line for line) as c.tags
local FIELD = {['pois.tsv'] = 'pois', ['poi_tags.tsv'] = 'tags'}
function M.text(c, name)
  local field = FIELD[name]
  if c[field] == nil then
    c[field] = false
    if FS:fileExists(c.root .. name) then
      local ok, text = pcall(readFile, c.root .. name)
      c[field] = ok and type(text) == 'string' and text or false
    end
  end
  return c[field]
end
-- the loaded sidecars, {root, title, index, places}, for the world map's point index (poiindex.lua)
function M.catalogs() return catalogs end

function M.searchPois(needle, limit, near)
  local hits = {}
  if #needle < 3 then return hits end
  for _, c in ipairs(catalogs) do
    local text, at = M.text(c, 'pois.tsv'), 1
    while text and #hits < M.POI_SCAN do
      local i = text:find(needle, at, true)
      if not i then break end
      local start = i
      while start > 1 and text:byte(start - 1) ~= 10 do start = start - 1 end
      local stop = text:find('\n', i, true) or #text + 1
      local key, lat, lon, cat, name, en = text:sub(start, stop - 1):match('^([^\t]*)\t([^\t]*)\t([^\t]*)\t([^\t]*)\t([^\t]*)\t?([^\t]*)$')
      local last = i + #needle - 1
      if key and last <= start + #key - 1 then
        -- the key holds every name of the point (' | ' between): exact or prefix of any one of them
        local head = i == start or text:sub(i - 3, i - 1) == ' | '
        local whole = head and (last == start + #key - 1 or text:sub(last + 1, last + 3) == ' | ')
        hits[#hits + 1] = {name = name, en = en ~= '' and en or nil, lat = tonumber(lat), lon = tonumber(lon), cat = cat,
          context = c.title, score = whole and 0 or head and 1 or 2}
      end
      at = stop + 1
    end
  end
  if near and near.lat and near.lon then
    local k = math.cos(math.rad(near.lat)) ^ 2
    for _, h in ipairs(hits) do h.far = (h.lat - near.lat) ^ 2 + k * (h.lon - near.lon) ^ 2 end
  end
  table.sort(hits, function(a, b)
    if a.score ~= b.score then return a.score < b.score end
    if a.far and a.far ~= b.far then return a.far < b.far end
    if a.name ~= b.name then return a.name < b.name end
    if a.lat ~= b.lat then return a.lat < b.lat end
    return a.lon < b.lon
  end)
  local out = {}
  for k = 1, math.min(limit or 20, #hits) do out[k] = hits[k] end
  return out
end

function M.places()
  local result = {}
  for _, c in ipairs(catalogs) do
    for _, p in ipairs(c.places) do result[#result + 1] = p end
  end
  return result
end

function M.roads(view, zoom)
  local level = zoom >= 11 and 11 or zoom >= 9 and 9 or 6
  local out, wanted = {}, {}
  clock = clock + 1
  for _, c in ipairs(catalogs) do
    for _, t in pairs(c.index.tiles) do
      if not (c.index.raster and zoom <= 10) and t.zoom == level and overlaps(t.box, view) and type(t.file) == 'string' and t.file:match('^[%d_%-]+%.json$') then
        wanted[#wanted + 1] = c.root .. t.file
      end
    end
  end
  table.sort(wanted) -- stable load order instead of table hash order
  local loads = 0
  for _, path in ipairs(wanted) do
    local entry = cache[path]
    if not entry and loads < 2 then
      entry = {lines = read(path) or {}}
      cache[path], loads = entry, loads + 1
    end
    if entry then entry.used = clock; out[#out + 1] = entry.lines end
  end
  local size, oldest, used = 0, nil, math.huge
  for path, entry in pairs(cache) do
    size = size + 1
    if entry.used < used then oldest, used = path, entry.used end
  end
  if size > 96 then
    local entries = {}
    for path, entry in pairs(cache) do entries[#entries+1] = {path, entry.used} end
    table.sort(entries, function(a,b) return a[2] < b[2] end)
    for k=1,size-96 do cache[entries[k][1]] = nil end
  end
  return out
end

function M.raster(view, zoom)
  if zoom < 5 or zoom > 10 then return {} end
  local n, wanted = 2^zoom, {}
  local function ty(lat)
    local r = math.rad(math.max(-85.0511, math.min(85.0511, lat)))
    return math.floor((1 - math.log(math.tan(r) + 1/math.cos(r))/math.pi)/2*n)
  end
  for _, c in ipairs(catalogs) do
    if c.index.raster then
      for x = math.floor((view.w+180)/360*n), math.floor((view.e+180)/360*n) do
        for y = math.max(0,ty(view.n)), math.min(n-1,ty(view.s)) do
          local file = c.index.raster[zoom .. '/' .. x .. '/' .. y]
          if file and file:match('^r[%d_%-]+%.png$') then
            wanted[#wanted+1] = {path=c.root .. file, lon=x/n*360-180, lat=math.deg(math.atan(math.sinh(math.pi*(1-2*y/n))))}
          end
        end
      end
    end
  end
  return wanted
end

return M
