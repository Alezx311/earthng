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

and, apart from the roads, a guard rail with a triangle taller than 3 m ('spike': a vertex at the wrong
height, a railing running down into the ground; its height as the length column), and a guard rail or mesh fence standing on a carriageway ('barrier': its
footprint on the asphalt, in m2, as the length column): a rail drawn across the lane under a bridge
or at a junction mouth. Piers and abutments (fence_wall) are not barriers. On near tiles also:

  parapet  a deck's wall (fence_wall) standing inside a carriageway, on asphalt at its own height
           all round: a parapet across a slip road's mouth (m2)
  prop     a lamp, a mapped tree or other street furniture standing a metre or more inside a
           carriageway, within 1 m of its height (the class names it: 'lamp point' is OSM's)
  step     the road's own asphalt (of the highest and lowest drawn, the one nearer the road's
           pack height) jumping by more than JUMP within a metre and not coming back within
           RETURN m: a deck end above or below its approach, seen as a wall across the road (m)

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
BARRIERS = ('e2rf_clad_metal', 'e2rf_fence_mesh')
WALL = 'e2rf_fence_wall'   # a deck's parapet and edge face, piers, abutments
CELL = 10.           # m: barrier pixels are reported per cell of this size
SPIKE = 3.           # m: a rail or fence triangle taller than this has a vertex at the wrong height
LONGEST = 4.         # m: ... if it is no wider than this (a rail's step is 2 m; a building's wall is wider)


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


JUMP = .4           # m: the asphalt under a road's centre line rising or falling this much within a metre
RETURN = 40.         # m: ... and not back within this: a road passing under a deck jumps up and down again


