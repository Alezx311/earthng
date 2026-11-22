"""Outbuildings (generator.lua BLD.small): garages, sheds, huts, kiosks and greenhouses drawn from
EarthNG's own surfaces (own_art.py), each use with its walls, its roof and the shape of it."""
import unittest

import test_kit


def small(ident, use, x=100, y=100, length=6, depth=4, height=None, **tags):
    b = {'id': ident, 'tags': {'building': use, **tags},
         'rings': [[[x, y, 20], [x + length, y, 20], [x + length, y + depth, 20], [x, y + depth, 20]]]}
    if height:
        b['height'] = height
    return b


class OutbuildingTests(unittest.TestCase):
    def setUp(self):
        self.h, self.lua = test_kit.load(self)

    def build(self, buildings, **opts):
        road = {'id': 'r', 'width': 8, 'tags': {'highway': 'residential'}, 'points': [[0, 80, 20], [1000, 80, 20]]}
        cells = [{'buildings': buildings, 'roads': [road],
                  'terrain': {'rect': [0, 0, 1000, 500], 'nx': 2, 'ny': 2, 'heights': [20] * 4}}]
        opts.setdefault('ownArt', True)
        opts.setdefault('country', 'ukraine')
        layers = self.h.build(cells, 0, 0, maxTrees=0, maxGrass=0, propSpacing=0, **opts)
        return layers[2] if opts.get('far') else layers[1]

    def materials(self, manifest):
        out = {}
        for _, mesh in self.h.meshes(manifest):
            out[mesh.material] = out.get(mesh.material, 0) + len(mesh.faces) // 3
        return out

    def test_without_the_own_surfaces_a_garage_is_drawn_as_before(self):
        mats = self.materials(self.build([small('g1', 'garage')], ownArt=False))
        self.assertFalse([m for m in mats if '_o_' in m or m.startswith('e2rf_door_g_')])
        self.assertIn('e2rf_plinth', mats)

    def test_each_use_draws_from_its_own_walls_and_roofs(self):
        walls, roofs, shapes = {}, {}, {}
        for use in ('garage', 'shed', 'hut', 'kiosk', 'greenhouse', 'barn', 'toilets'):
            for n in range(40):
                mats = self.materials(self.build([small(f'{use}{n}', use, length=12 if use == 'barn' else 6,
                                                        depth=7 if use == 'barn' else 4)]))
                wall = sorted(m for m in mats if m.startswith(('e2rf_clad_o_', 'e2rf_clad_tin')))
                roof = sorted(m for m in mats if m.startswith('e2rf_roof_o_'))
                self.assertTrue(wall, (use, n, sorted(mats)))
                self.assertEqual(len(roof), 1, (use, n, sorted(mats)))
                walls.setdefault(use, set()).update(wall)
                roofs.setdefault(use, set()).update(roof)
                # no house's tiled gable and no plain flat roof over an outbuilding
                self.assertFalse([m for m in mats if m in ('e2rf_roof', 'e2rf_roof_tile', 'e2rf_roof_sheet')], (use, n))
        self.assertGreaterEqual(len(walls['garage']), 5)
        self.assertGreaterEqual(len(walls['shed']), 4)
        self.assertGreaterEqual(len(roofs['shed']), 3)
        self.assertEqual(walls['greenhouse'], {'e2rf_clad_o_poly'})
        self.assertEqual(roofs['greenhouse'], {'e2rf_roof_o_poly'})
        self.assertTrue(all(w.startswith('e2rf_clad_o_st_') for w in walls['kiosk']), walls['kiosk'])
        self.assertIn('e2rf_clad_o_log', walls['hut'])

    def test_a_garage_roof_is_flat_or_a_lean_to_and_a_barn_has_a_low_gable(self):
        rises = []
        for n in range(30):
            manifest = self.build([small(f'g{n}', 'garage')])
            roof = [m for m in self.materials(manifest) if m.startswith('e2rf_roof_o_')][0]
            zs = [p[2] for tri in self.h.triangles(manifest, roof) for p in tri]
            # the walls' top is 2.7 m over the ground (BLD.low); the roof rises from it across 4 m
            self.assertAlmostEqual(min(zs), 22.7, delta=.02)
            rises.append(max(zs) - min(zs))
        self.assertTrue(all(.1 <= r <= 1.5 for r in rises), rises)
        self.assertTrue(any(r < .2 for r in rises))          # roofing felt with a hand of fall
        self.assertTrue(any(r > .45 for r in rises))         # a lean-to
        manifest = self.build([small('b1', 'barn', length=14, depth=8)])
        roof = [m for m in self.materials(manifest) if m.startswith('e2rf_roof_o_')][0]
        zs = [p[2] for tri in self.h.triangles(manifest, roof) for p in tri]
        rise = max(zs) - 26                                   # a barn's walls are 6 m
        self.assertTrue(.9 < rise < 2.1, rise)                # 20 degrees over 4 m, not a house's 28-38
        # a cowshed 90 m long has its gable too (a house's rule would leave it a flat roof)
        manifest = self.build([small('c1', 'cowshed', length=90, depth=18, height=7)])
        roof = [m for m in self.materials(manifest) if m.startswith('e2rf_roof_o_')][0]
        zs = [p[2] for tri in self.h.triangles(manifest, roof) for p in tri]
        self.assertGreater(max(zs) - 27, 2.5)                 # 20 degrees over 9 m

    def test_a_row_of_garages_has_doors_of_several_paints(self):
        manifest = self.build([small('row', 'garages', length=31, depth=6)])
        doors = {m: n for m, n in self.materials(manifest).items() if m.startswith('e2rf_door_')}
        self.assertGreaterEqual(len(doors), 3, doors)
        self.assertEqual(sum(doors.values()), 2 * 2 * 10)      # ten bays on either long wall, a quad each

    def test_with_the_atlas_of_doors_each_garage_door_is_a_whole_cell_of_it(self):
        manifest = self.build([small('row', 'garages', length=31, depth=6)], ownCells=True)
        mats = self.materials(manifest)
        self.assertEqual(mats.get('e2rf_door_ob'), 2 * 2 * 10)
        self.assertFalse([m for m in mats if m.startswith('e2rf_door_') and m != 'e2rf_door_ob'])
        cells = set()
        corners = list(self.h.uv_corners(manifest, 'e2rf_door_ob'))
        for k in range(0, len(corners), 3):
            us = [c[3] for c in corners[k:k + 3]]
            vs = [c[4] for c in corners[k:k + 3]]
            col, row = int(min(us) * 4), int(min(vs) * 2)
            # inside one cell, off its gutter
            self.assertGreater(min(us), col / 4 + .002)
            self.assertLess(max(us), (col + 1) / 4 - .002)
            self.assertLess(max(vs), (row + 1) / 2 - .004)
            cells.add((col, row))
        self.assertGreaterEqual(len(cells), 4)                 # several paints in one row
        # a shed's door is the left leaf of the last cell, a barn's gate the cell before it
        shed = self.materials(self.build([small('s9', 'shed')], ownCells=True))
        self.assertEqual(shed.get('e2rf_door_ob'), 2)
        barn = self.materials(self.build([small('b9', 'barn', length=14, depth=8)], ownCells=True))
        self.assertEqual(barn.get('e2rf_door_ob'), 2)

    def test_a_shed_has_a_board_door_and_a_kiosk_its_counter(self):
        shed = self.materials(self.build([small('s1', 'shed')]))
        self.assertGreaterEqual(shed.get('e2rf_gable', 0), 8)   # the door and its frame
        kiosk = self.materials(self.build([small('k1', 'kiosk', length=4, depth=3)]))
        self.assertIn('e2rf_win_pvc', kiosk)

    def test_mapped_material_and_roof_shape_are_kept(self):
        mats = self.materials(self.build([small('g2', 'garage', **{'building:material': 'wood'})]))
        self.assertIn('e2rf_clad_o_boards', mats)
        tagged = self.build([small('s2', 'shed', **{'roof:shape': 'gabled', 'roof:height': '2'})])
        roof = [m for m in self.materials(tagged) if m.startswith('e2rf_roof_o_')]
        self.assertEqual(len(roof), 1)
        zs = [p[2] for tri in self.h.triangles(tagged, roof[0]) for p in tri]
        self.assertAlmostEqual(max(zs) - 22.4, 2, delta=.05)   # the mapped ridge, over a shed's 2.4 m walls

    def test_small_unnamed_buildings_are_sheds_and_houses_take_the_own_walls(self):
        mats = self.materials(self.build([small('y1', 'yes', length=5, depth=4)]))
        self.assertTrue([m for m in mats if m.startswith(('e2rf_clad_o_', 'e2rf_clad_tin'))], sorted(mats))
        seen = set()
        for n in range(160):
            mats = self.materials(self.build([small(f'h{n}', 'house', length=10, depth=8)]))
            seen.update(m for m in mats if m.startswith('e2rf_hw_'))
        self.assertTrue({'e2rf_hw_limewash', 'e2rf_hw_log'} & seen, sorted(seen))
        self.assertTrue([m for m in seen if m.startswith('e2rf_hw_bd_')], sorted(seen))

    def test_a_far_box_keeps_the_outbuildings_wall(self):
        near = self.materials(self.build([small('g3', 'garage')]))
        far = self.materials(self.build([small('g3', 'garage')], far=True))
        wall = [m for m in near if m.startswith('e2rf_clad_o_')]
        self.assertTrue(wall)
        self.assertIn(wall[0], far)


if __name__ == '__main__':
    unittest.main()
