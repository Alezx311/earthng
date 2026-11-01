"""Facades drawn over CC0 material photos at art build, and the plain sheets of those materials.

The Panelka pack gave the world four photographs of walls, tinted into a family each. Here a facade
is built up the way fast_storefront builds a shop: a wall material (fetch_textures.MATERIAL_SETS)
and its paint, then openings with a room, curtains and the sky in the glass, frames, lintels,
sills, string courses, and last the dirt and the rain that run down from them. A height map goes
with the drawing: reveals and hoods shade the colour and tilt the normal map from one source.

A repeat is 12 m (BAYS x BAYS cells of 3 m, a floor each), so a block does not show the same four
windows. Everything comes from a seed by name: the same build gives the same art. Row 0 is the top
of the wall, as fast_photo.wall_image hands it to fast_art.photo_real. Windows of one LAYOUT stand
in the same boxes, so a layout's night glow serves every facade drawn on it (fast_packs).
"""
import numpy as np
from PIL import Image, ImageDraw

import fast_photo as photo
import fast_storefront as shop

CELL = 512                  # px of a 3 m cell
BAYS = 4
PX = CELL * BAYS
METRE = CELL / 3.0
REPEAT_M = 3.0 * BAYS
NORMAL_PX = 1024            # a normal map carries less than a colour map at this size
END_PX, END_M = 1024, 6.0   # a blank end wall, as the other end walls

# window box in parts of a cell, row 0 at the top of the floor: (left, top, right, bottom)
LAYOUTS = {'std': (.24, .20, .76, .68),         # 1.56 x 1.44 m, a Soviet block's
           'tall': (.30, .10, .70, .72),        # 1.2 x 1.86 m, tenements, stalinky, sash windows
           'wide': (.14, .16, .86, .72),        # 2.16 x 1.68 m, a new block's
           'small': (.35, .24, .65, .60)}       # 0.9 x 1.08 m, hot countries

WHITE, CREAM, STONE, IRON = (232, 230, 222), (224, 214, 192), (178, 174, 164), (42, 42, 44)
PHOTO = 'photo'             # a window cut from a Panelka panel (std layout only)


def _s(wall, metres, layout, windows, paint=None, trim=(), sill=STONE, dirt=.5, rain=.5, band=None, **more):
    return {'wall': wall, 'metres': metres if isinstance(metres, tuple) else (metres, metres), 'layout': layout,
            'windows': windows, 'paint': paint, 'trim': trim, 'sill': sill, 'dirt': dirt, 'rain': rain,
            'band': band, **more}


