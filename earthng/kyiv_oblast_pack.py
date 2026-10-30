"""Prepare and build the Kyiv oblast + Kyiv test polygon from cached Ukraine tiles.

The boundary is OSM relation 71248, downloaded separately as Nominatim JSON.  The
country's already cut tiles are hard-linked into a subset; they remain immutable.
Run --prepare before --build.  Neither operation touches the game's mods folder.
"""
import argparse
import json
import os
from pathlib import Path
import time

import shapely
from shapely.geometry import Polygon, box, shape

import build_country
import country_fetch
import fast_sources
import looks
import osm_select
import places

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'data/osm_tiles/ukraine-user'
SUBSET = ROOT / 'data/osm_tiles/kyiv-oblast-polygon'
WORK = ROOT / 'out/world'
OUT = ROOT / 'out/kyiv-oblast-polygon'


def outline(path):
    entry = json.loads(path.read_text(encoding='utf-8'))[0]
    if entry['osm_type'] != 'relation' or entry['osm_id'] != 71248:
        raise ValueError('expected OSM relation 71248 for Kyiv oblast')
    geo = shape(entry['geojson'])
    # The separate city of Kyiv is a hole in the oblast; fill it so it is drivable.
    parts = list(geo.geoms) if geo.geom_type == 'MultiPolygon' else [geo]
    return shapely.union_all([Polygon(part.exterior) for part in parts]).simplify(0.0005, preserve_topology=True).buffer(0.02)


def prepare(boundary):
    index = json.loads((SOURCE / 'index.json').read_text(encoding='utf-8'))
    if index.get('select') != osm_select.VERSION:
        raise ValueError('Ukraine tile cache uses obsolete selection rules; recut it first')
    area = outline(boundary)
    # Additional tile coverage supports a full cell at the polygon edge and region halo.
    selection = area.buffer(0.08)
    chosen = {k: v for k, v in index['tiles'].items() if selection.intersects(box(*v['cell']))}
    if not chosen:
        raise ValueError('no source tiles intersect the polygon')
    SUBSET.mkdir(parents=True, exist_ok=True)
    for entry in chosen.values():
        src, dst = SOURCE / entry['file'], SUBSET / entry['file']
        if dst.exists():
            if not os.path.samefile(src, dst):
                raise ValueError(f'stale subset tile: {dst}')
            continue
        os.link(src, dst)
    index['tiles'] = chosen
    index['package_box'] = list(selection.bounds)
    (SUBSET / 'index.json').write_text(json.dumps(index), encoding='utf-8')
    print(f"{len(chosen)} cached tiles, {sum(v['bytes'] for v in chosen.values()) / 1e6:.1f} MB", flush=True)
    dem = WORK / 'cache'
    country_fetch.fetch_dem(index, dem)
    regions = [r for r in build_country.grid_regions(SUBSET, dem, WORK)
               if area.intersects(box(*r['core']))]
    OUT.mkdir(parents=True, exist_ok=True)
    for region in regions:
        region['shape'] = area
    (OUT / 'regions.json').write_text(json.dumps([build_country._region_record(r) for r in regions]), encoding='utf-8')
    print(f'{len(regions)} indexed regions', flush=True)


def build(jobs):
    regions = [build_country._revive_region(r) for r in json.loads((OUT / 'regions.json').read_text(encoding='utf-8'))]
    known = places.by_id(places.load_index(ROOT))
    look = looks.recommended('ukraine', known)
    map_data = SOURCE / 'map'
    archive = build_country.build_country('kyiv-oblast', 'Київська область і Київ', '0.4.0', regions, OUT,
                                          jobs=jobs, landing=(50.4501, 30.5234), look=look,
                                          map_data=map_data if (map_data / 'index.json').is_file() else None)
    print(f'{archive}: {archive.stat().st_size / 1e6:.1f} MB', flush=True)


def control(jobs, lat=50.4619, lon=30.3500, name='bilychi'):
    # By default Bilychi: Velmart, Fora, Novus, McDonald's and Nova Poshta near Akademmistechko.
    # The whole-country index is reusable even while the polygon's indexes are still building.
    core = [30., 50., 31.5, 51.]
    pad = build_country.PAD
    window = [core[0]-pad[0], core[1]-pad[1], core[2]+pad[0], core[3]+pad[1]]
    identity, _ = fast_sources.source_identity(SOURCE, WORK / 'cache', box=window)
    directory = WORK / 'fast-index' / identity
    if not (directory / 'sources.sqlite').is_file():
        raise ValueError('central Ukraine index is not ready; finish polygon prepare first')
    meta = json.loads((directory / 'region.json').read_text(encoding='utf-8'))
    # The content-keyed index may have been built from a now-removed cache directory.
    # Keep its original metadata intact and bind this copy to the matching current tiles.
    if not (Path(meta['source']) / 'index.json').is_file():
        fixed = OUT / 'control-index'
        fixed.mkdir(parents=True, exist_ok=True)
        db = fixed / 'sources.sqlite'
        if not db.exists():
            os.link(directory / 'sources.sqlite', db)
        meta['source'] = str(SOURCE.resolve())
        (fixed / 'region.json').write_text(json.dumps(meta), encoding='utf-8')
        directory = fixed
    region = {'dir': directory, 'core': core, 'id': 'e0300-n500'}
    x, y = fast_sources.Frame.of(meta).local(lon, lat)
    bbox = [float(x)-1000, float(y)-1000, float(x)+1000, float(y)+1000]
    known = places.by_id(places.load_index(ROOT))
    look = looks.recommended('ukraine', known)
    archive = build_country.build_country(f'{name}-retail-check', f'{name}: тест закладів', '0.4.0',
                                          [region], OUT / f'{name}-control', bbox=bbox, jobs=jobs,
                                          landing=(lat, lon), look=look)
    print(f'{archive}: {archive.stat().st_size / 1e6:.1f} MB', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=('prepare', 'build', 'control'))
    p.add_argument('--boundary', type=Path, default=OUT / 'boundary.json')
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--at', nargs=3, metavar=('LAT', 'LON', 'NAME'), help='control: 2 km round this point')
    args = p.parse_args()
    started = time.monotonic()
    if args.phase == 'prepare':
        prepare(args.boundary)
    elif args.phase == 'build':
        build(args.jobs)
    else:
        control(args.jobs, *([float(args.at[0]), float(args.at[1]), args.at[2]] if args.at else []))
    print(f'{args.phase}: {time.monotonic() - started:.1f} s', flush=True)


if __name__ == '__main__':
    main()
