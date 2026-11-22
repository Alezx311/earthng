"""Span census: every bridge and tunnel of a pack by the shape of its profile, outside the game.

  python earthng/span_census.py --pack <mods>/earthng_kyiv-oblast.zip --region e0300-n500 \\
      --box 50.38 30.40 50.52 30.66 --label kyiv
  python earthng/span_census.py --pack out/polygon/earthng_polygon.zip --label polygon --sheet 40

A bridge is looked at one at a time in the game, and a bad one has to be found first. Here the
roads of an area are read from the pack, the bridges and tunnels mapped in pieces are joined
into spans, and each span's line of heights is measured twice: as the pack stores it (`pack`)
and as generator.lua draws it (`drawn`: after ROADS.liftDecks, which a tile runs on the roads of
its cells). A span is

  sag     a bridge whose deck dips between two higher parts of itself, the letter M from the
          side: metres under the lower of the two parts it dips between
  hump    a tunnel that climbs inside the hill it passes under: metres over the straight line
          between its mouths
  kink    the sharpest change of grade within 25 m of where the span meets the road it
          carries on as, read every 5 m, in per cent: a break of the road at the abutment or
          the mouth
  buried  a bridge's deck under the ground, metres (the pack's terrain under its centre line)
  bare    a tunnel's roof (ROADS.portal.head over its floor) out over the ground, metres: a box
          standing on the land instead of a hole in it
  steep   the steepest grade inside the span, per cent

--sheet N draws the N worst spans from the side, the pack's line dashed and the drawn one
solid over the ground under them. Runs go to out/spans/<label>: report.json, spans.csv,
sheet.png.
"""
import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

HEAD = 5.2            # generator.lua ROADS.portal.head: a tunnel's roof over its floor
DRIVEN = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential', 'service',
          'living_street', 'motorway_link', 'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link', 'road',
          'raceway', 'track'}
# what counts as a defect in the summary
LIMIT = {'sag': .5, 'hump': 1., 'kink': 4., 'buried': .3, 'bare': .5, 'steep': 10.}

LIFT = '''
local generator, roads = ...
generator.liftDecks(roads, function() end, true)
return roads
'''


def kind(tags):
    """'bridge', 'tunnel' or None, as the pack's height solve and the generator read the tags."""
    if tags.get('bridge') not in (None, 'no'):
        return 'bridge'
    if tags.get('tunnel') not in (None, 'no', 'building_passage'):
        return 'tunnel'
    return None


def along(points):
    p = np.asarray(points, dtype=float)
    return np.r_[0., np.cumsum(np.hypot(*np.diff(p[:, :2], axis=0).T))]


def brim(z):
    """The profile with its hollows filled to their brims: at each point the lower of the highest
    point before it and the highest after it (fast_profile.brim)."""
    z = np.asarray(z, dtype=float)
    return np.minimum(np.maximum.accumulate(z), np.maximum.accumulate(z[::-1])[::-1])


def chains(roads):
    """Spans mapped in pieces, joined: [(kind, [road, ...] in order, [reversed?, ...])]. Pieces
    join at a node where exactly two of one kind and one class of road meet."""
    spans = {r['id']: r for r in roads if kind(r['tags']) and r['tags'].get('highway') in DRIVEN and len(r['points']) >= 2}
    at = defaultdict(list)
    for r in spans.values():
        for e in (0, 1):
            at[(r['nodes'][e], kind(r['tags']))].append((r['id'], e))
    def other(rid, end):
        r = spans[rid]
        here = at[(r['nodes'][end], kind(r['tags']))]
        if len(here) != 2:
            return None
        nid, nend = here[0] if here[1] == (rid, end) else here[1]
        return None if nid == rid else (nid, nend)
    seen, out = set(), []
    for rid in sorted(spans):
        if rid in seen:
            continue
        # walk back to the chain's first piece, then forward
        cur, end, guard = rid, 0, 0
        while other(cur, end) and guard < 500:
            nid, nend = other(cur, end)
            if nid == rid:
                break                                   # a ring of bridges
            cur, end, guard = nid, 1 - nend, guard + 1
        chain, flips = [], []
        while cur not in seen:
            seen.add(cur)
            chain.append(spans[cur]); flips.append(end == 1)
            nxt = other(cur, 1 - end)
            if not nxt:
                break
            cur, end = nxt[0], nxt[1]
        if chain:
            out.append((kind(chain[0]['tags']), chain, flips))
    return out


