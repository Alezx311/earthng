"""The houses' library: walls, roofs, windows and doors of one- and two-storey houses by region.

Before it a house anywhere on the planet was a Ukrainian village house: the generator had the
region's wall, but half of those were one render sheet in other paints, and the roof's shape, the
windows and the door were the same from Kyiv to Kyoto. This library is what the houses of
houses.lua are drawn from: half-timber and Dutch brick, a Japanese siding panel and charred cedar,
white tile of a Chinese village, laterite, coral rag, mud brick, painted block, barrel tile, kawara,
palm thatch, corrugated iron, and a sheet of windows and doors for each part of the world.

    python earthng/house_art.py --generate [--only hs_koroid nd]   # paid: the sources that are missing
    python earthng/house_art.py --sheet out/house-art.jpg          # a look at the surfaces that are there
    python earthng/house_art.py --cells out/house-cells.jpg        # a look at the cut windows and doors
    python earthng/house_art.py --lua                              # rewrite house_lib.lua from what is there

The sources are paid, so made once and kept out of Git: surfaces in the texture library's own form
(data/textures/hs_<name> and hr_<name>: albedo.jpg, normal.jpg, roughness.jpg, height.jpg), the
sheets of windows in data/textures/house, every call in data/textures/house/fal_manifest.jsonl.
Surfaces come from PATINA (as own_art.py's), sheets from Nano Banana 2 (as kit_art.py's, eight
objects on magenta). A 'grey' surface is stored without its colour and painted by its kinds
(PAINTS): one sheet, several walls.

What takes them: fast_facade.HOUSE_SHEETS (sheets sh_h_*, sh_hr_*), fast_style (kinds hw_h_*,
roof_h_*, the atlases house_cells and house_cells2) and houses.lua through the generated
house_lib.lua, all only when every source is there (ready()). A checkout without them builds the
planet as before, and the generator dresses its houses as before.
"""
import argparse
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TEXTURES = ROOT / 'data' / 'textures'
SRC = TEXTURES / 'house'
LUA = ROOT / 'mod/lua/ge/extensions/e2r/house_lib.lua'
VERSION = '4'           # change whenever a source's picture or a cell's cut changes

WALL = (' Seamless tileable material texture photographed perfectly straight-on, orthographic, flat even overcast '
        'daylight, no cast shadows, no perspective, natural colours, uniform over the whole image with no large '
        'single feature, no windows, no doors, no objects, no text.')
ROOF = (' Seamless tileable material texture photographed perfectly straight down from directly above, orthographic, '
        'flat even overcast daylight, no cast shadows, no perspective, natural colours, evenly distributed over the '
        'whole image with no large single feature, no objects, no text.')
