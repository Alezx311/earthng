-- Road signs by country (docs/SIGNS.md, "Знаки за країною"). The game's sign set is Italian, and
-- most of Europe reads the same Vienna Convention faces; where a country's signs look otherwise
-- the generator draws them itself (generator.lua SIGNS.drawn*). Which country a tile is in comes
-- from the pack's id (Geofabrik's names: 'us-new-york', 'kyiv-oblast'), else from lat/lon boxes
-- (a spot pack, 'spot-london'), else from the pack's look.
local M = {}

-- ISO code by the words of a pack id: the whole id first, then its first word
M.IDS = {
  US = 'us united-states usa new-york california nevada kentucky indiana ohio us-midwest us-northeast us-pacific us-south us-west',
  CA = 'canada ontario quebec alberta british-columbia manitoba saskatchewan nova-scotia new-brunswick '
    .. 'newfoundland-and-labrador prince-edward-island yukon northwest-territories nunavut',
  GB = 'united-kingdom great-britain england scotland wales uk greater-london isle-of-man guernsey-jersey britain',
  IE = 'ireland ireland-and-northern-ireland',
  SE = 'sweden', FI = 'finland', IS = 'iceland', NO = 'norway', DK = 'denmark', PL = 'poland',
  DE = 'germany', FR = 'france', NL = 'netherlands', BE = 'belgium', AT = 'austria', CH = 'switzerland',
  IT = 'italy', ES = 'spain', PT = 'portugal', GR = 'greece', CZ = 'czech-republic', SK = 'slovakia',
  UA = 'ukraine kyiv kyiv-oblast crimea', RU = 'russia moscow moscow-oblast central-fed-district', BY = 'belarus',
  EE = 'estonia', LV = 'latvia', LT = 'lithuania', RO = 'romania', AL = 'albania',
  AU = 'australia australia-oceania', NZ = 'new-zealand', JP = 'japan',
  BR = 'brazil sudeste sul nordeste norte centro-oeste', MX = 'mexico', AR = 'argentina', CL = 'chile',
  ZA = 'south-africa', TZ = 'tanzania zanzibar',
}
local byId
local function idTable()
  if byId then return byId end
  byId = {}
  for iso, words in pairs(M.IDS) do
    for id in words:gmatch('%S+') do byId[id] = iso end
  end
  return byId
end

-- {iso, west, south, east, north}: the smaller and the more particular first (Northern Ireland
-- before Ireland, both before Britain)
M.BOXES = {
  {'GB', -8.2, 54.0, -5.4, 55.35}, {'IE', -10.7, 51.3, -5.9, 55.5}, {'GB', -8.7, 49.8, 1.9, 60.9},
  {'IS', -24.6, 63.2, -13.4, 66.6}, {'NL', 3.3, 50.75, 7.25, 53.6}, {'BE', 2.5, 49.5, 6.4, 51.5},
  {'CH', 5.95, 45.8, 10.5, 47.8}, {'AT', 9.5, 46.4, 17.2, 49.0}, {'DK', 8.0, 54.5, 15.2, 57.8},
  {'CZ', 12.1, 48.55, 18.9, 51.06}, {'PL', 14.1, 49.0, 24.15, 54.9}, {'DE', 5.85, 47.27, 15.05, 55.1},
  {'PT', -9.6, 36.9, -6.2, 42.2}, {'ES', -9.4, 36.0, 3.4, 43.8}, {'FR', -5.2, 41.3, 9.6, 51.1},
  {'IT', 6.6, 36.6, 18.6, 47.1}, {'GR', 19.3, 34.8, 28.3, 41.8},
  {'SE', 11.0, 55.3, 24.2, 69.1}, {'FI', 20.0, 59.7, 31.6, 70.1}, {'NO', 4.5, 57.9, 31.1, 71.2},
  {'EE', 21.7, 57.5, 28.2, 59.7}, {'UA', 22.1, 44.3, 40.3, 52.4}, {'RU', 27.0, 41.0, 180, 82},
  {'US', -125, 24.5, -66.9, 49.4}, {'US', -170, 51, -129, 71.5}, {'US', -161, 18.8, -154.7, 22.3},
  {'CA', -141, 41.6, -52.6, 83.1}, {'MX', -118.4, 14.5, -86.7, 32.7},
  {'AU', 112, -44, 154, -10}, {'NZ', 166, -47.5, 179, -34}, {'JP', 129, 30, 146, 46},
  {'BR', -74, -34, -34.8, 5.3}, {'AR', -73.6, -55.1, -53.6, -21.8}, {'CL', -75.7, -56, -66.4, -17.5},
  {'ZA', 16.4, -34.9, 32.9, -22.1},
}

