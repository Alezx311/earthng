"""Runtime Lua geometry invariants; needs lupa (or the existing out/test-tools install)."""
import copy
import json
import math
import sys
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

SOURCE = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/generator.lua'


def area(triangle):
    a, b, c = triangle
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2


def line(x0, y0, x1, y1, z=20):
    """A straight road as a pack has it: a point at least every 20 m (build_country.road_feature)."""
    n = math.ceil(math.hypot(x1 - x0, y1 - y0) / 20)
    return [[x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n, z] for k in range(n + 1)]


def cyclic(t):
    """A texture coordinate difference with whole repeats removed, in [-0.5, 0.5)."""
    return (t + .5) % 1 - .5


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.generator = self.lua.execute(SOURCE.read_text(encoding='utf8'))

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def plain(self, value):
        if hasattr(value, 'keys'):
            keys = list(value.keys())
            if all(isinstance(k, int) for k in keys):
                return [self.plain(value[k]) for k in range(1, len(keys) + 1)]
            return {k: self.plain(v) for k, v in value.items()}
        return value

    def build(self, cells, i=0, j=0, **options):
        return self.generator.build(self.table(cells), i, j, self.table(options))

    def meshes(self, manifest, material=None):
        for item in manifest['items'].values():
            for mesh in (item['meshes'] or self.lua.table()).values():
                if material is None or mesh.material == material:
                    yield item, mesh

    def triangles(self, manifest, material=None):
        for item, mesh in self.meshes(manifest, material):
            for k in range(1, len(mesh.faces) + 1, 3):
                triangle = []
                for index in range(k, k + 3):
                    p = mesh.verts[mesh.faces[index].v + 1]
                    triangle.append([p.x + item.pos[1], p.y + item.pos[2], p.z + item.pos[3]])
                yield triangle

    def uv_corners(self, manifest, material):
        """Every face corner as (x, y, z, u, v) in world metres."""
        for item, mesh in self.meshes(manifest, material):
            for k in range(1, len(mesh.faces) + 1):
                face = mesh.faces[k]
                p, uv = mesh.verts[face.v + 1], mesh.uvs[face.u + 1]
                yield p.x + item.pos[1], p.y + item.pos[2], p.z + item.pos[3], uv.u, uv.v

    def test_concave_polygon_and_courtyard_hole_keep_exact_area(self):
        shapes = [
            ([[[0, 0], [4, 0], [4, 1], [1, 1], [1, 4], [0, 4]]], 7),
            ([[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
              [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]]], 84),
        ]
        for rings, expected in shapes:
            with self.subTest(area=expected):
                triangles = self.plain(self.generator.triangulate(self.table(rings)))
                self.assertAlmostEqual(sum(map(area, triangles)), expected)
                for triangle in triangles:
                    if expected == 84:
                        cx = sum(p[0] for p in triangle) / 3
                        cy = sum(p[1] for p in triangle) / 3
                        self.assertFalse(3 < cx < 7 and 3 < cy < 7)

    def test_clip_interpolates_height_and_uv_at_tile_border(self):
        clipped = self.plain(self.generator.clip(self.table([
            [-10, 0, 0, 0, 0], [10, 0, 20, 1, 0], [10, 10, 20, 1, 1], [-10, 10, 0, 0, 1],
        ]), self.table([0, 0, 5, 10])))
        self.assertEqual(len(clipped), 4)
        for x, y, z, u, v in clipped:
            self.assertGreaterEqual(x, 0)
            self.assertLessEqual(x, 5)
            self.assertAlmostEqual(z, x + 10)
            self.assertAlmostEqual(u, (x + 10) / 20)
            self.assertAlmostEqual(v, y / 10)

    def test_profiled_road_and_terrain_are_continuous_across_tiles(self):
        source = [{'roads': [{'id': 'road', 'nodes': [10, 20], 'width': 10,
                              'tags': {'highway': 'residential', 'sidewalk': 'no'},
                              'points': [[0, 250, 10], [1000, 250, 20]]}],
                   'terrain': {'rect': [0, 0, 1000, 500], 'nx': 2, 'ny': 2, 'heights': [100] * 4}}]
        left = self.build(source)[0]
        right = self.build(source, i=1)[0]
        borders = []
        for manifest in [left, right]:
            road_border = set()
            for triangle in self.triangles(manifest, 'e2rf_road'):
                for x, y, z in triangle:
                    if abs(x - 500) < 1e-7:
                        road_border.add((round(y, 6), round(z, 6)))
            borders.append(road_border)
        self.assertEqual(borders[0], borders[1])
        self.assertEqual(borders[0], {(245, 15.1), (255, 15.1)})
        ground_points = [p for triangle in self.triangles(left, 'e2rf_ground') for p in triangle]
        pulled = [p[2] for p in ground_points if p[0] == 250 and p[1] == 250]
        self.assertTrue(pulled)
        # the ground lies at least groundDrop (0.25 m) under the road's profile, as in the Python
        # generator, and lower where the high DEM beside the road would lift it through the asphalt
        self.assertTrue(all(z <= 12.25 + 1e-7 for z in pulled))
        distant = [p[2] for p in ground_points if p[1] == 0]
        self.assertTrue(all(abs(z - 99.75) < 1e-7 for z in distant))
        for _, mesh in self.meshes(left, 'e2rf_road'):
            self.assertTrue(all(n.z == 1 for n in mesh.normals.values()))

    def surface_at(self, triangles, x, y):
        """The highest of the triangles over (x, y), or None."""
        best = None
        for a, b, c in triangles:
            den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(den) < 1e-12:
                continue
            u = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / den
            v = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / den
            if u >= -1e-9 and v >= -1e-9 and u + v <= 1 + 1e-9:
                z = u * a[2] + v * b[2] + (1 - u - v) * c[2]
                best = z if best is None else max(best, z)
        return best

    def test_sidewalks_stay_off_the_other_street_at_a_crossing(self):
        # two streets crossing at (250, 250); the old ribbons ran their sidewalks over each other
        roads = [{'id': 'ns', 'nodes': ['a', 'b'], 'width': 8, 'tags': {'highway': 'residential', 'sidewalk': 'both'},
                  'points': [[250, 0, 10], [250, 500, 10]]},
                 {'id': 'ew', 'nodes': ['c', 'd'], 'width': 8, 'tags': {'highway': 'residential', 'sidewalk': 'both'},
                  'points': [[0, 250, 10], [500, 250, 10]]}]
        road = self.build([{'roads': roads}])[0]
        walks = list(self.triangles(road, 'e2rf_sidewalk')) + list(self.triangles(road, 'e2rf_curb'))
        self.assertTrue(walks)
        for tri in walks:
            self.assertTrue(all(abs(p[2] - 10.1) < 1e-6 for p in tri))  # flush with the road
        # no sidewalk anywhere on either carriageway near the crossing
        for x in range(200, 301, 2):
            for y in (246.5, 250, 253.5):
                self.assertIsNone(self.surface_at(walks, x + .25, y), (x, y))
                self.assertIsNone(self.surface_at(walks, y, x + .25), (y, x))

    def detail_marks(self, roads, points):
        road = self.build([{'roads': roads, 'points': points}])[0]
        return [[tuple(p[:3]) for p in t] for t in self.triangles(road, 'e2rf_mark')], road

    def test_a_zebra_crossing_is_painted_across_the_street_at_its_node(self):
        street = {'id': 'r', 'nodes': ['a', 'b'], 'width': 7, 'tags': {'highway': 'residential', 'sidewalk': 'no'},
                  'points': [[0, 250, 10], [250, 250, 10], [500, 250, 10]]}
        zebra = {'id': 'z', 'kind': 'crossing', 'pos': [250, 250.05, 10], 'tags': {'highway': 'crossing'}}
        marks, _ = self.detail_marks([street], [zebra])
        self.assertTrue(marks)
        xs = [p[0] for t in marks for p in t]
        ys = [p[1] for t in marks for p in t]
        self.assertLessEqual(max(xs) - min(xs), 3.01)                  # 3 m along the street
        self.assertAlmostEqual((max(xs) + min(xs)) / 2, 250, places=3)
        self.assertGreater(max(ys) - min(ys), 6)                       # across the carriageway
        self.assertLess(max(ys) - min(ys), 7.5)
        self.assertIsNotNone(self.surface_at(marks, 250, 250))         # stripes and gaps
        self.assertIsNone(self.surface_at(marks, 250, 250.5))
        self.assertEqual(self.detail_marks([street], [])[0], [])

    def test_give_way_teeth_face_the_approach_and_move_to_the_junction_mouth(self):
        def street(id, nodes, points):
            return {'id': id, 'nodes': nodes, 'width': 7, 'points': points,
                    'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        through = [street('s', ['s', 'n'], [[250, 0, 10], [250, 250, 10]]),
                   street('t', ['n', 'u'], [[250, 250, 10], [250, 500, 10]])]
        side = street('w', ['a', 'n'], [[0, 250, 10], [245, 250, 10], [250, 250, 10]])
        give = {'id': 'g', 'kind': 'give_way', 'pos': [245, 250, 10], 'tags': {'highway': 'give_way'}}
        marks, _ = self.detail_marks(through + [side], [give])
        self.assertTrue(marks)
        xs = [p[0] for t in marks for p in t]
        ys = [p[1] for t in marks for p in t]
        # the mouth: 0.8 x 7 m from the node, the line 0.3 m before it, the teeth 0.6 m deep
        self.assertAlmostEqual(max(xs), 250 - 5.6 - .3, places=3)
        self.assertAlmostEqual(min(xs), 250 - 5.6 - .3 - .6, places=3)
        # traffic towards +x keeps right: the half south of the centre line
        self.assertLess(max(ys), 250)
        self.assertGreater(min(ys), 246.4)
        # tagged backward on a plain street: the other half, at the node itself
        plain = street('p', ['a', 'b'], [[0, 250, 10], [245, 250, 10], [500, 250, 10]])
        back = dict(give, tags={'highway': 'give_way', 'direction': 'backward'})
        marks, _ = self.detail_marks([plain], [back])
        self.assertGreater(min(p[1] for t in marks for p in t), 250)
        self.assertAlmostEqual(min(p[0] for t in marks for p in t), 245, places=3)
        self.assertAlmostEqual(max(p[0] for t in marks for p in t), 245.6, places=3)

    def test_a_turning_circle_widens_the_dead_end(self):
        street = {'id': 'r', 'nodes': ['a', 'n'], 'width': 7, 'tags': {'highway': 'residential', 'sidewalk': 'no'},
                  'points': [[0, 250, 10], [250, 250, 10]]}
        circle = {'id': 'c', 'kind': 'turning_circle', 'pos': [250, 250, 10], 'tags': {'highway': 'turning_circle'}}
        for points, round_end in (([], False), ([circle], True)):
            asphalt = list(self.triangles(self.build([{'roads': [street], 'points': points}])[0], 'e2rf_road'))
            self.assertIsNotNone(self.surface_at(asphalt, 240, 250))
            for x, y in ((250, 255.5), (255.5, 250), (250, 244.5), (246, 255)):
                self.assertEqual(self.surface_at(asphalt, x, y) is not None, round_end, (x, y, round_end))

    def test_a_mini_roundabout_is_a_painted_ring_on_its_junction(self):
        def street(id, nodes, points):
            return {'id': id, 'nodes': nodes, 'width': 7, 'points': points,
                    'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        roads = [street('w', ['w', 'n'], [[0, 250, 10], [250, 250, 10]]),
                 street('e', ['n', 'e'], [[250, 250, 10], [500, 250, 10]]),
                 street('s', ['s', 'n'], [[250, 0, 10], [250, 250, 10]])]
        mini = {'id': 'm', 'kind': 'mini_roundabout', 'pos': [250, 250, 10], 'tags': {'highway': 'mini_roundabout'}}
        marks, _ = self.detail_marks(roads, [mini])
        self.assertTrue(marks)
        for t in marks:
            cx, cy = sum(p[0] for p in t) / 3, sum(p[1] for p in t) / 3
            self.assertAlmostEqual(math.hypot(cx - 250, cy - 250), 2, delta=.35)

    def test_a_bridge_deck_has_edges_a_soffit_and_parapets(self):
        def walls(tags):
            road = {'id': 'b', 'nodes': ['a', 'b'], 'width': 8, 'tags': dict(tags, highway='trunk', sidewalk='no'),
                    'points': [[0, 250, 20], [500, 250, 20]]}
            return list(self.triangles(self.build([{'roads': [road]}])[1], 'e2rf_fence_wall'))
        self.assertEqual(walls({}), [])
        deck = walls({'bridge': 'viaduct', 'layer': '1'})
        self.assertTrue(deck)
        zs = [p[2] for t in deck for p in t]
        ys = [p[1] for t in deck for p in t]
        lift = 20 + .1                                                # ROAD_LIFT
        self.assertAlmostEqual(min(zs), lift - 1, places=2)          # the soffit, 1 m under
        self.assertAlmostEqual(max(zs), lift + .9, places=2)         # the parapet's top
        self.assertAlmostEqual(max(ys), 254, places=3)               # flush with the deck edge
        self.assertAlmostEqual(min(ys), 246, places=3)
        self.assertEqual(walls({'tunnel': 'building_passage'}), [])

    def test_per_side_sidewalk_tags_win(self):
        def sides(tags):
            road = {'id': 'r', 'nodes': ['a', 'b'], 'width': 7, 'points': [[0, 250, 10], [500, 250, 10]],
                    'tags': dict(tags, highway='residential')}
            walks = self.triangles(self.build([{'roads': [road]}])[0], 'e2rf_sidewalk')
            ys = [sum(p[1] for p in t) / 3 for t in walks]
            return {'left' for y in ys if y > 250} | {'right' for y in ys if y < 250}
        # left of the node order is +y here
        self.assertEqual(sides({'sidewalk:right': 'separate', 'sidewalk:left': 'no'}), {'right'})
        self.assertEqual(sides({'sidewalk:left': 'yes'}), {'left'})
        self.assertEqual(sides({'sidewalk': 'both', 'sidewalk:left': 'no'}), {'right'})
        self.assertEqual(sides({'sidewalk:both': 'separate'}), {'left', 'right'})
        self.assertEqual(sides({'sidewalk:both': 'no'}), set())

    def test_ground_never_reaches_the_asphalt_in_a_dip(self):
        # the road's profile dips 1.5 m between two 25 m lattice nodes (an underpass approach): the
        # ground, pulled to the profile at the nodes only, used to come up through the asphalt
        cell = {'roads': [{'id': 'r', 'nodes': ['a', 'b'], 'width': 7, 'tags': {'highway': 'tertiary', 'sidewalk': 'no'},
                           'points': [[0, 237, 10], [250, 250, 10], [262.5, 250.65, 8.5], [275, 251.3, 10], [500, 263, 10]]}],
                'terrain': {'rect': [0, 0, 500, 500], 'nx': 2, 'ny': 2, 'heights': [10] * 4}}
        road = self.build([cell])[0]
        ground = list(self.triangles(road, 'e2rf_ground'))
        asphalt = list(self.triangles(road, 'e2rf_road'))
        for k in range(200, 320):
            x = float(k)
            y = 237 + 26 * x / 500
            for off in (-3.4, 0, 3.4):
                top = self.surface_at(asphalt, x, y + off)
                low = self.surface_at(ground, x, y + off)
                self.assertIsNotNone(top)
                if low is not None:
                    self.assertLess(low, top - .05, (x, off))

    def test_junction_is_derived_from_road_ends_without_source_junctions(self):
        # a T of three graph segments meeting at node 'n' (500, 250), no junction feature: the
        # roads stop 0.8 x the widest (10 m) = 8 m short of the node, a fan from the node fills
        # the mouths, and both tiles round the node draw the same fan
        roads = [{'id': 'w', 'nodes': ['a', 'n'], 'width': 10, 'tags': {'highway': 'residential'},
                  'points': [[300, 250, 10], [500, 250, 10]]},
                 {'id': 'e', 'nodes': ['n', 'b'], 'width': 10, 'tags': {'highway': 'residential'},
                  'points': [[500, 250, 10], [700, 250, 10]]},
                 {'id': 's', 'nodes': ['n', 'c'], 'width': 6, 'tags': {'highway': 'residential'},
                  'points': [[500, 250, 10], [500, 50, 10]]}]
        left, right = self.build([{'roads': roads}], i=0)[0], self.build([{'roads': roads}], i=1)[0]
        for manifest, x0 in ((left, 400), (right, 500)):
            asphalt = list(self.triangles(manifest, 'e2rf_road'))
            # every point of the three carriageways near the node is asphalt at road height
            for x in [x0 + k + .5 for k in range(0, 100, 2)]:
                for y in (245.5, 250, 254.5):
                    if abs(x - 500) < 60:
                        z = self.surface_at(asphalt, x, y)
                        self.assertIsNotNone(z, (x, y))
                        self.assertAlmostEqual(z, 10.1, places=6)
            for y in [200 + k + .5 for k in range(0, 45, 2)]:
                for x in (497.5, 502.5):
                    if x0 <= x <= x0 + 100:
                        self.assertIsNotNone(self.surface_at(asphalt, x, y), (x, y))
        # the strips stop at the cut: no strip vertex between the node and 8 m out on the west road
        strip_x = [p[0] for tri in self.triangles(left, 'e2rf_road') for p in tri if abs(p[1] - 245) < 1e-6]
        self.assertFalse([x for x in strip_x if 492 + 1e-6 < x < 500 - 1e-6])
        # the fan is the same on both sides of the tile border x = 500
        border = [sorted((round(p[1], 4), round(p[2], 4)) for tri in self.triangles(m, 'e2rf_road')
                         for p in tri if abs(p[0] - 500) < 1e-7) for m in (left, right)]
        self.assertEqual(set(border[0]), set(border[1]))

    def test_junction_takes_the_major_road_material_and_marks_stop_at_its_mouth(self):
        # a primary through node 'n' and a residential side street, worn look: the major road is
        # 'road', the street 'road_worn'; the fan was always 'road' and the paint crossed it
        roads = [{'id': 'w', 'nodes': ['a', 'n'], 'width': 7, 'tags': {'highway': 'primary', 'sidewalk': 'no'},
                  'points': line(300, 250, 500, 250, 10)},
                 {'id': 'e', 'nodes': ['n', 'b'], 'width': 7, 'tags': {'highway': 'primary', 'sidewalk': 'no'},
                  'points': line(500, 250, 700, 250, 10)},
                 {'id': 's', 'nodes': ['n', 'c'], 'width': 5.5, 'tags': {'highway': 'residential', 'sidewalk': 'no'},
                  'points': line(500, 250, 500, 50, 10)}]
        manifest = self.build([{'roads': roads}], i=0, look={'asphalt': 'worn'})[0]
        near = lambda tri, r: math.hypot(sum(p[0] for p in tri) / 3 - 500, sum(p[1] for p in tri) / 3 - 250) < r
        self.assertTrue([t for t in self.triangles(manifest, 'e2rf_road') if near(t, 3)])
        self.assertFalse([t for t in self.triangles(manifest, 'e2rf_road_worn') if near(t, 4)])
        marks = list(self.triangles(manifest, 'e2rf_mark'))
        self.assertTrue(marks)
        # the roads are cut 0.8 x 7 = 5.6 m from the node: no paint inside the junction
        self.assertFalse([p for t in marks for p in t if math.hypot(p[0] - 500, p[1] - 250) < 5.5])
        # the residential street has no paint at all
        self.assertFalse([p for t in marks for p in t if p[1] < 240])

    def test_marks_follow_class_and_surface(self):
        def marks(tags, width=6):
            road = {'id': 'r', 'width': width, 'points': [[0, 10, 5], [100, 10, 5]], 'tags': dict(tags, sidewalk='no')}
            return list(self.triangles(self.build([{'roads': [road]}], tileSize=100, terrainStep=100)[0], 'e2rf_mark'))
        self.assertFalse(marks({'highway': 'residential'}))
        self.assertFalse(marks({'highway': 'tertiary', 'surface': 'gravel'}))
        tertiary = marks({'highway': 'tertiary'})
        # a dashed centre line (3 m in 12) and two solid edge lines
        self.assertEqual({round(sum(p[1] for p in t) / 3) for t in tertiary}, {7, 10, 13})
        self.assertFalse(marks({'highway': 'tertiary', 'lane_markings': 'no'}))
        # a one-lane roundabout ring: no lane line
        ring = marks({'highway': 'tertiary', 'junction': 'roundabout'}, width=5.5)
        self.assertFalse([t for t in ring if abs(sum(p[1] for p in t) / 3 - 10) < 1])

    def test_edge_lines_leave_the_paved_shoulder_outside(self):
        def lines(tags, width):
            road = {'id': 'r', 'width': width, 'points': [[0, 10, 5], [100, 10, 5]], 'tags': tags}
            found = self.triangles(self.build([{'roads': [road]}], tileSize=100, terrainStep=100)[0], 'e2rf_mark')
            return {round((min(p[1] for p in t) + max(p[1] for p in t)) / 2, 1) for t in found}
        # one carriageway of a dual trunk road, 2 x 3.5 m lanes: 0.5 m shoulder left, 1.5 m right
        self.assertEqual(lines({'highway': 'trunk', 'oneway': 'yes', 'lanes': '2'}, 9), {13.9, 10.5, 7.1})
        # drawn against the node order: the wide shoulder is on the other side
        self.assertEqual(lines({'highway': 'trunk', 'oneway': '-1', 'lanes': '2'}, 9), {12.9, 9.5, 6.1})
        # a measured width has no assumed shoulder
        self.assertEqual(lines({'highway': 'trunk', 'oneway': 'yes', 'lanes': '2', 'width': '9'}, 9),
                         {14.2, 10.0, 5.8})

    def test_a_gentle_bend_between_two_ways_is_joined_without_a_star(self):
        # a way split at node 'n' with a 30 degree turn: one carriageway, no wedge at the seam
        bend = [500 + 200 * math.cos(math.radians(30)), 250 + 200 * math.sin(math.radians(30))]
        roads = [{'id': 'w', 'nodes': ['a', 'n'], 'width': 7, 'tags': {'highway': 'tertiary', 'sidewalk': 'no'},
                  'points': line(300, 250, 500, 250, 10)},
                 {'id': 'e', 'nodes': ['n', 'b'], 'width': 7, 'tags': {'highway': 'tertiary', 'sidewalk': 'no'},
                  'points': line(500, 250, bend[0], bend[1], 10)}]
        manifest = self.build([{'roads': roads}], i=0)[0]
        asphalt = list(self.triangles(manifest, 'e2rf_road'))
        ux, uy = math.cos(math.radians(30)), math.sin(math.radians(30))
        for x in [490 + k * .5 for k in range(21)]:
            for y in [246.75 + k * .5 for k in range(16)]:
                # inside either carriageway by more than 5 cm
                west = x <= 500 and abs(y - 250) < 3.45
                along = (x - 500) * ux + (y - 250) * uy
                east = along >= 0 and abs(-(x - 500) * uy + (y - 250) * ux) < 3.45
                if west or east:
                    self.assertIsNotNone(self.surface_at(asphalt, x, y), (x, y))
        # the strips run to the node: a strip vertex on the bisector at the outer edge
        normal = (-math.sin(math.radians(15)), math.cos(math.radians(15)))
        mitre = 3.5 / math.cos(math.radians(15))
        corner = (500 + normal[0] * mitre, 250 + normal[1] * mitre)   # the inner edge, in tile 0
        self.assertTrue([p for t in asphalt for p in t if math.hypot(p[0] - corner[0], p[1] - corner[1]) < 1e-3])

    def test_fences_follow_the_ground_and_have_thickness(self):
        # one 400 m wall over a 6 m hump: its ends alone on the ground buried the middle
        heights = [0, 0, 0, 6, 0, 0, 0, 0, 0]
        cell = {'lines': [{'id': 'w', 'kind': 'fence', 'tags': {'barrier': 'wall'},
                           'points': [[50, 250, 0], [450, 250, 0]]}],
                'terrain': {'rect': [0, 0, 500, 500], 'nx': 3, 'ny': 3, 'heights': heights}}
        road, scene = self.build([cell])[:2]
        ground = list(self.triangles(road, 'e2rf_ground'))
        wall = list(self.triangles(scene, 'e2rf_fence_wall'))
        ys = {round(p[1], 4) for tri in wall for p in tri}
        self.assertEqual(ys, {249.9, 250.1})  # 0.2 m thick
        for x in range(60, 441, 10):
            g = self.surface_at(ground, x, 250)
            top = max(p[2] for tri in wall for p in tri if abs(p[0] - x) < 2.01)
            self.assertGreater(top - g, 1.9, x)    # a 2 m wall stands over the hump
            self.assertLess(top - g, 2.2, x)

    def test_bus_stop_on_the_carriageway_stands_beside_the_road(self):
        road = {'id': 'r', 'nodes': ['a', 'b'], 'width': 8, 'tags': {'highway': 'residential', 'sidewalk': 'both'},
                'points': [[0, 250, 0], [500, 250, 0]]}
        stop = {'id': 's', 'kind': 'stop', 'tags': {'highway': 'bus_stop'}, 'pos': [200, 250.5, 0]}
        scene = self.build([{'roads': [road], 'points': [stop]}])[1]
        shelters = [it for it in scene['items'].values() if it['kind'] == 'static' and 'busstop' in it['shape']]
        self.assertEqual(len(shelters), 1)
        pos = shelters[0]['pos']
        # right of the eastward road: beyond its 4 m half width, the 2 m sidewalk and 1.4 m more
        self.assertAlmostEqual(pos[2], 250 - 7.4)  # a Lua table: x, y, z at 1, 2, 3
        self.assertAlmostEqual(pos[1], 200.0)

    def test_building_hole_roof_and_collision_walls(self):
        rings = [[[100, 100, 0], [140, 100, 0], [140, 140, 0], [100, 140, 0]],
                 [[110, 110, 0], [130, 110, 0], [130, 130, 0], [110, 130, 0]]]
        road, scene, far, nav = self.build([{'buildings': [
            {'id': 'courtyard', 'rings': rings, 'height': 12, 'tags': {'building:material': 'brick'}}]}])
        roof = list(self.triangles(scene, 'e2rf_roof'))
        self.assertAlmostEqual(sum(map(area, roof)), 1200)
        self.assertTrue(all(p[2] == 12 for tri in roof for p in tri))
        wall_triangles = sum(len(mesh.faces) // 3 for _, mesh in self.meshes(scene)
                             if mesh.material.startswith('e2rf_wall_brk_'))
        self.assertEqual(wall_triangles, 16)
        self.assertIsNone(far)
        self.assertEqual(len(nav.segments), 0)
        self.assertFalse(road.drivable)

    def test_feature_duplicates_do_not_double_geometry_or_nav(self):
        cell = {'roads': [{'id': 'same', 'points': [[100, 100, 10], [200, 100, 10]],
                           'nodes': [1, 2], 'width': 7, 'tags': {'highway': 'residential'}}]}
        once = self.build([cell])
        twice = self.build([cell, copy.deepcopy(cell)])
        self.assertEqual(once[0].triangles, twice[0].triangles)
        self.assertEqual(len(twice[3].segments), 1)

    def test_navigation_reverses_negative_oneway_and_converts_mph(self):
        road = {'id': 'way', 'nodes': ['first', 'last'], 'width': 7,
                'points': [[0, 250, 5], [500, 250, 15]],
                'tags': {'highway': 'primary', 'oneway': '-1', 'lanes': '2', 'maxspeed': '35 mph'}}
        manifest, _, _, nav = self.build([{'roads': [road]}])
        s = nav.segments[1]
        self.assertEqual((s[2], s[3], s[4]), ('last', 'first', '++'))
        self.assertAlmostEqual(s[5], 35 * 1.609 / 3.6)
        self.assertEqual([s[k] for k in [8, 9, 10]], [500, 250, 15.1])
        coordinates = [[s[k], s[k + 1], s[k + 2]] for k in range(8, len(s) + 1, 3)]
        self.assertTrue(all(math.dist(a[:2], b[:2]) <= 80 for a, b in zip(coordinates, coordinates[1:])))
        self.assertTrue(manifest.drivable)

    def test_navigation_has_no_zero_length_edges(self):
        # repeated source points made zero-length navgraph edges; the game's random route walk
        # (traffic respawns) never got its length on them and froze the game
        road = {'id': 'r', 'nodes': ['a', 'b'], 'width': 7, 'tags': {'highway': 'residential'},
                'points': [[0, 250, 5], [100, 250, 5], [100, 250, 5], [100.1, 250, 5], [200, 250, 5]]}
        flat = {'id': 'dot', 'nodes': ['c', 'd'], 'width': 7, 'tags': {'highway': 'residential'},
                'points': [[300, 300, 5], [300, 300, 5]]}
        nav = self.build([{'roads': [road, flat]}])[3]
        segments = [nav.segments[k] for k in range(1, len(nav.segments) + 1)]
        self.assertEqual([s[1] for s in segments], ['r'])
        s = segments[0]
        points = [(s[k], s[k + 1]) for k in range(8, len(s) + 1, 3)]
        self.assertTrue(all(math.dist(p, q) >= .5 for p, q in zip(points, points[1:])))
        self.assertEqual(points[-1], (200, 250))

    def test_mesh_pieces_are_bounded_and_generation_yields(self):
        calls = []
        road, scene, _, _ = self.generator.build(self.table([]), 0, 0,
                                                self.table({'terrainStep': 10, 'pause': lambda: calls.append(1)}))
        self.assertGreater(len(calls), 50)
        self.assertGreater(len(road['items']), 1)
        for item, mesh in self.meshes(road):
            # one material per piece (each (object, material) pair costs a first draw), bounded
            self.assertLessEqual(item.triangles, 2500)
            self.assertEqual(len(item.meshes), 1)
            self.assertTrue(all(0 <= face.v < len(mesh.verts) for face in mesh.faces.values()))
        for triangle in self.triangles(road):
            self.assertTrue(all(0 <= p[0] <= 500 and 0 <= p[1] <= 500 for p in triangle))

    def test_generation_does_not_mutate_source_features(self):
        source = self.table([{'junctions': [{'id': 1, 'height': 20, 'rings': [[[0, 0], [50, 0], [50, 50], [0, 50]]]}]}])
        before = json.dumps(self.plain(source), sort_keys=True)
        first = self.generator.build(source, 0, 0, self.table({'terrainStep': 100}))[0]
        second = self.generator.build(source, 0, 0, self.table({'terrainStep': 100}))[0]
        self.assertEqual(json.dumps(self.plain(source), sort_keys=True), before)
        self.assertEqual(self.plain(first), self.plain(second))

    def test_forest_trees_are_deterministic_bounded_and_avoid_buildings(self):
        source = [{'areas': [{'id': 'forest', 'kind': 'forest',
                              'rings': [[[0, 0], [500, 0], [500, 500], [0, 500]]]}],
                   'buildings': [{'id': 'block', 'height': 30,
                                  'rings': [[[100, 100], [300, 100], [300, 300], [100, 300]]]}]}]
        first = self.build(source, terrainStep=100)[1]
        second = self.build(source, terrainStep=100)[1]
        statics = [item for item in first['items'].values() if item.kind == 'static']
        trees = [item for item in statics if 'groundcover' not in item.shape and 'rock' not in item.shape and '_bush_' not in item.shape]
        self.assertEqual(len(trees), 2400)
        self.assertTrue(any('grass' in item.shape for item in statics))
        self.assertTrue(any('_bush_' in item.shape for item in statics))
        self.assertTrue(all(not (100 < item.pos[1] < 300 and 100 < item.pos[2] < 300) for item in statics))
        self.assertEqual(self.plain(first), self.plain(second))

    def test_street_lamps_come_from_road_lighting_without_source_points(self):
        road = {'id': 'street', 'width': 7, 'points': [[0, 250, 10], [500, 250, 10]],
                'tags': {'highway': 'residential', 'lit': 'yes'}}
        scene = self.build([{'roads': [road]}], terrainStep=100)[1]
        lamps = [item for item in scene['items'].values() if item.kind == 'static' and item.shape.endswith('lamp1.dae')]
        self.assertEqual(len(lamps), 16)
        self.assertTrue(all(item.shape == '/art/shapes/objects/lamp1.dae' for item in lamps))
        self.assertTrue(all(item.decor and abs(item.pos[3] - 10.2) < 1e-8 for item in lamps))

    def test_street_props_line_sidewalks_and_footways_but_not_carriageways(self):
        # four arms meeting at a junction node (250, 250)
        roads = [{'id': arm, 'nodes': ['j', arm], 'width': 8, 'tags': {'highway': 'residential', 'sidewalk': 'both'},
                  'points': [[250, 250, 10], end]}
                 for arm, end in (('n', [250, 500, 10]), ('s', [250, 0, 10]), ('e', [500, 250, 10]), ('w', [0, 250, 10]))]
        lines = [{'id': 'walk', 'kind': 'path', 'tags': {'highway': 'footway'}, 'points': [[50, 50, 10], [50, 200, 10]]}]

        def props(**options):
            scene = self.build([{'roads': roads, 'lines': lines}], terrainStep=100, **options)[1]
            return [item for item in scene['items'].values() if item.prop]

        placed = props(propSpacing=6)
        self.assertGreater(len(placed), 250)
        self.assertTrue(all(item.kind == 'static' and item.collision == 'Collision Mesh' for item in placed))
        for item in placed:
            x, y = item.pos[1], item.pos[2]
            # off both carriageways
            self.assertFalse(abs(x - 250) < 4.2 and 0 <= y <= 500 or abs(y - 250) < 4.2 and 0 <= x <= 500, (x, y))
        walk = [item for item in placed if abs(item.pos[1] - 50) < 3 and item.pos[2] < 210]
        self.assertTrue(walk)
        self.assertTrue(all(abs(abs(item.pos[1] - 50) - 1.4) < 1e-6 for item in walk))
        # junction mouths stay clear
        self.assertFalse([item for item in placed if abs(item.pos[1] - 250) < 10 and abs(item.pos[2] - 250) < 10])
        self.assertEqual(props(propSpacing=0), [])
        self.assertEqual(props(propSpacing=6, look={'statics': 'sparse'}), [])

    def test_country_look_selects_worn_asphalt_brick_and_skips_lamps(self):
        road = {'id': 'street', 'width': 7, 'points': [[0, 250, 10], [500, 250, 10]],
                'tags': {'highway': 'residential', 'lit': 'yes', 'sidewalk': 'no'}}
        building = {'id': 'house', 'height': 12,
                    'rings': [[[100, 100], [140, 100], [140, 140], [100, 140]]]}
        look = {'block': 'postsoviet', 'asphalt': 'worn', 'buildings': 'brick', 'statics': 'none',
                'markings': 'none', 'verge': 'dirt', 'trees': 'regional'}
        road_manifest, scene = self.build([{'roads': [road], 'buildings': [building]}],
                                          terrainStep=100, look=look)[:2]
        materials = {mesh.material for _item, mesh in self.meshes(road_manifest)}
        self.assertIn('e2rf_road_worn', materials)
        self.assertNotIn('e2rf_mark', materials)
        self.assertIn('e2rf_bare_ground', materials)
        walls = [mesh.material for _item, mesh in self.meshes(scene)
                 if str(mesh.material).startswith('e2rf_wall_')]
        self.assertTrue(walls)
        self.assertTrue(all(material.startswith('e2rf_wall_brk_') for material in walls))
        lamps = [item for item in scene['items'].values()
                 if item.kind == 'static' and str(item.shape).endswith('lamp1.dae')]
        self.assertEqual(len(lamps), 0)

    def test_distant_verges_only_meet_the_near_tile_edge(self):
        # Far and horizon tiles draw no carriageway: a verge there is ground over ground and every
        # triangle is static collision. A far tile keeps the band along its edge; the horizon none.
        road = {'id': 'street', 'width': 7, 'nodes': [1, 2], 'points': [[-50, 250, 20], [550, 250, 20]],
                'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        cell = {'roads': [road], 'terrain': {'rect': [0, 0, 1000, 1000], 'nx': 5, 'ny': 5, 'heights': [20.0] * 25}}

        def verges(manifest):
            # verge pieces: small ground triangles that sit wholly in the band along the road
            return [t for t in self.triangles(manifest, 'e2rf_ground')
                    if all(238 <= p[1] <= 262 for p in t)]
        far = verges(self.build([cell], far=True)[2])
        self.assertTrue(far)
        for triangle in far:
            xs = [p[0] for p in triangle]
            self.assertTrue(min(xs) < 31 or max(xs) > 469, xs)
        horizon = self.build([cell], far=True, horizon=True)[2]
        self.assertFalse(verges(horizon))
        for item, _mesh in self.meshes(horizon):
            self.assertLessEqual(len(item.meshes), 4)

    def test_photo_loggia_facades_use_33_metre_uv_repeat(self):
        source = [{'buildings': [{'id': 'a', 'height': 33, 'tags': {'building:material': 'concrete'},
                                  'rings': [[[100, 100], [140, 100], [140, 140], [100, 140]]]}]}]
        scene = self.build(source, terrainStep=100)[1]
        walls = [mesh for _, mesh in self.meshes(scene) if mesh.material.startswith('e2rf_wall_lgg_')]
        self.assertTrue(walls)
        self.assertTrue(all(abs(mesh.uvs[k].v - 1) < 1e-8
                            for mesh in walls for k in range(1, len(mesh.verts) + 1) if mesh.verts[k].z == 33))

    def test_far_buildings_are_coarse_decoration_without_ground_or_roads(self):
        source = [{'buildings': [{'id': 'a', 'height': 30,
                                  'rings': [[[100, 100], [140, 100], [140, 140], [100, 140]]]}]}]
        road, scene, far, nav = self.build(source, far=True)
        self.assertEqual((len(road['items']), len(scene['items']), len(nav.segments)), (0, 0, 0))
        self.assertEqual(far.layer, 'far')
        self.assertTrue(all(item.decor and item.layer == 'far' for item in far['items'].values()))
        self.assertEqual(far.triangles, 10)

    def test_building_datums_match_across_independently_loaded_dem_cells(self):
        building = {'id': 'cross-cell', 'height': 12,
                    'rings': [[[950, 100, 100], [1150, 100, 100], [1150, 140, 100], [950, 140, 100]]]}
        west_cell = {'buildings': [building], 'terrain': {'rect': [0, 0, 1000, 1000],
                                                        'nx': 2, 'ny': 2, 'heights': [100] * 4}}
        east_cell = {'buildings': [building], 'terrain': {'rect': [1000, 0, 2000, 1000],
                                                        'nx': 2, 'ny': 2, 'heights': [100] * 4}}
        west = self.build([west_cell], i=1, terrainStep=100)[1]
        east = self.build([east_cell], i=2, terrainStep=100)[1]
        for manifest in [west, east]:
            roof = list(self.triangles(manifest, 'e2rf_roof'))
            self.assertTrue(roof)
            self.assertTrue(all(abs(p[2] - 112) < 1e-8 for tri in roof for p in tri))

    def test_dashed_marks_keep_source_phase_and_match_across_tile_border(self):
        source = [{'roads': [{'id': 'marked', 'width': 6, 'points': [[0, 10, 5], [100, 10, 5]],
                              'tags': {'highway': 'residential', 'lanes': '2', 'sidewalk': 'no'}}]}]
        manifests = [self.build(source, i=index, tileSize=25, terrainStep=25)[0] for index in [0, 1]]
        borders, border_v = [], []
        for manifest in manifests:
            marks = list(self.triangles(manifest, 'e2rf_mark'))
            # the quad is 1.45 x the 0.12 m paint: the worn line's paint is its middle two thirds
            self.assertAlmostEqual(sum(map(area, marks)), .84 * 1.45)
            self.assertTrue(all(abs(p[2] - 5.108) < 1e-8 for triangle in marks for p in triangle))
            borders.append({(round(y, 5), round(z, 5)) for triangle in marks for x, y, z in triangle if x == 25})
            self.assertTrue(all(item.decor for item, _ in self.meshes(manifest, 'e2rf_mark')))
            border_v.append(set())
            for x, y, _z, u, v in self.uv_corners(manifest, 'e2rf_mark'):
                # u across the line, v along it
                self.assertAlmostEqual(u, 0 if y < 10 else 1)
                if abs(x - 25) < 1e-6:
                    border_v[-1].add(round(v % 1, 4))
        self.assertEqual(borders[0], borders[1])
        self.assertEqual(borders[0], {(9.913, 5.108), (10.087, 5.108)})
        # the paint runs on over the tile border: 25 m into the road is 25 / 6.4 repeats
        self.assertEqual(border_v[0], border_v[1])
        self.assertEqual(border_v[0], {round(25 / 6.4 % 1, 4)})

    def edge_cell(self, *roads):
        # the DEM round the tile, as a pack's cells and the 40 m pad give it
        return {'roads': list(roads), 'terrain': {'rect': [-500, -500, 1500, 1500], 'nx': 5, 'ny': 5,
                                                  'heights': [20.0] * 25}}

    def test_edge_decals_lie_over_a_carriageway_edge_without_sidewalk(self):
        road = {'id': 'lane', 'width': 6, 'nodes': [1, 2], 'points': line(-50, 250, 550, 250),
                'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        manifest = self.build([self.edge_cell(road)])[0]
        corners = list(self.uv_corners(manifest, 'e2rf_edge_grass'))
        self.assertTrue(corners)
        self.assertFalse(list(self.meshes(manifest, 'e2rf_edge_dirt')))
        self.assertTrue(all(item.decor for item, _ in self.meshes(manifest, 'e2rf_edge_grass')))
        self.assertEqual({y > 250 for _x, y, *_ in corners}, {True, False})
        for x, y, z, u, v in corners:
            past = abs(y - 250) - 3          # metres past the road's edge
            # 0.6 m over the asphalt, 1.24 m over the verge; the road's edge at u = 0.38
            self.assertGreaterEqual(past, -.6 - 1e-6)
            self.assertLessEqual(past, 1.24 + 1e-6)
            self.assertAlmostEqual(u, .38 + past / 2, places=5)
            self.assertAlmostEqual(cyclic(v - (x + 50) / 8), 0, places=4)   # 8 m a repeat from the start
            if past <= 1e-6:
                self.assertAlmostEqual(z, 20.104, places=5)   # 4 mm over the road surface
            else:
                self.assertTrue(19.8 < z < 20.2, z)

    def test_main_roads_and_bare_verges_get_a_dirt_shoulder(self):
        tertiary = {'id': 'main', 'width': 7, 'nodes': [1, 2], 'points': line(-50, 250, 550, 250),
                    'tags': {'highway': 'tertiary', 'sidewalk': 'no'}}
        manifest = self.build([self.edge_cell(tertiary)])[0]
        self.assertTrue(list(self.meshes(manifest, 'e2rf_edge_dirt')))
        self.assertFalse(list(self.meshes(manifest, 'e2rf_edge_grass')))
        lane = {'id': 'lane', 'width': 6, 'nodes': [1, 2], 'points': line(-50, 250, 550, 250),
                'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        manifest = self.build([self.edge_cell(lane)], look={'verge': 'gravel'})[0]
        self.assertTrue(list(self.meshes(manifest, 'e2rf_edge_dirt')))
        self.assertFalse(list(self.meshes(manifest, 'e2rf_edge_grass')))

    def test_no_edge_decals_by_sidewalks_on_graded_roads_or_far_away(self):
        street = {'id': 'street', 'width': 7, 'nodes': [1, 2], 'points': line(-50, 250, 550, 250),
                  'tags': {'highway': 'residential', 'sidewalk': 'both'}}
        gravel = {'id': 'gravel', 'width': 4, 'nodes': [3, 4], 'points': line(-50, 100, 550, 100),
                  'tags': {'highway': 'track', 'surface': 'gravel'}}
        road, _scene, far, _nav = self.build([self.edge_cell(street, gravel)])
        for material in ('e2rf_edge_grass', 'e2rf_edge_dirt'):
            self.assertFalse(list(self.meshes(road, material)))
        lane = {'id': 'lane', 'width': 6, 'nodes': [1, 2], 'points': line(-50, 250, 550, 250),
                'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        far = self.build([self.edge_cell(lane)], far=True)[2]
        self.assertFalse(list(self.meshes(far, 'e2rf_edge_grass')))

    def test_untagged_streets_get_sidewalks_only_where_built_up(self):
        # houses 16 x 16 m every 20 m both sides of the west half (~17 % of the ground round the
        # street), nothing along the east half: sidewalks in the town, grass edges past it
        houses = [{'id': f'h{side}{x}', 'height': 6,
                   'rings': [[[x, 250 + side * 10], [x + 16, 250 + side * 10], [x + 16, 250 + side * 26],
                              [x, 250 + side * 26]]]}
                  for side in (1, -1) for x in range(-100, 200, 20)]
        street = {'id': 'street', 'width': 7, 'nodes': [1, 2], 'points': line(-50, 250, 550, 250),
                  'tags': {'highway': 'residential'}}
        cell = dict(self.edge_cell(street), buildings=houses)
        road = self.build([cell])[0]
        curb = list(self.triangles(road, 'e2rf_curb'))
        edges = list(self.triangles(road, 'e2rf_edge_grass'))
        self.assertTrue(curb and edges)
        self.assertLess(max(p[0] for t in curb for p in t), 300)
        self.assertGreaterEqual(min(p[0] for t in edges for p in t), 140)
        # a village (12 m houses, ~10 %): no sidewalk on its streets, one along its main road
        village = [dict(h, rings=[[[x, y] for x, y in ((r[0][0], r[0][1]), (r[0][0] + 12, r[0][1]),
                                                       (r[0][0] + 12, r[0][1] + (r[2][1] - r[0][1]) * .75),
                                                       (r[0][0], r[0][1] + (r[2][1] - r[0][1]) * .75))]])
                   for h in houses for r in [h['rings'][0]]]
        road = self.build([dict(self.edge_cell(street), buildings=village)])[0]
        self.assertFalse(list(self.triangles(road, 'e2rf_curb')))
        main = dict(street, tags={'highway': 'tertiary'})
        road = self.build([dict(self.edge_cell(main), buildings=village)])[0]
        self.assertTrue(list(self.triangles(road, 'e2rf_curb')))
        # the tags still decide: no sidewalk on 'no' however built up
        street['tags']['sidewalk'] = 'no'
        road = self.build([dict(self.edge_cell(street), buildings=houses)])[0]
        self.assertFalse(list(self.triangles(road, 'e2rf_curb')))

    def test_curb_runs_along_the_top_row_of_the_trim_sheet(self):
        street = {'id': 'street', 'width': 7, 'nodes': [1, 2], 'points': line(-50, 250, 550, 250),
                  'tags': {'highway': 'residential', 'sidewalk': 'both'}}
        manifest = self.build([self.edge_cell(street)])[0]
        corners = list(self.uv_corners(manifest, 'e2rf_curb'))
        self.assertTrue(corners)
        for x, y, _z, u, v in corners:
            # v across: .005 at the carriageway, .195 at the sidewalk; u along, 2 m a repeat
            self.assertAlmostEqual(v, .005 + (abs(y - 250) - 3.5) / .25 * .19, places=5)
            self.assertAlmostEqual(cyclic(u - (x + 50) / 2), 0, places=4)

    def test_edges_are_cut_by_a_crossing_carriageway(self):
        east = {'id': 'east', 'width': 6, 'nodes': [1, 2], 'points': line(-50, 250, 550, 250),
                'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        north = {'id': 'north', 'width': 6, 'nodes': [3, 4], 'points': line(250, -50, 250, 550),
                 'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        manifest = self.build([self.edge_cell(east, north)])[0]
        triangles = list(self.triangles(manifest, 'e2rf_edge_grass'))
        self.assertTrue(triangles)
        for triangle in triangles:
            cx, cy = (sum(p[k] for p in triangle) / 3 - 250 for k in (0, 1))
            # nothing of either road's edge decal lies on the other carriageway
            self.assertFalse(abs(cx) < 2.95 and abs(cy) < 4.45, (cx, cy))
            self.assertFalse(abs(cy) < 2.95 and abs(cx) < 4.45, (cx, cy))

    def test_no_edge_decals_when_the_game_lacks_their_maps(self):
        # an older BeamNG: world.lua loads the fallback materials, the generator draws no strip
        self.lua.execute('FS = {fileExists = function(_, path) return not path:find("decalroad", 1, true) end}')
        lane = {'id': 'lane', 'width': 6, 'nodes': [1, 2], 'points': line(-50, 250, 550, 250),
                'tags': {'highway': 'residential', 'lanes': '2', 'sidewalk': 'no'}}
        manifest = self.build([self.edge_cell(lane)])[0]
        self.assertFalse(list(self.meshes(manifest, 'e2rf_edge_grass')))
        self.assertTrue(list(self.meshes(manifest, 'e2rf_mark')))

    def test_parking_lots_produce_cars_with_body_glass_and_tyre_atlas_cells(self):
        source = [{'areas': [{'id': 'parking', 'kind': 'paved', 'tags': {'amenity': 'parking'},
                              'rings': [[[10, 10], [70, 10], [70, 50], [10, 50]]]}]}]
        scene = self.build(source, terrainStep=100)[1]
        cars = list(self.meshes(scene, 'e2rf_car'))
        self.assertTrue(cars)
        atlas_cells = set()
        for item, mesh in cars:
            self.assertTrue(item.decor)
            for uv in mesh.uvs.values():
                atlas_cells.add(round(uv.u * 16 - .5))
                self.assertEqual(uv.v, .5)
        self.assertIn(8, atlas_cells)  # glass
        self.assertIn(9, atlas_cells)  # tyres
        self.assertTrue(any(0 <= cell <= 7 for cell in atlas_cells))
        self.assertTrue(all(10 <= x <= 70 and 10 <= y <= 50
                            for triangle in self.triangles(scene, 'e2rf_car') for x, y, z in triangle))

    def test_gabled_and_hipped_roofs_cover_footprint_and_rise_above_eaves(self):
        for shape in ['gabled', 'hipped']:
            with self.subTest(shape=shape):
                source = [{'buildings': [{'id': 'house', 'height': 6, 'tags': {'building': 'house', 'roof:shape': shape},
                                          'rings': [[[100, 100, 10], [120, 100, 10], [120, 110, 10], [100, 110, 10]]]}]}]
                scene = self.build(source, terrainStep=100)[1]
                roof = list(self.triangles(scene, 'e2rf_roof_tile'))
                self.assertTrue(roof)
                # 0.5 m eaves round the 20 x 10 m footprint, dropping by the pitch below the wall top
                self.assertAlmostEqual(sum(map(area, roof)), 21 * 11)
                self.assertGreater(max(p[2] for triangle in roof for p in triangle), 16)
                eaves = [p for triangle in roof for p in triangle if p[1] < 100]
                self.assertTrue(eaves and all(abs(p[1] - 99.5) < 1e-6 and p[2] < 16 for p in eaves))
                self.assertEqual(list(self.triangles(scene, 'e2rf_roof')), [])

    def test_guessed_heights_make_village_houses_one_floor_with_a_pitched_roof(self):
        # the pack's 9 m for a building with no height or levels tag (build_country.py)
        def house(bid, w, d, x=100, **tags):
            return {'id': bid, 'height': 9, 'tags': {'building': 'yes', **tags},
                    'rings': [[[x, 100, 10], [x + w, 100, 10], [x + w, 100 + d, 10], [x, 100 + d, 10]]]}
        scene = self.build([{'buildings': [house('hut', 10, 9), house('levels', 10, 9, x=200, **{'building:levels': '3'}),
                                           house('block', 40, 30, x=300)]}], terrainStep=100)[1]
        heights = {}
        for item, mesh in self.meshes(scene):
            if str(mesh.material).startswith(('e2rf_wall_', 'e2rf_hw_', 'e2rf_plinth')):
                for k in range(1, len(mesh.verts) + 1):
                    v = mesh.verts[k]
                    x = v.x + item.pos[1]
                    key = 'hut' if x < 150 else 'levels' if x < 250 else 'block'
                    heights.setdefault(key, set()).add(round(v.z + item.pos[3], 4))
        # one floor; its roof rises over the 4.5 m half width at a house's 26-38 degrees
        self.assertIn(13.1, heights['hut'])
        roof = [p[2] for name in ('e2rf_roof_tile', 'e2rf_roof_sheet', 'e2rf_roof_metal', 'e2rf_roof_mtile_red',
                                  'e2rf_roof_mtile_brown', 'e2rf_roof_mtile_green')
                for t in self.triangles(scene, name) for p in t]
        ridge = max(roof)
        self.assertGreaterEqual(ridge, 13.1 + 4.5 * math.tan(math.radians(26)) - 1e-6)
        self.assertLessEqual(ridge, 13.1 + 4.5 * math.tan(math.radians(38)) + 1e-6)
        self.assertLessEqual(max(heights['hut']), ridge + 1e-6)     # gables, if any, up to the ridge
        self.assertEqual(max(heights['levels']), 19)          # tagged: the pack's height stays
        self.assertEqual(max(heights['block']), 19)           # 1200 m2: no better guess
        pitched = [p for name in ('e2rf_roof_tile', 'e2rf_roof_sheet', 'e2rf_roof_metal')
                   for t in self.triangles(scene, name) for p in t]
        self.assertTrue(pitched and all(p[0] < 150 for p in pitched))
        # a house's walls are plain (hw_*): its windows and door are their own quads
        self.assertTrue(any(str(m.material).startswith('e2rf_hw_') for _i, m in self.meshes(scene)))
        self.assertTrue(list(self.triangles(scene, 'e2rf_door_house')))

    def test_houses_get_windows_on_each_floor_and_one_door(self):
        house = {'id': 'h', 'height': 6, 'tags': {'building': 'house', 'building:levels': '2'},
                 'rings': [[[100, 100, 10], [112, 100, 10], [112, 108, 10], [100, 108, 10]]]}
        scene = self.build([{'buildings': [house]}], terrainStep=100)[1]
        windows = [t for name in ('e2rf_win_pvc', 'e2rf_win_wood') for t in self.triangles(scene, name)]
        doors = list(self.triangles(scene, 'e2rf_door_house'))
        # 3 windows a floor on the 12 m walls, 2 on the 8 m ones, two floors; one slot is the door
        self.assertEqual((len(windows) // 2, len(doors) // 2), (19, 1))
        for t in windows + doors:
            for x, y, z in t:
                outside = min(abs(x - 100), abs(x - 112), abs(y - 100), abs(y - 108))
                self.assertAlmostEqual(outside, .03, places=6)     # 3 cm out from the wall
                self.assertTrue(10 <= z <= 16 - .15, z)
        # the door is on a 12 m wall, on the ground
        self.assertTrue(all(abs(y - 99.97) < 1e-6 or abs(y - 108.03) < 1e-6 for t in doors for _x, y, _z in t))
        self.assertAlmostEqual(min(z for t in doors for _x, _y, z in t), 10.1)

    def test_post_soviet_roofs_mix_slate_and_metal_tile_with_uv_down_the_slope(self):
        houses = [{'id': f'h{k}', 'height': 4, 'tags': {'building': 'house'},
                   'rings': [[[k * 30, 100, 10], [k * 30 + 12, 100, 10], [k * 30 + 12, 108, 10], [k * 30, 108, 10]]]}
                  for k in range(30)]
        kinds = set()
        for country in ('ukraine', 'germany'):
            scene = self.build([{'buildings': houses}], terrainStep=100, tileSize=1000, country=country)[1]
            roofs = {m.material for _i, m in self.meshes(scene) if str(m.material).startswith('e2rf_roof_')}
            kinds.add(frozenset(roofs))
            if country == 'germany':
                self.assertEqual(roofs, {'e2rf_roof_tile'})
            else:
                self.assertTrue({'e2rf_roof_sheet', 'e2rf_roof_mtile_red'} <= roofs, roofs)
                # u along the 12 m ridge (x), v down the 4 m half width: the corrugation runs downhill
                for x, y, z, u, v in self.uv_corners(scene, 'e2rf_roof_sheet'):
                    self.assertGreaterEqual(v, -1e-9)
                    if abs(y - 104) < 1e-6:
                        self.assertAlmostEqual(v, 0)
        # a roof:colour tag picks the painted metal of that colour
        tagged = dict(houses[0], tags={'building': 'house', 'roof:colour': 'green'})
        scene = self.build([{'buildings': [tagged]}], terrainStep=100)[1]
        self.assertTrue(list(self.triangles(scene, 'e2rf_roof_mtile_green')))

    def test_garage_rows_get_doors_and_houses_a_plinth(self):
        row = {'id': 'row', 'height': 9, 'tags': {'building': 'garages'},
               'rings': [[[100, 100, 10], [160, 100, 10], [160, 106, 10], [100, 106, 10]]]}
        brick = {'id': 'b', 'height': 6, 'tags': {'building': 'house', 'building:material': 'brick'},
                 'rings': [[[200, 100, 10], [212, 100, 10], [212, 110, 10], [200, 110, 10]]]}
        scene = self.build([{'buildings': [row, brick]}], terrainStep=100)[1]
        doors = [t for name in ('e2rf_door_garage', 'e2rf_door_rust') for t in self.triangles(scene, name)]
        # a door a 3.1 m bay along the 60 m walls (19 each side), 2.2 m high, 2 cm out from them
        self.assertEqual(len(doors), 2 * 19 * 2)
        self.assertTrue(all(abs(p[1] - 99.98) < 1e-6 or abs(p[1] - 106.02) < 1e-6 for t in doors for p in t))
        self.assertAlmostEqual(max(p[2] for t in doors for p in t), 12.2)
        widths = {round(max(p[0] for p in t) - min(p[0] for p in t), 3) for t in doors}
        self.assertEqual(widths, {2.5})
        # the walls behind them, and the row's ends, are blank cement 2.7 m high
        cement = list(self.triangles(scene, 'e2rf_plinth'))
        row = [t for t in cement if all(p[0] < 200 for p in t)]
        self.assertAlmostEqual(max(p[2] for t in row for p in t), 12.7)
        # the house stands on a 0.35 m plinth
        plinth = [t for name in ('e2rf_plinth', 'e2rf_plinth_brown') for t in self.triangles(scene, name)
                  if all(p[0] >= 200 for p in t)]
        self.assertTrue(plinth)
        self.assertAlmostEqual(max(p[2] for t in plinth for p in t), 10.35)

    def test_courtyard_stays_open_even_when_pitched_roof_is_requested(self):
        source = [{'buildings': [{'id': 'courtyard', 'height': 6, 'tags': {'roof:shape': 'gabled'},
                                  'rings': [[[100, 100], [140, 100], [140, 140], [100, 140]],
                                            [[110, 110], [130, 110], [130, 130], [110, 130]]]}]}]
        scene = self.build(source, terrainStep=100)[1]
        self.assertEqual(list(self.triangles(scene, 'e2rf_roof_tile')), [])
        self.assertAlmostEqual(sum(map(area, self.triangles(scene, 'e2rf_roof'))), 1200)

    def test_sea_below_zero_gets_a_water_plane_only_where_ground_dips(self):
        def cell(heights):
            return {'terrain': {'rect': [0, 0, 1000, 1000], 'nx': 2, 'ny': 2, 'heights': heights}}
        for far in (False, True):
            with self.subTest(far=far):
                _, scene, farScene, _ = self.build([cell([20, 20, 20, 20])], far=far, seaLevel=20)
                scene = farScene if far else scene
                water = list(self.triangles(scene, 'e2rf_water'))
                self.assertEqual(len(water), 2)  # open sea: one quad for the whole tile
                self.assertTrue(all(p[2] == 20.3 for t in water for p in t))
                self.assertAlmostEqual(sum(map(area, water)), 500 * 500)
                _, scene, farScene, _ = self.build([cell([30, 30, 30, 30])], far=far, seaLevel=20)
                self.assertEqual(list(self.triangles(farScene if far else scene, 'e2rf_water')), [])
        # a coast (west under the sea, east on land): water over the western quads only
        _, scene, *_ = self.build([cell([20, 30, 20, 30])], seaLevel=20)
        water = list(self.triangles(scene, 'e2rf_water'))
        self.assertGreater(len(water), 2)
        self.assertLess(max(p[0] for t in water for p in t), 500)
        _, scene, *_ = self.build([cell([20, 20, 20, 20])])  # no seaLevel (v1 data): no sea
        self.assertEqual(list(self.triangles(scene, 'e2rf_water')), [])

    def corners(self, manifest, material=None):
        found = []
        for item, mesh in self.meshes(manifest, material):
            for k in range(1, len(mesh.faces) + 1, 3):
                for index in range(k, k + 3):
                    face = mesh.faces[index]
                    p = mesh.verts[face.v + 1]
                    n = mesh.normals[face.n + 1]
                    found.append((p.x + item.pos[1], p.y + item.pos[2], p.z + item.pos[3], n.x, n.y, n.z))
        return found

    def border(self, manifest, x, material='e2rf_ground', surface=False):
        pts = {}
        for px, py, pz, nx, ny, nz in self.corners(manifest, material):
            # A skirt shares the data-edge XY and would hide the surface sample.
            if abs(px - x) < 1e-5 and not (surface and abs(nz) < 0.05):
                pts[round(py, 3)] = (round(pz, 4), round(nx, 4), round(ny, 4), round(nz, 4))
        return pts

    def test_far_ground_keeps_a_hill_and_a_valley(self):
        def cell(heights):
            return {'terrain': {'rect': [0, 0, 1000, 1000], 'nx': 5, 'ny': 5, 'heights': heights}}
        hill = [20.0] * 25
        hill[6] = 400  # grid point (250 m, 250 m)
        road, scene, far, nav = self.build([cell(hill)], far=True)
        self.assertEqual((len(road['items']), len(scene['items']), len(nav.segments)), (0, 0, 0))
        self.assertEqual(far.layer, 'far')
        ground = list(self.triangles(far, 'e2rf_ground'))
        self.assertAlmostEqual(sum(map(area, ground)), 500 * 500, delta=1)
        # (0, 0) is a border vertex. (200, 200) is a coarse vertex on the slope up to the peak.
        self.assertAlmostEqual(self.surface_at(ground, 0, 0), 19.75, places=2)
        self.assertAlmostEqual(self.surface_at(ground, 200, 200), 262.95, places=2)
        self.assertGreater(self.surface_at(ground, 250, 250), 200)
        valley = [80.0] * 25
        valley[6] = 5
        low = list(self.triangles(self.build([cell(valley)], far=True)[2], 'e2rf_ground'))
        self.assertLess(self.surface_at(low, 200, 200), self.surface_at(low, 0, 0))

    def test_far_ridge_normals_tilt_away_from_the_crest(self):
        heights = [300.0 if ix == 1 else 20.0 for iy in range(5) for ix in range(5)]
        cell = {'terrain': {'rect': [0, 0, 1000, 1000], 'nx': 5, 'ny': 5, 'heights': heights}}
        far = self.build([cell], far=True)[2]
        left = [n for x, y, z, *n in self.corners(far, 'e2rf_ground') if abs(x - 200) < 1e-4 and abs(y - 200) < 1e-4]
        right = [n for x, y, z, *n in self.corners(far, 'e2rf_ground') if abs(x - 300) < 1e-4 and abs(y - 200) < 1e-4]
        self.assertTrue(left and right)
        self.assertLess(left[0][0], 0)
        self.assertGreater(right[0][0], 0)

    def test_near_and_far_share_ground_on_a_sloping_road(self):
        heights = [20.0 + ix * 20 for iy in range(5) for ix in range(5)]
        cell = {'roads': [{'id': 'road', 'nodes': [1, 2], 'width': 10,
                           'tags': {'highway': 'residential', 'sidewalk': 'no'},
                           'points': [[0, 250, 10], [1000, 250, 30]]}],
                'terrain': {'rect': [0, 0, 1000, 1000], 'nx': 5, 'ny': 5, 'heights': heights}}
        near = self.border(self.build([cell], i=0)[0], 500, surface=True)
        far = self.border(self.build([cell], i=1, far=True)[2], 500, surface=True)
        self.assertTrue(near and far)
        self.assertEqual(near, far)
        # x = 500 is DEM column 60 m. Away from the road the surface is that minus groundDrop.
        self.assertAlmostEqual(near[0][0], 59.75, places=2)
        self.assertNotAlmostEqual(near[250][0], near[0][0], places=2)

    def test_negative_tiles_share_the_ground_edge(self):
        cell = {'terrain': {'rect': [-1000, -1000, 0, 0], 'nx': 2, 'ny': 2, 'heights': [10, 40, 10, 40]}}
        left = self.border(self.build([cell], i=-2, j=-1, far=True)[2], -500)
        right = self.border(self.build([cell], i=-1, j=-1, far=True)[2], -500)
        self.assertTrue(left)
        self.assertEqual(left, right)

    def test_shared_dem_edge_does_not_depend_on_cell_order(self):
        low = {'terrain': {'rect': [0, 0, 500, 500], 'nx': 2, 'ny': 2, 'heights': [10, 10, 10, 10]}}
        high = {'terrain': {'rect': [500, 0, 1000, 500], 'nx': 2, 'ny': 2, 'heights': [80, 80, 80, 80]}}
        for cells in ([low, high], [high, low]):
            ground = list(self.triangles(self.build(cells, far=True)[2], 'e2rf_ground'))
            self.assertAlmostEqual(self.surface_at(ground, 500, 250), 9.75, places=2)

    def test_missing_dem_is_omitted_instead_of_a_zero_cliff(self):
        cell = {'terrain': {'rect': [0, 0, 400, 500], 'nx': 2, 'ny': 2, 'heights': [50, 50, 50, 50]}}
        far = self.build([cell], far=True)[2]
        verts = self.corners(far, 'e2rf_ground')
        self.assertTrue(all(v[0] <= 400 + 1e-4 for v in verts))
        self.assertTrue(all(abs(v[2]) > 1 for v in verts))
        dropped = [v for v in verts if v[2] < 40]
        self.assertTrue(dropped)
        for x, y, z, *_ in dropped:
            self.assertTrue(abs(x) < 1e-3 or abs(x - 400) < 1e-3 or abs(y) < 1e-3 or abs(y - 500) < 1e-3)

    def test_horizon_mesh_is_ground_without_buildings_or_trees(self):
        source = [{'buildings': [{'id': 'a', 'height': 30,
                                  'rings': [[[100, 100], [140, 100], [140, 140], [100, 140]]]}],
                   'areas': [{'id': 'wood', 'kind': 'forest',
                              'rings': [[[0, 0], [500, 0], [500, 500], [0, 500]]]}],
                   'terrain': {'rect': [0, 0, 1000, 1000], 'nx': 2, 'ny': 2, 'heights': [40, 40, 40, 40]}}]
        road, scene, horizon, nav = self.build(source, horizon=True)
        self.assertEqual(horizon.layer, 'horizon')
        self.assertEqual((len(road['items']), len(scene['items']), len(nav.segments)), (0, 0, 0))
        self.assertTrue(list(self.triangles(horizon, 'e2rf_ground')))
        self.assertFalse(any(item.kind == 'static' for item in horizon['items'].values()))
        self.assertTrue(all(item.layer == 'horizon' and item.collision == 'None'
                            for item in horizon['items'].values()))

    def test_far_woodland_has_sparse_decorative_canopy(self):
        source = [{'areas': [{'id': 'wood', 'kind': 'forest',
                              'rings': [[[0, 0], [500, 0], [500, 500], [0, 500]]]}]}]
        far = self.build(source, far=True)[2]
        trees = [item for item in far['items'].values() if item.kind == 'static']
        self.assertGreater(len(trees), 40)
        self.assertLessEqual(len(trees), 800)
        self.assertTrue(all(item.decor and item.layer == 'far' for item in trees))

    def test_far_tiles_keep_fences_and_horizon_does_not(self):
        cell = {'lines': [{'id': 'w', 'kind': 'fence', 'tags': {'barrier': 'wall'},
                           'points': [[50, 250, 0], [450, 250, 0]]}]}
        far = self.build([cell], far=True)[2]
        self.assertTrue(list(self.triangles(far, 'e2rf_fence_wall')))
        self.assertFalse(list(self.triangles(far, 'e2rf_footway')))
        horizon = self.build([cell], horizon=True)[2]
        self.assertFalse(list(self.triangles(horizon, 'e2rf_fence_wall')))


if __name__ == '__main__':
    unittest.main()
