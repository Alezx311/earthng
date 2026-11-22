"""Shore census: the water of a pack's tiles as the native Lua generator builds it, outside the game.

  python earthng/shore_census.py --pack out/polygon/earthng_polygon.zip --tiles=-5_-4,-4_-4
  python earthng/shore_census.py --pack <mods>/earthng_kyiv-oblast.zip --at 50.4265,30.5810 --ring 1

Each tile is built near twice: with shorelines (shore.lua) and without (options.shore = false,
the water on its DEM as before). For both it reports the water's objects, how much of the
ground under them is open water, and the length of block edge that shows: a block's side where
the ground beside it is still under the water is a straight cut of water in the open, the
"block of water with no shore". With shorelines it also counts the banks by kind and the
plants along them. map-<tile>.png: the ground by material, the open water, the mapped shore
(black) and the cuts (red), on the left with shorelines and on the right without.
Runs go to out/shore/<label>.
"""
import argparse
import json
import math
from pathlib import Path
import time

from lupa.luajit21 import LuaRuntime
import numpy as np
from PIL import Image, ImageDraw

import road_quality as rq

ROOT = Path(__file__).resolve().parents[1]
RES = 1.0   # m a pixel

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
-- The collector stands still while the tile is built: a cycle over the whole heap is ~100 ms,
-- and whether a build tips one over is chance. What a build costs the game is its own time and
-- the garbage it leaves (mb), which the game's collector pays for at its own pace.
collectgarbage('collect')
collectgarbage('stop')
local kb = collectgarbage('count')
local marks, last = {}, os.clock()
options.mark = function(name) local now = os.clock(); marks[name] = (marks[name] or 0) + (now - last) * 1000; last = now end
local t = os.clock()
local road, scene = generator.build(cells, i, j, options)
local ms = (os.clock() - t) * 1000
local mb = (collectgarbage('count') - kb) / 1024
collectgarbage('restart')
local fmt, mats, water, plants = string.format, {}, {}, {}
for layer, manifest in ipairs({road, scene}) do
  for _, item in ipairs(manifest.items) do
    local p = item.pos
    if item.kind == 'water' then
      water[#water + 1] = fmt('block %.3f %.3f %.3f %.3f %.3f %s', p[1] - item.scale[1] / 2, p[2] - item.scale[2] / 2,
        p[1] + item.scale[1] / 2, p[2] + item.scale[2] / 2, p[3], item.look)
    elseif item.kind == 'river' then
      local parts = {'river'}
      for _, n in ipairs(item.nodes) do parts[#parts + 1] = fmt('%.3f %.3f %.3f %.3f', n[1], n[2], n[3], n[4]) end
      water[#water + 1] = table.concat(parts, ' ')
    elseif item.kind == 'static' and item.name:find('_shore_', 1, true) then
      plants[#plants + 1] = fmt('%.2f %.2f %s', p[1], p[2], item.shape)
    end
    for _, mesh in ipairs(item.meshes or {}) do
      local m = mesh.material
      -- the ground and what is draped on it: the road layer's land, the scene layer's covers
      if not m:find('^e2rf_col_') and (layer == 1 or generator.SHORE_COVERS[m]) then
        local parts = mats[m] or {}
        mats[m] = parts
        local verts, faces = mesh.verts, mesh.faces
        for k = 1, #faces do
          local v = verts[faces[k].v + 1]
          parts[#parts + 1] = fmt('%.3f %.3f %.3f', v.x + p[1], v.y + p[2], v.z + p[3])
        end
      end
    end
  end
end
local result = {ms = ms, mb = mb, mats = {}, water = table.concat(water, '\\n'), plants = table.concat(plants, '\\n'), stages = marks}
for m, parts in pairs(mats) do result.mats[m] = table.concat(parts, ' ') end
return result
'''
# the scene layer's draped land (not walls, roofs or fences)
COVERS = ('ground', 'beach', 'scree', 'bare_rock', 'wetland', 'bare_ground', 'paved', 'park', 'forest', 'meadow',
          'farmland', 'scrub', 'heath', 'orchard', 'dune', 'desert', 'snow', 'mud', 'sand')
COLOURS = {'e2rf_beach': (232, 214, 160), 'e2rf_scree': (168, 162, 150), 'e2rf_bare_rock': (120, 118, 114),
           'e2rf_wetland': (110, 124, 84), 'e2rf_bare_ground': (160, 132, 96), 'e2rf_paved': (190, 190, 196),
           'e2rf_forest': (88, 128, 76), 'e2rf_park': (140, 178, 110), 'e2rf_meadow': (176, 196, 120),
           'e2rf_dune': (226, 200, 140), 'e2rf_mud': (96, 78, 60)}
ROADS = (70, 70, 74)
LAND = (150, 180, 110)


def runtime(pack):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f"package.path = '{(ROOT / 'mod/lua').as_posix()}/?.lua;' .. package.path")
    # the game's own trace limits (its lua/ge/main.lua): with LuaJIT's defaults the generator
    # overflows the trace cache, which is flushed 20-30 times a tile, and a build is timed at
    # three times what it takes
    lua.execute("jit.opt.start('minstitch=10000000', 'maxtrace=10000', 'maxmcode=8192', 'maxside=25', 'hotexit=100')")
    load = lua.eval('function(source, name) return assert(load(source, "@" .. name))() end')
    cellformat = load((rq.LUA / 'cellformat.lua').read_text(encoding='utf8'), 'cellformat.lua')
    generator = load((rq.LUA / 'generator.lua').read_text(encoding='utf8'), 'generator.lua')
    generator.SHORE_COVERS = lua.table_from({'e2rf_' + k: True for k in COVERS})
    build = lua.eval('function(src) return assert(load(src, "@shore_census")) end')(BUILD)

    def data(ci, cj):
        hit = pack.range(ci, cj)
        return hit and bytes(hit[0])

    def slots(ci, cj):
        hit = pack.range(ci, cj)
        return hit and lua.table_from([hit[1][0] + 1, hit[1][1]])
    return lua, generator, cellformat, build, data, slots


def tile_at(pack, lat, lon):
    g = pack.region['geo']
    # lon = g[2] + g[4] x + g[5] y, lat = g[3] + g[6] x + g[7] y
    det = g[4] * g[7] - g[5] * g[6]
    dlon, dlat = lon - g[2], lat - g[3]
    x, y = (dlon * g[7] - g[5] * dlat) / det, (g[4] * dlat - g[6] * dlon) / det
    return int(x // pack.size), int(y // pack.size)


def water_mask(text, rect, shape):
    """Per pixel: the level of the water object over it (NaN: none)."""
    level = np.full(shape, np.nan)
    h, w = shape
    ys, xs = np.mgrid[0:h, 0:w]
    px, py = rect[0] + (xs + .5) * RES, rect[1] + (ys + .5) * RES
    for line in text.split('\n') if text else ():
        parts = line.split()
        if parts[0] == 'block':
            x0, y0, x1, y1, z = map(float, parts[1:6])
            hit = (px >= x0) & (px <= x1) & (py >= y0) & (py <= y1)
            level = np.where(hit, np.fmax(level, z), level)
        else:
            nodes = np.array(parts[1:], dtype=float).reshape(-1, 4)
            for a, b in zip(nodes, nodes[1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                t = np.clip(((px - a[0]) * dx + (py - a[1]) * dy) / max(1e-9, dx * dx + dy * dy), 0, 1)
                d = np.hypot(px - a[0] - t * dx, py - a[1] - t * dy)
                hit = d <= (a[3] + (b[3] - a[3]) * t) / 2
                level = np.where(hit, np.fmax(level, a[2] + (b[2] - a[2]) * t), level)
    return level


def measure(result, rect, shape):
    tops, names = [], []
    for name, text in result.mats.items():
        tops.append(rq.raster(text, rect, shape))
        names.append(str(name))
    stack = np.stack(tops) if tops else np.full((1,) + shape, np.nan)
    ground = np.nanmax(np.where(np.isnan(stack), -1e9, stack), axis=0)
    top = np.argmax(np.where(np.isnan(stack), -1e9, stack), axis=0)
    level = water_mask(str(result.water), rect, shape)
    under = ~np.isnan(level)
    open_water = under & (ground < level - .02)
    # a block's side in the open: a pixel of open water whose neighbour has no water object over
    # it, though the ground there is under this water's level too (inside the tile only)
    cut = np.zeros(shape, dtype=bool)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        beside_under = np.roll(under, (dy, dx), axis=(0, 1))
        beside_ground = np.roll(ground, (dy, dx), axis=(0, 1))
        cut |= open_water & ~beside_under & (beside_ground < level - .05)
    cut[0, :] = cut[-1, :] = False
    cut[:, 0] = cut[:, -1] = False
    kinds = [line.split()[0] for line in str(result.water).split('\n') if line]
    return {'ms': round(float(result.ms)), 'mb': round(float(result.mb), 1), 'blocks': kinds.count('block'), 'rivers': kinds.count('river'),
            'open_m2': int(open_water.sum() * RES * RES), 'under_land_m2': int((under & ~open_water).sum() * RES * RES),
            'cut_m': int(cut.sum() * RES),
            'plants': len([line for line in str(result.plants).split('\n') if line])}, (top, names, open_water, cut)


def draw(pack, rect, layers, shape):
    top, names, open_water, cut = layers
    img = np.zeros(shape + (3,), dtype=np.uint8)
    img[:] = LAND
    for k, name in enumerate(names):
        colour = COLOURS.get(name) or (ROADS if name.startswith(('e2rf_road', 'e2rf_sidewalk', 'e2rf_curb', 'e2rf_footway')) else None)
        if colour:
            img[top == k] = colour
    img[open_water] = (img[open_water] * .25 + np.array((40, 110, 190)) * .75).astype(np.uint8)
    img[cut] = (230, 30, 30)
    picture = Image.fromarray(img[::-1])
    d = ImageDraw.Draw(picture)
    cell = int(pack.cell)
    h = shape[0]
    for ci in range(int(rect[0] // cell) - 1, int(rect[2] // cell) + 1):
        for cj in range(int(rect[1] // cell) - 1, int(rect[3] // cell) + 1):
            for f in (pack.source(ci, cj) or {}).get('areas', ()):
                if f['kind'] == 'water':
                    for ring in f['rings']:
                        pts = [((p[0] - rect[0]) / RES, h - (p[1] - rect[1]) / RES) for p in ring]
                        d.line(pts + pts[:1], fill=(0, 0, 0), width=1)
    return picture


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--pack', type=Path, default=ROOT / 'out/polygon/earthng_polygon.zip')
    p.add_argument('--region')
    p.add_argument('--tiles', help='tiles i_j, comma separated (--tiles=-7_-4,13_1: an index may be negative)')
    p.add_argument('--at', help='LAT,LON: the tile there')
    p.add_argument('--ring', type=int, default=0, help='with --at: this many tiles round it too')
    p.add_argument('--plants', action='store_true', help="with the flora and the tile's stones (quality 50)")
    p.add_argument('--label', default='run')
    p.add_argument('--out', type=Path, default=ROOT / 'out/shore')
    a = p.parse_args()
    pack = rq.Pack(a.pack, a.region)
    lua, generator, cellformat, build, data, slots = runtime(pack)
    rq.RES = RES
    size = pack.size
    if a.at:
        lat, lon = map(float, a.at.split(','))
        i0, j0 = tile_at(pack, lat, lon)
        tiles = [(i0 + di, j0 + dj) for dj in range(-a.ring, a.ring + 1) for di in range(-a.ring, a.ring + 1)]
    else:
        tiles = [tuple(map(int, t.split('_'))) for t in (a.tiles or '').split(',') if t]
    out = a.out / a.label
    out.mkdir(parents=True, exist_ok=True)
    rows = {}
    shape = (int(size / RES), int(size / RES))
    for i, j in tiles:
        rect = [i * size, j * size, (i + 1) * size, (j + 1) * size]
        pictures, row = [], {}

        def built(mode):
            options = {'tileSize': size, 'seaLevel': pack.region.get('seaLevel'), 'pause': lua.eval('function() end'),
                       'geo': lua.table_from(pack.region['geo']), 'shore': mode == 'shore',
                       'maxTrees': 0, 'maxGrass': 4000 if a.plants else 0, 'maxRocks': 80 if a.plants else 0}
            return build(generator, cellformat, data, slots, i, j, size, pack.cell, lua.table_from(options))
        # the first build of a tile pays for its cells and the traces: each mode is timed on its
        # faster run of two, in turn
        first = {mode: built(mode) for mode in ('shore', 'dem')}
        for mode in ('shore', 'dem'):
            result = first[mode] and built(mode)
            if result is None:
                break
            if first[mode].ms < result.ms:
                result = first[mode]
            row[mode], layers = measure(result, rect, shape)
            if mode == 'dem':
                row[mode]['stages'] = {str(k): round(float(v), 1) for k, v in result.stages.items()}
            if mode == 'shore':
                row[mode]['shore_ms'] = round(sum(float(result.stages[k] or 0) for k in ('shoreindex', 'shore', 'shoresink', 'banks')), 1)
                row[mode]['stages'] = {str(k): round(float(v), 1) for k, v in result.stages.items()}
                row[mode]['materials'] = sorted(str(m)[5:] for m in result.mats.keys() if str(m) in COLOURS)
            pictures.append(draw(pack, rect, layers, shape))
        if not row:
            print(f'{i}_{j}: no cells')
            continue
        both = Image.new('RGB', (shape[1] * 2 + 6, shape[0]), (255, 255, 255))
        both.paste(pictures[0], (0, 0))
        both.paste(pictures[1], (shape[1] + 6, 0))
        both.save(out / f'map-{i}_{j}.png')
        lat, lon = pack.geo(rect[0] + size / 2, rect[1] + size / 2)
        row['lat'], row['lon'] = round(lat, 5), round(lon, 5)
        rows[f'{i}_{j}'] = row
        s, o = row['shore'], row['dem']
        print(f"{i}_{j} ({lat:.4f}, {lon:.4f}): shore {s['blocks']} blocks {s['rivers']} rivers, open {s['open_m2']} m2, "
              f"cut {s['cut_m']} m, {s['ms']} ms ({s['shore_ms']} ms of it shore) {s['mb']} MB, plants {s['plants']}, {s['materials']}"
              f" | dem {o['blocks']} blocks {o['rivers']} rivers, open {o['open_m2']} m2, cut {o['cut_m']} m, {o['ms']} ms {o['mb']} MB")
    (out / 'report.json').write_text(json.dumps(rows, indent=1), encoding='utf8')
    print('report:', out / 'report.json')


if __name__ == '__main__':
    main()
