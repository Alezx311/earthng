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

    @unittest.skipUnless(native_tool.tool(), 'native Map Builder not built (cargo build --release in rust/)')
    def test_selection_cut_grows_to_whole_cells_like_python(self):
        import country_fetch
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pbf = tmp / 'fixture.osm.pbf'
            fixture(pbf)
            selection = [30.02, 50.02, 30.08, 50.06]            # inside a few cells, wholly inside none
            country_fetch.cut_tiles(pbf, tmp / 'tiles-cells', selection, emit=lambda _: None)
            index = json.loads((tmp / 'tiles-cells' / 'index.json').read_text(encoding='utf8'))
            self.assertEqual(index['cutter'], 'earthng-mapbuilder')
            self.assertEqual(index['package_box'], country_fetch.package_box(pbf, selection))
            osm_tiles.cut(pbf, tmp / 'python', country_fetch.package_box(pbf, selection))
            python = json.loads((tmp / 'python' / 'index.json').read_text(encoding='utf8'))
            self.assertTrue(index['tiles'])
            self.assertEqual(sorted(index['tiles']), sorted(python['tiles']))
            self.assertTrue(country_fetch.tiles_current(tmp / 'tiles-cells', selection))
            # a cut of the bare selection (the native cut before 7.11) is cut again
            subprocess.run(native_tool.cut_command(pbf, tmp / 'bare', selection), check=True, capture_output=True)
            self.assertFalse(country_fetch.tiles_current(tmp / 'bare', selection))
            self.assertTrue(country_fetch.tiles_current(tmp / 'bare'))

    @unittest.skipUnless(native_tool.tool(), 'native Map Builder not built (cargo build --release in rust/)')
    def test_selection_from_a_covering_cut_is_its_own_cut(self):
        import country_fetch
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pbf = tmp / 'fixture.osm.pbf'
            fixture(pbf)
            selection = [30.02, 50.02, 30.08, 50.06]
            self.assertFalse(country_fetch.tiles_from_cover(tmp, 'land', selection, country_fetch.tiles_dir(tmp, 'land', selection)))
            wide = [29.9, 49.9, 30.2, 50.2]
            country_fetch.cut_tiles(pbf, country_fetch.tiles_dir(tmp, 'land', wide), wide, emit=lambda _: None)
            lines = []
            taken = country_fetch.tiles_dir(tmp, 'land', selection)
            self.assertTrue(country_fetch.tiles_from_cover(tmp, 'land', selection, taken, lines.append))
            self.assertTrue(any('taken from land-user-cells' in line for line in lines))
            country_fetch.cut_tiles(pbf, tmp / 'fresh', selection, emit=lambda _: None)
            a = json.loads((taken / 'index.json').read_text(encoding='utf8'))
            b = json.loads((tmp / 'fresh' / 'index.json').read_text(encoding='utf8'))
            self.assertTrue(a['tiles'])
            self.assertEqual(a['package_box'], b['package_box'])
            self.assertEqual({k: t['sha256'] for k, t in a['tiles'].items()}, {k: t['sha256'] for k, t in b['tiles'].items()})
            self.assertTrue(country_fetch.tiles_current(taken, selection))
            for tile in a['tiles'].values():
                self.assertEqual((taken / tile['file']).read_bytes(), (tmp / 'fresh' / tile['file']).read_bytes())
            # a selection reaching past the covering cut is not taken from it
            self.assertFalse(country_fetch.tiles_from_cover(tmp, 'land', [30.0, 50.0, 30.4, 50.1],
                                                            country_fetch.tiles_dir(tmp, 'land', [30.0, 50.0, 30.4, 50.1])))


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
                patch.object(country_fetch, 'tiles_current', lambda tiles, box=None: False):
            (Path(tmp) / 'tiles.part').mkdir()          # what the native cut leaves when it fails
            country_fetch.cut_tiles(Path(tmp) / 'x.osm.pbf', Path(tmp) / 'tiles', jobs=2, heavy_jobs=1,
                                    emit=lambda line: None)
            self.assertFalse((Path(tmp) / 'tiles.part').exists())
        self.assertEqual(calls[0][0], 'native')
        self.assertTrue(calls[1][1].endswith('osm_tiles_country.py'))


