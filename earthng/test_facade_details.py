"""Facade details (BLD.downpipes, BLD.acUnits): opt-in, on the texture's window grid, deterministic."""
from pathlib import Path
import unittest

import test_generator


class FacadeDetailTests(unittest.TestCase):
    def setUp(self):
        self.h = test_generator.GeneratorTests()
        self.h.setUp()
        self.road = {'id': 'street', 'width': 8, 'tags': {'highway': 'residential'},
                     'points': [[50, 85, 0], [250, 85, 0]]}

    def block(self, material='brick', height=15, ring=None, ident='b1'):
        return {'id': ident, 'height': height,
                'tags': {'building': 'apartments', 'building:material': material, 'height': str(height)},
                'rings': [ring or [[100, 100], [160, 100], [160, 112], [100, 112]]]}

    def build(self, buildings, **opts):
        cells = [{'buildings': buildings, 'roads': [self.road]}]
        return self.h.build(cells, 0, 0, maxTrees=0, maxGrass=0, **opts)

    def tris(self, manifest, material):
        return list(self.h.triangles(manifest, 'e2rf_' + material))

    def wall_pipes(self, manifest):
        """Downpipe triangles: the pipe material under the roof (antennas stand on it)."""
        walls = [p[2] for _, m in self.h.meshes(manifest) if m.material.startswith('e2rf_wall_')
                 for t in self.h.triangles(manifest, m.material) for p in t]
        top = max(walls) if walls else 0
        return [t for t in self.tris(manifest, 'pipe') if min(p[2] for p in t) < top - 1e-6]

    def test_off_by_default_and_roads_unchanged(self):
        off = self.build([self.block()])
        on = self.build([self.block()], experimentalDetail=True)
        self.assertFalse(self.tris(off[1], 'pipe') or self.tris(off[1], 'ac_unit'))
        self.assertTrue(self.tris(on[1], 'pipe'))
        self.assertEqual(self.h.plain(off[0]), self.h.plain(on[0]))
        far = self.build([self.block()], experimentalDetail=True, far=True)
        for manifest in far[:3]:
            if manifest is not None:
                self.assertFalse(self.tris(manifest, 'pipe') or self.tris(manifest, 'ac_unit'))

    def test_downpipes_on_the_outer_corners_of_a_low_brick_block(self):
        scene = self.build([self.block()], experimentalDetail=True)[1]
        pipes = self.wall_pipes(scene)
        # four corners, three boxes each: shaft (4 sides), hopper (4 + bottom), kick-out (4 + top)
        self.assertEqual(len(pipes), 4 * (8 + 10 + 10))
        corners = [(100, 100), (160, 100), (160, 112), (100, 112)]
        for t in pipes:
            for x, y, _ in t:
                self.assertLess(min(abs(x - cx) + abs(y - cy) for cx, cy in corners), 1.2, (x, y))
                # outside the footprint
                self.assertFalse(100 < x < 160 and 100 < y < 112, (x, y))

    def test_no_pipes_on_panel_or_tall_blocks_and_none_in_a_reentrant_corner(self):
        self.assertFalse(self.wall_pipes(self.build([self.block('panel', 27)], experimentalDetail=True)[1]))
        self.assertFalse(self.wall_pipes(self.build([self.block('brick', 24)], experimentalDetail=True)[1]))
        ell = [[100, 100], [160, 100], [160, 112], [130, 112], [130, 140], [100, 140]]
        pipes = self.wall_pipes(self.build([self.block(ring=ell)], experimentalDetail=True)[1])
        self.assertEqual(len(pipes), 5 * 28)
        for t in pipes:
            for x, y, _ in t:
                self.assertGreater(abs(x - 130) + abs(y - 112), 1.2)

    def test_air_conditioners_sit_under_windows_above_the_ground_floor(self):
        scene = self.build([self.block('panel', 21, ring=[[100, 100], [220, 100], [220, 112], [100, 112]])],
                           experimentalDetail=True)[1]
        units = self.tris(scene, 'ac_unit')
        self.assertTrue(units)
        boxes = {}
        for t in units:
            for x, y, z in t:
                if abs(y - 100) < .5:               # the street wall (y = 100), its outside y < 100
                    self.assertLessEqual(y, 100 + 1e-6)
                    boxes.setdefault(round(x - 1.5) // 3, []).append((x, z))
        self.assertTrue(boxes)
        for xs in boxes.values():
            cx = (min(p[0] for p in xs) + max(p[0] for p in xs)) / 2
            self.assertAlmostEqual((cx - 100) % 3, 1.5, places=4)
            self.assertAlmostEqual(max(p[0] for p in xs) - min(p[0] for p in xs), .8, places=4)
        # the wall's datum: its foot is 0.3 m under it (generator: bottom = low - .3, flat ground)
        walls = [p[2] for _, m in self.h.meshes(scene) if m.material.startswith('e2rf_wall_')
                 for t in self.h.triangles(scene, m.material) for p in t]
        base = min(walls) + .3
        zs = [p[2] - base for t in units for p in t]
        # units start on the first floor, under its window sill (.96 m over the floor)
        self.assertGreaterEqual(min(zs), 3 - 1e-6)
        for z in zs:
            self.assertLessEqual(z % 3, .96 + 1e-6)
        # the same every build
        again = self.tris(self.build([self.block('panel', 21, ring=[[100, 100], [220, 100], [220, 112], [100, 112]])],
                                     experimentalDetail=True)[1], 'ac_unit')
        self.assertEqual(sorted(units), sorted(again))

    def test_no_units_on_blank_end_walls_or_loggia_photos(self):
        loggia = self.build([self.block('panel', 40, ring=[[100, 100], [130, 100], [130, 112], [100, 112]])],
                            experimentalDetail=True)[1]
        kinds = {m.material for _, m in self.h.meshes(loggia)}
        if any(k.startswith('e2rf_wall_lgg_') for k in kinds):
            self.assertFalse([t for t in self.tris(loggia, 'ac_unit')])

    def test_ground_floor_grilles_and_dishes(self):
        ring = [[100, 100], [220, 100], [220, 112], [100, 112]]
        off = self.build([self.block('panel', 21, ring=ring)])[1]
        self.assertFalse(self.tris(off, 'railing_dark'))
        scene = self.build([self.block('panel', 21, ring=ring)], experimentalDetail=True)[1]
        walls = [p[2] for _, m in self.h.meshes(scene) if m.material.startswith('e2rf_wall_')
                 for t in self.h.triangles(scene, m.material) for p in t]
        base = min(walls) + .3
        grilles = self.tris(scene, 'railing_dark')
        self.assertTrue(grilles)
        # over ground floor windows only (0.9 .. 2.45 m), 6 cm off the wall, outside the block
        self.assertEqual({round(p[2] - base, 2) for t in grilles for p in t}, {.9, 2.45})
        for t in grilles:
            for x, y, _ in t:
                self.assertFalse(100 < x < 220 and 100 < y < 112)
        # dishes: an octagon both sides (12 triangles) on an arm (10), above the ground floor
        dishes = self.tris(scene, 'dish')
        self.assertTrue(dishes)
        self.assertEqual(len(dishes) % 22, 0)
        self.assertGreater(min(p[2] for t in dishes for p in t) - base, 3)
        # not over a storefront's span: a shop node with a door in the middle of the street wall
        door = {'id': '-1000000000090:0', 'kind': 'door', 'pos': [160, 100, 0], 'tags': {'entrance': 'yes'}}
        poi = {'id': '-1000000000042:0', 'kind': 'poi', 'pos': [160, 102, 0], 'tags': {'shop': 'bakery'}}
        cells = [{'buildings': [self.block('panel', 21, ring=ring)], 'roads': [self.road], 'points': [poi, door]}]
        shop = self.h.build(cells, 0, 0, maxTrees=0, maxGrass=0, experimentalDetail=True, experimentalShopfront=True)[1]
        for t in self.tris(shop, 'railing_dark'):
            for x, y, _ in t:
                if abs(y - 100) < .2:
                    self.assertFalse(156 < x < 164, (x, y))

    def test_balcony_stacks_on_khrushchovkas(self):
        ring = [[100, 100], [220, 100], [220, 112], [100, 112]]
        off = self.build([self.block('brick', 15, ring=ring)])[1]
        self.assertFalse(self.tris(off, 'clad_metal') + self.tris(off, 'clad_tin'))
        scene = self.build([self.block('brick', 15, ring=ring)], experimentalDetail=True)[1]
        sheets = self.tris(scene, 'clad_metal') + self.tris(scene, 'clad_tin')
        self.assertTrue(sheets)
        walls = [p[2] for _, m in self.h.meshes(scene) if m.material.startswith('e2rf_wall_brk')
                 for t in self.h.triangles(scene, m.material) for p in t]
        base = min(walls) + .3
        self.assertGreaterEqual(min(p[2] for t in sheets for p in t) - base, 3)
        # no more than a metre out from the walls
        for t in sheets:
            for x, y, _ in t:
                self.assertTrue(99 - 1e-6 <= x <= 221 + 1e-6 and 99 - 1e-6 <= y <= 113 + 1e-6, (x, y))
        # columns on the street wall (y = 100): 3 m cells, no two side by side
        cols = sorted({int((sum(p[0] for p in t) / 3 - 100) // 3) for t in sheets if max(p[1] for p in t) < 100})
        self.assertTrue(cols)
        self.assertFalse([a for a, b in zip(cols, cols[1:]) if b - a == 1])
        # a five-storey panel block has them too; a nine-storey brick one and a twelve-storey
        # panel one do not
        panel = self.build([self.block('panel', 15, ring=ring)], experimentalDetail=True)[1]
        self.assertTrue(self.tris(panel, 'clad_metal') + self.tris(panel, 'clad_tin'))
        for material, height in (('brick', 27), ('panel', 36)):
            other = self.build([self.block(material, height, ring=ring)], experimentalDetail=True)[1]
            self.assertFalse(self.tris(other, 'wall_off_grey'), (material, height))

    def test_roof_shafts_and_antennas_stay_on_the_roof(self):
        ring = [[100, 100], [160, 100], [160, 112], [100, 112]]
        off = self.build([self.block('panel', 21, ring=ring)])[1]
        on = self.build([self.block('panel', 21, ring=ring)], experimentalDetail=True)[1]
        walls = [p[2] for _, m in self.h.meshes(on) if m.material.startswith('e2rf_wall_')
                 for t in self.h.triangles(on, m.material) for p in t]
        top = max(walls)
        extra = len(self.tris(on, 'parapet')) - len(self.tris(off, 'parapet'))
        self.assertGreater(extra, 0)
        self.assertEqual(extra % 10, 0)            # whole shafts, five faces each
        shafts = [t for t in self.tris(on, 'parapet') if t not in self.tris(off, 'parapet')]
        for t in shafts:
            for x, y, z in t:
                self.assertTrue(100 < x < 160 and 100 < y < 112, (x, y))
                self.assertGreaterEqual(z, top - 1e-6)
        masts = [t for t in self.tris(on, 'pipe') if min(p[2] for p in t) >= top - 1e-6]
        for t in masts:
            for x, y, z in t:
                self.assertTrue(99 < x < 161 and 99 < y < 113, (x, y))
                self.assertLessEqual(z, top + 3.2 + 1e-6)

    def test_address_plate_on_the_wall_facing_its_street(self):
        import fast_style
        named = {'id': 'street', 'width': 8, 'tags': {'highway': 'residential', 'name': 'вулиця Прилужна'},
                 'points': [[50, 85, 0], [250, 85, 0]]}
        other = {'id': 'back', 'width': 8, 'tags': {'highway': 'residential', 'name': 'вулиця Інша'},
                 'points': [[50, 127, 0], [250, 127, 0]]}
        block = self.block('panel', 15)
        block['tags'].update({'addr:housenumber': '4/15', 'addr:street': 'вулиця Прилужна'})

        def plate(roads, **opts):
            out = self.h.build([{'buildings': [block], 'roads': roads}], 0, 0, maxTrees=0, maxGrass=0, **opts)[1]
            return self.tris(out, 'glyphs'), self.tris(out, 'plate')
        self.assertEqual(plate([named, other]), ([], []))
        glyphs, back = plate([named, other], experimentalDetail=True)
        # "4/15" and "вул. Прилужна": 17 letters, two triangles each, on the street wall (y = 100)
        self.assertEqual(len(glyphs), 34)
        self.assertEqual(len(back), 2)
        self.assertEqual({round(p[1], 3) for t in glyphs for p in t}, {99.965})
        # the street it names is behind the block: the plate goes on that side
        moved = dict(named, points=[[50, 127, 0], [250, 127, 0]])
        glyphs, _ = plate([moved], experimentalDetail=True)
        self.assertEqual({round(p[1], 3) for t in glyphs for p in t}, {112.035})
        # no road of that name near: no plate
        self.assertEqual(plate([other], experimentalDetail=True), ([], []))

    def test_glyph_string_is_the_same_in_python_and_lua(self):
        import fast_style
        source = (Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8')
        line = next(l for l in source.splitlines() if l.startswith('BLD.GLYPHS = '))
        lua = self.h.lua.execute('return ' + line[len('BLD.GLYPHS = '):])
        self.assertEqual(lua.decode('utf8') if isinstance(lua, bytes) else lua, fast_style.GLYPHS)
        self.assertLessEqual(len(fast_style.GLYPHS), fast_style.GLYPHS_PER_ROW ** 2)


class RoadCoverTests(unittest.TestCase):
    def setUp(self):
        self.h = test_generator.GeneratorTests()
        self.h.setUp()

    def covers(self, tags, i=0, points=None, **opts):
        road = {'id': 'w1', 'width': 8, 'tags': tags, 'points': points or [[-200, 250, 0], [1200, 250, 0]]}
        out = self.h.build([{'roads': [road]}], i, 0, maxTrees=0, maxGrass=0, **opts)
        result = {}
        for kind in ('manhole', 'drain'):
            result[kind] = [t for m in out[:2] for t in self.h.triangles(m, 'e2rf_' + kind)]
        return result

    def covers_all(self, tags, i=0):
        road = {'id': 'w1', 'width': 8, 'tags': tags, 'points': [[-200, 250, 0], [1200, 250, 0]]}
        out = self.h.build([{'roads': [road]}], i, 0, maxTrees=0, maxGrass=0, experimentalDetail=True)
        return {k: list(self.h.triangles(out[0], 'e2rf_' + k)) for k in ('manhole', 'drain', 'patch')}

    def centres(self, triangles):
        # two triangles a quad: the centre of each quad's four corners
        pts = sorted({(round(p[0], 3), round(p[1], 3)) for t in triangles for p in t})
        return pts

    def test_off_by_default_and_only_on_town_streets(self):
        town = {'highway': 'residential', 'sidewalk': 'both'}
        self.assertEqual(self.covers(town), {'manhole': [], 'drain': []})
        on = self.covers(town, experimentalDetail=True)
        self.assertTrue(on['manhole'] and on['drain'])
        self.assertEqual(self.covers({'highway': 'service', 'sidewalk': 'both'}, experimentalDetail=True),
                         {'manhole': [], 'drain': []})
        self.assertEqual(self.covers({'highway': 'residential', 'sidewalk': 'no'}, experimentalDetail=True),
                         {'manhole': [], 'drain': []})
        self.assertEqual(self.covers({'highway': 'residential', 'sidewalk': 'both', 'bridge': 'yes', 'layer': '1'},
                                     experimentalDetail=True), {'manhole': [], 'drain': []})

    def test_lattice_spacing_sides_and_tile_seams(self):
        town = {'highway': 'residential', 'sidewalk': 'both'}
        tiles = {i: self.covers(town, i=i, experimentalDetail=True) for i in (-1, 0, 1)}

        def area(tris):
            return sum(abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2 for a, b, c in tris)
        holes = [t for i in (-1, 0, 1) for t in tiles[i]['manhole']]
        # each tile draws its part: whole covers add up to whole areas (0.82 m squares)
        self.assertAlmostEqual(area(holes) / (.82 * .82), round(area(holes) / (.82 * .82)), places=3)
        # the one on the seam at x = 0 is split between tiles -1 and 0
        seam = [t for i in (-1, 0) for t in tiles[i]['manhole'] if min(p[0] for p in t) > -1 and max(p[0] for p in t) < 1]
        self.assertAlmostEqual(area(seam), .82 * .82, places=4)
        whole = [t for t in tiles[0]['manhole'] + tiles[1]['manhole'] if max(p[0] for p in t) - min(p[0] for p in t) > .8]
        cx = sorted({round((min(p[0] for p in t) + max(p[0] for p in t)) / 2, 2) for t in whole})
        self.assertEqual({round(b - a, 2) for a, b in zip(cx, cx[1:])}, {55.0})
        # alternating lanes: 0.45 of the half width off the centre line (y = 250)
        ys = {round((min(p[1] for p in t) + max(p[1] for p in t)) / 2, 2) for t in whole}
        self.assertEqual(ys, {round(250 + 1.8, 2), round(250 - 1.8, 2)})
        # patches lie on the carriageway, under the covers and over the paint
        patches = [t for i in (0, 1) for t in self.covers_all(town, i)['patch']]
        self.assertTrue(patches)
        for t in patches:
            for _, y, _ in t:
                self.assertTrue(246 - 1e-6 <= y <= 254 + 1e-6)
        # drains at both curbs, inside the carriageway
        drains = [t for i in (0, 1) for t in tiles[i]['drain']]
        dy = {round((min(p[1] for p in t) + max(p[1] for p in t)) / 2, 2) for t in drains}
        self.assertEqual(dy, {round(250 + 4 - .21 - .03, 2), round(250 - 4 + .21 + .03, 2)})

if __name__ == '__main__':
    unittest.main()
