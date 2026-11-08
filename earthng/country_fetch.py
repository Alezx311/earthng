"""Download a ready country pack, or build one from a Geofabrik extract.

    python earthng/country_fetch.py places --query berlin
    python earthng/country_fetch.py build --place ukraine --mods "%LOCALAPPDATA%/BeamNG/BeamNG.drive/current"
    python earthng/country_fetch.py install --zip out/native-packs/earthng_ukraine.zip --mods <profile>

Building downloads that extract's .osm.pbf, cuts tiles, fetches Terrarium heights and
writes earthng_<id>.zip. The look (asphalt, markings, verge, buildings, trees, statics)
and the layer switches are stored in the country manifest. Meshes stay in the planet mod.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
from itertools import islice
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import looks  # noqa: E402
import places  # noqa: E402
import tls  # noqa: E402

CATALOG = HERE / 'ready_packs.json'
USER_AGENT = places.USER_AGENT


def default_mods():
    base = Path(os.environ.get('LOCALAPPDATA', ''))
    for candidate in (base / 'BeamNG' / 'BeamNG.drive' / 'current', base / 'BeamNG.drive' / 'current'):
        if candidate.exists():
            return candidate
    return base / 'BeamNG' / 'BeamNG.drive' / 'current'


def catalog_entries():
    if not CATALOG.exists():
        return []
    payload = json.loads(CATALOG.read_text(encoding='utf-8'))
    entries = payload.get('packs') if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []
    out = []
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get('id'), str):
            url = entry.get('url') or ''
            out.append({'id': entry['id'], 'title': entry.get('title') or entry['id'],
                        'url': url if isinstance(url, str) and url.startswith('https://') else ''})
    return out


def local_folders(root=ROOT):
    return [Path(root) / 'out' / 'native-packs', Path(root) / 'out' / 'country-setup']


def find_zip(slug_id, folders):
    name = f'earthng_{slug_id}.zip'
    for folder in folders:
        path = Path(folder) / name
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def availability(slug_id, mods, root=ROOT):
    """installed | local | url | none, plus the path or url to use."""
    installed = Path(mods) / 'mods' / f'earthng_{slug_id}.zip'
    if installed.is_file() and installed.stat().st_size > 0:
        return {'state': 'installed', 'path': installed, 'url': ''}
    local = find_zip(slug_id, local_folders(root))
    if local is not None:
        return {'state': 'local', 'path': local, 'url': ''}
    for entry in catalog_entries():
        if entry['id'] == slug_id and entry['url']:
            return {'state': 'url', 'path': None, 'url': entry['url']}
    return {'state': 'none', 'path': None, 'url': ''}


def content_length(url, timeout=30):
    request = urllib.request.Request(url, method='HEAD', headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=tls.context()) as response:
        length = response.headers.get('Content-Length')
    return int(length) if length and length.isdigit() else None


def unchanged_since(url, dest, timeout=60):
    """True when the server answers 304 Not Modified for a file as old as dest."""
    import email.utils
    stamp = email.utils.formatdate(Path(dest).stat().st_mtime, usegmt=True)
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'If-Modified-Since': stamp})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=tls.context()):
            return False
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code == 304
    except OSError:
        return False


def download(url, dest, emit=print, cancel=None):
    """Resume only a validated version of a file; publish complete transfers atomically."""
    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise InterruptedError('download stopped')

    check_cancel()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        total = content_length(url)
    except OSError:
        # Some download servers allow GET but reject HEAD.
        total = None
    check_cancel()
    if dest.exists() and total and dest.stat().st_size == total:
        emit(f'already have {dest.name} ({total} bytes)')
        return dest
    if dest.exists() and not total and unchanged_since(url, dest):
        # HEAD failed (Geofabrik let it time out on 2026-10-26): the complete copy we have is
        # still the server's, so it is not fetched again
        emit(f'already have {dest.name} (unchanged on the server)')
        return dest
    for attempt in range(DOWNLOAD_RESUMES + 1):
        check_cancel()
        try:
            return _transfer(url, dest, total, emit, check_cancel)
        except (InterruptedError, TransferError):   # Stop (an OSError too); a server answering wrong
            raise
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == DOWNLOAD_RESUMES:
                raise
            problem = f'HTTP {exc.code}'
        except (OSError, http.client.HTTPException) as exc:
            if attempt == DOWNLOAD_RESUMES:
                raise
            problem = str(exc) or type(exc).__name__
        part = dest.with_suffix(dest.suffix + '.part')
        have = part.stat().st_size if part.exists() else 0
        emit(f'{dest.name}: the connection broke ({problem}); resuming at {have / 2**20:.0f} MB')
        if cancel is not None:
            if cancel.wait(min(30, 2 * attempt)):
                raise InterruptedError('download stopped')
        else:
            time.sleep(min(30, 2 * attempt))


# Times a broken or stalled transfer is picked up where it stopped, in one build. A connection
# that sends nothing for DOWNLOAD_STALL seconds counts as broken (a minute of waiting each time
# was the old timeout).
DOWNLOAD_RESUMES = 8
DOWNLOAD_STALL = 20


class TransferError(OSError):
    """The server answered a resumed download wrongly: asking again in this build will not help."""


def _transfer(url, dest, total, emit, check_cancel):
    """One request: from the validated part file on, or from the start."""
    part = dest.with_suffix(dest.suffix + '.part')
    metadata = part.with_suffix(part.suffix + '.json')
    have = part.stat().st_size if part.exists() else 0
    try:
        saved = json.loads(metadata.read_text(encoding='utf-8'))
        validator = saved.get('validator') if saved.get('url') == url else None
    except (OSError, ValueError, AttributeError):
        validator = None
    if not isinstance(validator, str) or not validator:
        have = 0  # old/unknown partials cannot safely be appended to today's extract
    headers = {'User-Agent': USER_AGENT}
    if have:
        headers['Range'] = f'bytes={have}-'
        headers['If-Range'] = validator
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=DOWNLOAD_STALL, context=tls.context())
    except urllib.error.HTTPError as exc:
        if exc.code != 416 or not have:
            raise
        exc.close()
        check_cancel()
        have = 0
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        response = urllib.request.urlopen(request, timeout=DOWNLOAD_STALL, context=tls.context())
    with response:
        check_cancel()
        status = getattr(response, 'status', 200)
        response_headers = getattr(response, 'headers', {})
        length = response_headers.get('Content-Length')
        length = int(length) if length and length.isdigit() else None
        expected = length
        if status == 200:
            have = 0
            total = length if length is not None else total
        elif status == 206:
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response_headers.get('Content-Range', ''))
            if not match:
                raise TransferError('invalid Content-Range in resumed download')
            start, end, total = map(int, match.groups())
            if start != have or end < start or end >= total:
                raise TransferError('invalid Content-Range in resumed download')
            expected = end - start + 1
            if length is not None and length != expected:
                raise TransferError('Content-Length does not match Content-Range')
        else:
            raise TransferError(f'{url}: HTTP {status}')
        etag = response_headers.get('ETag', '')
        current_validator = etag if etag and not etag.startswith('W/') else response_headers.get('Last-Modified')
        if status == 206 and have and current_validator and current_validator != validator:
            raise TransferError('source changed during resumed download; retry the download')
        mode = 'ab' if status == 206 and have else 'wb'
        chunk = 1024 * 256
        last = time.monotonic()
        received = 0
        with open(part, mode) as handle:
            metadata.write_text(json.dumps({'url': url, 'validator': current_validator or
                                           (validator if status == 206 else None)}), encoding='utf-8')
            while True:
                check_cancel()
                data = response.read(chunk)
                if not data:
                    break
                handle.write(data)
                have += len(data)
                received += len(data)
                now = time.monotonic()
                if now - last > 1.5:
                    if total:
                        emit(f'{dest.name}: {have / 2**20:.0f} / {total / 2**20:.0f} MB')
                    else:
                        emit(f'{dest.name}: {have / 2**20:.0f} MB')
                    last = now
    check_cancel()
    if expected is not None and received != expected:
        raise OSError(f'incomplete download: expected {expected} response bytes, got {received}')
    if total is not None and part.stat().st_size != total:
        raise OSError(f'incomplete download: expected {total} bytes, got {part.stat().st_size}')
    os.replace(part, dest)
    metadata.unlink(missing_ok=True)
    emit(f'downloaded {dest.name}')
    return dest


def check_stopped(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError('operation stopped')


def copy_stream(source, target, cancel=None):
    """Bound memory and observe Stop even while copying a large local archive."""
    while True:
        check_stopped(cancel)
        chunk = source.read(1024 * 1024)
        if not chunk:
            return
        target.write(chunk)


def ensure_space(path, needed, what):
    """Refuse a step the disk cannot hold, before it starts: a full disk midway left caches
    half-written. needed: bytes."""
    probe = Path(path)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    if needed and free < needed:
        raise OSError(f'{what} needs about {needed / 2**30:.1f} GB free on {probe.anchor or probe}, '
                      f'but only {free / 2**30:.1f} GB is free. Free some space and press Build again; '
                      'finished steps are kept.')


# Disk a country takes per byte of its PBF (Ukraine, 0.88 GB): source tiles 4.1, extracts while
# cutting 1.5, the region index 6.6, the pack 3.8 with as much in resumable parts, and its
# installed copy 3.8.
SPACE_PER_PBF_BYTE = 24


def install_zip(source, mods, slug_id, section=None, cancel=None):
    """Copy a country zip, or one section of it, into the BeamNG mods folder."""
    source = Path(source)
    check_stopped(cancel)
    if not source.is_file():
        raise FileNotFoundError(source)
    with zipfile.ZipFile(source) as archive:
        marker = (f'earthng/countries/{slug_id}/manifest.json' if section is None
                  else f'earthng/countries/{slug_id}/sections/{section}/section.json')
        if marker not in archive.namelist():
            raise ValueError(f'{source.name} does not contain {marker}')
    target_dir = Path(mods) / 'mods'
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / (f'earthng_{slug_id}.zip' if section is None else f'earthng_{slug_id}_{section}.zip')
    temporary = target.with_suffix('.zip.part')
    ensure_space(target_dir, source.stat().st_size + 2**26, f'Installing {target.name}')
    try:
        with source.open('rb') as src, temporary.open('wb') as dst:
            copy_stream(src, dst, cancel)
        check_stopped(cancel)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def tiles_dir(root, slug_id, box):
    name = f'{slug_id}-user'
    if box:
        # '-cells': tiles cut from the selection grown to whole cells (osm_tiles.source_box);
        # older caches held only the cells wholly inside the selection and are not reused.
        name = f'{name}-cells'
        digest = hashlib.sha1(','.join(f'{float(v):.5f}' for v in box).encode()).hexdigest()[:8]
        name = f'{name}-{digest}'
    return Path(root) / 'data' / 'osm_tiles' / name


def tiles_current(tiles, box=None):
    """A finished cut made by today's rules: osm_select.VERSION, and a 'region' whose every
    overlapping cell is kept. Older cuts dropped each cell whose buffered box crossed the edge of
    the extract or of the selection: Narva in Estonia, 13-43 % of a spot extract, and (5-7.11.2026,
    native cut of the bare selection) every cell round a selection's edges."""
    import osm_select
    try:
        index = json.loads((Path(tiles) / 'index.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, AttributeError):
        return False
    if not isinstance(index, dict) or index.get('select') != osm_select.VERSION:
        return False
    region = index.get('region')
    return isinstance(region, list) and len(region) == 4


def tiles_from_cover(root, slug_id, box, tiles, emit=print):
    """A selection's tiles taken from a finished cut of the same country that covers it (the whole
    country, or a larger selection): a tile is the same bytes whichever box it was cut for, so the
    PBF is not downloaded or cut again. Files are hard links where the disk allows. False when no
    cut covers the selection."""
    import osm_tiles
    need = osm_tiles.region(box)
    folder = Path(root) / 'data' / 'osm_tiles'
    best = None
    for candidate in sorted(folder.glob(f'{slug_id}-user*')):
        if candidate == Path(tiles) or candidate.name.endswith(('.recut', '.part', '.work')) or not candidate.is_dir():
            continue
        whole = candidate.name == f'{slug_id}-user'          # the country: its package box is the extract
        if not tiles_current(candidate, None if whole else box):
            continue
        try:
            index = json.loads((candidate / 'index.json').read_text(encoding='utf-8'))
            cw, cs, ce, cn = index['region']
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if whole:
            # the country's region is its extract box: cut today, the selection would be
            # clipped to it the same way
            region = [max(need[0], cw), max(need[1], cs), min(need[2], ce), min(need[3], cn)]
        elif cw <= need[0] and cs <= need[1] and need[2] <= ce and need[3] <= cn:
            region = need
        else:
            continue
        if region[0] >= region[2] or region[1] >= region[3]:
            continue
        if best is None or len(index['tiles']) < len(best[1]['tiles']):
            best = (candidate, index, region)
    if best is None:
        return False
    candidate, index, region = best
    keys = osm_tiles.region_keys(region)
    wanted = {f'{x}_{y}' for x, y in keys}
    keep = {key: tile for key, tile in index['tiles'].items() if key in wanted}
    target = Path(tiles)
    part = target.with_name(target.name + '.part')
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True)
    for tile in keep.values():
        try:
            os.link(candidate / tile['file'], part / tile['file'])
        except OSError:
            shutil.copy2(candidate / tile['file'], part / tile['file'])
    subset = {k: v for k, v in index.items() if k not in ('tiles', 'package_box', 'region', 'seconds')}
    subset.update(package_box=osm_tiles.package_of(sorted(keys), region), region=region, tiles=keep,
                  seconds=0.0, taken_from=candidate.name)
    (part / 'index.json').write_text(json.dumps(subset, indent=1), encoding='utf-8')
    if target.exists():
        shutil.rmtree(target)
    os.replace(part, target)
    emit(f'Source tiles: {len(keep)} taken from {candidate.name}; no PBF download or cut needed.')
    return True


def cut_region(pbf, box):
    """The region a cut keeps for a selection (osm_tiles.region): the selection grown to whole
    cells, clipped to the extract's own box (the PBF header)."""
    import osmium
    import osm_tiles
    header = osmium.io.Reader(str(pbf), osmium.osm.osm_entity_bits.NOTHING).header().box()
    extract = [header.bottom_left.lon, header.bottom_left.lat, header.top_right.lon, header.top_right.lat] if header.valid() else None
    return osm_tiles.region(box, extract)


def map_cache_dir(root, slug_id, pbf):
    """Keep each source generation separate so changed PBFs never mix map tiles."""
    import build_map
    pbf = Path(pbf)
    stat = pbf.stat()
    stamp = [build_map.VERSION, pbf.name, stat.st_size, stat.st_mtime_ns]
    digest = hashlib.sha256(json.dumps(stamp).encode()).hexdigest()[:16]
    return Path(root) / 'out' / 'map-data' / slug_id / digest


def cut_tiles(pbf, tiles, box=None, jobs=None, emit=print, cancel=None, heavy_jobs=None):
    """Cut pbf into tiles. A cut by older rules stays usable until its replacement is done.
    jobs: cut workers; heavy_jobs: of them, how many may read the whole PBF at once. None: sized
    to the free memory (a whole-PBF task takes about 5 bytes per PBF byte, Ukraine 4.4 GB; the
    others, extracts of a block group and block cuts, 1.6 GB on average, more in a city)."""
    import sysmem
    tiles = Path(tiles)
    try:
        whole = max(1.5, 5 * Path(pbf).stat().st_size / 2**30)
    except OSError:
        whole = 4.4
    jobs = jobs or sysmem.jobs(2, 12)
    heavy_jobs = min(jobs, heavy_jobs or sysmem.jobs(whole, 4))
    target = tiles.with_name(tiles.name + '.recut') if tiles.exists() else tiles
    if not tiles_current(target, box):
        if target.exists():
            shutil.rmtree(target)
        emit(f'cutting tiles into {tiles.name}')
        import native_tool
        # the native cut: the same tiles in one read of the PBF on every core (Kyiv's centre
        # from Ukraine: 12 s instead of 21 min)
        region = cut_region(pbf, box) if box else None
        command = native_tool.cut_command(pbf, target, region)
        if command is not None:
            try:
                run_step(command, emit, cancel)
            except (subprocess.CalledProcessError, OSError) as exc:
                # out of memory on a whole country, a missing runtime: the Python cut still works
                emit(f'native cut failed ({exc}); cutting in Python')
                for folder in (target, target.with_name(target.name + '.part')):
                    shutil.rmtree(folder, ignore_errors=True)
                command = None
        if command is None:
            command = [_python(), str(HERE / 'osm_tiles_country.py'), str(pbf), '--out', str(target),
                       '--jobs', str(jobs), '--heavy-jobs', str(heavy_jobs)]
            if region:
                command += ['--region', *(repr(float(v)) for v in region)]
            run_step(command, emit, cancel)
    if target != tiles:
        shutil.rmtree(tiles)
        import sysmem
        sysmem.replace_dir(target, tiles)
    return tiles


def pbf_path(root, slug_id):
    return Path(root) / 'data' / 'pbf' / f'{slug_id}.osm.pbf'


def _python():
    """Interpreter that can import osmium. This checkout only."""
    try:
        import osmium  # noqa: F401
        executable = Path(sys.executable)
        return str(executable.with_name('python.exe') if executable.name.lower() == 'pythonw.exe' else executable)
    except ImportError:
        pass
    if os.name == 'nt':
        candidates = [ROOT / 'python' / 'python.exe', ROOT / '.venv' / 'Scripts' / 'python.exe']
    else:
        candidates = [ROOT / '.venv-linux' / 'bin' / 'python', ROOT / '.venv' / 'bin' / 'python']
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError(
        'need a Python with osmium in this repository .venv (requirements-fast.txt)') from None


# Elevation tiles downloaded at once: 8, 16 and 32 fetched 19, 29 and 56 tiles/s from the AWS
# bucket (2026-10-26); Ukraine needs 21 000 of them.
DEM_THREADS = 32


def fetch_dem(index, dem, emit=print, cancel=None):
    """Terrarium heights under every tile of a cut index, DEM_THREADS downloads at a time."""
    import fast_dem

    missing = [path for path in fast_dem.audit(index, dem) if not path.exists()]
    emit(f'DEM: {len(missing)} tiles')

    def one(path):
        if cancel is not None and cancel.is_set():
            return
        for attempt in range(6):
            try:
                fast_dem.fetch(path)
                return
            except Exception:
                if attempt == 5:
                    raise
                if cancel is not None:
                    if cancel.wait(2 + attempt * 2):
                        raise InterruptedError('build stopped')
                else:
                    time.sleep(2 + attempt * 2)
    if not missing:
        return
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    with ThreadPoolExecutor(DEM_THREADS) as pool:
        remaining = iter(missing)
        pending = {pool.submit(one, path) for path in islice(remaining, 2 * DEM_THREADS)}
        completed = 0
        try:
            while pending:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError('build stopped')
                done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
                for future in done:
                    future.result()
                    completed += 1
                if done:
                    emit(f'Elevation: {completed}/{len(missing)} tiles')
                for path in islice(remaining, len(done)):
                    pending.add(pool.submit(one, path))
        finally:
            for future in pending:
                future.cancel()


def dem_ahead_index(box=None, outline=None):
    """An index-like {'tiles': {key: {'coverage'}}} of the cells a cut may keep, known before the
    PBF is here: every cell of the box's region (osm_tiles.region), or, for a whole
    country, every cell touching its extract outline. A superset of the cut where the box holds
    sea or empty land; the Elevation stage fetches what the real cut adds."""
    import osm_tiles
    if box is not None:
        keys = osm_tiles.region_keys(osm_tiles.region(box))
        return {'tiles': {f'{x}_{y}': {'coverage': osm_tiles.coverage((x, y))} for x, y in keys}}
    if outline is not None:
        pw, ps, pe, pn = outline.bounds
    else:
        return None
    keys = [(x, y) for x in range(math.floor(pw / osm_tiles.CELL), math.floor(pe / osm_tiles.CELL) + 1)
            for y in range(math.floor(ps / osm_tiles.CELL), math.floor(pn / osm_tiles.CELL) + 1)]
    covers = {k: osm_tiles.coverage(k) for k in keys}
    import numpy as np
    import shapely
    c = np.array([covers[k] for k in keys])
    hit = shapely.intersects(shapely.box(c[:, 0], c[:, 1], c[:, 2], c[:, 3]), outline)
    keys = [k for k, h in zip(keys, hit) if h]
    return {'tiles': {f'{x}_{y}': {'coverage': covers[(x, y)]} for x, y in keys}}


class _DemAhead:
    """Elevation tiles downloaded while the PBF is cut (start() once it is here): the line is idle
    during the cut. Beside the PBF download itself they only slowed it, since one stream of it
    already fills the line (8.2 of ~8.5 MB/s from Kyiv, 2026-11-07). join() waits for it; the
    Elevation stage then fetches anything the real cut needs beyond it."""

    def __init__(self, index, dem, emit, cancel):
        import threading
        self.stop = threading.Event()
        self.error = None
        self.count = 0
        self.emit = emit
        self.started = time.monotonic()

        def run():
            import fast_dem
            try:
                self.count = sum(1 for p in fast_dem.audit(index, dem) if not p.exists())
                fetch_dem(index, dem, emit=lambda _line: None, cancel=self)
            except Exception as exc:       # the Elevation stage asks again for what is missing
                self.error = exc
        self.cancel = cancel
        self.thread = threading.Thread(target=run, name='dem-ahead', daemon=True)

    def start(self):
        self.started = time.monotonic()
        self.thread.start()

    # fetch_dem's cancel: the build's Stop, or this job's own stop
    def is_set(self):
        return self.stop.is_set() or (self.cancel is not None and self.cancel.is_set())

    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.is_set():
                return True
            time.sleep(min(0.2, max(0., deadline - time.monotonic())))
        return self.is_set()

    def join(self):
        if self.thread.ident is None:              # never started: the Elevation stage fetches it all
            return
        self.thread.join()
        if self.count:
            spent = time.monotonic() - self.started
            note = f'; {self.error}' if self.error and not isinstance(self.error, InterruptedError) else ''
            self.emit(f'Elevation fetched while the tiles were cut: {self.count} tiles in {spent:.0f} s{note}')

    def close(self):
        self.stop.set()
        if self.thread.ident is not None:
            self.thread.join()


@contextmanager
def _dem_ahead(index, dem, emit, cancel):
    """A _DemAhead for index (None: nothing to fetch ahead), stopped when the build leaves."""
    ahead = _DemAhead(index, dem, emit, cancel) if index and index['tiles'] else None
    try:
        yield ahead
    finally:
        if ahead is not None:
            ahead.close()


def _outline(root, place):
    """The extract's outline from the region picker's cached index-v1.json, or None (offline,
    never opened the picker): nothing is downloaded for it."""
    path = Path(root) / 'data' / 'geofabrik' / 'index-v1.json'
    if not path.is_file():
        return None
    try:
        return places.load_boundaries(root).get(place['id'])
    except (OSError, ValueError, KeyError, ImportError):
        return None


@contextmanager
def build_lock(work):
    """One build at a time per checkout: two windows wrote the same out/world job and region
    files. The operating system drops the lock with the process, so a crash leaves none."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    handle = open(work / 'build.lock', 'a+b')
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('Another Map Builder build is running from this folder. Wait for it '
                               'to finish or stop it, then build again.') from None
        yield
    finally:
        handle.close()


class GeofabrikSource:
    """Where a build's OSM tiles come from (docs/MAPBUILDER_APP.md, "Джерело тайлів").

    The contract a build relies on: tiles (a folder with index.json, tiles_current's rules) and
    pbf (the original extract, if the source has one: Map detail reads it). ready() says whether
    the tiles are there already (or were taken from a covering cut); fetch() gets what cut()
    needs; cut() writes the tiles. Today's only source: a Geofabrik extract's PBF, cut here. A tile
    server would fetch tiles by the sha256 in its index.json and have nothing to cut."""
    name = 'geofabrik'

    def __init__(self, root, place, box=None):
        self.root, self.place, self.box = Path(root), place, box
        self.slug = places.slug(place['id'])
        self.pbf = pbf_path(root, self.slug)
        self.tiles = tiles_dir(root, self.slug, box)

    def ready(self, emit=print):
        if tiles_current(self.tiles, self.box):
            return True
        return self.box is not None and tiles_from_cover(self.root, self.slug, self.box, self.tiles, emit)

    def fetch(self, emit=print, cancel=None):
        if (self.tiles / 'index.json').is_file():
            emit("The cached source tiles predate today's cut rules: cutting them again.")
        emit(f"PBF {self.place['name']}: {self.place['pbf']}")
        try:
            size = self.pbf.stat().st_size if self.pbf.is_file() else content_length(self.place['pbf'])
        except (OSError, ValueError):
            size = None
        if size:
            share = 1 if self.box is None else 0.3       # a selection keeps part of the country
            ensure_space(self.root / 'data', int(size * SPACE_PER_PBF_BYTE * share), f"Building {self.place['name']}")
        download(self.place['pbf'], self.pbf, emit, cancel)

    def cut(self, jobs=None, emit=print, cancel=None):
        cut_tiles(self.pbf, self.tiles, self.box, jobs, emit, cancel, min(jobs, 4) if jobs else None)


def tile_source(root, place, box=None):
    """The tile source of a build: a Geofabrik extract until a tile server exists."""
    return GeofabrikSource(root, place, box)


def build_place(place, mods, root=ROOT, **options):
    """Download sources if needed and write the country zip, then copy it into mods
    (_build_place), one build at a time per checkout."""
    with build_lock(Path(root) / 'out' / 'world'):
        return _build_place(place, mods, root=root, **options)


def _build_place(place, mods, root=ROOT, look=None, include=None, box=None, jobs=None,
                 landing=None, by_id=None, emit=print, cancel=None, progress=None, local_dem=False,
                 road_register=False, section=None):
    """Download sources if needed and write the country zip, then copy it into mods.
    local_dem: burn the Estonian Land Board's 10 m LiDAR terrain into the elevation tiles.
    road_register: join Transpordiamet's road register (state road widths, shoulders, guard
    rails) onto the source tiles.
    section: a sections.find() entry: build only that administrative area, as one region in its
    own zip (earthng_<country>_<section>.zip); the game joins the installed sections."""
    slug_id = places.slug(place['id'])
    known = dict(by_id or {})
    known.setdefault(place['id'], place)
    look = looks.canonical(look or looks.recommended(place['id'], known))
    include = looks.canonical_include(include if include is not None else {})
    # None: sized to the cores and the memory free when each stage starts (sysmem.jobs); a
    # fixed 4 left 12 of 16 cores idle in the export and nearly ran a country cut out of RAM.
    # Measured on Ukraine: an export worker peaks near 0.7 GB, a whole-country cut task near 4.4 GB.
    import sysmem
    if section is not None:
        import sections
        if box is not None:
            raise ValueError('a section build has its own box')
        box = sections.box(section)
    if box is not None:
        from builder_estimate import validate_box
        box = validate_box(box)

    @contextmanager
    def stage(name):
        if cancel is not None and cancel.is_set():
            raise InterruptedError('build stopped')
        start = time.monotonic()
        if progress:
            progress(name, None)
        yield
        if progress:
            progress(name, time.monotonic() - start)

    source = tile_source(root, place, box)
    pbf, tiles = source.pbf, source.tiles
    cached_tiles = source.ready(emit)
    # elevation under the box (or the country's outline) downloads while the PBF is cut
    with _dem_ahead(None if cached_tiles else dem_ahead_index(box, None if box is not None else _outline(root, place)),
                    Path(root) / 'out' / 'world' / 'cache', emit, cancel) as ahead:
        with stage('Sources'):
            if cached_tiles:
                emit('Reusing completed source tiles; no PBF download or scan needed.')
            else:
                source.fetch(emit, cancel)
            if ahead is not None:
                ahead.start()
        with stage('Cut tiles'):
            if not cached_tiles:
                source.cut(jobs, emit, cancel)
        if road_register:
            with stage('Road register'):
                import est_roads
                box_of = json.loads((tiles / 'index.json').read_text(encoding='utf-8'))['package_box']
                tiles = est_roads.enrich(tiles, est_roads.fetch(box_of, Path(root) / 'data', emit), emit)
        index = json.loads((tiles / 'index.json').read_text(encoding='utf-8'))
        map_data = tiles / 'map'
        map_job = None
        if section is not None:
            map_data = None       # the offline map is the country's: the country pack carries it
        elif not (map_data / 'index.json').is_file():
            if pbf.is_file():
                # It reads only the PBF: it runs beside the elevation and the index (Ukraine's
                # 90 s were waited for after a city's 40 s index), and the export waits for it.
                map_data = map_cache_dir(root, slug_id, pbf)
                map_job = _Background('Map detail', [_python(), str(HERE / 'build_map.py'), '--pbf', str(pbf),
                                                     '--out', str(map_data)], emit, cancel, progress)
            else:
                emit('No original PBF/map sidecar in this cache: using base map labels and close-up roads.')
                map_data = None
        try:
            return _build_rest(place, mods, root, look, include, jobs, landing, emit, cancel, stage, slug_id, tiles,
                               index, map_data, map_job, local_dem, road_register, section, ahead)
        finally:
            if map_job is not None:
                map_job.stop()


def _build_rest(place, mods, root, look, include, jobs, landing, emit, cancel, stage, slug_id, tiles, index,
                map_data, map_job, local_dem, road_register, section, ahead=None):
    import sysmem
    dem = Path(root) / 'out' / 'world' / 'cache'
    with stage('Elevation'):
        if ahead is not None:
            ahead.join()
        fetch_dem(index, dem, emit, cancel)
        if local_dem:
            import est_dem
            import fast_dem
            est_dem.refine(fast_dem.audit(index, dem), dem, emit)
    if cancel is not None and cancel.is_set():
        raise InterruptedError('build stopped')
    work = Path(root) / 'out' / 'world'
    emit('region index')
    with stage('Region index'):
        # The index pool dies in the detached Map Builder window. A section is the same
        # job: its outline goes out as GeoJSON and comes back for the export.
        regions_path = work / 'regions.json'
        index_job = {'command': 'index', 'sources': str(tiles), 'dem': str(dem),
                     'work': str(work), 'result': str(regions_path)}
        if section is not None:
            index_job['section'] = {'id': section['id'], 'box': section['box'],
                                    'geometry': section['geometry']}
        run_build_job(index_job, emit, cancel)
        regions = json.loads(regions_path.read_text(encoding='utf-8'))
    out = Path(root) / 'out' / 'country-setup'
    if map_job is not None:
        map_job.join()
    # the optional sources a pack is built from travel in it (build_country.CREDITS)
    credits = []
    if road_register:
        import est_roads
        credits.append(est_roads.CREDIT)
    if (dem / 'est' / 'burnt.json').is_file():
        import est_dem
        import fast_dem
        land = est_dem.credit(fast_dem.audit(index, dem), dem)
        if land:
            credits.append(land)
    part = f"_{section['id']}" if section else ''
    emit(f"building earthng_{slug_id}{part}.zip, block {look['block']}")
    with stage('Export'):
        # the pack is about the size of its source tiles (Ukraine: 3.3 GB from 3.6), and the finished
        # regions it resumes from take as much again until it is complete
        ensure_space(out, 2 * sum(t.get('bytes', 0) for t in index.get('tiles', {}).values()) + 2**28, 'The export')
        # Same process as the index: export's block pool dies in the detached window too.
        export_path = work / 'export-path.txt'
        run_build_job({'command': 'export', 'id': slug_id, 'title': place['name'], 'version': '0.4.0',
                       'regions': regions, 'out': str(out), 'jobs': jobs or sysmem.jobs(1.5), 'landing': landing,
                       'look': look, 'include': include,
                       # Same mapped POIs and runtime details as the Kyiv oblast experiment.
                       'rich_data': True, 'experiments': {'detail': True, 'shopfront': True},
                       'map_data': None if map_data is None else str(map_data),
                       'work': str(work), 'result': str(export_path), 'credits': credits,
                       'section': None if section is None else {'id': section['id'], 'title': section['name']}},
                      emit, cancel)
        archive = Path(export_path.read_text(encoding='utf-8').strip())
    if cancel is not None and cancel.is_set():
        raise InterruptedError('build stopped; completed ZIP retained, not installed')
    with stage('Install'):
        installed = install_zip(archive, mods, slug_id, section and section['id'], cancel=cancel)
    emit(f'installed {installed}')
    forget_old_index(work, tiles.name + (f"_{section['id']}" if section else ''), regions, emit)
    return installed


def forget_old_index(work, key, regions, emit=print):
    """After a pack is installed, delete the region indexes that the previous build of the same
    source (key) used and this one does not. A rebuilt country left its old ones behind for good
    (out/world/fast-index had grown to 75 GB)."""
    record = Path(work) / 'builds' / f'{key}.json'
    keep = sorted({Path(r['dir']).name for r in regions if isinstance(r, dict) and r.get('dir')})
    try:
        previous = set(json.loads(record.read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError):
        previous = set()
    freed = 0
    for name in sorted(previous - set(keep)):
        folder = Path(work) / 'fast-index' / name
        if not (isinstance(name, str) and name.startswith('fast-') and folder.is_dir()):
            continue
        freed += sum(f.stat().st_size for f in folder.rglob('*') if f.is_file())
        shutil.rmtree(folder, ignore_errors=True)
    if freed:
        emit(f'removed the region index of the previous build ({freed / 2**30:.1f} GB)')
    record.parent.mkdir(parents=True, exist_ok=True)
    temporary = record.with_suffix('.json.part')
    temporary.write_text(json.dumps(keep), encoding='utf-8')
    temporary.replace(record)


def run_build_job(job, emit=print, cancel=None):
    """Index or export in a normal python.exe, not in the Map Builder window.

    The window is a detached pythonw process and its stdout is the startup log.
    A process pool created there dies on Windows and is reported only as a child
    that terminated abruptly. Tile cutting already goes through run_step, and
    that pool finishes."""
    folder = Path(job['work'])
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{job['command']}-job.json"
    path.write_text(json.dumps(job), encoding='utf-8')
    run_step([_python(), str(HERE / 'build_country.py'), '--job', str(path)], emit, cancel)


class _Either:
    """A cancel event set when any of its events is (the user's Stop, or the build failing)."""
    def __init__(self, *events):
        self.events = [e for e in events if e is not None]

    def is_set(self):
        return any(e.is_set() for e in self.events)

    def wait(self, timeout):
        end = time.monotonic() + timeout
        while not self.is_set():
            left = end - time.monotonic()
            if left <= 0:
                return False
            time.sleep(min(.05, left))
        return True


class _Background:
    """A build stage in its own process beside the next stages: run_step on a thread, its
    progress reported as a stage of its own. join() waits and raises what it raised."""
    def __init__(self, name, command, emit, cancel, progress):
        import threading
        self.stopped = threading.Event()
        self.error = None
        self.name, self.progress = name, progress

        def run():
            start = time.monotonic()
            try:
                run_step(command, emit, _Either(cancel, self.stopped))
                if progress:
                    progress(name, time.monotonic() - start)
            except BaseException as exc:      # noqa: BLE001 - handed to join()
                self.error = exc
        if progress:
            progress(name, None)
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def join(self):
        self.thread.join()
        if self.error is not None:
            raise self.error

    def stop(self):
        """Kill it if it still runs (the build stopped or failed before it was joined)."""
        if self.thread.is_alive():
            self.stopped.set()
            self.thread.join()


def run_step(command, emit=print, cancel=None):
    """Capture worker output (the service has no console); cancel its process tree."""
    import threading
    check_stopped(cancel)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding='utf-8', errors='replace',
                          env={**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8'},
                          creationflags=creationflags) as process:
        def relay():
            for line in process.stdout:
                emit(line.rstrip())
        reader = threading.Thread(target=relay, daemon=True)
        reader.start()
        while process.poll() is None:
            if cancel is not None and cancel.wait(0.2):
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   capture_output=True, creationflags=creationflags)
                else:
                    process.terminate()
                process.wait()
                reader.join()
                raise InterruptedError('build stopped')
            if cancel is None:
                time.sleep(0.2)
        reader.join()
        check_stopped(cancel)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)