-- The faces, by country:
--   warn: 'triangle' (the game's), 'yellow' (a yellow triangle, drawn), 'diamond' (a yellow
--     diamond, drawn); limit: 'disc' (the game's 30-100, the rest drawn), 'yellow' (a yellow disc),
--     'uk' (a roundel without units, miles), 'us' (SPEED LIMIT board), 'ca' (MAXIMUM board);
--   us: the MUTCD regulatory set (YIELD, DO NOT ENTER, ONE WAY, DO NOT PASS, no priority road);
--   town and blade: board and letter colours (materials); exitBlue: a motorway's exits on blue
--   boards (else green); allGreen: every road's guide signs green.
local DEFAULT = {warn = 'triangle', limit = 'disc', town = {'sign_white', 'glyphs_dark'}, blade = {'plate', 'glyphs'},
  exitBlue = true}
M.DEFAULT = DEFAULT
local function family(base)
  local out = {}
  for k, v in pairs(DEFAULT) do out[k] = v end
  for k, v in pairs(base) do out[k] = v end
  return out
end
local GREEN_BOARD, BLUE_BOARD = {'sign_green', 'glyphs', 'glyphs'}, {'sign_blue', 'glyphs'}
local WHITE_BLADE = {'sign_white', 'glyphs_dark'}
M.FAMILIES = {
  US = family({warn = 'diamond', limit = 'us', us = true, town = GREEN_BOARD, blade = GREEN_BOARD, exitBlue = false, allGreen = true}),
  CA = family({warn = 'diamond', limit = 'ca', us = true, town = GREEN_BOARD, blade = GREEN_BOARD, exitBlue = false, allGreen = true}),
  MX = family({warn = 'diamond', exitBlue = false}),
  GB = family({limit = 'uk', blade = WHITE_BLADE}),
  IE = family({warn = 'diamond', blade = WHITE_BLADE}),
  SE = family({warn = 'yellow', limit = 'yellow', blade = WHITE_BLADE}),
  FI = family({warn = 'yellow', limit = 'yellow', blade = WHITE_BLADE, exitBlue = false}),
  IS = family({warn = 'yellow'}),
  PL = family({warn = 'yellow'}),
  DE = family({town = {'sign_yellow', 'glyphs_dark'}, blade = WHITE_BLADE}),
  AT = family({blade = WHITE_BLADE, exitBlue = false}),
  CH = family({blade = WHITE_BLADE, exitBlue = false}),
  FR = family({town = {'sign_white', 'glyphs_dark', 'paint_red'}, blade = BLUE_BOARD}),
  NL = family({town = BLUE_BOARD, blade = WHITE_BLADE}),
  IT = family({town = {'sign_white', 'glyphs_dark', 'glyphs_dark'}, exitBlue = false}),
  AU = family({warn = 'diamond', exitBlue = false, allGreen = true}),
  NZ = family({warn = 'diamond', exitBlue = false, allGreen = true}),
  JP = family({warn = 'diamond', exitBlue = false, allGreen = true}),
  BR = family({warn = 'diamond', exitBlue = false, allGreen = true}),
  AR = family({warn = 'diamond'}),
  CL = family({warn = 'diamond'}),
}

-- the ISO code of a pack id, or of a point when the id says nothing
function M.country(id, lat, lon)
  local ids = idTable()
  id = tostring(id or ''):lower()
  local iso = ids[id] or ids[id:match('^[^-]+') or '']
  if iso then return iso end
  -- a spot or a section: 'spot-london', 'uk-wales' (its first word above), 'europe-italy'
  for word in id:gmatch('[^-]+') do
    if ids[word] then return ids[word] end
  end
  if type(lat) == 'number' and type(lon) == 'number' then
    for _, b in ipairs(M.BOXES) do
      if lon >= b[2] and lon <= b[4] and lat >= b[3] and lat <= b[5] then return b[1] end
    end
  end
  return nil
end

-- The family of the signs: by country, a North American look without one
function M.family(id, look, lat, lon)
  local iso = M.country(id, lat, lon)
  local f = iso and M.FAMILIES[iso]
  if not f and type(look) == 'table' then
    if look.block == 'north-america' then f = M.FAMILIES.US
    elseif look.block == 'british' then f = M.FAMILIES.GB end
  end
  return f or DEFAULT, iso
end

return M