# wall_<name>. brk_ and pls_ as the Lua generator reads them: brick and render blocks, with their
# balconies, downpipes, plinth and end walls. paint: (colour, amount); windows: (kind, share).
STYLES = {
    # Soviet and post-Soviet blocks, old windows and their replacements side by side
    'brk_d_sil': _s('mat_brick_silicate', 2.0, 'std', ((PHOTO, .55), ('wood', .1), ('pvc', .35)), paint=((222, 216, 202), .55),
                    dirt=.55, rain=.7),
    'brk_d_red': _s('mat_brick_red', 2.0, 'std', ((PHOTO, .5), ('pvc', .4), ('pvc3', .1)), trim=('lintel',), dirt=.45),
    'brk_d_old': _s('mat_brick_old', 2.0, 'tall', (('wood', .6), ('pvc', .4)), trim=('arch',), band=((150, 92, 72), .2), dirt=.6, rain=.6),
    'pls_d_dash': _s('mat_dash', 1.5, 'std', ((PHOTO, .6), ('pvc', .4)), paint=((176, 170, 156), .6), dirt=.6, rain=.8),
    'pls_d_stalin': _s('mat_render', 2.5, 'tall', (('wood', .55), ('pvc', .45)), paint=((222, 200, 160), .9),
                       trim=('surround', 'hood'), sill=CREAM, band=((236, 222, 192), .22), dirt=.45, rain=.6),
    'pls_d_stalin_red': _s('mat_render', 2.5, 'tall', (('wood', .5), ('pvc', .5)), paint=((184, 112, 84), .9),
                           trim=('surround', 'hood'), sill=CREAM, band=((226, 206, 172), .22), trim_colour=(226, 206, 172), dirt=.45, rain=.6),
    'pls_d_aged': _s('mat_render_yellow', 2.5, 'tall', (('wood', .7), ('pvc', .3)), trim=('surround',), sill=CREAM,
                     band=((206, 190, 140), .16), dirt=.8, rain=.9),
    'pls_d_flake': _s('mat_render_flaking', 2.5, 'tall', (('wood', .7), ('pvc', .3)), trim=('surround',), sill=STONE,
                      band=((186, 184, 174), .16), dirt=.8, rain=.9),
    'pls_d_new': _s('mat_render', 2.5, 'wide', (('dark', .8), ('pvc3', .2)), paint=((214, 204, 184), .9), sill=(70, 72, 76),
                    trim=('joints', 'pier'), pier=(136, 100, 76), dirt=.2, rain=.25),
    'brk_d_new': _s('mat_clinker', 2.0, 'wide', (('dark', .75), ('pvc3', .25)), sill=(70, 72, 76), trim=('lintel_dark',), dirt=.15, rain=.2),
    # western and northern Europe
    'pls_d_euro': _s('mat_render', 2.5, 'std', (('pvc', .8), ('dark', .2)), paint=((226, 222, 212), .95), sill=(120, 122, 124),
                     dirt=.25, rain=.4),
    'pls_d_euro_warm': _s('mat_render', 2.5, 'tall', (('pvc', .9), ('pvc3', .1)), paint=((216, 196, 160), .95), sill=CREAM, trim=('surround',),
                          dirt=.3, rain=.4),
    'pls_d_ashlar': _s('mat_ashlar', 2.0, 'tall', (('casement', 1.),), paint=((206, 196, 176), .45), trim=('hood', 'rail'), sill=CREAM,
                       band=((214, 204, 184), .28), dirt=.5, rain=.6),
    # British, American and Pacific brick
    'brk_d_stock': _s('mat_brick_stock', 2.0, 'tall', (('sash', 1.),), trim=('lintel_light',), sill=CREAM, dirt=.55, rain=.5),
    'brk_d_vic': _s('mat_brick_red', 2.0, 'tall', (('sash', .8), ('sash6', .2)), trim=('lintel_light',), sill=CREAM,
                    band=((206, 196, 176), .14), dirt=.4, rain=.5),
    'brk_d_dark': _s('mat_brick_dark', 1.9, 'tall', (('sash', .7), ('dark', .3)), trim=('lintel_light',), sill=STONE, dirt=.4, rain=.4),
    # the Mediterranean, with shutters; the same paint in hotter countries
    'pls_d_shutter': _s('mat_render', 2.5, 'tall', (('wood', 1.),), paint=((214, 160, 96), .92), trim=('shutters',), sill=CREAM,
                        shutter=(58, 92, 64), dirt=.55, rain=.6),
    'pls_d_white': _s('mat_render', 2.5, 'tall', (('wood', 1.),), paint=((238, 236, 226), .95), trim=('shutters',), sill=WHITE,
                      shutter=(44, 88, 130), dirt=.3, rain=.45),
    'pls_d_sand': _s('mat_sandstone', 3.0, 'small', (('alu', .6), ('alubars', .4)), paint=((204, 182, 146), .3), sill=CREAM, dirt=.4, rain=.15),
    'pls_d_adobe': _s('mat_adobe', 2.0, 'small', (('wood', .6), ('alubars', .4)), paint=((190, 154, 112), .7), sill=(164, 130, 96), dirt=.5, rain=.25),
    # Asia, Africa and Latin America: tile and stained concrete, aluminium and window bars
    'pls_d_tile': _s('mat_render', 2.5, 'wide', (('alu', .5), ('alubars', .5)), paint=((226, 224, 216), .95), sill=(190, 190, 184),
                     tile=True, dirt=.4, rain=.9, rust=.8),
    'pls_d_stain': _s('mat_concrete_stain', 2.5, 'wide', (('alu', .5), ('alubars', .5)), paint=((186, 180, 166), .35), sill=(150, 148, 140),
                      dirt=.8, rain=1., rust=.5),
    'pls_d_blue': _s('mat_render', 2.5, 'std', (('alu', .5), ('alubars', .5)), paint=((96, 160, 170), .9), sill=WHITE, dirt=.6, rain=.8, rust=.3),
    'pls_d_pink': _s('mat_render', 2.5, 'std', (('alu', .5), ('alubars', .5)), paint=((216, 136, 128), .9), sill=WHITE, dirt=.6, rain=.8, rust=.3),
}
# Soviet panels with one flat's insulation on them: the panel photo, then render over part of it
PATCHED = {'pnl_patch_grey': 'pnl_grey', 'pnl_patch_beige': 'pnl_beige', 'pnl_patch_white': 'pnl_white'}
PATCH_RENDER = ((222, 208, 176), (214, 190, 160), (232, 226, 206), (206, 208, 180), (224, 196, 172), (236, 234, 226))
# what these walls look like to the flat packs and by night: art that is there already
FLAT_LIKE = {'brk_d_sil': 'brk_white', 'brk_d_red': 'brk_red', 'brk_d_old': 'brk_red', 'brk_d_new': 'brk_red', 'brk_d_stock': 'brk_white',
             'brk_d_vic': 'brk_red', 'brk_d_dark': 'brk_red', 'pls_d_dash': 'pls_grey', 'pls_d_stalin': 'pls_cream',
             'pls_d_stalin_red': 'pls_peach', 'pls_d_aged': 'pls_yellow', 'pls_d_flake': 'pls_grey', 'pls_d_new': 'pls_cream',
             'pls_d_euro': 'pls_cream', 'pls_d_euro_warm': 'pls_yellow', 'pls_d_ashlar': 'pls_cream', 'pls_d_shutter': 'pls_yellow',
             'pls_d_white': 'pls_cream', 'pls_d_sand': 'pls_yellow', 'pls_d_adobe': 'pls_peach', 'pls_d_tile': 'pls_cream',
             'pls_d_stain': 'pls_grey', 'pls_d_blue': 'pls_blue', 'pls_d_pink': 'pls_peach', **PATCHED}