def line_of(chain, flips, heights=None):
    """The chain's points in order: (xy [n, 2], z [n]); heights: {road id: [[x, y, z]]} as drawn."""
    xy, z = [], []
    for r, flip in zip(chain, flips):
        pts = np.asarray(r['points'], dtype=float)
        zs = pts[:, 2]
        if heights and r['id'] in heights:
            # liftDecks drops a point repeated in place and pulls a spike of the plan in: its own
            # points, read back at the pack's by arc length
            own = np.asarray(heights[r['id']], dtype=float)
            zs = np.interp(along(pts) / max(along(pts)[-1], 1e-6), along(own) / max(along(own)[-1], 1e-6), own[:, 2])
        if flip:
            pts, zs = pts[::-1], zs[::-1]
        first = 1 if xy else 0
        xy += pts[first:, :2].tolist(); z += zs[first:].tolist()
    return np.asarray(xy), np.asarray(z)


def break_at(s, z, end, rs, rz, e, reach=25., step=5.):
    """The sharpest change of grade within `reach` m of a joint, as a fraction: the span's line
    (s, z) from its end `end` (0 first, 1 last) and the road's (rs, rz) from its end e, read
    every `step` m through the joint."""
    def out(ss, zz, at, d):
        return float(np.interp(d if at == 0 else ss[-1] - d, ss, zz))
    a = min(reach, s[-1] / 2, rs[-1] / 2)
    n = int(a / step)
    if n < 1:
        return 0.
    line = [out(rs, rz, e, k * step) for k in range(n, 0, -1)] + [out(s, z, end, k * step) for k in range(0, n + 1)]
    grades = np.diff(line) / step
    return float(np.abs(np.diff(grades)).max()) if len(grades) > 1 else 0.


def measure(kind_, s, z, ground):
    """A span's line against itself and the ground under it: the defect columns, metres and %."""
    out = {'length': float(s[-1])}
    grades = np.abs(np.diff(z)) / np.maximum(np.diff(s), .5)
    out['steep'] = float(grades.max() * 100) if len(grades) else 0.
    if kind_ == 'bridge':
        dip = brim(z) - z
        k = int(np.argmax(dip))
        out['sag'], out['sag_at'] = float(dip[k]), float(s[k])
        if ground is not None and len(s) > 2:
            # the ends stand on the ground: the deck is judged a deck's depth in from them
            inner = (s > 3) & (s < s[-1] - 3)
            out['buried'] = float(max(0., (ground - z)[inner].max())) if inner.any() else 0.
            out['height'] = float((z - ground).max())
    else:
        chord = z[0] + (z[-1] - z[0]) * s / max(s[-1], 1e-6)
        rise = z - chord
        k = int(np.argmax(rise))
        out['hump'], out['hump_at'] = float(max(0., rise[k])), float(s[k])
        if ground is not None and len(s) > 2:
            inner = (s > 8) & (s < s[-1] - 8)
            out['bare'] = float(max(0., (z + HEAD - ground)[inner].max())) if inner.any() else 0.
            out['cover'] = float((ground - z - HEAD).max())
    return out


class Ground:
    """The pack's terrain under a point: the lattice of the cell it lies in (bilinear)."""

    def __init__(self, pack):
        self.pack, self.cells = pack, {}

    def cell(self, ci, cj):
        key = (ci, cj)
        if key not in self.cells:
            src = self.pack.source(ci, cj)
            t = src and src['terrain']
            self.cells[key] = t and t['nx'] > 1 and (t['rect'], np.asarray(t['heights'], dtype=float).reshape(t['ny'], t['nx'])) or None
        return self.cells[key]

    def at(self, xy):
        out = np.full(len(xy), np.nan)
        size = self.pack.cell
        for k, (x, y) in enumerate(xy):
            hit = self.cell(math.floor(x / size), math.floor(y / size))
            if not hit:
                continue
            rect, h = hit
            ny, nx = h.shape
            u = min(max((x - rect[0]) / (rect[2] - rect[0]) * (nx - 1), 0), nx - 1 - 1e-9)
            v = min(max((y - rect[1]) / (rect[3] - rect[1]) * (ny - 1), 0), ny - 1 - 1e-9)
            i, j = int(u), int(v)
            fu, fv = u - i, v - j
            out[k] = (h[j, i] * (1 - fu) + h[j, i + 1] * fu) * (1 - fv) + (h[j + 1, i] * (1 - fu) + h[j + 1, i + 1] * fu) * fv
        return out


