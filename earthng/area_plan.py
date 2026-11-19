"""Plan player selections as independently installable country sections, in WGS84 lon/lat."""
import gzip
import hashlib
import math
from functools import lru_cache
from pathlib import Path

from pyproj import Geod
import shapely
from shapely.affinity import translate
from shapely.geometry import Polygon, box as rectangle, mapping

import sections

GEOD = Geod(ellps='WGS84')
WIDTHS_KM = (1, 10, 100)


def _coordinate(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def validate_route(route, width_km=10):
    if not _coordinate(width_km) or width_km not in WIDTHS_KM:
        raise ValueError('Choose 1, 10 or 100 km on each side of the route.')
    points = []
    if not isinstance(route, (list, tuple)):
        raise ValueError('The route needs a list of longitude/latitude pairs.')
    for pair in route:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2 or not all(map(_coordinate, pair))
                or abs(pair[0]) > 180 or abs(pair[1]) > 90):
            raise ValueError('Route points must have a valid longitude and latitude.')
        lon, lat = map(float, pair)
        point = [lon if lon != -180 else 180., lat]
        if not points or point != points[-1]:
            points.append(point)
    if len(points) < 2:
        raise ValueError('Choose at least two different route points.')
    return points, int(width_km)


def _polygons(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type == 'Polygon':
        yield geometry
    elif geometry.geom_type in ('GeometryCollection', 'MultiPolygon'):
        for child in geometry.geoms:
            yield from _polygons(child)


def _wrap_ring(ring):
    """Keep a short geodesic footprint on its side(s) of the date line."""
    points = [ring[0]]
    for lon, lat in ring[1:] + ring[:1]:
        lon += 360 * round((points[-1][0] - lon) / 360)
        points.append((lon, lat))
    if abs(points[-1][0] - points[0][0]) > 180:
        pole = 90 if points[0][1] > 0 else -90
        points.extend([(points[-1][0], pole), (points[0][0], pole)])
    shape = Polygon(points)
    if not shape.is_valid:
        shape = shapely.make_valid(shape)
    west, _, east, _ = shape.bounds
    if -180 <= west and east <= 180:
        yield from _polygons(shape)
        return
    for wrap in range(math.floor((west + 180) / 360), math.ceil((east + 180) / 360)):
        band = rectangle(wrap*360 - 180, -90, wrap*360 + 180, 90)
        for piece in _polygons(shape.intersection(band)):
            yield translate(piece, xoff=-wrap*360)


def _corridor(points, width):
    # Short ellipsoidal legs avoid a single local projection distorting a transcontinental
    # buffer. Round caps join at turns, U-turns and endpoints. Offset distances are in metres.
    pieces = []
    for start, end in zip(points, points[1:]):
        _, _, length = GEOD.inv(*start, *end)
        steps = math.ceil(length / 20_000)
        if not steps:
            continue
        track = [start, *(GEOD.npts(*start, *end, steps - 1) if steps > 1 else []), end]
        for a, b in zip(track, track[1:]):
            forward, back, _ = GEOD.inv(*a, *b)
            ring = []
            for (lon, lat), heading in ((a, forward + 90), (b, back + 90)):
                angles = [heading + angle for angle in range(0, 181, 5)]
                x, y, _ = GEOD.fwd([lon]*len(angles), [lat]*len(angles), angles, [width*1000]*len(angles))
                ring.extend(zip(x, y))
            pieces.extend(_wrap_ring(ring))
    if not pieces:
        raise ValueError('Choose at least two different route points.')
    return shapely.union_all(pieces, grid_size=1e-9)


def _selection_box(box):
    if not isinstance(box, (tuple, list)) or len(box) != 4 or not all(map(_coordinate, box)):
        raise ValueError('The selection needs four finite coordinates.')
    west, south, east, north = box
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south < north <= 90) or west == east:
        raise ValueError('Select a non-empty rectangle within the map.')
    if west < east:
        return rectangle(*box)
    halves = [rectangle(w, south, e, north) for w, e in ((west, 180), (-180, east)) if w < e]
    if not halves:
        raise ValueError('Select a non-empty rectangle within the map.')
    return shapely.union_all(halves)


