"""Look of the fast generator: materials from the game's own tileable textures, UV scale per
surface kind, and a facade per building. No textures are shipped; all paths are BeamNG's
/assets (resolved to their .dds). Kinds are the Mesh face groups; material = 'e2rf_' + kind."""
import math
import os
import zlib
import nature
import retail

TEXTURES = {
    'asphalt': {
        'baseColorMap': '/assets/materials/tileable/road/m_road_asphalt_rough_01/t_road_asphalt_rough_01_b.color.png',
        'normalMap': '/assets/materials/tileable/road/m_road_asphalt_rough_01/t_road_asphalt_rough_01_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/road/m_road_asphalt_rough_01/t_road_asphalt_rough_01_r.data.png',
        'ambientOcclusionMap': '/assets/materials/tileable/road/m_road_asphalt_rough_01/t_road_asphalt_rough_01_ao.data.png',
    },
    'asphalt_major': {
        'baseColorMap': '/assets/materials/tileable/road/m_asphalt_new_01/t_asphalt_02_b.color.png',
        'normalMap': '/assets/materials/tileable/road/m_asphalt_new_01/t_asphalt_02_nm.normal.png',
        'ambientOcclusionMap': '/assets/materials/tileable/road/m_asphalt_new_01/t_asphalt_02_ao.data.png',
    },
    'sidewalk': {
        'baseColorMap': '/assets/materials/tileable/concrete/sidewalk1/t_sidewalk1_b.color.png',
        'normalMap': '/assets/materials/tileable/concrete/sidewalk1/t_sidewalk1_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/concrete/sidewalk1/t_sidewalk1_r.data.png',
    },
    'grass': {
        'baseColorMap': '/assets/materials/terrain/grass/groundmesh_grass2/groundmesh_grass_b.color.png',
    },
    'concrete': {
        'baseColorMap': '/assets/materials/tileable/concrete/concrete_plain/t_concrete_plain_b.color.png',
        'normalMap': '/assets/materials/tileable/concrete/concrete_plain/t_concrete_plain_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/concrete/concrete_plain/t_concrete_plain_r.data.png',
        'ambientOcclusionMap': '/assets/materials/tileable/concrete/concrete_plain/t_concrete_plain_ao.data.png',
    },
    'panel': {
        'baseColorMap': '/assets/materials/tileable/concrete/slabs_brutalist/t_slabs_brutalist_b.color.png',
        'normalMap': '/assets/materials/tileable/concrete/slabs_brutalist/t_slabs_brutalist_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/concrete/slabs_brutalist/t_slabs_brutalist_r.data.png',
        'ambientOcclusionMap': '/assets/materials/tileable/concrete/slabs_brutalist/t_slabs_brutalist_ao.data.png',
    },
    'precast': {
        'baseColorMap': '/assets/materials/tileable/concrete/concrete_precast1/t_concrete_precast1_b.color.png',
        'normalMap': '/assets/materials/tileable/concrete/concrete_precast1/t_concrete_precast1_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/concrete/concrete_precast1/t_concrete_precast1_r.data.png',
        'ambientOcclusionMap': '/assets/materials/tileable/concrete/concrete_precast1/t_concrete_precast1_ao.data.png',
    },
    'brick': {
        'baseColorMap': '/assets/materials/tileable/brick/brick_plain/t_brick_plain_b.color.png',
        'normalMap': '/assets/materials/tileable/brick/brick_plain/t_bricks_red_01_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/brick/brick_plain/t_bricks_red_01_r.data.png',
        'ambientOcclusionMap': '/assets/materials/tileable/brick/brick_plain/t_bricks_red_01_ao.data.png',
    },
    'brick_red': {
        'baseColorMap': '/assets/materials/tileable/brick/brick_plain/t_bricks_red_01_b.color.png',
        'normalMap': '/assets/materials/tileable/brick/brick_plain/t_bricks_red_01_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/brick/brick_plain/t_bricks_red_01_r.data.png',
        'ambientOcclusionMap': '/assets/materials/tileable/brick/brick_plain/t_bricks_red_01_ao.data.png',
    },
    'brick_white': {
        'baseColorMap': '/assets/materials/tileable/brick/t_brick_white_paint_01/t_brick_white_paint_01_b.color.png',
        'normalMap': '/assets/materials/tileable/brick/t_brick_white_paint_01/t_brick_white_paint_01_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/brick/t_brick_white_paint_01/t_brick_white_paint_01_r.data.png',
        'ambientOcclusionMap': '/assets/materials/tileable/brick/t_brick_white_paint_01/t_brick_white_paint_01_ao.data.png',
    },
    'plaster': {
        'baseColorMap': '/assets/materials/tileable/plaster/m_plaster_worn_01/t_plaster_worn_01_b.color.png',
        'normalMap': '/assets/materials/tileable/plaster/m_plaster_worn_01/t_plaster_worn_01_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/plaster/m_plaster_worn_01/t_plaster_worn_01_r.data.png',
        'ambientOcclusionMap': '/assets/materials/tileable/plaster/m_plaster_worn_01/t_plaster_worn_01_ao.data.png',
    },
    'stucco': {
        'baseColorMap': '/assets/materials/tileable/plaster/m_stucco_white/t_stucco_white_b.color.png',
        'normalMap': '/assets/materials/tileable/plaster/m_stucco_white/t_stucco_white_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/plaster/m_stucco_white/t_stucco_white_r.data.png',
        'ambientOcclusionMap': '/assets/materials/tileable/plaster/m_stucco_white/t_stucco_white_ao.data.png',
    },
    'glass': {
        'baseColorMap': '/assets/materials/tileable/glass/modernstripwindow/t_window_strips_01_b.color.png',
        'normalMap': '/assets/materials/tileable/glass/modernstripwindow/t_window_strips_01_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/glass/modernstripwindow/t_window_strips_01_r.data.png',
    },
    'windows': {
        'baseColorMap': '/assets/materials/tileable/glass/windows1/t_bld_ind_windows_b.color.png',
        'normalMap': '/assets/materials/tileable/glass/windows1/t_bld_ind_windows_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/glass/windows1/t_bld_ind_windows_r.data.png',
    },
    'block': {
        'baseColorMap': '/assets/materials/tileable/brick/ind_blockwall/t_concrete_cinderblock_01_b.color.png',
        'normalMap': '/assets/materials/tileable/brick/ind_blockwall/t_concrete_cinderblock_01_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/brick/ind_blockwall/t_concrete_cinderblock_01_r.data.png',
        'ambientOcclusionMap': '/assets/materials/tileable/brick/ind_blockwall/t_concrete_cinderblock_01_ao.data.png',
    },
    'roof': {
        'baseColorMap': '/assets/materials/tileable/roofing/asphalt_roof/t_asphalt_roof_b.color.png',
        'normalMap': '/assets/materials/tileable/roofing/asphalt_roof/t_asphalt_roof_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/roofing/asphalt_roof/t_asphalt_roof_r.data.png',
        'ambientOcclusionMap': '/assets/materials/tileable/roofing/asphalt_roof/t_asphalt_roof_ao.data.png',
    },
    'roof_tile': {
        'baseColorMap': '/assets/materials/tileable/roofing/t_italy_bld_roof_tiles/t_italy_bld_roof_tiles_b.color.png',
        'normalMap': '/assets/materials/tileable/roofing/t_italy_bld_roof_tiles/t_italy_bld_roof_tiles_nm.normal.png',
        'roughnessMap': '/assets/materials/tileable/roofing/t_italy_bld_roof_tiles/t_italy_bld_roof_tiles_r.data.png',
    },
    'roof_metal': {
        'baseColorMap': '/assets/materials/tileable/metal/corrugated_modern/t_metal_corrugated_01_b.color.png',
        'normalMap': '/assets/materials/tileable/metal/corrugated_modern/t_metal_corrugated_01_nm.normal.png',
        'ambientOcclusionMap': '/assets/materials/tileable/metal/corrugated_modern/t_metal_corrugated_01_ao.data.png',
    },
    'dirt': {
        'baseColorMap': '/assets/materials/terrain/soil/dirt_crumbly/t_dirt_crumbly_b.color.png',
        'normalMap': '/assets/materials/terrain/soil/dirt_crumbly/t_dirt_crumbly_nm.normal.png',
        'roughnessMap': '/assets/materials/terrain/soil/dirt_crumbly/t_dirt_crumbly_r.data.png',
        'ambientOcclusionMap': '/assets/materials/terrain/soil/dirt_crumbly/t_dirt_crumbly_ao.data.png',
    },
}


def _maps(folder, stem, *suffixes):
    """A stock material's maps by suffix: b, nm, r, ao, o."""
    names = {'b': ('baseColorMap', 'color'), 'nm': ('normalMap', 'normal'), 'r': ('roughnessMap', 'data'),
             'ao': ('ambientOcclusionMap', 'data'), 'o': ('opacityMap', 'data')}
    return {names[s][0]: f'{folder}/{stem}_{s}.{names[s][1]}.png' for s in suffixes}


# Road decals and the curb from the game's decal-road and trim sets, laid out along the road
# by the generator (uv mode 'strip': u across, v along). The worn line is the one East Coast
# paints 0.15 m wide with a 6.4 m repeat; the edges are 2 m wide with an 8 m repeat, the
# asphalt side at u = 0. The curb is the top row of the trim sheet. Of the game's grass edges
# t_road_edge_grass_02 is nearest the photo ground (linear means .107 .126 .051 against .090
# .131 .037) and fades out on both sides.
_DR = '/assets/materials/decalroad'
TEXTURES['line_worn'] = _maps(f'{_DR}/lines/line_white_damage_01', 't_line_white_damaged_01', 'b', 'nm', 'r', 'ao', 'o')
TEXTURES['edge_grass'] = _maps(f'{_DR}/vegetation/dirt_road_edge_grassy_d', 't_road_edge_grass_02', 'b', 'nm', 'r', 'ao', 'o')
TEXTURES['edge_dirt'] = _maps(f'{_DR}/asphalt/m_asphalt_dirt_edge', 't_asphalt_dirt_edge_02', 'b', 'nm', 'r', 'ao', 'o')
TEXTURES['curb_trim'] = _maps('/assets/materials/trim/concrete/m_sidewalk_curb_trim_01', 't_sidewalk_curb_trim_01',
                              'b', 'nm', 'r', 'ao')

