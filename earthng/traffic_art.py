"""Flow cars and pedestrians made with fal: the models without physics (flow.lua, walkers.lua).

Sources are paid and kept in data/fal/traffic (every call is logged by `um` in fal_manifest.jsonl
there); nothing is generated without an explicit --generate. The steps, each skipped when its file
is there already:

    image   a concept picture (Nano Banana 2): one car or one person on a plain background
    mesh    the picture as a textured low-poly model (Tripo H3.1, face_limit)
    rig     a person's model rigged and animated (Meshy: a walk, an idle, a seated idle)

    .venv\\Scripts\\python.exe earthng\\traffic_art.py --generate [--only car_sedan,ped_man_a]
    .venv\\Scripts\\python.exe earthng\\traffic_art.py --build       (the shapes, without any call)

build() cooks the sources into data/traffic-art/<VERSION>: a Collada shape and its maps per model
(the cars' paint as an instance-colour mask, the people's walk as static pose shapes), which
level_files() puts into the planet next to the drawn shapes of flow_art.py and people_art.py. A
checkout without the sources builds a planet with the drawn shapes only.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import colorsys
import json
import math
from pathlib import Path
import shutil
import subprocess

import numpy as np
from PIL import Image, ImageFilter

import fal_mesh
import fast_dds

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / 'data' / 'fal' / 'traffic'
OUT = ROOT / 'data' / 'traffic-art'
VERSION = '2'          # change whenever a file this module cooks changes

IMAGE_MODEL = 'fal-ai/nano-banana-2'
MESH_MODEL = 'tripo3d/h3.1/image-to-3d'
RIG_MODEL = 'fal-ai/meshy/rigging/multi-animation'
# Meshy's animation library: Casual_Walk, Idle, Chair_Sit_Idle_M
WALK, IDLE, SIT = 30, 0, 33

# The paint is asked for in a colour no other part of a car has, so the texture's paint can be
# told from its lamps, glass and tyres by hue (cook: the paint becomes the instance colour's mask).
CAR_STYLE = (' Single car alone, centered, the entire car visible with a margin, three-quarter front view from slightly '
             'above, isolated on a plain pure white seamless background, flat even soft studio light, no ground shadow, '
             'no reflections of surroundings. Every painted body panel, both bumpers and the mirror caps in one matte '
             'solid uniform bright pure green paint (chroma key green). Every window is completely opaque glossy black glass: '
             'nothing of the interior is visible, no seats, no steering wheel. Black tyres with plain silver wheels, clear '
             'headlights, red tail lights, black grille. No brand badges, no logos, no text, no '
             'licence plate characters, no people. Photorealistic product render.')
# name: (flow body 1..4 as flow.lua BODIES, (length, width over the mirrors, height) m, faces,
# prompt). The size is the car's in the game: a model comes out tall and wide (a crossover 2.4 m
# across would not fit its lane) and is fitted to all three.
CARS = {
    'car_sedan': (1, (4.60, 2.04, 1.46), 2600, 'A generic 2015 mid-size four-door family sedan.'),
    'car_sedan_b': (1, (4.35, 1.92, 1.42), 2600, 'A generic boxy 1990s four-door compact sedan, an old modest East European city car.'),
    'car_hatch': (2, (4.05, 1.96, 1.47), 2600, 'A generic 2012 compact five-door hatchback city car.'),
    'car_hatch_b': (2, (3.70, 1.84, 1.50), 2600, 'A generic small 2008 three-door hatchback supermini.'),
    'car_suv': (3, (4.60, 2.06, 1.62), 2800, 'A generic 2018 compact crossover SUV.'),
    'car_suv_b': (3, (4.85, 2.18, 1.85), 2800, 'A generic large 2010 body-on-frame SUV, tall and square.'),
    'car_van': (4, (5.40, 2.28, 2.45), 3000, 'A generic high-roof passenger minibus van with a row of side windows, a city shuttle minibus.'),
    'car_van_b': (4, (5.00, 2.20, 1.95), 3000, 'A generic panel delivery van with a closed cargo body without side windows.'),
}

PED_STYLE = (' Full-body picture, standing straight in a relaxed A-pose: arms straight and held away from the body at '
             'about 35 degrees, hands open, legs slightly apart, facing the camera straight on, neutral face, the '
             'entire figure from head to shoes visible with a margin. Isolated on a plain light grey seamless '
             'background, flat even soft light, no shadow, nothing held in the hands, no bag. Photorealistic.')
# name: (height m, faces, prompt)
PEDS = {
    'ped_man_a': (1.80, 2400, 'An ordinary man of about 35 in a dark navy zipped jacket, blue jeans and grey sneakers.'),
    'ped_woman_a': (1.67, 2400, 'An ordinary woman of about 30 with shoulder-length brown hair in a short beige jacket, '
                    'black slim trousers and white sneakers.'),
    'ped_man_b': (1.76, 2400, 'An ordinary man of about 60 with grey hair in a brown short coat, dark grey trousers and '
                  'black shoes.'),
    'ped_woman_b': (1.62, 2400, 'An ordinary woman of about 60 with short grey hair in a dark red quilted jacket, dark '
                    'trousers and low brown boots.'),
    'ped_man_c': (1.83, 2400, 'A young man of about 20 in a grey hoodie, black joggers and white sneakers.'),
    'ped_woman_c': (1.70, 2400, 'A young woman of about 22 with long dark hair in a light blue denim jacket, black '
                    'leggings and white sneakers.'),
    'ped_man_d': (1.78, 2400, 'An ordinary man of about 45 in an olive green field jacket, dark jeans and brown boots.'),
    'ped_woman_d': (1.65, 2400, 'An ordinary woman of about 45 with blond hair tied back in a black short puffer jacket, '
                    'blue jeans and black ankle boots.'),
}


def um(*args):
    """One `um fal` call into SRC (it downloads the outputs and logs the call)."""
    exe = shutil.which('um')
    if not exe:
        raise SystemExit('`um` (universal-modder) is not on PATH: it makes and logs the fal calls')
    subprocess.run([exe, 'fal', *args], check=True, cwd=str(ROOT))


def found(folder, stem, suffixes):
    for suffix in suffixes:
        hit = sorted(folder.glob(stem + '*' + suffix))
        if hit:
            return hit[0]


def image(name, prompt):
    folder = SRC / 'img'
    hit = found(folder, name, ('.png', '.jpg', '.webp'))
    if not hit:
        um('image', prompt, '--out', str(folder), '--name', name, '--aspect', '4:3' if name.startswith('car') else '3:4')
        hit = found(folder, name, ('.png', '.jpg', '.webp'))
    return hit


def mesh(name, picture, faces):
    folder = SRC / 'mesh'
    hit = folder / f'{name}.glb'
    hit = hit if hit.is_file() else None
    if not hit:
        um('run', MESH_MODEL, f'image_url=@{picture}', f'face_limit:={faces}', 'pbr:=false', 'texture:=true',
           'texture_quality=standard', '--out', str(folder), '--name', name)
        hit = folder / f'{name}.glb'
    return hit


def facing_front(name, model):
    """The model turned to face glTF's +z, as a new GLB: Meshy fits its skeleton to a figure that
    faces +z, and a model that stood sideways got its arms' bones through its chest (the pilot).
    The figure's depth is the narrower of its two horizontal extents (it stands with its arms
    out); its front is where its feet reach out from its shins."""
    import io
    import struct
    target = SRC / 'mesh' / f'{name}_front.glb'
    if target.is_file():
        return target
    glb = fal_mesh.GLB(model)
    q = merged(glb.primitives())          # the game's axes: z up, uv with v up
    xy = q.positions[:, :2]
    _, across = min((np.ptp(xy @ np.array([math.cos(a), math.sin(a)])), a) for a in np.radians(np.arange(0, 180, .5)))
    depth = np.array([math.cos(across), math.sin(across)])
    z = (q.positions[:, 2] - q.positions[:, 2].min()) / np.ptp(q.positions[:, 2])
    feet, shins = xy[z < .03], xy[(z > .06) & (z < .16)]
    reach = (feet.mean(0) - shins.mean(0)) @ depth if len(feet) and len(shins) else 0
    if reach < 0:
        depth = -depth
    turn(q, -math.pi / 2 - math.atan2(depth[1], depth[0]))     # its front to -y: glTF's +z
    pos = np.stack([q.positions[:, 0], q.positions[:, 2], -q.positions[:, 1]], 1).astype('<f4')
    nrm = np.stack([q.normals[:, 0], q.normals[:, 2], -q.normals[:, 1]], 1).astype('<f4')
    uv = np.stack([q.uv[:, 0], 1 - q.uv[:, 1]], 1).astype('<f4')
    idx = q.faces.astype('<u4').ravel()
    picture = io.BytesIO()
    texture_of(glb).save(picture, format='JPEG', quality=94)
    chunks = [pos.tobytes(), nrm.tobytes(), uv.tobytes(), idx.tobytes(), picture.getvalue()]
    views, blob = [], b''
    for chunk in chunks:
        views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(chunk)})
        blob += chunk + bytes(1) * (-len(chunk) % 4)
    doc = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0, 'name': name}],
           'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2}, 'indices': 3, 'material': 0}]}],
           'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}, 'metallicFactor': 0, 'roughnessFactor': .9}}],
           'textures': [{'source': 0}], 'images': [{'bufferView': 4, 'mimeType': 'image/jpeg'}],
           'buffers': [{'byteLength': len(blob)}], 'bufferViews': views,
           'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': len(pos), 'type': 'VEC3',
                          'min': pos.min(0).tolist(), 'max': pos.max(0).tolist()},
                         {'bufferView': 1, 'componentType': 5126, 'count': len(nrm), 'type': 'VEC3'},
                         {'bufferView': 2, 'componentType': 5126, 'count': len(uv), 'type': 'VEC2'},
                         {'bufferView': 3, 'componentType': 5125, 'count': len(idx), 'type': 'SCALAR'}]}
    text = json.dumps(doc).encode()
    text += b' ' * (-len(text) % 4)
    target.write_bytes(struct.pack('<4sII', b'glTF', 2, 28 + len(text) + len(blob)) + struct.pack('<II', len(text), 0x4E4F534A)
                       + text + struct.pack('<II', len(blob), 0x004E4942) + blob)
    return target


def rig(name, model, height):
    folder = SRC / 'rig' / name
    if not found(folder, '', ('.glb',)):
        model = facing_front(name, model)
        um('run', RIG_MODEL, f'model_url=@{model}', f'height_meters:={height}',
           f'animation_action_ids:={json.dumps([WALK, IDLE, SIT])}', '--out', str(folder), '--name', name)
    return folder


def generate(only=None, stage='rig'):
    jobs = [(n, s[-1] + CAR_STYLE, s[2], None) for n, s in CARS.items()]
    jobs += [(n, s[-1] + PED_STYLE, s[1], s[0]) for n, s in PEDS.items()]
    if only:
        jobs = [j for j in jobs if j[0] in only]

    def one(job):
        name, prompt, faces, height = job
        picture = image(name, prompt)
        model = mesh(name, picture, faces)
        if height and stage == 'rig':
            rig(name, model, height)
        return name

    with ThreadPoolExecutor(4) as pool:
        for name in pool.map(one, jobs):
            print('done', name, flush=True)




# --- the cook: sources to shapes ------------------------------------------------------------------
FLOW_DIR, PEOPLE_DIR = 'art/flow', 'art/people'
CAR_MAT, PED_MAT = 'e2r_flowm_', 'e2r_pedm_'
MAP = 1024             # px of a model's maps
POSES = 8              # walk poses (walkers.lua M.POSES)
FAR_CELL = .11         # m: the vertex grid of a person's far shape


def merged(primitives):
    """One primitive of them all (a model here has one material)."""
    pos, nrm, uv, faces, at = [], [], [], [], 0
    for q in primitives:
        if q.uv is None:
            raise ValueError('a model without texture coordinates')
        pos.append(q.positions); nrm.append(q.normals); uv.append(q.uv); faces.append(q.faces + at)
        at += len(q.positions)
    return fal_mesh.Primitive(np.concatenate(pos), np.concatenate(nrm), np.concatenate(uv), np.concatenate(faces), 0)


def texture_of(glb):
    """The base colour map of the model's first textured material, RGB."""
    for material in glb.doc.get('materials', []):
        spec = material.get('pbrMetallicRoughness', {}).get('baseColorTexture')
        if spec:
            tex = glb.doc['textures'][spec['index']]
            index = tex.get('source')
            for extension in ('EXT_texture_webp', 'EXT_texture_avif'):
                if index is None:
                    index = tex.get('extensions', {}).get(extension, {}).get('source')
            return glb.image(index).convert('RGB')
    raise ValueError('a model without a base colour map')


