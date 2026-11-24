"""An arch through a house (generator.lua BLD.ARCH): a road tagged tunnel=building_passage opens
the walls it crosses, in what is drawn and in the shell the car meets; needs lupa."""
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

LUA = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r'

GROUND = 20
TERRAIN = {'rect': [-500, -500, 1000, 1000], 'nx': 2, 'ny': 2, 'heights': [GROUND] * 4}
# a block 100 m long and 20 m deep, the way into its yard under its middle
BLOCK = {'id': 'b', 'height': 15, 'tags': {'building': 'apartments'},
         'rings': [[[150, 190], [250, 190], [250, 210], [150, 210]]]}


def road(ident, points, **tags):
    return {'id': ident, 'width': 4, 'points': [[x, y, GROUND] for x, y in points], 'tags': {'highway': 'service', **tags}}


def hit(orig, dest, tri):
    """Does the segment orig -> dest cross the triangle (either face)."""
    a, b, c = tri
    d = [dest[k] - orig[k] for k in range(3)]
    e1, e2 = [b[k] - a[k] for k in range(3)], [c[k] - a[k] for k in range(3)]
    h = [d[1] * e2[2] - d[2] * e2[1], d[2] * e2[0] - d[0] * e2[2], d[0] * e2[1] - d[1] * e2[0]]
    det = sum(e1[k] * h[k] for k in range(3))
    if abs(det) < 1e-12:
        return False
    s = [orig[k] - a[k] for k in range(3)]
    u = sum(s[k] * h[k] for k in range(3)) / det
    q = [s[1] * e1[2] - s[2] * e1[1], s[2] * e1[0] - s[0] * e1[2], s[0] * e1[1] - s[1] * e1[0]]
    v = sum(d[k] * q[k] for k in range(3)) / det
    t = sum(e2[k] * q[k] for k in range(3)) / det
    return u >= 0 and v >= 0 and u + v <= 1 and 0 <= t <= 1


class ArchTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.generator = self.lua.execute((LUA / 'generator.lua').read_text(encoding='utf8'))

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def scene(self, roads, building=BLOCK, **options):
        options.setdefault('relief', False)
        options.setdefault('land', False)
        options.setdefault('maxTrees', 0)
        options.setdefault('maxGrass', 0)
        options['tune'] = {'lanes': 0, 'crown': 0, 'ruts': 0}
        cell = {'buildings': [building], 'roads': roads, 'terrain': TERRAIN}
        scene = self.generator.build(self.table([cell]), 0, 0, self.table(options))[1]
        drawn, met = [], []
        for item in scene['items'].values():
            if item.kind != 'proc':
                continue
            ox, oy, oz = item.pos[1], item.pos[2], item.pos[3]
            for mesh in item.meshes.values():
                verts, faces = mesh.verts, list(mesh.faces.values())
                tris = []
                for k in range(0, len(faces), 3):
                    tris.append(tuple((verts[f.v + 1].x + ox, verts[f.v + 1].y + oy, verts[f.v + 1].z + oz) for f in faces[k:k + 3]))
                name = mesh.material
                if name == 'e2rf_col_bldg':
                    met += tris
                elif name.startswith(('e2rf_wall_', 'e2rf_kw_', 'e2rf_hw_', 'e2rf_plinth', 'e2rf_clad_', 'e2rf_sh_')):
                    drawn += tris
        return drawn, met

    def crossings(self, tris, orig, dest):
        return sum(1 for tri in tris if hit(orig, dest, tri))

    WAYS = [road('in', [(200, 100), (200, 190)]), road('arch', [(200, 190), (200, 210)], tunnel='building_passage'),
            road('yard', [(200, 210), (200, 300)])]

    def test_the_way_under_a_house_is_open_in_what_is_drawn_and_in_the_shell(self):
        drawn, met = self.scene(self.WAYS)
        closed_drawn, closed_met = self.scene(self.WAYS, arches=False)
        for x in (198.2, 200, 201.8):
            for z in (GROUND + .4, GROUND + 2, GROUND + 3.8):
                a, b = (x, 150, z), (x, 250, z)
                self.assertEqual(self.crossings(drawn, a, b), 0, (x, z))
                self.assertEqual(self.crossings(met, a, b), 0, (x, z))
                # without the arch the house stands whole across the way: two walls, drawn and met
                self.assertGreaterEqual(self.crossings(closed_drawn, a, b), 2, (x, z))
                self.assertEqual(self.crossings(closed_met, a, b), 2, (x, z))
        # over the opening the wall goes on, drawn and met
        a, b = (200, 150, GROUND + 6), (200, 250, GROUND + 6)
        self.assertGreaterEqual(self.crossings(drawn, a, b), 2)
        self.assertEqual(self.crossings(met, a, b), 2)
        # beside the opening the wall is as it was
        a, b = (180, 150, GROUND + 2), (180, 250, GROUND + 2)
        self.assertEqual(self.crossings(met, a, b), 2)
        self.assertGreaterEqual(self.crossings(drawn, a, b), 2)

    def test_the_passage_has_its_own_walls_and_ceiling(self):
        drawn, met = self.scene(self.WAYS)
        # across the passage, under the house: a wall either side, drawn and met (half the
        # paving and 0.6 m beside it from the way's middle)
        a, b = (190, 200, GROUND + 2), (210, 200, GROUND + 2)
        self.assertEqual(self.crossings(met, a, b), 2)
        self.assertEqual(self.crossings(drawn, a, b), 2)
        for tris in (met,):
            xs = sorted({round(c[0], 1) for tri in tris for c in tri if 189.99 < c[1] < 210.01 and 195 < c[0] < 205})
            self.assertEqual(len(xs), 2, xs)
            self.assertAlmostEqual(xs[0] + xs[1], 400, places=1)
            self.assertTrue(2.5 <= 200 - xs[0] <= 3.5, xs)
        # the ceiling 4.3 m over the road, and nothing of the shell in the way under it
        up, down = (200.7, 203.1, GROUND + .5), (200.7, 203.1, GROUND + 9)
        self.assertEqual(self.crossings(drawn, up, down), 1)
        ceiling = [tri for tri in drawn if hit(up, down, tri)][0]
        self.assertAlmostEqual(ceiling[0][2], GROUND + 4.3, places=2)

    def test_a_wall_along_the_passage_and_a_low_shed_keep_their_walls(self):
        # a way along the house's long wall, a metre inside it: no wall is square to it but the ends
        along = [road('arch', [(150, 191), (250, 191)], tunnel='building_passage')]
        _, met = self.scene(along)
        self.assertEqual(self.crossings(met, (200, 180, GROUND + 2), (200, 220, GROUND + 2)) >= 2, True)
        # a shed 3 m high on a track: not driven under
        shed = dict(BLOCK, height=3)
        _, met = self.scene(self.WAYS, building=shed)
        self.assertEqual(self.crossings(met, (200, 150, GROUND + 1), (200, 250, GROUND + 1)), 2)

    def test_an_oblique_way_opens_a_wider_run_of_the_wall(self):
        ways = [road('arch', [(190, 190), (210, 210)], tunnel='building_passage')]
        drawn, met = self.scene(ways)
        # along the way itself, and 2 m either side of it across: open
        for off in (-2, 0, 2):
            a = (170 + off * .7071, 170 - off * .7071, GROUND + 2)
            b = (230 + off * .7071, 230 - off * .7071, GROUND + 2)
            self.assertEqual(self.crossings(met, a, b), 0, off)
            self.assertEqual(self.crossings(drawn, a, b), 0, off)
        # 6 m beside it the walls stand
        a, b = (170 + 6, 170 - 6, GROUND + 2), (230 + 6, 230 - 6, GROUND + 2)
        self.assertEqual(self.crossings(met, a, b), 2)


if __name__ == '__main__':
    unittest.main()
