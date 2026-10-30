"""Street furniture where it stands, low-voltage lines, building parts and domes."""
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime
from shapely.geometry import box
import fast_sources as sources
import fast_style as style
import looks

ROOT = Path(__file__).resolve().parents[1]
STREET = {'id': 'street', 'nodes': ['a', 'b'], 'width': 8, 'tags': {'highway': 'residential'},
          'points': [[0, 90, 0], [400, 90, 0]]}
POLE = 'electric_pole_wood_old_01.dae'


class PackTests(unittest.TestCase):
    def test_furniture_needs_no_experiment(self):
        saved, style.POIS = style.POIS, False
        try:
            self.assertEqual(style.point_kind({'amenity': 'bench'}), 'bench')
            self.assertEqual(style.point_kind({'amenity': 'waste_basket'}), 'waste_basket')
            self.assertEqual(style.point_kind({'barrier': 'lift_gate'}), 'lift_gate')
            self.assertEqual(style.point_kind({'barrier': 'gate'}), 'gate')
            self.assertIn('barrier', style.point_keys())
        finally:
            style.POIS = saved

    def test_only_a_streets_wires_reach_the_map(self):
        self.assertEqual(style.line_kind({'power': 'minor_line'}), 'power')
        for tags in ({'power': 'line', 'voltage': '110000'}, {'power': 'line', 'voltage': '330000'}, {'power': 'line'},
                     {'power': 'cable'}):
            with self.subTest(tags=tags):
                self.assertIsNone(style.line_kind(tags))
        for tags in ({'power': 'tower'}, {'power': 'substation'}, {'power': 'pole'}):
            with self.subTest(tags=tags):
                self.assertIsNone(style.point_kind(tags))

    def test_filters_follow_their_groups(self):
        self.assertFalse(looks.keep_scenery('bench', {'pois': False}))
        self.assertFalse(looks.keep_scenery('power', {'barriers': False}))
        self.assertTrue(looks.keep_scenery('power', {'cover': False}))


