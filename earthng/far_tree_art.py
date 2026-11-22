"""The far trees' sheet: four tree silhouettes side by side, drawn, with their cut-out mask.

A far tile's trees are cards (generator.lua VEG.CARD): two crossed quads a tree, cut out of
this sheet. Cells, left to right: a round broadleaf crown, a tall narrow one, a pine (a flat
crown on a bare trunk), a spruce. A tree stands in the middle of its cell, its foot at the
cell's bottom edge, and fills the cell's height; the card is as wide as it is tall.

Drawn, not photographed: the planet ships no model of the game's or of the flora pack. The
colours are those of the near trees' crowns in the sun (the flora pack's, measured off a frame), so the far
wood and the near one are one colour where they meet.

    .venv/Scripts/python.exe earthng/far_tree_art.py out/far-trees      # the two PNGs, to look at
"""
import math
from pathlib import Path
import sys

import numpy as np
from PIL import Image

VERSION = '2'      # 2: the crowns as light as the near trees' in the sun (look-wood: the cards read a darker wood)
CELL = 256            # px a cell; the sheet is 4 cells wide
CELLS = ('broad', 'tall', 'pine', 'spruce')
# crown colours (sRGB): dark, mid, lit; the trunk
LEAF = ((54, 78, 34), (96, 134, 58), (146, 182, 88))
NEEDLE = ((42, 66, 36), (74, 110, 54), (114, 152, 80))
BARK = {'broad': (62, 54, 44), 'tall': (150, 148, 140), 'pine': (112, 82, 62), 'spruce': (58, 46, 38)}


def _noise(rng, size, scale):
    """Smooth 0..1 noise of `size` px with features of `scale` px."""
    n = max(2, int(math.ceil(size / scale)) + 2)
    grid = rng.random((n, n))
    ys, xs = np.mgrid[0:size, 0:size] / scale
    x0, y0 = xs.astype(int), ys.astype(int)
    tx, ty = xs - x0, ys - y0
    tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
    a = grid[y0, x0] * (1 - tx) + grid[y0, x0 + 1] * tx
    b = grid[y0 + 1, x0] * (1 - tx) + grid[y0 + 1, x0 + 1] * tx
    return a * (1 - ty) + b * ty


def _blobs(rng, size, centres):
    """Union of soft discs {x, y, r} (0..1 of the cell): its cover and, per pixel, the height of
    the nearest disc's dome (the crown's clumps catch the light on top)."""
    ys, xs = np.mgrid[0:size, 0:size] / size
    cover = np.zeros((size, size))
    dome = np.zeros((size, size))
    for x, y, r in centres:
        d = np.sqrt((xs - x) ** 2 + (ys - y) ** 2) / r
        inside = d < 1
        cover = np.maximum(cover, inside)
        # lit from the upper left: a dome shaded by its own normal
        h = np.sqrt(np.clip(1 - d * d, 0, 1))
        light = np.clip(.55 + .45 * (-(xs - x) / r * .5 - (ys - y) / r * .8), 0, 1) * h
        dome = np.where(inside, np.maximum(dome, light), dome)
    return cover, dome


def _crown(rng, kind):
    size = CELL
    if kind == 'broad':
        centres = [(.5 + rng.normal(0, .16), .36 + rng.normal(0, .13), rng.uniform(.09, .17)) for _ in range(46)]
        centres += [(.5, .38, .26)]
        trunk = (.5, .02, .62, 1.0)
    elif kind == 'tall':
        centres = [(.5 + rng.normal(0, .075), .40 + rng.normal(0, .2), rng.uniform(.06, .11)) for _ in range(52)]
        centres += [(.5, .42, .13), (.5, .25, .1), (.5, .58, .11)]
        trunk = (.5, .013, .55, 1.0)
    elif kind == 'pine':
        centres = [(.5 + rng.normal(0, .15), .2 + rng.normal(0, .06), rng.uniform(.07, .12)) for _ in range(34)]
        centres += [(.5, .2, .17)]
        trunk = (.5, .016, .2, 1.0)
    else:   # spruce: tiers that widen towards the foot
        centres = []
        for k in range(15):
            y = .06 + k * .058
            half = .03 + .2 * (k / 14) ** .9
            centres.append((.5, y, .025 + .6 * half))
            for _ in range(7):
                centres.append((.5 + rng.uniform(-half, half), y + rng.normal(0, .012), rng.uniform(.03, .055)))
        trunk = (.5, .012, .85, 1.0)
    centres = [(float(np.clip(x, .08, .92)), float(np.clip(y, .06, .95)), r) for x, y, r in centres]
    cover, dome = _blobs(rng, size, centres)
    # a ragged outline: the cover bitten by fine noise near its rim
    fine = _noise(rng, size, 5)
    cover = np.where((cover > 0) & (dome < .12) & (fine < .45), 0, cover)
    dark, mid, lit = LEAF if kind in ('broad', 'tall') else NEEDLE
    t = np.clip(dome * 1.25 + (_noise(rng, size, 9) - .5) * .5, 0, 1)
    rgb = np.zeros((size, size, 3))
    for c in range(3):
        rgb[..., c] = np.where(t < .5, dark[c] + (mid[c] - dark[c]) * t * 2, mid[c] + (lit[c] - mid[c]) * (t - .5) * 2)
    # the trunk under and through the crown
    ys, xs = np.mgrid[0:size, 0:size] / size
    tx, half, y0, y1 = trunk
    taper = half * (1 + (ys - y0) * 1.2)
    stem = (np.abs(xs - tx) < taper) & (ys >= y0) & (ys <= y1) & (cover == 0)
    bark = BARK[kind]
    shade = .75 + .5 * (xs - tx + taper) / (2 * taper + 1e-6)
    for c in range(3):
        rgb[..., c] = np.where(stem, bark[c] * shade, rgb[..., c])
    alpha = np.maximum(cover, stem)
    # colour under the cut-out's rim too: a mip must not bleed black into the crown
    fill = np.array(mid, dtype=float)
    for c in range(3):
        rgb[..., c] = np.where(alpha > 0, rgb[..., c], fill[c])
    return np.clip(rgb, 0, 255).astype(np.uint8), (alpha * 255).astype(np.uint8)


def sheet():
    """(colour RGB image, mask L image) of the four cells."""
    rng = np.random.default_rng(20261122)
    colour = np.zeros((CELL, CELL * len(CELLS), 3), dtype=np.uint8)
    mask = np.zeros((CELL, CELL * len(CELLS)), dtype=np.uint8)
    for k, kind in enumerate(CELLS):
        rgb, a = _crown(rng, kind)
        colour[:, k * CELL:(k + 1) * CELL], mask[:, k * CELL:(k + 1) * CELL] = rgb, a
    return Image.fromarray(colour), Image.fromarray(mask)


def write(real):
    """The sheet into an art build's `real` folder (fast_art's stage)."""
    colour, mask = sheet()
    colour.save(real / 'far_trees.color.png')
    mask.convert('RGB').save(real / 'far_trees_o.data.png')
    (real / 'far_trees.version').write_text(VERSION)


if __name__ == '__main__':
    out = Path(sys.argv[1] if len(sys.argv) > 1 else 'out/far-trees')
    out.mkdir(parents=True, exist_ok=True)
    colour, mask = sheet()
    colour.save(out / 'far_trees.color.png')
    mask.save(out / 'far_trees_o.png')
    preview = Image.new('RGB', colour.size, (150, 170, 190))
    preview.paste(colour, (0, 0), mask)
    preview.save(out / 'far_trees_preview.png')
    print(out / 'far_trees_preview.png')