OLD = ' Weathered for some decades and never new.'
# set (data/textures/hs_<name>): (metres a repeat, 'grey' when its kinds paint it, prompt)
WALLS = {
    # --- Europe
    'timber': (3.1, '', 'Wall of a half-timbered house (German Fachwerk): a regular frame of dark brown weathered oak '
               'beams about fifteen centimetres wide, one horizontal beam running along the very top edge of the '
               'image, vertical posts about one metre apart and a diagonal brace in every second field, the fields '
               'between the beams filled with off-white lime plaster, slightly cracked and grey with rain.' + OLD),
    'brick_dutch': (2.4, '', 'Wall of a Dutch house in small dark red-brown and purple-brown hand-moulded bricks in '
                    'running bond, about thirty-two courses from top to bottom, thin crisp pale grey joints.' + OLD),
    'limestone': (2.6, '', 'Wall of a French village house in coursed cream and honey-coloured limestone rubble, '
                  'roughly squared stones of mixed sizes from fifteen to thirty centimetres, wide flush sandy lime '
                  'mortar joints, light grey lichen.' + OLD),
    'granite': (2.8, '', 'Wall of a Breton farmhouse in grey granite rubble: large roughly squared grey and '
                'rust-flecked granite blocks of mixed sizes from thirty to fifty centimetres, joints pointed in pale '
                'lime mortar, patches of white and yellow lichen.' + OLD),
    'shakes': (2.0, '', 'Wall clad in weathered hand-split wooden shingles: overlapping horizontal rows of small '
               'silver-grey and brown cedar shakes each about ten centimetres wide, about ten rows from top to bottom, '
               'slightly uneven lower edges, darker damp streaks.' + OLD),
    'plank_dark': (2.4, '', 'Wall of an alpine chalet in wide horizontal larch planks burnt dark brown by decades of '
                   'sun, each plank about twenty centimetres high, deep grain and cracks, a few knots, paler '
                   'grey-brown where the rain washes.' + OLD),
    'batten': (2.0, 'grey', 'Wall of a Scandinavian wooden house clad in vertical board-and-batten: wide vertical '
               'boards about fifteen centimetres wide with a narrow raised batten strip over every joint, covered in '
               'matt paint in plain light neutral grey, slightly chalky, a little flaking near the bottom.'),
    'whitewash': (3.0, '', 'Wall of a Greek island house: a thick uneven stone wall under many coats of bright white '
                  'limewash, soft rounded bumps and hollows where the stones lie beneath, hairline cracks, faint grey '
                  'dust in the hollows.' + OLD),
    'basalt': (2.6, '', 'Wall of black volcanic basalt stone: roughly squared dark grey-black porous blocks of mixed '
               'sizes from twenty to forty centimetres, wide joints pointed flush in white lime mortar that contrast '
               'strongly with the dark stone.' + OLD),
    'brizolit': (2.5, 'grey', 'Facade of a 1970s Central European family house in scratched mineral render: coarse '
                 'scraped cement-lime plaster with tiny glittering mica flecks and small pits, plain light neutral '
                 'grey, darker rain streaks and a little soot.' + OLD),
    'eternit': (1.6, '', 'Wall clad in small fibre cement slates laid in a diamond pattern: grey square slates set on '
                'their corners overlapping like scales, each about twenty centimetres, weathered mid grey with paler '
                'and mossy patches.' + OLD),
    'slate_hung': (1.6, '', 'Wall of a German house clad in natural slate: small dark blue-grey slates with rounded '
                   'lower edges overlapping like fish scales in neat rows, each about fifteen centimetres, a soft '
                   'sheen, a few paler weathered slates.'),
    'log_square': (2.4, '', 'Wall of an old Carpathian wooden house built of squared hewn timbers: horizontal beams '
                   'about twenty-five centimetres high with adze marks, weathered grey-brown with long cracks, tight '
                   'joints packed with moss.' + OLD),
    'koroid': (2.0, 'grey', 'Modern insulated house facade in bark beetle decorative plaster: fine-grained acrylic '
               'render with many short thin wormlike grooves all running vertically, in plain light neutral grey, '
               'clean and matt.'),
    'brick_face': (2.4, 'grey', 'Wall of a modern house in smooth machine-made facing brick: crisp regular bricks in '
                   'running bond, about thirty courses from top to bottom, neatly recessed dark joints, the bricks in '
                   'plain light neutral grey with a slight variation of tone between them.'),
    'aerated': (2.4, '', 'Unfinished wall of large autoclaved aerated concrete blocks: smooth pale grey-white blocks '
                'each about sixty centimetres long and twenty-five high in running bond, very thin grey adhesive '
                'joints with small squeezed-out blobs, a few chipped corners and dusty smears.'),
    'brick_painted': (2.4, 'grey', 'Brick wall painted over many times: the courses and joints of bricks in running '
                      'bond, about thirty courses from top to bottom, showing through a thick coat of paint in plain '
                      'light neutral grey, the paint cracked along some joints and flaking in a few small patches.'),
    'tuff': (2.4, '', 'Wall of an Armenian house in volcanic tuff: smooth sawn ashlar blocks about forty centimetres '
             'long and twenty high in regular courses, shades of dusty pink, salmon, orange and dark violet-brown '
             'mixed at random, thin dark joints.' + OLD),
    # --- unfinished and plain, the world over
    'hollow': (2.4, '', 'Unrendered wall of an unfinished house built of large orange-red hollow clay blocks, each '
               'block about thirty centimetres long and twenty high with fine horizontal grooves on its face, in '
               'running bond, rough grey cement mortar squeezed out of the joints, cement smears and dust.'),
    'frame_brick': (3.1, '', 'Unrendered wall of a house with a concrete frame and brick infill: a horizontal grey cast '
                    'concrete beam about thirty centimetres high running along the very top edge of the image, below '
                    'it rough orange-red common brick in running bond with thick grey mortar joints, cement smears '
                    'and stains running down from the beam.'),
    'cement': (3.0, '', 'Unpainted grey cement render wall of an unfinished house: floated sand-cement plaster with '
               'faint swirl marks of the float, slightly darker and lighter patches where batches met, small '
               'shrinkage cracks, dust.'),
    'brick_common': (2.4, '', 'Wall of soft hand-made orange-red common bricks of slightly different sizes and shades '
                     'laid in uneven courses, about twenty-six courses from top to bottom, very thick rough '
                     'grey-brown mortar joints, chipped corners and dust.' + OLD),
    'brick_buff': (2.4, '', 'Wall of pale yellow-buff bricks: slightly uneven bricks in shades of straw, sand and '
                   'pale ochre in running bond, about thirty courses from top to bottom, grey mortar joints, dust and '
                   'light weathering.' + OLD),
    'block_painted': (2.4, 'grey', 'Wall of concrete blocks painted over: blocks about forty centimetres long and '
                      'twenty high in running bond, their joints and porous faces showing through thick paint in '
                      'plain light neutral grey, the paint a little faded and scuffed, a few small chips.'),
    'render_stained': (3.0, 'grey', 'Old painted cement render wall of a house in a humid tropical town: plain light '
                       'neutral grey paint, uneven patches of repair in slightly different tones, peeling flakes, '
                       'dark grey damp and algae stains gathering in vertical streaks, hairline cracks.'),
    'tinpatch': (2.4, '', 'Wall of a shack made of old corrugated iron sheets of different ages nailed side by side: '
                 'vertical corrugations, some sheets dull galvanised grey, some rusted orange-brown, one with the '
                 'remains of blue paint, overlaps with nail heads, dents.'),
    # --- North America, Oceania
    'stucco_lace': (3.0, 'grey', 'Exterior wall of an American suburban house in lace-texture stucco: a skip-trowelled '
                    'pattern of flat smooth islands over a rougher sandy ground, painted plain light neutral grey, '
                    'clean, with a few hairline cracks.'),
    'brick_ranch': (2.4, '', 'Wall of an American 1960s ranch house in mixed tumbled brick: red, orange, buff and a '
                    'few dark brown bricks at random in running bond, about thirty courses from top to bottom, pale '
                    'grey mortar joints slightly recessed, a few white mortar smears.'),
    'veneer': (2.4, '', 'Wall faced in stacked ledgestone veneer of an American house: long thin split-face stones in '
               'tan, grey and rust browns, dry-stacked tightly in horizontal rows from two to ten centimetres high '
               'with no visible mortar.'),
    'shingle_siding': (1.8, 'grey', 'Wall of an older American house clad in asbestos cement siding shingles: flat '
                       'rectangular panels about sixty centimetres wide and thirty high with a fine vertical '
                       'striated texture and a wavy lower edge, in overlapping rows with staggered joints, painted '
                       'plain light neutral grey, slightly chalky.'),
    'fibro': (2.4, 'grey', 'Wall of a 1950s Australian fibro house: flat fibre cement sheets painted plain light '
              'neutral grey, joined by narrow vertical timber cover battens about one metre twenty apart with small '
              'nail heads, the paint slightly chalky with fine dirt streaks.'),
    # --- East Asia
    'jp_siding': (2.4, 'grey', 'Exterior wall of a modern Japanese house in ceramic siding panels embossed as small '
                  'split-face stone tiles: a regular pattern of narrow horizontal rectangles about twenty centimetres '
                  'long and five high with fine shadow gaps, plain light neutral grey, clean.'),
    'yakisugi': (2.0, '', 'Wall of a traditional Japanese house clad in charred cedar boards: vertical boards about '
                 'fifteen centimetres wide, deep black-brown with a silvery cracked alligator-skin char and raised '
                 'grain, narrow battens over the joints.'),
    'tile_white': (1.6, '', 'Facade of a rural Chinese house covered in small white glazed rectangular ceramic tiles, '
                   'each tile about twenty centimetres long and six high laid in a brick bond with thin grey grout, '
                   'glossy, with grey dirt streaks running down and a few cracked tiles.'),
    'tile_strip': (1.6, 'grey', 'Facade covered in narrow vertical ceramic strip tiles of a 1990s East Asian house, '
                   'each tile about five centimetres wide and twenty high in a strict grid with thin dark grout, '
                   'satin glaze in plain light neutral grey with a slight variation between tiles, faint dirt '
                   'streaks.'),
    'cn_grey': (2.2, '', 'Wall of a northern Chinese courtyard house in blue-grey fired bricks: smooth dense grey '
                'bricks in running bond, about thirty courses from top to bottom, fine white lime joints, slight '
                'weathering and pale efflorescence.' + OLD),
    'rammed': (3.0, '', 'Rammed earth wall of a farmhouse: compacted yellow-ochre earth in horizontal layers about ten '
               'centimetres thick with faint lines between the lifts, small pebbles and straw showing, erosion pits '
               'and fine vertical cracks.' + OLD),
    # --- South and Southeast Asia
    'laterite': (2.4, '', 'Wall of dressed laterite stone blocks of Kerala: large red-brown and ochre porous pitted '
                 'blocks each about forty centimetres long and twenty-five high in regular courses, thin grey mortar '
                 'joints, darker damp patches and a little green moss in the pits.' + OLD),
    'schist': (2.4, '', 'Dry stone wall of a mountain house built of thin flat slabs of grey-brown schist and slate '
               'laid horizontally and tightly packed without mortar, slabs from two to eight centimetres thick, a few '
               'larger blocks, rusty and silvery tones, lichen.' + OLD),
    'teak': (2.0, '', 'Wall of a Thai wooden house in vertical tropical hardwood planks about fifteen centimetres '
             'wide, dark red-brown teak weathered grey at the edges, narrow dark gaps between the planks, old oil '
             'stain, a few nail heads.' + OLD),
    'bamboo': (2.0, '', 'Wall of woven split bamboo matting: flat strips of bamboo about three centimetres wide woven '
               'in a tight diagonal herringbone twill, pale straw and tan with darker aged strips, dusty.'),
    # --- the Middle East, Africa
    'jerusalem': (2.4, '', 'Wall of a Levantine house in Jerusalem stone: pale cream-gold limestone ashlar blocks '
                  'about forty centimetres long and twenty-five high in regular courses, each face roughly chiselled '
                  'with a smooth tooled margin, thin joints, slight grey weathering.'),
    # (the first prompt's "large patches fallen away" and "mould streaks" made one dark band across
    # the sheet, a stripe a storey on a wall)
    'coral': (2.8, '', 'Old wall of a house on the Swahili coast built of coral rag stone: small rough porous '
              'grey-brown and cream coral stones of mixed sizes set in thick off-white lime mortar, the stones '
              'showing evenly everywhere through a thin worn coat of limewash, small dark mould specks scattered '
              'evenly, hairline cracks.' + OLD),
    'earth_plaster': (3.0, 'grey', 'Wall of an adobe house finished in hand-smoothed mud plaster with chopped straw: a '
                      'soft uneven surface with palm strokes, fine cracks, bits of straw and small pebbles, slightly '
                      'eroded by rain in vertical runnels, plain pale grey-beige.' + OLD),
    'mudbrick': (2.2, '', 'Wall of sun-dried mud bricks: large tan-brown adobe bricks with straw in them, each about '
                 'thirty-five centimetres long and twelve high in rough courses, thick mud mortar joints eroded back '
                 'by the rain, cracks and rounded worn corners.' + OLD),
}
# set (data/textures/hr_<name>): (metres a repeat, 'grey', prompt); v runs down the slope
ROOFS = {
    'mission': (2.0, '', 'Close view of a roof of Spanish clay barrel tiles seen from directly above: rows of '
                'half-round terracotta tiles running straight from the top edge of the image to the bottom edge, '
                'about ten rows across, each row of convex cover tiles with a deep shaded channel beside it, the '
                'overlapping tile ends making horizontal steps, mixed sun-bleached orange, pink-buff and brown with '
                'pale lichen.'),
    'kawara': (2.0, 'grey', 'Close view of a Japanese kawara tile roof seen from directly above: glazed clay pantiles '
               'with an S-shaped wave profile in straight columns running from the top edge to the bottom edge, about '
               'nine columns across, the overlapping tile ends making neat horizontal rows about thirty centimetres '
               'apart, smooth satin glaze in plain neutral grey.'),
    'wood_shingle': (2.4, '', 'Roof of old wooden shingles seen from directly above: overlapping horizontal rows of '
                     'narrow split wooden shingles about ten centimetres wide, about twelve rows from top to bottom, '
                     'weathered silver-grey with dark damp lower edges and patches of green moss.'),
    'stone': (3.0, '', 'Roof of heavy stone slabs of an alpine mountain house seen from directly above: thick '
              'irregular grey gneiss and slate slabs of mixed sizes overlapping in rough horizontal rows, rusty and '
              'silver-grey, with moss and lichen along the laps.'),
    'seam': (2.0, 'grey', 'Standing seam sheet metal roof seen from directly above: flat painted steel pans about '
             'forty centimetres wide separated by thin raised seams running straight from the top edge to the bottom '
             'edge, matt paint in plain neutral grey, slightly chalky with faint streaks.'),
    # (drawn with its waves across the image whatever the prompt says: TURN lays them down the slope)
    'corr': (1.6, 'grey', 'Corrugated iron roof seen from directly above: fine regular rounded sine-wave corrugations '
             'about eight centimetres apart running straight from the top edge to the bottom edge, every wave shaded '
             'with a pale crest and a dark valley, two horizontal rows of overlapping sheet ends with small roofing '
             'screws, painted plain neutral grey, slightly faded.'),
    'palm': (2.4, '', 'Roof thatched with dried palm leaves seen from directly above: overlapping horizontal rows of '
             'grey-brown and straw-coloured palm frond mats, each row about twenty centimetres, the ragged leaf tips '
             'pointing to the bottom edge, weathered and sun-bleached.'),
    'reed': (2.4, '', 'Roof thatched with water reed seen from directly above: dense reed stalks all pointing straight '
             'down the slope from the top edge to the bottom edge, their cut ends in soft horizontal steps, '
             'grey-brown and golden, with dark weathered patches and a little green moss.'),
    'flat': (4.0, 'grey', 'Flat concrete roof of a house in a hot dry country seen from directly above: cement screed '
             'in plain neutral grey with fine shrinkage cracks, patched areas, faint dry puddle rings and wind-blown '
             'dust.'),
    'flat_mud': (4.0, '', 'Flat mud roof of an adobe house seen from directly above: smoothed clay and straw plaster in '
                 'pale tan-brown, a fine net of drying cracks, bits of straw, a few darker repaired patches and '
                 'shallow rain runnels.'),
    'fibre': (1.6, 'grey', 'Roof of fibre cement slates laid in a diamond pattern seen from directly above: square '
              'slates set on their corners overlapping like scales, each about thirty centimetres, plain neutral '
              'grey with slightly darker lower edges and a little lichen.'),
    'beaver': (1.6, '', 'Roof of plain clay beaver-tail tiles seen from directly above: small flat tiles with rounded '
               'lower ends in overlapping horizontal rows with staggered joints, about fourteen rows from top to '
               'bottom, red-brown and orange with darker weathered tiles and a little moss.'),
}
TURN = ('corr',)
# The linear mean a grey sheet of the library is levelled to (fast_facade.sheet). The older grey
# sheets stand at .6, and a paint lighter than sRGB 203 is cut off there channel by channel: a
# peach wall came out beige-grey. At .85 a paint keeps its hue up to 236.
GREY = .85
# How a set's maps are brought to the game's light before they become a sheet (toned()). PATINA's
# colour is delit and bright: a slate came out sky blue, a Chinese grey brick blue, a common brick
# orange; a fine render has all its grain in the height map and reads as flat paint.
#   sat, gain: the colour's saturation and level;   contrast: its departure from its own mean
#   cavity: pits and joints darker by the height map (1 = the kit's walls);   bump: the normal's strength
#   grooves: the short vertical worm tracks of bark beetle plaster, drawn (the model drew none)
CAVITY = 1.2
TONE = {
    'hs_slate_hung': {'sat': .3}, 'hs_cn_grey': {'sat': .3}, 'hs_brick_common': {'sat': .78},
    'hs_rammed': {'sat': .7}, 'hs_laterite': {'sat': .8}, 'hs_tuff': {'sat': .8}, 'hs_mudbrick': {'sat': .8},
    'hs_hollow': {'sat': .85}, 'hs_jerusalem': {'sat': .8}, 'hs_bamboo': {'sat': .85}, 'hr_flat_mud': {'sat': .6},
    'hr_beaver': {'sat': .85}, 'hs_brick_dutch': {'sat': .6},
    'hs_koroid': {'grooves': True, 'bump': 2.}, 'hs_render_stained': {'contrast': 3., 'cavity': 1.5},
    'hs_cement': {'contrast': 2.2, 'cavity': 1.5}, 'hs_brizolit': {'contrast': 2., 'cavity': 2.5, 'bump': 2.5},
    'hs_stucco_lace': {'cavity': 2.5, 'bump': 2.5}, 'hs_earth_plaster': {'contrast': 2.5, 'cavity': 2., 'bump': 2.},
    'hs_brick_face': {'contrast': 1.6}, 'hs_brick_painted': {'contrast': 1.8, 'cavity': 1.5},
    'hs_block_painted': {'contrast': 1.5, 'cavity': 1.5}, 'hs_jp_siding': {'contrast': 1.4}, 'hs_whitewash': {'cavity': 1.5},
    'hs_tile_white': {'contrast': 1.3}, 'hr_flat': {'contrast': 2.5, 'cavity': 1.5},
}
# The level of an own-coloured sheet: the sRGB grey its mean is brought to. PATINA's colour has no
# light in it and stands a third brighter than the thing: in the game's sun a barrel tile roof was
# pale peach, a Dutch brick pink, a wooden shingle white (houses-01, 22.11).
LUMA = {
    'hs_timber': 172, 'hs_brick_dutch': 92, 'hs_limestone': 184, 'hs_granite': 140, 'hs_shakes': 132, 'hs_plank_dark': 60,
    'hs_whitewash': 224, 'hs_basalt': 62, 'hs_eternit': 124, 'hs_slate_hung': 64, 'hs_log_square': 90, 'hs_aerated': 204,
    'hs_tuff': 138, 'hs_hollow': 134, 'hs_frame_brick': 134, 'hs_cement': 150, 'hs_brick_common': 118, 'hs_brick_buff': 174,
    'hs_tinpatch': 124, 'hs_brick_ranch': 112, 'hs_veneer': 134, 'hs_yakisugi': 42, 'hs_tile_white': 214, 'hs_cn_grey': 118,
    'hs_rammed': 158, 'hs_laterite': 104, 'hs_schist': 108, 'hs_teak': 86, 'hs_bamboo': 168, 'hs_jerusalem': 198,
    'hs_coral': 174, 'hs_mudbrick': 140,
    'hr_mission': 104, 'hr_wood_shingle': 112, 'hr_stone': 108, 'hr_palm': 118, 'hr_reed': 108, 'hr_flat_mud': 138, 'hr_beaver': 90,
}


