"""EarthNG.exe packaging: the runtime trailer the exe reads, the embedded path file, the file set."""
import ast
import hashlib
import io
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import app_service
import prepare_app
import prepare_release

ROOT = Path(__file__).resolve().parents[1]


class PrepareAppTests(unittest.TestCase):
    def test_release_staging_bundles_the_planet_in_the_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            planet = root / 'earthng_planet.zip'
            with zipfile.ZipFile(planet, 'w') as archive:
                archive.writestr('earthng/planet/manifest.json',
                    json.dumps({'runtime': 'lua', 'version': '1.0.1'}))
            out = root / 'release'

            def build(target, ref, native, **kw):
                self.assertEqual(kw['planet'], planet)
                exe = target / 'EarthNG.exe'
                exe.write_bytes(b'candidate')
                return exe, {'planetVersion': '1.0.1', 'sourceCommit': 'test'}, ''

            with patch.object(prepare_app, 'build', side_effect=build):
                prepare_release.prepare(planet, [], out)

    def test_trailer_matches_rust_runtime(self):
        # rust/crates/app/src/runtime.rs: [zip][sha256: 32][len: u64 LE][MAGIC: 16]
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'EarthNG.exe'
            exe.write_bytes(b'MZ window')
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, 'w') as archive:
                archive.writestr('earthng/app_service.py', 'x')
            payload = payload.getvalue()
            out = Path(tmp) / 'out' / 'EarthNG.exe'
            digest = prepare_app.append_runtime(exe, payload, out)
            data = out.read_bytes()
            self.assertEqual(data[-16:], prepare_app.MAGIC)
            self.assertEqual(len(prepare_app.MAGIC), 16)
            size = int.from_bytes(data[-24:-16], 'little')
            self.assertEqual(size, len(payload))
            self.assertEqual(data[-56:-24], hashlib.sha256(payload).digest())
            self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
            manifest_path = prepare_app.write_app_manifest(out, {'version': '0.9.0', 'planetVersion': '0.9.0'})
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            self.assertEqual(manifest['schema'], app_service.APP_SCHEMA)
            self.assertEqual(manifest['sha256'], hashlib.sha256(out.read_bytes()).hexdigest())
            self.assertEqual((manifest['version'], manifest['size']), ('0.9.0', out.stat().st_size))
            start = len(data) - 56 - size
            self.assertEqual(data[:start], b'MZ window')
            with zipfile.ZipFile(io.BytesIO(data[start:start + size])) as archive:
                self.assertEqual(archive.read('earthng/app_service.py'), b'x')

    def test_single_file_runtime_preserves_the_bundled_planet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            embedded = root / 'python.zip'
            with zipfile.ZipFile(embedded, 'w') as archive:
                archive.writestr('python313._pth', 'old')
            packages = root / 'packages'
            packages.mkdir()
            planet = root / 'planet.zip'
            with zipfile.ZipFile(planet, 'w') as archive:
                archive.writestr('earthng/planet/manifest.json', '{}')
            payload = prepare_app.build_runtime_zip({'BUILD_INFO.json': b'{}'}, embedded, packages, planet)
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                self.assertEqual(archive.read('earthng_planet.zip'), planet.read_bytes())
                self.assertEqual(archive.getinfo('earthng_planet.zip').compress_type, zipfile.ZIP_STORED)

    def test_embedded_python_finds_the_pipeline_and_its_packages(self):
        lines = prepare_app.PTH.splitlines()
        self.assertIn('Lib\\site-packages', lines)
        self.assertIn('..\\earthng', lines)          # scripts start each other by file name
        self.assertEqual(lines[-1], 'import site')

    def test_runtime_has_the_service_page_and_no_tk_window(self):
        info, files = prepare_app.runtime_files('HEAD', native=False)
        self.assertIn('earthng/app_service.py', files)
        self.assertIn('earthng/build_country.py', files)        # started by file name
        self.assertIn('earthng/osm_tiles_country.py', files)
        self.assertIn('app/ui/index.html', files)
        self.assertIn('app/ui/vendor/leaflet/leaflet.js', files)
        self.assertTrue(any(n.startswith('mod/lua/') for n in files))
        self.assertRegex(info['planetVersion'], r'^\d+\.\d+\.\d+$')


    def test_runtime_has_every_script_the_pipeline_starts(self):
        names = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'],
                                        cwd=ROOT, text=True).splitlines()
        files = {n: (ROOT / n).read_bytes() for n in names if (ROOT / n).is_file()}
        selected = prepare_release.builder_files(files)
        # country_fetch starts these by file name; build_country also needs the modules it imports.
        for module in ('app_service', 'osm_tiles_country', 'build_map', 'build_country', 'country_format',
                       'landcover', 'native_tool', 'build_area_photos', 'map_photo_codec'):
            self.assertIn(f'earthng/{module}.py', selected)
        # Every 'name.py' a bundled module mentions must be bundled too, or the build stops mid-way.
        for name, data in selected.items():
            if not name.endswith('.py'):
                continue
            for node in ast.walk(ast.parse(data.decode('utf-8-sig'))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    script = prepare_release._script_name(node.value)
                    if script and f'earthng/{script}.py' in files:
                        self.assertIn(f'earthng/{script}.py', selected, f'{name} starts {node.value}')

    def test_native_tools_come_only_from_their_own_commit(self):
        self.assertEqual(prepare_release.native_files('abc', {'earthng/x.py': b''}), {})   # a ref before rust/
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with self.assertRaisesRegex(ValueError, 'check out the release ref'):
            prepare_release.native_files('0' * 40, {'rust/Cargo.lock': b''})
        outputs = {('git', 'rev-parse', 'HEAD'): head + '\n',
                   ('git', 'status', '--porcelain', '--', 'rust'): ' M rust/x\n'}
        with patch.object(prepare_release.subprocess, 'check_output', lambda cmd, **kw: outputs[tuple(cmd)]), \
                self.assertRaisesRegex(ValueError, 'unchanged'):
            prepare_release.native_files(head, {'rust/Cargo.lock': b''})

    def test_ready_packs_name_the_release_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / 'earthng_albania.zip'
            with zipfile.ZipFile(pack, 'w') as archive:
                archive.writestr('earthng/countries/albania/manifest.json',
                                 json.dumps({'id': 'albania', 'title': 'Albania', 'runtime': 'native'}))
            self.assertEqual(prepare_release.ready_packs([pack], 'https://x/rel/'),
                             {'packs': [{'id': 'albania', 'title': 'Albania', 'url': 'https://x/rel/earthng_albania.zip'}]})
            wrong = Path(tmp) / 'albania.zip'
            pack.replace(wrong)
            with self.assertRaisesRegex(ValueError, 'filename'):
                prepare_release.ready_packs([wrong])


if __name__ == '__main__':
    unittest.main()
