"""The static FAL importer preserves dimensions, orientation, materials and winding."""
import base64
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

import fal_mesh


NS = {'c': fal_mesh.NS}


def write_glb(path, *, nodes=None, matrix=None, reflected=False, interleaved=False,
              material=False, image_uri=False, invalid_index=False, bad_normal=False, webp=False):
    """An asymmetric, closed tetrahedron; no generated/downloaded art is required."""
    pos = np.array([[0, 0, 0], [2, 0, 0], [0, 3, 0], [0, 0, 4]], dtype='<f4')
    faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype='<u2')
    nrm = fal_mesh.vertex_normals(pos.astype(float), faces).astype('<f4')
    if bad_normal:
        nrm[0] = 0
    if invalid_index:
        faces[-1, -1] = 999
    uv = np.array([[0, 0], [1, 0], [0, 1], [.75, .25]], dtype='<f4')
    document = {'asset': {'version': '2.0'}, 'buffers': [], 'bufferViews': [], 'accessors': [],
                'meshes': [{'primitives': []}]}
    binary = bytearray()

    def add_view(raw, **extras):
        while len(binary) % 4:
            binary.append(0)
        index = len(document['bufferViews'])
        document['bufferViews'].append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(raw), **extras})
        binary.extend(raw)
        return index

    def add_accessor(raw, kind, component, count, *, view=None, offset=0):
        if view is None:
            view = add_view(raw)
        index = len(document['accessors'])
        document['accessors'].append({'bufferView': view, 'byteOffset': offset, 'componentType': component,
                                      'count': count, 'type': kind})
        return index

    if interleaved:
        view = add_view(np.column_stack([pos, nrm, uv]).astype('<f4').tobytes(), byteStride=32)
        attrs = {'POSITION': add_accessor(None, 'VEC3', 5126, 4, view=view),
                 'NORMAL': add_accessor(None, 'VEC3', 5126, 4, view=view, offset=12),
                 'TEXCOORD_0': add_accessor(None, 'VEC2', 5126, 4, view=view, offset=24)}
    else:
        attrs = {'POSITION': add_accessor(pos.tobytes(), 'VEC3', 5126, 4),
                 'NORMAL': add_accessor(nrm.tobytes(), 'VEC3', 5126, 4),
                 'TEXCOORD_0': add_accessor(uv.tobytes(), 'VEC2', 5126, 4)}
    primitive = {'attributes': attrs, 'indices': add_accessor(faces.tobytes(), 'SCALAR', 5123, faces.size)}
    if material:
        image = Image.new('RGBA', (2, 2), (70, 140, 210, 255))
        stream = io.BytesIO()
        image.save(stream, format='WEBP' if webp else 'PNG', lossless=True)
        raw = stream.getvalue()
        document['images'] = ([{'uri': 'data:image/png;base64,' + base64.b64encode(raw).decode()}] if image_uri else
                              [{'bufferView': add_view(raw), 'mimeType': 'image/png'}])
        document['textures'] = ([{'extensions': {'EXT_texture_webp': {'source': 0}}}] if webp else [{'source': 0}])
        document['materials'] = [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0},
                                   'baseColorFactor': [.7, .8, .9, 1],
                                   'metallicRoughnessTexture': {'index': 0}},
                                  'normalTexture': {'index': 0}, 'occlusionTexture': {'index': 0}}]
        primitive['material'] = 0
    document['meshes'][0]['primitives'].append(primitive)
    document['nodes'] = nodes or [{'mesh': 0}]
    if matrix:
        document['nodes'][0]['matrix'] = matrix
    elif reflected:
        document['nodes'][0]['scale'] = [-1, 1, 1]
    document['scenes'] = [{'nodes': [0]}]
    document['scene'] = 0
    document['buffers'] = [{'byteLength': len(binary)}]
    while len(binary) % 4:
        binary.append(0)
    encoded = json.dumps(document, separators=(',', ':')).encode()
    encoded += b' ' * (-len(encoded) % 4)
    raw = (struct.pack('<4sII', b'glTF', 2, 12 + 8 + len(encoded) + 8 + len(binary)) +
           struct.pack('<II', len(encoded), 0x4E4F534A) + encoded +
           struct.pack('<II', len(binary), 0x004E4942) + binary)
    path.write_bytes(raw)
    return pos, faces, uv


class FalMeshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'tetra.glb'

    def test_metric_extent_ground_origin_and_collada_bindings(self):
        write_glb(self.path, material=True)
        out = self.root / 'export'
        result = fal_mesh.convert(self.path, out, 'kiosk', size=[6, 4, 3], yaw=90)
        np.testing.assert_allclose(result['bounds'], [[-3, -2, 0], [3, 2, 3]], atol=1e-7)
        self.assertEqual(result['triangles'], 4)
        dae = ET.parse(out / 'kiosk.dae')
        self.assertEqual(dae.findtext('c:asset/c:up_axis', namespaces=NS), 'Z_UP')
        self.assertEqual(dae.find('c:asset/c:unit', NS).get('meter'), '1')
        self.assertIsNotNone(dae.find('.//c:node[@name="kiosk_a100"]', NS))
        material = json.loads((out / 'main.materials.json').read_text())
        label = next(iter(material))
        self.assertEqual(dae.find('.//c:triangles', NS).get('material'), label)
        self.assertEqual(dae.find('.//c:instance_material', NS).get('target'), f'#{label}')
        uv_source = dae.find('.//c:source[@id="g0-uv"]/c:float_array', NS)
        uv = np.fromstring(uv_source.text, sep=' ').reshape(-1, 2)
        np.testing.assert_allclose(uv, [[0, 1], [1, 1], [0, 0], [.75, .75]])

    def test_y_up_to_z_up_and_proportional_height(self):
        write_glb(self.path)
        primitives = fal_mesh.GLB(self.path).primitives()
        np.testing.assert_array_equal(primitives[0].positions, [[0, 0, 0], [2, 0, 0], [0, 0, 3], [0, -4, 0]])
        extent = fal_mesh.fit(primitives, height=6)
        np.testing.assert_allclose(extent, [4, 8, 6])
        np.testing.assert_allclose(primitives[0].positions.min(axis=0), [-2, -4, 0])

    def test_hierarchical_quaternion_translation_and_nonuniform_scale(self):
        s = 2 ** -.5
        write_glb(self.path, nodes=[{'rotation': [0, 0, s, s], 'translation': [1, 0, 0], 'children': [1]},
                                    {'mesh': 0, 'translation': [0, 2, 0], 'scale': [2, 1, 1]}])
        primitive = fal_mesh.GLB(self.path).primitives()[0]
        np.testing.assert_allclose(primitive.positions, [[-1, 0, 0], [-1, 0, 4], [-4, 0, 0], [-1, -4, 0]], atol=1e-7)
        # Inverse transpose keeps every transformed vertex normal perpendicular to
        # its transformed tangent plane; interpolated normals remain unit length.
        np.testing.assert_allclose(np.linalg.norm(primitive.normals, axis=1), 1)
        source_pos, faces, _ = write_glb(self.root / 'plain.glb')
        original = fal_mesh.GLB(self.root / 'plain.glb').primitives()[0]
        transform = np.array([[0., 0, -1], [0, 1, 0], [2, 0, 0]])
        expected = original.normals @ np.linalg.inv(transform)
        expected /= np.linalg.norm(expected, axis=1)[:, None]
        np.testing.assert_allclose(primitive.normals, expected, atol=1e-7)

    def test_column_major_matrix_is_applied(self):
        matrix = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, 6, 7, 1]
        write_glb(self.path, matrix=matrix)
        primitive = fal_mesh.GLB(self.path).primitives()[0]
        np.testing.assert_allclose(primitive.positions[0], [5, -7, 6])

    def test_reflection_keeps_outward_winding_and_normals(self):
        write_glb(self.path, reflected=True)
        primitive = fal_mesh.GLB(self.path).primitives()[0]
        centre = primitive.positions.mean(axis=0)
        for face in primitive.faces:
            a, b, c = primitive.positions[face]
            normal = np.cross(b - a, c - a)
            self.assertGreater(np.dot(normal, (a + b + c) / 3 - centre), 0)
            self.assertGreater(np.dot(normal, primitive.normals[face].mean(axis=0)), 0)

    def test_embedded_and_data_uri_images_unpack_pbr_channels(self):
        for data_uri in (False, True):
            with self.subTest(data_uri=data_uri):
                write_glb(self.path, material=True, image_uri=data_uri)
                out = self.root / f'export_{data_uri}'
                fal_mesh.convert(self.path, out, 'cabinet', height=2)
                material = next(iter(json.loads((out / 'main.materials.json').read_text()).values()))
                self.assertEqual(material['version'], 1.5)
                stage = material['Stages'][0]
                self.assertEqual(stage['baseColorFactor'], [.7, .8, .9, 1])
                for field, value in [('roughnessMap', 140), ('metallicMap', 210), ('ambientOcclusionMap', 70)]:
                    self.assertTrue(stage[field].startswith('/art/shapes/earthng/kyiv3d/cabinet/'))
                    with Image.open(out / Path(stage[field]).name) as image:
                        self.assertEqual(image.getpixel((0, 0)), value)
                with Image.open(out / Path(stage['baseColorMap']).name) as image:
                    self.assertEqual(image.getpixel((0, 0)), (70, 140, 210, 255))

    def test_interleaved_accessors_match_tightly_packed(self):
        write_glb(self.path, interleaved=True)
        a = fal_mesh.GLB(self.path).primitives()[0]
        write_glb(self.root / 'plain.glb')
        b = fal_mesh.GLB(self.root / 'plain.glb').primitives()[0]
        for field in ('positions', 'normals', 'uv', 'faces'):
            np.testing.assert_array_equal(getattr(a, field), getattr(b, field))

    def test_trellis_webp_texture_extension_is_decoded_losslessly(self):
        write_glb(self.path, material=True, webp=True)
        out = self.root / 'webp_export'
        fal_mesh.convert(self.path, out, 'bakery', height=3)
        material = next(iter(json.loads((out / 'main.materials.json').read_text()).values()))
        with Image.open(out / Path(material['Stages'][0]['baseColorMap']).name) as image:
            self.assertEqual(image.getpixel((0, 0)), (70, 140, 210, 255))

    def test_zero_normal_is_reconstructed_from_incident_geometry(self):
        write_glb(self.path, bad_normal=True)
        glb = fal_mesh.GLB(self.path)
        primitive = glb.primitives()[0]
        self.assertEqual(glb.repairs['zero_normals_reconstructed'], 1)
        expected = fal_mesh.vertex_normals(primitive.positions, primitive.faces)
        np.testing.assert_allclose(primitive.normals[0], expected[0])

    def test_rejects_bad_indices_and_truncated_files(self):
        for options, message in [({'invalid_index': True}, 'index outside')]:
            write_glb(self.path, **options)
            with self.assertRaisesRegex(ValueError, message):
                fal_mesh.GLB(self.path).primitives()
        write_glb(self.path)
        self.path.write_bytes(self.path.read_bytes()[:-5])
        with self.assertRaisesRegex(ValueError, 'complete glTF'):
            fal_mesh.GLB(self.path)


if __name__ == '__main__':
    unittest.main()
