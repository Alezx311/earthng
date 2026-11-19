"""EarthNG.exe backend: protocol, game folder, planet install, projects (no network)."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

import app_service

HERE = Path(__file__).resolve().parent


def planet_zip(path, version='0.7.0', kind='earthng-planet'):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('earthng/planet/manifest.json', json.dumps({'kind': kind, 'version': version}))
        archive.writestr('lua/ge/extensions/e2r/world.lua', '-- planet')
    return path


class Recorder(io.StringIO):
    def messages(self):
        return [json.loads(line) for line in self.getvalue().splitlines()]


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.game = self.root / 'BeamNG' / 'current'
        (self.game / 'mods').mkdir(parents=True)
        self.out = Recorder()
        with patch.object(app_service.country_fetch, 'default_mods', return_value=self.game):
            self.service = app_service.Service(out=self.out, root=self.root / 'home')

    def tearDown(self):
        self.tmp.cleanup()

    def ask(self, **request):
        self.service.handle({'id': 7, **request})
        return self.out.messages()[-1]

    def wait_done(self):
        self.service.job.join(30)
        return [m for m in self.out.messages() if m.get('event') == 'done'][-1]

    def test_answers_carry_the_request_id_and_errors_do_not_stop_the_loop(self):
        self.service.serve(['{"id": 1, "cmd": "nope"}', 'not json', '{"id": 2, "cmd": "stop"}'])
        first, second, third = self.out.messages()
        self.assertEqual((first['id'], first['ok']), (1, False))
        self.assertIn('unknown command', first['error'])
        self.assertFalse(second['ok'])
        self.assertEqual((third['id'], third['ok']), (2, True))

    def test_status_reports_the_game_folder_and_a_missing_planet(self):
        status = self.ask(cmd='status')
        self.assertTrue(status['ok'])
        self.assertEqual(status['mods'], str(self.game))
        self.assertTrue(status['game_folder_ok'])
        self.assertFalse(status['planet']['installed'])

    def test_ready_pack_installs_catalogued_local_zip_and_keeps_planet(self):
        local = self.service.root / 'out' / 'native-packs'
        local.mkdir(parents=True)
        source = local / 'earthng_albania.zip'
        with zipfile.ZipFile(source, 'w') as archive:
            archive.writestr('earthng/countries/albania/manifest.json', '{}')
        planet_zip(self.game / 'mods' / app_service.PLANET)
        catalog = [{'id': 'albania', 'title': 'Albania', 'url': ''},
                   {'id': '../bad', 'title': 'Bad', 'url': 'https://example.org/bad'}]
        with patch.object(app_service.country_fetch, 'catalog_entries', return_value=catalog):
            self.assertEqual(self.ask(cmd='ready_packs')['packs'], [{'id': 'albania', 'title': 'Albania', 'state': 'local'}])
            self.assertFalse(self.ask(cmd='install_ready_pack', pack='../bad')['ok'])
            self.assertTrue(self.ask(cmd='install_ready_pack', pack='albania')['ok'])
            done = self.wait_done()
            self.assertEqual(done['result'], 'complete', done)
            self.assertEqual((self.game / 'mods' / source.name).read_bytes(), source.read_bytes())
            self.assertEqual(self.ask(cmd='ready_packs')['packs'][0]['state'], 'installed')

    def test_ready_pack_downloads_and_installs_planet_first(self):
        catalog = [{'id': 'albania', 'title': 'Albania', 'url': 'https://example.org/albania.zip'}]
        downloaded = []

        def download(url, dest, emit=print, cancel=None):
            downloaded.append(url)
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            if url.endswith(app_service.PLANET):
                planet_zip(dest)
            else:
                with zipfile.ZipFile(dest, 'w') as archive:
                    archive.writestr('earthng/countries/albania/manifest.json', '{}')
            return dest

        with patch.object(app_service.country_fetch, 'catalog_entries', return_value=catalog), \
             patch.object(app_service.country_fetch, 'download', side_effect=download):
            self.assertTrue(self.ask(cmd='install_ready_pack', pack='albania')['ok'])
            done = self.wait_done()
        self.assertEqual(done['result'], 'complete', done)
        self.assertTrue(downloaded[0].endswith(app_service.PLANET))
        self.assertEqual(downloaded[1], catalog[0]['url'])
        self.assertTrue((self.game / 'mods' / 'earthng_albania.zip').exists())

    def test_game_folder_choice_is_kept(self):
        other = self.root / 'other'
        (other / 'settings').mkdir(parents=True)
        self.assertTrue(self.ask(cmd='set_game_folder', path=str(other))['game_folder_ok'])
        with patch.object(app_service.country_fetch, 'default_mods', return_value=self.game):
            again = app_service.Service(out=Recorder(), root=self.root / 'home')
        self.assertEqual(again.mods, other)
        self.assertFalse(self.ask(cmd='set_game_folder', path=str(self.root / 'missing'))['ok'])

    def test_planet_install_downloads_checks_and_replaces_atomically(self):
        source = planet_zip(self.root / 'served.zip', '0.7.1')

        def fake_download(url, dest, emit=print, cancel=None):
            self.assertEqual(url, f'{app_service.RELEASE_URL}/{app_service.PLANET}')
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(source.read_bytes())
            return dest
        with patch.object(app_service.country_fetch, 'download', side_effect=fake_download):
            self.assertTrue(self.ask(cmd='install_planet')['ok'])
            done = self.wait_done()
        self.assertEqual(done['result'], 'complete', done)
        self.assertEqual(self.ask(cmd='status')['planet']['version'], '0.7.1')
        self.assertFalse((self.game / 'mods' / 'earthng_planet.zip.part').exists())

    def test_a_zip_that_is_not_a_planet_is_not_installed(self):
        with self.assertRaises(ValueError):
            app_service.install_planet(planet_zip(self.root / 'x.zip', kind='earthng-country'), self.game)
        self.assertFalse((self.game / 'mods' / 'earthng_planet.zip').exists())

    def test_one_job_at_a_time_and_stop(self):
        started, release = threading.Event(), threading.Event()

        def slow(cancel):
            started.set()
            while not cancel.is_set():
                release.wait(.01)
            raise InterruptedError
        self.service.start_job('slow', slow)
        started.wait(5)
        with self.assertRaises(RuntimeError):
            self.service.start_job('second', slow)
        self.assertTrue(self.ask(cmd='stop')['stopping'])
        self.assertEqual(self.wait_done()['result'], 'stopped')

    def test_a_build_installs_a_missing_planet_first(self):
        self.service.places = [{'id': 'albania', 'name': 'Albania', 'pbf': 'https://x/albania.osm.pbf'}]
        self.service.by_id = {'albania': self.service.places[0]}
        self.service.boundaries = {}
        source = planet_zip(self.root / 'served.zip', '0.7.0')
        order = []

        def fake_download(url, dest, emit=print, cancel=None):
            order.append('planet')
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(source.read_bytes())
            return dest

        def fake_build(place, mods, **kw):
            order.append(('build', (Path(mods) / 'mods' / 'earthng_planet.zip').is_file()))
            return Path(mods) / 'mods' / 'earthng_albania.zip'
        with patch.object(app_service, 'build_info', return_value={'planetVersion': '0.7.0'}),                 patch.object(app_service.country_fetch, 'download', side_effect=fake_download),                 patch.object(app_service.country_fetch, 'build_place', side_effect=fake_build):
            self.assertEqual(self.service.planet_needed(), 'missing')
            self.assertTrue(self.ask(cmd='build', place='albania', box=[19.8, 41.3, 19.9, 41.35])['ok'])
            done = self.wait_done()
            self.assertEqual(done['result'], 'complete', done)
            self.assertEqual(order, ['planet', ('build', True)])
            stages = [(m['name'], m['seconds'] is None) for m in self.out.messages() if m.get('event') == 'stage']
            self.assertEqual(stages, [('Planet', True), ('Planet', False)])
            self.assertIsNone(self.service.planet_needed())
            # an installed planet of the expected version is not fetched again
            self.assertTrue(self.ask(cmd='build', place='albania', box=[19.8, 41.3, 19.9, 41.35])['ok'])
            self.wait_done()
            self.assertEqual(order.count('planet'), 1)

    def test_an_older_planet_is_replaced_by_the_build(self):
        planet_zip(self.game / 'mods' / 'earthng_planet.zip', '0.6.0')
        with patch.object(app_service, 'build_info', return_value={'planetVersion': '0.7.0'}):
            self.assertEqual(self.service.planet_needed(), 'old')

    def test_release_installs_its_adjacent_planet_without_network(self):
        folder = self.root / 'release'
        folder.mkdir()
        exe = folder / 'EarthNG.exe'
        exe.write_bytes(b'MZ test')
        planet_zip(folder / app_service.PLANET, '1.0.0')
        with patch.object(app_service, 'exe_path', return_value=exe), \
                patch.object(app_service, 'build_info', return_value={'planetVersion': '1.0.0'}), \
                patch.object(app_service.country_fetch, 'download', side_effect=AssertionError('network')):
            self.service.fetch_planet(self.game, threading.Event())
            self.assertIsNone(self.service.planet_needed())
            planet_zip(folder / app_service.PLANET, '0.9.0')
            with self.assertRaisesRegex(ValueError, 'needs 1.0.0'):
                self.service.fetch_planet(self.game, threading.Event())

    def test_single_file_release_installs_bundled_planet_before_an_old_sidecar(self):
        runtime = self.root / 'runtime'
        runtime.mkdir()
        planet_zip(runtime / app_service.PLANET, '1.0.0')
        folder = self.root / 'download'
        folder.mkdir()
        exe = folder / 'EarthNG.exe'
        exe.write_bytes(b'MZ test')
        planet_zip(folder / app_service.PLANET, '0.9.0')
        with patch.object(app_service, 'ROOT', runtime), \
                patch.object(app_service, 'exe_path', return_value=exe), \
                patch.object(app_service, 'build_info', return_value={'planetVersion': '1.0.0'}), \
                patch.object(app_service.country_fetch, 'download', side_effect=AssertionError('network')):
            self.service.fetch_planet(self.game, threading.Event())
            self.assertIsNone(self.service.planet_needed())

    def test_a_build_needs_a_game_folder(self):
        self.service.places = [{'id': 'albania', 'name': 'Albania', 'pbf': 'https://x/albania.osm.pbf'}]
        self.service.by_id = {'albania': self.service.places[0]}
        self.service.boundaries = {}
        with patch.object(app_service, 'game_folder_ok', return_value=False):
            answer = self.ask(cmd='build', place='albania', box=[19.8, 41.3, 19.9, 41.35])
        self.assertFalse(answer['ok'])
        self.assertIn('BeamNG user folder', answer['error'])

    def albania(self):
        self.service.places = [{'id': 'albania', 'name': 'Albania', 'pbf': 'https://x/albania.osm.pbf'}]
        self.service.by_id = {'albania': self.service.places[0]}
        self.service.boundaries = {}

    def test_without_overpass_the_build_asks_to_download_the_pbf(self):
        self.albania()
        calls = []

        def fake_build(place, mods, **kw):
            calls.append(kw['allow_pbf'])
            if not kw['allow_pbf']:
                raise app_service.country_fetch.NeedsPbf('Overpass did not answer: overpass-api.de: HTTP Error 504')
            return Path(mods) / 'mods' / 'earthng_albania.zip'
        with patch.object(self.service, 'planet_needed', return_value=None),                 patch.object(app_service.country_fetch, 'content_length', return_value=54_466_814),                 patch.object(app_service.country_fetch, 'build_place', side_effect=fake_build):
            self.assertTrue(self.ask(cmd='build', place='albania', box=[19.8, 41.3, 19.84, 41.33])['ok'])
            done = self.wait_done()
            self.assertEqual(done['result'], 'needs_pbf', done)
            self.assertIn('504', done['reason'])
            self.assertEqual((done['place'], done['name'], done['pbf_bytes']), ('albania', 'Albania', 54_466_814))
            self.assertGreater(done['pbf_seconds'], 0)
            self.assertTrue(self.ask(cmd='build', place='albania', box=[19.8, 41.3, 19.84, 41.33], allow_pbf=True)['ok'])
            self.assertEqual(self.wait_done()['result'], 'complete')
        self.assertEqual(calls, [False, True])

    def test_the_estimate_names_the_source(self):
        self.albania()
        town = [19.8, 41.3, 19.84, 41.33]
        with patch.object(app_service.country_fetch, 'content_length', return_value=900 * 2**20):
            small = self.ask(cmd='estimate', place='albania', box=town)
            big = self.ask(cmd='estimate', place='albania', box=[19.5, 41.0, 20.0, 41.5])
            whole = self.ask(cmd='estimate', place='albania')
        with patch.object(app_service.country_fetch, 'content_length', return_value=54_466_814):
            little = self.ask(cmd='estimate', place='albania', box=town)      # a small country file
            pbf = app_service.country_fetch.pbf_path(self.service.root, 'albania')
            pbf.parent.mkdir(parents=True, exist_ok=True)
            pbf.write_bytes(b'x')
            cached = self.ask(cmd='estimate', place='albania', box=town)
        self.assertEqual([a['source'] for a in (small, big, whole, little, cached)],
                         ['overpass', 'pbf', 'pbf', 'pbf', 'pbf'])
        # asked first: only a large file not on disk, known to be needed before Overpass is tried
        self.assertEqual([a['ask_pbf'] for a in (small, big, whole, little, cached)],
                         [False, True, True, False, False])
        self.assertTrue(cached['cached_pbf'])
        for answer in (small, big, whole, little):
            self.assertGreater(answer['pbf_seconds'], 0)
            self.assertTrue(answer['seconds'])

    def test_geocode_turns_nominatim_rows_into_boxes(self):
        rows = [{'display_name': 'Tirana, Albania', 'lat': '41.3275', 'lon': '19.8189', 'type': 'city',
                 'boundingbox': ['41.28', '41.37', '19.75', '19.88']},
                {'display_name': 'broken'}]

        class Reply(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        seen = []

        def urlopen(request, timeout, context):
            seen.append(request)
            return Reply(json.dumps(rows).encode())

        with patch('urllib.request.urlopen', urlopen):
            answer = self.ask(cmd='geocode', query='Тирана', lang='uk')
        self.assertTrue(answer['ok'], answer)
        self.assertEqual(answer['results'], [{'name': 'Tirana, Albania', 'lat': 41.3275, 'lon': 19.8189,
                                              'bounds': [19.75, 41.28, 19.88, 41.37], 'kind': 'city'}])
        self.assertIn('format=jsonv2', seen[0].full_url)
        self.assertIn('EarthNG', seen[0].get_header('User-agent'))
        self.assertEqual(self.ask(cmd='geocode', query='  ')['results'], [])

    def test_projects_round_trip_with_their_edit_layer(self):
        project = {'schema': app_service.PROJECT_SCHEMA, 'id': 'tirana-centre', 'title': 'Tirana',
                   'selection': {'place': 'albania', 'box': [19.8, 41.3, 19.85, 41.34]},
                   'edits': [{'op': 'add', 'kind': 'bench', 'lat': 41.32, 'lon': 19.82}]}
        self.assertTrue(self.ask(cmd='project_save', project=project)['ok'])
        self.assertEqual(self.ask(cmd='projects')['projects'], [{'id': 'tirana-centre', 'title': 'Tirana'}])
        loaded = self.ask(cmd='project_load', name='tirana-centre')['project']
        self.assertEqual(loaded['edits'], project['edits'])
        self.assertFalse(self.ask(cmd='project_save', project={**project, 'id': '../x'})['ok'])
        self.assertFalse(self.ask(cmd='project_load', name='..')['ok'])

    def test_update_decision_is_newer_rebuilt_or_current(self):
        remote = {'version': '0.9.0', 'sha256': 'ab' * 32}
        self.assertEqual(app_service.app_update_decision('0.8.9', None, remote), 'newer')
        self.assertEqual(app_service.app_update_decision('0.10.0', None, remote), 'current')
        self.assertEqual(app_service.app_update_decision('0.9.0', 'ab' * 32, remote), 'current')
        self.assertEqual(app_service.app_update_decision('0.9.0', 'cd' * 32, remote), 'rebuilt')
        self.assertEqual(app_service.app_update_decision(None, None, remote), 'newer')
        self.assertIsNone(app_service.version_key('0.9'))
        with self.assertRaises(ValueError):
            app_service.parse_app_manifest('{"schema": "earthng-app-v1", "version": "0.9.0", "sha256": "zz", "size": 10}')
        parsed = app_service.parse_app_manifest(json.dumps({
            'schema': 'earthng-app-v1', 'version': '0.9.1', 'sha256': 'ab' * 32, 'size': 50_000_000}))
        self.assertEqual(parsed['version'], '0.9.1')

    def test_a_checkout_does_not_offer_an_update(self):
        updates = self.root / 'updates'
        updates.mkdir()
        (updates / 'error.txt').write_text('swap-failed', encoding='utf-8')
        with patch.dict(os.environ, {'EARTHNG_EXE': '', 'EARTHNG_UPDATES': str(updates)}):
            found = self.ask(cmd='app_update')
            self.assertEqual((found['available'], found['reason'], found['error']), (False, 'checkout', 'swap-failed'))
            self.assertFalse((updates / 'error.txt').exists())
            self.assertIsNone(self.ask(cmd='app_update')['error'])
            self.assertFalse(self.ask(cmd='download_app')['ok'])

    def test_app_update_offers_a_newer_release_and_a_rebuilt_file(self):
        exe = self.root / 'EarthNG.exe'
        exe.write_bytes(b'MZinstalled')
        updates = self.root / 'updates'
        newer = {'version': '0.9.1', 'sha256': 'ab' * 32, 'size': 50_000_000}
        with patch.dict(os.environ, {'EARTHNG_EXE': str(exe), 'EARTHNG_UPDATES': str(updates)}), \
                patch.object(app_service, 'build_info', return_value={'version': '0.9.0'}), \
                patch.object(app_service, 'fetch_app_manifest', return_value=newer):
            found = self.ask(cmd='app_update')
        self.assertEqual((found['available'], found['reason'], found['version']), (True, 'newer', '0.9.1'))
        same = {'version': '0.9.0', 'sha256': 'cd' * 32, 'size': 50_000_000}
        with patch.dict(os.environ, {'EARTHNG_EXE': str(exe), 'EARTHNG_UPDATES': str(updates)}), \
                patch.object(app_service, 'build_info', return_value={'version': '0.9.0'}), \
                patch.object(app_service, 'fetch_app_manifest', return_value=same):
            rebuilt = self.ask(cmd='app_update')
        self.assertEqual(rebuilt['reason'], 'rebuilt')
        self.assertTrue(rebuilt['available'])

    def test_download_app_keeps_a_file_only_when_its_hash_matches(self):
        exe = self.root / 'installed.exe'
        exe.write_bytes(b'MZold')
        payload = b'MZ' + b'new-exe'
        digest = hashlib.sha256(payload).hexdigest()
        remote = {'version': '0.9.1', 'sha256': digest, 'size': len(payload)}
        updates = self.root / 'updates'

        def fake_download(url, dest, emit=print, cancel=None):
            self.assertEqual(url, f'{app_service.RELEASE_URL}/{app_service.APP_EXE}')
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(payload)
            return dest

        env = {'EARTHNG_EXE': str(exe), 'EARTHNG_UPDATES': str(updates)}
        with patch.dict(os.environ, env), \
                patch.object(app_service, 'build_info', return_value={'version': '0.9.0'}), \
                patch.object(app_service, 'fetch_app_manifest', return_value=remote), \
                patch.object(app_service.country_fetch, 'download', side_effect=fake_download):
            self.assertTrue(self.ask(cmd='download_app')['ok'])
            done = self.wait_done()
        self.assertEqual(done['result'], 'complete', done)
        self.assertEqual(done['sha256'], digest)
        self.assertEqual((updates / 'EarthNG.exe').read_bytes(), payload)
        sidecar = json.loads((updates / 'EarthNG.json').read_text(encoding='utf-8'))
        self.assertEqual(sidecar['sha256'], digest)

        def wrong(url, dest, emit=print, cancel=None):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(b'MZnope')
            return dest

        bad = dict(remote, sha256='ab' * 32, size=len(b'MZnope'))
        with patch.dict(os.environ, env), \
                patch.object(app_service, 'build_info', return_value={'version': '0.9.0'}), \
                patch.object(app_service, 'fetch_app_manifest', return_value=bad), \
                patch.object(app_service.country_fetch, 'download', side_effect=wrong):
            self.assertTrue(self.ask(cmd='download_app')['ok'])
            failed = self.wait_done()
        self.assertEqual(failed['result'], 'failed', failed)
        self.assertIn('does not match', failed['error'])
        self.assertFalse((updates / 'EarthNG.exe').exists())

    def test_update_manifest_is_read_from_github_and_a_missing_one_is_absent(self):
        import io as bytes_io
        import urllib.error
        body = json.dumps({'schema': 'earthng-app-v1', 'version': '0.9.1', 'sha256': 'ab' * 32,
                           'size': 50_000_000}).encode()

        class Response(bytes_io.BytesIO):
            def __init__(self, payload, url):
                super().__init__(payload)
                self.url = url

            def geturl(self):
                return self.url

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def urlopen(request, timeout, context):
            self.assertEqual(request.full_url, f'{app_service.RELEASE_URL}/{app_service.APP_MANIFEST}')
            self.assertIn('EarthNG.exe', request.get_header('User-agent'))
            return Response(body, 'https://release-assets.githubusercontent.com/earthng')

        with patch('urllib.request.urlopen', urlopen):
            found = app_service.fetch_app_manifest()
        self.assertEqual(found['version'], '0.9.1')

        def missing(request, timeout, context):
            raise urllib.error.HTTPError(request.full_url, 404, 'missing', None, None)

        with patch('urllib.request.urlopen', missing):
            self.assertIsNone(app_service.fetch_app_manifest())

        def redirected(request, timeout, context):
            return Response(body, 'https://evil.example/EarthNG.json')

        with patch('urllib.request.urlopen', redirected):
            with self.assertRaisesRegex(ValueError, 'unexpected update host'):
                app_service.fetch_app_manifest()
        self.assertFalse(app_service.allowed_release_url('http://github.com/Alezx311/earthng/EarthNG.json'))


class ProcessTests(unittest.TestCase):
    CHILD_WHILE_READING = """
