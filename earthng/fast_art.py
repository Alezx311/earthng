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

import far_tree_art
import fast_facade
import fast_packs
import fast_pixel
import fast_storefront
import fast_tone
import kit_art
import poi_art
import street_art
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
    'plate': ((28, 54, 120), (200, 200, 200)), 'glyphs': ((240, 240, 236), (240, 240, 236)), 'glyphs_dark': ((10, 10, 12), (10, 10, 12)), 'sign_white': ((232, 232, 228), (232, 232, 228)),
    'sign_yellow': ((248, 196, 16), (248, 196, 16)), 'sign_green': ((0, 108, 58), (0, 108, 58)),
    'sign_blue': ((10, 66, 148), (10, 66, 148)), 'sign_black': ((12, 12, 14), (12, 12, 14)),
    'glyphs_red': ((184, 22, 16), (184, 22, 16)),
    'poi_marks': ((240, 240, 236), (240, 240, 236)), 'poi_marks_dark': ((10, 10, 12), (10, 10, 12)),
    'paint_red': ((184, 30, 24), (220, 220, 220)), 'fascia': ((30, 32, 35), (200, 200, 200)),
    'patch': ((52, 52, 54), (180, 180, 180)),
    'wire': ((40, 40, 42), (190, 190, 190)), 'roof_gold': ((212, 170, 60), (230, 230, 230)),
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
    'track': ((132, 124, 116), (204, 204, 204)), 'ballast': ((150, 144, 136), (214, 214, 214)),
    'rail': ((196, 198, 206), (240, 240, 240)), 'rail_side': ((118, 86, 68), (208, 208, 208)),
}
FLAT.update({k: (tuple(round(c * 255) for c in style.KINDS[k][1][:3]), (222, 222, 222)) for k in style.SHEET_KINDS})
# the lands of the open ground are the ground in a flat pack
FLAT.update({k: FLAT['ground'] for k in style.MACRO})
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
SYNTH.update({k: SYNTH['ground'] for k in style.MACRO})
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


# A lane of asphalt (fast_style LANES, generator.lua ROADS.laneBands): u across the lane, v along
# it. The grain is a strip of the same aerial photo the plain asphalt uses, laid along its own
# long cracks; the wear is drawn over it. Traffic leaves two wheel paths a little darker and
# smoother (rubber, flushed bitumen), a faint stained middle between them and a paler edge by the
# seam, all of them stronger in places and streaked along the road. The sheet keeps the base's
# mean, so a lane meets a junction's plain asphalt without a step in colour.
LANE_ART_VERSION = '3'
LANE_PX = (256, 2048)
LANE_BAND = .30             # the strip's near edge in the photo, as a share of its height
LANE_FADE = 160             # rows blended into the start so the sheet repeats along the road
# metres from the lane's middle: wheel paths, their spread, the middle's and the seam's spread
LANE_WEAR = {'path': .85, 'spread': .3, 'middle': .2, 'seam': .11}
LANE_GRAIN = 24             # texels: what of the photo is wider than this is left to the wear (a blotch
                            # of the photo came back every repeat, and mirrored in the lane beside it)


