"""The span census's measures (span_census.py), without a pack.

    .venv/Scripts/python.exe -m unittest discover -s earthng -p "test_span_census.py"
"""
import unittest

import numpy as np

import span_census as census


def road(name, nodes, xs, zs, **tags):
    return {'id': name, 'nodes': list(nodes), 'width': 8., 'tags': dict(tags, highway='secondary'),
            'points': [[x, 0., z] for x, z in zip(xs, zs)]}


class SpanCensusTests(unittest.TestCase):
    def test_pieces_of_one_span_are_joined_in_order(self):
        roads = [road('w', 'ab', [0, 100], [20, 20]),
                 road('d2', 'dc', [300, 200], [26, 22], bridge='yes'),          # drawn against the first
                 road('d1', 'bc', [100, 200], [20, 22], bridge='yes'),
                 road('e', 'de', [300, 400], [26, 26]),
                 road('t', 'ef', [400, 500], [26, 20], tunnel='yes'),
                 road('p', 'fg', [500, 520], [20, 20], tunnel='building_passage'),
                 road('f', 'gh', [520, 600], [20, 20], bridge='yes', highway='footway')]
        roads[-1]['tags']['highway'] = 'footway'                                # a foot bridge is no road's span
        found = {kind: [r['id'] for r in chain] for kind, chain, _ in census.chains(roads)}
        self.assertEqual(found, {'bridge': ['d1', 'd2'], 'tunnel': ['t']})
        (kind, chain, flips), = [c for c in census.chains(roads) if c[0] == 'bridge']
        xy, z = census.line_of(chain, flips)
        self.assertEqual(xy[:, 0].tolist(), [100, 200, 300])
        self.assertEqual(z.tolist(), [20, 22, 26])

    def test_a_dip_between_two_higher_parts_is_a_sag_and_a_ramp_is_not(self):
        s = np.arange(0., 240., 20.)
        m = np.array([20., 24, 26, 26, 22, 21, 21, 22, 26, 26, 24, 20])
        got = census.measure('bridge', s, m, np.full(len(s), 15.))
        self.assertAlmostEqual(got['sag'], 5)
        self.assertEqual(got['sag_at'], 100)
        self.assertEqual(got['buried'], 0)
        ramp = np.array([20., 20.5, 21.5, 23, 25, 26, 26, 26, 26, 26, 26, 26])   # a curve up to the deck
        self.assertEqual(census.measure('bridge', s, ramp, None)['sag'], 0)
        # a deck under the ground it should stand over
        self.assertAlmostEqual(census.measure('bridge', s, np.full(len(s), 20.), np.full(len(s), 21.5))['buried'], 1.5)

    def test_a_tunnel_over_the_line_between_its_mouths_or_out_of_the_ground(self):
        s = np.arange(0., 140., 20.)
        ground = np.array([20., 30, 36, 40, 36, 30, 20])
        climb = census.measure('tunnel', s, np.array([20., 23, 27, 29, 27, 23, 20]), ground)
        self.assertAlmostEqual(climb['hump'], 9)
        self.assertAlmostEqual(climb['bare'], 0)
        flat = census.measure('tunnel', s, np.full(len(s), 20.), np.full(len(s), 20.))
        self.assertEqual(flat['hump'], 0)
        self.assertAlmostEqual(flat['bare'], census.HEAD)                # a box on level ground

    def test_the_break_of_the_grade_at_a_joint(self):
        rs, rz = np.array([0., 100.]), np.array([20., 20.])              # level, ending at the joint
        s, z = np.array([0., 100.]), np.array([20., 28.])                # 8 % up from it
        self.assertAlmostEqual(census.break_at(s, z, 0, rs, rz, 1), .08)
        self.assertAlmostEqual(census.break_at(s, z, 0, np.array([0., 100.]), np.array([12., 20.]), 1), 0)
        # rounded over 50 m: the same turn in steps
        ss = np.linspace(0, 100, 101)
        curve = 20 + np.where(ss < 25, .08 * ss * ss / 50, .08 * (ss - 12.5))
        self.assertLess(census.break_at(ss, curve, 0, rs, rz, 1), .02)

    def test_the_worst_span_leads_and_the_summary_counts_over_the_limits(self):
        rows = [{'kind': 'bridge', 'pack_length': 100., 'pack_sag': 0., 'drawn_sag': 0., 'drawn_kink': 1.},
                {'kind': 'bridge', 'pack_length': 300., 'pack_sag': 4., 'drawn_sag': 0., 'drawn_kink': 9.},
                {'kind': 'tunnel', 'pack_length': 50., 'pack_hump': 3., 'drawn_hump': 3.}]
        self.assertEqual([r['pack_length'] for r in census.worst(rows)], [50., 300., 100.])
        got = census.summary(rows)
        self.assertEqual((got['bridge']['count'], got['bridge']['km']), (2, .4))
        self.assertEqual(got['bridge']['pack_sag']['over'], 1)
        self.assertEqual(got['bridge']['drawn_sag']['over'], 0)
        self.assertEqual(got['tunnel']['drawn_hump']['over'], 1)


if __name__ == '__main__':
    unittest.main()
