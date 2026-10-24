"""Compile source features into an ordinary native BeamNG country ZIP.

    python earthng/build_country.py --id ua --title Ukraine --version 0.1.0 \
        --region out/work/fast-index/<id> --bbox -1500 -1500 1500 1500 --out out/mods

Repeat --region for independently centred source indexes. --bbox is an optional
local-metre export window; complete intersecting cells are exported. Without it,
all fully covered cells of each index are exported. To prepare an index first use
--sources <OSM package> --dem <DEM cache> --lat 50.45 --lon 30.52 --work out/author.

The ZIP contains road centre lines/profiles, OSM polygons/tags and elevation grids,
not finished meshes. BeamNG's Lua runtime creates geometry while playing. No
Python, SQLite, OSM PBF, launcher, server or generated mesh is shipped to players.
"""
import argparse
from datetime import date
import json
import math
import os
from pathlib import Path
import re
import tempfile
import zipfile
import zlib

import numpy as np
import shapely

import country_format as binary
import fast_sources as sources
import looks
import nature


FORMAT = 'earthng-features-v2'
CELL = 1000
HALO = 100
GRID = 25
GRID_FINE = 10       # metres of a cell's elevation grid over a local ~10 m DEM (z13, est_dem)
MARGIN = 4000             # metres a region exports beyond its core box: driving room
GRID_STEP = (1.5, 1.0)    # degrees of a region core: ~105 x 111 km in Ukraine
PAD = (0.12, 0.08)        # source window beyond the core: MARGIN + HALO + tile buffer
ID = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,94}[a-z0-9])?\Z')
SOURCE_ID = re.compile(r'[a-z0-9][a-z0-9_-]{0,95}\Z')


def _identifier(value, label):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError(f'{label} must use lowercase letters, digits or hyphens')
    return value


def _json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise ValueError(f'cannot read JSON {path}: {exc}') from exc


def _finite(values, size, label):
    if not isinstance(values, (list, tuple)) or len(values) != size or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError(f'{label} must contain {size} finite numbers')
    return values


def _bounds(values, label):
    _finite(values, 4, label)
    if values[0] >= values[2] or values[1] >= values[3]:
        raise ValueError(f'{label} must have positive width and height')
    return values


def _encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf8')


def _xyz(store, xy, height=None, pending=None):
    """[[x, y, z]] of xy on the terrain (or at height). With pending, terrain points are
    queued: the returned list is filled by _sample_pending, one DEM lookup for a whole cell."""
    xy = np.asarray(xy, dtype=float)[:, :2]
    if height is None and pending is not None:
        result = []
        pending.append((xy, result))
        return result
    z = store.terrain.sample(xy) if height is None else np.full(len(xy), height)
    result = np.column_stack([xy, z])
    if not np.isfinite(result).all():
        raise ValueError('source geometry contains non-finite coordinates or elevations')
    return result.tolist()


def _sample_pending(store, pending):
    if not pending:
        return
    xy = np.concatenate([part for part, _ in pending])
    result = np.column_stack([xy, store.terrain.sample(xy)])
    if not np.isfinite(result).all():
        raise ValueError('source geometry contains non-finite coordinates or elevations')
    at = 0
    for part, out in pending:
        out.extend(result[at:at + len(part)].tolist())
        at += len(part)


def _parts(geometry, kind):
    if geometry.geom_type == kind:
        yield geometry
    elif hasattr(geometry, 'geoms'):
        for part in geometry.geoms:
            yield from _parts(part, kind)


def _rings(store, polygon, height=None, pending=None):
    # Preserve the full outer boundary and every hole. Lua performs triangulation.
    return [_xyz(store, ring.coords, height, pending) for ring in [polygon.exterior, *polygon.interiors]]


def road_feature(fid, data):
    """Preserve every bend/profile knot, adding samples along long segments."""
    xy = np.asarray(data['xy'], dtype=float)[:, :2]
    profile = np.asarray(data['prof'], dtype=float)
    if len(xy) < 2 or profile.ndim != 2 or profile.shape[0] != 2 or profile.shape[1] < 2:
        raise ValueError(f'road {fid}: invalid centre line or height profile')
    if not np.isfinite(xy).all() or not np.isfinite(profile).all():
        raise ValueError(f'road {fid}: non-finite centre line or height profile')
    distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    if distance[-1] <= 0 or np.any(np.diff(profile[0]) < 0):
        raise ValueError(f'road {fid}: invalid profile distances')
    knots = np.unique(np.r_[distance, profile[0], np.arange(0., distance[-1], 20.)])
    knots = knots[(knots >= 0.) & (knots <= distance[-1])]
    points = np.column_stack([np.interp(knots, distance, xy[:, 0]),
                              np.interp(knots, distance, xy[:, 1]),
                              np.interp(knots, profile[0], profile[1])]).tolist()
    width = float(data['width'])
    if not math.isfinite(width) or width <= 0:
        raise ValueError(f'road {fid}: invalid width')
    return {'id': str(fid), 'points': points, 'width': width,
            'tags': data['tags'], 'nodes': [str(n) for n in data['nodes']]}


