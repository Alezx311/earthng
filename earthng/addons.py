"""Optional packs EarthNG.exe puts beside the planet: the proving ground and the flora pack.

    .venv\\Scripts\\python.exe earthng\\addons.py --release v1.1.0 <earthng_polygon.zip> <earthng_flora.zip>

writes earthng/addons.json from the files published on that GitHub release: each pack's file
name, download URL, size and sha256. The catalog is committed, so the exe and the Linux package
carry it in their runtime (prepare_release.builder_files). The service (app_service.py) downloads
a chosen pack once, checks its size, sha256 and contents, and installs it into <user folder>/mods
next to the planet (docs/MAPBUILDER_APP.md). A pack whose file in mods has another size than the
catalog's is another build of it, and is replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import country_fetch  # noqa: E402

CATALOG = HERE / 'addons.json'
SCHEMA = 'earthng-addons-v1'
RELEASES = 'https://github.com/Alezx311/earthng/releases/download'
# What each pack is, by a file only that pack has; the order is the page's.
KNOWN = {
    'polygon': {'file': 'earthng_polygon.zip', 'marker': 'earthng/countries/polygon/manifest.json'},
    'flora': {'file': 'earthng_flora.zip', 'marker': 'art/shapes/earthng/flora/flora.json'},
}
BYTES_PER_SECOND = 3_000_000       # the planet came at ~3 MB/s from GitHub (app_service.PLANET_SECONDS)


def allowed_url(url):
    parts = urlsplit(url)
    host = (parts.hostname or '').lower()
    return parts.scheme == 'https' and host == 'github.com'


def check_entry(entry):
    """A catalog row as the service may use it, or ValueError."""
    if not isinstance(entry, dict) or entry.get('id') not in KNOWN:
        raise ValueError('unknown add-on')
    known = KNOWN[entry['id']]
    size, sha, url = entry.get('size'), entry.get('sha256'), entry.get('url')
    if entry.get('file') != known['file']:
        raise ValueError(f"{entry['id']}: the file is {known['file']}")
    if not isinstance(url, str) or not allowed_url(url) or not url.endswith('/' + known['file']):
        raise ValueError(f"{entry['id']}: the URL is a GitHub release file")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError(f"{entry['id']}: bad size")
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise ValueError(f"{entry['id']}: bad sha256")
    return {'id': entry['id'], 'file': known['file'], 'url': url, 'size': size, 'sha256': sha}


def load(path=CATALOG):
    """The packs this runtime offers, in the page's order; none without a catalog. A row that does
    not check out is left out, never trusted."""
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict) or payload.get('schema') != SCHEMA or not isinstance(payload.get('addons'), list):
        return []
    found = {}
    for entry in payload['addons']:
        try:
            checked = check_entry(entry)
        except ValueError:
            continue
        found.setdefault(checked['id'], checked)
    return [found[k] for k in KNOWN if k in found]


def target(entry, mods):
    return Path(mods) / 'mods' / entry['file']


def state(entry, mods):
    """'installed' (the catalog's size), 'other' (another build of the pack) or 'missing'."""
    path = target(entry, mods)
    try:
        size = path.stat().st_size
    except OSError:
        return 'missing'
    return 'installed' if size == entry['size'] else 'other'


def seconds(entries):
    return round(sum(e['size'] for e in entries) / BYTES_PER_SECOND)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def check_file(entry, path):
    """The downloaded file is the catalog's: its size, its sha256, and the pack's own marker."""
    path = Path(path)
    if path.stat().st_size != entry['size']:
        raise ValueError(f"{entry['file']}: the size does not match the release ({entry['size']} bytes)")
    if file_sha256(path) != entry['sha256']:
        raise ValueError(f"{entry['file']}: the file does not match the release")
    with zipfile.ZipFile(path) as archive:
        if KNOWN[entry['id']]['marker'] not in archive.namelist():
            raise ValueError(f"{entry['file']} is not the EarthNG {entry['id']} pack")


def install(entry, source, mods, cancel=None):
    """Copy a checked pack into <user folder>/mods under a temporary name, then swap it in."""
    folder = Path(mods) / 'mods'
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / entry['file']
    temporary = final.with_suffix('.zip.part')
    country_fetch.ensure_space(folder, entry['size'] + 2**26, f"Installing {entry['file']}")
    try:
        with open(source, 'rb') as src, temporary.open('wb') as dst:
            country_fetch.copy_stream(src, dst, cancel)
        country_fetch.check_stopped(cancel)
        os.replace(temporary, final)
    finally:
        temporary.unlink(missing_ok=True)
    return final


def fetch(entry, root, mods, emit=print, cancel=None):
    """Download a pack into <home>/downloads, check it, install it, and drop the download."""
    folder = Path(root) / 'downloads'
    folder.mkdir(parents=True, exist_ok=True)
    country_fetch.ensure_space(folder, entry['size'] + 2**26, f"Downloading {entry['file']}")
    download = folder / entry['file']
    emit(f"Downloading {entry['file']} ({entry['size'] / 2**20:.1f} MB) from GitHub Releases")
    country_fetch.download(entry['url'], download, emit, cancel)
    try:
        check_file(entry, download)
    except (OSError, ValueError, zipfile.BadZipFile):
        download.unlink(missing_ok=True)       # never resume from a file that is not the release's
        raise
    installed = install(entry, download, mods, cancel)
    download.unlink(missing_ok=True)
    emit(f"installed {entry['file']}")
    return installed


def entry_for(path, release, releases=RELEASES):
    """The catalog row of a local pack published on GitHub release `release` (a tag)."""
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    kinds = [k for k, known in KNOWN.items() if known['marker'] in names]
    if len(kinds) != 1:
        raise ValueError(f'{path.name}: not the proving ground or the flora pack')
    kind = kinds[0]
    if path.name != KNOWN[kind]['file']:
        raise ValueError(f"{path.name}: the {kind} pack is published as {KNOWN[kind]['file']}")
    if not re.fullmatch(r'[A-Za-z0-9._-]+', release):
        raise ValueError(f'bad release tag: {release}')
    return check_entry({'id': kind, 'file': path.name, 'url': f'{releases}/{release}/{path.name}',
                        'size': path.stat().st_size, 'sha256': file_sha256(path)})


def write(paths, release, out=CATALOG):
    entries = {}
    for path in paths:
        entry = entry_for(path, release)
        if entry['id'] in entries:
            raise ValueError(f"two {entry['id']} packs given")
        entries[entry['id']] = entry
    payload = {'schema': SCHEMA, 'release': release, 'addons': [entries[k] for k in KNOWN if k in entries]}
    Path(out).write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return payload


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--release', required=True, help='the GitHub release tag the packs are published on (v1.1.0)')
    p.add_argument('--out', type=Path, default=CATALOG)
    p.add_argument('packs', nargs='+', type=Path)
    a = p.parse_args()
    payload = write(a.packs, a.release, a.out)
    for entry in payload['addons']:
        print(f"{entry['sha256']}  {entry['file']}  {entry['size']}  {entry['url']}")
    print(f'Output: {a.out.resolve()}')


if __name__ == '__main__':
    main()