import subprocess, sys, threading
import app_service
inp, out = app_service.protocol_streams() if sys.argv[1] == 'fixed' else (sys.stdin, sys.stdout)
threading.Thread(target=inp.readline, daemon=True).start()     # the page's pipe, a read pending
try:
    child = subprocess.run([sys.executable, '-c', 'print(42)'], stdout=subprocess.PIPE, timeout=8)
    out.write('child said ' + child.stdout.decode().strip() + '\\n')
except subprocess.TimeoutExpired:
    out.write('child hung\\n')
out.flush()
"""

    def test_a_child_starts_while_the_page_pipe_has_a_read_pending(self):
        # Windows: a child inheriting our stdin pipe hangs in start-up until the pending read returns
        process = subprocess.Popen([sys.executable, '-c', self.CHILD_WHILE_READING, 'fixed'], cwd=HERE,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            out = process.stdout.readline().decode().strip()
        finally:
            process.stdin.close()
            process.wait(20)
            process.stdout.close()
        self.assertEqual(out, 'child said 42')

    def test_the_service_speaks_utf8_json_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, EARTHNG_HOME=tmp, PYTHONIOENCODING='')
            process = subprocess.run([sys.executable, str(HERE / 'app_service.py')],
                                     input=b'{"id": 1, "cmd": "status"}\n',
                                     capture_output=True, env=env, timeout=120)
            lines = [json.loads(line) for line in process.stdout.decode('utf-8').splitlines()]
        self.assertEqual(lines[0]['event'], 'ready')
        self.assertEqual(lines[0]['home'], tmp)
        self.assertTrue(lines[1]['ok'], lines[1])
        self.assertEqual(lines[1]['home'], tmp)


if __name__ == '__main__':
    unittest.main()
