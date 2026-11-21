"""The FoliMesh client: its calls, the cache that pays for a model once, the recipe's order."""
import json
from pathlib import Path
import tempfile
import unittest

import build_flora
import folimesh
import test_flora_mesh

GLB = b'glTF' + b'\0' * 40


class Server:
    """A stand-in for the endpoint: records the calls, answers like an MCP server."""

    def __init__(self, downloads=5, shape='text'):
        self.calls, self.downloads, self.shape = [], downloads, shape

    def __call__(self, payload, key):
        self.calls.append((payload['method'], payload.get('params', {}).get('name'), payload.get('params', {}).get('arguments')))
        self.key = key
        if payload['method'] != 'tools/call':
            return {'jsonrpc': '2.0', 'id': payload['id'], 'result': {'tools': [{'name': 'list_species'}]}}
        name, args = payload['params']['name'], payload['params']['arguments']
        if name == 'get_balance':
            data = {'plan': 'indie', 'downloads': self.downloads, 'aiCredits': 20}
        elif name == 'export_glb':
            if self.downloads <= 0:
                return {'jsonrpc': '2.0', 'id': payload['id'], 'result': {'isError': True, 'content': [
                    {'type': 'text', 'text': 'No downloads left'}]}}
            self.downloads -= 1
            data = {'url': f"https://folimesh.com/dl/{args['species']}_{args.get('seed')}.glb", 'expires': '24h'}
        elif name == 'list_species':
            data = [{'slug': 'oak', 'category': 'trees'}]
        else:
            data = {'species': args.get('species'), 'triangles': [20000, 9000, 3000, 600]}
        if self.shape == 'structured':
            return {'jsonrpc': '2.0', 'id': payload['id'], 'result': {'structuredContent': data, 'content': []}}
        return {'jsonrpc': '2.0', 'id': payload['id'], 'result': {'content': [{'type': 'text', 'text': json.dumps(data)}]}}


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / 'cache'
        self.server = Server()
        self.fetched = []
        self.client = folimesh.Client('fm_test', self.server, self.cache, pace=0, sleep=lambda s: None)

    def tearDown(self):
        self.tmp.cleanup()

    def download(self, url):
        self.fetched.append(url)
        return GLB

    def test_a_call_names_the_tool_and_drops_absent_arguments(self):
        self.assertEqual(self.client.stats('oak', seed=2)['triangles'][0], 20000)
        self.assertEqual(self.server.calls[-1], ('tools/call', 'get_stats', {'species': 'oak', 'seed': 2}))
        self.assertEqual(self.server.key, 'fm_test')

    def test_structured_and_text_replies_read_the_same(self):
        other = folimesh.Client('k', Server(shape='structured'), self.cache)
        self.assertEqual(other.balance(), self.client.balance())

    def test_an_export_is_downloaded_once(self):
        path, fresh = self.client.export('oak', 2, 80, download=self.download)
        self.assertTrue(fresh)
        self.assertEqual(path.name, 'oak_s2_a80.glb')
        self.assertEqual(path.read_bytes(), GLB)
        again, fresh = self.client.export('oak', 2, 80, download=self.download)
        self.assertFalse(fresh)
        self.assertEqual(len(self.fetched), 1)
        self.assertEqual(self.server.downloads, 4)
        log = [json.loads(line) for line in (self.cache / 'log.jsonl').read_text(encoding='utf8').splitlines()]
        self.assertEqual((log[0]['file'], log[0]['seed'], log[0]['age']), ('oak_s2_a80.glb', 2, 80))

    def test_what_is_not_a_glb_is_not_kept(self):
        with self.assertRaises(folimesh.FoliMeshError):
            self.client.export('oak', 1, download=lambda url: b'<html>')
        self.assertFalse(self.client.path('oak', 1).exists())

    def test_an_error_of_the_server_is_raised_with_its_words(self):
        self.server.downloads = 0
        with self.assertRaisesRegex(folimesh.FoliMeshError, 'No downloads left'):
            self.client.export('oak', 1, download=self.download)
        with self.assertRaisesRegex(folimesh.FoliMeshError, 'Invalid API key'):
            folimesh.unwrap({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32001, 'message': 'Invalid API key'}})

    def test_without_a_key_nothing_is_sent(self):
        client = folimesh.Client('', self.server, self.cache)
        client.key = None
        with self.assertRaisesRegex(folimesh.FoliMeshError, 'no API key'):
            client.balance()
        self.assertEqual(self.server.calls, [])

    def test_the_link_is_found_wherever_the_reply_holds_it(self):
        self.assertEqual(folimesh.find_url({'file': {'download_url': 'https://a/b.glb'}}), 'https://a/b.glb')
        self.assertEqual(folimesh.find_url('Ready: https://a/b.glb. Valid 24 h'), 'https://a/b.glb')
        self.assertIsNone(folimesh.find_url({'ok': True}))

    def test_cache_names_tell_variants_apart(self):
        self.assertEqual(folimesh.slug_of('stone-pine', 3, 40), 'stone_pine_s3_a40')
        self.assertEqual(folimesh.slug_of('oak'), 'oak_s1')
        self.assertEqual(folimesh.slug_of('oak', 1, None, 'lowpoly'), 'oak_s1_lowpoly')
        with self.assertRaises(ValueError):
            folimesh.slug_of('../oak')

    def test_the_balance_is_read_in_the_shapes_a_server_may_give(self):
        self.assertEqual(folimesh.balance_left({'downloads': 12}), 12)
        self.assertEqual(folimesh.balance_left({'balance': {'downloads': {'left': 7, 'monthly': 50}}}), 7)
        self.assertEqual(folimesh.balance_left('You have 31 downloads and 20 AI credits'), 31)
        self.assertIsNone(folimesh.balance_left({'plan': 'indie'}))


