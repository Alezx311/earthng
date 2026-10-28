"""Commercial OSM nodes as 'poi' points (EARTHNG_POIS=1): selection and the pack round trip."""
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

import country_format as binary
import fast_style as style
import looks

ROOT = Path(__file__).resolve().parents[1]


class PoiPointTests(unittest.TestCase):
    def setUp(self):
        self.saved = style.POIS

    def tearDown(self):
        style.POIS = self.saved

    def test_off_by_default_and_only_commercial_nodes_when_on(self):
        style.POIS = False
        self.assertIsNone(style.point_kind({'shop': 'bakery'}))
        self.assertNotIn('shop', style.point_keys())
        style.POIS = True
        self.assertEqual(set(style.point_keys()) - set(style.POINT_KEYS), {'shop', 'office', 'craft', 'amenity'})
        for tags in ({'shop': 'bakery'}, {'office': 'insurance'}, {'craft': 'shoemaker'},
                     {'amenity': 'pharmacy'}, {'amenity': 'cafe', 'name': 'Кава'}):
            with self.subTest(tags=tags):
                self.assertEqual(style.point_kind(tags), 'poi')
        for tags in ({'amenity': 'bench'}, {'amenity': 'school'}, {'amenity': 'parking'},
                     {'shop': 'vacant'}, {'shop': 'no'}, {'office': 'closed'}, {'disused:shop': 'yes'}):
            with self.subTest(tags=tags):
                self.assertIsNone(style.point_kind(tags))
        # an existing class wins: a shop's staircase door is still an entrance, a lamp a lamp
        self.assertEqual(style.point_kind({'entrance': 'staircase', 'shop': 'kiosk'}), 'entrance')
        self.assertEqual(style.point_kind({'highway': 'street_lamp', 'amenity': 'cafe'}), 'lamp')
        self.assertTrue(looks.keep_scenery('poi', {'pois': True}))
        self.assertFalse(looks.keep_scenery('poi', {'pois': False}))

    def test_game_decoder_keeps_the_osm_id_level_and_all_tags(self):
        tags = {'shop': 'convenience', 'name': 'Продукти', 'level': '0', 'opening_hours': '08:00-22:00'}
        cell = dict(roads=[], junctions=[], buildings=[], areas=[], lines=[],
                    points=[dict(id='-1000012345678:0', kind='poi', tags=tags, pos=[1012.34, 20.5, 170.25])],
                    terrain=dict(rect=[1000, 0, 2000, 1000], nx=2, ny=2, heights=[1, 2, 3, 4]))
        data, _ = binary.encode_block({binary.slot(1, 0): binary.encode_cell(cell, (1000, 0))})
        expected = binary.decode_cell(data, (1000, 0), [1000, 0, 2000, 1000], *binary.decode_block(data)[1])
        self.assertEqual(expected['points'][0]['tags'], tags)
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().cellformat = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/cellformat.lua').read_text(encoding='utf8'))
        lua.globals().blockData = data
        got = lua.execute('''local slots = cellformat.block(blockData)
          local r = slots[1]
          return cellformat.cell(blockData, r[1], r[2], 1000, 0, {1000, 0, 2000, 1000})''')
        point = got.points[1]
        self.assertEqual(point.kind, 'poi')
        self.assertEqual(point.id, '-1000012345678:0')
        self.assertEqual({k: v for k, v in point.tags.items()}, tags)
        self.assertAlmostEqual(point.pos[1], 1012.34)
        self.assertAlmostEqual(point.pos[2], 20.5)


if __name__ == '__main__':
    unittest.main()
