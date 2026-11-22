"""The proving ground: an island that does not exist, drawn at Point Nemo for testing the generator.

    python earthng/proving_ground.py                 # out/polygon/earthng_polygon.zip
    python earthng/proving_ground.py --plan          # the plan alone: PBF, tiles.json, plan.png

Real maps are a poor test bench: a surface or a junction of one kind has to be found first, it
lies among a hundred other things, and a camera aimed by coordinates looks past it. Here every
500 m tile of the game holds one subject (proving_zones.py), its street is named after what it
shows, and the cameras are part of the plan. The island is ordinary pack input: an OSM file
written from the plan and Terrarium heights computed from it go through the same cut, index and
exporter as a country (spot_pack.py), so what is tested is the pipeline players get.

The plan is in metres of the pack's own frame (x east, y north, the origin where four OSM cells
meet), so a plan tile is a game tile: tile (i, j) is x in [500 i, 500 i + 500).

Round the main grid lie four universes (BLOCKS; mod/lua/ge/extensions/e2r/universe.lua): a
mountain range, a desert, deep snow and deep mud. Each has the same sample of the main grid's
subjects, built by its own rules, and land of its own; the pack's manifest names the universe
of every tile, and the game builds the tile by it.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from osm_tiles import BUFFER, CELL  # noqa: E402

ID = 'polygon'
TITLE = 'Полігон · точка Немо'
VERSION = '0.1.0'
POINT_NEMO = (-48.8767, -123.3933)      # lat, lon of the oceanic pole of inaccessibility
# OSM cells (0.05 degrees) of the package, half-open: 6 x 5 cells, 22 x 28 km of ocean. The
# frame's origin is the middle of the package box (fast_sources.source_identity): the corner of
# four cells in longitude, the middle of a cell in latitude, 520 m from Point Nemo.
CELLS = (-2471, -980, -2465, -975)
CENTRE = (-48.875, -123.4)              # lat, lon
TILE = 500.
COLS, ROWS = range(-7, 7), range(-5, 5)  # the main grid, a subject a tile: 14 x 10, 7 x 5 km
GRID = (COLS[0] * TILE, ROWS[0] * TILE, (COLS[-1] + 1) * TILE, (ROWS[-1] + 1) * TILE)
RING = 120.                             # the ring road runs this far outside the grid
SHORE = 420.                            # the coastline this far outside the outermost block
CORNER = 500.                           # radius of the island's corners
BASE = 12.                              # metres above the sea of the flat land
# The island's blocks of tiles, half-open (i0, i1, j0, j1): the main grid and, a tile of ring
# road away, a universe on each side. prefix: of a tile's code ('MT-C2'; the main grid has none).
BLOCKS = (
    {'id': 'main', 'prefix': '', 'title': 'Основна сітка', 'titleEn': 'Main grid', 'tiles': (-7, 7, -5, 5), 'universe': None},
    {'id': 'mountains', 'prefix': 'MT', 'title': 'Гори', 'titleEn': 'Mountains', 'tiles': (-8, 8, 6, 12), 'universe': 'mountains'},
    {'id': 'desert', 'prefix': 'DS', 'title': 'Пустеля', 'titleEn': 'Desert', 'tiles': (-8, 8, -11, -6), 'universe': 'desert'},
    {'id': 'snow', 'prefix': 'SN', 'title': 'Сніг', 'titleEn': 'Snow', 'tiles': (-13, -8, -6, 6), 'universe': 'snow'},
    {'id': 'mud', 'prefix': 'MD', 'title': 'Багно', 'titleEn': 'Mud', 'tiles': (8, 13, -6, 6), 'universe': 'mud'},
    # (the island's south-east corner, between the desert and the mud)
    {'id': 'jungle', 'prefix': 'JG', 'title': 'Джунглі', 'titleEn': 'Jungle', 'tiles': (8, 13, -11, -6), 'universe': 'jungle'},
)
BLOCK = {b['id']: b for b in BLOCKS}
# the land every block stands on, in metres: the coastline runs SHORE outside it
LAND = (min(b['tiles'][0] for b in BLOCKS) * TILE, min(b['tiles'][2] for b in BLOCKS) * TILE,
        max(b['tiles'][1] for b in BLOCKS) * TILE, max(b['tiles'][3] for b in BLOCKS) * TILE)
# The sun the island is lit by (world.lua reads the manifest's 'sun'): Kyiv's, which the look is
# tuned to. Point Nemo's own June noon stands 18 degrees over the horizon: long shadows all day.
SUN = (50.45, 30.52)
LOOK = {'block': 'postsoviet', 'asphalt': 'worn', 'markings': 'white', 'verge': 'grass',
        'buildings': 'panel', 'trees': 'regional', 'statics': 'street'}


def box():
    """The package box: the cells and the pad a cut needs to keep their tiles (spot_pack.spot_box)."""
    pad = BUFFER + 0.002
    x0, y0, x1, y1 = CELLS
    return [round(x0 * CELL - pad, 6), round(y0 * CELL - pad, 6), round(x1 * CELL + pad, 6), round(y1 * CELL + pad, 6)]


def frame():
    from fast_sources import Frame
    return Frame.at(CENTRE[1], CENTRE[0])


def block_of(i, j):
    """The block a tile belongs to, or None (the ring road's corridor, the island's corners)."""
    for b in BLOCKS:
        i0, i1, j0, j1 = b['tiles']
        if i0 <= i < i1 and j0 <= j < j1:
            return b
    return None


def code(i, j):
    """A tile's name on the plan: columns A.. from the west, rows 1.. from the south of its block,
    after the block's prefix ('D7' in the main grid, 'MT-C2' in the mountains)."""
    b = block_of(i, j)
    if b is None:
        raise ValueError(f'tile {i}, {j} is in no block')
    name = f"{chr(65 + i - b['tiles'][0])}{j - b['tiles'][2] + 1}"
    return f"{b['prefix']}-{name}" if b['prefix'] else name


