"""The pictograms of the map's markers (the world map on M, the picker, the stock minimap).

  python earthng/map_icons.py                 # mod/earthng/planet/map_icons.png and e2r/map_icons.lua
  python earthng/map_icons.py --sheet out/map-icons.png

The marks of the points of interest in the world (poi_art.py, the same drawings as on a wall plaque
or an info stand) and the driver's ones the world has letters for (fuel, parking, a bed, a cup,
cash, WC ...), white on a clear ground in one small atlas the map draws as images: a marker is a
round badge of its group's colour with its mark, not a dot. The category of a point (pins.lua
STYLE, poiindex.lua SUB) names its mark in CATEGORY; a category without one keeps the letters or
the line drawing of pins.lua. Nothing paid, nothing downloaded; both files are committed.
"""
import argparse
from pathlib import Path

from PIL import Image

import poi_art
from poi_art import CLEAR

HERE = Path(__file__).resolve().parent
ATLAS = HERE.parent / 'mod/earthng/planet/map_icons.png'
LUA = HERE.parent / 'mod/lua/ge/extensions/e2r/map_icons.lua'
PER, CELL = 10, 48


def _pump(p):
    p.rect(.16, .12, .58, .86, r=.05)
    p.rect(.24, .2, .5, .42, fill=CLEAR, r=.02)
    p.rect(.1, .82, .64, .92, r=.02)
    p.line((.58, .5), (.72, .5), (.78, .58), (.78, .76), w=.07)
    p.line((.78, .6), (.86, .3), (.74, .18), w=.06)


def _bolt(p):
    p.poly((.6, .04), (.18, .56), (.45, .56), (.36, .96), (.82, .4), (.55, .4))


def _parking(p):
    p.rect(.26, .12, .78, .6, r=.22)
    p.rect(.26, .12, .46, .9, r=.02)
    p.rect(.46, .28, .6, .44, fill=CLEAR, r=.07)


def _bed(p):
    p.rect(.06, .28, .16, .84, r=.02)
    p.rect(.06, .58, .94, .72, r=.02)
    p.disc(.3, .47, .1)
    p.rect(.44, .4, .94, .6, r=.07)
    p.rect(.84, .7, .94, .84, r=.02)


def _cup(p):
    p.ring(.7, .54, .15, .07)
    p.rect(.16, .36, .68, .8, r=.1)
    p.rect(.16, .36, .68, .5)
    p.rect(.08, .84, .78, .91, r=.03)
    for x in (.32, .5):
        p.line((x, .1), (x + .05, .18), (x, .26), w=.05)


def _fork(p):
    for x in (.22, .32, .42):
        p.rect(x, .08, x + .055, .4, r=.02)
    p.rect(.22, .34, .475, .47, r=.06)
    p.rect(.31, .42, .385, .92, r=.03)
    p.poly((.62, .08), (.8, .22), (.8, .56), (.62, .56))
    p.rect(.66, .54, .745, .92, r=.03)


def _cash(p):
    p.rect(.06, .26, .94, .74, r=.06)
    p.rect(.13, .33, .87, .67, fill=CLEAR, r=.03)
    p.disc(.5, .5, .12)
    p.disc(.24, .5, .04)
    p.disc(.76, .5, .04)


def _wc(p):
    p.disc(.28, .18, .09)
    p.rect(.18, .3, .38, .62, r=.04)
    p.rect(.2, .58, .27, .92, r=.02)
    p.rect(.29, .58, .36, .92, r=.02)
    p.disc(.72, .18, .09)
    p.poly((.72, .28), (.56, .68), (.88, .68))
    p.rect(.65, .66, .7, .92, r=.02)
    p.rect(.74, .66, .79, .92, r=.02)
    p.rect(.485, .1, .515, .92)


def _wrench(p):
    p.disc(.7, .3, .2)
    p.poly((.7, .3), (.86, .02), (1., .26), fill=CLEAR)
    p.line((.62, .4), (.24, .8), w=.14)
    p.disc(.24, .8, .045, fill=CLEAR)


def _wash(p):
    for x in (.28, .5, .72):
        poi_art._drop(p, x, .24, .065)
    p.poly((.26, .58), (.36, .42), (.64, .42), (.74, .58))
    p.rect(.12, .56, .88, .78, r=.07)
    for x in (.3, .7):
        p.disc(x, .8, .09)
        p.disc(x, .8, .035, fill=CLEAR)


