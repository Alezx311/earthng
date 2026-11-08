"""EarthNG.exe packaging: the runtime trailer the exe reads, the embedded path file, the file set."""
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

import prepare_app


class PrepareAppTests(unittest.TestCase):
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
            start = len(data) - 56 - size
            self.assertEqual(data[:start], b'MZ window')
            with zipfile.ZipFile(io.BytesIO(data[start:start + size])) as archive:
                self.assertEqual(archive.read('earthng/app_service.py'), b'x')

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
        self.assertNotIn('earthng/country_ui.py', files)
        self.assertRegex(info['planetVersion'], r'^\d+\.\d+\.\d+$')


if __name__ == '__main__':
    unittest.main()
