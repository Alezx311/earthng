"""Time the game's router (mod routing.lua) on built routing files, outside the game.

    .venv/Scripts/python.exe earthng/bench_routing.py PACK.zip out/routing/ukraine-kyiv/earthng/countries/ukraine/routing/*.bin \
        --route 50.4501,30.5234,50.3450,30.8947 --route ...

The region frames come from the pack's manifests (their `geo` affine). LuaJIT here is lupa's,
not the game's, so the numbers are a guide: the game also pays its own frame around them.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import zipfile

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'earthng'))
from build_routing import regions_of  # noqa: E402


def local(geo, lat, lon):
    dx, dy = lon - geo[2], lat - geo[3]
    det = geo[4] * geo[7] - geo[5] * geo[6]
    return geo[0] + (dx * geo[7] - dy * geo[5]) / det, geo[1] + (dy * geo[4] - dx * geo[6]) / det


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('pack')
    parser.add_argument('files', nargs='+')
    parser.add_argument('--route', action='append', default=[], help='lat,lon,lat,lon')
    args = parser.parse_args(argv)
    with zipfile.ZipFile(args.pack) as archive:
        prefixes = regions_of(archive)
        geos = {Path(f).stem: json.loads(archive.read(prefixes[Path(f).stem] + 'manifest.json'))['geo'] for f in args.files}
    first = geos[Path(args.files[0]).stem]
    lua = LuaRuntime()
    lua.globals().routing = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/routing.lua').read_text(encoding='utf8'))
    lua.execute('clock = os.clock')
    regions = []
    for f in args.files:
        geo = geos[Path(f).stem]
        lua.globals().blob = Path(f).read_bytes()
        # region-local -> the first region's frame through lon/lat (the game does this with the
        # landing's frame); the same region is the identity
        lua.globals().g1 = lua.table_from(geo)
        lua.globals().g0 = lua.table_from(first)
        t = time.perf_counter()
        lua.execute('''
          local a, b = g1, g0
          local det = b[5] * b[8] - b[6] * b[7]
          region = routing.decode(blob, function(x, y)
            local dx, dy = x - a[1], y - a[2]
            local lon, lat = a[3] + a[5] * dx + a[6] * dy, a[4] + a[7] * dx + a[8] * dy
            local ex, ey = lon - b[3], lat - b[4]
            return b[1] + (ex * b[8] - ey * b[6]) / det, b[2] + (ey * b[5] - ex * b[7]) / det
          end)''')
        regions.append(lua.globals().region)
        print(f'decode {Path(f).name}: {1000 * (time.perf_counter() - t):.0f} ms, '
              f'{lua.eval("region.n")} nodes, {lua.eval("region.e")} edges, {Path(f).stat().st_size / 1e6:.2f} MB')
    lua.globals().list = lua.table_from(regions)
    t = time.perf_counter()
    lua.execute('graph = routing.graph(list)')
    print(f'graph: {1000 * (time.perf_counter() - t):.0f} ms, {lua.eval("graph.n")} nodes, {lua.eval("graph.arcs")} arcs')
    arcs, nodes = lua.eval('graph.arcs'), lua.eval('graph.n')
    print(f'ffi memory: ~{(arcs * (4 + 4 + 4 + 4 + 2 + 4 + 1) + nodes * (8 * 3 + 4 * 3 + 8 + 4 + 1)) / 1e6:.1f} MB')
    for spec in args.route:
        la, oa, lb, ob = map(float, spec.split(','))
        ax, ay = local(first, la, oa)
        bx, by = local(first, lb, ob)
        lua.globals().ax, lua.globals().ay, lua.globals().bx, lua.globals().by = ax, ay, bx, by
        t = time.perf_counter()
        lua.execute('''
          local c = clock()
          from, gap1 = routing.nearest(graph, ax, ay)
          to, gap2 = routing.nearest(graph, bx, by)
          snapMs = 1000 * (clock() - c); c = clock()
          time_, expanded = routing.search(graph, from, to)
          searchMs = 1000 * (clock() - c); c = clock()
          route = time_ and routing.route(graph, from, to, 'uk')
          routeMs = 1000 * (clock() - c)''')
        g = lua.globals()
        if not g.route:
            print(f'{spec}: no route ({g.expanded} expanded)')
            continue
        r = g.route
        print(f'{spec}: {r.length / 1000:.1f} km, {r.time / 60:.0f} min, {g.expanded} expanded, '
              f'snap {g.snapMs:.0f} ms (gaps {g.gap1:.0f}/{g.gap2:.0f} m), search {g.searchMs:.0f} ms, '
              f'route+steps {g.routeMs:.0f} ms (route() searches again), {len(r.steps)} steps, {len(r.points) // 2} points')
        for k in range(1, min(8, len(r.steps)) + 1):
            s = r.steps[k]
            print(f'   {s.at:7.0f} m  {s.turn:+5.0f}°  {s.name or ""} {s.ref or ""}')


if __name__ == '__main__':
    main()
