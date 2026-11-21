"""Art of the building kit (mod/lua/ge/extensions/e2r/kit.lua).

Three kinds of generated source, all made with fal and kept in data/textures/kit (paid, so only
with an explicit --generate; every call is logged by `um` in fal_manifest.jsonl there):

- WALLS: seamless PBR wall and roof surfaces (PATINA), one material each, tinted per kind;
- SHEETS: eight windows, doors or details on magenta in one image (Nano Banana 2), cut into the
  cells of one atlas (kit_cells);
- BANDS: long horizontal strips (cornices, slab edges, rustication) that repeat along a wall,
  stacked in one trim texture (kit_trim).

build() writes the maps into the art root's real/ folder; cells() describes the atlas for the Lua
side (kit_cells.lua is generated from it and checked in).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import shutil
import subprocess

import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / 'data' / 'textures' / 'kit'
LUA = ROOT / 'mod/lua/ge/extensions/e2r/kit_cells.lua'
VERSION = '4'          # change whenever a map this module writes changes

WALL_STYLE = (' Seamless tileable material texture photographed perfectly straight-on, orthographic, flat even '
              'overcast light, no cast shadows, no windows, no doors, no objects, no text, uniform over the whole image.')
# name: (metres a repeat, class, prompt). The class sets the roughness and how the tone is kept.
WALLS = {
    'brick_yellow': (3.0, 'brick', 'Wall of pale yellow ceramic facing brick of a 1970s Kyiv apartment block seen from several '
                     'metres away, small bricks in a regular running bond, about forty courses from top to bottom, grey '
                     'cement mortar joints, mild soot weathering.'),
    'brick_red': (3.0, 'brick', 'Wall of red-brown Soviet ceramic brick seen from several metres away, small slightly uneven '
                  'bricks in a regular running bond, about forty courses from top to bottom, pale grey mortar, a few '
                  'darker burnt bricks, mild weathering.'),
    'brick_silicate': (3.0, 'brick', 'Wall of white-grey silicate sand-lime brick of a 1960s Soviet five-storey apartment block '
                       'seen from several metres away, small bricks in a regular running bond, about forty courses from '
                       'top to bottom, grey mortar, faint grey rain staining.'),
    'brick_old': (3.0, 'brick', 'Wall of nineteenth century Kyiv yellow-ochre brick seen from several metres away, small worn '
                  'hand-made bricks in a regular bond, about forty courses from top to bottom, eroded dark joints, a few '
                  'chipped and replaced bricks, soot.'),
    'brick_brown': (3.0, 'brick', 'Wall of dark brown clinker facing brick of a modern apartment building seen from several '
                    'metres away, small crisp bricks in a regular running bond, about forty courses from top to bottom, '
                    'dark grey joints.'),
    'brick_london': (3.0, 'brick', 'Wall of London stock brick seen from several metres away, small yellow-brown bricks with '
                     'soot-darkened faces in Flemish bond, about forty courses from top to bottom, weathered lime mortar.'),
    'brick_us': (3.0, 'brick', 'Wall of old American red common brick of a New York tenement seen from several metres away, '
                 'small bricks in running bond with a header course every sixth row, about forty courses from top to '
                 'bottom, worn grey mortar, patches of soot.'),
    'plaster_smooth': (4.0, 'plaster', 'Smooth painted facade stucco in plain light neutral grey, very fine sand grain, a few '
                       'faint hairline cracks and subtle uneven trowel marks, barely visible dust streaks.'),
    'plaster_aged': (4.0, 'plaster', 'Old lime plaster facade in plain light neutral grey, patchy repairs in slightly different '
                     'tones, fine cracks, faint water stains and a little flaking paint.'),
    'plaster_rough': (2.0, 'plaster', 'Rough sprayed cement render on a facade, the Soviet "shuba" coat, coarse pebbly grain in '
                      'plain light neutral grey, evenly distributed, slightly dusty.'),
    'panel_pebble': (1.5, 'concrete', 'Surface of a Soviet precast concrete wall panel with exposed fine gravel aggregate, small '
                     'grey and beige pebbles densely set in cement, evenly distributed, light weathering.'),
    'panel_tile': (1.2, 'tile', 'Facade clad in small square glazed ceramic mosaic tiles of a Soviet apartment block, each '
                   'tile about two centimetres, light neutral grey-white tiles in a strict regular grid with thin grey '
                   'grout, a few slightly darker tiles, seen from two metres away.'),
    'concrete': (3.0, 'concrete', 'Plain cast concrete wall, light grey, faint horizontal formwork board marks, small air '
                 'pores, light rain streaks and stains.'),
    'rustic': (2.4, 'plaster', 'Rusticated stucco ground floor of a Stalin-era building: rectangular plaster blocks about sixty '
               'centimetres long and thirty high in running bond with deep bevelled V joints, plain light neutral grey '
               'paint, slightly dusty.'),
    'granite': (2.4, 'stone', 'Plinth cladding of large rectangular slabs of grey-pink granite with a rough bush-hammered '
                'face, about one metre long and half a metre high, thin dark joints, street dust near the joints.'),
    'limestone': (2.4, 'stone', 'Ashlar wall of pale beige limestone blocks about sixty centimetres long and thirty high in '
                  'regular courses, fine joints, soot in the joints and light weathering.'),
    'brownstone': (2.4, 'stone', 'Facade of New York brownstone, large smooth chocolate-brown sandstone ashlar blocks in regular '
                   'courses with fine joints, slight flaking and weathering.'),
    'fibre_panel': (2.4, 'panel', 'Modern ventilated facade of flat fibre cement panels in plain light neutral grey, each panel '
                    'about 1.2 metres wide and 0.6 high, in a strict grid with thin dark open joints and small rivets at '
                    'the corners.'),
    'corrugated': (1.2, 'metal', 'Painted corrugated steel sheet, vertical trapezoid ribs about ten centimetres apart, plain '
                   'light neutral grey paint, slightly chalky, tiny scratches.'),
    'asbestos': (1.5, 'concrete', 'Flat grey asbestos cement sheet of a Soviet balcony parapet, weathered, faint fibrous '
                 'texture, flaking pale paint and rain streaks.'),
    'bitumen': (4.0, 'roof', 'Flat roof covered with dark grey bituminous roofing felt with mineral granules, overlapping '
                'strips about one metre wide with tar seams, patches of repair and dry puddle marks, seen from above.'),
    'zinc': (1.5, 'metal', 'Standing seam roof of galvanized steel sheet, dull grey zinc with vertical seams about fifty '
             'centimetres apart, light oxidation spots and faint streaks.'),
    'azulejo': (1.4, 'tile', 'Facade of a Lisbon house covered in traditional Portuguese azulejo ceramic tiles, each square '
                'tile about fourteen centimetres with a repeating blue and white geometric floral pattern, glossy glaze, '
                'thin grout lines, a few chipped and faded tiles, seen from three metres away.'),
    'azulejo_green': (1.4, 'tile', 'Facade of a Porto house covered in traditional Portuguese ceramic tiles, each square tile '
                      'about fourteen centimetres, plain glossy bottle-green glaze with slight variation between tiles, thin '
                      'pale grout lines, a few cracked tiles, seen from three metres away.'),
    'whitewash': (3.0, 'plaster', 'Rough whitewashed lime wall of a Mediterranean village house, uneven hand-applied plaster '
                  'with soft bumps, thick chalky white paint, a few hairline cracks and faint grey rain marks.'),
    'stucco_warm': (4.0, 'plaster', 'Mediterranean lime stucco facade in plain light neutral grey, soft cloudy patina, sun-bleached, '
                    'faint cracks and a few stains under ledges.'),
}

SHEET_STYLE = (' Each one isolated on a plain solid magenta #FF00FF background with clear magenta gaps between them. '
               'Orthographic perfectly frontal view, no perspective, all at the same scale, flat overcast light, '
               'photorealistic. Only the objects themselves: no walls around them, no sills, no text, no labels.')
# name: (columns, rows, prompt, cells in reading order as (cell, width m, height m))
SHEETS = {
    'eeu_win1': (4, 2, 'Texture atlas sprite sheet: a strict grid of 4 columns and 2 rows showing 8 different apartment '
                 'windows typical of Kyiv, Ukraine. Row 1: old Soviet white wooden window with three panes and a small '
                 'ventilation pane with lace curtain; white PVC double window with blinds; brown PVC window with a curtain '
                 'and flowers; old wooden window with peeling blue-white paint and an air vent. Row 2: tall narrow pre-war '
                 'window with arched top and dark wooden frame; white PVC three-section window with tulle; window with an '
                 'open casement and laundry visible; modern anthracite aluminium window with a roller blind.',
                 [('w_sov3', 1.45, 1.5), ('w_pvc_blinds', 1.3, 1.5), ('w_pvc_brown', 1.3, 1.5), ('w_wood_blue', 1.3, 1.5),
                  ('w_arch', 1.1, 2.0), ('w_pvc3', 1.75, 1.5), ('w_laundry', 1.4, 1.5), ('w_dark', 1.45, 1.6)]),
    'eeu_win2': (4, 2, 'Texture atlas sprite sheet: a strict grid of 4 columns and 2 rows showing 8 different apartment '
                 'windows typical of Kyiv, Ukraine. Row 1: tall Stalin-era window, white wooden frame divided into six '
                 'panes, net curtain; tall Stalin-era double casement window with a transom, cream frame, heavy curtains; '
                 'wide three-section Soviet panel-block window with white painted wooden frames and a patterned curtain; '
                 'small square kitchen window with a white wooden frame and jars behind the glass. Row 2: white PVC window '
                 'with a mosquito net and a cat sitting behind the glass; stairwell window of a Soviet apartment block, '
                 'grey steel frame with many small panes of ribbed glass; ground-floor window behind a welded decorative '
                 'steel security grille painted white; modern floor-to-ceiling window with a thin dark grey aluminium '
                 'frame and a sheer curtain.',
                 [('w_stalin6', 1.2, 1.9), ('w_stalin2', 1.3, 2.0), ('w_panel3', 2.05, 1.5), ('w_kitchen', .9, 1.2),
                  ('w_pvc_cat', 1.3, 1.5), ('w_stair', 1.2, 1.4), ('w_grille', 1.3, 1.5), ('w_full', 1.6, 2.3)]),
    'eeu_door': (4, 2, 'Texture atlas sprite sheet: a strict grid of 4 columns and 2 rows showing 8 different doors typical '
                 'of Kyiv, Ukraine, each complete with its frame. Row 1: entrance door of a Soviet apartment block, grey '
                 'painted steel with a narrow wired-glass panel, intercom keypad and small paper notices; brown steel '
                 'security entrance door of an apartment block with a code lock; old pre-war wooden double door painted '
                 'dark green with carved panels and a glazed transom above; modern aluminium and glass entrance door with '
                 'a glazed side panel and a steel pull handle. Row 2: Soviet balcony block seen from outside: a narrow '
                 'glazed balcony door joined to a window, white painted wooden frames, net curtain; the same balcony block '
                 'in white PVC with tulle; glass shop entrance door in a white plastic frame; rusty steel basement utility '
                 'door with a padlock.',
                 [('d_steel_grey', 1.3, 2.1), ('d_steel_brown', 1.0, 2.1), ('d_old_double', 1.5, 2.9), ('d_glass', 1.9, 2.3),
                  ('d_balc_wood', 2.0, 2.2), ('d_balc_pvc', 2.0, 2.2), ('d_shop', 1.0, 2.1), ('d_basement', .9, 1.9)]),
    'eeu_balc': (2, 3, 'Texture atlas sprite sheet: a strict grid of 2 columns and 3 rows showing 6 different wide glazing '
                 'strips of enclosed apartment balconies typical of Kyiv, Ukraine, seen from the street. Each is a wide '
                 'horizontal band of window frames about three metres wide and 1.4 metres high, glazing only, without the '
                 'parapet below. Row 1: white painted wooden frames with five panes, laundry behind; white PVC sliding '
                 'panes with blinds half down. Row 2: brown wooden frames with one pane open, a bicycle and boxes behind; '
                 'aluminium sliding frames with dusty glass and curtains. Row 3: modern anthracite panoramic glazing with '
                 'thin frames; old green-painted wooden frames with small panes, flower pots behind.',
                 [('g_wood_white', 3.0, 1.4), ('g_pvc', 3.0, 1.4), ('g_wood_brown', 3.0, 1.4), ('g_alu', 3.0, 1.4),
                  ('g_dark', 3.0, 1.4), ('g_wood_green', 3.0, 1.4)]),
    'eeu_detail': (4, 2, 'Texture atlas sprite sheet: a strict grid of 4 columns and 2 rows showing 8 different facade '
                   'fittings of an apartment block in Kyiv, Ukraine. Row 1: outdoor unit of a split air conditioner, white '
                   'casing with a round fan grille; an older yellowed outdoor air conditioner unit with rust; square white '
                   'plastic ventilation grille with louvres; grey steel electrical meter cabinet with a small window. '
                   'Row 2: square panel of green-tinted glass blocks, four by four; rusty cast iron basement ventilation '
                   'grate; flat rectangular satellite television antenna panel, light grey; wall-mounted bank of six '
                   'grey steel mailboxes.',
                   [('x_ac_white', .8, .55), ('x_ac_old', .8, .55), ('x_vent', .3, .3), ('x_meter', .5, .7),
                    ('x_glassblock', .8, .8), ('x_grate', .5, .3), ('x_antenna', .6, .5), ('x_mail', .8, .6)]),
    'weu_win1': (4, 2, 'Texture atlas sprite sheet: a strict grid of 4 columns and 2 rows showing 8 different house and '
                 'apartment windows of Western Europe and North America. Row 1: white painted Georgian sash window, six '
                 'over six panes; Victorian sash window, two over two panes, cream frame, roller blind half down; American '
                 'double-hung window, white vinyl frame, horizontal blinds; cottage casement window with a dark green '
                 'wooden frame and small leaded top lights. Row 2: tall French window with grey-blue louvred shutters '
                 'folded open on both sides; tall Parisian window with a white frame and a low black wrought iron '
                 'guard rail; modern grey uPVC tilt-and-turn window with a venetian blind; German white-framed window '
                 'with a rolled-up exterior shutter box and a flower box below.',
                 [('w_sash66', 1.1, 1.8), ('w_sash22', 1.1, 1.9), ('w_hung', 1.0, 1.6), ('w_cottage', 1.2, 1.3),
                  ('w_shutters', 2.0, 2.0), ('w_paris', 1.2, 2.2), ('w_upvc', 1.2, 1.4), ('w_german', 1.3, 1.6)]),
    'weu_door': (5, 2, 'Texture atlas sprite sheet: a strict grid of 4 columns and 2 rows showing 8 different front doors '
                 'of Western Europe and North America, each complete with its frame. Row 1: British terraced house front '
                 'door painted glossy red with a brass letterbox and a semicircular fanlight above; black Georgian six '
                 'panel door with a rectangular transom light; American house front door, white, with a glazed storm '
                 'door; New York brownstone double door of dark varnished wood with glass panels and a transom. Row 2: '
                 'modern grey composite front door with a frosted glass strip; French wooden door painted grey-blue with '
                 'glass panes behind an iron grille; shop door with a glass pane in a dark green wooden frame; white '
                 'sectional garage door.',
                 # the model drew five a row: a garage door closes each
                 [('d_uk_red', 1.1, 2.6), ('d_uk_black', 1.1, 2.5), ('d_us_white', 1.0, 2.1), ('d_brownstone', 1.6, 2.8),
                  ('d_garage', 2.4, 2.1), ('d_modern', 1.0, 2.1), ('d_french', 1.1, 2.3), ('d_shop_green', 1.0, 2.2),
                  ('d_wood_brown', 1.2, 2.5), ('d_garage2', 2.4, 2.1)]),
    'med_win1': (4, 2, 'Texture atlas sprite sheet: a strict grid of 4 columns and 2 rows showing 8 different windows of old '
                 'town houses in Lisbon, Barcelona and Naples. Row 1: tall window with dark green wooden louvred shutters folded '
                 'open on both sides and a white frame; tall balcony door with a white frame and a black wrought iron railing '
                 'in front of it; window with closed brown wooden louvred shutters; small square window with a blue painted '
                 'wooden frame and a lace curtain. Row 2: tall French window with faded turquoise shutters half open and '
                 'laundry hanging below it; tall window with a grey roll-down exterior blind half lowered; arched window with '
                 'a stone-coloured surround and green shutters; modern white aluminium window with a white roller shutter box.',
                 [('m_shut_green', 2.0, 2.0), ('m_balc_rail', 1.3, 2.3), ('m_shut_brown', 1.1, 1.9), ('m_small', .85, .85),
                  ('m_shut_turq', 1.9, 2.3), ('m_blind', 1.1, 1.9), ('m_arch', 1.5, 2.2), ('m_modern', 1.2, 1.6)]),
    'med_door1': ((6, 4), 2, 'Texture atlas sprite sheet: a strict grid of 4 columns and 2 rows showing 8 different doors of old '
                  'town houses in Lisbon, Barcelona and Naples, each complete with its frame. Row 1: tall old wooden double '
                  'door painted dark green with brass knockers and a glazed fanlight; weathered blue wooden door with iron '
                  'studs; varnished brown double door with carved panels under a stone arch; shop door with glass panes in a '
                  'red wooden frame. Row 2: modern aluminium and glass apartment entrance door; garage door of horizontal '
                  'brown wooden slats; rusty green metal roller shutter of a closed shop; narrow white wooden door with a '
                  'small iron grille window.',
                  # the model drew six in the first row and four in the second
                  [('md_green', 1.6, 2.9), ('md_blue', 1.1, 2.2), ('md_brown', 1.6, 2.9), ('md_brown2', 1.6, 2.9),
                   ('md_red', 1.0, 2.2), ('md_red2', 1.0, 2.2),
                   ('md_modern', 1.4, 2.3), ('md_garage', 2.4, 2.2), ('md_shutter', 2.4, 2.4), ('md_white', .9, 2.0)]),
}
# The atlas a sheet's cells go to: Kyiv's in the first, the West's and the South's in the second.
ATLAS_OF = lambda sheet: 0 if sheet.startswith('eeu_') else 1

BAND_STYLE = (' One long straight horizontal strip running across the whole image from the left edge to the right edge, '
              'orthographic front elevation, evenly lit with soft ambient shading only, repeating regularly along its '
              'length, filling the image from top to bottom with nothing above or below it, no background, no text.')
# name: (height m, prompt)
BANDS = {
    'cornice_classic': (.55, 'Classical white-cream plaster cornice of a nineteenth century city building: stacked mouldings '
                        'with a row of small dentil blocks, slightly dusty.'),
    'cornice_stalin': (.7, 'Heavy Stalin-era Soviet neoclassical plaster cornice in pale cream: deep stepped mouldings with '
                       'a row of large rectangular modillion brackets underneath, slight grime.'),
    'cornice_plain': (.35, 'Plain painted concrete eaves slab edge of a Soviet apartment block, light grey, with dark '
                      'vertical rain streaks and a thin galvanized drip flashing along the top.'),
    'string_course': (.25, 'Simple flat plaster string course moulding of a facade, pale cream, one rounded bead along the '
                      'top and a small shadow gap below, slightly dusty.'),
    'slab_edge': (.2, 'Edge of a weathered concrete balcony slab seen from the front, light grey concrete with rust '
                  'stains, chipped corners and dark drip marks.'),
    'coping': (.2, 'Galvanized sheet metal parapet coping seen from the front, dull grey zinc with a folded drip edge, '
               'overlapping joints every metre, faint streaks.'),
    'frieze': (.6, 'Ornamental plaster frieze of an Art Nouveau Kyiv facade, pale cream, repeating relief of garlands and '
               'rosettes between two thin mouldings, soft grime in the recesses.'),
    'brick_arch': (.3, 'Soldier course of upright red-brown bricks on edge between two rows of normal bricks, grey mortar, '
                   'slight weathering.'),
}


def run(argv):
    result = subprocess.run([str(a) for a in argv], capture_output=True, text=True, encoding='utf8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'{argv[2:5]}: {result.stdout[-400:]} {result.stderr[-400:]}')


def generate(only=None, workers=4):
    """Paid fal calls for the sources that are missing. Returns what was made."""
    cli = shutil.which('um')
    if not cli:
        raise SystemExit('um (universal-modder) is required for generation')
    SRC.mkdir(parents=True, exist_ok=True)
    jobs = []
    for name, (_, _, prompt) in WALLS.items():
        if not (SRC / f'wall_{name}_color.png').exists():
            jobs.append(('wall', name, prompt))
    for name, (_, _, prompt, _) in SHEETS.items():
        if not (SRC / f'sheet_{name}.png').exists():
            jobs.append(('sheet', name, prompt))
    for name, (_, prompt) in BANDS.items():
        if not (SRC / f'band_{name}.png').exists():
            jobs.append(('band', name, prompt))
    if only:
        jobs = [j for j in jobs if j[1] in only or j[0] in only]

    def one(job):
        kind, name, prompt = job
        tmp = SRC / 'tmp' / f'{kind}_{name}'
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            if kind == 'wall':
                run([cli, 'fal', 'run', 'fal-ai/patina/material', 'prompt=' + prompt + WALL_STYLE, 'image_size=square_hd',
                     'maps:=["basecolor","normal","roughness","height"]', 'enable_prompt_expansion:=false',
                     '--out', tmp, '--name', name])
                for suffix, role in (('', 'lit'), ('_2', 'color'), ('_3', 'normal'), ('_4', 'rough'), ('_5', 'height')):
                    shutil.move(tmp / f'{name}{suffix}.png', SRC / f'wall_{name}_{role}.png')
            elif kind == 'sheet':
                run([cli, 'fal', 'image', prompt + SHEET_STYLE, '--model', 'fal-ai/nano-banana-2', '--res', '2K',
                     '--aspect', '16:9', '--out', tmp, '--name', name])
                shutil.move(tmp / f'{name}.png', SRC / f'sheet_{name}.png')
            else:
                run([cli, 'fal', 'image', prompt + BAND_STYLE, '--model', 'fal-ai/nano-banana-2', '--res', '2K',
                     '--aspect', '8:1', '--out', tmp, '--name', name])
                shutil.move(tmp / f'{name}.png', SRC / f'band_{name}.png')
            with (SRC / 'fal_manifest.jsonl').open('a', encoding='utf8') as log:
                log.write((tmp / 'fal_manifest.jsonl').read_text(encoding='utf8'))
            return f'{kind} {name}: ok'
        except Exception as error:      # one failed recipe must not lose the others
            return f'{kind} {name}: FAILED {error}'

    with ThreadPoolExecutor(workers) as pool:
        for line in pool.map(one, jobs):
            print(line, flush=True)
    return jobs


# ---------------------------------------------------------------------------------------------
# The maps. Walls: one colour and one normal map each, 1024 px. A wall that is painted (TINTS) is
# stored grey with a linear mean of GREY, and every paint is a material's baseColorFactor.
GREY = .6
BRICK_COURSE = .077            # a 65 mm brick and its joint
ROUGH = {'brick': .93, 'plaster': .94, 'concrete': .93, 'tile': .45, 'stone': .8, 'panel': .7, 'metal': .5, 'roof': .95}
TINTS = {
    'plaster_smooth': {'cream': (226, 214, 184), 'yellow': (224, 196, 128), 'peach': (226, 186, 150), 'pink': (214, 170, 160),
                       'white': (232, 230, 222), 'grey': (176, 176, 170)},
    'plaster_aged': {'yellow': (212, 186, 124), 'cream': (214, 202, 172), 'grey': (168, 166, 158), 'pink': (204, 164, 150),
                     'green': (166, 186, 160)},
    'plaster_rough': {'': (162, 160, 152)},
    'rustic': {'cream': (206, 196, 170), 'grey': (160, 158, 150)},
    'panel_pebble': {'': (168, 166, 158), 'beige': (190, 178, 152), 'warm': (176, 160, 142)},
    'panel_tile': {'': (214, 214, 206), 'blue': (150, 180, 200), 'beige': (206, 190, 156)},
    'fibre_panel': {'white': (226, 226, 220), 'grey': (150, 152, 152), 'dark': (72, 74, 78), 'orange': (204, 120, 60),
                    'green': (120, 150, 96)},
    'corrugated': {'white': (214, 214, 206), 'green': (70, 110, 84), 'blue': (84, 120, 160)},
    'asbestos': {'': (160, 160, 152), 'blue': (130, 156, 176)},
    'stucco_warm': {'cream': (226, 208, 170), 'ochre': (212, 164, 104), 'pink': (212, 158, 138)},
    'bitumen': {'': (84, 84, 88)},          # roofing felt is dark; the generated sheet came out pale
}
# Panel walls are sheets of two panels by two (a bay wide, a floor high each), their joints on
# the sheet's edges and middle: kit.lua maps them by the wall's own bays and floors.
PANELS = ('panel_pebble', 'panel_tile')
PANEL_PX, PANEL_JOINT = 2048, 9
ATLAS, SLOT, GUTTER = 4096, 512, 6
WIDE = ('eeu_balc',)             # sheets whose cells take two slots side by side
NO_GLASS = ('eeu_detail',)
# doors are matt but for these, whose panes are most of them
GLASS_DOORS = ('d_glass', 'd_shop', 'd_balc_wood', 'd_balc_pvc', 'd_shop_green', 'md_red', 'md_red2', 'md_modern')
# shutters, blinds and grilles are matt: no pane to find behind them
MATT = ('m_shut_brown', 'md_shutter', 'md_garage')
GLASS_FILL = ('g_dark',)         # the model left these panes magenta: glass, not wall
TRIM_W, TRIM_H = 4096, 2048
BAND_PX = {'cornice_classic': 256, 'cornice_stalin': 320, 'frieze': 256, 'cornice_plain': 192, 'string_course': 128,
           'slab_edge': 128, 'coping': 128, 'brick_arch': 128}
BAND_CROP = {'brick_arch': (0, .46), 'slab_edge': (.05, .95), 'coping': (.07, 1.)}       # rows kept, as shares
BAND_TRIM_X = {'slab_edge': .04}                                                        # broken ends cut off
# plain surfaces in the trim: name: (pixels, metres high, source wall or colour)
FLATS = {'concrete': (128, .5, 'concrete'), 'zinc': (96, .4, (138, 144, 148)), 'white': (96, .4, (228, 224, 212)),
         'dark': (64, .25, (44, 46, 48)), 'wood': (96, .4, (122, 92, 66))}


def ready():
    """Every source the build needs is there (they cost money to make: no silent rebuild)."""
    return (all((SRC / f'wall_{n}_color.png').exists() for n in WALLS)
            and all((SRC / f'sheet_{n}.png').exists() for n in SHEETS)
            and all((SRC / f'band_{n}.png').exists() for n in BANDS))


def wall_kinds():
    """kind -> (texture, sRGB tint or None, metres a repeat, class)."""
    out = {}
    for name, (metres, cls, _) in WALLS.items():
        tints = TINTS.get(name)
        if not tints:
            out[name] = (name, None, metres, cls)
        else:
            for tint, rgb in tints.items():
                out[name + ('_' + tint if tint else '')] = (name, rgb, metres, cls)
    return out


def _linear(a):
    a = a / 255.
    return np.where(a <= .04045, a / 12.92, ((a + .055) / 1.055) ** 2.4)


def _encode(a):
    a = np.clip(a, 0, 1)
    return np.where(a <= .0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - .055) * 255


def courses(height):
    """Brick courses down a square map: the strongest period of its row means."""
    rows = height.mean(axis=1)
    spectrum = np.abs(np.fft.rfft(rows - rows.mean()))
    return int(np.argmax(spectrum[8:80]) + 8)


def _blur(a, radius):
    return np.asarray(Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius)), dtype=np.float64) / 255


def _panels(lin, normal):
    """A sheet of 2 x 2 precast panels from a surface: the surface four times across, each panel
    its own shade, a sealed joint round each with the rain's grey under it."""
    size, half = PANEL_PX, PANEL_PX // 2
    tile = size // 4

    def tiled(a, mode):
        im = Image.fromarray(a.astype(np.uint8)).resize((tile, tile), Image.LANCZOS)
        out = Image.new(mode, (size, size))
        for x in range(0, size, tile):
            for y in range(0, size, tile):
                out.paste(im, (x, y))
        return np.asarray(out, dtype=np.float64)

    grey = tiled(_encode(lin), 'RGB') / 255
    lin = _linear(grey * 255)
    normal = tiled(normal, 'RGB')
    yy, xx = np.mgrid[0:size, 0:size]
    for k, shade in enumerate((1., .94, 1.04, .97)):
        lin[(yy // half == k // 2) & (xx // half == k % 2)] *= shade
    # distance to the nearest joint line, and the joint as a groove
    dx = np.minimum(xx % half, half - xx % half).astype(np.float64)
    dy = np.minimum(yy % half, half - yy % half).astype(np.float64)
    d = np.minimum(dx, dy)
    groove = np.clip(d / PANEL_JOINT, 0, 1)                 # 0 in the joint, 1 on the panel
    lin *= (.3 + .7 * groove ** 2)[..., None]
    # under a horizontal joint the panel is washed darker, fading over 30 cm
    below = (yy % half).astype(np.float64)
    lin *= (1 - .1 * np.exp(-below / 90.))[..., None]
    gy, gx = np.gradient(_blur(groove, 2.5))
    n = normal / 127.5 - 1
    n[..., 0] -= gx * 9
    n[..., 1] += gy * 9
    n /= np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-4)
    return lin, (n * .5 + .5) * 255


def wall_maps(name):
    """(colour, normal, metres) of one wall as the game wants a wall: the delit colour with its
    joints shaded a little, the normal green up (OpenGL), both upside down (a wall's v runs up),
    the metres from the brick courses where there are any."""
    metres, cls, _ = WALLS[name]
    colour = np.asarray(Image.open(SRC / f'wall_{name}_color.png').convert('RGB'), dtype=np.float64)
    height = np.asarray(Image.open(SRC / f'wall_{name}_height.png').convert('L'), dtype=np.float64) / 255
    normal = np.asarray(Image.open(SRC / f'wall_{name}_normal.png').convert('RGB'), dtype=np.float64)
    if cls == 'brick':
        metres = round(courses(height) * BRICK_COURSE, 2)
    # the joints and pits a shade darker: the delit colour alone reads as a print
    cavity = np.clip(1 + (height - _blur(height, 6)) * 1.6, .72, 1.08)[..., None]
    lin = _linear(colour) * cavity
    if name in TINTS:
        grey = lin @ np.array([.2126, .7152, .0722])
        lin = np.repeat((grey * GREY / grey.mean())[..., None], 3, axis=2)
    # green up follows +dh/dy down the image's rows
    gy = np.gradient(height, axis=0)
    if float(((normal[..., 1] - 127.5) * gy).sum()) < 0:
        normal[..., 1] = 255 - normal[..., 1]
    if name in PANELS:
        lin, normal = _panels(lin, normal)
        metres = 6.0
    colour = _encode(lin)
    flip = Image.FLIP_TOP_BOTTOM
    return (Image.fromarray(colour.astype(np.uint8)).transpose(flip), Image.fromarray(normal.astype(np.uint8)).transpose(flip), metres)


def _runs(mask, least):
    """[start, end) runs of True at least `least` long."""
    out, start = [], None
    for k, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = k
        elif not v and start is not None:
            if k - start >= least:
                out.append((start, k))
            start = None
    return out


def cut_sheet(name):
    """The cells of one sheet as [(cell, RGB array, background mask, width m, height m)]."""
    cols, rows, _, cells = SHEETS[name]
    im = np.asarray(Image.open(SRC / f'sheet_{name}.png').convert('RGB')).astype(np.int32)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    bg = (r > 150) & (b > 150) & (g < 120) & ((r + b) // 2 - g > 70)
    bands = _runs((~bg).mean(axis=1) > .02, 40)
    bands = sorted(sorted(bands, key=lambda q: q[0] - q[1])[:rows])
    if len(bands) != rows:
        raise ValueError(f'{name}: {len(bands)} rows of cells, expected {rows}')
    out, k = [], 0
    for row, (y0, y1) in enumerate(bands):
        want = cols[row] if isinstance(cols, tuple) else cols
        spans = _runs((~bg[y0:y1]).mean(axis=0) > .02, 40)
        spans = sorted(sorted(spans, key=lambda q: q[0] - q[1])[:want])
        if len(spans) != want:
            raise ValueError(f'{name}: {len(spans)} cells in a row, expected {want}')
        for x0, x1 in spans:
            # tight on the object, then two pixels in: the edge is blended with the magenta
            part = ~bg[y0:y1, x0:x1]
            ys, xs = np.where(part.mean(axis=1) > .04)[0], np.where(part.mean(axis=0) > .04)[0]
            cy0, cy1, cx0, cx1 = y0 + ys[0] + 3, y0 + ys[-1] - 2, x0 + xs[0] + 3, x0 + xs[-1] - 2
            cell, w, h = cells[k]
            out.append((cell, im[cy0:cy1, cx0:cx1].astype(np.uint8), bg[cy0:cy1, cx0:cx1], w, h))
            k += 1
    return out


def _dilate(mask, n):
    im = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * n + 1))
    return np.asarray(im) > 127