def like(name):
    """The older wall whose flat pack art stands in for this one (an end wall's stays an end wall's)."""
    bare = name[:-4] if name.endswith('_end') else name
    if bare not in FLAT_LIKE:
        return name
    other = FLAT_LIKE[bare]
    return other + '_end' if name.endswith('_end') and (other + '_end') in photo.PHOTO_WALLS else other


def boxes(layout, inner=.025):
    """(x0, y0, x1, y1) px of every window of a repeat on a layout, glass only."""
    x0, y0, x1, y1 = LAYOUTS[layout]
    return [((bx + x0 + inner) * CELL, (sy + y0 + inner) * CELL, (bx + x1 - inner) * CELL, (sy + y1 - inner) * CELL)
            for bx in range(BAYS) for sy in range(BAYS)]


def _load(path, metres, size, span, mode='RGB'):
    return np.asarray(photo.tiled(path, metres, size=size, span=span).convert(mode), np.float32) / 255


def material(st, size=PX, span=REPEAT_M):
    """(colour, normal) of the bare wall, 0..1 arrays: the photo at its real size and its paint.
    The normal stays OpenGL's (green up)."""
    src = photo.TEXTURES / st['wall']
    colour = _load(src / 'albedo.jpg', st['metres'], size, span)
    normal = _load(src / 'normal.jpg', st['metres'], size, span)
    if st['paint']:
        rgb, amount = st['paint']
        target = np.array(rgb, np.float32) / 255
        mean = colour.reshape(-1, 3).mean(0)
        grey = colour.mean(2, keepdims=True) / max(float(mean.mean()), .02)
        painted = grey ** .8 * target
        colour = colour * (1 - amount) + painted * amount
    return colour, normal


