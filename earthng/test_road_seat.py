"""A road seated on the land (generator.lua tune.seat: ROADS.FALL, ROADS.VERGE, ROADS.YARD); needs lupa."""
import math
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

SOURCE = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/generator.lua'
LIFT, KERB = .10, .12          # a road's surface over its profile, a kerb's top over the road
ROADS = ('e2rf_road', 'e2rf_road_major', 'e2rf_road_worn')
GROUND = ('e2rf_ground',)


def line(x0, y0, x1, y1, z0=20, z1=None):
    z1 = z0 if z1 is None else z1
    n = math.ceil(math.hypot(x1 - x0, y1 - y0) / 20)
    return [[x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n, z0 + (z1 - z0) * k / n] for k in range(n + 1)]


def blocks(levels=9, size=(60, 15), y0=(200, 290), tag='apartments'):
    """Buildings in two rows along x, clear of the roads between y 215 and 290."""
    out = []
    for row, y in enumerate(y0):
        for x in range(-100, 600, size[0] + 10):
            out.append({'id': f'b{row}_{x}', 'height': levels * 3, 'tags': {'building': tag, 'building:levels': str(levels)},
                        'rings': [[[x, y], [x + size[0], y], [x + size[0], y + size[1]], [x, y + size[1]]]]})
    return out


