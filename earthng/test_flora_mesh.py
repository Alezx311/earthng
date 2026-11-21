"""A FoliMesh GLB becomes a game tree: its levels of detail, wind colours, cut-out leaves, collision."""
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
import flora_mesh

NS = {'c': fal_mesh.NS}


def png(colour, size=8, alpha=None):
    image = Image.new('RGBA' if alpha is not None else 'RGB', (size, size), colour)
    if alpha is not None:
        # half of the texture is leaf, half is cut away
        a = Image.new('L', (size, size), 0)
        a.paste(255, (0, 0, size // 2, size))
        image.putalpha(a)
    out = io.BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


def write_tree(path, lods=4, extras=None, names=True, height=12.0):
    """A trunk (a prism of bark) and a crown (crossed leaf quads) a level, named as FoliMesh
    names its nodes; glTF's Y is up. Returns the triangle counts a level."""
    doc = {'asset': {'version': '2.0'}, 'buffers': [], 'bufferViews': [], 'accessors': [], 'meshes': [], 'nodes': [],
           'images': [], 'textures': [], 'scenes': [{'nodes': []}], 'scene': 0,
           'materials': [
               {'name': 'bark', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}, 'normalTexture': {'index': 1}},
               {'name': 'leaves', 'alphaMode': 'MASK', 'alphaCutoff': .4, 'doubleSided': True,
                'pbrMetallicRoughness': {'baseColorTexture': {'index': 2}}, 'normalTexture': {'index': 3}}]}
    if extras:
        doc['asset']['extras'] = extras
    binary = bytearray()

    def view(raw):
        while len(binary) % 4:
            binary.append(0)
        doc['bufferViews'].append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(raw)})
        binary.extend(raw)
        return len(doc['bufferViews']) - 1

    def accessor(array, kind, component):
        doc['accessors'].append({'bufferView': view(array.tobytes()), 'componentType': component, 'count': len(array),
                                 'type': kind})
        return len(doc['accessors']) - 1

    for image in (png((90, 70, 50)), png((128, 128, 255)), png((40, 110, 30), alpha=True), png((128, 128, 255))):
        doc['images'].append({'bufferView': view(image), 'mimeType': 'image/png'})
        doc['textures'].append({'source': len(doc['images']) - 1})
    counts = []
    for lod in range(lods):
        sides = max(3, 12 >> lod)
        ring = [(.3 * np.cos(2 * np.pi * k / sides), .3 * np.sin(2 * np.pi * k / sides)) for k in range(sides)]
        # glTF: x right, y up, z towards the viewer
        trunk = np.array([(x, 0, z) for x, z in ring] + [(x, height * .6, z) for x, z in ring], dtype='<f4')
        faces = []
        for k in range(sides):
            n = (k + 1) % sides
            faces += [(k, sides + n, n), (k, sides + k, sides + n)]
        trunk_faces = np.array(faces, dtype='<u2')
        quads = max(1, 6 >> lod)
        leaf, leaf_faces = [], []
        for q in range(quads):
            a = np.pi * q / quads
            dx, dz = 4 * np.cos(a), 4 * np.sin(a)
            base = len(leaf)
            leaf += [(-dx, height * .5, -dz), (dx, height * .5, dz), (dx, height, dz), (-dx, height, -dz)]
            leaf_faces += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
        leaf = np.array(leaf, dtype='<f4')
        leaf_faces = np.array(leaf_faces, dtype='<u2')
        counts.append(len(trunk_faces) + len(leaf_faces))
        for part, positions, tris, material in (('bark', trunk, trunk_faces, 0), ('leaves', leaf, leaf_faces, 1)):
            uv = np.column_stack([positions[:, 0] * .1 + .5, positions[:, 1] / height]).astype('<f4')
            doc['meshes'].append({'primitives': [{'attributes': {
                'POSITION': accessor(positions, 'VEC3', 5126), 'TEXCOORD_0': accessor(uv, 'VEC2', 5126)},
                'indices': accessor(tris.reshape(-1, 1), 'SCALAR', 5123), 'material': material}]})
            doc['nodes'].append({'mesh': len(doc['meshes']) - 1,
                                 'name': f'oak_s2_LOD{lod}_{part}' if names else f'part{len(doc["nodes"])}'})
            doc['scenes'][0]['nodes'].append(len(doc['nodes']) - 1)
    doc['buffers'].append({'byteLength': len(binary)})
    text = json.dumps(doc).encode()
    text += b' ' * (-len(text) % 4)
    binary += b'\0' * (-len(binary) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    Path(path).write_bytes(struct.pack('<4sII', b'glTF', 2, total) + struct.pack('<II', len(text), 0x4E4F534A) + text
                           + struct.pack('<II', len(binary), 0x004E4942) + bytes(binary))
    return counts


class FloraMeshTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.glb = self.root / 'oak_s2.glb'
        self.counts = write_tree(self.glb)
        self.entry = flora_mesh.convert(self.glb, self.root / 'pack', 'oak')
        self.folder = self.root / 'pack/art/shapes/earthng/flora/trees/oak'
        self.dae = ET.parse(self.folder / 'oak_s2.dae').getroot()

    def tearDown(self):
        self.tmp.cleanup()

    def nodes(self, under):
        return [n.get('name') for n in self.dae.findall(f".//c:node[@name='{under}']/c:node", NS)]

    def test_every_level_is_a_node_under_start01_by_its_pixel_size(self):
        self.assertEqual(self.nodes('start01'), ['Colmesh-1', 'oak_s2_a700', 'oak_s2_a400', 'oak_s2_a190', 'oak_s2_a70'])
        self.assertEqual(self.entry['lods'], [700, 400, 190, 70])
        self.assertEqual(self.entry['triangles'], self.counts)

    def test_the_billboard_is_a_node_beside_them(self):
        self.assertEqual(self.nodes('base00'), ['start01', 'bb_autobillboard25'])

    def test_the_tree_stands_up_in_metres_on_its_root(self):
        self.assertAlmostEqual(self.entry['height'], 12, places=3)
        self.assertAlmostEqual(self.entry['radius'], 4, delta=.3)
        self.assertAlmostEqual(self.entry['trunk'], .3, delta=.02)
        source = self.dae.find(".//c:geometry[@id='lod0']//c:source[@id='lod0-pos']/c:float_array", NS)
        positions = np.array(source.text.split(), dtype=float).reshape(-1, 3)
        self.assertAlmostEqual(positions[:, 2].max(), 12, places=3)
        self.assertAlmostEqual(positions[:, 2].min(), 0, places=3)

    def test_a_level_is_one_geometry_with_a_group_a_material(self):
        groups = self.dae.findall(".//c:geometry[@id='lod0']//c:triangles", NS)
        self.assertEqual(len(groups), 2)
        labels = [g.get('material') for g in groups]
        self.assertTrue(labels[0].startswith('e2rfl_oak_bark_') and labels[1].startswith('e2rfl_oak_leaves_'), labels)
        self.assertEqual(sum(int(g.get('count')) for g in groups), self.counts[0])
        self.assertEqual({i.get('semantic') for i in groups[0]} - {None}, {'VERTEX', 'NORMAL', 'TEXCOORD', 'COLOR'})

    def test_wind_is_still_at_the_trunk_and_moves_the_crown(self):
        geometry = self.dae.find(".//c:geometry[@id='lod0']", NS)
        colours = np.array(geometry.find(".//c:source[@id='lod0-col']/c:float_array", NS).text.split(), dtype=float).reshape(-1, 4)
        positions = np.array(geometry.find(".//c:source[@id='lod0-pos']/c:float_array", NS).text.split(), dtype=float).reshape(-1, 3)
        trunk = np.hypot(positions[:, 0], positions[:, 1]) < .35
        self.assertTrue(trunk.any() and (~trunk).any())
        # red (flutter) and blue (sway) are nothing on the trunk
        self.assertLess(colours[trunk][:, 0].max(), 1e-6)
        self.assertLess(colours[trunk][:, 2].max(), .05)
        self.assertGreater(colours[~trunk][:, 0].min(), .4)
        self.assertGreater(colours[~trunk][:, 2].max(), .5)
        self.assertTrue(((colours >= 0) & (colours <= 1)).all())

    def test_leaves_are_cut_out_and_two_sided_bark_is_not(self):
        defs = json.loads((self.folder / 'main.materials.json').read_text(encoding='utf8'))
        bark = next(v for k, v in defs.items() if '_bark_' in k)
        leaves = next(v for k, v in defs.items() if '_leaves_' in k)
        self.assertEqual((leaves['alphaTest'], leaves['alphaRef'], leaves['doubleSided']), (True, 102, True))
        self.assertNotIn('alphaTest', bark)
        for material in (bark, leaves):
            stage = material['Stages'][0]
            for key in ('baseColorMap', 'normalMap'):
                self.assertTrue(stage[key].startswith('/art/shapes/earthng/flora/trees/oak/t_'), stage[key])
                self.assertTrue((self.root / 'pack' / stage[key].lstrip('/')).exists(), stage[key])
        self.assertIn('opacityMap', leaves['Stages'][0])
        self.assertEqual(self.entry['materials'], '/art/shapes/earthng/flora/trees/oak/main.materials.json')

    def test_a_second_variant_shares_the_species_textures_and_materials(self):
        other = self.root / 'oak_s3.glb'
        write_tree(other, height=20.0)
        before = sorted(p.name for p in self.folder.glob('t_*'))
        entry = flora_mesh.convert(other, self.root / 'pack', 'oak')
        self.assertEqual(sorted(p.name for p in self.folder.glob('t_*')), before)
        self.assertAlmostEqual(entry['height'], 20, places=3)
        defs = json.loads((self.folder / 'main.materials.json').read_text(encoding='utf8'))
        self.assertEqual(len(defs), 2)

    def test_the_trunk_collides_as_a_prism(self):
        triangles = self.dae.find(".//c:geometry[@id='col']//c:triangles", NS)
        self.assertEqual(int(triangles.get('count')), 6 * 2 + 4 * 2)
        self.assertIsNone(triangles.get('material'))

    def test_the_files_own_distances_set_the_sizes(self):
        path = self.root / 'far.glb'
        write_tree(path, extras={'lodDistances': [20, 45, 100, 240]})
        entry = flora_mesh.convert(path, self.root / 'pack', 'oak', 'oak_far')
        # 12 m tall: 935 px at 12 m
        self.assertEqual(entry['lods'], [561, 249, 112, 47])

    def test_a_file_without_level_names_is_one_level(self):
        path = self.root / 'plain.glb'
        write_tree(path, lods=1, names=False)
        entry = flora_mesh.convert(path, self.root / 'pack', 'oak', 'oak_plain')
        self.assertEqual(entry['lods'], [250])
        self.assertEqual(len(entry['triangles']), 1)

    def test_names_are_checked(self):
        with self.assertRaises(ValueError):
            flora_mesh.convert(self.glb, self.root / 'pack', 'Oak Tree')


if __name__ == '__main__':
    unittest.main()