class Despiked:
    """DEM without single-spot spikes and pits. Terrarium has void artefacts of a few pixels
    (Zanzibar: +254 m and -66 m beside 20 m ground; a green cone in the game). A sample more
    than SPIKE metres from the median of its 5 x 5 neighbourhood (25 m steps) takes the median.
    The result depends on the world point alone, so neighbouring cells keep identical seams."""
    SPIKE = 40.
    OFFSETS = np.array([(dx, dy) for dy in range(-2, 3) for dx in range(-2, 3)], dtype=float) * GRID

    def __init__(self, terrain):
        self.terrain = terrain

    def sample(self, xy):
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        if not len(xy):
            return np.array([])
        around = (xy[:, None, :] + self.OFFSETS[None, :, :]).reshape(-1, 2)
        heights = np.asarray(self.terrain.sample(around), dtype=float).reshape(len(xy), len(self.OFFSETS))
        centre, median = heights[:, len(self.OFFSETS) // 2], np.median(heights, axis=1)
        return np.where(np.abs(centre - median) > self.SPIKE, median, centre)

    def grid(self, xs, ys):
        """sample() of the lattice ys x xs (GRID steps, row-major), each raw height read once:
        the 5 x 5 neighbourhoods of lattice points are lattice points too."""
        step = xs[1] - xs[0] if len(xs) > 1 else GRID
        ex = np.r_[xs[0] - 2*step, xs[0] - step, xs, xs[-1] + step, xs[-1] + 2*step]
        ey = np.r_[ys[0] - 2*step, ys[0] - step, ys, ys[-1] + step, ys[-1] + 2*step]
        raw = np.asarray(self.terrain.sample(np.array([(x, y) for y in ey for x in ex])),
                         dtype=float).reshape(len(ey), len(ex))
        windows = np.lib.stride_tricks.sliding_window_view(raw, (5, 5)).reshape(len(ys), len(xs), 25)
        centre, median = raw[2:-2, 2:-2], np.median(windows, axis=2)
        return np.where(np.abs(centre - median) > self.SPIKE, median, centre).ravel()


def _scenery(store, rect, depth=0):
    """Scenery under rect. A padded cell at a package's ragged edge (coast, border) may lie in
    no single OSM tile; its quarters are read from whichever tiles hold them, and a quarter
    held by none (open sea outside the package) has no scenery. Callers drop duplicate ids."""
    try:
        return store.scenery(rect)
    except ValueError as exc:
        if 'no_osm' not in str(exc):
            raise
        if depth >= 3:
            return []
    mx, my = (rect[0]+rect[2])/2, (rect[1]+rect[3])/2
    return [record for part in ([rect[0], rect[1], mx, my], [mx, rect[1], rect[2], my],
                                [rect[0], my, mx, rect[3]], [mx, my, rect[2], rect[3]])
            for record in _scenery(store, part, depth + 1)]


def compile_cell(store, rect, include=None):
    """Source records with a halo; all XY and Z share the source index's frame."""
    padded = [rect[0]-HALO, rect[1]-HALO, rect[2]+HALO, rect[3]+HALO]
    cell = {name: [] for name in ('roads', 'junctions', 'buildings', 'areas', 'lines', 'points')}
    seen = set()
    for fid, kind, data, geometry in store.query(padded):
        identity = (kind, fid)
        if identity in seen:
            continue
        seen.add(identity)
        if kind == 'road':
            cell['roads'].append(road_feature(fid, data))
        elif kind == 'junction':
            # The source's solved node h includes the old surface lift. Lua adds
            # its own road lift, so export the same underlying road datum here.
            height = float(data['h']) - sources.ROAD_LIFT
            for n, part in enumerate(_parts(geometry, 'Polygon')):
                cell['junctions'].append({'id': f'{fid}:{n}',
                                          'rings': _rings(store, part, height), 'height': height})
    seen.clear()
    pending, points = [], []
    for fid, kind, data, geometry in _scenery(store, padded):
        if kind == 'coastline' or (kind, fid) in seen or not looks.keep_scenery(kind, include):
            continue
        seen.add((kind, fid))
        tags = data.get('tags', {})
        if kind != 'building' and not shapely.box(*padded).contains(geometry):
            # A forest or field spans dozens of cells; whole, it was copied into each of them
            # (4/5 of a rural cell). Lua clips to the tile anyway, and the tile lies inside
            # this padded cell, so the cut 100 m outside the cell never shows.
            geometry = shapely.clip_by_rect(geometry, *padded)
        for n, part in enumerate(_parts(geometry, 'Polygon')):
            feature = {'id': f'{fid}:{n}', 'kind': kind, 'rings': _rings(store, part, None, pending), 'tags': tags}
            if kind == 'building':
                height = max(2.5, min(850., sources.number(tags.get('height'),
                             sources.number(tags.get('building:levels'), 3) * 3)))
                feature.update(height=height, minHeight=max(0., sources.number(tags.get('min_height'), 0.)))
                cell['buildings'].append(feature)
            else:
                cell['areas'].append(feature)
        for n, part in enumerate(_parts(geometry, 'LineString')):
            cell['lines'].append({'id': f'{fid}:{n}', 'kind': kind,
                                  'points': _xyz(store, part.coords, None, pending), 'tags': tags})
        for n, part in enumerate(_parts(geometry, 'Point')):
            feature = {'id': f'{fid}:{n}', 'kind': kind, 'pos': _xyz(store, [[part.x, part.y]], None, pending),
                       'tags': tags}
            points.append(feature)
            cell['points'].append(feature)
    _sample_pending(store, pending)
    for feature in points:
        feature['pos'] = feature['pos'][0]
    cell['areas'] = nature.partition(cell['areas'])
    cover = getattr(store, 'landcover', None)
    if cover is not None and (not include or include.get('cover', True) or include.get('water', True)):
        # Detailed mapped footprints win over satellite classes. Raster areas
        # carry no sampled Z: runtime drapes them on the shared final surface.
        overrides = [shapely.Polygon(f['rings'][0], f['rings'][1:])
                     for f in cell['areas'] + cell['buildings'] if f.get('rings')]
        for n, (kind, geometry, tags) in enumerate(cover.areas(rect, overrides)):
            if not looks.keep_scenery(kind, include):
                continue
            for k, part in enumerate(_parts(geometry, 'Polygon')):
                rings = [[[float(p[0]), float(p[1]), 0.] for p in ring.coords]
                         for ring in [part.exterior, *part.interiors]]
                cell['areas'].append({'id': f'wc:{int(rect[0])}:{int(rect[1])}:{n}:{k}',
                                      'kind': kind, 'tags': tags, 'rings': rings})
    for features in cell.values():
        features.sort(key=lambda feature: feature['id'])
    step = grid_step(store)
    xs = np.arange(rect[0], rect[2]+step, step, dtype=float)
    ys = np.arange(rect[1], rect[3]+step, step, dtype=float)
    if isinstance(store.terrain, Despiked):
        heights = store.terrain.grid(xs, ys)
    else:
        heights = np.asarray(store.terrain.sample(np.array([(x, y) for y in ys for x in xs])), dtype=float)
    if not np.isfinite(heights).all():
        raise ValueError('non-finite terrain grid')
    heights = _coast(store, rect, xs, ys, heights)
    cell['terrain'] = {'rect': list(rect), 'nx': len(xs), 'ny': len(ys), 'heights': heights.tolist()}
    return cell


def grid_step(store):
    """GRID, or GRID_FINE when the store reads a finer local DEM."""
    terrain = getattr(store.terrain, 'terrain', store.terrain)
    zoom = getattr(terrain, 'zoom', 12)
    return GRID_FINE if isinstance(zoom, int) and zoom > 12 else GRID


def _coastlines(store, box):
    """natural=coastline ways (local frame) under box. A source store reads them once per OSM tile:
    a full scenery read of the window cost a dense Manhattan cell ~80 s. Other stores (tests)
    give them through scenery."""
    tiles = getattr(store, 'source_index', {}).get('tiles')
    if not tiles or not hasattr(store, 'meta'):
        return [geometry for _fid, kind, _data, geometry in _scenery(store, box) if kind == 'coastline']
    import osmium
    cache = store.__dict__.setdefault('_coast_tiles', {})
    w, s, e, n = store.frame.geo_bbox(box)
    ways = {}
    for key, entry in tiles.items():
        cw, cs, ce, cn = entry['coverage']
        if ce < w or cw > e or cn < s or cs > n:
            continue
        if key not in cache:
            found = {}
            for obj in osmium.FileProcessor(str(Path(store.meta['source']) / entry['file'])).with_locations()                     .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY)).with_filter(osmium.filter.TagFilter(('natural', 'coastline'))):
                try:
                    coords = [(nd.lon, nd.lat) for nd in obj.nodes]
                except osmium.InvalidLocationError:
                    continue
                if len(coords) >= 2:
                    found[obj.id] = coords
            cache[key] = found
        ways.update(cache[key])
    if not ways:
        return []
    lines = [shapely.LineString(ways[k]) for k in sorted(ways)]
    return list(shapely.transform(lines, store.frame.local, interleaved=False))


