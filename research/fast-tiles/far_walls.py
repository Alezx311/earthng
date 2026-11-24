"""What of a far tile stands across its roads, without the game.

    python research/fast-tiles/far_walls.py --pack <earthng_x.zip> --lat 50.46414 --lon 30.34439 [--around 1]

Builds the far tile under the point (with its trees as cards, as the game asks for it) and counts
the upright sheets whose foot crosses a far road between 0.3 and 1.2 m over it: the cards of its
trees (two crossed sheets as wide as the tree is tall), the walls of its buildings (the box of a
building's bounds), its fences. Each by what a collision rebuild does with it (collision.lua
M.drawn): `met` is in the rebuild, `drawn` is not. Until 24.11 all of it was met, and a card's
clear part was a wall across the street nobody could see; a sheet that is met and crosses a road
is that bug back.
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'earthng'))
import bench_native  # noqa: E402

BUILD = '''
local native, generator, i, j, extra, collision = ...
local function upvalue(f, name)
  for k = 1, 200 do local n, v = debug.getupvalue(f, k); if not n then return end; if n == name then return v end end
end
local active = upvalue(native.update, 'active')
local d = active.region.data
local loadCell = upvalue(upvalue(native.update, 'buildTile'), 'loadCell')
local function cellOf(ci, cj, keep)
  local co = coroutine.create(function() return loadCell(string.format('%d_%d', ci, cj), ci, cj, keep) end)
  while true do
    local ok, cell = coroutine.resume(co)
    if not ok then error(cell) end
    if coroutine.status(co) == 'dead' then return cell end
  end
end
local list = {}
local keep = {i * 500, j * 500, (i + 1) * 500, (j + 1) * 500}
for ci = math.floor((i * 500 - 40) / d.cellSize), math.floor((i * 500 + 540) / d.cellSize) do
  for cj = math.floor((j * 500 - 40) / d.cellSize), math.floor((j * 500 + 540) / d.cellSize) do
    local ok, c = pcall(cellOf, ci, cj, keep)
    if ok and c then list[#list + 1] = c end
  end
end
local options = {tileSize = 500, far = true, farCards = true, pause = function() end,
  seaLevel = d.seaLevel, latitude = d.geo and d.geo[4], geo = d.geo, nature = d.nature, look = d.look, realStyle = true,
  cellSize = d.cellSize, hyper = true, farStep = 100, adaptiveFar = true}
for k, v in pairs(extra or {}) do options[k] = v end
local _, _, far = generator.build(list, i, j, options)
-- every triangle: {material, drawn, x, y, z of its three corners}
local out, n = {}, 0
for _, it in ipairs(far and far.items or {}) do
  if it.kind == 'proc' then
    local drawn = collision.drawn(it, it.meshes) and 1 or 0
    local ox, oy, oz = it.pos[1], it.pos[2], it.pos[3]
    for _, mesh in ipairs(it.meshes) do
      local v, f = mesh.verts, mesh.faces
      for t = 1, #f - 2, 3 do
        local a, b, c = v[f[t].v + 1], v[f[t + 1].v + 1], v[f[t + 2].v + 1]
        n = n + 1
        out[n] = {mesh.material or '', drawn, a.x + ox, a.y + oy, a.z + oz, b.x + ox, b.y + oy, b.z + oz, c.x + ox, c.y + oy, c.z + oz}
      end
    end
  end
end
return out
'''


def height_in(c, x, y):
    """The triangle's z over (x, y), or None outside it."""
    ax, ay, az, bx, by, bz, cx, cy, cz = c
    d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(d) < 1e-9:
        return None
    u = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / d
    v = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / d
    if u < 0 or v < 0 or u + v > 1:
        return None
    return u * az + v * bz + (1 - u - v) * cz


