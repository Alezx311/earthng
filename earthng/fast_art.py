"""Facade textures and texture packs for the fast generator.

A facade texture is one window cell, 3 m wide and one 3 m floor high; walls carry their own
UVs (u along the building outline, v up from its base), so the windows sit on floors. The
'real' pack draws the windows over the game's own wall textures (read from its asset zips,
nothing shipped); 'toon' and 'model' are flat stylisations. Written once per user folder:

    <user>/e2r_stream/fast-art/<VERSION>/<pack>/<style>.color.png
    <user>/e2r_stream/fast-art/<VERSION>/packs.json     material fields per pack (in-game switch)
"""
import io
import json
import os
from pathlib import Path
import zipfile

from PIL import Image, ImageChops, ImageDraw, ImageFont

import fast_packs
import fast_pixel
import fast_photo as photo
import fast_style as style

VERSION = 'v10'
CELL = 3.0          # m per texture repeat on walls: one window, one floor
PX = 1024           # texture size: as the game's own (a 256 px swap kept its 1024 mip chain and failed)


def game_dir():
    """The BeamNG.drive install: BEAMNG_DIR, else the Steam libraries (registry and
    libraryfolders.vdf), else the default Steam folder. None when not found."""
    import os, re
    candidates = []
    if os.environ.get('BEAMNG_DIR'):
        candidates.append(Path(os.environ['BEAMNG_DIR']))
    steam = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as k:
            steam.append(Path(winreg.QueryValueEx(k, 'SteamPath')[0]))
    except (OSError, ImportError):   # ImportError: no winreg off Windows
        pass
    steam.append(Path(r'C:/Program Files (x86)/Steam'))
    home = Path.home()   # Linux (the game under Proton): native and Flatpak Steam
    steam += [home / '.steam/steam', home / '.local/share/Steam',
              home / '.var/app/com.valvesoftware.Steam/.local/share/Steam']
    for root in steam:
        vdf = root / 'steamapps' / 'libraryfolders.vdf'
        libs = [root]
        if vdf.exists():
            libs += [Path(m.replace('\\', '/')) for m in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(errors='ignore'))]
        candidates += [lib / 'steamapps' / 'common' / 'BeamNG.drive' for lib in libs]
    for c in candidates:
        if (c / 'content' / 'assets' / 'materials').exists():
            return c
    return None


GAME = game_dir()
# the game's texture zips; without them the 'real' facades fall back to flat colours
ASSETS = (GAME / 'content' / 'assets' / 'materials') if GAME else Path('missing')

# wall style: (flat colour for toon, window kind) -- 'band' = office strip glazing
FACADES = {
    'panel':       ((222, 214, 196), 'panel'),
    'precast':     ((205, 200, 190), 'panel'),
    'brick':       ((176, 112, 86), 'window'),
    'brick_red':   ((160, 82, 64), 'window'),
    'brick_white': ((236, 232, 222), 'window'),
    'plaster':     ((238, 214, 170), 'window'),
    'stucco':      ((244, 240, 228), 'window'),
    'glass':       ((120, 160, 190), 'band'),
    'windows':     ((150, 170, 180), 'band'),
    'block':       ((170, 170, 165), 'small'),
}
ROOF = {'toon': (120, 96, 92), 'model': (210, 210, 210)}
FLAT = {   # kind: (toon colour, model colour)
    'road': ((92, 96, 110), (120, 120, 124)), 'road_major': ((80, 84, 98), (110, 110, 114)),
    'sidewalk': ((214, 204, 190), (236, 236, 236)), 'mark': ((250, 250, 240), (255, 255, 255)),
    'ground': ((126, 196, 112), (226, 228, 222)), 'forest': ((84, 150, 90), (200, 204, 198)),
    'paved': ((190, 184, 176), (220, 220, 220)), 'water': ((96, 176, 220), (180, 200, 214)),
    'roof': ((120, 96, 92), (210, 210, 210)), 'curb': ((240, 240, 240), (250, 250, 250)),
    'park': ((126, 196, 112), (226, 228, 222)), 'roof_tile': ((176, 84, 62), (200, 200, 200)),
    'roof_metal': ((96, 120, 116), (205, 205, 205)), 'parapet': ((200, 196, 190), (236, 236, 236)),
    'roof_sheet': ((160, 160, 152), (212, 212, 212)), 'roof_mtile_red': ((168, 64, 52), (204, 204, 204)),
    'roof_mtile_brown': ((120, 86, 72), (200, 200, 200)), 'roof_mtile_green': ((72, 120, 92), (206, 206, 206)),
    'door_garage': ((128, 134, 140), (222, 222, 222)), 'door_rust': ((140, 98, 74), (218, 218, 218)),
    'clad_metal': ((196, 204, 212), (232, 232, 232)), 'clad_tin': ((156, 128, 108), (220, 220, 220)),
    'plinth': ((132, 126, 118), (214, 214, 214)),
    'gable': ((150, 128, 104), (216, 216, 216)),
    'hw_white': ((240, 236, 226), (238, 238, 238)), 'hw_yellow': ((236, 206, 128), (232, 232, 232)),
    'hw_blue': ((172, 200, 222), (230, 230, 230)), 'hw_green': ((186, 212, 170), (232, 232, 232)),
    'hw_pink': ((232, 194, 182), (234, 234, 234)), 'hw_aged': ((204, 192, 160), (228, 228, 228)),
    'hw_brick_red': ((176, 96, 74), (222, 222, 222)), 'hw_silicate': ((226, 222, 210), (236, 236, 236)),
    'hw_oldbrick': ((140, 72, 58), (214, 214, 214)), 'hw_flatbrick': ((186, 118, 90), (220, 220, 220)),
    'hw_stone': ((168, 164, 154), (226, 226, 226)), 'hw_boards': ((196, 176, 140), (224, 224, 224)),
    'hw_siding': ((206, 196, 166), (230, 230, 230)), 'hw_wood': ((112, 88, 66), (210, 210, 210)),
    'win_pvc': ((70, 96, 120), (180, 190, 200)), 'win_wood': ((96, 74, 56), (176, 176, 176)),
    'door_house': ((110, 76, 54), (190, 190, 190)), 'plinth_brown': ((120, 74, 60), (206, 206, 206)),
}
BASE_PACKS = ('real', 'toon', 'model', 'synth')
PACKS = BASE_PACKS + ('pixel',) + fast_packs.PACKS
LABELS = {'real': 'Реальний', 'toon': 'Мультяшний', 'model': 'Макет', 'synth': 'Синтвейв', 'pixel': 'Ретро-місто', **fast_packs.LABELS}
MAP_FIELDS = ('baseColorMap', 'normalMap', 'roughnessMap', 'ambientOcclusionMap', 'emissiveMap', 'opacityMap', 'detailMap',
              'detailNormalMap', 'roughnessDetailMap')