def texels(image, uv):
    """The map's colour (0..1) at each texture coordinate (Collada's: v up)."""
    px = np.asarray(image, dtype=np.float32) / 255
    h, w = px.shape[:2]
    x = np.clip((uv[:, 0] % 1) * w, 0, w - 1).astype(int)
    y = np.clip((1 - uv[:, 1] % 1) * h, 0, h - 1).astype(int)
    return px[y, x]


def hsv(rgb):
    """Hue (degrees), saturation and value of an (..., 3) array of 0..1."""
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    safe = np.where(d > 1e-6, d, 1)
    hue = np.where(mx == r, ((g - b) / safe) % 6, np.where(mx == g, (b - r) / safe + 2, (r - g) / safe + 4)) * 60
    return np.where(d > 1e-6, hue, 0), np.where(mx > 1e-6, d / np.where(mx > 1e-6, mx, 1), 0), mx


def turn(q, angle):
    c, s = math.cos(angle), math.sin(angle)
    m = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.]])
    q.positions = q.positions @ m.T
    q.normals = q.normals @ m.T


def paint_maps(image):
    """A car's map without its paint, and the paint as a mask. The paint was asked for in pure
    green: where the map is green it becomes the paint's shading in grey (its light and its
    panel gaps), which the game multiplies by the copy's colour through the mask."""
    rgb = np.asarray(image.resize((MAP, MAP), Image.LANCZOS), dtype=np.float32) / 255
    hue, sat, val = hsv(rgb)
    green = np.clip(1 - np.abs(hue - 120) / 55, 0, 1) * np.clip((sat - .18) / .25, 0, 1) * np.clip((val - .1) / .15, 0, 1)
    mask = Image.fromarray((np.clip(green * 1.6, 0, 1) * 255).astype(np.uint8))
    # the paint's own edge is a blend of green and its neighbour: take it into the mask
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(.8))
    m = np.asarray(mask, dtype=np.float32)[..., None] / 255
    inside = val[green > .8]
    ref = float(np.percentile(inside, 85)) if inside.size else 1.
    shade = np.clip(val / max(ref, 1e-3), .2, 1.08)[..., None] * .92
    out = rgb * (1 - m) + shade * m
    palette = np.zeros_like(rgb)
    palette[..., 0] = m[..., 0]
    as_image = lambda a: Image.fromarray((np.clip(a, 0, 1) * 255 + .5).astype(np.uint8))
    return as_image(out), as_image(palette), float((m > .5).mean())


