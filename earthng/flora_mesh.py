"""A FoliMesh GLB as a BeamNG tree: one Collada shape with its levels of detail and a billboard.

A FoliMesh export (earthng/folimesh.py) holds a plant's levels of detail as separate nodes,
`<species>_s<variant>_LOD<n>_bark` and `..._leaves` (a second bark material is `..._bark2`), with
photo textures of bark and leaves and their normal maps. Its root node's `extras.alardonTree`
lists the levels with the distance each is made for and the trunk's collision as capsules. The
game wants what its own trees are (east_coast_usa/art/shapes/trees/*):

  base00
    start01
      <name>_a<size>     one node a level of detail: drawn while the tree is at least <size> px tall
      Colmesh-1          the trunk
    bb_autobillboard<size>   the game bakes an imposter and draws it under the last level

with one geometry a level (a triangle group a material) and vertex colours that carry the wind
(shaders/common/wind.hlsl, GPU Gems 3 ch. 16): red is how much a vertex flutters (a leaf's
edge), green the phase of its branch, blue how much it sways with the branch; the trunk's bend
comes from the height. A FoliMesh model carries the same three in its second and third texture
coordinates (TEXCOORD_1: height up the plant, way out along the branch; TEXCOORD_2: flutter,
phase); the wind is taken from those, and laid from the geometry for a file without them.

Its own vertex colour is a tint over the texture: mostly grey shade, but a rowan's berries, a
fly agaric's cap and a log's moss are coloured by nothing else. The game's vertex colour is the
wind's, so a part whose tint has colour in it is cut into a few groups of faces of one tint each
(TINT), and each group is a material of its own with that tint as its colour factor. The grey
shade is left out.

What a level costs decides when it is drawn, not the distance the file names for it: FoliMesh's
levels are made for a tree looked at (its level 0 is 30-200 thousand triangles, the game's own
oak 5 thousand), and a wood is thousands of them. A level is drawn once the plant is
LOD.px * sqrt(its triangles) px tall, less for a small plant. Level 0 loses its thinnest twigs
first (HERO.wood triangles of wood are kept) and is left out when it is still over HERO.most.

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
# A level's size in pixels of the plant's height on screen: px * sqrt(triangles), times `small`
# for a plant up to `low` m tall and 1 from `tall` m (a wood's trees are counted in thousands, an
# agave is one of a few). The game's own oak has 5200 triangles from 1000 px and 2500 at 200.
# least: the last level's size; step: the least gap between two levels; same: a level with more
# than this share of the triangles of the one before it is not worth a switch.
LOD = {'px': 4., 'small': .35, 'low': 2.8, 'tall': 8., 'least': 45, 'step': 20, 'most': 1100, 'same': .8}
# The sizes of a file without triangle counts worth a rule (one level, or a test's prism).
LOD_PX = {1: (250,), 2: (500, 200), 3: (700, 380, 150), 4: (700, 400, 190, 70)}
BILLBOARD_PX = 25
# Level 0 as the game can afford it: `wood` triangles of bark (the thickest parts first), and no
# level 0 at all when it still has more than `most` triangles.
HERO = {'wood': 24000, 'most': 80000}
LEAF_PARTS = ('leaves', 'leaf', 'needles', 'foliage', 'fronds', 'petals', 'flowers', 'blades')
PART_RE = re.compile(r'(?:^|_)LOD(\d)(?:_([A-Za-z]+))?', re.I)
# A part's tint as materials: faces whose tint has less colour than `grey` keep the plain
# material; the rest fall into bins of 1 / `grid` a channel, the `most` biggest of them kept and
# every other face given to the nearest. A group's tint is rounded to 1 / `round`, so the levels
# of a model (and its variants) come to the same few materials. A green tint (green over red
# and blue by `moss`) is moss: over a bark texture it is dark by the texture; on a part of one
# flat colour (a stump's cut, a log's end) it would be lime, and is taken down to `dark` of itself.
TINT = {'grey': .06, 'grid': 4, 'most': 4, 'round': 16, 'moss': .15, 'dark': .22}
# Bark as the game lights it: FoliMesh's bark is pale, and the baked shade its vertex colours
# darken it with is not kept (the game's own oak bark has a factor of .86 and an occlusion map
# over it). The first game run stood a wood of white trunks (out/flora/game-01).
BARK = .68
# A tree's patch: a part of one flat colour with under `share` of its level's wood triangles, on
# a plant over `tall` m. FoliMesh lays moss on a trunk as a few such triangles a hair over the
# bark; in the game they fight the bark for depth and read as brown stripes on every oak
# (out/flora/game-08). They are left out.
PATCH = {'share': .02, 'tall': 3.}
# The side of the plain white map a flat-colour material is given (the game imports nothing
# under 16; 64 as its own smallest textures are).
PLAIN = 64
# Leaves light through and are lit on their back as on their face, as the game's own are.
LEAF_MATERIAL = {'doubleSided': True, 'translucentZWrite': True, 'invertBackFaceNormals': True, 'subSurface': True,
                 'subSurfaceIntensity': .35}


class Piece:
    """One primitive of one level: arrays in the game's frame (Z up, metres). uv1, uv2: the
    file's second and third texture coordinates (its wind data), or None. tint: the file's
    vertex colours (linear RGB a vertex), or None. shade: the one tint of all its faces (a
    group cut by tinted()), or None for the plain material."""

    def __init__(self, positions, normals, uv, faces, material, part, uv1=None, uv2=None, tint=None):
        self.positions, self.normals, self.uv, self.faces = positions, normals, uv, faces
        self.material, self.part, self.uv1, self.uv2, self.tint = material, part, uv1, uv2, tint
        self.colour, self.shade = None, None

    @property
    def leaf(self):
        return self.part in LEAF_PARTS


def tree_extras(glb):
    """The generator's own notes on the model (`extras.alardonTree` of a node), or {}."""
    for node in glb.doc.get('nodes', []):
        extras = node.get('extras')
        if isinstance(extras, dict) and isinstance(extras.get('alardonTree'), dict) and 'lods' in extras['alardonTree']:
            return extras['alardonTree']
    return {}


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
        extra = [glb.accessor(attrs[name]).astype(float) if name in attrs else None for name in ('TEXCOORD_1', 'TEXCOORD_2')]
        extra = [e if e is not None and e.shape == (count, 2) else None for e in extra]
        tint = glb.accessor(attrs['COLOR_0']).astype(float) if 'COLOR_0' in attrs else None
        tint = tint[:, :3] if tint is not None and tint.ndim == 2 and tint.shape[0] == count and tint.shape[1] >= 3 else None
        material = source.get('material')
        here = part
        if here is None and material is not None:
            # no part in the node's name: the material says (a cut-out is foliage)
            m = doc['materials'][material]
            here = 'leaves' if m.get('alphaMode') in ('MASK', 'BLEND') else 'bark'
        yield Piece(positions, normals, uv, faces, material, here or 'bark', extra[0], extra[1], tint)


