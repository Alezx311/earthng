"""Routing graph of a pack region (earthng-routing-v1, docs/NAVIGATION.md «Формат R4»).

The cells answer "what stands here"; this file answers "how to get there". It holds only the
drivable topology the game's navgraph is built from (generator.lua navSegment: the same classes,
access and one-way rules), so a route found here is a list of the navgraph's own junctions
(`e2r_n<OSM node id>`).

    file    := 'EGR1' u(version) strings nodes edges restrictions exits
    strings := u(n) n * (u(len) bytes)
    nodes   := u(n) n * (u(id - prev id) s(x - prev x) s(y - prev y))       ascending OSM id
    edges   := u(n) n * (u(a - prev a) s(b - a) u(length) u(flags) u(speed)
                         u(name) u(nameUk) u(nameEn) u(ref) u(k) k * (s(dx) s(dy)))
    restrictions, exits := u(0)                                             reserved

Numbers are LEB128 varints, signed ones zigzagged (country_format). Coordinates and lengths are
region-local decimetres; a ref is 1 + string index, 0 for none. Edges run from a to b, the
direction of travel of a one-way road, and are sorted by (a, b). Inner points are the edge's
bends after RDP at SIMPLIFY m, as deltas from the previous point (the first from node a).
"""
import math

MAGIC = b'EGR1'
VERSION = 1
SCALE = 10                  # decimetres
SIMPLIFY = 5.0              # m: route line on the map and turn angles, not the road surface

# generator.lua SPEED / DRIVE: the classes the navgraph carries, in flag order
CLASSES = ('motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential',
           'living_street')
SPEED = {'motorway': 110, 'trunk': 90, 'primary': 60, 'secondary': 60, 'tertiary': 50,
         'unclassified': 50, 'residential': 40, 'living_street': 20}
NO_ONEWAY = {'no', 'false', '0', 'reversible', 'alternating'}
LINK, ONEWAY, RING = 8, 16, 32          # flags above the 3-bit class


def _number(value, default):
    try:
        out = float(str(value).split(';')[0].strip().split(' ')[0])
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def oneway(tags):
    """(one-way, reversed) as generator.lua ROADS.oneway."""
    value = str(tags.get('oneway', '')).lower()
    if value == '-1':
        return True, True
    if value in ('yes', '1', 'true'):
        return True, False
    if value in NO_ONEWAY:
        return False, False
    return tags.get('highway') == 'motorway' or tags.get('junction') in ('roundabout', 'circular'), False


def speed_kmh(tags):
    """Signed speed as navSegment reads maxspeed; 0 means the class default."""
    text = str(tags.get('maxspeed', '')).lower()
    if text == 'none':
        return 130
    if 'urban' in text:
        return 50
    if 'rural' in text:
        return 90
    value = _number(text, 0)
    if 'mph' in text:
        value *= 1.609
    return max(0, min(250, int(round(value))))


def edge_of(road):
    """The routing edge of a pack road feature, or None where navSegment makes no navgraph."""
    tags, points, nodes = road.get('tags') or {}, road.get('points') or [], road.get('nodes') or []
    highway = str(tags.get('highway', 'residential'))
    base = highway[:-5] if highway.endswith('_link') else highway
    if base not in SPEED or tags.get('access') in ('private', 'no') or tags.get('area') == 'yes':
        return None
    if len(points) < 2 or len(nodes) < 2:
        return None
    one, flip = oneway(tags)
    xy = [(float(p[0]), float(p[1])) for p in points]
    a, b = str(nodes[0]), str(nodes[-1])
    if flip:
        xy.reverse()
        a, b = b, a
    length = sum(math.dist(xy[k], xy[k + 1]) for k in range(len(xy) - 1))
    if length <= 0:
        return None
    flags = CLASSES.index(base) | (LINK if base != highway else 0) | (ONEWAY if one else 0)
    if tags.get('junction') in ('roundabout', 'circular'):
        flags |= RING
    return {'a': a, 'b': b, 'xy': xy, 'length': length, 'flags': flags, 'speed': speed_kmh(tags),
            'name': tags.get('name'), 'nameUk': tags.get('name:uk'), 'nameEn': tags.get('name:en'),
            'ref': tags.get('ref')}


def simplify(xy, tolerance=SIMPLIFY):
    """Ramer-Douglas-Peucker keeping both ends."""
    if len(xy) <= 2:
        return list(xy)
    keep, stack = {0, len(xy) - 1}, [(0, len(xy) - 1)]
    while stack:
        i, j = stack.pop()
        (ax, ay), (bx, by) = xy[i], xy[j]
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        worst, at = tolerance * tolerance, None
        for k in range(i + 1, j):
            px, py = xy[k]
            f = 0 if length2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / length2))
            ex, ey = px - ax - f * dx, py - ay - f * dy
            if ex * ex + ey * ey > worst:
                worst, at = ex * ex + ey * ey, k
        if at is not None:
            keep.add(at)
            stack += [(i, at), (at, j)]
    return [xy[k] for k in sorted(keep)]