def surface(q, image):
    """Points spread over every face (six a face): their places, the map's colour there and the
    area each stands for. A lamp is a few faces of a low model and may hold no vertex at all."""
    bary = np.array([[.6, .2, .2], [.2, .6, .2], [.2, .2, .6], [.4, .4, .2], [.4, .2, .4], [.2, .4, .4]])
    pos = np.einsum('sb,fbk->fsk', bary, q.positions[q.faces]).reshape(-1, 3)
    uv = np.einsum('sb,fbk->fsk', bary, q.uv[q.faces]).reshape(-1, 2)
    a, b, c = (q.positions[q.faces[:, i]] for i in range(3))
    area = np.repeat(np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2 / len(bary), len(bary))
    return pos, texels(image, uv), area


def save_map(image, path):
    """A map as the PNG its material names (the check sheet reads it) and as the DDS the game
    loads in its place. A PNG the game first cooks into a DDS of its own, after the batch that
    wears it was made: the flow's cars, whose paint is a mask of their own, then drew nothing at
    all (look-03), and each map was 0.12 s of a frame."""
    image.save(path)
    fast_dds.save(image, path.with_suffix('.dds'))


def cook_car(name, out):
    body, (length, width, height), _, _ = CARS[name]
    source = SRC / 'mesh' / f'{name}.glb'
    if not source.is_file():
        return None
    glb = fal_mesh.GLB(source)
    q = merged(glb.primitives())
    image = texture_of(glb)
    # along +x: the turn about z at which the footprint is narrowest
    xy = q.positions[:, :2]
    best = min((np.ptp(xy @ np.array([-math.sin(a), math.cos(a)])), a) for a in np.radians(np.arange(0, 180, .5)))
    turn(q, -best[1])
    # the size of the game's car of that body
    fal_mesh.fit([q], size=[length, width, height])
    # the nose at +x: the red of the tail lamps lies at the back; a model without them (a van's are
    # thin) has its headlamps, the pale glass low on an end, at the front
    pos, colour, area = surface(q, image)
    hue, sat, val = hsv(colour)
    red = ((hue < 14) | (hue > 346)) & (sat > .55) & (val > .3)
    low = (pos[:, 2] > height * .25) & (pos[:, 2] < height * .62)
    pale = (val > .72) & (sat < .2) & low & (np.abs(pos[:, 0]) > length * .36)
    if area[red].sum() > .02:
        back, why = float((pos[red, 0] * area[red]).sum() / area[red].sum()), 'tail lamps'
    elif area[pale].sum() > .02:
        back, why = -float((pos[pale, 0] * area[pale]).sum() / area[pale].sum()), 'headlamps'
    else:
        back, why = 0., 'unknown'
    if back > 0:
        turn(q, math.pi)
    base, palette, share = paint_maps(image)
    save_map(base, out / f'{name}.color.png')
    save_map(palette, out / f'{name}_pal.color.png')
    label = CAR_MAT + name
    (out / f'{name}.dae').write_bytes(fal_mesh.collada([q], {0: label}, name))
    size = np.ptp(q.positions, axis=0)
    return {'name': name, 'body': body, 'shape': f'{name}.dae', 'material': label, 'triangles': int(len(q.faces)),
            'size': [round(float(v), 3) for v in size], 'nose': why, 'paint': round(share, 3)}


