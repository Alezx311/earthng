-- Which plants grow where: the real species of a region, by its natural zones.
--
-- The generator knew three broadleaf models and two conifers and drew each tree's model by a
-- hash, so every wood from the Polissia to the Carpathians was the same even salt-and-pepper of
-- oak, beech and aspen. A real wood is stands: a pinewood with a birch grove in it, an oak and
-- hornbeam wood, an alder carr along the stream, and which of them it is depends on where it is.
-- This module answers that for Ukraine: the zone of a place (Polissia, forest-steppe, steppe, the
-- Carpathians by height, the Crimean mountains), the stand a point lies in (noise over a couple of
-- hundred metres: conifer or broadleaf where the map does not say, the stand's leading species,
-- its age) and the tree itself (the leading species mostly, the zone's other species among it).
--
-- A species is drawn with its own models where the flora pack has them (FoliMesh models built by
-- earthng/build_flora.py: /art/shapes/earthng/flora/flora.json lists them with their heights)
-- and with the game's stock trees that stand in for it otherwise, so the mod works without the
-- pack. A tree is asked for by height: the model nearest to it is taken and scaled to it.
--
-- The compositions are from the forestry of Ukraine's natural zones (the leading and attendant
-- species of its forest types). They are rules over the place and the map's leaf type, not a
-- surveyed map of stands.
local M = {}
local floor, min, max, abs = math.floor, math.min, math.max, math.abs

M.MANIFEST = '/art/shapes/earthng/flora/flora.json'
M.enabled = true

local ECA = '/levels/east_coast_usa/art/shapes/trees/'
local ITA = '/levels/italy/art/shapes/trees/trees_italy/'
local UT = '/levels/Utah/art/shapes/trees/Juniper/'
local OAK, BEECH, ASPEN, FIR = ECA .. 'trees_oak/tree_oak_', ECA .. 'trees_beech/tree_beech_', ECA .. 'trees_aspen/tree_aspen_',
  ECA .. 'trees_douglasfir/tree_douglasfir_'
local function S(shape, height) return {shape = shape .. '.dae', height = height} end

