"""Routing graph (routing_format.py) and the game's router (mod routing.lua) on the same bytes.

Run with: python -m unittest discover -s earthng -p test_routing.py
A routing file from build_routing.py in out/routing (if any) is also checked against Dijkstra.
"""
import heapq
import math
from pathlib import Path
import random
import sys
import unittest

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'earthng'))
import routing_format as rf  # noqa: E402

SRC = (ROOT / 'mod/lua/ge/extensions/e2r/routing.lua').read_text(encoding='utf8')


def road(rid, a, b, points, **tags):
    tags.setdefault('highway', 'residential')
    return {'id': str(rid), 'nodes': [str(a), str(b)], 'points': [[x, y, 0] for x, y in points], 'tags': tags}


def grid(size=6, step=100.0):
    """A size x size street grid; node id = 1000 + i + j * size. Row 2 is one-way eastwards,
    column 3 a primary road with a 90 km/h limit."""
    roads, rid = [], 1
    nid = lambda i, j: 1000 + i + j * size
    for j in range(size):
        for i in range(size - 1):
            tags = {'oneway': 'yes', 'name': 'One Way'} if j == 2 else {'name': f'Row {j}'}
            roads.append(road(rid, nid(i, j), nid(i + 1, j), [(i * step, j * step), ((i + 1) * step, j * step)], **tags))
            rid += 1
    for i in range(size):
        for j in range(size - 1):
            tags = {'highway': 'primary', 'maxspeed': '90', 'name': 'Avenue'} if i == 3 else {'name': f'Col {i}'}
            pts = [(i * step, j * step), (i * step + 8, (j + .5) * step), (i * step, (j + 1) * step)]
            roads.append(road(rid, nid(i, j), nid(i, j + 1), pts, **tags))
            rid += 1
    return roads


def dijkstra(decoded, source, target):
    """Travel time over the decoded file with routing.lua's costs."""
    adj = {}
    for e in decoded['edges']:
        cls = e['flags'] & 7
        speed = (e['speed'] or rf.SPEED[rf.CLASSES[cls]]) / 3.6
        cost = e['length'] / speed
        adj.setdefault(e['a'], []).append((e['b'], cost))
        if not e['flags'] & rf.ONEWAY:
            adj.setdefault(e['b'], []).append((e['a'], cost))
    best, queue = {source: 0.}, [(0., source)]
    while queue:
        d, n = heapq.heappop(queue)
        if n == target:
            return d
        if d > best.get(n, math.inf):
            continue
        for m, c in adj.get(n, ()):
            if d + c < best.get(m, math.inf):
                best[m] = d + c
                heapq.heappush(queue, (d + c, m))
    return None


class FormatTests(unittest.TestCase):
    def test_round_trip_keeps_topology_names_and_one_way_direction(self):
        roads = grid() + [road(900, 1, 2, [(0, 0), (5, 0)], highway='service'),            # not in the navgraph
                          road(901, 3, 4, [(0, 0), (5, 0)], access='private'),
                          road(902, 1005, 1011, [(500, 0), (500, 100)], oneway='-1', name='Back')]
        g = rf.graph(roads + grid())                   # the same features again, as in a neighbour cell
        decoded = rf.decode(rf.encode(g))
        self.assertEqual(len(decoded['nodes']), 36)
        self.assertEqual(len(decoded['edges']), 61)
        ids = [n[0] for n in decoded['nodes']]
        self.assertEqual(ids, sorted(ids))
        back = [e for e in decoded['edges'] if e['name'] == 'Back'][0]
        self.assertEqual((ids[back['a']], ids[back['b']]), (1011, 1005))     # oneway=-1 runs b -> a
        self.assertTrue(back['flags'] & rf.ONEWAY)
        avenue = [e for e in decoded['edges'] if e['name'] == 'Avenue'][0]
        self.assertEqual((rf.CLASSES[avenue['flags'] & 7], avenue['speed']), ('primary', 90))
        self.assertEqual(len(avenue['inner']), 1)                             # the 8 m bend stays
        self.assertAlmostEqual(avenue['length'], 2 * math.hypot(8, 50), places=1)

    def test_simplify_drops_points_on_a_straight_line(self):
        line = [(x, 0.) for x in range(0, 101, 20)] + [(100., 50.)]
        self.assertEqual(rf.simplify(line), [(0, 0.), (100, 0.), (100., 50.)])

    def test_speed_reads_units_and_zones(self):
        self.assertEqual(rf.speed_kmh({'maxspeed': '30 mph'}), 48)
        self.assertEqual(rf.speed_kmh({'maxspeed': 'UA:urban'}), 50)
        self.assertEqual(rf.speed_kmh({'maxspeed': 'none'}), 130)
        self.assertEqual(rf.speed_kmh({}), 0)