def lua_lift(generator=None):
    """f(roads) -> {road id: [[x, y, z]]}: the roads as generator.lua draws them (ROADS.liftDecks)."""
    from lupa.luajit21 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    source = Path(generator or ROOT / 'mod/lua/ge/extensions/e2r/generator.lua')
    gen = lua.eval('function(source, name) return assert(load(source, "@" .. name))() end')(source.read_text(encoding='utf8'), 'generator.lua')
    run = lua.eval('function(src) return assert(load(src, "@span_census")) end')(LIFT)

    def table(value):
        if isinstance(value, dict):
            return lua.table_from({k: table(v) for k, v in value.items()})
        if isinstance(value, (list, tuple)):
            return lua.table_from([table(v) for v in value])
        return value

    def lift(roads):
        if not hasattr(gen, 'liftDecks') or gen.liftDecks is None:
            return {}
        done = run(gen, table([{'id': r['id'], 'width': r['width'], 'tags': r['tags'], 'nodes': r['nodes'],
                                'points': r['points']} for r in roads]))
        return {done[k].id: [[p[1], p[2], p[3]] for p in done[k].points.values()] for k in range(1, len(roads) + 1)}
    return lift


def census(pack, box=None, generator=None, emit=print):
    """The spans of a pack's region (inside box: lat0, lon0, lat1, lon1) with their columns."""
    import road_quality as rq
    size = pack.cell
    cells = []
    for ci, cj in pack.cells():
        if box:
            lat, lon = pack.geo((ci + .5) * size, (cj + .5) * size)
            if not (box[0] <= lat <= box[2] and box[1] <= lon <= box[3]):
                continue
        cells.append((ci, cj))
    by_cell, roads = {}, {}
    for ci, cj in cells:
        src = pack.source(ci, cj)
        by_cell[(ci, cj)] = [r['id'] for r in (src or {}).get('roads', [])]
        for r in (src or {}).get('roads', []):
            roads.setdefault(r['id'], r)
    spans = chains(roads.values())
    emit(f'{len(cells)} cells, {len(roads)} roads, {len(spans)} spans '
         f"({sum(1 for k, *_ in spans if k == 'bridge')} bridges, {sum(1 for k, *_ in spans if k == 'tunnel')} tunnels)")
    ground = Ground(pack)
    lift = lua_lift(generator)
    ends = defaultdict(list)                # node -> [(road, end)] of the roads that are no span
    for r in roads.values():
        if not kind(r['tags']) and r['tags'].get('highway') in DRIVEN:
            for e in (0, 1):
                ends[r['nodes'][e]].append((r, e))
    lifted = {}

    def drawn(cell):
        """The heights of a cell's roads as a tile over it draws them: liftDecks sees the roads
        of the tile's cells, and a cell stands in for them here."""
        if cell not in lifted:
            ids = by_cell.get(cell, [])
            lifted[cell] = lift([roads[i] for i in ids]) if any(kind(roads[i]['tags']) for i in ids) else {}
        return lifted[cell]

    rows = []
    for n, (kind_, chain, flips) in enumerate(spans):
        xy, z = line_of(chain, flips)
        mid = xy[len(xy) // 2]
        cell = (math.floor(mid[0] / size), math.floor(mid[1] / size))
        heights = drawn(cell)
        _, zd = line_of(chain, flips, heights)
        s = np.r_[0., np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
        if s[-1] < 2:
            continue
        g = ground.at(xy)
        g = g if np.isfinite(g).all() else None
        tags = chain[0]['tags']
        lat, lon = pack.geo(float(mid[0]), float(mid[1]))
        row = {'kind': kind_, 'highway': tags.get('highway'), 'name': tags.get('bridge:name') or tags.get('tunnel:name') or tags.get('name') or '',
               'structure': tags.get('bridge:structure') or tags.get('bridge') or tags.get('tunnel'), 'pieces': len(chain),
               'lat': round(lat, 6), 'lon': round(lon, 6), 'id': chain[0]['id'], 'width': chain[0]['width']}
        for label, line in (('pack', z), ('drawn', zd)):
            for key, value in measure(kind_, s, line, g).items():
                row[f'{label}_{key}'] = value
        # the road the span carries on as, at each end: one driven road and nothing else there
        kinks = {'pack': 0., 'drawn': 0.}
        first, last = chain[0], chain[-1]
        for end, (r, flip) in ((0, (first, flips[0])), (1, (last, flips[-1]))):
            node = r['nodes'][(1 - end) if flip else end] if end == 0 else r['nodes'][0 if flip else 1]
            near = ends.get(node, [])
            if len(near) != 1:
                continue
            road, e = near[0]
            for label, hs, line in (('pack', None, z), ('drawn', heights, zd)):
                pts = np.asarray(road['points'], dtype=float)
                rs = along(pts)
                rz = pts[:, 2]
                if hs and road['id'] in hs:
                    own = np.asarray(hs[road['id']], dtype=float)
                    rz = np.interp(rs / max(rs[-1], 1e-6), along(own) / max(along(own)[-1], 1e-6), own[:, 2])
                kinks[label] = max(kinks[label], break_at(s, line, end, rs, rz, e) * 100)
        row['pack_kink'], row['drawn_kink'] = kinks['pack'], kinks['drawn']
        row['_line'] = (s, z, zd, g)
        rows.append(row)
        if n % 200 == 199:
            emit(f'  {n + 1} / {len(spans)}')
    return rows


def summary(rows):
    out = {}
    for kind_ in ('bridge', 'tunnel'):
        part = [r for r in rows if r['kind'] == kind_]
        entry = {'count': len(part), 'km': round(sum(r['pack_length'] for r in part) / 1000, 2)}
        for label in ('pack', 'drawn'):
            for key, limit in LIMIT.items():
                vals = [r.get(f'{label}_{key}') for r in part]
                vals = [v for v in vals if v is not None]
                if vals:
                    entry[f'{label}_{key}'] = {'over': sum(1 for v in vals if v > limit), 'limit': limit,
                                               'max': round(max(vals), 2), 'p90': round(float(np.percentile(vals, 90)), 2)}
        out[kind_] = entry
    return out


def worst(rows, label='drawn'):
    """The rows by how bad the worst of their columns is, each against its limit."""
    def score(r):
        return max((r.get(f'{label}_{key}') or 0.) / limit for key, limit in LIMIT.items())
    return sorted(rows, key=score, reverse=True)


def sheet(rows, path, count=40):
    """The worst spans from the side: ground, the pack's line (dashed), the drawn line."""
    from PIL import Image, ImageDraw
    rows = worst(rows)[:count]
    cols = 2
    w, h, pad = 900, 230, 34
    image = Image.new('RGB', (cols * w, max(1, math.ceil(len(rows) / cols)) * h), (250, 250, 247))
    pen = ImageDraw.Draw(image)
    for n, r in enumerate(rows):
        s, z, zd, g = r['_line']
        ox, oy = (n % cols) * w, (n // cols) * h
        lines = [z, zd] + ([g] if g is not None else [])
        lo, hi = min(float(a.min()) for a in lines) - 2, max(float(a.max()) for a in lines) + 3
        if r['kind'] == 'tunnel':
            hi = max(hi, float(zd.max()) + HEAD + 1)
        sx = (w - 2 * pad) / max(s[-1], 1.)
        sy = (h - 2 * pad) / max(hi - lo, 1.)

        def px(a, b):
            return ox + pad + a * sx, oy + h - pad - (b - lo) * sy
        if g is not None:
            pen.polygon([px(s[0], lo)] + [px(a, b) for a, b in zip(s, g)] + [px(s[-1], lo)], fill=(196, 208, 170))
        if r['kind'] == 'tunnel':
            pen.line([px(a, b + HEAD) for a, b in zip(s, zd)], fill=(120, 120, 120), width=1)
        dash = [px(a, b) for a, b in zip(s, z)]
        for a, b in zip(dash[::2], dash[1::2]):
            pen.line([a, b], fill=(200, 80, 60), width=2)
        pen.line([px(a, b) for a, b in zip(s, zd)], fill=(30, 30, 30), width=3)
        marks = ' '.join(f"{key} {r.get('drawn_' + key, 0):.1f}" for key in LIMIT if (r.get('drawn_' + key) or 0) > LIMIT[key])
        pen.text((ox + 6, oy + 4), f"{r['kind']} {r['highway']} {r['pack_length']:.0f} m x{r['pieces']}  {r['lat']}, {r['lon']}  "
                 f"z {lo + 2:.0f}..{hi - 3:.0f} (x{sy / sx:.0f})  {marks}", fill=(20, 20, 20))
        pen.rectangle([ox, oy, ox + w - 1, oy + h - 1], outline=(210, 210, 205))
    image.save(path)
    return path


def main():
    import road_quality as rq
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--region', help='region id in a country of several (default: the first)')
    p.add_argument('--box', type=float, nargs=4, metavar=('LAT0', 'LON0', 'LAT1', 'LON1'))
    p.add_argument('--generator', type=Path, help='another generator.lua (an A/B)')
    p.add_argument('--label', default='run')
    p.add_argument('--sheet', type=int, default=0, help='draw the N worst spans from the side')
    p.add_argument('--near', type=float, nargs=2, metavar=('LAT', 'LON'), help='only the spans within --reach m of a place')
    p.add_argument('--reach', type=float, default=400.)
    a = p.parse_args()
    out = ROOT / 'out' / 'spans' / a.label
    out.mkdir(parents=True, exist_ok=True)
    if a.near and not a.box:
        d = (a.reach + 1500) / 111000.
        a.box = [a.near[0] - d, a.near[1] - d * 1.6, a.near[0] + d, a.near[1] + d * 1.6]
    rows = census(rq.Pack(a.pack, a.region), a.box, a.generator)
    if a.near:
        rows = [r for r in rows if math.hypot((r['lat'] - a.near[0]) * 111000., (r['lon'] - a.near[1]) * 111000. * math.cos(math.radians(a.near[0]))) <= a.reach]
        for r in rows:
            s, z, zd, g = r['_line']
            print(f"--- {r['kind']} {r['highway']} {r['id']} x{r['pieces']} {r['lat']}, {r['lon']}")
            for k in range(len(s)):
                print(f"   s {s[k]:7.1f}  pack {z[k]:7.2f}  drawn {zd[k]:7.2f}" + (f"  ground {g[k]:7.2f}" if g is not None else ''))
    report = summary(rows)
    (out / 'report.json').write_text(json.dumps(report, indent=1), encoding='utf8')
    keys = [k for k in (rows[0] if rows else {}) if not k.startswith('_')]
    keys = sorted({k for r in rows for k in r if not k.startswith('_')}, key=lambda k: (k not in keys, keys.index(k) if k in keys else 0, k))
    with open(out / 'spans.csv', 'w', newline='', encoding='utf8') as f:
        w = csv.DictWriter(f, keys, extrasaction='ignore')
        w.writeheader()
        for r in worst(rows):
            w.writerow({k: (round(v, 2) if isinstance(v, float) and k not in ('lat', 'lon') else v) for k, v in r.items()})
    if a.sheet:
        sheet(rows, out / 'sheet.png', a.sheet)
    for kind_, entry in report.items():
        print(f"{kind_}: {entry['count']} spans, {entry['km']} km")
        for key in LIMIT:
            cells = [f"{label} {entry[label + '_' + key]['over']:4d} over {entry[label + '_' + key]['limit']:g} (max {entry[label + '_' + key]['max']:g}, p90 {entry[label + '_' + key]['p90']:g})"
                     for label in ('pack', 'drawn') if f'{label}_{key}' in entry]
            if cells:
                print(f'  {key:7s} ' + ' | '.join(cells))
    print(out)


if __name__ == '__main__':
    main()
