"""Biome census: what the native Lua generator lays and plants round a point of any pack, outside the game.

  python earthng/biome_census.py --pack <mods>/earthng_california.zip --lat 36.5785 --lon -118.2923 --label whitney
  python earthng/biome_census.py --pack ... --lat ... --lon ... --label x --tiles 3 --no-biome   # as before biomes

The tiles round the point (--tiles x --tiles, 500 m each) are built near, with decor, at the
panel's --quality, from the pack's own blocks (only those under the tiles are read, so a whole
state's pack works). The planet's climate grid comes from out/climate (earthng/build_climate.py).
The report gives the ground's area by material, the plants and stones by set, the tile build
times, and map.png: the ground's materials from above with the crowns, shrubs, tufts and stones
over them. Runs go to out/biomes/<label>.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys
import time
import zipfile

from lupa.luajit21 import LuaRuntime
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import country_format as binary  # noqa: E402
import fast_sources  # noqa: E402

LUA = ROOT / 'mod/lua/ge/extensions/e2r'
CLIMATE = ROOT / 'out/climate'

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
local road, scene = generator.build(cells, i, j, options)
local tris, items = {}, {}
for _, manifest in ipairs({road, scene}) do
  for _, item in ipairs(manifest.items) do
    if item.kind == 'proc' then
      for _, mesh in ipairs(item.meshes) do
        local v = mesh.verts
        for k = 1, #mesh.faces, 3 do
          local a, b, c = v[mesh.faces[k].v + 1], v[mesh.faces[k + 1].v + 1], v[mesh.faces[k + 2].v + 1]
          tris[#tris + 1] = string.format('%s %.1f %.1f %.1f %.1f %.1f %.1f', mesh.material,
            a.x + item.pos[1], a.y + item.pos[2], b.x + item.pos[1], b.y + item.pos[2], c.x + item.pos[1], c.y + item.pos[2])
        end
      end
    elseif item.kind == 'static' then
      items[#items + 1] = string.format('%s %s %.2f %.2f %.2f', item.name, item.shape, item.pos[1], item.pos[2], item.scale or 1)
    end
  end
end
return table.concat(tris, '\\n'), table.concat(items, '\\n'), table.concat(scene.stockMaterials or {}, ' ')
'''

# map colours of the ground materials (e2rf_<kind>)
GROUND = {'ground': (110, 150, 70), 'forest': (70, 115, 55), 'park': (90, 170, 80), 'meadow': (150, 185, 90),
          'farmland': (190, 170, 110), 'desert': (214, 190, 140), 'dune': (236, 214, 160), 'steppe': (196, 186, 120),
          'dry_grass': (214, 186, 100), 'tundra': (130, 140, 95), 'alpine': (140, 160, 110), 'scree': (150, 145, 135),
          'bare_rock': (115, 110, 105), 'snow': (250, 252, 255), 'snow_edge': (215, 225, 230), 'glacier': (210, 235, 250),
          'water': (90, 140, 200), 'beach': (230, 214, 170), 'heath': (160, 150, 95), 'scrub': (120, 140, 80),
          'paved': (170, 168, 165), 'road': (60, 60, 62), 'road_major': (40, 40, 42), 'sidewalk': (180, 180, 180)}
DOTS = {'tree': (20, 70, 20), 'grass': (240, 220, 60), 'rock': (90, 60, 40), 'flower': (230, 120, 200),
        'fern': (40, 140, 60), 'bush': (40, 110, 40)}


class Region:
    """One region of a country ZIP: its manifest, frame and the blocks under some tiles."""

    def __init__(self, path, lat, lon):
        self.zip = zipfile.ZipFile(path)
        names = self.zip.namelist()
        country = json.loads(self.zip.read(next(n for n in names if n.count('/') == 3 and n.endswith('manifest.json'))))
        hit = None
        for entry in country['regions']:
            if any(b[0] <= lon <= b[2] and b[1] <= lat <= b[3] for b in entry.get('coverage', [])):
                hit = entry
                break
        if hit is None:
            raise SystemExit(f'{path}: no region covers {lat}, {lon}')
        self.region = json.loads(self.zip.read(hit['manifest'].lstrip('/')))
        r = self.region
        self.size, self.cell = r['tileSize'], r['cellSize']
        x, y = fast_sources.Frame.of(r).local([lon], [lat])
        self.x, self.y = float(x[0]), float(y[0])
        self.blocks = {}

    def range(self, i, j):
        b = binary.BLOCK
        key = (i // b, j // b)
        if key not in self.blocks:
            entry = self.region['blocks'].get(f'{key[0]}_{key[1]}')
            data = self.zip.read(entry['path'].lstrip('/')) if entry else None
            self.blocks[key] = (data, binary.decode_block(data)) if data else None
        block = self.blocks[key]
        if not block:
            return None
        hit = block[1].get(binary.slot(i, j))
        return hit and (block[0], hit)


def runtime(region, biome=True):
    lua = LuaRuntime(unpack_returned_tuples=True)
    if biome:
        lua.execute(f"package.path = '{(ROOT / 'mod/lua').as_posix()}/?.lua;' .. package.path")
    load = lua.eval('function(source, name) return assert(load(source, "@" .. name))() end')
    mods = {name: load((LUA / f'{name}.lua').read_text(encoding='utf8'), f'{name}.lua') for name in ('cellformat', 'generator')}
    if biome:
        lua.eval('require')('ge/extensions/e2r/biome').ROOT = (CLIMATE / '1').as_posix() + '/'
    quality = load((LUA / 'quality.lua').read_text(encoding='utf8'), 'quality.lua')

    def data(ci, cj):
        hit = region.range(ci, cj)
        return hit and bytes(hit[0])

    def slots(ci, cj):
        hit = region.range(ci, cj)
        return hit and lua.table_from([hit[1][0] + 1, hit[1][1]])
    build = lua.eval('function(src) return assert(load(src, "@biome_census")) end')(BUILD)
    return lua, mods, quality, build, data, slots


def set_of(shape):
    """A short name of a stock shape's family: 'juniper', 'desert_rocks', 'palm', ..."""
    s = shape.lower()
    for key in ('juniper', 'grey_bush', 'dry_bush', 'dry_plant', 'dead_bush', 'dry_grass', 'deserttree', 'spanishbayonet',
                'rocks_desert', 'utah_boulder', 'utah_rock', 'rockface', 'eca_rock', 'oak_a', 'oak_b', 'oak_c', 'oak_d',
                'pine_radiata', 'eucalyptus', 'trees_shrub', 'fanpalm', 'italy_palm', 'trees_palm', 'tro_', 'tropical_plant',
                'holm_oak', 'cork_oak', 'olive', 'cypress', 'maritime_pine', 'scots_pine', 'douglasfir', 'poplar',
                'oak_', 'beech', 'aspen', 'generibush', 'clover', 'daisies', 'ferns', '3d_grass', 'scraggly', 'fluffy'):
        if key in s:
            return key.strip('_')
    return s.rsplit('/', 1)[-1].replace('.dae', '')


