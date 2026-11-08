"""Stage the player downloads: the planet, ready country packs and EarthNG.exe built from committed
code (prepare_app.py). Never publishes anything or touches a game profile."""
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
def source_snapshot(ref):
    commit = subprocess.check_output(['git', 'rev-parse', ref], cwd=ROOT, text=True).strip()
    data = subprocess.check_output(['git', 'archive', '--format=zip', commit], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = {n: archive.read(n) for n in archive.namelist() if not n.endswith('/')}
    return commit, files


def _script_name(value):
    """'build_country.py' or 'earthng/build_country.py' -> 'build_country'; anything else -> None."""
    if not value.endswith('.py') or any(c.isspace() for c in value):
        return None
    return value.replace('\\', '/').rsplit('/', 1)[-1][:-3]


def builder_files(files, start=('app_service', 'osm_tiles_country')):
    """Follow local imports and scripts started by file name (HERE / 'build_country.py')."""
    pending = list(start)
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
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # country_fetch runs build_map.py and build_country.py as subprocesses, which no
                # import names; without this the release shipped without build_country.py.
                script = _script_name(node.value)
                imports = [script] if script else []
            else:
                continue
            pending.extend(m for m in imports if f'earthng/{m}.py' in files
                           and f'earthng/{m}.py' not in selected)
    # the planet's Lua, for country_fetch.refresh_planet from committed mod code
    selected.update(n for n in files if n.startswith('mod/'))
    selected.update(('requirements-fast.txt', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'earthng/fast_tree_materials.json'))
    return {name: files[name] for name in sorted(selected)}


NATIVE = ('earthng-mapbuilder.exe', 'earthng_native.dll')


def _cargo():
    found = shutil.which('cargo')
    home = Path.home() / '.cargo' / 'bin' / 'cargo.exe'
    return found or (str(home) if home.is_file() else None)


def rust_notices(lock_text):
    """Name, version and licence of every crate rust/Cargo.lock pulls from crates.io, from the
    registry sources cargo unpacked when it built them."""
    import tomllib
    lock = tomllib.loads(lock_text)
    registry = Path.home() / '.cargo' / 'registry' / 'src'
    lines = ['Rust crates compiled into bin/earthng-mapbuilder.exe and bin/earthng_native.dll', '']
    for package in sorted(lock.get('package', []), key=lambda p: (p['name'], p['version'])):
        if 'source' not in package:
            continue           # the workspace's own crates: MIT, LICENSE
        licence = 'see crates.io'
        for manifest in registry.glob(f"*/{package['name']}-{package['version']}/Cargo.toml"):
            meta = tomllib.loads(manifest.read_text(encoding='utf-8')).get('package', {})
            licence = meta.get('license') or (f"file {meta['license-file']}" if meta.get('license-file') else licence)
            break
        lines.append(f"{package['name']} {package['version']}: {licence} (https://crates.io/crates/{package['name']})")
    return ('\n'.join(lines) + '\n').encode('utf-8')


def native_files(commit, source):
    """bin/ of the runtime: the Rust tools (docs/MAPBUILDER_RS.md) built from the snapshot's own
    rust/, or {} for a snapshot without it. The build runs in this checkout, so it must be that
    commit with rust/ unchanged; Python falls back to its own steps where bin/ is absent."""
    if 'rust/Cargo.lock' not in source:
        return {}
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--', 'rust'], cwd=ROOT, text=True).strip()
    if head != commit or dirty:
        raise ValueError('the native tools are built from this checkout: check out the release ref with rust/ '
                         'unchanged, or pass --no-native')
    cargo = _cargo()
    if cargo is None:
        raise ValueError('cargo not found (https://rustup.rs), or pass --no-native')
    subprocess.run([cargo, 'build', '--release', '--locked'], cwd=ROOT / 'rust', check=True)
    files = {f'bin/{name}': (ROOT / 'rust' / 'target' / 'release' / name).read_bytes() for name in NATIVE}
    files['bin/THIRD_PARTY_RUST.txt'] = rust_notices(source['rust/Cargo.lock'].decode('utf-8'))
    return files


def check_planet(planet):
    with zipfile.ZipFile(planet) as archive:
        manifest = json.loads(archive.read('earthng/planet/manifest.json'))
        if manifest.get('runtime') != 'lua':
            raise ValueError('release requires the native planet')
        if any(name.startswith(('content/', 'python/')) for name in archive.namelist()):
            raise ValueError('unexpected game/runtime files in planet')


def ready_packs(countries, release_url=RELEASE_URL):
    """earthng/ready_packs.json for the runtime: the country packs published beside the exe."""
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
    return {'packs': packs}


def prepare(planet, countries, out, ref='HEAD', release_url=RELEASE_URL, native=True):
    import prepare_app             # it imports this module: imported here, not at the top
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError('use an empty output directory so old assets cannot enter the release')
    check_planet(planet)
    packs = ready_packs(countries, release_url)
    out.mkdir(parents=True, exist_ok=True)
    target, info, _ = prepare_app.build(out, ref, native,
                                        extra={'earthng/ready_packs.json': json.dumps(packs, indent=2).encode('utf-8')})
    if info['planetVersion'] != planet_version(planet):
        raise ValueError(f"the exe expects planet {info['planetVersion']}, {Path(planet).name} is {planet_version(planet)}")
    for path in [Path(planet), *map(Path, countries)]:
        shutil.copyfile(path, out / path.name)
    for path in sorted([*out.glob('*.zip'), target]):
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        print(f'{digest}  {path.name}')
    print(f"Source: {info['sourceCommit']}\nOutput: {out.resolve()}")


def planet_version(planet):
    with zipfile.ZipFile(planet) as archive:
        return json.loads(archive.read('earthng/planet/manifest.json')).get('version')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--planet', type=Path, required=True)
    parser.add_argument('--country', type=Path, action='append', default=[])
    parser.add_argument('--ref', default='HEAD', help='committed source snapshot for EarthNG.exe')
    parser.add_argument('--release-url', default=RELEASE_URL, help='download URL prefix for ready packs')
    parser.add_argument('--no-native', action='store_true', help='leave out bin/ (the Rust tools): every step in Python')
    args = parser.parse_args()
    prepare(args.planet, args.country, args.out, args.ref, args.release_url, native=not args.no_native)


if __name__ == '__main__':
    main()
