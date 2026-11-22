"""How near the roads the lawn comes: a tile's lawn squares by their distance from the nearest
carriageway's edge, outside the game (LuaJIT under lupa, a real country ZIP).

    .venv/Scripts/python.exe earthng/verge_census.py --pack <earthng_kyiv-oblast.zip> --lat 50.3590 --lon 30.4030
        [--turf] [--lua-dir <copy of mod/lua/ge/extensions/e2r>] [--png out/verge/hatne.png]

The landing's own tile is built whole (its grass inside the scene). Every 2 m lawn square is
measured to the nearest road of the tile's navgraph (centre line, less its half width): the
table is the share of the land in each half-metre band beside the roads that has a lawn square
on it, and the height of the square's inner corners under its centre (a square that leans down
to the road, generator.lua VEG.roadside). --turf builds as the game does with the engine's
grass on (turf.lua active): the wood's floor, the dry lands' cover and the lawn up to the road.
"""
import argparse
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import bench_native  # noqa: E402

READ = '''
local native = ...
local st = native.status()
local key = native.tileAt()
local road, scene = native.manifest(key, 'road'), native.manifest(key, 'scene')
local squares, roads = {}, {}
for _, item in ipairs(scene.items or {}) do
  local p = item.grassPatch
  if p then
    for k = 1, #p.samples, 4 do
      local value = p.samples[k]
      local slot = value % 16
      squares[#squares + 1] = {p.x + (slot % 4) * 2 + 1, p.y + math.floor(slot / 4) * 2 + 1, p.samples[k + 1],
        p.samples[k + 2], p.samples[k + 3], value - slot}
    end
  end
end
for _, s in ipairs(road.navSegments or {}) do
  local pts = {}
  for k = 8, #s - 2, 3 do pts[#pts + 1] = {s[k], s[k + 1], s[k + 2]} end
  roads[#roads + 1] = {radius = s[6], drive = s[7], pts = pts}
end
local size = st.stream.tile
local i, j = key:match('^(-?%d+)_(-?%d+)$')
return {squares = squares, roads = roads, rect = {i * size, j * size, (i + 1) * size, (j + 1) * size}, key = key}
'''


def to_py(v):
    if hasattr(v, 'items'):
        keys = list(v.keys())
        if keys and all(isinstance(k, int) for k in keys):
            return [to_py(v[k]) for k in sorted(keys)]
        return {k: to_py(x) for k, x in v.items()}
    return v


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--turf', action='store_true', help="build as with the engine's grass on")
    p.add_argument('--quality', type=int, default=100)
    p.add_argument('--lua-dir', type=Path)
    p.add_argument('--png', type=Path, help='a map of the tile: roads, lawn squares, the bare band')
    a = p.parse_args()
    if a.lua_dir:
        bench_native.LUA = a.lua_dir
    lua, mods, _ = bench_native.runtime(a.pack)
    if a.turf:
        lua.execute("package.loaded['ge/extensions/e2r/turf'] = {active = function() return true end}")
    native = mods['native']
    native.refresh()
    native.setTune(mods['quality'].preset(a.quality))
    job = native.land(lua.table_from({'seq': 1, 'lat': a.lat, 'lon': a.lon}))
    if job.state == 'error':
        sys.exit(job.message)
    collect = lua.eval("function() collectgarbage('collect') end")
    for k in range(20000):
        native.update(.026, 150)
        if k % 4 == 0:
            collect()
        if native.status().job.state in ('ready', 'error'):
            break
    if native.status().job.state != 'ready':
        sys.exit('landing never became ready: ' + str(native.status().job.message))
    data = to_py(lua.execute(READ, native))
    rect, squares, roads = data['rect'], data['squares'], data['roads']
    segs = []
    for r in roads:
        pts = r['pts']
        for a_, b_ in zip(pts, pts[1:]):
            segs.append((a_[0], a_[1], b_[0], b_[1], r['radius'] or 3, a_[2], b_[2]))

    def edge(x, y):
        best, z = 1e9, 0.
        for ax, ay, bx, by, radius, az, bz in segs:
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            t = max(0., min(1., ((x - ax) * dx + (y - ay) * dy) / l2)) if l2 > 1e-9 else 0.
            d = math.hypot(x - ax - t * dx, y - ay - t * dy) - radius
            if d < best:
                best, z = d, az + (bz - az) * t
        return best, z
    # the land in each band: every 2 m square centre of the tile on the lawn's own lattice
    bands, lawn, lean, under = {}, {}, {}, {}
    have = {(round(s[0]), round(s[1])): s for s in squares}
    x = rect[0] + 1
    while x < rect[2]:
        y = rect[1] + 1
        while y < rect[3]:
            d, road_z = edge(x, y)
            if 0 <= d < 8:
                b = int(d * 2)
                bands[b] = bands.get(b, 0) + 1
                s = have.get((round(x), round(y)))
                if s:
                    lawn[b] = lawn.get(b, 0) + 1
                    lean.setdefault(b, []).append(abs(s[3]) + abs(s[4]))
                    under.setdefault(b, []).append(road_z - s[2])
            y += 2
        x += 2
    print(f"tile {data['key']}: {len(squares)} lawn squares, {len(segs)} road pieces")
    print('  m from the road   land squares   with lawn   share   mean lean   lawn under the road, m: mean, 90 %')
    for b in sorted(bands):
        n, got = bands[b], lawn.get(b, 0)
        l = lean.get(b) or [0]
        u = sorted(under.get(b) or [0])
        print(f"  {b / 2:4.1f}-{b / 2 + .5:<4.1f}        {n:6d}        {got:6d}     {got / n:5.0%}   {sum(l) / len(l):.2f}"
              f"        {sum(u) / len(u):5.2f}  {u[int(len(u) * .9)]:5.2f}")
    if a.png:
        from PIL import Image, ImageDraw
        scale = 4
        w = int((rect[2] - rect[0]) * scale)
        im = Image.new('RGB', (w, w), (58, 52, 44))
        dr = ImageDraw.Draw(im)

        def px(x, y):
            return (x - rect[0]) * scale, (rect[3] - y) * scale
        for s in squares:
            x0, y0 = px(s[0] - 1, s[1] + 1)
            dr.rectangle([x0, y0, x0 + 2 * scale - 1, y0 + 2 * scale - 1], fill=(70, 140, 60) if s[5] < 512 else (40, 90, 50))
        for ax, ay, bx, by, radius, _, _ in segs:
            dr.line([px(ax, ay), px(bx, by)], fill=(150, 150, 155), width=max(1, int(radius * 2 * scale)))
        a.png.parent.mkdir(parents=True, exist_ok=True)
        im.save(a.png)
        print('map:', a.png)
    sys.stdout.flush()
    import os
    os._exit(0)


if __name__ == '__main__':
    main()