class Rig:
    """A skinned and animated GLB (Meshy's): its mesh as it stands at a moment of its clip."""

    def __init__(self, path):
        glb = self.glb = fal_mesh.GLB(path)
        doc = glb.doc
        self.nodes = doc['nodes']
        self.names = {n.get('name'): i for i, n in enumerate(self.nodes)}
        self.parent = {c: i for i, n in enumerate(self.nodes) for c in n.get('children', [])}
        self.order = []
        todo = [i for i in range(len(self.nodes)) if i not in self.parent]
        while todo:
            i = todo.pop()
            self.order.append(i)
            todo += self.nodes[i].get('children', [])
        holder = next(n for n in self.nodes if 'mesh' in n and 'skin' in n)
        skin = doc['skins'][holder['skin']]
        self.joints = skin['joints']
        self.inverse = glb.accessor(skin['inverseBindMatrices']).astype(float).reshape(-1, 4, 4).transpose(0, 2, 1)
        pos, nrm, uv, faces, joints, weights, at = [], [], [], [], [], [], 0
        for prim in doc['meshes'][holder['mesh']]['primitives']:
            a = prim['attributes']
            p = glb.accessor(a['POSITION']).astype(float)
            pos.append(p)
            nrm.append(glb.accessor(a['NORMAL']).astype(float))
            t = glb.accessor(a['TEXCOORD_0']).astype(float)
            t[:, 1] = 1 - t[:, 1]
            uv.append(t)
            joints.append(glb.accessor(a['JOINTS_0']).astype(int))
            weights.append(glb.accessor(a['WEIGHTS_0']).astype(float))
            faces.append(glb.accessor(prim['indices']).reshape(-1, 3).astype(np.int64) + at)
            at += len(p)
        self.pos, self.nrm, self.uv, self.faces = (np.concatenate(v) for v in (pos, nrm, uv, faces))
        self.jidx, self.w = np.concatenate(joints), np.concatenate(weights)
        self.w = self.w / np.maximum(self.w.sum(1, keepdims=True), 1e-9)
        self.channels, self.duration = [], 0.
        for anim in doc.get('animations', [])[:1]:
            for ch in anim['channels']:
                sampler = anim['samplers'][ch['sampler']]
                times = glb.accessor(sampler['input']).astype(float)[:, 0]
                values = glb.accessor(sampler['output']).astype(float)
                if sampler.get('interpolation') == 'CUBICSPLINE':
                    values = values.reshape(len(times), 3, -1)[:, 1]
                self.channels.append((ch['target']['node'], ch['target']['path'], times, values))
                self.duration = max(self.duration, float(times[-1]))

    @staticmethod
    def _matrix(t, r, s):
        x, y, z, w = r / np.linalg.norm(r)
        m = np.eye(4)
        m[:3, :3] = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                              [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                              [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]) @ np.diag(s)
        m[:3, 3] = t
        return m

    def world(self, at):
        """Every node's transform in the scene at `at` s of the clip."""
        trs = {}
        for i, n in enumerate(self.nodes):
            trs[i] = [np.array(n.get('translation', [0, 0, 0]), float), np.array(n.get('rotation', [0, 0, 0, 1]), float),
                      np.array(n.get('scale', [1, 1, 1]), float)]
        for node, path, times, values in self.channels:
            k = int(np.clip(np.searchsorted(times, at) - 1, 0, max(len(times) - 2, 0)))
            if len(times) == 1:
                v = values[0]
            else:
                f = float(np.clip((at - times[k]) / max(times[k + 1] - times[k], 1e-9), 0, 1))
                a, b = values[k], values[k + 1]
                if path == 'rotation':
                    if np.dot(a, b) < 0:
                        b = -b
                    v = a + (b - a) * f
                    v = v / np.linalg.norm(v)
                else:
                    v = a + (b - a) * f
            slot = {'translation': 0, 'rotation': 1, 'scale': 2}.get(path)
            if slot is not None:
                trs[node][slot] = v
        out = {}
        for i in self.order:
            n = self.nodes[i]
            local = (np.asarray(n['matrix'], float).reshape(4, 4, order='F') if 'matrix' in n
                     else self._matrix(*trs[i]))
            out[i] = out[self.parent[i]] @ local if i in self.parent else local
        return out

    def pose(self, at):
        """The mesh at `at` s in the game's axes (x, -z, y of glTF): positions, normals, the joints' places by name."""
        world = self.world(at)
        skin = np.stack([world[j] @ self.inverse[k] for k, j in enumerate(self.joints)])
        per = np.einsum('vk,vkij->vij', self.w, skin[self.jidx])
        pos = np.einsum('vij,vj->vi', per[:, :3, :3], self.pos) + per[:, :3, 3]
        nrm = np.einsum('vij,vj->vi', per[:, :3, :3], self.nrm)
        axes = fal_mesh.AXES[:3, :3]
        pos, nrm = pos @ axes.T, nrm @ axes.T
        nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
        places = {n.get('name'): world[i][:3, 3] @ axes.T for i, n in enumerate(self.nodes)}
        return pos, nrm, places