# kind: (texture, fallback colour, groundType, metres per texture repeat, uv mode)
# uv mode 'plan' projects from above; 'wall' runs u along the wall and v up it; 'strip' runs
# u across a road strip and v along it (the generator's own UVs).
KINDS = {
    'road':        ('asphalt',       [.18, .19, .20, 1], 'ASPHALT', 6.0, 'plan'),
    'road_major':  ('asphalt_major', [.16, .17, .18, 1], 'ASPHALT', 6.0, 'plan'),
    'sidewalk':    ('sidewalk',      [.55, .55, .52, 1], 'ASPHALT', 3.0, 'plan'),
    'mark':        ('line_worn',     [.92, .91, .86, 1], 'ASPHALT', 6.4, 'strip'),
    'mark_yellow': ('line_worn',     [.93, .74, .12, 1], 'ASPHALT', 6.4, 'strip'),
    'ground':      ('grass',         [.29, .36, .22, 1], 'GRASS',   8.0, 'plan'),
    'paved':       ('concrete',      [.45, .45, .43, 1], 'ASPHALT', 6.0, 'plan'),
    'water':       (None,            [.12, .29, .38, 1], 'MUD',     8.0, 'plan'),
    'roof':        ('roof',          [.32, .31, .30, 1], 'ROCK',    6.0, 'plan'),
    'forest':      ('grass',         [.20, .30, .16, 1], 'GRASS',   8.0, 'plan'),
    'curb':        ('curb_trim',     [.70, .70, .68, 1], 'ASPHALT', 2.0, 'strip'),
    'edge_grass':  ('edge_grass',    [.29, .36, .22, 1], 'GRASS',   8.0, 'strip'),
    'edge_dirt':   ('edge_dirt',     [.45, .40, .32, 1], 'DIRT',    8.0, 'strip'),
}
# What these kinds were before the decals (texture or None for the flat colour): the material
# world.lua loads when the game lacks a map (an older BeamNG). The generator draws no edge
# strips then (generator.lua decalsPresent).
DECAL_FALLBACK = {'mark': None, 'mark_yellow': None, 'curb': 'concrete', 'edge_grass': None, 'edge_dirt': None}
EDGES = ('edge_grass', 'edge_dirt')
ART = '/e2r_stream/fast-art/v10'      # fast_art.ensure writes the facades there
WALLS = ('panel', 'precast', 'brick', 'brick_red', 'brick_white', 'plaster', 'stucco', 'glass', 'windows', 'block')
for w in WALLS:
    # walls carry their own UVs (one 3 m window cell per repeat, floors from the base)
    KINDS['wall_' + w] = (w, [.58, .55, .49, 1], 'ROCK', 3.0, 'wall')
# photographs written into the art folder by fast_art (ambientCG paving and earth, Panelka fence)
TEXTURES['paving'] = {'baseColorMap': f'{ART}/real/paving.color.png', 'normalMap': f'{ART}/real/paving.normal.png'}
TEXTURES['trodden'] = {'baseColorMap': f'{ART}/real/trodden.color.png', 'normalMap': f'{ART}/real/trodden.normal.png'}
TEXTURES['fence_po2'] = {'baseColorMap': f'{ART}/real/fence_po2.color.png'}
# Asphalt and line paint from CC0 photos (fast_art.road_sheets). Every asphalt has the same base,
# Poly Haven's 30 m aerial photo of a street over the road's repeat (ROAD_M, generator.lua
# COVER_SCALE), and its own detail over DETAIL_M: Poly Haven asphalt_01 in town, ambientCG
# Asphalt026C worn, Asphalt025C fresh. The game adds the detail maps to the base, linear (base +
# (2 * detail - 1) * strength); detailScale is the detail's UVs over the base's.
ROAD_M, DETAIL_M = 30.0, 2.0
_BASE = {'baseColorMap': f'{ART}/real/road_base.color.png', 'normalMap': f'{ART}/real/road_base.normal.png',
         'roughnessMap': f'{ART}/real/road_base.data.png', 'ambientOcclusionMap': f'{ART}/real/road_base_ao.data.png',
         'detailScale': [ROAD_M / DETAIL_M] * 2, 'detailNormalMapStrength': 1.0, 'detailRoughnessMapStrength': .15}
# grain strength: at .12 in town the stones speckled white a metre from the camera (park-vis-03)
for _name, _grain in (('road_city', .08), ('road_worn', .10), ('road_fresh', .05)):
    TEXTURES[_name] = {**_BASE, 'detailMap': f'{ART}/real/{_name}_dc.data.png', 'detailBaseColorMapStrength': _grain,
                       'detailNormalMap': f'{ART}/real/{_name}_dn.normal.png',
                       'roughnessDetailMap': f'{ART}/real/{_name}_dr.data.png'}
TEXTURES['line_paint'] = {'baseColorMap': f'{ART}/real/line.color.png', 'normalMap': f'{ART}/real/line.normal.png',
                          'roughnessMap': f'{ART}/real/line.data.png', 'opacityMap': f'{ART}/real/line_o.data.png'}
for _kind, _tex in (('road', 'road_city'), ('road_major', 'road_fresh'), ('mark', 'line_paint'),
                    ('mark_yellow', 'line_paint')):
    KINDS[_kind] = (_tex,) + KINDS[_kind][1:]
# the lines are our own art now: no older game lacks them
for _kind in ('mark', 'mark_yellow'):
    DECAL_FALLBACK.pop(_kind)
TEXTURES['fence_mesh'] = {
    'baseColorMap': '/assets/materials/tileable/metal/chainlink/t_chainlink_fence_b.color.png',
    'normalMap': '/assets/materials/tileable/metal/chainlink/t_chainlink_fence_nm.normal.png',
    'opacityMap': f'{ART}/real/chainlink_o.data.png',
}
CHAINLINK_OPACITY = '/assets/materials/tileable/metal/chainlink/t_chainlink_fence_o.data.png'
TEXTURES['car'] = {'baseColorMap': f'{ART}/real/cars.color.png'}
# material fields beyond the stage: see-through fences, both sides of a single quad
# The chain-link opacity mips keep the share of texels over CHAINLINK_MIP_REF (fast_dds). The
# material tests at 30: at 80 the wire dropped out after bilinear filtering and BC1 from ~6 m
# to ~35 m, so a fence vanished as the car came close (night-fence-02: ref 80 gone at 8 and
# 20 m, ref 30 drawn at 8, 20 and 40 m from the same DDS).
CHAINLINK_MIP_REF = 80
EXTRA = {'fence_mesh': {'alphaTest': True, 'alphaRef': 30, 'doubleSided': True, 'castShadows': False},
         'fence_wall': {'doubleSided': True}}
# Road decals are cut by their opacity, not blended: a translucent ProceduralMesh is lit in the
# forward pass, and an edge came out 0.8 of the verge in the sun and 1.1 in the shade beside it
# (decals-trunk-01). The game's own decal roads draw into the deferred buffers instead.
for _k in ('mark', 'mark_yellow') + EDGES:
    EXTRA[_k] = {'alphaTest': True, 'alphaRef': 77, 'castShadows': False}
# photo facades (fast_photo: Panelka pack): a 6 m repeat, the II-68 loggia sheet 33 m
import fast_photo as _photo
for w, (_family, _colour, _metres) in _photo.PHOTO_WALLS.items():
    KINDS['wall_' + w] = (None, [*_colour, 1], 'ROCK', _metres, 'wall')
# roofs: the parapet's inner face and pitched tile roofs of houses
KINDS['parapet'] = ('concrete', [.55, .55, .53, 1], 'ROCK', 3.0, 'wall')
KINDS['roof_tile'] = ('roof_tile', [.45, .22, .16, 1], 'ROCK', 2.0, 'roof')
KINDS['roof_metal'] = ('roof_metal', [.36, .42, .40, 1], 'ROCK', 2.0, 'roof')
# Post-Soviet roofs and outbuildings from the game's tileable set: asbestos-cement slate (шифер)
# on the light corrugation, painted metal tile on the grey slates sheet, garage doors, metal
# cladding of sheds and warehouses, a plinth. Uv mode 'roof': u along the ridge, v down the
# slope (generator.lua pitchedRoof).
_T = '/assets/materials/tileable'
TEXTURES['sheet'] = _maps(f'{_T}/metal/corrugation', 't_corrugation', 'b', 'nm', 'r', 'ao')
TEXTURES['metal_tile'] = _maps(f'{_T}/roofing/m_roof_slates_ochre', 't_roof_slates_ochre', 'b', 'nm', 'r', 'ao')
TEXTURES['rollup'] = _maps(f'{_T}/metal/t_italy_bld_rollupdoor', 't_italy_bld_rollupdoor', 'b', 'nm', 'r')
TEXTURES['rust_door'] = {'baseColorMap': f'{_T}/metal/WareHouse_door/Warehouse_door_d.png',
                         'normalMap': f'{_T}/metal/WareHouse_door/Warehouse_door_n.png'}
TEXTURES['cladding'] = _maps(f'{_T}/metal/m_metal_wall_corrugate', 't_metal_wall_corrugated', 'b', 'nm', 'r', 'ao')
TEXTURES['tin'] = _maps(f'{_T}/metal/m_corrugated_tin_v1', 't_corrugated_tin_v1', 'b', 'nm', 'r')
# PBR maps only: the legacy cement_coating with its old-style _n normal rendered the plinth near
# black in the shade (bld-hatne-03)
TEXTURES['plinth'] = _maps(f'{_T}/concrete/concrete_painted', 't_concrete_painted', 'b', 'nm', 'r')
TEXTURES['boards'] = _maps(f'{_T}/wood/weatherboards', 't_weatherboards', 'b', 'nm', 'r', 'ao')
KINDS['roof_sheet'] = ('sheet', [.62, .62, .60, 1], 'ROCK', 1.75, 'roof')
for _c, _rgb in (('red', [.44, .15, .13]), ('brown', [.29, .20, .18]), ('green', [.13, .28, .21])):
    KINDS['roof_mtile_' + _c] = ('metal_tile', [*_rgb, 1], 'METAL', 1.4, 'roof')
