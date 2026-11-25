-- The named points of the map sidecars (pois.tsv, build_map.py) as one spatial index for the world
-- map (worldmap.lua, docs/MAP.md "Карта світу"). A catalog is indexed a slice per frame in a
-- coroutine (SLICE seconds of os.clock), so the first opening of the map never stalls the game:
-- ffi arrays of lat, lon, category and the line's offset in the kept text, and a grid of GRID
-- degree cells whose points stand best first (pins.lua priority). Names and the OSM facts
-- (poi_tags.tsv, line for line with pois.tsv) are read from the text only for the points drawn or
-- hovered. Point i of a catalog is line i of its pois.tsv.
local M = {}
local okFfi, ffi = pcall(require, 'ffi')
local floor, find, sub, byte = math.floor, string.find, string.sub, string.byte
-- names in Latin letters for the English UI (translit.lua); as they are where it cannot load
local okTranslit, translit = pcall(require, 'ge/extensions/e2r/translit')
if not okTranslit or type(translit) ~= 'table' then translit = {latin = function(s) return s end} end

M.GRID = 0.05         -- degrees: a cell of the index
M.COARSE = 20         -- cells along a side of a coarse cell (1 degree), the walk's first step
M.SLICE = 0.003       -- s of indexing a frame
M.SCAN = 1500         -- points looked at in one cell for its best enabled ones
M.LEVELS = 9          -- pins.lua priorities 1-8; 9: a category the map has no look for
M.revision = 0        -- grows when an index is done or dropped (worldmap.lua drops its candidates)

local LON_CELLS, LON_COARSE = 8192, 512
local catalog, pins
local entries, job = {}, nil
local seen                        -- the catalog list the entries were made from
local CATS, CAT_ID, PRIORITY, PARENT = {}, {}, {}, {}
M.CATS, M.PRIORITY, M.PARENT = CATS, PRIORITY, PARENT

-- The finer kinds of a broad pin category, told by an OSM tag of poi_tags.tsv (old sidecars have
-- none: their points keep the broad one): name {Ukrainian, English}, and optionally its own look
-- (shape or text, pins.lua) and priority. A point becomes 'service_map/fuel' and so on.
M.SUB_KEYS = {amenity = true, tourism = true, historic = true, leisure = true, highway = true, shop = true}
M.SUB = {
  service_map = {
    fuel = {'АЗС', 'Fuel', shape = 'pump', priority = 3}, charging_station = {'Зарядна станція', 'EV charging', shape = 'bolt', priority = 4},
    car_wash = {'Автомийка', 'Car wash', shape = 'car'}, car_repair = {'СТО', 'Car repair', shape = 'wrench'},
    tyres = {'Шиномонтаж', 'Tyres', shape = 'wrench'}, pharmacy = {'Аптека', 'Pharmacy', shape = 'plus'},
    bank = {'Банк', 'Bank', text = '$'}, post_office = {'Пошта', 'Post office', shape = 'locker'},
    veterinary = {'Ветклініка', 'Vet', shape = 'plus'},
  },
  food = {
    cafe = {'Кафе', 'Cafe', shape = 'cup'}, restaurant = {'Ресторан', 'Restaurant'}, fast_food = {'Фастфуд', 'Fast food'},
    bar = {'Бар', 'Bar'}, pub = {'Паб', 'Pub'}, ice_cream = {'Морозиво', 'Ice cream'}, food_court = {'Фудкорт', 'Food court'},
  },
  sight = {
    museum = {'Музей', 'Museum', shape = 'columns', priority = 3}, attraction = {'Атракція', 'Attraction'},
    artwork = {'Мистецтво', 'Artwork'}, gallery = {'Галерея', 'Gallery'}, zoo = {'Зоопарк', 'Zoo', priority = 3},
    theme_park = {'Парк розваг', 'Theme park', priority = 3}, aquarium = {'Акваріум', 'Aquarium'},
    information = {'Інформація', 'Information', text = 'i'}, ruins = {'Руїни', 'Ruins', shape = 'castle'},
    archaeological_site = {'Археологія', 'Archaeological site'}, building = {'Історична будівля', 'Historic building', shape = 'house'},
  },
  leisure_map = {
    park = {'Парк', 'Park'}, garden = {'Сад', 'Garden'}, playground = {'Дитячий майданчик', 'Playground'},
    stadium = {'Стадіон', 'Stadium', priority = 4}, sports_centre = {'Спортцентр', 'Sports centre'},
    swimming_pool = {'Басейн', 'Swimming pool', shape = 'drop'}, fitness_centre = {'Фітнес', 'Fitness'},
    pitch = {'Спортивне поле', 'Pitch'}, cinema = {'Кінотеатр', 'Cinema'}, theatre = {'Театр', 'Theatre', shape = 'columns'},
    arts_centre = {'Центр мистецтв', 'Arts centre'}, nightclub = {'Нічний клуб', 'Nightclub'},
  },
  station_map = {bus_stop = {'Автобусна зупинка', 'Bus stop'}, bus_station = {'Автостанція', 'Bus station', priority = 4}},
}

