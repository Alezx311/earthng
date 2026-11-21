"""The real colour of the land from Sentinel-2, for a pack's far view and its near ground.

Source: the ESA WorldCover 2021 annual composite of Sentinel-2 L2A (red, green, blue, near
infrared; 10 m; cloud-free medians of a year), published as cloud-optimised GeoTIFFs of one degree
in the open bucket `esa-worldcover-s2` (https://registry.opendata.aws/esa-worldcover-vito-composites/),
licence CC BY 4.0: (c) ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021)
processed by ESA WorldCover consortium. Only the builder reads it; a pack carries its own maps and
the game stays offline. A window is read from the overview nearest the wanted step, a few range
requests a degree: nothing is downloaded whole.

Two products, both in the region's own frame (fast_sources.Frame: metres east and north of its
origin):

- the far colour map (`far/<region>.s2.color.dds`): the region's far raster (far/<region>.bin) in
  real colour, the same texels as the drawn map beside it (rust far_tex.rs), which keeps the
  water; far.lua takes it in place of that one.
- the near sheets (`far/<region>.s2.bin`): squares of SHEET_M metres (6 x 6 tiles) with a gutter
  round them, one small DDS each, in one file with an index. world.lua writes out the few round the
  car and gives each a material of its own: the sheet as base colour under the grass's fine detail
  (generator.lua S2). A tile lies in one sheet, so its ground never reads across a sheet's edge.

    python earthng/s2_colour.py --pack earthng_xx.zip --out earthng_xx_s2.zip [--lat .. --lon .. --radius-km 15]

writes the maps of a built pack into a second ZIP that installs beside it (same paths in the
game's file system); build_country adds them to a new pack itself.
"""
import argparse
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import zipfile

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fast_dds  # noqa: E402

BUCKET = 'https://esa-worldcover-s2.s3.eu-central-1.amazonaws.com/rgbnir/2021'
CREDIT = 'ESA WorldCover 2021 / Copernicus Sentinel-2'
ATTRIBUTION = ('© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) '
               'processed by ESA WorldCover consortium')
LICENSE = 'CC-BY-4.0'
SOURCE_STEP = 9.3           # m a source pixel along a meridian (1 / 12000 degree)
OVERVIEWS = (2, 4, 8, 16)   # the files' own reduced levels
READERS = 6                 # degrees read at once

# The composite is surface reflectance (x 10000). Land is dark in it (Kyiv's degree: a median
# luminance of .06), darker than the albedo the pack's own ground is drawn in (fast_tone: land
# about .10); GAIN brings the two together so real colour is not a dark patch beside drawn
# ground. Above KNEE the gain eases off: sand, salt and snow keep their place without clipping.
# At 1.7 and a saturation of 1.25 the land round Vytachiv came out a pale beige under the
# game's sun, its grass a green lawn on sand (hyperreal run-03).
GAIN = 1.4
KNEE, SHOULDER = .26, .3
# The colour's distance from grey is given back: a yearly median is flatter than any one day
SATURATION = 1.45
# The world is drawn in July and a year's median is browner than July: where the land is green
# for most of the year (the near infrared says so: NDVI from NDVI_LOW, in full from NDVI_HIGH)
# its colour is turned SUMMER_SHARE of the way to SUMMER times itself, greener and a little
# darker. Bare soil, sand, rock and roofs have no such NDVI and keep the colour they have.
SUMMER = (.82, 1.08, .72)
SUMMER_SHARE = .65
NDVI_LOW, NDVI_HIGH = .2, .6

# Near sheets: SHEET_M of land a sheet (a multiple of the 500 m tile), GUTTER_M round it for the
# filter and the first mips, at one of three steps by the pack's size. A pack of a city draws the
# real 10 m picture; a country of 600,000 km2 would be 4 GB of it and takes every fourth pixel.
SHEET_M, GUTTER_M = 3000.0, 100.0
TIERS = ((8000., 12.5), (80000., 25.), (math.inf, 50.))   # up to this many km2: metres a texel
MAGIC = b'EGS2'


