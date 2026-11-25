"""The EarthNG.exe window's backend: JSON lines on stdin, answers and events on stdout.

    python earthng/app_service.py            (EarthNG.exe starts it; docs/MAPBUILDER_APP.md)

A request is {"id": n, "cmd": "...", ...}; its answer {"id": n, "ok": true, ...} or
{"id": n, "ok": false, "error": "..."}. A job (install the planet, build a pack) answers at once
and reports with events: {"event": "log", "text"}, {"event": "stage", "name", "seconds"},
{"event": "done", "job", "result", "path"?, "error"?}. One job runs at a time.

`download_app` fetches a newer EarthNG.exe into %LOCALAPPDATA%\\EarthNG\\updates. The window then
replaces its own file and starts again. Maps, downloads and installed mods stay.

Data (PBF, tiles, DEM, packs, projects) live in EARTHNG_HOME, not beside the code: the exe's code
folder is replaced with each version. Without EARTHNG_HOME a checkout keeps using itself.
"""
from __future__ import annotations

import hashlib
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
import addons  # noqa: E402
import area_plan  # noqa: E402
import selection_build  # noqa: E402
import country_fetch  # noqa: E402
import looks  # noqa: E402
import places  # noqa: E402

RELEASES = 'https://github.com/Alezx311/earthng/releases'
# The rolling release of 0.9.x. Only the planet comes from it, for a build that carries none (a release
# exe and the Linux package bundle their own).
RELEASE_URL = f'{RELEASES}/download/EarthNG'
# Updates follow the newest published release whatever its tag (GitHub's /latest/ skips drafts and
# prereleases): its EarthNG.json names the version, and the exe is then taken from that version's own
# release, v<version>, so a release published between the check and the download changes nothing.
UPDATE_URL = f'{RELEASES}/latest/download'
APP_MANIFEST = 'EarthNG.json'   # published beside EarthNG.exe: version, sha256 and size of that file
APP_EXE = 'EarthNG.exe'
APP_SCHEMA = 'earthng-app-v1'
APP_MAX_BYTES = 4_000_000_000   # a sanity bound only: 1.1 is 647 MB (the old 500 MB bound refused it)
PLANET_STAGE = 'Planet'         # first build stage when the planet is missing or older than the packs
PLANET_SECONDS = 90             # ~270 MB from GitHub (97 s on 8.11)
ADDONS_STAGE = 'Add-ons'        # the proving ground and flora packs the player chose (addons.py), after the planet
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


def version_key(text):
    """(major, minor, patch) for a release version, or None."""
    if not isinstance(text, str) or not re.fullmatch(r'\d+\.\d+\.\d+', text):
        return None
    return tuple(int(part) for part in text.split('.'))


def app_update_decision(current, local_sha, remote):
    """'newer' when the release version is higher, 'rebuilt' when the same version was published
    again (a different sha256), otherwise 'current'. local_sha is required to notice a rebuild;
    a missing local version is treated as older than any release."""
    remote_key = version_key(remote.get('version'))
    if remote_key is None:
        raise ValueError('bad update version')
    local_key = version_key(current) if current else None
    if local_key is None or remote_key > local_key:
        return 'newer'
    if remote_key == local_key and local_sha and local_sha.lower() != remote['sha256']:
        return 'rebuilt'
    return 'current'


def exe_path():
    """The installed EarthNG.exe. Set only for a release build (rust/crates/app); a checkout has none."""
    raw = os.environ.get('EARTHNG_EXE')
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def updates_dir():
    override = os.environ.get('EARTHNG_UPDATES')
    if override:
        return Path(override)
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home())
    return base / 'EarthNG' / 'updates'


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_app_manifest(text):
    """EarthNG.json from the player release: the bytes of EarthNG.exe, not a URL to trust."""
    info = json.loads(text)
    if not isinstance(info, dict) or info.get('schema') != APP_SCHEMA:
        raise ValueError('unexpected update manifest')
    version = info.get('version')
    sha = info.get('sha256')
    size = info.get('size')
    if version_key(version) is None:
        raise ValueError('bad update version')
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise ValueError('bad update sha256')
    if isinstance(size, float) and size.is_integer():
        size = int(size)
    if not isinstance(size, int) or not 1_000_000 <= size <= APP_MAX_BYTES:
        raise ValueError('bad update size')
    parsed = {'version': version, 'sha256': sha, 'size': size}
    planet = info.get('planetVersion')
    if isinstance(planet, str):
        parsed['planetVersion'] = planet
    return parsed


