"""Country setup: asset blocks, Geofabrik index, ready-pack discovery. No downloads."""
import unittest
from pathlib import Path
import zipfile
import io
import json
import sys
import threading
from unittest.mock import patch

import country_fetch
import looks
import places


INDEX = {
    'features': [
        {'properties': {'id': 'europe', 'name': 'Europe', 'urls': {'pbf': 'https://download.geofabrik.de/europe-latest.osm.pbf'}}},
        {'properties': {'id': 'ukraine', 'parent': 'europe', 'name': 'Ukraine',
                        'urls': {'pbf': 'https://download.geofabrik.de/europe/ukraine-latest.osm.pbf'}}},
        {'properties': {'id': 'georgia', 'parent': 'asia', 'name': 'Georgia',
                        'urls': {'pbf': 'https://download.geofabrik.de/asia/georgia-latest.osm.pbf'}}},
        {'properties': {'id': 'asia', 'name': 'Asia', 'urls': {'pbf': 'https://download.geofabrik.de/asia-latest.osm.pbf'}}},
        {'properties': {'id': 'north-america', 'name': 'North America',
                        'urls': {'pbf': 'https://download.geofabrik.de/north-america-latest.osm.pbf'}}},
        {'properties': {'id': 'us/georgia', 'parent': 'north-america', 'name': 'Georgia',
                        'urls': {'pbf': 'https://download.geofabrik.de/north-america/us/georgia-latest.osm.pbf'}}},
        {'properties': {'id': 'berlin', 'parent': 'germany', 'name': 'Berlin',
                        'urls': {'pbf': 'https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf'}}},
        {'properties': {'id': 'germany', 'parent': 'europe', 'name': 'Germany',
                        'urls': {'pbf': 'https://download.geofabrik.de/europe/germany-latest.osm.pbf'}}},
        {'properties': {'id': 'secret', 'name': 'Nope', 'urls': {'pbf': 'https://example.com/secret.osm.pbf'}}},
    ]
}


