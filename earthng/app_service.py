"""The EarthNG.exe window's backend: JSON lines on stdin, answers and events on stdout.

    python earthng/app_service.py            (EarthNG.exe starts it; docs/MAPBUILDER_APP.md)

A request is {"id": n, "cmd": "...", ...}; its answer {"id": n, "ok": true, ...} or
{"id": n, "ok": false, "error": "..."}. A job (install the planet, build a pack) answers at once
and reports with events: {"event": "log", "text"}, {"event": "stage", "name", "seconds"},
{"event": "done", "job", "result", "path"?, "error"?}. One job runs at a time.

Data (PBF, tiles, DEM, packs, projects) live in EARTHNG_HOME, not beside the code: the exe's code
folder is replaced with each version. Without EARTHNG_HOME a checkout keeps using itself.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import time
import traceback
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parent

import builder_estimate as timing  # noqa: E402
import country_fetch  # noqa: E402
import looks  # noqa: E402
import places  # noqa: E402

RELEASE_URL = 'https://github.com/Alezx311/earthng/releases/download/EarthNG'
PLANET = 'earthng_planet.zip'
PROJECT_SCHEMA = 'earthng-project-v1'


def home():
    return Path(os.environ.get('EARTHNG_HOME') or ROOT)


def build_info():
    """BUILD_INFO.json of the runtime (prepare_app.py): version, source commit, planet version."""
    try:
        return json.loads((ROOT / 'BUILD_INFO.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


class Service:
    def __init__(self, out=None, root=None):
        self.out = out or sys.stdout
        self.root = Path(root) if root else home()
        self.lock = threading.Lock()
        self.job = None
        self.cancel = None
        self.places = None
        self.boundaries = None
        self.settings_path = self.root / 'app_settings.json'
        self.settings = self.load_settings()

    # ------------------------------------------------------------------ plumbing
    def send(self, message):
        line = json.dumps(message, ensure_ascii=False)
        with self.lock:
            self.out.write(line + '\n')
            self.out.flush()

    def log(self, text):
        self.send({'event': 'log', 'text': str(text)})

    def handle(self, request):
        rid = request.get('id')
        try:
            name = request.get('cmd')
            method = getattr(self, f'cmd_{name}', None) if isinstance(name, str) and name.isidentifier() else None
            if method is None:
                raise ValueError(f'unknown command: {name}')
            result = method(**{k: v for k, v in request.items() if k not in ('id', 'cmd')})
            self.send({'id': rid, 'ok': True, **(result or {})})
        except Exception as exc:  # noqa: BLE001 - every failure goes back to the page
            self.send({'id': rid, 'ok': False, 'error': str(exc) or type(exc).__name__})

    def serve(self, lines):
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError('a request is a JSON object')
            except ValueError as exc:
                self.send({'id': None, 'ok': False, 'error': f'bad request: {exc}'})
                continue
            self.handle(request)

    def start_job(self, name, target):
        """Run target(cancel) on a thread; report its end as a done event."""
        if self.job is not None and self.job.is_alive():
            raise RuntimeError('another job is running; stop it first')
        self.cancel = threading.Event()
        cancel = self.cancel

        def run():
            started = time.monotonic()
            done = {'event': 'done', 'job': name}
            try:
                path = target(cancel)
                done.update(result='complete', path=str(path) if path else None)
            except InterruptedError:
                done.update(result='stopped')
                self.log('Stopped. Finished source data is kept for the next build.')
            except Exception as exc:  # noqa: BLE001
                done.update(result='failed', error=str(exc) or type(exc).__name__)
                self.log(traceback.format_exc(limit=6))
            done['seconds'] = round(time.monotonic() - started, 1)
            self.send(done)
        self.job = threading.Thread(target=run, name=f'job-{name}', daemon=True)
        self.job.start()
        return {'job': name}

    # ------------------------------------------------------------------ settings and game folder
    def load_settings(self):
        settings = {'mods': str(country_fetch.default_mods())}
        try:
            saved = json.loads(self.settings_path.read_text(encoding='utf-8'))
            if isinstance(saved, dict):
                settings.update({k: v for k, v in saved.items() if isinstance(v, str)})
        except (OSError, ValueError):
            pass
        return settings

    def save_settings(self):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_path.with_suffix('.json.part')
        tmp.write_text(json.dumps(self.settings, ensure_ascii=False, indent=1), encoding='utf-8')
        tmp.replace(self.settings_path)

    @property
    def mods(self):
        return Path(self.settings['mods'])

    def planet_state(self):
        path = self.mods / 'mods' / PLANET
        state = {'path': str(path), 'installed': path.is_file(), 'version': None,
                 'expected': build_info().get('planetVersion')}
        if state['installed']:
            try:
                with zipfile.ZipFile(path) as archive:
                    manifest = json.loads(archive.read('earthng/planet/manifest.json'))
                state['version'] = manifest.get('version')
            except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
                state['error'] = f'unreadable planet: {exc}'
        return state

    def cmd_status(self):
        mods = self.mods
        free = None
        try:
            free = round(shutil.disk_usage(self.root if self.root.exists() else self.root.anchor).free / 2**30, 1)
        except OSError:
            pass
        return {'home': str(self.root), 'mods': str(mods), 'game_folder_ok': game_folder_ok(mods),
                'planet': self.planet_state(), 'busy': bool(self.job and self.job.is_alive()),
                'build': build_info(), 'free_gb': free, 'folders': [str(p) for p in game_folders()]}

    def cmd_set_game_folder(self, path):
        folder = Path(path)
        if not folder.is_dir():
            raise ValueError(f'not a folder: {folder}')
        self.settings['mods'] = str(folder)
        self.save_settings()
        return self.cmd_status()

    def cmd_open_folder(self, which='mods'):
        folder = {'mods': self.mods / 'mods', 'home': self.root,
                  'packs': self.root / 'out' / 'country-setup'}.get(which)
        if folder is None:
            raise ValueError(f'unknown folder: {which}')
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            os.startfile(folder)  # noqa: S606 - the user's own folder
        return {'path': str(folder)}

    # ------------------------------------------------------------------ planet
    def cmd_install_planet(self, url=None):
        url = url or f'{RELEASE_URL}/{PLANET}'
        if not url.startswith('https://'):
            raise ValueError('the planet is downloaded over https only')
        mods = self.mods

        def target(cancel):
            if not game_folder_ok(mods):
                raise ValueError(f'{mods} is not a BeamNG user folder (it has no mods folder or settings)')
            dest = self.root / 'downloads' / PLANET
            self.log(f'Downloading {PLANET} from GitHub Releases')
            country_fetch.download(url, dest, self.log, cancel)
            return install_planet(dest, mods, cancel)
        return self.start_job('install_planet', target)

    def cmd_stop(self):
        if self.cancel is not None:
            self.cancel.set()
        return {'stopping': bool(self.job and self.job.is_alive())}

    # ------------------------------------------------------------------ places and options
    def ensure_places(self, refresh=False):
        if self.places is None or refresh:
            loaded = places.load_index(self.root, refresh, self.log)
            self.places = sorted(loaded, key=lambda p: (p['name'].casefold(), p['id']))
            self.by_id = places.by_id(self.places)
        return self.places

    def cmd_places(self, query='', limit=60, refresh=False):
        found = places.search(self.ensure_places(bool(refresh)), query or '', limit)
        return {'places': [{'id': p['id'], 'name': p['name'], 'parent': places.parent_name(p, self.by_id)}
                           for p in found]}

    def ensure_boundaries(self):
        if self.boundaries is None:
            self.boundaries = places.load_boundaries(self.root)
        return self.boundaries

    def cmd_boundary(self, place):
        import shapely
        geometry = self.ensure_boundaries().get(place)
        if geometry is None:
            return {'geojson': None}
        simple = shapely.simplify(geometry, 0.01, preserve_topology=True)
        return {'geojson': json.loads(shapely.to_geojson(simple)), 'bounds': list(geometry.bounds)}

    def cmd_covering(self, box):
        """The smallest Geofabrik extract that holds the whole box (the tile source today)."""
        box = timing.validate_box([float(v) for v in box])
        self.ensure_places()
        best = places.smallest_covering(self.ensure_boundaries(), box, set(self.by_id))
        place = self.by_id.get(best) if best else None
        return {'place': {'id': place['id'], 'name': place['name'],
                          'parent': places.parent_name(place, self.by_id)} if place else None,
                'km2': round(timing.area_km2(box), 1)}

    def cmd_options(self, place=None):
        self.ensure_places()
        recommended = looks.recommended(place, self.by_id) if place in self.by_id else looks.canonical({'block': 'general'})
        return {'slots': {slot: [{'id': k, 'label': v} for k, v in choices.items()] for slot, choices in looks.SLOTS.items()},
                'slot_labels': looks.SLOT_LABELS,
                'blocks': [{'id': b['id'], 'title': b['title'], 'look': b['look']} for b in looks.BLOCKS],
                'layers': [{'id': k, 'label': label, 'default': default} for k, label, default in looks.LAYERS],
                'recommended': recommended}

    def cmd_estimate(self, place, box=None, include=None):
        self.ensure_places()
        if place not in self.by_id:
            raise ValueError(f'unknown place: {place}')
        box = timing.validate_box([float(v) for v in box]) if box else None
        include = looks.canonical_include(include or {})
        slug = places.slug(place)
        cached_pbf = country_fetch.pbf_path(self.root, slug).is_file()
        cached_tiles = country_fetch.tiles_current(country_fetch.tiles_dir(self.root, slug, box), box)
        size = None
        try:
            size = country_fetch.content_length(self.by_id[place]['pbf'])
        except OSError:
            pass
        times, reason = timing.estimate(size, box, include, cached_pbf, cached_tiles)
        return {'seconds': [round(t) for t in times] if times else None, 'stages': list(timing.STAGES),
                'reason': reason, 'pbf_bytes': size, 'cached_pbf': cached_pbf, 'cached_tiles': cached_tiles}

    # ------------------------------------------------------------------ build
    def cmd_build(self, place, box=None, look=None, include=None, project=None):
        self.ensure_places()
        if place not in self.by_id:
            raise ValueError(f'unknown place: {place}')
        box = timing.validate_box([float(v) for v in box]) if box else None
        look = looks.canonical(look) if look else None
        include = looks.canonical_include(include) if include is not None else None
        if box is not None:
            boundary = self.ensure_boundaries().get(place)
            if boundary is not None:
                from shapely.geometry import box as rectangle
                if not boundary.covers(rectangle(*box)):
                    raise ValueError('the area reaches outside the chosen source region: pick the covering region '
                                     'or a smaller rectangle')
        if not self.planet_state()['installed']:
            raise ValueError('install the planet first: the pack is read through earthng_planet.zip')
        chosen, mods = self.by_id[place], str(self.mods)

        def progress(name, seconds):
            self.send({'event': 'stage', 'name': name, 'seconds': seconds})

        def target(cancel):
            self.log(f"Building {chosen['name']}" + (f' {box}' if box else ''))
            return country_fetch.build_place(chosen, mods, root=self.root, look=look, include=include, box=box,
                                             by_id=self.by_id, emit=self.log, cancel=cancel, progress=progress)
        return self.start_job('build', target)

    # ------------------------------------------------------------------ projects
    def projects_dir(self):
        return self.root / 'projects'

    def cmd_projects(self):
        out = []
        for path in sorted(self.projects_dir().glob('*/project.json')):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                out.append({'id': data['id'], 'title': data.get('title') or data['id']})
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return {'projects': out}

    def cmd_project_save(self, project):
        project = check_project(project)
        folder = self.projects_dir() / project['id']
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / 'project.json.part'
        tmp.write_text(json.dumps(project, ensure_ascii=False, indent=1), encoding='utf-8')
        tmp.replace(folder / 'project.json')
        return {'id': project['id']}

    def cmd_project_load(self, name):
        """name: the project's id ('id' itself is the request's)."""
        if not PROJECT_ID.fullmatch(str(name)):
            raise ValueError('bad project id')
        return {'project': check_project(json.loads((self.projects_dir() / name / 'project.json').read_text(encoding='utf-8')))}


PROJECT_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,62}')


def check_project(project):
    """A project as saved: schema, id, selection, options and the edit layer (applied in a later step)."""
    if not isinstance(project, dict) or project.get('schema') != PROJECT_SCHEMA:
        raise ValueError(f'a project needs "schema": "{PROJECT_SCHEMA}"')
    if not PROJECT_ID.fullmatch(str(project.get('id', ''))):
        raise ValueError('a project id is lower-case letters, digits and dashes')
    selection = project.get('selection') or {}
    if not isinstance(selection, dict):
        raise ValueError('selection must be an object')
    if selection.get('box') is not None:
        selection['box'] = timing.validate_box([float(v) for v in selection['box']])
    if not isinstance(project.get('edits', []), list):
        raise ValueError('edits must be a list')
    project.setdefault('edits', [])
    project.setdefault('options', {})
    return project


def game_folders():
    """BeamNG user folders on this PC, newest layout first (0.40: BeamNG\\BeamNG.drive\\current)."""
    base = Path(os.environ.get('LOCALAPPDATA', ''))
    found = []
    for parent in (base / 'BeamNG' / 'BeamNG.drive', base / 'BeamNG.drive'):
        if not parent.is_dir():
            continue
        current = parent / 'current'
        if current.is_dir():
            found.append(current)
        versions = [p for p in parent.iterdir() if p.is_dir() and re.fullmatch(r'\d+\.\d+', p.name)]
        found.extend(sorted(versions, key=lambda p: [int(v) for v in p.name.split('.')], reverse=True))
    return found


def game_folder_ok(folder):
    folder = Path(folder)
    return folder.is_dir() and ((folder / 'mods').is_dir() or (folder / 'settings').is_dir())


def install_planet(source, mods, cancel=None):
    """Copy a downloaded planet into <user folder>/mods atomically, after checking it is one."""
    source = Path(source)
    with zipfile.ZipFile(source) as archive:
        manifest = json.loads(archive.read('earthng/planet/manifest.json'))
        if manifest.get('kind') != 'earthng-planet':
            raise ValueError(f'{source.name} is not an EarthNG planet')
    target_dir = Path(mods) / 'mods'
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / PLANET
    temporary = target.with_suffix('.zip.part')
    country_fetch.ensure_space(target_dir, source.stat().st_size + 2**26, f'Installing {PLANET}')
    try:
        with source.open('rb') as src, temporary.open('wb') as dst:
            country_fetch.copy_stream(src, dst, cancel)
        country_fetch.check_stopped(cancel)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def main():
    # the page reads UTF-8 lines; Windows pipes default to the ANSI code page
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8', newline='\n')
    service = Service()
    service.send({'event': 'ready', 'home': str(service.root), 'pid': os.getpid()})
    service.serve(sys.stdin)
    if service.cancel is not None:
        service.cancel.set()


if __name__ == '__main__':
    main()
