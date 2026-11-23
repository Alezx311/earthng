"""23.11: the generator's modes (auto, extreme, screenshot), a third of the trees, a park's own
wood, lost grass built again at any speed and the dawn a landing starts at; needs lupa."""
import math
import re
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

import test_native as native_harness
from test_native import fixture, geographic

LUA = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r'


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.quality = self.lua.execute((LUA / 'quality.lua').read_text(encoding='utf8'))

    def test_the_presets_plant_a_third_of_the_crowns_they_did(self):
        q = self.quality
        self.assertEqual([q.preset(v).maxTrees for v in (0, 50, 100)], [233, 600, 800])
        self.assertEqual([q.preset(v).maxFarTrees for v in (0, 50, 100)], [40, 133, 267])
        self.assertEqual(q.preset(50).rev, q.REV)

    def test_a_tune_saved_before_is_brought_over_once(self):
        q = self.quality
        old = self.lua.table_from({'maxTrees': 1800, 'maxFarTrees': 400, 'nearM': 1000, 'detail': 50})
        new = q.migrate(old)
        self.assertEqual((new.maxTrees, new.maxFarTrees, new.nearM, new.rev), (600, 133, 1000, q.REV))
        self.assertEqual(old.maxTrees, 1800)                       # a copy: the caller's table is its own
        again = q.migrate(new)
        self.assertEqual((again.maxTrees, again.maxFarTrees), (600, 133))
        self.assertIsNone(q.migrate(None))
        # what the game then runs with keeps the mark, so the file is written back as the new kind
        self.assertEqual(q.clamp(new).rev, q.REV)

    def test_extreme_is_every_setting_at_its_top_and_the_players_own_parked_cars(self):
        q = self.quality
        own = q.preset(20)
        own.parkedCars = 16
        same = self.lua.eval('function(a, b) return rawequal(a, b) end')
        self.assertTrue(same(q.modeTune(own, 'auto'), own))
        top, most = q.modeTune(own, 'extreme'), q.preset(100, 100)
        for key in ('nearM', 'farM', 'maxGrass', 'maxRocks', 'grassM', 'rockM', 'grassBudget', 'propSpacing',
                    'maxTrees', 'maxFarTrees', 'forestSpacing', 'groundSpacing'):
            self.assertEqual(top[key], most[key], key)
        self.assertEqual(top.parkedCars, 16)
        self.assertEqual(own.nearM, q.preset(20).nearM)             # the player's own tune is not touched
        self.assertEqual(q.modeTune(own, 'screenshot').farM, most.farM)
        self.assertEqual([q.mode(v) for v in ('auto', 'extreme', 'screenshot', 'bogus', None)],
                         ['auto', 'extreme', 'screenshot', 'auto', 'auto'])