def lane_maps(seed=2611):
    """(colour, normal, roughness) of the lane sheet as float arrays in 0..1, rows along the road."""
    import numpy as np
    rng = np.random.default_rng(seed)
    w, h = LANE_PX
    src = photo.TEXTURES / 'road_macro'
    # the photo's pixels under LANE_W x (LANE_M + the blended rows), the lane's length along x
    px = BASE_PX / style.ROAD_M
    tall = h + LANE_FADE
    box_w, box_h = int(round(style.LANE_M * tall / h * px)), int(round(style.LANE_W * px))
    top = int(BASE_PX * LANE_BAND)
    box = (0, top, min(BASE_PX, box_w), top + box_h)

    def strip(name, mode):
        im = Image.open(src / f'{name}.jpg').convert(mode).resize((BASE_PX, BASE_PX), Image.LANCZOS)
        # turned so that the road runs down the rows
        return np.asarray(im.crop(box).transpose(Image.TRANSPOSE).resize((w, tall), Image.LANCZOS), np.float32) / 255

    def wrap(a):
        # the rows past the end fade into the start: row h - 1 runs on into row 0
        t = (np.arange(LANE_FADE, dtype=np.float32) / LANE_FADE).reshape((-1,) + (1,) * (a.ndim - 1))
        out = a[:h].copy()
        out[:LANE_FADE] = a[h:] * (1 - t) + a[:LANE_FADE] * t
        return out

    lin = wrap(_srgb_to_linear(strip('albedo', 'RGB')))
    lum = lin @ np.array([.2126, .7152, .0722], np.float32)
    lin = lum[..., None] + (lin - lum[..., None]) * BASE_SATURATION
    # the grain alone, its odd dark stone clipped: one that stood out came by once a lane a repeat
    fine = lum - _blur_wrap(lum, LANE_GRAIN)
    fine = np.clip(fine, -1.6 * fine.std(), 1.6 * fine.std())
    lin = (lin - lum[..., None]) + (lum.mean() + fine)[..., None]
    m = ((np.arange(w, dtype=np.float32) + .5) / w - .5) * style.LANE_W          # metres from the middle
    W = LANE_WEAR
    paths = sum(np.exp(-.5 * ((m - s * W['path']) / W['spread']) ** 2) for s in (-1, 1))[None, :]
    middle = np.exp(-.5 * (m / W['middle']) ** 2)[None, :]
    seam = np.exp(-.5 * ((style.LANE_W / 2 - np.abs(m)) / W['seam']) ** 2)[None, :]
    # how worn each stretch is, each path on its own; streaks drawn out along the road
    left, right = (.55 + .45 * _periodic_noise(rng, 1, h, 1, n) for n in (9, 11))
    side = np.where(m[None, :] < 0, left, right)
    stained = _periodic_noise(rng, 1, h, 1, 14) ** 2
    streaks = (.6 * _periodic_noise(rng, w, h, 48, 10) + .4 * _periodic_noise(rng, w, h, 96, 28)) - .5
    # (drawn out along the road as well: every lane of a carriageway shows the same stretch of
    # the sheet, and a round blotch came by once a lane across the road)
    blotch = _periodic_noise(rng, w, h, 3, 6) - .5
    # (at .17 for the paths the lanes could not be told from the plain asphalt behind a car in
    # the game, under the detail maps' grain: hyperreal run-08)
    wear = 1 - .30 * paths * side - .12 * middle * stained + .09 * seam + .14 * streaks * (.4 + .6 * paths) + .04 * blotch
    # the joint between two lanes: a dark line a centimetre or two wide where the mats meet, broken
    joint = np.clip(_periodic_noise(rng, 1, h, 1, 40) * 2 - .7, 0, 1)
    wear[:, :2] *= 1 - .3 * joint
    lin = lin * wear[..., None]
    colour = _linear_to_srgb(lin * (BASE_MEAN / lin.mean()))
    n = wrap(strip('normal', 'RGB')) * 2 - 1
    # the photo was turned: its x is the sheet's y; green flipped for the game, as road_sheets
    nx, ny = n[..., 1], n[..., 0]
    nz = np.sqrt(np.clip(1 - nx * nx - ny * ny, 0, 1))
    normal = np.stack([nx, -ny, nz], -1) * .5 + .5
    rough = wrap(strip('roughness', 'L'))
    rough = np.clip(rough - rough.mean() + BASE_ROUGH - .26 * paths * side - .08 * middle * stained + .05 * seam, .05, 1)
    return np.clip(colour, 0, 1), np.clip(normal, 0, 1), rough


def lane_sheets(r):
    """The lane sheet's maps as PNGs in r (the real pack's folder)."""
    import numpy as np
    for a, name in zip(lane_maps(), ('road_lane.color.png', 'road_lane.normal.png', 'road_lane.data.png')):
        Image.fromarray((a * 255 + .5).astype(np.uint8)).convert('RGB').save(r / name)
    (r / 'lane.version').write_text(LANE_ART_VERSION)


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
    elif kind == 'track':
        f['opacityMap'] = style.TEXTURES['track']['opacityMap']    # the ragged shoulders
    elif kind in style.EDGES or kind in style.FADES:
        f['opacityFactor'] = 0
    elif kind in style.CUTS:
        f['opacityMap'] = ''


def pack_fields(pack, base, toned=True):
    """Material name -> stage-0 fields for one pack (all map fields present, '' clears).
    The real pack's colours are toned (fast_tone); the seasonal packs start from the untoned ones.
    A field's crops (fast_style.CROPS) are the real pack's own: every other pack draws them as
    its farmland."""
    out = _pack_fields(pack, base, toned)
    if pack != 'real':
        for kind, like in style.CROP_LIKE.items():
            if 'e2rf_' + like in out:
                out['e2rf_' + kind] = dict(out['e2rf_' + like])
        # the field tracks' ruts are the real pack's own: every other pack keeps its old track,
        # the bed it draws under them (the seasonal packs start from the real fields)
        for kind in style.RUTS:
            out['e2rf_' + kind] = {**out['e2rf_' + kind], 'opacityFactor': 0}
        # and so are the asphalt's lanes: no other pack draws them (generator.lua tune.lanes), and
        # each keeps the plain asphalt it has
        for kind, plain in style.LANES.items():
            out['e2rf_' + kind] = dict(out['e2rf_' + plain])
    return out