def _linear(a):
    return np.where(a <= .04045, a / 12.92, ((a + .055) / 1.055) ** 2.4)


def _encode(a):
    a = np.clip(a, 0, 1)
    return np.where(a <= .0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - .055)


def _blur(a, radius):
    from PIL import ImageFilter
    im = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(im, dtype=np.float32) / 255


def _grooves(size, seed=2611):
    """0..1: short vertical tracks of bark beetle plaster, a few millimetres wide and two to six
    centimetres long over a 2 m sheet, wrapped at the edges."""
    rng = np.random.default_rng(seed)
    g = np.zeros((size, size), np.float32)
    n = size * size // 300
    xs, ys, ls = rng.integers(0, size, n), rng.integers(0, size, n), rng.integers(size // 100, size // 32, n)
    for x, y, l in zip(xs, ys, ls):
        rows = np.arange(y, y + l) % size
        g[rows, x] = 1
        g[rows, (x + 1) % size] = np.maximum(g[rows, (x + 1) % size], .6)
    return np.clip(_blur(g, .7) * 1.6, 0, 1)


def toned(folder, colour, normal):
    """A set's colour and normal map (PIL, as read) by TONE, before fast_facade.sheet turns,
    greys and flips them."""
    t = TONE.get(folder, {})
    a = np.asarray(colour, np.float32) / 255
    n = np.asarray(normal, np.float32) / 127.5 - 1
    size, nsize = a.shape[0], n.shape[0]
    height = TEXTURES / folder / 'height.jpg'
    h = (np.asarray(Image.open(height).convert('L').resize((size, size), Image.LANCZOS), np.float32) / 255
         if height.exists() else None)
    if h is not None:
        a = a * np.clip(1 + (h - _blur(h, 6)) * 1.6 * t.get('cavity', CAVITY), .62, 1.1)[..., None]
    if t.get('grooves'):
        g = _grooves(size)
        a = a * (1 - .2 * g)[..., None]
        # a groove is a pit: the normal leans as the set's own does over its own height
        small = np.asarray(Image.fromarray((g * 255).astype(np.uint8)).resize((nsize, nsize), Image.BILINEAR), np.float32) / 255
        gy, gx = np.gradient(-small)
        sx = sy = 1.
        if h is not None:
            hs = np.asarray(Image.fromarray((h * 255).astype(np.uint8)).resize((nsize, nsize), Image.BILINEAR), np.float32) / 255
            hy, hx = np.gradient(hs)
            sx = 1. if float((n[..., 0] * hx).sum()) >= 0 else -1.
            sy = 1. if float((n[..., 1] * hy).sum()) >= 0 else -1.
        n[..., 0] += sx * gx * 5
        n[..., 1] += sy * gy * 5
    if 'contrast' in t:
        mean = a.mean(axis=(0, 1), keepdims=True)
        a = mean + (a - mean) * t['contrast']
    if 'sat' in t:
        grey = a.mean(axis=2, keepdims=True)
        a = grey + (a - grey) * t['sat']
    a = a * t.get('gain', 1.)
    if folder in LUMA:
        lin = _linear(np.clip(a, 0, 1))
        now = float((lin @ np.array([.2126, .7152, .0722], np.float32)).mean())
        a = _encode(lin * (float(_linear(np.float64(LUMA[folder] / 255))) / max(now, 1e-4)))
    if 'bump' in t:
        n[..., :2] *= t['bump']
    n = n / np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-4)
    return (Image.fromarray((np.clip(a, 0, 1) * 255 + .5).astype(np.uint8)),
            Image.fromarray(((n * .5 + .5) * 255 + .5).astype(np.uint8)))


