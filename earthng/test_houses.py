"""Houses of one and two storeys by region (houses.lua, house_art.py): every style is drawn from
kinds and cells that exist, a region's houses are its own, and a planet without the library
dresses its houses as before."""
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

import house_art
import test_generator

ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / 'mod/lua/ge/extensions/e2r'


def load(test=None):
    """A generator with the houses' module, its generated library and the kit's cells, as the
    game requires them."""
    h = test_generator.GeneratorTests()
    lua = h.lua = LuaRuntime(unpack_returned_tuples=True)
    for name in ('kit_cells', 'house_lib', 'kit', 'houses'):
        lua.globals().source = (LUA / f'{name}.lua').read_text(encoding='utf8')
        lua.execute(f"package.loaded['ge/extensions/e2r/{name}'] = assert(loadstring(source, '{name}'))()")
    h.generator = lua.execute((LUA / 'generator.lua').read_text(encoding='utf8'))
    return h, lua


def house(ident, x, y, length=11, depth=8, **tags):
    return {'id': ident, 'tags': {'building': 'house', **tags},
            'rings': [[[x, y, 20], [x + length, y, 20], [x + length, y + depth, 20], [x, y + depth, 20]]]}


def village(n=60, **tags):
    """n houses in rows 30 m apart, off the road."""
    return [house(f'h{k}', 20 + k % 15 * 30, 120 + k // 15 * 40, **tags) for k in range(n)]


class HouseStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h, cls.lua = load()
        cls.houses = cls.lua.eval("package.loaded['ge/extensions/e2r/houses']")

    def build(self, buildings, **opts):
        road = {'id': 'r', 'width': 8, 'tags': {'highway': 'residential'}, 'points': [[0, 60, 20], [1000, 60, 20]]}
        cells = [{'buildings': buildings, 'roads': [road],
                  'terrain': {'rect': [0, 0, 1000, 500], 'nx': 2, 'ny': 2, 'heights': [20] * 4}}]
        opts.setdefault('houseArt', True)
        opts.setdefault('ownArt', True)
        opts.setdefault('kit', False)
        opts.setdefault('country', 'ukraine')
        layers = self.h.build(cells, 0, 0, maxTrees=0, maxGrass=0, propSpacing=0, **opts)
        return layers[2] if opts.get('far') else layers[1]

    def materials(self, manifest):
        out = {}
        for _, mesh in self.h.meshes(manifest):
            out[mesh.material] = out.get(mesh.material, 0) + len(mesh.faces) // 3
        return out

    def defined(self):
        import fast_style
        return {'e2rf_' + kind for kind in fast_style.KINDS}

    def words(self, spec, prefix=''):
        return {prefix + name for name, _ in (pair.split() for pair in self._pairs(spec))}

    @staticmethod
    def _pairs(spec):
        parts = spec.split()
        return [' '.join(parts[k:k + 2]) for k in range(0, len(parts), 2)]

    # --- the tables ---------------------------------------------------------------------------
    def test_every_style_is_drawn_from_kinds_and_cells_that_exist(self):
        import fast_style
        import own_art
        if not own_art.ready():
            self.skipTest('the own surfaces are not in this checkout')
        kinds = set(fast_style.KINDS) | set(house_art.wall_kinds()) | set(house_art.roof_kinds())
        cells = set(house_art.cell_names()) | set(self.lua.eval("package.loaded['ge/extensions/e2r/kit_cells'].cells").keys())
        for name, style in self.houses.styles.items():
            for kind in self.words(style.walls, 'hw_') | self.words(style.roofs, 'roof_'):
                self.assertIn(kind, kinds, name)
            if style.flat:
                self.assertIn('roof_' + style.flat, kinds, name)
            for plinth in self.words(style.plinth or 'plinth 1'):
                self.assertTrue(plinth == 'none' or plinth.lstrip('=') in kinds, (name, plinth))
            for key in ('win', 'door'):
                named = self.words(style[key])
                self.assertFalse(named - cells, (name, key))
                # a planet without the kit's art still has a window and a door for every style
                self.assertTrue(named & set(house_art.cell_names()), (name, key))
            self.assertLessEqual(style.pitch[1], style.pitch[2], name)
            self.assertTrue(self.words(style.shapes) <= {'gabled', 'hipped', 'half-hipped', 'flat'}, name)

    def test_every_region_names_styles_that_exist(self):
        styles = set(self.houses.styles.keys())
        for table in (self.houses.regions, self.houses.countries):
            for place, lists in table.items():
                self.assertIn('any', lists, place)
                for zone, spec in lists.items():
                    if zone in ('any', 'arid', 'tropic', 'med', 'cold'):
                        self.assertFalse(self.words(spec) - styles, (place, zone))

    def test_the_library_file_holds_every_cell_and_every_kind(self):
        lib = self.lua.eval("package.loaded['ge/extensions/e2r/house_lib']")
        self.assertEqual(set(lib.cells.keys()), set(house_art.cell_names()))
        self.assertEqual(set(lib.walls.keys()), set(house_art.wall_kinds()))
        self.assertEqual(set(lib.roofs.keys()), set(house_art.roof_kinds()))
        for cell in lib.cells.values():
            self.assertIn(cell[7], (2, 3))

    def test_a_named_material_picks_a_wall_of_that_make(self):
        make, styles = self.houses.make, self.houses.styles
        self.assertEqual(make('hw_h_mudbrick'), 'earth')
        self.assertEqual(make('hw_h_brick_dutch'), 'brick')
        self.assertEqual(make('hw_h_jerusalem'), 'stone')
        self.assertEqual(make('hw_h_batten_red'), 'wood')
        self.assertEqual(make('hw_h_koroid_peach'), 'plaster')
        for n in range(30):
            self.assertEqual(make(self.houses.wall(styles.uk_brick, 'brick', n)), 'brick')
            self.assertEqual(make(self.houses.wall(styles.nd_wood, 'wood', n)), 'wood')
        # a make the style has no wall of is the generator's to answer
        self.assertIsNone(self.houses.wall(styles.nd_wood, 'brick', 1))

    def test_a_patch_of_the_map_is_mostly_one_style(self):
        region = self.houses.region('british', 'great-britain')
        same = 0
        picks = [self.houses.pick(region, None, 1000 + n, 4000 + n % 5, 9000 + n // 5).name for n in range(90)]
        top = max(set(picks), key=picks.count)
        same = picks.count(top)
        self.assertGreater(same, 55, picks)                 # two of three by the patch, the rest dealt
        self.assertGreater(len(set(picks)), 1)
        far = {self.houses.pick(region, None, 7, 4000 + 400 * n, 9000).name for n in range(40)}
        self.assertGreater(len(far), 2)                     # other patches, other styles

    def test_the_climate_changes_the_list(self):
        region = self.houses.region('north-america', 'us-california')
        desert = self.lua.table_from({'arid': True, 'group': 'desert'})
        cold = self.lua.table_from({'group': 'boreal'})
        dry = [self.houses.pick(region, desert, n, 0, 0).name for n in range(300)]
        north = [self.houses.pick(region, cold, n, 0, 0).name for n in range(300)]
        self.assertIn('us_adobe', dry)
        self.assertNotIn('us_adobe', north)
        self.assertIn('us_cabin', north)

    def test_a_country_has_its_own_lists(self):
        same = self.lua.eval('function(a, b) return a == b end')
        self.assertTrue(same(self.houses.region('east-asia', 'japan'), self.houses.countries.japan))
        self.assertTrue(same(self.houses.region('postsoviet', 'ukraine'), self.houses.regions.postsoviet))
        self.assertTrue(same(self.houses.region('western', 'germany-berlin'), self.houses.countries.germany))
        self.assertIsNone(self.houses.region('general', 'atlantis'))

    # --- the generator ------------------------------------------------------------------------
    def test_without_the_library_a_house_is_dressed_as_before(self):
        mats = self.materials(self.build(village(30), houseArt=False, look={'block': 'east-asia'}, country='japan'))
        self.assertFalse([m for m in mats if '_h_' in m or 'house_cells' in m], sorted(mats))

    def test_a_region_draws_its_own_houses(self):
        seen = {}
        for country, block in (('ukraine', 'postsoviet'), ('japan', 'east-asia'), ('great-britain', 'british'),
                               ('iran', 'middle-east'), ('tanzania', 'africa'), ('us', 'north-america')):
            mats = self.materials(self.build(village(60), look={'block': block}, country=country))
            seen[country] = mats
            self.assertTrue([m for m in mats if m.startswith('e2rf_house_cells')], (country, sorted(mats)))
            # every material drawn is one the planet defines ('no plinth' was once a material
            # e2rf_none: `a and false or b` is b)
            self.assertFalse({m for m in mats if not m.startswith('e2rf_col_')} - self.defined(), country)
        walls = {c: {m for m in mats if m.startswith('e2rf_hw_')} for c, mats in seen.items()}
        roofs = {c: {m for m in mats if m.startswith('e2rf_roof_')} for c, mats in seen.items()}
        self.assertTrue([m for m in walls['japan'] if '_jps_' in m or 'yakisugi' in m], walls['japan'])
        self.assertTrue([m for m in roofs['japan'] if 'kawara' in m], roofs['japan'])
        self.assertTrue([m for m in roofs['great-britain'] if m == 'e2rf_roof_slate'], roofs['great-britain'])
        self.assertTrue([m for m in roofs['iran'] if '_flat_' in m], roofs['iran'])
        self.assertTrue([m for m in roofs['tanzania'] if 'corr' in m or m in ('e2rf_roof_tin', 'e2rf_roof_zinc')], roofs['tanzania'])
        self.assertTrue([m for m in walls['us'] if 'vinyl' in m or 'clap' in m or 'brick_ranch' in m], walls['us'])
        # no region is Ukraine in another paint: at most a few walls in common
        for country in ('japan', 'iran', 'tanzania', 'us'):
            self.assertLess(len(walls[country] & walls['ukraine']), 4, (country, walls[country] & walls['ukraine']))
        # a hot country's house has no brick chimney
        self.assertNotIn('e2rf_chimney', seen['iran'])
        self.assertNotIn('e2rf_chimney', seen['tanzania'])
        self.assertIn('e2rf_chimney', seen['ukraine'])

    def test_a_flat_roof_lies_inside_its_parapet(self):
        manifest = self.build(village(40), look={'block': 'middle-east'}, country='iran')
        tops = {}
        for kind in ('e2rf_roof_h_flat_grey', 'e2rf_roof_h_flat_mud'):
            for tri in self.h.triangles(manifest, kind):
                for p in tri:
                    tops[round(p[2], 2)] = True
        self.assertTrue(tops)
        # a floor is 3.1 m: every roof is under its walls' top (23.1 or 26.2) by its rim
        for z in tops:
            under = min(top - z for top in (23.1, 26.2) if top - z > 0)
            self.assertTrue(.14 <= under <= .91, z)

    def test_upper_floors_follow_the_region(self):
        def two_storey(country, block):
            manifest = self.build(village(60), look={'block': block}, country=country)
            high = set()
            for item, mesh in self.h.meshes(manifest):
                if mesh.material.startswith('e2rf_hw_'):
                    for k in range(1, len(mesh.verts) + 1):
                        p = mesh.verts[k]
                        if p.z + item.pos[3] > 25.5:
                            high.add((round((p.x + item.pos[1] - 20) / 30), round((p.y + item.pos[2] - 120) / 40)))
            return len(high)
        self.assertGreater(two_storey('great-britain', 'british'), 35)
        self.assertLess(two_storey('tanzania', 'africa'), 15)

    def test_a_far_box_keeps_the_near_house_wall(self):
        near = self.materials(self.build(village(40), look={'block': 'nordic'}, country='sweden'))
        far = self.materials(self.build(village(40), look={'block': 'nordic'}, country='sweden', far=True))
        self.assertEqual({m for m in near if m.startswith('e2rf_hw_')}, {m for m in far if m.startswith('e2rf_hw_')})

    def test_a_named_material_is_kept(self):
        mats = self.materials(self.build(village(30, **{'building:material': 'brick'}), look={'block': 'british'}, country='great-britain'))
        walls = {m for m in mats if m.startswith('e2rf_hw_')}
        self.assertTrue(walls)
        self.assertTrue(all(self.houses.make(m[5:]) == 'brick' for m in walls), walls)

    def test_an_outbuilding_is_built_of_what_the_houses_are(self):
        def garages(country, block):
            sheds = [{'id': f'g{k}', 'tags': {'building': 'garage'},
                      'rings': [[[20 + k * 12, 120, 20], [26 + k * 12, 120, 20], [26 + k * 12, 124, 20], [20 + k * 12, 124, 20]]]}
                     for k in range(40)]
            return self.materials(self.build(sheds, look={'block': block}, country=country))
        japan, ukraine = garages('japan', 'east-asia'), garages('ukraine', 'postsoviet')
        self.assertTrue([m for m in japan if '_jps_' in m or 'yakisugi' in m], sorted(japan))
        self.assertFalse([m for m in japan if m.startswith('e2rf_clad_o_')], sorted(japan))
        # the post-Soviet yard keeps its own garages
        self.assertTrue([m for m in ukraine if m.startswith('e2rf_clad_o_')], sorted(ukraine))
        self.assertFalse({m for m in japan if not m.startswith('e2rf_col_')} - self.defined())

    def test_windows_are_their_own_size(self):
        # Japan's slit window is half a metre high and its wide one 1.8 m across: neither is the
        # 1.15 x 1.5 m every house's window was
        manifest = self.build(village(60), look={'block': 'east-asia'}, country='japan')
        sizes = set()
        for kind in ('e2rf_house_cells', 'e2rf_house_cells2'):
            for tri in self.h.triangles(manifest, kind):
                zs = [p[2] for p in tri]
                sizes.add(round(max(zs) - min(zs), 1))
        self.assertGreater(len(sizes), 3, sizes)


if __name__ == '__main__':
    unittest.main()
