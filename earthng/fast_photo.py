"""Photo facades and photo ground for the fast generator's 'real' pack.

Sources are CC0 photographs: the Panelka pack (https://kureca.itch.io/panelka-pack, facades of
Soviet blocks) and ambientCG (lawn, meadow, worn ground), imported by Earth2Road's
tools/import_panelka.py and tools/fetch_textures.py into data/textures/<set>/albedo.jpg.
The same composition as Earth2Road's BeamNG photo style (texture_styles.py): a facade repeat is
6 m (two 3 m storeys by two 3 m bays), the II-68 loggia sheet 33 m; ground sheets cover 24 m.

A wall kind is 'wall_<name>' (fast_style.KINDS); its repeat in metres is PHOTO_WALLS[name][2].
"""
import functools
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import paths

TEXTURES = paths.PROJECT / 'data/textures'
TILE_PX = 1024          # one 6 m repeat: the panel photos' own 512 px per 3 m cell
CELL = TILE_PX // 2
SHEET_PX = 2048         # the whole II-68 loggia photo, 33 m
LOGGIA_M = 33.0
PANEL_LAYERS = 6        # atlas: five windowed panels, then a blank one
WINDOW_LAYERS = (0, 1, 3, 4)   # layer 2 has a window grille: not in a repeat
PHOTO_WINDOWS = True           # brick and plaster: photo windows (photo_windows), not drawn ones
PANEL_GAIN = 1.32
PANEL_N = 4              # a panel repeat is 4 x 4 cells (12 m): lit windows at night do not form a checker

# name: (family, colour 0..1, metres per repeat). Colours are the city's: grey and beige panels,
# the pinkish and pale blue series, painted plaster of the old centre.
PHOTO_WALLS = {
    'pnl_grey':   ('panel',   (.80, .80, .78), 3.0 * PANEL_N),
    'pnl_beige':  ('panel',   (.86, .80, .70), 3.0 * PANEL_N),
    'pnl_pink':   ('panel',   (.86, .75, .71), 3.0 * PANEL_N),
    'pnl_blue':   ('panel',   (.74, .80, .86), 3.0 * PANEL_N),
    'pnl_white':  ('panel',   (.90, .90, .88), 3.0 * PANEL_N),
    'lgg_cream':  ('loggia',  (.87, .84, .77), LOGGIA_M),
    'lgg_grey':   ('loggia',  (.80, .80, .78), LOGGIA_M),
    'lgg_pink':   ('loggia',  (.86, .76, .72), LOGGIA_M),
    'brk_red':    ('brick',   (.65, .40, .32), 6.0),
    'brk_white':  ('brick',   (.88, .87, .83), 6.0),
    'pls_yellow': ('plaster', (.86, .74, .50), 6.0),
    'pls_cream':  ('plaster', (.89, .85, .76), 6.0),
    'pls_peach':  ('plaster', (.86, .75, .66), 6.0),
    'pls_green':  ('plaster', (.70, .78, .68), 6.0),
    'pls_blue':   ('plaster', (.70, .78, .86), 6.0),
    'pls_grey':   ('plaster', (.78, .77, .74), 6.0),
    # offices: drawn curtain walls (glass that reflects the sky: see fast_style.real_stage),
    # ribbon windows in light concrete; storefronts for the ground floors of the old town
    'off_blue':   ('curtain', (.50, .64, .76), 6.0),
    'off_green':  ('curtain', (.50, .66, .64), 6.0),
    'off_grey':   ('curtain', (.60, .64, .68), 6.0),
    'off_ribbon': ('ribbon',  (.86, .85, .81), 6.0),
    'off_ribbon_dark': ('ribbon', (.56, .55, .53), 6.0),
    'shop_dark':  ('shop',    (.20, .21, .22), 6.0),
    'shop_red':   ('shop',    (.55, .14, .12), 6.0),
    'shop_green': ('shop',    (.12, .36, .24), 6.0),
    'shop_blue':  ('shop',    (.12, .24, .45), 6.0),
}
# Drawn at art build (fast_facade.STYLES): a block's own materials, windows and weather over a
# 12 m repeat. Their colours stand for them in the flat packs' lists.
DRAWN = {
    'brk_d_sil': (.86, .84, .78), 'brk_d_red': (.55, .32, .26), 'brk_d_old': (.56, .32, .24), 'brk_d_new': (.46, .24, .18),
    'brk_d_stock': (.72, .56, .36), 'brk_d_vic': (.50, .30, .26), 'brk_d_dark': (.32, .24, .22),
    'pls_d_dash': (.69, .67, .61), 'pls_d_stalin': (.87, .78, .63), 'pls_d_stalin_red': (.72, .44, .33), 'pls_d_aged': (.78, .70, .36),
    'pls_d_flake': (.66, .66, .64), 'pls_d_new': (.84, .80, .72), 'pls_d_euro': (.89, .87, .83), 'pls_d_euro_warm': (.85, .77, .63),
    'pls_d_ashlar': (.81, .77, .69), 'pls_d_shutter': (.84, .63, .38), 'pls_d_white': (.93, .93, .89), 'pls_d_sand': (.80, .71, .57),
    'pls_d_adobe': (.75, .60, .44), 'pls_d_tile': (.89, .88, .85), 'pls_d_stain': (.73, .71, .65), 'pls_d_blue': (.38, .63, .67),
    'pls_d_pink': (.85, .53, .50),
}
for _n, _c in DRAWN.items():
    PHOTO_WALLS[_n] = ('facade', _c, 12.0)
# Soviet panels with some flats insulated (fast_facade.patched)
for _n, _key in (('pnl_patch_grey', 'pnl_grey'), ('pnl_patch_beige', 'pnl_beige'), ('pnl_patch_white', 'pnl_white')):
    PHOTO_WALLS[_n] = ('patched', PHOTO_WALLS[_key][1], 3.0 * PANEL_N)
