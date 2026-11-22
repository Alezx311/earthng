"""What stands on the proving ground (proving_ground.py): one subject a tile, one theme a row.

Every tile has its row's avenue through its middle, west to east, named after what the tile
shows; the game's street line reads that name, so the driver sees the tags under the wheels.
Column H is the junctions: the meridian crosses every avenue there in a different way. A ring
road runs round the grid, the coast is beach, shingle, rock and a harbour.

    row 10  road classes          row 5  street furniture and points of interest
    row 9   surfaces              row 4  ground covers
    row 8   lanes and markings    row 3  vegetation
    row 7   town blocks           row 2  water and rails
    row 6   houses, trade, works  row 1  relief

A subject is a table row where it can be: a new surface or cover is one more line.
"""
import math

from proving_ground import BASE, COLS, CORNER, GRID, LAND, RING, ROWS, SHORE, TILE, block_of, code, tags

MERIDIAN = 250.         # x of the north-south road: the middle of column H


# --- helpers -----------------------------------------------------------------------------------
def origin(i, j):
    return i * TILE, j * TILE


def centre_y(j):
    return j * TILE + TILE / 2


def register(plan, i, j, zone, title, title_en=None, tag_text=''):
    """A tile's entry in the game's list: where the car lands in it and its three cameras."""
    x0, y0 = origin(i, j)
    yc = y0 + TILE / 2
    plan.tiles[code(i, j)] = {
        'i': i, 'j': j, 'block': block_of(i, j)['id'], 'zone': zone, 'title': title, 'titleEn': title_en, 'tags': tag_text,
        'at': (x0 + 30, yc - 1.6), 'yaw': 90,
        'views': [{'id': 'street', 'eye': (x0 + 40, yc - 5, 2.4), 'target': (x0 + 250, yc, 1.), 'fov': 55},
                  {'id': 'over', 'eye': (x0 + 250, y0 - 90, 190), 'target': (x0 + 250, y0 + 235, 0), 'fov': 60},
                  {'id': 'top', 'eye': (x0 + 250, yc - 1, 520), 'target': (x0 + 250, yc, 0), 'fov': 55}]}
    return x0, y0, yc


def open_ground(plan, i, j):
    """Mown grass under a whole tile. Land with no tag is the generator's to plant, and it plants
    woods: a tile that shows a road, a slope or a junction keeps its subject in sight this way.
    Rows of town, covers and plants leave their ground as OSM would have it."""
    x0, y0 = origin(i, j)
    plan.rect(x0, y0, x0 + TILE, y0 + TILE, tags('landuse=meadow'))


def avenue(plan, i, j, tag, label, xs=()):
    """The row's road across a tile. xs: more points along it (metres from the tile's west edge)."""
    x0, y0 = origin(i, j)
    yc = y0 + TILE / 2
    pts = [(x0 + x, yc) for x in sorted({0., TILE, *map(float, xs)})]
    return plan.way(pts, dict(tag, name=f'{code(i, j)} {label}'))


def plots(i, j, side, n, setback=24., edge=14., gap=12.):
    """n plots in a row on one side of the avenue ('n' or 's'): (x0, y0, x1, y1) each."""
    x0, y0 = origin(i, j)
    w = (TILE - 2 * edge - (n - 1) * gap) / n
    ya, yb = (y0 + TILE / 2 + setback, y0 + TILE - edge) if side == 'n' else (y0 + edge, y0 + TILE / 2 - setback)
    return [(x0 + edge + k * (w + gap), ya, x0 + edge + k * (w + gap) + w, yb) for k in range(n)]


def along(a, b, step, inset=0.):
    """Points every step metres from a to b, the ends inset."""
    length = math.dist(a, b)
    n = max(1, int((length - 2 * inset) / step))
    return [(a[0] + (b[0] - a[0]) * (inset + k * step) / length, a[1] + (b[1] - a[1]) * (inset + k * step) / length)
            for k in range(n + 1)]


def shrunk(rect, by):
    return rect[0] + by, rect[1] + by, rect[2] - by, rect[3] - by


# --- the coast and the roads every row shares ---------------------------------------------------
def _round(plan, side, rect, r):
    """One side of a rectangle with round corners of radius r, counter-clockwise, corner to corner."""
    x0, y0, x1, y1 = rect
    a, b, c, d = x0 + r, y0 + r, x1 - r, y1 - r
    corners = {'s': ((a, b, 225, 270), (c, b, 270, 315)), 'e': ((c, b, 315, 360), (c, d, 0, 45)),
               'n': ((c, d, 45, 90), (a, d, 90, 135)), 'w': ((a, d, 135, 180), (a, b, 180, 225))}
    out = []
    for x, y, a0, a1 in corners[side]:
        out += plan.arc(x, y, r, a0, a1)
    return out


OUTLINE = (LAND[0] - SHORE, LAND[1] - SHORE, LAND[2] + SHORE, LAND[3] + SHORE)


def _side(plan, side, d):
    """One side of the island's outline, d metres inland."""
    return _round(plan, side, (OUTLINE[0] + d, OUTLINE[1] + d, OUTLINE[2] - d, OUTLINE[3] - d), CORNER - d)


def band(plan, side, d0, d1, tag):
    plan.area(_side(plan, side, d0) + _side(plan, side, d1)[::-1], tag)


def coast(plan):
    plan.area(sum((_side(plan, s, 0)[:-1] for s in 'senw'), []), tags('natural=coastline'))
    band(plan, 's', 3, 150, tags('natural=beach surface=sand', name='Південний пляж'))
    band(plan, 'w', 3, 150, tags('natural=beach surface=sand', name='Західний пляж'))
    band(plan, 'e', 3, 120, tags('natural=shingle', name='Галька'))
    band(plan, 'n', 3, 110, tags('natural=bare_rock', name='Північні скелі'))
    # a pier and a harbour basin on the east shore, a lighthouse on the north-east corner
    hx = OUTLINE[2]
    plan.way([(hx - 160, 600), (hx + 180, 600)], tags('man_made=pier highway=footway', name='Пірс'))
    basin = (hx - 230, 700., hx + 20, 1000.)
    plan.rect(*basin, tags('natural=water water=harbour', name='Гавань'))

    def dock(x, y, h):
        import numpy as np
        inside = (x > basin[0] - 20) & (x < basin[2] + 60) & (y > basin[1] - 20) & (y < basin[3] + 20)
        return np.where(inside, np.minimum(h, -3.), h)
    plan.carve.append(dock)
    plan.node(hx - 330, OUTLINE[3] - 330, tags('man_made=lighthouse', name='Маяк Немо'))
    lon, lat = -123.3933, -48.8767
    from proving_ground import frame
    x, y = frame().local(lon, lat)
    plan.node(float(x), float(y), tags('tourism=attraction historic=memorial', name='Точка Немо', name__en='Point Nemo'))


def ring(plan):
    around = (GRID[0] - RING, GRID[1] - RING, GRID[2] + RING, GRID[3] + RING)
    for side, label in zip('senw', ('південь', 'схід', 'північ', 'захід')):
        plan.way(_round(plan, side, around, 200.), tags('highway=secondary lanes=2 surface=asphalt', name=f'Кільцева ({label})'))
    for j in ROWS:
        yc = centre_y(j)
        for x, x1 in ((GRID[0], GRID[0] - RING), (GRID[2], GRID[2] + RING)):
            plan.way([(x, yc), (x1, yc)], tags('highway=tertiary', name=f'Ряд {j - ROWS[0] + 1}'))
    plan.way([(MERIDIAN, GRID[1]), (MERIDIAN, GRID[1] - RING)], tags('highway=tertiary', name='Меридіан'))
    plan.way([(MERIDIAN, GRID[3]), (MERIDIAN, GRID[3] + RING)], tags('highway=tertiary', name='Меридіан'))


# --- row 10: road classes -----------------------------------------------------------------------
CLASSES = (
    ('motorway 2x3', 'highway=motorway lanes=3', 16.),
    ('trunk 2x2', 'highway=trunk lanes=2', 10.),
    ('trunk lanes=4', 'highway=trunk lanes=4', 0),
    ('primary lanes=4', 'highway=primary lanes=4', 0),
    ('primary', 'highway=primary', 0),
    ('secondary', 'highway=secondary', 0),
    ('tertiary', 'highway=tertiary', 0),
    ('unclassified', 'highway=unclassified', 0),
    ('residential', 'highway=residential', 0),
    ('living_street', 'highway=living_street', 0),
    ('service', 'highway=service', 0),
    ('road', 'highway=road', 0),
    ('raceway', 'highway=raceway', 0),
)
PATHS = ('highway=footway', 'highway=cycleway', 'highway=path', 'highway=pedestrian',
         'highway=track tracktype=grade1', 'highway=track tracktype=grade3', 'highway=track tracktype=grade5',
         'highway=bridleway', 'highway=footway footway=sidewalk', 'highway=service service=driveway',
         'highway=service service=alley', 'highway=service service=parking_aisle', 'highway=steps')


def dual(plan, i, j, tag, label, gap):
    """A divided road across a tile: two one-way carriageways, joined to the row at both ends."""
    x0, y0 = origin(i, j)
    yc = y0 + TILE / 2
    name = f'{code(i, j)} {label}'
    plan.way([(x0, yc), (x0 + 50, yc)], dict(tag, name=name))
    plan.way([(x0 + 450, yc), (x0 + TILE, yc)], dict(tag, name=name))
    plan.way([(x0 + 50, yc), (x0 + 100, yc - gap / 2), (x0 + 400, yc - gap / 2), (x0 + 450, yc)],
             dict(tag, oneway='yes', name=name))
    plan.way([(x0 + 450, yc), (x0 + 400, yc + gap / 2), (x0 + 100, yc + gap / 2), (x0 + 50, yc)],
             dict(tag, oneway='yes', name=name))


def classes_tile(plan, i, j, k):
    label, spec, gap = CLASSES[k]
    x0, y0, yc = register(plan, i, j, 'classes', label, tag_text=spec)
    open_ground(plan, i, j)
    if gap:
        dual(plan, i, j, tags(spec), label, gap)
    else:
        avenue(plan, i, j, tags(spec), label)
    path = PATHS[k]
    plan.way([(x0 + 20, yc + 40), (x0 + 480, yc + 40)], tags(path, name=f'{code(i, j)} {path}'))
    # the same path on the other side with a surface a path often has
    soft = tags(path, surface='ground', name=f'{code(i, j)} {path} surface=ground')
    plan.way([(x0 + 20, yc - 40), (x0 + 480, yc - 40)], soft)
    # a way in from the avenue: a drive for what cars use, a footpath for the rest
    link = tags('highway=service') if path.startswith('highway=service') else tags('highway=footway')
    plan.way([(x0 + 60, yc + 40), (x0 + 60, yc), (x0 + 60, yc - 40)], link)


def road_classes(plan, j):
    for k, i in enumerate(c for c in COLS if c != 0):
        classes_tile(plan, i, j, k)


# --- row 9: surfaces ----------------------------------------------------------------------------
SURFACES = ('asphalt', 'concrete', 'concrete:plates', 'paving_stones', 'sett', 'cobblestone', 'compacted',
            'fine_gravel', 'gravel', 'dirt', 'ground', 'sand', 'grass')


def surfaces_tile(plan, i, j, k):
    s = SURFACES[k]
    x0, y0, yc = register(plan, i, j, 'surfaces', f'surface={s}', tag_text=f'highway=unclassified surface={s}')
    open_ground(plan, i, j)
    avenue(plan, i, j, tags('highway=unclassified', surface=s), f'surface={s}', xs=(120, 380))
    plan.way([(x0 + 20, yc + 34), (x0 + 480, yc + 34)], tags('highway=footway', surface=s))
    plan.way([(x0 + 20, yc - 34), (x0 + 480, yc - 34)], tags('highway=track', surface=s))
    north, south = plots(i, j, 'n', 2, setback=60), plots(i, j, 's', 2, setback=60)
    a = (north[0][0], north[0][1], north[0][2], north[0][1] + 70)
    plan.rect(*a, tags('amenity=parking parking=surface', surface=s, name=f'Стоянка {s}'))
    plan.way([(x0 + 120, yc), (x0 + 120, a[1] + 35), (a[2] - 10, a[1] + 35)],
             tags('highway=service service=parking_aisle', surface=s))
    b = (north[1][0], north[1][1], north[1][2], north[1][1] + 70)
    plan.rect(*b, tags('highway=pedestrian area=yes', surface=s, name=f'Площа {s}'))
    plan.way([(x0 + 380, yc), (x0 + 380, b[1])], tags('highway=footway', surface=s))
    c = (south[0][0], south[0][3] - 70, south[0][2], south[0][3])
    plan.rect(*c, tags('leisure=pitch sport=multi', surface=s, name=f'Майданчик {s}'))
    d = (south[1][0], south[1][3] - 70, south[1][2], south[1][3])
    plan.rect(*d, tags('landuse=industrial', surface=s, name=f'Двір {s}'))
    plan.way([(x0 + 380, yc), (x0 + 380, d[3] - 35), (d[2] - 10, d[3] - 35)], tags('highway=service', surface=s))


def surfaces(plan, j):
    for k, i in enumerate(c for c in COLS if c != 0):
        surfaces_tile(plan, i, j, k)


# --- row 8: lanes and markings ------------------------------------------------------------------
LANES = (
    ('lanes=1 (спільна смуга)', 'highway=residential lanes=1'),
    ('lanes=2', 'highway=secondary lanes=2'),
    ('lanes=3 (2+1)', 'highway=primary lanes=3 lanes:forward=2 lanes:backward=1'),
    ('lanes=4', 'highway=primary lanes=4'),
    ('lanes=6', 'highway=trunk lanes=6'),
    ('lanes=8', 'highway=trunk lanes=8'),
    ('lanes=4 turn:lanes', 'highway=primary lanes=4 lanes:forward=2 lanes:backward=2 '
                           'turn:lanes:forward=left|through;right turn:lanes:backward=left|through;right'),
    ('oneway lanes=1', 'highway=residential oneway=yes lanes=1'),
    ('oneway lanes=2', 'highway=secondary oneway=yes lanes=2'),
    ('oneway lanes=3', 'highway=primary oneway=yes lanes=3'),
    ('lane_markings=no', 'highway=tertiary lanes=2 lane_markings=no'),
    ('width=5.5', 'highway=residential width=5.5'),
    ('lanes 4 -> 2', None),
)


def lanes_tile(plan, i, j, k):
    label, spec = LANES[k]
    x0, y0, yc = register(plan, i, j, 'lanes', label, tag_text=spec or 'highway=primary lanes=4 / lanes=2')
    open_ground(plan, i, j)
    if spec is None:
        name = f'{code(i, j)} {label}'
        plan.way([(x0, yc), (x0 + 250, yc)], tags('highway=primary lanes=4', name=name))
        plan.way([(x0 + 250, yc), (x0 + TILE, yc)], tags('highway=primary lanes=2', name=name))
    else:
        avenue(plan, i, j, tags(spec), label, xs=(250,))
    # a side street of each kind to turn into: the mouth of a narrower road on a wider one
    plan.way([(x0 + 250, yc), (x0 + 250, yc + 200)], tags('highway=residential', name=f'{code(i, j)} бічна'))
    plan.way([(x0 + 250, yc), (x0 + 250, yc - 200)], tags('highway=service', name=f'{code(i, j)} проїзд'))
    plan.node(x0 + 250, yc + 200, tags('highway=turning_circle'))