# synthwave: dark violet surfaces, neon lines glowing (emissive), a striped sun at the horizon
SYNTH = {
    'road': (22, 16, 44), 'road_major': (26, 18, 52), 'sidewalk': (44, 30, 78), 'paved': (30, 20, 60),
    'water': (14, 10, 46), 'roof': (34, 22, 62), 'ground': (20, 8, 40), 'forest': (16, 6, 34),
    'roof_tile': (40, 20, 60), 'roof_metal': (30, 22, 60), 'parapet': (36, 22, 64),
}
SYNTH_GLOW = {'mark': (0.0, 1.0, 1.0), 'curb': (1.0, 0.1, 0.8)}   # emissive lines on the roads
NEON = (255, 40, 200)       # grid magenta
CYAN = (0, 240, 255)


def root(user):
    return Path(user) / 'e2r_stream' / 'fast-art' / VERSION


def game_texture(path):
    """A /assets/... .png map of the game, decoded from its .dds in the asset zips."""
    rel = path.lstrip('/')[:-4] + '.dds'
    for zip_name in ('tileable.zip', 'terrain.zip'):
        z = ASSETS / zip_name
        if z.exists():
            with zipfile.ZipFile(z) as zf:
                if rel in zf.namelist():
                    return Image.open(io.BytesIO(zf.read(rel))).convert('RGB')
    return None


def draw_windows(im, kind, pack):
    """Windows in world orientation (floor at the bottom of the picture)."""
    d = ImageDraw.Draw(im)
    s = PX / CELL
    glass = {'real': (52, 66, 82), 'toon': (150, 205, 235), 'model': (190, 190, 192), 'synth': (40, 10, 70)}[pack]
    frame = {'real': (225, 225, 220), 'toon': (60, 60, 70), 'model': (245, 245, 245), 'synth': CYAN}[pack]
    if kind == 'band':
        d.rectangle([0, s * .55, PX, s * 2.75], fill=glass)
        for x in range(0, PX, int(s * 1.5)):
            d.rectangle([x, s * .55, x + 2, s * 2.75], fill=frame)
        d.rectangle([0, s * .5, PX, s * .6], fill=frame)
        return
    if kind == 'small':
        x0, x1, y0, y1 = .9, 2.1, .6, 1.4
    else:
        x0, x1, y0, y1 = .8, 2.2, .6, 2.1         # 1.4 x 1.5 m window, sill 0.9 m up
    box = [s * x0, PX - s * y1, s * x1, PX - s * y0]
    d.rectangle([box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4], fill=frame)
    d.rectangle(box, fill=glass)
    mid = (box[0] + box[2]) / 2
    d.rectangle([mid - 2, box[1], mid + 2, box[3]], fill=frame)          # mullion
    d.rectangle([box[0] - 8, box[3] + 4, box[2] + 8, box[3] + 10], fill=frame)   # sill
    if kind == 'panel':                          # precast panel joints at the cell edges
        line = tuple(max(0, c - 40) for c in im.getpixel((2, 2)))
        d.rectangle([0, PX - 3, PX, PX], fill=line)
        d.rectangle([0, 0, 2, PX], fill=line)


def facade(name, pack, game_assets=True):
    colour, kind = FACADES[name]
    if pack == 'real':
        tex = game_texture(style.TEXTURES[name]['baseColorMap']) if game_assets else None
        if tex is None:
            im = Image.new('RGB', (PX, PX), colour)
        else:
            # the game texture spans 4 m; this cell is 3 m of it
            w, h = tex.size
            im = tex.crop((0, 0, int(w * CELL / 4), int(h * CELL / 4))).resize((PX, PX), Image.LANCZOS)
    elif pack == 'synth':
        im = Image.new('RGB', (PX, PX), (24, 14, 46))
    else:
        im = Image.new('RGB', (PX, PX), colour if pack == 'toon' else (238, 238, 236))
    draw_windows(im, kind, pack)
    # UV v grows with height and image rows grow downward: store it upside down
    return im.transpose(Image.FLIP_TOP_BOTTOM)


def stylised(name, pack, glow=False):
    """A photo wall's stand-in in a flat pack: its window cell tiled over the wall's repeat
    (2 x 2 cells for 6 m, 11 x 11 for the 33 m loggia sheet), upside down like facade()."""
    family, colour, metres = photo.PHOTO_WALLS[name]
    kind = None if family.startswith('end_') else ('panel' if family in ('panel', 'loggia') else 'window')
    if glow:
        cell = Image.new('RGB', (PX, PX), (0, 0, 0))
    elif pack == 'toon':
        cell = Image.new('RGB', (PX, PX), tuple(round(c * 255) for c in colour))
    elif pack == 'synth':
        cell = Image.new('RGB', (PX, PX), (24, 14, 46))
    else:
        cell = Image.new('RGB', (PX, PX), (238, 238, 236))
    if kind:
        draw_windows(cell, kind, 'synth' if glow else pack)
    if glow:
        mask = cell.point(lambda v: 255 if v > 200 else 0).convert('L')
        cell = Image.new('RGB', (PX, PX), (0, 0, 0))
        cell.paste(Image.new('RGB', (PX, PX), CYAN), mask=mask)
    n = max(1, round(metres / CELL))
    size = 2048 if n > 4 else PX
    step = size // n
    small = cell.resize((step, step), Image.LANCZOS)
    out = Image.new('RGB', (size, size))
    for i in range(n):
        for j in range(n):
            out.paste(small, (i * step, j * step))
    return out.resize((size, size)).transpose(Image.FLIP_TOP_BOTTOM)


def photo_real(name):
    """(colour, normal or None) of a photo wall for the 'real' pack, upside down like facade():
    texture v grows with height. A flipped normal map's green (tangent y) is inverted too."""
    im, nm = photo.wall_image(name, LAYERS[0] if LAYERS else None)
    im = im.transpose(Image.FLIP_TOP_BOTTOM)
    if nm is not None:
        r, g, b = nm.transpose(Image.FLIP_TOP_BOTTOM).split()
        nm = Image.merge('RGB', (r, g.point(lambda v: 255 - v), b))
    return im, nm


LAYERS = []

# Roads (fetch_textures.ROAD_SETS, CC0 photos), laid out as the game's own roads are: a base over
# the generator's road repeat (style.ROAD_M, generator.lua COVER_SCALE) and a fine detail over
# style.DETAIL_M through the detail maps. The base is Poly Haven's 30 m aerial photo of a street
# (cracks, patches, tyre marks; 4K, ~7 mm a texel); the detail is a 2 m photo at full size (~1 mm
# a texel) of each asphalt. Two 3 m photos squeezed into a 6 m repeat were blurred, and their
# stains drew a grid (park-vis-02).
BASE_PX, DETAIL_PX = 4096, 2048
BASE_MEAN, BASE_ROUGH = .12, .8     # linear albedo of the brightest asphalt; the others are tinted down
BASE_SATURATION = .5                # the aerial's purple cast
# The game adds a detail map to the base: base + (2 * detail - 1) * strength (defaultMat.hlsl
# blendDetail), linear. So a detail is the photo's own contrast around 0.5, without what is
# wider than DETAIL_SIGMA texels (it would repeat every 2 m); 4 sigma of it reach 0 and 1.
DETAIL_SIGMA = 48
# The paint of a line (ambientCG RoadLines025B: a worn solid line 21 px wide down the sheet's
# left edge), cut so the paint fills 1 / markSpread of the strip (generator.lua DECAL).
LINE_COLUMNS = (5, 36)
LINE_SIZE = (64, 2048)