def _pack_fields(pack, base, toned=True):
    if pack == 'pixel':
        return fast_pixel.fields(base)
    if pack in fast_packs.PACKS:
        return fast_packs.fields(pack, base, pack_fields('real', base, toned=False))
    out = {}
    for kind, (tex, fallback, _, _, mode) in style.KINDS.items():
        f = {k: '' for k in MAP_FIELDS}
        f['emissiveFactor'] = '0 0 0'
        if kind.startswith('wall_'):
            # a flat pack draws a new wall with the art of the older one it resembles
            w = kind[5:] if pack == 'real' else fast_facade.like(kind[5:])
            f['baseColorMap'] = f'{base}/{pack}/{w}.color.png'
            if pack == 'real':
                f.update(style.real_stage(kind))
            if pack == 'synth':
                f['emissiveMap'] = f'{base}/synth/{w}.glow.png'; f['emissiveFactor'] = '1 1 1'
            f['baseColorFactor'] = '1 1 1 1'
        elif pack == 'real':
            if kind in style.TURF or kind in style.PHOTO_GROUND or kind in style.MACRO or kind in style.CROPS:
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
        if kind in style.LENS:
            f['emissiveFactor'] = ' '.join(str(c * 4) for c in style.LENS[kind])
        if kind in ('brand_sign', 'brand_photo', 'storefront'):
            f['baseColorMap'] = f'{base}/real/{kind}.color.png'
            f['baseColorFactor'] = '1 1 1 1'
        if pack != 'real':
            stylised_decal(kind, f)
        if pack == 'real' and toned:
            t = fast_tone.factor(kind, f)
            if t:
                f['baseColorFactor'] = ' '.join(f'{c:.3f}' for c in t[:3]) + f' {float(t[3]):g}'
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
        if pack == 'real':
            # the level's TimeOfDay places the sun: a fixed azimuth and elevation here left the
            # sun in the SE at 48 degrees after a switch back, not where the landing had it
            for k in ('azimuth', 'elevation'):
                real['objects']['sunsky'].pop(k, None)
        return fast_packs.environment(pack, real) if pack in fast_packs.PACKS else real
    return {'authoredSun': True, 'objects': {
        'sunsky': {'azimuth': '250', 'elevation': '3', 'brightness': '0.45', 'skyBrightness': '6',
                   'colorize': '0.75 0.1 0.95 1', 'colorizeAmount': '4', 'fogScale': '0.55 0.08 0.75 1',
                   'sunScale': '1 0.3 0.8 1', 'ambientScale': '0.45 0.25 0.7 1'},
        'theLevelInfo': {'fogColor': '0.25 0.04 0.38 1', 'fogDensity': '0.00004', 'canvasClearColor': '40 10 60 255'}},
        'sun': {'azimuth': 250, 'distance': 3200, 'size': 1500, 'height': 420, 'material': 'e2rf_synth_sun'}}


def warm_defs(pack, fields, seen):
    """One material per pack and texture, loaded at the landing on a hidden triangle: a texture
    the engine first meets through a runtime map swap streams into a slot sized for the old one
    and breaks (\"dds mip chain (11) does not match texture (9)\", fast-game-packs-02). `seen`
    holds the maps warmed already: a material with nothing new adds only an object to the landing."""
    out = {}
    for mat, f in fields.items():
        stage = {k: v for k, v in f.items() if k in MAP_FIELDS and v}
        if not stage or seen.issuperset(stage.values()):
            continue
        seen.update(stage.values())
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
    if kind in style.BIOME_GROUND or kind in ('glacier', 'farmland'):
        nm = nm.resize((1024, 1024), Image.LANCZOS)
        if kind in SMOOTH_GROUND:
            im = im.resize((1024, 1024), Image.LANCZOS)
    return im, nm


def land_art(real):
    """The open land's colour sheets and the mask they dissolve by (fast_photo.macro_sheet)."""
    for name in photo.MACRO:
        photo.macro_sheet(name).save(real / f'macro_{name}.color.png')
    photo.relief_normal().save(real / 'macro_relief.normal.png')
    # the fields' crops (fast_style.CROPS)
    for crop in photo.FIELD_CROPS:
        for along_y in (False, True):
            colour, normal = photo.field_images(crop, along_y)
            name = f'field_{crop}{"_y" if along_y else ""}'
            colour.save(real / f'{name}.color.png')
            normal.save(real / f'{name}.normal.png')
    mask = photo.blend_mask()
    mask.save(real / 'land_blend_o.data.png')
    # the land a piece comes into is cut by the inverse (fast_style.CUTS)
    ImageChops.invert(mask).save(real / 'land_blend_inv_o.data.png')
    (real / 'land.version').write_text(LAND_ART_VERSION + own_tag())


LAND_ART_VERSION = '7'  # change whenever a land sheet, the relief, a field's crop or the mask (or its mips) changes
WOOD_ART_VERSION = '9'  # change whenever the wood's floor sheet does (fast_photo.GROUND['forest'], GROUND_OWN)
GROUND_ART_VERSION = '1'  # change whenever a photo ground sheet's recipe does (fast_photo.GROUND)


def own_tag():
    """What a stamp of art drawn from the texture library adds where EarthNG's own sets stand in
    (own_art.py): the sheets are drawn again when the sets come, go or change."""
    import own_art
    names = sorted(own_art.stand_ins().values()) + (sorted(fast_facade.OWN_SHEETS) if own_art.ready() else [])
    names += ['doors'] if own_art.ready() and own_art.cells_ready() else []
    return f'+own{own_art.VERSION}:{len(names)}' if names else ''


def ground_art(real):
    """The photo ground sheets again (fast_photo.GROUND), in the sets of today."""
    for kind in style.PHOTO_GROUND:
        if kind != 'forest':
            im, nm = ground_sheet(kind)
            im.save(real / f'ground_{kind}.color.png'); nm.save(real / f'ground_{kind}.normal.png')
    (real / 'ground.version').write_text(GROUND_ART_VERSION + own_tag())


def wood_art(real):
    """The wood's floor: its photo sheet again, in the recipe of today."""
    im, nm = ground_sheet('forest')
    im.save(real / 'ground_forest.color.png')
    nm.save(real / 'ground_forest.normal.png')
    (real / 'wood.version').write_text(WOOD_ART_VERSION + own_tag())


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