def cell_maps(cell, rgb, bg, glass=True):
    """(colour, glass mask 0..1) of one cell at the slot's inner size."""
    h, w = bg.shape
    fill_glass = cell in GLASS_FILL
    out = rgb.astype(np.float64)
    # the magenta and what it has bled into: pink pixels within a few of it
    pink = (out[..., 0] + out[..., 2]) / 2 - out[..., 1] > 34
    hole = _dilate(bg, 1) | (_dilate(bg, 4) & pink)
    if fill_glass:
        ramp = np.linspace(1.15, .8, h)[:, None, None]
        out[hole] = (np.array([58., 66, 76])[None, None, :] * ramp).repeat(w, 1)[hole]
    else:
        out[hole] = (206, 200, 188)
    mask = np.zeros((h, w))
    if glass:
        # the frame is what looks like the object's rim; lace as white as the frame stays matt
        m = max(3, int(min(h, w) * .03))
        rim = np.zeros((h, w), bool)
        rim[:m], rim[-m:], rim[:, :m], rim[:, -m:] = True, True, True, True
        ring = out[rim & ~hole]
        frame_colour = np.median(ring, axis=0) if len(ring) else np.array([200., 200, 200])
        dist = np.sqrt(((out - frame_colour) ** 2).sum(axis=2))
        pane = (dist > 52) & ~rim & (out.min(axis=2) < 205)
        pane &= ~hole if not fill_glass else True
        if fill_glass:
            pane |= hole
        mask = np.asarray(Image.fromarray((pane * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.6)), dtype=np.float64) / 255
    return out.astype(np.uint8), mask


