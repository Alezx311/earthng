-- Building kit: a facade assembled from small blocks instead of one textured quad a wall.
--
-- A style (M.styles) is a recipe of blocks: a plinth, floors split into bays, a window in its
-- reveal with a sill, a balcony box, an entrance with a canopy, string courses and a cornice.
-- A region (M.regions) says which styles its towns are built of. The building's own hash picks
-- the style, the wall, the pattern of bays and every flat's window, so two blocks of one series
-- still differ, and a block is the same in both tiles it straddles.
--
-- Everything is geometry in the tile's own mesh (scene.polygon): three materials for a whole
-- street (the wall, kit_cells, kit_trim), no object per window. The art is made by
-- earthng/kit_art.py; kit_cells.lua, generated there, holds the atlas cells, the trim bands and
-- the metres a repeat of each wall.
local M = {}
local NONE = {}
local floor, max, min, sqrt, abs = math.floor, math.max, math.min, math.sqrt, math.abs

local okData, DATA = pcall(require, 'ge/extensions/e2r/kit_cells')
if not okData or type(DATA) ~= 'table' then DATA = {cells = {}, bands = {}, walls = {}} end
M.data = DATA
M.ART = '/e2r_stream/fast-art/v10/real/kit_cells.color.dds'
M.CELLS, M.CELLS2, M.TRIM = 'kit_cells', 'kit_cells2', 'kit_trim'

local HMOD = 2147483647
local function ih(seed, a, b)
  local h = (seed * 1000003 + a) % HMOD
  h = (h * 1000003 + (b or 0)) % HMOD
  h = (h * 48271 + 11) % HMOD
  return (h * 48271 + 7) % HMOD
