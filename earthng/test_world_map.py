"""The world map on M (worldmap.lua) and its point index (poiindex.lua): the index is built a slice
a frame, keeps line numbers for the OSM facts, tells finer kinds from the tags, draws the best
point of a crowded square first, and the card reads the facts in the player's language."""
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
LUA = (ROOT / 'mod/lua').as_posix()


def poi(key, lat, lon, cat, name, en=''):
    return '\t'.join([key, f'{lat:.6f}', f'{lon:.6f}', cat, name, en])


FAKE_IM = r'''
calls = {}
local function count(name) return function(...) calls[name] = (calls[name] or 0) + 1 end end
keys = {}
fakeIm = setmetatable({
  ImVec2 = function(x, y) return {x = x, y = y} end,
  GetIO = function() return {DisplaySize = {x = 1600, y = 900}, WantTextInput = typing or false} end,
  GetContentRegionAvail = function() return {x = 1584, y = 884} end,
  GetCursorScreenPos = function() return {x = 0, y = 0} end,
  CalcTextSize = function(t) return {x = #t * 7, y = 14} end,
  BoolPtr = function(v) return {[0] = v} end,
  ArrayChar = function() return {text = ''} end,
  Checkbox = function() return false end, Button = function() return false end,
  Selectable1 = function() return false end, InputTextWithHint = function() return false end,
  IsKeyPressed = function(k) return keys[k] or false end, GetKeyIndex = function(k) return k end,
  Key_Escape = 'esc', Key_C = 'c', Key_PageUp = 'pgup', Key_PageDown = 'pgdn',
  WindowFlags_NoTitleBar = 1, WindowFlags_NoResize = 2, WindowFlags_NoMove = 4, WindowFlags_NoCollapse = 8,
  Cond_Always = 1,
  ImDrawList_AddCircleFilled = count('circle'), ImDrawList_AddRectFilled = count('rect'),
  ImDrawList_AddText1 = function(_, _, _, t) calls.text = (calls.text or 0) + 1; texts[#texts + 1] = t end,
  ImDrawList_AddCircle = count('ring'),
}, {__index = function() return function() end end})
texts = {}
'''


class WorldMapTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path = '{LUA}/?.lua;' .. package.path")
        self.lua.execute(FAKE_IM)
        self.lua.execute('''
          fakeCatalog = {list = {}}
          function fakeCatalog.catalogs() return fakeCatalog.list end
          function fakeCatalog.text(c, name) return c.files[name] or false end
          pins = require('ge/extensions/e2r/pins')
          index = require('ge/extensions/e2r/poiindex')
          worldmap = require('ge/extensions/e2r/worldmap')
          worldmap.attach(fakeCatalog, pins)
        ''')
        self.index = self.lua.eval('index')
        self.worldmap = self.lua.eval('worldmap')

    def add(self, title, pois, tags=None):
        files = self.lua.table_from({'pois.tsv': ''.join(p + '\n' for p in pois)})
        if tags is not None:
            files['poi_tags.tsv'] = ''.join(t + '\n' for t in tags)
        c = self.lua.table_from({'title': title, 'files': files})
        self.lua.eval('function(c) fakeCatalog.list[#fakeCatalog.list + 1] = c end')(c)
        return c

    def build(self, most=500):
        steps = 0
        while steps < most:
            self.index.step()
            steps += 1
            st = self.index.stats()
            if st.total and st.done == st.total and not st.busy:
                return steps
        self.fail('the index never finished')

    def kyiv(self):
        pois = [
            poi('замок', 50.4501, 30.5001, 'castle', 'Замок'),
            poi('кіоск', 50.4502, 30.5002, 'kiosk', 'Кіоск'),
            poi('wog', 50.4400, 30.5100, 'service_map', 'WOG', 'WOG en'),
            poi('аптека', 50.4402, 30.5102, 'service_map', 'Аптека'),
            'broken line without tabs',
            poi('кафе', 50.4420, 30.5120, 'food', 'Кафе'),
        ]
        tags = [
            'osm=n1\thistoric=castle\tstart_date=1650',
            'osm=n2\tshop=kiosk',
            'osm=n12\tamenity=fuel\tbrand=WOG\topening_hours=24/7\tfuel:diesel=yes\tfuel:octane_95=yes'
            '\taddr:street=Хрещатик\taddr:housenumber=1\taddr:city=Київ\twheelchair=limited',
            'osm=w7\tamenity=pharmacy',
            '',
            'osm=n9\tamenity=cafe\tcuisine=coffee_shop;pastry',
        ]
        return pois, tags

    def test_the_index_is_built_in_slices_and_keeps_the_lines(self):
        pois = [poi(f'p{k}', 50 + (k % 100) * .01, 30 + (k // 100) * .01, 'shop_map', f'P{k}') for k in range(20000)]
        self.add('Тест', sorted(pois))
        self.index.SLICE = 0
        steps = self.build(2000)
        self.assertGreater(steps, 3, 'a slice a frame, not the whole file at once')
        self.assertEqual(self.index.stats().points, 20000)
        self.assertIsNone(self.index.entries()[1].tags, 'no poi_tags.tsv: no facts, no finer kinds')
        self.assertEqual(self.index.name(self.index.entries()[1], 20000, 'uk'), sorted(f'P{k}' for k in range(20000))[-1])

    def test_finer_kinds_details_and_a_broken_line(self):
        pois, tags = self.kyiv()
        self.add('Україна', pois, tags)
        self.build()
        e = self.index.entries()[1]
        cats = {self.index.category(e, i) for i in (1, 2, 3, 4, 6)}
        self.assertEqual(cats, {'castle', 'kiosk', 'service_map/fuel', 'service_map/pharmacy', 'food/cafe'})
        self.assertEqual(self.index.stats().points, 5, 'the broken line is left out')
        # line 6 keeps its own facts after the broken line 5
        self.assertEqual(self.index.name(e, 6, 'uk'), 'Кафе')
        self.assertEqual(dict((kv[1], kv[2]) for kv in self.index.details(e, 6).values())['cuisine'], 'coffee_shop;pastry')
        self.assertEqual(self.index.name(e, 3, 'en'), 'WOG en')
        self.assertEqual(self.index.name(e, 3, 'uk'), 'WOG')
        fuel = self.index.PRIORITY[self.index.catId('service_map/fuel')]
        self.assertEqual(fuel, 3, 'a fuel station stands before the broad service pins')
        found = self.index.find(50.44, 30.51, 'service_map')
        self.assertTrue(self.lua.eval('function(a, b) return a == b end')(found[0], e))
        self.assertEqual(found[1], 3, 'a search hit of the broad category finds the finer point')

    def test_mismatched_facts_are_not_used(self):
        pois, tags = self.kyiv()
        self.add('Україна', pois, tags[:-1])
        self.build()
        e = self.index.entries()[1]
        self.assertIsNone(e.tags)
        self.assertEqual(self.index.category(e, 3), 'service_map')

    def collect(self, z, box, enabled_all=True):
        lua = self.lua
        lua.execute('found = {}')
        add = lua.eval('function(e, i, level) found[#found + 1] = {index.category(e, i), level} end')
        enabled = lua.table_from({k: True for k in range(1, len(self.index.CATS) + 1)})
        per = lua.eval(f'(function() local px = index.GRID / 360 * 256 * 2 ^ {z}; '
                       f'return px <= 24 and 1 or math.min(400, math.ceil((px / 24) ^ 2)) end)()')
        self.index.collect(box[0], box[1], box[2], box[3], per, enabled, add)
        return [(f[1], f[2]) for f in lua.eval('found').values()]

    def test_a_crowded_cell_shows_its_best_point_first(self):
        pois, tags = self.kyiv()
        self.add('Україна', pois, tags)
        self.build()
        far = self.collect(6, (30, 50, 31, 51))
        self.assertEqual(sorted(far), [('castle', 2), ('service_map/fuel', 3)],
                         'one point a cell from afar: the castle, not the kiosk beside it; the fuel station of its three')
        near = self.collect(16, (30.49, 50.43, 30.52, 50.46))
        self.assertEqual(sorted(c for c, _ in near), ['castle', 'food/cafe', 'kiosk', 'service_map/fuel', 'service_map/pharmacy'])
        self.assertEqual(self.collect(16, (10, 10, 11, 11)), [], 'nothing outside the box')

    def api(self, car=None):
        return self.lua.eval('''function(car)
          local L = function(uk, en) return uk end
          return {im = fakeIm, col = function() return 1 end, L = L, lang = function() return 'uk' end,
            theme = function() return {muted = 1, accent = 2, warn = 3} end, pushTheme = function() end, popTheme = function() end,
            winguard = {begin = function() end}, planetMap = {place = function() return true end, reserve = function() end,
              search = function() return {} end, searchPois = function() return {} end},
            drawMap = function(w, h, view)
              mapView = view
              -- a pan of (panX, panY) px moves every point and the box by as much
              local dx, dy = panX or 0, panY or 0
              local function screen(lat, lon) return (lon - 30.5) * 10000 + 800 + dx, (50.45 - lat) * 10000 + 450 + dy end
              local w, n = 30.4 - dx / 10000, 50.5 + dy / 10000
              view.overlay(1, screen, view.zoom, n, w, n - 0.1, w + 0.2, mouse, mouse ~= nil, {x = 340, y = 0}, {x = 1600, y = 900})
            end,
            car = function() return car end, start = function() return {lat = 50.45, lon = 30.5}, 16 end,
            canLand = function() return {title = 'Україна'} end, land = function() landed = true end,
            canNavigate = function() return true end, navigate = function() return true end,
            close = function() closed = true end}
        end''')(self.lua.table_from(car) if car else None)

    def test_remote_index_does_not_hide_streamed_pins_and_filters_still_apply(self):
        pois, tags = self.kyiv()
        self.add('Україна', pois, tags)
        self.build()
        self.worldmap.draw(self.api())
        view = self.lua.eval('mapView')
        self.assertFalse(view.noPins, 'Kyiv data must not hide pins in a section without a sidecar')
        pin = self.lua.table_from({'cat': 'parking'})
        self.assertTrue(view.acceptPin(pin))
        self.worldmap.state.off.parking = True
        self.assertFalse(view.acceptPin(pin))

        self.worldmap.state.off.parking = None
        cafe = self.lua.table_from({'cat': 'food', 'lat': 50.442, 'lon': 30.512})
        self.assertTrue(view.acceptPin(cafe))
        self.worldmap.state.off['food/cafe'] = True
        self.assertFalse(view.acceptPin(cafe), 'a disabled finer kind must not reappear as a streamed broad category')
        self.worldmap.state.points = False
        self.worldmap.draw(self.api())
        self.assertTrue(view.noPins)
        self.assertFalse(view.acceptPin(pin))

    def test_fullscreen_map_follows_main_viewport_desktop_origin(self):
        self.lua.execute('''
          fakeIm.GetMainViewport=function() return {Pos={x=480,y=258},Size={x=1600,y=900}} end
          fakeIm.SetNextWindowPos=function(p) nextPos=p end
          fakeIm.SetNextWindowSize=function(p) nextSize=p end
        ''')
        self.worldmap.draw(self.api())
        self.assertEqual((self.lua.globals().nextPos.x, self.lua.globals().nextPos.y), (480, 258))
        self.assertEqual((self.lua.globals().nextSize.x, self.lua.globals().nextSize.y), (1600, 900))

    def test_the_card_tells_the_osm_facts(self):
        pois, tags = self.kyiv()
        self.add('Україна', pois, tags)
        self.build()
        e = self.index.entries()[1]
        lines = [l[1] for l in self.worldmap.card(self.api({'lat': 50.45, 'lon': 30.5}), self.lua.table_from({'e': e, 'i': 3})).values()]
        self.assertEqual(lines[0], 'WOG')
        self.assertEqual(lines[1], 'АЗС · Україна')
        self.assertIn('Адреса: Хрещатик 1, Київ', lines)
        self.assertIn('Пальне: дизель, А-95', lines)
        self.assertIn('Години: 24/7', lines)
        self.assertIn('Доступ на візку: частково', lines)
        self.assertIn('OSM: amenity=fuel', lines)
        self.assertIn('osm.org/node/12', lines)
        self.assertTrue(lines[-1].endswith('км від авто'), lines[-1])
        cafe = [l[1] for l in self.worldmap.card(self.api(), self.lua.table_from({'e': e, 'i': 6})).values()]
        self.assertIn('Кухня: coffee shop, pastry', cafe)
        pharmacy = [l[1] for l in self.worldmap.card(self.api(), self.lua.table_from({'e': e, 'i': 4})).values()]
        self.assertIn('osm.org/way/7', pharmacy)

    def test_clicking_a_guide_label_opens_the_complete_article(self):
        import json
        article = json.loads((ROOT / 'mod/earthng/planet/guide.json').read_text(encoding='utf8'))[0]
        api = self.api()
        self.worldmap.draw(api)
        place = self.lua.table_from({'name': article['title']['uk'], 'article': article}, recursive=True)
        self.lua.eval('mapView').onClick(article['lat'], article['lon'], place)
        lines = [l[1] for l in self.worldmap.card(api, self.worldmap.state.pick).values()]
        self.assertEqual(lines[0], article['title']['uk'])
        self.assertIn(article['summary']['uk'], lines)
        self.assertIn('Джерело · ' + article['source'], lines)
        self.assertIsNone(self.lua.eval('landed'))

    def test_the_settlement_browser_pages_the_whole_pack(self):
        self.lua.globals().api = self.api()
        self.lua.execute('''
          local pack = {id='ua', title='Україна', starts={}}
          local packs, towns = {pack}, {}
          for i = 1, 53 do towns[i] = {50, 30 + i/1000, 14, 'Town ' .. i, 'Місто ' .. i, 0, 0, 'town'} end
          api.packs = function() return packs end
          api.planetMap.lower = string.lower
          api.planetMap.revision = function() return 1 end
          api.planetMap.packPlaces = function(id) assert(id == 'ua'); return towns end
          fakeIm.GetContentRegionAvailWidth = function() return 275 end
          fakeIm.SmallButton = function(label) return label:find('##browseNext', 1, true) ~= nil end
          fakeIm.Selectable1 = function(label) return label:find('##browseResult53', 1, true) ~= nil end
          local browser = {pack='ua', category='towns'}
          local view = {center={lat=50,lon=30}}
          for _ = 1, 7 do worldmap.drawBrowser(api, view, browser, function(row) chosen=row end) end
          assert(chosen.title == 'Місто 53')
          assert(chosen.lon == towns[53][2])
          assert(#browser.rows == 0, 'only visible pages of the catalog are materialized')
        ''')

    def test_the_map_draws_icons_close_up_dots_afar_and_hovers(self):
        pois, tags = self.kyiv()
        self.add('Україна', pois, tags)
        self.build()
        api = self.api()
        self.lua.execute('mouse = {x = 800 + 0.0001 * 10000, y = 450 - 0.0001 * 10000}')   # over the castle
        self.worldmap.draw(api)
        drawn = self.worldmap.drawn
        shown = lambda: sorted(drawn.i[k] for k in range(1, drawn.n + 1))
        self.assertEqual(shown(), [1, 3], 'the castle and fuel station win their cells over the kiosk, pharmacy and café')
        self.assertEqual(self.worldmap.state.hoverI, 1, 'the castle under the cursor')
        self.assertIn('Замок', list(self.lua.eval('texts').values()), 'its name beside the icon and on the card')
        # the castle filtered out: the kiosk takes its square; the cafe off too
        self.worldmap.state.off['castle'] = True
        self.worldmap.state.off['food/cafe'] = True
        self.worldmap.state.filterRev += 1
        self.worldmap.draw(api)
        self.assertEqual(shown(), [2, 3])
        # afar: dots, one square for the castle and kiosk
        self.lua.execute('calls = {}')
        self.lua.eval('mapView').zoom = 8
        self.worldmap.draw(api)
        self.assertGreaterEqual(self.lua.eval('calls').circle, 2 * drawn.n)

    def crowd(self, count=4000):
        """count points spread over the fake view, one category each of three"""
        cats = ['castle', 'food', 'shop_map']
        return [poi(f'p{k}', 50.401 + (k % 80) * 0.00122, 30.401 + (k // 80) * 0.0039, cats[k % 3], f'P{k}')
                for k in range(count)]

    def test_the_markers_are_capped_and_a_drag_does_not_collect_again(self):
        self.add('Тест', self.crowd())
        self.build(5000)
        self.worldmap.MAX_ICONS = 50
        api = self.api()
        self.worldmap.draw(api)
        drawn = self.worldmap.drawn
        self.assertEqual(drawn.n, 50, 'never more markers than the cap, however many points the view has')
        collects = self.worldmap.collects
        first = {drawn.i[k]: (drawn.x[k], drawn.y[k]) for k in range(1, drawn.n + 1)}
        self.lua.execute('panX, panY = 37, -21')
        self.worldmap.draw(api)
        self.assertEqual(self.worldmap.collects, collects, 'a short drag stays in the collected box')
        moved = {drawn.i[k]: (drawn.x[k], drawn.y[k]) for k in range(1, drawn.n + 1)}
        same = [i for i in moved if i in first]
        self.assertGreater(len(same), 20)
        for i in same:
            self.assertAlmostEqual(moved[i][0] - first[i][0], 37, places=6)
            self.assertAlmostEqual(moved[i][1] - first[i][1], -21, places=6)
        # a drag past the padding collects again; the squares are the world's, so a point that
        # won its square keeps it
        self.lua.execute('panX, panY = 1600, 0')
        self.worldmap.draw(api)
        self.assertEqual(self.worldmap.collects, collects + 1)

    def test_a_wide_collect_is_spread_over_frames_and_the_last_markers_stay(self):
        self.add('Тест', self.crowd(20000))
        self.build(5000)
        api = self.api()
        self.worldmap.draw(api)
        before = self.worldmap.drawn.n
        self.assertGreater(before, 0)
        self.worldmap.SLICE = -1   # yield at every pause (os.clock steps by a millisecond on Windows)
        self.worldmap.state.off['food'] = True
        self.worldmap.state.filterRev += 1
        frames = 0
        collects = self.worldmap.collects
        while self.worldmap.collects == collects:
            self.worldmap.draw(api)
            frames += 1
            self.assertLess(frames, 500)
            if self.worldmap.collects == collects:
                self.assertGreater(self.worldmap.drawn.n, 0, 'the last markers stay while the new ones are collected')
                cats = {self.index.category(self.worldmap.drawn.e[k], self.worldmap.drawn.i[k])
                        for k in range(1, self.worldmap.drawn.n + 1)}
                self.assertNotIn('food', cats, 'a category switched off leaves at once')
        self.assertGreater(frames, 2, 'a slice a frame, not the whole box at once')

    def test_a_click_picks_and_esc_shuts_and_the_game_pauses(self):
        pois, tags = self.kyiv()
        self.add('Україна', pois, tags)
        self.build()
        self.lua.execute('''
          paused = false
          simTimeAuthority = {pause = function(on) paused = on end, getPause = function() return paused end}
          mouse = {x = 800 + 1, y = 450 - 1}
        ''')
        api = self.api()
        self.worldmap.draw(api)
        self.assertTrue(self.lua.eval('paused'), 'the game pauses while the map is open')
        self.lua.eval('mapView').onClick(50.45, 30.5)
        pick = self.worldmap.state.pick
        self.assertEqual(pick.i, 1, 'a click on a marker picks that point, it does not land')
        self.assertIsNone(self.lua.eval('landed'))
        self.lua.execute('mouse = nil')
        self.worldmap.draw(api)
        self.lua.eval('mapView').onClick(50.0, 30.0)
        self.assertIsNone(self.worldmap.state.pick.e, 'an empty place: a plain point')
        self.lua.execute("keys.esc = true")
        self.worldmap.draw(api)
        self.assertTrue(self.lua.eval('closed'))
        self.worldmap.closed()
        self.assertFalse(self.lua.eval('paused'), 'the game runs again')
        # a game the player paused stays paused
        self.lua.execute('paused = true; keys.esc = false')
        self.worldmap.draw(api)
        self.worldmap.closed()
        self.assertTrue(self.lua.eval('paused'))


if __name__ == '__main__':
    unittest.main()