def atlas(index=0):
    """(colour, roughness, metal, {cell: (u0, v0, u1, v1, w m, h m, atlas)}) of the cells of the
    sheets that go to atlas `index`."""
    n = ATLAS // SLOT
    colour = np.full((ATLAS, ATLAS, 3), 128, np.uint8)
    glass = np.zeros((ATLAS, ATLAS))
    used = np.zeros((n, n), bool)
    table = {}
    for sheet in SHEETS:
        if ATLAS_OF(sheet) != index:
            continue
        span = 2 if sheet in WIDE else 1
        for cell, rgb, bg, wm, hm in cut_sheet(sheet):
            spot = next(((row, col) for row in range(n) for col in range(n - span + 1) if not used[row, col:col + span].any()), None)
            if spot is None:
                raise ValueError('the cell atlas is full')
            row, col = spot
            used[row, col:col + span] = True
            door = cell[:2] == 'd_' or cell[:3] == 'md_'
            pic, mask = cell_maps(cell, rgb, bg, glass=sheet not in NO_GLASS and cell not in MATT and (not door or cell in GLASS_DOORS))
            w, h = SLOT * span - 2 * GUTTER, SLOT - 2 * GUTTER
            pic = np.asarray(Image.fromarray(pic).resize((w, h), Image.LANCZOS))
            mask = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR), dtype=np.float64) / 255
            x, y = col * SLOT, row * SLOT
            colour[y:y + SLOT, x:x + SLOT * span] = np.pad(pic, ((GUTTER, GUTTER), (GUTTER, GUTTER), (0, 0)), mode='edge')
            glass[y:y + SLOT, x:x + SLOT * span] = np.pad(mask, GUTTER, mode='edge')
            table[cell] = (round((x + GUTTER + .5) / ATLAS, 5), round((y + GUTTER + .5) / ATLAS, 5),
                           round((x + SLOT * span - GUTTER - .5) / ATLAS, 5), round((y + SLOT - GUTTER - .5) / ATLAS, 5), wm, hm, index)
    rough = (.82 - .72 * glass) * 255
    half = (ATLAS // 2, ATLAS // 2)
    return (Image.fromarray(colour), Image.fromarray(rough.astype(np.uint8)).convert('RGB').resize(half, Image.BILINEAR),
            Image.fromarray((glass * 255).astype(np.uint8)).convert('RGB').resize(half, Image.BILINEAR), table)


def _period(a):
    """Columns of `a` to keep so its right end meets its left: the best match of the first strip
    in the last quarter (a cornice's dentils repeat; cut on a whole number of them)."""
    h, w, _ = a.shape
    grey = a.mean(axis=2)
    strip = min(256, w // 16)
    first = grey[:, :strip]
    best, at = None, w
    for x in range(int(w * .72), w - strip, 2):
        err = float(((grey[:, x:x + strip] - first) ** 2).mean())
        if best is None or err < best:
            best, at = err, x
    return at


def band_strip(name, px):
    """One band as a TRIM_W x px strip that repeats along its length, and its metres a repeat."""
    hm, _ = BANDS[name]
    a = np.asarray(Image.open(SRC / f'band_{name}.png').convert('RGB'), dtype=np.float64)
    h, w, _ = a.shape
    y0, y1 = BAND_CROP.get(name, (0, 1))
    a = a[int(h * y0):int(h * y1)]
    # the model leaves a white or black margin above and below some strips
    rows = a.reshape(a.shape[0], -1)
    blank = ((rows.mean(axis=1) > 244) | (rows.mean(axis=1) < 8)) & (rows.std(axis=1) < 9)
    keep = np.where(~blank)[0]
    a = a[keep[0]:keep[-1] + 1]
    cut = int(w * BAND_TRIM_X.get(name, 0))
    a = a[:, cut:w - cut] if cut else a
    a = a[:, :_period(a)]
    h, w, _ = a.shape
    # a short cross-fade over what the cut did not match
    fade = min(48, w // 20)
    t = np.linspace(0, 1, fade)[None, :, None]
    a[:, :fade] = a[:, :fade] * t + a[:, -fade:] * (1 - t)
    a = a[:, :w - fade]
    length = hm * a.shape[1] / a.shape[0]
    return Image.fromarray(a.astype(np.uint8)).resize((TRIM_W, px), Image.LANCZOS), hm, length


def trim():
    """(colour, {band: (v0, v1, metres high, metres a repeat)}): the bands, then the plain surfaces."""
    sheet = np.zeros((TRIM_H, TRIM_W, 3), np.uint8)
    table, y, g = {}, 0, 4
    rng = np.random.default_rng(4012)

    def put(name, strip, hm, length):
        nonlocal y
        px = strip.height
        body = np.asarray(strip.resize((TRIM_W, px - 2 * g), Image.LANCZOS))
        sheet[y:y + px] = np.pad(body, ((g, g), (0, 0), (0, 0)), mode='edge')
        table[name] = (round((y + g + .5) / TRIM_H, 5), round((y + px - g - .5) / TRIM_H, 5), hm, round(length, 3))
        y += px

    for name, px in BAND_PX.items():
        put(name, *band_strip(name, px))
    for name, (px, hm, source) in FLATS.items():
        if isinstance(source, str):
            tile = Image.open(SRC / f'wall_{source}_color.png').convert('RGB').resize((512, 512), Image.LANCZOS)
            strip = Image.new('RGB', (TRIM_W, px))
            for x in range(0, TRIM_W, 512):
                strip.paste(tile.crop((0, 0, 512, px)), (x, 0))
        else:
            # paint or sheet metal: the colour with a soft mottle that repeats along the strip
            noise = rng.normal(0, 1, (px // 4 + 1, TRIM_W // 4))
            noise = np.asarray(Image.fromarray(((noise * 40) + 128).clip(0, 255).astype(np.uint8)).resize((TRIM_W, px), Image.BICUBIC), dtype=np.float64) - 128
            body = np.array(source, dtype=np.float64)[None, None, :] + noise[..., None] * .16
            strip = Image.fromarray(body.clip(0, 255).astype(np.uint8))
        put(name, strip, hm, hm * TRIM_W / px)
    return Image.fromarray(sheet), table


def lua_text(cells, bands, walls):
    def row(values):
        return '{' + ', '.join(f'{v:g}' for v in values) + '}'
    lines = ['-- Generated by earthng/kit_art.py (--lua): the kit atlas as built. Do not edit.',
             f'return {{version = {VERSION},',
             '  -- cell = {u0, v0, u1, v1, metres wide, metres high, atlas}; v0 is the top; atlas 1 is kit_cells2',
             '  cells = {']
    lines += [f'    {name} = {row(v)},' for name, v in sorted(cells.items())]
    lines += ['  },', '  -- band = {v of its top, v of its foot, metres high, metres a repeat}', '  bands = {']
    lines += [f'    {name} = {row(v)},' for name, v in sorted(bands.items())]
    lines += ['  },', '  -- wall kind (e2rf_kw_<kind>) = metres a repeat', '  walls = {']
    lines += [f'    {name} = {v:g},' for name, v in sorted(walls.items())]
    lines += ['  },', '}', '']
    return '\n'.join(lines)


def build(real, lua=False):
    """Write every kit map into the art root's real/ folder (PNG; the caller makes the DDS).
    With lua=True also rewrite kit_cells.lua from what was built."""
    real = Path(real)
    real.mkdir(parents=True, exist_ok=True)
    metres = {}
    for name in WALLS:
        colour, normal, m = wall_maps(name)
        colour.save(real / f'kw_{name}.color.png')
        normal.save(real / f'kw_{name}.normal.png')
        metres[name] = m
    cells = {}
    for index, name in enumerate(('kit_cells', 'kit_cells2')):
        colour, rough, metal, table = atlas(index)
        colour.save(real / f'{name}.color.png')
        rough.save(real / f'{name}_r.data.png')
        metal.save(real / f'{name}_m.data.png')
        cells.update(table)
    sheet, bands = trim()
    sheet.save(real / 'kit_trim.color.png')
    walls = {kind: metres[tex] for kind, (tex, _, _, _) in wall_kinds().items()}
    (real / 'kit.version').write_text(VERSION)
    if lua:
        LUA.write_text(lua_text(cells, bands, walls), encoding='utf8', newline='\n')
    return cells, bands, walls


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--build', type=Path, help='write the maps (PNG) into this folder and refresh kit_cells.lua')
    p.add_argument('--generate', action='store_true', help='explicitly make paid fal calls for missing sources')
    p.add_argument('--only', nargs='+', help='recipe names or kinds (wall, sheet, band)')
    p.add_argument('--list', action='store_true')
    a = p.parse_args()
    if a.list:
        print(len(WALLS), 'walls,', len(SHEETS), 'sheets,', len(BANDS), 'bands')
    if a.generate:
        generate(a.only)
    if a.build:
        cells, bands, walls = build(a.build, lua=True)
        print(len(cells), 'cells,', len(bands), 'bands,', len(walls), 'wall kinds ->', a.build)


if __name__ == '__main__':
    main()
