"""World streaming keeps traffic-light data in step with loaded scenes."""
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]


class SignalLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.globals().quality = self.lua.execute(
            (ROOT / 'mod/lua/ge/extensions/e2r/quality.lua').read_text(encoding='utf8'))
        self.lua.execute('''
          require = function(name) if name == 'ge/extensions/e2r/quality' then return quality end; return {} end
          ui_imgui = setmetatable({ArrayChar=function() return {} end},
            {__index=function() return function() end end})
          hptimer = function() return {stop=function() return 0 end} end
          function findUp(fn, target, seen)
            seen = seen or {}; if seen[fn] then return end; seen[fn] = true
            local children = {}
            for i=1,200 do
              local name,value = debug.getupvalue(fn,i); if not name then break end
              if name == target then return value end
              if type(value) == 'function' then children[#children+1] = value end
            end
            for _,child in ipairs(children) do
              local value = findUp(child,target,seen); if value then return value end
            end
          end
          function replaceUp(fn, name, value)
            for i=1,200 do
              local n = debug.getupvalue(fn,i); if not n then break end
              if n == name then debug.setupvalue(fn,i,value); return end
            end
            error('missing upvalue ' .. name)
          end
        ''')
        self.lua.globals().world = self.lua.execute(
            (ROOT / 'mod/lua/ge/extensions/e2r/world.lua').read_text(encoding='utf8'))
        self.lua.execute('S = world.dbg().S; S.now = 10')

    def test_late_or_replaced_scene_marks_batched_ai_graph_dirty(self):
        self.lua.execute('''
          local start = assert(findUp(world.tick, 'startScene'))
          local native = assert(findUp(start, 'native'))
          native.manifest = function() return manifest end
          native.release = function() end
          replaceUp(start, 'loadNewMaterials', function() end)
          replaceUp(start, 'tileGroup', function() return {} end)
          replaceUp(start, 'queueItems', function() return 0 end)
          world.signals = {addTile=function() end}
          S.stream = {region='region'}
          local tile = {left=0}
          manifest = {source='region',items={},lights={{group=1}}}
          start('0_0', tile)
          assert(S.navDirty and S.flowLightVersion == 1)
          -- Replacing a lit scene with an unlit one must request a graph refresh as well.
          S.navDirty = false; manifest.lights = {}
          start('0_0', tile)
          assert(S.navDirty and S.flowLightVersion == 2)
          -- Scenes with no signals must not trigger extra graph rebuilds.
          S.navDirty = false; start('0_0', tile)
          assert(not S.navDirty and S.flowLightVersion == 2)
        ''')

    def test_nav_read_removes_lights_when_same_tile_has_none(self):
        self.lua.execute('''
          local read = assert(findUp(world.tick, 'navRead'))
          S.navLights = {key={{1,2}}}; S.nav = {}
          S.navPending = {{key='key',data={segments={},signals={}}}}
          read()
          assert(S.navLights.key == nil and S.flowLightVersion == 1)
          S.navPending = {{key='key',data={segments={},signals={{3,4}}}}}
          read()
          assert(S.navLights.key[1][1] == 3 and S.flowLightVersion == 2)
        ''')

    def test_new_arrival_clears_old_lights_before_graph_reset(self):
        self.lua.execute('''
          local arrive = assert(findUp(world.tick, 'beginArrival'))
          S.tiles, S.far, S.horizon, S.queue = {}, {}, {}, {}
          S.navLights = {key={{1,2}}}; S.nav = {}; S.navPending = {}
          map = {reset=function()
            assert(next(S.navLights) == nil)
            error('reset reached')
          end}
          local ok, err = pcall(arrive, {manifest={}})
          assert(not ok and err:find('reset reached', 1, true), err)
        ''')

    def test_end_mission_clears_lights(self):
        self.lua.execute('''
          replaceUp(world.onClientEndMission, 'restorePackState', function() end)
          replaceUp(world.onClientEndMission, 'resetForests', function() end)
          replaceUp(world.onClientEndMission, 'dropLights', function() end)
          local native = assert(findUp(world.onClientEndMission, 'native'))
          native.refresh = function() end
          S.navLights = {key={{1,2}}}
          world.onClientEndMission()
          assert(next(S.navLights) == nil)
        ''')

    def test_pack_refresh_clears_lights_with_the_world(self):
        self.lua.execute('''
          local refresh = assert(findUp(world.onModActivated, 'refreshCountries'))
          local native = assert(findUp(refresh, 'native'))
          native.refresh, native.status = function() end, function() return {} end
          replaceUp(refresh, 'dropGroup', function() end)
          replaceUp(refresh, 'dropLights', function() end)
          scenetree = {findObject=function() return nil end}
          map = {reset=function() end}
          S.stream = {region='old'}
          S.tiles, S.far, S.horizon, S.queue = {}, {}, {}, {}
          S.navLights = {key={{1,2}}}
          world.onModActivated()
          assert(next(S.navLights) == nil and S.stream == nil)
        ''')


if __name__ == '__main__':
    unittest.main()
