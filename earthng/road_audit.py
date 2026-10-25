"""Road audit: every road of a pack against what generator.lua draws, for a whole area at once.

  python earthng/road_audit.py --pack out/country/earthng_estonia.zip --region e0240-n590 \\
      --box 59.30 24.55 59.52 25.00 --jobs 6 --out out/polygon/runs/audit.csv [--far] [--stride 2]

Looking at roads and junctions one by one does not scale. Each tile of the area is built by
generator.lua (road_quality's LuaJIT runtime), its asphalt and its ground and cover are rastered
at 1 m, and the centre line of every road is walked every 6 m. A sample is

  missing  no asphalt within a metre of it: the road is not drawn there (a hole in a deck, a
           road no tile draws, a far tile without roads), or
  buried   ground or cover higher than the asphalt there: drawn, but hidden. A road in a tunnel
           (tunnel=*, layer -1) runs under the ground by design and is not checked for this.

--far builds the far tiles (the ring past the near radius, where the car's surroundings are
decoration): there only the roads a far tile draws (generator.lua ROADS.far: no service streets,
no tunnels) count. One CSV row
per bad stretch, longest first, with lat/lon to jump to it, and a summary line.
"""
import argparse
import csv
import math
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import road_quality as rq  # noqa: E402

DRIVEN = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential', 'service',
          'living_street', 'motorway_link', 'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link', 'road'}
NOT_FAR = {'service', 'living_street', 'road'}      # generator.lua ROADS.far.minRank
STEP = 6.            # m between the samples of a road
PIXEL = 1.           # m per raster pixel
ABOVE = .03          # m: ground this much over the asphalt hides it


def under_ground(tags):
    """A tunnel lies under the ground: ground over its asphalt is right."""
    return tags.get('tunnel') not in (None, 'no', 'building_passage') or str(tags.get('layer')) == '-1'


