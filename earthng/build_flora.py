"""The flora pack: FoliMesh models as the game's plants, in a mod ZIP of their own.

    python earthng/build_flora.py                       # every recipe: convert what is fetched, pack it
    python earthng/build_flora.py --fetch 20            # export up to 20 more models first
    python earthng/build_flora.py --region ukraine      # one recipe alone

A recipe (earthng/flora/<region>.json) names the species of a part of the world with their
FoliMesh slug, seed and age. earthng/folimesh.py exports each model once into data/folimesh/ (the
user's key, one download each); earthng/flora_mesh.py turns it into a Collada shape with the
game's levels of detail. This script does that for every fetched model of the recipes and writes

    data/flora/<pack>/art/shapes/earthng/flora/...          shapes, textures, materials
    data/flora/<pack>/art/shapes/earthng/flora/flora.json   species -> models (flora.lua reads it)
    out/flora/earthng_flora.zip                             the mod: beside earthng_planet.zip in mods/
    out/flora/blocks.json                                   the same list without the models: what
                                                            there is to build with, by place and layer

A shape goes into the pack with what the game cooked of it (its compiled .cdae and its imposter
sheets, earthng/flora_cook.py) where a test run has left that: the game's own levels ship both,
and a pack that bakes its imposters at a landing reset the graphics device (flora_cook.py). The
build says how many shapes are still raw.

<pack> is the recipe's name, or `all` for every recipe in one pack (the default: the planet reads
one manifest). The planet works without the pack (the game's own trees stand in), and takes a
species' own models as soon as the pack has them. Nothing of it is in Git: the FoliMesh licence
(4b) does not allow the models in an open repository; packed into the mod's archive they are
distributed with it.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import flora_cook  # noqa: E402
import flora_mesh  # noqa: E402
import folimesh  # noqa: E402

DATA = ROOT / 'data' / 'flora'
ZIP = 'earthng_flora.zip'
STAMP = (2026, 11, 21, 0, 0, 0)
NOTICE = """EarthNG flora pack

