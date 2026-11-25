"""The map's motion (mapmotion.lua), its roads at every zoom (maproads.lua), the markers' atlas
(map_icons.py) and the game's own minimap on an EarthNG level (minimap.lua)."""
import json
import math
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

import build_map
import map_icons

ROOT = Path(__file__).resolve().parents[1]
LUA = (ROOT / 'mod/lua').as_posix()


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f"package.path = '{LUA}/?.lua;' .. package.path")
    return lua


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.lua = runtime()
        self.lua.execute('''
          motion = require('ge/extensions/e2r/mapmotion')
          view = {center = {lat = 50.45, lon = 30.52}, zoom = 12}
          function run(seconds) local t = 0; while t < seconds do motion.step(view, 1 / 60, 1200, 800); t = t + 1 / 60 end end
          function under(sx, sy)
            local scale = 256 * 2 ^ view.zoom
            local cx, cy = motion.mercUnit(view.center.lat, view.center.lon)
            return motion.unmercUnit(cx + (sx - 600) / scale, cy + (sy - 400) / scale)
          end''')

    def test_the_wheel_eases_a_level_round_the_cursor(self):
        lua = self.lua
        lat, lon = lua.eval('under(900, 250)')
        lua.execute('motion.zoomBy(view, 1, 900, 250, 1200, 800); motion.step(view, 1 / 60, 1200, 800)')
        z = lua.eval('view.zoom')
        self.assertTrue(12 < z < 12.5, 'a frame moves the zoom a part of the way, not the whole level')
        seen = [z]
        for _ in range(8):
            lua.execute('motion.step(view, 1 / 60, 1200, 800)')
            seen.append(lua.eval('view.zoom'))
            now = lua.eval('under(900, 250)')
            self.assertAlmostEqual(now[0], lat, places=7, msg='the place under the cursor stays under it')
            self.assertAlmostEqual(now[1], lon, places=7)
        self.assertEqual(seen, sorted(seen))
        lua.execute('run(1)')
        self.assertEqual(lua.eval('view.zoom'), 13)
        self.assertFalse(lua.eval('motion.step(view, 1 / 60, 1200, 800)'), 'at rest')
        # two notches before the first is done add up; the limits hold
        lua.execute('motion.zoomBy(view, 1, 600, 400, 1200, 800); motion.zoomBy(view, 1, 600, 400, 1200, 800); run(1.5)')
        self.assertEqual(lua.eval('view.zoom'), 15)
        lua.execute('for _ = 1, 9 do motion.zoomBy(view, 1) end; run(2)')
        self.assertEqual(lua.eval('view.zoom'), 18)

    def test_a_thrown_map_glides_and_stops_and_a_held_one_does_not(self):
        lua = self.lua
        lua.execute('for _ = 1, 12 do motion.drag(view, -20, 0, 1 / 60) end')
        lon = lua.eval('view.center.lon')
        self.assertGreater(lon, 30.52, 'dragged left: the centre goes east')
        lua.execute('motion.release(view); run(.2)')
        glide = lua.eval('view.center.lon')
        self.assertGreater(glide, lon, 'it keeps moving after the release')
        lua.execute('run(3)')
        rest = lua.eval('view.center.lon')
        lua.execute('run(1)')
        self.assertEqual(lua.eval('view.center.lon'), rest, 'and comes to rest')
        self.assertLess((rest - lon) * 256 * 2 ** 12 / 360, 600, 'within a screen')
        # the hand stopped before letting go: no throw
        lua.execute('for _ = 1, 12 do motion.drag(view, -20, 0, 1 / 60) end; for _ = 1, 12 do motion.drag(view, 0, 0, 1 / 60) end')
        held = lua.eval('view.center.lon')
        lua.execute('motion.release(view); run(1)')
        self.assertEqual(lua.eval('view.center.lon'), held)

    def test_a_flight_to_a_place_and_a_jump_to_a_far_one(self):
        lua = self.lua
        lua.execute('motion.flyTo(view, 50.46, 30.60, 14, 1200, 800); motion.step(view, .1, 1200, 800)')
        lon = lua.eval('view.center.lon')
        self.assertTrue(30.52 < lon < 30.60)
        lua.execute('run(1)')
        self.assertAlmostEqual(lua.eval('view.center.lon'), 30.60, places=9)
        self.assertEqual(lua.eval('view.zoom'), 14)
        lua.execute('motion.flyTo(view, 37.77, -122.42, 13, 1200, 800)')
        self.assertEqual(lua.eval('view.center.lon'), -122.42, 'another continent is a jump')
        self.assertEqual(lua.eval('view.zoom'), 13)

    def test_a_zoom_or_centre_written_from_outside_is_taken_as_it_is(self):
        lua = self.lua
        lua.execute('motion.zoomBy(view, 2); motion.step(view, 1 / 60, 1200, 800); view.zoom = 9; view.center = {lat = 1, lon = 2}')
        lua.execute('run(1)')
        self.assertEqual(lua.eval('view.zoom'), 9)
        self.assertEqual((lua.eval('view.center.lat'), lua.eval('view.center.lon')), (1, 2))
        self.assertEqual((lua.eval('motion.level(9.49)'), lua.eval('motion.level(9.5)')), (9, 10))
        self.assertAlmostEqual(lua.eval('motion.stretch(9.5, 10)'), 2 ** -.5)


