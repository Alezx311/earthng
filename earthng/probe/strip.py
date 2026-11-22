"""One sheet of a probe's stills in order (earthng/probe/ped_hit.lua: hit_<name>_<n>.png).

    python earthng/probe/strip.py <folder> hit_a out.jpg [--cols 8] [--every 1] [--crop x0,y0,x1,y1]
"""
import argparse
from pathlib import Path

from PIL import Image


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('folder', type=Path)
    p.add_argument('stem')
    p.add_argument('out', type=Path)
    p.add_argument('--cols', type=int, default=8)
    p.add_argument('--every', type=int, default=1)
    p.add_argument('--first', type=int, default=0)
    p.add_argument('--count', type=int, default=64)
    p.add_argument('--width', type=int, default=320, help='px of a still on the sheet')
    p.add_argument('--crop', help='x0,y0,x1,y1 as shares of the still (0..1)')
    a = p.parse_args()
    files = sorted(a.folder.glob(a.stem + '_*.png'))[a.first::a.every][:a.count]
    if not files:
        raise SystemExit('no stills')
    tiles = []
    for f in files:
        im = Image.open(f).convert('RGB')
        if a.crop:
            x0, y0, x1, y1 = (float(v) for v in a.crop.split(','))
            im = im.crop((int(x0 * im.width), int(y0 * im.height), int(x1 * im.width), int(y1 * im.height)))
        tiles.append(im.resize((a.width, round(a.width * im.height / im.width)), Image.LANCZOS))
    rows = (len(tiles) + a.cols - 1) // a.cols
    h = tiles[0].height
    sheet = Image.new('RGB', (a.cols * a.width, rows * h), 'black')
    for k, im in enumerate(tiles):
        sheet.paste(im, (k % a.cols * a.width, k // a.cols * h))
    sheet.save(a.out, quality=90)
    print(len(tiles), 'stills', sheet.size)


if __name__ == '__main__':
    main()