def steps(points, rect, asphalt, lowest=None):
    """[(x, y, m)] where the drawn asphalt along one road's centre line jumps by more than JUMP in a metre
    and stays there: a deck end above or below its approach, a wall across the road. lowest: the
    lowest asphalt; of it and the highest, the one nearer the road's own height is the road's."""
    pts = np.asarray([p[:2] for p in points], dtype=float)
    along = np.r_[0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    if along[-1] < 2:
        return []
    s = np.arange(0, along[-1], 1.)
    x, y = np.interp(s, along, pts[:, 0]), np.interp(s, along, pts[:, 1])
    inside = (x >= rect[0] + 1) & (x < rect[2] - 1) & (y >= rect[1] + 1) & (y < rect[3] - 1)
    c = np.clip(((x - rect[0]) / PIXEL).astype(int), 0, asphalt.shape[1] - 1)
    r = np.clip(((y - rect[1]) / PIXEL).astype(int), 0, asphalt.shape[0] - 1)
    z = np.where(inside, asphalt[r, c], np.nan)
    if lowest is not None and np.asarray(points).shape[1] > 2:
        own = np.interp(s, along, np.asarray([p[2] for p in points], dtype=float))
        low = np.where(inside, lowest[r, c], np.nan)
        with np.errstate(invalid='ignore'):
            z = np.where(np.abs(low - own) < np.abs(z - own), low, z)
    out = []
    for k in np.flatnonzero(np.abs(np.diff(z)) > JUMP):
        d = z[k + 1] - z[k]
        ahead = z[k + 1:k + 1 + int(RETURN)]
        behind = z[max(0, k - int(RETURN)):k + 1]
        # back to the level it left within RETURN m on either side: something passing over
        if np.nanmin(np.abs(ahead - z[k])) < JUMP / 2 or np.nanmin(np.abs(behind - z[k + 1])) < JUMP / 2:
            continue
        out.append((float(x[k]), float(y[k]), float(abs(d))))
    return out


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


def barrier_pixels(asphalt, top, low):
    """Pixels where a barrier stands on the asphalt: its base is at (or sunk in) the carriageway and
    it rises over it. asphalt, top, low: the tile's rasters of the asphalt's top, the barrier's top
    and the barrier's lowest surface (NaN: none)."""
    with np.errstate(invalid='ignore'):
        return np.isfinite(asphalt) & np.isfinite(top) & (low <= asphalt + .25) & (top >= asphalt + .3) & (top <= asphalt + 3.)


def barrier_cells(pixels, rect):
    """[(x, y, m2)] per CELL-sized cell holding barrier pixels (a pixel is PIXEL m wide)."""
    rows, cols = np.nonzero(pixels)
    found = defaultdict(int)
    for r, c in zip(rows, cols):
        found[(int(c * PIXEL // CELL), int(r * PIXEL // CELL))] += 1
    return [(rect[0] + (cx + .5) * CELL, rect[1] + (cy + .5) * CELL, n * PIXEL * PIXEL) for (cx, cy), n in found.items()]


def spikes(text, limit=SPIKE):
    """[(x, y, spread m)] per CELL of a guard rail mesh (text: 'x y z' vertices, three to a triangle) whose triangles
    are taller than limit: a rail is .75 m high, so one that is not has a vertex at the
    wrong height (a ground sample off the loaded terrain read as 0), seen as a railing running down into the
    ground."""
    xyz = np.asarray(text.split(), dtype=float).reshape(-1, 3, 3)
    spread = xyz[:, :, 2].max(1) - xyz[:, :, 2].min(1)
    # a rail's triangle is a 2 m step of the beam: a warehouse's cladding (clad_metal too) is wider than that
    wide = np.maximum(np.ptp(xyz[:, :, 0], axis=1), np.ptp(xyz[:, :, 1], axis=1))
    spread = np.where(wide < LONGEST, spread, 0.)
    found = {}
    for (x, y, _), s in zip(xyz[spread > limit].mean(1), spread[spread > limit]):
        key = (int(x // CELL), int(y // CELL))
        found[key] = max(found.get(key, 0.), float(s))
    return [((cx + .5) * CELL, (cy + .5) * CELL, s) for (cx, cy), s in found.items()]


_open = {}


def _runtime(path, region, generator):
    key = (path, region, generator)
    if key not in _open:
        pack = rq.Pack(Path(path), region)
        lua, mods, build, data, slots = rq.lua_runtime(pack, generator)
        # the scene's walls too: a parapet standing on a carriageway
        _open[key] = (pack, lua, mods, build, data, slots, lua.table_from({m: True for m in rq.COVER | {WALL}}))
    return _open[key]


def props_on_road(text, asphalt, rect):
    """[(x, y, kind)] of street furniture ('x y z kind' lines) standing on a carriageway: the asphalt
    covers the pixel round it and its neighbours (a pole by the curb is not on the road) within 1 m of
    its foot (a lamp on the ground under a bridge is not on the deck)."""
    out, n = [], asphalt.shape[0]
    for line in (text or '').splitlines():
        x, y, z, kind = line.split(' ', 3)
        kind = kind.split(' ')[0] + ('' if ' ' not in kind else ' ' + kind.split(' ', 1)[1].split('_')[3])
        x, y, z = float(x), float(y), float(z)
        c, r = int((x - rect[0]) / PIXEL), int((y - rect[1]) / PIXEL)
        if 1 <= c < n - 1 and 1 <= r < n - 1:
            a = asphalt[r - 1:r + 2, c - 1:c + 2]
            if np.isfinite(a).all() and abs(asphalt[r, c] - z) < 1.:
                out.append((x, y, kind))
    return out


def audit_tile(job):
    """One tile: ({road id: [bad samples]}, {road id: samples}, {road id: (name, class, bridge)}, [(x, y, m2) of
    barriers on the asphalt], [(x, y, m) of rails and fences with a vertex at the wrong height], [(x, y, m2) of
    deck walls on the asphalt], [(x, y, kind) of street furniture on a carriageway])."""
    path, region, generator, far, i, j = job
    pack, lua, mods, build, data, slots, cover = _runtime(path, region, generator)
    size = pack.size
    rect = [i * size, j * size, (i + 1) * size, (j + 1) * size]
    res = build(mods['generator'], mods['cellformat'], data, slots, i, j, size, pack.cell,
                pack.region.get('seaLevel'), lua.table_from({'far': 1} if far else {}), cover, 1)
    bad, total, names = {}, defaultdict(int), {}
    if res is None:
        return bad, total, names, [], [], [], [], []
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
    barrier, low = top(BARRIERS), np.full(shape, np.nan)
    for m in BARRIERS:
        if mats.get(m):          # the lowest surface: the highest of the mirrored heights
            xyz = np.asarray(mats[m].split(), dtype=float).reshape(-1, 3)
            xyz[:, 2] *= -1
            low = np.fmax(low, rq.raster(' '.join(f'{v:.3f}' for v in xyz.ravel()), rect, shape))
    # far tiles draw buildings too, and a warehouse wall is clad_metal: rails and fences are judged on near tiles
    standing = barrier_cells(barrier_pixels(asphalt, barrier, -low), rect) if np.isfinite(barrier).any() and not far else []
    tall = spikes(mats['e2rf_clad_metal']) if mats.get('e2rf_clad_metal') else []         # not fences: a noise wall is 7 m
    walls = []
    if mats.get(WALL) and not far:
        wall = rq.raster(mats[WALL], rect, shape)
        xyz = np.asarray(mats[WALL].split(), dtype=float).reshape(-1, 3)
        xyz[:, 2] *= -1
        wall_low = -rq.raster(' '.join(f'{v:.3f}' for v in xyz.ravel()), rect, shape)
        # inside the carriageway only: a parapet stands its thickness inside the deck's edge pixel
        # (and its neighbours at the same height: a road under a deck's edge is not more of the deck)
        inner = np.isfinite(asphalt)
        mid = asphalt[1:-1, 1:-1]
        with np.errstate(invalid='ignore'):
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                inner[1:-1, 1:-1] &= np.abs(asphalt[1 + dr:asphalt.shape[0] - 1 + dr, 1 + dc:asphalt.shape[1] - 1 + dc] - mid) < .5
        inner[0, :] = inner[-1, :] = inner[:, 0] = inner[:, -1] = False
        walls = barrier_cells(barrier_pixels(np.where(inner, asphalt, np.nan), wall, wall_low), rect)
    props = [] if far else props_on_road(str(res.props or ''), asphalt, rect)
    skip = NOT_FAR if far else set()
    seen, jumps = set(), []
    lowest = np.full(shape, np.nan)
    for m in rq.CARRIAGEWAY:
        if mats.get(m):
            xyz = np.asarray(mats[m].split(), dtype=float).reshape(-1, 3)
            xyz[:, 2] *= -1
            lowest = np.fmax(lowest, rq.raster(' '.join(f'{v:.3f}' for v in xyz.ravel()), rect, shape))
    lowest = -lowest
    for rd in (pack.source(int(rect[0] // pack.cell), int(rect[1] // pack.cell)) or {}).get('roads', []):
        tags = rd.get('tags', {})
        if tags.get('highway') not in DRIVEN or tags.get('highway') in skip or rd['id'] in seen:
            continue
        if far and under_ground(tags):
            continue                  # a far tile draws no tunnel
        seen.add(rd['id'])
        found, checked = grade(rd['points'], tags, rect, asphalt, ground)
        if not far and not under_ground(tags):
            jumps.extend((x, y, m, rd['id']) for x, y, m in steps(rd['points'], rect, asphalt, lowest))
        total[rd['id']] += checked
        names[rd['id']] = (tags.get('name') or tags.get('ref') or '', tags.get('highway'), tags.get('bridge') or '')
        if found:
            bad[rd['id']] = found
    return bad, total, names, standing, tall, walls, props, jumps


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
    bad, total, names, standing, tall = defaultdict(list), defaultdict(int), {}, defaultdict(float), {}
    walls, props, jumps = defaultdict(float), {}, {}
    results = ProcessPoolExecutor(a.jobs).map(audit_tile, jobs, chunksize=4) if a.jobs > 1 else map(audit_tile, jobs)
    for k, (b, t, nm, st, sp, wl, pr, jp) in enumerate(results):
        for x, y, m, rid in jp:
            key = (round(x / CELL), round(y / CELL))
            if m > jumps.get(key, (0,))[0]:
                jumps[key] = (m, x, y, rid)
        for x, y, m2 in wl:
            walls[(round(x), round(y))] += m2
        for x, y, kind in pr:
            props[(round(x, 1), round(y, 1))] = kind
        for x, y, m2 in st:
            standing[(round(x), round(y))] += m2
        for x, y, s in sp:
            tall[(round(x), round(y))] = max(tall.get((round(x), round(y)), 0.), s)
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
    for (x, y), m2 in standing.items():
        lat, lon = pack.geo(x, y)
        rows.append({'kind': 'barrier', 'length_m': round(m2), 'name': '', 'class': 'rail/fence on asphalt', 'bridge': '',
                     'lat': round(lat, 5), 'lon': round(lon, 5), 'road': ''})
    for (x, y), s in tall.items():
        lat, lon = pack.geo(x, y)
        rows.append({'kind': 'spike', 'length_m': round(s), 'name': '', 'class': 'rail/fence vertex at the wrong height', 'bridge': '',
                     'lat': round(lat, 5), 'lon': round(lon, 5), 'road': ''})
    for (x, y), m2 in walls.items():
        lat, lon = pack.geo(x, y)
        rows.append({'kind': 'parapet', 'length_m': round(m2), 'name': '', 'class': 'deck wall on asphalt', 'bridge': '',
                     'lat': round(lat, 5), 'lon': round(lon, 5), 'road': ''})
    for (x, y), kind in props.items():
        lat, lon = pack.geo(x, y)
        rows.append({'kind': 'prop', 'length_m': 1, 'name': '', 'class': f'{kind} on the carriageway', 'bridge': '',
                     'lat': round(lat, 5), 'lon': round(lon, 5), 'road': ''})
    for m, x, y, rid in jumps.values():
        lat, lon = pack.geo(x, y)
        nm = names.get(rid, ('', '', ''))
        rows.append({'kind': 'step', 'length_m': round(m, 1), 'name': nm[0], 'class': nm[1], 'bridge': nm[2],
                     'lat': round(lat, 5), 'lon': round(lon, 5), 'road': rid})
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
          f"buried {count('buried')} ({100 * count('buried') / max(1, samples):.2f} %), {len(standing)} cells with a rail or fence on the road, "
          f"{len(tall)} cells with a rail or fence running into the ground, {len(walls)} cells with a deck wall on the road, "
          f"{len(props)} props on the carriageway, {len(jumps)} steps in the asphalt, {len(rows)} findings -> {a.out}")
    for r in rows[:15]:
        print(f"  {r['kind']:7s} {r['length_m']:5d} {'m2' if r['kind'] in ('barrier', 'parapet') else 'm '} {r['name'][:26]:26s} [{r['class']}{' bridge' if r['bridge'] else ''}]  "
              f"{r['lat']}, {r['lon']}  road {r['road']}")


if __name__ == '__main__':
    main()
