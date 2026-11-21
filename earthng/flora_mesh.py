"""A FoliMesh GLB as a BeamNG tree: one Collada shape with its levels of detail and a billboard.

A FoliMesh export (earthng/folimesh.py) holds a plant's levels of detail as separate nodes,
`<species>_s<variant>_LOD<n>_bark` and `..._leaves`, with photo textures of bark and leaves, their
normal maps, and simple collision in `extras`. The game wants what its own trees are
(east_coast_usa/art/shapes/trees/*):

  base00
    start01
      <name>_a<size>     one node a level of detail: drawn while the tree is at least <size> px tall
      Colmesh-1          the trunk, a prism
    bb_autobillboard<size>   the game bakes an imposter and draws it under the last level

with one geometry a level (a triangle group a material) and vertex colours that carry the wind
(shaders/common/wind.hlsl, GPU Gems 3 ch. 16): red is how much a vertex flutters (a leaf's
edge), green the phase of its branch, blue how much it sways with the branch; the trunk's bend
comes from the height. A FoliMesh model keeps its wind in other channels, so the colours are
laid here from the geometry: nothing at the trunk, growing along the branches and into the leaves.

Textures go beside the shape, each once a species (by content), as PNG and as DDS with full mip
chains; leaves keep their coverage down the chain (fast_dds alpha_ref), or a far crown thins to
twigs. Materials are named e2rfl_<species>_<part>.

    python earthng/flora_mesh.py data/folimesh/oak_s1.glb --species oak --out data/flora/pack
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

import fal_mesh
from fal_mesh import AXES, GLB, NS, unit_normals, vertex_normals

ROOT = '/art/shapes/earthng/flora'
# The levels' sizes in pixels of the tree's height on screen, most detailed first, and the
# billboard's: the game's own trees switch at 750, 500 and 250 and go to the imposter at 25.
LOD_PX = {1: (250,), 2: (500, 200), 3: (700, 380, 150), 4: (700, 400, 190, 70)}
BILLBOARD_PX = 25
# a level's distance in the file's extras to its size: px = height * PX_AT_1M / distance
# (a 1080 px tall frame at the game's 60 degree lens: 1080 / (2 tan 30))
PX_AT_1M = 935
LEAF_PARTS = ('leaves', 'leaf', 'needles', 'foliage', 'fronds', 'petals', 'flowers', 'blades')
PART_RE = re.compile(r'(?:^|_)LOD(\d)(?:_([A-Za-z]+))?', re.I)


class Piece:
    """One primitive of one level: arrays in the game's frame (Z up, metres)."""

    def __init__(self, positions, normals, uv, faces, material, part):
        self.positions, self.normals, self.uv, self.faces = positions, normals, uv, faces
        self.material, self.part = material, part
        self.colour = None

    @property
    def leaf(self):
        return self.part in LEAF_PARTS


def levels(glb):
    """{lod: [Piece]} of a FoliMesh GLB, node transforms baked, glTF's Y up turned to Z up.
    A node (or its mesh, or a parent) names the level and the part; a file without such names
    is one level."""
    doc = glb.doc
    nodes = doc.get('nodes', [])
    scenes = doc.get('scenes', [])
    roots = (scenes[doc.get('scene', 0)].get('nodes', []) if scenes else
             sorted(set(range(len(nodes))) - {c for n in nodes for c in n.get('children', [])}))
    out = {}

    def label(index, inherited):
        node = nodes[index]
        names = [node.get('name', '')]
        if 'mesh' in node:
            names.append(doc['meshes'][node['mesh']].get('name', ''))
        lod, part = inherited
        for name in names:
            match = PART_RE.search(name)
            if match:
                lod = int(match.group(1))
                if match.group(2):
                    part = match.group(2).lower()
            lowered = name.lower()
            for word in LEAF_PARTS + ('bark', 'trunk', 'branch', 'wood', 'stem', 'cap', 'rock', 'stone'):
                if lowered.endswith('_' + word) or lowered == word:
                    part = word
        return lod, part

    def visit(index, transform, inherited, trail):
        if index in trail:
            raise ValueError('Cycle in glTF node graph')
        node = nodes[index]
        transform = transform @ GLB.transform(node)
        here = label(index, inherited)
        if 'mesh' in node and not _collision(node.get('name', '')):
            lod, part = here
            for piece in _pieces(glb, node['mesh'], AXES @ transform, part):
                out.setdefault(lod or 0, []).append(piece)
        for child in node.get('children', []):
            visit(child, transform, here, trail | {index})

    for root in roots:
        visit(root, np.eye(4), (None, None), set())
    if not out:
        raise ValueError('GLB contains no triangle geometry')
    return dict(sorted(out.items()))