# blank end walls of elongated panel and brick blocks (no windows across the short side)
for _n, (_f, _c, _m) in list(PHOTO_WALLS.items()):
    if _f in ('panel', 'loggia', 'brick', 'patched'):
        PHOTO_WALLS[_n + '_end'] = ('end_brick' if _f == 'brick' else 'end_panel', _c, 6.0)
    elif _f == 'facade' and _n.startswith('brk_'):
        PHOTO_WALLS[_n + '_end'] = ('end_facade', _c, 6.0)

END_WALL_MAX_M = 16.0   # deeper walls are a wing's long side (Soviet blocks are 11-14 m deep)


def unit(*key):
    return int.from_bytes(hashlib.sha256(repr(key).encode()).digest()[:4], 'big') / 2**32


def tint(image, colour, strength=.5, gain=1.):
    """Shift a photo toward colour (0..1 RGB) keeping its brightness (times gain)."""
    a = np.asarray(image, dtype=np.float32)
    mean = sum(colour) / 3 or .05
    k = np.array([gain * (1 + strength * (c / mean - 1)) for c in colour], dtype=np.float32)
    return Image.fromarray(np.clip(a * k, 0, 255).astype('uint8'))


def tiled(path, metres, size=TILE_PX, span=6.0):
    """A tileable photo repeated over `span` m at its real size (whole repeats)."""
    src = Image.open(path).convert('RGB')
    nx, ny = max(1, round(span / metres[0])), max(1, round(span / metres[1]))
    cell = src.resize((size // nx, size // ny), Image.LANCZOS)
    out = Image.new('RGB', (size, size))
    for i in range(nx):
        for j in range(ny):
            out.paste(cell, (i * cell.width, j * cell.height))
    # size // n leaves a few black pixels on the seam when n does not divide size
    return out.crop((0, 0, cell.width * nx, cell.height * ny)).resize((size, size), Image.LANCZOS)


def windows(image, glass=(52, 62, 70)):
    """Windows over a plain wall on the 3 m grid: frame, two panes, sill."""
    d = ImageDraw.Draw(image)
    frame = (214, 214, 206)
    for bx in range(2):
        for sy in range(2):
            x0, y0 = bx * CELL, sy * CELL
            box = (x0 + .24 * CELL, y0 + (1 - .80) * CELL, x0 + .76 * CELL, y0 + (1 - .32) * CELL)
            d.rectangle(box, fill=frame)
            inner = (box[0] + .025 * CELL, box[1] + .025 * CELL, box[2] - .025 * CELL, box[3] - .025 * CELL)
            d.rectangle(inner, fill=glass)
            # a lighter upper pane: the sky in the glass
            d.rectangle((inner[0], inner[1], inner[2], inner[1] + (inner[3] - inner[1]) * .35),
                        fill=tuple(min(255, c + 34) for c in glass))
            mid = (box[0] + box[2]) / 2
            d.rectangle((mid - .014 * CELL, inner[1], mid + .014 * CELL, inner[3]), fill=frame)
            d.rectangle((box[0] - .03 * CELL, box[3], box[2] + .03 * CELL, box[3] + .035 * CELL), fill=(176, 176, 170))
    return image


# Photo windows for brick and plaster walls: the frame box of fast_packs.LAYER_GLASS cut from
# a Panelka panel (wooden, painted and PVC frames, curtains, flowers), laid into the drawn
# window's box, which the night glow (fast_packs.windows_of) lights. A reveal shadows its top
# and left; a rain stain runs down from the sill.
PHOTO_GLASS = {0: (.245, .165, .75, .69), 1: (.225, .17, .76, .71), 3: (.245, .13, .76, .665), 4: (.245, .145, .76, .695)}
WINDOW_BOX = (.24, .20, .76, .68)       # of a 3 m cell, row 0 at its top (the drawn frame)


def photo_windows(image, key, layers, normal=None):
    """Photo windows over a plain wall on the 3 m grid (image and its normal map in place)."""
    a = np.asarray(image, dtype=np.float32).copy()
    own = (1, 3, 4)[int(unit('wown', key) * 3)]          # the grey frame (0) only as an odd one
    nrm = None if normal is None else np.asarray(normal, dtype=np.uint8).copy()
    for bx in range(2):
        for sy in range(2):
            swap = WINDOW_LAYERS[int(unit('wflat', key, bx, sy) * len(WINDOW_LAYERS))]
            layer = swap if unit('wswap', key, bx, sy) < .25 else own
            g = PHOTO_GLASS[layer]
            crop = layers[layer].crop(tuple(round(v * CELL) for v in g))
            x0, y0 = bx * CELL + round(WINDOW_BOX[0] * CELL), sy * CELL + round(WINDOW_BOX[1] * CELL)
            x1, y1 = bx * CELL + round(WINDOW_BOX[2] * CELL), sy * CELL + round(WINDOW_BOX[3] * CELL)
            w = np.asarray(crop.resize((x1 - x0, y1 - y0), Image.LANCZOS), dtype=np.float32)
            a[y0:y1, x0:x1] = w
            # the reveal: the wall's thickness shades the top and the left of the opening
            r = max(2, round(.03 * CELL))
            for k in range(r):
                shade = .55 + .45 * k / r
                a[y0 + k, x0:x1] *= shade
                a[y0:y1, x0 + k] *= shade
            # a concrete sill, then a rain stain under it fading down the wall
            sill = (176, 176, 170)
            sx0, sx1 = x0 - round(.03 * CELL), x1 + round(.03 * CELL)
            sh = max(2, round(.035 * CELL))
            a[y1:y1 + sh, sx0:sx1] = sill
            a[y1 + sh:y1 + sh + max(1, sh // 2), sx0:sx1] *= .7
            run = round(unit('stain', key, bx, sy) * .22 * CELL + .08 * CELL)
            for k in range(run):
                yy = y1 + sh + k
                if yy >= a.shape[0]:
                    break
                fade = 1 - .16 * (1 - k / run)
                a[yy, x0 + r:x1 - r] *= fade
            if nrm is not None:
                nrm[y0:y1 + sh, sx0:sx1] = (128, 128, 255)
    image.paste(Image.fromarray(np.clip(a, 0, 255).astype('uint8')))
    if normal is not None:
        normal.paste(Image.fromarray(nrm))
    return image


def panel_atlas():
    a = Image.open(TEXTURES / 'panelka_panels/albedo.jpg').convert('RGB')
    s = a.height
    return [a.crop((k * s, 0, (k + 1) * s, s)).resize((CELL, CELL), Image.LANCZOS) for k in range(PANEL_LAYERS)]


def panel(colour, key, layers):
    """PANEL_N x PANEL_N photo panels: one window style per facade, an occasional different one."""
    own = WINDOW_LAYERS[int(unit('own', key) * len(WINDOW_LAYERS))]
    out = Image.new('RGB', (CELL * PANEL_N, CELL * PANEL_N))
    for bx in range(PANEL_N):
        for sy in range(PANEL_N):
            swap = WINDOW_LAYERS[int(unit('flat', key, bx, sy) * len(WINDOW_LAYERS))]
            out.paste(layers[swap if unit('swap', key, bx, sy) < .2 else own], (bx * CELL, sy * CELL))
    return tint(out, colour, gain=PANEL_GAIN)


def wall_image(name, layers=None):
    """(colour image, normal image or None) of one repeat; row 0 at the top of the wall."""
    family, colour, _ = PHOTO_WALLS[name]
    layers = layers or panel_atlas()
    if family in ('facade', 'patched', 'end_facade'):
        import fast_facade
        if family == 'facade':
            return fast_facade.draw(name, layers)
        if family == 'patched':
            return fast_facade.patched(name, layers), None
        return fast_facade.end_wall(name[:-4])
    if family == 'panel':
        return panel(colour, name, layers), None
    if family == 'loggia':
        a = Image.open(TEXTURES / 'panelka_loggias/albedo.jpg').convert('RGB')
        return tint(a.resize((SHEET_PX, SHEET_PX), Image.LANCZOS), colour, .3, 1.12), None
    if family == 'end_panel':
        import fast_facade
        return fast_facade.blank_panel(colour), None
    if family in ('curtain', 'ribbon', 'shop'):
        return drawn(family, colour, name), None
    white = colour[0] > .8
    src = TEXTURES / ('panelka_brick_white' if white else 'panelka_brick_red')
    if family in ('brick', 'end_brick'):
        im = tiled(src / 'albedo.jpg', (2.0, 1.8))
        if not white:      # the pack's red brick photographs pink: toward fired clay
            im = tint(im, (.60, .38, .31), .6, .8)
        nm = tiled(src / 'normal.jpg', (2.0, 1.8)) if (src / 'normal.jpg').exists() else None
        if family == 'brick':
            im = photo_windows(im, name, layers, nm) if PHOTO_WINDOWS else windows(im)
        return im, nm
    # plaster: the photo tinted strongly toward the paint colour
    im = tint(tiled(TEXTURES / 'panelka_plaster/albedo.jpg', (4.0, 4.0)), colour, .8)
    # the photo's cracks repeat every 4 m: mostly the paint, a little of the photo
    flat = Image.new('RGB', im.size, tuple(round(c * 238) for c in colour))
    im = Image.blend(flat, im, .4)
    return (photo_windows(im, name, layers) if PHOTO_WINDOWS else windows(im)), None


def drawn(family, colour, key):
    """Office and shop walls drawn here (row 0 at the top of a 6 m x 6 m repeat, two 3 m floors)."""
    rgb = tuple(round(c * 255) for c in colour)
    rng = np.random.default_rng(int(unit('drawn', key) * 2**31))
    im = Image.new('RGB', (TILE_PX, TILE_PX), rgb)
    d = ImageDraw.Draw(im)
    m = TILE_PX / 6.0                       # px per metre
    if family == 'curtain':
        # panes 1.5 m x 3 m: each a vertical sky gradient, slightly different; aluminium mullions,
        # a dark spandrel at every floor slab
        for fx in range(4):
            for fy in range(2):
                x0, y0 = fx * 1.5 * m, fy * 3 * m
                k = rng.uniform(.88, 1.1)
                for row in range(int(3 * m)):
                    t = row / (3 * m)
                    c = tuple(min(255, int(v * k * (1.18 - .38 * t))) for v in rgb)
                    d.line([(x0, y0 + row), (x0 + 1.5 * m, y0 + row)], fill=c)
                d.rectangle([x0, y0 + 2.45 * m, x0 + 1.5 * m, y0 + 3 * m], fill=tuple(int(v * .42) for v in rgb))
        for fx in range(5):
            d.rectangle([fx * 1.5 * m - 3, 0, fx * 1.5 * m + 3, TILE_PX], fill=(196, 200, 204))
        for fy in range(3):
            d.rectangle([0, fy * 3 * m - 4, TILE_PX, fy * 3 * m + 4], fill=(180, 184, 188))
        return im
    if family == 'ribbon':
        # a light concrete wall with a continuous window band per floor
        glass = (70, 88, 104)
        for fy in range(2):
            top = fy * 3 * m + .55 * m
            d.rectangle([0, top, TILE_PX, top + 1.55 * m], fill=glass)
            d.rectangle([0, top, TILE_PX, top + .35 * m], fill=(110, 130, 148))
            for fx in range(5):
                d.rectangle([fx * 1.5 * m - 3, top, fx * 1.5 * m + 3, top + 1.55 * m], fill=(200, 200, 196))
        return im
    # shop: on the lower 4.2 m: a granite plinth, shop windows with frames, a sign band (the
    # family colour) under the first floor; the upper 1.8 m stays plain (never shown)
    granite = (58, 56, 54)
    floor = TILE_PX                          # bottom of the image = street level
    d.rectangle([0, 0, TILE_PX, TILE_PX], fill=(150, 146, 140))
    d.rectangle([0, floor - .45 * m, TILE_PX, floor], fill=granite)
    for fx in range(3):
        x0 = fx * 2 * m + .15 * m
        x1 = x0 + 1.7 * m
        d.rectangle([x0, floor - 3.2 * m, x1, floor - .45 * m], fill=(214, 214, 210))
        for row in range(int(2.65 * m)):
            t = row / (2.65 * m)
            c = (int(60 + 70 * (1 - t)), int(72 + 74 * (1 - t)), int(84 + 76 * (1 - t)))
            d.line([(x0 + 5, floor - 3.15 * m + row), (x1 - 5, floor - 3.15 * m + row)], fill=c)
        d.rectangle([(x0 + x1) / 2 - 3, floor - 3.2 * m, (x0 + x1) / 2 + 3, floor - .45 * m], fill=(214, 214, 210))
    d.rectangle([0, floor - 4.2 * m, TILE_PX, floor - 3.3 * m], fill=rgb)
    for fx in range(3):
        x0 = fx * 2 * m + .5 * m
        d.rectangle([x0, floor - 3.95 * m, x0 + 1.0 * m, floor - 3.55 * m], fill=(236, 232, 214))
    return im


# --- ground --------------------------------------------------------------------------------------
GROUND_PX = 2048
GROUND_M = 24.0          # one sheet: 8 repeats of a 3 m photo, 6 of a 4 m one
# kind -> (base, metres), (patch, metres, cover), (wear, metres, cover), tint, saturation
GROUND = {
    'ground': (('photo_lawn', 3.0), ('photo_meadow', 4.0, .35), ('photo_worn', 3.0, .12), (.88, .88, .84), .58),
    'park':   (('photo_lawn', 3.0), ('photo_meadow', 4.0, .22), ('photo_worn', 3.0, .05), (.86, .90, .82), .66),
    'forest': (('photo_meadow', 4.0), ('photo_worn', 3.0, .35), ('photo_trodden', 3.0, .15), (.72, .74, .66), .6),
    'verge':  (('photo_verge', 3.0), ('photo_lawn', 3.0, .35), ('photo_worn', 3.0, .15), (.86, .88, .76), .85),
    # other climates' open ground (generator.lua bio.ground, biome.lua): ambientCG sets of
    # fetch_textures.SETS. Desert floor of sandy grit with crusted patches; wind-rippled dune
    # sand; steppe of dry ground and bleached grass; the Mediterranean's and savanna's golden
    # grass; tundra moss with red heath and lichen stones; the alpine belt's lichen, turf and
    # debris; snow over rock; the melting edge of a snow patch; glacier ice under old snow.
    'desert':    (('desert_soil', 3.0), ('desert_crust', 4.0, .35), ('ground', 3.0, .22), (1.0, .96, .9), .85),
    'dune':      (('dune_sand', 4.0), ('ground', 3.0, .12), ('desert_crust', 4.0, .08), (1.03, .99, .92), .9),
    'steppe':    (('steppe_ground', 3.0), ('photo_meadow', 4.0, .32), ('desert_soil', 3.0, .22), (1.04, 1.0, .8), .5),
    'dry_grass': (('grass', 3.0), ('steppe_ground', 4.0, .45), ('desert_soil', 3.0, .12), (1.24, 1.04, .66), .36),
    'tundra':    (('moss_earth', 3.0), ('moss_red', 4.0, .35), ('lichen_stones', 3.0, .3), (.9, .9, .82), .62),
    'alpine':    (('lichen_stones', 3.0), ('rock_debris', 3.0, .28), ('photo_meadow', 4.0, .12), (.92, .95, .93), .4),
    'snow':      (('snow_wind', 4.0), ('snow_fresh', 4.0, .25), ('rock_debris', 3.0, .03), (1.0, 1.0, 1.0), 1.0),
    'snow_edge': (('snow_wind', 4.0), ('snow_melt', 3.0, .38), ('lichen_stones', 3.0, .3), (1.0, 1.0, 1.0), .8),
    'glacier':   (('snow_wind', 4.0), ('snow_fresh', 4.0, .5), ('snow_dirty', 3.0, .06), (.95, .98, 1.02), .9),
    # ploughed black earth with last year's straw on it and paler dry stretches
    'farmland':  (('mat_soil', 2.0), ('mat_stubble', 2.0, .42), ('photo_worn', 3.0, .1), (.98, .94, .86), .9),
}
# Mean brightness (0..1, after tone and saturation) a sheet is brought to: Snow005 photographs
# grey, the dune sand dark; a kind not named keeps its photos' own.
GROUND_LEVEL = {'snow': .74, 'snow_edge': .64, 'glacier': .7, 'dune': .62, 'desert': .5, 'alpine': .42}


def _layer(name, metres, which):
    repeats = round(GROUND_M / metres)
    cell = GROUND_PX // repeats
    im = Image.open(TEXTURES / name / f'{which}.jpg').convert('RGB')
    tile = np.asarray(im.resize((cell, cell), Image.LANCZOS), dtype=np.float32) / 255
    sheet = np.tile(tile, (repeats, repeats, 1))
    if sheet.shape[0] != GROUND_PX:
        sheet = np.asarray(Image.fromarray((sheet * 255).astype('uint8')).resize((GROUND_PX, GROUND_PX), Image.LANCZOS),
                           dtype=np.float32) / 255
    return sheet


NOISE_PX = 512


def _noise(seed, cycles):
    """Smooth 0..1 noise that repeats with the sheet: waves of whole cycles, summed at NOISE_PX
    (at most 24 cycles: 21 px each) and scaled up; 2048 px direct took 18 s a sheet."""
    rng = np.random.default_rng(seed)
    axis = np.linspace(0, 2 * np.pi, NOISE_PX, endpoint=False, dtype=np.float32)
    u, v = np.meshgrid(axis, axis)
    total = np.zeros_like(u)
    for _ in range(28):
        fx, fy = rng.integers(-cycles, cycles + 1, 2)
        if fx == 0 and fy == 0:
            continue
        total += np.cos(fx * u + fy * v + rng.uniform(0, 2 * np.pi)) / (fx * fx + fy * fy) ** .35
    total = (total - total.min()) / (total.max() - total.min())
    # wrap a border before scaling so the sheet still repeats without a seam
    pad = np.pad(total, 2, mode='wrap')
    big = Image.fromarray(pad.astype(np.float32), mode='F').resize(((NOISE_PX + 4) * GROUND_PX // NOISE_PX,) * 2, Image.BICUBIC)
    k = 2 * GROUND_PX // NOISE_PX
    return np.asarray(big, dtype=np.float32)[k:k + GROUND_PX, k:k + GROUND_PX]


def _cover(noise, cover, detail):
    edge = 1 - cover + (detail - .4) * .5
    t = np.clip((noise - (edge - .03)) / .06, 0, 1)
    return (t * t * (3 - 2 * t))[..., None]


def ground_sheet(kind):
    """(colour, normal) images of one GROUND_M sheet: base photo, a turned copy to hide its
    grid, patches and worn spots on noise masks that repeat with the sheet. Normal green is
    flipped for BeamNG (ambientCG ships OpenGL normals)."""
    (base, bm), (patch, pm, pc), (wear, wm, wc), tone, saturation = GROUND[kind]
    key = int.from_bytes(hashlib.sha256(kind.encode()).digest()[:4], 'big')
    layers = {n: (_layer(n, m, 'albedo'), _layer(n, m, 'normal')) for n, m in ((base, bm), (patch, pm), (wear, wm))}
    shift = GROUND_PX // round(GROUND_M / bm) // 2
    turned_c = np.roll(np.rot90(layers[base][0]), (shift, shift), (0, 1))
    turned_n = np.roll(np.rot90(layers[base][1]), (shift, shift), (0, 1))
    turned_n = np.stack([1 - turned_n[..., 1], turned_n[..., 0], turned_n[..., 2]], -1)
    k = _cover(_noise(key + 99, 6), .5, np.full((GROUND_PX, GROUND_PX), .4, np.float32))
    colour = layers[base][0] * (1 - k) + turned_c * k
    normal = layers[base][1] * (1 - k) + turned_n * k
    target = colour.reshape(-1, 3).mean(0)
    for name, cover, amount, cycles in ((patch, pc, .6, 2), (wear, wc, .3, 4)):
        own_c, own_n = layers[name]
        own_c = own_c * (1 + amount * (target / np.maximum(own_c.reshape(-1, 3).mean(0), .02) - 1))
        noise = _noise(key + cycles, cycles) * .7 + _noise(key + 7 * cycles, 3 * cycles) * .2 + _noise(key + 13 * cycles, 24) * .1
        mask = _cover(noise, cover, own_c.mean(2))
        colour = colour * (1 - mask) + own_c * mask
        normal = normal * (1 - mask) + own_n * mask
    grey = (colour @ np.array([.3, .59, .11], dtype=np.float32))[..., None]
    colour = (grey + (colour - grey) * saturation) * np.array(tone, dtype=np.float32)
    if kind in GROUND_LEVEL:
        colour = colour * (GROUND_LEVEL[kind] / max(float(colour.mean()), .02))
    normal[..., 1] = 1 - normal[..., 1]
    img = lambda a: Image.fromarray(np.clip(a * 255 + .5, 0, 255).astype('uint8'))
    return img(colour), img(normal)


# --- open land: macro colour sheets ------------------------------------------------------------
# Open ground and meadows are one sheet MACRO_M wide (generator.lua COVER_SCALE), not a 24 m photo
# sheet: a 24 m repeat read as one green carpet from a hill and hid the relief. The sheet holds
# only colour, in patches of 2-40 m; the grain is the game's grey terrain detail map over 2 m
# (fast_style.macro_stage), which the engine adds to it. Four lands: the common grass, grass dried
# on slopes and ridges, the lush grass of hollows, and bare loam where the slope is steep.
# Colours are sRGB. The grass is the mean of the tufts streamed over it (the game's
# s_grass_green_short_01..03: 62 83 22, 94 104 50, 122 120 57), so the carpet has no edge.
MACRO_M = 96.0
MACRO_PX = 2048
# kind: base colour, then (colour, cover, cycles, sharpness) patches laid in order
MACRO = {
    # grass and lush: a field seen past the tufts is the tufts with their shade (12.11, land-02:
    # the lit sheet stood 40-50 % brighter and greyer than the carpet's edge)
    # (13.11: blue a little over the tufts' mean, for fast_tone to reach the land's saturation
    # with a factor under its 1.6 cap; the toned colour is what stands beside the tufts)
    'grass': ((71, 92, 35), [((87, 101, 41), .34, 3, .3), ((58, 81, 29), .34, 5, .26),
                             ((104, 110, 50), .08, 9, .12), ((82, 79, 44), .02, 17, .06)]),
    'dry':   ((140, 134, 76), [((158, 148, 88), .34, 4, .28), ((116, 120, 60), .26, 6, .2),
                              ((172, 160, 104), .09, 11, .1), ((122, 104, 70), .04, 15, .06)]),
    'lush':  ((54, 85, 34), [((66, 95, 37), .34, 4, .28), ((43, 70, 30), .30, 6, .22),
                             ((78, 103, 41), .08, 10, .1), ((48, 63, 31), .03, 16, .06)]),
    'earth': ((150, 126, 90), [((166, 142, 102), .32, 4, .26), ((128, 104, 74), .28, 7, .18),
                               ((126, 122, 70), .10, 9, .08), ((108, 88, 64), .05, 19, .06)]),
}


def _srgb(a):
    return np.where(a <= .0031308, a * 12.92, 1.055 * np.clip(a, 1e-6, None) ** (1 / 2.4) - .055)


def _linear(a):
    return np.where(a <= .04045, a / 12.92, ((a + .055) / 1.055) ** 2.4)


def _octaves(seed, cycles):
    """Noise that repeats with the sheet with features from 1/cycles of it down to a few pixels."""
    n = _noise(seed, cycles) * .6 + _noise(seed + 101, min(24, cycles * 3)) * .28
    rng = np.random.default_rng(seed + 7)
    fine = rng.random((MACRO_PX // 8, MACRO_PX // 8), dtype=np.float32)
    fine = np.asarray(Image.fromarray(fine, mode='F').resize((MACRO_PX, MACRO_PX), Image.BICUBIC), dtype=np.float32)
    n = n + (fine - .5) * .12
    return (n - n.min()) / (n.max() - n.min())


def _tiled(seed, cells, px=MACRO_PX):
    """Smooth 0..1 random field of `cells` x `cells` knots that repeats with the sheet (bicubic)."""
    rng = np.random.default_rng(seed)
    n = np.pad(rng.random((cells, cells), dtype=np.float32), 2, mode='wrap')
    big = np.asarray(Image.fromarray(n, mode='F').resize(((cells + 4) * px // cells,) * 2, Image.BICUBIC), dtype=np.float32)
    k = 2 * px // cells
    return big[k:k + px, k:k + px]


# The open land's own relief, in metres over one MACRO_M sheet (fast_style.macro_stage normalMap):
# from a parked car the ground was lit as one plane between the 2 m detail grain and the 25 m
# lattice, like plastic. Mounds of 3-8 m (the ground settling, old furrows, mole runs), tussocks
# of 0.4-1.2 m in patches (grass clumps and the hollows between them) and clods of 10-25 cm.
# Every land shares it, so a piece's two lands (cut_/fade_) lie on the same bumps.
RELIEF_SEED = 6151
# metres of height of the mounds, tussocks and clods
RELIEF_MOUNDS, RELIEF_TUSSOCKS, RELIEF_CLODS = .34, .11, .028


@functools.lru_cache(maxsize=1)
def relief_height():
    s = RELIEF_SEED
    # mounds of 3-8 m (knots every 6 and 3.2 m) over a slow swell of the sheet's own noise
    mounds = (_tiled(s, 16) * .55 + _tiled(s + 1, 30) * .45 - .5) * RELIEF_MOUNDS + (_noise(s + 6, 9) - .5) * .12
    # tussocks: knolls standing out of a lower floor, thick in some patches and gone in others
    t = _tiled(s + 2, 110) * .6 + _tiled(s + 3, 190) * .4
    patch = np.clip((_noise(s + 4, 7) - .25) / .35, 0, 1)
    tussocks = np.clip(t - .4, 0, None) ** 1.3 * patch * (RELIEF_TUSSOCKS / .4 ** 1.3)
    clods = (_tiled(s + 5, 520) * .7 + _tiled(s + 7, 1024) * .3 - .5) * RELIEF_CLODS
    return (mounds + tussocks + clods).astype(np.float32)


def relief_normal():
    """The relief as a normal map (green down, as fast_photo.ground_sheet flips ambientCG's)."""
    h = relief_height()
    texel = MACRO_M / MACRO_PX
    dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) / (2 * texel)
    dy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) / (2 * texel)
    n = np.stack([-dx, dy, np.ones_like(h)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    # green down: a row further down the image is further +v
    n[..., 1] = -n[..., 1]
    return Image.fromarray(np.clip((n * .5 + .5) * 255 + .5, 0, 255).astype('uint8'))


def relief_shade():
    """Light and dark the relief puts into colour: hollows between tussocks and the foot of a
    mound darker, their tops lighter (a multiplier near 1)."""
    h = relief_height()
    small = Image.fromarray(h, mode='F').resize((MACRO_PX // 16,) * 2, Image.BOX)
    pad = np.pad(np.asarray(small, dtype=np.float32), 2, mode='wrap')
    big = np.asarray(Image.fromarray(pad, mode='F').resize(((MACRO_PX // 16 + 4) * 16,) * 2, Image.BICUBIC), dtype=np.float32)
    local = big[32:32 + MACRO_PX, 32:32 + MACRO_PX]
    return np.clip(1 + (h - local) * 3.2, .8, 1.2).astype(np.float32)


# --- fields: one crop a field (generator.lua FIELD, fast_style.FIELDS) --------------------------
# A FIELD_M sheet of rows running along x (the '_y' kinds turn it), colour and height. July in
# the steppe: ploughed black soil in furrows, ripe wheat with a tractor's tramlines, stubble with
# the combine's swaths, sunflower or maize in rows over dark soil. Rows repeat as fields do, so a
# sheet's tiling does not show; the old sheet's 12 m blots of straw on soil did (a checker).
FIELD_M = 32.0
FIELD_PX = 2048
FIELD_CROPS = ('soil', 'wheat', 'stubble', 'rows')


def _photo_sheet(name, metres, which='albedo'):
    """A photo set tiled over the FIELD_M sheet (metres a repeat), with a turned copy over half of
    it on a noise mask to hide its grid; float RGB 0..1 (sRGB)."""
    repeats = max(1, round(FIELD_M / metres))
    cell = FIELD_PX // repeats
    im = Image.open(TEXTURES / name / f'{which}.jpg').convert('RGB').resize((cell, cell), Image.LANCZOS)
    tile = np.asarray(im, dtype=np.float32) / 255
    sheet = np.tile(tile, (repeats, repeats, 1))[:FIELD_PX, :FIELD_PX]
    if sheet.shape[0] != FIELD_PX:
        sheet = np.asarray(Image.fromarray((sheet * 255).astype('uint8')).resize((FIELD_PX, FIELD_PX), Image.LANCZOS),
                           dtype=np.float32) / 255
    turned = np.roll(np.rot90(sheet), (cell // 2, cell // 3), (0, 1))
    k = np.clip((_tiled(len(name) * 31 + 7, 12, FIELD_PX) - .4) / .2, 0, 1)[..., None]
    return sheet * (1 - k) + turned * k


def _rows(period_m, wobble_m, seed):
    """Across-row phase 0..1 of every texel (rows along x, wobbling `wobble_m` along them)."""
    v = np.arange(FIELD_PX, dtype=np.float32)[:, None] * (FIELD_M / FIELD_PX)
    bend = (_tiled(seed, 8, FIELD_PX) - .5) * 2 * wobble_m
    return ((v + bend) / period_m) % 1.0


def _tint(grey, dark, light):
    """A luminance 0..1 mapped between two sRGB colours."""
    d, l = np.array(dark, np.float32) / 255, np.array(light, np.float32) / 255
    return d + (l - d) * grey[..., None]


def _lum(rgb):
    return rgb @ np.array([.3, .59, .11], dtype=np.float32)


def _norm01(a):
    lo, hi = np.percentile(a, 1), np.percentile(a, 99)
    return np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1)


@functools.lru_cache(maxsize=4)
def field_sheet(crop):
    """(colour float RGB sRGB 0..1, height in metres) of a crop's sheet, rows along x."""
    texel = FIELD_M / FIELD_PX
    slow = _noise(FIELD_CROPS.index(crop) * 17 + 5, 3) - .5   # a sway of shade over the sheet
    v = np.arange(FIELD_PX, dtype=np.float32)[:, None] * texel
    if crop == 'soil':
        photo = _photo_sheet('mat_soil', 2.0)
        grain = _norm01(_lum(photo))
        phase = _rows(.42, .05, 11)
        ridge = .5 - .5 * np.cos(phase * 2 * np.pi)               # 1 on the ridge, 0 in the furrow
        clods = _tiled(12, 640, FIELD_PX)
        height = ridge * .055 + (clods - .5) * .03 + (grain - .5) * .012
        shade = .78 + .3 * ridge + .14 * (clods - .5) + .18 * slow
        colour = _tint(grain, (40, 33, 28), (104, 88, 74)) * shade[..., None]
        # the drier crest of a ridge a little paler and greyer
        colour = colour * (1 - .12 * ridge[..., None]) + np.array([.42, .38, .34], np.float32) * .12 * ridge[..., None]
    elif crop == 'wheat':
        blades = _norm01(_lum(_photo_sheet('photo_meadow', 1.6)))
        ears = _tiled(21, 900, FIELD_PX)
        drills = .5 - .5 * np.cos(_rows(.15, .02, 22) * 2 * np.pi)
        height = (blades - .5) * .05 + (ears - .5) * .04 + drills * .015
        # tramlines: two bare wheel tracks 1.8 m apart every 16 m
        track = np.zeros_like(v[:, 0])
        for centre in (7.1, 8.9, 23.1, 24.9):
            track = np.maximum(track, np.clip(1 - np.abs(v[:, 0] - centre) / .28, 0, 1))
        track = track[:, None] * np.ones((1, FIELD_PX), np.float32)
        height = height * (1 - track) - .12 * track
        g = np.clip(blades * .7 + ears * .3, 0, 1)
        colour = _tint(g, (126, 98, 46), (222, 192, 118)) * (.94 + .2 * slow)[..., None]
        soil = _tint(_norm01(_lum(_photo_sheet('mat_soil', 2.0))), (66, 54, 42), (128, 108, 84))
        colour = colour * (1 - track[..., None] * .85) + soil * track[..., None] * .85
    elif crop == 'stubble':
        photo = _photo_sheet('mat_stubble', 2.0)
        grain = _norm01(_lum(photo))
        straw = _tiled(31, 700, FIELD_PX)
        drills = .5 - .5 * np.cos(_rows(.15, .02, 32) * 2 * np.pi)
        # the combine's swaths: bands of 8 m a little paler and darker in turn
        swath = .5 + .5 * np.sign(np.sin(v / 8.0 * np.pi))
        height = (grain - .5) * .03 + drills * .02 + (straw - .5) * .015
        colour = photo * (.9 + .1 * swath + .16 * slow)[..., None]
        colour = _tint(grain, (104, 84, 56), (204, 182, 132)) * .55 + colour * .45
    else:   # rows: sunflower or maize, a broad band of leaves over every 2/3 m of dark soil
        # (48 rows to the sheet, centred 1/3 m off its edge: the grid of detail.lua's row tufts)
        leaves = _norm01(_lum(_photo_sheet('photo_meadow', 2.4)))
        phase = _rows(2 / 3, .04, 41)
        # plants every 0.3 m along the row, each a clump a little apart from the next
        u = np.arange(FIELD_PX, dtype=np.float32)[None, :] * texel
        plant = .5 + .5 * np.cos((u / .3 + _tiled(42, 40, FIELD_PX) * 3) * 2 * np.pi)
        across = np.clip(1 - np.abs(phase - .5) / (.33 + .06 * plant), 0, 1)
        canopy = np.clip(across * 1.6 - .2, 0, 1)
        canopy = canopy * (.82 + .3 * _tiled(43, 160, FIELD_PX))
        canopy = np.clip(canopy, 0, 1)
        height = canopy * .12 + (leaves - .5) * .02 * canopy
        green = _tint(leaves, (38, 58, 24), (112, 138, 60)) * (.92 + .2 * slow)[..., None]
        soil = _tint(_norm01(_lum(_photo_sheet('mat_soil', 2.0))), (44, 36, 30), (108, 92, 76))
        colour = soil * (1 - canopy[..., None]) + green * canopy[..., None]
    return np.clip(colour, 0, 1).astype(np.float32), height.astype(np.float32)


def field_images(crop, along_y=False):
    """(colour, normal) images of a crop's sheet; along_y turns the rows to run along y."""
    colour, height = field_sheet(crop)
    if along_y:
        colour, height = np.rot90(colour), np.rot90(height)
    texel = FIELD_M / FIELD_PX
    dx = (np.roll(height, -1, 1) - np.roll(height, 1, 1)) / (2 * texel)
    dy = (np.roll(height, -1, 0) - np.roll(height, 1, 0)) / (2 * texel)
    n = np.stack([-dx, dy, np.ones_like(height)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    n[..., 1] = -n[..., 1]
    img = lambda a: Image.fromarray(np.clip(a * 255 + .5, 0, 255).astype('uint8'))
    return img(colour), img(n * .5 + .5)


def macro_sheet(kind):
    """The colour image of one land's MACRO_M sheet. Blended in linear light."""
    base, patches = MACRO[kind]
    key = int.from_bytes(hashlib.sha256(('macro_' + kind).encode()).digest()[:4], 'big') % 100000
    colour = np.empty((MACRO_PX, MACRO_PX, 3), np.float32)
    colour[:] = _linear(np.array(base, np.float32) / 255)
    for index, (rgb, cover, cycles, soft) in enumerate(patches):
        noise = _octaves(key + 31 * index, cycles)
        edge = np.quantile(noise, 1 - cover)
        t = np.clip((noise - (edge - soft)) / (2 * soft), 0, 1)
        mask = (t * t * (3 - 2 * t))[..., None]
        colour = colour * (1 - mask) + _linear(np.array(rgb, np.float32) / 255) * mask
    # a slow change of brightness over the sheet, so no two fields of it read the same
    shade = _noise(key + 977, 2) * .7 + _noise(key + 978, 5) * .3
    colour = colour * (.86 + .28 * shade[..., None])
    # clumps of 1-3 m and a grain of 10-20 cm: from a hill the 2 m detail map is too fine to see,
    # and a sheet of smooth colour read as plastic
    rng = np.random.default_rng(key + 5)
    for cells, amount in ((MACRO_PX // 40, .16), (MACRO_PX // 12, .12), (MACRO_PX // 3, .12)):
        n = np.pad(rng.random((cells, cells), dtype=np.float32), 2, mode='wrap')
        big = np.asarray(Image.fromarray(n, mode='F').resize(((cells + 4) * MACRO_PX // cells,) * 2, Image.BICUBIC), dtype=np.float32)
        k = 2 * MACRO_PX // cells
        colour = colour * (1 + amount * (big[k:k + MACRO_PX, k:k + MACRO_PX, None] - .5))
    # the relief's own light and dark, at the same places as its normals (relief_normal)
    colour = colour * relief_shade()[..., None]
    return Image.fromarray(np.clip(_srgb(colour) * 255 + .5, 0, 255).astype('uint8'))


def blend_mask():
    """The opacity map the lands dissolve into each other by (generator.lua VEG.land): blobs of
    2-12 m with every grey level over the same share of the sheet, so an alpha test at ref
    covers 1 - ref / 255 of it. fast_dds keeps that in every mip ('uniform')."""
    n = _noise(4211, 9) * .5 + _noise(4212, 21) * .32
    rng = np.random.default_rng(4213)
    fine = rng.random((MACRO_PX // 4, MACRO_PX // 4), dtype=np.float32)
    n = n + np.asarray(Image.fromarray(fine, mode='F').resize((MACRO_PX, MACRO_PX), Image.BICUBIC), dtype=np.float32) * .08
    rank = np.argsort(np.argsort(n, axis=None)).reshape(n.shape)
    grey = (rank * (255.999 / rank.size)).astype('uint8')
    return Image.fromarray(grey).convert('RGB').resize((1024, 1024), Image.BOX)


def available():
    return (TEXTURES / 'panelka_panels/albedo.jpg').exists() and (TEXTURES / 'photo_lawn/albedo.jpg').exists()


# --- which wall --------------------------------------------------------------------------------
NAMED = {   # OSM building:colour words -> tint family hint
    'white': 'white', 'grey': 'grey', 'gray': 'grey', 'beige': 'beige', 'cream': 'cream', 'yellow': 'yellow',
    'pink': 'pink', 'red': 'red', 'brown': 'red', 'blue': 'blue', 'lightblue': 'blue', 'green': 'green',
    'orange': 'peach', 'peach': 'peach', 'silver': 'grey', 'tan': 'beige', 'ivory': 'cream',
}


def colour_word(value):
    """An OSM colour (name or #rrggbb) as one of the tint words above, or None."""
    if not value:
        return None
    v = str(value).strip().lower()
    if v in NAMED:
        return NAMED[v]
    if v.startswith('#') and len(v) == 7:
        try:
            r, g, b = (int(v[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            return None
        hi, lo = max(r, g, b), min(r, g, b)
        if hi - lo < 24:
            return 'white' if hi > 200 else 'grey'
        if r >= g and r >= b:
            return 'pink' if b > g * .9 else ('yellow' if g > r * .8 else ('peach' if g > r * .6 else 'red'))
        if g >= r and g >= b:
            return 'green'
        return 'blue'
    return None


def pick(options, word, h):
    """An option whose name has the colour word, else a stable choice by hash."""
    if word:
        hit = [o for o in options if o.split('_')[1] == word]
        if hit:
            return hit[h % len(hit)]
    return options[h % len(options)]


def end_walls(points):
    """Per edge of a footprint ring (x, y pairs, not closed): True for the short walls across
    the long axis of an elongated block (length >= 1.6 x width), as Earth2Road's end_walls."""
    n = len(points)
    mask = [False] * n
    if n < 3:
        return mask
    edges = [(points[(i + 1) % n][0] - points[i][0], points[(i + 1) % n][1] - points[i][1]) for i in range(n)]
    longest = max(edges, key=lambda d: d[0] ** 2 + d[1] ** 2)
    norm = (longest[0] ** 2 + longest[1] ** 2) ** .5
    if norm < 1e-6:
        return mask
    ax, ay = longest[0] / norm, longest[1] / norm
    along = [p[0] * ax + p[1] * ay for p in points]
    across = [-p[0] * ay + p[1] * ax for p in points]
    length, width = max(along) - min(along), max(across) - min(across)
    if length < 1.6 * width:
        return mask
    for i, (dx, dy) in enumerate(edges):
        d = (dx * dx + dy * dy) ** .5
        if d > 1e-6 and abs((dx * ax + dy * ay) / d) < .5 and d <= min(width * 1.05 + .5, END_WALL_MAX_M):
            mask[i] = True
    return mask
