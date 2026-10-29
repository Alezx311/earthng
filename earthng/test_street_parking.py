"""Street parking (ROADS.streetParking, options.experimentalDetail): bays where the road's tags say."""
import math
import unittest

import test_generator


class StreetParkingTests(unittest.TestCase):
    def setUp(self):
        self.h = test_generator.GeneratorTests()
        self.h.setUp()

    def bays(self, tags, width=12, points=(), **opts):
        road = {'id': 'street', 'nodes': ['a', 'b'], 'width': width, 'tags': {'highway': 'residential', **tags},
                'points': [[0, 250, 10], [500, 250, 10]]}
        opts.setdefault('experimentalDetail', True)
        scene = self.h.build([{'roads': [road], 'points': list(points)}], 0, 0, terrainStep=100, maxTrees=0,
                             maxGrass=0, propSpacing=0, parkedCars=8, **opts)[1]
        return [tuple(b.values()) for b in (scene['parking'] or {}).values()]

    def test_off_by_default_and_only_where_tagged(self):
        self.assertEqual(self.bays({'parking:right': 'lane'}, experimentalDetail=False), [])
        self.assertEqual(self.bays({}), [])
        self.assertEqual(self.bays({'parking:both': 'no'}), [])
        self.assertEqual(self.bays({'parking:both': 'separate'}), [])

    def test_a_parking_lane_on_the_right_edge_facing_the_traffic(self):
        bays = self.bays({'parking:right': 'lane'})
        self.assertGreater(len(bays), 60)
        for x, y, z, yaw in bays:
            # the right of the point order (south), inside the 12 m carriageway at its edge
            self.assertAlmostEqual(y, 250 - (6 - .95 - .1), places=3)
            self.assertAlmostEqual(math.cos(yaw), 1, places=6)
            self.assertAlmostEqual(z, 10 + .1, places=3)          # on the road's surface
        xs = sorted(b[0] for b in bays)
        self.assertAlmostEqual(xs[1] - xs[0], 6, places=3)

    def test_astride_the_curb_where_the_moving_lanes_need_the_width(self):
        narrow = self.bays({'parking:both': 'lane'}, width=7)
        self.assertEqual(sorted({round(b[1], 2) for b in narrow}), [246.45, 253.55])
        self.assertEqual(self.bays({'parking:both': 'lane', 'parking:both:orientation': 'diagonal'}, width=7), [])
        wide = self.bays({'parking:both': 'lane'}, width=10)
        self.assertEqual(sorted({round(b[1], 2) for b in wide}), [246.05, 253.95])

    def test_beside_the_road_on_the_left_and_the_older_scheme(self):
        side = self.bays({'parking:left': 'street_side', 'parking:left:orientation': 'perpendicular'})
        self.assertTrue(side)
        for x, y, z, yaw in side:
            self.assertAlmostEqual(y, 250 + 6 + .25 + 2.5, places=3)
            self.assertAlmostEqual(abs(math.sin(yaw)), 1, places=6)
        old = self.bays({'parking:lane:both': 'parallel', 'parking:lane:both:parallel': 'on_street'})
        self.assertEqual(sorted({round(b[1], 2) for b in old}), [245.05, 254.95])
        # the left row faces the other way on a two-way street
        left = [b for b in old if b[1] > 250]
        self.assertAlmostEqual(math.cos(left[0][3]), -1, places=6)

    def test_bays_keep_off_crossings_and_stops(self):
        points = [{'id': 'c', 'kind': 'crossing', 'tags': {'highway': 'crossing'}, 'pos': [200, 250, 10]},
                  {'id': 's', 'kind': 'stop', 'tags': {'highway': 'bus_stop'}, 'pos': [350, 244, 10]}]
        bays = self.bays({'parking:right': 'lane'}, points=points)
        self.assertTrue(bays)
        for x, y, *_ in bays:
            self.assertGreater(math.hypot(x - 200, y - 250), 6)
            self.assertGreater(math.hypot(x - 350, y - 244), 15)


if __name__ == '__main__':
    unittest.main()
