"""Regression checks for the map widget. Lua checks require lupa (or out/test-tools)."""
import sys
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime


UK_LABELS = {'pick': 'Обрати інше місце', 'back': 'Повернутися до їзди', 'hide': 'Приховати', 'show': 'Показати мапу'}
EN_LABELS = {'pick': 'Pick another place', 'back': 'Back to driving', 'hide': 'Hide', 'show': 'Show map'}


def load_world(lua, src):
    root = Path(__file__).resolve().parents[1] / 'mod/lua'
    for name in ('quality', 'detail'):
        lua.globals()[name] = lua.execute((root / f'ge/extensions/e2r/{name}.lua').read_text(encoding='utf8'))
    lua.execute("local old=require; require=function(n) if n=='ge/extensions/e2r/quality' then return quality elseif n=='ge/extensions/e2r/detail' then return detail else return old(n) end end")
    return lua.execute(src)


class WidgetTests(unittest.TestCase):
    def test_map_ui_keeps_streaming(self):
        self.map_ui_flow('uk', UK_LABELS)

    def test_map_ui_in_english(self):
        # the UK and California packages: build_mod.py --lang en rewrites the LANG line
        self.map_ui_flow('en', EN_LABELS)

    def test_package_offers_its_own_buttons(self):
        lua = LuaRuntime()
        lua.execute('''
          ui_imgui = setmetatable({ArrayChar=function() return {} end}, {__index=function() return function() end end})
          require=function() return {} end
          hptimer=function() return {stopAndReset=function() return 1 end} end''')
        src = (Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/world.lua').read_text(encoding='utf8').replace('local NATIVE = true', 'local NATIVE = false')
        lua.globals().mod = load_world(lua, src)
        shown = lua.eval('''function(status)
          local function up(fn, name)
            for i=1,100 do local n,v=debug.getupvalue(fn,i); if n==name then return v end end
          end
          local side=up(up(up(mod.onUpdate,'drawWindow'),'drawPicker'),'drawSidebar')
          up(mod.tick,'S').status=status
          local inPackage, out = up(side,'presetInPackage'), {}
          for _, p in ipairs(up(side,'PRESETS')) do if inPackage(p) then out[#out+1]=p[1] end end
          return table.concat(out, ',')
        end''')
        # Wales' box overlaps Bristol and Liverpool; only Welsh buttons
        wales = shown(lua.table_from({'area': 'uk-wales', 'packageBox': lua.table_from([-5.4, 51.35, -2.6, 53.45])}))
        self.assertEqual(wales.split(','), ['Cardiff', 'Swansea', 'Snowdonia', 'Aberystwyth', 'Conwy', 'Brecon Beacons'])
        # the whole UK: every UK button
        whole = shown(lua.table_from({'area': 'united-kingdom', 'packageBox': lua.table_from([-8.75, 49.4192, 1.9, 61.0])}))
        self.assertIn('Bristol', whole)
        self.assertIn('Stornoway', whole)
        self.assertNotIn('Times Square', whole)
        # the Ukraine box holds Bucharest and Iasi; the Romania box, Chernivtsi
        ukraine = shown(lua.table_from({'area': 'ukraine', 'packageBox': lua.table_from([22.1, 44.3, 40.3, 52.4])}))
        self.assertIn('Чернівці', ukraine)
        self.assertNotIn('Bucharest', ukraine)
        romania = shown(lua.table_from({'area': 'romania', 'packageBox': lua.table_from([20.2, 43.6, 29.8, 48.3])}))
        self.assertEqual(romania.split(',')[0], 'Bucharest')
        self.assertNotIn('Чернівці', romania)
        # a package the buttons do not know (a dev extract): by the box
        other = shown(lua.table_from({'area': 'kyiv', 'packageBox': lua.table_from([30.2, 50.2, 30.8, 50.6])}))
        self.assertEqual(other.split(','), ['Оболонь', 'Поділ', 'Хрещатик', 'Печерськ', 'Голосіїв', 'Біличі', 'Ірпінь', 'Бровари'])

    def native_widget(self, basemap=True):
        """world.lua in native mode with the real planetMap, a fake native and the built base map."""
        import json
        root = Path(__file__).resolve().parents[1]
        base = root / 'out/basemap'
        found = sorted((d for d in base.glob('*') if (d / 'index.json').exists()), key=lambda d: int(d.name)) if base.exists() else []
        if basemap and not found:
            self.skipTest('no base map: run earthng/build_basemap.py')
        lua = LuaRuntime()
        files = {}
        if basemap:
            files['/earthng/planet/basemap/index.json'] = found[-1] / 'index.json'
            files['/earthng/planet/basemap/labels.json'] = found[-1] / 'labels.json'

        def read_json(path):
            return lua.table_from(json.loads(files[path].read_text(encoding='utf8')), recursive=True)
        lua.globals().py_exists = lambda path: path in files
        lua.globals().py_json = read_json
        lua.globals().planet_src = (root / 'mod/lua/ge/extensions/e2r/planetMap.lua').read_text(encoding='utf8')
        lua.globals().catalog_src = (root / 'mod/lua/ge/extensions/e2r/mapCatalog.lua').read_text(encoding='utf8')
        lua.globals().navigation_src = (root / 'mod/lua/ge/extensions/e2r/navigation.lua').read_text(encoding='utf8')
        lua.globals().navigator_src = (root / 'mod/lua/ge/extensions/e2r/navigator.lua').read_text(encoding='utf8')
        lua.globals().routing_src = (root / 'mod/lua/ge/extensions/e2r/routing.lua').read_text(encoding='utf8')
        lua.execute('''
          ui_imgui = setmetatable({ArrayChar=function(n) return require('ffi').new('char[?]', n) end,
            Button=function(label) return label == clicked end,
            Selectable1=function(label) return label == clicked end,
            GetIO=function() return {MouseWheel=0} end,
            GetMousePos=function() return {x=-100,y=-100} end,
            GetItemRectMin=function() return {x=0,y=0} end,
            IsItemHovered=function() return false end,
            IsMouseDown=function() return false end,
            CalcTextSize=function(t) return {x=7*#t,y=13} end,
            GetStyle=function() return {ItemSpacing={x=4}} end,
            ImVec2=function(x, y) return {x=x, y=y} end,
            GetFontSize=function() return 13 end,
            GetFont=function() return nil end,
            GetContentRegionAvailWidth=function() return 280 end,
            GetContentRegionAvail=function() return {x=1100, y=640} end,
            GetFrameHeightWithSpacing=function() return 26 end,
            WindowFlags_NoCollapse=1, WindowFlags_AlwaysAutoResize=2, WindowFlags_NoScrollbar=4,
            WindowFlags_NoScrollWithMouse=8},
            {__index=function() return function() end end})
          FS={fileExists=function(_, path) return py_exists(path) end}
          jsonReadFile=function(path) return py_json(path) end
          hptimer=function() return {stopAndReset=function() return 1 end, stop=function() return 1 end} end
          countries={
            {id='ukraine', title='Україна', available=true, landing={lat=50.45, lon=30.52}},
            {id='zanzibar', title='Zanzibar', available=true, landing={lat=-6.16, lon=39.19}}}
          status={countries=countries, errors={}, packageBox={22, -6.5, 40.3, 52.4},
            coverage={{30.0, 50.0, 30.6, 50.3}, {30.5, 50.2, 31.0, 50.6}, {39.1, -6.4, 39.6, -5.7}},
            regions={{country='ukraine', coverage={{22, 44.3, 40.3, 52.4}}}, {country='zanzibar', coverage={{39.1, -6.4, 39.6, -5.7}}}}}
          fakeNative={status=function() return status end, refresh=function() end,
            mapRoads=function() return {} end,
            sectionPlaces=function(regions)
              local places = {}
              if type(regions) ~= 'table' then return places end
              for _, region in ipairs(regions) do
                local at = type(region) == 'table' and region.section == true and region.landing
                if type(at) == 'table' and type(at.lat) == 'number' and type(at.lon) == 'number' then
                  local title = region.title or region.id
                  places[#places + 1] = {title, at.lat, at.lon, region.country, title}
                end
              end
              return places
            end,
            at=function(lat, lon)
              for _, r in ipairs(status.regions) do
                local c = r.coverage[1]
                if lon >= c[1] and lon <= c[3] and lat >= c[2] and lat <= c[4] then
                  for _, k in ipairs(countries) do if k.id == r.country then return k end end
                end
              end
            end}
          local realRequire = require
          require=function(name)
            if name == 'ge/extensions/e2r/native' then return fakeNative end
            if name == 'ge/extensions/e2r/planetMap' then return loadstring(planet_src)() end
            if name == 'ge/extensions/e2r/mapCatalog' then return loadstring(catalog_src)() end
            if name == 'ge/extensions/e2r/navigation' then return loadstring(navigation_src)() end
            if name == 'ge/extensions/e2r/navigator' then return loadstring(navigator_src)() end
            if name == 'ge/extensions/e2r/routing' then return loadstring(routing_src)() end
            if name == 'bit' then return realRequire('bit') end
            if name == 'ui/imguiUtils' then return {texObj=function(path) return {texId=1, path=path} end} end
            if name == 'ffi' then return realRequire('ffi') end
            return {}
          end
          function up(fn, name)
            for i=1,200 do
              local n,v=debug.getupvalue(fn,i)
              if not n then break end
              if n==name then return v end
            end
            error('missing upvalue '..name)
          end''')
        src = (root / 'mod/lua/ge/extensions/e2r/world.lua').read_text(encoding='utf8')
        lua.globals().mod = load_world(lua, src)
        lua.execute('''
          S=up(mod.tick,'S'); draw=up(mod.onUpdate,'drawWindow')
          picker=up(draw,'drawPicker'); side=up(picker,'drawSidebar'); drawMap=up(picker,'drawMap')
          S.status=status; S.coverage=status.coverage; S.state='pick'; S.now=10''')
        return lua

    def test_minimap_click_routes_there_and_draws_the_line(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import routing_format
        import test_routing
        lua = self.native_widget(basemap=False)
        lua.globals().blob = routing_format.encode(routing_format.graph(test_routing.grid()))
        lua.execute('''
          -- the grid of test_routing in a frame of 1e-5 degrees a metre
          fakeNative.localPoint = function(lat, lon) return lon * 1e5, lat * 1e5 end
          fakeNative.toGeo = function(x, y) return y / 1e5, x / 1e5 end
          fakeNative.routing = function() return '/r.bin', 'demo' end
          fakeNative.readBytes = function() return blob end
          car = {x = 0, y = 0}
          getPlayerVehicle = function() return nil end
          vec3 = vec3 or function(x, y, z) return {x = x, y = y, z = z} end
          local function set(fn, name, value)
            for i = 1, 200 do
              local n = debug.getupvalue(fn, i)
              if not n then break end
              if n == name then debug.setupvalue(fn, i, value); return end
            end
            error('missing upvalue ' .. name)
          end
          set(draw, 'focus', function() return car end)
          -- no base map here: the map's own picture is not what this test reads
          local planet = up(drawMap, 'planetMap')
          planet.draw, planet.drawLabels = function() end, function() end
          texts, lines, frame = {}, 0, 0
          ui_imgui.TextColored = function(_, t) texts[#texts + 1] = t end
          ui_imgui.Text = function(t) texts[#texts + 1] = t end
          ui_imgui.ImDrawList_AddLine = function() lines = lines + 1 end
          ui_imgui.IsItemHovered = function() return true end
          ui_imgui.GetMousePos = function() return {x = 180, y = 90} end   -- the minimap's centre
          ui_imgui.IsMouseClicked = function() return frame == 1 end
          ui_imgui.GetMouseDragDelta = function() return {x = 0, y = 0} end
          S.state, S.now, S.stream, S.pickerOpen = 'driving', 10, {tile = 500}, false
          S.center = {lat = .005, lon = .005}
          S.mini = nil
          frame = 1; draw()                  -- the press
          frame = 2; draw()                  -- the release: a click, not a drag
          for k = 1, 100 do mod.navigator.step(function() return car end, 10 + k * .016, 'uk') end
          texts, lines = {}, 0
          frame = 3; draw()''')
        texts = [lua.eval('texts')[k] for k in range(1, lua.eval('#texts') + 1)]
        self.assertTrue(any(t.startswith('До цілі') for t in texts), texts)
        self.assertTrue(any(t.startswith('Через ') for t in texts), texts)
        self.assertGreater(lua.eval('lines'), 4)
        dest = lua.eval('mod.navigator.destination()')
        self.assertAlmostEqual(dest.x, 500, delta=1)
        self.assertAlmostEqual(dest.y, 500, delta=1)
        lua.execute("clicked = 'Скасувати маршрут'; frame = 4; draw()")
        self.assertFalse(lua.eval('mod.navigator.active()'))

    def test_landing_zones_do_not_overlap(self):
        lua = self.native_widget(basemap=False)
        rects = lua.eval('up(drawMap, "mergedCoverage")(status.coverage)')
        rects = [tuple(r.values()) for r in rects.values()]
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                overlap = min(a[2], b[2]) - max(a[0], b[0]) > 1e-9 and min(a[3], b[3]) - max(a[1], b[1]) > 1e-9
                self.assertFalse(overlap, (a, b))
        area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects)
        # two Kyiv boxes overlapping by 0.1 x 0.1, and Zanzibar
        expected = 0.6 * 0.3 + 0.5 * 0.4 - 0.1 * 0.1 + 0.5 * 0.7  # (on the 0.005 grid already)
        self.assertAlmostEqual(area, expected, places=6)

    def test_picker_lists_packs_and_flies_to_one(self):
        lua = self.native_widget()
        lua.execute('S.fitAll=true; clicked=nil; draw()')
        self.assertEqual(lua.eval('S.zoom'), lua.eval('S.zoom'))   # the window draws without errors
        self.assertGreater(lua.eval('S.center.lat'), -7)          # both packs in view
        lua.execute("clicked='Zanzibar##pack_zanzibar'; draw()")
        self.assertEqual(lua.eval('S.selectedPack'), 'zanzibar')
        self.assertAlmostEqual(lua.eval('S.center.lat'), -6.05, places=2)
        self.assertGreaterEqual(lua.eval('S.zoom'), 8)
        # the selected pack lists its own presets, which land at the place
        lua.execute("clicked='Stone Town##preset1'; draw()")
        self.assertAlmostEqual(lua.eval('S.marker.lat'), -6.163, places=3)

    def test_search_finds_cities_in_any_case(self):
        lua = self.native_widget()
        planet = lua.eval("require('ge/extensions/e2r/planetMap')")
        self.assertEqual(planet.lower('КИЇВ Ґанок Єнакієве Іршава'), 'київ ґанок єнакієве іршава')
        lua.globals().planet = planet
        first = lua.eval("planet.search('київ', 'uk', 5)[1]")
        self.assertAlmostEqual(first.lat, 50.43, places=1)
        self.assertEqual(lua.eval("planet.search('LVIV', 'en', 5)[1].name"), 'Lviv')

    def test_stock_minimap_graph_updates_without_traffic_while_parked(self):
        lua = self.native_widget(basemap=False)
        lua.execute('''
          step=up(mod.tick,'navStep'); build=up(step,'navBuild')
          function replace(fn, name, value)
            for i=1,200 do local n=debug.getupvalue(fn,i)
              if n==name then debug.setupvalue(fn,i,value); return end
            end
            error('missing '..name)
          end
          car={x=0,y=0,z=0}
          replace(build,'focus',function() return car end)
          graph={nodes={},buildSerial=0}; resets=0; invalidations=0
          map={getMap=function() return graph end, reset=function(nodes)
            resets=resets+1; graph={nodes=nodes,buildSerial=resets} end}
          ui_apps_minimap_roads={reset=function() invalidations=invalidations+1 end}
          vec3=function(x,y,z) return {x=x,y=y,z=z} end
          table.clear=function(t) for k in pairs(t) do t[k]=nil end end
          S.stream={}; S.tiles={a={}}; S.nav={}; S.navPending={}
          S.navPending[1]={key='a',data={segments={{1,10,11,'1-1',50,4,1,0,0,0,100,0,0}}}}
          S.now=10; step()
          assert(resets==1 and invalidations==1 and graph.nodes.e2r_n10)
          local keep=graph.nodes
          S.navPending[1]={key='a',data={segments={{2,11,12,'1-1',50,4,1,100,0,0,200,0,0}}}}
          S.now=10.1; step(); assert(resets==1)
          S.now=12.1; step()
          assert(resets==2 and graph.nodes==keep and graph.nodes.e2r_n12)
          assert(invalidations==2)
          S.now=14.2; step(); assert(resets==2)
          S.tiles={}; S.navDirty=true; S.now=16.3; step()
          assert(resets==3 and next(graph.nodes)==nil)
        ''')

    def map_ui_flow(self, lang, labels):
        lua = LuaRuntime()
        lua.execute('''
          ui_imgui = setmetatable({ArrayChar=function() return {} end,
            Button=function(label) return label == clicked end,
            GetIO=function() return {MouseWheel=0} end,
            GetMousePos=function() return {x=0,y=0} end,
            GetItemRectMin=function() return {x=0,y=0} end,
            IsItemHovered=function() return false end,
            IsMouseDown=function() return false end,
            CalcTextSize=function() return {x=10,y=10} end,
            GetStyle=function() return {ItemSpacing={x=4}} end,
            ImVec2=function(x, y) return {x=x, y=y} end,
            GetContentRegionAvailWidth=function() return 360 end,
            GetContentRegionAvail=function() return {x=1100, y=640} end,
            GetFrameHeightWithSpacing=function() return 26 end,
            WindowFlags_NoCollapse=1, WindowFlags_AlwaysAutoResize=2, WindowFlags_NoScrollbar=4,
            WindowFlags_NoScrollWithMouse=8},
            {__index=function() return function() end end})
          require=function() return {} end
          FS={fileExists=function() return false end}
          maptileRequests=0
          jsonWriteFile=function(path, tbl) if tbl.type=='maptiles' then maptileRequests=maptileRequests+1 end end
          hptimer=function() return {stopAndReset=function() return 1 end} end
          function up(fn, name, replacement)
            for i=1,100 do
              local n,v=debug.getupvalue(fn,i)
              if not n then break end
              if n==name then
                if replacement then debug.setupvalue(fn,i,replacement) end
                return v
              end
            end
            error('missing upvalue '..name)
          end
        ''')
        src = (Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/world.lua').read_text(encoding='utf8').replace('local NATIVE = true', 'local NATIVE = false')
        mod = load_world(lua, src.replace("local LANG = 'uk'", f"local LANG = '{lang}'"))
        lua.globals().mod = mod
        for key, label in labels.items():
            lua.globals()['label_' + key] = label
        lua.execute('''
          S=up(mod.tick,'S')
          draw=up(mod.onUpdate,'drawWindow')
          S.state='driving'; S.now=10; S.stream={}; S.viewDirty=true
          test=up(mod.onUpdate,'test')
          up(mod.tick,'test',{skipMap=true,manual=true})
          up(mod.tick,'placeSun',function() end)
          up(mod.tick,'readStatus',function() end)
          up(mod.tick,'replayStep',function() end)
          poses=0; tiles=0; collision=0
          up(mod.tick,'writePose',function() poses=poses+1 end)
          up(mod.tick,'updateTiles',function() tiles=tiles+1 end)
          up(mod.tick,'updateCollision',function() collision=collision+1; return true end)
          up(draw,'focus',function() return nil end)
          clicked=label_pick; draw()
          assert(S.state=='driving' and S.pickerOpen)
          mod.tick(0.016)
          assert(poses==1 and tiles==1 and collision==1)
          -- the map asks the companion for its OSM tiles (none are on disk here)
          assert(maptileRequests==1)
          clicked=label_back; draw()
          assert(S.state=='driving' and not S.pickerOpen)
          clicked=label_hide; draw()
          assert(S.widgetHidden)
          local asked=maptileRequests
          mod.tick(0.016); draw()
          assert(poses==2 and tiles==2 and maptileRequests==asked)  -- a hidden map asks nothing
          clicked=label_show; draw()
          assert(not S.widgetHidden and S.state=='driving')
          mod.tick(0.016)
          assert(poses==3)
          clicked=nil; S.now=30; draw()
          assert(maptileRequests>asked)  -- shown again: asks again (retry after MAP_RETRY)
        ''')



if __name__ == '__main__':
    unittest.main()
