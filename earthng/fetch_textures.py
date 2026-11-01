"""Download the CC0 sets the packs add into data/textures/<set>/<map>.jpg, with their sources in
data/textures/manifest.json (as Earth2Road's tools/fetch_textures.py does for the rest):
the ambientCG sets of the season packs (fast_art: winter, autumn) at 1K, the road surfaces and
line paint from ambientCG and Poly Haven (fast_art.road_sheets), and the materials of the drawn
facades and plain sheets (fast_facade).

    python earthng/fetch_textures.py
"""
import hashlib
import io
import json
import subprocess
import zipfile

import paths

DEST = paths.PROJECT / 'data' / 'textures'
MAPS = {'Color': 'albedo', 'NormalGL': 'normal', 'Roughness': 'roughness'}
SETS = {
    'snow_fresh': 'Snow005',          # clean fluffy snow: lawns, roofs
    'snow_trodden': 'Snow010C',       # footsteps: yards and paths
    'snow_dirty': 'Snow012',          # grey molten snow: verges by the road
    'leaves_orange': 'ScatteredLeaves007',
    'leaves_brown': 'ScatteredLeaves002',
    'leaves_forest': 'Ground070',
    # biome ground sheets (fast_photo.GROUND): deserts, dunes, steppe, tundra, the alpine belt, snow
    'desert_soil': 'Ground079S',      # sandy dirt with gravel
    'desert_crust': 'Ground080',      # dry rippled dirt
    'dune_sand': 'Ground097',         # wind ripples
    'steppe_ground': 'Ground102',     # dry yellow-green ground
    'lichen_stones': 'Ground063',     # dry grass, lichen and stones: fellfield, tundra
    'rock_debris': 'Ground110',       # dark rocky debris: scree belts
    'moss_earth': 'Ground037',        # damp moss: tundra, boreal floor
    'moss_red': 'Ground068',          # moss with red-brown heath
    'snow_wind': 'Snow014',           # wind-packed snow of the high mountains
    'snow_melt': 'Snow015',           # melting snow over grass: the edge of a snow patch
}
# Roads: (site, asset, maps that must be there, resolution). Ambient occlusion and opacity come
# along when a set has them. The aerial street is the roads' base; the others are their detail.
ROAD_SETS = {
    'road_city': ('polyhaven', 'asphalt_01', ('albedo', 'normal', 'roughness'), '2K'),     # even, worn, 2.1 m
    'road_worn': ('ambientcg', 'Asphalt026C', ('albedo', 'normal', 'roughness'), '2K'),    # cracked, patched
    'road_fresh': ('ambientcg', 'Asphalt025C', ('albedo', 'normal', 'roughness'), '2K'),   # dark, even
    'road_macro': ('polyhaven', 'aerial_asphalt_01', ('albedo', 'normal', 'roughness'), '4K'),  # 30 m of a street
    'road_line': ('ambientcg', 'RoadLines025B', ('albedo', 'normal', 'roughness', 'opacity'), '2K'),  # worn solid line
}
# Walls, roofs, fences and streets of the wider world at 1K: fast_facade draws its facades over them
# and makes its plain sheets of them. (site, asset, what it is)
MATERIAL_SETS = {
    # brick
    'mat_brick_red': ('polyhaven', 'red_brick_03'),              # machine-made red, pale joints
    'mat_brick_old': ('polyhaven', 'medieval_red_brick'),        # hand-made, uneven: before 1917
    'mat_brick_silicate': ('polyhaven', 'whitewashed_brick'),    # pale sand-lime brick of Soviet blocks
    'mat_brick_stock': ('polyhaven', 'yellow_brick'),            # London stock
    'mat_brick_dark': ('polyhaven', 'brick_wall_10'),            # brown-grey, North Sea and American
    'mat_clinker': ('polyhaven', 'exterior_wall_cladding_02'),   # brick slips of new blocks
    'mat_block': ('polyhaven', 't_concrete_wall_002'),           # bare concrete block
    # render and concrete
    'mat_dash': ('ambientcg', 'Concrete037'),                    # dash render ('шуба', pebbledash)
    'mat_render': ('ambientcg', 'Plaster002'),                   # even render
    'mat_render_flaking': ('ambientcg', 'PaintedPlaster014'),    # white paint off old brick
    'mat_render_yellow': ('ambientcg', 'PaintedPlaster018'),     # yellow paint off old render
    'mat_adobe': ('polyhaven', 'clay_plaster'),                  # mud plaster
    'mat_concrete_stain': ('ambientcg', 'Concrete035'),          # stained by the tropics
    'mat_concrete_board': ('ambientcg', 'Concrete043A'),         # board-marked, grey
    # stone
    'mat_ashlar': ('polyhaven', 'white_sandstone_blocks_02'),    # dressed pale limestone
    'mat_sandstone': ('polyhaven', 'sandstone_blocks_05'),       # warm coursed sandstone
    'mat_fieldstone': ('polyhaven', 'rough_block_wall'),         # rubble
    # boards and sheet
    'mat_clapboard': ('ambientcg', 'WoodSiding009'),             # painted clapboard
    'mat_boards_red': ('ambientcg', 'WoodSiding005'),            # Nordic red
    'mat_vinyl': ('polyhaven', 'exterior_wall_cladding_03'),     # vinyl siding
    'mat_tin_rust': ('polyhaven', 'rusty_corrugated_iron'),
    'mat_tin_zinc': ('polyhaven', 'worn_corrugated_iron'),
    'mat_profile': ('polyhaven', 'box_profile_metal_sheet'),     # profiled sheet of fences and roofs
    'mat_planks': ('ambientcg', 'WoodSiding003'),                # bare boards of a village fence
    # roofs
    'mat_roof_clay': ('polyhaven', 'clay_roof_tiles_02'),         # interlocking clay
    'mat_roof_pantile': ('ambientcg', 'RoofingTiles014A'),       # round Mediterranean tiles
    'mat_roof_concrete': ('ambientcg', 'RoofingTiles013B'),      # dark concrete tile
    'mat_roof_slate': ('polyhaven', 'roof_slates_03'),
    'mat_roof_shingle': ('polyhaven', 'grey_roof_01'),           # asphalt shingle
    'mat_roof_thatch': ('ambientcg', 'ThatchedRoof001A'),
    'mat_bitumen': ('polyhaven', 'bitumen'),                     # flat roofs
    # streets and fields
    'mat_setts': ('polyhaven', 'cobblestone_03'),                # granite setts
    'mat_soil': ('ambientcg', 'Ground048'),                      # dark ploughed earth
    'mat_stubble': ('ambientcg', 'Ground072'),                   # straw on soil
    'mat_laterite': ('polyhaven', 'red_laterite_soil_stones'),   # red earth of the tropics
}
ACG_MAPS = {'Color': 'albedo', 'NormalGL': 'normal', 'Roughness': 'roughness', 'AmbientOcclusion': 'ao',
            'Opacity': 'opacity'}