def repair_pixel_cache(shared):
    """Add pixel maps introduced since a shared cache was first built."""
    base = '/e2r_stream/fast-art/' + VERSION
    prefix = base + '/pixel/'
    fields = pack_fields('pixel', base)
    missing = set()
    for material in fields.values():
        for value in material.values():
            if isinstance(value, str) and value.startswith(prefix):
                name = Path(value[len(prefix):]).with_suffix('.dds').name
                if not (shared / 'pixel' / name).is_file():
                    missing.add(name)
    if missing:
        fast_pixel.build(shared, only=missing)
        to_dds(shared / 'pixel')


def missing_art(shared):
    """Check every local map in the generated manifest, including warmed materials."""
    prefix = '/e2r_stream/fast-art/' + VERSION + '/'
    manifest = json.loads((shared / 'packs.json').read_text(encoding='utf8'))
    missing = set()

    def visit(value):
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value.startswith(prefix):
            path = Path(value[len(prefix):]).with_suffix('.dds')
            if not (shared / path).is_file():
                missing.add(path.as_posix())

    visit(manifest)
    return missing


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
        # and the open land's sheets (generator.lua VEG.land)
        stamp = shared / 'real' / 'land.version'
        if not stamp.exists() or stamp.read_text() != LAND_ART_VERSION + own_tag():
            land_art(shared / 'real')
            to_dds(shared / 'real')
        # and the wood's floor
        stamp = shared / 'real' / 'wood.version'
        if not stamp.exists() or stamp.read_text() != WOOD_ART_VERSION + own_tag():
            wood_art(shared / 'real')
            to_dds(shared / 'real')
        # and the other photo ground sheets, where the sets they are drawn from changed
        stamp = shared / 'real' / 'ground.version'
        if (stamp.read_text() if stamp.exists() else GROUND_ART_VERSION) != GROUND_ART_VERSION + own_tag():
            ground_art(shared / 'real')
            to_dds(shared / 'real')
        # and the yard's paint and railing (generator.lua YARD)
        if not (shared / 'real' / 'railing_o.data.dds').exists():
            yard_art(shared / 'real')
            to_dds(shared / 'real')
        # and the far trees' cards (generator.lua VEG.CARD)
        stamp = shared / 'real' / 'far_trees.version'
        if not stamp.exists() or stamp.read_text() != far_tree_art.VERSION:
            far_tree_art.write(shared / 'real')
            to_dds(shared / 'real')
        # and the track bed (generator.lua RAIL)
        if not (shared / 'real' / 'track_o.data.dds').exists():
            rail_art(shared / 'real')
            to_dds(shared / 'real')
        # and the field tracks' ruts (generator.lua ROADS.ruts)
        stamp = shared / 'real' / 'ruts.version'
        if not stamp.exists() or stamp.read_text() != RUTS_ART_VERSION:
            ruts_art(shared / 'real')
            to_dds(shared / 'real')
        # and the asphalt's lanes (generator.lua ROADS.laneBands)
        stamp = shared / 'real' / 'lane.version'
        if not stamp.exists() or stamp.read_text() != LANE_ART_VERSION:
            lane_sheets(shared / 'real')
            to_dds(shared / 'real')
        stamp = shared / 'real' / 'brand_sign.version'
        if not (shared / 'real' / 'brand_photo.glow.dds').exists() or not stamp.exists() or stamp.read_text() != BRAND_ART_VERSION:
            brand_art(shared / 'real')
            to_dds(shared / 'real')
        # and the signs' letters
        stamp = shared / 'real' / 'glyphs.version'
        if (not stamp.exists() or stamp.read_text() != GLYPH_ART_VERSION) and glyph_art(shared / 'real'):
            to_dds(shared / 'real')
        # and the points of interest's pictograms (poi_art, generator.lua BLD.poiInfo)
        stamp = shared / 'real' / 'poi.version'
        if not stamp.exists() or stamp.read_text() != poi_art.VERSION:
            poi_art.build(shared / 'real')
            to_dds(shared / 'real')
        # and the drawn facades and plain sheets
        stamp = shared / 'real' / 'facade.version'
        if not stamp.exists() or stamp.read_text() != FACADE_ART_VERSION + own_tag():
            facade_art(shared)
            to_dds(shared)
        # and the houses' library (house_art, houses.lua): its sheets and its atlases of windows
        stamp = shared / 'real' / 'house.version'
        if fast_facade.HOUSE_SHEETS and (not stamp.exists() or stamp.read_text() != house_tag()):
            house_stage(shared / 'real')
            to_dds(shared / 'real')
        # and the building kit's walls, cells and trim (kit_art, generator.lua BLD.kit)
        stamp = shared / 'real' / 'kit.version'
        if kit_art.ready() and (not stamp.exists() or stamp.read_text() != kit_art.VERSION):
            kit_art.build(shared / 'real')
            to_dds(shared / 'real')
        # and a town's walking surfaces (street_art, generator.lua ROADS.YARD.paving)
        stamp = shared / 'real' / 'street.version'
        if street_art.ready() and (not stamp.exists() or stamp.read_text() != street_art.VERSION):
            street_art.build(shared / 'real')
            to_dds(shared / 'real')
        repair_pixel_cache(shared)
        write_manifest(shared)  # environment/fields are code, not a texture cache
    missing = missing_art(shared)
    if missing:
        raise FileNotFoundError('Shared EarthNG art is incomplete: ' + ', '.join(sorted(missing)))
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
            if fast_facade.like(name) != name:
                continue                        # facade_art
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
    (r / 'real' / 'wood.version').write_text(WOOD_ART_VERSION + own_tag())
    (r / 'real' / 'ground.version').write_text(GROUND_ART_VERSION + own_tag())
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
    land_art(r / 'real')
    yard_art(r / 'real')
    rail_art(r / 'real')
    ruts_art(r / 'real')
    brand_art(r / 'real')
    glyph_art(r / 'real')
    poi_art.build(r / 'real')
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
    lane_sheets(r / 'real')
    fast_packs.build(r, base)
    fast_pixel.build(r)
    facade_art(r)
    if fast_facade.HOUSE_SHEETS:
        house_stage(r / 'real')
    if kit_art.ready():
        kit_art.build(r / 'real')
    if street_art.ready():
        street_art.build(r / 'real')
    to_dds(r)
    write_manifest(r)
    return r