# The paints of the grey sets: kind suffix -> sRGB. Walls become hw_h_<stem>_<paint>, roofs
# roof_h_<stem>_<paint>; a set that is not grey is one kind, hw_h_<name> or roof_h_<name>.
STEMS = {'block_painted': 'blockp', 'render_stained': 'stain', 'stucco_lace': 'lace', 'shingle_siding': 'asb',
         'jp_siding': 'jps', 'tile_strip': 'strip', 'earth_plaster': 'earth', 'brick_face': 'face',
         'brick_painted': 'painted'}
PAINTS = {
    'batten': {'red': (130, 50, 40), 'yellow': (214, 176, 96), 'white': (232, 230, 222), 'black': (46, 46, 48),
               'blue': (98, 124, 150), 'green': (92, 116, 96), 'grey': (150, 152, 150), 'brown': (88, 62, 50)},
    'brizolit': {'grey': (150, 146, 138), 'ochre': (172, 152, 114), 'green': (140, 148, 128)},
    'koroid': {'peach': (232, 190, 150), 'yellow': (232, 210, 140), 'green': (178, 206, 160), 'beige': (222, 206, 178),
               'white': (236, 234, 226), 'grey': (176, 176, 172), 'terracotta': (198, 120, 90)},
    'brick_face': {'yellow': (214, 186, 122), 'peach': (214, 160, 120), 'brown': (120, 78, 60), 'red': (156, 72, 56),
                   'white': (226, 222, 210)},
    'brick_painted': {'white': (232, 230, 224), 'cream': (226, 214, 186), 'grey': (150, 152, 152), 'black': (50, 50, 52),
                      'pink': (224, 184, 176)},
    'block_painted': {'turq': (64, 170, 170), 'yellow': (234, 196, 80), 'pink': (228, 130, 140), 'lime': (150, 196, 96),
                      'orange': (230, 140, 70), 'blue': (70, 120, 190), 'white': (232, 230, 222), 'peach': (236, 180, 140)},
    'render_stained': {'pink': (214, 150, 140), 'blue': (110, 150, 200), 'yellow': (226, 190, 96), 'green': (136, 180, 140),
                       'cream': (226, 212, 176), 'white': (228, 226, 216), 'ochre': (204, 150, 84),
                       'terracotta': (190, 104, 76), 'lilac': (170, 150, 190)},
    'stucco_lace': {'tan': (196, 170, 134), 'beige': (214, 198, 170), 'grey': (170, 170, 164), 'peach': (220, 178, 146),
                    'sage': (160, 172, 146), 'white': (232, 228, 218)},
    'shingle_siding': {'white': (226, 226, 218), 'mint': (170, 200, 178), 'pink': (222, 184, 176), 'blue': (160, 188, 206),
                       'yellow': (226, 208, 150)},
    'fibro': {'green': (170, 196, 170), 'cream': (226, 214, 180), 'blue': (160, 190, 208), 'white': (230, 230, 222)},
    'jp_siding': {'beige': (206, 192, 166), 'cream': (226, 216, 192), 'grey': (160, 160, 156), 'brown': (120, 92, 74),
                  'white': (232, 230, 224), 'blue': (150, 168, 180)},
    'tile_strip': {'pink': (214, 170, 160), 'ochre': (196, 160, 100), 'mint': (160, 196, 176), 'brown': (130, 84, 64)},
    'earth_plaster': {'tan': (176, 142, 104), 'red': (160, 92, 62), 'pink': (198, 146, 118), 'sand': (206, 184, 144),
                      'umber': (124, 98, 76)},
}
ROOF_PAINTS = {
    'kawara': {'silver': (124, 128, 132), 'black': (50, 52, 56), 'blue': (52, 78, 120), 'brown': (98, 54, 42),
               'green': (60, 104, 84), 'orange': (190, 104, 60)},
    'seam': {'red': (128, 44, 38), 'green': (52, 92, 70), 'grey': (120, 124, 126), 'black': (44, 46, 50),
             'blue': (56, 84, 124), 'brown': (84, 58, 48)},
    'corr': {'red': (132, 48, 40), 'green': (58, 100, 72), 'blue': (66, 100, 150), 'silver': (168, 172, 174),
             'cream': (212, 204, 176)},
    'flat': {'grey': (150, 148, 142), 'white': (226, 224, 216), 'tan': (186, 166, 136)},
    'fibre': {'grey': (120, 120, 118), 'red': (132, 70, 58)},
}
# More paints of sheets the planet already had (fast_facade.SHEETS), and sheets cut again from
# their sources: kind -> (sheet, sRGB, metres a repeat). The sod roof is the library's own meadow.
EXTRA_WALLS = {
    'hw_h_clap_turq': ('sh_clapboard', (72, 170, 168), 1.2), 'hw_h_clap_pink': ('sh_clapboard', (230, 150, 160), 1.2),
    'hw_h_clap_green': ('sh_clapboard', (130, 170, 120), 1.2), 'hw_h_clap_grey': ('sh_clapboard', (150, 156, 160), 1.2),
    'hw_h_clap_red': ('sh_clapboard', (150, 56, 48), 1.2), 'hw_h_clap_black': ('sh_clapboard', (52, 52, 54), 1.2),
    'hw_h_vinyl_blue': ('sh_vinyl', (140, 160, 180), 2.0), 'hw_h_vinyl_sage': ('sh_vinyl', (160, 172, 150), 2.0),
    'hw_h_vinyl_tan': ('sh_vinyl', (196, 176, 146), 2.0),
    'hw_h_prof_blue': ('sh_profile', (70, 110, 160), 2.0), 'hw_h_prof_green': ('sh_profile', (60, 110, 80), 2.0),
    'hw_h_prof_red': ('sh_profile', (140, 50, 44), 2.0), 'hw_h_prof_white': ('sh_profile', (226, 226, 218), 2.0),
    'hw_h_prof_grey': ('sh_profile', (140, 144, 144), 2.0),
}
EXTRA_SHEETS = {'sh_hr_shingle': ('mat_roof_shingle', 'roof grey'), 'sh_hr_turf': ('own_meadow', 'roof')}
EXTRA_ROOFS = {
    'roof_h_shingle_brown': ('sh_hr_shingle', (96, 72, 58), 8.0, True), 'roof_h_shingle_black': ('sh_hr_shingle', (54, 54, 58), 8.0, True),
    'roof_h_shingle_red': ('sh_hr_shingle', (120, 62, 52), 8.0, True), 'roof_h_shingle_green': ('sh_hr_shingle', (78, 96, 80), 8.0, True),
    'roof_h_turf': ('sh_hr_turf', (90, 96, 60), 4.0, False),
}

