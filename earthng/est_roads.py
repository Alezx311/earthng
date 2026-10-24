"""Estonian road register (Transpordiamet Teeregister) details joined onto the OSM source tiles.

OSM maps few guard rails and no shoulders; the register has both for the state roads. Its
public WFS gives carriageway width and left / right shoulder per section (n_katlai) and the
guard rails (n_piire). The register draws each carriageway's axis, so an OSM carriageway
lies within a few metres of its sections:

- a state road's OSM way gets `width`, `shoulder:left:width`, `shoulder:right:width` (left
  and right of the way's node order) and `e2r:rails=register` (the generator then trusts
  the register for its rails and draws no rule-made ones near bridges);
- a register rail is placed at the matched OSM way's edge (its own position is only the
  axis offset by a default distance) and written as a new barrier=guard_rail way.

Local roads (7-digit numbers) are left alone: their widths are whole metres and often the
lane, not the street. The source tiles are copied, never edited: the enriched copy has its
own directory and checksums, so the OSM-only cache stays valid.

Data: Transpordiamet, Teeregister (CC BY 4.0 per andmed.eesti.ee; the WFS itself still
says "private" - confirm before redistributing a pack built with it).
"""
import hashlib
import json
import math
from pathlib import Path
import shutil
import urllib.request

WFS = ('https://teeregister.mnt.ee/290424/wfs?service=WFS&version=1.1.0&request=GetFeature'
       '&typeName=ms:{layer}&bbox={bbox}&outputFormat=application/json;%20subtype=geojson')
AGENT = 'EarthNG/0.1 (+https://github.com/Alezx311/earthng)'
LAYERS = ('n_katlai', 'n_piire')
VERSION = 'register-1'
STATE = 1_000_000          # register numbers of local roads have 7 digits
MATCH = 4.0                # m: an OSM carriageway and the register's section of it
RAIL_MATCH = 6.0           # m: a rail's axis and its OSM way (the axis is generated too)
PARALLEL = .8              # |cos| between the OSM way and the section
SAMPLE = 5.0               # m between the samples of an OSM way voting for its section
RAIL_STEP = 2.0            # m between the samples of a rail
RAIL_OFFSET = .5           # m outside the asphalt: generator.lua ROADS.rail.offset
RAIL_MIN = 4.0             # m: shorter pieces are dropped
RAIL_TYPES = {'1', '3', '8'}   # w-profile, concrete, double w-profile (91: pedestrian fence)
SIDE = {'VASAKUL': 1, 'PAREMAL': -1}
DUPLICATE = 3.0            # m: an OSM-mapped rail already stands there
ROAD_CLEAR = .2            # m outside another road's asphalt a rail may not reach (< RAIL_OFFSET)
SYNTHETIC = 4_000_000_000_000_000   # ids of the written rail nodes and ways (< 2**53)


def register_box(box):
    """The L-EST97 (EPSG:3301) box around a WGS84 (W, S, E, N) box, whole metres outward."""
    from pyproj import Transformer
    to = Transformer.from_crs(4326, 3301, always_xy=True)
    w, s, e, n = box
    xs, ys = to.transform([w, e, w, e, (w + e) / 2, (w + e) / 2], [s, s, n, n, s, n])
    return [math.floor(min(xs)), math.floor(min(ys)), math.ceil(max(xs)), math.ceil(max(ys))]


