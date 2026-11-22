-- The generator's knobs while the game runs: a value for the whole world and another for one
-- tile, so a road's crown, a kerb's width, the wall of a block of flats or a region's asset set
-- can be changed on the pause menu and seen on the tile under the car a second later.
--
-- A knob has a target: 'tune' (generator.lua TUNE, through options.tune), 'look' (a slot of the
-- pack's look, looks.py) or 'option' (a field of generator.build's options). Only knobs that
-- differ from their default are handed to the generator: a lab nobody touched changes nothing.
-- A tile's value wins over the world's. Tiles are named '<region id>:<i>_<j>'.
-- Pure Lua (earthng/test_lab.py runs it in lupa); native.lua asks resolve() for every tile.
local M = {}
M.path = 'settings/earthng-lab.json'
M.schema = 'earthng-lab-v1'
M.revision = 0                       -- grows with every change: caches of resolve() watch it
-- {read = function() return cfg end, write = function(cfg) end}; world.lua points it at M.path
M.storage = nil

local specs, order = {}, {}
local groups, groupOrder = {}, {}
local world, tiles = {}, {}          -- key -> value; scope -> {key -> value}
local resolved, resolvedAt = {}, -1

local function round(v) return math.floor(v + .5) end

local function normalise(spec, v)
  if spec.kind == 'bool' then
    if v == true or v == 1 or v == 'true' then return true end
    if v == false or v == 0 or v == 'false' then return false end
    return nil
  end
  if spec.kind == 'enum' then
    for _, entry in ipairs(spec.values) do
      if entry.value == v or tostring(entry.value) == tostring(v) then return entry.value end
    end
    return nil
  end
  v = tonumber(v)
  if not v or v ~= v or v == math.huge or v == -math.huge then return nil end
  if v < spec.min then v = spec.min end
  if v > spec.max then v = spec.max end
  local step = spec.step or (spec.kind == 'int' and 1 or nil)
  if step and step > 0 then
    v = spec.min + round((v - spec.min) / step) * step
    if v > spec.max then v = spec.max end
    -- 0.30000000000000004: the page would print it, and a value equal to its default must compare so
    v = tonumber(string.format('%.6f', v))
  end
  if spec.kind == 'int' then v = round(v) end
  return v
end

-- a knob's own default: a value, or a function of the tile (a pack names a universe for a tile
-- of its own; the world's default is asked with no tile)
local function ownDefault(spec, scope)
  local d = spec.default
  if type(d) == 'function' then d = d(scope) end
  return d
end

-- M.rules(id): a universe's rules ({tune =, look =, option =}; bind's host.rules). The universe
-- in force for a tile gives its knobs their defaults: a road's lanes are off in the snow, and
-- the page shows them off until somebody sets them on against the universe.
M.rules = nil
-- what the universe in force says of a knob, as the rule gives it (nil: nothing)
local function ruleOf(spec, scope)
  if M.rules and spec.key ~= 'universe' and specs.universe then
    local id = M.get('universe', scope)
    local rules = id and id ~= 'none' and M.rules(id) or nil
    local values = rules and rules[spec.target]
    local v = values and values[spec.field]
    if v ~= nil and spec.number then v = v ~= 0 and v ~= false end
    return v
  end
  return nil
end

local function defaultOf(spec, scope)
  local v = ruleOf(spec, scope)
  if v ~= nil then
    v = normalise(spec, v)
    if v ~= nil then return v end
  end
  return ownDefault(spec, scope)
end

