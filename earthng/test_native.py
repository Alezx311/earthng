"""LuaJIT tests for mounted source discovery and budgeted native generation.

Run with: python -m unittest discover -s earthng -p test_native.py
"""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
from lupa.luajit21 import LuaRuntime

sys.path.insert(0, str(ROOT / 'earthng'))
import country_format as binary


def fixture(size=4):
    base = '/earthng/countries/demo/'
    region_path = base + 'regions/sample.json'
    geo = [0, 0, 20, 40, .00001, .000004, -.000003, .00001]
    country = dict(schemaVersion=1, kind='earthng-country', id='demo', title='Demo', version='1',
                   runtime='native', sourceFormat='earthng-features-v1', coverage=[[19, 39, 21, 41]],
                   regions=[dict(id='sample', manifest=region_path, coverage=[[19, 39, 21, 41]])])
    region = dict(schemaVersion=1, id='sample', runtime='lua', tileSize=500, cellSize=1000,
                  geo=geo, bounds=[19, 39, 21, 41], cells={})
    files = {base + 'manifest.json': country, region_path: region}
    for i in range(size):
        for j in range(size):
            bounds = [i * 1000, j * 1000, (i + 1) * 1000, (j + 1) * 1000]
            path = base + f'regions/sample/cells/{i}_{j}.json'
            region['cells'][f'{i}_{j}'] = dict(path=path, bounds=bounds)
            files[path] = dict(roads=[], junctions=[], buildings=[], areas=[], lines=[], points=[],
                               terrain=dict(rect=bounds, nx=2, ny=2, heights=[0] * 4))
    return files


def geographic(x, y):
    return 40 - .000003 * x + .00001 * y, 20 + .00001 * x + .000004 * y