# Sheets of windows and doors (Nano Banana 2): four in a row, two rows, on magenta.
# name: (columns or a tuple of them a row, rows, prompt, cells in reading order as (cell, width m, height m))
SHEET_STYLE = (' Each one isolated on a plain solid magenta #FF00FF background with clear magenta gaps between them. '
               'Orthographic perfectly frontal view, no perspective, flat overcast light, photorealistic, a little '
               'weathered. Only the objects themselves, each complete with its frame, closed: no walls around them, '
               'no ground, no text, no letters, no numbers, no labels.')
_HEAD = 'Texture atlas sprite sheet: a strict grid of 4 columns and 2 rows showing 8 different windows and doors of '
SHEETS = {
    'ua': (4, 2, _HEAD + 'village houses in Ukraine. Row 1: a small house window with a white wooden frame of six panes '
           'inside wide carved wooden casing boards painted bright blue; a similar window with carved casings painted '
           'green and white and a lace curtain; a wooden window with a plain brown painted frame and casing; a white '
           'PVC window with one mullion set in old blue-painted wooden casings. Row 2: a brown wood-effect laminated '
           'PVC window with a roller blind; a glazed veranda window of many small square panes in a white-painted '
           'wooden frame; an old village house door of vertical planks painted blue-green with a small glazed panel; '
           'a modern brown steel entrance door with a pressed panel pattern.',
           [('ua_blue', 1.1, 1.4), ('ua_green', 1.1, 1.4), ('ua_brown', 1.0, 1.3), ('ua_pvc_blue', 1.1, 1.4),
            ('ua_lam', 1.3, 1.4), ('ua_veranda', 1.6, 1.4), ('ua_door_plank', .9, 2.0), ('ua_door_steel', .95, 2.05)]),
    'mo': (4, 2, _HEAD + 'newly built family houses. Row 1: a modern window with an anthracite grey frame in three '
           'sections; a large floor-to-ceiling fixed glazing with a thin black frame; a white PVC window with an '
           'arched top; a window with a golden-oak wood-effect PVC frame and a mosquito net. Row 2: a wide panoramic '
           'window with a dark frame and a sheer curtain; a white PVC window with a white exterior roller shutter '
           'lowered halfway; a modern anthracite front door with a long steel handle and a glass side panel; a dark '
           'brown steel front door with an oval forged iron and glass insert.',
           [('mo_anthr3', 1.8, 1.4), ('mo_full', 1.6, 2.2), ('mo_arch', 1.2, 1.6), ('mo_oak', 1.3, 1.4),
            ('mo_pano', 2.4, 1.5), ('mo_roller', 1.3, 1.4), ('mo_door_anthr', 1.4, 2.1), ('mo_door_forged', .95, 2.05)]),
    'nd': (4, 2, _HEAD + 'wooden houses in Sweden, Norway and Finland. Row 1: a Swedish window with a white frame, '
           'two casements of three panes each and wide flat white casing boards; a Norwegian window with one cross '
           'mullion and a dark green frame; a Finnish three-part window with white frames and a narrow ventilation '
           'casement; a modern Scandinavian window, one large undivided pane in a black frame. Row 2: a small square '
           'white window divided in four panes; an old Danish window with white glazing bars in a dark brown tarred '
           'frame; a panelled Swedish front door painted dark green with a small glazed top light and white casing; '
           'a modern Scandinavian front door in grey-blue with a narrow vertical glass strip.',
           [('nd_white6', 1.2, 1.3), ('nd_green', 1.1, 1.3), ('nd_three', 1.6, 1.3), ('nd_black', 1.4, 1.4),
            ('nd_small', .8, .8), ('nd_brown', 1.1, 1.2), ('nd_door_green', 1.0, 2.1), ('nd_door_blue', 1.0, 2.1)]),
    'al': (4, 2, _HEAD + 'houses in Bavaria, Austria, Poland and the Czech Republic. Row 1: a Bavarian farmhouse '
           'window with a white frame, open green wooden shutters on both sides and a flower box of red geraniums; '
           'an Austrian window with a brown stained wooden frame and open brown shutters; a small deep-set window '
           'with a stone surround and an iron grille; a white PVC window with a grey exterior roller shutter half '
           'down. Row 2: a wide twin window with brown wooden frames and a net curtain of a 1970s Polish family '
           'house; a tall old town window with a cream frame and an inner double casement; a carved rustic wooden '
           'front door stained dark brown with iron fittings; a 1970s front door of ribbed amber glass in a brown '
           'aluminium frame.',
           [('al_shut_green', 1.9, 1.5), ('al_shut_brown', 1.9, 1.4), ('al_grille', .8, .9), ('al_roller', 1.3, 1.4),
            ('al_twin', 1.8, 1.4), ('al_old', 1.1, 1.7), ('al_door_carved', 1.0, 2.1), ('al_door_glass', 1.0, 2.1)]),
    'uk': (4, 2, _HEAD + 'houses in England and Scotland. Row 1: a white uPVC casement window with two small '
           'top-hung fanlight openers above its panes; a white painted Victorian sash window, two panes over two; a '
           'Georgian sash window of six panes over six with a cream frame; a small cottage casement window with '
           'diamond leaded lights in a dark wooden frame. Row 2: a wide white uPVC window of three sections with '
           'leaded top lights and a net curtain; a small bathroom window with frosted glass and a top opener; a '
           'British terraced house front door painted glossy red with a brass letterbox, a knocker and a small '
           'rectangular fanlight above; a modern dark blue composite front door with a small arched glazed panel '
           'and a letterbox.',
           [('uk_fanlight', 1.2, 1.2), ('uk_sash22', 1.0, 1.7), ('uk_sash66', 1.0, 1.7), ('uk_cottage', 1.0, 1.1),
            ('uk_wide', 1.8, 1.3), ('uk_bath', .6, .9), ('uk_door_red', 1.0, 2.3), ('uk_door_blue', .95, 2.1),
            ('uk_door_navy', .95, 2.1)]),
    'us': (4, 2, _HEAD + 'suburban houses in the United States. Row 1: an American double-hung window with white trim '
           'and black louvred shutters on both sides; a wide picture window with two narrow side sashes in a white '
           'vinyl frame; an aluminium horizontal sliding window with an insect screen; a Craftsman bungalow window '
           'with a divided top sash and thick white casing. Row 2: a pair of double-hung windows side by side with '
           'dark green shutters; a small high bathroom window with frosted glass; an American front door painted red '
           'with six panels, a brass kick plate and white trim; a Craftsman front door in stained oak with three '
           'small glass panes at the top.',
           [('us_shut_black', 1.9, 1.6), ('us_picture', 2.4, 1.5), ('us_slider', 1.5, 1.1), ('us_craftsman', 1.1, 1.6),
            ('us_pair', 2.4, 1.5), ('us_small', .8, .6), ('us_door_red', 1.1, 2.1), ('us_door_craft', 1.0, 2.1)]),
    'la': (4, 2, _HEAD + 'houses in Mexico, Colombia and Brazil. Row 1: a window of a Mexican town house behind a '
           'projecting black wrought iron grille; a window with closed bright blue wooden shutters; a glass louvre '
           'jalousie window in an aluminium frame; a small square steel-framed window with frosted glass behind a '
           'simple grid of iron bars painted white. Row 2: a tall colonial window with turned wooden bars and inner '
           'shutters painted dark green; a modern aluminium sliding window with tinted glass behind decorative iron '
           'bars; a steel sheet front door painted turquoise with a small barred window; an old colonial double door '
           'of heavy studded wood painted ochre-brown.',
           [('la_reja', 1.2, 1.6), ('la_blue', 1.0, 1.4), ('la_louvre', 1.0, 1.2), ('la_bars', .9, .9),
            ('la_colonial', 1.2, 2.0), ('la_slide', 1.5, 1.2), ('la_door_steel', .95, 2.1), ('la_door_double', 1.5, 2.4)]),
    'jp': (4, 2, _HEAD + 'houses in Japan. Row 1: an aluminium sliding window with frosted glass in a bronze-coloured '
           'frame; a wide two-panel sliding window with a silver aluminium frame and a metal storm shutter box at one '
           'side; a traditional window covered by a fine vertical wooden lattice; a small low horizontal slit window '
           'with aluminium louvres. Row 2: a modern Japanese house window with a white frame and a low aluminium '
           'railing in front of it; a tall narrow fixed window with a dark frame; a modern Japanese entrance door, '
           'dark brown with a vertical slit of frosted glass and a long handle; a traditional sliding entrance door '
           'of wooden lattice and frosted glass.',
           [('jp_frost', 1.6, 1.1), ('jp_wide', 1.8, 1.2), ('jp_koshi', 1.5, 1.2), ('jp_slit', 1.2, .5),
            ('jp_rail', 1.6, 1.3), ('jp_narrow', .5, 1.5), ('jp_door_modern', 1.0, 2.2), ('jp_door_genkan', 1.7, 2.1)]),
    'cn': (4, 2, _HEAD + 'village houses in China, Korea and Vietnam. Row 1: an aluminium sliding window with blue '
           'tinted glass behind a stainless steel security grille; a wide window with a white aluminium frame and '
           'green tinted glass; an old wooden window painted dark red with a geometric lattice; a window enclosed in '
           'a projecting stainless steel cage. Row 2: a Korean house window with a white PVC frame and an outer '
           'insect screen; a Vietnamese window with louvred wooden shutters painted pale green; a rural Chinese '
           'double front door painted red with brass ring handles; a stainless steel security double door with a '
           'pressed pattern.',
           [('cn_blue', 1.5, 1.3), ('cn_green', 1.8, 1.4), ('cn_lattice', 1.2, 1.3), ('cn_cage', 1.5, 1.4),
            ('cn_korea', 1.5, 1.2), ('cn_viet', 1.1, 1.5), ('cn_door_red', 1.6, 2.3), ('cn_door_steel', 1.5, 2.2)]),
    'sa': (4, 2, _HEAD + 'houses in India, Pakistan and Bangladesh. Row 1: a window with a welded iron grille of a '
           'simple geometric pattern painted sky blue and wooden shutters behind it; a window with closed wooden '
           'shutters painted green; a perforated concrete jali screen panel painted white; an aluminium sliding '
           'window with reflective tinted glass behind a steel grille. Row 2: a small arched window with a painted '
           'plaster surround and iron bars; a wooden window with coloured glass top lights; a carved wooden double '
           'door varnished dark brown with brass studs; a painted steel sheet door in bright blue with a pressed '
           'diamond pattern.',
           [('sa_grille', 1.1, 1.3), ('sa_shut', 1.0, 1.3), ('sa_jali', 1.0, 1.0), ('sa_slide', 1.4, 1.2),
            ('sa_arch', .8, 1.2), ('sa_colour', 1.1, 1.4), ('sa_door_carved', 1.3, 2.1), ('sa_door_steel', .95, 2.05)]),
    'se': (4, 2, _HEAD + 'houses in Thailand, Indonesia and the Philippines. Row 1: a window of rows of glass louvre '
           'blades in a wooden frame; a window with open wooden plank shutters painted turquoise; a wooden window '
           'with a carved fretwork ventilation panel above it, stained dark brown; an aluminium sliding window with '
           'a mosquito screen and a simple steel grille. Row 2: a wide window with folding wooden louvred shutters '
           'painted pale yellow; a small window with wooden bars only and no glass; a double wooden door with '
           'louvred upper panels painted green; a folding accordion steel gate across a doorway.',
           [('se_louvre', 1.1, 1.3), ('se_turq', 1.6, 1.3), ('se_fret', 1.1, 1.6), ('se_slide', 1.5, 1.2),
            ('se_fold', 1.8, 1.6), ('se_bars', .9, .9), ('se_door_green', 1.3, 2.2), ('se_door_gate', 2.2, 2.4)]),
    'me': (4, 2, _HEAD + 'houses in Jordan, Tunisia, Egypt and Iran. Row 1: an arched window with a decorative '
           'wrought iron grille painted black and a pale stone surround; a Tunisian window with a projecting '
           'blue-painted iron cage grille and blue shutters; a dark brown wooden mashrabiya lattice screen window; '
           'a small plain aluminium window with a white roller shutter half lowered. Row 2: a window with closed '
           'pale green metal shutters; a small square deep-set window with iron bars; an ornate painted steel double '
           'door in dark green with a gold geometric pattern; an arched wooden door painted bright blue with black '
           'iron studs.',
           [('me_arch', 1.1, 1.6), ('me_blue', 1.3, 1.5), ('me_mashrabiya', 1.2, 1.5), ('me_roller', 1.2, 1.2),
            ('me_shut', 1.1, 1.3), ('me_small', .7, .7), ('me_door_steel', 1.5, 2.3), ('me_door_blue', 1.1, 2.2)]),
    'af': (4, 2, _HEAD + 'houses in Kenya, Tanzania, Nigeria and Ghana. Row 1: a steel casement window of small panes '
           'painted pale blue with welded burglar bars; a window opening closed by a wooden plank shutter painted '
           'green; a glass louvre window behind a steel security mesh; a small window with a blue-painted steel frame '
           'and a curtain. Row 2: a wide steel-framed window with diamond-pattern burglar bars painted white; a '
           'window opening filled with decorative concrete breeze blocks; a painted steel sheet door in red oxide '
           'with a padlock; a wooden plank door painted bright blue.',
           [('af_casement', 1.2, 1.2), ('af_plank', .9, 1.0), ('af_louvre', 1.0, 1.2), ('af_small', .9, .9),
            ('af_wide', 1.6, 1.2), ('af_breeze', 1.0, 1.0), ('af_door_steel', .9, 2.0), ('af_door_plank', .9, 2.0)]),
}
# what the model drew otherwise than asked: sheet -> columns a row. (Japan's lattice window and
# louvred slit stand one over the other in the fourth column: cut() parts what is stacked.)
DRAWN = {'uk': (4, 5)}       # two blue doors where one was asked for
# open shutters with nothing between their leaves: the magenta inside the object is glass
GLASS_FILL = ('se_turq',)
# cells with no pane to find: shutters closed, lattices, screens, breeze blocks (and every door
# but GLASS_DOORS)
MATT = ('la_blue', 'sa_shut', 'sa_jali', 'se_bars', 'me_mashrabiya', 'me_shut', 'af_plank', 'af_breeze', 'jp_koshi',
        'cn_lattice', 'jp_slit')
