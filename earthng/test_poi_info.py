"""What a point of interest is, said in the world (docs/POI.md "Енциклопедія"): the types of
poi_types.py, their generated library and marks, and generator.lua's info stands, wall plaques
and blade signs."""
import tempfile
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime
from PIL import Image

import fast_style
import poi_art
import poi_types
import test_pins

ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / 'mod/lua/ge/extensions/e2r'
STREET = test_pins.STREET
QUAD = 6        # the corners PinScene.corners counts for one quad: two triangles


def pin(ident, x, y, cat, **tags):
    return {'id': ident, 'kind': 'pin', 'pos': [x, y, 0], 'tags': {'e2r_cat': cat, **{k.replace('__', ':'): v for k, v in tags.items()}}}


class PoiTypeTests(unittest.TestCase):
    def test_the_library_in_the_mod_is_the_one_poi_types_writes(self):
        self.assertEqual((LUA / 'poi_lib.lua').read_text(encoding='utf8').replace('\r\n', '\n'), poi_art.lua_text(),
                         'run: python earthng/poi_art.py --lua')

    def test_every_type_is_whole_and_every_mark_is_drawn(self):
        self.assertLessEqual(len(poi_types.marks()), poi_art.PER * poi_art.PER)
        for key, t in poi_types.TYPES.items():
            self.assertIn(t['mark'], poi_art.MARKS, key)
            self.assertIn(t['group'], poi_types.GROUPS, key)
            self.assertIn(t['look'], ('stand', 'plaque', 'blade', ''), key)
            self.assertTrue(t['uk'] and t['en'], key)
            self.assertEqual(bool(t['textUk']), bool(t['textEn']), key)
            self.assertFalse(t['bare'] and t['look'] != 'stand', key)
            if not key.startswith('cat:'):
                self.assertIn(key.split('=')[0], poi_types.KEYS, key)
        for category, key in poi_types.CATEGORY.items():
            self.assertIn(key, poi_types.TYPES, category)

    def test_every_category_of_the_map_has_a_type(self):
        on_map = {rule[2] for rule in fast_style.PIN_RULES} - set(fast_style.PIN_OFF_MAP) - {''}
        for category in sorted(on_map):
            self.assertIsNotNone(poi_types.type_of({'e2r_cat': category}), category)

    def test_a_type_by_the_most_telling_tag_else_by_the_category(self):
        cases = [
            ({'e2r_cat': 'monument', 'historic': 'memorial', 'memorial': 'war_memorial'}, 'memorial=war_memorial'),
            ({'e2r_cat': 'monument', 'historic': 'memorial'}, 'historic=memorial'),
            ({'e2r_cat': 'monument'}, 'historic=monument'),
            ({'e2r_cat': 'castle', 'historic': 'fort'}, 'historic=fort'),
            ({'e2r_cat': 'sight', 'tourism': 'museum'}, 'tourism=museum'),
            ({'e2r_cat': 'sight'}, 'cat:sight'),                       # a pack from before the kind keys
            ({'e2r_cat': 'sight', 'artwork_type': 'mural'}, 'artwork_type=mural'),
            ({'e2r_cat': 'shop_map', 'shop': 'bakery'}, 'shop=bakery'),
            ({'e2r_cat': 'shop_map', 'shop': 'erotic'}, 'cat:shop_map'),
            ({'e2r_cat': 'billboard'}, None),
        ]
        for tags, key in cases:
            self.assertEqual(poi_types.type_of(tags), key, tags)

    def test_the_marks_atlas(self):
        with tempfile.TemporaryDirectory() as folder:
            poi_art.build(Path(folder))
            marks = Image.open(Path(folder) / 'poi_marks_o.data.png')
            self.assertEqual(marks.size, (poi_art.PER * poi_art.CELL,) * 2)
            self.assertEqual((Path(folder) / 'poi.version').read_text(), poi_art.VERSION)
            # every mark's cell is drawn in, and its rim is clear (a neighbour's mips never reach it)
            alpha = marks.convert('L').transpose(Image.FLIP_TOP_BOTTOM)
            for name, k in poi_art.cells().items():
                x, y = k % poi_art.PER * poi_art.CELL, k // poi_art.PER * poi_art.CELL
                cell = alpha.crop((x, y, x + poi_art.CELL, y + poi_art.CELL))
                self.assertGreater(sum(cell.histogram()[128:]), poi_art.CELL * poi_art.CELL * .04, name)
                rim = cell.crop((0, 0, poi_art.CELL, 8))
                self.assertEqual(rim.getextrema()[1], 0, name)
        self.assertIn('poi_marks_o.data.png', __import__('fast_art').MIP_REFS)
        for kind in ('poi_marks', 'poi_marks_dark'):
            self.assertTrue(fast_style.MATERIALS['e2rf_' + kind]['alphaTest'])


