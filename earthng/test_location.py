"""The line of where the car is (mod location.lua): the street under it and the settlement it is in."""
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'mod/lua/ge/extensions/e2r/location.lua').read_text(encoding='utf8')

HELPERS = r'''
  function seg(name, points, more)
    local s = {'id', 'a', 'b', '+', 10, 3.5, 1}
    local x0, y0, x1, y1 = 1e9, 1e9, -1e9, -1e9
    for _, p in ipairs(points) do
      s[#s + 1], s[#s + 2], s[#s + 3] = p[1], p[2], 0
      x0, y0, x1, y1 = math.min(x0, p[1]), math.min(y0, p[2]), math.max(x1, p[1]), math.max(y1, p[2])
    end
    local names = more or {}
    names.n = name
    return {s = s, box = {x0, y0, x1, y1}, names = (name or more) and names or nil}
  end
'''


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.mod = self.lua.execute(SRC)
        self.lua.execute(HELPERS)
        self.lua.globals().L = self.mod

    def test_the_closest_street_wins(self):
        name = self.lua.eval('''(function()
          local list = {a = seg('Main', {{0, 0}, {100, 0}}), b = seg('Side', {{0, 12}, {100, 12}})}
          return L.nearest(list, 50, 3, 0, 0).names.n
        end)()''')
        self.assertEqual(name, 'Main')

    def test_nothing_within_reach_is_no_street(self):
        self.assertTrue(self.lua.eval('''L.nearest({seg('Main', {{0, 0}, {100, 0}})}, 50, 41, 0, 0) == nil'''))

    def test_the_heading_picks_the_road_it_runs_along(self):
        """At a junction a car going east on the avenue is nearer the cross street's axis."""
        name = self.lua.eval('''(function()
          local list = {a = seg('Avenue', {{0, 0}, {100, 0}}), b = seg('Cross', {{50, -100}, {50, 100}})}
          return L.nearest(list, 52, 3, 1, 0).names.n
        end)()''')
        self.assertEqual(name, 'Avenue')

    def test_a_street_holds_at_a_junction_but_not_past_it(self):
        names = self.lua.eval('''(function()
          local a, b = seg('Avenue', {{0, 0}, {100, 0}}), seg('Cross', {{100, -100}, {100, 100}})
          local list = {a = a, b = b}
          return L.nearest(list, 96, 1, 0, 0, b).names.n, L.nearest(list, 80, 1, 0, 0, b).names.n
        end)()''')
        self.assertEqual(names, ('Cross', 'Avenue'))

    def test_a_language_uses_its_name_then_the_common_one_then_the_number(self):
        self.assertEqual(self.lua.eval("L.label({n = 'Хрещатик', u = 'вул. Хрещатик', e = 'Khreshchatyk St', r = 'E40'}, 'en')"),
                         ('Khreshchatyk St', 'E40'))
        self.assertEqual(self.lua.eval("L.label({n = 'Main St'}, 'uk')"), ('Main St', None))
        self.assertEqual(self.lua.eval("L.label({r = 'M06'}, 'uk')"), 'M06')

    def test_settlements(self):
        self.lua.execute('''
          places = L.index({
            {50.45, 30.52, 7, 'Kyiv', 'Київ', 1, 2950000, 'city'},
            {50.465, 30.515, 13, 'Podil', 'Поділ', 0, 0, 'suburb'},
            {50.2, 31.5, 11, 'Hlybochok', 'Глибочок', 0, 400, 'village'},
            {50.3, 31.5, 9, 'Town', 'Місто', 0, 0, 'town'},
          })''')
        town, part, near = self.lua.eval('L.settlement(places, 50.466, 30.516)')
        self.assertEqual((town[4], part[4], near), ('Kyiv', 'Podil', None))
        town, part, near = self.lua.eval('L.settlement(places, 50.30, 30.52)')
        self.assertEqual((town[4], part), ('Kyiv', None), 'the population reaches beyond a point: Kyiv is ~19 km across')
        town, part, near = self.lua.eval('L.settlement(places, 50.2, 31.51)')
        self.assertEqual((town[4], near), ('Hlybochok', None))
        town, part, near = self.lua.eval('L.settlement(places, 50.27, 31.56)')
        self.assertEqual((town, near[4]), (None, 'Town'), 'outside them all: near the closest')
        self.assertEqual(self.lua.eval('L.settlement(places, 45, 20)'), (None, None, None))

    def text(self, chunk):
        return self.lua.eval('''(function()
          local t, seen = L.new(), {}
          local env = {lang = 'uk', lat = 50.466, lon = 30.516, segments = {},
            places = function() return places end, near = function(n) return 'поблизу ' .. n end,
            region = function() return nil, 'Україна' end}
          local function go(now, x, y, vx, vy) return L.step(t, now, x, y, vx or 0, vy or 0, env) end
          ''' + chunk + '''
          return t.main, t.rest, t.ref, t.limit
        end)()''')

    def line(self):
        self.lua.execute('''places = L.index({{50.45, 30.52, 7, 'Kyiv', 'Київ', 1, 2950000, 'city'},
                                              {50.465, 30.515, 13, 'Podil', 'Поділ', 0, 0, 'suburb'}})''')

    def test_the_line_says_street_part_city_country(self):
        self.line()
        got = self.text("""env.segments = {seg('вул. Сагайдачного', {{0, 0}, {100, 0}}, {r = 'E40', l = '50'})}; go(0, 50, 0)""")
        self.assertEqual(got, ('вул. Сагайдачного', 'Поділ, Київ, Україна', 'E40', '50'))

    def test_without_a_street_the_settlement_leads(self):
        self.line()
        self.assertEqual(self.text('go(0, 0, 0)')[:2], ('Поділ', 'Київ, Україна'))

    def test_a_name_the_pack_repeats_is_said_once(self):
        self.lua.execute("places = L.index({{48.85, 2.35, 7, 'Paris', 'Париж', 1, 2100000, 'city'}})")
        got = self.text("env.lat, env.lon, env.region = 48.85, 2.35, function() return nil, 'Париж' end; go(0, 0, 0)")
        self.assertEqual(got[:2], ('Париж', None))

    def test_an_unnamed_stretch_keeps_the_name_for_a_moment(self):
        self.line()
        got = self.text("""
          local road = seg('Вулиця', {{0, 0}, {100, 0}})
          env.segments = {road, seg(nil, {{100, 0}, {300, 0}})}
          go(0, 50, 0, 10, 0)
          go(.5, 150, 0, 10, 0)
          seen.held = t.main
          assert(seen.held == 'Вулиця')
          go(1, 160, 0, 10, 0)
          go(4, 190, 0, 10, 0)""")
        self.assertEqual(got[0], 'Поділ', 'the name goes after HOLD s')

    def test_nothing_changes_no_text_is_built(self):
        self.line()
        changed = self.lua.eval('''(function()
          local t = L.new()
          local env = {lang = 'uk', lat = 50.466, lon = 30.516, segments = {seg('Вулиця', {{0, 0}, {100, 0}})},
            places = function() return places end}
          local first = L.step(t, 0, 50, 0, 0, 0, env)
          return first, L.step(t, .25, 51, 0, 0, 0, env), L.step(t, 3, 52, 0, 0, 0, env)
        end)()''')
        self.assertEqual(changed, (True, False, False))

    def test_the_language_changes_the_line_at_once(self):
        self.line()
        got = self.text("""
          env.segments = {seg('Вулиця', {{0, 0}, {100, 0}}, {e = 'Street'})}
          go(0, 50, 0)
          env.lang = 'en'
          go(.25, 50, 0)""")
        self.assertEqual(got[:2], ('Street', 'Podil, Kyiv, Україна'))


class NamesFromRoads(unittest.TestCase):
    def test_the_generator_gives_a_segment_its_names(self):
        src = (ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8')
        self.assertIn('nav.names[navigation[1]] = navNames(road)', src)


if __name__ == '__main__':
    unittest.main()
