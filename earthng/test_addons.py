"""Proving ground and flora packs beside the planet: the catalog, the checks, the install with the
planet and the map (addons.py, app_service.py; no network)."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

import addons
import app_service
import prepare_release
from test_app_service import Recorder, planet_zip

ROOT = Path(__file__).resolve().parents[1]


def pack_zip(path, kind):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(addons.KNOWN[kind]['marker'], json.dumps({'id': kind}))
        archive.writestr(f'{kind}/payload.bin', kind * 50)
    return path


class CatalogTests(unittest.TestCase):
    def test_the_committed_catalog_offers_both_packs_from_a_github_release(self):
        entries = addons.load()
        self.assertEqual([e['id'] for e in entries], ['polygon', 'flora'])
        for entry in entries:
            self.assertTrue(entry['url'].startswith(f'{addons.RELEASES}/v'), entry['url'])
            self.assertTrue(entry['url'].endswith('/' + entry['file']))

    def test_the_runtime_carries_the_catalog(self):
        names = [p.relative_to(ROOT).as_posix() for p in (ROOT / 'earthng').glob('*.py')]
        names += ['earthng/addons.json', 'earthng/fast_tree_materials.json', 'earthng/area_land.wkb.gz',
                  'requirements-fast.txt', 'LICENSE', 'THIRD_PARTY_NOTICES.md']
        files = {name: (ROOT / name).read_bytes() for name in names}
        selected = prepare_release.builder_files(files, start=('app_service',))
        self.assertIn('earthng/addons.py', selected)
        self.assertIn('earthng/addons.json', selected)

    def test_write_reads_the_packs_and_load_refuses_rows_it_cannot_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            polygon = pack_zip(tmp / 'earthng_polygon.zip', 'polygon')
            flora = pack_zip(tmp / 'earthng_flora.zip', 'flora')
            out = tmp / 'addons.json'
            addons.write([flora, polygon], 'v9.9.9', out)
            entries = addons.load(out)
            self.assertEqual([e['id'] for e in entries], ['polygon', 'flora'])
            self.assertEqual(entries[1]['sha256'], hashlib.sha256(flora.read_bytes()).hexdigest())
            self.assertEqual(entries[0]['url'], f'{addons.RELEASES}/v9.9.9/earthng_polygon.zip')
            with self.assertRaisesRegex(ValueError, 'published as'):
                addons.entry_for(pack_zip(tmp / 'trees.zip', 'flora'), 'v1')
            with self.assertRaisesRegex(ValueError, 'not the proving ground'):
                addons.entry_for(planet_zip(tmp / 'earthng_planet.zip'), 'v1')
            payload = json.loads(out.read_text(encoding='utf-8'))
            payload['addons'][0]['url'] = 'http://example.org/earthng_polygon.zip'
            payload['addons'][1]['file'] = '../earthng_flora.zip'
            out.write_text(json.dumps(payload), encoding='utf-8')
            self.assertEqual(addons.load(out), [])
            self.assertEqual(addons.load(tmp / 'missing.json'), [])


class ServiceAddonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.game = self.root / 'BeamNG' / 'current'
        (self.game / 'mods').mkdir(parents=True)
        self.served = self.root / 'served'
        self.served.mkdir()
        self.packs = {k: pack_zip(self.served / addons.KNOWN[k]['file'], k) for k in addons.KNOWN}
        self.catalog = self.root / 'addons.json'
        addons.write(list(self.packs.values()), 'v1.1.0', self.catalog)
        self.planet = planet_zip(self.served / app_service.PLANET, '1.1.0')
        self.out = Recorder()
        with patch.object(app_service.country_fetch, 'default_mods', return_value=self.game):
            self.service = app_service.Service(out=self.out, root=self.root / 'home')
        self.service.addons_path = self.catalog
        self.downloaded = []

    def tearDown(self):
        self.tmp.cleanup()

    def ask(self, **request):
        self.service.handle({'id': 7, **request})
        return self.out.messages()[-1]

    def wait_done(self):
        self.service.job.join(30)
        return [m for m in self.out.messages() if m.get('event') == 'done'][-1]

    def stages(self):
        return [m['name'] for m in self.out.messages() if m.get('event') == 'stage' and m['seconds'] is None]

    def serve(self, broken=()):
        """country_fetch.download from self.served; a name in broken arrives with other bytes."""
        def download(url, dest, emit=print, cancel=None):
            name = url.rsplit('/', 1)[-1]
            self.downloaded.append(name)
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            data = (self.served / name).read_bytes()
            Path(dest).write_bytes(data[:-1] + b'!' if name in broken else data)
            return dest
        return patch.object(app_service.country_fetch, 'download', side_effect=download)

    def planet_version(self):
        return patch.object(app_service, 'build_info', return_value={'planetVersion': '1.1.0'})

    def test_status_lists_the_packs_chosen_until_the_player_says_otherwise(self):
        state = self.ask(cmd='status')['addons']
        self.assertEqual([(a['id'], a['state'], a['chosen']) for a in state],
                         [('polygon', 'missing', True), ('flora', 'missing', True)])
        self.assertEqual(state[1]['size'], self.packs['flora'].stat().st_size)
        answer = self.ask(cmd='set_addons', chosen=['flora'])
        self.assertEqual([a['chosen'] for a in answer['addons']], [False, True])
        self.assertFalse(self.ask(cmd='set_addons', chosen=['../x'])['ok'])
        with patch.object(app_service.country_fetch, 'default_mods', return_value=self.game):
            again = app_service.Service(out=Recorder(), root=self.root / 'home')
        again.addons_path = self.catalog
        self.assertEqual(again.chosen_addons(), {'flora'})

    def test_installing_the_planet_brings_the_chosen_packs(self):
        self.ask(cmd='set_addons', chosen=['polygon', 'flora'])
        with self.serve(), self.planet_version():
            self.assertTrue(self.ask(cmd='install_planet')['ok'])
            done = self.wait_done()
        self.assertEqual(done['result'], 'complete', done)
        self.assertNotIn('warnings', done)
        self.assertEqual(self.downloaded, [app_service.PLANET, 'earthng_polygon.zip', 'earthng_flora.zip'])
        self.assertEqual(self.stages(), ['Planet', 'Add-ons'])
        for kind, source in self.packs.items():
            self.assertEqual((self.game / 'mods' / source.name).read_bytes(), source.read_bytes())
        self.assertEqual([a['state'] for a in self.ask(cmd='status')['addons']], ['installed', 'installed'])
        self.assertFalse((self.service.root / 'downloads' / 'earthng_flora.zip').exists())
        self.assertFalse(list((self.game / 'mods').glob('*.part')))

    def test_an_unchosen_pack_stays_out_and_an_installed_one_is_not_fetched_again(self):
        self.ask(cmd='set_addons', chosen=['polygon'])
        with self.serve(), self.planet_version():
            self.ask(cmd='install_planet')
            self.wait_done()
            self.assertFalse((self.game / 'mods' / 'earthng_flora.zip').exists())
            self.assertEqual(self.downloaded.count('earthng_polygon.zip'), 1)
            self.assertFalse(self.ask(cmd='install_addons')['ok'])        # nothing left to install
            self.ask(cmd='set_addons', chosen=['polygon', 'flora'])
            self.assertTrue(self.ask(cmd='install_addons')['ok'])
            done = self.wait_done()
        self.assertEqual(done['result'], 'complete', done)
        self.assertEqual(self.downloaded.count('earthng_polygon.zip'), 1)
        self.assertEqual(self.downloaded.count(app_service.PLANET), 1)    # the planet was current
        self.assertTrue((self.game / 'mods' / 'earthng_flora.zip').exists())

    def test_another_build_of_a_pack_is_replaced(self):
        (self.game / 'mods' / 'earthng_polygon.zip').write_bytes(b'an older proving ground')
        self.assertEqual(self.ask(cmd='status')['addons'][0]['state'], 'other')
        self.ask(cmd='set_addons', chosen=['polygon'])
        planet_zip(self.game / 'mods' / app_service.PLANET, '1.1.0')
        with self.serve(), self.planet_version():
            self.assertTrue(self.ask(cmd='install_addons')['ok'])
            self.assertEqual(self.wait_done()['result'], 'complete')
        self.assertEqual(self.downloaded, ['earthng_polygon.zip'])
        self.assertEqual((self.game / 'mods' / 'earthng_polygon.zip').read_bytes(), self.packs['polygon'].read_bytes())

    def test_a_file_that_is_not_the_release_is_never_installed(self):
        with self.serve(broken={'earthng_flora.zip'}), self.planet_version():
            self.ask(cmd='install_planet')
            done = self.wait_done()
        # the planet and the proving ground are in; the flora pack is a warning, not a failure
        self.assertEqual(done['result'], 'complete', done)
        self.assertEqual(len(done['warnings']), 1)
        self.assertIn('earthng_flora.zip', done['warnings'][0])
        self.assertFalse((self.game / 'mods' / 'earthng_flora.zip').exists())
        self.assertFalse((self.service.root / 'downloads' / 'earthng_flora.zip').exists())
        self.assertTrue((self.game / 'mods' / 'earthng_polygon.zip').exists())
        with self.serve(broken={'earthng_flora.zip'}), self.planet_version():
            self.ask(cmd='install_addons')
            done = self.wait_done()
        self.assertEqual(done['result'], 'failed', done)      # asked for on its own: a failure
        self.assertIn('does not match the release', done['error'])

    def test_stop_during_a_pack_stops_the_job(self):
        def stopped(url, dest, emit=print, cancel=None):
            raise InterruptedError('download stopped')
        planet_zip(self.game / 'mods' / app_service.PLANET, '1.1.0')
        with patch.object(app_service.country_fetch, 'download', side_effect=stopped), self.planet_version():
            self.ask(cmd='install_addons')
            self.assertEqual(self.wait_done()['result'], 'stopped')

    def test_a_build_installs_planet_then_packs_then_the_map(self):
        self.service.places = [{'id': 'albania', 'name': 'Albania', 'pbf': 'https://x/albania.osm.pbf'}]
        self.service.by_id = {'albania': self.service.places[0]}
        self.service.boundaries = {}
        order = []

        def fake_build(place, mods, **kw):
            order.append(sorted(p.name for p in (Path(mods) / 'mods').glob('*.zip')))
            return Path(mods) / 'mods' / 'earthng_albania.zip'
        with self.serve(), self.planet_version(), \
                patch.object(app_service.country_fetch, 'build_place', side_effect=fake_build), \
                patch.object(app_service.country_fetch, 'content_length', return_value=8_000_000), \
                patch.object(app_service.country_fetch, 'tiles_current', return_value=True):
            estimate = self.ask(cmd='estimate', place='albania', box=[19.8, 41.3, 19.9, 41.35])
            self.assertEqual(estimate['stages'][:3], ['Planet', 'Add-ons', 'Sources'], estimate)
            self.assertEqual(estimate['addons'], ['polygon', 'flora'])
            self.assertEqual(len(estimate['seconds']), len(estimate['stages']))
            self.assertTrue(self.ask(cmd='build', place='albania', box=[19.8, 41.3, 19.9, 41.35])['ok'])
            done = self.wait_done()
            self.assertEqual(done['result'], 'complete', done)
            self.assertEqual(order, [['earthng_flora.zip', 'earthng_planet.zip', 'earthng_polygon.zip']])
            self.assertEqual(self.stages()[:2], ['Planet', 'Add-ons'])
            again = self.ask(cmd='estimate', place='albania', box=[19.8, 41.3, 19.9, 41.35])
            self.assertEqual(again['stages'][0], 'Sources')
            self.assertEqual(again['addons'], [])

    def test_a_ready_pack_brings_the_chosen_packs_too(self):
        local = self.service.root / 'out' / 'native-packs'
        local.mkdir(parents=True)
        with zipfile.ZipFile(local / 'earthng_albania.zip', 'w') as archive:
            archive.writestr('earthng/countries/albania/manifest.json', '{}')
        self.ask(cmd='set_addons', chosen=['polygon'])
        catalog = [{'id': 'albania', 'title': 'Albania', 'url': ''}]
        with self.serve(), self.planet_version(), \
                patch.object(app_service.country_fetch, 'catalog_entries', return_value=catalog):
            self.assertTrue(self.ask(cmd='install_ready_pack', pack='albania')['ok'])
            done = self.wait_done()
        self.assertEqual(done['result'], 'complete', done)
        self.assertEqual(self.stages(), ['Planet', 'Add-ons', 'Install'])
        self.assertTrue((self.game / 'mods' / 'earthng_polygon.zip').exists())
        self.assertTrue((self.game / 'mods' / 'earthng_albania.zip').exists())

    def test_without_a_catalog_nothing_is_offered(self):
        self.service.addons_path = self.root / 'none.json'
        self.assertEqual(self.ask(cmd='status')['addons'], [])
        with self.serve(), self.planet_version():
            self.ask(cmd='install_planet')
            self.assertEqual(self.wait_done()['result'], 'complete')
        self.assertEqual(self.downloaded, [app_service.PLANET])


if __name__ == '__main__':
    unittest.main()
