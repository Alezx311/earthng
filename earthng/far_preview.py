"""Far-view rasters (earthng-far-v1, earthng-mapbuilder far) as pictures: cover classes over a
hillshade, built-up share in grey, landmarks as red dots. An offline check before the game.

python earthng/far_preview.py out/far/kyiv-oblast --out out/far/kyiv-oblast-preview.png
"""
import argparse
import struct
from pathlib import Path

import numpy as np
from PIL import Image

# class -> colour (far.lua FAR.COLOURS holds the same order)
COLOURS = [
    (118, 140, 84),   # 0 none: grass, unmapped land
    (170, 160, 104),  # 1 farmland
    (128, 156, 88),   # 2 meadow
    (46, 74, 40),     # 3 forest
    (104, 130, 70),   # 4 orchard
    (150, 140, 128),  # 5 residential
    (52, 86, 110),    # 6 water
    (120, 118, 114),  # 7 paved
    (86, 124, 66),    # 8 park
    (90, 104, 78),    # 9 wetland
    (176, 162, 132),  # 10 bare
    (98, 112, 70),    # 11 scrub
    (236, 240, 244),  # 12 snow
    (44, 76, 104),    # 13 sea
    (130, 126, 120),  # 14 rock
]


def read(path):
    data = Path(path).read_bytes()
    if data[:4] != b'EGF1':
        raise ValueError(f'{path}: not a far raster')
    u0, v0, nu, nv = struct.unpack_from('<iiII', data, 5)
    step, sea = struct.unpack_from('<ff', data, 21)
    at = 29
    elev = np.frombuffer(data, '<u2', (nu + 1) * (nv + 1), at).reshape(nv + 1, nu + 1)
    at += 2 * (nu + 1) * (nv + 1)
    cls = np.frombuffer(data, 'u1', nu * nv, at).reshape(nv, nu)
    built = np.frombuffer(data, 'u1', nu * nv, at + nu * nv).reshape(nv, nu)
    roof = np.frombuffer(data, 'u1', nu * nv, at + 2 * nu * nv).reshape(nv, nu)
    at += 3 * nu * nv
    (count,) = struct.unpack_from('<I', data, at)
    marks = np.frombuffer(data, np.dtype([('x', '<f4'), ('y', '<f4'), ('z', '<f4'), ('h', '<f4'), ('a', '<f4'),
                                          ('b', '<f4'), ('angle', '<f4'), ('kind', '<f4')]), count, at + 4)
    return dict(u0=u0, v0=v0, nu=nu, nv=nv, step=step, sea=sea, elev=elev, cls=cls, built=built, roof=roof,
                marks=marks)


def picture(r):
    h = np.where(r['elev'] > 0, r['elev'] / 4.0 - 500, np.nan)
    # pixel heights: the mean of the four corners
    hp = (h[:-1, :-1] + h[1:, :-1] + h[:-1, 1:] + h[1:, 1:]) / 4
    gy, gx = np.gradient(np.nan_to_num(hp, nan=np.nanmin(hp) if np.isfinite(hp).any() else 0), r['step'])
    shade = np.clip(1 + (-gx - gy) * 3, .55, 1.35)
    lut = np.array(COLOURS + [(0, 0, 0)] * (256 - len(COLOURS)), dtype=float)
    rgb = lut[r['cls']]
    b = r['built'][..., None] / 255.0
    rgb = rgb * (1 - .7 * b) + np.array([210, 200, 190]) * .7 * b
    rgb = rgb * shade[..., None]
    rgb[r['cls'] == 255] = (0, 0, 0)
    img = np.clip(rgb, 0, 255).astype(np.uint8)[::-1]     # north up
    for m in r['marks']:
        a = int(m['x'] / r['step']) - r['u0']
        v = r['nv'] - 1 - (int(m['y'] / r['step']) - r['v0'])
        if 0 <= a < r['nu'] and 0 <= v < r['nv']:
            img[v, a] = (230, 30, 30) if m['h'] < 100 else (255, 230, 0)
    return Image.fromarray(img)


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('folder', type=Path)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    rasters = [read(f) for f in sorted(a.folder.glob('*.bin'))]
    for f, r in zip(sorted(a.folder.glob('*.bin')), rasters):
        counts = np.bincount(r['cls'].ravel(), minlength=256)
        valid = r['cls'] != 255
        print(f.stem, f"{r['nu']}x{r['nv']}", 'elev', round(float((r['elev'][r['elev'] > 0] / 4 - 500).min()), 1),
              round(float((r['elev'][r['elev'] > 0] / 4 - 500).max()), 1), 'landmarks', len(r['marks']),
              'classes', {k: round(int(v) / max(1, int(valid.sum())), 3) for k, v in enumerate(counts[:15]) if v})
    # one picture per region side by side is enough for a check: each in its own frame
    pics = [picture(r) for r in rasters]
    width = sum(p.width for p in pics) + 4 * (len(pics) - 1)
    height = max(p.height for p in pics)
    sheet = Image.new('RGB', (width, height), (20, 20, 20))
    x = 0
    for pic in pics:
        sheet.paste(pic, (x, 0))
        x += pic.width + 4
    a.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(a.out)
    print(a.out)


if __name__ == '__main__':
    main()