class NativeTests(unittest.TestCase):
    def test_quality_invalidates_prepared_density_but_distance_keeps_ready_tiles(self):
        _, mod, cv = self.make()
        lat, lon = geographic(1750, 1750)
        mod.land(cv(dict(seq=1, lat=lat, lon=lon)))
        self.pump(mod)
        ready = set(mod.status().stream.ready.keys())
        self.assertTrue(ready)
        tune = dict(mod.setTune(cv({})))
        tune['grassM'] = 45
        tune['farM'] = 1800
        mod.setTune(cv(tune))
        self.assertEqual(set(mod.status().stream.ready.keys()), ready)
        tune['maxTrees'] = 700
        mod.setTune(cv(tune))
        self.assertFalse(set(mod.status().stream.ready.keys()))
        self.assertFalse(set(mod.status().stream.scenes.keys()))
        for _ in range(200):
            mod.update(.016, 2)
        self.assertTrue(set(mod.status().stream.ready.keys()))

    def make(self, files=None, real_generator=False):
        lua = LuaRuntime()

        def convert(value):
            if isinstance(value, dict):
                return lua.table_from({k: convert(v) for k, v in value.items()})
            if isinstance(value, (list, tuple)):
                return lua.table_from([convert(v) for v in value])
            return value

        files = deepcopy(files if files is not None else fixture())
        lua.globals().files = convert(files)
        lua.globals().manifestPaths = convert([p for p in files if p.endswith(('/manifest.json', '/section.json'))])
        lua.execute('''
          FS={fileExists=function(_,p) return files[p]~=nil end,
              findFiles=function(_, root, name)
                local found = {}
                for _, p in ipairs(manifestPaths) do
                  if p:sub(-#name - 1) == '/' .. name then found[#found + 1] = p end
                end
                return found
              end}
          jsonReadFile=function(p) return files[p] end
          io.open=function(p, mode)
            local data = files[p]
            if type(data) ~= 'string' then return nil end
            return {read=function() return data end, close=function() end}
          end
          jsonWriteFile=function() error('native provider must not write files') end
          hptimer=function() local elapsed=0; return {stop=function() elapsed=elapsed+0.7; return elapsed end} end
          buildCalls=0; fakeTriangles=0; fakeFarTriangles=0
          stubGenerator={build=function(cells,i,j,options)
            buildCalls=buildCalls+1
            for n=1,5 do options.pause() end
            local t=options.tileSize
            local road={items=fakeTriangles>0 and {{triangles=fakeTriangles,meshes={}}} or {},mats={'earthng_ground'},drivable=true,
              spawn={pos={(i+0.5)*t,(j+0.5)*t,5},dir={0,1,0}}}
            local far=options.far and {items=fakeFarTriangles>0 and {{triangles=fakeFarTriangles,meshes={}}} or {},mats={}} or nil
            return road,{items={},mats={}},far,{segments={{'segment'}}}
          end}
        ''')
        if real_generator:
            lua.globals().stubGenerator = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/generator.lua').read_text(encoding='utf8'))
        lua.globals().countries = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/countries.lua').read_text(encoding='utf8'))
        coordinate_path = ROOT / 'mod/lua/ge/extensions/e2r/coordinates.lua'
        lua.globals().coordinates = lua.execute(coordinate_path.read_text(encoding='utf8')) if coordinate_path.exists() else lua.table()
        lua.globals().cellformat = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/cellformat.lua').read_text(encoding='utf8'))
        lua.execute("require=function(name) if name=='ge/extensions/e2r/countries' then return countries elseif name=='ge/extensions/e2r/coordinates' then return coordinates elseif name=='ge/extensions/e2r/cellformat' then return cellformat else return stubGenerator end end")
        lua.globals().quality = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/quality.lua').read_text(encoding='utf8'))
        lua.execute("local old=require; require=function(n) if n=='ge/extensions/e2r/quality' then return quality else return old(n) end end")
        mod = lua.execute((ROOT / 'mod/lua/ge/extensions/e2r/native.lua').read_text(encoding='utf8'))
        return lua, mod, convert

    def pump(self, mod, count=400):
        for _ in range(count):
            mod.update(.016, 2)
            job = mod.status().job
            if job and job.state != 'working':
                return job
        self.fail('native landing did not finish')

    def test_section_places_are_counties_not_grid_tiles(self):
        _, mod, cv = self.make()
        places = mod.sectionPlaces(cv([
            dict(id='e0300-n5040', country='ukraine', title='Україна', landing=dict(lat=50.4, lon=30.3)),
            dict(id='e0310-n5050', country='ukraine', title='Україна', landing=dict(lat=50.5, lon=30.5)),
            dict(id='lviv', country='ukraine', title='Львів', section=True, landing=dict(lat=49.84, lon=24.03)),
            dict(id='harju', country='estonia', title='Harju', section=True, landing=dict(lat=59.4, lon=24.7)),
            dict(id='noland', country='estonia', title='Saare', section=True),
        ]))
        got = [(places[i][1], places[i][2], places[i][3], places[i][4]) for i in range(1, len(places) + 1)]
        self.assertEqual(got, [('Львів', 49.84, 24.03, 'ukraine'), ('Harju', 59.4, 24.7, 'estonia')])
        self.assertEqual(len(mod.sectionPlaces(None)), 0)

    def test_landing_uses_budgeted_generation_and_direct_manifests(self):
        lua, mod, cv = self.make()
        self.assertEqual(mod.refresh().countryCount, 1)
        region = mod.status().regions[1]   # the map lists a country's regions at their landings
        self.assertEqual((region.landing.lat, region.landing.lon), (mod.status().countries[1].landing.lat,
                                                                    mod.status().countries[1].landing.lon))
        lat, lon = geographic(1750, 1750)
        job = mod.land(cv(dict(seq=7, lat=lat, lon=lon)))
        self.assertEqual(job.state, 'working')
        self.assertEqual(lua.globals().buildCalls, 0)
        mod.update(.016, .5)
        self.assertEqual(job.state, 'working')
        job = self.pump(mod)
        self.assertEqual(job.state, 'ready')
        self.assertEqual(job.seq, 7)
        self.assertEqual(job.country, 'demo')
        self.assertEqual(job.manifest.spawn.yaw, 0)
        self.assertIsNone(job.horizonZ)
        self.assertTrue(job.horizonDem)
        self.assertGreaterEqual(mod.status().stream.readyCount, 9)
        key = f'{job.tile[1]}_{job.tile[2]}'
        self.assertEqual(mod.manifest(key, 'road').materials, '/earthng/planet/materials.json')
        self.assertEqual(mod.manifest(key, 'road').navSegments[1][1], 'segment')
        self.assertIsNotNone(mod.manifest(key, 'scene'))
        self.assertIsNone(mod.manifest(key, 'far'))

    def test_affine_inverse_and_safe_source_coverage(self):
        _, mod, _ = self.make()
        mod.refresh()
        lat, lon = geographic(1250, 1750)
        country, region, x, y, _ = mod.at(lat, lon)
        self.assertEqual((country.id, region.id), ('demo', 'sample'))
        self.assertAlmostEqual(x, 1250, places=5)
        self.assertAlmostEqual(y, 1750, places=5)
        # Both points are inside the broad geographic box, but lack source cells
        # or the complete 1 km startup neighbourhood.
        self.assertIsNone(mod.at(*geographic(-100, 2000)))
        self.assertIsNone(mod.at(*geographic(250, 2000)))
        self.assertIsNone(mod.at(float('nan'), lon))

    def test_exact_projection_controls_selection_and_car_affine(self):
        files = fixture()
        files['/earthng/countries/demo/regions/sample.json']['frame'] = {'testProjection': True}
        lua, mod, cv = self.make(files)
        # Deliberately differ from fixture.geo: exact frame coordinates take
        # precedence, while legacy sources without frame retain affine support.
        lua.execute('''coordinates.frame=function(spec)
          if not spec or not spec.testProjection then return nil end
          return {
            localPoint=function(lat,lon) return (lon-20)*100000,(lat-40)*100000 end,
            geographic=function(x,y) return 20+x/100000,40+y/100000 end,
            affineAt=function(x,y) return {x,y,20+x/100000,40+y/100000,.00001,0,0,.00001} end}
        end''')
        mod.refresh()
        _, _, x, y, _ = mod.at(40.0175, 20.0175)
        self.assertAlmostEqual(x, 1750)
        self.assertAlmostEqual(y, 1750)
        mod.land(cv(dict(seq=1, lat=40.0175, lon=20.0175)))
        self.assertAlmostEqual(mod.status().stream.geo[1], 1750)
        self.assertAlmostEqual(mod.status().stream.geo[2], 1750)
        mod.pose(cv(dict(x=2200, y=2100, vx=0, vy=0)))
        geo = mod.status().stream.geo
        self.assertEqual((geo[1], geo[2]), (2200, 2100))
        self.assertAlmostEqual(geo[3], 20.022)
        self.assertAlmostEqual(geo[4], 40.021)

    def test_missing_or_escaping_cell_disables_country(self):
        for invalid in ('missing', 'traversal'):
            files = fixture()
            path = files['/earthng/countries/demo/regions/sample.json']['cells']['1_1']['path']
            if invalid == 'missing':
                del files[path]
            else:
                files['/earthng/countries/demo/regions/sample.json']['cells']['1_1']['path'] = '/earthng/countries/demo/../other.json'
            with self.subTest(invalid=invalid):
                _, mod, _ = self.make(files)
                st = mod.refresh()
                self.assertEqual(st.countryCount, 0)
                self.assertFalse(st.countries[1].available)
                self.assertGreater(len(st.errors), 0)
                self.assertIsNone(mod.at(*geographic(1750, 1750)))

    def test_invalid_elevation_becomes_visible_job_error(self):
        files = fixture()
        for path, value in files.items():
            if '/cells/' in path:
                value['terrain']['heights'] = [0]
        _, mod, cv = self.make(files)
        mod.land(cv(dict(seq=2, lat=geographic(1750, 1750)[0], lon=geographic(1750, 1750)[1])))
        job = self.pump(mod)
        self.assertEqual(job.state, 'error')
        self.assertIn('elevation', job.message)

    def test_pose_preserves_geo_and_refresh_discards_old_generation(self):
        _, mod, cv = self.make()
        lat, lon = geographic(1750, 1750)
        mod.land(cv(dict(seq=1, lat=lat, lon=lon)))
        self.pump(mod)
        mod.pose(cv(dict(x=2300, y=2100, vx=25, vy=0, region='sample')))
        st = mod.status()
        want_lat, want_lon = geographic(2300, 2100)
        self.assertAlmostEqual(st.stream.car[1], want_lon)
        self.assertAlmostEqual(st.stream.car[2], want_lat)
        self.assertGreater(st.heartbeat, 0)
        mod.refresh()
        self.assertIsNone(mod.status().stream)
        self.assertIsNone(mod.status().job)
        self.assertIsNone(mod.manifest('3_3', 'road'))

    def test_no_coverage_cannot_start_generator(self):
        lua, mod, cv = self.make()
        job = mod.land(cv(dict(seq=1, lat=0, lon=0)))
        self.assertEqual(job.state, 'error')
        mod.update(.016, 2)
        self.assertEqual(lua.globals().buildCalls, 0)

    def test_source_cells_generate_playable_meshes_without_companion(self):
        files = fixture()
        for path, cell in files.items():
            if '/cells/' in path:
                cell['roads'] = [dict(id='main', nodes=[1, 2], width=8,
                                      points=[[0, 1750, 0], [4000, 1750, 20]],
                                      tags={'highway': 'residential', 'sidewalk': 'no'})]
        _, mod, cv = self.make(files, real_generator=True)
        lat, lon = geographic(1750, 1750)
        mod.land(cv(dict(seq=3, lat=lat, lon=lon)))
        job = self.pump(mod, count=4000)
        self.assertEqual(job.state, 'ready')
        self.assertGreater(job.manifest.triangles, 0)
        self.assertIsNotNone(job.manifest['items'][1].meshes)
        self.assertGreater(len(job.manifest.navSegments), 0)
        self.assertAlmostEqual(job.manifest.spawn.pos[3], 8.85)

    def test_no_road_within_reach_lands_on_the_ground_at_the_point(self):
        # a summit or a desert: no road in the landing square, the car stands on the DEM there
        _, mod, cv = self.make(real_generator=True)
        lat, lon = geographic(1750, 1750)
        mod.land(cv(dict(seq=4, lat=lat, lon=lon)))
        job = self.pump(mod, count=4000)
        self.assertEqual(job.state, 'ready')
        self.assertTrue(job.manifest.offRoad)
        self.assertFalse(job.manifest.drivable)
        self.assertAlmostEqual(job.manifest.spawn.pos[1], 1750, delta=1)
        self.assertAlmostEqual(job.manifest.spawn.pos[2], 1750, delta=1)

    def test_invalid_geometry_is_a_visible_job_error(self):
        files = fixture()
        for path, cell in files.items():
            if '/cells/' in path:
                cell['roads'] = [dict(id='bad', points=[[float('inf'), 1750, 0], [2000, 1750, 0]])]
        _, mod, cv = self.make(files, real_generator=True)
        lat, lon = geographic(1750, 1750)
        mod.land(cv(dict(seq=4, lat=lat, lon=lon)))
        job = self.pump(mod)
        self.assertEqual(job.state, 'error')
        self.assertIn('source geometry', job.message)

    def test_geometry_cache_is_bounded_and_does_not_rebuild_evicted_tiles(self):
        lua, mod, cv = self.make(fixture(6))
        lua.globals().fakeTriangles = 20000
        lat, lon = geographic(1750, 1750)
        mod.land(cv(dict(seq=4, lat=lat, lon=lon)))
        self.assertEqual(self.pump(mod).state, 'ready')
        # The renderer still needs all startup tiles during warm-up/descent.
        # Its first driving pose is the explicit release of that working set.
        self.assertGreaterEqual(mod.status().stream.readyCount, 9)
        self.assertTrue(mod.status().stream.cacheOverBudget)
        for _ in range(30):
            mod.update(.016, 2)
        self.assertGreaterEqual(mod.status().stream.readyCount, 9)
        mod.pose(cv(dict(x=1750, y=1750, vx=0, vy=0, state='driving')))
        for _ in range(1000):
            mod.update(.016, 2)
        stream = mod.status().stream
        self.assertLessEqual(stream.cachedTiles, stream.cacheLimits.tiles)
        self.assertLessEqual(stream.cachedCells, stream.cacheLimits.cells)
        self.assertLessEqual(stream.cachedTriangles, 80000)
        self.assertFalse(stream.cacheOverBudget)
        self.assertGreater(len(list(stream.far.keys())), 0)
        built = stream.built
        for _ in range(100):
            mod.update(.016, 2)
        self.assertEqual(stream.built, built)
        self.assertLess(built, 150)

    def test_tile_cache_holds_the_whole_oasis_ring(self):
        # 1.4 km near and 4 km far want ~230 tiles: over the old fixed 160 the far ring evicted
        # itself, and a parked camera kept the holes (a ridge floating over Innsbruck)
        lua, mod, cv = self.make(fixture(20))
        lua.globals().fakeTriangles = 10
        tune = dict(mod.setTune(cv({})))
        tune.update(nearM=1400, farM=4000)
        mod.setTune(cv(tune))
        lat, lon = geographic(10000, 10000)
        mod.land(cv(dict(seq=7, lat=lat, lon=lon)))
        self.assertEqual(self.pump(mod).state, 'ready')
        mod.pose(cv(dict(x=10000, y=10000, vx=0, vy=0, state='driving')))
        for _ in range(4000):
            mod.update(.016, 8)
        stream = mod.status().stream
        tiles = [k for k in stream.wanted.keys() if not str(k).startswith('h')]
        self.assertGreater(len(tiles), 160)
        self.assertGreaterEqual(stream.cacheLimits.tiles, len(tiles))
        self.assertEqual(stream.queued, 0)

    def test_far_layers_left_behind_do_not_hold_the_new_ring(self):
        # far builds wait while far geometry the renderer has not taken fills half the budget;
        # layers a camera jump left behind are never taken and must not count (Bergisel view)
        lua, mod, cv = self.make(fixture(24))
        lua.globals().fakeFarTriangles = 15000
        lat, lon = geographic(5000, 5000)
        mod.land(cv(dict(seq=8, lat=lat, lon=lon)))
        self.assertEqual(self.pump(mod).state, 'ready')
        mod.pose(cv(dict(x=5000, y=5000, vx=0, vy=0, state='driving')))
        for _ in range(500):
            mod.update(.016, 8)          # nobody takes these far layers
        self.assertGreater(len(list(mod.status().stream.far.keys())), 0)
        mod.pose(cv(dict(x=17000, y=17000, vx=0, vy=0, state='driving')))
        for _ in range(3000):
            mod.update(.016, 8)
            for key in list(mod.status().stream.far.keys()):
                i, j = (int(v) for v in str(key).split('_'))
                # the renderer takes the far layers of its ring (world.lua farLoadR), not those behind
                if ((i + .5) * 500 - 17000) ** 2 + ((j + .5) * 500 - 17000) ** 2 <= 4500 ** 2:
                    mod.manifest(key, 'far')
        self.assertEqual(mod.status().stream.queued, 0)

    def test_geometry_budget_keeps_delivered_far_layers(self):
        # the far ring is built, taken and released; then near tiles are rebuilt with geometry
        # nobody takes yet, over the budget. Evicting the delivered far layers freed nothing and
        # dropped the ring's bookkeeping (rebuilt at the next epoch while still on screen).
        lua, mod, cv = self.make(fixture(20))
        lat, lon = geographic(10000, 10000)
        mod.land(cv(dict(seq=9, lat=lat, lon=lon)))
        self.assertEqual(self.pump(mod).state, 'ready')
        mod.pose(cv(dict(x=10000, y=10000, vx=0, vy=0, state='driving')))

        def run(frames):
            for _ in range(frames):
                mod.update(.016, 8)
                for key in list(mod.status().stream.far.keys()):
                    if mod.manifest(key, 'far') is not None:
                        mod.release(key, 'far')
        run(1500)
        stream = mod.status().stream
        far_wanted = [k for k, p in stream.wanted.items() if not str(k).startswith('h') and p >= 1e6]
        self.assertGreater(len(far_wanted), 40)
        self.assertGreaterEqual(len(list(stream.far.keys())), len(far_wanted))
        lua.globals().fakeTriangles = 30000
        for key in [k for k, p in stream.wanted.items() if not str(k).startswith('h') and p < 1e6]:
            mod.unload(key)
        run(1500)
        stream = mod.status().stream
        self.assertLessEqual(stream.cachedTriangles, 80000)
        self.assertGreaterEqual(len(list(stream.far.keys())), len(far_wanted))

    def test_gpu_release_drops_arrays_and_unload_regenerates(self):
        lua, mod, cv = self.make()
        lua.globals().fakeTriangles = 1000
        lat, lon = geographic(1750, 1750)
        mod.land(cv(dict(seq=5, lat=lat, lon=lon)))
        job = self.pump(mod)
        key = f'{job.tile[1]}_{job.tile[2]}'
        road = mod.manifest(key, 'road')
        before = mod.status().stream.cachedTriangles
        self.assertTrue(mod.release(key, 'road'))
        # delivered: the item tables go, the count stays (the renderer's collision check)
        self.assertIsNone(road['items'][1])
        self.assertGreaterEqual(road.itemCount, 1)
        self.assertIsNotNone(road.spawn)
        self.assertEqual(road.navSegments[1][1], 'segment')
        self.assertTrue(mod.status().stream.ready[key])
        self.assertEqual(mod.status().stream.cachedTriangles, before - 1000)
        scene = mod.manifest(key, 'scene')
        scene['items'][1] = cv(dict(kind='proc', decor=True, meshes=[dict(verts=[])], triangles=1))
        self.assertTrue(mod.release(key, 'scene'))
        self.assertIsNone(scene['items'][1])
        self.assertGreaterEqual(scene.itemCount, 1)
        self.assertTrue(mod.unload(key))
        self.assertIsNone(mod.status().stream.ready[key])
        self.assertIsNone(mod.status().stream.scenes[key])
        self.assertIsNone(mod.manifest(key, 'road'))
        for _ in range(100):
            mod.update(.016, 2)
            if mod.manifest(key, 'road') is not None:
                break
        self.assertIsNotNone(mod.manifest(key, 'road')['items'][1].meshes)

    def test_taken_manifests_are_neither_evicted_nor_rebuilt_until_released(self):
        # A layer the renderer has taken is queued for spawning there. Evicting it freed nothing
        # and the tile was built again (92 rebuilds in a 10 km replay, native-replay-03).
        lua, mod, cv = self.make()
        lua.globals().fakeTriangles = 20000
        lat, lon = geographic(1750, 1750)
        mod.land(cv(dict(seq=6, lat=lat, lon=lon)))
        self.pump(mod)
        held = {key: mod.manifest(key, 'road') for key in mod.status().stream.ready.keys()}
        mod.pose(cv(dict(x=1750, y=1750, state='driving')))
        for _ in range(200):
            mod.update(.016, 2)
        stream = mod.status().stream
        self.assertEqual(stream.rebuilds, 0)
        same = lua.eval('rawequal')
        for key, manifest in held.items():
            self.assertTrue(same(mod.manifest(key, 'road'), manifest))
        key = next(iter(held))
        self.assertIsNotNone(held[key]['items'][1].meshes)
        self.assertTrue(mod.release(key, 'road'))
        self.assertIsNone(held[key]['items'][1])