GLASS_DOORS = ('mo_door_anthr', 'al_door_glass', 'jp_door_genkan')
ATLAS, SLOT, GUTTER = 4096, 512, 6
ATLASES = ('house_cells', 'house_cells2')
FIRST_ATLAS = 2         # kit_cells is 0 and kit_cells2 is 1 in a cell's seventh number


def wall_set(name):
    return 'hs_' + name


def roof_set(name):
    return 'hr_' + name


def has(folder):
    return (TEXTURES / folder / 'albedo.jpg').exists() and (TEXTURES / folder / 'normal.jpg').exists()


def sheet_path(name):
    return SRC / f'sheet_{name}.png'


def ready():
    """Every source of the library is there (houses.lua's styles draw from all of them)."""
    return (all(has(wall_set(n)) for n in WALLS) and all(has(roof_set(n)) for n in ROOFS)
            and all(sheet_path(n).exists() for n in SHEETS))


def sheets():
    """fast_facade sheets of the library: name -> (set of the texture library, fit)."""
    out = {'sh_h_' + n: (wall_set(n), 'wall grey' if grey else 'wall') for n, (_, grey, _) in WALLS.items()}
    out.update({'sh_hr_' + n: (roof_set(n), ('roof grey' if grey else 'roof') + (' turn' if n in TURN else ''))
                for n, (_, grey, _) in ROOFS.items()})
    out.update(EXTRA_SHEETS)
    return out