def _tram(p):
    p.line((.5, .24), (.5, .1), w=.05)
    p.line((.32, .09), (.68, .09), w=.05)
    p.rect(.2, .22, .8, .78, r=.09)
    p.rect(.28, .31, .72, .5, fill=CLEAR, r=.03)
    for x in (.33, .67):
        p.disc(x, .65, .045, fill=CLEAR)
    p.line((.32, .78), (.22, .93), w=.05)
    p.line((.68, .78), (.78, .93), w=.05)


def _mail(p):
    p.rect(.08, .24, .92, .78, r=.05)
    p.line((.12, .3), (.5, .58), (.88, .3), w=.055, fill=CLEAR)


def _picnic(p):
    p.rect(.14, .32, .86, .41, r=.02)
    p.rect(.03, .56, .97, .63, r=.02)
    p.line((.32, .4), (.2, .86), w=.065)
    p.line((.68, .4), (.8, .86), w=.065)


def _drop(p):
    poi_art._drop(p, .5, .6, .25)


def _dot(p):
    p.disc(.5, .5, .2)


EXTRA = {'pump': _pump, 'bolt': _bolt, 'parking': _parking, 'bed': _bed, 'cup': _cup, 'fork': _fork, 'cash': _cash,
         'wc': _wc, 'wrench': _wrench, 'wash': _wash, 'tram': _tram, 'mail': _mail, 'picnic': _picnic, 'drop': _drop,
         'dot': _dot}

# a point's category (pins.lua STYLE; 'parent/kind' of poiindex.lua SUB) -> its mark
CATEGORY = {
    'parking': 'parking', 'car_dealer': 'car', 'car_parts': 'wrench', 'rest_area': 'picnic', 'toilets': 'wc',
    'hotel': 'bed', 'motel': 'bed', 'atm': 'cash', 'payment_terminal': 'cash', 'exchange': 'cash', 'kiosk': 'bag',
    'coffee_vending': 'cup', 'water_vending': 'drop', 'drinking_water': 'drop', 'spring': 'spring', 'well': 'drop',
    'picnic': 'picnic', 'viewpoint': 'view', 'cross': 'cross', 'shrine': 'shrine', 'peak': 'peak', 'pass': 'pass',
    'tram_stop': 'tram', 'food': 'fork', 'service_map': 'wrench', 'shop_map': 'bag', 'sight': 'star',
    'leisure_map': 'tree', 'station_map': 'bus', 'mall': 'bag', 'diy': 'hammer', 'clinic': 'plus',
    'parcel_locker': 'mail', 'monument': 'monument', 'castle': 'castle', 'windmill': 'windmill', 'cave': 'cave',
    'rock': 'rock', 'waterfall': 'waterfall', 'metro': 'metro', 'station': 'train', 'airfield': 'plane',
    'ferry': 'boat', 'lighthouse': 'lighthouse', 'water_tower': 'tower', 'library': 'book', 'culture': 'museum',
    'hospital': 'hospital', 'school': 'cap',
    'service_map/fuel': 'pump', 'service_map/charging_station': 'bolt', 'service_map/car_wash': 'wash',
    'service_map/car_repair': 'wrench', 'service_map/tyres': 'wrench', 'service_map/pharmacy': 'plus',
    'service_map/bank': 'cash', 'service_map/post_office': 'mail', 'service_map/veterinary': 'paw',
    'food/cafe': 'cup', 'food/restaurant': 'fork', 'food/fast_food': 'fork', 'food/bar': 'bottle',
    'food/pub': 'bottle', 'food/ice_cream': 'cup', 'food/food_court': 'fork',
    'sight/museum': 'museum', 'sight/attraction': 'star', 'sight/artwork': 'sculpture', 'sight/gallery': 'frame',
    'sight/zoo': 'paw', 'sight/theme_park': 'wheel', 'sight/aquarium': 'fish', 'sight/information': 'info',
    'sight/ruins': 'ruins', 'sight/archaeological_site': 'dig', 'sight/building': 'manor',
    'leisure_map/park': 'tree', 'leisure_map/garden': 'flower', 'leisure_map/playground': 'toy',
    'leisure_map/stadium': 'stadium', 'leisure_map/sports_centre': 'ball', 'leisure_map/swimming_pool': 'waves',
    'leisure_map/fitness_centre': 'ball', 'leisure_map/pitch': 'ball', 'leisure_map/cinema': 'film',
    'leisure_map/theatre': 'masks', 'leisure_map/arts_centre': 'frame', 'leisure_map/nightclub': 'star',
    'station_map/bus_stop': 'bus', 'station_map/bus_station': 'bus',
    # the networks' points a streamed tile hands over without a category (pins.lua draw)
    'fuel': 'pump', 'shop': 'bag',
}


