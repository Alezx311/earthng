"""The Linux package: the BeamNG user folder on Linux and under Proton, the browser server's guards,
and the tarball (modes, symlinks, the planet added later). Runs on Windows too: no Linux needed."""
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import app_service  # noqa: E402
import app_web  # noqa: E402
import country_fetch  # noqa: E402
import prepare_linux  # noqa: E402
import prepare_release  # noqa: E402


class UserFolders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def folder(self, *parts):
        path = self.home.joinpath(*parts)
        (path / 'mods').mkdir(parents=True)
        return path

    def test_windows_keeps_localappdata(self):
        bases = country_fetch.user_folder_bases({'LOCALAPPDATA': r'C:\Users\x\AppData\Local'}, self.home, nt=True)
        self.assertEqual(bases, [Path(r'C:\Users\x\AppData\Local')])

    def test_native_client_first(self):
        native = self.folder('.local', 'share', 'BeamNG', 'BeamNG.drive', 'current')
        proton = self.folder('.steam', 'steam', 'steamapps', 'compatdata', '284160', 'pfx', 'drive_c', 'users',
                             'steamuser', 'AppData', 'Local', 'BeamNG', 'BeamNG.drive', 'current')
        self.assertEqual(country_fetch.default_mods({}, self.home, nt=False), native)
        self.assertEqual(app_service.game_folders({}, self.home, nt=False), [native, proton])

    def test_proton_in_another_steam_library(self):
        library = self.home / 'games'
        steam = self.home / '.local' / 'share' / 'Steam' / 'steamapps'
        steam.mkdir(parents=True)
        (steam / 'libraryfolders.vdf').write_text(
            '"libraryfolders"\n{\n "0"\n {\n  "path"  "%s"\n }\n "1"\n {\n  "path"  "%s"\n }\n}\n'
            % (self.home / '.local' / 'share' / 'Steam', library), encoding='utf-8')
        proton = self.folder('games', 'steamapps', 'compatdata', '284160', 'pfx', 'drive_c', 'users', 'steamuser',
                             'AppData', 'Local', 'BeamNG', 'BeamNG.drive', 'current')
        self.assertEqual(country_fetch.default_mods({}, self.home, nt=False), proton)

    def test_xdg_data_home_and_default(self):
        xdg = self.home / 'xdg'
        self.assertEqual(country_fetch.default_mods({'XDG_DATA_HOME': str(xdg)}, self.home, nt=False),
                         xdg / 'BeamNG' / 'BeamNG.drive' / 'current')
        found = self.folder('xdg', 'BeamNG', 'BeamNG.drive', 'current')
        self.assertEqual(country_fetch.default_mods({'XDG_DATA_HOME': str(xdg)}, self.home, nt=False), found)


class FakeService:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(json.loads(text))
        return True

    def stop(self):
        pass


class WebServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = app_web.make_server(0, tile_cache=self.tmp.name, start_service=False)
        self.server.service = FakeService()
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.stopping.set()
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, path, data=None, headers=None, host=None):
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=data, headers=headers or {},
                                         method='POST' if data is not None else 'GET')
        if host:
            request.add_header('Host', host)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_page_carries_key_and_transport(self):
        status, body = self.request('/')
        html = body.decode('utf-8')
        self.assertEqual(status, 200)
        self.assertIn(f'window.EARTHNG_KEY="{self.server.key}"', html)
        self.assertLess(html.index('src="web.js"'), html.index('src="app.js"'))
        self.assertEqual(self.request('/web.js')[0], 200)

    def test_guards(self):
        self.assertEqual(self.request('/', host=f'evil.example:{self.port}')[0], 403)
        self.assertEqual(self.request('/%2e%2e/earthng/app_web.py')[0], 404)
        self.assertEqual(self.request('/vendor/../../earthng/app_web.py')[0], 404)
        self.assertEqual(self.request('/events?k=wrong')[0], 403)
        body = json.dumps({'id': 1, 'cmd': 'status'}).encode()
        self.assertEqual(self.request('/ipc', body, {'Content-Type': 'application/json'})[0], 403)
        self.assertEqual(self.request('/ipc', body, {'X-EarthNG-Key': 'nope'})[0], 403)
        self.assertEqual(self.server.service.sent, [])

    def test_ipc_reaches_service_and_events_come_back(self):
        status, _ = self.request('/ipc', json.dumps({'id': 7, 'cmd': 'status'}).encode(),
                                 {'X-EarthNG-Key': self.server.key, 'Content-Type': 'application/json'})
        self.assertEqual(status, 204)
        self.assertEqual(self.server.service.sent, [{'id': 7, 'cmd': 'status'}])
        self.server.hub.publish(json.dumps({'event': 'ready', 'home': 'x'}))     # replayed to a late page
        stream = urllib.request.urlopen(f'http://127.0.0.1:{self.port}/events?k={self.server.key}', timeout=5)
        lines = []
        for raw in stream:
            if raw.startswith(b'data: '):
                lines.append(json.loads(raw[6:]))
                if len(lines) == 1:
                    self.server.hub.publish(json.dumps({'id': 7, 'ok': True}))
                if len(lines) == 2:
                    break
        stream.close()
        self.assertEqual(lines, [{'event': 'ready', 'home': 'x'}, {'id': 7, 'ok': True}])

    def test_app_commands_answer_without_service(self):
        status, _ = self.request('/ipc', json.dumps({'id': 3, 'cmd': 'apply_update', 'to': 'app'}).encode(),
                                 {'X-EarthNG-Key': self.server.key})
        self.assertEqual(status, 204)
        self.assertEqual(self.server.service.sent, [])

    def test_tiles_cached_and_checked(self):
        calls = []

        def fetch(z, x, y):
            calls.append((z, x, y))
            return b'\x89PNG tile'
        self.assertEqual(app_web.serve_tile('3/4/2.png', self.tmp.name, fetch), (200, b'\x89PNG tile'))
        self.assertEqual(app_web.serve_tile('3/4/2.png', self.tmp.name, fetch), (200, b'\x89PNG tile'))
        self.assertEqual(calls, [(3, 4, 2)])
        for bad in ('1/2/0.png', '20/0/0.png', '3/1/1.jpg', '../1/1.png', '3/1/1/1.png'):
            self.assertEqual(app_web.serve_tile(bad, self.tmp.name, fetch)[0], 400, bad)

    def test_hub_tracks_jobs(self):
        hub = app_web.Hub()
        hub.publish(json.dumps({'id': 1, 'ok': True, 'job': 'build'}))
        self.assertTrue(hub.busy)
        hub.publish(json.dumps({'event': 'done', 'job': 'build', 'result': 'complete'}))
        self.assertFalse(hub.busy)

    def test_local_folder(self):
        self.assertEqual(app_web.local({'EARTHNG_LOCAL': '/x/y'}), Path('/x/y'))
        if os.name != 'nt':
            self.assertEqual(app_web.local({'XDG_DATA_HOME': '/d'}), Path('/d/EarthNG'))


