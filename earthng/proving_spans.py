"""The proving ground's bridges and tunnels (proving_ground.BLOCKS 'spans'): the island's
north-east corner, a span a tile.

A bridge or a tunnel that goes wrong has to be found on a real map first, and the next one of
its kind is in another country. Here every way a span can lie is a tile, in rows by what makes
it differ:

    row 6  arches through houses, a railway's bank, culverts, galleries, a bridge into a tunnel
    row 5  tunnels: under a ridge, in pieces round a bend, under a street, under level ground, under a river
    row 4  bridges by their tags: beam and viaduct, arch and truss, hung ones, movable and covered, for feet
    row 3  viaducts and relief: a valley, a higher one in pieces, banks of two heights, a hillside, an island
    row 2  overpasses: over a street, a divided road, the rails, three levels, slip roads
    row 1  bridges over water: a stream, a river, a flood plain in pieces, two carriageways, a skew curve

The block's land is level (BASE) whatever its neighbours do, and a tile's own relief is added
to that, so a profile read here is the span's and nothing else's. span_census.py measures the
block as it does a country (its --box is the block's corners); each tile has a camera from the
side, where a deck's line and depth show, and a tunnel's tile one before its mouth.
"""
import math

from proving_ground import BASE, BLOCK, TILE, code, tags
import proving_zones as z

ZONE = 'spans'
EDGE = 100.             # m the block's land comes level over at its edges


def rect():
    i0, i1, j0, j1 = BLOCK[ZONE]['tiles']
    return i0 * TILE, j0 * TILE, i1 * TILE, j1 * TILE


def level(plan):
    """The block's land at BASE: the mud's lowland and the range's spurs stop at its edge. Towards
    the mud in the south the land comes level inside the block (a tile's road is 250 m from that
    edge); towards the shore in the east and north it stays level to the block's edge and falls
    away outside it, where no tile is."""
    x0, y0, x1, y1 = rect()

    def carve(x, y, h):
        w = (z.smooth_((y - y0) / EDGE) * z.smooth_((x1 + EDGE - x) / EDGE) * z.smooth_((y1 + EDGE - y) / EDGE)
             * (x > x0) * (y > y0))
        return h * (1 - w) + BASE * w
    plan.carve.append(carve)


def relief(plan, f):
    """A tile's own relief, metres added to the level land: f(x, y) arrays."""
    plan.carve.append(lambda x, y, h: h + f(x, y))


FLOOR = BASE - 2.       # the deepest a tile digs: the sea covers whatever lies under its level
RAMP = 150.             # m a tile's road climbs to a valley's rim over (6 m: 6 %)


def valley(plan, x0, y0, xc, depth, half, along=60., rim=0., edges=(0., 0.)):
    """A valley (depth > 0) or a ridge (depth < 0) running north-south through a tile at x = xc.
    rim: the land either side of a valley stands this high over the block's; edges: how high it
    stands at the tile's west and east edges, the tile's road climbing from there to the rim
    over RAMP m (a tile whose neighbour keeps the same height at their edge starts higher: the
    row climbs by steps). The valley is `depth` under the rim. The land is 12 m over the sea: a
    valley's depth comes from its rim, not from under BASE."""
    if depth - rim > FLOOR:
        raise ValueError(f'a valley {depth} m deep under a rim of {rim} m lies under the sea')

    def f(x, y):
        import numpy as np
        across = z.smooth_((y - y0) / along) * z.smooth_((y0 + TILE - y) / along)
        west = edges[0] + (rim - edges[0]) * z.smooth_((x - x0) / RAMP)
        east = edges[1] + (rim - edges[1]) * z.smooth_((x0 + TILE - x) / RAMP)
        inside = (x >= x0) & (x < x0 + TILE)                # an edge that stands high is this tile's alone
        return (np.where(x < xc, west, east) - depth * z.smooth_(1 - np.abs(x - xc) / half)) * across * inside
    relief(plan, f)


