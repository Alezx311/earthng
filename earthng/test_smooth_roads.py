"""Plan curves of the roads (generator.lua ROADS.smoothRoads); needs lupa."""
import math
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

SOURCE = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/generator.lua'


def line(x0, y0, x1, y1, z0=20, z1=None, step=20):
    """A straight run as a pack has it: a profile knot at least every 20 m."""
    z1 = z0 if z1 is None else z1
    n = math.ceil(math.hypot(x1 - x0, y1 - y0) / step)
    return [[x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n, z0 + (z1 - z0) * k / n] for k in range(n + 1)]


def turns(points):
    """Degrees of turn at every interior point of a polyline."""
    out = []
    for a, b, c in zip(points, points[1:], points[2:]):
        h1, h2 = math.atan2(b[1] - a[1], b[0] - a[0]), math.atan2(c[1] - b[1], c[0] - b[0])
        out.append(abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi) * 180 / math.pi)
    return out


def off_line(p, points):
    """Metres from p to the nearest part of a polyline."""
    best = math.inf
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1]))
    return best


class SmoothRoadsTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.generator = self.lua.execute(SOURCE.read_text(encoding='utf8'))
        self.roads_table = self.lua.execute('''
          for i = 1, 200 do
            local name, value = debug.getupvalue(..., i)
            if not name then break end
            if name == 'ROADS' then return value end
          end
          error('ROADS not found')
        ''', self.generator.build)

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def same(self, a, b):
        return self.lua.eval('rawequal')(a, b)

    def smooth(self, roads):
        source = self.table(roads)
        out = self.roads_table.smoothRoads(source, self.lua.eval('function() end'))
        result = []
        for k in range(1, len(roads) + 1):
            pts = out[k].points
            result.append([[pts[n][1], pts[n][2], pts[n][3]] for n in range(1, len(pts) + 1)])
        return result, source, out

    def road(self, points, highway='residential', nodes=('a', 'b'), width=6, rid='r'):
        return {'id': rid, 'nodes': list(nodes), 'width': width, 'points': points, 'tags': {'highway': highway}}

    def test_a_straight_road_is_left_as_surveyed(self):
        _, source, out = self.smooth([self.road(line(0, 0, 300, 0))])
        self.assertTrue(self.same(out[1], source[1]))      # the same table: nothing was copied

    def test_a_right_angle_takes_its_class_radius(self):
        pts = line(0, 0, 100, 0) + line(100, 0, 100, 100)[1:]
        (curve,), _, _ = self.smooth([self.road(pts)])
        self.assertEqual(curve[0][:2], [0, 0])
        self.assertEqual(curve[-1][:2], [100, 100])
        # one piece of at most ~5 degrees after another instead of one 90 degree break
        self.assertLess(max(turns(curve)), 6)
        self.assertAlmostEqual(sum(turns(curve)), 90, delta=.01)
        # a residential street turns on 8 m: the arc leaves the chord 8 m before the corner and
        # passes 8 sin(45) / 2 = 2.83 m inside it
        near = min(math.hypot(p[0] - 100, p[1]) for p in curve)
        self.assertAlmostEqual(near, 2.83, delta=.05)
        for p in curve:
            if p[0] < 92 - 1e-6 or p[1] > 8 + 1e-6:
                self.assertLess(off_line(p, pts), 1e-6)    # beyond the arc: on the survey
        # the pieces of the arc are not slivers
        steps = [math.dist(a[:2], b[:2]) for a, b in zip(curve, curve[1:])]
        self.assertGreater(min(steps), .2)

    def test_a_gentle_kink_stays_within_its_cut_of_the_survey(self):
        bend = math.radians(10)
        pts = line(0, 0, 200, 0) + line(200, 0, 200 + 200 * math.cos(bend), 200 * math.sin(bend))[1:]
        (curve,), _, _ = self.smooth([self.road(pts, 'primary', width=10)])
        self.assertLess(max(turns(curve)), 4.01)
        self.assertAlmostEqual(sum(turns(curve)), 10, delta=.01)
        # the node keeps a vertex of its own, on the arc's middle: .45 m off, inside DETAIL.near
        self.assertAlmostEqual(min(math.hypot(p[0] - 200, p[1]) for p in curve), .45, delta=.005)
        self.assertAlmostEqual(max(off_line(p, pts) for p in curve), .45, delta=.005)

    def test_a_sampled_curve_runs_between_its_nodes_and_its_chords(self):
        # a 60 m radius quarter circle mapped every 10 degrees
        ring = [[60 * math.cos(math.radians(a)), 60 * math.sin(math.radians(a)), 20] for a in range(0, 91, 10)]
        (curve,), _, _ = self.smooth([self.road(ring, 'secondary', width=8)])
        self.assertLess(max(turns(curve)), 4.01)
        radius = [math.hypot(p[0], p[1]) for p in curve[1:-1]]
        self.assertLess(max(radius), 60 + 1e-6)             # never outside the mapped nodes
        self.assertGreater(min(radius), 60 * math.cos(math.radians(5)) - .01)   # nor inside the chords
        self.assertEqual(curve[0], ring[0])
        self.assertEqual(curve[-1], ring[-1])

    def test_two_ways_that_run_on_share_one_arc(self):
        bend = math.radians(30)
        east_end = [500 + 200 * math.cos(bend), 250 + 200 * math.sin(bend)]
        west = self.road(line(300, 250, 500, 250), 'tertiary', ('a', 'n'), 7, 'w')
        east = self.road(line(500, 250, east_end[0], east_end[1]), 'tertiary', ('n', 'b'), 7, 'e')
        (w, e), _, _ = self.smooth([west, east])
        self.assertEqual(w[-1], e[0])                       # one shared end, off the node
        # a 30 degree turn of a tertiary road takes its 14 m radius: 14 tan(15) sin(15) / 2 off the node
        self.assertAlmostEqual(math.hypot(w[-1][0] - 500, w[-1][1] - 250), .4855, delta=.005)
        self.assertLess(max(turns(w + e[1:])), 4.01)        # no break at the seam either
        self.assertAlmostEqual(sum(turns(w + e[1:])), 30, delta=.01)
        # the tile's cells may list the two ways in either order
        (e2, w2), _, _ = self.smooth([east, west])
        self.assertEqual(w, w2)
        self.assertEqual(e, e2)

    def test_a_junction_end_stays_on_its_node(self):
        bend = math.radians(30)
        east_end = [500 + 200 * math.cos(bend), 250 + 200 * math.sin(bend)]
        roads = [self.road(line(300, 250, 500, 250), 'tertiary', ('a', 'n'), 7, 'w'),
                 self.road(line(500, 250, east_end[0], east_end[1]), 'tertiary', ('n', 'b'), 7, 'e'),
                 self.road(line(500, 250, 500, 50), 'tertiary', ('n', 'c'), 7, 's')]
        _, source, out = self.smooth(roads)
        for k in (1, 2, 3):
            self.assertTrue(self.same(out[k], source[k]))  # three mouths: a junction, nothing moves

    def test_heights_stay_on_the_profile(self):
        # a ramp of 10 m over the 200 m of chords, through a right angle
        pts = line(0, 0, 100, 0, 20, 25) + line(100, 0, 100, 100, 25, 30)[1:]
        (curve,), _, _ = self.smooth([self.road(pts)])
        z = [p[2] for p in curve]
        self.assertEqual(z[0], 20)
        self.assertEqual(z[-1], 30)
        self.assertTrue(all(b >= a - 1e-9 for a, b in zip(z, z[1:])))
        # the profile's own knots on the straight parts are kept
        self.assertIn([40, 0, 22], [[round(c, 6) for c in p] for p in curve])
        apex = min(curve, key=lambda p: math.hypot(p[0] - 100, p[1]))
        self.assertAlmostEqual(apex[2], 25, delta=.05)

    def test_survey_noise_does_not_bend_the_road(self):
        # two knots 30 cm apart, one of them 4 cm off the line, and a hairpin spike of bad data
        pts = [[0, 0, 20], [50, 0, 20], [50.3, .04, 20], [100, 0, 20], [150, 0, 20], [150.2, 0, 20],
               [149.9, .5, 20], [200, 0, 20]]
        (curve,), _, _ = self.smooth([self.road(pts)])
        self.assertLess(max(off_line(p, pts) for p in curve), .7)
        self.assertEqual(curve[0], pts[0])
        # every surveyed vertex still has a road vertex within DETAIL.near of it (a crossing's node)
        for q in pts[:5]:
            self.assertLess(min(math.hypot(p[0] - q[0], p[1] - q[1]) for p in curve), .5)
        self.assertEqual(curve[-1], pts[-1])

    def test_a_crossing_on_a_sharp_corner_keeps_its_zebra(self):
        # the arc of a 50 degree corner runs 1.6 m inside the node the crossing is mapped on:
        # DETAIL.paint finds it on the surveyed line and paints it on the arc
        bend = math.radians(50)
        pts = line(100, 250, 250, 250) + line(250, 250, 250 + 150 * math.cos(bend), 250 + 150 * math.sin(bend))[1:]
        road = self.road(pts, 'secondary', width=7)
        road['tags']['sidewalk'] = 'no'
        zebra = {'id': 'z', 'kind': 'crossing', 'pos': [250, 250, 20], 'tags': {'highway': 'crossing'}}
        paint = []
        for smooth in (0, 1):
            options = self.table({'relief': False, 'tune': {'smooth': smooth}})
            layer = self.generator.build(self.table([{'roads': [road], 'points': [zebra]}]), 0, 0, options)[0]
            area = 0
            for n in range(1, len(layer['items']) + 1):
                item = layer['items'][n]
                for m in range(1, len(item['meshes'] or []) + 1):
                    mesh = item['meshes'][m]
                    if mesh.material != 'e2rf_mark':
                        continue
                    for k in range(1, len(mesh.faces) + 1, 3):
                        a, b, c = ([mesh.verts[mesh.faces[i].v + 1].x + item.pos[1],
                                    mesh.verts[mesh.faces[i].v + 1].y + item.pos[2]] for i in range(k, k + 3))
                        if all(math.hypot(p[0] - 250, p[1] - 250) < 5 for p in (a, b, c)):
                            area += abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2
            paint.append(area)
        self.assertGreater(paint[0], 5)                     # the zebra's stripes on the surveyed corner
        self.assertGreater(paint[1], paint[0] * .8)


if __name__ == '__main__':
    unittest.main()
