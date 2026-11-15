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
        self.assertEqual(fast_style.pin_category({'shop': 'clothes'}), 'shop_map')
        self.assertEqual(fast_style.pin_category({'amenity': 'cafe'}), 'food')
        self.assertEqual(fast_style.pin_category({'tourism': 'museum'}), 'sight')
        self.assertIsNone(fast_style.pin_category({'shop': 'vacant'}))
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
        self.assertEqual(rules['pin_sites'], list(fast_style.PIN_SITES))

    def test_a_site_outline_says_when_it_is_a_building(self):
        self.assertEqual(fast_style.pin_site_tags({'shop': 'car', 'name': 'Auto Plaza', 'building': 'retail'}),
                         {'name': 'Auto Plaza', 'e2r_cat': 'car_dealer', 'e2r_bld': 'yes'})
        self.assertEqual(fast_style.pin_site_tags({'highway': 'rest_area', 'building': 'no'}), {'e2r_cat': 'rest_area'})
        self.assertTrue(set(fast_style.PIN_SITES) <= {rule[2] for rule in fast_style.PIN_RULES})


class PinScene(unittest.TestCase):
    """generator.lua and pins.lua in LuaJIT, and what a built scene draws."""
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

    def build(self, cells, far=False, **extra):
        options = {'terrainStep': 100, 'far': far, 'maxTrees': 0, 'relief': False, **extra}
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

    @staticmethod
    def groups(values, gap):
        """How many runs of sorted values lie more than `gap` apart."""
        values = sorted(values)
        return sum(1 for a, b in zip([None] + values, values) if a is None or b - a > gap)

    def bays(self, scene):
        return [tuple(b.values()) for b in (scene['parking'] or self.lua.table()).values()]


class PinRuntimeTests(PinScene):

    def test_map_label_falls_back_to_localized_name(self):
        point = {'id': 'museum', 'kind': 'pin', 'pos': [100, 70, 0],
                 'tags': {'e2r_cat': 'sight', 'name:en': 'Museum'}}
        scene = self.build([{'roads': [STREET], 'points': [point]}])
        self.assertEqual(scene.brandPOIs[1].label, 'Museum')

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
        # a named peak without a summit cross: a cairn, its name and height on a plate beside it
        self.assertTrue(self.near(yard, 250, 300, 1.2), 'the cairn')
        self.assertLess(max(p[2] for p in self.near(yard, 250, 300, 1.2)), 1.6)
        plate = self.near(self.corners(scene, 'e2rf_glyphs_dark'), 250, 300, 4)
        self.assertGreaterEqual(len(plate), 4 * (len('Hoverla') + len('2061 m') - 1))
        # the cross faces the street (its front, -y of its frame, toward y = 90)
        base = min(p[2] for p in self.near(yard, 100, 70))
        bar = [p for p in self.near(yard, 100, 70, 1) if abs(p[2] - base - 2.32) < 1e-6]
        self.assertTrue(bar and max(abs(p[0] - 100) for p in bar) > .5, 'the crossbar runs along the street')
        far = self.build([cell], far=True)
        self.assertEqual([r.id for r in far.brandPOIs.values()], ['peak'])

    def test_a_summit_cross_where_osm_says_so_and_nothing_on_a_nameless_peak(self):
        points = [{'id': 'cross', 'kind': 'pin', 'pos': [250, 300, 0],
                   'tags': {'e2r_cat': 'peak', 'name': 'Patscherkofel', 'ele': '2246', 'summit:cross': 'yes'}},
                  {'id': 'bare', 'kind': 'pin', 'pos': [400, 300, 0], 'tags': {'e2r_cat': 'peak'}}]
        scene = self.build([{'roads': [STREET], 'points': points}])
        yard = self.corners(scene, 'e2rf_yard')
        base = min(p[2] for p in self.near(yard, 250, 300, 1))
        self.assertGreater(max(p[2] for p in self.near(yard, 250, 300, 1)) - base, 3.5, 'a summit cross')
        self.assertFalse(self.near(yard, 400, 300, 5), 'a nameless hill keeps no mark')

    def test_an_atm_inside_hangs_on_its_buildings_open_wall(self):
        shop = {'id': 'shop', 'height': 6, 'tags': {'building': 'retail'}, 'rings': [[[100, 60], [130, 60], [130, 80], [100, 80]]]}
        neighbour = {'id': 'next', 'height': 6, 'tags': {'building': 'yes'}, 'rings': [[[130, 60], [150, 60], [150, 80], [130, 80]]]}
        atm = {'id': 'atm', 'kind': 'pin', 'pos': [128, 75, 0], 'tags': {'e2r_cat': 'atm', 'e2r_brand': 'privatbank'}}
        deep = {'id': 'deep', 'kind': 'pin', 'pos': [330, 40, 0], 'tags': {'e2r_cat': 'atm'}}
        mall = {'id': 'mall', 'height': 8, 'tags': {'building': 'retail'}, 'rings': [[[300, 10], [360, 10], [360, 70], [300, 70]]]}
        scene = self.build([{'roads': [STREET], 'buildings': [shop, neighbour, mall], 'points': [atm, deep]}])
        yard = self.corners(scene, 'e2rf_yard')
        # the party wall to the east (2 m) is shut by the next house: on the street wall (5 m) instead
        panel = [p for p in yard if 126.5 < p[0] < 129.5 and 79.5 < p[1] < 80.6]
        self.assertTrue(panel, 'on the street wall')
        self.assertGreater(max(p[1] for p in panel), 80.2, 'before the wall, toward the street')
        self.assertFalse([p for p in yard if 129.5 < p[0] < 130.6 and 72 < p[1] < 78], 'not on the party wall')
        self.assertTrue([p for p in self.corners(scene, 'e2rf_brand_sign') if 126.5 < p[0] < 129.5 and p[1] > 79.9 and p[2] > 1.7],
                        "the bank's sign over it")
        self.assertFalse(self.near(yard, 330, 40, 25), 'deep inside a mall: the map alone')

    def test_a_tram_stop_has_a_shelter_by_its_street(self):
        stop = {'id': 'tram', 'kind': 'pin', 'pos': [200, 90, 0], 'tags': {'e2r_cat': 'tram_stop', 'name': 'Lavra'}}
        scene = self.build([{'roads': [STREET], 'points': [stop]}])
        shelters = [it for it in scene['items'].values() if 'point_tram' in str(it.name)]
        self.assertEqual(len(shelters), 1)
        self.assertTrue(str(shelters[0].shape).endswith('s_busstop_jri.dae'))
        self.assertGreater(abs(shelters[0].pos[2] - 90), 4, 'beyond the kerb, off the carriageway')

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


