"""The flora pack's shapes as the game cooks them: its compiled shapes and imposters, kept and shipped.

    python earthng/flora_cook.py out/flora/game-04 [more runs ...]     # harvest test runs
    python earthng/flora_cook.py --list                                # what is cooked, what is not
    python earthng/flora_cook.py --forget game-06                      # a run that cooked its shapes wrong

A cook run is a test run with --cook-flora: the landing loads every shape of the pack (its
materials first), so the game cooks whatever the pack does not ship yet.

The game turns a Collada shape into its own `.cdae` the first time it meets it (0.2-0.7 s of a
frame for a pack model) and bakes the billboard a far tree is drawn as (`<shape>.dae.imposter.dds`
and `..._normals.dds`, 1-2 s). Its own levels ship both beside every tree. Ours did not, and on
21.11 the baking in the middle of a landing reset the graphics device in three runs of five
("The GPU stopped responding", out/flora/game-02, -03, -05; never the same shape): a pack whose
shapes bake at run time cannot be given to a player.

So the shapes are cooked here, once: a test run (earthng/test_world.py with the pack) leaves what
the game made under its profile's temp/, this tool copies it into data/flora/cooked/ with the
hash of the Collada file it was made from, and earthng/build_flora.py puts it beside the shape
when the hash still matches. A crashed run's finished shapes are as good as any. Like the models,
the cooked files are not in Git.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PACK = ROOT / 'data' / 'flora' / 'all'
STORE = ROOT / 'data' / 'flora' / 'cooked'
# beside <name>.dae: its compiled shape and its two imposter sheets
PARTS = ('{stem}.cdae', '{stem}.dae.imposter.dds', '{stem}.dae.imposter_normals.dds')
NEEDED = PARTS[1:]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def index(store=STORE):
    file = Path(store) / 'index.json'
    return json.loads(file.read_text(encoding='utf8')) if file.exists() else {}


def shapes(pack=PACK):
    """Every shape of the pack: (path relative to the pack, file)."""
    pack = Path(pack)
    return [(dae.relative_to(pack).as_posix(), dae) for dae in sorted(pack.rglob('*.dae'))]


def harvest(run, pack=PACK, store=STORE, say=print):
    """Take what a test run's game cooked of the pack's shapes. Returns the shapes taken."""
    temp = Path(run) / 'user' / 'current' / 'temp'
    known, taken = index(store), []
    for rel, dae in shapes(pack):
        folder, stem = temp / Path(rel).parent, dae.stem
        files = {part: folder / part.format(stem=stem) for part in PARTS}
        # a bake that did not finish leaves nothing or an empty file
        if not all(files[part].exists() and files[part].stat().st_size > 1024 for part in NEEDED):
            continue
        sha = digest(dae)
        have = known.get(rel)
        if have and have['dae'] == sha and len(have['files']) == len(PARTS):
            continue
        target = Path(store) / Path(rel).parent
        target.mkdir(parents=True, exist_ok=True)
        kept = []
        for part, source in files.items():
            if source.exists() and source.stat().st_size > 1024:
                shutil.copyfile(source, target / source.name)
                kept.append(source.name)
        known[rel] = {'dae': sha, 'files': kept, 'run': Path(run).name}
        taken.append(rel)
    Path(store).mkdir(parents=True, exist_ok=True)
    (Path(store) / 'index.json').write_text(json.dumps(dict(sorted(known.items())), indent=1), encoding='utf8')
    say(f'{Path(run).name}: {len(taken)} shapes taken')
    return taken


def serve(pack=PACK, store=STORE):
    """Put the cooked files beside the pack's shapes they were made from. Returns (cooked, raw):
    the shapes that have their imposters and those the game would still bake."""
    known, cooked, raw = index(store), [], []
    for rel, dae in shapes(pack):
        have = known.get(rel)
        if not have or have['dae'] != digest(dae):
            raw.append(rel)
            continue
        for name in have['files']:
            shutil.copyfile(Path(store) / Path(rel).parent / name, dae.parent / name)
        cooked.append(rel)
    return cooked, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('runs', nargs='*', type=Path, help='folders of earthng/test_world.py runs (their --out)')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--forget', metavar='RUN', help="drop what was taken from this run (its shapes were cooked wrong)")
    a = parser.parse_args()
    if a.forget:
        known = index()
        gone = [rel for rel, entry in known.items() if entry.get('run') == a.forget]
        for rel in gone:
            for name in known.pop(rel)['files']:
                (STORE / Path(rel).parent / name).unlink(missing_ok=True)
        (STORE / 'index.json').write_text(json.dumps(dict(sorted(known.items())), indent=1), encoding='utf8')
        print(f'forgot {len(gone)} shapes of {a.forget}')
    for run in a.runs:
        harvest(run)
    known = index()
    fresh = {rel: digest(dae) for rel, dae in shapes()}
    cooked = [rel for rel, sha in fresh.items() if known.get(rel, {}).get('dae') == sha]
    raw = [rel for rel in fresh if rel not in cooked]
    print(f'{len(cooked)} of {len(fresh)} shapes cooked; {len(raw)} the game would bake')
    if a.list or len(raw) <= 40:
        for rel in raw:
            print('  raw', rel.rsplit('/', 1)[-1])


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    main()