def names():
    """Every mark of the atlas in a stable order: the world's first, then the map's own."""
    world = sorted(poi_art.MARKS)
    return world + [n for n in sorted(EXTRA) if n not in poi_art.MARKS]


def mark(name, size=CELL):
    """The mark as opacity on a clear square, inside a margin of a tenth."""
    if name in poi_art.MARKS:
        return poi_art.mark(name, size)
    pen = poi_art.Pen(size * 4)
    EXTRA[name](pen)
    inner = round(size * .8)
    out = Image.new('L', (size, size), CLEAR)
    out.paste(pen.im.resize((inner, inner), Image.Resampling.LANCZOS), ((size - inner) // 2, (size - inner) // 2))
    return out


def atlas():
    """White marks, their opacity in the alpha channel."""
    all_names = names()
    rows = (len(all_names) + PER - 1) // PER
    alpha = Image.new('L', (PER * CELL, rows * CELL), 0)
    for k, name in enumerate(all_names):
        alpha.paste(mark(name), ((k % PER) * CELL, (k // PER) * CELL))
    out = Image.new('RGBA', alpha.size, (255, 255, 255, 0))
    out.putalpha(alpha)
    return out


def lua():
    all_names = names()
    rows = (len(all_names) + PER - 1) // PER
    known = set(all_names)
    missing = sorted({m for m in CATEGORY.values() if m not in known})
    if missing:
        raise ValueError(f'CATEGORY names marks the atlas has not: {missing}')
    lines = ['-- Generated by earthng/map_icons.py: the marks of the map\'s markers and the mark of each category.',
             '-- Do not edit.',
             f"return {{file = '/earthng/planet/map_icons.png', per = {PER}, rows = {rows},",
             '  -- mark -> its cell, row by row from the top left',
             '  cells = {' + ', '.join(f'{n} = {k}' for k, n in enumerate(all_names)) + '},',
             '  -- a category of pins.lua STYLE or a finer kind of poiindex.lua SUB -> its mark',
             '  category = {']
    for cat in sorted(CATEGORY):
        lines.append(f"    ['{cat}'] = '{CATEGORY[cat]}',")
    lines += ['  },', '}', '']
    return '\n'.join(lines)


def sheet(path):
    """The marks on their badges, for the eye."""
    from PIL import ImageDraw, ImageFont
    all_names = names()
    px, per = 72, 12
    out = Image.new('RGB', (per * (px + 10), ((len(all_names) + per - 1) // per) * (px + 22)), (232, 228, 216))
    d = ImageDraw.Draw(out)
    font = ImageFont.load_default()
    for k, name in enumerate(all_names):
        x, y = (k % per) * (px + 10) + 5, (k // per) * (px + 22) + 4
        d.ellipse((x, y, x + px, y + px), fill=(255, 255, 255))
        d.ellipse((x + 5, y + 5, x + px - 5, y + px - 5), fill=(40, 96, 198))
        m = mark(name, px - 22)
        out.paste((255, 255, 255), (x + 11, y + 11), m)
        d.text((x + 2, y + px + 3), name, fill=(40, 40, 40), font=font)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    out.save(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--sheet', type=Path)
    args = parser.parse_args()
    if args.sheet:
        sheet(args.sheet)
        print(f'sheet of {len(names())} marks')
    else:
        ATLAS.parent.mkdir(parents=True, exist_ok=True)
        atlas().save(ATLAS, optimize=True)
        LUA.write_text(lua(), encoding='utf8', newline='\n')
        print(f'{ATLAS.name}: {len(names())} marks; {LUA.name}')
