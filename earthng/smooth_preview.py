"""Plan curves, before and after: one tile's road layer drawn from above with tune.smooth 0 and 1.

  python earthng/smooth_preview.py --pack <earthng_xx.zip> --lat 46.9929 --lon 7.5309 --out out/hyperreal/bern

The native Lua generator builds the tile outside the game (the road quality bench's harness). The
picture is the generator's own triangles: asphalt, sidewalk, curb and painted lines. It shows the
shape of the road, not the game's materials or light. report.json has the cost of both builds.
"""
import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import road_quality as rq

# drawn in this order; the first matching prefix wins
LAYERS = [('ground', (96, 122, 74)), ('verge', (104, 124, 80)), ('road', (62, 64, 68)), ('paved', (120, 118, 112)),
          ('footway', (150, 146, 136)), ('sidewalk', (168, 164, 156)), ('curb', (214, 212, 204)), ('mark', (240, 238, 226))]


def layer_of(material):
    name = material.replace('e2rf_', '')
    if name.startswith('mark') or name.startswith('line') or name.startswith('zebra'):
        return 'mark'
    for key, _ in LAYERS:
        if name.startswith(key):
            return key
    return 'ground' if name in rq.GROUND or 'e2rf_' + name in rq.GROUND or 'e2rf_' + name in rq.COVER else None


def draw(result, rect, scale):
    w, h = int((rect[2] - rect[0]) * scale), int((rect[3] - rect[1]) * scale)
    image = Image.new('RGB', (w, h), (88, 110, 70))
    pen = ImageDraw.Draw(image)
    by_layer = {}
    for material, text in result['mats'].items():
        key = layer_of(material)
        if key and text:
            by_layer.setdefault(key, []).append(np.array(text.split(), dtype=float).reshape(-1, 3, 3))
    for key, colour in LAYERS:
        for tris in by_layer.get(key, []):
            for t in tris:
                pen.polygon([((p[0] - rect[0]) * scale, (rect[3] - p[1]) * scale) for p in t], fill=colour)
    return image


def kinks(result, least=2):
    """Breaks of the carriageway's edge: turns of `least` degrees or more between the outer
    edges of consecutive asphalt quads, per km of edge (the mouths' fans are left out)."""
    count, metres = 0, 0
    for material, text in result['mats'].items():
        if not material.startswith('e2rf_road') or not text:
            continue
        tris = np.array(text.split(), dtype=float).reshape(-1, 3, 3)[:, :, :2]
        edges = {}
        for t in tris:
            for a, b in ((0, 1), (1, 2), (2, 0)):
                key = tuple(sorted((tuple(np.round(t[a], 2)), tuple(np.round(t[b], 2)))))
                edges[key] = edges.get(key, 0) + 1
        ends = {}
        for (a, b), n in edges.items():
            if n == 1:                                  # an outline edge of the asphalt
                ends.setdefault(a, []).append(b)
                ends.setdefault(b, []).append(a)
                metres += math.dist(a, b)
        for p, others in ends.items():
            if len(others) == 2:
                (ax, ay), (bx, by) = others
                h1, h2 = math.atan2(p[1] - ay, p[0] - ax), math.atan2(by - p[1], bx - p[0])
                turn = abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi) * 180 / math.pi
                if least <= turn < 60:                  # 60 and over: a quad's own corner at a mouth
                    count += 1
    return count, metres


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack', required=True)
    ap.add_argument('--lat', type=float, required=True)
    ap.add_argument('--lon', type=float, required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--scale', type=float, default=4, help='pixels per metre')
    ap.add_argument('--window', type=float, default=180, help='metres of the close-up')
    args = ap.parse_args()
    pack = rq.Pack(args.pack)
    g = pack.region['geo']
    det = g[4] * g[7] - g[5] * g[6]
    x = ((args.lon - g[2]) * g[7] - g[5] * (args.lat - g[3])) / det
    y = (g[4] * (args.lat - g[3]) - g[6] * (args.lon - g[2])) / det
    i, j = int(x // pack.size), int(y // pack.size)
    rect = [i * pack.size, j * pack.size, (i + 1) * pack.size, (j + 1) * pack.size]
    lua, mods, build, data, slots = rq.lua_runtime(pack)
    sea = pack.region.get('seaLevel')
    cover = lua.table_from({m: True for m in rq.COVER | rq.GROUND | rq.WALK})
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report, images = {'lat': args.lat, 'lon': args.lon, 'tile': [i, j], 'pack': Path(args.pack).name}, {}
    for label, smooth in (('before', 0), ('after', 1)):
        tune = lua.table_from({'smooth': smooth})
        r = build(mods['generator'], mods['cellformat'], data, slots, i, j, pack.size, pack.cell, sea, tune, cover, 3)
        if r is None:
            raise SystemExit('no cells under this tile')
        result = {'ms': r.ms, 'tris': r.tris, 'mats': dict(r.mats)}
        n2, metres = kinks(result, 2)
        n5, _ = kinks(result, 5)
        report[label] = {'ms': round(result['ms'], 1), 'tris': int(result['tris']), 'edge_km': round(metres / 1000, 2),
                         'breaks_2deg_per_km': round(n2 / max(metres / 1000, 1e-9), 1),
                         'breaks_5deg_per_km': round(n5 / max(metres / 1000, 1e-9), 1),
                         # over any piece of an arc (a right angle's pieces reach 5.2 degrees)
                         'breaks_8deg_per_km': round(kinks(result, 8)[0] / max(metres / 1000, 1e-9), 1)}
        images[label] = draw(result, rect, args.scale)
        images[label].save(out / f'{label}.png')
    # the close-up: the window where the two pictures differ most
    a, b = (np.asarray(images[k], dtype=np.int16) for k in ('before', 'after'))
    diff = (np.abs(a - b).sum(axis=2) > 40).astype(np.float32)
    win = int(args.window * args.scale)
    stride = win // 4
    best, at = -1, (0, 0)
    for top in range(0, diff.shape[0] - win + 1, stride):
        for left in range(0, diff.shape[1] - win + 1, stride):
            score = diff[top:top + win, left:left + win].sum()
            if score > best:
                best, at = score, (top, left)
    top, left = at
    zoom = 2
    pair = Image.new('RGB', (win * zoom * 2 + 12, win * zoom), (20, 20, 20))
    for n, key in enumerate(('before', 'after')):
        crop = images[key].crop((left, top, left + win, top + win)).resize((win * zoom, win * zoom), Image.LANCZOS)
        pair.paste(crop, (n * (win * zoom + 12), 0))
    pair.save(out / 'before-after.png')
    cx, cy = rect[0] + (left + win / 2) / args.scale, rect[3] - (top + win / 2) / args.scale
    report['closeup'] = {'lat': round(g[3] + g[6] * cx + g[7] * cy, 6), 'lon': round(g[2] + g[4] * cx + g[5] * cy, 6),
                         'metres': args.window}
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
