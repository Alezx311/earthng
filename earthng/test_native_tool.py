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
