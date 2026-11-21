"""The flora pack's blocks on one sheet: a picture of every model with its name, height and triangles.

    blender -b --factory-startup -P earthng/flora_preview.py -- --pack data/flora/all out/flora/blocks --top
    python earthng/flora_sheet.py                      # out/flora/blocks.jpg, a sheet a place too

The pictures are flora_preview.py's (Blender renders what the converter wrote); the names and
numbers are out/flora/blocks.json's (earthng/build_flora.py). A sheet is what there is to build
with: it shows no model the licence forbids to share, only frames of them.
"""
import argparse
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CELL, LABEL = 256, 46


def font(size):
    for name in ('segoeui.ttf', 'arial.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def sheet(blocks, pictures, columns=8, title=None):
    """One image of the blocks' pictures in rows of `columns`, each with two lines under it."""
    rows = -(-len(blocks) // columns)
    head = 54 if title else 0
    image = Image.new('RGB', (columns * CELL, head + rows * (CELL + LABEL)), (24, 26, 28))
    draw = ImageDraw.Draw(image)
    big, small = font(17), font(13)
    if title:
        draw.text((14, 14), title, fill=(236, 236, 230), font=font(24))
    for index, block in enumerate(blocks):
        x, y = index % columns * CELL, head + index // columns * (CELL + LABEL)
        picture = Path(pictures) / f"{block['id']}.png"
        if picture.exists():
            image.paste(Image.open(picture).convert('RGB').resize((CELL, CELL), Image.LANCZOS), (x, y))
        else:
            draw.rectangle((x, y, x + CELL - 1, y + CELL - 1), outline=(90, 90, 90))
            draw.text((x + 12, y + 110), 'no picture', fill=(150, 150, 150), font=small)
        draw.text((x + 8, y + CELL + 4), f"{block['uk'] or block['species']}", fill=(236, 236, 230), font=big)
        triangles = ' / '.join(f'{t // 1000}k' if t >= 10000 else str(t) for t in block['triangles'])
        draw.text((x + 8, y + CELL + 25), f"{block['id']}  {block['height']:.1f} m  {triangles}", fill=(160, 166, 160), font=small)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--blocks', type=Path, default=ROOT / 'out' / 'flora' / 'blocks.json')
    parser.add_argument('--pictures', type=Path, default=ROOT / 'out' / 'flora' / 'blocks')
    parser.add_argument('--out', type=Path, default=ROOT / 'out' / 'flora' / 'blocks.jpg')
    a = parser.parse_args()
    blocks = json.loads(a.blocks.read_text(encoding='utf8'))
    sheet(blocks, a.pictures, title=f'EarthNG: блоки рослинності FoliMesh ({len(blocks)})').save(a.out, quality=88)
    print(a.out)
    places = {}
    for block in blocks:
        for place in block['use']:
            places.setdefault(place, []).append(block)
    for place, own in sorted(places.items()):
        out = a.out.with_name(f'{a.out.stem}-{place}.jpg')
        sheet(own, a.pictures, columns=6, title=f'{place}: {len(own)}').save(out, quality=88)
        print(out)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    main()
