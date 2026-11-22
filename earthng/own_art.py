"""EarthNG's own library of surfaces: the ground's and the small buildings', made in one style.

The game's maps and the CC0 photos the real pack is drawn from (fetch_textures.SETS) came each
from its own camera, light and country. This library is one hand: every surface is made by the
same model from a prompt written to one pattern (PATINA: colour, normal, roughness and height at
1024 px), an Eastern European place in flat overcast light, weathered a little and never new.

    python earthng/own_art.py --generate [--only own_lawn own_cinder]    # paid: the sources that are missing
    python earthng/own_art.py --sheet out/own-art.jpg                    # a look at what is there

The sources are paid, so made once and kept out of Git, in the texture library's own form:
data/textures/<set>/albedo.jpg, normal.jpg, roughness.jpg, height.jpg (as the CC0 sets of
fetch_textures.py), each call logged in data/textures/own/fal_manifest.jsonl. What takes them:

- GROUND: the photos under the open land (fast_photo.GROUND, its macro sheets and field sheets)
  are swapped for the set named here where it is present (fast_photo.own);
- WALLS, ROOFS: plain sheets of fast_facade.SHEETS and the kinds of fast_style for outbuildings
  (generator.lua BLD.small), only when every one of them is present (ready()).

A checkout without them builds the planet as before.
"""
import argparse
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TEXTURES = ROOT / 'data' / 'textures'
LOG = TEXTURES / 'own'
VERSION = '1'           # change whenever a set's picture changes: the sheets made of it are drawn again

PLAN = (' Seamless tileable material texture photographed perfectly straight down from directly above, orthographic, '
        'flat even overcast daylight, no cast shadows, no perspective, natural muted colours of a temperate Eastern '
        'European summer, evenly distributed over the whole image with no large single feature, no objects, no litter, '
        'no flowers, no text.')
WALL = (' Seamless tileable material texture photographed perfectly straight-on, orthographic, flat even overcast '
        'daylight, no cast shadows, no perspective, natural muted colours, weathered for some decades and never new, '
        'uniform over the whole image with no large single feature, no windows, no doors, no objects, no text.')
