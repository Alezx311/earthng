"""The register method (venues.py) and the look of a place (generator.lua BLD.VENUE), on a made-up type."""
import json
import math
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lupa.luajit21 import LuaRuntime
import venues

ROOT = Path(__file__).resolve().parents[1]
STREET = {'id': 'street', 'nodes': ['a', 'b'], 'width': 8, 'tags': {'highway': 'residential'},
          'points': [[0, 90, 0], [400, 90, 0]]}       # along y = 90, north of the building below
RING = [[100, 40], [160, 40], [160, 70], [100, 70]]
DEMO = {'title': 'Клуб № {ref}', 'credit': {'source': 'Оператор', 'data': 'list', 'url': 'https://example.org/'},
        'name': re.compile(r'клуб', re.I), 'not': re.compile(r'нічний', re.I),
        'regions': {'71': (48.4, 29.6, 50.1, 32.9), '32': (49.1, 29.2, 51.6, 32.2)}}
CARD = {'rgb': [16, 124, 100], 'sign': [.5, .001, .999, .124], 'banner': [.5005, .126, .578, .999],
        'panel': {'wide': 8, 'tall': 1, 'low': 3.1, 'least': 2.3, 'shed': 2.6, 'deep': 1.5}, 'door': {'wide': 5, 'high': 3},
        'banners': {'count': 3, 'step': 1.5, 'pole': 7, 'wide': .9, 'high': 4.2, 'drop': .3, 'aside': 7.5,
                    'out': [6, 8, 4, 11, 14]}}


def row(ref, address):
    return {'ref': ref, 'address': address, 'facts': [], **venues.parse_address(address)}