def measure(pieces):
    """A level's height, its crown's radius (98 % of the vertices lie within it) and the trunk's
    radius at the ground, all from the pivot at the root; `branch`: the farthest way out along a
    branch in the file's own measure (TEXCOORD_1's second number), 0 without it."""
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
    out = [p.uv1[:, 1] for p in pieces if p.uv1 is not None and p.uv2 is not None]
    branch = float(np.percentile(np.concatenate(out), 98)) if out else 0.
    return {'height': round(top, 3), 'bottom': round(low, 3), 'radius': round(float(np.percentile(flat, 98)), 3),
            'trunk': round(max(.02, trunk), 3), 'branch': round(branch, 4)}


def wind(pieces, size):
    """Vertex colours for the game's wind (red: flutter, green: phase, blue: sway). From the
    file's own wind data where a piece has it, else from where a vertex stands on the plant.
    size: measure() of the most detailed level, so every level sways alike."""
    height = max(.1, size['height'])
    radius = max(.1, size['radius'])
    trunk = size['trunk']
    reach = size.get('branch') or 0
    for piece in pieces:
        p = piece.positions
        if piece.uv1 is not None and piece.uv2 is not None and reach > 1e-3:
            # the file's own: how far out along its branch a vertex is, its flutter and its phase
            sway = np.clip(piece.uv1[:, 1] / reach, 0, 1) ** .8
            flutter = np.clip(piece.uv2[:, 0], 0, 1)
            phase = piece.uv2[:, 1] % 1
            if piece.leaf:
                sway = np.clip(sway + .08, 0, 1)
            piece.colour = np.column_stack([flutter, phase, sway, np.ones(len(p))])
            continue
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