def avenue(plan, i, j, spec, label, cuts=(), ys=None):
    """A tile's road west to east, named after what it shows. cuts: (from, to, tags) in metres
    from the tile's west edge, each a way of its own with those tags added (a span, or one
    piece of it). ys: f(metres from the west edge) -> metres north of the tile's middle, for a
    road that bends; its points are then 10 m apart."""
    x0, y0 = z.origin(i, j)
    yc = y0 + TILE / 2
    name = f'{code(i, j)} {label}'
    marks = sorted({0., TILE, *(float(v) for c in cuts for v in c[:2])})
    span = {(float(a), float(b)): extra for a, b, extra in cuts}

    def points(a, b):
        if ys is None:
            return [(x0 + a, yc), (x0 + b, yc)]
        n = max(1, int(math.ceil((b - a) / 10.)))
        return [(x0 + a + (b - a) * k / n, yc + ys(a + (b - a) * k / n)) for k in range(n + 1)]
    for a, b in zip(marks, marks[1:]):
        plan.way(points(a, b), tags(spec + ' ' + span.get((a, b), ''), name=name))


def link(plan, i, j, x, y, spec='highway=residential', west=True):
    """A road from (x, y) to the tile's avenue 40 m from its west (or east) edge: what passes
    under a bridge is joined to the island's roads by it."""
    x0, y0 = z.origin(i, j)
    xa = x0 + (40 if west else TILE - 40)
    plan.way([(x, y), (xa, y), (xa, y0 + TILE / 2)], tags(spec))


def river(plan, line, half, bed=None, depth=5., name=None):
    """A river along a line: its water `half` m either side, in a bed `depth` m deep."""
    plan.way(line, tags('waterway=river', name=name))
    plan.area([(x - half, y) for x, y in line] + [(x + half, y) for x, y in line[::-1]], tags('natural=water water=river'))
    z._bed(plan, line, bed or half + 50., depth)


def side_view(plan, i, j, back=150., up=5., at=4.):
    """The camera a span's line shows from: south of the tile's middle, low."""
    x0, y0 = z.origin(i, j)
    yc = y0 + TILE / 2
    plan.tiles[code(i, j)]['views'].append({'id': 'side', 'eye': (x0 + 250, yc - back, up), 'target': (x0 + 250, yc, at), 'fov': 60})


def mouth_view(plan, i, j, at, dy=0., back=70.):
    """The camera a tunnel's mouth shows from: on its road, `back` m before the mouth `at` m from
    the tile's west edge (the side camera of a tile whose ridge runs through it stands on the ridge)."""
    x0, y0 = z.origin(i, j)
    yc = y0 + TILE / 2 + dy
    plan.tiles[code(i, j)]['views'].append({'id': 'mouth', 'eye': (x0 + at - back, yc - 6, 3.5), 'target': (x0 + at, yc, 2.5), 'fov': 55})


BRIDGE = 'bridge=yes layer=1'
TUNNEL = 'tunnel=yes layer=-1'