def far_shape(q, cell=FAR_CELL, patch=1 / 12):
    """The shape on a grid of `cell` m: the vertices of a cell become one (a person at 60 m and
    beyond). Only vertices of one patch of the map join (a grid of `patch` of it): a vertex made of
    both sides of a seam would draw the map between them across its faces."""
    keys = np.concatenate([np.floor(q.positions / cell), np.floor(q.uv / patch)], axis=1).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    inverse = inverse.reshape(-1)
    count = np.bincount(inverse).astype(float)[:, None]
    pos = np.zeros((len(first), 3))
    nrm = np.zeros((len(first), 3))
    uv = np.zeros((len(first), 2))
    np.add.at(pos, inverse, q.positions)
    np.add.at(nrm, inverse, q.normals)
    np.add.at(uv, inverse, q.uv)
    faces = inverse[q.faces]
    keep = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    faces = faces[keep]
    # one of each pair of faces a collapse folded onto each other
    _, unique = np.unique(np.sort(faces, axis=1), axis=0, return_index=True)
    faces = faces[np.sort(unique)]
    length = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = np.where(length > 1e-9, nrm / np.maximum(length, 1e-9), [[0, 0, 1.]])
    # the place of a vertex is its cell's whatever its patch: the two sides of a seam stay shut
    _, cell_of = np.unique(keys[first][:, :3], axis=0, return_inverse=True)
    cell_of = cell_of.reshape(-1)
    total, members = np.zeros((cell_of.max() + 1, 3)), np.zeros((cell_of.max() + 1, 1))
    np.add.at(total, cell_of, pos)
    np.add.at(members, cell_of, count)
    # and a face with two corners in one cell has no area left
    cells = cell_of[faces]
    faces = faces[(cells[:, 0] != cells[:, 1]) & (cells[:, 1] != cells[:, 2]) & (cells[:, 0] != cells[:, 2])]
    return fal_mesh.Primitive((total / members)[cell_of], nrm, uv / count, faces, 0)