def tags(spec='', **more):
    """'highway=residential lanes=2' and name='...' as a tag dict (a__b for the key a:b)."""
    out = dict(item.split('=', 1) for item in spec.split())
    out.update({k.replace('__', ':'): str(v) for k, v in more.items() if v is not None})
    return out


def inland(x, y):
    """Metres from the coastline, positive on land: the island is a rectangle with round corners,
    SHORE outside the land of its blocks."""
    import numpy as np
    cx, cy = (LAND[0] + LAND[2]) / 2, (LAND[1] + LAND[3]) / 2
    hx, hy = (LAND[2] - LAND[0]) / 2 + SHORE, (LAND[3] - LAND[1]) / 2 + SHORE
    qx, qy = np.abs(x - cx) - (hx - CORNER), np.abs(y - cy) - (hy - CORNER)
    return CORNER - (np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0))


def smooth(t):
    import numpy as np
    t = np.clip(t, 0., 1.)
    return t * t * (3 - 2 * t)


class Plan:
    """Points, lines and areas in frame metres with OSM tags, the relief and the list of tiles."""

    def __init__(self):
        self.points = []                # [x, y, tags]
        self.index = {}                 # (cm, cm) -> point number: a point drawn twice is one node
        self.ways = []                  # [point numbers, tags]
        self.relations = []             # [[('w', way number, role)], tags]
        self.relief = []                # f(x, y) arrays -> metres added to the flat land
        self.carve = []                 # f(x, y, h) arrays -> h: after the relief (a river bed)
        self.tiles = {}                 # code -> {'i', 'j', 'block', 'zone', 'title', 'tags', 'views'}
        self.zones = []                 # {'id', 'title', 'titleEn', 'start': (x, y)}

    # --- drawing ---------------------------------------------------------------------------------
    def node(self, x, y, tag=None):
        key = (round(x * 100), round(y * 100))
        n = self.index.get(key)
        if n is None:
            n = self.index[key] = len(self.points)
            self.points.append([float(x), float(y), {}])
        if tag:
            self.points[n][2].update(tag)
        return n

    def way(self, pts, tag):
        ids = []
        for p in pts:
            n = p if isinstance(p, int) else self.node(p[0], p[1])
            if not ids or ids[-1] != n:
                ids.append(n)
        if len(ids) < 2:
            raise ValueError(f'a way of one point: {tag}')
        self.ways.append([ids, dict(tag)])
        return len(self.ways) - 1

    def area(self, pts, tag):
        pts = list(pts)
        return self.way(pts + [pts[0]], tag)

    def rect(self, x0, y0, x1, y1, tag):
        return self.area([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], tag)

    def box(self, cx, cy, w, d, tag, angle=0.):
        """A w x d rectangle round a point, its long side turned by angle (degrees, from east)."""
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        return self.area([(cx + u * c - v * s, cy + u * s + v * c)
                          for u, v in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))], tag)

    def hole(self, outer, inner, tag):
        """An area with a hole: a multipolygon of two rings (a block round its courtyard)."""
        a, b = self.area(outer, {}), self.area(inner, {})
        self.relations.append([[('w', a, 'outer'), ('w', b, 'inner')], dict(tag, type='multipolygon')])

    def arc(self, cx, cy, r, a0, a1, step=8.):
        """Points of an arc (degrees from east, counter-clockwise when a1 > a0)."""
        n = max(2, int(abs(math.radians(a1 - a0)) * r / step) + 1)
        return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * k / n)),
                 cy + r * math.sin(math.radians(a0 + (a1 - a0) * k / n))) for k in range(n + 1)]

    # --- the road net --------------------------------------------------------------------------
    @staticmethod
    def _net(tag):
        return ('highway' in tag or tag.get('railway') in ('rail', 'light_rail', 'tram', 'narrow_gauge')) \
            and tag.get('area') != 'yes'

    @staticmethod
    def _level(tag):
        return (tag.get('layer', '0'), tag.get('bridge', 'no') != 'no', tag.get('tunnel', 'no') != 'no')

    def weld(self):
        """Give two lines of the net a common node where they meet on one level. The zones only
        draw lines; a junction the exporter can read needs the node in both ways. A track that
        meets a road becomes a level crossing."""
        import shapely
        segments, owners = [], []
        for k, (ids, tag) in enumerate(self.ways):
            if not self._net(tag):
                continue
            for a, b in zip(ids, ids[1:]):
                pa, pb = self.points[a], self.points[b]
                segments.append(shapely.LineString([pa[:2], pb[:2]]))
                owners.append((k, a, b))
        if not segments:
            return 0
        tree = shapely.STRtree(segments)
        first, second = tree.query(segments, predicate='intersects')
        cuts = defaultdict(list)        # way -> [(a, b, new node)]
        made = 0
        for i, j in zip(first.tolist(), second.tolist()):
            if i >= j:
                continue
            (wa, a0, a1), (wb, b0, b1) = owners[i], owners[j]
            ta, tb = self.ways[wa][1], self.ways[wb][1]
            if self._level(ta) != self._level(tb):
                continue
            hit = segments[i].intersection(segments[j])
            if hit.geom_type != 'Point':
                continue                # lines lying on each other: the plan's own mistake
            n = self.node(hit.x, hit.y)
            for way, s0, s1 in ((wa, a0, a1), (wb, b0, b1)):
                if n not in (s0, s1):
                    cuts[way].append((s0, s1, n))
                    made += 1
            if ('railway' in ta) != ('railway' in tb):
                road = tb if 'railway' in ta else ta
                if road.get('highway') in ('footway', 'path', 'cycleway', 'pedestrian', 'steps', 'bridleway'):
                    self.points[n][2].setdefault('railway', 'crossing')
                else:
                    self.points[n][2].setdefault('railway', 'level_crossing')
        for way, items in cuts.items():
            ids = self.ways[way][0]
            extra = defaultdict(set)
            for s0, s1, n in items:
                extra[(s0, s1)].add(n)
            out = [ids[0]]
            for a, b in zip(ids, ids[1:]):
                pa = self.points[a]
                for n in sorted(extra.get((a, b), ()), key=lambda n: math.dist(pa[:2], self.points[n][:2])):
                    if out[-1] != n:
                        out.append(n)
                if out[-1] != b:
                    out.append(b)
            self.ways[way][0] = out
        return made

    # --- heights -------------------------------------------------------------------------------
    def height(self, x, y):
        """Ground in metres above the sea at frame points (arrays)."""
        import numpy as np
        x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
        d = inland(x, y)
        # the beach rises from the water's edge, the land is level from 260 m in; the sea bed
        # falls away so that the sea plane covers it whatever the exporter's despike does
        land = .6 + (BASE - .6) * smooth(d / 260.)
        h = np.where(d >= 0, land, np.maximum(-60., -1.5 + d * .08))
        if self.relief:
            extra = np.zeros_like(h)
            for f in self.relief:
                extra = extra + f(x, y)
            h = h + extra * smooth(d / 200.)      # no hill reaches the beach
        for f in self.carve:
            h = f(x, y, h)
        return h

    def write_dem(self, index, dem):
        """The Terrarium z12 tiles under a cut index, computed from the plan (fast_dem.audit)."""
        import numpy as np
        from PIL import Image
        import fast_dem
        fr = frame()
        paths = fast_dem.audit(index, dem)
        k = (np.arange(256) + .5) / 256
        for path in paths:
            tx, ty = int(path.parent.name), int(path.stem)
            lon = (tx + k) / 4096 * 360 - 180
            lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * (ty + k) / 4096))))
            lons, lats = np.meshgrid(lon, lat)
            x, y = fr.local(lons, lats)
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(fast_dem.terrarium_rgb(self.height(x, y)), 'RGB').save(path)
        return len(paths)

    # --- output --------------------------------------------------------------------------------
    def lonlat(self, x, y):
        lon, lat = frame().geographic(x, y)
        return float(lon), float(lat)

    def write_pbf(self, path):
        import numpy as np
        from osmium_compat import osmium
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + '.part')
        part.unlink(missing_ok=True)
        w, s, e, n = box()
        header = osmium.io.Header()
        header.add_box(osmium.osm.Box(osmium.osm.Location(w, s), osmium.osm.Location(e, n)))
        header.set('generator', 'EarthNG proving ground')
        xy = np.asarray([p[:2] for p in self.points])
        lons, lats = frame().geographic(xy[:, 0], xy[:, 1])
        writer = osmium.SimpleWriter(osmium.io.File(str(part), 'pbf'), header=header)
        try:
            for k, p in enumerate(self.points):
                writer.add_node(osmium.osm.mutable.Node(id=k + 1, version=1, visible=True, tags=p[2],
                                                        location=(round(float(lons[k]), 7), round(float(lats[k]), 7))))
            for k, (ids, tag) in enumerate(self.ways):
                writer.add_way(osmium.osm.mutable.Way(id=k + 1, version=1, visible=True, tags=tag,
                                                      nodes=[n + 1 for n in ids]))
            for k, (members, tag) in enumerate(self.relations):
                writer.add_relation(osmium.osm.mutable.Relation(
                    id=k + 1, version=1, visible=True, tags=tag,
                    members=[(kind, ref + 1, role) for kind, ref, role in members]))
        finally:
            writer.close()
        part.replace(path)
        return path

    def catalogue(self):
        """What the game shows of the plan: the zones to land in and every tile with its
        cameras, in the pack's manifest (world.lua reads country.polygon)."""
        def geo(x, y, *rest):
            lon, lat = self.lonlat(x, y)
            return [round(lat, 7), round(lon, 7), *rest]
        order = {b['id']: n for n, b in enumerate(BLOCKS)}
        tiles = []
        for name in sorted(self.tiles, key=lambda c: (order[self.tiles[c]['block']], self.tiles[c]['j'], self.tiles[c]['i'])):
            t = self.tiles[name]
            entry = {'code': name, 'i': t['i'], 'j': t['j'], 'block': t['block'], 'zone': t['zone'], 'title': t['title'],
                     'titleEn': t.get('titleEn') or t['title'], 'tags': t.get('tags', ''),
                     'at': geo(*t['at']), 'yaw': t.get('yaw', 90),
                     'views': [{'id': v['id'], 'eye': geo(*v['eye']), 'target': geo(*v['target']),
                                'fov': v.get('fov', 60)} for v in t['views']]}
            if BLOCK[t['block']]['universe']:
                entry['universe'] = BLOCK[t['block']]['universe']     # world.lua: the lab's default for the tile
            tiles.append(entry)
        zones = [{'id': z['id'], 'title': z['title'], 'titleEn': z['titleEn'], 'at': geo(*z['start'])}
                 for z in self.zones]
        blocks = [{'id': b['id'], 'title': b['title'], 'titleEn': b['titleEn'], 'universe': b['universe'],
                   'cols': [b['tiles'][0], b['tiles'][1] - 1], 'rows': [b['tiles'][2], b['tiles'][3] - 1]} for b in BLOCKS]
        import proving_zones
        return {'tile': TILE, 'blocks': blocks, 'zones': zones, 'tiles': tiles, 'themes': proving_zones.themes()}