FAKE_DRAW = '''
  paths, strokes, images, point = {}, {}, {}, {}
  im = setmetatable({
    ImVec2 = function(x, y) return {x = x, y = y} end,
    ImDrawList_PathLineTo = function(_, p) point[#point + 1] = {p.x, p.y} end,
    ImDrawList_PathStroke = function(_, colour, _, width)
      strokes[#strokes + 1] = {colour = colour, width = width, points = point}; point = {}
    end,
    ImDrawList_AddImage = function(_, tex, a, b, _, _, colour) images[#images + 1] = {tex, a.x, a.y, b.x, b.y, colour} end,
  }, {__index = function() return function() end end})
  -- a colour is its own description
  function col(r, g, b, a) return string.format('%.2f %.2f %.2f %.2f', r, g, b, a or 1) end
'''


class RoadsTests(unittest.TestCase):
    def setUp(self):
        self.lua = runtime()
        self.lua.execute(FAKE_DRAW)
        self.lua.execute('''
          roads = require('ge/extensions/e2r/maproads')
          motion = require('ge/extensions/e2r/mapmotion')
          -- the view of a 800 x 600 map centred on lat, lon at a zoom
          function viewAt(lat, lon, zoom)
            local scale = 256 * 2 ^ zoom
            local cx, cy = motion.mercUnit(lat, lon)
            return {rx = 100, ry = 50, x0 = cx * scale - 400, y0 = cy * scale - 300, scale = scale, width = 800, height = 600}
          end''')

    def tile(self, lines):
        return json.dumps([{'rank': rank, 'box': [0, 0, 0, 0], 'geo': [v for point in geo for v in point]} for rank, geo in lines],
                          separators=(',', ':'))

    def test_a_tile_is_taken_apart_without_a_json_decode_and_in_slices(self):
        lua = self.lua
        text = self.tile([(1, [(50.0, 30.0), (50.1, 30.1), (50.2, 30.1)]), (3, [(50.0, 30.0), (50.0, 30.2)]), (2, [(50.0, 30.0)])])
        lua.globals().text = text
        lua.execute('pauses = 0; lines = roads.parse(text, function() pauses = pauses + 1 end)')
        self.assertEqual(lua.eval('#lines'), 2, 'a line of one point is not a line')
        self.assertEqual((lua.eval('lines[1].class'), lua.eval('lines[1].n'), lua.eval('lines[2].class')), (1, 3, 3))
        x, y = lua.eval('motion.mercUnit(50.1, 30.1)')
        self.assertAlmostEqual(lua.eval('lines[1].xs[2]'), x)
        self.assertAlmostEqual(lua.eval('lines[1].ys[2]'), y)
        self.assertAlmostEqual(lua.eval('lines[1].x1'), lua.eval('lines[1].xs[2]'), msg='its box in Mercator units')
        # what the builder writes is what the reader reads: road_tiles' own JSON
        built = [item for _, _, level, item in build_map.road_tiles([(30, 50), (30.3, 50.1)], 1) if level == 11]
        lua.globals().built = json.dumps(built, separators=(',', ':'))
        self.assertEqual(lua.eval('#roads.parse(built)'), 1)
        # a file with another layout goes through the decoder whole
        lua.globals().odd = json.dumps([{'geo': [50, 30, 50.1, 30.1], 'box': [0, 0, 0, 0], 'rank': 2}])
        lua.globals().decode = lambda t: lua.table_from(json.loads(t), recursive=True)
        self.assertEqual(lua.eval('#roads.parse(odd, nil, decode)'), 1)
        self.assertEqual(lua.eval('roads.parse(odd, nil, decode)[1].class'), 2)
        many = self.tile([(3, [(50 + k * 1e-4, 30), (50 + k * 1e-4, 30.1)]) for k in range(200)])
        lua.globals().many = many
        lua.execute('pauses = 0; roads.parse(many, function() pauses = pauses + 1 end)')
        self.assertGreater(lua.eval('pauses'), 10)

    def catalog(self, tiles):
        """A fake mapCatalog of one sidecar with level 11 tiles {name: (box, text)}."""
        lua = self.lua
        lua.execute('''
          files = {}
          catalog = {revision = 1, list = {{root = '/m/', index = {tiles = {}, raster = {}}}}}
          function catalog.catalogs() return catalog.list end
          function read(path) reads = (reads or 0) + 1; return files[path] end''')
        for name, (box, text) in tiles.items():
            lua.globals().name, lua.globals().text = name, text
            lua.execute(f'files["/m/" .. name] = text; catalog.list[1].index.tiles[name] = '
                        f'{{zoom = 11, file = name, box = {{{box[0]}, {box[1]}, {box[2]}, {box[3]}}}}}')

    def test_tiles_under_the_view_come_a_slice_a_frame_and_are_kept(self):
        lua = self.lua
        near = self.tile([(1, [(50.4, 30.4), (50.6, 30.6)])])
        far = self.tile([(2, [(51.4, 30.4), (51.6, 30.6)])])
        self.catalog({'11_30_50.json': ((30, 50, 31, 51), near), '11_30_51.json': ((30, 51, 31, 52), far)})
        lua.execute('out = {}; frames = 0')
        lua.execute('''
          repeat
            frames = frames + 1
            n = roads.sidecar(catalog, 11, 30.4, 50.4, 30.6, 50.6, out, read)
          until n == 1 or frames > 50''')
        self.assertGreaterEqual(lua.eval('frames'), 2, 'the read and the parse are not the frame that asked')
        self.assertEqual((lua.eval('#out'), lua.eval('reads')), (1, 1), 'only the tile under the view is read')
        lua.execute('for _ = 1, 20 do roads.sidecar(catalog, 11, 30.4, 50.4, 30.6, 50.6, out, read) end')
        self.assertEqual(lua.eval('reads'), 1, 'and it is read once')
        self.assertFalse(lua.eval('roads.busy()'))

    def test_lines_are_drawn_by_class_within_the_budget_and_only_in_the_view(self):
        lua = self.lua
        lua.execute('''
          local function line(class, points, key)
            local xs, ys = {}, {}
            for k, p in ipairs(points) do xs[k], ys[k] = motion.mercUnit(p[1], p[2]) end
            return roads.newLine(class, xs, ys, #points, key)
          end
          street = line(4, {{50.449, 30.50}, {50.449, 30.54}})
          motorway = line(1, {{50.451, 30.50}, {50.4511, 30.52}, {50.451, 30.54}}, 'm1')
          again = line(1, {{50.451, 30.50}, {50.4511, 30.52}, {50.451, 30.54}}, 'm1')   -- the same road of the next tile
          away = line(1, {{51.5, 31.5}, {51.6, 31.6}})
          -- a long road that leaves the view and comes back: two runs, nothing sent for the part outside
          loop = line(2, {{50.45, 30.515}, {50.47, 30.515}, {50.60, 30.515}, {50.60, 30.525}, {50.47, 30.525}, {50.45, 30.525}})
          v = viewAt(50.45, 30.52, 14)
          sent, cut = roads.draw(im, {}, col, {{street, motorway, again, away, loop}}, v, 14, false,
            {true, true, true, true, true})''')
        strokes = [dict(s) for s in lua.eval('strokes').values()]
        style = lua.eval('roads.styleOf(col, 14, false)')
        order = [(s['colour'], s['width']) for s in strokes]
        self.assertEqual(order[0], (style[4][2], style[4][1]), 'the street first: it lies under the others')
        self.assertEqual(order[-1], (style[1][2], style[1][1]), 'the motorway last, its fill over its casing')
        self.assertEqual(order[-2], (style[1][4], style[1][3]))
        self.assertEqual(sum(1 for o in order if o == (style[1][2], style[1][1])), 1, 'one road of two tiles is drawn once')
        loops = [s for s in strokes if s['colour'] == style[2][2]]
        self.assertEqual(len(loops), 2, 'the part off the view breaks the line in two')
        for s in strokes:
            for x, y in (tuple(p.values()) for p in s['points'].values()):
                self.assertTrue(-700 < x - 500 < 700 and -700 < y - 350 < 700, 'a point far off the view is never sent')
        self.assertFalse(lua.eval('cut'))
        # a road with a point every 30 m: all of them at zoom 15, one every MIN_PX from afar, both ends kept
        lua.execute('''
          local xs, ys = {}, {}
          for k = 1, 60 do xs[k], ys[k] = motion.mercUnit(50.45, 30.51 + k * .00042) end
          dense = roads.newLine(3, xs, ys, 60)
          function points(zoom)
            strokes = {}
            roads.draw(im, {}, col, {{dense}}, viewAt(50.45, 30.52, zoom), zoom, true, {true, true, true})
            return strokes[#strokes].points
          end
          near, far = points(15), points(10)''')
        self.assertEqual(len(lua.eval('near')), 60)
        self.assertTrue(2 <= len(lua.eval('far')) <= 12, len(lua.eval('far')))
        self.assertAlmostEqual(lua.eval('far[#far][1] - far[1][1]'), 59 * .00042 / 360 * 256 * 2 ** 10, places=3)
        # a spent budget keeps the heavier class and says so
        lua.execute('''
          strokes = {}
          sent, cut = roads.draw(im, {}, col, {{street, motorway, loop}}, v, 14, false, {true, true, true, true, true}, 6)''')
        self.assertTrue(lua.eval('cut'))
        colours = {s['colour'] for s in (dict(x) for x in lua.eval('strokes').values())}
        self.assertIn(style[1][2], colours)
        self.assertNotIn(style[4][2], colours, 'the street is what a spent budget leaves out')
        # and the next frames draw the lighter classes coarser until the view fits: no holes
        self.assertGreater(lua.eval('roads.coarse'), 1)
        lua.execute('''
          roads.coarse = 1
          local xs, ys = {}, {}
          for k = 1, 400 do xs[k], ys[k] = motion.mercUnit(50.45, 30.505 + k * .00006) end
          crowd = {}
          for row = 1, 12 do
            local shifted = {}
            for k = 1, 400 do shifted[k] = ys[k] + row * 2e-7 end
            crowd[row] = roads.newLine(2, xs, shifted, 400)
          end
          frames = {}
          for f = 1, 12 do
            strokes = {}
            local _, c = roads.draw(im, {}, col, {crowd}, v, 14, true, {true, true, true}, 1500)
            frames[f] = {cut = c, lines = #strokes / 2, coarse = roads.coarse}
          end''')
        frames = [dict(f) for f in lua.eval('frames').values()]
        self.assertTrue(frames[0]['cut'])
        self.assertLess(frames[0]['lines'], 12, 'the first frame of a crowded view runs out')
        self.assertFalse(frames[-1]['cut'])
        self.assertEqual(frames[-1]['lines'], 12, 'then every road is there, with fewer bends')
        self.assertLessEqual(frames[-1]['coarse'], lua.eval('roads.COARSEST'))
        lua.execute('roads.coarse = 1')
        # a frame with the view and the lines of the last one sends the last points without a walk;
        # a moved view walks again, from the points the line thinned once for its level
        lua.execute('''
          local set = {street, motorway, loop}
          local function frame(view)
            strokes = {}
            roads.draw(im, {}, col, {set}, view, 14, false, {true, true, true, true, true})
            local first = strokes[#strokes].points[1]
            return first[1], first[2]
          end
          ax, ay = frame(v)
          thinned = motorway.sk
          local x0 = motorway.sx[1]
          motorway.sx[1] = x0 + 1e-4   -- would move the motorway's first point 60 px if walked again
          bx, by = frame(v)
          local moved = {}
          for k, value in pairs(v) do moved[k] = value end
          moved.x0 = v.x0 - 3
          cx, cy = frame(moved)
          motorway.sx[1] = x0''')
        self.assertEqual((lua.eval('bx'), lua.eval('by')), (lua.eval('ax'), lua.eval('ay')), 'the same view is not walked again')
        self.assertIsNotNone(lua.eval('thinned'), 'a drawn line keeps its thinned points')
        self.assertGreater(abs(lua.eval('cx') - lua.eval('ax') - 3), 30, 'a moved view walks the kept points')
        # the walk takes the lines through the set's grid: a road over hundreds of its cells
        # (kept aside, looked at every frame) and a street in one cell are both drawn
        lua.execute('''
          local function line(class, points)
            local xs, ys = {}, {}
            for k, p in ipairs(points) do xs[k], ys[k] = motion.mercUnit(p[1], p[2]) end
            return roads.newLine(class, xs, ys, #points)
          end
          across = line(2, {{50.00, 30.07}, {50.45, 30.52}, {50.90, 30.97}})
          local set = {across, street}
          strokes = {}
          roads.draw(im, {}, col, {set}, viewAt(50.45, 30.52, 14), 14, false, {true, true, true, true, true})
          wide, cellsUsed = #set.grid.wide, 0
          for k in pairs(set.grid) do if type(k) == 'number' then cellsUsed = cellsUsed + 1 end end''')
        drawn = {dict(s)['colour'] for s in lua.eval('strokes').values()}
        self.assertEqual(lua.eval('wide'), 1)
        self.assertIn(lua.eval('cellsUsed'), (1, 2), 'the street is in the cells its box touches')
        self.assertTrue({style[2][2], style[4][2]} <= drawn)
        # a set may give its streets only (the blocks under EXACT)
        lua.execute('''
          strokes = {}
          local set = {street, motorway}; set.from = 4
          roads.draw(im, {}, col, {set}, v, 14, false, {true, true, true, true, true})''')
        self.assertEqual(len(lua.eval('strokes')), 1)

    def test_a_block_line_becomes_a_street_once(self):
        lua = self.lua
        lua.execute('''
          line = {rank = 2, geo = {50.45, 30.5, 50.46, 30.51}, box = {50.45, 30.5, 50.46, 30.51}}
          a = roads.ofBlock(line); b = roads.ofBlock(line)''')
        self.assertTrue(lua.eval('a == b'))
        self.assertEqual((lua.eval('a.class'), lua.eval('a.n')), (4, 2))
        self.assertEqual(lua.eval("roads.ofBlock({rank = 1, geo = {1, 1, 2, 2}}).class"), 1)
        self.assertEqual(lua.eval("roads.ofBlock({rank = 3, geo = {1, 1, 2, 2}}).class"), 5)

    def test_overview_tiles_stretch_with_the_zoom_and_have_a_rim(self):
        lua = self.lua
        self.catalog({})
        lua.execute('''
          catalog.list[1].index.raster = {['8/149/86'] = 'r8_149_86.png', ['8/150/86'] = 'r8_150_86.png', ['9/299/173'] = 'r9_299_173.png'}
          roads.texture = function(path) loads = (loads or 0) + 1; return {texId = path} end
          function frame(zoom) images = {}; return roads.raster(im, {}, col, catalog, viewAt(50.45, 30.52, zoom), zoom, false) end
          drawn = frame(8)''')
        self.assertEqual(lua.eval('drawn'), 2)
        images = [list(i.values()) for i in lua.eval('images').values()]
        self.assertEqual(len(images), 10, 'four rims and the tile itself, for each')
        body = [i for i in images if i[5] == lua.eval('col(1, 1, 1, 1)')]
        self.assertEqual(sorted(round(i[3] - i[1]) for i in body), [256, 256])
        self.assertEqual(body[0][3], body[1][1], 'neighbours share an edge to the pixel')
        # a third of a level in: the same tiles, 26 % larger, no new texture
        lua.execute('loads = 0; drawn = frame(8.33)')
        body = [list(i.values()) for i in lua.eval('images').values() if list(i.values())[5] == lua.eval('col(1, 1, 1, 1)')]
        self.assertEqual((lua.eval('drawn'), lua.eval('loads')), (2, 0))
        self.assertAlmostEqual(body[0][3] - body[0][1], 256 * 2 ** .33, delta=1)
        # past the half the next level's tiles
        lua.execute('drawn = frame(8.6)')
        self.assertEqual(lua.eval('images[#images][1]'), '/m/r9_299_173.png')


