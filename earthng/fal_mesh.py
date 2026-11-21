"""Convert a static, textured FAL GLB to a metric BeamNG Collada shape.

No generator credentials are needed. Geometry stays indexed; node transforms are baked,
glTF (x,y,z) becomes BeamNG (x,-z,y), UV V is flipped for Collada, and the origin is
centred horizontally at ground level. The output contains only the supplied asset.
"""
import argparse
import base64
from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image


NS = 'http://www.collada.org/2005/11/COLLADASchema'
AXES = np.array([[1., 0, 0, 0], [0, 0, -1., 0], [0, 1., 0, 0], [0, 0, 0, 1.]])
DTYPES = {5120: '<i1', 5121: '<u1', 5122: '<i2', 5123: '<u2', 5125: '<u4', 5126: '<f4'}
WIDTHS = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


def finite(array, name):
    if not np.isfinite(array).all():
        raise ValueError(f'{name} contains non-finite values')
    return array


@dataclass
class Primitive:
    positions: np.ndarray
    normals: np.ndarray
    uv: np.ndarray | None
    faces: np.ndarray
    material: int | None


class GLB:
    def __init__(self, path):
        self.path = Path(path)
        raw = self.path.read_bytes()
        if len(raw) < 20:
            raise ValueError('Truncated GLB header')
        magic, version, length = struct.unpack_from('<4sII', raw)
        if magic != b'glTF' or version != 2 or length != len(raw):
            raise ValueError('Expected a complete glTF 2.0 binary file')
        chunks, cursor = {}, 12
        while cursor < len(raw):
            if cursor + 8 > len(raw):
                raise ValueError('Truncated GLB chunk header')
            size, kind = struct.unpack_from('<II', raw, cursor)
            cursor += 8
            if cursor + size > len(raw):
                raise ValueError('Truncated GLB chunk')
            if kind in chunks:
                raise ValueError('Repeated GLB JSON/BIN chunk')
            chunks[kind] = raw[cursor:cursor + size]
            cursor += size
        if 0x4E4F534A not in chunks:
            raise ValueError('GLB has no JSON chunk')
        self.doc = json.loads(chunks[0x4E4F534A].rstrip(b'\x00 \t\r\n'))
        self.repairs = {'degenerate_triangles_removed': 0, 'unused_vertices_removed': 0,
                        'zero_normals_reconstructed': 0}
        self.buffers = []
        for i, buffer in enumerate(self.doc.get('buffers', [])):
            if 'uri' in buffer:
                data = self.uri(buffer['uri'])
            elif i == 0:
                data = chunks.get(0x004E4942, b'')
            else:
                raise ValueError('Only the first GLB buffer can omit its URI')
            if len(data) < buffer['byteLength']:
                raise ValueError('GLB buffer is shorter than its declaration')
            self.buffers.append(data)

    def uri(self, uri):
        if uri.startswith('data:'):
            header, payload = uri.split(',', 1)
            if ';base64' not in header:
                raise ValueError('Only base64 data URIs are supported')
            return base64.b64decode(payload, validate=True)
        if '://' in uri:
            raise ValueError('Remote buffers and images must be downloaded first')
        path = (self.path.parent / uri).resolve()
        if not path.is_relative_to(self.path.parent.resolve()):
            raise ValueError('Asset dependency escapes its input folder')
        return path.read_bytes()

    def view(self, index):
        view = self.doc['bufferViews'][index]
        raw = self.buffers[view['buffer']]
        start, size = view.get('byteOffset', 0), view['byteLength']
        if start < 0 or size < 0 or start + size > len(raw):
            raise ValueError('bufferView outside its buffer')
        return view, raw[start:start + size]

    def accessor(self, index):
        acc = self.doc['accessors'][index]
        if 'sparse' in acc:
            raise ValueError('Sparse accessors are not supported; expand the asset first')
        if 'bufferView' not in acc:
            raise ValueError('Accessor has no bufferView')
        if acc['componentType'] not in DTYPES or acc['type'] not in WIDTHS:
            raise ValueError('Unsupported accessor component/type')
        dtype, width, count = np.dtype(DTYPES[acc['componentType']]), WIDTHS[acc['type']], acc['count']
        view, raw = self.view(acc['bufferView'])
        stride = view.get('byteStride', dtype.itemsize * width)
        offset = acc.get('byteOffset', 0)
        if count < 0 or offset < 0 or stride < dtype.itemsize * width:
            raise ValueError('Invalid accessor layout')
        end = offset + (count - 1) * stride + width * dtype.itemsize if count else offset
        if end > len(raw):
            raise ValueError('Accessor extends outside bufferView')
        values = np.ndarray((count, width), dtype=dtype, buffer=raw, offset=offset,
                            strides=(stride, dtype.itemsize)).copy()
        if acc.get('normalized') and dtype.kind in 'iu':
            values = values.astype(np.float64) / np.iinfo(dtype).max
            if dtype.kind == 'i':
                values = np.maximum(values, -1.)
        return finite(values, 'Accessor')

    def image(self, index):
        image = self.doc['images'][index]
        raw = self.uri(image['uri']) if 'uri' in image else self.view(image['bufferView'])[1]
        with Image.open(io.BytesIO(raw)) as src:
            src.load()
            return src.copy()

    @staticmethod
    def transform(node):
        if 'matrix' in node:
            matrix = np.asarray(node['matrix'], dtype=float).reshape(4, 4, order='F')
        else:
            x, y, z, w = node.get('rotation', [0, 0, 0, 1])
            q = np.array([x, y, z, w], dtype=float)
            if not np.isfinite(q).all() or np.linalg.norm(q) < 1e-12:
                raise ValueError('Invalid node quaternion')
            x, y, z, w = q / np.linalg.norm(q)
            rotation = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                                 [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                                 [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
            matrix = np.eye(4)
            matrix[:3, :3] = rotation @ np.diag(node.get('scale', [1, 1, 1]))
            matrix[:3, 3] = node.get('translation', [0, 0, 0])
        finite(matrix, 'Node transform')
        if not np.allclose(matrix[3], [0, 0, 0, 1]) or abs(np.linalg.det(matrix[:3, :3])) < 1e-12:
            raise ValueError('Node transform must be an invertible affine transform')
        return matrix

    def primitives(self):
        instances = []
        nodes = self.doc.get('nodes', [])
        if nodes:
            scenes = self.doc.get('scenes', [])
            roots = (scenes[self.doc.get('scene', 0)].get('nodes', []) if scenes else
                     sorted(set(range(len(nodes))) - {c for n in nodes for c in n.get('children', [])}))

            def visit(index, transform, trail):
                if index in trail:
                    raise ValueError('Cycle in glTF node graph')
                node = nodes[index]
                if 'skin' in node:
                    raise ValueError('Skinned meshes require a baked static pose')
                transform = transform @ self.transform(node)
                if 'mesh' in node:
                    instances.append((node['mesh'], AXES @ transform))
                for child in node.get('children', []):
                    visit(child, transform, trail | {index})
            for root in roots:
                visit(root, np.eye(4), set())
        else:
            instances = [(i, AXES) for i in range(len(self.doc.get('meshes', [])))]
        result = []
        for index, transform in instances:
            for source in self.doc['meshes'][index]['primitives']:
                if 'KHR_draco_mesh_compression' in source.get('extensions', {}):
                    raise ValueError('Draco-compressed geometry requires decompression first')
                if source.get('mode', 4) != 4 or source.get('targets'):
                    raise ValueError('Only static TRIANGLES primitives are supported')
                attrs = source['attributes']
                pos = self.accessor(attrs['POSITION']).astype(float)
                if pos.ndim != 2 or pos.shape[1] != 3 or not len(pos):
                    raise ValueError('POSITION must contain VEC3 vertices')
                faces = self.accessor(source['indices']) if 'indices' in source else np.arange(len(pos))[:, None]
                if faces.shape[1] != 1 or faces.dtype.kind not in 'iu' or faces.size % 3:
                    raise ValueError('Triangle indices must be integer SCALAR triples')
                faces = faces.reshape(-1, 3).astype(np.int64)
                if not len(faces) or faces.min() < 0 or faces.max() >= len(pos):
                    raise ValueError('Triangle index outside POSITION')
                pos = pos @ transform[:3, :3].T + transform[:3, 3]
                if np.linalg.det(transform[:3, :3]) < 0:
                    faces = faces[:, [0, 2, 1]]
                # Generative meshes can contain collapsed triangles and zero normals.
                # Discard only collapsed faces, then retain only referenced vertices;
                # repairing their normals after this avoids inventing isolated points.
                a, b, c = (pos[faces[:, i]] for i in range(3))
                threshold = max(float(np.ptp(pos, axis=0).max()), 1e-3) ** 2 * 1e-15
                keep = np.linalg.norm(np.cross(b - a, c - a), axis=1) > threshold
                self.repairs['degenerate_triangles_removed'] += int((~keep).sum())
                faces = faces[keep]
                if not len(faces):
                    continue
                used, reindex = np.unique(faces.ravel(), return_inverse=True)
                self.repairs['unused_vertices_removed'] += len(pos) - len(used)
                original_count = len(pos)
                pos, faces = pos[used], reindex.reshape(-1, 3)
                if 'NORMAL' in attrs:
                    nrm = self.accessor(attrs['NORMAL']).astype(float)
                    if nrm.shape != (original_count, 3):
                        raise ValueError('NORMAL and POSITION counts differ')
                    nrm = nrm[used] @ np.linalg.inv(transform[:3, :3])
                    bad = np.linalg.norm(nrm, axis=1) < 1e-12
                    if bad.any():
                        self.repairs['zero_normals_reconstructed'] += int(bad.sum())
                        nrm[bad] = vertex_normals(pos, faces)[bad]
                    nrm = unit_normals(nrm)
                else:
                    nrm = vertex_normals(pos, faces)
                uv = self.accessor(attrs['TEXCOORD_0']).astype(float) if 'TEXCOORD_0' in attrs else None
                if uv is not None:
                    if uv.shape != (original_count, 2):
                        raise ValueError('TEXCOORD_0 must match POSITION with two components')
                    uv = uv[used]
                    uv[:, 1] = 1 - uv[:, 1]
                mat = source.get('material')
                if mat is not None and not 0 <= mat < len(self.doc.get('materials', [])):
                    raise ValueError('Primitive references an absent material')
                result.append(Primitive(finite(pos, 'Positions'), nrm, uv, faces, mat))
        if not result:
            raise ValueError('GLB contains no triangle geometry in its active scene')
        return result


def unit_normals(normals):
    finite(normals, 'Normals')
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(lengths < 1e-12):
        raise ValueError('Zero-length vertex normal')
    return normals / lengths[:, None]


def vertex_normals(positions, faces):
    a, b, c = (positions[faces[:, i]] for i in range(3))
    normals = np.zeros_like(positions, dtype=float)
    face_normals = np.cross(b - a, c - a)
    for i in range(3):
        np.add.at(normals, faces[:, i], face_normals)
    # Opposed, duplicated faces can cancel a vertex average. A real incident face
    # still supplies a valid fallback normal; never emit a zero/NaN normal.
    bad = np.linalg.norm(normals, axis=1) < 1e-12
    if bad.any():
        fallback = np.zeros_like(normals)
        for i in range(3):
            fallback[faces[:, i]] = face_normals
        normals[bad] = fallback[bad]
    return unit_normals(normals)


def fit(primitives, size=None, height=None, yaw=0):
    if size is not None and height is not None:
        raise ValueError('Choose size or height, not both')
    angle = math.radians(yaw)
    turn = np.array([[math.cos(angle), -math.sin(angle), 0],
                     [math.sin(angle), math.cos(angle), 0], [0, 0, 1.]])
    for primitive in primitives:
        primitive.positions = primitive.positions @ turn.T
        primitive.normals = primitive.normals @ turn.T
    positions = np.concatenate([p.positions for p in primitives])
    lo, hi = positions.min(axis=0), positions.max(axis=0)
    extent = hi - lo
    if size is not None:
        size = np.asarray(size, dtype=float)
        if size.shape != (3,) or not np.isfinite(size).all() or np.any(size <= 0) or np.any(extent <= 1e-9):
            raise ValueError('Size and source extents must be three positive finite numbers')
        scale = size / extent
    elif height is not None:
        if not math.isfinite(height) or height <= 0 or extent[2] <= 1e-9:
            raise ValueError('Height and source height must be positive finite numbers')
        scale = np.full(3, height / extent[2])
    else:
        scale = np.ones(3)
    offset = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    for primitive in primitives:
        primitive.positions = (primitive.positions - offset) * scale
        primitive.normals = unit_normals(primitive.normals / scale)
    return extent * scale


def materials(glb, used, out, name, vfs_root):
    result, names = {}, {}
    for ordinal, index in enumerate(used):
        label = f'e2r_kyiv3d_{name}_{ordinal}'
        names[index] = label
        source = glb.doc['materials'][index] if index is not None else {}
        pbr = source.get('pbrMetallicRoughness', {})
        packed = 'metallicRoughnessTexture' in pbr
        stage = {'baseColorFactor': pbr.get('baseColorFactor', [1, 1, 1, 1]),
                 'roughnessFactor': pbr.get('roughnessFactor', 1. if packed else .8),
                 'metallicFactor': pbr.get('metallicFactor', 1. if packed else 0.)}

        def texture(spec, suffix, channel=None, mode=None):
            if spec.get('texCoord', 0) != 0 or spec.get('extensions'):
                raise ValueError('Only untransformed TEXCOORD_0 textures are supported')
            tex = glb.doc['textures'][spec['index']]
            image_index = tex.get('source')
            # Trellis 2 embeds lossless WebP via this standard glTF extension.
            # Pillow decodes it directly, retaining the model's supplied pixels.
            for extension in ('EXT_texture_webp', 'EXT_texture_avif'):
                if image_index is None:
                    image_index = tex.get('extensions', {}).get(extension, {}).get('source')
            if image_index is None:
                raise ValueError('Texture lacks a plain image source')
            image = glb.image(image_index)
            if channel is not None:
                image = image.convert('RGB').getchannel(channel)
            elif mode:
                image = image.convert(mode)
            filename = f'{label}_{suffix}.png'
            image.save(out / filename)
            return f'{vfs_root}/{filename}'

        if 'baseColorTexture' in pbr:
            stage['baseColorMap'] = texture(pbr['baseColorTexture'], 'b.color', mode='RGBA')
        if packed:
            stage['roughnessMap'] = texture(pbr['metallicRoughnessTexture'], 'r.data', 'G')
            stage['metallicMap'] = texture(pbr['metallicRoughnessTexture'], 'm.data', 'B')
        if 'normalTexture' in source:
            stage['normalMap'] = texture(source['normalTexture'], 'nm.normal', mode='RGB')
        if 'occlusionTexture' in source:
            stage['ambientOcclusionMap'] = texture(source['occlusionTexture'], 'ao.data', 'R')
        material = {'name': label, 'mapTo': label, 'class': 'Material', 'version': 1.5,
                    'Stages': [stage, {}, {}, {}], 'persistentId': hashlib.md5(label.encode()).hexdigest()}
        if source.get('doubleSided'):
            material['doubleSided'] = True
        if source.get('alphaMode') == 'MASK':
            material.update(alphaTest=True, alphaRef=int(round(source.get('alphaCutoff', .5) * 255)),
                            translucent=False)
        elif source.get('alphaMode') == 'BLEND':
            material.update(translucent=True, translucentBlendOp='LerpAlpha')
        result[label] = material
    return result, names


def collada(primitives, names, name):
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
    for label in names.values():
        effect = add(effects, 'effect', id=f'{label}-fx')
        technique = add(add(effect, 'profile_COMMON'), 'technique', sid='common')
        add(add(add(technique, 'lambert'), 'diffuse'), 'color', '1 1 1 1')
        add(add(mats, 'material', id=label, name=label), 'instance_effect', url=f'#{label}-fx')
    geometries = add(root, 'library_geometries')
    visual = add(add(root, 'library_visual_scenes'), 'visual_scene', id='Scene')
    base = add(add(visual, 'node', id='base00', name='base00'), 'node', id='start01', name='start01')
    for i, primitive in enumerate(primitives):
        gid, label = f'g{i}', names[primitive.material]
        mesh = add(add(geometries, 'geometry', id=gid, name=gid), 'mesh')

        def source(suffix, array, params):
            sid = f'{gid}-{suffix}'
            src = add(mesh, 'source', id=sid)
            add(src, 'float_array', ' '.join(format(float(v), '.9g') for v in array.ravel()),
                id=f'{sid}-array', count=array.size)
            accessor = add(add(src, 'technique_common'), 'accessor', source=f'#{sid}-array',
                           count=len(array), stride=len(params))
            for param in params:
                add(accessor, 'param', name=param, type='float')
        source('pos', primitive.positions, 'XYZ')
        source('nrm', primitive.normals, 'XYZ')
        if primitive.uv is not None:
            source('uv', primitive.uv, 'ST')
        add(add(mesh, 'vertices', id=f'{gid}-vtx'), 'input', semantic='POSITION', source=f'#{gid}-pos')
        triangles = add(mesh, 'triangles', material=label, count=len(primitive.faces))
        add(triangles, 'input', semantic='VERTEX', source=f'#{gid}-vtx', offset=0)
        add(triangles, 'input', semantic='NORMAL', source=f'#{gid}-nrm', offset=1)
        stride = 2
        if primitive.uv is not None:
            add(triangles, 'input', semantic='TEXCOORD', source=f'#{gid}-uv', offset=2, set=0)
            stride = 3
        indices = np.repeat(primitive.faces.ravel(), stride)
        add(triangles, 'p', ' '.join(map(str, indices)))
        node_name = f'{name}_a100' if i == 0 else f'{name}_{i}_a100'
        node = add(base, 'node', id=node_name, name=node_name)
        bind = add(add(add(node, 'instance_geometry', url=f'#{gid}'), 'bind_material'), 'technique_common')
        instance = add(bind, 'instance_material', symbol=label, target=f'#{label}')
        if primitive.uv is not None:
            add(instance, 'bind_vertex_input', semantic='UVMap', input_semantic='TEXCOORD', input_set=0)
    add(add(root, 'scene'), 'instance_visual_scene', url='#Scene')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def convert(path, out, name, size=None, height=None, yaw=0, vfs_root=None):
    """Write one DAE, material file, textures and measured bounds; return the manifest."""
    if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
        raise ValueError('Name must start with a lowercase letter and contain a-z, 0-9, _')
    if not math.isfinite(yaw):
        raise ValueError('Yaw must be finite')
    glb = GLB(path)
    primitives = glb.primitives()
    extent = fit(primitives, size, height, yaw)
    used = list(dict.fromkeys(p.material for p in primitives))
    textured = {i for i in used if i is not None and any(k in glb.doc['materials'][i].get('pbrMetallicRoughness', {})
                for k in ('baseColorTexture', 'metallicRoughnessTexture'))}
    if any(p.material in textured and p.uv is None for p in primitives):
        raise ValueError('Textured primitive has no TEXCOORD_0')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    vfs_root = (vfs_root or f'/art/shapes/earthng/kyiv3d/{name}').rstrip('/')
    material_data, names = materials(glb, used, out, name, vfs_root)
    dae = out / f'{name}.dae'
    dae.write_bytes(collada(primitives, names, name))
    (out / 'main.materials.json').write_text(json.dumps(material_data, indent=2), encoding='utf-8')
    positions = np.concatenate([p.positions for p in primitives])
    manifest = {'source': str(Path(path).resolve()), 'source_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                'shape': f'{vfs_root}/{name}.dae', 'materials': f'{vfs_root}/main.materials.json',
                'vertices': sum(len(p.positions) for p in primitives),
                'triangles': sum(len(p.faces) for p in primitives), 'size': extent.tolist(),
                'bounds': [positions.min(axis=0).tolist(), positions.max(axis=0).tolist()],
                'yaw_degrees': yaw, 'uv_v_flipped': True, 'repairs': glb.repairs,
                'collision': 'none; select Visible Mesh in the runtime'}
    (out / 'mesh.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('input', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--name', required=True)
    scale = parser.add_mutually_exclusive_group()
    scale.add_argument('--size', help='metric X,Y,Z extents after --yaw (allows nonuniform scaling)')
    scale.add_argument('--height', type=float, help='metric height, retaining proportions')
    parser.add_argument('--yaw', type=float, default=0)
    parser.add_argument('--vfs-root', help='output folder as an absolute game VFS path')
    args = parser.parse_args()
    size = [float(v) for v in args.size.split(',')] if args.size else None
    print(json.dumps(convert(args.input, args.out, args.name, size, args.height, args.yaw, args.vfs_root), indent=2))


if __name__ == '__main__':
    main()
