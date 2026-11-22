-- Universes: a place rebuilt by another world's rules. A texture pack repaints the materials
-- there are; a universe decides which climate the land has, which region's walls and props
-- stand on it, what its roads, roofs and open ground are made of and what the tyres feel.
-- The same OSM facts come out as a mountain town, a desert one, one under deep snow or one in
-- deep mud. The lab (lab.lua) names a universe for the world or for one tile; a pack may name
-- one for a tile of its own (the proving ground's four corners of the island).
--
-- A universe is a table of rules, each optional:
--   climate  {class = Köppen 1..30, treeline = m, snowline = m}: biome.lua forced()
--   look     slots of the pack's look (looks.py): block, asphalt, markings, verge, ...
--   tune     generator.lua TUNE fields
--   option   fields of generator.build's options (densities, land = false)
--   swap     {kind = kind | false}: a surface drawn with another material, or not drawn
--   patterns {{lua pattern, kind | false}}: the same for families of kinds (every roof)
--   feel     true: the invisible ground the car stands on takes the drawn land's physics
--   flora    a zone of flora.lua: the woods, shrubs and herbs that grow, whatever the place
-- An explicit knob of the lab wins over the universe's value of the same thing.
-- Pure Lua (earthng/test_universe.py).
local M = {}

M.order = {'mountains', 'desert', 'snow', 'mud', 'jungle'}

-- every asphalt and paving the generator lays, by family
local PAVED = {'^road$', '^road_major$', '^road_worn$', '^road_.*lane$', '^road_sett$', '^road_broken$'}
local UNPAVED = {'^road_gravel$', '^road_dirt$', '^road_track$', '^footway$', '^trodden$'}
local ROOFS = {'^roof', '^sh_roof', '^kw_bitumen$'}
-- the open land's sheets and the pairs they pass into one another by (fast_style LANDS)
local LANDS = {'^ground$', '^meadow$', '^grass_dry$', '^grass_lush$', '^earth$', '^fade_', '^cut_'}

local function rules(to, ...)
  local out = {}
  for _, family in ipairs({...}) do
    for _, pattern in ipairs(family) do out[#out + 1] = {pattern, to} end
  end
  return out
end

local function join(...)
  local out = {}
  for _, list in ipairs({...}) do
    for _, rule in ipairs(list) do out[#out + 1] = rule end
  end
  return out
end

M.list = {
  -- A range with every belt on one slope: a boreal valley, the tree line at 420 m, scree and
  -- rock over it, snow from 900 m. (The real lines of this latitude stand at 1600 and 2700 m:
  -- a massif that high needs twenty kilometres.) Central European walls and roofs.
  mountains = {label = {uk = 'Гори', en = 'Mountains'},
    about = {uk = 'Усі пояси на одному схилі: тайга в долині, вище межі лісу осип і скеля, ще вище сніг.',
      en = 'Every belt on one slope: boreal forest in the valley, scree and rock over the tree line, snow above.'},
    climate = {class = 27, treeline = 420, snowline = 900},
    look = {block = 'central', verge = 'gravel'},
    feel = true},
  -- A hot desert: bare ground, dunes where sand is mapped, palms in the towns, no grass edge
  -- on a road. Walls and roofs of the Middle East.
  desert = {label = {uk = 'Пустеля', en = 'Desert'},
    about = {uk = 'Спекотна пустеля: гола земля, дюни там, де на мапі пісок, пальми в містах, край дороги без трави.',
      en = 'A hot desert: bare ground, dunes where sand is mapped, palms in the towns, no grass at the road edge.'},
    climate = {class = 4},
    look = {block = 'middle-east', verge = 'dirt', asphalt = 'worn'},
    swap = {edge_grass = 'edge_dirt'},
    feel = true},
  -- Deep snow: the snow line under the sea, so every natural ground is snow, with the boreal
  -- forest standing in it. Roads are packed snow, sidewalks, fields and roofs lie under it,
  -- paint and cracks are not seen. Nordic walls.
  snow = {label = {uk = 'Сніг', en = 'Snow'},
    about = {uk = 'Глибокий сніг: уся природна земля під снігом, ліс стоїть. Дороги з накатаного снігу, тротуари, поля й дахи засипані, розмітки й тріщин не видно.',
      en = 'Deep snow: all natural ground is snow, the forest stands in it. Roads are packed snow, sidewalks, fields and roofs lie under it, paint and cracks are not seen.'},
    climate = {class = 27, snowline = -3000},
    look = {block = 'nordic', markings = 'none'},
    tune = {lanes = 0, wear = 0},
    swap = {sidewalk = 'snow', sidewalk_tile = 'snow', sidewalk_asphalt = 'snow', footway_asphalt = 'snow',
      paved = 'snow_edge', ballast = 'snow_edge', beach = 'snow', wetland = 'snow', orchard = 'snow', vineyard = 'snow',
      bare_ground = 'snow',
      mark = false, mark_yellow = false, edge_grass = false, edge_dirt = false, track = false,
      crack_net = false, crack_line = false, wear = false},
    patterns = join(rules('snow_edge', PAVED, UNPAVED), rules('snow', ROOFS, {'^farmland'}), rules(false, {'^ruts_'})),
    option = {maxGrass = 0, maxRocks = 0},
    feel = true},
  -- Deep mud: the open land, the fields and every unpaved road are mud a car sinks in; the
  -- asphalt stays, its edges are dirt. The climate and the region are the place's own.
  mud = {label = {uk = 'Багно', en = 'Mud'},
    about = {uk = 'Глибоке багно: відкрита земля, поля й ґрунтові дороги стають багном, у якому в’язне авто. Асфальт лишається, його краї ґрунтові. Клімат і регіон свої.',
      en = 'Deep mud: open land, fields and unpaved roads become mud a car sinks in. Asphalt stays, its edges are dirt. The climate and the region are the place\'s own.'},
    look = {verge = 'dirt', asphalt = 'worn'},
    swap = {bare_ground = 'mud', edge_grass = 'edge_dirt', beach = 'mud'},
    patterns = join(rules('mud', LANDS, UNPAVED, {'^farmland'})),
    option = {maxGrass = 300, land = false},
    feel = true},
  -- A rainforest: the wet tropics' climate, and its plants where the flora pack has them (the
  -- canopy, palms, bananas and tree ferns under it, lianas, the big leaves of the floor); the
  -- climate's old sets without the pack. Walls and roofs of South-East Asia, earth at the
  -- road's edge.
  jungle = {label = {uk = 'Джунглі', en = 'Jungle'},
    about = {uk = 'Дощовий ліс: клімат вологих тропіків і його рослини, де їх має пак флори. Край дороги ґрунтовий.',
      en = 'A rainforest: the climate of the wet tropics and its plants where the flora pack has them. Earth at the road edge.'},
    climate = {class = 1},
    flora = 'tropics',
    look = {block = 'southeast-asia', verge = 'dirt'},
    swap = {edge_grass = 'edge_dirt'},
    feel = true},
}

-- Climates by name, for the lab's own knob: one table a name (biome.lua caches by the table).
local CLIMATES = {rainforest = 1, savanna = 3, desert = 4, steppe = 7, mediterranean = 8, temperate = 15,
  boreal = 27, tundra = 29, ice = 30}
M.climates = {'rainforest', 'savanna', 'desert', 'steppe', 'mediterranean', 'temperate', 'boreal', 'tundra', 'ice'}
local climateSpecs = {}
function M.climate(name)
  local class = CLIMATES[name]
  if not class then return nil end
  local spec = climateSpecs[name]
  if not spec then spec = {class = class}; climateSpecs[name] = spec end
  return spec
end

function M.get(id) return M.list[id] end

-- kind -> the kind to draw (itself when no rule names it) or false to leave it out; the answer
-- for a kind is found once
function M.swapper(u)
  if u.swapFn ~= nil then return u.swapFn or nil end
  if not u.swap and not u.patterns then
    u.swapFn = false
    return nil
  end
  local memo, exact, patterns = {}, u.swap or {}, u.patterns or {}
  u.swapFn = function(kind)
    local to = memo[kind]
    if to == nil then
      to = exact[kind]
      if to == nil then
        for k = 1, #patterns do
          if kind:find(patterns[k][1]) then to = patterns[k][2]; break end
        end
      end
      if to == nil then to = kind end
      memo[kind] = to
    end
    return to
  end
  return u.swapFn
end

-- a pack's look with a universe's slots over it (the pack's own table is never changed)
function M.look(u, look)
  if not u.look then return look end
  local cache = u.looks
  if not cache then cache = setmetatable({}, {__mode = 'k'}); u.looks = cache end
  local key = type(look) == 'table' and look or M
  local out = cache[key]
  if not out then
    out = {}
    for k, v in pairs(type(look) == 'table' and look or {}) do out[k] = v end
    for k, v in pairs(u.look) do out[k] = v end
    cache[key] = out
  end
  return out
end

-- A universe's rules for a reader (the proving ground's page): {id, label, about, climate =
-- {class, name, treeline, snowline}, look = {slot = value}, tune = {...}, option = {...},
-- swaps = {{from, to}} sorted (to false: not drawn), patterns = how many families are swapped
-- by pattern, feel, flora}. Plain tables built on demand; nil for an unknown id.
function M.describe(id)
  local u = M.list[id]
  if not u then return nil end
  local out = {id = id, label = u.label, about = u.about, feel = u.feel and true or false, flora = u.flora}
  if u.climate then
    local name
    for key, class in pairs(CLIMATES) do if class == u.climate.class then name = key end end
    out.climate = {class = u.climate.class, name = name, treeline = u.climate.treeline, snowline = u.climate.snowline}
  end
  for _, field in ipairs({'look', 'tune', 'option'}) do
    if u[field] then
      local copy = {}
      for k, v in pairs(u[field]) do copy[k] = v end
      out[field] = copy
    end
  end
  local swaps = {}
  for from, to in pairs(u.swap or {}) do swaps[#swaps + 1] = {from, to} end
  table.sort(swaps, function(a, b) return a[1] < b[1] end)
  out.swaps, out.patterns = swaps, u.patterns and #u.patterns or 0
  return out
end

-- {id, uk, en} of every universe, in order: the lab's choices
function M.choices()
  local out = {}
  for _, id in ipairs(M.order) do
    local u = M.list[id]
    out[#out + 1] = {id, u.label.uk, u.label.en}
  end
  return out
end

return M
