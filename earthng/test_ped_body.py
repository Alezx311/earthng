"""The physical pedestrian (ped_body.py) and the blood stains (blood_art.py): what the game is given."""
import io
import json
import unittest

import numpy as np
from PIL import Image

import blood_art
import ped_body


class PedBodyTests(unittest.TestCase):
    def test_the_body_is_a_persons_weight_shared_as_a_persons(self):
        nodes = ped_body.skeleton()
        part = ped_body.jbeam(nodes, 1500)[ped_body.MODEL]
        weights, name = {}, None
        for row in part['nodes'][2:]:
            if isinstance(row, dict):
                name = row
            else:
                weights[row[0]] = name['nodeWeight']
        self.assertEqual(set(weights), set(nodes))
        self.assertAlmostEqual(sum(weights.values()), ped_body.MASS, delta=.2)
        trunk = sum(weights[n] for n in ('pl', 'pr', 'pf', 'pb', 'cl', 'cr', 'cf', 'cb'))
        self.assertGreater(trunk, ped_body.MASS * .45)          # the trunk: half of a person
        self.assertLess(weights['wl'] + weights['fl'] + weights['flx'], 2)   # a forearm and hand

    def test_tissue_joins_only_nodes_that_no_bone_or_lock_joins_and_every_beam_names_nodes(self):
        nodes = ped_body.skeleton()
        pair = lambda a, b: tuple(sorted((a, b)))
        stiff = {pair(*b) for b in ped_body.BONES} | {pair(*b) for b in ped_body.LOCKS}
        tissue = [pair(*t[0]) for t in ped_body.TISSUE]
        self.assertEqual(len(set(tissue)), len(tissue))
        self.assertFalse(stiff & set(tissue))       # the game drops a second beam between two nodes
        for a, b in stiff | set(tissue):
            self.assertIn(a, nodes)
            self.assertIn(b, nodes)
        # every joint has its tissue: knees, hips, ankles, shoulders, elbows, the neck
        for t in 'lr':
            for a, b in (('q', 's'), ('s', 'o')):
                self.assertIn(pair(a + t, b + t), tissue)
        part = ped_body.jbeam(nodes, 1500)[ped_body.MODEL]
        bounded = [row for row in part['beams'] if isinstance(row, dict) and row.get('beamType') == '|BOUNDED']
        self.assertEqual(len(bounded), len(tissue))
        for row in bounded:
            self.assertGreater(row['beamDamp'], 2 * (row['beamSpring'] * 1.5) ** .5)   # more than critical: no swing

    def test_collision_triangles_face_out_of_their_solid(self):
        nodes = ped_body.skeleton()
        tris = ped_body.collision_triangles(nodes)
        self.assertGreater(len(tris), 40)
        trunk = ['pf', 'pl', 'pb', 'pr', 'cf', 'cl', 'cb', 'cr', 'n']
        mid = np.mean([nodes[n] for n in trunk], axis=0)
        for a, b, c in tris:
            for n in (a, b, c):
                self.assertIn(n, nodes)
            if all(n in trunk for n in (a, b, c)):
                pa, pb, pc = (np.array(nodes[n]) for n in (a, b, c))
                normal = np.cross(pb - pa, pc - pa)
                self.assertGreaterEqual(normal @ ((pa + pb + pc) / 3 - mid), 0)

    def test_every_flexbody_has_three_nodes_off_one_line(self):
        nodes = ped_body.skeleton()
        for part, names in ped_body.part_nodes().items():
            pts = np.array([nodes[n] for n in names])
            spread = np.linalg.svd(pts - pts.mean(0), compute_uv=False)
            self.assertGreater(spread[1], .02, part)          # not on a line


class BloodArtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = blood_art.files()
        cls.listed = json.loads(cls.files['blood.json'])['stains']

    def test_every_kind_the_game_asks_for_is_there_with_its_picture_and_its_quad(self):
        kinds = {s['kind'] for s in self.listed}
        self.assertEqual(kinds, {'impact', 'spray', 'pool', 'smear', 'drops', 'run'})   # world.lua BLOOD.hitArt
        for s in self.listed:
            self.assertIn(s['texture'].rsplit('/', 1)[1], self.files)
            self.assertIn(s['shape'] + '.dae', self.files)
            self.assertTrue(s['texture'].startswith('/levels/e2r_world/art/people/'))
            self.assertTrue(0 < s['box'][0] <= 1 and 0 < s['box'][1] <= 1)

    def test_a_stain_is_blood_with_a_clear_margin_and_a_soft_edge(self):
        for s in self.listed:
            im = np.asarray(Image.open(io.BytesIO(self.files[s['texture'].rsplit('/', 1)[1]])), dtype=float) / 255
            alpha = im[..., 3]
            self.assertEqual(float(alpha[0].max() + alpha[-1].max() + alpha[:, 0].max() + alpha[:, -1].max()), 0, s['name'])
            cover = (alpha > .5).mean()
            self.assertTrue(.004 < cover < .6, (s['name'], cover))
            soft = ((alpha > .05) & (alpha < .5)).mean()
            self.assertGreater(soft, cover * .02, s['name'])   # not a hard cut
            body = im[alpha > .5]
            self.assertGreater(body[:, 0].mean(), 4 * body[:, 1].mean())   # red

    def test_thrown_and_dragged_stains_run_along_x(self):
        for s in self.listed:
            if s['kind'] in ('spray', 'smear', 'run'):
                self.assertGreater(s['box'][0], s['box'][1] * 1.15, s['name'])

    def test_the_atlas_holds_each_stain_in_its_own_square(self):
        opacity = np.asarray(Image.open(io.BytesIO(self.files['blood_o.data.png'])), dtype=float) / 255
        colour = Image.open(io.BytesIO(self.files['blood.color.png']))
        self.assertEqual(colour.size, (opacity.shape[1], opacity.shape[0]))
        cols, rows = blood_art.ATLAS
        self.assertLessEqual(len(self.listed), cols * rows)
        for k, s in enumerate(self.listed):
            dae = self.files[s['shape'] + '.dae']
            uv = [float(v) for v in dae.split('stain-ua" count="12">')[1].split('<')[0].split()]
            u, v = uv[0::2], uv[1::2]
            self.assertAlmostEqual(min(u), k % cols / cols)
            self.assertAlmostEqual(max(u), (k % cols + 1) / cols)
            self.assertAlmostEqual(max(v), 1 - (k // cols) / rows)
            cell = opacity[k // cols * blood_art.CELL:(k // cols + 1) * blood_art.CELL,
                           k % cols * blood_art.CELL:(k % cols + 1) * blood_art.CELL]
            self.assertGreater((cell > .25).mean(), .003)      # cut at alphaRef 64, something is left


if __name__ == '__main__':
    unittest.main()
