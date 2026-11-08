"""Build EarthNG.exe: the window (rust/crates/app) with its runtime appended (docs/MAPBUILDER_APP.md).

    .venv\\Scripts\\python.exe earthng\\prepare_app.py --out out\\release\\app

The runtime ZIP holds the embedded CPython (python.org's embeddable package), the packages of
requirements-fast.txt as wheels for it, the pipeline files the service imports (from a committed
snapshot, like prepare_release.py), mod/, the native tools and app/ui. The exe unpacks it once
per version into %LOCALAPPDATA%\\EarthNG\\runtime. Never publishes anything.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import prepare_release  # noqa: E402

PYTHON_VERSION = '3.13.2'          # the .venv's: its wheels (cp313) and the embeddable build match
PYTHON_URL = f'https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip'
CACHE = ROOT / 'data' / 'app-build'
MAGIC = b'EARTHNG-RUNTIME1'        # rust/crates/app/src/runtime.rs
# python313._pth: the embedded interpreter ignores PYTHONPATH and the script's own folder, so the
# pipeline (scripts start each other by file name) is put on the path here.
PTH = 'python313.zip\n.\nLib\\site-packages\n..\\earthng\nimport site\n'


def embedded_python(cache=CACHE):
    """python.org's embeddable CPython, downloaded once into data/app-build."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / Path(PYTHON_URL).name
    if not path.is_file():
        print(f'downloading {PYTHON_URL}')
        part = path.with_suffix('.part')
        with urllib.request.urlopen(PYTHON_URL, timeout=120) as response, part.open('wb') as out:
            shutil.copyfileobj(response, out)
        part.replace(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f'{path.name}: sha256 {digest}')
    return path


def site_packages(requirements, cache=CACHE):
    """requirements installed as win_amd64 cp313 wheels into a folder (pip --target)."""
    target = cache / f'site-packages-{hashlib.sha256(requirements.encode()).hexdigest()[:12]}'
    if not (target / '.complete').is_file():
        shutil.rmtree(target, ignore_errors=True)
        req = cache / 'requirements.txt'
        req.write_text(requirements, encoding='utf-8')
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check',
                        '--only-binary=:all:', '--platform', 'win_amd64', '--python-version', '3.13',
                        '--implementation', 'cp', '--target', str(target), '-r', str(req)], check=True)
        (target / '.complete').write_text('ok')
    return target


def planet_version(source):
    text = source['earthng/build_mod.py'].decode('utf-8')
    found = re.search(r"'kind': 'earthng-planet', 'version': '([\d.]+)'", text)
    if not found:
        raise ValueError('build_mod.py: planet version not found')
    return found.group(1)


def runtime_files(ref='HEAD', native=True, extra=None):
    """{name in the runtime ZIP: bytes} of the pipeline from a committed snapshot; extra: files the
    release adds (earthng/ready_packs.json)."""
    commit, source = prepare_release.source_snapshot(ref)
    files = prepare_release.builder_files(source)
    files.update({n: data for n, data in source.items() if n.startswith('app/ui/')})
    if 'earthng/app_service.py' not in files or 'app/ui/index.html' not in files:
        raise ValueError(f'{ref} has no app_service.py or app/ui: commit them first')
    if native:
        files.update(prepare_release.native_files(commit, source))
    info = {'version': app_version(source), 'sourceCommit': commit, 'planetVersion': planet_version(source),
            'python': PYTHON_VERSION}
    files.update(extra or {})
    files['BUILD_INFO.json'] = json.dumps(info, indent=2).encode('utf-8')
    return info, files


def app_version(source):
    text = source['rust/crates/app/Cargo.toml'].decode('utf-8')
    return re.search(r'^version = "([^"]+)"', text, re.M).group(1)


def build_runtime_zip(files, python_zip, packages):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        with zipfile.ZipFile(python_zip) as embedded:
            for info in embedded.infolist():
                name = info.filename
                if name.endswith('._pth'):
                    archive.writestr(f'python/{name}', PTH)
                else:
                    archive.writestr(f'python/{name}', embedded.read(info))
        for path in sorted(packages.rglob('*')):
            rel = path.relative_to(packages).as_posix()
            if path.is_file() and rel != '.complete' and '/__pycache__/' not in f'/{rel}':
                archive.write(path, f'python/Lib/site-packages/{rel}')
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return out.getvalue()


def append_runtime(exe, payload, target):
    digest = hashlib.sha256(payload).digest()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('wb') as out:
        out.write(Path(exe).read_bytes())
        out.write(payload)
        out.write(digest)
        out.write(len(payload).to_bytes(8, 'little'))
        out.write(MAGIC)
    return digest.hex()


def build(out, ref='HEAD', native=True, extra=None):
    """out/EarthNG.exe from the snapshot ref: the window built by cargo, the runtime appended."""
    info, files = runtime_files(ref, native, extra)
    cargo = prepare_release._cargo()
    if cargo is None:
        raise SystemExit('cargo not found (https://rustup.rs)')
    subprocess.run([cargo, 'build', '--release', '--locked', '-p', 'app'], cwd=ROOT / 'rust', check=True)
    requirements = (ROOT / 'requirements-fast.txt').read_text(encoding='utf-8')
    payload = build_runtime_zip(files, embedded_python(), site_packages(requirements))
    target = Path(out) / 'EarthNG.exe'
    digest = append_runtime(ROOT / 'rust' / 'target' / 'release' / 'EarthNG.exe', payload, target)
    print(f"EarthNG.exe {info['version']} ({info['sourceCommit'][:7]}, planet {info['planetVersion']}): "
          f"{target.stat().st_size / 2**20:.1f} MB, runtime {len(payload) / 2**20:.1f} MB, sha256 {digest[:16]}")
    return target, info, digest


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--ref', default='HEAD', help='committed source snapshot of the pipeline')
    p.add_argument('--no-native', action='store_true', help='leave out bin/ (every step in Python)')
    a = p.parse_args()
    target, _, _ = build(a.out, a.ref, native=not a.no_native)
    print(f'Output: {target.resolve()}')


if __name__ == '__main__':
    main()
