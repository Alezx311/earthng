"""The cook of the fal models (earthng/traffic_art.py): a car's paint as a mask, a person's poses
from a rig, the far shape, the turn to the front before rigging. No fal call is made."""
import io
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np
from PIL import Image

import fal_mesh
import traffic_art as ta


def glb(doc, blob):
    text = json.dumps(doc).encode()
    text += b' ' * (-len(text) % 4)
    blob += bytes(-len(blob) % 4)
    return (struct.pack('<4sII', b'glTF', 2, 28 + len(text) + len(blob)) + struct.pack('<II', len(text), 0x4E4F534A) + text
            + struct.pack('<II', len(blob), 0x004E4942) + blob)


def packed(arrays):
    """Buffer views and accessors of numpy arrays, one after another."""
    kinds = {1: 'SCALAR', 2: 'VEC2', 3: 'VEC3', 4: 'VEC4', 16: 'MAT4'}
    codes = {'<f4': 5126, '<u4': 5125, '<u2': 5123, '|u1': 5121}
    views, accessors, blob = [], [], b''
    for a in arrays:
        a = np.ascontiguousarray(a)
        width = 1 if a.ndim == 1 else a.shape[1]
        views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': a.nbytes})
        acc = {'bufferView': len(views) - 1, 'componentType': codes[a.dtype.str], 'count': len(a), 'type': kinds[width]}
        if width == 3 and a.dtype.kind == 'f':
            acc.update(min=a.min(0).tolist(), max=a.max(0).tolist())
        accessors.append(acc)
        blob += a.tobytes() + bytes(-a.nbytes % 4)
    return views, accessors, blob


def picture(colour=(200, 60, 60)):
    out = io.BytesIO()
    Image.new('RGB', (8, 8), colour).save(out, format='PNG')
    return out.getvalue()


def figure_glb(path, turn=0.):
    """A standing figure of boxes facing glTF +z turned by `turn` about y: a tall body 0.5 wide
    (x) and 0.2 deep, and two feet that reach 0.15 out in front."""
    def box(x0, x1, y0, y1, z0, z1):
        c = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], dtype=float)
        f = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4],
                      [1, 5, 7], [1, 7, 3]])
        return c, f
    parts = [box(-.25, .25, .14, 1.7, -.1, .1), box(-.25, .25, .1, .14, -.1, .1), box(-.2, -.05, 0, .1, -.1, .25),
             box(.05, .2, 0, .1, -.1, .25)]
    pos = np.concatenate([p for p, _ in parts])
    faces = np.concatenate([f + 8 * k for k, (_, f) in enumerate(parts)])
    c, s = math.cos(turn), math.sin(turn)
    pos = pos @ np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]).T
    nrm = pos / np.maximum(np.linalg.norm(pos, axis=1, keepdims=True), 1e-9)
    uv = np.tile([[.5, .5]], (len(pos), 1))
    image = picture()
    views, accessors, blob = packed([pos.astype('<f4'), nrm.astype('<f4'), uv.astype('<f4'), faces.astype('<u4').ravel()])
    views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(image)})
    blob += image
    doc = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
           'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2}, 'indices': 3, 'material': 0}]}],
           'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}], 'textures': [{'source': 0}],
           'images': [{'bufferView': 4, 'mimeType': 'image/png'}], 'buffers': [{'byteLength': len(blob)}],
           'bufferViews': views, 'accessors': accessors}
    Path(path).write_bytes(glb(doc, blob))


