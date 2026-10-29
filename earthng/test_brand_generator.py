"""Shops and fuel stations (generator.lua BLD.SHOP) on mapped buildings, and their atlas."""
import math
import tempfile
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime
from PIL import Image
import fast_art
import retail

ROOT = Path(__file__).resolve().parents[1]
STREET = {'id': 'street', 'nodes': ['a', 'b'], 'width': 8, 'tags': {'highway': 'residential'},
          'points': [[0, 90, 0], [400, 90, 0]]}       # along y = 90, under the shops below


class BrandGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.g = self.lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8'))

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def build(self, cells, i=0, far=False):
        return self.g.build(self.table(cells), i, 0, self.table({'terrainStep': 100, 'far': far, 'maxTrees': 0}))[2 if far else 1]

    def corners(self, scene, material='e2rf_brand_sign'):
        """Triangles as three (x, y, z, u, v) corners, in world metres."""
        out = []
        for item in scene['items'].values():
            for mesh in (item.meshes or self.lua.table()).values():
                if mesh.material != material:
                    continue
                for k in range(1, len(mesh.faces) + 1, 3):
                    tri = []
                    for n in range(3):
                        face = mesh.faces[k + n]
                        p, uv, n = mesh.verts[face.v + 1], mesh.uvs[face.u + 1], mesh.normals[face.n + 1]
                        tri.append((p.x + item.pos[1], p.y + item.pos[2], p.z + item.pos[3], uv.u, uv.v, (n.x, n.y, n.z)))
                    out.append(tri)
        return out

    @staticmethod
    def normal(tri):
        """The face's own normal (the mesh winds its faces clockwise for the game)."""
        return tri[0][5]

    def materials(self, scene):
        return {mesh.material for item in scene['items'].values() for mesh in (item.meshes or self.lua.table()).values()}

    @staticmethod
    def area(tri):
        a, b, c = tri
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        return math.sqrt(sum(x * x for x in n)) / 2

    def faces_of(self, scene, cell):
        """Triangles of a network's sign face (its square sign where it has one, else its lightbox):
        their uvs within that box, spanning a good part of it."""
        box = self.g.shopMark(cell)[0]
        u0, v0, u1, v1 = box[1], box[2], box[3], box[4]
        return [t for t in self.corners(scene) if max(p[3] for p in t) - min(p[3] for p in t) > (u1 - u0) / 3
                and all(u0 - 1e-6 <= p[3] <= u1 + 1e-6 and v0 - 1e-6 <= p[4] <= v1 + 1e-6 for p in t)]

    def flat(self, scene, cell, layer):
        """Triangles in one of a network's colours (1 sign, 2 facade, 3 accent)."""
        uv = self.g.shopFlat(cell, layer)
        return [t for t in self.corners(scene) if all(abs(p[3] - uv[1]) < 1e-3 and abs(p[4] - uv[2]) < 1e-3 for p in t)]

    def test_atlas_matches_the_catalogue(self):
        brands = self.g.BRANDS
        self.assertEqual(set(brands.keys()), set(retail.ALIASES))
        for index, (label, colour, key, *_) in enumerate(fast_art.BRAND_SIGNS):
            self.assertEqual(brands[key][1], index, key)
            # the dress generator.lua knows matches the art's
            style, lua = fast_art.BRAND_STYLE[key], self.g.shopStyle(index)
            self.assertEqual((bool(lua['clad']), lua['square'], bool(lua['accent'])),
                             (style.get('clad', False), style.get('square'), 'accent' in style), key)
            self.assertEqual(tuple(brands[key][3][n] for n in (1, 2, 3)), colour, key)
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as logos:
            Image.new('RGBA', (300, 100), (200, 30, 30, 255)).save(Path(logos) / 'wog.png')
            seen = Image.new('RGBA', (300, 100), (0, 0, 0, 0))
            seen.paste((0, 120, 60, 255), (100, 20, 200, 80))
            seen.save(Path(logos) / 'okko.png')
            fast_art.brand_art(Path(tmp), logos)
            colour, glow = (Image.open(Path(tmp) / f'brand_sign.{n}.png').copy() for n in ('color', 'glow'))
            self.assertEqual(colour.size, (2048, 2048))
            self.assertEqual(glow.size, (2048, 2048))
            self.assertGreater(min(colour.getpixel((20, 64))), 230)               # okko: a see-through logo on white
            self.assertEqual(colour.getpixel((256, 64)), (0, 120, 60))            # trimmed and fitted
            self.assertLess(max(abs(a - b) for a, b in zip(colour.getpixel((512 + 20, 64)), (200, 30, 30))), 16)   # wog: its own background
            # a typographic lightbox's plain left edge is its colour (the plain signs' stripe)
            atb = colour.getpixel((2 * 512 + int(.05 * 512), 2 * 128 + 64))
            self.assertLess(max(abs(a - b) for a, b in zip(atb, fast_art.BRAND_SIGNS[10][1])), 12)
            # every network's colour where generator.lua samples its stripe
            for index, (_, rgb, key, *_) in enumerate(fast_art.BRAND_SIGNS):
                uv = self.g.shopFlat(index)
                self.assertEqual(colour.getpixel((int(uv[1] * 2048), int(uv[2] * 2048))), rgb, key)
            # lightboxes glow at night, the dark pump body does not
            self.assertGreater(sum(glow.getpixel((256, 64))), 60)
            self.assertEqual(glow.getpixel((2 * 512 + 256, 14 * 128 + 64)), (0, 0, 0))

    def test_whole_shop_wears_its_colours_and_a_sign_on_every_side(self):
        # a 60 x 40 m supermarket south of the street at y = 90 (its north wall faces it)
        ring = [[100, 40], [160, 40], [160, 80], [100, 80]]
        poi = {'id': 'p', 'kind': 'grocery', 'pos': [130, 60, 0], 'tags': {'e2r_brand': 'velmart'}}
        for points in (ring, list(reversed(ring))):
            building = {'id': 'b', 'height': 7, 'tags': {'building': 'retail', 'e2r_brand': 'velmart'}, 'rings': [points]}
            scene = self.build([{'buildings': [building], 'points': [poi], 'roads': [STREET]}])
            fronts = self.faces_of(scene, 15)
            self.assertEqual(len(fronts), 4 * 2)                   # a lightbox face on each side
            self.assertEqual({tuple(round(x) for x in self.normal(t)) for t in fronts},
                             {(0, 1, 0), (0, -1, 0), (1, 0, 0), (-1, 0, 0)})
            north = [p for t in fronts if round(self.normal(t)[1]) == 1 for p in t]
            fascia = 7 * .28
            self.assertAlmostEqual(max(p[0] for p in north) - min(p[0] for p in north), 4 * 3.5, places=3)   # 7 % of the side, half the building at most
            # clad in its facade colour all round, the fascia over the accent stripe
            top = max(p[2] for t in self.corners(scene, 'e2rf_roof') for p in t)
            facade = self.flat(scene, 15, 2)
            self.assertAlmostEqual(sum(self.area(t) for t in facade), 200 * (top - (top - 7 - .3) + .15), delta=200 * .5)
            accent = self.flat(scene, 15, 3)
            self.assertAlmostEqual(min(p[2] for t in accent for p in t), top - fascia - .3, places=3)
            # glazing toward the street only
            glass = self.corners(scene, 'e2rf_wall_shop_dark')
            self.assertTrue(glass and all(p[1] > 80 for t in glass for p in t))

    def test_square_sign_for_a_square_logo(self):
        building = {'id': 'b', 'height': 5, 'tags': {'building': 'retail', 'e2r_brand': 'atb'},
                    'rings': [[[100, 100], [140, 100], [140, 120], [100, 120]]]}
        fronts = self.faces_of(self.build([{'buildings': [building]}]), 10)
        self.assertEqual(len(fronts), 4 * 2)
        for t in fronts:
            n = self.normal(t)
            along = [p[0] for p in t] if abs(n[1]) > .5 else [p[1] for p in t]
            self.assertAlmostEqual(max(along) - min(along), max(p[2] for p in t) - min(p[2] for p in t), places=3)

    def test_mcdonalds_and_post_office_have_signs_but_locker_is_only_a_marker(self):
        building = {'id': 'b', 'height': 5, 'tags': {'building': 'retail'},
                    'rings': [[[100, 100], [140, 100], [140, 140], [100, 140]]]}
        for kind, brand, subtype, has_sign in [('fast_food', 'mcdonalds', None, True),
                                               ('post', 'nova_poshta', 'office', True),
                                               ('post', 'nova_poshta', 'locker', False)]:
            tags = {'e2r_brand': brand}
            if subtype:
                tags['e2r_post_type'] = subtype
            poi = {'id': 'p', 'kind': kind, 'pos': [120, 120, 0], 'tags': tags}
            scene = self.build([{'buildings': [building], 'points': [poi]}])
            self.assertEqual(len(self.faces_of(scene, self.g.BRANDS[brand][1])) > 0, has_sign, subtype)
            self.assertEqual(scene.brandPOIs[1].brand, brand)
            self.assertEqual(scene.brandPOIs[1].postType, subtype)

    def test_shop_in_an_apartment_block_dresses_its_stretch_of_the_street_wall(self):
        building = {'id': 'b', 'height': 27, 'tags': {'building': 'apartments'},
                    'rings': [[[100, 20], [160, 20], [160, 80], [100, 80]]]}
        poi = {'id': 'p', 'kind': 'grocery', 'pos': [110, 75, 0], 'tags': {'e2r_brand': 'fora'}}
        scene = self.build([{'buildings': [building], 'points': [poi], 'roads': [STREET]}])
        top = max(p[2] for t in self.corners(scene, 'e2rf_roof') for p in t)
        base = top - 27
        fronts = self.faces_of(scene, 12)
        self.assertEqual(len(fronts), 2)
        self.assertEqual(round(self.normal(fronts[0])[1]), 1)       # the street wall
        zs = [p[2] - base for t in fronts for p in t]
        self.assertTrue(3.1 <= min(zs) and max(zs) <= 4.5)          # on the fascia over the ground floor
        fascia = self.flat(scene, 12, 2)
        xs = [p[0] for t in fascia for p in t]
        self.assertAlmostEqual(max(xs) - min(xs), 10, places=3)
        self.assertTrue(all(abs(p[1] - 80.07) < 1e-3 for t in fascia for p in t))
        glass = self.corners(scene, 'e2rf_wall_shop_dark')
        self.assertEqual(len(glass), 2)
        self.assertAlmostEqual(max(p[2] for t in glass for p in t) - base, 3.1 - .25, places=3)   # under the red stripe

    def test_unknown_convenience_store_reads_produkty_but_supermarket_nothing(self):
        building = {'id': 'b', 'height': 15, 'tags': {'building': 'apartments'},
                    'rings': [[[100, 100], [140, 100], [140, 140], [100, 140]]]}
        for shop, signed in (('convenience', True), ('supermarket', False)):
            poi = {'id': 'p', 'kind': 'grocery', 'pos': [120, 105, 0], 'tags': {'shop': shop}}
            scene = self.build([{'buildings': [building], 'points': [poi]}])
            self.assertEqual(len(self.faces_of(scene, 33)) > 0, signed, shop)

    def test_sign_clips_once_at_tile_seam(self):
        def total(x0, tiles):
            building = {'id': 'b', 'height': 6, 'tags': {'building': 'retail', 'e2r_brand': 'velmart'},
                        'rings': [[[x0, 100], [x0 + 40, 100], [x0 + 40, 130], [x0, 130]]]}
            cell = {'buildings': [building]}
            return sum(self.area(t) for i in tiles for t in self.corners(self.build([cell], i=i)))
        self.assertAlmostEqual(total(480, (0, 1)), total(100, (0,)), places=3)

    def test_fuel_site_roof_is_an_open_canopy_with_pumps_and_a_pylon(self):
        site = {'id': 'site', 'kind': 'fuel_site', 'tags': {'e2r_brand': 'okko'},
                'rings': [[[100, 20], [180, 20], [180, 84], [100, 84]]]}
        roof = {'id': 'roof', 'tags': {'building': 'roof'},
                'rings': [[[110, 40], [140, 40], [140, 54], [110, 54]]]}
        shop = {'id': 'shop', 'height': 4, 'tags': {'building': 'retail'},
                'rings': [[[150, 30], [170, 30], [170, 45], [150, 45]]]}
        poi = {'id': 'p', 'kind': 'fuel', 'pos': [165, 70, 0], 'tags': {'e2r_brand': 'okko'}}
        cell = {'areas': [site], 'buildings': [roof, shop], 'points': [poi], 'roads': [STREET]}
        scene = self.build([cell])
        # no walls under the roof: only the shop's
        for material in self.materials(scene):
            if material.startswith('e2rf_wall_'):
                self.assertTrue(all(p[0] >= 149 for t in self.corners(scene, material) for p in t), material)
        tris = self.corners(scene)
        top = max(p[2] for t in self.corners(scene, 'e2rf_roof') for p in t)
        base = top - 5.6                                              # a canopy clears a lorry
        under = [t for t in tris if all(abs(p[2] - (top - .9)) < 1e-6 for p in t) and self.normal(t)[2] < -.99]
        self.assertAlmostEqual(sum(self.area(t) for t in under), 30 * 14, places=3)
        # pumps: two islands across, three along, two pumps each, under the canopy
        pumps = [t for t in tris if all(abs(p[2] - (base + .18 + 1.85)) < .05 for p in t) and self.normal(t)[2] > .99]
        self.assertEqual(len(pumps), 2 * 2 * 3 * 2)
        self.assertTrue(all(110 < p[0] < 140 and 40 < p[1] < 54 for t in pumps for p in t))
        # the network's square sign on the canopy's two long sides, on the shop's four, on both
        # faces of the pylon; the canopy's fascia in its dark green, the yellow stripe under it
        self.assertEqual(len(self.faces_of(scene, 0)), 2 * 2 + 4 * 2 + 2 * 2)
        self.assertTrue(self.flat(scene, 0, 2) and self.flat(scene, 0, 3))
        board = [t for t in tris if all(p[3] < .25 and 10 / 16 < p[4] < 14 / 16 for p in t)]
        self.assertEqual(len(board), 4)
        self.assertTrue(all(p[1] > 80 for t in board for p in t))     # by the street's edge of the site
        self.assertEqual(len(scene.brandPOIs), 1)
        self.assertEqual(len(self.build([cell], i=1).brandPOIs), 0)
        self.assertIsNone(self.build([cell], far=True).brandPOIs)

    def test_shop_storeys_are_taller_than_a_flats(self):
        height = self.g.shopHeight
        self.assertEqual(height(self.table({'height': 6}), self.table({'building': 'retail', 'building:levels': '2'}), 2000, 0), 9)
        self.assertEqual(height(self.table({'height': 6}), self.table({'building': 'apartments', 'building:levels': '2'}), 2000, 0), 6)
        self.assertEqual(height(self.table({'height': 6}), self.table({'building': 'retail', 'building:levels': '2',
                                                                       'height': '7'}), 2000, 0), 6)

    def test_plain_roof_stands_on_columns(self):
        roof = {'id': 'roof', 'tags': {'building': 'roof'}, 'rings': [[[100, 100], [120, 100], [120, 108], [100, 108]]]}
        scene = self.build([{'buildings': [roof]}])
        self.assertFalse([m for m in self.materials(scene) if m.startswith('e2rf_wall_')])
        tris = self.corners(scene)
        top = max(p[2] for t in self.corners(scene, 'e2rf_roof') for p in t)
        tops = {round(max(p[2] for p in t), 3) for t in tris if self.normal(t)[2] > .99}
        self.assertIn(round(top - .35, 3), tops)                     # column tops under the slab
        columns = {(round(t[0][0]), round(t[0][1])) for t in tris if max(p[2] for p in t) < top - .3 and min(p[2] for p in t) < top - 3}
        self.assertGreaterEqual(len(columns), 4)

    def test_site_does_not_sign_unrelated_building_or_draw_without_a_street(self):
        site = {'id': 's', 'kind': 'fuel_site', 'tags': {'e2r_brand': 'okko'},
                'rings': [[[100, 100], [180, 100], [180, 180], [100, 180]]]}
        outside = {'id': 'house', 'height': 5, 'rings': [[[190, 190], [200, 190], [200, 200], [190, 200]]]}
        self.assertEqual(self.corners(self.build([{'areas': [site], 'buildings': [outside]}])), [])
        site['tags']['e2r_brand'] = 'unknown'
        self.assertEqual(self.corners(self.build([{'areas': [site], 'buildings': [outside]}])), [])


if __name__ == '__main__':
    unittest.main()
