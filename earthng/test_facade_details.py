"""Facade details (BLD.downpipes, BLD.acUnits): opt-in, on the texture's window grid, deterministic."""
import unittest

import test_generator


class FacadeDetailTests(unittest.TestCase):
    def setUp(self):
        self.h = test_generator.GeneratorTests()
        self.h.setUp()
        self.road = {'id': 'street', 'width': 8, 'tags': {'highway': 'residential'},
                     'points': [[50, 85, 0], [250, 85, 0]]}

    def block(self, material='brick', height=15, ring=None, ident='b1'):
        return {'id': ident, 'height': height,
                'tags': {'building': 'apartments', 'building:material': material, 'height': str(height)},
                'rings': [ring or [[100, 100], [160, 100], [160, 112], [100, 112]]]}

    def build(self, buildings, **opts):
        cells = [{'buildings': buildings, 'roads': [self.road]}]
        return self.h.build(cells, 0, 0, maxTrees=0, maxGrass=0, **opts)

    def tris(self, manifest, material):
        return list(self.h.triangles(manifest, 'e2rf_' + material))

    def test_off_by_default_and_roads_unchanged(self):
        off = self.build([self.block()])
        on = self.build([self.block()], experimentalDetail=True)
        self.assertFalse(self.tris(off[1], 'pipe') or self.tris(off[1], 'ac_unit'))
        self.assertTrue(self.tris(on[1], 'pipe'))
        self.assertEqual(self.h.plain(off[0]), self.h.plain(on[0]))
        far = self.build([self.block()], experimentalDetail=True, far=True)
        for manifest in far[:3]:
            if manifest is not None:
                self.assertFalse(self.tris(manifest, 'pipe') or self.tris(manifest, 'ac_unit'))

    def test_downpipes_on_the_outer_corners_of_a_low_brick_block(self):
        scene = self.build([self.block()], experimentalDetail=True)[1]
        pipes = self.tris(scene, 'pipe')
        # four corners, three boxes each: shaft (4 sides), hopper (4 + bottom), kick-out (4 + top)
        self.assertEqual(len(pipes), 4 * (8 + 10 + 10))
        corners = [(100, 100), (160, 100), (160, 112), (100, 112)]
        for t in pipes:
            for x, y, _ in t:
                self.assertLess(min(abs(x - cx) + abs(y - cy) for cx, cy in corners), 1.2, (x, y))
                # outside the footprint
                self.assertFalse(100 < x < 160 and 100 < y < 112, (x, y))

    def test_no_pipes_on_panel_or_tall_blocks_and_none_in_a_reentrant_corner(self):
        self.assertFalse(self.tris(self.build([self.block('panel', 27)], experimentalDetail=True)[1], 'pipe'))
        self.assertFalse(self.tris(self.build([self.block('brick', 24)], experimentalDetail=True)[1], 'pipe'))
        ell = [[100, 100], [160, 100], [160, 112], [130, 112], [130, 140], [100, 140]]
        pipes = self.tris(self.build([self.block(ring=ell)], experimentalDetail=True)[1], 'pipe')
        self.assertEqual(len(pipes), 5 * 28)
        for t in pipes:
            for x, y, _ in t:
                self.assertGreater(abs(x - 130) + abs(y - 112), 1.2)

    def test_air_conditioners_sit_under_windows_above_the_ground_floor(self):
        scene = self.build([self.block('panel', 21, ring=[[100, 100], [220, 100], [220, 112], [100, 112]])],
                           experimentalDetail=True)[1]
        units = self.tris(scene, 'ac_unit')
        self.assertTrue(units)
        boxes = {}
        for t in units:
            for x, y, z in t:
                if abs(y - 100) < .5:               # the street wall (y = 100), its outside y < 100
                    self.assertLessEqual(y, 100 + 1e-6)
                    boxes.setdefault(round(x - 1.5) // 3, []).append((x, z))
        self.assertTrue(boxes)
        for xs in boxes.values():
            cx = (min(p[0] for p in xs) + max(p[0] for p in xs)) / 2
            self.assertAlmostEqual((cx - 100) % 3, 1.5, places=4)
            self.assertAlmostEqual(max(p[0] for p in xs) - min(p[0] for p in xs), .8, places=4)
        # the wall's datum: its foot is 0.3 m under it (generator: bottom = low - .3, flat ground)
        walls = [p[2] for _, m in self.h.meshes(scene) if m.material.startswith('e2rf_wall_')
                 for t in self.h.triangles(scene, m.material) for p in t]
        base = min(walls) + .3
        zs = [p[2] - base for t in units for p in t]
        # units start on the first floor, under its window sill (.96 m over the floor)
        self.assertGreaterEqual(min(zs), 3 - 1e-6)
        for z in zs:
            self.assertLessEqual(z % 3, .96 + 1e-6)
        # the same every build
        again = self.tris(self.build([self.block('panel', 21, ring=[[100, 100], [220, 100], [220, 112], [100, 112]])],
                                     experimentalDetail=True)[1], 'ac_unit')
        self.assertEqual(sorted(units), sorted(again))

    def test_no_units_on_blank_end_walls_or_loggia_photos(self):
        loggia = self.build([self.block('panel', 40, ring=[[100, 100], [130, 100], [130, 112], [100, 112]])],
                            experimentalDetail=True)[1]
        kinds = {m.material for _, m in self.h.meshes(loggia)}
        if any(k.startswith('e2rf_wall_lgg_') for k in kinds):
            self.assertFalse([t for t in self.tris(loggia, 'ac_unit')])


if __name__ == '__main__':
    unittest.main()