def _collision(name):
    lowered = name.lower()
    return lowered.startswith(('col', 'ucx', 'ubx', 'ucp')) or 'collision' in lowered or 'collider' in lowered


def _pieces(glb, mesh, transform, part):
    doc = glb.doc
    for source in doc['meshes'][mesh]['primitives']:
        if 'KHR_draco_mesh_compression' in source.get('extensions', {}):
            raise ValueError('Draco-compressed geometry requires decompression first')
        if source.get('mode', 4) != 4:
            continue
        attrs = source['attributes']
        positions = glb.accessor(attrs['POSITION']).astype(float)
        count = len(positions)
        faces = glb.accessor(source['indices']) if 'indices' in source else np.arange(count)[:, None]
        faces = faces.reshape(-1, 3).astype(np.int64)
        if not len(faces) or faces.max() >= count:
            continue
        linear = transform[:3, :3]
        positions = positions @ linear.T + transform[:3, 3]
        if np.linalg.det(linear) < 0:
            faces = faces[:, [0, 2, 1]]
        a, b, c = (positions[faces[:, k]] for k in range(3))
        keep = np.linalg.norm(np.cross(b - a, c - a), axis=1) > 1e-12
        faces = faces[keep]
        if not len(faces):
            continue
        if 'NORMAL' in attrs:
            normals = glb.accessor(attrs['NORMAL']).astype(float) @ np.linalg.inv(linear)
            lengths = np.linalg.norm(normals, axis=1)
            bad = lengths < 1e-9
            if bad.any():
                normals[bad] = vertex_normals(positions, faces)[bad]
            normals = unit_normals(normals)
        else:
            normals = vertex_normals(positions, faces)
        uv = None
        if 'TEXCOORD_0' in attrs:
            uv = glb.accessor(attrs['TEXCOORD_0']).astype(float)
            uv[:, 1] = 1 - uv[:, 1]
        material = source.get('material')
        here = part
        if here is None and material is not None:
            # no part in the node's name: the material says (a cut-out is foliage)
            m = doc['materials'][material]
            here = 'leaves' if m.get('alphaMode') in ('MASK', 'BLEND') else 'bark'
        yield Piece(positions, normals, uv, faces, material, here or 'bark')


def measure(pieces):
    """A level's height, its crown's radius (98 % of the vertices lie within it) and the trunk's
    radius at the ground, all from the pivot at the root."""
    positions = np.concatenate([p.positions for p in pieces])
    top, low = float(positions[:, 2].max()), float(positions[:, 2].min())
    flat = np.hypot(positions[:, 0], positions[:, 1])
    wood = [p.positions for p in pieces if not p.leaf]
    trunk = .15
    if wood:
        w = np.concatenate(wood)
        # the wood within the lowest tenth of the height, off the root flare
        band = w[(w[:, 2] > low + .04 * (top - low)) & (w[:, 2] < low + .12 * (top - low))]
        if len(band) < 3:
            # a coarse trunk has no ring there: its foot then
            band = w[w[:, 2] < low + .12 * (top - low)]
        if len(band) >= 3:
            trunk = float(np.percentile(np.hypot(band[:, 0], band[:, 1]), 90))
    return {'height': round(top, 3), 'bottom': round(low, 3), 'radius': round(float(np.percentile(flat, 98)), 3),
            'trunk': round(max(.02, trunk), 3)}