def grade(points, tags, rect, asphalt, ground):
    """The samples of one road in one tile: ([('missing' | 'buried', x, y, s)], how many were checked).
    points: the road's {x, y, z}; asphalt, ground: the tile's top-surface rasters (NaN: none)."""
    pts = np.asarray([p[:2] for p in points], dtype=float)
    along = np.r_[0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    n = asphalt.shape[0]
    bad, checked = [], 0
    for s in np.arange(0, along[-1] + 1e-6, STEP):
        x, y = np.interp(s, along, pts[:, 0]), np.interp(s, along, pts[:, 1])
        if not (rect[0] + 1 <= x < rect[2] - 1 and rect[1] + 1 <= y < rect[3] - 1):
            continue
        checked += 1
        c, r = int((x - rect[0]) / PIXEL), int((y - rect[1]) / PIXEL)
        window = (slice(max(0, r - 1), min(n, r + 2)), slice(max(0, c - 1), min(n, c + 2)))
        a, g = asphalt[window], ground[window]
        if not np.isfinite(a).any():
            bad.append(('missing', float(x), float(y), float(s)))
        elif np.isfinite(g).any() and np.nanmax(g) > np.nanmax(a) + ABOVE and not under_ground(tags):
            bad.append(('buried', float(x), float(y), float(s)))
    return bad, checked


def stretches(bad):
    """Runs of consecutive bad samples of one kind: [(kind, length m, mean x, mean y)]."""
    bad = sorted(bad, key=lambda b: b[3])
    runs, run = [], []
    for b in bad:
        if run and (b[0] != run[-1][0] or b[3] - run[-1][3] > STEP * 1.5):
            runs.append(run)
            run = []
        run.append(b)
    if run:
        runs.append(run)
    return [(r[0][0], len(r) * STEP, float(np.mean([b[1] for b in r])), float(np.mean([b[2] for b in r]))) for r in runs]


_open = {}


def _runtime(path, region, generator):
    key = (path, region, generator)
    if key not in _open:
        pack = rq.Pack(Path(path), region)
        lua, mods, build, data, slots = rq.lua_runtime(pack, generator)
        _open[key] = (pack, lua, mods, build, data, slots, lua.table_from({m: True for m in rq.COVER}))
    return _open[key]


def audit_tile(job):
    """One tile: ({road id: [bad samples]}, {road id: samples}, {road id: (name, class, bridge)})."""
    path, region, generator, far, i, j = job
    pack, lua, mods, build, data, slots, cover = _runtime(path, region, generator)
    size = pack.size
    rect = [i * size, j * size, (i + 1) * size, (j + 1) * size]
    res = build(mods['generator'], mods['cellformat'], data, slots, i, j, size, pack.cell,
                pack.region.get('seaLevel'), lua.table_from({'far': 1} if far else {}), cover, 1)
    bad, total, names = {}, defaultdict(int), {}
    if res is None:
        return bad, total, names
    rq.RES = PIXEL
    shape = (int(size / PIXEL),) * 2
    mats = dict(res.mats.items())

    def top(materials):
        out = np.full(shape, np.nan)
        for m in materials:
            if mats.get(m):
                out = np.fmax(out, rq.raster(mats[m], rect, shape))
        return out
    asphalt, ground = top(rq.CARRIAGEWAY), top(rq.GROUND | rq.COVER)
    skip = NOT_FAR if far else set()
    seen = set()
    for rd in (pack.source(int(rect[0] // pack.cell), int(rect[1] // pack.cell)) or {}).get('roads', []):
        tags = rd.get('tags', {})
        if tags.get('highway') not in DRIVEN or tags.get('highway') in skip or rd['id'] in seen:
            continue
        if far and under_ground(tags):
            continue                  # a far tile draws no tunnel
        seen.add(rd['id'])
        found, checked = grade(rd['points'], tags, rect, asphalt, ground)
        total[rd['id']] += checked
        names[rd['id']] = (tags.get('name') or tags.get('ref') or '', tags.get('highway'), tags.get('bridge') or '')
        if found:
            bad[rd['id']] = found
    return bad, total, names


def local(pack, lat, lon):
    """Pack metres of a lat/lon (the pack's geo() is affine)."""
    g0 = np.array(pack.geo(0, 0))
    m = np.array([np.array(pack.geo(1, 0)) - g0, np.array(pack.geo(0, 1)) - g0]).T
    return tuple(float(v) for v in np.linalg.solve(m, np.array([lat, lon]) - g0))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--region', help='region id of a country of several (default: the first)')
    p.add_argument('--generator', type=Path, help='another generator.lua (an A/B)')
    p.add_argument('--box', nargs=4, type=float, metavar=('S', 'W', 'N', 'E'), help='lat/lon box to audit')
    p.add_argument('--all', action='store_true', help='every tile of the region')
    p.add_argument('--stride', type=int, default=1, help='every n-th tile in x and y')
    p.add_argument('--far', action='store_true', help='far tiles (roads from ROADS.far only)')
    p.add_argument('--jobs', type=int, default=1)
    p.add_argument('--out', type=Path, default=Path('out/polygon/runs/road_audit.csv'))
    a = p.parse_args()
    if not (a.box or a.all):
        p.error('give --box or --all')
    pack = rq.Pack(a.pack, a.region)
    size = pack.size
    per = int(pack.cell // size)
    tiles = sorted({(ci * per + di, cj * per + dj) for ci, cj in pack.cells() for di in range(per) for dj in range(per)})
    if a.box:
        s, w, n, e = a.box
        corners = [local(pack, la, lo) for la in (s, n) for lo in (w, e)]
        x0, x1 = min(c[0] for c in corners), max(c[0] for c in corners)
        y0, y1 = min(c[1] for c in corners), max(c[1] for c in corners)
        tiles = [t for t in tiles if t[0] * size < x1 and (t[0] + 1) * size > x0 and t[1] * size < y1 and (t[1] + 1) * size > y0]
    tiles = [t for t in tiles if t[0] % a.stride == 0 and t[1] % a.stride == 0]
    jobs = [(str(a.pack), a.region, str(a.generator) if a.generator else None, a.far, i, j) for i, j in tiles]
    bad, total, names = defaultdict(list), defaultdict(int), {}
    results = ProcessPoolExecutor(a.jobs).map(audit_tile, jobs, chunksize=4) if a.jobs > 1 else map(audit_tile, jobs)
    for k, (b, t, nm) in enumerate(results):
        for rid, found in b.items():
            bad[rid].extend(found)
        for rid, c in t.items():
            total[rid] += c
        names.update(nm)
        if (k + 1) % 200 == 0 or k + 1 == len(tiles):
            print(f'{k + 1}/{len(tiles)} tiles, {sum(len(v) for v in bad.values())} bad samples', flush=True)
    rows = []
    for rid, found in bad.items():
        for kind, length, x, y in stretches(found):
            lat, lon = pack.geo(x, y)
            rows.append({'kind': kind, 'length_m': round(length), 'name': names[rid][0], 'class': names[rid][1],
                         'bridge': names[rid][2], 'lat': round(lat, 5), 'lon': round(lon, 5), 'road': rid})
    rows.sort(key=lambda r: -r['length_m'])
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['kind', 'length_m', 'name', 'class', 'bridge', 'lat', 'lon', 'road'])
        writer.writeheader()
        writer.writerows(rows)
    samples = sum(total.values())
    count = lambda kind: sum(1 for v in bad.values() for b in v if b[0] == kind)
    print(f"{len(tiles)} tiles{' (far)' if a.far else ''}, {len(total)} roads, {samples} samples: "
          f"missing {count('missing')} ({100 * count('missing') / max(1, samples):.2f} %), "
          f"buried {count('buried')} ({100 * count('buried') / max(1, samples):.2f} %), {len(rows)} bad stretches -> {a.out}")
    for r in rows[:15]:
        print(f"  {r['kind']:7s} {r['length_m']:5d} m  {r['name'][:26]:26s} [{r['class']}{' bridge' if r['bridge'] else ''}]  "
              f"{r['lat']}, {r['lon']}  road {r['road']}")


if __name__ == '__main__':
    main()
