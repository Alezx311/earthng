-- The world map on M (docs/MAP.md "Карта світу"): the whole planet on one screen with the points
-- of interest of the installed map sidecars. A side panel holds the search, the layers, the filters
-- by group and category with their counts, and the chosen point's card; the map (world.lua
-- drawMap, view.world) shows the enabled points (poiindex.lua): dots of their group's colour when
-- far, icons closer, names close up, and the OSM facts (poi_tags.tsv) of the point under the
-- cursor. A click only picks a point or a place; its card offers the route there and a landing,
-- so a stray click never moves the car. The game pauses while the map is open (a layer switch).
--
-- Every frame: the markers are collected only when the zoom or the filters change or the view
-- leaves the box they were collected for (the view and PAD of it again on each side), thinned
-- to one a square of a grid fixed to the world (a drag never swaps the point of a square) and kept
-- best first with their screen place; a frame only shifts them by the drag and draws at most
-- MAX_DOTS or MAX_ICONS. Markers go into reused arrays, the dots share one reused ImVec2, labels
-- and cards are cached by point.
local M = {}
local okFfi, ffi = pcall(require, 'ffi')
local index = require('ge/extensions/e2r/poiindex')
local floor, max, min = math.floor, math.max, math.min

local catalog, pins
do
  local ok, module = pcall(require, 'ge/extensions/e2r/mapCatalog')
  catalog = ok and type(module) == 'table' and module.catalogs and module or nil
  ok, module = pcall(require, 'ge/extensions/e2r/pins')
  pins = ok and type(module) == 'table' and module.STYLE and module or nil
  index.attach(catalog, pins)
end
function M.attach(catalogModule, pinsModule)
  catalog, pins = catalogModule, pinsModule
  index.attach(catalogModule, pinsModule)
end
M.index = index

M.PANEL = 340              -- px: the side panel
M.DOT_ZOOM = 15            -- city services become pictograms at street scale
M.DOT_CELL, M.ICON_CELL = 52, 78
-- markers drawn a frame at most: every dot is two engine calls, an icon several (3000 dots and
-- 27-40 thousand candidates projected a frame made the zoomed-out map slow, 18.11)
M.MAX_DOTS, M.MAX_ICONS, M.MAX_LABELS = 360, 180, 32
M.PAD = 0.5                -- the collected box: the view and this share of it again on each side
M.SLICE = 0.002            -- s of collecting a frame (os.clock); the last markers stay meanwhile
M.LABEL_ZOOM = 15          -- names next to icons from this zoom (or a category's labelZoom)

local GROUP_ORDER = {'car', 'transport', 'stay', 'shop', 'money', 'health', 'sight', 'nature', 'water', 'civic'}
local GROUP_NAMES = {
  car = {'Авто й пальне', 'Driving and fuel'}, transport = {'Транспорт', 'Transport'}, stay = {'Ночівля', 'Stay'},
  shop = {'Магазини та їжа', 'Shops and food'}, money = {'Гроші', 'Money'}, health = {'Здоров\'я', 'Health'},
  sight = {'Пам\'ятки', 'Sights'}, nature = {'Природа', 'Nature'}, water = {'Вода', 'Water'}, civic = {'Громада', 'Civic'},
}
M.GROUP_ORDER, M.GROUP_NAMES = GROUP_ORDER, GROUP_NAMES

-- the OSM facts on a card: label {Ukrainian, English} by key, in the file's order (build_map.py
-- POI_DETAILS); the address and fuels are put together, kinds and the id go last
local DETAIL = {
  ['name:uk'] = {'Українською', 'In Ukrainian'}, opening_hours = {'Години', 'Hours'}, phone = {'Телефон', 'Phone'},
  ['contact:phone'] = {'Телефон', 'Phone'}, website = {'Сайт', 'Website'}, ['contact:website'] = {'Сайт', 'Website'},
  cuisine = {'Кухня', 'Cuisine'}, brand = {'Бренд', 'Brand'}, operator = {'Оператор', 'Operator'},
  network = {'Мережа', 'Network'}, ref = {'Номер', 'Ref'}, religion = {'Релігія', 'Religion'},
  denomination = {'Конфесія', 'Denomination'}, description = {'Опис', 'Description'},
  wheelchair = {'Доступ на візку', 'Wheelchair'}, internet_access = {'Інтернет', 'Internet'}, fee = {'Платно', 'Fee'},
  capacity = {'Місць', 'Capacity'}, stars = {'Зірок', 'Stars'}, rooms = {'Номерів', 'Rooms'},
  ele = {'Висота, м', 'Elevation, m'}, height = {'Висота споруди, м', 'Height, m'}, start_date = {'Відкрито', 'Since'},
  heritage = {'Пам\'ятка спадщини', 'Heritage'}, wikipedia = {'Вікіпедія', 'Wikipedia'}, wikidata = {'Wikidata', 'Wikidata'},
  drive_through = {'Drive-through', 'Drive-through'}, takeaway = {'З собою', 'Takeaway'}, delivery = {'Доставка', 'Delivery'},
  outdoor_seating = {'Тераса', 'Outdoor seating'}, toilets = {'Туалет', 'Toilets'},
  compressed_air = {'Підкачка шин', 'Tyre air'}, car_wash = {'Мийка', 'Car wash'}, iata = {'IATA', 'IATA'}, icao = {'ICAO', 'ICAO'},
}
local YES = {yes = {'так', 'yes'}, no = {'ні', 'no'}, limited = {'частково', 'limited'}, only = {'лише', 'only'},
  designated = {'так', 'yes'}, wlan = {'Wi-Fi', 'Wi-Fi'}, wifi = {'Wi-Fi', 'Wi-Fi'}}
local FUEL = {{'fuel:diesel', 'дизель', 'diesel'}, {'fuel:octane_95', 'А-95', '95'}, {'fuel:lpg', 'газ', 'LPG'}}
local KIND_KEYS = {'amenity', 'shop', 'tourism', 'leisure', 'historic', 'natural', 'railway', 'aeroway', 'man_made',
  'office', 'craft', 'healthcare', 'sport'}
M.DETAIL = DETAIL

local S = {off = {}, open = {}, ptr = {}, browser = {}, coverage = false, points = true, pause = true, filterRev = 0}
M.state = S

function M.openSearch()
  S.panel, S.browser.focus = 'places', true
end