def fetch(box, cache, emit=print, opener=None):
    """{layer: [GeoJSON feature]} of LAYERS inside the WGS84 box, cached by the box."""
    rbox = register_box(box)
    key = ','.join(str(v) for v in rbox)
    folder = Path(cache) / 'teeregister'
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for layer in LAYERS:
        path = folder / f"{layer}-{hashlib.sha256(key.encode()).hexdigest()[:10]}.json"
        if not path.exists():
            emit(f'road register: downloading {layer}')
            request = urllib.request.Request(WFS.format(layer=layer, bbox=key), headers={'User-Agent': AGENT})
            with (opener or urllib.request.urlopen)(request, timeout=120) as response:
                data = json.loads(response.read().decode('utf-8'))
            if not isinstance(data.get('features'), list):
                raise ValueError(f'road register {layer}: no features in the answer')
            part = path.with_suffix('.part')
            part.write_text(json.dumps(data), encoding='utf-8')
            part.replace(path)
        out[layer] = json.loads(path.read_text(encoding='utf-8'))['features']
    return out


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _tangent(line, s):
    """Unit direction of a shapely line at distance s along it."""
    length = line.length
    a, b = line.interpolate(max(0., s - 1.)), line.interpolate(min(length, s + 1.))
    dx, dy = b.x - a.x, b.y - a.y
    d = math.hypot(dx, dy) or 1.
    return dx / d, dy / d


def _refs(tags):
    return {r.strip() for r in str(tags.get('ref', '')).split(';') if r.strip()}


def _text(v):
    return f'{v:.2f}'.rstrip('0').rstrip('.')


class Register:
    """The register's state-road sections and rails in L-EST97, searchable."""

    def __init__(self, layers):
        import shapely
        self.sections, self.rails = [], []
        for f in layers.get('n_katlai', []):
            p, g = f.get('properties') or {}, f.get('geometry') or {}
            number = _number(p.get('tee_number'))
            if g.get('type') != 'LineString' or number is None or number >= STATE:
                continue
            carriage = _number(p.get('slai')) or _number(p.get('katlai'))
            if not carriage:
                continue
            self.sections.append((shapely.LineString(g['coordinates']), {
                'road': int(number), 'carriage': carriage,
                'left': _number(p.get('plaiv')), 'right': _number(p.get('plaip'))}))
        for f in layers.get('n_piire', []):
            p, g = f.get('properties') or {}, f.get('geometry') or {}
            number = _number(p.get('tee_number'))
            side = SIDE.get(str(p.get('viitepunkti_suund_nvps_xv', '')).upper())
            if g.get('type') != 'LineString' or number is None or side is None:
                continue
            if str(p.get('piiretyyp_piiretyyp_xv', '1')) not in RAIL_TYPES:
                continue
            self.rails.append((shapely.LineString(g['coordinates']), {
                'road': int(number), 'side': side, 'offset': _number(p.get('viitepunkt')) or 0.,
                'type': p.get('piiretyyp_piiretyyp_val') or ''}))
        self.tree = shapely.STRtree([g for g, _ in self.sections])

    def section_at(self, point, tangent, limit=MATCH):
        """(section info, same direction) of the nearest parallel section within limit, else None."""
        best = None
        for j in self.tree.query(point.buffer(limit)):
            line, info = self.sections[j]
            d = line.distance(point)
            if d > limit:
                continue
            tx, ty = _tangent(line, line.project(point))
            dot = tx * tangent[0] + ty * tangent[1]
            if abs(dot) < PARALLEL:
                continue
            if best is None or d < best[0]:
                best = (d, info, dot > 0)
        return best and best[1:]