KINDS['door_garage'] = ('rollup', [.42, .42, .41, 1], 'METAL', 3.0, 'wall')
KINDS['door_rust'] = ('rust_door', [.30, .26, .22, 1], 'METAL', 3.0, 'wall')
KINDS['clad_metal'] = ('cladding', [.69, .71, .74, 1], 'METAL', 3.0, 'wall')
KINDS['clad_tin'] = ('tin', [.55, .45, .38, 1], 'METAL', 3.0, 'wall')
KINDS['plinth'] = ('plinth', [.46, .45, .42, 1], 'ROCK', 3.0, 'wall')
# the gables of pitched roofs: boards (a facade's windows ran on into the gable askew)
KINDS['gable'] = ('boards', [.58, .52, .44, 1], 'ROCK', 1.5, 'wall')
# What the building kinds fall back to in a game without one of their maps (world.lua)
BUILDING_FALLBACK = {'roof_sheet': 'roof_metal', 'roof_mtile_red': 'roof_tile', 'roof_mtile_brown': 'roof_tile',
                     'roof_mtile_green': 'roof_tile', 'door_garage': 'block', 'door_rust': 'block',
                     'clad_metal': 'block', 'clad_tin': 'block', 'plinth': 'concrete', 'gable': None}
FALLBACK = {**DECAL_FALLBACK, **BUILDING_FALLBACK}
# Pitched roofs are seen from below under their eaves (generator.lua pitchedRoof)
ROOFS = ('roof_tile', 'roof_metal', 'roof_sheet', 'roof_mtile_red', 'roof_mtile_brown', 'roof_mtile_green')
for _k in ROOFS:
    EXTRA[_k] = {'doubleSided': True}
# Houses of one or two floors (generator.lua BLD.house): plain walls from the game's tileable set
# with windows and a door as their own quads from its atlases, so a village is not one photo
# facade with the same window rhythm. Colours are set below (TINT, by _factor).
TEXTURES['hw_stucco'] = _maps(f'{_T}/plaster/stucco1_white', 't_stucco1_white', 'b', 'nm', 'r', 'ao')
TEXTURES['hw_aged'] = _maps(f'{_T}/plaster/m_worn_brushed_plaster', 't_worn_brushed_plaster', 'b', 'nm', 'r', 'ao')
_brick = _maps(f'{_T}/brick/brick_painted', 't_brick_plain', 'nm', 'r', 'ao')
TEXTURES['hw_brick'] = {'baseColorMap': f'{_T}/brick/brick_plain/t_brick_plain_b.color.png', **_brick}
TEXTURES['hw_silicate'] = {'baseColorMap': f'{_T}/brick/brick_painted/t_brick_painted_b.color.png', **_brick}
TEXTURES['hw_siding'] = {'baseColorMap': f'{_T}/wood/eca_bld_woodcladding_new/eca_bld_woodcladding_new_d.png',
                         'normalMap': f'{_T}/wood/eca_bld_woodcladding_new/eca_bld_woodcladding_new_n.png'}
TEXTURES['hw_wood'] = _maps(f'{_T}/wood/ut_bld_wood_old', 't_ut_bld_wood_old', 'b', 'nm', 'r', 'ao')
TEXTURES['hw_oldbrick'] = _maps(f'{_T}/brick/t_italy_bld_old_bricks', 't_italy_bld_old_bricks', 'b', 'nm', 'r')
TEXTURES['hw_flatbrick'] = _maps(f'{_T}/brick/t_italy_bld_big_flat_bricks', 't_italy_bld_big_flat_bricks', 'b', 'nm', 'r')
TEXTURES['hw_stone'] = _maps(f'{_T}/brick/stone_brick_irregular', 't_stone_brick_irregular', 'b', 'nm', 'r', 'ao')
TEXTURES['win_pvc'] = _maps('/assets/materials/trim/plastic/windows_doors', 't_windows_doors', 'b', 'nm', 'r', 'ao')
TEXTURES['win_wood'] = _maps('/assets/materials/atlas/t_italy_bld_windows', 't_italy_bld_windows', 'b', 'nm', 'r')
TEXTURES['door_house'] = {'baseColorMap': '/assets/materials/atlas/m_door/doors1_d.png',
                          'normalMap': '/assets/materials/atlas/m_door/doors1_n.png'}
HOUSE_WALLS = {   # kind: (texture, flat colour for a game without the maps)
    'hw_white': ('hw_stucco', [.86, .85, .82]), 'hw_yellow': ('hw_stucco', [.78, .66, .38]),
    'hw_blue': ('hw_stucco', [.55, .64, .72]), 'hw_green': ('hw_stucco', [.6, .7, .55]),
    'hw_pink': ('hw_stucco', [.78, .64, .6]), 'hw_aged': ('hw_aged', [.6, .57, .48]),
    'hw_brick_red': ('hw_brick', [.55, .32, .26]), 'hw_silicate': ('hw_silicate', [.82, .8, .76]),
    'hw_siding': ('hw_siding', [.72, .68, .58]), 'hw_wood': ('hw_wood', [.36, .3, .24]),
    'hw_oldbrick': ('hw_oldbrick', [.48, .28, .22]), 'hw_flatbrick': ('hw_flatbrick', [.62, .4, .32]),
    'hw_stone': ('hw_stone', [.62, .6, .56]), 'hw_boards': ('boards', [.72, .64, .5]),
}
for _k, (_tex, _rgb) in HOUSE_WALLS.items():
    KINDS[_k] = (_tex, [*_rgb, 1], 'ROCK', 3.0, 'wall')
KINDS['win_pvc'] = ('win_pvc', [.22, .26, .3, 1], 'GLASS', 1.0, 'wall')
KINDS['win_wood'] = ('win_wood', [.3, .22, .15, 1], 'GLASS', 1.0, 'wall')
KINDS['door_house'] = ('door_house', [.32, .24, .18, 1], 'WOOD', 1.0, 'wall')
KINDS['plinth_brown'] = ('plinth', [.36, .22, .18, 1], 'ROCK', 3.0, 'wall')
# A house chimney shares the red-brick maps. One slot for the whole tile, not a texture per house.
KINDS['chimney'] = ('hw_brick', [.42, .24, .20, 1], 'ROCK', 1.6, 'wall')
# flat colours in a game without the maps: every house kind keeps its look's colour
BUILDING_FALLBACK.update({k: None for k in (*HOUSE_WALLS, 'win_pvc', 'win_wood', 'door_house', 'chimney')})
BUILDING_FALLBACK['plinth_brown'] = 'concrete'
# Facade details (generator.lua BLD.details, options.experimentalDetail): galvanised downpipes
# as a flat grey, air-conditioner boxes on the game's metal cladding
KINDS['pipe'] = (None, [.50, .51, .52, 1], 'METAL', 1.0, 'wall')
# Address plates (generator.lua BLD.addressPlate, options.experimentalDetail): a dark blue plate
# and white letters cut from a glyph atlas (fast_art.glyph_art: Noto Sans Mono Bold, OFL, from the
# game's own UI fonts), GLYPHS_PER_ROW to a row, row 0 at the top before the flip. The generator
# keeps the same string (BLD.GLYPHS).
GLYPHS = "0123456789/-.,'’№ ()АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯабвгґдеєжзиіїйклмнопрстуфхцчшщьюяЁЭЪЫёэъыABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
GLYPHS_PER_ROW = 16
TEXTURES['glyphs'] = {'baseColorMap': f'{ART}/real/glyphs.color.png', 'opacityMap': f'{ART}/real/glyphs_o.data.png'}
KINDS['glyphs'] = ('glyphs', [.96, .96, .94, 1], 'METAL', 1.0, 'wall')
KINDS['plate'] = (None, [.08, .18, .40, 1], 'METAL', 1.0, 'wall')
# a lift gate's red stripes (generator.lua BLD.liftGate); the white ones are the dish metal
KINDS['paint_red'] = (None, [.72, .10, .08, 1], 'METAL', 1.0, 'wall')
# a shop's sign board under its real name (generator.lua BLD.storeFront)
KINDS['fascia'] = (None, [.11, .12, .13, 1], 'METAL', 1.0, 'wall')
# drawn road signs (generator.lua SIGNS.drawLimit, drawTown): the white of the board, black letters
KINDS['sign_white'] = (None, [.9, .9, .88, 1], 'METAL', 1.0, 'wall')
KINDS['glyphs_dark'] = ('glyphs', [.03, .03, .035, 1], 'METAL', 1.0, 'wall')
EXTRA['glyphs_dark'] = {'alphaTest': True, 'alphaRef': 110, 'castShadows': False}
# a traffic light's lenses (generator.lua SIGNS.lamp): the dark glass, and what signals.lua shows lit
KINDS['lens_dark'] = (None, [.05, .05, .055, 1], 'METAL', 1.0, 'wall')
LENS = {'lens_red': (1., .09, .05), 'lens_yellow': (1., .62, .05), 'lens_green': (.1, 1., .42)}
for _kind, _glow in LENS.items():
    KINDS[_kind] = (None, [*_glow, 1], 'METAL', 1.0, 'wall')