COAST_BAND = 1500.  # metres from an OSM coastline within which its side overrides the DEM's sea
COAST_DRY = 300.    # land this close to the coastline stays above the sea plane


def _coast(store, rect, xs, ys, heights):
    """Terrarium blurs the shore over several hundred metres: off Copacabana the sea was +3 m
    ground 650 m out, so the sea plane stopped short and a forest grew on the water. An OSM
    coastline has the land on its left. The nearest coastline within COAST_BAND decides each
    grid point: on its right the ground sinks under the sea plane (deeper with distance), on its
    left within COAST_DRY it stays above it. The nearest shore, not a band per shore, so the sea
    beside a narrow cape is still sea. Depends on the world point and the coastline alone (all
    of it within reach is read), so cell seams stay identical."""
    if float(np.min(heights)) > sources.LIFT + 60:
        return heights      # no sea in reach of this cell's DEM: the shore fix cannot apply
    # the nearest coastline point of any grid point within the band lies in this window
    reach = COAST_BAND + 50
    wide = [rect[0] - reach, rect[1] - reach, rect[2] + reach, rect[3] + reach]
    pieces = [part for line in _coastlines(store, wide)
              for part in _parts(shapely.clip_by_rect(line, *wide), 'LineString') if part.length > 0]
    if not pieces:
        return heights
    lines = list(_parts(shapely.line_merge(shapely.MultiLineString(pieces), directed=True), 'LineString'))
    gx, gy = np.meshgrid(xs, ys)
    px, py = gx.ravel(), gy.ravel()
    points = shapely.points(px, py)
    distances = np.stack([shapely.distance(line, points) for line in lines])
    nearest, distance = distances.argmin(axis=0), distances.min(axis=0)
    side = np.zeros(len(px))
    for k, line in enumerate(lines):
        mask = (nearest == k) & (distance <= COAST_BAND)
        if not mask.any():
            continue
        # the side of the coastline's local direction at the nearest point (1 m either way)
        along = shapely.line_locate_point(line, points[mask])
        a = shapely.line_interpolate_point(line, np.maximum(along - 1, 0))
        b = shapely.line_interpolate_point(line, np.minimum(along + 1, line.length))
        ax, ay, bx, by = shapely.get_x(a), shapely.get_y(a), shapely.get_x(b), shapely.get_y(b)
        side[mask] = np.sign((bx - ax) * (py[mask] - ay) - (by - ay) * (px[mask] - ax))
    level = sources.LIFT
    out = np.asarray(heights, dtype=float).copy()
    wet = side < 0
    dry = (side > 0) & (distance <= COAST_DRY)
    out[wet] = np.minimum(out[wet], level - 1.0 - 0.01 * np.minimum(distance[wet], 600))
    out[dry] = np.maximum(out[dry], level + 0.6)
    return out