class PinSiteTests(PinScene):
    """L3 sites (docs/POI.md): 'pin_site' outlines and the pins of their categories without one.
    The street runs along y = 90 (carriageway 86..94); the ground lies at -0.25."""
    GROUND = -.25

    def test_a_dealer_lot_parks_cars_flies_flags_and_names_itself_on_a_pylon(self):
        site = {'id': 'dealer', 'kind': 'pin_site', 'tags': {'e2r_cat': 'car_dealer', 'name': 'Auto Plaza'},
                'rings': [[[100, 30], [180, 30], [180, 82], [100, 82]]]}
        showroom = {'id': 'showroom', 'height': 6, 'tags': {'building': 'retail'},
                    'rings': [[[110, 35], [140, 35], [140, 55], [110, 55]]]}
        scene = self.build([{'roads': [STREET], 'buildings': [showroom], 'areas': [site]}], parkedCars=0)
        bays = self.bays(scene)
        self.assertGreater(len(bays), 50, "the lot is a car park: its bays take the game's cars")
        self.assertTrue(all(100 < b[0] < 180 and 30 < b[1] < 82 for b in bays))
        self.assertFalse([b for b in bays if 110 <= b[0] <= 140 and 35 <= b[1] <= 55], 'none in the showroom')
        glyphs = [p for p in self.corners(scene, 'e2rf_glyphs') if 100 < p[0] < 180 and 70 < p[1] < 82]
        self.assertTrue(glyphs and min(p[2] for p in glyphs) > self.GROUND + 4, 'its name high on a pylon')
        # across the street's line: each face reads to one direction of the street
        xs, ys = [p[0] for p in glyphs], [p[1] for p in glyphs]
        self.assertGreater(max(ys) - min(ys), 2 * (max(xs) - min(xs)))
        tops = [p for p in self.corners(scene, 'e2rf_yard') if p[2] > self.GROUND + 5.1 and 79 < p[1] < 82]
        self.assertGreaterEqual(self.groups([p[0] for p in tops], 3), 4, 'feather flags along the street edge')
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        self.assertFalse([b for b in bays if abs(b[0] - cx) < 1.5 and abs(b[1] - cy) < 3], 'no car under the pylon')
        # a dealer in a building's outline has no lot of its own
        site['tags']['e2r_bld'] = 'yes'
        showroom['rings'] = site['rings']
        scene = self.build([{'roads': [STREET], 'buildings': [showroom], 'areas': [site]}], parkedCars=0)
        self.assertFalse(self.bays(scene))

    def test_a_motel_has_its_name_on_a_pylon_by_the_road(self):
        motel = {'id': 'motel', 'height': 7, 'tags': {'building': 'yes'},
                 'rings': [[[40, 50], [80, 50], [80, 70], [40, 70]]]}
        site = {'id': 'motel_site', 'kind': 'pin_site', 'rings': motel['rings'],
                'tags': {'e2r_cat': 'motel', 'name': 'Motel 7', 'e2r_bld': 'yes'}}
        points = [{'id': 'm', 'kind': 'pin', 'pos': [300, 60, 0], 'tags': {'e2r_cat': 'motel', 'name': 'Motel Ranch'}},
                  {'id': 'long', 'kind': 'pin', 'pos': [200, 60, 0], 'tags': {'e2r_cat': 'motel', 'name': 'Gasthof Zur Alten Post'}},
                  {'id': 'n', 'kind': 'pin', 'pos': [360, 60, 0], 'tags': {'e2r_cat': 'motel'}},
                  {'id': 'in', 'kind': 'pin', 'pos': [60, 60, 0], 'tags': {'e2r_cat': 'motel', 'name': 'Motel 7'}}]
        scene = self.build([{'roads': [STREET], 'buildings': [motel], 'areas': [site], 'points': points}], parkedCars=0)
        high = [p for p in self.corners(scene, 'e2rf_glyphs') if p[2] > self.GROUND + 4]

        def pylon(x0, x1):
            return [p for p in high if x0 < p[0] < x1 and 71 < p[1] < 86]
        # set back 16 m behind the street: its pylon stands between it and the street, off the kerb
        self.assertTrue(pylon(40, 80), 'the motel behind its yard')
        self.assertEqual(self.groups([p[0] for p in pylon(40, 80)], 1), 1, 'one pylon: its own point inside adds none')
        self.assertTrue(pylon(290, 310), 'a motel mapped as a point')
        self.assertLess(max(p[1] for p in pylon(290, 310)), 86 - 1.4, 'clear of the carriageway')
        self.assertFalse(pylon(340, 380), 'no name, no pylon')
        # a long name on two lines of letters over 0.55 m, not one line of small ones
        rows = sorted({round(p[2], 2) for p in pylon(190, 210)})     # the letters' feet and heads
        self.assertEqual(len(rows), 4, rows)
        self.assertGreater(rows[1] - rows[0], .55)
        short = sorted({round(p[2], 2) for p in pylon(290, 310)})
        self.assertEqual(len(short), 2, 'a short name on one line')
        self.assertGreater(short[1] - short[0], .55, 'read from the road')

    def test_a_rest_area_has_tables_a_bin_and_a_toilet_unless_osm_maps_them(self):
        rest = {'id': 'rest', 'kind': 'pin_site', 'tags': {'e2r_cat': 'rest_area'},
                'rings': [[[200, 40], [300, 40], [300, 84], [200, 84]]]}
        node = {'id': 'r', 'kind': 'pin', 'pos': [100, 90, 0], 'tags': {'e2r_cat': 'rest_area'}}   # on the street
        scene = self.build([{'roads': [STREET], 'areas': [rest], 'points': [node]}], parkedCars=0)
        yard = self.corners(scene, 'e2rf_yard')

        def at(z, x0, x1, y0, y1):
            return [p for p in yard if abs(p[2] - (self.GROUND + z)) < 1e-3 and x0 < p[0] < x1 and y0 < p[1] < y1]
        tables, toilets, bins = at(.77, 200, 300, 40, 84), at(2.35, 200, 300, 40, 84), at(.9, 200, 300, 40, 84)
        self.assertEqual(self.groups([p[0] for p in tables], 2.5), 3, 'three picnic tables in the site')
        self.assertTrue(toilets and bins)
        self.assertTrue(all(201 < p[0] < 299 and 41 < p[1] < 83 for p in tables + toilets + bins), 'inside, off its edge')
        # the node on the carriageway: its pocket beside the street, not on it
        pocket = at(.77, 80, 120, 60, 120)
        self.assertTrue(pocket and all(p[1] > 94.5 for p in pocket), 'tables pushed off the asphalt')
        self.assertTrue(at(2.35, 80, 120, 60, 120), 'its toilet booth')
        # OSM maps a table and toilets in it: those stand, ours do not double them
        mapped = [{'id': 't', 'kind': 'pin', 'pos': [250, 60, 0], 'tags': {'e2r_cat': 'picnic'}},
                  {'id': 'w', 'kind': 'pin', 'pos': [270, 60, 0], 'tags': {'e2r_cat': 'toilets'}}]
        scene = self.build([{'roads': [STREET], 'areas': [rest], 'points': mapped}], parkedCars=0)
        yard = self.corners(scene, 'e2rf_yard')
        self.assertEqual(self.groups([p[0] for p in at(.77, 200, 300, 40, 84)], 2.5), 1)
        self.assertEqual(self.groups([p[0] for p in at(2.35, 200, 300, 40, 84)], 2.5), 1)


if __name__ == '__main__':
    unittest.main()
