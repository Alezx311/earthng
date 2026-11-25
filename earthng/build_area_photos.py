"""Cache georeferenced Sentinel-2 RGB sheets for a Map Builder selection.

Only the builder uses the WMS. Packs contain mipmapped DXT sheets and an index, so all
map views in the game remain offline.

The sheets are a pyramid (levels): the finest level the budget of FINE sheets allows (a town at
10 m a pixel, Ukraine at 100 m), and under it coarser levels two zooms apart down to a handful of
sheets, so a wide view draws a few small textures and a close one only the fine sheets under it
(planetMap.lua drawPhotos: a sheet shows between its minZoom and maxZoom and the finer level
comes in over it). Until 24.11 a selection had one level of at most 64 sheets: a country was
300 m a pixel, a blur at any zoom a driver looks at.

Only the finest level is fetched. A coarser sheet is put together here from the sixteen under
it: the service mosaics its 10 m source for every request, and a sheet a thousand kilometres
wide timed out (Ukraine's zoom 5, 24.11).

An existing pack gets its imagery as a second ZIP that installs beside it (the same paths in the
game's file system), without rebuilding the pack:

    python earthng/build_area_photos.py --pack earthng_ukraine.zip --out out/photos
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
SIZE, ZOOM = 512, 13
FINE = 520           # sheets of the finest level at most
MAX_SHEETS = 600     # of the whole pyramid
STEP = 2             # zooms between two levels: a sheet of one covers 16 of the next
FLOOR = 6            # a sheet shows from this zoom at the least (the planet's own picture ends there)
# The service is a public one and says when it has had enough (HTTP 429 after ~350 sheets asked
# four at a time, 24.11): one request at a time with a pause, and a 429 or 503 is waited out as
# long as its Retry-After says (WAIT at most, RETRIES times) before the build gives the sheet up.
# What was fetched stays in the cache, so the next run only asks for the rest.
WORKERS = 1          # sheets asked for at once
PAUSE = .6           # s between two requests
WAIT, RETRIES = 120, 3
# The composite is surface reflectance: true to the ground and dark as a map (a forest is 25 of
# 255, a field 70), names and roads sink in it. A sheet is lifted before it is saved: gamma, gain,
# saturation (Kyiv oblast side by side, 24.11: .70 / 1.15 / 1.2 reads, .60 / 1.2 / 1.3 washes out).
TONE = (.70, 1.15, 1.2)
# the cache: sheets as the service gave them (until 24.11 a pack carried these) and the toned ones
RAW, TONED = 'worldcover-2021-v2', 'worldcover-2021-v2-tone1'


def mercator(lon, lat):
    lat = max(-85.05112878, min(85.05112878, lat))
    return (lon + 180) / 360, max(0, min(1, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2))


def _valid(box):
    w, s, e, n = box
    if not all(math.isfinite(v) for v in box) or not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError('invalid imagery bounds')


def _level(z, boxes):
    """The sheets of zoom z that touch any of the boxes, in reading order."""
    scale, found = 2 ** z, set()
    for w, s, e, n in boxes:
        x0, y0 = mercator(w, n)
        x1, y1 = mercator(e, s)
        a, b = max(0, math.floor(x0 * scale)), max(0, math.floor(y0 * scale))
        c, d = min(scale - 1, math.ceil(x1 * scale) - 1), min(scale - 1, math.ceil(y1 * scale) - 1)
        if (c - a + 1) * (d - b + 1) > 4 * MAX_SHEETS:
            return None       # far too many: not worth listing
        found.update((x, y) for y in range(b, d + 1) for x in range(a, c + 1))
    return sorted(found, key=lambda t: (t[1], t[0]))


def levels(box, coverage=None):
    """The pyramid of a selection, coarsest first: [(zoom, [(x, y), ...]), ...]. coverage: the
    boxes the pack really covers inside its bounds (a sheet over none of them is not fetched)."""
    _valid(box)
    boxes = [box]
    if coverage:
        for c in coverage:
            _valid(c)
        boxes = [list(c) for c in coverage]
    fine = None
    for z in range(ZOOM, -1, -1):
        sheets = _level(z, boxes)
        if sheets is not None and len(sheets) <= FINE:
            fine = (z, sheets)
            break
    out = [fine]
    # coarser levels while they still save a wide view anything, and not past the zoom the
    # planet's own picture takes over at (a sheet of zoom z is whole at view zoom z + 1)
    while len(out[0][1]) > 4 and out[0][0] - STEP >= FLOOR - 1:
        z = out[0][0] - STEP
        out.insert(0, (z, _level(z, boxes)))
    return out


def plan(box, coverage=None):
    """Fixed Web Mercator sheets of every level, at most MAX_SHEETS for any valid selection."""
    return [(z, x, y) for z, sheets in levels(box, coverage) for x, y in sheets]


def zooms(box, coverage=None):
    """zoom of a level -> (minZoom, maxZoom) its sheets show at: the coarsest from FLOOR, each up
    to the zoom before the next level's, the finest to the end."""
    pyramid = [z for z, _ in levels(box, coverage)]
    out = {}
    for k, z in enumerate(pyramid):
        low = FLOOR if k == 0 else max(FLOOR, z)
        high = 18 if k == len(pyramid) - 1 else max(low, max(FLOOR, pyramid[k + 1]) - 1)
        out[z] = (low, high)
    return out


