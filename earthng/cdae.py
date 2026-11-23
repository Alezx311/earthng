"""The game's compiled shape (`.cdae`, TSShape v31, MessagePack) read and written without the game.

    python earthng/cdae.py dump <file.cdae>            # what a shape holds
    python earthng/cdae.py grid <out.cdae> [--n 100] [--materials 4]   # a test shape

The format is the game's own cache of a Collada shape (documentation.beamng.com/modding/file_formats/cdae):
an i32 version (31 in the low byte), a u32 header length, a MessagePack map (`compression`, `bodysize`),
then the body as a run of MessagePack values in the order TSShape writes its fields. A vector is three
values: the count, the bytes of one element, the elements as one `bin`.

A shape written here is what a tile's unique geometry becomes when the mod stops handing triangles to
`createMesh` from Lua tables: one TSStatic, loaded by the engine from bytes. `write()` is the reference
for the Lua writer (`mod/lua/ge/extensions/e2r/cdae.lua`), and the two must write the same bytes.
"""
import argparse
import math
import struct
import sys
from pathlib import Path

VERSION = 31
EXPORTER = 124          # what BeamNG 0.40 writes in the high half of the version
INFO = ('\r\n\r\n\r\nWelcome! This is a binary file :D\r\n'
        'Please read the docs at https://go.beamng.com/shapeMessagepackFileformat\r\n\r\n\r\n')

# TSDrawPrimitive.matIndex
TRIANGLES, INDEXED, NO_MATERIAL, MATERIAL_MASK = 0x00000000, 0x20000000, 0x10000000, 0x0FFFFFFF
STANDARD_MESH, NULL_MESH = 0, 4
# The engine draws a mesh with 16-bit indices: past this many vertices they wrap (the file still
# reads back whole). A bigger shape is several meshes.
MESH_VERTICES = 65535


# --- MessagePack, the part the format uses -------------------------------------------------------

class Bin(bytes):
    """Bytes that go out as a `bin`, not a `str`."""


class F32(float):
    """A float that goes out as float32 (the format's floats are single)."""


def pack(value, out):
    """Append one value. Ints take the smallest form, like the game's writer."""
    if value is None:
        out += b'\xc0'
    elif value is True or value is False:
        out += b'\xc3' if value else b'\xc2'
    elif isinstance(value, int):
        if 0 <= value < 0x80:
            out.append(value)
        elif -32 <= value < 0:
            out.append(value & 0xff)
        elif 0 <= value <= 0xff:
            out += b'\xcc' + bytes((value,))
        elif 0 <= value <= 0xffff:
            out += b'\xcd' + struct.pack('>H', value)
        elif 0 <= value <= 0xffffffff:
            out += b'\xce' + struct.pack('>I', value)
        elif -0x80 <= value < 0:
            out += b'\xd0' + struct.pack('>b', value)
        elif -0x8000 <= value < 0:
            out += b'\xd1' + struct.pack('>h', value)
        elif -0x80000000 <= value < 0:
            out += b'\xd2' + struct.pack('>i', value)
        else:
            out += (b'\xcf' + struct.pack('>Q', value)) if value > 0 else (b'\xd3' + struct.pack('>q', value))
    elif isinstance(value, float):
        # the game's writer puts a whole float out as an int
        if value == int(value) and abs(value) < 0x80000000:
            return pack(int(value), out)
        out += b'\xca' + struct.pack('>f', value)
    elif isinstance(value, Bin):
        n = len(value)
        out += (b'\xc4' + bytes((n,))) if n <= 0xff else (b'\xc5' + struct.pack('>H', n)) if n <= 0xffff \
            else (b'\xc6' + struct.pack('>I', n))
        out += value
    elif isinstance(value, (str, bytes)):
        raw = value.encode('utf8') if isinstance(value, str) else value
        n = len(raw)
        if n < 32:
            out.append(0xa0 | n)
        elif n <= 0xff:
            out += b'\xd9' + bytes((n,))
        elif n <= 0xffff:
            out += b'\xda' + struct.pack('>H', n)
        else:
            out += b'\xdb' + struct.pack('>I', n)
        out += raw
    elif isinstance(value, (list, tuple)):
        n = len(value)
        if n < 16:
            out.append(0x90 | n)
        else:
            out += (b'\xdc' + struct.pack('>H', n)) if n <= 0xffff else (b'\xdd' + struct.pack('>I', n))
        for item in value:
            pack(item, out)
    elif isinstance(value, dict):
        n = len(value)
        if n < 16:
            out.append(0x80 | n)
        else:
            out += b'\xde' + struct.pack('>H', n)
        for key, item in value.items():
            pack(key, out)
            pack(item, out)
    else:
        raise TypeError(type(value))
    return out


