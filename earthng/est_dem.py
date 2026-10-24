"""Estonian LiDAR terrain (Maa- ja Ruumiamet DTM) burnt into the cached Terrarium tiles.

Terrarium z12 is SRTM-derived: ~19.5 m pixels at 59 deg N, and its trees and roofs stand
about 4 m over the bare ground. The Land Board's 10 m DTM is measured bare earth. Its
sheets are reprojected onto every cached z12 tile they cover and feathered into the
Terrarium heights over FEATHER metres inside the sheets' edge, so the downstream readers
(fast_sources.Terrain, fast_profile.Mosaic, build_country) take it unchanged. The first
burn keeps the original PNG in terrain/12.orig; a burn always starts from that original.
The sheets are also burnt into the four z13 children of every refined tile (terrain/13,
~9.6 m pixels): there Terrain reads zoom 13 and build_country exports a 10 m grid. A z13
pixel X samples the ground at X itself (Terrain's bilinear convention), and where the
feather fades the LiDAR out, a child is the z12 tile upsampled, as Terrain upsamples
the tiles no sheet reaches.

Map data: Republic of Estonia Land and Spatial Development Board (Maa- ja Ruumiamet),
https://geoportaal.maaruum.ee/opendata-licence
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import time
import urllib.request

import tls

import numpy as np

KIND = 'dem_10m_geotiff'
SHEET = 10000.0                  # a 1:20000 sheet: 10 x 10 km of L-EST97 (EPSG:3301)
FEATHER = 500.0
# L-EST97 metres of the mainland and the islands, with a margin
ESTONIA = (300000.0, 6300000.0, 800000.0, 6700000.0)
URL = ('https://geoportaal.maaruum.ee/index.php?lang_id=1&plugin_act=otsing&page_id=614'
       '&dl=1&kaardiruut={code}&andmetyyp={kind}&f={code}_dtm_10m.tif')
AGENT = 'EarthNG/0.1 (+https://github.com/Alezx311/earth2road)'
R = 20037508.342789244           # half the Web-Mercator world, metres
TILE = 2 * R / 4096              # one z12 tile


def sheet_code(e, n):
    """1:20000 sheet number holding the L-EST97 point (e, n): 6374 covers E540-550k, N6570-6580k."""
    return f'{math.floor((n - 6e6) / 1e5) + 1}{math.floor(e / 1e5) - 2}{math.floor(n / 1e4) % 10}{math.floor(e / 1e4) % 10}'


def sheets(box):
    """{code: (w, s, e, n)} of every sheet under an L-EST97 box, clipped to Estonia."""
    w, s, e, n = (max(box[0], ESTONIA[0]), max(box[1], ESTONIA[1]),
                  min(box[2], ESTONIA[2]), min(box[3], ESTONIA[3]))
    out = {}
    for ce in range(math.floor(w / SHEET), math.floor(e / SHEET) + 1):
        for cn in range(math.floor(s / SHEET), math.floor(n / SHEET) + 1):
            x, y = ce * SHEET, cn * SHEET
            out[sheet_code(x, y)] = (x, y, x + SHEET, y + SHEET)
    return out


def tile_bounds(x, y):
    """Web-Mercator (left, bottom, right, top) of z12 tile x/y."""
    return (-R + x * TILE, R - (y + 1) * TILE, -R + (x + 1) * TILE, R - y * TILE)


def tile_of(path):
    return int(path.parent.name), int(path.stem)


def encode(h):
    """Terrarium RGB for heights h (metres): r*256 + g + b/256 - 32768."""
    q = np.clip(np.round((np.asarray(h, float) + 32768) * 256), 0, 2 ** 24 - 1).astype(np.int64)
    return np.stack([q >> 16, (q >> 8) & 255, q & 255], -1).astype(np.uint8)


def decode(rgb):
    rgb = np.asarray(rgb, float)
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


def fetch_sheet(code, cache, kind=KIND):
    """The sheet's GeoTIFF in cache/est/<kind>/<code>.tif, or None when the Land Board has no
    such sheet (sea, abroad); a .none marker remembers that."""
    folder = Path(cache) / 'est' / kind
    path, none = folder / f'{code}.tif', folder / f'{code}.none'
    if path.exists():
        return path
    if none.exists():
        return None
    request = urllib.request.Request(URL.format(code=code, kind=kind), headers={'User-Agent': AGENT})
    with urllib.request.urlopen(request, timeout=90, context=tls.context()) as response:
        data = response.read()
    folder.mkdir(parents=True, exist_ok=True)
    if data[:4] not in (b'II*\x00', b'MM\x00*'):      # an HTML page: "no sheet with this number"
        none.write_bytes(b'')
        return None
    part = path.with_suffix(f'.{os.getpid()}.tif.part')   # builds running side by side
    part.write_bytes(data)
    import rasterio
    with rasterio.open(part) as source:
        if source.crs is None or source.crs.to_epsg() != 3301:
            raise ValueError(f'sheet {code}: not EPSG:3301')
    for attempt in range(10):   # an antivirus may hold the fresh .part for a moment (WinError 32)
        try:
            os.replace(part, path)
            return path
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(1)


def feather(e, n, covered):
    """0..1 weight of LiDAR at L-EST97 points: 1 deeper than FEATHER inside the covered sheets,
    falling to 0 at the edge towards any sheet that is missing."""
    ce, cn = np.floor(e / SHEET).astype(int), np.floor(n / SHEET).astype(int)
    keys = {(int(math.floor(b[0] / SHEET)), int(math.floor(b[1] / SHEET))) for b in covered}
    inside = np.array([(a, b) in keys for a, b in zip(ce.ravel(), cn.ravel(), strict=True)]).reshape(e.shape)
    reach = np.full(e.shape, FEATHER)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == dy == 0:
                continue
            gone = np.array([(a + dx, b + dy) not in keys
                             for a, b in zip(ce.ravel(), cn.ravel(), strict=True)]).reshape(e.shape)
            # distance from the point to the neighbouring sheet's rectangle
            x0, y0 = (ce + dx) * SHEET, (cn + dy) * SHEET
            gx = np.maximum(np.maximum(x0 - e, e - (x0 + SHEET)), 0)
            gy = np.maximum(np.maximum(y0 - n, n - (y0 + SHEET)), 0)
            reach = np.where(gone, np.minimum(reach, np.hypot(gx, gy)), reach)
    return np.where(inside, np.clip(reach / FEATHER, 0, 1), 0.0)


def burn_tile(path, near, original):
    """Heights of one z12 tile with the sheets near it ({code: (bounds, tif)}) feathered in;
    None if no sheet has data under it."""
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject
    from pyproj import Transformer
    from PIL import Image

    x, y = tile_of(path)
    left, bottom, right, top = tile_bounds(x, y)
    transform = from_origin(left, top, TILE / 256, TILE / 256)
    lidar = np.full((256, 256), np.nan, np.float32)
    for _bounds, sheet in near.values():
        with rasterio.open(sheet) as source:
            part = np.full((256, 256), np.nan, np.float32)
            reproject(rasterio.band(source, 1), part, src_nodata=source.nodata, dst_transform=transform,
                      dst_crs='EPSG:3857', dst_nodata=np.nan, resampling=Resampling.average)
        lidar = np.where(np.isnan(lidar), part, lidar)
    if np.isnan(lidar).all():
        return None
    with Image.open(original) as image:
        base = decode(np.asarray(image.convert('RGB')))
    px = left + (np.arange(256) + .5) * TILE / 256
    py = top - (np.arange(256) + .5) * TILE / 256
    mx, my = np.meshgrid(px, py)
    e, n = Transformer.from_crs(3857, 3301, always_xy=True).transform(mx, my)
    weight = feather(np.asarray(e), np.asarray(n), [bounds for bounds, _ in near.values()])
    weight = np.where(np.isnan(lidar), 0, weight)
    return np.where(weight > 0, base + (np.nan_to_num(lidar) - base) * weight, base)


def burn_fine(x, y, near, upsampled):
    """{(a, b): heights} of the four z13 children of z12 tile x/y with the sheets near it
    feathered into upsampled(a, b), the z12 heights at z13 pixels; children without data skipped."""
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject
    from pyproj import Transformer

    out = {}
    size = TILE / 2
    px = size / 256
    to_est = Transformer.from_crs(3857, 3301, always_xy=True)
    for a, b in [(2 * x + i, 2 * y + j) for i in (0, 1) for j in (0, 1)]:
        left, top = -R + a * size, R - b * size
        # pixel centres on the pixel corners: pixel X samples the ground at X
        transform = from_origin(left - px / 2, top + px / 2, px, px)
        lidar = np.full((256, 256), np.nan, np.float32)
        for _bounds, sheet in near.values():
            with rasterio.open(sheet) as source:
                part = np.full((256, 256), np.nan, np.float32)
                reproject(rasterio.band(source, 1), part, src_nodata=source.nodata, dst_transform=transform,
                          dst_crs='EPSG:3857', dst_nodata=np.nan, resampling=Resampling.bilinear)
            lidar = np.where(np.isnan(lidar), part, lidar)
        if np.isnan(lidar).all():
            continue
        mx, my = np.meshgrid(left + np.arange(256) * px, top - np.arange(256) * px)
        e, n = to_est.transform(mx, my)
        weight = feather(np.asarray(e), np.asarray(n), [bounds for bounds, _ in near.values()])
        weight = np.where(np.isnan(lidar), 0, weight)
        base = upsampled(a, b)
        out[(a, b)] = np.where(weight > 0, base + (np.nan_to_num(lidar) - base) * weight, base)
    return out


def refine(tiles, cache, emit=print, kind=KIND, fetch=fetch_sheet):
    """Burn the DTM into the given cached z12 tile paths (fast_dem.audit). Returns the number of
    tiles changed. A tile is re-burnt only when its sheets change (cache/est/burnt.json)."""
    from pyproj import Transformer

    cache = Path(cache)
    tiles = [Path(p) for p in tiles if Path(p).exists() or (cache / 'terrain' / '12.orig' / Path(p).parent.name / Path(p).name).exists()]
    if not tiles:
        return 0
    to_est = Transformer.from_crs(4326, 3301, always_xy=True)

    def est_box(x, y, margin=0.0):
        """L-EST97 box around z12 tile x/y."""
        west, south, east, north = tile_bounds(x, y)
        corners = [to_est.transform(mx / R * 180, math.degrees(math.atan(math.sinh(my / R * math.pi))))
                   for mx in (west, east) for my in (south, north)]
        return (min(p[0] for p in corners) - margin, min(p[1] for p in corners) - margin,
                max(p[0] for p in corners) + margin, max(p[1] for p in corners) + margin)

    found = {}
    for path in tiles:
        for code, bounds in sheets(est_box(*tile_of(path))).items():
            found.setdefault(code, bounds)
    emit(f'Estonian DTM: {len(found)} sheets')
    covered = {}
    for k, (code, bounds) in enumerate(sorted(found.items())):
        sheet = fetch(code, cache, kind)
        if sheet is not None:
            covered[code] = (bounds, sheet)
        emit(f'Estonian DTM: {k + 1}/{len(found)} sheets')
    if not covered:
        return 0
    record = cache / 'est' / 'burnt.json'
    burnt = json.loads(record.read_text()) if record.exists() else {}
    changed = 0
    for path in tiles:
        x, y = tile_of(path)
        near = {code: covered[code] for code in sheets(est_box(x, y, SHEET)) if code in covered}
        if not near:
            continue
        stamp = hashlib.sha256(json.dumps(sorted(
            (c, os.path.getsize(v[1])) for c, v in near.items())).encode()).hexdigest()[:16]
        original = cache / 'terrain' / '12.orig' / str(x) / f'{y}.png'
        if burnt.get(f'{x}/{y}') == stamp and original.exists() and path.exists():
            continue
        if not original.exists():
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, original)
        heights = burn_tile(path, near, original)
        if heights is None:
            continue
        from PIL import Image
        part = path.with_suffix(f'.{os.getpid()}.png.part')
        Image.fromarray(encode(heights), 'RGB').save(part, format='PNG')
        os.replace(part, path)
        burnt[f'{x}/{y}'] = stamp
        changed += 1
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(burnt, sort_keys=True, indent=0))
    emit(f'Estonian DTM: {changed} terrain tiles refined')
    # z13 children once every z12 tile is final (the upsampled base reads the neighbours)
    from fast_sources import Terrain
    from PIL import Image
    fine, done, todo = Terrain(cache, zoom=13), 0, []
    for path in tiles:
        x, y = tile_of(path)
        stamp = burnt.get(f'{x}/{y}')
        if stamp and burnt.get(f'13/{x}/{y}') != stamp:
            todo.append((x, y, stamp))
    for k, (x, y, stamp) in enumerate(todo):
        near = {code: covered[code] for code in sheets(est_box(x, y, SHEET)) if code in covered}
        try:
            children = burn_fine(x, y, near, fine.upsampled)
        except FileNotFoundError:          # a neighbour at the cache's edge: z12 serves here
            continue
        for (a, b), heights in children.items():
            path = cache / 'terrain' / '13' / str(a) / f'{b}.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            part = path.with_suffix(f'.{os.getpid()}.png.part')
            Image.fromarray(encode(heights), 'RGB').save(part, format='PNG')
            os.replace(part, path)
        burnt[f'13/{x}/{y}'] = stamp
        done += 1
        if done % 100 == 0:
            emit(f'Estonian DTM: {k + 1}/{len(todo)} fine tiles')
            record.write_text(json.dumps(burnt, sort_keys=True, indent=0))
    record.write_text(json.dumps(burnt, sort_keys=True, indent=0))
    emit(f'Estonian DTM: {done} tiles refined at z13')
    return changed + done


def credit(tiles, cache, kind=KIND):
    """The Land Board's credit for a pack over the given z12 tile paths (fast_dem.audit) when any
    of them carries the DTM, else None. A burn outlives the build that made it, so the record
    (cache/est/burnt.json), not the build's flag, says so. The licence asks for the licensor, the
    data and its extraction date, and the licence's reference."""
    cache = Path(cache)
    record = cache / 'est' / 'burnt.json'
    if not record.exists():
        return None
    burnt = json.loads(record.read_text())
    if not any(f'{x}/{y}' in burnt for x, y in (tile_of(Path(p)) for p in tiles)):
        return None
    sheets_ = list((cache / 'est' / kind).glob('*.tif'))
    year = time.gmtime(max(p.stat().st_mtime for p in sheets_)).tm_year if sheets_ else None
    return {'source': 'Republic of Estonia Land and Spatial Development Board (Maa- ja Ruumiamet)',
            'data': 'Elevation data, 10 m DTM' + (f', extracted {year}' if year else ''),
            'license': 'Estonian Land Board open data licence',
            'url': 'https://geoportaal.maaruum.ee/opendata-licence'}


def restore(cache):
    """Put every original Terrarium tile back."""
    cache = Path(cache)
    origin = cache / 'terrain' / '12.orig'
    count = 0
    for original in origin.glob('*/*.png'):
        target = cache / 'terrain' / '12' / original.parent.name / original.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        os.utime(target)            # a new mtime: the region index rebuilds
        count += 1
    shutil.rmtree(cache / 'terrain' / '13', ignore_errors=True)
    record = cache / 'est' / 'burnt.json'
    if record.exists():
        record.unlink()
    return count


def main():
    import fast_dem
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--sources', help='cut source tiles (index.json)')
    p.add_argument('--cache', required=True, help='DEM cache holding terrain/12')
    p.add_argument('--restore', action='store_true')
    a = p.parse_args()
    if a.restore:
        print(f'restored {restore(a.cache)} tiles')
        return
    if not a.sources:
        p.error('--sources is needed')
    index = json.loads((Path(a.sources) / 'index.json').read_text(encoding='utf-8'))
    refine(fast_dem.audit(index, a.cache), a.cache)


if __name__ == '__main__':
    main()
