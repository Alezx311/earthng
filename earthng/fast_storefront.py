"""Shop fronts drawn from numbers at art build time: no photograph, no game file.

A storefront is two bays of 3 m x 3 m per class of place (generator.lua BLD.FRONT): a window and
one with the door. Each is built the way a real one is seen: a lit room behind, the street and
sky in the glass over it, then frames, a plinth, door handles, stickers and dirt. The room is drawn
apart, so by night it alone glows. Everything comes from a seed by class and bay: the same build
gives the same art.
"""
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

CELL = 512                  # px of a bay
METRE = CELL / 3.0
COLS = 4                    # atlas 4 x 4 cells, a class's window then its door
CLASSES = ('shop', 'pharmacy', 'bank', 'cafe', 'bar', 'car_repair', 'tyres', 'car_wash')
SHUTTERED = ('car_repair', 'tyres', 'car_wash')
ANTHRACITE, SILVER = (56, 59, 64), (176, 180, 184)
FRAMES = {'shop': SILVER, 'pharmacy': SILVER, 'bank': ANTHRACITE, 'cafe': (70, 48, 32), 'bar': (38, 30, 28),
          'car_repair': ANTHRACITE, 'tyres': ANTHRACITE, 'car_wash': SILVER}
ROOMS = {'shop': (226, 222, 208), 'pharmacy': (240, 244, 242), 'bank': (46, 70, 108), 'cafe': (112, 74, 46),
         'bar': (34, 24, 24), 'car_repair': (84, 84, 80), 'tyres': (92, 90, 86), 'car_wash': (120, 150, 170)}
GOODS = {'shop': ((206, 52, 44), (240, 196, 60), (60, 130, 200), (70, 160, 90), (235, 235, 230), (232, 124, 44)),
         'pharmacy': ((252, 252, 250), (120, 190, 150), (90, 150, 210), (236, 150, 170), (214, 226, 232)),
         'bar': ((180, 110, 30), (80, 130, 70), (210, 170, 70), (120, 40, 30), (200, 200, 190))}
POSTERS = {'shop': (('АКЦІЯ', (214, 38, 40), (255, 255, 255)), ('-20%', (250, 208, 40), (190, 20, 24))),
           'pharmacy': (('24/7', (0, 128, 92), (255, 255, 255)),),
           'bank': (('КАРТКИ', (240, 240, 236), (30, 50, 100)), ('ВАЛЮТА', (30, 50, 100), (255, 255, 255))),
           'cafe': (('КАВА', (34, 36, 34), (236, 230, 214)), ('МЕНЮ', (34, 36, 34), (236, 230, 214))),
           'bar': (('ПИВО', (30, 26, 24), (244, 170, 50)),),
           'tyres': (('ШИНИ', (250, 208, 40), (30, 30, 30)),),
           'car_repair': (('ТО', (214, 38, 40), (255, 255, 255)),),
           'car_wash': (('МИЙКА', (20, 110, 180), (255, 255, 255)),)}


def y_of(z):
    """Row of a height over the pavement, in m."""
    return int(round((3 - z) * METRE))


def seed(*parts):
    return zlib.crc32('/'.join(map(str, parts)).encode('utf8'))


def shelves(d, x0, x1, rng, goods, top=2.25, step=.42):
    z = .55
    while z < top:
        y = y_of(z)
        x = x0
        while x < x1:
            w = int(rng.integers(10, 26))
            h = int(rng.integers(26, int(step * METRE) - 8))
            colour = goods[int(rng.integers(len(goods)))]
            d.rectangle((x, y - h, x + w - 2, y), fill=colour)
            d.rectangle((x, y - h, x + w - 2, y - h + 3), fill=tuple(min(255, c + 30) for c in colour))
            x += w
        d.rectangle((x0, y, x1, y + 5), fill=(190, 190, 186))
        z += step


