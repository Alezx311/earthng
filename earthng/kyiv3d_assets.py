"""Reproducible fal asset recipes for the Irpinska / Chornobylska prototype.

Paid generation is explicit (``--generate``). Inputs and downloaded originals stay
in out/; um records the endpoint, seed, request id and files in fal_manifest.jsonl.
These are regional artistic reconstructions, not surveyed replicas of the shops.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STYLE = (
    ' Photorealistic high fidelity PBR 3D game asset reference, precise straight architectural proportions, '
    'meticulous near-camera detail, realistic slightly weathered materials, maintained everyday Kyiv neighborhood. '
    'Entire single object in gentle three-quarter front-right view, front is the wide face. '
    'Neutral diffuse overcast studio illumination, no strong baked sun or directional shadows. '
    'Isolated on pure white background, no ground plane or ground shadow, no people, cars or surroundings. '
    'Roof and bottom fully visible with generous white margin. Not a diorama, not cartoon, no exploded parts.'
)

# dimensions are prototype targets in metres, not measurements of the real objects.
ASSETS = {
    'bakery': {'size': [6.5, 3.6, 3.2], 'seed': 21431, 'prompt':
        'Single Ukrainian street bakery pavilion, cream painted metal panels, burgundy trim, shallow flat roof '
        'with galvanized coping and rain streaks. Wide recessed bread shop window, narrow glass entrance door, '
        'individual loaves and warm wooden shelves visible inside, glazed counter, fascia sign ХЛІБ, '
        'roller shutter housing, fine rubber window seals, ventilation grille, small opening hours sticker.'},
    'coffee': {'size': [2.65, 2.65, 3.05], 'seed': 21432, 'prompt':
        'Compact contemporary Ukrainian coffee-to-go kiosk, charcoal vertical corrugated metal, warm oak '
        'service counter and mint green accents, open serving hatch with a professional chrome espresso '
        'machine, stacked paper cups, grinder and pastry display inside. Broad roof fascia reads КАВА in '
        'simple warm-white lettering, tiny menu panel, round exterior light, timber shelf, narrow side door. '
        'A single square 2.6 metre kiosk, no tables or loose items outside its footprint.'},
    'pharmacy': {'size': [7, 2.65, 3.15], 'seed': 21433, 'prompt':
        'Single-storey Ukrainian neighborhood pharmacy retail pavilion module 7 metres wide, 2.7 metres deep, '
        '3 metres high. Clean pale grey composite wall panels, green fascia with Ukrainian text ГАЛА АПТЕКА '
        'and a small green pharmacy cross. Broad shop windows with shelves of small medicine boxes visible '
        'behind glass, glass entrance door, stainless handrail at one small threshold, closed technical '
        'side panel and external ventilation grille. Fine aluminum mullions, realistic dark rubber seals.'},
    'flowers': {'size': [5.4, 5.7, 3.2], 'seed': 21434, 'prompt':
        'Kyiv flower shop pavilion, wide charcoal aluminum framed glazing, flat warm-grey metal roof with '
        'small overhang, black fascia sign КВІТИ. Behind the front glass are densely arranged individual '
        'pink and cream roses, white chrysanthemums, yellow sunflowers, foliage, clear glass and silver '
        'metal flower buckets on stepped stands, small handwritten price cards, charcoal walls, ceiling '
        'track lights, warm oak low bench. One glass door with long steel pull handle. This is a complete '
        'single small rectangular flower shop, 5 metres wide and 5 metres deep, not an entire street.'},
    'produce': {'size': [3.5, 1.8, 2.7], 'seed': 21435, 'prompt':
        'One Ukrainian neighborhood market produce stall, open front, faded olive metal rear panel and '
        'dark green canvas awning on thin square steel posts. Three stepped wooden display shelves with '
        'individual black and green crates full of red tomatoes, cucumbers, yellow peppers, apples, '
        'potatoes and onions, small plain handwritten price cards. Digital weighing scale on counter. '
        'Weathered timber edges, detailed canvas seams and folds. Single stall, all goods contained under '
        'the 3.5 metre wide awning, no detached items or floor.'},
    'flower_display': {'size': [1.5, .7, 1.25], 'seed': 21436, 'prompt':
        'A single freestanding florist outdoor display rack, two tiers of weathered oak shelves on thin '
        'black powder-coated steel frame. Eight individual galvanized silver buckets packed with distinct '
        'cream roses, pink peonies, white daisies, yellow sunflowers and green foliage; folded kraft paper '
        'bouquet wraps, fine stems, petal layers and leaves. Small black handwritten price cards in '
        'Ukrainian hryvnia. Rack 1.5 metres wide, 0.7 deep and 1.25 high. No surrounding shop, no floor.'},
    'aircon': {'size': [.85, .36, .62], 'seed': 21437, 'prompt':
        'A single realistic wall-mounted outdoor split air conditioner condenser, off-white weathered '
        'enameled metal casing, large circular fan behind dense dark concentric wire grille, fine '
        'ventilation slots, fasteners and folded casing seams. Two galvanized steel L brackets under it '
        'and a short insulated copper pipe pair at right. Appliance 85 centimetres wide, no wall, no '
        'building, no detached parts. This one compact exterior HVAC unit with its mounting brackets.'},
    'balcony': {'size': [2.8, 1.05, 2.6], 'seed': 21438, 'prompt':
        'One enclosed Kyiv late Soviet apartment balcony module, shallow concrete slab, lower parapet '
        'clad in faded cream corrugated metal, upper glazing in individual white PVC frames, three '
        'front window panes and one narrow pane on each return side, one partly open casement, curtains '
        'and a couple of small plant pots behind glazing. Thin galvanized roof cap and rain streaks, '
        'realistic window profiles and silicone joints. Front 2.8 metres wide, 1 metre projecting '
        'depth and 2.6 metres high. Flat mounting back, no surrounding building and no wall plane.'},
    'entry': {'size': [3.5, 1.7, 3.5], 'seed': 21439, 'prompt':
        'Single Kyiv apartment entrance porch module, rectangular weathered concrete portal, recessed '
        'dark green steel security door with narrow wired-glass strip, intercom and mail stickers, '
        'shallow corrugated metal canopy on two simple steel brackets, two concrete steps, small steel '
        'handrails, modest entrance light and small blue Ukrainian address plate. All parts attached '
        'in one compact module 3.5 metres wide, 1.7 deep and 3.5 high. Flat back for mounting against '
        'an apartment facade. No surrounding apartment block, no free-standing wall behind it.'},
    'copycentre': {'size': [7, 5.5, 3.2], 'seed': 21440, 'prompt':
        'One Kyiv neighborhood copy and print shop single storey pavilion, rectangular 7 metre frontage '
        'and 5 metre depth, white aluminum composite panels, medium blue fascia sign КОПІЦЕНТР. '
        'Wide glass front with printer and photocopier visible inside, blue-framed glass entrance door, '
        'small color sample posters, roller shutter housing, subtly weathered flat metal roof, '
        'electrical meter box and conduit neatly mounted on side, realistic seals and metal profiles.'},
}


def run(argv):
    print('Running:', ' '.join(str(a) for a in argv[:5]), flush=True)
    subprocess.run([str(a) for a in argv], check=True)


def provenance(generated):
    """Keep reproducibility alongside the shipped art, without temporary URLs or local paths."""
    manifest = generated / 'fal_manifest.jsonl'
    if not manifest.exists():
        return
    rows = [json.loads(line) for line in manifest.read_text(encoding='utf8').splitlines() if line.strip()]
    result = {'schema': 'earthng-generated-city-art-v1',
              'site': {'lat': 50.45973330892563, 'lon': 30.34628920171671},
              'evidence': 'OSM footprints; artistic regional appearance, not surveyed replicas', 'assets': {}}
    for name, recipe in ASSETS.items():
        mesh = ROOT / 'mod/art/shapes/earthng/kyiv3d' / name / 'mesh.json'
        if not mesh.exists():
            continue
        record = {'target_size_m': recipe['size'], 'steps': []}
        for row in rows:
            if row.get('name') != name:
                continue
            inputs = dict(row.get('input') or {})
            for key in ('image_url', 'image_urls'):
                if key in inputs:
                    inputs[key] = name + '.png'
            record['steps'].append({k: row[k] for k in ('endpoint', 'request_id', 'seed', 't') if k in row}
                                   | {'input': inputs})
        for ext in ('png', 'glb'):
            path = generated / f'{name}.{ext}'
            if path.exists():
                record[f'{ext}_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        result['assets'][name] = record
    dest = ROOT / 'mod/art/shapes/earthng/kyiv3d/provenance.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--out', type=Path, default=ROOT / 'out/kyiv-first-person-3d/generated')
    p.add_argument('--only', nargs='+', choices=ASSETS)
    p.add_argument('--generate', action='store_true', help='explicitly make paid fal calls for missing assets')
    p.add_argument('--convert', action='store_true', help='convert existing GLBs into the mod')
    a = p.parse_args()
    names = a.only or list(ASSETS)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'recipes.json').write_text(json.dumps(ASSETS, ensure_ascii=False, indent=2), encoding='utf8')
    cli = shutil.which('um')
    if a.generate and not cli:
        p.error('um is required for generation')
    for name in names:
        spec = ASSETS[name]
        image, mesh = a.out / f'{name}.png', a.out / f'{name}.glb'
        if a.generate:
            if not image.exists():
                run([cli, 'fal', 'image', spec['prompt'] + STYLE, '--model', 'fal-ai/nano-banana-2',
                     '--res', '2K', '--aspect', '1:1', '--seed', spec['seed'], '--out', a.out, '--name', name])
            if not mesh.exists():
                run([cli, 'fal', 'model3d', image, '--engine', 'trellis2', '--texture', '2048',
                     '--faces', '60000', '--set', 'resolution:=1536', '--set', f'seed:={spec["seed"]}',
                     '--set', 'ss_sampling_steps:=20', '--set', 'shape_slat_sampling_steps:=20',
                     '--set', 'tex_slat_sampling_steps:=20', '--out', a.out, '--name', name])
        if a.convert:
            if not mesh.exists():
                raise FileNotFoundError(mesh)
            from fal_mesh import convert
            target = ROOT / 'mod/art/shapes/earthng/kyiv3d' / name
            convert(mesh, target, name=name, size=spec['size'])
        print(name, 'mesh ready' if mesh.exists() else 'recipe only', flush=True)
    if a.convert:
        provenance(a.out)


if __name__ == '__main__':
    main()