def lanes(plan, j):
    for k, i in enumerate(c for c in COLS if c != 0):
        lanes_tile(plan, i, j, k)


# --- column H: junctions ------------------------------------------------------------------------
def _arms(plan, i, j, ave, mer, r=0., label=''):
    """The avenue and the meridian through a junction tile, stopping r metres short of its middle."""
    x0, y0 = origin(i, j)
    xm, yc = x0 + TILE / 2, y0 + TILE / 2
    name = f'{code(i, j)} {label}'
    if r:
        plan.way([(x0, yc), (xm - r, yc)], dict(ave, name=name))
        plan.way([(xm + r, yc), (x0 + TILE, yc)], dict(ave, name=name))
        plan.way([(xm, y0), (xm, yc - r)], dict(mer, name='Меридіан'))
        plan.way([(xm, yc + r), (xm, y0 + TILE)], dict(mer, name='Меридіан'))
    else:
        plan.way([(x0, yc), (xm, yc), (x0 + TILE, yc)], dict(ave, name=name))
        plan.way([(xm, y0), (xm, yc), (xm, y0 + TILE)], dict(mer, name='Меридіан'))
    return xm, yc


def _circle(plan, xm, yc, r, tag):
    pts = []
    for q in range(4):
        pts += plan.arc(xm, yc, r, q * 90, q * 90 + 90)[:-1]
    plan.area(pts, tag)


def _zebras(plan, xm, yc, d, kind='crossing=marked'):
    for dx, dy in ((d, 0), (-d, 0), (0, d), (0, -d)):
        plan.node(xm + dx, yc + dy, tags('highway=crossing ' + kind))


def _on(plan, way, x, y, tag):
    """A tagged node on a straight way of the plan (a sign's or a crossing's place on the road)."""
    ids = plan.ways[way][0]
    n = plan.node(x, y, tag)
    if n in ids:
        return n
    best = min(range(len(ids) - 1), key=lambda k: abs(
        math.dist(plan.points[ids[k]][:2], (x, y)) + math.dist((x, y), plan.points[ids[k + 1]][:2])
        - math.dist(plan.points[ids[k]][:2], plan.points[ids[k + 1]][:2])))
    ids.insert(best + 1, n)
    return n


def junction_tile(plan, i, j, row):
    """A junction of the meridian with a row's avenue; row: which of the ten kinds (the main grid's rows)."""
    ter, res = tags('highway=tertiary lanes=2'), tags('highway=residential')
    x0, y0 = origin(i, j)
    open_ground(plan, i, j)
    if row == 10:
        register(plan, i, j, 'junctions', 'Світлофор, 4 смуги', 'Signals, 4 lanes', 'highway=traffic_signals')
        xm, yc = _arms(plan, i, j, tags('highway=primary lanes=4'), tags('highway=secondary lanes=2'), label='світлофор')
        plan.node(xm, yc, tags('highway=traffic_signals'))
        for w in (len(plan.ways) - 2, len(plan.ways) - 1):
            horizontal = w == len(plan.ways) - 2
            for s in (-1, 1):
                _on(plan, w, xm + (s * 12 if horizontal else 0), yc + (0 if horizontal else s * 12),
                    tags('highway=crossing crossing=traffic_signals crossing:markings=zebra'))
    elif row == 9:
        register(plan, i, j, 'junctions', 'Кільце r=18', 'Roundabout r=18', 'junction=roundabout')
        xm, yc = _arms(plan, i, j, ter, ter, 18., 'кільце')
        _circle(plan, xm, yc, 18., tags('highway=tertiary junction=roundabout', name=f'{code(i, j)} кільце'))
    elif row == 8:
        register(plan, i, j, 'junctions', 'Знаки STOP', 'Stop signs', 'highway=stop')
        xm, yc = _arms(plan, i, j, tags('highway=secondary lanes=2'), res, label='STOP')
        for s in (-1, 1):
            _on(plan, len(plan.ways) - 1, xm, yc + s * 9, tags('highway=stop'))
    elif row == 7:
        register(plan, i, j, 'junctions', 'Міні-кільце', 'Mini roundabout', 'highway=mini_roundabout')
        xm, yc = _arms(plan, i, j, ter, res, label='міні-кільце')
        plan.node(xm, yc, tags('highway=mini_roundabout'))
    elif row == 6:
        register(plan, i, j, 'junctions', 'Зебри на всіх виїздах', 'Zebras on every arm', 'highway=crossing')
        xm, yc = _arms(plan, i, j, ter, ter, label='зебри')
        for w in (len(plan.ways) - 2, len(plan.ways) - 1):
            horizontal = w == len(plan.ways) - 2
            for s in (-1, 1):
                _on(plan, w, xm + (s * 9 if horizontal else 0), yc + (0 if horizontal else s * 9),
                    tags('highway=crossing crossing=uncontrolled crossing:markings=zebra'))
    elif row == 5:
        register(plan, i, j, 'junctions', 'Зміщене перехрестя', 'Staggered junction')
        xm, yc = x0 + TILE / 2, y0 + TILE / 2
        avenue(plan, i, j, tags('highway=secondary lanes=2'), 'зміщене')
        plan.way([(xm, y0), (xm, yc - 90), (xm - 35, yc - 45), (xm - 35, yc)], dict(res, name='Меридіан'))
        plan.way([(xm + 35, yc), (xm + 35, yc + 45), (xm, yc + 90), (xm, y0 + TILE)], dict(res, name='Меридіан'))
    elif row == 4:
        register(plan, i, j, 'junctions', 'Перетин під 45°', 'Skew crossing 45°')
        xm, yc = x0 + TILE / 2, y0 + TILE / 2
        avenue(plan, i, j, ter, 'під кутом')
        plan.way([(xm, y0), (xm, yc - 190), (xm - 120, yc - 120), (xm + 120, yc + 120), (xm, yc + 190),
                  (xm, y0 + TILE)], dict(ter, name='Меридіан'))
    elif row == 3:
        register(plan, i, j, 'junctions', 'Кільце r=40, п’ять виїздів', 'Roundabout r=40, five arms', 'junction=roundabout')
        xm, yc = _arms(plan, i, j, tags('highway=secondary lanes=2'), ter, 40., 'велике кільце')
        _circle(plan, xm, yc, 40., tags('highway=secondary junction=roundabout lanes=2', name=f'{code(i, j)} кільце'))
        a = math.radians(45)
        plan.way([(xm + 40 * math.cos(a), yc + 40 * math.sin(a)), (xm + 190, yc + 190)], dict(res, name=f'{code(i, j)} п’ятий'))
        plan.node(xm + 190, yc + 190, tags('highway=turning_circle'))
    elif row == 2:
        register(plan, i, j, 'junctions', 'Переїзд біля перехрестя', 'Level crossing by a junction', 'railway=level_crossing')
        xm, yc = _arms(plan, i, j, ter, ter, label='переїзд')
        plan.way([(x0 + 10, yc - 120), (x0 + TILE - 10, yc - 120)], tags('railway=rail gauge=1520', name='Вітка H2'))
    else:
        register(plan, i, j, 'junctions', 'Поступися дорогою', 'Give way', 'highway=give_way')
        xm, yc = _arms(plan, i, j, ter, res, label='give way')
        for s in (-1, 1):
            _on(plan, len(plan.ways) - 1, xm, yc + s * 9, tags('highway=give_way'))


def junctions(plan):
    for j in ROWS:
        junction_tile(plan, 0, j, j - ROWS[0] + 1)


# --- buildings ----------------------------------------------------------------------------------
def house(plan, cx, cy, w, d, tag, angle=0., doors=0, door='entrance=staircase'):
    """A w x d building; doors: that many entrances along its south (front) wall, nodes of the outline."""
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))

    def at(u, v):
        return cx + u * c - v * s, cy + u * s + v * c
    front = [(-w / 2 + w * (k + .5) / doors, -d / 2) for k in range(doors)]
    ring = [at(-w / 2, -d / 2)] + [at(*p) for p in front] + [at(w / 2, -d / 2), at(w / 2, d / 2), at(-w / 2, d / 2)]
    for p in front:
        plan.node(*at(*p), tags(door))
    return plan.area(ring, tag)


def shop(plan, x, y, spec, name, side=-1, depth=3., **more):
    """A shop as OSM has it: a point inside the building and a door on the wall towards the street."""
    plan.node(x, y, tags(spec, name=name, **more))
    plan.node(x, y + side * depth, tags('entrance=shop'))


def yard_road(plan, pts, name=None):
    return plan.way(pts, tags('highway=service', name=name))


def flats(levels, year, material=None, kind='apartments', **more):
    return tags(f'building={kind}', building__levels=levels, start_date=year, building__material=material, **more)


def town_old(plan, i, j, x0, y0, yc):
    """Blocks of the 1900s: houses wall to wall round a courtyard, about 105 x 92 m a block, lanes
    between them, shops on the avenue."""
    names = ('Пекарня', 'Кав’ярня «Точка»', 'Книгарня', 'Аптека', 'Квіти', 'Перукарня', 'Годинникар', 'Ательє')
    kinds = ('shop=bakery', 'amenity=cafe', 'shop=books', 'amenity=pharmacy', 'shop=florist', 'shop=hairdresser',
             'craft=watchmaker', 'shop=tailor')
    for side in (1, -1):
        for row in range(2):
            ya = yc + side * (16 + row * 108)
            yb = ya + side * 92
            lo, hi = min(ya, yb), max(ya, yb)
            for k in range(4):
                bx = x0 + 14 + k * 120
                outer = [(bx, lo), (bx + 106, lo), (bx + 106, hi), (bx, hi)]
                inner = [(bx + 12, lo + 12), (bx + 94, lo + 12), (bx + 94, hi - 12), (bx + 12, hi - 12)]
                plan.hole(outer, inner, flats(3 + (k + row) % 3, 1895 + 7 * k + 3 * row, 'brick', roof__shape='hipped'))
                if row == 0:
                    for n in range(2):
                        m = (2 * k + n + (4 if side < 0 else 0)) % 8
                        shop(plan, bx + 28 + n * 50, ya + side * 2, kinds[m], names[m], side=-side, depth=2.)
        # the lanes: three across between the blocks, one along between the rows, one behind
        for k in range(1, 4):
            x = x0 + 14 + k * 120 - 7
            plan.way([(x, yc), (x, yc + side * 232)], tags('highway=residential', name=f'{code(i, j)} провулок {k}'))
        for y, label in ((yc + side * 116, 'середня'), (yc + side * 232, 'задня')):
            plan.way([(x0 + 6, y), (x0 + 494, y)], tags('highway=residential', name=f'{code(i, j)} {label}'))
        for x in (x0 + 6, x0 + 494):
            plan.way([(x, yc), (x, yc + side * 232)], tags('highway=residential'))


def town_stalin(plan, i, j, x0, y0, yc):
    """1950s: long fronts of six floors on the avenue, wings behind, a square yard open to the back."""
    for side in (1, -1):
        for bx in (x0 + 24, x0 + 262):
            front = yc + side * 26
            house(plan, bx + 107, front, 214, 16, flats(6, 1953, 'plaster', roof__shape='hipped'), doors=5 if side < 0 else 0)
            for wx in (bx + 8, bx + 206):
                house(plan, wx, front + side * 68, 16, 120, flats(5, 1954, 'plaster', roof__shape='hipped'))
            plan.rect(bx + 60, min(front + side * 40, front + side * 110), bx + 150, max(front + side * 40, front + side * 110),
                      tags('leisure=park', name='Сквер у дворі'))
            shop(plan, bx + 60, front - side * 5, 'shop=supermarket', 'Гастроном', side=-side, depth=3.)
            shop(plan, bx + 150, front - side * 5, 'amenity=bank', 'Ощадкаса', side=-side, depth=3.)


def town_khrushchev(plan, i, j, x0, y0, yc):
    """1960s: five-floor slabs end-on to the avenue, a yard with a playground between each pair."""
    for side in (1, -1):
        for k in range(5):
            cx = x0 + 60 + k * 95
            cy = yc + side * 125
            house(plan, cx, cy, 12, 80, flats(5, 1962, 'brick' if k % 2 else 'panel'), angle=0)
            for n in range(4):
                plan.node(cx - 6, cy - 30 + n * 20, tags('entrance=staircase'))
            if k < 4:
                yard_road(plan, [(cx + 16, yc), (cx + 16, cy + side * 45)])
                if k % 2 == 0:
                    plan.rect(cx + 34, cy - 14, cx + 70, cy + 14, tags('leisure=playground'))
                else:
                    plan.rect(cx + 30, cy - 30, cx + 74, cy + 30, tags('amenity=parking parking=surface'))


def town_panel9(plan, i, j, x0, y0, yc):
    """1970s-80s: nine-floor panel slabs along the avenue and across it, driveways, a school-sized yard."""
    for side in (1, -1):
        house(plan, x0 + 130, yc + side * 40, 180, 13, flats(9, 1978, 'panel'), doors=6)
        house(plan, x0 + 370, yc + side * 40, 180, 13, flats(9, 1981, 'panel'), doors=6)
        house(plan, x0 + 46, yc + side * 140, 13, 130, flats(9, 1979, 'panel'))
        house(plan, x0 + 454, yc + side * 140, 13, 130, flats(9, 1983, 'panel'))
        house(plan, x0 + 250, yc + side * 215, 200, 13, flats(9, 1984, 'panel'), doors=6)
        yard_road(plan, [(x0 + 250, yc), (x0 + 250, yc + side * 60), (x0 + 70, yc + side * 60), (x0 + 70, yc + side * 195),
                         (x0 + 430, yc + side * 195), (x0 + 430, yc + side * 60), (x0 + 250, yc + side * 60)])
        plan.rect(x0 + 190, yc + side * 110 - 18, x0 + 250, yc + side * 110 + 18, tags('leisure=playground'))
        plan.rect(x0 + 270, yc + side * 110 - 16, x0 + 330, yc + side * 110 + 16, tags('leisure=pitch sport=soccer surface=asphalt'))
        plan.rect(x0 + 100, yc + side * 160 - 12, x0 + 180, yc + side * 160 + 12, tags('amenity=parking parking=surface'))
        for n in range(6):
            plan.node(x0 + 200 + n * 9, yc + side * 132, tags('amenity=bench' if n % 2 else 'natural=tree'))


