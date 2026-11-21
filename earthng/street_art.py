"""A town's walking surfaces that neither the game nor the CC0 sets have: the grey concrete
block paving of a Ukrainian sidewalk and the old cracked asphalt of a yard's footpath.

  python earthng/street_art.py --generate      # paid: the sources that are missing
  python earthng/street_art.py --sheet out/street-art.jpg

The sources are made with fal (PATINA, a material from a prompt: colour, normal, roughness and
height at 1024 px) and kept in data/textures/street: paid, so made once and not in Git. A
checkout without them has no such materials (ready() is false: fast_style leaves the kinds out
and the generator keeps the game's concrete sidewalk). build() writes the maps of the real pack.
"""
import argparse
import shutil
import subprocess
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / 'data' / 'textures' / 'street'
VERSION = '1'           # change whenever a map this module writes changes
STYLE = (' Seamless tileable material texture photographed perfectly straight-on from directly above, orthographic, '
         'flat even overcast light, no shadows, no perspective, no objects, no leaves, no markings.')
# kind: (metres a repeat, roughness of the whole sheet where the map is not used, prompt)
MATERIALS = {
    'sidewalk_tile': (2.4, .9, 'Worn grey concrete block paving of an Eastern European city sidewalk in the "old town" '
                               'pattern: small vibro-pressed concrete pavers, rectangles and squares of three sizes laid '
                               'in straight rows, light grey with a few darker and a few sand-stained blocks, fine sand and '
                               'dust in the narrow joints, some chipped corners, slightly uneven.'),
    # (the first prompt, "pale grey asphalt with coarse exposed gravel, a network of cracks", gave a
    # plain pale sheet with a few dots: the cracks have to be the subject)
    'sidewalk_asphalt': (3.0, .95, 'Heavily cracked old asphalt pavement, medium dark grey bitumen with small stones showing, '
                                   'covered edge to edge by an irregular alligator pattern of deep dark cracks, some cracks '
                                   'wider with sand and tiny weeds in them, one rectangular patch of darker newer asphalt, '
                                   'rough and dusty.'),
}


def ready():
    """Every source is there (a checkout that has not paid for them has no street art)."""
    return all((SRC / f'{name}_{role}.png').exists() for name in MATERIALS for role in ('color', 'normal', 'rough'))


def generate(only=None):
    """Paid fal calls for the sources that are missing. Returns what was made."""
    cli = shutil.which('um')
    if not cli:
        raise SystemExit('um (universal-modder) is required for generation')
    SRC.mkdir(parents=True, exist_ok=True)
    made = []
    for name, (_, _, prompt) in MATERIALS.items():
        if (only and name not in only) or (SRC / f'{name}_color.png').exists():
            continue
        tmp = SRC / 'tmp' / name
        tmp.mkdir(parents=True, exist_ok=True)
        subprocess.run([cli, 'fal', 'run', 'fal-ai/patina/material', 'prompt=' + prompt + STYLE, 'image_size=square_hd',
                        'maps:=["basecolor","normal","roughness","height"]', 'enable_prompt_expansion:=false',
                        '--out', str(tmp), '--name', name], check=True)
        for suffix, role in (('', 'lit'), ('_2', 'color'), ('_3', 'normal'), ('_4', 'rough'), ('_5', 'height')):
            shutil.move(tmp / f'{name}{suffix}.png', SRC / f'{name}_{role}.png')
        log = tmp / 'fal_manifest.jsonl'
        if log.exists():
            with (SRC / 'fal_manifest.jsonl').open('a', encoding='utf8') as out:
                out.write(log.read_text(encoding='utf8'))
        made.append(name)
        print(f'{name}: ok', flush=True)
    return made


def build(real, size=1024):
    """The maps of every kind as PNGs in `real` (the real pack's folder; fast_art turns them into
    DDS): <kind>.color.png, <kind>.normal.png (green flipped: the game's normals are DirectX's) and
    <kind>.data.png (roughness)."""
    for name in MATERIALS:
        Image.open(SRC / f'{name}_color.png').convert('RGB').resize((size, size), Image.LANCZOS).save(real / f'{name}.color.png')
        r, g, b = Image.open(SRC / f'{name}_normal.png').convert('RGB').resize((size, size), Image.LANCZOS).split()
        Image.merge('RGB', (r, g.point(lambda v: 255 - v), b)).save(real / f'{name}.normal.png')
        Image.open(SRC / f'{name}_rough.png').convert('L').resize((size, size), Image.LANCZOS).convert('RGB').save(real / f'{name}.data.png')
    (real / 'street.version').write_text(VERSION)


def sheet(path, repeats=2):
    """The colour maps side by side, each tiled `repeats` times: how a seam shows."""
    names = [n for n in MATERIALS if (SRC / f'{n}_color.png').exists()]
    px = 384
    out = Image.new('RGB', (len(names) * (px * repeats + 8), px * repeats), (20, 20, 20))
    for k, name in enumerate(names):
        tile = Image.open(SRC / f'{name}_color.png').convert('RGB').resize((px, px), Image.LANCZOS)
        for i in range(repeats):
            for j in range(repeats):
                out.paste(tile, (k * (px * repeats + 8) + i * px, j * px))
    out.save(path, quality=88)
    return names


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--generate', action='store_true', help='paid: make the missing sources with fal')
    ap.add_argument('--only', nargs='*')
    ap.add_argument('--sheet', type=Path)
    a = ap.parse_args()
    if a.generate:
        print('made:', generate(a.only))
    if a.sheet:
        print('sheet of', sheet(a.sheet))
    print('ready' if ready() else 'sources missing in ' + str(SRC))
