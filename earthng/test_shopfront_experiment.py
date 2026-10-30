"""Experimental storefronts (BLD.shopLinks): explicit opt-in, mapped evidence, conservative links."""
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
        # a block with a shop node 2 m in from its street wall (y = 100)
        self.block = {'id': 'block', 'height': 15, 'tags': {'building': 'apartments'},
                      'rings': [[[100, 100], [160, 100], [160, 112], [100, 112]]]}
        self.poi = {'id': '-1000000000042:0', 'kind': 'poi', 'pos': [130, 102, 0],
                    'tags': {'shop': 'bakery', 'name': 'x'}}

    def build(self, building=None, roads=None, i=0, points=None, buildings=None, report=None, infer=True, **opts):
        """infer: the nearest street wall stands in for a mapped door (shopTune inferWall), so the
        street-wall rules are testable; the door tests pass infer=False, the game's default."""
        cell = {'buildings': buildings if buildings is not None else [self.house if building is None else building],
                'roads': [self.road] if roads is None else roads, 'points': points or []}
        if infer and opts.get('experimentalShopfront'):
            opts.setdefault('shopTune', {'inferWall': True})
        options = self.h.table(dict(maxTrees=0, maxGrass=0, **opts))
        if report is not None:
            options.poiReport = report
        return self.h.generator.build(self.h.table([cell]), i, 0, options)

    def shop_tris(self, scene):
        out = []
        for _, mesh in self.h.meshes(scene):
            if mesh.material.startswith('e2rf_wall_shop_'):
                out += list(self.h.triangles(scene, mesh.material))
        return sorted({tuple(sorted(tuple(round(c, 4) for c in p) for p in t)) for t in out})

    def entries(self, report):
        return [e for e in self.h.plain(report) if e.get('evidence') != 'draw']

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
        # a tagged building without a node: the whole street wall less half a metre each end
        self.assertEqual({round(p[0], 6) for p in vertices}, {100.5, 139.5})

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
        # a split, not an overlay: the same wall area
        self.assertAlmostEqual(area_xz(before), area_xz(after))
        self.assertAlmostEqual(min(p[2] for t in before for p in t), min(p[2] for p in vertices))
        self.assertGreater(max(p[2] for t in before for p in t), max(p[2] for p in vertices))

    def test_poi_points_alone_change_nothing_without_the_switch(self):
        # Data-rich pack, experiment off: the new point kind is carried, not drawn
        plain = self.build(buildings=[self.block])
        door = {'id': '-1000000000090:0', 'kind': 'door', 'pos': [128, 100, 0], 'tags': {'entrance': 'yes'}}
        rich = self.build(buildings=[self.block], points=[self.poi, door])
        self.assertEqual(self.h.plain(plain[0]), self.h.plain(rich[0]))
        self.assertEqual(self.h.plain(plain[1]), self.h.plain(rich[1]))

    def test_by_default_a_node_needs_a_mapped_door(self):
        report = self.h.lua.table()
        scene = self.build(buildings=[self.block], points=[self.poi], experimentalShopfront=True, report=report,
                           infer=False)[1]
        self.assertFalse(self.shop_tris(scene))
        self.assertEqual([e['reason'] for e in self.entries(report)], ['no_mapped_door'])

    def test_the_wall_of_the_mapped_door_nearest_the_node(self):
        # doors on the back (y = 112, the yard) and on an end wall; the back door is nearest
        back = {'id': '-1000000000090:0', 'kind': 'door', 'pos': [128, 112, 0], 'tags': {'entrance': 'yes'}}
        end = {'id': '-1000000000091:0', 'kind': 'door', 'pos': [160, 106, 0], 'tags': {'entrance': 'shop'}}
        far = {'id': '-1000000000092:0', 'kind': 'door', 'pos': [100, 104, 0], 'tags': {'entrance': 'yes'}}
        stairs = {'id': '-1000000000093:0', 'kind': 'entrance', 'pos': [131, 100, 0], 'tags': {'entrance': 'staircase'}}
        poi = copy.deepcopy(self.poi)
        poi['pos'] = [130, 108, 0]
        report = self.h.lua.table()
        scene = self.build(buildings=[self.block], points=[poi, back, end, far, stairs], experimentalShopfront=True,
                           report=report, infer=False)[1]
        [entry] = self.entries(report)
        self.assertEqual((entry['decision'], entry['how'], entry['door'], entry['doorTag']),
                         ('linked', 'mapped_door', back['id'], 'yes'))
        # the anticlockwise ring runs the back wall from x = 160 to 100: the span is 4 m either
        # side of the door, on the wall the yard sees (no street needed)
        self.assertEqual(entry['wall'], '160.000,112.000,100.000,112.000')
        self.assertEqual(entry['span'], [28, 36])
        self.assertNotIn('street', entry)
        vertices = [p for t in self.shop_tris(scene) for p in t]
        self.assertTrue(vertices and all(abs(p[1] - 112) < 1e-6 for p in vertices))
        self.assertEqual({round(p[0], 6) for p in vertices}, {124, 132})
        # a door off the outline (a gate in the yard) or beyond doorReach is no evidence
        gate = copy.deepcopy(back)
        gate['pos'] = [128, 118, 0]
        lone = copy.deepcopy(end)
        lone['pos'] = [160, 106, 0]
        poi['pos'] = [102, 102, 0]
        report = self.h.lua.table()
        self.build(buildings=[self.block], points=[poi, gate], experimentalShopfront=True, report=report, infer=False)
        self.assertEqual([e['reason'] for e in self.entries(report)], ['no_mapped_door'])
        report = self.h.lua.table()
        self.build(buildings=[self.block], points=[poi, lone], experimentalShopfront=True, report=report, infer=False)
        self.assertEqual([e['reason'] for e in self.entries(report)], ['no_mapped_door'])

    def test_poi_ties_a_span_of_the_nearest_street_wall(self):
        report = self.h.lua.table()
        road, scene = self.build(buildings=[self.block], points=[self.poi], experimentalShopfront=True,
                                 report=report)[:2]
        self.assertEqual(self.h.plain(road), self.h.plain(self.build(buildings=[self.block], points=[self.poi])[0]))
        vertices = [p for t in self.shop_tris(scene) for p in t]
        self.assertTrue(vertices)
        self.assertTrue(all(abs(p[1] - 100) < 1e-6 for p in vertices))
        self.assertEqual({round(p[0], 6) for p in vertices}, {126, 134})
        [entry] = self.entries(report)
        self.assertEqual(entry['decision'], 'linked')
        self.assertEqual(entry['poi'], self.poi['id'])
        self.assertEqual(entry['how'], 'nearest_street_wall')
        self.assertEqual(entry['match'], 'inside')
        self.assertEqual(entry['levelRule'], 'unknown')
        self.assertEqual(entry['wall'], '100.000,100.000,160.000,100.000')

    def test_poi_near_the_wall_end_keeps_its_span_length(self):
        poi = copy.deepcopy(self.poi)
        poi['pos'] = [101, 102, 0]
        vertices = [p for t in self.shop_tris(self.build(buildings=[self.block], points=[poi],
                                                          experimentalShopfront=True)[1]) for p in t]
        self.assertEqual({round(p[0], 6) for p in vertices}, {100.5, 108.5})

    def reason(self, poi=None, buildings=None, roads=None, points=None, **opts):
        report = self.h.lua.table()
        scene = self.build(buildings=buildings or [self.block], roads=roads, report=report,
                           points=points or [poi or self.poi], experimentalShopfront=True, **opts)[1]
        entries = [e for e in self.entries(report) if e['evidence'] == 'poi']
        return entries[0].get('reason'), self.shop_tris(scene)

    def test_unclear_cases_are_skipped_with_a_reason(self):
        def tagged(**tags):
            poi = copy.deepcopy(self.poi)
            poi['tags'].update(tags)
            return poi
        deep = copy.deepcopy(self.block)
        deep['rings'] = [[[100, 100], [160, 100], [160, 160], [100, 160]]]
        deep_poi = copy.deepcopy(self.poi)
        deep_poi['pos'] = [130, 130, 0]
        twin = copy.deepcopy(self.block)
        twin['id'] = 'twin'
        outside = copy.deepcopy(self.poi)
        outside['pos'] = [130, 125, 0]
        between = copy.deepcopy(self.poi)
        between['pos'] = [130, 114, 0]
        other = {'id': 'other', 'height': 15, 'tags': {'building': 'yes'},
                 'rings': [[[100, 116], [160, 116], [160, 130], [100, 130]]]}
        back = copy.deepcopy(self.poi)
        back['pos'] = [130, 110, 0]
        corner = copy.deepcopy(self.poi)
        corner['pos'] = [102, 102, 0]
        side = {'id': 'side', 'width': 8, 'tags': {'highway': 'residential'}, 'points': [[85, 50, 0], [85, 200, 0]]}
        yard = {'id': 'yard', 'width': 4, 'tags': {'highway': 'service'}, 'points': [[50, 85, 0], [200, 85, 0]]}
        for name, args, expected in [
            ('upper', dict(poi=tagged(level='1')), 'level_upper_floor'),
            ('below', dict(poi=tagged(level='-1')), 'level_below_ground'),
            ('unclear', dict(poi=tagged(level='ground')), 'level_unclear'),
            ('indoor', dict(poi=tagged(indoor='yes')), 'indoor'),
            ('two_footprints', dict(buildings=[self.block, twin]), 'inside_several_buildings'),
            ('no_building', dict(poi=outside), 'no_building_near'),
            ('between_two', dict(poi=between, buildings=[self.block, other]), 'several_buildings_near'),
            ('deep_inside', dict(poi=deep_poi, buildings=[deep]), 'street_wall_too_far'),
            ('corner', dict(poi=corner, roads=[self.road, side]), 'two_street_walls_tie'),
            ('service_only', dict(roads=[yard]), 'no_street_wall'),
        ]:
            with self.subTest(name):
                reason, tris = self.reason(**args)
                self.assertEqual(reason, expected)
                self.assertFalse(tris)
        # the back of the block: its nearest street wall is still the front, within depth
        reason, tris = self.reason(poi=back)
        self.assertIsNone(reason)
        self.assertTrue(tris)
        # ground floor among others is the ground floor
        for level in ('0', '0;1', '-1;0', '0-2'):
            with self.subTest(level=level):
                self.assertIsNone(self.reason(poi=tagged(level=level))[0])

    def test_a_building_between_wall_and_street_blocks_it(self):
        kiosk = {'id': 'kiosk', 'height': 3, 'tags': {'building': 'kiosk'},
                 'rings': [[[110, 92], [150, 92], [150, 97], [110, 97]]]}
        reason, tris = self.reason(buildings=[self.block, kiosk])
        self.assertEqual(reason, 'no_street_wall')
        self.assertFalse(tris)

    def test_mapped_staircase_entrance_keeps_its_wall(self):
        entrance = {'id': '-1000000000077:0', 'kind': 'entrance', 'pos': [130, 100, 0],
                    'tags': {'entrance': 'staircase'}}
        tris = self.shop_tris(self.build(buildings=[self.block], points=[self.poi, entrance],
                                         experimentalShopfront=True)[1])
        xs = sorted({round(p[0], 6) for t in tris for p in t})
        self.assertEqual(xs, [126, 128.8, 131.2, 134])

    def test_a_small_shop_loses_its_house_dress_and_squeezes_the_band(self):
        kiosk = {'id': 'kiosk', 'height': 3.5, 'tags': {'building': 'yes', 'shop': 'kiosk', 'height': '3.5'},
                 'rings': [[[100, 100], [106, 100], [106, 104], [100, 104]]]}
        plain = self.build(kiosk)[1]
        self.assertTrue(any(m.material.startswith('e2rf_hw_') for _, m in self.h.meshes(plain)))
        report = self.h.lua.table()
        scene = self.build(kiosk, experimentalShopfront=True, report=report)[1]
        self.assertFalse(any(m.material.startswith('e2rf_hw_') for _, m in self.h.meshes(scene)))
        draws = [e for e in self.h.plain(report) if e.get('evidence') == 'draw']
        self.assertEqual([(e['decision'], e['reason'], round(e['band'], 6)) for e in draws],
                         [('drawn', 'house_walls_replaced', 3.1)])
        tris = self.shop_tris(scene)
        self.assertTrue(tris)
        # the band stops 0.4 m under the eaves, over the plaster's 0.35 m plinth; its texture
        # shows the whole 4.2 m design
        self.assertAlmostEqual(max(p[2] for t in tris for p in t) - min(p[2] for t in tris for p in t),
                               3.1 - .35, places=3)
        for _, mesh in self.h.meshes(scene):
            if mesh.material.startswith('e2rf_wall_shop_'):
                vs = [mesh.uvs[k].v if hasattr(mesh.uvs[k], 'v') else mesh.uvs[k][2] for k in range(1, len(mesh.uvs) + 1)]
                self.assertAlmostEqual(max(vs), .7, places=3)

    def test_shop_props_stand_along_the_span_through_the_shared_planner(self):
        long_block = copy.deepcopy(self.block)
        long_block['rings'] = [[[100, 100], [220, 100], [220, 112], [100, 112]]]
        road = {'id': 'street', 'width': 8, 'tags': {'highway': 'residential'}, 'points': [[50, 85, 0], [260, 85, 0]]}
        poi = copy.deepcopy(self.poi)
        poi['pos'] = [160, 102, 0]

        def furniture(on):
            scene = self.build(buildings=[long_block], roads=[road], points=[poi], propSpacing=6,
                               experimentalShopfront=on)[1]
            return [(item.pos[1], item.pos[2], item.name) for item in scene['items'].values()
                    if item.streetKind == 'furniture']
        off, on = furniture(False), furniture(True)
        self.assertFalse([f for f in off if 'poifront_' in f[2]])
        front = [f for f in on if 'poifront_' in f[2]]
        self.assertTrue(front)
        for x, y, _ in front:
            # before the span (156..164 m along the wall), out on the street side
            self.assertTrue(155 <= x <= 165 and 90 < y < 100, (x, y))
        # here nothing else moved (in a crowded street the shared planner may drop a lower one)
        self.assertEqual(sorted(f for f in on if 'poifront_' not in f[2]), sorted(off))

    def test_house_lifted_and_low_buildings_keep_their_walls(self):
        lifted = copy.deepcopy(self.block)
        lifted['tags']['min_height'] = '3'
        low = copy.deepcopy(self.block)
        low['height'] = 2.8
        low['tags']['height'] = '2.8'
        for building, reason in [(lifted, 'building_lifted'), (low, 'building_low')]:
            with self.subTest(reason):
                report = self.h.lua.table()
                scene = self.build(buildings=[building], points=[self.poi], experimentalShopfront=True,
                                   report=report)[1]
                self.assertFalse(self.shop_tris(scene))
                draws = [e for e in self.h.plain(report) if e.get('evidence') == 'draw']
                self.assertEqual({e['reason'] for e in draws}, {reason})

    def test_input_order_winding_and_duplicates(self):
        extra = {'id': 'far', 'width': 8, 'tags': {'highway': 'residential'},
                 'points': [[300, 300, 0], [400, 300, 0]]}
        other = copy.deepcopy(self.poi)
        other['id'], other['pos'] = '-1000000000043:0', [150, 103, 0]
        first = self.shop_tris(self.build(buildings=[self.block], roads=[self.road, extra],
                                          points=[self.poi, other], experimentalShopfront=True)[1])
        reverse = self.shop_tris(self.build(buildings=[self.block], roads=[extra, self.road],
                                            points=[other, self.poi], experimentalShopfront=True)[1])
        wound = copy.deepcopy(self.block)
        wound['rings'][0].reverse()
        winding = self.shop_tris(self.build(buildings=[wound], roads=[self.road, extra],
                                            points=[self.poi, other], experimentalShopfront=True)[1])
        self.assertTrue(first)
        self.assertEqual(first, reverse)
        self.assertEqual(first, winding)
        # the same node in two source cells (a halo) is one storefront
        cells = [{'buildings': [self.block], 'roads': [self.road], 'points': [self.poi]},
                 {'buildings': [self.block], 'roads': [self.road], 'points': [self.poi]}]
        twice = self.h.generator.build(self.h.table(cells), 0, 0,
                                       self.h.table(dict(maxTrees=0, maxGrass=0, experimentalShopfront=True,
                                                       shopTune={'inferWall': True})))[1]
        once = self.build(buildings=[self.block], points=[self.poi], experimentalShopfront=True)[1]
        self.assertEqual(self.shop_tris(twice), self.shop_tris(once))

    def test_tiles_either_side_of_a_building_agree(self):
        # The block spans the tile edge at x = 500; the street's near end lies in tile 0 only.
        block = copy.deepcopy(self.block)
        block['rings'] = [[[470, 100], [530, 100], [530, 112], [470, 112]]]
        poi = copy.deepcopy(self.poi)
        poi['pos'] = [497, 102, 0]
        road = {'id': 'street', 'width': 8, 'tags': {'highway': 'residential'}, 'points': [[300, 85, 0], [700, 85, 0]]}
        left = self.shop_tris(self.build(buildings=[block], roads=[road], points=[poi], i=0, experimentalShopfront=True)[1])
        right = self.shop_tris(self.build(buildings=[block], roads=[road], points=[poi], i=1, experimentalShopfront=True)[1])
        xs = {round(p[0], 6) for t in left + right for p in t}
        self.assertTrue(left and right)
        self.assertEqual((min(xs), max(xs)), (493, 501))

    def test_cell_seam_needs_both_cells_to_hold_the_neighbourhood(self):
        # cellSize 500 (the halo 100): a block 80 m past the seam at x = 500 may be cut away
        block = copy.deepcopy(self.block)
        block['rings'] = [[[420, 100], [580, 100], [580, 112], [420, 112]]]
        poi = copy.deepcopy(self.poi)
        poi['pos'] = [450, 102, 0]
        road = {'id': 'street', 'width': 8, 'tags': {'highway': 'residential'}, 'points': [[300, 85, 0], [700, 85, 0]]}
        reason, tris = self.reason(poi=poi, buildings=[block], roads=[road], cellSize=500)
        self.assertEqual(reason, 'cell_seam')
        self.assertFalse(tris)
        reason, tris = self.reason(poi=poi, buildings=[block], roads=[road])
        self.assertIsNone(reason)
        self.assertTrue(tris)
        # near the seam but wholly in one cell: only tiles of that cell draw it
        near = copy.deepcopy(self.block)
        near['rings'] = [[[420, 100], [480, 100], [480, 112], [420, 112]]]
        reason, tris = self.reason(poi=poi, buildings=[near], roads=[road], cellSize=500)
        self.assertIsNone(reason)
        self.assertTrue(tris)

    def test_far_tiles_and_tagged_buildings_with_several_street_walls(self):
        for manifest in self.build(far=True, experimentalShopfront=True)[:3]:
            if manifest is not None:
                self.assertFalse(self.shop_tris(manifest))
        other = {'id': 'other', 'width': 8, 'tags': {'highway': 'residential'}, 'points': [[50, 135, 0], [200, 135, 0]]}
        self.assertFalse(self.shop_tris(self.build(roads=[self.road, other], experimentalShopfront=True)[1]))
        closed = copy.deepcopy(self.house)
        closed['tags'] = {'building': 'residential', 'shop': 'vacant'}
        self.assertFalse(self.shop_tris(self.build(closed, experimentalShopfront=True)[1]))

    def test_near_road_beyond_fine_dem_bins_is_found_even_when_wide(self):
        # Fine DEM uses pullZero=15 m, while storefronts look 18 m from the road edge.
        for width in (8, 80):
            road = {'id': 'wide', 'width': width, 'tags': {'highway': 'residential'},
                    'points': [[50, 100 - width / 2 - 17.8, 0], [200, 100 - width / 2 - 17.8, 0]]}
            with self.subTest(width=width):
                off = self.build(roads=[road], tune={'pullZero': 15})
                on = self.build(roads=[road], experimentalShopfront=True, tune={'pullZero': 15})
                self.assertEqual(self.h.plain(off[0]), self.h.plain(on[0]))
                self.assertTrue(self.shop_tris(on[1]))

    def test_road_centre_outside_tile_can_still_face_interior_wall(self):
        building = copy.deepcopy(self.house)
        building['rings'] = [[[30, 100], [50, 100], [50, 140], [30, 140]]]
        road = {'id': 'outside', 'width': 80, 'tags': {'highway': 'residential'},
                'points': [[-27.8, 50, 0], [-27.8, 200, 0]]}
        self.assertTrue(self.shop_tris(self.build(building, [road], experimentalShopfront=True,
                                                  tune={'pullZero': 15})[1]))


if __name__ == '__main__':
    unittest.main()