class Package(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        parts = self.dir / 'parts'
        (parts / 'bin').mkdir(parents=True)
        for name in prepare_linux.NATIVE:
            (parts / 'bin' / name).write_bytes(b'\x7fELF fake')
        with tarfile.open(parts / 'python.tar', 'w') as tar:
            info = tarfile.TarInfo('python/bin/python3.13')
            data = b'#!fake'
            info.size, info.mode = len(data), 0o755
            tar.addfile(info, io.BytesIO(data))
            link = tarfile.TarInfo('python/bin/python3')
            link.type, link.linkname = tarfile.SYMTYPE, 'python3.13'
            tar.addfile(link)
        self.parts = parts
        self.info = {'version': '9.9.9', 'planetVersion': '9.9.9', 'sourceCommit': 'abc1234'}
        self.files = {'earthng/app_web.py': b'print(1)\n', 'BUILD_INFO.json': json.dumps(self.info).encode()}

    def tearDown(self):
        self.tmp.cleanup()

    def planet(self, version):
        path = self.dir / f'planet-{version}.zip'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('earthng/planet/manifest.json',
                       json.dumps({'kind': 'earthng-planet', 'version': version, 'runtime': 'lua'}))
        return path

    def test_modes_symlinks_and_launcher(self):
        target = prepare_linux.write_package(self.dir / prepare_linux.PACKAGE, self.files, self.parts, None, self.info)
        with tarfile.open(target) as tar:
            members = {m.name: m for m in tar}
            launcher = members['EarthNG/EarthNG']
            self.assertEqual(launcher.mode & 0o777, 0o755)
            text = tar.extractfile(launcher).read()
            self.assertTrue(text.startswith(b'#!/bin/sh\n'))
            self.assertNotIn(b'\r', text)
            self.assertEqual(members['EarthNG/bin/earthng-mapbuilder'].mode & 0o777, 0o755)
            self.assertEqual(members['EarthNG/python/bin/python3.13'].mode & 0o777, 0o755)
            self.assertTrue(members['EarthNG/python/bin/python3'].issym())
            self.assertEqual(members['EarthNG/python/bin/python3'].linkname, 'python3.13')
            self.assertIn('EarthNG/earthng/app_web.py', members)
            self.assertNotIn('EarthNG/earthng_planet.zip', members)

    def test_repack_adds_the_planet_of_the_right_version(self):
        built = self.dir / 'ci'
        built.mkdir()
        package = prepare_linux.write_package(built / prepare_linux.PACKAGE, self.files, self.parts, None, self.info)
        with self.assertRaises(ValueError):
            prepare_linux.repack(package, self.planet('1.0.0'), self.dir / 'bad')
        target, _ = prepare_linux.repack(package, self.planet('9.9.9'), self.dir / 'release')
        with tarfile.open(target) as tar:
            members = {m.name: m for m in tar}
            self.assertIn('EarthNG/earthng_planet.zip', members)
            self.assertEqual(members['EarthNG/EarthNG'].mode & 0o777, 0o755)
            self.assertTrue(members['EarthNG/python/bin/python3'].issym())

    def test_runtime_follows_app_web(self):
        files = {'earthng/app_service.py': b'import country_fetch\n', 'earthng/country_fetch.py': b'',
                 'earthng/app_web.py': b'import json\n', 'earthng/osm_tiles_country.py': b'',
                 'requirements-fast.txt': b'', 'LICENSE': b'', 'THIRD_PARTY_NOTICES.md': b'',
                 'earthng/fast_tree_materials.json': b'{}'}
        self.assertIn('earthng/app_web.py', prepare_release.builder_files(files))
        del files['earthng/app_web.py']                 # an older snapshot without it
        self.assertNotIn('earthng/app_web.py', prepare_release.builder_files(files))


if __name__ == '__main__':
    unittest.main()