def census(args):
    region = Region(args.pack, args.lat, args.lon)
    lua, mods, quality, build, data, slots = runtime(region, not args.no_biome)
    preset = quality.preset(args.quality)
    r = region.region
    options = lua.table_from({'tileSize': region.size, 'seaLevel': r.get('seaLevel', 20), 'latitude': r['geo'][3],
                              'pause': lua.eval('function() end')})
    if not args.no_biome:
        options['geo'] = lua.table_from(r['geo'])
    if r.get('nature'):
        options['nature'] = lua.table_from(r['nature'])
    for key in ('maxTrees', 'maxFarTrees', 'maxGrass', 'maxRocks', 'forestSpacing', 'groundSpacing', 'groundTrees'):
        options[key] = preset[key]
    size = int(region.size)
    ci, cj = math.floor(region.x / size), math.floor(region.y / size)
    half = args.tiles // 2
    ground, plants, sets, times, stock = Counter(), Counter(), Counter(), [], set()
    tris, items = [], []
    for j in range(cj - half, cj - half + args.tiles):
        for i in range(ci - half, ci - half + args.tiles):
            started = time.perf_counter()
            out = build(mods['generator'], mods['cellformat'], data, slots, i, j, size, int(region.cell), options)
            times.append(time.perf_counter() - started)
            if out is None:
                continue
            t, s, m = out
            stock.update(m.split())
            for line in t.split('\n') if t else ():
                mat, *v = line.split(' ')
                v = list(map(float, v))
                area = abs((v[2] - v[0]) * (v[5] - v[1]) - (v[4] - v[0]) * (v[3] - v[1])) / 2
                kind = mat.removeprefix('e2rf_')
                ground[kind] += area
                tris.append((kind, v))
            for line in s.split('\n') if s else ():
                name, shape, x, y, scale = line.split(' ')
                prefix = name.removeprefix('e2rl_').split('_', 2)
                layer = prefix[2] if len(prefix) > 2 else name
                layer = layer.split('_')[0].rstrip('b') if not layer.startswith('tree') else 'tree'
                if layer.startswith('srock'):
                    layer = 'rock'
                plants[layer] += 1
                sets[f'{layer}:{set_of(shape)}'] += 1
                items.append((layer, float(x), float(y)))
    total = sum(ground.values()) or 1
    report = {'pack': str(args.pack), 'lat': args.lat, 'lon': args.lon, 'biome': not args.no_biome,
              'tiles': args.tiles ** 2, 'quality': args.quality,
              'ground_share': {k: round(v / total, 4) for k, v in ground.most_common()},
              'plants': dict(plants.most_common()), 'sets': dict(sets.most_common()),
              'build_ms': {'mean': round(1000 * sum(times) / len(times), 1), 'max': round(1000 * max(times), 1)},
              'stock_materials': sorted(stock)}
    out = ROOT / 'out/biomes' / args.label
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    draw(out / 'map.png', tris, items, (ci - half) * size, (cj - half) * size, args.tiles * size)
    return report


def draw(path, tris, items, x0, y0, span):
    px_m = max(.5, span / 1500)
    w = int(span / px_m)
    img = Image.new('RGB', (w, w), (0, 0, 0))
    d = ImageDraw.Draw(img)

    def px(x, y):
        return ((x - x0) / px_m, (y0 + span - y) / px_m)
    order = {'road': 2, 'road_major': 2, 'sidewalk': 2}
    for kind, v in sorted(tris, key=lambda t: order.get(t[0], 0)):
        d.polygon([px(v[0], v[1]), px(v[2], v[3]), px(v[4], v[5])], fill=GROUND.get(kind, (255, 0, 255)))
    for layer, x, y in items:
        cx, cy = px(x, y)
        r = 1.6 if layer in ('grass', 'flower') else 2.4
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=DOTS.get(layer, (255, 255, 255)))
    img.save(path)


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--tiles', type=int, default=3, help='tiles per side round the point')
    p.add_argument('--quality', type=int, default=50)
    p.add_argument('--no-biome', action='store_true', help='without the climate (the generator as before biomes)')
    report = census(p.parse_args())
    print(json.dumps({k: v for k, v in report.items() if k != 'stock_materials'}, indent=1))


if __name__ == '__main__':
    main()
