"""The native Map Builder: switched by EARTHNG_NATIVE, and its cut keeps the objects osm_tiles.cut keeps."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import osmium

import native_tool
import osm_tiles


def objects(path):
    nodes, ways, rels = {}, {}, {}
    for o in osmium.FileProcessor(str(path)):
        tags = tuple(sorted((t.k, t.v) for t in o.tags))
        if o.is_node():
            nodes[o.id] = ((o.location.x, o.location.y), tags)
        elif o.is_way():
            ways[o.id] = (tuple(n.ref for n in o.nodes), tags)
        else:
            rels[o.id] = (tuple((m.type, m.ref, m.role) for m in o.members), tags)
    return nodes, ways, rels


def fixture(path):
    """Cells 600..601 x 1000..1001 (lon 30.00-30.10, lat 50.00-50.10) and things round them:
    a way leaving the package, nodes in the buffer, a multipolygon whose outer way lies outside,
    a nested landmark relation, a restriction with a missing member, a node with only meta tags."""
    n = osmium.osm.mutable.Node
    w = osmium.osm.mutable.Way
    r = osmium.osm.mutable.Relation
    with osmium.SimpleWriter(str(path)) as out:
        points = {
            1: (30.02, 50.02, {}), 2: (30.04, 50.03, {}), 3: (30.055, 50.03, {}),     # 3: in both cells' buffers
            4: (30.30, 50.30, {}),                                                     # far outside
            5: (30.03, 50.07, {'highway': 'street_lamp'}),                             # POI
            6: (30.031, 50.071, {'created_by': 'JOSM', 'source': 'survey'}),           # meta only
            7: (30.50, 50.50, {}), 8: (30.51, 50.50, {}), 9: (30.51, 50.51, {}),       # outside ring
            10: (30.075, 50.0099, {'amenity': 'bench', 'name': 'Лавка'}),              # buffer below the package
            11: (-30.0, -50.0, {}),
        }
        for nid, (lon, lat, tags) in points.items():
            out.add_node(n(id=nid, location=(lon, lat), tags=tags))
        out.add_way(w(id=100, nodes=[1, 2, 3], tags={'highway': 'residential', 'name': 'Вулиця'}))
        out.add_way(w(id=101, nodes=[3, 4], tags={'highway': 'primary'}))             # leaves the package
        out.add_way(w(id=102, nodes=[7, 8, 9, 7], tags={}))                            # outer way, far away
        out.add_way(w(id=103, nodes=[11, 7], tags={'highway': 'track'}))               # nowhere near
        out.add_relation(r(id=200, members=[('w', 102, 'outer'), ('w', 100, 'inner')],
                           tags={'type': 'multipolygon', 'landuse': 'forest'}))
        out.add_relation(r(id=201, members=[('r', 200, ''), ('n', 5, 'label')],
                           tags={'type': 'site', 'historic': 'castle'}))
        out.add_relation(r(id=202, members=[('w', 100, 'from'), ('n', 3, 'via'), ('w', 999, 'to')],
                           tags={'type': 'restriction', 'restriction': 'no_left_turn'}))
        out.add_relation(r(id=203, members=[('w', 101, '')], tags={'type': 'route', 'route': 'bus'}))


class NativeToolTests(unittest.TestCase):
    def test_switch_and_command(self):
        with patch.dict(os.environ, {'EARTHNG_NATIVE': '0'}):
            self.assertIsNone(native_tool.tool())
            self.assertIsNone(native_tool.cut_command('a.osm.pbf', 'out'))
        fake = Path('C:/x/earthng-mapbuilder.exe')
        with patch.object(native_tool, 'tool', return_value=fake):
            command = native_tool.cut_command('a.osm.pbf', 'out', [-1.5, 2, 3, 4.25])
        self.assertEqual(command, [str(fake), 'cut', 'a.osm.pbf', '--out', 'out',
                                   '--package-box', '-1.5', '2.0', '3.0', '4.25'])

    @unittest.skipUnless(native_tool.tool(), 'native Map Builder not built (cargo build --release in rust/)')
    def test_native_cut_matches_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pbf = tmp / 'fixture.osm.pbf'
            fixture(pbf)
            box = [29.99, 49.99, 30.11, 50.11]
            osm_tiles.cut(pbf, tmp / 'python', box)
            subprocess.run(native_tool.cut_command(pbf, tmp / 'native', box), check=True, capture_output=True)
            a = json.loads((tmp / 'python' / 'index.json').read_text(encoding='utf8'))
            b = json.loads((tmp / 'native' / 'index.json').read_text(encoding='utf8'))
            self.assertEqual(sorted(a['tiles']), sorted(b['tiles']))
            self.assertEqual(a['package_box'], b['package_box'])
            self.assertEqual(b['select'], osm_tiles.SELECT)
            self.assertTrue(a['tiles'])
            for key, tile in a['tiles'].items():
                other = b['tiles'][key]
                for field in ('cell', 'coverage', 'nodes', 'ways', 'relations'):
                    self.assertEqual(tile[field], other[field], (key, field))
                self.assertEqual(objects(tmp / 'python' / tile['file']), objects(tmp / 'native' / other['file']), key)


if __name__ == '__main__':
    unittest.main()


class NativeDemTests(unittest.TestCase):
    @unittest.skipUnless(native_tool.kernels(), 'earthng_native.dll not built (cargo build --release in rust/)')
    def test_dem_matches_numpy_and_reports_missing_tiles(self):
        import numpy as np
        from PIL import Image
        import build_country
        import fast_sources
        frame = fast_sources.Frame.at(30.52, 50.45)
        rng = np.random.default_rng(7)
        with tempfile.TemporaryDirectory() as tmp:
            scale = 256 * 2 ** 12
            lon, lat = frame.geographic(np.array([-3000., 3000.]), np.array([-3000., 3000.]))
            xs = ((np.array(lon) + 180) / 360 * scale // 256).astype(int)
            ys = ((1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * scale // 256).astype(int)
            for a in range(min(xs) - 1, max(xs) + 2):
                for b in range(min(ys) - 1, max(ys) + 2):
                    folder = Path(tmp) / 'terrain' / '12' / str(a)
                    folder.mkdir(parents=True, exist_ok=True)
                    rgb = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
                    rgb[:, :, 0] = 128          # ~0..255 m with a fine fraction
                    Image.fromarray(rgb, 'RGB').save(folder / f'{b}.png')
            terrain = fast_sources.Terrain(tmp, frame)
            self.assertIsNotNone(terrain.native())
            xy = rng.uniform(-2500, 2500, (5000, 2))
            fast = terrain.sample(xy), terrain.sample(xy, smooth=True)
            despiked = build_country.Despiked(terrain)
            grid_axes = np.arange(0., 250., 25.), np.arange(100., 300., 25.)
            fast_d = despiked.sample(xy[:500]), despiked.grid(*grid_axes)
            terrain._native = False
            slow = terrain.sample(xy), terrain.sample(xy, smooth=True)
            slow_d = despiked.sample(xy[:500]), despiked.grid(*grid_axes)
            for a, b in zip(fast + fast_d, slow + slow_d):
                self.assertLess(np.abs(a - b).max(), 1e-6)
            terrain._native = None
            with self.assertRaisesRegex(FileNotFoundError, 'no_dem'):
                terrain.sample([[5e6, 0.]])


class NativeRoutingTests(unittest.TestCase):
    @unittest.skipUnless(native_tool.tool(), 'native Map Builder not built (cargo build --release in rust/)')
    def test_routing_files_match_build_routing(self):
        import zipfile
        import build_routing
        import country_format as binary

        def road(rid, nodes, points, **tags):
            return {'id': str(rid), 'width': 6.0, 'tags': tags, 'nodes': [str(n) for n in nodes],
                    'points': [[x, y, 1.25] for x, y in points]}
        roads = [road(1, [10, 11], [(5, 5), (60.004, 5.5), (120, 5)], highway='primary', name='Хрещатик', maxspeed='30 mph'),
                 road(2, [11, 12], [(120, 5), (120, 300)], highway='residential', oneway='-1', **{'name:uk': 'Бічна'}),
                 road(3, [12, 13], [(120, 300), (400, 320), (700, 300)], highway='motorway_link', ref='M06'),
                 road(4, [13, 10], [(700, 300), (5, 5)], highway='tertiary', junction='roundabout', maxspeed='RU:urban'),
                 road(5, [12, 14], [(120, 300), (130, 900)], highway='service'),            # not routable
                 road(6, [14, 15], [(130, 900), (900, 990)], highway='residential', access='private'),
                 road(7, [15, 16], [(900, 990), (980, 980)], highway='unclassified', maxspeed='5_0')]
        cell = lambda rs: {'terrain': {'nx': 2, 'ny': 2, 'heights': [1., 2., 3., 4.]}, 'roads': rs}
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / 'pack.zip'
            prefix = 'earthng/countries/xx/regions/r1/'
            with zipfile.ZipFile(pack, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr(prefix + 'manifest.json', json.dumps({'cellSize': 1000, 'blockCells': 8}))
                # the same road stored in two cells, as a road crossing a cell border is
                payloads = {binary.slot(0, 0): binary.encode_cell(cell(roads), (0, 0)),
                            binary.slot(1, 0): binary.encode_cell(cell(roads[2:4]), (1000, 0))}
                z.writestr(prefix + 'blocks/0_0.bin', binary.encode_block(payloads)[0])
            expected = build_routing.build_region((str(pack), 'r1', prefix))[1]
            built = native_tool.routing(pack, emit=lambda line: None)
        self.assertEqual(built, [('r1', expected)])


class FallbackTests(unittest.TestCase):
    def test_a_failed_native_cut_is_cut_again_in_python(self):
        import country_fetch
        calls = []

        def run_step(command, emit=print, cancel=None):
            calls.append(command)
            if len(calls) == 1:
                raise subprocess.CalledProcessError(3, command)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(native_tool, 'cut_command', lambda pbf, out, box=None, threads=None: ['native', str(out)]), \
                patch.object(country_fetch, 'run_step', run_step), \
                patch.object(country_fetch, 'tiles_current', lambda tiles: False):
            (Path(tmp) / 'tiles.part').mkdir()          # what the native cut leaves when it fails
            country_fetch.cut_tiles(Path(tmp) / 'x.osm.pbf', Path(tmp) / 'tiles', jobs=2, heavy_jobs=1,
                                    emit=lambda line: None)
            self.assertFalse((Path(tmp) / 'tiles.part').exists())
        self.assertEqual(calls[0][0], 'native')
        self.assertTrue(calls[1][1].endswith('osm_tiles_country.py'))