EXTRA['glyphs'] = {'alphaTest': True, 'alphaRef': 110, 'castShadows': False}
# covers in the asphalt (generator.lua ROADS.covers): the Italy manhole sheet and the grid
# drain, cut by their opacity like the lines; drawn only where the game has these maps
TEXTURES['manhole'] = _maps('/assets/materials/baked_props/italy_ground_parts', 't_manhole_01_decal', 'b', 'nm', 'r', 'ao', 'o')
TEXTURES['drain'] = _maps(f'{_DR}/detail/m_metal_grid_drain', 't_metal_grid_drain', 'b', 'nm', 'r', 'ao', 'o')
KINDS['manhole'] = ('manhole', [.42, .41, .40, 1], 'METAL', 1.0, 'strip')
KINDS['drain'] = ('drain', [.30, .29, .28, 1], 'METAL', 1.0, 'strip')
TEXTURES['patch'] = _maps(f'{_DR}/asphalt/road_patches1', 't_asphalt_patchstrip', 'b', 'o')
KINDS['patch'] = ('patch', [.17, .17, .18, 1], 'ASPHALT', 1.0, 'strip')
for _k in ('manhole', 'drain', 'patch'):
    EXTRA[_k] = {'alphaTest': True, 'alphaRef': 77, 'castShadows': False}
    BUILDING_FALLBACK[_k] = None
KINDS['ac_unit'] = ('cladding', [.84, .84, .82, 1], 'METAL', 1.0, 'wall')
KINDS['dish'] = ('cladding', [.86, .86, .85, 1], 'METAL', 1.0, 'wall')
BUILDING_FALLBACK['ac_unit'] = BUILDING_FALLBACK['dish'] = None
FALLBACK.update(BUILDING_FALLBACK)
# footpaths and fences (decoration, no collision)
KINDS['footway'] = ('paving', [.50, .48, .46, 1], 'ASPHALT', 2.0, 'plan')
KINDS['footway_asphalt'] = ('road_city', [.20, .21, .22, 1], 'ASPHALT', 6.0, 'plan')
KINDS['trodden'] = ('trodden', [.42, .36, .28, 1], 'DIRT', 3.0, 'plan')
KINDS['fence_wall'] = ('fence_po2', [.62, .62, .60, 1], 'ROCK', 2.5, 'wall')
KINDS['fence_mesh'] = ('fence_mesh', [.30, .32, .30, 1], 'METAL', 2.0, 'wall')
KINDS['car'] = ('car', [.6, .6, .62, 1], 'METAL', 1.0, 'wall')       # parked cars carry their own UVs
# A yard's own things (generator.lua YARD): playground frames, sandpits, mushrooms and container
# screens take a cell of the paint atlas (fast_art.YARD_COLOURS), as cars do. Front gardens and
# playgrounds are fenced with a low railing of bars: one quad, the bars cut by opacity, the paint
# a tint over a white map (an sRGB factor: the colour itself over 255).
TEXTURES['yard'] = {'baseColorMap': f'{ART}/real/yard.color.png'}
KINDS['yard'] = ('yard', [.6, .6, .6, 1], 'METAL', 1.0, 'wall')
TEXTURES['brand_sign'] = {'baseColorMap': f'{ART}/real/brand_sign.color.png'}
KINDS['brand_sign'] = ('brand_sign', [1, 1, 1, 1], 'METAL', 1.0, 'wall')
# photographs of real stores squared up into facades (fast_art.SHOP_PHOTOS)
TEXTURES['brand_photo'] = {'baseColorMap': f'{ART}/real/brand_photo.color.png'}
KINDS['brand_photo'] = ('brand_photo', [1, 1, 1, 1], 'ROCK', 1.0, 'wall')
# shop fronts drawn at art build time (fast_storefront.py), by night their rooms glow
TEXTURES['storefront'] = {'baseColorMap': f'{ART}/real/storefront.color.png'}
KINDS['storefront'] = ('storefront', [1, 1, 1, 1], 'METAL', 1.0, 'wall')
# a low-voltage line's wires (generator.lua BLD.powerLines): thin upright ribbons, seen from both sides
KINDS['wire'] = (None, [.05, .05, .05, 1], 'METAL', 1.0, 'wall')
EXTRA['wire'] = {'doubleSided': True, 'castShadows': False}
# Railway tracks (generator.lua RAIL): the bed is concrete sleepers on ballast drawn at art build
# (fast_art.rail_art), u across it and v along it, its stony shoulders cut by opacity. The rails
# are steel boxes, worn bright on top and rusty down the sides.
TEXTURES['track'] = {'baseColorMap': f'{ART}/real/track.color.png', 'normalMap': f'{ART}/real/track.normal.png',
                     'opacityMap': f'{ART}/real/track_o.data.png', 'roughnessFactor': .95}
KINDS['track'] = ('track', [.44, .42, .39, 1], 'GRAVEL', 1.0, 'strip')
EXTRA['track'] = {'alphaTest': True, 'alphaRef': 60, 'castShadows': False}
TRACK_MIP_REF = 80
KINDS['rail'] = (None, [.58, .58, .59, 1], 'METAL', 1.0, 'wall')
KINDS['rail_side'] = (None, [.31, .23, .18, 1], 'METAL', 1.0, 'wall')
# gilded domes (generator.lua BLD.dome)
KINDS['roof_gold'] = (None, [.83, .66, .22, 1], 'METAL', 2.0, 'roof')
TEXTURES['railing'] = {'baseColorMap': f'{ART}/real/railing.color.png', 'opacityMap': f'{ART}/real/railing_o.data.png'}
RAILINGS = {'railing_blue': (52, 98, 150), 'railing_green': (46, 104, 70), 'railing_dark': (52, 54, 56)}
for _k, _rgb in RAILINGS.items():
    KINDS[_k] = ('railing', [_c / 255 for _c in _rgb] + [1], 'METAL', 1.0, 'wall')
    EXTRA[_k] = {'alphaTest': True, 'alphaRef': 60, 'doubleSided': True, 'castShadows': False}
RAILING_MIP_REF = 80
# a playground's sand: a flat colour (the beach sheet read as grey asphalt in the yard)
KINDS['sand'] = (None, [.80, .71, .53, 1], 'SAND', 3.0, 'plan')
# the photo ground covers a 24 m sheet (fast_photo.GROUND_M)
for _k in ('ground', 'forest'):
    KINDS[_k] = KINDS[_k][:3] + (_photo.GROUND_M,) + KINDS[_k][4:]
KINDS['park'] = ('grass', [.30, .40, .22, 1], 'GRASS', _photo.GROUND_M, 'plan')


# baseColorFactor per kind: the game's grass is dry West Coast grass; Kyiv's is green
TINT = {'ground': [.55, .85, .42, 1], 'forest': [.36, .58, .28, 1], 'paved': [.62, .62, .60, 1]}
TINT['glyphs_dark'] = [.03, .03, .035, 1]
TINT.update({_k: [_c / 255 for _c in _rgb] + [1] for _k, _rgb in RAILINGS.items()})
# Lines as East Coast paints them. The edge grass tint was set from linear means but acts as an
# sRGB factor (_factor below); in game it sits at .9 of the verge, so it stays. The dirt edge is
# twice as bright as the asphalt: a little darker and less yellow reads as a gravel shoulder; a
# blue-grey tint made a second, darker asphalt (decals-trunk-05).
TINT.update({'mark': [.99, .99, .99, 1], 'mark_yellow': [.94, .79, .27, 1],
             'edge_grass': [.84, 1, .73, 1], 'edge_dirt': [.74, .72, .70, 1]})
def _factor(srgb, mean):
    """baseColorFactor that takes a map whose linear mean is `mean` to the colour `srgb` (0-255).
    The game reads the factor as an sRGB colour: it multiplies by about factor ** 2.2. A plinth
    with a .26 factor came out at a twentieth of the wall above it in the same shade, where .26
    of the map's albedo would have been a third (bld-hatne-04)."""
    def linear(c):
        c /= 255
        return c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4

    def encode(m):
        return 12.92 * m if m <= .0031308 else 1.055 * m ** (1 / 2.4) - .055
    return [round(min(1., encode(min(1., linear(c) / mean))), 3) for c in srgb] + [1]


# Building colours (sRGB) over the maps' linear means: aged asbestos slate (158 158 150), metal
# tile in RAL 3009 (112 38 32), 8017 (74 52 46) and 6005-ish (32 72 54), pale cladding (176 182
# 188), a grey plinth (130 127 120), brown-grey stained boards (150 140 125).
TINT.update({'roof_sheet': _factor((158, 158, 150), .677), 'roof_mtile_red': _factor((112, 38, 32), .355),
             'roof_mtile_brown': _factor((74, 52, 46), .355), 'roof_mtile_green': _factor((32, 72, 54), .355),
             'clad_metal': _factor((176, 182, 188), .677), 'plinth': _factor((130, 127, 120), .862),
             'ac_unit': _factor((214, 214, 208), .677), 'dish': _factor((222, 222, 218), .677),
             'gable': _factor((150, 140, 125), .641)})
# House walls: lime-washed white, ochre, the blue and green of village houses, a pink; aged
# plaster as it is; red brick as it is; silicate brick off-white; beige siding; old dark wood as
# it is. Plinths grey or painted red-brown.
TINT.update({'hw_white': _factor((236, 234, 226), .885), 'hw_yellow': _factor((226, 196, 124), .885),
             'hw_blue': _factor((170, 196, 216), .885), 'hw_green': _factor((182, 206, 168), .885),
             'hw_pink': _factor((226, 192, 182), .885), 'hw_silicate': _factor((222, 218, 206), .948),
             'hw_siding': _factor((188, 180, 156), .486), 'plinth_brown': _factor((112, 68, 56), .862),
             # mild soot darkening; the game treats the factor as sRGB (see _factor)
             'chimney': [.86, .8, .76, 1]})

# Stock PBR textures: referenced in the installed game, never copied into the mod.
for _name, _path in {
    'rock': 'rock/macro_rocky/t_macro_rocky',
    'scree': 'rock/terrain_dirt_rocky/t_dirt_rocky',
    'sand': 'sand/t_sand/t_sand',
}.items():
    _base = '/assets/materials/terrain/' + _path
    TEXTURES[_name] = {'baseColorMap': _base + '_b.color.dds',
                       'normalMap': _base + '_nm.normal.dds',
                       'roughnessMap': _base + '_r.data.dds'}

