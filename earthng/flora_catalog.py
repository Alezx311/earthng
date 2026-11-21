"""What FoliMesh can grow: every species of its catalogue with the size and the triangles of its model.

    python earthng/flora_catalog.py            # ask for what is not in the table yet
    python earthng/flora_catalog.py --show     # print the table

list_species and get_stats cost nothing (earthng/folimesh.py), so the whole catalogue is measured
before a download is spent on any of it: a recipe (earthng/flora/<region>.json) is then written
from heights and triangle counts, not from names. The table is out/flora/catalog/stats.json; it
holds no model.
"""
import argparse
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import folimesh  # noqa: E402

TABLE = ROOT / 'out' / 'flora' / 'catalog' / 'stats.json'


def load(path=TABLE):
    return json.loads(Path(path).read_text(encoding='utf8')) if Path(path).exists() else {'species': {}}


def row(species, stats):
    """One line of the table from a get_stats reply."""
    lods = stats.get('lods') or []
    return {'name': species.get('name'), 'category': species.get('category'), 'height': stats.get('heightM'),
            'triangles': [lod.get('triangles') for lod in lods], 'distances': [lod.get('distanceM') for lod in lods],
            'bark': [lod.get('bark') for lod in lods], 'leaves': [lod.get('leaves') for lod in lods],
            'leaf': lods[0].get('leafType') if lods else None, 'ms': stats.get('generationMs')}


def measure(client, table, pause=1.2, say=print, save=None):
    """Fill the table with every species it lacks. Returns how many were asked."""
    asked = 0
    listed = client.species()
    items = listed.get('items', listed) if isinstance(listed, dict) else listed
    for species in items:
        slug = species['slug']
        if slug in table['species'] and 'error' not in table['species'][slug]:
            continue
        try:
            table['species'][slug] = row(species, client.stats(slug))
        except folimesh.FoliMeshError as error:
            table['species'][slug] = {'name': species.get('name'), 'category': species.get('category'), 'error': str(error)}
            say(f'  {slug}: {error}')
        asked += 1
        if save and asked % 10 == 0:
            save(table)
        time.sleep(pause)
    return asked


def show(table, say=print):
    by = {}
    for slug, one in table['species'].items():
        by.setdefault(one.get('category'), []).append((slug, one))
    for category, rows in by.items():
        say(f'{category} ({len(rows)})')
        for slug, one in rows:
            if 'error' in one:
                say(f'  {slug:20s} {one["error"][:80]}')
                continue
            say(f'  {slug:20s} {one["height"] or 0:6.2f} m  {one["leaf"] or "":8s} '
                + ' / '.join(str(t) for t in one['triangles']))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--show', action='store_true')
    a = parser.parse_args()
    table = load()
    if not a.show:
        def save(t):
            TABLE.parent.mkdir(parents=True, exist_ok=True)
            TABLE.write_text(json.dumps(t, indent=1, ensure_ascii=False), encoding='utf8')
        try:
            asked = measure(folimesh.Client(), table, save=save)
        except folimesh.FoliMeshError as error:
            raise SystemExit(f'FoliMesh: {error}')
        save(table)
        print(f'{asked} species measured, {len(table["species"])} in {TABLE}')
    show(table)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    main()