def town_panel16(plan, i, j, x0, y0, yc):
    """1980s: sixteen-floor towers and one long twelve-floor wall."""
    for side in (1, -1):
        for k in range(4):
            house(plan, x0 + 70 + k * 120, yc + side * 55, 26, 26, flats(16, 1986, 'panel'), doors=1)
        house(plan, x0 + 250, yc + side * 170, 400, 14, flats(12, 1988, 'panel'), doors=10)
        yard_road(plan, [(x0 + 30, yc), (x0 + 30, yc + side * 110), (x0 + 470, yc + side * 110), (x0 + 470, yc)])
        plan.rect(x0 + 60, yc + side * 110 + side * 8, x0 + 200, yc + side * 110 + side * 34, tags('amenity=parking parking=surface'))
        plan.rect(x0 + 300, yc + side * 125 - 12, x0 + 350, yc + side * 125 + 12, tags('leisure=playground'))


def town_modern(plan, i, j, x0, y0, yc):
    """2010s: towers of 25 floors on a two-floor podium of shops, a fenced yard with a barrier."""
    for side in (1, -1):
        house(plan, x0 + 250, yc + side * 36, 400, 26, tags('building=retail building:levels=2 start_date=2016 building:material=glass'))
        for k, name in enumerate(('Сільпо', 'Аптека АНЦ', 'Нова Пошта', 'Кав’ярня', 'Фітнес')):
            spec = ('shop=supermarket', 'amenity=pharmacy', 'amenity=post_office', 'amenity=cafe', 'leisure=fitness_centre')[k]
            shop(plan, x0 + 90 + k * 80, yc + side * 26, spec, name, side=-side, depth=3., brand=name if k < 3 else None)
        for k in range(3):
            house(plan, x0 + 100 + k * 150, yc + side * 110, 30, 30,
                  flats(25, 2016 + k, 'concrete', building__colour='#d8d4c8', roof__shape='flat'), doors=1)
        fence = [(x0 + 40, yc + side * 60), (x0 + 460, yc + side * 60), (x0 + 460, yc + side * 220), (x0 + 40, yc + side * 220)]
        plan.area(fence, tags('barrier=fence fence_type=metal'))
        gate = plan.node(x0 + 460, yc + side * 180, tags('barrier=lift_gate'))
        yard_road(plan, [(x0 + 490, yc), (x0 + 490, yc + side * 180), gate, (x0 + 250, yc + side * 180)])
        plan.rect(x0 + 60, yc + side * 150, x0 + 240, yc + side * 200, tags('amenity=parking parking=surface access=private'))
        plan.rect(x0 + 270, yc + side * 150 - 2, x0 + 330, yc + side * 200, tags('leisure=playground'))


def town_centre(plan, i, j, x0, y0, yc):
    """Offices, a hotel and a business centre of glass."""
    for side in (1, -1):
        house(plan, x0 + 80, yc + side * 50, 110, 50, tags('building=office building:levels=12 building:material=glass start_date=2008', name='БЦ «Немо»'), doors=2, door='entrance=main')
        house(plan, x0 + 250, yc + side * 45, 120, 36, tags('building=hotel tourism=hotel building:levels=9 start_date=1985', name='Готель «Океан»'), doors=1, door='entrance=main')
        house(plan, x0 + 410, yc + side * 50, 110, 50, tags('building=commercial building:levels=4 start_date=1998'), doors=3, door='entrance=shop')
        house(plan, x0 + 130, yc + side * 160, 200, 60, tags('building=office building:levels=20 height=78 building:material=glass start_date=2019'), doors=1, door='entrance=main')
        plan.rect(x0 + 260, yc + side * 110 if side > 0 else yc - 220, x0 + 480, yc + 220 if side > 0 else yc - 110,
                  tags('amenity=parking parking=surface'))
        yard_road(plan, [(x0 + 250, yc), (x0 + 250, yc + side * 100), (x0 + 470, yc + side * 100)])


def town_retail(plan, i, j, x0, y0, yc):
    """A supermarket box and a mall, each behind its car park."""
    house(plan, x0 + 130, yc + 170, 200, 80, tags('building=retail shop=supermarket building:levels=1 height=9', name='АТБ', brand='АТБ'), doors=2, door='entrance=shop')
    plan.rect(x0 + 30, yc + 30, x0 + 230, yc + 120, tags('amenity=parking parking=surface'))
    plan.way([(x0 + 130, yc), (x0 + 130, yc + 75), (x0 + 40, yc + 75)], tags('highway=service service=parking_aisle'))
    plan.way([(x0 + 130, yc + 75), (x0 + 220, yc + 75)], tags('highway=service service=parking_aisle'))
    house(plan, x0 + 370, yc + 150, 200, 120, tags('building=retail shop=mall building:levels=3 height=18', name='ТРЦ «Атол»'), doors=3, door='entrance=main')
    plan.rect(x0 + 270, yc + 28, x0 + 470, yc + 82, tags('amenity=parking parking=surface'))
    plan.way([(x0 + 370, yc), (x0 + 370, yc + 55), (x0 + 280, yc + 55)], tags('highway=service service=parking_aisle'))
    house(plan, x0 + 120, yc - 150, 180, 90, tags('building=retail shop=doityourself building:levels=1 height=11', name='Епіцентр', brand='Епіцентр'), doors=2, door='entrance=shop')
    plan.rect(x0 + 30, yc - 95, x0 + 470, yc - 30, tags('amenity=parking parking=surface'))
    plan.way([(x0 + 250, yc), (x0 + 250, yc - 62), (x0 + 40, yc - 62)], tags('highway=service service=parking_aisle'))
    plan.way([(x0 + 250, yc - 62), (x0 + 460, yc - 62)], tags('highway=service service=parking_aisle'))
    house(plan, x0 + 380, yc - 160, 140, 70, tags('building=retail shop=furniture building:levels=2', name='Меблі'), doors=1, door='entrance=shop')
    house(plan, x0 + 250, yc - 222, 60, 20, tags('building=parking parking=multi-storey building:levels=4', name='Паркінг'))


def town_school(plan, i, j, x0, y0, yc):
    site = (x0 + 20, yc + 26, x0 + 480, yc + 232)
    plan.rect(*site, tags('amenity=school', name='Школа № 1'))
    plan.rect(*site, tags('barrier=fence fence_type=metal'))
    for cx, cy, w, d in ((x0 + 130, yc + 70, 160, 16), (x0 + 60, yc + 120, 16, 90), (x0 + 200, yc + 120, 16, 90), (x0 + 130, yc + 170, 160, 16)):
        house(plan, cx, cy, w, d, tags('building=school building:levels=3 start_date=1974'))
    plan.rect(x0 + 260, yc + 60, x0 + 460, yc + 200, tags('leisure=track sport=running surface=tartan'))
    plan.rect(x0 + 290, yc + 85, x0 + 430, yc + 175, tags('leisure=pitch sport=soccer surface=grass'))
    site = (x0 + 20, yc - 232, x0 + 250, yc - 26)
    plan.rect(*site, tags('amenity=kindergarten', name='Дитсадок «Хвиля»'))
    plan.rect(*site, tags('barrier=fence fence_type=chain_link'))
    house(plan, x0 + 110, yc - 100, 120, 40, tags('building=kindergarten building:levels=2 start_date=1982'), doors=2, door='entrance=main')
    for k in range(4):
        plan.rect(x0 + 40 + k * 50, yc - 220, x0 + 76 + k * 50, yc - 180, tags('leisure=playground'))
    plan.rect(x0 + 280, yc - 232, x0 + 480, yc - 26, tags('leisure=sports_centre', name='Спорткомплекс'))
    house(plan, x0 + 380, yc - 80, 120, 60, tags('building=sports_hall building:levels=2 height=12'))
    plan.rect(x0 + 300, yc - 220, x0 + 360, yc - 130, tags('leisure=pitch sport=tennis surface=clay'))
    plan.rect(x0 + 380, yc - 220, x0 + 460, yc - 130, tags('leisure=pitch sport=basketball surface=asphalt'))


def town_hospital(plan, i, j, x0, y0, yc):
    plan.rect(x0 + 20, yc + 26, x0 + 480, yc + 232, tags('amenity=hospital', name='Лікарня швидкої допомоги'))
    for k in range(3):
        house(plan, x0 + 100 + k * 150, yc + 90, 110, 22, tags('building=hospital building:levels=6 start_date=1980'), doors=1, door='entrance=main')
    house(plan, x0 + 250, yc + 180, 300, 18, tags('building=hospital building:levels=3'))
    plan.way([(x0 + 40, yc), (x0 + 40, yc + 50), (x0 + 460, yc + 50), (x0 + 460, yc)], tags('highway=service', name='Під’їзд швидкої'))
    plan.node(x0 + 250, yc + 50, tags('emergency=ambulance_station', name='Швидка'))
    plan.rect(x0 + 20, yc - 232, x0 + 240, yc - 26, tags('amenity=clinic', name='Поліклініка'))
    house(plan, x0 + 130, yc - 90, 140, 40, tags('building=yes amenity=clinic building:levels=4'), doors=2, door='entrance=main')
    plan.rect(x0 + 40, yc - 220, x0 + 220, yc - 150, tags('amenity=parking parking=surface'))
    plan.rect(x0 + 270, yc - 232, x0 + 480, yc - 26, tags('amenity=university', name='Університет'))
    house(plan, x0 + 375, yc - 70, 180, 30, tags('building=university building:levels=5 start_date=1965'), doors=3, door='entrance=main')
    house(plan, x0 + 375, yc - 170, 60, 60, tags('building=dormitory building:levels=9'), doors=1)


def town_landmarks(plan, i, j, x0, y0, yc):
    plan.rect(x0 + 140, yc + 30, x0 + 360, yc + 150, tags('place=square highway=pedestrian area=yes surface=paving_stones', name='Площа Немо'))
    plan.node(x0 + 250, yc + 90, tags('historic=monument', name='Монумент картографам'))
    plan.node(x0 + 200, yc + 60, tags('amenity=fountain'))
    house(plan, x0 + 250, yc + 195, 90, 44, tags('building=yes amenity=theatre building:levels=4 height=22', name='Театр'), doors=3, door='entrance=main')
    house(plan, x0 + 70, yc + 100, 30, 46, tags('building=church amenity=place_of_worship religion=christian height=32 roof:shape=dome', name='Церква'), doors=1, door='entrance=main')
    house(plan, x0 + 430, yc + 100, 70, 40, tags('building=yes tourism=museum building:levels=3', name='Музей океану'), doors=1, door='entrance=main')
    plan.node(x0 + 60, yc - 90, tags('man_made=tower tower:type=communication height=120', name='Телевежа'))
    house(plan, x0 + 180, yc - 110, 120, 90, tags('building=stadium leisure=stadium height=20', name='Арена'))
    house(plan, x0 + 380, yc - 80, 140, 50, tags('building=cathedral amenity=place_of_worship religion=christian height=48 roof:shape=dome', name='Собор'), doors=1, door='entrance=main')
    plan.node(x0 + 380, yc - 190, tags('historic=memorial', name='Меморіал'))
    plan.node(x0 + 300, yc - 190, tags('man_made=water_tower height=30'))
    plan.node(x0 + 460, yc - 190, tags('historic=castle', name='Замок'))