class IconTests(unittest.TestCase):
    def test_the_atlas_and_its_table_are_the_generators(self):
        self.assertEqual(map_icons.LUA.read_text(encoding='utf8'), map_icons.lua(),
                         'run earthng/map_icons.py after changing a mark or a category')
        from PIL import Image
        with Image.open(map_icons.ATLAS) as image:
            rows = (len(map_icons.names()) + map_icons.PER - 1) // map_icons.PER
            self.assertEqual(image.size, (map_icons.PER * map_icons.CELL, rows * map_icons.CELL))
            self.assertEqual(image.mode, 'RGBA')

    def test_every_category_of_the_map_has_its_mark(self):
        lua = runtime()
        lua.execute('''
          pins = require('ge/extensions/e2r/pins')
          index = require('ge/extensions/e2r/poiindex')
          icons = require('ge/extensions/e2r/map_icons')
          missing = {}
          for cat in pairs(pins.STYLE) do
            if not icons.cells[icons.category[cat] or ''] then missing[#missing + 1] = cat end
          end
          for parent, kinds in pairs(index.SUB) do
            for kind in pairs(kinds) do
              local name = parent .. '/' .. kind
              if not icons.cells[icons.category[name] or ''] then missing[#missing + 1] = name end
            end
          end
          table.sort(missing)''')
        self.assertEqual(list(lua.eval('missing').values()), [])

    def test_a_badge_draws_its_mark_from_the_atlas_and_letters_without_it(self):
        lua = runtime()
        lua.execute(FAKE_DRAW)
        lua.execute('''
          circles, texts = 0, {}
          im.ImDrawList_AddCircleFilled = function() circles = circles + 1 end
          im.ImDrawList_AddText1 = function(_, _, _, text) texts[#texts + 1] = text end
          im.CalcTextSize = function(t) return {x = 7 * #t, y = 13} end
          pins = require('ge/extensions/e2r/pins')
          pins.badge(im, {}, 'parking', pins.STYLE.parking, 100, 100, 10, 'blue', 'white', 'shade')''')
        self.assertEqual((lua.eval('circles'), list(lua.eval('texts').values()), lua.eval('#images')), (3, ['P'], 0))
        lua.execute('''
          package.loaded['ge/extensions/e2r/pins'] = nil
          pins = require('ge/extensions/e2r/pins')
          pins.texture = function(path) asked = path; return {texId = 7} end
          pins.badge(im, {}, 'service_map/fuel', nil, 100, 100, 10, 'blue', 'white', 'shade')
          pins.badge(im, {}, 'no such category', {text = 'ATM'}, 100, 100, 10, 'blue', 'white', 'shade')''')
        self.assertEqual(lua.eval('asked'), '/earthng/planet/map_icons.png')
        self.assertEqual(lua.eval('#images'), 1)
        self.assertEqual(lua.eval('images[1][4] - images[1][2]'), 16)
        self.assertEqual(list(lua.eval('texts').values()), ['P', 'A'], 'letters wider than a badge: the first')