class NativeModeTests(unittest.TestCase):
    """native.lua's wanted set by the mode: a car at (2750, 5250) in a 12 km world of 500 m tiles."""

    def land(self, size=12, x=2750, y=5250):
        harness = native_harness.NativeTests()
        lua, mod, cv = harness.make(fixture(size))
        lat, lon = geographic(x, y)
        mod.land(cv(dict(seq=1, lat=lat, lon=lon)))
        self.assertEqual(harness.pump(mod).state, 'ready')
        return lua, mod, cv

    def wanted(self, mod, cv, **pose):
        mod.pose(cv(dict(x=2750, y=5250, state='driving', **pose)))
        mod.update(.016, 2)
        return mod.status().stream.wanted

    def test_auto_narrows_the_far_ring_at_speed_and_extreme_does_not(self):
        _, mod, cv = self.land()
        self.assertEqual(mod.mode(), 'auto')
        # 2 km ahead and 1000 m beside the path: outside the sleeve of a fast car
        self.assertIsNone(self.wanted(mod, cv, vx=100, vy=0)['9_12'])
        self.assertEqual(mod.setMode('extreme'), 'extreme')
        self.assertEqual(mod.status().stream.mode, 'extreme')
        self.assertGreaterEqual(self.wanted(mod, cv, vx=100, vy=0)['9_12'], 1_000_000)
        self.assertEqual(mod.setMode('nonsense'), 'auto')
        self.assertIsNone(self.wanted(mod, cv, vx=100, vy=0)['9_12'])

    def test_a_whole_tile_beside_the_road_stays_near_when_the_car_speeds_up(self):
        lua, mod, cv = self.land()
        # the landing built the tiles round the car whole (road and scene): 5_11 is one of them
        wanted = self.wanted(mod, cv, vx=100, vy=0)
        self.assertLess(wanted['5_11'], 1_000_000)
        self.assertLess(wanted['5_9'], 1_000_000)
        # a tile as far beside the road that was never built is far ground, as before
        self.assertGreaterEqual(wanted['7_11'], 1_000_000)
        self.assertGreaterEqual(wanted['7_9'], 1_000_000)
        # and one behind the car goes whatever it holds
        self.assertIsNone(self.wanted(mod, cv, vx=100, vy=0)['3_10'])

    def test_screenshot_wants_the_land_along_the_cameras_look(self):
        _, mod, cv = self.land(size=24)
        mod.setMode('screenshot')
        east = self.wanted(mod, cv, vx=0, vy=0, look=[1, 0])
        self.assertEqual(mod.status().stream.farReach, 10000)
        # 6 km and 9.7 km ahead: far tiles, whole (the far ring ends at 2.4 km here)
        self.assertGreaterEqual(east['17_10'], 1_000_000)
        self.assertLess(east['17_10'], 2_000_000)
        self.assertGreaterEqual(east['24_10'], 1_000_000)
        # past 10 km, and 6 km to the side or behind: nothing
        self.assertIsNone(east['26_10'])
        self.assertIsNone(east['5_22'])
        # 2 km ahead is near, 2 km to the side is the far ring's
        self.assertLess(east['9_10'], 1_000_000)
        self.assertGreater(east['9_10'], east['6_10'])               # after the tiles round the car
        self.assertGreaterEqual(east['5_14'], 1_000_000)
        # the sector turns with the camera
        north = self.wanted(mod, cv, vx=0, vy=0, look=[0, 1])
        self.assertIsNone(north['17_10'])
        self.assertGreaterEqual(north['5_22'], 1_000_000)
        self.assertLess(north['5_14'], 1_000_000)
        # the horizon's meshes leave the sector's own tiles alone (a quadrant is a 500 m tile)
        quadrants = 0
        for key in list(north.keys()):
            key = str(key)
            if key.startswith('h500:'):
                quadrants += 1
                self.assertIsNone(north[key[5:]], key)
            elif key.startswith('h1000:'):
                bi, bj = (int(v) for v in key[6:].split('_'))
                for i, j in ((2 * bi, 2 * bj), (2 * bi + 1, 2 * bj), (2 * bi, 2 * bj + 1), (2 * bi + 1, 2 * bj + 1)):
                    self.assertIsNone(north[f'{i}_{j}'], key)
        self.assertGreater(quadrants, 0)
        # (3.5 km north lies in the sector and in the horizon's ring: a far tile, and no quadrant)
        self.assertGreaterEqual(north['5_17'], 1_000_000)
        self.assertIsNone(north['h500:5_17'])
        # without a look, and in the other modes, the ring is the ring
        self.assertIsNone(self.wanted(mod, cv, vx=0, vy=0)['17_10'])
        mod.setMode('extreme')
        self.assertIsNone(self.wanted(mod, cv, vx=0, vy=0, look=[1, 0])['17_10'])

    def test_a_road_owed_soon_gets_six_ms_at_a_towns_pace(self):
        _, mod, cv = self.land()
        self.assertIsNone(mod.status().stream.ready['7_10'])
        # 12 m/s towards land not built yet: its road is due in 13 s (160 m), not within the 6 s
        # that were the only reason for more than the frame's 4 ms
        mod.pose(cv(dict(x=3340, y=5250, vx=12, vy=0, state='driving')))
        mod.update(.016, 4)
        self.assertAlmostEqual(mod.status().stream.wanted['7_10'], 160 / 12)
        self.assertEqual(mod.status().stream.budgetMs, 6)
        # from 15 m/s the game gives the generator 8 ms itself: what it is given stands
        _, mod, cv = self.land()
        mod.pose(cv(dict(x=3340, y=5250, vx=16, vy=0, state='driving')))
        mod.update(.016, 4)
        self.assertEqual(mod.status().stream.budgetMs, 4)

    def test_a_lost_lawn_is_built_again_at_a_towns_pace(self):
        lua, mod, cv = self.land()
        active = lua.eval('''function(native)
          local k = 1
          while true do
            local name, value = debug.getupvalue(native.update, k)
            if not name then return nil end
            if name == 'active' then return value end
            k = k + 1
          end
        end''')(mod)
        entry = active.tiles['5_10']
        self.assertIsNotNone(entry.road)
        entry.grassLost = True
        before = lua.globals().buildCalls
        # 14 m/s is over AHEAD.slow (10): the tile used to wait for a slower car. Its turn comes
        # after the far ground (it cannot be on time for a car that is on it already).
        for _ in range(900):
            mod.pose(cv(dict(x=2750, y=5250, vx=14, vy=0, state='driving')))
            mod.update(.016, 2)
        self.assertGreater(lua.globals().buildCalls, before)
        self.assertFalse(active.tiles['5_10'].grassLost)


