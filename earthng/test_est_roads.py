import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import shapely

import est_roads


def section(coords, road=11114, slai=6., left: float | None = 1., right=.5, nr=1):
    props = {'tee_number': road, 'soidutee_nr': nr, 'slai': slai, 'katlai': slai + 1}
    if left is not None:
        props['plaiv'], props['plaip'] = left, right
    return {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': coords}, 'properties': props}


def rail(coords, side='VASAKUL', offset=8, road=11114, kind='1'):
    return {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': coords},
            'properties': {'tee_number': road, 'viitepunkt': offset, 'viitepunkti_suund_nvps_xv': side,
                           'piiretyyp_piiretyyp_xv': kind, 'piiretyyp_piiretyyp_val': 'w-profiil'}}


ROAD = {'highway': 'secondary', 'ref': '11114'}


class WidthTests(unittest.TestCase):
    def test_a_state_road_takes_the_register_width_and_shoulders(self):
        register = est_roads.Register({'n_katlai': [section([[0, 0], [200, 0]])]})
        along = shapely.LineString([(10, 1), (190, 1)])
        self.assertEqual(est_roads.width_tags(ROAD, along, register),
                         {'width': '7.5', 'shoulder:left:width': '1', 'shoulder:right:width': '0.5',
                          'e2r:rails': 'register'})
        # drawn against the register's direction: its left shoulder is on the way's right
        against = shapely.LineString([(190, 1), (10, 1)])
        tags = est_roads.width_tags(ROAD, against, register)
        self.assertEqual((tags['shoulder:left:width'], tags['shoulder:right:width']), ('0.5', '1'))

    def test_no_register_tags_off_the_section_on_local_roads_or_over_a_width_tag(self):
        register = est_roads.Register({'n_katlai': [section([[0, 0], [200, 0]]),
                                                    section([[0, 50], [200, 50]], road=6531063)]})
        self.assertEqual(est_roads.width_tags(ROAD, shapely.LineString([(10, 9), (190, 9)]), register), {})
        self.assertEqual(est_roads.width_tags(ROAD, shapely.LineString([(10, 50), (190, 50)]), register), {})
        self.assertEqual(est_roads.width_tags({**ROAD, 'width': '6'}, shapely.LineString([(10, 0), (190, 0)]),
                                              register), {})
        # crossing it, not along it
        self.assertEqual(est_roads.width_tags(ROAD, shapely.LineString([(100, -50), (100, 50)]), register), {})

    def test_unknown_shoulders_fall_back_to_the_class(self):
        register = est_roads.Register({'n_katlai': [section([[0, 0], [200, 0]], left=None)]})
        tags = est_roads.width_tags(ROAD, shapely.LineString([(10, 0), (190, 0)]), register)
        self.assertEqual(tags['width'], '6.5')                        # 6 m + 0.25 m a side (secondary)


class RailTests(unittest.TestCase):
    def ways(self, extra=None, tags=None):
        tags = {**ROAD, 'width': '7', **(tags or {})}
        ways = {1: (tags, shapely.LineString([(0, 0), (300, 0)]))}
        ways.update(extra or {})
        return ways

    def test_a_register_rail_stands_at_the_matched_road_edge(self):
        # 8 m left of the axis in the register; the road is 7 m wide: 3.5 + 0.5 m left of it
        register = est_roads.Register({'n_piire': [rail([[50, 8], [150, 8]])]})
        out = est_roads.rail_lines(register, self.ways())
        self.assertEqual(len(out), 1)
        line = shapely.LineString(out[0][0])
        self.assertAlmostEqual(min(c[1] for c in line.coords), 4., places=6)
        self.assertAlmostEqual(max(c[1] for c in line.coords), 4., places=6)
        self.assertAlmostEqual(line.length, 100, delta=RAIL_SLACK)
        self.assertEqual(out[0][1]['barrier'], 'guard_rail')
        # PAREMAL: right of the register's direction, which runs against the way here
        register = est_roads.Register({'n_piire': [rail([[150, 8], [50, 8]], side='PAREMAL')]})
        line = shapely.LineString(est_roads.rail_lines(register, self.ways())[0][0])
        self.assertAlmostEqual(line.coords[0][1], 4., places=6)

    def test_no_rail_on_a_bridge_a_side_road_mouth_or_an_osm_rail(self):
        register = est_roads.Register({'n_piire': [rail([[50, 8], [150, 8]])]})
        self.assertEqual(est_roads.rail_lines(register, self.ways(tags={'bridge': 'yes'})), [])
        side = {2: ({'highway': 'residential', 'width': '5'}, shapely.LineString([(100, 0), (100, 60)]))}
        parts = [shapely.LineString(c) for c, _ in est_roads.rail_lines(register, self.ways(side))]
        self.assertEqual(len(parts), 2)
        self.assertTrue(all(p.distance(shapely.Point(100, 4)) >= 2.5 for p in parts))
        mapped = [shapely.LineString([(40, 4.2), (100, 4.2)])]
        parts = [shapely.LineString(c) for c, _ in est_roads.rail_lines(register, self.ways(), mapped)]
        self.assertEqual(len(parts), 1)
        self.assertGreater(min(c[0] for c in parts[0].coords), 102)

    def test_a_rail_between_two_register_carriageways_of_one_osm_way_is_its_median(self):
        # one two-way OSM way 14 m wide; the register's carriageway 3.5 m right of it has its rail
        # 4 m to its left: 0.5 m off the way's centre, on the asphalt
        register = est_roads.Register({'n_piire': [rail([[50, .5], [150, .5]], offset=4)]})
        ways = self.ways(tags={'width': '14'})
        ways[1] = (ways[1][0], ways[1][1])
        out = est_roads.rail_lines(register, ways)
        self.assertEqual(len(out), 1)
        self.assertTrue(all(abs(c[1]) < 1e-6 for c in out[0][0]))
        # the same rail along a one-way carriageway goes to its edge
        out = est_roads.rail_lines(register, self.ways(tags={'width': '14', 'oneway': 'yes'}))
        self.assertAlmostEqual(out[0][0][0][1], 7.5, places=6)

    def test_pedestrian_fences_are_not_guard_rails(self):
        register = est_roads.Register({'n_piire': [rail([[50, 8], [150, 8]], kind='91')]})
        self.assertEqual(est_roads.rail_lines(register, self.ways()), [])


RAIL_SLACK = 2 * est_roads.RAIL_STEP


class FetchTests(unittest.TestCase):
    def test_layers_are_downloaded_once_per_box(self):
        calls = []

        class Answer(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

        def opener(request, timeout):
            calls.append(request.full_url)
            return Answer(json.dumps({'type': 'FeatureCollection', 'features': []}).encode())

        with tempfile.TemporaryDirectory() as d:
            box = [24.89, 59.35, 24.91, 59.36]
            self.assertEqual(est_roads.fetch(box, d, emit=lambda *_: None, opener=opener),
                             {'n_katlai': [], 'n_piire': []})
            est_roads.fetch(box, d, emit=lambda *_: None, opener=opener)
        self.assertEqual(len(calls), 2)
        self.assertIn('typeName=ms:n_katlai', calls[0])
        e0, n0, e1, n1 = map(int, calls[0].split('bbox=')[1].split('&')[0].split(','))
        self.assertTrue(540000 < e0 < e1 < 560000 and 6570000 < n0 < n1 < 6590000)


class EnrichTests(unittest.TestCase):
    def test_tiles_are_copied_with_register_tags_and_new_rails(self):
        import osmium
        import osmium.io
        from osmium.osm import mutable
        from pyproj import Transformer
        to = Transformer.from_crs(4326, 3301, always_xy=True)
        lonlat = Transformer.from_crs(3301, 4326, always_xy=True)
        e0, n0 = to.transform(24.90, 59.355)
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'src'
            src.mkdir()
            writer = osmium.SimpleWriter(osmium.io.File(str(src / '498_1187.osm.pbf'), 'pbf'))
            for k in range(3):
                lon, lat = lonlat.transform(e0 + 100 * k, n0)
                writer.add_node(mutable.Node(id=k + 1, location=(lon, lat), version=1))
            writer.add_way(mutable.Way(id=10, nodes=[1, 2, 3], tags=ROAD, version=1))
            writer.close()
            data = (src / '498_1187.osm.pbf').read_bytes()
            (src / 'index.json').write_text(json.dumps({'package_box': [24.85, 59.3, 24.95, 59.4], 'tiles': {
                '498_1187': {'file': '498_1187.osm.pbf', 'coverage': [24.89, 59.34, 24.96, 59.41],
                             'sha256': hashlib.sha256(data).hexdigest()}}}))
            layers = {'n_katlai': [section([[e0 - 10, n0], [e0 + 210, n0]])],
                      'n_piire': [rail([[e0 + 50, n0 + 8], [e0 + 150, n0 + 8]])]}
            out = est_roads.enrich(src, layers, emit=lambda *_: None)
            self.assertEqual(est_roads.enrich(src, layers, emit=lambda *_: None), out)   # reused
            index = json.loads((out / 'index.json').read_text())
            tile = index['tiles']['498_1187']
            path = out / tile['file']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), tile['sha256'])
            self.assertEqual(index['register']['rails'], 1)
            ways = {}

            class Reader(osmium.SimpleHandler):
                def way(self, w):
                    ways[w.id] = (dict(w.tags), [(n.lon, n.lat) for n in w.nodes])

            Reader().apply_file(str(path), locations=True)
            self.assertEqual(ways[10][0]['width'], '7.5')
            new = [w for i, w in ways.items() if i > est_roads.SYNTHETIC]
            self.assertEqual(len(new), 1)
            self.assertEqual(new[0][0]['barrier'], 'guard_rail')
            xs, ys = to.transform([p[0] for p in new[0][1]], [p[1] for p in new[0][1]])
            for y in ys:
                self.assertAlmostEqual(y - n0, 7.5 / 2 + est_roads.RAIL_OFFSET, delta=.05)
            self.assertEqual(data, (src / '498_1187.osm.pbf').read_bytes())           # source untouched


if __name__ == '__main__':
    unittest.main()
