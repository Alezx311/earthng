-- The world map on M (docs/MAP.md "Карта світу"): the whole planet on one screen with the points
-- of interest of the installed map sidecars. A side panel holds the search, the layers, the filters
-- by group and category with their counts, and the chosen point's card; the map (world.lua
-- drawMap, view.world) shows the enabled points (poiindex.lua): dots of their group's colour when
-- far, icons closer, names close up, and the OSM facts (poi_tags.tsv) of the point under the
-- cursor. A click only picks a point or a place; its card offers the route there and a landing,
-- so a stray click never moves the car. The game pauses while the map is open (a layer switch).
--
-- Every frame: the candidates are collected only when the view or the filters change, markers go
-- into reused arrays, the dots share one reused ImVec2, labels and cards are cached by point.
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
M.DOT_ZOOM = 10            -- below it the points are dots, from it icons
M.DOT_CELL, M.ICON_CELL = 7, 24   -- px: one marker per square of this side
M.MAX_DOTS, M.MAX_ICONS, M.MAX_LABELS = 3000, 320, 60
M.LABEL_ZOOM = 15          -- names next to icons from this zoom (or a category's labelZoom)

local GROUP_ORDER = {'car', 'transport', 'stay', 'shop', 'money', 'health', 'sight', 'nature', 'water', 'civic'}
local GROUP_NAMES = {
  car = {'Авто', 'Car'}, transport = {'Транспорт', 'Transport'}, stay = {'Ночівля', 'Stay'},
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

local S = {off = {}, open = {}, ptr = {}, coverage = true, points = true, pause = true, filterRev = 0}
M.state = S

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
  local key = S.filterRev * 1e6 + index.revision * 1e3 + #index.CATS + (S.points and 0 or .5)
  if key == enabledKey then return end
  enabledKey = key
  for k in pairs(enabled) do enabled[k] = nil end
  if not S.points then return end
  for id, name in ipairs(index.CATS) do
    if styleOf(id) and not S.off[name] then enabled[id] = true end
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
local cache = {}
local function collect(z, w, s, e, n)
  if cache.z == z and cache.w == w and cache.s == s and cache.e == e and cache.n == n and cache.key == enabledKey then return end
  cache.z, cache.w, cache.s, cache.e, cache.n, cache.key = z, w, s, e, n, enabledKey
  for l = 1, LEVELS do levelCount[l] = 0 end
  local cell = z < M.DOT_ZOOM and M.DOT_CELL or M.ICON_CELL
  local px = index.GRID / 360 * 256 * 2 ^ z   -- an index cell on the screen
  local per = px <= cell and 1 or min(400, math.ceil((px / cell) ^ 2))
  index.collect(w, s, e, n, per, enabled, add)
end
M.collect = collect
M.levelCount = levelCount

local occupied, stamp = {}, 0
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
  collect(z, west, south, east, north)
  stamp = stamp + 1
  local dots = z < M.DOT_ZOOM
  local cell = dots and M.DOT_CELL or M.ICON_CELL
  local most = dots and M.MAX_DOTS or M.MAX_ICONS
  local white, n = colours.white, 0
  local x0, y0, x1, y1 = r0.x - 8, r0.y - 8, r1.x + 8, r1.y + 8
  for level = 1, LEVELS do
    local bE, bI = bucketE[level], bucketI[level]
    for k = 1, levelCount[level] do
      if n >= most then break end
      local e, i = bE[k], bI[k]
      local x, y = screen(e.lat[i], e.lon[i])
      if x >= x0 and x <= x1 and y >= y0 and y <= y1 then
        local key = floor(x / cell) * 65536 + floor(y / cell)
        local st = occupied[key] ~= stamp and styleOf(e.cat[i])
        if st then
          occupied[key], n = stamp, n + 1
          drawnX[n], drawnY[n], drawnE[n], drawnI[n] = x, y, e, i
          local fill = colours.group[st.group] or colours.dark
          if dots then
            P.x, P.y = x, y
            im.ImDrawList_AddCircleFilled(dl, P, 3.4, white, 8)
            im.ImDrawList_AddCircleFilled(dl, P, 2.5, fill, 8)
          else
            pins.icon(im, dl, st, x, y, fill, white)
          end
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
          local x, y, w = drawnX[k], drawnY[k], textWidth(im, name)
          if api.planetMap.place(x + 10, y - 8, x + 16 + w, y + 8) then
            labels = labels + 1
            im.ImDrawList_AddRectFilled(dl, im.ImVec2(x + 10, y - 8), im.ImVec2(x + 16 + w, y + 8), colours.halo, 4)
            im.ImDrawList_AddText1(dl, im.ImVec2(x + 13, y - 7), colours.dark, name)
          end
        end
      else
        api.planetMap.reserve(drawnX[k] - 9, drawnY[k] - 9, drawnX[k] + 9, drawnY[k] + 9)
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
  local where = e and e.title or p.context
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
    S.card = M.card(api, {e = e, i = i})
    S.card[#S.card + 1] = {api.L('Клік - вибрати', 'Click - pick'), 'muted'}
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

local function drawSearch(api, view)
  local im, L, lang = api.im, api.L, api.lang()
  S.buf = S.buf or im.ArrayChar(128)
  if im.PushItemWidth then im.PushItemWidth(-1) end
  im.InputTextWithHint('##worldsearch', L('Пошук: місто, вулиця, заклад...', 'Search: city, street, venue...'), S.buf, 128)
  if im.PopItemWidth then im.PopItemWidth() end
  S.typing = im.IsItemActive and im.IsItemActive() or false
  local query = bufText(S.buf):gsub('^%s+', ''):gsub('%s+$', '')
  if query ~= S.query then S.query, S.found = query, nil end
  if #query < 2 then return end
  if not S.found and api.planetMap then
    S.found = {places = api.planetMap.search(query, lang, 6) or {},
      pois = #query >= 3 and api.planetMap.searchPois and api.planetMap.searchPois(query, 10, view.center) or {}}
  end
  local found = S.found or {places = {}, pois = {}}
  for k, p in ipairs(found.places) do
    if im.Selectable1(p.name .. (p.context and ('  · ' .. p.context) or '') .. '##wp' .. k, false) then
      pickPoint(view, {lat = p.lat, lon = p.lon, title = p.name, context = p.context}, p.zoom or 12)
    end
  end
  for k, p in ipairs(found.pois) do
    local label = (lang == 'en' and p.en or p.name) .. '  · ' .. catName(p.cat, L)
    if im.Selectable1(label .. '##wq' .. k, false) then
      local e, i = index.find(p.lat, p.lon, p.cat)
      pickPoint(view, e and {e = e, i = i, lat = p.lat, lon = p.lon} or
        {lat = p.lat, lon = p.lon, title = lang == 'en' and p.en or p.name, cat = p.cat, context = p.context}, 17)
    end
  end
  if #found.places == 0 and #found.pois == 0 then im.TextColored(api.theme().muted, L('Нічого не знайдено', 'Nothing found')) end
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
    S.pickCard, S.pickLang, S.pickLines = p, api.lang(), M.card(api, p)
  end
  im.Separator()
  for k, l in ipairs(S.pickLines) do
    if k == 1 then im.TextColored(theme.accent, l[1])
    elseif l[2] == 'muted' then im.TextColored(theme.muted, l[1])
    else im.TextWrapped(l[1]) end
  end
  local lat, lon = p.lat, p.lon
  if p.e then lat, lon = index.position(p.e, p.i) end
  if api.canNavigate() and im.Button(L('Вести сюди', 'Navigate here') .. '##wnav', im.ImVec2(150, 0)) then
    if api.navigate(lat, lon) then api.close() else S.navFailed = p end
  end
  if S.navFailed == p then im.TextColored(theme.warn, L('Маршрут лише в межах поточного пакета', 'Routes stay within the current pack')) end
  local country = api.canLand(lat, lon)
  if country then
    if api.canNavigate() then im.SameLine() end
    if im.Button(L('Висадитися тут', 'Land here') .. '##wland', im.ImVec2(150, 0)) then api.land(lat, lon) end
  end
  if im.Button(L('Показати', 'Show') .. '##wshow', im.ImVec2(100, 0)) then
    view.center, view.follow = {lat = lat, lon = lon}, false
    view.zoom = max(view.zoom, 16)
  end
  im.SameLine()
  if im.Button(L('Скинути', 'Clear') .. '##wclear', im.ImVec2(100, 0)) then S.pick = nil end
end

local function drawPanel(api, view, width, height)
  local im, L, theme = api.im, api.L, api.theme()
  im.BeginChild1('##worldside', im.ImVec2(width, height), true)
  im.TextColored(theme.accent, L('Карта світу', 'World map'))
  im.SameLine()
  im.TextColored(theme.muted, L('  M - закрити', '  M - close'))
  drawSearch(api, view)
  im.Separator()
  local car = api.car()
  if car and im.Button(L('До авто', 'To the car') .. '##wcar', im.ImVec2(100, 0)) then
    view.center, view.zoom, view.follow = {lat = car.lat, lon = car.lon}, max(view.zoom, 14), false
  end
  if car then im.SameLine() end
  if im.Button(L('Весь світ', 'Whole world') .. '##wworld', im.ImVec2(100, 0)) then
    view.center, view.zoom, view.follow = {lat = 30, lon = 15}, 2, false
  end
  if im.Checkbox(L('Точки інтересу', 'Points of interest') .. '##wpts', ptr(im, 'points', S.points)) then
    S.points = S.ptr.points[0] and true or false
  end
  if im.Checkbox(L('Де можна висадитися', 'Where you can land') .. '##wcov', ptr(im, 'coverage', S.coverage)) then
    S.coverage = S.ptr.coverage[0] and true or false
  end
  if im.Checkbox(L('Пауза, поки відкрита карта', 'Pause while the map is open') .. '##wpause', ptr(im, 'pause', S.pause)) then
    S.pause = S.ptr.pause[0] and true or false
    M.setPause(S.pause)
  end
  im.Separator()
  drawPick(api, view)
  if S.pick then im.Separator() end
  drawFilters(api)
  im.Spacing()
  im.TextColored(theme.muted, L('Колесо - масштаб, перетягування - огляд, клік - вибрати точку; C - до авто, Esc - закрити',
    'Wheel - zoom, drag - pan, click - pick a point; C - to the car, Esc - close'))
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

-- --- the screen -----------------------------------------------------------------------------
-- api (world.lua LIMIT.worldApi): im, col, L, lang(), theme(), pushTheme, popTheme, winguard,
-- planetMap, drawMap(w, h, view), car(), start() -> center, zoom, canLand(lat, lon) -> pack or nil,
-- land(lat, lon), canNavigate(), navigate(lat, lon) -> true when routed, close()
function M.draw(api)
  local im = api.im
  index.step()
  local view = S.view
  if not view then
    local center, zoom = api.start()
    view = {center = {lat = center.lat, lon = center.lon}, zoom = zoom or 12, follow = false, world = true}
    view.overlay = function(...) overlay(api, ...) end
    view.onClick = function(lat, lon)
      if S.hoverE then
        local plat, plon = index.position(S.hoverE, S.hoverI)
        S.pick = {e = S.hoverE, i = S.hoverI, lat = plat, lon = plon}
      else
        S.pick = {lat = lat, lon = lon, title = api.L('Точка на мапі', 'A point on the map')}
      end
    end
    S.view = view
  end
  view.coverage = S.coverage
  view.noPins = index.stats().points > 0
  if not S.shown then
    S.shown = true
    -- the car's place when the map opens while driving
    local car = api.car()
    if car then view.center, view.zoom = {lat = car.lat, lon = car.lon}, max(view.zoom, 13) end
    if S.pause then M.setPause(true) end
  end
  if not colours then makeColours(api.col) end
  local io = im.GetIO()
  local w, h = io.DisplaySize.x, io.DisplaySize.y
  api.pushTheme()
  im.SetNextWindowPos(im.ImVec2(0, 0), im.Cond_Always)
  im.SetNextWindowSize(im.ImVec2(w, h), im.Cond_Always)
  local flags = im.WindowFlags_NoTitleBar + im.WindowFlags_NoResize + im.WindowFlags_NoMove + im.WindowFlags_NoCollapse
  api.winguard.begin(im, 'EarthNG##worldmap', flags)
  local avail = im.GetContentRegionAvail()
  local panel = min(M.PANEL, max(220, avail.x * .3))
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
  if im.IsKeyPressed(im.GetKeyIndex(im.Key_Escape)) then
    if typing and S.query and S.query ~= '' then clearBuf(S.buf) else api.close() end
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
