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


# plan bounds (x0, x1, y0, y1) of the stock street props, from the installed DAE geometry
PROP_BOUNDS = {'bollard_hoop_grey.dae': (-.518, .518, -.175, .175), 'bollard_yellow.dae': (-.2, .2, -.2, .2),
               'bollard_hoop_red.dae': (-.518, .518, -.175, .175),
               'garbage_bin_a.dae': (-.253, .253, -.235, .26), 'garbage_bin_b.dae': (-.253, .253, -.235, .321),
               'clutter_city_bench_wood.dae': (-1, 1, -.357, .205), 'planterbox.dae': (-.46, .46, -.46, .46),
               'clutter_city_bike_stand.dae': (-2.079, 2.079, -.321, .321), 'hydrant1.dae': (-.326, .326, -.377, .377),
               'postbox_blue.dae': (-.335, .249, -.32, .32), 'clutter_city_bin_round.dae': (-.348, .348, -.348, .348),
               'italy_clutter_metal_bin.DAE': (-.171, .171, -.171, .171),
               'italy_clutter_metal_bin_small.DAE': (-.1, .1, -.1, .1),
               'italy_clutter_dumpster.DAE': (-.783, .783, -.414, .414),
               'italy_clutter_big_dustbin.DAE': (-.356, .347, -.367, .34), 'clutter_city_bollard_concrete.dae': (-.385, .385, -.385, .385),
               'ind_dumpster_full.DAE': (-1.516, 1.501, -.818, .818), 'ind_dumpster_empty.DAE': (-1.516, 1.501, -.818, .818),
               'clutter_city_wood_stool.dae': (-.294, .294, -.294, .294),
               'clutter_city_wood_table_small.dae': (-.291, .291, -.435, .435),
               'clutter_city_wood_table.dae': (-.291, .291, -.785, .785),
               'clutter_city_chalkboard_sign.dae': (-.234, .234, -.363, .363),
               'clutter_barrels_red.dae': (-.297, .297, -.297, .297),
               'clutter_barrels_white.dae': (-.297, .297, -.297, .297),
               's_wood_crate_closed.dae': (-.785, .785, -1.502, 1.502),
               's_wheelbarrow.dae': (-.936, .910, -.384, .391),
               'hr_plasticbarrier.DAE': (-.741, .741, -.27, .27)}
# a paved retail frontage under the test tile: its footways take the street's furniture
RETAIL = {'id': 'retail', 'kind': 'paved', 'tags': {'landuse': 'retail'},
          'rings': [[[-50, -50], [550, -50], [550, 550], [-50, 550]]]}


def prop_outline(x, y, yaw, shape, step=.05):
    """Points every `step` m round a prop's plan rectangle; yaw turns local X to (cos, -sin) (BeamNG)."""
    x0, x1, y0, y1 = PROP_BOUNDS[shape.rsplit('/', 1)[-1]]
    c, s = math.cos(yaw), math.sin(yaw)
    local = []
    for k in range(int((x1 - x0) / step) + 1):
        local += [(x0 + k * step, y0), (x0 + k * step, y1)]
    for k in range(int((y1 - y0) / step) + 1):
        local += [(x0, y0 + k * step), (x1, y0 + k * step)]
    local += [(x1, y0), (x1, y1)]
    return [(x + lx * c + ly * s, y - lx * s + ly * c) for lx, ly in local]


def segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1])


