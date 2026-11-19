"""Rebuild the small offline image sheets shipped in mod/earthng/planet/photos.

Normal planet builds package the prepared sheets and need no imagery service.
Each sheet stores its bounds in normalized Web Mercator coordinates (northwest
origin). Add a sheet and credit here to extend the atlas to another place.
"""
import io
import json
import math
from pathlib import Path
from urllib.request import urlopen

import numpy as np
from PIL import Image, ImageDraw
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
import build_basemap
from map_photo_codec import save_photo


OUT = Path(__file__).resolve().parents[1] / 'mod/earthng/planet/photos'
NASA = ('https://assets.science.nasa.gov/content/dam/science/esd/eo/images/bmng/'
        'bmng-topography/july/world.topo.200407.3x5400x2700.jpg')
WORLD_COVER = ('https://esa-worldcover-s2.s3.eu-central-1.amazonaws.com/rgbnir/2021/'
               '{lat}/ESA_WorldCover_10m_2021_v200_{tile}_S2RGBNIR.tif')
NAIP = ('https://naipeuwest.blob.core.windows.net/naip/v002/ca/2024/ca_060cm_2024/'
        '37122/m_3712213_se_10_060_20240520.tif')
ORIGIN = math.pi * 6378137  # half the width of EPSG:3857, metres


def with_boundaries(image, boundaries):
    # Draw separately at each sheet resolution so a world overview retains
    # fine boundaries after downsampling. No labels are baked into the sheets.
    size = image.width * 2
    mask = Image.new('L', (size, size))
    draw = ImageDraw.Draw(mask)
    for feature in boundaries:
        for part in build_basemap.rings(feature['geometry']):
            for line in part:
                lon, lat = np.asarray(line)[:, :2].T
                x, y = build_basemap.merc(lon, lat, size)
                xy = np.stack((x, y), axis=1)
                splits = np.flatnonzero(np.abs(np.diff(x)) > size / 2) + 1
                for segment in np.split(xy, splits):
                    if len(segment) >= 2:
                        draw.line([tuple(p) for p in segment], fill=145, width=2)
    result = image.copy()
    result.paste((241, 221, 186), mask=mask.resize(image.size, Image.Resampling.LANCZOS))
    return result


def blue_marble():
    with urlopen(NASA, timeout=90) as response:
        image = Image.open(io.BytesIO(response.read())).convert('RGB')
    size = 4096
    a = np.asarray(image.resize((size, size // 2), Image.Resampling.LANCZOS))
    # NASA's source is equirectangular. Sample at each Mercator output pixel centre.
    y = (np.arange(size) + .5) / size
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * y))))
    v = (90 - lat) / 180 * len(a) - .5
    row = v.astype(int)
    frac = (v - row)[:, None, None]
    pixels = np.empty((size, size, 3), dtype='uint8')
    for start in range(0, size, 64):
        sl = slice(start, start + 64)
        pixels[sl] = a[row[sl]] * (1 - frac[sl]) + a[row[sl] + 1] * frac[sl]
    image = Image.fromarray(pixels)
    build_basemap.fetch()
    boundaries = build_basemap.read('ne_10m_admin_0_boundary_lines_land')
    overview = with_boundaries(image.resize((1024, 1024), Image.Resampling.LANCZOS), boundaries)
    overview.save(OUT / 'world.jpg', quality=83, optimize=True)
    image = with_boundaries(image, boundaries)
    sheets = [dict(file='world.jpg', box=[0, 0, 1, 1], minZoom=2, maxZoom=3, credit='NASA Blue Marble')]
    for y in range(4):
        for x in range(4):
            name = f'world-{x}-{y}.jpg'
            box = (x * 1024, y * 1024, (x + 1) * 1024, (y + 1) * 1024)
            image.crop(box).save(OUT / name, quality=83, optimize=True)
            sheets.append(dict(file=name, box=[p / size for p in box], minZoom=4, maxZoom=6,
                               credit='NASA Blue Marble'))
    return sheets


def city(name, lon, lat, span, size, min_zoom, source, credit):
    """A square of EPSG:3857 from an orthorectified source, with a soft edge."""
    x = lon * ORIGIN / 180
    y = math.asinh(math.tan(math.radians(lat))) * ORIGIN / math.pi
    w, s, e, n = x - span / 2, y - span / 2, x + span / 2, y + span / 2
    transform = from_bounds(w, s, e, n, size, size)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR'), rasterio.open(source) as src:
        with WarpedVRT(src, crs='EPSG:3857', transform=transform, width=size, height=size,
                       resampling=Resampling.bilinear) as vrt:
            rgb = vrt.read([1, 2, 3]).transpose(1, 2, 0)
    valid = rgb.any(axis=2)
    if rgb.dtype == np.uint16:
        # Sentinel optical reflectance is scaled by 10,000. A fixed display
        # stretch preserves differences between tiles and lifts dark vegetation.
        rgb = (255 * np.clip(rgb / 3100, 0, 1) ** .68).astype('uint8')
    edge = np.arange(size) + .5
    edge = np.minimum(edge, size - edge)
    fade = np.minimum(1, np.minimum(edge[:, None], edge[None, :]) / (size * .055))
    rgba = Image.fromarray(np.dstack((rgb, (valid * fade * 255).astype('uint8'))))
    filename = name + '.dds'
    save_photo(rgba, OUT / filename)
    box = [(w + ORIGIN) / (2 * ORIGIN), (ORIGIN - n) / (2 * ORIGIN),
           (e + ORIGIN) / (2 * ORIGIN), (ORIGIN - s) / (2 * ORIGIN)]
    return dict(file=filename, box=box, minZoom=min_zoom, maxZoom=18, credit=credit)


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    sheets = blue_marble()
    for name, lon, lat, span, size, tile in [
        ('kyiv', 30.51, 50.45, 43000, 2048, 'N50E030'),
        ('san-francisco', -122.435, 37.765, 22000, 1024, 'N37W123'),
    ]:
        sheets.append(city(name, lon, lat, span, size, 8,
                           WORLD_COVER.format(lat=tile[:3], tile=tile), 'ESA WorldCover 2021'))
    sheets.append(city('russian-hill', -122.416, 37.793, 5200, 2048, 12, NAIP, 'USDA NAIP 2024'))
    (OUT / 'index.json').write_text(json.dumps(sheets, indent=2) + '\n', encoding='utf8')


if __name__ == '__main__':
    build()
