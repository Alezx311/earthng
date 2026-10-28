"""Experimental storefronts: conservative geometry and explicit opt-in."""
import copy
import unittest

import test_generator


class ShopfrontExperimentTests(unittest.TestCase):
    def setUp(self):
        self.h = test_generator.GeneratorTests()
        self.h.setUp()
        self.road = {'id': 'street', 'width': 8, 'tags': {'highway': 'residential'},
                     'points': [[50, 85, 0], [200, 85, 0]]}
        self.house = {'id': 'shop', 'height': 9, 'tags': {'building': 'retail'},
                      'rings': [[[100, 100], [140, 100], [140, 120], [100, 120]]]}

    def build(self, building=None, roads=None, i=0, **opts):
        cell = {'buildings': [self.house if building is None else building],
                'roads': [self.road] if roads is None else roads}
        return self.h.build([cell], i=i, maxTrees=0, maxGrass=0, **opts)

    def shop_tris(self, scene):
        return list(self.h.triangles(scene, 'e2rf_wall_shop_dark'))

    def test_explicit_opt_in_preserves_road_and_replaces_only_lower_street_wall(self):
        road, scene = self.build()[:2]
        off_road, off_scene = self.build(experimentalShopfront=False)[:2]
        changed_road, changed_scene = self.build(experimentalShopfront=True)[:2]
        self.assertEqual(self.h.plain(road), self.h.plain(off_road))
        self.assertEqual(self.h.plain(scene), self.h.plain(off_scene))
        self.assertEqual(self.h.plain(road), self.h.plain(changed_road))
        self.assertFalse(self.shop_tris(scene))
        triangles = self.shop_tris(changed_scene)
        self.assertTrue(triangles)
        vertices = [p for t in triangles for p in t]
        self.assertTrue(all(abs(p[1] - 100) < 1e-6 for p in vertices))
        # No new wall outside the original footprint; the shop is a split, not an overlay.
        self.assertEqual({round(p[0], 6) for p in vertices}, {100, 140})
        def wall_faces(manifest):
            result = []
            for item, mesh in self.h.meshes(manifest):
                if not mesh.material.startswith('e2rf_wall_'):
                    continue
                for k in range(1, len(mesh.faces) + 1, 3):
                    triangle = []
                    for index in range(k, k + 3):
                        point = mesh.verts[mesh.faces[index].v + 1]
                        triangle.append((point.x + item.pos[1], point.y + item.pos[2], point.z + item.pos[3]))
                    if all(abs(p[1] - 100) < 1e-6 for p in triangle):
                        result.append(triangle)
            return result
        def area_xz(faces):
            return sum(abs((b[0] - a[0]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[0] - a[0])) / 2
                       for a, b, c in faces)
        before, after = wall_faces(scene), wall_faces(changed_scene)
        self.assertTrue(before and after)
        self.assertAlmostEqual(area_xz(before), area_xz(after))
        self.assertAlmostEqual(min(p[2] for t in before for p in t), min(p[2] for p in vertices))
        self.assertGreater(max(p[2] for t in before for p in t), max(p[2] for p in vertices))

    def test_unmapped_ambiguous_and_boundary_cases_are_skipped(self):
        no_shop = copy.deepcopy(self.house)
        no_shop['tags'] = {'building': 'residential'}
        closed_shop = copy.deepcopy(self.house)
        closed_shop['tags'] = {'building': 'residential', 'shop': 'no'}
        elevated = copy.deepcopy(self.house)
        elevated['tags']['min_height'] = '3'
        boundary = copy.deepcopy(self.house)
        boundary['rings'] = [[[490, 100], [510, 100], [510, 120], [490, 120]]]
        boundary_road = {'id': 'edge', 'width': 8, 'tags': {'highway': 'residential'},
                         'points': [[450, 85, 0], [550, 85, 0]]}
        other = {'id': 'other', 'width': 8, 'tags': {'highway': 'residential'},
                 'points': [[50, 135, 0], [200, 135, 0]]}
        for building, roads, i, options in [
            (no_shop, [self.road], 0, {}),
            (closed_shop, [self.road], 0, {}),
            (elevated, [self.road], 0, {}),
            (self.house, [], 0, {}),
            (self.house, [self.road, other], 0, {}),
            (boundary, [boundary_road], 0, {}),
            (boundary, [boundary_road], 1, {}),
            (self.house, [self.road], 0, {'far': True}),
        ]:
            with self.subTest(tags=building['tags'], i=i, options=options):
                self.assertFalse(self.shop_tris(self.build(building, roads, i, experimentalShopfront=True, **options)[1]))

    def test_input_order_and_explicit_shop_tag(self):
        tagged = copy.deepcopy(self.house)
        tagged['tags'] = {'building': 'yes', 'shop': 'bakery'}
        extra = {'id': 'far', 'width': 8, 'tags': {'highway': 'residential'},
                 'points': [[300, 300, 0], [400, 300, 0]]}
        first = self.shop_tris(self.build(tagged, [self.road, extra], experimentalShopfront=True)[1])
        reverse = self.shop_tris(self.build(tagged, [extra, self.road], experimentalShopfront=True)[1])
        self.assertTrue(first)
        self.assertEqual(first, reverse)
        tagged['rings'][0].reverse()
        winding = self.shop_tris(self.build(tagged, [self.road, extra], experimentalShopfront=True)[1])
        # The oriented face is invariant to clockwise/anticlockwise input winding.
        self.assertEqual(first, winding)

    def test_near_road_beyond_fine_dem_bins_is_found_even_when_wide(self):
        # Fine DEM uses pullZero=15 m, while storefronts look 18 m from the road edge.
        # Put the wall on a 50 m bin boundary, so the old smaller road bins missed it.
        for width in (8, 80):
            road = {'id': 'wide', 'width': width, 'tags': {'highway': 'residential'},
                    'points': [[50, 100 - width / 2 - 17.8, 0],
                               [200, 100 - width / 2 - 17.8, 0]]}
            with self.subTest(width=width):
                off = self.build(roads=[road], tune={'pullZero': 15})
                on = self.build(roads=[road], experimentalShopfront=True, tune={'pullZero': 15})
                self.assertEqual(self.h.plain(off[0]), self.h.plain(on[0]))
                scene = on[1]
                self.assertTrue(self.shop_tris(scene))

    def test_road_centre_outside_tile_can_still_face_interior_wall(self):
        building = copy.deepcopy(self.house)
        building['rings'] = [[[30, 100], [50, 100], [50, 140], [30, 140]]]
        road = {'id': 'outside', 'width': 80, 'tags': {'highway': 'residential'},
                'points': [[-27.8, 50, 0], [-27.8, 200, 0]]}
        self.assertTrue(self.shop_tris(self.build(building, [road], experimentalShopfront=True,
                                                 tune={'pullZero': 15})[1]))


if __name__ == '__main__':
    unittest.main()