class NativeCellsTests(unittest.TestCase):
    """earthng-mapbuilder compile writes compile_cell's payloads: a small region with a real index,
    DEM tiles and a scene of every scenery kind it handles (clips, partition, buildings, lines)."""

    @unittest.skipUnless(native_tool.tool() and native_tool.kernels() and native_tool.geos_library(),
                         'native tools not built (cargo build --release in rust/) or no shapely GEOS')
    def test_native_cells_are_the_python_bytes(self):
        import sqlite3
        import numpy as np
        import shapely
        from PIL import Image
        from shapely.geometry import LineString, Point, Polygon, box
        import build_country
        import country_format
        import fast_sources
        frame = fast_sources.Frame.at(30.525, 50.475)
        rng = np.random.default_rng(3)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            scale = 256 * 2 ** 12
            lon, lat = frame.geographic(np.array([-2500., 2500.]), np.array([-2500., 2500.]))
            xs = ((np.array(lon) + 180) / 360 * scale // 256).astype(int)
            ys = ((1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * scale // 256).astype(int)
            for a in range(min(xs) - 1, max(xs) + 2):
                for b in range(min(ys) - 1, max(ys) + 2):
                    folder = tmp / 'dem' / 'terrain' / '12' / str(a)
                    folder.mkdir(parents=True, exist_ok=True)
                    rgb = np.zeros((256, 256, 3), dtype=np.uint8)
                    rgb[:, :, 0] = 129                       # 256 m and up: no sea near
                    rgb[:, :, 1] = (np.arange(256)[None, :] // 32 + np.arange(256)[:, None] // 64).astype(np.uint8)
                    rgb[:, :, 2] = rng.integers(0, 256, (256, 256), dtype=np.uint8)
                    rgb[rng.integers(0, 256, 40), rng.integers(0, 256, 40), 1] = 200   # spikes for Despiked
                    Image.fromarray(rgb, 'RGB').save(folder / f'{b}.png')
            ix, iy = 610, 1009
            osm = tmp / 'osm'
            osm.mkdir()
            coverage = [ix * .05 - .01, iy * .05 - .01, (ix + 1) * .05 + .01, (iy + 1) * .05 + .01]
            (osm / 'index.json').write_text(json.dumps({'cell': .05, 'buffer': .01, 'tiles': {
                f'{ix}_{iy}': {'coverage': coverage, 'file': 'none.osm.pbf', 'bytes': 1}}}))
            region = tmp / 'region'
            region.mkdir()
            (region / 'region.json').write_text(json.dumps({
                'id': 'test', 'frame': frame.spec(), 'dem': str(tmp / 'dem'), 'demZoom': 12, 'source': str(osm),
                'coverage': [coverage], 'bbox': coverage}))
            db = sqlite3.connect(region / 'sources.sqlite')
            db.execute('CREATE TABLE features(id INTEGER PRIMARY KEY, kind TEXT, data TEXT, geom BLOB)')
            db.execute('CREATE VIRTUAL TABLE bounds USING rtree(id,x0,x1,y0,y1)')
            road = {'xy': [[-1300, -200], [-400, 33.3], [-399.9, 33.3], [300, 700], [1300, 750]],
                    'prof': [[0, 233, 500, 733, 2100], [300.1, 301, 310, 305.5, 320]],
                    'width': 7, 'tags': {'highway': 'residential', 'name': 'Вулиця'},
                    'nodes': [9007199254740993, 'f17']}
            junction = Polygon([(-420, 20), (-380, 20), (-380, 50), (-420, 50)])
            for fid, kind, data, geometry in ((5, 'road', road, LineString(road['xy'])),
                                              (-14319656677, 'junction', {'h': 310.25}, junction)):
                x0, y0, x1, y1 = geometry.bounds
                db.execute('INSERT INTO features VALUES(?,?,?,?)', (fid, kind, json.dumps(data), shapely.to_wkb(geometry)))
                db.execute('INSERT INTO bounds VALUES(?,?,?,?,?)', (fid, x0, x1, y0, y1))
            db.commit()
            db.close()
            records = [
                (-3 * 10**12 - 8, 'grocery_site', {'tags': {'shop': 'supermarket'}}, box(100, 100, 160, 140)),
                (-10**12 - 2, 'stop', {'tags': {'highway': 'bus_stop', 'name': 'Зупинка'}}, Point(-50.25, 12.5)),
                (-40, 'fence', {'tags': {'barrier': 'fence'}}, LineString([(-1500, 10), (-200, 10), (-150, 400)])),
                (-41, 'power', {'tags': {'power': 'line'}}, LineString([(-1600, -50), (1600, -40)])),
                (2, 'forest', {'tags': {'landuse': 'forest'}},
                 shapely.MultiPolygon([Polygon([(-3000, -3000), (500, -3000), (500, 600), (-3000, 600)],
                                               holes=[[(-300, -300), (-300, -100), (-100, -100), (-100, -300)]])])),
                (4, 'meadow', {'tags': {'landuse': 'meadow'}}, Polygon([(-200, -200), (300, -200), (300, 300), (-200, 300)])),
                (6, 'building', {'tags': {'building': 'yes', 'height': '12,5 m', 'building:levels': '4'}},
                 Polygon([(10, 10), (60, 10), (60, 40), (10, 40)])),
                (8, 'building', {'tags': {'building': 'house', 'building:levels': '2;3', 'min_height': '3'}},
                 Polygon([(900, -800), (1300, -800), (1300, -500), (900, -500)])),
                (10, 'water', {'tags': {'natural': 'water'}}, Polygon([(-900, 200), (-700, 200), (-700, 500)])),
                (12, 'paved', {'tags': {'area:highway': 'yes'}}, Polygon([(-250, -250), (0, -250), (0, 0), (-250, 0)])),
                (14, 'park', {'tags': {'leisure': 'park'}}, Point(1e6, 1e6).buffer(1)),    # far: never queried
            ]
            records.sort(key=lambda r: r[0])
            scenes = tmp / 'scenes'
            scenes.mkdir()
            (scenes / f'{ix}_{iy}.scene').write_bytes(fast_sources.write_scene(records))
            store = build_country._despike(fast_sources.Store(region))
            store.scene_dir = scenes
            cells = [(-1, -1), (0, -1), (-1, 0), (0, 0)]
            for i, j in cells:
                padded = [i*1000-100, j*1000-100, (i+1)*1000+100, (j+1)*1000+100]
                self.assertEqual([leaf[4] for leaf in build_country._scenery_plan(store, padded)], [f'{ix}_{iy}'])
            native = build_country._native_cells(store, cells, None)
            self.assertEqual(sorted(native), sorted(cells))
            for i, j in cells:
                rect = [i*1000, j*1000, (i+1)*1000, (j+1)*1000]
                cell = build_country.compile_cell(store, rect)
                self.assertEqual(native[i, j], (country_format.encode_cell(cell, rect[:2]), len(cell['roads'])), (i, j))
            areas = build_country.compile_cell(store, [-1000, -1000, 0, 0])['areas']
            self.assertTrue(any(':cover:' in a['id'] for a in areas))
            with patch.dict(os.environ, {'EARTHNG_NATIVE': '0'}):
                self.assertEqual(build_country._native_cells(store, cells, None), {})
            store.db.close()

    @unittest.skipUnless(native_tool.tool() and native_tool.kernels() and native_tool.geos_library(),
                         'native tools not built (cargo build --release in rust/) or no shapely GEOS')
    def test_cells_by_the_sea_are_the_python_bytes(self):
        """_coast and _flood: a coastline of two ways (Python reads the raw tile, Rust its scene),
        a harbour at sea level, a building with full-width digits; a cell whose coastline tiles
        have no scene yet goes back with COAST_SCENES before any other work."""
        import sqlite3
        import numpy as np
        from osmium.osm.mutable import Node, Way
        from PIL import Image
        import build_country
        import country_format
        import fast_sources
        frame = fast_sources.Frame.at(30.525, 50.475)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            scale = 256 * 2 ** 12
            lon, lat = frame.geographic(np.array([-2500., 2500.]), np.array([-2500., 2500.]))
            xs = ((np.array(lon) + 180) / 360 * scale // 256).astype(int)
            ys = ((1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * scale // 256).astype(int)
            for a in range(min(xs) - 1, max(xs) + 2):
                for b in range(min(ys) - 1, max(ys) + 2):
                    folder = tmp / 'dem' / 'terrain' / '12' / str(a)
                    folder.mkdir(parents=True, exist_ok=True)
                    rgb = np.zeros((256, 256, 3), dtype=np.uint8)
                    rgb[:, :, 0] = 128                       # 0-11 m: the sea's reach
                    rgb[:, :, 1] = (np.arange(256)[None, :] // 32 + np.arange(256)[:, None] // 64).astype(np.uint8)
                    rgb[:, :, 2] = (np.arange(256)[None, :] * 7 % 256).astype(np.uint8)
                    Image.fromarray(rgb, 'RGB').save(folder / f'{b}.png')
            nodes, ways, ident = [], [], [100]

            def node(x, y, tags=None):
                ident[0] += 1
                lo, la = frame.geographic(np.array([float(x)]), np.array([float(y)]))
                nodes.append(Node(id=ident[0], location=(float(lo[0]), float(la[0])), tags=tags or {}))
                return ident[0]

            shared = node(0, -250)
            ways.append(Way(id=50, nodes=[node(-3000, -300), node(-1200, -420), shared],
                            tags={'natural': 'coastline'}))
            ways.append(Way(id=51, nodes=[shared, node(900, -180), node(3000, -350)], tags={'natural': 'coastline'}))
            harbour = [node(-600, -900), node(-200, -900), node(-200, -600), node(-600, -600)]
            ways.append(Way(id=52, nodes=harbour + [harbour[0]], tags={'natural': 'water', 'water': 'harbour'}))
            house = [node(100, 100), node(140, 100), node(140, 130), node(100, 130)]
            ways.append(Way(id=53, nodes=house + [house[0]], tags={'building': 'yes', 'height': '１２'}))
            osm = tmp / 'osm'
            osm.mkdir()
            with osmium.SimpleWriter(str(osm / 'tile.osm.pbf')) as writer:
                for o in nodes:
                    writer.add_node(o)
                for o in ways:
                    writer.add_way(o)
            ix, iy = 610, 1009
            coverage = [ix * .05 - .01, iy * .05 - .01, (ix + 1) * .05 + .01, (iy + 1) * .05 + .01]
            (osm / 'index.json').write_text(json.dumps({'cell': .05, 'buffer': .01, 'tiles': {
                f'{ix}_{iy}': {'coverage': coverage, 'file': 'tile.osm.pbf',
                               'bytes': (osm / 'tile.osm.pbf').stat().st_size}}}))
            region = tmp / 'region'
            region.mkdir()
            (region / 'region.json').write_text(json.dumps({
                'id': 'test', 'frame': frame.spec(), 'dem': str(tmp / 'dem'), 'demZoom': 12, 'source': str(osm),
                'coverage': [coverage], 'bbox': coverage}))
            db = sqlite3.connect(region / 'sources.sqlite')
            db.execute('CREATE TABLE features(id INTEGER PRIMARY KEY, kind TEXT, data TEXT, geom BLOB)')
            db.execute('CREATE VIRTUAL TABLE bounds USING rtree(id,x0,x1,y0,y1)')
            db.commit()
            db.close()
            scenes = tmp / 'scenes'
            scenes.mkdir()
            store = build_country._despike(fast_sources.Store(region))
            store.scene_dir = scenes
            cells = [(-1, -1), (0, -1), (-1, 0), (0, 0)]
            for i, j in cells:
                self.assertEqual(build_country._coast_tiles(store, [i*1000, j*1000, (i+1)*1000, (j+1)*1000]),
                                 [f'{ix}_{iy}'])
            configs = []
            compile_cells = native_tool.compile_cells

            def recorded(config, tasks):
                configs.append(config)
                return compile_cells(config, tasks)
            with patch.object(native_tool, 'compile_cells', recorded):
                native = build_country._native_cells(store, cells, None)
            self.assertEqual(sorted(native), sorted(cells))
            self.assertEqual(len(configs), 1)
            done, left = native_tool.compile_cells(configs[0], [(0, -1, [], [f'{ix}_{iy}', 'no_such_tile'])])
            self.assertEqual((done, left), ({}, {(0, -1): native_tool.COAST_SCENES}))
            lowered = 0
            for i, j in cells:
                rect = [i*1000, j*1000, (i+1)*1000, (j+1)*1000]
                cell = build_country.compile_cell(store, rect)
                lowered += min(cell['terrain']['heights']) < fast_sources.LIFT
                self.assertEqual(native[i, j], (country_format.encode_cell(cell, rect[:2]), len(cell['roads'])), (i, j))
            self.assertEqual(lowered, 2)      # the sea side of the coastline, south of it
            heights = {b['tags']['height']: b['height'] for b in build_country.compile_cell(store, [0, 0, 1000, 1000])['buildings']}
            self.assertEqual(heights, {'１２': 12.0})
            store.db.close()


class NativeIndexTests(unittest.TestCase):
    """The index's native parts: read_ways (earthng-mapbuilder ways) is osmium's dicts, key order
    and all; crossings (earthng_native.dll) is the numpy one bit for bit."""

    @unittest.skipUnless(native_tool.tool(), 'native tool not built (cargo build --release in rust/)')
    def test_native_read_ways_is_osmium(self):
        import hashlib
        from osmium.osm.mutable import Node, Way
        import fast_sources
        self.assertEqual(native_tool.ways_fingerprint(), native_tool.WAYS)
        nodes, ways, ident = [], [], [100]

        def node(dx, dy):
            ident[0] += 1
            nodes.append(Node(id=ident[0], location=(30.5 + dx * 1e-5, 50.45 + dy * 1e-5)))
            return ident[0]
        a, b, c, d = node(0, 0), node(100, 0), node(100, 100), node(0, 100)
        ways.append(Way(id=10, nodes=[a, b, c], tags={'highway': 'residential', 'name': 'Вулиця', 'lanes': '2'}))
        ways.append(Way(id=11, nodes=[c, d], tags={'highway': 'primary_link'}))
        ways.append(Way(id=12, nodes=[a, d], tags={'highway': 'footway', 'bridge': 'yes'}))           # a foot bridge
        ways.append(Way(id=13, nodes=[a, b], tags={'highway': 'footway'}))                           # not a bridge
        ways.append(Way(id=14, nodes=[b, c], tags={'highway': 'service', 'access': 'no'}))
        ways.append(Way(id=15, nodes=[a, b, c, d, a], tags={'man_made': 'bridge', 'highway': 'pedestrian', 'area': 'yes'}))
        ways.append(Way(id=16, nodes=[a, b, a], tags={'man_made': 'bridge'}))                         # too short a ring
        ways.append(Way(id=17, nodes=[a], tags={'highway': 'tertiary'}))                              # one node
        ways.append(Way(id=18, nodes=[b, d], tags={'highway': 'cycleway', 'bridge': 'viaduct', 'indoor': 'yes'}))
        ways.append(Way(id=19, nodes=[d, a], tags={'highway': 'unclassified', 'tunnel': 'yes', 'layer': '-1'}))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tile.osm.pbf'
            with osmium.SimpleWriter(str(path)) as writer:
                for o in nodes:
                    writer.add_node(o)
                for o in ways:
                    writer.add_way(o)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            native = native_tool.read_ways([path, path], [sha, sha])
            python = fast_sources.read_ways(path, sha)
            self.assertIsNotNone(native)
            for part in native:
                for got, want in zip(part, python):
                    self.assertEqual(list(got.items()), list(want.items()))
                    for k in got:
                        if isinstance(got[k], tuple):
                            self.assertEqual(list(got[k][0].items()), list(want[k][0].items()))
            self.assertEqual(sorted(python[0]), [10, 11, 19])
            self.assertEqual(list(python[1]), [12])
            self.assertEqual(list(python[2]), [15])
            # a way with a node the tile lacks is Python's error: the native read leaves it
            ways.append(Way(id=20, nodes=[a, 999], tags={'highway': 'residential'}))
            with osmium.SimpleWriter(str(path), overwrite=True) as writer:
                for o in nodes:
                    writer.add_node(o)
                for o in ways:
                    writer.add_way(o)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertIsNone(native_tool.read_ways([path], [sha]))
            with self.assertRaises(ValueError):
                fast_sources.read_ways(path, sha)

    @unittest.skipUnless(native_tool.kernels(), 'native kernels not built (cargo build --release in rust/)')
    def test_native_crossings_are_numpy_bits(self):
        import numpy as np
        import fast_profile
        rng = np.random.default_rng(7)
        # a grid of streets and bridges over it: stations 20 m apart, segments of 2-9 stations
        counts = rng.integers(2, 10, 400)
        seg_of = np.repeat(np.arange(len(counts)), counts)
        starts = rng.uniform(-800, 800, (len(counts), 2))
        heads = rng.normal(size=(len(counts), 2))
        heads /= np.linalg.norm(heads, axis=1)[:, None]
        k = np.arange(len(seg_of)) - np.repeat(np.cumsum(counts) - counts, counts)
        pos = starts[seg_of] + heads[seg_of] * (k * 19.7)[:, None]
        pos[5] = pos[4]                                     # a zero-length edge
        same = seg_of[1:] == seg_of[:-1]
        kinds = rng.choice([0, 0, 0, 1], len(counts))
        layers = rng.choice([1., 1., 2.], len(counts))
        widths = rng.uniform(3, 30, len(counts))[seg_of]
        levels = (kinds * layers)[seg_of]
        upper = kinds[seg_of] > 0
        lower = np.ones(len(seg_of), bool)
        got = fast_profile.crossings(pos, seg_of, same, upper, lower, widths, levels)
        want = fast_profile.python_crossings(pos, seg_of, same, upper, lower, widths, levels)
        self.assertGreater(len(want[0]), 100)
        for g, w in zip(got, want):
            w = np.asarray(w, dtype=g.dtype)
            self.assertEqual(g.view(np.int64).tolist(), w.view(np.int64).tolist())

    @unittest.skipUnless(native_tool.kernels(), 'native kernels not built (cargo build --release in rust/)')
    def test_native_csr_and_close_pairs_are_numpy_bits(self):
        import numpy as np
        import fast_profile
        if not native_tool.kernels().has_solve:
            self.skipTest('an older earthng_native.dll')
        rng = np.random.default_rng(11)
        bits = lambda a: np.asarray(a).view(np.int64).tolist() if np.asarray(a).dtype == float else np.asarray(a).tolist()
        # duplicates in runs of every length numpy's pairwise sum treats apart (< 8, 8..128, > 128)
        n = 50
        rows = np.r_[rng.integers(0, n, 3000), np.full(300, 7), np.full(20, 9)]
        cols = np.r_[rng.integers(0, n, 3000), np.full(300, 3), np.full(20, 9)]
        vals = rng.normal(size=len(rows)) * 10.0 ** rng.uniform(-3, 3, len(rows))
        for got, want in zip(fast_profile.csr(rows, cols, vals, n), fast_profile.python_csr(rows, cols, vals, n)):
            self.assertEqual(bits(got), bits(want))
        counts = rng.integers(2, 10, 500)
        seg_of = np.repeat(np.arange(len(counts)), counts)
        k = np.arange(len(seg_of)) - np.repeat(np.cumsum(counts) - counts, counts)
        heads = rng.normal(size=(len(counts), 2))
        pos = rng.uniform(-600, 600, (len(counts), 2))[seg_of] + heads[seg_of] * (k * 9.3)[:, None]
        pos[5] = pos[4]
        same = seg_of[1:] == seg_of[:-1]
        width = rng.uniform(3, 30, len(counts))[seg_of]
        ground = rng.random(len(seg_of)) < .9
        got = fast_profile.close_pairs(pos, seg_of, width, ground, same)
        want = fast_profile.python_close_pairs(pos, seg_of, width, ground, same)
        self.assertGreater(len(want[0]), 100)
        for g, w in zip(got, want):
            self.assertEqual(bits(g), bits(w))

    @unittest.skipUnless(native_tool.kernels(), 'native kernels not built (cargo build --release in rust/)')
    def test_native_split_is_the_python_loop(self):
        import math
        from collections import Counter
        import numpy as np
        native = native_tool.kernels()
        if not native.has_split:
            self.skipTest('an older earthng_native.dll')

        def python_split(lens, ids, X, Y):          # _prepare's loop
            refs, out, at = Counter(ids), [], 0
            for count in lens:
                nodes = ids[at:at + count]; xy = list(zip(X[at:at + count], Y[at:at + count])); at += count
                cuts = [0] + [q for q in range(1, len(nodes) - 1) if refs[nodes[q]] > 1] + [len(nodes) - 1]
                for a, b in zip(cuts, cuts[1:]):
                    pts = [xy[a]] + [xy[q] for q in range(a + 1, b + 1)
                                     if math.hypot(xy[q][0] - xy[q-1][0], xy[q][1] - xy[q-1][1]) > 0.01]
                    if len(pts) < 2:
                        continue
                    cum = [0.]
                    for q in range(1, len(pts)):
                        cum.append(cum[-1] + math.hypot(pts[q][0] - pts[q-1][0], pts[q][1] - pts[q-1][1]))
                    if cum[-1] < .1:
                        continue
                    out.append(([[round(p[0], 3), round(p[1], 3)] for p in pts], [nodes[a], nodes[b]], cum))
            return out
        rng = np.random.default_rng(7)
        lens = rng.integers(1, 30, 2000)
        N = int(lens.sum())
        ids = rng.integers(0, N * 2 // 3, N).tolist()
        X = np.cumsum(rng.choice([0., .005, .01, .0100000001, .05, 1., 37.], N) * rng.choice([1, -1], N))
        X[rng.random(N) < .02] += .0625                      # exact ties at three decimals
        Y = np.cumsum(rng.choice([0., .003, .0625, 2.5], N)) * 10.0 ** rng.uniform(-2, 4, N)
        want = python_split(lens.tolist(), ids, X.tolist(), Y.tolist())
        way, na, nb, off, rows, xy, cum, length = native.split_roads(lens, ids, X, Y)
        self.assertGreater(len(want), 1000)
        self.assertEqual(len(na), len(want))
        for s, (pts, nodes, c) in enumerate(want):
            self.assertEqual([int(na[s]), int(nb[s])], nodes)
            self.assertEqual(np.array(pts).view(np.int64).tolist(), xy[off[s]:off[s + 1]].view(np.int64).tolist())
            self.assertEqual(np.array(c).view(np.int64).tolist(), cum[off[s]:off[s + 1]].view(np.int64).tolist())
            self.assertEqual(length[s], c[-1])

    @unittest.skipUnless(native_tool.kernels(), 'native kernels not built (cargo build --release in rust/)')
    def test_native_float_repr_is_python(self):
        import numpy as np
        native = native_tool.kernels()
        if not native.has_index:
            self.skipTest('an older earthng_native.dll')
        rng = np.random.default_rng(5)
        values = [0.0, -0.0, 1.0, 0.1, 1e16, 1e15 + .5, 1e-4, 1e-5, 5e-324, 1.7976931348623157e308, float('nan'),
                  float('inf'), -float('inf'), 9127.1505126953125, -9127.1505126953125, 2.675]
        values += (rng.standard_normal(20000) * 10.0 ** rng.uniform(-30, 30, 20000)).tolist()
        values += [float(int(m)) / 2.0 ** int(s) for m, s in zip(rng.integers(1, 1 << 52, 20000), rng.integers(8, 40, 20000))]
        for x in values:
            want = {'nan': 'NaN', 'inf': 'Infinity', '-inf': '-Infinity'}.get(repr(x), repr(x))
            self.assertEqual(native.float_repr(x), want)

    @unittest.skipUnless(native_tool.kernels(), 'native kernels not built (cargo build --release in rust/)')
    def test_native_write_index_is_python_rows(self):
        import copy
        import sqlite3
        import numpy as np
        import fast_sources
        native = native_tool.kernels()
        if not native.has_index:
            self.skipTest('an older earthng_native.dll')
        # a star of roads round node 1 (a junction), a road to a dead end, a foot segment
        ends = {2: (100., 0.), 3: (0., 100.), 4: (-70., -70.), 5: (100., 80.)}
        tags = [{'highway': 'primary', 'name': 'Вулиця "Нова"\n'}, {'highway': 'residential', 'bridge': 'yes', 'layer': '2'},
                {'highway': 'service'}, {'highway': 'track', 'width': '3,5'}]
        segments, arcs, mouths = [], [], {}
        for i, (node, (x, y)) in enumerate(((2, ends[2]), (3, ends[3]), (4, ends[4]))):
            pts = np.array([[0., 0.], [x / 2 + .123456789, y / 2 - .987654321], [x, y]])
            cum = np.r_[0., np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
            width = [7.5, 4, 3.25][i]
            segments.append({'id': i + 1, 'way': 100 + i, 'tags': tags[i], 'xy': np.round(pts, 3).tolist(), 'nodes': [1, node],
                             'width': width, 'prof': [np.round(cum, 2).tolist(), np.round(100 + cum / 50, 3).tolist()]})
            arcs.append((pts, cum))
            mouths.setdefault(1, []).append((i + 1, 0, pts[0].tolist(), None, width, cum[-1]))
            mouths.setdefault(node, []).append((i + 1, 1, pts[-1].tolist(), None, width, cum[-1]))
        pts = np.array([[100., 0.], [100., 80.]])
        segments.append({'id': 4, 'way': 103, 'tags': tags[3], 'xy': pts.tolist(), 'nodes': [2, 5], 'width': 3.5,
                         'prof': [[0., 80.], [102., 101.5]]})
        arcs.append((pts, np.array([0., 80.])))
        mouths[2].append((4, 0, [100., 0.], None, 3.5, 80.))
        mouths[5] = [(4, 1, [100., 80.], None, 3.5, 80.)]
        segments.append({'way': 7, 'tags': {'highway': 'footway', 'bridge': 'yes'}, 'width': 2.0, 'xy': [[5., 5.], [9., 9.]],
                         'nodes': ['f1', 'f2'], 'prof': [[0., 5.66], [101., 101.2]], 'id': 5})
        arcs.append((np.array([[5., 5.], [9., 9.]]), np.array([0., 5.656854249492381])))
        node_h = {1: 100.0, 2: 102.000001, 3: 102.1, 4: 101.9, 5: 101.5}
        rows = {}
        with tempfile.TemporaryDirectory() as tmp:
            for name, on in (('native', True), ('python', False)):
                native.has_index = on
                try:
                    path = Path(tmp) / f'{name}.sqlite'
                    fast_sources.write_index(copy.deepcopy(segments), arcs, copy.deepcopy(mouths), node_h, path, emit=lambda s: None)
                finally:
                    native.has_index = True
                db = sqlite3.connect(path)
                rows[name] = {t: db.execute(f'SELECT * FROM {t} ORDER BY rowid').fetchall() for t in ('features', 'nodes', 'links', 'bounds')}
                db.close()
        self.assertEqual(len(rows['python']['features']), 7)             # junctions 1 and 2, five segments
        for table in rows['python']:
            self.assertEqual(rows['native'][table], rows['python'][table], table)


def _scene_fixture(path):
    """A raw tile with what Store.build_scene reads: buildings and their parts (covered, in the
    air), retail sites with and without their surveyed node, a multipolygon relation, rings
    drawn either way round, a broken ring, lines and points."""
    from osmium.osm.mutable import Node, Relation, Way
    nodes, ways, rels = [], [], []
    ident = [100]

    def node(dx, dy, tags=None):
        ident[0] += 1
        nodes.append(Node(id=ident[0], location=(30.5 + dx * 1e-5, 50.45 + dy * 1e-5), tags=tags or {}))
        return ident[0]

    def ring(way_id, points, tags=None):
        refs = [node(x, y) for x, y in points]
        ways.append(Way(id=way_id, nodes=refs + [refs[0]], tags=tags or {}))

    ring(10, [(0, 0), (100, 0), (100, 100), (0, 100)],
         {'building': 'yes', 'height': '20', 'building:material': 'brick', 'amenity': 'place_of_worship'})
    ring(11, [(5, 5), (95, 5), (95, 95), (5, 95)], {'building:part': 'yes', 'min_height': '5'})
    ring(12, [(40, 40), (40, 60), (60, 60), (60, 40)], {'building:part': 'yes', 'min_height': '25'})
    ring(13, [(300, 0), (400, 0), (400, 80), (300, 80)], {'building': 'house'})
    ring(14, [(320, 20), (380, 20), (380, 60), (320, 60)], {'building:part': 'roof', 'building:min_level': '2'})
    ring(15, [(500, 0), (600, 0), (600, 100), (500, 100)], {'shop': 'supermarket', 'name': 'АТБ'})
    node(550, 50, {'shop': 'supermarket', 'brand': 'АТБ'})
    ring(16, [(700, 0), (800, 0), (800, 100), (700, 100)], {'shop': 'supermarket', 'name': 'Сільпо', 'building': 'retail'})
    node(900, 0, {'amenity': 'post_office', 'name': 'Нова Пошта №12'})
    ring(17, [(0, 300), (300, 300), (300, 600), (0, 600)])
    ring(18, [(100, 400), (200, 400), (200, 500), (100, 500)])
    rels.append(Relation(id=20, members=[('w', 17, 'outer'), ('w', 18, 'inner')],
                         tags={'type': 'multipolygon', 'natural': 'water', 'name': 'Озеро'}))
    ring(19, [(500, 400), (500, 600), (700, 650), (720, 380)], {'landuse': 'forest'})        # clockwise
    ring(21, [(900, 300), (1000, 400), (1000, 300), (900, 400)], {'landuse': 'grass'})       # a bow tie
    line = [node(0, 800), node(400, 820), node(800, 790)]
    ways.append(Way(id=30, nodes=line, tags={'highway': 'footway', 'surface': 'asphalt'}))
    ways.append(Way(id=31, nodes=[node(0, 900), node(900, 900)],
                    tags={'railway': 'tram', 'name': 'Трамвай', 'gauge': '1524', 'electrified': 'contact_line'}))
    ways.append(Way(id=32, nodes=[node(0, 1000), node(500, 1000)], tags={'barrier': 'fence', 'layer': '1'}))
    node(10, 700, {'highway': 'crossing', 'crossing': 'unmarked'})
    node(20, 700, {'highway': 'traffic_signals'})
    node(30, 700, {'natural': 'tree', 'leaf_type': 'broadleaved'})
    node(40, 700, {'highway': 'bus_stop', 'name': 'Зупинка "Центр"\n'})
    with osmium.SimpleWriter(str(path)) as writer:
        for o in nodes:
            writer.add_node(o)
        for o in ways:
            writer.add_way(o)
        for o in rels:
            writer.add_relation(o)


class NativeScenesTests(unittest.TestCase):
    def test_rules_fingerprint(self):
        found = native_tool.rules_fingerprint()
        self.assertEqual(found, native_tool.RULES,
                         'a function Store.build_scene runs changed: port it to rust/crates/cells (rules.rs, '
                         f'scenebuild.rs), check the scenes against Python, then set native_tool.RULES = {found!r}')

    @unittest.skipUnless(native_tool.tool() and native_tool.geos_library() and native_tool.proj_library(),
                         'native tools not built (cargo build --release in rust/), or no shapely GEOS / pyproj PROJ')
    def test_native_scene_is_the_python_bytes(self):
        import fast_sources
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _scene_fixture(tmp / 'tile.osm.pbf')
            store = fast_sources.Store.__new__(fast_sources.Store)
            store.meta = {'source': str(tmp)}
            store.frame = fast_sources.Frame.at(30.5, 50.45)
            entry = {'file': 'tile.osm.pbf'}
            want = fast_sources.write_scene(store.build_scene(entry))
            self.assertIsNone(native_tool.build_scene(store, entry, tmp / 'native.scene'))
            self.assertEqual((tmp / 'native.scene').read_bytes(), want)
            fids, kinds, tags, _ = fast_sources.read_scene(want)
            by = dict(zip(fids, zip(kinds, tags)))
            self.assertEqual(by[20][1].get('e2r_outline'), '1')             # its part covers it
            self.assertEqual(by[26][1].get('height'), '6.0')               # a part in the air
            self.assertEqual(by[22][1]['e2r_of'], '20')
            self.assertIn('grocery_site', kinds)
            self.assertIn(41, fids)                                        # the relation's water
            self.assertNotIn(42, fids)                                     # the bow tie
            with patch.dict(os.environ, {'EARTHNG_NATIVE': '0'}):
                self.assertIsNotNone(native_tool.build_scene(store, entry, tmp / 'off.scene'))
