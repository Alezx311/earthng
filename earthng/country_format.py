"""Binary source cells of native country packages (earthng-features-v2).

A region stores its 1 km source cells in blocks of BLOCK x BLOCK cells, one file per block:

    block   := 'EGB2' varint(count) count * (varint(slot) varint(length)) payloads
    slot    := (i - bi*BLOCK) + (j - bj*BLOCK) * BLOCK, ascending
    payload := strings terrain roads junctions buildings areas lines points

All numbers are unsigned LEB128 varints; signed ones are zigzagged. Lengths, heights and
coordinates are integer centimetres, terrain heights decimetres. Every polyline or ring starts at the cell origin
(i*cellSize, j*cellSize, 0) and continues as deltas, so equal source points round to equal
integers in every cell and neighbouring tiles keep identical seams. The ZIP's deflate does the
general-purpose compression; the game reads these files with plain string.byte.

Packs are written as fixed-width blocks (EGB3, transcode_cell): the same header with magic
'EGB3', and in each cell the same string table followed by

    u32 count, count * u16 words, nx*ny * u16 heights

The words hold the varints a v2 cell has after its strings, in the same order and zigzagged
where v2 zigzags: a value under 0xffff is one word, a larger one is 0xffff and then its low and
high 16 bits (3 % of the values in the Kyiv oblast pack). The grid is the exception: nx, ny and
the cell's lowest height (decimetres, zigzag) stay among the values, and the heights follow the
words as decimetres above that lowest one. The game copies both parts into FFI arrays with one
ffi.copy each instead of decoding varints byte by byte (docs/RUST_IN_MOD.md). Deflated, a block is
~15 % larger than v2. Readers take both: decode_block reads either header, decode_cell and
decode_roads turn a v3 cell back into its v2 bytes, which are exactly the bytes encode_cell wrote.
"""
import math
import struct

import numpy as np

MAGIC = b'EGB2'
MAGIC3 = b'EGB3'
ESCAPE = 0xffff     # an EGB3 word: the value is in the next two words (low, high)
BLOCK = 8
SCALE = 100
TERRAIN = 10       # DEM heights: decimetres (the z12 source is metre-scale anyway)
KINDS = ('roads', 'junctions', 'buildings', 'areas', 'lines', 'points')


