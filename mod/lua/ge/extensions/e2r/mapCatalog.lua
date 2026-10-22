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
  catalogs[#catalogs + 1] = {root = root, index = index, places = places}
  M.revision = M.revision + 1
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
