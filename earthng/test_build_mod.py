"""The common planet cannot depend on the developer's regional build cache."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import build_mod
import fast_art
import build_basemap
import build_climate
import prepare_release


class SharedPlanetTests(unittest.TestCase):
    def test_regional_build_caches_never_enter_the_planet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            here, mod = root / 'earthng', root / 'mod'
            here.mkdir()
            mod.mkdir()
            for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
                (root / name).write_text('notice')
            art = root / 'data/art-distributable' / fast_art.VERSION
            art.mkdir(parents=True)
            (art / 'packs.json').write_text('{}')
            (art / 'shared.dds').write_bytes(b'shared art')
            for folder in ('out/map-data/test', 'out/far/test', 'climate', 'basemap'):
                (root / folder).mkdir(parents=True)
            (root / 'out/map-data/test/index.json').write_text('{}')
            (root / 'out/map-data/test/pois.tsv').write_text('regional points')
            (root / 'out/far/test/region.bin').write_bytes(b'regional heights')
            (root / 'out/far/test/region.color.dds').write_bytes(b'regional imagery')
            (root / 'climate/global.bin').write_bytes(b'global climate')
            (root / 'basemap/index.json').write_text('{}')
            with patch.object(build_mod, 'HERE', here), patch.object(build_mod, 'MOD', mod), \
                    patch.object(build_mod, 'level_files', return_value={}), \
                    patch.object(fast_art, 'prebuild', return_value=art), \
                    patch.object(fast_art, 'logo_credits', return_value=''), \
                    patch.object(build_basemap, 'build', return_value=root / 'basemap'), \
                    patch.object(build_climate, 'build', return_value=root / 'climate'):
                target = build_mod.build(root / 'result')
                with zipfile.ZipFile(target) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertEqual(archive.read('earthng/planet/climate/global.bin'), b'global climate')
                    self.assertIn('earthng/planet/basemap/index.json', archive.namelist())
                    self.assertFalse(any('/maps/' in n or '/far/' in n for n in archive.namelist()))
                prepare_release.check_planet(target)
                unexpected = mod / 'earthng/planet/far/test'
                unexpected.mkdir(parents=True)
                (unexpected / 'region.bin').write_bytes(b'local data')
                with self.assertRaisesRegex(ValueError, 'Regional data'):
                    build_mod.build(root / 'bad')
                self.assertFalse((root / 'bad' / build_mod.ZIP).exists())

    def test_release_rejects_a_planet_with_regional_payload(self):
        for name in ('earthng/planet/far/xx/r.bin', 'earthng/planet/maps/xx/index.json',
                     'earthng/countries/xx/manifest.json', 'earthng/planet/guide.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                planet = Path(tmp) / 'planet.zip'
                with zipfile.ZipFile(planet, 'w') as archive:
                    archive.writestr('earthng/planet/manifest.json', json.dumps({'runtime': 'lua'}))
                    archive.writestr(name, '{}')
                with self.assertRaisesRegex(ValueError, 'regional data'):
                    prepare_release.check_planet(planet)

    def test_release_rejects_regional_photo_sheets(self):
        with tempfile.TemporaryDirectory() as tmp:
            planet = Path(tmp) / 'planet.zip'
            with zipfile.ZipFile(planet, 'w') as archive:
                archive.writestr('earthng/planet/manifest.json', json.dumps({'runtime': 'lua'}))
                archive.writestr('earthng/planet/photos/index.json', json.dumps([{'maxZoom': 18}]))
            with self.assertRaisesRegex(ValueError, 'regional imagery'):
                prepare_release.check_planet(planet)


class InstallTests(unittest.TestCase):
    def test_the_planet_takes_its_name_only_when_whole(self):
        # a copy cut short left half a planet in the game's mods folder, and the game unmounts
        # every ZIP mod over one bad archive (23.11.2026)
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'built.zip', Path(tmp) / 'mods' / build_mod.ZIP
            target.parent.mkdir()
            source.write_bytes(b'new planet' * 1000)
            target.write_bytes(b'old planet')
            build_mod.install(source, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual([f.name for f in target.parent.iterdir()], [build_mod.ZIP])

    def test_a_failed_copy_leaves_the_old_planet(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / build_mod.ZIP
            target.write_bytes(b'old planet')
            with self.assertRaises(OSError):
                build_mod.install(Path(tmp) / 'missing.zip', target)
            self.assertEqual(target.read_bytes(), b'old planet')