def refresh_planet(mods, emit=print, cancel=None):
    """Replace Lua, materials.json and the packs' settings inside an existing planet zip. Art
    files stay (the settings name only art of the same version, and the game's own maps)."""
    import fast_art
    import fast_style

    check_stopped(cancel)

    zip_path = Path(mods) / 'mods' / 'earthng_planet.zip'
    if not zip_path.is_file():
        raise FileNotFoundError(f'missing {zip_path}. Build the planet first: earthng/build_mod.py')
    replacements = {}
    mod = ROOT / 'mod'
    for src in mod.rglob('*'):
        if src.is_file():
            replacements[src.relative_to(mod).as_posix()] = src.read_bytes()
    replacements['earthng/planet/materials.json'] = json.dumps(fast_style.MATERIALS).encode('utf-8')
    replacements[f'e2r_stream/fast-art/{fast_art.VERSION}/packs.json'] = fast_art.manifest_text().encode('utf-8')
    # keep the language the planet was built with (build_mod.py --lang rewrites this line)
    world = 'lua/ge/extensions/e2r/world.lua'
    with zipfile.ZipFile(zip_path) as source:
        installed = source.read(world).decode('utf-8') if world in source.namelist() else ''
    lang = re.search(r"^local LANG = '(\w+)'", installed, re.M)
    if lang and world in replacements:
        replacements[world] = re.sub(r"^local LANG = '\w+'", f"local LANG = '{lang.group(1)}'",
                                     replacements[world].decode('utf-8'), count=1, flags=re.M).encode('utf-8')
    temporary = zip_path.with_suffix('.zip.tmp')
    replaced = 0
    try:
        with zipfile.ZipFile(zip_path) as source, zipfile.ZipFile(temporary, 'w') as dest:
            for info in source.infolist():
                check_stopped(cancel)
                data = replacements.pop(info.filename, None)
                stamp = info.date_time if info.date_time[0] >= 1980 else (2020, 1, 1, 0, 0, 0)
                copy = zipfile.ZipInfo(info.filename, date_time=stamp)
                copy.compress_type = info.compress_type
                copy.external_attr = info.external_attr
                if data is None:
                    copy.file_size = info.file_size
                    with source.open(info) as src, dest.open(copy, 'w') as dst:
                        copy_stream(src, dst, cancel)
                else:
                    dest.writestr(copy, data)
                    replaced += 1
            for name, data in replacements.items():
                check_stopped(cancel)
                if name.startswith('lua/') or name == 'earthng/planet/materials.json':
                    dest.writestr(name, data)
                    replaced += 1
        check_stopped(cancel)
        os.replace(temporary, zip_path)
    finally:
        temporary.unlink(missing_ok=True)
    emit(f'planet code updated ({replaced} files) in {zip_path.name}')
    return zip_path


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('command', choices=('places', 'sections', 'build', 'install', 'refresh-planet'))
    parser.add_argument('--query', default='')
    parser.add_argument('--place', help='Geofabrik extract id, for example ukraine or berlin')
    parser.add_argument('--mods', type=Path, default=default_mods())
    parser.add_argument('--zip', type=Path)
    parser.add_argument('--box', type=float, nargs=4, metavar=('W', 'S', 'E', 'N'))
    parser.add_argument('--jobs', type=int, default=0)
    parser.add_argument('--block', default='')
    parser.add_argument('--landing', type=float, nargs=2, metavar=('LAT', 'LON'))
    parser.add_argument('--refresh-index', action='store_true')
    parser.add_argument('--local-dem', action='store_true',
                        help='Estonia: refine the elevation with the Land Board 10 m LiDAR terrain')
    parser.add_argument('--section', help='build one administrative area (county, city) of the place '
                        'as its own zip; list them with the sections command')
    parser.add_argument('--road-register', action='store_true',
                        help='Estonia: state road widths, shoulders and guard rails from the road register')
    for slot in looks.SLOTS:
        parser.add_argument(f'--{slot}', default='')
    for key, _label, _default in looks.LAYERS:
        parser.add_argument(f'--no-{key}', dest=f'no_{key}', action='store_true')
    args = parser.parse_args()
    if args.command == 'places':
        found = places.search(places.load_index(ROOT, args.refresh_index), args.query)
        for place in found:
            print(f"{place['id']}\t{place['name']}\t{place['parent']}")
        return
    if args.command == 'refresh-planet':
        refresh_planet(args.mods)
        return
    if args.command == 'install':
        if not args.place or not args.zip:
            parser.error('install needs --place and --zip')
        print(install_zip(args.zip, args.mods, places.slug(args.place), args.section))
        return
    if not args.place:
        parser.error(f'{args.command} needs --place')
    index = places.by_id(places.load_index(ROOT, args.refresh_index))
    place = index.get(args.place)
    if place is None:
        parser.error(f'unknown extract {args.place}')
    section = None
    if args.command == 'sections' or args.section:
        import sections
        pbf = pbf_path(ROOT, places.slug(place['id']))
        if not pbf.is_file():
            download(place['pbf'], pbf)
        found = sections.load(pbf, ROOT / 'data' / 'sections')
        if args.command == 'sections':
            for entry in found:
                print(f"{entry['id']}	{entry['name']}	level {entry['level']}	{entry['box']}")
            return
        try:
            section = sections.find(found, args.section)
            sections.box(section)
        except ValueError as exc:
            parser.error(str(exc))
    base = looks.recommended(place['id'], index)
    if args.block:
        block = looks.BLOCK_BY_ID.get(args.block)
        if block is None:
            parser.error(f'unknown asset block {args.block}')
        base = {'block': block['id'], **block['look']}
    for slot in looks.SLOTS:
        chosen = getattr(args, slot)
        if chosen:
            base[slot] = chosen
    include = {key: not getattr(args, f'no_{key}') for key, _label, _default in looks.LAYERS}
    built = build_place(place, args.mods, look=looks.canonical(base), include=include,
                        box=args.box, jobs=args.jobs or None, by_id=index,
                        landing=tuple(args.landing) if args.landing else None,
                        local_dem=args.local_dem, road_register=args.road_register, section=section)
    print(built)


if __name__ == '__main__':
    main()