def tier(area_km2):
    """Metres a texel of the near sheets for a pack of this many km2."""
    return next(step for limit, step in TIERS if area_km2 <= limit)


def sheet_px(step):
    return int(round((SHEET_M + 2 * GUTTER_M) / step))


def tile_name(lat, lon):
    """The one-degree file whose south-west corner is (lat, lon), whole degrees."""
    return f'{"N" if lat >= 0 else "S"}{abs(lat):02d}{"E" if lon >= 0 else "W"}{abs(lon):03d}'


def tile_url(lat, lon):
    name = tile_name(lat, lon)
    return f'{BUCKET}/{name[:3]}/ESA_WorldCover_10m_2021_v200_{name}_S2RGBNIR.tif'


SLACK = 1.3                 # a level whose pixels are up to this much coarser than the step is read


def overview_level(step):
    """The rasterio overview_level whose pixels are the largest not over SLACK x `step` metres
    (None: the full picture). A far map of 29 m texels reads the 37 m level, a quarter of the
    bytes of the 19 m one, and is no softer to the eye from 3 km; a near sheet of 12.5 m reads
    the picture itself."""
    level = None
    for k, factor in enumerate(OVERVIEWS):
        if SOURCE_STEP * factor <= step * SLACK:
            level = k
    return level


def albedo(reflectance):
    """Linear base colour (0..1, H x W x 3) of linear surface reflectance (0..1): red, green,
    blue and, where the source gives it, near infrared as a fourth band."""
    r = np.asarray(reflectance, np.float32)
    a = r[..., :3] * GAIN
    over = np.maximum(a - KNEE, 0)
    a = np.where(a > KNEE, KNEE + over / (1 + over / SHOULDER), a)
    if r.shape[-1] > 3:
        red, nir = r[..., 0], r[..., 3]
        ndvi = (nir - red) / np.maximum(nir + red, 1e-4)
        v = np.clip((ndvi - NDVI_LOW) / (NDVI_HIGH - NDVI_LOW), 0, 1)
        v = v * v * (3 - 2 * v) * SUMMER_SHARE
        a = a * (1 + (np.array(SUMMER, np.float32) - 1) * v[..., None])
    lum = (a @ np.array([.2126, .7152, .0722], np.float32))[..., None]
    return np.clip(lum + (a - lum) * SATURATION, 0, 1)


def _srgb(a):
    a = np.clip(a, 0, 1)
    return np.where(a <= .0031308, 12.92 * a, 1.055 * a ** (1 / 2.4) - .055)


def _linear(a):
    return np.where(a <= .04045, a / 12.92, ((a + .055) / 1.055) ** 2.4)