# --- row 1: bridges over water -----------------------------------------------------------------
def water_stream(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=tertiary', 'місток через струмок', [(240, 260, BRIDGE)])
    line = [(x0 + 250, y0 + 30), (x0 + 250, y0 + 470)]
    plan.way(line, tags('waterway=stream', name='Струмок'))
    z._bed(plan, line, 30., 2.5)


def water_river(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=secondary lanes=2', 'міст через річку', [(205, 295, BRIDGE)])
    xr = x0 + 250
    river(plan, [(xr - 20, y0 + 20), (xr + 15, y0 + 140), (xr, yc), (xr - 15, y0 + 360), (xr + 20, y0 + 480)], 18., 70., name='Немо')


def water_plain(plan, i, j, x0, y0, yc):
    # the deck starts on the flood plain 100 m before the water: over each bank it rose to the
    # clearance and fell back over the river
    avenue(plan, i, j, 'highway=primary lanes=2', 'міст через заплаву, три частини',
           [(100, 200, BRIDGE), (200, 300, BRIDGE), (300, 400, BRIDGE)])
    xr = x0 + 250
    river(plan, [(xr, y0 + 20), (xr, y0 + 480)], 50., 90., name='Широка')
    plan.rect(x0 + 110, y0 + 30, xr - 60, y0 + 470, tags('natural=wetland wetland=wet_meadow'))


def water_dual(plan, i, j, x0, y0, yc):
    name = f'{code(i, j)} два мости поруч'
    spec = 'highway=trunk lanes=2 oneway=yes'
    plan.way([(x0, yc), (x0 + 60, yc)], tags('highway=trunk lanes=2', name=name))
    plan.way([(x0 + 440, yc), (x0 + TILE, yc)], tags('highway=trunk lanes=2', name=name))
    for dy, flip in ((-6.5, False), (6.5, True)):
        parts = [[(x0 + 60, yc), (x0 + 110, yc + dy), (x0 + 190, yc + dy)],
                 [(x0 + 190, yc + dy), (x0 + 310, yc + dy)],
                 [(x0 + 310, yc + dy), (x0 + 390, yc + dy), (x0 + 440, yc)]]
        for k, pts in enumerate(parts):
            extra = ' ' + BRIDGE if k == 1 else ''
            plan.way(pts[::-1] if flip else pts, tags(spec + extra, name=name))
    river(plan, [(x0 + 250, y0 + 20), (x0 + 250, y0 + 480)], 30., 80., name='Двоє')


def water_skew(plan, i, j, x0, y0, yc):
    bend = lambda s: 60. * math.sin(math.pi * min(max((s - 100.) / 300., 0.), 1.)) ** 2
    avenue(plan, i, j, 'highway=secondary lanes=2', 'міст у кривій, навскіс',
           [(190, 250, BRIDGE), (250, 310, BRIDGE)], ys=bend)
    river(plan, [(x0 + 90, y0 + 150), (x0 + 250, yc + 60), (x0 + 410, y0 + 470)], 20., 70., name='Коса')


# --- row 2: overpasses -------------------------------------------------------------------------
def over_street(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=secondary lanes=2', 'шляхопровід над вулицею', [(220, 280, BRIDGE)])
    plan.way([(x0 + 250, y0 + 60), (x0 + 250, y0 + 440)], tags('highway=residential', name='Під мостом'))
    link(plan, i, j, x0 + 250, y0 + 60)


def over_divided(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=primary lanes=2', 'шляхопровід над магістраллю', [(180, 320, BRIDGE)])
    for dx, flip in ((-8, True), (8, False)):
        pts = [(x0 + 250 + dx, y0 + 60), (x0 + 250 + dx, y0 + 440)]
        plan.way(pts[::-1] if flip else pts, tags('highway=trunk lanes=2 oneway=yes', name='Магістраль під мостом'))
    plan.way([(x0 + 242, y0 + 60), (x0 + 258, y0 + 60)], tags('highway=trunk'))
    plan.way([(x0 + 242, y0 + 440), (x0 + 258, y0 + 440)], tags('highway=trunk'))
    link(plan, i, j, x0 + 242, y0 + 60)


def over_rails(plan, i, j, x0, y0, yc):
    # nothing of the road graph passes under: the deck stands the clearance over level ground
    avenue(plan, i, j, 'highway=secondary lanes=2', 'шляхопровід над колією', [(190, 310, BRIDGE)])
    for dx in (247, 253):
        plan.way([(x0 + dx, y0 + 10), (x0 + dx, y0 + 490)], tags('railway=rail gauge=1520 usage=main electrified=contact_line'))


def over_stack(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=primary lanes=2', 'три рівні', [(130, 370, 'bridge=yes layer=2')])
    xm = x0 + 250
    name = f'{code(i, j)} середній рівень'
    plan.way([(xm, y0 + 40), (xm, yc - 70)], tags('highway=secondary', name=name))
    plan.way([(xm, yc - 70), (xm, yc + 70)], tags('highway=secondary ' + BRIDGE, name=name))
    plan.way([(xm, yc + 70), (xm, y0 + 460)], tags('highway=secondary', name=name))
    link(plan, i, j, xm, y0 + 40)
    plan.way([(x0 + 150, yc - 100), (x0 + 350, yc + 100)], tags('highway=residential', name=f'{code(i, j)} низом'))
    link(plan, i, j, x0 + 350, yc + 100, west=False)


def over_slips(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=trunk lanes=2', 'міст із з’їздами', [(200, 300, BRIDGE)])
    xm = x0 + 250
    plan.way([(xm, y0 + 50), (xm, y0 + 450)], tags('highway=secondary', name='Під мостом'))
    link(plan, i, j, xm, y0 + 50)
    # a slip road down from the approach, and one that leaves the deck itself
    plan.way([(x0 + 110, yc), (x0 + 160, yc - 14), (x0 + 215, yc - 70), (xm, yc - 130)], tags('highway=trunk_link oneway=yes'))
    plan.way([(x0 + 280, yc), (x0 + 320, yc + 12), (x0 + 345, yc + 40)], tags('highway=trunk_link oneway=yes ' + BRIDGE))
    plan.way([(x0 + 345, yc + 40), (x0 + 350, yc + 100), (x0 + 310, yc + 150), (xm, yc + 160)], tags('highway=trunk_link oneway=yes'))


# --- row 3: viaducts and relief ----------------------------------------------------------------
def relief_viaduct(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=secondary lanes=2', 'віадук над долиною', [(150, 350, 'bridge=viaduct layer=1')])
    valley(plan, x0, y0, x0 + 250, 16., 100., rim=6., edges=(0., 6.))
    plan.way([(x0 + 250, y0 + 60), (x0 + 250, y0 + 440)], tags('waterway=stream', name='Потік'))
    plan.way([(x0 + 130, yc - 100), (x0 + 370, yc - 100)], tags('highway=track tracktype=grade3', name=f'{code(i, j)} дном долини'))


def relief_deep(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=trunk lanes=2', 'високий віадук, чотири частини',
           [(150 + 50 * k, 200 + 50 * k, 'bridge=viaduct layer=1') for k in range(4)])
    valley(plan, x0, y0, x0 + 250, 22., 100., rim=12., edges=(6., 6.))
    plan.way([(x0 + 250, y0 + 60), (x0 + 250, y0 + 440)], tags('waterway=stream'))


def relief_banks(plan, i, j, x0, y0, yc):
    # a deck that only runs uphill from one bank to the other: no ramp to ease, no step to leave
    avenue(plan, i, j, 'highway=secondary lanes=2', 'міст між берегами різної висоти', [(170, 330, BRIDGE)])

    def f(x, y):
        import numpy as np
        within = z._within(x0, y0, x, y)
        gorge = -FLOOR * z.smooth_(1 - np.abs(x - (x0 + 250)) / 80.)
        # (the high viaduct's tile ends 6 m up at this one's west edge: down from there first)
        down = 6. * z.smooth_(1 - (x - x0) / 110.) * z.smooth_((y - y0) / 60.) * z.smooth_((y0 + TILE - y) / 60.) * (x >= x0)
        return down + (14. * z.smooth_((x - (x0 + 200)) / 180.) + gorge) * within
    relief(plan, f)
    plan.way([(x0 + 250, y0 + 70), (x0 + 250, y0 + 430)], tags('waterway=stream'))


def relief_hillside(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=secondary lanes=2', 'віадук на косогорі', [(190, 310, BRIDGE)])

    def f(x, y):
        import numpy as np
        # (the low side stops 4 m under the road and the gully 6 m under that: lower is the sea's)
        slope = np.clip(.2 * (y - yc), -4., 30.)
        gully = -6. * z.smooth_(1 - np.abs(x - (x0 + 250)) / 75.) * z.smooth_((y - yc + 120) / 120.)
        return (slope + gully) * z._within(x0, y0, x, y)
    relief(plan, f)


def relief_island(plan, i, j, x0, y0, yc):
    # two channels and the island between them: the deck must not come down to the island
    avenue(plan, i, j, 'highway=primary lanes=2', 'міст через острів, дві частини', [(80, 250, BRIDGE), (250, 420, BRIDGE)])
    for xr, name in ((x0 + 150, 'Лівий рукав'), (x0 + 350, 'Правий рукав')):
        river(plan, [(xr, y0 + 20), (xr, y0 + 480)], 28., 60., name=name)
    plan.rect(x0 + 200, y0 + 40, x0 + 300, y0 + 460, tags('natural=scrub', name='Острів'))


# --- row 4: bridges by their tags ----------------------------------------------------------------
def kinds(first, second, label, water=True):
    """A tile of two bridges with different tags over one canal: the avenue's and a street's 130 m north."""
    def make(plan, i, j, x0, y0, yc):
        avenue(plan, i, j, 'highway=secondary lanes=2', label, [(200, 300, first + ' layer=1')])
        name = f'{code(i, j)} другий міст'
        ya = yc + 130
        plan.way([(x0 + 40, yc), (x0 + 40, ya), (x0 + 200, ya)], tags('highway=tertiary', name=name))
        plan.way([(x0 + 200, ya), (x0 + 300, ya)], tags('highway=tertiary ' + second + ' layer=1', name=name))
        plan.way([(x0 + 300, ya), (x0 + 460, ya), (x0 + 460, yc)], tags('highway=tertiary', name=name))
        river(plan, [(x0 + 250, y0 + 20), (x0 + 250, y0 + 480)], 30., 75., name='Канал видів')
    return make


def kinds_foot(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=tertiary', 'мости для людей', [(215, 285, BRIDGE)])
    river(plan, [(x0 + 250, y0 + 20), (x0 + 250, y0 + 480)], 22., 60., name='Тиха')
    for dy, spec in ((70, 'highway=footway'), (110, 'highway=cycleway'), (150, 'highway=pedestrian')):
        y = yc + dy
        plan.way([(x0 + 150, y), (x0 + 215, y)], tags(spec))
        plan.way([(x0 + 215, y), (x0 + 285, y)], tags(spec + ' ' + BRIDGE))
        plan.way([(x0 + 285, y), (x0 + 350, y)], tags(spec))
    plan.way([(x0 + 150, yc), (x0 + 150, yc + 150)], tags('highway=footway'))
    plan.way([(x0 + 350, yc), (x0 + 350, yc + 150)], tags('highway=footway'))
    # a ford's cousin and a walk over a marsh
    plan.way([(x0 + 150, yc - 110), (x0 + 228, yc - 110)], tags('highway=service'))
    plan.way([(x0 + 228, yc - 110), (x0 + 272, yc - 110)], tags('highway=service bridge=low_water_crossing'))
    plan.way([(x0 + 272, yc - 110), (x0 + 350, yc - 110)], tags('highway=service'))
    plan.way([(x0 + 150, yc), (x0 + 150, yc - 110)], tags('highway=service'))
    plan.way([(x0 + 350, yc), (x0 + 350, yc - 110)], tags('highway=service'))
    plan.rect(x0 + 60, yc - 220, x0 + 200, yc - 140, tags('natural=wetland wetland=marsh'))
    plan.way([(x0 + 70, yc - 180), (x0 + 190, yc - 180)], tags('highway=path bridge=boardwalk surface=wood'))


# --- row 5: tunnels ----------------------------------------------------------------------------
def tunnel_ridge(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=secondary lanes=2', 'тунель під хребтом', [(150, 350, TUNNEL)])
    valley(plan, x0, y0, x0 + 250, -34., 115.)
    plan.way([(x0 + 100, yc), (x0 + 100, yc + 150), (x0 + 400, yc + 150), (x0 + 400, yc)],
             tags('highway=track tracktype=grade2', name=f'{code(i, j)} через перевал'))
    mouth_view(plan, i, j, 150)


def tunnel_pieces(plan, i, j, x0, y0, yc):
    # four ways of one tunnel round a bend: every split of the way used to come up to the hill's top
    bend = lambda s: 28. * math.sin(2 * math.pi * min(max((s - 60.) / 380., 0.), 1.))
    avenue(plan, i, j, 'highway=primary lanes=2', 'довгий тунель, чотири частини, у кривій',
           [(60 + 95 * k, 155 + 95 * k, TUNNEL) for k in range(4)], ys=bend)
    valley(plan, x0, y0, x0 + 250, -60., 200.)
    mouth_view(plan, i, j, 60)


def tunnel_street(plan, i, j, x0, y0, yc):
    # underpasses shorter than two of the height solve's stations: nothing pulled them under the street
    avenue(plan, i, j, 'highway=secondary lanes=2', 'проїзд під вулицею, 30 м', [(235, 265, TUNNEL)])
    xm = x0 + 250
    plan.way([(xm, y0 + 30), (xm, y0 + 470)], tags('highway=primary lanes=4', name='Вулиця над проїздами'))
    link(plan, i, j, xm, y0 + 470)
    name = f'{code(i, j)} проїзд 16 м'
    ya = yc - 130
    plan.way([(x0 + 60, yc), (x0 + 60, ya), (xm - 8, ya)], tags('highway=residential', name=name))
    plan.way([(xm - 8, ya), (xm + 8, ya)], tags('highway=residential ' + TUNNEL, name=name))
    plan.way([(xm + 8, ya), (x0 + 440, ya), (x0 + 440, yc)], tags('highway=residential', name=name))
    mouth_view(plan, i, j, 235)


def tunnel_level(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=secondary lanes=2', 'тунель під рівною землею', [(125, 375, TUNNEL)])
    plan.rect(x0 + 140, yc - 60, x0 + 360, yc + 60, tags('leisure=park', name='Сквер над тунелем'))
    mouth_view(plan, i, j, 125)


def tunnel_river(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=primary lanes=2', 'тунель під річкою', [(150, 350, TUNNEL)])
    river(plan, [(x0 + 250, y0 + 20), (x0 + 250, y0 + 480)], 32., 80., name='Над тунелем')
    mouth_view(plan, i, j, 150)


# --- row 6: arches, banks, pipes ---------------------------------------------------------------
def arch_houses(plan, i, j, x0, y0, yc):
    # the same arch tagged three ways, as OSM has it: a passage, a tunnel, a tunnel on a layer
    avenue(plan, i, j, 'highway=residential', 'арки крізь будинки')
    back = yc + 170
    plan.way([(x0 + 60, back), (x0 + 440, back)], tags('highway=service', name='За будинком'))
    for dx, spec in ((120, 'tunnel=building_passage'), (250, 'tunnel=yes'), (380, 'tunnel=yes layer=-1')):
        x = x0 + dx
        plan.way([(x, yc), (x, yc + 62)], tags('highway=service'))
        plan.way([(x, yc + 62), (x, yc + 78)], tags('highway=service ' + spec, name=f'{code(i, j)} {spec}'))
        plan.way([(x, yc + 78), (x, back)], tags('highway=service'))
    plan.rect(x0 + 70, yc + 62, x0 + 430, yc + 78, tags('building=apartments building:levels=5', name='Дім з арками'))
    # a long passage under a deep block, and a covered way
    plan.way([(x0 + 250, yc), (x0 + 250, yc - 50)], tags('highway=service'))
    plan.way([(x0 + 250, yc - 50), (x0 + 250, yc - 110)], tags('highway=service tunnel=yes', name=f'{code(i, j)} довга арка'))
    plan.way([(x0 + 250, yc - 110), (x0 + 250, yc - 170), (x0 + 60, yc - 170), (x0 + 60, yc)], tags('highway=service'))
    plan.rect(x0 + 200, yc - 110, x0 + 300, yc - 50, tags('building=retail building:levels=3', name='Пасаж'))


def arch_rails(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=secondary lanes=2', 'проїзд під насипом колії', [(222, 278, TUNNEL)])
    xr = x0 + 250
    plan.way([(xr, y0 + 10), (xr, y0 + 490)], tags('railway=rail gauge=1520 embankment=yes usage=main'))

    def bank(x, y):
        import numpy as np
        return 8. * z.smooth_(1 - np.abs(x - xr) / 34.) * z.smooth_((y - y0) / 50.) * z.smooth_((y0 + TILE - y) / 50.)
    relief(plan, bank)
    mouth_view(plan, i, j, 222)
    # the same under rails the land does not rise for: a tunnel by its tag alone
    name = f'{code(i, j)} під колією без насипу'
    xb, ya = x0 + 120, yc - 150
    plan.way([(xb, y0 + 10), (xb, y0 + 240)], tags('railway=rail gauge=1520 service=spur'))
    plan.way([(x0 + 40, yc), (x0 + 40, ya), (xb - 12, ya)], tags('highway=residential', name=name))
    plan.way([(xb - 12, ya), (xb + 12, ya)], tags('highway=residential ' + TUNNEL, name=name))
    plan.way([(xb + 12, ya), (x0 + 200, ya), (x0 + 200, yc)], tags('highway=residential', name=name))


def arch_pipes(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=tertiary sidewalk=both', 'труба, підземний перехід, брід')
    xr = x0 + 150
    plan.way([(xr - 40, y0 + 470), (xr, yc + 25)], tags('waterway=stream', name='Струмок у трубі'))
    plan.way([(xr, yc + 25), (xr, yc - 25)], tags('waterway=stream tunnel=culvert layer=-1'))
    plan.way([(xr, yc - 25), (xr + 40, y0 + 30)], tags('waterway=stream'))
    z._bed(plan, [(xr - 40, y0 + 470), (xr, yc + 25), (xr, yc - 25), (xr + 40, y0 + 30)], 35., 2.)
    # a subway for people under the avenue, steps down to it at both ends
    xp = x0 + 320
    plan.way([(xp, yc + 40), (xp, yc + 16)], tags('highway=steps incline=down'))
    plan.way([(xp, yc + 16), (xp, yc - 16)], tags('highway=footway tunnel=yes layer=-1', name='Підземний перехід'))
    plan.way([(xp, yc - 16), (xp, yc - 40)], tags('highway=steps incline=up'))
    plan.way([(xp - 60, yc + 40), (xp + 60, yc + 40)], tags('highway=footway'))
    plan.way([(xp - 60, yc - 40), (xp + 60, yc - 40)], tags('highway=footway'))
    # a ford on a track
    plan.way([(x0 + 60, yc), (x0 + 60, yc - 150), (xr + 60, yc - 150)], tags('highway=track tracktype=grade3'))
    plan.node(xr + 22, yc - 150, tags('ford=yes'))


def arch_gallery(plan, i, j, x0, y0, yc):
    avenue(plan, i, j, 'highway=secondary lanes=2', 'галерея на схилі й крита дорога',
           [(130, 300, 'tunnel=avalanche_protector'), (360, 440, 'covered=yes')])

    def slope(x, y):
        import numpy as np
        return np.clip(.3 * (y - yc), -FLOOR, 40.) * z._within(x0, y0, x, y)
    relief(plan, slope)


def arch_both(plan, i, j, x0, y0, yc):
    # off a bridge straight into a tunnel: an abutment and a mouth 30 m apart
    avenue(plan, i, j, 'highway=secondary lanes=2', 'з мосту в тунель', [(80, 220, BRIDGE), (250, 420, TUNNEL)])

    def f(x, y):
        import numpy as np
        gorge = -FLOOR * z.smooth_(1 - np.abs(x - (x0 + 150)) / 85.)
        ridge = 40. * z.smooth_(1 - np.abs(x - (x0 + 335)) / 110.)
        return (gorge + ridge) * z.smooth_((y - y0) / 60.) * z.smooth_((y0 + TILE - y) / 60.)
    relief(plan, f)
    plan.way([(x0 + 150, y0 + 60), (x0 + 150, y0 + 440)], tags('waterway=stream'))
    mouth_view(plan, i, j, 250, back=50.)


# A row from the south, a tile from the west: (title, English title, what builds it).
ROWS = (
    (('Місток через струмок', 'Small bridge over a stream', water_stream),
     ('Міст через річку', 'River bridge', water_river),
     ('Міст через заплаву', 'Bridge over a flood plain', water_plain),
     ('Два мости поруч', 'Twin carriageway bridges', water_dual),
     ('Міст у кривій, навскіс', 'Skew bridge on a curve', water_skew)),
    (('Шляхопровід над вулицею', 'Overpass over a street', over_street),
     ('Шляхопровід над магістраллю', 'Overpass over a divided road', over_divided),
     ('Шляхопровід над колією', 'Overpass over the rails', over_rails),
     ('Три рівні', 'Three levels', over_stack),
     ('Міст із з’їздами', 'Bridge with slip roads', over_slips)),
    (('Віадук над долиною', 'Viaduct over a valley', relief_viaduct),
     ('Високий віадук', 'High viaduct', relief_deep),
     ('Береги різної висоти', 'Banks of two heights', relief_banks),
     ('Віадук на косогорі', 'Hillside viaduct', relief_hillside),
     ('Міст через острів', 'Bridge over an island', relief_island)),
    (('Балковий міст і віадук', 'Beam bridge and viaduct', kinds('bridge=yes bridge:structure=beam', 'bridge=viaduct', 'балковий міст і віадук')),
     ('Арка й ферма', 'Arch and truss', kinds('bridge=yes bridge:structure=arch', 'bridge=yes bridge:structure=truss', 'арковий міст і ферма')),
     ('Висячий і вантовий', 'Suspension and cable-stayed',
      kinds('bridge=yes bridge:structure=suspension', 'bridge=yes bridge:structure=cable-stayed', 'висячий і вантовий')),
     ('Розвідний і критий', 'Movable and covered',
      kinds('bridge=movable bridge:movable=bascule', 'bridge=covered covered=yes', 'розвідний і критий')),
     ('Мости для людей', 'Bridges for people', kinds_foot)),
    (('Тунель під хребтом', 'Tunnel under a ridge', tunnel_ridge),
     ('Довгий тунель у кривій', 'Long tunnel round a bend', tunnel_pieces),
     ('Проїзд під вулицею', 'Underpass under a street', tunnel_street),
     ('Тунель під рівною землею', 'Tunnel under level ground', tunnel_level),
     ('Тунель під річкою', 'Tunnel under a river', tunnel_river)),
    (('Арки крізь будинки', 'Arches through houses', arch_houses),
     ('Проїзд під колією', 'Underpass under the rails', arch_rails),
     ('Труба, перехід, брід', 'Culvert, subway, ford', arch_pipes),
     ('Галерея й крита дорога', 'Gallery and covered road', arch_gallery),
     ('З мосту в тунель', 'Off a bridge into a tunnel', arch_both)),
)


def build(plan):
    i0, i1, j0, j1 = BLOCK[ZONE]['tiles']
    level(plan)
    for row, tiles in enumerate(ROWS):
        j = j0 + row
        for col, (title, title_en, make) in enumerate(tiles):
            i = i0 + col
            x0, y0, yc = z.register(plan, i, j, ZONE, title, title_en)
            z.open_ground(plan, i, j)
            make(plan, i, j, x0, y0, yc)
            side_view(plan, i, j)
    # every row's road runs on from the last; a street down each side of the block joins the rows,
    # and the two southern rows carry on from the mountains' two (their avenues end at this edge)
    ya, yb = z.centre_y(j0), z.centre_y(j1 - 1)
    for x in (i0 * TILE + 8, i1 * TILE - 8):
        plan.way([(x, ya), (x, yb)], tags('highway=residential', name='Об’їзд мостів'))
    plan.zones.append({'id': ZONE, 'title': 'Мости й тунелі', 'titleEn': 'Bridges and tunnels',
                       'start': (i0 * TILE + 30, ya - 1.6)})