# Macrocolour comes from mapped land use; fine grain uses existing tileable PBR.
for _kind, _tex, _tint, _ground, _scale in (
    ('meadow', 'grass', [.72, .83, .48, 1], 'GRASS', 24),
    ('farmland', 'dirt', [.68, .60, .36, 1], 'DIRT', 24),
    ('orchard', 'grass', [.59, .72, .38, 1], 'GRASS', 24),
    ('vineyard', 'dirt', [.70, .65, .46, 1], 'DIRT', 12),
    ('scrub', 'grass', [.57, .64, .37, 1], 'GRASS', 24),
    ('heath', 'grass', [.68, .62, .43, 1], 'GRASS', 24),
    ('bare_rock', 'rock', [.87, .87, .84, 1], 'ROCK', 12),
    ('scree', 'scree', [.85, .82, .76, 1], 'GRAVEL', 12),
    ('beach', 'sand', [1, .96, .85, 1], 'SAND', 12),
    ('wetland', 'dirt', [.40, .44, .32, 1], 'MUD', 12),
    ('glacier', None, [.88, .92, .95, 1], 'SNOW', 24),
    ('bare_ground', 'dirt', [.86, .78, .62, 1], 'DIRT', 12),
):
    KINDS[_kind] = (_tex, _tint, _ground, _scale, 'plan')
    TINT[_kind] = _tint
# A station's or a yard's ground (landuse=railway, a 'paved' area: generator.lua draws it in
# this): grey ballast, not the concrete of a car park
KINDS['ballast'] = ('scree', [.60, .58, .55, 1], 'GRAVEL', 4, 'plan')
TINT['ballast'] = KINDS['ballast'][1]

# Country carriageways, worst last. groundType is what the tyres feel.
for _kind, _tex, _tint, _ground, _scale in (
    ('road_worn', 'road_worn', [1, 1, 1, 1], 'ASPHALT', 6),
    ('road_gravel', 'scree', [.78, .74, .68, 1], 'GRAVEL', 4),
    ('road_dirt', 'dirt', [.70, .58, .40, 1], 'DIRT', 4),
    ('road_broken', 'dirt', [.58, .52, .36, 1], 'DIRT', 3),
    ('road_track', 'grass', [.62, .68, .40, 1], 'DIRT', 4),
):
    KINDS[_kind] = (_tex, _tint, _ground, _scale, 'plan')
    TINT[_kind] = _tint
# Asphalt over the one aerial base (linear mean .12, fast_art.BASE_MEAN): a town street of grey
# aged asphalt, a worn one lighter and warmer, a fresh one dark.
for _kind, _srgb in (('road', (83, 83, 82)), ('footway_asphalt', (83, 83, 82)), ('road_worn', (99, 97, 92)),
                     ('road_major', (62, 62, 63))):
    KINDS[_kind] = KINDS[_kind][:3] + (ROAD_M,) + KINDS[_kind][4:]
    TINT[_kind] = _factor(_srgb, .12)

# OSM areas that change the ground under them (anything else stays grass)
PAVED = {'industrial', 'commercial', 'retail', 'railway', 'garages', 'construction', 'depot'}
WOODS = {'forest', 'wood'}


PARKS = {'park', 'garden', 'recreation_ground', 'cemetery', 'village_green'}


ISLANDS = {'area:highway': 'traffic_island', 'traffic_calming': 'island'}
# Zones that keep their ground free (GENERATION_GAPS G03): each takes the cover that plants like
# it. A sports ground is open, a school or hospital site a yard, allotments an orchard.
FIELDS = {'pitch', 'track'}
HARD_FIELDS = {'asphalt', 'concrete', 'tartan', 'rubber', 'acrylic', 'paving_stones', 'paved', 'clay', 'sand', 'dirt', 'gravel'}
SITES = {'school', 'kindergarten', 'college', 'university', 'hospital', 'clinic'}


def ground_kind(tags):
    """'island' (a raised traffic island: the generator shapes it on the road), 'paved', 'forest',
    'park', 'residential' or None for an OSM area's tags."""
    if any(tags.get(k) == v for k, v in ISLANDS.items()) and tags.get('area') != 'no':
        return 'island'
    if tags.get('leisure') == 'playground':
        return 'playground'           # a yard's sandpit and swings (generator.lua YARD.playground)
    if tags.get('leisure') in FIELDS:
        return 'paved' if tags.get('surface') in HARD_FIELDS else 'meadow'     # generator.lua VEG.fields
    if tags.get('amenity') in SITES or tags.get('leisure') in ('sports_centre', 'stadium'):
        return 'residential'
    if tags.get('landuse') == 'allotments':
        return 'orchard'
    if (tags.get('landuse') in PAVED or tags.get('amenity') == 'parking' or tags.get('place') == 'square'
            or tags.get('highway') == 'pedestrian' and tags.get('area') == 'yes'):
        return 'paved'                # a pedestrian area is a square to the generator
    if tags.get('landuse') in WOODS or tags.get('natural') in WOODS:
        return 'forest'
    if tags.get('leisure') in PARKS or tags.get('landuse') in PARKS:
        return 'park'
    if tags.get('landuse') == 'residential':
        return 'residential'          # yards: trees between the blocks, ground stays grass
    return nature.ground_kind(tags)


PATHS = {'footway': 2.0, 'path': 1.2, 'pedestrian': 4.0, 'cycleway': 2.0, 'steps': 2.0, 'bridleway': 1.5,
         'track': 3.0}
UNPAVED = {'unpaved', 'dirt', 'ground', 'earth', 'grass', 'sand', 'gravel', 'fine_gravel', 'compacted', 'mud', 'wood'}


# Railway tracks the generator lays (generator.lua RAIL): rails on a ballast bed, flush with the
# carriageway where they cross or run along a road. A track in a tunnel stays off the map, and a
# metro (railway=subway) runs in tunnels nearly everywhere.
RAILS = ('rail', 'light_rail', 'tram', 'narrow_gauge')
# the tags of a track the generator reads: the rest (names, operators, voltages) only grow the pack
RAIL_TAGS = ('railway', 'gauge', 'usage', 'service', 'electrified', 'embedded', 'bridge', 'layer')


def rail_tags(tags):
    """The RAIL_TAGS of a track way, as a plain dict."""
    return {k: tags.get(k) for k in RAIL_TAGS if tags.get(k) is not None}


def line_kind(tags):
    """'path', 'fence', 'guard_rail', 'gantry' (an overhead sign frame across a road), 'tree_row' or 'rail'
    (a railway or tram track) for an OSM way drawn as a line, 'coastline' for the shore the exporter
    fixes the DEM with (never drawn), else None."""
    if tags.get('natural') == 'coastline':
        return 'coastline'
    if (tags.get('railway') in RAILS and tags.get('tunnel') in (None, 'no') and tags.get('covered') in (None, 'no')
            and tags.get('area') != 'yes'):
        return 'rail'
    if tags.get('man_made') == 'gantry':
        return 'gantry'
    h = tags.get('highway')
    if (h in PATHS and tags.get('area') != 'yes'
            and tags.get('bridge') in (None, 'no') and tags.get('tunnel') in (None, 'no')
            and tags.get('layer', '0') in ('0', '')):
        return 'path'
    if tags.get('natural') == 'tree_row':
        return 'tree_row'
    if tags.get('barrier') in ('fence', 'wall'):
        return 'fence'
    if tags.get('barrier') == 'guard_rail':
        return 'guard_rail'
    if tags.get('barrier') == 'hedge':
        return 'hedge'
    # a street's own wires. The main grid (power=line, its towers, substations) stays off the map
    if tags.get('power') == 'minor_line':
        return 'power'
    return None


# Road details painted or shaped by the generator at a way node (it finds the road under the
# node). 'stop_sign' because 'stop' is a bus stop: an older runtime skips unknown kinds.
ROAD_DETAILS = ('crossing', 'give_way', 'stop_sign', 'mini_roundabout', 'turning_circle')
UNMARKED = ('no', 'none', 'unmarked')


# Every key point_kind reads: the exporter hands Python only nodes with one of them.
POINT_KEYS = ('highway', 'traffic_sign', 'railway', 'natural', 'public_transport', 'entrance', 'leisure', 'amenity', 'barrier', 'shop', 'man_made', 'vending', 'brand', 'operator', 'name',
              'brand:uk', 'brand:en', 'name:uk', 'name:en', 'name:ru', 'operator:uk',
              'operator:en', 'operator:ru', 'brand:wikidata', 'operator:wikidata')


def point_kind(tags):
    """'stop', 'signal' or one of ROAD_DETAILS for an OSM node, else None."""
    retail_kind = retail.kind(tags)
    # a pack with the storefront experiment keeps its shops as POIs with their real names
    if retail_kind and not (POIS and retail_kind == 'service' and poi(tags)):
        return retail_kind
    highway = tags.get('highway')
    if tags.get('natural') == 'tree':
        return 'tree'
    if highway == 'street_lamp':
        return 'lamp'
    if highway == 'crossing':
        marked = tags.get('crossing:markings', tags.get('crossing'))
        return None if marked in UNMARKED else 'crossing'
    if highway == 'give_way':
        return 'give_way'
    if highway == 'stop':
        return 'stop_sign'
    if highway == 'mini_roundabout':
        return 'mini_roundabout'
    if highway in ('turning_circle', 'turning_loop'):
        return 'turning_circle'
    # Retain the surveyed fact even when an older runtime does not draw it.
    if highway == 'traffic_signals':
        return 'signal'
    if highway == 'speed_camera':
        return 'speed_camera'
    if tags.get('railway') == 'level_crossing':
        return 'level_crossing'
    if tags.get('traffic_sign'):
        return 'traffic_sign'
    if tags.get('highway') == 'bus_stop' or (tags.get('public_transport') == 'platform' and
                                              any(tags.get(k) == 'yes' for k in ('bus', 'trolleybus', 'tram'))):
        return 'stop'
    # a block's stair doors (benches, a canopy and a gap in the front garden) and a playground
    # drawn as a node
    if tags.get('entrance') in ENTRANCES:
        return 'entrance'
    if tags.get('leisure') == 'playground':
        return 'playground'
    # street furniture where it stands (generator.lua: the points' loop, BLD.openGates)
    if tags.get('amenity') == 'bench':
        return 'bench'
    if tags.get('amenity') == 'waste_basket':
        return 'waste_basket'
    if tags.get('barrier') == 'lift_gate':
        return 'lift_gate'
    if tags.get('barrier') in ('gate', 'swing_gate', 'sliding_gate', 'wicket_gate'):
        return 'gate'
    if POIS and poi(tags):
        return 'poi'
    if POIS and tags.get('entrance') in DOORS:
        return 'door'
    return None