def _source_meta(directory):
    meta = _json(Path(directory) / 'region.json')
    raw_id = meta.get('id')
    if not isinstance(raw_id, str) or not SOURCE_ID.fullmatch(raw_id):
        raise ValueError('source region id must use lowercase letters, digits, underscores or hyphens')
    if meta.get('generator') != sources.VERSION:
        raise ValueError(f'{raw_id}: unsupported source index; expected {sources.VERSION}')
    _bounds(meta.get('bbox'), f'{raw_id}: source bbox')
    spec = meta.get('frame')
    if not isinstance(spec, dict) or not isinstance(spec.get('crs'), str):
        raise ValueError(f'{raw_id}: source index needs its geographic frame')
    _finite(spec.get('origin'), 2, f'{raw_id}: frame origin')
    return meta


def _local_bbox(frame, bbox):
    x, y = frame.local([bbox[0], bbox[0], bbox[2], bbox[2]], [bbox[1], bbox[3], bbox[1], bbox[3]])
    return [float(min(x)), float(min(y)), float(max(x)), float(max(y))]


def _provenance(meta, index):
    """Keep the source snapshot identity and attribution, without authoring paths."""
    original = index.get('source') or meta.get('source') or meta['id']
    basename = str(original).replace('\\', '/').rstrip('/').rsplit('/', 1)[-1]
    source_id = re.sub(r'(?i)(?:\.osm)?\.pbf$', '', basename)
    result = {'source': 'OpenStreetMap contributors', 'license': 'ODbL-1.0', 'sourceId': source_id}
    match = re.search(r'(?:^|-)(\d{2})(\d{2})(\d{2})$', source_id)
    if match:
        try:
            result['sourceDate'] = date(2000 + int(match[1]), int(match[2]), int(match[3])).isoformat()
        except ValueError:
            pass  # A package name is evidence of a date only when it is valid.
    return result


def _deflate(data, level=9):
    """Raw deflate of one zip member. Same compressor zipfile uses at this level, so a block
    compressed in a worker is byte-for-byte the member writestr used to write on one thread."""
    compressor = zlib.compressobj(level, zlib.DEFLATED, -15)
    blob = compressor.compress(data) + compressor.flush()
    return zlib.crc32(data) & 0xffffffff, len(data), blob


