-- The card of the point of interest by the car (docs/POI.md "Енциклопедія"): driving up to a
-- place the map marks, the player reads what it is - its name, what such a thing is (the two
-- sentences of its type, poi_lib.lua), and what OSM knows of this one: its height, its year, who
-- made it, its Wikipedia article's name. A point reached under VISIT_SPEED is entered in the
-- journal (settings/earthng_journal.json, kept by world.lua): the card says when a place is new
-- and how many the player has found.
--
-- step() runs four times a second over the streamed tiles' records (generator.lua SPLIT.out:
-- {kind = 'pin', x, y, label, ele, info = poi.record}); the card's lines are made once per point
-- and language. draw() takes no input and never has the mouse.
local M = {}
local poi = require('ge/extensions/e2r/poi')
-- names in Latin letters for the English UI (translit.lua); as they are where it cannot load
local okTranslit, translit = pcall(require, 'ge/extensions/e2r/translit')
if not okTranslit or type(translit) ~= 'table' then translit = {latin = function(s) return s end} end

M.RANGE = 60          -- m: the nearest described point within this shows its card
M.KEEP = 80           -- m: a shown card stays until the car is this far
M.SPEED = 25          -- m/s: no card over this (90 km/h): nobody reads at speed
M.VISIT = 35          -- m, and under VISIT_SPEED m/s: the point is found
M.VISIT_SPEED = 14
M.WRAP = 62           -- characters a line of text
M.NOTE = 220          -- characters of an OSM description kept

function M.new()
  return {seen = {}, found = 0}
end

-- the journal as saved: {ids = {'n123', ...}}
function M.load(t, data)
  t.seen, t.found = {}, 0
  for _, id in ipairs(type(data) == 'table' and type(data.ids) == 'table' and data.ids or {}) do
    if not t.seen[id] then t.seen[id], t.found = true, t.found + 1 end
  end
end