def room(kind, rng):
    """The lit room behind the glass, a window's width of it."""
    wall = ROOMS[kind]
    im = Image.new('RGB', (CELL, CELL), wall)
    d = ImageDraw.Draw(im)
    d.rectangle((0, y_of(.35), CELL, CELL), fill=tuple(int(c * .62) for c in wall))
    if kind in GOODS and kind != 'bar':
        shelves(d, 12, CELL - 12, rng, GOODS[kind])
        for x in range(30, CELL, 150):                         # strip lights
            d.rectangle((x, y_of(2.72), x + 96, y_of(2.67)), fill=(255, 255, 250))
    elif kind == 'bar':
        for z in (1.5, 2.0):
            shelves(d, 40, CELL - 40, rng, GOODS['bar'], top=z + .01, step=.5)
        d.rectangle((20, y_of(1.1), CELL - 20, y_of(.3)), fill=(58, 34, 24))
        for x in range(70, CELL, 120):
            d.ellipse((x - 12, y_of(2.45), x + 12, y_of(2.3)), fill=(255, 196, 110))
    elif kind == 'bank':
        d.rectangle((30, y_of(1.15), CELL - 30, y_of(.3)), fill=(150, 152, 158))
        d.rectangle((30, y_of(1.2), CELL - 30, y_of(1.14)), fill=(206, 208, 212))
        d.rectangle((150, y_of(1.9), 280, y_of(.3)), fill=(64, 68, 74))
        d.rectangle((170, y_of(1.75), 260, y_of(1.35)), fill=(90, 190, 230))
        d.rectangle((176, y_of(1.28), 254, y_of(1.12)), fill=(170, 172, 176))
        for x in range(30, CELL, 170):
            d.rectangle((x, y_of(2.75), x + 110, y_of(2.7)), fill=(232, 240, 255))
    elif kind == 'cafe':
        for x in range(0, CELL, 26):                           # boards
            d.line((x, 0, x, y_of(.35)), fill=tuple(int(c * .8) for c in wall), width=2)
        d.rectangle((60, y_of(2.3), 240, y_of(1.5)), fill=(34, 36, 34))
        for x in (120, 380):
            d.rectangle((x - 62, y_of(.78), x + 62, y_of(.72)), fill=(70, 44, 28))
            d.rectangle((x - 5, y_of(.72), x + 5, y_of(.3)), fill=(46, 32, 24))
            for side in (-1, 1):
                sx = x + side * 86
                d.rectangle((sx - 18, y_of(.48), sx + 18, y_of(.43)), fill=(58, 38, 26))
                d.rectangle((sx - 3, y_of(.43), sx + 3, y_of(.3)), fill=(46, 32, 24))
                d.rectangle((sx + side * 15 - 3, y_of(.95), sx + side * 15 + 3, y_of(.43)), fill=(58, 38, 26))
        for x in (120, 250, 380):
            d.line((x, 0, x, y_of(2.15)), fill=(30, 26, 24), width=2)
            d.ellipse((x - 26, y_of(2.2), x + 26, y_of(2.0)), fill=(255, 214, 140))
    elif kind == 'tyres':
        for col, x in enumerate(range(70, CELL - 40, 124)):
            for row in range(int(rng.integers(4, 7))):
                cy = y_of(.42 + row * .3)
                d.ellipse((x - 54, cy - 24, x + 54, cy + 24), fill=(26, 26, 28), outline=(60, 60, 62), width=4)
                d.ellipse((x - 26, cy - 11, x + 26, cy + 11), fill=(44, 44, 46))
        for x in range(30, CELL, 180):
            d.rectangle((x, y_of(2.75), x + 110, y_of(2.7)), fill=(240, 240, 232))
    else:
        for x in range(30, CELL, 180):
            d.rectangle((x, y_of(2.75), x + 110, y_of(2.7)), fill=(240, 240, 232))
    return im


