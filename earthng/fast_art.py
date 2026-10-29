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

from PIL import Image, ImageDraw

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
    'pipe': ((150, 152, 156), (220, 220, 220)), 'ac_unit': ((222, 222, 216), (236, 236, 236)),
    'dish': ((228, 228, 224), (238, 238, 238)),
    'manhole': ((110, 108, 104), (200, 200, 200)), 'drain': ((80, 78, 74), (190, 190, 190)),
    'patch': ((52, 52, 54), (180, 180, 180)),
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
