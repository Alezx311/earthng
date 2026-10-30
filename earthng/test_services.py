"""Roadside services and zones: the pack's classes and what the generator does with them."""
import tempfile
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime
from PIL import Image
import fast_art
import fast_style as style
import looks
import retail

ROOT = Path(__file__).resolve().parents[1]
STREET = {'id': 'street', 'nodes': ['a', 'b'], 'width': 8, 'tags': {'highway': 'residential'},
          'points': [[0, 90, 0], [400, 90, 0]]}


class ClassTests(unittest.TestCase):
    def test_every_class_and_nothing_else(self):
        for tags in ({'shop': 'car_repair'}, {'shop': 'tyres'}, {'amenity': 'car_wash'}, {'amenity': 'charging_station'},
                     {'amenity': 'pharmacy'}, {'amenity': 'bank'}, {'amenity': 'cafe'}, {'amenity': 'restaurant'}):
            with self.subTest(tags=tags):
                self.assertEqual(retail.kind(tags), 'service')
                self.assertEqual(style.point_kind(tags), 'service')
        for tags in ({'amenity': 'bench'}, {'amenity': 'school'}, {'shop': 'clothes'}, {'amenity': 'parking'}):
            self.assertIsNone(retail.kind(tags))

    def test_older_classes_keep_theirs(self):
        self.assertEqual(retail.kind({'amenity': 'fast_food', 'brand': "McDonald's"}), 'fast_food')
        self.assertEqual(retail.kind({'amenity': 'post_office', 'name': 'Нова пошта'}), 'post')
        self.assertEqual(retail.kind({'shop': 'convenience'}), 'grocery')

    def test_a_network_is_known_by_name_branch_number_or_item(self):
        for tags, key in (({'amenity': 'pharmacy', 'name': 'Подорожник'}, 'podorozhnyk'),
                          ({'amenity': 'pharmacy', 'name': 'Подорожник №12'}, 'podorozhnyk'),
                          ({'amenity': 'pharmacy', 'name': 'Аптека 911'}, 'apteka_911'),
                          ({'amenity': 'bank', 'name': 'Каса', 'brand:wikidata': 'Q1515015'}, 'privatbank'),
                          ({'amenity': 'bank', 'operator': 'Ощадбанк'}, 'oschadbank'),
                          ({'amenity': 'charging_station', 'brand': 'TOKA'}, 'toka'),
                          ({'shop': 'tyres', 'brand': 'Віанор'}, 'vianor')):
            with self.subTest(tags=tags):
                self.assertEqual(retail.brand(tags), key)
                self.assertEqual(retail.enriched(tags).get('e2r_brand'), key)

    def test_a_shop_with_a_service_name_is_no_network_shop(self):
        self.assertIsNone(retail.brand({'shop': 'convenience', 'name': 'Подорожник'}))
        self.assertIsNone(retail.brand({'amenity': 'pharmacy', 'name': 'Аптека біля дому'}))

    def test_the_storefront_experiment_keeps_its_points(self):
        saved, style.POIS = style.POIS, True
        try:
            self.assertEqual(style.point_kind({'amenity': 'pharmacy'}), 'poi')
            self.assertEqual(style.point_kind({'shop': 'tyres'}), 'poi')
            self.assertEqual(style.point_kind({'amenity': 'charging_station'}), 'service')
        finally:
            style.POIS = saved

    def test_points_and_sites_reach_the_pack(self):
        include = {'buildings': True}
        self.assertTrue(looks.keep_scenery('service', include))
        self.assertTrue(looks.keep_scenery('service_site', include))
        self.assertFalse(looks.keep_scenery('service', {'buildings': False}))


class ZoneTests(unittest.TestCase):
    def test_zones_take_the_cover_that_plants_like_them(self):
        for tags, kind in (({'leisure': 'pitch'}, 'meadow'), ({'leisure': 'pitch', 'surface': 'grass'}, 'meadow'),
                           ({'leisure': 'pitch', 'surface': 'asphalt'}, 'paved'), ({'leisure': 'track'}, 'meadow'),
                           ({'amenity': 'school'}, 'residential'), ({'amenity': 'kindergarten'}, 'residential'),
                           ({'amenity': 'hospital'}, 'residential'), ({'amenity': 'university'}, 'residential'),
                           ({'leisure': 'stadium'}, 'residential'), ({'landuse': 'allotments'}, 'orchard')):
            with self.subTest(tags=tags):
                self.assertEqual(style.ground_kind(tags), kind)

    def test_older_covers_stay(self):
        self.assertEqual(style.ground_kind({'leisure': 'playground'}), 'playground')
        self.assertEqual(style.ground_kind({'landuse': 'cemetery'}), 'park')
        self.assertEqual(style.ground_kind({'landuse': 'forest'}), 'forest')