def arm_glb(path):
    """A strip along glTF +y on two bones, root at the origin and elbow at y = 1; the clip turns the
    elbow a quarter about z over one second."""
    pos = np.array([[0, 0, 0], [.1, 0, 0], [0, 1, 0], [.1, 1, 0], [0, 2, 0], [.1, 2, 0]], dtype='<f4')
    nrm = np.tile([[0, 0, 1]], (6, 1)).astype('<f4')
    uv = np.tile([[.5, .5]], (6, 1)).astype('<f4')
    faces = np.array([0, 1, 3, 0, 3, 2, 2, 3, 5, 2, 5, 4], dtype='<u4')
    joints = np.array([[0, 0, 0, 0]] * 2 + [[1, 0, 0, 0]] * 4, dtype='|u1')
    weights = np.tile([[1, 0, 0, 0]], (6, 1)).astype('<f4')
    inverse = np.stack([np.eye(4), np.eye(4)])
    inverse[1][1, 3] = -1                     # the elbow's bind place is (0, 1, 0)
    inverse = inverse.transpose(0, 2, 1).reshape(2, 16).astype('<f4')
    times = np.array([0, 1], dtype='<f4')
    quarter = math.sin(math.pi / 4)
    turns = np.array([[0, 0, 0, 1], [0, 0, quarter, quarter]], dtype='<f4')
    image = picture()
    views, accessors, blob = packed([pos, nrm, uv, faces, joints, weights, inverse, times, turns])
    views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(image)})
    blob += image
    doc = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [2, 0]}],
           'nodes': [{'name': 'Root', 'children': [1]}, {'name': 'Elbow', 'translation': [0, 1, 0]}, {'name': 'body', 'mesh': 0, 'skin': 0}],
           'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2, 'JOINTS_0': 4, 'WEIGHTS_0': 5},
                                       'indices': 3, 'material': 0}]}],
           'skins': [{'joints': [0, 1], 'inverseBindMatrices': 6}],
           'animations': [{'samplers': [{'input': 7, 'output': 8, 'interpolation': 'LINEAR'}],
                           'channels': [{'sampler': 0, 'target': {'node': 1, 'path': 'rotation'}}]}],
           'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}], 'textures': [{'source': 0}],
           'images': [{'bufferView': 9, 'mimeType': 'image/png'}], 'buffers': [{'byteLength': len(blob)}],
           'bufferViews': views, 'accessors': accessors}
    Path(path).write_bytes(glb(doc, blob))