def width_tags(tags, line, register):
    """Register tags for one OSM way (shapely line in L-EST97), or {} when it has no section.
    Most of the way's samples must agree on one section."""
    import fast_sources as road_widths
    if tags.get('width') is not None:
        return {}
    votes, samples = {}, 0
    n = max(1, int(line.length // SAMPLE))
    for k in range(n):
        s = (k + .5) * line.length / n
        samples += 1
        hit = register.section_at(line.interpolate(s), _tangent(line, s))
        if hit:
            info, same = hit
            key = (info['carriage'], info['left'], info['right'], same)
            votes[key] = votes.get(key, 0) + 1
    if not votes:
        return {}
    (carriage, left, right, same), count = max(votes.items(), key=lambda kv: (kv[1], kv[0][0]))
    if count * 2 < samples:
        return {}
    if left is None or right is None:
        default = road_widths.shoulder(tags)
        left = default[0] if left is None else left
        right = default[1] if right is None else right
    if not same:
        left, right = right, left
    width = carriage + left + right
    if not .6 <= width / road_widths.road_width(tags) <= 1.8:
        return {}
    return {'width': _text(width), 'shoulder:left:width': _text(left), 'shoulder:right:width': _text(right),
            'e2r:rails': 'register'}


def _offset_piece(line, s0, s1, offset):
    """The part s0..s1 of line, offset metres to its left (negative: right)."""
    from shapely.ops import substring
    piece = substring(line, s0, s1)
    if piece.geom_type != 'LineString' or piece.length < RAIL_MIN:
        return None
    if offset == 0:
        return piece
    moved = piece.offset_curve(offset, join_style='mitre', mitre_limit=2.)
    if moved.geom_type == 'MultiLineString':
        moved = max(moved.geoms, key=lambda g: g.length)
    return moved if moved.geom_type == 'LineString' and moved.length >= RAIL_MIN else None


def rail_lines(register, ways, mapped_rails=()):
    """New guard rails [(L-EST97 coordinates, tags)]: every register rail on the edge of the OSM
    ways it runs along. ways: {id: (tags, shapely line in L-EST97)} with the final tags;
    mapped_rails: OSM rails (shapely lines) already drawn, not doubled."""
    import shapely
    import fast_sources as road_widths
    ids = list(ways)
    tree = shapely.STRtree([ways[i][1] for i in ids])
    mapped = shapely.STRtree(list(mapped_rails)) if mapped_rails else None
    out = []
    for rail, info in register.rails:
        # the register placed the rail info['offset'] m off its axis: walk the axis
        axis = rail.offset_curve(-info['side'] * info['offset']) if info['offset'] else rail
        if axis.geom_type != 'LineString' or axis.length == 0:
            axis = rail
        n = max(1, int(math.ceil(axis.length / RAIL_STEP)))
        runs = []
        for k in range(n + 1):
            s = axis.length * k / n
            p, t = axis.interpolate(s), _tangent(axis, s)
            best = None
            for j in tree.query(p.buffer(RAIL_MATCH)):
                tags, line = ways[ids[j]]
                d = line.distance(p)
                if d > RAIL_MATCH:
                    continue
                along = line.project(p)
                tx, ty = _tangent(line, along)
                dot = tx * t[0] + ty * t[1]
                if abs(dot) < PARALLEL:
                    continue
                score = d + (0 if str(info['road']) in _refs(tags) else 3.)
                if best is None or score < best[0]:
                    q = line.interpolate(along)
                    left = tx * (p.y - q.y) - ty * (p.x - q.x)       # the axis, left of the way
                    sign = 1 if dot > 0 else -1
                    best = (score, ids[j], along, sign, left + info['side'] * sign * info['offset'])
            if best is None:
                runs.append(None)
                continue
            _, wid, along, sign, lateral = best
            if runs and runs[-1] and runs[-1][0] == wid and runs[-1][1] == sign:
                runs[-1][3] = along
                runs[-1][4].append(lateral)
            else:
                runs.append([wid, sign, along, along, [lateral]])
        for run in runs:
            if not run:
                continue
            wid, sign, a, b, lateral = run
            tags, line = ways[wid]
            if tags.get('bridge') not in (None, 'no') or tags.get('tunnel') not in (None, 'no'):
                continue     # the deck has parapets; a tunnel has walls
            s0, s1 = min(a, b), max(a, b)
            half = road_widths.road_width(tags) / 2
            offset = info['side'] * sign * (half + RAIL_OFFSET)
            # the register's two carriageways under one two-way OSM way: its rail between them
            # lands on the asphalt, and stands on the way's centre line
            if not road_widths.oneway(tags) and abs(sorted(lateral)[len(lateral) // 2]) < half - 1.:
                offset = 0.
            piece = _offset_piece(line, s0, s1, offset)
            if piece is None:
                continue
            for part in _without_mapped(_off_roads(piece, wid, ways, ids, tree), mapped):
                out.append((list(part.coords), {
                    'barrier': 'guard_rail', 'source': 'Transpordiamet Teeregister',
                    'e2r:register': info['type'] or 'yes'}))
    return out


def _off_roads(piece, wid, ways, ids, tree):
    """piece without the stretches on another at-grade road (a side road's mouth: the register's
    chainage is approximate); a rail goes on under a bridge."""
    import shapely
    import fast_sources
    cut = []
    for j in tree.query(piece.buffer(20.)):
        tags, line = ways[ids[j]]
        if ids[j] == wid or tags.get('bridge') not in (None, 'no') or tags.get('tunnel') not in (None, 'no'):
            continue
        zone = line.buffer(fast_sources.road_width(tags) / 2 + ROAD_CLEAR)
        if zone.intersects(piece):
            cut.append(zone)
    if not cut:
        return piece
    return piece.difference(shapely.union_all(cut))


def _without_mapped(piece, mapped):
    """The LineString parts of piece without the stretches within DUPLICATE m of an OSM-mapped rail."""
    import shapely
    parts = list(piece.geoms) if hasattr(piece, 'geoms') else [piece]
    if len(parts) > 1:
        return [g for p in parts for g in _without_mapped(p, mapped)]
    piece = parts[0]
    if piece.geom_type != 'LineString' or piece.length < RAIL_MIN:
        return []
    if mapped is None:
        return [piece]
    near = [mapped.geometries[j] for j in mapped.query(piece.buffer(DUPLICATE))]
    if not near:
        return [piece]
    rest = piece.difference(shapely.union_all([g.buffer(DUPLICATE) for g in near]))
    parts = list(rest.geoms) if hasattr(rest, 'geoms') else [rest]
    return [g for g in parts if g.geom_type == 'LineString' and g.length >= RAIL_MIN]


def _osm_rails(path):
    """OSM barrier=guard_rail ways of one tile as [(lon, lat), ...]."""
    import osmium
    rails = []

    class Reader(osmium.SimpleHandler):
        def way(self, w):
            if w.tags.get('barrier') == 'guard_rail':
                pts = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
                if len(pts) >= 2:
                    rails.append(pts)

    Reader().apply_file(str(path), locations=True)
    return rails


def plan(tiles, layers):
    """(tag updates {way id: tags to add}, new rails [[(lon, lat), ...], tags]) for the source
    tiles directory from the register layers."""
    import shapely
    from pyproj import Transformer
    import fast_sources
    to = Transformer.from_crs(4326, 3301, always_xy=True)
    back = Transformer.from_crs(3301, 4326, always_xy=True)
    index = json.loads((Path(tiles) / 'index.json').read_text(encoding='utf-8'))
    roads, mapped = {}, []
    for tile in index['tiles'].values():
        path = Path(tiles) / tile['file']
        roads.update(fast_sources.read_roads(path, tile['sha256']))
        mapped += _osm_rails(path)
    register = Register(layers)

    def project(pts):
        xs, ys = to.transform([p[0] for p in pts], [p[1] for p in pts])
        return shapely.LineString(list(zip(xs, ys)))

    updates, ways = {}, {}
    for wid, (tags, nodes) in roads.items():
        line = project([(lon, lat) for _, lon, lat in nodes])
        if line.length == 0:
            continue
        add = width_tags(tags, line, register)
        if add:
            updates[wid] = add
        ways[wid] = ({**tags, **add}, line)
    rails = []
    for coords, tags in rail_lines(register, ways, [project(r) for r in mapped]):
        lons, lats = back.transform([c[0] for c in coords], [c[1] for c in coords])
        rails.append((list(zip(lons, lats)), tags))
    return updates, rails


def _write_tile(src, dst, updates, rails):
    """src copied to dst with the tag updates on its ways and the rails (with their nodes) added
    after its own nodes and ways; ids of the rails stay above every OSM id, in order."""
    import osmium
    from osmium.osm import mutable
    counts = {'nodes': 0, 'ways': 0, 'relations': 0}
    part = Path(str(dst) + '.part')
    writer = osmium.SimpleWriter(osmium.io.File(str(part), 'pbf'))
    phase = ['n']

    def flush(to):
        if phase[0] == 'n' and to in ('w', 'r'):
            for nid, lon, lat in (n for _, nodes, _ in rails for n in nodes):
                writer.add_node(mutable.Node(id=nid, location=(lon, lat), version=1))
                counts['nodes'] += 1
            phase[0] = 'w'
        if phase[0] == 'w' and to == 'r':
            for wid, nodes, tags in rails:
                writer.add_way(mutable.Way(id=wid, nodes=[n[0] for n in nodes], tags=tags, version=1))
                counts['ways'] += 1
            phase[0] = 'r'

    try:
        for obj in osmium.FileProcessor(str(src)):
            kind = obj.type_str()
            flush(kind)
            if kind == 'n':
                writer.add_node(obj)
                counts['nodes'] += 1
            elif kind == 'w':
                add = updates.get(obj.id)
                writer.add_way(obj.replace(tags={**dict(obj.tags), **add}) if add else obj)
                counts['ways'] += 1
            else:
                writer.add_relation(obj)
                counts['relations'] += 1
        flush('r')
    finally:
        writer.close()
    part.replace(dst)
    return counts


def enriched_dir(tiles, layers):
    digest = hashlib.sha256((VERSION + json.dumps(layers, sort_keys=True)).encode()).hexdigest()[:8]
    return Path(tiles).with_name(f'{Path(tiles).name}-register-{digest}')


def enrich(tiles, layers, emit=print):
    """The source tiles directory with the register joined on, built once next to tiles."""
    out = enriched_dir(tiles, layers)
    if (out / 'index.json').is_file():
        emit(f'road register: reusing {out.name}')
        return out
    index = json.loads((Path(tiles) / 'index.json').read_text(encoding='utf-8'))
    updates, rails = plan(tiles, layers)
    emit(f'road register: {len(updates)} ways get widths and shoulders, {len(rails)} guard rails added')
    numbered, next_id = [], SYNTHETIC
    for pts, tags in rails:
        nodes = []
        for lon, lat in pts:
            next_id += 1
            nodes.append((next_id, lon, lat))
        next_id += 1
        numbered.append((next_id, nodes, tags))
    work = out.with_name(out.name + '.part')
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    for tile in index['tiles'].values():
        w, s, e, n = tile['coverage']
        mine = [r for r in numbered if any(w <= lon <= e and s <= lat <= n for _, lon, lat in r[1])]
        dst = work / tile['file']
        counts = _write_tile(Path(tiles) / tile['file'], dst, updates, mine)
        tile.update(counts, bytes=dst.stat().st_size, sha256=hashlib.sha256(dst.read_bytes()).hexdigest())
    index['register'] = {'version': VERSION, 'ways': len(updates), 'rails': len(numbered),
                         'attribution': 'Transpordiamet, Teeregister (CC BY 4.0)'}
    (work / 'index.json').write_text(json.dumps(index, indent=1), encoding='utf-8')
    if out.exists():
        shutil.rmtree(out)
    work.replace(out)
    return out


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('tiles', type=Path, help='source tiles directory (osm_tiles index.json)')
    parser.add_argument('--cache', type=Path, required=True)
    a = parser.parse_args()
    index = json.loads((a.tiles / 'index.json').read_text(encoding='utf-8'))
    box = index['package_box']
    print(enrich(a.tiles, fetch(box, a.cache)))


if __name__ == '__main__':
    main()
