"""The wall of supporters (generator.lua BLD.supportersWall, supporters.lua), the flags of the
world's countries (flag_art.py, flag_lib.lua) and their tile on the proving ground
(proving_thanks.py); needs lupa."""
import re
import sys
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
LUA = HERE.parent / 'mod/lua/ge/extensions/e2r'

TERRAIN = {'rect': [-500, -500, 1000, 1000], 'nx': 2, 'ny': 2, 'heights': [20] * 4}
STREET = {'id': 'r', 'width': 6, 'points': [[100, 240, 20], [400, 240, 20]], 'tags': {'highway': 'residential'}}


class WallTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        source = (LUA / 'supporters.lua').read_text(encoding='utf8')
        self.lua.globals().supporters_source = source
        self.lua.execute("package.preload['ge/extensions/e2r/supporters'] = function() return assert(loadstring(supporters_source))() end")
        self.generator = self.lua.execute((LUA / 'generator.lua').read_text(encoding='utf8'))
        self.list = self.lua.eval("require('ge/extensions/e2r/supporters')")

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def letters(self, operator):
        tags = {'e2r_cat': 'billboard'}
        if operator:
            tags['operator'] = operator
        board = {'id': 'wall', 'kind': 'pin', 'pos': [250, 260, 20], 'tags': tags}
        cell = {'points': [board], 'roads': [STREET], 'terrain': TERRAIN}
        options = {'relief': False, 'land': False, 'maxTrees': 0, 'maxGrass': 0, 'tune': {'lanes': 0, 'crown': 0, 'ruts': 0}}
        scene = self.generator.build(self.table([cell]), 0, 0, self.table(options))[1]
        quads, xs, zs = 0, [], []
        for item in scene['items'].values():
            if item.kind != 'proc':
                continue
            for mesh in item.meshes.values():
                if mesh.material == 'e2rf_glyphs':
                    quads += len(mesh.faces) // 6
                    xs += [v.x + item.pos[1] for v in mesh.verts.values()]
                    zs += [v.z + item.pos[3] for v in mesh.verts.values()]
        return quads, xs, zs

    def test_the_list_names_the_supporters(self):
        names = list(self.list.names.values())
        self.assertEqual(names[:3], ['Adrian Burke', 'Demon Abis', 'Tyler Reid'])
        self.assertEqual(len(names), len(set(names)))
        # every letter of a name is in the glyph atlas (one that is not is set as a space)
        import fast_style
        for name in names + [self.list.title, self.list.thanks]:
            self.assertFalse(set(name) - set(fast_style.GLYPHS) - {' '}, name)

    def test_the_tagged_billboard_is_the_wall_with_every_name_on_both_faces(self):
        quads, xs, zs = self.letters('EarthNG supporters')
        texts = list(self.list.names.values()) + [self.list.title, self.list.thanks]
        self.assertEqual(quads, 2 * sum(len(t.replace(' ', '')) for t in texts))
        # a board tens of metres wide, its words from over a car's roof to a house's height
        self.assertGreater(max(xs) - min(xs), 20)
        self.assertGreater(min(zs), 20 + 2.6)
        self.assertGreater(max(zs) - min(zs), 6)
        # a billboard that is not tagged asks for support, as before
        plain, _, _ = self.letters(None)
        self.assertEqual(plain, 0)

    def test_the_board_grows_with_the_list(self):
        plan = self.generator.wallPlan
        few = plan(self.list)
        self.assertEqual((few.cols, few.rows), (2, 4))
        self.assertEqual(few.k, 1)
        wide = {}
        for count in (30, 120, 600):
            p = plan(self.table({'names': [f'Supporter Number {n}' for n in range(count)]}))
            self.assertGreaterEqual(p.cols * p.rows, count)
            self.assertLess(p.cols * p.rows, count + p.cols)
            wide[count] = p.wide
            # letters never under the smallest size; the board no wider than the limit until
            # they are at it
            self.assertGreaterEqual(1.05 * p.k, .45 - 1e-9)
            if 1.05 * p.k > .45 + 1e-6:
                self.assertLessEqual(p.wide, 64 + 1e-6)
            self.assertLess(abs(p.wide / p.tall - 2.3), 1.2, count)
        self.assertLess(wide[30], wide[120])
        self.assertIsNone(plan(self.table({'names': []})))