function M.save(t)
  local ids = {}
  for id in pairs(t.seen) do ids[#ids + 1] = id end
  table.sort(ids)
  return {version = 1, ids = ids}
end

-- text cut into lines of at most `width` characters at its spaces (UTF-8: a character is a lead
-- byte and its continuation bytes)
function M.wrap(text, width, out)
  out = out or {}
  local line, count = '', 0
  for word in tostring(text):gmatch('%S+') do
    local n = select(2, word:gsub('[^\128-\191]', ''))
    if count > 0 and count + 1 + n > width then
      out[#out + 1] = line
      line, count = word, n
    else
      line, count = count > 0 and (line .. ' ' .. word) or word, count + (count > 0 and 1 or 0) + n
    end
  end
  if count > 0 then out[#out + 1] = line end
  return out
end

local function cut(text, most)
  text = tostring(text)
  if #text <= most then return text end
  local stop = most
  while stop > 1 and text:byte(stop + 1) and text:byte(stop + 1) >= 128 and text:byte(stop + 1) < 192 do stop = stop - 1 end
  return text:sub(1, stop) .. '…'
end

-- does this record have a card: a pin whose type the library says something of
function M.described(rec)
  local info = rec.info
  if rec.kind ~= 'pin' or not info then return nil end
  local t = poi.lib.types[info.type]
  if t and t.textUk then return t end
  return nil
end

-- The card's lines {text, role} for a record: role 'title', 'kind', 'text', 'fact', 'new' or 'old'.
-- details: the point's OSM facts of the map sidecar as {{key, value}, ...} (poiindex.details), or nil
function M.lines(rec, t, lang, isNew, found, details)
  local en = lang == 'en'
  local function L(uk, e) return en and e or uk end
  local info, out = rec.info, {}
  local kind = L(t.uk, t.en)
  local name = en and (info.en or translit.latin(rec.label)) or rec.label
  out[1] = {cut(name or kind, 70), 'title'}
  if name then out[#out + 1] = {kind, 'kind'} end
  for _, line in ipairs(M.wrap(L(t.textUk, t.textEn), M.WRAP)) do out[#out + 1] = {line, 'text'} end
  local facts, have = {}, {}
  local function fact(key, label, value)
    if value and value ~= '' and not have[key] then
      have[key] = true
      facts[#facts + 1] = label .. ': ' .. cut(value, 90)
    end
  end
  local ele = poi.metres(rec.ele)
  fact('ele', L('Висота над рівнем моря', 'Elevation'), ele and string.format(L('%d м', '%d m'), math.floor(ele + .5)))
  fact('start_date', L('Рік', 'Year'), info.year)
  local tall = poi.metres(info.tall)
  fact('height', L('Висота споруди', 'Height'), tall and string.format(L('%g м', '%g m'), tall))
  fact('by', L('Автор', 'By'), en and translit.latin(info.by) or info.by)
  for _, kv in ipairs(details or {}) do
    local key, value = kv[1], kv[2]
    if key == 'start_date' then fact(key, L('Рік', 'Year'), poi.year(value) or value)
    elseif key == 'ele' and poi.metres(value) then fact(key, L('Висота над рівнем моря', 'Elevation'), string.format(L('%d м', '%d m'), math.floor(poi.metres(value) + .5)))
    elseif key == 'height' and poi.metres(value) then fact(key, L('Висота споруди', 'Height'), string.format(L('%g м', '%g m'), poi.metres(value)))
    elseif key == 'heritage' then fact(key, L('Пам\'ятка спадщини', 'Heritage'), L('так', 'yes'))
    elseif key == 'religion' then fact(key, L('Релігія', 'Religion'), value)
    elseif key == 'wikipedia' and not info.wiki then info.wiki = value
    elseif key == 'description' and not info.note then info.note = value
    elseif key == 'description:en' then info.noteEn = value end
  end
  if info.heritage then fact('heritage', L('Пам\'ятка спадщини', 'Heritage'), L('так', 'yes')) end
  fact('wikipedia', L('Вікіпедія', 'Wikipedia'), info.wiki and info.wiki:gsub('^%a%a%a?:', ''))
  for _, line in ipairs(facts) do out[#out + 1] = {line, 'fact'} end
  -- OSM's own words: in English its English ones, and none in a script an English reader cannot read
  local note = info.note
  if en then note = info.noteEn or (note and not note:find('[\208\209\210]') and note) or nil end
  if note then
    for _, line in ipairs(M.wrap('«' .. cut(note, M.NOTE) .. '»', M.WRAP)) do out[#out + 1] = {line, 'fact'} end
  end
  if isNew then
    out[#out + 1] = {string.format(L('Нове місце в журналі · знайдено %d', 'New in your journal · %d found'), found), 'new'}
  else
    out[#out + 1] = {L('Ви тут уже були', 'You have been here'), 'old'}
  end
  return out
end

-- tiles: the streamed tiles (each with .brandPOIs); x, y: the car; speed in m/s; env.lang;
-- env.details(rec) -> the sidecar's facts or nil; env.found(t) is called when the journal grows
function M.step(t, x, y, speed, tiles, env)
  local lang = env and env.lang or 'uk'
  local cur = t.rec
  if cur then
    local d2 = (cur.x - x) ^ 2 + (cur.y - y) ^ 2
    if d2 > M.KEEP * M.KEEP or speed > M.SPEED * 1.2 or not t.tile or tiles[t.tileKey] ~= t.tile then cur = nil end
  end
  if speed <= M.SPEED then
    local best, bestD = nil, M.RANGE * M.RANGE
    if cur then bestD = math.min(bestD, ((cur.x - x) ^ 2 + (cur.y - y) ^ 2) * .6) end   -- a nearer one must be clearly nearer
    for key, tile in pairs(tiles) do
      local list = tile.brandPOIs
      if list then
        for i = 1, #list do
          local rec = list[i]
          if rec.info and rec ~= cur then
            local d2 = (rec.x - x) ^ 2 + (rec.y - y) ^ 2
            if d2 < bestD and M.described(rec) then best, bestD, t.tile, t.tileKey = rec, d2, tile, key end
          end
        end
      end
    end
    if best then cur = best end
  end
  if cur ~= t.rec or (cur and t.lang ~= lang) then
    t.rec, t.lang, t.card = cur, lang, nil
    if cur then
      t.type = M.described(cur)
      t.new = not t.seen[tostring(cur.id)]
      t.card = M.lines(cur, t.type, lang, t.new, t.found + (t.new and 1 or 0), env and env.details and env.details(cur) or nil)
    end
  end
  -- found: the car came up to it and slowed down
  if cur and t.new and not t.seen[tostring(cur.id)] and speed <= M.VISIT_SPEED
      and (cur.x - x) ^ 2 + (cur.y - y) ^ 2 <= M.VISIT * M.VISIT then
    t.seen[tostring(cur.id)], t.found = true, t.found + 1
    if env and env.found then env.found(t, cur) end
  end
  return t.card
end

-- The card at the foot of the screen, centred; group colours from pins.lua. One set of ImVec2 for
-- the session (each is an engine object).
local look
function M.draw(im, t, pins)
  local card = t.card
  if not card then return end
  local view = im.GetMainViewport()
  if not view then return end
  local v = look
  if not v then
    v = {pos = im.ImVec2(0, 0), pivot = im.ImVec2(.5, 1), pad = im.ImVec2(16, 10), a = im.ImVec2(0, 0), b = im.ImVec2(0, 0),
      back = im.ImVec4(.08, .09, .11, .82), title = im.ImVec4(.98, .98, .99, 1), kind = im.ImVec4(.72, .78, .86, 1),
      text = im.ImVec4(.93, .93, .94, 1), fact = im.ImVec4(.74, .77, .82, 1), new = im.ImVec4(.98, .82, .32, 1),
      old = im.ImVec4(.55, .6, .66, 1), bars = {},
      flags = im.WindowFlags_NoDecoration + im.WindowFlags_NoInputs + im.WindowFlags_NoNav + im.WindowFlags_NoSavedSettings
        + im.WindowFlags_NoFocusOnAppearing + im.WindowFlags_NoBringToFrontOnFocus + im.WindowFlags_AlwaysAutoResize + im.WindowFlags_NoDocking}
    look = v
  end
  v.pos.x, v.pos.y = view.Pos.x + view.Size.x / 2, view.Pos.y + view.Size.y - 96
  im.SetNextWindowPos(v.pos, im.Cond_Always, v.pivot)
  im.PushStyleColor2(im.Col_WindowBg, v.back)
  im.PushStyleVar1(im.StyleVar_WindowRounding, 10)
  im.PushStyleVar1(im.StyleVar_WindowBorderSize, 0)
  im.PushStyleVar2(im.StyleVar_WindowPadding, v.pad)
  im.Begin('EarthNG##poicard', nil, v.flags)
  -- a bar of the group's colour down the card's left edge
  local group = t.type and t.type.group
  local g = pins and pins.GROUP and pins.GROUP[group]
  if g then
    local bar = v.bars[group]
    if not bar then bar = im.GetColorU322(im.ImVec4(g[1], g[2], g[3], 1)); v.bars[group] = bar end
    local at, size = im.GetWindowPos(), im.GetWindowSize()
    v.a.x, v.a.y, v.b.x, v.b.y = at.x, at.y + 8, at.x + 5, at.y + size.y - 8
    im.ImDrawList_AddRectFilled(im.GetWindowDrawList(), v.a, v.b, bar, 2)
  end
  for i = 1, #card do
    local line = card[i]
    if line[2] == 'title' then im.SetWindowFontScale(1.25) end
    im.PushStyleColor2(im.Col_Text, v[line[2]] or v.text)
    im.TextUnformatted(line[1])
    im.PopStyleColor(1)
    if line[2] == 'title' then im.SetWindowFontScale(1) end
  end
  im.End()
  im.PopStyleVar(3)
  im.PopStyleColor(1)
end

return M