class AddressTests(unittest.TestCase):
    def test_every_form_of_address(self):
        for text, settlement, street, house in (
                ('21010, м. Вінниця, вул. Садова, 24', 'Вінниця', 'вул. Садова', '24'),
                ('23600, м. Тульчин, вул. Лісова, 55 А', 'Тульчин', 'вул. Лісова', '55а'),
                ('04128, м. Київ, вул. Садова 19', 'Київ', 'вул. Садова', '19'),
                ('58023, м. Чернівці,вул. Руська, 248 М', 'Чернівці', 'вул. Руська', '248м'),
                ('08131, с. Нове Село, вул. Андрія Шевченка, 2', 'Нове Село', 'вул. Андрія Шевченка', '2'),
                ('90125, Берегівський район, с. Камʼянське, вул. Лісова, 4-А', 'Камʼянське', 'вул. Лісова', '4а'),
                ('70417, с. Сонячне, Сонячне шосе, б. 2а', 'Сонячне', 'Сонячне шосе', '2а')):
            with self.subTest(text=text):
                got = venues.parse_address(text)
                self.assertEqual((got['settlement'], got['street'].strip(), got['house']), (settlement, street, house))

    def test_a_mall_and_a_metro_hall_are_noted(self):
        mall = venues.parse_address('04073, м. Київ, вул. Садова, 36. ТРЦ «Центр» (вхід № 3)')
        self.assertEqual((mall['within'], mall['house']), ('mall', '36'))
        self.assertEqual(venues.parse_address('м. Харків, Станція метро "Парк", вестибюль №1')['within'], 'metro')

    def test_street_words_leave_the_type_and_initials(self):
        self.assertEqual(venues.street_words('вул. М. Шевченка'), ['шевченка'])
        self.assertEqual(venues.street_words('вулиця Миколи Шевченка'), ['миколи', 'шевченка'])

    def test_a_register_reads_its_rows(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(venues, 'REGISTERS', Path(folder)):
            (Path(folder) / 'demo.tsv').write_text('# a note\n3201\t04128, м. Київ, вул. Садова 19\tgarden,cafe\n', encoding='utf8')
            rows = venues.load_register('demo')
        self.assertEqual([(r['ref'], r['house'], r['facts']) for r in rows], [('3201', '19', ['garden', 'cafe'])])


class ResolveTests(unittest.TestCase):
    PLACE = {'name': 'київ', 'lat': 50.45, 'lon': 30.52, 'place': 'city'}

    def setUp(self):
        types = patch.dict(venues.TYPES, {'demo': DEMO})
        types.start()
        self.addCleanup(types.stop)

    def resolved(self, rows, addressed=(), named=(), places=None, anchors=None):
        return venues.resolve(rows, {'places': [self.PLACE] if places is None else places,
                                     'addressed': list(addressed), 'named': list(named)}, 'demo', anchors)

    def item(self, osm, lat=50.46, lon=30.5, area=0., name='', street='', house='', building=''):
        return {'osm': osm, 'lat': lat, 'lon': lon, 'area': area, 'name': name, 'street': street, 'house': house, 'building': building}

    def test_a_number_in_a_name_wins_over_the_address(self):
        rows = [row('3244', '02161, м. Київ, вул. Садова, 52')]
        out = self.resolved(rows, addressed=[self.item('way/1', street='Садова вулиця', house='52', building='yes')],
                            named=[self.item('node/2', name='Клуб № 3244')])
        self.assertEqual((out[0]['how'], out[0]['osm']), ('number', 'node/2'))

    def test_the_address_takes_the_building_in_town_only(self):
        rows = [row('3244', '02161, м. Київ, вул. Садова, 52')]
        town = self.item('way/1', street='вулиця Садова', house='52', building='yes')
        node = self.item('node/3', street='вулиця Садова', house='52', area=0)
        away = self.item('way/2', lat=49.5, lon=30.0, street='вулиця Садова', house='52', building='yes')
        out = self.resolved(rows, addressed=[away, node, town])
        self.assertEqual((out[0]['how'], out[0]['osm']), ('address', 'way/1'))
        self.assertEqual(self.resolved(rows, addressed=[away])[0]['reason'], 'no_address')

    def test_a_name_alone_decides_only_in_a_town_of_one_row(self):
        named = [self.item('way/5', name='Клуб', area=400)]
        one = [row('3244', '02161, м. Київ, вул. Садова, 52')]
        two = one + [row('3245', '02105, м. Київ, вул. Лісова, 8')]
        self.assertEqual(self.resolved(one, named=named)[0]['how'], 'name')
        self.assertTrue(all('reason' in r for r in self.resolved(two, named=named)))

    def test_the_operators_point_rules_out_a_namesake(self):
        rows = [row('7148', '19000, м. Лісове, вул. Садова, 21')]
        away = self.item('way/9', lat=49.545, lon=31.001, name='Клуб', area=900)
        out = self.resolved(rows, named=[away], places=[], anchors={'7148': (49.0, 31.9)})
        self.assertEqual((out[0]['how'], out[0]['lat'], out[0].get('osm')), ('map', 49.0, None))

    def test_an_anchor_takes_the_building_beside_it(self):
        rows = [row('3244', '02161, м. Київ, вул. Садова, 52'), row('3245', '02105, м. Київ, вул. Лісова, 8')]
        here = self.item('way/5', lat=50.5, lon=30.6, name='Клуб', area=400)
        out = self.resolved(rows, named=[here], anchors={'3244': (50.5002, 30.6002), '3245': (50.40, 30.70)})
        self.assertEqual((out[0]['how'], out[0]['osm']), ('name', 'way/5'))
        self.assertEqual(out[1]['how'], 'map')

    def test_an_anchor_in_the_big_city_is_no_anchor_for_a_village(self):
        # a geocoder that cannot find a village puts it in the regional centre
        rows = [row('3201', '07000, с. Лісове, вул. Садова, 1')]
        village = {'name': 'лісове', 'lat': 50.8, 'lon': 31.0, 'place': 'village'}
        city = self.item('way/1', lat=50.45, lon=30.52, street='вулиця Садова', house='1', building='yes')
        out = self.resolved(rows, addressed=[city], places=[village], anchors={'3201': (50.4501, 30.5201)})
        self.assertEqual(out[0]['reason'], 'no_address_anchor_elsewhere')
        here = self.item('way/2', lat=50.801, lon=31.001, street='вулиця Садова', house='1', building='yes')
        out = self.resolved(rows, addressed=[city, here], places=[village], anchors={'3201': (50.4501, 30.5201)})
        self.assertEqual((out[0]['how'], out[0]['osm']), ('address', 'way/2'))

    def test_a_namesake_in_another_region_is_no_town(self):
        rows = [row('7148', '19000, с. Лісове, вул. Садова, 18')]
        elsewhere = {'name': 'лісове', 'lat': 46.9, 'lon': 33.0, 'place': 'village'}
        there = self.item('way/3', lat=46.901, lon=33.001, street='вулиця Садова', house='18', building='yes')
        self.assertEqual(self.resolved(rows, addressed=[there], places=[elsewhere])[0]['reason'], 'no_settlement')

    def test_an_anchor_outside_its_region_is_dropped(self):
        self.assertFalse(venues.in_region('demo', '7142', (50.45, 30.52)))
        self.assertTrue(venues.in_region('demo', '7141', (49.44, 32.06)))
        self.assertTrue(venues.in_region('demo', '9999', (10, 10)))           # no region of that number
        with tempfile.TemporaryDirectory() as folder, patch.object(venues, 'REGISTERS', Path(folder)):
            (Path(folder) / 'demo.map.json').write_text(json.dumps({'points': {'7142': [50.45, 30.52], '7141': [49.44, 32.06]}}), encoding='utf8')
            self.assertEqual(list(venues.anchors_of('demo')), ['7141'])

    def test_nothing_is_guessed_without_a_settlement(self):
        out = self.resolved([row('3201', '20324, Уманський р-н, автодорога, 203 км, будинок б/н')], places=[])
        self.assertEqual(out[0]['reason'], 'no_settlement')

    def test_the_catalogue_is_what_the_pack_covers(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(venues, 'REGISTERS', Path(folder)):
            record = {'ref': '3244', 'name': 'Клуб № 3244', 'lat': 50.46, 'lon': 30.5, 'within': None}
            other = {'ref': '3245', 'name': 'Клуб № 3245', 'reason': 'no_address'}
            (Path(folder) / 'demo.located.json').write_text(json.dumps({'records': [record, other]}), encoding='utf8')
            self.assertEqual([p['ref'] for p in venues.catalogue([[30, 50, 31, 51]])], ['3244'])
            self.assertEqual(venues.catalogue([[35, 48, 36, 49]]), [])
            self.assertEqual(venues.credits([{'type': 'demo'}]), [DEMO['credit']])

    def test_no_type_is_in_use(self):
        with patch.dict(venues.TYPES, clear=True):
            self.assertEqual(venues.TYPES, {})
        self.assertEqual(list(venues.located()), [])
        self.assertEqual(venues.catalogue([[20, 44, 41, 53]]), [])


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.g = self.lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8'))
        self.g.VENUE.types.demo = self.table(CARD)

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def build(self, buildings, points, roads=(STREET,), far=False):
        cells = [{'buildings': buildings, 'points': points, 'roads': list(roads)}]
        return self.g.build(self.table(cells), 0, 0, self.table({'terrainStep': 100, 'far': far, 'maxTrees': 0}))[2 if far else 1]

    def corners(self, scene, material):
        out = []
        for item in scene['items'].values():
            for mesh in (item.meshes or self.lua.table()).values():
                if mesh.material == material:
                    for k in range(1, len(mesh.faces) + 1):
                        face = mesh.faces[k]
                        p = mesh.verts[face.v + 1]
                        out.append((p.x + item.pos[1], p.y + item.pos[2], p.z + item.pos[3]))
        return out

    @staticmethod
    def building(height=12, ring=RING):
        return {'id': 'b', 'height': height, 'tags': {'building': 'office'}, 'rings': [ring]}

    @staticmethod
    def poi(pos=(130, 55, 0), **tags):
        return {'id': 'v', 'kind': 'venue', 'pos': list(pos),
                'tags': {'e2r_venue': 'demo', 'e2r_ref': '12', 'name': 'Клуб № 12', **tags}}

    def test_no_card_draws_nothing(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        g = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8'))
        self.assertEqual(len(list(g.VENUE.types.items())), 0)
        self.g.VENUE.types.demo = None
        self.assertEqual(self.corners(self.build([self.building()], [self.poi()]), 'e2rf_brand_photo'), [])

    def test_the_door_is_on_the_street_wall_with_its_panel_and_banners(self):
        for ring in (RING, list(reversed(RING))):
            scene = self.build([self.building(ring=ring)], [self.poi()])
            photo = self.corners(scene, 'e2rf_brand_photo')
            self.assertTrue(photo)
            panel = [p for p in photo if 70 < p[1] < 73]
            self.assertAlmostEqual(min(p[0] for p in panel), 126, places=3)     # 8 m wide, mid wall
            self.assertAlmostEqual(max(p[0] for p in panel), 134, places=3)
            glass = self.corners(scene, 'e2rf_storefront')
            self.assertTrue(glass and all(p[1] > 69.9 for p in glass))
            # banners beside the door, off the road (it starts at y = 86) and off the building
            cloth = [p for p in photo if p[2] > 4.2]
            self.assertTrue(cloth)
            self.assertTrue(all(70 < p[1] < 85 and not 126 < p[0] < 134 for p in cloth))

    def test_a_mapped_door_chooses_the_wall(self):
        door = {'id': 'd', 'kind': 'entrance', 'pos': [160, 50, 0], 'tags': {'entrance': 'main'}}
        scene = self.build([self.building()], [self.poi(), door])
        glass = self.corners(scene, 'e2rf_storefront')
        self.assertTrue(glass and all(p[0] > 159.9 for p in glass))

    def test_two_places_at_one_address_share_one_panel(self):
        one = self.corners(self.build([self.building()], [self.poi()]), 'e2rf_brand_photo')
        second = dict(self.poi(), id='w')
        two = self.corners(self.build([self.building()], [self.poi(), second]), 'e2rf_brand_photo')
        self.assertEqual(len(one), len(two))

    def test_a_metro_hall_draws_nothing_and_a_mall_no_banners(self):
        self.assertEqual(self.corners(self.build([self.building()], [self.poi(e2r_within='metro')]), 'e2rf_brand_photo'), [])
        mall = self.corners(self.build([self.building()], [self.poi(e2r_within='mall')]), 'e2rf_brand_photo')
        self.assertTrue(mall and all(p[2] < 5 for p in mall))

    def test_an_unknown_type_and_a_far_tile_draw_nothing(self):
        poi = self.poi()
        poi['tags']['e2r_venue'] = 'somewhere_else'
        self.assertEqual(self.corners(self.build([self.building()], [poi]), 'e2rf_brand_photo'), [])
        self.assertEqual(self.corners(self.build([self.building()], [self.poi()], far=True), 'e2rf_brand_photo'), [])

    def test_a_point_beside_its_building_still_means_it(self):
        scene = self.build([self.building()], [self.poi((130, 75, 0))])
        self.assertTrue([p for p in self.corners(scene, 'e2rf_brand_photo') if 70 < p[1] < 73])

    def test_a_single_storey_place_has_its_panel_at_the_eaves(self):
        scene = self.build([self.building(height=3)], [self.poi()])
        panel = [p for p in self.corners(scene, 'e2rf_brand_photo') if 70 < p[1] < 73]
        self.assertTrue(panel)
        self.assertGreaterEqual(min(p[2] for p in panel) - min(p[2] for p in self.corners(scene, 'e2rf_storefront')), 2.2)

    def test_a_shed_is_left_alone(self):
        self.assertEqual(self.corners(self.build([self.building(height=2.2)], [self.poi()]), 'e2rf_brand_photo'), [])

    def test_a_place_without_a_mapped_building_has_a_board_by_the_road(self):
        scene = self.build([], [self.poi((130, 70, 0))])
        photo = self.corners(scene, 'e2rf_brand_photo')
        self.assertTrue(photo)
        self.assertTrue(all(p[1] < 86 for p in photo))       # off the carriageway
        self.assertEqual(self.corners(self.build([], [self.poi((130, 90, 0))]), 'e2rf_brand_photo'), [])    # not on it

    def test_the_map_lists_the_place_by_name(self):
        scene = self.build([self.building()], [self.poi()])
        marks = [p for p in scene['brandPOIs'].values()]
        self.assertEqual([(m.kind, m.label) for m in marks], [('venue', 'Клуб № 12')])
        self.assertAlmostEqual(math.fsum((marks[0].x, marks[0].y)), 185)


if __name__ == '__main__':
    unittest.main()