def allowed_release_url(url):
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    host = (parts.hostname or '').lower()
    return parts.scheme == 'https' and (host == 'github.com' or host.endswith('.githubusercontent.com'))


def release_file_url(name, version=None):
    """EarthNG.json of the newest release, or EarthNG.exe of the release of `version` (tag v<version>)."""
    if name == APP_MANIFEST:
        return f'{UPDATE_URL}/{APP_MANIFEST}'
    if name == APP_EXE:
        if version_key(version) is None:
            raise ValueError('the exe is downloaded for a release version')
        return f'{RELEASES}/download/v{version}/{APP_EXE}'
    raise ValueError(name)


def fetch_app_manifest(url=None):
    """The release's EarthNG.json, or None when this release has not published one (HTTP 404)."""
    import urllib.error
    import urllib.request
    import tls
    url = url or release_file_url(APP_MANIFEST)
    if not allowed_release_url(url):
        raise ValueError('the update manifest is downloaded over https only')
    request = urllib.request.Request(url, headers={'User-Agent': f'{places.USER_AGENT} EarthNG.exe', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=20, context=tls.context()) as response:
            final = response.geturl()
            if not allowed_release_url(final):
                raise ValueError('unexpected update host')
            payload = response.read(1 << 20)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return parse_app_manifest(payload.decode('utf-8-sig'))


def consume_update_error():
    """A note left by the replacer when the file could not be swapped; shown once."""
    path = updates_dir() / 'error.txt'
    try:
        text = path.read_text(encoding='utf-8').strip()
        path.unlink()
    except OSError:
        return None
    return text or None


NETWORK = {'geocode', 'app_update'}


class Service:
    def __init__(self, out=None, root=None):
        self.out = out or sys.stdout
        self.root = Path(root) if root else home()
        self.lock = threading.Lock()
        self.job = None
        self.cancel = None
        self.places = None
        self.boundaries = None
        self.last_selection = None
        self.geocode_lock = threading.Lock()
        self.geocoded = 0.0
        self.settings_path = self.root / 'app_settings.json'
        self.settings = self.load_settings()
        self.addons_path = addons.CATALOG

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
            if request.get('cmd') in NETWORK:     # a slow web request never holds up status or stop
                threading.Thread(target=self.handle, args=(request,), daemon=True).start()
            else:
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
                outcome = target(cancel)
                if isinstance(outcome, dict):
                    done.update(result='complete')
                    done.update({k: v for k, v in outcome.items() if k in ('path', 'sha256', 'version', 'warnings')})
                else:
                    done.update(result='complete', path=str(outcome) if outcome else None)
            except country_fetch.NeedsPbf as exc:
                # not a failure: the page asks whether to download the country's PBF
                done.update(result='needs_pbf', reason=exc.reason, **getattr(exc, 'offer', {}))
                self.log(f'Overpass: {exc.reason}')
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
                if isinstance(saved.get('addons'), list):
                    settings['addons'] = [v for v in saved['addons'] if v in addons.KNOWN]
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
                'planet': self.planet_state(), 'addons': self.addons_state(), 'busy': bool(self.job and self.job.is_alive()),
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
        open_in_file_manager(folder)
        return {'path': str(folder)}

    # ------------------------------------------------------------------ planet
    def planet_needed(self):
        """None when the installed planet is the one this build's packs expect, else why not."""
        state = self.planet_state()
        if not state['installed']:
            return 'missing'
        if state.get('error'):
            return 'unreadable'
        if state['expected'] and state['version'] != state['expected']:
            return 'old'
        return None

    def fetch_planet(self, mods, cancel, url=None):
        """Install the bundled or adjacent planet, otherwise download it from the release."""
        program = exe_path()
        candidates = [ROOT / PLANET]
        if program:
            candidates.append(program.with_name(PLANET))
        local = next((path for path in candidates if path.is_file()), None) if url is None else None
        if local:
            with zipfile.ZipFile(local) as archive:
                manifest = json.loads(archive.read('earthng/planet/manifest.json'))
            expected = build_info().get('planetVersion')
            if expected and manifest.get('version') != expected:
                raise ValueError(f"The local planet is {manifest.get('version')}; this build needs {expected}.")
            self.log(f'Installing {PLANET} from {local.parent}')
            return install_planet(local, mods, cancel)
        url = url or f'{RELEASE_URL}/{PLANET}'
        if not url.startswith('https://'):
            raise ValueError('the planet is downloaded over https only')
        dest = self.root / 'downloads' / PLANET
        self.log(f'Downloading {PLANET} from GitHub Releases')
        country_fetch.download(url, dest, self.log, cancel)
        target = install_planet(dest, mods, cancel)
        state = self.planet_state()
        if state['expected'] and state['version'] != state['expected']:
            self.log(f"warning: the release has planet {state['version']}, this EarthNG expects {state['expected']}")
        self.log(f"installed {PLANET} {state['version'] or ''}".rstrip())
        return target

    def cmd_install_planet(self, url=None):
        if url is not None and not str(url).startswith('https://'):
            raise ValueError('the planet is downloaded over https only')
        mods = self.mods

        def target(cancel):
            if not game_folder_ok(mods):
                raise ValueError(f'{mods} is not a BeamNG user folder (it has no mods folder or settings)')
            self.send({'event': 'stage', 'name': PLANET_STAGE, 'seconds': None})
            start = time.monotonic()
            path = self.fetch_planet(mods, cancel, url)
            self.send({'event': 'stage', 'name': PLANET_STAGE, 'seconds': time.monotonic() - start})
            return with_warnings(path, self.install_addons(mods, cancel))
        return self.start_job('install_planet', target)

    # ------------------------------------------------------------------ add-ons (addons.py)
    def addon_catalog(self):
        return addons.load(self.addons_path)

    def chosen_addons(self):
        """The packs the player wants beside the planet: every one the runtime offers until they choose."""
        chosen = self.settings.get('addons')
        return set(chosen) if isinstance(chosen, list) else set(addons.KNOWN)

    def addons_state(self, mods=None):
        mods = Path(mods) if mods else self.mods
        chosen = self.chosen_addons()
        return [{'id': e['id'], 'size': e['size'], 'state': addons.state(e, mods), 'chosen': e['id'] in chosen}
                for e in self.addon_catalog()]

    def addons_pending(self, mods=None):
        """Chosen packs that are not in mods yet, or are another build of them there."""
        mods = Path(mods) if mods else self.mods
        chosen = self.chosen_addons()
        return [e for e in self.addon_catalog() if e['id'] in chosen and addons.state(e, mods) != 'installed']

    def cmd_set_addons(self, chosen):
        if not isinstance(chosen, list) or any(c not in addons.KNOWN for c in chosen):
            raise ValueError('chosen is a list of add-on ids')
        self.settings['addons'] = [k for k in addons.KNOWN if k in chosen]
        self.save_settings()
        return {'addons': self.addons_state()}

    def install_addons(self, mods, cancel, strict=False):
        """Install the chosen packs that are missing, as a stage of the job that installs the planet.
        A pack that fails is a warning there (the map still builds); strict raises it."""
        pending = self.addons_pending(mods)
        warnings = []
        if not pending:
            return warnings
        self.send({'event': 'stage', 'name': ADDONS_STAGE, 'seconds': None})
        start = time.monotonic()
        for entry in pending:
            try:
                addons.fetch(entry, self.root, mods, self.log, cancel)
            except InterruptedError:
                raise
            except Exception as exc:  # noqa: BLE001 - a missing add-on never costs the map
                if strict:
                    raise
                reason = str(exc) or type(exc).__name__
                warnings.append(f"{entry['file']}: {reason}")
                self.log(f"warning: {entry['file']} was not installed: {reason}")
        self.send({'event': 'stage', 'name': ADDONS_STAGE, 'seconds': time.monotonic() - start})
        return warnings

    def cmd_install_addons(self):
        """Install the chosen packs now (the planet first, if it is not the one they go with)."""
        if not self.addons_pending():
            raise ValueError('the chosen add-ons are already installed')
        mods = self.mods

        def target(cancel):
            if not game_folder_ok(mods):
                raise ValueError(f'{mods} is not a BeamNG user folder (it has no mods folder or settings)')
            if self.planet_needed():
                self.send({'event': 'stage', 'name': PLANET_STAGE, 'seconds': None})
                start = time.monotonic()
                self.fetch_planet(mods, cancel)
                self.send({'event': 'stage', 'name': PLANET_STAGE, 'seconds': time.monotonic() - start})
            self.install_addons(mods, cancel, strict=True)
            return mods / 'mods'
        return self.start_job('install_addons', target)

    def lead_stages(self):
        """The stages a build runs before its own: the planet, then the chosen add-ons."""
        stages, seconds = [], []
        planet = self.planet_needed()
        if planet:
            stages.append(PLANET_STAGE)
            seconds.append(PLANET_SECONDS)
        pending = self.addons_pending()
        if pending:
            stages.append(ADDONS_STAGE)
            seconds.append(addons.seconds(pending))
        return stages, seconds, planet, [e['id'] for e in pending]

    def cmd_app_update(self):
        """Whether the published EarthNG.exe is newer than this one. A checkout reports 'checkout'
        and does not call GitHub: replacing rust/target is not an install."""
        current = build_info().get('version')
        report = {'current': current, 'available': False, 'error': consume_update_error()}
        if os.environ.get('EARTHNG_PACKAGE') == 'linux':
            # the Linux package (app_web.py) replaces itself only by a new download from the release
            report['reason'] = 'linux'
            return report
        if exe_path() is None:
            report['reason'] = 'checkout'
            return report
        try:
            remote = fetch_app_manifest()
        except (OSError, ValueError) as exc:
            report['reason'] = 'offline'
            report['detail'] = str(exc) or type(exc).__name__
            return report
        if remote is None:
            report['reason'] = 'no-manifest'
            return report
        local_sha = file_sha256(exe_path()) if version_key(current) == version_key(remote['version']) else None
        reason = app_update_decision(current, local_sha, remote)
        report.update(version=remote['version'], size=remote['size'], reason=reason,
                      available=reason in ('newer', 'rebuilt'))
        return report

    def cmd_download_app(self):
        """Download EarthNG.exe from the player release, check its size and sha256, and leave
        EarthNG.json beside it for the window to swap in."""
        if exe_path() is None:
            raise ValueError('updates apply to the installed EarthNG.exe')

        def target(cancel):
            remote = fetch_app_manifest()
            if remote is None:
                raise ValueError('this release has no update manifest')
            current = build_info().get('version')
            installed = exe_path()
            local_sha = file_sha256(installed) if version_key(current) == version_key(remote['version']) else None
            if app_update_decision(current, local_sha, remote) == 'current':
                raise ValueError('this EarthNG is already current')
            folder = updates_dir()
            folder.mkdir(parents=True, exist_ok=True)
            country_fetch.ensure_space(folder, remote['size'] + 2**26, 'Updating EarthNG')
            dest = folder / APP_EXE
            self.log(f"Downloading {APP_EXE} {remote['version']} from GitHub Releases")
            country_fetch.download(release_file_url(APP_EXE, remote['version']), dest, self.log, cancel)
            if dest.stat().st_size != remote['size']:
                dest.unlink(missing_ok=True)
                raise ValueError(f"downloaded size does not match the release ({remote['size']} bytes)")
            digest = file_sha256(dest)
            if digest != remote['sha256']:
                dest.unlink(missing_ok=True)
                raise ValueError('downloaded file does not match the release')
            with dest.open('rb') as stream:
                if stream.read(2) != b'MZ':
                    dest.unlink(missing_ok=True)
                    raise ValueError('downloaded file is not a Windows program')
            sidecar = {'schema': APP_SCHEMA, 'version': remote['version'], 'sha256': digest, 'size': remote['size']}
            (folder / APP_MANIFEST).write_text(json.dumps(sidecar, indent=2) + '\n', encoding='utf-8')
            self.log(f"Downloaded {APP_EXE} {remote['version']}")
            return {'path': str(dest), 'version': remote['version'], 'sha256': digest}
        return self.start_job('download_app', target)

    def cmd_stop(self):
        if self.cancel is not None:
            self.cancel.set()
        return {'stopping': bool(self.job and self.job.is_alive())}

    def cmd_ready_packs(self):
        packs = []
        for entry in country_fetch.catalog_entries():
            slug = entry['id']
            if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', slug):
                continue
            available = country_fetch.availability(slug, self.mods, self.root)
            if available['state'] != 'none':
                packs.append({'id': slug, 'title': entry['title'], 'state': available['state']})
        return {'packs': packs}

    def cmd_install_ready_pack(self, pack):
        entries = {e['id']: e for e in self.cmd_ready_packs()['packs']}
        if pack not in entries:
            raise ValueError('unknown ready pack')
        mods = self.mods

        def target(cancel):
            if not game_folder_ok(mods):
                raise ValueError(f'{mods} is not a BeamNG user folder (it has no mods folder or settings)')
            if self.planet_needed():
                self.send({'event': 'stage', 'name': 'Planet', 'seconds': None})
                self.fetch_planet(mods, cancel)
                self.send({'event': 'stage', 'name': 'Planet', 'seconds': 0})
            warnings = self.install_addons(mods, cancel)
            self.send({'event': 'stage', 'name': 'Install', 'seconds': None})
            source = country_fetch.availability(pack, mods, self.root)
            if source['state'] == 'installed':
                target_path = source['path']
            else:
                if source['state'] == 'url':
                    archive = self.root / 'downloads' / f'earthng_{pack}.zip'
                    country_fetch.download(source['url'], archive, self.log, cancel)
                elif source['state'] == 'local':
                    archive = source['path']
                else:
                    raise ValueError('ready pack is no longer available')
                target_path = country_fetch.install_zip(archive, mods, pack, cancel=cancel)
            self.send({'event': 'stage', 'name': 'Install', 'seconds': 0})
            return with_warnings(target_path, warnings)
        return self.start_job('install_ready_pack', target)

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

    def cmd_geocode(self, query, lang='en'):
        """Cities and addresses from OpenStreetMap's Nominatim: one request per search (Enter),
        never per keystroke, as its usage policy asks."""
        import urllib.parse
        import urllib.request
        import tls
        query = str(query).strip()
        if not query:
            return {'results': []}
        with self.geocode_lock:                                  # at most one request a second
            wait = self.geocoded + 1.0 - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.geocoded = time.monotonic()
        url = 'https://nominatim.openstreetmap.org/search?' + urllib.parse.urlencode(
            {'q': query, 'format': 'jsonv2', 'limit': 6, 'accept-language': lang})
        request = urllib.request.Request(url, headers={'User-Agent': f'{places.USER_AGENT} EarthNG.exe'})
        with urllib.request.urlopen(request, timeout=20, context=tls.context()) as response:
            found = json.loads(response.read())
        out = []
        for item in found:
            try:
                s, n, w, e = (float(v) for v in item['boundingbox'])
                out.append({'name': item.get('display_name', ''), 'lat': float(item['lat']), 'lon': float(item['lon']),
                            'bounds': [w, s, e, n], 'kind': item.get('type') or item.get('category') or ''})
            except (KeyError, TypeError, ValueError):
                continue
        return {'results': out}

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

    def selection_plan(self, selection):
        if not isinstance(selection, dict):
            raise ValueError('Select a rectangle or a route.')
        key = json.dumps(selection, sort_keys=True)
        if self.last_selection and self.last_selection[0] == key:
            return self.last_selection[1]
        self.ensure_places()
        plan = area_plan.plan(self.ensure_boundaries(), self.by_id, box=selection.get('box'),
                              route=selection.get('route'), width_km=selection.get('width_km', 10))
        if not plan['parts']:
            raise ValueError('No regional source covers this selection.')
        self.last_selection = (key, plan)
        return plan

    def cmd_plan_area(self, selection):
        plan = self.selection_plan(selection)
        ids = dict.fromkeys(part['place'] for part in plan['parts'])
        sources = [{'id': k, 'name': self.by_id[k]['name'],
                    'parent': places.parent_name(self.by_id[k], self.by_id)} for k in ids]
        return {k: plan[k] for k in ('km2', 'uncovered_km2', 'geojson', 'bounds')} | {
            'place': sources[0], 'sources': sources, 'part_count': len(plan['parts'])}

    def cmd_options(self, place=None):
        self.ensure_places()
        recommended = looks.recommended(place, self.by_id) if place in self.by_id else looks.canonical({'block': 'general'})
        return {'slots': {slot: [{'id': k, 'label': v} for k, v in choices.items()] for slot, choices in looks.SLOTS.items()},
                'slot_labels': looks.SLOT_LABELS,
                'blocks': [{'id': b['id'], 'title': b['title'], 'look': b['look']} for b in looks.BLOCKS],
                'layers': [{'id': k, 'label': label, 'default': default} for k, label, default in looks.LAYERS],
                'recommended': recommended}

    def cmd_estimate(self, place=None, box=None, include=None, selection=None):
        if selection is not None:
            return self.selection_estimate(self.selection_plan(selection), looks.canonical_include(include or {}))
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
        source = self.source_of(box, cached_pbf, cached_tiles, size)
        times, reason = timing.estimate(size, box, include, cached_pbf, cached_tiles,
                                        overpass=country_fetch.overpass_km2(box) if source == 'overpass' else None)
        lead, lead_seconds, planet, pending = self.lead_stages()     # the build installs these first
        stages = lead + list(timing.STAGES)
        seconds = lead_seconds + [round(t) for t in times] if times else None
        return {'seconds': seconds, 'stages': stages, 'planet': planet, 'addons': pending,
                'reason': reason, 'pbf_bytes': size, 'cached_pbf': cached_pbf, 'cached_tiles': cached_tiles,
                'source': source, 'pbf_seconds': self.pbf_seconds(size, box, include),
                # the page asks before a large country file is downloaded; a small one just comes
                'ask_pbf': source == 'pbf' and not cached_pbf and not country_fetch.small_pbf(size)}

    def selection_estimate(self, plan, include):
        import sections
        from concurrent.futures import ThreadPoolExecutor
        parts = plan['parts']
        ids = list(dict.fromkeys(part['place'] for part in parts))
        sizes, local = {}, {}
        for key in ids:
            pbf = country_fetch.pbf_path(self.root, places.slug(key))
            local[key] = pbf.is_file()
            sizes[key] = pbf.stat().st_size if local[key] else None
        missing = [k for k in ids if not local[k]]
        # A world selection remains usable without querying hundreds of remote file sizes.
        if 0 < len(missing) <= 12:
            with ThreadPoolExecutor(max_workers=4) as pool:
                sizes.update(zip(missing, pool.map(lambda k: country_fetch.pbf_size(self.by_id[k], 5), missing)))
        totals = [0.0] * len(timing.STAGES)
        modes, downloads = set(), set()
        known = True
        for part in parts:
            key = part['place']
            box = sections.box(part['section'])
            cached = country_fetch.tiles_current(country_fetch.tiles_dir(self.root, places.slug(key), box), box)
            mode = self.source_of(box, local[key], cached, sizes[key]) if len(parts) == 1 else ('tiles' if cached else 'pbf')
            modes.add(mode)
            times, _ = timing.estimate(sizes[key], box, include, local[key] or key in downloads, cached,
                                       overpass=country_fetch.overpass_km2(box) if mode == 'overpass' else None)
            if mode == 'pbf' and not local[key]:
                downloads.add(key)
            if times:
                totals = [a + b for a, b in zip(totals, times)]
            else:
                known = False
        lead, lead_seconds, planet, pending = self.lead_stages()
        stages = lead + list(timing.STAGES)
        totals = lead_seconds + totals
        size = sum(sizes[k] for k in downloads) if all(sizes[k] for k in downloads) else None
        return {'seconds': [round(v) for v in totals] if known else None, 'stages': stages, 'planet': planet,
                'addons': pending,
                'reason': '—', 'pbf_bytes': size, 'cached_pbf': all(local.values()), 'cached_tiles': modes == {'tiles'},
                'source': 'pbf' if 'pbf' in modes else next(iter(modes)), 'pbf_seconds': None,
                'ask_pbf': any(not country_fetch.small_pbf(sizes[k]) for k in downloads)}

    @staticmethod
    def source_of(box, cached_pbf, cached_tiles, size=None):
        """Where a build's OSM data comes from (country_fetch.tile_source): 'tiles' already cut,
        'overpass' for the area alone, or 'pbf', the country's file (on disk, small, or large and
        asked for)."""
        if cached_tiles:
            return 'tiles'
        if box is None or cached_pbf or country_fetch.small_pbf(size) \
                or country_fetch.overpass_km2(box) > country_fetch.OVERPASS_MAX_KM2:
            return 'pbf'
        return 'overpass'

    @staticmethod
    def pbf_seconds(size, box, include):
        """Download and cut of the country's PBF: what the page shows before asking to download it."""
        times, _ = timing.estimate(size, box, include)
        return round(times[0] + times[1]) if times else None

    # ------------------------------------------------------------------ build
    def cmd_build(self, place=None, box=None, look=None, include=None, project=None, allow_pbf=False, selection=None):
        """allow_pbf: the user agreed to download the country's PBF. Without it a selection comes
        from Overpass, and a done event with result 'needs_pbf' asks for that agreement."""
        self.ensure_places()
        plan = self.selection_plan(selection) if selection is not None else None
        if plan:
            place = plan['parts'][0]['place']
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
        if not game_folder_ok(self.mods):
            raise ValueError(f'{self.mods} is not a BeamNG user folder: choose it in Settings')
        chosen, mods = self.by_id[place], str(self.mods)
        planet = self.planet_needed()

        def progress(name, seconds):
            self.send({'event': 'stage', 'name': name, 'seconds': seconds})

        def target(cancel):
            if planet:          # the pack is read through earthng_planet.zip: install it with the pack
                progress(PLANET_STAGE, None)
                start = time.monotonic()
                self.fetch_planet(Path(mods), cancel)
                progress(PLANET_STAGE, time.monotonic() - start)
            warnings = self.install_addons(Path(mods), cancel)
            return with_warnings(build_area(cancel), warnings)

        def build_area(cancel):
            if plan:
                def part(i, total, name):
                    self.send({'event': 'part', 'index': i, 'total': total, 'name': name})
                if len(plan['parts']) > 1 and not allow_pbf:
                    estimate = self.selection_estimate(plan, include or {})
                    if estimate['ask_pbf']:
                        offer = country_fetch.NeedsPbf('Regional source files are needed for this selection.')
                        offer.offer = {'name': ', '.join(self.by_id[k]['name'] for k in
                                                         dict.fromkeys(p['place'] for p in plan['parts'])),
                                       'pbf_bytes': estimate['pbf_bytes']}
                        raise offer
                paths = selection_build.build(plan, self.by_id, mods, self.root, look=look, include=include,
                                              allow_pbf=allow_pbf or len(plan['parts']) > 1,
                                              emit=self.log, cancel=cancel, progress=progress, on_part=part)
                return paths[0] if len(paths) == 1 else paths[0].parent
            self.log(f"Building {chosen['name']}" + (f' {box}' if box else ''))
            try:
                return country_fetch.build_place(chosen, mods, root=self.root, look=look, include=include, box=box,
                                                 by_id=self.by_id, emit=self.log, cancel=cancel, progress=progress,
                                                 allow_pbf=bool(allow_pbf))
            except country_fetch.NeedsPbf as exc:
                size = None
                try:
                    size = country_fetch.content_length(chosen['pbf'])
                except OSError:
                    pass
                exc.offer = {'place': place, 'name': chosen['name'], 'pbf_bytes': size,
                             'pbf_seconds': self.pbf_seconds(size, box, looks.canonical_include(include or {}))}
                raise
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
    if selection.get('route') is not None:
        if selection.get('box') is not None:
            raise ValueError('Select a rectangle or a route, not both.')
        selection['route'], selection['width_km'] = area_plan.validate_route(selection['route'], selection.get('width_km', 10))
    elif selection.get('box') is not None:
        box = [float(v) for v in selection['box']]
        if len(box) == 4 and box[0] > box[2]:
            timing.validate_box([box[2], box[1], box[0], box[3]])
            selection['box'] = box
        else:
            selection['box'] = timing.validate_box(box)
    if not isinstance(project.get('edits', []), list):
        raise ValueError('edits must be a list')
    project.setdefault('edits', [])
    project.setdefault('options', {})
    return project


def with_warnings(outcome, warnings):
    """A job's result with the add-ons it could not install, for the done event."""
    if not warnings:
        return outcome
    return {'path': str(outcome) if outcome else None, 'warnings': warnings}


def game_folders(env=None, home=None, nt=None):
    """BeamNG user folders on this PC, newest layout first (0.40: BeamNG\\BeamNG.drive\\current);
    on Linux the native client's, then the Proton prefix's (country_fetch.user_folder_bases)."""
    found = []
    for base in country_fetch.user_folder_bases(env, home, nt):
        for parent in (base / 'BeamNG' / 'BeamNG.drive', base / 'BeamNG.drive'):
            if not parent.is_dir():
                continue
            current = parent / 'current'
            if current.is_dir():
                found.append(current)
            versions = [p for p in parent.iterdir() if p.is_dir() and re.fullmatch(r'\d+\.\d+', p.name)]
            found.extend(sorted(versions, key=lambda p: [int(v) for v in p.name.split('.')], reverse=True))
    return found


def open_in_file_manager(folder):
    """Show a folder of the user's: Explorer on Windows, xdg-open on Linux, open on macOS."""
    if os.name == 'nt':
        os.startfile(folder)  # noqa: S606 - the user's own folder
        return
    import subprocess
    opener = 'open' if sys.platform == 'darwin' else 'xdg-open'
    if shutil.which(opener):
        subprocess.Popen([opener, str(folder)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,  # noqa: S603
                         stderr=subprocess.DEVNULL, start_new_session=True)


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


def protocol_streams():
    """Private copies of the page's pipes; fds 0 and 1 then point at NUL and at stderr (the log).
    Every child of this service inherits the standard handles. A child that gets our stdin pipe
    hangs in its interpreter start-up: it seeks the handle, and Windows holds that query until the
    read our main thread has pending on the same pipe returns, i.e. until the page sends a line.
    A child's stray print to our stdout would also land in the protocol."""
    inp = os.fdopen(os.dup(0), 'r', encoding='utf-8', errors='replace')
    out = os.fdopen(os.dup(1), 'w', encoding='utf-8', newline='\n')
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    os.dup2(2, 1)
    sys.stdin = open(os.devnull, encoding='utf-8')
    sys.stdout = sys.stderr
    return inp, out


def main():
    inp, out = protocol_streams()       # the page reads UTF-8 lines, not the ANSI code page
    service = Service(out=out)
    service.send({'event': 'ready', 'home': str(service.root), 'pid': os.getpid()})
    service.serve(inp)
    if service.cancel is not None:
        service.cancel.set()


if __name__ == '__main__':
    main()