def look_of(image, q, forward):
    """The colours of the clothes and the skin (sRGB 0..1) for the physical body that takes this
    walker's place (pedhit.lua): the middle colour of the chest, of the thighs and of the face."""
    colour = texels(image, q.uv)
    z = (q.positions[:, 2] - q.positions[:, 2].min()) / max(np.ptp(q.positions[:, 2]), 1e-6)
    side = np.abs(q.positions[:, 1])
    front = q.normals @ forward > .3
    pick = lambda mask: [round(float(v), 3) for v in np.median(colour[mask], axis=0)] if mask.sum() >= 4 else None
    # the face among hair, a hood and a collar: what has the hue of skin
    hue, sat, val = hsv(colour)
    skin = (hue > 4) & (hue < 42) & (sat > .15) & (sat < .65) & (val > .35)
    return {'shirt': pick((z > .62) & (z < .78) & (side < .14)) or [.4, .4, .4],
            'pants': pick((z > .25) & (z < .42)) or [.2, .2, .25],
            'skin': pick((z > .86) & (z < .95) & front & (side < .08) & skin) or [.8, .62, .5]}


def cook_ped(name, out):
    height = PEDS[name][0]
    folder = SRC / 'rig' / name
    clips = {'walk': folder / f'{name}_walking_glb.glb', 'stand': folder / f'{name}_animation_glb_2.glb',
             'sit': folder / f'{name}_animation_glb_3.glb'}
    if not all(path.is_file() for path in clips.values()):
        return None
    walk = Rig(clips['walk'])
    image = texture_of(walk.glb)
    save_map(image.resize((MAP, MAP), Image.LANCZOS), out / f'{name}.color.png')
    label = PED_MAT + name

    def shape(rig, at, scale, yaw):
        pos, nrm, places = rig.pose(at)
        hips = places['Hips']
        pos = pos - [hips[0], hips[1], 0]
        q = fal_mesh.Primitive(pos * scale, nrm, rig.uv.copy(), rig.faces.copy(), 0)
        turn(q, yaw)
        q.positions[:, 2] -= q.positions[:, 2].min()
        return q

    def facing(rig, at):
        """The turn about z that brings the way the feet point to +x."""
        _, _, places = rig.pose(at)
        toe = (places['LeftToeBase'] + places['RightToeBase']) / 2 - (places['LeftFoot'] + places['RightFoot']) / 2
        return -math.atan2(toe[1], toe[0])

    # the stand: the idle's first moment; its height sets the scale of every pose
    idle = Rig(clips['stand'])
    pos, _, _ = idle.pose(0)
    scale = height / max(np.ptp(pos[:, 2]), 1e-6)
    stand = shape(idle, 0, scale, facing(idle, 0))
    # the walk: one stride, from the moment the left foot passes the right one going forward
    yaw = facing(walk, 0)
    fwd = np.array([math.cos(-yaw), math.sin(-yaw), 0])
    times = np.linspace(0, walk.duration, 97)
    lead = []
    for at in times:
        _, _, places = walk.pose(at)
        lead.append(float((places['LeftFoot'] - places['RightFoot']) @ fwd))
    lead = np.array(lead)
    ups = [k for k in range(len(lead) - 1) if lead[k] <= 0 < lead[k + 1]]
    if len(ups) >= 2:
        start, stride = float(times[ups[0]]), float(times[ups[1]] - times[ups[0]])
    else:
        start, stride = float(times[ups[0]]) if ups else 0., walk.duration
    shapes = {}
    for k in range(POSES):
        at = (start + stride * k / POSES) % max(walk.duration, 1e-6)
        shapes[f'walk{k}'] = shape(walk, at, scale, yaw)
    shapes['stand'] = stand
    seat = Rig(clips['sit'])
    # the clip's first moment: upright, hands on the thighs (later it leans on its knees)
    shapes['sit'] = shape(seat, 0, scale, facing(seat, 0))
    shapes['far'] = far_shape(shapes['walk0'])
    files = {}
    for key, q in shapes.items():
        file = f'{name}_{key}.dae'
        (out / file).write_bytes(fal_mesh.collada([q], {0: label}, f'{name}_{key}'))
        files[key] = file
    return {'name': name, 'height': height, 'material': label, 'shapes': files, 'triangles': int(len(stand.faces)),
            'farTriangles': int(len(shapes['far'].faces)), 'stride': round(stride, 3),
            'look': look_of(image, stand, np.array([1., 0, 0]))}


