-- What a point of interest is (docs/POI.md "Енциклопедія"): the type of a pin from its OSM tags
-- (poi_lib.lua, written by earthng/poi_art.py from poi_types.py), the mark of that type in the
-- atlas, and the facts OSM gives about this one point. The generator draws from it (an info stand,
-- a plaque, a blade sign: BLD.poiInfo), the card by the car reads from it (poicard.lua).
local M = {}

do
  local ok, lib = pcall(require, 'ge/extensions/e2r/poi_lib')
  M.lib = ok and type(lib) == 'table' and lib.types and lib or {per = 8, keys = {}, groups = {}, category = {}, types = {}}
end

-- the types by tag key and value, and by category: a lookup makes no string (a tile asks for every
-- pin, twice)
local byKey, byCat = {}, {}
for key, t in pairs(M.lib.types) do
  local k, v = key:match('^([^=]+)=(.+)$')
  if k then
    byKey[k] = byKey[k] or {}
    byKey[k][v] = {key, t}
  elseif key:sub(1, 4) == 'cat:' then
    byCat[key:sub(5)] = {key, t}
  end
end
for cat, key in pairs(M.lib.category) do
  if M.lib.types[key] then byCat[cat] = {key, M.lib.types[key]} end
end

-- the type of a pin's tags: (key, type) by the first of lib.keys that names one, else by its
-- category (a pack built before the kind keys were kept); nil when the library knows neither
function M.typeOf(tags)
  local keys = M.lib.keys
  for i = 1, #keys do
    local value = tags[keys[i]]
    if value then
      local hit = byKey[keys[i]]
      hit = hit and hit[value]
      if hit then return hit[1], hit[2] end
    end
  end
  local hit = byCat[tags.e2r_cat or '']
  if hit then return hit[1], hit[2] end
  return nil
end

-- the uv box of a mark's cell: u0, v0, u1, v1 with v upward (the atlas is flipped like the glyphs)
function M.uv(cell)
  local per = M.lib.per
  local col, row = cell % per, math.floor(cell / per)
  return col / per, 1 - (row + 1) / per, (col + 1) / per, 1 - row / per
end

-- the year in an OSM date ('1654', '1654-05-01', 'C17' gives none)
function M.year(text)
  local year = tostring(text or ''):match('^%s*~?(%d%d%d%d)')
  return year
end

local function metres(text)
  local n = tonumber((tostring(text or ''):gsub(',', '.'):match('^%s*(%-?%d+%.?%d*)')))
  return n
end
M.metres = metres

-- What a stand says of this point without a word of ours: its height above the sea, the year it
-- dates from. Short strings in the glyphs' letters.
function M.facts(tags)
  local out = {}
  local ele = metres(tags.ele)
  if ele then out[#out + 1] = string.format('%d m', math.floor(ele + .5)) end
  local year = M.year(tags.start_date)
  if year then out[#out + 1] = year end
  return out
end

-- The record a tile hands to the card for a pin (generator.lua SPLIT.out): its type and the facts
-- kept in the pack; nil for a point whose type the library has no text for (a shop, a car park).
function M.record(tags)
  local key, t = M.typeOf(tags)
  if not t or not t.textUk then return nil end
  return {type = key, year = M.year(tags.start_date), tall = tags.height, wiki = tags.wikipedia,
    note = tags.description or tags.inscription, en = tags['name:en'], by = tags.architect or tags.artist_name,
    noteEn = tags['description:en'] or tags['inscription:en'],
    heritage = tags.heritage}
end

return M