ENTRANCES = ('staircase', 'main', 'home')

# Commercial OSM nodes kept as facts (kind 'poi') for the storefront experiment: a shop, office
# or craft, or an amenity from this list (amenity alone is a bench or a school as often as a
# shop). Off unless EARTHNG_POIS=1 at build time: packs built without it are unchanged, and a
# runtime that does not know the kind skips it. All the node's tags travel with it.
POIS = os.environ.get('EARTHNG_POIS') == '1'
POI_KEYS = ('shop', 'office', 'craft', 'amenity', 'entrance', 'barrier')
POI_AMENITY = frozenset(('cafe', 'restaurant', 'fast_food', 'bar', 'pub', 'ice_cream', 'bank',
                         'bureau_de_change', 'money_transfer', 'payment_centre', 'pharmacy',
                         'post_office', 'dentist', 'doctors', 'clinic', 'veterinary', 'internet_cafe'))
POI_NOT = ('no', 'vacant', 'closed', 'disused', 'abandoned')
# Other mapped doors on a building's outline, with POIS: the evidence of which wall a shop opens
# on (a staircase, main or home door is an 'entrance' already)
DOORS = ('yes', 'shop', 'service', 'secondary')


def poi(tags):
    """True for a commercial node as defined above."""
    for key in ('shop', 'office', 'craft'):
        value = tags.get(key)
        if value and value not in POI_NOT:
            return True
    return tags.get('amenity') in POI_AMENITY


def point_keys():
    """Keys whose nodes the exporter hands to point_kind."""
    return POINT_KEYS + (POI_KEYS if POIS else ())


BUS_STOP = '/art/shapes/objects/s_busstop_jri.dae'
TRAFFIC_LIGHT = '/art/shapes/objects/trafficlight_city1.dae'
# the shapes' own facing: the yaw that turns their front to +x of the world (measured in game)
BUS_STOP_YAW = math.pi       # vis-12-stops: the open side faced away from the road
TRAFFIC_LIGHT_YAW = 0.0


def path_kind(tags):
    """Material of a footpath: paving tiles in the city, trodden earth on paths and tracks."""
    surface = tags.get('surface')
    if surface in UNPAVED or (surface is None and tags.get('highway') in ('path', 'track', 'bridleway')):
        return 'trodden'
    if surface == 'asphalt' or tags.get('highway') == 'cycleway':
        return 'footway_asphalt'
    return 'footway'


# the game's own tree shapes (precompiled .cdae next to each .dae); no collision, so a forest
# adds nothing to be:reloadCollision
TREES = ['/assets/meshes/foliage/trees_library/beech/tree_beech_forest_a.dae',
         '/assets/meshes/foliage/trees_library/beech/tree_beech_small_b.dae',
         '/assets/meshes/foliage/trees_library/birch/tree_aspen_forest_a.dae',
         '/assets/meshes/foliage/trees_library/birch/tree_aspen_small_b.dae',
         '/assets/meshes/foliage/trees_library/oak/tree_oak_forest_a.dae',
         '/assets/meshes/foliage/trees_library/oak/tree_oak_sml_a.dae']
LAMP = '/art/shapes/objects/lamp1.dae'     # the street lamp roadgen-v2 used
TREE_SPACING = {'forest': 9.0, 'park': 14.0}
TREES_PER_TILE = 900
_T = '/assets/meshes/foliage/trees_library'
# which trees where: Kyiv's streets are lined with chestnuts and lindens (oak and beech stand in),
# its yards with birches, poplars and old broad trees
TREE_SETS = {
    'street': [f'{_T}/oak/tree_oak_sml_a.dae', f'{_T}/oak/tree_oak_sml_b.dae', f'{_T}/beech/tree_beech_small_b.dae',
               f'{_T}/beech/tree_beech_small_c.dae'],
    'row': [f'{_T}/beech/tree_beech_small_b.dae', f'{_T}/beech/tree_beech_small_c.dae', f'{_T}/birch/tree_aspen_small_a.dae'],
    'yard': [f'{_T}/birch/tree_aspen_large_a.dae', f'{_T}/birch/tree_aspen_small_b.dae', f'{_T}/oak/tree_oak_large_a.dae',
             f'{_T}/beech/tree_beech_large_c.dae', f'{_T}/oak/tree_oak_sml_b.dae', f'{_T}/birch/tree_aspen_small_d.dae'],
    'park': [f'{_T}/oak/tree_oak_large_b.dae', f'{_T}/beech/tree_beech_large_c.dae', f'{_T}/birch/tree_aspen_large_b.dae',
             f'{_T}/oak/tree_oak_sml_a.dae'],
    'forest': TREES,
}
ALL_TREES = sorted({t for v in TREE_SETS.values() for t in v})


# Other climates' open ground (generator.lua bio.ground): their own photo sheets of GROUND_M,
# with what the tyres feel. The glacier was a flat colour until it had a sheet.
BIOME_GROUND = {'desert': 'DIRT', 'dune': 'SAND', 'steppe': 'GRASS', 'dry_grass': 'GRASS', 'tundra': 'GRASS',
                'alpine': 'GRAVEL', 'snow': 'SNOW', 'snow_edge': 'SNOW'}
for _k, _ground in BIOME_GROUND.items():
    KINDS[_k] = (None, [*(_c / 255 for _c in {'desert': (184, 152, 112), 'dune': (214, 176, 126), 'steppe': (162, 146, 96),
                                              'dry_grass': (176, 146, 80), 'tundra': (122, 124, 86), 'alpine': (124, 118, 98),
                                              'snow': (232, 236, 242), 'snow_edge': (206, 212, 204)}[_k]), 1],
                 _ground, _photo.GROUND_M, 'plan')
KINDS['glacier'] = KINDS['glacier'][:3] + (_photo.GROUND_M,) + KINDS['glacier'][4:]
PHOTO_GROUND = ('ground', 'park', 'forest', *BIOME_GROUND, 'glacier', 'farmland')

# Lawns, parks and meadows are soil with a fine relief, not the flat lawn photo. The mesh UV
# repeats every COVER_SCALE metre (generator.lua, 24). The detail maps tile every 2 m, the same
# grain BeamNG uses on a terrain block. Blades are the streamed tufts; this only replaces the sheet.
TURF = ('park',)
_SOIL = '/assets/materials/terrain/soil/macro_clumply/t_macro_clumpy'
_VEG = '/assets/materials/terrain/grass/t_dirt_vegetation/t_dirt_vegetation'
TURF_BASE_M, TURF_DETAIL_M = 24.0, 2.0


def turf_stage(kind):
    """Stock soil (macro) plus a 2 m vegetation detail. Parks take a little more of the detail colour."""
    return {
        'baseColorMap': _SOIL + '_b.color.dds',
        'normalMap': _SOIL + '_nm.normal.dds',
        'roughnessMap': _SOIL + '_r.data.dds',
        'roughnessFactor': .94,
        'detailMap': _VEG + '_b.png',
        'detailNormalMap': _VEG + '_nm.png',
        'roughnessDetailMap': _VEG + '_r.png',
        'detailScale': [TURF_BASE_M / TURF_DETAIL_M, TURF_BASE_M / TURF_DETAIL_M],
        'detailBaseColorMapStrength': .55 if kind == 'park' else .38,
        'detailNormalMapStrength': 1.0,
        'detailRoughnessMapStrength': .4,
    }


# Open land (generator.lua VEG.land): the common grass, grass dried on slopes and ridges, lush
# grass in hollows and bare loam on steep ground. Each is a colour sheet MACRO_M wide
# (fast_photo.macro_sheet) under one of the game's grey terrain detail maps over LAND_DETAIL_M,
# which the engine adds to it (base + (2 * detail - 1) * strength).
# Where one land passes into another the generator draws both in the same place, each cut by
# the dissolve mask: fade_<land><level> is the land coming in, over LAND_COVER[level] of the
# area, and cut_<land><level> the land it comes into, over the rest (the inverse mask). They
# do not overlap but for LAND_OVERLAP grey levels of the mask, so nothing fights for depth and
# no hole shows the sky through a compressed texel.
MACRO_M, LAND_DETAIL_M = _photo.MACRO_M, 2.0
_TERRAIN = '/assets/materials/terrain/'
# land: (sheet, detail map stem, detail colour strength, groundType, fallback colour)
LANDS = {
    'grass': ('grass', 'grass/t_grass_01/t_grass_01', .45, 'GRASS', (84, 100, 42)),
    'dry':   ('dry', 'grass/t_dirt_dry_grass/t_dirt_dry_grass', .48, 'GRASS', (142, 134, 76)),
    'lush':  ('lush', 'grass/t_grass_02/t_grass_02', .40, 'GRASS', (62, 92, 34)),
    'earth': ('earth', 'soil/dirt_crumbly/t_dirt_crumbly', .50, 'DIRT', (150, 124, 88)),
}
# six levels, a seventh of the area each (generator.lua VEG.land.levels, collision.lua QUIET):
# with three, a quarter each, the levels' borders read as a grid of 12.5 m squares
LAND_LEVELS = 6
LAND_COVER = tuple(round(k / (LAND_LEVELS + 1), 3) for k in range(1, LAND_LEVELS + 1))
LAND_OVERLAP = 6
LAND_OF = {'ground': 'grass', 'meadow': 'grass', 'grass_dry': 'dry', 'grass_lush': 'lush', 'earth': 'earth'}
FADES, CUTS = {}, {}
for _level, _cover in enumerate(LAND_COVER, 1):
    for _land in ('dry', 'lush', 'earth'):
        FADES[f'fade_{_land}{_level}'] = (_land, _cover)
    for _land in ('grass', 'dry', 'lush'):
        CUTS[f'cut_{_land}{_level}'] = (_land, _cover)
