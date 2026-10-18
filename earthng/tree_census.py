"""Tree census: crowns the native Lua generator plants over a test area, by source, outside the game.

  python earthng/tree_census.py --label base --generator old_generator.lua
  python earthng/tree_census.py --label try --compare base --map -17250 -6250 1500

Every tile of the pack (or every --step-th) is built near, with decor, at the panel's --quality
(50 = Balanced), its cells loaded as native.lua loads them: the tile's own cells first, then
the 40 m pad. A crown's source is read from its name: forest, park, residential, orchard,
scrub, heath (OSM areas), ground (open land, the hill lattice), town (open land among
buildings), row (OSM natural=tree_row). The report gives crowns per tile and per hectare,
the share of each source and the tiles at the cap; --map draws crowns over the pack's own
areas, roads and buildings (map.png). Runs go to out/trees/<label>.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import time

from PIL import Image, ImageDraw

import road_quality as rq

ROOT = Path(__file__).resolve().parents[1]
QUALITY = rq.LUA / 'quality.lua'

BUILD = '''
local generator, cellformat, data, slots, i, j, size, cellSize, options = ...
local x0, y0 = i * size, j * size
local cells, seen = {}, {}
local function add(ci, cj)
  local range = slots(ci, cj)
  if range and not seen[ci .. '_' .. cj] then
    seen[ci .. '_' .. cj] = true
    cells[#cells + 1] = cellformat.cell(data(ci, cj), range[1], range[2], ci * cellSize, cj * cellSize,
      {ci * cellSize, cj * cellSize, (ci + 1) * cellSize, (cj + 1) * cellSize}, nil, {x0, y0, x0 + size, y0 + size})
  end
end
for ci = math.floor(x0 / cellSize), math.ceil((x0 + size) / cellSize) - 1 do
  for cj = math.floor(y0 / cellSize), math.ceil((y0 + size) / cellSize) - 1 do add(ci, cj) end
end
for ci = math.floor((x0 - 40) / cellSize), math.ceil((x0 + size + 40) / cellSize) - 1 do
  for cj = math.floor((y0 - 40) / cellSize), math.ceil((y0 + size + 40) / cellSize) - 1 do add(ci, cj) end
end
if #cells == 0 then return nil end
local _, scene = generator.build(cells, i, j, options)
local out = {}
for _, item in ipairs(scene.items) do
  local source = item.kind == 'static' and item.name:match('_tree_(.*)$')
  if source then out[#out + 1] = string.format('%s %.2f %.2f', source, item.pos[1], item.pos[2]) end
end
return table.concat(out, '\\n')
'''
COLOURS = {'ground': (220, 40, 30), 'town': (20, 20, 20), 'forest': (20, 90, 30), 'park': (40, 150, 40),
           'residential': (230, 150, 20), 'row': (160, 0, 200)}
FILL = {'forest': (150, 196, 140), 'park': (190, 226, 170), 'residential': (226, 220, 206),
        'paved': (210, 206, 214), 'water': (160, 196, 230), 'meadow': (214, 232, 180)}


def source_of(name):
    """'town_123' -> 'town'; an older generator named a crown by its key alone."""
    kind, _, key = name.rpartition('_')
    return kind or 'lattice'


def census(pack, generator, quality, step):
    lua, mods, _, data, slots = rq.lua_runtime(pack, generator)
    load = lua.eval('function(source, name) return assert(load(source, "@" .. name))() end')
    preset = load(QUALITY.read_text(encoding='utf8'), 'quality.lua').preset(quality)
    options = lua.table_from({'tileSize': pack.size, 'seaLevel': pack.region.get('seaLevel', 20),
                              'latitude': pack.region['geo'][3], 'pause': lua.eval('function() end')})
    for key in ('maxTrees', 'maxFarTrees', 'maxGrass', 'maxRocks', 'forestSpacing', 'groundSpacing', 'groundTrees'):
        options[key] = preset[key]
    build = lua.eval('function(src) return assert(load(src, "@tree_census")) end')(BUILD)
    size, cell = int(pack.size), int(pack.cell)
    cells = pack.cells()
    tiles = {}
    for i in range(min(c[0] for c in cells) * cell // size, (max(c[0] for c in cells) + 1) * cell // size, step):
        for j in range(min(c[1] for c in cells) * cell // size, (max(c[1] for c in cells) + 1) * cell // size, step):
            text = build(mods['generator'], mods['cellformat'], data, slots, i, j, size, cell, options)
            if text is not None:
                tiles[f'{i}_{j}'] = [(float(x), float(y), source_of(name))
                                     for name, x, y in (line.split(' ') for line in text.split('\n') if line)]
    return tiles, int(preset['maxTrees'])


def summary(tiles, cap, size):
    sources = Counter(t[2] for crowns in tiles.values() for t in crowns)
    total = sum(sources.values())
    hectares = len(tiles) * size * size / 1e4
    return {'tiles': len(tiles), 'crowns': total, 'per_tile': round(total / max(1, len(tiles))),
            'per_ha': round(total / max(1e-9, hectares), 1), 'cap': cap,
            'tiles_at_cap': sum(1 for crowns in tiles.values() if len(crowns) >= cap),
            'sources': {k: v for k, v in sources.most_common()}}


def draw_map(pack, tiles, x0, y0, size, path):
    px_m = max(1., size / 1200)
    width = int(size / px_m)
    img = Image.new('RGB', (width, width), (236, 232, 222))
    d = ImageDraw.Draw(img)

    def px(p):
        return ((p[0] - x0) / px_m, (y0 + size - p[1]) / px_m)
    cell = int(pack.cell)
    layers, seen = {'areas': [], 'buildings': [], 'roads': [], 'lines': []}, set()
    for ci in range(int(x0 // cell) - 1, int((x0 + size) // cell) + 1):
        for cj in range(int(y0 // cell) - 1, int((y0 + size) // cell) + 1):
            source = pack.source(ci, cj)
            for name, features in (source or {}).items():
                for f in features if name in layers else ():
                    # areas are clipped per cell under one id: every cell's piece is drawn
                    if name == 'areas' or (name, f['id']) not in seen:
                        seen.add((name, f['id']))
                        layers[name].append(f)
    for f in sorted(layers['areas'], key=lambda f: {'residential': 0, 'paved': 1}.get(f['kind'], 2)):
        d.polygon([px(p) for p in f['rings'][0]], fill=FILL.get(f['kind'], (220, 236, 190)))
        for hole in f['rings'][1:]:
            d.polygon([px(p) for p in hole], fill=(236, 232, 222))
    for f in layers['roads']:
        d.line([px(p) for p in f['points']], fill=(255, 255, 255), width=max(1, int(f['width'] / px_m)))
    for f in layers['lines']:
        if f['kind'] == 'tree_row':
            d.line([px(p) for p in f['points']], fill=(200, 60, 200), width=2)
    for f in layers['buildings']:
        d.polygon([px(p) for p in f['rings'][0]], fill=(150, 140, 135), outline=(110, 100, 95))
    n, r = 0, max(1.5, 3.5 / px_m)
    for crowns in tiles.values():
        for x, y, source in crowns:
            if x0 <= x < x0 + size and y0 <= y < y0 + size:
                cx, cy = px((x, y))
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=COLOURS.get(source, (0, 0, 0)))
                n += 1
    legend = '  '.join(COLOURS)
    d.rectangle([0, 0, width, 22], fill=(255, 255, 255))
    d.text((4, 5), f'{n} crowns in {size:.0f} m ({n / (size * size / 1e4):.0f}/ha)   {legend}', fill=(0, 0, 0))
    img.save(path)


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', type=Path, default=ROOT / 'out/polygon/earthng_kyiv10.zip')
    p.add_argument('--label', default='run')
    p.add_argument('--step', type=int, default=1, help='every n-th tile in x and y (a quick loop)')
    p.add_argument('--quality', type=int, default=50, help='the panel slider: 0 Potato, 50 Balanced, 100 OASIS')
    p.add_argument('--generator', type=Path, help='another generator.lua (an A/B against an older version)')
    p.add_argument('--map', type=float, nargs=3, metavar=('X0', 'Y0', 'SIZE'), help='draw a square of the area, m')
    p.add_argument('--compare', nargs='*', help='labels of earlier runs to print beside this one')
    p.add_argument('--out', type=Path, default=ROOT / 'out/trees')
    a = p.parse_args()
    pack = rq.Pack(a.pack)
    started = time.perf_counter()
    tiles, cap = census(pack, a.generator, a.quality, a.step)
    out = a.out / a.label
    out.mkdir(parents=True, exist_ok=True)
    report = {'pack': str(a.pack), 'quality': a.quality, 'step': a.step,
              'summary': summary(tiles, cap, pack.size), 'seconds': round(time.perf_counter() - started)}
    (out / 'report.json').write_text(json.dumps(report, indent=1), encoding='utf8')
    (out / 'trees.json').write_text(json.dumps(tiles), encoding='utf8')
    if a.map:
        draw_map(pack, tiles, *a.map, out / 'map.png')
    runs = [(a.label, report['summary'])]
    for label in a.compare or []:
        runs.append((label, json.loads((a.out / label / 'report.json').read_text(encoding='utf8'))['summary']))
    sources = sorted({k for _, s in runs for k in s['sources']}, key=lambda k: -runs[0][1]['sources'].get(k, 0))
    print(f'{"":>16}' + ''.join(f'{label:>12}' for label, _ in runs))
    for key in ('tiles', 'crowns', 'per_tile', 'per_ha', 'tiles_at_cap'):
        print(f'{key:>16}' + ''.join(f'{s[key]:>12}' for _, s in runs))
    for key in sources:
        print(f'{key:>16}' + ''.join(f'{s["sources"].get(key, 0):>12}' for _, s in runs))
    print('report:', out / 'report.json')


if __name__ == '__main__':
    main()
