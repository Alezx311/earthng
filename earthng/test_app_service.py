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

    def test_build_needs_the_planet(self):
        self.service.places = [{'id': 'albania', 'name': 'Albania', 'pbf': 'https://x/albania.osm.pbf'}]
        self.service.by_id = {'albania': self.service.places[0]}
        self.service.boundaries = {}
        answer = self.ask(cmd='build', place='albania', box=[19.8, 41.3, 19.9, 41.35])
        self.assertFalse(answer['ok'])
        self.assertIn('planet', answer['error'])

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
