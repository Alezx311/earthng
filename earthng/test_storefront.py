"""Shop fronts drawn at art build time (fast_storefront.py) and real names on signs."""
import tempfile
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime
import numpy as np
from PIL import Image
import fast_art
import fast_storefront as front

ROOT = Path(__file__).resolve().parents[1]
STREET = {'id': 'street', 'nodes': ['a', 'b'], 'width': 8, 'tags': {'highway': 'residential'},
          'points': [[0, 90, 0], [400, 90, 0]]}
BLOCK = [[100, 40], [160, 40], [160, 70], [100, 70]]
SMALL = [[100, 60], [116, 60], [116, 72], [100, 72]]


class ArtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        front.art(Path(cls.folder.name), fast_art._shop_font)
        cls.colour = np.asarray(Image.open(Path(cls.folder.name) / 'storefront.color.png').convert('RGB'), float)
        cls.glow = np.asarray(Image.open(Path(cls.folder.name) / 'storefront.glow.png').convert('RGB'), float)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def cell(self, image, k):
        x, y = k % front.COLS * front.CELL, k // front.COLS * front.CELL
        return image[y:y + front.CELL, x:x + front.CELL]

    def test_every_class_has_its_window_and_door(self):
        self.assertEqual(self.colour.shape, (2048, 2048, 3))
        self.assertLessEqual(len(front.CLASSES) * 2, front.COLS ** 2)
        for n, kind in enumerate(front.CLASSES):
            with self.subTest(kind=kind):
                self.assertGreater(np.abs(self.cell(self.colour, n * 2) - self.cell(self.colour, n * 2 + 1)).mean(), 3)

    def test_classes_look_apart(self):
        means = [self.cell(self.colour, n * 2).mean(axis=(0, 1)) for n in range(len(front.CLASSES))]
        self.assertGreater(np.abs(means[1] - means[4]).sum(), 60)      # a pharmacy is no bar

    def test_the_same_build_gives_the_same_art(self):
        a, _ = front.bay('cafe', 0, fast_art._shop_font)
        b, _ = front.bay('cafe', 0, fast_art._shop_font)
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_by_night_the_room_glows_not_the_plinth_or_the_shutter(self):
        shop = self.cell(self.glow, 0)
        self.assertGreater(shop[front.y_of(1.5)].mean(), 40)
        self.assertLess(shop[front.y_of(.1)].mean(), 2)
        self.assertLess(self.cell(self.glow, 5 * 2).mean(), 1)         # car repair: its shutter is down

    def test_atlas_and_generator_agree(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        g = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8'))
        self.g = g
        self.assertEqual(g.FRONT.per, front.COLS)
        self.assertEqual(g.FRONT.bay, front.CELL / front.METRE)
        for name, kind in (('pharmacy', 'pharmacy'), ('bank', 'bank'), ('cafe', 'cafe'), ('bar', 'bar'),
                           ('car_repair', 'car_repair'), ('tyres', 'tyres'), ('car_wash', 'car_wash')):
            self.assertEqual(front.CLASSES[g.FRONT.classes[name]], kind)


class SignTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.g = self.lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8'))

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def build(self, points, ring=BLOCK, height=15, building='apartments'):
        block = {'id': 'b', 'height': height, 'tags': {'building': building}, 'rings': [ring]}
        cells = [{'buildings': [block], 'points': points, 'roads': [STREET]}]
        return self.g.build(self.table(cells), 0, 0, self.table({'terrainStep': 100, 'maxTrees': 0}))[1]

    def verts(self, scene, material):
        out = []
        for item in scene['items'].values():
            for mesh in (item.meshes or self.lua.table()).values():
                if mesh.material == material:
                    for k in range(1, len(mesh.faces) + 1):
                        face = mesh.faces[k]
                        p, uv = mesh.verts[face.v + 1], mesh.uvs[face.u + 1]
                        out.append((p.x + item.pos[1], p.y + item.pos[2], p.z + item.pos[3], uv.u, uv.v))
        return out

    @staticmethod
    def poi(tags, kind='service', pos=(130, 69, 0)):
        return {'id': 'p', 'kind': kind, 'pos': list(pos), 'tags': tags}

    def test_a_plain_place_goes_by_its_name_on_a_band(self):
        scene = self.build([self.poi({'amenity': 'pharmacy', 'name': 'Аптека Здоров\'я'})])
        letters = self.verts(scene, 'e2rf_glyphs')
        self.assertTrue(letters)
        low = min(p[2] for p in letters)
        self.assertGreater(low, 3.0)                                   # over the visor
        self.assertLess(max(p[2] for p in letters), 3.96)              # under the sills
        self.assertTrue(all(p[1] > 69.9 for p in letters))

    def test_no_name_keeps_the_class_sign(self):
        scene = self.build([self.poi({'amenity': 'pharmacy'})])
        self.assertEqual(self.verts(scene, 'e2rf_glyphs'), [])
        box = self.g.shopUV(68)
        self.assertTrue([p for p in self.verts(scene, 'e2rf_brand_sign') if box[1] - .001 <= p[3] <= box[3] + .001 and box[2] - .001 <= p[4] <= box[4] + .001])

    def test_a_network_keeps_its_logo(self):
        scene = self.build([self.poi({'amenity': 'bank', 'name': 'ПриватБанк', 'e2r_brand': 'privatbank'})])
        self.assertEqual(self.verts(scene, 'e2rf_glyphs'), [])

    def test_a_name_too_long_for_the_band_falls_back(self):
        scene = self.build([self.poi({'amenity': 'cafe', 'name': 'Дуже довга назва кафе ' * 3})])
        self.assertEqual(self.verts(scene, 'e2rf_glyphs'), [])

    def test_the_front_is_whole_bays_with_a_door_in_the_middle_of_the_class(self):
        scene = self.build([self.poi({'amenity': 'bank'})])
        glass = self.verts(scene, 'e2rf_storefront')
        self.assertEqual(round(max(p[0] for p in glass) - min(p[0] for p in glass)), 6)     # two bays round the sign
        us = sorted({round(p[3] * 4 - .004 if p[3] * 4 % 1 < .5 else p[3] * 4 + .004) for p in glass})
        self.assertEqual({int(p[4] * 4) for p in glass if p[4] < 1}, {1})     # bank: the atlas's second row
        self.assertEqual(us, [0, 1, 2])                                       # door and window side by side

    def test_a_towers_fascia_hangs_under_its_visor(self):
        scene = self.build([self.poi({'amenity': 'pharmacy', 'name': 'Аптека'})], height=30)
        letters = self.verts(scene, 'e2rf_glyphs')
        self.assertTrue(letters)
        self.assertLess(max(p[2] for p in letters), 3.0)               # the visor starts at 3.1

    def test_a_long_name_takes_more_bays(self):
        short = self.verts(self.build([self.poi({'amenity': 'cafe', 'name': 'Хвиля'})]), 'e2rf_storefront')
        long_ = self.verts(self.build([self.poi({'amenity': 'cafe', 'name': 'Кав\'ярня на розі старої вулиці'})]), 'e2rf_storefront')
        self.assertEqual(round(max(p[0] for p in short) - min(p[0] for p in short)), 6)
        self.assertGreater(max(p[0] for p in long_) - min(p[0] for p in long_), 8)

    def test_on_a_hillside_the_door_stands_on_the_pavement(self):
        scene = self.build([self.poi({'amenity': 'bank'})])
        v = {round(p[4] * 4 % 1, 2) for p in self.verts(scene, 'e2rf_storefront')}
        self.assertTrue(v)
        self.assertEqual(self.g.frontFloor(self.table([0, 0]), self.table([10, 0]), 10, 5, 3, lambda x, y: 5), 5)
        self.assertEqual(self.g.frontFloor(self.table([0, 0]), self.table([10, 0]), 10, 5, 3, lambda x, y: 1), 3)

    def test_no_room_over_the_pavement_no_front(self):
        calls = []
        scene = self.lua.table_from({'polygon': lambda *a: calls.append(a)})
        wall = self.table([0, 0]), self.table([10, 0])
        self.g.shopFront_(scene, *wall, 10, 0, 6, -.3, 3.2, 1.6, 0)
        self.assertEqual(calls, [])
        self.g.shopFront_(scene, *wall, 10, 0, 6, -.3, 3.2, 0, 0)
        self.assertTrue(calls)

    def test_a_front_stops_at_a_bays_height_on_a_tall_wall(self):
        scene = self.build([self.poi({'amenity': 'bank'})])
        self.assertLessEqual(max(p[2] for p in self.verts(scene, 'e2rf_storefront')), 3.26)

    def test_a_small_cafe_wears_its_band_and_name_alone(self):
        scene = self.build([self.poi({'amenity': 'cafe', 'name': 'Вікторія'}, pos=(108, 66, 0))], ring=SMALL, height=4, building='yes')
        letters = self.verts(scene, 'e2rf_glyphs')
        self.assertTrue(letters)
        self.assertTrue(all(p[1] > 71.9 for p in letters))             # on the street wall alone
        flat = self.g.shopFlat(70, 2)
        self.assertTrue([p for p in self.verts(scene, 'e2rf_brand_sign') if abs(p[3] - flat[1]) < .002 and abs(p[4] - flat[2]) < .002])


if __name__ == '__main__':
    unittest.main()