class TrafficArtTests(unittest.TestCase):
    def test_the_green_paint_becomes_a_mask_and_its_shading_stays_grey(self):
        px = np.zeros((64, 64, 3), dtype=np.uint8)
        px[:, :32] = (40, 190, 60)        # paint, lit
        px[:16, :32] = (20, 95, 30)       # paint in shade
        px[:, 32:48] = (200, 20, 20)      # a tail lamp
        px[:, 48:] = (15, 15, 18)         # glass
        base, palette, share = ta.paint_maps(Image.fromarray(px))
        base, palette = np.asarray(base.resize((64, 64))), np.asarray(palette.resize((64, 64)))
        self.assertGreater(palette[40, 10, 0], 240)                    # the paint is the mask's red
        self.assertEqual((int(palette[40, 10, 1]), int(palette[40, 10, 2])), (0, 0))
        self.assertLess(palette[40, 40, 0], 10)                        # the lamp and the glass are not
        self.assertLess(palette[40, 56, 0], 10)
        r, g, b = (int(v) for v in base[40, 10])
        self.assertLess(max(r, g, b) - min(r, g, b), 6)                # no green left under the mask
        self.assertGreater(int(base[40, 10, 0]), int(base[8, 10, 0]) + 60)   # its shade is kept
        self.assertGreater(base[40, 40, 0], 180)                       # the lamp is still red
        self.assertLess(base[40, 40, 1], 40)
        self.assertAlmostEqual(share, .5, delta=.06)

    def test_a_far_shape_has_fewer_faces_keeps_its_seams_shut_and_its_map(self):
        # a tube of 24 x 40 quads, 0.3 m across and 1.7 m tall, cut open along one seam of its map
        n, m = 24, 40
        pos, uv, faces = [], [], []
        for j in range(m + 1):
            for i in range(n + 1):
                a = 2 * math.pi * i / n
                pos.append([.15 * math.cos(a), .15 * math.sin(a), 1.7 * j / m])
                uv.append([i / n, j / m])
        for j in range(m):
            for i in range(n):
                k = j * (n + 1) + i
                faces += [[k, k + 1, k + n + 2], [k, k + n + 2, k + n + 1]]
        pos, uv, faces = np.array(pos), np.array(uv), np.array(faces)
        nrm = pos * [1, 1, 0]
        nrm = nrm / np.linalg.norm(nrm, axis=1, keepdims=True)
        far = ta.far_shape(fal_mesh.Primitive(pos, nrm, uv, faces, 0))
        self.assertLess(len(far.faces), len(faces) / 2)
        self.assertGreater(len(far.faces), 40)
        a, b, c = (far.positions[far.faces[:, k]] for k in range(3))
        self.assertGreater(np.linalg.norm(np.cross(b - a, c - a), axis=1).min(), 1e-9)   # no folded face
        # no face draws the map across its seam: a face's corners stay within a few patches of each other
        spread = np.ptp(far.uv[far.faces], axis=1).max(axis=0)
        self.assertLess(spread[0], .4)
        # the seam stays shut: by their places the faces have no more open edges than a shape made
        # without a look at the map (one patch)
        def open_edges(shape):
            _, place = np.unique(np.round(shape.positions, 6), axis=0, return_inverse=True)
            place = place.reshape(-1)[shape.faces]
            edges = np.sort(np.concatenate([place[:, [0, 1]], place[:, [1, 2]], place[:, [2, 0]]]), axis=1)
            return int((np.unique(edges, axis=0, return_counts=True)[1] == 1).sum())
        whole = ta.far_shape(fal_mesh.Primitive(pos, nrm, uv, faces, 0), patch=10)
        self.assertEqual(open_edges(far), open_edges(whole))
        self.assertGreater(len(far.positions), len(whole.positions))     # the seam's two sides are two vertices

    def test_a_figure_that_stands_sideways_is_turned_to_the_front_for_the_rig(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = ta.SRC
            ta.SRC = Path(tmp)
            (ta.SRC / 'mesh').mkdir()
            try:
                for name, turn in (('ped_a', 0.), ('ped_b', math.pi / 2), ('ped_c', math.pi), ('ped_d', -2.2)):
                    source = ta.SRC / 'mesh' / f'{name}.glb'
                    figure_glb(source, turn)
                    q = ta.merged(fal_mesh.GLB(ta.facing_front(name, source)).primitives())
                    # the game's axes: glTF +z is -y. The feet reach out to the front, the width is along x
                    low = q.positions[q.positions[:, 2] < .05]
                    self.assertAlmostEqual(low[:, 1].min(), -.25, places=3, msg=name)
                    self.assertAlmostEqual(low[:, 1].max(), .1, places=3, msg=name)
                    self.assertAlmostEqual(float(np.ptp(q.positions[:, 0])), .5, places=3, msg=name)
                    self.assertAlmostEqual(float(np.ptp(q.positions[:, 2])), 1.7, places=3, msg=name)
            finally:
                ta.SRC = saved

    def test_a_rig_poses_its_mesh_by_its_bones_at_a_moment_of_its_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'arm.glb'
            arm_glb(path)
            rig = ta.Rig(path)
            self.assertAlmostEqual(rig.duration, 1.)
            # glTF (x, y, z) is the game's (x, -z, y): the strip stands along +z
            pos, nrm, places = rig.pose(0)
            np.testing.assert_allclose(pos[4], [0, 0, 2], atol=1e-6)
            np.testing.assert_allclose(places['Elbow'], [0, 0, 1], atol=1e-6)
            # the elbow turned a quarter about glTF z: what was above it now lies along glTF -x
            pos, nrm, _ = rig.pose(1)
            np.testing.assert_allclose(pos[4], [-1, 0, 1], atol=1e-5)
            np.testing.assert_allclose(pos[5], [-1, 0, 1.1], atol=1e-5)
            np.testing.assert_allclose(pos[0], [0, 0, 0], atol=1e-6)        # the root's part stays
            np.testing.assert_allclose(nrm[4], [0, -1, 0], atol=1e-5)       # glTF +z, the turn's own axis
            # half way: an eighth
            pos, _, _ = rig.pose(.5)
            np.testing.assert_allclose(pos[4], [-math.sin(math.pi / 4), 0, 1 + math.cos(math.pi / 4)], atol=2e-2)

    def test_the_planet_gets_the_cooked_models_and_none_without_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = ta.OUT
            ta.OUT = Path(tmp)
            try:
                self.assertEqual(ta.level_files('e2r_world'), {})
                out = ta.cooked()
                (out / ta.FLOW_DIR).mkdir(parents=True)
                (out / ta.PEOPLE_DIR).mkdir(parents=True)
                for name in ('car_x.dae', 'car_x.color.png', 'car_x.color.dds', 'car_x_pal.color.png'):
                    (out / ta.FLOW_DIR / name).write_bytes(b'c')
                shapes = {key: f'ped_y_{key}.dae' for key in ['stand', 'sit', 'far'] + [f'walk{k}' for k in range(ta.POSES)]}
                for name in list(shapes.values()) + ['ped_y.color.png']:
                    (out / ta.PEOPLE_DIR / name).write_bytes(b'p')
                manifest = {'version': ta.VERSION, 'cars': [{'name': 'car_x', 'body': 3, 'shape': 'car_x.dae', 'material': 'e2r_flowm_car_x'}],
                            'peds': [{'name': 'ped_y', 'material': 'e2r_pedm_ped_y', 'shapes': shapes,
                                      'look': {'shirt': [.1, .2, .3], 'pants': [0, 0, 0], 'skin': [1, 1, 1]}}]}
                (out / 'models.json').write_text(json.dumps(manifest), encoding='utf8')
                files = ta.level_files('e2r_world')
            finally:
                ta.OUT = saved
        models = json.loads(files['levels/e2r_world/art/traffic_models.json'])
        self.assertEqual(models['cars'], [{'name': 'car_x', 'body': 3, 'shape': '/levels/e2r_world/art/flow/car_x.dae'}])
        self.assertEqual(models['peds'][0]['shapes']['walk3'], '/levels/e2r_world/art/people/ped_y_walk3.dae')
        self.assertEqual(models['peds'][0]['look']['shirt'], [.1, .2, .3])
        self.assertEqual(len(models['peds'][0]['shapes']), ta.POSES + 3)
        for shape in [models['cars'][0]['shape']] + list(models['peds'][0]['shapes'].values()):
            self.assertIn(shape[1:], files)
        cars = json.loads(files['levels/e2r_world/art/flow/fal.materials.json'])
        stage = cars['e2r_flowm_car_x']['Stages'][0]
        self.assertTrue(stage['instanceDiffuse'])
        self.assertEqual(stage['colorPaletteMap'], '/levels/e2r_world/art/flow/car_x_pal.color.png')
        self.assertIn(stage['colorPaletteMap'][1:], files)
        # a map cooked as a DDS goes in as the DDS alone, under the name the material has for the PNG
        self.assertEqual(stage['baseColorMap'], '/levels/e2r_world/art/flow/car_x.color.png')
        self.assertIn('levels/e2r_world/art/flow/car_x.color.dds', files)
        self.assertNotIn('levels/e2r_world/art/flow/car_x.color.png', files)
        people = json.loads(files['levels/e2r_world/art/people/fal.materials.json'])
        self.assertEqual(people['e2r_pedm_ped_y']['Stages'][0]['baseColorMap'], '/levels/e2r_world/art/people/ped_y.color.png')

    def test_every_car_is_one_of_the_flows_bodies_and_fits_a_lane(self):
        import flow_art
        for name, (body, (length, width, height), faces, _) in ta.CARS.items():
            self.assertIn(body, range(1, len(flow_art.BODIES) + 1), name)
            self.assertLess(width, 2.35, name)           # the narrowest lane the flow draws is 2.6 m
            self.assertGreater(length, 3.4, name)
            self.assertLessEqual(faces, 3000, name)
        self.assertEqual({body for body, _, _, _ in ta.CARS.values()}, set(range(1, len(flow_art.BODIES) + 1)))


if __name__ == '__main__':
    unittest.main()