def request_url(z, x, y):
    step = 2 * ORIGIN / 2 ** z
    left, top = -ORIGIN + x * step, ORIGIN - y * step
    params = dict(service='WMS', version='1.3.0', request='GetMap', layers=LAYER,
                  styles='', crs='EPSG:3857', bbox=','.join(map(str, (left, top - step, left + step, top))),
                  width=SIZE, height=SIZE, format='image/png', transparent='TRUE', time='2021-01-01')
    return SERVICE + '?' + urlencode(params)


def fetch(z, x, y, sleep=None):
    import time
    from urllib.error import HTTPError
    sleep = sleep or time.sleep
    request = Request(request_url(z, x, y), headers={'User-Agent': 'EarthNG MapBuilder (offline map imagery)'})
    for attempt in range(RETRIES + 1):
        try:
            with urlopen(request, timeout=40) as response:
                data = response.read(12 * 1024 * 1024 + 1)
            break
        except HTTPError as exc:
            if exc.code not in (429, 503) or attempt == RETRIES:
                raise
            try:
                asked = float(exc.headers.get('Retry-After') or 0)
            except (TypeError, ValueError):
                asked = 0
            sleep(min(WAIT, max(asked, 15 * (attempt + 1))))
    sleep(PAUSE)
    if len(data) > 12 * 1024 * 1024:
        raise ValueError('imagery response too large')
    with Image.open(io.BytesIO(data)) as source:
        if source.size != (SIZE, SIZE):
            raise ValueError('unexpected imagery dimensions')
        image = source.convert('RGBA')
        image.load()
    return image


def tone(image):
    """The sheet lifted for a map (TONE); its alpha stays."""
    from PIL import ImageEnhance
    gamma, gain, saturation = TONE
    lut = [min(255, round(255 * (i / 255) ** gamma * gain)) for i in range(256)]
    rgba = image.convert('RGBA')
    out = ImageEnhance.Color(rgba.convert('RGB').point(lut * 3)).enhance(saturation).convert('RGBA')
    out.putalpha(rgba.getchannel('A'))
    return out


def _obtain(cache, z, x, y):
    """The cached sheet's file name, None for empty ocean or no data; fetched when missing (a
    sheet an earlier build fetched and kept untoned is toned, not fetched again)."""
    name = f's2-{z}-{x}-{y}.dds'
    path = cache / name
    try:
        if not path.is_file():
            raw = cache.parent / RAW / name
            if raw.is_file():
                with Image.open(raw) as kept:
                    image = kept.convert('RGBA')
            else:
                image = fetch(z, x, y)
            # Empty ocean/no-data is still cached, avoiding repeated service requests.
            tmp = path.with_suffix(f'.{x}-{y}.tmp')
            save_photo(tone(image), tmp)
            tmp.replace(path)
        with Image.open(path) as image:
            if image.size != (SIZE, SIZE):
                raise ValueError('invalid cached imagery dimensions')
            if not image.convert('RGBA').getchannel('A').getbbox():
                return None
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        raise
    return name


def _compose(cache, key, z, x, y, names):
    """A coarser sheet from the sheets STEP zooms under it (names: (z, x, y) -> file or None);
    its file name, None where none of them has anything. The file belongs to the selection
    (key): another selection has other sheets under the same square."""
    side = 2 ** STEP
    canvas, any_child = Image.new('RGBA', (SIZE * side, SIZE * side), (0, 0, 0, 0)), False
    for j in range(side):
        for i in range(side):
            child = names.get((z + STEP, x * side + i, y * side + j))
            if child:
                with Image.open(cache / child) as image:
                    canvas.paste(image.convert('RGBA'), (i * SIZE, j * SIZE))
                any_child = True
    if not any_child:
        return None
    name = f'c{key}-{z}-{x}-{y}.dds'
    tmp = (cache / name).with_suffix('.tmp')
    save_photo(canvas.resize((SIZE, SIZE), Image.Resampling.BOX), tmp)
    tmp.replace(cache / name)
    return name