def parts(positions, faces):
    """The connected part each face belongs to (vertices welded by place): an array of labels."""
    _, inverse = np.unique(np.round(positions * 2000).astype(np.int64), axis=0, return_inverse=True)
    welded = inverse.ravel()[faces]
    label = np.arange(int(welded.max()) + 1)
    a = np.concatenate([welded[:, 0], welded[:, 1], welded[:, 2]])
    b = np.concatenate([welded[:, 1], welded[:, 2], welded[:, 0]])
    while True:
        low = np.minimum(label[a], label[b])
        new = label.copy()
        np.minimum.at(new, a, low)
        np.minimum.at(new, b, low)
        # every vertex to its label's label: a branch's long tube closes in a few rounds
        while True:
            hop = new[new]
            if np.array_equal(hop, new):
                break
            new = hop
        if np.array_equal(new, label):
            return label[welded[:, 0]]
        label = new


def thin(pieces, budget):
    """A level's wood within `budget` triangles: its connected parts (a branch is a tube of its
    own) from the thickest down, the twigs left out. Returns the pieces, the leaves untouched."""
    wood = [p for p in pieces if not p.leaf]
    if sum(len(p.faces) for p in wood) <= budget:
        return pieces
    found = []
    for index, piece in enumerate(wood):
        labels = parts(piece.positions, piece.faces)
        a, b, c = (piece.positions[piece.faces[:, k]] for k in range(3))
        areas = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
        centres = (a + b + c) / 3
        for label in np.unique(labels):
            own = labels == label
            span = centres[own]
            length = float(np.linalg.norm(span.max(axis=0) - span.min(axis=0))) + 1e-6
            # a tube's radius: its area over its length round
            found.append((float(areas[own].sum()) / (2 * math.pi * length), int(own.sum()), index, label, labels))
    found.sort(key=lambda part: (-part[0], -part[1]))
    keep = {index: np.zeros(len(piece.faces), dtype=bool) for index, piece in enumerate(wood)}
    left = budget
    for position, (_, count, index, label, labels) in enumerate(found):
        if position and count > left:
            continue
        keep[index] |= labels == label
        left -= count
    out = [p for p in pieces if p.leaf]
    for index, piece in enumerate(wood):
        if keep[index].any():
            piece.faces = piece.faces[keep[index]]
            out.append(piece)
    return out