class Source:
    """Windows of the composite in any projected frame. cache: a folder for what was read (a
    window is a few megabytes; a rebuild of the same pack reads nothing again)."""

    def __init__(self, cache=None, emit=None):
        self.cache = Path(cache) if cache else None
        self.emit = emit or (lambda text: None)
        self.missing = set()

    def _env(self):
        import rasterio
        return rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',
                            GDAL_HTTP_MAX_RETRY=3, GDAL_HTTP_RETRY_DELAY=2, GDAL_HTTP_TIMEOUT=60,
                            GDAL_HTTP_USERAGENT='EarthNG MapBuilder (offline ground colour)',
                            VSI_CACHE=True, GDAL_CACHEMAX=256)

    def read(self, crs, x0, y1, step_x, step_y, width, height):
        """Reflectance (0..1, float32, H x W x 4: red, green, blue, near infrared) of the grid whose top-left
        corner is (x0, y1) in `crs` and whose texels are step_x by step_y metres, row 0 north;
        and the mask of texels that have data. Degrees with no file (open sea) stay empty.

        Each degree under the grid gives one window of the level nearest the step (one ranged
        read of its blocks), and the grid's texels are sampled from it between its four nearest
        pixels. A warped read through GDAL asked the server block by block: eight minutes a
        far map where this takes seconds."""
        key = None
        if self.cache:
            import hashlib
            key = hashlib.sha256(json.dumps([crs, x0, y1, step_x, step_y, width, height,
                                             overview_level(min(step_x, step_y)), 'window4']).encode()).hexdigest()[:24]
            hit = self.cache / f'{key}.npz'
            if hit.is_file():
                with np.load(hit) as data:
                    return data['rgb'].astype(np.float32) / 10000, data['rgb'].any(axis=2)
        lon, lat = self.lonlat(crs, x0, y1, step_x, step_y, width, height)
        level = overview_level(min(step_x, step_y))
        factor = 1 if level is None else OVERVIEWS[level]
        per = DEGREE_PX / factor            # pixels of the level a degree
        degrees = [(la, lo) for la in range(math.floor(float(lat.min())), math.floor(float(lat.max())) + 1)
                   for lo in range(math.floor(float(lon.min())), math.floor(float(lon.max())) + 1)
                   if tile_url(la, lo) not in self.missing]
        out = np.zeros((height, width, 4), np.uint16)

        def one(degree):
            la, lo = degree
            inside = (lat >= la) & (lat < la + 1) & (lon >= lo) & (lon < lo + 1)
            if not inside.any():
                return degree, None, None
            # the level's pixel of every texel in this degree: column from its west edge, row from its north
            col, row = (lon[inside] - lo) * per - .5, (la + 1 - lat[inside]) * per - .5
            c0, c1 = max(0, math.floor(float(col.min()))), min(int(per) - 1, math.floor(float(col.max())) + 1)
            r0, r1 = max(0, math.floor(float(row.min()))), min(int(per) - 1, math.floor(float(row.max())) + 1)
            window = self.window(la, lo, level, c0, r0, c1 - c0 + 1, r1 - r0 + 1)
            if window is None:
                return degree, None, None
            return degree, inside, bilinear(window, col - c0, row - r0)

        # the degrees of a window side by side: the time is the server's, not ours
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(min(READERS, max(1, len(degrees)))) as pool:
            parts = list(pool.map(one, degrees))
        for degree, inside, values in parts:
            if inside is not None:
                out[inside] = values
                self.emit(f'Sentinel-2: {tile_name(*degree)} read at {min(step_x, step_y):g} m')
        if key:
            self.cache.mkdir(parents=True, exist_ok=True)
            tmp = self.cache / f'{key}.tmp.npz'
            np.savez_compressed(tmp, rgb=out)
            tmp.replace(self.cache / f'{key}.npz')
        return out.astype(np.float32) / 10000, out.any(axis=2)

    @staticmethod
    def lonlat(crs, x0, y1, step_x, step_y, width, height, every=16):
        """Longitude and latitude of every texel's centre (H x W each). The projection is asked
        every `every` texels and read between: over a few hundred metres it is a plane to a
        millimetre."""
        import pyproj
        to_geo = pyproj.Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
        nx, ny = (width - 1) // every + 2, (height - 1) // every + 2
        gx = x0 + (np.arange(nx) * every + .5) * step_x
        gy = y1 - (np.arange(ny) * every + .5) * step_y
        mx, my = np.meshgrid(gx, gy)
        glon, glat = to_geo.transform(mx.ravel(), my.ravel())
        glon, glat = np.asarray(glon).reshape(ny, nx), np.asarray(glat).reshape(ny, nx)
        fx, fy = np.arange(width) / every, np.arange(height) / every
        ix, iy = np.minimum(fx.astype(int), nx - 2), np.minimum(fy.astype(int), ny - 2)
        tx, ty = (fx - ix)[None, :], (fy - iy)[:, None]

        def spread(g):
            a, b = g[iy][:, ix], g[iy][:, ix + 1]
            c, d = g[iy + 1][:, ix], g[iy + 1][:, ix + 1]
            return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty
        return spread(glon), spread(glat)

    def window(self, la, lo, level, col, row, width, height):
        """Pixels (H x W x 4, uint16) of a degree's file at an overview level, or None where
        there is no file (open sea)."""
        import rasterio
        from rasterio.windows import Window
        url = tile_url(la, lo)
        with self._env():
            try:
                options = {} if level is None else {'overview_level': level}
                with rasterio.open('/vsicurl/' + url, **options) as ds:
                    return np.moveaxis(ds.read(indexes=[1, 2, 3, 4], window=Window(col, row, width, height)), 0, -1)
            except rasterio.errors.RasterioIOError as exc:
                if '404' in str(exc):
                    self.missing.add(url)
                    return None
                raise


