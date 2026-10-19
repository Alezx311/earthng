"""Stage three player downloads from committed code; never publish or modify a game profile."""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE_URL = 'https://github.com/Alezx311/earthng/releases/download/EarthNG'
BUILDER_README = r"""EarthNG Map Builder — Windows

Want to play the included demo?
Put earthng_planet.zip and the demo country's ZIP in your BeamNG user folder's
mods directory. Keep both ZIPs packed. Open Freeroam > EarthNG - Planet.
Map Builder and Python are only needed to make or download other map packs.

Ready maps — no generation or Python needed
Ukraine (2.96 GB):
https://drive.google.com/file/d/1WriRBq6pBBjSUyySV81RMgzRViK83NpJ/view
All ready country maps:
https://drive.google.com/drive/folders/1n3A-msXrJtuQ2qJKn7YqzCooLZyliKMy?usp=drive_link
Download the individual country's ZIP, keep it packed and place it in mods
beside earthng_planet.zip. Always get the planet ZIP from GitHub Releases.
If Drive creates a wrapper ZIP when downloading several files, extract that
wrapper first; the earthng_<country>.zip files inside must remain packed.
Map Builder also has a Download ready maps (Google Drive) button.

Build your own map
1. Install Python 3.13 from https://www.python.org/downloads/windows/
   Include Tcl/Tk and the Python launcher in the installer.
2. Extract this entire archive to a writable folder. Do not run it inside ZIP.
3. Double-click MapBuilder.bat. First launch runs Setup.bat to install packages.
4. Select your BeamNG user folder (the folder containing mods).
5. Choose a country/region or select an area on the map, then Build my own.
   Wait for the installed message. The result is also in out/country-setup.
6. Restart BeamNG after adding or replacing a map ZIP.

Install earthng_planet.zip first: it supplies the offline map, city labels,
preview materials and the game's runtime. Internet is required for initial
setup and new source data. Large regions can take hours and many GB of disk.
Stop cancels a build before installation; the window waits for its worker.

If the window does not open, run Setup.bat and read the error. To see Python
errors, open a terminal here and run:
  .venv\Scripts\python.exe earthng/country_ui.py

Uninstall: delete this extracted folder. Generated packs already installed in
BeamNG remain in mods; remove their ZIPs there if no longer wanted.
This experimental release was tested with BeamNG.drive 0.39.4 on Windows.
OSM coverage and performance vary. No multiplayer compatibility is claimed.

Code: MIT (LICENSE). Data and assets: THIRD_PARTY_NOTICES.md.
Release packaging assisted by OpenAI Codex.
Source and issues: https://github.com/Alezx311/earthng
"""


def source_snapshot(ref):
    commit = subprocess.check_output(['git', 'rev-parse', ref], cwd=ROOT, text=True).strip()
    data = subprocess.check_output(['git', 'archive', '--format=zip', commit], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = {n: archive.read(n) for n in archive.namelist() if not n.endswith('/')}
    return commit, files


def builder_files(files):
    """Follow local imports, including worker functions and the subprocess entry point."""
    pending = ['country_ui', 'osm_tiles_country']
    selected = set()
    while pending:
        module = pending.pop()
        name = f'earthng/{module}.py'
        if name in selected:
            continue
        selected.add(name)
        for node in ast.walk(ast.parse(files[name].decode('utf-8-sig'))):
            if isinstance(node, ast.Import):
                imports = [a.name.split('.')[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports = [node.module.split('.')[0]]
            else:
                continue
            pending.extend(m for m in imports if f'earthng/{m}.py' in files
                           and f'earthng/{m}.py' not in selected)
    # Supports the existing Refresh planet code button, using committed mod code.
    selected.update(n for n in files if n.startswith('mod/'))
    selected.update(('MapBuilder.bat', 'Setup.bat', 'requirements-fast.txt',
                     'LICENSE', 'THIRD_PARTY_NOTICES.md', 'earthng/fast_tree_materials.json'))
    return {name: files[name] for name in sorted(selected)}


def prepare(planet, countries, out, ref='HEAD', release_url=RELEASE_URL):
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError('use an empty output directory so old assets cannot enter the release')
    commit, source = source_snapshot(ref)
    with zipfile.ZipFile(planet) as archive:
        manifest = json.loads(archive.read('earthng/planet/manifest.json'))
        if manifest.get('runtime') != 'lua':
            raise ValueError('release requires the native planet')
        if any(name.startswith(('content/', 'python/')) for name in archive.namelist()):
            raise ValueError('unexpected game/runtime files in planet')
    packs = []
    for country in countries:
        with zipfile.ZipFile(country) as archive:
            names = [n for n in archive.namelist()
                     if n.startswith('earthng/countries/') and len(n.split('/')) == 4
                     and n.endswith('/manifest.json')]
            if len(names) != 1:
                raise ValueError(f'{country}: expected one country manifest')
            manifest = json.loads(archive.read(names[0]))
            if manifest.get('runtime') != 'native':
                raise ValueError(f'{country}: expected a native country')
            if Path(country).name != f"earthng_{manifest['id']}.zip":
                raise ValueError('country filename must match its manifest id')
            packs.append({'id': manifest['id'], 'title': manifest['title'],
                          'url': release_url.rstrip('/') + '/' + Path(country).name})
    files = builder_files(source)
    files['README.txt'] = BUILDER_README.encode('utf-8')
    files['earthng/ready_packs.json'] = json.dumps({'packs': packs}, indent=2).encode('utf-8')
    files['BUILD_INFO.json'] = json.dumps({'sourceCommit': commit}, indent=2).encode('utf-8')
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out / 'EarthNG-MapBuilder.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    for path in [Path(planet), *map(Path, countries)]:
        shutil.copyfile(path, out / path.name)
    for path in sorted(out.glob('*.zip')):
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        print(f'{digest}  {path.name}')
    print(f'Source: {commit}\nOutput: {out.resolve()}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--planet', type=Path, required=True)
    parser.add_argument('--country', type=Path, action='append', required=True)
    parser.add_argument('--ref', default='HEAD', help='committed source snapshot for Map Builder')
    parser.add_argument('--release-url', default=RELEASE_URL, help='download URL prefix for ready packs')
    args = parser.parse_args()
    prepare(args.planet, args.country, args.out, args.ref, args.release_url)


if __name__ == '__main__':
    main()