FACADE_ART_VERSION = '4'  # change whenever a drawn facade or sheet changes


def facade_art(r):
    """The drawn facades, their end walls and their night glow, and the plain sheets (fast_facade)."""
    real = r / 'real'
    if not LAYERS:
        LAYERS.append(photo.panel_atlas())
    for name, (family, _, _) in photo.PHOTO_WALLS.items():
        if fast_facade.like(name) == name and family != 'end_panel':
            continue
        im, nm = photo_real(name)
        im.save(real / f'{name}.color.png')
        if nm is not None:
            nm.resize((fast_facade.NORMAL_PX, fast_facade.NORMAL_PX), Image.LANCZOS).save(real / f'{name}.normal.png')
    for name in fast_facade.SHEETS:
        im, nm = fast_facade.sheet(name)
        im.save(real / f'{name}.color.png')
        nm.save(real / f'{name}.normal.png')
    # the outbuildings' doors (own_art.cells: generator.lua BLD.SMALL.cells)
    import own_art
    if own_art.ready() and own_art.cells_ready():
        own_art.cells().save(real / 'ob_cells.color.png')
    boards, gaps = fast_facade.fence_boards()
    boards.save(real / 'fence_boards.color.png')
    gaps.save(real / 'fence_boards_o.data.png')
    fast_packs.layout_glows(r)
    (real / 'facade.version').write_text(FACADE_ART_VERSION + own_tag())


def house_tag():
    import house_art
    return f'{house_art.VERSION}:{len(fast_facade.HOUSE_SHEETS)}'


def house_stage(real):
    """The houses' library (house_art.py): its plain sheets and the atlases of windows and doors."""
    import house_art
    for name in fast_facade.HOUSE_SHEETS:
        im, nm = fast_facade.sheet(name)
        im.save(real / f'{name}.color.png')
        nm.save(real / f'{name}.normal.png')
    house_art.build(real)
    (real / 'house.version').write_text(house_tag())


# alphaRef per opacity map whose mips keep its coverage (fast_dds.keep_coverage)
MIP_REFS = {'chainlink_o.data.png': style.CHAINLINK_MIP_REF, 'line_o.data.png': style.EXTRA['mark']['alphaRef'],
            'railing_o.data.png': style.RAILING_MIP_REF, 'far_trees_o.data.png': style.FAR_TREE_MIP_REF, 'fence_boards_o.data.png': style.FENCE_BOARDS_MIP_REF,
            'track_o.data.png': style.TRACK_MIP_REF, 'land_blend_o.data.png': 'uniform', 'land_blend_inv_o.data.png': 'uniform',
            'ruts_o.data.png': style.RUTS_REF, 'ruts_two_o.data.png': style.RUTS_REF,
            # the signs' letters: a box filter thins their strokes away from the 16 px level on
            'glyphs_o.data.png': style.EXTRA['glyphs']['alphaRef'],
            # and the points of interest's pictograms, for the same reason
            'poi_marks_o.data.png': style.POI_MARKS_REF}
# The yard atlas (generator.lua YARD.cell keeps the same order): playground paint, wood, metal,
# sand, container screens and the yellow of the hemisphere bollards.
YARD_COLOURS = [(196, 52, 40), (236, 188, 40), (46, 108, 186), (62, 148, 70), (228, 118, 40), (146, 104, 62),
                (126, 128, 130), (44, 44, 46), (204, 180, 132), (52, 98, 150), (226, 226, 220), (128, 62, 50),
                (162, 160, 152), (214, 184, 58), (122, 178, 92), (92, 62, 40)]


# The shop and fuel station atlas (generator.lua BLD.SHOP): 4 x 32 cells of 512 x 128 px, the
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
BRAND_ART_VERSION = '13'  # change whenever an existing atlas cell changes; 13: neutral signs, fronts
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
# From photographs of the stores on Wikimedia Commons where there are some (ATB, Fora, OKKO, WOG,
# Nova Poshta, EKO, AMIC), the networks' own colours otherwise; Velmart's red and yellow as the
# user knows its stores.
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
    'velmart': {'facade': (214, 32, 38), 'accent': (250, 205, 0), 'clad': True},
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
# The atlas's second half (2048 x 2048 below the first, generator.lua BLD.SHOP.more): cell 64 on.
# The plain signs of the service classes, then the networks. A network with a logo takes its
# colour from the logo (brand_logos, measured), one without keeps its class's colour and its name
# in type: a colour nobody has checked is not invented.
SERVICE_CLASS = {'car': (42, 44, 50), 'wash': (20, 110, 180), 'charge': (20, 130, 80), 'pharmacy': (0, 128, 92),
                 'bank': (30, 50, 100), 'food': (122, 66, 36)}