class Reader:
    def __init__(self, data, at=0):
        self.data, self.at = data, at

    def done(self):
        return self.at >= len(self.data)

    def take(self, n):
        piece = self.data[self.at:self.at + n]
        self.at += n
        return piece

    def num(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def next(self):
        b = self.data[self.at]
        self.at += 1
        if b < 0x80:
            return b
        if b >= 0xe0:
            return b - 0x100
        if 0x80 <= b <= 0x8f:
            return self.map(b & 15)
        if 0x90 <= b <= 0x9f:
            return [self.next() for _ in range(b & 15)]
        if 0xa0 <= b <= 0xbf:
            return self.take(b & 31).decode('utf8', 'replace')
        if b == 0xc0:
            return None
        if b in (0xc2, 0xc3):
            return b == 0xc3
        if b in (0xc4, 0xc5, 0xc6):
            return Bin(self.take(self.num({0xc4: '>B', 0xc5: '>H', 0xc6: '>I'}[b])))
        if b == 0xca:
            return F32(self.num('>f'))
        if b == 0xcb:
            return self.num('>d')
        if 0xcc <= b <= 0xcf:
            return self.num(('>B', '>H', '>I', '>Q')[b - 0xcc])
        if 0xd0 <= b <= 0xd3:
            return self.num(('>b', '>h', '>i', '>q')[b - 0xd0])
        if b in (0xd9, 0xda, 0xdb):
            return self.take(self.num({0xd9: '>B', 0xda: '>H', 0xdb: '>I'}[b])).decode('utf8', 'replace')
        if b in (0xdc, 0xdd):
            return [self.next() for _ in range(self.num('>H' if b == 0xdc else '>I'))]
        if b in (0xde, 0xdf):
            return self.map(self.num('>H' if b == 0xde else '>I'))
        raise ValueError(f'msgpack byte {b:#x} at {self.at - 1}')

    def map(self, n):
        out = {}
        for _ in range(n):
            key = self.next()
            out[key] = self.next()
        return out

    def vector(self):
        """(count, element bytes, data)."""
        return self.next(), self.next(), self.next()


# --- reading ------------------------------------------------------------------------------------

SHAPE_VECTORS = ('nodes', 'objects', 'subShapeFirstNode', 'subShapeFirstObject', 'subShapeNumNodes',
                 'subShapeNumObjects', 'defaultRotations', 'defaultTranslations', 'nodeRotations',
                 'nodeTranslations', 'nodeUniformScales', 'nodeAlignedScales', 'nodeArbitraryScaleFactors',
                 'nodeArbitraryScaleRots', 'groundTranslations', 'groundRotations', 'objectStates',
                 'triggers', 'details')
MESH_VECTORS = ('verts', 'tverts', 'tverts2', 'colors', 'norms', 'encodedNorms', 'primitives', 'indices',
                'tangents')
SEQUENCE_FIELDS = ('nameIndex', 'flags', 'numKeyframes', 'duration', 'priority', 'firstGroundFrame',
                   'numGroundFrames', 'baseRotation', 'baseTranslation', 'baseScale', 'baseObjectState',
                   'baseDecalState', 'firstTrigger', 'numTriggers', 'toolBegin', 'rotationMatters',
                   'translationMatters', 'scaleMatters', 'visMatters', 'frameMatters', 'matFrameMatters')


def read(path):
    """A shape as a dict of raw fields (vectors stay (count, element bytes, bytes))."""
    data = Path(path).read_bytes()
    version, header_size = struct.unpack_from('<iI', data)
    if version & 0xff != VERSION:
        raise ValueError(f'{path}: version {version & 0xff}, not {VERSION}')
    header = Reader(data, 8).next()
    body = data[8 + header_size:]
    if header.get('compression'):
        import zstandard
        body = zstandard.ZstdDecompressor().decompress(body)
    r = Reader(body)
    shape = {'version': version, 'header': header, 'bodyBytes': len(body)}
    for name in ('smallestVisibleSize', 'smallestVisibleDL', 'radius', 'tubeRadius', 'center', 'bounds'):
        shape[name] = r.next()
    for name in SHAPE_VECTORS:
        shape[name] = r.vector()
    shape['names'] = [r.next() for _ in range(r.next())]
    meshes = shape['meshes'] = []
    for _ in range(r.next()):
        mesh = {'type': r.next()}
        meshes.append(mesh)
        if mesh['type'] == NULL_MESH:
            continue
        for name in ('numFrames', 'numMatFrames', 'parentMesh', 'bounds', 'center', 'radius'):
            mesh[name] = r.next()
        for name in MESH_VECTORS:
            mesh[name] = r.vector()
        mesh['vertsPerFrame'] = r.next()
        mesh['flags'] = r.next()
        if mesh['type'] == 1:
            parent = mesh['parentMesh'] < 0
            names = (('initialVerts', 'initialNorms') if parent else ()) + ('initialTransforms',) + \
                (('vertexIndex', 'boneIndex', 'weight', 'nodeIndex') if parent else ())
            for name in names:
                mesh[name] = r.vector()
    shape['sequences'] = [{name: r.next() for name in SEQUENCE_FIELDS} for _ in range(r.next())]
    shape['materials'] = []
    if not r.done():
        for _ in range(r.next()):
            shape['materials'].append({name: r.next() for name in
                                       ('name', 'flags', 'reflectanceMap', 'bumpMap', 'detailMap',
                                        'detailScale', 'reflectionAmount')})
    shape['left'] = len(body) - r.at
    return shape


def brief(value):
    if isinstance(value, tuple) and len(value) == 3 and isinstance(value[2], bytes):
        count, size, data = value
        head = data[:min(len(data), 48)].hex(' ', 4)
        return f'vector {count} x {size} B  [{head}{" ..." if len(data) > 48 else ""}]'
    if isinstance(value, Bin):
        return f'bin {len(value)} B [{value[:32].hex(" ", 4)}]'
    return repr(value)


def dump(path, say=print):
    shape = read(path)
    for name, value in shape.items():
        if name == 'meshes':
            for i, mesh in enumerate(value):
                say(f'mesh {i}:')
                for key, item in mesh.items():
                    say(f'    {key}: {brief(item)}')
        elif name in ('sequences', 'materials', 'names'):
            say(f'{name}: {value}')
        else:
            say(f'{name}: {brief(value)}')
    return shape


# --- writing ------------------------------------------------------------------------------------

def vector(out, count, size, data=b''):
    pack(count, out)
    pack(size, out)
    pack(Bin(data), out)


def bounds_of(positions):
    """(min x, y, z, max x, y, z) of a flat float list."""
    xs, ys, zs = positions[0::3], positions[1::3], positions[2::3]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def sphere_of(box):
    centre = ((box[0] + box[3]) / 2, (box[1] + box[4]) / 2, (box[2] + box[5]) / 2)
    radius = math.dist(centre, box[3:]) if hasattr(math, 'dist') else 0
    tube = math.hypot(box[3] - centre[0], box[4] - centre[1])
    return centre, radius, tube


def tangents_of(normals):
    """A tangent for each normal: world +x laid into the surface, handedness -1 as the game bakes it."""
    out = []
    for i in range(0, len(normals), 3):
        nx, ny, nz = normals[i:i + 3]
        tx, ty, tz = 1 - nx * nx, -nx * ny, -nx * nz
        length = math.sqrt(tx * tx + ty * ty + tz * tz)
        if length < 1e-6:
            tx, ty, tz, length = 0.0, 1.0, 0.0, 1.0
        out += (tx / length, ty / length, tz / length, -1.0)
    return out


def write(path, meshes, visible_size=2.0, compress=False):
    """Write a static shape of one detail level.

    meshes: [{'name', 'positions' (flat xyz), 'normals' (flat xyz), 'uvs' (flat uv, v down as the
    engine reads it), 'parts': [(material name, [vertex indices, three a triangle, clockwise from
    the front: the engine draws and collides that side only])]}]. Each mesh is an
    object of the shape; each part is one draw call with its material. Returns the bytes written.
    """
    materials, names = [], []

    def name_index(name):
        if name not in names:
            names.append(name)
        return names.index(name)

    def material_index(name):
        if name not in materials:
            materials.append(name)
        return materials.index(name)

    body = bytearray()
    every = [v for mesh in meshes for v in mesh['positions']]
    box = bounds_of(every)
    centre, radius, tube = sphere_of(box)
    # the node tree a Collada import leaves: base00 > start01 > the node of the detail level
    size_name = str(int(visible_size))
    base, start, holder = name_index('base00'), name_index('start01'), name_index('tile' + size_name)
    nodes = struct.pack('<5i', base, -1, -1, 1, -1) + struct.pack('<5i', start, 0, -1, 2, -1) + \
        struct.pack('<5i', holder, 1, 0, -1, -1)
    objects = b''
    states = b''
    for i, mesh in enumerate(meshes):
        last = i == len(meshes) - 1
        objects += struct.pack('<6i', name_index(mesh['name']), 1, i, 2, -1 if last else i + 1, -1)
        states += struct.pack('<fii', 1.0, 0, 0)
    triangles = sum(len(part[1]) for mesh in meshes for part in mesh['parts']) // 3
    details = struct.pack('<3i3fi2i2IfI', name_index('detail' + size_name), 0, 0, visible_size, -1.0, -1.0, triangles, 0, 0, 0, 0, 0.0, 0)

    pack(F32(visible_size), body)
    pack(0, body)
    pack(F32(radius), body)
    pack(F32(tube), body)
    pack([F32(v) for v in centre], body)
    pack([F32(v) for v in box], body)
    vector(body, 3, 20, nodes)
    vector(body, len(meshes), 24, objects)
    vector(body, 1, 4, struct.pack('<i', 0))                 # subShapeFirstNode
    vector(body, 1, 4, struct.pack('<i', 0))                 # subShapeFirstObject
    vector(body, 1, 4, struct.pack('<i', 3))                 # subShapeNumNodes
    vector(body, 1, 4, struct.pack('<i', len(meshes)))       # subShapeNumObjects
    identity = struct.pack('<4h', 0, 0, 0, 32766)
    vector(body, 3, 8, identity * 3)                         # defaultRotations
    vector(body, 3, 12, bytes(36))                           # defaultTranslations
    for size in (8, 12, 4, 12, 12, 8, 12, 8):                # node animation, ground: none
        vector(body, 0, size)
    vector(body, len(meshes), 12, states)
    vector(body, 0, 8)                                       # triggers
    vector(body, 1, 52, details)
    # the meshes come after the names in the file, so collect names of materials first
    packed = bytearray()
    pack(len(meshes), packed)
    for mesh in meshes:
        positions = mesh['positions']
        count = len(positions) // 3
        if count > MESH_VERTICES:
            raise ValueError(f"{mesh['name']}: {count} vertices; the engine draws a mesh with 16-bit indices")
        mbox = bounds_of(positions)
        mcentre, mradius, _ = sphere_of(mbox)
        indices, primitives = [], b''
        for material, part in mesh['parts']:
            primitives += struct.pack('<3I', len(indices), len(part),
                                      TRIANGLES | INDEXED | material_index(material))
            indices.extend(part)
        pack(STANDARD_MESH, packed)
        pack(1, packed)                                      # numFrames
        pack(1, packed)                                      # numMatFrames
        pack(-1, packed)                                     # parentMesh
        pack([F32(v) for v in mbox], packed)
        pack([F32(v) for v in mcentre], packed)
        pack(F32(mradius), packed)
        vector(packed, count, 12, struct.pack(f'<{count * 3}f', *positions))
        vector(packed, count, 8, struct.pack(f'<{count * 2}f', *mesh['uvs']))
        vector(packed, 0, 8)                                 # tverts2
        vector(packed, 0, 4)                                 # colors
        vector(packed, count, 12, struct.pack(f'<{count * 3}f', *mesh['normals']))
        vector(packed, 0, 1)                                 # encodedNorms
        vector(packed, len(mesh['parts']), 12, primitives)
        vector(packed, len(indices), 4, struct.pack(f'<{len(indices)}I', *indices))
        tangents = mesh.get('tangents') or tangents_of(mesh['normals'])
        vector(packed, count, 16, struct.pack(f'<{count * 4}f', *tangents))
        pack(count, packed)                                  # vertsPerFrame
        pack(0, packed)                                      # flags
    pack(len(names), body)
    for name in names:
        pack(name, body)
    body += packed
    pack(0, body)                                            # sequences
    pack(len(materials), body)
    for index, name in enumerate(materials):
        pack(name, body)
        pack(3, body)                                        # S_Wrap | T_Wrap
        pack(index, body)                                    # reflectanceMap: the game writes the index
        pack(0xffffffff, body)                               # bump and detail maps: none
        pack(0xffffffff, body)
        pack(F32(1.0), body)
        pack(F32(1.0), body)

    size = len(body)
    if compress:
        import zstandard
        body = zstandard.ZstdCompressor().compress(bytes(body))
    header = pack({'info': INFO, 'compression': bool(compress), 'bodysize': size,
                   'objectNames': [mesh['name'] for mesh in meshes]}, bytearray())
    data = struct.pack('<iI', VERSION | EXPORTER << 16, len(header)) + bytes(header) + bytes(body)
    if path is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(data)
    return data


def grid(n=100, size=100.0, materials=1, name='grid', wave=2.0):
    """A square of n x n cells with a wave in it, its cells dealt to the materials in stripes."""
    positions, normals, uvs = [], [], []
    step = size / n
    for j in range(n + 1):
        for i in range(n + 1):
            x, y = i * step - size / 2, j * step - size / 2
            z = wave * math.sin(x * 0.2) * math.cos(y * 0.2)
            dx, dy = wave * 0.2 * math.cos(x * 0.2) * math.cos(y * 0.2), -wave * 0.2 * math.sin(x * 0.2) * math.sin(y * 0.2)
            length = math.sqrt(dx * dx + dy * dy + 1)
            positions += (x, y, z)
            normals += (-dx / length, -dy / length, 1 / length)
            uvs += (x / 4, -y / 4)
    parts = [[] for _ in range(materials)]
    for j in range(n):
        part = parts[j * materials // n]
        for i in range(n):
            a = j * (n + 1) + i
            b, c, d = a + 1, a + n + 1, a + n + 2
            part += (a, d, b, a, c, d)       # clockwise from above: the engine's front
    return {'name': name, 'positions': positions, 'normals': normals, 'uvs': uvs,
            'parts': [(f'e2r_cdae_test_{k}', part) for k, part in enumerate(parts)]}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = p.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('dump')
    d.add_argument('file', type=Path)
    g = sub.add_parser('grid')
    g.add_argument('file', type=Path)
    g.add_argument('--n', type=int, default=100)
    g.add_argument('--materials', type=int, default=1)
    args = p.parse_args(argv)
    if args.cmd == 'dump':
        dump(args.file)
    else:
        data = write(args.file, [grid(args.n, materials=args.materials)])
        print(f'{args.file}: {len(data)} bytes')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    main()
