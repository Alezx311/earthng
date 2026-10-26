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
from itertools import islice
import json
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
    check_cancel()
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
        response = urllib.request.urlopen(request, timeout=60, context=tls.context())
    except urllib.error.HTTPError as exc:
        if exc.code != 416 or not have:
            raise
        exc.close()
        check_cancel()
        have = 0
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        response = urllib.request.urlopen(request, timeout=60, context=tls.context())
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
                raise OSError('invalid Content-Range in resumed download')
            start, end, total = map(int, match.groups())
            if start != have or end < start or end >= total:
                raise OSError('invalid Content-Range in resumed download')
            expected = end - start + 1
            if length is not None and length != expected:
                raise OSError('Content-Length does not match Content-Range')
        else:
            raise OSError(f'{url}: HTTP {status}')
        etag = response_headers.get('ETag', '')
        current_validator = etag if etag and not etag.startswith('W/') else response_headers.get('Last-Modified')
        if status == 206 and have and current_validator and current_validator != validator:
            raise OSError('source changed during resumed download; retry the download')
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


def tiles_current(tiles):
    """A finished cut made by today's selection rules (osm_select.VERSION)."""
    import osm_select
    try:
        return json.loads((Path(tiles) / 'index.json').read_text(encoding='utf-8')).get('select') == osm_select.VERSION
    except (OSError, ValueError, AttributeError):
        return False


def cut_tiles(pbf, tiles, box=None, jobs=4, emit=print, cancel=None):
    """Cut pbf into tiles. A cut by older rules stays usable until its replacement is done."""
    tiles = Path(tiles)
    target = tiles.with_name(tiles.name + '.recut') if tiles.exists() else tiles
    if not tiles_current(target):
        if target.exists():
            shutil.rmtree(target)
        emit(f'cutting tiles into {tiles.name}')
        command = [_python(), str(HERE / 'osm_tiles_country.py'), str(pbf), '--out', str(target),
                   '--jobs', str(jobs)]
        if box:
            command += ['--package-box', *(str(v) for v in box)]
        run_step(command, emit, cancel)
    if target != tiles:
        shutil.rmtree(tiles)
        target.replace(tiles)
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
    # Measured on Ukraine: an export worker peaks near 0.7 GB, a cut worker near 4.4 GB.
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

    pbf = pbf_path(root, slug_id)
    tiles = tiles_dir(root, slug_id, box)
    cached_tiles = tiles_current(tiles)
    with stage('Sources'):
        if cached_tiles:
            emit('Reusing completed source tiles; no PBF download or scan needed.')
        else:
            if (tiles / 'index.json').is_file():
                emit('The cached source tiles predate the points the generator now reads '
                     '(lamps, trees, stops, entrances): cutting them again.')
            emit(f"PBF {place['name']}: {place['pbf']}")
            try:
                size = pbf.stat().st_size if pbf.is_file() else content_length(place['pbf'])
            except (OSError, ValueError):
                size = None
            if size:
                share = 1 if box is None else 0.3       # a selection keeps part of the country
                ensure_space(Path(root) / 'data', int(size * SPACE_PER_PBF_BYTE * share), f"Building {place['name']}")
            download(place['pbf'], pbf, emit, cancel)
    with stage('Cut tiles'):
        if not cached_tiles:
            cut_tiles(pbf, tiles, box, min(jobs, 4) if jobs else sysmem.jobs(4, 4), emit, cancel)
    if road_register:
        with stage('Road register'):
            import est_roads
            box_of = json.loads((tiles / 'index.json').read_text(encoding='utf-8'))['package_box']
            tiles = est_roads.enrich(tiles, est_roads.fetch(box_of, Path(root) / 'data', emit), emit)
    index = json.loads((tiles / 'index.json').read_text(encoding='utf-8'))
    dem = Path(root) / 'out' / 'world' / 'cache'
    with stage('Elevation'):
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
    map_data = tiles / 'map'
    if section is not None:
        map_data = None       # the offline map is the country's: the country pack carries it
    elif not (map_data / 'index.json').is_file():
        if pbf.is_file():
            # A separate worker keeps this cancellable, just like source extraction.
            map_data = Path(root) / 'out' / 'map-data' / slug_id
            with stage('Map detail'):
                run_step([_python(), str(HERE / 'build_map.py'), '--pbf', str(pbf), '--out', str(map_data)], emit, cancel)
        else:
            emit('No original PBF/map sidecar in this cache: using base map labels and close-up roads.')
            map_data = None
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


def run_step(command, emit=print, cancel=None):
    """Capture worker output even when MapBuilder.bat uses pythonw; cancel its process tree."""
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