def graph(roads):
    """{nodes: [(osm id, x, y)], edges: [...]} from pack road features (region-local metres).

    A road crosses cells and is stored in each of them: features are taken once per id, and an
    edge between the same two nodes with the same length (to the decimetre) once."""
    seen, ends, edges, keys = set(), {}, [], set()
    for road in roads:
        rid = str(road.get('id'))
        if rid in seen:
            continue
        seen.add(rid)
        edge = edge_of(road)
        if edge is None:
            continue
        key = (edge['a'], edge['b'], int(round(edge['length'] * SCALE)), edge['flags'] & ONEWAY)
        if key in keys:
            continue
        keys.add(key)
        ends.setdefault(edge['a'], edge['xy'][0])
        ends.setdefault(edge['b'], edge['xy'][-1])
        edges.append(edge)
    ids = sorted(ends, key=int)
    return {'nodes': [(int(n), ends[n][0], ends[n][1]) for n in ids], 'edges': edges}


class _Writer:
    def __init__(self):
        self.out = bytearray(MAGIC)

    def u(self, value):
        if value < 0:
            raise ValueError('negative unsigned varint')
        while value >= 0x80:
            self.out.append((value & 0x7f) | 0x80)
            value >>= 7
        self.out.append(value)

    def s(self, value):
        self.u(value * 2 if value >= 0 else -value * 2 - 1)


def _dm(value):
    return int(round(float(value) * SCALE))


def encode(g):
    w = _Writer()
    w.u(VERSION)
    strings = {}
    for edge in g['edges']:
        for field in ('name', 'nameUk', 'nameEn', 'ref'):
            if edge.get(field):
                strings.setdefault(str(edge[field]), len(strings))
    w.u(len(strings))
    for text in strings:
        data = text.encode('utf8')
        w.u(len(data)); w.out += data
    index = {}
    w.u(len(g['nodes']))
    prev, px, py = 0, 0, 0
    for k, (nid, x, y) in enumerate(g['nodes']):
        if nid <= prev and k:
            raise ValueError('routing nodes must ascend by OSM id')
        index[str(nid)] = k
        qx, qy = _dm(x), _dm(y)
        w.u(nid - prev); w.s(qx - px); w.s(qy - py)
        prev, px, py = nid, qx, qy
    rows = sorted(((index[e['a']], index[e['b']], e) for e in g['edges']), key=lambda r: (r[0], r[1]))
    w.u(len(rows))
    prev_a = 0
    for a, b, e in rows:
        w.u(a - prev_a); w.s(b - a)
        prev_a = a
        w.u(max(1, _dm(e['length']))); w.u(e['flags']); w.u(e['speed'])
        for field in ('name', 'nameUk', 'nameEn', 'ref'):
            w.u(strings[str(e[field])] + 1 if e.get(field) else 0)
        inner = simplify(e['xy'])[1:-1]
        w.u(len(inner))
        px, py = g['nodes'][a][1], g['nodes'][a][2]
        qx, qy = _dm(px), _dm(py)
        for x, y in inner:
            rx, ry = _dm(x), _dm(y)
            w.s(rx - qx); w.s(ry - qy)
            qx, qy = rx, ry
    w.u(0)          # restrictions: from the raw cut once build_country writes this file
    w.u(0)          # exits: motorway_junction ref/name, likewise
    return bytes(w.out)


class _Reader:
    def __init__(self, data):
        self.data, self.at = data, 0

    def u(self):
        value, shift = 0, 0
        while True:
            if self.at >= len(self.data) or shift > 63:
                raise ValueError('truncated routing file')
            b = self.data[self.at]
            self.at += 1
            value |= (b & 0x7f) << shift
            if b < 0x80:
                return value
            shift += 7

    def s(self):
        v = self.u()
        return v // 2 if v % 2 == 0 else -(v + 1) // 2


def decode(data):
    """Reference decoder (tests): {strings, nodes: [(id, x, y)], edges: [{a, b, ...}]}."""
    if bytes(data[:4]) != MAGIC:
        raise ValueError('not an EarthNG routing file')
    r = _Reader(data)
    r.at = 4
    if r.u() != VERSION:
        raise ValueError('unsupported routing version')
    strings = []
    for _ in range(r.u()):
        n = r.u()
        strings.append(bytes(data[r.at:r.at + n]).decode('utf8'))
        r.at += n
    nodes, nid, x, y = [], 0, 0, 0
    for _ in range(r.u()):
        nid += r.u(); x += r.s(); y += r.s()
        nodes.append((nid, x / SCALE, y / SCALE))
    edges, a = [], 0
    for _ in range(r.u()):
        a += r.u()
        b = a + r.s()
        e = {'a': a, 'b': b, 'length': r.u() / SCALE, 'flags': r.u(), 'speed': r.u()}
        for field in ('name', 'nameUk', 'nameEn', 'ref'):
            ref = r.u()
            e[field] = strings[ref - 1] if ref else None
        qx, qy = round(nodes[a][1] * SCALE), round(nodes[a][2] * SCALE)
        inner = []
        for _ in range(r.u()):
            qx += r.s(); qy += r.s()
            inner.append((qx / SCALE, qy / SCALE))
        e['inner'] = inner
        edges.append(e)
    if r.u() != 0 or r.u() != 0 or r.at != len(data):
        raise ValueError('unexpected routing tail')
    return {'strings': strings, 'nodes': nodes, 'edges': edges}
