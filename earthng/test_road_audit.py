"""The road audit's grading, on hand-made rasters (no pack, no Lua)."""
import unittest

import numpy as np

import road_audit as audit


class GradeTests(unittest.TestCase):
    def setUp(self):
        self.rect = [0, 0, 100, 100]
        # a 6 m wide strip of asphalt along y = 50 at z 10, ground 1 m under it
        self.asphalt = np.full((100, 100), np.nan)
        self.asphalt[47:53, :] = 10.
        self.ground = np.full((100, 100), 9.)
        self.road = [[0, 50, 10], [100, 50, 10]]

    def test_a_drawn_road_passes(self):
        bad, checked = audit.grade(self.road, {'highway': 'trunk'}, self.rect, self.asphalt, self.ground)
        self.assertEqual(bad, [])
        self.assertGreater(checked, 12)             # a 100 m road, a sample every 6 m, none within 1 m of the tile's edge

    def test_a_hole_in_the_asphalt_is_missing(self):
        self.asphalt[:, 40:70] = np.nan
        bad, _ = audit.grade(self.road, {'highway': 'trunk'}, self.rect, self.asphalt, self.ground)
        self.assertTrue(bad and all(b[0] == 'missing' and 35 < b[1] < 75 for b in bad))
        runs = audit.stretches(bad)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0][0], 'missing')
        self.assertAlmostEqual(runs[0][1], 30, delta=12)           # the hole, to the 6 m step

    def test_ground_over_the_asphalt_is_buried_unless_the_road_is_a_tunnel(self):
        self.ground[:, 20:40] = 11.
        bad, _ = audit.grade(self.road, {'highway': 'trunk'}, self.rect, self.asphalt, self.ground)
        self.assertTrue(bad and all(b[0] == 'buried' for b in bad))
        for tags in ({'highway': 'trunk', 'tunnel': 'yes'}, {'highway': 'trunk', 'layer': '-1'}):
            self.assertEqual(audit.grade(self.road, tags, self.rect, self.asphalt, self.ground)[0], [])
        # a building passage is not a tunnel
        self.assertTrue(audit.grade(self.road, {'highway': 'trunk', 'tunnel': 'building_passage'},
                                    self.rect, self.asphalt, self.ground)[0])

    def test_ground_under_or_level_with_the_asphalt_is_fine(self):
        self.ground[:, :] = 10.02
        self.assertEqual(audit.grade(self.road, {'highway': 'trunk'}, self.rect, self.asphalt, self.ground)[0], [])

    def test_stretches_split_at_a_gap_and_at_a_change_of_kind(self):
        bad = [('missing', 10, 50, 0.), ('missing', 16, 50, 6.), ('missing', 40, 50, 30.), ('buried', 46, 50, 36.)]
        kinds = [(k, round(length)) for k, length, _, _ in audit.stretches(bad)]
        self.assertEqual(kinds, [('missing', 12), ('missing', 6), ('buried', 6)])


if __name__ == '__main__':
    unittest.main()
