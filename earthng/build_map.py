"""Offline settlement search and road overviews from an OSM PBF.

python earthng/build_map.py --pbf data/pbf/albania.osm.pbf --out out/map-data/albania
The directory can ship in a country at map/, or in the planet at maps/<country id>/.
Existing country packs therefore need no geometry rebuild to gain map detail.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import tempfile

import osmium
from shapely.geometry import LineString
from PIL import Image, ImageDraw

VERSION = 1
PLACE_ZOOM = {'city': 7, 'town': 9, 'village': 11, 'hamlet': 13, 'suburb': 13, 'neighbourhood': 15}
ROAD_RANK = {'motorway': 1, 'trunk': 1, 'primary': 1, 'secondary': 2, 'tertiary': 3}
LEVELS = ((6, 4, 1, .002), (9, 1, 2, .0004), (11, 1, 3, .0001))


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


def raster_overviews(root, index):
    """Transparent road tiles for wide views: a few image draws instead of 6,000 lines/frame."""
    raster = {}
    colors = {1: (204, 122, 38, 255), 2: (184, 153, 89, 255), 3: (166, 166, 156, 255)}
    for zoom in range(5, 11):
        level = 6 if zoom < 9 else 9
        size = 256 * 2**zoom
        buckets, seen = defaultdict(list), set()
        for tile in index['tiles'].values():
            if tile['zoom'] != level:
                continue
            for line in json.loads((root / tile['file']).read_text(encoding='utf8')):
                key = tuple(line['geo'])
                if key in seen:
                    continue
                seen.add(key)
                points = []
                for lat, lon in zip(key[::2], key[1::2]):
                    lat = math.radians(max(-85.0511, min(85.0511, lat)))
                    points.append(((lon + 180) / 360 * size,
                                   (1 - math.asinh(math.tan(lat)) / math.pi) / 2 * size))
                xs, ys = zip(*points)
                for x in range(math.floor((min(xs)-3)/256), math.floor((max(xs)+3)/256)+1):
                    for y in range(max(0, math.floor((min(ys)-3)/256)), min(2**zoom-1, math.floor((max(ys)+3)/256))+1):
                        buckets[x, y].append((line['rank'], points))
        for (x, y), lines in buckets.items():
            image = Image.new('RGBA', (512, 512))
            draw = ImageDraw.Draw(image)
            for rank, points in sorted(lines, key=lambda item: -item[0]):
                xy = [((px-x*256)*2, (py-y*256)*2) for px, py in points]
                draw.line(xy, fill=colors[rank], width=4 if rank == 1 else 2, joint='curve')
            filename = f'r{zoom}_{x}_{y}.png'
            image.resize((256, 256), Image.Resampling.LANCZOS).save(root / filename)
            raster[f'{zoom}/{x}/{y}'] = filename
    index['raster'] = raster
    return index


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
        road_count = 0
        emit(f'Map: reading settlements and main roads from {pbf.name}')
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
                coords = [(nd.lon, nd.lat) for nd in obj.nodes]
                for key, box, level, item in road_tiles(coords, rank):
                    # Spool JSON lines: memory is bounded by a small batch per spatial tile.
                    tiles[key] = {'box': box, 'zoom': level, 'file': key + '.json'}
                    buffers[key].append(json.dumps(item, separators=(',', ':')))
                    if len(buffers[key]) >= 128:
                        with (root / (key + '.part')).open('a', encoding='utf8') as f:
                            f.write('\n'.join(buffers.pop(key)) + '\n')
                road_count += 1
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
