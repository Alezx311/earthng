"""Railway and tram tracks (PACK_DATA A5): pack lines, the bed and rails, level crossings."""
import copy
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime
from shapely.geometry import LineString
import build_country as country
import country_format as binary
import fast_style as style
import looks
from test_country import Store

ROOT = Path(__file__).resolve().parents[1]
STREET = {'id': 'street', 'nodes': ['a', 'b'], 'width': 8, 'tags': {'highway': 'residential'},
          'points': [[0, 90, 0], [500, 90, 0]]}
BROAD = {'railway': 'rail', 'gauge': '1520'}


class PackTests(unittest.TestCase):
    def test_tracks_are_lines_and_tunnels_stay_off(self):
        for value in style.RAILS:
            with self.subTest(railway=value):
                self.assertEqual(style.line_kind({'railway': value}), 'rail')
        for tags in ({'railway': 'rail', 'tunnel': 'yes'}, {'railway': 'subway'}, {'railway': 'abandoned'},
                     {'railway': 'platform'}, {'railway': 'tram', 'covered': 'yes'}, {'railway': 'level_crossing'}):
            with self.subTest(tags=tags):
                self.assertIsNone(style.line_kind(tags))
        # a track on a bridge reaches the generator: it keeps the part over a road deck
        self.assertEqual(style.line_kind({'railway': 'rail', 'bridge': 'yes'}), 'rail')

    def test_a_track_keeps_only_the_tags_the_generator_reads(self):
        tags = {'railway': 'rail', 'gauge': '1520', 'electrified': 'contact_line', 'voltage': '3000',
                'name': 'Київ — Фастів', 'operator': 'Укрзалізниця', 'usage': 'main', 'bridge': 'yes'}
        self.assertEqual(style.rail_tags(tags), {'railway': 'rail', 'gauge': '1520', 'electrified': 'contact_line',
                                                 'usage': 'main', 'bridge': 'yes'})

    def test_tracks_stay_whatever_the_layers(self):
        self.assertTrue(looks.keep_scenery('rail', {'cover': False, 'barriers': False, 'pois': False}))

    def test_a_station_ground_stays_paved_in_the_pack(self):
        # an older runtime keeps a yard free of trees; this one draws it in ballast (RAIL.cover)
        self.assertEqual(style.ground_kind({'landuse': 'railway'}), 'paved')

    def test_materials(self):
        track = style.MATERIALS['e2rf_track']
        self.assertTrue(track['alphaTest'])
        self.assertTrue(track['Stages'][0]['opacityMap'].endswith('/real/track_o.data.dds'))
        self.assertEqual(style.MATERIALS['e2rf_ballast']['groundType'], 'GRAVEL')
        for kind in ('rail', 'rail_side'):
            self.assertIn('diffuseColor', style.MATERIALS['e2rf_' + kind]['Stages'][0])

    def test_a_long_track_is_cut_to_the_padded_cell_and_survives_the_format(self):
        store = Store()
        line = (-5, 'rail', {'tags': dict(BROAD)}, LineString([(-3000, 500), (4000, 500)]))
        store.scenery = lambda rect: [line]
        cell = country.compile_cell(store, [0, 0, 1000, 1000])
        rails = [f for f in cell['lines'] if f['kind'] == 'rail']
        self.assertEqual(len(rails), 1)
        xs = [p[0] for p in rails[0]['points']]
        self.assertEqual((min(xs), max(xs)), (-100, 1100))
        back = binary.decode_cell(binary.encode_cell(copy.deepcopy(cell), (0, 0)), (0, 0), [0, 0, 1000, 1000])
        self.assertEqual([f['tags'] for f in back['lines'] if f['kind'] == 'rail'], [BROAD])


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.g = self.lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8'))

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def build(self, i=0, **cell):
        cell.setdefault('roads', [STREET])
        return self.g.build(self.table([cell]), i, 0, self.table({"terrainStep": 100, "maxTrees": 0}))[:2]

    @staticmethod
    def track(points, tags=None, ident='t'):
        return {'id': ident, 'kind': 'rail', 'points': [[x, y, 0] for x, y in points], 'tags': tags or dict(BROAD)}

    def corners(self, layers, material):
        out = []
        for layer in layers:
            for item in layer['items'].values():
                for mesh in (item.meshes or self.lua.table()).values():
                    if mesh.material == material:
                        for k in range(1, len(mesh.faces) + 1):
                            p = mesh.verts[mesh.faces[k].v + 1]
                            out.append((p.x + item.pos[1], p.y + item.pos[2], p.z + item.pos[3]))
        return out

    def test_open_track_is_a_bed_and_two_rails_a_gauge_apart(self):
        layers = self.build(lines=[self.track([[50, 300], [450, 300]])])
        bed, rails, sides = (self.corners(layers, 'e2rf_' + k) for k in ('track', 'rail', 'rail_side'))
        self.assertTrue(bed and rails and sides)
        # the bed: 1.52 m gauge + 1.25 m each side, a few cm over the ground
        self.assertAlmostEqual(min(p[1] for p in bed), 300 - 2.01, places=3)
        self.assertAlmostEqual(max(p[1] for p in bed), 300 + 2.01, places=3)
        heads = sorted({round(p[1], 3) for p in rails})
        self.assertEqual(heads, [299.168, 299.24, 300.76, 300.832])     # inner faces 1.52 m apart
        bed_z = max(p[2] for p in bed)
        self.assertAlmostEqual(max(p[2] for p in rails) - bed_z, .15, delta=.02)
        self.assertAlmostEqual(min(p[2] for p in sides), min(p[2] for p in bed), delta=.02)

    def test_a_standard_gauge_track_outside_the_former_union(self):
        layers = self.build(lines=[self.track([[50, 300], [450, 300]], {'railway': 'rail'})])
        heads = sorted({round(p[1], 3) for p in self.corners(layers, 'e2rf_rail')})
        self.assertAlmostEqual(heads[2] - heads[1], 1.435, places=2)

    def test_a_level_crossing_lays_the_rails_flush_with_the_carriageway(self):
        layers = self.build(lines=[self.track([[200, 20], [200, 160]])])
        road = max(p[2] for p in self.corners(layers, 'e2rf_road') if abs(p[1] - 90) < 4.01)
        on = [p for p in self.corners(layers, 'e2rf_rail') if abs(p[1] - 90) < 3.8]
        self.assertTrue(on)
        for p in on:
            self.assertAlmostEqual(p[2], road + .012, places=3)
        # no bed and no rail sides on the asphalt; the bed comes back past the curb
        self.assertFalse([p for p in self.corners(layers, 'e2rf_track') if abs(p[1] - 90) < 3.9])
        self.assertFalse([p for p in self.corners(layers, 'e2rf_rail_side') if abs(p[1] - 90) < 3.85])
        bed = self.corners(layers, 'e2rf_track')
        self.assertTrue([p for p in bed if 90 + 4 < p[1] < 90 + 6])
        self.assertTrue([p for p in bed if 90 - 6 < p[1] < 90 - 4])

    def test_a_crossing_is_cut_finely_and_open_track_coarsely(self):
        layers = self.build(lines=[self.track([[200, 20], [200, 300]])])
        knots = sorted({round(p[1], 3) for p in self.corners(layers, 'e2rf_rail') if abs(p[0] - 200.832) < 1e-3})
        near = [y for y in knots if abs(y - 90) < 8]
        far = [y for y in knots if y > 200]
        self.assertLessEqual(max(b - a for a, b in zip(near, near[1:])), 1.0 + 1e-6)
        self.assertGreater(min(b - a for a, b in zip(far, far[1:])), 4)

    def test_a_tram_in_the_street_is_only_its_rail_heads(self):
        layers = self.build(lines=[self.track([[100, 90.6], [400, 90.6]], {'railway': 'tram', 'gauge': '1524'})])
        self.assertTrue(self.corners(layers, 'e2rf_rail'))
        self.assertFalse(self.corners(layers, 'e2rf_track'))
        self.assertFalse(self.corners(layers, 'e2rf_rail_side'))

    def test_a_bridge_over_no_deck_draws_nothing(self):
        layers = self.build(lines=[self.track([[50, 300], [450, 300]], {'railway': 'rail', 'bridge': 'yes'})])
        self.assertFalse(self.corners(layers, 'e2rf_rail'))
        self.assertFalse(self.corners(layers, 'e2rf_track'))

    def test_a_kilometre_of_open_track_stays_cheap(self):
        layers = self.build(lines=[self.track([[0, 300], [500, 300]])])
        tris = sum(len(self.corners(layers, 'e2rf_' + k)) // 3 for k in ('track', 'rail', 'rail_side'))
        # 8 m knots: a bed quad and two rails of three quads, 14 triangles: ~1.75 k a kilometre
        self.assertLess(tris * 2, 1900)

    def test_a_siding_has_rail_sides_only_near_a_road(self):
        far = self.build(lines=[self.track([[50, 300], [450, 300]], {**BROAD, 'service': 'siding'})])
        self.assertTrue(self.corners(far, 'e2rf_rail'))
        self.assertFalse(self.corners(far, 'e2rf_rail_side'))
        near = self.build(lines=[self.track([[50, 110], [450, 110]], {**BROAD, 'service': 'siding'})])
        self.assertTrue(self.corners(near, 'e2rf_rail_side'))

    def test_two_tiles_meet_on_the_same_edge(self):
        line = self.track([[300, 300], [555, 340], [700, 345]])
        left = self.build(0, lines=[line])
        right = self.build(1, lines=[line])

        def edge(layers, material):
            return sorted((round(p[1], 3), round(p[2], 3)) for p in self.corners(layers, material) if abs(p[0] - 500) < 1e-6)
        for material in ('e2rf_track', 'e2rf_rail'):
            with self.subTest(material=material):
                self.assertTrue(edge(left, material))
                self.assertEqual(set(edge(left, material)), set(edge(right, material)))

    def test_side_by_side_beds_never_share_a_height(self):
        layers = self.build(lines=[self.track([[50, 300], [450, 300]], ident=f't{n}') for n in range(2)])
        heights = {round(p[2], 4) for p in self.corners(layers, 'e2rf_track')}
        self.assertGreater(len(heights), 1)

    def test_a_station_ground_is_ballast(self):
        ring = [[100, 200], [400, 200], [400, 450], [100, 450], [100, 200]]
        yard = {'id': 'y', 'kind': 'paved', 'tags': {'landuse': 'railway'}, 'rings': [ring]}
        layers = self.build(areas=[yard])
        self.assertTrue(self.corners(layers, 'e2rf_ballast'))
        self.assertFalse(self.corners(layers, 'e2rf_paved'))
        parking = {'id': 'p', 'kind': 'paved', 'tags': {'amenity': 'parking'}, 'rings': [ring]}
        layers = self.build(areas=[parking])
        self.assertTrue(self.corners(layers, 'e2rf_paved'))
        self.assertFalse(self.corners(layers, 'e2rf_ballast'))

    def test_tracks_make_no_collision(self):
        collision = self.lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/collision.lua').read_text(encoding='utf8'))
        for kind in ('track', 'rail', 'rail_side', 'ballast'):
            self.assertTrue(collision.QUIET.scene['e2rf_' + kind])


if __name__ == '__main__':
    unittest.main()
