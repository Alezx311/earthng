"""Count ProceduralMesh objects and (object, material) pairs the generator makes per tile.

    python earthng/mesh_pairs.py --pack <earthng_ukraine.zip> --lat 50.4475 --lon 30.5225 [--radius 1] [--far] [--materials]

Each new (object, material) pair costs the engine ~2.3 ms the first frame it is drawn
(night-probe-10), so this count is a streaming cost, like triangles are.
"""
import argparse
import json

import bench_native

COUNT = '''
local native, generator, i0, j0, radius, far = ...
local function upvalue(f, name)
  for k = 1, 200 do local n, v = debug.getupvalue(f, k); if not n then return end; if n == name then return v end end
end
local active = upvalue(native.update, 'active')
local d = active.region.data
local loadCell = upvalue(upvalue(native.update, 'buildTile'), 'loadCell')
local function cellOf(i, j, keep)
  local co = coroutine.create(function() return loadCell(string.format('%d_%d', i, j), i, j, keep) end)
  while true do
    local ok, cell = coroutine.resume(co)
    if not ok then error(cell) end
    if coroutine.status(co) == 'dead' then return cell end
  end
end
local out = {}
for di = -radius, radius do for dj = -radius, radius do
  local i, j = i0 + di, j0 + dj
  local list = {}
  for ci = math.floor((i * 500 - 40) / d.cellSize), math.floor((i * 500 + 540) / d.cellSize) do
    for cj = math.floor((j * 500 - 40) / d.cellSize), math.floor((j * 500 + 540) / d.cellSize) do
      local c = cellOf(ci, cj, {i * 500, j * 500, (i + 1) * 500, (j + 1) * 500})
      if c then list[#list + 1] = c end
    end
  end
  local t = clock()
  local road, scene, farM = generator.build(list, i, j, {tileSize = 500, far = far, pause = function() end, seaLevel = d.seaLevel,
    latitude = d.geo and d.geo[4], nature = d.nature, look = d.look})
  local ms = (clock() - t) * 1000
  local row = {key = i .. '_' .. j, ms = ms}
  for name, m in pairs({road = road, scene = scene, far = farM}) do
    local objects, npairs, tris, mats = 0, 0, 0, {}
    for _, it in ipairs(m and m.items or {}) do
      if it.kind == 'proc' then
        objects = objects + 1
        npairs = npairs + #it.meshes
        for _, mesh in ipairs(it.meshes) do
          tris = tris + #mesh.faces / 3
          mats[mesh.material] = (mats[mesh.material] or 0) + #mesh.faces / 3
        end
      end
    end
    local nm = 0
    for _ in pairs(mats) do nm = nm + 1 end
    row[name] = {objects = objects, pairs = npairs, tris = tris, materials = nm, byMaterial = mats}
  end
  out[#out + 1] = row
end end
return out
'''


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', required=True)
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--radius', type=int, default=1)
    p.add_argument('--far', action='store_true')
    p.add_argument('--materials', action='store_true', help='also sum triangles per material over all tiles')
    a = p.parse_args()
    lua, mods, _ = bench_native.runtime(a.pack)
    native = mods['native']
    native.refresh()
    job = native.land(lua.table_from({'lat': a.lat, 'lon': a.lon, 'seq': 1}))
    if job['state'] == 'error':
        raise SystemExit(job['message'])
    x, y = native.localPoint(a.lat, a.lon)
    res = lua.execute(COUNT, native, mods['generator'], int(x // 500), int(y // 500), a.radius, a.far)
    total, byMaterial = {}, {}
    for row in res.values():
        line = [row['key'], f"{row['ms']:.0f} ms"]
        for name in ('road', 'scene', 'far'):
            r = row[name]
            if r is None or not r['objects']:
                continue
            line.append(f"{name}: {r['objects']} obj {r['pairs']} pairs {int(r['tris'])} tris {r['materials']} mats")
            t = total.setdefault(name, [0, 0, 0])
            t[0] += r['objects']; t[1] += r['pairs']; t[2] += int(r['tris'])
            for mat, n in (r['byMaterial'] or {}).items():
                byMaterial[(name, mat)] = byMaterial.get((name, mat), 0) + n
        print(' | '.join(line))
    print(json.dumps(total))
    if a.materials:
        for (name, mat), n in sorted(byMaterial.items(), key=lambda kv: -kv[1]):
            print(f'{name:6} {mat:32} {int(n):8}')


if __name__ == '__main__':
    main()