class FlagTests(unittest.TestCase):
    def test_the_countries_are_the_united_nations_without_russia(self):
        import flag_art
        self.assertEqual(len(flag_art.MEMBERS), 193)
        self.assertEqual(len(set(flag_art.CODES)), len(flag_art.CODES))
        self.assertEqual(len(flag_art.CODES), 194)
        self.assertNotIn('ru', flag_art.CODES)
        for code in ('ua', 'us', 'gb', 'de', 'pl', 'jp', 'br', 'np', 'va', 'ps'):
            self.assertIn(code, flag_art.CODES)
        self.assertLessEqual(len(flag_art.CODES), flag_art.PER ** 2)
        # every picture is in the repository, and the generated library is the builder's
        self.assertTrue(flag_art.ready())
        self.assertEqual(flag_art.LUA.read_text(encoding='utf8'), flag_art.lua_text())

    def test_the_atlas_has_a_flag_a_cell(self):
        import flag_art
        colour, alpha = flag_art.sheet()
        w, h = flag_art.CELL
        self.assertEqual(colour.size, (flag_art.PER * w, flag_art.PER * h))

        def middle(code, fx, fy):
            k = flag_art.CODES.index(code)
            return colour.getpixel(((k % flag_art.PER) * w + int(w * fx), (k // flag_art.PER) * h + int(h * fy)))
        # Ukraine: blue over yellow; Japan: a red disc on white; Poland: white over red
        top, bottom = middle('ua', .5, .25), middle('ua', .5, .75)
        self.assertTrue(top[2] > top[0] + 60 and bottom[0] > 200 and bottom[2] < 90, (top, bottom))
        disc, field = middle('jp', .5, .5), middle('jp', .12, .2)
        self.assertTrue(disc[0] > 150 and disc[1] < 90 and min(field) > 230, (disc, field))
        self.assertTrue(min(middle('pl', .5, .25)) > 225 and middle('pl', .5, .75)[0] > 180)
        # a rectangle's cell is whole; Nepal's leaves its corner clear
        k = flag_art.CODES.index('np')
        x, y = (k % flag_art.PER) * w, (k // flag_art.PER) * h
        self.assertLess(alpha.getpixel((x + w - 12, y + 12)), 40)
        self.assertGreater(alpha.getpixel((x + w // 4, y + h // 2)), 200)
        k = flag_art.CODES.index('ua')
        self.assertGreater(alpha.getpixel(((k % flag_art.PER) * w + 2, (k // flag_art.PER) * h + 2)), 200)

    def flags(self, country):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().flag_source = (LUA / 'flag_lib.lua').read_text(encoding='utf8')
        lua.execute("package.preload['ge/extensions/e2r/flag_lib'] = function() return assert(loadstring(flag_source))() end")
        generator = lua.execute((LUA / 'generator.lua').read_text(encoding='utf8'))

        def table(value):
            if isinstance(value, dict):
                return lua.table_from({k: table(v) for k, v in value.items()})
            if isinstance(value, list):
                return lua.table_from([table(v) for v in value])
            return value
        pole = {'id': 'pole', 'kind': 'pin', 'pos': [250, 250, 20], 'tags': {'e2r_cat': 'flagpole', 'country': country, 'height': '9'}}
        cell = {'points': [pole], 'roads': [STREET], 'terrain': TERRAIN}
        options = {'relief': False, 'land': False, 'maxTrees': 0, 'maxGrass': 0, 'tune': {'lanes': 0, 'crown': 0, 'ruts': 0}}
        scene = generator.build(table([cell]), 0, 0, table(options))[1]
        uvs, size = [], []
        for item in scene['items'].values():
            if item.kind != 'proc':
                continue
            for mesh in item.meshes.values():
                if mesh.material == 'e2rf_flags':
                    uvs += [(uv.u, uv.v) for uv in mesh.uvs.values()]
                    zs = [v.z for v in mesh.verts.values()]
                    xy = [(v.x, v.y) for v in mesh.verts.values()]
                    wide = max(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** .5 for a in xy for b in xy)
                    size = [wide, max(zs) - min(zs), len(mesh.faces) // 3]
        return uvs, size

    def test_a_pole_flies_its_countrys_flag_from_the_atlas(self):
        import flag_art
        for code in ('UA', 'GB', 'CH'):
            uvs, (wide, tall, triangles) = self.flags(code)
            k = flag_art.CODES.index(code.lower())
            col, row = k % flag_art.PER, k // flag_art.PER
            self.assertEqual(triangles, 4, code)        # two faces
            for u, v in uvs:
                self.assertTrue(col / flag_art.PER < u < (col + 1) / flag_art.PER, (code, u))
                self.assertTrue(1 - (row + 1) / flag_art.PER < v < 1 - row / flag_art.PER, (code, v))
            # as wide as its own proportion: Ukraine's 3:2, Britain's 2:1, Switzerland's square
            self.assertAlmostEqual(wide / tall, flag_art.aspects()[code.lower()], delta=.02)
        # a country the atlas has not flies no picture
        self.assertEqual(self.flags('RU')[0], [])


class DecorPieceTests(unittest.TestCase):
    def test_two_hundred_poles_keep_every_piece_of_their_material(self):
        # A material is cut into pieces of 2500 triangles. The pins draw into the decor collector
        # after its first items joined the scene, and the pieces cut off before the signs' and the
        # yard's own counts were taken never joined it: two hundred flagpoles flew their flags
        # (776 triangles) over no poles (two hundred times 60).
        lua = LuaRuntime(unpack_returned_tuples=True)
        generator = lua.execute((LUA / 'generator.lua').read_text(encoding='utf8'))

        def table(value):
            if isinstance(value, dict):
                return lua.table_from({k: table(v) for k, v in value.items()})
            if isinstance(value, list):
                return lua.table_from([table(v) for v in value])
            return value
        poles = [{'id': f'p{k}', 'kind': 'pin', 'pos': [100 + (k % 20) * 4, 300 + (k // 20) * 4, 20],
                  'tags': {'e2r_cat': 'flagpole', 'country': 'UA', 'height': '9'}} for k in range(200)]
        cell = {'points': poles, 'roads': [STREET], 'terrain': TERRAIN}
        options = {'relief': False, 'land': False, 'maxTrees': 0, 'maxGrass': 0, 'tune': {'lanes': 0, 'crown': 0, 'ruts': 0}}
        scene = generator.build(table([cell]), 0, 0, table(options))[1]
        triangles, pieces = 0, 0
        for item in scene['items'].values():
            if item.kind == 'proc':
                for mesh in item.meshes.values():
                    if mesh.material == 'e2rf_yard':
                        triangles += len(mesh.faces) // 3
                        pieces += 1
                        self.assertTrue(item.decor)
        self.assertGreater(pieces, 2)
        self.assertGreaterEqual(triangles, 200 * 60)


class ThanksTileTests(unittest.TestCase):
    def test_every_country_has_a_pole_on_the_thanks_tile(self):
        import flag_art
        import proving_ground
        import proving_thanks
        plan = proving_ground.make_plan()
        i0, i1, j0, j1 = proving_ground.BLOCK['thanks']['tiles']
        poles = [p for p in plan.points if p[2].get('man_made') == 'flagpole'
                 and i0 * 500 < p[0] < i1 * 500 and j0 * 500 < p[1] < j1 * 500]
        self.assertEqual(sorted(p[2]['country'] for p in poles), sorted(c.upper() for c in flag_art.CODES))
        self.assertNotIn('RU', {p[2]['country'] for p in poles})
        self.assertGreaterEqual(len(proving_thanks.poles()), len(flag_art.CODES))
        # no two poles nearer than a flag is long
        for a in poles:
            self.assertFalse([b for b in poles if b is not a and (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 < 3.3 ** 2])

    def test_the_proving_ground_has_the_supporters_tile(self):
        import proving_ground
        import proving_thanks
        plan = proving_ground.make_plan()
        tile = plan.tiles[proving_thanks.CODE]
        self.assertEqual((tile['block'], tile['zone']), ('thanks', 'thanks'))
        self.assertTrue(any(z['id'] == 'thanks' for z in plan.zones))
        boards = [p for p in plan.points if p[2] and p[2].get('operator') == 'EarthNG supporters']
        self.assertEqual(len(boards), 1)
        x, y, tags = boards[0]
        self.assertEqual(tags['advertising'], 'billboard')
        i0, i1, j0, j1 = proving_ground.BLOCK['thanks']['tiles']
        self.assertTrue(i0 * 500 < x < i1 * 500 and j0 * 500 < y < j1 * 500)
        # the operator the generator reads is the one the plan writes
        source = (LUA / 'generator.lua').read_text(encoding='utf8')
        self.assertEqual(re.search(r"BLD\.PIN\.thanks = \{operator = '([^']+)'", source).group(1), tags['operator'])


if __name__ == '__main__':
    unittest.main()