def town_market(plan, i, j, x0, y0, yc):
    plan.rect(x0 + 30, yc + 30, x0 + 300, yc + 200, tags('amenity=marketplace surface=asphalt', name='Ринок'))
    for r in range(5):
        for k in range(12):
            house(plan, x0 + 45 + k * 21, yc + 50 + r * 30, 5, 4, tags('building=kiosk building:levels=1'))
            if (r + k) % 4 == 0:
                plan.node(x0 + 45 + k * 21, yc + 50 + r * 30, tags('shop=kiosk', name=('Овочі', 'Хліб', 'Сир', 'Риба')[(r + k) % 4 // 1 % 4]))
    plan.rect(x0 + 330, yc + 30, x0 + 480, yc + 130, tags('amenity=bus_station surface=asphalt', name='Автостанція'))
    house(plan, x0 + 405, yc + 160, 80, 20, tags('building=yes amenity=bus_station building:levels=1'), doors=2, door='entrance=main')
    for k in range(4):
        plan.node(x0 + 345 + k * 40, yc + 60, tags('highway=bus_stop shelter=yes bench=yes', name=f'Платформа {k + 1}'))
    plan.way([(x0 + 405, yc), (x0 + 405, yc + 80)], tags('highway=service service=bus'))
    for k in range(10):
        house(plan, x0 + 40 + k * 44, yc - 40, 6, 5, tags('building=kiosk building:levels=1'))
        plan.node(x0 + 40 + k * 44, yc - 40, tags('shop=kiosk' if k % 2 else 'amenity=fast_food', name=('Кава', 'Шаурма', 'Преса', 'Квіти', 'Лото')[k % 5]))
    plan.node(x0 + 80, yc - 80, tags('amenity=toilets fee=yes'))
    plan.node(x0 + 120, yc - 80, tags('amenity=drinking_water'))
    plan.node(x0 + 160, yc - 80, tags('amenity=atm operator=ПриватБанк'))
    plan.rect(x0 + 200, yc - 220, x0 + 470, yc - 80, tags('amenity=parking parking=surface fee=yes'))
    plan.way([(x0 + 335, yc), (x0 + 335, yc - 150), (x0 + 210, yc - 150)], tags('highway=service service=parking_aisle'))


def town_garages(plan, i, j, x0, y0, yc):
    plan.rect(x0 + 20, yc + 26, x0 + 480, yc + 232, tags('landuse=garages', name='ГБК «Маяк»'))
    for r in range(6):
        y = yc + 50 + r * 32
        house(plan, x0 + 250, y, 420, 6, tags('building=garages building:levels=1'))
        if r % 2 == 0:
            plan.way([(x0 + 30, y + 16), (x0 + 470, y + 16)], tags('highway=service service=alley'))
    plan.way([(x0 + 30, yc), (x0 + 30, yc + 210)], tags('highway=service'))
    plan.node(x0 + 30, yc + 30, tags('barrier=lift_gate'))
    plan.rect(x0 + 20, yc - 232, x0 + 300, yc - 26, tags('landuse=construction', name='Будмайданчик'))
    plan.rect(x0 + 20, yc - 232, x0 + 300, yc - 26, tags('barrier=fence fence_type=corrugated'))
    house(plan, x0 + 160, yc - 130, 80, 40, tags('building=construction building:levels=7'))
    plan.node(x0 + 100, yc - 80, tags('man_made=crane'))
    plan.rect(x0 + 330, yc - 232, x0 + 480, yc - 26, tags('landuse=brownfield'))
    house(plan, x0 + 400, yc - 120, 60, 30, tags('building=ruins abandoned=yes building:levels=2'))


TOWN = (('Старе місто, 1900-ті', 'Old town', town_old), ('Сталінки, 1950-ті', 'Stalin era', town_stalin),
        ('Хрущовки, 1960-ті', 'Khrushchev slabs', town_khrushchev), ('Панельки 9 поверхів', 'Panel, 9 floors', town_panel9),
        ('Панельки 16 поверхів', 'Panel, 16 floors', town_panel16), ('Новобудови 25 поверхів', 'New towers', town_modern),
        ('Офіси й готель', 'Offices and a hotel', town_centre), ('Торгівля', 'Retail', town_retail),
        ('Школа, садок, спорт', 'School and sport', town_school), ('Лікарня, університет', 'Hospital, university', town_hospital),
        ('Визначні споруди', 'Landmarks', town_landmarks), ('Ринок і автостанція', 'Market, bus station', town_market),
        ('Гаражі й будова', 'Garages, construction', town_garages))


def town_tile(plan, i, j, k):
    title, title_en, make = TOWN[k]
    x0, y0, yc = register(plan, i, j, 'town', title, title_en)
    avenue(plan, i, j, tags('highway=tertiary lanes=2 sidewalk=both lit=yes maxspeed=50'), title,
           xs=(16, 30, 40, 130, 250, 335, 370, 405, 460, 490))
    make(plan, i, j, x0, y0, yc)


def town(plan, j):
    for k, i in enumerate(c for c in COLS if c != 0):
        town_tile(plan, i, j, k)


# --- row 6: houses, trade, works ----------------------------------------------------------------
FENCES = ('wood', 'metal', 'chain_link', 'brick', 'concrete', 'stone', 'corrugated', 'railing')


def lot(plan, x, y, w, d, side, n, levels=1):
    """A homestead on the avenue: fence, gate, house, garage, shed and a few fruit trees."""
    ya, yb = (y, y + d) if side > 0 else (y - d, y)
    kind = FENCES[n % len(FENCES)]
    fence = tags('barrier=wall wall=brick') if kind == 'brick' and n % 2 else tags('barrier=fence', fence_type=kind)
    gate = plan.node(x + w * .3, y, tags('barrier=gate'))
    plan.way([(x, y), gate, (x + w, y), (x + w, y + side * d), (x, y + side * d), (x, y)], fence)
    roof = ('gabled', 'hipped', 'gabled', 'half-hipped', 'pyramidal', 'flat')[n % 6]
    house(plan, x + w * .58, y + side * 14, 9 + n % 3, 8 + n % 2,
          tags('building=house', building__levels=levels + (n % 3 == 0), roof__shape=roof, addr__housenumber=n + 1,
               addr__street='Дослідна вулиця'), doors=1, door='entrance=home', angle=0 if side < 0 else 180)
    house(plan, x + w * .3, y + side * 22, 4, 6, tags('building=garage building:levels=1'))
    plan.way([(x + w * .3, y - side * 14), gate, (x + w * .3, y + side * 18)], tags('highway=service service=driveway'))
    if n % 2:
        house(plan, x + w * .75, y + side * (d - 7), 5, 4, tags('building=shed building:levels=1'))
    for k in range(3):
        plan.node(x + 4 + k * (w - 8) / 2, y + side * (d - 5 - 6 * (k % 2)), tags('natural=tree', leaf_type='broadleaved', genus=('Malus', 'Prunus', 'Pyrus')[k]))
    return ya, yb


def works_village(plan, i, j, x0, y0, yc):
    for side in (1, -1):
        for n in range(16):
            lot(plan, x0 + 18 + n * 29, yc + side * 14, 26, 46, side, n + (16 if side < 0 else 0))
        plan.rect(x0 + 18, min(yc + side * 70, yc + side * 230), x0 + 482, max(yc + side * 70, yc + side * 230),
                  tags('landuse=farmland' if side > 0 else 'landuse=orchard'))


def works_cottages(plan, i, j, x0, y0, yc):
    for k in range(20):                                   # a terrace: houses wall to wall
        house(plan, x0 + 30 + k * 7, yc + 34, 7, 10, tags('building=terrace building:levels=2 roof:shape=gabled'), doors=1, door='entrance=home', angle=180)
    for k in range(9):                                    # semi-detached pairs
        for half in (0, 1):
            house(plan, x0 + 220 + k * 30 + half * 9, yc + 34, 9, 10, tags('building=semidetached_house building:levels=2 roof:shape=hipped'))
    plan.way([(x0 + 20, yc + 70), (x0 + 480, yc + 70)], tags('highway=living_street', name='Котеджна'))
    plan.way([(x0 + 20, yc), (x0 + 20, yc + 70)], tags('highway=living_street'))
    plan.way([(x0 + 480, yc), (x0 + 480, yc + 70)], tags('highway=living_street'))
    for k in range(14):
        house(plan, x0 + 40 + k * 32, yc + 100, 12, 10, tags('building=detached building:levels=2', roof__shape=('gabled', 'hipped')[k % 2]))
        house(plan, x0 + 40 + k * 32, yc + 180, 14, 12, tags('building=bungalow building:levels=1 roof:shape=hipped'))
    plan.rect(x0 + 20, yc + 84, x0 + 480, yc + 232, tags('landuse=residential'))
    plan.rect(x0 + 20, yc - 232, x0 + 480, yc - 26, tags('landuse=residential', name='Містечко'))
    for r in range(3):
        y = yc - 60 - r * 70
        plan.way([(x0 + 30, y), (x0 + 470, y)], tags('highway=residential', name=f'Провулок {r + 1}'))
        for k in range(14):
            house(plan, x0 + 45 + k * 31, y + 20, 10, 9, tags('building=house', building__levels=1 + k % 2, roof__shape=('gabled', 'hipped', 'flat')[k % 3]))
            plan.node(x0 + 60 + k * 31, y + 9, tags('highway=street_lamp') if k % 3 == 0 else tags('natural=tree'))
    plan.way([(x0 + 30, yc), (x0 + 30, yc - 200)], tags('highway=residential'))
    plan.way([(x0 + 470, yc), (x0 + 470, yc - 200)], tags('highway=residential'))


def works_dacha(plan, i, j, x0, y0, yc):
    for side in (1, -1):
        lo, hi = (yc + 26, yc + 232) if side > 0 else (yc - 232, yc - 26)
        plan.rect(x0 + 20, lo, x0 + 480, hi, tags('landuse=allotments', name='СТ «Прибій»'))
        for r in range(2):
            y = lo + 50 + r * 100
            plan.way([(x0 + 24, y), (x0 + 476, y)], tags('highway=track tracktype=grade3'))
            for k in range(20):
                house(plan, x0 + 36 + k * 23, y + (16 if k % 2 else -16), 5, 6, tags(('building=hut', 'building=cabin', 'building=shed')[k % 3], building__levels=1))
        plan.way([(x0 + 250, yc), (x0 + 250, yc + side * 200)], tags('highway=track tracktype=grade2'))


def works_farm(plan, i, j, x0, y0, yc):
    plan.rect(x0 + 30, yc + 30, x0 + 300, yc + 200, tags('landuse=farmyard', name='Ферма'))
    for k in range(3):
        house(plan, x0 + 160, yc + 60 + k * 50, 90, 18, tags(('building=barn', 'building=cowshed', 'building=stable')[k], building__levels=1, height=7))
    house(plan, x0 + 60, yc + 60, 12, 10, tags('building=farm building:levels=1 roof:shape=gabled'))
    for k in range(3):
        plan.node(x0 + 240 + k * 14, yc + 180, tags('man_made=silo height=14'))
    plan.way([(x0 + 60, yc), (x0 + 60, yc + 40), (x0 + 280, yc + 40)], tags('highway=track tracktype=grade2'))
    house(plan, x0 + 400, yc + 120, 120, 160, tags('building=greenhouse building:levels=1 height=5'))
    plan.rect(x0 + 20, yc - 232, x0 + 250, yc - 26, tags('landuse=farmland crop=wheat'))
    plan.rect(x0 + 262, yc - 232, x0 + 480, yc - 26, tags('landuse=farmland crop=sunflower'))
    plan.way([(x0 + 256, yc), (x0 + 256, yc - 232)], tags('highway=track tracktype=grade4'))
    plan.way([(x0 + 20, yc - 24), (x0 + 480, yc - 24)], tags('natural=tree_row'))


def works_plant(plan, i, j, x0, y0, yc):
    site = (x0 + 20, yc + 26, x0 + 480, yc + 232)
    plan.rect(*site, tags('landuse=industrial', name='Завод «Полюс»'))
    plan.rect(*site, tags('barrier=wall wall=concrete'))
    house(plan, x0 + 150, yc + 90, 220, 70, tags('building=industrial height=16 building:levels=2'))
    house(plan, x0 + 380, yc + 90, 140, 50, tags('building=industrial height=12 building:levels=2 building:material=metal'))
    house(plan, x0 + 120, yc + 190, 160, 40, tags('building=industrial height=10'))
    plan.node(x0 + 300, yc + 190, tags('man_made=chimney height=90'))
    for k in range(4):
        cx, cy = x0 + 360 + k * 30, yc + 190
        plan.area(plan.arc(cx, cy, 11, 0, 360, step=5)[:-1], tags('man_made=storage_tank building=storage_tank height=12'))
    plan.way([(x0 + 40, yc), (x0 + 40, yc + 44), (x0 + 460, yc + 44)], tags('highway=service'))
    plan.node(x0 + 40, yc + 26, tags('barrier=gate'))
    house(plan, x0 + 60, yc + 34, 8, 6, tags('building=service building:levels=1', name='Прохідна'))
    site = (x0 + 20, yc - 232, x0 + 480, yc - 26)
    plan.rect(*site, tags('landuse=industrial', name='ТЕЦ'))
    plan.rect(*site, tags('barrier=fence fence_type=concrete'))
    house(plan, x0 + 150, yc - 120, 200, 90, tags('building=industrial height=30 building:levels=4'))
    plan.node(x0 + 300, yc - 80, tags('man_made=chimney height=150'))
    plan.node(x0 + 340, yc - 80, tags('man_made=chimney height=150'))
    for k in range(2):
        plan.area(plan.arc(x0 + 390 + k * 50, yc - 170, 22, 0, 360, step=6)[:-1], tags('man_made=cooling_tower building=yes height=60'))
    plan.rect(x0 + 300, yc - 220, x0 + 360, yc - 180, tags('power=substation'))


def works_warehouses(plan, i, j, x0, y0, yc):
    for side in (1, -1):
        lo, hi = (yc + 26, yc + 232) if side > 0 else (yc - 232, yc - 26)
        plan.rect(x0 + 20, lo, x0 + 480, hi, tags('landuse=industrial' if side > 0 else 'landuse=commercial', name='Логістика'))
        plan.rect(x0 + 20, lo, x0 + 480, hi, tags('barrier=fence fence_type=chain_link'))
        for k in range(3):
            house(plan, x0 + 95 + k * 155, yc + side * 150, 130, 100, tags('building=warehouse height=11 building:levels=1', building__material=('metal', 'concrete', 'metal')[k]))
        plan.way([(x0 + 250, yc), (x0 + 250, yc + side * 70), (x0 + 40, yc + side * 70)], tags('highway=service'))
        plan.way([(x0 + 250, yc + side * 70), (x0 + 460, yc + side * 70)], tags('highway=service'))
        plan.node(x0 + 250, yc + side * 26, tags('barrier=lift_gate'))
        plan.rect(x0 + 40, min(yc + side * 34, yc + side * 60), x0 + 220, max(yc + side * 34, yc + side * 60), tags('amenity=parking parking=surface hgv=yes'))


def works_utility(plan, i, j, x0, y0, yc):
    plan.rect(x0 + 30, yc + 40, x0 + 200, yc + 160, tags('power=substation', name='Підстанція'))
    plan.rect(x0 + 30, yc + 40, x0 + 200, yc + 160, tags('barrier=fence fence_type=chain_link'))
    house(plan, x0 + 60, yc + 70, 20, 12, tags('building=service power=substation building:levels=1'))
    line = [(x0 + 200, yc + 100), (x0 + 480, yc + 100)]
    plan.way(along(line[0], line[1], 40), tags('power=minor_line'))
    for p in along(line[0], line[1], 40):
        plan.node(p[0], p[1], tags('power=pole'))
    plan.node(x0 + 300, yc + 190, tags('man_made=water_tower height=28'))
    plan.node(x0 + 400, yc + 190, tags('man_made=mast tower:type=communication height=45'))
    plan.rect(x0 + 30, yc - 220, x0 + 230, yc - 40, tags('man_made=wastewater_plant landuse=industrial', name='Очисні'))
    for k in range(3):
        plan.area(plan.arc(x0 + 70 + k * 60, yc - 130, 22, 0, 360, step=6)[:-1], tags('natural=water water=basin'))
    plan.rect(x0 + 270, yc - 220, x0 + 470, yc - 40, tags('landuse=depot', name='Автобусний парк'))
    house(plan, x0 + 370, yc - 170, 160, 50, tags('building=garages building:levels=1 height=7'))
    plan.way([(x0 + 370, yc), (x0 + 370, yc - 110)], tags('highway=service'))


def works_fuel(plan, i, j, x0, y0, yc):
    for k, (brand, side) in enumerate((('OKKO', 1), ('WOG', -1))):
        cx = x0 + 120
        plan.rect(cx - 70, min(yc + side * 20, yc + side * 90), cx + 70, max(yc + side * 20, yc + side * 90),
                  tags('amenity=fuel', name=brand, brand=brand))
        house(plan, cx, yc + side * 45, 40, 16, tags('building=roof layer=1 height=6'))
        house(plan, cx, yc + side * 75, 30, 14, tags('building=retail shop=convenience building:levels=1', name=brand))
        plan.way([(cx - 90, yc), (cx - 60, yc + side * 45), (cx + 60, yc + side * 45), (cx + 90, yc)], tags('highway=service oneway=yes'))
    house(plan, x0 + 300, yc + 60, 30, 14, tags('building=yes amenity=car_wash building:levels=1', name='Мийка'))
    plan.way([(x0 + 300, yc), (x0 + 300, yc + 50)], tags('highway=service'))
    plan.rect(x0 + 350, yc + 26, x0 + 480, yc + 200, tags('highway=rest_area', name='Майданчик відпочинку'))
    plan.rect(x0 + 360, yc + 40, x0 + 470, yc + 100, tags('amenity=parking parking=surface hgv=yes'))
    plan.node(x0 + 380, yc + 130, tags('amenity=toilets'))
    plan.node(x0 + 410, yc + 130, tags('leisure=picnic_table'))
    plan.node(x0 + 440, yc + 130, tags('amenity=bbq'))
    plan.way([(x0 + 415, yc), (x0 + 415, yc + 70)], tags('highway=service'))
    house(plan, x0 + 350, yc - 90, 120, 16, tags('building=hotel tourism=motel building:levels=2', name='Мотель «Тихий»'), doors=6, door='entrance=yes')
    plan.rect(x0 + 290, yc - 70, x0 + 410, yc - 30, tags('amenity=parking parking=surface'))
    plan.way([(x0 + 350, yc), (x0 + 350, yc - 50)], tags('highway=service'))
    plan.node(x0 + 450, yc - 40, tags('amenity=charging_station', name='ТОКА', brand='ТОКА'))
    house(plan, x0 + 300, yc - 180, 60, 30, tags('building=retail amenity=restaurant building:levels=1', name='Кафе «Дальнобій»'), doors=1, door='entrance=main')


def works_cars(plan, i, j, x0, y0, yc):
    specs = (('shop=car', 'Автосалон', 60, 34), ('shop=car_parts', 'Автозапчастини', 40, 20), ('shop=car_repair', 'СТО', 50, 24),
             ('shop=tyres', 'Шини', 36, 18), ('shop=motorcycle', 'Мото', 30, 18))
    for side in (1, -1):
        x = x0 + 30
        for k, (spec, name, w, d) in enumerate(specs):
            house(plan, x + w / 2, yc + side * (36 + d / 2), w, d, tags('building=retail building:levels=1 height=7', name=name) | tags(spec),
                  doors=1, door='entrance=shop', angle=0 if side > 0 else 180)
            plan.rect(x, min(yc + side * 14, yc + side * 32), x + w, max(yc + side * 14, yc + side * 32), tags('amenity=parking parking=surface'))
            x += w + 28
        plan.rect(x0 + 30, min(yc + side * 100, yc + side * 220), x0 + 470, max(yc + side * 100, yc + side * 220),
                  tags('amenity=parking parking=surface', name='Майданчик автосалону') if side > 0 else tags('landuse=commercial'))


def works_strip(plan, i, j, x0, y0, yc):
    """A strip of small shops with the networks the generator knows by name."""
    north = (('shop=supermarket', 'АТБ'), ('shop=supermarket', 'Сільпо'), ('shop=convenience', 'Фора'), ('amenity=pharmacy', 'Аптека 911'),
             ('amenity=post_office', 'Нова Пошта'), ('amenity=fast_food', "McDonald's"), ('amenity=bank', 'ПриватБанк'),
             ('amenity=cafe', 'Aroma Kava'), ('amenity=fast_food', 'KFC'), ('shop=bakery', 'Львівські круасани'))
    south = (('shop=convenience', 'Продукти'), ('shop=alcohol', 'Вина світу'), ('shop=hardware', 'Господар'), ('shop=clothes', 'Одяг'),
             ('shop=mobile_phone', 'Мобілочка'), ('shop=hairdresser', 'Перукарня'), ('amenity=restaurant', 'Пузата Хата'),
             ('shop=florist', 'Квіти'), ('shop=pet', 'Зоотовари'), ('amenity=pharmacy', 'Аптека Доброго Дня'))
    for side, row in ((1, north), (-1, south)):
        for k, (spec, name) in enumerate(row):
            cx = x0 + 44 + k * 46
            house(plan, cx, yc + side * 26, 40, 14, tags('building=retail building:levels=1'), doors=0)
            shop(plan, cx, yc + side * 22, spec, name, side=-side, depth=3., brand=name if side > 0 else None)
        plan.rect(x0 + 24, min(yc + side * 44, yc + side * 90), x0 + 476, max(yc + side * 44, yc + side * 90), tags('amenity=parking parking=surface'))
        plan.way([(x0 + 16, yc), (x0 + 16, yc + side * 66), (x0 + 484, yc + side * 66), (x0 + 484, yc)], tags('highway=service service=parking_aisle'))


def works_sport(plan, i, j, x0, y0, yc):
    plan.rect(x0 + 30, yc + 30, x0 + 330, yc + 220, tags('leisure=stadium', name='Стадіон «Немо»'))
    plan.rect(x0 + 50, yc + 50, x0 + 310, yc + 200, tags('leisure=track sport=running surface=tartan'))
    plan.rect(x0 + 90, yc + 80, x0 + 270, yc + 170, tags('leisure=pitch sport=soccer surface=grass'))
    house(plan, x0 + 180, yc + 212, 200, 12, tags('building=grandstand height=10'))
    for k, (sport, surface) in enumerate((('tennis', 'clay'), ('tennis', 'hard'), ('basketball', 'asphalt'), ('volleyball', 'sand'))):
        plan.rect(x0 + 350, yc + 30 + k * 48, x0 + 470, yc + 70 + k * 48, tags('leisure=pitch', sport=sport, surface=surface))
    plan.rect(x0 + 30, yc - 220, x0 + 230, yc - 40, tags('leisure=park', name='Парк'))
    plan.rect(x0 + 60, yc - 180, x0 + 110, yc - 130, tags('leisure=playground'))
    plan.area(plan.arc(x0 + 170, yc - 110, 26, 0, 360, step=6)[:-1], tags('natural=water water=pond'))
    plan.way([(x0 + 40, yc - 50), (x0 + 220, yc - 210)], tags('highway=footway'))
    plan.way([(x0 + 40, yc - 210), (x0 + 220, yc - 50)], tags('highway=footway'))
    plan.rect(x0 + 260, yc - 220, x0 + 470, yc - 40, tags('leisure=golf_course', name='Гольф'))
    plan.rect(x0 + 300, yc - 180, x0 + 360, yc - 120, tags('golf=green natural=grassland'))
    plan.rect(x0 + 380, yc - 160, x0 + 420, yc - 130, tags('golf=bunker natural=sand'))


def works_cemetery(plan, i, j, x0, y0, yc):
    site = (x0 + 30, yc + 30, x0 + 470, yc + 225)
    plan.rect(*site, tags('landuse=cemetery', name='Цвинтар'))
    plan.rect(*site, tags('barrier=wall wall=brick'))
    house(plan, x0 + 250, yc + 70, 14, 20, tags('building=chapel amenity=place_of_worship height=14'), doors=1, door='entrance=main')
    plan.way([(x0 + 250, yc), (x0 + 250, yc + 210)], tags('highway=footway'))
    plan.way([(x0 + 50, yc + 130), (x0 + 450, yc + 130)], tags('highway=footway'))
    plan.node(x0 + 250, yc + 30, tags('barrier=gate'))
    plan.rect(x0 + 30, yc - 225, x0 + 470, yc - 30, tags('landuse=recreation_ground', name='Поле для свят'))
    plan.node(x0 + 100, yc - 100, tags('tourism=picnic_site'))
    plan.node(x0 + 200, yc - 100, tags('amenity=shelter shelter_type=gazebo'))
    plan.node(x0 + 300, yc - 100, tags('tourism=viewpoint'))
    plan.node(x0 + 400, yc - 100, tags('tourism=camp_site'))


def works_parking(plan, i, j, x0, y0, yc):
    plan.rect(x0 + 30, yc + 30, x0 + 470, yc + 220, tags('amenity=parking parking=surface', name='Перехоплювальна стоянка'))
    for r in range(4):
        plan.way([(x0 + 40, yc + 55 + r * 45), (x0 + 460, yc + 55 + r * 45)], tags('highway=service service=parking_aisle'))
    plan.way([(x0 + 40, yc), (x0 + 40, yc + 190)], tags('highway=service'))
    plan.way([(x0 + 460, yc), (x0 + 460, yc + 190)], tags('highway=service'))
    house(plan, x0 + 130, yc - 120, 180, 100, tags('building=parking parking=multi-storey building:levels=5', name='Багаторівневий паркінг'))
    plan.way([(x0 + 130, yc), (x0 + 130, yc - 70)], tags('highway=service'))
    plan.rect(x0 + 270, yc - 220, x0 + 470, yc - 40, tags('amenity=parking parking=surface surface=gravel', name='Гравійна стоянка'))
    plan.way([(x0 + 370, yc), (x0 + 370, yc - 130)], tags('highway=service surface=gravel'))


WORKS = (('Село, садиби', 'Village homesteads', works_village, 'highway=residential parking:both=no'),
         ('Котеджі, таунхауси', 'Cottages, terraces', works_cottages, 'highway=residential'),
         ('Дачі', 'Allotments', works_dacha, 'highway=unclassified surface=compacted'),
         ('Ферма й поля', 'Farm and fields', works_farm, 'highway=unclassified'),
         ('Завод і ТЕЦ', 'Plant and power station', works_plant, 'highway=tertiary'),
         ('Склади', 'Warehouses', works_warehouses, 'highway=tertiary'),
         ('Інженерні споруди', 'Utilities', works_utility, 'highway=unclassified'),
         ('АЗС, мотель, відпочинок', 'Fuel, motel, rest area', works_fuel, 'highway=primary lanes=2'),
         ('Автосалони й СТО', 'Car trade', works_cars, 'highway=secondary lanes=2'),
         ('Крамниці вздовж дороги', 'Roadside shops', works_strip, 'highway=secondary lanes=2 sidewalk=both'),
         ('Стадіон, корти, парк', 'Stadium, courts, park', works_sport, 'highway=tertiary sidewalk=both'),
         ('Цвинтар, місця відпочинку', 'Cemetery, leisure', works_cemetery, 'highway=unclassified'),
         ('Стоянки', 'Car parks', works_parking, 'highway=secondary lanes=2 parking:both=parallel'))


def works_tile(plan, i, j, k):
    title, title_en, make, spec = WORKS[k]
    x0, y0, yc = register(plan, i, j, 'works', title, title_en, spec)
    avenue(plan, i, j, tags(spec), title, xs=(16, 30, 40, 60, 130, 250, 256, 300, 335, 350, 370, 415, 460, 484))
    make(plan, i, j, x0, y0, yc)


def works(plan, j):
    for k, i in enumerate(c for c in COLS if c != 0):
        works_tile(plan, i, j, k)


# --- row 5: street furniture and points of interest ----------------------------------------------
def _both(plan, x0, yc, step, off, make, inset=20.):
    for side in (1, -1):
        for n, p in enumerate(along((x0, yc + side * off), (x0 + TILE, yc + side * off), step, inset)):
            make(p[0], p[1], side, n)


def street_lamps(plan, i, j, x0, y0, yc, ave):
    _both(plan, x0, yc, 30, 7.5, lambda x, y, side, n: plan.node(x + (15 if side < 0 else 0), y, tags('highway=street_lamp lamp_mount=bent_mast')))


def street_trees(plan, i, j, x0, y0, yc, ave):
    genus = ('Tilia', 'Acer', 'Aesculus', 'Populus', 'Betula', 'Quercus', 'Fraxinus', 'Picea', 'Pinus', 'Salix')
    for n, p in enumerate(along((x0, yc + 8), (x0 + TILE, yc + 8), 12, 14)):
        g = genus[n // 4 % len(genus)]
        plan.node(p[0], p[1], tags('natural=tree', genus=g, leaf_type='needleleaved' if g in ('Picea', 'Pinus') else 'broadleaved'))
    plan.way([(x0 + 14, yc - 8), (x0 + 486, yc - 8)], tags('natural=tree_row'))
    plan.way([(x0 + 14, yc - 40), (x0 + 240, yc - 40)], tags('natural=tree_row leaf_type=needleleaved'))
    plan.way([(x0 + 260, yc - 40), (x0 + 486, yc - 40)], tags('barrier=hedge'))
    for k in range(8):
        plan.node(x0 + 40 + k * 60, yc + 90 + (k % 3) * 40, tags('natural=tree denotation=natural_monument', genus=genus[k]))


def street_benches(plan, i, j, x0, y0, yc, ave):
    kinds = ('amenity=bench', 'amenity=waste_basket', 'amenity=bench backrest=no', 'amenity=recycling recycling_type=container',
             'amenity=bicycle_parking', 'amenity=waste_disposal', 'man_made=planter', 'amenity=vending_machine vending=parking_tickets',
             'barrier=bollard', 'amenity=post_box', 'amenity=telephone', 'man_made=street_cabinet', 'emergency=fire_hydrant fire_hydrant:type=pillar')
    _both(plan, x0, yc, 18, 8.5, lambda x, y, side, n: plan.node(x, y, tags(kinds[n % len(kinds)], direction=0 if side < 0 else 180)))


def street_stops(plan, i, j, x0, y0, yc, ave):
    for k, (x, shelter) in enumerate(((80, 'yes'), (250, 'no'), (420, 'yes'))):
        for side in (1, -1):
            plan.node(x0 + x, yc + side * 7.5, tags('highway=bus_stop public_transport=platform bus=yes', shelter=shelter, bench=shelter,
                                                   name=f'Зупинка {code(i, j)}-{k + 1}'))
        plan.way([(x0 + x - 12, yc + 9), (x0 + x + 12, yc + 9)], tags('public_transport=platform highway=platform'))
    plan.node(x0 + 160, yc + 7.5, tags('highway=bus_stop public_transport=platform trolleybus=yes shelter=yes', name='Тролейбусна'))
    plan.node(x0 + 340, yc - 7.5, tags('amenity=taxi', name='Таксі'))


def street_crossings(plan, i, j, x0, y0, yc, ave):
    kinds = ('highway=crossing crossing=marked crossing:markings=zebra', 'highway=crossing crossing=uncontrolled',
             'highway=crossing crossing=traffic_signals crossing:signals=yes', 'highway=crossing crossing=marked crossing:island=yes',
             'highway=crossing crossing=unmarked', 'highway=crossing crossing=marked traffic_calming=table')
    for k, spec in enumerate(kinds):
        x = x0 + 50 + k * 80
        _on(plan, ave, x, yc, tags(spec))
        plan.way([(x, yc + 40), (x, yc), (x, yc - 40)], tags('highway=footway footway=crossing'))
    plan.way([(x0 + 20, yc + 40), (x0 + 480, yc + 40)], tags('highway=footway'))
    plan.way([(x0 + 20, yc - 40), (x0 + 480, yc - 40)], tags('highway=footway'))
    for x in (130, 290):
        _on(plan, ave, x0 + x + 40, yc, tags('traffic_calming=bump'))


def street_signs(plan, i, j, x0, y0, yc, ave):
    signs = ('maxspeed', 'maxspeed', 'maxspeed', 'maxspeed', 'stop', 'give_way', 'priority_road', 'no_entry', 'overtaking',
             'roundabout', 'hump', 'city_limit', 'UA:1.39', 'UA:3.29[70]', 'UA:5.45')
    limits = (30, 50, 70, 90)
    for k, sign in enumerate(signs):
        x = x0 + 30 + k * 31
        tag = tags(traffic_sign=sign, direction='forward' if k % 2 == 0 else 'backward')
        if sign == 'maxspeed':
            tag['maxspeed'] = str(limits[k])
        if sign in ('city_limit', 'UA:5.45'):
            tag['name'] = 'Немоград'
        _on(plan, ave, x, yc, tag)


def street_control(plan, i, j, x0, y0, yc, ave):
    _on(plan, ave, x0 + 100, yc, tags('highway=speed_camera maxspeed=50'))
    plan.way([(x0 + 200, yc - 12), (x0 + 200, yc + 12)], tags('man_made=gantry'))
    plan.way([(x0 + 360, yc - 12), (x0 + 360, yc + 12)], tags('man_made=gantry'))
    for side in (1, -1):
        plan.way([(x0 + 230, yc + side * 6.5), (x0 + 480, yc + side * 6.5)], tags('barrier=guard_rail'))
    plan.ways[ave][1].update(tags('destination=Точка_Немо ref=Н-01 maxspeed=90 overtaking=no'))
    _on(plan, ave, x0 + 420, yc, tags('highway=traffic_signals traffic_signals:direction=forward'))
    plan.node(x0 + 60, yc + 9, tags('highway=milestone distance=1'))
    plan.node(x0 + 300, yc + 9, tags('highway=emergency_access_point'))


def street_fences(plan, i, j, x0, y0, yc, ave):
    kinds = ('barrier=fence fence_type=wood', 'barrier=fence fence_type=chain_link', 'barrier=fence fence_type=metal',
             'barrier=fence fence_type=concrete', 'barrier=fence fence_type=railing', 'barrier=fence fence_type=corrugated',
             'barrier=fence fence_type=split_rail', 'barrier=fence', 'barrier=wall wall=brick', 'barrier=wall wall=stone',
             'barrier=wall wall=concrete', 'barrier=wall', 'barrier=hedge', 'barrier=guard_rail', 'barrier=retaining_wall',
             'barrier=city_wall', 'barrier=fence fence_type=stone', 'barrier=fence fence_type=brick')
    for k, spec in enumerate(kinds):
        side = 1 if k % 2 == 0 else -1
        x = x0 + 20 + (k // 2) * 52
        plan.way([(x, yc + side * 14), (x + 44, yc + side * 14), (x + 44, yc + side * 50)], tags(spec, height=1.2 + (k % 4) * .4))


def street_gates(plan, i, j, x0, y0, yc, ave):
    kinds = ('gate', 'lift_gate', 'swing_gate', 'sliding_gate', 'wicket_gate', 'bollard', 'chain', 'cattle_grid', 'toll_booth', 'height_restrictor')
    for k, kind in enumerate(kinds):
        side = 1 if k % 2 == 0 else -1
        x = x0 + 40 + (k // 2) * 95
        plan.rect(x - 30, min(yc + side * 40, yc + side * 110), x + 30, max(yc + side * 40, yc + side * 110), tags('barrier=fence fence_type=metal'))
        gate = plan.node(x, yc + side * 40, tags(barrier=kind))
        _on(plan, ave, x, yc, None)
        plan.way([(x, yc), gate, (x, yc + side * 90)], tags('highway=service service=driveway'))


def street_power(plan, i, j, x0, y0, yc, ave):
    for side in (1, -1):
        pts = along((x0 + 10, yc + side * 9), (x0 + 490, yc + side * 9), 40)
        plan.way(pts, tags('power=minor_line'))
        for p in pts:
            plan.node(p[0], p[1], tags('power=pole'))
    kinds = ('man_made=street_cabinet', 'emergency=fire_hydrant fire_hydrant:type=underground', 'man_made=manhole', 'power=transformer',
             'man_made=surveillance', 'emergency=phone', 'man_made=monitoring_station', 'man_made=flagpole')
    for k, spec in enumerate(kinds):
        plan.node(x0 + 40 + k * 55, yc + 12, tags(spec))
    plan.way([(x0 + 250, yc + 9), (x0 + 250, yc + 200)], tags('power=minor_line'))


def street_pins(plan, i, j, x0, y0, yc, ave):
    pins = ('amenity=atm', 'amenity=payment_terminal', 'amenity=bureau_de_change', 'amenity=vending_machine vending=water',
            'amenity=vending_machine vending=coffee', 'amenity=toilets', 'amenity=drinking_water', 'amenity=bbq', 'shop=kiosk',
            'amenity=parking', 'tourism=hotel', 'tourism=hostel', 'tourism=motel', 'amenity=fuel', 'amenity=charging_station',
            'amenity=pharmacy', 'amenity=hospital', 'amenity=post_box', 'tourism=viewpoint', 'tourism=picnic_site',
            'tourism=information information=board', 'amenity=fountain', 'shop=car', 'shop=car_parts', 'highway=rest_area',
            'amenity=car_wash', 'amenity=parcel_locker', 'amenity=bicycle_rental', 'tourism=camp_site', 'amenity=shelter')
    for k, spec in enumerate(pins):
        side = 1 if k % 2 == 0 else -1
        plan.node(x0 + 22 + (k // 2) * 31, yc + side * 12, tags(spec, name=spec.split('=', 1)[1].split()[0]))


def street_brands(plan, i, j, x0, y0, yc, ave):
    north = (('amenity=fuel', 'OKKO'), ('amenity=fuel', 'WOG'), ('amenity=fuel', 'SOCAR'), ('amenity=fuel', 'UPG'), ('amenity=fuel', 'БРСМ-Нафта'),
             ('amenity=fuel', 'Shell'), ('amenity=fuel', 'Укрнафта'), ('amenity=fuel', 'KLO'))
    south = (('shop=supermarket', 'АТБ'), ('shop=supermarket', 'Сільпо'), ('shop=supermarket', 'Фора'), ('shop=supermarket', 'NOVUS'),
             ('amenity=fast_food', "McDonald's"), ('amenity=post_office', 'Нова Пошта №1'), ('amenity=fast_food', 'KFC'), ('amenity=cafe', 'Aroma Kava'))
    for side, row in ((1, north), (-1, south)):
        for k, (spec, name) in enumerate(row):
            cx = x0 + 40 + k * 60
            house(plan, cx, yc + side * 34, 36, 16, tags('building=retail building:levels=1'))
            shop(plan, cx, yc + side * 30, spec, name, side=-side, depth=4., brand=name)


def street_ads(plan, i, j, x0, y0, yc, ave):
    kinds = ('advertising=billboard', 'advertising=column', 'advertising=poster_box', 'advertising=totem', 'man_made=flagpole',
             'advertising=screen', 'advertising=board', 'tourism=artwork artwork_type=sculpture', 'amenity=clock', 'tourism=information information=guidepost')
    _both(plan, x0, yc, 46, 11, lambda x, y, side, n: plan.node(x, y, tags(kinds[(n + (5 if side < 0 else 0)) % len(kinds)], direction=90)))


STREET = (('Ліхтарі', 'Street lamps', street_lamps), ('Дерева й живоплоти', 'Trees and hedges', street_trees),
          ('Лавки, урни, дрібниці', 'Benches, bins, small things', street_benches), ('Зупинки', 'Stops', street_stops),
          ('Переходи', 'Crossings', street_crossings), ('Дорожні знаки', 'Traffic signs', street_signs),
          ('Камери, рами, відбійники', 'Cameras, gantries, guard rails', street_control), ('Паркани й мури', 'Fences and walls', street_fences),
          ('Ворота й шлагбауми', 'Gates and barriers', street_gates), ('Стовпи й люки', 'Poles and covers', street_power),
          ('Точки інтересу', 'Points of interest', street_pins), ('Мережі й бренди', 'Networks and brands', street_brands),
          ('Реклама', 'Advertising', street_ads))


def street_tile(plan, i, j, k):
    title, title_en, make = STREET[k]
    x0, y0, yc = register(plan, i, j, 'street', title, title_en)
    ave = avenue(plan, i, j, tags('highway=secondary lanes=2 sidewalk=both lit=yes'), title)
    make(plan, i, j, x0, y0, yc, ave)


def street(plan, j):
    for k, i in enumerate(c for c in COLS if c != 0):
        street_tile(plan, i, j, k)


# --- row 4: ground covers -----------------------------------------------------------------------
COVERS = (
    '', 'landuse=grass', 'landuse=meadow', 'natural=grassland',
    'natural=heath', 'natural=scrub', 'natural=fell', 'natural=bare_ground',
    'landuse=farmland', 'landuse=farmland crop=wheat', 'landuse=farmland crop=sunflower', 'landuse=farmland crop=maize',
    'landuse=farmyard', 'landuse=orchard', 'landuse=vineyard', 'landuse=allotments',
    'natural=wetland', 'natural=wetland wetland=marsh', 'natural=wetland wetland=swamp', 'natural=wetland wetland=reedbed',
    'natural=sand', 'natural=beach', 'natural=shingle', 'natural=scree',
    'natural=bare_rock', 'natural=glacier', 'natural=water', 'natural=mud',
    'landuse=residential', 'landuse=industrial', 'landuse=commercial', 'landuse=retail',
    'landuse=construction', 'landuse=railway', 'landuse=garages', 'landuse=depot',
    'amenity=parking', 'place=square', 'highway=pedestrian area=yes', 'landuse=brownfield',
    'leisure=park', 'leisure=garden', 'landuse=cemetery', 'landuse=village_green',
    'landuse=recreation_ground', 'leisure=pitch', 'leisure=pitch surface=asphalt', 'leisure=playground',
    'amenity=school', 'landuse=forest', 'natural=wood', 'landuse=quarry',
)


def covers_tile(plan, i, j, k):
    four = COVERS[k * 4:k * 4 + 4]
    title = ' · '.join((c or 'без тегів').split('=', 1)[-1].replace(' ', ' ') for c in four)
    x0, y0, yc = register(plan, i, j, 'covers', title, tag_text=' | '.join(c or '-' for c in four))
    avenue(plan, i, j, tags('highway=unclassified'), title)
    rects = plots(i, j, 'n', 2) + plots(i, j, 's', 2)
    for spec, rect in zip(four, rects):
        if spec:
            plan.rect(*rect, tags(spec, name=spec))
        plan.way([(rect[0], rect[1] - 3), (rect[2], rect[1] - 3)], tags('highway=path', name=spec or 'без тегів'))


def covers(plan, j):
    for k, i in enumerate(c for c in COLS if c != 0):
        covers_tile(plan, i, j, k)


# --- row 3: vegetation --------------------------------------------------------------------------
PLANTS = (
    ('landuse=forest leaf_type=broadleaved', 'landuse=forest leaf_type=needleleaved'),
    ('landuse=forest leaf_type=mixed', 'natural=wood leaf_type=broadleaved'),
    ('natural=wood leaf_type=needleleaved', 'landuse=forest wood=deciduous'),
    ('landuse=forest', 'natural=wood'),
    ('leisure=park', 'leisure=garden'),
    ('landuse=orchard trees=apple_trees', 'landuse=orchard trees=cherry_trees'),
    ('landuse=vineyard', 'landuse=plant_nursery'),
    ('natural=scrub', 'natural=heath'),
    ('natural=wetland wetland=swamp', 'natural=wetland wetland=reedbed'),
    ('landuse=meadow', 'natural=grassland'),
    ('landuse=residential', 'landuse=village_green'),
    ('landuse=forest leaf_type=broadleaved', 'landuse=forest leaf_type=needleleaved'),
    ('landuse=logging', 'natural=tree_group'),
)


def plants_tile(plan, i, j, k):
    north, south = PLANTS[k]
    title = f"{north.split('=', 1)[1]} · {south.split('=', 1)[1]}"
    x0, y0, yc = register(plan, i, j, 'plants', title, tag_text=f'{north} | {south}')
    # the last but one: the road itself runs through the wood, no clearing beside it
    through = k == 11
    avenue(plan, i, j, tags('highway=tertiary'), title)
    a, = plots(i, j, 'n', 1, setback=3 if through else 24)
    b, = plots(i, j, 's', 1, setback=3 if through else 24)
    plan.rect(*a, tags(north, name=north))
    plan.rect(*b, tags(south, name=south))
    if 'park' in north or 'garden' in north or 'village' in south:
        for rect in (a, b):
            plan.way([(rect[0] + 10, rect[1] + 10), (rect[2] - 10, rect[3] - 10)], tags('highway=footway'))
            plan.way([(rect[0] + 10, rect[3] - 10), (rect[2] - 10, rect[1] + 10)], tags('highway=footway'))
            for n in range(8):
                plan.node(rect[0] + 30 + n * 55, (rect[1] + rect[3]) / 2 + 30, tags('amenity=bench' if n % 2 else 'natural=tree'))
    else:
        plan.way([(a[0] + 20, a[1] + 60), (a[2] - 20, a[3] - 40)], tags('highway=path'))
        plan.way([(b[0] + 20, b[3] - 60), (b[2] - 20, b[1] + 40)], tags('highway=track tracktype=grade4'))


def plants(plan, j):
    for k, i in enumerate(c for c in COLS if c != 0):
        plants_tile(plan, i, j, k)


# --- row 2: water and rails ---------------------------------------------------------------------
def _bed(plan, line, half, depth):
    """Sink the ground along a line of points: a river's valley in the heights."""
    import numpy as np
    import shapely
    path = shapely.LineString(line)

    def carve(x, y, h):
        near = np.abs(x - (line[0][0] + line[-1][0]) / 2) < 400
        d = np.full(x.shape, 1e9)
        if near.any():
            d[near] = shapely.distance(shapely.points(x[near], y[near]), path)
        return h - depth * (1 - np.clip(d / half, 0, 1)) ** 2 * (d < half)
    plan.carve.append(carve)


def bridged(plan, i, j, spec, label, a, b, extra=''):
    """The avenue with a bridge between a and b metres from the tile's west edge."""
    x0, y0 = origin(i, j)
    yc = y0 + TILE / 2
    name = f'{code(i, j)} {label}'
    plan.way([(x0, yc), (x0 + a, yc)], tags(spec, name=name))
    plan.way([(x0 + a, yc), (x0 + b, yc)], tags(spec + ' bridge=yes layer=1 ' + extra, name=name))
    plan.way([(x0 + b, yc), (x0 + TILE, yc)], tags(spec, name=name))


def water_river(plan, i, j, x0, y0, yc):
    bridged(plan, i, j, 'highway=tertiary', 'міст через річку', 205, 295)
    xr = x0 + 250
    line = [(xr - 20, y0 + 20), (xr + 15, y0 + 140), (xr, yc), (xr - 15, y0 + 360), (xr + 20, y0 + 480)]
    plan.way(line, tags('waterway=river', name='Немо'))
    left = [(x - 18, y) for x, y in line]
    right = [(x + 18, y) for x, y in line]
    plan.area(left + right[::-1], tags('natural=water water=river'))
    _bed(plan, line, 70., 5.)
    plan.way([(x0 + 60, yc + 60), (xr - 40, yc + 60)], tags('highway=path'))


def water_stream(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, tags('highway=tertiary'), 'струмок у трубі')
    xr = x0 + 250
    plan.way([(xr - 60, y0 + 480), (xr, yc + 30)], tags('waterway=stream', name='Струмок'))
    plan.way([(xr, yc + 30), (xr, yc - 30)], tags('waterway=stream tunnel=culvert layer=-1'))
    plan.way([(xr, yc - 30), (xr + 60, y0 + 20)], tags('waterway=stream'))
    plan.way([(x0 + 100, y0 + 60), (x0 + 400, y0 + 60)], tags('waterway=ditch'))
    plan.way([(x0 + 100, y0 + 440), (x0 + 400, y0 + 440)], tags('waterway=drain'))
    _bed(plan, [(xr - 60, y0 + 480), (xr, yc + 30), (xr, yc - 30), (xr + 60, y0 + 20)], 45., 2.)


def water_lake(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, tags('highway=tertiary'), 'озеро й ставок')
    outer = plan.arc(x0 + 250, yc + 125, 95, 0, 360, step=10)[:-1]
    inner = plan.arc(x0 + 250, yc + 125, 26, 0, 360, step=8)[:-1]
    plan.hole(outer, inner, tags('natural=water water=lake', name='Озеро'))
    plan.area(inner, tags('place=islet natural=wood', name='Острівець'))
    plan.rect(x0 + 40, yc - 220, x0 + 460, yc - 40, tags('leisure=park', name='Парк зі ставком'))
    plan.area(plan.arc(x0 + 250, yc - 130, 40, 0, 360, step=8)[:-1], tags('natural=water water=pond', name='Ставок'))
    plan.way(plan.arc(x0 + 250, yc - 130, 52, 0, 360, step=10), tags('highway=footway'))
    plan.way([(x0 + 250, yc), (x0 + 250, yc - 78)], tags('highway=footway'))


def water_canal(plan, i, j, x0, y0, yc):
    bridged(plan, i, j, 'highway=tertiary', 'міст через канал', 225, 275)
    xr = x0 + 250
    plan.way([(xr, y0 + 20), (xr, y0 + 480)], tags('waterway=canal', name='Канал'))
    plan.rect(xr - 8, y0 + 20, xr + 8, y0 + 480, tags('natural=water water=canal'))
    plan.way([(xr - 60, yc + 120), (xr - 14, yc + 120)], tags('highway=footway'))
    plan.way([(xr - 14, yc + 120), (xr + 14, yc + 120)], tags('highway=footway bridge=yes layer=1'))
    plan.way([(xr + 14, yc + 120), (xr + 60, yc + 120)], tags('highway=footway'))
    plan.way([(xr - 12, y0 + 20), (xr - 12, yc - 12)], tags('barrier=retaining_wall'))
    _bed(plan, [(xr, y0 + 20), (xr, y0 + 480)], 40., 3.)


def water_marsh(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, tags('highway=tertiary embankment=yes'), 'болото й очерет')
    plan.rect(x0 + 20, yc + 24, x0 + 480, yc + 230, tags('natural=wetland wetland=reedbed'))
    plan.area(plan.arc(x0 + 250, yc + 130, 60, 0, 360, step=9)[:-1], tags('natural=water water=pond'))
    plan.rect(x0 + 20, yc - 230, x0 + 240, yc - 24, tags('natural=wetland wetland=marsh'))
    plan.rect(x0 + 260, yc - 230, x0 + 480, yc - 24, tags('natural=wetland wetland=bog'))
    plan.way([(x0 + 40, yc - 120), (x0 + 220, yc - 120)], tags('highway=path bridge=boardwalk surface=wood'))


def water_reservoir(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, tags('highway=tertiary'), 'водосховище й басейни')
    plan.rect(x0 + 40, yc + 50, x0 + 460, yc + 220, tags('natural=water water=reservoir', name='Водосховище'))
    plan.way([(x0 + 40, yc + 50), (x0 + 460, yc + 50)], tags('waterway=dam'))
    plan.rect(x0 + 40, yc - 220, x0 + 200, yc - 60, tags('natural=water water=basin landuse=basin'))
    plan.rect(x0 + 240, yc - 110, x0 + 290, yc - 85, tags('leisure=swimming_pool'))
    plan.rect(x0 + 330, yc - 220, x0 + 460, yc - 60, tags('landuse=salt_pond natural=water'))


def water_quay(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, tags('highway=tertiary sidewalk=both'), 'набережна')
    plan.rect(x0 + 20, yc + 60, x0 + 480, yc + 230, tags('natural=water water=lake', name='Затока'))
    plan.way([(x0 + 20, yc + 52), (x0 + 480, yc + 52)], tags('highway=pedestrian', name='Набережна'))
    plan.way([(x0 + 20, yc + 59), (x0 + 480, yc + 59)], tags('barrier=retaining_wall'))
    plan.way([(x0 + 250, yc + 52), (x0 + 250, yc + 160)], tags('man_made=pier highway=footway'))
    for k in range(10):
        plan.node(x0 + 40 + k * 46, yc + 48, tags('highway=street_lamp' if k % 2 else 'amenity=bench'))
    plan.way([(x0 + 120, yc + 30), (x0 + 120, yc + 52)], tags('highway=footway'))
    plan.rect(x0 + 20, yc - 230, x0 + 480, yc - 30, tags('natural=beach surface=sand', name='Міський пляж'))


def rail_single(plan, i, j, x0, y0, yc):
    ave = avenue(plan, i, j, tags('highway=tertiary'), 'переїзд, одна колія')
    plan.way([(x0 + 250, y0 + 10), (x0 + 250, y0 + 490)], tags('railway=rail gauge=1520 usage=branch', name='Колія I2'))
    _on(plan, ave, x0 + 250, yc, tags('railway=level_crossing crossing:barrier=full crossing:light=yes'))
    plan.rect(x0 + 232, y0 + 10, x0 + 268, y0 + 490, tags('landuse=railway'))


def rail_station(plan, i, j, x0, y0, yc):
    ave = avenue(plan, i, j, tags('highway=secondary lanes=2'), 'станція, дві колії')
    for dx in (247, 253):
        plan.way([(x0 + dx, y0 + 10), (x0 + dx, y0 + 490)], tags('railway=rail gauge=1520 usage=main electrified=contact_line'))
        _on(plan, ave, x0 + dx, yc, tags('railway=level_crossing crossing:barrier=half'))
    plan.rect(x0 + 258, yc + 30, x0 + 263, yc + 200, tags('railway=platform public_transport=platform'))
    plan.rect(x0 + 237, yc + 30, x0 + 242, yc + 200, tags('railway=platform public_transport=platform'))
    house(plan, x0 + 300, yc + 110, 30, 60, tags('building=train_station building:levels=2', name='Вокзал Немо'), doors=1, door='entrance=main')
    plan.node(x0 + 250, yc + 110, tags('railway=station', name='Немо-Пасажирський'))
    plan.rect(x0 + 330, yc + 40, x0 + 460, yc + 180, tags('amenity=parking parking=surface'))
    plan.way([(x0 + 395, yc), (x0 + 395, yc + 110)], tags('highway=service'))
    plan.way([(x0 + 242, yc + 60), (x0 + 258, yc + 60)], tags('highway=footway railway=crossing'))
    plan.node(x0 + 247, yc - 150, tags('railway=signal'))
    plan.node(x0 + 253, yc - 200, tags('railway=buffer_stop'))


def rail_tram(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, tags('highway=secondary lanes=4 sidewalk=both'), 'трамвай у дорозі')
    for dy in (-1.7, 1.7):
        plan.way([(x0 + 2, yc + dy), (x0 + 498, yc + dy)], tags('railway=tram gauge=1524 embedded=yes electrified=contact_line'))
    for x in (120, 380):
        plan.node(x0 + x, yc + 1.7, tags('railway=tram_stop public_transport=stop_position tram=yes', name='Трамвайна'))
        plan.node(x0 + x, yc + 9, tags('highway=bus_stop public_transport=platform tram=yes shelter=yes', name='Трамвайна'))
    plan.way([(x0 + 250, yc - 1.7), (x0 + 280, yc - 30), (x0 + 280, yc - 200)], tags('railway=tram gauge=1524', name='У депо'))
    house(plan, x0 + 300, yc - 180, 80, 60, tags('building=industrial height=9', name='Трамвайне депо'))


def rail_over(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, tags('highway=tertiary'), 'колія над дорогою')
    xr = x0 + 250
    plan.way([(xr, y0 + 10), (xr, yc - 30)], tags('railway=rail gauge=1520 embankment=yes'))
    plan.way([(xr, yc - 30), (xr, yc + 30)], tags('railway=rail gauge=1520 bridge=yes layer=1'))
    plan.way([(xr, yc + 30), (xr, y0 + 490)], tags('railway=rail gauge=1520 embankment=yes'))

    def bank(x, y):
        import numpy as np
        across = np.clip(1 - np.abs(x - xr) / 45., 0, 1)
        gap = np.clip((np.abs(y - yc) - 24) / 30., 0, 1)
        ends = np.clip((235 - np.abs(y - yc)) / 60., 0, 1)
        return 7. * smooth_(across) * gap * ends
    plan.relief.append(bank)


def rail_under(plan, i, j, x0, y0, yc):
    bridged(plan, i, j, 'highway=secondary lanes=2', 'дорога над колією', 190, 310)
    plan.way([(x0 + 250, y0 + 10), (x0 + 250, y0 + 490)], tags('railway=rail gauge=1520 usage=main'))
    plan.way([(x0 + 256, y0 + 10), (x0 + 256, y0 + 490)], tags('railway=light_rail'))


def rail_yard(plan, i, j, x0, y0, yc):
    ave = avenue(plan, i, j, tags('highway=tertiary'), 'вузька колія й депо')
    plan.rect(x0 + 60, yc + 30, x0 + 440, yc + 220, tags('landuse=railway', name='Сортувальна'))
    for k in range(6):
        plan.way([(x0 + 80, yc + 50 + k * 28), (x0 + 420, yc + 50 + k * 28)], tags('railway=rail gauge=1520 service=yard'))
        plan.node(x0 + 420, yc + 50 + k * 28, tags('railway=buffer_stop'))
    house(plan, x0 + 120, yc + 200, 80, 24, tags('building=train_station building:levels=1 height=8', name='Локомотивне депо'))
    plan.way([(x0 + 150, y0 + 10), (x0 + 150, yc - 40), (x0 + 350, yc - 40), (x0 + 350, y0 + 10 + 0)], tags('railway=narrow_gauge gauge=750'))
    plan.way([(x0 + 100, yc - 200), (x0 + 100, yc), (x0 + 100, yc + 30)], tags('railway=rail gauge=1520 service=spur'))
    _on(plan, ave, x0 + 100, yc, tags('railway=level_crossing'))
    plan.way([(x0 + 400, yc - 200), (x0 + 480, yc - 200)], tags('railway=disused'))


WATER = (('Річка й міст', 'River and a bridge', water_river), ('Струмок, канава, труба', 'Stream, ditch, culvert', water_stream),
         ('Озеро з островом, ставок', 'Lake with an island, pond', water_lake), ('Канал', 'Canal', water_canal),
         ('Болото', 'Wetlands', water_marsh), ('Водосховище, басейни', 'Reservoir, basins', water_reservoir),
         ('Набережна й пляж', 'Quay and beach', water_quay), ('Переїзд', 'Level crossing', rail_single),
         ('Станція', 'Station', rail_station), ('Трамвай', 'Tram', rail_tram), ('Колія над дорогою', 'Rail over the road', rail_over),
         ('Дорога над колією', 'Road over the rails', rail_under), ('Депо, вузька колія', 'Yard, narrow gauge', rail_yard))


def water_tile(plan, i, j, k):
    title, title_en, make = WATER[k]
    x0, y0, yc = register(plan, i, j, 'water', title, title_en)
    if k >= 7:
        open_ground(plan, i, j)       # the rails; the water keeps its wild banks
    make(plan, i, j, x0, y0, yc)


def water(plan, j):
    for k, i in enumerate(c for c in COLS if c != 0):
        water_tile(plan, i, j, k)


# --- row 1: relief ------------------------------------------------------------------------------
def smooth_(t):
    import numpy as np
    t = np.clip(t, 0., 1.)
    return t * t * (3 - 2 * t)


def _within(x0, y0, x, y, edge=70.):
    """1 inside a tile, falling to 0 over edge metres at its sides: a tile's relief stays its own."""
    return (smooth_((x - x0) / edge) * smooth_((x0 + TILE - x) / edge)
            * smooth_((y - y0) / edge) * smooth_((y0 + TILE - y) / edge))


def relief_grade(grade):
    def make(plan, i, j, x0, y0, yc):
        avenue(plan, i, j, tags('highway=tertiary'), f'ухил {grade} %', xs=(250,))
        top = grade / 100. * 180

        def ridge(x, y):
            import numpy as np
            return top * np.clip(1 - np.abs(x - (x0 + 250)) / 180., 0, 1) * smooth_((y - y0) / 70.) * smooth_((y0 + TILE - y) / 70.)
        plan.relief.append(ridge)
        plan.way([(x0 + 250, yc), (x0 + 250, yc + 200)], tags('highway=residential', name=f'{code(i, j)} гребенем'))
        plan.way([(x0 + 70, yc - 120), (x0 + 430, yc - 120)], tags('highway=track tracktype=grade3', name=f'{code(i, j)} ґрунтова, {grade} %'))
        plan.way([(x0 + 70, yc), (x0 + 70, yc - 120)], tags('highway=track tracktype=grade3'))
    return make


def relief_serpentine(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, tags('highway=tertiary'), 'серпантин і кар’єр', xs=(120, 250))
    cx, cy = x0 + 250, yc + 125

    def hill(x, y):
        import numpy as np
        return 46. * smooth_(1 - np.hypot(x - cx, y - cy) / 120.)
    plan.relief.append(hill)
    pts = [(x0 + 120, yc)]
    for k in range(6):
        y = yc + 26 + k * 17
        half = 96 - k * 13
        row = [(cx - half, y), (cx + half, y)]
        pts += row if k % 2 == 0 else row[::-1]
    pts.append((cx, cy))
    plan.way(pts, tags('highway=residential', name=f'{code(i, j)} серпантин'))
    plan.node(cx, cy, tags('tourism=viewpoint highway=turning_circle', name='Оглядовий майданчик'))
    px, py = x0 + 250, yc - 125

    def pit(x, y):
        import numpy as np
        return -9. * smooth_(1 - np.hypot(x - px, y - py) / 110.)
    plan.relief.append(pit)
    plan.area(plan.arc(px, py, 95, 0, 360, step=14)[:-1], tags('landuse=quarry natural=bare_rock', name='Кар’єр'))
    plan.way([(x0 + 250, yc), (x0 + 250, yc - 60), (px + 50, py + 20), (px, py)], tags('highway=track tracktype=grade4'))


def relief_cross(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, tags('highway=tertiary'), 'косогір 20 %', xs=(250,))

    def slope(x, y):
        import numpy as np
        return np.clip(.2 * (y - yc), -36., 36.) * _within(x0, y0, x, y)
    plan.relief.append(slope)
    for k in range(6):
        house(plan, x0 + 60 + k * 75, yc + 30, 12, 10, tags('building=house building:levels=2 roof:shape=gabled'))
        house(plan, x0 + 60 + k * 75, yc - 30, 12, 10, tags('building=house building:levels=1 roof:shape=hipped'))
    plan.way([(x0 + 250, yc), (x0 + 250, yc + 190)], tags('highway=residential', name=f'{code(i, j)} угору, 20 %'))
    plan.way([(x0 + 250, yc), (x0 + 250, yc - 190)], tags('highway=residential', name=f'{code(i, j)} униз, 20 %'))


def relief_viaduct(plan, i, j, x0, y0, yc):
    bridged(plan, i, j, 'highway=secondary lanes=2', 'віадук над долиною', 150, 350, 'bridge:structure=beam')
    xr = x0 + 250

    def valley(x, y):
        import numpy as np
        return -22. * smooth_(1 - np.abs(x - xr) / 110.) * smooth_((y - y0) / 60.) * smooth_((y0 + TILE - y) / 60.)
    plan.relief.append(valley)
    plan.way([(xr, y0 + 60), (xr, y0 + 440)], tags('waterway=stream', name='Потік'))
    plan.way([(x0 + 130, yc - 100), (xr + 120, yc - 100)], tags('highway=track tracktype=grade3', name=f'{code(i, j)} дном долини'))


def relief_tunnel(plan, i, j, x0, y0, yc):
    name = f'{code(i, j)} тунель'
    plan.way([(x0, yc), (x0 + 150, yc)], tags('highway=secondary lanes=2', name=name))
    plan.way([(x0 + 150, yc), (x0 + 350, yc)], tags('highway=secondary lanes=2 tunnel=yes layer=-1', name=name))
    plan.way([(x0 + 350, yc), (x0 + TILE, yc)], tags('highway=secondary lanes=2', name=name))

    def ridge(x, y):
        import numpy as np
        return 34. * smooth_(1 - np.abs(x - (x0 + 250)) / 115.) * smooth_((y - y0) / 60.) * smooth_((y0 + TILE - y) / 60.)
    plan.relief.append(ridge)
    plan.way([(x0 + 100, yc), (x0 + 100, yc + 150), (x0 + 400, yc + 150), (x0 + 400, yc)], tags('highway=track tracktype=grade2', name=f'{code(i, j)} через перевал'))
    plan.node(x0 + 250, yc + 150, tags('mountain_pass=yes', name='Перевал'))


def relief_waves(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, tags('highway=tertiary'), 'хвилі: виїмки й насипи')

    def waves(x, y):
        import numpy as np
        return 7. * np.sin((x - x0) / 160. * 2 * math.pi) * np.cos((y - y0) / 220. * 2 * math.pi) * _within(x0, y0, x, y)
    plan.relief.append(waves)
    plan.way([(x0 + 40, yc + 120), (x0 + 460, yc + 120)], tags('highway=unclassified', name=f'{code(i, j)} паралельна'))
    plan.way([(x0 + 40, yc), (x0 + 40, yc + 120)], tags('highway=unclassified'))
    plan.way([(x0 + 460, yc), (x0 + 460, yc + 120)], tags('highway=unclassified'))
    plan.way([(x0 + 40, yc - 120), (x0 + 460, yc - 120)], tags('railway=rail gauge=1520', name='Колія хвилями'))


def relief_steps(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, tags('highway=tertiary'), 'тераси й цілі метри DEM')

    def terraces(x, y):
        import numpy as np
        raw = (x - x0) / TILE * 18.
        north = np.floor(raw / 3.) * 3.                    # terraces 3 m high every 83 m
        south = np.round(raw)                              # a survey in whole metres, as Terrarium has it
        return np.where(y > yc, north, south) * _within(x0, y0, x, y, 40.)
    plan.relief.append(terraces)
    plan.way([(x0 + 40, yc + 120), (x0 + 460, yc + 120)], tags('highway=residential', name=f'{code(i, j)} терасами'))
    plan.way([(x0 + 40, yc - 120), (x0 + 460, yc - 120)], tags('highway=residential', name=f'{code(i, j)} сходинками DEM'))
    for x in (40, 460):
        plan.way([(x0 + x, yc - 120), (x0 + x, yc + 120)], tags('highway=residential'))


def relief_studio(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, tags('highway=tertiary'), 'студія: рівні майданчики', xs=(250,))
    # paved ground with nothing on it: a square would be given benches and bins, a car park cars
    plan.rect(x0 + 30, yc + 26, x0 + 470, yc + 226, tags('landuse=commercial surface=asphalt', name='Студія, асфальт'))
    plan.rect(x0 + 30, yc - 226, x0 + 245, yc - 26, tags('landuse=commercial surface=concrete', name='Студія, бетон'))
    plan.rect(x0 + 255, yc - 226, x0 + 470, yc - 26, tags('landuse=commercial surface=paving_stones', name='Студія, плитка'))
    plan.way([(x0 + 250, yc), (x0 + 250, yc + 120)], tags('highway=service'))
    plan.way([(x0 + 250, yc), (x0 + 250, yc - 120)], tags('highway=service'))
    views = plan.tiles[code(i, j)]['views']
    views.append({'id': 'studio', 'eye': (x0 + 250, yc + 104, 1.5), 'target': (x0 + 250, yc + 126, 0.7), 'fov': 40})
    views.append({'id': 'studio-side', 'eye': (x0 + 232, yc + 126, 1.2), 'target': (x0 + 250, yc + 126, 0.7), 'fov': 40})
    views.append({'id': 'studio-34', 'eye': (x0 + 238, yc + 112, 1.8), 'target': (x0 + 250, yc + 126, 0.6), 'fov': 45})
    plan.tiles[code(i, j)]['at'] = (x0 + 250, yc + 126)
    plan.tiles[code(i, j)]['yaw'] = 90


def relief_offroad(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, tags('highway=track tracktype=grade3 surface=dirt'), 'бездоріжжя')

    def bumps(x, y):
        import numpy as np
        a = np.sin((x - x0) / 55. * 2 * math.pi) * np.sin((y - y0) / 70. * 2 * math.pi)
        b = np.sin((x - x0) / 31. * 2 * math.pi + 1.3) * np.cos((y - y0) / 43. * 2 * math.pi)
        return (5. * a + 2. * b + 4.) * _within(x0, y0, x, y)
    plan.relief.append(bumps)
    plan.rect(x0 + 30, yc + 30, x0 + 240, yc + 220, tags('natural=scree'))
    plan.rect(x0 + 260, yc + 30, x0 + 470, yc + 220, tags('natural=bare_rock'))
    plan.rect(x0 + 30, yc - 220, x0 + 240, yc - 30, tags('natural=sand'))
    plan.rect(x0 + 260, yc - 220, x0 + 470, yc - 30, tags('natural=mud'))
    loop = [(x0 + 60, yc), (x0 + 60, yc + 190), (x0 + 440, yc + 190), (x0 + 440, yc - 190), (x0 + 60, yc - 190), (x0 + 60, yc)]
    plan.way(loop, tags('highway=track tracktype=grade5 surface=ground', name=f'{code(i, j)} коло бездоріжжям'))
    plan.way([(x0 + 250, yc + 190), (x0 + 250, yc - 190)], tags('highway=path surface=ground'))
    plan.way([(x0 + 150, yc - 200), (x0 + 150, yc + 200)], tags('waterway=stream', name='Брід'))
    plan.node(x0 + 150, yc, tags('ford=yes'))


RELIEF = (('Ухил 5 %', 'Grade 5 %', relief_grade(5)), ('Ухил 10 %', 'Grade 10 %', relief_grade(10)),
          ('Ухил 15 %', 'Grade 15 %', relief_grade(15)), ('Ухил 20 %', 'Grade 20 %', relief_grade(20)),
          ('Ухил 30 %', 'Grade 30 %', relief_grade(30)), ('Серпантин і кар’єр', 'Hairpins and a pit', relief_serpentine),
          ('Косогір', 'Cross slope', relief_cross), ('Віадук над долиною', 'Viaduct over a valley', relief_viaduct),
          ('Тунель під хребтом', 'Tunnel under a ridge', relief_tunnel), ('Хвилі: виїмки й насипи', 'Cuts and fills', relief_waves),
          ('Тераси й сходинки DEM', 'Terraces and DEM steps', relief_steps), ('Студія', 'Studio', relief_studio),
          ('Бездоріжжя', 'Off road', relief_offroad))


def relief_tile(plan, i, j, k):
    title, title_en, make = RELIEF[k]
    x0, y0, yc = register(plan, i, j, 'relief', title, title_en)
    open_ground(plan, i, j)
    make(plan, i, j, x0, y0, yc)


def relief(plan, j):
    for k, i in enumerate(c for c in COLS if c != 0):
        relief_tile(plan, i, j, k)


# --- the whole island ---------------------------------------------------------------------------
ROWS_PLAN = {10: ('classes', 'Класи доріг', 'Road classes', road_classes),
             9: ('surfaces', 'Покриття', 'Surfaces', surfaces),
             8: ('lanes', 'Смуги й розмітка', 'Lanes and markings', lanes),
             7: ('town', 'Міська забудова', 'Town blocks', town),
             6: ('works', 'Садиби, торгівля, виробництво', 'Houses, trade, works', works),
             5: ('street', 'Вуличні меблі й точки інтересу', 'Street furniture and points of interest', street),
             4: ('covers', 'Покриви землі', 'Ground covers', covers),
             3: ('plants', 'Рослинність', 'Vegetation', plants),
             2: ('water', 'Вода й колії', 'Water and rails', water),
             1: ('relief', 'Рельєф і студія', 'Relief and the studio', relief)}


# What a theme is there to show, for the page's card of the tile under the car (the catalogue's
# 'themes'): a tile's zone -> its name and one sentence on what to look at.
THEMES = {
    'classes': ('Класи доріг', 'Road classes',
                'Один клас дороги OSM на тайл, від автомагістралі до стежки: ширина, смуги, узбіччя й тротуари, '
                'які генератор дає класу без інших тегів.',
                'One OSM road class a tile, from a motorway to a path: the width, lanes, shoulders and sidewalks '
                'the generator gives a class with no other tags.'),
    'surfaces': ('Покриття', 'Surfaces',
                 'Одне значення surface на дорозі, тротуарі, ґрунтівці, стоянці й площі: матеріал, колії та знос.',
                 'One surface value on a road, a sidewalk, a track, a car park and a square: its material, ruts and wear.'),
    'lanes': ('Смуги й розмітка', 'Lanes and markings',
              'Кількість смуг і розмітка: від однієї до восьми смуг, 2+1, смуги повороту, однобічні вулиці, звуження.',
              'Lane counts and paint: one to eight lanes, 2+1, turn lanes, one-way streets, a width taper.'),
    'town': ('Міська забудова', 'Town blocks',
             'Квартали за епохами й типами: які стіни, дахи, вікна й двори конструктор дає кожному виду забудови.',
             'Blocks by era and type: the walls, roofs, windows and yards the kit gives each kind of building.'),
    'works': ('Садиби, торгівля, виробництво', 'Houses, trade, works',
              'Село, дачі, ферма, завод, склади, АЗС, крамниці, стадіон, цвинтар: забудова поза кварталами міста.',
              'A village, dachas, a farm, a plant, warehouses, fuel, shops, a stadium, a cemetery: what is built outside town blocks.'),
    'street': ('Вуличні меблі й точки інтересу', 'Street furniture and points of interest',
               'Ліхтарі, лавки, зупинки, переходи, знаки, паркани, бренди й реклама: що стоїть на вулиці і де саме.',
               'Lamps, benches, stops, crossings, signs, fences, brands and adverts: what stands on a street, and where.'),
    'covers': ('Покриви землі', 'Ground covers',
               'Кілька ділянок landuse і natural на тайл, від землі без тегів до льодовика: матеріал, трава й переходи між ними.',
               'Several landuse and natural plots a tile, from untagged land to a glacier: the material, the grass and how they meet.'),
    'plants': ('Рослинність', 'Vegetation',
               'Ліси за типом листя, парк, сад, виноградник, чагарник, болото: породи, густота й шари рослин.',
               'Woods by leaf type, a park, an orchard, a vineyard, scrub, a wetland: the species, the density and the layers.'),
    'water': ('Вода й колії', 'Water and rails',
              'Річка з мостом, струмок, озеро, канал, набережна; переїзд, станція, трамвай і шляхопроводи.',
              'A river and its bridge, a stream, a lake, a canal, an embankment; a level crossing, a station, a tram and overpasses.'),
    'relief': ('Рельєф', 'Relief',
               'Ухили 5–30 %, серпантин, кар’єр, косогір, віадук, тунель: як дорога й земля сідають на схил.',
               'Grades of 5-30 %, switchbacks, a quarry, a side slope, a viaduct, a tunnel: how the road and the land sit on a slope.'),
    'junctions': ('Перехрестя', 'Junctions',
                  'Світлофор, кільця, STOP, зебри, зміщені й косі з’їзди: як сходяться дороги, тротуари й розмітка.',
                  'Lights, roundabouts, a stop sign, zebras, offset and skewed arms: how roads, sidewalks and paint meet.'),
    'spans': ('Мости й тунелі', 'Bridges and tunnels',
              'Один міст або тунель на тайл: над водою, над дорогою, у рельєфі, за тегами, під землею й крізь будинки. '
              'Дивитися збоку: лінію настилу, його товщину, опори, стик із дорогою, портал.',
              'One bridge or tunnel a tile: over water, over a road, in relief, by its tags, under the ground and through '
              'houses. Look from the side: the deck’s line and depth, its piers, where it meets the road, the portal.'),
    'wild': ('Земля всесвіту', 'The universe’s own land',
             'Рельєф і природа, заради яких блок існує: тут видно клімат, підміну матеріалів і фізику ґрунту всесвіту.',
             'The relief and nature the block exists for: the universe’s climate, swapped materials and ground physics show here.'),
}


def themes():
    return {zone: {'title': uk, 'titleEn': en, 'about': about, 'aboutEn': about_en}
            for zone, (uk, en, about, about_en) in THEMES.items()}


# a subject of the main grid by its theme and its place in the row: what a universe builds again
TILES = {'classes': classes_tile, 'surfaces': surfaces_tile, 'lanes': lanes_tile, 'town': town_tile, 'works': works_tile,
         'street': street_tile, 'covers': covers_tile, 'plants': plants_tile, 'water': water_tile, 'relief': relief_tile,
         'junction': junction_tile}


def build(plan):
    coast(plan)
    ring(plan)
    junctions(plan)
    plan.zones.append({'id': 'junctions', 'title': 'Перехрестя (стовпець H)', 'titleEn': 'Junctions (column H)',
                       'start': (MERIDIAN + 1.6, GRID[1] + 40)})
    for row in sorted(ROWS_PLAN, reverse=True):
        zone, title, title_en, make = ROWS_PLAN[row]
        j = ROWS[0] + row - 1
        make(plan, j)
        plan.zones.append({'id': zone, 'title': f'{title} (ряд {row})', 'titleEn': f'{title_en} (row {row})',
                           'start': (GRID[0] + 30, centre_y(j) - 1.6)})
    # the studio first: the pack's own landing is a level square with nothing in the way
    studio = next((t for t in plan.tiles.values() if t['title'] == 'Студія'), None)
    if studio:
        plan.zones.insert(0, {'id': 'studio', 'title': 'Студія', 'titleEn': 'Studio', 'start': studio['at']})
    import proving_universes
    proving_universes.build(plan)
    import proving_spans
    proving_spans.build(plan)