def _cm(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('non-finite source number')
    return int(round(value * SCALE))


class _Writer:
    def __init__(self):
        self.out = bytearray()

    def u(self, value):
        if value < 0:
            raise ValueError('negative unsigned varint')
        while value >= 0x80:
            self.out.append((value & 0x7f) | 0x80)
            value >>= 7
        self.out.append(value)

    def s(self, value):
        self.u(value * 2 if value >= 0 else -value * 2 - 1)


def _strings(cell):
    table = {}
    def add(value):
        if not isinstance(value, str):
            raise ValueError('source strings and tags must be text')
        table.setdefault(value, len(table))
    for kind in KINDS:
        for feature in cell.get(kind, []):
            add(str(feature['id']))
            if 'kind' in feature:
                add(feature['kind'])
            for key, value in (feature.get('tags') or {}).items():
                add(str(key)); add(str(value))
            for node in feature.get('nodes', []):
                add(str(node))
    return table


def encode_cell(cell, origin):
    """Bytes of one compiled cell; origin is the cell's south-west corner in region metres."""
    w, strings = _Writer(), _strings(cell)
    w.u(len(strings))
    for text in strings:
        data = text.encode('utf8')
        w.u(len(data)); w.out += data
    ox, oy = _cm(origin[0]), _cm(origin[1])

    def ref(value):
        w.u(strings[str(value)])

    def tags(value):
        value = value or {}
        w.u(len(value))
        for key in sorted(value):
            ref(str(key)); ref(str(value[key]))

    def line(points, minimum):
        if len(points) < minimum:
            raise ValueError('too few source coordinates')
        w.u(len(points))
        px, py, pz = ox, oy, 0
        out = w.out
        # _cm and _Writer.s by hand: a country's every coordinate passes here
        for p in points:
            n = len(p)
            if n != 2 and n != 3:
                raise ValueError('source points need two or three coordinates')
            try:
                x, y, z = round(p[0] * SCALE), round(p[1] * SCALE), round(p[2] * SCALE) if n == 3 else 0
            except (OverflowError, ValueError):
                raise ValueError('non-finite source number') from None
            for value in (x - px, y - py, z - pz):
                value = value * 2 if value >= 0 else -value * 2 - 1
                while value >= 0x80:
                    out.append((value & 0x7f) | 0x80)
                    value >>= 7
                out.append(value)
            px, py, pz = x, y, z

    def rings(value):
        if not value:
            raise ValueError('source polygon without rings')
        w.u(len(value))
        for ring in value:
            line(ring, 3)

    terrain = cell['terrain']
    heights = terrain['heights']
    if len(heights) != terrain['nx'] * terrain['ny']:
        raise ValueError('terrain size does not match its grid')
    w.u(terrain['nx']); w.u(terrain['ny'])
    previous = 0
    for h in heights:
        h = round(float(h) * TERRAIN)
        w.s(h - previous)
        previous = h
    for kind in KINDS:
        features = cell.get(kind, [])
        w.u(len(features))
        for f in features:
            ref(f['id'])
            if kind == 'roads':
                w.u(_cm(f['width'])); tags(f.get('tags'))
                w.u(len(f.get('nodes', [])))
                for node in f.get('nodes', []):
                    ref(node)
                line(f['points'], 2)
            elif kind == 'junctions':
                w.s(_cm(f['height'])); rings(f['rings'])
            elif kind == 'buildings':
                ref(f['kind']); w.u(_cm(f['height'])); w.u(_cm(f.get('minHeight', 0.)))
                tags(f.get('tags')); rings(f['rings'])
            elif kind == 'areas':
                ref(f['kind']); tags(f.get('tags')); rings(f['rings'])
            elif kind == 'lines':
                ref(f['kind']); tags(f.get('tags')); line(f['points'], 2)
            else:
                ref(f['kind']); tags(f.get('tags')); line([f['pos']], 1)
    return bytes(w.out)


class _Reader:
    def __init__(self, data, at=0, end=None):
        self.data, self.at, self.end = data, at, len(data) if end is None else end

    def u(self):
        value, shift = 0, 0
        while True:
            if self.at >= self.end or shift > 56:
                raise ValueError('truncated or invalid source varint')
            b = self.data[self.at]
            self.at += 1
            value |= (b & 0x7f) << shift
            if b < 0x80:
                return value
            shift += 7

    def s(self):
        value = self.u()
        return value >> 1 if value % 2 == 0 else -((value + 1) >> 1)

    def skip(self, count):
        """Past `count` varints."""
        data, at = self.data, self.at
        while count:
            if data[at] < 0x80:
                count -= 1
            at += 1
        self.at = at


def _strings_end(data, at, end):
    r = _Reader(data, at, end)
    for _ in range(r.u()):
        n = r.u()       # not `r.at += r.u()`: that adds to r.at as it was before the varint
        r.at += n
        if r.at > end:
            raise ValueError('truncated source string')
    return r.at


def _varints(buf):
    """Every LEB128 varint of buf, as int64 (each must fit in a u32)."""
    b = np.frombuffer(buf, np.uint8)
    if not len(b):
        return np.zeros(0, np.int64)
    ends = b < 0x80
    if not ends[-1]:
        raise ValueError('truncated source varint')
    group = np.cumsum(ends) - ends
    starts = np.flatnonzero(np.r_[True, ends[:-1]])
    shift = np.arange(len(b)) - starts[group]
    if shift.max() > 4:
        raise ValueError('source value over u32')
    values = np.bincount(group, weights=(b & 0x7f) * np.power(128.0, shift), minlength=len(starts))
    values = values.astype(np.int64)    # exact: every weight and sum is an integer under 2**35
    if values.max() >= 1 << 32:
        raise ValueError('source value over u32')
    return values


def _varint_bytes(values):
    """LEB128 bytes of non-negative int64 values (the shortest form, as _Writer.u writes)."""
    v = np.asarray(values, np.int64)
    if not len(v):
        return b''
    if v.min() < 0:
        raise ValueError('negative unsigned varint')
    v = v.astype(np.uint64)
    nb = np.ones(len(v), np.int64)
    for k in range(1, 10):
        nb += v >= np.uint64(1 << (7 * k))
    pos = np.cumsum(nb) - nb
    out = np.empty(int(nb.sum()), np.uint8)
    for k in range(int(nb.max())):
        sel = nb > k
        part = (v[sel] >> np.uint64(7 * k)) & np.uint64(0x7f)
        part |= (nb[sel] > k + 1).astype(np.uint64) << np.uint64(7)
        out[pos[sel] + k] = part
    return out.tobytes()


def _zig(v):
    v = np.asarray(v, np.int64)
    return np.where(v >= 0, 2 * v, -2 * v - 1)


def _unzig(v):
    v = np.asarray(v, np.int64)
    return np.where(v % 2 == 0, v // 2, -((v + 1) // 2))


def transcode_cell(payload):
    """One v2 cell (encode_cell's bytes) as an EGB3 cell (see the module docstring)."""
    payload = bytes(payload)
    s = _strings_end(payload, 0, len(payload))
    values = _varints(payload[s:])
    if len(values) < 2:
        raise ValueError('invalid source elevation grid')
    nx, ny = int(values[0]), int(values[1])
    n = nx * ny
    if len(values) < 2 + n:
        raise ValueError('truncated source elevation grid')
    heights = np.cumsum(_unzig(values[2:2 + n])) if n else np.zeros(0, np.int64)
    base = int(heights.min()) if n else 0
    relief = heights - base
    if n and relief.max() > 0xffff:
        raise ValueError('cell relief over the u16 range')
    rest = np.concatenate([np.array([nx, ny, int(_zig(base))], np.int64), values[2 + n:]])
    if rest.max() >= 1 << 32:
        raise ValueError('source value over u32')
    big = rest >= ESCAPE
    pos = np.cumsum(1 + 2 * big) - (1 + 2 * big)
    words = np.empty(len(rest) + 2 * int(big.sum()), np.int64)
    words[pos] = np.where(big, ESCAPE, rest)
    words[pos[big] + 1] = rest[big] & 0xffff
    words[pos[big] + 2] = rest[big] >> 16
    return (payload[:s] + struct.pack('<I', len(words)) + words.astype('<u2').tobytes()
            + relief.astype('<u2').tobytes())


def cell_to_v2(payload):
    """An EGB3 cell back as the v2 bytes it was transcoded from."""
    payload = bytes(payload)
    s = _strings_end(payload, 0, len(payload))
    if s + 4 > len(payload):
        raise ValueError('truncated source cell')
    (count,) = struct.unpack_from('<I', payload, s)
    after = s + 4 + 2 * count
    if count < 3 or after > len(payload):
        raise ValueError('truncated source cell')
    values = _words(np.frombuffer(payload, '<u2', count, s + 4).astype(np.int64))
    if len(values) < 3:
        raise ValueError('truncated source cell')
    nx, ny, n = int(values[0]), int(values[1]), int(values[0] * values[1])
    if after + 2 * n != len(payload):
        raise ValueError('source cell size mismatch')
    heights = int(_unzig(values[2])) + np.frombuffer(payload, '<u2', n, after).astype(np.int64)
    deltas = np.diff(heights, prepend=0)
    out = np.concatenate([np.array([nx, ny], np.int64), _zig(deltas), values[3:]])
    return payload[:s] + _varint_bytes(out)


def _words(words):
    """The values of EGB3 words: an escape (0xffff) and the two words after it are one value."""
    keep = np.ones(len(words), bool)
    values = words.copy()
    skip = -1
    for k in np.flatnonzero(words == ESCAPE).tolist():
        if k <= skip:
            continue        # the low or high half of an escaped value
        if k + 2 >= len(words):
            raise ValueError('truncated source cell')
        values[k] = words[k + 1] | (words[k + 2] << 16)
        keep[k + 1] = keep[k + 2] = False
        skip = k + 2
    return values[keep]


def _v2_cell(data, at, end):
    """data[at:end] of a block as v2 bytes: (data, at, end) unchanged for a v2 block, the cell
    alone for a v3 block (cells start after the 4-byte magic, so at >= 5; a bare payload has 0)."""
    if at >= 5 and bytes(data[:4]) == MAGIC3:
        cell = cell_to_v2(data[at:len(data) if end is None else end])
        return cell, 0, len(cell)
    return data, at, end


def decode_cell(data, origin, rect, at=0, end=None):
    """The table Lua builds from encode_cell's bytes (reference decoder for tests)."""
    data, at, end = _v2_cell(data, at, end)
    r = _Reader(data, at, end)
    strings = []
    for _ in range(r.u()):
        n = r.u()
        if r.at + n > r.end:
            raise ValueError('truncated source string')
        strings.append(bytes(data[r.at:r.at + n]).decode('utf8'))
        r.at += n
    ref = lambda: strings[r.u()]
    ox, oy = _cm(origin[0]), _cm(origin[1])

    def tags():
        return {ref(): ref() for _ in range(r.u())}

    def line():
        out, px, py, pz = [], ox, oy, 0
        for _ in range(r.u()):
            px += r.s(); py += r.s(); pz += r.s()
            out.append([px / SCALE, py / SCALE, pz / SCALE])
        return out

    def rings():
        return [line() for _ in range(r.u())]

    nx, ny = r.u(), r.u()
    heights, h = [], 0
    for _ in range(nx * ny):
        h += r.s()
        heights.append(h / TERRAIN)
    cell = {'terrain': {'rect': list(rect), 'nx': nx, 'ny': ny, 'heights': heights}}
    for kind in KINDS:
        features = cell[kind] = []
        for _ in range(r.u()):
            f = {'id': ref()}
            if kind == 'roads':
                f['width'] = r.u() / SCALE; f['tags'] = tags()
                f['nodes'] = [ref() for _ in range(r.u())]
                f['points'] = line()
            elif kind == 'junctions':
                f['height'] = r.s() / SCALE; f['rings'] = rings()
            elif kind == 'buildings':
                f['kind'] = ref(); f['height'] = r.u() / SCALE; f['minHeight'] = r.u() / SCALE
                f['tags'] = tags(); f['rings'] = rings()
            elif kind == 'areas':
                f['kind'] = ref(); f['tags'] = tags(); f['rings'] = rings()
            elif kind == 'lines':
                f['kind'] = ref(); f['tags'] = tags(); f['points'] = line()
            else:
                f['kind'] = ref(); f['tags'] = tags(); f['pos'] = line()[0]
            features.append(f)
    if r.at != r.end:
        raise ValueError('trailing bytes after source cell')
    return cell


def decode_roads(data, origin, at, end, seen):
    """The roads of a cell, as decode_cell gives them, that `seen` (a set of ids it adds to) has
    not had: a road is stored whole in every cell it crosses. Stops where the roads end, and steps
    over what it does not need: routing reads a country this way, most of a cell is buildings."""
    data, at, end = _v2_cell(data, at, end)
    r = _Reader(data, at, end)
    strings = []
    for _ in range(r.u()):
        n = r.u()
        strings.append((r.at, r.at + n))
        r.at += n
    text = lambda: bytes(data[slice(*strings[r.u()])]).decode('utf8')
    r.skip(r.u() * r.u())
    ox, oy, out = _cm(origin[0]), _cm(origin[1]), []
    for _ in range(r.u()):
        ident = text()
        if ident in seen:
            r.u()
            r.skip(2 * r.u())
            r.skip(r.u())
            r.skip(3 * r.u())
            continue
        seen.add(ident)
        f = {'id': ident, 'width': r.u() / SCALE}
        f['tags'] = {text(): text() for _ in range(r.u())}
        f['nodes'] = [text() for _ in range(r.u())]
        points, px, py, pz = [], ox, oy, 0
        for _ in range(r.u()):
            px += r.s(); py += r.s(); pz += r.s()
            points.append([px / SCALE, py / SCALE, pz / SCALE])
        f['points'] = points
        out.append(f)
    return out


def slot(i, j):
    return (i % BLOCK) + (j % BLOCK) * BLOCK


def encode_block(payloads, fixed=False):
    """payloads: {slot: bytes} (encode_cell's). Returns the block file and its 64-bit presence
    mask (hex); fixed: an EGB3 block (transcode_cell of every payload)."""
    w = _Writer()
    w.out += MAGIC3 if fixed else MAGIC
    if fixed:
        payloads = {k: transcode_cell(v) for k, v in payloads.items()}
    slots = sorted(payloads)
    w.u(len(slots))
    for k in slots:
        if not 0 <= k < BLOCK * BLOCK:
            raise ValueError('cell slot outside its block')
        w.u(k); w.u(len(payloads[k]))
    for k in slots:
        w.out += payloads[k]
    return bytes(w.out), mask(slots)


def mask(slots):
    """16 hex digits; digit d (first = 0) holds slots 4d..4d+3 as bits 1, 2, 4, 8."""
    digits = [0] * (BLOCK * BLOCK // 4)
    for k in slots:
        digits[k // 4] |= 1 << (k % 4)
    return ''.join('0123456789abcdef'[d] for d in digits)


def decode_block(data):
    """{slot: (start, end)} byte ranges of the cells of a block file."""
    if bytes(data[:4]) not in (MAGIC, MAGIC3):
        raise ValueError('not an EarthNG source block')
    r = _Reader(data, 4)
    entries = [(r.u(), r.u()) for _ in range(r.u())]
    out, at = {}, r.at
    for k, n in entries:
        out[k] = (at, at + n)
        at += n
    if at != len(data):
        raise ValueError('source block size mismatch')
    return out
