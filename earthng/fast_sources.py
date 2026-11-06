"""Cold-start OSM index for the streaming generator. No SUMO or generated meshes.

The index owns complete OSM ways and junction mouths, not tile-local decisions.
SQLite/RTree readers are independent and bounded; workers never copy a city graph.
"""
from collections import Counter, defaultdict, OrderedDict
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time

import numpy as np
from PIL import Image
import pyproj
import shapely
from shapely.geometry import LineString, MultiPoint, Point
from shapely.ops import transform

VERSION = 'fast-23'         # source index cache: combined railway tracks, level crossings, speed cameras and foot-bridge decks
GEOMETRY = 'fast-33'         # mesh/material semantics; bump to reject tiles built by older code
TILE = 500.0
ROAD_LIFT = 0.12            # road surface over its profile (the ground mesh sits 0.25 under the DEM)
LIFT = 20.0                 # absolute DEM heights + lift; never the carrier plane
CRS = 'EPSG:32636'          # the frame before fast-9 (Kyiv): old replay routes are in it
ORIGIN = (324000., 5590000.)
DRIVABLE = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'residential',
            'unclassified', 'service', 'living_street', 'road', 'raceway'}
# Foot and cycle ways on a bridge of their own: the deck's width without a width tag.
FOOT_REACH = 30.       # m: the street a foot bridge's end comes to (fast_profile.foot_decks)
FOOT_WIDTH = {'footway': 2.5, 'path': 2.0, 'pedestrian': 4.0, 'cycleway': 2.5, 'steps': 2.5, 'bridleway': 2.5}
SIDEWALK_REACH, SIDEWALK_SHARE = 6., .6     # a foot way this far past a road bridge's edge over this share of it is its sidewalk
DECK_SHARE = .6                             # a foot way this much inside a man_made=bridge outline is on that bridge


def number(value, default):
    try:
        return float(str(value).split(';')[0].replace(' m', '').replace(',', '.'))
    except (ValueError, TypeError):
        return default


# Lane width (m) by highway class when a way has no width tag. One 3.3 m lane for every class
# made a residential street as wide as a primary road (6.6 m) and the classes indistinguishable.
LANE_WIDTH = {'motorway': 3.75, 'trunk': 3.5, 'primary': 3.5, 'secondary': 3.25, 'tertiary': 3.0,
              'unclassified': 3.0, 'residential': 3.0, 'road': 3.0}
# A two-way road tagged lanes=1 is an unmarked road both directions share, not one lane wide:
# cars still pass each other on it (Estonian country roads are mapped so). Its carriageway is
# this share of two lanes, at least SHARED_MIN.
SHARED = .9
SHARED_MIN = 4.5
ONE_LANE_MIN = 4.0                                    # a one-way carriageway: lane plus margins
# A race track's carriageway (highway=raceway, sport=karting narrower) where no width is tagged.
RACEWAY = {'karting': 8.0}
RACEWAY_WIDTH = 12.0
NARROW = {'living_street': 4.5, 'service': 4.0}       # whole carriageway, any lane count
DRIVEWAY = 3.0                                        # service=driveway / alley
# Paved shoulder (m) outside the edge line, (left, right) of the direction, where a way has no
# width tag. The generator's ROADS.shoulder holds the same rule and paints the edge lines
# inside it.
SHOULDER = {'motorway': (.75, 2.5), 'trunk': (1., 1.), 'primary': (.5, .5), 'secondary': (.25, .25)}
SHOULDER_ONEWAY = {'trunk': (.5, 1.5), 'primary': (.25, .75)}
SHOULDER_LINK = (.25, 1.)                             # motorway and trunk ramps


def oneway(tags):
    """OSM's explicit or implied one-way: motorways and roundabouts are one-way unless tagged no."""
    value = str(tags.get('oneway', '')).lower()
    if value in ('yes', '1', '-1', 'true'):
        return True
    if value in ('no', 'false', '0', 'reversible', 'alternating'):
        return False
    return tags.get('highway') == 'motorway' or tags.get('junction') in ('roundabout', 'circular')


def shoulder(tags):
    """(left, right) paved shoulder: tagged (shoulder:left:width and shoulder:right:width, left and
    right of the node order: est_roads writes them), else by class for a way without a width tag;
    roundabouts have none."""
    tagged = number(tags.get('shoulder:left:width'), None), number(tags.get('shoulder:right:width'), None)
    if None not in tagged:
        return tagged
    highway = tags.get('highway', '')
    if tags.get('width') is not None or tags.get('junction') in ('roundabout', 'circular'):
        return 0., 0.
    if highway in ('motorway_link', 'trunk_link'):
        return SHOULDER_LINK
    if oneway(tags) and highway in SHOULDER_ONEWAY:
        return SHOULDER_ONEWAY[highway]
    return SHOULDER.get(highway, (0., 0.))


def road_width(tags):
    klass = tags.get('highway', '').replace('_link', '')
    if klass in FOOT_WIDTH:
        return min(35., max(1.5, number(tags.get('width'), FOOT_WIDTH[klass])))
    one = oneway(tags)
    if klass == 'raceway':
        fallback = RACEWAY.get(tags.get('sport'), RACEWAY_WIDTH)
    elif klass in NARROW and tags.get('lanes') is None:
        fallback = DRIVEWAY if tags.get('service') in ('driveway', 'alley') else NARROW[klass]
    else:
        motorway = tags.get('highway') == 'motorway'
        lanes = max(1., number(tags.get('lanes'), 2 if motorway or not one else 1))
        lane = LANE_WIDTH.get(klass, 3.3)
        fallback = lanes * lane
        if one:
            fallback = max(ONE_LANE_MIN, fallback)
        elif lanes < 2:
            fallback = max(SHARED_MIN, 2 * lane * SHARED)
        if tags.get('junction') in ('roundabout', 'circular'):
            # a circulating carriageway is wider than its lanes: long vehicles track inside it
            fallback = max(5.5, lanes * 4.)
        fallback = max(3.2, fallback) + sum(shoulder(tags))
    return min(35., max(2.5, number(tags.get('width'), fallback)))