def glass_over(lit, rng, tint=(1., 1., 1.)):
    """The room through a pane: dimmed by the glass, the sky and the street over it (0..1)."""
    h, w = lit.shape[:2]
    t = np.linspace(0, 1, h)[:, None]
    sky = np.array((.70, .79, .90))
    reflection = sky * (1 - t) ** 1.6 + np.array((.30, .32, .33)) * t ** 2 * .55
    street = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(street)
    x = int(rng.integers(-60, 0))
    while x < w:                                                # the far side of the street
        width = int(rng.integers(70, 180))
        d.rectangle((x, int(h * rng.uniform(.28, .5)), x + width, int(h * .8)), fill=int(rng.integers(50, 110)))
        x += width + int(rng.integers(0, 16))
    mirrored = np.asarray(street.filter(ImageFilter.GaussianBlur(7)), float)[..., None] / 255
    streak = np.zeros((h, w))
    for _ in range(3):
        at = rng.uniform(-.3, 1.0)
        wide = rng.uniform(.04, .12)
        xx, yy = np.meshgrid(np.linspace(0, 1, w), np.linspace(0, 1, h))
        streak += np.clip(1 - np.abs(xx + yy * .55 - at) / wide, 0, 1) * rng.uniform(.04, .1)
    out = lit * np.array(tint) * .72 + reflection[:, None, :] * .34 - mirrored * .22 + streak[..., None]
    return np.clip(out, 0, 1)


