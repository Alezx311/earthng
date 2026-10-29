"""Real network logos for shop and fuel station signs, from Wikimedia Commons.

Each network of retail.ALIASES has its Wikidata item (also matched against OSM's brand:wikidata)
and, where Commons holds one, the logo file picked for a street sign. The logos are fetched as
PNG renderings into data/brands/<key>.png (not in Git), with data/brands/SOURCES.json recording
each file's page, licence and author; fast_art.brand_art fits them into the lightboxes. A logo is
a trademark whatever its copyright licence: these files stay in local builds unless the packs'
owner decides otherwise. A network without a file here keeps its typographic sign.

PHOTOS are parts of photographs of real stores, squared up by four corners into facade textures
(data/brands/<key>.png, generator.lua BLD.SHOP.photo): McDonald's entrance tower and the glazing
of its dining room, from a CC BY-SA photograph of its restaurant on the left bank of Kyiv.

    python earthng/brand_logos.py            # fetch the missing ones
    python earthng/brand_logos.py --force    # fetch them all again
"""
import argparse
import html
import io
import json
import re
import time
import urllib.parse
import urllib.request

from PIL import Image

import paths

UA = {'User-Agent': 'EarthNG/0.6 (https://github.com/alezx311/EarthNG; network logos for map signs)'}
API = 'https://commons.wikimedia.org/w/api.php'
OUT = paths.PROJECT / 'data' / 'brands'
WIDTH = 1024            # the rendering's width: a 512 px lightbox cell with room to trim

# key: (Wikidata item, Commons file or None[, crop: the part of the image kept, in fractions])
LOGOS = {
    'okko': ('Q2045483', None),      # Commons has the old pill and Galnaftogaz's, not the griffin
    'wog': ('Q12072939', 'WOG-logo-background-RGB.svg'),
    'ukrnafta': ('Q2447961', 'Ukrnafta.png'),
    'avias': ('Q12122687', 'Avias logo.svg'),
    'brsm': ('Q56356523', None),
    'shell': ('Q154950', 'Shell wordmark 2019.svg'),
    'socar': ('Q1622293', 'Logo of SOCAR.svg'),
    'upg': ('Q117706281', 'Logo-upg.png'),
    'k_lo': ('Q60966526', 'KLO logo.svg'),
    'motto': ('Q117706332', None),
    'atb': ('Q4054103', None),       # Commons' 'АТБ' logos are the Asia-Pacific Bank's
    'silpo': ('Q4419434', 'Silpo outline logo.svg'),
    'fora': ('Q4491805', 'Fora logo.svg'),
    'novus': ('Q116748340', 'Novus Ukraina logo.svg'),
    'auchan': ('Q4073419', 'Auchan Retail logo.svg', (0, 0, .535, 1)),   # the stores' 'Auchan' alone
    'velmart': ('Q121004370', None),
    'kolo': (None, None),
    'rukavychka': ('Q20092568', 'Rukavychka logo.png'),
    'sim23': ('Q107167415', 'Sim23-market-logo.png'),
    'simi': (None, None),
    'faino': ('Q117866213', 'Logos-faynomarket.svg'),
    'thrash': (None, 'Thrash wordmark.svg'),
    'varus': ('Q114944216', 'Varus logo 500х100.png'),
    'fozzy': ('Q12063200', 'FOZZY logo.svg'),
    'eco': ('Q12103350', 'ЕКО МАРКЕТ.svg'),
    'blyzenko': ('Q117670418', None),
    'amic': ('Q96047373', 'Amic Energy logo.svg'),
    'parallel': ('Q4344907', 'Parallel-logo.jpg'),
    'vst': (None, None),
    'bvs': ('Q117707193', None),
    'mcdonalds': ('Q38076', "McDonald's Golden Arches.svg"),
    'nova_poshta': ('Q12133863', 'Nova Poshta 2022 logo.png'),
}


def _get(params):
    url = API + '?' + urllib.parse.urlencode({**params, 'format': 'json'})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.load(r)


def _text(value):
    return html.unescape(re.sub(r'<[^>]+>', '', value or '')).strip()


