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


class BarrierTests(unittest.TestCase):
    def setUp(self):
        self.asphalt = np.full((100, 100), np.nan)
        self.asphalt[40:60, :] = 10.

    def test_a_rail_standing_on_the_asphalt_is_found_and_one_beside_it_is_not(self):
        top, low = np.full((100, 100), np.nan), np.full((100, 100), np.nan)
        top[48:52, 20:80], low[48:52, 20:80] = 10.75, 9.7               # across the lane, base sunk in the road
        top[10:12, 20:80], low[10:12, 20:80] = 10.75, 9.7               # beside it, off the asphalt
        pixels = audit.barrier_pixels(self.asphalt, top, low)
        self.assertEqual(int(pixels.sum()), 4 * 60)
        self.assertTrue(pixels[48:52, 20:80].all() and not pixels[10:12].any())
        cells = audit.barrier_cells(pixels, [0, 0, 100, 100])
        self.assertAlmostEqual(sum(c[2] for c in cells), 240, delta=1)

    def test_a_rail_along_the_edge_is_not_on_the_road(self):
        top, low = np.full((100, 100), np.nan), np.full((100, 100), np.nan)
        top[40, 20:80], low[40, 20:80] = 10.75, 9.7                     # posts over the asphalt's first row
        top[59, 20:80], low[59, 20:80] = 10.75, 9.7                     # and its last
        self.assertEqual(int(audit.barrier_pixels(self.asphalt, top, low).sum()), 0)

    def test_a_barrier_high_over_the_road_or_too_tall_is_not_standing_on_it(self):
        top, low = np.full((100, 100), np.nan), np.full((100, 100), np.nan)
        top[48:52, 20:80], low[48:52, 20:80] = 16., 14.                 # a gantry 4 m over the lane
        self.assertEqual(int(audit.barrier_pixels(self.asphalt, top, low).sum()), 0)


class PackTests(unittest.TestCase):
    def test_a_one_region_zip_without_a_country_manifest_is_read(self):
        import json
        import tempfile
        import zipfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'county.zip'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('earthng/countries/estonia/regions/harju-maakond/manifest.json',
                           json.dumps({'tileSize': 500, 'cellSize': 1000, 'blocks': {}}))
            pack, named = audit.rq.Pack(path), audit.rq.Pack(path, 'harju-maakond')
            try:
                self.assertEqual((pack.size, pack.cell, pack.country['regions'][0]['id']), (500, 1000, 'harju-maakond'))
                self.assertEqual(named.size, 500)
            finally:
                pack.zip.close()
                named.zip.close()


class SpikeTests(unittest.TestCase):
    def mesh(self, *zs):
        return ' '.join(f'{x} 5 {z}' for x, z in zip((0, 1, 0.5) * (len(zs) // 3), zs))

    def test_a_rail_with_a_vertex_dropped_to_the_ground_is_found(self):
        found = audit.spikes(self.mesh(47, 47.3, 47, 22, 47.3, 47))            # a rail triangle, then one with a vertex at 22 m
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0][2], 25.3, delta=.01)

    def test_an_ordinary_rail_or_fence_is_not(self):
        self.assertEqual(audit.spikes(self.mesh(47, 47.75, 47, 47, 47.75, 47.75)), [])
        self.assertEqual(audit.spikes(self.mesh(0, 2.4, 0)), [])               # a 2.4 m fence

    def test_a_tall_wide_wall_is_a_building_and_not_a_rail(self):
        self.assertEqual(audit.spikes('0 5 40  19 5 40  19 5 76'), [])         # a warehouse's clad_metal


class RowLineTests(unittest.TestCase):
    def test_a_finding_with_a_fractional_length_prints(self):
        # a lamp 1 m inside a carriageway has a float length: the summary crashed on it with `:5d`
        row = {'kind': 'prop', 'length_m': 1.0, 'name': '', 'class': 'lamp streetlamp on the carriageway',
               'bridge': False, 'lat': 59.3, 'lon': 24.8, 'road': 7}
        self.assertIn('prop', audit.row_line(row))
        self.assertIn('  12 m ', audit.row_line({**row, 'kind': 'missing', 'length_m': 12}))


class SpikeBuildingTests(unittest.TestCase):
    def test_a_narrow_tall_triangle_at_a_buildings_outline_is_its_wall(self):
        ring = [[0, 0, 0], [30, 0, 0], [30, 20, 0], [0, 20, 0], [0, 0, 0]]
        wall = '30 5 0  30.7 5.3 0  30.7 5.3 18'          # a corner sliver of a warehouse's cladding
        self.assertEqual(audit.spikes(wall), [(35., 5., 18.)])
        self.assertEqual(audit.spikes(wall, rings=[ring]), [])
        self.assertEqual(len(audit.spikes('60 5 0  60.7 5.3 0  60.7 5.3 18', rings=[ring])), 1)       # far from it: a rail


class UnderDeckTests(unittest.TestCase):
    RECT = [0., 0., 40., 40.]

    def deck(self):
        a = np.full((40, 40), np.nan)
        a[10:30, 10:30] = 20.
        return a

    def rail(self, x, z):
        return f'{x} 20 {z}  {x + 2} 20 {z}  {x + 2} 20 {z + .75}'

    def test_a_rail_with_a_deck_over_it_is_found(self):
        self.assertEqual(audit.rails_under([self.rail(14, 10.)], self.deck(), self.RECT), [(15., 25., 1)])

    def test_a_rail_on_the_deck_or_off_it_is_not(self):
        self.assertEqual(audit.rails_under([self.rail(14, 20.)], self.deck(), self.RECT), [])
        self.assertEqual(audit.rails_under([self.rail(33, 10.)], self.deck(), self.RECT), [])

    def test_a_wall_wider_than_a_rail_is_not(self):
        self.assertEqual(audit.rails_under(['12 20 10  22 20 10  22 20 20'], self.deck(), self.RECT), [])

    def test_a_rail_at_the_foot_of_an_embankment_is_not(self):
        # the ramp's edge pixel is 10 m over the rail beside it: the road is high there, the rail is not under it
        self.assertEqual(audit.rails_under([self.rail(9, 10.)], self.deck(), self.RECT), [])
        self.assertEqual(audit.rails_under([self.rail(10, 10.)], self.deck(), self.RECT), [(15., 25., 1)])


if __name__ == '__main__':
    unittest.main()