def area(kind, rect, ident=None, tags=None):
    x0, y0, x1, y1 = rect
    return {'id': ident or kind, 'kind': kind, 'tags': tags or {}, 'rings': [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]]}


class TreeTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.generator = self.lua.execute((LUA / 'generator.lua').read_text(encoding='utf8'))

    def table(self, value):
        if isinstance(value, dict):
            return self.lua.table_from({k: self.table(v) for k, v in value.items()})
        if isinstance(value, list):
            return self.lua.table_from([self.table(v) for v in value])
        return value

    def scene(self, areas, layer=1, **options):
        cell = {'areas': areas, 'terrain': {'rect': [-500, -500, 1000, 1000], 'nx': 2, 'ny': 2, 'heights': [120] * 4}}
        options.setdefault('relief', False)
        options.setdefault('land', False)
        options.setdefault('maxTrees', 2400)                        # the cap out of the way: the lattice is read
        options.setdefault('maxGrass', 4000)
        return self.generator.build(self.table([cell]), 0, 0, self.table(options))[layer]

    @staticmethod
    def trees(scene, source=None):
        out = []
        for item in scene['items'].values():
            name = str(item.name or '')
            found = re.search(r'tree_([a-z_]+?)_-?\d+$', name)
            if item.kind == 'static' and found and (source is None or found.group(1) == source):
                out.append(item)
        return out

    @staticmethod
    def lawn(scene):
        """(x, y) -> flags of every 2 m lawn square of the scene."""
        out = {}
        for item in scene['items'].values():
            patch = item.grassPatch
            if patch:
                samples = list(patch.samples.values())
                for k in range(0, len(samples), 4):
                    slot = int(samples[k]) % 16
                    out[(round(patch.x + (slot % 4) * 2 + 1), round(patch.y + (slot // 4) * 2 + 1))] = int(samples[k]) - slot
        return out

    def test_a_wood_keeps_a_third_of_its_lattice(self):
        # 9 ha at the default 5 m step: 3600 lattice points, .8 to 1 of them a tree before
        trees = self.trees(self.scene([area('forest', (100, 100, 400, 400))]), 'forest')
        self.assertLess(len(trees), 2400)                           # the cap of this test is not reached
        self.assertAlmostEqual(len(trees) / 3240, 1 / 3, delta=.04)

    def test_the_default_cap_is_the_top_presets(self):
        scene = self.generator.build(self.table([{'areas': [area('forest', (0, 0, 500, 500))],
                                                  'terrain': {'rect': [-500, -500, 1000, 1000], 'nx': 2, 'ny': 2, 'heights': [120] * 4}}]),
                                     0, 0, self.table({'relief': False, 'land': False}))[1]
        self.assertEqual(len(self.trees(scene)), 800)

    def test_the_far_tile_plants_a_prefix_of_the_thinned_wood(self):
        near = {(round(i.pos[1], 2), round(i.pos[2], 2)) for i in self.trees(self.scene([area('forest', (0, 0, 500, 500))]))}
        far = self.scene([area('forest', (0, 0, 500, 500))], layer=2, far=True, farDecor=True, maxFarTrees=200)
        spots = {(round(i.pos[1], 2), round(i.pos[2], 2)) for i in self.trees(far)}
        self.assertEqual(len(spots), 200)
        self.assertLessEqual(spots, near)

    def test_scrub_is_not_thinned_with_the_trees(self):
        # a 12 m lattice of bushes: 1764 points, all of them a candidate as before
        self.assertGreater(len(self.trees(self.scene([area('scrub', (0, 0, 500, 500))]), 'scrub')), 1200)

    def test_a_wood_inside_a_park_is_the_parks(self):
        park = area('park', (0, 0, 500, 500), tags={'leisure': 'park'})
        wood = area('forest', (100, 100, 400, 400), tags={'natural': 'wood'})
        scene = self.scene([park, wood])
        inside = [i for i in self.trees(scene) if 100 <= i.pos[1] < 400 and 100 <= i.pos[2] < 400]
        self.assertTrue(inside)
        self.assertFalse(self.trees(scene, 'forest'))               # they are the park's trees
        # 9 ha on the park's 14 m lattice: 459 points, two thirds of them planted (chance 2, thinned)
        self.assertAlmostEqual(len(inside) / 459, 2 / 3, delta=.12)
        # a plain park keeps a sixth of its lattice (chance .5, thinned): the wood is four times it
        plain = [i for i in self.trees(self.scene([park]), 'park') if 100 <= i.pos[1] < 400 and 100 <= i.pos[2] < 400]
        self.assertGreater(len(inside), 2.5 * len(plain))
        # and a wood of its own is thicker still
        own = [i for i in self.trees(self.scene([wood])) if 100 <= i.pos[1] < 400 and 100 <= i.pos[2] < 400]
        self.assertGreater(len(own), 2.5 * len(inside))

    def test_a_parks_wood_grows_the_parks_lawn_and_a_wood_its_own_floor(self):
        park = area('park', (0, 0, 500, 500), tags={'leisure': 'park'})
        wood = area('forest', (100, 100, 400, 400), tags={'natural': 'wood'})
        spots = [(x, y) for x in range(151, 350, 20) for y in range(151, 350, 20)]
        lawn = self.lawn(self.scene([park, wood], woodFloor=True))
        got = [lawn[s] for s in spots if s in lawn]
        self.assertGreater(len(got), len(spots) * .8)
        self.assertTrue(all(flags < 512 for flags in got))          # lawn, not a wood's floor (512, 1024)
        alone = self.lawn(self.scene([wood], woodFloor=True))
        floor = [alone[s] for s in spots if s in alone]
        self.assertTrue(floor)
        self.assertTrue(all(512 <= flags < 2048 for flags in floor))

    def test_a_wood_beside_a_park_or_only_touching_it_stays_a_wood(self):
        park = area('park', (0, 0, 200, 500), tags={'leisure': 'park'})
        beside = area('forest', (200, 0, 500, 500), tags={'natural': 'wood'})
        self.assertTrue(self.trees(self.scene([park, beside]), 'forest'))
        # a third of it in the park is not enough
        across = area('forest', (100, 0, 400, 500), tags={'natural': 'wood'})
        self.assertTrue(self.trees(self.scene([park, across]), 'forest'))


class DawnTests(unittest.TestCase):
    """world.lua LIMIT.DAWN, the part that asks nothing of the game."""

    def setUp(self):
        source = (LUA / 'world.lua').read_text(encoding='utf8')
        block = re.search(r'LIMIT\.DAWN = \{.*?\n(?=-- At a landing: the level)', source, re.S).group(0)
        self.dawn = LuaRuntime(unpack_returned_tuples=True).execute('local LIMIT = {}\n' + block + '\nreturn LIMIT.DAWN')

    def sun(self, lat, lon, mo, d, time):
        """The sun's height at the game's `time` there, worked out from the clock back to the sky."""
        n = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334][mo - 1] + d
        g = 2 * math.pi * (n - 81) / 365
        dec = math.radians(23.44) * math.sin(g)
        eot = 9.87 * math.sin(2 * g) - 7.53 * math.cos(g) - 1.5 * math.sin(g)
        solar = ((time + .5) % 1) * 24 - self.dawn.zone(lat, lon, 2026, mo, d) + lon / 15 + eot / 60
        phi = math.radians(lat)
        return math.degrees(math.asin(math.sin(phi) * math.sin(dec)
                                      + math.cos(phi) * math.cos(dec) * math.cos(math.radians(15 * (solar - 12)))))

    def test_the_levels_own_hour_is_kyivs_dawn(self):
        time, sun = self.dawn.time(50.45, 30.52, 2026, 6, 40)       # the level's TimeOfDay: day 40 of June
        self.assertAlmostEqual(time, self.dawn.level, delta=.002)
        self.assertEqual(sun, self.dawn.sun)
        build = (LUA.parents[4] / 'earthng/build_mod.py').read_text(encoding='utf8')
        self.assertIn(f"'startTime': {self.dawn.level}, 'time': {self.dawn.level}", build)

    def test_the_sun_stands_low_in_the_morning_wherever_the_landing_is(self):
        for lat, lon, mo, d in ((50.45, 30.52, 6, 40), (50.45, 30.52, 12, 20), (34.05, -118.24, 6, 40), (1.35, 103.82, 3, 20),
                                (-33.87, 151.21, 1, 10), (64.15, -21.94, 6, 40), (69.65, 18.96, 6, 20), (35.68, 139.76, 10, 5)):
            time, _ = self.dawn.time(lat, lon, 2026, mo, d)
            self.assertAlmostEqual(self.sun(lat, lon, mo, d, time), self.dawn.sun, delta=.3, msg=(lat, lon, mo, d))
            self.assertGreater(time, .5, (lat, lon))                # a morning: after midnight, before noon
            self.assertGreater(self.sun(lat, lon, mo, d, time + .01), self.sun(lat, lon, mo, d, time))   # and rising

    def test_the_clock_is_the_games_zone_with_summer_time(self):
        zone = self.dawn.zone
        self.assertEqual(zone(50.45, 30.52, 2026, 7, 10), 3)        # Kyiv, EEST
        self.assertEqual(zone(50.45, 30.52, 2026, 1, 10), 2)
        self.assertEqual(zone(50.45, 30.52, 2026, 3, 28), 2)        # the last Sunday of March 2026 is the 29th
        self.assertEqual(zone(50.45, 30.52, 2026, 3, 29), 3)
        self.assertEqual(zone(34.05, -118.24, 2026, 7, 10), -7)     # Los Angeles, PDT
        self.assertEqual(zone(34.05, -118.24, 2026, 3, 7), -8)      # the second Sunday of March 2026 is the 8th
        self.assertEqual(zone(34.05, -118.24, 2026, 3, 8), -7)
        self.assertEqual(zone(-33.87, 151.21, 2026, 1, 10), 11)     # Sydney's summer
        self.assertEqual(zone(-33.87, 151.21, 2026, 7, 10), 10)
        self.assertEqual(zone(1.35, 103.82, 2026, 7, 10), 7)        # the tropics keep no summer time
        self.assertEqual(zone(50.45, 30.52, 2026, 7, 10, 5.5), 5.5)   # the level's own offset wins
        self.assertEqual(zone(50.45, 30.52, 2026, 7, 10, None, 'none'), 2)

    def test_a_polar_winter_gets_its_noon_and_a_polar_summer_its_morning(self):
        time, sun = self.dawn.time(69.65, 18.96, 2026, 12, 20)      # Tromso: the sun does not rise
        self.assertLess(sun, 0)
        self.assertLess(abs(((time + .5) % 1) * 24 - 12), 1)        # about noon by the clock
        time, sun = self.dawn.time(80, 15, 2026, 6, 20)             # Svalbard: it never goes under 9 degrees
        self.assertAlmostEqual(((time + .5) % 1) * 24 + 15 / 15 - self.dawn.zone(80, 15, 2026, 6, 20), 6, delta=.2)


if __name__ == '__main__':
    unittest.main()