PH_MAPS = {'Diffuse': 'albedo', 'nor_gl': 'normal', 'Rough': 'roughness', 'AO': 'ao'}


def _get(url):
    return subprocess.run(['curl', '-fsSL', '--retry', '2', '--max-time', '300', url], check=True,
                          capture_output=True).stdout


def _ambientcg(asset, resolution, maps):
    """{map: bytes} from an ambientCG JPG zip, and the record of where it came from."""
    url = f'https://ambientcg.com/get?file={asset}_{resolution}-JPG.zip'
    blob = _get(url)
    out = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for entry in z.namelist():
            for key, name in maps.items():
                if entry.endswith(f'_{key}.jpg'):
                    out[name] = z.read(entry)
    return out, {'source': url, 'license': 'CC0-1.0 (ambientCG)', 'zip_sha256': hashlib.sha256(blob).hexdigest()}


def _polyhaven(asset, resolution):
    files = json.loads(_get(f'https://api.polyhaven.com/files/{asset}'))
    out = {}
    for key, name in PH_MAPS.items():
        jpg = files.get(key, {}).get(resolution.lower(), {}).get('jpg')
        if jpg:
            out[name] = _get(jpg['url'])
    return out, {'source': f'https://polyhaven.com/a/{asset}', 'license': 'CC0-1.0 (Poly Haven)'}


def _save(manifest, name, asset, maps, record):
    folder = DEST / name
    folder.mkdir(parents=True, exist_ok=True)
    for out, data in maps.items():
        (folder / f'{out}.jpg').write_bytes(data)
    manifest[name] = {'asset': asset, **record, 'files': {out: hashlib.sha256(data).hexdigest() for out, data in maps.items()}}
    print('texture', name, asset)


def main():
    manifest_path = DEST / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for name, asset in SETS.items():
        if manifest.get(name, {}).get('asset') == asset and all((DEST / name / f'{m}.jpg').exists() for m in MAPS.values()):
            continue
        maps, record = _ambientcg(asset, '1K', MAPS)
        missing = set(MAPS.values()) - set(maps)
        if missing:
            raise RuntimeError(f'{asset}: missing maps {missing}')
        _save(manifest, name, asset, maps, record)
    for name, (site, asset, need, resolution) in ROAD_SETS.items():
        known = manifest.get(name, {})
        if known.get('asset') == asset and known.get('resolution', '2K') == resolution                 and all((DEST / name / f'{m}.jpg').exists() for m in need):
            continue
        maps, record = _ambientcg(asset, resolution, ACG_MAPS) if site == 'ambientcg' else _polyhaven(asset, resolution)
        record['resolution'] = resolution
        missing = set(need) - set(maps)
        if missing:
            raise RuntimeError(f'{asset}: missing maps {missing}')
        _save(manifest, name, asset, maps, record)
    for name, (site, asset) in MATERIAL_SETS.items():
        if manifest.get(name, {}).get('asset') == asset and all((DEST / name / f'{m}.jpg').exists() for m in MAPS.values()):
            continue
        maps, record = _ambientcg(asset, '1K', ACG_MAPS) if site == 'ambientcg' else _polyhaven(asset, '1K')
        record['resolution'] = '1K'
        missing = set(MAPS.values()) - set(maps)
        if missing:
            raise RuntimeError(f'{asset}: missing maps {missing}')
        _save(manifest, name, asset, maps, record)
        manifest_path.write_text(json.dumps(manifest, indent=2))
    manifest_path.write_text(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