def build(box, cache, emit=print, cancel=None, coverage=None):
    """Prepare the selection's photo index. Reuse each completed tile on retry.

    Service failure keeps already completed imagery and leaves the chart available;
    the next build retries missing sheets. Cancellation always stops the export.
    """
    from concurrent.futures import ThreadPoolExecutor
    cache = Path(cache) / TONED
    cache.mkdir(parents=True, exist_ok=True)
    import hashlib
    key = hashlib.sha256(json.dumps([box, coverage]).encode()).hexdigest()[:16]
    pyramid = levels(box, coverage)
    shown = zooms(box, coverage)
    # the finest level is fetched, the others are put together from it
    tasks = [(pyramid[-1][0], x, y) for x, y in pyramid[-1][1]]
    emit(f'Map imagery: {len(tasks)} offline sheets, {len(pyramid)} levels (ESA WorldCover 2021)')
    names, failed, answered, at = {}, 0, False, 0

    def stopped():
        return cancel is not None and cancel.is_set()

    def one(task):
        if stopped():
            raise InterruptedError('build stopped')
        return _obtain(cache, *task)

    with ThreadPoolExecutor(WORKERS) as pool:
        while at < len(tasks) and failed < 3:
            if stopped():
                raise InterruptedError('build stopped')
            # one at a time until the service has answered: an unavailable service must not
            # delay a whole country by dozens of timeouts
            batch = tasks[at:at + (WORKERS if answered else 1)]
            at += len(batch)
            for task, job in [(task, pool.submit(one, task)) for task in batch]:
                try:
                    names[task] = job.result()
                    answered = True
                except InterruptedError:
                    raise
                except (OSError, ValueError) as exc:
                    failed += 1
                    emit(f'Map imagery: s2-{task[0]}-{task[1]}-{task[2]} unavailable ({exc}); keeping the chart there')
            if at % 80 < len(batch) and at < len(tasks):
                emit(f'Map imagery: {at} of {len(tasks)} sheets')
    if stopped():
        raise InterruptedError('build stopped')
    for z, tiles in reversed(pyramid[:-1]):
        for x, y in tiles:
            names[(z, x, y)] = _compose(cache, key, z, x, y, names)
    sheets = []
    for z, tiles in pyramid:
        for x, y in tiles:
            name = names.get((z, x, y))
            if name:
                scale = 2 ** z
                low, high = shown[z]
                sheets.append(dict(file=name, box=[x / scale, y / scale, (x + 1) / scale, (y + 1) / scale],
                                   minZoom=low, maxZoom=high, credit=CREDIT))
    # A per-selection index avoids including unrelated cached tiles in a new pack.
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


def pack_targets(pack):
    """What an installed pack covers: [(folder in the game's file system, bounds, coverage)], one
    for the country or for each of its sections, from the manifests in the ZIP."""
    import zipfile
    found = []
    with zipfile.ZipFile(pack) as archive:
        for name in archive.namelist():
            parts = name.split('/')
            country = len(parts) == 4 and parts[:2] == ['earthng', 'countries'] and parts[3] == 'manifest.json'
            section = (len(parts) == 6 and parts[:2] == ['earthng', 'countries'] and parts[3] == 'sections'
                       and parts[5] == 'manifest.json')
            if not (country or section):
                continue
            manifest = json.loads(archive.read(name))
            coverage = [c[:4] for c in manifest.get('coverage') or [] if len(c) >= 4]
            if not coverage:
                continue
            bounds = [min(c[0] for c in coverage), min(c[1] for c in coverage),
                      max(c[2] for c in coverage), max(c[3] for c in coverage)]
            found.append(('/'.join(parts[:-1]), bounds, coverage))
    # a country whose sections carry their own manifests: the sections are what is installed
    sections = [f for f in found if '/sections/' in f[0]]
    return sections or found


def addon(pack, out, cache, emit=print):
    """<pack>_photos.zip in `out`: the imagery of an installed pack, to install beside it."""
    import zipfile
    pack, out = Path(pack), Path(out)
    targets = pack_targets(pack)
    if not targets:
        raise ValueError(f'{pack.name}: no manifest with coverage')
    out.mkdir(parents=True, exist_ok=True)
    path = out / (pack.stem + '_photos.zip')
    tmp = path.with_suffix('.tmp')
    total = 0
    with zipfile.ZipFile(tmp, 'w') as archive:
        for folder, bounds, coverage in targets:
            index = build(bounds, cache, emit, coverage=coverage)
            total += len(json.loads(index.read_text(encoding='utf8')))
            write_archive(archive, index, folder + '/photos')
    tmp.replace(path)
    emit(f'{path.name}: {total} sheets, {path.stat().st_size / 2**20:.0f} MB')
    return path


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Map imagery for an installed pack, as a ZIP to install beside it')
    parser.add_argument('--pack', required=True, type=Path, action='append', help='earthng_<id>.zip (repeatable)')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--cache', type=Path, default=Path(__file__).resolve().parents[1] / 'data' / 'map-imagery')
    parser.add_argument('--plan', action='store_true', help='only say how many sheets each level takes')
    args = parser.parse_args()
    for pack in args.pack:
        if args.plan:
            for folder, bounds, coverage in pack_targets(pack):
                shown = zooms(bounds, coverage)
                for z, sheets in levels(bounds, coverage):
                    metres = 2 * ORIGIN / 2 ** z / SIZE * math.cos(math.radians((bounds[1] + bounds[3]) / 2))
                    print(f'{folder}: zoom {z}: {len(sheets)} sheets, {metres:.0f} m a pixel, shown at {shown[z][0]}-{shown[z][1]}')
        else:
            addon(pack, args.out, args.cache)