-- The stock models that stand in for a species: {shape, height above the ground in metres}
-- (measured from the installed .dae). A model is used from .6 to 1.1 of its own size: scaled
-- up, the stock pine's trunk (64 cm through as it is) stood as thick as a sequoia's (flora-02).
local STOCK = {
  oak = {S(OAK .. 'forest_a', 15.3), S(OAK .. 'forest_b', 15.3), S(OAK .. 'large_b', 15.5), S(OAK .. 'large_c', 14.4),
    S(OAK .. 'large_a', 12.1), S(OAK .. 'sml_b', 9), S(OAK .. 'sml_a', 8.2)},
  beech = {S(BEECH .. 'forest_a', 19.7), S(BEECH .. 'forest_b', 20.7), S(BEECH .. 'large_b', 20.3), S(BEECH .. 'large_c', 16.8),
    S(BEECH .. 'small_b', 11.2), S(BEECH .. 'small_c', 9.4)},
  hornbeam = {S(BEECH .. 'large_c', 16.8), S(BEECH .. 'small_d', 11.2), S(BEECH .. 'small_b', 11.2), S(BEECH .. 'small_c', 9.4)},
  linden = {S(BEECH .. 'large_b', 20.3), S(OAK .. 'large_b', 15.5), S(OAK .. 'large_a', 12.1), S(OAK .. 'sml_b', 9)},
  maple = {S(OAK .. 'forest_b', 15.3), S(BEECH .. 'large_c', 16.8), S(BEECH .. 'small_d', 11.2), S(OAK .. 'sml_a', 8.2)},
  ash = {S(ASPEN .. 'forest_b', 17.9), S(OAK .. 'forest_a', 15.3), S(ASPEN .. 'large_b', 9.7)},
  elm = {S(OAK .. 'forest_b', 15.3), S(OAK .. 'large_c', 14.4), S(OAK .. 'sml_b', 9)},
  alder = {S(ASPEN .. 'forest_a', 15), S(BEECH .. 'small_b', 11.2), S(ASPEN .. 'large_a', 9.7)},
  birch = {S(ASPEN .. 'forest_b', 17.9), S(ASPEN .. 'forest_a', 15), S(ASPEN .. 'large_b', 9.7), S(ASPEN .. 'large_a', 9.7),
    S(ASPEN .. 'small_c', 7.3), S(ASPEN .. 'small_a', 5.9)},
  aspen = {S(ASPEN .. 'forest_b', 17.9), S(ASPEN .. 'forest_a', 15), S(ASPEN .. 'small_d', 7.7), S(ASPEN .. 'small_b', 5.8)},
  -- the aspen, its own genus: the game's poplars have billboards baked in autumn yellow, and a
  -- stand or a row of them was a yellow grove from the air (flora-06). The generator still
  -- plants one of those in ten crowns of a mapped row, as before.
  poplar = {S(ASPEN .. 'forest_b', 17.9), S(ASPEN .. 'forest_a', 15), S(ASPEN .. 'large_b', 9.7)},
  willow = {S(BEECH .. 'overhang_a', 12.5), S(BEECH .. 'large_c', 16.8), S(OAK .. 'large_a', 12.1)},
  rowan = {S(ASPEN .. 'small_low', 5.5), S(OAK .. 'sml_a', 8.2)},
  chestnut = {S(OAK .. 'large_b', 15.5), S(OAK .. 'large_a', 12.1), S(BEECH .. 'large_c', 16.8)},
  walnut = {S(OAK .. 'large_a', 12.1), S(OAK .. 'sml_b', 9)},
  fruit = {S(OAK .. 'sml_a', 8.2), S(BEECH .. 'small_c', 9.4), S(ASPEN .. 'small_low', 5.5)},
  pine = {S(ITA .. 'scots_pine', 17.4), S(ITA .. 'scots_pine_filler', 13.1)},
  spruce = {S(FIR .. 'large_b', 21.1), S(FIR .. 'large_d', 21.3), S(FIR .. 'large_a', 19.4), S(FIR .. 'small_a', 12.8),
    S(FIR .. 'small_c', 7.6)},
  fir = {S(FIR .. 'large_c', 18.7), S(FIR .. 'large_a', 19.4), S(FIR .. 'small_b', 10.9), S(FIR .. 'small_d', 4.7)},
  larch = {S(FIR .. 'large_c', 18.7), S(FIR .. 'small_a', 12.8)},
  thuja = {S(ITA .. 'cypress_tree', 7)},
  cypress = {S(ITA .. 'cypress_tree', 7)},
  dead = {S(OAK .. 'dead_a', 11.5), S(OAK .. 'dead_b', 8.4), S(FIR .. 'dead', 4.1)},
  -- the shrub layer
  hazel = {S(BEECH .. 'bush_e', 6.1), S(BEECH .. 'bush_d', 6.3), S(BEECH .. 'bush_c', 3.3), S(BEECH .. 'bush_b', 3.1)},
  elder = {S(OAK .. 'bush_b', 4), S(OAK .. 'bush_c', 3), S(ASPEN .. 'bush_c', 3.2)},
  hawthorn = {S(OAK .. 'bush_c', 3), S(ECA .. 'ECA_coast_bush/generibush_small', 1.4)},
  rose = {S(ECA .. 'ECA_coast_bush/generibush_small', 1.4), S(ECA .. 'ECA_coast_bush/generibush', 1.4)},
  raspberry = {S(BEECH .. 'bush_a', 1.1), S(OAK .. 'bush_a', 1.3)},
  lilac = {S(OAK .. 'bush_b', 4), S(BEECH .. 'bush_b', 3.1)},
  juniper = {S(UT .. 'Juniper_bush_medium_01', 2.3), S(UT .. 'Juniper_bush_large_01', 2.3), S(UT .. 'Juniper_bush_small_02', 1.9)},
  bush = {S(BEECH .. 'bush_b', 3.1), S(OAK .. 'bush_c', 3), S(ASPEN .. 'bush_b', 2.3), S(ASPEN .. 'bush_a', 1.9)},
  -- the young growth of a wood's own trees
  oak_young = {S(OAK .. 'bush_b', 4), S(OAK .. 'bush_c', 3), S(OAK .. 'bush_a', 1.3)},
  beech_young = {S(BEECH .. 'bush_d', 6.3), S(BEECH .. 'bush_e', 6.1), S(BEECH .. 'bush_c', 3.3), S(BEECH .. 'bush_a', 1.1)},
  birch_young = {S(ASPEN .. 'small_low', 5.5), S(ASPEN .. 'bush_c', 3.2), S(ASPEN .. 'bush_b', 2.3), S(ASPEN .. 'bush_a', 1.9)},
  pine_young = {S(ECA .. 'ECA_coast_bush/maritime_pine_bush', 4), S(ITA .. 'scots_pine_filler', 13.1)},
  spruce_young = {S(FIR .. 'small_d', 4.7), S(FIR .. 'bush_a', 2.5), S(FIR .. 'bush_b', 1.9)},
}
M.STOCK = STOCK