class PoiSceneTests(test_pins.PinScene):
    """generator.lua with poi.lua and its library, as the game requires them."""
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        for name in ('poi_lib', 'poi'):
            self.lua.globals().source = (LUA / f'{name}.lua').read_text(encoding='utf8')
            self.lua.execute(f"package.loaded['ge/extensions/e2r/{name}'] = assert(loadstring(source, '{name}'))()")
        self.g = self.lua.execute((LUA / 'generator.lua').read_text(encoding='utf8'))
        self.poi = self.lua.eval("package.loaded['ge/extensions/e2r/poi']")

    def marks(self, scene, material='e2rf_poi_marks'):
        return self.corners(scene, material)

    def test_lua_reads_a_type_as_python_does(self):
        cases = [{'e2r_cat': 'monument', 'historic': 'memorial', 'memorial': 'war_memorial'}, {'e2r_cat': 'sight'},
                 {'e2r_cat': 'shop_map', 'shop': 'florist'}, {'e2r_cat': 'peak'}, {'e2r_cat': 'billboard'},
                 {'e2r_cat': 'sight', 'tourism': 'information', 'information': 'board'}]
        for tags in cases:
            found = self.poi.typeOf(self.table(tags))
            self.assertEqual(found and found[0], poi_types.type_of(tags), tags)
        self.assertEqual(list(self.poi.facts(self.table({'ele': '2061', 'start_date': '1654-05-01'})).values()), ['2061 m', '1654'])
        self.assertEqual(list(self.poi.facts(self.table({'start_date': 'C17'})).values()), [])

    def test_a_named_sight_in_the_open_gets_a_stand_facing_the_street(self):
        points = [pin('castle', 100, 70, 'castle', name='Olesko', start_date='1327'),
                  pin('nameless', 200, 70, 'monument'),
                  pin('falls', 300, 70, 'waterfall')]
        scene = self.build([{'roads': [STREET], 'points': points}])
        board = self.near(self.corners(scene, 'e2rf_sign_white'), 100, 70, 1.5)
        self.assertTrue(board, 'the white board')
        self.assertAlmostEqual(max(p[2] for p in board) - min(p[2] for p in board), 1.1, delta=.01)
        self.assertGreater(max(p[0] for p in board) - min(p[0] for p in board), 1.4, 'the board runs along the street')
        # its name in white on the head, its year in dark ink, its mark in dark ink before the board
        self.assertEqual(len(self.near(self.corners(scene, 'e2rf_glyphs'), 100, 70, 1.5)), QUAD * len('Olesko'))
        self.assertEqual(len(self.near(self.corners(scene, 'e2rf_glyphs_dark'), 100, 70, 1.5)), QUAD * len('1327'))
        mark = self.near(self.marks(scene, 'e2rf_poi_marks_dark'), 100, 70, 1.5)
        self.assertEqual(len(mark), QUAD)
        self.assertGreater(min(p[1] for p in mark), max(p[1] for p in board), 'the mark is on the face to the street (y = 90)')
        # a monument OSM has no name for keeps no stand; a waterfall gets one with its mark alone
        self.assertFalse(self.near(self.corners(scene, 'e2rf_sign_white'), 200, 70, 4))
        self.assertTrue(self.near(self.corners(scene, 'e2rf_sign_white'), 300, 70, 1.5))
        self.assertEqual(len(self.near(self.marks(scene, 'e2rf_poi_marks_dark'), 300, 70, 1.5)), QUAD)
        self.assertFalse(self.near(self.corners(scene, 'e2rf_glyphs'), 300, 70, 1.5))
        records = {r.id: r for r in scene.brandPOIs.values()}
        self.assertEqual((records['castle'].info.type, records['castle'].info.year), ('historic=castle', '1327'))

    def test_a_stand_beside_the_categorys_own_object(self):
        scene = self.build([{'roads': [STREET], 'points': [pin('view', 100, 70, 'viewpoint')]}])
        yard = self.corners(scene, 'e2rf_yard')
        self.assertTrue(self.near(yard, 100, 70, .5), 'the binoculars where the point is')
        board = self.corners(scene, 'e2rf_sign_white')
        self.assertTrue(board)
        middle = sum(p[0] for p in board) / len(board)
        self.assertAlmostEqual(abs(middle - 100), 2.3, delta=.05)

    def test_in_a_building_a_plaque_or_a_blade_on_its_open_wall(self):
        hall = {'id': 'hall', 'height': 9, 'tags': {'building': 'yes'}, 'rings': [[[100, 60], [130, 60], [130, 80], [100, 80]]]}
        shed = {'id': 'shed', 'height': 2.6, 'tags': {'building': 'yes'}, 'rings': [[[200, 60], [210, 60], [210, 80], [200, 80]]]}
        points = [pin('museum', 110, 76, 'sight', name='Museum of Salt', tourism='museum'),
                  pin('bakery', 124, 77, 'shop_map', shop='bakery', name='Bulka'),
                  pin('near', 124.5, 77, 'shop_map', shop='florist'),
                  pin('low', 205, 77, 'shop_map', shop='bakery'),
                  pin('grocer', 118, 77, 'shop_map', shop='convenience'),
                  pin('under', 115, 76, 'sight', name='Crypt', e2r_in='yes')]
        scene = self.build([{'roads': [STREET], 'buildings': [hall, shed], 'points': points}])
        marks = self.marks(scene)
        # the plaque: its mark on the street wall (y = 80), outside it, at eye height
        plaque = [p for p in marks if 109 < p[0] < 111]
        self.assertEqual(len(plaque), QUAD)
        self.assertTrue(all(80 < p[1] < 80.1 for p in plaque))
        self.assertTrue(all(1.4 < p[2] - 0 < 2.6 for p in plaque))
        name = [p for p in self.corners(scene, 'e2rf_glyphs') if 109 < p[0] < 111 and 80 < p[1] < 80.1]
        self.assertEqual(len(name), QUAD * (len('Museum of Salt') - 2), 'the name in two lines under the mark')
        # the blade: hung out across the pavement, a mark on each face, over heads
        blade = [p for p in marks if 123 < p[0] < 125]
        self.assertEqual(len(blade), 2 * QUAD)
        self.assertTrue(all(80.1 < p[1] < 81 for p in blade))
        self.assertGreaterEqual(min(p[2] for p in blade), 2.5)
        self.assertEqual(len({round(p[0], 3) for p in blade}), 2, 'two faces, each in a plane across the wall')
        # the florist half a metre on, the shop that has a sign of its own, the low shed, the crypt: none
        self.assertEqual(len(marks), 3 * QUAD)

    def test_a_tile_takes_so_many_and_none_when_switched_off(self):
        points = [pin(f'c{k}', 20 + k * 30, 70 + (k % 2) * 200, 'castle', name=f'Castle {k}') for k in range(13)]
        cell = {'roads': [STREET], 'points': points}
        scene = self.build([cell])
        most = self.g.PIN.info.stands
        self.assertEqual(len(self.marks(scene, 'e2rf_poi_marks_dark')), QUAD * most)
        off = self.build([cell], poiInfo=False)
        self.assertFalse(self.marks(off, 'e2rf_poi_marks_dark'))
        self.assertFalse(self.corners(off, 'e2rf_sign_white'))

    def test_over_the_limit_the_points_worth_the_drive_keep_their_stands(self):
        most = self.g.PIN.info.stands
        plain = [pin(f'm{k}', 20 + k * 20, 70, 'monument', name=f'Stone {k}') for k in range(most + 3)]
        best = [pin('falls', 20 + (most + 3) * 20, 70, 'waterfall'),
                pin('known', 20 + (most + 4) * 20, 70, 'monument', name='Founders', wikipedia='en:Founders', start_date='1888')]
        scene = self.build([{'roads': [STREET], 'points': plain + best}])
        boards = self.corners(scene, 'e2rf_sign_white')
        self.assertEqual(len(self.marks(scene, 'e2rf_poi_marks_dark')), QUAD * most)
        for point in best:
            self.assertTrue(self.near(boards, point['pos'][0], 70, 1.5), point['id'])
        self.assertEqual(sum(1 for point in plain if self.near(boards, point['pos'][0], 70, 1.5)), most - 2, 'the rest of the limit')

    def test_without_the_library_the_tile_is_as_before(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute("package.loaded['ge/extensions/e2r/poi'] = false")
        self.lua, self.g = lua, lua.execute((LUA / 'generator.lua').read_text(encoding='utf8'))
        scene = self.build([{'roads': [STREET], 'points': [pin('castle', 100, 60, 'castle', name='Olesko')]}])
        self.assertFalse(self.corners(scene, 'e2rf_sign_white'))
        self.assertIsNone(scene.brandPOIs[1].info)


class PoiCardTests(unittest.TestCase):
    """poicard.lua: the card by the car and the journal of found places."""
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        for name in ('poi_lib', 'poi', 'poicard'):
            self.lua.globals().source = (LUA / f'{name}.lua').read_text(encoding='utf8')
            self.lua.execute(f"package.loaded['ge/extensions/e2r/{name}'] = assert(loadstring(source, '{name}'))()")
        self.card = self.lua.eval("package.loaded['ge/extensions/e2r/poicard']")
        self.poi = self.lua.eval("package.loaded['ge/extensions/e2r/poi']")

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def record(self, ident, x, y, label=None, **tags):
        tags = {k.replace('__', ':'): v for k, v in tags.items()}
        rec = {'id': ident, 'kind': 'pin', 'cat': tags['e2r_cat'], 'x': x, 'y': y, 'ele': tags.get('ele')}
        if label:
            rec['label'] = label
        rec = self.table(rec)
        rec.info = self.poi.record(self.table(tags))
        return rec

    def tiles(self, *records):
        return self.table({'0_0': {'brandPOIs': list(records)}})

    @staticmethod
    def text(card):
        return [(line[1], line[2]) for line in card.values()]

    def test_the_card_of_the_nearest_described_point_in_the_players_language(self):
        castle = self.record('w7', 100, 50, 'Олеський замок', e2r_cat='castle', start_date='1327', name__en='Olesko Castle',
                             wikipedia='uk:Олеський замок')
        shop = self.record('n1', 100, 10, 'Хліб', e2r_cat='shop_map', shop='bakery')
        t, tiles = self.card.new(), self.tiles(castle, shop)
        self.assertIsNone(self.card.step(t, 100, 200, 5, tiles, self.table({'lang': 'uk'})), 'too far')
        self.assertIsNone(self.card.step(t, 100, 12, 5, self.tiles(shop), self.table({'lang': 'uk'})), 'a shop has no card')
        self.assertIsNone(self.card.step(t, 100, 40, 40, tiles, self.table({'lang': 'uk'})), 'nobody reads at 144 km/h')
        lines = self.text(self.card.step(t, 100, 20, 20, tiles, self.table({'lang': 'uk'})))
        self.assertEqual(lines[0], ('Олеський замок', 'title'))
        self.assertEqual(lines[1], ('Замок', 'kind'))
        body = [line for line, role in lines if role == 'text']
        self.assertEqual(' '.join(body), poi_types.TYPES['historic=castle']['textUk'])
        self.assertTrue(all(len(line) <= self.card.WRAP for line in body))
        self.assertIn(('Рік: 1327', 'fact'), lines)
        self.assertIn(('Вікіпедія: Олеський замок', 'fact'), lines)
        self.assertEqual(lines[-1], ('Нове місце в журналі · знайдено 1', 'new'))
        english = self.text(self.card.step(t, 100, 20, 20, tiles, self.table({'lang': 'en'})))
        self.assertEqual(english[:2], [('Olesko Castle', 'title'), ('Castle', 'kind')])
        self.assertIn(('Year: 1327', 'fact'), english)

    def test_a_place_is_found_once_the_car_comes_up_and_slows_down(self):
        spring = self.record('n5', 0, 0, e2r_cat='spring')
        t, tiles, found = self.card.new(), self.tiles(spring), []
        env = self.table({'lang': 'uk'})
        env.found = lambda state, rec: found.append(rec.id)
        card = self.card.step(t, 50, 0, 20, tiles, env)
        self.assertEqual(self.text(card)[0], ('Джерело', 'title'), 'a nameless point is titled by what it is')
        self.assertEqual(found, [], 'passing by at 72 km/h does not find it')
        self.card.step(t, 20, 0, 10, tiles, env)
        self.assertEqual((found, t.found), (['n5'], 1))
        self.card.step(t, 10, 0, 2, tiles, env)
        self.assertEqual(found, ['n5'], 'once')
        # the journal survives the session; back at the place, the card says so
        again = self.card.new()
        self.card.load(again, self.card.save(t))
        self.assertEqual(again.found, 1)
        self.assertEqual(self.text(self.card.step(again, 10, 0, 2, tiles, env))[-1], ('Ви тут уже були', 'old'))
        # the card leaves with the car, and with its tile
        self.assertIsNone(self.card.step(again, 200, 0, 2, tiles, env))
        self.card.step(again, 10, 0, 2, tiles, env)
        self.assertIsNone(self.card.step(again, 10, 0, 2, self.table({}), env))

    def test_the_sidecars_facts_join_the_card(self):
        mill = self.record('n9', 0, 0, 'Млин', e2r_cat='windmill')
        env = self.table({'lang': 'uk'})
        env.details = lambda rec: self.table([['start_date', '1894'], ['heritage', '2'], ['wikipedia', 'uk:Вітряк (Кудряве)'],
                                              ['phone', '+380'], ['description', 'Стовповий вітряк']])
        lines = self.text(self.card.step(self.card.new(), 5, 0, 0, self.tiles(mill), env))
        for line in ('Рік: 1894', "Пам'ятка спадщини: так",'Вікіпедія: Вітряк (Кудряве)', '«Стовповий вітряк»'):
            self.assertIn((line, 'fact'), lines)
        self.assertFalse([line for line, _ in lines if '+380' in line], 'nothing personal on the card')

    def test_wrap_counts_characters_not_bytes(self):
        lines = list(self.card.wrap('Найвища точка гори або пагорба над рівнем моря', 20).values())
        self.assertEqual(lines, ['Найвища точка гори', 'або пагорба над', 'рівнем моря'])


if __name__ == '__main__':
    unittest.main()