class PartTests(unittest.TestCase):
    def test_a_part_takes_its_buildings_tags_and_the_parts_replace_the_box(self):
        outline = {'building': 'church', 'building:colour': 'white', 'amenity': 'place_of_worship'}
        part = {'e2r_part': '1', 'building:part': 'yes'}
        found = {7: ('building', outline, box(0, 0, 10, 10)), 8: ('building', part, box(1, 1, 9, 9))}
        sources.link_parts(found)
        self.assertEqual(part['e2r_of'], '7')
        self.assertEqual((part['building'], part['building:colour'], part['amenity']), ('church', 'white', 'place_of_worship'))
        self.assertEqual(outline['e2r_outline'], '1')

    def test_a_small_part_leaves_the_building_standing(self):
        outline = {'building': 'yes'}
        part = {'e2r_part': '1', 'building:part': 'yes', 'building:material': 'brick'}
        sources.link_parts({7: ('building', outline, box(0, 0, 10, 10)), 8: ('building', part, box(1, 1, 3, 3))})
        self.assertNotIn('e2r_outline', outline)
        self.assertEqual(part['building:material'], 'brick')

    def test_a_shop_inside_lends_its_part_no_sign(self):
        outline = {'building': 'retail', 'amenity': 'bank'}
        part = {'e2r_part': '1', 'building:part': 'yes'}
        sources.link_parts({7: ('building', outline, box(0, 0, 10, 10)), 8: ('building', part, box(1, 1, 9, 9))})
        self.assertNotIn('amenity', part)

    def test_a_part_alone_is_a_building(self):
        part = {'e2r_part': '1', 'building:part': 'yes'}
        sources.link_parts({8: ('building', part, box(1, 1, 9, 9))})
        self.assertEqual(part['building'], 'yes')
        self.assertNotIn('e2r_of', part)

    def test_the_smallest_building_round_a_part_holds_it(self):
        big, small = {'building': 'yes'}, {'building': 'yes'}
        part = {'e2r_part': '1', 'building:part': 'yes'}
        sources.link_parts({1: ('building', big, box(0, 0, 100, 100)), 2: ('building', small, box(1, 1, 9, 9)),
                            3: ('building', part, box(2, 2, 8, 8))})
        self.assertEqual(part['e2r_of'], '2')


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

    def build(self, **cell):
        cell.setdefault('roads', [STREET])
        return self.g.build(self.table([cell]), 0, 0, self.table({'terrainStep': 100, 'maxTrees': 0}))[1]

    def corners(self, scene, material):
        out = []
        for item in scene['items'].values():
            for mesh in (item.meshes or self.lua.table()).values():
                if mesh.material == material:
                    for k in range(1, len(mesh.faces) + 1):
                        p = mesh.verts[mesh.faces[k].v + 1]
                        out.append((p.x + item.pos[1], p.y + item.pos[2], p.z + item.pos[3]))
        return out

    def items(self, scene, name):
        return [item for item in scene['items'].values() if name in str(item.shape or '')]

    @staticmethod
    def line(points, kind='power', tags=None):
        return {'id': 'l', 'kind': kind, 'points': [[x, y, 0] for x, y in points], 'tags': tags or {'power': 'minor_line'}}

    def test_furniture_stands_where_it_is_mapped(self):
        for kind, shape in (('bench', 'bench_wood'), ('waste_basket', 'bin_round')):
            with self.subTest(kind=kind):
                scene = self.build(points=[{'id': 'p', 'kind': kind, 'pos': [200, 200, 0], 'tags': {}}])
                near = [i for i in self.items(scene, shape) if abs(i.pos[1] - 200) < 1 and abs(i.pos[2] - 200) < 1]
                self.assertEqual(len(near), 1)

    def test_a_pole_on_each_node_with_its_arm_across_the_line(self):
        scene = self.build(lines=[self.line([[100, 200], [150, 200], [200, 200]])])
        poles = self.items(scene, POLE)
        self.assertEqual(sorted(round(p.pos[1]) for p in poles), [100, 150, 200])
        # the line runs along +x: the pole's y turns to +x, a quarter turn clockwise
        for pole in poles:
            self.assertAlmostEqual(abs(pole.rot[3]), .7071, places=3)
            self.assertEqual(pole.collision, 'Collision Mesh')

    def test_a_long_span_gets_poles_of_its_own(self):
        scene = self.build(lines=[self.line([[100, 200], [280, 200]])])
        xs = sorted(round(p.pos[1]) for p in self.items(scene, POLE))
        self.assertEqual(xs, [100, 145, 190, 235, 280])

    def test_no_pole_on_the_carriageway(self):
        scene = self.build(lines=[self.line([[200, 40], [200, 90], [200, 140]])])
        ys = sorted(round(p.pos[2]) for p in self.items(scene, POLE))
        self.assertEqual(ys, [40, 140])

    def test_wires_hang_between_the_poles_lowest_mid_span(self):
        scene = self.build(lines=[self.line([[100, 200], [160, 200]])])
        wire = self.corners(scene, 'e2rf_wire')
        self.assertTrue(wire)
        ends = [p[2] for p in wire if abs(p[0] - 100) < .01]
        mid = [p[2] for p in wire if abs(p[0] - 130) < .01]
        self.assertGreater(max(ends) - .01, max(mid))
        self.assertAlmostEqual(max(ends) - max(mid), .012 * 60, places=2)
        self.assertEqual({round(p[1], 1) for p in wire}, {199.3, 199.4, 200.6, 200.7})

    def test_a_wire_crossing_tiles_stays_whole(self):
        here = self.corners(self.build(lines=[self.line([[470, 200], [530, 200]])]), 'e2rf_wire')
        self.assertAlmostEqual(max(p[0] for p in here), 500, places=3)
        scene = self.g.build(self.table([{'lines': [self.line([[470, 200], [530, 200]])], 'roads': [STREET]}]), 1, 0,
                             self.table({'terrainStep': 100, 'maxTrees': 0}))[1]
        self.assertAlmostEqual(min(p[0] for p in self.corners(scene, 'e2rf_wire')), 500, places=3)

    def test_other_lines_draw_no_wires(self):
        scene = self.build(lines=[self.line([[100, 200], [160, 200]], 'path', {'highway': 'footway'})])
        self.assertEqual(self.corners(scene, 'e2rf_wire'), [])

    @staticmethod
    def building(ident='b', ring=None, height=12, **tags):
        return {'id': ident, 'height': height, 'tags': {'building': 'yes', **tags},
                'rings': [ring or [[100, 200], [120, 200], [120, 220], [100, 220]]]}

    def tops(self, scene):
        return [p[2] for p in self.corners(scene, 'e2rf_roof')]

    def test_an_outline_its_parts_replace_draws_nothing(self):
        plain = self.build(buildings=[self.building(height=12)])
        hidden = self.build(buildings=[self.building(height=12, e2r_outline='1')])
        self.assertTrue(self.corners(plain, 'e2rf_roof'))
        self.assertEqual(self.corners(hidden, 'e2rf_roof'), [])

    def test_a_lifted_part_starts_above_the_ground(self):
        part = self.building(height=30, e2r_part='1')
        part['minHeight'] = 20
        walls = [p for item in self.build(buildings=[part])['items'].values()
                 for mesh in (item.meshes or self.lua.table()).values() if mesh.material.startswith('e2rf_wall')
                 for p in [mesh.verts[mesh.faces[k].v + 1].z + item.pos[3] for k in range(1, len(mesh.faces) + 1)]]
        self.assertGreaterEqual(min(walls), 19.5)

    def test_parts_of_one_building_share_its_walls(self):
        kinds = set()
        for n in range(6):
            part = self.building(f'p{n}', height=20, e2r_part='1', e2r_of='77')
            scene = self.build(buildings=[part])
            kinds.add(tuple(sorted(m.material for i in scene['items'].values()
                                   for m in (i.meshes or self.lua.table()).values() if m.material.startswith('e2rf_wall'))))
        self.assertEqual(len(kinds), 1)

    def test_a_church_is_plaster_not_a_panel_block(self):
        scene = self.build(buildings=[self.building(height=24, building='church')])
        walls = {m.material for i in scene['items'].values() for m in (i.meshes or self.lua.table()).values() if m.material.startswith('e2rf_wall')}
        self.assertEqual(walls, {'e2rf_wall_pls_cream'})

    def test_a_dome_rises_from_the_walls(self):
        scene = self.build(buildings=[self.building(height=12, **{'roof:shape': 'dome'})])
        roofs = [p for mesh in ('e2rf_roof_metal', 'e2rf_roof_tile', 'e2rf_roof_sheet', 'e2rf_roof_mtile_red', 'e2rf_roof_mtile_brown', 'e2rf_roof_mtile_green')
                 for p in self.corners(scene, mesh)]
        self.assertTrue(roofs)
        radius = max(p[0] for p in roofs) - 110
        self.assertLess(radius, 15)
        self.assertAlmostEqual(max(p[2] for p in roofs) - min(p[2] for p in roofs), radius, delta=1)

    def test_an_onion_bulges_and_tapers(self):
        scene = self.build(buildings=[self.building(height=12, **{'roof:shape': 'onion', 'roof:colour': 'gold'})])
        gold = self.corners(scene, 'e2rf_roof_gold')
        self.assertTrue(gold)
        low = min(p[2] for p in gold)
        foot = max(p[0] for p in gold if abs(p[2] - low) < .01)
        self.assertGreater(max(p[0] for p in gold), foot + .5)     # wider above its foot
        self.assertLess(max(p[0] for p in gold if p[2] == max(q[2] for q in gold)), 110.01)

    def test_a_low_part_without_a_roof_of_its_own_stays_flat(self):
        scene = self.build(buildings=[self.building(height=6, e2r_part='1')])
        self.assertTrue(self.corners(scene, 'e2rf_roof'))


if __name__ == '__main__':
    unittest.main()