class MinimapTests(unittest.TestCase):
    def setUp(self):
        self.lua = runtime()
        self.lua.execute('''
          mm = require('ge/extensions/e2r/minimap')
          pins = require('ge/extensions/e2r/pins')
          index = require('ge/extensions/e2r/poiindex')
          widths = {}
          ui_apps_minimap_vehicles = {drawPlayer = function(dtReal, dtSim) return .5 end}
          ui_apps_minimap_roads = {drawRoads = function(p, radius, td, settings, camPos, scale, dpi) widths[#widths + 1] = 2 / scale end}''')

    def test_the_scale_and_the_road_width_are_ours_only_while_installed(self):
        lua = self.lua
        game = lua.eval('ui_apps_minimap_vehicles.drawPlayer')
        lua.execute('mm.install()')
        self.assertEqual(lua.eval('ui_apps_minimap_vehicles.drawPlayer()'), 1.5, 'three times the game\'s 0.5 m a pixel')
        lua.execute('mm.setZoom(5)')
        self.assertEqual(lua.eval('ui_apps_minimap_vehicles.drawPlayer()'), 2.5)
        # a road stays ROAD_PX wide however far the minimap sees; close up it is the game's own
        lua.execute('ui_apps_minimap_roads.drawRoads(nil, 100, {}, {}, {}, 2.5, 1); ui_apps_minimap_roads.drawRoads(nil, 100, {}, {}, {}, .5, 1)')
        self.assertAlmostEqual(lua.eval('widths[1]'), 2.4)
        self.assertAlmostEqual(lua.eval('widths[2]'), 4)
        # installing again does not wrap the wrap; a module the game reloaded is wrapped anew
        lua.execute('mm.install(); mm.install()')
        self.assertEqual(lua.eval('ui_apps_minimap_vehicles.drawPlayer()'), 2.5)
        lua.execute('ui_apps_minimap_vehicles.drawPlayer = function() return 1 end; mm.install()')
        self.assertEqual(lua.eval('ui_apps_minimap_vehicles.drawPlayer()'), 5)
        lua.execute('mm.restore()')
        self.assertEqual(lua.eval('ui_apps_minimap_vehicles.drawPlayer()'), 1)
        self.assertFalse(lua.eval('mm.active()'))
        # a game without the modules is left alone
        lua.execute('ui_apps_minimap_vehicles, ui_apps_minimap_roads = nil, nil; mm.install(); mm.restore()')
        self.assertIsNotNone(game)

    def test_the_points_round_the_car_are_markers_by_weight_and_filter(self):
        lua = self.lua
        rows = [('замок', 50.4505, 30.5205, 'castle', 'Замок'), ('кіоск', 50.4506, 30.5206, 'kiosk', 'Кіоск'),
                ('азс', 50.4520, 30.5260, 'service_map', 'WOG'), ('готель', 50.4490, 30.5150, 'hotel', 'Готель'),
                ('далеко', 50.6000, 30.9000, 'castle', 'Далекий замок')]
        lua.globals().text = ''.join('\t'.join([k, f'{lat:.6f}', f'{lon:.6f}', cat, name, '']) + '\n' for k, lat, lon, cat, name in rows)
        lua.execute('''
          local catalog = {list = {{title = 'Тест', files = {['pois.tsv'] = text}}}}
          function catalog.catalogs() return catalog.list end
          function catalog.text(c, name) return c.files[name] or false end
          index.attach(catalog, pins)
          for _ = 1, 50 do index.step() end
          -- a frame of metres round 50.45, 30.52
          local k = 111320 * math.cos(math.rad(50.45))
          env = {index = index, pins = pins, off = {}, filterRev = 0,
            toGeo = function(x, y) return 50.45 + y / 110574, 30.52 + x / k end,
            toLocal = function(lat, lon) return (lon - 30.52) * k, (lat - 50.45) * 110574 end,
            colour = function(r, g, b) return r * 65536 + g * 256 + b end}
          assert(mm.refresh(10, 0, 0, env))''')
        marks = lua.eval('mm.markers')
        n = marks.count()
        self.assertEqual(n, 3, 'the castle, the fuel station and the hotel; the kiosk is too minor, the far castle too far')
        self.assertEqual(marks.r[1], 6.5, 'the weightiest first and largest')
        brown = round(.55 * 255) * 65536 + round(.34 * 255) * 256 + round(.18 * 255)
        self.assertEqual(marks.colour[1], brown, 'in its group\'s colour')
        self.assertAlmostEqual(marks.x[1], .0005 * 111320 * math.cos(math.radians(50.45)), delta=.5)
        # nothing new for half a second on the spot; a move or the time takes them again
        self.assertFalse(lua.eval('mm.refresh(10.2, 5, 5, env)'))
        self.assertTrue(lua.eval('mm.refresh(10.2, 80, 0, env)'))
        self.assertTrue(lua.eval('mm.refresh(11, 80, 0, env)'))
        # a category switched off on the atlas leaves the minimap as well
        lua.execute("env.off.castle = true; env.filterRev = 1; mm.refresh(12, 0, 0, env)")
        self.assertEqual(marks.count(), 2)
        # a pack whose map data has no points: the streamed tiles' own, a network's point as well
        lua.execute('''
          env.off, env.filterRev = {}, 2
          index.reset()
          env.tiles = {a = {brandPOIs = {{kind = 'pin', cat = 'metro', x = 300, y = 40}, {kind = 'fuel', brand = 'wog', x = -200, y = 90},
            {kind = 'pin', cat = 'kiosk', x = 10, y = 10}, {kind = 'pin', cat = 'no such', x = 20, y = 20}}}}
          mm.refresh(13, 0, 0, env)''')
        self.assertEqual(marks.count(), 2, 'the metro and the fuel station; the kiosk is too minor')
        self.assertEqual((marks.x[1], marks.y[1]), (300, 40))
        self.assertEqual(lua.eval('mm.stats.indexed'), 0)
        lua.execute('env.tiles = nil; index.attach(nil, pins)')
        # drawn through the game's own circle marker, the destination with its edge pointer
        lua.execute('''
          drawn, pointer = {}, nil
          utils = {simpleCircle = function(pos, fill, rim, radius) drawn[#drawn + 1] = {pos.x, pos.y, fill, radius} end,
            simpleCircleWithEdgePointer = function(pos, fill, rim, radius) pointer = {pos.x, pos.y, fill, radius} end}
          assert(mm.draw({}, utils, {x = 900, y = -40}, 77) == 0, 'nothing while the wraps are off')
          ui_apps_minimap_vehicles = {drawPlayer = function() return .5 end}
          mm.install()
          count = mm.draw({}, utils, {x = 900, y = -40}, 77)''')
        self.assertEqual((lua.eval('count'), lua.eval('#drawn')), (2, 2))
        self.assertEqual(list(lua.eval('pointer').values()), [900, -40, 77, 8])


if __name__ == '__main__':
    unittest.main()