def across(triangles):
    """{(material, drawn): [sheets, sheets across a road]} of the far tile's triangles."""
    roads, sheets = [], defaultdict(dict)
    for material, drawn, *c in triangles:
        if material.startswith('e2rf_road'):
            roads.append(c)
            continue
        ux, uy, uz = c[3] - c[0], c[4] - c[1], c[5] - c[2]
        vx, vy, vz = c[6] - c[0], c[7] - c[1], c[8] - c[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        length = (nx * nx + ny * ny + nz * nz) ** .5
        if length > 1e-9 and abs(nz / length) < .2:
            foot = sorted({(round(c[k], 2), round(c[k + 1], 2)) for k in (0, 3, 6)})
            if len(foot) >= 2:
                z0, z1 = min(c[2], c[5], c[8]), max(c[2], c[5], c[8])
                old = sheets[(material, int(drawn))].get((foot[0], foot[-1]))
                sheets[(material, int(drawn))][(foot[0], foot[-1])] = (min(z0, old[0]), max(z1, old[1])) if old else (z0, z1)
    bins = defaultdict(list)
    for c in roads:
        for bx in range(int(min(c[0], c[3], c[6]) // 8), int(max(c[0], c[3], c[6]) // 8) + 1):
            for by in range(int(min(c[1], c[4], c[7]) // 8), int(max(c[1], c[4], c[7]) // 8) + 1):
                bins[(bx, by)].append(c)
    out = {}
    for key, feet in sheets.items():
        hit = 0
        for (a, b), (z0, z1) in feet.items():
            steps = max(2, int(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** .5 / .5))
            crossed = False
            for k in range(steps + 1):
                x, y = a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps
                for c in bins.get((int(x // 8), int(y // 8)), ()):
                    z = height_in(c, x, y)
                    if z is not None and z0 < z + 1.2 and z1 > z + .3:
                        crossed = True
                        break
                if crossed:
                    break
            hit += crossed
        out[key] = [len(feet), hit]
    return out, len(roads)


def family(material):
    name = material[5:] if material.startswith('e2rf_') else material
    for prefix, label in (('far_tree', 'tree cards'), ('fence', 'fences'), ('wall_', 'building boxes'), ('hw_', 'building boxes'),
                          ('kw_', 'building boxes'), ('clad_', 'building boxes'), ('plinth', 'building boxes'), ('sh_', 'building boxes')):
        if name.startswith(prefix):
            return label
    return name


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', required=True)
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--around', type=int, default=0, help='also the tiles this many steps round it')
    p.add_argument('--quality', type=int, default=100, help="the game's quality preset the tile is built with")
    a = p.parse_args()
    lua, mods, _ = bench_native.runtime(a.pack, game_structs=True, kit=True, houses=True)
    lua.execute("mods.ffi, mods.bit = package.loaded.ffi, bit")
    native = mods['native']
    native.refresh()
    job = native.land(lua.table_from({'lat': a.lat, 'lon': a.lon, 'seq': 1}))
    if job['state'] == 'error':
        raise SystemExit(job['message'])
    x, y = native.localPoint(a.lat, a.lon)
    tune = mods['quality'].preset(a.quality)
    extra = {name: tune[name] for name in ('maxTrees', 'maxFarTrees', 'maxGrass', 'maxRocks', 'forestSpacing', 'groundSpacing',
                                           'groundTrees', 'parkedCars', 'propSpacing', 'detail')}
    build = lua.eval('function(src) return assert(load(src, "@far_walls")) end')(BUILD)
    collision = lua.eval('function(source) return assert(load(source, "@collision.lua"))() end')(
        (ROOT / 'mod/lua/ge/extensions/e2r/collision.lua').read_text(encoding='utf8'))
    total = defaultdict(lambda: [0, 0])
    met_across = 0
    for dj in range(a.around, -a.around - 1, -1):
        for di in range(-a.around, a.around + 1):
            i, j = int(x // 500) + di, int(y // 500) + dj
            rows = build(native, mods['generator'], i, j, lua.table_from(extra), collision)
            found, roads = across([list(t.values()) for t in rows.values()])
            line = defaultdict(lambda: [0, 0])
            for (material, drawn), (sheets, hit) in found.items():
                key = (family(material), 'drawn' if drawn else 'met')
                for acc in (line, total):
                    acc[key][0] += sheets
                    acc[key][1] += hit
                if not drawn:
                    met_across += hit
            parts = ', '.join(f'{k[0]} {k[1]} {v[1]}/{v[0]}' for k, v in sorted(line.items()) if v[1])
            print(f'{i}_{j}: {roads} far road triangles; across a road: {parts or "nothing"}')
    print('\nsheets across a far road / all sheets, by what a collision rebuild does with them:')
    for (name, cls), (sheets, hit) in sorted(total.items(), key=lambda kv: (-kv[1][1], kv[0])):
        print(f'  {name:18s} {cls:5s} {hit:5d} / {sheets}')
    print(f'\nmet and across a road: {met_across}')
    return 1 if met_across else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    sys.exit(main())
