"""Download the CC0 sets the packs add into data/textures/<set>/<map>.jpg, with their sources in
data/textures/manifest.json (as Earth2Road's tools/fetch_textures.py does for the rest):
the ambientCG sets of the season packs (fast_art: winter, autumn) at 1K, and the road surfaces
and line paint from ambientCG and Poly Haven (fast_art.road_sheets).

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
    manifest_path.write_text(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