class RoadSeatTests(unittest.TestCase):
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
        options.setdefault('land', False)
        # (the crown and the ruts off unless a test asks: the lean and the land are read off flat strips)
        options['tune'] = {'lanes': 0, 'crown': 0, 'ruts': 0, **(options.get('tune') or {})}
        return self.generator.build(self.table(cells), i, j, self.table(options))

    def triangles(self, manifest, materials):
        out = []
        for item in (manifest['items'] or self.lua.table()).values():
            for mesh in (item['meshes'] or self.lua.table()).values():
                if mesh.material in materials:
                    pts = [(mesh.verts[mesh.faces[k].v + 1].x + item.pos[1], mesh.verts[mesh.faces[k].v + 1].y + item.pos[2],
                            mesh.verts[mesh.faces[k].v + 1].z + item.pos[3]) for k in range(1, len(mesh.faces) + 1)]
                    out += [pts[k:k + 3] for k in range(0, len(pts), 3)]
        return out

    def surface(self, triangles, x, y):
        """The highest of the triangles over (x, y), or None."""
        best = None
        for (ax, ay, az), (bx, by, bz), (cx, cy, cz) in triangles:
            den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(den) < 1e-12:
                continue
            u = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / den
            v = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / den
            if u >= -1e-9 and v >= -1e-9 and u + v <= 1 + 1e-9:
                z = u * az + v * bz + (1 - u - v) * cz
                best = z if best is None else max(best, z)
        return best

    def cell(self, *roads, heights=20, **extra):
        return {'roads': list(roads), 'terrain': {'rect': [-500, -500, 1000, 1000], 'nx': 2, 'ny': 2, 'heights': [heights] * 4},
                **extra}

    def road(self, ident, y, z=20, width=4, x0=-100, x1=600, **tags):
        return {'id': ident, 'width': width, 'points': line(x0, y, x1, y, z),
                'tags': {'highway': 'service', **{k.replace('_', ':'): v for k, v in tags.items()}}}

    def test_the_land_comes_up_to_a_seated_road_and_stays_under_it(self):
        cell = self.cell(self.road('r', 250))
        seated = self.build([cell])[0]
        ground, asphalt = self.triangles(seated, GROUND), self.triangles(seated, ROADS)
        self.assertAlmostEqual(self.surface(asphalt, 250, 250), 20 + LIFT, places=6)
        # a hand's breadth under the edge, where it stood a quarter of a metre and more
        for y in (253, 256, 262, 290):
            self.assertLess(20 + LIFT - self.surface(ground, 250, y), .08, y)
        # and never through the asphalt
        for x in range(10, 500, 7):
            for y in (248.2, 250, 251.8):
                self.assertLess(self.surface(ground, x, y), self.surface(asphalt, x, y) - .03)
        # another art pack keeps the road it had: the ground 0.25 m under the profile
        old = self.triangles(self.build([cell], realStyle=False)[0], GROUND)
        self.assertAlmostEqual(self.surface(old, 250, 290), 19.75, places=6)
        self.assertAlmostEqual(self.surface(self.triangles(self.build([cell], tune={'seat': 0})[0], GROUND), 250, 290),
                               19.75, places=6)

    def test_a_road_leans_towards_the_road_beside_it(self):
        # two driveways 20 m apart, the northern 0.6 m higher: 3 % between them
        low, high = self.road('low', 240, 20), self.road('high', 260, 20.6)
        asphalt = self.triangles(self.build([self.cell(low, high)])[0], ROADS)
        for y, z in ((240, 20), (260, 20.6)):
            south, mid, north = (self.surface(asphalt, 250, y + o) for o in (-1.9, 0, 1.9))
            self.assertAlmostEqual(mid, z + LIFT, places=3)            # the centre line keeps its profile
            # one neighbour, on one side: FALL.lone of the slope to it
            self.assertAlmostEqual((north - south) / 3.8, .03 * .75, places=3)
        # the land between them is the slope from one to the other, not two terraces and a step
        ground = self.triangles(self.build([self.cell(low, high)])[0], GROUND)
        for y in (244, 250, 256):
            self.assertAlmostEqual(self.surface(ground, 250, y), 20 + .6 * (y - 240) / 20, delta=.12)
        # no more than its class is built with, however steep the land (2 m in 20: 10 %)
        steep = self.triangles(self.build([self.cell(low, self.road('high', 260, 22))])[0], ROADS)
        lean = (self.surface(steep, 250, 241.9) - self.surface(steep, 250, 238.1)) / 3.8
        self.assertAlmostEqual(lean, .035, places=3)

    def test_what_does_not_lean(self):
        flat = lambda tris, y: abs(self.surface(tris, 250, y + 1.9) - self.surface(tris, 250, y - 1.9)) < 1e-6
        # a road alone, a trunk road, a bridge, a road of another art pack
        alone = self.triangles(self.build([self.cell(self.road('r', 250))])[0], ROADS)
        self.assertTrue(flat(alone, 250))
        trunk = dict(self.road('t', 240), tags={'highway': 'trunk', 'sidewalk': 'no'})
        cell = self.cell(trunk, self.road('high', 260, 20.6))
        self.assertTrue(flat(self.triangles(self.build([cell])[0], ROADS + ('e2rf_road_major',)), 240))
        cell = self.cell(self.road('low', 240), self.road('high', 260, 20.6))
        self.assertTrue(flat(self.triangles(self.build([cell], realStyle=False)[0], ROADS), 240))
        # a street it meets ahead is not beside it: the arms of a crossing stay level
        cross = self.cell({'id': 'a', 'width': 4, 'nodes': [1, 2], 'points': line(-100, 250, 250, 250), 'tags': {'highway': 'service'}},
                          {'id': 'b', 'width': 4, 'nodes': [2, 3], 'points': line(250, 250, 250, 600, 20, 23), 'tags': {'highway': 'service'}})
        arms = self.triangles(self.build([cross])[0], ROADS)
        self.assertLess(abs(self.surface(arms, 150, 251.9) - self.surface(arms, 150, 248.1)), .02)

    def test_paint_lies_on_a_leaning_road(self):
        tags = {'highway': 'residential', 'sidewalk': 'no', 'lane_markings': 'yes'}
        street = {'id': 's', 'width': 7, 'points': line(-100, 240, 600, 240), 'tags': tags}
        road = self.build([self.cell(street, self.road('high', 262, 20.6))])[0]
        asphalt, paint = self.triangles(road, ROADS), self.triangles(road, ('e2rf_mark',))
        self.assertTrue(paint)
        lean = (self.surface(asphalt, 250, 243) - self.surface(asphalt, 250, 237)) / 6
        self.assertGreater(lean, .01)
        for tri in paint:
            for x, y, z in tri:
                if 20 < x < 480:
                    over = z - self.surface(asphalt, x, y)
                    self.assertGreater(over, .004, (x, y))
                    self.assertLess(over, .02, (x, y))

    def test_a_verge_is_as_wide_as_the_height_it_takes_up(self):
        # level land: a strip 1.2 m wide, where every verge was 3 m
        ground = self.triangles(self.build([self.cell(self.road('r', 250))])[0], GROUND)
        # (an untagged service way is 5 m wide: its edge 2.5 m from the centre line)
        edge = [t for t in ground if any(abs(abs(p[1] - 250) - 2.5) < 1e-6 for p in t)]
        self.assertTrue(edge)
        self.assertAlmostEqual(max(abs(p[1] - 250) for t in edge for p in t), 3.7, places=6)

    def test_a_bank_is_a_berm_and_a_slope_or_a_cut_and_easy_ground(self):
        # ROADS.VERGE on a road along x at 10 m, its paving's edge 2 m from the centre line: the
        # land `drop` m under it to the north (left), `rise` m over it to the south
        verge = self.lua.eval('''function(V, north, south)
          local strip = {edge = function(k, offset, dz) return {k * 10, offset, 10 + (dz or 0)} end}
          local function ground(x, y) return 10 + (y > 0 and north or south) end
          local function up() return 0, 0, 1 end
          local out = {}
          for _, sign in ipairs({1, -1}) do
            local rows = {}
            for q, quad in ipairs(V.quads(strip, 1, sign, 2, 0, ground, up)) do
              for c, p in ipairs(quad) do rows[#rows + 1] = {q, p[1], p[2], p[3], p[9] or 0, p[8] or 0} end
            end
            out[#out + 1] = rows
          end
          return out
        end''')
        def quads(north, south):
            sides = verge(self.generator.VERGE, north, south)
            return [[tuple(row.values()) for row in side.values()] for side in sides.values()]
        # level with the road within a hand: one quad 1.2 m wide, its far corners the ground's
        flush, _ = quads(-.1, -.1)
        self.assertEqual({q for q, *_ in flush}, {1})
        self.assertEqual(sorted({round(y, 3) for _, _, y, *_ in flush}), [2, 3.2])
        self.assertEqual({round(z, 3) for _, _, y, z, mark, _ in flush if mark == 1}, {9.9})
        self.assertEqual({y for _, _, y, _, mark, _ in flush if mark == 1}, {3.2})
        # a metre down: four metres out, a berm that falls an eighth of it over the first 30 %
        fill, cut = quads(-1, .8)
        self.assertEqual({q for q, *_ in fill}, {1, 2})
        self.assertEqual(sorted({(round(y, 3), round(z, 3)) for _, _, y, z, *_ in fill}), [(2, 10), (3.2, 9.88), (6, 9)])
        self.assertTrue(all(nz > .05 for *_, nz in fill))              # lit as a bank, not as flat ground
        # 0.8 m up: 3.5 m out (steps of half a metre), the bank first, the easy ground after
        self.assertEqual(sorted({(round(y, 3), round(z, 3)) for _, _, y, z, *_ in cut}),
                         [(-5.5, 10.8), (-3.05, 10.44), (-2, 10)])
        # both stand over the straight line between their ends: the ground lattice under them
        for rows, sign in ((fill, 1), (cut, -1)):
            (y0, z0), (y1, z1) = [(y, z) for _, _, y, z, mark, _ in rows if abs(abs(y) - 2) < 1e-9][0], \
                [(y, z) for _, _, y, z, mark, _ in rows if mark == 1][0]
            for _, _, y, z, *_ in rows:
                self.assertGreaterEqual(z + 1e-9, z0 + (z1 - z0) * (y - y0) / (y1 - y0))
        # a thing set down on a verge stands on it, not on the ground under it
        beside = self.generator.VERGE.beside
        self.assertAlmostEqual(beside(9, 10, 2), 9.5)                  # half of the 4 m a metre takes
        self.assertAlmostEqual(beside(9.9, 10, .6), 9.95)
        self.assertAlmostEqual(beside(9, 10, 5), 9)

    def test_asphalt_for_two_directions_is_crowned(self):
        street = {'id': 's', 'width': 7, 'points': line(-100, 250, 600, 250),
                  'tags': {'highway': 'residential', 'sidewalk': 'no', 'lane_markings': 'yes'}}
        road = self.build([self.cell(street)], tune={'crown': .02})[0]
        asphalt = self.triangles(road, ROADS)
        # the middle 2 % of the half width over the edges, which stay on the profile
        self.assertAlmostEqual(self.surface(asphalt, 250, 250), 20 + LIFT + .02 * 3.5, places=4)
        self.assertAlmostEqual(self.surface(asphalt, 250, 251.75), 20 + LIFT + .02 * 1.75, places=4)
        for y in (246.5, 253.5):
            self.assertAlmostEqual(self.surface(asphalt, 250, y + (.001 if y < 250 else -.001)), 20 + LIFT, places=3)
        # the paint lies on the crown
        for tri in self.triangles(road, ('e2rf_mark',)):
            for x, y, z in tri:
                if 20 < x < 480:
                    self.assertAlmostEqual(z - self.surface(asphalt, x, y), .008, delta=.004)
        # a strip's end is level: a junction's fan meets it with no lip in the middle of the mouth
        a = {'id': 'a', 'width': 7, 'nodes': [1, 2], 'points': line(-100, 250, 250, 250), 'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        b = {'id': 'b', 'width': 7, 'nodes': [2, 3], 'points': line(250, 250, 250, 600), 'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        c = {'id': 'c', 'width': 7, 'nodes': [2, 4], 'points': line(250, 250, 250, -100), 'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        tee = self.triangles(self.build([self.cell(a, b, c)], tune={'crown': .02})[0], ROADS)
        for x in (244.35, 244.45, 246, 249):                             # the end of `a` (its cut: 5.6 m) and the fan
            self.assertAlmostEqual(self.surface(tee, x, 250), 20 + LIFT, delta=.002, msg=x)
        self.assertAlmostEqual(self.surface(tee, 150, 250), 20 + LIFT + .07, places=3)
        # one direction, a narrow driveway, another art pack: flat
        for extra, options in (({'oneway': 'yes'}, {}), ({}, {'realStyle': False})):
            flat = dict(street, tags={**street['tags'], **extra})
            tris = self.triangles(self.build([self.cell(flat)], tune={'crown': .02}, **options)[0], ROADS)
            self.assertAlmostEqual(self.surface(tris, 250, 250), 20 + LIFT, places=6)
        # an avenue's middle rises 12 cm at most
        wide = dict(street, width=30, tags={'highway': 'primary', 'sidewalk': 'no'})
        tris = self.triangles(self.build([self.cell(wide)], tune={'crown': .02})[0], ROADS + ('e2rf_road_major',))
        self.assertAlmostEqual(self.surface(tris, 250, 250), 20 + LIFT + .12, places=4)

    def test_the_lane_sheet_runs_on_across_a_crown(self):
        street = {'id': 's', 'width': 7, 'points': line(-100, 250, 600, 250), 'tags': {'highway': 'residential', 'sidewalk': 'no'}}
        road = self.build([self.cell(street)], tune={'crown': .02, 'lanes': 1})[0]
        corners = []
        for item in road['items'].values():
            for mesh in item['meshes'].values():
                if mesh.material == 'e2rf_road_lane':
                    for k in range(1, len(mesh.faces) + 1):
                        f = mesh.faces[k]
                        corners.append((mesh.verts[f.v + 1].y + item.pos[2], mesh.uvs[f.u + 1].u, mesh.verts[f.v + 1].z + item.pos[3]))
        self.assertTrue(corners)
        # u: 0 on the left edge, the lane count on the right, half of it on the ridge
        us = {round(y, 3): round(u, 4) for y, u, _ in corners}
        self.assertEqual(us, {253.5: 0, 250: 1, 246.5: 2})
        self.assertAlmostEqual(max(z for y, _, z in corners if abs(y - 250) < 1e-6), 20 + LIFT + .07, places=4)

    def test_an_unpaved_road_is_driven_into_ruts(self):
        dirt = {'id': 'd', 'width': 3.5, 'points': line(-100, 250, 600, 250), 'tags': {'highway': 'residential', 'surface': 'dirt'}}
        road = self.build([self.cell(dirt)], tune={'ruts': 1})[0]
        bed = self.triangles(road, ('e2rf_road_dirt',))
        self.assertTrue(bed)
        deep, humps = [], []
        for x in range(30, 480, 20):
            # (a dirt road's centre line rises and falls on its own: the bed's edge is the measure)
            edge = self.surface(bed, x, 251.749)
            self.assertAlmostEqual(self.surface(bed, x, 248.251), edge, delta=.004)       # level from edge to edge
            ruts = [self.surface(bed, x, 250 + o) for o in (-.75, .75)]
            deep += [edge - z for z in ruts]
            humps.append(self.surface(bed, x, 250) - edge)
        # under each wheel path, more and less from point to point; a hump between them
        self.assertGreater(min(deep), .05 * .4)
        self.assertLess(max(deep), .05 * 1.31)
        self.assertGreater(max(deep) - min(deep), .01)
        self.assertTrue(all(.008 < h < .035 for h in humps), humps)
        # the ground stays under the deepest rut
        ground = self.triangles(road, GROUND)
        for x in range(30, 480, 20):
            for o in (-.75, 0, .75):
                self.assertLess(self.surface(ground, x, 250 + o), self.surface(bed, x, 250 + o) - .01)
        # gravel is shallower, asphalt has none, and another art pack's dirt road is the flat strip it was
        gravel = self.triangles(self.build([self.cell(dict(dirt, tags={'highway': 'residential', 'surface': 'gravel'}))],
                                           tune={'ruts': 1})[0], ('e2rf_road_gravel',))
        self.assertLess(self.surface(gravel, 250, 251.749) - self.surface(gravel, 250, 250.75), .025 * 1.31)
        old = self.triangles(self.build([self.cell(dirt)], tune={'ruts': 1}, realStyle=False)[0], ('e2rf_road_dirt',))
        self.assertAlmostEqual(self.surface(old, 250, 250.75), self.surface(old, 250, 251.749), places=6)

    def test_open_land_has_humps_a_fine_lattice_can_hold(self):
        cell = {'terrain': {'rect': [-500, -500, 1000, 1000], 'nx': 2, 'ny': 2, 'heights': [50.0] * 4}}
        def heights(**options):
            tris = self.triangles(self.build([cell], relief=True, **options)[0], GROUND)
            return {(round(x, 3), round(y, 3)): z for t in tris for x, y, z in t}
        fine, coarse = heights(), heights(realStyle=False)
        self.assertEqual(len(fine), 41 * 41)                             # nodes every 12.5 m
        self.assertEqual(len(coarse), 21 * 21)
        # the same land with the fine humps over it: at the nodes both have, up to a quarter of a
        # metre apart (and the 0.29 m between the two packs' grounds)
        diff = [fine[k] - coarse[k] - .29 for k in coarse]
        self.assertGreater(max(diff) - min(diff), .2)
        self.assertLess(max(map(abs, diff)), .251)
        # neighbouring nodes differ: no flat cell
        step = [abs(fine[(x, y)] - fine[(x + 12.5, y)]) for (x, y) in fine if (x + 12.5, y) in fine]
        self.assertGreater(sorted(step)[len(step) // 2], .012)
        self.assertGreater(max(step), .08)

    def test_a_towns_asphalt_is_cracked_patched_and_worn(self):
        # a yard's driveway among blocks of flats beside a higher street: it leans, and its covers,
        # patches and wear lie on it as it leans
        drive = self.road('d', 240, width=6, x0=-400, x1=900)
        street = {'id': 's', 'width': 7, 'points': line(-400, 264, 900, 264, 20.7), 'tags': {'highway': 'residential'}}
        road = self.build([self.cell(drive, street, buildings=blocks(y0=(190, 300)))], tune={'crown': .02})[0]
        asphalt = self.triangles(road, ROADS)
        kinds = ('e2rf_crack_net', 'e2rf_crack_line', 'e2rf_wear', 'e2rf_patch', 'e2rf_manhole')
        found = {kind: self.triangles(road, (kind,)) for kind in kinds}
        self.assertTrue(all(found.values()), {k: len(v) for k, v in found.items()})
        self.assertGreater(self.surface(asphalt, 250, 242.5) - self.surface(asphalt, 250, 237.5), .05)   # it leans
        for kind, tris in found.items():
            for tri in tris:
                for x, y, z in tri:
                    under = self.surface(asphalt, x, y)
                    if under is not None and 5 < x < 495:
                        self.assertGreater(z - under, .002, (kind, x, y))
                        self.assertLess(z - under, .03, (kind, x, y))
        # within the carriageway, and none in another art pack
        on_drive = [p for kind in kinds[:3] for tri in found[kind] for p in tri if p[1] < 250]
        self.assertTrue(on_drive and all(237 - 1e-6 <= p[1] <= 243 + 1e-6 for p in on_drive))
        old = self.build([self.cell(drive, street, buildings=blocks(y0=(190, 300)))], realStyle=False)[0]
        self.assertFalse(any(self.triangles(old, (kind,)) for kind in kinds))

    def test_a_post_soviet_towns_sidewalks_are_block_paving_and_old_asphalt(self):
        def paving(highway, **options):
            street = {'id': 's', 'width': 7, 'points': line(-100, 250, 600, 250), 'tags': {'highway': highway, 'sidewalk': 'both'}}
            road = self.build([self.cell(street)], **options)[0]
            return {kind for kind in ('e2rf_sidewalk', 'e2rf_sidewalk_tile', 'e2rf_sidewalk_asphalt') if self.triangles(road, (kind,))}
        # block paving along a main street, cracked asphalt along the rest
        self.assertEqual(paving('secondary', country='ukraine'), {'e2rf_sidewalk_tile'})
        self.assertEqual(paving('residential', country='ukraine'), {'e2rf_sidewalk_asphalt'})
        # the game's concrete slabs in another country and in another art pack
        self.assertEqual(paving('secondary', country='united-kingdom'), {'e2rf_sidewalk'})
        self.assertEqual(paving('secondary', country='ukraine', realStyle=False), {'e2rf_sidewalk'})

    def test_no_blade_of_paving_stands_on_a_carriageway(self):
        # What the clip leaves of a sidewalk between two pieces of a junction's asphalt: a strip
        # 3 cm wide and 9 m long (0.27 m2, over CURB.tiny). Raised 12 cm with its faces it stood
        # across the junction, too thin to see and too high to cross.
        slab = self.lua.eval('''function(curbSlab, piece, on)
          local out = {}
          curbSlab(function(material, poly) out[#out + 1] = {material, poly[1][3]} end, 'sidewalk', {piece}, piece, {}, nil,
            function() return on end)
          return out
        end''')
        def drawn(piece, on):
            return [tuple(row.values()) for row in slab(self.generator.curbSlab, self.table(piece), on).values()]
        blade = [[0, 0, 20], [9, 0, 20], [9, .03, 20], [0, .03, 20]]
        stone = [[0, 0, 20], [9, 0, 20], [9, .25, 20], [0, .25, 20]]
        self.assertEqual(drawn(blade, True), [])                         # on the asphalt: not at all
        self.assertEqual(drawn(blade, False), [('sidewalk', 20)])        # beside it: flush, no faces
        self.assertEqual(drawn(stone, True), [])                         # nor a whole stone on a road
        self.assertEqual(drawn(stone, False), [('sidewalk', 20 + KERB)])  # beside it: raised as it was

    def test_two_ways_lean_as_one_where_they_meet_end_to_end(self):
        # one street in two ways (a tag changes at x = 250), a higher road beside the western half
        # only: each half for itself, the western leant and the eastern lay level, a step at the join
        west = {'id': 'w', 'width': 5, 'nodes': [1, 2], 'points': line(-100, 240, 250, 240), 'tags': {'highway': 'service', 'width': '5'}}
        east = {'id': 'e', 'width': 5, 'nodes': [2, 3], 'points': line(250, 240, 600, 240),
                'tags': {'highway': 'service', 'width': '5', 'surface': 'asphalt'}}
        high = {'id': 'h', 'width': 4, 'points': line(-100, 262, 250, 262, 20.7), 'tags': {'highway': 'service', 'width': '4'}}
        asphalt = self.triangles(self.build([self.cell(west, east, high)])[0], ROADS)
        lean = lambda x: self.surface(asphalt, x, 242.4) - self.surface(asphalt, x, 237.6)
        self.assertGreater(lean(120), .08)                               # the western half leans
        self.assertLess(abs(lean(420)), .01)                             # far along the eastern, level
        # across the join the edge runs on: no step between the two strips' ends
        for y in (237.6, 240, 242.4):
            self.assertLess(abs(self.surface(asphalt, 249.9, y) - self.surface(asphalt, 250.1, y)), .004, y)
        # reversed, the eastern way's left is the western's right: still one edge
        back = dict(east, nodes=[3, 2], points=list(reversed(east['points'])))
        asphalt = self.triangles(self.build([self.cell(west, back, high)])[0], ROADS)
        for y in (237.6, 240, 242.4):
            self.assertLess(abs(self.surface(asphalt, 249.9, y) - self.surface(asphalt, 250.1, y)), .004, y)

    def test_a_yards_driveway_is_kerbed_among_blocks_of_flats_only(self):
        drive = self.road('d', 250)
        kerbs = lambda **extra: self.triangles(self.build([self.cell(drive, **extra)])[0], ('e2rf_curb',))
        town = kerbs(buildings=blocks())
        self.assertTrue(town)
        tops = {round(p[2], 3) for t in town for p in t}
        self.assertIn(round(20 + LIFT + KERB, 3), tops)
        # the stone on both sides, a quarter of a metre wide, and the lawn from its top
        ys = {round(abs(p[1] - 250), 3) for t in town for p in t}
        self.assertEqual(ys, {2.5, 2.75})
        self.assertEqual({p[1] > 250 for t in town for p in t}, {True, False})
        ground = self.triangles(self.build([self.cell(drive, buildings=blocks())])[0], GROUND)
        self.assertAlmostEqual(self.surface(ground, 250, 252.76), 20 + LIFT + KERB, delta=.01)
        # open country, a street of private houses, a parking aisle, another art pack: none
        self.assertFalse(kerbs())
        self.assertFalse(kerbs(buildings=blocks(levels=1, size=(12, 10), tag='house')))
        aisle = dict(drive, tags={'highway': 'service', 'service': 'parking_aisle'})
        self.assertFalse(self.triangles(self.build([self.cell(aisle, buildings=blocks())])[0], ('e2rf_curb',)))
        self.assertFalse(self.triangles(self.build([self.cell(drive, buildings=blocks())], realStyle=False)[0], ('e2rf_curb',)))

    def test_an_untagged_service_way_is_as_wide_as_a_yards_driveway(self):
        def width(road, **options):
            tris = self.triangles(self.build([self.cell(road)], **options)[0], ROADS)
            return 2 * max(abs(p[1] - 250) for t in tris for p in t)
        plain = self.road('d', 250)
        self.assertAlmostEqual(width(plain), 5, places=6)
        self.assertAlmostEqual(width(dict(plain, width=3, tags={'highway': 'service', 'service': 'driveway'})), 3.5, places=6)
        # what the map says stays, and so does another art pack's road
        self.assertAlmostEqual(width(dict(plain, tags={'highway': 'service', 'width': '4'})), 4, places=6)
        self.assertAlmostEqual(width(dict(plain, width=3, tags={'highway': 'service', 'lanes': '1'})), 3, places=6)
        self.assertAlmostEqual(width(dict(plain, tags={'highway': 'service', 'service': 'parking_aisle'})), 4, places=6)
        self.assertAlmostEqual(width(plain, realStyle=False), 4, places=6)
        # the cell is every build's: its road is not the one made wider
        cell = self.table([self.cell(plain)])
        self.generator.build(cell, 0, 0, self.table({'relief': False}))
        self.assertEqual(cell[1].roads[1].width, 4)

    def test_two_tiles_draw_one_leaning_road_and_one_land(self):
        low, high = self.road('low', 240, 20, x0=-200, x1=1200), self.road('high', 262, 20.7, x0=-200, x1=1200)
        cells = [self.cell(low, high, buildings=blocks())]
        def border(manifest, materials):
            return sorted({(round(y, 4), round(z, 4)) for t in self.triangles(manifest, materials) for x, y, z in t
                           if abs(x - 500) < 1e-6 and 200 < y < 300})
        left, right = self.build(cells)[0], self.build(cells, i=1)[0]
        for materials in (ROADS, GROUND, ('e2rf_curb',)):
            self.assertTrue(border(left, materials), materials)
            self.assertEqual(border(left, materials), border(right, materials), materials)


if __name__ == '__main__':
    unittest.main()