# set: (the set of the library it stands in for, metres a repeat, prompt)
GROUND = {
    'own_lawn': ('photo_lawn', 3.0, 'Mown lawn grass of a city yard, short dense blades in a muted olive green with a few '
                 'yellowed blades and a little dry thatch between them.'),
    'own_meadow': ('photo_meadow', 4.0, 'Unmown meadow grass seen from above, longer blades lying in several directions, '
                   'fine seed heads, clover and plantain leaves low among them, olive green with straw-coloured dry stems.'),
    # (the first prompt, "bare compacted earth with sparse tufts", gave a blank beige sheet: what
    # lies on the earth has to be the subject)
    'own_worn': ('photo_worn', 3.0, 'Patchy worn grass of a trampled yard seen from above: flattened tufts of short dull '
                 'green and yellowed grass over about half of the image, scattered between them patches of bare '
                 'grey-brown earth with many small pebbles, bits of dry stalk and footprints pressed into it.'),
    'own_verge': ('photo_verge', 3.0, 'Roadside verge: coarse dusty grass, broad plantain and dandelion leaves, dry '
                  'stalks and a little grit and sand between the plants, dull olive green and tan.'),
    'own_litter': ('leaves_brown', 2.0, 'Floor of a deciduous wood: a thick layer of last year\'s brown oak and hornbeam '
                   'leaves, small twigs and a few acorn cups, dark humus showing in the gaps.'),
    'own_moss': ('moss_earth', 4.0, 'Floor of a pine wood: patches of green moss, a carpet of fallen brown pine needles, '
                 'small cones and bits of bark, dark earth between them.'),
    'own_soil': ('mat_soil', 2.0, 'Ploughed black earth of a Ukrainian field, chernozem: dark brown-black crumbly clods '
                 'and fine tilth, a few pale dry clod tops and thin roots.'),
    'own_stubble': ('mat_stubble', 2.0, 'Wheat stubble after harvest seen from above: short cut straw stalks standing in '
                    'faint parallel rows, loose straw and chaff lying over dark soil, pale gold and grey-brown.'),
    'own_steppe': ('steppe_ground', 3.0, 'Dry steppe grassland in late summer: bleached tufts of feather grass and '
                   'fescue, straw yellow and grey-green, cracked pale earth between the tufts.'),
    'own_dirt': (None, 3.0, 'Dried mud of a village dirt road seen from above: grey-brown clay loam broken edge to '
                 'edge by a clear network of shrinkage cracks into plates a hand wide, many small stones pressed into '
                 'it, crumbs of darker earth and bits of straw.'),
    'own_gravel': (None, 2.0, 'Crushed stone surfacing: angular grey granite gravel of mixed sizes up to three '
                   'centimetres, densely packed, with fine grey dust between the stones.'),
    'own_sand': (None, 3.0, 'Fine pale river sand with faint wind ripples, a few tiny shell fragments and darker damp '
                 'grains, warm light beige.'),
}
# set: (metres a repeat, 'grey' when it is painted by its kinds, prompt)
WALLS = {
    'own_cinder': (2.4, '', 'Wall of a Ukrainian garage built of grey cinder blocks, each block about forty centimetres '
                   'long and twenty high in running bond, rough porous faces, crude uneven cement mortar joints with '
                   'smears, a few chipped corners.'),
    'own_shell': (2.4, '', 'Wall of sawn shell limestone blocks of southern Ukraine, each block about forty centimetres '
                  'long and twenty high in running bond, pale yellow-cream porous stone full of small shell holes, thin '
                  'grey mortar joints, dust and light rain stains.'),
    'own_silicate': (2.4, '', 'Wall of a Soviet garage in white-grey silicate brick laid without care: slightly uneven '
                     'courses in running bond, about thirty courses from top to bottom, thick grey mortar squeezed out of '
                     'the joints, grey rain streaks and a few chipped bricks.'),
    'own_brick_rough': (2.4, '', 'Wall of a shed in old red-brown brick laid roughly: uneven courses in running bond, '
                        'about thirty courses from top to bottom, wide sandy mortar joints, some darker burnt bricks and '
                        'pale salt stains.'),
    'own_boards_grey': (2.0, '', 'Wall of a village shed made of unpainted vertical softwood boards about twelve '
                        'centimetres wide, weathered silver-grey with darker grain and knots, narrow dark gaps between '
                        'the boards, a few rusty nail heads.'),
    'own_boards_paint': (2.0, 'grey', 'Wall of a village house clad in vertical tongue-and-groove boards about ten '
                         'centimetres wide, covered in old thick oil paint in plain light neutral grey, the paint '
                         'cracked and flaking in places to bare grey wood.'),
    'own_steel': (2.5, 'grey', 'Wall of an old welded sheet steel garage: flat steel sheets about one metre wide '
                  'joined by raised vertical welded seams, angle-iron ribs and rows of rivets, thick old brushed paint '
                  'in plain light neutral grey peeling in flakes, brown rust blooming along every seam, in scratches '
                  'and in patches, a few dents.'),
    'own_osb': (2.4, '', 'Wall of oriented strand board panels, large flat wood strands pressed in all directions, '
                'honey and tan, slightly greyed by weather, a thin panel joint.'),
    'own_poly': (2.0, '', 'Wall of a garden greenhouse made of cellular polycarbonate sheet: milky translucent white '
                 'plastic with fine vertical channels a centimetre apart, dusty, faint green algae near the bottom, '
                 'thin aluminium joining strips two metres apart.'),
    'own_log': (2.4, '', 'Wall of an old log cabin: horizontal round pine logs about twenty centimetres thick, '
                'weathered dark brown-grey with long cracks, moss and tow caulking in the grooves between the logs.'),
    'own_limewash': (3.0, '', 'Wall of an old Ukrainian clay-plastered village house: uneven hand-smoothed plaster under '
                     'many coats of white limewash, a fine net of cracks, small patches where the wash has flaked to '
                     'ochre clay, grey rain marks.'),
    'own_slab': (3.0, '', 'Wall of a precast concrete garage: plain grey concrete slabs with a rough cast face, faint '
                 'formwork marks, air pores, rust stains from the reinforcement and dark rain streaks.'),
}
ROOFS = {
    'own_wave': (1.75, '', 'Close view of a roof of deeply corrugated grey asbestos cement sheets seen from directly '
                 'above: about twelve big rounded waves across the image running straight from the top edge to the '
                 'bottom edge, every wave clearly shaded with a pale crest and a dark valley, two horizontal rows of '
                 'overlapping sheet ends with nail heads, patches of yellow-green lichen on the crests and dark moss '
                 'in the valleys.'),
    'own_felt': (4.0, '', 'Flat garage roof covered with old bituminous roll roofing seen from directly above: dark grey '
                 'strips about one metre wide with glossy black tar along the overlaps, cracked blisters, lighter '
                 'patches of repair and a little dust and dry leaf mould.'),
    'own_ondulin': (1.9, 'grey', 'Roof of bituminous corrugated sheets seen from directly above: small rounded '
                    'corrugations about ten centimetres apart running from the top of the image to the bottom, matt '
                    'fibrous surface in plain neutral grey, rows of nail caps, overlapping sheet ends.'),
    'own_tin': (1.8, '', 'Old galvanised sheet steel roof seen from directly above: flat sheets with standing seams about '
                'fifty centimetres apart running from the top of the image to the bottom, dull zinc grey going to '
                'orange-brown rust in streaks and at the seams.'),
}
SETS = {**GROUND, **WALLS, **ROOFS}

