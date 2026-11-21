"""The building kit (kit.lua): facades assembled from blocks inside the tile generator."""
import math
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

import test_generator


ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / 'mod/lua/ge/extensions/e2r'


def load(test):
    """A generator with the kit module and its generated cell table, as the game requires them."""
    h = test_generator.GeneratorTests()
    lua = h.lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().cells_source = (LUA / 'kit_cells.lua').read_text(encoding='utf8')
    lua.globals().kit_source = (LUA / 'kit.lua').read_text(encoding='utf8')
    lua.execute("package.loaded['ge/extensions/e2r/kit_cells'] = assert(loadstring(cells_source))()")
    lua.execute("kit = assert(loadstring(kit_source))(); package.loaded['ge/extensions/e2r/kit'] = kit")
    h.generator = lua.execute((LUA / 'generator.lua').read_text(encoding='utf8'))
    return h, lua


def block(ident='b1', x=100, y=100, length=60, depth=12, height=27, **tags):
    return {'id': ident, 'height': height, 'tags': {'building': 'apartments', **tags},
            'rings': [[[x, y, 20], [x + length, y, 20], [x + length, y + depth, 20], [x, y + depth, 20]]]}


class KitTests(unittest.TestCase):
    def setUp(self):
        self.h, self.lua = load(self)

    def build(self, buildings, i=0, j=0, **opts):
        road = {'id': 'r', 'width': 8, 'tags': {'highway': 'residential'}, 'points': [[0, 80, 20], [1000, 80, 20]]}
        cells = [{'buildings': buildings, 'roads': [road],
                  'terrain': {'rect': [0, 0, 1000, 500], 'nx': 2, 'ny': 2, 'heights': [20] * 4}}]
        opts.setdefault('kit', True)
        opts.setdefault('country', 'ukraine')
        layers = self.h.build(cells, i, j, maxTrees=0, maxGrass=0, propSpacing=0, **opts)
        return layers[2] if opts.get('far') else layers[1]

    def materials(self, manifest):
        out = {}
        for item, mesh in self.h.meshes(manifest):
            out[mesh.material] = out.get(mesh.material, 0) + len(mesh.faces) // 3
        return out

    def test_block_is_assembled_from_kit_materials(self):
        report = self.lua.table()
        mats = self.materials(self.build([block()], kitReport=report))
        self.assertIn('e2rf_kit_cells', mats)
        self.assertIn('e2rf_kit_trim', mats)
        self.assertTrue(any(m.startswith('e2rf_kw_') for m in mats))
        # the photo facades with their painted windows are gone from this building
        self.assertFalse([m for m in mats if m.startswith(('e2rf_wall_pnl', 'e2rf_wall_brk', 'e2rf_wall_pls', 'e2rf_wall_lgg'))])
        self.assertEqual(report.buildings, 1)
        # a nine-floor block 60 m long stays within a few thousand triangles
        self.assertGreater(report.tris, 800)
        self.assertLess(report.tris, 9000)

    def test_kit_off_keeps_the_photo_walls(self):
        mats = self.materials(self.build([block()], kit=False))
        self.assertFalse([m for m in mats if m.startswith(('e2rf_kw_', 'e2rf_kit_'))])
        self.assertTrue([m for m in mats if m.startswith('e2rf_wall_')])

    def test_houses_sheds_and_churches_keep_their_own_walls(self):
        for tags, height in (({'building': 'house'}, 6), ({'building': 'garages'}, 3), ({'building': 'church'}, 20),
                             ({'building': 'industrial'}, 12), ({'building': 'yes', 'amenity': 'place_of_worship'}, 20)):
            b = block(height=height)
            b['tags'] = tags
            mats = self.materials(self.build([b]))
            self.assertFalse([m for m in mats if m.startswith(('e2rf_kw_', 'e2rf_kit_trim'))], tags)
            # a house takes its region's window and door from the atlas, nothing else
            self.assertEqual('e2rf_kit_cells' in mats, tags == {'building': 'house'}, tags)

    def test_deterministic_and_whole_across_a_tile_edge(self):
        one = self.materials(self.build([block()]))
        two = self.materials(self.build([block()]))
        self.assertEqual(one, two)
        # a block across x = 500: each tile draws its part and nothing beyond its edge
        b = block(x=470)
        left, right = self.build([b], 0, 0), self.build([b], 1, 0)
        for manifest, lo, hi in ((left, 0, 500), (right, 500, 1000)):
            for material in ('e2rf_kit_cells', 'e2rf_kit_trim'):
                xs = [p[0] for tri in self.h.triangles(manifest, material) for p in tri]
                self.assertTrue(xs, material)
                self.assertGreaterEqual(min(xs), lo - 1e-6)
                self.assertLessEqual(max(xs), hi + 1e-6)

    def test_walls_face_out_and_windows_sit_in_reveals(self):
        manifest = self.build([block(start_date='1975')], detail=100)
        # the south wall (y = 100) faces -y: its glass is set back into the building
        ys = set()
        for tri in self.h.triangles(manifest, 'e2rf_kit_cells'):
            if all(abs(p[1] - tri[0][1]) < 1e-6 for p in tri) and tri[0][1] < 105:
                ys.add(round(tri[0][1], 3))
                a, b, c = tri
                # clockwise in the mesh (generator.triangle): the stored order's normal points in
                n = (b[0] - a[0]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[0] - a[0])
                self.assertNotEqual(n, 0)
        self.assertTrue(any(100.05 < y < 100.4 for y in ys), ys)

    def test_far_box_keeps_the_kit_walls_colour(self):
        kit = self.lua.globals().kit
        tags = self.lua.table_from({'building': 'apartments', 'start_date': '1982'})
        options = self.lua.table_from({'kit': True})
        kind = kit.farKind(tags, 30, 600, 5, 'postsoviet', options)
        self.assertTrue(kind.startswith('wall_pnl_'), kind)
        self.assertIsNone(kit.farKind(self.lua.table_from({'building': 'house'}), 30, 600, 5, 'postsoviet', options))
        self.assertIsNone(kit.farKind(tags, 30, 600, 5, 'postsoviet', self.lua.table_from({'kit': False})))
        far = self.materials(self.build([block(start_date='1982', height=30)], far=True))
        self.assertTrue([m for m in far if m.startswith('e2rf_wall_pnl_')], far)
        self.assertFalse([m for m in far if m.startswith(('e2rf_kw_', 'e2rf_kit_'))], far)

    def test_styles_follow_region_year_and_height(self):
        kit = self.lua.globals().kit
        tags = self.lua.table_from
        self.assertEqual(kit.styleOf(tags({'building': 'apartments', 'start_date': '1912'}), 14, 5, 'postsoviet'), 'oldtown')
        self.assertEqual(kit.styleOf(tags({'building': 'apartments', 'start_date': '1952'}), 20, 5, 'postsoviet'), 'stalin')
        self.assertEqual(kit.styleOf(tags({'building': 'apartments', 'start_date': '1982'}), 45, 5, 'postsoviet'), 'panel')
        self.assertEqual(kit.styleOf(tags({'building': 'apartments', 'start_date': '2015'}), 60, 5, 'postsoviet'), 'modern')
        self.assertEqual(kit.styleOf(tags({'building': 'office'}), 30, 5, 'postsoviet'), 'modern')
        seen = {kit.styleOf(tags({'building': 'apartments'}), 12, h, 'british') for h in range(40)}
        self.assertIn('british', seen)
        self.assertNotIn('panel', seen)
        seen = {kit.styleOf(tags({'building': 'apartments'}), 40, h, 'postsoviet') for h in range(60)}
        self.assertEqual(seen, {'panel', 'modern', 'brick'})
        # a block round a court is the old town's, a plain slab is a series'
        court = self.h.table([[[0, 0], [60, 0], [60, 50], [0, 50]], [[10, 10], [50, 10], [50, 40], [10, 40]]])
        slab = self.h.table([[[0, 0], [60, 0], [60, 12], [0, 12]]])
        ell = self.h.table([[[0, 0], [60, 0], [60, 12], [12, 12], [12, 50], [0, 50]]])
        self.assertTrue(kit.irregular(court))
        self.assertTrue(kit.irregular(ell))
        self.assertFalse(kit.irregular(slab))
        seen = {kit.styleOf(tags({'building': 'apartments'}), 30, h, 'postsoviet', court) for h in range(60)}
        self.assertIn('stalin', seen)
        self.assertNotIn('panel', seen)

    def test_every_style_refers_to_built_art(self):
        kit = self.lua.globals().kit
        data = kit.data
        cell_lists = ('W', 'D', 'T', 'K', 'S', 'F', 'ground', 'doors')
        for name, style in kit.styles.items():
            for key in cell_lists:
                for cell in (style[key] or self.lua.table()).values():
                    self.assertIsNotNone(data.cells[cell], f'{name}.{key}: {cell}')
            for key in ('walls', 'plinthWall', 'groundWall'):
                for wall in (style[key] or self.lua.table()).values():
                    self.assertIsNotNone(data.walls[wall], f'{name}.{key}: {wall}')
            self.assertIsNotNone(data.bands[style.cornice[1]], name)
            if style.balcony:
                for wall in style.balcony.parapet.values():
                    self.assertIsNotNone(data.walls[wall], f'{name}.balcony: {wall}')
                for cell in list(style.balcony.glass.values()) + list(style.balcony.door.values()):
                    self.assertIsNotNone(data.cells[cell], f'{name}.balcony: {cell}')
        for band in ('concrete', 'zinc', 'white', 'dark', 'slab_edge', 'coping', 'string_course'):
            self.assertIsNotNone(data.bands[band], band)

    def test_shop_floor_stays_plain_for_the_generators_fronts(self):
        # the kit called directly: a street wall of a building with a mapped shop keeps its
        # ground floor whole (no plinth, no windows), the floors above have their windows
        out = self.lua.execute("""
          local quads, lowest = {}, {}
          local scene = {polygon = function(kind, pts)
            quads[kind] = (quads[kind] or 0) + 1
            for _, p in ipairs(pts) do if kind == 'kit_cells' then lowest[#lowest + 1] = p[3] end end
          end}
          local ring = {{0, 0}, {40, 0}, {40, 12}, {0, 12}}
          local plan = kit.plan({tags = {building = 'apartments', start_date = '1982'}, height = 27, footprint = 480, h = 7,
            block = 'postsoviet', options = {kit = true, detail = 100}, ring = ring, rings = {ring}, shop = true,
            street = function() return true end, ground = function() return 20 end})
          kit.wall(plan, scene, ring[1], ring[2], 40, 0, 19.7, 20, 47, {full = 40, road = true})
          local low = math.huge
          for _, z in ipairs(lowest) do low = math.min(low, z) end
          return plan.name, low, quads.kit_cells or 0
        """)
        self.assertEqual(out[0], 'panel')
        self.assertGreater(out[1], 20 + 1.0 + 2.8)        # nothing of the atlas on the ground floor
        self.assertGreater(out[2], 50)

    def test_every_style_builds_in_every_region(self):
        kit = self.lua.globals().kit
        for country, heights in (('ukraine', (9, 16, 27, 48)), ('united-kingdom', (9, 16, 30)), ('new-york', (9, 16, 40)),
                                 ('germany', (9, 16, 30)), ('zanzibar', (9, 16))):
            for height in heights:
                for n in range(6):
                    report = self.lua.table()
                    self.build([block(ident=f'b{n}', height=height, length=18 + n * 9)], country=country, kitReport=report)
                    self.assertEqual(report.buildings, 1, (country, height, n))
                    self.assertGreater(report.tris, 60)


if __name__ == '__main__':
    unittest.main()