-- A species: its Latin name, the height a grown tree reaches in a closed wood (metres), whether
-- it is a conifer, and what stands in for it where it has no models of its own.
M.SPECIES = {
  oak = {latin = 'Quercus robur', height = 27},
  beech = {latin = 'Fagus sylvatica', height = 31},
  hornbeam = {latin = 'Carpinus betulus', height = 21},
  linden = {latin = 'Tilia cordata', height = 25},
  maple = {latin = 'Acer platanoides', height = 24},
  ash = {latin = 'Fraxinus excelsior', height = 28},
  elm = {latin = 'Ulmus glabra', height = 24},
  alder = {latin = 'Alnus glutinosa', height = 22},
  birch = {latin = 'Betula pendula', height = 23},
  aspen = {latin = 'Populus tremula', height = 23},
  poplar = {latin = 'Populus nigra', height = 27},
  willow = {latin = 'Salix alba', height = 18},
  rowan = {latin = 'Sorbus aucuparia', height = 9},
  chestnut = {latin = 'Aesculus hippocastanum', height = 20},
  walnut = {latin = 'Juglans regia', height = 15},
  fruit = {latin = 'Prunus, Malus', height = 6.5},
  pine = {latin = 'Pinus sylvestris', height = 27, conifer = true},
  spruce = {latin = 'Picea abies', height = 32, conifer = true},
  fir = {latin = 'Abies alba', height = 33, conifer = true},
  larch = {latin = 'Larix decidua', height = 28, conifer = true},
  thuja = {latin = 'Thuja occidentalis', height = 8, conifer = true},
  cypress = {latin = 'Cupressus sempervirens', height = 14, conifer = true},
  dead = {latin = '', height = 12},
  hazel = {latin = 'Corylus avellana', height = 4.5, shrub = true},
  elder = {latin = 'Sambucus nigra', height = 3.5, shrub = true},
  hawthorn = {latin = 'Crataegus monogyna', height = 3.5, shrub = true},
  rose = {latin = 'Rosa canina', height = 1.8, shrub = true},
  raspberry = {latin = 'Rubus idaeus', height = 1.3, shrub = true},
  lilac = {latin = 'Syringa vulgaris', height = 3.5, shrub = true},
  juniper = {latin = 'Juniperus communis', height = 2.6, shrub = true, conifer = true},
  bush = {latin = 'Frangula alnus, Euonymus', height = 2.8, shrub = true},
  oak_young = {of = 'oak', height = 3.5, shrub = true},
  beech_young = {of = 'beech', height = 4.5, shrub = true},
  birch_young = {of = 'birch', height = 4, shrub = true},
  pine_young = {of = 'pine', height = 4, shrub = true, conifer = true},
  spruce_young = {of = 'spruce', height = 3.5, shrub = true, conifer = true},
}

-- --- models ------------------------------------------------------------------------------------

local models = nil       -- species -> {{shape, height, materials}}: the pack's, else the stock's
local exists = {}
local function have(shape)
  local found = exists[shape]
  if found == nil then
    found = true
    if FS then
      local ok, there = pcall(function() return FS:fileExists(shape) end)
      found = ok and there and true or false
    end
    exists[shape] = found
  end
  return found
