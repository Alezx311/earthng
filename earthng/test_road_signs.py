"""Road signs (SIGNS, options.experimentalDetail): mapped nodes and what the roads at a node say."""
import math
import unittest

import test_generator

J = [250, 250, 10]


def arm(ident, end, highway='residential', **tags):
    return {'id': ident, 'nodes': ['j', ident], 'width': 8, 'tags': {'highway': highway, **tags},
            'points': [J, end]}


class RoadSignTests(unittest.TestCase):
    def setUp(self):
        self.h = test_generator.GeneratorTests()
        self.h.setUp()

    def signs(self, roads, points=(), **opts):
        cells = [{'roads': roads, 'points': list(points)}]
        opts.setdefault('experimentalDetail', True)
        scene = self.h.build(cells, 0, 0, terrainStep=100, maxTrees=0, maxGrass=0, propSpacing=0, **opts)[1]
        out = []
        for item in scene['items'].values():
            if item.streetKind == 'sign':
                yaw = 2 * math.atan2(item.rot[3], item.rot[4])
                out.append((item.shape.split('italy_traf_sign_')[1][:-4], item.pos[1], item.pos[2], yaw))
        return sorted(out)

    def t_junction(self, minor='residential', **extra):
        return [arm('w', [0, 250, 10], 'primary'), arm('e', [500, 250, 10], 'primary'),
                arm('s', [250, 0, 10], minor, **extra)]

    def test_off_by_default(self):
        self.assertEqual(self.signs(self.t_junction(), experimentalDetail=False), [])

    def test_a_side_street_gives_way_and_the_main_road_is_signed(self):
        signs = self.signs(self.t_junction())
        kinds = [s[0] for s in signs]
        self.assertEqual(kinds.count('give_way'), 1)
        self.assertEqual(kinds.count('priorityroad'), 2)
        give = [s for s in signs if s[0] == 'give_way'][0]
        # on the right of who drives north up the side street, short of the junction, facing south
        self.assertTrue(254 < give[1] < 258, give)
        self.assertTrue(235 < give[2] < 250, give)
        self.assertAlmostEqual(math.sin(give[3]), 0, places=3)
        self.assertGreater(math.cos(give[3]), .99)
        for _, x, y, yaw in [s for s in signs if s[0] == 'priorityroad']:
            # beside the main road, out of the carriageway, turned to the approach
            self.assertTrue(abs(y - 250) > 4.2, (x, y))
            # the face looks away from the junction, at the driver coming up to it
            fx, fy = -math.sin(yaw), -math.cos(yaw)
            self.assertGreater(fx * (x - 250), 0, (x, y, yaw))

    def test_no_priority_signs_where_crossings_have_lights_or_roads_are_equal(self):
        lights = [{'id': 'c1', 'kind': 'crossing', 'tags': {'highway': 'crossing', 'crossing': 'traffic_signals'},
                   'pos': [250, 230, 10]}]
        self.assertFalse([s for s in self.signs(self.t_junction(), lights) if s[0] in ('give_way', 'priorityroad')])
        equal = [arm('w', [0, 250, 10]), arm('e', [500, 250, 10]), arm('s', [250, 0, 10])]
        self.assertEqual(self.signs(equal), [])
        # a service way out of a yard is not signed either
        self.assertFalse([s for s in self.signs(self.t_junction('service')) if s[0] == 'give_way'])

    def test_a_mapped_give_way_node_stands_once(self):
        node = {'id': 'g1', 'kind': 'give_way', 'tags': {'highway': 'give_way'}, 'pos': [250, 0 + 230, 10]}
        roads = self.t_junction()
        roads[2]['points'] = [J, [250, 230, 10], [250, 0, 10]]
        kinds = [s[0] for s in self.signs(roads, [node])]
        self.assertEqual(kinds.count('give_way'), 1)

    def test_a_speed_change_and_a_marked_crossing(self):
        roads = [{'id': 'a', 'nodes': ['x', 'k'], 'width': 8, 'tags': {'highway': 'tertiary', 'maxspeed': '50'},
                  'points': [[0, 250, 10], [100, 250, 10], [250, 250, 10]]},   # the crossing is a vertex
                 {'id': 'b', 'nodes': ['k', 'y'], 'width': 8, 'tags': {'highway': 'tertiary', 'maxspeed': '30'},
                  'points': [[250, 250, 10], [500, 250, 10]]}]
        crossing = {'id': 'z1', 'kind': 'crossing', 'tags': {'highway': 'crossing', 'crossing': 'zebra'},
                    'pos': [100, 250, 10]}
        signs = self.signs(roads, [crossing])
        speed = [s for s in signs if s[0].startswith('speed_')]
        self.assertEqual([s[0] for s in speed], ['speed_30', 'speed_50'])
        thirty = speed[0]
        # 8 m past the node eastbound, on the south (right) side, facing west
        self.assertAlmostEqual(thirty[1], 258, delta=.6)
        self.assertLess(thirty[2], 246)
        self.assertLess(-math.sin(thirty[3]), -.99)
        zebras = [s for s in signs if s[0] == 'zebra']
        self.assertEqual(len(zebras), 2)
        self.assertEqual(sorted(s[2] > 250 for s in zebras), [False, True])
        # 40 km/h has no model: nothing rather than a wrong number
        roads[1]['tags']['maxspeed'] = '40'
        self.assertEqual([s[0] for s in self.signs(roads) if s[0].startswith('speed_')], ['speed_50'])

    def test_one_way_street_off_a_junction(self):
        roads = self.t_junction(oneway='yes')
        roads[2]['points'] = [J, [250, 0, 10]]          # leaves the junction southwards
        kinds = [s[0] for s in self.signs(roads)]
        self.assertIn('one_way', kinds)
        self.assertNotIn('noentry', kinds)
        self.assertNotIn('give_way', kinds)             # nobody drives up it to the junction
        roads[2]['tags']['oneway'] = '-1'
        kinds = [s[0] for s in self.signs(roads)]
        self.assertIn('noentry', kinds)
        self.assertIn('give_way', kinds)

    def test_tiles_agree(self):
        """A sign stands once over the four tiles round a junction on their corner."""
        roads = [{'id': i, 'nodes': ['j', i], 'width': 8, 'tags': {'highway': h},
                  'points': [[500, 500, 10], end]}
                 for i, h, end in (('w', 'primary', [0, 500, 10]), ('e', 'primary', [1000, 500, 10]),
                                   ('s', 'residential', [500, 0, 10]), ('n', 'residential', [500, 1000, 10]))]
        seen = []
        for i in (0, 1):
            for j in (0, 1):
                cells = [{'roads': roads, 'points': []}]
                scene = self.h.build(cells, i, j, terrainStep=100, maxTrees=0, maxGrass=0, propSpacing=0,
                                     experimentalDetail=True)[1]
                seen += [(round(it.pos[1], 3), round(it.pos[2], 3)) for it in scene['items'].values()
                         if it.streetKind == 'sign']
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(len(seen), 4)                  # two give-ways, two main-road signs


if __name__ == '__main__':
    unittest.main()
