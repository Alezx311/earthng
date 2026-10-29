"""Look of the fast generator: materials from the game's own tileable textures, UV scale per
surface kind, and a facade per building. No textures are shipped; all paths are BeamNG's
/assets (resolved to their .dds). Kinds are the Mesh face groups; material = 'e2rf_' + kind."""
import math
import os
import zlib
import nature

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
    ('farmland', 'dirt', [.68, .60, .36, 1], 'DIRT', 12),
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


def ground_kind(tags):
    """'island' (a raised traffic island: the generator shapes it on the road), 'paved', 'forest',
    'park', 'residential' or None for an OSM area's tags."""
    if any(tags.get(k) == v for k, v in ISLANDS.items()) and tags.get('area') != 'no':
        return 'island'
    if tags.get('leisure') == 'playground':
        return 'playground'           # a yard's sandpit and swings (generator.lua YARD.playground)
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


def line_kind(tags):
    """'path', 'fence', 'guard_rail', 'gantry' (an overhead sign frame across a road) or 'tree_row' for
    an OSM way drawn as a line, 'coastline' for the shore the exporter fixes the DEM with (never
    drawn), else None."""
    if tags.get('natural') == 'coastline':
        return 'coastline'
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
    return None


# Road details painted or shaped by the generator at a way node (it finds the road under the
# node). 'stop_sign' because 'stop' is a bus stop: an older runtime skips unknown kinds.
ROAD_DETAILS = ('crossing', 'give_way', 'stop_sign', 'mini_roundabout', 'turning_circle')
UNMARKED = ('no', 'none', 'unmarked')


# Every key point_kind reads: the exporter hands Python only nodes with one of them.
POINT_KEYS = ('highway', 'natural', 'public_transport', 'entrance', 'leisure')


def point_kind(tags):
    """'stop', 'signal' or one of ROAD_DETAILS for an OSM node, else None."""
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
    # traffic signals: the game's trafficlight_city1.dae is a head without a pole (it lay at the
    # curb, vis-13-signals); placing is written (fast.add_street_points), off until a pole model
    if tags.get('highway') == 'traffic_signals' and SIGNALS:
        return 'signal'
    if tags.get('highway') == 'bus_stop' or (tags.get('public_transport') == 'platform' and
                                              any(tags.get(k) == 'yes' for k in ('bus', 'trolleybus', 'tram'))):
        return 'stop'
    # a block's stair doors (benches, a canopy and a gap in the front garden) and a playground
    # drawn as a node
    if tags.get('entrance') in ENTRANCES:
        return 'entrance'
    if tags.get('leisure') == 'playground':
        return 'playground'
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
POI_KEYS = ('shop', 'office', 'craft', 'amenity', 'entrance')
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


SIGNALS = False
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
PHOTO_GROUND = ('ground', 'park', 'forest', *BIOME_GROUND, 'glacier')

# Lawns, parks and meadows are soil with a fine relief, not the flat lawn photo. The mesh UV
# repeats every COVER_SCALE metre (generator.lua, 24). The detail maps tile every 2 m, the same
# grain BeamNG uses on a terrain block. Blades are the streamed tufts; this only replaces the sheet.
TURF = ('ground', 'park', 'meadow')
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


def real_stage(kind):
    """Stage-0 maps of a kind in the 'real' pack."""
    tex, colour, _, _, _ = KINDS[kind]
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
        if _photo.PHOTO_WALLS[w][0] in ('brick', 'end_brick'):
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
    if kind in TINT and kind not in PHOTO_GROUND and kind not in TURF:
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
