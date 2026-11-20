"""Rebuild the small offline image sheets shipped in mod/earthng/planet/photos.

Normal planet builds package the prepared sheets and need no imagery service.
Each sheet stores its bounds in normalized Web Mercator coordinates (northwest
origin). Regional imagery is built by build_area_photos into country/section ZIPs.
"""
import io
import json
from pathlib import Path
from urllib.request import urlopen

import numpy as np
from PIL import Image, ImageDraw
import build_basemap


OUT = Path(__file__).resolve().parents[1] / 'mod/earthng/planet/photos'
NASA = ('https://assets.science.nasa.gov/content/dam/science/esd/eo/images/bmng/'
        'bmng-topography/july/world.topo.200407.3x5400x2700.jpg')


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


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    sheets = blue_marble()
    (OUT / 'index.json').write_text(json.dumps(sheets, indent=2) + '\n', encoding='utf8')


if __name__ == '__main__':
    build()