def outline_clearance(outline, points):
    """The least distance from a prop's outline to a polyline's axis."""
    return min(segment_distance(p, a, b) for p in outline for a, b in zip(points, points[1:]))


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
        def walls(tags, highway='trunk'):
            road = {'id': 'b', 'nodes': ['a', 'b'], 'width': 8, 'tags': dict(tags, highway=highway, sidewalk='no'),
                    'points': [[0, 250, 20], [500, 250, 20]]}
            return list(self.triangles(self.build([{'roads': [road]}])[1], 'e2rf_fence_wall'))
        self.assertEqual(walls({}), [])
        deck = walls({'bridge': 'viaduct', 'layer': '1'})
        self.assertTrue(deck)
        lift = 20 + .1                                                # ROAD_LIFT
        flat = [t for t in deck if max(p[2] for p in t) - min(p[2] for p in t) < 1e-6]
        # the soffit: a main road's girder deck 1.5 m deep; a street's slab 1.2 m
        self.assertAlmostEqual(min(p[2] for t in flat for p in t), lift - 1.5, places=2)
        street = walls({'bridge': 'yes'}, 'tertiary')
        self.assertAlmostEqual(min(p[2] for t in street for p in t if p[2] > 15), lift - 1.2, places=2)
        zs = [p[2] for t in deck for p in t]
        ys = [p[1] for t in deck for p in t]
        self.assertAlmostEqual(max(zs), lift + .9, places=2)         # the parapet's top
        self.assertLess(min(zs), 0)                                   # piers down into the ground
        self.assertAlmostEqual(max(ys), 254 + .3, places=3)          # the abutments, a parapet wider
        self.assertAlmostEqual(min(ys), 246 - .3, places=3)
        self.assertEqual(walls({'tunnel': 'building_passage'}), [])

    def test_side_by_side_decks_keep_parapets_off_each_other(self):
        # Kyiv, Povitrianykh Syl: two 11.5 m oneway decks 9.7 m apart overlap in plan; each one's
        # parapet stood on the other's carriageway and stopped the car
        def deck(way, y, step=0.):
            return {'id': way, 'nodes': [way + 'a', way + 'b'], 'width': 11.5,
                    'tags': {'highway': 'primary', 'oneway': 'yes', 'sidewalk': 'no', 'bridge': 'yes', 'layer': '1'},
                    'points': [[0, y, 20 + step], [500, y, 20 + step]]}

        def parapets(roads):
            tops = [t for t in self.triangles(self.build([{'roads': roads}])[1], 'e2rf_fence_wall')
                    if all(abs(p[2] - 21.0) < .02 for p in t)]                  # the parapet tops
            return sorted({round(p[1], 1) for t in tops for p in t})
        pair = parapets([deck('n', 254.85), deck('s', 245.15)])
        self.assertTrue(pair)
        # deck edges: 239.4 / 250.9 and 249.1 / 260.6; only the outer two keep a parapet
        self.assertFalse([y for y in pair if 240 < y < 260], pair)
        self.assertTrue([y for y in pair if y > 260] and [y for y in pair if y < 240], pair)
        # a deck 5 m higher (a stacked bridge) is not the same surface: both keep their parapets
        stacked = parapets([deck('n', 254.85), deck('s', 245.15, step=5)])
        self.assertTrue([y for y in stacked if 245 < y < 255])

    def test_side_by_side_bridges_are_one_deck(self):
        # a median of a few metres is one slab: asphalt and soffit cross the gap, parapets
        # only on the outside. Thirty metres apart stays two decks.
        def bridge(name, y0, y1=None, width=8):
            y1 = y0 if y1 is None else y1
            return {'id': name, 'nodes': [name + 'a', name + 'b'], 'width': width,
                    'tags': {'highway': 'trunk', 'oneway': 'yes', 'bridge': 'yes', 'layer': '1', 'sidewalk': 'no'},
                    'points': line(0, y0, 400, y1, 20)}

        def built(roads):
            road, walls = self.build([{'roads': roads}])[:2]
            return (list(self.triangles(road, 'e2rf_road_major')),
                    list(self.triangles(walls, 'e2rf_fence_wall')))

        asphalt, walls = built([bridge('s', 250), bridge('n', 262)])
        self.assertAlmostEqual(self.surface_at(asphalt, 200, 256), 20.1, places=2)  # the gap is paved
        self.assertIsNotNone(self.surface_at(walls, 200, 256))                        # one soffit across it
        tops = [p[1] for t in walls for p in t if all(abs(q[2] - 21.0) < .02 for q in t)]
        self.assertTrue(any(y < 247 for y in tops) and any(y > 265 for y in tops), tops)
        self.assertFalse([y for y in tops if 250 < y < 262], tops)
        # a converging ramp is not one deck: the wide end keeps a hole between the soffits
        asphalt, walls = built([bridge('s', 250), bridge('n', 290, 258)])
        self.assertIsNone(self.surface_at(walls, 40, 268))
        # far enough apart to be two bridges
        _, walls = built([bridge('s', 250), bridge('n', 280)])
        self.assertIsNone(self.surface_at(walls, 200, 265))
        tops = [p[1] for t in walls for p in t if all(abs(q[2] - 21.0) < .02 for q in t)]
        self.assertTrue(any(250 < y < 258 for y in tops) and any(272 < y < 280 for y in tops), tops)

    def test_staggered_carriageway_bridges_leave_no_hole_past_the_longer_ones_end(self):
        # The united slab runs along the host, the longer bridge, and takes the other only where it
        # runs beside it; a deck sticking out past the host's end had its own asphalt suppressed and
        # no slab: a hole with the lane markings floating over it (Tallinna ringtee, 59.3126,
        # 24.7376). Such a pair stays two decks, each whole.
        def bridge(name, x0, x1, y):
            return {'id': name, 'nodes': [name + 'a', name + 'b'], 'width': 8,
                    'tags': {'highway': 'trunk', 'oneway': 'yes', 'bridge': 'yes', 'layer': '1', 'sidewalk': 'no'},
                    'points': line(x0, y, x1, y, 20)}
        for south, north in (((0, 300), (120, 420)), ((0, 300), (120, 400)), ((0, 320), (120, 400))):
            road, walls = self.build([{'roads': [bridge('s', *south, 250), bridge('n', *north, 262)]}])[:2]
            asphalt = list(self.triangles(road, 'e2rf_road_major'))
            walls = list(self.triangles(walls, 'e2rf_fence_wall'))
            for (x0, x1), y in ((south, 250), (north, 262)):
                for x in (x0 + 10, (x0 + x1) // 2, x1 - 10):
                    self.assertAlmostEqual(self.surface_at(asphalt, x, y), 20.1, places=2, msg=(south, north, x, y))
                    self.assertIsNotNone(self.surface_at(walls, x, y), (south, north, x, y))   # and a soffit
        # beside each other along the whole length they are still one deck
        road, walls = self.build([{'roads': [bridge('s', 0, 300, 250), bridge('n', 20, 280, 262)]}])[:2]
        self.assertIsNotNone(self.surface_at(list(self.triangles(walls, 'e2rf_fence_wall')), 150, 256))

    def test_a_bridge_line_loses_a_spike_and_keeps_a_bend(self):
        pts = line(0, 250, 400, 250, 20)
        for p in pts:
            if abs(p[0] - 200) < 1:
                p[1] = 252
        road = {'id': 'b', 'nodes': ['a', 'c'], 'width': 8, 'points': pts,
                'tags': {'highway': 'trunk', 'bridge': 'yes', 'layer': '1', 'sidewalk': 'no'}}
        asphalt = list(self.triangles(self.build([{'roads': [road]}])[0], 'e2rf_road_major'))
        edge = [p[1] for t in asphalt for p in t if 190 < p[0] < 210]
        self.assertTrue(edge)
        # a 2 m spike would put the edge at 256; two capped pulls bring it to about 255
        self.assertLess(max(edge), 255.6)
        self.assertGreater(max(edge), 254.4)
        r, length, x0, y0 = 400, 200, 200, 300
        n = math.ceil(length / 20)
        arc = []
        for k in range(n + 1):
            ang = (k / n - .5) * (length / r)
            arc.append([x0 + r * math.sin(ang), y0 - r * (1 - math.cos(ang)), 20])
        curve = {'id': 'c', 'nodes': ['a', 'b'], 'width': 8, 'points': arc,
                 'tags': {'highway': 'trunk', 'bridge': 'yes', 'layer': '1', 'sidewalk': 'no'}}
        asphalt = list(self.triangles(self.build([{'roads': [curve]}])[0], 'e2rf_road_major'))
        self.assertIsNotNone(self.surface_at(asphalt, x0, y0))          # the crown stays on the arc
        self.assertIsNone(self.surface_at(asphalt, x0, y0 + 8))

    def test_a_deck_is_not_raised_by_the_other_carriageways_approach(self):
        # Two one-way bridges of a dual carriageway, staggered, their roads joined only far away.
        # Each deck's overhang reaches the other's approach, whose centre line is a lane off to
        # the side. Only a road that passes under the deck itself asks for clearance.
        def way(name, nodes, x0, x1, y, bridge=False):
            tags = {'highway': 'trunk', 'oneway': 'yes', 'sidewalk': 'no'}
            if bridge:
                tags.update(bridge='yes', layer='1')
            return {'id': name, 'nodes': nodes, 'width': 12, 'points': line(x0, y, x1, y, 20), 'tags': tags}

        roads = [way('s0', ['s1', 's2'], 0, 100, 250), way('s1', ['s2', 's3'], 100, 300, 250, True),
                 way('s2', ['s3', 's4'], 300, 500, 250), way('n0', ['n1', 'n2'], 0, 200, 262),
                 way('n1', ['n2', 'n3'], 200, 400, 262, True), way('n2', ['n3', 'n4'], 400, 500, 262)]
        asphalt = list(self.triangles(self.build([{'roads': roads}])[0], 'e2rf_road_major'))
        for x, y in ((200, 250), (290, 262)):
            self.assertLess(self.surface_at(asphalt, x, y), 21.5, (x, y))

    def test_a_deck_is_not_raised_over_a_slip_road_level_with_it(self):
        # Kyiv, Mykoly Mikhnovskoho at the Druzhby Narodiv junction: a one-lane link level with the
        # deck runs beside it under its overhang and joins it through another way. Read as a road
        # under the deck it threw the deck 12 m up, a wall across the road for the other carriageway.
        def way(name, nodes, points, width=16, **tags):
            return {'id': name, 'nodes': nodes, 'width': width, 'points': points,
                    'tags': dict(tags, highway=tags.pop('highway', 'trunk'), sidewalk='no')}
        roads = [way('west', ['w', 'a'], line(0, 250, 200, 250, 20)),
                 way('deck', ['a', 'b'], line(200, 250, 300, 250, 20), bridge='yes', layer='1'),
                 way('east', ['b', 'e'], line(300, 250, 500, 250, 20)),
                 way('link', ['l1', 'l2'], line(150, 255, 290, 255, 20), width=5, highway='primary_link')]
        asphalt = list(self.triangles(self.build([{'roads': roads}])[0], 'e2rf_road_major'))
        self.assertLess(self.surface_at(asphalt, 250, 248), 21)

    def test_a_parapet_leaves_the_mouth_of_a_slip_road_open(self):
        # a link leaving a deck at its own height crosses the deck's parapet line over a few metres
        # of a long segment: judged whole, the parapet stood across the link's mouth
        main = {'id': 'main', 'nodes': ['m1', 'm2'], 'width': 12, 'points': line(0, 250, 500, 250, 20),
                'tags': {'highway': 'trunk', 'oneway': 'yes', 'sidewalk': 'no', 'bridge': 'yes', 'layer': '1'}}
        link = {'id': 'link', 'nodes': ['k1', 'k2'], 'width': 5, 'points': line(250, 256, 350, 275, 20),
                'tags': {'highway': 'trunk_link', 'oneway': 'yes', 'sidewalk': 'no', 'bridge': 'yes', 'layer': '1'}}
        def tops(roads):
            return [t for t in self.triangles(self.build([{'roads': roads}])[1], 'e2rf_fence_wall')
                    if all(abs(p[2] - 21.0) < .05 for p in t)]
        def across(found):
            return [t for t in found if all(255.5 < p[1] < 256.2 for p in t) and any(256 < p[0] < 266 for p in t)]
        self.assertTrue(across(tops([main])))                     # alone the deck has its parapet there
        self.assertFalse(across(tops([main, link])))              # the link's mouth is open
        self.assertTrue([t for t in tops([main, link]) if all(255.5 < p[1] < 256.2 for p in t) and min(p[0] for p in t) > 300])

    def test_a_low_pack_bridge_clears_a_truck_and_the_approaches_ramp(self):
        # Installed Ukraine pack, bridge 2149 over road 148723 near 50.45845, 30.42135:
        # the stored deck sits about 2 m above the road, and the soffit is 1 m thick, so the
        # headroom is about 1 m. A pack that already clears by 4.5 m is left on its profile.
        # The same geometry shifted onto Kyiv's negative coordinates locks the deck bins.
        def way(name, nodes, points, tags, width=12):
            return {'id': name, 'nodes': nodes, 'width': width, 'points': points,
                    'tags': dict(tags, highway='primary', sidewalk='no')}

        def scene(bridge_z, origin=(0, 0), tile=(0, 0), extra=()):
            ox, oy = origin
            def moved(points):
                return [[x + ox, y + oy, z] for x, y, z in points]
            roads = [
                way('west', ['w', 'a'], moved(line(0, 250, 200, 250, 20)), {}),
                way('deck', ['a', 'b'], moved(line(200, 250, 300, 250, bridge_z)),
                    {'bridge': 'yes', 'layer': '1'}),
                way('east', ['b', 'e'], moved(line(300, 250, 500, 250, 20)), {}),
                way('under', ['u', 'v'], moved(line(250, 0, 250, 500, 20)), {}, 40),
                *extra,
            ]
            built = self.build([{'roads': roads}], i=tile[0], j=tile[1])
            road, walls = built[0], built[1]
            asphalt = list(self.triangles(road, 'e2rf_road_major'))
            soffit = [t for t in self.triangles(walls, 'e2rf_fence_wall')
                      if abs(sum(p[0] for p in t) / 3 - (ox + 250)) < 12
                      and abs(sum(p[1] for p in t) / 3 - (oy + 250)) < 12]
            return asphalt, soffit

        def check(origin, tile=(0, 0)):
            ox, oy = origin
            low, soffit = scene(22, origin, tile)
            self.assertTrue(soffit, origin)
            lower = self.surface_at(low, ox + 250, oy + 40)
            self.assertAlmostEqual(lower, 20.1, places=2)
            headroom = min(p[2] for t in soffit for p in t) - lower
            self.assertGreaterEqual(headroom, 4.5, origin)
            # 20 + 6.0 of clearance + 0.1 of slack, plus the 0.1 road lift. A second
            # helping of the same lack (a wide road under several segments) lands near 32.
            self.assertLess(self.surface_at(low, ox + 250, oy + 250), 27.0, origin)
            self.assertAlmostEqual(self.surface_at(low, ox, oy + 250), 20.1, delta=.05)
            self.assertAlmostEqual(self.surface_at(low, ox + 500, oy + 250), 20.1, delta=.05)
            samples = [(x, self.surface_at(low, ox + x, oy + 250)) for x in range(0, 501, 10)]
            self.assertTrue(all(z is not None for _, z in samples), origin)
            slopes = []
            for (x0, z0), (x1, z1) in zip(samples, samples[1:]):
                slope = abs(z1 - z0) / (x1 - x0)
                slopes.append(slope)
                self.assertLessEqual(slope, .065, (origin, x0, z0, z1))
            # a straight grade into a flat deck kinks by the whole grade in one step;
            # the eased ramp changes slope gradually
            turns = [abs(b - a) for a, b in zip(slopes, slopes[1:])]
            self.assertLessEqual(max(turns), .04, origin)
            # 6% over 20 m is 1.2 m. A missed abutment is the whole 3.6 m lift.
            joint = [self.surface_at(low, ox + x, oy + 250) for x in (190, 200, 210)]
            self.assertLessEqual(max(joint) - min(joint), 1.35, joint)
            clear, _ = scene(30, origin, tile)
            self.assertAlmostEqual(self.surface_at(clear, ox + 250, oy + 250), 30.1, delta=.05)
            self.assertAlmostEqual(self.surface_at(clear, ox, oy + 250), 20.1, delta=.05)

        check((0, 0))
        # tile (-47, -8) is x [-23500, -23000), y [-4000, -3500): the whole span, on negative bins
        check((-23500, -4000), (-47, -8))
        # a 20% street in the same tile keeps its hill; the ramp must not terrace it
        hill_pts = line(0, 40, 100, 40, 10)
        for p in hill_pts:
            p[2] = 10 + 20 * p[0] / 100
        hill = way('hill', ['h1', 'h2'], hill_pts, {}, 7)
        asphalt, _ = scene(22, extra=(hill,))
        self.assertAlmostEqual(self.surface_at(asphalt, 0, 40), 10.1, delta=.05)
        self.assertAlmostEqual(self.surface_at(asphalt, 100, 40), 30.1, delta=.05)

    def test_a_repeated_abutment_stays_on_the_same_ramp(self):
        # Country cells repeat the shared node: the same xy twice, at the approach end
        # or at a bridge end. The raise landed on the later copy. The mesh keeps the
        # first and drops anything within 0.1 mm, so the deck began a full clearance
        # above the road. A 1 cm gap is a real edge and has to ramp as well.
        def way(name, nodes, points, tags, width=12):
            return {'id': name, 'nodes': nodes, 'width': width, 'points': points,
                    'tags': dict(tags, highway='primary', sidewalk='no')}

        def copy(points):
            return [list(p) for p in points]

        def exact_end(points):
            points = copy(points)
            return points + [list(points[-1])]

        def exact_start(points):
            points = copy(points)
            return [list(points[0])] + points

        def centimetre_end(points):
            points = copy(points)
            a, b = points[-2], points[-1]
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            points.insert(-1, [b[0] - (b[0] - a[0]) / length * .01,
                               b[1] - (b[1] - a[1]) / length * .01, b[2]])
            return points

        west, deck, east = line(0, 250, 200, 250, 20), line(200, 250, 400, 250, 20), line(400, 250, 500, 250, 20)
        # 2 m under the stored deck, as an old pack keeps it (a road level with a deck joins it)
        under = line(300, 0, 300, 500, 18)

        def scene(west_pts, deck_pts):
            roads = [
                way('west', ['w', 'a'], west_pts, {}),
                way('deck', ['a', 'b'], deck_pts, {'bridge': 'yes', 'layer': '1'}),
                way('east', ['b', 'e'], copy(east), {}),
                way('under', ['u', 'v'], copy(under), {}, 40),
            ]
            built = self.build([{'roads': roads}])
            asphalt = list(self.triangles(built[0], 'e2rf_road_major'))
            soffit = [t for t in self.triangles(built[1], 'e2rf_fence_wall')
                      if abs(sum(p[0] for p in t) / 3 - 300) < 15
                      and abs(sum(p[1] for p in t) / 3 - 250) < 15]
            return asphalt, soffit

        cases = {
            'approach end repeated': (exact_end(west), copy(deck)),
            'bridge start repeated': (copy(west), exact_start(deck)),
            'bridge end repeated': (copy(west), exact_end(deck)),
            'both abutments repeated': (exact_end(west), exact_start(exact_end(deck))),
            'approach end one centimetre short': (centimetre_end(west), copy(deck)),
        }
        for name, (west_pts, deck_pts) in cases.items():
            with self.subTest(name=name):
                asphalt, soffit = scene(west_pts, deck_pts)
                self.assertTrue(soffit, name)
                lower = self.surface_at(asphalt, 300, 40)
                self.assertAlmostEqual(lower, 18.1, places=2)
                headroom = min(p[2] for t in soffit for p in t) - lower
                self.assertGreaterEqual(headroom, 4.5, name)
                samples = [(x, self.surface_at(asphalt, x, 250)) for x in range(0, 501, 2)]
                self.assertTrue(all(z is not None for _, z in samples), name)
                for (x0, z0), (x1, z1) in zip(samples, samples[1:]):
                    self.assertLessEqual(abs(z1 - z0) / (x1 - x0), .065, (name, x0, z0, z1))
                self.assertAlmostEqual(samples[0][1], 20.1, delta=.05)
                self.assertAlmostEqual(samples[-1][1], 20.1, delta=.05)
                # the deck over the road underneath is one carriageway here, so the
                # sampled top is the ramp, not a second road stacked under it
                self.assertGreater(self.surface_at(asphalt, 300, 250), lower + 4.5, name)

    def test_piers_stand_every_25_m_but_never_on_a_road_under_the_bridge(self):
        bridge = {'id': 'b', 'nodes': ['a', 'b'], 'width': 8, 'points': [[0, 250, 20], [500, 250, 20]],
                  'tags': {'highway': 'trunk', 'bridge': 'yes', 'layer': '1', 'sidewalk': 'no'}}
        under = {'id': 'u', 'nodes': ['s', 'n'], 'width': 7, 'points': [[250, 0, 10], [250, 500, 10]],
                 'tags': {'highway': 'residential', 'sidewalk': 'no'}}

        def piers(roads):
            walls = self.triangles(self.build([{'roads': roads}])[1], 'e2rf_fence_wall')
            low = [t for t in walls if min(p[2] for p in t) < 15]       # under the soffit
            return sorted({round(sum(p[0] for p in t) / 3 / 5) * 5 for t in low})
        alone = piers([bridge])
        self.assertIn(250, alone)
        self.assertIn(25, alone)
        self.assertIn(0, alone)                                       # an abutment at each end
        crossed = piers([bridge, under])
        self.assertNotIn(250, crossed)
        self.assertEqual(set(alone) - set(crossed), {250})

    def test_main_road_approaches_to_a_bridge_get_guard_rails(self):
        def rails(highway, lines=(), register=False):
            bridge = {'id': 'b', 'nodes': ['a', 'b'], 'width': 8, 'points': [[250, 250, 10], [500, 250, 10]],
                      'tags': {'highway': highway, 'bridge': 'yes', 'sidewalk': 'no'}}
            approach = {'id': 'r', 'nodes': ['c', 'a'], 'width': 8, 'points': [[100, 250, 10], [250, 250, 10]],
                        'tags': {'highway': highway, 'sidewalk': 'no', **({'e2r:rails': 'register'} if register else {})}}
            cells = [{'roads': [bridge, approach], 'lines': list(lines)}]
            return list(self.triangles(self.build(cells)[1], 'e2rf_clad_metal'))
        metal = rails('trunk')
        self.assertTrue(metal)
        xs = [p[0] for t in metal for p in t]
        ys = [abs(p[1] - 250) for t in metal for p in t]
        zs = [p[2] for t in metal for p in t]
        self.assertAlmostEqual(min(xs), 210, delta=.2)                # 40 m of the approach
        self.assertAlmostEqual(max(xs), 250, delta=.2)
        self.assertGreater(min(ys), 4.4)                              # outside the road's edge
        self.assertLess(max(ys), 4.85)                                # posts behind the beam
        self.assertAlmostEqual(max(zs), 10 + .1 + .75, places=2)
        self.assertEqual(rails('residential'), [])
        self.assertEqual(rails('trunk', register=True), [])           # the register's own rails stand
        osm = {'id': 'g', 'kind': 'guard_rail', 'tags': {'barrier': 'guard_rail'}, 'points': [[100, 254.5, 0], [200, 254.5, 0]]}
        metal = rails('residential', [osm])
        self.assertTrue(metal)
        zs = [p[2] for t in metal for p in t]
        self.assertAlmostEqual(max(zs) - min(zs), .75 + .3, places=2)  # the beam's top over the posts' feet
        self.assertAlmostEqual(max(p[0] for t in metal for p in t), 200, delta=.2)

    def test_a_main_road_on_a_high_embankment_gets_guard_rails_unless_the_register_covers_it(self):
        terrain = {'rect': [0, 0, 500, 500], 'nx': 2, 'ny': 2, 'heights': [20] * 4}

        def rails(z, highway='trunk_link', register=False):
            road = {'id': 'r', 'nodes': ['a', 'b'], 'width': 6, 'points': [[0, 250, z], [500, 250, z]],
                    'tags': {'highway': highway, 'oneway': 'yes', 'sidewalk': 'no',
                             **({'e2r:rails': 'register'} if register else {})}}
            return list(self.triangles(self.build([{'roads': [road], 'terrain': terrain}])[1], 'e2rf_clad_metal'))
        metal = rails(24)
        self.assertTrue(metal)
        ys = sorted({round(p[1] - 250) for t in metal for p in t})
        self.assertEqual(ys, [-4, -3, 3, 4])                         # both sides, off the edge
        self.assertEqual(rails(21), [])                               # a low bank: none
        self.assertEqual(rails(24, register=True), [])                # the register knows better
        self.assertEqual(rails(24, highway='residential'), [])

    def test_a_guard_rail_rounds_its_corners_and_shades_smooth(self):
        rail = {'id': 'g', 'kind': 'guard_rail', 'tags': {'barrier': 'guard_rail'},
                'points': [[100, 100, 0], [200, 100, 0], [200, 200, 0]]}
        # the road it guards, 1 m inside its bend
        road = {'id': 'r', 'nodes': ['a', 'b'], 'width': 6, 'points': [[100, 96, 0], [204, 96, 0], [204, 200, 0]],
                'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        scene = self.build([{'roads': [road], 'lines': [rail]}])[1]
        metal = [p for t in self.triangles(scene, 'e2rf_clad_metal') for p in t]
        self.assertTrue(metal)
        # the beam cuts the 90 degree corner on an arc (6 m legs): never near the bare vertex
        self.assertGreater(min(math.hypot(p[0] - 200, p[1] - 100) for p in metal), 1.5)
        # welded vertex normals: the folds and the bend give many directions, not a box's few
        normals = {(round(n.x, 2), round(n.y, 2), round(n.z, 2))
                   for _, mesh in self.meshes(scene, 'e2rf_clad_metal') for n in mesh.normals.values()}
        self.assertGreater(len(normals), 40)
        self.assertTrue(any(abs(n[2]) > .3 for n in normals))     # the folds face up and down

    def test_steep_ground_at_a_decks_end_is_drawn_as_its_concrete(self):
        # OSM draws many decks barely longer than the road under them: on the 10 m lattice the ground
        # between the approach's bank and that road stood at 60-70 degrees, a wall of grass by the
        # abutment. Banks of 63 degrees (25 m up over one 12.5 m lattice row) run past a deck's end
        # and under its middle, where a viaduct's valley side stays ground.
        n = 41
        heights = [20 if j * 12.5 <= 200 else 45 if j * 12.5 <= 300 else 70 for j in range(n) for i in range(n)]
        terrain = {'rect': [0, 0, 500, 500], 'nx': n, 'ny': n, 'heights': heights}
        deck = {'id': 'b', 'nodes': ['a', 'b'], 'width': 8, 'points': [[250, 150, 90], [250, 220, 90], [250, 290, 90]],
                'tags': {'highway': 'tertiary', 'bridge': 'yes', 'layer': '1', 'sidewalk': 'no'}}
        road = self.build([{'roads': [deck], 'terrain': terrain}])[0]

        def slope(t):
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
            nx = (by - ay) * (cz - az) - (bz - az) * (cy - ay)
            ny = (bz - az) * (cx - ax) - (bx - ax) * (cz - az)
            nz = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            return math.degrees(math.acos(min(1, abs(nz) / max(1e-12, math.sqrt(nx * nx + ny * ny + nz * nz)))))

        def off_deck(t):      # from the deck's edge
            x, y = sum(p[0] for p in t) / 3, sum(p[1] for p in t) / 3
            return math.hypot(x - 250, max(0, y - 290, 150 - y)) - 4
        bank = lambda t: all(299 < p[1] < 314 for p in t)
        concrete = [t for t in self.triangles(road, 'e2rf_fence_wall') if bank(t)]
        self.assertTrue(concrete)
        self.assertTrue(all(off_deck(t) <= 15 for t in concrete))
        steep = [t for t in self.triangles(road, 'e2rf_ground') if bank(t) and slope(t) > 55]
        self.assertTrue(steep)                                        # away from the deck: still ground
        self.assertTrue(all(off_deck(t) > 15 for t in steep))
        valley = lambda t: all(199 < p[1] < 214 and abs(p[0] - 250) < 20 for p in t)
        self.assertTrue([t for t in self.triangles(road, 'e2rf_ground') if valley(t) and slope(t) > 55])
        self.assertEqual([t for t in self.triangles(road, 'e2rf_fence_wall') if valley(t) and slope(t) < 85], [])

    def test_an_osm_guard_rail_is_drawn_only_beside_a_carriageway(self):
        # OSM maps a rail where the imagery showed it; some stand metres off the road the pack
        # draws (an old alignment, a ramp since rebuilt) and were drawn out in the grass
        road = {'id': 'r', 'nodes': ['a', 'b'], 'width': 8, 'points': line(0, 250, 500, 250, 0),
                'tags': {'highway': 'trunk', 'sidewalk': 'no'}}
        # 1 m off the asphalt from x 100 to 200, then out to 15 m off it by x 260
        drifting = {'id': 'g', 'kind': 'guard_rail', 'tags': {'barrier': 'guard_rail'},
                    'points': [[100, 255, 0], [200, 255, 0], [260, 269, 0], [400, 269, 0]]}
        lone = {'id': 'f', 'kind': 'guard_rail', 'tags': {'barrier': 'guard_rail'},
                'points': [[100, 100, 0], [300, 100, 0]]}       # in a field, no road near
        # weaving 3.4 to 4.6 m off the far edge, a vertex every 8 m: its 8 m stretches past 4 m
        # do not chop it up
        weaving = {'id': 'v', 'kind': 'guard_rail', 'tags': {'barrier': 'guard_rail'},
                   'points': [[100 + 8 * k, 242.6 if k % 2 == 0 else 241.4, 0] for k in range(13)]}
        scene = self.build([{'roads': [road], 'lines': [drifting, lone, weaving]}])[1]
        metal = [p for t in self.triangles(scene, 'e2rf_clad_metal') for p in t]
        beside = [p[0] for p in metal if abs(p[1] - 255) < .5]
        self.assertTrue(beside)
        self.assertAlmostEqual(min(beside), 100, delta=.5)
        self.assertGreater(max(p[0] for p in metal), 205)          # on along the bend while near
        self.assertEqual([p for p in metal if p[1] > 258.5], [])    # never more than 4 m off
        self.assertEqual([p for p in metal if p[1] < 200], [])      # the lone one: none
        woven = [p[0] for p in metal if 240 < p[1] < 244]
        self.assertTrue(all(any(x <= q < x + 2 for q in woven) for x in range(100, 196, 2)))

    def test_a_slip_road_leaving_a_trunk_road_gets_a_hatched_gore(self):
        tags = {'highway': 'trunk', 'oneway': 'yes', 'lanes': '2', 'sidewalk': 'no'}
        main_in = {'id': 'a', 'nodes': ['w', 'n'], 'width': 8, 'points': [[0, 250, 10], [200, 250, 10]], 'tags': tags}
        main_out = {'id': 'b', 'nodes': ['n', 'e'], 'width': 8, 'points': [[200, 250, 10], [500, 250, 10]], 'tags': tags}
        slip = {'id': 'c', 'nodes': ['n', 's'], 'width': 5, 'points': [[200, 250, 10], [500, 280, 10]],
                'tags': {'highway': 'trunk_link', 'oneway': 'yes', 'sidewalk': 'no'}}
        road = self.build([{'roads': [main_in, main_out, slip]}])[0]

        def wedge(tris):     # between the two carriageways' facing edges, past the junction
            out = []
            for t in tris:
                x = sum(p[0] for p in t) / 3
                y = sum(p[1] for p in t) / 3
                if 230 < x < 400 and 254.2 < y < 250 + (x - 200) * .1 - 2.6:
                    out.append(t)
            return out
        self.assertTrue(wedge(self.triangles(road, 'e2rf_road_major')))      # paved
        stripes = wedge(self.triangles(road, 'e2rf_mark'))
        self.assertTrue(stripes)
        # diagonal, not along the road like a lane line
        dirs = set()
        for t in stripes:
            xs = [p[0] for p in t]
            ys = [p[1] for p in t]
            dirs.add((max(ys) - min(ys)) > .6)
        self.assertIn(True, dirs)
        # a plain one-way trunk without a slip road has no gore
        plain = self.build([{'roads': [main_in, main_out]}])[0]
        self.assertEqual(wedge(self.triangles(plain, 'e2rf_mark')), [])

    def test_barriers_mapped_beside_a_deck_are_not_drawn_on_the_road_under_it(self):
        bridge = {'id': 'b', 'nodes': ['a', 'b'], 'width': 8, 'points': [[200, 250, 20], [300, 250, 20]],
                  'tags': {'highway': 'tertiary', 'bridge': 'yes', 'layer': '1', 'sidewalk': 'no'}}
        under = {'id': 'u', 'nodes': ['s', 'n'], 'width': 8, 'points': [[250, 0, 10], [250, 500, 10]],
                 'tags': {'highway': 'trunk', 'sidewalk': 'no'}}
        # OSM: a guard rail and a railing along the deck's edges, a rail beside the road under it
        deck_rail = {'id': 'g', 'kind': 'guard_rail', 'tags': {'barrier': 'guard_rail'},
                     'points': [[180, 254.5, 0], [320, 254.5, 0]]}
        railing = {'id': 'f', 'kind': 'fence', 'tags': {'barrier': 'fence', 'fence_type': 'railing'},
                   'points': [[190, 245.5, 0], [310, 245.5, 0]]}
        low_rail = {'id': 'l', 'kind': 'guard_rail', 'tags': {'barrier': 'guard_rail'},
                    'points': [[254.5, 150, 0], [254.5, 350, 0]]}
        # the deck's approaches: a rail stands only beside a road
        west = {'id': 'w', 'nodes': ['w', 'a'], 'width': 8, 'points': [[100, 250, 20], [200, 250, 20]],
                'tags': {'highway': 'tertiary', 'sidewalk': 'no'}}
        east = {'id': 'e', 'nodes': ['b', 'e'], 'width': 8, 'points': [[300, 250, 20], [400, 250, 20]],
                'tags': {'highway': 'tertiary', 'sidewalk': 'no'}}
        scene = self.build([{'roads': [bridge, under, west, east], 'lines': [deck_rail, railing, low_rail]}])[1]
        metal = list(self.triangles(scene, 'e2rf_clad_metal'))
        mesh = list(self.triangles(scene, 'e2rf_fence_mesh'))

        def across_the_road(tris):    # over the lower road's asphalt, off its own rail
            return [t for t in tris if all(abs(p[0] - 250) < 4 for p in t) and all(abs(p[1] - 250) > 1 for p in t)
                    and not all(abs(p[0] - 254.5) < .6 for p in t)]
        self.assertEqual(across_the_road(metal), [])
        self.assertEqual(across_the_road(mesh), [])
        # the lower road's rail stops at the deck's edges and goes on past them; the deck's ones go on past its ends
        # and keeps ROADS.onDeck.under m (8) off its edges (the deck is 4 m half width): no rail end in front of the pier
        self.assertEqual([t for t in metal if all(abs(p[0] - 254.5) < .6 and abs(p[1] - 250) < 11 for p in t)], [])
        self.assertTrue([t for t in metal if all(abs(p[0] - 254.5) < .6 and 13 < abs(p[1] - 250) < 60 for p in t)])
        self.assertTrue([t for t in metal if all(p[0] < 195 and abs(p[1] - 254.5) < .6 for p in t)])
        self.assertTrue([t for t in mesh if all(p[0] > 300 for p in t)])

    def test_a_rail_running_on_under_a_high_deck_at_a_skew_is_cut_under_it(self):
        # Tallinna ringtee at Jüri: median and slip road rails OSM carries on under the overpass, 10 m up, at an
        # angle to it (here 45 degrees), crossing each other at the pier: left out under the deck, kept past it
        bridge = {'id': 'b', 'nodes': ['a', 'b'], 'width': 8, 'points': [[200, 250, 20], [300, 250, 20]],
                  'tags': {'highway': 'tertiary', 'bridge': 'yes', 'layer': '1', 'sidewalk': 'no'}}
        under = {'id': 'u', 'nodes': ['s', 'n'], 'width': 8, 'points': [[100, 100, 10], [400, 400, 10]],
                 'tags': {'highway': 'trunk', 'sidewalk': 'no'}}
        west = {'id': 'w', 'nodes': ['w', 'a'], 'width': 8, 'points': [[100, 250, 20], [200, 250, 20]],
                'tags': {'highway': 'tertiary', 'sidewalk': 'no'}}
        east = {'id': 'e', 'nodes': ['b', 'e'], 'width': 8, 'points': [[300, 250, 20], [400, 250, 20]],
                'tags': {'highway': 'tertiary', 'sidewalk': 'no'}}
        d = 5 / 2 ** .5           # 5 m off the carriageway's line, on its right
        rail = {'id': 'g', 'kind': 'guard_rail', 'tags': {'barrier': 'guard_rail'},
                'points': [[150 + d, 150 - d, 0], [350 + d, 350 - d, 0]]}
        metal = list(self.triangles(self.build([{'roads': [bridge, under, west, east], 'lines': [rail]}])[1], 'e2rf_clad_metal'))
        self.assertEqual([t for t in metal if all(abs(p[1] - 250) < 4 and abs(p[0] - 255) < 8 for p in t)], [])
        self.assertTrue([t for t in metal if all(10 < p[1] - 250 < 60 and abs(p[0] - p[1] - 0) < 9 for p in t)])
        self.assertTrue([t for t in metal if all(-60 < p[1] - 250 < -10 for p in t)])

    def test_fences_across_a_carriageway_or_under_a_low_deck_are_cut_there(self):
        # OSM: a fence across a road at grade (a gate the pack does not carry), a fence under a
        # bridge deck 1.5 m over the ground (it would stand through the deck) and one under a
        # deck 8 m up (also left out under the deck itself: a piece over any deck is, see
        # test_a_wall_leaves_a_gap_over_a_road_and_under_a_deck)
        road = {'id': 'r', 'nodes': ['a', 'b'], 'width': 8, 'points': [[0, 100, 20.1], [500, 100, 20.1]],
                'tags': {'highway': 'trunk', 'sidewalk': 'no'}}
        low = {'id': 'l', 'nodes': ['c', 'd'], 'width': 8, 'points': [[0, 250, 21.5], [500, 250, 21.5]],
               'tags': {'highway': 'trunk', 'bridge': 'yes', 'layer': '1', 'sidewalk': 'no'}}
        high = {'id': 'h', 'nodes': ['e', 'f'], 'width': 8, 'points': [[0, 400, 28], [500, 400, 28]],
                'tags': {'highway': 'trunk', 'bridge': 'yes', 'layer': '1', 'sidewalk': 'no'}}
        fences = [{'id': f'f{x}', 'kind': 'fence', 'tags': {'barrier': 'fence'}, 'points': [[x, y - 30, 0], [x, y + 30, 0]]}
                  for x, y in ((100, 100), (250, 250), (400, 400))]
        cell = {'roads': [road, low, high], 'lines': fences,
                'terrain': {'rect': [0, 0, 500, 500], 'nx': 2, 'ny': 2, 'heights': [20] * 4}}
        mesh = list(self.triangles(self.build([cell])[1], 'e2rf_fence_mesh'))
        over = lambda x, y: [t for t in mesh if all(abs(p[0] - x) < 1 and abs(p[1] - y) < 3.5 for p in t)]
        beside = lambda x, y: [t for t in mesh if all(abs(p[0] - x) < 1 and 8 < abs(p[1] - y) < 25 for p in t)]
        self.assertEqual(over(100, 100), [])
        self.assertEqual(over(250, 250), [])
        self.assertEqual(over(400, 400), [])
        for x, y in ((100, 100), (250, 250), (400, 400)):
            self.assertTrue(beside(x, y))

    def test_a_traffic_island_is_a_curbed_slab_over_the_road(self):
        # a splitter island between a road's two carriageways: paved (small) or grass (tagged)
        def build(tags):
            roads = [{'id': f'r{y}', 'nodes': [f'a{y}', f'b{y}'], 'width': 4, 'points': [[0, y, 20.5], [500, y, 20.5]],
                      'tags': {'highway': 'secondary', 'oneway': 'yes', 'sidewalk': 'no'}} for y in (246, 254)]
            island = {'id': 'i', 'kind': 'island', 'tags': tags,
                      'rings': [[[240, 248.5, 0], [260, 248.5, 0], [260, 251.5, 0], [240, 251.5, 0]]]}
            return self.build([{'roads': roads, 'areas': [island],
                                'terrain': {'rect': [0, 0, 500, 500], 'nx': 2, 'ny': 2, 'heights': [20] * 4}}])[0]
        paved = build({'area:highway': 'traffic_island'})
        top = [t for t in self.triangles(paved, 'e2rf_paved') if all(240 <= p[0] <= 260 and 248 < p[1] < 252 for p in t)]
        self.assertTrue(top)
        lift = 20.5 + .1
        self.assertTrue(all(abs(p[2] - (lift + .15)) < .02 for t in top for p in t))
        rim = [t for t in self.triangles(paved, 'e2rf_curb') if all(239.9 <= p[0] <= 260.1 and 248.4 < p[1] < 251.6 for p in t)]
        self.assertTrue(rim)
        self.assertLess(min(p[2] for t in rim for p in t), lift)
        grass = build({'area:highway': 'traffic_island', 'surface': 'grass'})
        self.assertFalse([t for t in self.triangles(grass, 'e2rf_paved') if all(240 <= p[0] <= 260 and 248 < p[1] < 252 for p in t)])

    def test_a_small_roundabout_gets_a_paved_apron_inside_its_ring(self):
        import math

        def ring(radius, parts=2, n=24):
            pts = [[250 + radius * math.cos(2 * math.pi * k / n), 250 + radius * math.sin(2 * math.pi * k / n), 20.1]
                   for k in range(n + 1)]
            step = n // parts
            return [{'id': f'r{i}', 'nodes': [f'n{i}', f'n{(i + 1) % parts}'], 'width': 7,
                     'points': pts[i * step:(i + 1) * step + 1],
                     'tags': {'highway': 'primary', 'junction': 'roundabout', 'sidewalk': 'no'}}
                    for i in range(parts)]
        terrain = {'rect': [0, 0, 500, 500], 'nx': 2, 'ny': 2, 'heights': [20] * 4}

        def apron(roads, radius=15):
            road = self.build([{'roads': roads, 'terrain': terrain}])[0]
            return [t for t in self.triangles(road, 'e2rf_paved')
                    if all(math.hypot(p[0] - 250, p[1] - 250) < radius for p in t)]
        small = apron(ring(15))
        self.assertTrue(small)
        r = [math.hypot(p[0] - 250, p[1] - 250) for t in small for p in t]
        self.assertGreater(min(r), 15 - 3.5 - 2.1)          # 2 m wide, inside the carriageway
        self.assertLess(max(r), 15 - 3.5 + .05)
        self.assertTrue(all(abs(p[2] - (20.1 + .1 + .04)) < .02 for t in small for p in t))
        self.assertFalse(apron(ring(40), 40))                    # a big ring: grass island only
        self.assertFalse(apron(ring(15)[:1]))                # half a ring is no roundabout

    def test_a_gantry_spans_the_road_clear_over_it(self):
        road = {'id': 'r', 'nodes': ['a', 'b'], 'width': 10, 'points': [[0, 250, 20.1], [500, 250, 20.1]],
                'tags': {'highway': 'trunk', 'sidewalk': 'no'}}
        gantry = {'id': 'g', 'kind': 'gantry', 'tags': {'man_made': 'gantry'}, 'points': [[200, 240, 0], [200, 260, 0]]}
        scene = self.build([{'roads': [road], 'lines': [gantry],
                             'terrain': {'rect': [0, 0, 500, 500], 'nx': 2, 'ny': 2, 'heights': [20] * 4}}])[1]
        tris = list(self.triangles(scene, 'e2rf_fence_mesh'))
        over = [t for t in tris if min(p[1] for p in t) < 245 and max(p[1] for p in t) > 255]
        self.assertTrue(over)
        self.assertGreater(min(p[2] for t in over for p in t), 20 + 5.5)
        posts = [p for t in tris for p in t if abs(p[1] - 240) < .5 and p[2] < 21]
        self.assertTrue(posts)

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
        # the road register's shoulders: 1 m left, 0.5 m right of the node order
        self.assertEqual(lines({'highway': 'trunk', 'oneway': 'yes', 'lanes': '2', 'width': '9',
                                'shoulder:left:width': '1', 'shoulder:right:width': '.5'}, 9), {13.4, 9.8, 6.1})

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

    def test_a_wall_leaves_a_gap_over_a_road_and_under_a_deck(self):
        # Kyiv: a rail yard's wall crossed the Povitrianykh Syl overpass and stopped the car
        wall = {'id': 'w', 'kind': 'fence', 'tags': {'barrier': 'wall'}, 'points': [[250, 20, 10], [250, 480, 10]]}
        for tags in ({}, {'bridge': 'yes', 'layer': '1'}):
            with self.subTest(tags=tags):
                road = {'id': 'r', 'nodes': ['a', 'b'], 'width': 10, 'points': [[0, 250, 10], [500, 250, 10]],
                        'tags': dict(tags, highway='primary', sidewalk='no')}
                scene = self.build([{'roads': [road], 'lines': [wall]}], terrainStep=100)[1]
                ys = [p[1] for t in self.triangles(scene, 'e2rf_fence_wall') for p in t if abs(p[0] - 250) < .2]
                self.assertTrue([y for y in ys if y < 200] and [y for y in ys if y > 300])
                self.assertFalse([y for y in ys if 245 < y < 255], 'wall on the carriageway')

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
                'tags': {'highway': 'residential', 'lit': 'yes', 'sidewalk': 'both'}}
        scene = self.build([{'roads': [road]}], terrainStep=100)[1]
        lamps = [item for item in scene['items'].values() if item.kind == 'static' and item.shape.endswith('lamp1.dae')]
        self.assertEqual(len(lamps), 16)
        self.assertTrue(all(item.shape == '/art/shapes/objects/lamp1.dae' for item in lamps))
        self.assertTrue(all(item.decor and abs(item.pos[3] - 10.1) < 1e-8 for item in lamps))

    def test_surveyed_lamps_replace_the_inferred_row_beside_them(self):
        # OSM maps Kyiv's lamps (203 k in its region): the street's own row must not double them
        road = {'id': 'street', 'width': 7, 'points': [[0, 250, 10], [500, 250, 10]],
                'tags': {'highway': 'residential', 'lit': 'yes', 'sidewalk': 'both'}}
        mapped = [{'id': f'l{k}', 'kind': 'lamp', 'tags': {'highway': 'street_lamp'}, 'pos': [x, 245, 10]}
                  for k, x in enumerate(range(20, 260, 30))]
        scene = self.build([{'roads': [road], 'points': mapped}], terrainStep=100)[1]
        lamps = [item for item in scene['items'].values() if item.kind == 'static' and item.shape.endswith('lamp1.dae')]
        at = {(p['pos'][0], p['pos'][1]) for p in mapped}
        surveyed = [item for item in lamps if (item.pos[1], item.pos[2]) in at]
        inferred = [item for item in lamps if (item.pos[1], item.pos[2]) not in at]
        self.assertEqual(len(surveyed), len(mapped))
        self.assertTrue(inferred)                                        # the unmapped half keeps its row
        for item in inferred:
            self.assertTrue(all(math.hypot(item.pos[1] - x, item.pos[2] - y) > 12 for x, y in at))
        self.assertTrue(all(item.pos[1] > 242 for item in inferred))

    def test_surveyed_lamps_on_the_carriageway_go_to_its_edge(self):
        # OSM maps many lamps as nodes of the street or in its lanes: ~3,700 stood in central Kyiv's roads
        road = {'id': 'street', 'width': 7, 'points': [[0, 250, 10], [500, 250, 10]],
                'tags': {'highway': 'residential', 'sidewalk': 'both'}}
        points = [{'id': 'axis', 'kind': 'lamp', 'tags': {}, 'pos': [100, 250, 10]},
                  {'id': 'north', 'kind': 'lamp', 'tags': {}, 'pos': [200, 252, 10]},
                  {'id': 'south', 'kind': 'lamp', 'tags': {}, 'pos': [300, 247.5, 10]},
                  {'id': 'beside', 'kind': 'lamp', 'tags': {}, 'pos': [400, 244, 10]},
                  {'id': 'lane', 'kind': 'tree', 'tags': {}, 'pos': [150, 251, 10]},
                  {'id': 'pit', 'kind': 'tree', 'tags': {}, 'pos': [450, 245.5, 10]}]
        scene = self.build([{'roads': [road], 'points': points}], terrainStep=100)[1]
        placed = {item.name.split('_point_')[1]: item for item in scene['items'].values()
                  if item.kind == 'static' and '_point_' in item.name}
        self.assertEqual(set(placed), {'axis', 'north', 'south', 'beside', 'pit'})
        for name in ('axis', 'north', 'south'):
            self.assertGreaterEqual(abs(placed[name].pos[2] - 250), 3.5 + .5, name)
        self.assertGreater(placed['north'].pos[2], 250)
        self.assertLess(placed['south'].pos[2], 250)
        self.assertEqual((placed['north'].pos[1], placed['south'].pos[1]), (200, 300))
        self.assertEqual((placed['beside'].pos[1], placed['beside'].pos[2]), (400, 244))
        self.assertEqual((placed['pit'].pos[1], placed['pit'].pos[2]), (450, 245.5))

    def test_a_surveyed_lamp_on_a_deck_stands_on_its_parapet(self):
        deck = {'id': 'deck', 'nodes': ['a', 'b'], 'width': 8, 'points': line(0, 250, 500, 250, 20),
                'tags': {'highway': 'primary', 'sidewalk': 'no', 'bridge': 'yes', 'layer': '1'}}
        lamp = {'id': 'l', 'kind': 'lamp', 'tags': {}, 'pos': [250, 251, 5]}
        scene = self.build([{'roads': [deck], 'points': [lamp]}], terrainStep=100)[1]
        item = next(item for item in scene['items'].values() if item.kind == 'static' and '_point_' in item.name)
        self.assertAlmostEqual(item.pos[2], 254 - .15, places=3)     # in the parapet, 0.3 m thick
        self.assertAlmostEqual(item.pos[3], 20 + .1 + .9, places=2)  # its top, over the deck

    def test_street_props_line_sidewalks_and_footways_but_not_carriageways(self):
        # four arms meeting at a junction node (250, 250)
        roads = [{'id': arm, 'nodes': ['j', arm], 'width': 8, 'tags': {'highway': 'residential', 'sidewalk': 'both'},
                  'points': [[250, 250, 10], end]}
                 for arm, end in (('n', [250, 500, 10]), ('s', [250, 0, 10]), ('e', [500, 250, 10]), ('w', [0, 250, 10]))]
        lines = [{'id': 'walk', 'kind': 'path', 'tags': {'highway': 'footway'}, 'points': [[50, 50, 10], [50, 200, 10]]}]
        # a house wall 1.8 m east of the footway's axis, 0.4 m behind where a prop would stand
        house = {'id': 'house', 'height': 9, 'rings': [[[51.8, 100], [70, 100], [70, 140], [51.8, 140]]]}

        def props(**options):
            scene = self.build([{'roads': roads, 'lines': lines, 'buildings': [house]}], terrainStep=100, **options)[1]
            return [item for item in scene['items'].values() if item.streetKind == 'furniture']

        placed = props(propSpacing=6)
        self.assertGreater(len(placed), 200)
        self.assertTrue(all(item.kind == 'static' and item.collision == 'Collision Mesh' for item in placed))
        for item in placed:
            x, y = item.pos[1], item.pos[2]
            # off both carriageways
            self.assertFalse(abs(x - 250) < 4.2 and 0 <= y <= 500 or abs(y - 250) < 4.2 and 0 <= x <= 500, (x, y))
        walk = [item for item in placed if abs(item.pos[1] - 50) < 3 and item.pos[2] < 210]
        self.assertTrue(walk)
        # beside the paving (1 m half width) by each kind's own half depth
        self.assertTrue(all(1.5 < abs(item.pos[1] - 50) < 2.01 for item in walk))
        self.assert_props_clear([(item.pos[1], item.pos[2], 2 * math.atan2(item.rot[3], item.rot[4]), item.shape)
                                 for item in placed], roads, lines)
        self.assertFalse([item for item in walk if item.pos[1] > 50 and 99 <= item.pos[2] <= 141])
        self.assertTrue([item for item in walk if item.pos[1] < 50 and 99 <= item.pos[2] <= 141])
        # junction mouths stay clear
        self.assertFalse([item for item in placed if abs(item.pos[1] - 250) < 10 and abs(item.pos[2] - 250) < 10])
        self.assertEqual(props(propSpacing=0), [])
        self.assertEqual(props(propSpacing=6, look={'statics': 'sparse'}), [])
        # no random stop or give-way signs (OSM's own are drawn elsewhere)
        self.assertFalse([item for item in placed if 'sign_' in item.shape])

    def street_props(self, cells, i=0, j=0):
        scene = self.build(cells, i, j, terrainStep=100, propSpacing=6)[1]
        return [(item.pos[1], item.pos[2], item.shape) for item in scene['items'].values() if item.streetKind == 'furniture']

    def street_prop_items(self, cells, only=None):
        """Placed props as (x, y, yaw, shape); only: a fresh generator with just the stock prop whose file ends so."""
        if only:
            self.setUp()
            kinds = self.generator.STREET_PROPS
            keep = [kinds[k] for k in range(1, len(kinds) + 1) if kinds[k][1].endswith(only)]
            for k in range(len(kinds), 0, -1):
                kinds[k] = None
            for k, prop in enumerate(keep, 1):
                kinds[k] = prop
        scene = self.build(cells, 0, 0, terrainStep=100, propSpacing=6, maxTrees=0)[1]
        return [(item.pos[1], item.pos[2], 2 * math.atan2(item.rot[3], item.rot[4]), item.shape)
                for item in scene['items'].values() if item.streetKind == 'furniture']

    def assert_props_clear(self, placed, roads=(), paths=()):
        """Every prop's whole plan keeps 0.3 m off the carriageways and the paths' paving."""
        for x, y, yaw, shape in placed:
            outline = prop_outline(x, y, yaw, shape)
            for road in roads:
                self.assertGreaterEqual(outline_clearance(outline, road['points']), road['width'] / 2 + .3 - 1e-6,
                                        (x, y, shape, road['id']))
            for path in paths:
                half = float(path['tags'].get('width', 2)) / 2
                self.assertGreaterEqual(outline_clearance(outline, path['points']), half + .3 - 1e-6, (x, y, shape, path['id']))

    def test_street_props_bike_stands_run_along_the_kerb_and_keep_their_length_off_an_acute_fork(self):
        # a street forks at (250, 250) into two arms 20 degrees apart: a 4.2 m stand along one
        # arm's sidewalk near the fork would reach the other arm's carriageway with an end
        tags = {'highway': 'residential', 'sidewalk': 'both'}
        stem = {'id': 'stem', 'nodes': ['s', 'j'], 'width': 8, 'tags': tags, 'points': [[250, 20, 10], [250, 250, 10]]}
        arms = [{'id': f'arm{k}', 'nodes': ['j', f'e{k}'], 'width': 8, 'tags': tags,
                 'points': [[250, 250, 10], [250 + 230 * math.sin(a), 250 + 230 * math.cos(a), 10]]}
                for k, a in enumerate((math.radians(-10), math.radians(10)))]
        roads = [stem] + arms
        placed = self.street_prop_items([{'roads': roads}], 'clutter_city_bike_stand.dae')
        self.assertGreater(len(placed), 100)
        self.assert_props_clear(placed, roads)
        for x, y, yaw, _shape in placed:
            # local X along the street it stands on
            road = min(roads, key=lambda r: segment_distance((x, y), r['points'][0], r['points'][1]))
            (ax, ay, _), (bx, by, _) = road['points']
            length = math.hypot(bx - ax, by - ay)
            self.assertAlmostEqual(abs(math.cos(yaw) * (bx - ax) / length - math.sin(yaw) * (by - ay) / length), 1, 6)
        # the fork's inner sidewalks: the lattice point 31 m up an arm (y 280.5) has its centre 5.4 m
        # from the other arm's axis (a point test passes it) but the stand's end 4.2 m; outer ones keep stands
        inner = [p for p in placed if p[1] > 250 and abs(p[0] - 250) < math.tan(math.radians(10)) * (p[1] - 250)]
        self.assertFalse([p for p in inner if p[1] < 283], inner)
        self.assertTrue(inner)
        self.assertTrue([p for p in placed if 260 < p[1] < 290 and abs(p[0] - 250) > 8])

    def test_street_props_keep_a_long_stand_off_a_bend_but_benches_stay_on_a_straight_sidewalk(self):
        # one way turns 120 degrees at (250, 250); a stand along a leg would end within its own bend
        tags = {'highway': 'residential', 'sidewalk': 'both'}
        bend = {'id': 'bend', 'width': 8, 'tags': tags,
                'points': [[30, 250, 10], [250, 250, 10],
                           [250 + 220 * math.cos(math.radians(60)), 250 + 220 * math.sin(math.radians(60)), 10]]}
        placed = self.street_prop_items([{'roads': [bend]}], 'clutter_city_bike_stand.dae')
        self.assert_props_clear(placed, [bend])
        self.assertGreater(len(placed), 50)
        # benches every lattice step on both sidewalks of a straight street: not erased by their size
        street = {'id': 'street', 'width': 8, 'tags': tags, 'points': [[0, 250, 10], [500, 250, 10]]}
        benches = self.street_prop_items([{'roads': [street]}], 'clutter_city_bench_wood.dae')
        self.assertGreaterEqual(len(benches), 2 * ((500 - 12) // 6))
        self.assert_props_clear(benches, [street])
        self.assertTrue(all(abs(abs(y - 250) - (4 + 2 - .457)) < 1e-6 for _x, y, _yaw, _s in benches))

    def test_street_props_on_a_narrow_footway_keep_off_its_neighbour(self):
        # 1 m footways 2 m apart: a stand or a bench between them would lie on the other's
        # paving; the outer sides keep theirs
        walks = [{'id': 'a', 'kind': 'path', 'tags': {'highway': 'footway', 'width': '1'}, 'points': [[100, 100, 10], [100, 400, 10]]},
                 {'id': 'b', 'kind': 'path', 'tags': {'highway': 'footway', 'width': '1'}, 'points': [[102, 100, 10], [102, 400, 10]]}]
        near = {'clutter_city_bike_stand.dae': .321, 'clutter_city_bench_wood.dae': .205, 'planterbox.dae': .46 * math.sqrt(2)}
        for kind, edge in near.items():
            placed = self.street_prop_items([{'lines': walks, 'areas': [RETAIL]}], kind)
            self.assert_props_clear(placed, paths=walks)
            self.assertFalse([p for p in placed if 100 < p[0] < 102], kind)
            self.assertTrue([p for p in placed if p[0] < 100] and [p for p in placed if p[0] > 102], kind)
            # just off its own paving: the plan's edge 0.35 m beyond the paving's half width
            self.assertTrue(all(abs(min(abs(x - 100), abs(x - 102)) - (.5 + .35 + edge)) < 1e-6 for x, _y, _yaw, _s in placed))

    def test_street_props_keep_the_road_lattice_across_a_tile_seam(self):
        # the road starts at junction j (900, 250) in tile 1 and runs west into tile 0, which
        # does not see the junction: both tiles step 6 m from j, and the junction's cut moves nothing
        main = {'id': 'main', 'nodes': ['j', 'w'], 'width': 8, 'tags': {'highway': 'residential', 'sidewalk': 'both'},
                'points': [[900, 250, 10], [100, 250, 10]]}
        arms = [{'id': arm, 'nodes': ['j', arm], 'width': 12, 'tags': {'highway': 'residential'},
                 'points': [[900, 250, 10], end]} for arm, end in (('n', [900, 450, 10]), ('s', [900, 50, 10]))]
        tile0 = self.street_props([{'roads': [main]}], 0, 0)
        tile1 = self.street_props([{'roads': [main] + arms}], 1, 0)
        alone = self.street_props([{'roads': [main]}], 1, 0)
        along = [p for p in tile0 + tile1 if abs(p[1] - 250) < 7 and p[0] < 880]
        self.assertGreater(len(along), 100)
        for x, y, _shape in along:
            phase = (900 - x) % 6
            self.assertTrue(min(phase, 6 - phase) < 1e-6, (x, y))
        edge = sorted(p[0] for p in tile0 + tile1 if p[1] > 250 and abs(p[0] - 500) < 10)
        self.assertTrue(all(abs(b - a - 6) < 1e-6 or abs(b - a) < 1e-6 for a, b in zip(edge, edge[1:])), edge)
        # the same props, kind included, whether or not the tile sees the junction
        key = lambda props: sorted((round(x, 3), round(y, 3), shape) for x, y, shape in props if x < 880)
        self.assertEqual(key(tile1), key(alone))

    def test_street_props_run_on_through_a_way_split(self):
        # one straight street split at (250, 250) by a tag change: a joint, not a junction, so the
        # sidewalk keeps 3 m (not 6) either side of it and no sign stands there
        tags = {'highway': 'residential', 'sidewalk': 'both'}
        roads = [{'id': 'a', 'nodes': ['p', 'q'], 'width': 8, 'tags': tags, 'points': [[250, 0, 10], [250, 250, 10]]},
                 {'id': 'b', 'nodes': ['q', 'r'], 'width': 8, 'tags': dict(tags, maxspeed='30'),
                  'points': [[250, 250, 10], [250, 500, 10]]}]
        placed = self.street_props([{'roads': roads}])
        east = sorted(p[1] for p in placed if p[0] > 250)
        self.assertGreater(len(east), 45)
        gaps = [b - a for a, b in zip(east, east[1:])]
        self.assertLessEqual(max(gaps), 24 + 1e-6, east)
        self.assertGreaterEqual(min(gaps), 6 - 1e-6, east)
        self.assertFalse([p for p in placed if 'sign_' in p[2]])

    def test_street_props_skip_a_separate_sidewalk_and_stay_off_the_street_band(self):
        # the north sidewalk is a footway of its own 7 m from the axis: only that footway's
        # outer row has props there; its inner row would stand on the road's drawn sidewalk
        road = {'id': 'street', 'width': 8, 'points': [[0, 250, 10], [500, 250, 10]],
                'tags': {'highway': 'residential', 'sidewalk:left': 'separate', 'sidewalk:right': 'yes'}}
        walk = {'id': 'walk', 'kind': 'path', 'tags': {'highway': 'footway', 'footway': 'sidewalk'},
                'points': [[0, 257, 10], [500, 257, 10]]}
        placed = self.street_props([{'roads': [road], 'lines': [walk]}])
        north = [p for p in placed if p[1] > 250]
        self.assertTrue(north)
        self.assertTrue(all(258.5 < y < 259.01 for _x, y, _s in north), sorted({round(p[1], 2) for p in north}))
        self.assertTrue([p for p in placed if p[1] < 250])
        for k, a in enumerate(placed):
            for b in placed[k + 1:]:
                self.assertGreater((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2, 1, (a, b))

    def test_street_props_keep_off_other_paths_crossings_and_path_ends(self):
        # two footways cross at (250, 250); a zebra crosses the street at x=300
        walks = [{'id': 'ns', 'kind': 'path', 'tags': {'highway': 'footway'}, 'points': [[250, 100, 10], [250, 400, 10]]},
                 {'id': 'ew', 'kind': 'path', 'tags': {'highway': 'footway'}, 'points': [[100, 250, 10], [400, 250, 10]]}]
        placed = self.street_props([{'lines': walks, 'areas': [RETAIL]}])
        self.assertTrue(placed)
        for x, y, _shape in placed:
            self.assertFalse(abs(x - 250) < 1.3 and 100 <= y <= 400 or abs(y - 250) < 1.3 and 100 <= x <= 400, (x, y))
            for ex, ey in ((250, 100), (250, 400), (100, 250), (400, 250)):
                self.assertGreater(abs(x - ex) + abs(y - ey), 3, (x, y))
        street = {'id': 'street', 'width': 8, 'points': [[0, 250, 10], [500, 250, 10]],
                  'tags': {'highway': 'residential', 'sidewalk': 'both'}}
        zebra = {'id': 'zebra', 'kind': 'path', 'tags': {'highway': 'footway', 'footway': 'crossing'},
                 'points': [[300, 244, 10], [300, 256, 10]]}
        placed = self.street_props([{'roads': [street], 'lines': [zebra]}])
        self.assertFalse([p for p in placed if abs(p[0] - 300) < 2], [p for p in placed if abs(p[0] - 300) < 2])
        self.assertTrue([p for p in placed if 290 <= p[0] <= 310])

    def test_street_props_only_on_paths_and_streets_on_the_ground(self):
        hidden = [{'id': f'u{k}', 'kind': 'path', 'tags': dict(tags, highway='footway'),
                   'points': [[100 + 40 * k, 100, 10], [100 + 40 * k, 400, 10]]}
                  for k, tags in enumerate(({'indoor': 'yes'}, {'level': '-1'}, {'layer': '-1'},
                                            {'covered': 'yes'}, {'tunnel': 'yes'}, {'level': '1'}))]
        self.assertEqual(self.street_props([{'lines': hidden}]), [])
        # a road tunnel under the street leaves the street's sidewalk props above it
        street = {'id': 'street', 'width': 8, 'points': [[0, 250, 10], [500, 250, 10]],
                  'tags': {'highway': 'residential', 'sidewalk': 'both'}}
        tunnel = {'id': 'tunnel', 'width': 10, 'points': [[250, 0, 0], [250, 500, 0]],
                  'tags': {'highway': 'residential', 'tunnel': 'yes', 'layer': '-1', 'sidewalk': 'both'}}
        placed = self.street_props([{'roads': [street, tunnel]}])
        self.assertTrue([p for p in placed if abs(p[0] - 250) < 5 and abs(p[1] - 250) < 7])
        self.assertFalse([p for p in placed if abs(p[1] - 250) > 7.1])

    def street_assets(self, cells, i=0, j=0, **options):
        scene = self.build(cells, i, j, terrainStep=100, propSpacing=options.pop('propSpacing', 3), **options)[1]
        return [item for item in scene['items'].values() if item.streetKind]

    def test_dense_racks_do_not_overlap_even_across_tile_boundary(self):
        kinds = self.generator.STREET_PROPS
        rack = next(p for p in kinds.values() if p[1].endswith('clutter_city_bike_stand.dae'))
        for k in range(len(kinds), 0, -1):
            kinds[k] = None
        kinds[1] = rack
        road = {'id': 'dense', 'width': 8, 'tags': {'highway': 'residential', 'sidewalk': 'both'},
                'points': [[0, 250, 10], [1000, 250, 10]]}
        items = self.street_assets([{'roads': [road]}], maxTrees=0) + self.street_assets([{'roads': [road]}], i=1, maxTrees=0)
        self.assertGreater(len(items), 100)
        for side in (-1, 1):
            row = sorted(item.pos[1] for item in items if (item.pos[2] - 250) * side > 0)
            # Independent measured rectangle length, plus the inter-object access gap.
            self.assertTrue(all(b - a >= 4.158 + .4 for a, b in zip(row, row[1:])))

    def test_street_plan_is_order_and_tile_independent_with_crossing_paths(self):
        road = {'id': 'avenue', 'width': 12, 'tags': {'highway': 'primary', 'sidewalk': 'both'},
                'points': [[0, 250, 10], [1000, 250, 10]]}
        paths = [{'id': 'a', 'kind': 'path', 'tags': {'highway': 'footway', 'footway': 'sidewalk'},
                  'points': [[400, 270, 10], [600, 270, 10]]},
                 {'id': 'b', 'kind': 'path', 'tags': {'highway': 'footway'},
                  'points': [[480, 220, 10], [530, 300, 10]]}]
        source = [{'roads': [road], 'lines': paths}]
        def key(items):
            return sorted((item.streetKind, item.shape, tuple(round(item.pos[k], 5) for k in (1, 2)),
                           tuple(round(item.rot[k], 5) for k in (3, 4))) for item in items)
        split = self.street_assets(source) + self.street_assets(source, i=1)
        whole = self.street_assets(source, tileSize=1000)
        self.assertEqual(key(split), key(whole))
        reverse = self.street_assets([{'roads': [road], 'lines': list(reversed(paths))}], tileSize=1000)
        self.assertEqual(key(whole), key(reverse))
        self.assertEqual({item.streetKind for item in split}, {'tree', 'lamp', 'furniture'})
        self.assertTrue(all(item.prop and item.collision == 'Collision Mesh' for item in split))

    def furniture(self, cells, **options):
        """Placed furniture as (x, y, yaw, shape, name) on tile 0, 0."""
        scene = self.build(cells, 0, 0, terrainStep=100, propSpacing=options.pop('propSpacing', 12), maxTrees=0, **options)[1]
        return [(item.pos[1], item.pos[2], 2 * math.atan2(item.rot[3], item.rot[4]), item.shape, item.name)
                for item in scene['items'].values() if item.streetKind == 'furniture']

    def test_street_furniture_by_blocks_of_flats_turns_to_the_yard(self):
        # six blocks of flats 12 x 60 m with no street near: a bench and a bin at the entrances,
        # backs to the wall, and rows of three containers out in the yard
        blocks = []
        for k in range(6):
            x0, y0 = 60 + 130 * (k % 3), 80 + 200 * (k // 3)
            blocks.append({'id': f'flats{k}', 'height': 27, 'tags': {'building': 'apartments'},
                           'rings': [[[x0, y0], [x0 + 12, y0], [x0 + 12, y0 + 60], [x0, y0 + 60]]]})
        placed = self.furniture([{'buildings': blocks}], propSpacing=6)
        entrance = [p for p in placed if '_entrance_' in p[4]]
        bins = [p for p in placed if '_bins_' in p[4]]
        self.assertTrue([p for p in entrance if p[3].endswith('bench_wood.dae')])
        self.assertTrue([p for p in entrance if p[3].endswith('metal_bin.DAE')])
        self.assertTrue(bins)
        self.assertEqual(set(p[3].rsplit('/', 1)[1] for p in placed), {'clutter_city_bench_wood.dae', 'italy_clutter_metal_bin.DAE',
                                                                     'italy_clutter_dumpster.DAE'})
        for x, y, yaw, shape, _name in placed:
            outline = prop_outline(x, y, yaw, shape)
            for block in blocks:
                ring = block['rings'][0]
                for px, py in outline:
                    inside = ring[0][0] < px < ring[1][0] and ring[0][1] < py < ring[2][1]
                    self.assertFalse(inside, (x, y, shape))
                    self.assertGreaterEqual(outline_clearance([(px, py)], ring + [ring[0]]), .6 - 1e-6, (x, y, shape))
        for x, y, yaw, shape, _name in entrance:
            block = min(blocks, key=lambda b: outline_clearance([(x, y)], b['rings'][0] + [b['rings'][0][0]]))
            ring = block['rings'][0]
            self.assertLess(outline_clearance([(x, y)], ring + [ring[0]]), 3.5)
            if shape.endswith('bench_wood.dae'):
                # local +Y (sin, cos) turned out from the wall it stands at
                cx, cy = (ring[0][0] + ring[1][0]) / 2, (ring[0][1] + ring[2][1]) / 2
                # the wall it stands out from: the side it is furthest past (a bench now stands
                # beside the door, 2.6 m along the wall, so it can be near a corner)
                out = (x - cx, 0) if abs(x - cx) - 6 > abs(y - cy) - 30 else (0, y - cy)
                self.assertGreater(math.sin(yaw) * out[0] + math.cos(yaw) * out[1], 0, (x, y))
        rows = {}
        for p in bins:
            rows.setdefault(p[4].rsplit('_', 1)[0], []).append(p)
        for row in rows.values():
            self.assertLessEqual(len(row), 3)
            row.sort(key=lambda p: (p[0], p[1]))
            for a, b in zip(row, row[1:]):
                self.assertAlmostEqual(math.hypot(b[0] - a[0], b[1] - a[1]), 1.85, 6)

    def yard(self, cells, **options):
        """The near scene of tile 0, 0 and what YARD laid out there (cars, kit) as plain lists."""
        scene = self.build(cells, 0, 0, terrainStep=100, propSpacing=options.pop('propSpacing', 12), **options)[1]
        return scene, self.plain(scene['yard'])

    def test_a_yard_driveway_gets_cars_parked_beside_it(self):
        # a block of flats and a 3 m driveway 13 m off its yard wall: cars along it, off the
        # asphalt, clear of the block, lengthwise; none along the same lane far from any flats
        block = {'id': 'flats', 'height': 27, 'tags': {'building': 'apartments'},
                 'rings': [[[200, 200], [215, 200], [215, 280], [200, 280]]]}
        drive = {'id': 'drive', 'width': 3, 'tags': {'highway': 'service', 'service': 'driveway'},
                 'points': [[228, 150, 10], [228, 330, 10]]}
        lane = {'id': 'lane', 'width': 3, 'tags': {'highway': 'service'}, 'points': [[420, 20, 10], [420, 480, 10]]}
        scene, yard = self.yard([{'buildings': [block], 'roads': [drive, lane]}], maxTrees=0)
        cars = yard['cars']
        self.assertGreater(len(cars), 8)
        for x, y, yaw in cars:
            self.assertLess(abs(x - 228), 6, (x, y))
            self.assertGreater(abs(x - 228), 1.5 + .88 + .5, (x, y))
            self.assertAlmostEqual(abs(math.sin(yaw)), 1, 3)
            self.assertGreater(min(abs(x - 200), abs(x - 215)) if 200 - 3 < y < 280 + 3 else 9, 1.5)
        self.assertTrue(list(self.triangles(scene, 'e2rf_car')))

    def test_a_playground_has_sand_and_kit_inside_it_and_no_trees(self):
        block = {'id': 'flats', 'height': 27, 'tags': {'building': 'apartments'},
                 'rings': [[[200, 200], [215, 200], [215, 280], [200, 280]]]}
        play = {'id': 'play', 'kind': 'playground', 'tags': {'leisure': 'playground'},
                'rings': [[[240, 215], [272, 215], [272, 247], [240, 247]]]}
        green = {'id': 'yard', 'kind': 'residential', 'tags': {'landuse': 'residential'},
                 'rings': [[[150, 150], [350, 150], [350, 350], [150, 350]]]}
        scene, yard = self.yard([{'buildings': [block], 'areas': [green, play]}])
        kinds = {kind for _, _, kind in yard['kit']}
        self.assertGreaterEqual(len(yard['kit']), 4)
        self.assertGreaterEqual(len(kinds), 4)
        for x, y, _kind in yard['kit']:
            self.assertTrue(241 < x < 271 and 216 < y < 246, (x, y))
        kit = [t for t in self.triangles(scene, 'e2rf_yard') if all(238 < p[0] < 274 and 213 < p[1] < 249 for p in t)]
        self.assertGreater(len(kit), 200)
        sand = list(self.triangles(scene, 'e2rf_sand'))
        self.assertTrue(sand)
        self.assertTrue(all(240 - 1e-6 <= p[0] <= 272 + 1e-6 and 215 - 1e-6 <= p[1] <= 247 + 1e-6 for t in sand for p in t))
        for item in scene['items'].values():
            if item.shape and not item.prop and '/trees' in item.shape:
                self.assertFalse(240 < item.pos[1] < 272 and 215 < item.pos[2] < 247, item.shape)

    def test_front_gardens_leave_a_gap_and_a_porch_at_each_mapped_door(self):
        # six blocks with two stair doors each on the yard (east) wall
        cells, doors = [{'buildings': [], 'points': []}], []
        for k in range(6):
            x0, y0 = 40 + 140 * (k % 3), 60 + 220 * (k // 3)
            cells[0]['buildings'].append({'id': f'flats{k}', 'height': 27, 'tags': {'building': 'apartments'},
                                          'rings': [[[x0, y0], [x0 + 14, y0], [x0 + 14, y0 + 80], [x0, y0 + 80]]]})
            for n, dy in enumerate((22, 57)):
                doors.append((x0 + 14, y0 + dy))
                cells[0]['points'].append({'id': f'door{k}_{n}', 'kind': 'entrance', 'tags': {'entrance': 'staircase'},
                                           'pos': [x0 + 14, y0 + dy, 10]})
        scene, _ = self.yard(cells, maxTrees=0)
        rails = [p for kind in ('railing_blue', 'railing_green', 'railing_dark')
                 for t in self.triangles(scene, 'e2rf_' + kind) for p in t]
        self.assertTrue(rails)
        porch = [p for t in self.triangles(scene, 'e2rf_yard') for p in t]
        for dx, dy in doors:
            # the railing keeps 2 m either side of the door clear in front of it
            self.assertFalse([p for p in rails if dx < p[0] < dx + 5 and abs(p[1] - dy) < 2.1], (dx, dy))
            # a step in front of the door and a canopy ~2.9 m over it
            here = [p for p in porch if dx - .1 < p[0] < dx + 1.8 and abs(p[1] - dy) < 1.5]
            self.assertTrue(here, (dx, dy))
            self.assertAlmostEqual(max(p[2] for p in here) - min(p[2] for p in here), 2.94 + .3, 1)

    def test_street_furniture_follows_the_ground_a_path_runs_through(self):
        # a footway through a park, one past a building, one in the fields beyond the town
        park = {'id': 'park', 'kind': 'park', 'tags': {'leisure': 'park'}, 'rings': [[[0, 0], [200, 0], [200, 500], [0, 500]]]}
        house = {'id': 'school', 'height': 9, 'tags': {'building': 'yes'}, 'rings': [[[300, 240], [330, 240], [330, 270], [300, 270]]]}
        walks = [{'id': name, 'kind': 'path', 'tags': {'highway': 'footway'}, 'points': [[x, 40, 10], [x, 460, 10]]}
                 for name, x in (('park', 100), ('yard', 285), ('field', 480))]
        placed = self.furniture([{'areas': [park], 'buildings': [house], 'lines': walks}], propSpacing=6)
        def kinds(x):
            return {p[3].rsplit('/', 1)[1] for p in placed if abs(p[0] - x) < 4}
        self.assertEqual(kinds(100), {'clutter_city_bench_wood.dae', 'clutter_city_bin_round.dae'})
        self.assertTrue(kinds(285))
        self.assertLessEqual(kinds(285), {'clutter_city_bench_wood.dae', 'italy_clutter_metal_bin.DAE', 'garbage_bin_a.dae'})
        self.assertEqual(kinds(480), set())

    def test_street_furniture_at_house_gates_and_on_a_village_sidewalk(self):
        # houses north of a village street with sidewalks: a wheelie bin or a bench past the
        # sidewalk at some gates, and the sidewalk gets a village's furniture, not a city's
        road = {'id': 'street', 'width': 6, 'tags': {'highway': 'residential', 'sidewalk': 'both'},
                'points': [[0, 250, 10], [500, 250, 10]]}
        houses = [{'id': f'house{k}', 'height': 6, 'tags': {'building': 'yes'},
                   'rings': [[[20 + 25 * k, 268], [30 + 25 * k, 268], [30 + 25 * k, 278], [20 + 25 * k, 278]]]}
                  for k in range(19)]
        placed = self.furniture([{'roads': [road], 'buildings': houses}])
        gates = [p for p in placed if '_gate_' in p[4]]
        self.assertTrue(gates)
        for x, y, yaw, shape, _name in gates:
            self.assertGreater(y, 250)
            outline = prop_outline(x, y, yaw, shape)
            self.assertGreaterEqual(outline_clearance(outline, road['points']), 3 + 2 + .3 - 1e-6, (x, y, shape))
        self.assertTrue([p for p in placed if '_gate_' not in p[4]])
        self.assertLessEqual({p[3].rsplit('/', 1)[1] for p in placed},
                             {'clutter_city_bench_wood.dae', 'garbage_bin_a.dae', 'garbage_bin_b.dae', 'italy_clutter_big_dustbin.DAE'})

    def test_postsoviet_streets_use_european_furniture(self):
        # a city street with no houses: the sidewalk mix, not the village set
        road = {'id': 'street', 'width': 8, 'tags': {'highway': 'residential', 'sidewalk': 'both', 'lit': 'yes'},
                'points': [[0, 250, 10], [500, 250, 10]]}
        look = {'block': 'postsoviet', 'statics': 'street'}
        scene = self.build([{'roads': [road]}], terrainStep=100, propSpacing=6, maxTrees=0, look=look)[1]
        furniture = [item for item in scene['items'].values() if item.streetKind == 'furniture']
        names = {item.shape.rsplit('/', 1)[-1] for item in furniture}
        self.assertIn('bollard_hoop_red.dae', names)
        self.assertIn('italy_clutter_metal_bin.DAE', names)
        self.assertNotIn('postbox_blue.dae', names)
        self.assertNotIn('bollard_yellow.dae', names)
        self.assertFalse([item.shape for item in furniture if 'sign_' in item.shape])
        lamps = [item.shape for item in scene['items'].values() if item.streetKind == 'lamp']
        self.assertTrue(lamps)
        self.assertTrue(all(shape.endswith('lamp1.dae') for shape in lamps))

    def test_postsoviet_village_and_park_skip_the_american_bins(self):
        road = {'id': 'street', 'width': 6, 'tags': {'highway': 'residential', 'sidewalk': 'both'},
                'points': [[0, 250, 10], [500, 250, 10]]}
        houses = [{'id': f'house{k}', 'height': 6, 'tags': {'building': 'yes'},
                   'rings': [[[20 + 25 * k, 268], [30 + 25 * k, 268], [30 + 25 * k, 278], [20 + 25 * k, 278]]]}
                  for k in range(19)]
        look = {'block': 'postsoviet'}
        placed = self.furniture([{'roads': [road], 'buildings': houses}], look=look)
        village = {p[3].rsplit('/', 1)[1] for p in placed}
        self.assertLessEqual(village, {'clutter_city_bench_wood.dae', 'italy_clutter_metal_bin.DAE',
                                       'italy_clutter_metal_bin_small.DAE', 'italy_clutter_big_dustbin.DAE'})
        self.assertIn('italy_clutter_metal_bin.DAE', village)
        self.assertNotIn('garbage_bin_a.dae', village)
        self.assertNotIn('postbox_blue.dae', village)
        park = {'id': 'park', 'kind': 'park', 'tags': {'leisure': 'park'},
                'rings': [[[0, 0], [200, 0], [200, 500], [0, 500]]]}
        walk = {'id': 'park', 'kind': 'path', 'tags': {'highway': 'footway'}, 'points': [[100, 40, 10], [100, 460, 10]]}
        placed = self.furniture([{'areas': [park], 'lines': [walk]}], look=look, propSpacing=6)
        kinds = {p[3].rsplit('/', 1)[1] for p in placed if abs(p[0] - 100) < 4}
        self.assertLessEqual(kinds, {'clutter_city_bench_wood.dae', 'clutter_city_bin_round.dae',
                                     'clutter_city_wood_table_small.dae', 'clutter_city_wood_stool.dae'})
        self.assertIn('clutter_city_bench_wood.dae', kinds)
        self.assertTrue(kinds & {'clutter_city_wood_table_small.dae', 'clutter_city_wood_stool.dae'})

    def test_street_furniture_on_a_square_stays_on_it(self):
        square = {'id': 'square', 'kind': 'paved', 'tags': {'place': 'square'},
                  'rings': [[[100, 100], [220, 100], [220, 180], [100, 180]]]}
        placed = self.furniture([{'areas': [square]}], propSpacing=6)
        self.assertGreater(len(placed), 20)
        for x, y, _yaw, shape, _name in placed:
            outline = prop_outline(x, y, _yaw, shape)
            self.assertTrue(all(100 <= px <= 220 and 100 <= py <= 180 for px, py in outline), (x, y, shape))
        self.assertLessEqual({p[3].rsplit('/', 1)[1] for p in placed},
                             {'planterbox.dae', 'clutter_city_bench_wood.dae', 'clutter_city_bin_round.dae',
                              'clutter_city_bollard_concrete.dae', 'clutter_city_bike_stand.dae'})

    def test_street_lamps_and_trees_respect_exclusions_and_quality(self):
        road = {'id': 'avenue', 'width': 8, 'tags': {'highway': 'primary', 'sidewalk': 'both'},
                'points': [[0, 250, 10], [500, 250, 10]]}
        water = {'id': 'pond', 'kind': 'water', 'rings': [[[90, 240], [170, 240], [170, 270], [90, 270]]]}
        point = {'id': 'mapped-tree', 'kind': 'tree', 'pos': [204, 259, 10]}
        source = [{'roads': [road], 'areas': [water], 'points': [point]}]
        items = self.street_assets(source)
        self.assertTrue(any(item.streetKind == 'tree' for item in items))
        self.assertFalse([item for item in items if 90 <= item.pos[1] <= 170])
        inferred = [item for item in items if 'point_' not in item.name]
        self.assertTrue(all(math.hypot(item.pos[1] - 204, item.pos[2] - 259) >= 3 for item in inferred))
        disabled = self.street_assets([{'roads': [road]}], propSpacing=0)
        self.assertEqual({item.streetKind for item in disabled}, {'lamp'})
        dark = dict(road, tags=dict(road['tags'], lit='no'))
        self.assertFalse([item for item in self.street_assets([{'roads': [dark]}]) if item.streetKind == 'lamp'])
        bridge = dict(road, tags=dict(road['tags'], bridge='yes'))
        self.assertEqual(self.street_assets([{'roads': [bridge]}]), [])
        self.assertEqual(self.street_assets([{'roads': [road]}], far=True), [])

    def test_street_furniture_keeps_a_walkable_corridor_and_curb_roles(self):
        road = {'id': 'street', 'width': 8, 'tags': {'highway': 'residential', 'sidewalk': 'both'},
                'points': [[0, 250, 10], [500, 250, 10]]}
        items = self.street_assets([{'roads': [road]}], maxTrees=0, propSpacing=6)
        curb = [item for item in items if 'bollard_hoop' in item.shape]
        self.assertTrue(curb)
        self.assertTrue(all(abs(item.pos[2] - 250) < 5 for item in curb))
        for item in items:
            outline = prop_outline(item.pos[1], item.pos[2], 2 * math.atan2(item.rot[3], item.rot[4]), item.shape)
            depths = [abs(y - 250) - 4 for _x, y in outline]
            # A single item's occupied width leaves at least 1.2 m on a 2 m walk.
            occupied = max(0, min(2, max(depths)) - max(0, min(depths)))
            self.assertLessEqual(occupied, .8 + 1e-6)

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

    def test_a_fine_source_grid_sets_a_fine_ground_lattice(self):
        # a 10 m LiDAR grid: lattice nodes every 10 m and the real relief kept near the road;
        # a 25 m Terrarium grid keeps the 25 m lattice and the wide pull
        road = {'id': 'r', 'width': 6, 'nodes': [1, 2], 'points': [[-50, 250, 20.1], [550, 250, 20.1]],
                'tags': {'highway': 'residential', 'sidewalk': 'no'}}

        def ground(step):
            n = int(500 / step) + 1
            heights = [20.0 + (3.0 if abs(k // n * step - 200) < 1 else 0) for k in range(n * n)]
            cell = {'roads': [road], 'terrain': {'rect': [0, 0, 500, 500], 'nx': n, 'ny': n, 'heights': heights}}
            return [p for t in self.triangles(self.build([cell])[0], 'e2rf_ground') for p in t]

        fine, coarse = ground(10), ground(25)
        lattice = lambda ps, step: {round(p[0], 3) for p in ps if abs(p[0] / step - round(p[0] / step)) < 1e-6}
        self.assertIn(10.0, lattice(fine, 10))
        self.assertNotIn(10.0, lattice(coarse, 25))
        # a 3 m bank 50 m from the road's centre: kept by the fine DEM, pulled down by the coarse
        bump = lambda ps: max((p[2] for p in ps if abs(p[1] - 200) < .5 and 100 < p[0] < 400), default=0)
        self.assertGreater(bump(fine), 22.6)
        self.assertLess(bump(coarse), 22.2)

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

    def test_a_track_stops_at_the_edge_of_the_road_it_crosses(self):
        # the road's profile sits 0.4 m under the DEM (a cut); the track's two source vertices
        # carry the raw DEM 0.5 m over it: drawn straight across, its slab stood proud of the
        # asphalt and threw cars off
        road = {'id': 'main', 'width': 7, 'nodes': [1, 2], 'points': line(-50, 250, 550, 250, 19.6),
                'tags': {'highway': 'tertiary'}}
        track = {'id': 't', 'kind': 'path', 'points': [[250, 100, 20.5], [250, 400, 20.5]],
                 'tags': {'highway': 'track'}}
        manifest = self.build([dict(self.edge_cell(road), lines=[track])])[0]
        dirt = [p for t in self.triangles(manifest, 'e2rf_road_dirt') for p in t]
        self.assertTrue(dirt)
        self.assertEqual({y > 250 for _x, y, _z in dirt}, {True, False})   # both sides kept
        edge = 3.5 + .3
        self.assertTrue(all(abs(y - 250) >= edge - 1e-3 for _x, y, _z in dirt))
        # it lies on the ground pulled to the road: at the road's height where it stops
        near = [z for _x, y, z in dirt if abs(y - 250) < edge + .05]
        self.assertTrue(near)
        self.assertTrue(all(abs(z - (19.6 + .1)) < .02 for z in near), near)
        far = [z for _x, y, z in dirt if abs(y - 250) > 100]
        self.assertTrue(all(abs(z - (20 + .1)) < .1 + .02 for z in far), far)   # DEM plus wear

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
        # 3 windows a floor on the 12 m walls, 2 on the 8 m ones, two floors; one slot is the door.
        # A gable may add one attic quad above the wall top (16 m).
        wall = [t for t in windows if max(p[2] for p in t) < 16]
        attic = [t for t in windows if min(p[2] for p in t) > 16]
        self.assertEqual((len(wall) // 2, len(doors) // 2), (19, 1))
        self.assertLessEqual(len(attic) // 2, 1)
        for t in wall + doors:
            for x, y, z in t:
                outside = min(abs(x - 100), abs(x - 112), abs(y - 100), abs(y - 108))
                self.assertAlmostEqual(outside, .03, places=6)     # 3 cm out from the wall
                self.assertTrue(10 <= z <= 16 - .15, z)
        # the door is on a 12 m wall, on the ground
        self.assertTrue(all(abs(y - 99.97) < 1e-6 or abs(y - 108.03) < 1e-6 for t in doors for _x, y, _z in t))
        self.assertAlmostEqual(min(z for t in doors for _x, _y, z in t), 10.1)

    def test_house_massing_stays_off_the_far_ring_and_potato(self):
        # Grammar v0: large parts are a few quads. Windows stay atlas cells, thinned when detail is low.
        def house(bid, levels='2'):
            return {'id': bid, 'height': 6, 'tags': {'building': 'house', 'building:levels': levels},
                    'rings': [[[100, 100, 10], [112, 100, 10], [112, 108, 10], [100, 108, 10]]]}
        scene = self.build([{'buildings': [house('mass')]}], terrainStep=100)[1]
        chimneys = list(self.triangles(scene, 'e2rf_chimney'))
        self.assertEqual(len(chimneys), 10)  # four sides and a top
        self.assertGreater(max(p[2] for t in chimneys for p in t), 16)
        self.assertTrue(all(99 < p[0] < 113 and 99 < p[1] < 109 for t in chimneys for p in t))
        gable = [p for t in self.triangles(scene, 'e2rf_gable') for p in t]

        def past(p, margin):
            return p[0] < 100 - margin or p[0] > 112 + margin or p[1] < 100 - margin or p[1] > 108 + margin

        # cornice sits 7 cm outside the walls, up at the eaves; the porch reaches ~0.85 m out
        self.assertTrue(any(p[2] > 15.5 and past(p, .04) for p in gable))
        self.assertTrue(any(p[2] < 14 and past(p, .5) for p in gable))
        flat = {'id': 'flat', 'height': 6, 'tags': {'building': 'house', 'roof:shape': 'flat'},
                'rings': [[[200, 100, 10], [212, 100, 10], [212, 108, 10], [200, 108, 10]]]}
        flat_scene = self.build([{'buildings': [flat]}], terrainStep=100)[1]
        self.assertFalse(list(self.triangles(flat_scene, 'e2rf_chimney')))
        far = self.build([{'buildings': [house('far')]}], terrainStep=100, far=True)[1]
        self.assertFalse(list(self.triangles(far, 'e2rf_chimney')))
        self.assertFalse(list(self.triangles(far, 'e2rf_gable')))

        def window_quads(built):
            return [t for name in ('e2rf_win_pvc', 'e2rf_win_wood') for t in self.triangles(built, name)]

        full = len(window_quads(scene))
        potato = self.build([{'buildings': [house('pot')]}], terrainStep=100, detail=0)[1]
        self.assertLess(len(window_quads(potato)), full)
        self.assertFalse(list(self.triangles(potato, 'e2rf_chimney')))
        self.assertTrue(list(self.triangles(potato, 'e2rf_door_house')))

        def lua_hash(value):
            h = 17
            for byte in value.encode():
                h = (h * 131 + byte) % 2147483647
            return h

        bid = next(f'bal{k}' for k in range(80) if lua_hash(f'bal{k}') % 4 == 1)
        bal = self.build([{'buildings': [house(bid)]}], terrainStep=100)[1]
        deck = [p for t in self.triangles(bal, 'e2rf_gable') for p in t
                if 13 < p[2] < 14.2 and past(p, .5)]
        self.assertTrue(deck, bid)

    def test_city_blocks_gain_a_rim_a_crown_and_a_canopy(self):
        # Flat city blocks, near tiles, detail >= 40. Photo walls stay one quad. The new parts
        # are a socle, a parapet with a coping, one roof bulkhead and concrete canopies.
        def block(bid, height, rings, **tags):
            return {'id': bid, 'height': height, 'tags': tags, 'rings': rings}

        def rect(x, y, w, d, z=10):
            return [[[x, y, z], [x + w, y, z], [x + w, y + d, z], [x, y + d, z]]]

        panel = block('panel', 27, rect(100, 100, 40, 16), **{'building': 'apartments', 'building:material': 'panel'})
        scene = self.build([{'buildings': [panel]}], terrainStep=100)[1]
        top = 37
        parapet = list(self.triangles(scene, 'e2rf_parapet'))
        self.assertGreater(len(parapet), 16)
        self.assertLess(len(parapet), 80)
        self.assertFalse(list(self.triangles(scene, 'e2rf_chimney')))
        high = [p for t in parapet for p in t if p[2] > top + 1]
        self.assertTrue(high)
        self.assertTrue(all(99 < p[0] < 141 and 99 < p[1] < 117 for p in high))
        self.assertTrue(any(p[2] > top + .3 and p[1] < 99.97 for t in parapet for p in t))
        self.assertTrue(any(12 < p[2] < 16 and p[1] < 99.2 for t in parapet for p in t))
        # The orbit camera is above the ledge, so the top faces up and the fascia faces out.
        hood_n = [n for x, y, z, *n in self.corners(scene, 'e2rf_parapet') if 12 < z < 16 and y < 99.2]
        self.assertTrue(any(n[2] > .5 for n in hood_n))
        self.assertTrue(any(n[1] < -.5 for n in hood_n))
        socle = [p for t in self.triangles(scene, 'e2rf_plinth') for p in t]
        self.assertTrue(any(9.9 < p[2] < 10.4 and p[1] < 99.98 for p in socle))
        walls = [p[2] for item, mesh in self.meshes(scene) if str(mesh.material).startswith('e2rf_wall_')
                 for k in range(1, len(mesh.verts) + 1)
                 for p in [(mesh.verts[k].x, mesh.verts[k].y, mesh.verts[k].z + item.pos[3])]]
        self.assertTrue(any(abs(z - top) < 1e-6 for z in walls))
        # The face has vertices only at the roof and at the rim, so the band between them is empty.
        south = [n for x, y, z, *n in self.corners(scene, 'e2rf_parapet')
                 if y < 99.97 and abs(n[2]) < .2 and top - .05 <= z <= top + 1.2]
        self.assertTrue(south)
        self.assertTrue(all(n[1] < -.5 for n in south))
        coping = [n for x, y, z, *n in self.corners(scene, 'e2rf_parapet') if z > top + .65]
        self.assertTrue(any(n[2] > .5 for n in coping))

        house = block('mass', 6, rect(200, 100, 12, 8), **{'building': 'house', 'building:levels': '2'})
        house_scene = self.build([{'buildings': [house]}], terrainStep=100)[1]
        self.assertEqual(len(list(self.triangles(house_scene, 'e2rf_chimney'))), 10)
        self.assertFalse(list(self.triangles(house_scene, 'e2rf_parapet')))

        shed = block('shed', 10, rect(100, 200, 30, 12), **{'building': 'shed'})
        garage = block('row', 12, rect(100, 300, 60, 8), **{'building': 'garages'})
        quiet = self.build([{'buildings': [shed, garage]}], terrainStep=100)[1]
        self.assertFalse(list(self.triangles(quiet, 'e2rf_parapet')))

        far = self.build([{'buildings': [panel]}], terrainStep=100, far=True)[2]
        self.assertEqual(far.triangles, 10)
        self.assertFalse(list(self.triangles(far, 'e2rf_parapet')))
        potato = self.build([{'buildings': [panel]}], terrainStep=100, detail=0)[1]
        self.assertFalse(list(self.triangles(potato, 'e2rf_parapet')))
        self.assertFalse(list(self.triangles(potato, 'e2rf_plinth')))

        court = block('court', 20, [
            [[100, 100, 10], [160, 100, 10], [160, 160, 10], [100, 160, 10]],
            [[120, 120, 10], [140, 120, 10], [140, 140, 10], [120, 140, 10]]],
            **{'building': 'apartments'})
        court_scene = self.build([{'buildings': [court]}], terrainStep=100)[1]
        court_top = 30
        rim = [p for t in self.triangles(court_scene, 'e2rf_parapet') for p in t]
        self.assertTrue(any(p[1] < 99.97 and court_top < p[2] < court_top + 1 for p in rim))
        self.assertFalse(any(court_top < p[2] < court_top + 1 and 120.5 < p[0] < 139.5 and 120.2 < p[1] < 121 for p in rim))
        crown = [p for p in rim if p[2] > court_top + 1]
        self.assertTrue(crown)
        self.assertTrue(all(not (120.4 < p[0] < 139.6 and 120.4 < p[1] < 139.6) for p in crown))

        ell = block('ell', 22, [[
            [100, 100, 10], [150, 100, 10], [150, 118, 10], [118, 118, 10], [118, 150, 10], [100, 150, 10]]],
            **{'building': 'apartments'})
        ell_scene = self.build([{'buildings': [ell]}], terrainStep=100)[1]
        ell_crown = [p for t in self.triangles(ell_scene, 'e2rf_parapet') for p in t if p[2] > 33]
        self.assertTrue(ell_crown)
        self.assertTrue(all(not (p[0] > 118.4 and p[1] > 118.4) for p in ell_crown))

        gabled = block('pitch', 18, rect(100, 100, 30, 12), **{'building': 'apartments', 'roof:shape': 'gabled'})
        pitched = self.build([{'buildings': [gabled]}], terrainStep=100)[1]
        self.assertTrue(all(p[2] < 18 for t in self.triangles(pitched, 'e2rf_parapet') for p in t))

        # North wall is the first long side. A road to the south pulls the canopy onto that face.
        faced = block('faced', 27, [[[140, 116, 10], [100, 116, 10], [100, 100, 10], [140, 100, 10]]],
                      **{'building': 'apartments', 'building:material': 'panel'})
        road = {'id': 'street', 'width': 8, 'points': [[80, 88, 10], [180, 88, 10]],
                'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        faced_scene = self.build([{'roads': [road], 'buildings': [faced]}], terrainStep=100)[1]
        hood = [p for t in self.triangles(faced_scene, 'e2rf_parapet') for p in t if 12 < p[2] < 16]
        self.assertTrue(any(p[1] < 99.2 for p in hood))
        self.assertTrue(any(p[1] > 116.2 for p in hood))

        # A long facade cut into 10 m OSM edges is still one wall: hoods reach the far end.
        split = block('split', 27, [[
            [100, 100, 10], [110, 100, 10], [120, 100, 10], [130, 100, 10],
            [140, 100, 10], [150, 100, 10], [160, 100, 10], [170, 100, 10],
            [180, 100, 10], [180, 116, 10], [100, 116, 10]]],
            **{'building': 'apartments', 'building:material': 'panel'})
        split_scene = self.build([{'roads': [road], 'buildings': [split]}], terrainStep=100)[1]
        split_hood = [p for t in self.triangles(split_scene, 'e2rf_parapet') for p in t if 12 < p[2] < 16]
        self.assertTrue(any(p[1] < 99.2 and p[0] > 155 for p in split_hood))
        self.assertTrue(any(p[1] > 116.2 for p in split_hood))

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

    def test_low_houses_mix_stone_old_brick_and_boards(self):
        stone = {'id': 'stone', 'height': 6, 'tags': {'building': 'house', 'building:material': 'stone'},
                 'rings': [[[100, 100, 10], [112, 100, 10], [112, 110, 10], [100, 110, 10]]]}
        scene = self.build([{'buildings': [stone]}], terrainStep=100)[1]
        self.assertTrue(list(self.triangles(scene, 'e2rf_hw_stone')))
        plaster = [{'id': f'p{k}', 'height': 6, 'tags': {'building': 'house', 'building:material': 'plaster'},
                    'rings': [[[k * 20, 200, 10], [k * 20 + 10, 200, 10], [k * 20 + 10, 210, 10], [k * 20, 210, 10]]]}
                   for k in range(40)]
        plain = [{'id': f'h{k}', 'height': 5, 'tags': {'building': 'house'},
                  'rings': [[[k * 16, 300, 10], [k * 16 + 10, 300, 10], [k * 16 + 10, 308, 10], [k * 16, 308, 10]]]}
                 for k in range(120)]
        scene = self.build([{'buildings': plaster + plain}], terrainStep=100, tileSize=2000)[1]

        def materials_near(pred):
            found = set()
            for item, mesh in self.meshes(scene):
                name = str(mesh.material)
                if not name.startswith('e2rf_hw_'):
                    continue
                for k in range(1, len(mesh.verts) + 1):
                    if pred(mesh.verts[k].y + item.pos[2]):
                        found.add(name)
                        break
            return found

        plaster_walls = materials_near(lambda y: y < 250)
        self.assertTrue(plaster_walls)
        self.assertTrue(all(material in ('e2rf_hw_white', 'e2rf_hw_yellow', 'e2rf_hw_blue', 'e2rf_hw_green',
                                         'e2rf_hw_pink', 'e2rf_hw_aged') for material in plaster_walls), plaster_walls)
        mixed = materials_near(lambda y: y > 250)
        self.assertTrue({'e2rf_hw_oldbrick', 'e2rf_hw_flatbrick', 'e2rf_hw_stone', 'e2rf_hw_boards'} <= mixed, mixed)

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

    def test_far_tiles_draw_the_roads_that_the_guard_rails_beside_them_stand_by(self):
        # Past the near radius the car's surroundings are far tiles. They kept the rails and fences
        # but drew no road, so from a free camera the ringtee was grass between two lines of
        # guard rail. A far tile draws each road's surface, as plain decoration without collision;
        # service streets and parking aisles stay out (the far ring's triangle budget).
        def road(name, highway, y, width):
            return {'id': name, 'nodes': [name + 'a', name + 'b'], 'width': width,
                    'tags': {'highway': highway, 'sidewalk': 'no'}, 'points': [[0, y, 30], [500, y, 30]]}
        trunk, lane = road('t', 'trunk', 150, 12), road('s', 'service', 350, 4)
        terrain = {'rect': [0, 0, 500, 500], 'nx': 2, 'ny': 2, 'heights': [30] * 4}
        cell = {'roads': [trunk, lane], 'terrain': terrain}
        far = self.build([cell], far=True)[2]
        asphalt = [t for m in ('e2rf_road', 'e2rf_road_major', 'e2rf_road_worn') for t in self.triangles(far, m)]
        self.assertTrue(asphalt)
        ys = [p[1] for t in asphalt for p in t]
        self.assertAlmostEqual(min(ys), 144, delta=.3)                  # the trunk road's width
        self.assertAlmostEqual(max(ys), 156, delta=.3)
        self.assertGreater(min(p[2] for t in asphalt for p in t), 30)    # over the ground, not in it
        self.assertTrue(all(item.decor and item.layer == 'far' for item in far['items'].values()))
        horizon = self.build([cell], horizon=True)[2]
        self.assertFalse([t for m in ('e2rf_road', 'e2rf_road_major') for t in self.triangles(horizon, m)])
        # in a 10 m cutting the coarse far terrain (100 m triangles) stands over the road: the far
        # road is lifted to just over it, never hidden under it (Laagna tee: ground 4 m over the road)
        cutting = {'roads': [trunk], 'terrain': {'rect': [0, 0, 500, 500], 'nx': 2, 'ny': 2, 'heights': [40] * 4}}
        far = self.build([cutting], far=True)[2]
        asphalt = [t for m in ('e2rf_road', 'e2rf_road_major', 'e2rf_road_worn') for t in self.triangles(far, m)]
        ground = list(self.triangles(far, 'e2rf_ground'))
        self.assertTrue(asphalt and ground)
        for x in (60, 150, 250, 350, 440):
            for y in (146, 150, 154):
                road_z, ground_z = self.surface_at(asphalt, x, y), self.surface_at(ground, x, y)
                self.assertIsNotNone(road_z, (x, y))
                self.assertGreaterEqual(road_z, ground_z - .005, (x, y, road_z, ground_z))

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
