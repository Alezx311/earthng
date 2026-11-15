"""Points of interest (docs/POI.md, wave 1): fast_style.PIN_RULES in the pack, generator.lua's
objects and map records, pins.lua's styles."""
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime
import fast_style
import native_tool

ROOT = Path(__file__).resolve().parents[1]
STREET = {'id': 'street', 'nodes': ['a', 'b'], 'width': 8, 'tags': {'highway': 'residential'},
          'points': [[0, 90, 0], [400, 90, 0]]}


class PinRulesTests(unittest.TestCase):
    def test_categories_from_osm_tags(self):
        cases = {
            (('amenity', 'atm'),): 'atm',
            (('amenity', 'vending_machine'), ('vending', 'water')): 'water_vending',
            (('tourism', 'guest_house'),): 'hotel',
            (('tourism', 'motel'),): 'motel',
            (('historic', 'wayside_cross'),): 'cross',
            (('man_made', 'cross'),): 'cross',
            (('natural', 'peak'), ('ele', '2061')): 'peak',
            (('mountain_pass', 'yes'), ('highway', 'turning_circle')): 'pass',
            (('shop', 'kiosk'),): 'kiosk',
            (('amenity', 'parking'), ('parking', 'surface')): 'parking',
        }
        for pairs, category in cases.items():
            self.assertEqual(fast_style.pin_category(dict(pairs)), category, pairs)
        self.assertIsNone(fast_style.pin_category({'shop': 'clothes'}))
        self.assertIsNone(fast_style.pin_category({'disused:amenity': 'atm'}))

    def test_point_kind_keeps_the_older_kinds_first(self):
        self.assertEqual(fast_style.point_kind({'amenity': 'atm'}), 'pin')
        self.assertEqual(fast_style.point_kind({'amenity': 'bench', 'tourism': 'viewpoint'}), 'bench')
        self.assertEqual(fast_style.point_kind({'amenity': 'fuel', 'shop': 'kiosk'}), 'fuel')
        self.assertEqual(fast_style.point_kind({'amenity': 'bank', 'atm': 'yes'}), 'service')
        self.assertEqual(fast_style.point_kind({'highway': 'turning_circle', 'mountain_pass': 'yes'}), 'turning_circle')
        for key in ('tourism', 'historic', 'mountain_pass'):
            self.assertIn(key, fast_style.point_keys())

    def test_pin_keeps_few_tags_and_its_bank(self):
        tags = fast_style.pin_tags({'amenity': 'atm', 'operator': 'ПриватБанк', 'opening_hours': '24/7',
                                    'phone': '+380 00 000 0000', 'name': ''})
        self.assertEqual(tags, {'operator': 'ПриватБанк', 'e2r_cat': 'atm', 'e2r_brand': 'privatbank'})
        hotel = fast_style.pin_tags({'tourism': 'hotel', 'name': 'Hotel Alpenrose', 'stars': '3', 'brand': 'Sense'})
        self.assertEqual(hotel, {'name': 'Hotel Alpenrose', 'brand': 'Sense', 'e2r_cat': 'hotel'})   # no bank for a hotel
        # a passage's ATM, a mall's kiosk: on the map, no object in the street
        for under in ({'level': '-1'}, {'level': ' -2;-1'}, {'indoor': 'yes'}, {'location': 'underground'}):
            self.assertEqual(fast_style.pin_tags({'amenity': 'atm', **under}).get('e2r_in'), 'yes', under)
        for out in ({'level': '0'}, {'level': '1;-1'}, {'indoor': 'no'}, {'location': 'roof'}, {'covered': 'yes'}):
            self.assertNotIn('e2r_in', fast_style.pin_tags({'amenity': 'atm', **out}), out)

    def test_scene_rules_carry_the_table(self):
        rules = native_tool.scene_rules()
        self.assertEqual([tuple(r) for r in rules['pin_rules']], list(fast_style.PIN_RULES))
        self.assertEqual(rules['pin_tags'], list(fast_style.PIN_TAGS))


class PinRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.g = self.lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8'))
        self.pins = self.lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/pins.lua').read_text(encoding='utf8'))

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def build(self, cells, far=False):
        options = {'terrainStep': 100, 'far': far, 'maxTrees': 0, 'relief': False}
        return self.g.build(self.table(cells), 0, 0, self.table(options))[2 if far else 1]

    def corners(self, scene, material):
        out = []
        for item in scene['items'].values():
            for mesh in (item.meshes or self.lua.table()).values():
                if mesh.material == material:
                    for face in mesh.faces.values():
                        p = mesh.verts[face.v + 1]
                        out.append((p.x + item.pos[1], p.y + item.pos[2], p.z + item.pos[3]))
        return out

    @staticmethod
    def near(points, x, y, r=3):
        return [p for p in points if (p[0] - x) ** 2 + (p[1] - y) ** 2 < r * r]

    def test_every_category_has_a_map_style_and_the_far_lists_agree(self):
        styles = set(self.pins.STYLE.keys())
        self.assertEqual({rule[2] for rule in fast_style.PIN_RULES}, styles)
        self.assertEqual(set(self.pins.FAR.keys()), set(self.g.PIN.far.keys()))
        self.assertTrue(set(self.g.PIN.objects.keys()) <= styles)
        # the icons read without a language: pictograms or Latin letters
        for name, style in self.pins.STYLE.items():
            self.assertTrue(style.shape or all(ord(ch) < 128 for ch in style.text), name)

    def test_objects_off_the_road_and_outside_buildings_and_records_for_the_map(self):
        mall = {'id': 'mall', 'height': 8, 'tags': {'building': 'retail'},
                'rings': [[[300, 20], [360, 20], [360, 60], [300, 60]]]}
        points = [
            {'id': 'cross', 'kind': 'pin', 'pos': [100, 70, 0], 'tags': {'e2r_cat': 'cross'}},
            {'id': 'atm', 'kind': 'pin', 'pos': [150, 70, 0], 'tags': {'e2r_cat': 'atm', 'e2r_brand': 'privatbank'}},
            {'id': 'road_atm', 'kind': 'pin', 'pos': [200, 90, 0], 'tags': {'e2r_cat': 'atm'}},
            {'id': 'passage_atm', 'kind': 'pin', 'pos': [120, 70, 0], 'tags': {'e2r_cat': 'atm', 'e2r_in': 'yes'}},
            {'id': 'mall_kiosk', 'kind': 'pin', 'pos': [330, 40, 0], 'tags': {'e2r_cat': 'kiosk'}},
            {'id': 'peak', 'kind': 'pin', 'pos': [250, 300, 0], 'tags': {'e2r_cat': 'peak', 'name': 'Hoverla', 'ele': '2061'}},
            {'id': 'next_tile', 'kind': 'pin', 'pos': [600, 300, 0], 'tags': {'e2r_cat': 'cross'}},
        ]
        cell = {'roads': [STREET], 'buildings': [mall], 'points': points}
        scene = self.build([cell])
        records = {r.id: r for r in scene.brandPOIs.values()}
        self.assertEqual(set(records), {'cross', 'atm', 'road_atm', 'passage_atm', 'mall_kiosk', 'peak'})
        self.assertEqual((records['peak'].kind, records['peak'].cat, records['peak'].label, records['peak'].ele),
                         ('pin', 'peak', 'Hoverla', '2061'))
        self.assertEqual(records['atm'].brand, 'privatbank')
        yard = self.corners(scene, 'e2rf_yard')
        self.assertTrue(self.near(yard, 100, 70), 'the cross')
        self.assertTrue(max(p[2] for p in self.near(yard, 100, 70)) > 2.9, 'a cross stands 3 m tall')
        self.assertTrue(self.near(self.corners(scene, 'e2rf_brand_sign'), 150, 70, 1), "the bank's sign on its ATM")
        self.assertFalse(self.near(yard, 200, 90), 'nothing on the carriageway')
        self.assertFalse(self.near(yard, 120, 70), 'an ATM under ground stays on the map')
        self.assertFalse(self.near(yard, 330, 40), 'an indoor kiosk stays on the map')
        self.assertFalse(self.near(yard, 250, 300), 'a peak has no object')
        # the cross faces the street (its front, -y of its frame, toward y = 90)
        base = min(p[2] for p in self.near(yard, 100, 70))
        bar = [p for p in self.near(yard, 100, 70, 1) if abs(p[2] - base - 2.32) < 1e-6]
        self.assertTrue(bar and max(abs(p[0] - 100) for p in bar) > .5, 'the crossbar runs along the street')
        far = self.build([cell], far=True)
        self.assertEqual([r.id for r in far.brandPOIs.values()], ['peak'])

    def test_a_named_hotel_exchange_or_parts_shop_signs_its_building_in_its_own_name(self):
        def house(ident, x0, use):
            return {'id': ident, 'height': 9, 'tags': {'building': use},
                    'rings': [[[x0, 70], [x0 + 40, 70], [x0 + 40, 84], [x0, 84]]]}
        buildings = [house('hotel', 40, 'hotel'), house('exchange', 120, 'commercial'), house('parts', 200, 'retail')]
        points = [
            {'id': 'h', 'kind': 'pin', 'pos': [60, 77, 0], 'tags': {'e2r_cat': 'hotel', 'name': 'Hotel Dnipro'}},
            # a script the glyphs lack: the English name instead
            {'id': 'x', 'kind': 'pin', 'pos': [140, 77, 0], 'tags': {'e2r_cat': 'exchange', 'name': 'Ηλιος', 'name:en': 'Ilios'}},
            # no name: no sign, and never a word of ours
            {'id': 'p', 'kind': 'pin', 'pos': [220, 77, 0], 'tags': {'e2r_cat': 'car_parts'}},
        ]
        scene = self.build([{'roads': [STREET], 'buildings': buildings, 'points': points}])
        glyphs = self.corners(scene, 'e2rf_glyphs')

        def on(x0):
            return [p for p in glyphs if x0 - 1 <= p[0] <= x0 + 41 and 82 <= p[1] <= 86]
        self.assertTrue(on(40), "the hotel's name over the street")
        self.assertTrue(on(120), 'the exchange by its English name')
        self.assertFalse(on(200), 'a nameless parts shop')
        self.assertEqual(self.g.PIN.signs.hotel, 69)
        self.assertFalse(self.corners(scene, 'e2rf_storefront'), 'no shop front, its posters have words')
        self.assertTrue(set(self.g.PIN.signs.keys()) <= set(self.pins.STYLE.keys()))


if __name__ == '__main__':
    unittest.main()