for _k, _land in list(LAND_OF.items()) + [(k, v[0]) for k, v in {**FADES, **CUTS}.items()]:
    _l = LANDS[_land]
    KINDS[_k] = (None, [*(c / 255 for c in _l[4]), 1], _l[3], MACRO_M, 'plan')
    # cut, not blended (a translucent ProceduralMesh is lit in the forward pass); the masks'
    # mips keep every level's coverage (fast_art.MIP_REFS 'uniform')
    if _k in FADES:
        EXTRA[_k] = {'alphaTest': True, 'alphaRef': round(255 * (1 - FADES[_k][1])), 'castShadows': False}
    elif _k in CUTS:
        EXTRA[_k] = {'alphaTest': True, 'alphaRef': round(255 * CUTS[_k][1]) - LAND_OVERLAP, 'castShadows': False}
MACRO = tuple(LAND_OF) + tuple(FADES) + tuple(CUTS)


def macro_stage(kind):
    land = LAND_OF.get(kind) or (FADES.get(kind) or CUTS[kind])[0]
    sheet, detail, strength, _, _ = LANDS[land]
    stage = {
        'baseColorMap': f'{ART}/real/macro_{sheet}.color.png',
        'roughnessFactor': .96 if land == 'earth' else .93,
        'detailMap': _TERRAIN + detail + '_b.png',
        'detailNormalMap': _TERRAIN + detail + '_nm.png',
        'roughnessDetailMap': _TERRAIN + detail + '_r.png',
        'detailScale': [MACRO_M / LAND_DETAIL_M] * 2,
        'detailBaseColorMapStrength': strength,
        'detailNormalMapStrength': 1.0,
        'detailRoughnessMapStrength': .4,
    }
    if kind in FADES:
        stage['opacityMap'] = f'{ART}/real/land_blend_o.data.png'
    elif kind in CUTS:
        stage['opacityMap'] = f'{ART}/real/land_blend_inv_o.data.png'
    return stage


def real_stage(kind):
    """Stage-0 maps of a kind in the 'real' pack."""
    tex, colour, _, _, _ = KINDS[kind]
    if kind in MACRO:
        return macro_stage(kind)
    if kind in TURF:
        return turf_stage(kind)
    if kind in nature.NATURAL and tex == 'grass':
        return {'baseColorMap': f'{ART}/real/ground_ground.color.png',
                'normalMap': f'{ART}/real/ground_ground.normal.png', 'roughnessFactor': .95}
    if kind.startswith('wall_') and kind[5:] in _photo.PHOTO_WALLS:
        w = kind[5:]
        stage = {'baseColorMap': f'{ART}/real/{w}.color.png'}
        if _photo.PHOTO_WALLS[w][0] == 'curtain':
            # glass that mirrors the sky: smooth and part metal (BeamNG PBR)
            stage.update(roughnessFactor=.12, metallicFactor=.55)
        if _photo.PHOTO_WALLS[w][0] in ('brick', 'end_brick', 'facade', 'end_facade'):
            stage['normalMap'] = f'{ART}/real/{w}.normal.png'
        return stage
    if kind.startswith('wall_'):
        w = kind[5:]
        stage = {'baseColorMap': f'{ART}/real/{w}.color.png'}
        if 'normalMap' in TEXTURES[w]:
            stage['normalMap'] = TEXTURES[w]['normalMap']
        return stage
    if kind in PHOTO_GROUND:
        return {'baseColorMap': f'{ART}/real/ground_{kind}.color.png', 'normalMap': f'{ART}/real/ground_{kind}.normal.png'}
    return dict(TEXTURES[tex]) if tex else {'diffuseColor': colour}


def material(kind):
    _, colour, ground, _, _ = KINDS[kind]
    stage = real_stage(kind)
    if kind in TINT and kind not in PHOTO_GROUND and kind not in TURF and kind not in MACRO:
        stage['baseColorFactor'] = TINT[kind]
    if kind == 'road_worn':
        stage['roughnessFactor'] = .96
    elif kind in ('road_gravel', 'road_dirt', 'road_broken', 'road_track'):
        stage['roughnessFactor'] = .98
    out = {'name': 'e2rf_' + kind, 'mapTo': 'e2rf_' + kind, 'class': 'Material', 'version': 1.5,
           'groundType': ground, 'Stages': [stage, {}, {}, {}], 'doubleSided': False, **EXTRA.get(kind, {})}
    if kind in FALLBACK:
        old = FALLBACK[kind]
        out['e2rFallback'] = {'name': 'e2rf_' + kind, 'mapTo': 'e2rf_' + kind, 'class': 'Material', 'version': 1.5,
                              'groundType': ground, 'doubleSided': EXTRA.get(kind, {}).get('doubleSided', False),
                              'Stages': [dict(TEXTURES[old]) if old else {'diffuseColor': colour}, {}, {}, {}]}
    return out


# Plain sheets of CC0 photos (fast_facade.SHEETS), made at art build and shipped with the planet:
# a roughness for the whole sheet, no map, to keep them small. The walls of houses go with the
# game's own (HOUSE_WALLS; generator.lua BLD.regions, BLD.wallScale), the roofs with ROOFS
# (BLD.regions, BLD.repeats).
import fast_facade as _facade
_ROUGH = {'sh_tin_rust': (.72, .4), 'sh_tin_zinc': (.55, .6), 'sh_profile': (.5, .55), 'sh_roof_tin': (.72, .4),
          'sh_roof_zinc': (.55, .6), 'sh_roof_profile': (.5, .55), 'sh_roof_slate': (.6, 0), 'sh_setts': (.8, 0)}
for _s in _facade.SHEETS:
    _rough, _metal = _ROUGH.get(_s, (.92, 0))
    TEXTURES[_s] = {'baseColorMap': f'{ART}/real/{_s}.color.png', 'normalMap': f'{ART}/real/{_s}.normal.png',
                    'roughnessFactor': _rough, 'metallicFactor': _metal}
_G = _facade.GREY_MEAN
SHEET_WALLS = {   # kind: (sheet, colour of the wall, metres a repeat, linear mean of the sheet when tinted)
    'hw_dash': ('sh_dash', (176, 170, 156), 1.5, .31), 'hw_dash_cream': ('sh_dash', (204, 188, 150), 1.5, .31),
    'hw_flaking': ('sh_flaking', (168, 166, 154), 2.5, None), 'hw_flaking_yellow': ('sh_flaking_yellow', (190, 166, 96), 2.5, None),
    'hw_render_white': ('sh_render', (232, 228, 218), 2.5, .67), 'hw_render_ochre': ('sh_render', (208, 158, 100), 2.5, .67),
    'hw_render_terracotta': ('sh_render', (184, 112, 84), 2.5, .67), 'hw_render_sand': ('sh_render', (214, 192, 150), 2.5, .67),
    'hw_render_teal': ('sh_render', (106, 164, 164), 2.5, .67), 'hw_render_pink': ('sh_render', (214, 148, 136), 2.5, .67),
    'hw_adobe': ('sh_adobe', (150, 110, 74), 2.0, None), 'hw_block': ('sh_block', (150, 142, 128), 3.0, None),
    'hw_ashlar': ('sh_ashlar', (190, 180, 160), 2.0, None), 'hw_sandstone': ('sh_sandstone', (186, 164, 130), 3.0, None),
    'hw_fieldstone': ('sh_fieldstone', (130, 120, 100), 3.0, None),
    'hw_clapboard_white': ('sh_clapboard', (232, 230, 222), 1.2, _G), 'hw_clapboard_blue': ('sh_clapboard', (150, 176, 194), 1.2, _G),
    'hw_clapboard_yellow': ('sh_clapboard', (222, 200, 140), 1.2, _G),
    'hw_vinyl_white': ('sh_vinyl', (226, 226, 216), 2.0, _G), 'hw_vinyl_grey': ('sh_vinyl', (168, 172, 170), 2.0, _G),
    'hw_vinyl_cream': ('sh_vinyl', (218, 204, 170), 2.0, _G),
    'hw_falu': ('sh_boards_red', (130, 50, 40), 2.0, None), 'hw_stock': ('sh_stock', (176, 136, 90), 2.0, None),
    'hw_brick_dark': ('sh_brick_dark', (84, 66, 58), 1.9, None), 'hw_clinker': ('sh_clinker', (120, 66, 48), 2.0, None),
    'hw_tin': ('sh_tin_rust', (120, 60, 36), 2.0, None), 'hw_zinc': ('sh_tin_zinc', (120, 118, 114), 1.8, None),
}
for _k, (_tex, _rgb, _m, _mean) in SHEET_WALLS.items():
    KINDS[_k] = (_tex, [_c / 255 for _c in _rgb] + [1], 'ROCK', _m, 'wall')
    if _mean:
        TINT[_k] = _factor(_rgb, _mean)
