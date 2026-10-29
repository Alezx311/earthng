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


class RoadCoverTests(unittest.TestCase):
    def setUp(self):
        self.h = test_generator.GeneratorTests()
        self.h.setUp()

    def covers(self, tags, i=0, points=None, **opts):
        road = {'id': 'w1', 'width': 8, 'tags': tags, 'points': points or [[-200, 250, 0], [1200, 250, 0]]}
        out = self.h.build([{'roads': [road]}], i, 0, maxTrees=0, maxGrass=0, **opts)
        result = {}
        for kind in ('manhole', 'drain'):
            result[kind] = [t for m in out[:2] for t in self.h.triangles(m, 'e2rf_' + kind)]
        return result

    def centres(self, triangles):
        # two triangles a quad: the centre of each quad's four corners
        pts = sorted({(round(p[0], 3), round(p[1], 3)) for t in triangles for p in t})
        return pts

    def test_off_by_default_and_only_on_town_streets(self):
        town = {'highway': 'residential', 'sidewalk': 'both'}
        self.assertEqual(self.covers(town), {'manhole': [], 'drain': []})
        on = self.covers(town, experimentalDetail=True)
        self.assertTrue(on['manhole'] and on['drain'])
        self.assertEqual(self.covers({'highway': 'service', 'sidewalk': 'both'}, experimentalDetail=True),
                         {'manhole': [], 'drain': []})
        self.assertEqual(self.covers({'highway': 'residential', 'sidewalk': 'no'}, experimentalDetail=True),
                         {'manhole': [], 'drain': []})
        self.assertEqual(self.covers({'highway': 'residential', 'sidewalk': 'both', 'bridge': 'yes', 'layer': '1'},
                                     experimentalDetail=True), {'manhole': [], 'drain': []})

    def test_lattice_spacing_sides_and_tile_seams(self):
        town = {'highway': 'residential', 'sidewalk': 'both'}
        tiles = {i: self.covers(town, i=i, experimentalDetail=True) for i in (-1, 0, 1)}

        def area(tris):
            return sum(abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2 for a, b, c in tris)
        holes = [t for i in (-1, 0, 1) for t in tiles[i]['manhole']]
        # each tile draws its part: whole covers add up to whole areas (0.82 m squares)
        self.assertAlmostEqual(area(holes) / (.82 * .82), round(area(holes) / (.82 * .82)), places=3)
        # the one on the seam at x = 0 is split between tiles -1 and 0
        seam = [t for i in (-1, 0) for t in tiles[i]['manhole'] if min(p[0] for p in t) > -1 and max(p[0] for p in t) < 1]
        self.assertAlmostEqual(area(seam), .82 * .82, places=4)
        whole = [t for t in tiles[0]['manhole'] + tiles[1]['manhole'] if max(p[0] for p in t) - min(p[0] for p in t) > .8]
        cx = sorted({round((min(p[0] for p in t) + max(p[0] for p in t)) / 2, 2) for t in whole})
        self.assertEqual({round(b - a, 2) for a, b in zip(cx, cx[1:])}, {55.0})
        # alternating lanes: 0.45 of the half width off the centre line (y = 250)
        ys = {round((min(p[1] for p in t) + max(p[1] for p in t)) / 2, 2) for t in whole}
        self.assertEqual(ys, {round(250 + 1.8, 2), round(250 - 1.8, 2)})
        # drains at both curbs, inside the carriageway
        drains = [t for i in (0, 1) for t in tiles[i]['drain']]
        dy = {round((min(p[1] for p in t) + max(p[1] for p in t)) / 2, 2) for t in drains}
        self.assertEqual(dy, {round(250 + 4 - .24 - .12, 2), round(250 - 4 + .24 + .12, 2)})

if __name__ == '__main__':
    unittest.main()
