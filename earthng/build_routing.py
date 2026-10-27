"""Routing graphs (routing_format) for the regions of a built country pack.

    .venv/Scripts/python.exe earthng/build_routing.py PACK.zip --out out/routing/ukraine [--region e0300-n500]

The graph comes from the pack's own road features, so a pack already published gets routing
without a rebuild: the result is `routing/<region>.bin` under the pack's country folder, written
loose and as a companion ZIP (`<pack>_routing.zip`) that the game mounts beside the pack.
Restrictions and motorway exits are not in the cells; build_country fills them from the raw cut.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import re
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import country_format  # noqa: E402
import routing_format  # noqa: E402

BLOCK_NAME = re.compile(r'(-?\d+)_(-?\d+)\.bin\Z')


def region_roads(archive, prefix, cell_size, block=country_format.BLOCK):
    """Every road feature of a region's blocks with region-local coordinates."""
    for name in archive.namelist():
        if not name.startswith(prefix + 'blocks/'):
            continue
        hit = BLOCK_NAME.search(name)
        if not hit:
            continue
        bi, bj = int(hit.group(1)), int(hit.group(2))
        data = archive.read(name)
        for slot, (start, end) in country_format.decode_block(data).items():
            i, j = bi * block + slot % block, bj * block + slot // block
            origin = (i * cell_size, j * cell_size)
            rect = (origin[0], origin[1], origin[0] + cell_size, origin[1] + cell_size)
            yield from country_format.decode_cell(data, origin, rect, start, end)['roads']


def regions_of(archive):
    """{region id: manifest prefix} of a pack ZIP."""
    out = {}
    for name in archive.namelist():
        hit = re.match(r'(earthng/countries/[^/]+/regions/([^/]+)/)manifest\.json\Z', name)
        if hit:
            out[hit.group(2)] = hit.group(1)
    return out


def build_region(task):
    pack, region, prefix = task
    started = time.perf_counter()
    with zipfile.ZipFile(pack) as archive:
        manifest = json.loads(archive.read(prefix + 'manifest.json'))
        g = routing_format.graph(region_roads(archive, prefix, manifest.get('cellSize', 1000),
                                              manifest.get('blockCells', country_format.BLOCK)))
    data = routing_format.encode(g)
    return region, data, {'nodes': len(g['nodes']), 'edges': len(g['edges']), 'bytes': len(data),
                          'seconds': round(time.perf_counter() - started, 1)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('pack')
    parser.add_argument('--out', required=True)
    parser.add_argument('--region', action='append', help='only these region ids')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args(argv)
    pack, out = Path(args.pack).resolve(), Path(args.out)
    with zipfile.ZipFile(pack) as archive:
        regions = regions_of(archive)
    if args.region:
        missing = set(args.region) - set(regions)
        if missing:
            parser.error(f'no such region: {", ".join(sorted(missing))}')
        regions = {k: regions[k] for k in args.region}
    country = next(iter(regions.values())).split('/')[2]
    folder = out / 'earthng' / 'countries' / country / 'routing'
    folder.mkdir(parents=True, exist_ok=True)
    stats = {}
    tasks = [(str(pack), region, prefix) for region, prefix in sorted(regions.items())]
    with ProcessPoolExecutor(max(1, min(args.workers, len(tasks)))) as pool:
        for region, data, info in pool.map(build_region, tasks):
            (folder / f'{region}.bin').write_bytes(data)
            stats[region] = info
            print(region, info, flush=True)
    (out / 'routing.json').write_text(json.dumps({'version': routing_format.VERSION, 'country': country,
                                                  'regions': stats}, indent=1))
    companion = out / f'{pack.stem}_routing.zip'
    with zipfile.ZipFile(companion, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(folder.glob('*.bin')):
            archive.write(path, path.relative_to(out).as_posix())
    print('companion', companion, companion.stat().st_size, 'bytes')


if __name__ == '__main__':
    main()
