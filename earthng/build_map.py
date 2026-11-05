"""Offline settlement search and road overviews from an OSM PBF.

python earthng/build_map.py --pbf data/pbf/albania.osm.pbf --out out/map-data/albania
The directory can ship in a country at map/, or in the planet at maps/<country id>/.
Existing country packs therefore need no geometry rebuild to gain map detail.
"""
import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import tempfile

import osmium
from shapely.geometry import LineString
from PIL import Image, ImageDraw

VERSION = 1
PLACE_ZOOM = {'city': 7, 'town': 9, 'village': 11, 'hamlet': 13, 'suburb': 13, 'neighbourhood': 15}
ROAD_RANK = {'motorway': 1, 'trunk': 1, 'primary': 1, 'secondary': 2, 'tertiary': 3}
LEVELS = ((6, 4, 1, .002), (9, 1, 2, .0004), (11, 1, 3, .0001))
SPOOL = 64 << 20   # characters of road JSON held before they go to the part files


def encode(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf8')


def settlement(lat, lon, tags):
    kind = tags.get('place')
    name = tags.get('name') or tags.get('name:en') or tags.get('name:uk')
    if kind not in PLACE_ZOOM or not name:
        return None
    try:
        population = max(0, int(tags.get('population', '0').replace(' ', '')))
    except ValueError:
        population = 0
    aliases = sorted({v for k, v in tags.items() if k.startswith('name:') or k in ('name', 'alt_name', 'int_name', 'official_name')})
    context = tags.get('addr:district') or tags.get('is_in') or ''
    return [round(lat, 6), round(lon, 6), PLACE_ZOOM[kind], tags.get('name:en') or name,
            tags.get('name:uk') or name, int(tags.get('capital') == 'yes'), population, kind, ';'.join(aliases), context]


def road_tiles(coords, rank):
    """Keep endpoints/bends and use bounded geographic tiles at each scale."""
    if len(coords) < 2:
        return
    line = LineString(coords)
    for level, size, max_rank, tolerance in LEVELS:
        if rank > max_rank:
            continue
        simplified = line.simplify(tolerance, preserve_topology=False)
        w, s, e, n = simplified.bounds
        geo = [round(v, 6) for lon, lat in simplified.coords for v in (lat, lon)]
        item = {'rank': rank, 'box': [s, w, n, e], 'geo': geo}
        for x in range(math.floor(w / size), math.floor(e / size) + 1):
            for y in range(math.floor(s / size), math.floor(n / size) + 1):
                yield f'{level}_{x}_{y}', [x * size, y * size, (x + 1) * size, (y + 1) * size], level, item


def _tiles_of(level, size, rank, w, s, e, n, geo):
    item = {'rank': rank, 'box': [s, w, n, e], 'geo': geo}
    for x in range(math.floor(w / size), math.floor(e / size) + 1):
        for y in range(math.floor(s / size), math.floor(n / size) + 1):
            yield f'{level}_{x}_{y}', [x * size, y * size, (x + 1) * size, (y + 1) * size], level, item


def road_tiles_many(roads):
    """road_tiles of each (rank, coords) in turn, the same items in the same order, with the
    simplification of a whole batch in one GEOS call per level."""
    import numpy
    import shapely
    found = [[] for _ in roads]
    for level, size, max_rank, tolerance in LEVELS:
        picked = [i for i, (rank, coords) in enumerate(roads) if rank <= max_rank and len(coords) >= 2]
        if not picked:
            continue
        counts = [len(roads[i][1]) for i in picked]
        flat = numpy.array([point for i in picked for point in roads[i][1]], dtype=float)
        lines = shapely.linestrings(flat, indices=numpy.repeat(numpy.arange(len(picked)), counts))
        simple = shapely.simplify(lines, tolerance, preserve_topology=False)
        bounds = shapely.bounds(simple).tolist()
        points, owner = shapely.get_coordinates(simple, return_index=True)
        starts = numpy.searchsorted(owner, numpy.arange(len(picked) + 1)).tolist()
        points = points.tolist()
        for j, i in enumerate(picked):
            geo = [round(v, 6) for lon, lat in points[starts[j]:starts[j + 1]] for v in (lat, lon)]
            found[i].append(_tiles_of(level, size, roads[i][0], *bounds[j], geo))
    for tiles in found:
        for level_tiles in tiles:
            yield from level_tiles


def _render(root, zoom, x, y, lines, colors):
    image = Image.new('RGBA', (512, 512))
    draw = ImageDraw.Draw(image)
    for rank, points in sorted(lines, key=lambda item: -item[0]):
        xy = [((px-x*256)*2, (py-y*256)*2) for px, py in points]
        draw.line(xy, fill=colors[rank], width=4 if rank == 1 else 2, joint='curve')
    filename = f'r{zoom}_{x}_{y}.png'
    image.resize((256, 256), Image.Resampling.LANCZOS).save(root / filename)
    return filename


def raster_overviews(root, index):
    """Transparent road tiles for wide views: a few image draws instead of 6,000 lines/frame."""
    from concurrent.futures import ThreadPoolExecutor
    raster = {}
    colors = {1: (204, 122, 38, 255), 2: (184, 153, 89, 255), 3: (166, 166, 156, 255)}
    unique = {}
    # Pillow releases the GIL while it resamples and compresses: tiles render on threads, and
    # the index keeps their order.
    with ThreadPoolExecutor(min(8, os.cpu_count() or 1)) as pool:
        for zoom in range(5, 11):
            level = 6 if zoom < 9 else 9
            size = 256 * 2**zoom
            if level not in unique:
                # each line once per level, in tile order: what every zoom of the level draws
                lines, seen = [], set()
                for tile in index['tiles'].values():
                    if tile['zoom'] != level:
                        continue
                    for line in json.loads((root / tile['file']).read_text(encoding='utf8')):
                        key = tuple(line['geo'])
                        if key not in seen:
                            seen.add(key)
                            lines.append((line['rank'], key))
                unique[level] = lines
            buckets = defaultdict(list)
            for rank, key in unique[level]:
                points = []
                for lat, lon in zip(key[::2], key[1::2]):
                    lat = math.radians(max(-85.0511, min(85.0511, lat)))
                    points.append(((lon + 180) / 360 * size,
                                   (1 - math.asinh(math.tan(lat)) / math.pi) / 2 * size))
                xs, ys = zip(*points)
                for x in range(math.floor((min(xs)-3)/256), math.floor((max(xs)+3)/256)+1):
                    for y in range(max(0, math.floor((min(ys)-3)/256)), min(2**zoom-1, math.floor((max(ys)+3)/256))+1):
                        buckets[x, y].append((rank, points))
            jobs = [((x, y), pool.submit(_render, root, zoom, x, y, lines, colors)) for (x, y), lines in buckets.items()]
            for (x, y), job in jobs:
                raster[f'{zoom}/{x}/{y}'] = job.result()
    index['raster'] = raster
    return index


def _osmium_source(pbf, places):
    """Settlements into places; yields (rank, [(lon, lat)]) of main roads with every node located."""
    # C++ filters skip the millions of untagged geometry nodes before crossing into Python;
    # the location handler still sees those nodes, so ways keep their complete geometry.
    tags = [('place', k) for k in PLACE_ZOOM] + [('highway', k + suffix) for k in ROAD_RANK for suffix in ('', '_link')]
    processor = osmium.FileProcessor(str(pbf)).with_locations().with_filter(osmium.filter.TagFilter(*tags))
    for obj in processor:
        if obj.is_node() and obj.location.valid() and obj.tags.get('place') in PLACE_ZOOM:
            p = settlement(obj.location.lat, obj.location.lon, dict(obj.tags))
            if p:
                places.append(p)
        elif obj.is_way():
            rank = ROAD_RANK.get(obj.tags.get('highway', '').removesuffix('_link'))
            if not rank or not all(nd.location.valid() for nd in obj.nodes):
                continue
            yield rank, [(nd.lon, nd.lat) for nd in obj.nodes]


def _main_roads(pbf, places, emit):
    """The PBF pass: native (earthng-mapbuilder map-source) when it is here, else osmium."""
    import native_tool
    try:
        # the native reader takes .pbf only; osmium also reads .osm XML (the tests' samples)
        found = native_tool.map_source(pbf, emit) if Path(pbf).name.endswith('.pbf') else None
    except (OSError, RuntimeError, ValueError) as exc:
        emit(f'Map: native reader failed ({exc}); reading with osmium')
        found = None
    if found is None:
        yield from _osmium_source(pbf, places)
        return
    native_places, roads = found
    for lat, lon, pairs in native_places:
        # osmium Tags.get is the first value of a key, dict() keeps the last: both as osmium had them
        place = next((v for k, v in pairs if k == 'place'), None)
        if place in PLACE_ZOOM and -90 <= lat <= 90 and -180 <= lon <= 180:
            p = settlement(lat, lon, dict(pairs))
            if p:
                places.append(p)
    yield from roads


def _batches(items, size):
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def build(pbf, out, emit=print):
    pbf, out = Path(pbf), Path(out)
    stamp = [VERSION, pbf.name, pbf.stat().st_size, pbf.stat().st_mtime_ns]
    marker = out / 'index.json'
    if marker.exists() and json.loads(marker.read_text(encoding='utf8')).get('sourceStamp') == stamp:
        index = json.loads(marker.read_text(encoding='utf8'))
        if 'raster' not in index:
            encode(marker, raster_overviews(out, index))
        return out
    # A source change must use a new output directory; never leave mixed generations.
    if out.exists():
        raise ValueError(f'{out} already exists with another source; choose a new map output directory')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='earthng-map-', dir=out.parent) as work:
        root = Path(work) / 'map'
        root.mkdir()
        places, tiles, buffers = [], {}, defaultdict(list)
        road_count = buffered = 0
        emit(f'Map: reading settlements and main roads from {pbf.name}')
        for batch in _batches(_main_roads(pbf, places, emit), 4096):
            road_count += len(batch)
            for key, box, level, item in road_tiles_many(batch):
                tiles[key] = {'box': box, 'zoom': level, 'file': key + '.json'}
                text = json.dumps(item, separators=(',', ':'))
                buffers[key].append(text)
                buffered += len(text)
                if buffered >= SPOOL:
                    # Spool JSON lines: memory stays bounded, and each tile's part file opens once
                    # per spool rather than once per 128 lines (8,000 opens on Argentina).
                    for name in list(buffers):
                        with (root / (name + '.part')).open('a', encoding='utf8') as f:
                            f.write('\n'.join(buffers.pop(name)) + '\n')
                    buffered = 0
        for key in sorted(tiles):
            part = root / (key + '.part')
            with (root / (key + '.json')).open('w', encoding='utf8') as dest:
                dest.write('[')
                first = True
                if part.exists():
                    with part.open(encoding='utf8') as src:
                        for line in src:
                            dest.write(('' if first else ',') + line.strip())
                            first = False
                    part.unlink()
                for line in buffers.pop(key, []):
                    dest.write(('' if first else ',') + line)
                    first = False
                dest.write(']')
        places.sort(key=lambda p: (p[2], -p[6], p[3], p[0], p[1]))
        encode(root / 'places.json', places)
        index = {'version': VERSION, 'sourceStamp': stamp, 'source': 'OpenStreetMap contributors',
                 'license': 'ODbL-1.0', 'places': len(places), 'roads': road_count, 'tiles': tiles}
        encode(root / 'index.json', raster_overviews(root, index))
        root.replace(out)
    emit(f'Map: {len(places)} settlements, {road_count} roads, {len(tiles)} overview tiles')
    return out


def write_archive(archive, directory, prefix):
    import zipfile
    for path in sorted(Path(directory).iterdir()):
        if path.suffix in ('.json', '.png'):
            archive.write(path, prefix.rstrip('/') + '/' + path.name, compress_type=zipfile.ZIP_DEFLATED)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pbf', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    build(args.pbf, args.out)