def wind(pieces, size):
    """Vertex colours for the game's wind (red: flutter, green: phase, blue: sway), from where a
    vertex stands on the plant. size: measure() of the most detailed level, so every level
    sways alike."""
    height = max(.1, size['height'])
    radius = max(.1, size['radius'])
    trunk = size['trunk']
    for piece in pieces:
        p = piece.positions
        flat = np.hypot(p[:, 0], p[:, 1])
        up = np.clip(p[:, 2] / height, 0, 1)
        # sway: none on the trunk's axis, more out along a branch and up the crown
        out = np.clip((flat - 1.5 * trunk) / radius, 0, 1)
        sway = np.clip(out ** .8 * (.35 + .65 * up), 0, 1)
        # phase: branches round the trunk and up it move out of step
        phase = (np.arctan2(p[:, 1], p[:, 0]) / (2 * math.pi) + .5 + up * 1.7) % 1
        if piece.leaf:
            flutter = np.clip(.45 + .55 * out, 0, 1)
            sway = np.clip(sway + .12, 0, 1)
        else:
            flutter = np.zeros(len(p))
        piece.colour = np.column_stack([flutter, phase, sway, np.ones(len(p))])


def lod_sizes(count, glb, height):
    """Pixel sizes of `count` levels, most detailed first: from the file's own distances where
    it names them, else the game's usual ones."""
    distances = None
    for holder in [glb.doc.get('asset', {}), glb.doc] + glb.doc.get('scenes', []) + glb.doc.get('nodes', []):
        extras = holder.get('extras') if isinstance(holder, dict) else None
        if isinstance(extras, dict):
            for name in ('lodDistances', 'lod_distances', 'lodDistance', 'lods', 'lod'):
                value = extras.get(name)
                if isinstance(value, list) and value and all(isinstance(v, (int, float)) for v in value):
                    distances = [float(v) for v in value]
                    break
        if distances:
            break
    if distances and len(distances) >= count - 1:
        # distances[k]: where level k gives way to level k + 1; the last level runs to the billboard
        sizes = [max(BILLBOARD_PX + 10, int(round(height * PX_AT_1M / max(1., d)))) for d in distances[:count]]
        sizes = sizes[:count] + [max(BILLBOARD_PX + 10, sizes[-1] // 2)] * (count - len(sizes))
        fixed = []
        for size in sizes:
            fixed.append(min(size, fixed[-1] - 10) if fixed else size)
        if fixed[-1] > BILLBOARD_PX:
            return fixed
    return list(LOD_PX.get(count) or [max(40, 700 - k * (660 // max(1, count - 1))) for k in range(count)])


def _texture_name(image, kind):
    data = image.tobytes()
    return f't_{hashlib.sha256(data).hexdigest()[:10]}_{kind}'


def _save(image, folder, stem, suffix, alpha_ref=None):
    """A texture as PNG and DDS (the game loads the DDS when it is there). Returns the file name."""
    name = f'{stem}.{suffix}.png'
    path = folder / name
    if not path.exists():
        image.save(path)
        try:
            import fast_dds
            side = 1 << (max(image.size).bit_length() - 1)
            if image.size == (side, side) and side >= 4:
                fast_dds.save(image, path.with_suffix('.dds'), alpha_ref=alpha_ref)
        except Exception:
            # the PNG alone works: the game cooks it at first use
            pass
    return name


def materials(glb, pieces_by_lod, folder, species, vfs):
    """Material definitions for the pieces' glTF materials: {name: definition}, and
    {(gltf material, part): name}. Textures are written into `folder` once each."""
    out, names = {}, {}
    doc = glb.doc
    used = {}
    for pieces in pieces_by_lod.values():
        for piece in pieces:
            used.setdefault((piece.material, piece.leaf), piece.part)
    for (index, leaf), part in sorted(used.items(), key=lambda kv: (kv[0][0] is None, kv[0][0] or 0, kv[0][1])):
        source = doc['materials'][index] if index is not None else {}
        pbr = source.get('pbrMetallicRoughness', {})
        stage = {'roughnessFactor': pbr.get('roughnessFactor', .85 if leaf else .95), 'metallicFactor': 0.}
        factor = pbr.get('baseColorFactor')
        if factor:
            stage['baseColorFactor'] = list(factor)
        cut = leaf or source.get('alphaMode') in ('MASK', 'BLEND')
        ref = int(round(source.get('alphaCutoff', .5) * 255))
        key = hashlib.sha256()

        def image_of(spec):
            tex = doc['textures'][spec['index']]
            which = tex.get('source')
            for extension in ('EXT_texture_webp', 'EXT_texture_avif', 'KHR_texture_basisu'):
                if which is None:
                    which = tex.get('extensions', {}).get(extension, {}).get('source')
            return glb.image(which)

        if 'baseColorTexture' in pbr:
            image = image_of(pbr['baseColorTexture'])
            if cut and image.mode in ('RGBA', 'LA', 'PA'):
                image = image.convert('RGBA')
                rgb = image.convert('RGB')
                stem = _texture_name(image, 'b')
                # colour without a matte line at the cut: the mip chain keeps the leaves' share
                stage['baseColorMap'] = f'{vfs}/' + _save(image, folder, stem, 'color', alpha_ref=ref)
                stage['opacityMap'] = f'{vfs}/' + _save(image.getchannel('A'), folder, stem + '_o', 'data')
                del rgb
            else:
                image = image.convert('RGB')
                stage['baseColorMap'] = f'{vfs}/' + _save(image, folder, _texture_name(image, 'b'), 'color')
            key.update(stage['baseColorMap'].encode())
        if 'normalTexture' in source:
            image = image_of(source['normalTexture']).convert('RGB')
            stage['normalMap'] = f'{vfs}/' + _save(image, folder, _texture_name(image, 'nm'), 'normal')
            key.update(stage['normalMap'].encode())
        if 'metallicRoughnessTexture' in pbr:
            image = image_of(pbr['metallicRoughnessTexture']).convert('RGB').getchannel('G')
            stage['roughnessMap'] = f'{vfs}/' + _save(image, folder, _texture_name(image, 'r'), 'data')
            stage['roughnessFactor'] = pbr.get('roughnessFactor', 1.)
        if 'occlusionTexture' in source:
            image = image_of(source['occlusionTexture']).convert('RGB').getchannel('R')
            stage['ambientOcclusionMap'] = f'{vfs}/' + _save(image, folder, _texture_name(image, 'ao'), 'data')
        base = 'leaves' if leaf else re.sub(r'[^a-z0-9]', '', (part or 'bark').lower()) or 'bark'
        # variants of a species share a material when they share its textures
        name = f'e2rfl_{species}_{base}_{key.hexdigest()[:6]}'
        material = {'name': name, 'mapTo': name, 'class': 'Material', 'version': 1.5,
                    'Stages': [stage, {}, {}, {}], 'persistentId': hashlib.md5(name.encode()).hexdigest(),
                    'annotation': 'NATURE', 'materialTag0': 'earthng', 'materialTag1': 'vegetation',
                    'groundType': 'GRASS' if leaf else 'WOOD'}
        if cut:
            material.update(alphaTest=True, alphaRef=ref, doubleSided=True, translucentZWrite=True)
        elif source.get('doubleSided'):
            material['doubleSided'] = True
        out[name] = material
        names[(index, leaf)] = name
    return out, names


def trunk_prism(size, height=None, sides=6):
    """The collision: a prism round the trunk from the ground to `height` (a third of the tree)."""
    r = size['trunk'] * 1.05
    top = height or max(1.5, size['height'] * .33)
    ring = [(r * math.cos(2 * math.pi * k / sides), r * math.sin(2 * math.pi * k / sides)) for k in range(sides)]
    positions = [(x, y, size['bottom']) for x, y in ring] + [(x, y, top) for x, y in ring]
    faces = []
    for k in range(sides):
        n = (k + 1) % sides
        faces += [(k, n, sides + n), (k, sides + n, sides + k)]
    for k in range(1, sides - 1):
        faces += [(0, k + 1, k), (sides, sides + k, sides + k + 1)]
    return np.array(positions, dtype=float), np.array(faces, dtype=np.int64)


def collada(name, lods, sizes, names, collision=None, billboard=BILLBOARD_PX):
    """The shape: lods [[Piece]] most detailed first, sizes their pixel sizes."""
    ET.register_namespace('', NS)

    def add(parent, tag, text=None, **attrs):
        node = ET.SubElement(parent, f'{{{NS}}}{tag}', {k: str(v) for k, v in attrs.items()})
        node.text = text
        return node

    root = ET.Element(f'{{{NS}}}COLLADA', version='1.4.1')
    asset = add(root, 'asset')
    add(asset, 'unit', name='meter', meter='1')
    add(asset, 'up_axis', 'Z_UP')
    effects, mats = add(root, 'library_effects'), add(root, 'library_materials')
    for label in sorted(set(names.values())):
        effect = add(effects, 'effect', id=f'{label}-fx')
        technique = add(add(effect, 'profile_COMMON'), 'technique', sid='common')
        add(add(add(technique, 'lambert'), 'diffuse'), 'color', '1 1 1 1')
        add(add(mats, 'material', id=label, name=label), 'instance_effect', url=f'#{label}-fx')
    geometries = add(root, 'library_geometries')
    visual = add(add(root, 'library_visual_scenes'), 'visual_scene', id='Scene')
    base = add(visual, 'node', id='base00', name='base00', type='NODE')
    start = add(base, 'node', id='start01', name='start01', type='NODE')

    def floats(values, digits):
        return ' '.join(format(float(v), f'.{digits}g') for v in np.asarray(values).ravel())

    def geometry(gid, groups):
        """groups: [(material or None, positions, normals, uv, colour, faces)] -> one geometry."""
        mesh = add(add(geometries, 'geometry', id=gid, name=gid), 'mesh')
        positions = np.concatenate([g[1] for g in groups])
        normals = np.concatenate([g[2] for g in groups])
        uvs = np.concatenate([g[3] if g[3] is not None else np.zeros((len(g[1]), 2)) for g in groups])
        colours = (np.concatenate([g[4] if g[4] is not None else np.ones((len(g[1]), 4)) for g in groups])
                   if any(g[4] is not None for g in groups) else None)

        def source(suffix, array, params, digits):
            sid = f'{gid}-{suffix}'
            src = add(mesh, 'source', id=sid)
            add(src, 'float_array', floats(array, digits), id=f'{sid}-array', count=array.size)
            accessor = add(add(src, 'technique_common'), 'accessor', source=f'#{sid}-array',
                           count=len(array), stride=len(params))
            for param in params:
                add(accessor, 'param', name=param, type='float')

        source('pos', positions, 'XYZ', 7)
        source('nrm', normals, 'XYZ', 4)
        source('uv', uvs, 'ST', 6)
        if colours is not None:
            source('col', colours, 'RGBA', 4)
        add(add(mesh, 'vertices', id=f'{gid}-vtx'), 'input', semantic='POSITION', source=f'#{gid}-pos')
        offset, used = 0, []
        for material, pos, _, _, _, faces in groups:
            attrs = {'count': len(faces)}
            if material:
                attrs['material'] = material
                used.append(material)
            triangles = add(mesh, 'triangles', **attrs)
            add(triangles, 'input', semantic='VERTEX', source=f'#{gid}-vtx', offset=0)
            add(triangles, 'input', semantic='NORMAL', source=f'#{gid}-nrm', offset=0)
            add(triangles, 'input', semantic='TEXCOORD', source=f'#{gid}-uv', offset=0, set=0)
            if colours is not None:
                add(triangles, 'input', semantic='COLOR', source=f'#{gid}-col', offset=0, set=0)
            add(triangles, 'p', ' '.join(map(str, (faces + offset).ravel())))
            offset += len(pos)
        return used

    def instance(parent, node_name, gid, used):
        node = add(parent, 'node', id=node_name, name=node_name, type='NODE')
        inst = add(node, 'instance_geometry', url=f'#{gid}')
        if used:
            bind = add(add(inst, 'bind_material'), 'technique_common')
            for label in dict.fromkeys(used):
                entry = add(bind, 'instance_material', symbol=label, target=f'#{label}')
                add(entry, 'bind_vertex_input', semantic='UVMap', input_semantic='TEXCOORD', input_set=0)

    if collision is not None:
        positions, faces = collision
        used = geometry('col', [(None, positions, vertex_normals(positions, faces), None, None, faces)])
        instance(start, 'Colmesh-1', 'col', used)
    for level, (pieces, size) in enumerate(zip(lods, sizes)):
        groups = {}
        for piece in pieces:
            groups.setdefault(names[(piece.material, piece.leaf)], []).append(piece)
        merged = []
        for label, group in groups.items():
            offset, faces = 0, []
            for piece in group:
                faces.append(piece.faces + offset)
                offset += len(piece.positions)
            merged.append((label, np.concatenate([p.positions for p in group]), np.concatenate([p.normals for p in group]),
                           np.concatenate([p.uv if p.uv is not None else np.zeros((len(p.positions), 2)) for p in group]),
                           np.concatenate([p.colour if p.colour is not None else np.ones((len(p.positions), 4)) for p in group]),
                           np.concatenate(faces)))
        used = geometry(f'lod{level}', merged)
        instance(start, f'{name}_a{size}', f'lod{level}', used)
    if billboard:
        add(base, 'node', id=f'bb_autobillboard{billboard}', name=f'bb_autobillboard{billboard}', type='NODE')
    add(add(root, 'scene'), 'instance_visual_scene', url='#Scene')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def convert(path, out, species, name=None, group='trees', billboard=BILLBOARD_PX):
    """Write <out>/art/shapes/earthng/flora/<group>/<species>/<name>.dae with its textures and
    materials; return the model's manifest entry {shape, materials, height, radius, trunk,
    triangles, source}."""
    path = Path(path)
    if not re.fullmatch(r'[a-z][a-z0-9_]*', species):
        raise ValueError(f'not a species name: {species!r}')
    name = name or path.stem
    if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
        raise ValueError(f'not a shape name: {name!r}')
    glb = GLB(path)
    by_lod = levels(glb)
    order = sorted(by_lod)
    size = measure(by_lod[order[0]])
    for lod in order:
        wind(by_lod[lod], size)
    vfs = f'{ROOT}/{group}/{species}'
    folder = Path(out) / vfs.lstrip('/')
    folder.mkdir(parents=True, exist_ok=True)
    defs, names = materials(glb, by_lod, folder, species, vfs)
    sizes = lod_sizes(len(order), glb, size['height'])
    # a plant without wood (grass, a fern) has no trunk to hit
    woody = any(not piece.leaf for piece in by_lod[order[0]]) and size['height'] > 2.5
    dae = collada(name, [by_lod[lod] for lod in order], sizes, names,
                  collision=trunk_prism(size) if woody else None, billboard=billboard)
    (folder / f'{name}.dae').write_bytes(dae)
    file = folder / 'main.materials.json'
    known = json.loads(file.read_text(encoding='utf8')) if file.exists() else {}
    known.update(defs)
    file.write_text(json.dumps(dict(sorted(known.items())), indent=1), encoding='utf8')
    return {'shape': f'{vfs}/{name}.dae', 'materials': f'{vfs}/main.materials.json', 'height': size['height'],
            'radius': size['radius'], 'trunk': size['trunk'], 'lods': sizes,
            'triangles': [int(sum(len(p.faces) for p in by_lod[lod])) for lod in order],
            'source': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('input', type=Path)
    parser.add_argument('--species', required=True)
    parser.add_argument('--name')
    parser.add_argument('--group', default='trees')
    parser.add_argument('--out', type=Path, required=True, help="the flora pack's root (holds art/)")
    a = parser.parse_args()
    print(json.dumps(convert(a.input, a.out, a.species, a.name, a.group), indent=2))


if __name__ == '__main__':
    main()