Vegetation created with FoliMesh (https://folimesh.com), a procedural vegetation generator by
individual entrepreneur Voliansky Filipp Andriyovych, Kyiv. The models are licensed to the
maker of this pack under the FoliMesh License Agreement (https://folimesh.com/license) for use
inside EarthNG. They are not to be extracted, redistributed or resold separately from it.
"""


def shape_name(model, plant, source):
    """A shape's name: the recipe's species, another slug's own name where a variant has one,
    and the variant (seed, age)."""
    own = model['species'].replace('-', '_')
    variant = source.stem[len(own):]
    return model['name'] + ('_' + own if model['species'] != plant['slug'] else '') + variant


def build(region='all', cache=folimesh.CACHE, data=DATA, say=print, hero=True):
    """Convert every fetched model of a recipe (or of all of them); returns (pack folder, manifest)."""
    names = folimesh.regions() if region == 'all' else [region]
    pack = Path(data) / region
    art = pack / flora_mesh.ROOT.lstrip('/')
    if art.exists():
        shutil.rmtree(art)
    species = {}
    missing = 0
    for one in names:
        recipe = folimesh.recipe(one)
        for model in folimesh.wanted(recipe):
            plant = recipe['species'][model['name']]
            source = Path(cache) / f"{folimesh.slug_of(model['species'], model['seed'], model['age'], model['style'])}.glb"
            if not source.exists():
                missing += 1
                continue
            group = plant.get('group', 'trees')
            try:
                entry = flora_mesh.convert(source, pack, model['name'], shape_name(model, plant, source), group, hero=hero)
            except (ValueError, KeyError, OSError) as error:
                say(f'  {source.name}: {error}')
                continue
            entry.update(seed=model['seed'], age=model['age'], slug=model['species'])
            kept = species.setdefault(model['name'], {
                'latin': plant.get('latin', ''), 'uk': plant.get('uk', ''), 'slug': plant['slug'], 'group': group,
                'layer': plant.get('layer'), 'use': plant.get('use', []), 'region': one, 'models': []})
            kept['models'].append(entry)
            say(f"  {entry['shape'].rsplit('/', 1)[-1]:34s} {entry['height']:6.2f} m  {entry['triangles']}  a{entry['lods']}")
    cooked, raw = flora_cook.serve(pack) if region == 'all' else ([], [])
    manifest = {'schema': 2, 'region': region, 'regions': names, 'source': 'FoliMesh (folimesh.com), realistic style',
                'cooked': len(cooked), 'raw': len(raw), 'species': species}
    art.mkdir(parents=True, exist_ok=True)
    (art / 'flora.json').write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding='utf8')
    (art / 'NOTICE.txt').write_text(NOTICE, encoding='utf8')
    models = sum(len(s['models']) for s in species.values())
    say(f'{region}: {models} models of {len(species)} species; {missing} of the recipes not fetched yet')
    if region == 'all':
        say(f'cooked: {len(cooked)} shapes; raw (the game would bake them at a landing): {len(raw)}'
            + (': ' + ', '.join(rel.rsplit('/', 1)[-1][:-4] for rel in raw[:40]) if raw else ''))
    return pack, manifest


def blocks(manifest):
    """The pack as a list of building blocks, a model each, without anything of the model itself:
    {id, species, uk, latin, layer, use, height, radius, triangles}. The constructor's catalogue."""
    out = []
    for name, plant in manifest['species'].items():
        for model in plant['models']:
            out.append({'id': model['shape'].rsplit('/', 1)[-1][:-4], 'species': name, 'uk': plant.get('uk', ''),
                        'latin': plant.get('latin', ''), 'group': plant.get('group'), 'layer': plant.get('layer') or 'canopy',
                        'use': plant.get('use', []), 'region': plant.get('region'), 'height': model['height'],
                        'radius': model['radius'], 'triangles': model['triangles'], 'shape': model['shape']})
    out.sort(key=lambda b: (b['region'] or '', b['layer'], b['species'], b['id']))
    return out


def pack_zip(pack, out):
    """The pack folder as a mod ZIP: art/ at its root. A texture goes in as its DDS alone where
    it has one (the game reads `name.color.dds` for a material's `name.color.png`)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as z:
        for src in sorted((Path(pack) / 'art').rglob('*')):
            if not src.is_file() or (src.suffix.lower() == '.png' and src.with_suffix('.dds').exists()):
                continue
            # textures are compressed already
            stored = src.suffix.lower() in ('.png', '.jpg')
            # one date for every file, as in the game's own archives: a shape newer than its
            # compiled copy or its imposter is cooked again
            entry = zipfile.ZipInfo(src.relative_to(pack).as_posix(), date_time=STAMP)
            entry.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            with src.open('rb') as data:
                z.writestr(entry, data.read())
    temporary.replace(out)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--region', default='all', help="a recipe of earthng/flora/, or 'all' (the default)")
    parser.add_argument('--fetch', type=int, metavar='N', help='export up to N missing models first (one download each)')
    parser.add_argument('--reserve', type=int, default=0, help='downloads to leave on the balance')
    parser.add_argument('--no-hero', action='store_true', help="leave every model's level 0 out (a lighter pack)")
    parser.add_argument('--out', type=Path, default=ROOT / 'out' / 'flora' / ZIP)
    a = parser.parse_args()
    if a.fetch:
        try:
            folimesh.fetch(folimesh.Client(), a.region, a.fetch, a.reserve)
        except folimesh.FoliMeshError as error:
            raise SystemExit(f'FoliMesh: {error}')
    pack, manifest = build(a.region, hero=not a.no_hero)
    if not manifest['species']:
        raise SystemExit('no models to pack: fetch some first (python earthng/build_flora.py --fetch 10)')
    listing = a.out.with_name('blocks.json')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    listing.write_text(json.dumps(blocks(manifest), indent=1, ensure_ascii=False), encoding='utf8')
    print(pack_zip(pack, a.out))
    print(listing)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    main()