SERVICE_SIGNS = [
    ('СТО', SERVICE_CLASS['car'], 'plain_car_repair'), ('ШИНОМОНТАЖ', SERVICE_CLASS['car'], 'plain_tyres'),
    ('АВТОМИЙКА', SERVICE_CLASS['wash'], 'plain_car_wash'), ('ЗАРЯДКА', SERVICE_CLASS['charge'], 'plain_charging'),
    ('АПТЕКА', SERVICE_CLASS['pharmacy'], 'plain_pharmacy'), ('БАНК', SERVICE_CLASS['bank'], 'plain_bank'),
    ('КАФЕ', SERVICE_CLASS['food'], 'plain_food'),
    ('ОЩАДБАНК', (8, 72, 72), 'oschadbank'), ('ПРИВАТБАНК', (88, 184, 72), 'privatbank'),
    ('РАЙФФАЙЗЕН', (250, 240, 10), 'raiffeisen', (30, 30, 30)), ('УКРСИББАНК', (0, 140, 110), 'ukrsibbank'),
    ('SENSE BANK', (40, 40, 248), 'sense'), ('ПУМБ', (232, 8, 40), 'pumb'), ('УКРГАЗБАНК', (40, 88, 168), 'ukrgasbank'),
    ('А-БАНК', (8, 200, 88), 'a_bank'), ('CRÉDIT AGRICOLE', (0, 110, 80), 'credit_agricole'), ('OTP BANK', (8, 104, 72), 'otp'),
    ('ПОДОРОЖНИК', (8, 104, 72), 'podorozhnyk'), ('АНЦ', (8, 152, 216), 'anc'), ('АПТЕКА 911', (168, 40, 40), 'apteka_911'),
    ('АПТЕКА ОПТОВИХ ЦІН', SERVICE_CLASS['pharmacy'], 'apteka_opt'), ("БАЖАЄМО ЗДОРОВ'Я", SERVICE_CLASS['pharmacy'], 'bazhaemo'),
    ('ДОБРОГО ДНЯ', SERVICE_CLASS['pharmacy'], 'dobroho_dnya'), ('ЗДОРОВА РОДИНА', SERVICE_CLASS['pharmacy'], 'zdorova_rodyna'),
    ('LVIV CROISSANTS', (30, 30, 30), 'lviv_croissants'), ('KFC', (228, 8, 40), 'kfc'), ("DOMINO'S", (8, 152, 232), 'dominos'),
    ('AROMA KAVA', SERVICE_CLASS['food'], 'aroma_kava'), ('КУЛИНИЧІ', SERVICE_CLASS['food'], 'kulynychi'),
    ('ПУЗАТА ХАТА', SERVICE_CLASS['food'], 'puzata_hata'), ('PIZZA DAY', SERVICE_CLASS['food'], 'pizza_day'),
    ('IONITY', (72, 8, 120), 'ionity'), ('TOKA', SERVICE_CLASS['charge'], 'toka'), ('EVA CHARGERS', SERVICE_CLASS['charge'], 'autoenterprise'),
    ('VIANOR', SERVICE_CLASS['car'], 'vianor'),
]
SERVICE_CELL, SERVICE_SWATCH = 64, (112, 115, 118)                         # generator.lua BLD.SHOP.more, more_swatch
SHOP_COLS, SHOP_ROWS, SHOP_CELL = 4, 32, (512, 128)
SHOP_GENERIC = [('АЗС', (46,72,104)), ('ПРОДУКТИ', (38,92,62))]          # cells 32, 33
SHOP_PRICE = (0, 10, 1, 4)                                                # column, row, columns, rows
# The same plain signs outside Ukraine (generator.lua BLD.SHOP.neutral): a pictogram for each word,
# the colours kept: fuel, groceries, then the service classes of SERVICE_SIGNS[:7] in order
NEUTRAL_SIGNS = {100: ('fuel', SHOP_GENERIC[0][1]), 101: ('cart', SHOP_GENERIC[1][1]),
                 102: ('wrench', SERVICE_CLASS['car']), 104: ('tyre', SERVICE_CLASS['car']),
                 105: ('wash', SERVICE_CLASS['wash']), 106: ('charge', SERVICE_CLASS['charge']),
                 108: ('cross', SERVICE_CLASS['pharmacy']), 109: ('bank', SERVICE_CLASS['bank']),
                 110: ('cup', SERVICE_CLASS['food'])}
NEUTRAL_PRICE = (3, 24, 1, 4)                                             # the price board's grades in Latin
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