def _srgb_to_linear(a):
    import numpy as np
    return np.where(a <= .04045, a / 12.92, ((a + .055) / 1.055) ** 2.4)


def _linear_to_srgb(a):
    import numpy as np
    return np.where(a <= .0031308, 12.92 * a, 1.055 * np.maximum(a, 0) ** (1 / 2.4) - .055)


def _blur_wrap(a, sigma):
    """Gaussian blur of a 2D array that wraps at the edges, as the repeat does."""
    import numpy as np
    fy, fx = np.fft.fftfreq(a.shape[0])[:, None], np.fft.fftfreq(a.shape[1])[None, :]
    return np.real(np.fft.ifft2(np.fft.fft2(a) * np.exp(-2 * (np.pi * sigma) ** 2 * (fx * fx + fy * fy))))


def road_sheets(r):
    """The roads' base, the detail maps of each asphalt and the line paint as PNGs in r/real
    (build turns them into DDS)."""
    import numpy as np

    def load(path, mode, size):
        return np.asarray(Image.open(path).convert(mode).resize((size, size), Image.LANCZOS), np.float32) / 255

    def save(a, path):
        Image.fromarray((np.clip(a, 0, 1) * 255 + .5).astype(np.uint8)).convert('RGB').save(path)

    def normal(path, size, sigma=None):
        # green flipped for the game, as the paths'; a detail loses its slopes wider than sigma
        n = load(path, 'RGB', size) * 2 - 1
        nx, ny = n[..., 0], n[..., 1]
        if sigma:
            nx, ny = nx - _blur_wrap(nx, sigma), ny - _blur_wrap(ny, sigma)
        nz = np.sqrt(np.clip(1 - nx * nx - ny * ny, 0, 1))
        return np.stack([nx, -ny, nz], -1) * .5 + .5

    def detail(a):
        hp = a - _blur_wrap(a, DETAIL_SIGMA)
        return .5 + .5 * np.clip(hp / (4 * hp.std()), -1, 1)

    out = r / 'real'
    out.mkdir(parents=True, exist_ok=True)
    src = photo.TEXTURES / 'road_macro'
    lin = _srgb_to_linear(load(src / 'albedo.jpg', 'RGB', BASE_PX))
    lum = lin @ np.array([.2126, .7152, .0722], np.float32)
    lin = lum[..., None] + (lin - lum[..., None]) * BASE_SATURATION
    save(_linear_to_srgb(lin * (BASE_MEAN / lin.mean())), out / 'road_base.color.png')
    save(normal(src / 'normal.jpg', BASE_PX), out / 'road_base.normal.png')
    ra = load(src / 'roughness.jpg', 'L', DETAIL_PX)
    save(np.clip(ra - ra.mean() + BASE_ROUGH, .05, 1), out / 'road_base.data.png')
    # the cracks' occlusion, softened: a whole street under it was darker in every light
    save(1 - (1 - load(src / 'ao.jpg', 'L', DETAIL_PX)) * .5, out / 'road_base_ao.data.png')
    for name in ('road_city', 'road_worn', 'road_fresh'):
        src = photo.TEXTURES / name
        lum = _srgb_to_linear(load(src / 'albedo.jpg', 'L', DETAIL_PX))
        save(detail(lum / max(lum.mean(), 1e-4)), out / f'{name}_dc.data.png')
        save(normal(src / 'normal.jpg', DETAIL_PX, DETAIL_SIGMA), out / f'{name}_dn.normal.png')
        save(detail(load(src / 'roughness.jpg', 'L', DETAIL_PX)), out / f'{name}_dr.data.png')
    src = photo.TEXTURES / 'road_line'
    box = (LINE_COLUMNS[0], 0, LINE_COLUMNS[1], 2048)

    def strip(m, mode='RGB'):
        return Image.open(src / f'{m}.jpg').convert(mode).crop(box).resize(LINE_SIZE, Image.LANCZOS)
    alpha = np.asarray(strip('opacity', 'L'), np.float32) / 255
    # white paint: the yellow sheet's brightness, its mean set to an aged white line; the texels
    # around the paint take that mean too, so no dark fringe creeps in with the mips
    lum = np.asarray(strip('albedo', 'L'), np.float32) / 255
    paint = lum[alpha > .5].mean()
    lum = np.where(alpha > .5, lum * (.8 / paint), .8)
    Image.fromarray((np.clip(lum, 0, 1) * 255 + .5).astype(np.uint8)).convert('RGB').save(out / 'line.color.png')
    rr, g, b = strip('normal').split()
    Image.merge('RGB', (rr, g.point(lambda v: 255 - v), b)).save(out / 'line.normal.png')
    strip('roughness').save(out / 'line.data.png')
    Image.fromarray((alpha * 255 + .5).astype(np.uint8)).convert('RGB').save(out / 'line_o.data.png')


def synth_glow(name):
    """Emissive map for a synthwave facade: only the neon window frames light up."""
    im = Image.new('RGB', (PX, PX), (0, 0, 0))
    draw_windows(im, FACADES[name][1], 'synth')
    mask = im.convert('RGB').point(lambda v: 255 if v > 200 else 0).convert('L')
    out = Image.new('RGB', (PX, PX), (0, 0, 0))
    out.paste(Image.new('RGB', (PX, PX), CYAN), mask=mask)
    return out.transpose(Image.FLIP_TOP_BOTTOM)


def synth_grid(base, glow=False):
    """One ground repeat with neon lines on its edges (the Outrun grid)."""
    im = Image.new('RGB', (PX, PX), (0, 0, 0) if glow else base)
    d = ImageDraw.Draw(im)
    w = PX // 64
    d.rectangle([0, 0, PX, w], fill=NEON); d.rectangle([0, 0, w, PX], fill=NEON)
    return im