-- a category's look: its STYLE (pins.lua), a finer kind with its own shape or letters
local styles = {}
local function styleOf(id)
  local st = styles[id]
  if st == nil then
    local name, parent = index.CATS[id], index.PARENT[id]
    local base = pins and parent and pins.STYLE[parent]
    st = base or false
    if base and name ~= parent then
      local sub = index.SUB[parent] and index.SUB[parent][name:sub(#parent + 2)]
      local look = sub and (sub.shape or sub.text) and sub or base
      st = {group = base.group, text = look.text, shape = look.shape, labelZoom = base.labelZoom}
    end
    styles[id] = st
  end
  return st or nil
end
M.styleOf = styleOf

-- a category's name in the language
local function catName(name, L)
  if not name then return '' end
  local parent, kind = name:match('^([^/]+)/(.+)$')
  local sub = parent and index.SUB[parent] and index.SUB[parent][kind]
  if sub then return L(sub[1], sub[2]) end
  local n = pins and pins.NAMES and pins.NAMES[parent or name]
  return n and L(n[1], n[2]) or name
end
M.catName = catName

-- the categories shown: number -> true, rebuilt when a filter, the index or its categories change
local enabled, enabledKey = {}, nil
local function refreshEnabled()
  local category, pack = S.browser.category or 'all', S.browser.pack
  local key = table.concat({S.filterRev, index.revision, #index.CATS, S.points and 1 or 0, category, pack or ''}, ':')
  if key == enabledKey then return end
  enabledKey = key
  for k in pairs(enabled) do enabled[k] = nil end
  if not S.points then return end
  for id, name in ipairs(index.CATS) do
    local style = styleOf(id)
    if style and not S.off[name] and (category == 'all' or category == 'poi' or style.group == category) then enabled[id] = true end
  end
end

-- the filter list: groups of categories with their counts and labels (made when the counts or
-- the language change, no strings a frame)
local counts, filters, filterKey = {}, {}, nil
local function refreshFilters(L, lang)
  local key = index.revision * 1e3 + #index.CATS + (lang == 'en' and .5 or 0)
  if key == filterKey then return filters end
  filterKey = key
  index.counts(counts)
  filters = {}
  for name, count in pairs(counts) do
    local parent = name:match('^[^/]+')
    local st = pins and pins.STYLE[parent]
    if st then
      local g = filters[st.group]
      if not g then g = {cats = {}, total = 0}; filters[st.group] = g end
      g.cats[#g.cats + 1] = {name = name, count = count, label = catName(name, L)}
      g.total = g.total + count
    end
  end
  for group, g in pairs(filters) do
    table.sort(g.cats, function(a, b)
      if a.count ~= b.count then return a.count > b.count end
      return a.name < b.name
    end)
    for _, c in ipairs(g.cats) do c.text = string.format('%s  %d##wc_%s', c.label, c.count, c.name) end
    local n = GROUP_NAMES[group]
    g.text = string.format('%s  %d##wg_%s', n and L(n[1], n[2]) or group, g.total, group)
  end
  return filters
end

-- --- candidates and markers -----------------------------------------------------------------
local LEVELS = index.LEVELS
local bucketE, bucketI, levelCount = {}, {}, {}
for l = 1, LEVELS do bucketE[l], bucketI[l], levelCount[l] = {}, {}, 0 end
local function add(e, i, level)
  local n = levelCount[level] + 1
  levelCount[level] = n
  bucketE[level][n], bucketI[level][n] = e, i
end
-- The kept markers: two sets, the one drawn and the one being made. A set holds each marker's
-- screen place when it was collected, where lat 0, lon 0 was then (refX, refY) and the zoom.
local function newSet() return {n = 0, x = {}, y = {}, e = {}, i = {}, refX = 0, refY = 0} end
local shown, making = newSet(), newSet()
M.kept = shown
M.collects = 0
local job, target = nil, {}
local occupied, stamp = {}, 0   -- one marker a square: square -> stamp of the collect that took it
local LAT = 85.06

-- Collect the box into a set and thin it to one marker a square of a grid fixed to the world
-- (anchored at lat 0, lon 0, so a later collect keeps the same point of a square), best first:
-- the buckets go by priority. pause() yields when the frame's slice is spent.
local function build(set, z, w, s, e, n, screen, pause)
  for l = 1, LEVELS do levelCount[l] = 0 end
  local cell = z < M.DOT_ZOOM and M.DOT_CELL or M.ICON_CELL
  local px = index.GRID / 360 * 256 * 2 ^ z   -- an index cell on the screen
  local per = px <= cell and 1 or min(400, math.ceil((px / cell) ^ 2))
  index.collect(w, s, e, n, per, enabled, add, pause, S.browser.pack)
  local rx, ry = screen(0, 0)
  local xa, ya = screen(n, w)
  local xb, yb = screen(s, e)
  local fx0, fy0 = floor((xa - rx) / cell), floor((ya - ry) / cell)
  local nx, ny = floor((xb - rx) / cell) - fx0 + 1, floor((yb - ry) / cell) - fy0 + 1
  stamp = stamp + 1
  local X, Y, E, I, k = set.x, set.y, set.e, set.i, 0
  for level = 1, LEVELS do
    local bE, bI = bucketE[level], bucketI[level]
    for j = 1, levelCount[level] do
      local en, i = bE[j], bI[j]
      local x, y = screen(en.lat[i], en.lon[i])
      local fx, fy = floor((x - rx) / cell) - fx0, floor((y - ry) / cell) - fy0
      -- a point of an index cell over the box's edge stays out: it is off the box
      if fx >= 0 and fx < nx and fy >= 0 and fy < ny then
        local key = fy * nx + fx + 1
        if occupied[key] ~= stamp then
          occupied[key], k = stamp, k + 1
          X[k], Y[k], E[k], I[k] = x, y, en, i
        end
      end
      if j % 512 == 0 then pause() end
    end
  end
  for j = k + 1, set.n do E[j] = nil end
  set.n, set.refX, set.refY, set.z = k, rx, ry, z
end

-- Keep the markers over the view: a new collect when the zoom or the filters change or the view
-- leaves the box of the last one (the view and PAD of it on each side), a slice a frame; the
-- markers shown stay until it is done. True when a collect is under way.
local function collect(z, w, s, e, n, screen)
  w, e, s, n = max(-180, w), min(180, e), max(-LAT, s), min(LAT, n)
  local t = target
  if not (t.z == z and t.key == enabledKey and w >= t.w and e <= t.e and s >= t.s and n <= t.n) then
    local pw, ph = (e - w) * M.PAD, (n - s) * M.PAD
    t.z, t.key = z, enabledKey
    t.w, t.e, t.s, t.n = max(-180, w - pw), min(180, e + pw), max(-LAT, s - ph), min(LAT, n + ph)
    local set, bw, bs, be, bn = making, t.w, t.s, t.e, t.n
    job = coroutine.create(function(start)
      local clock = os.clock
      local function pause()
        if clock() - start > M.SLICE then start = coroutine.yield() end
      end
      build(set, z, bw, bs, be, bn, screen, pause)
    end)
  end
  if not job then return false end
  local ok, err = coroutine.resume(job, os.clock())
  if not ok then
    job = nil
    if log then log('W', 'e2r.worldmap', 'collecting the points failed: ' .. tostring(err)) end
    return false
  end
  if coroutine.status(job) ~= 'dead' then return true end
  job = nil
  shown, making = making, shown
  M.kept, M.collects = shown, M.collects + 1
  return false
end
M.collect = collect
M.levelCount = levelCount

local drawnX, drawnY, drawnE, drawnI = {}, {}, {}, {}
M.drawn = {n = 0, x = drawnX, y = drawnY, e = drawnE, i = drawnI}
local colours, P             -- U32 colours made once; one ImVec2 for every dot
local widths, widthCount = {}, 0

local function textWidth(im, text)
  local w = widths[text]
  if not w then
    widthCount = widthCount + 1
    if widthCount > 4000 then widths, widthCount = {}, 1 end
    w = im.CalcTextSize(text).x
    widths[text] = w
  end
  return w
end

local function makeColours(col)
  colours = {white = col(1, 1, 1), dark = col(.12, .12, .12), halo = col(1, 1, 1, .85), ring = col(1, .85, .1),
    pick = col(.86, .15, .12), pickDark = col(.5, .05, .05), cardBg = col(.10, .11, .13, .95), cardRim = col(.45, .70, 1),
    title = col(1, 1, 1), text = col(.88, .9, .93), muted = col(.62, .65, .70), accent = col(.45, .70, 1), group = {}}
  for g, rgb in pairs(pins and pins.GROUP or {}) do colours.group[g] = col(rgb[1], rgb[2], rgb[3]) end
end

-- the markers over the map (view.overlay, called by drawMap before the place names)
local function overlay(api, dl, screen, z, north, west, south, east, mouse, hovered, r0, r1)
  local im = api.im
  if not colours then makeColours(api.col) end
  if not P then P = im.ImVec2(0, 0) end
  refreshEnabled()
  if z >= 6 and S.points then collect(z, west, south, east, north, screen) end
  local dots = z < M.DOT_ZOOM
  local most = dots and M.MAX_DOTS or M.MAX_ICONS
  local white, n = colours.white, 0
  local x0, y0, x1, y1 = r0.x - 8, r0.y - 8, r1.x + 8, r1.y + 8
  -- The shown markers moved by the drag since they were collected: lat 0, lon 0 moved as much
  -- as every point. While a new zoom is collected the last zoom's markers scale round it (the
  -- map's pixels double a zoom step) and a category just switched off is left out.
  local set = shown
  local rx, ry = screen(0, 0)
  local f = set.z and 2 ^ (z - set.z) or 1
  local X, Y, E, I, srx, sry = set.x, set.y, set.e, set.i, set.refX, set.refY
  for k = 1, (z >= 6 and S.points) and set.n or 0 do
    if n >= most then break end
    local x, y = rx + (X[k] - srx) * f, ry + (Y[k] - sry) * f
    if x >= x0 and x <= x1 and y >= y0 and y <= y1 then
      local e, i = E[k], I[k]
      local st = enabled[e.cat[i]] and (not S.browser.pack or e.c.id == S.browser.pack) and styleOf(e.cat[i])
      local half = dots and 4 or st and st.text and max(9, textWidth(im, st.text) / 2 + 5) or 9
      if st and api.planetMap.place(x - half, y - (dots and 4 or 9), x + half, y + (dots and 4 or 9)) then
        n = n + 1
        drawnX[n], drawnY[n], drawnE[n], drawnI[n] = x, y, e, i
        local fill = colours.group[st.group] or colours.dark
        if dots then
          P.x, P.y = x, y
          im.ImDrawList_AddCircleFilled(dl, P, 3.8, white, 12)
          im.ImDrawList_AddCircleFilled(dl, P, 2.6, fill, 12)
        else
          pins.icon(im, dl, st, x, y, fill, white)
        end
      end
    end
  end
  M.drawn.n = n
  -- names beside the icons where they fit (the place names keep out of them, planetMap.place)
  if not dots and api.planetMap then
    local lang, labels = api.lang(), 0
    for k = 1, n do
      if labels >= M.MAX_LABELS then break end
      local e, i = drawnE[k], drawnI[k]
      local st = styleOf(e.cat[i])
      if z >= min(M.LABEL_ZOOM, st.labelZoom or M.LABEL_ZOOM) then
        local name = index.name(e, i, lang)
        if name ~= '' then
          local x, y, w = drawnX[k] + (st.text and max(0, textWidth(im, st.text) / 2 - 3) or 0), drawnY[k], textWidth(im, name)
          if api.planetMap.place(x + 10, y - 8, x + 16 + w, y + 8) then
            labels = labels + 1
            im.ImDrawList_AddRectFilled(dl, im.ImVec2(x + 10, y - 8), im.ImVec2(x + 16 + w, y + 8), colours.halo, 4)
            im.ImDrawList_AddText1(dl, im.ImVec2(x + 13, y - 7), colours.dark, name)
          end
        end
      end
    end
  end
  -- the point under the cursor
  S.hoverE, S.hoverI = nil, nil
  if hovered and mouse then
    local best, reach = nil, dots and 49 or 144
    for k = 1, n do
      local d = (drawnX[k] - mouse.x) ^ 2 + (drawnY[k] - mouse.y) ^ 2
      if d < reach then best, reach = k, d end
    end
    if best then
      S.hoverE, S.hoverI, S.hoverX, S.hoverY = drawnE[best], drawnI[best], drawnX[best], drawnY[best]
      im.ImDrawList_AddCircle(dl, im.ImVec2(S.hoverX, S.hoverY), dots and 6 or 12, colours.ring, 16, 2.5)
    end
  end
  -- the picked point: a red pin
  local pick = S.pick
  if pick then
    local x, y = screen(pick.lat, pick.lon)
    im.ImDrawList_AddCircleFilled(dl, im.ImVec2(x, y - 14), 9, white)
    im.ImDrawList_AddTriangleFilled(dl, im.ImVec2(x - 7, y - 11), im.ImVec2(x + 7, y - 11), im.ImVec2(x, y), white)
    im.ImDrawList_AddCircleFilled(dl, im.ImVec2(x, y - 14), 7.5, colours.pick)
    im.ImDrawList_AddTriangleFilled(dl, im.ImVec2(x - 5.6, y - 11.5), im.ImVec2(x + 5.6, y - 11.5), im.ImVec2(x, y - 1.5), colours.pick)
    im.ImDrawList_AddCircleFilled(dl, im.ImVec2(x, y - 14), 3, colours.pickDark)
  end
end
M.overlay = overlay

-- --- cards ----------------------------------------------------------------------------------
local function distance(lat1, lon1, lat2, lon2)
  local k = math.cos(math.rad((lat1 + lat2) / 2))
  return math.sqrt(((lat2 - lat1) * 110574) ^ 2 + ((lon2 - lon1) * 111320 * k) ^ 2)
end

-- a line cut to `most` bytes on a whole UTF-8 letter
local function cut(text, most)
  if #text <= most then return text end
  local stop = most
  while stop > 1 and text:byte(stop + 1) and text:byte(stop + 1) >= 128 and text:byte(stop + 1) < 192 do stop = stop - 1 end
  return text:sub(1, stop) .. '...'
end

-- The lines of a point's card: {text, kind ('title', 'text', 'muted', 'accent')}. p: {e, i} of the
-- index or {lat, lon, title, cat} (a search hit or a place).
function M.card(api, p)
  local L = api.L
  local out = {}
  local function line(text, kind) out[#out + 1] = {cut(text, 90), kind or 'text'} end
  local e, i = p.e, p.i
  local lat, lon = p.lat, p.lon
  local title, cat = p.title, p.cat
  if e then
    lat, lon = index.position(e, i)
    title, cat = index.name(e, i, api.lang()), index.category(e, i)
  end
  line(title ~= '' and title or catName(cat, L), 'title')
  if p.article then
    local a = p.article
    line(L(a.area.uk, a.area.en), 'muted')
    out[#out + 1] = {L(a.summary.uk, a.summary.en), 'text'}
    line(L('Джерело · ', 'Source · ') .. a.source, 'muted')
  end
  local where = e and e.title or (not p.article and p.context or nil)
  if cat or where then line((cat and catName(cat, L) or '') .. (cat and where and ' · ' or '') .. (where or ''), 'muted') end
  local details = e and index.details(e, i)
  if details then
    local tags = {}
    for _, kv in ipairs(details) do tags[kv[1]] = kv[2] end
    local street, city = tags['addr:street'], tags['addr:city']
    if street or city then
      local a = street and (street .. (tags['addr:housenumber'] and (' ' .. tags['addr:housenumber']) or '')) or ''
      if city then a = a ~= '' and (a .. ', ' .. city) or city end
      line(L('Адреса: ', 'Address: ') .. a)
    end
    local fuels = {}
    for _, f in ipairs(FUEL) do if tags[f[1]] == 'yes' then fuels[#fuels + 1] = L(f[2], f[3]) end end
    if #fuels > 0 then line(L('Пальне: ', 'Fuel: ') .. table.concat(fuels, ', ')) end
    for _, kv in ipairs(details) do
      local d = DETAIL[kv[1]]
      if d then
        local v = kv[2]
        local y = YES[v]
        if y then v = L(y[1], y[2]) end
        if kv[1] == 'cuisine' then v = v:gsub(';', ', '):gsub('_', ' ') end
        line(L(d[1], d[2]) .. ': ' .. v)
      end
    end
    local kinds = {}
    for _, k in ipairs(KIND_KEYS) do if tags[k] then kinds[#kinds + 1] = k .. '=' .. tags[k] end end
    if #kinds > 0 then line('OSM: ' .. table.concat(kinds, ', '), 'muted') end
    local osm = tags.osm
    if osm then
      local t = osm:sub(1, 1)
      line('osm.org/' .. (t == 'w' and 'way' or t == 'r' and 'relation' or 'node') .. '/' .. osm:sub(2), 'muted')
    end
  elseif e then
    line(L('Деталі OSM - з оновленими даними мапи', 'OSM details come with updated map data'), 'muted')
  end
  if lat and lon then line(string.format('%.5f, %.5f', lat, lon), 'muted') end
  local car = api.car()
  if car and lat then
    local d = distance(car.lat, car.lon, lat, lon)
    line(d < 1000 and string.format(L('%d м від авто', '%d m from the car'), floor(d))
      or string.format(L('%.1f км від авто', '%.1f km from the car'), d / 1000), 'accent')
  end
  return out
end

local function hoverCard(api)
  local e, i = S.hoverE, S.hoverI
  if not e then return nil end
  if S.cardE ~= e or S.cardI ~= i or S.cardLang ~= api.lang() then
    S.cardE, S.cardI, S.cardLang = e, i, api.lang()
    local name = index.name(e, i, api.lang())
    local category = catName(index.category(e, i), api.L)
    S.card = {{cut(name ~= '' and name or category, 64), 'title'},
      {name ~= '' and category or e.title, 'muted'}}
  end
  return S.card
end

local function drawCard(im, dl, lines, x, y, left, top, right, bottom)
  local w, h = 0, 10
  for _, l in ipairs(lines) do
    if not l.w then l.w = im.CalcTextSize(l[1]).x end
    w, h = max(w, l.w), h + 18
  end
  w = w + 20
  if x + w > right then x = x - w - 32 end
  if y + h > bottom then y = bottom - h end
  x, y = max(left, x), max(top, y)
  im.ImDrawList_AddRectFilled(dl, im.ImVec2(x, y), im.ImVec2(x + w, y + h), colours.cardBg, 6)
  im.ImDrawList_AddRect(dl, im.ImVec2(x, y), im.ImVec2(x + w, y + h), colours.cardRim, 6, 0, 1.5)
  local ty = y + 6
  for _, l in ipairs(lines) do
    im.ImDrawList_AddText1(dl, im.ImVec2(x + 10, ty), colours[l[2]] or colours.text, l[1])
    ty = ty + 18
  end
end

-- --- the panel ------------------------------------------------------------------------------
local function ptr(im, key, value)
  local p = S.ptr[key]
  if not p then p = im.BoolPtr(value); S.ptr[key] = p end
  p[0] = value
  return p
end

local function bufText(buf)
  if okFfi and type(buf) == 'cdata' then return ffi.string(buf) end
  return type(buf) == 'table' and buf.text or ''
end
local function clearBuf(buf)
  if okFfi and type(buf) == 'cdata' then ffi.fill(buf, 128) elseif type(buf) == 'table' then buf.text = '' end
end

local function pickPoint(view, p, zoom)
  S.pick = p
  view.center = {lat = p.lat, lon = p.lon}
  if zoom then view.zoom = zoom end
  view.follow = false
end

local SEARCH_LIMIT, PAGE_SIZE = 48, 8
local BROWSE_KINDS = {
  all = {'Усі категорії', 'All categories'}, start = {'Стартові місця', 'Starting points'},
  towns = {'Міста й села', 'Towns and villages'}, guide = {'Путівник', 'Field guide'},
  poi = {'Точки інтересу', 'Points of interest'},
}

local function nearby(near, pack, group, lang)
  local active = {}
  for id in ipairs(index.CATS) do
    local style = styleOf(id)
    if style and (group == 'poi' or style.group == group) then active[id] = true end
  end
  local around, radius = {}, .22   -- about 25 km
  local cos = max(.2, math.cos(math.rad(near.lat)))
  index.collect(near.lon - radius / cos, near.lat - radius, near.lon + radius / cos, near.lat + radius,
    24, active, function(e, i)
      local lat, lon = index.position(e, i)
      local d = (lat - near.lat)^2 + ((lon - near.lon) * cos)^2
      if d <= radius^2 then around[#around + 1] = {e = e, i = i, lat = lat, lon = lon, d = d} end
    end, nil, pack)
  table.sort(around, function(a, b)
    if a.d ~= b.d then return a.d < b.d end
    if a.e.title ~= b.e.title then return a.e.title < b.e.title end
    return a.i < b.i
  end)
  for k = #around, SEARCH_LIMIT + 1, -1 do around[k] = nil end
  for _, p in ipairs(around) do
    p.title, p.context = index.name(p.e, p.i, lang), p.e.title
    p.cat, p.zoom = index.category(p.e, p.i), 16
  end
  return around
end

local function townRow(p, lang)
  return {title = lang == 'en' and p[4] or p[5], context = p.context, kind = p[8],
    lat = p[1], lon = p[2], zoom = 14}
end

local function browseResults(api, query, category, pack, packs, near)
  local map, lang, L = api.planetMap, api.lang(), api.L
  local rows = {}
  local needle = map.lower(query)
  local function matches(name) return name and map.lower(name):find(needle, 1, true) end
  if category == 'all' or category == 'start' then
    for _, c in ipairs(packs) do
      if not pack or c.id == pack then
        for _, p in ipairs(c.starts) do
          if matches(p[1]) or matches(p[5]) or matches(c.title) then
            rows[#rows + 1] = {title = lang == 'en' and (p[5] or p[1]) or p[1],
              lat = p[2], lon = p[3], context = c.title, kind = 'start', zoom = 15}
          end
        end
      end
    end
  end
  if not pack and (category == 'guide' or category == 'all' and query == '') then
    for _, a in ipairs(map.articles()) do
      if matches(a.title.en) or matches(a.title.uk) or matches(a.area.en) or matches(a.area.uk) then
        rows[#rows + 1] = {title = L(a.title.uk, a.title.en), context = L(a.area.uk, a.area.en),
          lat = a.lat, lon = a.lon, article = a, zoom = 16}
      end
    end
  end
  if category == 'all' or category == 'towns' then
    if query == '' and pack then
      local towns = map.packPlaces(pack)
      if category == 'towns' then return rows, towns end
      for k = 1, min(SEARCH_LIMIT, #towns) do
        rows[#rows + 1] = townRow(towns[k], lang)
      end
    elseif query ~= '' then
      for _, p in ipairs(map.search(query, lang, SEARCH_LIMIT, pack, category == 'towns')) do
        rows[#rows + 1] = {title = p.name, lat = p.lat, lon = p.lon, context = p.context,
          kind = p.kind, article = p.article, zoom = p.zoom}
      end
    end
  end
  if category == 'poi' or GROUP_NAMES[category] or category == 'all' and query ~= '' then
    local points
    if query == '' then
      points = nearby(near, pack, category, lang)
    else
      local accepts
      if GROUP_NAMES[category] then
        accepts = function(cat)
          local style = pins.STYLE[cat]
          return style and style.group == category
        end
      end
      points = map.searchPois(query, SEARCH_LIMIT, near, pack, accepts)
      for _, p in ipairs(points) do
        p.e, p.i = index.find(p.lat, p.lon, p.cat, p.pack)
        p.title, p.zoom = lang == 'en' and (p.en or p.name) or p.name, 17
        if p.e then p.cat = index.category(p.e, p.i) end
      end
    end
    for _, p in ipairs(points) do rows[#rows + 1] = p end
  end
  return rows
end

local function fitText(im, text, width)
  if im.CalcTextSize(text).x <= width then return text end
  local n = #text
  repeat
    n = n - 1
    while n > 0 and text:byte(n + 1) >= 128 and text:byte(n + 1) < 192 do n = n - 1 end
    local short = text:sub(1, n) .. '…'
    if im.CalcTextSize(short).x <= width then return short end
  until n == 0
  return ''
end

-- Used by the landing picker and atlas. Each keeps its own query, scope and list position.
function M.drawBrowser(api, view, browser, choose)
  local im, L, map = api.im, api.L, api.planetMap
  local packs = api.packs()
  local pack
  for _, c in ipairs(packs) do if c.id == browser.pack then pack = c; break end end
  browser.pack = pack and pack.id
  browser.category = browser.category or 'all'
  local function title(pair) return L(pair[1], pair[2]) end
  if browser.category == 'guide' and pack then browser.category = 'all' end
  local filter = browser.category
  local packLabel = L('Усі пакети', 'All packs')
  im.SetNextItemWidth(-1)
  if im.BeginCombo('##browsePack', pack and pack.title or packLabel) then
    if im.Selectable1(packLabel, not pack) then
      browser.pack = nil
      if api.selectPack and pack then api.selectPack(nil) end
    end
    for _, c in ipairs(packs) do
      if im.Selectable1(c.title .. '##browse_' .. c.id, pack == c) then
        browser.pack = c.id
        if api.selectPack and pack ~= c then api.selectPack(c) end
      end
    end
    im.EndCombo()
  end
  im.SetNextItemWidth(-1)
  if im.BeginCombo('##browseCategory', title(BROWSE_KINDS[filter] or GROUP_NAMES[filter])) then
    local function option(key, names)
      if im.Selectable1(title(names) .. '##category_' .. key, filter == key) then browser.category = key end
    end
    for _, key in ipairs({'all', 'start', 'towns', 'guide', 'poi'}) do
      if key ~= 'guide' or not browser.pack then option(key, BROWSE_KINDS[key]) end
    end
    for _, key in ipairs(GROUP_ORDER) do option(key, GROUP_NAMES[key]) end
    im.EndCombo()
  end
  if browser.category == 'guide' and browser.pack then browser.category = 'all' end
  browser.buf = browser.buf or im.ArrayChar(128)
  im.SetNextItemWidth(-38)
  if browser.focus then im.SetKeyboardFocusHere(0); browser.focus = false end
  local wasTyping = browser.typing
  local submitted = im.InputTextWithHint('##browseSearch', L('Місто, пам’ятка, заклад…', 'Town, landmark, venue…'),
    browser.buf, 128, im.InputTextFlags_EnterReturnsTrue)
  browser.typing = im.IsItemActive()
  im.SameLine()
  if im.Button('×##browseClear') then clearBuf(browser.buf) end
  if im.IsItemHovered() then im.SetTooltip(L('Очистити пошук', 'Clear search')) end
  local query = bufText(browser.buf):gsub('^%s+', ''):gsub('%s+$', '')
  if (browser.typing or wasTyping) and im.IsKeyPressed(im.GetKeyIndex(im.Key_Escape))
    and (query ~= '' or browser.query and browser.query ~= '') then
    clearBuf(browser.buf)
    query, browser.escaped = '', true
  end
  local scoped
  for _, c in ipairs(packs) do if c.id == browser.pack then scoped = c; break end end
  local localList = query == '' and (browser.category == 'poi' or GROUP_NAMES[browser.category])
  if localList then
    if im.SmallButton(L('Оновити місця поблизу', 'Refresh nearby places')) then browser.key = nil end
    if im.IsItemHovered() then
      im.SetTooltip(L('До 25 км від центра мапи або старту пакета', 'Within 25 km of the map centre or pack start'))
    end
  end
  local _, letters = query:gsub('[^\128-\191]', '')
  if letters == 1 then
    im.TextWrapped(L('Введіть щонайменше дві літери.', 'Enter at least two characters.'))
    return
  end
  local key = table.concat({query, browser.category, browser.pack or '', api.lang(), map.revision(), index.revision}, '\0')
  if key ~= browser.key or packs ~= browser.packs then
    local near = view.center
    if scoped and scoped.landing and (not api.packAt or api.packAt(near.lat, near.lon) ~= scoped.id) then near = scoped.landing end
    local same = query == browser.query and browser.lastPack == browser.pack and browser.lastCategory == browser.category
    browser.key, browser.packs, browser.query = key, packs, query
    browser.lastPack, browser.lastCategory = browser.pack, browser.category
    browser.rows, browser.towns = browseResults(api, query, browser.category, browser.pack, packs, near)
    browser.townRows = {}
    if not same then browser.row = 1 end
  end
  local rows = browser.rows
  local count = browser.towns and #browser.towns or #rows
  if count == 0 then
    local stats = index.stats()
    if localList and stats.done < stats.total then im.TextWrapped(L('Завантажуємо місця з паків…', 'Reading places from packs…'))
    elseif query ~= '' then im.TextWrapped(L('Нічого не знайдено в поточному пакеті й категорії.', 'No matches for these filters.'))
    elseif localList then im.TextWrapped(L('Поруч немає місць цієї категорії.', 'There are no nearby places in this category.'))
    elseif not scoped and browser.category == 'towns' then im.TextWrapped(L('Оберіть пакет або введіть назву.', 'Choose a pack or enter a name.'))
    elseif #packs == 0 then im.TextWrapped(L('Встановіть пак місцевості, щоб побачити його місця.', 'Install a region pack to browse its places.'))
    else im.TextWrapped(L('У цьому пакеті немає списку для цієї категорії.', 'This pack has no list for this category.')) end
    return
  end
  local row = max(1, min(count, browser.row or 1))
  if browser.typing then
    if im.IsKeyPressed(im.GetKeyIndex(im.Key_DownArrow)) then row = min(count, row + 1) end
    if im.IsKeyPressed(im.GetKeyIndex(im.Key_UpArrow)) then row = max(1, row - 1) end
  end
  local page = floor((row - 1) / PAGE_SIZE)
  if browser.page ~= page then browser.page, browser.townRows = page, {} end
  local width = im.GetContentRegionAvailWidth() - 12
  local fontsize = im.GetFontSize()
  for i = page * PAGE_SIZE + 1, min(count, (page + 1) * PAGE_SIZE) do
    local p = rows[i] or browser.townRows[i]
    if not p then
      p = townRow(browser.towns[i], api.lang())
      browser.townRows[i] = p
    end
    if not p.caption or p.width ~= width or p.fontsize ~= fontsize then
      local meta = p.cat and catName(p.cat, L) or p.kind == 'start' and browser.category ~= 'start' and L('Старт', 'Start') or
        p.article and browser.category ~= 'guide' and L('Путівник', 'Field guide') or nil
      local context = p.context
      if scoped and context then
        local prefix = scoped.title .. ' · '
        if context == scoped.title then context = nil
        elseif context:sub(1, #prefix) == prefix then context = context:sub(#prefix + 1) end
      end
      if meta then context = context and meta .. ' · ' .. context or meta end
      p.caption, p.subtitle = fitText(im, p.title, width), context and fitText(im, context, width)
      p.width, p.fontsize = width, fontsize
    end
    local clicked = im.Selectable1(p.caption .. '##browseResult' .. i, i == row)
    if p.caption ~= p.title and im.IsItemHovered() then im.SetTooltip(p.title) end
    if p.subtitle then im.TextColored(api.theme().muted, p.subtitle) end
    if clicked or submitted and i == row then browser.row = i; choose(p); return end
  end
  if count > PAGE_SIZE then
    if im.SmallButton(L('‹ Назад', '‹ Previous') .. '##browsePrev') then row = max(1, (page - 1) * PAGE_SIZE + 1) end
    im.SameLine()
    im.Text(string.format('%d / %d', page + 1, math.ceil(count / PAGE_SIZE)))
    im.SameLine()
    if im.SmallButton(L('Далі ›', 'Next ›') .. '##browseNext') then row = min(page + 1, floor((count - 1) / PAGE_SIZE)) * PAGE_SIZE + 1 end
  end
  browser.row = row
end

local function drawFilters(api)
  local im, L, theme = api.im, api.L, api.theme()
  local list = refreshFilters(L, api.lang())
  im.Text(L('Точки інтересу', 'Points of interest'))
  im.SameLine()
  if im.Button(L('Усі', 'All') .. '##wall', im.ImVec2(56, 0)) then S.off, S.filterRev = {}, S.filterRev + 1 end
  im.SameLine()
  if im.Button(L('Жодної', 'None') .. '##wnone', im.ImVec2(64, 0)) then
    for name in pairs(counts) do S.off[name] = true end
    S.filterRev = S.filterRev + 1
  end
  local any = false
  for _, g in ipairs(GROUP_ORDER) do
    local group = list[g]
    if group then
      any = true
      if im.Button((S.open[g] and '-' or '+') .. '##wo_' .. g, im.ImVec2(22, 0)) then S.open[g] = not S.open[g] end
      im.SameLine()
      local at = im.GetCursorScreenPos()
      im.ImDrawList_AddRectFilled(im.GetWindowDrawList(), im.ImVec2(at.x, at.y + 5), im.ImVec2(at.x + 12, at.y + 17),
        colours and colours.group[g] or 0, 3)
      im.Dummy(im.ImVec2(14, 20))
      im.SameLine()
      local on = false
      for _, c in ipairs(group.cats) do if not S.off[c.name] then on = true; break end end
      local p = ptr(im, 'g_' .. g, on)
      if im.Checkbox(group.text, p) then
        for _, c in ipairs(group.cats) do S.off[c.name] = (not p[0]) or nil end
        S.filterRev = S.filterRev + 1
      end
      if S.open[g] then
        for _, c in ipairs(group.cats) do
          im.Dummy(im.ImVec2(30, 1))
          im.SameLine()
          local cp = ptr(im, c.name, not S.off[c.name])
          if im.Checkbox(c.text, cp) then
            S.off[c.name] = (not cp[0]) or nil
            S.filterRev = S.filterRev + 1
          end
        end
      end
    end
  end
  if not any then
    im.TextWrapped(L('Точок ще немає: їх дають дані мапи встановлених пакетів (map/ або maps/ планети).',
      'No points yet: they come with the installed packs\' map data (map/ or the planet\'s maps/).'))
  end
  local st = index.stats()
  if st.busy then
    im.TextColored(theme.accent, string.format(L('Індексую: %s (%d з %d)', 'Indexing: %s (%d of %d)'), st.busy, st.done, st.total))
  else
    im.TextColored(theme.muted, string.format(L('Точок: %d · каталогів: %d', 'Points: %d · catalogs: %d'), st.points, st.total))
  end
end

local function drawPick(api, view)
  local im, L, theme = api.im, api.L, api.theme()
  local p = S.pick
  if not p then return end
  if S.pickCard ~= p or S.pickLang ~= api.lang() then
    if p.article then p.title = api.L(p.article.title.uk, p.article.title.en) end
    S.pickCard, S.pickLang, S.pickLines = p, api.lang(), M.card(api, p)
  end
  im.Separator()
  for k, l in ipairs(S.pickLines) do
    if k == 1 then im.TextColored(theme.accent, l[1])
    elseif l[2] == 'muted' then im.TextColored(theme.muted, l[1])
    else im.TextWrapped(l[1]) end
  end
  if p.article and im.SetClipboardText and im.SmallButton(L('Копіювати посилання', 'Copy source link')) then
    im.SetClipboardText(p.article.url)
  end
  local lat, lon = p.lat, p.lon
  if p.e then lat, lon = index.position(p.e, p.i) end
  if api.canNavigate() and im.Button(L('Вести сюди', 'Navigate here') .. '##wnav', im.ImVec2(150, 0)) then
    if api.navigate(lat, lon) then api.close() else S.navFailed = p end
  end
  if S.navFailed == p then im.TextColored(theme.warn, L('Маршрут лише в межах поточного пакета', 'Routes stay within the current pack')) end
  local country = api.canLand(lat, lon)
  if country then
    if im.Button(L('Висадитися тут', 'Land here') .. '##wland', im.ImVec2(150, 0)) then api.land(lat, lon) end
  end
  if im.Button(L('Показати', 'Show') .. '##wshow', im.ImVec2(100, 0)) then
    view.center, view.follow = {lat = lat, lon = lon}, false
    view.zoom = max(view.zoom, 16)
  end
  im.SameLine()
  if im.Button(L('Скинути вибір', 'Clear selection') .. '##wclear') then S.pick, S.panel = nil, 'places' end
end

local function drawPanel(api, view, width, height)
  local im, L, theme = api.im, api.L, api.theme()
  im.BeginChild1('##worldside', im.ImVec2(width, height), true)
  if S.panel ~= S.lastPanel then im.SetScrollY(0); S.lastPanel = S.panel end
  im.TextColored(theme.accent, L('Атлас Землі', 'Earth atlas'))
  local car = api.car()
  if car and im.Button(L('До авто', 'To the car') .. '##wcar') then
    view.center, view.zoom, view.follow = {lat = car.lat, lon = car.lon}, 15, false
  end
  if car then im.SameLine() end
  if im.Button(L('Весь світ', 'Whole world') .. '##wworld') then
    view.center, view.zoom, view.follow = {lat = 30, lon = 15}, 2, false
  end
  im.SameLine()
  if im.Button(L('Закрити', 'Close') .. '##wclose') then api.close() end
  im.Separator()
  local function tab(id, label)
    local active = theme.selected and (S.panel or 'places') == id
    if active then im.PushStyleColor2(im.Col_Button, theme.selected) end
    if im.Button(label .. '##w' .. id) then S.panel = id end
    if active then im.PopStyleColor() end
  end
  tab('places', L('Місця', 'Places'))
  if S.pick then
    im.SameLine()
    tab('card', L('Картка', 'Place card'))
  end
  im.SameLine()
  tab('layers', L('Шари', 'Layers'))
  im.Separator()
  if S.panel == 'card' and S.pick then
    drawPick(api, view)
  elseif S.panel == 'layers' then
    if api.photo and im.Checkbox(L('Фотопідкладка', 'Map imagery') .. '##wphoto', ptr(im, 'photo', api.photo())) then
      api.setPhoto(S.ptr.photo[0])
    end
    if im.Checkbox(L('Точки інтересу', 'Points of interest') .. '##wpts', ptr(im, 'points', S.points)) then
      S.points = S.ptr.points[0] and true or false
    end
    if im.Checkbox(L('Де можна висадитися', 'Where you can land') .. '##wcov', ptr(im, 'coverage', S.coverage)) then
      S.coverage = S.ptr.coverage[0] and true or false
    end
    if im.Checkbox(L('Пауза, поки відкрита мапа', 'Pause while the map is open') .. '##wpause', ptr(im, 'pause', S.pause)) then
      S.pause = S.ptr.pause[0] and true or false
      M.setPause(S.pause)
    end
    if S.points and im.CollapsingHeader1(L('Категорії позначок', 'Marker categories') .. '##wfilter') then drawFilters(api) end
  elseif api.packs then
    M.drawBrowser(api, view, S.browser, function(p) pickPoint(view, p, p.zoom); S.panel = 'card' end)
  end
  im.EndChild()
end

-- --- the game's pause -----------------------------------------------------------------------
-- taken only when the game ran: a game the player paused stays paused after the map
function M.setPause(on)
  local sta = rawget(_G, 'simTimeAuthority')
  if type(sta) ~= 'table' or type(sta.pause) ~= 'function' then return end
  if on and not S.paused then
    local ok, already = pcall(function() return sta.getPause and sta.getPause() end)
    if ok and already then return end
    if pcall(sta.pause, true) then S.paused = true end
  elseif not on and S.paused then
    pcall(sta.pause, false)
    S.paused = false
  end
end

-- the map is shut (world.lua, every frame it is not open): give the game back
function M.closed()
  if S.shown then
    S.shown = false
    M.setPause(false)
  end
end

-- Streamed scenes can carry points even when this area has no map sidecar. Keep
-- them as a fallback under the atlas filters; the shared layout removes duplicates.
local function acceptsPin(poi)
  if not S.points then return false end
  local cat = poi.cat or (poi.kind == 'fuel' and 'service_map' or 'shop_map')
  local style = pins and pins.STYLE[cat]
  if poi.lat and poi.lon and poi.mapCategoryRevision ~= index.revision then
    local e, i = index.find(poi.lat, poi.lon, cat)
    poi.mapCategory = e and index.category(e, i) or cat
    poi.mapCategoryRevision = index.revision
  end
  local category = S.browser.category or 'all'
  return style and not S.off[cat] and not S.off[poi.mapCategory or cat]
    and (not S.browser.pack or (S.packAt and S.packAt(poi.lat, poi.lon) == S.browser.pack))
    and (category == 'all' or category == 'poi' or style.group == category)
end

-- --- the screen -----------------------------------------------------------------------------
-- api (world.lua LIMIT.worldApi): im, col, L, lang(), theme(), pushTheme, popTheme, winguard,
-- planetMap, drawMap(w, h, view), car(), start() -> center, zoom, canLand(lat, lon) -> pack or nil,
-- land(lat, lon), canNavigate(), navigate(lat, lon) -> true when routed, close()
function M.draw(api)
  local im = api.im
  S.packAt = api.packAt
  index.step()
  local view = S.view
  if not view then
    local center, zoom = api.start()
    view = {center = {lat = center.lat, lon = center.lon}, zoom = zoom or 12, follow = false, world = true}
    view.overlay = function(...) overlay(api, ...) end
    view.acceptPin = acceptsPin
    view.onClick = function(lat, lon, place)
      S.panel = 'card'
      if place then
        S.pick = {lat = lat, lon = lon, title = place.name, article = place.article, context = place.context}
      elseif S.hoverE then
        local plat, plon = index.position(S.hoverE, S.hoverI)
        S.pick = {e = S.hoverE, i = S.hoverI, lat = plat, lon = plon}
      else
        S.pick = {lat = lat, lon = lon, title = api.L('Точка на мапі', 'A point on the map')}
      end
    end
    S.view = view
  end
  view.coverage = S.coverage
  view.noPins = not S.points
  if not S.shown then
    S.shown = true
    -- the car's place when the map opens while driving
    local car = api.car()
    if car then
      local _, zoom = api.start()
      view.center, view.zoom = {lat = car.lat, lon = car.lon}, max(view.zoom, zoom or 13, 13)
    end
    if S.pause then M.setPause(true) end
  end
  if not colours then makeColours(api.col) end
  local io = im.GetIO()
  local w, h = io.DisplaySize.x, io.DisplaySize.y
  local viewport = im.GetMainViewport and im.GetMainViewport()
  local origin = viewport and viewport.Pos
  if viewport and viewport.Size.x > 0 and viewport.Size.y > 0 then w, h = viewport.Size.x, viewport.Size.y end
  api.pushTheme()
  im.SetNextWindowPos(im.ImVec2(origin and origin.x or 0, origin and origin.y or 0), im.Cond_Always)
  im.SetNextWindowSize(im.ImVec2(w, h), im.Cond_Always)
  local flags = im.WindowFlags_NoTitleBar + im.WindowFlags_NoResize + im.WindowFlags_NoMove + im.WindowFlags_NoCollapse
  api.winguard.begin(im, 'EarthNG##worldmap', flags)
  local avail = im.GetContentRegionAvail()
  local panel = min(M.PANEL, max(260, avail.x * .32))
  drawPanel(api, view, panel, avail.y)
  im.SameLine()
  im.BeginGroup()
  local mapW, mapH = max(1, avail.x - panel - 8), max(1, avail.y)
  local r0 = im.GetCursorScreenPos()
  local r0x, r0y = r0.x, r0.y
  api.drawMap(mapW, mapH, view)
  im.EndGroup()
  local lines = hoverCard(api)
  if lines then
    drawCard(im, im.GetWindowDrawList(), lines, S.hoverX + 18, S.hoverY + 14, r0x + 4, r0y + 4, r0x + mapW - 4, r0y + mapH - 4)
  end
  -- keys: Esc clears the search first, then shuts; C - to the car; PageUp/PageDown - zoom
  local typing = io.WantTextInput
  if S.browser.escaped then
    S.browser.escaped = false
  elseif im.IsKeyPressed(im.GetKeyIndex(im.Key_Escape)) then
    api.close()
  elseif not typing then
    local car = api.car()
    if car and im.Key_C and im.IsKeyPressed(im.GetKeyIndex(im.Key_C)) then
      view.center, view.follow = {lat = car.lat, lon = car.lon}, false
    end
    if im.Key_PageUp and im.IsKeyPressed(im.GetKeyIndex(im.Key_PageUp)) then view.zoom = min(18, view.zoom + 1) end
    if im.Key_PageDown and im.IsKeyPressed(im.GetKeyIndex(im.Key_PageDown)) then view.zoom = max(2, view.zoom - 1) end
  end
  im.End()
  api.popTheme()
end

return M