def _price_board(lit, grades=('А-95+', 'А-95', 'ДП', 'ГАЗ')):
    """A pylon's board: the grades on the left, amber digits on the right showing no price."""
    w, h = SHOP_CELL[0] * SHOP_PRICE[2], SHOP_CELL[1] * SHOP_PRICE[3]
    board = Image.new('RGB', (w, h), (0, 0, 0) if lit else (30, 32, 35))
    d = ImageDraw.Draw(board)
    if not lit:
        d.rectangle((0, 0, w - 1, h - 1), outline=(170, 174, 178), width=10)
    font = _shop_font(64)
    for n, grade in enumerate(grades):
        y = 34 + n * 116
        size = 64
        while font.getlength(grade) > 250 and size > 30:
            size -= 4
            font = _shop_font(size)
        d.text((36, y + (64 - size) // 2), grade, font=font, fill=(236, 236, 230))
        font = _shop_font(64)
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
    for index, (label, colour, key, *letters) in enumerate(SERVICE_SIGNS):
        path = own / f'{key}.png'
        logo = Image.open(path) if path.is_file() else None
        put(SERVICE_CELL + index, _lightbox(colour, label, letters[0] if letters else (255, 255, 255), logo), True)
        for base in SERVICE_SWATCH:
            stripe, cell = w // 16, base + index // 16
            x, y = cell % SHOP_COLS * w + index % 16 * stripe, cell // SHOP_COLS * h
            atlas.paste(colour, (x, y, x + stripe, y + h))
    at = (SHOP_PRICE[0] * w, SHOP_PRICE[1] * h)
    atlas.paste(_price_board(False), at)
    glow.paste(_price_board(True), at)
    import fast_picto
    for index, (name, colour) in NEUTRAL_SIGNS.items():
        put(index, _face(SHOP_CELL, colour, fast_picto.mark(name), (.8, .72)), True)
    at = (NEUTRAL_PRICE[0] * w, NEUTRAL_PRICE[1] * h)
    latin = ('95', '98', 'DIESEL', 'LPG')
    atlas.paste(_price_board(False, latin), at)
    glow.paste(_price_board(True, latin), at)
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
    fast_storefront.art(r, _shop_font)
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


GLYPH_FONT = 'ui/common/Noto_Sans_Mono/static/NotoSansMono-Bold.ttf'   # in the game: OFL
GLYPH_CELL = 64
GLYPH_ART_VERSION = '2'  # 2: mips keep the strokes (MIP_REFS), letters read from farther off


def glyph_art(r):
    """The address plates' letters (fast_style.GLYPHS): white over a 1024 px atlas, their shapes
    as opacity; flipped like the facades so v grows upward. A missing font leaves no file."""
    from PIL import ImageFont
    path = Path(game_dir()) / GLYPH_FONT if game_dir() else None
    if not path or not path.exists():
        return False
    n = style.GLYPHS_PER_ROW
    size = n * GLYPH_CELL
    font = ImageFont.truetype(str(path), round(GLYPH_CELL * .78))
    alpha = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(alpha)
    top = font.getbbox('Hg')[1]
    for k, ch in enumerate(style.GLYPHS):
        x, y = (k % n) * GLYPH_CELL, (k // n) * GLYPH_CELL
        width = font.getlength(ch)
        d.text((x + (GLYPH_CELL - width) / 2, y + GLYPH_CELL * .06 - top), ch, fill=255, font=font)
    Image.new('RGB', (size, size), (255, 255, 255)).save(r / 'glyphs.color.png')
    alpha.convert('RGB').transpose(Image.FLIP_TOP_BOTTOM).save(r / 'glyphs_o.data.png')
    (r / 'glyphs.version').write_text(GLYPH_ART_VERSION)
    return True


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


# A track bed (generator.lua RAIL, fast_style 'track'): u across the bed, v along it, four
# concrete sleepers to a repeat. The sleepers fill the middle TRACK_SLEEPER of the width; the
# rails are geometry, only their pads and rust are drawn.
TRACK_SLEEPERS, TRACK_SLEEPER, TRACK_RAILS = 4, .68, (.30, .70)


def rail_art(r):
    """track.color/normal and its opacity (the ballast shoulders ragged): grey stones, the
    concrete sleepers with dark pads under the rails, rust down the ballast beside them."""
    import random
    import numpy as np
    rng = random.Random(1520)
    size = PX
    colour = Image.new('RGB', (size, size), (104, 99, 92))
    height = Image.new('L', (size, size), 90)
    dc, dh = ImageDraw.Draw(colour), ImageDraw.Draw(height)
    for _ in range(9000):
        x, y, s = rng.uniform(0, size), rng.uniform(0, size), rng.uniform(4, 11)
        g = rng.randint(78, 158)
        box = (x - s, y - s * rng.uniform(.6, 1), x + s, y + s * rng.uniform(.6, 1))
        dc.ellipse(box, fill=(g + rng.randint(-6, 8), g - rng.randint(0, 6), g - rng.randint(2, 12)))
        dh.ellipse(box, fill=rng.randint(110, 200))
    a = np.asarray(colour).astype(float)
    u = (np.arange(size) + .5) / size
    for rail in TRACK_RAILS:
        rust = np.exp(-((u - rail) / .045) ** 2)[None, :, None]
        a = a * (1 - .35 * rust) + np.array([96, 62, 40]) * .35 * rust
    h = np.asarray(height).astype(float)
    u0, u1 = (1 - TRACK_SLEEPER) / 2 * size, (1 + TRACK_SLEEPER) / 2 * size
    cell = size / TRACK_SLEEPERS
    for k in range(TRACK_SLEEPERS):
        v0, v1 = int(k * cell + cell * .22), int(k * cell + cell * .78)
        x0, x1 = int(u0 + rng.uniform(-6, 6)), int(u1 + rng.uniform(-6, 6))
        grey = rng.randint(148, 170)
        tone = np.array([grey, grey - 2, grey - 8], dtype=float)
        block = tone + np.asarray([[rng.uniform(-7, 7)] for _ in range(v1 - v0)])[:, :, None]
        a[v0:v1, x0:x1] = block
        a[v0:v1, x0:x0 + 5] *= .8; a[v0:v1, x1 - 5:x1] *= .8
        a[v0:v0 + 4, x0:x1] *= .85; a[v1 - 4:v1, x0:x1] *= .7
        for rail in TRACK_RAILS:
            c = int(rail * size)
            a[v0 + 3:v1 - 3, c - 20:c + 20] = (58, 52, 48)
        h[v0:v1, x0:x1] = 230
    colour = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    gy, gx = np.gradient(h / 255 * 6)
    n = np.dstack([-gx, gy, np.ones_like(h)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    normal = Image.fromarray(((n * .5 + .5) * 255).astype(np.uint8))
    # the shoulders: the bed ends 3-8 % in from each side, ragged stone by stone
    alpha = np.full((size, size), 255, dtype=np.uint8)
    edge = np.cumsum([rng.uniform(-1, 1) for _ in range(size)])
    edge = .055 + .025 * np.sin(edge / 9) + np.array([rng.uniform(-.01, .01) for _ in range(size)])
    alpha[(u[None, :] < edge[:, None]) | (1 - u[None, :] < edge[::-1, None])] = 0
    colour.save(r / 'track.color.png')
    normal.save(r / 'track.normal.png')
    Image.fromarray(alpha).convert('RGB').save(r / 'track_o.data.png')


# Field tracks (generator.lua ROADS.ruts, fast_style RUTS): the opacity over the game's dirt-road
# decal, u across and v along, 80 m of track a repeat. The middle RUTS_CORE of the width (the
# bed) is always solid; outside it the dirt ends raggedly, from the bed's edge to the decal's,
# with grass biting in and dirt spilling out. The two-track one also opens a ragged strip of
# the bed's grass down the middle.
RUTS_ART_VERSION = '1'
RUTS_PX = (256, 2048)


def _periodic_noise(rng, w, h, cells_u, cells_v):
    """Smooth noise in [0, 1], w x h, repeating along v (rows): random cells, bicubic, wrapped."""
    import numpy as np
    small = rng.random((cells_v, cells_u)).astype(np.float32)
    tall = Image.fromarray(np.vstack([small, small, small]), 'F').resize((w, h * 3), Image.BICUBIC)
    return np.asarray(tall, np.float32)[h:2 * h]


def ruts_masks(seed=2026):
    """(full, two-track) opacity as uint8 arrays, rows along the track."""
    import numpy as np
    rng = np.random.default_rng(seed)
    w, h = RUTS_PX
    edge_noise = (.4 * _periodic_noise(rng, w, h, 6, 24) + .3 * _periodic_noise(rng, w, h, 12, 64)
                  + .18 * _periodic_noise(rng, w, h, 32, 200) + .12 * _periodic_noise(rng, w, h, 64, 600))
    u = (np.arange(w, dtype=np.float32) + .5) / w
    bed = .5 * (1 - style.RUTS_CORE)
    # 0 at the decal's edge, 1 at the bed's: the dirt ends where this plus the noise passes .5.
    # The noise fades out towards both, so the bed's edge and the decal's are never drawn.
    d = np.minimum(u, 1 - u)[None, :] / bed
    value = d + .9 * (edge_noise - .5) * np.clip(1 - d * d, 0, 1)
    value[:, d[0] >= 1] = 1.0
    full = np.clip((value - .5) * 8 + .5, 0, 1)
    gap_noise = (.5 * _periodic_noise(rng, w, h, 3, 40) + .3 * _periodic_noise(rng, w, h, 8, 160)
                 + .2 * _periodic_noise(rng, w, h, 24, 500))
    middle = np.abs(u - .5)[None, :] / .07 + 1.3 * (gap_noise - .5)
    grass = np.clip((.5 - middle) * 8 + .5, 0, 1)
    two = np.minimum(full, 1 - grass)
    return (full * 255).astype(np.uint8), (two * 255).astype(np.uint8)


def ruts_art(r):
    full, two = ruts_masks()
    Image.fromarray(full).convert('RGB').save(r / 'ruts_o.data.png')
    Image.fromarray(two).convert('RGB').save(r / 'ruts_two_o.data.png')
    (r / 'ruts.version').write_text(RUTS_ART_VERSION)


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
    seen = set()
    return json.dumps(style.dds({'order': list(PACKS), 'labels': LABELS, 'fields': fields, 'warm': {p: warm_defs(p, fields[p], seen) for p in PACKS},
                                 'environment': {p: environment(p) for p in PACKS}, 'extra': sun}))


def write_manifest(r):
    """Refresh pack settings independently of the expensive texture build."""
    tmp = r / 'packs.json.tmp'
    tmp.write_text(manifest_text(), encoding='utf8')
    os.replace(tmp, r / 'packs.json')