def _km2(geometry):
    # Integral over straight lon/lat edges on the authalic sphere. Unlike a single signed
    # geodesic ring this also gives the correct area for rectangles wider than a hemisphere.
    def ring_area(ring):
        coords = list(ring.coords)
        total = 0.
        for (x, y), (x1, y1) in zip(coords, coords[1:]):
            half = math.radians(y1 - y) / 2
            sine = math.sin(math.radians((y1 + y) / 2))
            total += math.radians(x1 - x) * sine * (math.sin(half)/half if half else 1.)
        return abs(total) * 6371.0088**2
    return sum(ring_area(p.exterior) - sum(ring_area(h) for h in p.interiors) for p in _polygons(geometry))


@lru_cache(maxsize=1)
def _land():
    # Natural Earth public-domain ne_10m_land.geojson from build_basemap.py. Each of its
    # 6,837 land polygons was simplified at 0.012 degrees with topology preserved, then
    # stored as a little-endian WKB GeometryCollection. Only used to choose coastal extracts.
    path = Path(__file__).with_name('area_land.wkb.gz')
    with gzip.open(path, 'rb') as source:
        return shapely.STRtree(shapely.get_parts(shapely.from_wkb(source.read())))


def _near_land(shape):
    return bool(len(_land().query(shape, predicate='dwithin', distance=0.06)))


def _regions(shape):
    """Bisect only occupied branches, never the bounding grid of a diagonal or wrapped route."""
    west, south, east, north = shape.bounds
    width = (east - west) * 111.32 * math.cos(math.radians((south + north)/2))
    height = (north - south) * 110.57
    # Leave room for sections.box()'s source margin (at most 4.5 km).
    if max(width, height) <= sections.MAX_SPAN_KM - 6 and east - west <= 6:
        yield shape
        return
    if width >= height or east - west > 6:
        mid = (west + east) / 2
        halves = (rectangle(west, south, mid, north), rectangle(mid, south, east, north))
    else:
        mid = (south + north) / 2
        halves = (rectangle(west, south, east, mid), rectangle(west, mid, east, north))
    for half in halves:
        piece = shapely.union_all(list(_polygons(shape.intersection(half))))
        if not piece.is_empty:
            yield from _regions(piece)


def plan(boundaries, by_id, *, box=None, route=None, width_km=10):
    """'uncovered_km2' includes water skipped between Geofabrik extracts."""
    if (box is None) == (route is None):
        raise ValueError('Choose either an area or a route.')
    if route is None:
        requested = _selection_box(box)
        kind = 'area'
    else:
        requested = _corridor(*validate_route(route, width_km))
        kind = 'route'
    # Smaller extracts own overlapping land first. Where a parent contains only offshore
    # leftovers do not fetch a continent for them. The coastline never cuts a section.
    candidates = sorted((g.area, key) for key, g in boundaries.items() if key in by_id and g.intersects(requested))
    remaining = requested
    parts = []
    for _, key in candidates:
        if remaining.is_empty:
            break
        boundary = boundaries[key]
        pieces = list(_polygons(remaining.intersection(boundary)))
        if not pieces:
            continue
        selected = shapely.union_all(pieces)
        # A regional extract that alone covers a small island is usable even if Natural
        # Earth's coastline omits it. Whole-continent fallback still needs some land.
        if not (not parts and by_id[key].get('parent') and boundary.covers(requested)) and not _near_land(selected):
            continue
        for footprint in _regions(selected):
            identity = hashlib.sha256(shapely.normalize(footprint).wkb).hexdigest()[:16]
            x, y = footprint.representative_point().coords[0]
            section = {'id': f'{kind}-{identity}', 'name': f"{by_id[key]['name']} ({y:.3f}, {x:.3f})",
                       'box': list(footprint.bounds), 'geometry': mapping(footprint), 'margin': 0}
            parts.append({'place': key, 'section': section})
        remaining = remaining.difference(boundary)
    if not parts:
        raise ValueError('No source with land coverage was found for this selection.')
    return {'parts': parts, 'km2': round(_km2(requested), 2), 'uncovered_km2': round(_km2(remaining), 2),
            'geojson': mapping(requested), 'bounds': list(requested.bounds)}
