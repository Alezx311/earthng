-- OSM map sidecars belong to country and section ZIPs, alongside their driving data.
local M = {revision = 0}
-- (its road tiles and overview images are read and drawn by maproads.lua)
local signature, pending, catalogs = '', {}, {}
local function read(path)
  local ok, value = pcall(jsonReadFile, path)
  return ok and type(value) == 'table' and value or nil
end

-- an index.json the runtime reads (version 1 with its tiles), else nil
function M.usable(index)
  return type(index) == 'table' and index.version == 1 and type(index.tiles) == 'table' and index or nil
end
function M.step(countries)
  local ids, current = {}, {}
  for _, c in ipairs(countries or {}) do
    if c.available then
      local function add(root, title)
        ids[#ids + 1] = root .. ':' .. tostring(c.version) .. ':' .. title
        current[#current + 1] = {id=c.id, title=title, root=root}
      end
      local root = '/earthng/countries/' .. c.id .. '/'
      add(root .. 'map/', c.title)
      for _, r in ipairs(c.regions or {}) do
        if r.section then add(root .. 'sections/' .. r.id .. '/map/', r.title or c.title) end
      end
    end
  end
  table.sort(ids)
  local key = table.concat(ids, '|')
  if key ~= signature then
    signature, pending, catalogs = key, current, {}
    M.revision = M.revision + 1
  end
  -- At most one country's index/settlements per frame; no geometry decoding or network.
  local c = table.remove(pending, 1)
  if not c then return end
  local root = c.root
  local index = FS:fileExists(root .. 'index.json') and M.usable(read(root .. 'index.json')) or nil
  if not index then return end
  local places = read(root .. 'places.json') or {}
  for _, p in ipairs(places) do
    p.pack = c.id
    p.context = c.title .. (p[10] and p[10] ~= '' and (' · ' .. p[10]) or '')
  end
  catalogs[#catalogs + 1] = {id = c.id, root = root, index = index, places = places, title = c.title}
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

function M.searchPois(needle, limit, near, pack, accepts)
  local hits = {}
  if #needle < 3 then return hits end
  for _, c in ipairs(catalogs) do
    local text, at = (not pack or c.id == pack) and M.text(c, 'pois.tsv'), 1
    local matched = 0
    while text and matched < M.POI_SCAN do
      local i = text:find(needle, at, true)
      if not i then break end
      local start = i
      while start > 1 and text:byte(start - 1) ~= 10 do start = start - 1 end
      local stop = text:find('\n', i, true) or #text + 1
      local key, lat, lon, cat, name, en = text:sub(start, stop - 1):match('^([^\t]*)\t([^\t]*)\t([^\t]*)\t([^\t]*)\t([^\t]*)\t?([^\t]*)$')
      local last = i + #needle - 1
      if key and last <= start + #key - 1 and (not accepts or accepts(cat)) then
        -- the key holds every name of the point (' | ' between): exact or prefix of any one of them
        local head = i == start or text:sub(i - 3, i - 1) == ' | '
        local whole = head and (last == start + #key - 1 or text:sub(last + 1, last + 3) == ' | ')
        hits[#hits + 1] = {name = name, en = en ~= '' and en or nil, lat = tonumber(lat), lon = tonumber(lon), cat = cat,
          context = c.title, pack = c.id, score = whole and 0 or head and 1 or 2}
        matched = matched + 1
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
    if a.lon ~= b.lon then return a.lon < b.lon end
    return a.context < b.context
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

function M.packPlaces(id)
  local result = {}
  for _, c in ipairs(catalogs) do
    if c.id == id then
      for _, p in ipairs(c.places) do result[#result + 1] = p end
    end
  end
  return result
end

return M
