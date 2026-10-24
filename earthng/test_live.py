"""Offline checks for the in-game live window. The compiler runs in Lua.

No Overpass call, no network, and no BeamNG. Run with:
python -m unittest discover -s earthng -p test_live.py
"""
from pathlib import Path
import math
import unittest

ROOT = Path(__file__).resolve().parents[1]
from lupa.luajit21 import LuaRuntime


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    coordinates = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/coordinates.lua').read_text(encoding='utf-8'))
    lua.globals().coordinates = coordinates
    lua.execute("""
      require = function(name)
        if name == 'ge/extensions/e2r/coordinates' then return coordinates end
        error('unexpected require ' .. tostring(name))
      end
    """)
    live = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/live.lua').read_text(encoding='utf-8'))
    return lua, coordinates, live


def to_lua(lua, value):
    if isinstance(value, dict):
        return lua.table_from({k: to_lua(lua, v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return lua.table_from([to_lua(lua, v) for v in value])
    return value


def as_list(proxy):
    out = []
    i = 1
    while True:
        item = proxy[i]
        if item is None:
            return out
        out.append(item)
        i += 1


def by_id(items, identity):
    for item in items:
        if item.id == identity:
            return item
    raise AssertionError(identity)


def nearest(points, x, y):
    best, dist = None, 1e18
    for p in points:
        d = (p[1] - x) ** 2 + (p[2] - y) ** 2
        if d < dist:
            best, dist = p, d
    return best


def project(lon, lat):
    return lon * 100.0, lat * 100.0


class LiveWindowTests(unittest.TestCase):
    def setUp(self):
        self.lua, self.coordinates, self.live = runtime()

    def test_landing_cells_grow_in_steps(self):
        ids = [(pair[1], pair[2]) for pair in as_list(self.live.cellIds(1200))]
        self.assertEqual(sorted(ids), [(-1, -1), (-1, 0), (0, -1), (0, 0)])
        self.assertEqual(self.live.wantedRadius(0, 0), 1200)
        self.assertEqual(self.live.wantedRadius(0, 1200), 4200)
        self.assertEqual(self.live.wantedRadius(0, 4200), 4500)
        self.assertEqual(self.live.wantedRadius(0, 4500), 4500)
        self.assertEqual(self.live.wantedRadius(8000, 4500), 7500)
        self.assertEqual(self.live.wantedRadius(20000, 9000), 12000)
        self.assertEqual(self.live.wantedRadius(20000, 12000), 12000)

    def test_look_boxes(self):
        self.assertEqual(self.live.lookFor(50.45, 30.52), 'postsoviet')
        self.assertEqual(self.live.lookFor(50, 14), 'western')
        self.assertEqual(self.live.lookFor(0, 0), 'general')

    def test_the_frame_stays_on_the_pin(self):
        spec = self.live.frameSpec(50.4501, 30.5234)
        self.assertEqual(spec.crs, 'EPSG:32636')
        frame = self.coordinates.frame(spec)
        x, y = frame.localPoint(50.4501, 30.5234)
        self.assertLess(abs(x), 1)
        self.assertLess(abs(y), 1)
        again = self.live.frameSpec(50.4501, 30.5234)
        self.assertEqual(again.origin[1], spec.origin[1])
        self.assertEqual(again.origin[2], spec.origin[2])

    def test_terrarium_height_and_tile(self):
        self.assertAlmostEqual(self.live.terrarium(128, 0, 0), 0, places=6)
        self.assertAlmostEqual(self.live.terrarium(128, 10, 0), 10, places=6)

        def tile(lat, lon):
            n = 4096
            x = math.floor((lon + 180) / 360 * n)
            t = math.tan(math.radians(lat))
            y = math.floor((1 - math.log(t + math.sqrt(t * t + 1)) / math.pi) / 2 * n)
            return x, y

        for lat, lon in ((50.45, 30.52), (40.71, -74.01), (-33.87, 151.21)):
            self.assertEqual(self.live.tileXY(lat, lon), tile(lat, lon))

    def test_a_published_cell_is_not_rewritten(self):
        live = self.live
        self.assertIsNotNone(live.begin(50.45, 30.52))
        live.put(to_lua(self.lua, {'0_0': {'marker': 'a'}}))
        live.put(to_lua(self.lua, {'0_0': {'marker': 'b'}, '1_0': {'marker': 'c'}}))
        self.assertEqual(live.cell(0, 0).marker, 'a')
        self.assertEqual(live.cell(1, 0).marker, 'c')
        self.assertIsNone(live.sync())
        live.put(to_lua(self.lua, {
            '-1_-1': {'marker': 'land'}, '-1_0': {'marker': 'land'}, '0_-1': {'marker': 'land'},
        }))
        region = live.sync()
        self.assertEqual(region.country.id, 'live')
        self.assertEqual(region.descriptor.id, 'here')
        self.assertEqual(region.data.blockCells, 1)
        self.assertTrue(region.data.blocks['0_0'].memory)
        self.assertEqual(region.data.blocks['0_0'].mask, '1000000000000000')
        self.assertEqual(region.data.look.block, 'postsoviet')
        serial = region.serial
        self.assertTrue(live.put(to_lua(self.lua, {'2_0': {'marker': 'd'}})))
        self.assertTrue(live.absorb(region))
        self.assertGreater(region.serial, serial)
        self.assertTrue(region.data.blocks['2_0'].memory)
        self.assertFalse(live.absorb(region))

    def test_request_does_not_download_without_the_game_scheduler(self):
        self.assertFalse(self.live.request(50.45, 30.52))
        self.assertIn('планувальника', self.live.status().message_uk)

    def test_the_downloader_does_not_declare_a_c_function(self):
        src = (ROOT / 'mod/lua/ge/extensions/e2r/live.lua').read_text(encoding='utf-8')
        self.assertNotIn('ffi.cdef', src)
        self.assertNotIn('ffi.load', src)
        self.assertNotIn('WinHttp', src)
        self.assertNotIn('SecureComm', src)
        self.assertIn("require, 'socket.http'", src)
        self.assertIn("require, 'ltn12'", src)
        self.assertIn('overpass.osm.ch', src)
        self.assertIn('open-meteo.com', src)

    def test_overpass_html_is_refused(self):
        elements, err = self.live.parseOverpass('<html>no</html>')
        self.assertIsNone(elements)
        self.assertIn('refused', err)

    def test_osm_features_follow_the_generator(self):
        elements = [
            {'type': 'node', 'id': 1, 'lon': 0.10, 'lat': 0.10},
            {'type': 'node', 'id': 2, 'lon': 0.12, 'lat': 0.10},
            {'type': 'node', 'id': 3, 'lon': 0.12, 'lat': 0.12},
            {'type': 'node', 'id': 4, 'lon': 0.10, 'lat': 0.12},
            {'type': 'node', 'id': 5, 'lon': 0.30, 'lat': 0.10},
            {'type': 'node', 'id': 6, 'lon': 0.32, 'lat': 0.10},
            {'type': 'node', 'id': 7, 'lon': 0.32, 'lat': 0.12},
            {'type': 'node', 'id': 8, 'lon': 0.30, 'lat': 0.12},
            {'type': 'node', 'id': 9, 'lon': 0.50, 'lat': 0.10},
            {'type': 'node', 'id': 10, 'lon': 0.56, 'lat': 0.10},
            {'type': 'node', 'id': 11, 'lon': 0.56, 'lat': 0.16},
            {'type': 'node', 'id': 12, 'lon': 0.50, 'lat': 0.16},
            {'type': 'node', 'id': 13, 'lon': 0.10, 'lat': 0.40},
            {'type': 'node', 'id': 14, 'lon': 0.20, 'lat': 0.40},
            {'type': 'node', 'id': 15, 'lon': 0.10, 'lat': 0.60},
            {'type': 'node', 'id': 16, 'lon': 0.20, 'lat': 0.60},
            {'type': 'node', 'id': 17, 'lon': 0.40, 'lat': 0.40, 'tags': {'highway': 'bus_stop'}},
            {'type': 'node', 'id': 18, 'lon': 0.45, 'lat': 0.40, 'tags': {'highway': 'traffic_signals'}},
            {'type': 'node', 'id': 19, 'lon': 0.48, 'lat': 0.40,
             'tags': {'highway': 'crossing', 'crossing': 'unmarked'}},
            {'type': 'way', 'id': 100, 'nodes': [1, 2, 3, 4, 1], 'tags': {'building': 'house'}},
            {'type': 'way', 'id': 101, 'nodes': [5, 6, 7, 8, 5],
             'tags': {'building': 'apartments', 'building:levels': '5'}},
            {'type': 'way', 'id': 102, 'nodes': [9, 10, 11, 12, 9], 'tags': {'leisure': 'park'}},
            {'type': 'way', 'id': 103, 'nodes': [13, 14], 'tags': {'highway': 'footway'}},
            {'type': 'way', 'id': 104, 'nodes': [15, 16], 'tags': {'highway': 'residential'}},
            {'type': 'way', 'id': 105, 'nodes': [13, 15], 'tags': {'barrier': 'fence'}},
            {'type': 'way', 'id': 106, 'nodes': [1, 2, 3, 4, 1],
             'tags': {'highway': 'pedestrian', 'area': 'yes'}},
            {'type': 'way', 'id': 107, 'nodes': [15, 16], 'tags': {'highway': 'track'}},
        ]
        cells = self.live.compile(
            to_lua(self.lua, elements), project, lambda x, y: 10, to_lua(self.lua, [[0, 0]]), None)
        cell = cells['0_0']
        roads = as_list(cell.roads)
        self.assertEqual([road.id for road in roads], ['w104'])
        self.assertAlmostEqual(roads[0].width, 5.5, places=2)
        house = by_id(as_list(cell.buildings), 'b100')
        self.assertEqual(house.kind, 'house')
        self.assertIsNone(house.height)
        apartments = by_id(as_list(cell.buildings), 'b101')
        self.assertAlmostEqual(apartments.height, 15, places=2)
        self.assertEqual(by_id(as_list(cell.areas), 'a102').kind, 'park')
        lines = {line.id: line.kind for line in as_list(cell.lines)}
        self.assertEqual(lines['l103'], 'path')
        self.assertEqual(lines['l105'], 'fence')
        self.assertEqual(lines['l107'], 'path')
        points = as_list(cell.points)
        self.assertEqual([point.kind for point in points], ['stop'])
        blob = ' '.join(item.kind for item in as_list(cell.buildings) + as_list(cell.areas)
                        + as_list(cell.lines) + points)
        self.assertNotIn('sign_', blob)

    def _bridge(self, elements, sample):
        cells = self.live.compile(
            to_lua(self.lua, elements), project, sample, to_lua(self.lua, [[0, 0], [-1, 0]]), None)
        roads = as_list(cells['0_0'].roads)
        return {road.id: road for road in roads}

    def test_a_flat_bridge_clears_and_a_valley_stays_at_the_banks(self):
        flat = self._bridge([
            {'type': 'node', 'id': 1, 'lon': -0.8, 'lat': 0},
            {'type': 'node', 'id': 2, 'lon': 0.8, 'lat': 0},
            {'type': 'way', 'id': 1, 'nodes': [1, 2], 'tags': {'highway': 'primary', 'bridge': 'yes'}},
        ], lambda x, y: 10)
        road = flat['w1']
        points = as_list(road.points)
        self.assertAlmostEqual(nearest(points, -80, 0)[3], 30, places=2)
        self.assertGreaterEqual(nearest(points, 0, 0)[3], 36.5)

        valley = self._bridge([
            {'type': 'node', 'id': 1, 'lon': -0.8, 'lat': 0},
            {'type': 'node', 'id': 2, 'lon': 0.8, 'lat': 0},
            {'type': 'way', 'id': 1, 'nodes': [1, 2], 'tags': {'highway': 'primary', 'bridge': 'yes'}},
        ], lambda x, y: 20 if abs(x) >= 40 else 0)
        mid = nearest(as_list(valley['w1'].points), 0, 0)
        self.assertGreater(mid[3], 39)
        self.assertLess(mid[3], 41)

    def test_clearance_lifts_only_the_bridge_interior(self):
        def sample(x, y):
            return 0 if abs(y) < 0.5 else 40

        roads = self._bridge([
            {'type': 'node', 'id': 1, 'lon': -0.8, 'lat': 0},
            {'type': 'node', 'id': 2, 'lon': 0.8, 'lat': 0},
            {'type': 'node', 'id': 3, 'lon': -0.15, 'lat': 0.02},
            {'type': 'node', 'id': 4, 'lon': 0.15, 'lat': 0.02},
            {'type': 'way', 'id': 1, 'nodes': [1, 2], 'tags': {'highway': 'primary', 'bridge': 'yes'}},
            {'type': 'way', 'id': 2, 'nodes': [3, 4], 'tags': {'highway': 'residential'}},
        ], sample)
        bridge = as_list(roads['w1'].points)
        under = as_list(roads['w2'].points)
        self.assertAlmostEqual(nearest(bridge, -80, 0)[3], 20, places=2)
        self.assertGreaterEqual(nearest(bridge, 0, 0)[3], 65)
        self.assertAlmostEqual(nearest(under, 0, 2)[3], 60, places=2)

    def test_a_tunnel_drops_its_interior_and_a_passage_stays_on_the_ground(self):
        elements = [
            {'type': 'node', 'id': 1, 'lon': -0.8, 'lat': 0.1},
            {'type': 'node', 'id': 2, 'lon': 0.8, 'lat': 0.1},
            {'type': 'node', 'id': 3, 'lon': -0.8, 'lat': 0.3},
            {'type': 'node', 'id': 4, 'lon': 0.8, 'lat': 0.3},
            {'type': 'way', 'id': 1, 'nodes': [1, 2],
             'tags': {'highway': 'primary', 'tunnel': 'yes'}},
            {'type': 'way', 'id': 2, 'nodes': [3, 4],
             'tags': {'highway': 'service', 'tunnel': 'building_passage'}},
        ]
        roads = self._bridge(elements, lambda x, y: 10)
        tunnel = as_list(roads['w1'].points)
        passage = as_list(roads['w2'].points)
        self.assertAlmostEqual(nearest(tunnel, -80, 10)[3], 30, places=2)
        self.assertAlmostEqual(nearest(tunnel, 0, 10)[3], 23, places=2)
        self.assertAlmostEqual(nearest(passage, 0, 30)[3], 30, places=2)


if __name__ == '__main__':
    unittest.main()