def tinted(pieces):
    """The pieces with every part whose tint has colour in it cut into groups of faces of one
    tint each (TINT): [Piece], a group's `shade` its tint. A part of grey shade alone is kept."""
    out = []
    for piece in pieces:
        if piece.tint is None or not len(piece.faces):
            out.append(piece)
            continue
        face = piece.tint[piece.faces].mean(axis=1)
        coloured = face.max(axis=1) - face.min(axis=1) >= TINT['grey']
        if not coloured.any():
            out.append(piece)
            continue
        bins = np.where(coloured[:, None], np.round(face * TINT['grid']), -1).astype(int)
        keys, inverse, counts = np.unique(bins, axis=0, return_inverse=True, return_counts=True)
        inverse = inverse.ravel()
        kept = np.argsort(-counts, kind='stable')[:TINT['most']]
        centres = np.array([face[inverse == k].mean(axis=0) for k in kept])
        # a face of a bin that is not kept: the nearest tint of those that are
        nearest = np.argmin(((face[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2), axis=1)
        slot = {int(k): n for n, k in enumerate(kept)}
        group = np.array([slot.get(int(k), -1) for k in inverse])
        group = np.where(group < 0, nearest, group)
        for n, k in enumerate(kept):
            own = group == n
            if not own.any():
                continue
            part = Piece(piece.positions, piece.normals, piece.uv, piece.faces[own], piece.material, piece.part,
                         piece.uv1, piece.uv2, piece.tint)
            part.colour = piece.colour
            # (the grey bin is the plain material: shade is not a colour)
            part.shade = None if keys[k][0] < 0 else tuple(
                round(float(v) * TINT['round']) / TINT['round'] for v in face[own].mean(axis=0))
            out.append(part)
    return out


def unpatched(glb, pieces, height):
    """The pieces without a tree's patches (PATCH)."""
    if height <= PATCH['tall']:
        return pieces
    wood = sum(len(p.faces) for p in pieces if not p.leaf)
    out = []
    for piece in pieces:
        material = glb.doc['materials'][piece.material] if piece.material is not None else {}
        flat = 'baseColorTexture' not in material.get('pbrMetallicRoughness', {})
        if not piece.leaf and flat and len(piece.faces) < PATCH['share'] * wood:
            continue
        out.append(piece)
    return out


def choose(by_lod, hero=True):
    """The levels the game gets, most detailed first: [(file's level, [Piece])]. Level 0 thinned
    to what the game affords or left out; a level about as heavy as the one before it left out."""
    order = sorted(by_lod)
    chosen = []
    for position, lod in enumerate(order):
        pieces = by_lod[lod]
        if position == 0 and len(order) > 1:
            if not hero:
                continue
            pieces = thin(pieces, HERO['wood'])
            if sum(len(p.faces) for p in pieces) > HERO['most']:
                continue
        count = sum(len(p.faces) for p in pieces)
        if chosen and count > LOD['same'] * sum(len(p.faces) for p in chosen[-1][1]):
            continue
        chosen.append((lod, pieces))
    return [(lod, tinted(pieces)) for lod, pieces in chosen]


def lod_sizes(triangles, height):
    """Pixel sizes of the levels, most detailed first, from their triangle counts and the plant's
    height in metres (LOD)."""
    count = len(triangles)
    if count == 1 or max(triangles) < 64:
        return list(LOD_PX.get(count) or [max(40, 700 - k * (660 // max(1, count - 1))) for k in range(count)])
    t = min(1., max(0., (height - LOD['low']) / (LOD['tall'] - LOD['low'])))
    factor = LOD['px'] * (LOD['small'] + (1 - LOD['small']) * t)
    sizes = [int(round(min(LOD['most'], factor * math.sqrt(n)))) for n in triangles]
    # from the last level up: it is at least `least`, every one before it `step` more
    sizes[-1] = max(LOD['least'], sizes[-1])
    for k in range(count - 2, -1, -1):
        sizes[k] = max(sizes[k], sizes[k + 1] + LOD['step'])
    return sizes


def _texture_name(image, kind):
    data = image.tobytes()
    return f't_{hashlib.sha256(data).hexdigest()[:10]}_{kind}'


def power_of_two(image):
    """The image with each side a power of two, at least 16: the game imports nothing else
    ("Size must be a power of two and at least 16x16": a 1024 x 1536 leaf atlas came out as the
    pink IMPORT FAILED texture on every pine, out/flora/game-01). A side goes down to the power
    under it unless it is within a tenth of the one above."""
    def side(n):
        low = 1 << (max(1, n).bit_length() - 1)
        return max(16, low * 2 if n >= low * 1.8 else low)
    size = (side(image.size[0]), side(image.size[1]))
    return image if size == image.size else image.resize(size, Image.LANCZOS)


def _save(image, folder, stem, suffix, alpha_ref=None):
    """A texture as PNG and DDS (the game loads the DDS when it is there). Returns the file name."""
    name = f'{stem}.{suffix}.png'
    path = folder / name
    if not path.exists():
        image = power_of_two(image)
        image.save(path)
        try:
            import fast_dds
            fast_dds.save(image, path.with_suffix('.dds'), alpha_ref=alpha_ref)
        except Exception:
            # the PNG alone works: the game cooks it at first use
            pass
    return name


def srgb(linear):
    """A glTF colour factor (linear) as the game reads a material's baseColorFactor (sRGB)."""
    out = []
    for value in list(linear)[:3]:
        v = min(1., max(0., float(value)))
        out.append(round(12.92 * v if v <= .0031308 else 1.055 * v ** (1 / 2.4) - .055, 4))
    return out + [float(linear[3]) if len(linear) > 3 else 1.]


def materials(glb, pieces_by_lod, folder, species, vfs):
    """Material definitions for the pieces' glTF materials: {name: definition}, and
    {(gltf material, part): name}. Textures are written into `folder` once each."""
    out, names = {}, {}
    doc = glb.doc
    used = {}
    for pieces in pieces_by_lod.values():
        for piece in pieces:
            used.setdefault((piece.material, piece.leaf, piece.shade), piece.part)
    for (index, leaf, shade), part in sorted(used.items(), key=lambda kv: (kv[0][0] is None, kv[0][0] or 0, kv[0][1],
                                                                          kv[0][2] is not None, kv[0][2] or ())):
        source = doc['materials'][index] if index is not None else {}
        pbr = source.get('pbrMetallicRoughness', {})
        stage = {'roughnessFactor': pbr.get('roughnessFactor', .85 if leaf else .95), 'metallicFactor': 0.}
        key = hashlib.sha256()
        factor = pbr.get('baseColorFactor')
        if shade:
            tint = list(shade)
            if 'baseColorTexture' not in pbr and tint[1] > tint[0] + TINT['moss'] and tint[1] > tint[2] + TINT['moss']:
                tint = [value * TINT['dark'] for value in tint]
            # the group's tint over the material's own colour (both linear)
            factor = [a * b for a, b in zip((list(factor) if factor else [1., 1., 1.])[:3], tint)] + [1.]
        if not leaf and 'baseColorTexture' in pbr:
            factor = [value * BARK for value in (list(factor) if factor else [1., 1., 1.])[:3]] + [1.]
        if factor:
            stage['baseColorFactor'] = srgb(factor)
            key.update(json.dumps(stage['baseColorFactor']).encode())
        if 'baseColorTexture' not in pbr:
            # a material of one flat colour still needs a colour map: without any the game draws
            # its orange NoMaterial hatch (the moss patches on the oaks, out/flora/game-01)
            stage['baseColorMap'] = f'{vfs}/' + _save(Image.new('RGB', (PLAIN, PLAIN), (255, 255, 255)), folder, 't_plain_b', 'color')
        cut = leaf or source.get('alphaMode') in ('MASK', 'BLEND')
        ref = int(round(source.get('alphaCutoff', .5) * 255))

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
                stem = _texture_name(image, 'b')
                # colour without a matte line at the cut: the mip chain keeps the leaves' share
                stage['baseColorMap'] = f'{vfs}/' + _save(bleed(image), folder, stem, 'color')
                stage['opacityMap'] = f'{vfs}/' + _save(image.getchannel('A'), folder, stem + '_o', 'data', alpha_ref=ref)
            else:
                cut = cut and leaf
                image = image.convert('RGB')
                stage['baseColorMap'] = f'{vfs}/' + _save(image, folder, _texture_name(image, 'b'), 'color')
            key.update(stage['baseColorMap'].encode())
        if 'normalTexture' in source:
            # glTF's normal map has green up; the game's has it down
            r, g, b = image_of(source['normalTexture']).convert('RGB').split()
            image = Image.merge('RGB', (r, g.point(lambda v: 255 - v), b))
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
            material.update(alphaTest=True, alphaRef=ref, **LEAF_MATERIAL)
        elif source.get('doubleSided'):
            material['doubleSided'] = True
        out[name] = material
        names[(index, leaf, shade)] = name
    return out, names


def bleed(image, rounds=6):
    """A cut-out's colour spread into what is cut away, so a mip does not mix a leaf's edge with
    whatever colour the file left there (a pale or dark line round every leaf from afar)."""
    rgba = np.asarray(image.convert('RGBA'), dtype=np.float32)
    colour, known = rgba[..., :3].copy(), rgba[..., 3] > 24
    if known.all() or not known.any():
        return image.convert('RGB')
    mean = colour[known].mean(axis=0)
    for _ in range(rounds):
        total = np.zeros_like(colour)
        weight = np.zeros(known.shape, dtype=np.float32)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            shifted = np.roll(known, (dy, dx), axis=(0, 1))
            total += np.roll(colour, (dy, dx), axis=(0, 1)) * shifted[..., None]
            weight += shifted
        grow = ~known & (weight > 0)
        colour[grow] = total[grow] / weight[grow][:, None]
        known = known | grow
    colour[~known] = mean
    return Image.fromarray(np.clip(colour, 0, 255).astype(np.uint8), 'RGB')


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


def capsule_prisms(capsules, sides=6, reach=6.):
    """The collision the file names: a prism round each capsule of the trunk (a leaning trunk is
    several), in the game's frame; None without usable capsules. Capsules that begin above
    `reach` m are not a car's concern."""
    turn = AXES[:3, :3]
    positions, faces = [], []
    for capsule in capsules or []:
        try:
            a, b = np.array(capsule['a'], dtype=float) @ turn.T, np.array(capsule['b'], dtype=float) @ turn.T
            radius = float(capsule['radius'])
        except (KeyError, TypeError, ValueError):
            continue
        if a.shape != (3,) or b.shape != (3,) or not radius > 0 or min(a[2], b[2]) > reach:
            continue
        axis = b - a
        length = float(np.linalg.norm(axis))
        if length < 1e-4:
            continue
        axis /= length
        side = np.cross(axis, (1., 0, 0) if abs(axis[0]) < .9 else (0., 1, 0))
        side /= np.linalg.norm(side)
        other = np.cross(axis, side)
        base = len(positions)
        for end in (a, b):
            for k in range(sides):
                t = 2 * math.pi * k / sides
                positions.append(end + radius * (math.cos(t) * side + math.sin(t) * other))
        for k in range(sides):
            n = (k + 1) % sides
            faces += [(base + k, base + n, base + sides + n), (base + k, base + sides + n, base + sides + k)]
        for k in range(1, sides - 1):
            faces += [(base, base + k + 1, base + k), (base + sides, base + sides + k, base + sides + k + 1)]
    if not faces:
        return None
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

        # (a tenth of a millimetre on a 30 m tree; the file is text, and a level 0 is 50,000 triangles)
        source('pos', positions, 'XYZ', 6)
        source('nrm', normals, 'XYZ', 3)
        source('uv', uvs, 'ST', 5)
        if colours is not None:
            source('col', colours, 'RGBA', 3)
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
            groups.setdefault(names[(piece.material, piece.leaf, piece.shade)], []).append(piece)
        merged = []
        for label, group in groups.items():
            # only the vertices a group's faces use: a thinned level leaves most of them behind
            arrays = []
            for piece in group:
                used_vertices, faces = np.unique(piece.faces, return_inverse=True)
                arrays.append((piece.positions[used_vertices], piece.normals[used_vertices],
                               piece.uv[used_vertices] if piece.uv is not None else np.zeros((len(used_vertices), 2)),
                               piece.colour[used_vertices] if piece.colour is not None else np.ones((len(used_vertices), 4)),
                               faces.reshape(-1, 3)))
            offset, faces = 0, []
            for one in arrays:
                faces.append(one[4] + offset)
                offset += len(one[0])
            merged.append((label, np.concatenate([one[0] for one in arrays]), np.concatenate([one[1] for one in arrays]),
                           np.concatenate([one[2] for one in arrays]), np.concatenate([one[3] for one in arrays]),
                           np.concatenate(faces)))
        used = geometry(f'lod{level}', merged)
        instance(start, f'{name}_a{size}', f'lod{level}', used)
    if billboard:
        add(base, 'node', id=f'bb_autobillboard{billboard}', name=f'bb_autobillboard{billboard}', type='NODE')
    add(add(root, 'scene'), 'instance_visual_scene', url='#Scene')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def convert(path, out, species, name=None, group='trees', billboard=BILLBOARD_PX, hero=True):
    """Write <out>/art/shapes/earthng/flora/<group>/<species>/<name>.dae with its textures and
    materials; return the model's manifest entry {shape, materials, height, radius, trunk, lods,
    triangles, levels (the file's levels kept), source}."""
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
    capsules = tree_extras(glb).get('collision')
    radii = [float(c['radius']) for c in capsules or [] if isinstance(c, dict) and isinstance(c.get('radius'), (int, float))]
    if radii:
        # the file's own trunk: a moss patch or a low bough beside it counts as wood in measure()
        size['trunk'] = round(max(.02, radii[0]), 3)
    for lod in order:
        wind(by_lod[lod], size)
    chosen = [(lod, unpatched(glb, pieces, size['height'])) for lod, pieces in choose(by_lod, hero)]
    kept = {lod: pieces for lod, pieces in chosen}
    vfs = f'{ROOT}/{group}/{species}'
    folder = Path(out) / vfs.lstrip('/')
    folder.mkdir(parents=True, exist_ok=True)
    defs, names = materials(glb, kept, folder, species, vfs)
    triangles = [int(sum(len(p.faces) for p in pieces)) for _, pieces in chosen]
    sizes = lod_sizes(triangles, size['height'])
    # a plant without wood (grass, a fern) has no trunk to hit
    woody = any(not piece.leaf for piece in by_lod[order[0]]) and size['height'] > 2.5
    collision = None
    if woody:
        collision = capsule_prisms(capsules) or trunk_prism(size)
    dae = collada(name, [pieces for _, pieces in chosen], sizes, names, collision=collision, billboard=billboard)
    (folder / f'{name}.dae').write_bytes(dae)
    file = folder / 'main.materials.json'
    known = json.loads(file.read_text(encoding='utf8')) if file.exists() else {}
    known.update(defs)
    file.write_text(json.dumps(dict(sorted(known.items())), indent=1), encoding='utf8')
    return {'shape': f'{vfs}/{name}.dae', 'materials': f'{vfs}/main.materials.json', 'height': size['height'],
            'radius': size['radius'], 'trunk': size['trunk'], 'lods': sizes, 'triangles': triangles,
            'levels': [lod for lod, _ in chosen], 'source': path.name,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('input', type=Path)
    parser.add_argument('--species', required=True)
    parser.add_argument('--name')
    parser.add_argument('--group', default='trees')
    parser.add_argument('--no-hero', action='store_true', help="leave the file's level 0 out")
    parser.add_argument('--out', type=Path, required=True, help="the flora pack's root (holds art/)")
    a = parser.parse_args()
    print(json.dumps(convert(a.input, a.out, a.species, a.name, a.group, hero=not a.no_hero), indent=2))


if __name__ == '__main__':
    main()