class LookTests(unittest.TestCase):
    def setUp(self):
        self.places = places.by_id(places.parse_index(INDEX))

    def test_postsoviet_default_is_panel_and_worn_asphalt(self):
        look = looks.recommended('ukraine', self.places)
        self.assertEqual(look['block'], 'postsoviet')
        self.assertEqual(look['buildings'], 'panel')
        self.assertEqual(look['asphalt'], 'worn')
        self.assertEqual(look['trees'], 'regional')

    def test_child_region_follows_its_country(self):
        look = looks.recommended('berlin', self.places)
        self.assertEqual(look['block'], 'western')
        self.assertEqual(look['buildings'], 'mixed')
        self.assertEqual(look['asphalt'], 'smooth')

    def test_us_state_does_not_inherit_the_country_of_georgia(self):
        country = looks.recommended('georgia', self.places)
        state = looks.recommended('us/georgia', self.places)
        self.assertEqual(country['block'], 'postsoviet')
        self.assertEqual(state['block'], 'north-america')
        self.assertEqual(state['markings'], 'yellow')

    def test_unknown_place_stays_on_the_general_block(self):
        self.assertEqual(looks.recommended('atlantis', self.places)['block'], 'general')

    def test_override_keeps_the_block_and_rejects_an_unknown_choice(self):
        look = looks.canonical({'block': 'postsoviet', 'buildings': 'brick'})
        self.assertEqual((look['buildings'], look['asphalt']), ('brick', 'worn'))
        with self.assertRaises(ValueError):
            looks.canonical({'block': 'postsoviet', 'asphalt': 'cobble'})

    def test_layers_drop_buildings_and_keep_roads(self):
        include = looks.canonical_include({'buildings': False})
        self.assertFalse(looks.keep_scenery('building', include))
        self.assertTrue(looks.keep_scenery('water', include))
        self.assertTrue(looks.keep_scenery('road', include))
        self.assertTrue(looks.keep_scenery('crossing', {'cover': False, 'stops': False}))
        self.assertTrue(looks.keep_scenery('forest', None))

    def test_slug_flattens_a_state_id(self):
        self.assertEqual(places.slug('us/california'), 'us-california')

    def test_index_ignores_a_pbf_outside_geofabrik(self):
        ids = {place['id'] for place in places.parse_index(INDEX)}
        self.assertNotIn('secret', ids)
        self.assertIn('ukraine', ids)

    def test_search_finds_a_name(self):
        found = places.search(list(self.places.values()), 'ber')
        self.assertEqual([place['id'] for place in found], ['berlin'])

    def test_corrupt_cached_list_is_refetched(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            path = places.cache_path(folder)
            path.parent.mkdir(parents=True)
            path.write_text('{broken')
            response = io.BytesIO(json.dumps(INDEX).encode())
            with patch.object(places.urllib.request, 'urlopen', return_value=response):
                loaded = places.load_index(folder, emit=lambda _: None)
            self.assertEqual(loaded, places.parse_index(INDEX))
            self.assertEqual(places.load_cached(folder), loaded)

    def test_failed_refresh_keeps_the_working_cached_list(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            path = places.cache_path(folder)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(INDEX))
            with patch.object(places.urllib.request, 'urlopen', side_effect=OSError('offline')):
                loaded = places.load_index(folder, refresh=True, emit=lambda _: None)
            self.assertEqual(loaded, places.parse_index(INDEX))


class PackFileTests(unittest.TestCase):
    def test_download_resumes_only_matching_version_and_range(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            dest = Path(folder) / 'extract.pbf'
            part = dest.with_suffix('.pbf.part')
            meta = part.with_suffix('.part.json')
            url = 'https://example.com/extract.pbf'
            part.write_bytes(b'abc')
            meta.write_text(json.dumps({'url': url, 'validator': '"v1"'}))
            response = io.BytesIO(b'def')
            response.status = 206
            response.headers = {'Content-Range': 'bytes 3-5/6', 'Content-Length': '3', 'ETag': '"v1"'}
            with patch.object(country_fetch, 'content_length', return_value=6), \
                    patch.object(country_fetch.urllib.request, 'urlopen', return_value=response) as opened:
                country_fetch.download(url, dest, emit=lambda _: None)
            request = opened.call_args.args[0]
            self.assertEqual(request.get_header('If-range'), '"v1"')
            self.assertEqual(request.get_header('Range'), 'bytes=3-')
            self.assertEqual(dest.read_bytes(), b'abcdef')
            self.assertFalse(meta.exists())

    def test_download_rejects_wrong_resume_offset_without_damaging_partial(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            dest = Path(folder) / 'extract.pbf'
            part = dest.with_suffix('.pbf.part')
            url = 'https://example.com/extract.pbf'
            part.write_bytes(b'abc')
            part.with_suffix('.part.json').write_text(json.dumps({'url': url, 'validator': '"v1"'}))
            response = io.BytesIO(b'abcdef')
            response.status = 206
            response.headers = {'Content-Range': 'bytes 0-5/6', 'ETag': '"v1"'}
            with patch.object(country_fetch, 'content_length', return_value=6), \
                    patch.object(country_fetch.urllib.request, 'urlopen', return_value=response):
                with self.assertRaisesRegex(OSError, 'Content-Range'):
                    country_fetch.download(url, dest, emit=lambda _: None)
            self.assertEqual(part.read_bytes(), b'abc')
            self.assertFalse(dest.exists())

    def test_get_works_without_head_and_restarts_unverified_partial(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            dest = Path(folder) / 'extract.pbf'
            dest.with_suffix('.pbf.part').write_bytes(b'old prefix')
            response = io.BytesIO(b'new')
            response.status = 200
            response.headers = {'Content-Length': '3'}
            with patch.object(country_fetch, 'content_length', side_effect=OSError('HEAD rejected')), \
                    patch.object(country_fetch.urllib.request, 'urlopen', return_value=response) as opened:
                country_fetch.download('https://example.com/extract.pbf', dest, emit=lambda _: None)
            self.assertIsNone(opened.call_args.args[0].get_header('Range'))
            self.assertEqual(dest.read_bytes(), b'new')

    def test_changed_source_restarts_instead_of_appending(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            dest = Path(folder) / 'extract.pbf'
            part = dest.with_suffix('.pbf.part')
            url = 'https://example.com/extract.pbf'
            part.write_bytes(b'old')
            part.with_suffix('.part.json').write_text(json.dumps({'url': url, 'validator': '"old"'}))
            response = io.BytesIO(b'new version')
            response.status = 200  # If-Range no longer matches
            response.headers = {'Content-Length': '11', 'ETag': '"new"'}
            with patch.object(country_fetch, 'content_length', return_value=6), \
                    patch.object(country_fetch.urllib.request, 'urlopen', return_value=response):
                country_fetch.download(url, dest, emit=lambda _: None)
            self.assertEqual(dest.read_bytes(), b'new version')

    def test_cancel_before_download_or_worker_does_no_work(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(country_fetch, 'content_length') as head, \
                patch.object(country_fetch.subprocess, 'Popen') as popen:
            with self.assertRaises(InterruptedError):
                country_fetch.download('https://example.com/file', 'unused', cancel=cancel)
            with self.assertRaises(InterruptedError):
                country_fetch.run_step(['unused'], cancel=cancel)
        head.assert_not_called()
        popen.assert_not_called()

    def test_cancel_install_preserves_existing_pack_and_cleans_partial(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.zip'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('earthng/countries/test/manifest.json', '{}')
            target = root / 'mods' / 'earthng_test.zip'
            target.parent.mkdir()
            target.write_bytes(b'existing pack')
            cancel = threading.Event()
            copy = country_fetch.copy_stream
            def stopped(src, dst, event):
                copy(src, dst, event)
                event.set()
            with patch.object(country_fetch, 'copy_stream', side_effect=stopped):
                with self.assertRaises(InterruptedError):
                    country_fetch.install_zip(source, root, 'test', cancel=cancel)
            self.assertEqual(target.read_bytes(), b'existing pack')
            self.assertFalse(target.with_suffix('.zip.part').exists())

    def test_refresh_streams_art_and_cancel_preserves_original(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            root = Path(folder)
            planet = root / 'mods' / 'earthng_planet.zip'
            planet.parent.mkdir()
            with zipfile.ZipFile(planet, 'w') as archive:
                archive.writestr('art/large.bin', b'a' * (3 * 1024 * 1024))
            before = planet.read_bytes()
            cancel = threading.Event()
            original_read = zipfile.ZipFile.read
            def guarded(archive, name, *args, **kwargs):
                self.assertNotEqual(name, 'art/large.bin', 'art must be streamed')
                return original_read(archive, name, *args, **kwargs)
            original_copy = country_fetch.copy_stream
            def stopped(src, dst, event):
                original_copy(src, dst, event)
                event.set()
            with patch.object(zipfile.ZipFile, 'read', guarded), \
                    patch.object(country_fetch, 'copy_stream', side_effect=stopped):
                with self.assertRaises(InterruptedError):
                    country_fetch.refresh_planet(root, emit=lambda _: None, cancel=cancel)
            self.assertEqual(planet.read_bytes(), before)
            self.assertFalse(planet.with_suffix('.zip.tmp').exists())
            with patch.object(zipfile.ZipFile, 'read', guarded):
                country_fetch.refresh_planet(root, emit=lambda _: None)
            with zipfile.ZipFile(planet) as archive:
                self.assertEqual(archive.read('art/large.bin'), b'a' * (3 * 1024 * 1024))

    def test_truncated_download_keeps_partial_and_existing_destination(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            dest = Path(folder) / 'extract.pbf'
            dest.write_bytes(b'old')
            response = io.BytesIO(b'short')
            response.status = 200
            with patch.object(country_fetch, 'content_length', return_value=20), \
                    patch.object(country_fetch.urllib.request, 'urlopen', return_value=response):
                with self.assertRaisesRegex(OSError, 'incomplete download'):
                    country_fetch.download('https://example.com/extract.pbf', dest, emit=lambda _: None)
            self.assertEqual(dest.read_bytes(), b'old')
            self.assertEqual(dest.with_suffix('.pbf.part').read_bytes(), b'short')

    def test_worker_output_and_failure_reach_the_gui_log(self):
        import subprocess
        lines = []
        with self.assertRaises(subprocess.CalledProcessError):
            country_fetch.run_step([sys.executable, '-c', 'print("tile failure"); raise SystemExit(3)'], lines.append)
        self.assertIn('tile failure', lines)

    def test_missing_osmium_does_not_ask_for_another_checkout(self):
        import builtins
        import unittest.mock
        real = builtins.__import__

        def guarded(name, globals=None, locals=None, fromlist=(), level=0):
            if name == 'osmium':
                raise ImportError(name)
            return real(name, globals, locals, fromlist, level)

        with unittest.mock.patch('builtins.__import__', guarded), \
                unittest.mock.patch.object(Path, 'is_file', return_value=False):
            with self.assertRaises(RuntimeError) as caught:
                country_fetch._python()
        self.assertNotIn('earth2road', str(caught.exception).lower())
        self.assertIn('requirements-fast.txt', str(caught.exception))

    def test_install_requires_the_country_manifest(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'earthng_ukraine.zip'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('earthng/countries/ukraine/manifest.json', '{}')
            mods = root / 'profile'
            installed = country_fetch.install_zip(source, mods, 'ukraine')
            self.assertTrue(installed.is_file())
            self.assertEqual(country_fetch.availability('ukraine', mods, root)['state'], 'installed')

    def test_refresh_replaces_lua_and_leaves_art(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            root = Path(folder)
            mods = root / 'profile'
            planet = mods / 'mods' / 'earthng_planet.zip'
            planet.parent.mkdir(parents=True)
            with zipfile.ZipFile(planet, 'w') as archive:
                archive.writestr('lua/ge/extensions/e2r/generator.lua', 'old')
                archive.writestr('e2r_stream/fast-art/v10/real/keep.dds', b'dds')
                archive.writestr('e2r_stream/fast-art/v10/packs.json', '{}')
            # refresh_planet reads the repository mod/, so the lua member changes
            # and the untouched art member stays; the packs' settings are code too.
            country_fetch.refresh_planet(mods, emit=lambda _text: None)
            with zipfile.ZipFile(planet) as archive:
                names = set(archive.namelist())
                self.assertIn('e2r_stream/fast-art/v10/real/keep.dds', names)
                self.assertNotEqual(archive.read('lua/ge/extensions/e2r/generator.lua'), b'old')
                self.assertIn(b'mark_yellow', archive.read('earthng/planet/materials.json'))
                self.assertIn(b'e2rf_edge_grass', archive.read('e2r_stream/fast-art/v10/packs.json'))

    def test_refresh_keeps_the_planet_language(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            mods = Path(folder) / 'profile'
            planet = mods / 'mods' / 'earthng_planet.zip'
            planet.parent.mkdir(parents=True)
            with zipfile.ZipFile(planet, 'w') as archive:
                archive.writestr('lua/ge/extensions/e2r/world.lua', "local x = 1\nlocal LANG = 'en'   -- built\n")
            country_fetch.refresh_planet(mods, emit=lambda _text: None)
            with zipfile.ZipFile(planet) as archive:
                text = archive.read('lua/ge/extensions/e2r/world.lua').decode('utf-8')
            self.assertIn("local LANG = 'en'", text)
            self.assertNotIn("local LANG = 'uk'", text)
            self.assertGreater(len(text), 1000)  # the repository's world.lua, not the old one


if __name__ == '__main__':
    unittest.main()