DEGREE_PX = 12000           # pixels of the full picture a degree


def bilinear(image, col, row):
    """image (H x W x C) read at fractional pixel places (col, row: 1-D), clamped at its edges.
    A pixel without data (0 in every band) gives none to its neighbours: the value there is the
    nearest pixel's."""
    h, w = image.shape[:2]
    col, row = np.clip(col, 0, w - 1), np.clip(row, 0, h - 1)
    c0, r0 = np.minimum(col.astype(int), max(0, w - 2)), np.minimum(row.astype(int), max(0, h - 2))
    c1, r1 = np.minimum(c0 + 1, w - 1), np.minimum(r0 + 1, h - 1)
    tx, ty = (col - c0)[:, None], (row - r0)[:, None]
    a, b, c, d = (image[r, cc].astype(np.float32) for r, cc in ((r0, c0), (r0, c1), (r1, c0), (r1, c1)))
    value = (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty
    nearest = image[np.rint(row).astype(int), np.rint(col).astype(int)]
    empty = ~(a.any(axis=1) & b.any(axis=1) & c.any(axis=1) & d.any(axis=1))
    out = np.rint(value).astype(np.uint16)
    out[empty] = nearest[empty]
    return out


def fill(rgb, mask):
    """Texels without data take the mean of those with data round them, pass by pass (the
    filter and the mips of a sheet read past the land's edge)."""
    if mask.all() or not mask.any():
        return rgb
    rgb, mask = rgb.copy(), mask.copy()
    for _ in range(64):
        if mask.all():
            break
        total, count = np.zeros_like(rgb), np.zeros(mask.shape, np.float32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx or dy:
                    m = np.roll(mask, (dy, dx), (0, 1))
                    # nothing wraps round the picture
                    if dy == 1: m[0, :] = False
                    if dy == -1: m[-1, :] = False
                    if dx == 1: m[:, 0] = False
                    if dx == -1: m[:, -1] = False
                    total += np.where(m[..., None], np.roll(rgb, (dy, dx), (0, 1)), 0)
                    count += m
        grow = ~mask & (count > 0)
        rgb[grow] = total[grow] / count[grow][:, None]
        mask |= grow
    rgb[~mask] = rgb[mask].mean(axis=0)
    return rgb


# --- the far colour map ---------------------------------------------------------------------------

def far_raster(data):
    """(u0, v0, nu, nv, step) of a far raster (far/<region>.bin, rust far.rs 'EGF1'): it covers
    x from u0 * step to (u0 + nu) * step and y from v0 * step likewise, in the region's metres."""
    if data[:4] != b'EGF1':
        raise ValueError('not a far raster')
    u0, v0, nu, nv, step, _sea = struct.unpack_from('<iiIIff', data, 5)
    return u0, v0, nu, nv, step


def dds_image(data):
    """The first level of a BC1 DDS (the pack's own maps, fast_dds and rust far_tex.rs) as an
    H x W x 3 uint8 array of the stored values. Pillow reads no DX10 header marked sRGB."""
    if data[:4] != b'DDS ':
        raise ValueError('not a DDS')
    h, w = struct.unpack_from('<II', data, 12)
    at = 128 + (20 if data[84:88] == b'DX10' else 0)
    n = (w // 4) * (h // 4)
    blocks = np.frombuffer(data, '<u4', n * 2, at).reshape(n, 2)
    c0, c1 = blocks[:, 0] & 0xffff, blocks[:, 0] >> 16
    p0, p1 = fast_dds._unpack(c0), fast_dds._unpack(c1)
    four = (c0 > c1)[:, None]
    palette = np.stack([p0, p1, np.where(four, (2 * p0 + p1) / 3, (p0 + p1) / 2), np.where(four, (p0 + 2 * p1) / 3, 0)], 1)
    index = (blocks[:, 1][:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3
    texels = palette[np.arange(n)[:, None], index]
    return (texels.reshape(h // 4, w // 4, 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(h, w, 3) + .5).astype(np.uint8)


def far_map(source, frame, raster, drawn=None, rough=None):
    """The far colour map of a region in real colour: a PIL image the size of the drawn map
    (`drawn`: its DDS bytes; without one, a power of two near the raster's own size). Water
    (the drawn map's smooth texels, `rough`: its roughness DDS) keeps the drawn colour: the
    composite's water is whatever the sun and the silt made of it that year."""
    u0, v0, nu, nv, step = raster
    if drawn is not None:
        base = dds_image(drawn)
        height, width = base.shape[:2]
    else:
        base = None
        width, height = (max(4, 1 << round(math.log2(max(4, n * step / 50)))) for n in (nu, nv))
    x0, y1 = frame['origin'][0] + u0 * step, frame['origin'][1] + (v0 + nv) * step
    rgb, mask = source.read(frame['crs'], x0, y1, nu * step / width, nv * step / height, width, height)
    if not mask.any():
        return None
    colour = albedo(fill(rgb, mask))
    if base is not None:
        keep = ~mask
        if rough is not None:
            smooth = np.asarray(Image.fromarray(dds_image(rough)[..., 0]).resize((width, height), Image.BILINEAR)) < 128
            keep = keep | smooth
        if keep.any():
            colour = np.where(keep[..., None], _linear(np.asarray(base, np.float32) / 255), colour)
    return Image.fromarray((_srgb(colour) * 255 + .5).astype(np.uint8))


def dds_bytes(image, srgb=True):
    """A PIL image as the game's BC1 DDS (fast_dds), in memory."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix='earthng-s2-') as folder:
        path = Path(folder) / ('map.color.dds' if srgb else 'map.data.dds')
        fast_dds.save(image, path, srgb=srgb)
        return path.read_bytes()


# --- the near sheets ------------------------------------------------------------------------------

def sheets_of(bounds):
    """(I0, J0, NI, NJ): the sheets under a region's bounds (x0, y0, x1, y1 in its metres)."""
    i0, j0 = math.floor(bounds[0] / SHEET_M), math.floor(bounds[1] / SHEET_M)
    i1, j1 = math.ceil(bounds[2] / SHEET_M), math.ceil(bounds[3] / SHEET_M)
    return i0, j0, max(0, i1 - i0), max(0, j1 - j0)


def near_sheets(source, frame, bounds, step, wanted=None, emit=None):
    """The near sheets of a region as the bytes of far/<region>.s2.bin, or None when the region
    has no data at all. wanted(I, J) -> bool limits the sheets (a spot of a big pack); the
    region is read in blocks of BLOCK sheets a side, one request for each."""
    BLOCK = 4
    i0, j0, ni, nj = sheets_of(bounds)
    px, gutter = sheet_px(step), int(round(GUTTER_M / step))
    payload = int(round(SHEET_M / step))
    assert px == payload + 2 * gutter and px & (px - 1) == 0, (px, payload, gutter)
    entries = {}
    for bj in range(0, nj, BLOCK):
        for bi in range(0, ni, BLOCK):
            cells = [(i0 + bi + a, j0 + bj + b) for b in range(min(BLOCK, nj - bj)) for a in range(min(BLOCK, ni - bi))
                     if wanted is None or wanted(i0 + bi + a, j0 + bj + b)]
            if not cells:
                continue
            wi, wj = min(BLOCK, ni - bi), min(BLOCK, nj - bj)
            # the block with one gutter round it: every sheet's own gutter is its neighbours' land
            width, height = wi * payload + 2 * gutter, wj * payload + 2 * gutter
            x0 = frame['origin'][0] + (i0 + bi) * SHEET_M - gutter * step
            y1 = frame['origin'][1] + (j0 + bj + wj) * SHEET_M + gutter * step
            rgb, mask = source.read(frame['crs'], x0, y1, step, step, width, height)
            if not mask.any():
                continue
            colour = albedo(fill(rgb, mask))
            image = (_srgb(colour) * 255 + .5).astype(np.uint8)
            for I, J in cells:
                left = (I - i0 - bi) * payload
                top = (j0 + bj + wj - 1 - J) * payload
                part = mask[top:top + px, left:left + px]
                if part.any():
                    entries[(I, J)] = dds_bytes(Image.fromarray(image[top:top + px, left:left + px]))
            if emit:
                emit(f'Sentinel-2 sheets: {len(entries)} of {ni * nj}')
    if not entries:
        return None
    return pack_sheets(entries, step, px, gutter, (i0, j0, ni, nj))


def pack_sheets(entries, step, px, gutter, grid):
    """far/<region>.s2.bin: 'EGS2', version, step in mm, sheet side in px, gutter in px, sheet
    in mm of land, I0, J0, NI, NJ, then NI * NJ pairs (offset, length), row by row from J0 (a
    length of 0: no sheet), then the DDS files end to end. Little endian."""
    i0, j0, ni, nj = grid
    head = MAGIC + struct.pack('<BIIIIiiII', 1, int(round(step * 1000)), px, gutter, int(round(SHEET_M * 1000)), i0, j0, ni, nj)
    at = len(head) + 8 * ni * nj
    table, body = [], []
    for J in range(j0, j0 + nj):
        for I in range(i0, i0 + ni):
            data = entries.get((I, J))
            if data:
                table.append(struct.pack('<II', at, len(data)))
                body.append(data)
                at += len(data)
            else:
                table.append(struct.pack('<II', 0, 0))
    return head + b''.join(table) + b''.join(body)


def read_sheets(data):
    """The header of a sheets file and its {(I, J): DDS bytes} (the tests and the tools)."""
    if data[:4] != MAGIC:
        raise ValueError('not a sheets file')
    version, step, px, gutter, sheet, i0, j0, ni, nj = struct.unpack_from('<BIIIIiiII', data, 4)
    head = {'version': version, 'step': step / 1000, 'px': px, 'gutter': gutter, 'sheet': sheet / 1000,
            'i0': i0, 'j0': j0, 'ni': ni, 'nj': nj}
    at = 4 + struct.calcsize('<BIIIIiiII')
    out = {}
    for n in range(ni * nj):
        offset, length = struct.unpack_from('<II', data, at + 8 * n)
        if length:
            out[(i0 + n % ni, j0 + n // ni)] = data[offset:offset + length]
    return head, out


# --- a pack ---------------------------------------------------------------------------------------

def pack_regions(archive):
    """{region id: (root path, manifest dict)} of a pack ZIP."""
    out = {}
    for name in archive.namelist():
        if '/regions/' in name and name.endswith('/manifest.json'):
            region = name.split('/')[-2]
            out[region] = (name[:-len(f'regions/{region}/manifest.json')], json.loads(archive.read(name)))
    return out


def region_area_km2(manifest):
    """The land a region's cells hold (its halo into the next region included)."""
    return manifest.get('cellCount', 0) * (manifest.get('cellSize', 1000) / 1000) ** 2


def region_blocks(manifest):
    """The squares of the region's frame that hold cells: [(x0, y0, x1, y1)], metres."""
    side = manifest.get('blockCells', 8) * manifest.get('cellSize', 1000)
    out = []
    for key in manifest.get('blocks') or {}:
        bi, bj = (int(v) for v in key.split('_'))
        out.append((bi * side, bj * side, (bi + 1) * side, (bj + 1) * side))
    return out


def build_pack(pack, cache, emit=print, spot=None, cancel=None, far=True, near=True):
    """The real-colour maps of a built pack: {path in the pack: bytes}. spot: (lat, lon, km), only
    the near sheets within that distance (a look at a big pack without reading all of it)."""
    import pyproj
    source = Source(cache, emit)
    out = {}
    with zipfile.ZipFile(pack) as archive:
        names = set(archive.namelist())
        regions = pack_regions(archive)
        area = sum(region_area_km2(m) for _, m in regions.values())
        step = tier(area)
        emit(f'Sentinel-2 ground colour: {len(regions)} regions, {area:.0f} km2, near sheets at {step:g} m')
        for region in sorted(regions):
            if cancel is not None and cancel.is_set():
                raise InterruptedError('build stopped')
            root, manifest = regions[region]
            frame, blocks = manifest.get('frame'), region_blocks(manifest)
            if not frame or not blocks:
                continue
            bounds = [min(b[0] for b in blocks), min(b[1] for b in blocks), max(b[2] for b in blocks), max(b[3] for b in blocks)]

            def held(I, J):
                # a sheet with any of the region's cells under it
                x0, y0 = I * SHEET_M, J * SHEET_M
                return any(b[0] < x0 + SHEET_M and b[2] > x0 and b[1] < y0 + SHEET_M and b[3] > y0 for b in blocks)
            wanted = held
            if spot:
                to_frame = pyproj.Transformer.from_crs('EPSG:4326', frame['crs'], always_xy=True)
                sx, sy = to_frame.transform(spot[1], spot[0])
                sx, sy, reach = sx - frame['origin'][0], sy - frame['origin'][1], spot[2] * 1000

                def wanted(I, J, sx=sx, sy=sy, reach=reach, held=held):
                    cx, cy = (I + .5) * SHEET_M, (J + .5) * SHEET_M
                    return held(I, J) and math.hypot(cx - sx, cy - sy) <= reach + SHEET_M
                if not (bounds[0] - reach <= sx <= bounds[2] + reach and bounds[1] - reach <= sy <= bounds[3] + reach):
                    continue
            bin_path = f'{root}far/{region}.bin'
            if far and bin_path in names:
                drawn, rough = f'{root}far/{region}.color.dds', f'{root}far/{region}_r.data.dds'
                image = far_map(source, frame, far_raster(archive.read(bin_path)),
                                archive.read(drawn) if drawn in names else None,
                                archive.read(rough) if rough in names else None)
                if image is not None:
                    out[f'{root}far/{region}.s2.color.dds'] = dds_bytes(image)
                    emit(f'Sentinel-2: far map of {region} {image.size[0]} x {image.size[1]}')
            if near:
                data = near_sheets(source, frame, bounds, step, wanted, emit)
                if data:
                    out[f'{root}far/{region}.s2.bin'] = data
    return out


def write_archive(archive, files):
    for path in sorted(files):
        # no clock in the pack: the same sources give the same bytes
        info = zipfile.ZipInfo(path, date_time=(2020, 1, 1, 0, 0, 0))
        info.compress_type, info.external_attr = zipfile.ZIP_STORED, 0o600 << 16
        archive.writestr(info, files[path])


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', type=Path, required=True, help='a built earthng_<id>.zip')
    p.add_argument('--out', type=Path, required=True, help='the ZIP of maps to install beside it')
    p.add_argument('--cache', type=Path, default=HERE.parent / 'data' / 's2')
    p.add_argument('--lat', type=float)
    p.add_argument('--lon', type=float)
    p.add_argument('--radius-km', type=float, default=15)
    p.add_argument('--no-far', action='store_true')
    p.add_argument('--no-near', action='store_true')
    a = p.parse_args()
    spot = (a.lat, a.lon, a.radius_km) if a.lat is not None and a.lon is not None else None
    files = build_pack(a.pack, a.cache, spot=spot, far=not a.no_far, near=not a.no_near)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = a.out.with_suffix('.tmp')
    with zipfile.ZipFile(tmp, 'w', allowZip64=True) as archive:
        write_archive(archive, files)
    os.replace(tmp, a.out)
    print(a.out, f'{len(files)} files, {sum(map(len, files.values())) / 1e6:.1f} MB')


if __name__ == '__main__':
    main()