SHEET_ROOFS = {   # kind: (sheet, colour, metres a repeat, linear mean of the sheet when tinted)
    'roof_clay': ('sh_roof_clay', (150, 80, 56), 2.0, None), 'roof_pantile': ('sh_roof_pantile', (168, 96, 70), 2.0, None),
    'roof_concrete': ('sh_roof_concrete', (58, 58, 64), 2.0, None), 'roof_slate': ('sh_roof_slate', (92, 96, 100), 3.0, None),
    'roof_shingle': ('sh_roof_shingle', (96, 96, 96), 8.0, None), 'roof_thatch': ('sh_roof_thatch', (120, 100, 76), 2.0, None),
    'roof_tin': ('sh_roof_tin', (120, 60, 36), 2.0, None), 'roof_zinc': ('sh_roof_zinc', (124, 122, 118), 1.8, None),
    'roof_prof_red': ('sh_roof_profile', (112, 38, 32), 2.0, _G), 'roof_prof_green': ('sh_roof_profile', (40, 84, 62), 2.0, _G),
    'roof_prof_brown': ('sh_roof_profile', (74, 52, 46), 2.0, _G), 'roof_prof_grey': ('sh_roof_profile', (120, 124, 124), 2.0, _G),
}
for _k, (_tex, _rgb, _m, _mean) in SHEET_ROOFS.items():
    KINDS[_k] = (_tex, [_c / 255 for _c in _rgb] + [1], 'METAL' if _tex in ('sh_roof_tin', 'sh_roof_zinc', 'sh_roof_profile') else 'ROCK', _m, 'roof')
    if _mean:
        TINT[_k] = _factor(_rgb, _mean)
    EXTRA[_k] = {'doubleSided': True}
ROOFS += tuple(SHEET_ROOFS)
# Fences (generator.lua BLD.fenceKind): profiled sheet in its three usual paints, brick and rubble
# walls, a fence of upright boards with its gaps cut by opacity
TEXTURES['fence_boards'] = {'baseColorMap': f'{ART}/real/fence_boards.color.png', 'opacityMap': f'{ART}/real/fence_boards_o.data.png',
                            'roughnessFactor': .92}
FENCE_BOARDS_MIP_REF = 80
for _k, _rgb in (('fence_prof_green', (46, 96, 70)), ('fence_prof_brown', (92, 62, 50)), ('fence_prof_grey', (140, 144, 144))):
    KINDS[_k] = ('sh_profile', [_c / 255 for _c in _rgb] + [1], 'METAL', 2.0, 'wall')
    TINT[_k] = _factor(_rgb, _G)
    EXTRA[_k] = {'doubleSided': True}
KINDS['fence_brick'] = ('sh_brick_red', [.5, .3, .25, 1], 'ROCK', 2.0, 'wall')
KINDS['fence_stone'] = ('sh_fieldstone', [.5, .46, .4, 1], 'ROCK', 3.0, 'wall')
KINDS['fence_boards'] = ('fence_boards', [.42, .34, .26, 1], 'WOOD', 2.0, 'wall')
EXTRA['fence_boards'] = {'alphaTest': True, 'alphaRef': 60, 'doubleSided': True}
for _k in ('fence_brick', 'fence_stone'):
    EXTRA[_k] = {'doubleSided': True}
# a street of granite setts: what the tyres feel stays asphalt, as the worn road it replaces
KINDS['road_sett'] = ('sh_setts', [.45, .44, .42, 1], 'ASPHALT', 3.0, 'plan')
SHEET_KINDS = (*SHEET_WALLS, *SHEET_ROOFS, 'fence_prof_green', 'fence_prof_brown', 'fence_prof_grey', 'fence_brick', 'fence_stone',
               'fence_boards', 'road_sett')


def dds(obj):
    """Our art paths with the .dds the art folder holds (fast_art writes no PNG): the game finds
    either, but warns for every '.png' it corrects."""
    if isinstance(obj, dict):
        return {k: dds(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [dds(v) for v in obj]
    if isinstance(obj, str) and obj.startswith('/e2r_stream/fast-art/') and obj.endswith('.png'):
        return obj[:-4] + '.dds'
    return obj


MATERIALS = dds({'e2rf_' + k: material(k) for k in KINDS})
for _kind, _glow in LENS.items():
    MATERIALS['e2rf_' + _kind]['Stages'][0]['emissiveFactor'] = [c * 4 for c in _glow]
# The tree shapes' own materials (game textures under /assets): this level does not define
# them, and without them every tree rendered as the orange NO MATERIAL (fast-game-detail-03).
import json as _json
from pathlib import Path as _Path
MATERIALS.update(_json.loads((_Path(__file__).with_name('fast_tree_materials.json')).read_text(encoding='utf8')))
# the thin-leaf physics material (no stages: what a car feels in a bush) of Italy's generibush and
# East Coast's fir bush, as leaves_strong above; the levels define it in a file that would also
# overwrite our leaves_strong
MATERIALS['leaves_thin'] = {**MATERIALS['leaves_strong'], 'name': 'leaves_thin', 'mapTo': 'leaves_thin', 'groundType': 'leaves_thin'}
# Poplar leaves (Automation Test Track's poplars, generator.lua VEG.poplar) as that level defines
# them but summer green: its leaves are autumn yellow (sRGB 154 132 58) and stood out in every
# village (veg-hatne-a). The autumn pack gives the level's own colour back, winter drops them.
# Their billboards (the level's baked imposter) stay yellow: the generator plants few poplars.
_POPLAR = '/assets/materials/tree/poplar'
POPLAR_LEAVES = {}
for _name, _folder, _stem in (('m_poplar_leaves_01', 't_poplar_leaves_01', 't_poplar_leaves'),
                              ('m_poplar_leaves_02', 't_poplar_leaves_02', 't_poplar_leaves_02')):
    POPLAR_LEAVES[_name] = {
        'name': _name, 'mapTo': _name, 'class': 'Material', 'version': 1.5, 'alphaTest': True, 'alphaRef': 70,
        'Stages': [{**_maps(f'{_POPLAR}/{_folder}', _stem, 'b', 'nm', 'r', 'ao', 'o'),
                    'baseColorFactor': [.5, .8, .74, 1]}, {}, {}, {}]}
POPLAR_AUTUMN = '1 0.962 0.872 1'
MATERIALS.update(POPLAR_LEAVES)

INDUSTRIAL = {'industrial', 'warehouse', 'factory', 'garages', 'garage', 'shed', 'hangar', 'service', 'storage_tank'}
OFFICE = {'office', 'commercial', 'retail', 'supermarket', 'mall', 'hotel'}
HOUSE = {'house', 'detached', 'semidetached_house', 'terrace', 'bungalow', 'cabin', 'farm', 'hut'}


def wall(tags, height, fid, central=False):
    """Facade for a building by its tags, height and district; a stable hash picks among the
    similar. Photo walls (fast_photo) for housing, the game's textures for offices and sheds."""
    b = tags.get('building', 'yes')
    h = zlib.crc32(str(fid).encode())
    if b in INDUSTRIAL:
        return 'wall_block'
    # glass only by use: a tall block without tags is a residential panel high-rise here
    # (fast-game-detail-02 dressed Akademmistechko's 16-storey blocks as offices)
    word = _photo.colour_word(tags.get('building:colour'))
    if b in OFFICE or tags.get('office'):
        # towers in curtain glass, lower offices in ribbon windows; the old town keeps plaster
        if height > 20:
            return 'wall_' + (_photo.pick(['off_blue', 'off_green', 'off_grey'], word, h // 7) if h % 10 < 7 else 'off_ribbon')
        if central and h % 10 < 6:
            return 'wall_' + _photo.pick(['pls_yellow', 'pls_cream', 'pls_peach', 'pls_grey'], word, h // 7)
        return 'wall_' + ('off_ribbon' if h % 3 else 'off_ribbon_dark')
    material = tags.get('building:material', '')
    pnl = ['pnl_grey', 'pnl_beige', 'pnl_pink', 'pnl_blue', 'pnl_white', 'pnl_grey', 'pnl_beige']
    lgg = ['lgg_cream', 'lgg_grey', 'lgg_pink']
    brk = ['brk_red', 'brk_white', 'brk_white']
    pls = ['pls_yellow', 'pls_cream', 'pls_peach', 'pls_green', 'pls_blue', 'pls_grey']
    if material == 'brick':
        family = brk
    elif material in ('panel', 'concrete', 'reinforced_concrete'):
        family = lgg if height >= 26 and h % 3 else pnl
    elif material in ('plaster', 'stucco'):
        family = pls
    elif b in HOUSE or height < 8:
        family = brk if h % 5 < 2 else pls
    elif height >= 26:                     # nine storeys and up: panel or loggia blocks
        family = lgg if h % 9 < 4 else pnl
    elif height >= 14:                     # five to eight storeys: khrushchovky, panel and brick
        r = h % 20
        family = (pls if r < 12 else brk if r < 17 else pnl) if central else (pnl if r < 8 else brk if r < 15 else pls)
    else:                                  # three, four storeys: the old town and stalinky
        family = pls if h % 5 < 3 else brk
    return 'wall_' + _photo.pick(family, word, h // 7)


def shopfront(tags, height, fid, central, kind):
    """The storefront kind for the ground floor of a building in the old town (or tagged with a
    shop), or None."""
    b = tags.get('building', 'yes')
    h = zlib.crc32(str(fid).encode()) // 11
    family = kind[5:].split('_')[0]
    if family in ('off', 'lgg') or b in INDUSTRIAL or b in HOUSE or height < 9:
        return None
    if tags.get('shop') or tags.get('amenity') in ('cafe', 'restaurant', 'bank', 'pharmacy') or \
            (central and b in ('yes', 'apartments', 'residential', 'commercial', 'retail') and h % 10 < 6):
        return 'wall_' + ('shop_dark', 'shop_red', 'shop_green', 'shop_blue', 'shop_dark')[h % 5]
    return None


SHOP_HEIGHT = 4.2


def end_wall(kind):
    """The blank end-wall kind of a facade, or the facade itself."""
    end = kind + '_end'
    return end if end in KINDS else kind


def pitched(tags, height, area):
    """True for a pitched (gabled) roof: by roof:shape, else houses and small low buildings."""
    shape = tags.get('roof:shape')
    if shape:
        return shape in ('gabled', 'hipped', 'pyramidal', 'half-hipped', 'saltbox', 'mansard', 'gambrel')
    b = tags.get('building', 'yes')
    return (b in HOUSE or (height < 8 and area < 260)) and b not in INDUSTRIAL and area < 900
