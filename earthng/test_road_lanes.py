"""The asphalt as lanes with the texture along the road (generator.lua ROADS.lanes, laneBands); needs lupa."""
import math
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

SOURCE = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/generator.lua'
LANE_M = 28.0
LANE_KINDS = ('e2rf_road_lane', 'e2rf_road_major_lane', 'e2rf_road_worn_lane')
PLAIN_KINDS = ('e2rf_road', 'e2rf_road_major', 'e2rf_road_worn')


def area(triangle):
    (ax, ay), (bx, by), (cx, cy) = (p[:2] for p in triangle)
    return abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2


class RoadLaneTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.generator = self.lua.execute(SOURCE.read_text(encoding='utf8'))

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def build(self, cells, i=0, j=0, **options):
        options.setdefault('relief', False)
        # the crown off (generator ROADS.SHAPE: it cuts a band over the centre line in two);
        # test_road_seat.py builds the lanes with it
        options['tune'] = {'crown': 0, **(options.get('tune') or {})}
        return self.generator.build(self.table(cells), i, j, self.table(options))

    def corners(self, manifest, materials):
        """Every face corner of the materials as (x, y, z, u, v, nx, ny, nz), three a triangle."""
        out = []
        for item in (manifest['items'] or self.lua.table()).values():
            for mesh in (item['meshes'] or self.lua.table()).values():
                if mesh.material in materials:
                    for k in range(1, len(mesh.faces) + 1):
                        face = mesh.faces[k]
                        p, uv, n = mesh.verts[face.v + 1], mesh.uvs[face.u + 1], mesh.normals[face.n + 1]
                        out.append((p.x + item.pos[1], p.y + item.pos[2], p.z + item.pos[3], uv.u, uv.v, n.x, n.y, n.z))
        return out

    def triangles(self, manifest, materials):
        c = self.corners(manifest, materials)
        return [c[k:k + 3] for k in range(0, len(c), 3)]

    def road(self, width, tags, y=250, x0=-50, x1=550, z0=20, z1=20, **extra):
        n = math.ceil((x1 - x0) / 20)
        points = [[x0 + (x1 - x0) * k / n, y, z0 + (z1 - z0) * k / n] for k in range(n + 1)]
        return {'id': 'r', 'width': width, 'nodes': [1, 2], 'points': points, 'tags': {'sidewalk': 'no', **tags}, **extra}

    def lane_count(self, manifest, x=250.0, eps=1e-6):
        """The lanes the sheet shows across the carriageway at a cross-section: its u runs from 0
        on the left edge to the lane count on the right."""
        us = [c[3] for tri in self.triangles(manifest, LANE_KINDS)
              if min(p[0] for p in tri) - eps <= x <= max(p[0] for p in tri) + eps for c in tri]
        self.assertTrue(us)
        self.assertAlmostEqual(min(us), 0, places=6)
        self.assertAlmostEqual(max(us), round(max(us)), places=6)
        return round(max(us))

    def lanes_across(self, manifest, materials=LANE_KINDS, x=250.0, eps=1e-6):
        """The bands a material has at a cross-section: sorted (y low, y high) of each."""
        bands = set()
        for tri in self.triangles(manifest, materials):
            xs = [p[0] for p in tri]
            if min(xs) - eps <= x <= max(xs) + eps:
                ys = [p[1] for p in tri]
                bands.add((round(min(ys), 3), round(max(ys), 3)))
        return sorted(bands)

    def test_a_two_lane_street_has_the_sheet_once_a_lane_along_the_road(self):
        road = self.road(6, {'highway': 'residential'})
        manifest = self.build([{'roads': [road]}])[0]
        # nothing of the carriageway is left in the plain projection
        self.assertEqual(self.triangles(manifest, PLAIN_KINDS), [])
        tris = self.triangles(manifest, ('e2rf_road_lane',))
        self.assertAlmostEqual(sum(area(t) for t in tris), 6 * 500, places=3)
        # one quad a chord across the whole carriageway, as before the lanes: no more triangles
        self.assertEqual(self.lanes_across(manifest), [(247.0, 253.0)])
        self.assertEqual(len(tris), 2 * 26)     # 25 chords of 20 m and the two the tile cuts
        self.assertEqual(self.lane_count(manifest), 2)
        for tri in tris:
            for x, y, z, u, v, nx, ny, nz in tri:
                self.assertAlmostEqual(z, 20.1)
                # u across the road from its left edge (it runs east: left is north), one repeat a lane
                self.assertAlmostEqual(u, (253.0 - y) / 3, places=5)
                # v along the road from its start, a repeat every LANE_M metres
                self.assertAlmostEqual(v, (x + 50) / LANE_M, places=4)
                self.assertAlmostEqual(nz, 1)

    def test_lanes_and_uvs_agree_across_a_tile_border(self):
        road = self.road(7, {'highway': 'tertiary', 'lanes': '2'}, y=10, x0=0, x1=100)
        cells = [{'roads': [road]}]
        borders = []
        for index in (0, 1):
            manifest = self.build(cells, i=index, tileSize=25, terrainStep=25)[0]
            corners = self.corners(manifest, ('e2rf_road_lane',))
            self.assertTrue(corners)
            borders.append({(round(y, 4), round(u, 4), round(v, 4)) for x, y, z, u, v, *_ in corners if abs(x - 25) < 1e-6})
        self.assertTrue(borders[0])
        self.assertEqual(borders[0], borders[1])

    def test_shoulders_stay_plain_asphalt_beside_the_lanes(self):
        # a primary road without a width tag: .5 m of shoulder each side (ROADS.shoulders)
        road = self.road(8, {'highway': 'primary', 'lanes': '2'})
        manifest = self.build([{'roads': [road]}])[0]
        self.assertEqual(self.lanes_across(manifest, ('e2rf_road_major_lane',)), [(246.5, 253.5)])
        self.assertEqual(self.lane_count(manifest), 2)
        self.assertEqual(self.lanes_across(manifest, ('e2rf_road_major',)), [(246.0, 246.5), (253.5, 254.0)])
        # the shoulder keeps the world projection the junctions have (30 m a repeat)
        for x, y, z, u, v, *_ in self.corners(manifest, ('e2rf_road_major',)):
            self.assertAlmostEqual(u, x / 30, places=4)
            self.assertAlmostEqual(v, y / 30, places=4)

    def test_lane_count_follows_the_tags_the_pack_and_the_width(self):
        def count(width, tags):
            return self.lane_count(self.build([{'roads': [self.road(width, tags)]}])[0])
        # the way's own tag
        self.assertEqual(count(14, {'highway': 'secondary', 'lanes': '4', 'width': '14'}), 4)
        self.assertEqual(count(10.5, {'highway': 'secondary', 'lanes:forward': '2', 'lanes:backward': '1', 'width': '10.5'}), 3)
        # the lanes the pack carried over from the road's tagged sections (fast_sources.infer_lanes)
        self.assertEqual(count(10.5, {'highway': 'primary', 'oneway': 'yes', 'e2r:lanes': '3', 'width': '10.5'}), 3)
        # no count at all: read off the width, in pairs on a two-way road
        self.assertEqual(count(14, {'highway': 'secondary', 'width': '14'}), 4)
        self.assertEqual(count(7, {'highway': 'secondary', 'width': '7'}), 2)
        self.assertEqual(count(11, {'highway': 'secondary', 'width': '11'}), 2)
        self.assertEqual(count(7.5, {'highway': 'primary', 'oneway': 'yes', 'width': '7.5'}), 2)
        # never a lane under 2.5 m
        self.assertEqual(count(6, {'highway': 'residential', 'lanes': '4'}), 2)
        self.assertEqual(count(4, {'highway': 'service', 'width': '4'}), 1)
        # (an untagged service way is drawn 5 m wide, a yard's driveway: generator ROADS.YARD)
        self.assertEqual(count(4, {'highway': 'service'}), 2)

    def marks(self, width, tags):
        manifest = self.build([{'roads': [self.road(width, tags)]}])[0]
        return self.lanes_across(manifest, ('e2rf_mark',), x=250.5)

    def test_a_minor_streets_line_does_not_come_and_go_with_the_lanes_tag(self):
        # 'lanes=2' on a residential street is the default written out: no centre line either way
        self.assertEqual(self.marks(6, {'highway': 'residential'}), [])
        self.assertEqual(self.marks(6, {'highway': 'residential', 'lanes': '2'}), [])
        self.assertEqual(self.marks(6, {'highway': 'unclassified', 'lanes:forward': '1', 'lanes:backward': '1'}), [])
        # the map says it is painted, or the street has three lanes and more
        self.assertEqual(len(self.marks(5.8, {'highway': 'residential', 'lanes': '2', 'lane_markings': 'yes'})), 1)
        self.assertEqual(len(self.marks(9, {'highway': 'residential', 'lanes': '3', 'width': '9'})), 2)
        # a main road is painted with or without the tag
        self.assertEqual(len(self.marks(5.8, {'highway': 'tertiary'})), 1)
        self.assertEqual(len(self.marks(5.8, {'highway': 'tertiary', 'lanes': '2'})), 1)
        self.assertEqual(self.marks(5.8, {'highway': 'tertiary', 'lanes': '2', 'lane_markings': 'no'}), [])

    def test_the_lines_lie_on_the_seams_between_the_lanes(self):
        tags = {'highway': 'secondary', 'lanes': '4', 'width': '14'}
        manifest = self.build([{'roads': [self.road(14, tags)]}])[0]
        # four lanes of 3.5 m across 14 m: the sheet repeats four times, its seams 3.5 m apart
        self.assertEqual(self.lane_count(manifest), 4)
        self.assertEqual(self.lanes_across(manifest), [(243.0, 257.0)])
        lines = self.lanes_across(manifest, ('e2rf_mark',), x=250.5)
        centres = sorted({round((a + b) / 2, 2) for a, b in lines})
        # a dashed line on each seam, a double solid one astride the centre, and the two edge lines
        for seam in (246.5, 253.5):
            self.assertIn(seam, centres)
        self.assertIn(249.9, centres)
        self.assertIn(250.1, centres)

    def test_other_packs_and_distant_tiles_keep_the_plain_asphalt(self):
        road = self.road(7, {'highway': 'tertiary', 'lanes': '2'})
        cells = [{'roads': [road]}]
        other = self.build(cells, realStyle=False)[0]
        self.assertEqual(self.triangles(other, LANE_KINDS), [])
        self.assertAlmostEqual(sum(area(t) for t in self.triangles(other, ('e2rf_road',))), 7 * 500, places=3)
        off = self.build(cells, tune={'lanes': 0})[0]
        self.assertEqual(self.triangles(off, LANE_KINDS), [])
        self.assertAlmostEqual(sum(area(t) for t in self.triangles(off, ('e2rf_road',))), 7 * 500, places=3)
        # a far tile draws its roads into the scene layer, as plain quads
        for manifest in self.build(cells, far=True)[:2]:
            self.assertEqual(self.triangles(manifest, LANE_KINDS), [])

    def test_graded_roads_and_tracks_are_not_lanes(self):
        for tags in ({'highway': 'unclassified', 'surface': 'gravel'}, {'highway': 'track'},
                     {'highway': 'residential', 'surface': 'sett'}):
            manifest = self.build([{'roads': [self.road(5, tags)]}])[0]
            self.assertEqual(self.triangles(manifest, LANE_KINDS), [], tags)

    def test_a_climbing_road_is_lit_as_a_slope(self):
        # 10 % up to the east: the normal leans back west by the slope
        road = self.road(7, {'highway': 'tertiary'}, z0=20, z1=80)
        manifest = self.build([{'roads': [road]}])[0]
        want = math.hypot(.1, 1)
        seen = 0
        for x, y, z, u, v, nx, ny, nz in self.corners(manifest, ('e2rf_road_lane',)):
            if 100 < x < 400:
                self.assertAlmostEqual(nx, -.1 / want, places=3)
                self.assertAlmostEqual(ny, 0, places=5)
                self.assertAlmostEqual(nz, 1 / want, places=3)
                seen += 1
        self.assertGreater(seen, 20)

    def joined(self, wide_tags, narrow_tags, wide=10.5, narrow=7.0, split=250, x0=-50, x1=550, **options):
        """A wide way running on into a narrow one at x = split, no junction between them."""
        west = self.road(wide, wide_tags, x0=x0, x1=split)
        east = self.road(narrow, narrow_tags, x0=split, x1=x1)
        west.update(id='west', nodes=[1, 2])
        east.update(id='east', nodes=[2, 3])
        return self.build([{'roads': [west, east]}], **options)[0]

    def edge_at(self, manifest, x, materials=LANE_KINDS + PLAIN_KINDS, eps=1e-6):
        """The asphalt's northern edge at a cross-section, read off the triangles' own edges."""
        best = None
        for tri in self.triangles(manifest, materials):
            for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                if min(a[0], b[0]) - eps <= x <= max(a[0], b[0]) + eps and abs(b[0] - a[0]) > eps:
                    y = a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])
                    best = y if best is None else max(best, y)
        return best

    def test_a_wider_way_narrows_to_the_way_it_runs_on_into(self):
        three = {'highway': 'secondary', 'lanes': '3', 'oneway': 'yes', 'width': '10.5'}
        two = {'highway': 'secondary', 'lanes': '2', 'oneway': 'yes', 'width': '7'}
        manifest = self.joined(three, two)
        # the two edges meet at the join: no step of 1.75 m
        self.assertAlmostEqual(self.edge_at(manifest, 250 - 1e-3), 253.5, places=2)
        self.assertAlmostEqual(self.edge_at(manifest, 250 + 1e-3), 253.5, places=2)
        # the flare ends on the strip's first point 35 m or more from the join (40 m here: a knot
        # every 20 m), one straight edge; then the full width. The narrow way keeps its own.
        self.assertAlmostEqual(self.edge_at(manifest, 250 - 20), 253.5 + 1.75 / 2, places=2)
        self.assertAlmostEqual(self.edge_at(manifest, 250 - 30), 253.5 + 1.75 * .75, places=2)
        self.assertAlmostEqual(self.edge_at(manifest, 250 - 40), 255.25, places=2)
        self.assertAlmostEqual(self.edge_at(manifest, 100), 255.25, places=2)
        self.assertAlmostEqual(self.edge_at(manifest, 400), 253.5, places=2)
        # without the taper: the step the wide way ended in
        step = self.joined(three, two, tune={'taper': 0})
        self.assertAlmostEqual(self.edge_at(step, 250 - 1e-3), 255.25, places=2)

    def test_the_lanes_squeeze_through_the_flare_and_their_lines_wait_for_its_end(self):
        three = {'highway': 'secondary', 'lanes': '3', 'oneway': 'yes', 'width': '10.5'}
        two = {'highway': 'secondary', 'lanes': '2', 'oneway': 'yes', 'width': '7'}
        manifest = self.joined(three, two)
        # three lanes all the way, squeezed into the narrowed carriageway at the join
        # (the wide way: 300 m of it lie before the join, v over 10 repeats)
        near = [c for c in self.corners(manifest, LANE_KINDS) if 229.9 < c[0] < 250.001 and c[4] > 5]
        at_join = sorted({(round(c[1], 3), round(c[3], 3)) for c in near if abs(c[0] - 250) < 1e-6})
        self.assertEqual(at_join, [(246.5, 3.0), (253.5, 0.0)])
        self.assertEqual(self.lane_count(manifest, x=100), 3)
        self.assertEqual(self.lanes_across(manifest, x=100), [(244.75, 255.25)])

        def lines(x):
            return sorted({round((a + b) / 2, 1) for a, b in self.lanes_across(manifest, ('e2rf_mark',), x=x)})
        # the wide way's two lane lines begin where the flare ends; its edge lines follow the edge
        self.assertEqual(lines(95.5), [245.1, 248.2, 251.8, 254.9])     # (a dash every 12 m: one lies here)
        # in the flare (a dash would lie at x = 238..241): nothing between the lanes, and the edge
        # lines run in with the edges
        paint = [[sum(c[k] for c in tri) / 3 for k in (0, 1)] for tri in self.triangles(manifest, ('e2rf_mark',))]
        flare = [y for x, y in paint if 211 < x < 249]
        self.assertTrue(flare)
        self.assertFalse([y for y in flare if 247.5 < y < 252.5])
        self.assertTrue([y for y in flare if 253.0 < y < 254.9])
        self.assertTrue([y for y in flare if 245.1 < y < 247.0])

    def test_sidewalks_and_verges_follow_the_narrowing_edge(self):
        three = {'highway': 'secondary', 'lanes': '3', 'oneway': 'yes', 'width': '10.5', 'sidewalk': 'both'}
        two = {'highway': 'secondary', 'lanes': '2', 'oneway': 'yes', 'width': '7', 'sidewalk': 'both'}
        manifest = self.joined(three, two)
        # the curb starts where the asphalt ends, at the join as along the wide way
        for x, edge in ((250 - 1e-3, 253.5), (100, 255.25)):
            curb = [y for tri in self.triangles(manifest, ('e2rf_curb',)) for px, y, *_ in tri
                    if abs(px - x) < 12 and y > 250]
            self.assertTrue(curb)
            if x == 100:
                self.assertAlmostEqual(min(curb), edge, places=2)
        inner = self.edge_at(manifest, 250 - 1e-3, ('e2rf_curb',))
        self.assertAlmostEqual(inner, 253.5 + .25, places=2)

    def test_the_navgraph_has_the_lanes_that_are_drawn(self):
        def lanes(width, tags, **options):
            nav = self.build([{'roads': [self.road(width, tags)]}], **options)[3]
            return nav.segments[1][4]
        self.assertEqual(lanes(7, {'highway': 'tertiary'}), '-+')
        self.assertEqual(lanes(14, {'highway': 'secondary', 'width': '14'}), '--++')
        self.assertEqual(lanes(10.5, {'highway': 'primary', 'oneway': 'yes', 'e2r:lanes': '3', 'width': '10.5'}), '+++')
        self.assertEqual(lanes(10.5, {'highway': 'secondary', 'lanes:forward': '2', 'lanes:backward': '1', 'width': '10.5'}), '-++')


if __name__ == '__main__':
    unittest.main()