def _tiles(colour, height, rng):
    """Small facing tiles 12 x 6 cm, a little different each, in their joints."""
    w, h = max(2, round(.12 * METRE)), max(2, round(.06 * METRE))
    nx, ny = PX // w, PX // h
    jitter = rng.normal(1, .035, (ny + 1, nx + 2))
    yy, xx = np.mgrid[0:PX, 0:PX]
    row, col = yy // h, (xx + (yy // h % 2) * (w // 2)) // w
    colour *= jitter[np.minimum(row, ny), np.minimum(col, nx + 1)][..., None]
    joint = (yy % h == 0) | ((xx + (yy // h % 2) * (w // 2)) % w == 0)
    colour[joint] *= .78
    height[joint] -= .08


def _room(w, h, rng):
    """The room behind a window: dark, a curtain's folds or a blind over it (h x w x 3, 0..1)."""
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    base = np.array((rng.uniform(.1, .18), rng.uniform(.09, .15), rng.uniform(.08, .13)), np.float32)
    room = np.ones((h, w, 3), np.float32) * base * (1.15 - .35 * t)
    x = np.linspace(0, 1, w, dtype=np.float32)
    what = rng.random()
    if what < .5:                                   # tulle from a rail to the sill, folds in it
        folds = .5 + .5 * np.sin(x * rng.uniform(26, 44) + rng.uniform(0, 6)) * np.sin(x * rng.uniform(5, 9) + rng.uniform(0, 6))
        alpha = (rng.uniform(.5, .72) + .22 * folds)[None, :, None]
        reach = rng.uniform(.8, 1.)
        alpha = alpha * (np.linspace(0, 1, h)[:, None, None] < reach)
        room = room * (1 - alpha) + np.array((.6, .6, .56), np.float32) * alpha
    elif what < .62:                                # a roller blind part of the way down
        reach = int(h * rng.uniform(.2, .75))
        room[:reach] = np.array((.52, .49, .42), np.float32) * rng.uniform(.8, 1.)
    if rng.random() < .3:                           # drapes at the sides
        fabric = np.array(((.48, .3, .22), (.3, .34, .42), (.56, .48, .3), (.34, .4, .3))[int(rng.integers(4))], np.float32)
        side = int(w * rng.uniform(.1, .22))
        for a, b in ((0, side), (w - side, w)):
            room[:, a:b] = fabric * (.8 + .2 * np.sin(np.arange(b - a) * .6))[None, :, None]
    if rng.random() < .16:                          # pots on the sill, leaves a hand high
        for _ in range(int(rng.integers(1, 4))):
            cx = int(rng.integers(w // 6, 5 * w // 6))
            r = max(2, int(.05 * METRE * rng.uniform(.7, 1.2)))
            for _ in range(9):
                lx, ly = cx + int(rng.normal(0, r)), h - 2 * r - int(abs(rng.normal(0, r * 1.2)))
                room[max(0, ly - 2):ly + 3, max(0, lx - 3):lx + 3] = np.array((.11, .2, .1), np.float32) * rng.uniform(.7, 1.2)
            room[h - 2 * r:h, max(0, cx - r):cx + r] = (.3, .17, .11)
    return room


def _shaded(d, box, colour, width=1):
    """A frame bar: lit on its top and left, in shade on its bottom and right."""
    x0, y0, x1, y1 = box
    d.rectangle(box, fill=colour)
    d.line((x0, y0, x1, y0), fill=tuple(min(255, c + 16) for c in colour), width=width)
    d.line((x0, y0, x0, y1), fill=tuple(min(255, c + 12) for c in colour), width=width)
    d.line((x0, y1, x1, y1), fill=tuple(int(c * .66) for c in colour), width=width)
    d.line((x1, y0, x1, y1), fill=tuple(int(c * .72) for c in colour), width=width)


def _frames(im, kind, rng):
    """The joinery of one window over its glass."""
    w, h = im.size
    d = ImageDraw.Draw(im)
    paint = {'wood': tuple(int(c * rng.uniform(.78, .96)) for c in (226, 222, 208)), 'pvc': (236, 236, 232), 'pvc3': (236, 236, 232),
             'dark': (58, 60, 64), 'sash': (232, 230, 222), 'sash6': (232, 230, 222), 'casement': (70, 74, 70),
             'alu': (178, 182, 186), 'alubars': (178, 182, 186)}[kind]
    t = {'alu': 4, 'alubars': 4, 'dark': 7, 'pvc': 8, 'pvc3': 8}.get(kind, 9)

    def bar(x0, y0, x1, y1):
        _shaded(d, (x0, y0, x1, y1), paint)

    for box in ((0, 0, w - 1, t), (0, h - t - 1, w - 1, h - 1), (0, 0, t, h - 1), (w - t - 1, 0, w - 1, h - 1)):
        bar(*box)
    mid = w // 2
    if kind == 'wood':
        # two leaves, a transom with its lights over them, the ventilation pane in the left one
        y = int(h * .3)
        bar(mid - t // 2 - 1, 0, mid + t // 2 + 1, h - 1)
        bar(0, y - t // 2, w - 1, y + t // 2)
        bar(int(w * .24) - 2, y, int(w * .24) + 2, int(h * .62))
        bar(t, int(h * .62) - 2, mid, int(h * .62) + 2)
    elif kind == 'pvc':
        bar(mid - t // 2, 0, mid + t // 2, h - 1)
        hy = int(h * .52)
        d.rectangle((w - t * 2 - 4, hy - 9, w - t * 2, hy + 9), fill=(204, 204, 200))
    elif kind in ('pvc3', 'dark'):
        for x in (w // 3, 2 * w // 3):
            bar(x - t // 2, 0, x + t // 2, h - 1)
    elif kind in ('sash', 'sash6'):
        y = h // 2
        bar(0, y - t // 2 - 1, w - 1, y + t // 2 + 1)
        if kind == 'sash6':
            for x in (w // 3, 2 * w // 3):
                d.line((x, 0, x, h), fill=paint, width=3)
            for y2 in (h // 4, 3 * h // 4):
                d.line((0, y2, w, y2), fill=paint, width=3)
    elif kind == 'casement':
        bar(mid - t // 2, 0, mid + t // 2, h - 1)
        for k in (1, 2, 3):
            d.line((t, h * k // 4, w - t, h * k // 4), fill=paint, width=3)
    elif kind in ('alu', 'alubars'):
        bar(mid - 3, 0, mid + 3, h - 1)
        if kind == 'alubars':                       # window bars on brackets
            for x in range(10, w, max(10, int(.12 * METRE))):
                d.line((x, 0, x, h), fill=IRON, width=3)
            for y2 in (h // 4, h // 2, 3 * h // 4):
                d.line((0, y2, w, y2), fill=IRON, width=4)


def _window(st, kind, w, h, rng, layers, wall_rng):
    """The picture of one window, w x h px."""
    if kind == PHOTO:
        layer = photo.WINDOW_LAYERS[int(wall_rng.integers(len(photo.WINDOW_LAYERS)))]
        crop = layers[layer].crop(tuple(round(v * photo.CELL) for v in photo.PHOTO_GLASS[layer]))
        return crop.resize((w, h), Image.LANCZOS)
    room = _room(w, h, rng).astype(np.float64)
    pane = shop.glass_over(room, rng, (1., 1., 1.)) ** 1.3 * .82      # the sky in a dark room's glass, not a pale board
    im = Image.fromarray((pane * 255).astype('uint8'))
    _frames(im, kind, rng)
    return im


def _put(colour, height, box, rgb, raised, jitter=None):
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0 = max(0, x0), max(0, y0)
    region = np.array(rgb, np.float32) / 255
    if jitter is not None:
        region = region * (1 + jitter.normal(0, .02, (max(1, y1 - y0), max(1, x1 - x0), 1)))
    colour[y0:y1, x0:x1] = region
    height[y0:y1, x0:x1] = np.maximum(height[y0:y1, x0:x1], raised)


def _arch(colour, height, box, st, rng):
    """A segmental arch of bricks on end over a window: joints fan out from below it."""
    x0, y0, x1, _ = box
    w = x1 - x0
    cx, rise, ring = (x0 + x1) / 2, .22 * METRE, .3 * METRE
    radius = (w * w / 4 + rise * rise) / (2 * rise)
    centre_y = y0 + radius - rise
    top = int(y0 - rise - ring - 2)
    yy, xx = np.mgrid[top:int(y0 + 2), int(x0 - ring):int(x1 + ring)]
    r = np.hypot(xx - cx, yy - centre_y)
    keep = (r > radius) & (r < radius + ring) & (yy < y0)
    angle = np.arctan2(xx - cx, centre_y - yy)
    course = np.floor(angle * radius / (.085 * METRE)).astype(np.int32)
    tone = 1 + .09 * np.sin(course * 12.9898 + 3)
    joint = (angle * radius / (.085 * METRE)) % 1 < .16
    ys, xs = yy[keep], xx[keep]
    inside = (ys >= 0) & (ys < PX) & (xs >= 0) & (xs < PX)
    ys, xs = ys[inside], xs[inside]
    colour[ys, xs] = np.clip(colour[ys, xs] * .9 * tone[keep][inside][:, None], 0, 1)
    colour[ys[joint[keep][inside]], xs[joint[keep][inside]]] = (.72, .68, .62)
    height[ys, xs] = .3


def _shutters(colour, height, box, rgb, rng):
    """Louvred shutters folded back on both sides of a window."""
    x0, y0, x1, y1 = box
    leaf = (x1 - x0) * .5
    for a, b in ((x0 - leaf - 4, x0 - 4), (x1 + 4, x1 + leaf + 4)):
        ia, ib = max(0, int(a)), min(PX, int(b))
        ly0, ly1 = int(y0), int(y1)
        shade = rng.uniform(.82, 1.)
        blades = (np.arange(ly1 - ly0) % 7 < 5)[:, None, None]
        tone = np.array(rgb, np.float32) / 255 * shade
        colour[ly0:ly1, ia:ib] = tone * (blades * 1. + (1 - blades) * .62)
        colour[ly0:ly1, [ia, ia + 1, ib - 2, ib - 1]] = tone * 1.12
        height[ly0:ly1, ia:ib] = np.where(blades[..., 0], .55, .3)


def _trim(st, colour, height, box, rng):
    """What frames an opening on the wall, box in px of the opening (frame included)."""
    x0, y0, x1, y1 = box
    trim = st['trim']
    edge = st.get('trim_colour', CREAM)
    w = .1 * METRE
    if 'surround' in trim:
        _put(colour, height, (x0 - w, y0 - w, x1 + w, y1), edge, .35, rng)
    if 'hood' in trim:
        _put(colour, height, (x0 - w * 1.8, y0 - w * 2.4, x1 + w * 1.8, y0 - w * 1.3), edge, 1.1, rng)
        _put(colour, height, (x0 - w * 1.2, y0 - w * 1.3, x1 + w * 1.2, y0 - w * .9), edge, .7, rng)
    if 'lintel' in trim:
        _put(colour, height, (x0 - w * 1.6, y0 - w * 1.8, x1 + w * 1.6, y0), (138, 134, 126), .22, rng)
    if 'lintel_light' in trim:
        _put(colour, height, (x0 - w * 1.2, y0 - w * 2.2, x1 + w * 1.2, y0), CREAM, .25, rng)
    if 'lintel_dark' in trim:
        _put(colour, height, (x0 - w * .6, y0 - w * 1.2, x1 + w * .6, y0), (70, 72, 76), .3, rng)
    if 'arch' in trim:
        _arch(colour, height, box, st, rng)
    if 'shutters' in trim:
        _shutters(colour, height, box, st['shutter'], rng)


def _shadows(colour, height):
    """Shade under what stands out: a soft stack of steps down the wall, wrapping with the repeat."""
    cast = np.zeros_like(height)
    for step, weight in ((2, 1.), (5, .8), (9, .6), (15, .4), (24, .22)):
        below = np.roll(height, (step, step // 6), (0, 1))
        cast = np.maximum(cast, (below - height) * weight)
    return colour * (1 - np.clip(cast * .42, 0, .62))[..., None]


def _normal(normal, height, strength=6.):
    """The photo's normal map with the slopes of the height map on it (OpenGL: x right, y up)."""
    dy, dx = np.gradient(height)
    n = normal * 2 - 1
    n[..., 0] -= dx * strength
    n[..., 1] += dy * strength
    n /= np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-4)
    return n * .5 + .5


def _dirt(colour, name, amount):
    """Soot and damp: broad stains of street grey that repeat with the sheet."""
    k = shop.seed('dirt', name) % 100000
    noise = photo._noise(k, 3) * .6 + photo._noise(k + 7, 11) * .4
    fall = (np.linspace(.75, 1.2, PX, dtype=np.float32)[:, None])
    stain = np.clip((noise - .42) / .4, 0, 1) * amount * .34 * fall
    return colour * (1 - stain[..., None]) + np.array((.27, .26, .24), np.float32) * stain[..., None]


def _blur(a, sigma):
    """Gaussian blur that wraps with the repeat."""
    fy, fx = np.fft.fftfreq(a.shape[0])[:, None], np.fft.fftfreq(a.shape[1])[None, :]
    return np.real(np.fft.ifft2(np.fft.fft2(a) * np.exp(-2 * (np.pi * sigma) ** 2 * (fx * fx + fy * fy)))).astype(np.float32)


def _rain(colour, runs, amount, rust, rng):
    """Dark streaks down from each sill, wrapping from the bottom of the repeat to its top; rust
    from window bars and brackets in hot wet countries."""
    streak = np.zeros((PX, PX), np.float32)
    red = np.zeros((PX, PX), np.float32)
    for x0, x1, y in runs:
        for _ in range(int((x1 - x0) / 7)):
            x = int(rng.uniform(x0, x1))
            length = int(rng.uniform(.3, 1.5) * METRE)
            width = int(rng.integers(1, 5))
            strength = rng.uniform(.25, 1.) * amount
            rows = np.arange(y, y + length) % PX
            streak[rows, x:x + width] += strength * np.linspace(1, 0, length, dtype=np.float32)[:, None] ** 1.4
            if rng.random() < rust:
                red[rows, x:x + width] += strength * np.linspace(1, 0, length, dtype=np.float32)[:, None] ** 2
    streak, red = np.clip(_blur(streak, 2.2), 0, 1), np.clip(_blur(red, 1.6), 0, 1)
    colour = colour * (1 - streak[..., None] * .42)
    return colour * (1 - red[..., None] * .5) + np.array((.42, .2, .1), np.float32) * red[..., None] * .5


def draw(name, layers=None):
    """(colour, normal) PIL images of one repeat of a facade: row 0 at the top of the wall, the
    normal's green turned as fast_art.photo_real wants it."""
    st = STYLES[name]
    rng = np.random.default_rng(shop.seed('facade', name))
    layers = layers or photo.panel_atlas()
    colour, normal = material(st)
    height = np.zeros((PX, PX), np.float32)
    if st.get('tile'):
        _tiles(colour, height, rng)
    if 'pier' in st['trim']:                        # the darker panel between a new block's windows
        for bx in range(0, BAYS, 2):
            x0 = (bx + LAYOUTS[st['layout']][2]) * CELL
            x1 = (bx + 1 + LAYOUTS[st['layout']][0]) * CELL
            mask = np.zeros(PX, bool)
            mask[int(x0):int(x1) % PX if x1 < PX else PX] = True
            colour[:, mask] = colour[:, mask] * .3 + np.array(st['pier'], np.float32) / 255 * .7
    if 'joints' in st['trim']:                      # the panels of a ventilated facade
        for y in range(0, PX, int(1.2 * METRE)):
            colour[y:y + 2] *= .7
            height[y:y + 2] = -.2
    if st['band']:
        rgb, metres = st['band']
        for sy in range(BAYS):
            _put(colour, height, (0, sy * CELL, PX, sy * CELL + metres * METRE), rgb, .5, rng)
    left, top, right, bottom = LAYOUTS[st['layout']]
    weights = np.array([share for _, share in st['windows']], float)
    kinds = [kind for kind, _ in st['windows']]
    runs = []
    for bx in range(BAYS):
        for sy in range(BAYS):
            box = ((bx + left) * CELL, (sy + top) * CELL, (bx + right) * CELL, (sy + bottom) * CELL)
            _trim(st, colour, height, box, rng)
            x0, y0, x1, y1 = (int(round(v)) for v in box)
            kind = kinds[int(rng.choice(len(kinds), p=weights / weights.sum()))]
            pane = _window(st, kind, x1 - x0, y1 - y0, rng, layers, rng)
            colour[y0:y1, x0:x1] = np.asarray(pane, np.float32) / 255
            height[y0:y1, x0:x1] = -1.
            normal[y0:y1, x0:x1] = (.5, .5, 1.)
            reach = int(.04 * METRE)
            sill = int(.06 * METRE)
            _put(colour, height, (x0 - reach, y1, x1 + reach, y1 + sill), st['sill'], .7, rng)
            runs.append((x0, x1, y1 + sill))
    if 'rail' in st['trim']:
        for bx in range(BAYS):
            for sy in range(BAYS):
                x0, x1 = int((bx + left) * CELL) - 8, int((bx + right) * CELL) + 8
                y1 = int((sy + bottom) * CELL)
                y0 = y1 - int(.8 * METRE)
                colour[y0:y0 + 5, x0:x1] = np.array(IRON, np.float32) / 255
                colour[y0:y1, x0:x1][:, ::14] = np.array(IRON, np.float32) / 255
                height[y0:y0 + 5, x0:x1] = .9
    colour = _dirt(colour, name, st['dirt'])
    colour = _rain(colour, runs, st['rain'], st.get('rust', 0), rng)
    colour = _shadows(colour, height)
    colour = np.clip(colour + rng.normal(0, .006, (PX, PX, 1)), 0, 1)
    out = _normal(normal, height)
    out[..., 1] = 1 - out[..., 1]                   # photo_real turns it back as it flips the rows
    img = lambda a: Image.fromarray((np.clip(a, 0, 1) * 255 + .5).astype('uint8'))
    return img(colour), img(out)


def end_wall(name):
    """(colour, normal) of the blank end wall of a brick facade: its material alone."""
    st = STYLES[name]
    colour, normal = material(st, END_PX, END_M)
    normal[..., 1] = 1 - normal[..., 1]
    img = lambda a: Image.fromarray((np.clip(a, 0, 1) * 255 + .5).astype('uint8'))
    return img(colour), img(normal)


def blank_panel(rgb):
    """A panel block's windowless end wall, a repeat of 6 m: stained concrete and its joints. The
    pack's blank panel is a photograph of a bricked-up window, which came out as rows of blotches."""
    st = {'wall': 'mat_concrete_board', 'metres': (3., 3.), 'paint': (tuple(round(c * 212) for c in rgb), .8)}
    colour, _ = material(st, END_PX, END_M)
    step = END_PX // 2
    for k in (0, step):
        colour[k:k + 3] *= .62
        colour[:, k:k + 3] *= .66
    return Image.fromarray((np.clip(colour, 0, 1) * 255 + .5).astype('uint8'))


def patched(name, layers=None):
    """A panel block with insulated flats: the panel photo as fast_photo.panel keys it, so its
    windows are its plain sibling's and that wall's night glow fits, and render on some flats."""
    key = PATCHED[name]
    layers = layers or photo.panel_atlas()
    rgb = photo.PHOTO_WALLS[key][1]
    base = photo.panel(rgb, key, layers)
    n, cell = photo.PANEL_N, photo.CELL
    size = n * cell
    colour = np.asarray(base, np.float32) / 255
    height = np.zeros((size, size), np.float32)
    rng = np.random.default_rng(shop.seed('patch', name))
    own = photo.WINDOW_LAYERS[int(photo.unit('own', key) * len(photo.WINDOW_LAYERS))]
    mask = np.zeros((size, size), bool)
    glass = []
    for bx in range(n):
        for sy in range(n):
            swap = photo.WINDOW_LAYERS[int(photo.unit('flat', key, bx, sy) * len(photo.WINDOW_LAYERS))]
            layer = swap if photo.unit('swap', key, bx, sy) < .2 else own
            x0, y0, x1, y1 = photo.PHOTO_GLASS[layer]
            pad = .035
            glass.append(tuple(int(v * cell) for v in (bx + x0 - pad, sy + y0 - pad, bx + x1 + pad, sy + y1 + pad)))
    for bx in range(n):
        for sy in range(n):
            if rng.random() > .36:
                continue
            render = np.array(PATCH_RENDER[int(rng.integers(len(PATCH_RENDER)))], np.float32) / 255
            wide = 1 + int(rng.random() < .55)          # a room or the whole flat
            x0, x1 = bx * cell, min(size, (bx + wide) * cell)
            y0, y1 = sy * cell, (sy + 1) * cell
            patch = np.zeros((size, size), bool)
            patch[y0:y1, x0:x1] = True
            for a, b, c, d in glass:
                patch[b:d, a:c] = False
            grain = rng.normal(1, .018, (size, size, 1)).astype(np.float32)
            colour[patch] = (render * grain)[patch]
            mask |= patch
    height[mask] = .6
    colour = _shadows(colour, height)
    k = shop.seed('dirt', name) % 100000
    noise = np.clip((photo._noise(k, 5) - .5) / .4, 0, 1)
    dirt = noise * mask * .16
    colour = colour * (1 - dirt[..., None]) + np.array((.3, .29, .27), np.float32) * dirt[..., None]
    return Image.fromarray((np.clip(colour, 0, 1) * 255 + .5).astype('uint8'))


# --- plain sheets -----------------------------------------------------------------------------
# name: (material, fit). A kind of fast_style.SHEETS takes one repeat at its own size. 'wall' sheets
# are stored upside down as facades are (their v grows upward; a board's lap must shade downward);
# 'plan' and 'roof' ones are not (roof v runs down the slope). 'grey' drops a colour that the
# kinds tint themselves; 'turn' lays a photo's courses level.
SHEETS = {
    'sh_dash': ('mat_dash', 'wall'), 'sh_render': ('mat_render', 'wall'), 'sh_flaking': ('mat_render_flaking', 'wall'),
    'sh_flaking_yellow': ('mat_render_yellow', 'wall'), 'sh_adobe': ('mat_adobe', 'wall'),
    'sh_block': ('mat_block', 'wall turn'), 'sh_ashlar': ('mat_ashlar', 'wall'), 'sh_sandstone': ('mat_sandstone', 'wall'),
    'sh_fieldstone': ('mat_fieldstone', 'wall'), 'sh_clapboard': ('mat_clapboard', 'wall grey'), 'sh_boards_red': ('mat_boards_red', 'wall'),
    'sh_vinyl': ('mat_vinyl', 'wall grey'), 'sh_stock': ('mat_brick_stock', 'wall'), 'sh_brick_dark': ('mat_brick_dark', 'wall'),
    'sh_brick_red': ('mat_brick_red', 'wall'),
    'sh_clinker': ('mat_clinker', 'wall'), 'sh_tin_rust': ('mat_tin_rust', 'wall'), 'sh_tin_zinc': ('mat_tin_zinc', 'wall'),
    'sh_profile': ('mat_profile', 'wall grey'), 'sh_planks': ('mat_planks', 'wall'),
    'sh_roof_clay': ('mat_roof_clay', 'roof'), 'sh_roof_pantile': ('mat_roof_pantile', 'roof'),
    'sh_roof_concrete': ('mat_roof_concrete', 'roof'), 'sh_roof_slate': ('mat_roof_slate', 'roof'),
    'sh_roof_shingle': ('mat_roof_shingle', 'roof'), 'sh_roof_thatch': ('mat_roof_thatch', 'roof'),
    'sh_roof_tin': ('mat_tin_rust', 'roof'), 'sh_roof_zinc': ('mat_tin_zinc', 'roof'), 'sh_roof_profile': ('mat_profile', 'roof grey'),
    'sh_setts': ('mat_setts', 'plan'), 'sh_soil': ('mat_soil', 'plan'), 'sh_stubble': ('mat_stubble', 'plan'),
    'sh_laterite': ('mat_laterite', 'plan'),
}
SHEET_PX, SHEET_NORMAL_PX = 1024, 512
# Photos too dark for a baseColorFactor (at most 1) to bring up: their own colour times this. A
# 'grey' sheet is levelled to GREY_MEAN (linear), which its kinds' factors count from.
SHEET_LEVEL = {'sh_boards_red': 2.6, 'sh_planks': 2.2, 'sh_brick_dark': 1.7, 'sh_clinker': 1.5}
GREY_MEAN = .6


def sheet(name):
    """(colour, normal) PIL images of a plain sheet, as the game wants them."""
    source, fit = SHEETS[name]
    src = photo.TEXTURES / source
    colour = Image.open(src / 'albedo.jpg').convert('RGB').resize((SHEET_PX, SHEET_PX), Image.LANCZOS)
    normal = Image.open(src / 'normal.jpg').convert('RGB').resize((SHEET_NORMAL_PX, SHEET_NORMAL_PX), Image.LANCZOS)
    if 'turn' in fit:
        colour = colour.transpose(Image.ROTATE_90)
        r, g, b = normal.transpose(Image.ROTATE_90).split()
        normal = Image.merge('RGB', (g.point(lambda v: 255 - v), r, b))
    if 'grey' in fit:
        grey = (np.asarray(colour.convert('L'), np.float32) / 255) ** 2.2
        grey = np.clip(grey * GREY_MEAN / max(float(grey.mean()), .01), 0, 1) ** (1 / 2.2)
        colour = Image.fromarray((grey * 255 + .5).astype('uint8')).convert('RGB')
    elif name in SHEET_LEVEL:
        k = SHEET_LEVEL[name]
        colour = colour.point(lambda v: min(255, round(v * k ** (1 / 2.2))))
    r, g, b = normal.split()
    if 'wall' in fit:
        colour = colour.transpose(Image.FLIP_TOP_BOTTOM)
        r, g, b = r.transpose(Image.FLIP_TOP_BOTTOM), g.transpose(Image.FLIP_TOP_BOTTOM), b.transpose(Image.FLIP_TOP_BOTTOM)
    else:
        g = g.point(lambda v: 255 - v)              # green flipped for the game, as the ground's
    return colour, Image.merge('RGB', (r, g, b))


def fence_boards():
    """A fence of upright boards, 2 m high and 2 m a repeat: gaps cut by opacity (fast_art), the
    weathered planks of the village fence turned upright and a rail across their back."""
    colour, normal = sheet('sh_planks')
    colour = colour.transpose(Image.ROTATE_90)
    mask = Image.new('L', colour.size, 255)
    d = ImageDraw.Draw(mask)
    boards, px = 12, colour.width
    for k in range(boards):
        x = k * px // boards
        d.rectangle((x, 0, x + 7, px), fill=0)
    return colour, mask.convert('RGB')
