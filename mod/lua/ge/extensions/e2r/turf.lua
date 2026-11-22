-- The engine's own grass on EarthNG's ground: GroundCover on a hidden TerrainBlock.
--
-- The game's dense grass (GroundCover: hundreds of thousands of billboards placed and culled by
-- the engine, swaying in its wind) grows only on a TerrainBlock, on the squares of the terrain
-- materials its types name. EarthNG's ground is its own mesh, so the lawn was TSStatic tufts made
-- in Lua within a budget (detail.lua): 9,000 of them, a carpet that ended 20 m from the car.
-- Here one TerrainBlock lies under the land round the car and is never drawn
-- (setRenderEnabled(false); BeamNG.Earth's finding, MIT: a block that is not drawn still carries
-- GroundCover and its layer map). Its heights are the ground's own where the generator laid lawn
-- (the 2 m squares of a tile's grass patches, generator.lua lawnCarpet), a few centimetres under
-- it; its layer map names the lawn's kind there and 'none' everywhere else, far below, so no
-- road, yard, building or water grows grass. The stock GroundCover definitions of Hirochi
-- Raceway and West Coast USA are read from the game's own files and bound to those layers.
--
-- The block is N squares of SQUARE m a side and moves when the car nears its edge or the lawn
-- round the car has changed (tiles arrive after a landing). A move is a new .ter file (the
-- game's format: version 9, size, heights, layers, material names) swapped in: the heights are
-- gathered over several frames, the swap and the regrowth of the grass happen in one.
--
-- The block collides like any terrain. It lies under the drawn ground and its collision proxy
-- (SINK), and far under everything where there is no lawn.
--
-- A wood's floor is two more layers (generator.lua lawnCarpet flags 512 and 1024): under
-- broadleaves ferns, the wood's low herbs and its flowers, under conifers the sparser herbs of
-- a needle floor. They are stock definitions too: Hirochi's forest floor.
--
-- At speed the grass is a few definitions a layer: what reads from a fast car. Slow enough to
-- look round (M.STILL: under `slow` m/s for `after` s; 50 km/h, the user's bar of 21.11, was a
-- walking pace before) the layers fill up as a level's own are laid, one definition over
-- another: nettles and tall weeds, flowers, seeded grass heads, wet plants in the hollows, the
-- wood's second and third herbs. The definitions marked `still` are made then, at most `step` a
-- frame, and go once the car has been above `fast` m/s (60 km/h) for `leave` s: a car that holds
-- 50 does not make and drop them at every touch of the pedal. A definition regrows its cells in
-- the frame it is made: above `crawl` m/s they are made one every `pace` s, not `step` a frame.
local M = {}

M.NAME = 'e2rTurf'
M.TEXTURE_SET = 'e2rTurfTextureSet'
M.DIR = 'e2r_stream/turf'
M.N = 512            -- samples a side: with SQUARE 2 m, 1022 m of land
M.SQUARE = 2         -- m: the lawn's own squares (detail.lua, generator.lua lawnCarpet)
M.SINK = .07         -- m under the drawn ground
M.DEEP = 30          -- m under the lowest lawn: the block where there is none
M.EDGE = 190         -- m: the block follows when the car is this near its edge
M.PERIOD = 1.5       -- s between two moves at the least
-- New lawn (a tile's grass arrives) is put into the block where it is within NEAR m of the car:
-- the grass reaches no farther, and lawn beyond it waits for the block's next move. Gathering
-- for every arrival moved the block every PERIOD all the way down a road.
M.NEAR, M.NEAR_CELL = 170, 32
M.BUDGET = 1.5       -- ms a frame for gathering the next block
-- the block's layers (earthng/turf_art.py LAYERS, the same order): its layer map holds index - 1
M.LAYERS = {'e2rTurfNone', 'e2rTurfGrass', 'e2rTurfLush', 'e2rTurfDry', 'e2rTurfCrop', 'e2rTurfForest', 'e2rTurfPine'}
M.STILL = {slow = 13.9, fast = 16.7, after = 1.2, leave = 2, step = 2, crawl = 2.5, pace = .25}
M.enabled = true
-- element count factor (the settings: grass density) and draw distance factor
M.density, M.distance = 1, 1

local HIROCHI, WCUSA, TRAINING, ECA = '/levels/hirochi_raceway/', '/levels/west_coast_usa/', '/levels/driver_training/',
  '/levels/east_coast_usa/'
local HIROCHI_GC, TRAINING_GC = HIROCHI .. 'art/shapes/groundcover/main.materials.json',
  TRAINING .. 'art/shapes/groundcover/main.materials.json'
M.SOURCES = {
  hirochi = {materials = HIROCHI_GC, items = HIROCHI .. 'main/MissionGroup/vegetation/terrain_grass/items.level.json'},
  hirochi2 = {materials = HIROCHI_GC, items = HIROCHI .. 'main/MissionGroup/vegetation/terrain_grass2/items.level.json'},
  floor = {materials = HIROCHI_GC, items = HIROCHI .. 'main/MissionGroup/vegetation/terrain_forest_floor/items.level.json'},
  forest = {materials = HIROCHI_GC, items = HIROCHI .. 'main/MissionGroup/vegetation/terrain_forest/items.level.json'},
  wcusa = {materials = WCUSA .. 'art/groundcover/main.materials.json',
    items = WCUSA .. 'main/MissionGroup/vegetation/items.level.json'},
  nettles = {materials = TRAINING_GC, items = TRAINING .. 'main/MissionGroup/Level_object/vegetation/terrain_dirt_grass/items.level.json'},
  wet = {materials = TRAINING_GC, items = TRAINING .. 'main/MissionGroup/Level_object/vegetation/terrain_dirt_loose/items.level.json'},
  -- (the seeded grass heads' material is in the level's 3D grass folder)
  eca = {materials = {ECA .. 'art/shapes/groundcover/main.materials.json', ECA .. 'art/shapes/groundcover/3d_grass_test/main.materials.json'},
    items = ECA .. 'main/MissionGroup/Level_object/vegetation/terrain_grass/items.level.json'},
  eca2 = {materials = ECA .. 'art/shapes/groundcover/main.materials.json',
    items = ECA .. 'main/MissionGroup/Level_object/vegetation/terrain_grass2/items.level.json'},
}
-- stock GroundCover (source, src) -> our layer, with the share of its elements; `name` names a
-- second use of one definition; `fields` override stock fields.
-- The shares are over the stock counts: Hirochi's own lawn stands on a green terrain texture and
-- reads as a carpet at 1; on our ground, whose colour is the place's, 0.6 of it was a tuft a
-- square metre on bare land. At these a slope is a meadow to 80 m and the frame is the same
-- (Vytachiv, Balanced, 1280 x 720: 6.5 ms with and without, a block move 20 ms; hyperreal probe-01).
M.LONG = {radius = 90, dissolveRadius = 60}
M.DEFS = {
  -- the common lawn: short grass, long grass over it
  {source = 'hirochi', src = 'small_grass_close', layer = 'e2rTurfGrass', share = 1.8},
  {source = 'hirochi', src = 'long_grass_distant', layer = 'e2rTurfGrass', share = 1.2, fields = M.LONG},
  -- lush hollows and a field's green rows: mostly long grass
  {source = 'hirochi', src = 'small_grass_close', name = 'small_grass_close_lush', layer = 'e2rTurfLush', share = 1.2},
  {source = 'hirochi', src = 'long_grass_distant', name = 'long_grass_distant_lush', layer = 'e2rTurfLush', share = 1.8, fields = M.LONG},
  -- dry ground: dry grass with some green in it; ripe wheat: the dry grass, dense
  {source = 'hirochi', src = 'small_grass_close', name = 'small_grass_close_dry', layer = 'e2rTurfDry', share = .75},
  {source = 'wcusa', src = 'grass_dry_1', layer = 'e2rTurfDry', share = 1.8},
  {source = 'wcusa', src = 'grass_dry_1', name = 'grass_dry_1_crop', layer = 'e2rTurfCrop', share = 3},
  -- a broadleaf wood's floor: ferns in clumps and the low herbs between them
  {source = 'floor', src = 'fern1', layer = 'e2rTurfForest', share = 1.3},
  {source = 'floor', src = 'Forest_weed', layer = 'e2rTurfForest', share = 1.1},
  -- a conifer wood's: sparse low herbs over the needles, a fern here and there
  {source = 'floor', src = 'Forest_weed', name = 'Forest_weed_pine', layer = 'e2rTurfPine', share = .8},
  {source = 'floor', src = 'fern1', name = 'fern1_pine', layer = 'e2rTurfPine', share = .4},
  -- Standing still: the layers a level's own vegetation is laid in, one over another.
  -- the lawn: flowers, daisies and buttercups, seeded grass heads, a clump of coarse weeds
  {source = 'hirochi2', src = 'flowers_01', layer = 'e2rTurfGrass', share = 1.6, still = true},
  {source = 'eca', src = 'Daisies', layer = 'e2rTurfGrass', share = 1.2, still = true},
  {source = 'eca2', src = 'buttercups_close', layer = 'e2rTurfGrass', share = 1, still = true},
  {source = 'eca', src = 'long_grass_clump_close_03', layer = 'e2rTurfGrass', share = .7, still = true},
  {source = 'hirochi', src = 'medium_grass_close', layer = 'e2rTurfGrass', share = 1.2, still = true},
  -- the lush hollows: tall wet plants, more long grass, buttercups
  {source = 'wet', src = 'wet_weed_01', layer = 'e2rTurfLush', share = .16, still = true},
  {source = 'eca2', src = 'buttercups_close', name = 'buttercups_lush', layer = 'e2rTurfLush', share = 1.4, still = true},
  {source = 'hirochi', src = 'medium_grass_close', name = 'medium_grass_lush', layer = 'e2rTurfLush', share = 2, still = true},
  -- dry ground: seeded heads and a flower
  {source = 'eca', src = 'long_grass_clump_close_03', name = 'seeded_dry', layer = 'e2rTurfDry', share = .5, still = true},
  {source = 'hirochi2', src = 'flowers_01', name = 'flowers_dry', layer = 'e2rTurfDry', share = .7, still = true},
  -- the broadleaf floor: its flowers, nettles in drifts, the forest's second herb, grass in the light
  {source = 'floor', src = 'Purple_flowers', layer = 'e2rTurfForest', share = .9, still = true},
  {source = 'nettles', src = 'Nettles_01', layer = 'e2rTurfForest', share = .3, still = true},
  {source = 'forest', src = 'Weed2', layer = 'e2rTurfForest', share = .5, still = true},
  {source = 'hirochi', src = 'long_grass_distant', name = 'long_grass_forest', layer = 'e2rTurfForest', share = .25, still = true,
    fields = M.LONG},
  -- the needle floor: the forest's herb, flowers at the paths, grass tufts
  {source = 'forest', src = 'Weed2', name = 'Weed2_pine', layer = 'e2rTurfPine', share = .6, still = true},
  {source = 'floor', src = 'Purple_flowers', name = 'Purple_flowers_pine', layer = 'e2rTurfPine', share = .35, still = true},
  {source = 'hirochi', src = 'small_grass_close', name = 'small_grass_pine', layer = 'e2rTurfPine', share = .3, still = true},
}
-- The grass's colour. The stock lawn materials are a racing circuit's watered green; over land
-- whose sheet is the colour the place has from above (fast_tone.SATELLITE: 91 91 63 round Kyiv)
-- the blades stood as a second, louder green (own-01: the lawn read 70 125 35 in the sun). The
-- common and the lush grass are drawn in copies of their materials with the base colour factor
-- multiplied by M.TINT, about half of the way from the stock green to the picture's olive: less
-- green, more red and blue. Flowers, ferns and the dry grass keep their materials.
M.TINT = {1.18, .96, 1.3}
M.TINTED = {m_grass_green_short_01 = true, m_grass_green_long_01 = true}
M.TINT_LAYERS = {e2rTurfGrass = true, e2rTurfLush = true}

-- Pure: the copy of a stock material definition `m` under `name` with its colour factor tinted.
function M.tinted(m, name, tint)
  local c = {}
  for k, v in pairs(m) do c[k] = v end
  c.name, c.mapTo, c.persistentId = name, name, nil
  c.Stages = {}
  for i, stage in ipairs(m.Stages or {}) do
    local st = {}
    for k, v in pairs(stage) do st[k] = v end
    c.Stages[i] = st
  end
  local st = c.Stages[1]
  if st then
    local f = type(st.baseColorFactor) == 'table' and st.baseColorFactor or {1, 1, 1, 1}
    st.baseColorFactor = {(f[1] or 1) * tint[1], (f[2] or 1) * tint[2], (f[3] or 1) * tint[3], f[4] or 1}
  end
  return c
end

M.PREFIX = 'e2rTurfGC_'
-- CPU placement: all cells regrow in the frame of a move (flushGroundCoverGrids); GPU-placed
-- cells draw a frame later and read a layer copy the hidden block never refreshes (BeamNG.Earth)
M.PLACEMENT = {{'useNewPlacement', '1'}, {'useNewPlacementGpu', '0'}}

local ffi
do
  local ok, lib = pcall(require, 'ffi')
  if ok and type(lib) == 'table' then ffi = lib end
end

local floor, min, max = math.floor, math.min, math.max
local tiles = {}        -- tile -> {patches}
local count = 0         -- patches held
local revision = 0      -- bumped when the patches change
local pending = {}      -- NEAR_CELL squares that got lawn since the block was last gathered
local block             -- the block in the game: {x0, y0, seq, revision, file}
local work              -- the next block being gathered (a coroutine)
local covers = {}       -- GroundCover object names made
local coverSet = {}     -- name -> true
local defsCache, loadedMaterials = {}, {}
local stats = {moves = 0, patches = 0, squares = 0, ms = 0, error = nil}
M.stats = stats

-- the layer (0-based index into M.LAYERS) of a lawn sample's flags (generator.lua lawnCarpet:
-- 16 a lush hollow, 32 thin on dry ground, 64 ripe wheat, 128 a field's rows)
function M.layerOf(flags)
  -- a wood's floor: under conifers, under broadleaves (0: the planet has no such layers yet)
  if flags >= 512 then return M.woodLayers == false and 0 or (flags >= 1024 and 6 or 5) end
  if flags >= 128 then return 2 end
  if floor(flags / 64) % 2 == 1 then return 4 end
  if floor(flags / 32) % 2 == 1 then return 3 end
  if floor(flags / 16) % 2 == 1 then return 2 end
  return 1
end

-- A tile's lawn patch arrives (detail.lua add). True: the turf has it, no tufts are made.
function M.take(tile, patch)
  if not M.active() then return false end
  local list = tiles[tile]
  if not list then list = {}; tiles[tile] = list end
  list[#list + 1] = patch
  count, revision = count + 1, revision + 1
  pending[floor(patch.x / M.NEAR_CELL) * 65536 + floor(patch.y / M.NEAR_CELL)] = true
  return true
end

-- lawn that is not in the block yet lies within NEAR of (x, y)
function M.freshNear(x, y)
  local c, r = M.NEAR_CELL, M.NEAR
  for cx = floor((x - r) / c), floor((x + r) / c) do
    for cy = floor((y - r) / c), floor((y + r) / c) do
      if pending[cx * 65536 + cy] then return true end
    end
  end
  return false
end

function M.remove(tile)
  local list = tiles[tile]
  if not list then return end
  tiles[tile] = nil
  count, revision = count - #list, revision + 1
end

-- Pure: the block's south-west corner for a car at (x, y): on the lawn's 8 m lattice, the car
-- in the middle.
function M.originFor(x, y)
  local half = (M.N - 1) * M.SQUARE / 2
  return floor((x - half) / 8 + .5) * 8, floor((y - half) / 8 + .5) * 8
end

-- Pure: gather the patches into a block at (x0, y0). Returns heights (uint16[N * N], row 0
-- south), layers (uint8[N * N]), base (the block's z), maxHeight, and the squares of lawn; or
-- nil when no lawn lies in it. pause() is called between patches.
function M.gather(x0, y0, pause)
  local N, SQ = M.N, M.SQUARE
  local zs = ffi.new('float[?]', N * N)
  local layers = ffi.new('uint8_t[?]', N * N)
  local BIG = 1e30
  for k = 0, N * N - 1 do zs[k] = BIG end
  local low, high, squares, n = BIG, -BIG, 0, 0
  local x1, y1 = x0 + (N - 1) * SQ, y0 + (N - 1) * SQ
  for _, list in pairs(tiles) do
    for _, patch in ipairs(list) do
      local px, py = patch.x, patch.y
      if px >= x0 and py >= y0 and px + 8 <= x1 and py + 8 <= y1 then
        local cx0, cy0 = floor((px - x0) / SQ + .5), floor((py - y0) / SQ + .5)
        local samples = patch.samples
        for k = 1, #samples, 4 do
          local value = samples[k]
          local slot = value % 16
          local z, gx, gy = samples[k + 1] - M.SINK, samples[k + 2], samples[k + 3]
          local cx, cy = cx0 + slot % 4, cy0 + floor(slot / 4)
          layers[cy * N + cx] = M.layerOf((value - slot))
          -- the square's four corners on its own plane; a corner two squares share takes the lower
          for dy = 0, 1 do
            for dx = 0, 1 do
              local h = z + gx * (dx * 2 - 1) * SQ / 2 + gy * (dy * 2 - 1) * SQ / 2
              local at = (cy + dy) * N + cx + dx
              if h < zs[at] then zs[at] = h end
              if h < low then low = h end
              if h > high then high = h end
            end
          end
          squares = squares + 1
        end
      end
      n = n + 1
      if pause and n % 24 == 0 then pause() end
    end
  end
  if squares == 0 then return nil end
  local base = floor(low - M.DEEP)
  -- the height range the 16 bits cover: a power of two over the lawn's own, so most moves keep it
  local range = 64
  while range < high - base + 2 do range = range * 2 end
  local heights = ffi.new('uint16_t[?]', N * N)
  local scale = 65535 / range
  for k = 0, N * N - 1 do
    local z = zs[k]
    heights[k] = z < BIG and floor((z - base) * scale + .5) or 0
    if pause and k % 32768 == 32767 then pause() end
  end
  return heights, layers, base, range, squares
end

-- Pure: the bytes of the game's terrain file (version 9: size, heights, layers, material names)
function M.terBytes(heights, layers)
  local N = M.N
  local head = ffi.new('uint8_t[5]', 9, N % 256, floor(N / 256) % 256, 0, 0)
  local parts = {ffi.string(head, 5), ffi.string(heights, N * N * 2), ffi.string(layers, N * N),
    string.char(#M.LAYERS, 0, 0, 0)}
  for _, name in ipairs(M.LAYERS) do parts[#parts + 1] = string.char(#name) .. name end
  return table.concat(parts)
end

-- --- the engine ------------------------------------------------------------------------------

-- the level has the layers' materials (earthng/turf_art.py): an older planet does not
function M.ready()
  if M.readyState == nil then
    M.readyState = scenetree ~= nil and scenetree.findObject(M.TEXTURE_SET) ~= nil
      and scenetree.findObject(M.LAYERS[2]) ~= nil or false
    -- an older planet has the lawn's layers only: the block is written without the wood's
    M.woodLayers = M.readyState and scenetree.findObject(M.LAYERS[6]) ~= nil
  end
  return M.readyState
end

local function fieldValue(v)
  if type(v) == 'table' then
    local parts = {}
    for i, x in ipairs(v) do parts[i] = tostring(x) end
    return table.concat(parts, ' ')
  end
  if type(v) == 'boolean' then return v and '1' or '0' end
  return tostring(v)
end

local SKIP = {name = true, class = true, persistentId = true, __parent = true, position = true, Types = true,
  internalName = true, canSave = true}
local RADIUS = {radius = true, dissolveRadius = true, shapeCullRadius = true}

-- Pure: the setField calls {field, index, value} that make a stock definition on `layer`, its
-- element count times `share`, its radii times `dist`.
function M.fieldsFor(def, layer, share, dist, null)
  local calls = {}
  for k, v in pairs(def) do
    if not SKIP[k] and v ~= null then
      if k == 'maxElements' then v = max(1, floor((tonumber(v) or 0) * share + .5)) end
      if RADIUS[k] and tonumber(v) then v = tonumber(v) * dist end
      calls[#calls + 1] = {k, 0, fieldValue(v)}
    end
  end
  for i, t in ipairs(type(def.Types) == 'table' and def.Types or {}) do
    for k, v in pairs(t) do
      if v ~= nil and v ~= null then
        -- every type the stock definition grows somewhere grows on our layer
        if k == 'layer' then v = (v ~= '' and layer or '') end
        calls[#calls + 1] = {k, i - 1, fieldValue(v)}
      end
    end
  end
  table.sort(calls, function(a, b) if a[1] ~= b[1] then return a[1] < b[1] end return a[2] < b[2] end)
  return calls
end

local function readDefs(source)
  local text = readFile and readFile(M.SOURCES[source].items)
  if type(text) ~= 'string' then return nil end
  local want, out = {}, {}
  for _, d in ipairs(M.DEFS) do if d.source == source then want[d.src] = true end end
  for line in text:gmatch('[^\r\n]+') do
    if line:find('"GroundCover"', 1, true) then
      local ok, d = pcall(jsonDecode, line)
      if ok and type(d) == 'table' and want[d.name] then out[d.name] = d end
    end
  end
  return out
end

local function removeCovers()
  for _, name in ipairs(covers) do
    local o = scenetree.findObject(name)
    if o then pcall(function() o:delete() end) end
  end
  covers, coverSet = {}, {}
end

-- Pure: is a definition wanted now: always, or only standing still; a wood's when the planet
-- has the wood's layers.
function M.wanted(d)
  if d.still and not M.still then return false end
  if M.woodLayers == false and (d.layer == M.LAYERS[6] or d.layer == M.LAYERS[7]) then return false end
  return true
end

-- the tinted copy of a stock grass material, made once (nil: the stock one stays)
local tintMade = {}
local function tintedMaterial(files, material)
  if not M.TINTED[material] then return nil end
  local name = 'e2rTurf_' .. material
  if tintMade[name] ~= nil then return tintMade[name] or nil end
  tintMade[name] = false
  pcall(function()
    for _, file in ipairs(files) do
      local defs = jsonReadFile(file)
      local m = type(defs) == 'table' and defs[material]
      if m then
        local out = 'e2r_world/turf_' .. material .. '.json'
        jsonWriteFile(out, {[name] = M.tinted(m, name, M.TINT)}, false)
        loadJsonMaterialsFile('/' .. out)
        tintMade[name] = name
        return
      end
    end
  end)
  return tintMade[name] or nil
end

local function makeCover(d, name)
  if defsCache[d.source] == nil then
    local files = M.SOURCES[d.source].materials
    if type(files) ~= 'table' then files = {files} end
    for _, file in ipairs(files) do
      if not loadedMaterials[file] and FS:fileExists(file) then
        loadJsonMaterialsFile(file)
        loadedMaterials[file] = true
      end
    end
    defsCache[d.source] = readDefs(d.source) or false
  end
  local def = defsCache[d.source] and defsCache[d.source][d.src]
  if not def then return false end
  local old = scenetree.findObject(name)
  if old then old:delete() end
  local gc = createObject('GroundCover')
  local dist = M.distance
  for _, c in ipairs(M.fieldsFor(def, d.layer, d.share * M.density * dist * dist, dist, jsonNull)) do
    gc:setField(c[1], c[2], c[3])
  end
  for k, v in pairs(d.fields or {}) do
    gc:setField(k, 0, tostring(RADIUS[k] and tonumber(v) and tonumber(v) * dist or v))
  end
  for _, f in ipairs(M.PLACEMENT) do gc:setField(f[1], 0, f[2]) end
  -- the common and the lush grass in the land's own tone (M.TINT)
  if M.TINT and M.TINT_LAYERS[d.layer] and type(def.material) == 'string' then
    local files = M.SOURCES[d.source].materials
    local tinted = tintedMaterial(type(files) == 'table' and files or {files}, def.material)
    if tinted then gc:setField('material', 0, tinted) end
  end
  gc.canSave = false
  gc:registerObject(name)
  scenetree.MissionGroup:addObject(gc)
  pcall(function() gc:postApply() end)
  return true
end

-- The GroundCover objects, once the block exists: those wanted now are made (at most `limit`
-- of them in this call), those no longer wanted go. Returns whether any stand, and how many
-- are still to be made.
local function ensureCovers(limit)
  local made, left = 0, 0
  local ok, err = pcall(function()
    for _, d in ipairs(M.DEFS) do
      local name = M.PREFIX .. (d.name or d.src)
      local want = M.wanted(d)
      if want and coverSet[name] == nil then
        if limit and made >= limit then
          left = left + 1
        else
          -- false: the game has no such definition; not asked again
          coverSet[name] = makeCover(d, name)
          if coverSet[name] then covers[#covers + 1] = name; made = made + 1 end
        end
      elseif not want and coverSet[name] then
        local o = scenetree.findObject(name)
        if o then pcall(function() o:delete() end) end
        coverSet[name] = nil
        for k = #covers, 1, -1 do
          if covers[k] == name then table.remove(covers, k) end
        end
      end
    end
  end)
  if not ok then
    stats.error = tostring(err)
    log('W', 'e2r.turf', 'ground cover: ' .. tostring(err))
    removeCovers()
  end
  stats.covers = #covers
  return #covers > 0, left
end

-- Pure: the car's (or the camera's) speed from its place this frame and the last, and whether
-- it is slow enough for the full layers by M.STILL: true once it has been under `slow` for
-- `after` s, false once it has been over `fast` for `leave` s; between the two it keeps what it has.
function M.motion(p, now)
  local T = M.STILL
  local last = M.lastP
  if last and now > last.t then
    local v = math.sqrt((p.x - last.x) ^ 2 + (p.y - last.y) ^ 2 + ((p.z or 0) - last.z) ^ 2) / (now - last.t)
    -- a landing or a hop is not a drive
    if v < 200 then M.speed = v end
  end
  if not last or now > last.t then M.lastP = {x = p.x, y = p.y, z = p.z or 0, t = now} end
  local v = M.speed
  if not v then return M.still end
  if v > T.fast then
    M.slowSince, M.fastSince = nil, M.fastSince or now
    if now - M.fastSince >= (T.leave or 0) then M.still = false end
  elseif v < T.slow then
    M.fastSince, M.slowSince = nil, M.slowSince or now
    if now - M.slowSince >= T.after then M.still = true end
  else
    M.slowSince, M.fastSince = nil, nil
  end
  return M.still
end

local function write(path, bytes)
  local folder = path:match('^(.*)/[^/]+$')
  if folder and FS.directoryCreate and not FS:directoryExists('/' .. folder) then FS:directoryCreate('/' .. folder, true) end
  local f = assert(io.open(path, 'wb'))
  f:write(bytes)
  f:close()
end

-- Put a gathered block into the game: a new terrain file, the block made or moved, the grass
-- regrown this frame.
local function commit(x0, y0, heights, layers, base, range)
  local timer = hptimer and hptimer()
  local seq = (block and block.seq or 0) + 1
  -- a new name each time: the engine skips a file it already has
  local path = M.DIR .. '/block_' .. seq .. '.ter'
  write(path, M.terBytes(heights, layers))
  local tb = scenetree.findObject(M.NAME)
  if not tb then
    tb = TerrainBlock and TerrainBlock() or createObject('TerrainBlock')
    tb:setName(M.NAME)
    tb:setField('baseTexSize', 0, '256')
    tb:setField('castShadows', 0, '0')
    tb:setField('squareSize', 0, tostring(M.SQUARE))
    tb:setField('maxHeight', 0, tostring(range))
    tb:setField('materialTextureSet', 0, M.TEXTURE_SET)
    tb:setField('terrainFile', 0, '/' .. path)
    tb.canSave = false
    tb:registerObject(M.NAME)
    scenetree.MissionGroup:addObject(tb)
  else
    tb:setField('maxHeight', 0, tostring(range))
    tb:setField('terrainFile', 0, '/' .. path)
    tb:postApply()
  end
  tb:setPosition(vec3(x0, y0, base))
  if tb.setRenderEnabled then tb:setRenderEnabled(false) end
  if block and block.file and FS.removeFile then pcall(function() FS:removeFile('/' .. block.file) end) end
  block = {x0 = x0, y0 = y0, seq = seq, file = path, base = base, range = range}
  if ensureCovers() and flushGroundCoverGrids then flushGroundCoverGrids() end
  M.coversLeft = 0
  stats.moves = stats.moves + 1
  if timer then stats.ms = timer:stop() end
end

-- The quality's grass settings as the turf's own (quality.lua: Balanced is 100 m and 9000 tufts):
-- how far it is drawn and how thick it stands.
function M.factors(tune)
  local reach, budget = tonumber(tune and tune.grassM), tonumber(tune and tune.grassBudget)
  if not reach or not budget then return 1, 1 end
  if reach <= 0 or budget <= 0 then return 0, 0 end
  return max(.3, min(1.5, budget / 9000)), max(.6, min(1.4, reach / 100))
end

-- Every frame (world.lua): p the camera or the car {x, y, z}, now the clock in seconds, tune the
-- quality in force. Returns true in the frame the block moved.
function M.step(p, now, tune)
  if not p or count == 0 or not M.active() then return false end
  if tune and tune ~= M.tune then
    -- a new quality: the grass thinner or thicker, nearer or farther (0: none)
    M.tune = tune
    local density, distance = M.factors(tune)
    if density <= 0 then
      if #covers > 0 then removeCovers() end
      M.off = true
    else
      M.off = false
      M.set(density, distance)
    end
  end
  if M.off then return false end
  -- standing still: the layers fill up; moving off: back to what a moving car reads
  local was = M.still
  if M.stillOn ~= false then M.motion(p, now) else M.still = false end
  if block and (M.still ~= was or (M.coversLeft or 0) > 0) then
    local T = M.STILL
    local moving = (M.speed or 0) > T.crawl
    if M.still ~= was or not moving or now - (M.coverAt or -1) >= T.pace then
      local _, left = ensureCovers(moving and 1 or T.step)
      M.coversLeft, M.coverAt = left, now
      stats.still = M.still or false
    end
  end
  if work then
    -- (the coroutine keeps the pause it was started with: the clock is this frame's)
    M.timer = hptimer()
    local ok, x0, y0, heights, layers, base, range, squares = coroutine.resume(work, function()
      if M.timer:stop() >= M.BUDGET then coroutine.yield() end
    end)
    if not ok then
      work, stats.error = nil, tostring(x0)
      log('W', 'e2r.turf', 'gather: ' .. tostring(x0))
      return false
    end
    if coroutine.status(work) ~= 'dead' then return false end
    work = nil
    M.at = now
    if not heights then return false end
    local done, err = pcall(commit, x0, y0, heights, layers, base, range)
    if not done then
      -- an engine that will not take the block: the lawn goes back to its tufts from here on
      stats.error = tostring(err)
      log('W', 'e2r.turf', 'block: ' .. tostring(err))
      M.failed = true
      return false
    end
    block.revision, stats.squares, stats.patches = M.gathered, squares, count
    return true
  end
  if M.at and now - M.at < M.PERIOD then return false end
  local span = (M.N - 1) * M.SQUARE
  local near = block and (p.x - block.x0 < M.EDGE or block.x0 + span - p.x < M.EDGE
    or p.y - block.y0 < M.EDGE or block.y0 + span - p.y < M.EDGE)
  if block and not near and (block.revision == revision or not M.freshNear(p.x, p.y)) then return false end
  -- the same place again for new lawn; a new place when the car nears the edge
  local x0, y0 = M.originFor(p.x, p.y)
  if block and not near then x0, y0 = block.x0, block.y0 end
  M.gathered, pending = revision, {}
  work = coroutine.create(function(pause)
    return x0, y0, M.gather(x0, y0, pause)
  end)
  return false
end

-- density ('low', 'normal', 'high' or a factor) and distance: the objects are made again
function M.set(density, distance)
  local d, r = tonumber(density) or M.density, tonumber(distance) or M.distance
  if d == M.density and r == M.distance then return end
  M.density, M.distance = d, r
  if #covers > 0 then
    removeCovers()
    if ensureCovers() and flushGroundCoverGrids then flushGroundCoverGrids() end
  end
end

function M.active() return M.enabled and M.real ~= false and not M.failed and ffi ~= nil and M.ready() end

local function clear()
  removeCovers()
  local tb = scenetree and scenetree.findObject(M.NAME)
  if tb then pcall(function() tb:delete() end) end
  block, work = nil, nil
end

-- The texture pack in force (world.lua): the engine's grass is the real pack's. Every other
-- pack keeps the tufts it draws in its own colours; its tiles are built again at the switch.
function M.setReal(on)
  on = on and true or false
  if (M.real ~= false) == on then return end
  M.real = on
  if not on then
    clear()
    tiles, count, revision = {}, 0, revision + 1
  end
end

-- The player's switch (world.lua option 'turf'). Off: the grass and its block go; the lawns of
-- tiles built from then on are tufts again (detail.lua), those already here stay bare until then.
function M.setEnabled(on)
  on = on and true or false
  if on == M.enabled then return end
  M.enabled = on
  if not on then clear() end
end

-- The level ended: its objects and the stock materials loaded for it went with it.
function M.reset()
  tiles, count, revision, block, work, pending = {}, 0, 0, nil, nil, {}
  covers, coverSet, defsCache, loadedMaterials = {}, {}, {}, {}
  M.readyState, M.at, M.failed, M.tune, M.off, M.woodLayers = nil, nil, nil, nil, nil, nil
  M.still, M.speed, M.lastP, M.slowSince, M.fastSince, M.coversLeft, M.coverAt = nil, nil, nil, nil, nil, nil, nil
  stats.moves, stats.patches, stats.squares, stats.error = 0, 0, 0, nil
end

return M
