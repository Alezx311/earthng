"""The water's look by the weather (waterfx.lua): wind, rain, cloud and night change its fields."""
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

LUA = Path(__file__).resolve().parents[1] / 'mod/lua'


class WaterFxTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path = '{LUA.as_posix()}/?.lua;' .. package.path")
        self.fx = self.lua.eval("require('ge/extensions/e2r/waterfx')")

    def look(self, kind, **weather):
        w = {'wind': .3, 'rain': 0, 'cloud': .1, 'night': 0, 'cold': 0, **weather}
        rows = self.fx.look(kind, self.lua.table_from(w))
        out = {}
        for k in range(1, len(rows) + 1):
            name, index, value = rows[k][1], rows[k][2], rows[k][3]
            out[(name, index)] = value
        return out

    @staticmethod
    def f(look, name, index=0):
        return float(look[(name, index)])

    def test_wind_raises_waves_ripples_and_foam(self):
        for kind in ('sea', 'lake', 'pond', 'river'):
            with self.subTest(kind=kind):
                calm, breeze, storm = (self.look(kind, wind=w) for w in (0, .3, 1))
                for field in ('overallWaveMagnitude', 'overallRippleMagnitude', 'overallFoamOpacity'):
                    self.assertLess(self.f(calm, field), self.f(breeze, field), field)
                    self.assertLess(self.f(breeze, field), self.f(storm, field), field)
                self.assertGreater(abs(self.f(storm, 'rippleSpeed')), abs(self.f(calm, 'rippleSpeed')))
                self.assertLess(self.f(storm, 'specularPower'), self.f(calm, 'specularPower'))
        # the sea is rougher than a lake, a lake than a river, in the same wind
        waves = [self.f(self.look(kind, wind=.8), 'overallWaveMagnitude') for kind in ('sea', 'lake', 'river')]
        self.assertEqual(waves, sorted(waves, reverse=True))

    def test_rain_pocks_the_water_and_takes_its_mirror(self):
        dry, wet = self.look('lake'), self.look('lake', rain=.8)
        self.assertGreater(self.f(wet, 'overallRippleMagnitude'), self.f(dry, 'overallRippleMagnitude') + .2)
        self.assertLess(self.f(wet, 'reflectivity'), self.f(dry, 'reflectivity'))
        self.assertLess(self.f(wet, 'specularPower'), self.f(dry, 'specularPower') * .7)
        self.assertGreater(self.f(wet, 'waterFogDensity'), self.f(dry, 'waterFogDensity'))
        # finer ripples: a smaller texture scale
        self.assertLess(float(wet[('rippleTexScale', 0)].split()[0]), float(dry[('rippleTexScale', 0)].split()[0]))

    def test_cloud_and_night_darken_and_grey_the_water(self):
        def rgb(look):
            return [int(v) for v in look[('baseColor', 0)].split()[:3]]
        clear, cloudy, night = rgb(self.look('lake')), rgb(self.look('lake', cloud=1)), rgb(self.look('lake', night=1))
        self.assertLess(sum(cloudy), sum(clear))
        self.assertLess(sum(night), sum(clear) * .6)
        self.assertLess(max(cloudy) - min(cloudy), max(clear) - min(clear))
        self.assertEqual(self.look('lake')[('baseColor', 0)].split()[3], '255')

    def test_a_fair_day_keeps_the_look_the_water_had(self):
        """The fields at the default weather stay near what world.lua set before the weather."""
        lake, river, sea, pond = (self.look(k) for k in ('lake', 'river', 'sea', 'pond'))
        self.assertAlmostEqual(self.f(lake, 'overallWaveMagnitude'), .08, delta=.03)
        self.assertAlmostEqual(self.f(lake, 'overallRippleMagnitude'), .28, delta=.05)
        self.assertAlmostEqual(self.f(river, 'overallRippleMagnitude'), .35, delta=.05)
        self.assertAlmostEqual(self.f(sea, 'reflectivity'), .28, delta=.02)
        self.assertAlmostEqual(self.f(lake, 'waterFogDensity'), .9, delta=.1)
        self.assertAlmostEqual(self.f(pond, 'waterFogDensity'), 1.5, delta=.1)
        self.assertAlmostEqual(self.f(river, 'depthGradientMax'), 6)

    def weather(self, state, **pack):
        return self.fx.weather(self.lua.table_from(state), self.lua.table_from(pack))

    def test_the_weather_is_read_from_the_games_environment(self):
        fair = self.weather({'windSpeed': 2, 'cloudCover': .2, 'numOfDrops': 0, 'time': 0})
        self.assertEqual(fair.rain, 0)
        self.assertEqual(fair.night, 0)
        self.assertAlmostEqual(fair.wind, .25)
        rain = self.weather({'windSpeed': 1, 'cloudCover': .1, 'numOfDrops': 3000, 'time': 0})
        self.assertGreater(rain.rain, .8)
        self.assertGreater(rain.cloud, .8, 'rain falls from a covered sky')
        self.assertGreater(rain.wind, .4)
        self.assertEqual(self.weather({'time': .5}).night, 1)
        self.assertEqual(self.weather({'time': .2}).night, 0)
        # the pack's snow round the camera is counted as drops by the game: it is not rain
        snow = self.weather({'numOfDrops': 3000, 'time': 0}, snow=True)
        self.assertEqual(snow.rain, 0)
        self.assertEqual(snow.cold, 1)
        self.assertEqual(self.weather({'time': 0}, rain=True).rain, .7)
        # no environment at all: a fair day
        none = self.fx.weather(None, None)
        self.assertEqual((none.wind, none.rain), (.3, 0))

    def test_tracked_water_takes_a_new_weather_a_few_objects_a_frame(self):
        run = self.lua.eval('''function(fx)
          local objs, sets = {}, {}
          local function make(id)
            local o = {id = id}
            function o:setField(name, index, value) sets[#sets + 1] = {id, name, value} end
            function o:getID() return id end
            objs[id] = o
            return o
          end
          for id = 1, 10 do
            local o, kind = make(id), id % 2 == 0 and 'lake' or 'river'
            fx.dress(o, kind)
            fx.track(o, kind)
          end
          -- an object that is not registered yet has no id: it is not followed
          fx.track(make(0), 'lake')
          local first = #sets
          local state = {windSpeed = 1, cloudCover = .1, numOfDrops = 0, time = 0}
          local function read() return state, {} end
          local function find(id) return objs[id] end
          sets = {}
          local frames = {}
          frames[1] = fx.step(0, read, find, 4)
          frames[2] = fx.step(.1, read, find, 4)
          frames[3] = fx.step(.2, read, find, 4)
          frames[4] = fx.step(.3, read, find, 4)
          -- the same weather a second later: nothing to do
          frames[5] = fx.step(1.5, read, find, 4)
          -- a storm comes in, and three tiles have gone
          state = {windSpeed = 8, cloudCover = 1, numOfDrops = 3000, time = 0}
          objs[1], objs[2], objs[3] = nil, nil, nil
          frames[6] = fx.step(3, read, find, 4)
          frames[7] = fx.step(3.1, read, find, 4)
          return first, frames, #fx.objects
        end''')
        first, frames, alive = run(self.fx)
        self.assertGreater(first, 100)
        self.assertEqual([frames[k] for k in range(1, 8)], [4, 4, 2, 0, 0, 4, 3])
        self.assertEqual(alive, 7)


if __name__ == '__main__':
    unittest.main()