class RecipeTest(unittest.TestCase):
    def test_the_recipe_of_ukraine_reads_and_names_known_species(self):
        recipe = folimesh.recipe('ukraine')
        models = folimesh.wanted(recipe)
        self.assertGreater(len(models), 50)
        names = [(m['species'], m['seed'], m['age']) for m in models]
        self.assertEqual(len(names), len(set(names)), 'a model listed twice would be paid for once but built twice')
        # the leading trees of the three zones come before anything second
        first = [m['name'] for m in models[:14]]
        for species in ('pine', 'oak', 'birch', 'hornbeam', 'beech', 'spruce', 'alder'):
            self.assertIn(species, first)
        # a species' second variant waits for every first one of its priority
        self.assertLess(first.index('oak'), next(i for i, m in enumerate(models) if m['name'] == 'oak' and m['seed'] == 2))

    def test_the_recipes_trees_are_the_floras(self):
        from lupa.luajit21 import LuaRuntime
        lua = LuaRuntime(unpack_returned_tuples=True)
        flora = lua.eval('function(s) return assert(load(s, "@flora.lua"))() end')(
            (folimesh.ROOT / 'mod/lua/ge/extensions/e2r/flora.lua').read_text(encoding='utf8'))
        known = set(flora.SPECIES.keys())
        stock = set(flora.STOCK.keys())
        named = set()
        for region in folimesh.regions():
            names = set(folimesh.recipe(region)['species'])
            self.assertEqual(names & named, set(), f'{region} names a species another recipe has')
            named |= names
        self.assertEqual(named - known, set(), 'models the flora does not plant')
        # what the flora plants and no recipe has stands as the game's own trees
        self.assertEqual(known - named - stock, set())

    def test_every_recipe_reads_and_all_of_them_make_one_list(self):
        self.assertEqual(folimesh.regions()[0], 'ukraine')
        models = folimesh.wanted_all()
        files = [folimesh.slug_of(m['species'], m['seed'], m['age'], m['style']) for m in models]
        self.assertEqual(len(files), len(set(files)), 'a model listed twice')
        self.assertGreater(len(models), 100)
        # a region's first models are not behind another's last
        first = {m['region'] for m in models[:40]}
        self.assertEqual(first, set(folimesh.regions()))
        # a variant may be another FoliMesh species: the old oak is an oak
        old = next(m for m in models if m['species'] == 'old-oak')
        self.assertEqual(old['name'], 'oak')
        for region in folimesh.regions():
            for name, plant in folimesh.recipe(region)['species'].items():
                self.assertRegex(name, r'^[a-z][a-z0-9_]*$')
                self.assertTrue(plant.get('use'), f'{name}: a block belongs to some place')

    def test_fetch_takes_the_most_needed_within_the_balance(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Server(downloads=4)
            client = folimesh.Client('k', server, Path(tmp), pace=0, sleep=lambda s: None)
            real = folimesh.fetch_bytes
            folimesh.fetch_bytes = lambda url, timeout=300: GLB
            try:
                have, got, missing = folimesh.fetch(client, 'ukraine', limit=10, reserve=1, say=lambda *a: None)
            finally:
                folimesh.fetch_bytes = real
            self.assertEqual(len(got), 3)
            self.assertEqual(server.downloads, 1)
            self.assertEqual(got[0], 'pine_s1_a70.glb')
            # again: nothing is paid for twice
            have, got2, _ = folimesh.fetch(client, 'ukraine', dry=True, say=lambda *a: None)
            self.assertEqual(sorted(have), sorted(got))


class PackTest(unittest.TestCase):
    def test_fetched_models_become_a_pack_with_a_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cache = tmp / 'cache'
            cache.mkdir()
            test_flora_mesh.write_tree(cache / 'oak_s1_a80.glb', height=24.0)
            test_flora_mesh.write_tree(cache / 'oak_s11_a7.glb', height=3.0)
            test_flora_mesh.write_tree(cache / 'barberry_s1.glb', height=2.0)
            pack, manifest = build_flora.build('ukraine', cache, tmp / 'data', say=lambda *a: None)
            species = manifest['species']
            self.assertEqual(sorted(species), ['barberry', 'oak', 'oak_young'])
            self.assertEqual(species['oak']['models'][0]['shape'], '/art/shapes/earthng/flora/trees/oak/oak_s1_a80.dae')
            self.assertEqual(species['oak_young']['models'][0]['shape'],
                             '/art/shapes/earthng/flora/trees/oak_young/oak_young_s11_a7.dae')
            self.assertAlmostEqual(species['oak']['models'][0]['height'], 24, places=2)
            out = build_flora.pack_zip(pack, tmp / 'earthng_flora.zip')
            import zipfile
            names = zipfile.ZipFile(out).namelist()
            self.assertIn('art/shapes/earthng/flora/flora.json', names)
            self.assertIn('art/shapes/earthng/flora/trees/oak/oak_s1_a80.dae', names)
            self.assertIn('art/shapes/earthng/flora/NOTICE.txt', names)
            self.assertTrue(all(n.startswith('art/shapes/earthng/flora/') for n in names))
            # a texture is packed once: its DDS where it has one
            for name in names:
                if name.endswith('.png'):
                    self.assertNotIn(name[:-4] + '.dds', names)
            blocks = build_flora.blocks(manifest)
            # by layer, then by species: the canopy before the shrubs
            self.assertEqual([b['id'] for b in blocks], ['oak_s1_a80', 'barberry_s1', 'oak_young_s11_a7'])
            oak = blocks[0]
            self.assertEqual((oak['species'], oak['layer'], oak['region']), ('oak', 'canopy', 'ukraine'))
            self.assertIn('forest', oak['use'])
            self.assertEqual(blocks[1]['layer'], 'shrub')

    def test_a_variant_of_another_slug_keeps_its_own_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cache = tmp / 'cache'
            cache.mkdir()
            test_flora_mesh.write_tree(cache / 'oak_s1_a80.glb', height=24.0)
            test_flora_mesh.write_tree(cache / 'old_oak_s1.glb', height=18.0)
            test_flora_mesh.write_tree(cache / 'palm_coconut_s1.glb', height=19.0)
            pack, manifest = build_flora.build('all', cache, tmp / 'data', say=lambda *a: None)
            shapes = [m['shape'].rsplit('/', 1)[-1] for m in manifest['species']['oak']['models']]
            self.assertEqual(shapes, ['oak_s1_a80.dae', 'oak_old_oak_s1.dae'])
            self.assertEqual(manifest['species']['coconut_palm']['region'], 'tropics')
            self.assertEqual(manifest['regions'][0], 'ukraine')


if __name__ == '__main__':
    unittest.main()