# A sheet of doors for outbuildings (Nano Banana 2, as the kit's sheets of windows: kit_art.SHEETS):
# eight objects in a grid on magenta, cut out into the atlas ob_cells (cells()), four across and
# two down, in this order (generator.lua BLD.SMALL.cells counts them from 0).
SHEET_STYLE = (' Each one isolated on a plain solid magenta #FF00FF background with clear magenta gaps between them. '
               'Orthographic perfectly frontal view, no perspective, flat overcast light, photorealistic, weathered '
               'for decades. Only the doors themselves, closed, filling their cells: no walls around them, no '
               'ground, no text, no numbers, no labels.')
DOORS = ('Texture atlas sprite sheet: a strict grid of 4 columns and 2 rows showing 8 different doors of garages and '
         'sheds typical of Ukraine. Row 1: a Soviet double-leaf sheet steel garage door painted dark green with rust '
         'along its edges; a double-leaf steel garage door in red-brown primer with a small wicket door in one leaf; '
         'a double-leaf steel garage door in peeling light grey paint with rust streaks; a double-leaf steel garage '
         'door painted faded blue. Row 2: an unpainted heavily rusted double-leaf steel garage door; a modern white '
         'sectional garage door of horizontal panels; a tall double gate of a barn made of weathered grey vertical '
         'planks with diagonal braces; a narrow shed door of old vertical boards with a Z brace and a padlock.')
# cell: (width m, height m)
DOOR_CELLS = (('g_green', 2.5, 2.2), ('g_primer', 2.5, 2.2), ('g_grey', 2.5, 2.2), ('g_blue', 2.5, 2.2),
              ('g_rust', 2.5, 2.2), ('g_sectional', 2.5, 2.2), ('barn_gate', 3.2, 3.0), ('shed_door', .9, 1.9))
CELL_PX, CELL_GUTTER, CELL_COLS, CELL_ROWS = 512, 6, 4, 2


def doors_sheet():
    return LOG / 'sheet_doors.png'


def cells_ready():
    return doors_sheet().exists()