def utm_crs(lon, lat):
    zone = int((lon + 180) // 6) % 60 + 1
    return f'EPSG:{(32600 if lat >= 0 else 32700) + zone}'


class Frame:
    """World metres = UTM metres minus an origin. Every index has its own frame, at the landing
    (Frame.at): BeamNG keeps positions in float32, and with one origin for the country Uzhhorod
    lay 613 km from Kyiv's (steps of 6 cm); the UTM zone of the landing keeps the scale true in
    the west as well."""
    def __init__(self, crs=CRS, origin=ORIGIN):
        self.crs = crs
        self.forward = pyproj.Transformer.from_crs('EPSG:4326', crs, always_xy=True)
        self.inverse = pyproj.Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
        self.cx, self.cy = float(origin[0]), float(origin[1])

    @classmethod
    def at(cls, lon, lat):
        """The frame centred on a point (whole metres), in the point's UTM zone."""
        crs = utm_crs(lon, lat)
        x, y = pyproj.Transformer.from_crs('EPSG:4326', crs, always_xy=True).transform(lon, lat)
        return cls(crs, (round(x), round(y)))

    @classmethod
    def of(cls, meta):
        """The frame of an index (region.json, or its source index)."""
        spec = meta.get('frame')
        return cls(spec['crs'], spec['origin']) if spec else cls()

    def spec(self):
        return {'crs': self.crs, 'origin': [self.cx, self.cy]}

    def local(self, lon, lat):
        x, y = self.forward.transform(lon, lat)
        return np.asarray(x) - self.cx, np.asarray(y) - self.cy

    def lonlat(self, x, y):
        return self.inverse.transform(x, y)

    def geographic(self, x, y):
        return self.inverse.transform(np.asarray(x) + self.cx, np.asarray(y) + self.cy)

    def tile_of(self, lon, lat):
        x, y = self.local(lon, lat)
        return math.floor(x / TILE), math.floor(y / TILE)

    def rect(self, i, j, pad=0.):
        return i*TILE-pad, j*TILE-pad, (i+1)*TILE+pad, (j+1)*TILE+pad

    def geo_bbox(self, rect):
        x0, y0, x1, y1 = rect
        lon, lat = self.geographic([x0,x0,x1,x1], [y0,y1,y0,y1])
        return [float(min(lon)), float(min(lat)), float(max(lon)), float(max(lat))]


# A package larger than this is indexed as a window round the landing (Kyiv oblast: ~2900
# source tiles; the whole of it would take minutes against the 120 s start).
WINDOW_TILES = 300
WINDOW_SNAP = 0.2           # window centres on this grid: nearby landings share an index
WINDOW_WAYS = 1_200_000     # OSM ways a window may hold: the Kyiv package (162 tiles) has 1.17 M
WINDOW_RINGS = (5, 20)      # rings of tiles round the centre: at least ~56 x 55 km, at most ~210 x 220


def window_of(index, point):
    """The tiles of a large package that a landing at point indexes, and the window box. The
    window grows ring by ring (1.5 cells of longitude per cell of latitude: about square in km)
    while it holds fewer ways than the Kyiv package, so a rural window covers far more ground
    for the same indexing time."""
    if point is None or len(index['tiles']) <= WINDOW_TILES:
        return index, None
    lon, lat = point
    cell = index.get('cell', .05)
    centre = [round(round(lon / WINDOW_SNAP) * WINDOW_SNAP, 6), round(round(lat / WINDOW_SNAP) * WINDOW_SNAP, 6)]
    cx, cy = centre[0] / cell, centre[1] / cell
    entries = []
    for k, v in index['tiles'].items():
        x, y = (v['cell'][0] + v['cell'][2]) / 2 / cell, (v['cell'][1] + v['cell'][3]) / 2 / cell
        entries.append((max(abs(x - cx) / 1.5, abs(y - cy)), k, v))
    tiles, ways = {}, 0
    for r in range(WINDOW_RINGS[0], WINDOW_RINGS[1] + 1):
        ring = {k: v for d, k, v in entries if d <= r}
        total = sum(v.get('ways', WINDOW_WAYS) for v in ring.values())
        if tiles and total > WINDOW_WAYS:
            break
        tiles, ways = ring, total
        if total >= WINDOW_WAYS:
            break
    if not tiles:
        raise ValueError(f'no_osm: {lon:.4f}, {lat:.4f} is outside the source package')
    xs = [c for v in tiles.values() for c in (v['cell'][0], v['cell'][2])]
    ys = [c for v in tiles.values() for c in (v['cell'][1], v['cell'][3])]
    window = [round(min(xs), 6), round(min(ys), 6), round(max(xs), 6), round(max(ys), 6)]
    return dict(index, tiles=tiles, package_box=window, window=window, centre=centre), window


def window_box(index, box):
    """The tiles of a package under a lon/lat box (an authoring grid region), centred on it."""
    tiles = {k: v for k, v in index['tiles'].items()
             if v['cell'][0] < box[2] and v['cell'][2] > box[0] and v['cell'][1] < box[3] and v['cell'][3] > box[1]}
    if not tiles:
        raise ValueError(f'no_osm: {box} is outside the source package')
    xs = [c for v in tiles.values() for c in (v['cell'][0], v['cell'][2])]
    ys = [c for v in tiles.values() for c in (v['cell'][1], v['cell'][3])]
    window = [round(min(xs), 6), round(min(ys), 6), round(max(xs), 6), round(max(ys), 6)]
    centre = [round((box[0] + box[2]) / 2, 6), round((box[1] + box[3]) / 2, 6)]
    return dict(index, tiles=tiles, package_box=window, window=window, centre=centre), window


def dem_tiles(box):
    """z12 Terrarium tiles under a lon/lat box, one tile of margin (fast_dem.audit's rule)."""
    w, s, e, n = box
    tile = lambda lon, lat: ((lon + 180) / 360 * 4096, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 4096)
    x0, y0 = tile(w, n); x1, y1 = tile(e, s)
    return [(x, y) for x in range(math.floor(x0) - 1, math.floor(x1) + 2) for y in range(math.floor(y0) - 1, math.floor(y1) + 2)]


# Raw OSM tiles kept parsed: an export block with its halo touches up to six, and four made
# every block parse them all again.
SCENES = 9
PARSE_WORKERS = min(6, os.cpu_count() or 2)     # tile parsers of one index (fewer when regions run side by side)


def source_identity(source, dem, point=None, box=None):
    """Index checksum (of the window's tiles) plus the DEM files under it (name, size, mtime):
    old geometry cannot survive source replacement. Contents were hashed before: 200 MB of
    PNG per landing for the oblast."""
    source, dem = Path(source), Path(dem)
    index = json.loads((source / 'index.json').read_bytes())
    index, window = window_box(index, box) if box is not None else window_of(index, point)
    # the frame's origin: the window's centre (the landing snapped to WINDOW_SNAP, so nearby
    # landings share the index and its tiles; at most ~11 km from the car), else the package's
    if 'centre' not in index:
        w, s, e, n = index['package_box']
        index = dict(index, centre=[round((w + e) / 2, 6), round((s + n) / 2, 6)])
    index = dict(index, frame=Frame.at(*index['centre']).spec())
    h = hashlib.sha256(VERSION.encode() + json.dumps(index, sort_keys=True).encode())
    for x, y in dem_tiles(index['package_box']):
        # the z12 tile and its z13 children (a local DEM burnt finer, est_dem)
        for zoom, a, b in [(12, x, y)] + [(13, 2 * x + i, 2 * y + j) for i in (0, 1) for j in (0, 1)]:
            p = dem / 'terrain' / str(zoom) / str(a) / f'{b}.png'
            if p.exists():
                st = p.stat()
                h.update(f'{zoom}/{a}/{b}:{st.st_size}:{st.st_mtime_ns}'.encode())
    return VERSION + '-' + h.hexdigest()[:16], index


def dem_zoom(dem, box):
    """13 when a local DEM was burnt into z13 tiles under the box (est_dem), else 12."""
    for x, y in dem_tiles(box):
        for i in (0, 1):
            for j in (0, 1):
                if (Path(dem) / 'terrain' / '13' / str(2 * x + i) / f'{2 * y + j}.png').exists():
                    return 13
    return 12


class Terrain:
    """Vectorized, offline Terrarium samples with a tile-independent pixel grid.

    Bilinear sampling crosses PNG boundaries. Missing tiles fail explicitly.
    Roads use a symmetric 5-tap spatial filter; no optional network downloads.
    zoom 13: a local DEM's ~10 m tiles (est_dem); where none was burnt, the z12 tile
    bilinearly upsampled, so the two meet without a step.
    """
    def __init__(self, cache, frame=None, zoom=12):
        self.cache, self.frame, self.zoom = Path(cache), frame or Frame(), zoom
        self.images = OrderedDict()
        self.coarse = Terrain(cache, self.frame) if zoom == 13 else None
        self._native = None

    def __getstate__(self):
        return {**self.__dict__, '_native': None}

    def native(self):
        """The same sampler in earthng_native.dll (native_tool.Dem), or None."""
        if self._native is None:
            import native_tool
            kernels = native_tool.kernels()
            self._native = (kernels and kernels.dem(self.cache, self.zoom, self.frame.crs, self.frame.cx,
                                                    self.frame.cy, LIFT)) or False
        return self._native or None

    def has(self, a, b):
        if (self.cache / 'terrain' / str(self.zoom) / str(a) / f'{b}.png').exists():
            return True
        return self.zoom == 13 and self.coarse.has(a // 2, b // 2)

    def upsampled(self, a, b):
        """z13 tile a/b from the z12 heights: pixel X of z13 is pixel X/2 of z12."""
        gx, gy = np.meshgrid(np.arange(a * 256, a * 256 + 256) / 2, np.arange(b * 256, b * 256 + 256) / 2)
        ix, iy = np.floor(gx).astype(int).ravel(), np.floor(gy).astype(int).ravel()
        u, v, n = (gx.ravel() - ix), (gy.ravel() - iy), ix.size
        p = self.coarse.pixels(np.concatenate([ix, ix + 1, ix, ix + 1]), np.concatenate([iy, iy, iy + 1, iy + 1]))
        return ((p[:n] * (1 - u) + p[n:2 * n] * u) * (1 - v) + (p[2 * n:3 * n] * (1 - u) + p[3 * n:] * u) * v).reshape(256, 256)

    def image(self, a, b):
        key = (a, b)
        if key not in self.images:
            path = self.cache / 'terrain' / str(self.zoom) / str(a) / f'{b}.png'
            if not path.exists() and self.zoom == 13:
                self.images[key] = self.upsampled(a, b)
            elif not path.exists():
                raise FileNotFoundError(f'no_dem: {path}')
            else:
                with Image.open(path) as im:
                    rgb = np.asarray(im.convert('RGB'), dtype=float)
                self.images[key] = rgb[:,:,0]*256 + rgb[:,:,1] + rgb[:,:,2]/256 - 32768
            if len(self.images) > 24:
                self.images.popitem(last=False)
        self.images.move_to_end(key)
        return self.images[key]

    def pixels(self, x, y):
        tx, ty = x // 256, y // 256
        a0, b0 = int(tx[0]), int(ty[0])
        if (tx == a0).all() and (ty == b0).all():     # the usual case: one PNG
            return self.image(a0, b0)[y % 256, x % 256]
        out = np.empty(len(x), dtype=float)
        keys = tx * 65536 + ty                          # z12/z13 tile indices are 0..8191
        for key in np.unique(keys).tolist():
            mask = keys == key
            a, b = divmod(key, 65536)
            out[mask] = self.image(a, b)[y[mask] % 256, x[mask] % 256]
        return out

    def sample(self, xy, smooth=False):
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        if not len(xy):
            return np.array([])
        native = self.native()
        if native is not None:
            return native.sample(xy, smooth)
        lon, lat = self.frame.geographic(xy[:,0], xy[:,1])
        scale = 256 * 2**self.zoom
        x = (lon+180)/360*scale
        y = (1-np.arcsinh(np.tan(np.radians(lat)))/np.pi)/2*scale
        ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
        u, v = x-ix, y-iy
        offsets = [(0,0,1.)] if not smooth else [(0,0,.5),(-1,0,.125),(1,0,.125),(0,-1,.125),(0,1,.125)]
        z = np.zeros(len(x))
        n = len(x)
        for dx, dy, weight in offsets:
            # the four corners in one lookup (one pass over the PNG keys)
            p = self.pixels(np.concatenate([ix+dx, ix+dx+1, ix+dx, ix+dx+1]),
                            np.concatenate([iy+dy, iy+dy, iy+dy+1, iy+dy+1]))
            z += weight * ((p[:n]*(1-u) + p[n:2*n]*u)*(1-v) + (p[2*n:3*n]*(1-u) + p[3*n:]*u)*v)
        if not np.isfinite(z).all():
            raise ValueError('non-finite DEM')
        return z + LIFT


def foot_bridge(tags):
    """A foot or cycle way on a bridge of its own. Indoor ones are a building's corridors."""
    return (tags.get('highway') in FOOT_WIDTH and tags.get('bridge') not in (None, 'no') and tags.get('area') != 'yes'
            and tags.get('tunnel') in (None, 'no') and tags.get('indoor') in (None, 'no'))


def read_ways(path, sha256):
    """The ways of one source tile the height solve needs: drivable ones and foot bridges, both
    {way id: (tags, [(node, lon, lat), ...])}, and the closed man_made=bridge outlines
    {way id: [(lon, lat), ...]}."""
    import osmium
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != sha256:
        raise ValueError(f'OSM checksum mismatch: {path}')
    roads, feet, decks = {}, {}, {}

    class Reader(osmium.SimpleHandler):
        def way(self, w):
            if w.tags.get('man_made') == 'bridge' and w.id not in decks and w.is_closed():
                ring = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
                if len(ring) == len(w.nodes) and len(ring) >= 4:
                    decks[w.id] = ring
            h = w.tags.get('highway', '')
            drivable = h in DRIVABLE or h.endswith('_link')
            if not drivable and not foot_bridge(w.tags):
                return
            found = roads if drivable else feet
            if w.id in found or w.tags.get('area') == 'yes' or w.tags.get('access') == 'no':
                return
            nodes = [(n.ref, n.lon, n.lat) for n in w.nodes if n.location.valid()]
            if len(nodes) != len(w.nodes):
                raise ValueError(f'incomplete OSM way {w.id}')
            if len(nodes) >= 2:
                found[w.id] = (dict(w.tags), nodes)

    Reader().apply_file(str(path), locations=True)
    return roads, feet, decks


def read_roads(path, sha256):
    """Drivable ways of one source tile: {way id: (tags, [(node, lon, lat), ...])}."""
    return read_ways(path, sha256)[0]


def foot_segments(feet, decks, frame, segments, sample, emit=print):
    """Segments of the foot bridges, solved after the roads, which stay exactly as they are: a foot
    bridge splits no road and makes no junction, and its nodes are its own ('f<id>').

    OSM maps a road bridge's sidewalks as bridges too: a way along a road bridge is left to that
    bridge's deck. A foot bridge's man_made=bridge outline gives the deck its width, on the way
    nearest its middle: the ways beside that one are lanes of the same deck (Pont Saint-Louis)."""
    import fast_profile
    order = sorted(feet)
    if not order:
        return []

    def lines_of(parts):
        return shapely.linestrings(np.concatenate(parts), indices=np.repeat(np.arange(len(parts)), [len(p) for p in parts]))

    def local(lonlat):
        lon, lat = zip(*lonlat)
        return np.column_stack(frame.local(list(lon), list(lat)))

    lines = lines_of([local([n[1:] for n in feet[wid][1]]) for wid in order])
    lengths = shapely.length(lines)
    tree = shapely.STRtree(lines)
    over = [seg for seg in segments if fast_profile.kind(seg['tags']) != 'tunnel']
    roads = lines_of([np.asarray(seg['xy']) for seg in over]) if over else np.array([])
    keep = lengths > .5
    decked = np.array([fast_profile.kind(seg['tags']) == 'bridge' for seg in over], dtype=bool)
    if decked.any():
        reach = np.array([seg['width'] / 2 + SIDEWALK_REACH for seg in over])[decked]
        near = shapely.buffer(roads[decked], reach, cap_style='flat')
        i, j = tree.query(near, predicate='intersects')
        along = np.bincount(j, shapely.length(shapely.intersection(lines[j], near[i])), len(lines))
        keep &= along < SIDEWALK_SHARE * lengths
    wide = np.zeros(len(lines))
    if decks:
        rings = [local(ring) for ring in decks.values()]
        outlines = shapely.make_valid(shapely.polygons(shapely.linearrings(
            np.concatenate(rings), indices=np.repeat(np.arange(len(rings)), [len(r) for r in rings]))))
        carries = np.zeros(len(outlines), dtype=bool)        # a road bridge's outline says nothing of its sidewalks
        if decked.any():
            carries[shapely.STRtree(roads[decked]).query(outlines, predicate='intersects')[0]] = True
        half = shapely.length(outlines) / 2
        along_it = (half + np.sqrt(np.maximum(half * half - 4 * shapely.area(outlines), 0.))) / 2     # a rectangle's long side
        across = shapely.area(outlines) / along_it
        i, j = tree.query(outlines, predicate='intersects')
        inside = shapely.length(shapely.intersection(lines[j], outlines[i]))
        on = keep[j] & ~carries[i] & (inside >= DECK_SHARE * lengths[j])
        i, j, inside = i[on], j[on], inside[on]
        spanned = np.bincount(i, inside, len(outlines)) >= DECK_SHARE * along_it
        ranked = np.lexsort((shapely.distance(lines[j], shapely.centroid(outlines[i])), i))
        middles = shapely.line_interpolate_point(lines, lengths / 2)
        drawn = {}
        for o, k in zip(i[ranked].tolist(), j[ranked].tolist()):
            if spanned[o]:
                kept = drawn.setdefault(o, [])
                if any(shapely.distance(middles[k], lines[m]) < across[o] / 2 for m in kept):
                    keep[k] = False                                  # a lane of the deck the middle way draws
                else:
                    kept.append(k)
                    wide[k] = max(wide[k], across[o])
    out = []
    for k in np.flatnonzero(keep).tolist():
        tags, nodes = feet[order[k]]
        out.append({'way': order[k], 'tags': tags, 'width': max(road_width(tags), min(35., float(wide[k]))),
                    'xy': np.round(shapely.get_coordinates(lines[k]), 3).tolist(),
                    'nodes': [f'f{nodes[0][0]}', f'f{nodes[-1][0]}']})
    crossings = [[] for _ in out]
    if out and len(roads):
        foot = lines_of([np.asarray(seg['xy']) for seg in out])
        for i, j in shapely.STRtree(roads).query(foot, predicate='crosses').T.tolist():
            for point in shapely.get_parts(shapely.intersection(foot[i], roads[j])):
                if shapely.get_type_id(point) == 0:
                    height = np.interp(shapely.line_locate_point(roads[j], point), *over[j]['prof'])
                    crossings[i].append((float(shapely.line_locate_point(foot[i], point)), float(height), over[j]['width'] / 2))
    streets = [k for k, seg in enumerate(over) if fast_profile.kind(seg['tags']) != 'bridge']

    def banks(xy):
        heights = np.full(len(xy), np.nan)
        if streets:
            points = shapely.points(xy)
            near = shapely.STRtree(roads[streets])
            for i, j in near.query_nearest(points, max_distance=FOOT_REACH, all_matches=False).T.tolist():
                k = streets[j]
                heights[i] = np.interp(shapely.line_locate_point(roads[k], points[i]), *over[k]['prof'])
        return heights
    profiles = fast_profile.foot_decks(out, sample, crossings, banks)
    for seg, (ps, ph) in zip(out, profiles):
        seg['prof'] = [np.round(ps, 2).tolist(), np.round(ph, 3).tolist()]
    emit(f'foot bridges: {len(out)} of {len(order)} ways, {sum(map(len, crossings))} road crossings')
    return out


class Polylines:
    """Many 1-D functions (xp[k], fp[k]) evaluated at once: value(x, k) == np.interp(x, xp[k], fp[k])
    bit for bit (the same slope formula), without a Python step per call."""
    def __init__(self, xp):
        self.n = np.array([len(a) for a in xp])
        self.start = np.concatenate([[0], np.cumsum(self.n)[:-1]])
        self.X = np.concatenate(xp)
        first, last = self.X[self.start], self.X[self.start + self.n - 1]
        # the functions laid end to end (1 apart) only to find the bracketing pair
        self.offset = np.concatenate([[0.], np.cumsum(last - first + 1.)[:-1]]) - first
        self.shifted = self.X + np.repeat(self.offset, self.n)

    def locate(self, x, k):
        lo, hi = self.start[k], self.start[k] + self.n[k] - 1
        j = np.clip(np.searchsorted(self.shifted, x + self.offset[k], side='right') - 1, lo, np.maximum(lo, hi - 1))
        return j, np.minimum(j + 1, hi), lo, hi

    def value(self, x, where, fp):
        j, j1, lo, hi = where
        X, F = self.X, fp
        with np.errstate(divide='ignore', invalid='ignore'):
            out = (F[j1] - F[j]) / (X[j1] - X[j]) * (x - X[j]) + F[j]
        out = np.where(x <= X[lo], F[lo], out)
        return np.where(x >= X[hi], F[hi], out)


def _dumps(objs, compact):
    return [json.dumps(o, separators=(',', ':')) if compact else json.dumps(o) for o in objs]


def write_index(segments, arcs, mouths, node_h, path, emit=print):
    """The read-only index (features, their bounds, nodes, links) into a new SQLite file at path.
    Mouths are done as arrays (a Python step per mouth was ~90 s of London's cold index), the JSON
    of the rows is encoded in parallel (~60 s in one process), and the rows go in key / spatial
    order into a database without a journal: a temporary file, renamed only once complete."""
    from concurrent.futures import ProcessPoolExecutor
    started = time.perf_counter()
    pool = ProcessPoolExecutor(min(6, os.cpu_count() or 2)) if len(segments) > 50_000 else None
    schema = '''PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-262144;
            PRAGMA temp_store=MEMORY;
            CREATE TABLE features(id INTEGER PRIMARY KEY, kind TEXT, data TEXT, geom BLOB);
            CREATE VIRTUAL TABLE bounds USING rtree(id,x0,x1,y0,y1);
            CREATE TABLE nodes(id INTEGER PRIMARY KEY, data TEXT);
            CREATE TABLE links(node INTEGER, segment INTEGER);'''
    if not segments:
        # no road in the whole region (wilderness): the same empty tables, no mouths to place
        db = sqlite3.connect(path)
        db.executescript(schema)
        db.execute('CREATE INDEX links_node ON links(node)')
        db.commit(); db.close()
        return
    try:
        # every mouth, node by node in mouths order
        nids = list(mouths)
        counts = np.array([len(mouths[n]) for n in nids])
        flat = [e for n in nids for e in mouths[n]]
        sid = np.array([e[0] for e in flat]); end = np.array([e[1] for e in flat])
        width = np.array([e[4] for e in flat], dtype=float); length = np.array([e[5] for e in flat], dtype=float)
        del flat
        first = np.concatenate([[0], np.cumsum(counts)[:-1]])
        radius = np.where(counts > 1, np.maximum.reduceat(width, first) * .8, 0.)
        cut = np.minimum(np.repeat(radius, counts), length * .25)
        s = np.where(end == 0, cut, length - cut)
        k = sid - 1
        arc = Polylines([a[1] for a in arcs])
        ax_, ay_ = np.concatenate([a[0][:, 0] for a in arcs]), np.concatenate([a[0][:, 1] for a in arcs])
        def at(x):
            w = arc.locate(x, k)
            return arc.value(x, w, ax_), arc.value(x, w, ay_)
        px, py = at(s)
        fx, fy = at(np.minimum(length, s + .25))
        bx, by = at(np.maximum(0, s - .25))
        dx, dy = fx - bx, fy - by
        norm = np.maximum(1e-9, np.sqrt(dx * dx + dy * dy))
        dx, dy = dx / norm, dy / norm
        nx, ny = -dy * width / 2, dx * width / 2
        plus = np.round(np.column_stack([px + nx, py + ny]), 3).tolist()
        minus = np.round(np.column_stack([px - nx, py - ny]), 3).tolist()
        prof = Polylines([np.asarray(seg['prof'][0], dtype=float) for seg in segments])
        cz = (prof.value(s, prof.locate(s, k), np.concatenate([np.asarray(seg['prof'][1], dtype=float) for seg in segments]))
              + ROAD_LIFT).tolist()
        bridge = np.array([max(1, number(seg['tags'].get('layer'), 1)) * 6.5
                           if seg['tags'].get('bridge') not in (None, 'no') else 0. for seg in segments])
        level = np.maximum(np.maximum.reduceat(bridge[k], first), 0.).tolist()
        cuts = np.zeros((len(segments) + 1, 2)); cuts[sid, end] = cut
        cuts = cuts.tolist()
        emit(f'mouths: {time.perf_counter()-started:.1f}s')
        nodes, junctions = [], []
        for n, nid, a, lev in zip(counts.tolist(), nids, first.tolist(), level):
            entries = mouths[nid]
            data = {'xy': entries[0][2], 'raise': lev, 'segments': [e[0] for e in entries], 'h': node_h[nid] + ROAD_LIFT}
            nodes.append(data)
            if n > 1:
                junctions.append((nid, data, [c for i in range(a, a + n) for c in (plus[i], minus[i])],
                                  [z for i in range(a, a + n) for z in (cz[i], cz[i])]))
        del plus, minus, cz
        bound_rows, kept = [], []
        if junctions:
            jc = [len(j[2]) for j in junctions]
            hulls = shapely.convex_hull(shapely.multipoints(np.concatenate([j[2] for j in junctions]),
                                                            indices=np.repeat(np.arange(len(junctions)), jc)))
            areas, wkbs, bounds = shapely.area(hulls), shapely.to_wkb(hulls), shapely.bounds(hulls)
            for (nid, data, corners, z), area, wkb, (x0, y0, x1, y1) in zip(junctions, areas, wkbs, bounds):
                if area > .01:
                    kept.append((-nid, dict(data, node=nid, corners=corners, cz=z), wkb))
                    bound_rows.append((-nid, x0, x1, y0, y1))
        del junctions
        lines = shapely.linestrings(np.concatenate([a[0] for a in arcs]),
                                    indices=np.repeat(np.arange(len(arcs)), [len(a[0]) for a in arcs]))
        seg_wkb = shapely.to_wkb(lines)
        for seg, (x0, y0, x1, y1) in zip(segments, shapely.bounds(lines)):
            seg['cuts'] = cuts[seg['id']]
            # Bounds include end mouths so a query always includes the owning segment.
            pad = seg['width'] / 2 + 1
            bound_rows.append((seg['id'], x0 - pad, x1 + pad, y0 - pad, y1 + pad))
        del lines
        emit(f'rows: {time.perf_counter()-started:.1f}s')
        def dumps(objs, compact):
            if pool is None:
                out = _dumps(objs, compact)
                return lambda: out
            step = max(1, len(objs) // 48 + 1)
            futures = [pool.submit(_dumps, objs[i:i + step], compact) for i in range(0, len(objs), step)]
            return lambda: [t for f in futures for t in f.result()]
        node_json = dumps(nodes, False)
        junction_json = dumps([j[1] for j in kept], True)
        segment_json = dumps(segments, True)
        # the R-tree fills far faster in spatial order: 1 km cells along a Morton curve
        b = np.array([r[1:] for r in bound_rows])
        code = np.zeros(len(b), dtype=np.int64)
        cx, cy = ((b[:, 0] + b[:, 1]) / 2000).astype(np.int64) & 0xffff, ((b[:, 2] + b[:, 3]) / 2000).astype(np.int64) & 0xffff
        for bit in range(16):
            code |= ((cx >> bit) & 1) << (2 * bit) | ((cy >> bit) & 1) << (2 * bit + 1)
        bound_rows = [bound_rows[i] for i in np.argsort(code, kind='stable')]
        link_rows = sorted(zip(np.repeat(nids, counts).tolist(), sid.tolist()), key=lambda r: r[0])
        db = sqlite3.connect(path)
        db.executescript(schema)
        db.executemany('INSERT INTO bounds VALUES(?,?,?,?,?)', bound_rows)
        db.executemany('INSERT INTO links VALUES(?,?)', link_rows)
        db.execute('CREATE INDEX links_node ON links(node)')
        db.executemany('INSERT INTO nodes VALUES(?,?)', sorted(zip(nids, node_json())))
        # junctions (negative ids) before roads: features in key order
        db.executemany('INSERT INTO features VALUES(?,?,?,?)',
                       [(fid, 'junction', text, wkb) for (fid, _, wkb), text in sorted(zip(kept, junction_json()), key=lambda r: r[0][0])])
        db.executemany('INSERT INTO features VALUES(?,?,?,?)',
                       ((seg['id'], 'road', text, wkb) for seg, text, wkb in zip(segments, segment_json(), seg_wkb)))
        db.commit(); db.close()
        emit(f'written: {time.perf_counter()-started:.1f}s')
    finally:
        if pool:
            pool.shutdown(cancel_futures=True)


class Cancelled(Exception):
    """A newer landing replaced the one this index was being built for."""


def prepare(*args, **kw):
    """_prepare without the cyclic garbage collector: with millions of live lists and dicts
    (London's window: 650 k roads) each collection walked them all again; the index was built
    ~2x slower and a pickle of it loaded 10x slower. Reference counting still frees them.
    The collector is process-wide, so the companion's other threads run without it for the
    build too; they make no cycles worth collecting meanwhile."""
    enabled = gc.isenabled()
    gc.disable()
    try:
        return _prepare(*args, **kw)
    finally:
        if enabled:
            gc.enable()


def _prepare(source, output, dem, emit=print, point=None, cancelled=None, box=None):
    """Parse source tiles once, split roads at shared nodes, publish a read-only index.
    A large package is indexed as a window round point (the landing). cancelled() is asked
    between the stages: a window of a big city takes minutes, and the single preparer must not
    finish it for a landing the player has already left (the next landing waited behind it)."""
    import osmium
    started = time.perf_counter()
    def check():
        if cancelled and cancelled():
            raise Cancelled(point)
    identity, index = source_identity(source, dem, point, box)
    target = Path(output) / identity
    final = target / 'sources.sqlite'
    if final.exists():
        return target, json.loads((target / 'region.json').read_text())
    check()
    target.mkdir(parents=True, exist_ok=True)
    frame = Frame.of(index)
    roads = {}

    files = [Path(source) / entry['file'] for entry in index['tiles'].values()]
    shas = [entry['sha256'] for entry in index['tiles'].values()]
    if len(files) > 24:
        # tiles parse in parallel; merged in tile order, first copy of a way wins (as before)
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(PARSE_WORKERS) as pool:
            parts = list(pool.map(read_ways, files, shas, chunksize=4))
    else:
        parts = [read_ways(f, h) for f, h in zip(files, shas)]
    roads, feet, decks = {}, {}, {}
    for part, foot, deck in parts:
        for wid, road in part.items():
            roads.setdefault(wid, road)
        for wid, road in foot.items():
            feet.setdefault(wid, road)
        decks.update(deck)
    del parts
    emit(f'roads parsed in {time.perf_counter()-started:.1f}s')
    check()
    refs = Counter(n[0] for _, nodes in roads.values() for n in nodes)
    order = sorted(roads)
    lens = [len(roads[w][1]) for w in order]
    lon = [n[1] for w in order for n in roads[w][1]]; lat = [n[2] for w in order for n in roads[w][1]]
    X, Y = frame.local(lon, lat)            # one transform for every node (was one per way)
    X, Y = X.tolist(), Y.tolist(); del lon, lat
    segments, arcs, mouths = [], [], defaultdict(list)
    at = 0
    hypot = math.hypot
    for wid, count in zip(order, lens):
        tags, nodes = roads[wid]
        xy = list(zip(X[at:at + count], Y[at:at + count])); at += count
        cuts = [0] + [k for k in range(1,len(nodes)-1) if refs[nodes[k][0]] > 1] + [len(nodes)-1]
        width = None
        for a, b in zip(cuts, cuts[1:]):
            # points closer than 1 cm to the previous raw point dropped; arc length after that
            pts = [xy[a]] + [xy[k] for k in range(a + 1, b + 1)
                             if hypot(xy[k][0] - xy[k-1][0], xy[k][1] - xy[k-1][1]) > 0.01]
            if len(pts)<2:
                continue
            cum = [0.]
            for k in range(1, len(pts)):
                cum.append(cum[-1] + hypot(pts[k][0] - pts[k-1][0], pts[k][1] - pts[k-1][1]))
            if cum[-1] < .1:
                continue
            if width is None:
                width = road_width(tags)
            # millimetres are enough (seams <= 1 cm) and keep the JSON a third the size
            seg = {'id': len(segments)+1, 'way': wid, 'tags': tags, 'xy': [[round(q[0], 3), round(q[1], 3)] for q in pts],
                   'nodes': [nodes[a][0],nodes[b][0]], 'width': width}
            segments.append(seg); arcs.append((np.array(pts), np.array(cum)))
            mouths[seg['nodes'][0]].append((seg['id'],0,list(pts[0]),None,width,cum[-1]))
            mouths[seg['nodes'][1]].append((seg['id'],1,list(pts[-1]),None,width,cum[-1]))
    del roads, refs
    # one height solve for the whole graph: shared nodes, smooth grades, soft bridges/tunnels
    import fast_profile
    zoom = dem_zoom(dem, index['package_box'])
    terrain = Terrain(dem, frame, zoom)
    # a wilderness region (Everest's Tibetan side) has no road at all: nothing to solve
    if segments:
        mosaic = fast_profile.Mosaic(terrain, np.concatenate([np.asarray(seg['xy']) for seg in segments]))
        profiles, node_h = fast_profile.solve(segments, lambda q: mosaic.sample(q, missing=True), emit=emit)
        for seg, (ps, ph) in zip(segments, profiles):
            seg['prof'] = [np.round(ps, 2).tolist(), np.round(ph, 3).tolist()]
        del mosaic, profiles
    else:
        node_h = {}
    emit(f'profile ready: {time.perf_counter()-started:.1f}s')
    check()
    for seg in foot_segments(feet, decks, frame, segments, lambda q, m=fast_profile.Mosaic(terrain): m.sample(q, missing=True), emit):
        seg['id'] = len(segments) + 1
        pts = np.asarray(seg['xy'])
        segments.append(seg); arcs.append((pts, np.r_[0., np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]))
    tmp = target / f'sources.{os.getpid()}.tmp'
    tmp.unlink(missing_ok=True)         # left by an earlier run of this process
    write_index(segments, arcs, mouths, node_h, tmp, emit)
    meta = {'id':identity,'generator':VERSION,'bbox':index['package_box'],'center':index['centre'],'frame':index['frame'],
            'dem':str(Path(dem).resolve()), 'demZoom':zoom, 'source':str(Path(source).resolve()),
            'coverage':[v['coverage'] for v in index['tiles'].values()],
            'seconds':time.perf_counter()-started,'roads':len(segments),'scenery':'lazy from raw OSM'}
    (target/'region.json').write_text(json.dumps(meta),encoding='utf8')
    os.replace(tmp,final)
    emit(f'index ready: {meta["seconds"]:.1f}s, {len(segments)} segments')
    return target, meta


# what a building:part takes from the building round it, when it has none of its own
PART_TAGS = ('building', 'building:material', 'building:cladding', 'building:colour', 'historic')


def lifted(tags):
    """Metres a building:part hangs over the ground: min_height, or 3 m for each building:min_level."""
    try:
        return float(tags.get('min_height') or 3 * float(tags.get('building:min_level', 0)))
    except ValueError:
        return 0.


def link_parts(found):
    """Tie each building:part to the building that holds it: it takes that building's tags and
    id (e2r_of: one wall material for all its parts). A building mostly covered by parts that reach
    the ground gets e2r_outline: the parts draw it, its own box would hide them. Parts in the air
    stand on the building (a dome on a tomb), so it stays and reaches up to them, unless its own
    height holds them: the London Eye is 256 parts inside one 136 m slab."""
    parts = [(ident, tags, geometry) for ident, (kind, tags, geometry) in found.items() if kind == 'building' and tags.get('e2r_part')]
    if not parts:
        return
    outlines = [(ident, tags, geometry) for ident, (kind, tags, geometry) in found.items() if kind == 'building' and not tags.get('e2r_part')]
    tree = shapely.STRtree([entry[2] for entry in outlines]) if outlines else None
    covered, under = {}, {}
    for _, tags, geometry in parts:
        inside = geometry.representative_point()
        holder = None
        for n in (tree.query(inside) if tree else ()):
            if outlines[int(n)][2].covers(inside) and (holder is None or outlines[int(n)][2].area < holder[2].area):
                holder = outlines[int(n)]
        if holder:
            if lifted(tags) >= number(holder[1].get('height'), 0.) > 0 or (lifted(tags) > 0 and 'height' not in holder[1]):
                under[holder[0]] = min(lifted(tags), under.get(holder[0], lifted(tags)))
            else:
                covered[holder[0]] = covered.get(holder[0], 0.) + geometry.area
            tags['e2r_of'] = str(holder[0])
            for key in PART_TAGS:
                if key in holder[1] and key not in tags:
                    tags[key] = holder[1][key]
            if holder[1].get('amenity') == 'place_of_worship':
                tags['amenity'] = 'place_of_worship'
        tags.setdefault('building', 'yes')
    for ident, tags, geometry in outlines:
        if covered.get(ident, 0.) >= .5 * geometry.area:
            tags['e2r_outline'] = '1'
        elif ident in under and 'height' not in tags and 'building:levels' not in tags:
            tags['height'] = str(under[ident])


SCENE_MAGIC = b'ESC1'


def write_scene(records):
    """A scene file (rust/crates/cells scene.rs reads it too): 'ESC1', count, then per record fid,
    kind, tags as a JSON list of [key, value] (their order kept) and WKB, little-endian."""
    import struct
    out = [SCENE_MAGIC, struct.pack('<I', len(records))]
    for (fid, kind, data, _), wkb in zip(records, shapely.to_wkb([r[3] for r in records])):
        name = kind.encode('utf8')
        tags = json.dumps(list(data['tags'].items()), ensure_ascii=False, separators=(',', ':')).encode('utf8')
        out += [struct.pack('<qH', fid, len(name)), name, struct.pack('<I', len(tags)), tags,
                struct.pack('<I', len(wkb)), wkb]
    return b''.join(out)


def read_scene(data):
    """(fids, kinds, tag dicts, WKB) of a write_scene file."""
    import struct
    if data[:4] != SCENE_MAGIC:
        raise ValueError('not a scene file')
    count, = struct.unpack_from('<I', data, 4)
    at, fids, kinds, tags, wkb = 8, [], [], [], []
    for _ in range(count):
        fid, n = struct.unpack_from('<qH', data, at)
        at += 10
        kinds.append(data[at:at + n].decode('utf8'))
        at += n
        n, = struct.unpack_from('<I', data, at)
        tags.append(dict(json.loads(data[at + 4:at + 4 + n])))
        at += 4 + n
        n, = struct.unpack_from('<I', data, at)
        wkb.append(data[at + 4:at + 4 + n])
        at += 4 + n
        fids.append(fid)
    return fids, kinds, tags, wkb


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.meta = json.loads((self.directory/'region.json').read_text())
        self.db = sqlite3.connect((self.directory/'sources.sqlite').as_uri()+'?mode=ro',uri=True)
        self.frame = Frame.of(self.meta)
        self.terrain = Terrain(self.meta['dem'],self.frame,self.meta.get('demZoom',12))
        from shapely.geometry import box
        self.coverage = shapely.union_all([box(*r) for r in self.meta['coverage']])
        self.heights = OrderedDict()
        self.scenes = OrderedDict()
        self.source_index = json.loads((Path(self.meta['source'])/'index.json').read_text())

    def query(self, rect, kinds=None):
        x0,y0,x1,y1=rect
        rows = self.db.execute('''SELECT f.id,f.kind,f.data,f.geom FROM bounds b JOIN features f ON f.id=b.id
            WHERE b.x1>=? AND b.x0<=? AND b.y1>=? AND b.y0<=? ORDER BY f.id''',(x0,x1,y0,y1))
        rows = [row for row in rows if kinds is None or row[1] in kinds]
        return [(fid,kind,json.loads(data),geometry) for (fid,kind,data,_),geometry
                in zip(rows,shapely.from_wkb([row[3] for row in rows]).tolist())]

    def node(self, nid):
        return json.loads(self.db.execute('SELECT data FROM nodes WHERE id=?',(nid,)).fetchone()[0])

    def height(self, nid):
        if nid in self.heights:
            self.heights.move_to_end(nid)
            return self.heights[nid]
        h = float(self.node(nid)['h'])     # solved with the whole graph (fast_profile)
        self.heights[nid] = h
        if len(self.heights)>8192:
            self.heights.popitem(last=False)
        return h

    def covered(self, rect):
        from shapely.geometry import box
        return self.coverage.covers(box(*self.frame.geo_bbox(rect)))

    def scenery(self, rect):
        """Load only the raw OSM block needed now, including multipolygon holes.

        This work is timed in scene jobs, never hidden in a prebuilt city asset.
        """
        import osmium
        import osm_tiles
        bbox=self.frame.geo_bbox(rect)
        hit=osm_tiles.tile_for(self.source_index,bbox)
        if not hit:
            raise ValueError(f'no_osm scenery coverage: {bbox}')
        key,entry=hit
        if key not in self.scenes:
            records = self.load_scene(key)
            if records is None and self.scene_dir:
                self.save_scene(key)        # or wait for the worker reading it now
                records = self.load_scene(key)
            if records is None:
                records = self.build_scene(entry)
            self.scenes[key]=(records,shapely.STRtree([r[3] for r in records]))
            if len(self.scenes)>SCENES: self.scenes.popitem(last=False)
        self.scenes.move_to_end(key)
        records,tree=self.scenes[key]
        from shapely.geometry import box
        return [records[int(k)] for k in sorted(tree.query(box(*rect)))]

    # A city export splits its blocks between all workers, and each would read the same raw OSM
    # tiles again (half of a dense cell's time): the tiles are read once beforehand
    # (build_country._shared_scenes) and kept as WKB in scene_dir for this build.
    scene_dir = None

    def scene_path(self, key):
        return Path(self.scene_dir) / f'{key}.scene' if self.scene_dir else None

    def load_scene(self, key):
        path = self.scene_path(key)
        if path is None or not path.is_file():
            return None
        fids, kinds, tags, wkb = read_scene(path.read_bytes())
        return list(zip(fids, kinds, ({'tags': t} for t in tags), shapely.from_wkb(wkb)))

    def save_scene(self, key, wait=600.):
        """Read raw tile key into scene_dir once. While another worker reads it (its .lock file),
        wait for its file instead of reading the tile twice; if that worker fails (the lock goes
        without a file) or takes longer than wait seconds, read it here."""
        path = self.scene_path(key)
        if path.is_file():
            return
        lock = path.with_suffix('.lock')
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            handle = None
            deadline = time.monotonic() + wait
            while not path.is_file() and lock.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            if path.is_file():
                return
        try:
            entry = self.source_index['tiles'][key]
            part = path.with_suffix(f'.{os.getpid()}.part')
            # the same bytes from rust/ (native_tool.build_scene) where it covers the tile
            import native_tool
            if native_tool.build_scene(self, entry, part) is not None:
                part.write_bytes(write_scene(self.build_scene(entry)))
            os.replace(part, path)
        finally:
            if handle is not None:
                os.close(handle)
                lock.unlink(missing_ok=True)

    def build_scene(self, entry):
        """Records (fid, kind, {'tags'}, local geometry) of one raw OSM tile, sorted by fid."""
        import osmium
        found={}; lines={}; retail_areas={}; marks=[]; factory=osmium.geom.WKBFactory()
        import fast_style
        import retail
        import venues
        class Reader(osmium.SimpleHandler):
            def area(self,a):
                tags = retail.enriched(a.tags)
                point_kind = retail.kind(tags)
                kind='building' if tags.get('building') not in (None,'no') else (
                    'water' if tags.get('natural')=='water' or tags.get('waterway')=='riverbank' else None)
                if kind is None and tags.get('building:part') not in (None,'no'):
                    kind='building'; tags['e2r_part']='1'
                if kind is None:
                    kind=fast_style.ground_kind(tags)
                if (kind and a.id not in found) or point_kind:
                    try:
                        geometry=shapely.from_wkb(factory.create_multipolygon(a))
                    except RuntimeError:
                        return      # broken OSM ring (e.g. area 29961653): skip that area alone
                    if kind:
                        found[a.id]=(kind,tags,geometry)
                    # A mapped site/building is still useful as a point even if it has no
                    # recognized ground kind. A representative point stays inside the area.
                    if point_kind and not geometry.is_empty:
                        retail_areas[-(2*10**12+a.id)]=(point_kind,tags,geometry)
                        found[-(3*10**12+a.id)]=(point_kind + '_site',tags,geometry)
            def node(self,n):
                # bus stops and traffic signals where OSM has them (way nodes keep their tags
                # in the source tiles); keyed apart from areas and ways
                tags=dict(n.tags)
                kind=fast_style.point_kind(tags)
                if kind and n.location.valid():
                    marks.append((-(10**12+n.id),kind,retail.enriched(tags),n.location.lon,n.location.lat))
            def way(self,w):
                # footpaths, fences, tree rows: lines, not areas (an area id is 2 x way id,
                # so a line keys as -way id to stay apart)
                kind=fast_style.line_kind(w.tags)
                if kind and -w.id not in lines:
                    try:
                        coords=[(n.lon,n.lat) for n in w.nodes]
                    except osmium.InvalidLocationError:
                        return
                    if len(coords)>=2:
                        tags=fast_style.rail_tags(w.tags) if kind=='rail' else dict(w.tags)
                        lines[-w.id]=(kind,tags,LineString(coords))
        # Only nodes that can be points reach Python (Kyiv tile: 21 k of 218 k, 0.57 -> 0.25 s);
        # the location index still sees every node, so ways and areas keep their geometry.
        Reader().apply_file(str(Path(self.meta['source'])/entry['file']),locations=True,
                            filters=[osmium.filter.KeyFilter(*fast_style.point_keys()).enable_for(osmium.osm.NODE)])
        for (ident,kind,tags,*_),geometry in zip(marks,shapely.points([m[3:] for m in marks] or np.empty((0,2)))):
            lines[ident]=(kind,tags,geometry)
        # OSM often maps a business both as a node and a containing site/building.
        # Keep the surveyed node when category and known brand match; unknown names
        # or neighbouring businesses are never guessed to be duplicates.
        nodes = [(kind, tags.get('e2r_brand'), geom, tags.get('e2r_post_type')) for kind, tags, geom in lines.values()
                 if kind in ('fuel', 'grocery', 'fast_food', 'post', 'service') and tags.get('e2r_brand')]
        tree = shapely.STRtree([entry[2] for entry in nodes]) if nodes else None
        for ident, (kind, tags, geometry) in retail_areas.items():
            brand = tags.get('e2r_brand')
            duplicate = bool(brand and tree and any(
                nodes[int(i)][0] == kind and nodes[int(i)][1] == brand and
                nodes[int(i)][3] == tags.get('e2r_post_type') and geometry.covers(nodes[int(i)][2]) for i in tree.query(geometry)))
            if not duplicate:
                lines[ident] = (kind, tags, geometry.representative_point())
        link_parts(found)
        # places from a register (venues.py): every scene holds them, a query takes those it covers
        for n,(venue,record) in enumerate(venues.located()):
            lines[-(4*10**12+n)]=('venue',venues.point_tags(venue,record),Point(record['lon'],record['lat']))
        found.update(lines)
        ordered=sorted(found.items())
        geoms=shapely.make_valid(shapely.transform([v[1][2] for v in ordered],self.frame.local,interleaved=False))
        return [(fid,kind,{'tags':tags},geom) for (fid,(kind,tags,_)),geom in zip(ordered,geoms)]
