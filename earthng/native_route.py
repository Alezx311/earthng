"""A drivable route straight from a native country pack, for test_world.py --route.

    python earthng/native_route.py --pack <earthng_ukraine.zip> --lat 48.45306 --lon 24.55611 --km 6 --out out/routes/yaremche.json

Decodes the road graph round the point (road ends share node ids), starts on the nearest
major road and keeps driving: at each node the continuation of the same or a bigger road with
the smallest turn, never a road twice. Writes {"geo": [[lat, lon], ...]} with every road point,
which the native test projects into the landing's frame.
"""
import argparse
import json
import math
from pathlib import Path

import bench_native

RANK = {'motorway': 6, 'trunk': 5, 'primary': 4, 'secondary': 3, 'tertiary': 2, 'unclassified': 1, 'residential': 1}

ROADS = '''
local native, radius = ...
local function upvalue(f, name)
  for k = 1, 200 do local n, v = debug.getupvalue(f, k); if not n then return end; if n == name then return v end end
end
local active = upvalue(native.update, 'active')
local r, d = active.region, active.region.data
local loadCell = upvalue(upvalue(native.update, 'buildTile'), 'loadCell')
local hasCell = upvalue(loadCell, 'hasCell')
local x0, y0 = active.landing.x, active.landing.y
local s = d.cellSize
local out, seen = {}, {}
for i = math.floor((x0 - radius) / s), math.floor((x0 + radius) / s) do
  for j = math.floor((y0 - radius) / s), math.floor((y0 + radius) / s) do
    if hasCell(r, i, j) then
      local co = coroutine.create(function() return loadCell(string.format('%d_%d', i, j), i, j, {i * s, j * s, (i + 1) * s, (j + 1) * s}) end)
      local cell
      while true do
        local ok, v = coroutine.resume(co)
        if not ok then error(v) end
        if coroutine.status(co) == 'dead' then cell = v; break end
      end
      for _, road in ipairs(cell.roads or {}) do
        local hw = road.tags and road.tags.highway
        if road.points and hw and not seen[road.id] and #road.nodes >= 2 then
          seen[road.id] = true
          local pts = {}
          for k, p in ipairs(road.points) do
            local lon, lat = r.projection.geographic(p[1], p[2])
            pts[k] = {p[1], p[2], lat, lon}
          end
          out[#out + 1] = {id = road.id, highway = hw, a = road.nodes[1], b = road.nodes[#road.nodes], pts = pts,
            bridge = road.tags.bridge, tunnel = road.tags.tunnel}
        end
      end
    end
  end
end
return {roads = out, x = x0, y = y0}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', required=True)
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--km', type=float, default=6)
    p.add_argument('--radius', type=float, default=5000)
    p.add_argument('--min-rank', type=int, default=1)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    lua, mods, _ = bench_native.runtime(a.pack)
    native = mods['native']
    native.refresh()
    job = native.land(lua.table_from({'lat': a.lat, 'lon': a.lon, 'seq': 1}))
    if job['state'] == 'error':
        raise SystemExit(job['message'])
    res = lua.execute(ROADS, native, a.radius)
    roads = []
    for road in res['roads'].values():
        pts = [tuple(p.values()) for p in road['pts'].values()]
        rank = RANK.get(str(road['highway']).replace('_link', ''), 0)
        if rank >= a.min_rank and len(pts) >= 2:
            roads.append({'id': road['id'], 'rank': rank, 'a': road['a'], 'b': road['b'], 'pts': pts})
    print(len(roads), 'roads')
    by_node = {}
    for road in roads:
        by_node.setdefault(road['a'], []).append((road, False))
        by_node.setdefault(road['b'], []).append((road, True))
    x0, y0 = res['x'], res['y']

    def dist2(p):
        return (p[0] - x0) ** 2 + (p[1] - y0) ** 2
    start = min(roads, key=lambda r: min(dist2(p) for p in r['pts']) - r['rank'] * 400 ** 2)
    route, used, length = [], set(), 0.0
    road, backwards = start, False
    while road and length < a.km * 1000:
        used.add(road['id'])
        pts = road['pts'][::-1] if backwards else road['pts']
        for q in pts if not route else pts[1:]:
            if route:
                length += math.dist(route[-1][:2], q[:2])
            route.append(q)
        node = road['a'] if backwards else road['b']
        back = next((q for q in reversed(route) if math.dist(q[:2], route[-1][:2]) > 5), route[0])
        heading = math.atan2(route[-1][1] - back[1], route[-1][0] - back[0])
        best = None
        for nxt, rev in by_node.get(node, []):
            if nxt['id'] in used:
                continue
            npts = nxt['pts'][::-1] if rev else nxt['pts']
            ahead = next((q for q in npts if math.dist(q[:2], npts[0][:2]) > 5), npts[-1])
            h2 = math.atan2(ahead[1] - npts[0][1], ahead[0] - npts[0][0])
            turn = abs((h2 - heading + math.pi) % (2 * math.pi) - math.pi)
            score = turn - 0.35 * min(nxt['rank'], road['rank'] + 1)
            if turn < 2.2 and (best is None or score < best[0]):
                best = (score, nxt, rev)
        if not best:
            print('stop at node', node, 'candidates', [(n['id'], n['rank'], n['id'] in used) for n, _ in by_node.get(node, [])])
            break
        _, road, backwards = best
    print(f'{length / 1000:.2f} km, {len(route)} points')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({'geo': [[round(q[2], 6), round(q[3], 6)] for q in route]}), encoding='utf8')


if __name__ == '__main__':
    main()