function M.attach(catalogModule, pinsModule) catalog, pins = catalogModule, pinsModule end

local function array(kind, n)
  if okFfi then return ffi.new(kind .. '[?]', n + 1) end
  return {}
end

-- a category's small number (one byte in the index); a finer kind names its broad parent
function M.catId(name, parent, kind)
  local id = CAT_ID[name]
  if not id then
    id = #CATS + 1
    CATS[id], CAT_ID[name], PARENT[id] = name, id, parent or name
    local s = pins and pins.STYLE[parent or name]
    local sub = parent and M.SUB[parent] and M.SUB[parent][kind]
    PRIORITY[id] = sub and sub.priority or s and s.priority or M.LEVELS
  end
  return id
end

-- the finer kind of point i (its poi_tags.tsv line from `at`), else the broad id
local function finer(tags, at, broad, name)
  local subs = M.SUB[name]
  if not subs or not tags then return broad end
  local stop = (find(tags, '\n', at, true) or #tags + 1) - 1
  while at <= stop do
    local tab = find(tags, '\t', at, true)
    local last = (tab and tab <= stop) and tab - 1 or stop
    local eq = find(tags, '=', at, true)
    if eq and eq < last and M.SUB_KEYS[sub(tags, at, eq - 1)] then
      local value = sub(tags, eq + 1, last)
      if subs[value] then return M.catId(name .. '/' .. value, name, value) end
    end
    at = last + 2
  end
  return broad
end

-- the decimal in text[a..b] ('%.6f' from build_map.py; a sign, digits and one point), nil if not
local function number(text, a, b)
  if b < a then return nil end
  local sign, v, scale, i = 1, 0, nil, a
  if byte(text, i) == 45 then sign, i = -1, i + 1 end
  while i <= b do
    local c = byte(text, i)
    if c == 46 and not scale then scale = 1
    elseif c >= 48 and c <= 57 then
      v = v * 10 + (c - 48)
      if scale then scale = scale * 10 end
    else return nil end
    i = i + 1
  end
  return sign * v / (scale or 1)
end
M.number = number

local function cellOf(lat, lon)
  return floor((lat + 90) / M.GRID) * LON_CELLS + floor((lon + 180) / M.GRID)
end

-- one catalog's index; pause() yields when the frame's slice is spent
local function build(e, pause)
  local text = catalog.text(e.c, 'pois.tsv')
  if not text then e.ready = true; return end
  local len, n, at = #text, 0, 1
  while at <= len do
    local nl = find(text, '\n', at, true) or len + 1
    n, at = n + 1, nl + 1
    if n % 8192 == 0 then pause() end
  end
  -- the OSM facts, line for line; a file that does not match line for line is not used
  local tags, tagOff = catalog.text(e.c, 'poi_tags.tsv') or nil, nil
  if tags then
    local tlen, line = #tags, 0
    tagOff = array('uint32_t', n)
    at = 1
    while at <= tlen and line < n do
      line = line + 1
      tagOff[line] = at
      at = (find(tags, '\n', at, true) or tlen) + 1
      if line % 8192 == 0 then pause() end
    end
    if line ~= n or at <= tlen then tags, tagOff = nil, nil end
  end
  local lat, lon, cat, off, key = array('float', n), array('float', n), array('uint8_t', n), array('uint32_t', n), array('uint32_t', n)
  local counts, levelCount, cells = {}, {}, {}
  for l = 1, M.LEVELS do levelCount[l] = 0 end
  local w, s, east, north = 180, 90, -180, -90
  at = 1
  for i = 1, n do
    local nl = find(text, '\n', at, true) or len + 1
    local t1 = find(text, '\t', at, true)
    local t2 = t1 and t1 < nl and find(text, '\t', t1 + 1, true)
    local t3 = t2 and t2 < nl and find(text, '\t', t2 + 1, true)
    local t4 = t3 and t3 < nl and find(text, '\t', t3 + 1, true)
    off[i], cat[i] = at, 0
    if t4 and t4 < nl then
      local a, o = number(text, t1 + 1, t2 - 1), number(text, t2 + 1, t3 - 1)
      if a and o and a >= -90 and a <= 90 and o >= -180 and o <= 180 then
        local name = sub(text, t3 + 1, t4 - 1)
        local id = M.catId(name)
        if tags then id = finer(tags, tagOff[i], id, name) end
        if id <= 255 then
          lat[i], lon[i], cat[i] = a, o, id
          local k = cellOf(a, o)
          key[i] = k
          cells[k] = (cells[k] or 0) + 1
          counts[id] = (counts[id] or 0) + 1
          local level = PRIORITY[id]
          levelCount[level] = levelCount[level] + 1
          if a < s then s = a end
          if a > north then north = a end
          if o < w then w = o end
          if o > east then east = o end
        end
      end
    end
    at = nl + 1
    if i % 2048 == 0 then pause() end
  end
  -- the points by priority, then into their cells in that order: each cell best first
  local levelAt, byLevel = {}, array('uint32_t', n)
  local total = 1
  for l = 1, M.LEVELS do levelAt[l], total = total, total + levelCount[l] end
  for i = 1, n do
    local id = cat[i]
    if id > 0 then
      local l = PRIORITY[id]
      byLevel[levelAt[l]], levelAt[l] = i, levelAt[l] + 1
    end
    if i % 8192 == 0 then pause() end
  end
  local first, next, coarse, used = {}, {}, {}, 1
  for k, c in pairs(cells) do
    first[k], next[k], used = used, used, used + c
    local q = floor(floor(k / LON_CELLS) / M.COARSE) * LON_COARSE + floor((k % LON_CELLS) / M.COARSE)
    local list = coarse[q]
    if not list then list = {}; coarse[q] = list end
    list[#list + 1] = k
  end
  local order = array('uint32_t', used)
  for t = 1, used - 1 do
    local i = byLevel[t]
    local k = key[i]
    order[next[k]], next[k] = i, next[k] + 1
    if t % 8192 == 0 then pause() end
  end
  e.n, e.lat, e.lon, e.cat, e.off, e.text = n, lat, lon, cat, off, text
  e.first, e.count, e.coarse, e.order, e.counts = first, cells, coarse, order, counts
  e.box = {w = w, s = s, e = east, n = north}
  e.points = used - 1
  e.names = {}
  e.tags, e.tagOff = tags, tagOff
  e.ready = true
end

local function sync()
  local list = catalog and catalog.catalogs() or {}
  if list == seen and #entries == #list then return end
  local old, kept = {}, false
  for _, e in ipairs(entries) do old[e.c] = e end
  entries, seen = {}, list
  for _, c in ipairs(list) do
    entries[#entries + 1] = old[c] or {c = c, title = c.title}
    if job and job.e.c == c then kept = true end
  end
  -- a catalog still listed keeps its half-built index (catalogs arrive one a frame)
  if not kept then job = nil end
  M.revision = M.revision + 1
end

-- index a slice: the next catalog not yet done (call once a frame while the map is open)
function M.step()
  if not catalog then return end
  sync()
  if not job then
    for _, e in ipairs(entries) do
      if not e.ready then
        job = {e = e, co = coroutine.create(function(start)
          local clock = os.clock
          local function pause()
            if clock() - start > M.SLICE then start = coroutine.yield() end
          end
          build(e, pause)
        end)}
        break
      end
    end
  end
  if job then
    local ok, err = coroutine.resume(job.co, os.clock())
    if not ok then
      job.e.ready, job.e.error = true, tostring(err)
      if log then log('W', 'e2r.poiindex', 'indexing ' .. tostring(job.e.title) .. ' failed: ' .. tostring(err)) end
    end
    if coroutine.status(job.co) == 'dead' then
      job = nil
      M.revision = M.revision + 1
    end
  end
end

-- {done, total catalogs, points indexed, busy title}
local stats = {}
function M.stats()
  local done, points = 0, 0
  for _, e in ipairs(entries) do
    if e.ready then done = done + 1; points = points + (e.points or 0) end
  end
  stats.done, stats.total, stats.points, stats.busy = done, #entries, points, job and job.e.title or nil
  return stats
end

-- points of each category over every catalog (worldmap.lua's filter list)
function M.counts(out)
  for k in pairs(out) do out[k] = nil end
  for _, e in ipairs(entries) do
    if e.ready and e.counts then
      for id, c in pairs(e.counts) do out[CATS[id]] = (out[CATS[id]] or 0) + c end
    end
  end
  return out
end

-- Every enabled point of the box, or the best `per` of each grid cell: add(e, i, level) for each.
-- enabled: category number -> true; pause (optional) is called every few hundred cells, so a
-- caller in a coroutine can spread a wide box over frames (worldmap.lua).
function M.collect(w, s, e, n, per, enabled, add, pause, pack)
  local G, C = M.GRID, M.COARSE
  local walked = 0
  w, e = math.max(-180, w), math.min(180, e)
  local cy0, cy1 = floor((s + 90) / G), floor((n + 90) / G)
  local cx0, cx1 = floor((w + 180) / G), floor((e + 180) / G)
  local qy0, qy1, qx0, qx1 = floor(cy0 / C), floor(cy1 / C), floor(cx0 / C), floor(cx1 / C)
  for _, en in ipairs(entries) do
    local b = (not pack or en.c.id == pack) and en.ready and en.box
    if b and b.w <= e and b.e >= w and b.s <= n and b.n >= s then
      local coarse, first, count, order, cat = en.coarse, en.first, en.count, en.order, en.cat
      for qy = qy0, qy1 do
        for qx = qx0, qx1 do
          local list = coarse[qy * LON_COARSE + qx]
          if list then
            for j = 1, #list do
              local k = list[j]
              local cy, cx = floor(k / LON_CELLS), k % LON_CELLS
              walked = walked + 1
              if pause and walked % 256 == 0 then pause() end
              if cy >= cy0 and cy <= cy1 and cx >= cx0 and cx <= cx1 then
                local f, taken = first[k], 0
                local last = f + math.min(count[k], M.SCAN) - 1
                for t = f, last do
                  local i = order[t]
                  local id = cat[i]
                  if enabled[id] then
                    add(en, i, PRIORITY[id])
                    taken = taken + 1
                    if taken >= per then break end
                  end
                end
              end
            end
          end
        end
      end
    end
  end
end

-- the fields of point i's line: name, English name (text positions, no strings made)
local function fields(text, at)
  local len = #text
  local nl = find(text, '\n', at, true) or len + 1
  local t = at
  for _ = 1, 4 do
    t = find(text, '\t', t, true)
    if not t or t > nl then return nil end
    t = t + 1
  end
  local t5 = find(text, '\t', t, true)
  if t5 and t5 < nl then return t, t5 - 1, t5 + 1, nl - 1 end
  return t, nl - 1, nl, nl - 1
end

-- point i's name: English when lang is 'en' and it has one, else in Latin letters for English
-- (translit.lua); kept for the next frames
function M.name(e, i, lang)
  local names = e.names
  local hit = names[i]
  if hit then return lang == 'en' and hit[2] or hit[1] end
  local a, b, c, d = fields(e.text, e.off[i])
  if not a then return '' end
  local name = sub(e.text, a, b)
  local en = translit.latin(d >= c and sub(e.text, c, d) or name)
  e.nameCount = (e.nameCount or 0) + 1
  if e.nameCount > 4000 then e.names, e.nameCount = {}, 1; names = e.names end
  names[i] = {name, en}
  return lang == 'en' and en or name
end

function M.category(e, i) return CATS[e.cat[i]] end
function M.position(e, i) return e.lat[i], e.lon[i] end

-- point i's OSM facts as {{key, value}, ...} in the file's order, or nil without poi_tags.tsv
function M.details(e, i)
  if not e.tags then return nil end
  local text, at = e.tags, e.tagOff[i]
  local stop = (find(text, '\n', at, true) or #text + 1) - 1
  local out = {}
  while at <= stop do
    local tab = find(text, '\t', at, true)
    local last = (tab and tab <= stop) and tab - 1 or stop
    local eq = find(text, '=', at, true)
    if eq and eq < last then out[#out + 1] = {sub(text, at, eq - 1), sub(text, eq + 1, last)} end
    at = last + 2
  end
  return out
end

-- the indexed point at lat, lon of category cat (a search hit), or nil
function M.find(lat, lon, cat, pack)
  local k, id = cellOf(lat, lon), CAT_ID[cat]
  for _, e in ipairs(entries) do
    local f = (not pack or e.c.id == pack) and e.ready and e.first and e.first[k]
    if f then
      for t = f, f + e.count[k] - 1 do
        local i = e.order[t]
        if (not id or e.cat[i] == id or PARENT[e.cat[i]] == cat) and math.abs(e.lat[i] - lat) < 2e-5 and math.abs(e.lon[i] - lon) < 2e-5 then return e, i end
      end
    end
  end
  return nil
end

function M.entries() return entries end
function M.reset() entries, seen, job = {}, nil, nil; M.revision = M.revision + 1 end

return M
