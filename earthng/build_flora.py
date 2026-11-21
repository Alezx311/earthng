"""The flora pack of a region: FoliMesh models as the game's trees, in a mod ZIP of their own.

    python earthng/build_flora.py --region ukraine                 # convert what is fetched, pack it
    python earthng/build_flora.py --region ukraine --fetch 20      # export up to 20 more models first

The recipe (earthng/flora/<region>.json) names the species of a region with their FoliMesh slug,
seed and age. earthng/folimesh.py exports each model once into data/folimesh/ (the user's key,
one download each); earthng/flora_mesh.py turns it into a Collada shape with the game's levels of
detail. This script does that for every fetched model of the recipe and writes

    data/flora/<region>/art/shapes/earthng/flora/...     shapes, textures, materials
    data/flora/<region>/art/shapes/earthng/flora/flora.json   species -> models (flora.lua reads it)
    out/flora/earthng_flora.zip                          the mod: beside earthng_planet.zip in mods/

The planet works without the pack (the game's own trees stand in), and takes a species' own
models as soon as the pack has them. Nothing of it is in Git: the FoliMesh licence (4b) does not
allow the models in an open repository; packed into the mod's archive they are distributed with it.
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
import flora_mesh  # noqa: E402
import folimesh  # noqa: E402

DATA = ROOT / 'data' / 'flora'
ZIP = 'earthng_flora.zip'
NOTICE = """EarthNG flora pack

Vegetation created with FoliMesh (https://folimesh.com), a procedural vegetation generator by
individual entrepreneur Voliansky Filipp Andriyovych, Kyiv. The models are licensed to the
maker of this pack under the FoliMesh License Agreement (https://folimesh.com/license) for use
inside EarthNG. They are not to be extracted, redistributed or resold separately from it.
"""


def build(region, cache=folimesh.CACHE, data=DATA, say=print):
    """Convert every fetched model of the region's recipe; returns (pack folder, manifest)."""
    recipe = folimesh.recipe(region)
    pack = Path(data) / region
    art = pack / flora_mesh.ROOT.lstrip('/')
    if art.exists():
        shutil.rmtree(art)
    species = {}
    missing = 0
    for model in folimesh.wanted(recipe):
        plant = recipe['species'][model['name']]
        source = Path(cache) / f"{folimesh.slug_of(model['species'], model['seed'], model['age'], model['style'])}.glb"
        if not source.exists():
            missing += 1
            continue
        group = plant.get('group', 'trees')
        # a shape's name: the recipe's species and the variant
        name = model['name'] + source.stem[len(model['species'].replace('-', '_')):]
        try:
            entry = flora_mesh.convert(source, pack, model['name'], name, group)
        except (ValueError, KeyError, OSError) as error:
            say(f'  {source.name}: {error}')
            continue
        entry.update(seed=model['seed'], age=model['age'])
        one = species.setdefault(model['name'], {'latin': plant.get('latin', ''), 'uk': plant.get('uk', ''),
                                                 'slug': plant['slug'], 'group': group, 'layer': plant.get('layer'),
                                                 'models': []})
        one['models'].append(entry)
        say(f"  {entry['shape']}  {entry['height']:.1f} m  {entry['triangles']}")
    manifest = {'schema': 1, 'region': region, 'source': recipe.get('source', 'FoliMesh'), 'species': species}
    art.mkdir(parents=True, exist_ok=True)
    (art / 'flora.json').write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding='utf8')
    (art / 'NOTICE.txt').write_text(NOTICE, encoding='utf8')
    models = sum(len(s['models']) for s in species.values())
    say(f'{region}: {models} models of {len(species)} species; {missing} of the recipe not fetched yet')
    return pack, manifest


def pack_zip(pack, out):
    """The pack folder as a mod ZIP: art/ at its root."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as z:
        for src in sorted((Path(pack) / 'art').rglob('*')):
            if src.is_file():
                # textures are compressed already
                stored = src.suffix.lower() in ('.png', '.dds', '.jpg')
                z.write(src, src.relative_to(pack).as_posix(), compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
    temporary.replace(out)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--region', default='ukraine')
    parser.add_argument('--fetch', type=int, metavar='N', help='export up to N missing models first (one download each)')
    parser.add_argument('--reserve', type=int, default=0, help='downloads to leave on the balance')
    parser.add_argument('--out', type=Path, default=ROOT / 'out' / 'flora' / ZIP)
    a = parser.parse_args()
    if a.fetch:
        try:
            folimesh.fetch(folimesh.Client(), a.region, a.fetch, a.reserve)
        except folimesh.FoliMeshError as error:
            raise SystemExit(f'FoliMesh: {error}')
    pack, manifest = build(a.region)
    if not manifest['species']:
        raise SystemExit(f'no models to pack: fetch some first (python earthng/build_flora.py --region {a.region} --fetch 10)')
    print(pack_zip(pack, a.out))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    main()
