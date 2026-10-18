"""Illustrative street elevation with the real material textures, not a game render."""
from functools import lru_cache
import io
import struct
from pathlib import Path
import zipfile

from PIL import Image, ImageDraw

import fast_style

ROOT = Path(__file__).resolve().parents[1]


def decode_image(data):
    # Pillow understands BC1/2/3 UNORM but not their sRGB header variants.
    # Their block bytes are identical. Decode those bytes as display RGB;
    # only this in-memory header changes, never the installed DDS file.
    if len(data) >= 148 and data[:4] == b'DDS ' and data[84:88] == b'DX10':
        fmt = struct.unpack_from('<I', data, 128)[0]
        if fmt in (72, 75, 78):
            data = data[:128] + struct.pack('<I', fmt-1) + data[132:]
    with Image.open(io.BytesIO(data)) as opened:
        return opened.convert('RGB')


@lru_cache(maxsize=96)
def material(kind, mods):
    spec = fast_style.MATERIALS['e2rf_' + kind]['Stages'][0]
    path = spec.get('baseColorMap', '')
    source = None
    image = None
    if path.startswith('/e2r_stream/'):
        relative = path.lstrip('/')
        planet = Path(mods) / 'mods' / 'earthng_planet.zip'
        try:
            with zipfile.ZipFile(planet) as archive:
                image = decode_image(archive.read(relative))
                source = 'installed planet'
        except (OSError, KeyError, ValueError, NotImplementedError, zipfile.BadZipFile):
            pass
        if image is None:
            suffix = relative.split('fast-art/', 1)[-1]
            for folder in ('art-distributable', 'art'):
                local = ROOT / 'data' / folder / suffix
                try:
                    image = decode_image(local.read_bytes())
                    source = 'local art'
                    break
                except (OSError, ValueError, NotImplementedError):
                    pass
    elif path.startswith('/assets/'):
        import fast_art
        try:
            relative = path.lstrip('/')[:-4] + '.dds'
            for name in ('tileable.zip', 'terrain.zip'):
                archive_path = fast_art.ASSETS / name
                if not archive_path.exists():
                    continue
                with zipfile.ZipFile(archive_path) as archive:
                    if relative in archive.namelist():
                        image = decode_image(archive.read(relative))
                        break
            if image is not None:
                source = 'game texture'
        except (OSError, ValueError, NotImplementedError, zipfile.BadZipFile):
            pass
    if image is None:
        colour = fast_style.KINDS[kind][1]
        image = Image.new('RGB', (96, 96), tuple(round(v*255) for v in colour[:3]))
        source = 'colour fallback'
    else:
        image.thumbnail((256, 256))
        tint = spec.get('baseColorFactor', [1, 1, 1])
        channels = image.split()
        image = Image.merge('RGB', [ch.point([min(255, round(v*tint[i])) for v in range(256)])
                                    for i, ch in enumerate(channels)])
    return image, source


def kinds(look):
    road = {'smooth': 'road', 'worn': 'road_worn', 'fresh': 'road_major'}[look['asphalt']]
    verge = {'grass': 'ground', 'dirt': 'bare_ground', 'dry': 'heath', 'gravel': 'scree'}[look['verge']]
    walls = {'panel': ['pnl_grey', 'lgg_cream', 'pnl_beige'], 'brick': ['brk_red', 'brk_white', 'brk_red'],
             'plaster': ['pls_yellow', 'pls_cream', 'pls_peach'], 'mixed': ['pnl_grey', 'brk_red', 'pls_cream']}[look['buildings']]
    return road, verge, ['wall_' + wall for wall in walls]


def render(look, include, mods, latitude=50):
    road, verge, walls = kinds(look)
    image = Image.new('RGB', (440, 230), '#dbe9ef')
    sources = {}

    def surface(kind, rect, repeat):
        texture, source = material(kind, mods)
        sources[kind] = source
        x0, y0, x1, y1 = rect
        patch = Image.new('RGB', (x1-x0, y1-y0))
        tile = texture.resize((repeat, repeat), Image.Resampling.LANCZOS)
        for x in range(0, patch.width, repeat):
            for y in range(0, patch.height, repeat):
                patch.paste(tile, (x, y))
        image.paste(patch, (x0, y0))

    surface(verge, (0, 122, 440, 164), 60)
    surface(road, (0, 164, 440, 230), 100)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 153, 440, 163), fill='#c8c5bd')
    if include.get('buildings', True):
        for i, wall in enumerate(walls):
            left = 18 + i*139
            top = (30, 48, 20)[i]
            surface(wall, (left, top, left+112, 142), 56 if 'lgg_' not in wall else 112)
            draw.rectangle((left, top-4, left+112, top), fill='#68716f')
            draw.rectangle((left, top, left+112, 142), outline='#707772')
    if look['markings'] != 'none':
        colour = '#efbd1f' if look['markings'] == 'yellow' else '#eeece0'
        for x in range(0, 440, 52):
            draw.rectangle((x, 195, x+28, 198), fill=colour)
    if include.get('treeRows', True) or include.get('cover', True):
        choice = look['trees']
        if choice == 'regional':
            choice = 'conifer' if abs(latitude) > 55 else 'mixed'
        for i, x in enumerate((12, 154, 296, 425)):
            draw.rectangle((x-2, 108, x+2, 151), fill='#645645')
            if choice == 'conifer' or choice == 'mixed' and i % 2:
                draw.polygon([(x, 72), (x-18, 127), (x+18, 127)], fill='#395c44')
            else:
                draw.ellipse((x-20, 77, x+20, 125), fill='#507349')
    if look['statics'] == 'street':
        for x in (80, 358):
            draw.line((x, 153, x, 85, x+18, 85), fill='#4d5559', width=3)
            draw.line((x+10, 87, x+21, 87), fill='#ece4b7', width=3)
    if look['statics'] != 'none' and include.get('stops', True):
        draw.rectangle((218, 123, 249, 151), fill='#839ca2', outline='#4d5559', width=2)
        draw.rectangle((214, 119, 253, 123), fill='#565f62')
    if include.get('barriers', True):
        draw.line((10, 145, 135, 145), fill='#7d8079', width=2)
        for x in range(10, 136, 8):
            draw.line((x, 140, x, 151), fill='#7d8079', width=1)
    return image, sources
