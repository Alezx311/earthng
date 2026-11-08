"""EarthNG.exe backend: protocol, game folder, planet install, projects (no network)."""
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

    def test_a_build_needs_a_game_folder(self):
        self.service.places = [{'id': 'albania', 'name': 'Albania', 'pbf': 'https://x/albania.osm.pbf'}]
        self.service.by_id = {'albania': self.service.places[0]}
        self.service.boundaries = {}
        with patch.object(app_service, 'game_folder_ok', return_value=False):
            answer = self.ask(cmd='build', place='albania', box=[19.8, 41.3, 19.9, 41.35])
        self.assertFalse(answer['ok'])
        self.assertIn('BeamNG user folder', answer['error'])

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