end

-- The flora pack's manifest {species = {name = {models = {{shape, height, materials}}}}}, or nil.
function M.readManifest()
  if not FS or not jsonReadFile then return nil end
  local ok, data = pcall(function()
    if not FS:fileExists(M.MANIFEST) then return nil end
    return jsonReadFile(M.MANIFEST)
  end)
  return ok and type(data) == 'table' and type(data.species) == 'table' and data or nil
end

-- Use this manifest (tests; nil: read the pack's again at the next question).
function M.setManifest(manifest)
  M.manifest, M.manifestRead, models = manifest, manifest ~= nil, nil
end

local function load()
  if not M.manifestRead then
    M.manifest, M.manifestRead = M.readManifest(), true
  end
  models = {}
  local pack = M.manifest and M.manifest.species or {}
  for name in pairs(M.SPECIES) do
    local list = {}
    for _, model in ipairs(type(pack[name]) == 'table' and pack[name].models or {}) do
      if type(model.shape) == 'string' and tonumber(model.height) and have(model.shape) then
        list[#list + 1] = {shape = model.shape, height = tonumber(model.height), materials = model.materials, own = true}
      end
    end
    if #list == 0 then
      for _, model in ipairs(STOCK[name] or {}) do
        if have(model.shape) then list[#list + 1] = model end
      end
    end
    models[name] = list
  end
end

-- The models of a species here (its own, or the stock stand-ins this game has); may be empty.
function M.models(species)
  if not models then load() end
  return models[species] or {}
end

-- Has a species models of its own (the flora pack's), not the stock stand-ins?
function M.own(species)
  local list = M.models(species)
  return list[1] ~= nil and list[1].own == true
end

-- A plant of `species` about `height` m tall: shape, scale, the shape's material file (nil for a
-- stock shape) and the model's own height; nil when the species has no model here. h: the
-- plant's own hash (models of much the same fit are told apart by it).
function M.plant(species, height, h)
  local list = M.models(species)
  local n = #list
  if n == 0 then return nil end
  -- the models within a fifth of the best fit, one of them by the hash
  local best = 1e9
  for k = 1, n do
    local d = abs(math.log(height / list[k].height))
    if d < best then best = d end
  end
  local fit, count = {}, 0
  for k = 1, n do
    if abs(math.log(height / list[k].height)) <= best + .2 then count = count + 1; fit[count] = list[k] end
  end
  local model = fit[(h or 0) % count + 1]
  local lo, hi = .6, model.own and 1.3 or 1.1
  local scale = max(lo, min(hi, height / model.height))
  M.used[model.shape] = true
  return model.shape, scale, model.materials, model.height
end
-- every shape handed out since the level began (the world's warm-up reads it)
M.used = {}

-- --- noise -------------------------------------------------------------------------------------

local HMOD = 2147483647
local function knot(seed, a, b)
  local h = (seed * 1000003 + a) % HMOD
  h = (h * 1000003 + b) % HMOD
  h = (h * 48271 + 11) % HMOD
  return (h * 48271 + 7) % HMOD % 4096 / 4096
end
-- smooth 0..1 value noise with `size` m features
local function noise(x, y, size, seed)
  local fx, fy = x / size, y / size
  local gx, gy = floor(fx), floor(fy)
  local tx, ty = fx - gx, fy - gy
  tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
  local a = knot(seed, gx, gy) + (knot(seed, gx + 1, gy) - knot(seed, gx, gy)) * tx
  local b = knot(seed, gx, gy + 1) + (knot(seed, gx + 1, gy + 1) - knot(seed, gx, gy + 1)) * tx
  return a + (b - a) * ty
end
M.noise = noise
-- The noise as a rank: 0..1 with every value as likely as any other, so a share of the area is
-- a threshold. Value noise bunches round a half; its own measured quantiles spread it.
local QUANT = nil
local function rank(v)
  if not QUANT then
    local sample, n = {}, 0
    for i = 0, 63 do
      for j = 0, 63 do n = n + 1; sample[n] = noise(i * 7.31 + .37, j * 5.77 + .11, 13, 977) end
    end
    table.sort(sample)
    QUANT = {}
    for k = 0, 64 do QUANT[k] = sample[max(1, min(n, floor(k / 64 * (n - 1) + 1.5)))] end
  end
  if v <= QUANT[0] then return 0 end
  for k = 1, 64 do
    if v <= QUANT[k] then
      local a, b = QUANT[k - 1], QUANT[k]
      return (k - 1 + (b > a and (v - a) / (b - a) or 0)) / 64
    end
  end
  return 1
end
function M.field(x, y, size, seed) return rank(noise(x, y, size, seed)) end

-- --- zones -------------------------------------------------------------------------------------

-- The borders of Ukraine's natural zones as latitude over longitude: north of POLISSIA the
-- mixed forests, south of STEPPE the steppe, the forest-steppe between them (after the physical
-- geography's zoning: Lutsk - Rivne - Zhytomyr - Kyiv - Nizhyn - Hlukhiv, and Velyka
-- Mykhailivka - Pervomaisk - Kropyvnytskyi - Kobeliaky - Nova Vodolaha - Kupiansk).
local POLISSIA = {{22, 50.45}, {23.5, 50.6}, {25.3, 50.72}, {26.25, 50.6}, {28.65, 50.22}, {30.5, 50.44}, {31.9, 51.02},
  {33.9, 51.6}, {41, 51.8}}
local STEPPE = {{22, 47.2}, {28.5, 47.25}, {29.85, 47.1}, {30.85, 48.02}, {31.5, 48.3}, {32.26, 48.48}, {33.44, 48.86},
  {34.2, 49.12}, {35.87, 49.7}, {36.85, 49.44}, {37.6, 49.68}, {41, 49.8}}
local function border(line, lon)
  if lon <= line[1][1] then return line[1][2] end
  for k = 2, #line do
    if lon <= line[k][1] then
      local a, b = line[k - 1], line[k]
      return a[2] + (b[2] - a[2]) * (lon - a[1]) / (b[1] - a[1])
    end
  end
  return line[#line][2]
end
-- the region the rules are written for (Ukraine and a margin round it)
M.BOX = {21.5, 44.2, 40.8, 52.6}
function M.covers(lon, lat)
  local b = M.BOX
  return lon >= b[1] and lon <= b[3] and lat >= b[2] and lat <= b[4]
end

-- The zone of a place: 'polissia', 'foreststeppe', 'steppe', 'carpathians', 'crimea', or nil
-- outside the region. e: metres above the sea. x, y: the place in the region's frame, for a
-- border that wanders (a zone does not end on a line: +-0.12 degrees of noise over 9 km).
function M.zone(lon, lat, e, x, y)
  if not M.covers(lon, lat) then return nil end
  e = e or 0
  -- the Carpathians and their foothills; the Crimean mountains and the south coast under them
  if lon < 26.6 and lat < 49.75 and lat > 47.6 and e >= 330 then return 'carpathians' end
  if lat < 45.05 and lon > 33.2 and lon < 35.6 and (e >= 220 or lat < 44.62 + (lon - 33.4) * .22) then return 'crimea' end
  local wander = x and (noise(x, y, 9000, 311) - .5) * .24 or 0
  if lat + wander > border(POLISSIA, lon) then return 'polissia' end
  if lat + wander < border(STEPPE, lon) then return 'steppe' end
  return 'foreststeppe'
end

-- --- stands ------------------------------------------------------------------------------------

-- A zone's woods. conifer: the share of the wooded area under conifer stands where the map does
-- not name the leaf type. Each list: {species, parts}; the first is the stand's usual leader.
-- wet: beside water and in the wetlands. west / east: the list right and left of the Dnipro
-- (the hornbeam does not cross it), by longitude 31.2.
local ZONES = {
  polissia = {conifer = .64,
    conifer_stand = {{'pine', 76}, {'birch', 12}, {'oak', 5}, {'aspen', 4}, {'spruce', 3}},
    broadleaf = {{'birch', 30}, {'oak', 26}, {'alder', 12}, {'aspen', 12}, {'hornbeam', 9}, {'linden', 6}, {'maple', 5}},
    broadleaf_east = {{'birch', 32}, {'oak', 28}, {'aspen', 14}, {'alder', 10}, {'linden', 9}, {'maple', 7}},
    wet = {{'alder', 58}, {'birch', 16}, {'willow', 16}, {'aspen', 10}},
    under = {{'hazel', 30}, {'bush', 24}, {'rowan', 12}, {'juniper', 10}, {'raspberry', 10}, {'birch_young', 8}, {'oak_young', 6}},
    under_conifer = {{'juniper', 24}, {'bush', 20}, {'pine_young', 16}, {'birch_young', 14}, {'rowan', 12}, {'oak_young', 8},
      {'raspberry', 6}},
  },
  foreststeppe = {conifer = .14,
    conifer_stand = {{'pine', 84}, {'birch', 8}, {'oak', 6}, {'aspen', 2}},
    broadleaf = {{'oak', 38}, {'hornbeam', 20}, {'linden', 11}, {'maple', 11}, {'ash', 10}, {'elm', 4}, {'birch', 3}, {'aspen', 3}},
    broadleaf_east = {{'oak', 44}, {'linden', 16}, {'maple', 15}, {'ash', 12}, {'elm', 5}, {'birch', 4}, {'aspen', 4}},
    wet = {{'alder', 34}, {'willow', 34}, {'poplar', 20}, {'ash', 12}},
    under = {{'hazel', 36}, {'elder', 14}, {'bush', 16}, {'hawthorn', 8}, {'oak_young', 10}, {'beech_young', 10}, {'raspberry', 6}},
    under_conifer = {{'bush', 24}, {'elder', 16}, {'pine_young', 16}, {'oak_young', 14}, {'birch_young', 14}, {'rose', 8},
      {'raspberry', 8}},
  },
  steppe = {conifer = .08,
    conifer_stand = {{'pine', 92}, {'birch', 5}, {'oak', 3}},
    broadleaf = {{'oak', 34}, {'ash', 26}, {'maple', 16}, {'elm', 12}, {'poplar', 7}, {'linden', 5}},
    wet = {{'willow', 48}, {'poplar', 36}, {'alder', 10}, {'ash', 6}},
    under = {{'hawthorn', 24}, {'rose', 22}, {'elder', 16}, {'bush', 22}, {'oak_young', 10}, {'lilac', 6}},
    under_conifer = {{'rose', 26}, {'bush', 26}, {'pine_young', 22}, {'hawthorn', 14}, {'elder', 12}},
  },
  crimea = {conifer = .22,
    conifer_stand = {{'pine', 86}, {'oak', 10}, {'hornbeam', 4}},
    broadleaf = {{'oak', 52}, {'hornbeam', 22}, {'ash', 10}, {'maple', 9}, {'linden', 7}},
    high = {{'beech', 54}, {'hornbeam', 16}, {'pine', 16}, {'maple', 8}, {'ash', 6}},      -- from 650 m
    wet = {{'alder', 40}, {'willow', 30}, {'poplar', 20}, {'ash', 10}},
    under = {{'juniper', 26}, {'hawthorn', 22}, {'rose', 18}, {'bush', 18}, {'oak_young', 10}, {'hazel', 6}},
    under_conifer = {{'juniper', 40}, {'rose', 20}, {'bush', 20}, {'pine_young', 20}},
  },
  -- the Carpathians' belts by height (M.belt): foothill oak and hornbeam, the beech, the spruce
  carpathians = {
    low = {conifer = .06, conifer_stand = {{'pine', 50}, {'spruce', 40}, {'larch', 10}},
      broadleaf = {{'oak', 30}, {'hornbeam', 24}, {'beech', 24}, {'linden', 8}, {'maple', 8}, {'ash', 6}}},
    beech = {conifer = .22, conifer_stand = {{'spruce', 52}, {'fir', 34}, {'beech', 12}, {'larch', 2}},
      broadleaf = {{'beech', 66}, {'fir', 10}, {'maple', 9}, {'spruce', 6}, {'ash', 4}, {'elm', 3}, {'birch', 2}}},
    spruce = {conifer = .8, conifer_stand = {{'spruce', 76}, {'fir', 14}, {'beech', 6}, {'rowan', 4}},
      broadleaf = {{'beech', 54}, {'spruce', 22}, {'maple', 10}, {'rowan', 8}, {'birch', 6}}},
    wet = {{'alder', 66}, {'willow', 22}, {'ash', 12}},
    under = {{'hazel', 30}, {'beech_young', 26}, {'elder', 12}, {'raspberry', 12}, {'rowan', 10}, {'bush', 10}},
    under_conifer = {{'spruce_young', 34}, {'rowan', 18}, {'raspberry', 16}, {'beech_young', 14}, {'bush', 10}, {'juniper', 8}},
  },
}
M.ZONES = ZONES
-- the Carpathian belt at e metres (its borders wander with u, the stand's 0..1 noise)
function M.belt(e, u)
  local shift = ((u or .5) - .5) * 160
  if e + shift < 520 then return 'low' end
  if e + shift < 1080 then return 'beech' end
  return 'spruce'
end

-- Where people live: what is planted, by the kind of the place. The steppe's towns have the
-- plane and the poplar, its shelter belts the ash, elm and maple.
local SETTLED = {
  town = {{'linden', 20}, {'chestnut', 15}, {'maple', 15}, {'poplar', 11}, {'birch', 10}, {'ash', 8}, {'rowan', 5}, {'spruce', 5},
    {'willow', 4}, {'walnut', 4}, {'thuja', 3}},
  park = {{'oak', 18}, {'linden', 17}, {'maple', 14}, {'chestnut', 11}, {'birch', 9}, {'ash', 7}, {'hornbeam', 6}, {'pine', 6},
    {'spruce', 5}, {'willow', 4}, {'elm', 3}},
  garden = {{'fruit', 46}, {'walnut', 18}, {'birch', 6}, {'spruce', 5}, {'linden', 5}, {'rowan', 6}, {'willow', 5}, {'lilac', 9}},
  row = {{'linden', 24}, {'poplar', 20}, {'maple', 14}, {'chestnut', 12}, {'ash', 10}, {'birch', 8}, {'walnut', 7}, {'willow', 5}},
  field = {{'poplar', 24}, {'ash', 20}, {'maple', 16}, {'elm', 12}, {'oak', 12}, {'birch', 8}, {'walnut', 8}},
}
M.SETTLED = SETTLED

local function weighted(list, r)
  local total = 0
  for k = 1, #list do total = total + list[k][2] end
  local at = r * total
  for k = 1, #list do
    at = at - list[k][2]
    if at < 0 then return list[k][1] end
  end
  return list[#list][1]
end
M.weighted = weighted

-- a list without the species that have no model in this game (a game without a level's zip)
local kept = setmetatable({}, {__mode = 'k'})
local function available(list)
  local out = kept[list]
  if out and out.models == models then return out.list end
  if not models then load() end
  local have_ = {}
  for k = 1, #list do
    if #M.models(list[k][1]) > 0 then have_[#have_ + 1] = list[k] end
  end
  kept[list] = {list = have_, models = models}
  return have_
end

-- The stand at a point. q: {zone, lon, e (metres above the sea), needle (true, false or nil for
-- the map's leaf type: conifer, broadleaf, unknown), mixed (the map says mixed), wet}. Returns
-- {conifer = bool, list = the stand's species, leader = its leading species, age = 0..1}.
M.STAND = {type = 280, leader = 130, age = 190, purity = .62, mixed = 70}
function M.stand(q, x, y)
  local Z = ZONES[q.zone]
  if not Z then return nil end
  local T = M.STAND
  local zone = Z
  if q.zone == 'carpathians' then zone = Z[M.belt(q.e or 600, M.field(x, y, 400, 617))] end
  local list, conifer
  if q.wet then
    list, conifer = Z.wet, false
  else
    conifer = q.needle
    if conifer == nil then
      -- the map does not say: stands of the zone's share, small ones where it says 'mixed'
      local share = q.mixed and .5 or zone.conifer
      conifer = M.field(x, y, q.mixed and T.mixed or T.type, 601) < share
    end
    if conifer then list = zone.conifer_stand
    elseif q.zone == 'crimea' and (q.e or 0) >= 650 then list = Z.high
    elseif zone.broadleaf_east and (q.lon or 0) > 31.2 then list = zone.broadleaf_east
    else list = zone.broadleaf end
  end
  list = available(list)
  if #list == 0 then return nil end
  return {conifer = conifer and true or false, list = list, leader = weighted(list, M.field(x, y, T.leader, 603)),
    age = M.field(x, y, T.age, 605), under = conifer and Z.under_conifer or Z.under}
end

-- A tree of the stand: its species and its height in metres. r1, r2: the tree's own 0..1 hashes.
-- A stand is mostly its leader; young stands are low and even, old ones tall with a few giants.
function M.tree(stand, r1, r2)
  local species = stand.leader
  if r1 >= M.STAND.purity then species = weighted(stand.list, (r1 - M.STAND.purity) / (1 - M.STAND.purity)) end
  local grown = M.SPECIES[species].height
  local age = stand.age
  -- .5 of the grown height in the youngest stands, 1.04 in the oldest; each tree +-13 %
  local height = grown * (.5 + .54 * age ^ .8) * (.87 + .26 * r2)
  return species, height
end

-- A shrub or young tree under the stand: species and height in metres.
function M.undergrowth(stand, r1, r2)
  local list = available(stand.under)
  if #list == 0 then return nil end
  local species = weighted(list, r1)
  return species, M.SPECIES[species].height * (.55 + .7 * r2)
end

-- A planted tree where people live. kind: 'town', 'park', 'garden', 'row' (a street's row) or
-- 'field' (a shelter belt). patch: 0..1 that is one value along a street or across a yard (a
-- row is one species: a linden avenue, a line of poplars). Returns species, height in metres.
function M.planted(kind, zone, patch, r1, r2)
  local list = available(SETTLED[kind] or SETTLED.town)
  if #list == 0 then return nil end
  local species
  local pure = (kind == 'row' or kind == 'field') and .86 or (kind == 'park' and .35 or .2)
  if r1 < pure then species = weighted(list, patch) else species = weighted(list, (r1 - pure) / (1 - pure)) end
  local grown = M.SPECIES[species].height
  -- planted trees stand open and stay lower than a wood's; a garden's are small
  local k = kind == 'garden' and .8 or (kind == 'park' and .78 or .62)
  if M.SPECIES[species].shrub then k = 1 end
  return species, grown * k * (.72 + .5 * r2)
end

-- Every shape a zone's woods, undergrowth, streets and yards may take, sorted: the world loads
-- them once at a landing (a model first met while driving is a hitch).
function M.shapesOf(zone)
  local Z = ZONES[zone]
  if not Z then return {} end
  local species = {}
  local function take(list)
    for _, entry in ipairs(list or {}) do species[entry[1]] = true end
  end
  local function zoneLists(z)
    take(z.conifer_stand); take(z.broadleaf); take(z.broadleaf_east); take(z.high); take(z.wet)
    take(z.under); take(z.under_conifer)
  end
  zoneLists(Z)
  for _, belt in ipairs({'low', 'beech', 'spruce'}) do
    if Z[belt] then zoneLists(Z[belt]) end
  end
  for _, list in pairs(SETTLED) do take(list) end
  local seen, out = {}, {}
  for name in pairs(species) do
    for _, model in ipairs(M.models(name)) do
      if not seen[model.shape] then seen[model.shape] = true; out[#out + 1] = model.shape end
    end
  end
  table.sort(out)
  return out
end

-- Is the flora in force at a place: on, and the place inside the region it is written for.
function M.on(lon, lat)
  return M.enabled and lon ~= nil and M.covers(lon, lat)
end

function M.reset()
  M.used, models, exists = {}, nil, {}
  M.manifest, M.manifestRead = nil, false
end

return M