class ArtTests(unittest.TestCase):
    def test_every_network_has_its_cell_and_colours(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        g = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8'))
        for index, (_, colour, key, *_) in enumerate(fast_art.SERVICE_SIGNS):
            cell = fast_art.SERVICE_CELL + index
            if key.startswith('plain_'):
                continue
            self.assertEqual(g.BRANDS[key][1], cell, key)
            self.assertEqual(tuple(g.BRANDS[key][3][n] for n in (1, 2, 3)), colour, key)
        self.assertEqual(set(retail.SERVICE_NETWORKS),
                         {key for _, _, key, *_ in fast_art.SERVICE_SIGNS if not key.startswith('plain_')})
        last = fast_art.SERVICE_CELL + len(fast_art.SERVICE_SIGNS) - 1
        self.assertLess(last, fast_art.SERVICE_SWATCH[0])

    def test_the_swatch_holds_each_networks_colour(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        g = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8'))
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as logos:
            fast_art.brand_art(Path(tmp), logos)
            atlas = Image.open(Path(tmp) / 'brand_sign.color.png').convert('RGB')
            self.assertEqual(atlas.size, (2048, 4096))
            for index, (_, colour, _key, *_) in enumerate(fast_art.SERVICE_SIGNS):
                uv = g.shopFlat(fast_art.SERVICE_CELL + index, 2)
                self.assertEqual(atlas.getpixel((int(uv[1] * 2048), int(uv[2] * 4096))), colour)


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.g = self.lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8'))

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def sign_cells(self, points, height=7, tags=None):
        building = {'id': 'b', 'height': height, 'tags': tags or {'building': 'commercial'},
                    'rings': [[[100, 40], [130, 40], [130, 70], [100, 70]]]}
        cells = [{'buildings': [building], 'points': points, 'roads': [STREET]}]
        scene = self.g.build(self.table(cells), 0, 0, self.table({'terrainStep': 100, 'maxTrees': 0}))[1]
        uvs = set()
        for item in scene['items'].values():
            for mesh in (item.meshes or self.lua.table()).values():
                if mesh.material == 'e2rf_brand_sign':
                    for k in range(1, len(mesh.faces) + 1):
                        uv = mesh.uvs[mesh.faces[k].u + 1]
                        uvs.add((round(uv.u, 3), round(uv.v, 3)))
        return uvs, scene

    def face(self, cell):
        box = self.g.shopUV(cell)
        return (round(box[1], 3), round(box[2], 3)), (round(box[3], 3), round(box[4], 3))

    def test_a_plain_service_has_its_class_sign(self):
        poi = {'id': 'p', 'kind': 'service', 'pos': [115, 55, 0], 'tags': {'shop': 'tyres'}}
        uvs, _ = self.sign_cells([poi])
        self.assertEqual(self.g.shopCell('service', self.table(poi['tags'])), 65)
        low, high = self.face(65)
        self.assertTrue(any(low[0] <= u <= high[0] and low[1] <= v <= high[1] for u, v in uvs))

    def test_a_network_wears_its_colour_and_shows_on_the_map(self):
        poi = {'id': 'p', 'kind': 'service', 'pos': [115, 55, 0], 'tags': {'amenity': 'bank', 'e2r_brand': 'privatbank'}}
        uvs, scene = self.sign_cells([poi])
        self.assertEqual(self.g.shopCell('service', self.table(poi['tags'])), 72)
        flat = self.g.shopFlat(72, 2)
        self.assertTrue(any(abs(u - flat[1]) < .002 and abs(v - flat[2]) < .002 for u, v in uvs))
        self.assertEqual([m.brand for m in scene['brandPOIs'].values()], ['privatbank'])

    def test_a_plain_service_stays_off_the_map(self):
        poi = {'id': 'p', 'kind': 'service', 'pos': [115, 55, 0], 'tags': {'amenity': 'cafe'}}
        self.assertEqual(len(list(self.sign_cells([poi])[1]['brandPOIs'].values())), 0)

    def test_a_tall_block_keeps_its_walls_with_a_stretch_of_shop(self):
        poi = {'id': 'p', 'kind': 'service', 'pos': [115, 68, 0], 'tags': {'amenity': 'pharmacy'}}
        uvs, _ = self.sign_cells([poi], height=27, tags={'building': 'apartments'})
        low, high = self.face(68)
        self.assertTrue(any(low[0] <= u <= high[0] and low[1] <= v <= high[1] for u, v in uvs))

    def test_a_sports_ground_stays_open(self):
        rings = [[[100, 100], [300, 100], [300, 300], [100, 300]]]
        area = {'id': 'f', 'kind': 'meadow', 'rings': rings, 'tags': {'leisure': 'pitch'}}
        meadow = {'id': 'm', 'kind': 'meadow', 'rings': rings, 'tags': {'landuse': 'meadow'}}

        def tufts(cover):
            cells = [{'areas': [cover], 'roads': [STREET]}]
            scene = self.g.build(self.table(cells), 0, 0, self.table({'terrainStep': 100}))[1]
            return sum(1 for item in scene['items'].values() if ('_lawn_' in str(item.name or '') or '_flower_' in str(item.name or ''))
                       and 120 < item.pos[1] < 280 and 120 < item.pos[2] < 280)
        self.assertGreater(tufts(meadow), 0)
        self.assertEqual(tufts(area), 0)


if __name__ == '__main__':
    unittest.main()
