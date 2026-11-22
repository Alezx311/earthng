"""What colour the land is from above, by kind: the Sentinel-2 composite (s2_colour.py) read over a
built pack's far rasters and averaged by the raster's cover class.

    .venv\\Scripts\\python.exe earthng\\ground_colour.py --pack <mods>/earthng_kyiv-oblast.zip [--out earthng/ground_targets.json]

A far raster (far/<region>.bin, rust far.rs) has a cover class and a built-up share for every
texel of the region; the composite gives the same texels' colour in the tone the far view and the
near sheets are drawn in (s2_colour.albedo). A class's colour is the median of its texels that
have nothing built on them and no other class beside them (a field's edge is half a hedge). The
table written is what fast_style tints the ground's own textures to (GROUND_SRGB), so a meadow
under the wheels is the meadow's colour in the picture from space.

Reads the open bucket `esa-worldcover-s2` (CC BY 4.0, see s2_colour.py) through its cache
(data/s2); nothing is downloaded whole.
"""
import argparse
import json
import struct
import zipfile
from pathlib import Path

import numpy as np

import s2_colour

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# the far raster's classes (far.lua FAR.COLOURS, far_preview.COLOURS) that are open land
CLASSES = {0: 'ground', 1: 'farmland', 2: 'meadow', 3: 'forest', 4: 'orchard', 8: 'park', 9: 'wetland', 10: 'bare',
           11: 'scrub', 14: 'rock'}


def raster(data):
    """A far raster's frame and its class and built-share grids (row 0 south)."""
    if data[:4] != b'EGF1':
        raise ValueError('not a far raster')
    u0, v0, nu, nv = struct.unpack_from('<iiII', data, 5)
    step, _sea = struct.unpack_from('<ff', data, 21)
    at = 29 + 2 * (nu + 1) * (nv + 1)
    cls = np.frombuffer(data, 'u1', nu * nv, at).reshape(nv, nu)
    built = np.frombuffer(data, 'u1', nu * nv, at + nu * nv).reshape(nv, nu)
    return u0, v0, nu, nv, step, cls, built


def inside(mask):
    """Texels whose four neighbours are in the mask too."""
    m = mask.copy()
    m[1:] &= mask[:-1]
    m[:-1] &= mask[1:]
    m[:, 1:] &= mask[:, :-1]
    m[:, :-1] &= mask[:, 1:]
    return m


def sample(pack, cache, emit=print, only=None):
    """{kind: N x 3 linear colours} of the pack's open land."""
    source = s2_colour.Source(cache, emit)
    out = {kind: [] for kind in CLASSES.values()}
    with zipfile.ZipFile(pack) as archive:
        names = set(archive.namelist())
        for region, (root, manifest) in sorted(s2_colour.pack_regions(archive).items()):
            path = f'{root}far/{region}.bin'
            frame = manifest.get('frame')
            if path not in names or not frame or (only and region not in only):
                continue
            u0, v0, nu, nv, step, cls, built = raster(archive.read(path))
            x0, y1 = frame['origin'][0] + u0 * step, frame['origin'][1] + (v0 + nv) * step
            rgb, mask = source.read(frame['crs'], x0, y1, step, step, nu, nv)
            if not mask.any():
                continue
            # the composite's row 0 is north, the raster's south
            colour, mask = s2_colour.albedo(rgb)[::-1], mask[::-1]
            for c, kind in CLASSES.items():
                pick = inside(cls == c) & (built == 0) & mask
                if pick.sum() >= 50:
                    out[kind].append(colour[pick])
            emit(f'{region}: {nu} x {nv} at {step:g} m')
    return {kind: np.concatenate(rows) for kind, rows in out.items() if rows}


def summary(samples):
    """{kind: {srgb: median colour 0-255, texels, spread: the middle half of its lightness}}."""
    out = {}
    for kind, a in samples.items():
        lum = a @ np.array([.2126, .7152, .0722])
        lo, hi = np.percentile(lum, (25, 75))
        mid = np.median(a[(lum >= lo) & (lum <= hi)], axis=0)
        srgb = s2_colour._srgb(mid) * 255
        out[kind] = {'srgb': [int(round(float(v))) for v in srgb], 'texels': int(len(a)),
                     'spread': [round(float(v), 4) for v in (lo, hi)]}
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', required=True, type=Path)
    p.add_argument('--cache', type=Path, default=ROOT / 'data' / 's2')
    p.add_argument('--region', action='append', help='only these regions of the pack')
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    result = summary(sample(a.pack, a.cache, only=set(a.region) if a.region else None))
    for kind, row in sorted(result.items()):
        print(f'{kind:10s} {row["srgb"]} texels {row["texels"]}')
    if a.out:
        a.out.write_text(json.dumps({'source': s2_colour.ATTRIBUTION, 'license': s2_colour.LICENSE, 'pack': a.pack.name,
                                     'tone': {'gain': s2_colour.GAIN, 'saturation': s2_colour.SATURATION},
                                     'kinds': result}, indent=1), encoding='utf8')


if __name__ == '__main__':
    main()
