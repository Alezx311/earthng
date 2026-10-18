"""A small pack round one point (about 10 x 10 km) from a city extract, for showcase shots.

    python earthng/spot_pack.py --id rio --title "Rio de Janeiro" --lat -22.955 --lon -43.185 --look-of brazil --source https://download.bbbike.org/osm/bbbike/RiodeJaneiro/RiodeJaneiro.osm.pbf

The source is a city extract (BBBike), a small Geofabrik region or a local .osm.pbf, so no
country PBF is downloaded. Tiles are cut only under the square round the point, heights are
fetched for them, and out/spots/earthng_spot-<id>.zip is written: the same cut, DEM and exporter
as country_fetch.py, on a smaller area. The pack is an ordinary country for the planet mod.
"""
import argparse
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import country_fetch  # noqa: E402
import looks  # noqa: E402
from osm_tiles import BUFFER, CELL  # noqa: E402
import places  # noqa: E402


def spot_box(lat, lon, km):
    """Package box of the cells under a km x km square round the point. osm_tiles keeps a tile
    only when its cell plus BUFFER fits inside the box, hence the pad."""
    dlat = km / 2 / 111.32
    dlon = km / 2 / (111.32 * math.cos(math.radians(lat)))
    x0, x1 = math.floor((lon - dlon) / CELL), math.floor((lon + dlon) / CELL)
    y0, y1 = math.floor((lat - dlat) / CELL), math.floor((lat + dlat) / CELL)
    pad = BUFFER + 0.002
    return [round(x0 * CELL - pad, 6), round(y0 * CELL - pad, 6),
            round((x1 + 1) * CELL + pad, 6), round((y1 + 1) * CELL + pad, 6)]


def source_pbf(source, emit=print):
    """A local path as it is; a URL downloaded once into data/pbf/spot-<file name>."""
    if not source.startswith(('http://', 'https://')):
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    name = source.rstrip('/').rsplit('/', 1)[-1]
    return country_fetch.download(source, ROOT / 'data' / 'pbf' / f'spot-{name}', emit)


def check_extent(pbf, box, emit=print):
    import osmium
    header = osmium.io.Reader(str(pbf), osmium.osm.osm_entity_bits.NOTHING).header().box()
    if not header.valid():
        return
    w, s, e, n = header.bottom_left.lon, header.bottom_left.lat, header.top_right.lon, header.top_right.lat
    if box[0] < w or box[1] < s or box[2] > e or box[3] > n:
        emit(f'warning: the extract covers {w:.3f},{s:.3f},{e:.3f},{n:.3f}, the spot {box}; edge cells may be empty')


def build_spot(spot_id, title, lat, lon, km, source, look, out, jobs=2, landing=None, emit=print):
    import json
    import build_country

    country_id = places.slug(f'spot-{spot_id}')
    box = spot_box(lat, lon, km)
    emit(f'{title}: box {box}')
    pbf = source_pbf(source, emit)
    check_extent(pbf, box, emit)
    tiles = country_fetch.tiles_dir(ROOT, country_id, box)
    if not (tiles / 'index.json').exists():
        emit(f'cutting tiles into {tiles.name}')
        country_fetch.run_step([country_fetch._python(), str(HERE / 'osm_tiles_country.py'), str(pbf),
                                '--out', str(tiles), '--jobs', str(jobs),
                                '--package-box', *(str(v) for v in box)], emit)
    index = json.loads((tiles / 'index.json').read_text(encoding='utf-8'))
    emit(f"{len(index['tiles'])} tiles")
    dem = ROOT / 'out' / 'world' / 'cache'
    country_fetch.fetch_dem(index, dem, emit)
    regions = build_country.grid_regions(tiles, dem, ROOT / 'out' / 'world', emit=emit)
    return build_country.build_country(country_id, title, '0.4.0', regions, out, emit=emit, jobs=jobs,
                                       landing=landing or (lat, lon), look=look)


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--id', required=True, help='short name; the pack is earthng_spot-<id>.zip')
    p.add_argument('--title', required=True)
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--km', type=float, default=10, help='side of the square round the point')
    p.add_argument('--source', required=True, help='URL or path of an .osm.pbf that covers the square')
    p.add_argument('--look-of', default='', help='Geofabrik id whose asset block the spot uses (e.g. brazil)')
    p.add_argument('--block', default='', help='asset block id instead of --look-of')
    p.add_argument('--landing', type=float, nargs=2, metavar=('LAT', 'LON'))
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--out', type=Path, default=ROOT / 'out' / 'spots')
    a = p.parse_args()
    if a.block:
        block = looks.BLOCK_BY_ID.get(a.block)
        if block is None:
            p.error(f'unknown asset block {a.block}')
        look = looks.canonical({'block': block['id'], **block['look']})
    elif a.look_of:
        known = places.by_id(places.load_index(ROOT))
        if a.look_of not in known:
            p.error(f'unknown Geofabrik id {a.look_of}')
        look = looks.recommended(a.look_of, known)
    else:
        p.error('give --look-of or --block')
    print(build_spot(a.id, a.title, a.lat, a.lon, a.km, a.source, look, a.out, a.jobs,
                     tuple(a.landing) if a.landing else None))


if __name__ == '__main__':
    main()