def shutter(kind, door, rng):
    """A roller shutter's ribs from the lintel down, with a person's door in a door bay."""
    im = Image.new('RGB', (CELL, CELL), (150, 154, 158))
    d = ImageDraw.Draw(im)
    base = int(rng.integers(150, 186))
    for y in range(y_of(2.9), y_of(.03), 12):
        d.rectangle((0, y, CELL, y + 8), fill=(base, base + 2, base + 5))
        d.rectangle((0, y + 8, CELL, y + 11), fill=(base - 52, base - 50, base - 48))
    d.rectangle((CELL // 2 - 26, y_of(.42), CELL // 2 + 26, y_of(.36)), fill=(60, 62, 64))
    if door:
        x0, x1 = int(1.0 * METRE), int(1.95 * METRE)
        d.rectangle((x0, y_of(2.15), x1, y_of(.02)), fill=(92, 104, 118), outline=(50, 54, 58), width=6)
        d.rectangle((x0 + 22, y_of(2.0), x1 - 22, y_of(1.15)), fill=(70, 86, 104))
        d.rectangle((x1 - 22, y_of(1.08), x1 - 12, y_of(.96)), fill=(200, 200, 196))
    return im


def sticker(im, box, word, fill, ink, font):
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    d.rectangle(box, fill=fill)
    size = max(10, int((y1 - y0) * .62))
    type_face = font(size)
    while type_face.getlength(word) > (x1 - x0) * .86 and size > 8:
        size -= 2
        type_face = font(size)
    width = type_face.getlength(word)
    top = type_face.getbbox(word)
    d.text((x0 + ((x1 - x0) - width) / 2, y0 + ((y1 - y0) - (top[3] - top[1])) / 2 - top[1]), word, fill=ink, font=type_face)


def bay(kind, door, font):
    """(colour, glow) of one bay, PIL RGB images of CELL x CELL."""
    rng = np.random.default_rng(seed(kind, door))
    glow = Image.new('RGB', (CELL, CELL), (0, 0, 0))
    frame = FRAMES[kind]
    rail = int(.05 * METRE)
    if kind in SHUTTERED and (door or kind != 'tyres'):
        im = shutter(kind, door, rng)
    else:
        lit = room(kind, rng).filter(ImageFilter.GaussianBlur(1.4))
        array = np.asarray(lit, float) / 255
        fall = (1.08 - .3 * np.linspace(0, 1, CELL))[:, None, None]      # lit from the ceiling
        array = np.clip(array * fall, 0, 1)
        tint = (.92, .96, 1.) if kind == 'bank' else (1., 1., 1.)
        im = Image.fromarray((glass_over(array, rng, tint) * 255).astype('uint8'))
        glow.paste(Image.fromarray((array * 255).astype('uint8')).point(lambda v: round(v * .9)))
        d = ImageDraw.Draw(im)
        d.rectangle((0, y_of(2.42), CELL, y_of(2.3)), fill=frame)         # transom under the fanlight
        for box in ((0, 0, rail, CELL), (CELL - rail, 0, CELL, CELL)):
            d.rectangle(box, fill=frame)
        d.rectangle((0, y_of(3), CELL, y_of(2.92)), fill=frame)
        if door:
            for x0, x1 in ((.28, 1.5), (1.5, 2.72)):
                a, b = int(x0 * METRE), int(x1 * METRE)
                d.rectangle((a, y_of(2.3), b, y_of(.03)), outline=frame, width=rail)
            for x, side in ((1.38, 1), (1.62, -1)):                        # long pull bars
                a = int(x * METRE)
                d.rectangle((a - 4, y_of(1.45), a + 4, y_of(.7)), fill=(216, 218, 220))
            d.rectangle((int(.28 * METRE), y_of(.03), int(2.72 * METRE), CELL), fill=(70, 72, 74))
            sticker(im, (int(.5 * METRE), y_of(1.72), int(1.28 * METRE), y_of(1.5)), 'ВІДЧИНЕНО', (250, 250, 246), (20, 120, 70), font)
        else:
            d.rectangle((CELL // 2 - rail // 2, y_of(2.3), CELL // 2 + rail // 2, y_of(.32)), fill=frame)
            d.rectangle((0, y_of(.38), CELL, y_of(.3)), fill=frame)
            # the plinth: dark polished stone, a speckle in it
            d.rectangle((0, y_of(.3), CELL, CELL), fill=(62, 62, 66))
            specks = np.asarray(im, float)
            noise = rng.normal(0, 7, (CELL - y_of(.3), CELL, 1))
            specks[y_of(.3):] = np.clip(specks[y_of(.3):] + noise, 0, 255)
            im = Image.fromarray(specks.astype('uint8'))
            mask = Image.new('L', (CELL, CELL), 255)
            ImageDraw.Draw(mask).rectangle((0, y_of(.3), CELL, CELL), fill=0)
            glow = Image.composite(glow, Image.new('RGB', (CELL, CELL)), mask)
    posters = POSTERS.get(kind, ())
    if posters and not door:
        word, fill, ink = posters[int(rng.integers(len(posters)))]
        if kind == 'pharmacy':
            d = ImageDraw.Draw(im)
            c, y, r = int(.75 * METRE), y_of(1.6), int(.42 * METRE)
            d.ellipse((c - r, y - r, c + r, y + r), fill=(250, 252, 250))
            for box in ((c - r * .62, y - r * .22, c + r * .62, y + r * .22), (c - r * .22, y - r * .62, c + r * .22, y + r * .62)):
                d.rectangle(box, fill=(0, 150, 90))
            ImageDraw.Draw(glow).ellipse((c - r, y - r, c + r, y + r), fill=(150, 190, 170))
        box = (int(1.72 * METRE), y_of(1.52), int(2.72 * METRE), y_of(.92))
        sticker(im, box, word, fill, ink, font)
    array = np.asarray(im, float)
    # dirt: the grey of the street creeping up from the pavement, a little grime all over
    climb = (np.clip((np.linspace(0, 1, CELL) - .78) / .22, 0, 1) ** 2)[:, None, None]
    array = array * (1 - climb * .28) + np.array((88, 84, 78)) * climb * .28
    array += rng.normal(0, 2.2, (CELL, CELL, 1))
    return Image.fromarray(np.clip(array, 0, 255).astype('uint8')), glow


def art(r, font):
    """storefront.color.png and storefront.glow.png into r."""
    size = CELL * COLS
    colour, glow = Image.new('RGB', (size, size)), Image.new('RGB', (size, size))
    for n, kind in enumerate(CLASSES):
        for door in (0, 1):
            k = n * 2 + door
            at = (k % COLS * CELL, k // COLS * CELL)
            a, b = bay(kind, door, font)
            colour.paste(a, at)
            glow.paste(b, at)
    colour.save(r / 'storefront.color.png')
    glow.save(r / 'storefront.glow.png')