def wall_kinds():
    """kind -> (sheet, sRGB of the wall or None for the sheet's own colour, metres a repeat, painted)."""
    out = {}
    for name, (metres, grey, _) in WALLS.items():
        stem = STEMS.get(name, name)
        if grey:
            for paint, rgb in PAINTS[name].items():
                out[f'hw_h_{stem}_{paint}'] = ('sh_h_' + name, rgb, metres, True)
        else:
            out['hw_h_' + stem] = ('sh_h_' + name, None, metres, False)
    for kind, (sheet, rgb, metres) in EXTRA_WALLS.items():
        out[kind] = (sheet, rgb, metres, True)
    return out


def roof_kinds():
    out = {}
    for name, (metres, grey, _) in ROOFS.items():
        if grey:
            for paint, rgb in ROOF_PAINTS[name].items():
                out[f'roof_h_{name}_{paint}'] = ('sh_hr_' + name, rgb, metres, True)
        else:
            out['roof_h_' + name] = ('sh_hr_' + name, None, metres, False)
    for kind, (sheet, rgb, metres, painted) in EXTRA_ROOFS.items():
        out[kind] = (sheet, rgb, metres, painted)
    return out


def mean_rgb(folder):
    """The sRGB mean of a set's colour map (a flat colour for a game without the maps)."""
    im = Image.open(TEXTURES / folder / 'albedo.jpg').convert('RGB').resize((32, 32), Image.BILINEAR)
    return tuple(int(v) for v in np.asarray(im).reshape(-1, 3).mean(axis=0))


def means():
    """{sheet: sRGB mean} of the library's own-coloured sheets, kept beside the sources (fast_style
    is imported often: sixty JPEGs are not opened each time)."""
    import json
    book = SRC / 'means.json'
    known = json.loads(book.read_text(encoding='utf8')) if book.exists() else {}
    stamp = {name: int((TEXTURES / folder / 'albedo.jpg').stat().st_mtime) for name, (folder, _) in sheets().items()}
    if known.get('stamp') != stamp:
        known = {'stamp': stamp, 'rgb': {name: mean_rgb(folder) for name, (folder, _) in sheets().items()}}
        book.write_text(json.dumps(known), encoding='utf8')
    return {name: tuple(rgb) for name, rgb in known['rgb'].items()}


ROLES = (('', 'lit'), ('_2', 'albedo'), ('_3', 'normal'), ('_4', 'roughness'), ('_5', 'height'))


def generate(only=None, workers=4):
    """Paid fal calls for the sources that are missing. Returns the lines of what was made."""
    cli = shutil.which('um')
    if not cli:
        raise SystemExit('um (universal-modder) is required for generation')
    SRC.mkdir(parents=True, exist_ok=True)
    jobs = [('set', wall_set(n), prompt + WALL) for n, (_, _, prompt) in WALLS.items() if not has(wall_set(n))]
    jobs += [('set', roof_set(n), prompt + ROOF) for n, (_, _, prompt) in ROOFS.items() if not has(roof_set(n))]
    jobs += [('sheet', n, spec[2] + SHEET_STYLE) for n, spec in SHEETS.items() if not sheet_path(n).exists()]
    if only:
        jobs = [j for j in jobs if j[1] in only or j[0] in only]

    def one(job):
        kind, name, prompt = job
        tmp = SRC / 'tmp' / name
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            if kind == 'set':
                argv = [cli, 'fal', 'run', 'fal-ai/patina/material', 'prompt=' + prompt, 'image_size=square_hd',
                        'maps:=["basecolor","normal","roughness","height"]', 'enable_prompt_expansion:=false',
                        '--out', str(tmp), '--name', name]
            else:
                argv = [cli, 'fal', 'image', prompt, '--model', 'fal-ai/nano-banana-2', '--res', '2K', '--aspect', '16:9',
                        '--out', str(tmp), '--name', name]
            done = subprocess.run(argv, capture_output=True, text=True, encoding='utf8', errors='replace')
            if done.returncode:
                return f'{name}: FAILED {done.stdout[-300:]} {done.stderr[-300:]}'
            if kind == 'set':
                out = TEXTURES / name
                out.mkdir(parents=True, exist_ok=True)
                for suffix, role in ROLES:
                    source = tmp / f'{name}{suffix}.png'
                    if role != 'lit' and source.exists():
                        Image.open(source).convert('RGB').save(out / f'{role}.jpg', quality=95)
            else:
                shutil.move(tmp / f'{name}.png', sheet_path(name))
            log = tmp / 'fal_manifest.jsonl'
            if log.exists():
                with (SRC / 'fal_manifest.jsonl').open('a', encoding='utf8') as book:
                    book.write(log.read_text(encoding='utf8'))
                log.unlink()
            return f'{name}: ok'
        except Exception as error:      # one failed recipe must not lose the others
            return f'{name}: FAILED {error}'

    lines = []
    with ThreadPoolExecutor(workers) as pool:
        for line in pool.map(one, jobs):
            print(line, flush=True)
            lines.append(line)
    return lines