class RouterTests(unittest.TestCase):
    def load(self, data, shift=(0., 0.)):
        lua = LuaRuntime()
        mod = lua.execute(SRC)
        lua.globals().routing = mod
        lua.globals().blob = data
        lua.execute(f'''
          local r = routing.decode(blob, function(x, y) return x + {shift[0]}, y + {shift[1]} end)
          graph = routing.graph({{r}})''')
        return lua

    def test_route_follows_one_way_and_prefers_the_fast_avenue(self):
        data = rf.encode(rf.graph(grid()))
        decoded = rf.decode(data)
        lua = self.load(data, shift=(1000., -500.))
        lua.execute('''
          local from = routing.nearest(graph, 1000 + 0, -500 + 0)
          local to = routing.nearest(graph, 1000 + 500, -500 + 500)
          route = routing.route(graph, from, to, 'en')''')
        route = lua.eval('route')
        ids = [route.ids[k] for k in range(1, len(route.ids) + 1)]
        self.assertEqual((ids[0], ids[-1]), ('1000', '1035'))
        index = {str(n[0]): k for k, n in enumerate(decoded['nodes'])}
        self.assertAlmostEqual(route.time, dijkstra(decoded, index['1000'], index['1035']), places=3)
        # the 90 km/h avenue (column 3) carries the climb north
        self.assertIn('1027', ids)
        self.assertGreater(len(route.steps), 0)
        names = {route.steps[k].name for k in range(1, len(route.steps) + 1)}
        self.assertIn('Avenue', names)
        # the line is in the world frame and runs through the avenue's bend
        xs = [route.points[k] for k in range(1, len(route.points) + 1, 2)]
        self.assertIn(1000 + 308.0, xs)

    def test_one_way_row_is_not_driven_backwards(self):
        size = 6
        roads = [r for r in grid(size) if r['tags'].get('name') == 'One Way']
        roads.append(road(999, 1012, 1017, [(0, 200), (0, 250), (500, 250), (500, 200)], name='Detour'))
        data = rf.encode(rf.graph(roads))
        lua = self.load(data)
        lua.execute('''
          local from = routing.nearest(graph, 500, 200)
          local to = routing.nearest(graph, 0, 200)
          route = routing.route(graph, from, to, 'en')''')
        route = lua.eval('route')
        self.assertEqual([route.ids[k] for k in range(1, len(route.ids) + 1)], ['1017', '1012'])
        self.assertAlmostEqual(route.length, 600, places=0)

    def test_regions_share_border_nodes_and_edges(self):
        west = rf.graph([r for r in grid() if all((int(n) - 1000) % 6 <= 3 for n in r['nodes'])])
        east = rf.graph([r for r in grid() if all((int(n) - 1000) % 6 >= 3 for n in r['nodes'])])
        lua = LuaRuntime()
        mod = lua.execute(SRC)
        lua.globals().routing = mod
        lua.globals().w, lua.globals().e = rf.encode(west), rf.encode(east)
        lua.execute('''
          graph = routing.graph({routing.decode(w), routing.decode(e)})
          route = routing.route(graph, routing.nearest(graph, 0, 0), routing.nearest(graph, 500, 500), 'en')''')
        self.assertEqual(lua.eval('graph.n'), 36)      # column 3 is in both and counted once
        whole = rf.decode(rf.encode(rf.graph(grid())))
        index = {str(n[0]): k for k, n in enumerate(whole['nodes'])}
        self.assertAlmostEqual(lua.eval('route.time'), dijkstra(whole, index['1000'], index['1035']), places=3)

    def test_unreachable_target_gives_no_route(self):
        roads = [road(1, 1, 2, [(0, 0), (100, 0)]), road(2, 3, 4, [(500, 0), (600, 0)])]
        lua = self.load(rf.encode(rf.graph(roads)))
        self.assertIsNone(lua.eval('routing.route(graph, routing.nearest(graph, 0, 0), routing.nearest(graph, 600, 0))'))


BUILT = sorted((ROOT / 'out/routing').glob('*/earthng/countries/*/routing/*.bin'))


@unittest.skipUnless(BUILT, 'no routing file from build_routing.py in out/routing')
class BuiltRegionTests(unittest.TestCase):
    def test_lua_matches_dijkstra_on_a_real_region(self):
        data = BUILT[0].read_bytes()
        decoded = rf.decode(data)
        lua = LuaRuntime()
        lua.globals().routing = lua.execute(SRC)
        lua.globals().blob = data
        lua.execute('graph = routing.graph({routing.decode(blob)})')
        search = lua.eval('function(a, b) return routing.search(graph, a, b) end')
        rng = random.Random(7)
        n, checked = len(decoded['nodes']), 0
        while checked < 6:
            a, b = rng.randrange(n), rng.randrange(n)
            want = dijkstra(decoded, a, b)
            if want is None:
                continue
            got, _ = search(a, b)
            self.assertAlmostEqual(got, want, delta=1e-3 * want + 1e-6)
            checked += 1


if __name__ == '__main__':
    unittest.main()