def info(name):
    """The file's rendering URL and its licence fields from Commons."""
    pages = _get({'action': 'query', 'titles': 'File:' + name, 'prop': 'imageinfo',
                  'iiprop': 'url|extmetadata|mime|size', 'iiurlwidth': WIDTH})['query']['pages']
    page = next(iter(pages.values()))
    if 'imageinfo' not in page:
        raise LookupError(f'no such file on Commons: {name}')
    ii = page['imageinfo'][0]
    meta = ii.get('extmetadata', {})
    return {'file': name, 'page': ii['descriptionurl'], 'url': ii.get('thumburl') or ii['url'],
            'licence': _text(meta.get('LicenseShortName', {}).get('value')),
            'author': _text(meta.get('Artist', {}).get('value')),
            'credit': _text(meta.get('Credit', {}).get('value'))}


def fetch(key, force=False):
    _, name, *crop = LOGOS[key]
    target = OUT / f'{key}.png'
    if name is None or (target.exists() and not force):
        return None
    meta = info(name)
    with urllib.request.urlopen(urllib.request.Request(meta['url'], headers=UA), timeout=60) as r:
        image = Image.open(io.BytesIO(r.read()))
        image.load()
    image = image.convert('RGBA')
    if crop:
        x0, y0, x1, y1 = crop[0]
        image = image.crop((round(x0 * image.width), round(y0 * image.height), round(x1 * image.width), round(y1 * image.height)))
    image.save(target)
    return meta


# key: (Commons file, corners top left, top right, bottom right, bottom left in pixels of its
# PHOTO_FRAME rendering, size in px)
PHOTOS = {
    'mcdonalds_bay': ('Левый берег Киева, осень 2021 год, 15.jpg',
                      ((1050, 298), (1385, 270), (1357, 868), (1068, 872)), (512, 1024)),
    'mcdonalds_glass': ('Левый берег Киева, осень 2021 год, 15.jpg',
                        ((1507, 428), (1755, 447), (1753, 626), (1508, 618)), (512, 330)),
}
PHOTO_FRAME = (1920, 1440)      # the corners above are pixels of this rendering of the photograph


def _perspective(corners, size):
    """PIL's PERSPECTIVE coefficients taking an output of `size` from the quad `corners`."""
    import numpy as np
    w, h = size
    rows, rhs = [], []
    for (x, y), (X, Y) in zip(((0, 0), (w, 0), (w, h), (0, h)), corners):
        rows += [[x, y, 1, 0, 0, 0, -X * x, -X * y], [0, 0, 0, x, y, 1, -Y * x, -Y * y]]
        rhs += [X, Y]
    return np.linalg.solve(np.array(rows, float), np.array(rhs, float)).tolist()


def fetch_photo(key, force=False):
    name, corners, size = PHOTOS[key]
    target = OUT / f'{key}.png'
    if target.exists() and not force:
        return None
    global WIDTH
    width, WIDTH = WIDTH, PHOTO_FRAME[0]
    try:
        meta = info(name)
    finally:
        WIDTH = width
    with urllib.request.urlopen(urllib.request.Request(meta['url'], headers=UA), timeout=60) as r:
        image = Image.open(io.BytesIO(r.read())).convert('RGB')
    kx, ky = image.width / PHOTO_FRAME[0], image.height / PHOTO_FRAME[1]
    quad = [(x * kx, y * ky) for x, y in corners]
    image.transform(size, Image.PERSPECTIVE, _perspective(quad, size), Image.BICUBIC).save(target)
    return meta


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--force', action='store_true', help='fetch every logo again')
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    sources_path = OUT / 'SOURCES.json'
    sources = json.loads(sources_path.read_text(encoding='utf8')) if sources_path.exists() else {}
    for key, (item, name, *_) in LOGOS.items():
        if name is None:
            print(f'{key:12} no logo on Commons: typographic sign')
            continue
        try:
            meta = fetch(key, args.force)
        except (LookupError, OSError) as error:
            print(f'{key:12} FAILED {error}')
            continue
        if meta:
            sources[key] = {'wikidata': item, **meta}
            print(f"{key:12} {meta['file']} ({meta['licence']})")
            time.sleep(.5)              # Wikimedia's API etiquette: one request at a time, unhurried
        else:
            print(f'{key:12} kept')
    for key in PHOTOS:
        try:
            meta = fetch_photo(key, args.force)
        except (LookupError, OSError) as error:
            print(f'{key:12} FAILED {error}')
            continue
        if meta:
            sources[key] = meta
            print(f"{key:12} {meta['file']} ({meta['licence']})")
            time.sleep(.5)
    sources_path.write_text(json.dumps(sources, ensure_ascii=False, indent=1), encoding='utf8')


if __name__ == '__main__':
    main()
