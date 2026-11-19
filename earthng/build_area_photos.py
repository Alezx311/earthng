"""Cache georeferenced Sentinel-2 RGB sheets for a Map Builder selection.

Only the builder uses the WMS. Packs contain mipmapped DXT5 sheets and an index, so all
map views in the game remain offline. Large selections use a coarser grid to
bound downloads, pack size and texture residency.
"""
import io
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image
from map_photo_codec import save_photo

SERVICE = 'https://titiler.terrascope.be/wms'
LAYER = 'esa-worldcover-s2rgbnir-10m-2021-v2_tcc'
CREDIT = 'ESA WorldCover 2021 / Copernicus Sentinel-2'
ATTRIBUTION = ('© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data '
               '(2021) processed by ESA WorldCover consortium')
ORIGIN = math.pi * 6378137
SIZE, MAX_SHEETS, ZOOM = 512, 64, 13


def mercator(lon, lat):
    lat = max(-85.05112878, min(85.05112878, lat))
    return (lon + 180) / 360, max(0, min(1, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2))


def plan(box):
    """Fixed Web Mercator sheets, at most MAX_SHEETS for any valid selection."""
    w, s, e, n = box
    if not all(math.isfinite(v) for v in box) or not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError('invalid imagery bounds')
    x0, y0 = mercator(w, n)
    x1, y1 = mercator(e, s)
    for z in range(ZOOM, -1, -1):
        scale = 2 ** z
        a, b = max(0, math.floor(x0 * scale)), max(0, math.floor(y0 * scale))
        c, d = min(scale - 1, math.ceil(x1 * scale) - 1), min(scale - 1, math.ceil(y1 * scale) - 1)
        if (c - a + 1) * (d - b + 1) <= MAX_SHEETS:
            return [(z, x, y) for y in range(b, d + 1) for x in range(a, c + 1)]


def request_url(z, x, y):
    step = 2 * ORIGIN / 2 ** z
    left, top = -ORIGIN + x * step, ORIGIN - y * step
    params = dict(service='WMS', version='1.3.0', request='GetMap', layers=LAYER,
                  styles='', crs='EPSG:3857', bbox=','.join(map(str, (left, top - step, left + step, top))),
                  width=SIZE, height=SIZE, format='image/png', transparent='TRUE', time='2021-01-01')
    return SERVICE + '?' + urlencode(params)


def fetch(z, x, y):
    request = Request(request_url(z, x, y), headers={'User-Agent': 'EarthNG MapBuilder (offline map imagery)'})
    with urlopen(request, timeout=25) as response:
        data = response.read(12 * 1024 * 1024 + 1)
    if len(data) > 12 * 1024 * 1024:
        raise ValueError('imagery response too large')
    with Image.open(io.BytesIO(data)) as source:
        if source.size != (SIZE, SIZE):
            raise ValueError('unexpected imagery dimensions')
        image = source.convert('RGBA')
        image.load()
    return image


def build(box, cache, emit=print, cancel=None):
    """Prepare the selection's photo index. Reuse each completed tile on retry.

    Service failure keeps already completed imagery and leaves the chart available;
    the next build retries missing sheets. Cancellation always stops the export.
    """
    cache = Path(cache) / 'worldcover-2021-v2'
    cache.mkdir(parents=True, exist_ok=True)
    sheets = []
    tasks = plan(box)
    emit(f'Map imagery: {len(tasks)} offline sheets (ESA WorldCover 2021)')
    failed = 0
    for z, x, y in tasks:
        if cancel is not None and cancel.is_set():
            raise InterruptedError('build stopped')
        name = f's2-{z}-{x}-{y}.dds'
        path = cache / name
        try:
            if not path.is_file():
                image = fetch(z, x, y)
                # Empty ocean/no-data is still cached, avoiding repeated service requests.
                tmp = path.with_suffix('.tmp')
                save_photo(image, tmp)
                tmp.replace(path)
            with Image.open(path) as image:
                if image.size != (SIZE, SIZE):
                    raise ValueError('invalid cached imagery dimensions')
                if not image.convert('RGBA').getchannel('A').getbbox():
                    continue
        except (OSError, ValueError) as exc:
            path.unlink(missing_ok=True)
            failed += 1
            emit(f'Map imagery: {name} unavailable ({exc}); keeping the chart there')
            # An unavailable service must not delay a whole country by dozens of timeouts.
            if failed >= 3:
                break
            continue
        scale = 2 ** z
        sheets.append(dict(file=name, box=[x / scale, y / scale, (x + 1) / scale, (y + 1) / scale],
                           minZoom=6, maxZoom=18, credit=CREDIT))
    if cancel is not None and cancel.is_set():
        raise InterruptedError('build stopped')
    # A per-selection index avoids including unrelated cached tiles in a new pack.
    import hashlib
    key = hashlib.sha256(json.dumps(box).encode()).hexdigest()[:16]
    target = cache / ('selection-' + key + '.json')
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(sheets, separators=(',', ':')), encoding='utf8')
    tmp.replace(target)
    return target


def write_archive(archive, index, prefix):
    import zipfile
    index = Path(index)
    sheets = json.loads(index.read_text(encoding='utf8'))
    archive.writestr(prefix + '/index.json', json.dumps(sheets, separators=(',', ':')),
                     compress_type=zipfile.ZIP_DEFLATED)
    for sheet in sheets:
        archive.write(index.parent / sheet['file'], prefix + '/' + sheet['file'],
                      compress_type=zipfile.ZIP_STORED)
