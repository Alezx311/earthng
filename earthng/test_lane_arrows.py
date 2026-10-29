"""Lane arrows from turn:lanes (DETAIL.arrows, options.experimentalDetail)."""
import unittest

import test_generator


class LaneArrowTests(unittest.TestCase):
    def setUp(self):
        self.h = test_generator.GeneratorTests()
        self.h.setUp()

    def marks(self, tags, width=10.5, **opts):
        road = {'id': 'r', 'nodes': ['a', 'b'], 'width': width,
                'tags': {'highway': 'secondary', 'sidewalk': 'no', **tags},
                'points': [[0, 250, 10], [400, 250, 10]]}
        built = self.h.build([{'roads': [road], 'points': []}], 0, 0, **opts)[0]
        return [[tuple(p[:3]) for p in t] for t in self.h.triangles(built, 'e2rf_mark')]

    def arrows(self, tags, **opts):
        base = set(map(tuple, map(sorted, self.marks({k: v for k, v in tags.items() if 'turn' not in k}, **opts))))
        return [t for t in self.marks(tags, **opts) if tuple(sorted(t)) not in base]

    def test_off_by_default(self):
        tags = {'oneway': 'yes', 'lanes': '3', 'turn:lanes': 'left|through|right'}
        self.assertEqual(self.arrows(tags), [])
        self.assertTrue(self.arrows(tags, experimentalDetail=True))

    def test_one_way_lanes_left_to_right_before_the_end(self):
        tags = {'oneway': 'yes', 'lanes': '3', 'turn:lanes': 'left|through|through;right'}
        arrows = self.arrows(tags, experimentalDetail=True)
        xs = [p[0] for t in arrows for p in t]
        ys = [p[1] for t in arrows for p in t]
        # two sets: the last one tipped 6 m short of the end at x = 400, one 25 m before it
        self.assertAlmostEqual(max(xs), 400 - 6, delta=.05)
        self.assertLess(min(xs), 400 - 6 - 25 - 4.3)
        # inside the carriageway (lanes of 3.5 m); the left lane (north, +y) turns left
        self.assertLess(max(ys), 250 + 5.25)
        self.assertGreater(min(ys), 250 - 5.25)
        near = [p for t in arrows for p in t if p[0] > 380]
        lane = lambda lo, hi: [p for p in near if lo <= p[1] <= hi]
        self.assertGreater(max(p[1] for p in lane(251.75, 255)), 253.5 + .5)   # the left arm
        self.assertLess(min(p[1] for p in lane(245, 248.25)), 246.5 - .5)      # the right arm

    def test_backward_lanes_on_their_own_half_and_bare_tag_on_two_way_left(self):
        arrows = self.arrows({'lanes': '2', 'turn:lanes:backward': 'left'}, experimentalDetail=True)
        self.assertTrue(arrows)
        xs = [p[0] for t in arrows for p in t]
        # towards x = 0, short of the 6 m before the end (a turn-only arrow has no head on top)
        self.assertTrue(6 <= min(xs) < 8, min(xs))
        self.assertTrue(all(p[1] >= 250 - 1e-6 for t in arrows for p in t))   # the north half
        self.assertEqual(self.arrows({'lanes': '2', 'turn:lanes': 'left|through'}, experimentalDetail=True), [])


if __name__ == '__main__':
    unittest.main()