end
M.ih = ih
local function unit(seed, a, b) return ih(seed, a, b) / HMOD end
local function pick(list, n) return list[n % #list + 1] end

-- 'a 3 b 1' -> {'a', 'a', 'a', 'b'}
local function words(spec)
  local out = {}
  for name, weight in spec:gmatch('(%S+) (%d+)') do
    for _ = 1, tonumber(weight) do out[#out + 1] = name end
  end
  return out
end

-- ---------------------------------------------------------------------------------------------
-- Styles. Lengths in metres. A pattern is the run of bays along a wall, repeated:
--   W window, D wide window, T tall window, K small window, B balcony, S stair (door at the ground),
--   F full-height window, - blank.
-- `front` faces the street, `back` the yard with the entrances; `ends` is a short end wall.
M.styles = {
  -- Soviet large-panel series, 9 to 16 floors: gravel panels, joints, balconies stacked in columns
  panel = {
    floor = 2.8, bay = 3.2, plinth = 1.0, attic = 1.3, margin = .15, ac = 9, patches = 11,
    walls = words('panel_pebble 3 panel_pebble_beige 3 panel_pebble_warm 2 panel_tile 2 panel_tile_blue 1 panel_tile_beige 2'),
    plinthWall = {'concrete'}, panels = true,
    front = {'WBW', 'BWWBW', 'WBWD', 'BWW'}, back = {'WKSKW', 'WSKW', 'KSKWW'}, ends = {'-', 'cW', 'cB', 'cW'},
    W = words('w_sov3 3 w_pvc_blinds 3 w_pvc_cat 2 w_laundry 1 w_wood_blue 1 w_pvc_brown 1'),
    D = words('w_panel3 3 w_pvc3 3'), K = {'w_kitchen', 'w_pvc_blinds'}, S = {'w_stair'},
    ground = words('w_grille 2 w_pvc_blinds 2 w_sov3 1'),
    size = {W = {1.45, 1.5}, D = {2.05, 1.5}, K = {.95, 1.2}, S = {1.2, 1.2}}, sill = .85, reveal = .13,
    balcony = {depth = 1.05, parapet = words('asbestos 3 asbestos_blue 1 corrugated_white 2 corrugated_green 1 concrete 2'),
      glazed = .65, glass = words('g_wood_white 3 g_pvc 3 g_alu 2 g_wood_brown 1 g_wood_green 1'), door = {'d_balc_wood', 'd_balc_pvc'}},
    doors = {'d_steel_grey', 'd_steel_brown'}, porch = 'slab',
    cornice = {'cornice_plain', .3, .35},
  },
  -- brick blocks of the 1960s-80s, 5 to 9 floors
  brick = {
    floor = 2.8, bay = 3.0, plinth = .9, attic = .7, margin = .45, ac = 9, patches = 8,
    walls = words('brick_silicate 4 brick_red 3 brick_yellow 3'),
    plinthWall = {'concrete', 'plaster_rough'},
    front = {'WWBW', 'WBWW', 'WDBW'}, back = {'WKSKW', 'WWSW', 'KSKW'}, ends = {'-W-', '-', 'WW'},
    W = words('w_sov3 3 w_pvc_blinds 3 w_pvc_cat 1 w_laundry 1 w_wood_blue 2 w_pvc_brown 2'),
    D = words('w_panel3 2 w_pvc3 3'), K = {'w_kitchen', 'w_pvc_blinds'}, S = {'w_stair'},
    ground = words('w_grille 3 w_pvc_blinds 2 w_sov3 1'),
    size = {W = {1.4, 1.5}, D = {1.9, 1.5}, K = {.9, 1.2}, S = {1.2, 1.2}}, sill = .85, reveal = .2,
    balcony = {depth = .95, parapet = words('asbestos 3 corrugated_white 2 corrugated_green 1 corrugated_blue 1 asbestos_blue 1'),
      glazed = .55, glass = words('g_wood_white 3 g_pvc 3 g_alu 1 g_wood_brown 2 g_wood_green 1'), door = {'d_balc_wood', 'd_balc_pvc'}},
    doors = {'d_steel_grey', 'd_steel_brown'}, porch = 'slab',
    cornice = {'cornice_plain', .25, .3},
  },
  -- Stalin-era neoclassical, 4 to 8 floors: rusticated ground floor, tall windows in casings,
  -- string courses, a heavy cornice
  stalin = {
    floor = 3.3, bay = 3.3, plinth = 1.0, attic = 1.0, margin = .8, ac = 7,
    walls = words('plaster_smooth_cream 3 plaster_smooth_yellow 3 plaster_smooth_peach 2 plaster_aged_grey 2 plaster_aged_yellow 2 plaster_smooth_pink 1'),
    plinthWall = {'granite'}, groundWall = {'rustic_cream', 'rustic_grey'},
    front = {'TTBTT', 'TBT', 'TTT'}, back = {'TTSTT', 'TST'}, ends = {'T', 'TT'},
    T = words('w_stalin6 3 w_stalin2 3 w_pvc_blinds 1'), S = {'w_stalin6'}, ground = {'w_stalin2', 'w_grille'},
    size = {T = {1.25, 1.95}, S = {1.2, 1.5}}, sill = .8, reveal = .22, casing = .14,
    balcony = {depth = .8, parapet = {'plaster_smooth_white'}, glazed = .15, glass = {'g_wood_white', 'g_pvc'}, door = {'d_balc_wood'}, every = 2},
    doors = {'d_old_double'}, porch = 'portal',
    cornice = {'cornice_stalin', .55, .7}, courses = {'string_course', 1, -1}, frieze = 'frieze',
  },
  -- before 1917: brick or plaster, tall arched windows in casings, a frieze under the cornice
  oldtown = {
    floor = 3.5, bay = 2.7, plinth = .7, attic = .9, margin = .6, ac = 7,
    walls = words('brick_old 4 plaster_aged_yellow 2 plaster_aged_cream 2 plaster_aged_pink 1 plaster_aged_green 1 plaster_smooth_cream 1'),
    plinthWall = {'granite', 'rustic_grey'},
    front = {'TTT', 'TTBT'}, back = {'TTT', 'TST'}, ends = {'T', 'TT', '-'},
    T = words('w_arch 3 w_stalin2 3 w_stalin6 2'), S = {'w_arch'}, ground = {'w_stalin2', 'w_arch'},
    size = {T = {1.15, 2.05}, S = {1.1, 1.6}}, sill = .85, reveal = .25, casing = .16,
    balcony = {depth = .75, parapet = {'plaster_smooth_white'}, glazed = .1, glass = {'g_wood_white'}, door = {'d_balc_wood'}, every = 2, rail = true},
    doors = {'d_old_double'}, porch = 'portal',
    cornice = {'cornice_classic', .45, .55}, courses = {'string_course', 1}, frieze = 'frieze',
  },
  -- this century: ventilated panels or brick, big dark windows, glazed loggias
  modern = {
    floor = 3.0, bay = 3.6, plinth = .3, attic = 1.1, margin = .3, ac = 13,
    walls = words('fibre_panel_white 5 fibre_panel_grey 5 fibre_panel_dark 2 fibre_panel_orange 1 brick_brown 4 plaster_smooth_white 4 plaster_smooth_cream 2'),
    plinthWall = {'granite', 'fibre_panel_dark'},
    front = {'FWBW', 'WBFB', 'FBW'}, back = {'WWSWW', 'FSW'}, ends = {'WW', 'F', '-W-'},
    W = words('w_dark 4 w_pvc_blinds 2 w_pvc_cat 1'), F = {'w_full'}, S = {'w_dark'}, ground = {'w_dark', 'w_full'},
    size = {W = {1.5, 1.6}, F = {1.7, 2.3}, S = {1.3, 1.4}}, sill = .8, reveal = .16, sillF = .12,
    balcony = {depth = 1.2, parapet = words('fibre_panel_white 2 fibre_panel_grey 2 fibre_panel_dark 2'), glazed = .9,
      glass = words('g_dark 5 g_pvc 1 g_alu 1'), door = {'d_balc_pvc'}},
    doors = {'d_glass'}, porch = 'glass',
    cornice = {'coping', .08, .2},
  },
  -- two and three floors of plaster or brick: a town's ordinary old stock
  low = {
    floor = 3.1, bay = 2.9, plinth = .6, attic = .5, margin = .5, ac = 10,
    walls = words('plaster_aged_yellow 3 plaster_aged_cream 3 plaster_aged_grey 2 plaster_aged_pink 1 plaster_aged_green 1 brick_red 3 brick_silicate 3 plaster_rough 2'),
    plinthWall = {'concrete', 'plaster_rough'},
    front = {'WW', 'WWW'}, back = {'WSW', 'WW'}, ends = {'W', '-'},
    W = words('w_sov3 3 w_pvc_blinds 3 w_wood_blue 2 w_pvc_brown 2 w_pvc_cat 1'), S = {'w_kitchen'}, ground = words('w_grille 1 w_sov3 2 w_pvc_blinds 2'),
    size = {W = {1.35, 1.5}, S = {.9, 1.2}}, sill = .9, reveal = .18,
    doors = {'d_steel_brown', 'd_steel_grey', 'd_basement'}, porch = 'slab',
    cornice = {'cornice_plain', .22, .28},
  },
  -- Britain and Ireland: stock brick, sash windows, a panelled door with a fanlight
  british = {
    floor = 3.0, bay = 2.6, plinth = .35, attic = .5, margin = .5,
    walls = words('brick_london 5 brick_red 2 brick_brown 1 plaster_smooth_white 1 plaster_smooth_cream 1'),
    plinthWall = {'plaster_smooth_white', 'brick_london'},
    front = {'TT', 'TTT'}, back = {'TST', 'TT'}, ends = {'T', '-'},
    T = words('w_sash66 3 w_sash22 4 w_upvc 1'), S = {'w_sash22'}, ground = {'w_sash22', 'w_sash66'},
    size = {T = {1.1, 1.85}, S = {1.0, 1.5}}, sill = .8, reveal = .12, casing = .1,
    doors = {'d_uk_red', 'd_uk_black', 'd_modern'}, porch = 'none', doorStreet = true,
    cornice = {'string_course', .1, .25}, lintel = 'string_course',
  },
  -- North American brick walk-ups and brownstones: double-hung windows, a bracketed cornice
  american = {
    floor = 3.2, bay = 2.4, plinth = .9, attic = .9, margin = .5, ac = 5,
    walls = words('brick_us 5 brownstone 3 brick_brown 1 limestone 1'),
    plinthWall = {'brownstone', 'limestone'},
    front = {'TTT', 'TT'}, back = {'TST', 'TT'}, ends = {'T', '-'},
    T = words('w_hung 4 w_sash22 2 w_upvc 1'), S = {'w_hung'}, ground = {'w_hung'},
    size = {T = {1.0, 1.75}, S = {1.0, 1.5}}, sill = .75, reveal = .16, casing = .12,
    doors = {'d_brownstone', 'd_us_white'}, porch = 'stoop', doorStreet = true,
    cornice = {'cornice_classic', .5, .6}, lintel = 'string_course',
  },
  -- continental Europe: stone or warm stucco, tall windows with shutters or a rail
  euro = {
    floor = 3.2, bay = 2.8, plinth = .5, attic = .8, margin = .6, ac = 4,
    walls = words('limestone 3 stucco_warm_cream 3 stucco_warm_ochre 2 stucco_warm_pink 1 plaster_smooth_white 2 plaster_smooth_cream 1'),
    plinthWall = {'limestone', 'granite'},
    front = {'TTT', 'TTBT'}, back = {'TST', 'TT'}, ends = {'T', '-'},
    T = words('w_paris 3 w_shutters 3 w_german 2 w_cottage 1'), S = {'w_german'}, ground = {'w_german', 'w_paris'},
    size = {T = {1.2, 2.0}, S = {1.1, 1.5}}, sill = .7, reveal = .18, casing = .12,
    balcony = {depth = .6, parapet = {'plaster_smooth_white'}, glazed = 0, glass = {'g_wood_white'}, door = {'w_paris'}, every = 2, rail = true},
    doors = {'d_french', 'd_modern'}, porch = 'none', doorStreet = true,
    cornice = {'cornice_classic', .4, .5}, courses = {'string_course', 1},
  },
}
-- the South: tiles or sun-bleached stucco, shutters, a balcony door behind an iron rail
M.styles.med = {
  floor = 3.2, bay = 2.8, plinth = .4, attic = .7, margin = .6, ac = 9,
  walls = words('azulejo 3 azulejo_green 1 stucco_warm_cream 3 stucco_warm_ochre 3 stucco_warm_pink 2 whitewash 2 limestone 1'),
  plinthWall = {'limestone', 'granite'},
  front = {'TBT', 'TTBT', 'BTB', 'TT'}, back = {'TST', 'TT'}, ends = {'T', '-'},
  T = words('m_shut_green 3 m_shut_brown 2 m_shut_turq 2 m_blind 2 m_arch 1 m_modern 1'), S = {'m_small'},
  ground = {'m_shut_brown', 'm_blind'},
  size = {T = {1.15, 1.95}, S = {.85, .85}}, sill = .6, reveal = .2, casing = .12,
  balcony = {depth = .5, parapet = {'plaster_smooth_white'}, glazed = 0, glass = {'g_wood_white'}, door = {'m_balc_rail'}, rail = true},
  doors = {'md_green', 'md_blue', 'md_brown', 'md_brown2', 'md_red', 'md_modern'}, porch = 'none', doorStreet = true,
  cornice = {'cornice_classic', .35, .45}, courses = {'string_course', 1},
}
-- Cells drawn with their open shutters: they lie on the wall at their own size, not in a reveal.
M.proud = {m_shut_green = true, m_shut_turq = true, w_shutters = true, m_balc_rail = true}

-- Region block (generator BLD.spec's names) -> styles by height: tall >= 24 m, mid >= 11 m, low.
M.regions = {
  postsoviet = {tall = words('panel 7 modern 3 brick 1'), high = words('panel 4 stalin 3 brick 2 modern 2'), mid = words('brick 4 panel 3 stalin 3 modern 1'), low = words('low 5 oldtown 3 stalin 1 brick 1')},
  central = {tall = words('panel 5 modern 4'), mid = words('euro 4 brick 2 panel 2 stalin 1 modern 1'), low = words('euro 4 low 3 oldtown 2')},
  british = {tall = words('modern 5 brick 1'), mid = words('british 5 modern 2'), low = words('british 8 modern 1')},
  ['north-america'] = {tall = words('modern 4 american 2'), mid = words('american 6 modern 2'), low = words('american 6 modern 1')},
  oceania = {tall = words('modern 5'), mid = words('british 3 modern 3'), low = words('british 4 modern 1')},
  western = {tall = words('modern 5 euro 1'), mid = words('euro 6 modern 2'), low = words('euro 7 modern 1')},
  nordic = {tall = words('modern 4 panel 1'), mid = words('euro 3 modern 3 brick 1'), low = words('euro 4 modern 2')},
  mediterranean = {tall = words('modern 4 med 2'), mid = words('med 6 euro 1 modern 1'), low = words('med 8')},
  general = {tall = words('modern 4 panel 1'), mid = words('euro 2 modern 2 brick 1'), low = words('low 2 euro 2')},
}
for _, block in ipairs({'latin', 'east-asia', 'south-asia', 'southeast-asia', 'middle-east', 'africa'}) do
  M.regions[block] = {tall = words('modern 5 panel 1'), mid = words('modern 3 med 2 low 1'), low = words('low 3 med 3')}
end

-- What the kit builds: blocks of flats and public buildings. Houses, sheds, plants, churches and
-- towers keep the generator's own walls.
-- A flat that has insulated its own piece of the facade: a slab of foam and render over its
-- bay, in whatever paint the owner chose. Every panel block of the 2010s has a dozen.
M.PATCH = {'plaster_smooth_cream', 'plaster_smooth_peach', 'plaster_smooth_yellow', 'plaster_smooth_white',
  'plaster_smooth_pink', 'plaster_smooth_grey'}
M.uses = {yes = true, apartments = true, residential = true, dormitory = true, hotel = true, school = true,
  university = true, college = true, hospital = true, public = true, civic = true, government = true,
  kindergarten = true, office = true, commercial = true, retail = true}
M.MIN = {height = 5.6, area = 55, detail = 40}

-- The kit's art in this planet, or options.kit: true forces it (tests, the bench), false keeps
-- the generator's own walls.
function M.enabled(options)
  options = options or NONE
  if options.kit ~= nil then return options.kit and true or false end
  -- the way back without a rebuild of the planet: E2R_KIT = false in the game's Lua console,
  -- then land again
  if rawget(_G, 'E2R_KIT') == false then return false end
  if options.realStyle == false or options.far or options.horizon then return false end
  if M.found == nil then
    M.found = (FS and next(DATA.cells) and FS:fileExists(M.ART)) and true or false
  end
  return M.found
end

-- A footprint that is no plain slab: a court inside it, or under 72 % of its own box along its
-- longest wall. A free-standing slab is a block of a series; what wraps a court or follows a
-- street's corner is the old town's perimeter block.
function M.irregular(rings)
  local ring = rings and rings[1]
  if not ring or #ring < 4 then return false end
  if rings[2] then return true end
  local ax, ay, longest, twice = 1, 0, 0, 0
  for k, p in ipairs(ring) do
    local q = ring[k % #ring + 1]
    local dx, dy = q[1] - p[1], q[2] - p[2]
    local length = sqrt(dx * dx + dy * dy)
    if length > longest then ax, ay, longest = dx / length, dy / length, length end
    twice = twice + p[1] * q[2] - q[1] * p[2]
  end
  local u0, v0, u1, v1 = math.huge, math.huge, -math.huge, -math.huge
  for _, p in ipairs(ring) do
    local u, v = p[1] * ax + p[2] * ay, p[2] * ax - p[1] * ay
    u0, v0, u1, v1 = min(u0, u), min(v0, v), max(u1, u), max(v1, v)
  end
  local box = (u1 - u0) * (v1 - v0)
  return box > 1 and abs(twice) / 2 / box < .72
end
M.oldcity = {tall = words('stalin 6 brick 2 modern 2'), mid = words('stalin 4 oldtown 3 brick 2 modern 1'),
  low = words('oldtown 6 low 3 stalin 1')}

function M.styleOf(tags, height, h, block, rings)
  local region = M.regions[block or ''] or M.regions.general
  local use, material = tags.building, tags['building:material']
  local year = tonumber(tostring(tags.start_date or ''):match('%d%d%d%d'))
  if (block == 'postsoviet' or block == 'central') and height < 42 and M.irregular(rings) then region = M.oldcity end
  local list = height >= 24 and (height < 34 and region.high or region.tall) or height >= 11 and region.mid or region.low
  local style = pick(list, ih(h, 11))
  if block == 'postsoviet' then
    -- a mapped year or material says more than the hash
    if year then
      style = year < 1920 and 'oldtown' or year < 1958 and 'stalin' or year < 1995 and (height >= 24 and 'panel' or style) or 'modern'
      if year >= 1958 and year < 1995 and style ~= 'panel' and style ~= 'brick' then style = height >= 24 and 'panel' or 'brick' end
    end
    if material == 'brick' and (style == 'panel' or style == 'modern') then style = height < 30 and 'brick' or style end
    if (material == 'panel' or material == 'concrete') and style ~= 'panel' and height >= 11 then style = 'panel' end
    if style == 'oldtown' and height > 22 then style = 'stalin' end
    if style == 'stalin' and height > 30 then style = 'panel' end
  end
  if (use == 'office' or use == 'commercial' or use == 'retail' or use == 'hotel' or material == 'glass') and style ~= 'oldtown' and style ~= 'stalin' then
    style = 'modern'
  end
  return style
end

-- A house keeps the generator's walls and roof (BLD.dress); the kit gives it its region's
-- window and door out of the atlas, with glass that mirrors the sky.
M.houses = {
  postsoviet = {win = words('w_sov3 3 w_wood_blue 2 w_pvc_blinds 3 w_pvc_brown 2 w_pvc_cat 1 w_kitchen 1'),
    door = {'d_steel_brown', 'd_wood_brown', 'd_steel_grey'}},
  british = {win = words('w_sash66 2 w_sash22 3 w_upvc 3 w_cottage 2'), door = {'d_uk_red', 'd_uk_black', 'd_modern', 'd_shop_green'}},
  ['north-america'] = {win = words('w_hung 4 w_sash22 1 w_upvc 1'), door = {'d_us_white', 'd_modern', 'd_wood_brown'}},
  western = {win = words('w_german 3 w_upvc 3 w_cottage 2'), door = {'d_modern', 'd_french', 'd_wood_brown'}},
  mediterranean = {win = words('m_shut_brown 3 m_blind 2 m_modern 2 m_small 1'), door = {'md_blue', 'md_white', 'md_green'}},
  general = {win = words('w_upvc 2 w_pvc_blinds 2 w_german 1'), door = {'d_modern', 'd_wood_brown', 'd_steel_brown'}},
}
M.houses.nordic, M.houses.central, M.houses.oceania = M.houses.western, M.houses.western, M.houses.british
-- the window's and the door's cell {u0, v0, u1, v1, ...} of house h in a region, or nil
function M.house(block, h)
  local H = M.houses[block or ''] or M.houses.general
  return DATA.cells[pick(H.win, ih(h, 41))], DATA.cells[pick(H.door, ih(h, 42))]
end

-- A far tile draws a building as a box in one photo facade. The kit's building keeps its wall
-- there: the generator's facade nearest its wall and style, so a block does not change colour
-- where its tile turns near. Nil: not the kit's building.
M.far = {
  panel_pebble = 'pnl_grey', panel_pebble_beige = 'pnl_beige', panel_pebble_warm = 'pnl_beige', panel_tile = 'pnl_white',
  panel_tile_blue = 'pnl_blue', panel_tile_beige = 'pnl_beige',
  brick_silicate = 'brk_white', brick_red = 'brk_red', brick_yellow = 'brk_d_stock', brick_old = 'brk_d_old',
  brick_brown = 'brk_d_dark', brick_london = 'brk_d_stock', brick_us = 'brk_d_vic', brownstone = 'brk_d_dark',
  limestone = 'pls_d_ashlar',
  plaster_smooth_cream = 'pls_cream', plaster_smooth_yellow = 'pls_yellow', plaster_smooth_peach = 'pls_peach',
  plaster_smooth_pink = 'pls_peach', plaster_smooth_white = 'pls_d_white', plaster_smooth_grey = 'pls_grey',
  plaster_aged_yellow = 'pls_yellow', plaster_aged_cream = 'pls_cream', plaster_aged_grey = 'pls_grey',
  plaster_aged_pink = 'pls_peach', plaster_aged_green = 'pls_green', plaster_rough = 'pls_grey',
  fibre_panel_white = 'pls_d_new', fibre_panel_grey = 'off_grey', fibre_panel_dark = 'off_ribbon_dark',
  fibre_panel_orange = 'pls_d_new', fibre_panel_green = 'pls_d_new',
  azulejo = 'pls_d_tile', azulejo_green = 'pls_d_tile', whitewash = 'pls_d_white',
  stucco_warm_cream = 'pls_d_euro_warm', stucco_warm_ochre = 'pls_d_euro_warm', stucco_warm_pink = 'pls_d_euro_warm',
}
function M.farKind(tags, height, footprint, h, block, options, rings)
  options = options or NONE
  if options.kit == false or options.realStyle == false then return nil end
  if options.kit == nil then
    if rawget(_G, 'E2R_KIT') == false then return nil end
    if M.found == nil then M.found = (FS and next(DATA.cells) and FS:fileExists(M.ART)) and true or false end
    if not M.found then return nil end
  end
  if not M.uses[tags.building or ''] or tags.e2r_part or height < M.MIN.height or (footprint or 0) < M.MIN.area then return nil end
  if options.detail and options.detail < M.MIN.detail then return nil end
  local S = M.styles[M.styleOf(tags, height, h, block, rings)]
  local kind = S and M.far[pick(S.walls, ih(h, 1))]
  return kind and 'wall_' .. kind or nil
end

-- ctx: tags, height, footprint, h, block, options, rect, ring (outer, oriented as the walls
-- run), street(x, y) -> a road within reach, ground(x, y), shop (a mapped shop inside).
function M.plan(ctx)
  local options = ctx.options or NONE
  if not M.enabled(options) then return nil end
  local tags, height = ctx.tags or NONE, ctx.height
  if not M.uses[tags.building or ''] or tags.e2r_part or height < M.MIN.height or (ctx.footprint or 0) < M.MIN.area then return nil end
  if options.detail and options.detail < M.MIN.detail then return nil end
  local h = ctx.h
  local name = M.styleOf(tags, height, h, ctx.block, ctx.rings)
  local S = M.styles[name]
  if not S then return nil end
  local usable = height - S.plinth - S.attic
  local n = tonumber(tags['building:levels'])
  n = n and floor(n + .5) or nil
  if not n or n < 1 or usable / n < 2.45 or usable / n > 4.6 then n = max(1, floor(usable / S.floor + .5)) end
  if usable / n < 2.3 then return nil end
  local wall = pick(S.walls, ih(h, 1))
  local detail = options.detail or 65
  local plan = {style = S, name = name, h = h, rect = ctx.rect, floors = n, fh = usable / n, plinth = S.plinth,
    wall = wall, wallM = DATA.walls[wall] or 3, ground = ctx.ground, shop = ctx.shop,
    plinthWall = pick(S.plinthWall, ih(h, 2)), groundWall = S.groundWall and pick(S.groundWall, ih(h, 3)) or nil,
    front = pick(S.front, ih(h, 4)), back = pick(S.back, ih(h, 5)), ends = pick(S.ends, ih(h, 6)),
    -- reveals and sills as far up as they read from the street; above, a window is one quad
    deep = detail >= 90 and 8 or detail >= 65 and 5 or 3, lean = detail < 65,
    tris = 0, parts = {}}
  if S.balcony then
    local B = S.balcony
    plan.parapet = pick(B.parapet, ih(h, 7))
    -- a series glazes its balconies alike or not at all; the flats differ within it
    plan.glazed = B.glazed
    plan.balconyFrom = (S.groundWall or name == 'oldtown') and 1 or ih(h, 8) % 2
  end
  -- the walls with entrances: long ones off the street, else the longest
  -- the wall with the entrances: the longest one off the street (on it, where a style's doors
  -- open on the street), else the longest
  local ring, longest, best, entry, entryLength = ctx.ring or NONE, 0, nil, nil, 0
  for k, a in ipairs(ring) do
    local b = ring[k % #ring + 1]
    local length = sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2)
    if length > 0 then
      local mx, my = (a[1] + b[1]) / 2 + (b[2] - a[2]) / length * 8, (a[2] + b[2]) / 2 - (b[1] - a[1]) / length * 8
      local road = ctx.street and ctx.street(mx, my) and true or false
      local edge = {a = a, b = b, length = length, road = road}
      if length > longest then longest, best = length, edge end
      if length >= 9 and (road == (S.doorStreet or false)) and length > entryLength then entry, entryLength = edge, length end
    end
  end
  plan.entries, plan.longest = {entry or best}, longest
  return plan
end

-- ---------------------------------------------------------------------------------------------
-- Geometry in a wall's frame: s along a -> b, o outward, z up.
local function pt(W, s, o, z, u, v)
  return {W.ax + W.dx * s + W.dy * o, W.ay + W.dy * s - W.dx * o, z, u, v}
end

-- A quad whose normal points along (nx, ny, nz) in the wall's frame (s, o, z).
local function quad(W, kind, p0, p1, p2, p3, ns, no, nz)
  local nx, ny = W.dx * ns + W.dy * no, W.dy * ns - W.dx * no
  local ux, uy, uz = p1[1] - p0[1], p1[2] - p0[2], p1[3] - p0[3]
  local vx, vy, vz = p2[1] - p0[1], p2[2] - p0[2], p2[3] - p0[3]
  if (uy * vz - uz * vy) * nx + (uz * vx - ux * vz) * ny + (ux * vy - uy * vx) * nz < 0 then p1, p3 = p3, p1 end
  -- a wall wholly inside the tile writes its quads without clipping (generator collector.quad)
  if W.fast then W.fast(kind, p0, p1, p2, p3) else W.polygon(kind, {p0, p1, p2, p3}, false) end
  W.plan.tris = W.plan.tris + 2
end

-- Wall material to texture: u along the wall (and round a corner into a reveal), v up, as the
-- generator's own walls (their maps are stored upside down). In metres a repeat m, or (m = 0)
-- in the wall's own panels: a panel sheet is two bays by two floors, its joints on the bay and
-- floor lines.
local function wu(W, m, s) if m == 0 then return (s - W.ps) / W.pu end return (W.along + s) / m end
local function wv(W, m, z) if m == 0 then return (z - W.pz) / W.pv end return (z - W.base) / m end
local function wallQuad(W, kind, m, s0, s1, z0, z1, o)
  local u0, u1, v0, v1 = wu(W, m, s0), wu(W, m, s1), wv(W, m, z0), wv(W, m, z1)
  quad(W, kind, pt(W, s0, o, z0, u0, v0), pt(W, s1, o, z0, u1, v0), pt(W, s1, o, z1, u1, v1), pt(W, s0, o, z1, u0, v1), 0, 1, 0)
end
-- its side at s between o0 and o1, facing along s (dir = 1) or against it
local function wallSide(W, kind, m, s, o0, o1, z0, z1, dir)
  local u0, u1, v0, v1 = wu(W, m, s + o0), wu(W, m, s + o1), wv(W, m, z0), wv(W, m, z1)
  quad(W, kind, pt(W, s, o0, z0, u0, v0), pt(W, s, o1, z0, u1, v0), pt(W, s, o1, z1, u1, v1), pt(W, s, o0, z1, u0, v1), dir, 0, 0)
end
-- its top or underside at z
local function wallCap(W, kind, m, s0, s1, o0, o1, z, dir)
  local d = m == 0 and W.pv or m
  local u0, u1, v0, v1 = wu(W, m, s0), wu(W, m, s1), o0 / d, o1 / d
  quad(W, kind, pt(W, s0, o0, z, u0, v0), pt(W, s1, o0, z, u1, v0), pt(W, s1, o1, z, u1, v1), pt(W, s0, o1, z, u0, v1), 0, 0, dir)
end

-- An atlas cell on a quad facing out: the whole cell, or the part (f0..f1 across it).
local function cellQuad(W, cell, s0, s1, z0, z1, o, f0, f1)
  local c = DATA.cells[cell]
  if not c then return end
  local u0, u1 = c[1] + (c[3] - c[1]) * (f0 or 0), c[1] + (c[3] - c[1]) * (f1 or 1)
  quad(W, c[7] == 1 and M.CELLS2 or M.CELLS, pt(W, s0, o, z0, u0, c[4]), pt(W, s1, o, z0, u1, c[4]), pt(W, s1, o, z1, u1, c[2]), pt(W, s0, o, z1, u0, c[2]), 0, 1, 0)
end
local function cellSide(W, cell, s, o0, o1, z0, z1, dir, f0, f1)
  local c = DATA.cells[cell]
  if not c then return end
  local u0, u1 = c[1] + (c[3] - c[1]) * f0, c[1] + (c[3] - c[1]) * f1
  quad(W, c[7] == 1 and M.CELLS2 or M.CELLS, pt(W, s, o0, z0, u0, c[4]), pt(W, s, o1, z0, u1, c[4]), pt(W, s, o1, z1, u1, c[2]), pt(W, s, o0, z1, u0, c[2]), dir, 0, 0)
end

-- A trim band: its whole height on a face, repeating along it. `flat` bands are plain surfaces:
-- any face takes a slice.
local function band(name) return DATA.bands[name] or DATA.bands.concrete or NONE end
local function bandQuad(W, name, s0, s1, z0, z1, o)
  local b = band(name)
  if not b[1] then return end
  local u0, u1 = (W.along + s0) / b[4], (W.along + s1) / b[4]
  quad(W, M.TRIM, pt(W, s0, o, z0, u0, b[2]), pt(W, s1, o, z0, u1, b[2]), pt(W, s1, o, z1, u1, b[1]), pt(W, s0, o, z1, u0, b[1]), 0, 1, 0)
end
local function bandSide(W, name, s, o0, o1, z0, z1, dir)
  local b = band(name)
  if not b[1] then return end
  local u0, u1 = o0 / b[4], o1 / b[4]
  quad(W, M.TRIM, pt(W, s, o0, z0, u0, b[2]), pt(W, s, o1, z0, u1, b[2]), pt(W, s, o1, z1, u1, b[1]), pt(W, s, o0, z1, u0, b[1]), dir, 0, 0)
end
-- top or underside in a band's upper or lower edge (dir = 1 up)
local function bandCap(W, name, s0, s1, o0, o1, z, dir)
  local b = band(name)
  if not b[1] then return end
  local u0, u1 = (W.along + s0) / b[4], (W.along + s1) / b[4]
  local edge = dir > 0 and b[1] or b[2]
  local v0, v1 = edge, edge + (b[2] - b[1]) * (dir > 0 and .12 or -.12)
  quad(W, M.TRIM, pt(W, s0, o0, z, u0, v0), pt(W, s1, o0, z, u1, v0), pt(W, s1, o1, z, u1, v1), pt(W, s0, o1, z, u0, v1), 0, 0, dir)
end
-- A box of a band standing out of the wall: front, the two ends, the top and the underside.
local function bandBox(W, name, s0, s1, o0, o1, z0, z1, faces)
  bandQuad(W, name, s0, s1, z0, z1, o1)
  if not faces or faces:find('l', 1, true) then bandSide(W, name, s0, o0, o1, z0, z1, -1) end
  if not faces or faces:find('r', 1, true) then bandSide(W, name, s1, o0, o1, z0, z1, 1) end
  if not faces or faces:find('t', 1, true) then bandCap(W, name, s0, s1, o0, o1, z1, 1) end
  if not faces or faces:find('b', 1, true) then bandCap(W, name, s0, s1, o0, o1, z0, -1) end
end
-- A box of wall material.
local function wallBox(W, kind, m, s0, s1, o0, o1, z0, z1, faces)
  wallQuad(W, kind, m, s0, s1, z0, z1, o1)
  if not faces or faces:find('l', 1, true) then wallSide(W, kind, m, s0, o0, o1, z0, z1, -1) end
  if not faces or faces:find('r', 1, true) then wallSide(W, kind, m, s1, o0, o1, z0, z1, 1) end
  if not faces or faces:find('t', 1, true) then wallCap(W, kind, m, s0, s1, o0, o1, z1, 1) end
  if not faces or faces:find('b', 1, true) then wallCap(W, kind, m, s0, s1, o0, o1, z0, -1) end
end
M.prims = {pt = pt, quad = quad, wallQuad = wallQuad, wallBox = wallBox, bandBox = bandBox, cellQuad = cellQuad}

local function count(W, part, before)
  local parts = W.plan.parts
  parts[part] = (parts[part] or 0) + W.plan.tris - before
end

-- ---------------------------------------------------------------------------------------------
-- Blocks.

-- A window in its opening s0..s1, z0..z1: the glass set back in a reveal of the wall's own
-- material, a sill over the bottom. Above plan.deep floors the window is one quad on the wall.
function M.window(W, cell, s0, s1, z0, z1, k, kind, m, door)
  local S, plan = W.S, W.plan
  local before = plan.tris
  -- an air conditioner under the sill of a flat that has bought one: the unit's face from the
  -- atlas on a box, its casing's edge on the sides
  if S.ac and k >= 1 and not door and s1 - s0 > 1 then
    local seed = ih(plan.h, floor((W.along + s0) * 8 + .5), k + 77)
    if seed % 100 < S.ac then
      local unit = seed % 3 == 0 and 'x_ac_old' or 'x_ac_white'
      local w, hgt, d = .78, .54, .3
      local a0 = math.floor(seed / 100) % 2 == 0 and s0 + .04 or s1 - w - .04
      local za = z0 - .26 - hgt
      cellQuad(W, unit, a0, a0 + w, za, za + hgt, d)
      cellSide(W, unit, a0, 0, d, za, za + hgt, -1, .9, .97)
      cellSide(W, unit, a0 + w, 0, d, za, za + hgt, 1, .9, .97)
      bandCap(W, 'white', a0, a0 + w, 0, d, za + hgt, 1)
      count(W, 'ac', before)
      before = plan.tris
    end
  end
  if k >= W.deep or M.proud[cell] then
    cellQuad(W, cell, s0, s1, z0, z1, M.proud[cell] and .05 or .025)
    count(W, 'window', before)
    return
  end
  local r = S.reveal
  cellQuad(W, cell, s0, s1, z0, z1, -r)
  wallSide(W, kind, m, s0, -r, 0, z0, z1, 1)
  wallSide(W, kind, m, s1, -r, 0, z0, z1, -1)
  wallCap(W, kind, m, s0, s1, -r, 0, z1, -1)
  -- the sill: one sheet sloping from under the frame out past the wall
  local b = band('zinc')
  if b[1] then
    local out, over = .08, .05
    local u0, u1 = (s0 - over) / b[4], (s1 + over) / b[4]
    quad(W, M.TRIM, pt(W, s0 - over, -r, z0 + .04, u0, b[1]), pt(W, s1 + over, -r, z0 + .04, u1, b[1]),
      pt(W, s1 + over, out, z0 - .03, u1, b[2]), pt(W, s0 - over, out, z0 - .03, u0, b[2]), 0, .3, 1)
  end
  count(W, 'window', before)
  if S.casing and k < W.deep then
    -- a casing round the opening, 3 cm proud: jambs, head, and a keyed lintel on the main floors
    before = plan.tris
    local c, o = S.casing, .03
    bandQuad(W, 'white', s0 - c, s0, z0, z1 + c, o)
    bandQuad(W, 'white', s1, s1 + c, z0, z1 + c, o)
    bandQuad(W, 'white', s0, s1, z1, z1 + c, o)
    if S.frieze and k >= 1 and k <= 2 then
      bandBox(W, 'string_course', s0 - c - .06, s1 + c + .06, 0, .1, z1 + c, z1 + c + .14, 'lrtb')
    end
    count(W, 'casing', before)
  elseif S.lintel and k < W.deep then
    before = plan.tris
    bandQuad(W, S.lintel, s0 - .12, s1 + .12, z1, z1 + .22, .012)
    count(W, 'casing', before)
  end
end

-- A balcony in front of bay sa..sb at floor level zf: the slab, the parapet, and the glazing a
-- flat has added (or has not). Behind it the wall has a balcony door (the caller's opening).
function M.balcony(W, sa, sb, zf, k, last)
  local S, plan = W.S, W.plan
  local B = S.balcony
  local before = plan.tris
  local inset = B.rail and .5 or .22
  local s0, s1, d = sa + inset, sb - inset, B.depth
  local slab, rail = .14, B.rail and .95 or 1.05
  if B.rail then bandBox(W, 'slab_edge', s0, s1, 0, d, zf - slab, zf, 'lrb')
  else bandCap(W, 'slab_edge', s0, s1, 0, d, zf - slab, -1) end
  local seed = ih(plan.h, floor(W.along + sa + .5), k)
  local z0, z1 = B.rail and zf or zf - slab, zf + rail
  if B.rail then
    -- a light balcony: a low solid front in the trim's white, as a balustrade reads from the street
    bandBox(W, 'white', s0, s1, d - .08, d, z0, z1, 'lrt')
    bandSide(W, 'white', s0, 0, d, z0, z1, -1)
    bandSide(W, 'white', s1, 0, d, z0, z1, 1)
    bandCap(W, 'slab_edge', s0, s1, 0, d, zf, 1)
  else
    local kind = 'kw_' .. plan.parapet
    local m = DATA.walls[plan.parapet] or 1.5
    local top = zf + W.fh - slab
    local glazed = seed / HMOD < plan.glazed
    wallQuad(W, kind, m, s0, s1, z0, z1, d)
    wallSide(W, kind, m, s0, 0, d, z0, glazed and plan.lean and top or z1, -1)
    wallSide(W, kind, m, s1, 0, d, z0, glazed and plan.lean and top or z1, 1)
    if glazed then
      local cell = pick(B.glass, seed)
      cellQuad(W, cell, s0, s1, z1, top, d)
      if not plan.lean then
        local part = min(1, d / (s1 - s0))
        cellSide(W, cell, s0, 0, d, z1, top, -1, 0, part)
        cellSide(W, cell, s1, 0, d, z1, top, 1, 1 - part, 1)
      end
      if last then bandBox(W, 'zinc', s0 - .05, s1 + .05, 0, d + .08, top, top + .06, 'lrtb') end
    else
      bandCap(W, 'coping', s0, s1, d - .1, d, z1, 1)
      bandCap(W, 'slab_edge', s0, s1, 0, d, zf, 1)
      if last then bandBox(W, 'slab_edge', s0, s1, 0, d, top, top + slab, 'lrb') end
    end
  end
  count(W, 'balcony', before)
end

-- An entrance in bay sa..sb: the door in a deep reveal at the ground, a step, a canopy.
function M.entrance(W, sa, sb, kind, m, zFloor)
  local S, plan = W.S, W.plan
  local before = plan.tris
  local cell = pick(S.doors, ih(plan.h, 31, floor(W.along + sa)))
  local c = DATA.cells[cell] or NONE
  local dw, dh = c[5] or 1.2, c[6] or 2.1
  local mid = (sa + sb) / 2
  dw = min(dw, sb - sa - .5)
  local p = pt(W, mid, .6, 0)
  local g = plan.ground and plan.ground(p[1], p[2]) or W.base
  -- at the ground, or (a stoop) at the ground floor's level with steps up to it
  local z0 = S.porch == 'stoop' and zFloor or min(max(g + .12, W.bottom + .3), zFloor)
  local z1 = z0 + dh
  local s0, s1, r = mid - dw / 2, mid + dw / 2, S.porch == 'portal' and .45 or .3
  cellQuad(W, cell, s0, s1, z0, z1, -r)
  wallSide(W, kind, m, s0, -r, 0, z0, z1, 1)
  wallSide(W, kind, m, s1, -r, 0, z0, z1, -1)
  wallCap(W, kind, m, s0, s1, -r, 0, z1, -1)
  -- the step, down into the ground
  if S.porch ~= 'stoop' then bandBox(W, 'concrete', s0 - .35, s1 + .35, -r, .9, z0 - .6, z0, 'lrt') end
  if S.porch == 'slab' then
    -- a concrete canopy on two fins
    local w, d, zc = dw / 2 + .55, 1.5, z1 + .25
    bandBox(W, 'slab_edge', mid - w, mid + w, 0, d, zc, zc + .16, 'lrtb')
    bandBox(W, 'concrete', mid - w, mid - w + .14, 0, d - .25, z0 - .6, zc, 'lr')
    bandBox(W, 'concrete', mid + w - .14, mid + w, 0, d - .25, z0 - .6, zc, 'lr')
  elseif S.porch == 'portal' then
    -- a plaster surround with a cornice over the door
    local c2 = .22
    bandQuad(W, 'white', s0 - c2, s0, z0, z1 + c2, .04)
    bandQuad(W, 'white', s1, s1 + c2, z0, z1 + c2, .04)
    bandQuad(W, 'white', s0, s1, z1, z1 + c2, .04)
    bandBox(W, 'string_course', s0 - c2 - .15, s1 + c2 + .15, 0, .22, z1 + c2, z1 + c2 + .2, 'lrtb')
  elseif S.porch == 'glass' then
    local w, zc = dw / 2 + .4, z1 + .15
    bandBox(W, 'dark', mid - w, mid + w, 0, 1.3, zc, zc + .07, 'lrtb')
  elseif S.porch == 'stoop' then
    -- steps up to a raised door, in the plinth's stone
    local pk, pm = 'kw_' .. plan.plinthWall, DATA.walls[plan.plinthWall] or 2.4
    local rise = max(.2, z0 - g)
    local steps = max(1, min(8, floor(rise / .17 + .5)))
    wallBox(W, pk, pm, s0 - .25, s1 + .25, 0, .9, g - .5, z0, 'lrt')
    for n = 1, steps do
      wallBox(W, pk, pm, s0 - .25, s1 + .25, .9 + (n - 1) * .3, .9 + n * .3, g - .5, z0 - n * rise / (steps + 1), 'lrt')
    end
  end
  count(W, 'entrance', before)
  return s0, s1, z0, z1
end

-- ---------------------------------------------------------------------------------------------
-- One wall piece a -> b (outside on the right), `along` metres round the ring before it.
-- info: full (the whole wall's length), road (a street in front), blank (no openings).
function M.wall(plan, scene, a, b, length, along, bottom, base, top, info)
  if length < .05 then return true end
  info = info or NONE
  local S = plan.style
  local dx, dy = (b[1] - a[1]) / length, (b[2] - a[2]) / length
  -- nothing of a wall wholly outside the tile (its balconies and porches reach 2.6 m out)
  local rect, reach = plan.rect, 2.6
  local x0, x1, y0, y1 = min(a[1], b[1]), max(a[1], b[1]), min(a[2], b[2]), max(a[2], b[2])
  if rect and (x1 < rect[1] - reach or x0 > rect[3] + reach or y1 < rect[2] - reach or y0 > rect[4] + reach) then return true end
  local W = {polygon = scene.polygon, ax = a[1], ay = a[2], dx = dx, dy = dy, along = along, base = base, bottom = bottom,
    plan = plan, S = S, fh = plan.fh}
  if scene.quad and rect and x0 > rect[1] + reach and x1 < rect[3] - reach and y0 > rect[2] + reach and y1 < rect[4] - reach then
    W.fast = scene.quad
  end
  local n, fh = plan.floors, plan.fh
  local z0 = min(top, base + plan.plinth)          -- the ground floor's level
  local full = info.full or length
  local before = plan.tris

  -- the pattern of bays
  local margin = S.margin
  local nb = floor((length - 2 * margin) / S.bay + .5)
  local entry = false
  for _, e in ipairs(plan.entries or NONE) do
    -- this piece lies on the entrance wall
    local mx, my = (a[1] + b[1]) / 2, (a[2] + b[2]) / 2
    local ex, ey = e.b[1] - e.a[1], e.b[2] - e.a[2]
    local t = ((mx - e.a[1]) * ex + (my - e.a[2]) * ey) / (e.length * e.length)
    if t > 0 and t < 1 and abs((mx - e.a[1]) * ey - (my - e.a[2]) * ex) / e.length < .05 then entry = true; break end
  end
  local pattern = entry and plan.back or (full < 15 and plan.longest > full * 1.6) and plan.ends or plan.front
  if info.blank or length < 2.6 or nb < 1 or #pattern == 0 then nb = 0 end
  local bw = nb > 0 and (length - 2 * margin) / nb or S.bay
  local cols = {}
  if nb > 0 then
    -- centred, so both ends of a wall close alike; an entrance wall has a stair at least
    local shift = floor((#pattern - nb % #pattern) / 2) % #pattern
    local stairs = 0
    for i = 1, nb do
      local c = pattern:sub((i - 1 + shift) % #pattern + 1, (i - 1 + shift) % #pattern + 1)
      if c == 'S' then stairs = stairs + 1 end
      cols[i] = c
    end
    if entry and stairs == 0 then cols[floor((nb + 1) / 2)] = 'S' end
    if not entry then
      for i = 1, nb do if cols[i] == 'S' then cols[i] = S.size.T and 'T' or 'W' end end
    end
    if nb == 1 and cols[1] == 'B' then cols[1] = S.size.T and 'T' or 'W' end
    -- 'cX': X up the middle of an otherwise blank wall
    if pattern:sub(1, 1) == 'c' then
      for i = 1, nb do cols[i] = '-' end
      cols[floor((nb + 1) / 2)] = pattern:sub(2, 2)
      if nb % 2 == 0 then cols[nb / 2 + 1] = pattern:sub(2, 2) end
    end
  end
  local topw = min(top, base + plan.plinth + n * fh)          -- the top floor's ceiling; the attic above
  -- the wall and its texture: metres, or the wall's own panels (two bays by two floors a sheet)
  local kind, m = 'kw_' .. plan.wall, plan.wallM
  if S.panels then
    m = 0
    W.ps, W.pu, W.pz, W.pv = nb > 0 and margin or 0, 2 * bw, z0, 2 * fh
  end
  local gk, gm = kind, m
  if plan.groundWall then gk, gm = 'kw_' .. plan.groundWall, DATA.walls[plan.groundWall] or 2.4 end
  -- a shop's ground floor is the generator's: its fascia, sign and fronts want a plain wall
  local shopFloor = plan.shop and info.road

  -- entrances first: the plinth and the ground floor are cut for their doors
  local doors = {}
  if nb > 0 and not shopFloor then
    for i = 1, nb do
      if cols[i] == 'S' then
        local sa = margin + (i - 1) * bw
        doors[i] = {M.entrance(W, sa, sa + bw, gk, gm, z0)}
      end
    end
  end

  -- the plinth, 5 cm proud with its ledge, down into the ground; open at a door
  before = plan.tris
  local pk, pm = 'kw_' .. plan.plinthWall, DATA.walls[plan.plinthWall] or 3
  if z0 > bottom and shopFloor then
    wallQuad(W, gk, gm, 0, length, bottom, z0, 0)
  elseif z0 > bottom then
    local cursor = -.05
    for i = 1, nb do
      local d = doors[i]
      if d and d[3] < z0 - .02 then
        wallQuad(W, pk, pm, cursor, d[1], bottom, z0, .05)
        wallCap(W, pk, pm, cursor, d[1], 0, .05, z0, 1)
        wallSide(W, pk, pm, d[1], 0, .05, d[3], z0, 1)
        wallSide(W, pk, pm, d[2], 0, .05, d[3], z0, -1)
        cursor = d[2]
      end
    end
    wallQuad(W, pk, pm, cursor, length + .05, bottom, z0, .05)
    wallCap(W, pk, pm, cursor, length + .05, 0, .05, z0, 1)
  end
  count(W, 'plinth', before)

  -- openings: s0, s1, z0, z1, cell, letter of bay i on floor k; nil for none
  local function opening(i, k)
    local c = cols[i]
    if c == '-' then return nil end
    local sa = margin + (i - 1) * bw
    local zf = z0 + k * fh
    if k == 0 and shopFloor then return nil end
    if c == 'S' and k == 0 then
      -- the door's top stands in the ground floor's wall
      local d = doors[i]
      if d and d[4] > zf + .02 then return d[1], d[2], max(zf, d[3]), min(d[4], zf + fh - .1), nil, 'door' end
      return nil
    end
    local seed = ih(plan.h, floor((along + sa) * 4 + .5), k)
    if c == 'B' then
      local B = S.balcony
      if not B or k < plan.balconyFrom or (B.every and k % B.every ~= plan.balconyFrom % B.every) then
        c = S.size.T and 'T' or S.size.D and 'D' or 'W'
      else
        local cell = pick(B.door, seed)
        local cd = DATA.cells[cell] or NONE
        local w, hgt = min(cd[5] or 2, bw - .7), min(cd[6] or 2.2, fh - .45)
        local mid = sa + bw / 2
        return mid - w / 2, mid + w / 2, zf + .08, zf + .08 + hgt, cell, 'B'
      end
    end
    local size = S.size[c] or S.size.W or S.size.T
    local list = S[c] or S.W or S.T
    if k == 0 and S.ground and c ~= 'S' and c ~= 'F' then list = S.ground end
    -- a house of one build keeps its windows; in a block of flats every flat has its own
    local cell = (S.casing and seed % 5 ~= 0) and pick(list, ih(plan.h, 21)) or pick(list, seed)
    local w, hgt = min(size[1], bw - .5), min(size[2], fh - .7)
    if M.proud[cell] then
      local cd = DATA.cells[cell] or NONE
      w, hgt = min(cd[5] or w, bw - .25), min(cd[6] or hgt, fh - .6)
    end
    local sill = c == 'F' and (S.sillF or .1) or c == 'S' and fh * .5 or S.sill
    if sill + hgt > fh - .25 then sill = max(.1, fh - .25 - hgt) end
    local mid = sa + bw / 2
    return mid - w / 2, mid + w / 2, zf + sill, zf + sill + hgt, cell, c
  end

  -- the wall round the openings of floors k0..k1 between zLo and zHi: piers the full height
  -- where a column keeps its width, spandrels between its windows; a column that does not,
  -- cell by cell
  -- what the wall is cut for: a cell that lies on the wall with its open shutters needs no hole
  -- (and a hole behind it would show the sky at a glancing angle)
  local function hole(i, k)
    local a0, a1, b0, b1, cell = opening(i, k)
    if cell and M.proud[cell] then return nil end
    return a0, a1, b0, b1
  end
  local function span(k0, k1, zLo, zHi, wk, wm)
    if zHi - zLo < .01 then return end
    local cursor = 0
    for i = 1, nb do
      local sa = margin + (i - 1) * bw
      local s0, s1, uniform = nil, nil, true
      for k = k0, k1 do
        local o0, o1 = hole(i, k)
        if o0 then
          if s0 and (abs(o0 - s0) > .001 or abs(o1 - s1) > .001) then uniform = false end
          s0, s1 = s0 or o0, s1 or o1
        end
      end
      if s0 and uniform then
        wallQuad(W, wk, wm, cursor, s0, zLo, zHi, 0)
        local z = zLo
        for k = k0, k1 do
          local _, _, oz0, oz1 = hole(i, k)
          if oz0 then
            if oz0 - z > .005 then wallQuad(W, wk, wm, s0, s1, z, oz0, 0) end
            z = oz1
          end
        end
        if zHi - z > .005 then wallQuad(W, wk, wm, s0, s1, z, zHi, 0) end
        cursor = s1
      elseif s0 then
        if sa - cursor > .001 then wallQuad(W, wk, wm, cursor, sa, zLo, zHi, 0) end
        for k = k0, k1 do
          local zf, zc = max(zLo, z0 + k * fh), k == k1 and zHi or z0 + (k + 1) * fh
          local o0, o1, oz0, oz1 = hole(i, k)
          if o0 then
            wallQuad(W, wk, wm, sa, o0, zf, zc, 0)
            wallQuad(W, wk, wm, o1, sa + bw, zf, zc, 0)
            if oz0 - zf > .005 then wallQuad(W, wk, wm, o0, o1, zf, oz0, 0) end
            if zc - oz1 > .005 then wallQuad(W, wk, wm, o0, o1, oz1, zc, 0) end
          else
            wallQuad(W, wk, wm, sa, sa + bw, zf, zc, 0)
          end
        end
        cursor = sa + bw
      end
    end
    wallQuad(W, wk, wm, cursor, length, zLo, zHi, 0)
  end

  before = plan.tris
  local zg = plan.groundWall and min(topw, z0 + fh) or z0      -- the ground floor's own wall up to here
  local deep = (info.road or plan.deep >= 8) and plan.deep or 1
  W.deep = deep
  local deepTo = min(n, deep) - 1
  if nb == 0 then
    if zg > z0 then wallQuad(W, gk, gm, 0, length, z0, zg, 0) end
    wallQuad(W, kind, m, 0, length, zg, top, 0)
  else
    local k0 = 0
    if plan.groundWall then span(0, 0, z0, zg, gk, gm); k0 = 1 end
    if deepTo >= k0 then span(k0, deepTo, zg, z0 + (deepTo + 1) * fh, kind, m) end
    -- above the deep floors the wall is whole; its windows lie on it
    local zu = z0 + max(k0, deepTo + 1) * fh
    if top - zu > .01 then wallQuad(W, kind, m, 0, length, zu, top, 0) end
  end
  count(W, 'wall', before)

  for i = 1, nb do
    local sa = margin + (i - 1) * bw
    for k = 0, n - 1 do
      local s0, s1, oz0, oz1, cell, c = opening(i, k)
      if s0 and cell then
        if k == 0 and plan.groundWall then M.window(W, cell, s0, s1, oz0, oz1, k, gk, gm, c == 'B')
        else M.window(W, cell, s0, s1, oz0, oz1, k, kind, m, c == 'B') end
        if S.patches and k >= 1 and c ~= 'B' and c ~= 'S' then
          local seed = ih(plan.h, floor((along + sa) * 2 + .5), k + 311)
          if seed % 100 < S.patches then
            -- the insulated flat: its bay's panel under 6 cm of render, open round the window
            before = plan.tris
            local paint = pick(M.PATCH, floor(seed / 100))
            local pk2, pm2, o = 'kw_' .. paint, DATA.walls[paint] or 4, .06
            local zf = z0 + k * fh
            local pa, pb, za, zb = sa + .04, sa + bw - .04, zf + .03, zf + fh - .03
            wallQuad(W, pk2, pm2, pa, s0, za, zb, o)
            wallQuad(W, pk2, pm2, s1, pb, za, zb, o)
            wallQuad(W, pk2, pm2, s0, s1, za, oz0, o)
            wallQuad(W, pk2, pm2, s0, s1, oz1, zb, o)
            count(W, 'patch', before)
          end
        end
        if c == 'B' then M.balcony(W, sa, sa + bw, z0 + k * fh, k, k == n - 1 or select(6, opening(i, k + 1)) ~= 'B') end
      end
    end
  end

  -- string courses over the floors a style names (negative: counted from the top)
  before = plan.tris
  if S.courses then
    for j = 2, #S.courses do
      local k = S.courses[j]
      if k < 0 then k = n + k end
      if k >= 1 and k < n then
        local z = z0 + k * fh
        bandBox(W, S.courses[1], -.08, length + .08, 0, .08, z - .11, z + .11, 'tb')
      end
    end
  end
  -- the frieze and the cornice under the roof
  local C = S.cornice
  local zc = top - C[3]
  if S.frieze and zc - topw > .45 then
    local f = band(S.frieze)
    local fhgt = min(f[3] or .5, zc - topw - .05)
    bandQuad(W, S.frieze, 0, length, zc - fhgt, zc, .015)
  end
  bandBox(W, C[1], -C[2], length + C[2], 0, C[2], zc, top, 'tb')
  count(W, 'trim', before)
  return true
end

return M
