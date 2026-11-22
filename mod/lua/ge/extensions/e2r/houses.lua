-- Houses of one and two storeys by region.
--
-- A style (M.styles) is what a kind of house is made of: its walls, its roofs and the shapes and
-- pitch of them, its windows and doors, its plinth, whether it has a chimney, a wooden cornice or
-- a porch, how often it has an upper floor. A region (M.regions: a look's block, a country of
-- M.countries) is a list of styles, and may name other lists for a dry, a tropical, a
-- Mediterranean or a cold climate (biome.lua). The house's own hash picks the style, and two
-- houses of three take the style of their patch of the map, so a street is of one kind and the
-- next estate of another.
--
-- Before this the generator had a region's walls and nothing else: one render sheet in six paints
-- for half the world, and under them the same gable of 26-38 degrees, the same two sheets of
-- windows, a brick chimney and a board cornice from Kyiv to Kyoto. A house anywhere on the planet
-- was a Ukrainian village house in another paint.
--
-- The art is earthng/house_art.py's (kinds hw_h_*, roof_h_*, the atlases house_cells and
-- house_cells2); house_lib.lua, generated there, holds the atlas cells and the metres a repeat.
-- Names here go without their prefixes: a wall 'h_koroid_peach' is the kind hw_h_koroid_peach, a
-- roof 'h_mission' is roof_h_mission. Windows and doors are cells of house_lib or of the kit's
-- kit_cells (w_*, m_*, d_*, md_*: there only where the planet has the kit's art).
local M = {}
local NONE = {}
local floor, min, max, sin = math.floor, math.min, math.max, math.sin

local function data(name)
  local ok, t = pcall(require, 'ge/extensions/e2r/' .. name)
  return ok and type(t) == 'table' and t or nil
end
local LIB = data('house_lib') or {cells = {}, walls = {}, roofs = {}}
local KIT = data('kit_cells') or {cells = {}}
M.lib = LIB
M.ART = '/e2r_stream/fast-art/v10/real/house_cells.color.dds'
-- the material of a cell by its seventh number
M.ATLAS = {[0] = 'kit_cells', 'kit_cells2', 'house_cells', 'house_cells2'}

local HMOD = 2147483647
local function ih(seed, a, b)
  local h = (seed * 1000003 + a) % HMOD
  h = (h * 1000003 + (b or 0)) % HMOD
  h = (h * 48271 + 11) % HMOD
  return (h * 48271 + 7) % HMOD
end
M.ih = ih

-- 'a 2 b 1' -> {'a', 'b', 'a'}: dealt out, not in runs
local function words(spec, prefix)
  local out = {}
  for name, weight in spec:gmatch('(%S+) (%d+)') do
    for _ = 1, tonumber(weight) do out[#out + 1] = (prefix or '') .. name end
  end
  local n, dealt, step = #out, {}, #out % 7 ~= 0 and 7 or 11
  for k = 1, n do dealt[k] = out[k * step % n + 1] end
  return dealt
end
M.words = words

-- ---------------------------------------------------------------------------------------------
-- Styles. walls, roofs: 'kind weight' words without 'hw_' and 'roof_'. shapes: gabled, hipped,
-- half-hipped, flat. pitch: degrees {from, to}. eave: metres past the wall. gable: 'wall' (the
-- wall's own kind), 'boards', nil (the generator's mix). win, door: cells. plinth: 'plinth',
-- 'plinth_brown', 'none' or '=kind'. chimney: the share that has one. two: the share with an
-- upper floor among houses of 45-260 m2 whose height OSM does not say (nil: the generator's
-- guess). flat: the kind of a flat roof; rim: its parapet {from, to}.
local S = {}
M.styles = S

-- --- Ukraine and the post-Soviet village
S.ua_khata = {
  walls = 'limewash 5 white 4 blue 2 green 1 aged 3 yellow 1 h_earth_sand 1',
  roofs = 'sheet 5 o_wave 3 h_reed 1 metal 1 o_tin 1 mtile_brown 1', shapes = 'hipped 5 gabled 3 half-hipped 2', pitch = {30, 40},
  win = 'ua_blue 3 ua_green 3 ua_brown 2 ua_pvc_blue 2', door = 'ua_door_plank 3 ua_door_steel 1',
  plinth = 'plinth_brown 2 plinth 2', two = 0}
S.ua_wood = {
  walls = 'boards 3 bd_green 3 bd_blue 2 bd_brown 2 bd_ochre 1 log 3 h_log_square 2 siding 2 wood 1',
  roofs = 'sheet 5 o_wave 3 mtile_green 1 mtile_brown 1 metal 1 o_tin 1 h_seam_red 1', shapes = 'gabled 5 hipped 3 half-hipped 2', pitch = {30, 40},
  win = 'ua_blue 3 ua_green 3 ua_brown 3 ua_pvc_blue 1 ua_veranda 1', door = 'ua_door_plank 3 ua_door_steel 1',
  plinth = 'plinth_brown 2 plinth 2', two = 0}
S.ua_brick = {
  walls = 'silicate 5 brick_red 4 oldbrick 2 flatbrick 2 dash 2 dash_cream 2 flaking 1 flaking_yellow 1 shell 1 stone 1',
  roofs = 'sheet 5 mtile_red 2 mtile_brown 2 prof_red 1 prof_brown 1 prof_green 1 metal 1 o_wave 2',
  shapes = 'gabled 5 hipped 4 half-hipped 1', pitch = {28, 38}, gable = 'wall',
  win = 'ua_brown 2 ua_lam 2 w_pvc_blinds 2 w_pvc_brown 2 ua_veranda 1 w_sov3 2 ua_pvc_blue 1', door = 'ua_door_steel 3 ua_door_plank 1 d_steel_brown 1',
  plinth = 'plinth 3 plinth_brown 1', two = .15}
S.ua_cottage = {
  walls = 'h_koroid_peach 3 h_koroid_yellow 2 h_koroid_beige 3 h_koroid_white 2 h_koroid_green 1 h_koroid_grey 2 h_koroid_terracotta 1 '
    .. 'h_face_yellow 3 h_face_peach 2 h_face_brown 2 h_face_red 1 vinyl_cream 1 siding 1',
  roofs = 'mtile_red 4 mtile_brown 4 mtile_green 2 shingle 1 h_shingle_brown 2 h_shingle_red 1 prof_grey 1 prof_brown 1',
  shapes = 'gabled 4 hipped 4 half-hipped 2', pitch = {28, 42}, gable = 'wall',
  win = 'mo_anthr3 2 mo_arch 2 mo_oak 3 mo_roller 2 w_pvc_blinds 2 mo_pano 1 ua_lam 2', door = 'mo_door_forged 3 mo_door_anthr 2 ua_door_steel 2',
  plinth = 'plinth 3 =hw_h_veneer 1 =hw_stone 1', chimney = .6, two = .6}
S.ua_unfinished = {
  walls = 'h_aerated 4 shell 2 h_hollow 1 block 1 h_cement 2 silicate 1', roofs = 'mtile_brown 3 mtile_red 2 prof_grey 2 sheet 2 o_ond_brown 1',
  shapes = 'gabled 6 hipped 4', pitch = {28, 40}, gable = 'wall', win = 'mo_roller 2 w_pvc_blinds 3 mo_oak 1', door = 'ua_door_steel 3 mo_door_forged 1',
  plinth = 'plinth 1', chimney = .3, cornice = false, porch = false, two = .5}
S.ru_izba = {
  walls = 'log 4 h_log_square 4 bd_green 2 bd_blue 2 bd_brown 2 bd_ochre 1 boards 2 h_batten_brown 1',
  roofs = 'metal 3 h_seam_red 2 h_seam_green 2 h_seam_grey 1 sheet 4 o_wave 2', shapes = 'gabled 7 hipped 2 half-hipped 1', pitch = {30, 42},
  win = 'ua_blue 3 ua_green 3 ua_brown 2 ua_veranda 1', door = 'ua_door_plank 3 ua_door_steel 1', plinth = 'plinth_brown 2 plinth 1', two = 0}
S.bal_wood = {
  walls = 'h_batten_yellow 3 h_batten_green 2 h_batten_brown 2 h_batten_grey 2 h_batten_red 1 clapboard_yellow 2 clapboard_white 1 '
    .. 'bd_green 1 bd_ochre 1 silicate 3 h_brizolit_grey 2',
  roofs = 'o_wave 4 sheet 3 h_seam_grey 2 h_seam_red 1 concrete 2 prof_grey 1', shapes = 'gabled 7 hipped 2 half-hipped 1', pitch = {32, 44},
  win = 'nd_three 3 nd_white6 3 ua_brown 2 nd_brown 1', door = 'nd_door_green 2 ua_door_plank 2 ua_door_steel 1', plinth = 'plinth 3', two = .25}
S.cau_stone = {
  walls = 'h_tuff 5 stone 2 fieldstone 2 h_cement 2 block 2 render_sand 2 h_limestone 1',
  roofs = 'zinc 4 h_corr_silver 3 tin 2 h_seam_red 2 tile 1 h_corr_red 1', shapes = 'hipped 6 gabled 4', pitch = {20, 30}, gable = 'wall',
  win = 'ua_brown 2 w_pvc_blinds 2 al_twin 2 me_arch 1 ua_veranda 2', door = 'ua_door_steel 2 al_door_carved 1 me_door_steel 1',
  plinth = '=hw_fieldstone 1 none 2', chimney = .4, two = .6}
S.ca_mud = {
  walls = 'h_mudbrick 4 h_earth_sand 3 h_earth_tan 2 limewash 3 h_cement 2 h_brick_buff 3 silicate 2',
  roofs = 'sheet 4 o_wave 3 h_corr_silver 3 zinc 2', shapes = 'gabled 5 hipped 4 flat 1', pitch = {15, 25}, gable = 'wall',
  win = 'ua_brown 3 ua_blue 2 me_shut 1 w_pvc_blinds 2', door = 'ua_door_steel 2 me_door_blue 1 ua_door_plank 2',
  plinth = 'none 2 plinth 1', chimney = .3, cornice = false, two = .1, flat = 'h_flat_mud', rim = {.2, .4}}

-- --- Central Europe and the Balkans
S.ce_cube = {
  walls = 'h_brizolit_grey 4 h_brizolit_ochre 2 h_brizolit_green 2 dash 2 render_sand 2 flaking 1 h_eternit 1',
  roofs = 'h_fibre_grey 3 sheet 2 prof_brown 1 prof_red 1 concrete 2 o_felt 1', shapes = 'flat 3 hipped 5 gabled 2', pitch = {18, 28}, gable = 'wall',
  win = 'al_twin 4 al_roller 2 w_german 2 al_old 1', door = 'al_door_glass 3 d_modern 1 al_door_carved 1',
  plinth = 'plinth 3', cornice = false, two = .85, flat = 'o_felt', rim = {.2, .35}}
S.ce_village = {
  walls = 'render_white 3 render_sand 3 flaking 2 flaking_yellow 1 h_brizolit_grey 2 brick_red 2 oldbrick 2 h_eternit 1 fieldstone 1',
  roofs = 'h_beaver 4 clay 4 h_fibre_grey 2 h_fibre_red 1 concrete 2 sheet 1', shapes = 'gabled 6 hipped 2 half-hipped 2', pitch = {36, 46},
  win = 'al_old 3 al_twin 3 al_roller 2 w_cottage 1 al_grille 1', door = 'al_door_carved 2 al_door_glass 2 d_wood_brown 1',
  plinth = 'plinth 2 =hw_fieldstone 1', two = .3}
S.ce_new = {
  walls = 'h_koroid_white 3 h_koroid_beige 3 h_koroid_peach 2 h_koroid_yellow 2 h_koroid_grey 2 h_koroid_green 1 h_face_brown 1 h_face_red 1 render_white 2',
  roofs = 'concrete 5 clay 3 mtile_brown 1 mtile_red 1 h_seam_grey 1 h_seam_black 1', shapes = 'gabled 5 hipped 4 flat 1', pitch = {25, 42}, gable = 'wall',
  win = 'mo_anthr3 3 mo_roller 3 mo_oak 2 mo_pano 1 mo_full 1 al_roller 2', door = 'mo_door_anthr 3 mo_door_forged 1 d_modern 2',
  plinth = 'plinth 2 =hw_h_veneer 1', chimney = .5, cornice = false, two = .7, flat = 'h_flat_grey', rim = {.2, .35}}
S.bk_unfinished = {
  walls = 'h_hollow 5 h_frame_brick 3 h_cement 3 block 1', roofs = 'clay 5 pantile 2 h_mission 1 concrete 1',
  shapes = 'hipped 5 gabled 5', pitch = {20, 30}, gable = 'wall', win = 'al_roller 4 mo_roller 2 w_upvc 1 al_twin 1', door = 'mo_door_forged 1 al_door_glass 2 ua_door_steel 1',
  plinth = 'none 1', chimney = .5, cornice = false, porch = false, two = .8}
S.bk_render = {
  walls = 'render_white 4 render_sand 3 render_ochre 2 render_pink 1 fieldstone 2 h_limestone 2 flaking_yellow 1 h_koroid_yellow 1',
  roofs = 'clay 5 pantile 3 h_mission 2', shapes = 'hipped 5 gabled 5', pitch = {20, 28}, gable = 'wall',
  win = 'al_roller 3 al_shut_brown 2 m_blind 2 al_twin 2 m_shut_brown 1', door = 'al_door_carved 2 al_door_glass 2 md_brown 1',
  plinth = 'none 2 =hw_fieldstone 1', chimney = .6, cornice = false, two = .7}

-- --- Western Europe
S.we_render = {
  walls = 'render_white 5 render_sand 3 h_brizolit_grey 1 dash 1 h_koroid_white 2 h_koroid_beige 1',
  roofs = 'clay 4 concrete 4 h_beaver 2 slate 1', shapes = 'gabled 7 hipped 2 half-hipped 1', pitch = {35, 48}, gable = 'wall',
  win = 'w_german 3 al_roller 3 w_upvc 2 al_shut_green 1 mo_roller 1', door = 'd_modern 2 al_door_glass 2 al_door_carved 1',
  plinth = 'plinth 3', chimney = .7, cornice = false, two = .7}
S.we_brick = {
  walls = 'h_brick_dutch 5 clinker 3 brick_dark 2 stock 1 h_brick_buff 2 h_painted_white 2 brick_red 1',
  roofs = 'clay 4 concrete 4 slate 1 h_reed 1', shapes = 'gabled 8 hipped 2', pitch = {40, 50}, eave = .2, gable = 'wall',
  win = 'w_upvc 3 w_cottage 2 w_german 2 nd_white6 2 w_sash22 1', door = 'd_modern 2 d_french 1 nd_door_green 1 d_uk_black 1',
  plinth = 'none 1', cornice = false, porch = false, two = .8}
S.we_timber = {
  walls = 'h_timber 6 render_white 2', roofs = 'h_beaver 5 clay 3 slate 2', shapes = 'gabled 8 half-hipped 2', pitch = {45, 52}, gable = 'wall',
  win = 'al_shut_green 3 w_cottage 3 al_old 2 al_shut_brown 1', door = 'al_door_carved 3 d_french 1',
  plinth = '=hw_fieldstone 2 =hw_h_granite 1', cornice = false, two = .8}
S.we_stone = {
  walls = 'h_limestone 5 h_granite 3 fieldstone 2 stone 1 sandstone 2', roofs = 'slate 4 clay 3 h_mission 1 h_stone 1 h_beaver 1',
  shapes = 'gabled 7 hipped 3', pitch = {35, 45}, eave = .25, gable = 'wall',
  win = 'w_shutters 3 w_paris 1 w_cottage 2 al_shut_brown 2 al_old 1', door = 'd_french 3 al_door_carved 1 d_wood_brown 1',
  plinth = 'none 1', cornice = false, porch = false, two = .7}
S.we_slate = {
  walls = 'h_slate_hung 3 render_white 3 h_granite 3 h_eternit 1', roofs = 'slate 8 h_fibre_grey 1', shapes = 'gabled 7 hipped 3', pitch = {38, 48}, eave = .25,
  gable = 'wall', win = 'w_german 3 w_cottage 2 w_shutters 2 al_old 1', door = 'd_french 2 al_door_carved 1 d_modern 1', plinth = 'none 1 =hw_h_granite 1',
  cornice = false, two = .7}
S.al_chalet = {
  walls = 'h_plank_dark 5 render_white 4 h_shakes 1 h_log_square 2', roofs = 'h_wood_shingle 2 concrete 3 h_stone 2 h_seam_grey 2 clay 2 h_seam_brown 1',
  shapes = 'gabled 10', pitch = {18, 26}, eave = .9, win = 'al_shut_green 4 al_shut_brown 4 al_grille 1 al_roller 1', door = 'al_door_carved 3 d_wood_brown 1',
  plinth = '=hw_fieldstone 2 =hw_render_white 1', two = .85}
S.we_modern = {
  walls = 'h_koroid_white 4 h_koroid_grey 2 render_white 3 h_batten_black 1 h_face_white 1 h_face_brown 1 h_batten_grey 1',
  roofs = 'concrete 4 h_seam_black 2 h_seam_grey 2 slate 1', shapes = 'gabled 5 flat 3 hipped 2', pitch = {22, 45}, eave = .15, gable = 'wall',
  win = 'mo_anthr3 3 mo_full 2 mo_pano 2 mo_roller 2 nd_black 1', door = 'mo_door_anthr 3 d_modern 1', plinth = 'none 1',
  chimney = .2, cornice = false, porch = false, two = .8, flat = 'h_flat_grey', rim = {.2, .35}}

-- --- Britain and Ireland
S.uk_brick = {
  walls = 'brick_red 5 stock 3 brick_dark 2 h_brick_buff 1 h_painted_white 1 h_painted_cream 1',
  roofs = 'slate 6 concrete 4 clay 1', shapes = 'gabled 7 hipped 3', pitch = {35, 45}, eave = .15, gable = 'wall',
  win = 'uk_fanlight 4 uk_sash22 3 uk_wide 2 uk_sash66 1 w_upvc 2 w_sash22 1 uk_bath 1', door = 'uk_door_red 2 uk_door_blue 2 d_uk_red 1 d_uk_black 2 d_modern 1',
  plinth = 'none 1', cornice = false, porch = false, two = .85}
S.uk_dash = {
  walls = 'dash 5 dash_cream 3 render_white 4 render_sand 1 h_painted_white 1', roofs = 'slate 5 concrete 5 clay 1',
  shapes = 'hipped 5 gabled 5', pitch = {32, 42}, eave = .2, gable = 'wall', win = 'uk_fanlight 5 uk_wide 3 w_upvc 2 uk_sash22 1 uk_bath 1', door = 'uk_door_blue 2 uk_door_navy 2 uk_door_red 1 d_modern 1 d_uk_black 1',
  plinth = 'none 2 =hw_brick_red 1', cornice = false, porch = false, two = .85}
S.uk_stone = {
  walls = 'h_granite 3 sandstone 3 fieldstone 2 h_limestone 3 h_schist 1 render_white 2 dash 1', roofs = 'slate 8 h_stone 1 h_reed 1',
  shapes = 'gabled 8 hipped 2', pitch = {36, 46}, eave = .15, gable = 'wall', win = 'uk_sash22 3 uk_sash66 3 uk_cottage 2 uk_fanlight 2 w_cottage 1',
  door = 'uk_door_red 2 uk_door_blue 1 d_uk_black 2 d_shop_green 1 d_wood_brown 1', plinth = 'none 1', cornice = false, porch = false, two = .6}
S.uk_cottage = {
  walls = 'h_whitewash 3 render_white 3 h_timber 2 h_painted_white 2 h_painted_pink 1 h_painted_cream 1', roofs = 'h_reed 4 slate 3 clay 2',
  shapes = 'gabled 6 half-hipped 2 hipped 2', pitch = {45, 52}, eave = .35, gable = 'wall', win = 'uk_cottage 5 w_cottage 2 uk_sash66 2 nd_small 1',
  door = 'uk_door_red 1 uk_door_blue 1 d_shop_green 2 d_uk_black 1 d_wood_brown 1', plinth = 'none 1', cornice = false, two = .3}

-- --- the North
S.nd_wood = {
  walls = 'falu 5 h_batten_red 4 h_batten_yellow 4 h_batten_white 4 h_batten_blue 1 h_batten_green 1 h_batten_grey 2 clapboard_white 2 clapboard_yellow 1 clapboard_blue 1',
  roofs = 'concrete 4 clay 3 h_seam_black 2 h_seam_red 1 h_seam_grey 1 prof_red 1 prof_grey 1', shapes = 'gabled 9 hipped 1', pitch = {27, 40}, eave = .45,
  gable = 'wall', win = 'nd_white6 4 nd_green 1 nd_three 3 nd_small 1 nd_black 1', door = 'nd_door_green 2 nd_door_blue 2',
  plinth = 'plinth 3 =hw_h_granite 1', two = .5}
S.nd_dark = {
  walls = 'h_batten_black 4 h_plank_dark 3 h_batten_grey 2 h_batten_brown 3 h_clap_black 1 h_log_square 1',
  roofs = 'h_seam_black 4 concrete 3 h_turf 1 h_seam_grey 1 h_wood_shingle 1', shapes = 'gabled 9 hipped 1', pitch = {25, 42}, eave = .4, gable = 'wall',
  win = 'nd_black 4 nd_three 3 nd_white6 2 nd_small 1', door = 'nd_door_blue 2 nd_door_green 1 mo_door_anthr 1', plinth = 'plinth 2 =hw_h_granite 1',
  chimney = .6, two = .5}
S.nd_brick = {
  walls = 'h_brick_buff 5 brick_red 4 h_painted_white 2 render_white 3 h_whitewash 1', roofs = 'concrete 4 clay 3 h_reed 1 h_fibre_grey 2 h_seam_black 1',
  shapes = 'gabled 6 hipped 4', pitch = {24, 45}, eave = .3, gable = 'wall', win = 'nd_three 4 nd_white6 3 nd_brown 2 nd_black 1',
  door = 'nd_door_blue 2 nd_door_green 2 d_modern 1', plinth = 'none 1 plinth 1', cornice = false, two = .2}
S.nd_iceland = {
  walls = 'h_prof_red 3 h_prof_blue 3 h_prof_green 2 h_prof_white 3 h_prof_grey 2 h_batten_white 1 h_cement 2 render_white 1',
  roofs = 'h_corr_red 4 h_corr_green 2 h_corr_blue 2 h_corr_silver 1 h_seam_black 1 h_seam_red 1 h_turf 1', shapes = 'gabled 9 hipped 1', pitch = {25, 40}, eave = .2,
  gable = 'wall', win = 'nd_white6 4 nd_three 2 nd_small 2 nd_green 1', door = 'nd_door_green 2 nd_door_blue 2', plinth = 'plinth 3',
  chimney = .5, two = .5}

-- --- the Mediterranean
S.md_render = {
  walls = 'render_white 4 render_ochre 4 render_sand 3 render_terracotta 3 render_pink 2 flaking_yellow 1',
  roofs = 'h_mission 5 pantile 3 clay 2', shapes = 'hipped 5 gabled 5', pitch = {16, 24}, eave = .3, gable = 'wall',
  win = 'm_shut_green 3 m_shut_brown 3 m_blind 2 m_modern 2 m_small 1 m_shut_turq 1 me_shut 1', door = 'md_green 2 md_blue 1 md_brown 2 md_white 1 md_modern 1 la_door_double 1 me_door_blue 1',
  plinth = 'none 3 =hw_fieldstone 1', chimney = .3, cornice = false, porch = false, two = .7}
S.md_stone = {
  walls = 'sandstone 3 fieldstone 3 h_limestone 4 ashlar 1 h_granite 2 h_schist 1', roofs = 'h_mission 6 pantile 2 h_stone 1 clay 1',
  shapes = 'gabled 6 hipped 4', pitch = {16, 24}, eave = .25, gable = 'wall', win = 'm_shut_brown 3 m_shut_green 2 m_small 2 al_grille 1 m_blind 1',
  door = 'md_brown 2 md_green 2 md_blue 1 al_door_carved 1', plinth = 'none 1', chimney = .4, cornice = false, porch = false, two = .7}
S.md_white = {
  walls = 'h_whitewash 8 render_white 2', roofs = 'h_mission 6 pantile 2', shapes = 'flat 6 gabled 2 hipped 2', pitch = {14, 20}, eave = .2, gable = 'wall',
  win = 'm_small 3 m_shut_turq 2 me_blue 2 m_blind 1 la_blue 2', door = 'md_blue 4 me_door_blue 3 md_white 2', plinth = 'none 1',
  chimney = .15, cornice = false, porch = false, two = .5, flat = 'h_flat_white', rim = {.25, .45}, attic = false}
S.md_unfinished = {
  walls = 'h_frame_brick 3 h_hollow 3 h_cement 3 render_sand 2 block 1', roofs = 'clay 5 pantile 2 h_mission 2', shapes = 'flat 5 hipped 3 gabled 2',
  pitch = {16, 24}, gable = 'wall', win = 'm_modern 3 m_blind 3 al_roller 2 me_roller 2', door = 'md_modern 2 md_white 1 me_door_steel 1 md_shutter 1',
  plinth = 'none 1', chimney = .15, cornice = false, porch = false, two = .9, flat = 'h_flat_grey', rim = {.2, .7}, attic = false}
S.md_basalt = {
  walls = 'h_basalt 4 h_whitewash 5 render_white 1', roofs = 'h_mission 6 pantile 3 clay 1', shapes = 'gabled 5 hipped 4 flat 1', pitch = {16, 24}, eave = .2,
  gable = 'wall', win = 'm_small 3 m_shut_green 2 m_shut_brown 2 m_blind 1 me_shut 2 la_blue 1', door = 'md_green 2 md_blue 2 md_white 1 me_door_blue 2', plinth = 'none 2 =hw_h_basalt 1',
  chimney = .3, cornice = false, porch = false, two = .5, flat = 'h_flat_white'}

-- --- North America
S.us_siding = {
  walls = 'vinyl_white 4 vinyl_grey 3 vinyl_cream 3 h_vinyl_blue 2 h_vinyl_sage 2 h_vinyl_tan 2 clapboard_white 3 clapboard_blue 1 clapboard_yellow 1 '
    .. 'h_clap_grey 2 h_clap_red 1 h_asb_white 1 h_asb_mint 1 h_asb_pink 1 h_asb_blue 1 h_asb_yellow 1',
  roofs = 'shingle 5 h_shingle_brown 3 h_shingle_black 3 h_shingle_red 1 h_shingle_green 1', shapes = 'gabled 6 hipped 4', pitch = {20, 34}, eave = .4,
  gable = 'wall', win = 'us_shut_black 3 us_pair 2 us_picture 2 us_craftsman 2 w_hung 3 us_slider 1', door = 'us_door_red 2 us_door_craft 2 d_us_white 2',
  plinth = 'plinth 2 none 2 =hw_h_brick_ranch 1', chimney = .3, two = .5}
S.us_brick = {
  walls = 'h_brick_ranch 5 brick_red 3 brick_dark 1 h_painted_white 2 h_veneer 2 h_brick_buff 1',
  roofs = 'shingle 5 h_shingle_brown 3 h_shingle_black 3 h_shingle_red 1', shapes = 'hipped 6 gabled 4', pitch = {18, 28}, eave = .45, gable = 'wall',
  win = 'us_shut_black 3 us_pair 3 us_picture 3 w_hung 2 us_slider 1', door = 'us_door_red 2 us_door_craft 2 d_us_white 2', plinth = 'none 1',
  chimney = .4, cornice = false, two = .35}
S.us_stucco = {
  walls = 'h_lace_tan 4 h_lace_beige 4 h_lace_grey 2 h_lace_peach 2 h_lace_sage 1 h_lace_white 2', roofs = 'h_mission 4 concrete 3 shingle 2 h_shingle_brown 1 clay 1',
  shapes = 'hipped 7 gabled 3', pitch = {16, 24}, eave = .35, gable = 'wall', win = 'us_slider 4 us_picture 2 us_small 1 us_pair 2 us_craftsman 1',
  door = 'us_door_craft 2 d_us_white 2 us_door_red 1', plinth = 'none 1', chimney = .1, cornice = false, porch = false, two = .4, attic = false}
S.us_adobe = {
  walls = 'h_earth_tan 4 h_earth_pink 3 h_earth_sand 2 h_lace_tan 2 adobe 1', roofs = 'h_mission 3 h_corr_silver 1 h_seam_red 1', shapes = 'flat 8 hipped 2',
  pitch = {14, 20}, gable = 'wall', win = 'us_small 2 la_blue 3 us_craftsman 2 la_bars 1', door = 'us_door_craft 2 la_door_steel 1 la_door_double 1',
  plinth = 'none 1', chimney = .2, cornice = false, porch = false, two = .1, flat = 'h_flat_tan', rim = {.4, .7}, attic = false}
S.us_shingle = {
  walls = 'h_shakes 5 clapboard_white 3 h_clap_grey 2 h_clap_red 1 h_batten_white 1', roofs = 'h_shingle_black 4 shingle 3 h_wood_shingle 2 h_seam_grey 1',
  shapes = 'gabled 8 hipped 2', pitch = {30, 45}, eave = .3, gable = 'wall', win = 'us_craftsman 3 us_shut_black 2 w_hung 3 us_pair 2 w_sash66 1',
  door = 'us_door_craft 3 us_door_red 2 d_us_white 1', plinth = 'plinth 1 =hw_fieldstone 1 none 1', chimney = .5, two = .6}
S.us_cabin = {
  walls = 'log 3 h_log_square 2 h_batten_brown 2 h_plank_dark 2 h_clap_red 1 h_vinyl_tan 1 h_clap_grey 1',
  roofs = 'h_seam_green 3 h_seam_red 2 h_seam_grey 2 h_seam_brown 1 shingle 2 h_shingle_green 1', shapes = 'gabled 9 hipped 1', pitch = {28, 42}, eave = .5,
  gable = 'wall', win = 'us_craftsman 2 w_hung 3 us_slider 2 nd_small 1 us_pair 1', door = 'us_door_craft 3 d_us_white 1', plinth = 'plinth 1 =hw_fieldstone 1',
  chimney = .6, two = .3}

-- --- Latin America and the Caribbean
S.la_block = {
  walls = 'h_blockp_turq 3 h_blockp_yellow 3 h_blockp_pink 2 h_blockp_lime 1 h_blockp_orange 2 h_blockp_blue 2 h_blockp_white 3 h_blockp_peach 2 '
    .. 'h_stain_yellow 1 h_stain_green 1 h_stain_pink 1 h_stain_blue 1',
  roofs = 'h_corr_silver 3 zinc 2 tin 1 h_mission 2 h_corr_red 1', shapes = 'flat 6 gabled 3 hipped 1', pitch = {10, 18}, eave = .3, gable = 'wall',
  win = 'la_reja 3 la_bars 3 la_louvre 2 la_slide 3 la_blue 1', door = 'la_door_steel 4 la_door_double 1', plinth = 'none 1',
  chimney = 0, cornice = false, porch = false, two = .45, flat = 'h_flat_grey', rim = {.2, .6}, attic = false}
S.la_unfinished = {
  walls = 'h_hollow 4 h_frame_brick 3 h_brick_common 3 block 2 h_cement 2', roofs = 'zinc 3 tin 1 h_corr_silver 2', shapes = 'flat 7 gabled 3',
  pitch = {8, 16}, gable = 'wall', win = 'la_bars 4 la_slide 3 la_louvre 2 la_reja 1', door = 'la_door_steel 5', plinth = 'none 1',
  chimney = 0, cornice = false, porch = false, two = .5, flat = 'h_flat_grey', rim = {.15, .9}, attic = false}
S.la_colonial = {
  walls = 'h_stain_white 3 h_stain_yellow 3 h_stain_ochre 2 h_stain_terracotta 2 h_stain_pink 1 h_stain_blue 2 render_white 2 h_whitewash 2',
  roofs = 'h_mission 8 pantile 2', shapes = 'gabled 6 hipped 4', pitch = {18, 25}, eave = .5, gable = 'wall',
  win = 'la_colonial 4 la_reja 3 la_blue 2', door = 'la_door_double 4 la_door_steel 1 md_brown 1', plinth = 'none 2 =hw_fieldstone 1',
  chimney = 0, cornice = false, porch = false, two = .3, attic = false}
S.la_adobe = {
  walls = 'h_mudbrick 4 h_earth_tan 3 h_earth_red 2 adobe 1 h_whitewash 2 h_rammed 1', roofs = 'h_mission 4 h_corr_silver 3 tin 2 h_reed 1',
  shapes = 'gabled 7 hipped 3', pitch = {18, 26}, eave = .4, gable = 'wall', win = 'la_blue 3 la_bars 3 af_plank 2', door = 'la_door_steel 2 af_door_plank 2 la_door_double 1',
  plinth = 'none 2 =hw_fieldstone 1', chimney = 0, cornice = false, porch = false, two = .1, attic = false}
S.la_wood = {
  walls = 'h_clap_turq 3 h_clap_pink 2 h_clap_green 2 clapboard_yellow 2 clapboard_blue 2 clapboard_white 2 h_shakes 2 h_prof_blue 1 h_prof_green 1',
  roofs = 'h_corr_red 3 h_corr_green 2 h_corr_blue 1 h_corr_silver 3 zinc 1', shapes = 'gabled 7 hipped 3', pitch = {25, 38}, eave = .4, gable = 'wall',
  win = 'la_louvre 3 la_blue 2 us_craftsman 2 se_turq 1 w_hung 1', door = 'la_door_steel 1 us_door_craft 1 se_door_green 2', plinth = 'none 2 plinth 1',
  chimney = .1, two = .25, attic = false}

-- --- East Asia
S.jp_modern = {
  walls = 'h_jps_beige 4 h_jps_cream 3 h_jps_grey 3 h_jps_brown 2 h_jps_white 3 h_jps_blue 1 render_white 1 vinyl_grey 1',
  roofs = 'h_kawara_silver 3 h_kawara_black 3 h_seam_black 2 h_seam_grey 1 h_seam_brown 2 concrete 2 h_shingle_black 1',
  shapes = 'hipped 5 gabled 5', pitch = {22, 30}, eave = .45, gable = 'wall', win = 'jp_frost 3 jp_wide 4 jp_rail 3 jp_slit 1 jp_narrow 1',
  door = 'jp_door_modern 4 jp_door_genkan 1', plinth = 'plinth 1', chimney = 0, cornice = false, porch = false, two = .85, attic = false}
S.jp_old = {
  walls = 'h_yakisugi 4 render_white 3 h_earth_sand 2 wood 1 zinc 1 h_batten_brown 1', roofs = 'h_kawara_silver 5 h_kawara_black 3 h_kawara_brown 2 h_kawara_blue 1 h_seam_brown 1',
  shapes = 'hipped 6 gabled 4', pitch = {26, 34}, eave = .7, gable = 'wall', win = 'jp_koshi 4 jp_frost 3 jp_wide 2', door = 'jp_door_genkan 4 jp_door_modern 1',
  plinth = 'none 1 plinth 1', chimney = 0, cornice = false, porch = false, two = .5, attic = false}
S.cn_tile = {
  walls = 'h_tile_white 5 h_strip_pink 2 h_strip_ochre 2 h_strip_mint 1 h_cement 2 h_stain_white 1 h_strip_brown 1',
  roofs = 'h_kawara_black 3 h_corr_blue 2 h_kawara_orange 1 h_corr_red 1 clay 1', shapes = 'flat 5 gabled 4 hipped 1', pitch = {20, 28}, eave = .3, gable = 'wall',
  win = 'cn_blue 4 cn_green 3 cn_cage 2 cn_korea 1', door = 'cn_door_red 3 cn_door_steel 4', plinth = 'none 1', chimney = 0, cornice = false, porch = false,
  two = .8, flat = 'h_flat_grey', rim = {.3, .9}, attic = false}
S.cn_brick = {
  walls = 'h_cn_grey 4 brick_red 4 h_brick_common 2 h_rammed 1 h_cement 1', roofs = 'h_kawara_silver 4 clay 3 h_corr_blue 2 h_corr_red 1 h_kawara_black 2',
  shapes = 'gabled 9 hipped 1', pitch = {22, 30}, eave = .3, gable = 'wall', win = 'cn_lattice 2 cn_blue 3 cn_green 3', door = 'cn_door_red 4 cn_door_steel 2',
  plinth = 'none 1', chimney = .15, cornice = false, porch = false, two = .15, attic = false}
S.kr_villa = {
  walls = 'brick_red 3 clinker 2 h_tile_white 2 h_cement 1 h_stain_white 2 h_stain_cream 1 h_face_red 1', roofs = 'h_kawara_blue 3 h_kawara_orange 3 h_kawara_silver 2 h_seam_blue 1 h_seam_green 1',
  shapes = 'flat 4 hipped 4 gabled 2', pitch = {20, 30}, eave = .35, gable = 'wall', win = 'cn_korea 5 jp_wide 2 cn_green 1', door = 'cn_door_steel 3 jp_door_modern 2',
  plinth = 'none 1 plinth 1', chimney = 0, cornice = false, porch = false, two = .7, flat = 'h_flat_grey', rim = {.5, .9}, attic = false}
S.mn_wood = {
  walls = 'bd_green 2 bd_blue 2 bd_brown 2 boards 3 log 2 h_cement 2 silicate 2 h_brick_common 1', roofs = 'h_corr_red 4 h_corr_green 3 h_corr_blue 3 h_corr_silver 2',
  shapes = 'gabled 7 hipped 3', pitch = {22, 34}, gable = 'wall', win = 'ua_brown 3 ua_blue 2 w_pvc_blinds 2', door = 'ua_door_steel 2 ua_door_plank 2',
  plinth = 'plinth 1', chimney = .7, two = .05}

-- --- South Asia
S.in_pucca = {
  walls = 'h_stain_pink 3 h_stain_blue 3 h_stain_yellow 3 h_stain_green 2 h_stain_cream 3 h_stain_white 2 h_stain_lilac 1 h_blockp_peach 1 h_blockp_lime 1 h_cement 1',
  roofs = 'tin 2 h_corr_silver 2 clay 1', shapes = 'flat 9 gabled 1', pitch = {12, 20}, gable = 'wall', win = 'sa_grille 4 sa_shut 2 sa_slide 3 sa_jali 1 sa_colour 1 sa_arch 1',
  door = 'sa_door_carved 2 sa_door_steel 4', plinth = 'none 1', chimney = 0, cornice = false, porch = false, two = .6, flat = 'h_flat_grey', rim = {.5, .9}, attic = false}
S.in_brick = {
  walls = 'h_brick_common 6 brick_red 2 h_frame_brick 3 h_cement 2', roofs = 'tin 2 h_corr_silver 2 zinc 1', shapes = 'flat 8 gabled 2', pitch = {10, 18},
  gable = 'wall', win = 'sa_grille 3 sa_shut 3 sa_jali 2 sa_arch 1', door = 'sa_door_steel 4 sa_door_carved 1', plinth = 'none 1',
  chimney = 0, cornice = false, porch = false, two = .5, flat = 'h_flat_grey', rim = {.15, .8}, attic = false}
S.in_kutcha = {
  walls = 'h_earth_tan 3 h_earth_red 2 h_earth_umber 1 h_mudbrick 2 h_bamboo 2 h_whitewash 1', roofs = 'h_palm 2 h_reed 2 clay 3 tin 2 h_corr_silver 2',
  shapes = 'gabled 6 hipped 4', pitch = {22, 32}, eave = .6, gable = 'wall', win = 'sa_shut 3 af_plank 2 sa_arch 1 se_bars 2', door = 'sa_door_steel 1 af_door_plank 3',
  plinth = 'none 1', chimney = 0, cornice = false, porch = false, two = 0, attic = false}
S.in_laterite = {
  walls = 'h_laterite 4 h_stain_white 3 h_stain_yellow 2 h_stain_cream 2', roofs = 'clay 6 pantile 2 h_mission 1', shapes = 'hipped 7 gabled 3', pitch = {26, 34}, eave = .8,
  gable = 'wall', win = 'sa_colour 3 sa_shut 3 sa_grille 2', door = 'sa_door_carved 3 sa_door_steel 1', plinth = 'none 1 =hw_h_laterite 1',
  chimney = 0, cornice = false, porch = false, two = .4, attic = false}
S.hm_stone = {
  walls = 'h_schist 4 fieldstone 2 h_rammed 2 h_whitewash 2 h_brick_common 2', roofs = 'h_stone 3 h_corr_silver 3 h_corr_blue 2 h_corr_red 1 tin 1',
  shapes = 'gabled 8 hipped 2', pitch = {18, 26}, eave = .5, gable = 'wall', win = 'sa_colour 3 sa_shut 3 se_fret 2 al_grille 1', door = 'sa_door_carved 2 af_door_plank 2',
  plinth = 'none 1', chimney = .2, cornice = false, porch = false, two = .7, attic = false}

-- --- Southeast Asia and the Pacific
S.se_wood = {
  walls = 'h_teak 5 h_clap_turq 1 h_clap_green 1 clapboard_blue 1 h_bamboo 2 wood 1', roofs = 'h_corr_silver 3 h_corr_red 2 h_corr_blue 2 h_corr_green 1 tin 2 h_palm 2 clay 1',
  shapes = 'gabled 6 hipped 4', pitch = {28, 40}, eave = .7, gable = 'wall', win = 'se_louvre 3 se_turq 3 se_fret 2 se_bars 2', door = 'se_door_green 3 af_door_plank 1',
  plinth = 'none 1', chimney = 0, cornice = false, two = .3, attic = false}
S.se_block = {
  walls = 'h_stain_white 3 h_stain_cream 3 h_stain_yellow 2 h_stain_green 2 h_stain_blue 1 h_stain_pink 1 h_blockp_white 2 h_blockp_turq 1 h_blockp_peach 1 h_cement 1',
  roofs = 'h_corr_red 2 h_corr_blue 2 h_corr_silver 2 h_corr_green 1 clay 3 concrete 2 zinc 1', shapes = 'hipped 6 gabled 4', pitch = {22, 32}, eave = .6,
  gable = 'wall', win = 'se_slide 4 se_louvre 3 se_fold 1 cn_viet 1', door = 'se_door_gate 2 se_door_green 2 sa_door_steel 2', plinth = 'none 1',
  chimney = 0, cornice = false, porch = false, two = .5, attic = false}
S.se_shophouse = {
  walls = 'h_tile_white 3 h_strip_pink 1 h_strip_ochre 1 h_strip_mint 1 h_stain_yellow 2 h_stain_cream 2 h_stain_green 1 h_stain_blue 1',
  roofs = 'h_corr_blue 2 h_corr_red 2 clay 2', shapes = 'flat 5 hipped 3 gabled 2', pitch = {18, 28}, gable = 'wall', win = 'cn_viet 3 se_fold 2 se_slide 3 cn_blue 2',
  door = 'se_door_gate 5 cn_door_steel 1', plinth = 'none 1', chimney = 0, cornice = false, porch = false, two = .9, flat = 'h_flat_grey', rim = {.4, .9}, attic = false}
S.se_bamboo = {
  walls = 'h_bamboo 6 h_teak 2 tin 1', roofs = 'h_palm 6 tin 2 h_corr_silver 2', shapes = 'gabled 6 hipped 4', pitch = {32, 42}, eave = .7, gable = 'wall',
  win = 'se_bars 4 se_turq 2 af_plank 2', door = 'af_door_plank 3 se_door_green 1', plinth = 'none 1', chimney = 0, cornice = false, porch = false, two = 0, attic = false}

-- --- the Middle East and North Africa
S.me_stone = {
  walls = 'h_jerusalem 6 sandstone 2 h_limestone 2', roofs = 'h_mission 3 clay 1', shapes = 'flat 9 hipped 1', pitch = {18, 26}, gable = 'wall',
  win = 'me_arch 3 me_roller 3 me_shut 3 me_small 1', door = 'me_door_steel 4 me_door_blue 1', plinth = 'none 1', chimney = 0, cornice = false, porch = false,
  two = .7, flat = 'h_flat_grey', rim = {.4, .8}, attic = false}
S.me_render = {
  walls = 'render_sand 4 render_white 3 h_stain_cream 3 h_cement 2 h_lace_beige 2 h_stain_white 1 h_stain_ochre 1', roofs = 'zinc 1 h_mission 1', shapes = 'flat 10',
  pitch = {12, 18}, gable = 'wall', win = 'me_roller 4 me_shut 3 me_arch 2 me_mashrabiya 1', door = 'me_door_steel 4 me_door_blue 1', plinth = 'none 1',
  chimney = 0, cornice = false, porch = false, two = .7, flat = 'h_flat_grey', rim = {.4, .9}, attic = false}
S.me_unfinished = {
  walls = 'block 4 h_hollow 3 h_frame_brick 2 h_cement 4', roofs = 'zinc 1 tin 1', shapes = 'flat 10', pitch = {10, 16}, gable = 'wall',
  win = 'me_roller 3 me_small 3 me_shut 2 la_bars 1', door = 'me_door_steel 4 af_door_steel 1', plinth = 'none 1', chimney = 0, cornice = false, porch = false,
  two = .6, flat = 'h_flat_grey', rim = {.15, .9}, attic = false}
S.me_mud = {
  walls = 'h_mudbrick 4 h_earth_tan 3 h_earth_sand 3 h_rammed 1 h_earth_pink 1', roofs = 'h_reed 1 tin 1', shapes = 'flat 10', pitch = {10, 16}, gable = 'wall',
  win = 'me_small 4 me_shut 2 af_plank 2', door = 'me_door_blue 2 af_door_plank 3 me_door_steel 2', plinth = 'none 1', chimney = 0, cornice = false, porch = false,
  two = .2, flat = 'h_flat_mud', rim = {.2, .5}, attic = false}
S.me_brick = {
  walls = 'h_brick_buff 6 h_cement 2 render_sand 2 h_frame_brick 1', roofs = 'zinc 1 tin 1', shapes = 'flat 10', pitch = {10, 16}, gable = 'wall',
  win = 'me_roller 3 me_shut 3 me_arch 2 me_small 1', door = 'me_door_steel 4 me_door_blue 1', plinth = 'none 1', chimney = 0, cornice = false, porch = false,
  two = .7, flat = 'h_flat_grey', rim = {.3, .8}, attic = false}

-- --- Africa south of the Sahara
S.af_block = {
  walls = 'block 4 h_blockp_white 2 h_blockp_blue 2 h_blockp_yellow 2 h_blockp_turq 1 h_blockp_peach 2 h_cement 3 h_stain_cream 2 h_stain_green 1',
  roofs = 'h_corr_silver 5 zinc 3 tin 3 h_corr_red 2 h_corr_blue 2 h_corr_green 1', shapes = 'hipped 5 gabled 5', pitch = {14, 24}, eave = .5, gable = 'wall',
  win = 'af_casement 4 af_wide 2 af_louvre 2 af_small 2 af_breeze 1', door = 'af_door_steel 4 af_door_plank 2', plinth = 'none 1',
  chimney = 0, cornice = false, porch = false, two = .12, attic = false}
S.af_brick = {
  walls = 'h_brick_common 6 brick_red 2 h_cement 1 h_frame_brick 1', roofs = 'h_corr_silver 5 tin 3 zinc 2 h_reed 2', shapes = 'gabled 6 hipped 4', pitch = {14, 26}, eave = .4,
  gable = 'wall', win = 'af_casement 3 af_small 3 af_plank 2 af_breeze 1', door = 'af_door_steel 3 af_door_plank 3', plinth = 'none 1',
  chimney = 0, cornice = false, porch = false, two = .05, attic = false}
S.af_mud = {
  walls = 'h_earth_red 4 h_earth_tan 3 h_earth_umber 2 h_mudbrick 3', roofs = 'h_reed 4 h_palm 2 tin 3 h_corr_silver 2', shapes = 'hipped 5 gabled 5', pitch = {25, 40}, eave = .6,
  gable = 'wall', win = 'af_plank 4 af_small 2 se_bars 1', door = 'af_door_plank 4 af_door_steel 1', plinth = 'none 1', chimney = 0, cornice = false, porch = false,
  two = 0, attic = false}
S.af_shack = {
  walls = 'h_tinpatch 5 tin 2 zinc 2 h_prof_blue 1 h_prof_green 1', roofs = 'tin 4 zinc 3 h_corr_silver 3', shapes = 'gabled 10', pitch = {6, 12}, eave = .2, gable = 'wall',
  win = 'af_small 3 af_plank 3 af_louvre 1', door = 'af_door_plank 3 af_door_steel 2', plinth = 'none 1', chimney = 0, cornice = false, porch = false, two = 0, attic = false}
S.zb_coral = {
  walls = 'h_coral 5 h_stain_white 3 h_whitewash 2 block 2 h_stain_cream 1', roofs = 'h_palm 4 h_corr_silver 3 tin 2 zinc 1 h_corr_red 1',
  shapes = 'hipped 7 gabled 3', pitch = {28, 38}, eave = .6, gable = 'wall', win = 'se_bars 2 af_plank 2 me_mashrabiya 1 af_casement 3 se_turq 1',
  door = 'sa_door_carved 3 af_door_plank 2 me_door_blue 1', plinth = 'none 1', chimney = 0, cornice = false, porch = false, two = .25, attic = false}
S.za_suburb = {
  walls = 'brick_red 4 h_face_yellow 2 h_face_brown 1 render_white 3 h_lace_beige 3 h_stain_cream 1 h_brick_ranch 2', roofs = 'concrete 5 h_corr_red 2 h_corr_green 1 clay 2 h_reed 1 h_corr_silver 1',
  shapes = 'hipped 6 gabled 4', pitch = {18, 26}, eave = .5, gable = 'wall', win = 'af_wide 3 af_casement 3 us_slider 2 us_picture 1', door = 'us_door_craft 1 af_door_steel 2 d_modern 1',
  plinth = 'none 2 =hw_brick_red 1', chimney = .3, cornice = false, two = .15, attic = false}

-- --- Australia and New Zealand
S.au_weatherboard = {
  walls = 'clapboard_white 4 clapboard_blue 1 clapboard_yellow 2 h_clap_grey 2 h_clap_green 1 h_fibro_green 2 h_fibro_cream 2 h_fibro_blue 1 h_fibro_white 2',
  roofs = 'h_corr_silver 4 h_corr_red 3 h_corr_green 2 h_corr_blue 1 h_corr_cream 1 concrete 2', shapes = 'hipped 6 gabled 4', pitch = {20, 30}, eave = .5, gable = 'wall',
  win = 'w_sash22 3 us_slider 3 w_hung 2 us_picture 1 us_pair 1', door = 'd_us_white 2 us_door_red 1 us_door_craft 1', plinth = 'none 2 =hw_brick_red 1',
  chimney = .3, two = .15}
S.au_brick = {
  walls = 'h_brick_buff 4 brick_red 3 h_brick_ranch 3 brick_dark 1 h_lace_beige 2 h_lace_grey 1 h_painted_white 1', roofs = 'concrete 6 clay 3 h_seam_grey 2 h_corr_cream 1 h_corr_silver 1',
  shapes = 'hipped 8 gabled 2', pitch = {20, 26}, eave = .5, gable = 'wall', win = 'us_slider 5 us_picture 3 us_pair 1', door = 'us_door_craft 2 d_us_white 2 d_modern 1',
  plinth = 'none 1', chimney = .15, cornice = false, two = .2, attic = false}

-- ---------------------------------------------------------------------------------------------
-- Regions: a look's block, as 'style weight' words; arid, tropic, med and cold stand in where
-- the climate is that (a desert or a steppe; a rainforest or a savanna; the Mediterranean kind;
-- the taiga and the tundra). A block not named here keeps the generator's own lists.
M.regions = {
  postsoviet = {any = 'ua_khata 4 ua_wood 3 ua_brick 5 ua_cottage 5 ua_unfinished 1', cold = 'ru_izba 6 ua_wood 3 ua_brick 3 ua_cottage 3'},
  central = {any = 'ce_cube 3 ce_village 4 ce_new 3 bk_unfinished 1 bk_render 1', med = 'bk_render 4 md_stone 3 bk_unfinished 2 ce_new 1'},
  western = {any = 'we_render 5 we_brick 3 we_timber 1 we_stone 2 we_slate 1 we_modern 2', med = 'md_render 5 md_stone 3 we_stone 2 we_modern 1',
    cold = 'al_chalet 5 we_render 3 we_modern 1'},
  british = {any = 'uk_brick 5 uk_dash 4 uk_stone 2 uk_cottage 1'},
  nordic = {any = 'nd_wood 6 nd_dark 2 nd_brick 2', cold = 'nd_wood 5 nd_dark 4 nd_iceland 1'},
  mediterranean = {any = 'md_render 5 md_stone 3 md_white 1 md_unfinished 1', arid = 'md_white 3 md_render 4 md_unfinished 2 md_stone 2',
    cold = 'md_stone 4 al_chalet 2 md_render 3'},
  ['north-america'] = {any = 'us_siding 6 us_brick 4 us_shingle 1 us_stucco 1', arid = 'us_stucco 6 us_adobe 2 us_brick 1 us_siding 2',
    med = 'us_stucco 6 us_siding 3 us_shingle 1 us_brick 1', tropic = 'us_stucco 5 us_siding 2 la_block 2 la_wood 1', cold = 'us_siding 5 us_cabin 3 us_brick 1 us_shingle 1'},
  latin = {any = 'la_block 5 la_unfinished 3 la_colonial 2 la_adobe 1', arid = 'la_adobe 3 la_block 4 la_unfinished 3',
    tropic = 'la_block 5 la_wood 2 la_unfinished 2 la_colonial 2', cold = 'la_wood 4 la_adobe 3 la_block 2 la_unfinished 1'},
  ['east-asia'] = {any = 'jp_modern 3 cn_tile 4 cn_brick 3 jp_old 1', cold = 'cn_brick 5 mn_wood 3 cn_tile 2', arid = 'cn_brick 5 ca_mud 3 cn_tile 2'},
  ['south-asia'] = {any = 'in_pucca 5 in_brick 3 in_kutcha 2', tropic = 'in_pucca 4 in_laterite 3 in_kutcha 2 in_brick 1',
    arid = 'in_pucca 5 in_brick 3 me_mud 2', cold = 'hm_stone 6 in_brick 2 in_pucca 2'},
  ['southeast-asia'] = {any = 'se_block 5 se_wood 3 se_shophouse 2 se_bamboo 1'},
  ['middle-east'] = {any = 'me_render 4 me_unfinished 3 me_stone 2 me_mud 2 me_brick 1', med = 'me_stone 4 me_render 3 me_unfinished 2 md_white 1'},
  africa = {any = 'af_block 5 af_brick 3 af_mud 2 af_shack 1', tropic = 'af_block 5 af_mud 3 af_brick 2 af_shack 1',
    arid = 'me_mud 3 me_unfinished 3 me_render 3 af_block 2 md_white 1', med = 'me_render 3 md_white 3 me_unfinished 3 md_render 1'},
  oceania = {any = 'au_brick 5 au_weatherboard 4', tropic = 'au_weatherboard 5 au_brick 2 se_block 2 af_block 1', arid = 'au_weatherboard 4 au_brick 3 af_shack 1'},
}
-- A country of its own inside its block (a pack's id, or its first word): its lists in place of
-- the block's. A zone the country does not name falls to its `any`.
M.countries = {
  estonia = {any = 'bal_wood 5 ua_brick 3 ua_cottage 3 nd_wood 1'},
  georgia = {any = 'cau_stone 5 ua_brick 2 ua_cottage 2 bk_unfinished 2'},
  uzbekistan = {any = 'ca_mud 6 ua_brick 2 ua_cottage 1 me_brick 1'},
  kazakhstan = {any = 'ua_brick 4 ua_wood 2 ua_cottage 3 ca_mud 1 ua_khata 1', arid = 'ca_mud 4 ua_brick 4 ua_cottage 2', cold = 'ru_izba 5 ua_brick 3 ua_cottage 2'},
  russia = {any = 'ru_izba 4 ua_wood 3 ua_brick 4 ua_cottage 4 ua_unfinished 1', cold = 'ru_izba 7 ua_brick 2 ua_cottage 2'},
  romania = {any = 'bk_render 4 ce_village 3 bk_unfinished 2 ce_new 2 ua_khata 1'},
  croatia = {any = 'bk_render 4 bk_unfinished 3 ce_village 2 ce_new 1', med = 'md_stone 4 bk_render 4 bk_unfinished 2'},
  netherlands = {any = 'we_brick 8 we_modern 2 we_render 1'},
  france = {any = 'we_stone 4 we_render 4 we_brick 1 we_slate 1 we_timber 1 we_modern 2', med = 'md_render 5 md_stone 3 we_stone 2', cold = 'al_chalet 5 we_stone 3 we_render 2'},
  germany = {any = 'we_render 5 we_brick 2 we_timber 2 we_slate 1 we_modern 2', cold = 'al_chalet 5 we_render 4 we_modern 1'},
  switzerland = {any = 'al_chalet 5 we_render 4 we_modern 2 we_stone 1'},
  ireland = {any = 'uk_dash 5 uk_stone 3 uk_brick 2 uk_cottage 2'},
  denmark = {any = 'nd_brick 6 nd_wood 2 uk_cottage 1 nd_dark 1'},
  norway = {any = 'nd_wood 5 nd_dark 4 nd_brick 1'},
  iceland = {any = 'nd_iceland 6 nd_dark 2 nd_wood 2'},
  greece = {any = 'md_white 5 md_render 3 md_stone 2 md_unfinished 2'},
  turkey = {any = 'md_unfinished 4 md_render 4 md_stone 1 bk_render 1 me_render 1', arid = 'md_unfinished 4 me_render 3 me_mud 2 md_stone 1'},
  azores = {any = 'md_basalt 5 md_render 3 md_white 2'},
  japan = {any = 'jp_modern 7 jp_old 3'},
  china = {any = 'cn_tile 5 cn_brick 4 se_shophouse 1', cold = 'cn_brick 6 cn_tile 3 mn_wood 1', arid = 'cn_brick 5 ca_mud 3 cn_tile 2'},
  taiwan = {any = 'cn_tile 6 jp_old 1 se_shophouse 2 la_unfinished 1'},
  ['south-korea'] = {any = 'kr_villa 6 cn_tile 2 jp_modern 2'},
  mongolia = {any = 'mn_wood 6 cn_brick 2 ua_brick 2'},
  nepal = {any = 'hm_stone 5 in_brick 3 in_pucca 2'},
  ['sri-lanka'] = {any = 'in_laterite 4 in_pucca 4 in_kutcha 2'},
  maldives = {any = 'zb_coral 5 in_pucca 4 se_block 1'},
  vietnam = {any = 'se_shophouse 4 se_block 4 cn_tile 2 se_wood 1'},
  philippines = {any = 'se_block 4 se_wood 3 se_bamboo 2 la_unfinished 1'},
  israel = {any = 'me_stone 6 me_render 2 me_unfinished 2'},
  iran = {any = 'me_brick 5 me_mud 2 me_render 2 me_unfinished 2'},
  afghanistan = {any = 'me_mud 6 me_unfinished 2 me_stone 2'},
  ['gcc-states'] = {any = 'me_render 6 me_unfinished 2 me_stone 1 me_mud 1'},
  zanzibar = {any = 'zb_coral 5 af_block 4 af_mud 1 af_shack 1'},
  tanzania = {any = 'af_block 4 af_brick 3 af_mud 2 zb_coral 1 af_shack 1'},
  ['south-africa'] = {any = 'za_suburb 5 af_block 2 af_shack 2 af_brick 1'},
  mexico = {any = 'la_block 5 la_unfinished 3 la_colonial 2 la_adobe 1', arid = 'la_adobe 3 la_block 4 la_unfinished 2 us_adobe 1'},
  chile = {any = 'la_wood 4 la_block 3 la_unfinished 2 la_colonial 1', arid = 'la_adobe 4 la_block 3 la_unfinished 3'},
  ['new-zealand'] = {any = 'au_weatherboard 6 au_brick 3 nd_dark 1'},
}
-- countries that go by another's lists
for id, like in pairs({latvia = 'estonia', lithuania = 'estonia', armenia = 'georgia', azerbaijan = 'georgia', turkmenistan = 'uzbekistan',
    tajikistan = 'uzbekistan', kyrgyzstan = 'uzbekistan', bulgaria = 'romania', moldova = 'romania', serbia = 'croatia',
    ['bosnia-herzegovina'] = 'croatia', montenegro = 'croatia', macedonia = 'croatia', kosovo = 'croatia', albania = 'croatia',
    slovenia = 'croatia', belgium = 'netherlands', austria = 'switzerland', liechtenstein = 'switzerland', alps = 'switzerland',
    ['faroe-islands'] = 'iceland', greenland = 'iceland', cyprus = 'greece', malta = 'greece', ['north-korea'] = 'south-korea',
    bhutan = 'nepal', jordan = 'israel', lebanon = 'israel', syria = 'israel', ['israel-and-palestine'] = 'israel', iraq = 'iran',
    yemen = 'afghanistan', scotland = 'ireland', wales = 'ireland', ['ireland-and-northern-ireland'] = 'ireland'}) do
  M.countries[id] = M.countries[like]
end

-- ---------------------------------------------------------------------------------------------
-- What a wall is made of, by its kind's name: a material OSM names picks among a style's walls
-- of that make.
local MAKES = {
  {'earth', 'adobe', 'earth_', 'mudbrick', 'rammed'},
  {'brick', 'brick', 'clinker', 'stock', 'silicate', 'face_', 'painted_', 'cn_grey', 'hollow'},
  {'stone', 'stone', 'granite', 'schist', 'basalt', 'laterite', 'coral', 'jerusalem', 'tuff', 'ashlar', 'shell', 'veneer'},
  {'wood', 'boards', '_bd_', 'log', 'wood', 'hw_siding', 'clap', 'batten', 'plank', 'shakes', 'teak', 'falu', 'timber', 'yakisugi', 'bamboo'},
  {'block', 'hw_block', 'blockp', 'aerated'},
  {'vinyl', 'vinyl'},
}
local makeOf = {}
function M.make(kind)
  local make = makeOf[kind]
  if make == nil then
    make = 'plaster'
    for _, row in ipairs(MAKES) do
      for k = 2, #row do
        if kind:find(row[k], 1, true) then make = row[1]; break end
      end
      if make ~= 'plaster' then break end
    end
    makeOf[kind] = make
  end
  return make
end
M.TAGS = {brick = 'brick', bricks = 'brick', stone = 'stone', masonry = 'stone', limestone = 'stone', sandstone = 'stone',
  wood = 'wood', timber_framing = 'wood', log = 'wood', plaster = 'plaster', stucco = 'plaster', render = 'plaster',
  adobe = 'earth', mud = 'earth', clay = 'earth', cement_block = 'block', concrete_block = 'block', block = 'block',
  vinyl = 'vinyl', plastic = 'vinyl'}

-- A style's lists, made once. kit: the kit's cells are in this planet.
local function ready(style)
  if style.lists then return style.lists end
  local L = {walls = words(style.walls, 'hw_'), roofs = words(style.roofs, 'roof_'), shapes = words(style.shapes), makes = {}}
  for _, kind in ipairs(L.walls) do
    local make = M.make(kind)
    L.makes[make] = L.makes[make] or {}
    L.makes[make][#L.makes[make] + 1] = kind
  end
  -- plinths: 'none' is no plinth, '=kind' a wall's kind
  L.plinths = {}
  for _, name in ipairs(words(style.plinth or 'plinth 1')) do
    if name == 'none' then L.plinths[#L.plinths + 1] = false
    elseif name:sub(1, 1) == '=' then L.plinths[#L.plinths + 1] = name:sub(2)
    else L.plinths[#L.plinths + 1] = name end
  end
  -- windows and doors: with the kit's cells and without them
  for _, key in ipairs({'win', 'door'}) do
    local all, own = {}, {}
    for _, name in ipairs(words(style[key] or '')) do
      if LIB.cells[name] then all[#all + 1], own[#own + 1] = LIB.cells[name], LIB.cells[name]
      elseif KIT.cells[name] then all[#all + 1] = KIT.cells[name] end
    end
    L[key], L[key .. 'Own'] = all, own
  end
  style.lists = L
  return L
end

-- yard: the style's outbuildings are the post-Soviet yard's own (generator.lua BLD.SMALL: silicate
-- brick, cinder block, welded steel, wave slate); any other style's garage and shed are built of
-- what its houses are
for name, style in pairs(S) do
  style.name = name
  style.yard = (name:find('^ua_') or name:find('^ru_') or name:find('^bal_') or name:find('^cau_') or name:find('^ca_')
    or name:find('^mn_')) and true or false
end

-- The library's art in this planet, or options.houseArt: true forces it (tests), false keeps the
-- generator's own houses. E2R_HOUSES = false in the game's Lua console is the way back without a
-- rebuild of the planet (then land again).
function M.enabled(options)
  options = options or NONE
  if options.houseArt ~= nil then return options.houseArt and true or false end
  if rawget(_G, 'E2R_HOUSES') == false then return false end
  if options.realStyle == false then return false end
  if M.found == nil then
    M.found = (FS and next(LIB.cells) and FS:fileExists(M.ART)) and true or false
  end
  return M.found
end

-- The lists of a place: its country's, else its block's; nil where neither is named.
function M.region(block, country)
  local id = tostring(country or '')
  return M.countries[id] or M.countries[id:match('^[^-]+') or ''] or M.regions[block or '']
end

-- arid, tropic, med, cold or nil for a temperate place (biome.lua's place)
function M.zone(place)
  if not place then return nil end
  if place.arid then return 'arid' end
  local g = place.group
  if g == 'rainforest' or g == 'savanna' then return 'tropic' end
  if g == 'mediterranean' then return 'med' end
  if g == 'boreal' or g == 'tundra' or g == 'ice' then return 'cold' end
  return nil
end

-- A patch of the map is of one kind: two houses of three take the style their patch names
-- (about 170 m across, its edges bent so that no patch is a square on the map), the third its own.
M.PATCH = {size = 170, bend = 45, share = 3}
function M.pick(region, place, h, x, y)
  if not region then return nil end
  local zone = M.zone(place)
  local spec = zone and region[zone] or region.any
  region.lists = region.lists or {}
  local list = region.lists[spec]
  if not list then
    list = words(spec)
    region.lists[spec] = list
  end
  local n = ih(h, 7)
  if x and ih(h, 5) % M.PATCH.share ~= 0 then
    local P = M.PATCH
    n = ih(floor((x + P.bend * sin(y / 97)) / P.size) + 40000, floor((y + P.bend * sin(x / 113)) / P.size) + 40000, 3)
  end
  return S[list[n % #list + 1]]
end

-- The wall of house h in a style. material: OSM's building:material ('' when it names none);
-- a material the style has no wall of gives nil (the generator's own answer for it).
function M.wall(style, material, h)
  local L = ready(style)
  local make = M.TAGS[material or '']
  if make then
    local list = L.makes[make]
    return list and list[ih(h, 3) % #list + 1] or nil
  end
  if material and material ~= '' then return nil end
  return L.walls[ih(h, 3) % #L.walls + 1]
end

-- The roof of an outbuilding beside a house of this style: its flat roof's kind under a flat or a
-- lean-to shape, one of its roofs otherwise.
function M.roofOf(style, h, shape)
  local L = ready(style)
  if shape == 'flat' then return 'roof_' .. (style.flat or 'h_flat_grey') end
  return L.roofs[ih(h, 13) % #L.roofs + 1]
end

-- Floors of a house whose height OSM does not say: 1 or 2, or nil for the generator's own guess.
function M.floors(style, area, h)
  if not style.two or area < 45 or area >= 260 then return nil end
  local share = area >= 140 and min(1, style.two + .25) or style.two
  return ih(h, 37) % 100 < share * 100 and 2 or 1
end

-- A cell's size on a wall: its own, fitted into maxW x maxH with its proportions kept.
function M.fit(cell, maxW, maxH)
  local k = min(1, maxW / cell[5], maxH / cell[6])
  return cell[5] * k, cell[6] * k
end

-- Dress house h in its style: d is the generator's dress (BLD.dress), kind its wall. tags: OSM's.
function M.dress(d, style, kind, h, kit, tags)
  local L = ready(style)
  tags = tags or NONE
  d.style = style
  d.shape = L.shapes[ih(h, 23) % #L.shapes + 1]
  if tags['roof:shape'] == 'flat' then d.shape = 'flat' end
  local lo, hi = style.pitch[1], style.pitch[2]
  d.pitch = lo + ih(h, 29) % (hi - lo + 1)
  d.eave = style.eave
  d.roof = L.roofs[ih(h, 13) % #L.roofs + 1]
  if d.shape == 'flat' then
    d.flat = 'roof_' .. (style.flat or 'h_flat_grey')
    local rim = style.rim or M.RIM
    d.rim = rim[1] + (rim[2] - rim[1]) * (ih(h, 31) % 8) / 7
  end
  if style.gable == 'wall' then d.gable = kind
  elseif style.gable == 'boards' then d.gable = 'gable' end
  d.plinth = L.plinths[ih(h, 19) % #L.plinths + 1]
  -- a plinth of the wall's own kind is no plinth
  if d.plinth == kind then d.plinth = false end
  d.chimney = ih(h, 43) % 100 < (style.chimney or 1) * 100
  d.cornice = style.cornice ~= false and d.shape ~= 'flat'
  d.porch = style.porch ~= false
  d.attic = style.attic ~= false
  d.noBalcony = style.cornice == false
  local wins, doors = kit and L.win or L.winOwn, kit and L.door or L.doorOwn
  if #wins > 0 then d.kitWin = wins[ih(h, 41) % #wins + 1] end
  if #doors > 0 then d.kitDoor = doors[ih(h, 42) % #doors + 1] end
  return d
end
M.RIM = {.25, .5}

return M