def materials(manifest):
    """The models' materials by folder: {folder: {name: material}} (paths filled in by level_files)."""
    cars, peds = {}, {}
    for car in manifest['cars']:
        cars[car['material']] = {'name': car['material'], 'mapTo': car['material'], 'class': 'Material', 'version': 1.5,
                                 'Stages': [{'baseColorMap': car['name'] + '.color.png', 'colorPaletteMap': car['name'] + '_pal.color.png',
                                             'instanceDiffuse': True, 'roughnessFactor': .34, 'metallicFactor': .3,
                                             'clearCoatFactor': .4, 'clearCoatRoughnessFactor': .2}, {}, {}, {}]}
    for ped in manifest['peds']:
        peds[ped['material']] = {'name': ped['material'], 'mapTo': ped['material'], 'class': 'Material', 'version': 1.5,
                                 'Stages': [{'baseColorMap': ped['name'] + '.color.png', 'roughnessFactor': .86}, {}, {}, {}]}
    return {FLOW_DIR: cars, PEOPLE_DIR: peds}


def cooked():
    return OUT / VERSION


def build(only=None):
    """The shapes and maps of every model whose sources are there, into cooked(); returns the manifest."""
    out = cooked()
    (out / FLOW_DIR).mkdir(parents=True, exist_ok=True)
    (out / PEOPLE_DIR).mkdir(parents=True, exist_ok=True)
    manifest = {'version': VERSION, 'cars': [], 'peds': []}
    for name in CARS:
        if not only or name in only:
            car = cook_car(name, out / FLOW_DIR)
            if car:
                manifest['cars'].append(car)
    for name in PEDS:
        if not only or name in only:
            ped = cook_ped(name, out / PEOPLE_DIR)
            if ped:
                manifest['peds'].append(ped)
    (out / 'models.json').write_text(json.dumps(manifest, indent=1), encoding='utf8')
    return manifest


def level_files(level):
    """The cooked models for the planet ZIP (build_mod.py): {} when nothing is cooked."""
    out = cooked()
    index = out / 'models.json'
    if not index.is_file():
        return {}
    manifest = json.loads(index.read_text(encoding='utf8'))
    files = {}
    for folder, mats in materials(manifest).items():
        root = f'levels/{level}/{folder}/'
        for material in mats.values():
            stage = material['Stages'][0]
            for field in ('baseColorMap', 'colorPaletteMap'):
                if field in stage:
                    # the DDS goes into the planet under the PNG's name with its own suffix: the
                    # game loads it where the material names the PNG
                    source = out / folder / stage[field]
                    packed = source.with_suffix('.dds') if source.with_suffix('.dds').is_file() else source
                    files[root + packed.name] = packed.read_bytes()
                    stage[field] = '/' + root + stage[field]
        if mats:
            files[root + 'fal.materials.json'] = json.dumps(mats, indent=1)
    for car in manifest['cars']:
        files[f'levels/{level}/{FLOW_DIR}/{car["shape"]}'] = (out / FLOW_DIR / car['shape']).read_bytes()
    for ped in manifest['peds']:
        for file in ped['shapes'].values():
            files[f'levels/{level}/{PEOPLE_DIR}/{file}'] = (out / PEOPLE_DIR / file).read_bytes()
    # what the Lua side reads (world.lua M.trafficModels): the shapes by body, the people and their looks
    files[f'levels/{level}/art/traffic_models.json'] = json.dumps({
        'cars': [{'name': c['name'], 'body': c['body'], 'shape': f'/levels/{level}/{FLOW_DIR}/{c["shape"]}'} for c in manifest['cars']],
        'peds': [{'name': q['name'], 'look': q['look'],
                  'shapes': {k: f'/levels/{level}/{PEOPLE_DIR}/{v}' for k, v in q['shapes'].items()}} for q in manifest['peds']]})
    return files


# --- a look without the game ---------------------------------------------------------------------
def preview(q, image, view, size=360, tint=None, palette=None):
    """The shape drawn from `view` ('side', 'front', 'top', 'quarter') with its map, flat lit: a
    check of the turn, the scale and the paint before the game sees it."""
    turns = {'side': (0, 0), 'front': (90, 0), 'top': (0, 90), 'quarter': (-35, 20)}
    yaw, pitch = (math.radians(v) for v in turns[view])
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    # screen x: across the view, screen y: up, depth: towards the viewer (who looks along -y turned)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1.]])
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    p = q.positions @ rz.T @ rx.T
    sx, sz, depth = p[:, 0], p[:, 2], -p[:, 1]
    span = max(np.ptp(sx), np.ptp(sz)) * 1.08
    px = ((sx - (sx.min() + sx.max()) / 2) / span + .5) * size
    py = (.5 - (sz - (sz.min() + sz.max()) / 2) / span) * size
    tex = np.asarray(image.convert('RGB').resize((512, 512)), dtype=np.float32) / 255
    if tint is not None and palette is not None:
        m = np.asarray(palette.convert('RGB').resize((512, 512)), dtype=np.float32)[..., :1] / 255
        tex = tex * (1 - m) + tex * np.array(tint) * m
    canvas = np.ones((size, size, 3), dtype=np.float32) * .78
    zbuf = np.full((size, size), -1e9)
    light = np.array([.3, -.6, .74])
    n_view = q.normals @ rz.T @ rx.T
    for f in q.faces:
        x, y = px[f], py[f]
        x0, x1 = int(max(0, math.floor(x.min()))), int(min(size - 1, math.ceil(x.max())))
        y0, y1 = int(max(0, math.floor(y.min()))), int(min(size - 1, math.ceil(y.max())))
        if x0 > x1 or y0 > y1:
            continue
        area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
        if abs(area) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
        w0 = ((x[1] - gx) * (y[2] - gy) - (x[2] - gx) * (y[1] - gy)) / area
        w1 = ((x[2] - gx) * (y[0] - gy) - (x[0] - gx) * (y[2] - gy)) / area
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        d = w0 * depth[f[0]] + w1 * depth[f[1]] + w2 * depth[f[2]]
        box = zbuf[y0:y1 + 1, x0:x1 + 1]
        hit = inside & (d > box)
        if not hit.any():
            continue
        u = w0 * q.uv[f[0], 0] + w1 * q.uv[f[1], 0] + w2 * q.uv[f[2], 0]
        v = w0 * q.uv[f[0], 1] + w1 * q.uv[f[1], 1] + w2 * q.uv[f[2], 1]
        tx = np.clip((u % 1) * 512, 0, 511).astype(int)
        ty = np.clip((1 - v % 1) * 512, 0, 511).astype(int)
        shade = .55 + .45 * max(0., float(n_view[f].mean(0) @ light))
        box[hit] = d[hit]
        canvas[y0:y1 + 1, x0:x1 + 1][hit] = tex[ty[hit], tx[hit]] * shade
    return Image.fromarray((np.clip(canvas, 0, 1) * 255).astype(np.uint8))