# ---------------------------------------------------------------------------------------------
# The atlases of windows and doors: the kit's cutter and its glass mask (kit_art), cells of
# SLOT px in two sheets of ATLAS px, sixty-four a sheet.
def cut(name):
    """The cells of one sheet as [(cell, RGB array, background mask, width m, height m)]."""
    import kit_art
    cols, rows, _, cells = SHEETS[name]
    im = np.asarray(Image.open(sheet_path(name)).convert('RGB')).astype(np.int32)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    bg = (r > 150) & (b > 150) & (g < 120) & ((r + b) // 2 - g > 70)
    # thin rules the model sometimes draws between its cells are background too
    lines = (bg.mean(axis=1) > .5)[:, None] | (bg.mean(axis=0) > .5)[None, :]
    thin = ~bg & lines & (im.sum(axis=2) < 200)
    if thin.any():
        im = im.copy()
        im[thin] = (255, 0, 255)
        bg = bg | thin
    rows_ = sorted(sorted(kit_art._runs((~bg).mean(axis=1) > .02, 40), key=lambda q: q[0] - q[1])[:rows])
    if len(rows_) != rows:
        raise ValueError(f'{name}: {len(rows_)} rows of cells, expected {rows}')
    parts = []
    for row, (y0, y1) in enumerate(rows_):
        spans = kit_art._runs((~bg[y0:y1]).mean(axis=0) > .02, 40)
        want = DRAWN.get(name, cols)
        want = want[row] if isinstance(want, tuple) else want
        for x0, x1 in sorted(sorted(spans, key=lambda q: q[0] - q[1])[:want]):
            # objects one over the other in a column are each a cell
            for s0, s1 in kit_art._runs((~bg[y0:y1, x0:x1]).mean(axis=1) > .04, 30):
                part = ~bg[y0 + s0:y0 + s1, x0:x1]
                ys, xs = np.where(part.mean(axis=1) > .04)[0], np.where(part.mean(axis=0) > .04)[0]
                cy0, cy1, cx0, cx1 = y0 + s0 + ys[0] + 3, y0 + s0 + ys[-1] - 2, x0 + xs[0] + 3, x0 + xs[-1] - 2
                parts.append((im[cy0:cy1, cx0:cx1].astype(np.uint8), bg[cy0:cy1, cx0:cx1]))
    if len(parts) != len(cells):
        raise ValueError(f'{name}: {len(parts)} objects, expected {len(cells)}')
    return [(cell, rgb, mask, w, h) for (cell, w, h), (rgb, mask) in zip(cells, parts)]


def atlases():
    """[(colour, roughness, metal)] of the two atlases and {cell: (u0, v0, u1, v1, w m, h m, atlas)}."""
    import kit_art
    n = ATLAS // SLOT
    out, table = [], {}
    cells = [c for name in SHEETS for c in cut(name)]
    for index in range(len(ATLASES)):
        colour = np.full((ATLAS, ATLAS, 3), 128, np.uint8)
        glass = np.zeros((ATLAS, ATLAS))
        for k, (cell, rgb, bg, wm, hm) in enumerate(cells[index * n * n:(index + 1) * n * n]):
            door = '_door_' in cell
            pic, mask = kit_art.cell_maps(cell, rgb, bg, glass=cell not in MATT and (not door or cell in GLASS_DOORS),
                                          fill=cell in GLASS_FILL)
            size = SLOT - 2 * GUTTER
            pic = np.asarray(Image.fromarray(pic).resize((size, size), Image.LANCZOS))
            mask = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize((size, size), Image.BILINEAR), dtype=np.float64) / 255
            x, y = k % n * SLOT, k // n * SLOT
            colour[y:y + SLOT, x:x + SLOT] = np.pad(pic, ((GUTTER, GUTTER), (GUTTER, GUTTER), (0, 0)), mode='edge')
            glass[y:y + SLOT, x:x + SLOT] = np.pad(mask, GUTTER, mode='edge')
            table[cell] = (round((x + GUTTER + .5) / ATLAS, 5), round((y + GUTTER + .5) / ATLAS, 5),
                           round((x + SLOT - GUTTER - .5) / ATLAS, 5), round((y + SLOT - GUTTER - .5) / ATLAS, 5),
                           wm, hm, FIRST_ATLAS + index)
        rough = (.82 - .72 * glass) * 255
        half = (ATLAS // 2, ATLAS // 2)
        out.append((Image.fromarray(colour), Image.fromarray(rough.astype(np.uint8)).convert('RGB').resize(half, Image.BILINEAR),
                    Image.fromarray((glass * 255).astype(np.uint8)).convert('RGB').resize(half, Image.BILINEAR)))
    if len(table) != len(cells):
        raise ValueError('the houses\' cells do not fit their atlases')
    return out, table


def cell_names():
    return [cell for spec in SHEETS.values() for cell, _, _ in spec[3]]


def lua_text(cells):
    def row(values):
        return '{' + ', '.join(f'{v:g}' for v in values) + '}'
    lines = ['-- Generated by earthng/house_art.py (--lua): the houses\' library as built. Do not edit.',
             f'return {{version = {VERSION},',
             '  -- cell = {u0, v0, u1, v1, metres wide, metres high, atlas}; v0 is the top; atlas 2 is',
             '  -- house_cells, 3 house_cells2 (0 and 1 are the kit\'s)',
             '  cells = {']
    lines += [f'    {name} = {row(v)},' for name, v in sorted(cells.items())]
    lines += ['  },', '  -- wall kind (e2rf_<kind>) = metres a repeat', '  walls = {']
    lines += [f'    {kind} = {v[2]:g},' for kind, v in sorted(wall_kinds().items())]
    lines += ['  },', '  -- roof kind = metres a repeat (u along the ridge, v down the slope)', '  roofs = {']
    lines += [f'    {kind} = {v[2]:g},' for kind, v in sorted(roof_kinds().items())]
    lines += ['  },', '}', '']
    return '\n'.join(lines)


def build(real, lua=False):
    """Write the atlases into the art root's real/ folder (PNG; the caller makes the DDS). The
    surfaces are fast_facade's sheets. With lua=True also rewrite house_lib.lua."""
    real = Path(real)
    real.mkdir(parents=True, exist_ok=True)
    maps, table = atlases()
    for name, (colour, rough, metal) in zip(ATLASES, maps):
        colour.save(real / f'{name}.color.png')
        rough.save(real / f'{name}_r.data.png')
        metal.save(real / f'{name}_m.data.png')
    if lua:
        LUA.write_text(lua_text(table), encoding='utf8', newline='\n')
    return table


def sheet(path, px=256, cols=10):
    """The colour maps of the surfaces that are there, each tiled twice (how a seam shows), named."""
    from PIL import ImageDraw
    names = [wall_set(n) for n in WALLS] + [roof_set(n) for n in ROOFS]
    names = [n for n in names if has(n)]
    if not names:
        return names
    cell = px * 2
    rows = (len(names) + cols - 1) // cols
    out = Image.new('RGB', (cols * (cell + 6), rows * (cell + 22)), (20, 20, 20))
    draw = ImageDraw.Draw(out)
    for k, name in enumerate(names):
        tile = Image.open(TEXTURES / name / 'albedo.jpg').convert('RGB').resize((px, px), Image.LANCZOS)
        x, y = k % cols * (cell + 6), k // cols * (cell + 22)
        for i in range(2):
            for j in range(2):
                out.paste(tile, (x + i * px, y + 20 + j * px))
        draw.text((x + 4, y + 4), name, fill=(240, 240, 240))
    out.save(path, quality=88)
    return names


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--generate', action='store_true', help='paid: make the missing sources with fal')
    ap.add_argument('--only', nargs='*', help='names of sets (hs_koroid, hr_reed) or sheets (nd), or a kind: set, sheet')
    ap.add_argument('--sheet', type=Path)
    ap.add_argument('--cells', type=Path, help='write the first atlas of cut windows and doors here (a look at it)')
    ap.add_argument('--lua', action='store_true', help='rewrite house_lib.lua (needs every sheet)')
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    if a.list:
        print(len(WALLS), 'walls,', len(ROOFS), 'roofs,', len(SHEETS), 'sheets ->', len(wall_kinds()), 'wall kinds,',
              len(roof_kinds()), 'roof kinds,', len(cell_names()), 'cells')
    if a.generate:
        generate(a.only)
    if a.sheet:
        print('sheet of', len(sheet(a.sheet)), 'sets')
    if a.cells:
        maps, table = atlases()
        maps[0][0].save(a.cells, quality=90)
        if len(maps) > 1:
            maps[1][0].save(a.cells.with_name(a.cells.stem + '2' + a.cells.suffix), quality=90)
    if a.lua:
        _, table = atlases()
        LUA.write_text(lua_text(table), encoding='utf8', newline='\n')
        print(len(table), 'cells ->', LUA)
    missing = ([wall_set(n) for n in WALLS if not has(wall_set(n))] + [roof_set(n) for n in ROOFS if not has(roof_set(n))]
               + ['sheet ' + n for n in SHEETS if not sheet_path(n).exists()])
    print('ready' if not missing else 'missing: ' + ' '.join(missing))
