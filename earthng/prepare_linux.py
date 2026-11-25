"""Build the Linux package of EarthNG: EarthNG-linux-x86_64.tar.gz (docs/LINUX.md).

    python earthng/prepare_linux.py --out out/release/linux --planet <earthng_planet.zip> [--test]

The same runtime as EarthNG.exe (prepare_app.runtime_files: the pipeline, app/ui, mod/, BUILD_INFO)
around a Linux interpreter instead of the Windows window:

    EarthNG/
      EarthNG                 launcher: python/bin/python3 earthng/app_web.py (the page in the browser)
      python/                 CPython 3.13 from python-build-standalone + requirements-fast wheels
      bin/                    earthng-mapbuilder, libearthng_native.so (rust/, without the window crate)
      earthng/ app/ui/ mod/   from the committed snapshot --ref
      earthng_planet.zip      the planet (optional, as in the exe)

The Linux parts are built in Docker (quay.io/pypa/manylinux_2_28_x86_64: glibc 2.28, so the
binaries run on Ubuntu 20.04+, Debian 11+, Fedora, Arch and SteamOS). The tarball itself is written
here with tarfile, which keeps the executable bits and symlinks a Windows disk would lose.
--test also runs the Rust tests and the Python unit tests on Linux with the packaged interpreter.
A Docker volume (earthng-linux-cache) keeps rustup, crates, the target folder and downloads.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import prepare_app  # noqa: E402
import prepare_release  # noqa: E402

IMAGE = 'quay.io/pypa/manylinux_2_28_x86_64'
VOLUME = 'earthng-linux-cache'
# python-build-standalone (Astral): relocatable CPython, the same idea as the Windows embeddable build
PYTHON_URL = ('https://github.com/astral-sh/python-build-standalone/releases/download/20261110/'
              'cpython-3.13.18%2B20261110-x86_64-unknown-linux-gnu-install_only.tar.gz')
PYTHON_SHA256 = '50c774f6674740739f791c05a9177ed03e2fe02abebda9bca3512eb7309b37cc'
PYTHON_VERSION = '3.13.18'
NATIVE = ('earthng-mapbuilder', 'libearthng_native.so')
TOP = 'EarthNG'
PACKAGE = 'EarthNG-linux-x86_64.tar.gz'

LAUNCHER = '''#!/bin/sh
# EarthNG for Linux: opens the Map Builder in your browser (docs/LINUX.md in the repository).
# Data: ~/.local/share/EarthNG/data. Stop with Ctrl+C, or close the page: it ends on its own.
HERE="$(cd "$(dirname "$0")" && pwd)"
unset PYTHONHOME PYTHONPATH
# the bundled interpreter's OpenSSL looks in /etc/ssl: point it at this distribution's CA bundle
if [ -z "${SSL_CERT_FILE:-}" ]; then
  for f in /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/cert.pem /etc/ssl/ca-bundle.pem; do
    if [ -r "$f" ]; then export SSL_CERT_FILE="$f"; break; fi
  done
fi
exec "$HERE/python/bin/python3" -X utf8 "$HERE/earthng/app_web.py" "$@"
'''

README = '''EarthNG {version} for Linux
==========================

1. Unpack this folder anywhere (for example ~/EarthNG) and run ./EarthNG
   (from a terminal, or double-click it and choose "Run").
2. The Map Builder opens in your browser. It finds BeamNG.drive's user folder of the native
   Linux client (~/.local/share/BeamNG/BeamNG.drive/current) or of the Windows build under
   Steam Proton (steamapps/compatdata/284160/pfx/.../AppData/Local/BeamNG/BeamNG.drive/current).
   If it does not, choose the folder in Settings.
3. Create a map. The planet and your map are installed into the game's mods folder.
4. In BeamNG.drive open Freeroam -> EarthNG - Planet.

Downloads, tiles and built packs live in ~/.local/share/EarthNG/data, logs in
~/.local/share/EarthNG/logs. The server listens on 127.0.0.1 only and stops a few minutes after
the last page is closed. ./EarthNG --help lists the options.

Needs: x86_64 Linux with glibc 2.28 or newer and a web browser. Nothing else is installed.
'''

SCRIPT = r'''
set -euo pipefail
CACHE=${CACHE:-/cache} SRC=${SRC:-/src} OUT=${OUT:-/out} WORK=${WORK:-/work}
export RUSTUP_HOME=$CACHE/rustup CARGO_HOME=$CACHE/cargo CARGO_TARGET_DIR=$CACHE/target
export PATH=$CACHE/cargo/bin:$PATH
if ! command -v cargo >/dev/null 2>&1; then
  curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --no-modify-path
fi
rustup toolchain list | grep -q stable || rustup toolchain install stable --profile minimal
cargo --version
cd $SRC/rust
cargo build --release --locked --workspace --exclude app
mkdir -p $OUT/bin
cp "$CARGO_TARGET_DIR/release/earthng-mapbuilder" "$CARGO_TARGET_DIR/release/libearthng_native.so" $OUT/bin/
strip --strip-debug $OUT/bin/earthng-mapbuilder $OUT/bin/libearthng_native.so
if [ "$EARTHNG_TEST" = 1 ]; then
  cargo test --release --locked --workspace --exclude app 2>&1 | tee $OUT/rust-tests.log
fi
mkdir -p $CACHE/downloads
PY=$CACHE/downloads/$(basename "$PYTHON_URL" | sed 's/%2B/+/')
if [ ! -f "$PY" ] || ! echo "$PYTHON_SHA256  $PY" | sha256sum -c - >/dev/null 2>&1; then
  curl -sSfL -o "$PY.part" "$PYTHON_URL"
  echo "$PYTHON_SHA256  $PY.part" | sha256sum -c -
  mv "$PY.part" "$PY"
fi
rm -rf "$WORK" && mkdir -p "$WORK"
tar -xzf "$PY" -C $WORK
$WORK/python/bin/python3 -m pip install --quiet --no-cache-dir --disable-pip-version-check \
  --only-binary=:all: --no-compile -r $SRC/requirements-fast.txt
find $WORK/python -name __pycache__ -type d -prune -exec rm -rf {} +
# pyosmium's wheel links the system's libexpat.so.1 (the manylinux rules allow it) and a minimal
# system has none (a bare Ubuntu 20.04): ship this image's copy (glibc 2.28) and have
# sitecustomize load it, before anything imports osmium, where the system has no copy of its own
expat() { ldconfig -p | awk '/libexpat\.so\.1 .*x86-64/ && !p {p = $NF} END {print p}'; }   # reads it all: no SIGPIPE under pipefail
EXPAT=$(expat)
if [ -z "$EXPAT" ]; then dnf install -y -q expat >/dev/null; EXPAT=$(expat); fi
SITE=$($WORK/python/bin/python3 -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
mkdir -p $SITE/earthng.libs
cp -L "$EXPAT" $SITE/earthng.libs/libexpat.so.1
cp $SRC/earthng/linux_sitecustomize.py $SITE/sitecustomize.py
$WORK/python/bin/python3 -c "import numpy, shapely, pyproj, osmium, PIL, sys; print('python', sys.version.split()[0], 'packages ok')"
tar -cf $OUT/python.tar -C $WORK python
if [ "$EARTHNG_TEST" = 1 ]; then
  # the whole repository snapshot with the Linux tools beside it, tested by the packaged interpreter
  # the packaged python/ is already in python.tar: the test tools go in only now
  $WORK/python/bin/python3 -m pip install --quiet --no-cache-dir --disable-pip-version-check --only-binary=:all: -r $SRC/requirements-dev.txt
  # in a checkout (REPO, the CI job) the tests see its .git; in Docker a copy of the snapshot
  if [ -n "${REPO:-}" ]; then TESTDIR=$REPO; else rm -rf $WORK/repo && cp -r $SRC $WORK/repo && TESTDIR=$WORK/repo; fi
  mkdir -p $TESTDIR/bin && cp $OUT/bin/* $TESTDIR/bin/
  cd $TESTDIR
  if $WORK/python/bin/python3 -m unittest discover -s earthng -p "test_*.py" > $OUT/python-tests.log 2>&1; then
    echo OK > $OUT/python-tests.status
  else
    echo FAILED > $OUT/python-tests.status
  fi
  tail -5 $OUT/python-tests.log
fi
'''


def docker():
    found = shutil.which('docker')
    if not found:
        raise SystemExit('docker not found: install Docker Desktop, or run with --native on Linux')
    return found


def snapshot(ref):
    """(commit, {name: bytes}) of the committed tree, LF as committed."""
    return prepare_release.source_snapshot(ref)


def write_tree(files, folder):
    for name, data in files.items():
        path = Path(folder) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def build_linux_parts(source, out, test=False, native=False, cache=None):
    """Run SCRIPT: out/bin/*, out/python.tar (and test logs). In the manylinux container, or with
    native=True right here on a Linux host (the CI job runs inside that container already)."""
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='earthng-linux-src-') as src, \
            tempfile.TemporaryDirectory(prefix='earthng-linux-work-') as work:
        needed = source if test else {n: d for n, d in source.items()
                                      if n.startswith('rust/') or n == 'requirements-fast.txt'}
        write_tree(needed, src)
        env = {'PYTHON_URL': PYTHON_URL, 'PYTHON_SHA256': PYTHON_SHA256, 'EARTHNG_TEST': '1' if test else '0'}
        if native:
            cache = Path(cache or Path.home() / '.cache' / 'earthng-linux-build').resolve()
            cache.mkdir(parents=True, exist_ok=True)
            env.update(CACHE=str(cache), SRC=src, OUT=str(out), WORK=str(Path(work) / 'w'), REPO=str(ROOT))
            subprocess.run(['bash', '-c', SCRIPT], check=True, env={**os.environ, **env})
            return
        command = [docker(), 'run', '--rm', '-v', f'{VOLUME}:/cache', '-v', f'{Path(src).resolve()}:/src:ro',
                   '-v', f'{out}:/out']
        for key, value in env.items():
            command += ['-e', f'{key}={value}']
        subprocess.run(command + [IMAGE, 'bash', '-c', SCRIPT], check=True)


def add_bytes(tar, name, data, mode=0o644, mtime=None):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    info.mtime = mtime or time.time()
    tar.addfile(info, io.BytesIO(data))


def add_planet(tar, planet, mtime):
    info = tarfile.TarInfo(f'{TOP}/earthng_planet.zip')
    info.size, info.mode, info.mtime = Path(planet).stat().st_size, 0o644, mtime
    with open(planet, 'rb') as stream:
        tar.addfile(info, stream)


def write_package(target, files, parts, planet=None, info=None):
    """The tarball: TOP/ with the runtime files, the Linux python/ and bin/, the launcher."""
    mtime = time.time()
    target = Path(target)
    part = target.with_name(target.name + '.part')
    with tarfile.open(part, 'w:gz', compresslevel=6, format=tarfile.PAX_FORMAT) as tar:
        add_bytes(tar, f'{TOP}/EarthNG', LAUNCHER.encode('utf-8'), 0o755, mtime)
        add_bytes(tar, f'{TOP}/README-Linux.txt', README.format(version=info['version']).encode('utf-8'), 0o644, mtime)
        for name, data in sorted(files.items()):
            add_bytes(tar, f'{TOP}/{name}', data, 0o644, mtime)
        for name in NATIVE:
            add_bytes(tar, f'{TOP}/bin/{name}', (Path(parts) / 'bin' / name).read_bytes(), 0o755, mtime)
        with tarfile.open(Path(parts) / 'python.tar') as python:
            for member in python:
                member.name = f'{TOP}/{member.name}'
                if member.islnk():
                    member.linkname = f'{TOP}/{member.linkname}'
                tar.addfile(member, python.extractfile(member) if member.isfile() else None)
        if planet is not None:
            add_planet(tar, planet, mtime)
    part.replace(target)
    return target


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def package_info(package):
    with tarfile.open(package) as tar:
        return json.loads(tar.extractfile(f'{TOP}/BUILD_INFO.json').read())


def repack(package, planet, out):
    """A package built without the planet (CI: the planet's art is not in Git) with this planet
    added, every other member copied as it is (modes, symlinks)."""
    info = package_info(package)
    prepare_release.check_planet(planet)
    if prepare_release.planet_version(planet) != info['planetVersion']:
        raise ValueError(f"the package expects planet {info['planetVersion']}, "
                         f'{Path(planet).name} is {prepare_release.planet_version(planet)}')
    target = Path(out) / PACKAGE
    if target.exists() or target.resolve() == Path(package).resolve():
        raise SystemExit(f'{target} exists: use an empty output folder')
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + '.part')
    with tarfile.open(package) as src, tarfile.open(part, 'w:gz', compresslevel=6, format=tarfile.PAX_FORMAT) as tar:
        for member in src:
            if member.name == f'{TOP}/earthng_planet.zip':
                continue
            tar.addfile(member, src.extractfile(member) if member.isfile() else None)
        add_planet(tar, planet, time.time())
    part.replace(target)
    return target, info


def build(out, planet=None, ref='HEAD', test=False, native=False):
    out = Path(out)
    if out.exists() and any(p.name == PACKAGE for p in out.iterdir()):
        raise SystemExit(f'{out / PACKAGE} exists: use an empty output folder')
    info, files = prepare_app.runtime_files(ref, native=False)
    commit, source = snapshot(ref)
    if planet is not None:
        prepare_release.check_planet(planet)
        if prepare_release.planet_version(planet) != info['planetVersion']:
            raise ValueError('bundled planet version must match the app runtime')
    info.update(platform='linux-x86_64', python=PYTHON_VERSION)
    files['BUILD_INFO.json'] = json.dumps(info, indent=2).encode('utf-8')
    parts = out / 'linux-parts'
    if parts.exists():
        shutil.rmtree(parts)
    cache = Path.home() / '.cache' / 'earthng-linux-build'
    build_linux_parts(source, parts, test=test, native=native, cache=cache)
    # the crates' licences from the registry cargo just used (Docker: its volume is not readable
    # here, the host's own ~/.cargo has the same lock file's crates)
    registry = cache / 'cargo' / 'registry' / 'src' if native else None
    files['bin/THIRD_PARTY_RUST.txt'] = prepare_release.rust_notices(
        source['rust/Cargo.lock'].decode('utf-8'), registry, 'bin/earthng-mapbuilder and bin/libearthng_native.so')
    target = write_package(out / PACKAGE, files, parts, planet, info)
    print(f"{PACKAGE} {info['version']} ({commit[:7]}, planet {info['planetVersion'] if planet else 'not bundled'}, "
          f'python {PYTHON_VERSION}): {target.stat().st_size / 2**20:.1f} MB, sha256 {sha256(target)}')
    status = parts / 'python-tests.status'
    if test and status.is_file():
        result = status.read_text().strip()
        print(f'Python tests on Linux: {result} (log: {parts / "python-tests.log"})')
        if result != 'OK':
            raise SystemExit(1)
    return target, info


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--planet', type=Path, help='bundle the planet ZIP (as the exe does)')
    p.add_argument('--ref', default='HEAD', help='committed source snapshot')
    p.add_argument('--test', action='store_true', help='run the Rust and Python tests on Linux too')
    p.add_argument('--native', action='store_true', help='build right here (a Linux host), not in Docker')
    p.add_argument('--repack', type=Path, metavar='PACKAGE',
                   help='add --planet to a package built without one (the CI artifact) and write it to --out')
    a = p.parse_args()
    if a.repack:
        if not a.planet:
            p.error('--repack needs --planet')
        target, info = repack(a.repack, a.planet, a.out)
        print(f"{PACKAGE} {info['version']} ({info['sourceCommit'][:7]}, planet {info['planetVersion']}): "
              f'{target.stat().st_size / 2**20:.1f} MB, sha256 {sha256(target)}')
    else:
        target, _ = build(a.out, a.planet, a.ref, a.test, a.native)
    print(f'Output: {target.resolve()}')


if __name__ == '__main__':
    main()
