-- Runtime geometry from compact source features. Nothing is written to disk, and no
-- service or executable is required. All coordinates remain in the source region's frame.
local M = {}
local EPS = 1e-8
local ROAD_LIFT = 0.10
local floor = math.floor
local NONE = {}
-- Weld keys: millimetres from the tile centre (|x|, |y| < 1048 m) and 1/1024 of a UV repeat
-- (|u|, |v| < 32768 repeats: region UVs are absolute, ~27000 at 80 km with a 3 m repeat).
local WELD, WELD2 = 2 ^ 20, 2 ^ 21
local UVQ, UVQ2 = 2 ^ 25, 2 ^ 26
-- Source grids at or under FINE_DEM.grid metres are a measured DEM: the ground follows it closer
-- to the roads (pullFull/pullZero for a 10 m LiDAR grid; a 25 m Terrarium grid keeps TUNE's).
local FINE_DEM = {grid = 12.5, pullFull = 3, pullZero = 15}
-- Road and ground shaping; the road quality bench (earthng/road_quality.py) overrides them
-- through options.tune. Metres.
local TUNE = {roadLift = ROAD_LIFT, groundDrop = .25, pullFull = 12, pullZero = 70, shoulder = 3, margin = .12,
  terrainStep = 25, sidewalk = 2, curb = .25, vergeCut = 1, vergeSink = 0, pressEven = 1, mitre = 2,
  simplifyXY = 0, simplifyZ = .02, fenceStep = 4, wallThick = .2, fenceThick = .08}
-- Covers that take a whole ground triangle over (lower rank wins where they overlap).
local CLAIM = {paved = 1, water = 2, glacier = 3, bare_rock = 4, scree = 5, beach = 6,
  wetland = 7, orchard = 8, vineyard = 9, farmland = 10, meadow = 11, heath = 12,
  scrub = 13, forest = 14, park = 15, bare_ground = 16}
-- Asphalt: the aerial street photo over 30 m, its fine detail through the detail maps
-- (fast_style.ROAD_M, DETAIL_M).
local COVER_SCALE = {ground = 24, forest = 24, park = 24, meadow = 24, orchard = 24,
  scrub = 24, heath = 24, glacier = 24, farmland = 12, vineyard = 12, bare_rock = 12,
  scree = 12, beach = 12, wetland = 12, bare_ground = 12,
  road = 30, road_major = 30, road_worn = 30, footway_asphalt = 30,
  -- the climate's open ground (biome.lua): photo sheets of fast_photo.GROUND_M
  desert = 24, dune = 24, steppe = 24, dry_grass = 24, tundra = 24, alpine = 24, snow = 24, snow_edge = 24}
local ABIN = 12.5      -- m: bins of asphalt pieces that sidewalks and verges are cut by
local SEA_ABOVE = 0.3   -- the sea plane over the DEM's flat sea surface (no z-fighting)
local ECA_TREE = '/levels/east_coast_usa/art/shapes/trees/'
local LAMP = '/art/shapes/objects/lamp1.dae'
local BUS_STOP = '/art/shapes/objects/s_busstop_jri.dae'
-- East Coast shapes have billboard LODs, so a crown stays up past the mesh pop.
-- The foliage-library oak is the last slot: it still draws if a level mesh is missing.
local TREES = {
  ECA_TREE .. 'trees_oak/tree_oak_sml_a.dae',
  ECA_TREE .. 'trees_oak/tree_oak_forest_a.dae',
  ECA_TREE .. 'trees_oak/tree_oak_large_b.dae',
  ECA_TREE .. 'trees_beech/tree_beech_small_c.dae',
  ECA_TREE .. 'trees_beech/tree_beech_forest_a.dae',
  ECA_TREE .. 'trees_aspen/tree_aspen_small_a.dae',
  ECA_TREE .. 'trees_aspen/tree_aspen_forest_b.dae',
  '/assets/meshes/foliage/trees_library/oak/tree_oak_sml_a.dae'}
-- A single OSM tree node (not the forest lattice). The first East Coast oak has a billboard.
local TREE = TREES[1]
local CONIFERS = {'/levels/italy/art/shapes/trees/trees_italy/scots_pine.dae',
  '/levels/italy/art/shapes/trees/trees_italy/scots_pine_filler.dae'}
local BUSHES = {
  ECA_TREE .. 'trees_beech/tree_beech_bush_b.dae',
  ECA_TREE .. 'trees_oak/tree_oak_bush_c.dae',
  '/assets/meshes/foliage/trees_library/beech/tree_beech_bush_a.dae',
  '/assets/meshes/foliage/trees_library/birch/tree_aspen_bush_a.dae'}
-- Stock tufts and stones from the player's install. GroundCover needs a TerrainBlock,
-- so near scatter uses these meshes. Nothing is copied into the mod.
local GRASS = {'/levels/east_coast_usa/art/shapes/groundcover/3d_grass_test/s_grass_green_short_01.dae',
  '/levels/east_coast_usa/art/shapes/groundcover/3d_grass_test/s_grass_green_short_02.dae',
  '/levels/east_coast_usa/art/shapes/groundcover/3d_grass_test/s_grass_green_short_03.dae',
  '/levels/east_coast_usa/art/shapes/groundcover/3d_grass_test/s_grass_green_long_01.dae',
  '/levels/east_coast_usa/art/shapes/groundcover/3d_grass_test/s_grass_green_long_02.dae'}
-- Native blade span and the lowest vertex, both in metres, from the position
-- arrays. A shared scale of 9 made the long meshes several metres tall.
local GRASS_MESH = {
  [GRASS[1]] = {span = 0.265, bottom = -0.038},
  [GRASS[2]] = {span = 0.258, bottom = -0.033},
  [GRASS[3]] = {span = 0.255, bottom = -0.019},
  [GRASS[4]] = {span = 0.514, bottom = -0.023},
  [GRASS[5]] = {span = 0.530, bottom = -0.046},
}
local ROCKS = {'/levels/east_coast_usa/art/shapes/rocks/eca_rock_small.dae',
  '/levels/east_coast_usa/art/shapes/rocks/eca_rock_small_2.dae',
  '/levels/east_coast_usa/art/shapes/rocks/eca_rock_small_3.dae',
  '/levels/east_coast_usa/art/shapes/rocks/eca_rock_small_4.dae',
  '/levels/east_coast_usa/art/shapes/rocks/eca_rock_medium_1.dae'}
-- Vegetation sets, one table (build() is near LuaJIT's 60 upvalues). Heights are the models'
-- own (first LOD): the forest variants stand 16-21 m and at a 1.55 scale made 30 m trees in
-- every Kyiv yard; towns and gardens take the 8-12 m small variants instead.
local ECA_GC = '/levels/east_coast_usa/art/shapes/groundcover/'
local VEG = {
  forest = TREES,
  town = {ECA_TREE .. 'trees_oak/tree_oak_sml_a.dae', ECA_TREE .. 'trees_oak/tree_oak_sml_b.dae',
    ECA_TREE .. 'trees_beech/tree_beech_small_b.dae', ECA_TREE .. 'trees_beech/tree_beech_small_c.dae',
    ECA_TREE .. 'trees_aspen/tree_aspen_small_a.dae', ECA_TREE .. 'trees_aspen/tree_aspen_small_c.dae',
    ECA_TREE .. 'trees_aspen/tree_aspen_large_a.dae', '/assets/meshes/foliage/trees_library/oak/tree_oak_sml_a.dae'},
  -- old park trees: the town's and the broad crowns
  park = {ECA_TREE .. 'trees_oak/tree_oak_sml_a.dae', ECA_TREE .. 'trees_oak/tree_oak_large_a.dae',
    ECA_TREE .. 'trees_oak/tree_oak_large_b.dae', ECA_TREE .. 'trees_beech/tree_beech_small_d.dae',
    ECA_TREE .. 'trees_beech/tree_beech_large_b.dae', ECA_TREE .. 'trees_aspen/tree_aspen_large_a.dae',
    '/assets/meshes/foliage/trees_library/oak/tree_oak_sml_a.dae'},
  -- village yards: small trees and big shrubs
  garden = {ECA_TREE .. 'trees_oak/tree_oak_sml_a.dae', ECA_TREE .. 'trees_beech/tree_beech_small_c.dae',
    ECA_TREE .. 'trees_aspen/tree_aspen_small_b.dae', ECA_TREE .. 'ECA_coast_bush/generibush.dae',
    ECA_TREE .. 'trees_oak/tree_oak_bush_c.dae', '/assets/meshes/foliage/trees_library/oak/tree_oak_sml_a.dae'},
  -- Kyiv's and the villages' poplars: one in ten crowns of a tree row
  poplar = {'/levels/automation_test_track/art/shapes/trees/trees_poplar/s_poplar_large_01.dae',
    '/levels/automation_test_track/art/shapes/trees/trees_poplar/s_poplar_large_02.dae',
    '/levels/automation_test_track/art/shapes/trees/trees_poplar/s_poplar_large_03.dae'},
  pine = CONIFERS,
  -- spruce and fir of the mountains: the Douglas fir stands in
  fir = {ECA_TREE .. 'trees_douglasfir/tree_douglasfir_large_a.dae', ECA_TREE .. 'trees_douglasfir/tree_douglasfir_large_c.dae',
    ECA_TREE .. 'trees_douglasfir/tree_douglasfir_small_a.dae', ECA_TREE .. 'trees_douglasfir/tree_douglasfir_small_c.dae'},
  bush = BUSHES,
  grass = GRASS, grassMesh = GRASS_MESH, rocks = ROCKS, tree = TREE,
  flowers = {ECA_GC .. 'Clover_closetop.dae', ECA_GC .. 'daisies_closetop.dae'},
  ferns = {ECA_GC .. 'lush_ferns_01_a.dae', ECA_GC .. 'lush_ferns_01_b.dae', ECA_GC .. 'lush_ferns_02_a.dae',
    ECA_GC .. 'lush_ferns_02_b.dae'},
  -- the material files their shapes need (world.lua loads them; a game without one keeps going)
  materials = {'/levels/east_coast_usa/art/shapes/trees/trees_douglasfir/main.materials.json',
    '/levels/east_coast_usa/art/shapes/trees/ECA_coast_bush/main.materials.json',
    '/levels/east_coast_usa/art/shapes/groundcover/main.materials.json',
    '/levels/automation_test_track/art/shapes/trees/trees_poplar/main.materials.json'},
}
-- Gardens: from this built-up share of the ground round a point, fully at gardenFrom +
-- gardenRamp (a village street reads .04-.14). Firs from firFrom m above the sea, fully at
-- firFrom + firRamp: the Polissia and steppe pinewoods stay pine, the Carpathians turn fir.
VEG.gardenFrom, VEG.gardenRamp, VEG.firFrom, VEG.firRamp = .004, .012, 450, 450

-- Plants and stones of other climates (biome.lua), all from the player's own levels: Utah's
-- junipers, sagebrush and boulders, Johnson Valley's desert shrubs, dry grass and rocks, West
-- Coast USA's live oaks, Monterey pines, eucalyptus, fan palms and chaparral, Jungle Rock
-- Island's coconut palms and rainforest, Italy's holm and cork oaks, olives, cypresses and
-- maritime pines. Heights are the models' own (first LOD, measured from the .dae).
local UT, JV, WCA = '/levels/Utah/art/shapes/', '/levels/johnson_valley/art/shapes/', '/levels/west_coast_usa/art/shapes/'
local JRI, ITA = '/levels/jungle_rock_island/art/shapes/', '/levels/italy/art/shapes/'
VEG.juniper = {UT .. 'trees/Juniper/Juniper_tree_01.dae', UT .. 'trees/Juniper/Juniper_tree_02.dae',   -- 4.5-7.5 m
  UT .. 'trees/Juniper/Juniper_tree_03.dae', UT .. 'trees/Juniper/Juniper_tree_04.dae', UT .. 'trees/Juniper/Juniper_ancient_01.dae'}
-- shrubs of the open desert and steppe, in the Forest (1.4-2.9 m) with the Spanish bayonet yucca
VEG.desertShrub = {UT .. 'trees/Juniper/Juniper_bush_small_dry_01.dae', UT .. 'trees/Juniper/Juniper_bush_small_dry_02.dae',
  UT .. 'trees/Juniper/Juniper_bush_small_01.dae', UT .. 'trees/Juniper/Juniper_bush_medium_01.dae',
  JV .. 'trees/deserttrees/deserttree_bush_medium.dae', JV .. 'trees/deserttrees/deserttree_bush_medium_dead.dae',
  WCA .. 'trees/spanishbayonet1.dae'}
-- the hot deserts' creosote and mesquite stand-ins, Spanish bayonet and a dry juniper now and then
VEG.desertShrubHot = {JV .. 'trees/deserttrees/deserttree_bush_medium.dae', JV .. 'trees/deserttrees/deserttree_bush_medium_dead.dae',
  JV .. 'trees/deserttrees/deserttree_bush_medium.dae', WCA .. 'trees/spanishbayonet1.dae', WCA .. 'trees/spanishbayonet2.dae',
  UT .. 'trees/Juniper/Juniper_bush_small_dry_02.dae'}
-- sagebrush, creosote, dead bushes and dry plants (0.4-1 m): groundcover, so detail.lua streams
-- them round the camera like the grass
VEG.desertPlants = {UT .. 'groundcover/s_gc_utah_grey_bush_01.dae', UT .. 'groundcover/s_gc_utah_grey_bush_02.dae',
  UT .. 'groundcover/s_gc_utah_grey_bush_03.dae', UT .. 'groundcover/s_gc_utah_grey_bush_04.dae',
  JV .. 'groundcover/s_gc_jv_dry_bush_01.dae', JV .. 'groundcover/s_gc_jv_dry_bush_03.dae',
  JV .. 'groundcover/s_gc_jv_dry_plant_01.dae', JV .. 'groundcover/s_gc_jv_dry_plant_02.dae',
  UT .. 'groundcover/s_gc_dead_bush_01.dae'}
VEG.dryTufts = {JV .. 'groundcover/s_gc_dry_grass_01.dae', JV .. 'groundcover/s_gc_dry_grass_02.dae',
  JV .. 'groundcover/s_gc_dry_grass_03.dae', JV .. 'groundcover/s_gc_dry_grass_04.dae'}
VEG.grassMesh[VEG.dryTufts[1]] = {span = .71, bottom = -.05}
VEG.grassMesh[VEG.dryTufts[2]] = {span = 1.06, bottom = -.17}
VEG.grassMesh[VEG.dryTufts[3]] = {span = .37, bottom = -.24}
VEG.grassMesh[VEG.dryTufts[4]] = {span = .37, bottom = -.24}
-- the last of a rock set is its big one (every fifth stone)
-- mostly Johnson Valley's tan granite; Utah's red sandstone one stone in eight (a valley of red
-- boulders read as Utah anywhere, the Owens Valley's granite too)
VEG.desertRocks = {JV .. 'rocks/s_rocks_desert_small_01.dae', JV .. 'rocks/s_rocks_desert_small_03.dae',
  JV .. 'rocks/s_rocks_desert_small_05.dae', JV .. 'rocks/s_rocks_desert_tiny_01.dae', JV .. 'rocks/s_rocks_desert_small_01.dae',
  JV .. 'rocks/s_rocks_desert_tiny_01.dae', UT .. 'rocks/utah_rock_flat_a.dae', JV .. 'rocks/s_rocks_desert_medium_03.dae'}
VEG.mountainRocks = {ROCKS[1], ROCKS[2], ROCKS[3], ROCKS[4], ITA .. 'rocks/italy_rockface_small_1.dae',
  ITA .. 'rocks/italy_rockface_tiny_1.dae', '/levels/east_coast_usa/art/shapes/rocks/eca_rock_medium_2.dae',
  ITA .. 'rocks/italy_rockface_boulder_1.dae'}
VEG.oakWest = {WCA .. 'trees/trees_oak/oak_a.dae', WCA .. 'trees/trees_oak/oak_b.dae',             -- 7-10 m
  WCA .. 'trees/trees_oak/oak_c.dae', WCA .. 'trees/trees_oak/oak_d.dae'}
VEG.pineWest = {WCA .. 'trees/trees_conifer/pine_radiata_small.dae', WCA .. 'trees/trees_conifer/pine_radiata_forest.dae',
  WCA .. 'trees/trees_conifer/pine_radiata_large.dae', WCA .. 'trees/trees_conifer/pine_radiata_weathered.dae'}
VEG.eucalyptus = {WCA .. 'trees/trees_eucalyptus/eucalyptus_double.dae', WCA .. 'trees/trees_eucalyptus/eucalyptus_tall.dae'}
VEG.chaparralWest = {WCA .. 'trees/trees_shrub/shrub_a.dae', WCA .. 'trees/trees_shrub/shrub_b.dae',   -- 3-5 m
  WCA .. 'trees/trees_shrub/shrub_c.dae', WCA .. 'trees/trees_shrub/shrub_d.dae', WCA .. 'trees/trees_shrub/shrub_e.dae',
  WCA .. 'trees/trees_shrub/shrub_f.dae', WCA .. 'trees/trees_shrub/shrub_g.dae', WCA .. 'trees/spanishbayonet1.dae'}
VEG.med = {ITA .. 'trees/trees_italy/holm_oak.dae', ITA .. 'trees/trees_italy/holm_oak_city_small.dae',
  ITA .. 'trees/trees_italy/cork_oak_medium.dae', ITA .. 'trees/trees_italy/cork_oak_large_1.dae',
  ITA .. 'trees/trees_italy/olive.dae', ITA .. 'trees/trees_italy/cypress_tree.dae'}
VEG.medPine = {ITA .. 'trees/trees_italy/maritime_pine.dae', ITA .. 'trees/trees_italy/maritime_pine_2.dae'}
VEG.chaparral = {ITA .. 'trees/trees_italy/holm_oak_bush.dae', ITA .. 'trees/trees_italy/cork_oak_bush_medium.dae',
  ITA .. 'trees/trees_italy/scraggly_bush.dae', ITA .. 'trees/trees_italy/maritime_pine_bush.dae',
  ITA .. 'trees/trees_italy/generibush.dae', ITA .. 'trees/trees_italy/fluffy_bush.dae'}
VEG.palmFan = {WCA .. 'trees/trees_palm/fanpalm_full.dae', WCA .. 'trees/trees_palm/fanpalm_short.dae',   -- 10-21 m
  WCA .. 'trees/trees_palm/fanpalm_skirt.dae', WCA .. 'trees/trees_palm/fanpalm_slim.dae',
  WCA .. 'trees/trees_palm/fanpalm_tall.dae', ITA .. 'trees/trees_italy/italy_palm_1.dae'}
VEG.palmCoco = {JRI .. 'trees/trees_palm/palm_small.dae', JRI .. 'trees/trees_palm/palm_short.dae',   -- 9-25 m
  JRI .. 'trees/trees_palm/palm_medium.dae', JRI .. 'trees/trees_palm/palm_tall.dae', JRI .. 'trees/trees_palm/palm_bend_sml.dae'}
VEG.tropical = {JRI .. 'trees/trees_tropical_1/tro_tree_1_huge.dae', JRI .. 'trees/trees_tropical_1/tro_tree_1_filler_02.dae',
  JRI .. 'trees/trees_tropical_2/tro_tree_2_medium.dae',
  JRI .. 'trees/trees_tropical_2/tro_tree_2_filler.dae', JRI .. 'trees/trees_tropical_2/tro_tree_2_tiny.dae'}
VEG.tropicalBush = {JRI .. 'trees/bush_tropical_1/tro_bush_huge.dae', JRI .. 'trees/bush_tropical_1/tro_bush_small.dae',
  JRI .. 'trees/bush_tropical_1/tro_tree_1_bush_large.dae', JRI .. 'trees/bush_tropical_2/tro_bush_2_small.dae',
  JRI .. 'trees/tropical_wide_leaves/tropical_plant_01_a.dae', JRI .. 'trees/tropical_wide_leaves/tropical_plant_02_a.dae',
  JRI .. 'trees/tropical_wide_leaves/tropical_plant_03_a.dae', JRI .. 'trees/trees_tropical_2/tro_tree_2_bush_huge.dae'}
-- dwarf shrubs of the tundra and the alpine belt; krummholz is the fir scaled down
VEG.tundraShrub = {UT .. 'trees/Juniper/Juniper_bush_small_01.dae', UT .. 'trees/Juniper/Juniper_bush_small_02.dae',
  ECA_TREE .. 'trees_douglasfir/tree_douglasfir_bush_a.dae', '/assets/meshes/foliage/bushes/generibush_small.dae'}
-- the material files of every level folder above (world.lua loads one when a tile first names it)
VEG.stock = {
  [UT .. 'trees/Juniper/'] = UT .. 'trees/Juniper/main.materials.json',
  [UT .. 'groundcover/'] = UT .. 'groundcover/main.materials.json', [UT .. 'rocks/'] = UT .. 'rocks/main.materials.json',
  [JV .. 'trees/deserttrees/'] = JV .. 'trees/deserttrees/main.materials.json',
  [JV .. 'groundcover/'] = JV .. 'groundcover/main.materials.json', [JV .. 'rocks/'] = JV .. 'rocks/main.materials.json',
  [WCA .. 'trees/trees_oak/'] = WCA .. 'trees/trees_oak/main.materials.json',
  [WCA .. 'trees/trees_conifer/'] = WCA .. 'trees/trees_conifer/main.materials.json',
  [WCA .. 'trees/trees_eucalyptus/'] = WCA .. 'trees/trees_eucalyptus/main.materials.json',
  [WCA .. 'trees/trees_shrub/'] = WCA .. 'trees/trees_shrub/main.materials.json',
  [WCA .. 'trees/trees_palm/'] = WCA .. 'trees/trees_palm/main.materials.json',
  [WCA .. 'trees/'] = WCA .. 'trees/main.materials.json',
  [JRI .. 'trees/trees_palm/'] = JRI .. 'trees/trees_palm/main.materials.json',
  [JRI .. 'trees/trees_tropical_1/'] = JRI .. 'trees/trees_tropical_1/main.materials.json',
  [JRI .. 'trees/trees_tropical_2/'] = JRI .. 'trees/trees_tropical_2/main.materials.json',
  [JRI .. 'trees/bush_tropical_1/'] = JRI .. 'trees/bush_tropical_1/main.materials.json',
  [JRI .. 'trees/bush_tropical_2/'] = JRI .. 'trees/bush_tropical_2/main.materials.json',
  [JRI .. 'trees/tropical_wide_leaves/'] = JRI .. 'trees/tropical_wide_leaves/main.materials.json',
  [ITA .. 'trees/trees_italy/'] = ITA .. 'trees/trees_italy/main.materials.json',
  [ITA .. 'rocks/'] = ITA .. 'rocks/main.materials.json',
}
-- A level's shared tree materials sit one folder up (JRI's leaves, West Coast's bark)
VEG.stockParent = {[JRI .. 'trees/'] = JRI .. 'trees/main.materials.json', [UT .. 'trees/'] = UT .. 'trees/main.materials.json',
  [WCA .. 'trees/'] = WCA .. 'trees/main.materials.json', [JV .. 'trees/'] = JV .. 'trees/main.materials.json'}
-- Materials a folder's shapes take from another folder (a material audit of every set against the
-- level files, 22.10): Jungle Rock's lianas, its second tropical tree's branches and leaves from the
-- first. Zanzibar's trees hung with orange NO MATERIAL ribbons without them. (The thin-leaf physics
-- material of Italy's generibush and the fir bush is the planet's own: fast_style.)
VEG.stockExtra = {
  [JRI .. 'trees/trees_tropical_1/'] = {JRI .. 'trees/vines_tropical/main.materials.json'},
  [JRI .. 'trees/trees_tropical_2/'] = {JRI .. 'trees/trees_tropical_1/main.materials.json', JRI .. 'trees/vines_tropical/main.materials.json'},
  [JRI .. 'trees/bush_tropical_2/'] = {JRI .. 'trees/vines_tropical/main.materials.json'},
}
-- Street furniture on the sidewalks of near tiles (experiment): stock props, solid items of the
-- level's Forest (world.lua), where a TSStatic cost ~8 times the spawn time and its collision
-- ~4 ms a thousand in every rebuild (out/overnight/props). curb: stands at the curb, not at the
-- sidewalk's outer edge; face: turned to the road. Weights per hundred. No stop or give-way
-- signs: a random one stood mid-block at way splits and faced anywhere; the OSM ones are drawn.
local WCO = WCA .. 'objects/'
local ECA_CLUTTER = '/levels/east_coast_usa/art/shapes/clutter/'
VEG.stock[WCO] = WCO .. 'main.materials.json'
-- East Coast clutter takes its wood from the buildings file. The dealership clutter file adds
-- eca_bld_cleanmetal, which the chalkboard names and the buildings file does not define.
VEG.stockExtra[ECA_CLUTTER] = {'/levels/east_coast_usa/art/shapes/buildings/main.materials.json',
  '/art/shapes/garage_and_dealership/Clutter/main.materials.json'}
-- fp: the model's plan bounds {x0, x1, y0, y1} in its own metres, measured from the installed DAE
-- geometry (out/runtime-review/asset-bounds.jsonl; the yellow bollard is unmeasured: a guess
-- on the large side). A face prop's long X runs along the path and its +Y faces the road.
VEG.props = {
  {WCO .. 'bollard_hoop_grey.dae', 18, curb = true, face = true, fp = {-.518, .518, -.175, .175}},
  {'/art/shapes/objects/bollard_yellow.dae', 8, curb = true, fp = {-.2, .2, -.2, .2}},
  {WCO .. 'garbage_bin_a.dae', 12, fp = {-.253, .253, -.235, .26}},
  {WCO .. 'garbage_bin_b.dae', 8, fp = {-.253, .253, -.235, .321}},
  {ECA_CLUTTER .. 'clutter_city_bench_wood.dae', 14, face = true, fp = {-1, 1, -.357, .205}},
  {WCO .. 'planterbox.dae', 10, fp = {-.46, .46, -.46, .46}},
  {ECA_CLUTTER .. 'clutter_city_bike_stand.dae', 8, face = true, fp = {-2.079, 2.079, -.321, .321}},
  {WCO .. 'hydrant1.dae', 8, curb = true, fp = {-.326, .326, -.377, .377}},
  {WCO .. 'postbox_blue.dae', 6, face = true, fp = {-.335, .249, -.32, .32}},
}
-- Furniture by place, not one street mix everywhere: the paths of a park and of a block's yard,
-- a square, the yards by the blocks of flats (benches at the entrances, a site of 1100 l
-- containers), wheelie bins and benches at the gates of houses, planters and bins before shops.
-- /art shapes take their materials from the game's global art folder. with: a second prop gap
-- metres along the path (a bin beside its bench); away: +Y turned from the path, not to it.
local GDC = '/art/shapes/garage_and_dealership/Clutter/'
local BENCH = {ECA_CLUTTER .. 'clutter_city_bench_wood.dae', 1, face = true, fp = {-1, 1, -.357, .205}}
local ROUND_BIN = {GDC .. 'clutter_city_bin_round.dae', 1, fp = {-.348, .348, -.348, .348}}
local SMALL_BIN = {GDC .. 'italy_clutter_metal_bin.DAE', 1, fp = {-.171, .171, -.171, .171}}
VEG.yard = {
  {BENCH[1], 35, face = true, fp = BENCH.fp, with = SMALL_BIN, gap = 1.75},
  {BENCH[1], 15, face = true, fp = BENCH.fp},
  {SMALL_BIN[1], 30, fp = SMALL_BIN.fp},
  {WCO .. 'garbage_bin_a.dae', 20, fp = {-.253, .253, -.235, .26}},
}
VEG.park = {
  {BENCH[1], 50, face = true, fp = BENCH.fp, with = ROUND_BIN, gap = 1.9},
  {BENCH[1], 20, face = true, fp = BENCH.fp},
  {ROUND_BIN[1], 30, fp = ROUND_BIN.fp},
}
VEG.square = {
  {WCO .. 'planterbox.dae', 25, fp = {-.46, .46, -.46, .46}},
  {BENCH[1], 25, face = true, fp = BENCH.fp, with = ROUND_BIN, gap = 1.9},
  {ROUND_BIN[1], 15, fp = ROUND_BIN.fp},
  {ECA_CLUTTER .. 'clutter_city_bollard_concrete.dae', 20, fp = {-.385, .385, -.385, .385}},
  {ECA_CLUTTER .. 'clutter_city_bike_stand.dae', 15, face = true, fp = {-2.079, 2.079, -.321, .321}},
}
-- a village street's sidewalk: now and then a bench or a bin, no planters, hoops or racks
VEG.village = {{'', 60, none = true}, {BENCH[1], 18, face = true, fp = BENCH.fp},
  {WCO .. 'garbage_bin_a.dae', 14, fp = {-.253, .253, -.235, .26}}, {WCO .. 'garbage_bin_b.dae', 8, fp = {-.253, .253, -.235, .321}}}
VEG.entrance = {{BENCH[1], 1, face = true, away = true, fp = BENCH.fp, with = SMALL_BIN, gap = 1.75}}
VEG.container = {{GDC .. 'italy_clutter_dumpster.DAE', 1, face = true, away = true, priority = 2.5,
  fp = {-.783, .783, -.414, .414}}}
VEG.gate = {
  {GDC .. 'italy_clutter_big_dustbin.DAE', 60, face = true, fp = {-.356, .347, -.367, .34}},
  {BENCH[1], 40, face = true, fp = BENCH.fp},
}
VEG.shopFront = {
  {WCO .. 'planterbox.dae', 35, fp = {-.46, .46, -.46, .46}},
  {WCO .. 'garbage_bin_a.dae', 25, fp = {-.253, .253, -.235, .26}},
  {ECA_CLUTTER .. 'clutter_city_bike_stand.dae', 20, face = true, fp = {-2.079, 2.079, -.321, .321}},
  {ROUND_BIN[1], 20, fp = ROUND_BIN.fp},
}
VEG.backyard = {{GDC .. 'ind_dumpster_full.DAE', 50, face = true, away = true, fp = {-1.516, 1.501, -.818, .818}},
  {GDC .. 'ind_dumpster_empty.DAE', 50, face = true, away = true, fp = {-1.516, 1.501, -.818, .818}}}
VEG.propSets = {'yard', 'park', 'square', 'village', 'entrance', 'container', 'gate', 'shopFront', 'backyard'}
-- Sidewalk mixes by look.block. america is VEG.props itself, so a test can still replace that
-- table before the first placement. europe: postsoviet, central, western, british, nordic,
-- east and southeast Asia. med: plaster countries. No mailboxes and no scattered signs.
local HOOP_GREY = {WCO .. 'bollard_hoop_grey.dae', 1, curb = true, face = true, fp = {-.518, .518, -.175, .175}}
local HOOP_RED = {WCO .. 'bollard_hoop_red.dae', 1, curb = true, face = true, fp = {-.518, .518, -.175, .175}}
local METAL_BIN = {GDC .. 'italy_clutter_metal_bin.DAE', 1, fp = {-.171, .171, -.171, .171}}
local TINY_BIN = {GDC .. 'italy_clutter_metal_bin_small.DAE', 1, fp = {-.1, .1, -.1, .1}}
local CONCRETE_BOLLARD = {ECA_CLUTTER .. 'clutter_city_bollard_concrete.dae', 1, curb = true, fp = {-.385, .385, -.385, .385}}
local STOOL = {ECA_CLUTTER .. 'clutter_city_wood_stool.dae', 1, fp = {-.294, .294, -.294, .294}}
local TABLE_SMALL = {ECA_CLUTTER .. 'clutter_city_wood_table_small.dae', 1, face = true, fp = {-.291, .291, -.435, .435}}
local TABLE = {ECA_CLUTTER .. 'clutter_city_wood_table.dae', 1, face = true, fp = {-.291, .291, -.785, .785}}
local BOARD = {ECA_CLUTTER .. 'clutter_city_chalkboard_sign.dae', 1, face = true, fp = {-.234, .234, -.363, .363}}
local function weighted(prop, weight, extra)
  local out = {prop[1], weight}
  for k, v in pairs(prop) do if k ~= 1 and k ~= 2 then out[k] = v end end
  for k, v in pairs(extra or NONE) do out[k] = v end
  return out
end
VEG.kits = {
  europe = {
    weighted(HOOP_GREY, 14), weighted(HOOP_RED, 10), weighted(METAL_BIN, 14), weighted(TINY_BIN, 10),
    weighted(BENCH, 16), weighted(CONCRETE_BOLLARD, 12),
    {WCO .. 'planterbox.dae', 8, fp = {-.46, .46, -.46, .46}},
    {ECA_CLUTTER .. 'clutter_city_bike_stand.dae', 8, face = true, fp = {-2.079, 2.079, -.321, .321}},
    {WCO .. 'hydrant1.dae', 8, curb = true, fp = {-.326, .326, -.377, .377}},
  },
  med = {
    {WCO .. 'planterbox.dae', 18, fp = {-.46, .46, -.46, .46}},
    weighted(BENCH, 16), weighted(METAL_BIN, 14), weighted(TINY_BIN, 12), weighted(CONCRETE_BOLLARD, 14),
    weighted(HOOP_GREY, 8),
    {ECA_CLUTTER .. 'clutter_city_bike_stand.dae', 8, face = true, fp = {-2.079, 2.079, -.321, .321}},
    {WCO .. 'hydrant1.dae', 6, curb = true, fp = {-.326, .326, -.377, .377}},
    weighted(ROUND_BIN, 4),
  },
}
local EUROPE = {
  yard = {
    weighted(BENCH, 30, {with = TINY_BIN, gap = 1.75}), weighted(BENCH, 12), weighted(TINY_BIN, 22),
    weighted(METAL_BIN, 18), weighted(TINY_BIN, 10), weighted(STOOL, 8),
  },
  park = {
    weighted(BENCH, 36, {with = ROUND_BIN, gap = 1.9}), weighted(BENCH, 14), weighted(ROUND_BIN, 16),
    weighted(TABLE_SMALL, 18), weighted(STOOL, 16),
  },
  square = {
    {WCO .. 'planterbox.dae', 18, fp = {-.46, .46, -.46, .46}},
    weighted(BENCH, 16, {with = ROUND_BIN, gap = 1.9}), weighted(ROUND_BIN, 10),
    {ECA_CLUTTER .. 'clutter_city_bollard_concrete.dae', 12, fp = {-.385, .385, -.385, .385}},
    {ECA_CLUTTER .. 'clutter_city_bike_stand.dae', 10, face = true, fp = {-2.079, 2.079, -.321, .321}},
    weighted(TABLE, 14), weighted(STOOL, 10), weighted(BOARD, 10),
  },
  village = {{'', 58, none = true}, weighted(BENCH, 18), weighted(METAL_BIN, 14), weighted(TINY_BIN, 10)},
  entrance = VEG.entrance, container = VEG.container,
  gate = {weighted({GDC .. 'italy_clutter_big_dustbin.DAE', 1, face = true, fp = {-.356, .347, -.367, .34}}, 45),
    weighted(BENCH, 30), weighted(METAL_BIN, 25)},
  shopFront = {
    {WCO .. 'planterbox.dae', 22, fp = {-.46, .46, -.46, .46}},
    weighted(METAL_BIN, 14), weighted(TINY_BIN, 12),
    {ECA_CLUTTER .. 'clutter_city_bike_stand.dae', 14, face = true, fp = {-2.079, 2.079, -.321, .321}},
    weighted(TABLE_SMALL, 16), weighted(BOARD, 14), weighted(STOOL, 8),
  },
  backyard = {
    {GDC .. 'ind_dumpster_full.DAE', 28, face = true, away = true, fp = {-1.516, 1.501, -.818, .818}},
    {GDC .. 'ind_dumpster_empty.DAE', 22, face = true, away = true, fp = {-1.516, 1.501, -.818, .818}},
    {GDC .. 'clutter_barrels_red.dae', 14, fp = {-.297, .297, -.297, .297}},
    {GDC .. 'clutter_barrels_white.dae', 10, fp = {-.297, .297, -.297, .297}},
    {'/art/shapes/objects/s_wood_crate_closed.dae', 10, face = true, away = true, fp = {-.785, .785, -1.502, 1.502}},
    {'/art/shapes/objects/s_wheelbarrow.dae', 8, face = true, away = true, fp = {-.936, .910, -.384, .391}},
    {GDC .. 'hr_plasticbarrier.DAE', 8, face = true, away = true, fp = {-.741, .741, -.27, .27}},
  },
}
VEG.kitSets = {europe = EUROPE, med = EUROPE}
-- what a building is to the furniture round it
local FLATS = {apartments = true, residential = true, dormitory = true}
local HOUSES = {house = true, detached = true, semidetached_house = true, bungalow = true, farm = true}
local SHOPS = {retail = true, commercial = true, supermarket = true, kiosk = true, mall = true}
VEG.used = {}
VEG.biomeSets = {juniper = true, desertShrub = true, desertShrubHot = true, desertPlants = true, dryTufts = true, desertRocks = true,
  mountainRocks = true, oakWest = true, pineWest = true, eucalyptus = true, chaparralWest = true, med = true,
  medPine = true, chaparral = true, palmFan = true, palmCoco = true, tropical = true, tropicalBush = true, tundraShrub = true}
-- A set, noted for the warm-up when it is another climate's
function VEG.use(name)
  if VEG.biomeSets[name] then VEG.used[name] = true end
  return VEG.have(name)
end
local okBiome, biomeModule = pcall(require, 'ge/extensions/e2r/biome')
VEG.biome = okBiome and type(biomeModule) == 'table' and biomeModule or nil
-- Every shape the generator may place, once, for world.lua's load-time warm-up: the temperate
-- sets always, another climate's sets once a tile has used them
function VEG.warm(...)
  local out, seen = {}, {}
  local function add(shape) if shape and not seen[shape] then seen[shape] = true; out[#out + 1] = shape end end
  for _, name in ipairs({'forest', 'town', 'park', 'garden', 'poplar', 'pine', 'fir', 'bush', 'flowers', 'ferns'}) do
    for _, shape in ipairs(VEG.have(name)) do add(shape) end
  end
  add(VEG.grass[1]); add(VEG.grass[4]); add(VEG.rocks[1]); add(VEG.rocks[5])
  local used = {}
  for name in pairs(VEG.used) do used[#used + 1] = name end
  table.sort(used)
  for _, name in ipairs(used) do
    local set = VEG.have(name)
    add(set[1]); add(set[#set])
  end
  for _, shape in ipairs({...}) do add(shape) end
  return out
end
-- The stock material files a manifest's shapes need, sorted.
function VEG.stockFor(items, shapes)
  local files, out = {}, {}
  local all = {}
  for _, item in ipairs(items) do all[#all + 1] = item.shape end
  for _, shape in ipairs(shapes or NONE) do all[#all + 1] = shape end
  for _, shape in ipairs(all) do
    if type(shape) == 'string' and shape:sub(1, 8) == '/levels/' then
      local folder = shape:match('^(.*/)[^/]*$')
      local file, parent = VEG.stock[folder], VEG.stockParent[folder and folder:match('^(.*/)[^/]*/$') or '']
      if file then files[file] = true end
      if parent and (file or VEG.stockExtra[folder]) then files[parent] = true end
      for _, extra in ipairs(VEG.stockExtra[folder] or NONE) do files[extra] = true end
    end
  end
  for file in pairs(files) do out[#out + 1] = file end
  table.sort(out)
  return out
end
-- A set without the shapes this game lacks (FS absent, as outside the game: all of them); an
-- empty set falls back to the forest's. Checked once per shape.
VEG.seen = {}
function VEG.have(name)
  local set = VEG[name]
  VEG.ok = VEG.ok or {}
  if VEG.ok[name] then return VEG.ok[name] end
  local out = {}
  for _, shape in ipairs(set) do
    local found = VEG.seen[shape]
    if found == nil then
      found = true
      if FS then
        local ok, exists = pcall(function() return FS:fileExists(shape) end)
        found = ok and exists and true or false
      end
      VEG.seen[shape] = found
    end
    if found then out[#out + 1] = shape end
  end
  if #out == 0 and name ~= 'forest' then out = VEG.have(VEG.fallback[name] or 'forest') end
  VEG.ok[name] = out
  return out
end
-- What a set stands in with in a game without its level: shrubs for shrubs, stones for stones
VEG.fallback = {desertShrub = 'bush', desertShrubHot = 'desertShrub', chaparral = 'bush', chaparralWest = 'chaparral', tundraShrub = 'bush',
  tropicalBush = 'bush', desertPlants = 'grass', dryTufts = 'grass', desertRocks = 'rocks', mountainRocks = 'rocks',
  oakWest = 'town', med = 'town', medPine = 'pine', pineWest = 'pine', juniper = 'pine', palmFan = 'palmCoco',
  palmCoco = 'town', tropical = 'forest', eucalyptus = 'town'}
-- Road decals (fast_style 'strip' kinds) carry their own UVs: u across, v along the road.
-- The worn line's paint is the middle two thirds of its texture, so a quad is markSpread
-- times the painted width. An edge decal is edgeWidth wide with the asphalt side at u = 0;
-- the road's edge sits at edgeAt, where both edge textures are past their ragged start (their
-- alpha test passes from u ~ .2), and at most edgeIn metres of it lie over the asphalt. The
-- curb is the top row of the trim sheet, two stones a repeat. One table: build() is near
-- LuaJIT's 60 upvalues.
local DECAL = {markRepeat = 6.4, markSpread = 1.45, markLift = .008,
  edgeWidth = 2, edgeAt = .38, edgeIn = .6, edgeRepeat = 8, edgeLift = {.004, .03},
  curbRepeat = 2, curbRow = {.005, .195},
  dirtRoads = {motorway = true, trunk = true, primary = true, secondary = true, tertiary = true}}
local BUILT_BIN = 50   -- m: bins of the built-up share (sidewalks, town groves)
-- Every map of the edge materials (fast_style.TEXTURES). A game without one of them (an older
-- BeamNG) gets the fallback materials from world.lua, and no edge strip is drawn.
local EDGE_MAPS = {}
for _, stem in ipairs({'vegetation/dirt_road_edge_grassy_d/t_road_edge_grass_02',
    'asphalt/m_asphalt_dirt_edge/t_asphalt_dirt_edge_02'}) do
  for _, suffix in ipairs({'_b.color', '_nm.normal', '_r.data', '_ao.data', '_o.data'}) do
    EDGE_MAPS[#EDGE_MAPS + 1] = '/assets/materials/decalroad/' .. stem .. suffix .. '.dds'
  end
end
-- The maps of the road covers (ROADS.covers): the Italy manhole sheet and the grid drain.
local COVER_MAPS = {}
for _, stem in ipairs({'baked_props/italy_ground_parts/t_manhole_01_decal', 'decalroad/detail/m_metal_grid_drain/t_metal_grid_drain'}) do
  for _, suffix in ipairs({'_b.color', '_nm.normal', '_o.data'}) do
    COVER_MAPS[#COVER_MAPS + 1] = '/assets/materials/' .. stem .. suffix .. '.dds'
  end
end
-- The asphalt patch strip (ROADS.covers patches): newer than the covers, checked on its own.
local PATCH_MAPS = {'/assets/materials/decalroad/asphalt/road_patches1/t_asphalt_patchstrip_b.color.dds',
  '/assets/materials/decalroad/asphalt/road_patches1/t_asphalt_patchstrip_o.data.dds'}
local patchesFound
local function patchesPresent()
  if patchesFound == nil then
    patchesFound = true
    if FS then
      for _, path in ipairs(PATCH_MAPS) do
        local ok, found = pcall(function() return FS:fileExists(path) end)
        if not (ok and found) then patchesFound = false; break end
      end
    end
  end
  return patchesFound
end
local coversFound
local function coversPresent()
  if coversFound == nil then
    coversFound = true
    if FS then
      for _, path in ipairs(COVER_MAPS) do
        local ok, found = pcall(function() return FS:fileExists(path) end)
        if not (ok and found) then coversFound = false; break end
      end
    end
  end
  return coversFound
end

local decalsFound
local function decalsPresent()
  if decalsFound == nil then
    decalsFound = true
    if FS then
      for _, path in ipairs(EDGE_MAPS) do
        local ok, found = pcall(function() return FS:fileExists(path) end)
        if not (ok and found) then decalsFound = false; break end
      end
    end
  end
  return decalsFound
end

local function hash(value)
  local h = 17
  for index = 1, #value do h = (h * 131 + value:byte(index)) % 2147483647 end
  return h
end

-- Numeric twin of hash() for scatter lattices: a tile walks tens of thousands of lattice
-- points, and building a string per point made garbage and most of the scatter time.
local HMOD = 2147483647
local function ihash(seed, a, b, c)
  local h = (seed * 1000003 + a) % HMOD
  h = (h * 1000003 + b) % HMOD
  if c then h = (h * 1000003 + c) % HMOD end
  h = (h * 48271 + 11) % HMOD
  return (h * 48271 + 7) % HMOD
end

-- An exact key of lattice point (gx, gy): namespace 0..3, lattice code 0..511.
local function latticeKey(ns, gx, gy, code)
  return (((gx + 524288) * 1048576 + (gy + 524288)) * 512 + code) * 4 + ns
end
local function keyHash(seed, key) return ihash(seed, key % HMOD, math.floor(key / HMOD)) end

local function lerp(a, b, t)
  local n = math.max(#a, #b)
  -- A per-corner normal sits at [6..8]. A nil UV in [4] or [5] would stop `#` before it,
  -- and the clipped border would fall back to a face normal that the neighbour does not share.
  if type(a[6]) == 'number' or type(b[6]) == 'number' or type(a[9]) == 'number' or type(b[9]) == 'number' then
    n = math.max(n, 9)
  end
  local out = {}
  for k = 1, n do out[k] = (a[k] or 0) + ((b[k] or 0) - (a[k] or 0)) * t end
  return out
end

local function cleanRing(ring)
  local out = {}
  for _, p in ipairs(ring or {}) do
    local q = out[#out]
    if not q or math.abs(q[1] - p[1]) + math.abs(q[2] - p[2]) > EPS then out[#out + 1] = p end
  end
  if #out > 1 and math.abs(out[1][1] - out[#out][1]) + math.abs(out[1][2] - out[#out][2]) < EPS then
    out[#out] = nil
  end
  return out
end

-- Horizontal slabs use even/odd filling across every ring. They triangulate concave
-- footprints and courtyard holes directly, without fragile bridges between duplicate vertices.
-- Edges (sorted by their low y) and vertex heights of rings, made once for a polygon that is
-- swept many times (row by row).
local function prepareRings(rings)
  local edges, vys, seen = {}, {}, {}
  for _, raw in ipairs(rings or {}) do
    local ring = cleanRing(raw)
    for k, a in ipairs(ring) do
      local b = ring[k % #ring + 1]
      if not seen[a[2]] then vys[#vys + 1], seen[a[2]] = a[2], true end
      if math.abs(a[2] - b[2]) > EPS then
        edges[#edges + 1] = {a, b, lo = math.min(a[2], b[2]), hi = math.max(a[2], b[2]), index = #edges + 1}
      end
    end
  end
  table.sort(vys)
  table.sort(edges, function(a, b) return a.lo == b.lo and a.index < b.index or a.lo < b.lo end)
  return {prepared = true, edges = edges, vys = vys}
end

-- quads: band trapezoids {a, b, c, d} instead of their two triangles (to be clipped further).
-- rings may be prepareRings' result.
local function triangulate(rings, pause, rect, quads)
  local prep = rings and rings.prepared and rings or prepareRings(rings)
  local ys, result = {}, {}
  if rect then ys = {rect[2], rect[4]} end
  for _, y in ipairs(prep.vys) do
    if not rect or (y > rect[2] and y < rect[4]) then ys[#ys + 1] = y end
  end
  local order = {}
  for _, edge in ipairs(prep.edges) do
    if rect and edge.lo >= rect[4] then break end
    if not rect or edge.hi > rect[2] then order[#order + 1] = edge end
  end
  table.sort(ys)
  -- A sweep: the edges crossing a band are those begun below its middle and not yet ended,
  -- kept in an active list instead of testing every edge of a big forest in every band.
  local function at(edge, y)
    local a, b = edge[1], edge[2]
    return a[1] + (b[1] - a[1]) * ((y - a[2]) / (b[2] - a[2]))
  end
  local function on(edge, y)
    return lerp(edge[1], edge[2], (y - edge[1][2]) / (edge[2][2] - edge[1][2]))
  end
  -- Band pieces wholly left or right of the tile would be clipped to nothing.
  local left, right = rect and rect[1] - EPS, rect and rect[3] + EPS
  local active, nextEdge = {}, 1
  local byX = function(a, b) return a.x == b.x and a.index < b.index or a.x < b.x end
  for n = 1, #ys - 1 do
    local low, high = ys[n], ys[n + 1]
    local mid = (low + high) * 0.5
    while nextEdge <= #order and order[nextEdge].lo <= mid do
      active[#active + 1] = order[nextEdge]
      nextEdge = nextEdge + 1
    end
    local cross, alive = {}, 0
    for k = 1, #active do
      local edge = active[k]
      if edge.hi > mid then
        alive = alive + 1
        active[alive] = edge
        cross[#cross + 1] = {x = at(edge, mid), edge = edge, index = edge.index}
      end
    end
    for k = #active, alive + 1, -1 do active[k] = nil end
    table.sort(cross, byX)
    for k = 1, #cross - 1, 2 do
      local e, f = cross[k].edge, cross[k + 1].edge
      local outside = false
      if rect then
        local xa, xb, xc, xd = at(e, low), at(f, low), at(f, high), at(e, high)
        outside = math.max(xa, xb, xc, xd) < left or math.min(xa, xb, xc, xd) > right
      end
      if not outside then
        local a, b, c, d = on(e, low), on(f, low), on(f, high), on(e, high)
        if quads then
          if b[1] - a[1] > EPS or c[1] - d[1] > EPS then result[#result + 1] = {a, b, c, d} end
        else
          if b[1] - a[1] > EPS then result[#result + 1] = {a, b, c} end
          if c[1] - d[1] > EPS then result[#result + 1] = {a, c, d} end
        end
      end
    end
    if pause then pause() end
  end
  return result
end

-- Clip in XY while interpolating elevation and optional UVs. Identical world-space
-- intersections on adjacent tiles prevent cracks and preserve road profiles at their border.
local function clip(poly, rect)
  -- Wholly inside (the usual case): every pass would copy it unchanged.
  local x0, y0, x1, y1 = rect[1] - EPS, rect[2] - EPS, rect[3] + EPS, rect[4] + EPS
  local inside = true
  for k = 1, #poly do
    local p = poly[k]
    local x, y = p[1], p[2]
    if x < x0 or x > x1 or y < y0 or y > y1 then inside = false; break end
  end
  if inside then return poly end
  local output = poly
  for side = 1, 4 do
    local axis = (side == 1 or side == 3) and 1 or 2
    local boundary, greater = rect[side], side < 3
    local input = output
    output = {}
    if #input == 0 then break end
    local a = input[#input]
    local inA = greater and a[axis] >= boundary - EPS or not greater and a[axis] <= boundary + EPS
    for _, b in ipairs(input) do
      local inB = greater and b[axis] >= boundary - EPS or not greater and b[axis] <= boundary + EPS
      if inA ~= inB then
        local t = (boundary - a[axis]) / (b[axis] - a[axis])
        local p = lerp(a, b, t)
        p[axis] = boundary
        output[#output + 1] = p
      end
      if inB then output[#output + 1] = b end
      a, inA = b, inB
    end
  end
  return output
end

-- The part of a polyline from distance a after its start to distance b before its end (z and
-- any other coordinates interpolated); {} when nothing is left.
local function trimLine(points, a, b)
  local dist = {0}
  for k = 2, #points do
    local p, q = points[k - 1], points[k]
    dist[k] = dist[k - 1] + math.sqrt((q[1] - p[1]) ^ 2 + (q[2] - p[2]) ^ 2)
  end
  local s0, s1 = a, dist[#points] - b
  if s1 - s0 < .05 then return {} end
  local function at(d)
    for k = 1, #points - 1 do
      if d <= dist[k + 1] or k == #points - 1 then
        return lerp(points[k], points[k + 1], (d - dist[k]) / math.max(EPS, dist[k + 1] - dist[k]))
      end
    end
  end
  local out = {at(s0)}
  for k = 2, #points - 1 do
    if dist[k] > s0 + 1e-3 and dist[k] < s1 - 1e-3 then out[#out + 1] = points[k] end
  end
  out[#out + 1] = at(s1)
  return out
end

-- Metres of centre-line rise and fall. Grade 0–1 stays on the surveyed profile so a worn
-- city street does not grow new vertices. Grade 2–5 samples every 8 m; the first and last
-- 6 m of each span stay put so a junction mouth still meets the fan.
local WEAR_AMP = {0, 0, .06, .10, .14, .18}
local function densifyWear(points, grade)
  if grade < 2 or #points < 2 then return points end
  local amp, step = WEAR_AMP[grade + 1] or 0, 8
  local out = {points[1]}
  local function push(p)
    local q = out[#out]
    if not q or math.abs(q[1] - p[1]) + math.abs(q[2] - p[2]) > 1e-3 then out[#out + 1] = p end
  end
  for k = 1, #points - 1 do
    local a, b = points[k], points[k + 1]
    local dx, dy = b[1] - a[1], b[2] - a[2]
    local dz = (b[3] or 0) - (a[3] or 0)
    local length = math.sqrt(dx * dx + dy * dy)
    local n = math.max(1, math.ceil(length / step))
    for s = 1, n - 1 do
      local t = s / n
      local along = math.min(t, 1 - t) * length
      local p = {a[1] + dx * t, a[2] + dy * t, (a[3] or 0) + dz * t}
      if along > 6 then
        local wobble = (hash('wear:' .. floor(p[1] + .5) .. ':' .. floor(p[2] + .5)) % 1000 / 1000 - .5) * 2 * amp
        p[3] = p[3] + wobble
      end
      push(p)
    end
    push(b)
  end
  return out
end

-- Douglas-Peucker in plan and height: a knot stays when dropping it moves the line more than
-- xy metres sideways or z metres up or down (the sources carry a profile knot every few metres).
local function simplify(points, xy, z)
  local n = #points
  if n <= 2 then return points end
  local keep = {[1] = true, [n] = true}
  local stack = {{1, n}}
  while #stack > 0 do
    local span = table.remove(stack)
    local i0, i1 = span[1], span[2]
    local a, b = points[i0], points[i1]
    local dx, dy = b[1] - a[1], b[2] - a[2]
    local len2 = dx * dx + dy * dy
    local worst, at = 0, nil
    for k = i0 + 1, i1 - 1 do
      local p = points[k]
      local t = len2 > 0 and math.max(0, math.min(1, ((p[1] - a[1]) * dx + (p[2] - a[2]) * dy) / len2)) or 0
      local ex, ey = a[1] + dx * t - p[1], a[2] + dy * t - p[2]
      local ez = (a[3] or 0) + ((b[3] or 0) - (a[3] or 0)) * t - (p[3] or 0)
      local e = math.max(math.sqrt(ex * ex + ey * ey) / xy, math.abs(ez) / z)
      if e > worst then worst, at = e, k end
    end
    if at and worst > 1 then
      keep[at] = true
      stack[#stack + 1], stack[#stack + 2] = {i0, at}, {at, i1}
    end
  end
  local out = {}
  for k = 1, n do if keep[k] then out[#out + 1] = points[k] end end
  return out
end

local function boundsTouch(a, b, margin)
  margin = margin or 0
  return a[1] <= b[3] + margin and a[3] >= b[1] - margin and a[2] <= b[4] + margin and a[4] >= b[2] - margin
end

local function ringBounds(rings)
  local bounds = {math.huge, math.huge, -math.huge, -math.huge}
  for _, ring in ipairs(rings or {}) do
    for _, p in ipairs(ring) do
      bounds[1], bounds[2] = math.min(bounds[1], p[1]), math.min(bounds[2], p[2])
      bounds[3], bounds[4] = math.max(bounds[3], p[1]), math.max(bounds[4], p[2])
    end
  end
  return bounds
end

local function ringsTouch(rings, rect)
  return boundsTouch(ringBounds(rings), rect)
end

-- Edges of a big ring by y band, so a point test reads only the edges that can cross its
-- row. The crossing rule is the plain one below, so the answer is the same. Forest rings of
-- thousands of vertices made point tests most of a tile's scatter time.
local bandIndex = setmetatable({}, {__mode = 'k'})
local function ringBands(ring)
  local index = bandIndex[ring]
  if index ~= nil then return index end
  local n = #ring
  if n < 24 then bandIndex[ring] = false; return false end
  local y0, y1 = math.huge, -math.huge
  for k = 1, n do
    local y = ring[k][2]
    if y < y0 then y0 = y end
    if y > y1 then y1 = y end
  end
  local count = math.max(1, math.min(4096, math.floor(n / 4)))
  local h = (y1 - y0) / count
  if not (h > 0) then bandIndex[ring] = false; return false end
  local bands, previous = {}, ring[n]
  for k = 1, n do
    local a, b = ring[k][2], previous[2]
    if a > b then a, b = b, a end
    for i = math.min(count - 1, math.floor((a - y0) / h)), math.min(count - 1, math.floor((b - y0) / h)) do
      local band = bands[i]
      if not band then band = {}; bands[i] = band end
      band[#band + 1] = k
    end
    previous = ring[k]
  end
  index = {y0 = y0, y1 = y1, h = h, count = count, bands = bands}
  bandIndex[ring] = index
  return index
end

local function inside(rings, x, y)
  local filled = false
  for _, ring in ipairs(rings or {}) do
    local index = ringBands(ring)
    if index then
      if y >= index.y0 and y <= index.y1 then
        local band = index.bands[math.min(index.count - 1, math.floor((y - index.y0) / index.h))]
        if band then
          local n = #ring
          for _, k in ipairs(band) do
            local p, previous = ring[k], ring[k == 1 and n or k - 1]
            if (p[2] > y) ~= (previous[2] > y)
              and x < (previous[1] - p[1]) * (y - p[2]) / (previous[2] - p[2]) + p[1] then filled = not filled end
          end
        end
      end
    else
      local previous = ring[#ring]
      for _, p in ipairs(ring) do
        if (p[2] > y) ~= (previous[2] > y)
          and x < (previous[1] - p[1]) * (y - p[2]) / (previous[2] - p[2]) + p[1] then filled = not filled end
        previous = p
      end
    end
  end
  return filled
end

-- Whether (x, y) lies closer than d to an edge of the rings (a crown against a wall).
local function nearEdge(rings, x, y, d)
  local d2 = d * d
  for _, ring in ipairs(rings or {}) do
    local previous = ring[#ring]
    for _, p in ipairs(ring) do
      local ax, ay = previous[1], previous[2]
      local dx, dy = p[1] - ax, p[2] - ay
      local len2 = dx * dx + dy * dy
      local t = len2 > EPS and math.max(0, math.min(1, ((x - ax) * dx + (y - ay) * dy) / len2)) or 0
      local ex, ey = ax + t * dx - x, ay + t * dy - y
      if ex * ex + ey * ey < d2 then return true end
      previous = p
    end
  end
  return false
end

local function number(value, default)
  return tonumber(tostring(value or ''):match('^%s*([%d%.%-]+)')) or default
end

-- 0 smooth asphalt, 1 worn asphalt, 2 gravel, 3 dirt, 4 broken, 5 overgrown.
-- Explicit surface wins over the highway class. tracktype and a bad smoothness
-- only make a minor road worse. Motorway–secondary ignore smoothness alone.
local function roadGrade(tags)
  tags = tags or {}
  local highway = (tags.highway or ''):gsub('_link$', '')
  local surface, grade = tags.surface, 0
  if surface == 'asphalt' or surface == 'concrete' or surface == 'paved' or surface == 'chipseal' then
    grade = 0
  elseif surface == 'cobblestone' or surface == 'sett' or surface == 'paving_stones' or surface == 'unhewn_cobblestone' then
    grade = 1
  elseif surface == 'gravel' or surface == 'fine_gravel' or surface == 'pebblestone' or surface == 'compacted' then
    grade = 2
  elseif surface == 'dirt' or surface == 'ground' or surface == 'earth' or surface == 'unpaved'
      or surface == 'mud' or surface == 'soil' or surface == 'sand' then
    grade = 3
  elseif surface == 'grass' or surface == 'grass_paver' then
    grade = 5
  elseif highway == 'track' then
    grade = 3
  end
  local track = tags.tracktype
  if track == 'grade1' then grade = math.max(grade, 1)
  elseif track == 'grade2' then grade = math.max(grade, 2)
  elseif track == 'grade3' then grade = math.max(grade, 3)
  elseif track == 'grade4' then grade = math.max(grade, 4)
  elseif track == 'grade5' then grade = 5 end
  local smooth = tags.smoothness
  local major = highway == 'motorway' or highway == 'trunk' or highway == 'primary' or highway == 'secondary'
  if not major and grade == 0 and (smooth == 'bad' or smooth == 'very_bad' or smooth == 'horrible'
      or smooth == 'very_horrible' or smooth == 'impassable') then
    grade = 1
  end
  if highway == 'track' and (smooth == 'horrible' or smooth == 'very_horrible') then grade = math.max(grade, 4) end
  if highway == 'track' and smooth == 'impassable' then grade = 5 end
  return grade
end

local ROAD_GRADE_MAT = {'road_worn', 'road_gravel', 'road_dirt', 'road_broken', 'road_track'}
local TRACK_WIDTH = {4.0, 3.8, 3.5, 3.2, 2.8, 2.5}

-- Near tiles: one material per ProceduralMesh. The engine pays ~2.3 ms the first frame it
-- draws each (object, material) pair, whatever its size (night-probe-10); pieces of 1500
-- triangles that mixed every material of their corner made ~110 pairs per city tile. A
-- material is now cut only at PIECE_TRIS: about tris / PIECE_TRIS + materials pairs a tile.
-- Far and horizon tiles (mixed): every ProceduralMesh is also a static collision instance,
-- ~40 us each in every be:reloadCollision whether anything can reach it or not, so a
-- distant tile packs MIXED_MATS materials per object (a far city tile: 28 -> 7 objects).
-- Not all of them in one: its first frame would draw ~25 new pairs (~57 ms) at once.
local PIECE_TRIS, MIXED_TRIS, MIXED_MATS = 2500, 4000, 4
local function collector(rect, key, layer, pause, mixed)
  local origin = {(rect[1] + rect[3]) * 0.5, (rect[2] + rect[4]) * 0.5, 0}
  local items, groups, used, operations, total = {}, {}, {}, 0, 0
  local function flushMaterial(material)
    local mesh = groups[material]
    if not mesh then return end
    mesh.vmap, mesh.nmap, mesh.umap, mesh.fmap = nil, nil, nil, nil
    local triangles = mesh.tris
    mesh.tris = nil
    items[#items + 1] = {kind = 'proc', name = 'e2rl_' .. key .. '_' .. layer .. '_' .. #items,
      pos = origin, meshes = {mesh}, triangles = triangles, mats = {material}, layer = layer}
    groups[material] = nil
  end
  local function flush()
    local mats = {}
    for material in pairs(groups) do mats[#mats + 1] = material end
    table.sort(mats)
    if not mixed then
      for _, material in ipairs(mats) do flushMaterial(material) end
      return
    end
    for first = 1, #mats, MIXED_MATS do
      local meshes, names, triangles = {}, {}, 0
      for k = first, math.min(#mats, first + MIXED_MATS - 1) do
        local mesh = groups[mats[k]]
        mesh.vmap, mesh.nmap, mesh.umap, mesh.fmap = nil, nil, nil, nil
        triangles = triangles + mesh.tris
        mesh.tris = nil
        meshes[#meshes + 1], names[#names + 1] = mesh, mats[k]
      end
      items[#items + 1] = {kind = 'proc', name = 'e2rl_' .. key .. '_' .. layer .. '_' .. #items,
        pos = origin, meshes = meshes, triangles = triangles, mats = names, layer = layer}
    end
    groups, total = {}, 0
  end
  -- Faces index positions, normals and UVs separately (BeamNG ProceduralMesh, like OBJ), so each
  -- is welded on its own: a ground node is one position for its six triangles, a flat road one
  -- normal for the whole piece, and a corner {v, n, u} seen again reuses its face table. The
  -- geometry is unchanged; the Lua tables (and the garbage the game's collector walks) are not.
  local function vertexIndex(mesh, p)
    local x, y, z = p[1] - origin[1], p[2] - origin[2], p[3] or 0
    local xq, yq = floor(x * 1000 + .5), floor(y * 1000 + .5)
    if xq < -WELD or xq >= WELD or yq < -WELD or yq >= WELD then
      local verts = mesh.verts
      verts[#verts + 1] = {x = x, y = y, z = z}
      return #verts - 1
    end
    -- vmap[key]: the index of the one vertex at this x, y, or {[zq] = index} once a wall puts a
    -- second height there (a table for every ground node was ~2 % of a city tile's garbage)
    local key = (xq + WELD) * WELD2 + yq + WELD
    local vmap, verts = mesh.vmap, mesh.verts
    local hit = vmap[key]
    local zq = floor(z * 1000 + .5)
    local zs
    if hit then
      if type(hit) == 'table' then
        zs = hit
        local index = zs[zq]
        if index then return index end
      else
        local zqHit = floor(verts[hit + 1].z * 1000 + .5)
        if zqHit == zq then return hit end
        zs = {[zqHit] = hit}
        vmap[key] = zs
      end
    end
    local index = #verts
    verts[index + 1] = {x = x, y = y, z = z}
    if zs then zs[zq] = index else vmap[key] = index end
    return index
  end
  local function normalIndex(mesh, nx, ny, nz)
    local key = floor((nx + 1) * 10000 + .5) * 1073741824 + floor((ny + 1) * 10000 + .5) * 32768 + floor((nz + 1) * 10000 + .5)
    local index = mesh.nmap[key]
    if not index then
      local normals = mesh.normals
      index = #normals
      normals[index + 1] = {x = nx, y = ny, z = nz}
      mesh.nmap[key] = index
    end
    return index
  end
  local function uvIndex(mesh, u, v)
    local uq, vq = floor(u * 1024 + .5), floor(v * 1024 + .5)
    local uvs = mesh.uvs
    if uq < -UVQ or uq >= UVQ or vq < -UVQ or vq >= UVQ then
      uvs[#uvs + 1] = {u = u, v = v}
      return #uvs - 1
    end
    local key = (uq + UVQ) * UVQ2 + vq + UVQ
    local index = mesh.umap[key]
    if not index then
      index = #uvs
      uvs[index + 1] = {u = u, v = v}
      mesh.umap[key] = index
    end
    return index
  end
  local function corner(mesh, p, n, scale, axis)
    local v = vertexIndex(mesh, p)
    local pu, pv = p[1], p[2]
    -- Dominant-axis box projection for rock; world-locked and independent of
    -- tile origin. It uses ordinary mesh UVs, no undocumented shader API.
    if axis == 'x' then pu, pv = p[2], p[3] or 0
    elseif axis == 'y' then pu, pv = p[1], p[3] or 0 end
    local u = uvIndex(mesh, p[4] or pu / scale, p[5] or pv / scale)
    local key = (v * 8192 + n) * 8192 + u
    local face = mesh.fmap[key]
    if not face then face = {v = v, n = n, u = u}; mesh.fmap[key] = face end
    local faces = mesh.faces
    faces[#faces + 1] = face
  end
  -- Ground passes a per-corner normal in p[6..8] (nx can be 0, so the type is the test).
  -- Walls, curbs and roads leave it unset and keep the face normal n. Not a closure inside
  -- triangle(): one per triangle was ~5 % of a city tile's garbage.
  local function cornerNormal(mesh, p, plain, n)
    if not plain and type(p[6]) == 'number' and type(p[7]) == 'number' and type(p[8]) == 'number' then
      return normalIndex(mesh, p[6], p[7], p[8])
    end
    return n
  end
  local scales = {}
  -- hooks.steep(kind, a, b, c): another material for a piece steeper than acos(hooks.nz), drawn
  -- flat shaded and box-mapped hooks.scale m a repeat, or false to leave it out (ROADS.wing)
  local hooks = {}
  local function triangle(kind, a, b, c, up)
    local a3, b3, c3 = a[3] or 0, b[3] or 0, c[3] or 0
    local ux, uy, uz = b[1] - a[1], b[2] - a[2], b3 - a3
    local vx, vy, vz = c[1] - a[1], c[2] - a[2], c3 - a3
    local nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    local len = math.sqrt(nx * nx + ny * ny + nz * nz)
    if len < EPS then return end
    if up and nz < 0 then b, c, nx, ny, nz = c, b, -nx, -ny, -nz end
    nx, ny, nz = nx / len, ny / len, nz / len
    if up == 'flat' then nx, ny, nz = 0, 0, 1 end
    local plain = false
    if hooks.steep and math.abs(nz) < hooks.nz then
      local swap = hooks.steep(kind, a, b, c)
      if swap == false then return end
      if swap then kind, plain = swap, true end
    end
    local material = 'e2rf_' .. kind
    if mixed and total >= mixed then flush() end
    local mesh = groups[material]
    if not mixed and mesh and mesh.tris >= PIECE_TRIS then flushMaterial(material); mesh = nil end
    if not mesh then
      mesh = {verts = {}, normals = {}, uvs = {}, faces = {}, material = material,
        vmap = {}, nmap = {}, umap = {}, fmap = {}, tris = 0}
      groups[material], used[material] = mesh, true
    end
    local scale = plain and hooks.scale or scales[kind]
    if not scale then
      scale = COVER_SCALE[kind] or 6
      if kind == 'sidewalk' or kind:find('wall_', 1, true) == 1 then scale = 3 end
      scales[kind] = scale
    end
    local n = normalIndex(mesh, nx, ny, nz)
    -- BeamNG ProceduralMesh expects clockwise face indices and zero-based indices.
    local axis
    if plain or kind == 'bare_rock' or kind == 'scree' then
      local ax, ay, az = math.abs(nx), math.abs(ny), math.abs(nz)
      if ax > az and ax >= ay then axis = 'x' elseif ay > az then axis = 'y' end
    end
    corner(mesh, a, cornerNormal(mesh, a, plain, n), scale, axis)
    corner(mesh, c, cornerNormal(mesh, c, plain, n), scale, axis)
    corner(mesh, b, cornerNormal(mesh, b, plain, n), scale, axis)
    mesh.tris, total, operations = mesh.tris + 1, total + 1, operations + 1
    if operations % 64 == 0 then pause() end
  end
  local function polygon(kind, polygon, up)
    local clipped = clip(polygon, rect)
    local first = clipped[1]
    for k = 2, #clipped - 1 do triangle(kind, first, clipped[k], clipped[k + 1], up) end
  end
  return {items = items, used = used, polygon = polygon, triangle = triangle, finish = flush, hooks = hooks}
end

-- Road semantics shared by the strips, junctions, markings, sidewalks and navgraph (one table:
-- build() is near LuaJIT's 60 upvalues).
local ROADS = {
  noOneway = {no = true, ['false'] = true, ['0'] = true, reversible = true, alternating = true},
  -- importance of a class; a link a little under its road
  rank = {motorway = 7, trunk = 6, primary = 5, secondary = 4, tertiary = 3, unclassified = 2,
    residential = 2, living_street = 1, service = 1, road = 1},
  -- classes with edge lines; tertiary only when wide enough for them (ROADS.marks)
  edged = {motorway = true, trunk = true, primary = true, secondary = true},
  -- classes with a centre line at all (an Estonian or Ukrainian residential street has none)
  centred = {motorway = true, trunk = true, primary = true, secondary = true, tertiary = true},
}
-- OSM's explicit or implied one-way, and whether the way runs against its node order.
function ROADS.oneway(tags)
  local one = tostring(tags.oneway or ''):lower()
  if one == '-1' then return true, true end
  if one == 'yes' or one == '1' or one == 'true' then return true, false end
  if ROADS.noOneway[one] then return false, false end
  return tags.highway == 'motorway' or tags.junction == 'roundabout' or tags.junction == 'circular', false
end
function ROADS.rankOf(tags)
  local highway = tags.highway or ''
  local base = highway:gsub('_link$', '')
  return (ROADS.rank[base] or 0) - (base ~= highway and .5 or 0)
end
function ROADS.ring(tags)
  return tags.junction == 'roundabout' or tags.junction == 'circular'
end
-- the pack's height solve's test (fast_profile.kind): any bridge value but no; a tunnel but no
-- or an arch through a house. A layer tag alone is a ground road there and here.
function ROADS.bridge(tags)
  return tags.bridge ~= nil and tags.bridge ~= 'no'
end
function ROADS.tunnel(tags)
  return tags.tunnel ~= nil and tags.tunnel ~= 'no' and tags.tunnel ~= 'building_passage'
end
-- a deck's concrete: its edge face reaches depth under the road, a parapet height over it.
-- Piers: a wall every `every` m of a bridge at least `min` long, `across` of the half width,
-- `thick` along the road, kept `clear` m off any road under it; abutments `thick` deep.
ROADS.deck = {depth = 1, parapet = .9, thick = .3, repeatU = 2.5,
  pier = {every = 25, min = 16, across = .85, thick = 1.6, clear = 1.5, gap = 1, sink = .5}}
-- A deck's ends: OSM draws many decks barely longer than the road under them, and on the 10 m
-- lattice the ground between the approach's bank and that road stood at 60-70 degrees, a wall
-- of grass by the abutment (Pärnu mnt over Järvevana tee, Tartu mnt at Pildiküla). Ground and
-- cover steeper than `steep` degrees within `reach` m of an abutment (a deck's end that is no
-- other deck's, past its half width) is drawn in the abutment's concrete, a wing wall; the
-- grass edge decals over it are left out. A viaduct's valley sides between its ends stay ground.
ROADS.wing = {steep = 55, reach = 15, material = 'fence_wall', decals = {edge_grass = true, edge_dirt = true},
  covers = {ground = true, forest = true, park = true, meadow = true, orchard = true, scrub = true, heath = true,
    farmland = true, vineyard = true, wetland = true, bare_ground = true, beach = true, desert = true, dune = true,
    steppe = true, dry_grass = true, tundra = true, alpine = true, snow = true, snow_edge = true}}
-- main roads' decks are girders deeper than a street's slab (fast_profile.CLEARANCE leaves
-- 4.5 m under the deepest)
function ROADS.deckDepth(tags)
  local rank = ROADS.rankOf(tags)
  return rank >= 4.5 and 1.5 or rank >= 2.5 and 1.2 or ROADS.deck.depth
end
-- Guard rail (OSM barrier=guard_rail, and 40 m of a main road's approach to a bridge): a
-- galvanised W-beam `beam` m tall whose top is `height` over the base, on posts every `posts` m.
-- profile: its folds ({off the centre line, up from the beam's foot}), `thick` m deep in all.
ROADS.rail = {height = .75, beam = .32, thick = .1, post = .14, step = 2, posts = 4, sink = .3,
  round = 6, ease = 2, profile = {{0, 0}, {.05, .04}, {.05, .09}, {.015, .155}, {.05, .22}, {.05, .27}, {0, .32}},
  approach = 40, offset = .5, rank = 4.5, material = 'clad_metal'}
-- A far tile draws the surface of every road of this class (ROADS.rankOf) or above, decoration
-- only: the far ring is ~130 tiles of the triangle budget, so service streets stay out. `clear`:
-- how far over the coarse far ground a road's surface is kept where that ground would hide it.
ROADS.far = {minRank = 2, clear = .25}
-- A quad turned to face (ox, oy, oz) by Newell's normal, through polygon(material, poly, up).
function ROADS.orient(polygon, material, poly, ox, oy, oz)
  local nx, ny, nz = 0, 0, 0
  for k = 1, #poly do
    local a, b = poly[k], poly[k % #poly + 1]
    nx, ny, nz = nx + (a[2] - b[2]) * (a[3] + b[3]), ny + (a[3] - b[3]) * (a[1] + b[1]), nz + (a[1] - b[1]) * (a[2] + b[2])
  end
  if nx * ox + ny * oy + nz * oz < 0 then
    local flipped = {}
    for k = #poly, 1, -1 do flipped[#flipped + 1] = poly[k] end
    poly = flipped
  end
  polygon(material, poly, false)
end

-- A box's four sides round (x, y): `across` half width along the normal of (tx, ty), `along`
-- half length along it, from zb up to zt. Its top and bottom are never seen.
function ROADS.box(face, material, x, y, tx, ty, across, along, zb, zt, repeatU)
  local nx, ny = -ty, tx
  local function c(sa, sb, z, u, v)
    return {x + nx * across * sa + tx * along * sb, y + ny * across * sa + ty * along * sb, z, u, v}
  end
  local h, wa, wb = (zt - zb) / repeatU, 2 * across / repeatU, 2 * along / repeatU
  for _, s in ipairs({1, -1}) do
    face({c(-1, s, zt, 0, 0), c(1, s, zt, wa, 0), c(1, s, zb, wa, h), c(-1, s, zb, 0, h)}, tx * s, ty * s, 0, material)
    face({c(s, -1, zt, 0, 0), c(s, 1, zt, wb, 0), c(s, 1, zb, wb, h), c(s, -1, zb, 0, h)}, nx * s, ny * s, 0, material)
  end
end

-- A guard rail along path ({x, y, z}, z its base, or ctx.ground(x, y)): a W-beam (rail.profile,
-- mirrored on its back) swept along the path with its corners rounded (up to rail.round m off
-- a vertex), its ground line eased over rail.ease samples and one welded normal per vertex, so
-- curves and the beam's folds shade smooth; a post every rail.posts metres on the `behind`
-- side (+1 left of the path's direction, -1 right). Only segments whose midpoint lies in
-- ctx.rect: the tile that owns them, so a rail across a tile edge is drawn once.
function ROADS.roundPath(path, radius)
  if #path < 3 or radius <= 0 then return path end
  local out = {path[1]}
  for k = 2, #path - 1 do
    local a, b, c = path[k - 1], path[k], path[k + 1]
    local l1 = math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2)
    local l2 = math.sqrt((c[1] - b[1]) ^ 2 + (c[2] - b[2]) ^ 2)
    local turn = l1 > EPS and l2 > EPS and ((b[1] - a[1]) * (c[1] - b[1]) + (b[2] - a[2]) * (c[2] - b[2])) / (l1 * l2) or 1
    if turn > .9994 then
      out[#out + 1] = b                     -- under 2 degrees: nothing to round
    else
      local d = math.min(radius, l1 / 2, l2 / 2)
      local p = lerp(b, a, d / l1)
      local q = lerp(b, c, d / l2)
      local n = turn > .9 and 2 or 4
      for i = 0, n do
        local t = i / n
        local u, v, w = (1 - t) * (1 - t), 2 * t * (1 - t), t * t
        out[#out + 1] = {u * p[1] + v * b[1] + w * q[1], u * p[2] + v * b[2] + w * q[2],
          u * (p[3] or 0) + v * (b[3] or 0) + w * (q[3] or 0)}
      end
    end
  end
  out[#out + 1] = path[#path]
  return out
end

function ROADS.guardRail(ctx, path)
  local rail, rect, face = ROADS.rail, ctx.rect, ctx.face
  local behind = ctx.behind or 1
  path = ROADS.roundPath(path, rail.round)
  local pts, along = {}, {}
  for k = 1, #path - 1 do
    local a, b = path[k], path[k + 1]
    local length = math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2)
    if length > EPS then
      local n = math.max(1, math.ceil(length / rail.step))
      for i = #pts == 0 and 0 or 1, n do
        local t = i / n
        local x, y = a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t
        -- ctx.ground: an OSM rail follows the drawn ground between its nodes too
        pts[#pts + 1] = {x, y, ctx.ground and ctx.ground(x, y) or a[3] + (b[3] - a[3]) * t}
        along[#pts] = #pts > 1 and along[#pts - 1] + length / n or 0
      end
    end
  end
  if #pts < 2 then return end
  -- a beam follows the ground's lie, not each ground triangle's kink
  if ctx.ground then
    for _ = 1, rail.ease do
      local z = {}
      for k = 2, #pts - 1 do z[k] = (pts[k - 1][3] + 2 * pts[k][3] + pts[k + 1][3]) / 4 end
      for k = 2, #pts - 1 do pts[k][3] = z[k] end
    end
  end
  -- per point: the mean tangent, and the mitre that keeps the beam's depth through a bend
  local frames = {}
  for k = 1, #pts do
    local a, b = pts[math.max(1, k - 1)], pts[math.min(#pts, k + 1)]
    local tx, ty = b[1] - a[1], b[2] - a[2]
    local l = math.max(EPS, math.sqrt(tx * tx + ty * ty))
    tx, ty = tx / l, ty / l
    local mitre = 1
    if k > 1 then
      local p = pts[k - 1]
      local sx, sy = pts[k][1] - p[1], pts[k][2] - p[2]
      local sl = math.max(EPS, math.sqrt(sx * sx + sy * sy))
      mitre = 1 / math.max(.5, (sx * tx + sy * ty) / sl)
    end
    frames[k] = {tx, ty, mitre}
  end
  -- the profile's vertex normals ({across, up}): each the mean of its two folds' normals
  local profile, low = rail.profile, rail.height - rail.beam
  local pn = {}
  for i = 1, #profile do
    local nx, nz = 0, 0
    for _, e in ipairs({{i - 1, i}, {i, i + 1}}) do
      local p, q = profile[e[1]], profile[e[2]]
      if p and q then
        local dn, dz = q[1] - p[1], q[2] - p[2]
        local l = math.max(EPS, math.sqrt(dn * dn + dz * dz))
        nx, nz = nx + dz / l, nz - dn / l
      end
    end
    local l = math.max(EPS, math.sqrt(nx * nx + nz * nz))
    pn[i] = {nx / l, nz / l}
  end
  local function vertex(k, i, side, u)
    local p, f, q = pts[k], frames[k], profile[i]
    local nx, ny = -f[2], f[1]
    local off = q[1] * side * f[3]
    local n = pn[i]
    return {p[1] + nx * off, p[2] + ny * off, p[3] + low + q[2], u, q[2] / rail.beam * .25,
      nx * n[1] * side, ny * n[1] * side, n[2]}
  end
  local post = 0
  for k = 1, #pts - 1 do
    local a, b = pts[k], pts[k + 1]
    local dx, dy = b[1] - a[1], b[2] - a[2]
    local l = math.max(EPS, math.sqrt(dx * dx + dy * dy))
    local tx, ty = dx / l, dy / l
    local mx, my = (a[1] + b[1]) / 2, (a[2] + b[2]) / 2
    local mine = mx >= rect[1] and mx < rect[3] and my >= rect[2] and my < rect[4]
    if mine then
      local u0, u1 = along[k] / 4, along[k + 1] / 4
      for _, side in ipairs({1, -1}) do
        for i = 1, #profile - 1 do
          local fn = pn[i][1] + pn[i + 1][1]
          local fz = pn[i][2] + pn[i + 1][2]
          face({vertex(k, i, side, u0), vertex(k + 1, i, side, u1), vertex(k + 1, i + 1, side, u1), vertex(k, i + 1, side, u0)},
            -ty * fn * side, tx * fn * side, fz, rail.material)
        end
      end
      -- the beam's ends: its two skins closed by the fold
      for _, e in ipairs({k == 1 and 1 or nil, k == #pts - 1 and k + 1 or nil}) do
        local s = e == 1 and -1 or 1
        for i = 1, #profile - 1 do
          local c = {vertex(e, i, 1, 0), vertex(e, i + 1, 1, 0), vertex(e, i + 1, -1, 0), vertex(e, i, -1, 0)}
          for _, v in ipairs(c) do v[6], v[7], v[8] = nil, nil, nil end
          face(c, tx * s, ty * s, 0, rail.material)
        end
      end
    end
    -- posts at 0, posts, 2 * posts, ... metres along the rail, each in the segment holding it
    while post <= along[k + 1] + EPS do
      if mine then
        local t = math.max(0, math.min(1, (post - along[k]) / math.max(EPS, along[k + 1] - along[k])))
        local off = (rail.thick / 2 + rail.post / 2) * behind
        ROADS.box(face, rail.material, a[1] + dx * t - ty * off, a[2] + dy * t + tx * off, tx, ty,
          rail.post / 2, rail.post / 2, a[3] + (b[3] - a[3]) * t - rail.sink, a[3] + (b[3] - a[3]) * t + rail.height - .02, 1)
      end
      post = post + rail.posts
    end
  end
end

-- OSM maps a bridge's railings and guard rails as plain barrier ways beside the deck; drawn on
-- the ground they cross whatever passes under it. The deck's parapets stand in for them: a
-- barrier's stretches within `reach` m of a bridge's edge and running with it are dropped.
-- A barrier across a carriageway (at least `across` off its line: a gore's rail meeting a
-- merging road at a shallow angle stays) is dropped there too: at grade it is a gate or a
-- mapping slip. A barrier under a bridge deck, at any angle and any height, is dropped under it:
-- a fence mapped under a low bridge would stand through the road, and the median and slip road
-- rails OSM runs on under an overpass read as rails going down under the bridge (Tallinna ringtee
-- at Jüri), crossing each other at the piers; they resume past the deck's edge. A deck at least
-- `clear` m over the ground there also keeps barriers `under` m off its edges and ends: the median
-- rails ran up to the deck's edge and stopped in front of its piers (a rail end across the median
-- at the pier), which still read as rails under the bridge. Tunnels pass under everything.
ROADS.onDeck = {reach = 3, parallel = .85, step = 2, cross = .3, across = .5, under = 8, clear = 3.5}
-- the runs of points ({x, y, ...}) off every bridge deck and carriageway in strips; nil when
-- none is near. ground(x, y): the drawn ground, for a deck's clearance (none: decks only).
function ROADS.offDecks(strips, points, ground)
  local od, decks = ROADS.onDeck, nil
  local x0, y0, x1, y1 = math.huge, math.huge, -math.huge, -math.huge
  for _, p in ipairs(points) do
    x0, y0, x1, y1 = math.min(x0, p[1]), math.min(y0, p[2]), math.max(x1, p[1]), math.max(y1, p[2])
  end
  for _, strip in ipairs(strips) do
    local bridge = ROADS.bridge(strip.tags)
    if bridge or ground and not ROADS.tunnel(strip.tags) then
      local ps = strip.points
      local r = math.max(bridge and strip.hw + od.under or 0, strip.hw + od.cross)
      for k = 1, #ps - 1 do
        local a, b = ps[k], ps[k + 1]
        if math.max(a[1], b[1]) + r > x0 and math.min(a[1], b[1]) - r < x1
          and math.max(a[2], b[2]) + r > y0 and math.min(a[2], b[2]) - r < y1 then
          decks = decks or {}
          -- {ax, ay, bx, by, along reach, across reach, az, bz, deck, x0, y0, x1, y1 (reach box), under reach}
          decks[#decks + 1] = {a[1], a[2], b[1], b[2], bridge and strip.hw + od.reach or 0, strip.hw + od.cross,
            a[3] or 0, b[3] or 0, bridge, math.min(a[1], b[1]) - r, math.min(a[2], b[2]) - r,
            math.max(a[1], b[1]) + r, math.max(a[2], b[2]) + r, bridge and strip.hw + od.under or 0}
        end
      end
    end
  end
  if not decks then return nil end
  local function onDeck(ax, ay, bx, by)
    local dx, dy = bx - ax, by - ay
    local l = math.sqrt(dx * dx + dy * dy)
    if l < EPS then return false end
    local mx, my = (ax + bx) / 2, (ay + by) / 2
    for _, s in ipairs(decks) do
      local sx, sy = s[3] - s[1], s[4] - s[2]
      local l2 = sx * sx + sy * sy
      if l2 > EPS and mx > s[10] and mx < s[12] and my > s[11] and my < s[13] then
        local cos = math.abs(dx * sx + dy * sy) / (l * math.sqrt(l2))
        local along = cos >= od.parallel
        local t = math.max(0, math.min(1, ((mx - s[1]) * sx + (my - s[2]) * sy) / l2))
        local d2 = (mx - s[1] - t * sx) ^ 2 + (my - s[2] - t * sy) ^ 2
        if along and d2 < s[5] * s[5] then return true end
        if d2 < s[6] * s[6] and (s[9] or ground and cos <= od.across) then return true end
        if s[9] and ground and d2 < s[14] * s[14] and s[7] + (s[8] - s[7]) * t - ground(mx, my) >= od.clear then return true end
      end
    end
    return false
  end
  local runs, run = {}, nil
  for k = 1, #points - 1 do
    local a, b = points[k], points[k + 1]
    local n = math.max(1, math.ceil(math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2) / od.step))
    for i = 1, n do
      local p = {a[1] + (b[1] - a[1]) * (i - 1) / n, a[2] + (b[2] - a[2]) * (i - 1) / n}
      local q = i == n and {b[1], b[2]} or {a[1] + (b[1] - a[1]) * i / n, a[2] + (b[2] - a[2]) * i / n}
      if onDeck(p[1], p[2], q[1], q[2]) then
        run = nil
      else
        if not run then run = {p}; runs[#runs + 1] = run end
        run[#run + 1] = q
      end
    end
  end
  return runs
end
-- OSM maps a guard rail where the imagery showed it, and some stand metres off the road the pack
-- draws (an old alignment, a ramp since rebuilt, a mapping offset): out in the grass they read
-- as junk (round the Assaku - Jüri overpass of Tallinna ringtee, 8 to 17 m off). A rail is kept
-- only within `far` m of a carriageway's edge (a deck's too, its sidewalk included), cut where
-- a sample `step` m along it leaves that; a stretch under `hole` m and within far + `slack`
-- between kept ones stays (a rail weaving round `far` m off is not chopped into stubs), and
-- pieces under `min` m go. The kept pieces keep the rail's own vertices, so its corners round
-- as before.
ROADS.byRoad = {far = 4, step = 2, min = 4, hole = 10, slack = 3}
function ROADS.besideRoads(strips, points, sidewalk)
  local br = ROADS.byRoad
  local x0, y0, x1, y1 = math.huge, math.huge, -math.huge, -math.huge
  for _, p in ipairs(points) do
    x0, y0, x1, y1 = math.min(x0, p[1]), math.min(y0, p[2]), math.max(x1, p[1]), math.max(y1, p[2])
  end
  local near = {}
  for _, strip in ipairs(strips) do
    if not ROADS.tunnel(strip.tags) then
      local walk = false
      for _, w in pairs(strip.walk or NONE) do
        if w[1] or w[-1] then walk = true; break end
      end
      local edge = strip.hw + (walk and sidewalk or 0)
      local r = edge + br.far + br.slack
      -- the road's own line: its strip stops at a junction's mouth
      local ps = strip.road and strip.road.points or strip.points
      for k = 1, #ps - 1 do
        local a, b = ps[k], ps[k + 1]
        if math.max(a[1], b[1]) + r > x0 and math.min(a[1], b[1]) - r < x1
          and math.max(a[2], b[2]) + r > y0 and math.min(a[2], b[2]) - r < y1 then
          near[#near + 1] = {a[1], a[2], b[1], b[2], edge}
        end
      end
    end
  end
  -- metres outside the nearest carriageway's edge
  local function gap(x, y)
    local best = math.huge
    for _, s in ipairs(near) do
      local dx, dy = s[3] - s[1], s[4] - s[2]
      local l2 = dx * dx + dy * dy
      local t = l2 > EPS and math.max(0, math.min(1, ((x - s[1]) * dx + (y - s[2]) * dy) / l2)) or 0
      local d = math.sqrt((x - s[1] - t * dx) ^ 2 + (y - s[2] - t * dy) ^ 2) - s[5]
      if d < best then best = d end
    end
    return best
  end
  local samples = {}
  for k = 1, #points - 1 do
    local a, b = points[k], points[k + 1]
    local n = math.max(1, math.ceil(math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2) / br.step))
    for i = k == 1 and 0 or 1, n do
      local p = i == 0 and a or i == n and b or {a[1] + (b[1] - a[1]) * i / n, a[2] + (b[2] - a[2]) * i / n}
      local g = gap(p[1], p[2])
      samples[#samples + 1] = {p = p, gap = g, vertex = i == 0 or i == n, keep = g <= br.far}
    end
  end
  local i = 1
  while i <= #samples do
    if samples[i].keep then
      i = i + 1
    else
      local j, worst, length = i, 0, 0
      while j <= #samples and not samples[j].keep do worst = math.max(worst, samples[j].gap); j = j + 1 end
      if i > 1 and j <= #samples and worst <= br.far + br.slack then
        for m = i, j do
          local p, q = samples[m - 1].p, samples[m].p
          length = length + math.sqrt((q[1] - p[1]) ^ 2 + (q[2] - p[2]) ^ 2)
        end
        if length <= br.hole then
          for m = i, j - 1 do samples[m].keep = true end
        end
      end
      i = j
    end
  end
  local runs, run, last = {}, nil, nil
  local function close()
    if run and last ~= run[#run] then run[#run + 1] = last end
    if run then
      local length = 0
      for k = 2, #run do length = length + math.sqrt((run[k][1] - run[k - 1][1]) ^ 2 + (run[k][2] - run[k - 1][2]) ^ 2) end
      if length >= br.min then runs[#runs + 1] = run end
    end
    run = nil
  end
  for _, s in ipairs(samples) do
    if s.keep then
      if not run then run = {s.p} elseif s.vertex then run[#run + 1] = s.p end
      last = s.p
    else
      close()
    end
  end
  close()
  return runs
end

-- Under the decks: a wall pier every deck.pier.every metres of a bridge (none where a road
-- passes under it or the ground is within deck.pier.gap of the soffit), an abutment under each
-- end that is no other bridge's end, and guard rails on the first rail.approach metres of a
-- main road's plain approach to a bridge, both sides (none on a way tagged e2r:rails=register:
-- the road register's rails are its own barrier=guard_rail ways). ctx: strips, rect, ground(x, y), face,
-- pause, sidewalk (m).
function ROADS.substructure(ctx)
  local deck, pier, rail, rect, ground, face = ROADS.deck, ROADS.deck.pier, ROADS.rail, ctx.rect, ctx.ground, ctx.face
  local function owns(x, y) return x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4] end
  local bridgeEnds, ends = {}, {}
  for _, strip in ipairs(ctx.strips) do
    local nodes = strip.road and strip.road.nodes or NONE
    for e = 1, 2 do
      local id = nodes[e] ~= nil and tostring(nodes[e])
      if id then
        ends[id] = (ends[id] or 0) + 1
        if ROADS.bridge(strip.tags) then bridgeEnds[id] = (bridgeEnds[id] or 0) + 1 end
      end
    end
  end
  if not next(bridgeEnds) then return end
  local below
  local function roadUnder(x, y)
    if not below then
      below = {}
      for _, other in ipairs(ctx.strips) do
        if not ROADS.bridge(other.tags) then
          local ps = other.points
          for k = 1, #ps - 1 do
            below[#below + 1] = {ps[k][1], ps[k][2], ps[k + 1][1], ps[k + 1][2], other.hw + pier.clear}
          end
        end
      end
    end
    for _, s in ipairs(below) do
      local ax, ay, bx, by, r = s[1], s[2], s[3], s[4], s[5]
      if x > math.min(ax, bx) - r and x < math.max(ax, bx) + r and y > math.min(ay, by) - r and y < math.max(ay, by) + r then
        local dx, dy = bx - ax, by - ay
        local l2 = dx * dx + dy * dy
        local t = l2 > EPS and math.max(0, math.min(1, ((x - ax) * dx + (y - ay) * dy) / l2)) or 0
        if (x - ax - t * dx) ^ 2 + (y - ay - t * dy) ^ 2 < r * r then return true end
      end
    end
    return false
  end
  for _, strip in ipairs(ctx.strips) do
    local points, dist, edge, hw = strip.points, strip.dist, strip.edge, strip.hw
    local n = #points
    local nodes = strip.road and strip.road.nodes or NONE
    local function wide(k, sign)
      local walk = strip.walk[math.max(1, math.min(k, n - 1))] or NONE
      if sign then return hw + (walk[sign] and ctx.sidewalk or 0) end
      return hw + ((walk[1] or walk[-1]) and ctx.sidewalk or 0)
    end
    if ROADS.bridge(strip.tags) and n >= 2 and not (strip.road and strip.road.deckGroup) then
      local depth = ROADS.deckDepth(strip.tags)
      -- centre, tangent and soffit height at s metres along the strip
      local function at(s)
        local k = 1
        while k < n - 1 and dist[k + 1] < s do k = k + 1 end
        local t = math.max(0, math.min(1, (s - dist[k]) / math.max(EPS, dist[k + 1] - dist[k])))
        local a, b = edge(k, 0, -depth), edge(k + 1, 0, -depth)
        local dx, dy = b[1] - a[1], b[2] - a[2]
        local l = math.max(EPS, math.sqrt(dx * dx + dy * dy))
        return a[1] + dx * t, a[2] + dy * t, a[3] + (b[3] - a[3]) * t, dx / l, dy / l, k
      end
      local first, length = dist[1], dist[n] - dist[1]
      if length >= pier.min then
        local count = math.max(2, math.ceil(length / pier.every))
        for i = 1, count - 1 do
          local x, y, z, tx, ty, k = at(first + length * i / count)
          if owns(x, y) then
            local across = wide(k) * pier.across
            local zg = ground(x, y)
            local clear = z - zg >= pier.gap
            for _, f in ipairs({-1, -.5, 0, .5, 1}) do
              if clear and roadUnder(x - ty * across * f, y + tx * across * f) then clear = false end
            end
            if clear then
              ROADS.box(face, 'fence_wall', x, y, tx, ty, across, pier.thick / 2, zg - pier.sink, z + .05, deck.repeatU)
            end
          end
        end
      end
      for e = 1, 2 do
        local id = nodes[e] ~= nil and tostring(nodes[e])
        if id and bridgeEnds[id] == 1 then
          local x, y, z, tx, ty, k = at(e == 1 and first + pier.thick / 2 or dist[n] - pier.thick / 2)
          local zg = ground(x, y)
          if owns(x, y) and z - zg > .1 then
            ROADS.box(face, 'fence_wall', x, y, tx, ty, wide(k) + deck.thick, pier.thick / 2, zg - pier.sink, z + .05, deck.repeatU)
          end
        end
      end
    elseif not ROADS.tunnel(strip.tags) and ROADS.rankOf(strip.tags) >= rail.rank and n >= 2
      and strip.tags['e2r:rails'] ~= 'register' then
      for e = 1, 2 do
        local id = nodes[e] ~= nil and tostring(nodes[e])
        -- only a plain approach: the bridge and this road meet there and nothing else does
        if id and bridgeEnds[id] == 1 and ends[id] == 2 then
          local from = e == 1 and dist[1] or dist[n]
          local k0, k1, step = e == 1 and 1 or n, e == 1 and n or 1, e == 1 and 1 or -1
          for _, sign in ipairs({1, -1}) do
            local path = {}
            for k = k0, k1, step do
              local offset = (wide(k, sign) + rail.offset) * sign
              local gone = math.abs(dist[k] - from)
              if gone <= rail.approach then
                path[#path + 1] = edge(k, offset, 0)
              else
                local prev = k - step
                local t = (rail.approach - math.abs(dist[prev] - from)) / math.max(EPS, math.abs(dist[k] - dist[prev]))
                local a, b = edge(prev, offset, 0), edge(k, offset, 0)
                path[#path + 1] = {a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t, a[3] + (b[3] - a[3]) * t}
                break
              end
            end
            -- the path runs away from the bridge: walking from the start end the road's left
            -- (+ side) is the path's left; from the far end it is the path's right. Posts stand
            -- away from the road.
            local behind = sign * step
            if #path >= 2 then ROADS.guardRail({rect = rect, face = face, behind = behind}, path) end
          end
        end
      end
    end
    if ctx.pause then ctx.pause() end
  end
end
-- One slab for a deckGroup: the carriageways stay separate ways, but the mesh is a single
-- soffit, a single asphalt quad and parapets only on the outer edges. Piers stand on the
-- united centre line. A mate is included only where it actually runs beside the host.
function ROADS.unitedDecks(ctx)
  local deck, rect, lift = ROADS.deck, ctx.rect, ctx.lift or 0
  local function owns(x, y) return x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4] end
  local groups = {}
  for _, strip in ipairs(ctx.strips) do
    local id = strip.road and strip.road.deckGroup
    if id and ROADS.bridge(strip.tags) and strip.edge and #strip.points >= 2 then
      local list = groups[id]
      if not list then list = {}; groups[id] = list end
      list[#list + 1] = strip
    end
  end
  local function project(strip, x, y)
    local pts, best, bestD = strip.points
    for i = 2, #pts do
      local a, b = pts[i - 1], pts[i]
      local dx, dy = b[1] - a[1], b[2] - a[2]
      local l2 = dx * dx + dy * dy
      if l2 > EPS then
        local t = ((x - a[1]) * dx + (y - a[2]) * dy) / l2
        if t >= 0 and t <= 1 then
          local qx, qy = a[1] + dx * t, a[2] + dy * t
          local ddx, ddy = x - qx, y - qy
          local d2 = ddx * ddx + ddy * ddy
          if not bestD or d2 < bestD then
            bestD = d2
            best = {qx, qy, (a[3] or 0) + ((b[3] or 0) - (a[3] or 0)) * t, math.sqrt(d2), i - 1,
              dx, dy}
          end
        end
      end
    end
    return best
  end
  local function atDist(strip, s)
    local pts, dist = strip.points, strip.dist
    local n = #pts
    local k = 1
    while k < n - 1 and dist[k + 1] < s do k = k + 1 end
    local span = math.max(EPS, dist[k + 1] - dist[k])
    local t = math.max(0, math.min(1, (s - dist[k]) / span))
    local a, b = pts[k], pts[k + 1]
    local dx, dy = b[1] - a[1], b[2] - a[2]
    local l = math.max(EPS, math.sqrt(dx * dx + dy * dy))
    return a[1] + dx * t, a[2] + dy * t, (a[3] or 0) + ((b[3] or 0) - (a[3] or 0)) * t, dx / l, dy / l, k
  end
  local function sideWalk(strip, k, sign)
    local walk = strip.walk and strip.walk[k]
    return walk and walk[sign] and ctx.sidewalk or 0
  end
  for _, members in pairs(groups) do
    if #members >= 2 then
      local host = members[1]
      local group = {members = {}}
      for _, strip in ipairs(members) do group.members[strip] = true end
      for _, strip in ipairs(members) do
        if strip.road and strip.road.deckHost then host = strip end
      end
      local depth = 0
      for _, strip in ipairs(members) do depth = math.max(depth, ROADS.deckDepth(strip.tags)) end
      local function frame(s)
        local x, y, z, tx, ty, k = atDist(host, s)
        local nx, ny = -ty, tx
        local left = host.hw + sideWalk(host, k, 1)
        local right = -(host.hw + sideWalk(host, k, -1))
        local top = z
        for _, mate in ipairs(members) do
          if mate ~= host then
            local hit = project(mate, x, y)
            if hit and hit[4] - host.hw - mate.hw <= 12 and math.abs(z - hit[3]) < 1.5 then
              local off = (hit[1] - x) * nx + (hit[2] - y) * ny
              local mk = hit[5]
              local walkL, walkR = sideWalk(mate, mk, 1), sideWalk(mate, mk, -1)
              local same = hit[6] * tx + hit[7] * ty >= 0
              if not same then walkL, walkR = walkR, walkL end
              left = math.max(left, off + mate.hw + walkL)
              right = math.min(right, off - mate.hw - walkR)
              if hit[3] > top then top = hit[3] end
            end
          end
        end
        return {x = x, y = y, z = top, tx = tx, ty = ty, nx = nx, ny = ny, left = left, right = right, s = s}
      end
      local length = host.dist[#host.dist] - host.dist[1]
      local samples, s = {}, host.dist[1]
      samples[1] = frame(s)
      while s < host.dist[#host.dist] - .01 do
        s = math.min(host.dist[#host.dist], s + 8)
        samples[#samples + 1] = frame(s)
      end
      local function corner(sample, offset, dz, u, v)
        return {sample.x + sample.nx * offset, sample.y + sample.ny * offset, sample.z + lift + dz, u, v}
      end
      for i = 1, #samples - 1 do
        local a, b = samples[i], samples[i + 1]
        if a.left - a.right > .2 and b.left - b.right > .2 then
          local u0, u1 = a.s / deck.repeatU, b.s / deck.repeatU
          local quad = {corner(a, a.left, 0), corner(a, a.right, 0), corner(b, b.right, 0), corner(b, b.left, 0)}
          if boundsTouch(rect, ringBounds({quad}), 0) then
            ctx.roads.polygon(host.material, quad, 'flat')
            ctx.face({corner(a, a.left, -depth, u0, 0), corner(b, b.left, -depth, u1, 0),
              corner(b, b.right, -depth, u1, (a.left - a.right) / deck.repeatU),
              corner(a, a.right, -depth, u0, (a.left - a.right) / deck.repeatU)}, 0, 0, -1)
            for _, side in ipairs({{a.left, b.left, 1}, {a.right, b.right, -1}}) do
              local edgeA, edgeB, outward = side[1], side[2], side[3]
              local outerA, outerB = edgeA + deck.thick * outward, edgeB + deck.thick * outward
              local top, low = deck.parapet, -depth
              local ox, oy = a.nx * outward, a.ny * outward
              -- in 2 m pieces, none over a slip road leaving the deck (a parapet across its mouth)
              local pieces = 4
              local function line(f, offA, offB, dz, v)
                local p, q = corner(a, offA, dz, u0, v), corner(b, offB, dz, u1, v)
                return {p[1] + (q[1] - p[1]) * f, p[2] + (q[2] - p[2]) * f, p[3] + (q[3] - p[3]) * f, p[4] + (q[4] - p[4]) * f, v}
              end
              local free = {}
              for s = 1, pieces do free[s] = not (ctx.onOther and ctx.onOther(group, line((s - .5) / pieces, edgeA, edgeB, 0, 0))) end
              local s = 1
              while s <= pieces do
                if free[s] then
                  local e = s
                  while e < pieces and free[e + 1] do e = e + 1 end
                  local f0, f1 = (s - 1) / pieces, e / pieces
                  ctx.face({line(f0, outerA, outerB, top, 0), line(f1, outerA, outerB, top, 0),
                    line(f1, outerA, outerB, low, (top - low) / deck.repeatU),
                    line(f0, outerA, outerB, low, (top - low) / deck.repeatU)}, ox, oy, 0)
                  ctx.face({line(f0, edgeA, edgeB, top, 0), line(f1, edgeA, edgeB, top, 0),
                    line(f1, edgeA, edgeB, 0, top / deck.repeatU),
                    line(f0, edgeA, edgeB, 0, top / deck.repeatU)}, -ox, -oy, 0)
                  ctx.face({line(f0, edgeA, edgeB, top, 0), line(f1, edgeA, edgeB, top, 0),
                    line(f1, outerA, outerB, top, deck.thick / deck.repeatU),
                    line(f0, outerA, outerB, top, deck.thick / deck.repeatU)}, 0, 0, 1)
                  s = e + 1
                else
                  s = s + 1
                end
              end
            end
          end
        end
      end
      local below, pier = nil, deck.pier
      local function roadUnder(x, y)
        if not below then
          below = {}
          for _, other in ipairs(ctx.strips) do
            if not ROADS.bridge(other.tags) then
              local ps = other.points
              for k = 1, #ps - 1 do
                below[#below + 1] = {ps[k][1], ps[k][2], ps[k + 1][1], ps[k + 1][2], other.hw + pier.clear}
              end
            end
          end
        end
        for _, seg in ipairs(below) do
          local ax, ay, bx, by, r = seg[1], seg[2], seg[3], seg[4], seg[5]
          if x > math.min(ax, bx) - r and x < math.max(ax, bx) + r and y > math.min(ay, by) - r and y < math.max(ay, by) + r then
            local dx, dy = bx - ax, by - ay
            local l2 = dx * dx + dy * dy
            local t = l2 > EPS and math.max(0, math.min(1, ((x - ax) * dx + (y - ay) * dy) / l2)) or 0
            if (x - ax - t * dx) ^ 2 + (y - ay - t * dy) ^ 2 < r * r then return true end
          end
        end
        return false
      end
      local function blocked(x, y, tx, ty, across)
        for _, f in ipairs({-1, -.5, 0, .5, 1}) do
          if roadUnder(x - ty * across * f, y + tx * across * f) then return true end
        end
        return false
      end
      local bridgeEnds = {}
      for _, strip in ipairs(ctx.strips) do
        local nodes = strip.road and strip.road.nodes or NONE
        for e = 1, 2 do
          local id = nodes[e] ~= nil and tostring(nodes[e])
          if id and ROADS.bridge(strip.tags) then bridgeEnds[id] = (bridgeEnds[id] or 0) + 1 end
        end
      end
      if length >= pier.min then
        local count = math.max(2, math.ceil(length / pier.every))
        for i = 1, count - 1 do
          local sample = frame(host.dist[1] + length * i / count)
          local across = (sample.left - sample.right) / 2 * pier.across
          local mid = (sample.left + sample.right) / 2
          local x = sample.x + sample.nx * mid
          local y = sample.y + sample.ny * mid
          local z = sample.z + lift - depth
          if owns(x, y) then
            local zg = ctx.ground(x, y)
            local clear = z - zg >= pier.gap and not blocked(x, y, sample.tx, sample.ty, across)
            if clear then
              ROADS.box(ctx.face, 'fence_wall', x, y, sample.tx, sample.ty, across, pier.thick / 2, zg - pier.sink, z + .05, deck.repeatU)
            end
          end
        end
      end
      local nodes = host.road and host.road.nodes or NONE
      for e = 1, 2 do
        local id = nodes[e] ~= nil and tostring(nodes[e])
        if id and bridgeEnds[id] == 1 then
          local sample = frame(e == 1 and host.dist[1] + pier.thick / 2 or host.dist[#host.dist] - pier.thick / 2)
          local across = (sample.left - sample.right) / 2 + deck.thick
          local mid = (sample.left + sample.right) / 2
          local x = sample.x + sample.nx * mid
          local y = sample.y + sample.ny * mid
          local z = sample.z + lift - depth
          local zg = ctx.ground(x, y)
          if owns(x, y) and z - zg > .1 then
            ROADS.box(ctx.face, 'fence_wall', x, y, sample.tx, sample.ty, across, pier.thick / 2, zg - pier.sink, z + .05, deck.repeatU)
          end
        end
      end
    end
    if ctx.pause then ctx.pause() end
  end
end
-- Guard rails on high embankments of main roads the road register does not cover (no
-- e2r:rails=register): where the road stands `height` m over the raw DEM `probe` m out from its
-- edge for at least `run` m, a rail `rail.offset` m off the edge (sidewalk included). A rail
-- stops `clear` m short of any other road (a slip road, a junction). ctx: strips, rect, dem(x, y),
-- crowded(x, y, road), face, sidewalk, pause.
ROADS.embankment = {height = 3, probe = 8, run = 30, step = 4, clear = 1}
function ROADS.embankmentRails(ctx)
  local shape, rail = ROADS.embankment, ROADS.rail
  if not ctx.dem then return end
  for index, strip in ipairs(ctx.strips) do
    local tags, points, dist, edge, hw = strip.tags or NONE, strip.points, strip.dist, strip.edge, strip.hw
    local n = #points
    if n >= 2 and edge and not ROADS.bridge(tags) and not ROADS.tunnel(tags) and strip.grade == 0
        and ROADS.rankOf(tags) >= rail.rank and tags['e2r:rails'] ~= 'register' and dist[n] >= shape.run then
      for _, sign in ipairs({1, -1}) do
        local paths, path, from = {}, nil, 0
        local function close(s)
          if path and #path >= 2 and s - from >= shape.run then paths[#paths + 1] = path end
          path = nil
        end
        local k = 1
        for s = 0, dist[n], shape.step do
          while k < n - 1 and dist[k + 1] < s do k = k + 1 end
          local t = math.max(0, math.min(1, (s - dist[k]) / math.max(EPS, dist[k + 1] - dist[k])))
          local walk = (strip.walk[k] or NONE)[sign] and ctx.sidewalk or 0
          local function at(offset)
            local a, b = edge(k, offset * sign, 0), edge(k + 1, offset * sign, 0)
            return {a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t, a[3] + (b[3] - a[3]) * t}
          end
          local p, probe = at(hw + walk + rail.offset), at(hw + walk + shape.probe)
          local z = (points[k][3] or 0) + ((points[k + 1][3] or 0) - (points[k][3] or 0)) * t
          local below = ctx.dem(probe[1], probe[2])      -- nil off every source grid
          local high = below ~= nil and z - below >= shape.height
            and not ctx.crowded(p[1], p[2], strip.road, shape.clear)
          if high then
            if not path then path, from = {}, s end
            path[#path + 1] = p
          else
            close(s)
          end
        end
        close(dist[n])
        for _, rails in ipairs(paths) do
          ROADS.guardRail({rect = ctx.rect, face = ctx.face, behind = sign}, rails)
        end
      end
    end
    if index % 16 == 0 and ctx.pause then ctx.pause() end
  end
end
-- Paved shoulder (m) outside the edge lines, left and right of the node order: tagged
-- (shoulder:left:width and shoulder:right:width, from the road register), else by class where the
-- way has no width tag: the pack widened the carriageway by it (fast_sources.shoulder, same rule).
ROADS.shoulders = {motorway = {.75, 2.5}, trunk = {1, 1}, primary = {.5, .5}, secondary = {.25, .25}}
ROADS.shouldersOneway = {trunk = {.5, 1.5}, primary = {.25, .75}}
function ROADS.shoulder(tags)
  local tagLeft, tagRight = tonumber(tags['shoulder:left:width']), tonumber(tags['shoulder:right:width'])
  if tagLeft and tagRight then return tagLeft, tagRight end
  local highway = tags.highway or ''
  if tags.width ~= nil or ROADS.ring(tags) then return 0, 0 end
  local oneway, flip = ROADS.oneway(tags)
  local s = (highway == 'motorway_link' or highway == 'trunk_link') and {.25, 1}
    or oneway and ROADS.shouldersOneway[highway] or ROADS.shoulders[highway]
  if not s then return 0, 0 end
  if flip then return s[2], s[1] end
  return s[1], s[2]
end
-- The painted lines of a strip by class, lanes and surface: {offset, width, dashed, double}.
-- Gravel, dirt and broken roads have none; minor streets have none unless tagged with lanes.
function ROADS.marks(tags, width, grade)
  local marks = {}
  local paint = tostring(tags.lane_markings or '')
  if grade >= 2 or paint == 'no' or width < 4.5 then return marks end
  local class = (tags.highway or ''):gsub('_link$', '')
  local oneway = ROADS.oneway(tags)
  -- offsets are left of the node order; the lanes share the carriageway between the shoulders
  local left, right = ROADS.shoulder(tags)
  if width - left - right < 3 then left, right = 0, 0 end
  local carriage = width - left - right
  local lanes = math.max(1, math.min(math.floor(carriage / 2.5),
    math.floor(number(tags.lanes, ROADS.ring(tags) and math.floor(carriage / 4 + .1)
      or oneway and math.floor(carriage / 3.3 + .5) or 2))))
  local painted = ROADS.centred[class] or tags.lanes ~= nil or paint == 'yes'
  if painted and lanes >= 2 then
    for lane = 1, lanes - 1 do
      local centre = not oneway and math.abs(lane - lanes / 2) < .01
      local at = -width / 2 + right + lane * carriage / lanes
      -- a four-lane two-way road: a solid double centre line
      if centre and lanes >= 4 then
        marks[#marks + 1] = {offset = at - .1, width = .12}
        marks[#marks + 1] = {offset = at + .1, width = .12}
      else
        marks[#marks + 1] = {offset = at, width = .12, dashed = true}
      end
    end
  end
  if ROADS.edged[class] or (class == 'tertiary' and width >= 6) or (paint == 'yes' and width >= 6) then
    -- on the carriageway's edge where there is a shoulder, else a little inside the asphalt
    local l, r = left > 0 and left + .1 or .3, right > 0 and right + .1 or .3
    marks[#marks + 1], marks[#marks + 2] = {offset = width / 2 - l, width = .15}, {offset = -width / 2 + r, width = .15}
  end
  return marks
end

-- A track's runs off the roads: its line every TRACK_STEP m, cut where it comes within
-- TRACK_CLEAR of a road's edge (segmentBins: the tile's road segments in 50 m bins), each
-- point at height(x, y), the ground pulled to the roads, so a run's end meets the road's edge.
-- A rough track's rise and fall (WEAR_AMP by grade, densifyWear's hash) is added here: its
-- points are already closer than densifyWear's spans. The first and last 6 m stay put.
local TRACK_STEP, TRACK_CLEAR, TRACK_MIN = 4, .3, 2
function ROADS.trackRuns(points, segmentBins, height, grade)
  local function onRoad(p)
    local x, y = p[1], p[2]
    for _, segment in ipairs(segmentBins[(math.floor(x / 50) + 32768) * 65536 + math.floor(y / 50) + 32768] or {}) do
      if segment.surface then
        local a = segment.a
        local t = math.max(0, math.min(1, ((x - a[1]) * segment.dx + (y - a[2]) * segment.dy) / segment.len2))
        local dx, dy = x - (a[1] + t * segment.dx), y - (a[2] + t * segment.dy)
        if dx * dx + dy * dy < (segment.width / 2 + TRACK_CLEAR) ^ 2 then return true end
      end
    end
    return false
  end
  local function mix(a, b, t)
    return {a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t, (a[3] or 0) + ((b[3] or 0) - (a[3] or 0)) * t}
  end
  local dense = {}
  for k = 1, #points - 1 do
    local a, b = points[k], points[k + 1]
    local n = math.max(1, math.ceil(math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2) / TRACK_STEP))
    for i = 0, n - 1 do dense[#dense + 1] = mix(a, b, i / n) end
  end
  if #points >= 2 then dense[#dense + 1] = mix(points[#points], points[#points], 0) end
  local runs, run, prev, prevIn = {}, nil, nil, nil
  for _, p in ipairs(dense) do
    local inside = onRoad(p)
    if prev and inside ~= prevIn then
      -- the road's edge between the two samples: lo keeps prev's side, hi p's
      local lo, hi = prev, p
      for _ = 1, 8 do
        local m = mix(lo, hi, .5)
        if onRoad(m) == prevIn then lo = m else hi = m end
      end
      if inside then run[#run + 1], run = lo, nil
      else run = {hi}; runs[#runs + 1] = run end
    end
    if not inside then
      if not run then run = {}; runs[#runs + 1] = run end
      run[#run + 1] = p
    end
    prev, prevIn = p, inside
  end
  local out = {}
  for _, r in ipairs(runs) do
    local length = 0
    for k = 2, #r do length = length + math.sqrt((r[k][1] - r[k - 1][1]) ^ 2 + (r[k][2] - r[k - 1][2]) ^ 2) end
    if #r >= 2 and length >= TRACK_MIN then
      local amp, along = WEAR_AMP[(grade or 0) + 1] or 0, 0
      for k, p in ipairs(r) do
        if k > 1 then along = along + math.sqrt((p[1] - r[k - 1][1]) ^ 2 + (p[2] - r[k - 1][2]) ^ 2) end
        p[3] = height(p[1], p[2]) or p[3]
        if amp > 0 and along > 6 and length - along > 6 then
          p[3] = p[3] + (hash('wear:' .. math.floor(p[1] + .5) .. ':' .. math.floor(p[2] + .5)) % 1000 / 1000 - .5) * 2 * amp
        end
      end
      out[#out + 1] = r
    end
  end
  return out
end

local SPEED = {motorway = 110, trunk = 90, primary = 60, secondary = 60, tertiary = 50,
  unclassified = 50, residential = 40, living_street = 20}
local DRIVE = {motorway = 1, trunk = 1, primary = 1, secondary = 1, tertiary = .9,
  unclassified = .7, residential = .7, living_street = .4}
local NAV_MIN = .5     -- m: the shortest navgraph edge
local function navSegment(road)
  local tags, points = road.tags or {}, road.points or {}
  local highway = (tags.highway or 'residential'):gsub('_link$', '')
  if not SPEED[highway] or tags.access == 'private' or tags.access == 'no' or tags.area == 'yes' or #points < 2 then return nil end
  local total = math.max(1, math.min(8, math.floor(number(tags.lanes, math.floor((road.width or 7) / 3.5 + .5)))))
  local oneway, flip = ROADS.oneway(tags)
  local lanes
  if oneway then
    lanes = string.rep('+', math.min(4, total))
  else
    local back = number(tags['lanes:backward'], math.max(1, math.floor(total / 2)))
    local forward = number(tags['lanes:forward'], math.max(1, total - back))
    lanes = string.rep('-', math.min(4, back)) .. string.rep('+', math.min(4, forward))
  end
  local speedText = tostring(tags.maxspeed or ''):lower()
  local speed = number(speedText, SPEED[highway])
  if speedText:find('mph', 1, true) then speed = speed * 1.609 end
  if speedText == 'none' then speed = 130 end
  if speedText:find('urban', 1, true) then speed = 50 end
  if speedText:find('rural', 1, true) then speed = 90 end
  local nodes = road.nodes or {tostring(road.id) .. ':a', tostring(road.id) .. ':b'}
  local result = {tostring(road.id), nodes[flip and 2 or 1], nodes[flip and 1 or 2], lanes,
    speed / 3.6, (road.width or 7) / 2, DRIVE[highway]}
  -- Knots closer than NAV_MIN are one: the game's random route walk (graphpath getRandomPathG,
  -- traffic respawns) adds edge lengths until it has enough, and on a piece of graph of only
  -- zero-length edges (repeated source points) it never had, and froze the game.
  local ordered = {}
  for index = 1, #points do
    local p = points[flip and (#points - index + 1) or index]
    local q = ordered[#ordered]
    if not q or (p[1] - q[1]) ^ 2 + (p[2] - q[2]) ^ 2 >= NAV_MIN * NAV_MIN then ordered[#ordered + 1] = p
    elseif index == #points then ordered[#ordered] = p end   -- the end node keeps its own point
  end
  if #ordered < 2 then return nil end
  for index, p in ipairs(ordered) do
    if index > 1 then
      local prev = ordered[index - 1]
      local distance = math.sqrt((p[1] - prev[1]) ^ 2 + (p[2] - prev[2]) ^ 2)
      local steps = math.max(1, math.ceil(distance / 80))
      for step = 1, steps - 1 do
        local q = lerp(prev, p, step / steps)
        result[#result + 1], result[#result + 2], result[#result + 3] = q[1], q[2], (q[3] or 0) + ROAD_LIFT
      end
    end
    result[#result + 1], result[#result + 2], result[#result + 3] = p[1], p[2], (p[3] or 0) + ROAD_LIFT
  end
  return result
end

-- Which sides get a sidewalk (1 left, -1 right of the direction): city streets by default unless
-- tagged otherwise; one carriageway of a divided road only on its right.
local WALKS = {primary = true, secondary = true, tertiary = true, residential = true, living_street = true, unclassified = true}
local function walkSides(tags)
  if roadGrade(tags) >= 2 then return {} end
  if not WALKS[tags.highway] then return {} end
  local v = tags.sidewalk
  local both, left, right = tags['sidewalk:both'], tags['sidewalk:left'], tags['sidewalk:right']
  if both or left or right then
    -- per-side tags win; 'separate' is a footway mapped beside the road, which is not drawn
    local function on(side) return side ~= nil and side ~= 'no' and side ~= 'none' end
    local base = v == 'both' or v == 'yes' or v == 'separate'
    local sides = {}
    if on(left or both) or (left == nil and both == nil and (base or v == 'left')) then sides[1] = true end
    if on(right or both) or (right == nil and both == nil and (base or v == 'right')) then sides[-1] = true end
    return sides
  end
  if v == nil and ROADS.oneway(tags) then return {[-1] = true} end
  if v == 'no' or v == 'none' then return {} end
  if v == 'left' then return {[1] = true} end
  if v == 'right' then return {[-1] = true} end
  return {[1] = true, [-1] = true}
end

-- A segment's sidewalk sides. An untagged street gets walkSides' default only where the ground
-- round its middle is built over: Ukraine's village streets and tertiary roads through the
-- forest were paved 2 m either side (decals-rural-04, decals-village-04). Built share along
-- the streets of the Ukraine pack (p10-p90): central Kyiv .21-.45, Obolon and Darnytsia main
-- roads .04-.39, Boyarka .10-.22, Kyiv's private houses .09-.18, the villages Hatne and Bilychi
-- .04-.14, fields 0. Main roads keep sidewalks from WALK_MAIN (a village's high street, a
-- prospect between far-apart blocks); streets from WALK_STREET (a town, not a village).
local WALK_MAIN, WALK_STREET = .04, .12
local MAIN_ROADS = {primary = true, secondary = true, tertiary = true}
local function walkAt(tags, sides, a, b, builtAt)
  if tags.sidewalk ~= nil or tags['sidewalk:both'] ~= nil or tags['sidewalk:left'] ~= nil
      or tags['sidewalk:right'] ~= nil or not next(sides) then return sides end
  local least = MAIN_ROADS[tags.highway] and WALK_MAIN or WALK_STREET
  return builtAt((a[1] + b[1]) / 2, (a[2] + b[2]) / 2) >= least and sides or NONE
end

-- Road details at OSM way nodes (fast_style.ROAD_DETAILS, kept 30 m round the tile by the cell
-- decoder): turning circles widen a dead end into a round plate (the junction builder), zebra
-- crossings, stop and give-way lines and mini-roundabout rings are painted (DETAIL.paint). A
-- node sits on a vertex of its road, and the road's points follow the way, so the node finds
-- its road and the way's direction without any heading in the pack.
local DETAIL = {near = .5, zebra = 3, stripe = .5, gap = .5, bar = .4, tooth = {.5, .6, .4}, ring = {2, .3},
  kinds = {crossing = true, give_way = true, stop_sign = true, mini_roundabout = true}}
-- {[bucket] = {point...}} of the points of the given kinds, by the metre
function DETAIL.index(points, kinds)
  local bins = {}
  for _, point in ipairs(points) do
    local p = point.pos
    if p and kinds[point.kind] then
      local key = (floor(p[1]) + 65536) * 131072 + floor(p[2]) + 65536
      local bin = bins[key] or {}
      bins[key], bin[#bin + 1] = bin, point
    end
  end
  return bins
end
function DETAIL.at(bins, x, y, kind)
  for dx = -1, 1 do
    for dy = -1, 1 do
      for _, point in ipairs(bins[(floor(x) + dx + 65536) * 131072 + floor(y) + dy + 65536] or NONE) do
        local p = point.pos
        if (not kind or point.kind == kind) and (p[1] - x) ^ 2 + (p[2] - y) ^ 2 < DETAIL.near ^ 2 then return point end
      end
    end
  end
end
-- The round end of a dead end: points at radius r round the node outside the mouth's two corners
-- (cut along the road from the node, half a width aside), in the node's ground height.
function DETAIL.bulb(node, dx, dy, hw, cut, r)
  local out, base = {}, math.atan2(dy, dx)
  local open = math.atan2(hw, math.max(cut, EPS)) + .05
  local n = 20
  for k = 0, n do
    local a = base + open + (2 * math.pi - 2 * open) * k / n
    out[#out + 1] = {node[1] + math.cos(a) * r, node[2] + math.sin(a) * r, node[3] or 0}
  end
  return out
end
function DETAIL.bulbRadius(width)
  return math.max(6, math.min(12, width / 2 + 3))
end
-- a quad round centre c (x, y, z) along the unit axis (ax, ay): length along it, width across;
-- u across the paint, v along it (the mark texture's line runs along v)
local function paintQuad(emit, c, ax, ay, length, width, z0, z1)
  local nx, ny, hl, hw = -ay, ax, length / 2, width * DECAL.markSpread / 2
  emit({{c[1] - ax * hl + nx * hw, c[2] - ay * hl + ny * hw, z0, 0, 0},
    {c[1] - ax * hl - nx * hw, c[2] - ay * hl - ny * hw, z0, 1, 0},
    {c[1] + ax * hl - nx * hw, c[2] + ay * hl - ny * hw, z1 or z0, 1, length / DECAL.markRepeat},
    {c[1] + ax * hl + nx * hw, c[2] + ay * hl + ny * hw, z1 or z0, 0, length / DECAL.markRepeat}})
end
-- where along a polyline s falls: the point (with z) and the unit direction there
local function alongLine(points, dist, s)
  local n = #points
  for k = 1, n - 1 do
    if s <= dist[k + 1] or k == n - 1 then
      local a, b = points[k], points[k + 1]
      local l = math.max(EPS, dist[k + 1] - dist[k])
      local t = math.max(0, math.min(1, (s - dist[k]) / l))
      return lerp(a, b, t), (b[1] - a[1]) / l, (b[2] - a[2]) / l
    end
  end
  return points[1], 1, 0
end
-- ctx: roads, points, stars, cutsOf, rect, z (paint over the profile), emit(poly), pause
function DETAIL.paint(ctx)
  local wanted = {}
  local rect = ctx.rect
  for _, point in ipairs(ctx.points) do
    local p = point.pos
    if p and point.kind ~= 'turning_circle' and ctx.kinds[point.kind]
        and boundsTouch(rect, {p[1], p[2], p[1], p[2]}, 15) then
      wanted[#wanted + 1] = point
    end
  end
  if #wanted == 0 then return 0 end
  -- the raw road vertices round the tile, by the metre
  local vertices = {}
  for index, road in ipairs(ctx.roads) do
    local points = road.points or NONE
    if #points >= 2 then
      for k, p in ipairs(points) do
        if boundsTouch(rect, {p[1], p[2], p[1], p[2]}, 20) then
          local key = (floor(p[1]) + 65536) * 131072 + floor(p[2]) + 65536
          local bin = vertices[key] or {}
          vertices[key], bin[#bin + 1] = bin, {road, k}
        end
      end
    end
    if index % 256 == 0 then ctx.pause() end
  end
  local painted = 0
  for _, point in ipairs(wanted) do
    local p, tags = point.pos, point.tags or NONE
    if point.kind == 'mini_roundabout' then
      for _, star in ipairs(ctx.stars) do
        if (star.node[1] - p[1]) ^ 2 + (star.node[2] - p[2]) ^ 2 < 1 then
          local r, w, n = DETAIL.ring[1], DETAIL.ring[2], 24
          for k = 1, n do
            local a, b = 2 * math.pi * (k - 1) / n, 2 * math.pi * k / n
            local ca, cb = {star.node[1] + math.cos(a) * r, star.node[2] + math.sin(a) * r},
              {star.node[1] + math.cos(b) * r, star.node[2] + math.sin(b) * r}
            local ax, ay = cb[1] - ca[1], cb[2] - ca[2]
            local l = math.sqrt(ax * ax + ay * ay)
            paintQuad(ctx.emit, {(ca[1] + cb[1]) / 2, (ca[2] + cb[2]) / 2}, ax / l, ay / l, l + .02, w,
              star.height + ctx.z + .005)
          end
          painted = painted + 1
          break
        end
      end
    else
      local found
      for dx = -1, 1 do
        for dy = -1, 1 do
          for _, v in ipairs(vertices[(floor(p[1]) + dx + 65536) * 131072 + floor(p[2]) + dy + 65536] or NONE) do
            local q = v[1].points[v[2]]
            local d = (q[1] - p[1]) ^ 2 + (q[2] - p[2]) ^ 2
            if d < DETAIL.near ^ 2 and (not found or d < found[3]) then found = {v[1], v[2], d} end
          end
        end
      end
      if found then
        local road, k = found[1], found[2]
        local rtags, points = road.tags or NONE, road.points
        local dist = {0}
        for i = 2, #points do
          dist[i] = dist[i - 1] + math.sqrt((points[i][1] - points[i - 1][1]) ^ 2 + (points[i][2] - points[i - 1][2]) ^ 2)
        end
        local length, s = dist[#points], dist[k]
        local width = math.max(.5, math.min(80, road.width or 7))
        local left, right = ROADS.shoulder(rtags)
        if width - left - right < 3 then left, right = 0, 0 end
        -- the carriageway between the shoulders, as offsets left of the node order
        local lo, hi = -width / 2 + right, width / 2 - left
        if point.kind == 'crossing' then
          local c, tx, ty = alongLine(points, dist, s)
          local zebra = (hi - lo) < 5 and DETAIL.zebra - .5 or DETAIL.zebra
          local z0 = (alongLine(points, dist, s - zebra / 2)[3] or 0) + ctx.z
          local z1 = (alongLine(points, dist, s + zebra / 2)[3] or 0) + ctx.z
          local pitch = DETAIL.stripe + DETAIL.gap
          local count = math.max(1, math.floor((hi - lo + DETAIL.gap) / pitch))
          local first = (lo + hi) / 2 - (count - 1) * pitch / 2
          for n = 0, count - 1 do
            local o = first + n * pitch
            paintQuad(ctx.emit, {c[1] - ty * o, c[2] + tx * o}, tx, ty, zebra, DETAIL.stripe, z0, z1)
          end
          painted = painted + 1
        else
          -- the approach: the tagged direction, else towards the nearer road end
          local direction = tostring(tags.direction or '')
          local forward
          if direction == 'forward' then forward = true
          elseif direction == 'backward' then forward = false
          else forward = (length - s) <= s end
          -- by a junction the line goes to its mouth, where the strip stops
          local cuts = ctx.cutsOf[road] or NONE
          local cut = forward and (cuts[2] or 0) or (cuts[1] or 0)
          local toEnd = forward and (length - s) or s
          local at = s
          if cut > 0 and toEnd <= cut + 6 then at = forward and length - cut - .3 or cut + .3 end
          local c, tx, ty = alongLine(points, dist, at)
          local sx, sy = forward and tx or -tx, forward and ty or -ty   -- the travel direction
          local oneway = ROADS.oneway(rtags)
          local mid = (lo + hi) / 2
          -- right-hand traffic: the approach lanes are right of the travel direction
          local a, b = lo, hi
          if not oneway then
            if forward then a, b = lo, mid else a, b = mid, hi end
          end
          local z = (c[3] or 0) + ctx.z
          if point.kind == 'stop_sign' then
            local o = (a + b) / 2
            local back = DETAIL.bar / 2
            paintQuad(ctx.emit, {c[1] - ty * o - sx * back, c[2] + tx * o - sy * back}, -ty, tx, b - a, DETAIL.bar, z)
          else
            local base, height, gap = DETAIL.tooth[1], DETAIL.tooth[2], DETAIL.tooth[3]
            local count = math.max(1, math.floor((b - a + gap) / (base + gap)))
            local first = (a + b) / 2 - (count - 1) * (base + gap) / 2
            for n = 0, count - 1 do
              local o = first + n * (base + gap)
              local bx, by = c[1] - ty * o, c[2] + tx * o
              -- the base on the line, the point towards the driver coming up to it
              ctx.emit({{bx - ty * base / 2, by + tx * base / 2, z, 0, 0},
                {bx - sx * height, by - sy * height, z, .5, height / DECAL.markRepeat},
                {bx + ty * base / 2, by - tx * base / 2, z, 1, 0}})
            end
          end
          painted = painted + 1
        end
      end
    end
    ctx.pause()
  end
  return painted
end

-- Raised traffic islands (OSM area:highway=traffic_island, traffic_calming=island areas): a
-- `height` m slab over the road beside it, its rim a curb face down to `sink` under the road.
-- Grass on top when tagged so or bigger than `paved` m2, else sett paving. ctx: roads (the
-- pack's road lines, raw), rect, lift, polygon(material, poly), pause.
ROADS.islandShape = {height = .15, sink = .2, reach = 25, paved = 60}
function ROADS.island(ctx, area)
  local shape, rect = ROADS.islandShape, ctx.rect
  local ring = cleanRing((area.rings or NONE)[1] or NONE)
  if #ring < 3 or not ringsTouch({ring}, rect) then return end
  local box = ringBounds({ring})
  local r = shape.reach
  -- the height of the nearest at-grade road (its raw line: the same in every tile of the cell)
  local segments = {}
  for _, road in ipairs(ctx.roads or NONE) do
    local tags = road.tags or NONE
    if not ROADS.bridge(tags) and not ROADS.tunnel(tags) then
      local ps = road.points or NONE
      for k = 1, #ps - 1 do
        local a, b = ps[k], ps[k + 1]
        if math.max(a[1], b[1]) > box[1] - r and math.min(a[1], b[1]) < box[3] + r
          and math.max(a[2], b[2]) > box[2] - r and math.min(a[2], b[2]) < box[4] + r then
          segments[#segments + 1] = {a, b}
        end
      end
    end
  end
  if #segments == 0 then return end      -- an island off every road (a pedestrian area's)
  local function roadAt(x, y)
    local best, z = math.huge, 0
    for _, s in ipairs(segments) do
      local a, b = s[1], s[2]
      local sx, sy = b[1] - a[1], b[2] - a[2]
      local l2 = sx * sx + sy * sy
      local t = l2 > EPS and math.max(0, math.min(1, ((x - a[1]) * sx + (y - a[2]) * sy) / l2)) or 0
      local d = (x - a[1] - t * sx) ^ 2 + (y - a[2] - t * sy) ^ 2
      if d < best then best, z = d, (a[3] or 0) + ((b[3] or 0) - (a[3] or 0)) * t end
    end
    return z + ctx.lift
  end
  local twice = 0
  for k, a in ipairs(ring) do
    local b = ring[k % #ring + 1]
    twice = twice + a[1] * b[2] - b[1] * a[2]
  end
  local tags = area.tags or NONE
  local grass = tags.surface == 'grass' or tags.landuse == 'grass'
    or (tags.surface == nil and math.abs(twice) / 2 > shape.paved)
  local top = grass and 'ground' or 'paved'
  for _, quad in ipairs(triangulate({ring}, nil, rect, true)) do
    local poly = {}
    for n, p in ipairs(quad) do poly[n] = {p[1], p[2], roadAt(p[1], p[2]) + shape.height, p[1] / 2, p[2] / 2} end
    ctx.polygon(top, poly, true)
  end
  -- the rim: each edge in the tile holding its midpoint, faced outwards (ring winding)
  local outward = twice > 0 and 1 or -1
  for k, a in ipairs(ring) do
    local b = ring[k % #ring + 1]
    local mx, my = (a[1] + b[1]) / 2, (a[2] + b[2]) / 2
    local dx, dy = b[1] - a[1], b[2] - a[2]
    local l = math.sqrt(dx * dx + dy * dy)
    if l > EPS and mx >= rect[1] and mx < rect[3] and my >= rect[2] and my < rect[4] then
      local za, zb = roadAt(a[1], a[2]), roadAt(b[1], b[2])
      local h = shape.height + shape.sink
      ROADS.orient(ctx.polygon, 'curb', {{a[1], a[2], za + shape.height, 0, 0}, {b[1], b[2], zb + shape.height, l, 0},
        {b[1], b[2], zb - shape.sink, l, h}, {a[1], a[2], za - shape.sink, 0, h}}, dy / l * outward, -dx / l * outward, 0)
    end
  end
  if ctx.pause then ctx.pause() end
end

-- Roundabout aprons: a small roundabout (junction=roundabout ways closing a ring of at most
-- `maxRadius` m) gets a sett-paved truncated apron inside the carriageway, `width` m (at most
-- `share` of the inner radius) wide, `height` m over the road, its island side a curb face
-- down to `sink` under the road. Each quad is drawn by the tile holding its midpoint.
-- ctx: roads (the pack's road lines, raw), rect, lift, polygon(material, poly, up), pause.
ROADS.apronShape = {maxRadius = 25, minInner = 3, width = 2, share = .3, height = .04, curb = .12,
  sink = .2, round = .15, gap = math.pi / 3}
function ROADS.aprons(ctx)
  local shape, rect = ROADS.apronShape, ctx.rect
  local parent, members, order = {}, {}, {}
  local function find(id)
    while parent[id] ~= id do parent[id] = parent[parent[id]]; id = parent[id] end
    return id
  end
  for _, road in ipairs(ctx.roads or NONE) do
    local tags, nodes = road.tags or NONE, road.nodes or NONE
    if ROADS.ring(tags) and not ROADS.bridge(tags) and not ROADS.tunnel(tags)
        and nodes[1] ~= nil and nodes[2] ~= nil and #(road.points or NONE) >= 2 then
      local a, b = tostring(nodes[1]), tostring(nodes[2])
      for _, id in ipairs({a, b}) do if not parent[id] then parent[id] = id end end
      parent[find(a)] = find(b)
      members[#members + 1] = {road = road, node = a}
    end
  end
  local groups = {}
  for _, m in ipairs(members) do
    local root = find(m.node)
    if not groups[root] then groups[root], order[#order + 1] = {}, root end
    local g = groups[root]
    g[#g + 1] = m.road
  end
  for _, root in ipairs(order) do
    local group = groups[root]
    local sx, sy, n, widths = 0, 0, 0, {}
    for _, road in ipairs(group) do
      local ps = road.points
      for k = 1, #ps - 1 do sx, sy, n = sx + ps[k][1], sy + ps[k][2], n + 1 end
      widths[#widths + 1] = math.max(.5, math.min(40, road.width or 7))
    end
    local cx, cy = sx / math.max(1, n), sy / math.max(1, n)
    -- the ring's inner edge: every vertex moved half its road's width towards the centre
    local edge, radii = {}, 0
    for i, road in ipairs(group) do
      local hw = widths[i] / 2
      for _, p in ipairs(road.points) do
        local dx, dy = p[1] - cx, p[2] - cy
        local r = math.sqrt(dx * dx + dy * dy)
        if r > EPS then
          edge[#edge + 1] = {angle = math.atan2(dy, dx), r = r, hw = hw, z = p[3] or 0}
          radii = radii + r
        end
      end
    end
    local mean = radii / math.max(1, #edge)
    table.sort(edge, function(a, b) return a.angle < b.angle end)
    local round, widest = #edge >= 6 and mean <= shape.maxRadius, 0
    for k, e in ipairs(edge) do
      if math.abs(e.r - mean) > shape.round * mean + 1 then round = false end
      local nxt = edge[k % #edge + 1]
      local step = (nxt.angle - e.angle) % (2 * math.pi)
      if #edge == 1 then step = 2 * math.pi end
      widest = math.max(widest, step)
    end
    local hwMean = 0
    for _, w in ipairs(widths) do hwMean = hwMean + w / 2 end
    hwMean = hwMean / #widths
    local inner = mean - hwMean
    if round and widest <= shape.gap and inner >= shape.minInner
        and cx > rect[1] - mean and cx < rect[3] + mean and cy > rect[2] - mean and cy < rect[4] + mean then
      local width = math.min(shape.width, inner * shape.share)
      local function at(e, back)
        local r = math.max(.5, e.r - e.hw - back)
        local c, s = math.cos(e.angle), math.sin(e.angle)
        return cx + c * r, cy + s * r
      end
      for k, a in ipairs(edge) do
        local b = edge[k % #edge + 1]
        local ox1, oy1 = at(a, 0)
        local ox2, oy2 = at(b, 0)
        local ix1, iy1 = at(a, width)
        local ix2, iy2 = at(b, width)
        local mx, my = (ox1 + ox2 + ix1 + ix2) / 4, (oy1 + oy2 + iy1 + iy2) / 4
        if mx >= rect[1] and mx < rect[3] and my >= rect[2] and my < rect[4] then
          local za, zb = a.z + ctx.lift, b.z + ctx.lift
          local top = shape.height
          ctx.polygon('paved', {{ox1, oy1, za + top, ox1 / 2, oy1 / 2}, {ix1, iy1, za + top, ix1 / 2, iy1 / 2},
            {ix2, iy2, zb + top, ix2 / 2, iy2 / 2}, {ox2, oy2, zb + top, ox2 / 2, oy2 / 2}}, true)
          -- the island's curb: up from the apron, faced out onto it
          local dx, dy = ix2 - ix1, iy2 - iy1
          local l = math.sqrt(dx * dx + dy * dy)
          if l > EPS then
            local fx, fy = cx - (ix1 + ix2) / 2, cy - (iy1 + iy2) / 2
            local fl = math.max(EPS, math.sqrt(fx * fx + fy * fy))
            local h = shape.curb + shape.sink
            ROADS.orient(ctx.polygon, 'curb', {{ix1, iy1, za + shape.curb, 0, 0}, {ix2, iy2, zb + shape.curb, l, 0},
              {ix2, iy2, zb - shape.sink, l, h}, {ix1, iy1, za - shape.sink, 0, h}}, -fx / fl, -fy / fl, 0)
          end
        end
      end
    end
    if ctx.pause then ctx.pause() end
  end
end

-- An overhead sign gantry (OSM man_made=gantry, a way from post to post across the road): a
-- lattice tower at each end and a lattice beam `clear` m over the highest ground under it.
-- ctx: rect, ground(x, y), face(poly, ox, oy, oz, material).
ROADS.gantryShape = {clear = 5.8, depth = 1.2, width = .9, post = .7, step = 2, material = 'fence_mesh',
  chord = .08, chordMaterial = 'clad_metal'}
function ROADS.gantry(ctx, line)
  local shape, rect, ground = ROADS.gantryShape, ctx.rect, ctx.ground
  local ps = line.points or NONE
  if #ps < 2 then return end
  local function mine(x, y) return x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4] end
  local high = -math.huge
  for k = 1, #ps - 1 do
    local a, b = ps[k], ps[k + 1]
    local n = math.max(1, math.ceil(math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2) / shape.step))
    for i = 0, n do
      local x, y = a[1] + (b[1] - a[1]) * i / n, a[2] + (b[2] - a[2]) * i / n
      high = math.max(high, ground(x, y))
    end
  end
  local zb = high + shape.clear
  local zt = zb + shape.depth
  local face, m, half = ctx.face, shape.material, shape.width / 2
  for k = 1, #ps - 1 do
    local a, b = ps[k], ps[k + 1]
    local dx, dy = b[1] - a[1], b[2] - a[2]
    local l = math.sqrt(dx * dx + dy * dy)
    local mx, my = (a[1] + b[1]) / 2, (a[2] + b[2]) / 2
    if l > EPS and mine(mx, my) then
      local tx, ty = dx / l, dy / l
      ROADS.box(face, m, mx, my, tx, ty, half, l / 2, zb, zt, 2)
      local nx, ny = -ty * half, tx * half
      for _, z in ipairs({zb, zt}) do
        face({{a[1] + nx, a[2] + ny, z, 0, 0}, {b[1] + nx, b[2] + ny, z, l / 2, 0},
          {b[1] - nx, b[2] - ny, z, l / 2, half}, {a[1] - nx, a[2] - ny, z, 0, half}}, 0, 0, z == zt and 1 or -1, m)
        -- solid chords along the beam's four edges
        for _, side in ipairs({1, -1}) do
          local cx, cy = mx + nx * side, my + ny * side
          ROADS.box(face, shape.chordMaterial, cx, cy, tx, ty, shape.chord, l / 2, z - shape.chord, z + shape.chord, 1)
        end
      end
    end
  end
  for _, e in ipairs({ps[1], ps[#ps]}) do
    if mine(e[1], e[2]) then
      local a, b = ps[1], ps[#ps]
      local dx, dy = b[1] - a[1], b[2] - a[2]
      local l = math.max(EPS, math.sqrt(dx * dx + dy * dy))
      ROADS.box(face, m, e[1], e[2], dx / l, dy / l, shape.post / 2, shape.post / 2, ground(e[1], e[2]) - .3, zt, 2)
    end
  end
end

-- Gores: where a slip road leaves or joins a main carriageway (two one-way mouths of a node
-- running off within `angle` of each other, one a link or both main roads), the wedge between
-- their facing edges is paved until it is `wide` m across and hatched with diagonal stripes
-- every `every` m, `stripe` m wide; past that the ground (a grass gore) takes over.
local GORE = {angle = .82, wide = 3.5, start = .2, every = 5, stripe = .45, margin = .3, step = 1,
  reach = 150, rank = 4.5, sink = .01}

-- a mouth's point and unit direction (away from the node) s metres from the node
local function goreAt(m, s)
  local points, dist = m.road.points, m.dist
  local length = dist[#points]
  local p, dx, dy = alongLine(points, dist, m.e == 1 and s or length - s)
  if m.e == 2 then dx, dy = -dx, -dy end
  return p, dx, dy
end

-- ctx: roads, rect, lift, markZ, surface(material, poly), mark(poly), material(tags), pause
function GORE.paint(ctx)
  local mouths, order = {}, {}
  for _, road in ipairs(ctx.roads) do
    local tags, points, nodes = road.tags or NONE, road.points or NONE, road.nodes or NONE
    local highway = tags.highway or ''
    local link = highway:find('_link$') ~= nil
    if #points >= 2 and nodes[1] ~= nil and nodes[2] ~= nil and ROADS.oneway(tags)
        and (link or ROADS.rankOf(tags) >= GORE.rank) and not ROADS.bridge(tags) and not ROADS.tunnel(tags) then
      local dist = {0}
      for k = 2, #points do
        dist[k] = dist[k - 1] + math.sqrt((points[k][1] - points[k - 1][1]) ^ 2 + (points[k][2] - points[k - 1][2]) ^ 2)
      end
      if dist[#points] > 2 then
        for e = 1, 2 do
          local id = tostring(nodes[e])
          if not mouths[id] then mouths[id], order[#order + 1] = {}, id end
          local list = mouths[id]
          list[#list + 1] = {road = road, e = e, dist = dist, link = link, hw = math.max(.5, math.min(40, road.width or 7)) / 2}
        end
      end
    end
  end
  for index, id in ipairs(order) do
    if index % 32 == 0 and ctx.pause then ctx.pause() end
    local list = mouths[id]
    for i = 1, #list - 1 do
      for j = i + 1, #list do
        local a, b = list[i], list[j]
        local _, ax, ay = goreAt(a, 0)
        local _, bx, by = goreAt(b, 0)
        if (a.link or b.link) and not (a.link and b.link) and ax * bx + ay * by > GORE.angle then
          if a.link then a, b = b, a end         -- a: the main carriageway, b: the slip road
          local reach = math.min(GORE.reach, a.dist[#a.dist], b.dist[#b.dist])
          -- the side of a that b lies on, from where they have parted
          local probe = math.min(reach, 30)
          local pa, dax, day = goreAt(a, probe)
          local pb = goreAt(b, probe)
          local side = ((pb[1] - pa[1]) * -day + (pb[2] - pa[2]) * dax) >= 0 and 1 or -1
          local rows, started = {}, false
          for s = 0, reach, GORE.step do
            local p, dx, dy = goreAt(a, s)
            local nx, ny = -dy * side, dx * side
            local ea = {p[1] + nx * a.hw, p[2] + ny * a.hw, (p[3] or 0)}
            local q, ex, ey = goreAt(b, s)
            local mx, my = ey * side, -ex * side      -- b's normal towards a
            local eb = {q[1] + mx * b.hw, q[2] + my * b.hw, (q[3] or 0)}
            local gap = (eb[1] - ea[1]) * nx + (eb[2] - ea[2]) * ny
            if gap > GORE.start then
              started = true
              rows[#rows + 1] = {ea, eb, gap, s, nx, ny, dx, dy}
            elseif started then
              break                               -- they meet again: not a gore
            end
            if gap > GORE.wide then break end
          end
          if #rows >= 2 and rows[#rows][3] > GORE.wide * .6 then
            local material = ctx.material(a.road.tags or NONE)
            local z = ctx.lift - GORE.sink
            for k = 1, #rows - 1 do
              local r, t = rows[k], rows[k + 1]
              ctx.surface(material, {{r[1][1], r[1][2], r[1][3] + z}, {t[1][1], t[1][2], t[1][3] + z},
                {t[2][1], t[2][2], t[2][3] + z}, {r[2][1], r[2][2], r[2][3] + z}})
            end
            -- stripes: from a's edge at s to b's edge one gap further on, inside the margins
            local first, last = rows[1][4], rows[#rows][4]
            for s = first + GORE.every / 2, last - 1, GORE.every do
              local k = math.max(1, math.min(#rows, floor((s - first) / GORE.step) + 1))
              local r = rows[k]
              local far = math.min(#rows, k + math.max(1, floor(r[3] / GORE.step + .5)))
              local u = rows[far]
              local p0, p1 = r[1], u[2]
              local dx, dy = p1[1] - p0[1], p1[2] - p0[2]
              local l = math.sqrt(dx * dx + dy * dy)
              if l > 2 * GORE.margin + .5 then
                dx, dy = dx / l, dy / l
                local c = {(p0[1] + p1[1]) / 2, (p0[2] + p1[2]) / 2}
                paintQuad(ctx.mark, c, dx, dy, l - 2 * GORE.margin, GORE.stripe, p0[3] + ctx.markZ, p1[3] + ctx.markZ)
              end
            end
          end
        end
      end
    end
  end
end

-- Building rules in one table (build() is near LuaJIT's 60 upvalues).
local BLD = {floor = 3.1, plinth = .35, guessed = 9, door = {bay = 3.1, width = 2.5, height = 2.2, out = .02}}
-- Outbuildings' heights, and the uses that are houses.
BLD.low = {garage = 2.7, garages = 2.7, shed = 2.4, carport = 2.4, kiosk = 2.7, hut = 2.6, cabin = 3.1,
  toilets = 2.7, greenhouse = 2.6, roof = 3.5, stable = 4.5, cowshed = 5, barn = 6, farm_auxiliary = 4}
BLD.houses = {house = true, detached = true, semidetached_house = true, bungalow = true, terrace = true,
  farm = true}
BLD.shops = {industrial = true, warehouse = true, factory = true, commercial = true, retail = true, service = true}

-- A building's height. The pack writes 3 floors x 3 m where OSM has no height or levels
-- (build_country.py): every house of a village stood 9 m tall under a flat roof (bld-hatne-01,
-- 377 of Hatne's 392 buildings). Such a guess is made again from the use and the footprint:
-- outbuildings by use, small houses one floor (a quarter of the 140-260 m2 ones two), 260-450
-- m2 two floors, small shops and workshops one tall floor; anything bigger keeps the pack's.
function BLD.height(building, tags, area, h)
  local height = building.height or number(tags.height, number(tags['building:levels'], 3) * 3)
  if tags.height or tags['building:levels'] or height ~= BLD.guessed then return height end
  local b = tags.building or 'yes'
  if BLD.low[b] then return BLD.low[b] end
  if b == 'yes' or b == 'residential' or BLD.houses[b] then
    if area < 30 and not BLD.houses[b] then return 2.6 end
    if area < 140 then return BLD.floor end
    if area < 260 then return h % 4 == 0 and 2 * BLD.floor or BLD.floor end
    if area < 450 then return 2 * BLD.floor end
  elseif BLD.shops[b] and area < 300 then
    return 4
  end
  return height
end

-- Post-Soviet roofs: asbestos-cement slate and painted metal tile, some profiled sheet and clay.
-- By the look's block, or for a pack built before looks by its country (looks.py 'postsoviet').
BLD.postsoviet = {ukraine = true, belarus = true, moldova = true, russia = true, georgia = true,
  armenia = true, azerbaijan = true, kazakhstan = true, uzbekistan = true, kyrgyzstan = true,
  tajikistan = true, turkmenistan = true, estonia = true, latvia = true, lithuania = true,
  romania = true, bulgaria = true}
BLD.mix = {'roof_sheet', 'roof_sheet', 'roof_sheet', 'roof_sheet', 'roof_sheet', 'roof_sheet', 'roof_sheet',
  'roof_mtile_red', 'roof_mtile_red', 'roof_mtile_red', 'roof_mtile_red', 'roof_mtile_brown',
  'roof_mtile_brown', 'roof_mtile_brown', 'roof_mtile_green', 'roof_mtile_green', 'roof_metal',
  'roof_metal', 'roof_tile', 'roof_tile'}
BLD.colour = {red = 'roof_mtile_red', darkred = 'roof_mtile_red', maroon = 'roof_mtile_red',
  brown = 'roof_mtile_brown', saddlebrown = 'roof_mtile_brown', green = 'roof_mtile_green',
  darkgreen = 'roof_mtile_green', grey = 'roof_sheet', gray = 'roof_sheet', lightgrey = 'roof_sheet',
  white = 'roof_sheet', silver = 'roof_metal'}
-- metres per texture repeat on a pitched roof (u along the ridge, v down the slope)
BLD.repeats = {roof_tile = 2, roof_metal = 2, roof_sheet = 1.75, roof_mtile_red = 1.4,
  roof_mtile_brown = 1.4, roof_mtile_green = 1.4}

function BLD.roof(tags, h, postsoviet)
  local m, colour = tags['roof:material'], BLD.colour[tostring(tags['roof:colour'] or ''):lower()]
  if m == 'metal' or m == 'tin' or m == 'metal_sheet' then
    return colour and colour:find('mtile', 1, true) and colour or 'roof_metal'
  end
  if m == 'roof_tiles' or m == 'tile' or m == 'clay' then return 'roof_tile' end
  if m == 'eternit' or m == 'asbestos' or (m == 'slate' and postsoviet) then return 'roof_sheet' end
  if colour then return colour end
  if postsoviet then return BLD.mix[math.floor(h / 13) % #BLD.mix + 1] end
  return 'roof_tile'
end

-- Houses of one or two floors: a plain wall from the game's tileable set, and the windows and a
-- door as their own quads from its atlases (fast_style HOUSE_WALLS). The photo facades gave every
-- house of a village the same plaster and the same window rhythm (bld-hatne-05).
BLD.homes = {yes = true, house = true, detached = true, semidetached_house = true, bungalow = true,
  terrace = true, residential = true, farm = true, cabin = true}
-- by h % 100. Plaster stays under 38; the rest is brick, stone, silicate, siding and boards.
BLD.walls = {{10, 'hw_white'}, {17, 'hw_yellow'}, {23, 'hw_blue'}, {28, 'hw_green'}, {31, 'hw_pink'},
  {38, 'hw_aged'}, {48, 'hw_brick_red'}, {56, 'hw_oldbrick'}, {64, 'hw_flatbrick'}, {72, 'hw_stone'},
  {80, 'hw_silicate'}, {90, 'hw_siding'}, {100, 'hw_boards'}}
BLD.wallColour = {white = 'hw_white', ivory = 'hw_white', cream = 'hw_aged', beige = 'hw_aged', yellow = 'hw_yellow',
  orange = 'hw_yellow', blue = 'hw_blue', lightblue = 'hw_blue', green = 'hw_green', lightgreen = 'hw_green',
  pink = 'hw_pink', red = 'hw_brick_red', brown = 'hw_brick_red', grey = 'hw_silicate', gray = 'hw_silicate'}
-- metres per texture repeat on a house wall. Big flat bricks and stone courses are wider than a plaster repeat.
BLD.wallScale = {hw_brick_red = 1.6, hw_oldbrick = 1.6, hw_flatbrick = 2.4, hw_stone = 2,
  hw_silicate = 1.6, hw_siding = 1.2, hw_boards = 1.2, hw_wood = 2}
-- atlas cells {u0, v0, u1, v1} (v0 at the image's top) and the opening's size in metres
BLD.windows = {
  win_pvc = {w = 1.15, h = 1.5, cells = {{.441, .002, .641, .264}, {.644, .002, .846, .264},
    {.442, .27, .640, .545}, {.643, .27, .840, .545}}},
  win_wood = {w = 1.0, h = 1.55, cells = {{.013, .025, .134, .215}, {.139, .025, .260, .214},
    {.264, .025, .386, .214}, {.632, .116, .753, .306}, {.503, .307, .624, .496}, {.629, .308, .751, .5}}}}
BLD.doors = {w = 1.0, h = 2.05, cells = {{0, 0, .25, .5}, {.252, 0, .498, .5}, {.752, 0, 1, .5}}}

function BLD.house(tags, height, h)
  if height >= 8 or not BLD.homes[tags.building or 'yes'] then return nil end
  local m = tostring(tags['building:material'] or tags['facade:material'] or '')
  if m == 'panel' or m == 'concrete' or m == 'reinforced_concrete' or m == 'glass' or m == 'metal' then return nil end
  local colour = BLD.wallColour[(tostring(tags['building:colour'] or ''):lower():gsub('[%s_]', ''))]
  if m == 'brick' then
    if colour == 'hw_white' or colour == 'hw_silicate' then return 'hw_silicate' end
    if h % 5 == 0 then return 'hw_oldbrick' end
    if h % 5 == 1 then return 'hw_flatbrick' end
    return 'hw_brick_red'
  end
  if m == 'stone' or m == 'masonry' then return 'hw_stone' end
  if m == 'wood' or m == 'timber_framing' or m == 'log' then
    local n = h % 3
    if n == 0 then return 'hw_siding' end
    if n == 1 then return 'hw_boards' end
    return 'hw_wood'
  end
  if colour and (m == 'plaster' or m == 'stucco' or m == '') then return colour end
  local plaster = m == 'plaster' or m == 'stucco'
  for _, w in ipairs(BLD.walls) do
    if h % 100 < w[1] then
      if plaster and w[1] > 38 then return 'hw_white' end   -- tagged plaster: not brick, stone or wood
      return w[2]
    end
  end
  return 'hw_white'
end

-- One house's openings: its window style and cell, door cell, plinth, gable and roof guesses.
function BLD.dress(kind, h)
  local old = kind == 'hw_wood' or kind == 'hw_aged' or kind == 'hw_blue' or kind == 'hw_green'
    or kind == 'hw_oldbrick' or kind == 'hw_flatbrick' or kind == 'hw_stone' or kind == 'hw_boards'
  local win = (old and h % 10 < 8 or not old and h % 10 < 4) and 'win_wood' or 'win_pvc'
  local cells = BLD.windows[win].cells
  return {win = win, cell = cells[math.floor(h / 11) % #cells + 1],
    door = BLD.doors.cells[math.floor(h / 17) % #BLD.doors.cells + 1],
    plinth = (h % 20 < 7) and 'plinth_brown' or 'plinth',
    gable = (kind == 'hw_siding' or kind == 'hw_wood' or kind == 'hw_boards' or math.floor(h / 3) % 3 ~= 0) and kind or 'gable',
    shape = math.floor(h / 23) % 20 < 9 and 'hipped' or 'gabled', pitch = 26 + math.floor(h / 29) % 13}
end

-- Bays along a wall. Balanced and above keep a window about every 2.9 m (at most 8).
-- Low steps them out; Potato keeps a single bay. Far tiles never call this.
function BLD.bays(length, detail)
  if length < 2.4 then return 0 end
  local step, cap = 2.9, 8
  if detail and detail <= 15 then step, cap = 5.4, 1
  elseif detail and detail < 40 then step, cap = 4.2, 4 end
  return math.min(cap, math.max(1, math.floor((length - .8) / step)))
end

-- Large house parts (porch, cornice, balcony, chimney) from detail 40 up. Potato and Low
-- keep the walls, the roof and a thinned run of windows.
function BLD.mass(detail)
  return not (detail and detail < 40)
end

-- The door's bay: the last one on a hipped house, the first otherwise. One bay is the door.
function BLD.slot(n, shape)
  if n > 1 and shape == 'hipped' then return n end
  return 1
end

-- Windows on every floor of an outer wall a -> b (inside on its left), evenly spaced, 3 cm out;
-- the door in one slot of the door wall's ground floor.
function BLD.openings(scene, a, b, length, base, height, dress, door, detail)
  local n = BLD.bays(length, detail)
  if n == 0 then return end
  local style = BLD.windows[dress.win]
  local dx, dy = (b[1] - a[1]) / length, (b[2] - a[2]) / length
  local ox, oy = dy * .03, -dx * .03
  local function quad(kind, s, w, z0, z1, cell)
    local s0, s1 = s - w / 2, s + w / 2
    scene.polygon(kind, {{a[1] + dx * s0 + ox, a[2] + dy * s0 + oy, z0, cell[1], cell[4]},
      {a[1] + dx * s1 + ox, a[2] + dy * s1 + oy, z0, cell[3], cell[4]},
      {a[1] + dx * s1 + ox, a[2] + dy * s1 + oy, z1, cell[3], cell[2]},
      {a[1] + dx * s0 + ox, a[2] + dy * s0 + oy, z1, cell[1], cell[2]}}, false)
  end
  local floors = math.max(1, math.floor((height + .3) / BLD.floor))
  local doorSlot = door and BLD.slot(n, dress.shape)
  for f = 0, floors - 1 do
    local z0 = base + f * BLD.floor + .85
    if z0 + style.h > base + height - .15 then break end
    for i = 1, n do
      local s = (i - .5) * length / n
      if f == 0 and i == doorSlot then
        quad('door_house', s, BLD.doors.w, base + .1, base + .1 + BLD.doors.h, dress.door)
      else
        quad(dress.win, s, style.w, z0, z0 + style.h, dress.cell)
      end
    end
  end
end

local function wallMaterial(building, look, height)
  local tags = building.tags or {}
  local h = hash(tostring(building.id or ''))
  height = height or building.height or number(tags.height, number(tags['building:levels'], 3) * 3)
  local material = tags['building:material'] or tags['facade:material']
  local b = tags.building
  look = type(look) == 'table' and look or NONE
  -- garages: blank cement walls between the doors (the block facade has windows)
  if b == 'garages' or b == 'garage' then return 'plinth' end
  -- sheds in rusty corrugated tin, warehouses half clad in metal sheet
  if b == 'shed' then return h % 2 == 0 and 'clad_tin' or 'wall_block' end
  if b == 'industrial' or b == 'warehouse' or b == 'factory' then return h % 2 == 0 and 'clad_metal' or 'wall_block' end
  local house = BLD.house(tags, height, h)
  if house then return house end
  if material == 'glass' or b == 'office' or b == 'commercial' or b == 'retail' or b == 'hotel' or tags.office then
    local family = height > 20 and {'off_blue', 'off_green', 'off_grey', 'off_ribbon'} or {'off_ribbon', 'off_ribbon_dark'}
    return 'wall_' .. family[h % #family + 1]
  end
  local panel = {'pnl_grey', 'pnl_beige', 'pnl_pink', 'pnl_blue', 'pnl_white'}
  local loggia = {'lgg_cream', 'lgg_grey', 'lgg_pink'}
  local brick = {'brk_red', 'brk_white'}
  local plaster = {'pls_yellow', 'pls_cream', 'pls_peach', 'pls_green', 'pls_blue', 'pls_grey'}
  local family
  if material == 'brick' then family = brick
  elseif material == 'panel' or material == 'concrete' or material == 'reinforced_concrete' then family = height >= 26 and h % 3 ~= 0 and loggia or panel
  elseif material == 'plaster' or material == 'stucco' then family = plaster
  elseif height < 8 then family = h % 5 < 3 and plaster or brick   -- a house is not a panel block
  elseif look.buildings == 'panel' then family = height >= 26 and (h % 3 ~= 0 and loggia or panel) or panel
  elseif look.buildings == 'brick' then family = brick
  elseif look.buildings == 'plaster' then family = plaster
  elseif height >= 26 then family = h % 9 < 4 and loggia or panel
  elseif height >= 14 then family = h % 20 < 8 and panel or h % 20 < 15 and brick or plaster
  else family = h % 5 < 3 and plaster or brick end
  return 'wall_' .. family[math.floor(h / 7) % #family + 1]
end

local function facadeScale(kind)
  if kind:find('_end$', 1) then return 6 end
  if kind:find('door_', 1, true) == 1 or kind:find('clad_', 1, true) == 1 or kind == 'plinth' then return 3 end
  if kind == 'gable' then return 1.5 end
  if kind:find('hw_', 1, true) == 1 then return BLD.wallScale[kind] or 3 end
  if kind:find('wall_lgg_', 1, true) == 1 then return 33 end
  if kind:find('wall_pnl_', 1, true) == 1 then return 12 end
  if kind == 'wall_block' then return 3 end
  return 6
end

local function footprintFrame(ring)
  local ax, ay, longest, area = 1, 0, 0, 0
  for index, p in ipairs(ring) do
    local q = ring[index % #ring + 1]
    local dx, dy = q[1] - p[1], q[2] - p[2]
    local length = math.sqrt(dx * dx + dy * dy)
    if length > longest then ax, ay, longest = dx / length, dy / length, length end
    area = area + p[1] * q[2] - q[1] * p[2]
  end
  local bx, by = -ay, ax
  local u0, v0, u1, v1 = math.huge, math.huge, -math.huge, -math.huge
  for _, p in ipairs(ring) do
    local u, v = p[1] * ax + p[2] * ay, p[1] * bx + p[2] * by
    u0, v0, u1, v1 = math.min(u0, u), math.min(v0, v), math.max(u1, u), math.max(v1, v)
  end
  if u1 - u0 < v1 - v0 then ax, ay, bx, by, u0, v0, u1, v1 = bx, by, -ax, -ay, v0, -u1, v1, -u0 end
  return {ax = ax, ay = ay, bx = bx, by = by, u0 = u0, v0 = v0, u1 = u1, v1 = v1, area = math.abs(area) / 2}
end

-- A point on wall a -> b, `out` metres to the outside (the ring's inside is on the left).
local function wallPoint(a, b, length, s, out, z, u, v)
  local dx, dy = (b[1] - a[1]) / length, (b[2] - a[2]) / length
  return {a[1] + dx * s + dy * out, a[2] + dy * s - dx * out, z, u, v}
end

-- Board band under the eaves, 7 cm out from the wall. One quad a wall.
function BLD.cornice(scene, a, b, length, top)
  local z0, z1, e = top - .2, top + .04, .07
  scene.polygon('gable', {wallPoint(a, b, length, -e, e, z0, 0, 0),
    wallPoint(a, b, length, length + e, e, z0, (length + 2 * e) / 1.5, 0),
    wallPoint(a, b, length, length + e, e, z1, (length + 2 * e) / 1.5, .16),
    wallPoint(a, b, length, -e, e, z1, 0, .16)}, false)
end

-- A canopy over the door, sloping down toward the street. The boards face downward
-- (gable is single sided) and a lip marks the outer edge. Above a car, so it stays
-- off the collision list only by sharing nothing solid at bumper height: the lip
-- is at the door head.
function BLD.porch(scene, a, b, length, base, dress, detail)
  local n = BLD.bays(length, detail)
  if n == 0 then return end
  local slot = BLD.slot(n, dress.shape)
  local s = (slot - .5) * length / n
  local s0, s1 = s - .9, s + .9
  local head = base + .1 + BLD.doors.h + .06
  local zOut = head - .28
  -- normal points down: seen from the yard
  scene.polygon('gable', {wallPoint(a, b, length, s0, .05, head, 0, 0),
    wallPoint(a, b, length, s1, .05, head, 1, 0),
    wallPoint(a, b, length, s1, .85, zOut, 1, 1),
    wallPoint(a, b, length, s0, .85, zOut, 0, 1)}, false)
  scene.polygon('gable', {wallPoint(a, b, length, s0, .85, zOut - .12, 0, 0),
    wallPoint(a, b, length, s1, .85, zOut - .12, 1, 0),
    wallPoint(a, b, length, s1, .85, zOut, 1, .12),
    wallPoint(a, b, length, s0, .85, zOut, 0, .12)}, false)
end

-- One wooden balcony on a two-storey house: a slab and a rail, not a balcony per window.
function BLD.balcony(scene, a, b, length, base, h)
  if length < 5 then return end
  local w = 2.1
  local s = math.max(w / 2 + .4, math.min(length - w / 2 - .4, length * (.28 + (h % 3) * .18)))
  local s0, s1 = s - w / 2, s + w / 2
  local z = base + BLD.floor
  scene.polygon('gable', {wallPoint(a, b, length, s0, .05, z + .08, 0, 0),
    wallPoint(a, b, length, s1, .05, z + .08, 1, 0),
    wallPoint(a, b, length, s1, .82, z + .08, 1, 1),
    wallPoint(a, b, length, s0, .82, z + .08, 0, 1)}, true)
  scene.polygon('gable', {wallPoint(a, b, length, s0, .82, z, 0, 0),
    wallPoint(a, b, length, s1, .82, z, 1, 0),
    wallPoint(a, b, length, s1, .82, z + .08, 1, .08),
    wallPoint(a, b, length, s0, .82, z + .08, 0, .08)}, false)
  scene.polygon('gable', {wallPoint(a, b, length, s0, .82, z + .08, 0, 0),
    wallPoint(a, b, length, s1, .82, z + .08, 1, 0),
    wallPoint(a, b, length, s1, .82, z + .92, 1, .7),
    wallPoint(a, b, length, s0, .82, z + .92, 0, .7)}, false)
end

-- Brick shaft on the ridge. Ten triangles, one mesh per tile, no collision (collision.lua).
function BLD.chimney(scene, ring, top, dress, h, tags)
  local frame = footprintFrame(cleanRing(ring))
  local length, width = frame.u1 - frame.u0, frame.v1 - frame.v0
  if width < 3 or length < 4 then return end
  local pitch = dress.pitch or 32
  local rise = math.max(.5, math.min(10, number(tags['roof:height'], math.min(6, width / 2 * math.tan(math.rad(pitch))))))
  local inset = 0
  local shape = dress.shape
  if shape == 'hipped' or shape == 'half-hipped' or shape == 'pyramidal' then inset = math.min(width / 2, length / 2) end
  if shape == 'pyramidal' then inset = length / 2 end
  local r0, r1 = frame.u0 + inset, frame.u1 - inset
  if r1 - r0 < .9 then return end
  local along = r0 + (r1 - r0) * (.32 + (h % 5) * .08)
  along = math.max(r0 + .35, math.min(r1 - .35, along))
  local mid = (frame.v0 + frame.v1) / 2
  local ridge = top + rise
  local s = .24
  local z0, z1 = ridge - .5, ridge + 1.05
  local function p(u, v, z, uu, vv)
    return {u * frame.ax + v * frame.bx, u * frame.ay + v * frame.by, z, uu, vv}
  end
  local u0, u1, v0, v1 = along - s, along + s, mid - s, mid + s
  -- each face: bottom edge with the outside on the right of its direction, then up
  scene.polygon('chimney', {p(u0, v0, z0, 0, 0), p(u1, v0, z0, 1, 0), p(u1, v0, z1, 1, 1), p(u0, v0, z1, 0, 1)}, false)
  scene.polygon('chimney', {p(u1, v1, z0, 0, 0), p(u0, v1, z0, 1, 0), p(u0, v1, z1, 1, 1), p(u1, v1, z1, 0, 1)}, false)
  scene.polygon('chimney', {p(u1, v0, z0, 0, 0), p(u1, v1, z0, 1, 0), p(u1, v1, z1, 1, 1), p(u1, v0, z1, 0, 1)}, false)
  scene.polygon('chimney', {p(u0, v1, z0, 0, 0), p(u0, v0, z0, 1, 0), p(u0, v0, z1, 1, 1), p(u0, v1, z1, 0, 1)}, false)
  scene.polygon('chimney', {p(u0, v0, z1, 0, 0), p(u1, v0, z1, 1, 0), p(u1, v1, z1, 1, 1), p(u0, v1, z1, 0, 1)}, true)
end

-- A city block (flat-roofed, not a house and not a shed). Houses keep BLD.cornice and the chimney.
function BLD.block(use, height)
  if height < 8 or BLD.low[use or ''] then return false end
  return true
end

-- Concrete course 4 cm in front of a photo facade. The wall quad keeps its own UVs, so the
-- ground floor of a panel stays where the photograph put it.
function BLD.socle(scene, a, b, length, bottom, base)
  local z0 = math.max(bottom, base - .05)
  local z1 = z0 + .28
  scene.polygon('plinth', {wallPoint(a, b, length, 0, .04, z0, 0, 0),
    wallPoint(a, b, length, length, .04, z0, length / 3, 0),
    wallPoint(a, b, length, length, .04, z1, length / 3, .1),
    wallPoint(a, b, length, 0, .04, z1, 0, .1)}, false)
end

-- Same winding as the wall loop: outer CCW faces the street, a clockwise court faces the yard.
function BLD.orient(raw, rings)
  local ring, signed = cleanRing(raw), 0
  for k, p in ipairs(ring) do
    local q = ring[k % #ring + 1]
    signed = signed + p[1] * q[2] - q[1] * p[2]
  end
  if (raw == rings[1] and signed < 0) or (raw ~= rings[1] and signed > 0) then
    local reversed = {}
    for k = #ring, 1, -1 do reversed[#reversed + 1] = ring[k] end
    ring = reversed
  end
  return ring
end

-- Rim of a flat roof: a face 5 cm outside the wall and a coping across it. Outer ring only,
-- and only edges long enough to read from the street. A court and a short jog would push a
-- dense tile past PIECE_TRIS (2500) and split e2rf_parapet into extra first-frame draws.
function BLD.parapets(scene, rings, top, height, h)
  local rim = (height >= 40 and 1.05 or height >= 16 and .7 or .42) + (h % 4) * .03
  local out, cap = .05, .12
  local raw = rings[1]
  if raw then
    local ring = BLD.orient(raw, rings)
    for k, a in ipairs(ring) do
      local b = ring[k % #ring + 1]
      local length = math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2)
      if length > 6 then
        scene.polygon('parapet', {wallPoint(a, b, length, 0, out, top, 0, 0),
          wallPoint(a, b, length, length, out, top, length / 3, 0),
          wallPoint(a, b, length, length, out, top + rim, length / 3, rim / 3),
          wallPoint(a, b, length, 0, out, top + rim, 0, rim / 3)}, false)
        scene.polygon('parapet', {wallPoint(a, b, length, 0, out - cap, top + rim, 0, 0),
          wallPoint(a, b, length, length, out - cap, top + rim, length / 3, 0),
          wallPoint(a, b, length, length, out, top + rim, length / 3, cap / 3),
          wallPoint(a, b, length, 0, out, top + rim, 0, cap / 3)}, true)
      end
    end
  end
end

-- Stair and machine bulkhead on the flat roof. Skipped when the box would leave the mass
-- (a courtyard hole or the missing corner of an L). A tall block may add a smaller vent.
function BLD.crown(scene, rings, top, height, h, area)
  if height < 9 or area < 180 then return end
  local ring = cleanRing(rings[1])
  if #ring < 3 then return end
  local frame = footprintFrame(ring)
  local length, width = frame.u1 - frame.u0, frame.v1 - frame.v0
  if width < 7 or length < 9 then return end
  local function world(u, v)
    return u * frame.ax + v * frame.bx, u * frame.ay + v * frame.by
  end
  local function fits(u, v, du, dv)
    if u - du / 2 < frame.u0 + .8 or u + du / 2 > frame.u1 - .8 then return false end
    if v - dv / 2 < frame.v0 + .8 or v + dv / 2 > frame.v1 - .8 then return false end
    for _, corner in ipairs({{-1, -1}, {1, -1}, {1, 1}, {-1, 1}, {0, 0}}) do
      local x, y = world(u + corner[1] * (du / 2 - .3), v + corner[2] * (dv / 2 - .3))
      if not inside(rings, x, y) then return false end
    end
    return true
  end
  local function place(du, dv, avoid)
    if du > length - 2.4 or dv > width - 2 then return nil end
    local uSteps = math.max(1, math.floor((length - du - 1.6) / 4))
    local vSteps = math.max(1, math.floor((width - dv - 1.6) / 3.5))
    local span = uSteps * vSteps
    local u0 = frame.u0 + du / 2 + .9
    local v0 = frame.v0 + dv / 2 + .9
    local start = h % span
    for n = 0, math.min(16, span) - 1 do
      local k = (start + n) % span
      local iu, iv = k % uSteps, math.floor(k / uSteps)
      local u = u0 + (uSteps == 1 and 0 or iu * (length - du - 1.8) / (uSteps - 1))
      local v = v0 + (vSteps == 1 and 0 or iv * (width - dv - 1.8) / (vSteps - 1))
      local hit = avoid and math.abs(u - avoid[1]) < (du + avoid[3]) / 2 + 1.4
        and math.abs(v - avoid[2]) < (dv + avoid[4]) / 2 + 1.4
      if not hit and fits(u, v, du, dv) then return u, v end
    end
  end
  local function box(cx, cy, du, dv, rise)
    local u0, u1 = cx - du / 2, cx + du / 2
    local v0, v1 = cy - dv / 2, cy + dv / 2
    local z0, z1 = top + .02, top + .02 + rise
    local function p(u, v, z, uu, vv)
      return {u * frame.ax + v * frame.bx, u * frame.ay + v * frame.by, z, uu, vv}
    end
    scene.polygon('parapet', {p(u0, v0, z0, 0, 0), p(u1, v0, z0, 1, 0), p(u1, v0, z1, 1, 1), p(u0, v0, z1, 0, 1)}, false)
    scene.polygon('parapet', {p(u1, v1, z0, 0, 0), p(u0, v1, z0, 1, 0), p(u0, v1, z1, 1, 1), p(u1, v1, z1, 0, 1)}, false)
    scene.polygon('parapet', {p(u1, v0, z0, 0, 0), p(u1, v1, z0, 1, 0), p(u1, v1, z1, 1, 1), p(u1, v0, z1, 0, 1)}, false)
    scene.polygon('parapet', {p(u0, v1, z0, 0, 0), p(u0, v0, z0, 1, 0), p(u0, v0, z1, 1, 1), p(u0, v1, z1, 0, 1)}, false)
    scene.polygon('parapet', {p(u0, v0, z1, 0, 0), p(u1, v0, z1, 1, 0), p(u1, v1, z1, 1, 1), p(u0, v1, z1, 0, 1)}, true)
  end
  local du = height >= 40 and 7.2 or height >= 16 and 5 or 3.6
  local dv = height >= 40 and 5.2 or height >= 16 and 3.4 or 2.6
  local rise = height >= 40 and 3.1 or height >= 16 and 2.3 or 1.65
  local u, v = place(du, dv, nil)
  if not u then return end
  box(u, v, du, dv, rise)
  if height >= 26 and area >= 400 then
    local vu, vv = place(2.4, 1.8, {u, v, du, dv})
    if vu then box(vu, vv, 2.4, 1.8, 1.35) end
  end
end

-- Roof clutter of a flat-roofed block (options.experimentalDetail): two rows of ventilation
-- shafts along the roof's long axis, a shaft every `step` m at `chance`, and a few television
-- antennas (a mast with two cross bars) on blocks of five floors and more. Every box must lie
-- on the roof (the crown's test); the bulkheads of BLD.crown are kept clear.
BLD.ROOF = {step = 6, chance = .7, shaft = {.7, .7, .9}, rows = 2.2, antennas = 3, mast = 3.2}
function BLD.roofClutter(scene, rings, top, height, h)
  local R = BLD.ROOF
  local ring = cleanRing(rings[1])
  if #ring < 3 or height < 8 then return 0 end
  local frame = footprintFrame(ring)
  local length, width = frame.u1 - frame.u0, frame.v1 - frame.v0
  if width < 7 or length < 9 then return 0 end
  local function world(u, v) return u * frame.ax + v * frame.bx, u * frame.ay + v * frame.by end
  local function fits(u, v, du, dv)
    for _, c in ipairs({{-1, -1}, {1, -1}, {1, 1}, {-1, 1}}) do
      local x, y = world(u + c[1] * (du / 2 + .4), v + c[2] * (dv / 2 + .4))
      if not inside(rings, x, y) then return false end
    end
    return true
  end
  local function box(kind, cu, cv, du, dv, z0, z1)
    local u0, u1, v0, v1 = cu - du / 2, cu + du / 2, cv - dv / 2, cv + dv / 2
    local function p(u, v, z, uu, vv)
      local x, y = world(u, v)
      return {x, y, z, uu, vv}
    end
    local rise = z1 - z0
    scene.polygon(kind, {p(u0, v0, z0, 0, 0), p(u1, v0, z0, du, 0), p(u1, v0, z1, du, rise), p(u0, v0, z1, 0, rise)}, false)
    scene.polygon(kind, {p(u1, v1, z0, 0, 0), p(u0, v1, z0, du, 0), p(u0, v1, z1, du, rise), p(u1, v1, z1, 0, rise)}, false)
    scene.polygon(kind, {p(u1, v0, z0, 0, 0), p(u1, v1, z0, dv, 0), p(u1, v1, z1, dv, rise), p(u1, v0, z1, 0, rise)}, false)
    scene.polygon(kind, {p(u0, v1, z0, 0, 0), p(u0, v0, z0, dv, 0), p(u0, v0, z1, dv, rise), p(u0, v1, z1, 0, rise)}, false)
    scene.polygon(kind, {p(u0, v0, z1, 0, 0), p(u1, v0, z1, du, 0), p(u1, v1, z1, du, dv), p(u0, v1, z1, 0, dv)}, true)
  end
  -- the crown's bulkheads sit near the middle of the long axis: leave the middle 8 m
  local mid, n = (frame.u0 + frame.u1) / 2, 0
  local cv = (frame.v0 + frame.v1) / 2
  local du, dv, rise = R.shaft[1], R.shaft[2], R.shaft[3]
  for k = 0, math.floor((length - 2) / R.step) do
    local u = frame.u0 + 1 + k * R.step + R.step / 2
    if math.abs(u - mid) > 4 and u < frame.u1 - 1 then
      for side = -1, 1, 2 do
        local v = cv + side * R.rows
        if ihash(h, k, side + 2, 83) % 1000 < R.chance * 1000 and fits(u, v, du, dv) then
          box('parapet', u, v, du, dv, top, top + rise)
          n = n + 1
        end
      end
    end
  end
  if height >= 14 then
    for a = 1, R.antennas do
      if ihash(h, a, 0, 89) % 3 ~= 0 then
        local u = frame.u0 + 2 + (ihash(h, a, 1, 89) % 1000) / 1000 * math.max(0, length - 4)
        local v = cv + ((ihash(h, a, 2, 89) % 1000) / 1000 - .5) * math.max(0, width - 4)
        if math.abs(u - mid) > 4.5 and fits(u, v, .3, .3) then
          box('pipe', u, v, .05, .05, top, top + R.mast)
          box('pipe', u, v, 1.6, .03, top + R.mast - .5, top + R.mast - .46)
          box('pipe', u, v, 1.1, .03, top + R.mast - .15, top + R.mast - .11)
          n = n + 1
        end
      end
    end
  end
  return n
end

local function segDistance(x, y, a, b)
  local dx, dy = b[1] - a[1], b[2] - a[2]
  local len2 = dx * dx + dy * dy
  local t = len2 > EPS and math.max(0, math.min(1, ((x - a[1]) * dx + (y - a[2]) * dy) / len2)) or 0
  return math.sqrt((a[1] + t * dx - x) ^ 2 + (a[2] + t * dy - y) ^ 2), t * math.sqrt(len2)
end

-- Address plates (options.experimentalDetail): a building's real addr:housenumber, and its
-- addr:street shortened, white on a dark blue plate by the left corner of the wall that faces
-- that street (the nearest segment of a road of that name within `reach` m). Without a road
-- of that name near, no plate: a guess of the wall would put the number on the yard.
-- Letters are cells of the glyph atlas (fast_style.GLYPHS, the same string), a monospace font.
BLD.GLYPHS = '0123456789/-.,\'’№ ()АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯабвгґдеєжзиіїйклмнопрстуфхцчшщьюяЁЭЪЫёэъыABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
BLD.PLATE = {reach = 45, number = .26, street = .11, aspect = .6, pad = .07, z = 2.7, perRow = 16,
  short = {{'вулиця ', 'вул. '}, {'проспект ', 'просп. '}, {'провулок ', 'пров. '}, {'бульвар ', 'бульв. '},
    {'площа ', 'пл. '}, {'узвіз ', 'узв. '}, {'набережна ', 'наб. '}, {' вулиця', ''}, {' провулок', ' пров.'}}}
local glyphIndex
function BLD.glyphs(text)
  if not glyphIndex then
    glyphIndex = {}
    local k = 0
    for ch in BLD.GLYPHS:gmatch('[%z\1-\127\194-\244][\128-\191]*') do glyphIndex[ch], k = k, k + 1 end
  end
  -- a space keeps its place but draws nothing (its cell would show its neighbours' mips)
  local out = {}
  for ch in tostring(text):gmatch('[%z\1-\127\194-\244][\128-\191]*') do
    out[#out + 1] = ch ~= ' ' and glyphIndex[ch] or -1
  end
  return out
end

function BLD.streetLabel(name)
  local s = ' ' .. tostring(name) .. ' '
  for _, pair in ipairs(BLD.PLATE.short) do
    local a, b = pair[1], pair[2]
    local i = s:lower():find(a, 1, true)
    if i then s = s:sub(1, i - 1) .. b .. s:sub(i + #a) end
  end
  return (s:gsub('^%s+', ''):gsub('%s+$', ''))
end

function BLD.addressPlate(scene, rings, tags, base, height, roads)
  local P = BLD.PLATE
  local number, street = tags['addr:housenumber'], tags['addr:street']
  if not number or not street or not roads then return false end
  local ring = BLD.orient(rings[1], rings)
  local best
  for k, a in ipairs(ring) do
    local b = ring[k % #ring + 1]
    local dx, dy = b[1] - a[1], b[2] - a[2]
    local len = math.sqrt(dx * dx + dy * dy)
    if len >= 3 then
      local mx, my, nx, ny = (a[1] + b[1]) / 2, (a[2] + b[2]) / 2, dy / len, -dx / len
      for _, road in ipairs(roads) do
        if (road.tags or NONE).name == street then
          local pts = road.points or NONE
          for q = 1, #pts - 1 do
            local d, t = segDistance(mx, my, pts[q], pts[q + 1])
            if d <= P.reach then
              local f = t / math.max(EPS, math.sqrt((pts[q + 1][1] - pts[q][1]) ^ 2 + (pts[q + 1][2] - pts[q][2]) ^ 2))
              local px, py = pts[q][1] + (pts[q + 1][1] - pts[q][1]) * f, pts[q][2] + (pts[q + 1][2] - pts[q][2]) * f
              if (px - mx) * nx + (py - my) * ny > 0 and (not best or d < best.d) then
                best = {a = a, b = b, len = len, d = d}
              end
            end
          end
        end
      end
    end
  end
  if not best then return false end
  local label = BLD.glyphs(BLD.streetLabel(street))
  local digits = BLD.glyphs(number)
  local w1, w2 = #digits * P.number * P.aspect, #label * P.street * P.aspect
  local width = math.max(w1, w2) + 2 * P.pad
  if width > best.len - .6 then return false end
  local z0 = base + math.min(P.z, math.max(1.6, height - 1.2))
  local hgt = P.number + P.street + 3 * P.pad
  local a, b, len = best.a, best.b, best.len
  local s0 = .4
  scene.polygon('plate', {wallPoint(a, b, len, s0, .025, z0, 0, 0), wallPoint(a, b, len, s0 + width, .025, z0, 1, 0),
    wallPoint(a, b, len, s0 + width, .025, z0 + hgt, 1, 1), wallPoint(a, b, len, s0, .025, z0 + hgt, 0, 1)}, false)
  local function line(chars, size, zb, total)
    local cw = size * P.aspect
    local start = s0 + (width - total) / 2
    for i, g in ipairs(chars) do
      if g >= 0 then
        local col, row = g % P.perRow, math.floor(g / P.perRow)
        local u0, u1 = col / P.perRow, (col + 1) / P.perRow
        local v0, v1 = 1 - (row + 1) / P.perRow, 1 - row / P.perRow
        local c0 = start + (i - 1) * cw
        -- a cell is square: the letter's height is the cell's, its advance `aspect` of it
        local pad = (size - cw) / 2
        scene.polygon('glyphs', {wallPoint(a, b, len, c0 - pad, .035, zb, u0, v0),
          wallPoint(a, b, len, c0 + cw + pad, .035, zb, u1, v0),
          wallPoint(a, b, len, c0 + cw + pad, .035, zb + size, u1, v1),
          wallPoint(a, b, len, c0 - pad, .035, zb + size, u0, v1)}, false)
      end
    end
  end
  line(digits, P.number, z0 + P.pad, w1)
  line(label, P.street, z0 + 2 * P.pad + P.number, w2)
  BLD.note('plate', a, b, len, s0 + width / 2, z0 - base)
  return true
end

-- A mapped lift gate (barrier=lift_gate, options.experimentalDetail): a post at the right edge
-- of the way it stands on and its boom raised upright, striped red and white. Raised: a boom
-- across the way without collision would let a car through it. Returns true when drawn.
BLD.LIFTGATE = {post = {.3, .3, 1.05}, boom = 3.6, stripe = .6, reach = 3}
function BLD.liftGate(scene, p, roads, ground)
  local G = BLD.LIFTGATE
  local best, hit = G.reach
  for _, road in ipairs(roads) do
    local pts = road.points or NONE
    for k = 1, #pts - 1 do
      local d, t = segDistance(p[1], p[2], pts[k], pts[k + 1])
      if d < best then best, hit = d, {a = pts[k], b = pts[k + 1], width = road.width or 4} end
    end
  end
  if not hit then return false end
  local dx, dy = hit.b[1] - hit.a[1], hit.b[2] - hit.a[2]
  local len = math.sqrt(dx * dx + dy * dy)
  if len < EPS then return false end
  local ux, uy = dx / len, dy / len
  -- a little frame on the gate's line across the way: s along the road, o to its right
  local half = math.max(1.5, math.min(4, hit.width / 2)) + .45
  local cx, cy = p[1] + uy * half, p[2] - ux * half
  local a, b = {cx - ux, cy - uy}, {cx + ux, cy + uy}
  local z = ground(cx, cy)
  local w, d, h = G.post[1], G.post[2], G.post[3]
  BLD.box(scene, 'dish', a, b, 2, 1 - w / 2, 1 + w / 2, -d / 2, d / 2, z, z + h, true, true, false)
  local n = math.floor(G.boom / G.stripe)
  for k = 0, n - 1 do
    BLD.box(scene, k % 2 == 0 and 'paint_red' or 'dish', a, b, 2, .96, 1.04, -.04, .04,
      z + h + k * G.stripe, z + h + (k + 1) * G.stripe, true, k == n - 1, false)
  end
  return true
end

-- A stop's name on its own pole beside the shelter (options.experimentalDetail): the real
-- `name` of the stop node, white on the plate's blue, over the line a -> b (the plate faces
-- the right of it); letters shrink to keep the plate within `maxWidth`. Returns true when drawn.
BLD.STOPSIGN = {size = .13, minSize = .07, maxWidth = 2.2, z = 2.1, pole = 2.75}
function BLD.stopSign(scene, x, y, z, ux, uy, name)
  local S, P = BLD.STOPSIGN, BLD.PLATE
  if not name or name == '' then return false end
  local chars = BLD.glyphs(name)
  local size = math.max(S.minSize, math.min(S.size, (S.maxWidth - 2 * P.pad) / math.max(1, #chars) / P.aspect))
  local width = #chars * size * P.aspect + 2 * P.pad
  if width > S.maxWidth + .01 then return false end
  local a, b = {x - ux * width / 2, y - uy * width / 2}, {x + ux * width / 2, y + uy * width / 2}
  local hgt = size + 2 * P.pad
  local z0 = z + S.z
  BLD.box(scene, 'pipe', a, b, width, width / 2 - .03, width / 2 + .03, -.09, -.03, z, z + S.pole, true, true, false)
  scene.polygon('plate', {wallPoint(a, b, width, 0, 0, z0, 0, 0), wallPoint(a, b, width, width, 0, z0, 1, 0),
    wallPoint(a, b, width, width, 0, z0 + hgt, 1, 1), wallPoint(a, b, width, 0, 0, z0 + hgt, 0, 1)}, false)
  scene.polygon('plate', {wallPoint(a, b, width, width, -.02, z0, 0, 0), wallPoint(a, b, width, 0, -.02, z0, 1, 0),
    wallPoint(a, b, width, 0, -.02, z0 + hgt, 1, 1), wallPoint(a, b, width, width, -.02, z0 + hgt, 0, 1)}, false)
  local cw = size * P.aspect
  local pad = (size - cw) / 2
  for i, g in ipairs(chars) do
    if g >= 0 then
      local col, row = g % P.perRow, math.floor(g / P.perRow)
      local u0, u1 = col / P.perRow, (col + 1) / P.perRow
      local v0, v1 = 1 - (row + 1) / P.perRow, 1 - row / P.perRow
      local c0 = P.pad + (i - 1) * cw
      scene.polygon('glyphs', {wallPoint(a, b, width, c0 - pad, .01, z0 + P.pad, u0, v0),
        wallPoint(a, b, width, c0 + cw + pad, .01, z0 + P.pad, u1, v0),
        wallPoint(a, b, width, c0 + cw + pad, .01, z0 + P.pad + size, u1, v1),
        wallPoint(a, b, width, c0 - pad, .01, z0 + P.pad + size, u0, v1)}, false)
    end
  end
  BLD.note('stopsign', a, b, width, width / 2, S.z)
  return true
end

-- One concrete visor along a whole facade. The top faces the sky: the orbit camera sits
-- above a car, and a downward sheet (the house porch) was invisible there. The outer
-- edge is a short vertical fascia so the ledge reads from the side. h is unused.
function BLD.canopy(scene, a, b, length, base, h, height)
  if length < 12 then return end
  local reach = height >= 22 and 1.3 or 1.2
  local head = base + (height >= 22 and 3.5 or 3.2)
  local zOut = head - .18
  local s0, s1 = .35, length - .35
  local span = s1 - s0
  scene.polygon('parapet', {wallPoint(a, b, length, s0, .04, head, 0, 0),
    wallPoint(a, b, length, s1, .04, head, span / 3, 0),
    wallPoint(a, b, length, s1, reach, zOut, span / 3, reach / 3),
    wallPoint(a, b, length, s0, reach, zOut, 0, reach / 3)}, true)
  scene.polygon('parapet', {wallPoint(a, b, length, s0, reach, zOut - .22, 0, 0),
    wallPoint(a, b, length, s1, reach, zOut - .22, span / 3, 0),
    wallPoint(a, b, length, s1, reach, zOut, span / 3, .16),
    wallPoint(a, b, length, s0, reach, zOut, 0, .16)}, false)
end

-- Facade details (options.experimentalDetail, city blocks on near tiles): what a photo wall
-- cannot carry. Downpipes on the outer corners of low brick and plaster blocks (panel and
-- taller blocks drain inside); air-conditioner boxes under windows of panel, brick and plaster
-- walls, on the 3 m window grid of their textures (fast_photo: a window at .24-.76 of a cell,
-- its sill .96 m over the floor). Small, without collision (collision.lua QUIET).
BLD.DETAIL = {pipe = .11, pipeOff = .06, pipeMax = 6, pipeHeight = 18, cell = 3,
  ac = {wall_pnl_ = .05, wall_brk_ = .07, wall_pls_ = .07}, acMax = 40, acWidth = .8, acDepth = .28}

-- A box against the wall a -> b: s0..s1 along it, o0..o1 out from it, z0..z1. back: also the
-- face toward the wall (a pipe stands off it); top, bottom: the horizontal faces.
function BLD.box(scene, kind, a, b, length, s0, s1, o0, o1, z0, z1, back, top, bottom)
  local du, dz, dd = s1 - s0, z1 - z0, o1 - o0
  local function w(s, o, z, u, v) return wallPoint(a, b, length, s, o, z, u, v) end
  scene.polygon(kind, {w(s0, o1, z0, 0, 0), w(s1, o1, z0, du, 0), w(s1, o1, z1, du, dz), w(s0, o1, z1, 0, dz)}, false)
  scene.polygon(kind, {w(s1, o1, z0, 0, 0), w(s1, o0, z0, dd, 0), w(s1, o0, z1, dd, dz), w(s1, o1, z1, 0, dz)}, false)
  scene.polygon(kind, {w(s0, o0, z0, 0, 0), w(s0, o1, z0, dd, 0), w(s0, o1, z1, dd, dz), w(s0, o0, z1, 0, dz)}, false)
  if back then
    scene.polygon(kind, {w(s1, o0, z0, 0, 0), w(s0, o0, z0, du, 0), w(s0, o0, z1, du, dz), w(s1, o0, z1, 0, dz)}, false)
  end
  if top then
    scene.polygon(kind, {w(s0, o0, z1, 0, 0), w(s0, o1, z1, 0, dd), w(s1, o1, z1, du, dd), w(s1, o0, z1, du, 0)}, true)
  end
  if bottom then
    scene.polygon(kind, {w(s0, o0, z0, 0, 0), w(s1, o0, z0, du, 0), w(s1, o1, z0, du, dd), w(s0, o1, z0, 0, dd)}, true)
  end
end

-- Tools only (options.detailReport, e.g. a camera list): where a facade detail stands, the
-- wall point under it and the wall's outward normal. BLD.report is set per build.
function BLD.note(kind, a, b, length, s, z)
  local report = BLD.report
  if report then
    local dx, dy = (b[1] - a[1]) / length, (b[2] - a[2]) / length
    report[#report + 1] = {kind = kind, x = a[1] + dx * s, y = a[2] + dy * s, z = z, nx = dy, ny = -dx}
  end
end

-- The air-conditioner rate of a wall kind (BLD.DETAIL.ac), nil for walls without the grid.
function BLD.acRate(kind)
  if kind:find('_end$') then return nil end
  for prefix, rate in pairs(BLD.DETAIL.ac) do
    if kind:find(prefix, 1, true) == 1 then return rate end
  end
end

-- Air conditioners on one outer wall: a box under the window of a 3 m cell (the cells run from
-- the ring's first corner, as the texture's u does), floors above the ground one; not in a
-- storefront's band. Returns how many it put.
function BLD.acUnits(scene, a, b, length, along, base, height, kind, h, spans, room)
  local D = BLD.DETAIL
  local rate = BLD.acRate(kind)
  if not rate or length < 6 or room <= 0 then return 0 end
  local floors = math.floor((height - .3) / D.cell)
  local n = 0
  for k = math.ceil((along + .3) / D.cell), math.floor((along + length - .3) / D.cell) - 1 do
    local s = k * D.cell - along + D.cell / 2
    for f = 1, BLD.balconyColumn(kind, height, h, k) and 0 or floors - 1 do
      if ihash(h, k, f, 31) % 1000 < rate * 1000 then
        local z0 = base + f * D.cell + .22
        local clear = true
        for _, span in ipairs(spans or NONE) do
          if s + D.acWidth / 2 > span[1] and s - D.acWidth / 2 < span[2] and z0 < base + BLD.SHOP.band + .1 then clear = false end
        end
        if clear then
          BLD.box(scene, 'ac_unit', a, b, length, s - D.acWidth / 2, s + D.acWidth / 2, .02, .02 + D.acDepth,
            z0, z0 + .52, false, true, true)
          BLD.note('ac_unit', a, b, length, s, z0 - base)
          n = n + 1
          if n >= room then return n end
        end
      end
    end
  end
  return n
end

-- Balconies of a brick or plaster block of three to six floors (the khrushchovka) and of a
-- panel block of three to nine (whose photo panels have none): stacks on some 3 m window
-- columns of a wall, never two side by side, from the first floor up. A
-- concrete slab, a parapet of profiled sheet (pale or brown by building), and on about half
-- of them glazing (the office glass) up to the slab above, a roof slab over the top one.
BLD.BALCONY = {column = .3, glazed = .55, width = {.12, .82}, depth = .95, minFloors = 3, maxFloors = 6,
  panelFloors = 9}

-- Whether the 3 m column k of a building (hash h) carries a balcony stack, for a wall kind.
function BLD.balconyColumn(kind, height, h, k)
  local B = BLD.BALCONY
  local panel = kind:find('wall_pnl_', 1, true) == 1
  if not (panel or kind:find('wall_brk_', 1, true) == 1 or kind:find('wall_pls_', 1, true) == 1) or kind:find('_end$') then
    return false
  end
  local floors = math.floor((height - .3) / BLD.DETAIL.cell)
  if floors < B.minFloors or floors > (panel and B.panelFloors or B.maxFloors) then return false end
  local function chosen(c) return ihash(h, c, 0, 61) % 1000 < B.column * 1000 end
  return chosen(k) and not chosen(k - 1)
end

function BLD.balconies(scene, a, b, length, along, base, height, kind, h, spans)
  local B, D = BLD.BALCONY, BLD.DETAIL
  if length < 6 then return 0 end
  local floors = math.floor((height - .3) / D.cell)
  local sheet = h % 3 == 0 and 'clad_tin' or 'clad_metal'
  local n = 0
  for k = math.ceil((along + .3) / D.cell), math.floor((along + length - .3) / D.cell) - 1 do
    if BLD.balconyColumn(kind, height, h, k) then
      local c0 = k * D.cell - along
      local s0, s1 = c0 + B.width[1] * D.cell, c0 + B.width[2] * D.cell
      local clear = true
      for _, span in ipairs(spans or NONE) do
        if s1 > span[1] and s0 < span[2] then clear = false end
      end
      for f = 1, floors - 1 do
        local z = base + f * D.cell
        if clear or z > base + BLD.SHOP.band + .1 then
          local o = B.depth
          BLD.box(scene, 'plinth', a, b, length, s0, s1, .02, o, z - .02, z + .12, false, true, true)
          BLD.box(scene, sheet, a, b, length, s0, s1, o - .05, o, z + .12, z + 1.05, true, true, false)
          BLD.box(scene, sheet, a, b, length, s0, s0 + .05, .02, o - .05, z + .12, z + 1.05, true, true, false)
          BLD.box(scene, sheet, a, b, length, s1 - .05, s1, .02, o - .05, z + 1.05 - .93, z + 1.05, true, true, false)
          if ihash(h, k, f, 67) % 1000 < B.glazed * 1000 then
            local g0, g1 = z + 1.05, z + D.cell - .02
            local function pane(p, q, r, t)
              scene.polygon('wall_off_grey', {p, q, r, t}, false)
            end
            local u0, u1 = (along + s0) / 6, (along + s1) / 6
            pane(wallPoint(a, b, length, s0, o - .03, g0, u0, .02), wallPoint(a, b, length, s1, o - .03, g0, u1, .02),
              wallPoint(a, b, length, s1, o - .03, g1, u1, .02 + (g1 - g0) / 6), wallPoint(a, b, length, s0, o - .03, g1, u0, .02 + (g1 - g0) / 6))
            pane(wallPoint(a, b, length, s1, o - .03, g0, 0, .02), wallPoint(a, b, length, s1, .02, g0, (o - .05) / 6, .02),
              wallPoint(a, b, length, s1, .02, g1, (o - .05) / 6, .02 + (g1 - g0) / 6), wallPoint(a, b, length, s1, o - .03, g1, 0, .02 + (g1 - g0) / 6))
            pane(wallPoint(a, b, length, s0, .02, g0, 0, .02), wallPoint(a, b, length, s0, o - .03, g0, (o - .05) / 6, .02),
              wallPoint(a, b, length, s0, o - .03, g1, (o - .05) / 6, .02 + (g1 - g0) / 6), wallPoint(a, b, length, s0, .02, g1, 0, .02 + (g1 - g0) / 6))
          end
          if f == floors - 1 then
            BLD.box(scene, 'plinth', a, b, length, s0, s1, .02, o + .05, z + D.cell - .02, z + D.cell + .1, false, true, true)
          end
          BLD.note('balcony', a, b, length, (s0 + s1) / 2, z - base)
          n = n + 1
        end
      end
    end
  end
  return n
end

-- Window extras on one outer wall of a panel, brick or plaster block, on the same 3 m grid:
-- bars over a share of the ground floor's windows (the railing's bars, 6 cm out), and a
-- satellite dish on the pier beside a window above it (a disc tilted to the sky on an arm).
-- Not in a storefront's span. Returns how many dishes and grilles it put.
BLD.EXTRAS = {grille = .35, dish = .03, window = {.23, .77, .9, 2.45}, dishR = .3}
function BLD.windowExtras(scene, a, b, length, along, base, height, kind, h, spans)
  local D, X = BLD.DETAIL, BLD.EXTRAS
  if not BLD.acRate(kind) or length < 6 then return 0 end
  local floors = math.floor((height - .3) / D.cell)
  local n = 0
  local function free(s0, s1, z)
    for _, span in ipairs(spans or NONE) do
      if s1 > span[1] and s0 < span[2] and z < BLD.SHOP.band + .1 then return false end
    end
    return true
  end
  for k = math.ceil((along + .3) / D.cell), math.floor((along + length - .3) / D.cell) - 1 do
    local c0 = k * D.cell - along
    local s0, s1 = c0 + X.window[1] * D.cell, c0 + X.window[2] * D.cell
    if ihash(h, k, 0, 47) % 1000 < X.grille * 1000 and free(s0, s1, 0) then
      local z0, z1 = base + X.window[3], base + X.window[4]
      scene.polygon('railing_dark', {wallPoint(a, b, length, s0, .06, z0, 0, 0),
        wallPoint(a, b, length, s1, .06, z0, s1 - s0, 0),
        wallPoint(a, b, length, s1, .06, z1, s1 - s0, 1),
        wallPoint(a, b, length, s0, .06, z1, 0, 1)}, false)
      n = n + 1
    end
    for f = 1, BLD.balconyColumn(kind, height, h, k) and 0 or floors - 1 do
      if ihash(h, k, f, 53) % 1000 < X.dish * 1000 then
        -- on the pier right of the window, a little over its middle
        local s, z, r = c0 + .89 * D.cell, base + f * D.cell + 1.75, X.dishR
        if s + r < length - .2 then
          BLD.box(scene, 'dish', a, b, length, s - .03, s + .03, .02, .32, z - .03, z + .03, false, true, true)
          local ring = {}
          for q = 0, 7 do
            local t = q * math.pi / 4
            -- a disc in the plane facing out and 25 degrees up, centred .4 m out
            local du, dv = math.cos(t) * r, math.sin(t) * r
            ring[#ring + 1] = wallPoint(a, b, length, s + du, .4 - dv * .42, z + dv * .9, .5 + du, .5 + dv)
          end
          scene.polygon('dish', ring, false)
          local back = {}
          for q = #ring, 1, -1 do back[#back + 1] = ring[q] end
          scene.polygon('dish', back, false)
          BLD.note('dish', a, b, length, s, z - base)
          n = n + 1
        end
      end
    end
  end
  return n
end

-- Downpipes at the outer corners of a low brick or plaster block: a pipe 0.3 m round the
-- corner on the incoming wall, a hopper under the eaves, a kick-out at the foot. At most
-- pipeMax, the corners between the longest walls first.
function BLD.downpipes(scene, rings, base, top, height, kind)
  local D = BLD.DETAIL
  if height > D.pipeHeight or not (kind:find('wall_brk_', 1, true) == 1 or kind:find('wall_pls_', 1, true) == 1) then return 0 end
  local ring = BLD.orient(rings[1], rings)
  local n = #ring
  if n < 3 then return 0 end
  local corners = {}
  for k = 1, n do
    local a, p, b = ring[(k - 2) % n + 1], ring[k], ring[k % n + 1]
    local ux, uy, vx, vy = p[1] - a[1], p[2] - a[2], b[1] - p[1], b[2] - p[2]
    local lu, lv = math.sqrt(ux * ux + uy * uy), math.sqrt(vx * vx + vy * vy)
    if lu >= 3 and lv >= 3 and (ux * vy - uy * vx) / (lu * lv) > .5 then
      corners[#corners + 1] = {a = a, p = p, len = lu, weight = lu + lv, k = k}
    end
  end
  table.sort(corners, function(u, v) return u.weight > v.weight or (u.weight == v.weight and u.k < v.k) end)
  local w, o0 = D.pipe, D.pipeOff
  for i = 1, math.min(D.pipeMax, #corners) do
    local c = corners[i]
    local s1 = c.len - .3
    local s0 = s1 - w
    BLD.box(scene, 'pipe', c.a, c.p, c.len, s0, s1, o0, o0 + w, base + .32, top - .42, true, false, false)
    BLD.box(scene, 'pipe', c.a, c.p, c.len, s0 - .07, s1 + .07, o0 - .03, o0 + w + .07, top - .42, top - .14, true, false, true)
    BLD.box(scene, 'pipe', c.a, c.p, c.len, s0, s1, o0, o0 + .38, base + .1, base + .32, true, true, false)
    BLD.note('pipe', c.a, c.p, c.len, s0, 0)
  end
  return math.min(D.pipeMax, #corners)
end

-- Covers in a town street's asphalt (options.experimentalDetail; synthetic, not mapped): a
-- round manhole every manholeStep m, in the gap between the wheel paths of one lane and then
-- the other, and a grid drain every drainStep m at each curb that has a sidewalk. Lattices run
-- from the road's source start (strip.start + dist), phased by its id, so tiles and junction
-- cuts agree; every tile a cover touches draws it (the collector clips it to the tile), and
-- none lies within `clear` m of a cut end (a junction's fan).
-- With patches: a patch of new asphalt every patchStep m at patchChance, 2.5 to 6 m long,
-- 0.9 to 1.8 m wide, somewhere across the carriageway (the patch sheet is 1 x 8 of its width).
ROADS.COVERS = {manholeStep = 55, drainStep = 38, clear = 7, manhole = .82, drain = {.42, .95},
  patchStep = 23, patchChance = .5,
  classes = {residential = true, tertiary = true, secondary = true, primary = true, unclassified = true,
    living_street = true}}
function ROADS.covers(strips, rect, lift, decor, pause, patches)
  local C = ROADS.COVERS
  for n, strip in ipairs(strips) do
    local tags, points, dist = strip.tags, strip.points, strip.dist
    local class = (tags.highway or ''):gsub('_link$', '')
    if strip.surface and strip.grade <= 1 and C.classes[class] and strip.hw >= 2.5 and #points >= 2 then
      local total, start, seed = dist[#dist], strip.start or 0, hash(tostring(strip.road.id or n))
      local function place(step, phase, put)
        for m = math.ceil((start + C.clear - phase) / step), math.floor((start + total - C.clear - phase) / step) do
          local at = m * step + phase - start
          local k = 1
          while k < #points - 1 and dist[k + 1] < at do k = k + 1 end
          local a, b = points[k], points[k + 1]
          local len = dist[k + 1] - dist[k]
          if len > EPS then
            local f = (at - dist[k]) / len
            local ux, uy = (b[1] - a[1]) / len, (b[2] - a[2]) / len
            put(m, k, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, (a[3] or 0) + ((b[3] or 0) - (a[3] or 0)) * f, ux, uy)
          end
        end
      end
      -- a patch lies between the paint and the covers: none of them fights another for depth
      local function quad(kind, x, y, z, ux, uy, along, across, u0, v0, u1, v1)
        local reach = math.max(along, across) / 2 + .1
        if not boundsTouch(rect, {x - reach, y - reach, x + reach, y + reach}) then return end
        local nx, ny, ha, hc = -uy, ux, along / 2, across / 2
        local zz = z + lift + DECAL.markLift * (kind == 'patch' and 1.25 or 1.5)
        decor.polygon(kind, {{x - ux * ha - nx * hc, y - uy * ha - ny * hc, zz, u0, v0},
          {x - ux * ha + nx * hc, y - uy * ha + ny * hc, zz, u1, v0},
          {x + ux * ha + nx * hc, y + uy * ha + ny * hc, zz, u1, v1},
          {x + ux * ha - nx * hc, y + uy * ha - ny * hc, zz, u0, v1}}, 'flat')
      end
      local town = false
      for k = 1, #points - 1 do
        local w = strip.walk[k] or NONE
        if w[1] or w[-1] then town = true; break end
      end
      if town then
        place(C.manholeStep, seed % C.manholeStep, function(m, k, x, y, z, ux, uy)
          local side = m % 2 == 0 and 1 or -1
          local off = strip.hw * .45 * side
          -- the round cover: the upper right quarter of the sheet
          quad('manhole', x - uy * off, y + ux * off, z, ux, uy, C.manhole, C.manhole, .5, 0, 1, .5)
        end)
        if patches then
          place(C.patchStep, (seed * 13 + 5) % C.patchStep, function(m, k, x, y, z, ux, uy)
            local r = ihash(seed, m, 0, 71)
            if r % 1000 < C.patchChance * 1000 then
              local long = 2.5 + (r % 7) * .58
              local wide = .9 + (math.floor(r / 7) % 5) * .22
              local room = math.max(0, strip.hw - wide / 2 - .35)
              local off = ((math.floor(r / 35) % 101) / 50 - 1) * room
              local v0 = (math.floor(r / 3535) % 100) / 100
              quad('patch', x - uy * off, y + ux * off, z, ux, uy, long, wide, 0, v0, 1, v0 + long / wide / 8)
            end
          end)
        end
        place(C.drainStep, (seed * 7 + 11) % C.drainStep, function(m, k, x, y, z, ux, uy)
          for _, side in ipairs({1, -1}) do
            if (strip.walk[k] or NONE)[side] then
              local off = (strip.hw - C.drain[1] / 2 - .03) * side
              quad('drain', x - uy * off, y + ux * off, z, ux, uy, C.drain[2], C.drain[1], 0, 0, 1, .5)
            end
          end
        end)
      end
    end
    if n % 16 == 0 then pause() end
  end
end

-- True when a carriageway (not a yard driveway) passes within r metres of (x, y).
-- segmentBins is the tile's road index from build(); service ways are a yard, not a street.
function BLD.street(bins, x, y, r)
  local key = (math.floor(x / 50) + 32768) * 65536 + math.floor(y / 50) + 32768
  for _, s in ipairs(bins[key] or NONE) do
    local way = (s.tags or NONE).highway
    if s.surface and s.len2 > 0 and way ~= 'service' and way ~= 'living_street' then
      local t = math.max(0, math.min(1, ((x - s.a[1]) * s.dx + (y - s.a[2]) * s.dy) / s.len2))
      local d = math.sqrt((s.a[1] + t * s.dx - x) ^ 2 + (s.a[2] + t * s.dy - y) ^ 2) - s.width / 2
      if d < r then return true end
    end
  end
  return false
end

-- Storefront experiment (options.experimentalShopfront, off by default). Evidence is a mapped
-- commercial node (a 'poi' point, packs built with EARTHNG_POIS=1) or the building's own shop,
-- retail or commercial tag. A node is tied to the one building it stands in (or within `edge`
-- of, with no other within `near`) and to the wall of the mapped door ('door' point, or a main
-- entrance) on that building nearest it, within doorReach; a tagged building without a node
-- gets its only street wall. Anything unclear is skipped, with its reason in
-- options.poiReport when the caller passes a table. The wall's lower band then takes a neutral
-- shop material: a synthetic look of the use, not the real sign, windows or door. Nothing is
-- placed on the ground.
--   reach: a street's edge at most this far out from the wall; depth: a node farther than this
--   from its wall is inside the block, not on its front; span: metres of front per node; tie: a
--   second street wall this much farther is still a tie (a corner); band: the shop's height (the
--   texture's design, squeezed into a lower building down to minBand); halo: the pack's source
--   halo round a cell (build_country.HALO); margin:
--   the building's neighbourhood that must lie in every cell a drawing tile may load.
BLD.SHOP = {reach = 18, depth = 12, span = 8, tie = 1.5, edge = 3, near = 10, band = 4.2, minBand = 2.6, entrance = 1.2,
  halo = 100, margin = 60, minWall = 4, doorReach = 20, inferWall = false,
  -- a yard's service way is not a shop street, unless `service` is set (a sensitivity run of
  -- shop_audit.py --tune): then one without a service=* subtype counts too, never a parking
  -- aisle, a driveway or a drive-through
  service = false, serviceNot = {parking_aisle = true, driveway = true, ['drive-through'] = true, emergency_access = true},
  materials = {'wall_shop_dark', 'wall_shop_red', 'wall_shop_green', 'wall_shop_blue'},
  -- a shop the generator would dress as a house (its windows and door) gets plain walls instead
  hosts = {'wall_pls_cream', 'wall_pls_grey', 'wall_pls_peach', 'wall_brk_white'},
  closed = {no = true, vacant = true, closed = true, disused = true, abandoned = true}}

-- 'ground', 'unknown' (no level tag), 'upper', 'below' or 'unclear' for a node's level tag.
function BLD.shopLevel(tags)
  local value = tags.level
  if value == nil or value == '' then return 'unknown' end
  local low, high
  for part in tostring(value):gmatch('[^;]+') do
    local a, b = part:match('^%s*(%-?[%d%.]+)%s*%-%s*(%-?[%d%.]+)%s*$')
    a, b = tonumber(a), tonumber(b)
    if not a then a = tonumber(part:match('^%s*(.-)%s*$')); b = a end
    if not a or not b then return 'unclear' end
    low, high = math.min(low or a, a, b), math.max(high or a, a, b)
  end
  if not low then return 'unclear' end
  if high < 0 then return 'below' end
  if low > 0 then return 'upper' end
  return 'ground'
end

local function shopTagged(tags)
  local shop = tags.shop
  return (shop and not BLD.SHOP.closed[shop]) or tags.building == 'retail' or tags.building == 'commercial'
end

-- The exterior ring as the wall loop of build() walks it: cleaned, anticlockwise.
local function outerRing(rings)
  local ring, signed = cleanRing(rings[1]), 0
  for k, p in ipairs(ring) do local q = ring[k % #ring + 1]; signed = signed + p[1] * q[2] - q[1] * p[2] end
  if signed < 0 then local rev = {}; for k = #ring, 1, -1 do rev[#rev + 1] = ring[k] end; ring = rev end
  return ring
end

function BLD.wallKey(a, b)
  return string.format('%.3f,%.3f,%.3f,%.3f', a[1], a[2], b[1], b[2])
end


-- Report only (poiReport): the class of the road whose edge comes nearest a building's walls,
-- and that gap, with no class, side or parallel test. Explains a 'no_street_wall'.
function BLD.nearestRoad(roads, building)
  local ring, best, class = cleanRing(building.rings[1]), math.huge, nil
  local box = ringBounds(building.rings)
  for _, road in ipairs(roads) do
    local points = road.points or NONE
    for k = 1, #points - 1 do
      local a, b = points[k], points[k + 1]
      if boundsTouch(box, {math.min(a[1], b[1]), math.min(a[2], b[2]), math.max(a[1], b[1]), math.max(a[2], b[2])}, 80) then
        for _, p in ipairs(ring) do
          local d = segDistance(p[1], p[2], a, b) - (road.width or 7) / 2
          if d < best then best, class = d, (road.tags or NONE).highway or 'track' end
        end
      end
    end
  end
  return class, best < math.huge and best or nil
end

-- Storefronts of one tile: building id -> {[wallKey] = {{s0, s1, material, evidence id}, ...}}
-- (metres along the wall from its first corner), or nil. Built from the whole source data
-- (lists), never from the tile's own road bins, so every tile that draws a building takes the
-- same decision; options.cellSize (the game passes it) also skips a building whose
-- neighbourhood a tile in the next cell may not have loaded.
function BLD.shopLinks(lists, options, pause)
  local S, report = BLD.SHOP, options.poiReport
  if type(options.shopTune) == 'table' then
    S = {}
    for k, v in pairs(BLD.SHOP) do S[k] = v end
    for k, v in pairs(options.shopTune) do S[k] = v end
  end
  local function note(entry) if type(report) == 'table' then report[#report + 1] = entry end end
  local pois, tagged = {}, {}
  for _, p in ipairs(lists.points) do
    if p.kind == 'poi' and p.pos then pois[#pois + 1] = p end
  end
  for _, b in ipairs(lists.buildings) do
    if shopTagged(b.tags or NONE) then tagged[#tagged + 1] = b end
  end
  if #pois == 0 and #tagged == 0 then return nil end
  local function binKey(x, y) return (math.floor(x / 50) + 32768) * 65536 + math.floor(y / 50) + 32768 end
  local function binAdd(bins, box, margin, value)
    for by = math.floor((box[2] - margin) / 50), math.floor((box[4] + margin) / 50) do
      for bx = math.floor((box[1] - margin) / 50), math.floor((box[3] + margin) / 50) do
        local key = (bx + 32768) * 65536 + by + 32768
        local bin = bins[key] or {}
        bins[key], bin[#bin + 1] = bin, value
      end
    end
  end
  -- buildings by bin, each bin taking those within `near` of it
  local houses, boxes = {}, {}
  for n, b in ipairs(lists.buildings) do
    if b.rings and b.rings[1] and #b.rings[1] >= 3 then
      boxes[b] = ringBounds(b.rings)
      binAdd(houses, boxes[b], S.near, b)
    end
    if n % 256 == 0 then pause() end
  end
  -- carriageways on the ground (a yard's service way and a living street are not a shop street)
  local streets = {}
  for n, road in ipairs(lists.roads) do
    local tags, points = road.tags or NONE, road.points or NONE
    local way = tags.highway
    local yard = way == 'service' and not (S.service and not S.serviceNot[tags.service or ''])
    if not road.track and not ROADS.bridge(tags) and not ROADS.tunnel(tags) and not yard and way ~= 'living_street' then
      local width = math.max(.5, math.min(80, road.width or 7))
      for k = 1, #points - 1 do
        local a, b = points[k], points[k + 1]
        local dx, dy = b[1] - a[1], b[2] - a[2]
        local len2 = dx * dx + dy * dy
        if len2 > EPS then
          binAdd(streets, {math.min(a[1], b[1]), math.min(a[2], b[2]), math.max(a[1], b[1]), math.max(a[2], b[2])},
            width / 2 + S.reach, {a = a, dx = dx, dy = dy, len2 = len2, width = width})
        end
      end
    end
    if n % 64 == 0 then pause() end
  end
  local entrances, doors = {}, {}
  for _, p in ipairs(lists.points) do
    local tag = (p.tags or NONE).entrance
    if p.pos and p.kind == 'entrance' and tag ~= 'main' then binAdd(entrances, {p.pos[1], p.pos[2], p.pos[1], p.pos[2]}, 2, p) end
    if p.pos and (p.kind == 'door' or (p.kind == 'entrance' and tag == 'main')) then
      binAdd(doors, {p.pos[1], p.pos[2], p.pos[1], p.pos[2]}, S.doorReach, p)
    end
  end
  -- The gap to the edge of the street a wall faces: parallel, outside the wall, within reach,
  -- with no other building between them. nil when there is none.
  local function street(owner, a, b, len)
    local dx, dy = b[1] - a[1], b[2] - a[2]
    local x, y = (a[1] + b[1]) / 2, (a[2] + b[2]) / 2
    local nx, ny = dy / len, -dx / len        -- outward from an anticlockwise ring
    local best
    for _, s in ipairs(streets[binKey(x, y)] or NONE) do
      if math.abs((dx * s.dx + dy * s.dy) / (len * math.sqrt(s.len2))) >= .85 then
        local t = math.max(0, math.min(1, ((x - s.a[1]) * s.dx + (y - s.a[2]) * s.dy) / s.len2))
        local ox, oy = s.a[1] + t * s.dx - x, s.a[2] + t * s.dy - y
        local gap = math.sqrt(ox * ox + oy * oy) - s.width / 2
        if ox * nx + oy * ny > s.width / 2 + .5 and gap <= S.reach and (not best or gap < best) then
          local open = true
          for _, f in ipairs({.25, .5, .75}) do
            local px, py = x + nx * (.3 + gap * f), y + ny * (.3 + gap * f)
            for _, other in ipairs(houses[binKey(px, py)] or NONE) do
              if other ~= owner and inside(other.rings, px, py) then open = false; break end
            end
            if not open then break end
          end
          if open then best = gap end
        end
      end
    end
    return best
  end
  -- A tile that draws the building lies in a cell the footprint touches; each such cell (with
  -- its halo) must hold the whole neighbourhood. Other cells a tile loads only add to it.
  local function seamSafe(box)
    local s = options.cellSize
    if not s then return true end
    local r = {box[1] - S.margin, box[2] - S.margin, box[3] + S.margin, box[4] + S.margin}
    return r[1] >= math.floor(box[3] / s) * s - S.halo and r[3] <= (math.floor(box[1] / s) + 1) * s + S.halo and
      r[2] >= math.floor(box[4] / s) * s - S.halo and r[4] <= (math.floor(box[2] / s) + 1) * s + S.halo
  end
  local walls = {}
  local function streetWalls(b)
    if not walls[b] then
      local list, ring = {}, outerRing(b.rings)
      for k, a in ipairs(ring) do
        local q = ring[k % #ring + 1]
        local len = math.sqrt((q[1] - a[1]) ^ 2 + (q[2] - a[2]) ^ 2)
        if len >= S.minWall then
          local gap = street(b, a, q, len)
          if gap then list[#list + 1] = {a = a, b = q, len = len, gap = gap, key = BLD.wallKey(a, q)} end
        end
      end
      walls[b] = list
    end
    return walls[b]
  end
  local function edgeDistance(rings, x, y)
    local best = math.huge
    for _, ring in ipairs(rings) do
      local c = cleanRing(ring)
      for k, a in ipairs(c) do best = math.min(best, (segDistance(x, y, a, c[k % #c + 1]))) end
    end
    return best
  end
  local links, chosen = {}, {}
  local function add(b, wall, s0, s1, material, id)
    local own = links[b.id] or {}
    links[b.id], chosen[b.id] = own, b
    local spans = own[wall.key] or {spans = {}, wall = wall}
    own[wall.key] = spans
    spans.spans[#spans.spans + 1] = {s0, s1, material, id}
  end
  local tied = {}
  for n, p in ipairs(pois) do
    local x, y, tags = p.pos[1], p.pos[2], p.tags or NONE
    local entry = {evidence = 'poi', poi = tostring(p.id), x = x, y = y, shop = tags.shop, amenity = tags.amenity,
      office = tags.office, craft = tags.craft, level = tags.level, levelRule = BLD.shopLevel(tags)}
    local within, close = {}, {}
    for _, b in ipairs(houses[binKey(x, y)] or NONE) do
      if inside(b.rings, x, y) then within[#within + 1] = b
      else
        local d = edgeDistance(b.rings, x, y)
        if d <= S.near then close[#close + 1] = {b, d} end
      end
    end
    table.sort(close, function(u, v) return u[2] < v[2] or (u[2] == v[2] and tostring(u[1].id) < tostring(v[1].id)) end)
    entry.inside, entry.near = #within, #close
    local building, reason
    local level = entry.levelRule
    if tags.indoor and tags.indoor ~= 'no' then reason = 'indoor'
    elseif tags.location == 'underground' or tags.location == 'indoor' then reason = 'location_' .. tags.location
    elseif level == 'below' then reason = 'level_below_ground'
    elseif level == 'upper' then reason = 'level_upper_floor'
    elseif level == 'unclear' then reason = 'level_unclear'
    elseif #within > 1 then reason = 'inside_several_buildings'
    elseif #within == 1 then building = within[1]; entry.match = 'inside'
    elseif #close == 0 then reason = 'no_building_near'
    elseif close[1][2] > S.edge then reason = 'nearest_building_too_far'; entry.edge = close[1][2]
    elseif close[2] then reason = 'several_buildings_near'
    else building = close[1][1]; entry.match = 'edge'; entry.edge = close[1][2] end
    if building then
      entry.building = tostring(building.id)
      if not seamSafe(boxes[building]) then reason, building = 'cell_seam', nil end
    end
    if building then
      -- The wall: the one a mapped door of this building stands on, the door nearest the
      -- node (a mapped shop door is the evidence; Bilychi 29.10: the nearest street wall
      -- missed the mapped door in 10 of 15 checkable links). With S.inferWall (a
      -- sensitivity run) a building without doors falls back to its nearest street wall.
      local ring, door = outerRing(building.rings), nil
      for _, d in ipairs(doors[binKey(x, y)] or NONE) do
        local dd = math.sqrt((d.pos[1] - x) ^ 2 + (d.pos[2] - y) ^ 2)
        if dd <= S.doorReach then
          for k, a in ipairs(ring) do
            local q = ring[k % #ring + 1]
            local off, t = segDistance(d.pos[1], d.pos[2], a, q)
            if off <= 1 and (not door or dd < door.dd or (dd == door.dd and tostring(d.id) < tostring(door.point.id))) then
              door = {point = d, dd = dd, a = a, b = q, t = t}
            end
          end
        end
      end
      local wall, at
      if door then
        local len = math.sqrt((door.b[1] - door.a[1]) ^ 2 + (door.b[2] - door.a[2]) ^ 2)
        wall, at = {a = door.a, b = door.b, len = len, key = BLD.wallKey(door.a, door.b)}, door.t
        wall.gap = len >= S.minWall and street(building, door.a, door.b, len) or nil
        entry.how, entry.door, entry.doorTag, entry.doorDistance = 'mapped_door', tostring(door.point.id),
          (door.point.tags or NONE).entrance, door.dd
        entry.wallDistance = segDistance(x, y, door.a, door.b)
      elseif not S.inferWall then
        reason = 'no_mapped_door'
      else
        local best, second
        for _, w in ipairs(streetWalls(building)) do
          local d, t = segDistance(x, y, w.a, w.b)
          if not best or d < best.d then best, second = {wall = w, d = d, t = t}, best
          elseif not second or d < second.d then second = {wall = w, d = d, t = t} end
        end
        if not best then
          reason = 'no_street_wall'
          if type(report) == 'table' then entry.nearestRoad, entry.nearestGap = BLD.nearestRoad(lists.roads, building) end
        elseif best.d > S.depth then reason = 'street_wall_too_far'; entry.wallDistance = best.d
        elseif second and second.d - best.d < S.tie then reason = 'two_street_walls_tie'; entry.wallDistance = best.d
        else wall, at = best.wall, best.t; entry.how, entry.wallDistance = 'nearest_street_wall', best.d end
      end
      if wall then
        local s0, s1 = math.max(.5, at - S.span / 2), math.min(wall.len - .5, at + S.span / 2)
        if s1 - s0 < S.span and wall.len - 1 >= S.span then
          if s0 <= .5 then s1 = .5 + S.span else s0 = wall.len - .5 - S.span end
        end
        if s1 - s0 < 2 then reason = 'wall_too_short'
        else
          entry.decision, entry.wall, entry.street, entry.span = 'linked', wall.key, wall.gap, {s0, s1}
          tied[building] = true
          add(building, wall, s0, s1, S.materials[hash(tostring(p.id)) % #S.materials + 1], tostring(p.id))
        end
      end
    end
    if not entry.decision then entry.decision, entry.reason = 'rejected', reason end
    note(entry)
    if n % 16 == 0 then pause() end
  end
  for n, b in ipairs(tagged) do
    if not tied[b] then
      local tags = b.tags or NONE
      local box = boxes[b] or ringBounds(b.rings)
      local entry = {evidence = 'building_tag', building = tostring(b.id), shop = tags.shop, use = tags.building,
        x = (box[1] + box[3]) / 2, y = (box[2] + box[4]) / 2}
      if #b.rings ~= 1 then entry.reason = 'courtyard_or_parts'
      elseif not seamSafe(box) then entry.reason = 'cell_seam'
      else
        local list = streetWalls(b)
        if #list == 0 then entry.reason = 'no_street_wall'
        elseif #list > 1 then entry.reason = 'several_street_walls'
        else
          entry.decision, entry.wall = 'linked', list[1].key
          add(b, list[1], .5, list[1].len - .5, S.materials[hash(tostring(b.id)) % #S.materials + 1], 'building:' .. tostring(b.id))
        end
      end
      if not entry.decision then entry.decision = 'rejected' end
      note(entry)
    end
    if n % 16 == 0 then pause() end
  end
  -- Spans along each wall in order; an overlap goes to the earlier one; a mapped staircase
  -- entrance on the wall keeps its own wall either side.
  for _, own in pairs(links) do
    for key, item in pairs(own) do
      local wall, cuts, out, at = item.wall, {}, {}, -math.huge
      local seen = {}
      for by = math.floor(math.min(wall.a[2], wall.b[2]) / 50), math.floor(math.max(wall.a[2], wall.b[2]) / 50) do
        for bx = math.floor(math.min(wall.a[1], wall.b[1]) / 50), math.floor(math.max(wall.a[1], wall.b[1]) / 50) do
          for _, e in ipairs(entrances[(bx + 32768) * 65536 + by + 32768] or NONE) do
            local d, t = segDistance(e.pos[1], e.pos[2], wall.a, wall.b)
            if d <= 1.5 and not seen[e] then seen[e] = true; cuts[#cuts + 1] = {t - S.entrance, t + S.entrance} end
          end
        end
      end
      table.sort(item.spans, function(u, v) return u[1] < v[1] or (u[1] == v[1] and u[4] < v[4]) end)
      for _, span in ipairs(item.spans) do
        local pieces = {{math.max(span[1], at), span[2]}}
        for _, c in ipairs(cuts) do
          local kept = {}
          for _, piece in ipairs(pieces) do
            if c[2] <= piece[1] or c[1] >= piece[2] then kept[#kept + 1] = piece
            else
              if c[1] > piece[1] then kept[#kept + 1] = {piece[1], c[1]} end
              if c[2] < piece[2] then kept[#kept + 1] = {c[2], piece[2]} end
            end
          end
          pieces = kept
        end
        for _, piece in ipairs(pieces) do
          if piece[2] - piece[1] >= 1 then out[#out + 1] = {piece[1], piece[2], span[3], span[4]} end
        end
        at = math.max(at, span[2])
      end
      own[key] = #out > 0 and out or nil
    end
  end
  return links
end

-- Straight facades are often many OSM edges. Chain the ones that meet and point the same
-- way, then put hoods on each street run and on the longest yard run. One edge at a time
-- left a long brick slab with a single hood on a short piece, off the camera.
function BLD.canopies(scene, h, height)
  local list = BLD.faces
  local n = list and #list or 0
  if n == 0 then return end
  local function nxt(i) return i % n + 1 end
  local function prv(i) return (i - 2) % n + 1 end
  local function joins(p, f)
    local gap = (f[1][1] - p[2][1]) ^ 2 + (f[1][2] - p[2][2]) ^ 2
    if gap > .36 then return false end
    local pdx, pdy = p[2][1] - p[1][1], p[2][2] - p[1][2]
    local fdx, fdy = f[2][1] - f[1][1], f[2][2] - f[1][2]
    local pl = math.sqrt(pdx * pdx + pdy * pdy)
    local fl = math.sqrt(fdx * fdx + fdy * fdy)
    if pl < 1e-4 or fl < 1e-4 then return false end
    return (pdx * fdx + pdy * fdy) / (pl * fl) > .985
  end
  local start = 1
  for i = 1, n do
    if not joins(list[prv(i)], list[i]) then start = i break end
  end
  local streets, best, bestLen = 0, nil, 0
  local function emit(a, b, z, road)
    local dx, dy = b[1] - a[1], b[2] - a[2]
    local chord = math.sqrt(dx * dx + dy * dy)
    if chord < 12 then return end
    if road and streets < 4 then
      streets = streets + 1
      BLD.canopy(scene, a, b, chord, z, h, height)
    elseif not road and chord > bestLen then
      best, bestLen = {a, b, z, chord}, chord
    end
  end
  local i = start
  repeat
    local face = list[i]
    local a, b, z, road = face[1], face[2], face.z, face.road
    local j = nxt(i)
    local steps = 1
    while j ~= start and steps < n and joins(list[prv(j)], list[j]) do
      b = list[j][2]
      if list[j].road then road = true end
      j = nxt(j)
      steps = steps + 1
    end
    emit(a, b, z, road)
    i = j
  until i == start
  if best then BLD.canopy(scene, best[1], best[2], best[4], best[3], h, height) end
end

-- One attic window in the gable at the long-axis end, when the triangle is tall enough.
function BLD.gableWin(scene, frame, top, rise, dress)
  if rise < 1.55 or not dress.win or not dress.cell then return end
  local mid = (frame.v0 + frame.v1) / 2
  local cell, hw = dress.cell, .34
  local z0 = top + math.max(.4, rise * .3)
  local z1 = z0 + .72
  if z1 > top + rise - .2 then return end
  local ox, oy = frame.ax * .03, frame.ay * .03
  local function p(v, z, uu, vv)
    return {frame.u1 * frame.ax + v * frame.bx + ox, frame.u1 * frame.ay + v * frame.by + oy, z, uu, vv}
  end
  scene.polygon(dress.win, {p(mid - hw, z0, cell[1], cell[4]), p(mid + hw, z0, cell[3], cell[4]),
    p(mid + hw, z1, cell[3], cell[2]), p(mid - hw, z1, cell[1], cell[2])}, false)
end

-- guess: a house's dress (BLD.dress) for its roof shape, pitch and gables where OSM has none
local function pitchedRoof(scene, rings, tags, top, base, kind, height, material, guess)
  if #rings ~= 1 then return false end -- Courtyards always keep their open flat-roof footprint.
  local ring = cleanRing(rings[1])
  if #ring < 3 then return false end
  local frame = footprintFrame(ring)
  local length, width = frame.u1 - frame.u0, frame.v1 - frame.v0
  local explicit, house = tags['roof:shape'], tags.building == 'house' or tags.building == 'detached' or tags.building == 'bungalow'
  if explicit and explicit ~= 'gabled' and explicit ~= 'hipped' and explicit ~= 'pyramidal' and explicit ~= 'half-hipped' then return false end
  if not explicit and not (house or (height < 8 and frame.area < 260)) then return false end
  if width < 3 or length < 3 or frame.area / math.max(EPS, length * width) < .82 then return false end
  if not explicit and width > 18 then return false end
  guess = guess or NONE
  local shape = explicit or guess.shape
  local pitch = guess.pitch or (house and 35 or 28)
  local rise = math.max(.5, math.min(10, number(tags['roof:height'], math.min(6, width / 2 * math.tan(math.rad(pitch))))))
  material = material or 'roof_tile'
  -- Eaves: the roof runs on past the walls (a box under a lid read as a toy, bld-hatne-01) and
  -- drops by the pitch; the material is double sided, so the overhang shows from below.
  local slope = rise / math.max(EPS, width / 2)
  local eave = width < 5 and .25 or .5
  local mid = (frame.v0 + frame.v1) / 2
  local u0, u1, v0, v1 = frame.u0 - eave, frame.u1 + eave, frame.v0 - eave, frame.v1 + eave
  local low = top - eave * slope
  -- UVs: u along the ridge, v down the slope from the ridge, BLD.repeats metres a repeat
  local scale = BLD.repeats[material] or 2
  local stretch = math.sqrt(1 + slope * slope)
  local function point(u, v, z, along, down)
    return {u * frame.ax + v * frame.bx, u * frame.ay + v * frame.by, z, along / scale, down * stretch / scale}
  end
  local inset = (shape == 'hipped' or shape == 'half-hipped' or shape == 'pyramidal') and math.min(width / 2, length / 2) or 0
  if shape == 'pyramidal' then inset = length / 2 end
  -- the two long slopes
  local a, b = point(u0, v0, low, 0, mid - v0), point(u1, v0, low, u1 - u0, mid - v0)
  local c, d = point(u1, v1, low, u1 - u0, v1 - mid), point(u0, v1, low, 0, v1 - mid)
  local r0 = point(frame.u0 + inset - (inset > 0 and 0 or eave), mid, top + rise, frame.u0 + inset - (inset > 0 and 0 or eave) - u0, 0)
  local r1 = point(frame.u1 - inset + (inset > 0 and 0 or eave), mid, top + rise, frame.u1 - inset + (inset > 0 and 0 or eave) - u0, 0)
  scene.polygon(material, {a, b, r1, r0}, true)
  scene.polygon(material, {c, d, r0, r1}, true)
  if inset > 0 then
    -- hip ends: u across the end, v down from the ridge's end
    local function hip(p, q, r, ridgeU)
      local function at(x, uu, vv) return {x[1], x[2], x[3], (vv - v0) / scale, math.abs(uu - ridgeU) * stretch / scale} end
      return {at(p, p.u, p.v), at(q, q.u, q.v), at(r, ridgeU, mid)}
    end
    b.u, b.v, c.u, c.v, d.u, d.v, a.u, a.v = u1, v0, u1, v1, u0, v1, u0, v0
    scene.polygon(material, hip(b, c, r1, frame.u1 - inset), true)
    scene.polygon(material, hip(d, a, r0, frame.u0 + inset), true)
  else
    a, b = point(frame.u0, frame.v0, top, 0, 0), point(frame.u1, frame.v0, top, 0, 0)
    c, d = point(frame.u1, frame.v1, top, 0, 0), point(frame.u0, frame.v1, top, 0, 0)
    r0, r1 = point(frame.u0, mid, top + rise, 0, 0), point(frame.u1, mid, top + rise, 0, 0)
    -- a facade's gables are boards: its windows ran on into the gable askew (bld-hatne-03)
    local gable = guess.gable or (kind:find('wall_', 1, true) == 1 and 'gable' or kind)
    local scale = facadeScale(gable)
    for _, face in ipairs({{b, c, r1}, {d, a, r0}}) do
      face[1] = {face[1][1], face[1][2], top, 0, (top - base) / scale}
      face[2] = {face[2][1], face[2][2], top, width / scale, (top - base) / scale}
      face[3] = {face[3][1], face[3][2], top + rise, width / (2 * scale), (top + rise - base) / scale}
      scene.polygon(gable, face, false)
    end
    if guess.mass then BLD.gableWin(scene, frame, top, rise, guess) end
  end
  return true
end

-- Low-poly solids in one paint atlas (cars: car_art.CAR_COLOURS, then glass 8 and tyre 9; the
-- yard: fast_art.YARD_COLOURS). A piece is placed by a frame (x, y, z, yaw counter-clockwise),
-- its faces wound counter-clockwise from outside, each in the middle of its atlas cell.
local SOLID = {}
function SOLID.frame(x, y, z, yaw)
  local c, s = math.cos(yaw), math.sin(yaw)
  return function(px, py, pz) return {x + px * c - py * s, y + px * s + py * c, z + pz} end
end
function SOLID.face(mesh, material, cell, T, pts, up)
  local u, poly = (cell + .5) / 16, {}
  for k, p in ipairs(pts) do
    local w = T(p[1], p[2], p[3])
    poly[k] = {w[1], w[2], w[3], u, .5}
  end
  mesh.polygon(material, poly, up)
end
-- A side profile (x along, z up; counter-clockwise) extruded across y0..y1: the caps in capCell,
-- the edge from point k in edgeCell(k) (or capCell). noCap0: leave the -y cap out.
function SOLID.extrude(mesh, material, T, ring, y0, y1, capCell, edgeCell, noCap0)
  local n, low, high = #ring, {}, {}
  for k = 1, n do
    low[k] = {ring[k][1], y0, ring[k][2]}
    high[n + 1 - k] = {ring[k][1], y1, ring[k][2]}
  end
  if not noCap0 then SOLID.face(mesh, material, capCell, T, low) end
  SOLID.face(mesh, material, capCell, T, high)
  for k = 1, n do
    local p, q = ring[k], ring[k % n + 1]
    SOLID.face(mesh, material, edgeCell and edgeCell(k) or capCell, T,
      {{p[1], y1, p[2]}, {q[1], y1, q[2]}, {q[1], y0, q[2]}, {p[1], y0, p[2]}})
  end
end
-- A box x0..x1, y0..y1, z0..z1 without its underside
function SOLID.box(mesh, material, cell, T, x0, y0, z0, x1, y1, z1)
  SOLID.extrude(mesh, material, T, {{x0, z0}, {x1, z0}, {x1, z1}, {x0, z1}}, y0, y1, cell, function(k)
    return cell end)
end
-- A square beam w thick from p to q ({x, y, z} in the frame), its ends open
function SOLID.beam(mesh, material, cell, T, p, q, w)
  local dx, dy, dz = q[1] - p[1], q[2] - p[2], q[3] - p[3]
  local l = math.sqrt(dx * dx + dy * dy + dz * dz)
  if l < EPS then return end
  dx, dy, dz = dx / l, dy / l, dz / l
  local ax, ay, az = dy, -dx, 0           -- d x up
  local al = math.sqrt(ax * ax + ay * ay)
  if al < .1 then ax, ay, az, al = 1, 0, 0, 1 end
  ax, ay, az = ax / al, ay / al, az / al
  local bx, by, bz = dy * az - dz * ay, dz * ax - dx * az, dx * ay - dy * ax   -- d x a
  local h, c = w / 2, {}
  for k = 1, 4 do
    local t = (k - .5) * math.pi / 2
    local ca, sb = math.cos(t) * h * 1.414, math.sin(t) * h * 1.414
    c[k] = {ax * ca + bx * sb, ay * ca + by * sb, az * ca + bz * sb}
  end
  for k = 1, 4 do
    local e, f = c[k], c[k % 4 + 1]
    SOLID.face(mesh, material, cell, T, {{p[1] + e[1], p[2] + e[2], p[3] + e[3]}, {p[1] + f[1], p[2] + f[2], p[3] + f[3]},
      {q[1] + f[1], q[2] + f[2], q[3] + f[3]}, {q[1] + e[1], q[2] + e[2], q[3] + e[3]}})
  end
end
-- An n-sided frustum round the frame's z axis from radius r0 at z0 to r1 at z1 (0: a cone),
-- a lid on top when r1 > 0, a floor under it when under (a mushroom's roof seen from below)
function SOLID.prism(mesh, material, cell, T, n, z0, z1, r0, r1, under)
  local bottom, top = {}, {}
  for k = 1, n do
    local t = (k - 1) * 2 * math.pi / n
    bottom[k] = {math.cos(t) * r0, math.sin(t) * r0, z0}
    top[k] = {math.cos(t) * r1, math.sin(t) * r1, z1}
  end
  for k = 1, n do
    local m = k % n + 1
    SOLID.face(mesh, material, cell, T, {bottom[k], bottom[m], top[m], top[k]})
  end
  if r1 > EPS then SOLID.face(mesh, material, cell, T, top, true) end
  if under then
    local floorRing = {}
    for k = n, 1, -1 do floorRing[#floorRing + 1] = bottom[k] end
    SOLID.face(mesh, material, under, T, floorRing)
  end
end

-- A parked car, 4.4 x 1.76 m: a body with a sloped bonnet and boot, a glasshouse with its
-- windscreen and roof, six-sided wheels. ~100 triangles.
local CAR_BODY = {{-2.15, .30}, {2.15, .30}, {2.22, .52}, {2.12, .74}, {1.05, .84}, {-1.75, .87}, {-2.17, .80},
  {-2.22, .52}}
local CAR_GLASS = {{-1.72, .84}, {1.02, .82}, {.22, 1.38}, {-1.22, 1.41}}
local function parkedCar(mesh, x, y, z, yaw, colour)
  local T = SOLID.frame(x, y, z, yaw)
  SOLID.extrude(mesh, 'car', T, CAR_BODY, -.88, .88, colour)
  SOLID.extrude(mesh, 'car', T, CAR_GLASS, -.76, .76, 8, function(k) return k == 3 and colour or 8 end)
  local wheel = {}
  for k = 1, 6 do
    local t = (k - 1) * math.pi / 3 + math.pi / 6
    wheel[k] = {math.cos(t) * .31, .31 + math.sin(t) * .31}
  end
  for _, wx in ipairs({-1.36, 1.36}) do
    local ring = {}
    for k, p in ipairs(wheel) do ring[k] = {p[1] + wx, p[2]} end
    SOLID.extrude(mesh, 'car', T, ring, .70, .92, 9, nil, true)
    -- the other side's wheel, the car turned round: its outer face is the +y cap again
    SOLID.extrude(mesh, 'car', SOLID.frame(x, y, z, yaw + math.pi), ring, .70, .92, 9, nil, true)
  end
end

-- Per source cell, once: its features deduplicated by id and sorted. The renderer's cell cache
-- keeps the cell table, so the four tiles of a 1 km cell share this work. Weak keys: nothing
-- is written into the source tables.
local prepared = setmetatable({}, {__mode = 'k'})
local KINDS = {'roads', 'junctions', 'buildings', 'areas', 'lines', 'points'}

local function collect(cells, pause)
  local lists = {roads = {}, junctions = {}, buildings = {}, areas = {}, lines = {}, points = {}}
  local seen, terrain = {}, {}
  for _, cell in ipairs(cells or {}) do
    if cell.terrain then terrain[#terrain + 1] = cell.terrain end
    for _, kind in ipairs(KINDS) do
      local output = lists[kind]
      seen[kind] = seen[kind] or {}
      for index, feature in ipairs(cell[kind] or {}) do
        local id = tostring(feature.id or index)
        if not seen[kind][id] then
          seen[kind][id], output[#output + 1] = true, feature
        end
      end
    end
    pause()
  end
  -- highway=track is stored as a path line. Draw it as a drivable ribbon. A bridge or
  -- tunnel stays a thin path: its deck is not the ground profile.
  local lines = {}
  for _, line in ipairs(lists.lines) do
    local tags = line.tags or {}
    local highway = (tags.highway or ''):gsub('_link$', '')
    if line.kind == 'path' and highway == 'track' and not ROADS.bridge(tags) and not ROADS.tunnel(tags) and tags.area ~= 'yes' then
      local grade = roadGrade(tags)
      lists.roads[#lists.roads + 1] = {id = 'track:' .. tostring(line.id), points = line.points,
        width = number(tags.width, TRACK_WIDTH[grade + 1] or 3.2), tags = tags, track = true}
    else
      lines[#lines + 1] = line
    end
  end
  lists.lines = lines
  for _, list in pairs(lists) do
    local ids = {}
    for _, feature in ipairs(list) do ids[feature] = tostring(feature.id or '') end
    table.sort(list, function(a, b) return ids[a] < ids[b] end)
  end
  return lists, terrain
end

-- spacing: metres between props along each sidewalk and footway; put(name, shape, x, y, z, yaw)
-- emits one. The lattice runs along the whole road from its first node, not the strip trimmed at
-- a junction (a tile trims only the junctions it sees: two tiles put the props out of step at
-- their seam). A sidewalk prop keeps 6 m from its strip's ends at a junction, 3 m where the
-- street runs on into its next way (a joint), a footway prop 3 m from the path's ends; every prop keeps off the carriageways, the other paths, the crossings and
-- the buildings. Footways (most of central Kyiv's sidewalks are mapped as their own ways) get them
-- just beside the paving, on the ground; a road's side tagged sidewalk=separate gets none (its
-- footway has them). Indoor, underground and covered paths get none.
local function pathOnGround(tags)
  if ROADS.bridge(tags) or ROADS.tunnel(tags) then return false end
  if (tags.indoor or 'no') ~= 'no' or (tags.covered or 'no') ~= 'no' then return false end
  if (tonumber(tags.layer) or 0) < 0 then return false end
  return tags.level == nil or tonumber(tags.level) == 0
end
local function pathCrossing(tags)
  return tags.footway == 'crossing' or tags.cycleway == 'crossing' or tags.path == 'crossing'
    or tags.footway == 'traffic_island' or (tags.crossing ~= nil and tags.crossing ~= 'no')
end
-- Squared distance from (px, py) to the segment a-b
local function pointSegment2(px, py, ax, ay, bx, by)
  local dx, dy = bx - ax, by - ay
  local len2 = dx * dx + dy * dy
  local t = len2 > EPS and math.max(0, math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2)) or 0
  return (ax + t * dx - px) ^ 2 + (ay + t * dy - py) ^ 2
end
-- Squared distance between the segments a-b and c-d (0 where they cross)
local function segmentSegment2(ax, ay, bx, by, cx, cy, dx, dy)
  local d1 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
  local d2 = (bx - ax) * (dy - ay) - (by - ay) * (dx - ax)
  local d3 = (dx - cx) * (ay - cy) - (dy - cy) * (ax - cx)
  local d4 = (dx - cx) * (by - cy) - (dy - cy) * (bx - cx)
  if (d1 > 0) ~= (d2 > 0) and (d3 > 0) ~= (d4 > 0) and d1 ~= 0 and d2 ~= 0 and d3 ~= 0 and d4 ~= 0 then return 0 end
  return math.min(pointSegment2(ax, ay, cx, cy, dx, dy), pointSegment2(bx, by, cx, cy, dx, dy),
    pointSegment2(cx, cy, ax, ay, bx, by), pointSegment2(dx, dy, ax, ay, bx, by))
end
-- Whether the capsule a-b (half length hl, midpoint mx, my) comes nearer than m to the segment
-- c-d: the midpoint first, the exact test only within reach of it
local function capsuleNear(ax, ay, bx, by, mx, my, hl, cx, cy, dx, dy, m)
  if pointSegment2(mx, my, cx, cy, dx, dy) >= (m + hl) ^ 2 then return false end
  return hl < 1e-6 or segmentSegment2(ax, ay, bx, by, cx, cy, dx, dy) < m * m
end
-- A prop's plan as a capsule round a segment of its own X axis, conservative for its bounds fp:
-- a face prop (turned with the path) the length of the model, radius half its depth; any other
-- (random yaw) a disc round its origin through its farthest corner. near, far: metres from the
-- origin to the capsule's edge toward the road (+Y) and away from it.
local function propFootprint(prop)
  if prop.capsule then return prop.capsule end
  local fp = prop.fp or {-.3, .3, -.3, .3}
  local c
  if prop.face then
    local r = (fp[4] - fp[3]) / 2
    c = {x0 = fp[1], x1 = fp[2], y = (fp[3] + fp[4]) / 2, r = r, near = fp[4], far = -fp[3]}
  else
    local r = math.sqrt(math.max(fp[1] ^ 2, fp[2] ^ 2) + math.max(fp[3] ^ 2, fp[4] ^ 2))
    c = {x0 = 0, x1 = 0, y = 0, r = r, near = r, far = r}
  end
  -- a prop turned away from its path reaches toward it by its back
  if prop.away then c.near, c.far = c.far, c.near end
  c.curb = prop.curb
  prop.capsule = c
  return c
end
local function walkSeparate(tags, side)
  local v = tags[side == 1 and 'sidewalk:left' or 'sidewalk:right'] or tags['sidewalk:both']
  if v == nil and tags['sidewalk:left'] == nil and tags['sidewalk:right'] == nil then v = tags.sidewalk end
  return v == 'separate'
end

-- america when there is no block, or the block is the tested North American mix.
function VEG.streetKit(look)
  local block = type(look) == 'table' and look.block or nil
  if block == 'mediterranean' or block == 'latin' or block == 'middle-east'
      or block == 'south-asia' or block == 'africa' then
    return 'med'
  end
  if block == nil or block == '' or block == 'north-america' or block == 'oceania' or block == 'general' then
    return 'america'
  end
  return 'europe'
end

-- Props and place sets this game has, once per kit. america reads VEG.props at the first call.
function VEG.streetHave(kit)
  VEG.haveKits = VEG.haveKits or {}
  local cached = VEG.haveKits[kit]
  if cached then return cached.props, cached.sets end
  local list = VEG.kits[kit] or VEG.props
  local props = {}
  for _, p in ipairs(list) do
    if not FS or FS:fileExists(p[1]) then props[#props + 1] = p end
  end
  local sets, custom = {}, VEG.kitSets[kit]
  for _, name in ipairs(VEG.propSets) do
    local source = custom and custom[name] or VEG[name]
    local have = {total = 0}
    for _, p in ipairs(source) do
      if p.none or (not FS or FS:fileExists(p[1])) and (not p.with or not FS or FS:fileExists(p.with[1])) then
        have[#have + 1] = p
        have.total = have.total + p[2]
      end
    end
    sets[name] = have
  end
  cached = {props = props, sets = sets}
  VEG.haveKits[kit] = cached
  return props, sets
end

-- The storefront spans (BLD.shopLinks) of one building on the wall p -> q, in metres from p,
-- whichever way the source ring runs; nil when the wall has none.
function VEG.shopSpans(own, p, q, length)
  if not own then return nil end
  local spans = own[BLD.wallKey(p, q)]
  if spans then return spans end
  spans = own[BLD.wallKey(q, p)]
  if not spans then return nil end
  local out = {}
  for k = #spans, 1, -1 do out[#out + 1] = {length - spans[k][2], length - spans[k][1]} end
  return out
end

function VEG.streetProps(strips, lines, buildings, segmentBins, rect, spacing, lift, walkWidth, ground, put, pause, context)
  context = context or {}
  spacing = math.max(0, tonumber(spacing) or 0)
  -- Plan neighbours too: ownership is applied only after conflict resolution. A
  -- local priority minimum makes the result independent of tile/generation order.
  local owned = rect
  rect = {rect[1] - 12, rect[2] - 12, rect[3] + 12, rect[4] + 12}
  local candidates, occupied = {}, {}
  -- the props this game has (all of them outside the game, where FS is absent)
  local props, sets = VEG.streetHave(VEG.streetKit(context.look))
  local total = 0
  for _, p in ipairs(props) do total = total + p[2] end
  local count = 0
  -- More furniture in yards and squares as the street step shortens (Balanced 12 m: 1)
  local dense = spacing > 0 and math.min(1.5, 12 / spacing) or 0
  -- the tile's buildings in 50 m bins, 0.6 m out from the walls (a footway along a wall).
  -- These set-up loops pause too: over a city tile's buildings, lines and strips they ran
  -- 13-22 ms without one (Kyiv stream bench).
  local walls = {}
  for _, building in ipairs(buildings) do
    pause()
    if ringsTouch(building.rings, rect) then
      local b = ringBounds(building.rings)
      local entry = {rings = building.rings, bounds = b}
      for by = math.floor((b[2] - 1) / 50), math.floor((b[4] + 1) / 50) do
        for bx = math.floor((b[1] - 1) / 50), math.floor((b[3] + 1) / 50) do
          local bin = walls[bx * 65536 + by] or {}
          walls[bx * 65536 + by], bin[#bin + 1] = bin, entry
        end
      end
    end
  end
  for _, area in ipairs(context.areas or NONE) do
    pause()
    if area.kind == 'water' or area.kind == 'parking' or (area.tags or NONE).amenity == 'parking' then
      local b = ringBounds(area.rings)
      if boundsTouch(b, rect, 1) then
        -- a car park keeps furniture out, not the lamps and trees at its edge
        local entry = {rings = area.rings, bounds = b, parking = area.kind ~= 'water'}
        for by = math.floor((b[2] - 1) / 50), math.floor((b[4] + 1) / 50) do
          for bx = math.floor((b[1] - 1) / 50), math.floor((b[3] + 1) / 50) do
            local bin = walls[bx * 65536 + by] or {}
            walls[bx * 65536 + by], bin[#bin + 1] = bin, entry
          end
        end
      end
    end
  end
  -- the ground a point stands on (park, square, paved, residential...) from the mapped areas,
  -- and the 50 m bins with a building in them (a town, not a field or a forest)
  local grounds, built, squares = {}, {}, {}
  for _, area in ipairs(context.areas or NONE) do
    pause()
    local tags = area.tags or NONE
    local kind = area.kind
    if kind == 'paved' and (tags.place == 'square' or tags.highway == 'pedestrian') then kind = 'square' end
    if kind == 'park' or kind == 'meadow' or kind == 'residential' or kind == 'square' or kind == 'forest'
        or kind == 'paved' then
      local b = ringBounds(area.rings)
      if boundsTouch(b, rect, 1) then
        local entry = {rings = area.rings, bounds = b, kind = kind}
        if kind == 'square' then squares[#squares + 1] = entry end
        -- a residential area spans kilometres: only the bins round this tile
        for by = math.floor(math.max(b[2], rect[2] - 50) / 50), math.floor(math.min(b[4], rect[4] + 50) / 50) do
          for bx = math.floor(math.max(b[1], rect[1] - 50) / 50), math.floor(math.min(b[3], rect[3] + 50) / 50) do
            local bin = grounds[bx * 65536 + by] or {}
            grounds[bx * 65536 + by], bin[#bin + 1] = bin, entry
          end
        end
      end
    end
  end
  -- footprint m2 of the buildings centred in each 50 m bin, and whether one of them is a block
  -- of flats or taller than 3 floors (a town's, not a village's)
  local footprint = {}
  for _, building in ipairs(buildings) do
    pause()
    local b = ringBounds(building.rings)
    if boundsTouch(b, rect, 100) then
      local ring, a2 = building.rings[1] or NONE, 0
      for k = 1, #ring do
        local p, q = ring[k], ring[k % #ring + 1]
        a2 = a2 + p[1] * q[2] - q[1] * p[2]
      end
      footprint[building] = a2 / 2
      local key = math.floor((b[1] + b[3]) / 100) * 65536 + math.floor((b[2] + b[4]) / 100)
      local bin = built[key] or {area = 0}
      built[key] = bin
      bin.area = bin.area + math.abs(a2) / 2
      bin.tall = bin.tall or (building.height or 0) >= 12 or FLATS[(building.tags or NONE).building] or false
    end
  end
  -- the most particular ground wins: a park drawn inside a residential area is a park
  local RANK = {square = 1, park = 2, forest = 3, meadow = 4, paved = 5, residential = 6}
  local function groundAt(x, y)
    local best
    for _, e in ipairs(grounds[math.floor(x / 50) * 65536 + math.floor(y / 50)] or NONE) do
      local b = e.bounds
      if (not best or RANK[e.kind] < RANK[best]) and x >= b[1] and x <= b[3] and y >= b[2] and y <= b[4]
          and inside(e.rings, x, y) then best = e.kind end
    end
    return best
  end
  -- a building within a bin or two of the point
  local function town(x, y)
    local bx, by = math.floor(x / 50), math.floor(y / 50)
    for dx = -1, 1 do
      for dy = -1, 1 do
        if built[(bx + dx) * 65536 + by + dy] then return true end
      end
    end
    return false
  end
  -- Houses round the point but no block of flats, and under a sixth of the ground built over
  -- (a city's blocks of flats: a fifth and more)
  local function village(x, y)
    local bx, by, area, any = math.floor(x / 50), math.floor(y / 50), 0, false
    for dx = -1, 1 do
      for dy = -1, 1 do
        local bin = built[(bx + dx) * 65536 + by + dy]
        if bin then
          if bin.tall then return false end
          area, any = area + bin.area, true
        end
      end
    end
    return any and area < 3600
  end
  -- the capsule a-b of radius r inside a building or nearer than 0.6 m to its wall
  local function inWall(bins, ax, ay, bx, by, mx, my, hl, r, furniture)
    local m = r + .6
    for _, w in ipairs(bins) do
      local b = w.bounds
      if (furniture or not w.parking) and math.max(ax, bx) >= b[1] - m and math.max(ay, by) >= b[2] - m and math.min(ax, bx) <= b[3] + m
          and math.min(ay, by) <= b[4] + m then
        if inside(w.rings, ax, ay) or inside(w.rings, bx, by) then return true end
        for _, ring in ipairs(w.rings) do
          local previous = ring[#ring]
          for _, p in ipairs(ring) do
            if capsuleNear(ax, ay, bx, by, mx, my, hl, previous[1], previous[2], p[1], p[2], m) then return true end
            previous = p
          end
        end
      end
    end
    return false
  end
  -- keep-out bands round polylines in 50 m bins: r metres either side of a segment
  local function band(bins, a, b, r)
    local dx, dy = b[1] - a[1], b[2] - a[2]
    local len2 = dx * dx + dy * dy
    local box = {math.min(a[1], b[1]), math.min(a[2], b[2]), math.max(a[1], b[1]), math.max(a[2], b[2])}
    if len2 < EPS or not boundsTouch(rect, box, r) then return end
    local entry = {a = a, dx = dx, dy = dy, len2 = len2, r = r}
    for by = math.floor((box[2] - r) / 50), math.floor((box[4] + r) / 50) do
      for bx = math.floor((box[1] - r) / 50), math.floor((box[3] + r) / 50) do
        local bin = bins[bx * 65536 + by] or {}
        bins[bx * 65536 + by], bin[#bin + 1] = bin, entry
      end
    end
  end
  -- the capsule a-b of radius r reaching into a band
  local function inBand(bins, ax, ay, bx, by, mx, my, hl, r)
    for _, s in ipairs(bins) do
      if capsuleNear(ax, ay, bx, by, mx, my, hl, s.a[1], s.a[2], s.a[1] + s.dx, s.a[2] + s.dy, s.r + r) then return true end
    end
    return false
  end
  -- the entries of every 50 m bin under the box round a-b (r out), keyed as bins (plus offset)
  local function near(bins, ax, ay, bx, by, r, offset)
    local x0, x1 = math.floor((math.min(ax, bx) - r) / 50), math.floor((math.max(ax, bx) + r) / 50)
    local y0, y1 = math.floor((math.min(ay, by) - r) / 50), math.floor((math.max(ay, by) + r) / 50)
    if x0 == x1 and y0 == y1 then return bins[(x0 + offset) * 65536 + y0 + offset] or NONE end
    local list = {}
    for bx_ = x0, x1 do
      for by_ = y0, y1 do
        for _, e in ipairs(bins[(bx_ + offset) * 65536 + by_ + offset] or NONE) do list[#list + 1] = e end
      end
    end
    return list
  end
  -- Surveyed trees, lamps and bus stops take precedence over inferred furniture. A street
  -- whose lamps are mapped gets no inferred lamp within 12 m of one (the row is every 30 m).
  local surveyedLamps = {}
  for _, p in ipairs(context.points or NONE) do
    pause()
    if p.pos and (p.kind == 'tree' or p.kind == 'lamp' or p.kind == 'stop') then
      local x, y = p.pos[1], p.pos[2]
      local r = p.kind == 'tree' and 3 or p.kind == 'stop' and 5 or 2
      band(occupied, {x - .001, y}, {x + .001, y}, r)
      if p.kind == 'lamp' then band(surveyedLamps, {x - .001, y}, {x + .001, y}, 12) end
    end
  end
  -- paths on the ground (their paving and 0.3 m more; a crossing 2 m either side) and the
  -- streets' sidewalks (a footway's prop does not stand on them)
  local paths, walks = {}, {}
  for _, line in ipairs(lines) do
    pause()
    local tags, points = line.tags or NONE, line.points or NONE
    if line.kind == 'path' and tags.area ~= 'yes' and pathOnGround(tags) then
      local r = pathCrossing(tags) and 2 or (tonumber(tags.width) or 2) / 2 + .3
      for k = 1, #points - 1 do band(paths, points[k], points[k + 1], r) end
    end
  end
  for _, strip in ipairs(strips) do
    pause()
    if strip.surface then
      for k = 1, #strip.points - 1 do
        local w = strip.walk[k] or NONE
        band(walks, strip.points[k], strip.points[k + 1], strip.hw + ((w[1] or w[-1]) and walkWidth or 0) + .3)
      end
    end
  end
  pause()
  -- one prop at lattice distance d of its road or path; t along the polyline segment from a
  -- (unit ux, uy), `side` of it
  local function place(seed, d, a, t, ux, uy, side, offset, z, name, footway, fixed, group)
    local h = ihash(seed, math.floor(d * 10 + .5), side + 2, 7)
    local pick, prop = h % math.max(1, total), props[1]
    for _, p in ipairs(props) do
      if pick < p[2] then prop = p; break end
      pick = pick - p[2]
    end
    if fixed and fixed.total then
      -- a place set: its own weighted pick
      local n = h % math.max(1, fixed.total)
      prop = nil
      for _, p in ipairs(fixed) do
        if n < p[2] then prop = p; break end
        n = n - p[2]
      end
      fixed = prop
    else
      prop = fixed or prop
    end
    if not prop then return end
    -- A village street is not a city's: its own sparse set
    if not fixed and village(a[1] + ux * t, a[2] + uy * t) then return place(seed, d, a, t, ux, uy, side, offset, z, name, footway, sets.village) end
    if prop.none then return end
    -- Rare fixtures have a street-scale cadence, never a dense random row.
    if not fixed and #props > 1 then
      local period = prop[1]:find('hydrant', 1, true) and 120
        or prop[1]:find('postbox', 1, true) and 180
        or prop[1]:find('bike_stand', 1, true) and 48
      if period and (footway or d % period >= math.min(spacing, 6)) then return end
      if footway and prop.curb then return end
    end
    local c = propFootprint(prop)
    local off, onGround = offset(c)
    if not off then return end
    local x = a[1] + ux * t - uy * off * side
    local y = a[2] + uy * t + ux * off * side
    if x < rect[1] or x >= rect[3] or y < rect[2] or y >= rect[4] then return end
    local shape = prop[1]
    if prop.kind == 'tree' and context.treeAt then
      shape = context.treeAt(x, y)
      if not shape then return end
    end
    -- a bench or a stand along its path, +Y to the road; the rest at random. Yaw turns local X
    -- to (cos, -sin) as BeamNG's MatrixF:setFromEuler does (clockwise from above).
    local yaw = prop.face and math.atan2(ux, uy) + side * math.pi / 2 + (prop.away and math.pi or 0) or (h % 628) / 100
    local cs, sn = math.cos(yaw), math.sin(yaw)
    local cx, cy = x + c.y * sn, y + c.y * cs
    local ax, ay, bx, by = cx + c.x0 * cs, cy - c.x0 * sn, cx + c.x1 * cs, cy - c.x1 * sn
    local r, mx, my, hl = c.r, (ax + bx) / 2, (ay + by) / 2, (c.x1 - c.x0) / 2
    if prop.kind == 'lamp' and inBand(near(surveyedLamps, ax, ay, bx, by, r, 0), ax, ay, bx, by, mx, my, hl, r) then return end
    if inWall(near(walls, ax, ay, bx, by, r + .6, 0), ax, ay, bx, by, mx, my, hl, r, not prop.kind)
        or inBand(near(occupied, ax, ay, bx, by, r, 0), ax, ay, bx, by, mx, my, hl, r)
        or inBand(near(paths, ax, ay, bx, by, r, 0), ax, ay, bx, by, mx, my, hl, r)
        or footway and inBand(near(walks, ax, ay, bx, by, r, 0), ax, ay, bx, by, mx, my, hl, r) then return end
    -- the carriageways on the ground (a bridge or a tunnel leaves the street under or over it)
    for _, segment in ipairs(near(segmentBins, ax, ay, bx, by, r, 32768)) do
      local sa = segment.a
      if segment.surface and capsuleNear(ax, ay, bx, by, mx, my, hl, sa[1], sa[2], sa[1] + segment.dx, sa[2] + segment.dy,
          segment.width / 2 + .3 + r) then return end
    end
    candidates[#candidates + 1] = {name = name, shape = shape, x = x, y = y, z = onGround and ground(x, y) or z(x, y), yaw = yaw,
      ax = ax, ay = ay, bx = bx, by = by, mx = mx, my = my, hl = hl, r = r,
      priority = prop.priority or 3, rank = h, kind = prop.kind or 'furniture', scale = prop.scale or 1, group = group}
    -- a group (a bench and its bin, a row of containers) does not thin itself
    if prop.with then
      candidates[#candidates].group = group or name
      place(seed, d, a, t + prop.gap, ux, uy, side, offset, z, name .. '_w', footway, prop.with, group or name)
    end
    return true
  end
  -- start: metres of the road before points[1]; margin1, margin2: metres kept clear at its ends
  local function walk(points, dist, seed, sides, margin1, margin2, start, offset, z, prefix, footway, step, fixed, phase)
    step, phase = step or spacing, phase or 0
    if step <= 0 then return end
    local length = dist[#dist] or 0
    for k = 1, #points - 1 do
      local a, b = points[k], points[k + 1]
      local seg = dist[k + 1] - dist[k]
      if seg > .5 then
        local ux, uy = (b[1] - a[1]) / seg, (b[2] - a[2]) / seg
        local d = math.ceil((dist[k] + start - phase) / step - 1e-6) * step + phase - start
        while d < dist[k + 1] do
          if d > margin1 and d < length - margin2 then
            for _, side in ipairs({1, -1}) do
              if sides(k, side) then
                local t = d - dist[k]
                place(seed, d + start, a, t, ux, uy, side, function(c) return offset(c, k, side) end,
                  z or function() return (a[3] or 0) + t / seg * ((b[3] or 0) - (a[3] or 0)) + lift end,
                  prefix .. '_' .. math.floor(d + start + .5) .. '_' .. side, footway, fixed)
              end
            end
          end
          d = d + step
        end
      end
      if k % 16 == 0 then pause() end
    end
  end
  for s, strip in ipairs(strips) do
    if strip.surface and (strip.dist[#strip.dist] or 0) > 14 then
      local hw, tags, id, joints = strip.hw, strip.tags or NONE, tostring(strip.road.id or s), strip.joints or NONE
      walk(strip.points, strip.dist, hash(id), function(k, side) return strip.walk[k][side] and not walkSeparate(tags, side) end,
        joints[1] and 3 or 6, joints[2] and 3 or 6, strip.start or 0, function(prop)
          -- A continuous 1.2 m pedestrian corridor; large objects use the outer verge.
          if prop.near + prop.far + (prop.curb and .35 or .1) + 1.2 > walkWidth then return hw + walkWidth + .35 + prop.near, true end
          return hw + (prop.curb and math.max(.45, .35 + prop.near) or walkWidth - math.max(.45, .1 + prop.far))
        end, nil, 'prop_' .. id)
      local major = tags.highway == 'primary' or tags.highway == 'secondary' or tags.highway == 'tertiary' or tags.highway == 'trunk'
      if context.lamps and tags.lit ~= 'no' and (tags.lit == 'yes' or major) and (not FS or FS:fileExists(LAMP)) then
        walk(strip.points, strip.dist, hash(id), function(k, side)
          return side == -1 or hw >= 6 and strip.walk[k][side]
        end, 6, 6, strip.start or 0, function(prop, k, side)
          if strip.walk[k][side] then return hw + walkWidth - .1 - prop.far end
          return hw + .35 + prop.near, true
        end,
          nil, 'streetlamp_' .. id, false, 30,
          {LAMP, kind = 'lamp', priority = 1, face = true, fp = {-.61, .61, -.32, .32}})
      end
      if context.tree and spacing > 0 then
        walk(strip.points, strip.dist, hash(id), function(k, side)
          return strip.walk[k][side] and not walkSeparate(tags, side)
        end, 10, 10, strip.start or 0, function() return hw + walkWidth + 3 end,
          ground, 'streettree_' .. id, false, math.max(24, math.ceil(spacing / 24) * 24), context.tree, 12)
      end
    end
    pause()
  end
  for l, line in ipairs(lines) do
    local tags, points = line.tags or NONE, line.points or NONE
    local way = tags.highway
    if line.kind == 'path' and (way == 'footway' or way == 'pedestrian' or way == 'path' or way == 'cycleway') and #points > 1
        and pathOnGround(tags) and not pathCrossing(tags) then
      local dist = {0}
      for k = 2, #points do
        dist[k] = dist[k - 1] + math.sqrt((points[k][1] - points[k - 1][1]) ^ 2 + (points[k][2] - points[k - 1][2]) ^ 2)
      end
      local half = (tonumber(tags.width) or 2) / 2
      -- What the path runs through picks its furniture: benches and bins in a park or a
      -- yard, a street's mix on a square or a paved frontage. A path out of town gets none.
      local mx, my = points[1][1], points[1][2]
      for k = 2, #points do
        if dist[k] >= dist[#dist] / 2 then
          local f = (dist[#dist] / 2 - dist[k - 1]) / math.max(EPS, dist[k] - dist[k - 1])
          mx = points[k - 1][1] + (points[k][1] - points[k - 1][1]) * f
          my = points[k - 1][2] + (points[k][2] - points[k - 1][2]) * f
          break
        end
      end
      local where, set, step = groundAt(mx, my), false, spacing
      if where == 'square' then set = sets.square
      elseif where == 'paved' or tags.footway == 'sidewalk' then set = nil
      elseif where == 'park' then set, step = sets.park, spacing * 2
      elseif town(mx, my) then set, step = sets.yard, spacing * 3 end
      if set ~= false and (way == 'path' or way == 'cycleway') then set, step = set or sets.park, step * 1.5 end
      if set ~= false then
        walk(points, dist, hash(tostring(line.id or l)), function() return true end, 3, 3, 0,
          function(prop) return half + .35 + prop.near end, ground, 'walkprop_' .. tostring(line.id or l), true, step, set)
      end
      if context.tree and spacing > 0 and tags.footway == 'sidewalk' then
        walk(points, dist, hash(tostring(line.id or l)), function() return true end, 10, 10, 0,
          function() return half + 3.3 end, ground, 'walktree_' .. tostring(line.id or l), true,
          math.max(24, math.ceil(spacing / 24) * 24), context.tree, 12)
      end
    end
    pause()
  end
  -- The nearest carriageway on the ground within r metres of its edge (service ways and living
  -- streets are a yard's driveways, not a street, unless `driveways`): segment, foot t (0..1).
  local function roadNear(x, y, r, driveways)
    local best, bestD, bestT
    for _, s in ipairs(segmentBins[(math.floor(x / 50) + 32768) * 65536 + math.floor(y / 50) + 32768] or NONE) do
      local way = (s.tags or NONE).highway
      if s.surface and (driveways or way ~= 'service' and way ~= 'living_street') then
        local t = math.max(0, math.min(1, ((x - s.a[1]) * s.dx + (y - s.a[2]) * s.dy) / s.len2))
        local d = math.sqrt((s.a[1] + t * s.dx - x) ^ 2 + (s.a[2] + t * s.dy - y) ^ 2) - s.width / 2
        if d < r and (not bestD or d < bestD) then best, bestD, bestT = s, d, t end
      end
    end
    return best, bestT
  end
  -- Round the buildings. A block of flats: a bench and a bin at its entrances on the walls that
  -- face away from the street, a site of containers in the yard. A shop: planters, bins and
  -- bike stands along its street walls, a skip behind it. A house: a wheelie bin or a bench by
  -- the road at its gate. Benches and containers turn their backs to the wall.
  if spacing > 0 then
    for index, building in ipairs(buildings) do
      local tags = building.tags or NONE
      local kind = tags.building
      local flats = FLATS[kind] or kind == 'yes' and (building.height or 0) >= 12
      local shop = not flats and (SHOPS[kind] or tags.shop ~= nil)
      local ring = building.rings[1]
      local b = ringBounds(building.rings)
      local house = HOUSES[kind] or kind == 'yes' and not flats and not shop and footprint[building]
        and math.abs(footprint[building]) >= 30 and math.abs(footprint[building]) <= 300 and village((b[1] + b[3]) / 2, (b[2] + b[4]) / 2)
      if (flats or shop or house) and ring and #ring >= 3 and boundsTouch(b, rect, 30) then
        local id = tostring(building.id or index):gsub('[^%w_]', '_')
        local seed = hash(id)
        if house then
          local cx, cy = (b[1] + b[3]) / 2, (b[2] + b[4]) / 2
          local s, t = roadNear(cx, cy, 30, true)
          if s and ihash(seed, 3, 1, 1) % 100 < 45 * dense then
            local length = math.sqrt(s.len2)
            local ux, uy = s.dx / length, s.dy / length
            local side = ux * (cy - s.a[2]) - uy * (cx - s.a[1]) > 0 and 1 or -1
            -- at the verge, past a sidewalk if the street has one on this side
            local fx, fy = s.a[1] + t * s.dx, s.a[2] + t * s.dy
            local walked = VEG.streetBlocked(walks, fx - uy * side * (s.width / 2 + 1), fy + ux * side * (s.width / 2 + 1))
            local verge = s.width / 2 + (walked and walkWidth + .5 or 1.2)
            place(seed, 1, s.a, t * length, ux, uy, side, function(c) return verge + c.near, true end, ground,
              'gate_' .. id, false, sets.gate)
          end
        else
          local area2 = 0
          for k = 1, #ring do
            local p, q = ring[k], ring[k % #ring + 1]
            area2 = area2 + p[1] * q[2] - q[1] * p[2]
          end
          -- place() puts side 1 to the left of an edge; a counter-clockwise ring's outside is right
          local out = area2 > 0 and -1 or 1
          local yardWalls, backDone = {}, false
          for k = 1, #ring do
            local p, q = ring[k], ring[k % #ring + 1]
            local length = math.sqrt((q[1] - p[1]) ^ 2 + (q[2] - p[2]) ^ 2)
            if length >= 6 then
              local ux, uy = (q[1] - p[1]) / length, (q[2] - p[2]) / length
              local nx, ny = -uy * out, ux * out
              local mx, my = (p[1] + q[1]) / 2 + nx * 8, (p[2] + q[2]) / 2 + ny * 8
              local street = roadNear(mx, my, shop and 18 or 6) ~= nil
              -- a block's mapped shop (the storefront experiment): the shop set along its span only
              local spans = not shop and VEG.shopSpans(context.shopLinks and context.shopLinks[building.id], p, q, length)
              if spans and roadNear(mx, my, 18) then
                local step = math.max(8, spacing * 1.25)
                for n, span in ipairs(spans) do
                  local count = math.max(1, math.floor((span[2] - span[1]) / step))
                  for e = 1, count do
                    if ihash(seed, k, n * 16 + e, 7) % 100 < 60 * dense then
                      place(seed, k * 100 + 50 + n * 4 + e, p, span[1] + (e - .5) * (span[2] - span[1]) / count, ux, uy, out,
                        function(c) return .9 + c.near, true end, ground, 'poifront_' .. id .. '_' .. k .. '_' .. n .. '_' .. e,
                        false, sets.shopFront)
                    end
                  end
                end
              elseif flats and not street and length >= 12 then
                yardWalls[#yardWalls + 1] = {k, length}
                local n = math.max(1, math.floor(length / 25))
                for e = 1, n do
                  if ihash(seed, k, e, 5) % 100 < 55 * dense then
                    -- beside the door (YARD.porch puts the step and canopy on it)
                    place(seed, k * 100 + e, p, (e - .5) * length / n + 2.6, ux, uy, out, function(c) return 1 + c.near, true end,
                      ground, 'entrance_' .. id .. '_' .. k .. '_' .. e, false, sets.entrance)
                  end
                end
              elseif shop and street then
                local step = math.max(8, spacing * 1.25)
                for e = 1, math.floor(length / step) do
                  if ihash(seed, k, e, 6) % 100 < 60 * dense then
                    place(seed, k * 100 + e, p, (e - .5) * step + (length % step) / 2, ux, uy, out,
                      function(c) return .9 + c.near, true end, ground, 'front_' .. id .. '_' .. k .. '_' .. e, false, sets.shopFront)
                  end
                end
              elseif shop and not backDone and ihash(seed, k, 0, 6) % 100 < 40 * dense then
                backDone = true
                place(seed, k * 100, p, length / 2, ux, uy, out, function(c) return 1.5 + c.near, true end, ground,
                  'back_' .. id .. '_' .. k, false, sets.backyard)
              end
            end
          end
          -- Three containers side by side out in the yard, by an end of a yard wall: the first
          -- free spot (the middle one placed) of the longest walls, both ends, 6, 9 or 3.5 m out.
          -- They outrank the benches and bins round them.
          if #yardWalls > 0 and ihash(seed, 9, 9, 9) % 100 < math.min(75, 50 * dense) then
            table.sort(yardWalls, function(u, v) return u[2] > v[2] or u[2] == v[2] and u[1] < v[1] end)
            local flip = ihash(seed, 9, 9, 8) % 2
            for w = 1, math.min(3, #yardWalls) do
              local k, length = yardWalls[w][1], yardWalls[w][2]
              local p, q = ring[k], ring[k % #ring + 1]
              local ux, uy = (q[1] - p[1]) / length, (q[2] - p[2]) / length
              local done = false
              for _, off in ipairs({6, 9, 3.5}) do
                for e = 0, 1 do
                  local t0 = (e + flip) % 2 == 0 and 4 or length - 7.7
                  local function bin(n)
                    return place(seed, 9000 + n, p, t0 + n * 1.85, ux, uy, out, function(c) return off + c.near, true end,
                      ground, 'bins_' .. id .. '_' .. n, false, sets.container, 'bins_' .. id)
                  end
                  if t0 >= 2 and bin(1) then
                    bin(0); bin(2)
                    done = true
                    break
                  end
                end
                if done then break end
              end
              if done then break end
            end
          end
        end
      end
      if index % 32 == 0 then pause() end
    end
    -- Squares: a loose lattice of planters, benches with bins, bollards and bike stands, 3.5 m
    -- in from the square's edge (a bench and its bin, a rack reach that far)
    local cell, taken = math.max(8, spacing), {}
    for _, e in ipairs(squares) do
      local b = e.bounds
      for gx = math.floor(math.max(b[1], rect[1]) / cell), math.floor(math.min(b[3], rect[3]) / cell) do
        for gy = math.floor(math.max(b[2], rect[2]) / cell), math.floor(math.min(b[4], rect[4]) / cell) do
          local h = ihash(77, gx, gy, 3)
          local x, y = (gx + .2 + (h % 60) / 100) * cell, (gy + .2 + (math.floor(h / 60) % 60) / 100) * cell
          if h % 100 < 50 * dense and not taken[gx * 65536 + gy] and inside(e.rings, x, y)
              and not nearEdge(e.rings, x, y, 3.5) then
            taken[gx * 65536 + gy] = true  -- squares drawn over each other: one prop a cell
            local turn = (math.floor(h / 3600) % 4) * math.pi / 2
            place(h, 0, {x, y}, 0, math.cos(turn), math.sin(turn), 1, function() return 0, true end, ground,
              'square_' .. gx .. '_' .. gy, false, sets.square)
          end
        end
      end
      pause()
    end
  end
  -- Index candidate capsules, not just their origins (a rack spans over four metres).
  local bins = {}
  for _, c in ipairs(candidates) do
    for by = math.floor((math.min(c.ay, c.by) - c.r - .4) / 50), math.floor((math.max(c.ay, c.by) + c.r + .4) / 50) do
      for bx = math.floor((math.min(c.ax, c.bx) - c.r - .4) / 50), math.floor((math.max(c.ax, c.bx) + c.r + .4) / 50) do
        local bin = bins[bx * 65536 + by] or {}
        bins[bx * 65536 + by], bin[#bin + 1] = bin, c
      end
    end
  end
  local reserved = {}
  for index, c in ipairs(candidates) do
    local clear = true
    for _, q in ipairs(near(bins, c.ax, c.ay, c.bx, c.by, c.r + .4, 0)) do
      local wins = q.priority < c.priority or q.priority == c.priority and (q.rank < c.rank or q.rank == c.rank and q.name < c.name)
      if wins and (not c.group or q.group ~= c.group) and capsuleNear(c.ax, c.ay, c.bx, c.by, c.mx, c.my, c.hl, q.ax, q.ay, q.bx, q.by, c.r + q.r + .4) then
        clear = false; break
      end
    end
    if clear then
      -- Used by vegetation scatter as well, so an avenue is not filled by yard trees.
      band(reserved, {c.ax - .001, c.ay}, {c.bx + .001, c.by}, c.r + 2)
      if c.x >= owned[1] and c.x < owned[3] and c.y >= owned[2] and c.y < owned[4] then
        put(c.name, c.shape, c.x, c.y, c.z, c.yaw, c.scale, c.kind)
        count = count + 1
      end
    end
    if index % 64 == 0 then pause() end
  end
  return count, reserved
end

function VEG.streetBlocked(bins, x, y)
  for _, s in ipairs(bins[math.floor(x / 50) * 65536 + math.floor(y / 50)] or NONE) do
    if pointSegment2(x, y, s.a[1], s.a[2], s.a[1] + s.dx, s.a[2] + s.dy) < s.r * s.r then return true end
  end
  return false
end

-- The yard of a block of flats as a Kyiv one looks from a window: cars along every driveway,
-- a playground (sand, swings, a slide, a sandpit under a mushroom, a carousel, a climbing frame)
-- with benches and a hedge on its road side, front gardens with shrubs behind a low railing under
-- the windows, a screen round the containers, lamps over the driveways and a spruce by some
-- doors. Runs after the street furniture and keeps out of its places; what it puts is reserved
-- against the tree scatter in turn. Procedural pieces take the 'yard' atlas (YARD.cell) and the
-- railing kinds (fast_style.RAILINGS); hedges, shrubs, lamps and trees are stock shapes.
local YARD = {cell = {red = 0, yellow = 1, blue = 2, green = 3, orange = 4, wood = 5, metal = 6, dark = 7,
  sand = 8, paint = 9, white = 10, rubber = 11, concrete = 12, bollard = 13, light = 14, brown = 15},
  hedge = '/levels/italy/art/shapes/trees/trees_italy/cypress_hedge_3m.dae', hedgeLong = 2.38, hedgeScale = .7,
  -- parallel bays along a driveway: one every carStep m, the car's side carGap m off its edge
  carStep = 5.7, carGap = .95, carsMax = 360, lampStep = 34, railH = .75,
  railings = {'railing_blue', 'railing_green', 'railing_dark'}, bench = BENCH[1],
  driveways = {service = true, living_street = true}}

-- a bin key as VEG.streetProps keeps its own (no offset)
local function yardBin(x, y) return math.floor(x / 50) * 65536 + math.floor(y / 50) end
-- a keep-out band a-b of radius r in bins as VEG.streetProps returns them (VEG.streetBlocked)
function YARD.reserve(bins, a, b, r)
  local dx, dy = b[1] - a[1], b[2] - a[2]
  local entry = {a = a, dx = dx, dy = dy, len2 = math.max(EPS, dx * dx + dy * dy), r = r}
  for by = math.floor((math.min(a[2], b[2]) - r) / 50), math.floor((math.max(a[2], b[2]) + r) / 50) do
    for bx = math.floor((math.min(a[1], b[1]) - r) / 50), math.floor((math.max(a[1], b[1]) + r) / 50) do
      local bin = bins[bx * 65536 + by] or {}
      bins[bx * 65536 + by], bin[#bin + 1] = bin, entry
    end
  end
end

-- Playground pieces round their own origin, x along the frame. Returns the radius they reach.
YARD.kit = {}
function YARD.kit.swing(mesh, T, h)
  local c, paint = YARD.cell, (h % 3 == 0) and YARD.cell.red or (h % 3 == 1) and YARD.cell.blue or YARD.cell.green
  for _, x in ipairs({-1.5, 1.5}) do
    SOLID.beam(mesh, 'yard', paint, T, {x, -.9, 0}, {x, 0, 2.3}, .08)
    SOLID.beam(mesh, 'yard', paint, T, {x, .9, 0}, {x, 0, 2.3}, .08)
  end
  SOLID.beam(mesh, 'yard', c.metal, T, {-1.6, 0, 2.3}, {1.6, 0, 2.3}, .09)
  for _, x in ipairs({-.65, .65}) do
    SOLID.beam(mesh, 'yard', c.metal, T, {x - .2, 0, 2.25}, {x - .2, 0, .5}, .025)
    SOLID.beam(mesh, 'yard', c.metal, T, {x + .2, 0, 2.25}, {x + .2, 0, .5}, .025)
    SOLID.box(mesh, 'yard', c.wood, T, x - .25, -.13, .44, x + .25, .13, .5)
  end
  return 2.1
end
function YARD.kit.slide(mesh, T, h)
  local c = YARD.cell
  local paint = (h % 2 == 0) and c.yellow or c.orange
  for _, p in ipairs({{-1.2, -.45}, {-1.2, .45}, {-.4, -.45}, {-.4, .45}}) do
    SOLID.beam(mesh, 'yard', c.blue, T, {p[1], p[2], 0}, {p[1], p[2], 1.9}, .08)
  end
  SOLID.box(mesh, 'yard', c.wood, T, -1.25, -.5, 1.1, -.35, .5, 1.16)
  -- a little pyramid roof over the deck and the ladder at the back
  local top = T(-.8, 0, 0)
  SOLID.prism(mesh, 'yard', paint, SOLID.frame(top[1], top[2], top[3], 0), 4, 1.9, 2.4, .75, 0, paint)
  for k = 0, 4 do SOLID.beam(mesh, 'yard', c.metal, T, {-1.2 - .02 * k, -.4, .22 * k}, {-1.2 - .02 * k, .4, .22 * k}, .04) end
  -- the chute: a sloped plank with its sides, down to +x
  local z0, z1 = 1.16, .3
  SOLID.face(mesh, 'yard', paint, T, {{-.35, -.3, z0}, {1.9, -.3, z1}, {1.9, .3, z1}, {-.35, .3, z0}}, true)
  SOLID.face(mesh, 'yard', paint, T, {{-.35, .3, z0}, {1.9, .3, z1}, {1.9, -.3, z1}, {-.35, -.3, z0}})
  for _, y in ipairs({-.32, .32}) do
    SOLID.box(mesh, 'yard', paint, T, -.35, y - .03, z0 - .1, -.3, y + .03, z0 + .2)
    SOLID.beam(mesh, 'yard', paint, T, {-.35, y, z0 + .12}, {1.9, y, z1 + .12}, .06)
  end
  SOLID.box(mesh, 'yard', paint, T, 1.9, -.32, 0, 2.3, .32, z1)
  return 2.4
end
function YARD.kit.sandpit(mesh, T, h)
  local c = YARD.cell
  for _, s in ipairs({{-1.3, -1.3, 1.3, -1.18}, {-1.3, 1.18, 1.3, 1.3}, {-1.3, -1.18, -1.18, 1.18}, {1.18, -1.18, 1.3, 1.18}}) do
    SOLID.box(mesh, 'yard', c.wood, T, s[1], s[2], -.05, s[3], s[4], .3)
  end
  SOLID.face(mesh, 'yard', c.sand, T, {{-1.18, -1.18, .18}, {1.18, -1.18, .18}, {1.18, 1.18, .18}, {-1.18, 1.18, .18}}, true)
  -- the mushroom over it: a post and an eight-sided cap, red or green
  SOLID.beam(mesh, 'yard', c.wood, T, {.95, .95, 0}, {.95, .95, 2.1}, .12)
  local cap = SOLID.frame(T(.95, .95, 0)[1], T(.95, .95, 0)[2], T(.95, .95, 0)[3], 0)
  SOLID.prism(mesh, 'yard', (h % 2 == 0) and c.red or c.green, cap, 8, 2.0, 2.65, 1.35, 0, c.brown)
  return 1.9
end
function YARD.kit.carousel(mesh, T, h)
  local c = YARD.cell
  SOLID.prism(mesh, 'yard', c.metal, T, 4, 0, .2, .25, .2)
  SOLID.prism(mesh, 'yard', (h % 2 == 0) and c.blue or c.red, T, 10, .2, .3, 1.05, 1.05)
  SOLID.beam(mesh, 'yard', c.metal, T, {0, 0, .3}, {0, 0, .9}, .07)
  for k = 0, 3 do
    local t = k * math.pi / 2
    SOLID.beam(mesh, 'yard', c.yellow, T, {0, 0, .85}, {math.cos(t) * .85, math.sin(t) * .85, .85}, .04)
    SOLID.beam(mesh, 'yard', c.yellow, T, {math.cos(t) * .85, math.sin(t) * .85, .85}, {math.cos(t) * .85, math.sin(t) * .85, .3}, .04)
  end
  return 1.3
end
function YARD.kit.climber(mesh, T, h)
  local c = YARD.cell
  local paint = (h % 3 == 0) and c.green or (h % 3 == 1) and c.red or c.blue
  for _, p in ipairs({{-1.2, -.6}, {1.2, -.6}, {-1.2, .6}, {1.2, .6}}) do
    SOLID.beam(mesh, 'yard', paint, T, {p[1], p[2], 0}, {p[1], p[2], 2.0}, .07)
  end
  for _, y in ipairs({-.6, .6}) do SOLID.beam(mesh, 'yard', paint, T, {-1.2, y, 2.0}, {1.2, y, 2.0}, .06) end
  for k = 0, 6 do
    local x = -1.05 + k * .35
    SOLID.beam(mesh, 'yard', c.metal, T, {x, -.6, 2.0}, {x, .6, 2.0}, .035)
  end
  for k = 1, 4 do
    for _, x in ipairs({-1.2, 1.2}) do SOLID.beam(mesh, 'yard', c.metal, T, {x, -.6, k * .4}, {x, .6, k * .4}, .035) end
  end
  return 1.6
end
function YARD.kit.springer(mesh, T, h)
  local c = YARD.cell
  SOLID.beam(mesh, 'yard', c.dark, T, {0, 0, 0}, {0, 0, .4}, .12)
  SOLID.box(mesh, 'yard', (h % 2 == 0) and c.yellow or c.light, T, -.4, -.12, .4, .4, .12, .7)
  SOLID.box(mesh, 'yard', (h % 2 == 0) and c.yellow or c.light, T, .2, -.1, .7, .4, .1, 1.0)
  return .7
end
function YARD.kit.bench(mesh, T)
  local c = YARD.cell
  -- a yard table under its own little mushroom, as in the photo's wooden pavilions
  SOLID.prism(mesh, 'yard', c.wood, T, 8, 0, .75, .1, .1)
  SOLID.prism(mesh, 'yard', c.wood, T, 8, .75, .8, .6, .6)
  SOLID.beam(mesh, 'yard', c.wood, T, {0, 0, .8}, {0, 0, 2.2}, .1)
  SOLID.prism(mesh, 'yard', c.brown, T, 8, 2.15, 2.75, 1.5, 0, c.wood)
  return 1.6
end
YARD.kitOrder = {'swing', 'slide', 'sandpit', 'carousel', 'climber', 'springer', 'bench', 'springer'}
-- A block's stair door at (x, y) on a wall along (ux, uy), its outside to side `out` of it (as
-- VEG.streetProps): a door leaf, a concrete step and a painted canopy over it
function YARD.porch(mesh, x, y, z, ux, uy, out, h)
  local c = YARD.cell
  local T = SOLID.frame(x, y, z, math.atan2(uy, ux))
  local function yy(a, b) return math.min(a * out, b * out), math.max(a * out, b * out) end
  local y0, y1 = yy(0, 1.7)
  SOLID.box(mesh, 'yard', c.concrete, T, -1.3, y0, -.3, 1.3, y1, .16)
  y0, y1 = yy(0, 1.45)
  local paint = ({c.paint, c.blue, c.concrete, c.green})[h % 4 + 1]
  SOLID.box(mesh, 'yard', paint, T, -1.45, y0, 2.78, 1.45, y1, 2.94)
  local yo = .03 * out
  local leaf = {{-.65, yo, .16}, {.65, yo, .16}, {.65, yo, 2.3}, {-.65, yo, 2.3}}
  if out > 0 then leaf = {leaf[4], leaf[3], leaf[2], leaf[1]} end
  SOLID.face(mesh, 'yard', (h % 3 == 0) and c.brown or c.dark, T, leaf)
end
-- A half-sphere bollard (the yellow or bare concrete domes that keep cars off a yard's corners)
function YARD.dome(mesh, T, cell)
  SOLID.prism(mesh, 'yard', cell, T, 6, -.05, .28, .34, .16)
end

-- ctx: rect, scene, decor (no collision: cars), ground, drapeRings, put(name, shape, x, y, z,
-- yaw, scale, kind), lists, strips, segmentBins, reserved (VEG.streetProps' bins or nil), spacing,
-- pause, have(set name), names (put names of the street furniture: container rows)
function YARD.build(ctx)
  local rect, lists, pause = ctx.rect, ctx.lists, ctx.pause
  local reserved = ctx.reserved or {}
  ctx.cars, ctx.kit = {}, {}
  local dense = ctx.spacing > 0 and math.min(1.5, 12 / ctx.spacing) or 0
  if dense <= 0 then return reserved, 0 end
  local halo = {rect[1] - 30, rect[2] - 30, rect[3] + 30, rect[4] + 30}
  -- blocks of flats (a yard is within 40 m of one) and every building as an obstacle, 50 m bins
  local flatsBins, wallBins = {}, {}
  local function addTo(bins, entry, b, m)
    for by = math.floor((b[2] - m) / 50), math.floor((b[4] + m) / 50) do
      for bx = math.floor((b[1] - m) / 50), math.floor((b[3] + m) / 50) do
        local bin = bins[bx * 65536 + by] or {}
        bins[bx * 65536 + by], bin[#bin + 1] = bin, entry
      end
    end
  end
  local blocks = {}
  for _, building in ipairs(lists.buildings) do
    local b = ringBounds(building.rings)
    if boundsTouch(b, halo, 40) then
      local entry = {rings = building.rings, bounds = b, building = building}
      addTo(wallBins, entry, b, 1)
      local kind = (building.tags or NONE).building
      if FLATS[kind] or kind == 'yes' and (building.height or 0) >= 12 then
        addTo(flatsBins, entry, b, 40)
        blocks[#blocks + 1] = entry
      end
    end
  end
  if #blocks == 0 then return reserved, 0 end
  local function yard(x, y)
    for _, e in ipairs(flatsBins[yardBin(x, y)] or NONE) do
      local b = e.bounds
      if x > b[1] - 40 and x < b[3] + 40 and y > b[2] - 40 and y < b[4] + 40 then return true end
    end
    return false
  end
  local function inBuilding(x, y, m)
    for _, e in ipairs(wallBins[yardBin(x, y)] or NONE) do
      local b = e.bounds
      if x >= b[1] - m and x <= b[3] + m and y >= b[2] - m and y <= b[4] + m
          and (inside(e.rings, x, y) or m > 0 and nearEdge(e.rings, x, y, m)) then return true end
    end
    return false
  end
  -- carriageways on the ground within `m` of their edge
  local function onRoad(x, y, m)
    for _, s in ipairs(ctx.segmentBins[(math.floor(x / 50) + 32768) * 65536 + math.floor(y / 50) + 32768] or NONE) do
      if s.surface then
        local t = math.max(0, math.min(1, ((x - s.a[1]) * s.dx + (y - s.a[2]) * s.dy) / s.len2))
        if (s.a[1] + t * s.dx - x) ^ 2 + (s.a[2] + t * s.dy - y) ^ 2 < (s.width / 2 + m) ^ 2 then return true end
      end
    end
    return false
  end
  -- footpaths, playgrounds, car parks, water and mapped doors as keep-outs
  local paths, places = {}, {}
  for _, line in ipairs(lists.lines) do
    local tags = line.tags or NONE
    if line.kind == 'path' and pathOnGround(tags) and boundsTouch(ringBounds({line.points}), halo, 5) then
      local r = (tonumber(tags.width) or 2) / 2 + .2
      for k = 1, #line.points - 1 do YARD.reserve(paths, line.points[k], line.points[k + 1], r) end
    end
  end
  local playgrounds = {}
  for _, area in ipairs(lists.areas) do
    local tags = area.tags or NONE
    if (area.kind == 'playground' or area.kind == 'water' or area.kind == 'parking' or tags.amenity == 'parking')
        and ringsTouch(area.rings, halo) then
      local entry = {rings = area.rings, bounds = ringBounds(area.rings), area = area}
      addTo(places, entry, entry.bounds, 1)
      if area.kind == 'playground' then playgrounds[#playgrounds + 1] = entry end
    end
  end
  local doors, surveyedLamps = {}, {}
  for _, point in ipairs(lists.points) do
    local p = point.pos
    if p and p[1] > halo[1] and p[1] < halo[3] and p[2] > halo[2] and p[2] < halo[4] then
      if point.kind == 'lamp' then
        -- a mapped yard lamp stands for the driveway's own (one every 34 m)
        YARD.reserve(surveyedLamps, {p[1] - .001, p[2]}, {p[1] + .001, p[2]}, 14)
      elseif point.kind == 'entrance' then
        doors[#doors + 1] = point
        YARD.reserve(paths, {p[1] - .001, p[2]}, {p[1] + .001, p[2]}, 2.5)
      elseif point.kind == 'playground' then
        -- a playground drawn as a node: a 9 m round one
        local ring = {}
        for k = 1, 12 do
          local t = k * math.pi / 6
          ring[k] = {p[1] + math.cos(t) * 9, p[2] + math.sin(t) * 9}
        end
        local entry = {rings = {ring}, bounds = ringBounds({ring}), area = point}
        addTo(places, entry, entry.bounds, 1)
        playgrounds[#playgrounds + 1] = entry
      end
    end
  end
  local function inPlace(x, y)
    for _, e in ipairs(places[yardBin(x, y)] or NONE) do
      local b = e.bounds
      if x >= b[1] and x <= b[3] and y >= b[2] and y <= b[4] and inside(e.rings, x, y) then return true end
    end
    return false
  end
  local function free(x, y)
    return not VEG.streetBlocked(reserved, x, y) and not VEG.streetBlocked(paths, x, y) and not inPlace(x, y)
  end
  local count = 0
  local function stock(name, shape, x, y, yaw, scale, kind)
    if x < rect[1] or x >= rect[3] or y < rect[2] or y >= rect[4] then return end
    ctx.put(name, shape, x, y, ctx.ground(x, y), yaw, scale, kind)
    count = count + 1
  end

  -- the container rows the street furniture put (their sites stay open)
  local function nearBins(x, y)
    for _, row in ipairs(ctx.containers or NONE) do
      if (row.x - x) ^ 2 + (row.y - y) ^ 2 < 16 then return true end
    end
    return false
  end
  -- 1. Front gardens under the windows of a block's yard walls: shrubs in a strip .6-4.5 m out,
  -- a low railing round it, a gap at every door (mapped, or every 25 m as the benches stand)
  for _, e in ipairs(blocks) do
    local ring = cleanRing(e.rings[1])
    if #ring >= 3 and boundsTouch(e.bounds, rect, 10) then
      local id = tostring(e.building.id or ''):gsub('[^%w_]', '_')
      local seed = hash('garden' .. id)
      local area2 = 0
      for k = 1, #ring do
        local p, q = ring[k], ring[k % #ring + 1]
        area2 = area2 + p[1] * q[2] - q[1] * p[2]
      end
      local out = area2 > 0 and -1 or 1
      local railing = YARD.railings[seed % #YARD.railings + 1]
      for k = 1, #ring do
        local p, q = ring[k], ring[k % #ring + 1]
        local length = math.sqrt((q[1] - p[1]) ^ 2 + (q[2] - p[2]) ^ 2)
        if length >= 12 then
          local ux, uy = (q[1] - p[1]) / length, (q[2] - p[2]) / length
          local nx, ny = -uy * out, ux * out      -- to the outside, as VEG.streetProps' side `out`
          local mx, my = (p[1] + q[1]) / 2, (p[2] + q[2]) / 2
          -- a yard wall: no street (a driveway does not count) within 14 m
          local street = false
          for _, s in ipairs(ctx.segmentBins[(math.floor((mx + nx * 8) / 50) + 32768) * 65536 + math.floor((my + ny * 8) / 50) + 32768] or NONE) do
            local way = (s.tags or NONE).highway
            if s.surface and not YARD.driveways[way] then
              local t = math.max(0, math.min(1, ((mx + nx * 8 - s.a[1]) * s.dx + (my + ny * 8 - s.a[2]) * s.dy) / s.len2))
              if (s.a[1] + t * s.dx - mx - nx * 8) ^ 2 + (s.a[2] + t * s.dy - my - ny * 8) ^ 2 < (s.width / 2 + 6) ^ 2 then street = true end
            end
          end
          if not street then
            -- doors on this wall: mapped ones, else the benches' every 25 m; a porch at each
            local gaps = {}
            for _, door in ipairs(doors) do
              local dx, dy = door.pos[1] - p[1], door.pos[2] - p[2]
              local s, o = dx * ux + dy * uy, dx * nx + dy * ny
              if s > 1.5 and s < length - 1.5 and math.abs(o) < 1.5 then gaps[#gaps + 1] = s end
            end
            if #gaps == 0 then
              local m = math.max(1, math.floor(length / 25))
              for g = 1, m do gaps[#gaps + 1] = (g - .5) * length / m end
            end
            table.sort(gaps)
            for g, s in ipairs(gaps) do
              local x, y = p[1] + ux * s, p[2] + uy * s
              YARD.porch(ctx.scene, x, y, ctx.ground(x + nx * .8, y + ny * .8), ux, uy, out, ihash(seed, k, g, 7))
              YARD.reserve(reserved, {x - ux * 1.3 + nx, y - uy * 1.3 + ny}, {x + ux * 1.3 + nx, y + uy * 1.3 + ny}, 1)
            end
            -- how deep the garden can be here: up to 4.5 m, 60 cm short of a road, path or wall
            local depth = 4.5
            for _, f in ipairs({.25, .5, .75}) do
              local bx, by = p[1] + ux * length * f, p[2] + uy * length * f
              for dd = 1.25, 4.5, .25 do
                local x, y = bx + nx * (dd + .6), by + ny * (dd + .6)
                if dd < depth and (onRoad(x, y, 0) or VEG.streetBlocked(paths, x, y) or inPlace(x, y)
                    or nearBins(x, y) or inBuilding(x, y, 0)) then depth = dd end
              end
            end
            if depth >= 1.6 and ihash(seed, k, 1, 1) % 100 < 70 then
              local runs, from = {}, 1.5
              for _, g in ipairs(gaps) do
                if g - 2.2 - from >= 3 then runs[#runs + 1] = {from, g - 2.2} end
                from = math.max(from, g + 2.2)
              end
              if length - 1.5 - from >= 3 then runs[#runs + 1] = {from, length - 1.5} end
              for r, run in ipairs(runs) do
                local z0, z1 = run[1], run[2]
                -- the railing: along the front and back to the wall at both ends
                local corners = {{z0, .6}, {z0, depth}, {z1, depth}, {z1, .6}}
                for c = 1, 3 do
                  local a, b = corners[c], corners[c + 1]
                  local ax, ay = p[1] + ux * a[1] + nx * a[2], p[2] + uy * a[1] + ny * a[2]
                  local bx, by = p[1] + ux * b[1] + nx * b[2], p[2] + uy * b[1] + ny * b[2]
                  local seg = math.sqrt((bx - ax) ^ 2 + (by - ay) ^ 2)
                  local pieces = math.max(1, math.ceil(seg / 4))
                  for m = 0, pieces - 1 do
                    local fa, fb = m / pieces, (m + 1) / pieces
                    local x0, y0 = ax + (bx - ax) * fa, ay + (by - ay) * fa
                    local x1, y1 = ax + (bx - ax) * fb, ay + (by - ay) * fb
                    local g0, g1 = ctx.ground(x0, y0) - .05, ctx.ground(x1, y1) - .05
                    local u0, u1 = seg * fa, seg * fb
                    ctx.scene.polygon(railing, {{x0, y0, g0, u0, 0}, {x1, y1, g1, u1, 0}, {x1, y1, g1 + YARD.railH, u1, 1},
                      {x0, y0, g0 + YARD.railH, u0, 1}}, false)
                  end
                end
                YARD.reserve(reserved, {p[1] + ux * z0 + nx * depth, p[2] + uy * z0 + ny * depth},
                  {p[1] + ux * z1 + nx * depth, p[2] + uy * z1 + ny * depth}, .8)
                -- shrubs inside: one every ~2.6 m in two loose rows, now and then a spruce
                local shrubs = ctx.have and ctx.have('bush') or NONE
                if #shrubs > 0 then
                  for s = z0 + 1.2, z1 - 1, 2.6 do
                    local h = ihash(seed, k * 1000 + r, math.floor(s * 10), 3)
                    local o = (h % 2 == 0) and math.min(2, depth / 2) or math.max(1.6, depth - 1.2)
                    local x, y = p[1] + ux * s + nx * o, p[2] + uy * s + ny * o
                    if h % 100 < 70 then
                      stock('shrub_' .. id .. '_' .. k .. '_' .. math.floor(s * 10), shrubs[h % #shrubs + 1], x, y,
                        (h % 628) / 100, .45 + (h % 30) / 100, 'tree')
                    end
                  end
                end
                pause()
              end
              -- a spruce by a door now and then (the blue spruces of Soviet yards)
              local firs = ctx.have and ctx.have('fir') or NONE
              if #firs > 0 then
                for g, s in ipairs(gaps) do
                  if ihash(seed, k, g, 9) % 100 < 22 then
                    local x, y = p[1] + ux * (s + 3.4) + nx * 3, p[2] + uy * (s + 3.4) + ny * 3
                    if not onRoad(x, y, 1.5) and free(x, y) then
                      stock('spruce_' .. id .. '_' .. k .. '_' .. g, firs[#firs], x, y, ihash(seed, k, g, 8) % 628 / 100,
                        .55, 'tree')
                      YARD.reserve(reserved, {x - .001, y}, {x + .001, y}, 3)
                    end
                  end
                end
              end
            end
          end
        end
      end
    end
  end

  -- 2. Lamps over the driveways: one side, every lampStep m, kept clear of the cars after them
  local lamps = ctx.lamp and (not FS or FS:fileExists(ctx.lamp))
  -- 3. Cars along both sides of a wide driveway, one side (by the way's hash) of a narrow one
  local cars = 0
  for s, strip in ipairs(ctx.strips) do
    local tags = strip.tags or NONE
    local length = strip.dist[#strip.dist] or 0
    if strip.surface and YARD.driveways[tags.highway] and length > 12
        and boundsTouch(ringBounds({strip.points}), halo, 5) then
      local id = tostring(strip.road.id or s)
      local seed = hash('yard' .. id)
      local both = strip.hw * 2 >= 5.5
      local oneSide = seed % 2 == 0 and 1 or -1
      local points, dist = strip.points, strip.dist
      -- two domes either side of the mouth where it meets another way, now and then
      local joints = strip.joints or NONE
      for e = 1, 2 do
        local a = e == 1 and points[1] or points[#points]
        local b = e == 1 and points[2] or points[#points - 1]
        local l = math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2)
        if not joints[e] and l > 3 and ihash(seed, e, 0, 41) % 100 < 45 then
          local ux, uy = (b[1] - a[1]) / l, (b[2] - a[2]) / l
          local cell = ihash(seed, e, 1, 41) % 3 == 0 and YARD.cell.concrete or YARD.cell.bollard
          for _, side in ipairs({1, -1}) do
            for m = 0, 1 do
              local along, off = .9 + m * 1.3, strip.hw + .55
              local x, y = a[1] + ux * along - uy * off * side, a[2] + uy * along + ux * off * side
              if x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4] and not onRoad(x, y, .3)
                  and not inBuilding(x, y, .5) and free(x, y) then
                YARD.dome(ctx.scene, SOLID.frame(x, y, ctx.ground(x, y), 0), cell)
                YARD.reserve(reserved, {x - .001, y}, {x + .001, y}, .7)
              end
            end
          end
        end
      end
      for k = 1, #points - 1 do
        local a, b = points[k], points[k + 1]
        local seg = dist[k + 1] - dist[k]
        if seg > .5 then
          local ux, uy = (b[1] - a[1]) / seg, (b[2] - a[2]) / seg
          local d = math.ceil((dist[k] + (strip.start or 0)) / YARD.carStep) * YARD.carStep - (strip.start or 0)
          while d < dist[k + 1] do
            local t = d - dist[k]
            if d > 6 and d < length - 6 then
              local cx, cy = a[1] + ux * t, a[2] + uy * t
              if lamps and math.floor(d / YARD.carStep) % math.floor(YARD.lampStep / YARD.carStep) == seed % 6 then
                local side = -oneSide
                local off = strip.hw + .5
                local lx, ly = cx - uy * off * side, cy + ux * off * side
                if yard(lx, ly) and not inBuilding(lx, ly, .8) and free(lx, ly) and not onRoad(lx, ly, .2)
                    and not VEG.streetBlocked(surveyedLamps, lx, ly) then
                  YARD.reserve(reserved, {lx - .001, ly}, {lx + .001, ly}, 1.2)
                  -- the lamp's arm over the driveway (lamp1: its +Y)
                  stock('yardlamp_' .. id .. '_' .. math.floor(d), ctx.lamp, lx, ly, math.atan2(uy * side, -ux * side), 1, 'lamp')
                end
              end
              -- a narrow one: its side by the hash, or the other where that one has no room
              local done = false
              for _, side in ipairs({oneSide, -oneSide}) do
                local h = ihash(seed, math.floor(d * 10 + .5), side + 2, 31)
                if (both or not done) and h % 100 < 74 * math.min(1, dense) and cars < YARD.carsMax then
                  local off = strip.hw + YARD.carGap + .88
                  local x, y = cx - uy * off * side, cy + ux * off * side
                  local yaw = math.atan2(uy, ux) + (h % 7 < 2 and math.pi or 0)
                  local ok = x > rect[1] - 3 and x < rect[3] + 3 and y > rect[2] - 3 and y < rect[4] + 3 and yard(x, y)
                  local c, sn = math.cos(yaw), math.sin(yaw)
                  if ok then
                    for _, q in ipairs({{0, 0}, {-2.2, -.9}, {2.2, -.9}, {2.2, .9}, {-2.2, .9}, {-1.1, 0}, {1.1, 0}}) do
                      local px, py = x + q[1] * c - q[2] * sn, y + q[1] * sn + q[2] * c
                      if inBuilding(px, py, .6) or onRoad(px, py, .05) or not free(px, py) then ok = false; break end
                    end
                  end
                  if ok then
                    parkedCar(ctx.decor, x, y, ctx.ground(x, y) + .02, yaw, math.floor(h / 100) % 8)
                    ctx.cars[#ctx.cars + 1] = {x, y, yaw}
                    done = true
                    YARD.reserve(reserved, {x - c * 2.2, y - sn * 2.2}, {x + c * 2.2, y + sn * 2.2}, 1)
                    cars = cars + 1
                  end
                end
              end
            end
            d = d + YARD.carStep
          end
        end
      end
      pause()
    end
  end

  -- 4. Playgrounds: sand, a piece of the kit on each free 5.5 m slot inside, benches round the
  -- edge looking in, a hedge on the sides that face a road
  for index, e in ipairs(playgrounds) do
    local ring = cleanRing(e.rings[1])
    if #ring >= 3 and boundsTouch(e.bounds, rect, 4) then
      ctx.drapeRings('sand', e.rings, .03)
      local id = tostring((e.area or NONE).id or index):gsub('[^%w_]', '_')
      local seed = hash('play' .. id)
      local frame = footprintFrame(ring)
      local placed, n = {}, 0
      local maxKit = math.max(1, math.min(9, math.floor(frame.area / 28 * math.min(1, dense))))
      for v = frame.v0 + 2.6, frame.v1 - 2.4, 5.5 do
        for u = frame.u0 + 2.6, frame.u1 - 2.4, 5.5 do
          if n < maxKit then
            local x, y = u * frame.ax + v * frame.bx, u * frame.ay + v * frame.by
            local kind = YARD.kitOrder[(n + seed) % #YARD.kitOrder + 1]
            local r = ({swing = 2.1, slide = 2.4, sandpit = 1.9, carousel = 1.3, climber = 1.6, springer = .7, bench = 1.6})[kind]
            local fits = inside(e.rings, x, y) and not nearEdge(e.rings, x, y, r + .3) and not inBuilding(x, y, r + .5)
              and not onRoad(x, y, r)
            for _, q in ipairs(placed) do
              if (q[1] - x) ^ 2 + (q[2] - y) ^ 2 < (q[3] + r + .8) ^ 2 then fits = false end
            end
            if fits then
              n = n + 1
              placed[#placed + 1] = {x, y, r}
              local yaw = math.atan2(frame.ay, frame.ax) + (ihash(seed, n, 1, 2) % 2) * math.pi
              YARD.kit[kind](ctx.scene, SOLID.frame(x, y, ctx.ground(x, y), yaw), ihash(seed, n, 3, 4))
              ctx.kit[#ctx.kit + 1] = {x, y, kind}
            end
          end
        end
        pause()
      end
      -- round the edge: benches inside looking in; a hedge just inside where a carriageway runs
      -- within 8 m outside
      local area2 = 0
      for k = 1, #ring do
        local p, q = ring[k], ring[k % #ring + 1]
        area2 = area2 + p[1] * q[2] - q[1] * p[2]
      end
      local inward = area2 > 0 and 1 or -1      -- the inside is left of a counter-clockwise edge
      for k = 1, #ring do
        local p, q = ring[k], ring[k % #ring + 1]
        local length = math.sqrt((q[1] - p[1]) ^ 2 + (q[2] - p[2]) ^ 2)
        if length >= 4 then
          local ux, uy = (q[1] - p[1]) / length, (q[2] - p[2]) / length
          local nx, ny = -uy * inward, ux * inward
          local mx, my = (p[1] + q[1]) / 2, (p[2] + q[2]) / 2
          if onRoad(mx - nx * 8, my - ny * 8, 0) or onRoad(mx - nx * 4, my - ny * 4, 0) then
            local step = YARD.hedgeLong * YARD.hedgeScale
            for s = step / 2 + .6, length - step / 2 - .6, step do
              local x, y = p[1] + ux * s + nx * .7, p[2] + uy * s + ny * .7
              if not VEG.streetBlocked(reserved, x, y) and not VEG.streetBlocked(paths, x, y) and not onRoad(x, y, .5) then
                stock('playhedge_' .. id .. '_' .. k .. '_' .. math.floor(s * 10), YARD.hedge, x, y, math.atan2(-uy, ux),
                  YARD.hedgeScale, 'hedge')
                YARD.reserve(reserved, {x - ux, y - uy}, {x + ux, y + uy}, .6)
              end
            end
          elseif ihash(seed, k, 5, 6) % 100 < 60 then
            local x, y = mx + nx * 1.1, my + ny * 1.1
            local clear = true
            for _, q in ipairs(placed) do
              if (q[1] - x) ^ 2 + (q[2] - y) ^ 2 < (q[3] + 1.6) ^ 2 then clear = false end
            end
            if clear then stock('playbench_' .. id .. '_' .. k, YARD.bench, x, y, math.atan2(nx, ny), 1, 'furniture') end
          end
        end
      end
      -- trees keep off the sand: the whole playground is reserved (a band per edge would leave
      -- its middle open; the tree scatter tests the playground areas itself, see blockers)
    end
  end

  -- 5. The container site: a screen of the same railing behind the row and at its ends
  for _, row in ipairs(ctx.containers or NONE) do
    local x, y, yaw = row.x, row.y, row.yaw
    -- stock yaw: +Y is (sin, cos); the row runs along local X (cos, -sin); the screen is behind
    local ax, ay, bx, by = math.cos(yaw), -math.sin(yaw), math.sin(yaw), math.cos(yaw)
    local railing = 'railing_blue'
    local half, back, front = 3.1, -.85, .9
    local pts = {{-half, front}, {-half, back}, {half, back}, {half, front}}
    for c = 1, 3 do
      local a, b = pts[c], pts[c + 1]
      local x0, y0 = x + ax * a[1] + bx * a[2], y + ay * a[1] + by * a[2]
      local x1, y1 = x + ax * b[1] + bx * b[2], y + ay * b[1] + by * b[2]
      local seg = math.sqrt((x1 - x0) ^ 2 + (y1 - y0) ^ 2)
      local g0, g1 = ctx.ground(x0, y0) - .05, ctx.ground(x1, y1) - .05
      ctx.scene.polygon(railing, {{x0, y0, g0, 0, 0}, {x1, y1, g1, seg, 0}, {x1, y1, g1 + 1.5, seg, 1}, {x0, y0, g0 + 1.5, 0, 1}}, false)
    end
  end
  ctx.yardCars = cars
  return reserved, count
end

-- Same numbers as fast_profile: 4.5 m of headroom under the deepest soffit (a main road's
-- 1.5 m girder), plus a little slack so a sampled footprint does not fall short of it.
-- A street slab is 1 m and keeps a little more air. The grade limits keep the rise on a
-- ramp a truck can drive; clearance still wins, and the rise is capped so a bad pack
-- cannot throw the deck up.
-- A road passes under a deck only from `below` m under it: an old pack keeps ~2 m (a pack's
-- clearance solve and live.lua's BRIDGE_CLEAR more), and a road level with the deck is a slip
-- road joining or leaving it, at any angle (Mykoly Mikhnovskoho at the Druzhby Narodiv junction
-- rose 12 m over its own merging link and the trunk at its gore: a wall across the road for the
-- other carriageway).
local DECK_CLEAR = {gap = 6.0, slack = .1, overhang = 2, cap = 40, bin = 32, below = 1}
local DECK_GRADE = {motorway = .05, trunk = .05, primary = .06, secondary = .06, tertiary = .07,
  motorway_link = .07, trunk_link = .07, primary_link = .07, secondary_link = .07}

local function deckLevel(tags)
  if ROADS.tunnel(tags) then return -1 end
  if not ROADS.bridge(tags) then return 0 end
  local text = tostring(tags.layer or '1'):match('^%s*([%+%-]?%d+%.?%d*)')
  local value = tonumber(text or '')
  if not value or value ~= value then value = 1 end
  value = math.abs(value)
  if value < 1 then value = 1 end
  return value
end

local function deckGrade(tags)
  return DECK_GRADE[tags.highway or ''] or .08
end

-- A pack built before the clearance solve stores the deck about 2 m above the road under it.
-- The soffit is drawn up to 1.5 m below that, so a car hits the concrete. Raise only the deck, then let
-- the extra height run out along the span and the roads that share its nodes, at the class
-- grade. Roads that share a node are the ramps, not the road underneath: they are not a second
-- carriageway to clear. Each build copies the points first, so a tile that shares the source
-- cell still starts from the same heights.
local function liftDecks(roads, pause)
  local bridges = false
  for _, road in ipairs(roads or {}) do
    if ROADS.bridge((road.tags) or {}) then bridges = true break end
  end
  if not bridges then return end
  local meta, maxLevel = {}, 0
  for index, road in ipairs(roads) do
    local tags = road.tags or {}
    local level = deckLevel(tags)
    -- The mesh keeps the first of two points and drops a later one closer than 0.1 mm.
    -- Country cells repeat an abutment (the same node twice, or a centimetre that rounded
    -- onto it). The raise landed on that later copy, the mesh threw it away, and the bridge
    -- started a full clearance above the road that shares the node. Collapse onto the point
    -- the mesh keeps, and keep the higher copy so a raise already on the repeat survives.
    local src, points, base = road.points or {}, {}, {}
    for _, p in ipairs(src) do
      local q = points[#points]
      local z = p[3] or 0
      if q and math.abs(q[1] - p[1]) + math.abs(q[2] - p[2]) <= 1e-4 then
        if z > q[3] then q[3], base[#base] = z, z end
      else
        points[#points + 1] = {p[1], p[2], z}
        base[#base + 1] = z
      end
    end
    local owned = {}
    for _, id in ipairs(road.nodes or {}) do
      if id ~= nil then owned[tostring(id)] = true end
    end
    local dist = {0}
    for i = 2, #points do
      local a, b = points[i - 1], points[i]
      dist[i] = dist[i - 1] + math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2)
    end
    meta[index] = {road = road, tags = tags, level = level, points = points, base = base,
      nodes = owned, dist = dist, width = math.max(.5, math.min(80, road.width or 7)),
      grade = deckGrade(tags)}
    road.points = points
    if level > maxLevel then maxLevel = level end
    if index % 32 == 0 then pause() end
  end
  -- A kink of one bad node (a spike off an otherwise straight deck) reads as a warp. Pull it
  -- part way back to the chord of its neighbours. A bend's sagitta at a 20 m spacing stays
  -- under the threshold, so a cloverleaf is not straightened. Ends stay: the abutment is shared.
  local function smoothPlan(m)
    local pts = m.points
    if #pts < 3 then return end
    for _ = 1, 2 do
      local shift = {}
      for i = 2, #pts - 1 do
        local a, b, c = pts[i - 1], pts[i], pts[i + 1]
        local acx, acy = c[1] - a[1], c[2] - a[2]
        local ac2 = acx * acx + acy * acy
        local t = 0
        if ac2 > EPS then
          t = ((b[1] - a[1]) * acx + (b[2] - a[2]) * acy) / ac2
          if t < 0 then t = 0 elseif t > 1 then t = 1 end
        end
        local ox, oy = b[1] - (a[1] + acx * t), b[2] - (a[2] + acy * t)
        local off = math.sqrt(ox * ox + oy * oy)
        if off > .75 then
          local pull = math.min(.5, off * .5)
          shift[i] = {b[1] - ox / off * pull, b[2] - oy / off * pull}
        end
      end
      for i, p in pairs(shift) do pts[i][1], pts[i][2] = p[1], p[2] end
    end
    local dist = {0}
    for i = 2, #pts do
      local a, b = pts[i - 1], pts[i]
      dist[i] = dist[i - 1] + math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2)
    end
    m.dist = dist
  end
  for _, m in ipairs(meta) do
    if m.level > 0 then smoothPlan(m) end
  end
  local function shares(a, b)
    for id in pairs(a.nodes) do
      if b.nodes[id] then return true end
    end
    return false
  end
  -- Spread a raised end along the road. The limit is the class grade, or the pack's own
  -- grade where the street is already steeper: a hill in the same tile is not a ramp.
  local function sweep(m)
    local pts, dist, grade, base = m.points, m.dist, m.grade, m.base
    local moved = false
    for i = 2, #pts do
      local span = dist[i] - dist[i - 1]
      if span > EPS then
        local limit = math.max(grade, math.abs(base[i] - base[i - 1]) / span)
        local cap = pts[i - 1][3] - limit * span
        if pts[i][3] < cap - 1e-4 then pts[i][3] = cap; moved = true end
      end
    end
    for i = #pts - 1, 1, -1 do
      local span = dist[i + 1] - dist[i]
      if span > EPS then
        local limit = math.max(grade, math.abs(base[i + 1] - base[i]) / span)
        local cap = pts[i + 1][3] - limit * span
        if pts[i][3] < cap - 1e-4 then pts[i][3] = cap; moved = true end
      end
    end
    return moved
  end
  local function equalize()
    local height, moved = {}, false
    for _, m in ipairs(meta) do
      local nodes = m.road.nodes or {}
      local ends = {nodes[1], nodes[2]}
      local at = {1, #m.points}
      for e = 1, 2 do
        local p = m.points[at[e]]
        if ends[e] ~= nil and p then
          local id, z = tostring(ends[e]), p[3]
          if not height[id] or z > height[id] then height[id] = z end
        end
      end
    end
    for _, m in ipairs(meta) do
      if m.level >= 0 then
        local nodes = m.road.nodes or {}
        local ends = {nodes[1], nodes[2]}
        local at = {1, #m.points}
        for e = 1, 2 do
          local z = ends[e] ~= nil and height[tostring(ends[e])] or nil
          local p = m.points[at[e]]
          if z and p and p[3] < z - 1e-4 then p[3] = z; moved = true end
        end
      end
    end
    return moved
  end
  for level = 1, maxLevel do
    for _ = 1, 2 do
      local bins = {}
      -- Nested integer keys: a packed ix*K+iy collides once a road spans K bins,
      -- and Kyiv's pack sits on negative coordinates.
      local function put(seg)
        local a, b, reach = seg.a, seg.b, seg.reach
        local x0, x1 = math.min(a[1], b[1]) - reach, math.max(a[1], b[1]) + reach
        local y0, y1 = math.min(a[2], b[2]) - reach, math.max(a[2], b[2]) + reach
        for ix = math.floor(x0 / DECK_CLEAR.bin), math.floor(x1 / DECK_CLEAR.bin) do
          local col = bins[ix]
          if not col then col = {}; bins[ix] = col end
          for iy = math.floor(y0 / DECK_CLEAR.bin), math.floor(y1 / DECK_CLEAR.bin) do
            local list = col[iy]
            if not list then list = {}; col[iy] = list end
            list[#list + 1] = seg
          end
        end
      end
      for _, m in ipairs(meta) do
        if m.level >= 0 and m.level < level and #m.points >= 2 then
          local reach = m.width / 2
          for i = 2, #m.points do
            local a, b = m.points[i - 1], m.points[i]
            if (b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2 > EPS then
              put({a = a, b = b, reach = reach, half2 = reach * reach, level = m.level, owner = m})
            end
          end
        end
      end
      for _, m in ipairs(meta) do
        if m.level == level and #m.points >= 2 then
        local half = m.width / 2 + DECK_CLEAR.overhang
        -- Deltas land after every segment is measured. Raising a shared vertex in
        -- place made the next segment add the same lack again, so a wide road
        -- under the span climbed by twice the clearance.
        local add = {}
        for i = 2, #m.points do
          local a, b = m.points[i - 1], m.points[i]
          local dx, dy = b[1] - a[1], b[2] - a[2]
          local len = math.sqrt(dx * dx + dy * dy)
          if len > EPS then
          local z0, z1 = a[3], b[3]
          local nx, ny = -dy / len, dx / len
          local steps = math.max(1, math.ceil(len / 2))
          local across = math.max(1, math.ceil(half))
          local maxLack = 0
          for s = 0, steps do
            local t = s / steps
            local x = a[1] + dx * t
            local y = a[2] + dy * t
            local z = z0 + (z1 - z0) * t
            for k = 0, across do
              local offset = -half + 2 * half * (k / across)
              local px, py = x + nx * offset, y + ny * offset
              local col = bins[math.floor(px / DECK_CLEAR.bin)]
              local list = col and col[math.floor(py / DECK_CLEAR.bin)]
              if list then
                for _, seg in ipairs(list) do
                  if seg.owner ~= m and not shares(m, seg.owner) then
                    local sx, sy = seg.b[1] - seg.a[1], seg.b[2] - seg.a[2]
                    local l2 = sx * sx + sy * sy
                    local u = 0
                    if l2 > EPS then
                      u = ((px - seg.a[1]) * sx + (py - seg.a[2]) * sy) / l2
                      if u < 0 then u = 0 elseif u > 1 then u = 1 end
                    end
                    local qx, qy = seg.a[1] + sx * u, seg.a[2] + sy * u
                    local ddx, ddy = px - qx, py - qy
                    -- The road must pass under the deck itself. Its ribbon grazing the overhang
                    -- is not a crossing: the other carriageway of a dual bridge lies a few
                    -- metres off, and its approach ran this deck up, which ran its own bridge
                    -- up in turn (a 12 m hill at the Tallinna ringtee bridges).
                    local under = math.abs((qx - x) * nx + (qy - y) * ny) <= m.width / 2
                    if under and ddx * ddx + ddy * ddy <= seg.half2 then
                      local qz = seg.a[3] + (seg.b[3] - seg.a[3]) * u
                      if qz <= z - DECK_CLEAR.below then
                        local need = qz + DECK_CLEAR.gap * (level - seg.level) + DECK_CLEAR.slack - z
                        if need > maxLack then maxLack = need end
                      end
                    end
                  end
                end
              end
            end
          end
          if maxLack > .01 then
            add[i - 1] = math.max(add[i - 1] or 0, maxLack)
            add[i] = math.max(add[i] or 0, maxLack)
          end
          end
        end
        for i, extra in pairs(add) do
          local p = m.points[i]
          p[3] = p[3] + extra
        end
        end
        pause()
      end
      -- One hop per shared node. A ramp can cross several short streets before it
      -- is back at the pack height; stop once a pass changes nothing.
      for _hop = 1, 24 do
        local moved = equalize()
        for _, m in ipairs(meta) do
          if m.level >= 0 and #m.points >= 2 and sweep(m) then moved = true end
        end
        if not moved then break end
      end
    end
  end
  -- Two carriageways of one bridge are separate OSM ways. Drawn apart, a median is two
  -- soffits and the two profiles drift by a few centimetres, which reads as a ridge.
  -- Same deck level, nearly parallel, a stable gap of at most 12 m: one group. A ramp
  -- whose separation changes, or a deck stacked a few metres above, stays its own span.
  local function project(m, x, y)
    local best, bestD
    local pts, dist = m.points, m.dist
    for i = 2, #pts do
      local a, b = pts[i - 1], pts[i]
      local dx, dy = b[1] - a[1], b[2] - a[2]
      local l2 = dx * dx + dy * dy
      if l2 > EPS then
        local t = ((x - a[1]) * dx + (y - a[2]) * dy) / l2
        if t >= 0 and t <= 1 then
          local qx, qy = a[1] + dx * t, a[2] + dy * t
          local ddx, ddy = x - qx, y - qy
          local d2 = ddx * ddx + ddy * ddy
          if not bestD or d2 < bestD then
            local l = math.sqrt(l2)
            bestD = d2
            best = {qx, qy, a[3] + (b[3] - a[3]) * t, math.sqrt(d2), dist[i - 1] + l * t}
          end
        end
      end
    end
    return best
  end
  local function pointAt(m, s)
    local pts, dist = m.points, m.dist
    if s <= 0 then return pts[1][1], pts[1][2], pts[1][3] end
    for i = 2, #pts do
      if s <= dist[i] or i == #pts then
        local a, b = pts[i - 1], pts[i]
        local span = math.max(EPS, dist[i] - dist[i - 1])
        local t = math.max(0, math.min(1, (s - dist[i - 1]) / span))
        return a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t, a[3] + (b[3] - a[3]) * t
      end
    end
  end
  local function chord(m)
    local a, b = m.points[1], m.points[#m.points]
    local dx, dy = b[1] - a[1], b[2] - a[2]
    local l = math.sqrt(dx * dx + dy * dy)
    if l < 1 then return nil end
    return dx / l, dy / l
  end
  local function parallel(a, b)
    if a.level <= 0 or a.level ~= b.level or #a.points < 2 or #b.points < 2 then return false end
    local ax, ay = chord(a)
    local bx, by = chord(b)
    if not ax or not bx or math.abs(ax * bx + ay * by) < .9 then return false end
    local short = a.dist[#a.dist] <= b.dist[#b.dist] and a or b
    local long = short == a and b or a
    local length = short.dist[#short.dist]
    if length < 30 then return false end
    local count = math.max(2, math.floor(length / 25))
    local n, s0, s1, near, far = 0, length, 0, math.huge, 0
    for i = 0, count do
      local s = length * i / count
      local x, y, z = pointAt(short, s)
      local hit = project(long, x, y)
      if hit and hit[4] - short.width / 2 - long.width / 2 <= 12 and math.abs(z - hit[3]) < 1.5 then
        n = n + 1
        if s < s0 then s0 = s end
        if s > s1 then s1 = s end
        if hit[4] < near then near = hit[4] end
        if hit[4] > far then far = hit[4] end
      end
    end
    return n >= 3 and s1 - s0 >= 30 and s1 - s0 >= length * .5 and far - near <= 4
  end
  local parent = {}
  for i = 1, #meta do parent[i] = i end
  local function find(i)
    while parent[i] ~= i do parent[i] = parent[parent[i]]; i = parent[i] end
    return i
  end
  local function unite(i, j)
    i, j = find(i), find(j)
    if i ~= j then parent[j] = i end
  end
  local bridges = {}
  for i, m in ipairs(meta) do
    if m.level > 0 and #m.points >= 2 and m.dist[#m.dist] >= 30 then bridges[#bridges + 1] = i end
  end
  for a = 1, #bridges do
    for b = a + 1, #bridges do
      if parallel(meta[bridges[a]], meta[bridges[b]]) then unite(bridges[a], bridges[b]) end
    end
    if a % 8 == 0 then pause() end
  end
  local membersOf, group = {}, 0
  for _, i in ipairs(bridges) do
    local root = find(i)
    local list = membersOf[root]
    if not list then list = {}; membersOf[root] = list end
    list[#list + 1] = i
  end
  for _, list in pairs(membersOf) do
    if #list >= 2 then
      group = group + 1
      local host, hostLen = list[1], -1
      for _, i in ipairs(list) do
        local len = meta[i].dist[#meta[i].dist]
        if len > hostLen then host, hostLen = i, len end
      end
      for _, i in ipairs(list) do meta[i].road.deckGroup = group end
      meta[host].road.deckHost = true
      for _pass = 1, 3 do
        for _, i in ipairs(list) do
          local m = meta[i]
          local want = {}
          for k, p in ipairs(m.points) do want[k] = p[3] end
          for _, j in ipairs(list) do
            if j ~= i then
              local other = meta[j]
              for k, p in ipairs(m.points) do
                local hit = project(other, p[1], p[2])
                if hit and hit[4] - m.width / 2 - other.width / 2 <= 12 and hit[3] > want[k]
                    and math.abs(p[3] - hit[3]) < 1.5 then
                  want[k] = hit[3]
                end
              end
            end
          end
          for k, z in ipairs(want) do m.points[k][3] = z end
        end
      end
      -- The united slab runs along the host and takes a mate only where it runs beside it: a
      -- deck sticking out past the host's end would have neither slab nor (its own are
      -- suppressed in a group) asphalt and soffit, a hole with the lane marks floating over it.
      -- Such a group stays separate decks, each whole.
      local loose = false
      for _, i in ipairs(list) do
        if i ~= host then
          local m, out = meta[i], 0
          for s = 0, m.dist[#m.dist], 4 do
            local x, y = pointAt(m, s)
            if not project(meta[host], x, y) then out = out + 4 end
          end
          if out > 8 then loose = true end
        end
      end
      if loose then
        for _, i in ipairs(list) do meta[i].road.deckGroup, meta[i].road.deckHost = nil, nil end
      end
    end
    pause()
  end
  for _hop = 1, 8 do
    local moved = equalize()
    for _, m in ipairs(meta) do
      if m.level >= 0 and #m.points >= 2 and sweep(m) then moved = true end
    end
    if not moved then break end
  end
  -- The clearance ramp is a straight grade up to a flat deck: a kink at each end of it.
  -- A smoothstep whose steepest slope is the class grade needs about half as much run
  -- again, taken from approach that is still on the ground. Where that spare length is
  -- missing the straight ramp stays. Nothing is lowered, so a clearance hold stays put.
  local function connected(m, node)
    if node == nil then return nil end
    local id, found = tostring(node), nil
    for _, other in ipairs(meta) do
      if other ~= m and other.level >= 0 and #other.points >= 2 then
        local nodes = other.road.nodes or {}
        -- nodes names the two ends only; the second end is the last point, not point 2
        local at
        if nodes[1] ~= nil and tostring(nodes[1]) == id then at = 1
        elseif nodes[2] ~= nil and tostring(nodes[2]) == id then at = #other.points end
        if at then
          if found then return nil end
          found = {other, at}
        end
      end
    end
    return found and found[1], found and found[2]
  end
  local function easeSide(m, iH, dir)
    local zH = m.points[iH][3]
    local chain, road, idx, step = {}, m, iH + dir, dir
    -- The flat deck can run to the abutment. The ramp then lives on the next way, and the
    -- chain has to step across the shared node before the first sample.
    if idx < 1 or idx > #m.points then
      local nodes = m.road.nodes or {}
      local node = dir < 0 and nodes[1] or nodes[2]
      local nxt, nEnd = connected(m, node)
      if not nxt or #nxt.points < 2 then return end
      chain[1] = {nxt, nEnd}
      step = nEnd == 1 and 1 or -1
      road, idx = nxt, nEnd + step
    end
    local low, dropped, flat, guard = zH, false, 0, 0
    while road and idx >= 1 and idx <= #road.points and guard < 80 do
      local z = road.points[idx][3]
      if z < low - .05 then low, dropped = z, true end
      if dropped and z > low + .3 then break end
      guard = guard + 1
      chain[#chain + 1] = {road, idx}
      local atEnd = (step > 0 and idx == #road.points) or (step < 0 and idx == 1)
      if not atEnd then
        idx = idx + step
      else
        local nodes = road.road.nodes or {}
        local node = idx == 1 and nodes[1] or nodes[2]
        local atBase = z - (road.base[idx] or z) <= .05
        local nxt, nEnd = connected(road, node)
        if not nxt or #nxt.points < 2 then break end
        local j = nEnd == 1 and 2 or nEnd - 1
        local span = math.abs(nxt.dist[j] - nxt.dist[nEnd])
        local bg = span > EPS and math.abs(nxt.base[j] - nxt.base[nEnd]) / span or 0
        if atBase and bg > .02 then break end
        chain[#chain + 1] = {nxt, nEnd}
        step = nEnd == 1 and 1 or -1
        road, idx = nxt, nEnd + step
        if atBase then flat = flat + 1 end
        if flat > 12 then break end
      end
    end
    if #chain == 0 then return end
    local cum, zAt, run, pm, pi = {}, {}, 0, m, iH
    for k, item in ipairs(chain) do
      local meta, i = item[1], item[2]
      if meta == pm then run = run + math.abs(meta.dist[i] - meta.dist[pi]) end
      cum[k], zAt[k], pm, pi = run, meta.points[i][3], meta, i
    end
    local k0 = 1
    while k0 <= #chain and cum[k0] < 1 do k0 = k0 + 1 end
    if k0 > #chain or math.abs(zH - zAt[k0]) / cum[k0] < .02 then return end
    local foot
    for k, item in ipairs(chain) do
      local meta, i = item[1], item[2]
      if meta.points[i][3] - meta.base[i] <= .05 then foot = k; break end
    end
    if not foot or cum[foot] < 8 then return end
    local slack = foot
    for k = foot, #chain do
      local meta, i = chain[k][1], chain[k][2]
      if meta.points[i][3] - meta.base[i] > .05 then break end
      slack = k
    end
    local zFoot = zAt[foot]
    local rise = zH - zFoot
    if rise < .4 then return end
    local limit = m.grade
    if not limit or limit < .02 then limit = .08 end
    local need = 1.5 * rise / limit
    if cum[slack] + .5 < need then return end
    for k, item in ipairs(chain) do
      local d = cum[k]
      if d > need then break end
      local t = 1 - d / math.max(EPS, need)
      if t < 0 then t = 0 end
      local s = t * t * (3 - 2 * t)
      local zNew = zFoot + rise * s
      local p = item[1].points[item[2]]
      if zNew > p[3] + 1e-4 then p[3] = zNew end
    end
  end
  for _, m in ipairs(meta) do
    if m.level > 0 and #m.points >= 3 then
      local zMax, iMax = m.points[1][3], 1
      for i = 2, #m.points do
        if m.points[i][3] > zMax then zMax, iMax = m.points[i][3], i end
      end
      local left, right = iMax, iMax
      while left > 1 and m.points[left - 1][3] >= zMax - .15 do left = left - 1 end
      while right < #m.points and m.points[right + 1][3] >= zMax - .15 do right = right + 1 end
      easeSide(m, left, -1)
      easeSide(m, right, 1)
    end
  end
  for _, m in ipairs(meta) do
    for i, p in ipairs(m.points) do
      local cap = m.base[i] + DECK_CLEAR.cap
      if p[3] > cap then p[3] = cap end
    end
  end
end

local function build(cells, i, j, options)
  options = options or {}
  local pause = options.pause or options.yield or function() end
  local size = options.tileSize or 500
  -- far: the 3 km ring. horizon: DEM-only past it. Both shape the ground like near (so the
  -- shared edge matches) but emit no road mesh, nav or collision. Decor is the optional
  -- far buildings and trees; a horizon tile never has it.
  local distant = options.far or options.horizon
  local visualRoads = not distant
  local decor = not options.horizon and (not options.far or options.farDecor ~= false)
  local layerName = options.horizon and 'horizon' or (options.far and 'far' or 'scene')
  local rect, key = {i * size, j * size, (i + 1) * size, (j + 1) * size}, tostring(i) .. '_' .. tostring(j)
  local target = options.center or {(i + .5) * size, (j + .5) * size}
  local lists, terrain
  local single = cells and #cells == 1 and cells[1]
  if single and prepared[single] then
    lists, terrain = prepared[single][1], prepared[single][2]
  else
    lists, terrain = collect(cells, pause)
    if single then prepared[single] = {lists, terrain} end
  end
  -- Old country packs store bridge profiles with about a metre under the soffit. Raise those
  -- decks, and the roads that run up to them, before any mesh or junction reads the points.
  liftDecks(lists.roads, pause)
  local roads, scene = collector(rect, key, 'road', pause), collector(rect, key, layerName, pause, distant and MIXED_TRIS or nil)
  local roadDecor, sceneDecor = collector(rect, key .. '_marks', 'road', pause), collector(rect, key .. '_cars', 'scene', pause)
  -- A far tile (the ring past the near radius, ~1 km) draws each road's surface into its scene layer,
  -- decoration without collision: it kept the guard rails and fences, and from a free camera the
  -- Tallinna ringtee was grass between two lines of rail. The horizon draws no road.
  local farRoads = options.far and not options.horizon
  local function drawn(strip)
    return visualRoads or (farRoads and not ROADS.tunnel(strip.tags) and ROADS.rankOf(strip.tags) >= ROADS.far.minRank)
  end
  -- a far road's surfaces wait for the far ground to exist: they are lifted over its triangles where
  -- the coarse terrain would hide them (before the collectors finish)
  local farQuads, farTris = {}, {}
  local function emitSurface(material, poly)
    if farRoads then farQuads[#farQuads + 1] = {material, poly} else roads.polygon(material, poly, 'flat') end
  end
  -- mark(name): the stage that just ended (the road quality bench times them)
  local mark = options.mark or function() end
  local look = type(options.look) == 'table' and options.look or NONE
  local postsoviet = look.block == 'postsoviet' or BLD.postsoviet[tostring(options.country or '')] or false
  local function lookOf(slot)
    local value = look[slot]
    return type(value) == 'string' and value or nil
  end
  local asphalt = lookOf('asphalt')
  local minorRoad, majorRoad = 'road', 'road_major'
  if asphalt == 'worn' then minorRoad, majorRoad = 'road_worn', 'road'
  elseif asphalt == 'fresh' then minorRoad, majorRoad = 'road_major', 'road_major' end
  -- a carriageway's material: graded surfaces by grade, asphalt by class (links with their road);
  -- a junction takes the material of its most important road
  local function roadMaterial(tags)
    local grade = roadGrade(tags)
    if grade ~= 0 then return ROAD_GRADE_MAT[grade], grade end
    return ROADS.rankOf(tags) >= 4.5 and majorRoad or minorRoad, grade
  end
  local vergeKind = 'ground'
  local vergeChoice = lookOf('verge')
  if vergeChoice == 'dirt' then vergeKind = 'bare_ground'
  elseif vergeChoice == 'dry' then vergeKind = 'heath'
  elseif vergeChoice == 'gravel' then vergeKind = 'scree' end
  local markChoice = lookOf('markings')
  local markKind = 'mark'
  if markChoice == 'yellow' then markKind = 'mark_yellow'
  elseif markChoice == 'none' then markKind = nil end
  local staticChoice = lookOf('statics')
  local wantLamps = staticChoice ~= 'sparse' and staticChoice ~= 'none'
  local wantStops = staticChoice ~= 'none'
  local tune = {}
  for name, value in pairs(TUNE) do tune[name] = value end
  -- A finer source grid (a 10 m LiDAR DEM; Terrarium packs carry 25 m) sets a finer ground
  -- lattice (options.terrainStep still wins), and an accurate DEM needs less pull to its
  -- roads: the real ditches and embankments stay.
  local gridStep = math.huge
  for _, grid in ipairs(terrain) do
    local r = grid.rect
    if r and (grid.nx or 0) > 1 then gridStep = math.min(gridStep, (r[3] - r[1]) / (grid.nx - 1)) end
  end
  if gridStep < tune.terrainStep - EPS then
    tune.terrainStep = gridStep
    if gridStep <= FINE_DEM.grid then tune.pullFull, tune.pullZero = FINE_DEM.pullFull, FINE_DEM.pullZero end
  end
  if options.terrainStep then tune.terrainStep = options.terrainStep end
  for name, value in pairs(options.tune or NONE) do tune[name] = value end
  local lift, step = tune.roadLift, tune.terrainStep
  -- A road shapes the ground up to pullZero from its edge, and the ground lattice reaches one
  -- step past the tile (its border nodes are lowered for roads in the neighbour's cells too).
  local reach = tune.pullZero + step + 5
  local segments, segmentBins, nav, bestSpawn, bestDistance = {}, {}, {segments = {}}, nil, math.huge
  for _, road in ipairs(lists.roads) do
    local tags, points, width = road.tags or {}, road.points or {}, math.max(.5, math.min(80, road.width or 7))
    for index = 1, #points - 1 do
      local a, b = points[index], points[index + 1]
      local dx, dy = b[1] - a[1], b[2] - a[2]
      local length = math.sqrt(dx * dx + dy * dy)
      if length > EPS then
        local bounds = {math.min(a[1], b[1]), math.min(a[2], b[2]), math.max(a[1], b[1]), math.max(a[2], b[2])}
        if boundsTouch(rect, bounds, width / 2 + reach) then
          -- a track lies on the ground (ROADS.trackRuns): it does not shape it
          local segment = {a = a, b = b, dx = dx, dy = dy, len2 = length * length, width = width, road = road,
            tags = tags, surface = not road.track and not ROADS.bridge(tags) and not ROADS.tunnel(tags)}
          segments[#segments + 1] = segment
          local margin = width / 2 + tune.pullZero
          for by = math.floor((bounds[2] - margin) / 50), math.floor((bounds[4] + margin) / 50) do
            for bx = math.floor((bounds[1] - margin) / 50), math.floor((bounds[3] + margin) / 50) do
              local binKey = (bx + 32768) * 65536 + by + 32768
              local bin = segmentBins[binKey] or {}
              segmentBins[binKey], bin[#bin + 1] = bin, segment
            end
          end
        end
      end
      if index % 32 == 0 then pause() end
    end
    local navigation = visualRoads and navSegment(road)
    if navigation then nav.segments[#nav.segments + 1] = navigation end
    pause()
  end

  -- One world-space sample. No grids: 0, so a near tile without a DEM stays the flat
  -- lattice the roads already sit on. Grids that miss the point: nil, so a distant mesh
  -- omits the quad instead of dropping a cliff to z = 0. A point on a shared cell edge
  -- belongs to every grid that contains it; the lower rect origin wins, so the order the
  -- cells were loaded in cannot move the surface.
  -- Grids are cell rectangles that only share edges. Then a point well inside the grid of
  -- the previous sample is in that grid alone, and the scan below would pick it anyway.
  local disjoint, lastGrid = true, nil
  for a = 1, #terrain do
    for b = a + 1, #terrain do
      local p, q = terrain[a].rect, terrain[b].rect
      if p and q and p[1] < q[3] - EPS and q[1] < p[3] - EPS and p[2] < q[4] - EPS and q[2] < p[4] - EPS then disjoint = false end
    end
  end
  local function demAt(x, y)
    if #terrain == 0 then return 0 end
    local best, bestX, bestY
    local last = disjoint and lastGrid
    if last then
      local box = last.rect
      if x > box[1] + EPS and x < box[3] - EPS and y > box[2] + EPS and y < box[4] - EPS then best = last end
    end
    for _, grid in ipairs(best and NONE or terrain) do
      local box = grid.rect
      if box and x >= box[1] - EPS and x <= box[3] + EPS and y >= box[2] - EPS and y <= box[4] + EPS
          and grid.nx >= 2 and grid.ny >= 2 and grid.heights then
        local ox, oy = box[1], box[2]
        if not best or ox < bestX - EPS or (math.abs(ox - bestX) <= EPS and oy < bestY) then
          best, bestX, bestY = grid, ox, oy
        end
      end
    end
    if not best then return nil end
    lastGrid = best
    local grid, box = best, best.rect
    local gx = math.max(0, math.min(grid.nx - 1, (x - box[1]) / (box[3] - box[1]) * (grid.nx - 1)))
    local gy = math.max(0, math.min(grid.ny - 1, (y - box[2]) / (box[4] - box[2]) * (grid.ny - 1)))
    local ix, iy = math.min(grid.nx - 2, math.floor(gx)), math.min(grid.ny - 2, math.floor(gy))
    local tx, ty = gx - ix, gy - iy
    local heights, row = grid.heights, iy * grid.nx + ix + 1
    local z00, z10 = heights[row] or 0, heights[row + 1] or 0
    local z01, z11 = heights[row + grid.nx] or 0, heights[row + grid.nx + 1] or 0
    return (z00 * (1 - tx) + z10 * tx) * (1 - ty) + (z01 * (1 - tx) + z11 * tx) * ty
  end
  local function rawHeight(x, y)
    local z = demAt(x, y)
    if z == nil then return 0 end
    return z
  end
  -- The DEM pulled to the roads round a point (fast.ground_corners): fully at a road's profile
  -- within pullFull of its edge, the DEM alone from pullZero. Nearer roads weigh more in the
  -- height, the strongest pull wins. Bridges and tunnels do not pull.
  local heightOperations = 0
  local span = math.max(1, tune.pullZero - tune.pullFull)
  local function pulled(x, y)
    local base = demAt(x, y)
    if base == nil then return nil end
    local nearby = segmentBins[(floor(x / 50) + 32768) * 65536 + floor(y / 50) + 32768] or NONE
    local sa, sz, pull = 0, 0, 0
    for _, segment in ipairs(nearby) do
      if segment.surface then
        local a = segment.a
        local t = math.max(0, math.min(1, ((x - a[1]) * segment.dx + (y - a[2]) * segment.dy) / segment.len2))
        local px, py = a[1] + t * segment.dx, a[2] + t * segment.dy
        local d = math.max(0, math.sqrt((x - px) ^ 2 + (y - py) ^ 2) - segment.width / 2)
        if d < tune.pullZero then
          local s = math.max(0, math.min(1, (tune.pullZero - d) / span))
          local w = s * s * (3 - 2 * s)
          local weight = w / math.max(d, 1)
          sa, sz = sa + weight, sz + weight * ((a[3] or 0) + t * ((segment.b[3] or 0) - (a[3] or 0)))
          if w > pull then pull = w end
        end
      end
      heightOperations = heightOperations + 1
      if heightOperations % 512 == 0 then pause() end
    end
    if sa > 0 then return base + (sz / sa - base) * pull end
    return base
  end

  mark('segments')
  -- The ground lattice: global nodes every step metres, one ring past the tile. Its height is
  -- the pulled DEM minus groundDrop, then lowered wherever the bilinear surface would reach a
  -- road, sidewalk or junction from below (the Python generator cut holes into the ground there;
  -- lowering the four corners of a cell by the worst excess in it is cheap, and since a node's
  -- drop depends only on the cells round it, neighbouring tiles agree on their shared nodes).
  -- One step past the tile is not enough for a border normal: the sample a step
  -- outside has to be pressed from both of its cells, or the neighbour tile's slope
  -- disagrees. The extra ring is only for those samples; drawn quads stay in the tile.
  local n0x, n0y = floor(rect[1] / step + .5) - 1, floor(rect[2] / step + .5) - 1
  local count = math.max(1, floor(size / step + .5))
  local nodes, lower = {}, {}
  local function nodeKey(gx, gy) return (gx - n0x) * 4096 + (gy - n0y) end
  for gy = n0y - 1, n0y + count + 3 do
    for gx = n0x - 1, n0x + count + 3 do
      local z = pulled(gx * step, gy * step)
      if z == nil then nodes[nodeKey(gx, gy)] = nil else nodes[nodeKey(gx, gy)] = z - tune.groundDrop end
    end
    pause()
  end
  local function lattice(x, y)
    local fx, fy = x / step, y / step
    local gx, gy = floor(fx), floor(fy)
    if gx < n0x - 1 or gy < n0y - 1 or gx >= n0x + count + 3 or gy >= n0y + count + 3 then return nil end
    local u, v = fx - gx, fy - gy
    local k = nodeKey(gx, gy)
    return k, u, v
  end
  -- The drawn ground at (x, y) must stay at or under target. The ground triangle's corners are
  -- lowered in proportion to how far each stands above target, just enough at this point: the
  -- high corner that props the surface up takes the drop, not the low one on the road. A node
  -- keeps the largest drop asked of it, so the order of the samples does not matter.
  local function press(x, y, target)
    local k, u, v = lattice(x, y)
    if not k then return end
    local ka, kb, kc, wa, wb, wc
    if u >= v then ka, kb, kc, wa, wb, wc = k, k + 4096, k + 4097, 1 - u, u - v, v
    else ka, kb, kc, wa, wb, wc = k, k + 4097, k + 1, 1 - v, u, v - u end
    local za, zb, zc = nodes[ka], nodes[kb], nodes[kc]
    if za == nil or zb == nil or zc == nil then return end
    local excess = wa * za + wb * zb + wc * zc - target
    if excess <= 0 then return end
    local ha, hb, hc = math.max(0, za - target), math.max(0, zb - target), math.max(0, zc - target)
    local f = excess / (wa * ha + wb * hb + wc * hc)
    if tune.pressEven > 0 then ha, hb, hc, f = 1, 1, 1, excess end
    for _, pair in ipairs({{ka, ha}, {kb, hb}, {kc, hc}}) do
      local drop = pair[2] * f
      if drop > (lower[pair[1]] or 0) then lower[pair[1]] = drop end
    end
  end
  -- The ground as drawn: each lattice cell is two triangles split along its (x0, y0)-(x1, y1)
  -- diagonal (the collector fans a quad from its first corner).
  local function ground(x, y)
    local k, u, v = lattice(x, y)
    if k then
      local a, b, c, d = nodes[k], nodes[k + 4096], nodes[k + 1], nodes[k + 4097]
      -- A corner outside the DEM used to fall back to the raw grid and drop the road pull,
      -- so the same verge sampled from the other tile landed tens of metres higher.
      if a ~= nil and b ~= nil and c ~= nil and d ~= nil then
        local z00, z10 = a - (lower[k] or 0), b - (lower[k + 4096] or 0)
        local z01, z11 = c - (lower[k + 1] or 0), d - (lower[k + 4097] or 0)
        if u >= v then return z00 + (z10 - z00) * u + (z11 - z10) * v end
        return z00 + (z11 - z01) * u + (z01 - z00) * v
      end
    end
    local z = pulled(x, y)
    return z and z - tune.groundDrop or 0
  end
  -- Height of the drawn surface, or nil outside every DEM grid. No grids at all stays the
  -- numeric ground (flat near tiles). A sample just outside a grid is nil so the normal
  -- there is one-sided instead of a slope down to the old z = 0 fallback.
  -- demAt(x, y) ~= nil without the interpolation: some grid holds the point.
  local function demCovered(x, y)
    local last = disjoint and lastGrid
    if last then
      local box = last.rect
      if x > box[1] + EPS and x < box[3] - EPS and y > box[2] + EPS and y < box[4] - EPS then return true end
    end
    return demAt(x, y) ~= nil
  end
  local function heightAt(x, y)
    if #terrain == 0 then return ground(x, y) end
    if not demCovered(x, y) then return nil end
    return ground(x, y)
  end
  local normalCache -- enabled only after road pressing has finished
  local function groundNormal(x, y)
    -- keyed by the point to a micrometre, as the old '%.6f' string key was, without the string
    local row, key = nil, nil
    if normalCache then
      local kx = floor(x * 1e6 + .5)
      row = normalCache[kx]
      if not row then row = {}; normalCache[kx] = row end
      key = floor(y * 1e6 + .5)
    end
    local cached = row and row[key]
    if cached then return cached[1], cached[2], cached[3] end
    local function slope(dx, dy)
      local zp, zm, z0 = heightAt(x + dx, y + dy), heightAt(x - dx, y - dy), heightAt(x, y)
      if zp and zm then return (zp - zm) / (2 * step) end
      if zp and z0 then return (zp - z0) / step end
      if zm and z0 then return (z0 - zm) / step end
      return 0
    end
    local nx, ny, nz = -slope(step, 0), -slope(0, step), 1
    local len = math.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / len, ny / len, nz / len
    if row then row[key] = {nx, ny, nz} end
    return nx, ny, nz
  end
  -- Spatially indexed mapped cover, shared by terrain and vegetation at all LODs.
  -- Explicit OSM wins over WorldCover. Tie-breaking never depends on load order.
  local coverBins = {}
  for _, area in ipairs(lists.areas) do
    if CLAIM[area.kind] or area.kind == 'residential' then
      local b = ringBounds(area.rings)
      local rank = (CLAIM[area.kind] or 50) + (((area.tags or NONE).source or ''):find('worldcover', 1, true) and 100 or 0)
      local idString = tostring(area.id)
      for gx = floor(math.max(rect[1], b[1]) / 100), floor(math.min(rect[3], b[3]) / 100) do
        for gy = floor(math.max(rect[2], b[2]) / 100), floor(math.min(rect[4], b[4]) / 100) do
          local k = (gx + 32768) * 65536 + gy + 32768
          local bin = coverBins[k] or {}; coverBins[k] = bin
          bin[#bin + 1] = {area = area, rank = rank, id = idString}
        end
      end
      pause()
    end
  end
  local function coverAt(x, y)
    local best, rank, bestId
    for _, entry in ipairs(coverBins[(floor(x / 100) + 32768) * 65536 + floor(y / 100) + 32768] or NONE) do
      if (not rank or entry.rank < rank or (entry.rank == rank and entry.id < bestId))
          and inside(entry.area.rings, x, y) then best, rank, bestId = entry.area, entry.rank, entry.id end
    end
    return best and best.kind or 'ground', best
  end
  -- The climate (biome.lua), one place per 100 m bin, nil without the planet's climate grid or
  -- the pack's geographic transform: the generator then does what it did before biomes.
  -- One table, as build() is near LuaJIT's limits on locals and upvalues.
  local bio = {bins = {}, on = VEG.biome ~= nil and type(options.geo) == 'table' and VEG.biome.available(),
    sea = options.seaLevel or 20, config = type(options.nature) == 'table' and options.nature or NONE}
  function bio.at(x, y)
    if not bio.on then return nil end
    local bx, by = floor(x / 100), floor(y / 100)
    local k = (bx + 32768) * 65536 + by + 32768
    local p = bio.bins[k]
    if not p then
      p = VEG.biome.at(options.geo, (bx + .5) * 100, (by + .5) * 100)
      bio.bins[k] = p
    end
    return p
  end
  function bio.treeline(p) return tonumber(bio.config.treeLine) or p.treeline end
  -- Smooth 0..1 noise with `size` m features (the decor's grove() is the same).
  function bio.noise(x, y, size, seed)
    local fx, fy = x / size, y / size
    local gx, gy = floor(fx), floor(fy)
    local tx, ty = fx - gx, fy - gy
    tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
    local v00, v10 = ihash(seed, gx, gy) % 1000 / 1000, ihash(seed, gx + 1, gy) % 1000 / 1000
    local v01, v11 = ihash(seed, gx, gy + 1) % 1000 / 1000, ihash(seed, gx + 1, gy + 1) % 1000 / 1000
    local a, b = v00 + (v10 - v00) * tx, v01 + (v11 - v01) * tx
    return a + (b - a) * ty
  end
  -- Share of snow at a point: from 300 m under the snow line to 500 m over it, a slope facing
  -- the pole holding it ~250 m lower and one facing the sun ~250 m higher. Nothing steeper than 60°.
  function bio.snow(p, e, nx, ny, nz)
    -- not steeper than 45 degrees: snow on a cliff face showed every jagged triangle (Whitney)
    if nz < .7 then return 0 end
    local flat = math.sqrt(math.max(0, 1 - nz * nz))
    local pole = flat > .02 and (p.south and -ny or ny) / flat * math.min(1, flat * 3) or 0
    local t = (e + 250 * pole - (p.snowline - 300)) / 800
    if t <= 0 then return 0 end
    t = math.min(1, t)
    return t * t * (3 - 2 * t)
  end
  -- The open ground of a place: grass where it was (temperate, boreal, tropics), dry ground in
  -- deserts and steppes, golden grass under the Mediterranean and savanna sun, moss in the
  -- tundra; above the tree line alpine turf, scree and rock as it climbs.
  function bio.ground(p, x, y, e, nz)
    local treeline = bio.treeline(p)
    -- patches of 150-200 m: at 45-60 m every 25 m ground triangle flipped between turf, scree
    -- and rock, a camouflage of jagged triangles from a summit (Mount Whitney, in game)
    local alpine = e - treeline - 120 + (bio.noise(x, y, 180, 51) - .5) * 160
    if alpine > 0 and p.group ~= 'ice' then
      if nz < .62 then return 'bare_rock' end
      local high = alpine / math.max(300, p.snowline - treeline)
      if nz < .8 or bio.noise(x, y, 160, 53) < high * 1.1 - .15 then return 'scree' end
      if p.arid then return 'steppe' end
      return p.group == 'tundra' and 'tundra' or 'alpine'
    end
    local group = p.group
    if group == 'desert' then
      if nz < .7 then return 'bare_rock' end
      if nz < .88 then return 'scree' end
      return 'desert'
    elseif group == 'steppe' then
      if nz < .64 then return 'bare_rock' end
      if nz < .8 then return 'scree' end
      return bio.noise(x, y, 140, 55) > .72 and 'desert' or 'steppe'
    elseif group == 'mediterranean' or group == 'savanna' then
      if nz < .62 then return 'bare_rock' end
      return bio.noise(x, y, 120, 57) > (group == 'savanna' and .6 or .7) and 'ground' or 'dry_grass'
    elseif group == 'tundra' then
      if nz < .64 then return 'bare_rock' end
      return bio.noise(x, y, 70, 59) > .76 and 'scree' or 'tundra'
    elseif group == 'ice' then
      return nz < .55 and 'bare_rock' or 'snow'
    end
    -- the vista past 5 km has no land cover (elevation alone): wooded hills, open lowlands
    if options.vista and (nz < .93 or bio.noise(x, y, 1400, 65) > .55) then return 'forest' end
    return 'ground'
  end
  -- The slope a biome reads: over 80 m, not one 25 m triangle, so neighbours agree on rock,
  -- scree or turf (heightAt: the drawn ground; nil off the DEM falls back to the triangle's)
  function bio.normal(x, y)
    local d = 40
    local e, w, n, s = heightAt(x + d, y), heightAt(x - d, y), heightAt(x, y + d), heightAt(x, y - d)
    if not (e and w and n and s) then return groundNormal(x, y) end
    local gx, gy = (e - w) / (2 * d), (n - s) / (2 * d)
    local len = math.sqrt(gx * gx + gy * gy + 1)
    return -gx / len, -gy / len, 1 / len
  end
  local NATURAL_GROUND = {ground = true, forest = true, meadow = true, scrub = true, heath = true, bare_ground = true,
    bare_rock = true, scree = true, beach = true, park = true, farmland = false}
  local function surfaceKind(x, y, kind)
    kind = kind or coverAt(x, y)
    if kind == 'residential' then kind = 'ground' end
    local p = bio.on and NATURAL_GROUND[kind] and bio.at(x, y)
    if p then
      local e = rawHeight(x, y) - bio.sea
      local nx, ny, nz = bio.normal(x, y)
      local snow = bio.snow(p, e, nx, ny, nz)
      if snow > 0 then
        local n = bio.noise(x, y, 140, 61) * .75 + bio.noise(x, y, 35, 63) * .25
        if n < snow then return (snow < .9 and n > snow - .1) and 'snow_edge' or 'snow' end
      end
      if kind == 'ground' then return bio.ground(p, x, y, e, nz) end
      local arid, group = p.arid, p.group
      -- mapped land of a dry climate: a National Forest drawn over Nevada's sagebrush, dunes
      if kind == 'beach' and group == 'desert' then return 'dune' end
      if (kind == 'forest' or kind == 'meadow' or kind == 'heath' or kind == 'scrub') and (arid or group == 'mediterranean' or group == 'savanna') then
        local open = bio.ground(p, x, y, e, nz)
        if open ~= 'ground' then return open end
      end
      if (kind == 'meadow' or kind == 'heath') and e > bio.treeline(p) + 150 then return bio.ground(p, x, y, e, nz) end
      -- a park of a dry town is a lawn where it is flat; a park drawn over a desert mountain is
      -- the mountain (Las Vegas' Lone Mountain stood bright green)
      if kind == 'park' and (arid or group == 'mediterranean') and nz < .96 then return bio.ground(p, x, y, e, nz) end
    end
    if kind == 'forest' or kind == 'meadow' or kind == 'scrub' or kind == 'heath' or kind == 'bare_ground' then
      local _, _, nz = groundNormal(x, y)
      if nz < .64 then return 'bare_rock' end
      if kind == 'bare_ground' and nz < .85 then return 'scree' end
    end
    return kind
  end
  local function backgroundKind(x, y)
    local kind, area = coverAt(x, y)
    -- Satellite classes are already a coarse raster. Sample the base lattice
    -- instead of triangulating every staircase/OSM cut-out a second time.
    if area and ((area.tags or NONE).source or ''):find('worldcover', 1, true) then return kind end
    return 'ground'
  end
  mark('lattice')
  -- Roads as continuous strips: a knot's normal is the mean of its two segments' directions, so
  -- consecutive quads share their edge vertices (no bevels, no gaps on bends), on every tile.
  local strips, asphalt, asphaltBins = {}, {}, {}
  -- twice the signed area (counter-clockwise > 0)
  local function area2(poly)
    local s = 0
    for k = 1, #poly do local p, q = poly[k], poly[k % #poly + 1]; s = s + p[1] * q[2] - q[1] * p[2] end
    return s
  end
  local function addAsphalt(poly, road, index)
    local box = ringBounds({poly})
    local entry = {poly = poly, bounds = box, road = road, index = index, ccw = area2(poly) > 0}
    asphalt[#asphalt + 1] = entry
    for by = math.floor(box[2] / ABIN), math.floor(box[4] / ABIN) do
      for bx = math.floor(box[1] / ABIN), math.floor(box[3] / ABIN) do
        local binKey = (bx + 32768) * 65536 + by + 32768
        local bin = asphaltBins[binKey] or {}
        asphaltBins[binKey], bin[#bin + 1] = bin, entry
      end
    end
  end
  local stripReach = 3 + tune.sidewalk + tune.shoulder + step
  -- Built-up share of the ground: building footprint in 50 m bins, read over the 3 x 3 bins
  -- round a point and blended between bin centres, so there is no step at a bin or tile edge.
  -- The cells carry their neighbours' buildings 100 m deep: bins up to 4 past the tile give a
  -- point within stripReach of it the same share from either tile beside it.
  local builtBins, builtShare, lowBins, lowShare = {}, {}, {}, {}
  for index, building in ipairs(lists.buildings) do
    local b = ringBounds(building.rings)
    if boundsTouch(b, rect, 4 * BUILT_BIN) then
      local footprint = 0
      for k, ring in ipairs(building.rings) do footprint = footprint + (k == 1 and 1 or -1) * math.abs(area2(ring)) / 2 end
      -- a house or a shed (one or two floors, small): its plot is a garden, not a town yard
      local tags = building.tags or NONE
      local levels = number(tags['building:levels'], 0)
      local low = footprint < 400 and levels <= 2 and (number(tags.height, 0) < 8)
        and (BLD.homes[tags.building or 'yes'] or BLD.low[tags.building or ''] ~= nil)
      local w, h = math.max(b[3] - b[1], EPS), math.max(b[4] - b[2], EPS)
      for gx = floor(b[1] / BUILT_BIN), floor(b[3] / BUILT_BIN) do
        local ox = math.min(b[3], (gx + 1) * BUILT_BIN) - math.max(b[1], gx * BUILT_BIN)
        for gy = floor(b[2] / BUILT_BIN), floor(b[4] / BUILT_BIN) do
          local oy = math.min(b[4], (gy + 1) * BUILT_BIN) - math.max(b[2], gy * BUILT_BIN)
          local id = (gx + 32768) * 65536 + gy + 32768
          local part = footprint * math.max(0, math.min(1, ox / w)) * math.max(0, math.min(1, oy / h))
          builtBins[id] = (builtBins[id] or 0) + part
          if low then lowBins[id] = (lowBins[id] or 0) + part end
        end
      end
    end
    if index % 256 == 0 then pause() end
  end
  local function binShare(gx, gy, bins, cache)
    bins, cache = bins or builtBins, cache or builtShare
    local id = (gx + 32768) * 65536 + gy + 32768
    local share = cache[id]
    if not share then
      share = 0
      for dx = -1, 1 do
        for dy = -1, 1 do share = share + (bins[(gx + dx + 32768) * 65536 + gy + dy + 32768] or 0) end
      end
      share = share / (9 * BUILT_BIN * BUILT_BIN)
      cache[id] = share
    end
    return share
  end
  -- built-up share round (x, y); low: only the houses' and sheds'
  local function builtAt(x, y, low)
    local bins, cache = low and lowBins or builtBins, low and lowShare or builtShare
    local fx, fy = x / BUILT_BIN - .5, y / BUILT_BIN - .5
    local gx, gy = floor(fx), floor(fy)
    local tx, ty = fx - gx, fy - gy
    local s00, s10 = binShare(gx, gy, bins, cache), binShare(gx + 1, gy, bins, cache)
    local s01, s11 = binShare(gx, gy + 1, bins, cache), binShare(gx + 1, gy + 1, bins, cache)
    local a = s00 + (s10 - s00) * tx
    local b = s01 + (s11 - s01) * tx
    return a + (b - a) * ty
  end
  -- Junctions from the road graph itself. A source road is one graph segment, its two ends
  -- the nodes road.nodes names, so a node's mouths are the road ends sharing its id. The pack
  -- builder's rules (fast_sources.write_index, fast.junction_star): a node of two or more mouths
  -- takes 0.8 x its widest road off every road end, at most a quarter of the road; each mouth has
  -- two corners at that distance, half a width either side (the direction over +-0.25 m), at the
  -- road's profile height; the corners in angle order round the node make its star. Every road
  -- touching a node near the tile is in the tile's cells, so neighbouring tiles agree.
  -- Two mouths meeting at a gentle angle (a way split by a tag change, a closed ring's seam, a
  -- roundabout arc) are one carriageway: no star, the strips share a mitred end (jointsOf).
  local cutsOf, stars, jointsOf = {}, {}, {}
  -- Tracks (path lines with the raw DEM at a few far-apart vertices) as ground ribbons that
  -- stop at the edge of every road they meet or cross. Drawn on across a road, a track's flat
  -- slab stood proud of the asphalt and threw cars off.
  do
    local kept = {}
    for index, road in ipairs(lists.roads) do
      if index % 64 == 0 then pause() end
      if road.track then
        for n, run in ipairs(ROADS.trackRuns(road.points or NONE, segmentBins, pulled, roadGrade(road.tags or NONE))) do
          kept[#kept + 1] = {id = road.id .. ':' .. n, points = run, width = road.width, tags = road.tags, track = true}
        end
      else
        kept[#kept + 1] = road
      end
    end
    lists.roads = kept
  end
  local details = DETAIL.index(distant and NONE or lists.points, {turning_circle = true})
  local function along(points, dist, s)
    for k = 1, #points - 1 do
      if s <= dist[k + 1] or k == #points - 1 then
        return lerp(points[k], points[k + 1], math.max(0, math.min(1, (s - dist[k]) / math.max(EPS, dist[k + 1] - dist[k]))))
      end
    end
    return points[1]
  end
  do
    local mouths, order = {}, {}
    for index, road in ipairs(lists.roads) do
      -- a city tile's cells hold thousands of roads: these loops ran 15-20 ms unbroken
      if index % 64 == 0 then pause() end
      local points, nodes = road.points or NONE, road.nodes or NONE
      if #points >= 2 and nodes[1] ~= nil and nodes[2] ~= nil then
        local dist = {0}
        for k = 2, #points do
          local a, b = points[k - 1], points[k]
          dist[k] = dist[k - 1] + math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2)
        end
        if dist[#points] > EPS then
          for e = 1, 2 do
            local id = tostring(nodes[e])
            local list = mouths[id]
            if not list then list = {}; mouths[id], order[#order + 1] = list, id end
            list[#list + 1] = {road = road, e = e, dist = dist, width = math.max(.5, math.min(80, road.width or 7))}
          end
        end
      end
    end
    -- the unit direction from the node into a mouth's road, over its first 2 m
    local function into(m)
      local points, dist = m.road.points, m.dist
      local length = dist[#points]
      local s = math.min(2, length)
      local node = along(points, dist, m.e == 1 and 0 or length)
      local p = along(points, dist, m.e == 1 and s or length - s)
      local dx, dy = p[1] - node[1], p[2] - node[2]
      local l = math.max(EPS, math.sqrt(dx * dx + dy * dy))
      return dx / l, dy / l
    end
    for index, id in ipairs(order) do
      if index % 32 == 0 then pause() end
      local list = mouths[id]
      local joined = false
      if #list == 2 then
        local ax, ay = into(list[1])
        local bx, by = into(list[2])
        -- at most a 60 degree turn: the mitre is at most 1 / cos 30 = 1.15 of the half width
        if ax * bx + ay * by < -.5 then
          joined = true
          local tx, ty = bx - ax, by - ay
          local l = math.max(EPS, math.sqrt(tx * tx + ty * ty))
          tx, ty = tx / l, ty / l
          for k, m in ipairs(list) do
            -- the strip's own direction at this end runs into the road at its start, to the
            -- node at its end; the joint's tangent turned the same way
            local dx, dy = (k == 1 and ax or bx), (k == 1 and ay or by)
            if m.e == 2 then dx, dy = -dx, -dy end
            local sign = (tx * dx + ty * dy) >= 0 and 1 or -1
            local mitre = 1 / math.max(.5, math.abs(tx * dx + ty * dy))
            local joints = jointsOf[m.road] or {}
            jointsOf[m.road], joints[m.e] = joints, {tx * sign, ty * sign, mitre}
          end
        end
      end
      local first = list[1]
      local fp = first.road.points
      local node = first.e == 1 and fp[1] or fp[#fp]
      -- a dead end mapped as a turning circle: a one-mouth star with a round far side
      local bulb = #list == 1 and DETAIL.at(details, node[1], node[2], 'turning_circle')
        and DETAIL.bulbRadius(first.width) or nil
      if (#list > 1 and not joined) or bulb then
        local radius = bulb or 0
        for _, m in ipairs(list) do radius = math.max(radius, m.width * .8) end
        -- the fan's material: the one most of its mouths have (a roundabout's entry keeps the
        -- ring's), on a tie the more important road's
        local corners, raised, votes, material, top = {}, false, {}, nil, -1
        for _, m in ipairs(list) do
          local mat = roadMaterial(m.road.tags or NONE)
          local vote = votes[mat] or {n = 0, rank = -1}
          votes[mat], vote.n = vote, vote.n + 1
          vote.rank = math.max(vote.rank, ROADS.rankOf(m.road.tags or NONE))
          if vote.n * 100 + vote.rank > top then material, top = mat, vote.n * 100 + vote.rank end
          local points, dist = m.road.points, m.dist
          local length = dist[#points]
          local cut = math.min(radius, length * .25)
          local cuts = cutsOf[m.road] or {0, 0}
          cutsOf[m.road], cuts[m.e] = cuts, cut
          local s = m.e == 1 and cut or length - cut
          local p = along(points, dist, s)
          local f, b = along(points, dist, math.min(length, s + .25)), along(points, dist, math.max(0, s - .25))
          local dx, dy = f[1] - b[1], f[2] - b[2]
          local l = math.max(EPS, math.sqrt(dx * dx + dy * dy))
          local nx, ny = -dy / l * m.width / 2, dx / l * m.width / 2
          corners[#corners + 1] = {p[1] + nx, p[2] + ny, p[3] or 0}
          corners[#corners + 1] = {p[1] - nx, p[2] - ny, p[3] or 0}
          if ROADS.bridge(m.road.tags or NONE) then raised = true end
        end
        if bulb then
          local dx, dy = into(first)
          local cut = (cutsOf[first.road] or NONE)[first.e] or 0
          for _, q in ipairs(DETAIL.bulb(node, dx, dy, first.width / 2, cut, bulb)) do corners[#corners + 1] = q end
        end
        local angle = {}
        for _, c in ipairs(corners) do angle[c] = math.atan2(c[2] - node[2], c[1] - node[1]) end
        table.sort(corners, function(a, b) return angle[a] < angle[b] end)
        stars[#stars + 1] = {node = {node[1], node[2]}, height = node[3] or 0, rings = {corners}, raised = raised,
          material = material}
      end
    end
  end
  local trimmed = {}
  for _, road in ipairs(lists.roads) do
    local tags, raw, width = road.tags or {}, road.points or {}, math.max(.5, math.min(80, road.width or 7))
    local points = {}
    for _, p in ipairs(raw) do
      local q = points[#points]
      if not q or math.abs(q[1] - p[1]) + math.abs(q[2] - p[2]) > 1e-4 then
        points[#points + 1] = {p[1], p[2], p[3] or 0}
      end
    end
    -- the road stops at its junction mouths; the junction's own surface is between
    local cuts, full = cutsOf[road], points
    if cuts and #points >= 2 and (cuts[1] > 0 or cuts[2] > 0) then points = trimLine(points, cuts[1], cuts[2]) end
    if tune.simplifyXY > 0 then points = simplify(points, tune.simplifyXY, tune.simplifyZ) end
    if #points >= 2 and boundsTouch(rect, ringBounds({points}), width / 2 + stripReach) then
      local grade = roadGrade(tags)
      points = densifyWear(points, grade)
      local normals, hw = {}, width / 2
      for k = 1, #points do
        local tx, ty = 0, 0
        for _, pair in ipairs({{k - 1, k}, {k, k + 1}}) do
          local a, b = points[pair[1]], points[pair[2]]
          if a and b then
            local dx, dy = b[1] - a[1], b[2] - a[2]
            local l = math.sqrt(dx * dx + dy * dy)
            tx, ty = tx + dx / l, ty + dy / l
          end
        end
        local l = math.max(EPS, math.sqrt(tx * tx + ty * ty))
        -- a mitre keeps the full width on a bend: the mean of two unit directions is cos(turn / 2)
        -- long (each segment counted once at an end); capped so a hairpin does not spike
        local ends = (k == 1 or k == #points) and 1 or 2
        local mitre = math.min(tune.mitre, ends / l)
        normals[k] = {-ty / l * mitre, tx / l * mitre}
      end
      -- a joined end: the two strips share the bisecting edge, no wedge between them
      local joints = jointsOf[road]
      if joints and #points >= 2 then
        for e, k in ipairs({1, #points}) do
          local j = joints[e]
          if j then normals[k] = {-j[2] * j[3], j[1] * j[3]} end
        end
      end
      local surfaceRoad = not ROADS.bridge(tags) and not ROADS.tunnel(tags)
      local material = roadMaterial(tags)
      -- a grass track where the open ground is desert, dry grass, turf or snow is a dirt track
      -- (a green ribbon ran across the Owens Valley)
      if material == 'road_track' and bio.on and points[1] and surfaceKind(points[1][1], points[1][2], 'ground') ~= 'ground' then
        material = 'road_dirt'
      end
      local dist = {0}   -- along the strip, for the UVs of its curbs and edges
      for k = 2, #points do
        dist[k] = dist[k - 1] + math.sqrt((points[k][1] - points[k - 1][1]) ^ 2 + (points[k][2] - points[k - 1][2]) ^ 2)
      end
      -- The sides a segment has sidewalks on: the tags', or for an untagged street only where
      -- it is built up (walkAt).
      local sides, walk = walkSides(tags), {}
      for k = 1, #points - 1 do walk[k] = walkAt(tags, sides, points[k], points[k + 1], builtAt) end
      -- start: metres of the road cut off before points[1] (street props keep the road's lattice);
      -- joints: its ends that run on into the next way (no junction there)
      local strip = {road = road, points = points, normals = normals, hw = hw, tags = tags, dist = dist,
        surface = surfaceRoad, material = material, grade = grade, sides = sides, walk = walk,
        start = cuts and cuts[1] or 0, joints = joints}
      strips[#strips + 1] = strip
      trimmed[road] = points
      -- A cut mouth's corridor back to its node, a centimetre under the junction fan: drawn only
      -- where the junction's star misses this mouth (an odd star, e.g. a short wide link between
      -- two carriageways, whose fan leaves gaps).
      strip.corridors = {}
      for _, e in ipairs(points ~= full and surfaceRoad and {{1, full[1]}, {#points, full[#full]}} or NONE) do
        local k, node = e[1], e[2]
        local p, n = points[k], normals[k]
        local nl = math.sqrt(n[1] * n[1] + n[2] * n[2])
        if math.sqrt((p[1] - node[1]) ^ 2 + (p[2] - node[2]) ^ 2) > .05 and nl > EPS then
          strip.nodes = strip.nodes or {}
          strip.nodes[k] = node
          local ux, uy = n[1] / nl * hw, n[2] / nl * hw
          local zp, zn = (p[3] or 0) + lift - .01, (node[3] or 0) + lift - .01
          local quad = {{p[1] + ux, p[2] + uy, zp}, {p[1] - ux, p[2] - uy, zp},
            {node[1] - ux, node[2] - uy, zn}, {node[1] + ux, node[2] + uy, zn}}
          strip.corridors[k] = quad
        end
      end
      local function edge(k, offset, dz)
        local p, n = points[k], normals[k]
        local widen = 1
        if grade >= 4 and k > 1 and k < #points then
          widen = 1 + (hash('edge:' .. floor(p[1] + .5) .. ':' .. floor(p[2] + .5)) % 1000 / 1000 - .5) * .34
        end
        return {p[1] + n[1] * offset * widen, p[2] + n[2] * offset * widen, (p[3] or 0) + lift + (dz or 0)}
      end
      strip.edge = edge
      for k = 1, #points - 1 do
        local a, b = points[k], points[k + 1]
        local quad = {edge(k, hw), edge(k, -hw), edge(k + 1, -hw), edge(k + 1, hw)}
        local box = ringBounds({quad})
        if boundsTouch(rect, box, stripReach) then
          if surfaceRoad then addAsphalt(quad, strip, k) end
          if drawn(strip) and boundsTouch(rect, box, 0) and (farRoads or not road.deckGroup) then
            emitSurface(strip.material, quad)
          end
          local dx, dy = b[1] - a[1], b[2] - a[2]
          local length = math.sqrt(dx * dx + dy * dy)
          local t = math.max(0, math.min(1, ((target[1] - a[1]) * dx + (target[2] - a[2]) * dy) / (length * length)))
          local p = lerp(a, b, t)
          local distance = (p[1] - target[1]) ^ 2 + (p[2] - target[2]) ^ 2
          if distance < bestDistance and p[1] >= rect[1] and p[1] <= rect[3] and p[2] >= rect[2] and p[2] <= rect[4] then
            bestDistance = distance
            bestSpawn = {pos = {p[1], p[2], (p[3] or 0) + lift}, yaw = math.atan2(dx, dy)}
          end
        end
        if k % 32 == 0 then pause() end
      end
    end
    pause()
  end
  -- A bridge's deck: concrete edge faces from the road (or sidewalk) edge down to the soffit,
  -- the soffit itself, and a parapet on either side, all solid. Every face is a whole quad of
  -- its segment, clipped to the tile like the fences.
  if visualRoads then
    -- A grouped carriageway whose mate missed this tile keeps the ordinary deck. The pair
    -- itself is drawn once, below, so the two asphalt strips do not z-fight in the median.
    local groupCount = {}
    for _, strip in ipairs(strips) do
      local id = strip.road and strip.road.deckGroup
      if id then groupCount[id] = (groupCount[id] or 0) + 1 end
    end
    for _, strip in ipairs(strips) do
      local id = strip.road and strip.road.deckGroup
      if id and groupCount[id] < 2 then
        local points, edge, hw = strip.points, strip.edge, strip.hw
        for k = 1, #points - 1 do
          local quad = {edge(k, hw), edge(k, -hw), edge(k + 1, -hw), edge(k + 1, hw)}
          if boundsTouch(rect, ringBounds({quad}), 0) then roads.polygon(strip.material, quad, 'flat') end
        end
        strip.road.deckGroup = nil
      end
    end
    local deck = ROADS.deck
    local function face(poly, ox, oy, oz, material)
      -- turned to face (ox, oy, oz): Newell's normal of the quad
      local nx, ny, nz = 0, 0, 0
      for k = 1, #poly do
        local a, b = poly[k], poly[k % #poly + 1]
        nx, ny, nz = nx + (a[2] - b[2]) * (a[3] + b[3]), ny + (a[3] - b[3]) * (a[1] + b[1]), nz + (a[1] - b[1]) * (a[2] + b[2])
      end
      if nx * ox + ny * oy + nz * oz < 0 then
        local flipped = {}
        for k = #poly, 1, -1 do flipped[#flipped + 1] = poly[k] end
        poly = flipped
      end
      scene.polygon(material or 'fence_wall', poly, false)
    end
    -- Two decks of one road side by side (a dual carriageway's bridges, ~10 m apart and 11.5 m
    -- wide in Kyiv) overlap in plan: each one's parapet stood on the other's carriageway and
    -- stopped the car. A side whose parapet line lies on another strip's surface at the deck's
    -- height (within 1.5 m) gets no parapet or edge face; the two decks read as one.
    local deckBins = {}
    for _, other in ipairs(strips) do
      local pts = other.points
      for k = 1, #pts - 1 do
        local a, b = pts[k], pts[k + 1]
        local reach = other.hw + tune.sidewalk + 1
        for by = floor((math.min(a[2], b[2]) - reach) / 50), floor((math.max(a[2], b[2]) + reach) / 50) do
          for bx = floor((math.min(a[1], b[1]) - reach) / 50), floor((math.max(a[1], b[1]) + reach) / 50) do
            local bin = deckBins[bx * 65536 + by] or {}
            deckBins[bx * 65536 + by], bin[#bin + 1] = bin, {other, k}
          end
        end
      end
    end
    -- own: a strip, or a set of strips (a united deck's carriageways)
    local function onOtherSurface(own, p)
      for _, entry in ipairs(deckBins[floor(p[1] / 50) * 65536 + floor(p[2] / 50)] or NONE) do
        local other, k = entry[1], entry[2]
        if other ~= own and not (own.members and own.members[other]) then
          local a, b = other.points[k], other.points[k + 1]
          local dx, dy = b[1] - a[1], b[2] - a[2]
          local len2 = dx * dx + dy * dy
          if len2 > EPS then
            local t = math.max(0, math.min(1, ((p[1] - a[1]) * dx + (p[2] - a[2]) * dy) / len2))
            local d = math.sqrt((p[1] - a[1] - t * dx) ^ 2 + (p[2] - a[2] - t * dy) ^ 2)
            local side = (p[1] - a[1]) * -dy + (p[2] - a[2]) * dx >= 0 and 1 or -1
            local reach = other.hw + (other.walk[k][side] and tune.sidewalk or 0) + .5
            local z = (a[3] or 0) + t * ((b[3] or 0) - (a[3] or 0)) + lift
            if d < reach and math.abs(z - p[3]) < 1.5 then return true end
          end
        end
      end
      return false
    end
    for _, strip in ipairs(strips) do
      if ROADS.bridge(strip.tags) and not (strip.road and strip.road.deckGroup) then
        local points, edge, hw = strip.points, strip.edge, strip.hw
        local depth = ROADS.deckDepth(strip.tags)
        for k = 1, #points - 1 do
          local box = ringBounds({{points[k], points[k + 1]}})
          if boundsTouch(rect, box, hw + tune.sidewalk + 1) then
            local u0, u1 = strip.dist[k] / deck.repeatU, strip.dist[k + 1] / deck.repeatU
            local function at(i, offset, dz, u, v)
              local p = edge(i, offset, dz)
              p[4], p[5] = u, v
              return p
            end
            local dx, dy = points[k + 1][1] - points[k][1], points[k + 1][2] - points[k][2]
            for _, sign in ipairs({1, -1}) do
              local outer = (hw + (strip.walk[k][sign] and tune.sidewalk or 0)) * sign
              local inner = outer - deck.thick * sign
              local ox, oy = -dy * sign, dx * sign
              -- Piece by piece (~2 m): only the stretch over another carriageway goes. A slip road
              -- leaving the deck, or a deck beside it, covers part of a segment; judged whole (2 of 3
              -- samples) the parapet stood across the mouth, a barrier across the road.
              local a0, b0 = edge(k, outer), edge(k + 1, outer)
              local n = math.max(1, math.ceil(math.sqrt((b0[1] - a0[1]) ^ 2 + (b0[2] - a0[2]) ^ 2) / 2))
              local free = {}
              for s = 1, n do
                local f = (s - .5) / n
                free[s] = not onOtherSurface(strip, {a0[1] + (b0[1] - a0[1]) * f, a0[2] + (b0[2] - a0[2]) * f, a0[3] + (b0[3] - a0[3]) * f})
              end
              -- a point of the parapet line at fraction f of the segment, with its texture u
              local function along(offset, dz, f, v)
                local a, b = at(k, offset, dz, u0, v), at(k + 1, offset, dz, u1, v)
                return {a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f, a[4] + (b[4] - a[4]) * f, v}
              end
              local top, low = deck.parapet, -depth
              local s = 1
              while s <= n do
                if free[s] then
                  local e = s
                  while e < n and free[e + 1] do e = e + 1 end
                  local f0, f1 = (s - 1) / n, e / n
                  -- the edge face, outside, from the parapet's top to the soffit
                  face({along(outer, top, f0, 0), along(outer, top, f1, 0),
                    along(outer, low, f1, (top - low) / deck.repeatU), along(outer, low, f0, (top - low) / deck.repeatU)}, ox, oy, 0)
                  -- the parapet's inner face and its top
                  face({along(inner, top, f0, 0), along(inner, top, f1, 0),
                    along(inner, 0, f1, top / deck.repeatU), along(inner, 0, f0, top / deck.repeatU)}, -ox, -oy, 0)
                  face({along(inner, top, f0, 0), along(inner, top, f1, 0),
                    along(outer, top, f1, deck.thick / deck.repeatU), along(outer, top, f0, deck.thick / deck.repeatU)}, 0, 0, 1)
                  s = e + 1
                else
                  s = s + 1
                end
              end
            end
            -- the soffit, seen from the road under the bridge
            local l = (hw + (strip.walk[k][1] and tune.sidewalk or 0))
            local r = -(hw + (strip.walk[k][-1] and tune.sidewalk or 0))
            face({at(k, l, -depth, u0, 0), at(k + 1, l, -depth, u1, 0),
              at(k + 1, r, -depth, u1, (l - r) / deck.repeatU), at(k, r, -depth, u0, (l - r) / deck.repeatU)}, 0, 0, -1)
          end
          if k % 32 == 0 then pause() end
        end
      end
    end
    ROADS.unitedDecks({strips = strips, rect = rect, ground = ground, face = face, roads = roads,
      lift = lift, pause = pause, sidewalk = tune.sidewalk, onOther = onOtherSurface})
    ROADS.substructure({strips = strips, rect = rect, ground = ground, face = face, pause = pause, sidewalk = tune.sidewalk})
    ROADS.embankmentRails({strips = strips, rect = rect, dem = #terrain > 0 and demAt or nil, face = face, pause = pause, sidewalk = tune.sidewalk,
      crowded = function(x, y, road, clear)
        for _, segment in ipairs(segmentBins[(floor(x / 50) + 32768) * 65536 + floor(y / 50) + 32768] or NONE) do
          if segment.road ~= road then
            local a = segment.a
            local t = math.max(0, math.min(1, ((x - a[1]) * segment.dx + (y - a[2]) * segment.dy) / math.max(EPS, segment.len2)))
            local ex, ey = x - a[1] - t * segment.dx, y - a[2] - t * segment.dy
            local r = segment.width / 2 + clear
            if ex * ex + ey * ey < r * r then return true end
          end
        end
        return false
      end})
  end
  mark('strips')
  -- ROADS.wing: the steep ground at an abutment is drawn as its concrete
  do
    local wing, bins, deckEnds = ROADS.wing, nil, {}
    for _, strip in ipairs(strips) do
      local nodes = ROADS.bridge(strip.tags) and strip.road and strip.road.nodes or NONE
      for e = 1, 2 do
        if nodes[e] ~= nil then deckEnds[tostring(nodes[e])] = (deckEnds[tostring(nodes[e])] or 0) + 1 end
      end
    end
    for _, strip in ipairs(strips) do
      local nodes, raw = strip.road and strip.road.nodes or NONE, strip.road and strip.road.points or strip.points
      for e = 1, 2 do
        if ROADS.bridge(strip.tags) and nodes[e] ~= nil and deckEnds[tostring(nodes[e])] == 1 and #raw >= 2 then
          local p, r = raw[e == 1 and 1 or #raw], strip.hw + wing.reach
          local s = {p[1], p[2], strip.hw}
          bins = bins or {}
          for bx = floor((p[1] - r) / 50), floor((p[1] + r) / 50) do
            for by = floor((p[2] - r) / 50), floor((p[2] + r) / 50) do
              local key = (bx + 32768) * 65536 + by + 32768
              local bin = bins[key] or {}
              bins[key], bin[#bin + 1] = bin, s
            end
          end
        end
      end
    end
    if bins then
      local function steep(kind, a, b, c)
        local decal = wing.decals[kind]
        if not decal and not wing.covers[kind] then return nil end
        local x, y = (a[1] + b[1] + c[1]) / 3, (a[2] + b[2] + c[2]) / 3
        for _, s in ipairs(bins[(floor(x / 50) + 32768) * 65536 + floor(y / 50) + 32768] or NONE) do
          if math.sqrt((x - s[1]) ^ 2 + (y - s[2]) ^ 2) - s[3] <= wing.reach then
            return not decal and wing.material
          end
        end
        return nil
      end
      for _, c in ipairs({roads, scene, roadDecor}) do
        c.hooks.steep, c.hooks.nz, c.hooks.scale = steep, math.cos(math.rad(wing.steep)), ROADS.deck.repeatU
      end
    end
  end
  -- Strip ends of streets with sidewalks, by the metre: a junction with one of them at a mouth
  -- gets a sidewalk ring.
  local walkEnds = {}
  for _, strip in ipairs(strips) do
    local last = #strip.points
    for _, e in ipairs({{strip.points[1], 1}, {strip.points[last], last - 1}}) do
      if next(strip.walk[e[2]] or NONE) then
        local p = e[1]
        local key = (floor(p[1]) + 65536) * 131072 + floor(p[2]) + 65536
        local list = walkEnds[key] or {}
        walkEnds[key], list[#list + 1] = list, p
      end
    end
  end
  -- Every strip end by the metre, with its direction into the road: a junction's mouth is the
  -- edge between two corners whose midpoint is a strip end.
  local stripEnds, corridors, corridorOf, corridorsAt = {}, {}, {}, {}
  for _, strip in ipairs(strips) do
    local pts = strip.points
    for _, e in ipairs({{pts[1], pts[2], 1}, {pts[#pts], pts[#pts - 1], #pts}}) do
      local p, q = e[1], e[2]
      local dx, dy = q[1] - p[1], q[2] - p[2]
      local l = math.max(EPS, math.sqrt(dx * dx + dy * dy))
      local key = (floor(p[1]) + 65536) * 131072 + floor(p[2]) + 65536
      local list = stripEnds[key] or {}
      local corridor = strip.corridors and strip.corridors[e[3]]
      stripEnds[key], list[#list + 1] = list, {p = p, dx = dx / l, dy = dy / l, corridor = corridor}
      if corridor then
        local node = strip.nodes[e[3]]
        local c = {quad = corridor, material = strip.material}
        corridors[#corridors + 1], corridorOf[corridor] = c, c
        local key = floor(node[1] * 10 + .5) * 2 ^ 26 + floor(node[2] * 10 + .5)
        local list = corridorsAt[key] or {}
        corridorsAt[key], list[#list + 1] = list, c
      end
    end
  end
  local function stripEndAt(x, y)
    for dx = -1, 1 do
      for dy = -1, 1 do
        for _, e in ipairs(stripEnds[(floor(x) + dx + 65536) * 131072 + floor(y) + dy + 65536] or NONE) do
          if (e.p[1] - x) ^ 2 + (e.p[2] - y) ^ 2 < .01 then return e end
        end
      end
    end
  end
  local function walkEndNear(x, y)
    for dx = -1, 1 do
      for dy = -1, 1 do
        for _, p in ipairs(walkEnds[(floor(x) + dx + 65536) * 131072 + floor(y) + dy + 65536] or NONE) do
          if (p[1] - x) ^ 2 + (p[2] - y) ^ 2 < .01 then return true end
        end
      end
    end
    return false
  end
  local plates = {}
  -- Junctions: a fan from the node over its star, each corner at its road's profile, so the
  -- surface meets every cut road end without a step.
  for _, junction in ipairs(stars) do
    local rings = junction.rings or NONE
    local ring = cleanRing(rings[1])
    if #ring >= 3 and boundsTouch(rect, ringBounds({ring}), stripReach) then
      local cx, cy = junction.node[1], junction.node[2]
      local centre = junction.height + lift
      local corners = {}
      for k, p in ipairs(ring) do corners[k] = {p[1], p[2], p[3] + lift} end
      do
        -- Between two mouths the star's chord cut the inner corner off (a wedge of grass in the
        -- asphalt, up to several m2): the edges of the two roads meet at a point instead.
        local n, dirs = #corners, {}
        local mouth = {}
        for k = 1, n do
          local a, b = corners[k], corners[k % n + 1]
          local e = stripEndAt((a[1] + b[1]) / 2, (a[2] + b[2]) / 2)
          if e then
            mouth[k], dirs[k], dirs[k % n + 1] = true, e, e
            if e.corridor then corridorOf[e.corridor].fanned = true end
          end
        end
        -- one mouth of this node missing from the star: the star is odd (interleaved corners),
        -- so every road here keeps its corridor
        local odd = false
        for _, c in ipairs(corridorsAt[floor(cx * 10 + .5) * 2 ^ 26 + floor(cy * 10 + .5)] or NONE) do
          if not c.fanned then odd = true end
        end
        if odd then
          for _, c in ipairs(corridorsAt[floor(cx * 10 + .5) * 2 ^ 26 + floor(cy * 10 + .5)] or NONE) do c.fanned = false end
        end
        local out = {}
        for k = 1, n do
          local a, b = corners[k], corners[k % n + 1]
          out[#out + 1] = a
          local ea, eb = dirs[k], dirs[k % n + 1]
          if not mouth[k] and ea and eb and ea ~= eb then
            -- a + t * ea = b + u * eb
            local det = ea.dx * (-eb.dy) - ea.dy * (-eb.dx)
            if math.abs(det) > .2 then
              local rx, ry = b[1] - a[1], b[2] - a[2]
              local t = (rx * (-eb.dy) - ry * (-eb.dx)) / det
              local u = (ea.dx * ry - ea.dy * rx) / det
              local reach = math.sqrt((a[1] - cx) ^ 2 + (a[2] - cy) ^ 2) + math.sqrt((b[1] - cx) ^ 2 + (b[2] - cy) ^ 2)
              local x, y = a[1] + ea.dx * t, a[2] + ea.dy * t
              -- only on the far side of the chord from the node (else the fan would lose the
              -- triangle between them), and near (not a spike between near-parallel roads)
              local away = (b[1] - a[1]) * (y - a[2]) - (b[2] - a[2]) * (x - a[1])
              local node = (b[1] - a[1]) * (cy - a[2]) - (b[2] - a[2]) * (cx - a[1])
              if away * node < 0 and math.abs(t) < reach and math.abs(u) < reach then
                out[#out + 1] = {x, y, (a[3] + b[3]) / 2}
              end
            end
          end
        end
        corners = out
      end
      local plate = {ring = corners, centre = {cx, cy, centre}}
      plates[#plates + 1] = plate
      local touches = boundsTouch(rect, ringBounds({ring}), 0)
      for k = 1, #corners do
        local tri = {{cx, cy, centre}, corners[k], corners[k % #corners + 1]}
        addAsphalt(tri, nil, nil)
        if (visualRoads or farRoads) and touches then emitSurface(junction.material or minorRoad, tri) end
      end
      -- round a ground-level star (fast.junction_verge): a sidewalk ring when a street with
      -- sidewalks meets here, then the verge down to the ground, both away from the node
      if not junction.raised then
        local walks = false
        for k = 1, #corners do
          local a, b = corners[k], corners[k % #corners + 1]
          if walkEndNear((a[1] + b[1]) / 2, (a[2] + b[2]) / 2) then walks = true; break end
        end
        local inset = walks and tune.sidewalk or 0
        local mids, outs = {}, {}
        for k, q in ipairs(corners) do
          local dx, dy = q[1] - cx, q[2] - cy
          local l = math.max(EPS, math.sqrt(dx * dx + dy * dy))
          dx, dy = dx / l, dy / l
          mids[k] = {q[1] + dx * inset, q[2] + dy * inset, q[3]}
          outs[k] = {q[1] + dx * (inset + tune.shoulder), q[2] + dy * (inset + tune.shoulder), 0}
        end
        plate.mids, plate.walks, plate.verges = mids, {}, {}
        for k = 1, #corners do
          local n = k % #corners + 1
          if walks then plate.walks[#plate.walks + 1] = {corners[k], corners[n], mids[n], mids[k]} end
          if tune.shoulder > 0 then plate.verges[#plate.verges + 1] = {mids[k], mids[n], outs[n], outs[k]} end
        end
      end
    end
    pause()
  end

  for _, c in ipairs(corridors) do
    if not c.fanned then
      local box = ringBounds({c.quad})
      if boundsTouch(rect, box, stripReach) then
        addAsphalt(c.quad, nil, nil)
        if (visualRoads or farRoads) and boundsTouch(rect, box, 0) then emitSurface(c.material, c.quad) end
      end
    end
  end

  -- Convex polygon minus convex polygons (Sutherland-Hodgman per edge): the pieces of a
  -- sidewalk or verge that are not on asphalt. z and UVs are interpolated along the cuts.
  local function side(ax, ay, bx, by, p) return (bx - ax) * (p[2] - ay) - (by - ay) * (p[1] - ax) end
  local function split(poly, ax, ay, bx, by, ccw)
    local inside, outside = {}, {}
    local n = #poly
    for k = 1, n do
      local p, q = poly[k], poly[k % n + 1]
      local sp, sq = side(ax, ay, bx, by, p), side(ax, ay, bx, by, q)
      if not ccw then sp, sq = -sp, -sq end
      if sp >= -1e-9 then inside[#inside + 1] = p end
      if sp <= 1e-9 then outside[#outside + 1] = p end
      if (sp > 1e-9 and sq < -1e-9) or (sp < -1e-9 and sq > 1e-9) then
        local x = lerp(p, q, sp / (sp - sq))
        inside[#inside + 1], outside[#outside + 1] = x, x
      end
    end
    return inside, outside
  end
  -- Some edge of c has every vertex of poly strictly on its outer side.
  local function beyond(poly, c, ccw)
    for k = 1, #c do
      local a, b = c[k], c[k % #c + 1]
      local ax, ay, bx, by = a[1], a[2], b[1], b[2]
      local all = true
      for n = 1, #poly do
        local sd = side(ax, ay, bx, by, poly[n])
        if (ccw and sd > -1e-9) or (not ccw and sd < 1e-9) then all = false; break end
      end
      if all then return true end
    end
    return false
  end
  local cutOps = 0
  local function subtract(poly, skip)
    local pieces = {poly}
    local box = ringBounds({poly})
    local pccw = area2(poly) > 0
    local seen = {}
    for by = math.floor(box[2] / ABIN), math.floor(box[4] / ABIN) do
      for bx = math.floor(box[1] / ABIN), math.floor(box[3] / ABIN) do
        for _, entry in ipairs(asphaltBins[(bx + 32768) * 65536 + by + 32768] or NONE) do
          if not seen[entry] and boundsTouch(box, entry.bounds) and not (skip and skip(entry)) then
            seen[entry] = true
            local c, ccw = entry.poly, entry.ccw
            local out, cut = {}, false
            for _, piece in ipairs(pieces) do
              -- separated convex pieces (the usual case: only the bounds touch) stay whole
              if beyond(piece, c, ccw) or beyond(c, piece, pccw) then
                out[#out + 1] = piece
              else
                cut = true
                local rest = piece
                for k = 1, #c do
                  local a, b = c[k], c[k % #c + 1]
                  local inner, outer = split(rest, a[1], a[2], b[1], b[2], ccw)
                  if #outer >= 3 and math.abs(area2(outer)) > 2e-4 then out[#out + 1] = outer end
                  rest = inner
                  if #rest < 3 or math.abs(area2(rest)) <= 2e-4 then break end
                end
              end
              cutOps = cutOps + 1
              if cutOps % 32 == 0 then pause() end
            end
            if cut then pieces = out end
            if #pieces == 0 then return pieces end
          end
        end
      end
    end
    return pieces
  end
  local function emit(collectorOf, material, poly, skip, up)
    -- Distant tiles skip the carriageway. The verge is the transition band: the same
    -- ground wedge the near tile cuts at this edge, so the shared border keeps its vertices.
    if not visualRoads and not (distant and material == 'ground') then return end
    for _, piece in ipairs(subtract(poly, skip)) do
      if material == 'ground' then
        -- Outer edge points are marked at [9]. Resample them after the clip: a linear
        -- blend of the two tiles' endpoint heights does not land on the shared ground().
        local clipped = clip(piece, rect)
        local shaded = {}
        local cx, cy = 0, 0
        for i, p in ipairs(clipped) do
          local z = p[3] or 0
          if (p[9] or 0) > 0.9 then z = ground(p[1], p[2]) end
          local q = {p[1], p[2], z}
          q[6], q[7], q[8] = groundNormal(p[1], p[2])
          shaded[i] = q
          cx, cy = cx + p[1], cy + p[2]
        end
        -- a verge is the place's own ground: desert, alpine turf or snow, not a green band
        local kind = material
        if bio.on and #shaded >= 3 then kind = surfaceKind(cx / #shaded, cy / #shaded, 'ground') end
        if #shaded >= 3 then collectorOf.polygon(kind, shaded, up) end
      else
        collectorOf.polygon(material, piece, up)
      end
    end
  end
  mark('plates')
  -- Sidewalks flush with the road (a curb band, then paving) on the sides the tags allow, cut by
  -- every carriageway and junction; verges from the outer edge down to the ground, cut the same.
  for _, strip in ipairs(strips) do
    local points, hw, edge = strip.points, strip.hw, strip.edge
    local own = function(entry) return entry.road == strip end
    for k = 1, #points - 1 do
      local box = ringBounds({{points[k], points[k + 1]}})
      if boundsTouch(rect, box, hw + stripReach) then
        local near = function(entry) return entry.road == strip and math.abs(entry.index - k) <= 1 end
        for _, sign in ipairs({1, -1}) do
          local walk = strip.walk[k][sign] and tune.sidewalk or 0
          local outer = hw + walk
          if walk > 0 then
            local curb = math.min(tune.curb, walk)
            local band = {edge(k, sign * hw), edge(k, sign * (hw + curb)), edge(k + 1, sign * (hw + curb)), edge(k + 1, sign * hw)}
            local paved = {edge(k, sign * (hw + curb)), edge(k, sign * outer), edge(k + 1, sign * outer), edge(k + 1, sign * (hw + curb))}
            if boundsTouch(rect, ringBounds({band, paved}), 0) then
              if curb > 0 then
                -- u along the curb from the strip's own distance, v across the trim row
                local u0 = strip.dist[k] / DECAL.curbRepeat % 1
                local u1 = u0 + (strip.dist[k + 1] - strip.dist[k]) / DECAL.curbRepeat
                band[1][4], band[1][5], band[2][4], band[2][5] = u0, DECAL.curbRow[1], u0, DECAL.curbRow[2]
                band[3][4], band[3][5], band[4][4], band[4][5] = u1, DECAL.curbRow[2], u1, DECAL.curbRow[1]
                emit(roads, 'curb', band, near, 'flat')
              end
              emit(roads, 'sidewalk', paved, near, 'flat')
            end
          end
          if strip.surface and tune.shoulder > 0 then
            local inner = {edge(k, sign * outer, -tune.vergeSink), edge(k + 1, sign * outer, -tune.vergeSink)}
            local o1, o2 = edge(k, sign * (outer + tune.shoulder)), edge(k + 1, sign * (outer + tune.shoulder))
            local verge = {inner[1], o1, o2, inner[2]}
            -- a carriageway edge (no sidewalk) also gets an edge decal once the ground is final;
            -- its part over the asphalt can reach a tile whose rect the verge misses
            if boundsTouch(rect, ringBounds({verge}), walk == 0 and DECAL.edgeIn or 0) then
              strip.verges = strip.verges or {}
              strip.verges[#strip.verges + 1] = {verge, own, k = k, edge = walk == 0}
            end
          end
        end
      end
      if k % 32 == 0 then pause() end
    end
    pause()
  end
  mark('sidewalks')
  for _, plate in ipairs(plates) do
    for _, quad in ipairs(plate.walks or NONE) do
      if boundsTouch(rect, ringBounds({quad}), 0) then emit(roads, 'sidewalk', quad, nil, 'flat') end
    end
  end
  -- Press the lattice under every surface strip (road and sidewalk, sampled every 2 m from each
  -- segment's start) and under junction plates, then the verges take the lowered ground.
  -- One sample count for every strip: a city's short strips never reached a per-strip k % 16.
  local pressed = 0
  for _, strip in ipairs(strips) do
    if strip.surface then
      local points, hw = strip.points, strip.hw
      for k = 1, #points - 1 do
        local a, b = points[k], points[k + 1]
        local length = math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2)
        if boundsTouch(rect, ringBounds({{a, b}}), hw + tune.sidewalk + step + 1) then
          local left = hw + (strip.walk[k][1] and tune.sidewalk or 0)
          local right = hw + (strip.walk[k][-1] and tune.sidewalk or 0)
          local na, nb = strip.normals[k], strip.normals[k + 1]
          local samples = math.max(1, math.ceil(length / 2))
          for s = 0, samples do
            local t = s / samples
            local x, y = a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t
            local nx, ny = na[1] + (nb[1] - na[1]) * t, na[2] + (nb[2] - na[2]) * t
            local z = (a[3] or 0) + ((b[3] or 0) - (a[3] or 0)) * t + lift - tune.margin
            for _, offset in ipairs({-right, -hw, -hw * .5, 0, hw * .5, hw, left}) do
              press(x + nx * offset, y + ny * offset, z)
            end
            pressed = pressed + 1
            if pressed % 16 == 0 then pause() end
          end
        end
      end
    end
  end
  for index, plate in ipairs(plates) do
    if index % 8 == 0 then pause() end
    local c = plate.centre
    press(c[1], c[2], c[3] - tune.margin)
    for k, m in ipairs(plate.mids or NONE) do
      local q = plate.ring[k]
      press(m[1], m[2], m[3] - tune.margin)
      press((m[1] + q[1]) / 2, (m[2] + q[2]) / 2, m[3] - tune.margin)
    end
    for k, p in ipairs(plate.ring) do
      press(p[1], p[2], p[3] - tune.margin)
      local q = plate.ring[k % #plate.ring + 1]
      press((p[1] + q[1] + c[1]) / 3, (p[2] + q[2] + c[2]) / 3, (p[3] + q[3] + c[3]) / 3 - tune.margin)
    end
  end
  normalCache = {} -- no more press() calls; covers repeatedly shade shared lattice corners
  -- Ground cover lies on the ground as drawn: cut by lattice cell and diagonal, so each piece is
  -- in one ground triangle and exactly parallel to it. The pressed ground keeps it under the
  -- asphalt, so carriageways need not be cut out (that shattered big squares into 24k pieces).
  local function drape(kind, poly, above)
    local box = ringBounds({poly})
    local x0, x1 = math.max(box[1], rect[1]), math.min(box[3], rect[3])
    local y0, y1 = math.max(box[2], rect[2]), math.min(box[4], rect[4])
    if x0 >= x1 or y0 >= y1 then return end
    for gy = floor(y0 / step), math.ceil(y1 / step) - 1 do
      for gx = floor(x0 / step), math.ceil(x1 / step) - 1 do
        local cx, cy = gx * step, gy * step
        local piece = clip(poly, {cx, cy, cx + step, cy + step})
        if #piece >= 3 and math.abs(area2(piece)) > 2e-4 then
          local upper, lower2 = split(piece, cx, cy, cx + step, cy + step, true)
          for _, half in ipairs({upper, lower2}) do
            if #half >= 3 and math.abs(area2(half)) > 2e-4 then
              local out = {}
              for n, q in ipairs(half) do out[n] = {q[1], q[2], ground(q[1], q[2]) + above} end
              scene.polygon(kind, out, true)
            end
          end
        end
      end
      pause()
    end
  end
  -- A big area (a square, a forest): bands of one sweep, aligned to the lattice rows, cut by
  -- column and diagonal. Sweeping the whole polygon alone gave hundreds of long slivers.
  local claims = {}
  local function drapeRings(kind, rings, above)
    local box = ringBounds(rings)
    local x0, x1 = math.max(box[1], rect[1]), math.min(box[3], rect[3])
    local y0, y1 = math.max(box[2], rect[2]), math.min(box[4], rect[4])
    if x0 >= x1 or y0 >= y1 then return end
    -- pieces per ground triangle; the bands of one polygon never overlap, so their areas add up
    local pieces, filled, order = {}, {}, {}
    local full = step * step
    local prep = prepareRings(rings)
    -- row by row: a row's bands split only at the vertices inside it, so most cells of a big
    -- area lie inside one band and are taken whole, without clipping
    for gy = floor(y0 / step), math.ceil(y1 / step) - 1 do
     local ry0, ry1 = math.max(y0, gy * step), math.min(y1, (gy + 1) * step)
     for _, band in ipairs(triangulate(prep, nil, {x0, ry0, x1, ry1}, true)) do
      local bx0 = math.max(x0, math.min(band[1][1], band[4][1]))
      local bx1 = math.min(x1, math.max(band[2][1], band[3][1]))
      local inX0, inX1 = math.max(band[1][1], band[4][1]), math.min(band[2][1], band[3][1])
      local tall = math.abs(band[1][2] - gy * step) < 1e-6 and math.abs(band[4][2] - (gy + 1) * step) < 1e-6
      for gx = floor(bx0 / step), math.ceil(bx1 / step) - 1 do
        local cx, cy = gx * step, gy * step
        local key0 = ((gx + 32768) * 65536 + gy + 32768) * 2
        if tall and cx >= inX0 - 1e-6 and cx + step <= inX1 + 1e-6 then
          for key = key0, key0 + 1 do
            if not filled[key] then pieces[key], filled[key], order[#order + 1] = {}, 0, key end
            filled[key] = filled[key] + full
          end
        else
        local piece = cleanRing(clip(band, {cx, cy, cx + step, cy + step}))
        if #piece >= 3 and math.abs(area2(piece)) > 2e-4 then
          for _, half in ipairs({split(piece, cx, cy, cx + step, cy + step, true)}) do
            local twice = math.abs(area2(half))
            if #half >= 3 and twice > 2e-4 then
              local sx, sy = 0, 0
              for _, q in ipairs(half) do sx, sy = sx + q[1], sy + q[2] end
              local key = ((gx + 32768) * 65536 + gy + 32768) * 2 + ((sx - cx * #half) >= (sy - cy * #half) and 0 or 1)
              local list = pieces[key]
              if not list then list = {}; pieces[key], filled[key], order[#order + 1] = list, 0, key end
              list[#list + 1], filled[key] = half, filled[key] + twice
            end
          end
        end
        end
      end
     end
     pause()
    end
    local rank = CLAIM[kind]
    for _, key in ipairs(order) do
      if rank and filled[key] > full - 1e-2 then
        -- the whole ground triangle: drawn in this material instead of grass
        local held = claims[key]
        if not held or CLAIM[held] > rank then claims[key] = kind end
      else
        for _, half in ipairs(pieces[key]) do
          local out = {}
          local cx, cy = 0, 0
          for n, q in ipairs(half) do
            out[n] = {q[1], q[2], ground(q[1], q[2]) + above}
            if kind ~= 'water' then out[n][6], out[n][7], out[n][8] = groundNormal(q[1], q[2]) end
            cx, cy = cx + q[1], cy + q[2]
          end
          scene.polygon(surfaceKind(cx / #half, cy / #half, kind), out, true)
        end
      end
    end
    pause()
  end
  -- Far and horizon tiles draw no carriageway, so a verge there is ground over ground: in a
  -- city it was 83% of a far tile's triangles and ~90% of a horizon block's. Every
  -- ProceduralMesh triangle is static collision the engine rebuilds on each
  -- be:reloadCollision (night-probe-11: far 97 ms and horizon 182 ms of 356 ms in Kyiv).
  -- A far tile keeps the verges along its edge, where they meet the near tile's ground.
  local inner = {rect[1] + 30, rect[2] + 30, rect[3] - 30, rect[4] - 30}
  local function vergeWanted(box)
    if not boundsTouch(rect, box, 0) then return false end
    if not distant then return true end
    return not options.horizon and not (box[1] >= inner[1] and box[2] >= inner[2] and box[3] <= inner[3] and box[4] <= inner[4])
  end
  for _, plate in ipairs(plates) do
    for _, quad in ipairs(plate.verges or NONE) do
      if vergeWanted(ringBounds({quad})) then
        local outerA = {quad[3][1], quad[3][2], ground(quad[3][1], quad[3][2])}
        local outerB = {quad[4][1], quad[4][2], ground(quad[4][1], quad[4][2])}
        outerA[9], outerB[9] = 1, 1
        emit(distant and scene or roads, vergeKind, {quad[1], quad[2], outerA, outerB}, nil, true)
      end
    end
  end
  -- Edge decals over a carriageway's edge where it has no sidewalk: grass creeping onto the
  -- asphalt, or a dirt shoulder along main roads (and wherever the look's verge is bare).
  -- Graded roads are dirt already. Decoration only: no collision (collision.lua QUIET).
  local edgesOn = visualRoads and decalsPresent()
  local function edgeKind(strip)
    if not edgesOn or strip.grade > 1 or strip.tags.service == 'parking_aisle' then return nil end
    if vergeChoice == 'dirt' or vergeChoice == 'gravel' or vergeChoice == 'dry' then return 'edge_dirt' end
    -- no grass creeping onto the asphalt where the verge is desert, dry grass, turf or snow
    local first = strip.points[1]
    if bio.on and first and surfaceKind(first[1], first[2], 'ground') ~= 'ground' then return 'edge_dirt' end
    return DECAL.dirtRoads[((strip.tags.highway or ''):gsub('_link$', ''))] and 'edge_dirt' or 'edge_grass'
  end
  -- The decal lies edgeLift over the road and over the verge as drawn: a point `metres` past
  -- the road's edge (negative: over the asphalt) on the line from the verge's inner corner a to
  -- its outer corner o, which is tune.shoulder away.
  local function edgePoint(a, o, metres, lift, v)
    local t = metres / tune.shoulder
    local z = metres > 0 and a[3] + (o[3] - a[3]) * t or a[3] + tune.vergeSink
    return {a[1] + (o[1] - a[1]) * t, a[2] + (o[2] - a[2]) * t, z + lift, DECAL.edgeAt + metres / DECAL.edgeWidth, v}
  end
  local function emitEdge(kind, strip, item)
    local verge, k = item[1], item.k
    local inside = math.min(DECAL.edgeIn, strip.hw * .25)
    local out = math.min(DECAL.edgeWidth * (1 - DECAL.edgeAt), tune.shoulder)
    local v0 = strip.dist[k] / DECAL.edgeRepeat % 1
    local v1 = v0 + (strip.dist[k + 1] - strip.dist[k]) / DECAL.edgeRepeat
    local a, o, b, p = verge[1], verge[2], verge[4], verge[3]   -- inner and outer corners at k, k + 1
    local low, high = DECAL.edgeLift[1], DECAL.edgeLift[2]
    emit(roadDecor, kind, {edgePoint(a, o, -inside, low, v0), edgePoint(a, o, 0, low, v0),
      edgePoint(b, p, 0, low, v1), edgePoint(b, p, -inside, low, v1)}, item[2], 'flat')
    emit(roadDecor, kind, {edgePoint(a, o, 0, low, v0), edgePoint(a, o, out, high, v0),
      edgePoint(b, p, out, high, v1), edgePoint(b, p, 0, low, v1)}, item[2], true)
  end
  local edgeOps = 0
  for _, strip in ipairs(strips) do
    local kind = edgeKind(strip)
    for _, item in ipairs(strip.verges or NONE) do
      local verge = item[1]
      if not distant or vergeWanted(ringBounds({verge})) then
        verge[2][3], verge[3][3] = ground(verge[2][1], verge[2][2]), ground(verge[3][1], verge[3][2])
        -- [9] marks the outer edge. The clip resamples it from ground() so both tiles agree.
        verge[2][9], verge[3][9] = 1, 1
        local groundMesh = distant and scene or roads
        if tune.vergeCut > 0 then emit(groundMesh, vergeKind, verge, item[2], true)
        elseif visualRoads then roads.polygon(vergeKind, verge, true)
        elseif distant then scene.polygon(vergeKind, verge, true) end
        if kind and item.edge then
          emitEdge(kind, strip, item)
          edgeOps = edgeOps + 1
          if edgeOps % 64 == 0 then pause() end
        end
      end
    end
  end

  mark('verges')
  if visualRoads and markKind then
    -- along the strips, so the paint stops at a junction's mouth instead of crossing its fan;
    -- the dash phase keeps the source distance (the strip starts its cut into the road)
    for _, strip in ipairs(strips) do
      local road = strip.road
      local points, tags, width = strip.points, strip.tags, math.max(.5, math.min(80, road.width or 7))
      local marks = ROADS.marks(tags, width, strip.grade)
      local distance = (cutsOf[road] or NONE)[1] or 0
      for index = 1, #points - 1 do
        local a, b = points[index], points[index + 1]
        local dx, dy = b[1] - a[1], b[2] - a[2]
        local length = math.sqrt(dx * dx + dy * dy)
        if length > EPS then
          if boundsTouch(rect, {math.min(a[1], b[1]), math.min(a[2], b[2]), math.max(a[1], b[1]), math.max(a[2], b[2])}, width / 2) then
            local nx, ny = -dy / length, dx / length
            local function span(mark, start, finish)
              if finish - start <= EPS then return end
              local p, q = lerp(a, b, (start - distance) / length), lerp(a, b, (finish - distance) / length)
              local half = mark.width * DECAL.markSpread / 2
              local left, right = mark.offset - half, mark.offset + half
              -- the worn paint runs on along the road: v from the source distance
              local v0 = start / DECAL.markRepeat % 1
              local v1 = v0 + (finish - start) / DECAL.markRepeat
              local zp, zq = (p[3] or 0) + lift + DECAL.markLift, (q[3] or 0) + lift + DECAL.markLift
              roadDecor.polygon(markKind, {{p[1] + nx * left, p[2] + ny * left, zp, 0, v0},
                {p[1] + nx * right, p[2] + ny * right, zp, 1, v0},
                {q[1] + nx * right, q[2] + ny * right, zq, 1, v1},
                {q[1] + nx * left, q[2] + ny * left, zq, 0, v1}}, 'flat')
            end
            for _, mark in ipairs(marks) do
              if mark.dashed then
                for start = math.floor(distance / 12) * 12, distance + length, 12 do span(mark, math.max(distance, start), math.min(distance + length, start + 3)) end
              else span(mark, distance, distance + length) end
            end
          end
          distance = distance + length
        end
        if index % 32 == 0 then pause() end
      end
      pause()
    end
  end

  if visualRoads and not distant and options.experimentalDetail and coversPresent() then
    ROADS.covers(strips, rect, lift, roadDecor, pause, patchesPresent())
  end
  if visualRoads and not distant then
    ROADS.aprons({roads = lists.roads, rect = rect, lift = lift, pause = pause,
      polygon = function(material, poly, up) roads.polygon(material, poly, up) end})
  end
  for _, area in ipairs(visualRoads and not distant and lists.areas or NONE) do
    if area.kind == 'island' then
      ROADS.island({roads = lists.roads, rect = rect, lift = lift, pause = pause,
        polygon = function(material, poly, up) roads.polygon(material, poly, up) end}, area)
    end
  end
  if visualRoads and not distant then
    GORE.paint({roads = lists.roads, rect = rect, lift = lift, markZ = lift + DECAL.markLift, pause = pause,
      material = roadMaterial,
      surface = function(material, poly) roads.polygon(material, poly, 'flat') end,
      mark = function(poly) if markKind then roadDecor.polygon(markKind, poly, 'flat') end end})
  end
  if visualRoads and markKind and not distant then
    DETAIL.paint({roads = lists.roads, points = lists.points, stars = stars, cutsOf = cutsOf, rect = rect,
      kinds = DETAIL.kinds, z = lift + DECAL.markLift,
      emit = function(poly) roadDecor.polygon(markKind, poly, 'flat') end, pause = pause})
  end
  mark('marks')
  -- OSM has no sea polygons (only coastlines); the DEM's sea is flat at the region's seaLevel
  -- (0 m plus the world lift). Open water is a plane just above it over every ground quad that
  -- reaches it; higher ground covers the plane on the shore. Lakes and rivers are OSM areas.
  local sea = type(options.seaLevel) == 'number' and options.seaLevel + SEA_ABOVE or nil
  -- Death Valley's floor lies 86 m under the sea, and the plane flooded it: a tile far inland
  -- (land on the climate grid ~3 km round its corners and centre) has no sea at all
  if sea and bio.on and VEG.biome.inland then
    local dry = true
    for _, q in ipairs({{.5, .5}, {0, 0}, {1, 0}, {0, 1}, {1, 1}}) do
      if not VEG.biome.inland(options.geo, rect[1] + q[1] * size, rect[2] + q[2] * size) then dry = false; break end
    end
    if dry then sea = nil end
  end
  local seaStep = distant and size / 5 or size / count
  local seaCount = math.max(1, math.floor(size / seaStep + .5))
  local seaQuads, seaAll = {}, true
  for gy = 0, sea and seaCount - 1 or -1 do
    for gx = 0, seaCount - 1 do
      local x0, y0 = rect[1] + size * gx / seaCount, rect[2] + size * gy / seaCount
      local x1, y1 = rect[1] + size * (gx + 1) / seaCount, rect[2] + size * (gy + 1) / seaCount
      if math.min(rawHeight(x0, y0), rawHeight(x1, y0), rawHeight(x0, y1), rawHeight(x1, y1)) < sea then
        seaQuads[#seaQuads + 1] = {x0, y0, x1, y1}
      else
        seaAll = false
      end
    end
    pause()
  end
  if sea and seaAll then seaQuads = {rect} end
  for _, q in ipairs(seaQuads) do
    scene.polygon('water', {{q[1], q[2], sea}, {q[3], q[2], sea}, {q[3], q[4], sea}, {q[1], q[4], sea}}, 'flat')
  end
  mark('groundsea')
  for _, area in ipairs(distant and NONE or lists.areas) do
    local kind = area.kind
    if CLAIM[kind] and not (((area.tags or NONE).source or ''):find('worldcover', 1, true)) and ringsTouch(area.rings, rect) then
      drapeRings(kind, area.rings, .025)
    end
    pause()
  end
  -- Height of the drawn surface, or nil outside every DEM grid. No grids at all stays the
  -- numeric ground (flat near tiles). A sample just outside a grid is nil so the normal
  -- there is one-sided instead of a slope down to the old z = 0 fallback.
  local function vertex(x, y, z)
    local p = {x, y, z}
    p[6], p[7], p[8] = groundNormal(x, y)
    return p
  end
  -- The ground lattice: each cell two triangles along its (x0, y0)-(x1, y1) diagonal, drawn in
  -- the material of the cover that fills it whole (claims), else as grass.
  for gy = 0, distant and -1 or count - 1 do
    for gx = 0, count - 1 do
      local cx, cy = n0x + 1 + gx, n0y + 1 + gy
      local x0, y0 = cx * step, cy * step
      local x1, y1 = x0 + step, y0 + step
      local a, b = vertex(x0, y0, ground(x0, y0)), vertex(x1, y0, ground(x1, y0))
      local c, d = vertex(x1, y1, ground(x1, y1)), vertex(x0, y1, ground(x0, y1))
      local gkey = ((cx + 32768) * 65536 + cy + 32768) * 2
      local tx, ty = (x0+x1+x1)/3, (y0+y0+y1)/3
      roads.polygon(surfaceKind(tx, ty, claims[gkey] or backgroundKind(tx, ty)), {a, b, c}, true)
      tx, ty = (x0+x1+x0)/3, (y0+y1+y1)/3
      roads.polygon(surfaceKind(tx, ty, claims[gkey + 1] or backgroundKind(tx, ty)), {a, c, d}, true)
    end
    pause()
  end
  local function manifest(collector, layer)
    local mats, total = {}, 0
    for material in pairs(collector.used) do mats[#mats + 1] = material end
    table.sort(mats)
    for _, item in ipairs(collector.items) do total = total + (item.triangles or 0) end
    local warm = VEG.warm(LAMP, BUS_STOP)
    return {version = 1, generator = 'earthng-lua-v1', source = options.regionId, layer = layer,
      tile = {i, j}, rect = rect, materials = options.materials or '/earthng/planet/materials.json',
      items = collector.items, mats = mats, triangles = total, packs = options.packs,
      warmShapes = warm, stockMaterials = VEG.stockFor(collector.items, warm), yard = collector.yard}
  end
  -- No road: the car stands on the ground at the landing (native.lua's off-road landing). The
  -- gentlest ground within ~80 m of it, the car across the slope: on Everest's summit ridge it
  -- rolled off the point itself.
  local function groundSpawn()
    local best, bestScore
    for dy = -80, 80, 10 do
      for dx = -80, 80, 10 do
        local x, y = target[1] + dx, target[2] + dy
        local d = math.sqrt(dx * dx + dy * dy)
        if d <= 80 and heightAt(x, y) and coverAt(x, y) ~= 'water' then
          local nx, ny, nz = groundNormal(x, y)
          local score = nz - d / 4000
          if not bestScore or score > bestScore then best, bestScore = {x, y, nx, ny}, score end
        end
      end
    end
    if not best then return {pos = {target[1], target[2], ground(target[1], target[2]) + ROAD_LIFT}, yaw = 0} end
    local x, y = best[1], best[2]
    -- along the contour (-ny, nx), as a road spawn's yaw = atan2(-dx, dy) of its direction
    local yaw = (math.abs(best[3]) + math.abs(best[4]) > 1e-3) and math.atan2(best[4], best[3]) or 0
    return {pos = {x, y, ground(x, y) + ROAD_LIFT}, yaw = yaw}
  end
  -- Nothing writes the road layer past this point. options.roadReady(road, nav) (native.lua,
  -- while driving) takes it now, and the scene is built when the coroutine is resumed again:
  -- the scene is ~3/4 of a near tile (central Kyiv: 230 of 820 ms is the road), and at 300 km/h
  -- the road ahead could not wait for the buildings of the tiles beside it.
  local roadManifest
  local function finishRoad()
    roads.finish()
    roadDecor.finish()
    for _, item in ipairs(roadDecor.items) do item.decor = true; roads.items[#roads.items + 1] = item end
    for material in pairs(roadDecor.used) do roads.used[material] = true end
    roadManifest = manifest(roads, 'road')
    roadManifest.spawn = bestSpawn or groundSpawn()
    roadManifest.drivable = bestSpawn ~= nil
  end
  if options.roadReady and not distant then
    finishRoad()
    options.roadReady(roadManifest, nav)
  end
  -- Distant ground is render-only and lives in the far/horizon manifest. The tile border is
  -- sampled at the near step so it shares that edge; the interior is the coarse step. A fan
  -- joins them. Corners belong to one fan, so two strips never cover the same quad.
  if distant and #terrain > 0 then
    local fine = step
    local coarse = options.horizon and (options.horizonStep or options.farStep or 100) or (options.farStep or 100)
    coarse = fine * math.max(1, math.floor(coarse / fine + 1e-6))
    if size < coarse * 2 - EPS then coarse = fine end
    local x0, y0, x1, y1 = rect[1], rect[2], rect[3], rect[4]
    local function emitTri(a, b, c)
      if not a or not b or not c then return end
      if farRoads then farTris[#farTris + 1] = {a, b, c} end
      scene.triangle(surfaceKind((a[1]+b[1]+c[1])/3, (a[2]+b[2]+c[2])/3), a, b, c, true)
    end
    local function at(x, y)
      local z = heightAt(x, y)
      if not z then return nil end
      return vertex(x, y, z)
    end
    local ix0, iy0, ix1, iy1 = x0 + coarse, y0 + coarse, x1 - coarse, y1 - coarse
    if ix1 > ix0 + EPS and iy1 > iy0 + EPS then
      local function ticks(a, b, stride)
        local out, v = {}, a
        while v < b - EPS do out[#out + 1] = v; v = v + stride end
        out[#out + 1] = b
        return out
      end
      local xs, ys = ticks(ix0, ix1, coarse), ticks(iy0, iy1, coarse)
      for gy = 1, #ys - 1 do
        for gx = 1, #xs - 1 do
          local ax, ay = xs[gx], ys[gy]
          local bx, by = xs[gx + 1], ys[gy + 1]
          emitTri(at(ax, ay), at(bx, ay), at(bx, by))
          emitTri(at(ax, ay), at(bx, by), at(ax, by))
        end
        pause()
      end
    end
    local function pointsAlong(ax, ay, bx, by, n)
      local out = {}
      for k = 0, n do
        local t = k / math.max(n, 1)
        out[#out + 1] = {ax + (bx - ax) * t, ay + (by - ay) * t}
      end
      return out
    end
    -- Outer fine polyline P and inner coarse knots. P[0] matches the first knot's
    -- parameter, P[n] the last. Triangles (L, P[i], P[i+1]) plus (L, P[n], R).
    local function fan(outer, inner)
      local ia = 1
      for k = 1, #inner - 1 do
        local L, R = inner[k], inner[k + 1]
        local ib = ia
        while ib < #outer do
          ib = ib + 1
          local p = outer[ib]
          if math.abs(p[1] - R[1]) <= EPS and math.abs(p[2] - R[2]) <= EPS then break end
          -- R is inset, so the outer end shares R's along-edge coordinate, not its position.
          local along = math.abs(R[1] - L[1]) >= math.abs(R[2] - L[2])
          local target = along and R[1] or R[2]
          local got = along and p[1] or p[2]
          if math.abs(got - target) <= EPS then break end
        end
        for n = ia, ib - 1 do
          emitTri(at(L[1], L[2]), at(outer[n][1], outer[n][2]), at(outer[n + 1][1], outer[n + 1][2]))
        end
        local p = outer[ib]
        if math.abs(p[1] - R[1]) > EPS or math.abs(p[2] - R[2]) > EPS then
          emitTri(at(L[1], L[2]), at(p[1], p[2]), at(R[1], R[2]))
        end
        ia = ib
      end
    end
    local function fanPoint(outer, x, y)
      for n = 1, #outer - 1 do
        emitTri(at(x, y), at(outer[n][1], outer[n][2]), at(outer[n + 1][1], outer[n + 1][2]))
      end
    end
    local nFine = math.floor(coarse / fine + .5)
    local span = (x1 - x0) - 2 * coarse
    local nSpanFine = math.floor(span / fine + .5)
    local nSpanCoarse = math.floor(span / coarse + .5)
    if span > EPS then
      fan(pointsAlong(x0 + coarse, y0, x1 - coarse, y0, nSpanFine),
        pointsAlong(x0 + coarse, y0 + coarse, x1 - coarse, y0 + coarse, nSpanCoarse))
      fan(pointsAlong(x0 + coarse, y1, x1 - coarse, y1, nSpanFine),
        pointsAlong(x0 + coarse, y1 - coarse, x1 - coarse, y1 - coarse, nSpanCoarse))
      fan(pointsAlong(x0, y0 + coarse, x0, y1 - coarse, nSpanFine),
        pointsAlong(x0 + coarse, y0 + coarse, x0 + coarse, y1 - coarse, nSpanCoarse))
      fan(pointsAlong(x1, y0 + coarse, x1, y1 - coarse, nSpanFine),
        pointsAlong(x1 - coarse, y0 + coarse, x1 - coarse, y1 - coarse, nSpanCoarse))
    end
    local function corner(outer, x, y) fanPoint(outer, x, y) end
    corner(pointsAlong(x0, y0 + coarse, x0, y0, nFine), x0 + coarse, y0 + coarse)
    -- continue the L from the SW corner of the tile to the south inset
    fanPoint(pointsAlong(x0, y0, x0 + coarse, y0, nFine), x0 + coarse, y0 + coarse)
    fanPoint(pointsAlong(x1, y0 + coarse, x1, y0, nFine), x1 - coarse, y0 + coarse)
    fanPoint(pointsAlong(x1, y0, x1 - coarse, y0, nFine), x1 - coarse, y0 + coarse)
    fanPoint(pointsAlong(x0, y1 - coarse, x0, y1, nFine), x0 + coarse, y1 - coarse)
    fanPoint(pointsAlong(x0, y1, x0 + coarse, y1, nFine), x0 + coarse, y1 - coarse)
    fanPoint(pointsAlong(x1, y1 - coarse, x1, y1, nFine), x1 - coarse, y1 - coarse)
    fanPoint(pointsAlong(x1, y1, x1 - coarse, y1, nFine), x1 - coarse, y1 - coarse)
    -- Skirt only where the next sample really has no DEM. A shared tile edge whose
    -- neighbour grid is loaded is left open; the skirt does not hide a wrong height.
    local function skirtEdge(p, q, outwardX, outwardY)
      local ux, uy = q[1] - p[1], q[2] - p[2]
      if -uy * outwardX + ux * outwardY < 0 then p, q = q, p end
      local drop = 24
      local pb, qb = {p[1], p[2], p[3] - drop}, {q[1], q[2], q[3] - drop}
      scene.triangle('ground', p, q, qb, false)
      scene.triangle('ground', p, qb, pb, false)
    end
    local n = math.floor(size / fine + .5)
    local function gridZ(ix, iy) return heightAt(x0 + ix * fine, y0 + iy * fine) end
    for iy = 0, n do
      for ix = 0, n do
        if ix < n then
          local z0, z1 = gridZ(ix, iy), gridZ(ix + 1, iy)
          if z0 and z1 then
            local function side(dir)
              local a, b = gridZ(ix, iy + dir), gridZ(ix + 1, iy + dir)
              return a ~= nil and b ~= nil
            end
            local south, north = side(-1), side(1)
            if south ~= north then
              skirtEdge({x0 + ix * fine, y0 + iy * fine, z0}, {x0 + (ix + 1) * fine, y0 + iy * fine, z1},
                0, south and 1 or -1)
            end
          end
        end
        if iy < n then
          local z0, z1 = gridZ(ix, iy), gridZ(ix, iy + 1)
          if z0 and z1 then
            local function side(dir)
              local a, b = gridZ(ix + dir, iy), gridZ(ix + dir, iy + 1)
              return a ~= nil and b ~= nil
            end
            local west, east = side(-1), side(1)
            if west ~= east then
              skirtEdge({x0 + ix * fine, y0 + iy * fine, z0}, {x0 + ix * fine, y0 + (iy + 1) * fine, z1},
                west and 1 or -1, 0)
            end
          end
        end
      end
      if iy % 4 == 3 then pause() end
    end
    -- A vista block's edge runs at 100 m, the 5 km horizon's beside it at 25 m: a ridge between
    -- two of its knots showed the sky through the seam. Every edge hangs a skirt in the ground's
    -- own material, facing out of the block.
    if options.vista then
      for _, e in ipairs({{x0, y0, x1, y0, 0, -1}, {x1, y0, x1, y1, 1, 0}, {x1, y1, x0, y1, 0, 1}, {x0, y1, x0, y0, -1, 0}}) do
        local m = math.floor(math.max(math.abs(e[3] - e[1]), math.abs(e[4] - e[2])) / fine + .5)
        for k = 0, m - 1 do
          local ax, ay = e[1] + (e[3] - e[1]) * k / m, e[2] + (e[4] - e[2]) * k / m
          local bx, by = e[1] + (e[3] - e[1]) * (k + 1) / m, e[2] + (e[4] - e[2]) * (k + 1) / m
          local za, zb = heightAt(ax, ay), heightAt(bx, by)
          if za and zb then
            local p, q = {ax, ay, za}, {bx, by, zb}
            if -(by - ay) * e[5] + (bx - ax) * e[6] < 0 then p, q = q, p end
            local kind = surfaceKind((ax + bx) / 2, (ay + by) / 2)
            scene.triangle(kind, p, q, {q[1], q[2], q[3] - 60}, false)
            scene.triangle(kind, p, {q[1], q[2], q[3] - 60}, {p[1], p[2], p[3] - 60}, false)
          end
        end
        pause()
      end
    end
  end
  mark('areas')
  local shopLinks = decor and options.experimentalShopfront and not options.far and BLD.shopLinks(lists, options, pause) or nil
  for _, building in ipairs(decor and lists.buildings or NONE) do
    local rings, tags = building.rings or {}, building.tags or {}
    local exterior = cleanRing(rings[1])
    if #exterior >= 3 and ringsTouch(rings, rect) then
      local footprint, h = math.abs(area2(exterior)) / 2, hash(tostring(building.id or ''))
      -- Buildings can cross source-cell boundaries. Their full exported footprint Z
      -- gives both tiles the same datum even when the centroid's DEM cell is absent.
      local sourceLow, sourceSum, sourceCount = math.huge, 0, 0
      for _, p in ipairs(exterior) do
        if p[3] then sourceLow, sourceSum, sourceCount = math.min(sourceLow, p[3]), sourceSum + p[3], sourceCount + 1 end
      end
      if options.far then
        local box = ringBounds(rings)
        rings = {{{box[1], box[2]}, {box[3], box[2]}, {box[3], box[4]}, {box[1], box[4]}}}
        exterior = rings[1]
      end
      local low, cx, cy = math.huge, 0, 0
      for _, p in ipairs(exterior) do low, cx, cy = math.min(low, ground(p[1], p[2])), cx + p[1], cy + p[2] end
      local base = sourceCount > 0 and sourceSum / sourceCount or ground(cx / #exterior, cy / #exterior)
      if sourceCount > 0 then low = sourceLow end
      local height = math.max(2.2, math.min(850, BLD.height(building, tags, footprint, h)))
      local lifted = (building.minHeight or number(tags.min_height, 0)) > 0
      local bottom = lifted and base + (building.minHeight or number(tags.min_height, 0)) or low - .3
      local top, kind = base + height, wallMaterial(building, look, height)
      -- Storefront spans (BLD.shopLinks). A lifted block and a wall lower than the band keep
      -- their walls; a small shop the look dresses as a house takes plain walls under the band.
      local shopWalls, shopBand, shopNote = shopLinks and shopLinks[building.id], nil, nil
      if shopWalls then
        shopBand = math.min(BLD.SHOP.band, height - .4)
        shopNote = lifted and 'building_lifted' or shopBand < BLD.SHOP.minBand and 'building_low' or nil
        if not shopNote and kind:find('hw_', 1, true) == 1 then
          kind, shopNote = BLD.SHOP.hosts[h % #BLD.SHOP.hosts + 1], 'house_walls_replaced'
        end
        if type(options.poiReport) == 'table' then
          options.poiReport[#options.poiReport + 1] = {evidence = 'draw', building = tostring(building.id),
            decision = (shopNote == 'building_lifted' or shopNote == 'building_low') and 'rejected' or 'drawn',
            reason = shopNote, band = shopBand, tile = key}
        end
        if shopNote == 'building_lifted' or shopNote == 'building_low' then shopWalls = nil end
      end
      -- A plinth under low brick and plaster walls (the photo panels have their own); garage
      -- doors along a row's long walls, or a single garage's short ones.
      local plinth = not lifted and height <= 13 and (kind:find('wall_brk_', 1, true) == 1 or kind:find('wall_pls_', 1, true) == 1)
      -- a house (BLD.house): its plinth colour, windows, door, gables and roof guesses
      local dress = kind:find('hw_', 1, true) == 1 and BLD.dress(kind, h) or nil
      if dress then plinth = not lifted and dress.plinth end
      -- Grammar v0, near tiles at Balanced and above: cornice, porch, one balcony, chimney.
      if dress and not options.far and BLD.mass(options.detail) then
        dress.mass = true
        dress.balcony = height >= BLD.floor * 2 - .2 and h % 4 == 1
      end
      local plinthKind = type(plinth) == 'string' and plinth or 'plinth'
      local use = tags.building
      -- City grammar, near tiles at Balanced and above. Houses stay on dress.mass.
      -- Flat roofs gain a parapet and a crown; street facades and the long yard side gain canopies.
      BLD.city, BLD.face, BLD.faces = nil, nil, nil
      BLD.city = (not dress and not options.far and not lifted and BLD.mass(options.detail) and BLD.block(use, height)) or nil
      if BLD.city then BLD.faces = {} end
      local doors = (use == 'garage' or use == 'garages') and (h % 3 == 0 and 'door_rust' or 'door_garage')
      local detailed = options.experimentalDetail and BLD.city and not options.far
      BLD.report = type(options.detailReport) == 'table' and options.detailReport or nil
      local acRoom = BLD.DETAIL.acMax
      for _, raw in ipairs(rings) do
        local ring, along = cleanRing(raw), 0
        local signed = 0
        for k, p in ipairs(ring) do local q = ring[k % #ring + 1]; signed = signed + p[1] * q[2] - q[1] * p[2] end
        -- Outer walls face away from CCW rings; courtyard walls face into clockwise rings.
        local reverse = (raw == rings[1] and signed < 0) or (raw ~= rings[1] and signed > 0)
        if reverse then local reversed = {}; for k = #ring, 1, -1 do reversed[#reversed + 1] = ring[k] end; ring = reversed end
        -- a house's door goes on its longest outer wall
        local doorWall = 0
        if dress and raw == rings[1] and not options.far then
          for k, a in ipairs(ring) do
            local b = ring[k % #ring + 1]
            doorWall = math.max(doorWall, (b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2)
          end
        end
        for k, a in ipairs(ring) do
          local b = ring[k % #ring + 1]
          local length = math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2)
          local wallKind = kind
          if length < 16 and (kind:find('wall_pnl_', 1, true) == 1 or kind:find('wall_lgg_', 1, true) == 1 or kind:find('wall_brk_', 1, true) == 1) then wallKind = kind .. '_end' end
          local door = doors and ((use == 'garages' and length >= 8) or (use == 'garage' and length <= 4.5))
          local scale = facadeScale(wallKind)
          local seam = plinth and math.min(top, math.max(bottom, base + BLD.plinth)) or bottom
          if seam > bottom then
            scene.polygon(plinthKind, {{a[1], a[2], bottom, along / 3, (bottom - base) / 3},
              {b[1], b[2], bottom, (along + length) / 3, (bottom - base) / 3},
              {b[1], b[2], seam, (along + length) / 3, (seam - base) / 3},
              {a[1], a[2], seam, along / 3, (seam - base) / 3}}, false)
          end
          -- a storefront splits the wall's lower band along the wall: shop spans, the wall
          -- between them, one wall above (the same UV as unsplit)
          local spans = shopWalls and raw == rings[1] and length > EPS and shopWalls[BLD.wallKey(a, b)]
          local upper = spans and base + shopBand > seam and base + shopBand or seam
          if upper > seam then
            -- the shop texture's street level is v = 0 and its design 4.2 m high: below the datum
            -- it stretches a little, under a lower band it is squeezed to fit
            local function piece(material, s0, s1, sc, shop)
              local p0 = {a[1] + (b[1] - a[1]) * s0 / length, a[2] + (b[2] - a[2]) * s0 / length}
              local p1 = {a[1] + (b[1] - a[1]) * s1 / length, a[2] + (b[2] - a[2]) * s1 / length}
              local squeeze = shop and BLD.SHOP.band / shopBand or 1
              local v0 = shop and math.max(0, seam - base) * squeeze / sc or (seam - base) / sc
              local v1 = (upper - base) * squeeze / sc
              scene.polygon(material, {{p0[1], p0[2], seam, (along + s0) / sc, v0},
                {p1[1], p1[2], seam, (along + s1) / sc, v0},
                {p1[1], p1[2], upper, (along + s1) / sc, v1},
                {p0[1], p0[2], upper, (along + s0) / sc, v1}}, false)
            end
            local at = 0
            for _, span in ipairs(spans) do
              if span[1] > at then piece(wallKind, at, span[1], scale) end
              piece(span[3], span[1], span[2], 6, true)
              at = span[2]
            end
            if at < length then piece(wallKind, at, length, scale) end
          end
          scene.polygon(wallKind, {{a[1], a[2], upper, along / scale, (upper - base) / scale},
            {b[1], b[2], upper, (along + length) / scale, (upper - base) / scale},
            {b[1], b[2], top, (along + length) / scale, height / scale},
            {a[1], a[2], top, along / scale, height / scale}}, false)
          if door and length > EPS then
            -- one door a bay, 2 cm out from the cement: a row of doors between piers, not one
            -- shutter along the whole row (bld-garages-03)
            local d = BLD.door
            local bays = math.max(1, math.floor((length + .3) / d.bay))
            local width = math.min(d.width, length / bays - .4)
            local dx, dy = (b[1] - a[1]) / length, (b[2] - a[2]) / length
            local ox, oy = dy * d.out, -dx * d.out        -- outward: the ring runs with the wall's inside on its left
            local z0, z1 = math.min(seam, base), base + d.height
            for n = 0, bays - 1 do
              local s0 = (n + .5) * length / bays - width / 2
              local s1 = s0 + width
              scene.polygon(doors, {{a[1] + dx * s0 + ox, a[2] + dy * s0 + oy, z0, 0, (z0 - base) / d.height},
                {a[1] + dx * s1 + ox, a[2] + dy * s1 + oy, z0, 1, (z0 - base) / d.height},
                {a[1] + dx * s1 + ox, a[2] + dy * s1 + oy, z1, 1, 1},
                {a[1] + dx * s0 + ox, a[2] + dy * s0 + oy, z1, 0, 1}}, false)
            end
          end
          if detailed and raw == rings[1] then
            acRoom = acRoom - BLD.acUnits(scene, a, b, length, along, base, height, wallKind, h, spans, acRoom)
            BLD.windowExtras(scene, a, b, length, along, base, height, wallKind, h, spans)
            BLD.balconies(scene, a, b, length, along, base, height, wallKind, h, spans)
          end
          if dress and dress.mass and length > .4 then BLD.cornice(scene, a, b, length, top) end
          if BLD.city and raw == rings[1] and length > 6 and not plinth then BLD.socle(scene, a, b, length, bottom, base) end
          if BLD.city and raw == rings[1] and length >= 6 then
            BLD.probe = wallPoint(a, b, length, length * .5, 8, 0, 0, 0)
            BLD.onroad = BLD.street(segmentBins, BLD.probe[1], BLD.probe[2], 18)
            BLD.faces[#BLD.faces + 1] = {a, b, len = length, z = base, road = BLD.onroad and true or false}
          end
          if doorWall > 0 then
            local isDoor = length * length >= doorWall - 1e-6
            BLD.openings(scene, a, b, length, base, height, dress, isDoor, options.detail)
            if dress.mass and isDoor then BLD.porch(scene, a, b, length, base, dress, options.detail) end
            if dress.balcony and not isDoor and length >= 5 then BLD.balcony(scene, a, b, length, base, h); dress.balcony = false end
            if isDoor then doorWall = math.huge end
          end
          along = along + length
          if k % 32 == 0 then pause() end
        end
      end
      if detailed then BLD.downpipes(scene, rings, base, top, height, kind) end
      if options.experimentalDetail and not options.far and not lifted then
        BLD.addressPlate(scene, rings, tags, base, height, lists.roads)
      end
      if options.far or not pitchedRoof(scene, rings, tags, top, base, kind, height, BLD.roof(tags, h, postsoviet), dress) then
        for _, tri in ipairs(triangulate(rings, pause, rect)) do
          for _, p in ipairs(tri) do p[3] = top end
          scene.polygon('roof', tri, true)
        end
        if BLD.city then
          BLD.parapets(scene, rings, top, height, h)
          BLD.crown(scene, rings, top, height, h, footprint)
          if detailed then BLD.roofClutter(scene, rings, top, height, h) end
        end
      elseif dress and dress.mass then
        BLD.chimney(scene, rings[1], top, dress, h, tags)
      end
      if BLD.city then BLD.canopies(scene, h, height) end
      BLD.city, BLD.face, BLD.faces = nil, nil, nil
    end
    pause()
  end
  mark('buildings')
  -- A fence or wall as a thin box that follows the drawn ground: a knot every fenceStep metres
  -- (one quad per OSM segment, its ends alone on the ground, sank metres into a hump between
  -- them and vanished from the street), sides along mitred normals, a top and two end caps.
  -- Concrete for walls and concrete/brick/stone fences, chain link for the rest (fast.add_fence).
  local function fence(line)
    local tags = line.tags or NONE
    local ft = tags.fence_type
    local concrete = tags.barrier == 'wall' or ft == 'concrete' or ft == 'brick' or ft == 'stone'
    local kind = concrete and 'fence_wall' or 'fence_mesh'
    local height = math.min(3, number(tags.height, concrete and 2 or 1.6))
    local half = (concrete and tune.wallThick or tune.fenceThick) / 2
    local scale = concrete and 2.5 or 2
    local raw, pts, along = line.points or NONE, {}, {}
    for index = 1, #raw - 1 do
      local a, b = raw[index], raw[index + 1]
      local length = math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2)
      if length > EPS then
        local n = math.max(1, math.ceil(length / tune.fenceStep))
        for k = #pts == 0 and 0 or 1, n do
          pts[#pts + 1] = {a[1] + (b[1] - a[1]) * k / n, a[2] + (b[2] - a[2]) * k / n}
          along[#pts] = (#pts > 1 and along[#pts - 1] + length / n) or 0
        end
      end
    end
    if #pts < 2 or not boundsTouch(rect, ringBounds({pts}), half + 1) then return end
    local normals = {}
    for k = 1, #pts do
      local tx, ty = 0, 0
      for _, pair in ipairs({{k - 1, k}, {k, k + 1}}) do
        local a, b = pts[pair[1]], pts[pair[2]]
        if a and b then
          local dx, dy = b[1] - a[1], b[2] - a[2]
          local l = math.sqrt(dx * dx + dy * dy)
          tx, ty = tx + dx / l, ty + dy / l
        end
      end
      local l = math.max(EPS, math.sqrt(tx * tx + ty * ty))
      local mitre = math.min(2, ((k == 1 or k == #pts) and 1 or 2) / l)
      normals[k] = {-ty / l * mitre * half, tx / l * mitre * half}
      pts[k][3] = ground(pts[k][1], pts[k][2]) - .1
    end
    local function corner(k, side, up)
      local p, n = pts[k], normals[k]
      local z = p[3] + (up and height + .1 or 0)
      return {p[1] + n[1] * side, p[2] + n[2] * side, z, along[k] / scale, (z - p[3]) / scale}
    end
    -- A piece over a carriageway or a deck is left out: OSM fences cross a road at a gate or pass
    -- under a bridge, and on the ground lattice (24 m DEM) a yard's wall stood 2 m high across the
    -- Povitrianykh Syl overpass in Kyiv.
    local function overRoad(k)
      local x, y = (pts[k][1] + pts[k + 1][1]) / 2, (pts[k][2] + pts[k + 1][2]) / 2
      for _, segment in ipairs(segmentBins[(floor(x / 50) + 32768) * 65536 + floor(y / 50) + 32768] or NONE) do
        local a = segment.a
        local t = math.max(0, math.min(1, ((x - a[1]) * segment.dx + (y - a[2]) * segment.dy) / segment.len2))
        if (x - a[1] - t * segment.dx) ^ 2 + (y - a[2] - t * segment.dy) ^ 2 < (segment.width / 2 + .5) ^ 2 then return true end
      end
      return false
    end
    for k = 1, #pts - 1 do
      local box = ringBounds({{pts[k], pts[k + 1]}})
      if boundsTouch(rect, box, half * 2 + .5) and not overRoad(k) then
        scene.polygon(kind, {corner(k + 1, 1), corner(k, 1), corner(k, 1, true), corner(k + 1, 1, true)}, false)
        scene.polygon(kind, {corner(k, -1), corner(k + 1, -1), corner(k + 1, -1, true), corner(k, -1, true)}, false)
        scene.polygon(kind, {corner(k, 1, true), corner(k, -1, true), corner(k + 1, -1, true), corner(k + 1, 1, true)}, true)
      end
    end
    for _, e in ipairs({{1, 2}, {#pts, #pts - 1}}) do
      local k = e[1]
      if boundsTouch(rect, ringBounds({{pts[k]}}), half * 2 + .5) then
        local a, b, c, d = corner(k, 1), corner(k, -1), corner(k, -1, true), corner(k, 1, true)
        a[4], b[4], c[4], d[4] = 0, 2 * half / scale, 2 * half / scale, 0
        if k == 1 then scene.polygon(kind, {b, a, d, c}, false) else scene.polygon(kind, {a, b, c, d}, false) end
      end
    end
    pause()
  end
  -- Far tiles keep fences: the near scene used to be the only copy, so a wall
  -- on a far tile vanished as the camera reached it. Paths stay near-only.
  -- Horizon draws neither.
  for _, line in ipairs(options.horizon and NONE or lists.lines) do
    local points, tags = line.points or {}, line.tags or {}
    if line.kind == 'gantry' then
      ROADS.gantry({rect = rect, ground = ground, face = function(poly, ox, oy, oz, material)
        ROADS.orient(scene.polygon, material, poly, ox, oy, oz)
      end}, line)
    end
    local barrier = (line.kind == 'fence' or line.kind == 'guard_rail') and #points >= 2
    for _, run in ipairs(barrier and (ROADS.offDecks(strips, points, ground) or {points}) or NONE) do
      if #run >= 2 and line.kind == 'fence' then
        fence(run == points and line or {tags = line.tags, points = run})
      elseif #run >= 2 then
        for _, piece in ipairs(ROADS.besideRoads(strips, run, tune.sidewalk)) do
          local path = {}
          for k, p in ipairs(piece) do path[k] = {p[1], p[2], 0} end
          ROADS.guardRail({rect = rect, ground = ground, face = function(poly, ox, oy, oz, material)
            ROADS.orient(scene.polygon, material, poly, ox, oy, oz)
          end}, path)
        end
        pause()
      end
    end
    if not distant then
      for index = 1, #points - 1 do
        local a, b = points[index], points[index + 1]
        local dx, dy = b[1] - a[1], b[2] - a[2]
        local length = math.sqrt(dx * dx + dy * dy)
        if length > EPS then
          if line.kind == 'path' then
            local width = number(tags.width, 2) / 2
            local nx, ny = -dy / length * width, dx / length * width
            local material = tags.surface == 'asphalt' and 'footway_asphalt' or tags.highway == 'path' and 'trodden' or 'footway'
            local poly = {{a[1] + nx, a[2] + ny}, {a[1] - nx, a[2] - ny}, {b[1] - nx, b[2] - ny}, {b[1] + nx, b[2] + ny}}
            drape(material, poly, .04)
          end
        end
        if index % 32 == 0 then pause() end
      end
    end
    pause()
  end
  local function static(name, shape, x, y, z, yaw, scale)
    scene.items[#scene.items + 1] = {kind = 'static', name = 'e2rl_' .. key .. '_' .. name,
      pos = {x, y, z}, rot = {0, 0, math.sin(yaw / 2), math.cos(yaw / 2)}, scale = scale or 1,
      shape = shape, decor = true, layer = 'scene', collision = 'None'}
  end
  mark('lines')
  local parking = {}
  if not distant then
    local occupied = {}
    for _, building in ipairs(lists.buildings) do
      if ringsTouch(building.rings, rect) then occupied[#occupied + 1] = {bounds = ringBounds(building.rings), rings = building.rings} end
    end
    local cars, maxCars = 0, math.max(0, math.min(300, options.maxCars or 300))
    local realCars = (options.parkedCars or 0) > 0
    local function buildingAt(x, y)
      for _, building in ipairs(occupied) do
        local b = building.bounds
        if x >= b[1] and x <= b[3] and y >= b[2] and y <= b[4] and inside(building.rings, x, y) then return true end
      end
      return false
    end
    for _, area in ipairs(lists.areas) do
      local tags = area.tags or {}
      -- an underground or rooftop car park keeps its cars off the ground above it
      local surface = tags.parking ~= 'underground' and tags.parking ~= 'rooftop' and tags.location ~= 'underground'
      if cars < maxCars and surface and (tags.amenity == 'parking' or area.kind == 'parking') and ringsTouch(area.rings, rect) then
        local frame = footprintFrame(cleanRing(area.rings[1]))
        if frame.area >= 120 then
          local row = 0
          for v = frame.v0 + 2.75, frame.v1 - 2.7, 5.5 do
            if row % 3 ~= 1 then
              for u = frame.u0 + 1.35, frame.u1 - 1.3, 2.7 do
                local x, y = u * frame.ax + v * frame.bx, u * frame.ay + v * frame.by
                local h = hash(tostring(area.id) .. ':' .. string.format('%.3f:%.3f', u, v))
                if x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4] and not buildingAt(x, y) then
                  local yaw = math.atan2(frame.by, frame.bx) + (h % 2 == 0 and math.pi or 0)
                  local fits = true
                  for _, corner in ipairs({{-2.2, -.9}, {2.2, -.9}, {2.2, .9}, {-2.2, .9}}) do
                    local cx = x + corner[1] * math.cos(yaw) - corner[2] * math.sin(yaw)
                    local cy = y + corner[1] * math.sin(yaw) + corner[2] * math.cos(yaw)
                    if not inside(area.rings, cx, cy) then fits = false end
                  end
                  if fits then
                    -- every free bay is a spot for the game's parked cars (parking.lua); with
                    -- those off, two of three bays get a box car
                    parking[#parking + 1] = {x, y, ground(x, y), yaw}
                    if not realCars and h % 100 < 66 then
                      parkedCar(sceneDecor, x, y, ground(x, y) + .02, yaw, math.floor(h / 100) % 8)
                    end
                    cars = cars + 1
                  end
                end
                if cars >= maxCars then break end
              end
            end
            row = row + 1
            pause()
            if cars >= maxCars then break end
          end
        end
      end
      if cars >= maxCars then break end
    end
  end
  mark('decor')
  -- The far ground is coarse triangles (options.farStep, 100 m) inside the tile and a fan to the fine
  -- lattice at its border: it ignores a road's cutting. Each far road surface vertex is lifted to
  -- ROADS.far.clear over the far ground's own triangle under it (never lowered), so it is not hidden.
  if farRoads and #farQuads > 0 then
    local BIN, bins = 50, {}
    for _, t in ipairs(farTris) do
      local x0, y0 = math.min(t[1][1], t[2][1], t[3][1]), math.min(t[1][2], t[2][2], t[3][2])
      local x1, y1 = math.max(t[1][1], t[2][1], t[3][1]), math.max(t[1][2], t[2][2], t[3][2])
      for bx = floor(x0 / BIN), floor(x1 / BIN) do
        for by = floor(y0 / BIN), floor(y1 / BIN) do
          local key = (bx + 32768) * 65536 + by + 32768
          local bin = bins[key] or {}
          bins[key], bin[#bin + 1] = bin, t
        end
      end
    end
    local function farHeight(x, y)
      for _, t in ipairs(bins[(floor(x / BIN) + 32768) * 65536 + floor(y / BIN) + 32768] or NONE) do
        local a, b, c = t[1], t[2], t[3]
        local den = (b[2] - c[2]) * (a[1] - c[1]) + (c[1] - b[1]) * (a[2] - c[2])
        if math.abs(den) > 1e-9 then
          local u = ((b[2] - c[2]) * (x - c[1]) + (c[1] - b[1]) * (y - c[2])) / den
          local v = ((c[2] - a[2]) * (x - c[1]) + (a[1] - c[1]) * (y - c[2])) / den
          if u >= -1e-6 and v >= -1e-6 and u + v <= 1 + 1e-6 then return u * a[3] + v * b[3] + (1 - u - v) * c[3] end
        end
      end
      return nil
    end
    local function lifted(p)
      local h = farHeight(p[1], p[2])
      return {p[1], p[2], h and math.max(p[3], h + ROADS.far.clear) or p[3]}
    end
    for _, item in ipairs(farQuads) do
      local material, poly = item[1], item[2]
      if #poly == 4 then
        -- cut along the road every 10 m: the far ground bends at its triangle edges, a long quad would not
        local len = math.sqrt((poly[4][1] - poly[1][1]) ^ 2 + (poly[4][2] - poly[1][2]) ^ 2)
        local n = math.max(1, math.ceil(len / 10))
        local function at(t)
          return lifted(lerp(poly[1], poly[4], t)), lifted(lerp(poly[2], poly[3], t))
        end
        local l0, r0 = at(0)
        for i = 1, n do
          local l1, r1 = at(i / n)
          scene.polygon(material, {l0, r0, r1, l1}, 'flat')
          l0, r0 = l1, r1
        end
      else
        local out = {}
        for k, p in ipairs(poly) do out[k] = lifted(p) end
        scene.polygon(material, out, 'flat')
      end
    end
  end
  if not roadManifest then finishRoad() end
  scene.finish()
  sceneDecor.finish()
  for _, item in ipairs(sceneDecor.items) do item.decor = true; scene.items[#scene.items + 1] = item end
  for material in pairs(sceneDecor.used) do scene.used[material] = true end
  -- A bus shelter stands beyond the curb (and sidewalk) of the nearest ground-level road, its open
  -- side to the road (fast.add_street_points): OSM puts most stops on the carriageway itself.
  -- A platform and its stop position nearby make one shelter.
  local shelters = {}
  local function shelter(point, p)
    for _, q in ipairs(shelters) do
      if (q[1] - p[1]) ^ 2 + (q[2] - p[2]) ^ 2 < 900 then return end
    end
    local best, hit = 3600, nil
    for _, strip in ipairs(strips) do
      if strip.surface then
        local pts = strip.points
        for k = 1, #pts - 1 do
          local a, b = pts[k], pts[k + 1]
          local dx, dy = b[1] - a[1], b[2] - a[2]
          local len2 = dx * dx + dy * dy
          if len2 > EPS then
            local t = math.max(0, math.min(1, ((p[1] - a[1]) * dx + (p[2] - a[2]) * dy) / len2))
            local qx, qy = a[1] + dx * t, a[2] + dy * t
            local d = (p[1] - qx) ^ 2 + (p[2] - qy) ^ 2
            if d < best then best, hit = d, {strip = strip, k = k, x = qx, y = qy, dx = dx, dy = dy, len = math.sqrt(len2)} end
          end
        end
      end
    end
    if not hit then return end
    local nx, ny = -hit.dy / hit.len, hit.dx / hit.len
    local side = (p[1] - hit.x) * nx + (p[2] - hit.y) * ny >= 0 and 1 or -1
    if math.sqrt(best) < hit.strip.hw + .5 then side = -1 end  -- on the carriageway: its right side
    local walk = hit.strip.walk[hit.k][side] and tune.sidewalk or 0
    local off = hit.strip.hw + walk + 1.4
    local x, y = hit.x + nx * side * off, hit.y + ny * side * off
    if x < rect[1] or x >= rect[3] or y < rect[2] or y >= rect[4] then return end
    shelters[#shelters + 1] = p
    local fx, fy = -nx * side, -ny * side
    static('point_' .. tostring(point.id):gsub('[^%w_]', '_'), BUS_STOP, x, y, ground(x, y) + .25,
      math.atan2(fx, fy) + math.pi)
    if options.experimentalDetail then
      -- 3.6 m along the road from the shelter, on its curb side, the plate facing the road
      local ux, uy = hit.dx / hit.len, hit.dy / hit.len
      local sx, sy = x + ux * 3.6 - nx * side * .6, y + uy * 3.6 - ny * side * .6
      -- the plate's front is the right of its line: for side 1 the road is to the right of +u
      local lx, ly = side == 1 and ux or -ux, side == 1 and uy or -uy
      BLD.stopSign(scene, sx, sy, ground(sx, sy), lx, ly, (point.tags or NONE).name)
    end
  end
  -- OSM maps many lamps (and some trees) as nodes of the street itself or on its carriageway: from
  -- 26.10 the packs carry them, and central Kyiv had ~3,700 lamps standing in the lanes. A lamp
  -- on a street at grade goes to that street's edge on its own side (0.7 m into the sidewalk, or
  -- 1.2 m onto the verge); one on a deck, with no street at grade under it, stands on the
  -- parapet at the deck's height. A tree there is left out, and so is a lamp whose new place is
  -- another carriageway. Returns x, y, z, or nil.
  -- The whole centre lines (segmentBins: a strip is cut back at a junction, a lamp on its plate is
  -- still on the road), at grade or on a deck, within 2 m of z when z is given.
  -- (one table: build() is at LuaJIT's 200 locals)
  local OFFROAD = {}
  function OFFROAD.nearestOn(x, y, z, bridges, except, reach)
    local best, hit = math.huge, nil
    for _, s in ipairs(segmentBins[(floor(x / 50) + 32768) * 65536 + floor(y / 50) + 32768] or NONE) do
      if s.road ~= except and ((s.surface and not bridges) or (bridges and ROADS.bridge(s.tags) and not ROADS.tunnel(s.tags))) then
        local a = s.a
        local t = math.max(0, math.min(1, ((x - a[1]) * s.dx + (y - a[2]) * s.dy) / s.len2))
        local qx, qy = a[1] + s.dx * t, a[2] + s.dy * t
        local d = math.sqrt((x - qx) ^ 2 + (y - qy) ^ 2)
        local sz = (a[3] or 0) + ((s.b[3] or 0) - (a[3] or 0)) * t + lift
        if d < s.width / 2 + (reach or .3) and d < best and (not z or math.abs(sz - z) < 2) then
          local len = math.sqrt(s.len2)
          best = d
          hit = {road = s.road, hw = s.width / 2, x = qx, y = qy, z = sz, nx = -s.dy / len, ny = s.dx / len}
        end
      end
    end
    return hit
  end
  -- the drawn asphalt at grade (strips, junction plates, mouths: addAsphalt's convex pieces), and
  -- within pad m of it
  function OFFROAD.onAsphalt(x, y)
    for _, entry in ipairs(asphaltBins[(floor(x / ABIN) + 32768) * 65536 + floor(y / ABIN) + 32768] or NONE) do
      local b = entry.bounds
      if x >= b[1] and x <= b[3] and y >= b[2] and y <= b[4] then
        local poly, inside = entry.poly, true
        for k = 1, #poly do
          local p, q = poly[k], poly[k % #poly + 1]
          local cross = (q[1] - p[1]) * (y - p[2]) - (q[2] - p[2]) * (x - p[1])
          if (entry.ccw and cross < 0) or (not entry.ccw and cross > 0) then inside = false; break end
        end
        if inside then return true end
      end
    end
    return false
  end
  function OFFROAD.nearAsphalt(x, y, pad)
    return OFFROAD.onAsphalt(x, y) or OFFROAD.onAsphalt(x + pad, y) or OFFROAD.onAsphalt(x - pad, y) or OFFROAD.onAsphalt(x, y + pad) or OFFROAD.onAsphalt(x, y - pad)
  end
  function OFFROAD.walkAt(road, x, y, side)
    if not OFFROAD.stripOf then
      OFFROAD.stripOf = {}
      for _, strip in ipairs(strips) do OFFROAD.stripOf[strip.road] = strip end
    end
    local strip, best, walk = OFFROAD.stripOf[road], math.huge, 0
    for k = 1, strip and #strip.points - 1 or 0 do
      local q = strip.points[k]
      local d = (q[1] - x) ^ 2 + (q[2] - y) ^ 2
      if d < best then best, walk = d, strip.walk[k][side] and tune.sidewalk or 0 end
    end
    return walk
  end
  function OFFROAD.offCarriageway(point, p)
    local x, y, z = p[1], p[2], ground(p[1], p[2])
    -- a street tree in its pit by the curb stays: only one on the asphalt itself goes
    if point.kind ~= 'lamp' then
      if OFFROAD.onAsphalt(x, y) then return nil end
      return x, y, z
    end
    -- at the drawn ground's height or the point's own (the pack's DEM, under an embankment or a
    -- cutting): a street at grade, not a deck over it
    local h = type(p[3]) == 'number' and p[3] or z
    local hit = OFFROAD.nearestOn(x, y, z, false) or OFFROAD.nearestOn(x, y, h, false)
    -- on a junction's corner or a mouth, past the centre line's width: the nearest street's side
    if not hit and OFFROAD.nearAsphalt(x, y, .3) then
      hit = OFFROAD.nearestOn(x, y, z, false, nil, 30) or OFFROAD.nearestOn(x, y, h, false, nil, 30)
    end
    local bridge = not hit and OFFROAD.nearestOn(x, y, nil, true)
    hit = hit or bridge
    if not hit then return x, y, z end
    if point.kind ~= 'lamp' then return nil end
    local side = (x - hit.x) * hit.nx + (y - hit.y) * hit.ny >= 0 and 1 or -1
    local walk = OFFROAD.walkAt(hit.road, hit.x, hit.y, side)
    local off = bridge and hit.hw + walk - ROADS.deck.thick / 2 or hit.hw + (walk > 0 and .7 or 1.2)
    local d = (x - hit.x) * hit.nx * side + (y - hit.y) * hit.ny * side
    off = math.max(off, d)
    x, y = hit.x + hit.nx * side * off, hit.y + hit.ny * side * off
    -- off the drawn asphalt, half a metre at a time (a turning lane, a junction's corner)
    for _ = 1, 16 do
      if bridge or not OFFROAD.nearAsphalt(x, y, .3) then break end
      x, y = x + hit.nx * side * .5, y + hit.ny * side * .5
    end
    if not bridge and OFFROAD.nearAsphalt(x, y, .3) then return nil end
    z = bridge and hit.z + ROADS.deck.parapet or ground(x, y)
    if OFFROAD.nearestOn(x, y, z, false, hit.road) or OFFROAD.nearestOn(x, y, z, true, hit.road) then return nil end
    return x, y, z
  end
  for _, point in ipairs(distant and NONE or lists.points) do
    local p = point.pos
    if p and point.kind == 'stop' and wantStops then
      shelter(point, p)
    elseif p and point.kind == 'lift_gate' and options.experimentalDetail and
        p[1] >= rect[1] and p[1] < rect[3] and p[2] >= rect[2] and p[2] < rect[4] then
      BLD.liftGate(scene, p, lists.roads, ground)
    elseif p and p[1] >= rect[1] and p[1] < rect[3] and p[2] >= rect[2] and p[2] < rect[4] then
      local shape = point.kind == 'tree' and VEG.tree or (point.kind == 'lamp' and wantLamps) and LAMP or
        (point.kind == 'bench' and options.experimentalDetail) and BENCH[1]
      local x, y, z
      if shape then x, y, z = OFFROAD.offCarriageway(point, p) end
      if x then
        -- a mapped bench faces the nearest path or road within 8 m (its front is local +y)
        local yaw = 0
        if point.kind == 'bench' then
          local best, fx, fy = 8
          for _, line in ipairs(lists.lines) do
            if line.kind == 'path' then
              local pts = line.points or NONE
              for q = 1, #pts - 1 do
                local d, t = segDistance(x, y, pts[q], pts[q + 1])
                if d < best and d > .3 then
                  local l = math.max(EPS, math.sqrt((pts[q + 1][1] - pts[q][1]) ^ 2 + (pts[q + 1][2] - pts[q][2]) ^ 2))
                  best, fx, fy = d, pts[q][1] + (pts[q + 1][1] - pts[q][1]) * t / l, pts[q][2] + (pts[q + 1][2] - pts[q][2]) * t / l
                end
              end
            end
          end
          if fx then yaw = math.atan2(fx - x, fy - y) end
        end
        static('point_' .. tostring(point.id):gsub('[^%w_]', '_'), shape, x, y, z, yaw)
        local it = scene.items[#scene.items]
        it.prop, it.streetKind, it.collision = true, point.kind, 'Collision Mesh'
      end
    end
    pause()
  end
  if wantLamps and not distant then
    local function treeAt(x, y)
      local p = bio.at(x, y)
      if p and (p.group == 'ice' or p.group == 'tundra' or rawHeight(x, y) - bio.sea > bio.treeline(p)) then return nil end
      local set = VEG.have('town')
      if p and (p.group == 'desert' or p.group == 'savanna' or p.group == 'rainforest') then set = VEG.use('palmFan')
      elseif p and p.group == 'mediterranean' then set = VEG.use('med') end
      return set[1]
    end
    local tree = (options.maxTrees or 2400) > 0 and {TREE, kind = 'tree', priority = 2, scale = .65,
      fp = {-2, 2, -2, 2}} or nil
    local containers = {}
    local function put(name, shape, x, y, z, yaw, scale, kind)
      static(name, shape, x, y, z, yaw, scale)
      local it = scene.items[#scene.items]
      it.prop, it.streetKind, it.collision = true, kind, 'Collision Mesh'
      -- the middle container of a row (YARD screens the site)
      if name:sub(1, 5) == 'bins_' and name:sub(-2) == '_1' then containers[#containers + 1] = {x = x, y = y, yaw = yaw} end
    end
    local _, reserved = VEG.streetProps(strips, lists.lines, lists.buildings, segmentBins, rect,
      options.propSpacing, lift, tune.sidewalk, ground, put, pause,
      {lamps = true, tree = tree, treeAt = treeAt, areas = lists.areas, points = lists.points, look = look,
        shopLinks = shopLinks})
    local yardCtx = {rect = rect, scene = scene, decor = sceneDecor, ground = ground, drapeRings = drapeRings,
      put = put, lists = lists, strips = strips, segmentBins = segmentBins, reserved = reserved,
      spacing = options.propSpacing or 0, pause = pause, have = VEG.have, lamp = LAMP, containers = containers}
    local before = #sceneDecor.items
    -- options.yard == false leaves the yards as the street furniture left them (A/B benches)
    if options.yard ~= false then reserved = YARD.build(yardCtx) end
    -- the scene was finished before the furniture: flush what the yard drew, its cars as decor
    scene.finish()
    sceneDecor.finish()
    for k = before + 1, #sceneDecor.items do
      local item = sceneDecor.items[k]
      item.decor = true
      scene.items[#scene.items + 1] = item
    end
    for material in pairs(sceneDecor.used) do scene.used[material] = true end
    scene.streetReservations = reserved
    -- what the yard laid out, for the offline maps and tests (cars and kit are mesh, not items)
    scene.yard = {cars = yardCtx.cars, kit = yardCtx.kit, containers = containers}
  end
  if decor then
    local WALL = 3
    local blockers = {}
    for index, building in ipairs(lists.buildings) do
      local b = ringBounds(building.rings)
      if boundsTouch(b, rect, WALL) then blockers[#blockers + 1] = {rings = building.rings, bounds = b, wall = true} end
      if index % 256 == 0 then pause() end
    end
    for _, area in ipairs(lists.areas) do
      -- a playground keeps its sand free of the tree scatter (YARD)
      if (area.kind == 'water' or area.kind == 'paved' or area.kind == 'playground') and ringsTouch(area.rings, rect) then
        blockers[#blockers + 1] = {rings = area.rings, bounds = ringBounds(area.rings), paved = area.kind == 'paved'}
      end
    end
    local blockedOps = 0
    -- wall: clearance from building walls (a crown), 0 for grass and stones. paved: a mapped
    -- tree may stand in a square or a car park (a grate in the paving), a lattice one may not.
    local function blocked(x, y, pad, wall, paved)
      pad, wall = pad or 3.5, wall or 0
      if scene.streetReservations and VEG.streetBlocked(scene.streetReservations, x, y) then return true end
      local nearby = segmentBins[(floor(x / 50) + 32768) * 65536 + floor(y / 50) + 32768] or NONE
      for _, segment in ipairs(nearby) do
        local a = segment.a
        local t = math.max(0, math.min(1, ((x - a[1]) * segment.dx + (y - a[2]) * segment.dy) / segment.len2))
        if (x - a[1] - t * segment.dx) ^ 2 + (y - a[2] - t * segment.dy) ^ 2 < (segment.width / 2 + pad) ^ 2 then return true end
        blockedOps = blockedOps + 1
        if blockedOps % 512 == 0 then pause() end
      end
      for _, blocker in ipairs(blockers) do
        local b = blocker.bounds
        local m = blocker.wall and wall or 0
        if not (paved and blocker.paved) and x >= b[1] - m and y >= b[2] - m and x <= b[3] + m and y <= b[4] + m
            and (inside(blocker.rings, x, y) or (m > 0 and nearEdge(blocker.rings, x, y, m))) then return true end
        blockedOps = blockedOps + 1
        if blockedOps % 512 == 0 then pause() end
      end
      return false
    end
    -- The same world lattice, eligibility and ordering are used for near/far.
    -- Far takes the first N accepted plants, never a new seed or position.
    local candidates, positions = {}, {}
    local function optNum(name, default, lo, hi)
      local value = tonumber(options[name])
      if not value then value = default end
      return math.max(lo, math.min(hi, value))
    end
    -- Smooth 0..1 noise with `size` m features (GROVE by default): groups of trees and the
    -- lawns or fields between them.
    local GROVE = 45
    local function grove(x, y, size, seed)
      size = size or GROVE
      local fx, fy = x / size, y / size
      local gx, gy = floor(fx), floor(fy)
      local tx, ty = fx - gx, fy - gy
      tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
      seed = seed or 7
      local v00, v10 = ihash(seed, gx, gy) % 1000 / 1000, ihash(seed, gx + 1, gy) % 1000 / 1000
      local v01, v11 = ihash(seed, gx, gy + 1) % 1000 / 1000, ihash(seed, gx + 1, gy + 1) % 1000 / 1000
      local a, b = v00 + (v10 - v00) * tx, v01 + (v11 - v01) * tx
      return a + (b - a) * ty
    end
    local forestSpacing = optNum('forestSpacing', 5, 4, 24)
    local groundSpacing = optNum('groundSpacing', 6, 4, 30)
    -- Town yards stay a loose lattice. A 8 m step turned every courtyard into forest
    -- and the extra crowns were what dropped the frame from 60 to the twenties. 21.10 the
    -- user still found a tree on every free spot of the city: yards and parks are looser
    -- again, and residential land plants only inside groves (VEG.grove below).
    local spacingOf = {forest = forestSpacing, park = 14, residential = 16, orchard = 13, scrub = 12, heath = 16}
    local townChance = {park = .5, orchard = .45}
    -- Open woodland of dry mountains (pinyon and juniper on Nevada's ranges): from 1500 m under
    -- the tree line, fully 900 m under it, thinning out to the line.
    function bio.woodland(p, e)
      local t = bio.treeline(p)
      local w = math.max(0, math.min(1, (e - (t - 1500)) / 600))
      return w * math.max(0, math.min(1, (t - e) / 250))
    end
    -- Crowns and shrubs on open ground at a place: (chance, kind, shrub). Temperate, boreal and
    -- rainforest land keeps the chance it had; a desert gets shrubs and junipers on its ranges, a
    -- steppe fewer, a Mediterranean hill oak savanna and chaparral under its mountain pines, a
    -- savanna scattered trees, the tundra and the alpine belt dwarf shrubs.
    function bio.open(p, x, y, chance, kind, e)
      local g, treeline = p.group, bio.treeline(p)
      if kind == 'town' or kind == 'garden' then return chance, kind, false end
      local shrubAbove = e > treeline - 40 and g ~= 'ice' and g ~= 'desert'
      if shrubAbove then
        -- dwarf shrubs thin out over the lower half of the alpine belt
        local high = (e - treeline) / math.max(300, p.snowline - treeline)
        return math.max(0, .16 * (1 - 2 * high)), kind, true
      end
      if g == 'temperate' or g == 'boreal' or g == 'rainforest' then return chance, kind, false end
      local pick = bio.noise(x, y, 23, 73)
      if g == 'desert' or g == 'steppe' then
        local w = bio.woodland(p, e)
        local tree = (g == 'desert' and .45 or .55) * w + (g == 'steppe' and .015 or 0)
        if pick < .5 then return tree * 2, kind, false end
        return g == 'desert' and .26 or .2, kind, true
      elseif g == 'mediterranean' then
        -- conifer forest of the mountains (the Sierra's west slope, the Apennines) from ~900 m
        local forest = math.max(0, math.min(1, (e - 900) / 600))
        local savanna = bio.noise(x, y, 90, 75) > .55 and .45 or .03
        if forest > 0 and pick < forest then return .85, kind, false end
        if pick < .55 then return savanna, kind, false end
        return bio.noise(x, y, 150, 77) > .45 and .3 or .05, kind, true
      elseif g == 'savanna' then
        if pick < .5 then return bio.noise(x, y, 80, 79) > .6 and .3 or .06, kind, false end
        return .12, kind, true
      elseif g == 'tundra' then
        return .25, kind, true
      end
      return 0, kind, false
    end
    -- Species of a crown or shrub at a place: (set, scale), or nil for the temperate choice.
    function bio.species(p, candidate, e, needle, settled, u, h)
      local g, kind, treeline = p.group, candidate.kind, bio.treeline(p)
      local scrubby = candidate.shrub or kind == 'scrub' or kind == 'heath'
      if scrubby then
        if e > treeline - 100 or g == 'tundra' then return 'tundraShrub', .45 + u * .4 end
        if g == 'desert' or g == 'steppe' then return p.hot and 'desertShrubHot' or 'desertShrub', .7 + u * .5 end
        if g == 'mediterranean' then
          if p.west then return 'chaparralWest', .35 + u * .35 end
          return 'chaparral', .5 + u * .4
        end
        if g == 'savanna' or g == 'rainforest' then return 'tropicalBush', .45 + u * .4 end
        return nil
      end
      local hot = g == 'rainforest' or g == 'savanna'
      -- palms: the beaches of the tropics, a share of every street and yard where they grow
      if kind == 'beach' then return hot and 'palmCoco' or 'palmFan', .7 + u * .4 end
      if settled and p.palms and h % 100 < (hot and 55 or 35) then return hot and 'palmCoco' or 'palmFan', .7 + u * .4 end
      if p.australia then return 'eucalyptus', (settled and .5 or .65) + u * .4 end
      if g == 'desert' or g == 'steppe' then
        if settled then return p.west and 'oakWest' or 'med', .6 + u * .4 end
        local pine = (e - (treeline - 800)) / 600
        if keyHash(81, candidate.key) % 1000 / 1000 < pine then return p.west and 'pineWest' or 'pine', .6 + u * .4 end
        return 'juniper', .75 + u * .45
      elseif g == 'mediterranean' then
        if needle or e > 1000 + (h % 400) then
          if e > 1700 then return 'fir', .65 + u * .45 end
          return p.west and 'pineWest' or 'medPine', .7 + u * .45
        end
        if p.west then
          if settled and h % 100 < 20 then return 'eucalyptus', .55 + u * .35 end
          return 'oakWest', (settled and .6 or .8) + u * .4
        end
        return 'med', (settled and .6 or .75) + u * .4
      elseif g == 'savanna' then
        if settled then return 'tropical', .4 + u * .3 end
        return 'tropical', .35 + u * .3
      elseif g == 'rainforest' then
        if not settled and e < 40 and h % 100 < 45 then return 'palmCoco', .7 + u * .4 end
        return 'tropical', (settled and .4 or .55) + u * .4
      elseif g == 'boreal' and not settled and not needle and kind ~= 'park' then
        if keyHash(83, candidate.key) % 1000 / 1000 < .75 then
          return e > VEG.firFrom and 'fir' or 'pine', .7 + u * .55
        end
      end
      return nil
    end
    -- Grass, flowers, ferns, understory and stones of the decor scatter at a place: another
    -- climate's set, false for none, `shapes` for the temperate one.
    function bio.decor(p, prefix, kind, e, shapes, x, y)
      local g = p.group
      if e > p.snowline - 350 and prefix ~= 'rock' then return false end
      local open = kind == 'ground' or kind == 'meadow' or kind == 'heath' or kind == 'forest' or kind == 'scrub'
      -- nothing green on scree, rock, snow or desert; the alpine turf keeps a third of its tufts
      local mild = (g == 'temperate' or g == 'boreal' or g == 'rainforest') and e < bio.treeline(p) - 150
      if open and x and not mild and prefix ~= 'rock' and prefix ~= 'bush' then
        local surface = surfaceKind(x, y, kind)
        if bio.bare[surface] or surface == 'desert' or surface == 'dune' then return false end
        if (surface == 'alpine' or surface == 'tundra') and (prefix == 'fern' or ihash(91, floor(x * 10), floor(y * 10)) % 3 ~= 0) then
          return false
        end
      end
      if prefix == 'grass' then
        -- yards of a dry town are gravel and a few dry tufts; parks and gardens are watered
        if kind == 'residential' and (p.arid or g == 'mediterranean') then
          return x and ihash(93, floor(x * 10), floor(y * 10)) % 4 == 0 and VEG.use('dryTufts') or false
        end
        if not open then return shapes end
        if g == 'desert' then return false end
        if g == 'steppe' or g == 'savanna' or g == 'mediterranean' then return VEG.use('dryTufts') end
      elseif prefix == 'flower' then
        if g == 'desert' or g == 'steppe' or g == 'savanna' or g == 'mediterranean' then return false end
      elseif prefix == 'fern' then
        if g ~= 'temperate' and g ~= 'boreal' and g ~= 'rainforest' then return false end
      elseif prefix == 'bush' then
        if p.arid then return VEG.use(p.hot and 'desertShrubHot' or 'desertShrub') end
        if g == 'mediterranean' then return VEG.use(p.west and 'chaparralWest' or 'chaparral') end
        if g == 'rainforest' or g == 'savanna' then return VEG.use('tropicalBush') end
      elseif prefix == 'rock' then
        if p.arid then return VEG.use('desertRocks') end
        if e > bio.treeline(p) - 100 or g == 'tundra' or g == 'ice' then return VEG.use('mountainRocks') end
      end
      return shapes
    end
    -- Layers of the climate's own open ground, on lattices of their own: sagebrush, creosote and
    -- dry plants of deserts and steppes, dry tufts of steppes, savannas and Mediterranean hills,
    -- turf of the alpine belt, and stones of deserts, the alpine belt and the tundra.
    -- (chance at a lattice point; set, lowest and highest size: metres for tufts, else scale)
    bio.bare = {scree = true, bare_rock = true, snow = true, snow_edge = true, glacier = true}
    function bio.layerChance(p, prefix, x, y, e)
      local g, treeline = p.group, bio.treeline(p)
      local alpine = e > treeline + 60
      if e > p.snowline - 200 then return prefix == 'rock' and .08 or 0 end
      if prefix == 'grass' then
        if g == 'desert' then return .3 end
        if g == 'steppe' then return .42 end
        if g == 'savanna' then return .3 end
        if g == 'mediterranean' then return bio.noise(x, y, 120, 57) > .7 and 0 or .22 end
        if alpine or g == 'tundra' then return .14 end
        return 0
      end
      if g == 'desert' then return .26 end
      if g == 'steppe' then return .09 end
      if alpine then return .2 + .35 * math.min(1, (e - treeline) / math.max(300, p.snowline - treeline)) end
      if g == 'tundra' then return .2 end
      if g == 'mediterranean' or g == 'savanna' then return .03 end
      return 0
    end
    function bio.layerSet(p, prefix, e, h)
      local g = p.group
      if prefix == 'grass' then
        if g == 'desert' or (g == 'steppe' and h % 10 < 6) then return VEG.use('desertPlants'), .75, 1.25 end
        if g == 'steppe' or g == 'savanna' or g == 'mediterranean' then return VEG.use('dryTufts'), .3, .65 end
        return VEG.grass, .14, .24
      end
      if p.arid then return VEG.use('desertRocks'), .55, 1.35 end
      return VEG.use('mountainRocks'), .6, 1.45
    end
    function bio.layers(grassCap, rockCap, spread)
      if distant or not bio.on then return end
      -- any other climate, or ground near a tree line, in the tile (3 x 3 samples)?
      local any = false
      for s = 0, 8 do
        local x, y = rect[1] + (s % 3 + .5) * size / 3, rect[2] + (floor(s / 3) + .5) * size / 3
        local p = bio.at(x, y)
        if p and ((p.group ~= 'temperate' and p.group ~= 'boreal' and p.group ~= 'rainforest')
            or rawHeight(x, y) - bio.sea > bio.treeline(p) - 200) then any = true end
      end
      if not any then return end
      for _, layer in ipairs({{'grass', 4.5, 31, grassCap}, {'rock', 7, 33, rockCap}}) do
        local prefix, spacing, seed, cap = layer[1], layer[2], layer[3], layer[4]
        local list, code = {}, floor(spacing * 10 + .5)
        for gy = floor(rect[2] / spacing) - 1, math.ceil(rect[4] / spacing) do
          for gx = floor(rect[1] / spacing) - 1, math.ceil(rect[3] / spacing) do
            if gx % 8 == 0 then pause() end
            local h = ihash(seed, gx, gy, code)
            local x = (gx + .5 + (h % 1000 / 1000 - .5) * .7) * spacing
            local y = (gy + .5 + (floor(h / 1000) % 1000 / 1000 - .5) * .7) * spacing
            if x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4] then
              local kind = coverAt(x, y)
              local p = NATURAL_GROUND[kind] and kind ~= 'beach' and kind ~= 'park' and bio.at(x, y)
              if p then
                local key = latticeKey(4, gx, gy, code)
                if keyHash(seed + 100, key) % 1000 / 1000 < bio.layerChance(p, prefix, x, y, rawHeight(x, y) - bio.sea) then
                  list[#list + 1] = {x = x, y = y, hash = h, key = key, p = p}
                end
              end
            end
          end
          pause()
        end
        spread(list, cap, 25, function(c)
          local x, y, h = c.x, c.y, c.hash
          local z = ground(x, y)
          local _, _, nz = groundNormal(x, y)
          -- a stone on a cliff face hung half in the air from the side (Whitney's east face)
          if nz < (prefix == 'rock' and .55 or .7) or (sea and z <= sea) or blocked(x, y, prefix == 'grass' and 2.2 or 3) then
            return false
          end
          local surface = (prefix == 'grass' or c.p.snowline - 400 < rawHeight(x, y) - bio.sea) and surfaceKind(x, y)
          if prefix == 'grass' and bio.bare[surface] then return false end
          -- a stone now and then on a snowfield, not a scatter
          if (surface == 'snow' or surface == 'glacier') and h % 8 ~= 0 then return false end
          local set, lo, hi = bio.layerSet(c.p, prefix, rawHeight(x, y) - bio.sea, h)
          local shape = set[h % #set + 1]
          local scale = lo + keyHash(seed + 200, c.key) % 1000 / 1000 * (hi - lo)
          local mesh = VEG.grassMesh[shape]
          if mesh then scale = scale / mesh.span; z = z - mesh.bottom * scale end   -- tufts: metres high
          if prefix == 'rock' and h % 6 == 0 then shape = set[#set]; scale = scale * .9 end
          static(prefix .. 'b_' .. c.key, shape, x, y, z, h % 6283 / 1000, scale)
          return true
        end)
      end
    end
    -- the tropics and hot coasts plant palms on mapped beaches
    local centre = bio.on and bio.at((rect[1] + rect[3]) / 2, (rect[2] + rect[4]) / 2)
    if centre and (centre.group == 'rainforest' or centre.group == 'savanna' or (centre.palms and centre.hot)) then
      spacingOf.beach, townChance.beach = 15, .32
    end
    for _, area in ipairs(lists.areas) do
      local spacing = spacingOf[area.kind]
      if spacing and ringsTouch(area.rings, rect) then
        local box = ringBounds(area.rings)
        for gy = floor(math.max(rect[2], box[2]) / spacing) - 1, math.ceil(math.min(rect[4], box[4]) / spacing) do
          for gx = floor(math.max(rect[1], box[1]) / spacing) - 1, math.ceil(math.min(rect[3], box[3]) / spacing) do
            if gx % 8 == 0 then pause() end
            local code = floor(spacing * 10 + .5)
            local h = ihash(1, gx, gy, code)
            local x = (gx + .5 + (h % 1000 / 1000 - .5) * .6) * spacing
            local y = (gy + .5 + (floor(h / 1000) % 1000 / 1000 - .5) * .6) * spacing
            local position = latticeKey(0, gx, gy, code)
            if x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4] and not positions[position] then
              local kind, owner = coverAt(x, y)
              if owner and spacingOf[kind] == spacing then
                positions[position] = true
                -- Coherent patches make clearings, instead of uniformly filling polygons.
                local cluster = ihash(3, floor(x / 65), floor(y / 65)) % 1000 / 1000
                -- A low floor left whole 65 m groves almost empty, which read as a broken forest.
                -- Parks and yards keep a lower chance so the town reads as lawns with trees, not canopy.
                local chance = kind == 'forest' and (.8 + .2 * cluster) or (townChance[kind] or 1)
                if kind == 'residential' then chance = grove(x, y) > .45 and .6 or .1 end
                -- A wood drawn over a village (Hatne's houses stand in an 11 ha forest polygon)
                -- thins round the houses to a sixth, its crowns kept off them like yard trees.
                local wooded = false
                if kind == 'forest' then
                  local built = builtAt(x, y, true)   -- houses only: a park wood among blocks stays a wood
                  if built > VEG.gardenFrom then
                    wooded = true
                    chance = chance * (1 - .85 * math.min(1, (built - VEG.gardenFrom) / .02))
                  end
                  -- a forest polygon of a dry climate is open woodland (a National Forest over
                  -- Nevada's sagebrush), a riverside grove keeps a quarter
                  local p = bio.on and bio.at(x, y)
                  if p and p.arid then chance = chance * math.max(.25, bio.woodland(p, rawHeight(x, y) - bio.sea)) end
                end
                if keyHash(4, position) % 1000 / 1000 < chance then
                  candidates[#candidates + 1] = {x=x, y=y, hash=h, key=position, kind=kind, tags=owner.tags or NONE,
                    wooded=wooded}
                end
              end
            end
          end
          pause()
        end
      end
    end
    -- Untagged hills in the country pack are kind 'ground'. Without this lattice
    -- they stay a green sheet with a tree only where OSM drew a forest polygon.
    -- Untagged ground among buildings is something else: courtyards, school and hospital
    -- grounds, verges, vacant lots (OSM areas the pack does not keep). Filled like a hill it
    -- made a forest of every Kyiv block. Past URBAN_FROM of built-up share the hill lattice
    -- fades into 'town' trees: groves with open lawns between them, broadleaf.
    local URBAN_FROM, URBAN_FULL = .03, .12
    local wantGround = options.groundTrees ~= false and options.groundTrees ~= 0
    if wantGround then
      for gy = floor(rect[2] / groundSpacing) - 1, math.ceil(rect[4] / groundSpacing) do
        for gx = floor(rect[1] / groundSpacing) - 1, math.ceil(rect[3] / groundSpacing) do
          if gx % 8 == 0 then pause() end
          local code = floor(groundSpacing * 10 + .5)
          local h = ihash(2, gx, gy, code)
          local x = (gx + .5 + (h % 1000 / 1000 - .5) * .6) * groundSpacing
          local y = (gy + .5 + (floor(h / 1000) % 1000 / 1000 - .5) * .6) * groundSpacing
          local position = latticeKey(1, gx, gy, code)
          if x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4] and not positions[position]
              and coverAt(x, y) == 'ground' then
            positions[position] = true
            -- Open land far from buildings stays the wooded hill it was (the Carpathian slopes the
            -- pack has no forest on went bare with fields between groves, veg-yaremche-a), with
            -- clearings of 110 m noise over about a third. Within ~75 m of buildings (a village,
            -- the private sector): sparse garden trees. Among a town's buildings: a few groves.
            local built, houses = builtAt(x, y), builtAt(x, y, true)
            local cluster = ihash(3, floor(x / 65), floor(y / 65)) % 1000 / 1000
            local chance, kind = grove(x, y, 110, 9) > .32 and .94 + .06 * cluster or .06, 'ground'
            local garden = math.max(0, math.min(1, (built - VEG.gardenFrom) / VEG.gardenRamp))
            if garden > 0 then
              chance = chance + ((grove(x, y) > .45 and .4 or .12) - chance) * garden
              if garden >= .5 then kind = 'garden' end
            end
            -- a town only by the share of its bigger buildings: a private sector of houses at
            -- 10 % built-up stayed bare under the town rule (veg-private-a)
            local urban = math.max(0, math.min(1, (built - houses - URBAN_FROM) / (URBAN_FULL - URBAN_FROM)))
            if urban > 0 then
              local town = grove(x, y) > .6 and .35 or .02
              chance = chance + (town - chance) * urban
              if urban >= .5 then kind = 'town' end
            end
            -- another climate's open land (bio.open); shrubs only near: they do not read from 3 km
            local p, shrub = bio.on and bio.at(x, y), false
            if p then chance, kind, shrub = bio.open(p, x, y, chance, kind, rawHeight(x, y) - bio.sea) end
            if keyHash(4, position) % 1000 / 1000 < chance and not (shrub and distant) then
              candidates[#candidates + 1] = {x = x, y = y, hash = h, key = position, kind = kind, tags = NONE, shrub = shrub}
            end
          end
        end
        pause()
      end
    end
    local config = type(options.nature) == 'table' and options.nature or NONE
    local treeChoice = lookOf('trees')
    if treeChoice == 'regional' then treeChoice = nil end
    local openPine = treeChoice == 'conifer' and .82 or treeChoice == 'broadleaf' and .12 or .4
    local latitude = math.abs(tonumber(options.latitude) or 48)
    -- A configurable regional heuristic, not a measured tree-line dataset.
    -- Explicit OSM leaf_type overrides the biome mix, never slope/water exclusions.
    local treeline = tonumber(config.treeLine) or (latitude > 65 and 800 or latitude > 55 and 1500 or latitude > 35 and 2200 or 3600)
    local coniferStart = tonumber(config.coniferStart) or (latitude > 55 and 0 or 1000)
    -- 0 is a real cap. `or` would also keep it (0 is truthy in Lua); optNum clamps it.
    local maxTrees = optNum('maxTrees', 2400, 0, 2400)
    if distant then maxTrees = math.min(maxTrees, optNum('maxFarTrees', 800, 0, 1200)) end
    -- A global hash prefix spends the whole cap on whichever grove hashed lowest,
    -- so the next street or hillside stays a green sheet. Round-robin gives every
    -- 25 m cell a turn. Far stops earlier on that same sequence, so it stays a prefix.
    -- Candidates come unsorted: each bucket is sorted by (hash, key) on its own, which gives a
    -- bucket the same order as one sort of the whole list did, with pauses between buckets
    -- (that sort ran 15-30 ms unbroken in a city tile).
    local function byHash(a, b) return a.hash == b.hash and a.key < b.key or a.hash < b.hash end
    local function spread(list, limit, cell, accept)
      if limit <= 0 then return end
      local buckets, ids = {}, {}
      for index = 1, #list do
        if index % 64 == 0 then pause() end
        local item = list[index]
        local id = (floor(item.x / cell) + 32768) * 65536 + floor(item.y / cell) + 32768
        local bucket = buckets[id]
        if not bucket then
          bucket = {}
          buckets[id] = bucket
          ids[#ids + 1] = id
        end
        bucket[#bucket + 1] = item
      end
      table.sort(ids)
      for index = 1, #ids do
        table.sort(buckets[ids[index]], byHash)
        if index % 16 == 0 then pause() end
      end
      local cursor, planted, moving = {}, 0, true
      while planted < limit and moving do
        moving = false
        for index = 1, #ids do
          if planted >= limit then break end
          local id = ids[index]
          local bucket = buckets[id]
          local at = (cursor[id] or 0) + 1
          while at <= #bucket do
            pause() -- Bound even a long run of rejected candidates.
            local item = bucket[at]
            at = at + 1
            if accept(item) then
              planted = planted + 1
              moving = true
              break
            end
          end
          cursor[id] = at - 1
        end
        pause()
      end
    end
    -- OSM tree rows (natural=tree_row): surveyed crowns along streets and field edges. They
    -- go before the lattice and spend its cap first; far plants a prefix of the same rows.
    -- A crown stands where the row crosses a ROW_STEP grid line of its main axis, so a row
    -- read from two cells or tiles keeps one rhythm.
    local ROW_STEP, rowPlanted, rowSeen = 8, 0, {}
    for _, line in ipairs(maxTrees > 0 and lists.lines or NONE) do
      if line.kind == 'tree_row' then
        local points, tags = line.points or NONE, line.tags or NONE
        local needle = tags.leaf_type == 'needleleaved' or tags.leaf_type == 'coniferous'
        for index = 1, #points - 1 do
          local a, b = points[index], points[index + 1]
          local dx, dy = b[1] - a[1], b[2] - a[2]
          local axis = math.abs(dx) >= math.abs(dy) and 1 or 2
          local from, to = a[axis], b[axis]
          for k = math.ceil(math.min(from, to) / ROW_STEP), math.floor(math.max(from, to) / ROW_STEP) do
            local t = math.abs(to - from) > EPS and (k * ROW_STEP - from) / (to - from) or 1
            local x, y = a[1] + dx * t, a[2] + dy * t
            local position = latticeKey(3, floor(x), floor(y), 1)
            -- t = 1 is the next segment's first crown
            if rowPlanted < maxTrees and t < 1 - EPS and not rowSeen[position]
                and x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4] then
              rowSeen[position] = true
              local z = ground(x, y)
              if (not sea or z > sea) and not blocked(x, y, .5, 2, true) then
                local h = keyHash(8, position)
                -- a poplar now and then: their billboards are baked autumn yellow (the level's
                -- imposter), and a village full of them looked like October from 150 m (veg-hatne-b)
                local name = needle and 'pine' or (h % 10 < 1 and 'poplar' or 'town')
                -- avenues of palms where they grow, of the climate's own street trees elsewhere
                local p = bio.on and bio.at(x, y)
                if p and not needle then
                  local hot = p.group == 'rainforest' or p.group == 'savanna'
                  if p.palms and h % 10 < 4 then name = hot and 'palmCoco' or 'palmFan'
                  else name = bio.species(p, {kind = 'town', key = position}, z - bio.sea, false, true, .5, h) or name end
                end
                local set = VEG.use(name)
                static(string.format('tree_row_%d', position), set[math.floor(h / 7) % #set + 1], x, y, z, h % 6283 / 1000, .8 + keyHash(6, position) % 300 / 1000)
                rowPlanted = rowPlanted + 1
              end
            end
          end
          if index % 32 == 0 then pause() end
        end
      end
    end
    spread(candidates, maxTrees - rowPlanted, 25, function(candidate)
      local x, y, h = candidate.x, candidate.y, candidate.hash
      local z = ground(x, y)
      local elevation = rawHeight(x, y) - (options.seaLevel or 20)
      local _, _, nz = groundNormal(x, y)
      local bush = candidate.kind == 'scrub' or candidate.kind == 'heath' or candidate.shrub
      local kind = candidate.kind
      local settled = kind == 'town' or kind == 'residential' or kind == 'garden' or kind == 'park' or candidate.wooded
      -- the climate's own tree line; dwarf shrubs climb to the snow
      local p = bio.on and bio.at(x, y)
      local line, shrubLine = treeline, 250
      if p then line, shrubLine = bio.treeline(p), math.max(250, p.snowline - 300 - bio.treeline(p)) end
      if p and bush and (p.arid or elevation > line - 150) and bio.bare[surfaceKind(x, y, kind == 'ground' and 'ground' or nil)] then
        return false
      end
      -- a crown's radius from walls (4.5 m) and roads (4 m) where people live: it stood 3 m off a wall.
      -- A garden's small fruit-sized trees keep 3 m.
      if not (nz >= (bush and .64 or .72) and elevation < line + (bush and shrubLine or 0)
          and (not sea or z > sea) and not blocked(x, y, settled and (kind == 'garden' and 3 or 4) or nil,
            bush and 1.5 or (settled and (kind == 'garden' and 3 or 4.5) or WALL))) then return false end
      local leaf = candidate.tags.leaf_type or candidate.tags.wood
      local needle = leaf == 'needleleaved' or leaf == 'coniferous'
      if leaf ~= 'broadleaved' and leaf ~= 'deciduous' and not needle and candidate.kind == 'forest' then
        local mix = leaf == 'mixed' and .5 or math.max(0, math.min(.85, (elevation-coniferStart)/700))
        if treeChoice == 'conifer' then mix = math.max(mix, .7)
        elseif treeChoice == 'broadleaf' and leaf ~= 'mixed' then mix = math.min(mix, .15) end
        needle = keyHash(5, candidate.key) % 1000 / 1000 < mix
      end
      -- Open hills have no leaf_type. A fixed share of pines keeps a Carpathian mix.
      if candidate.kind == 'ground' then
        needle = keyHash(5, candidate.key) % 1000 / 1000 < openPine
      end
      -- Species and size by where it stands. Conifers: Scots pine in the lowlands, the fir
      -- (spruce, fir) from VEG.firFrom m up. Forests .7-1.25 of the model; town, park and
      -- garden trees are the small variants at .55-1.0 (the 1.55 cap made 30 m crowns).
      local u = keyHash(6, candidate.key) % 1000 / 1000
      local name, scale
      if bush then name, scale = 'bush', .5 + u * .4
      elseif needle then
        local fir = math.max(0, math.min(.9, (elevation - VEG.firFrom) / VEG.firRamp))
        name, scale = keyHash(10, candidate.key) % 1000 / 1000 < fir and 'fir' or 'pine', .7 + u * .55
      elseif kind == 'park' then name, scale = 'park', .6 + u * .45
      elseif kind == 'garden' or kind == 'orchard' then
        if h % 100 < 25 then name, scale = 'town', .65 + u * .35 else name, scale = 'garden', .5 + u * .35 end
      elseif settled then name, scale = 'town', .55 + u * .45
      elseif candidate.wooded then name, scale = 'forest', .6 + u * .4
      else name, scale = 'forest', .7 + u * .55 end
      if p then
        local other, size = bio.species(p, candidate, elevation, needle, settled, u, h)
        if other then name, scale = other, size end
        -- krummholz: the last 150 m under the tree line grows low and bent
        if not bush and not settled and elevation > line - 150 then
          scale = scale * (.45 + .55 * math.max(0, (line - elevation) / 150))
          if name == 'forest' or name == 'pine' then name = 'fir' end
        end
      end
      local set = VEG.use(name)
      -- Source and exact key: `..` prints 14 digits, and one lattice point's keys in two
      -- namespaces (forest and open ground at one spacing) printed the same name.
      static(string.format('tree_%s_%d', candidate.kind, candidate.key), set[h % #set + 1], x, y, z,
        h % 6283 / 1000, scale)
      return true
    end)
    -- Grass, forest floor and loose stone. Far keeps only a ranked handful of rocks:
    -- tufts do not read at the horizon, and the far list stays inside the near list.
    local SEED = {grass = 11, bush = 12, rock = 13, flower = 14, fern = 15}
    local function scatter(prefix, spacingOf, chanceOf, shapes, cap, farCap, scaleMin, scaleMax, minNz, elevationOf)
      local seed = SEED[prefix] or 19
      local limit = cap
      if distant then limit = farCap or 0 end
      if limit <= 0 then return end
      local candidates, positions = {}, {}
      for _, area in ipairs(lists.areas) do
        local spacing = spacingOf[area.kind]
        if spacing and ringsTouch(area.rings, rect) then
          local box = ringBounds(area.rings)
          for gy = floor(math.max(rect[2], box[2]) / spacing) - 1, math.ceil(math.min(rect[4], box[4]) / spacing) do
            for gx = floor(math.max(rect[1], box[1]) / spacing) - 1, math.ceil(math.min(rect[3], box[3]) / spacing) do
              if gx % 8 == 0 then pause() end
              local code = floor(spacing * 10 + .5)
              local h = ihash(seed, gx, gy, code)
              local x = (gx + .5 + (h % 1000 / 1000 - .5) * .55) * spacing
              local y = (gy + .5 + (floor(h / 1000) % 1000 / 1000 - .5) * .55) * spacing
              local position = latticeKey(0, gx, gy, code)
              if x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4] and not positions[position] then
                local kind = coverAt(x, y)
                if spacingOf[kind] == spacing and keyHash(seed + 100, position) % 1000 / 1000 < (chanceOf[kind] or 0) then
                  positions[position] = true
                  candidates[#candidates + 1] = {x = x, y = y, hash = h, key = position, kind = kind}
                end
              end
            end
            pause()
          end
        end
      end
      -- Kind 'ground' is the absence of a cover, so it has no area to walk.
      -- The Ukraine pack's open hills are this kind: without the lattice they stay a flat sheet.
      local openSpacing = spacingOf.ground
      if openSpacing then
        for gy = floor(rect[2] / openSpacing) - 1, math.ceil(rect[4] / openSpacing) do
          for gx = floor(rect[1] / openSpacing) - 1, math.ceil(rect[3] / openSpacing) do
            if gx % 8 == 0 then pause() end
            local code = floor(openSpacing * 10 + .5)
            local h = ihash(seed + 300, gx, gy, code)
            local x = (gx + .5 + (h % 1000 / 1000 - .5) * .55) * openSpacing
            local y = (gy + .5 + (floor(h / 1000) % 1000 / 1000 - .5) * .55) * openSpacing
            local position = latticeKey(1, gx, gy, code)
            if x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4] and not positions[position] then
              if coverAt(x, y) == 'ground' and keyHash(seed + 100, position) % 1000 / 1000 < (chanceOf.ground or 0) then
                positions[position] = true
                candidates[#candidates + 1] = {x = x, y = y, hash = h, key = position, kind = 'ground'}
              end
            end
          end
          pause()
        end
      end
      spread(candidates, limit, 25, function(candidate)
        local x, y, h = candidate.x, candidate.y, candidate.hash
        local z = ground(x, y)
        local elevation = rawHeight(x, y) - (options.seaLevel or 20)
        local _, _, nz = groundNormal(x, y)
        local elevationCap = elevationOf and elevationOf[candidate.kind]
        local clearance = prefix == 'grass' and 2.2 or 3.5
        if not (nz >= minNz and (not elevationCap or elevation < elevationCap) and (not sea or z > sea) and not blocked(x, y, clearance)) then
          return false
        end
        -- another climate's tufts, shrubs and stones (bio.decor), or none at all
        local here, lo, hi = shapes, scaleMin, scaleMax
        local p = bio.on and bio.at(x, y)
        if p then
          here = bio.decor(p, prefix, candidate.kind, elevation, shapes, x, y)
          if not here then return false end
          if here ~= shapes and prefix == 'grass' then lo, hi = .3, .6 end   -- dry tufts stand taller
        end
        local shape = here[h % #here + 1]
        local scale
        if prefix == 'grass' then
          -- scaleMin/scaleMax are the blade height in metres, not a raw multiplier.
          local mesh = VEG.grassMesh[shape]
          local span = mesh and mesh.span or 0.26
          local want = lo + (keyHash(seed + 200, candidate.key) % 1000) / 1000 * (hi - lo)
          scale = want / span
          z = z - (mesh and mesh.bottom or 0) * scale
        else
          scale = lo + (keyHash(seed + 200, candidate.key) % 1000) / 1000 * (hi - lo)
          if prefix == 'rock' and h % 5 == 0 then shape = here[#here]; scale = scale * .8 end
        end
        static(prefix .. '_' .. candidate.key, shape, x, y, z, h % 6283 / 1000, scale)
        return true
      end)
    end
    local function opt(name, default, cap)
      local value = options[name]
      if value == nil then value = default end
      return math.max(0, math.min(cap, value))
    end
    local maxGrass = opt('maxGrass', 4000, 4800)
    local maxRocks = opt('maxRocks', 80, 200)
    local maxUnder = opt('maxUnderstory', 220, 400)
    -- Lawns, parks, meadows and open ground: one descriptor per 8 m cell. detail.lua
    -- expands it into a short-grass carpet only while that cell is live. Dry and cold
    -- climates keep their own scatter (bio.layers); these kinds are not in it.
    local function lawnCarpet()
      if distant or maxGrass <= 0 then return end
      local cell, step = 8, 2
      local lawn = {ground = true, park = true, meadow = true, residential = true}
      local function climate(x, y)
        if not bio.on then return true end
        local p = bio.at(x, y)
        if not p then return true end
        local g = p.group
        if g ~= 'temperate' and g ~= 'boreal' and g ~= 'rainforest' then return false end
        return rawHeight(x, y) - bio.sea < bio.treeline(p) - 80
      end
      local shapes = {VEG.grass[1], VEG.grass[2], VEG.grass[3]}
      local mesh = VEG.grassMesh
      local spans = {mesh[shapes[1]].span, mesh[shapes[2]].span, mesh[shapes[3]].span}
      local bottoms = {mesh[shapes[1]].bottom, mesh[shapes[2]].bottom, mesh[shapes[3]].bottom}
      local x0, y0 = floor(rect[1] / cell) * cell, floor(rect[2] / cell) * cell
      for oy = y0, rect[4] - 1e-6, cell do
        for ox = x0, rect[3] - 1e-6, cell do
          if ox >= rect[1] and ox < rect[3] and oy >= rect[2] and oy < rect[4] and climate(ox + 4, oy + 4) then
            local samples, anchor = {}, nil
            for sy = 0, 3 do
              for sx = 0, 3 do
                local x, y = ox + sx * step + 1, oy + sy * step + 1
                if x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4] and lawn[coverAt(x, y)] then
                  local z = ground(x, y)
                  local nx, ny, nz = groundNormal(x, y)
                  if nz >= .72 and (not sea or z > sea) and not blocked(x, y, 2.4) then
                    local n = #samples
                    samples[n + 1], samples[n + 2] = sy * 4 + sx, z
                    samples[n + 3] = nz > 1e-4 and -nx / nz or 0
                    samples[n + 4] = nz > 1e-4 and -ny / nz or 0
                    if not anchor then anchor = {x, y, z} end
                  end
                end
              end
            end
            if anchor then
              static(string.format('lawn_%d_%d', floor(ox), floor(oy)), shapes[1], anchor[1], anchor[2], anchor[3], 0, 1)
              scene.items[#scene.items].grassPatch = {
                x = ox, y = oy, shapes = shapes, spans = spans, bottoms = bottoms, samples = samples}
            end
          end
          if ox % 64 == 0 then pause() end
        end
        pause()
      end
    end
    -- Forest floor and mapped fields stay a thin scatter. Lawn kinds are absent here,
    -- so a town tile does not plant a second tuft on the carpet.
    scatter('grass', {farmland = 8, heath = 7, forest = 12, orchard = 5, vineyard = 9},
      {farmland = .35, heath = .5, forest = .2, orchard = .55, vineyard = .28},
      VEG.grass, maxGrass, 0, 0.20, 0.30, .72, {forest = treeline + 80})
    lawnCarpet()
    scatter('bush', {forest = 14, park = 18},
      {forest = .4, park = .22},
      VEG.have('bush'), maxUnder, 0, .85, 1.3, .72, {forest = treeline + 80})
    -- clover and daisy patches (2.3 and 1.5 m across) and ferns under the trees
    local maxFlowers = math.floor(maxGrass * .12)
    scatter('flower', {meadow = 7, park = 9, ground = 12, orchard = 10, residential = 11},
      {meadow = .45, park = .3, ground = .2, orchard = .3, residential = .2},
      VEG.have('flowers'), maxFlowers, 0, .8, 1.2, .8, {meadow = treeline})
    scatter('fern', {forest = 9}, {forest = .3},
      VEG.have('ferns'), math.floor(maxGrass * .1), 0, .7, 1.2, .72, {forest = treeline})
    scatter('rock', {bare_rock = 11, scree = 8}, {bare_rock = .72, scree = .84},
      VEG.rocks, maxRocks, math.min(16, maxRocks), .55, 1.25, .45, nil)
    -- Slopes too steep for trees still had no stones unless OSM tagged bare_rock or scree.
    -- Same sorted lattice near and far, so the far handful stays inside the near list.
    local function scatterSlopeRocks()
      local limit = distant and math.min(16, maxRocks) or maxRocks
      if limit <= 0 then return end
      local spacing, candidates, positions = 16, {}, {}
      for gy = floor(rect[2] / spacing) - 1, math.ceil(rect[4] / spacing) do
        for gx = floor(rect[1] / spacing) - 1, math.ceil(rect[3] / spacing) do
          if gx % 8 == 0 then pause() end
          local h = ihash(21, gx, gy)
          local x = (gx + .5 + (h % 1000 / 1000 - .5) * .5) * spacing
          local y = (gy + .5 + (floor(h / 1000) % 1000 / 1000 - .5) * .5) * spacing
          if x >= rect[1] and x < rect[3] and y >= rect[2] and y < rect[4] then
            local _, _, nz = groundNormal(x, y)
            local kind = coverAt(x, y)
            -- 0.94 is about 20°. Rounded Carpathian hills were steeper than flat ground
            -- and gentler than 45°, so the old 0.7 gate never placed a stone on them.
            if nz < .94 and nz >= .25 and kind ~= 'water' and kind ~= 'paved' and kind ~= 'residential' then
              local position = latticeKey(2, gx, gy, 160)
              local steep = (.94 - nz) / .69
              if not positions[position] and keyHash(22, position) % 1000 / 1000 < (.45 + .55 * steep) then
                positions[position] = true
                candidates[#candidates + 1] = {x = x, y = y, hash = h, key = position}
              end
            end
          end
        end
        pause()
      end
      spread(candidates, limit, 25, function(candidate)
        local x, y, h = candidate.x, candidate.y, candidate.hash
        local z = ground(x, y)
        if not ((not sea or z > sea) and not blocked(x, y)) then return false end
        local scale = .7 + (keyHash(23, candidate.key) % 1000) / 1000 * .7
        -- the climate's stones: desert sandstone, mountain granite and limestone
        local p, set = bio.on and bio.at(x, y), VEG.rocks
        if p and (p.arid or p.group == 'tundra' or p.group == 'ice' or rawHeight(x, y) - bio.sea > bio.treeline(p) - 100) then
          -- rocky climates: no stone on a cliff face (it hung in the air), and the far ring's handful
          -- only on gentle ground (its coarse mesh runs tens of metres off a steep slope)
          local _, _, nz = bio.normal(x, y)
          if nz < .55 or (distant and nz < .9) then return false end
        end
        if p then
          local e = rawHeight(x, y) - bio.sea
          set = bio.decor(p, 'rock', 'ground', e, VEG.rocks)
          if e > p.snowline - 400 and h % 6 ~= 0 then
            local surface = surfaceKind(x, y)
            if surface == 'snow' or surface == 'glacier' then return false end
          end
        end
        local shape = set[h % #set + 1]
        if h % 5 == 0 then shape = set[#set]; scale = scale * .8 end
        static('srock_' .. candidate.key, shape, x, y, z, h % 6283 / 1000, scale)
        return true
      end)
    end
    scatterSlopeRocks()
    -- deserts, steppes, the alpine belt and the tundra: their own tufts and many more stones
    -- (detail.lua shows the nearest within its budget)
    bio.layers(math.floor(maxGrass * .6), math.min(600, maxRocks * 3), spread)
  end
  mark('trees')
  local sceneManifest = manifest(scene, 'scene')
  sceneManifest.parking = parking
  if distant then
    sceneManifest.layer = layerName
    for _, item in ipairs(sceneManifest.items) do
      item.decor, item.layer, item.collision = true, layerName, 'None'
    end
    return roadManifest, manifest({used = {}, items = {}}, 'scene'), sceneManifest, nav
  end
  return roadManifest, sceneManifest, nil, nav
end

M.build = build
M.YARD = YARD
M.triangulate = triangulate
M.clip = clip
M.EDGE_MAPS = EDGE_MAPS
M.STREET_PROPS = VEG.props
return M