def synth_sun():
    """The sun: yellow to magenta from the top, cut by widening gaps in its lower half."""
    im = Image.new('RGBA', (PX, PX), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for y in range(PX):
        t = y / PX
        if t > .5 and (t * 18) % 1 < .15 + .45 * (t - .5) / .5:
            continue
        half = (max(0., (PX / 2) ** 2 - (y - PX / 2) ** 2)) ** .5
        if half > 0:
            d.line([(PX / 2 - half, y), (PX / 2 + half, y)], fill=(255, int(230 - 200 * t), int(60 + 140 * t), 255))
    return im


def colour(rgb, alpha=1):
    return ' '.join(f'{c / 255:.3f}' for c in rgb) + f' {alpha:g}'


def stylised_decal(kind, f):
    """Road decals in a flat-coloured pack: lines keep the worn paint's outline (their quads are
    wider than the paint), the edge decals are hidden (a flat band over the asphalt edge)."""
    if kind in ('mark', 'mark_yellow'):
        f['opacityMap'] = style.TEXTURES['line_worn']['opacityMap']
    elif kind in style.EDGES:
        f['opacityFactor'] = 0


def pack_fields(pack, base):
    """Material name -> stage-0 fields for one pack (all map fields present, '' clears)."""
    if pack == 'pixel':
        return fast_pixel.fields(base)
    if pack in fast_packs.PACKS:
        return fast_packs.fields(pack, base, pack_fields('real', base))
    out = {}
    for kind, (tex, fallback, _, _, mode) in style.KINDS.items():
        f = {k: '' for k in MAP_FIELDS}
        f['emissiveFactor'] = '0 0 0'
        if kind.startswith('wall_'):
            w = kind[5:]
            f['baseColorMap'] = f'{base}/{pack}/{w}.color.png'
            if pack == 'real':
                f.update(style.real_stage(kind))
            if pack == 'synth':
                f['emissiveMap'] = f'{base}/synth/{w}.glow.png'; f['emissiveFactor'] = '1 1 1'
            f['baseColorFactor'] = '1 1 1 1'
        elif pack == 'real':
            if kind in style.TURF or kind in style.PHOTO_GROUND:
                f.update(style.real_stage(kind))
                f['baseColorFactor'] = '1 1 1 1'
            elif kind in style.nature.NATURAL:
                f.update(style.real_stage(kind))
                f['baseColorFactor'] = colour([c * 255 for c in style.TINT[kind][:3]])
            elif tex:
                f.update(style.TEXTURES[tex])
                tint = style.TINT.get(kind, [1, 1, 1, 1])
                f['baseColorFactor'] = colour([c * 255 for c in tint[:3]], tint[3] if len(tint) > 3 else 1)
            else:
                f['baseColorFactor'] = colour([c * 255 for c in fallback[:3]])
        elif pack == 'synth':
            if kind in ('ground', 'forest', 'paved', 'park'):
                f['baseColorMap'] = f'{base}/synth/grid_{"ground" if kind == "park" else kind}.color.png'
                f['emissiveMap'] = f'{base}/synth/grid.glow.png'; f['emissiveFactor'] = '1 1 1'
                f['baseColorFactor'] = '1 1 1 1'
            elif kind in SYNTH_GLOW:
                g = SYNTH_GLOW[kind]
                f['baseColorFactor'] = colour([c * 255 for c in g]); f['emissiveFactor'] = ' '.join(map(str, g))
            else:
                f['baseColorFactor'] = colour(SYNTH.get(kind, (30, 20, 50)))
        else:
            f['baseColorFactor'] = colour(FLAT.get(kind, ((200, 200, 200), (230, 230, 230)))[0 if pack == 'toon' else 1])
        if kind in ('brand_sign', 'brand_photo'):
            f['baseColorMap'] = f'{base}/real/{kind}.color.png'
            f['baseColorFactor'] = '1 1 1 1'
        if pack != 'real':
            stylised_decal(kind, f)
        # a field is set from a string (detailScale '15.0 15.0')
        out['e2rf_' + kind] = {k: ' '.join(map(str, v)) if isinstance(v, list) else v for k, v in f.items()}
    return out


def environment(pack):
    """Sky and fog per pack: the level's own (earthng/build_mod.SKY) or a synthwave dusk."""
    import build_mod
    sky = {o['name']: o for o in build_mod.SKY}

    def fields(o, keys):
        return {k: (' '.join(map(str, o[k])) if isinstance(o[k], list) else str(o[k])) for k in keys if k in o}
    sun_keys = ('azimuth', 'elevation', 'brightness', 'skyBrightness', 'colorize', 'colorizeAmount', 'fogScale',
                'sunScale', 'ambientScale', 'nightColor', 'nightFogColor', 'nightCubemap')
    info_keys = ('fogColor', 'fogDensity', 'canvasClearColor', 'globalEnviromentMap')
    if pack != 'synth':
        real = {'objects': {'sunsky': {**fields(sky['sunsky'], sun_keys), 'useNightCubemap': '0'}, 'theLevelInfo': fields(sky['theLevelInfo'], info_keys),
                            'clouds': fields(sky['clouds'], ('coverage', 'exposure', 'baseColor'))},
                'sun': False}
        if pack == 'pixel':
            return fast_pixel.environment(real)
        return fast_packs.environment(pack, real) if pack in fast_packs.PACKS else real
    return {'authoredSun': True, 'objects': {
        'sunsky': {'azimuth': '250', 'elevation': '3', 'brightness': '0.45', 'skyBrightness': '6',
                   'colorize': '0.75 0.1 0.95 1', 'colorizeAmount': '4', 'fogScale': '0.55 0.08 0.75 1',
                   'sunScale': '1 0.3 0.8 1', 'ambientScale': '0.45 0.25 0.7 1'},
        'theLevelInfo': {'fogColor': '0.25 0.04 0.38 1', 'fogDensity': '0.00004', 'canvasClearColor': '40 10 60 255'}},
        'sun': {'azimuth': 250, 'distance': 3200, 'size': 1500, 'height': 420, 'material': 'e2rf_synth_sun'}}


def warm_defs(pack, fields):
    """One material per pack and texture, loaded at the landing on a hidden triangle: a texture
    the engine first meets through a runtime map swap streams into a slot sized for the old one
    and breaks (\"dds mip chain (11) does not match texture (9)\", fast-game-packs-02)."""
    out = {}
    for mat, f in fields.items():
        stage = {k: v for k, v in f.items() if k in MAP_FIELDS and v}
        if not stage:
            continue
        name = f'e2rf_pk_{pack}_{mat.removeprefix("e2rf_")}'
        out[name] = {'name': name, 'mapTo': name, 'class': 'Material', 'version': 1.5,
                     'Stages': [stage, {}, {}, {}]}
    return out


# Biome sheets (fast_style.BIOME_GROUND) ship smaller: their normals at 1024 px (2.3 cm a texel
# over the 24 m sheet), and the smooth snow, ice and dune colours too. 2048 px each added 27 MB
# to the planet ZIP.
SMOOTH_GROUND = ('snow', 'snow_edge', 'glacier', 'dune')


def ground_sheet(kind):
    im, nm = photo.ground_sheet(kind)
    if kind in style.BIOME_GROUND or kind == 'glacier':
        nm = nm.resize((1024, 1024), Image.LANCZOS)
        if kind in SMOOTH_GROUND:
            im = im.resize((1024, 1024), Image.LANCZOS)
    return im, nm


def ensure(user):
    """The art in the user folder (the game reads it from there): copied from the shared
    build in data/art/<VERSION>, which is written once (~20 s: photo facades and ground
    sheets). Returns the art root path in the user folder."""
    import shutil
    import paths
    r = root(user)
    if (r / 'packs.json').exists():
        return r
    shared = prebuild()
    # file by file, packs.json last (the marker): renaming a whole folder inside the profile is
    # refused while the game watches it (WinError 5, vis-02-akadem)
    for src in sorted(shared.rglob('*')):
        if src.is_file() and src.name != 'packs.json':
            dst = r / src.relative_to(shared)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    tmp = r / 'packs.json.tmp'
    shutil.copyfile(shared / 'packs.json', tmp)
    os.replace(tmp, r / 'packs.json')
    return r


def prebuild(distributable=False):
    """The shared art build (data/art/<VERSION>), written when missing; returns its path."""
    import paths
    shared = paths.PROJECT / 'data' / ('art-distributable' if distributable else 'art') / VERSION
    if not (shared / 'packs.json').exists():
        build(shared, game_assets=not distributable)
    else:
        if not (shared / 'real' / 'road_base.color.dds').exists():
            # roads came after this build's facades: only they are written
            road_sheets(shared)
            to_dds(shared / 'real')
        # the biome ground sheets came after it too (fast_style.BIOME_GROUND): the missing ones
        missing = [k for k in style.PHOTO_GROUND if not (shared / 'real' / f'ground_{k}.color.dds').exists()]
        if missing:
            for kind in missing:
                im, nm = ground_sheet(kind)
                im.save(shared / 'real' / f'ground_{kind}.color.png'); nm.save(shared / 'real' / f'ground_{kind}.normal.png')
            to_dds(shared / 'real')
        # and the yard's paint and railing (generator.lua YARD)
        if not (shared / 'real' / 'railing_o.data.dds').exists():
            yard_art(shared / 'real')
            to_dds(shared / 'real')
        stamp = shared / 'real' / 'brand_sign.version'
        if not (shared / 'real' / 'brand_photo.glow.dds').exists() or not stamp.exists() or stamp.read_text() != BRAND_ART_VERSION:
            brand_art(shared / 'real')
            to_dds(shared / 'real')
        write_manifest(shared)  # environment/fields are code, not a texture cache
    return shared


def build(r, game_assets=True):
    """Write the facade textures, ground sheets and packs.json into r."""
    base = '/e2r_stream/fast-art/' + VERSION
    done = r / 'packs.json'
    for pack in BASE_PACKS:
        (r / pack).mkdir(parents=True, exist_ok=True)
        for name in FACADES:
            path = r / pack / f'{name}.color.png'
            facade(name, pack, game_assets=game_assets).save(path)
            if pack == 'synth':
                synth_glow(name).save(r / pack / f'{name}.glow.png')
        for name in photo.PHOTO_WALLS:
            if pack == 'real':
                if not LAYERS:
                    LAYERS.append(photo.panel_atlas())
                im, nm = photo_real(name)
                im.save(r / pack / f'{name}.color.png')
                if nm is not None:
                    nm.save(r / pack / f'{name}.normal.png')
            else:
                stylised(name, pack).save(r / pack / f'{name}.color.png')
                if pack == 'synth':
                    stylised(name, pack, glow=True).save(r / pack / f'{name}.glow.png')
    for kind in style.PHOTO_GROUND:
        im, nm = ground_sheet(kind)
        im.save(r / 'real' / f'ground_{kind}.color.png'); nm.save(r / 'real' / f'ground_{kind}.normal.png')
    # footpaths: ambientCG photos as they are (normal green flipped for BeamNG)
    for name, src in (('paving', 'paving'), ('trodden', 'photo_trodden')):
        Image.open(photo.TEXTURES / src / 'albedo.jpg').convert('RGB').resize((1024, 1024), Image.LANCZOS).save(r / 'real' / f'{name}.color.png')
        rr, g, b = Image.open(photo.TEXTURES / src / 'normal.jpg').convert('RGB').resize((1024, 1024), Image.LANCZOS).split()
        Image.merge('RGB', (rr, g.point(lambda v: 255 - v), b)).save(r / 'real' / f'{name}.normal.png')
    # parked cars: one cell per paint colour, then glass and tyre (car_art.CAR_COLOURS)
    import car_art
    cars = Image.new('RGB', (32 * car_art.CAR_ATLAS, 32))
    d = ImageDraw.Draw(cars)
    for k, rgb in enumerate(car_art.CAR_COLOURS + [(36, 44, 52), (22, 22, 22)]):
        d.rectangle([32 * k, 0, 32 * k + 31, 31], fill=rgb)
    cars.save(r / 'real' / 'cars.color.png')
    yard_art(r / 'real')
    brand_art(r / 'real')
    # the PO-2 concrete fence: one 2.5 m x 2 m slab... laid over a 2.5 m repeat, the slab in the
    # lower 0.8 of it (fences are 2 m tall), upside down like the facades
    slab = Image.open(photo.TEXTURES / 'panelka_fence/albedo.jpg').convert('RGB')
    fence = Image.new('RGB', (1024, 1024), (150, 150, 146))
    fence.paste(slab.resize((1024, 820), Image.LANCZOS), (0, 1024 - 820))
    fence.transpose(Image.FLIP_TOP_BOTTOM).save(r / 'real' / 'fence_po2.color.png')
    # chain link: the game's opacity map again, with mips that keep the wire (fast_dds.keep_coverage)
    if game_assets:
        chainlink = game_texture(style.CHAINLINK_OPACITY)
    else:
        # Distributable art contains only our drawing and CC0 photo sources. Game
        # shapes/materials remain references into the player's own installation.
        chainlink = Image.new('RGB', (PX, PX), (0, 0, 0))
        wire = ImageDraw.Draw(chainlink)
        for k in range(-PX, 2 * PX, 64):
            wire.line((k, 0, k + PX, PX), fill=(255, 255, 255), width=5)
            wire.line((k, 0, k - PX, PX), fill=(255, 255, 255), width=5)
    chainlink.save(r / 'real' / 'chainlink_o.data.png')
    for kind in ('ground', 'forest', 'paved'):
        synth_grid(SYNTH[kind]).save(r / 'synth' / f'grid_{kind}.color.png')
    synth_grid(None, glow=True).save(r / 'synth' / 'grid.glow.png')
    synth_sun().save(r / 'synth' / 'sun.color.png')
    road_sheets(r)
    fast_packs.build(r, base)
    fast_pixel.build(r)
    to_dds(r)
    write_manifest(r)
    return r


# alphaRef per opacity map whose mips keep its coverage (fast_dds.keep_coverage)
MIP_REFS = {'chainlink_o.data.png': style.CHAINLINK_MIP_REF, 'line_o.data.png': style.EXTRA['mark']['alphaRef'],
            'railing_o.data.png': style.RAILING_MIP_REF}
# The yard atlas (generator.lua YARD.cell keeps the same order): playground paint, wood, metal,
# sand, container screens and the yellow of the hemisphere bollards.
YARD_COLOURS = [(196, 52, 40), (236, 188, 40), (46, 108, 186), (62, 148, 70), (228, 118, 40), (146, 104, 62),
                (126, 128, 130), (44, 44, 46), (204, 180, 132), (52, 98, 150), (226, 226, 220), (128, 62, 50),
                (162, 160, 152), (214, 184, 58), (122, 178, 92), (92, 62, 40)]


# The shop and fuel station atlas (generator.lua BLD.SHOP): 4 x 16 cells of 512 x 128 px, the
# shape of a lightbox 4 m x 1 m. Cells 0..31 are the networks of retail.ALIASES in the order of
# generator.lua SOLID.BRANDS, 32 and 33 the plain 'АЗС' and 'ПРОДУКТИ' of an unknown network.
# Cells 34-35, 36-37 and 38-39 hold each network's sign, facade and accent colours as stripes of
# 32 px (16 a cell): the cladding, fascia and stripes of its shops, canopies and pumps. The price
# board is a block of one column by four rows; beside it 12 square signs of 256 px (SHOP_SQUARE);
# the last two rows are flat colours and McDonald's word mark (SHOP_WORDMARKS). Photographs of
# real stores (brand_logos.PHOTOS) go into brand_photo.color.png (SHOP_PHOTOS). A lightbox is the
# network's real logo where
# earthng/brand_logos.py fetched one into data/brands/<key>.png (Wikimedia Commons): on a white
# panel when the logo is see-through, else on its own background; otherwise its name in type.
BRAND_ART_VERSION = '7'  # change whenever an existing atlas cell changes
# (label, sign colour, key in generator.lua SOLID.BRANDS[, letters when not white])
BRAND_SIGNS = [
    ('OKKO', (0,90,50), 'okko', (255,205,0)), ('WOG', (0,150,60), 'wog'), ('УКРНАФТА', (0,72,150), 'ukrnafta'),
    ('АВІАС', (0,90,170), 'avias'), ('БРСМ', (213,26,37), 'brsm'), ('SHELL', (251,206,7), 'shell', (221,29,33)),
    ('SOCAR', (0,100,163), 'socar'), ('UPG', (24,24,26), 'upg', (0,170,80)), ('KLO', (255,205,0), 'k_lo', (30,30,30)),
    ('MOTTO', (213,35,39), 'motto'), ('АТБ', (19,69,151), 'atb'), ('СІЛЬПО', (240,120,30), 'silpo'),
    ('ФОРА', (100,190,50), 'fora'), ('NOVUS', (0,160,70), 'novus'), ('AUCHAN', (220,30,52), 'auchan'),
    ('ВЕЛМАРТ', (240,200,0), 'velmart', (220,30,40)), ('КОЛО', (235,92,37), 'kolo'), ('РУКАВИЧКА', (110,35,60), 'rukavychka'),
    ('СІМ23', (231,52,54), 'sim23'), ('СІМІ', (233,85,31), 'simi'), ('ФАЙНО', (0,140,70), 'faino'),
    ('THRASH!', (30,30,30), 'thrash'), ('VARUS', (245,120,30), 'varus'), ('FOZZY', (230,30,40), 'fozzy'),
    ('ЕКО МАРКЕТ', (200,16,46), 'eco'), ('БЛИЗЕНЬКО', (40,113,171), 'blyzenko'),
    ('AMIC', (0,150,70), 'amic'), ('PARALLEL', (0,140,70), 'parallel'), ('VST', (230,75,32), 'vst'), ('БВС', (16,106,164), 'bvs'),
    ("McDonald's", (200,16,46), 'mcdonalds', (255,199,44)), ('НОВА ПОШТА', (218,41,28), 'nova_poshta'),
]
# How a network dresses a building (generator.lua BLD.SHOP.style mirrors clad, square and
# accent): facade, the colour of its fascia (and of every wall when clad); accent, a stripe under
# the fascia; square, its slot of SHOP_SQUARE (a square sign: a square logo, or the name stacked).
# From photographs of the stores on Wikimedia Commons where there are some (ATB, Fora, Velmart,
# OKKO, WOG, Nova Poshta, EKO, AMIC), the networks' own colours otherwise.
BRAND_STYLE = {
    'okko': {'facade': (0, 90, 50), 'accent': (255, 205, 0), 'square': 0},
    'wog': {'facade': (0, 150, 60)},
    'ukrnafta': {'facade': (0, 72, 150), 'accent': (255, 210, 0)},
    'avias': {'facade': (0, 90, 170), 'square': 1},
    'brsm': {'facade': (213, 26, 37)},
    'shell': {'facade': (251, 206, 7), 'accent': (221, 29, 33)},
    'socar': {'facade': (0, 100, 163)},
    'upg': {'facade': (24, 24, 26), 'accent': (0, 170, 80), 'square': 2},
    'k_lo': {'facade': (255, 205, 0), 'accent': (30, 30, 30), 'square': 3},
    'motto': {'facade': (213, 35, 39)},
    'atb': {'facade': (19, 69, 151), 'clad': True, 'square': 4},
    'silpo': {'facade': (240, 120, 30)},
    'fora': {'facade': (100, 190, 50), 'accent': (220, 40, 40), 'clad': True},
    'novus': {'facade': (0, 160, 70)},
    'auchan': {'facade': (220, 30, 52)},
    'velmart': {'facade': (60, 140, 50), 'accent': (240, 200, 0), 'clad': True},
    'kolo': {'facade': (235, 92, 37)},
    'rukavychka': {'facade': (110, 35, 60)},
    'sim23': {'facade': (231, 52, 54), 'square': 5},
    'simi': {'facade': (233, 85, 31)},
    'faino': {'facade': (0, 140, 70), 'square': 6},
    'thrash': {'facade': (30, 30, 30), 'accent': (255, 220, 0)},
    'varus': {'facade': (245, 120, 30)},
    'fozzy': {'facade': (230, 30, 40)},
    'eco': {'facade': (200, 16, 46), 'accent': (0, 50, 140), 'square': 7},
    'blyzenko': {'facade': (40, 113, 171)},
    'amic': {'facade': (0, 150, 70), 'accent': (230, 50, 40)},
    'parallel': {'facade': (0, 140, 70), 'accent': (240, 120, 30)},
    'vst': {'facade': (230, 75, 32)},
    'bvs': {'facade': (16, 106, 164)},
    # as its new restaurants (a photograph from Kyiv's left bank): charcoal, a wooden band, the
    # entrance tower and dining room glazing from that photograph, its word mark on every side
    'mcdonalds': {'facade': (38, 38, 40), 'accent': (150, 100, 60), 'clad': True, 'square': 8},
    'nova_poshta': {'facade': (218, 41, 28)},
}
SHOP_COLS, SHOP_ROWS, SHOP_CELL = 4, 16, (512, 128)
SHOP_GENERIC = [('АЗС', (46,72,104)), ('ПРОДУКТИ', (38,92,62))]          # cells 32, 33
SHOP_PRICE = (0, 10, 1, 4)                                                # column, row, columns, rows
SHOP_SWATCH = (34, 36, 38)                                                # sign, facade, accent: 16 colours a cell
SHOP_SQUARE = (512, 1280, 256, 6)                                         # x, y, size, per row: 12 slots
# logos drawn on the network's colour rather than a white panel
LOGO_ON_COLOUR = {'mcdonalds'}
# cell: (word, panel, letters): McDonald's name on its fascias and under its pylon's arches
SHOP_WORDMARKS = {61: ("McDonald's", (30, 30, 32), (255, 255, 255)), 62: ("McDonald's", (200, 16, 46), (255, 255, 255))}
# brand_photo.color.png (2048 x 1024): key -> (x, y) of its rectified photograph
SHOP_PHOTOS = {'mcdonalds_bay': (0, 0), 'mcdonalds_glass': (512, 0)}
# cell: (colour, lit at night): a white panel, the lit underside of a canopy, a dark body,
# brushed metal, the concrete of a pump island, McDonald's gold (its pole sign's arches)
SHOP_FLATS = {56: ((232, 233, 230), False), 57: ((238, 238, 232), True), 58: ((44, 46, 50), False),
              59: ((168, 172, 176), False), 60: ((150, 148, 142), False), 63: ((255, 199, 44), True)}


def _shop_font(size):
    # the Windows Arial installation and Pillow's DejaVu both include Ukrainian glyphs
    for name in ('arialbd.ttf', 'C:/Windows/Fonts/arialbd.ttf', 'DejaVuSans-Bold.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise RuntimeError('A Unicode font (Arial Bold or DejaVu Sans Bold) is required for brand signs')


def _logo_panel(logo, colour=None):
    """(logo trimmed to what it draws, panel colour): a see-through logo stands on white (or
    `colour`), an opaque one on the colour of its own border."""
    logo = logo.convert('RGBA')
    alpha = logo.getchannel('A')
    clear = alpha.point(lambda a: 255 if a < 128 else 0).histogram()[255] / (logo.width * logo.height)
    box = alpha.point(lambda a: 255 if a > 24 else 0).getbbox()
    logo = logo.crop(box) if box else logo
    # see-through beyond an antialiased rim (an SVG's opaque card keeps a soft edge)
    if clear > .03:
        return logo, colour or (246, 246, 244)
    rgb = logo.convert('RGB')
    edge = [rgb.getpixel((x, y)) for x in (0, rgb.width - 1) for y in (0, rgb.height // 2, rgb.height - 1)]
    panel = tuple(sorted(c[n] for c in edge)[len(edge) // 2] for n in range(3))
    # trimmed to what differs from that background, a little of it kept round the mark
    away = ImageChops.difference(rgb, Image.new('RGB', rgb.size, panel)).convert('L').point(lambda d: 255 if d > 40 else 0)
    box = away.getbbox()
    if box:
        m = round(.04 * max(box[2] - box[0], box[3] - box[1]))
        logo = logo.crop((max(0, box[0] - m), max(0, box[1] - m), min(rgb.width, box[2] + m), min(rgb.height, box[3] + m)))
    return logo, panel


def _type(label, letters, lines=1):
    """The name in bold type on a clear layer, one or (stacked by words) more lines."""
    font = _shop_font(96)
    words = label.split()
    rows = [label] if lines == 1 or len(words) == 1 else [' '.join(words[:len(words) // 2]), ' '.join(words[len(words) // 2:])]
    probe = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    boxes = [probe.textbbox((0, 0), r, font=font) for r in rows]
    w = max(b[2] - b[0] for b in boxes) + 4
    step = max(b[3] - b[1] for b in boxes) + 16
    mark = Image.new('RGBA', (w, step * len(rows)))
    d = ImageDraw.Draw(mark)
    for n, (r, b) in enumerate(zip(rows, boxes)):
        d.text(((w - (b[2] - b[0])) // 2 - b[0], n * step + 2 - b[1]), r, font=font, fill=(*letters, 255))
    return mark


def _face(size, colour, mark, fill):
    """A lightbox face of `size`: a darker rim, a little lighter at the top, `mark` fitted into
    `fill` of it with its proportions kept."""
    w, h = size
    top = tuple(min(255, round(c * 1.08 + 6)) for c in colour)
    face = Image.new('RGB', (w, h), colour)
    d = ImageDraw.Draw(face)
    for row in range(h):
        t = row / (h - 1)
        d.line([(0, row), (w, row)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, colour)))
    d.rectangle((0, 0, w - 1, h - 1), outline=tuple(round(c * .62) for c in colour), width=max(3, w // 100))
    k = min(w * fill[0] / mark.width, h * fill[1] / mark.height)
    mark = mark.resize((max(1, round(mark.width * k)), max(1, round(mark.height * k))), Image.Resampling.LANCZOS)
    face.paste(mark, ((w - mark.width) // 2, (h - mark.height) // 2), mark)
    return face


def _lightbox(colour, label, letters, logo=None, on_colour=False, size=SHOP_CELL):
    """A lightbox (4:1, or a square `size`): a logo fitted into 88 % by 76 % of it, or the name
    into 80 % by 62 % (stacked by words in a square)."""
    if logo is not None:
        logo, colour = _logo_panel(logo, colour if on_colour else None)
        return _face(size, colour, logo, (.88, .76) if size[0] > size[1] else (.84, .84))
    square = size[0] == size[1]
    return _face(size, colour, _type(label, letters, 2 if square else 1), (.82, .7) if square else (.8, .62))


def _atb_roundel(size):
    """ATB's square sign as on its stores: a white panel, a blue ring, 'АТБ' in red."""
    w = size[0]
    face = Image.new('RGB', size, (250, 250, 248))
    d = ImageDraw.Draw(face)
    d.rectangle((0, 0, w - 1, w - 1), outline=(19, 69, 151), width=w // 32)
    m = w * .12
    d.ellipse((m, m, w - m, w - m), outline=(19, 69, 151), width=round(w * .07))
    mark = _type('АТБ', (220, 30, 40))
    k = w * .52 / mark.width
    mark = mark.resize((round(mark.width * k), round(mark.height * k)), Image.Resampling.LANCZOS)
    face.paste(mark, ((w - mark.width) // 2, (w - mark.height) // 2), mark)
    return face


def _price_board(lit):
    """A pylon's board: the grades on the left, amber digits on the right showing no price."""
    w, h = SHOP_CELL[0] * SHOP_PRICE[2], SHOP_CELL[1] * SHOP_PRICE[3]
    board = Image.new('RGB', (w, h), (0, 0, 0) if lit else (30, 32, 35))
    d = ImageDraw.Draw(board)
    if not lit:
        d.rectangle((0, 0, w - 1, h - 1), outline=(170, 174, 178), width=10)
    font = _shop_font(64)
    for n, grade in enumerate(('А-95+', 'А-95', 'ДП', 'ГАЗ')):
        y = 34 + n * 116
        d.text((36, y), grade, font=font, fill=(236, 236, 230))
        d.rounded_rectangle((300, y - 4, 476, y + 74), 8, fill=(0, 0, 0) if lit else (12, 12, 12))
        d.text((312, y), '--.--', font=font, fill=(255, 150, 20) if lit else (120, 70, 12))
    return board


def brand_art(r, logos=None):
    """brand_sign.color.png and its night emissive map, brand_sign.glow.png; the logos from
    `logos` (data/brands)."""
    import paths
    w, h = SHOP_CELL
    atlas = Image.new('RGB', (w * SHOP_COLS, h * SHOP_ROWS), (45, 45, 45))
    glow = Image.new('RGB', atlas.size, (0, 0, 0))
    own = Path(logos) if logos else paths.PROJECT / 'data' / 'brands'

    def paste(image, at, lit):
        atlas.paste(image, at)
        if lit:
            glow.paste(image.point(lambda v: round(v * .85)), at)

    def put(index, image, lit):
        paste(image, (index % SHOP_COLS * w, index // SHOP_COLS * h), lit)

    sx, sy, side, per = SHOP_SQUARE
    for index, (label, colour, key, *letters) in enumerate(BRAND_SIGNS):
        path = own / f'{key}.png'
        logo = Image.open(path) if path.is_file() else None
        letters = letters[0] if letters else (255, 255, 255)
        put(index, _lightbox(colour, label, letters, logo, key in LOGO_ON_COLOUR), True)
        style = BRAND_STYLE[key]
        for cell, rgb in zip(SHOP_SWATCH, (colour, style['facade'], style.get('accent', style['facade']))):
            stripe, cell = w // 16, cell + index // 16
            x, y = cell % SHOP_COLS * w + index % 16 * stripe, cell // SHOP_COLS * h
            atlas.paste(rgb, (x, y, x + stripe, y + h))
        if 'square' in style:
            slot = style['square']
            face = _atb_roundel((side, side)) if key == 'atb' else _lightbox(
                colour, label, letters, logo, key in LOGO_ON_COLOUR, (side, side))
            paste(face, (sx + slot % per * side, sy + slot // per * side), True)
    for n, (label, colour) in enumerate(SHOP_GENERIC):
        put(32 + n, _lightbox(colour, label, (255, 255, 255)), True)
    at = (SHOP_PRICE[0] * w, SHOP_PRICE[1] * h)
    atlas.paste(_price_board(False), at)
    glow.paste(_price_board(True), at)
    for index, (colour, lit) in SHOP_FLATS.items():
        put(index, Image.new('RGB', SHOP_CELL, colour), lit)
    for index, (word, panel, letters) in SHOP_WORDMARKS.items():
        put(index, _lightbox(panel, word, letters), True)
    atlas.save(r / 'brand_sign.color.png')
    glow.save(r / 'brand_sign.glow.png')
    # the photographs, charcoal where one is missing; by night a little of their own light
    photo = Image.new('RGB', (2048, 1024), (38, 38, 40))
    for key, at in SHOP_PHOTOS.items():
        path = own / f'{key}.png'
        if path.is_file():
            photo.paste(Image.open(path).convert('RGB'), at)
    photo.save(r / 'brand_photo.color.png')
    photo.point(lambda v: round(v * .7)).save(r / 'brand_photo.glow.png')
    (r / 'brand_sign.version').write_text(BRAND_ART_VERSION)


def logo_credits(logos=None):
    """Markdown crediting each logo the atlas draws (data/brands/SOURCES.json), or ''."""
    import paths
    own = Path(logos) if logos else paths.PROJECT / 'data' / 'brands'
    sources = own / 'SOURCES.json'
    if not sources.is_file():
        return ''
    rows = [f"- {key}: [{s['file']}]({s['page']}), {s['licence']}" + (f", {s['author']}" if s.get('author') else '')
            for key, s in sorted(json.loads(sources.read_text(encoding='utf8')).items()) if (own / f'{key}.png').is_file()]
    if not rows:
        return ''
    return ('# Network logos and store photographs on shop and fuel station signs\n\n'
            'From Wikimedia Commons (earthng/brand_logos.py), fitted into e2r_stream/fast-art/*/real/brand_sign.* '
            '(logos) and brand_photo.* (photographs squared up into facades): each is shared under CC BY-SA 4.0 '
            'where it holds a CC BY-SA file. The logos are trademarks of their owners; their use here endorses '
            'nothing.\n\n' + '\n'.join(rows) + '\n')


def yard_art(r):
    """The yard paint atlas and the low railing (white paint, its bars as opacity: 1 m a repeat,
    a bar every 12.5 cm, a thicker post at the seam, a rail near the top and the bottom)."""
    atlas = Image.new('RGB', (32 * len(YARD_COLOURS), 32))
    d = ImageDraw.Draw(atlas)
    for k, rgb in enumerate(YARD_COLOURS):
        d.rectangle([32 * k, 0, 32 * k + 31, 31], fill=rgb)
    atlas.save(r / 'yard.color.png')
    Image.new('RGB', (64, 64), (255, 255, 255)).save(r / 'railing.color.png')
    bars = Image.new('RGB', (256, 256), (0, 0, 0))
    d = ImageDraw.Draw(bars)
    for k in range(8):
        x = k * 32 + 16
        d.rectangle([x - 5, 0, x + 5, 255], fill=(255, 255, 255))
    d.rectangle([0, 0, 11, 255], fill=(255, 255, 255))
    d.rectangle([244, 0, 255, 255], fill=(255, 255, 255))
    for v0, v1 in ((8, 24), (232, 248)):
        d.rectangle([0, v0, 255, v1], fill=(255, 255, 255))
    bars.save(r / 'railing_o.data.png')


def to_dds(r):
    """Every map as a BC1 DDS with its mips, the PNG removed: the game reads '<name>.png' from
    '<name>.dds' as it does its own assets, and does not cook (vis-08-centre showed checker
    placeholders for ~30 s while ~70 PNGs cooked one by one)."""
    import fast_dds
    from concurrent.futures import ThreadPoolExecutor

    def one(png):
        fast_dds.save(Image.open(png), png.with_suffix('.dds'), alpha_ref=MIP_REFS.get(png.name))
        png.unlink()
    with ThreadPoolExecutor(6) as pool:
        list(pool.map(one, sorted(r.rglob('*.png'))))


def manifest_text():
    """packs.json: pack settings, written apart from the expensive texture build."""
    base = '/e2r_stream/fast-art/' + VERSION
    fields = {p: pack_fields(p, base) for p in PACKS}
    sun = {'e2rf_synth_sun': {'name': 'e2rf_synth_sun', 'mapTo': 'e2rf_synth_sun', 'class': 'Material', 'version': 1.5,
                              # additive: the black around the disc adds nothing (an alpha test left a square)
                              'translucent': True, 'translucentBlendOp': 'Add', 'translucentZWrite': False,
                              'doubleSided': True,
                              'Stages': [{'baseColorMap': f'{base}/synth/sun.color.png', 'emissiveMap': f'{base}/synth/sun.color.png',
                                          'emissiveFactor': [1, 1, 1]}, {}, {}, {}]}}
    return json.dumps(style.dds({'order': list(PACKS), 'labels': LABELS, 'fields': fields, 'warm': {p: warm_defs(p, fields[p]) for p in PACKS},
                                 'environment': {p: environment(p) for p in PACKS}, 'extra': sun}))


def write_manifest(r):
    """Refresh pack settings independently of the expensive texture build."""
    tmp = r / 'packs.json.tmp'
    tmp.write_text(manifest_text(), encoding='utf8')
    os.replace(tmp, r / 'packs.json')