function M.group(g)
  if not groups[g.key] then groupOrder[#groupOrder + 1] = g.key end
  groups[g.key] = {key = g.key, label = g.label or {uk = g.key, en = g.key}, collapsed = g.collapsed or nil}
end

-- define{key=, target='tune'|'look'|'option', field=, kind='bool'|'int'|'float'|'enum', min=, max=, step=,
--        values={{value=, label={uk=, en=}}}, default=, group=, label={uk=, en=}, hint={uk=, en=},
--        number=true, neutral=}
-- field: the name in the target table (the key itself when left out). number: a bool the
-- generator reads as 0 / 1 (TUNE's switches). default: a value, or a function for a knob that
-- follows something else until it is set (the world's quality; called with the tile's name
-- where a tile has a default of its own). neutral: the value that means nothing is asked; a
-- knob that has one is handed to the generator whenever its value in force is another, set by
-- hand or not (the universe a pack gives a tile).
function M.define(spec)
  assert(type(spec) == 'table' and type(spec.key) == 'string', 'lab.define: key')
  assert(spec.target == 'tune' or spec.target == 'look' or spec.target == 'option', 'lab.define: target of ' .. spec.key)
  assert(spec.kind == 'bool' or spec.kind == 'int' or spec.kind == 'float' or spec.kind == 'enum', 'lab.define: kind of ' .. spec.key)
  if spec.kind == 'int' or spec.kind == 'float' then
    assert(type(spec.min) == 'number' and type(spec.max) == 'number' and spec.min <= spec.max, 'lab.define: range of ' .. spec.key)
  end
  if spec.kind == 'enum' then assert(type(spec.values) == 'table' and #spec.values > 0, 'lab.define: values of ' .. spec.key) end
  if not specs[spec.key] then order[#order + 1] = spec.key end
  spec.field = spec.field or spec.key
  specs[spec.key] = spec
  M.revision = M.revision + 1
  return spec
end

function M.has(key) return specs[key] ~= nil end

-- the value in force for a tile (scope) or for the world (scope nil), and where it comes from:
-- 'tile', 'world' or 'default'
function M.get(key, scope)
  local spec = specs[key]
  if not spec then return nil end
  local own = scope and tiles[scope]
  if own and own[key] ~= nil then return own[key], 'tile' end
  if world[key] ~= nil then return world[key], 'world' end
  return defaultOf(spec, scope), 'default'
end

local function changed()
  M.revision = M.revision + 1
  if M.storage then M.storage.write(M.save()) end
end

-- set(key, value, scope): scope nil is the world. A value equal to what the level above gives
-- (the default for the world, the world's value for a tile) drops the override. Returns the
-- value in force and whether anything changed; nil and a reason when refused.
function M.set(key, value, scope)
  local spec = specs[key]
  if not spec then return nil, 'unknown knob ' .. tostring(key) end
  local v = normalise(spec, value)
  if v == nil then return nil, 'invalid value' end
  local store = world
  if scope then
    store = tiles[scope]
    if not store then store = {}; tiles[scope] = store end
  end
  -- what the level above gives: the world's value over the tile's own default, or the default
  local above
  if scope and world[key] ~= nil then above = world[key] else above = defaultOf(spec, scope) end
  local nextValue = v
  if v == above then nextValue = nil end
  local was = store[key]
  store[key] = nextValue
  if scope and next(store) == nil then tiles[scope] = nil end
  if was == nextValue then return v, false end
  changed()
  return v, true
end

-- drop one override (key) or all of a tile's (key nil); scope nil: the world's
function M.reset(key, scope)
  local store = scope and tiles[scope] or (not scope and world) or nil
  if not store then return false end
  local any = false
  if key then
    any = store[key] ~= nil
    store[key] = nil
  else
    any = next(store) ~= nil
    for k in pairs(store) do store[k] = nil end
  end
  if scope and next(store) == nil then tiles[scope] = nil end
  if any then changed() end
  return any
end

function M.resetAll()
  local any = next(world) ~= nil or next(tiles) ~= nil
  world, tiles = {}, {}
  if any then changed() end
  return any
end

-- the scopes that have overrides of their own, sorted
function M.scopes()
  local out = {}
  for scope in pairs(tiles) do out[#out + 1] = scope end
  table.sort(out)
  return out
end

function M.touched(scope)
  if scope then return tiles[scope] ~= nil end
  return next(world) ~= nil
end

-- What generator.build takes for a tile: {tune = {...}, look = {...}, option = {...}}, each nil
-- when nothing of its kind is set. The tables are shared and must not be changed by the caller.
function M.resolve(scope)
  if resolvedAt ~= M.revision then resolved, resolvedAt = {}, M.revision end
  local key = scope or ''
  local r = resolved[key]
  if r then return r end
  r = {}
  local own = scope and tiles[scope]
  for k = 1, #order do
    local spec = specs[order[k]]
    local v = own and own[spec.key]
    if v == nil then v = world[spec.key] end
    if v == nil and spec.neutral ~= nil then
      v = defaultOf(spec, scope)
      if v == spec.neutral then v = nil end
    end
    if v ~= nil then
      local t = r[spec.target]
      if not t then t = {}; r[spec.target] = t end
      if spec.number then v = v and 1 or 0 end
      t[spec.field] = v
    end
  end
  resolved[key] = r
  return r
end

-- a pack's look with the lab's slots over it (the pack's own table is never changed)
function M.lookOf(look, scope)
  local over = M.resolve(scope).look
  if not over then return look end
  local out = {}
  for k, v in pairs(type(look) == 'table' and look or {}) do out[k] = v end
  for k, v in pairs(over) do out[k] = v end
  return out
end

local function label(l, fallback)
  if type(l) == 'table' then return {uk = l.uk or l.en or fallback, en = l.en or l.uk or fallback} end
  if type(l) == 'string' then return {uk = l, en = l} end
  return {uk = fallback, en = fallback}
end

-- What the page draws: {revision=, scope=, groups={{key=, label=, collapsed=, knobs={...}}}, scopes={...}}.
-- A knob: its range, its default, the world's value, the tile's own (nil: none) and the one in force.
function M.payload(scope)
  local byGroup, out = {}, {}
  for k = 1, #order do
    local spec = specs[order[k]]
    local value, from = M.get(spec.key, scope)
    local d = {key = spec.key, target = spec.target, kind = spec.kind, label = label(spec.label, spec.key),
      hint = spec.hint and label(spec.hint, '') or nil, min = spec.min, max = spec.max,
      step = spec.step or (spec.kind == 'int' and 1 or nil), default = defaultOf(spec, scope),
      world = world[spec.key], tile = scope and tiles[scope] and tiles[scope][spec.key] or nil,
      value = value, from = from}
    if spec.kind == 'enum' then
      d.values = {}
      for i, entry in ipairs(spec.values) do
        d.values[i] = {value = entry.value, label = label(entry.label, tostring(entry.value))}
      end
    end
    local gk = spec.group or 'other'
    local g = byGroup[gk]
    if not g then
      local known = groups[gk] or {key = gk, label = {uk = gk, en = gk}}
      g = {key = known.key, label = known.label, collapsed = known.collapsed, knobs = {}}
      byGroup[gk] = g
    end
    g.knobs[#g.knobs + 1] = d
  end
  for _, key in ipairs(groupOrder) do
    if byGroup[key] then out[#out + 1] = byGroup[key]; byGroup[key] = nil end
  end
  for k = 1, #order do
    local g = byGroup[specs[order[k]].group or 'other']
    if g then out[#out + 1] = g; byGroup[g.key] = nil end
  end
  return {revision = M.revision, scope = scope, groups = out, scopes = M.scopes(), worldTouched = next(world) ~= nil,
    tileTouched = scope and tiles[scope] ~= nil or false}
end

-- What is in force for a tile (or the world), for a reader: the proving ground's page shows it
-- beside the tile. groups: a list of group keys whose knobs are all listed with their value in
-- force ({key, label, value, text, from}); changed: every other knob that is not at its own
-- default. from: 'tile', 'world', 'universe' (a rule of the universe in force gives the value)
-- or 'default'. text: an enum's label for the value.
function M.report(scope, groupKeys)
  local whole = {}
  for _, key in ipairs(groupKeys or {}) do whole[key] = {} end
  local changed = {}
  for k = 1, #order do
    local spec = specs[order[k]]
    local value, from = M.get(spec.key, scope)
    local own = ownDefault(spec, scope)
    if from == 'default' and value ~= own then
      from = 'universe'
      -- the number the generator is given is the rule's own, not the knob's nearest step
      local rule = ruleOf(spec, scope)
      if type(rule) == 'number' then value = rule end
    end
    local entry = {key = spec.key, group = spec.group or 'other', label = label(spec.label, spec.key), value = value, from = from}
    if spec.kind == 'enum' then
      for _, choice in ipairs(spec.values) do
        if choice.value == value then entry.text = label(choice.label, tostring(value)) end
      end
    end
    local list = whole[entry.group]
    if list then
      list[#list + 1] = entry
    elseif from ~= 'default' then
      entry.default = own
      changed[#changed + 1] = entry
    end
  end
  return {groups = whole, changed = changed}
end

-- --- settings/earthng-lab.json ---------------------------------------------------------------------
function M.save()
  local w, t = {}, {}
  for k, v in pairs(world) do w[k] = v end
  for scope, store in pairs(tiles) do
    local copy = {}
    for k, v in pairs(store) do copy[k] = v end
    t[scope] = copy
  end
  return {schema = M.schema, world = w, tiles = t}
end

-- Takes what a file holds: unknown knobs and values out of range are left out, never an error.
function M.load(cfg)
  if cfg == nil and M.storage then cfg = M.storage.read() end
  world, tiles = {}, {}
  if type(cfg) == 'table' and cfg.schema == M.schema then
    for k, v in pairs(type(cfg.world) == 'table' and cfg.world or {}) do
      local spec = specs[k]
      local value = spec and normalise(spec, v)
      if value ~= nil and value ~= ownDefault(spec, nil) then world[k] = value end
    end
    for scope, store in pairs(type(cfg.tiles) == 'table' and cfg.tiles or {}) do
      if type(scope) == 'string' and type(store) == 'table' then
        local own = {}
        for k, v in pairs(store) do
          local spec = specs[k]
          local value = spec and normalise(spec, v)
          if value ~= nil then own[k] = value end
        end
        if next(own) then tiles[scope] = own end
      end
    end
  end
  M.revision = M.revision + 1
  return M
end

-- --- the knobs there are ---------------------------------------------------------------------------
local function choices(list)
  local out = {}
  for i, entry in ipairs(list) do out[i] = {value = entry[1], label = {uk = entry[2], en = entry[3] or entry[2]}} end
  return out
end

-- TUNE's fields with a name and a range of their own; the rest of its numbers get a plain slider
-- in 'advanced' (bind), so a knob added to the generator is on the page without a change here.
local KNOWN = {
  seat = {group = 'road', kind = 'bool', number = true, label = {uk = 'Дорога посаджена на землю', en = 'Road seated on the land'},
    hint = {uk = 'Нахил за схилом, узбіччя, бордюри в дворах', en = 'Leans with the slope, verges, kerbed yards'}},
  smooth = {group = 'road', kind = 'bool', number = true, label = {uk = 'Заокруглені повороти', en = 'Rounded plan corners'}},
  lanes = {group = 'road', kind = 'bool', number = true, label = {uk = 'Асфальт смугами', en = 'Asphalt drawn as lanes'}},
  taper = {group = 'road', kind = 'bool', number = true, label = {uk = 'Плавне звуження', en = 'Width taper at joins'}},
  wear = {group = 'road', kind = 'bool', number = true, label = {uk = 'Знос: латки, тріщини, люки', en = 'Wear: patches, cracks, covers'}},
  ruts = {group = 'road', kind = 'bool', number = true, label = {uk = 'Колії на ґрунтових', en = 'Ruts on unpaved roads'}},
  crown = {group = 'road', kind = 'float', min = 0, max = .08, step = .005, label = {uk = 'Опуклість проїзду, м на метр', en = 'Crown, m per metre'}},
  roadLift = {group = 'road', kind = 'float', min = 0, max = .5, step = .01, label = {uk = 'Дорога над профілем, м', en = 'Road over its profile, m'}},
  sidewalk = {group = 'road', kind = 'float', min = 0, max = 6, step = .25, label = {uk = 'Ширина тротуару, м', en = 'Sidewalk width, m'}},
  curb = {group = 'road', kind = 'float', min = 0, max = 1, step = .05, label = {uk = 'Ширина бордюру, м', en = 'Kerb width, m'}},
  shoulder = {group = 'road', kind = 'float', min = 0, max = 8, step = .25, label = {uk = 'Узбіччя, м', en = 'Shoulder, m'}},
  mitre = {group = 'road', kind = 'float', min = 0, max = 6, step = .25, label = {uk = 'Межа гострого кута', en = 'Mitre limit'}},
  groundDrop = {group = 'ground', kind = 'float', min = -.3, max = .6, step = .01, default = 'seatDrop',
    label = {uk = 'Земля нижче краю дороги, м', en = 'Ground under the road edge, m'}},
  margin = {group = 'ground', kind = 'float', min = 0, max = .5, step = .01, default = 'seatMargin',
    label = {uk = 'Земля притиснута під дорогою, м', en = 'Ground pressed under the road, m'}},
  pullFull = {group = 'ground', kind = 'float', min = 0, max = 60, step = 1, label = {uk = 'Земля йде за дорогою до, м', en = 'Ground follows the road within, m'}},
  pullZero = {group = 'ground', kind = 'float', min = 5, max = 200, step = 5, label = {uk = 'Вплив дороги зникає на, м', en = 'Road pull ends at, m'}},
  terrainStep = {group = 'ground', kind = 'enum', default = 'seatStep',
    values = choices({{6.25, '6,25 м', '6.25 m'}, {12.5, '12,5 м', '12.5 m'}, {25, '25 м', '25 m'}, {50, '50 м', '50 m'}}),
    label = {uk = 'Крок сітки землі', en = 'Ground lattice step'}},
  vergeCut = {group = 'ground', kind = 'float', min = 0, max = 4, step = .25, label = {uk = 'Зріз узбіччя, м', en = 'Verge cut, m'}},
  vergeSink = {group = 'ground', kind = 'float', min = 0, max = 1, step = .05, label = {uk = 'Просідання узбіччя, м', en = 'Verge sink, m'}},
}
-- never a knob: other fields derive them, or they are not numbers a slider can hold
local HIDDEN = {seatDrop = true, seatMargin = true, seatStep = true, pressEven = true}

local BLOCKS = {{'postsoviet', 'Пострадянський', 'Post-Soviet'}, {'central', 'Центральна Європа', 'Central Europe'},
  {'western', 'Західна Європа', 'Western Europe'}, {'nordic', 'Північ', 'Nordic'}, {'british', 'Британія', 'British'},
  {'mediterranean', 'Середземномор’я', 'Mediterranean'}, {'north-america', 'Північна Америка', 'North America'},
  {'latin', 'Латинська Америка', 'Latin America'}, {'east-asia', 'Східна Азія', 'East Asia'},
  {'south-asia', 'Південна Азія', 'South Asia'}, {'southeast-asia', 'Південно-Східна Азія', 'South-East Asia'},
  {'middle-east', 'Близький Схід', 'Middle East'}, {'africa', 'Африка', 'Africa'}, {'oceania', 'Океанія', 'Oceania'},
  {'general', 'Загальний', 'General'}}

-- bind{tune = generator.TUNE, look = the pack's look, kitStyles = {...}, kitWalls = {...},
--      quality = function(key) return the world's quality value end}
-- Defines every knob. Called again after a landing: the defaults of the look follow the pack.
function M.bind(host)
  host = host or {}
  local tune = host.tune or {}
  specs, order, groups, groupOrder = {}, {}, {}, {}
  M.rules = host.rules
  M.group{key = 'universe', label = {uk = 'Всесвіт', en = 'Universe'}}
  M.group{key = 'look', label = {uk = 'Набір асетів і текстур', en = 'Assets and textures'}}
  M.group{key = 'buildings', label = {uk = 'Будівлі', en = 'Buildings'}}
  M.group{key = 'road', label = {uk = 'Дорога', en = 'Road'}}
  M.group{key = 'ground', label = {uk = 'Земля біля дороги', en = 'Ground by the road'}}
  M.group{key = 'detail', label = {uk = 'Наповнення', en = 'Content'}}
  M.group{key = 'advanced', label = {uk = 'Інші числа генератора', en = 'Other generator numbers'}, collapsed = true}

  -- A universe (universe.lua): the climate, the region, the materials and the ground's physics
  -- of another world over the same map. host.universes: {{id, uk, en}}; host.universeOf(scope):
  -- the universe a pack names for a tile of its own. The knobs under it win over its rules.
  local none = {{'none', 'Свій', 'Its own'}}
  if host.universes and #host.universes > 0 then
    local list = {none[1]}
    for _, entry in ipairs(host.universes) do list[#list + 1] = entry end
    M.define{key = 'universe', target = 'option', kind = 'enum', group = 'universe', values = choices(list), neutral = 'none',
      default = function(scope)
        local id = scope and host.universeOf and host.universeOf(scope)
        for _, entry in ipairs(list) do if entry[1] == id then return id end end
        return 'none'
      end,
      label = {uk = 'Правила якого світу', en = 'Whose rules'},
      hint = {uk = 'Клімат, регіон, матеріали доріг, дахів і землі, фізика ґрунту', en = 'Climate, region, materials of roads, roofs and land, ground physics'}}
  end
  if host.climates and #host.climates > 0 then
    local list = {{'auto', 'За місцем або всесвітом', 'By the place or the universe'}}
    for _, name in ipairs(host.climates) do list[#list + 1] = {name, name, name} end
    M.define{key = 'climate', target = 'option', kind = 'enum', group = 'universe', values = choices(list), default = 'auto',
      label = {uk = 'Клімат', en = 'Climate'}}
  end
  -- The woods of a natural zone (flora.lua ZONES), whatever the place: a Polissia pinewood, a
  -- Carpathian beech wood or a rainforest on any tile. host.floraZones: {{id, uk, en}}.
  if host.floraZones and #host.floraZones > 0 then
    local list = {{'auto', 'За місцем і кліматом', 'By the place and the climate'}}
    for _, entry in ipairs(host.floraZones) do list[#list + 1] = entry end
    M.define{key = 'floraZone', target = 'option', kind = 'enum', group = 'universe', values = choices(list), default = 'auto',
      label = {uk = 'Природна зона рослинності', en = 'Vegetation zone'},
      hint = {uk = 'Які дерева, кущі й трави ростуть: з пака флори', en = 'Which trees, shrubs and herbs grow: from the flora pack'}}
  end
  M.define{key = 'feel', target = 'option', kind = 'enum', group = 'universe', default = 'auto',
    values = choices({{'auto', 'Як вирішує всесвіт', 'As the universe decides'}, {'on', 'Увімкнено', 'On'}, {'off', 'Вимкнено', 'Off'}}),
    label = {uk = 'Фізика ґрунту за видом землі', en = 'Ground physics by the land drawn'},
    hint = {uk = 'Сніг, пісок і багно під колесами; інакше всюди трава', en = 'Snow, sand and mud under the tyres; grass everywhere otherwise'}}

  -- host.look: the pack's look, or a function that returns it (the landing changes it)
  local function lookNow()
    local look = host.look
    if type(look) == 'function' then look = look() end
    return type(look) == 'table' and look or {}
  end
  local function slot(key, list, uk, en, fallback)
    M.define{key = 'look.' .. key, field = key, target = 'look', kind = 'enum', group = 'look', values = choices(list),
      default = function()
        local value = lookNow()[key]
        for _, entry in ipairs(list) do if entry[1] == value then return value end end
        return fallback
      end, label = {uk = uk, en = en}}
  end
  slot('block', BLOCKS, 'Регіон (стіни, дахи, паркани, меблі)', 'Region (walls, roofs, fences, props)', 'general')
  slot('asphalt', {{'smooth', 'Рівний', 'Smooth'}, {'worn', 'Зношений', 'Worn'}, {'fresh', 'Свіжий', 'Fresh'}}, 'Асфальт', 'Asphalt', 'smooth')
  slot('markings', {{'white', 'Біла', 'White'}, {'yellow', 'Жовта', 'Yellow'}, {'none', 'Без розмітки', 'None'}}, 'Розмітка', 'Markings', 'white')
  slot('verge', {{'grass', 'Трава', 'Grass'}, {'dirt', 'Ґрунт', 'Dirt'}, {'dry', 'Суха трава', 'Dry grass'}, {'gravel', 'Гравій', 'Gravel'}},
    'Узбіччя', 'Verge', 'grass')
  slot('buildings', {{'panel', 'Панель і лоджії', 'Panel and loggias'}, {'brick', 'Цегла', 'Brick'}, {'plaster', 'Тиньк', 'Plaster'},
    {'mixed', 'Змішано', 'Mixed'}}, 'Будівлі без тегів', 'Untagged buildings', 'mixed')
  slot('trees', {{'regional', 'За широтою', 'By latitude'}, {'broadleaf', 'Листяні', 'Broadleaf'}, {'mixed', 'Мішані', 'Mixed'},
    {'conifer', 'Хвойні', 'Conifer'}}, 'Дерева', 'Trees', 'regional')
  slot('statics', {{'street', 'Ліхтарі й зупинки', 'Lamps and stops'}, {'sparse', 'Лише зупинки', 'Stops only'},
    {'none', 'Без меблів', 'None'}}, 'Вуличні меблі', 'Street props', 'street')

  -- the building kit (kit.lua): on or off, and one style or one wall for every block of a tile
  local auto = {{'auto', 'Як вирішує генератор', 'As the generator decides'}}
  M.define{key = 'kit', target = 'option', kind = 'enum', group = 'buildings', default = 'auto',
    values = choices({auto[1], {'on', 'Увімкнено', 'On'}, {'off', 'Вимкнено', 'Off'}}),
    label = {uk = 'Конструктор фасадів', en = 'Facade kit'}}
  local function named(list)
    local out = {auto[1]}
    for _, name in ipairs(list or {}) do out[#out + 1] = {name, name, name} end
    return out
  end
  if host.kitStyles and #host.kitStyles > 0 then
    M.define{key = 'kitStyle', target = 'option', kind = 'enum', group = 'buildings', default = 'auto', values = choices(named(host.kitStyles)),
      label = {uk = 'Стиль усіх будинків тайла', en = 'Style of every building'}}
  end
  -- houses of one and two storeys (houses.lua): a country's lists in place of the place's own,
  -- or one style for every house of a tile
  if host.houseCountries and #host.houseCountries > 0 then
    M.define{key = 'houseCountry', target = 'option', kind = 'enum', group = 'buildings', default = 'auto', values = choices(named(host.houseCountries)),
      label = {uk = 'Хати за країною', en = 'Houses as in the country'}}
  end
  if host.houseStyles and #host.houseStyles > 0 then
    M.define{key = 'houseStyle', target = 'option', kind = 'enum', group = 'buildings', default = 'auto', values = choices(named(host.houseStyles)),
      label = {uk = 'Стиль усіх хат тайла', en = 'Style of every house'}}
  end
  if host.kitWalls and #host.kitWalls > 0 then
    M.define{key = 'kitWall', target = 'option', kind = 'enum', group = 'buildings', default = 'auto', values = choices(named(host.kitWalls)),
      label = {uk = 'Стіна всіх будинків тайла', en = 'Wall of every building'}}
  end

  for name, known in pairs(KNOWN) do
    if tune[name] ~= nil then
      local spec = {key = name, target = 'tune'}
      for k, v in pairs(known) do spec[k] = v end
      local d = spec.default
      if type(d) == 'string' then d = tune[d] else d = tune[name] end
      if spec.kind == 'bool' then d = d ~= 0 and d ~= false end
      spec.default = d
      spec.order = name
      M.define(spec)
    end
  end
  local rest = {}
  for name, value in pairs(tune) do
    if not KNOWN[name] and not HIDDEN[name] and type(value) == 'number' then rest[#rest + 1] = name end
  end
  table.sort(rest)
  for _, name in ipairs(rest) do
    local value = tune[name]
    local top = math.max(1, math.abs(value) * 4)
    M.define{key = name, target = 'tune', kind = 'float', group = 'advanced', min = value < 0 and -top or 0, max = top,
      step = top / 200, default = value, label = {uk = name, en = name}}
  end

  local quality = host.quality or function() return nil end
  local function follows(key, uk, en, lo, hi, step, kind)
    M.define{key = key, target = 'option', kind = kind or 'int', group = 'detail', min = lo, max = hi, step = step,
      default = function() return quality(key) or lo end, label = {uk = uk, en = en}}
  end
  follows('detail', 'Деталізація, 0–100', 'Detail, 0-100', 0, 100, 5)
  follows('propSpacing', 'Меблі на тротуарі кожні, м (0: немає)', 'Street props every, m (0: none)', 0, 60, 1)
  follows('maxTrees', 'Дерев на тайл', 'Trees a tile', 0, 4000, 50)
  follows('maxGrass', 'Трави на тайл', 'Grass a tile', 0, 60000, 500)
  follows('maxRocks', 'Каміння на тайл', 'Rocks a tile', 0, 2000, 25)
  follows('forestSpacing', 'Крок лісу, м', 'Forest spacing, m', 3, 30, .5, 'float')
  follows('groundSpacing', 'Крок трави, м', 'Ground cover spacing, m', 1, 30, .5, 'float')
  M.define{key = 'hyper', target = 'option', kind = 'enum', group = 'detail', default = 'auto',
    values = choices({auto[1], {'on', 'Увімкнено', 'On'}, {'off', 'Вимкнено', 'Off'}}),
    label = {uk = 'Знаки, світлофори, стрілки смуг', en = 'Signs, signals, lane arrows'}}
  M.define{key = 'experimentalDetail', target = 'option', kind = 'enum', group = 'detail', default = 'auto',
    values = choices({auto[1], {'on', 'Увімкнено', 'On'}, {'off', 'Вимкнено', 'Off'}}),
    label = {uk = 'Деталі міста (фасади, адреси, парковка)', en = 'City details (facades, addresses, parking)'}}
  M.define{key = 'experimentalShopfront', target = 'option', kind = 'enum', group = 'detail', default = 'auto',
    values = choices({auto[1], {'on', 'Увімкнено', 'On'}, {'off', 'Вимкнено', 'Off'}}),
    label = {uk = 'Вітрини за дверима з мапи', en = 'Storefronts from mapped doors'}}

  -- the order inside a group: the look and the switches as defined, TUNE's known knobs by name
  local head, tail = {}, {}
  for _, key in ipairs(order) do
    if specs[key].order then tail[#tail + 1] = key else head[#head + 1] = key end
  end
  table.sort(tail, function(a, b)
    local sa, sb = specs[a], specs[b]
    if (sa.kind == 'bool') ~= (sb.kind == 'bool') then return sa.kind == 'bool' end
    return a < b
  end)
  order = {}
  for _, key in ipairs(head) do order[#order + 1] = key end
  for _, key in ipairs(tail) do order[#order + 1] = key end
  M.revision = M.revision + 1
  return M
end

-- 'auto' / 'on' / 'off' of an option knob as the generator's nil / true / false; first: what
-- the caller would pass with the lab untouched
function M.switch(value, first)
  if value == 'on' then return true end
  if value == 'off' then return false end
  return first
end

return M
