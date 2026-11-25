"""What the car meets over the asphalt of a near tile, without the game.

    python earthng/clear_census.py --pack <earthng_x.zip> --lat 50.4641 --lon 30.3444 [--around 1] [--list 20]
    python earthng/clear_census.py --pack <earthng_x.zip> --lat 50.46 --lon 30.35 --find Чорнобильська

Builds the near tile under the point as the game asks for it (the real art pack, the engine's
grass on, the quality preset) and looks at every 0.25 m of its asphalt (the road layer's
`e2rf_road*` surfaces, junction plates included) for what a collision rebuild would put there
from 6 cm to 1.6 m over it:

  proxy   the invisible collision meshes (e2rf_col_ground under the land, e2rf_col_bldg and the
          other shells of the buildings): nothing is drawn where they stand;
  solid   drawn meshes that collide (kerbs, sidewalks, parked cars, fences, walls);
  static  objects with collision (Forest props `#solid`, TSStatic with a collision mesh), by
          their anchor on the asphalt;
  turf    the hidden terrain block of the engine's grass (turf.lua): its 2 m squares stand
          SINK under the lawn, and a square over the asphalt is a ledge nobody can see.

`--list N` prints the N worst places of each kind with lat/lon (for test_world.py --geo-view).
`--option name=value` passes a generator option (true, false or a number).
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'earthng'))
import bench_native  # noqa: E402

VM_JIT = 'minstitch=10000000,maxtrace=2000,maxmcode=4000,maxside=10,hotexit=200'

CELLS = '''
local native, i, j = ...
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
return list, d
'''

FIND = '''
local list, name = ...
local out, seen = {}, {}
for _, cell in ipairs(list) do
  for _, road in ipairs(cell.roads or {}) do
    local n = (road.tags or {}).name or ''
    if n:find(name, 1, true) and not seen[road.id] then
      seen[road.id] = true
      local p = road.points[math.floor(#road.points / 2) + 1]
      out[#out + 1] = {n, (road.tags or {}).highway or '', p[1], p[2]}
    end
  end
end
return out
'''

BUILD = '''
local generator, list, d, i, j, extra, collision, knock, turf = ...
local options = {tileSize = 500, pause = function() end,
  seaLevel = d.seaLevel, latitude = d.geo and d.geo[4], geo = d.geo, nature = d.nature, look = d.look, realStyle = true,
  cellSize = d.cellSize, farStep = 100, adaptiveFar = true, turf = true, woodFloor = true, aridLawn = true, vergeSheet = true}
for k, v in pairs(extra or {}) do options[k] = v end
local road, scene, _, _, grass = generator.build(list, i, j, options)
local x0, y0 = i * 500, j * 500
local floor, min, max = math.floor, math.min, math.max
-- the asphalt's triangles by 2 m bin
local BIN = 2
local bins = {}
local function binOf(x, y) return (floor(x / BIN) + 32768) * 65536 + floor(y / BIN) + 32768 end
local function put(t)
  for bx = floor(min(t[1], t[4], t[7]) / BIN), floor(max(t[1], t[4], t[7]) / BIN) do
    for by = floor(min(t[2], t[5], t[8]) / BIN), floor(max(t[2], t[5], t[8]) / BIN) do
      local k = (bx + 32768) * 65536 + by + 32768
      local b = bins[k]
      if not b then b = {}; bins[k] = b end
      b[#b + 1] = t
    end
  end
end
local function zIn(t, x, y)
  local ax, ay, az, bx, by, bz, cx, cy, cz = t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], t[9]
  local den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
  if den > -1e-9 and den < 1e-9 then return nil end
  local u = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / den
  local v = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / den
  if u < -1e-6 or v < -1e-6 or u + v > 1 + 1e-6 then return nil end
  return u * az + v * bz + (1 - u - v) * cz
end
-- the top asphalt under (x, y), or nil
local function asphalt(x, y)
  local best
  for _, t in ipairs(bins[binOf(x, y)] or {}) do
    local z = zIn(t, x, y)
    if z and (not best or z > best) then best = z end
  end
  return best
end
local function eachTri(item, fn)
  local ox, oy, oz = item.pos[1], item.pos[2], item.pos[3] or 0
  for _, mesh in ipairs(item.meshes or {}) do
    local v, f = mesh.verts, mesh.faces
    local name = mesh.material or ''
    for t = 1, #f - 2, 3 do
      local a, b, c = v[f[t].v + 1], v[f[t + 1].v + 1], v[f[t + 2].v + 1]
      fn(name, mesh, a.x + ox, a.y + oy, a.z + oz, b.x + ox, b.y + oy, b.z + oz, c.x + ox, c.y + oy, c.z + oz)
    end
  end
end
local asphaltTris = 0
for _, it in ipairs(road and road.items or {}) do
  if it.kind == 'proc' and not it.proxy then
    eachTri(it, function(name, mesh, ax, ay, az, bx, by, bz, cx, cy, cz)
      if name:sub(1, 9) == 'e2rf_road' then
        put({ax, ay, az, bx, by, bz, cx, cy, cz}); asphaltTris = asphaltTris + 1
      end
    end)
  end
end
-- hits: kind -> key -> {count, x, y, rise}; one count per 0.25 m cell of asphalt
local hits, cells = {}, {}
local STEP, LOW, HIGH = .25, .06, 1.6
local function hit(kind, key, x, y, rise)
  if x < x0 or x >= x0 + 500 or y < y0 or y >= y0 + 500 then return end
  local c = kind .. ':' .. floor(x / STEP) .. ':' .. floor(y / STEP)
  if cells[c] then return end
  cells[c] = true
  local byKind = hits[kind]
  if not byKind then byKind = {}; hits[kind] = byKind end
  local h = byKind[key]
  if not h then h = {n = 0, places = {}}; byKind[key] = h end
  h.n = h.n + 1
  -- places 8 m apart, the highest rise first kept
  local pk = floor(x / 8) .. ':' .. floor(y / 8)
  local p = h.places[pk]
  if not p or rise > p[3] then h.places[pk] = {x, y, rise} end
end
-- every collision triangle of a layer, sampled every STEP over its face
local function sampleTri(kind, key, ax, ay, az, bx, by, bz, cx, cy, cz)
  local l1 = math.sqrt((bx - ax) ^ 2 + (by - ay) ^ 2 + (bz - az) ^ 2)
  local l2 = math.sqrt((cx - ax) ^ 2 + (cy - ay) ^ 2 + (cz - az) ^ 2)
  local n1, n2 = max(1, math.ceil(l1 / STEP)), max(1, math.ceil(l2 / STEP))
  for s = 0, n1 do
    local u = s / n1
    for t = 0, n2 - s * n2 / n1 do
      local w = t / n2
      if u + w <= 1 + 1e-9 then
        local x = ax + (bx - ax) * u + (cx - ax) * w
        local y = ay + (by - ay) * u + (cy - ay) * w
        local z = az + (bz - az) * u + (cz - az) * w
        local zr = asphalt(x, y)
        if zr and z > zr + LOW and z < zr + HIGH then hit(kind, key, x, y, z - zr) end
      end
    end
  end
end
local statics, collidable, kinds = 0, 0, {}
local layers = {{'road', road}, {'scene', scene}}
for _, pair in ipairs(layers) do
  local layer, m = pair[1], pair[2]
  for _, it in ipairs(m and m.items or {}) do
    local kk = layer .. ':' .. tostring(it.kind) .. (it.prop and ':prop' or '') .. (it.shape and ':shape' or '') .. (it.pos and ':pos' or '')
    kinds[kk] = (kinds[kk] or 0) + 1
    if it.kind == 'proc' then
      local kind
      if it.proxy then kind = 'proxy'
      elseif it.forceCollision or not collision.quiet(it.meshes, it.layer or layer) then kind = 'solid' end
      if kind then
        eachTri(it, function(name, mesh, ...)
          if name:sub(1, 9) ~= 'e2rf_road' and not (kind == 'solid' and mesh.quiet) then sampleTri(kind, name, ...) end
        end)
      end
    elseif (it.kind == nil or it.kind == 'static') and type(it.pos) == 'table' and it.shape then
      -- an object: a prop is a collidable Forest kind unless it can be knocked down; a crown never collides
      local shape = it.shape
      local veg = shape:find('/trees/', 1, true) or shape:find('flora', 1, true) or shape:find('/vegetation/', 1, true)
        or shape:find('grass', 1, true) or shape:find('bush', 1, true) or shape:find('shrub', 1, true)
      local collides
      if it.prop then collides = not (knock and knock(shape))
      elseif veg then collides = false
      else collides = (it.collision or 'Collision Mesh') ~= 'None' end
      statics = statics + 1
      if collides then
        collidable = collidable + 1
        local x, y, z = it.pos[1], it.pos[2], it.pos[3] or 0
        local zr = asphalt(x, y)
        local name = shape:match('([^/]+)$') or shape
        if zr and z > zr - 1 and z < zr + HIGH then hit('static', name, x, y, max(0, z - zr))
        elseif not zr then
          -- standing beside the asphalt, within the reach of a prop's body (0.8 m)
          for a = 0, 7 do
            local qx, qy = x + .8 * math.cos(a * math.pi / 4), y + .8 * math.sin(a * math.pi / 4)
            local zq = asphalt(qx, qy)
            if zq and z > zq - 1 and z < zq + HIGH then hit('static at the edge', name, x, y, max(0, z - zq)); break end
          end
        end
      end
    end
  end
end
-- the engine's grass: the hidden block's squares (turf.lua gather), corners on the square's own plane
local SQ, SINK = turf.SQUARE, turf.SINK
local squares, over = 0, 0
for _, m in ipairs({scene, grass}) do
  for _, it in ipairs(m and m.items or {}) do
    local patch = it.grassPatch
    if patch then
      local s = patch.samples
      for k = 1, #s, 4 do
        local slot = s[k] % 16
        local z, gx, gy = s[k + 1] - SINK, s[k + 2], s[k + 3]
        local cx = patch.x + (slot % 4) * SQ + 1
        local cy = patch.y + floor(slot / 4) * SQ + 1
        squares = squares + 1
        local worst
        for _, q in ipairs({{0, 0}, {-.95, -.95}, {.95, -.95}, {-.95, .95}, {.95, .95}, {0, -.95}, {0, .95}, {-.95, 0}, {.95, 0}}) do
          local x, y = cx + q[1], cy + q[2]
          local zr = asphalt(x, y)
          if zr then
            local h = z + gx * q[1] + gy * q[2]
            if h > zr + .03 and (not worst or h - zr > worst[3]) then worst = {x, y, h - zr} end
          end
        end
        if worst then
          over = over + 1
          local key = (s[k] - slot) >= 2048 and 'verge square' or 'lawn square'
          hit('turf', key, worst[1], worst[2], worst[3])
        end
      end
    end
  end
end
local out = {asphaltTris = asphaltTris, squares = squares, over = over, kinds = {}, statics = statics, collidable = collidable, itemKinds = kinds}
for kind, byKey in pairs(hits) do
  local rows = {}
  for key, h in pairs(byKey) do
    local places = {}
    for _, p in pairs(h.places) do places[#places + 1] = p end
    table.sort(places, function(a, b) return a[3] > b[3] end)
    rows[#rows + 1] = {key = key, n = h.n, places = places}
  end
  table.sort(rows, function(a, b) return a.n > b.n end)
  out.kinds[kind] = rows
end
return out
'''


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', required=True)
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--around', type=int, default=0, help='also the tiles this many steps round it')
    p.add_argument('--quality', type=int, default=100, help="the game's quality preset the tile is built with")
    p.add_argument('--option', action='append', default=[], help='name=value for the generator (true, false or a number)')
    p.add_argument('--list', type=int, default=6, help='places listed per kind and material')
    p.add_argument('--find', help='print the roads whose name has this text (and their middles) and stop')
    a = p.parse_args()
    lua, mods, _ = bench_native.runtime(a.pack, game_structs=True, kit=True, houses=True)
    lua.execute('jit.opt.start(' + ', '.join(repr(v) for v in VM_JIT.split(',')) + ')')
    lua.execute("mods.ffi, mods.bit = package.loaded.ffi, bit")
    native = mods['native']
    native.refresh()
    job = native.land(lua.table_from({'lat': a.lat, 'lon': a.lon, 'seq': 1}))
    if job['state'] == 'error':
        raise SystemExit(job['message'])
    x, y = native.localPoint(a.lat, a.lon)
    cells = lua.eval('function(src) return assert(load(src, "@clear_cells")) end')(CELLS)
    if a.find:
        find = lua.eval('function(src) return assert(load(src, "@clear_find")) end')(FIND)
        seen = set()
        for dj in range(-1, 2):
            for di in range(-1, 2):
                i, j = int(x // 500) + di, int(y // 500) + dj
                lst, _ = cells(native, i, j)
                for row in find(lst, a.find).values():
                    name, hw, px, py = list(row.values())
                    if (name, round(px), round(py)) in seen:
                        continue
                    seen.add((name, round(px), round(py)))
                    lat, lon = to_geo(native, px, py, a.lat, a.lon, x, y)
                    print(f'{name} ({hw}): {lat:.6f}, {lon:.6f}')
        return 0
    tune = mods['quality'].preset(a.quality)
    extra = {name: tune[name] for name in ('maxTrees', 'maxFarTrees', 'maxGrass', 'maxRocks', 'forestSpacing', 'groundSpacing',
                                           'groundTrees', 'parkedCars', 'propSpacing', 'detail')}
    for item in a.option:
        name, _, value = item.partition('=')
        extra[name] = True if value == 'true' else False if value == 'false' else float(value)
    build = lua.eval('function(src) return assert(load(src, "@clear_census")) end')(BUILD)
    collision = lua.eval('function(source) return assert(load(source, "@collision.lua"))() end')(
        (ROOT / 'mod/lua/ge/extensions/e2r/collision.lua').read_text(encoding='utf8'))
    # knock.lua's kinds (a knockable prop has no static collision) and turf.lua's block
    lua_dir = ROOT / 'mod/lua/ge/extensions/e2r'
    knock = lua.eval('function(source) local ok, m = pcall(function() return assert(load(source, "@knock.lua"))() end);'
                     ' return ok and m or nil end')((lua_dir / 'knock.lua').read_text(encoding='utf8'))
    knock_of = lua.eval('function(k) return k and k.kindOf and function(s) return k.kindOf(s) ~= nil end or nil end')(knock)
    text = (lua_dir / 'turf.lua').read_text(encoding='utf8')
    square = float(re.search(r'^M\.SQUARE = ([\d.]+)', text, re.M).group(1))
    sink = float(re.search(r'^M\.SINK = ([\d.]+)', text, re.M).group(1))
    turf = lua.table_from({'SQUARE': square, 'SINK': sink})
    total = defaultdict(lambda: defaultdict(int))
    worst = defaultdict(list)
    for dj in range(a.around, -a.around - 1, -1):
        for di in range(-a.around, a.around + 1):
            i, j = int(x // 500) + di, int(y // 500) + dj
            lst, d = cells(native, i, j)
            r = build(mods['generator'], lst, d, i, j, lua.table_from(extra), collision, knock_of, turf)
            parts = []
            for kind, rows in (r['kinds'] or {}).items():
                n = 0
                for row in rows.values():
                    n += row['n']
                    total[kind][row['key']] += row['n']
                    for place in row['places'].values():
                        worst[(kind, row['key'])].append(tuple(place.values()))
                parts.append(f'{kind} {n * 0.0625:.1f} m2')
            if a.list > 50: print(dict(r['itemKinds']))
            print(f"{i}_{j}: asphalt {r['asphaltTris']} triangles; objects {r['statics']} ({r['collidable']} collide); lawn squares {r['squares']}, over the asphalt {r['over']};"
                  f" over the asphalt: {', '.join(parts) or 'nothing'}")
    print('\nover the asphalt, 6 cm to 1.6 m, by kind and material (m2 of asphalt; places with the rise, m):')
    for kind in ('proxy', 'turf', 'static', 'static at the edge', 'solid'):
        rows = total.get(kind)
        if not rows:
            continue
        print(f'  {kind}:')
        for key, n in sorted(rows.items(), key=lambda kv: -kv[1]):
            places = sorted(worst[(kind, key)], key=lambda q: -q[2])[:a.list]
            where = '; '.join('%.6f, %.6f +%.2f' % (*to_geo(native, px, py, a.lat, a.lon, x, y), rise) for px, py, rise in places)
            print(f'    {key:28s} {n * 0.0625:8.1f}   {where}')
    return 0


def to_geo(native, px, py, lat0, lon0, x0, y0):
    """lat, lon of a local point, by the local metre scale round the landing point."""
    import math
    # two probes give the local affine; the pack's projection is near-linear over a few km
    xa, ya = native.localPoint(lat0 + 0.001, lon0)
    xb, yb = native.localPoint(lat0, lon0 + 0.001)
    # solve [xa-x0 xb-x0; ya-y0 yb-y0] [dlat dlon]' * 1000 = [px-x0, py-y0]
    m11, m12, m21, m22 = xa - x0, xb - x0, ya - y0, yb - y0
    det = m11 * m22 - m12 * m21
    dx, dy = px - x0, py - y0
    dlat = (dx * m22 - dy * m12) / det * 0.001
    dlon = (m11 * dy - m21 * dx) / det * 0.001
    if not math.isfinite(dlat):
        return lat0, lon0
    return lat0 + dlat, lon0 + dlon


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    sys.exit(main())