def make_plan():
    import proving_zones
    plan = Plan()
    proving_zones.build(plan)
    plan.weld()
    return plan


def draw(plan, path, size=4200):
    """The plan as a picture: every way by its main tag, the tile grid and the codes."""
    from PIL import Image, ImageDraw
    west, south, east, north = LAND[0] - SHORE - 150, LAND[1] - SHORE - 150, LAND[2] + SHORE + 150, LAND[3] + SHORE + 150
    scale = size / (east - west)
    image = Image.new('RGB', (size, round((north - south) * scale)), (36, 78, 110))
    pen = ImageDraw.Draw(image)

    def px(x, y):
        return (x - west) * scale, (north - y) * scale
    fill = {'landuse': (150, 170, 120), 'natural': (120, 160, 110), 'leisure': (140, 190, 130),
            'amenity': (170, 170, 170), 'building': (200, 150, 120), 'place': (180, 180, 180)}
    coast = [w for w in plan.ways if w[1].get('natural') == 'coastline']
    for ids, _ in coast:
        pen.polygon([px(*plan.points[n][:2]) for n in ids], fill=(196, 206, 170))
    for order in ('landuse', 'natural', 'leisure', 'amenity', 'place', 'building'):
        for ids, tag in plan.ways:
            if order in tag and ids[0] == ids[-1] and len(ids) > 3 and tag.get('natural') != 'coastline' \
                    and 'highway' not in tag:
                colour = (90, 150, 200) if tag.get('natural') == 'water' else fill[order]
                pen.polygon([px(*plan.points[n][:2]) for n in ids], fill=colour, outline=(90, 90, 90))
    for ids, tag in plan.ways:
        line = [px(*plan.points[n][:2]) for n in ids]
        if 'highway' in tag and tag.get('area') != 'yes':
            major = tag['highway'] in ('motorway', 'trunk', 'primary', 'secondary', 'tertiary')
            foot = tag['highway'] in ('footway', 'path', 'cycleway', 'steps', 'track', 'pedestrian', 'bridleway')
            pen.line(line, fill=(120, 90, 60) if foot else (250, 250, 250), width=1 if foot else 3 if major else 2)
        elif 'railway' in tag:
            pen.line(line, fill=(30, 30, 30), width=2)
        elif 'waterway' in tag:
            pen.line(line, fill=(90, 150, 200), width=3)
        elif 'barrier' in tag:
            pen.line(line, fill=(90, 60, 40), width=1)
    for b in BLOCKS:
        colour = (255, 210, 0) if b['id'] == 'main' else (255, 140, 60)
        for i in range(b['tiles'][0], b['tiles'][1]):
            for j in range(b['tiles'][2], b['tiles'][3]):
                x0, y0 = px(i * TILE, (j + 1) * TILE)
                x1, y1 = px((i + 1) * TILE, j * TILE)
                pen.rectangle([x0, y0, x1, y1], outline=colour)
                pen.text((x0 + 3, y0 + 2), code(i, j), fill=colour)
    image.save(path)
    return path


