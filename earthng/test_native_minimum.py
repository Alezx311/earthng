"""Budgeted terrain minima in the native tile-loading coroutine."""
import unittest

import test_native as helpers


class NativeMinimumTests(unittest.TestCase):
    def test_legacy_cell_is_not_cached_until_minimum_finishes(self):
        files = helpers.fixture()
        path = '/earthng/countries/demo/regions/sample/cells/1_1.json'
        heights = [3] * (257 * 257)
        heights[-1] = -6
        files[path]['terrain'].update(nx=257, ny=257, heights=heights)
        lua, mod, cv = helpers.NativeTests().make(files)
        lat, lon = helpers.geographic(1750, 1750)
        mod.land(cv(dict(seq=1, lat=lat, lon=lon)))
        lua.globals().native = mod
        lua.execute('''
          local function up(f, key)
            for i = 1, 200 do
              local name, value = debug.getupvalue(f, i)
              if not name then break end
              if name == key then return value end
            end
            error('missing upvalue ' .. key)
          end
          local active = up(native.update, 'active')
          local load = up(up(native.update, 'buildTile'), 'loadCell')
          active.pause = function() coroutine.yield() end
          local function job() return load('1_1', 1, 1, nil, {}) end
          -- A tile job can be discarded while parked. A new job must not see a
          -- half-published cell and permanently skip computing its low.
          local abandoned = coroutine.create(job)
          local ok = coroutine.resume(abandoned)
          assert(ok and coroutine.status(abandoned) == 'suspended')
          assert(active.cells['1_1'] == nil and active.lows['1_1'] == nil)
          local replacement = coroutine.create(job)
          local yields, result = 0
          repeat
            ok, result = coroutine.resume(replacement)
            assert(ok, result)
            if coroutine.status(replacement) ~= 'dead' then yields = yields + 1 end
          until coroutine.status(replacement) == 'dead'
          assert(yields == 8 and result == active.cells['1_1'].data)
          assert(active.lows['1_1'] == -6)
          local cached = coroutine.create(job)
          ok, result = coroutine.resume(cached)
          assert(ok and coroutine.status(cached) == 'dead' and result == active.cells['1_1'].data)
        ''')

    def test_budgeted_minimum_for_packed_and_live_cells(self):
        helper = helpers.NativeTests()
        lua, mod, cv = helper.make(helpers.fixture_v2())
        lat, lon = helpers.geographic(1750, 1750)
        mod.land(cv(dict(seq=1, lat=lat, lon=lon)))
        lua.globals().native = mod
        run = lua.eval('''function()
          local function up(f, key)
            for i = 1, 200 do
              local name, value = debug.getupvalue(f, i)
              if not name then break end
              if name == key then return value end
            end
            error('missing upvalue ' .. key)
          end
          local function set(f, key, value)
            for i = 1, 200 do
              local name = debug.getupvalue(f, i)
              if not name then break end
              if name == key then debug.setupvalue(f, i, value); return end
            end
            error('missing upvalue ' .. key)
          end
          local active = up(native.update, 'active')
          local build = up(native.update, 'buildTile')
          local load = up(build, 'loadCell')
          local terrainOnly = up(build, 'loadTerrain')
          local heights = {}
          for i = 1, 257 * 257 do heights[i] = 7 end
          heights[50000] = -8.5
          local cell = {terrain={heights=heights}}
          active.pause = function() coroutine.yield('budget') end
          -- A cached block and decoder stub isolate the minimum pass, while the real
          -- loadCell path still chooses the source and records active.lows.
          active.blocks['0_0'] = {data='x', slots={[9]={1,1}}}
          cellformat.cell = function() return cell end
          local function loadWithBudget(fn, key)
            local co = coroutine.create(fn)
            local yields, result = 0
            repeat
              local ok, value = coroutine.resume(co)
              assert(ok, value)
              if coroutine.status(co) == 'dead' then result = value else
                assert(value == 'budget'); yields = yields + 1
                assert(active.lows[key] == nil, 'partial minimum published')
              end
            until result
            return yields, result
          end
          local y, got = loadWithBudget(function() return load('1_1', 1, 1, nil, {}) end, '1_1')
          assert(y == 8 and got == cell and active.lows['1_1'] == -8.5)
          -- A cached minimum of zero is valid in Lua and must not trigger another pass.
          active.lows['1_1'] = 0
          local second = coroutine.create(function() return load('1_1', 1, 1, nil, {}) end)
          local ok, cached = coroutine.resume(second)
          assert(ok and coroutine.status(second) == 'dead' and cached == cell and active.lows['1_1'] == 0)

          local live = {cell=function() return cell end}
          set(load, 'live', live)
          set(terrainOnly, 'live', live)
          active.region.data.blocks['0_0'].memory = true
          active.lows['1_1'] = nil
          y, got = loadWithBudget(function() return load('1_1', 1, 1, nil, {}) end, '1_1')
          assert(y == 8 and got == cell and active.lows['1_1'] == -8.5)
          active.lows['1_1'] = nil
          cell.low = nil
          y, got = loadWithBudget(function() return terrainOnly('1_1', 1, 1, {}) end, '1_1')
          assert(y == 8 and got.low == -8.5 and active.lows['1_1'] == -8.5)
          cell.low = 0
          active.lows['1_1'] = nil
          local third = coroutine.create(function() return terrainOnly('1_1', 1, 1, {}) end)
          ok, cached = coroutine.resume(third)
          assert(ok and coroutine.status(third) == 'dead' and cached.low == 0 and active.lows['1_1'] == 0)
        end''')
        run()


if __name__ == '__main__':
    unittest.main()