def read_dae(path):
    """A shape this module wrote, back as a primitive (for preview)."""
    import xml.etree.ElementTree as ET
    ns = {'c': fal_mesh.NS}
    root = ET.parse(path).getroot()
    arrays = {}
    for source in root.iterfind('.//c:source', ns):
        values = np.array(source.find('c:float_array', ns).text.split(), dtype=float)
        stride = int(source.find('.//c:accessor', ns).get('stride'))
        arrays[source.get('id').rsplit('-', 1)[-1]] = values.reshape(-1, stride)
    idx = np.array(root.find('.//c:triangles/c:p', ns).text.split(), dtype=np.int64).reshape(-1, 3, 3)[:, :, 0]
    return fal_mesh.Primitive(arrays['pos'], arrays['nrm'], arrays['uv'], idx, 0)


def sheet(manifest, path):
    """Every cooked model on one picture: the cars from the side, the front and above in two
    paints, the people's poses from the side and the front."""
    out = cooked()
    rows = []
    for car in manifest['cars']:
        q = read_dae(out / FLOW_DIR / car['shape'])
        base = Image.open(out / FLOW_DIR / (car['name'] + '.color.png'))
        pal = Image.open(out / FLOW_DIR / (car['name'] + '_pal.color.png'))
        rows.append([preview(q, base, 'side', tint=(.55, .07, .06), palette=pal), preview(q, base, 'front', tint=(.86, .86, .84), palette=pal),
                     preview(q, base, 'top', tint=(.1, .17, .35), palette=pal), preview(q, base, 'quarter', tint=(.05, .05, .06), palette=pal)])
    for ped in manifest['peds']:
        base = Image.open(out / PEOPLE_DIR / (ped['name'] + '.color.png'))
        row = []
        for key, view in (('stand', 'front'), ('walk0', 'side'), ('walk2', 'side'), ('walk4', 'side'), ('walk6', 'side'), ('sit', 'side'), ('far', 'front')):
            row.append(preview(read_dae(out / PEOPLE_DIR / ped['shapes'][key]), base, view, size=240))
        rows.append(row)
    if not rows:
        return
    width = max(sum(im.width for im in row) for row in rows)
    canvas = Image.new('RGB', (width, sum(row[0].height for row in rows)), 'white')
    y = 0
    for row in rows:
        x = 0
        for im in row:
            canvas.paste(im, (x, y))
            x += im.width
        y += row[0].height
    canvas.save(path, quality=88)


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--generate', action='store_true', help='make the missing sources with fal (paid)')
    p.add_argument('--only', help='comma list of model names')
    p.add_argument('--stage', choices=('image', 'mesh', 'rig'), default='rig', help='--generate stops after this step')
    p.add_argument('--build', action='store_true', help='cook the sources into shapes (no call)')
    p.add_argument('--sheet', type=Path, help='with --build: a picture of every cooked model')
    a = p.parse_args()
    only = set(a.only.split(',')) if a.only else None
    if a.generate:
        if a.stage == 'image':
            names = [n for n in list(CARS) + list(PEDS) if not only or n in only]
            with ThreadPoolExecutor(4) as pool:
                list(pool.map(lambda n: image(n, (CARS[n][-1] + CAR_STYLE) if n in CARS else (PEDS[n][-1] + PED_STYLE)), names))
        else:
            generate(only, a.stage)
    if a.build:
        manifest = build(only)
        for item in manifest['cars'] + manifest['peds']:
            print(json.dumps({k: v for k, v in item.items() if k != 'shapes'}))
        if a.sheet:
            sheet(manifest, a.sheet)


if __name__ == '__main__':
    main()