def build(out=ROOT / 'out' / 'polygon', jobs=2, emit=print, plan_only=False):
    import os
    out = Path(out)
    work = out / 'work'
    plan = make_plan()
    emit(f'plan: {len(plan.points)} nodes, {len(plan.ways)} ways, {len(plan.tiles)} tiles')
    if work.exists():
        shutil.rmtree(work)             # a plan changes whole: nothing of the last build is reused
    pbf = plan.write_pbf(work / 'polygon.osm.pbf')
    catalogue = plan.catalogue()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'tiles.json').write_text(json.dumps(catalogue, ensure_ascii=False, indent=1), encoding='utf-8')
    draw(plan, out / 'plan.png')
    if plan_only:
        return pbf

    import build_country
    import country_fetch
    import fast_style
    os.environ['EARTHNG_POIS'] = '1'    # shops and doors as points, as the Map Builder builds
    fast_style.POIS = True
    # the folder's name is the region's id in the pack (build_country.grid_regions)
    tiles = country_fetch.cut_tiles(pbf, work / ID, box(), jobs, emit)
    index = json.loads((tiles / 'index.json').read_text(encoding='utf-8'))
    w, s, e, n = index['package_box']
    centre = (round((s + n) / 2, 6), round((w + e) / 2, 6))
    if centre != CENTRE:
        raise RuntimeError(f'the cut kept {index["package_box"]}: its middle {centre} is not the plan origin {CENTRE}')
    dem = work / 'dem'
    emit(f'DEM: {plan.write_dem(index, dem)} tiles from the plan')
    regions = build_country.grid_regions(tiles, dem, work / 'world', emit=emit)
    from build_map import build as build_map
    map_data = build_map(pbf, work / 'map', emit=emit)
    start = plan.zones[0]['start'] if plan.zones else (0., 0.)
    lon, lat = plan.lonlat(start[0], start[1])
    return build_country.build_country(ID, TITLE, VERSION, regions, out, emit=emit, jobs=jobs, landing=(lat, lon),
                                       look=LOOK, map_data=map_data, experiments={'detail': True, 'shopfront': True},
                                       extra={'polygon': catalogue, 'sun': {'lat': SUN[0], 'lon': SUN[1]}})


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--out', type=Path, default=ROOT / 'out' / 'polygon')
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--plan', action='store_true', help='write the plan (PBF, tiles.json, plan.png) and stop')
    a = p.parse_args()
    print(build(a.out, a.jobs, plan_only=a.plan))


if __name__ == '__main__':
    main()
