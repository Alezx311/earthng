"""The proving ground's thanks tile (proving_ground.BLOCKS 'thanks'): the wall of supporters.

The island's north-west corner of the ring road, the one tile of the corridor between the main
grid, the snow and the mountains that is a block of its own. An alley of limes leaves the ring
road at its corner and runs north-west to a square; across the square stands a billboard tagged
operator = OPERATOR, which the generator draws as the wall of supporters: the names of
mod/lua/ge/extensions/e2r/supporters.lua in letters on a board that grows with the list
(generator.lua BLD.supportersWall). The names are the planet's, not the pack's: a new name is a
line in supporters.lua and a planet rebuild, and this pack stays as it is.

Round the wall, the square and the alley fly the flags of the world's countries, a pole each
(flag_art.CODES: the members of the United Nations and its observers, without Russia), so that
whoever comes finds their own.
"""
import math

import flag_art
from proving_ground import BLOCK, GRID, RING, TILE, code, tags
import proving_zones as z

ZONE = 'thanks'
OPERATOR = 'EarthNG supporters'     # generator.lua BLD.PIN.thanks.operator
I, J = BLOCK[ZONE]['tiles'][0], BLOCK[ZONE]['tiles'][2]
CODE = code(I, J)
ALLEY = 190.            # m from the ring road's corner to the square
SQUARE = 46.            # half the square's street, along the wall
BACK = 17.              # m from that street's middle to the wall (the generator turns a board
#                         to a road within 25 m of it)
STEP = 3.4              # m between two flagpoles
POLE = 9                # m, a pole's height


def poles():
    """Where the flagpoles stand, (along, across) of the alley, the first by the wall: beside the
    wall across the square, round the square's near side, down both sides of the alley, then in
    arcs behind the wall, each arc from its middle outwards."""
    out = []
    for k in range(9):
        for side in (-1, 1):
            out.append((ALLEY + 7, side * (16 + k * STEP)))
    for k in range(11):
        for side in (-1, 1):
            out.append((ALLEY - 7, side * (11 + k * STEP)))
    d = ALLEY - 12
    while d >= 20:
        for side in (-1, 1):
            out.append((d, side * 6.8))
        d -= STEP
    for radius in (30., 36., 42.):
        n = int(math.radians(78) * radius / STEP)
        for k in range(n + 1):
            for side in ((1,) if k == 0 else (-1, 1)):
                a = side * k * STEP / radius
                out.append((ALLEY + BACK + radius * math.cos(a), radius * math.sin(a)))
    return out


def build(plan):
    x0, y0, _ = z.register(plan, I, J, ZONE, 'Алея подяки', 'Supporters’ wall', 'advertising=billboard operator=EarthNG supporters')
    z.open_ground(plan, I, J)
    # the ring road's north-west corner: where its north side ends and its west side begins
    around = (GRID[0] - RING, GRID[1] - RING, GRID[2] + RING, GRID[3] + RING)
    corner = z._round(plan, 'n', around, 200.)[-1]
    u = (-math.sqrt(.5), math.sqrt(.5))         # along the alley, north-west
    v = (math.sqrt(.5), math.sqrt(.5))          # across it, to the right of a car driving in

    def at(along, across=0.):
        return corner[0] + u[0] * along + v[0] * across, corner[1] + u[1] * along + v[1] * across

    plan.way([corner, at(ALLEY * .5), at(ALLEY)],
             tags('highway=residential lanes=2 sidewalk=both lit=yes surface=asphalt', name=f'{CODE} Алея подяки', name__en=f'{CODE} Supporters’ Alley'))
    plan.way([at(ALLEY, -SQUARE), at(ALLEY), at(ALLEY, SQUARE)],
             tags('highway=residential sidewalk=both lit=yes surface=paving_stones', name='Площа подяки', name__en='Supporters’ Square'))
    # limes either side of the alley, a mown lawn behind the square (no trees before the wall), the wall across it
    for side in (-1, 1):
        plan.way([at(18, side * 9.5), at(ALLEY - 14, side * 9.5)], tags('natural=tree_row leaf_type=broadleaved species=Tilia'))
    plan.area([at(ALLEY + 6, -SQUARE - 10), at(ALLEY + 6, SQUARE + 10), at(ALLEY + 60, SQUARE + 10), at(ALLEY + 60, -SQUARE - 10)],
              tags('landuse=grass', name='Сквер подяки'))
    plan.node(*at(ALLEY + BACK), tags('advertising=billboard support=ground', operator=OPERATOR,
                                      name='Стіна подяки', name__en='Wall of supporters'))
    for side in (-1, 1):
        for k in range(3):
            plan.node(*at(ALLEY - 13, side * (13 + k * 11)), tags('amenity=bench'))
    # the flags of the world's countries (flag_art.CODES: Ukraine's first, by the wall), a pole each
    for (along, across), country in zip(poles(), ['ua'] + [c for c in flag_art.CODES if c != 'ua']):
        plan.node(*at(along, across), tags('man_made=flagpole', country=country.upper(), height=POLE))
    # the car lands on the alley, driving in; the cameras look at the wall
    tile = plan.tiles[CODE]
    wall = at(ALLEY + BACK)
    tile['at'], tile['yaw'] = at(34, 1.6), 315
    tile['views'] = [{'id': 'street', 'eye': (*at(40, 3), 2.4), 'target': (*wall, 8.), 'fov': 55},
                     {'id': 'over', 'eye': (*at(ALLEY - 150, 0), 110), 'target': (*wall, 4.), 'fov': 60},
                     {'id': 'top', 'eye': (x0 + 250, y0 + 249, 520), 'target': (x0 + 250, y0 + 250, 0), 'fov': 55},
                     {'id': 'wall', 'eye': (*at(ALLEY - 42, 0), 5.), 'target': (*wall, 8.5), 'fov': 58}]
    plan.zones.append({'id': ZONE, 'title': 'Алея подяки', 'titleEn': 'Supporters’ wall', 'start': tile['at']})
