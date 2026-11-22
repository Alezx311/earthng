"""LuaJIT tests for predict.lua: the path ahead along the navgraph's segments (exp/predict-tiles).

Run with: python -m unittest discover -s earthng -p test_predict.py
"""
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'mod/lua/ge/extensions/e2r/predict.lua').read_text(encoding='utf8')


def segment(sid, a, b, points, lanes='-+'):
    """A segment as world.lua navRead keeps it: s = {id, a, b, lanes, speed, radius, drive, x, y, z...}."""
    s = [sid, a, b, lanes, 13.9, 4, 1]
    for x, y in points:
        s += [x, y, 0]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return {'s': s, 'box': [min(xs), min(ys), max(xs), max(ys)]}


class PredictTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.mod = self.lua.execute(SOURCE)

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def ahead(self, segments, x, y, ux, uy, length):
        index = self.mod.index(self.table({s['s'][0]: s for s in segments}))
        out, on_road = self.mod.ahead(index, x, y, ux, uy, length)
        flat = [out[k] for k in range(1, len(out) + 1)]
        return [tuple(flat[k:k + 3]) for k in range(0, len(flat), 3)], on_road

    def test_along_a_straight_road_every_step_costs_its_metres(self):
        pts, on_road = self.ahead([segment(1, 10, 11, [(0, 0), (1000, 0)])], 100, 2, 1, 0, 500)
        self.assertTrue(on_road)
        self.assertEqual(pts[0], (100, 2, 0))
        road = pts[1:]
        self.assertTrue(all(abs(y) < 1e-6 for _, y, _ in road))
        # a point every STEP (40 m) up to the length: the last at 480 m
        self.assertAlmostEqual(road[0][0], 140)
        self.assertAlmostEqual(road[-1][0], 580)
        for x, _, cost in road:
            self.assertAlmostEqual(cost, x - 100)

    def test_at_a_junction_straight_on_keeps_its_cost_and_a_turn_weighs_more(self):
        segments = [segment(1, 1, 2, [(0, 0), (500, 0)]),
                    segment(2, 2, 3, [(500, 0), (1000, 0)]),
                    segment(3, 2, 4, [(500, 0), (500, 500)])]
        pts, _ = self.ahead(segments, 100, 0, 1, 0, 800)
        straight = [p for p in pts if p[0] > 500.5]
        turn = [p for p in pts if p[1] > .5]
        self.assertTrue(straight and turn)
        for x, _, cost in straight:
            self.assertAlmostEqual(cost, x - 100)
        for _, y, cost in turn:
            self.assertAlmostEqual(cost, (400 + y) * 1.6)
        # the walk reads up to a cost of 800: 800 m straight on, 500 m round the turn (a point
        # every 40 m: the last at 480 m, y 80)
        self.assertAlmostEqual(max(p[0] for p in straight), 900)
        self.assertAlmostEqual(max(p[1] for p in turn), 80)

    def test_a_one_way_street_is_not_entered_against_it_and_a_u_turn_never(self):
        segments = [segment(1, 1, 2, [(0, 0), (500, 0)]),
                    segment(3, 4, 2, [(500, 500), (500, 0)], lanes='++'),     # one-way into the junction
                    segment(5, 2, 5, [(500, 0), (100, 20)])]                   # sharply back
        pts, _ = self.ahead(segments, 100, 0, 1, 0, 800)
        self.assertFalse([p for p in pts if p[1] > .5 and p[0] > 499])
        self.assertFalse([p for p in pts if p[0] < 499 and p[1] > 1])
        # with nowhere to go the road's loose end runs on straight for EXTEND m
        self.assertAlmostEqual(max(p[0] for p in pts), 900)

    def test_past_a_loose_end_the_path_goes_on_straight(self):
        pts, _ = self.ahead([segment(1, 1, 2, [(0, 0), (500, 0)])], 100, 0, 1, 0, 2000)
        # 400 m to the end, then EXTEND (400 m) along the last piece
        self.assertAlmostEqual(max(p[0] for p in pts), 900)
        self.assertAlmostEqual(max(p[2] for p in pts), 800)

    def test_standing_the_path_runs_both_ways_and_heading_back_the_other_way(self):
        segments = [segment(1, 1, 2, [(0, 0), (1000, 0)])]
        pts, _ = self.ahead(segments, 500, 0, 0, 0, 200)
        xs = [p[0] for p in pts]
        self.assertAlmostEqual(min(xs), 300)
        self.assertAlmostEqual(max(xs), 700)
        pts, _ = self.ahead(segments, 500, 0, -1, 0, 200)
        xs = [p[0] for p in pts]
        self.assertAlmostEqual(min(xs), 300)
        self.assertAlmostEqual(max(xs), 500)

    def test_off_every_road_the_path_is_the_heading(self):
        pts, on_road = self.ahead([segment(1, 1, 2, [(0, 0), (1000, 0)])], 100, 200, 0, 1, 300)
        self.assertFalse(on_road)
        self.assertAlmostEqual(pts[-1][1], 480)
        self.assertTrue(all(abs(p[0] - 100) < 1e-6 for p in pts))
        index_less = self.mod.ahead(None, 0, 0, 1, 0, 100)
        self.assertEqual(len(index_less[0]), 3 * 3)

    def test_a_route_is_read_from_the_point_nearest_the_car(self):
        line = self.lua.table_from([0, 0, 1000, 0, 1000, 1000])
        out = self.mod.along(line, 900, 30, 300)
        flat = [out[k] for k in range(1, len(out) + 1)]
        pts = [tuple(flat[k:k + 3]) for k in range(0, len(flat), 3)]
        self.assertEqual(pts[0], (900, 0, 0))
        self.assertAlmostEqual(pts[-1][2], 280)
        # round the corner at 100 m: on the north leg from there
        corner = [p for p in pts if p[1] > 1]
        self.assertTrue(corner)
        for x, y, cost in corner:
            self.assertAlmostEqual(x, 1000)
            self.assertAlmostEqual(cost, 100 + y)


if __name__ == '__main__':
    unittest.main()
