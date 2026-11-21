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


def write_tree(path, lods=4, extras=None, names=True, height=12.0, tree=None, wind=False, factor=None):
    """A trunk (a prism of bark) and a crown (crossed leaf quads) a level, named as FoliMesh
    names its nodes; glTF's Y is up. Returns the triangle counts a level. tree: the generator's
    own notes (extras.alardonTree of the first node). wind: the model's wind data in its second
    and third texture coordinates. factor: the bark is a flat colour, not a texture."""
    doc = {'asset': {'version': '2.0'}, 'buffers': [], 'bufferViews': [], 'accessors': [], 'meshes': [], 'nodes': [],
           'images': [], 'textures': [], 'scenes': [{'nodes': []}], 'scene': 0,
           'materials': [
               {'name': 'bark', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}, 'normalTexture': {'index': 1}},
               {'name': 'leaves', 'alphaMode': 'MASK', 'alphaCutoff': .4, 'doubleSided': True,
                'pbrMetallicRoughness': {'baseColorTexture': {'index': 2}}, 'normalTexture': {'index': 3}}]}
    if extras:
        doc['asset']['extras'] = extras
    if factor:
        doc['materials'][0] = {'name': 'bark', 'pbrMetallicRoughness': {'baseColorFactor': list(factor)}}
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
            attributes = {'POSITION': accessor(positions, 'VEC3', 5126), 'TEXCOORD_0': accessor(uv, 'VEC2', 5126)}
            if wind:
                # height up the plant and the way out along a branch; flutter and phase
                out = np.hypot(positions[:, 0], positions[:, 2]) / 4 * (2 if part == 'leaves' else 0)
                attributes['TEXCOORD_1'] = accessor(np.column_stack([positions[:, 1] / height, out]).astype('<f4'), 'VEC2', 5126)
                flutter = np.full(len(positions), .7 if part == 'leaves' else 0.)
                attributes['TEXCOORD_2'] = accessor(np.column_stack([flutter, np.full(len(positions), .25)]).astype('<f4'),
                                                    'VEC2', 5126)
            doc['meshes'].append({'primitives': [{'attributes': attributes,
                'indices': accessor(tris.reshape(-1, 1), 'SCALAR', 5123), 'material': material}]})
            doc['nodes'].append({'mesh': len(doc['meshes']) - 1,
                                 'name': f'oak_s2_LOD{lod}_{part}' if names else f'part{len(doc["nodes"])}'})
            doc['scenes'][0]['nodes'].append(len(doc['nodes']) - 1)
    if tree:
        doc['nodes'][0]['extras'] = {'alardonTree': tree}
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
        # the file's last level is no lighter than the one before it: it is not worth a switch
        self.assertEqual(self.counts[2], self.counts[3])
        self.assertEqual(self.nodes('start01'), ['Colmesh-1', 'oak_s2_a700', 'oak_s2_a380', 'oak_s2_a150'])
        self.assertEqual(self.entry['lods'], [700, 380, 150])
        self.assertEqual(self.entry['triangles'], self.counts[:3])
        self.assertEqual(self.entry['levels'], [0, 1, 2])

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

    def test_a_levels_triangles_set_its_size_and_a_small_plant_switches_nearer(self):
        rule = flora_mesh.LOD
        tall = flora_mesh.lod_sizes([50000, 14000, 4000, 1100], 13.3)
        self.assertEqual(tall, [894, 473, 253, 133])
        low = flora_mesh.lod_sizes([9000, 1400, 400, 100], 2.4)
        for sizes in (tall, low):
            self.assertTrue(all(a - b >= rule['step'] for a, b in zip(sizes, sizes[1:])), sizes)
            self.assertGreaterEqual(sizes[-1], rule['least'])
            self.assertGreater(sizes[-1], flora_mesh.BILLBOARD_PX)
        # the same triangles on a plant a fifth as tall: drawn from a smaller size on screen
        self.assertLess(flora_mesh.lod_sizes([50000, 14000, 4000, 1100], 2.4)[0], tall[0] / 2)
        # nothing is asked to fill more than the screen
        self.assertEqual(flora_mesh.lod_sizes([400000, 1000], 20)[0], rule['most'])

    def test_level_0_keeps_its_thick_wood_and_drops_the_twigs(self):
        def tube(x, radius, length, sides=6):
            ring = [(radius * np.cos(2 * np.pi * k / sides), radius * np.sin(2 * np.pi * k / sides)) for k in range(sides)]
            positions = np.array([(x + a, b, 0) for a, b in ring] + [(x + a, b, length) for a, b in ring], dtype=float)
            faces = []
            for k in range(sides):
                n = (k + 1) % sides
                faces += [(k, n, sides + n), (k, sides + n, sides + k)]
            return positions, np.array(faces, dtype=np.int64)

        positions, faces, offset = [], [], 0
        # a trunk and forty twigs in one mesh, as a FoliMesh level 0 has them
        for x, radius, length in [(0, .3, 6)] + [(1 + k, .01, .5) for k in range(40)]:
            p, f = tube(x, radius, length)
            positions.append(p)
            faces.append(f + offset)
            offset += len(p)
        wood = flora_mesh.Piece(np.concatenate(positions), None, None, np.concatenate(faces), 0, 'bark')
        leaves = flora_mesh.Piece(positions[0] + (0, 0, 6), None, None, faces[0], 1, 'leaves')
        self.assertEqual(len(set(flora_mesh.parts(wood.positions, wood.faces))), 41)
        kept = flora_mesh.thin([wood, leaves], 60)
        bark = next(p for p in kept if not p.leaf)
        self.assertEqual(len(bark.faces), 60)
        # the trunk is in what is kept, whole
        self.assertEqual(int((bark.faces < 12).all(axis=1).sum()), 12)
        self.assertEqual(len(next(p for p in kept if p.leaf).faces), 12)
        # within the budget nothing is touched
        self.assertIs(flora_mesh.thin([wood, leaves], 1000)[0], wood)

    def test_a_level_0_too_heavy_for_the_game_is_left_out(self):
        heavy = dict(flora_mesh.HERO)
        try:
            flora_mesh.HERO.update(wood=4, most=20)
            entry = flora_mesh.convert(self.glb, self.root / 'pack', 'oak', 'oak_light')
        finally:
            flora_mesh.HERO.update(heavy)
        self.assertEqual(entry['levels'], [1, 2])
        self.assertEqual(entry['triangles'], self.counts[1:3])
        plain = flora_mesh.convert(self.glb, self.root / 'pack', 'oak', 'oak_plain_levels', hero=False)
        self.assertEqual(plain['levels'], [1, 2])

    def test_the_models_own_wind_data_becomes_the_wind_colours(self):
        path = self.root / 'windy.glb'
        write_tree(path, wind=True)
        flora_mesh.convert(path, self.root / 'pack', 'oak', 'oak_windy')
        dae = ET.parse(self.folder / 'oak_windy.dae').getroot()
        geometry = dae.find(".//c:geometry[@id='lod0']", NS)
        colours = np.array(geometry.find(".//c:source[@id='lod0-col']/c:float_array", NS).text.split(), dtype=float).reshape(-1, 4)
        groups = geometry.findall('.//c:triangles', NS)
        by = {('leaves' if '_leaves_' in g.get('material') else 'bark'): np.unique(np.array(g.find('c:p', NS).text.split(), dtype=int))
              for g in groups}
        # the bark: no flutter and no sway (the file says 0); the leaves: the file's flutter, its phase
        self.assertLess(colours[by['bark']][:, [0, 2]].max(), 1e-6)
        self.assertTrue(np.allclose(colours[by['leaves']][:, 0], .7, atol=.01))
        self.assertTrue(np.allclose(colours[:, 1], .25, atol=.01))
        self.assertGreater(colours[by['leaves']][:, 2].max(), .9)

    def test_the_trunk_collides_as_the_files_capsules(self):
        path = self.root / 'leaning.glb'
        # glTF: y up; two capsules up a leaning trunk and one high in the crown
        tree = {'lods': [{'index': k, 'distance': d} for k, d in enumerate((0, 15, 60, 200))], 'collision': [
            {'kind': 'capsule', 'a': [0, .2, 0], 'b': [.3, 2.5, 0], 'radius': .4},
            {'kind': 'capsule', 'a': [.3, 2.5, 0], 'b': [.9, 4.5, -.2], 'radius': .35},
            {'kind': 'capsule', 'a': [2, 9, 0], 'b': [3, 11, 0], 'radius': .2}]}
        write_tree(path, tree=tree)
        entry = flora_mesh.convert(path, self.root / 'pack', 'oak', 'oak_leaning')
        self.assertAlmostEqual(entry['trunk'], .4, places=3)
        dae = ET.parse(self.folder / 'oak_leaning.dae').getroot()
        col = dae.find(".//c:geometry[@id='col']", NS)
        self.assertEqual(int(col.find('.//c:triangles', NS).get('count')), 2 * 20)
        positions = np.array(col.find(".//c:source[@id='col-pos']/c:float_array", NS).text.split(), dtype=float).reshape(-1, 3)
        # Z is up in the game: the prisms reach from .2 to 4.5 m and lean along x
        self.assertAlmostEqual(positions[:, 2].min(), .2, delta=.2)
        self.assertAlmostEqual(positions[:, 2].max(), 4.5, delta=.2)
        self.assertGreater(positions[:, 0].max(), 1)

    def test_a_flat_colour_is_given_as_the_game_reads_it(self):
        path = self.root / 'flat.glb'
        write_tree(path, factor=(.0782, .1946, .0273, 1))
        flora_mesh.convert(path, self.root / 'pack', 'moss', 'moss_flat')
        defs = json.loads((self.root / 'pack/art/shapes/earthng/flora/trees/moss/main.materials.json').read_text(encoding='utf8'))
        bark = next(v for k, v in defs.items() if '_bark_' in k)
        # glTF's factor is linear, a material's is sRGB
        for value, want in zip(bark['Stages'][0]['baseColorFactor'], (.3098, .4784, .1804, 1.)):
            self.assertAlmostEqual(value, want, delta=.0005)
        # ... over a plain white map: a material with no colour map at all is drawn as the
        # game's NoMaterial hatch
        plain = Image.open(self.root / 'pack' / bark['Stages'][0]['baseColorMap'].lstrip('/'))
        self.assertEqual((plain.size, plain.getpixel((3, 3))), ((64, 64), (255, 255, 255)))

    def test_a_trees_moss_patch_is_left_out_and_a_mushrooms_cap_is_not(self):
        glb = flora_mesh.GLB(self.glb)
        glb.doc['materials'].append({'name': 'moss', 'pbrMetallicRoughness': {'baseColorFactor': [0, .2, 0, 1]}})
        flat = len(glb.doc['materials']) - 1
        tri = np.array([(0, 1, 2)], dtype=np.int64)
        corners = np.array([(0, 0, 0), (1, 0, 0), (0, 0, 1)], dtype=float)
        trunk = flora_mesh.Piece(np.zeros((300, 3)), None, None, np.zeros((100, 3), dtype=np.int64), 0, 'bark')
        patch = flora_mesh.Piece(corners, None, None, tri, flat, 'bark')
        leaves = flora_mesh.Piece(corners, None, None, tri, 1, 'leaves')
        self.assertEqual(flora_mesh.unpatched(glb, [trunk, patch, leaves], 14.), [trunk, leaves])
        # a low plant keeps every part; a part that is most of the wood is no patch
        self.assertEqual(len(flora_mesh.unpatched(glb, [trunk, patch, leaves], .3)), 3)
        self.assertEqual(flora_mesh.unpatched(glb, [patch, leaves], 14.), [patch, leaves])

    def test_a_texture_is_a_power_of_two_or_the_game_refuses_it(self):
        fit = flora_mesh.power_of_two
        self.assertEqual(fit(Image.new('RGB', (1024, 1536))).size, (1024, 1024))
        self.assertEqual(fit(Image.new('RGB', (1024, 1900))).size, (1024, 2048))
        self.assertEqual(fit(Image.new('RGB', (8, 8))).size, (16, 16))
        same = Image.new('RGB', (512, 256))
        self.assertIs(fit(same), same)
        # every texture of a converted shape, the leaves' cut-out too, and its DDS beside it
        for path in self.folder.glob('t_*.png'):
            width, height = Image.open(path).size
            self.assertEqual((width & (width - 1), height & (height - 1)), (0, 0), path.name)
            self.assertGreaterEqual(min(width, height), 16, path.name)
            self.assertTrue(path.with_suffix('.dds').exists(), path.name)

    def test_bark_is_darkened_and_leaves_are_not(self):
        defs = json.loads((self.folder / 'main.materials.json').read_text(encoding='utf8'))
        bark = next(v for k, v in defs.items() if '_bark_' in k)
        leaves = next(v for k, v in defs.items() if '_leaves_' in k)
        factor = bark['Stages'][0]['baseColorFactor']
        self.assertTrue(all(.7 < value < .95 for value in factor[:3]), factor)      # sRGB of BARK
        self.assertNotIn('baseColorFactor', leaves['Stages'][0])

    def test_a_tint_with_colour_in_it_becomes_materials_and_grey_shade_does_not(self):
        positions = np.array([(x, y, 0) for y in range(3) for x in range(40)], dtype=float)
        faces = np.array([(k, k + 1, k + 40) for k in range(39)] + [(k + 40, k + 41, k + 80) for k in range(39)], dtype=np.int64)
        tint = np.ones((120, 3))
        tint[:40] = (.9, .05, .03)                      # a red cap: the first row's vertices
        tint[80:] = (.6, .6, .6)                        # shade under it: grey
        cap = flora_mesh.Piece(positions, None, None, faces, 0, 'bark', tint=tint)
        shade = flora_mesh.Piece(positions, None, None, faces, 1, 'bark', tint=np.full((120, 3), .7))
        plain = flora_mesh.Piece(positions, None, None, faces, 2, 'bark')
        out = flora_mesh.tinted([cap, shade, plain])
        # grey shade and no tint at all: the pieces as they were
        self.assertIs(out[-2], shade)
        self.assertIs(out[-1], plain)
        groups = out[:-2]
        self.assertGreater(len(groups), 1)
        self.assertLessEqual(len(groups), flora_mesh.TINT['most'])
        self.assertEqual(sum(len(g.faces) for g in groups), len(faces))
        reds = [g for g in groups if g.shade and g.shade[0] > 2 * g.shade[1]]
        self.assertTrue(reds)
        # a tint is rounded: two levels of a model come to the same material
        for g in groups:
            for value in g.shade or ():
                self.assertAlmostEqual(value * flora_mesh.TINT['round'], round(value * flora_mesh.TINT['round']), places=6)
        self.assertTrue(any(g.shade is None for g in groups), 'the grey faces keep the plain material')

    def test_a_normal_map_is_turned_to_the_games_green(self):
        defs = json.loads((self.folder / 'main.materials.json').read_text(encoding='utf8'))
        bark = next(v for k, v in defs.items() if '_bark_' in k)
        image = Image.open(self.root / 'pack' / bark['Stages'][0]['normalMap'].lstrip('/'))
        # the file's (128, 128, 255): green up; the game's: green down
        self.assertEqual(image.getpixel((0, 0)), (128, 127, 255))

    def test_leaves_light_through_as_the_games_own(self):
        defs = json.loads((self.folder / 'main.materials.json').read_text(encoding='utf8'))
        leaves = next(v for k, v in defs.items() if '_leaves_' in k)
        self.assertTrue(leaves['subSurface'] and leaves['invertBackFaceNormals'])
        # the colour has no alpha of its own: the cut is the opacity map's
        colour = Image.open(self.root / 'pack' / leaves['Stages'][0]['baseColorMap'].lstrip('/'))
        self.assertEqual(colour.mode, 'RGB')
        # what is cut away took the leaf's colour, not the file's
        self.assertEqual(colour.getpixel((7, 0)), colour.getpixel((0, 0)))

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