def fixture_v2(size=4, roads=False, landing=(1750, 1750)):
    """The same demo region in earthng-features-v2: binary 8 x 8 cell blocks."""
    base = '/earthng/countries/demo/'
    region_path = base + 'regions/sample.json'
    files = fixture(1)
    country = files[base + 'manifest.json']
    country['sourceFormat'] = 'earthng-features-v2'
    blocks, payloads = {}, {}
    for i in range(size):
        for j in range(size):
            bounds = [i * 1000, j * 1000, (i + 1) * 1000, (j + 1) * 1000]
            cell = dict(roads=[], junctions=[], buildings=[], areas=[], lines=[], points=[],
                        terrain=dict(rect=bounds, nx=2, ny=2, heights=[0, 1.5, -2.25, 3]))
            if roads:
                cell['roads'] = [dict(id='main', nodes=['1', '2'], width=8,
                                      points=[[0, 1750, 0], [4000, 1750, 20]],
                                      tags={'highway': 'residential', 'sidewalk': 'no'})]
            payloads.setdefault((i // 8, j // 8), {})[binary.slot(i, j)] = binary.encode_cell(cell, bounds[:2])
    for (bi, bj), cells in payloads.items():
        data, mask = binary.encode_block(cells)
        path = base + f'regions/sample/blocks/{bi}_{bj}.bin'
        files[path] = data
        blocks[f'{bi}_{bj}'] = dict(path=path, mask=mask)
    files[region_path] = dict(schemaVersion=2, id='sample', runtime='lua', sourceFormat='earthng-features-v2',
                              tileSize=500, cellSize=1000, blockCells=8, geo=files[region_path]['geo'],
                              bounds=[19, 39, 21, 41], coverage=[[19, 39, 21, 41]], landing=list(landing),
                              blocks=blocks)
    for path in [p for p in files if '/cells/' in p]:
        del files[path]
    return files


class NativeV2Tests(NativeTests.__base__):
    make = NativeTests.make
    pump = NativeTests.pump

    def test_lua_decoder_matches_reference_decoder(self):
        lua, _, _ = self.make()
        cell = dict(roads=[dict(id='w1', nodes=['9007199254740993', 'b'], width=7.25, tags={'highway': 'primary', 'name': 'Вулиця'},
                                points=[[1000.004, 2000.5, 151.237], [1999.99, -3.5, -12.01]])],
                    junctions=[dict(id='j:0', height=50.5, rings=[[[1, 2, 3], [4, 5, 6], [7, 8, 9]]])],
                    buildings=[dict(id='b:0', kind='building', height=12, minHeight=3, tags={'building': 'yes'},
                                    rings=[[[0, 0, 1], [10, 0, 1], [10, 10, 1]], [[2, 2, 1], [3, 2, 1], [3, 3, 1]]])],
                    areas=[dict(id='a:0', kind='water', tags={}, rings=[[[0, 0, 0], [5, 0, 0], [5, 5, 0]]])],
                    lines=[dict(id='l:0', kind='fence', tags={'barrier': 'fence'}, points=[[1, 1, 1], [2, 2, 2]])],
                    points=[dict(id='p:0', kind='stop', tags={'highway': 'bus_stop'}, pos=[1000, 20, 50.4])],
                    terrain=dict(rect=[1000, 0, 2000, 1000], nx=2, ny=3, heights=[1, 2.04, 3, -4, 5, 6.66]))
        data, _ = binary.encode_block({binary.slot(1, 0): binary.encode_cell(cell, (1000, 0))})
        expected = binary.decode_cell(data, (1000, 0), [1000, 0, 2000, 1000], *binary.decode_block(data)[1])
        lua.globals().blockData = data
        got = lua.execute('''local slots = cellformat.block(blockData)
          local r = slots[1]
          return cellformat.cell(blockData, r[1], r[2], 1000, 0, {1000, 0, 2000, 1000})''')

        def plain(value):
            if hasattr(value, 'items') and not isinstance(value, dict):
                items = dict(value.items())
                if items and all(isinstance(k, int) for k in items):
                    return [plain(items[k]) for k in sorted(items)]
                return {k: plain(v) for k, v in items.items()}
            if isinstance(value, bytes):
                return value.decode('utf8')
            return value

        got = plain(got)
        for kind in binary.KINDS:
            for feature in got[kind]:
                feature.setdefault('tags', {}) if kind != 'junctions' else None
        self.assertEqual(got, expected)
        lua.globals().blockData = data[:-1]
        with self.assertRaises(Exception):
            lua.execute('cellformat.block(blockData)')

    def test_v2_region_lands_without_enumerating_cells(self):
        lua, mod, cv = self.make(fixture_v2())
        st = mod.refresh()
        self.assertEqual(st.countryCount, 1)
        lat, lon = geographic(1750, 1750)
        self.assertAlmostEqual(st.countries[1].landing.lat, lat)
        self.assertAlmostEqual(st.countries[1].landing.lon, lon)
        self.assertIsNotNone(mod.at(lat, lon))
        self.assertIsNone(mod.at(*geographic(250, 2000)))  # the startup square leaves the cells
        lua.execute('''local build = stubGenerator.build
          stubGenerator.build = function(cells, ...) lastCells = cells; return build(cells, ...) end''')
        mod.land(cv(dict(seq=1, lat=lat, lon=lon)))
        job = self.pump(mod)
        self.assertEqual(job.state, 'ready')
        terrain = lua.globals().lastCells[1].terrain
        self.assertEqual((terrain.nx, terrain.ny, terrain.heights[3]), (2, 2, -2.2))  # decimetres

    def test_v2_cells_generate_meshes_with_the_real_generator(self):
        _, mod, cv = self.make(fixture_v2(roads=True), real_generator=True)
        lat, lon = geographic(1750, 1750)
        mod.land(cv(dict(seq=3, lat=lat, lon=lon)))
        job = self.pump(mod, count=4000)
        self.assertEqual(job.state, 'ready')
        self.assertGreater(job.manifest.triangles, 0)
        self.assertGreater(len(job.manifest.navSegments), 0)
        self.assertAlmostEqual(job.manifest.spawn.pos[3], 8.85)

    def test_map_streets_come_from_blocks_before_landing(self):
        _, mod, cv = self.make(fixture_v2(roads=True))
        mod.refresh()
        s, w = geographic(0, 0)
        n, e = geographic(4000, 4000)
        view = dict(w=min(w, e) - .01, s=min(s, n) - .01, e=max(w, e) + .01, n=max(s, n) + .01)
        lines = []
        for _ in range(50):
            got = mod.mapRoads(cv(view), 50)
            lines = [line for block in got.values() for line in block.values()]
            if lines:
                break
        self.assertEqual(len(lines), 1)  # one road, though all 16 cells hold it
        self.assertEqual(lines[0].rank, 2)
        geo = list(lines[0].geo.values())
        self.assertAlmostEqual(geo[0], geographic(0, 1750)[0], places=6)
        self.assertAlmostEqual(geo[1], geographic(0, 1750)[1], places=6)
        self.assertAlmostEqual(geo[-2], geographic(4000, 1750)[0], places=6)
        far = dict(w=view['w'] - 40, s=view['s'] - 20, e=view['e'] + 40, n=view['n'] + 20)
        self.assertEqual(len(mod.mapRoads(cv(far), 50)), 0)  # zoomed far out: no streets, no loading

    def test_v2_bad_landing_or_block_paths_disable_region(self):
        for name, change in (('landing outside', lambda f: f['/earthng/countries/demo/regions/sample.json'].update(landing=[250, 2000])),
                             ('escaping block', lambda f: next(iter(f['/earthng/countries/demo/regions/sample.json']['blocks'].values())).update(path='/earthng/countries/demo/../x.bin')),
                             ('bad mask', lambda f: next(iter(f['/earthng/countries/demo/regions/sample.json']['blocks'].values())).update(mask='zz')),
                             ('missing block', lambda f: f.pop('/earthng/countries/demo/regions/sample/blocks/0_0.bin'))):
            files = fixture_v2()
            change(files)
            with self.subTest(name):
                _, mod, _ = self.make(files)
                st = mod.refresh()
                self.assertEqual(st.countryCount, 0)
                self.assertGreater(len(st.errors), 0)

    def test_v2_corrupt_block_is_a_visible_job_error(self):
        files = fixture_v2()
        path = '/earthng/countries/demo/regions/sample/blocks/0_0.bin'
        files[path] = files[path][:-5]
        _, mod, cv = self.make(files)
        lat, lon = geographic(1750, 1750)
        mod.land(cv(dict(seq=2, lat=lat, lon=lon)))
        job = self.pump(mod)
        self.assertEqual(job.state, 'error')
        self.assertIn('source block', job.message)

    def test_author_landing_is_used_only_when_landable(self):
        for point, expected in (((1250, 2250), (1250, 2250)), ((100, 100), (1750, 1750))):
            files = fixture_v2()
            lat, lon = geographic(*point)
            files['/earthng/countries/demo/manifest.json']['landing'] = dict(lat=lat, lon=lon)
            with self.subTest(point=point):
                _, mod, _ = self.make(files)
                landing = mod.refresh().countries[1].landing
                want = geographic(*expected)
                self.assertAlmostEqual(landing.lat, want[0])
                self.assertAlmostEqual(landing.lon, want[1])

    def test_fast_driving_still_wants_far_ground_and_the_horizon(self):
        _, mod, cv = self.make(fixture(8))
        lat, lon = geographic(3500, 3500)
        mod.land(cv(dict(seq=11, lat=lat, lon=lon)))
        self.assertEqual(self.pump(mod).state, 'ready')
        # 40 m/s is past the 90 km/h decor gate. Far ground and the horizon stay wanted.
        mod.pose(cv(dict(x=3500, y=3500, vx=40, vy=0, state='driving')))
        mod.update(.016, 2)
        far = horizon = 0
        wanted = mod.status().stream.wanted
        for key in wanted.keys():
            priority = wanted[key]
            if str(key).startswith('h'):
                horizon += 1
                self.assertGreaterEqual(priority, 2_000_000)
            elif priority >= 1_000_000:
                far += 1
        self.assertGreater(far, 0)
        self.assertGreater(horizon, 0)

    def test_terrain_only_decoder_reads_the_grid_of_a_full_cell(self):
        lua, _, _ = self.make()
        cell = dict(roads=[dict(id='w1', nodes=['a', 'b'], width=7, tags={'highway': 'primary'},
                                points=[[1000, 0, 5], [1500, 10, 6]])],
                    junctions=[], buildings=[], areas=[], lines=[], points=[],
                    terrain=dict(rect=[1000, 0, 2000, 1000], nx=2, ny=3, heights=[1, 2.04, 3, -4, 5, 6.66]))
        data, _ = binary.encode_block({binary.slot(1, 0): binary.encode_cell(cell, (1000, 0))})
        first, last = binary.decode_block(data)[binary.slot(1, 0)]
        got = lua.globals().cellformat.terrain(data, first + 1, last, lua.table_from([1000, 0, 2000, 1000]))
        self.assertEqual(list(got.terrain.heights.values()), [1, 2.0, 3, -4, 5, 6.7])
        self.assertEqual(got.low, -4)
        self.assertEqual(len(got.roads), 0)

    def test_vista_runs_on_from_a_summit_but_not_while_driving_or_on_the_plain(self):
        _, mod, cv = self.make(fixture(40))
        lat, lon = geographic(20000, 20000)
        mod.land(cv(dict(seq=12, lat=lat, lon=lon)))
        self.assertEqual(self.pump(mod).state, 'ready')

        def vista(**pose):
            mod.pose(cv(dict(x=20000, y=20000, state='driving', **pose)))
            mod.update(.016, 2)
            wanted = mod.status().stream.wanted
            return [k for k in wanted.keys() if str(k).startswith('v4000')], mod.status().stream

        # 400 m over the lowest ground round the camera, standing: 4 km blocks out to 24 km
        keys, st = vista(z=400, vx=0, vy=0)
        self.assertGreater(len(keys), 20)
        # past 5 km nothing decodes whole cells: the full horizon tiles are those of the 5 km ring
        full = sum(1 for k in st.wanted.keys() if str(k).startswith('h'))
        light = sum(1 for k in st.wanted.keys() if str(k).startswith('v'))
        self.assertLess(light, 260)
        self.assertEqual(st.vista, 24000)
        wanted = st.wanted
        self.assertTrue(all(wanted[k] >= 3_000_000 for k in keys))
        # the blocks and the 1 km horizon cover each 500 m quadrant once
        quads = {}
        for key in wanted.keys():
            key = str(key)
            kind, _, ij = key.partition(':')
            if kind not in ('v4000', 'v1000', 'v500', 'h1000', 'h500'):
                continue
            i, j = map(int, ij.split('_'))
            n = {'v4000': 8, 'v1000': 2, 'v500': 1, 'h1000': 2, 'h500': 1}[kind]
            for a in range(n):
                for b in range(n):
                    q = (i * n + a, j * n + b)
                    self.assertNotIn(q, quads, key)
                    quads[q] = key
        # driving at 20 m/s or standing on the plain: the 5 km horizon alone
        keys, st = vista(z=400, vx=20, vy=0)
        self.assertEqual(keys, [])
        self.assertEqual(full, sum(1 for k in st.wanted.keys() if str(k).startswith('h')))
        self.assertEqual(vista(z=100, vx=0, vy=0)[0], [])
        self.assertIsNone(mod.status().stream.vista)

    def test_coarse_horizon_stays_until_its_children_are_ready(self):
        _, mod, cv = self.make()

        def rect(x, y, size):
            return [x, y, x + size, y + size]

        parent = dict(key='parent', rank=1, rect=rect(0, 0, 1000))
        children = [dict(key=f'c{n}', rank=0, rect=rect(x, y, 500))
                    for n, (x, y) in enumerate(((0, 0), (500, 0), (0, 500), (500, 500)))]

        def show(ready_keys):
            ready = {key: True for key in ready_keys}
            table = mod.horizonShow(cv([parent, *children]), cv(ready))
            return {table[i] for i in range(1, len(table) + 1)}

        self.assertEqual(show(['parent', 'c0', 'c1', 'c2']), {'parent'})
        self.assertEqual(show(['parent', 'c0', 'c1', 'c2', 'c3']), {'c0', 'c1', 'c2', 'c3'})
        # A shared edge is not an overlap, so this neighbour is not one of the parent's children.
        neighbour = dict(key='edge', rank=0, rect=rect(1000, 0, 500))
        table = mod.horizonShow(cv([parent, neighbour]), cv(dict(parent=True, edge=True)))
        self.assertEqual({table[i] for i in range(1, len(table) + 1)}, {'parent', 'edge'})
        alone = mod.horizonShow(cv([dict(key='solo', rank=0, rect=rect(2000, 0, 500))]), cv(dict(solo=True)))
        self.assertEqual([alone[i] for i in range(1, len(alone) + 1)], ['solo'])


if __name__ == '__main__':
    unittest.main()
