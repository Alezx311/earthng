"""Smoke test of an unpacked Linux package (prepare_linux.py), as a player's browser would drive it.

    EarthNG/python/bin/python3 earthng/linux_smoke.py --package EarthNG [--place monaco] [--fake-planet]

Starts the package's own launcher (./EarthNG --no-browser), reads the session key from the page it
serves, listens to /events, asks the service for its status through POST /ipc, then builds a small
place end to end (sources, cut, elevation, index, export, install) into the BeamNG user folder the
service found, and checks the installed pack. --fake-planet puts a planet manifest of the expected
version into the mods folder first, so a package without a bundled planet does not fetch one.
--addons names the add-on packs (earthng/addons.json) chosen before the build: they are downloaded
from the release with the planet stage, and the ones not named must stay out of the mods folder.
Exit code 0 only when every step passed.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile


def fail(text):
    print(f'FAIL: {text}', flush=True)
    sys.exit(1)


class Page:
    def __init__(self, base):
        self.base = base
        html = urllib.request.urlopen(base, timeout=10).read().decode('utf-8')
        found = re.search(r'window\.EARTHNG_KEY="([^"]+)"', html)
        if not found or 'src="web.js"' not in html:
            fail('the page has no session key or no web.js')
        self.key = found.group(1)
        self.messages = queue.Queue()
        self.next_id = 1
        threading.Thread(target=self.listen, daemon=True).start()

    def listen(self):
        stream = urllib.request.urlopen(f'{self.base}events?k={self.key}', timeout=3600)
        for raw in stream:
            line = raw.decode('utf-8').rstrip('\n')
            if line.startswith('data: '):
                self.messages.put(json.loads(line[6:]))

    def post(self, message):
        body = json.dumps(message).encode('utf-8')
        request = urllib.request.Request(f'{self.base}ipc', data=body, method='POST',
                                         headers={'Content-Type': 'application/json', 'X-EarthNG-Key': self.key})
        return urllib.request.urlopen(request, timeout=10).status

    def call(self, cmd, timeout=120, **args):
        rid = self.next_id
        self.next_id += 1
        self.post({'id': rid, 'cmd': cmd, **args})
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                message = self.messages.get(timeout=1)
            except queue.Empty:
                continue
            if message.get('id') == rid:
                if not message.get('ok'):
                    fail(f'{cmd}: {message.get("error")}')
                return message
            self.seen(message)
        fail(f'{cmd}: no answer in {timeout} s')

    def wait_done(self, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                message = self.messages.get(timeout=1)
            except queue.Empty:
                continue
            self.seen(message)
            if message.get('event') == 'done':
                return message
        fail(f'no done event in {timeout} s')

    @staticmethod
    def seen(message):
        if message.get('event') == 'stage':
            print(f"  stage {message.get('name')}: {message.get('seconds')}", flush=True)
        elif message.get('event') == 'log':
            print(f"    {str(message.get('text'))[:160]}", flush=True)
        elif message.get('event') == 'service_exit':
            fail('the service stopped')


def fake_planet(mods, version):
    target = Path(mods) / 'mods' / 'earthng_planet.zip'
    target.parent.mkdir(parents=True, exist_ok=True)
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as z:
        z.writestr('earthng/planet/manifest.json',
                   json.dumps({'kind': 'earthng-planet', 'version': version, 'runtime': 'lua'}))
    target.write_bytes(data.getvalue())


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--package', type=Path, required=True, help='the unpacked EarthNG folder')
    p.add_argument('--place', default='monaco')
    p.add_argument('--port', type=int, default=47123)
    p.add_argument('--fake-planet', action='store_true')
    p.add_argument('--build-timeout', type=int, default=1800)
    p.add_argument('--addons', nargs='*', default=['polygon'],
                   help='add-on packs to choose before the build (default: the small proving ground)')
    a = p.parse_args()
    package = a.package.resolve()
    for name in ('EarthNG', 'python/bin/python3', 'bin/earthng-mapbuilder', 'bin/libearthng_native.so',
                 'earthng/app_web.py', 'app/ui/web.js', 'BUILD_INFO.json'):
        path = package / name
        if not path.exists():
            fail(f'missing {name}')
    if not os.access(package / 'EarthNG', os.X_OK) or not os.access(package / 'bin' / 'earthng-mapbuilder', os.X_OK):
        fail('launcher or native tool is not executable')
    info = json.loads((package / 'BUILD_INFO.json').read_text())
    print('BUILD_INFO', info, flush=True)
    tool = subprocess.run([str(package / 'bin' / 'earthng-mapbuilder'), '--help'], capture_output=True, text=True)
    if tool.returncode != 0:
        fail(f'earthng-mapbuilder --help: {tool.returncode} {tool.stderr[-400:]}')
    print('native tool ok:', tool.stdout.splitlines()[0], flush=True)
    # every compiled package imports in the packaged interpreter (on a bare system libexpat
    # comes from earthng.libs through sitecustomize)
    probe = subprocess.run([str(package / 'python' / 'bin' / 'python3'), '-c',
                            'import numpy, shapely, pyproj, osmium, PIL, ctypes.util; '
                            'import osmium.io; print("packages ok, system expat:", ctypes.util.find_library("expat"))'],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        fail(f'packaged python imports: {probe.stderr[-600:]}')
    print(probe.stdout.strip(), flush=True)

    server = subprocess.Popen([str(package / 'EarthNG'), '--no-browser', '--port', str(a.port), '--stay'],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        first = server.stdout.readline()
        print('launcher:', first.strip(), flush=True)
        if 'is open at' not in first:
            fail(f'launcher did not start: {first}{server.stdout.read()[-2000:] if server.poll() is not None else ""}')
        page = Page(f'http://127.0.0.1:{a.port}/')
        status = page.call('status')
        print('status:', {k: status.get(k) for k in ('home', 'mods', 'game_folder_ok', 'planet', 'folders')}, flush=True)
        if not status.get('game_folder_ok'):
            fail(f"the BeamNG user folder was not found: {status.get('mods')}")
        update = page.call('app_update')
        if update.get('reason') != 'linux':
            fail(f'app_update reason {update.get("reason")!r}, expected linux')
        tile = urllib.request.urlopen(f'http://127.0.0.1:{a.port}/tile/3/4/2.png', timeout=30)
        if tile.status != 200 or tile.read(8) != b'\x89PNG\r\n\x1a\n':
            fail('background tile is not a PNG')
        print('tile ok', flush=True)
        if a.fake_planet:
            fake_planet(status['mods'], info['planetVersion'])
        if not a.place:
            print('PASS (no build)', flush=True)
            return
        chosen = page.call('set_addons', chosen=a.addons)['addons']
        print('add-ons chosen:', [(x['id'], x['chosen'], x['state']) for x in chosen], flush=True)
        started = time.monotonic()
        page.call('build', place=a.place, allow_pbf=True)
        done = page.wait_done(a.build_timeout)
        print('done:', done, f'{time.monotonic() - started:.0f} s', flush=True)
        if done.get('result') != 'complete':
            fail(f"build {done.get('result')}: {done.get('error')}")
        if done.get('warnings'):
            fail(f"build warnings: {done.get('warnings')}")
        installed = Path(status['mods']) / 'mods'
        packs = sorted(installed.glob('earthng_*.zip'))
        print('mods:', [(x.name, x.stat().st_size) for x in packs], flush=True)
        after = page.call('status').get('addons') or []
        print('add-ons after:', [(x['id'], x['chosen'], x['state']) for x in after], flush=True)
        for entry in after:
            want = 'installed' if entry['id'] in a.addons else 'missing'
            if entry['state'] != want:
                fail(f"add-on {entry['id']}: {entry['state']}, expected {want}")
        pack = Path(done.get('path') or '')
        if pack.name in ('', 'earthng_planet.zip') or pack.parent.resolve() != installed.resolve() \
                or not pack.is_file():
            fail(f"the build installed no pack in {installed}: {done.get('path')!r}")
        with zipfile.ZipFile(pack) as z:
            bad = z.testzip()
            manifests = [n for n in z.namelist() if n.endswith('/manifest.json') and n.count('/') == 3]
            if bad or not manifests:
                fail(f'pack damaged ({bad}) or without a manifest')
            manifest = json.loads(z.read(manifests[0]))
            print('pack manifest:', {k: manifest.get(k) for k in ('id', 'title', 'kind', 'runtime', 'version')},
                  f'{len(z.namelist())} files', flush=True)
        print('PASS', flush=True)
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == '__main__':
    main()
