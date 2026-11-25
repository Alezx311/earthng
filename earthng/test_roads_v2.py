"""Roads v2 in the generator (EarthNG-RoadIntelligence, 25.11.2026): curb returns at junction
corners (ROADS.FILLET), one plate for two divided roads crossing (ROADS.CLUSTER), dense ground
presses under plates, paving decided for a whole strip side (ROADS.fillKerbs), zebras at the
mouth and on the top asphalt, the AI's lanes on the painted ones (navSegment). Each has its TUNE
switch, and all are the real pack's only; needs lupa."""
import math
import unittest

import test_generator as tg


class RoadsV2Tests(unittest.TestCase):
    def setUp(self):
        # EarthNG's generator test helpers (build, triangles, surface_at), not its tests
        self.T = tg.GeneratorTests('test_marks_follow_class_and_surface')
        self.T.setUp()
        self.gen = self.T.generator

    def table(self, value):
        return self.T.table(value)

    def asphalt(self, manifest):
        return [t for m in ('e2rf_road', 'e2rf_road_worn', 'e2rf_road_lane', 'e2rf_road_worn_lane', 'e2rf_road_major',
                            'e2rf_road_major_lane') for t in self.T.triangles(manifest, m)]

    def test_every_switch_is_on(self):
        tune = self.gen.TUNE
        self.assertEqual(tune.fillet, 1)
        self.assertEqual(tune.cluster, 1)
        self.assertEqual(tune.densePress, 2)
        self.assertAlmostEqual(tune.walkFill, .4)
        self.assertEqual(tune.zebraMouth, 1)
        self.assertEqual(tune.zebraTop, 1)
        self.assertEqual(tune.navLanes, 1)

    def test_corner_radius_by_class(self):
        F = self.gen.ERI.FILLET
        self.assertEqual(F.radiusOf(self.table({'highway': 'primary'})), 10)
        self.assertEqual(F.radiusOf(self.table({'highway': 'primary_link'})), 10)
        self.assertEqual(F.radiusOf(self.table({'highway': 'service'})), 3)
        self.assertEqual(F.radiusOf(self.table({'highway': 'unknown'})), 5)

    # ---------------------------------------------------------------- paving along a strip side
    def walk(self, sides, kerbs):
        """walk[k] = {side = true} own sidewalks, walk.kerb[k] = {side = metres}, chords 10 m long."""
        n = len(sides)
        w = {k + 1: {s: True for s in sides[k]} for k in range(n)}
        w['kerb'] = {k + 1: dict(kerbs[k]) for k in range(n) if kerbs[k]}
        dist = [10. * k for k in range(n + 1)]
        return self.table(w), self.table(dist)

    def plain_kerb(self, w, n, side):
        kerb = w['kerb']
        return [None if kerb[k + 1] is None or kerb[k + 1][side] is None else round(kerb[k + 1][side], 3) for k in range(n)]

    def test_a_paved_side_is_paved_all_along(self):
        curb = self.gen.TUNE.curb
        # found on chords 2, 3 and 5 of 6: the rest is the kerb stone alone (sidewalk=separate)
        kerbs = [{1: curb}, {1: 3.}, {1: 4.}, {1: curb}, {1: 5.}, {1: curb}]
        w, dist = self.walk([[]] * 6, kerbs)
        self.gen.ERI.fillKerbs(w, dist, .4)
        self.assertEqual(self.plain_kerb(w, 6, 1), [3., 3., 4., 4.5, 5., 5.])

    def test_a_side_found_on_little_of_it_keeps_the_kerb_stone(self):
        curb = self.gen.TUNE.curb
        kerbs = [{1: curb}, {1: curb}, {1: 4.}, {1: curb}, {1: curb}, {1: curb}]
        w, dist = self.walk([[]] * 6, kerbs)
        self.gen.ERI.fillKerbs(w, dist, .4)
        self.assertEqual(self.plain_kerb(w, 6, 1), [curb] * 6)

    def test_an_untagged_sides_own_sidewalk_stays_where_too_little_is_found(self):
        kerbs = [None, None, {-1: 4.}, None, None, None]
        w, dist = self.walk([[-1], [-1], [], [-1], [-1], [-1]], kerbs)
        self.gen.ERI.fillKerbs(w, dist, .4)
        self.assertTrue(all(w[k][-1] for k in (1, 2, 4, 5, 6)))
        self.assertEqual(w['kerb'][3][-1], 4.)

    def test_an_untagged_side_mostly_paved_turns_its_own_sidewalk_into_paving(self):
        kerbs = [{-1: 4.}, {-1: 4.}, None, {-1: 4.}, {-1: 4.}, None]
        w, dist = self.walk([[], [], [-1], [], [], [-1]], kerbs)
        self.gen.ERI.fillKerbs(w, dist, .4)
        self.assertEqual(self.plain_kerb(w, 6, -1), [4.] * 6)
        self.assertFalse(any(w[k][-1] for k in range(1, 7)))

    def test_the_cluster_hull(self):
        C = self.gen.ERI.CLUSTER
        pts = self.table([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [5, 5, 0], [2, 8, 0]])
        hull = C.hull(pts)
        self.assertEqual(len(hull), 4)
        self.assertAlmostEqual(C.area(hull), 100.)

    # ---------------------------------------------------------------- junctions
    def roads(self, through='residential', side='residential', w=7., ws=7.):
        line = tg.line
        # the node in the middle of tile 0, 0 (0..500 m)
        return [{'id': 'w', 'nodes': ['a', 'n'], 'width': w, 'tags': {'highway': through, 'sidewalk': 'no'}, 'points': line(50, 250, 250, 250, 10)},
                {'id': 'e', 'nodes': ['n', 'b'], 'width': w, 'tags': {'highway': through, 'sidewalk': 'no'}, 'points': line(250, 250, 450, 250, 10)},
                {'id': 's', 'nodes': ['n', 'c'], 'width': ws, 'tags': {'highway': side, 'sidewalk': 'no'}, 'points': line(250, 250, 250, 50, 10)}]

    def corner_is_paved(self, **options):
        m = self.T.build([{'roads': self.roads()}], i=0, **options)[0]
        # 1.7 m along and 1.1 m off the edges past their corner (side street x = 253.5, through
        # road y = 246.5): the arc of radius 6 fills it, the chamfer left it as grass
        return self.T.surface_at(self.asphalt(m), 255.2, 245.4) is not None, m

    def test_a_t_junction_corner_is_a_curb_return(self):
        paved, fillet = self.corner_is_paved()
        self.assertTrue(paved)
        self.assertFalse(self.corner_is_paved(tune={'fillet': 0})[0])
        # the arc stays inside the corner's circle (centre 259.5, 240.5; radius 6)
        self.assertIsNone(self.T.surface_at(self.asphalt(fillet), 257.5, 242.5))

    def test_a_through_road_stays_whole_past_a_side_streets_mouth(self):
        m = self.T.build([{'roads': self.roads('primary', 'residential', 7., 5.5)}], i=0)[0]
        marks = list(self.T.triangles(m, 'e2rf_mark'))
        self.assertTrue(marks)
        near = min(math.hypot(p[0] - 250, p[1] - 250) for t in marks for p in t)
        # cut for its corner with the street (2.75 + 6 m), not the node's second road's 10 m
        self.assertLess(near, 10.)
        self.assertGreater(near, 5.5)
        self.assertIsNotNone(self.T.surface_at(list(self.T.triangles(m, 'e2rf_road_major')), 250, 250))

    # ---------------------------------------------------------------- zebras
    def zebra_under_asphalt(self, **options):
        # a T junction on a 10% cross slope (the through road rises east, the side street is flat
        # at the node's height) and a zebra mapped on the side street 4 m from the node, inside the
        # junction's cut: the plate's fan rises east over the street's profile
        def street(ident, nodes, points):
            return {'id': ident, 'nodes': nodes, 'width': 7, 'points': points, 'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        z = lambda x: 20 + .1 * (x - 250)
        roads = [street('w', ['a', 'n'], [[x, 250, z(x)] for x in range(50, 251, 20)]),
                 street('e', ['n', 'b'], [[x, 250, z(x)] for x in range(250, 451, 20)]),
                 street('s', ['n', 'c'], [[250, 250, 20], [250, 246, 20]] + [[250, y, 20] for y in range(230, 49, -20)])]
        zebra = {'id': 'z', 'kind': 'crossing', 'pos': [250, 246, 20], 'tags': {'highway': 'crossing'}}
        m = self.T.build([{'roads': roads, 'points': [zebra]}], **options)[0]
        asphalt = self.asphalt(m)
        marks = [t for t in self.T.triangles(m, 'e2rf_mark') if all(abs(p[0] - 250) < 6 and 236 < p[1] < 249 for p in t)]
        self.assertTrue(marks)
        worst = 0
        for t in marks:
            centre = [sum(p[k] for p in t) / 3 for k in range(3)]
            for x, y, h in [p[:3] for p in t] + [centre]:
                top = self.T.surface_at(asphalt, x, y)
                if top is not None:
                    worst = max(worst, top - h)
        return worst

    def test_a_zebra_by_a_junction_lies_on_the_top_asphalt(self):
        # where it was mapped, on the plate: 0.29 m under its fan at the road's own height before
        self.assertGreater(self.zebra_under_asphalt(tune={'zebraMouth': 0, 'zebraTop': 0}), .2)
        self.assertLessEqual(self.zebra_under_asphalt(tune={'zebraMouth': 0}), 1e-4)
        # at the mouth: 2 cm under the crossing road's strip and the plate's edge before
        self.assertGreater(self.zebra_under_asphalt(tune={'zebraTop': 0}), .01)
        self.assertLessEqual(self.zebra_under_asphalt(), 1e-4)

    # ---------------------------------------------------------------- navgraph
    def nav_radius(self, **options):
        # a widened street: 9.4 m with 1.7 m shoulders, two painted lanes of 3 m
        road = {'id': 'r', 'nodes': ['a', 'b'], 'width': 9.4, 'points': tg.line(0, 250, 500, 250, 10),
                'tags': {'highway': 'residential', 'sidewalk': 'no', 'e2r:lanes': '2',
                         'shoulder:left:width': '1.7', 'shoulder:right:width': '1.7'}}
        nav = self.T.build([{'roads': [road]}], **options)[3]
        return nav.segments[1][4], nav.segments[1][6]

    def test_the_ais_lanes_are_the_painted_ones(self):
        self.assertEqual(self.nav_radius(), ('-+', 3.0))                       # the AI's lanes: 2 x 3 m
        self.assertEqual(self.nav_radius(tune={'navLanes': 0}), ('-+', 4.7))  # 2 x 4.7 m, 0.85 m off the paint

    # ---------------------------------------------------------------- the real pack's only
    def test_the_other_art_packs_build_as_before(self):
        # toon, model, synth, pixel and the seasons (options.realStyle = false): every switch off,
        # whatever the tune says
        self.assertFalse(self.corner_is_paved(realStyle=False)[0])
        self.assertFalse(self.corner_is_paved(realStyle=False, tune={'fillet': 1})[0])
        self.assertGreater(self.zebra_under_asphalt(realStyle=False), .2)
        self.assertEqual(self.nav_radius(realStyle=False), ('-+', 4.7))


if __name__ == '__main__':
    unittest.main()