def generate_sheet():
    """Paid: the sheet of doors, when it is missing."""
    cli = shutil.which('um')
    if not cli:
        raise SystemExit('um (universal-modder) is required for generation')
    if cells_ready():
        return False
    tmp = LOG / 'tmp' / 'sheet_doors'
    tmp.mkdir(parents=True, exist_ok=True)
    subprocess.run([cli, 'fal', 'image', DOORS + SHEET_STYLE, '--model', 'fal-ai/nano-banana-2', '--res', '2K',
                    '--aspect', '16:9', '--out', str(tmp), '--name', 'doors'], check=True)
    shutil.move(tmp / 'doors.png', doors_sheet())
    log = tmp / 'fal_manifest.jsonl'
    if log.exists():
        with (LOG / 'fal_manifest.jsonl').open('a', encoding='utf8') as book:
            book.write(log.read_text(encoding='utf8'))
    return True


def _runs(mask, least):
    out, start = [], None
    for k, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = k
        elif not v and start is not None:
            if k - start >= least:
                out.append((start, k))
            start = None
    return out


def cells():
    """The atlas of the doors (a PIL image, CELL_COLS x CELL_ROWS cells of CELL_PX) cut from the
    sheet: every object tight on its own edge, the magenta it stood on and what bled into it
    replaced by the door's own middle colour, a gutter of its edge round it."""
    import numpy as np
    im = np.asarray(Image.open(doors_sheet()).convert('RGB')).astype(np.int32)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    bg = (r > 150) & (b > 150) & (g < 120) & ((r + b) // 2 - g > 70)
    bands = _runs((~bg).mean(axis=1) > .02, 40)
    bands = sorted(sorted(bands, key=lambda q: q[0] - q[1])[:CELL_ROWS])
    if len(bands) != CELL_ROWS:
        raise ValueError(f'doors: {len(bands)} rows of cells, expected {CELL_ROWS}')
    atlas = Image.new('RGB', (CELL_COLS * CELL_PX, CELL_ROWS * CELL_PX), (120, 120, 120))
    k = 0
    for row, (y0, y1) in enumerate(bands):
        spans = _runs((~bg[y0:y1]).mean(axis=0) > .02, 40)
        spans = sorted(sorted(spans, key=lambda q: q[0] - q[1])[:CELL_COLS])
        if len(spans) != CELL_COLS:
            raise ValueError(f'doors: {len(spans)} cells in row {row}, expected {CELL_COLS}')
        for x0, x1 in spans:
            part = ~bg[y0:y1, x0:x1]
            ys, xs = np.where(part.mean(axis=1) > .5)[0], np.where(part.mean(axis=0) > .5)[0]
            cy0, cy1, cx0, cx1 = y0 + ys[0] + 3, y0 + ys[-1] - 2, x0 + xs[0] + 3, x0 + xs[-1] - 2
            cut, hole = im[cy0:cy1, cx0:cx1].astype(np.float64), bg[cy0:cy1, cx0:cx1]
            pink = (cut[..., 0] + cut[..., 2]) / 2 - cut[..., 1] > 34
            hole = hole | pink
            if (~hole).any():
                cut[hole] = np.median(cut[~hole], axis=0)
            inner = CELL_PX - 2 * CELL_GUTTER
            pic = np.asarray(Image.fromarray(cut.astype(np.uint8)).resize((inner, inner), Image.LANCZOS))
            pic = np.pad(pic, ((CELL_GUTTER,) * 2, (CELL_GUTTER,) * 2, (0, 0)), mode='edge')
            atlas.paste(Image.fromarray(pic), (k % CELL_COLS * CELL_PX, k // CELL_COLS * CELL_PX))
            k += 1
    return atlas

ROLES = (('', 'lit'), ('_2', 'albedo'), ('_3', 'normal'), ('_4', 'roughness'), ('_5', 'height'))


def has(name):
    return (TEXTURES / name / 'albedo.jpg').exists() and (TEXTURES / name / 'normal.jpg').exists()


def ready():
    """Every wall and roof of the library is there (the generator's outbuildings draw from all of them)."""
    return all(has(name) for name in list(WALLS) + list(ROOFS))


def stand_ins():
    """{set of the texture library: the own set that takes its place} for the ground's sets that are there."""
    return {old: name for name, (old, _, _) in GROUND.items() if old and has(name)}


def generate(only=None, workers=4):
    """Paid fal calls for the sets that are missing. Returns the lines of what was made."""
    cli = shutil.which('um')
    if not cli:
        raise SystemExit('um (universal-modder) is required for generation')
    LOG.mkdir(parents=True, exist_ok=True)
    jobs = [name for name in SETS if not has(name) and (not only or name in only)]

    def one(name):
        prompt = SETS[name][-1] + (PLAN if name in GROUND or name in ROOFS else WALL)
        tmp = LOG / 'tmp' / name
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            done = subprocess.run([cli, 'fal', 'run', 'fal-ai/patina/material', 'prompt=' + prompt, 'image_size=square_hd',
                                   'maps:=["basecolor","normal","roughness","height"]', 'enable_prompt_expansion:=false',
                                   '--out', str(tmp), '--name', name], capture_output=True, text=True, encoding='utf8',
                                  errors='replace')
            if done.returncode:
                return f'{name}: FAILED {done.stdout[-300:]} {done.stderr[-300:]}'
            out = TEXTURES / name
            out.mkdir(parents=True, exist_ok=True)
            for suffix, role in ROLES:
                source = tmp / f'{name}{suffix}.png'
                if role != 'lit' and source.exists():
                    Image.open(source).convert('RGB').save(out / f'{role}.jpg', quality=95)
            log = tmp / 'fal_manifest.jsonl'
            if log.exists():
                with (LOG / 'fal_manifest.jsonl').open('a', encoding='utf8') as book:
                    book.write(log.read_text(encoding='utf8'))
            return f'{name}: ok'
        except Exception as error:      # one failed recipe must not lose the others
            return f'{name}: FAILED {error}'

    lines = []
    with ThreadPoolExecutor(workers) as pool:
        for line in pool.map(one, jobs):
            print(line, flush=True)
            lines.append(line)
    return lines


def sheet(path, repeats=2, px=256):
    """The colour maps side by side, each tiled `repeats` times (how a seam shows), named."""
    from PIL import ImageDraw
    names = [n for n in SETS if has(n)]
    if not names:
        return names
    cols = 7
    cell = px * repeats
    rows = (len(names) + cols - 1) // cols
    out = Image.new('RGB', (cols * (cell + 6), rows * (cell + 22)), (20, 20, 20))
    draw = ImageDraw.Draw(out)
    for k, name in enumerate(names):
        tile = Image.open(TEXTURES / name / 'albedo.jpg').convert('RGB').resize((px, px), Image.LANCZOS)
        x, y = k % cols * (cell + 6), k // cols * (cell + 22)
        for i in range(repeats):
            for j in range(repeats):
                out.paste(tile, (x + i * px, y + 20 + j * px))
        draw.text((x + 4, y + 4), name, fill=(240, 240, 240))
    out.save(path, quality=88)
    return names


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--generate', action='store_true', help='paid: make the missing sets with fal')
    ap.add_argument('--only', nargs='*')
    ap.add_argument('--sheet', type=Path)
    ap.add_argument('--doors', type=Path, help='write the cut atlas of doors here (a look at it)')
    a = ap.parse_args()
    if a.generate:
        generate(a.only)
        if not a.only:
            generate_sheet()
    if a.doors and cells_ready():
        cells().save(a.doors, quality=90)
    if a.sheet:
        print('sheet of', len(sheet(a.sheet)), 'sets')
    missing = [n for n in SETS if not has(n)]
    print('ready' if not missing else 'missing: ' + ' '.join(missing))
