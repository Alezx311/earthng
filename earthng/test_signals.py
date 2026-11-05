"""Traffic lights that run: the groups SIGNS gives them (generator.lua) and the clock of signals.lua."""
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

import test_generator

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'mod/lua/ge/extensions/e2r/signals.lua').read_text(encoding='utf8')
J = [250, 250, 10]


def arm(ident, end, highway='residential', **tags):
    return {'id': ident, 'nodes': ['j', ident], 'width': 8, 'tags': {'highway': highway, **tags}, 'points': [J, end]}


def crossroads(highway='primary'):
    return [arm('w', [0, 250, 10], highway), arm('e', [500, 250, 10], highway),
            arm('s', [250, 0, 10], 'residential'), arm('n', [250, 500, 10], 'residential')]


class Planned(unittest.TestCase):
    def setUp(self):
        self.h = test_generator.GeneratorTests()
        self.h.setUp()

    def run_scene(self, roads, points):
        report = self.h.lua.table()
        scene = self.h.build([{'roads': roads, 'points': points}], 0, 0, terrainStep=100, maxTrees=0, maxGrass=0,
                             propSpacing=0, detailReport=report, experimentalDetail=True)[1]
        return report, scene

    def lights(self, scene):
        return [scene['lights'][k + 1] for k in range(len(scene['lights']))]

    def test_a_light_on_a_junction_stops_every_way_in(self):
        report, scene = self.run_scene(crossroads(), [{'id': 's', 'kind': 'signal', 'tags': {}, 'pos': J}])
        self.assertEqual(report.signs.signal, 4)
        self.assertEqual(sorted(q.road for q in self.lights(scene)), ['e', 'n', 's', 'w'])

    def test_a_one_way_arm_has_no_light_for_the_way_it_does_not_run(self):
        roads = crossroads()
        roads[2]['tags']['oneway'] = 'yes'     # j -> south: nobody drives in from there
        report, _ = self.run_scene(roads, [{'id': 's', 'kind': 'signal', 'tags': {}, 'pos': J}])
        self.assertEqual(report.signs.signal, 3)

    def test_a_node_short_of_a_junction_stops_who_drives_at_it(self):
        roads = crossroads()
        roads[0]['points'] = [J, [230, 250, 10], [0, 250, 10]]
        report, scene = self.run_scene(roads, [{'id': 's', 'kind': 'signal', 'tags': {}, 'pos': [230, 250, 10]}])
        self.assertEqual(report.signs.signal, 1)
        light = self.lights(scene)[0]
        self.assertGreater(light.dx, .99, 'eastwards, at the junction')

    def test_a_crossing_mid_block_stops_both_ways(self):
        road = {'id': 'r', 'nodes': ['a', 'b'], 'width': 8, 'tags': {'highway': 'residential'},
                'points': [[100, 250, 10], [250, 250, 10], [400, 250, 10]]}
        report, _ = self.run_scene([road], [{'id': 's', 'kind': 'signal', 'tags': {}, 'pos': [250, 250, 10]}])
        self.assertEqual(report.signs.signal, 2)

    def test_two_nodes_of_one_stop_line_are_one_light(self):
        roads = crossroads()
        roads[0]['points'] = [J, [230, 250, 10], [0, 250, 10]]
        report, _ = self.run_scene(roads, [{'id': 'a', 'kind': 'signal', 'tags': {}, 'pos': J},
                                           {'id': 'b', 'kind': 'signal', 'tags': {}, 'pos': [230, 250, 10]}])
        self.assertEqual(report.signs.signal, 4, 'the arm has its light from the junction node')

    def test_a_crossing_has_two_phases_and_the_opposite_ways_share_one(self):
        _, scene = self.run_scene(crossroads(), [{'id': 's', 'kind': 'signal', 'tags': {}, 'pos': J}])
        group = {q.road: q.group for q in self.lights(scene)}
        self.assertEqual(group['w'], group['e'])
        self.assertEqual(group['n'], group['s'])
        self.assertEqual(group['w'] // 2, group['n'] // 2, 'the same slot of the cycle')
        self.assertNotEqual(group['w'], group['n'])

    def test_each_lens_has_a_mesh_of_its_own_in_the_decor(self):
        _, scene = self.run_scene(crossroads(), [{'id': 's', 'kind': 'signal', 'tags': {}, 'pos': J}])
        lit = [item for item in scene['items'].values() if item.lens is not None]
        self.assertEqual(sorted({(item.lens % 2, item.colour) for item in lit}),
                         [(a, c) for a in (0, 1) for c in ('green', 'red', 'yellow')])
        self.assertTrue(all(item.decor for item in lit))

    def test_a_wide_road_has_a_head_over_its_lanes(self):
        narrow, wide = crossroads(), crossroads()
        for road in wide:
            road['width'] = 16
        count = lambda s: sum(item.triangles for item in s['items'].values() if item.lens is not None)
        self.assertGreater(count(self.run_scene(wide, [{'id': 's', 'kind': 'signal', 'tags': {}, 'pos': J}])[1]),
                           count(self.run_scene(narrow, [{'id': 's', 'kind': 'signal', 'tags': {}, 'pos': J}])[1]))


STUBS = r'''
  hidden, objects, mailbox, sent = {}, {}, {}, {}
  scenetree = {findObjectById = function(id)
    if objects[id] then return {setHidden = function(_, v) hidden[id] = v end} end end}
  be = {queueAllObjectLua = function(_, text) sent[#sent + 1] = text end,
        sendToMailbox = function(_, name, data) mailbox[#mailbox + 1] = data end}
  serialize = function(t) dict = t; return 'dict' end
  lpack = {encodeBin = function(t) return t end}
  seg = {s = {'r', 'a', 'b', '+-', 10, 3, 1, 0, 0, 0, 100, 0, 0, 200, 0, 0}}
  nodes = {e2r_na = {links = {e2r_sr_2 = {}}}, e2r_sr_2 = {links = {e2r_na = {}, e2r_nb = {}}}, e2r_nb = {links = {e2r_sr_2 = {}}}}
'''


class Clock(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(STUBS)
        self.mod = self.lua.execute(SRC)
        self.lua.globals().S = self.mod

    def test_two_axes_of_a_crossing_are_never_both_going(self):
        colour = self.mod.colour
        for group in (0, 2, 4):
            seen = set()
            for t in range(0, 240):
                a, b = colour(group, t / 2), colour(group + 1, t / 2)
                seen.add((a, b))
                self.assertIn('red', (a, b), f'{group} at {t / 2}')
            self.assertEqual(seen, {('green', 'red'), ('yellow', 'red'), ('red', 'red'), ('red', 'green'), ('red', 'yellow')})

    def test_crossings_change_at_different_times(self):
        colour = self.mod.colour
        self.assertGreater(len({colour(g, 10) for g in (0, 2, 4)}), 1)

    def test_the_lens_of_the_phase_shows_and_the_last_goes(self):
        self.lua.execute('''
          objects[1], objects[2], objects[3] = true, true, true
          S.step(0, false)
          S.addMesh(1, 0, 'green'); S.addMesh(2, 0, 'yellow'); S.addMesh(3, 0, 'red')''')
        self.assertEqual(self.lua.eval('hidden[1]'), False)
        self.assertEqual(self.lua.eval('hidden[2]'), True)
        self.assertEqual(self.lua.eval('hidden[3]'), True)
        self.lua.execute('S.step(25, false)')
        self.assertEqual((self.lua.eval('hidden[1]'), self.lua.eval('hidden[2]')), (True, False))
        self.lua.execute('S.step(28, false)')
        self.assertEqual((self.lua.eval('hidden[2]'), self.lua.eval('hidden[3]')), (True, False))

    def test_a_mesh_that_went_with_its_tile_is_forgotten(self):
        self.lua.execute('''
          objects[1] = true
          S.step(0, false)
          S.addMesh(1, 0, 'green')
          objects[1] = nil
          S.step(25, false)
          objects[1] = true
          hidden[1] = 'untouched'
          S.step(58, false)''')
        self.assertEqual(self.lua.eval('hidden[1]'), 'untouched')

    def test_a_stop_point_is_the_edge_of_the_way_it_drives(self):
        self.assertEqual(self.lua.eval("S.edge('r', seg, {x = 150, y = 2, dx = 1, dy = 0}, nodes)"), ('e2r_sr_2', 'e2r_nb'))
        self.assertEqual(self.lua.eval("S.edge('r', seg, {x = 150, y = 2, dx = -1, dy = 0}, nodes)"), ('e2r_nb', 'e2r_sr_2'))
        self.assertEqual(self.lua.eval("S.edge('r', seg, {x = 50, y = 2, dx = 1, dy = 0}, nodes)"), ('e2r_na', 'e2r_sr_2'))

    def feed(self):
        self.lua.execute('''
          S.step(0, true)
          S.addTile('t', {{road = 'r', x = 150, y = 0, z = 0, dx = 1, dy = 0, group = 0}})
          S.navgraph(nodes, {r = seg}, 150, 0, true, function(x, y, z) return {x, y, z} end)''')

    def test_the_game_gets_the_lights_of_the_graph_as_core_trafficsignals_sends_them(self):
        self.feed()
        self.assertEqual(self.lua.eval('sent[1]'), 'mapmgr.setSignals(dict)')
        self.assertEqual(self.lua.eval("dict.e2r_sr_2.e2r_nb[1].action"), 0)
        self.assertEqual(self.lua.eval("dict.e2r_sr_2.e2r_nb[1].state"), 'green')

    def test_a_change_goes_to_the_mailbox(self):
        self.feed()
        self.lua.execute('S.step(20, true); S.step(25, true)')
        self.assertEqual([self.lua.eval(f'mailbox[1][{k}]') for k in range(1, 5)], ['e2r_sr_2', 'e2r_nb', 1, 1])
        self.lua.execute('S.step(28, true)')
        self.assertEqual(self.lua.eval('mailbox[2][4]'), 2)

    def test_the_test_sees_who_waits_and_who_runs_a_red(self):
        self.feed()
        self.lua.execute('''
          S.step(0, true)
          S.step(30, true)
          tally = {}
          S.watch({{x = 140, y = 0, vx = 0, vy = 0}, {x = 150, y = 1, vx = 9, vy = 0}, {x = 150, y = 40, vx = 9, vy = 0}}, tally)''')
        self.assertEqual(self.lua.eval('tally.waiting'), 1)
        self.assertEqual(self.lua.eval('tally.ran'), 1)
        self.assertEqual(self.lua.eval('tally.lights'), 1)

    def test_no_traffic_nothing_is_sent(self):
        self.lua.execute('''
          S.step(0, false)
          S.addTile('t', {{road = 'r', x = 150, y = 0, z = 0, dx = 1, dy = 0, group = 0}})
          S.navgraph(nodes, {r = seg}, 150, 0, false, function(x, y, z) return {x, y, z} end)
          S.step(25, false)''')
        self.assertEqual((self.lua.eval('#sent'), self.lua.eval('#mailbox')), (0, 0))

    def test_a_light_a_car_may_be_stopped_at_stays_in_the_table_until_the_car_is_far(self):
        """ai.lua indexes signalsData by the edge it found: a dropped edge would stop its Lua."""
        self.feed()
        self.lua.execute('''
          S.dropTile('t')
          S.navgraph(nodes, {r = seg}, 1500, 0, true, function(x, y, z) return {x, y, z} end)''')
        self.assertTrue(self.lua.eval('dict.e2r_sr_2 ~= nil'))
        self.lua.execute('''S.navgraph(nodes, {r = seg}, 3500, 0, true, function(x, y, z) return {x, y, z} end)''')
        self.assertTrue(self.lua.eval('dict.e2r_sr_2 == nil'))


if __name__ == '__main__':
    unittest.main()