def _write_deflated(archive, path, crc, size, blob):
    """Append a member that is already deflated. ZipFile.writestr compresses on the calling
    thread; a country is hundreds of thousands of blocks, and that one thread was the export."""
    info = zipfile.ZipInfo(path, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.compress_level = 9
    info.CRC = crc
    info.file_size = size
    info.compress_size = len(blob)
    info.external_attr = 0o600 << 16
    archive._writecheck(info)
    archive._didModify = True
    if archive._seekable:
        archive.fp.seek(archive.start_dir)
    info.header_offset = archive.fp.tell()
    archive.fp.write(info.FileHeader(False))
    archive.fp.write(blob)
    archive.filelist.append(info)
    archive.NameToInfo[info.filename] = info
    archive.start_dir = archive.fp.tell()


def _write(archive, path, data):
    # Stable member timestamps make the same sources produce the same archive.
    _write_deflated(archive, path, *_deflate(data))


def _write_json(archive, path, value):
    _write(archive, path, _encode(value))


def compile_block(store, cells, include=None):
    """Encoded payloads {slot: bytes} and road counts {slot: n} of the given (i, j) cells."""
    payloads, roads = {}, {}
    for i, j in cells:
        rect = [i*CELL, j*CELL, (i+1)*CELL, (j+1)*CELL]
        try:
            cell = compile_cell(store, rect, include)
        except FileNotFoundError as exc:
            if 'no_dem' not in str(exc):
                raise
            continue    # no elevation there (a border sliver): the cell is absent, not flat
        slot = binary.slot(i, j)
        payloads[slot] = binary.encode_cell(cell, rect[:2])
        roads[slot] = len(cell['roads'])
    return payloads, roads


def _finish_block(store, cells, include):
    """A block ready for the zip: deflated bytes and the presence mask, or None when every
    cell lacked elevation. Deflate runs here so each worker compresses its own blocks."""
    payloads, counts = compile_block(store, cells, include)
    if not payloads:
        return None, counts
    data, mask = binary.encode_block(payloads)
    crc, size, blob = _deflate(data)
    return (crc, size, blob, mask), counts


_WORKER = {}


def _despike(store):
    if not isinstance(store.terrain, Despiked):
        store.terrain = Despiked(store.terrain)
    return store


def _worker_open(directory, landcover=(), include=None):
    _WORKER['store'] = _despike(sources.Store(directory))
    _WORKER['include'] = include
    if landcover:
        from landcover import WorldCover
        _WORKER['store'].landcover = WorldCover(landcover, _WORKER['store'].frame)


def _worker_block(task):
    key, cells = task
    return key, _finish_block(_WORKER['store'], cells, _WORKER.get('include'))


def _region_spec(region):
    """A region is a source-index directory, or {'dir', 'core', 'id'}: core is the lon/lat box
    this region answers landings for (neighbours share a few km of margin)."""
    if isinstance(region, dict):
        return Path(region['dir']), region.get('core'), region.get('id')
    return Path(region), None, None


def _runs(keys):
    """Rows of consecutive blocks, as (bj, bi0, bi1)."""
    rows = {}
    for bi, bj in keys:
        rows.setdefault(bj, []).append(bi)
    for bj in sorted(rows):
        xs = sorted(rows[bj])
        start = prev = xs[0]
        for x in xs[1:]:
            if x == prev + 1:
                prev = x
                continue
            yield bj, start, prev
            start = prev = x
        yield bj, start, prev


def _clip(box, core):
    if core is None:
        return box
    out = [max(box[0], core[0]), max(box[1], core[1]), min(box[2], core[2]), min(box[3], core[3])]
    return out if out[0] < out[2] and out[1] < out[3] else None


def _landing(present, roads, frame, core):
    """The centre of a cell with roads whose whole 3 x 3 neighbourhood is exported, nearest
    the core's centre: a country button always lands on a road with full startup sources.
    A region without a single road (Everest's: trails only) lands in its most central cell
    with a full neighbourhood instead."""
    if core is not None:
        x, y = frame.local([(core[0]+core[2])/2], [(core[1]+core[3])/2])
        cx, cy = float(x[0]), float(y[0])
    else:
        cx = sum(i+.5 for i, _ in present)/len(present)*CELL
        cy = sum(j+.5 for _, j in present)/len(present)*CELL
    best = None
    wild = not any(roads.values())
    for (i, j) in sorted(present if wild else roads):
        if (wild or roads[(i, j)]) and all((i+a, j+b) in present for a in (-1, 0, 1) for b in (-1, 0, 1)):
            d = ((i+.5)*CELL-cx)**2 + ((j+.5)*CELL-cy)**2
            if best is None or d < best[0]:
                best = (d, [(i+.5)*CELL, (j+.5)*CELL])
    return best and best[1]


def _stopped(cancel):
    return cancel is not None and cancel.is_set()


def _export_region(archive, country_id, region, bbox, emit, jobs=1, landcover=(), cover_meta=None, vegetation=None,
                   include=None, look=None, cancel=None):
    directory, core, region_id = _region_spec(region)
    meta = _source_meta(directory)
    region_id = region_id or meta['id'].replace('_', '-')
    _identifier(region_id, 'region id')
    if core is not None:
        core = [float(v) for v in _bounds(list(core), f'{region_id}: core box')]
    store = _despike(sources.Store(directory))
    try:
        if landcover:
            from landcover import WorldCover
            store.landcover = WorldCover(landcover, store.frame)
        provenance = _provenance(meta, getattr(store, 'source_index', {}))
        frame = store.frame
        if bbox is not None:
            local = list(bbox)
        elif core is not None:
            c = _local_bbox(frame, core)
            local = [c[0]-MARGIN, c[1]-MARGIN, c[2]+MARGIN, c[3]+MARGIN]
        else:
            local = _local_bbox(frame, meta['bbox'])
        _bounds(local, 'local export bbox')
        base = f'earthng/countries/{country_id}/regions/{region_id}'
        outline = region.get('shape') if isinstance(region, dict) else None
        if outline is not None:
            import shapely
            shapely.prepare(outline)
        blocks = {}
        for j in range(math.floor(local[1]/CELL), math.ceil(local[3]/CELL)):
            for i in range(math.floor(local[0]/CELL), math.ceil(local[2]/CELL)):
                rect = [i*CELL, j*CELL, (i+1)*CELL, (j+1)*CELL]
                # a section exports the cells of its outline, not of its whole box
                if outline is not None and not outline.intersects(shapely.box(*frame.geo_bbox(rect))):
                    continue
                if store.covered(rect):
                    blocks.setdefault((i // binary.BLOCK, j // binary.BLOCK), []).append((i, j))
        if not blocks:
            raise ValueError(f'{region_id}: export contains no fully covered source cells')
        total = sum(len(v) for v in blocks.values())
        emit(f'export {region_id}: {total} cells in {len(blocks)} blocks')
        if _stopped(cancel):
            raise InterruptedError('build stopped')
        tasks = sorted(blocks.items())
        pool = None
        if jobs > 1 and len(tasks) > 1:
            import multiprocessing
            pool = multiprocessing.get_context('spawn').Pool(
                min(jobs, len(tasks)), _worker_open, (str(directory), landcover, include))
            results = pool.imap(_worker_block, tasks)
        else:
            results = ((key, _finish_block(store, cells, include)) for key, cells in tasks)
        manifest_blocks, present, roads, done = {}, set(), {}, 0
        stopped = False
        finished = False
        try:
            for (bi, bj), (packed, counts) in results:
                done += len(blocks[(bi, bj)])
                if _stopped(cancel):
                    stopped = True
                    break
                if not packed:
                    continue
                crc, size, blob, mask = packed
                path = f'{base}/blocks/{bi}_{bj}.bin'
                _write_deflated(archive, path, crc, size, blob)
                manifest_blocks[f'{bi}_{bj}'] = {'path': '/' + path, 'mask': mask}
                for slot, n in counts.items():
                    cell = (bi*binary.BLOCK + slot % binary.BLOCK, bj*binary.BLOCK + slot // binary.BLOCK)
                    present.add(cell)
                    roads[cell] = n
                if done == total or len(manifest_blocks) % 50 == 0:
                    emit(f'export {region_id}: {done}/{total} cells')
            else:
                finished = True
        finally:
            if pool is not None:
                # close() waits for every queued block. Stop, or a worker error, leaves
                # unread results; on Windows that fills the queue and join never returns.
                if finished:
                    pool.close()
                else:
                    pool.terminate()
                pool.join()
        if stopped:
            raise InterruptedError('build stopped')
        coverage = []
        if not present:
            raise ValueError(f'{region_id}: no cell exported (no_dem under every source cell)')
        exported = {}
        for i, j in present:
            exported.setdefault((i // binary.BLOCK, j // binary.BLOCK), []).append((i, j))
        for bj, bi0, bi1 in _runs(exported):
            cells = [c for bi in range(bi0, bi1 + 1) for c in exported[(bi, bj)]]
            rect = [min(i for i, _ in cells)*CELL, min(j for _, j in cells)*CELL,
                    (max(i for i, _ in cells)+1)*CELL, (max(j for _, j in cells)+1)*CELL]
            box = _clip(frame.geo_bbox(rect), core)
            if box:
                coverage.append(box)
        landing = _landing(present, roads, frame, core)
        if not coverage or (landing is None and core is not None):
            raise ValueError(f'{region_id}: no landable cells (roads with a complete neighbourhood) in its core')
        lon, lat = frame.geographic([0., 1., 0.], [0., 0., 1.])
        geo = [0., 0., float(lon[0]), float(lat[0]), float(lon[1]-lon[0]),
               float(lon[2]-lon[0]), float(lat[1]-lat[0]), float(lat[2]-lat[0])]
        _finite(geo, 8, 'geographic transform')
        boxes = [frame.geo_bbox([i*CELL, j*CELL, (i+1)*CELL, (j+1)*CELL]) for i, j in present
                 if not all((i+a, j+b) in present for a, b in ((-1, 0), (1, 0), (0, -1), (0, 1)))]
        bounds = [min(b[0] for b in boxes), min(b[1] for b in boxes),
                  max(b[2] for b in boxes), max(b[3] for b in boxes)]
        manifest = {'schemaVersion': 2, 'id': region_id, 'runtime': 'lua', 'sourceFormat': FORMAT,
                    'tileSize': sources.TILE, 'cellSize': CELL, 'blockCells': binary.BLOCK,
                    'frame': frame.spec(), 'geo': geo, 'bounds': bounds, 'coverage': coverage,
                    'seaLevel': sources.LIFT, 'cellCount': len(present), 'blocks': manifest_blocks, **provenance}
        if landing is not None:
            manifest['landing'] = landing
        manifest['natureVersion'] = nature.VERSION
        if vegetation:
            manifest['nature'] = vegetation
        if cover_meta:
            manifest['landcover'] = cover_meta
        if look:
            manifest['look'] = look
        if include:
            manifest['include'] = include
        path = f'{base}/manifest.json'
        _write_json(archive, path, manifest)
        return {'id': region_id, 'manifest': '/' + path, 'coverage': coverage, **provenance}
    finally:
        if getattr(store, 'landcover', None) is not None:
            store.landcover.close()
        store.db.close()


def build_country(country_id, title, version, regions, out, bbox=None, emit=print, jobs=1, landing=None, landcover=(), vegetation=None,
                  look=None, include=None, cancel=None, map_data=None, section=None):
    """Stream source blocks to ZIP64 and atomically replace the completed archive.
    section: {'id', 'title'}: one region, written as a section of the country
    (earthng_<country>_<section>.zip with sections/<id>/section.json and no country manifest),
    which the game joins with the country's other mounted sections."""
    _identifier(country_id, 'country id')
    if not isinstance(title, str) or not title.strip() or not isinstance(version, str) or not version.strip():
        raise ValueError('country title and version must be nonempty strings')
    if not regions:
        raise ValueError('at least one --region or --sources package is required')
    for key, value in (vegetation or {}).items():
        if key not in ('treeLine', 'coniferStart') or not math.isfinite(value) or not 0 <= value <= 6000:
            raise ValueError('vegetation heights must be finite metres above sea level in 0..6000')
    if look is not None:
        look = looks.canonical(look)
    if include is not None:
        include = looks.canonical_include(include)
    cover_meta = None
    if landcover:
        from landcover import provenance
        landcover = tuple(str(Path(p).resolve()) for p in landcover)
        cover_meta = provenance(landcover)
    if bbox is not None:
        _bounds(bbox, 'local export bbox')
    identifiers = []
    for region in regions:
        directory, _, given = _region_spec(region)
        identifiers.append(given or _source_meta(directory)['id'].replace('_', '-'))
    if len(identifiers) != len(set(identifiers)):
        raise ValueError('duplicate region id after slug normalization')
    if section is not None:
        _identifier(section['id'], 'section id')
        if len(regions) != 1 or identifiers[0] != section['id']:
            raise ValueError('a section is one region with the section id')
    output = Path(out)
    output.mkdir(parents=True, exist_ok=True)
    target = output / (f'earthng_{country_id}.zip' if section is None else f"earthng_{country_id}_{section['id']}.zip")
    handle, temporary = tempfile.mkstemp(prefix=target.stem + '-', suffix='.zip.tmp', dir=output)
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, 'w', allowZip64=True) as archive:
            entries = []
            for region in regions:
                if _stopped(cancel):
                    raise InterruptedError('build stopped')
                try:
                    entries.append(_export_region(archive, country_id, region, bbox, emit, jobs, landcover, cover_meta, vegetation, include, look, cancel))
                except ValueError as exc:
                    # A grid box of open sea or a border sliver: the rest of the country stays.
                    if len(regions) == 1 or not isinstance(region, dict) or 'no ' not in str(exc):
                        raise
                    emit(f'skip region: {exc}')
            if not entries:
                raise ValueError('no region has landable cells')
            provenance = {'source': 'OpenStreetMap contributors', 'license': 'ODbL-1.0'}
            snapshots = {entry['sourceId']: {key: entry[key] for key in ('sourceId', 'sourceDate') if key in entry}
                         for entry in entries}
            if len(snapshots) == 1:
                provenance.update(next(iter(snapshots.values())))
            else:
                provenance['sources'] = [snapshots[key] for key in sorted(snapshots)]
            manifest = {'schemaVersion': 1, 'kind': 'earthng-country', 'id': country_id,
                        'title': title.strip(), 'version': version.strip(), 'runtime': 'native',
                        'sourceFormat': FORMAT, 'coverage': [b for r in entries for b in r['coverage']],
                        'regions': entries, **provenance}
            if landing is not None:
                manifest['landing'] = {'lat': float(landing[0]), 'lon': float(landing[1])}
            manifest['natureVersion'] = nature.VERSION
            if cover_meta:
                manifest['landcover'] = cover_meta
            if look:
                manifest['look'] = look
            if include:
                manifest['include'] = include
            if section is None:
                _write_json(archive, f'earthng/countries/{country_id}/manifest.json', manifest)
            else:
                region = dict(entries[0], title=section['title'])
                manifest.update(kind='earthng-section', country=country_id, id=section['id'],
                                sectionTitle=section['title'], region=region)
                del manifest['regions']
                _write_json(archive, f"earthng/countries/{country_id}/sections/{section['id']}/section.json", manifest)
            # the offline map is the country's: a section's zip leaves it to the country pack
            if map_data is not None and section is None:
                from build_map import write_archive
                write_archive(archive, map_data, f'earthng/countries/{country_id}/map')
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def section_region(source, dem, work, core, region_id, outline=None, emit=print):
    """One region answering landings in core (a section's lon/lat box), however many tiles it
    holds; outline (lon/lat shape) limits the cells it exports."""
    window = [core[0]-PAD[0], core[1]-PAD[1], core[2]+PAD[0], core[3]+PAD[1]]
    directory, _ = sources.prepare(source, Path(work) / 'fast-index', dem, emit=emit, box=window)
    region = {'dir': directory, 'core': list(core), 'id': region_id}
    if outline is not None:
        region['shape'] = outline
    return region


def grid_regions(source, dem, work, step=None, emit=print, cancel=None):
    """Cover a whole OSM package: one source index per grid box of step degrees, with its own
    frame at the box centre, so the car stays within ~80 km of its origin. A package small
    enough to index whole stays one region."""
    step = step or GRID_STEP
    index = json.loads((Path(source) / 'index.json').read_bytes())
    name = re.sub(r'[^a-z0-9-]+', '-', Path(source).name.lower()).strip('-')
    if _stopped(cancel):
        raise InterruptedError('build stopped')
    if len(index['tiles']) <= sources.WINDOW_TILES:
        directory, _ = sources.prepare(source, Path(work) / 'fast-index', dem, emit=emit)
        return [{'dir': directory, 'core': index['package_box'], 'id': name}]
    dx, dy = step
    boxes = set()
    for entry in index['tiles'].values():
        c = entry['cell']
        if not entry.get('ways'):
            continue
        for bx in range(math.floor((c[0]+1e-9)/dx), math.floor((c[2]-1e-9)/dx) + 1):
            for by in range(math.floor((c[1]+1e-9)/dy), math.floor((c[3]-1e-9)/dy) + 1):
                boxes.add((bx, by))
    regions = []
    for n, (bx, by) in enumerate(sorted(boxes)):
        if _stopped(cancel):
            raise InterruptedError('build stopped')
        core = [round(bx*dx, 6), round(by*dy, 6), round((bx+1)*dx, 6), round((by+1)*dy, 6)]
        window = [core[0]-PAD[0], core[1]-PAD[1], core[2]+PAD[0], core[3]+PAD[1]]
        emit(f'index {n+1}/{len(boxes)}: {core}')
        try:
            directory, _ = sources.prepare(source, Path(work) / 'fast-index', dem, emit=emit, box=window)
        except ValueError as exc:
            emit(f'skip {core}: {exc}')
            continue
        lon, lat = core[0], core[1]
        rid = f"{'e' if lon >= 0 else 'w'}{abs(round(lon*10)):04d}-{'n' if lat >= 0 else 's'}{abs(round(lat*10)):03d}"
        regions.append({'dir': directory, 'core': core, 'id': rid})
    return regions


def _region_record(region):
    """The index job's JSON. A section outline is GeoJSON; a grid region has none."""
    record = {'dir': str(region['dir']), 'core': region.get('core'), 'id': region.get('id')}
    outline = region.get('shape')
    if outline is not None:
        record['shape'] = shapely.geometry.mapping(outline)
    return record


def _revive_region(region):
    """Turn a section outline written by the index job back into a geometry."""
    outline = region.get('shape') if isinstance(region, dict) else None
    if not isinstance(outline, dict):
        return region
    revived = dict(region)
    revived['shape'] = shapely.geometry.shape(outline)
    return revived


def run_job(path):
    """One GUI build step. The caller is python.exe started by country_fetch.run_step."""
    job = json.loads(Path(path).read_text(encoding='utf-8'))
    command = job['command']
    destination = Path(job['result'])
    destination.unlink(missing_ok=True)
    if command == 'index':
        spec = job.get('section')
        if spec:
            import sections
            regions = [section_region(job['sources'], job['dem'], job['work'], spec['box'], spec['id'],
                                      sections.shape(spec))]
        else:
            regions = grid_regions(job['sources'], job['dem'], job['work'])
        destination.write_text(json.dumps([_region_record(region) for region in regions]), encoding='utf-8')
        return
    if command == 'export':
        archive = build_country(
            job['id'], job['title'], job['version'],
            [_revive_region(region) for region in job['regions']], job['out'],
            jobs=job.get('jobs') or 1, landing=job.get('landing'), look=job.get('look'),
            include=job.get('include'), map_data=job.get('map_data'), section=job.get('section'))
        destination.write_text(str(archive), encoding='utf-8')
        return
    raise ValueError(f'unknown build job {command}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--job', type=Path,
                        help='GUI step: index or export, as written by country_fetch.run_build_job')
    parser.add_argument('--id')
    parser.add_argument('--title')
    parser.add_argument('--version', default='0.2.0')
    parser.add_argument('--region', action='append', default=[], help='prepared source-index directory')
    parser.add_argument('--out')
    parser.add_argument('--bbox', type=float, nargs=4, metavar=('X0', 'Y0', 'X1', 'Y1'))
    parser.add_argument('--sources', help='OSM tile package: export all of it as a grid of regions')
    parser.add_argument('--dem', help='offline DEM cache for --sources')
    parser.add_argument('--work', help='authoring cache for --sources')
    parser.add_argument('--grid', type=float, nargs=2, default=GRID_STEP, metavar=('DLON', 'DLAT'))
    parser.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument('--landing', type=float, nargs=2, metavar=('LAT', 'LON'),
                        help='where the country button lands (inside the export)')
    parser.add_argument('--landcover', action='append', default=[], metavar='GEOTIFF',
                        help='local ESA WorldCover 2021 v200 Map GeoTIFF; repeat for adjacent tiles (optional)')
    parser.add_argument('--tree-line', type=float, help='regional forest limit in metres above sea level')
    parser.add_argument('--conifer-start', type=float, help='altitude at which untagged forest begins mixing conifers')
    args = parser.parse_args()
    if args.job:
        try:
            run_job(args.job)
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        return
    if not args.id or not args.title or not args.out:
        parser.error('the following arguments are required: --id, --title, --out')
    try:
        regions = list(args.region)
        if args.sources:
            if args.dem is None or args.work is None:
                parser.error('--sources requires --dem and --work')
            regions += grid_regions(args.sources, args.dem, args.work, args.grid)
        vegetation = {k: v for k, v in (('treeLine', args.tree_line), ('coniferStart', args.conifer_start)) if v is not None}
        result = build_country(args.id, args.title, args.version, regions, args.out, args.bbox,
                               jobs=args.jobs, landing=args.landing, landcover=args.landcover, vegetation=vegetation)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(result)


if __name__ == '__main__':
    main()
