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
          assert(S.signalDirty and not S.navDirty and S.flowLightVersion == 1)
          -- Replacing a lit scene with an unlit one must request a graph refresh as well.
          S.signalDirty = false; manifest.lights = {}
          start('0_0', tile)
          assert(S.signalDirty and not S.navDirty and S.flowLightVersion == 2)
          -- Scenes with no signals must not trigger extra signal refreshes.
          S.signalDirty = false; start('0_0', tile)
          assert(not S.signalDirty and not S.navDirty and S.flowLightVersion == 2)
        ''')

    def test_signal_refresh_batches_without_resetting_road_graph(self):
        self.lua.execute('''
          local step = assert(findUp(world.tick, 'navStep'))
          replaceUp(step, 'focus', function() return {x=50,y=60} end)
          local m = {buildSerial=123,nodes={n={links={}}}}
          local calls, resets = 0, 0
          map = {getMap=function() return m end, reset=function() resets=resets+1 end}
          world.signals = {navgraph=function(nodes, nav, x, y, traffic, makePos)
            assert(nodes == m.nodes and nav == S.nav and x == 50 and y == 60)
            calls=calls+1
          end}
          S.stream, S.navPending, S.nav = {}, {}, {}
          S.navSerial, S.navPos, S.navAt, S.navDirty = 123, {50,60}, 9, false
          S.signalDirty, S.signalAt = true, nil
          step()
          assert(calls == 1 and resets == 0 and not S.signalDirty and S.signalAt == 10)
          assert(S.navAt == 9 and S.navSerial == 123)
          -- Several arriving scenes within the next two seconds share a single refresh.
          S.signalDirty, S.now = true, 11
          step(); step(); assert(calls == 1 and S.signalDirty)
          S.now = 12; step()
          assert(calls == 2 and resets == 0 and not S.signalDirty)
        ''')

    def test_pending_road_or_foreign_rebuild_takes_precedence(self):
        self.lua.execute('''
          local step = assert(findUp(world.tick, 'navStep'))
          replaceUp(step, 'focus', function() return {x=1,y=2} end)
          local m = {buildSerial=1,nodes={n={links={}}}}
          local builds, updates = 0, 0
          map = {getMap=function() return m end}
          world.signals = {navgraph=function() updates=updates+1 end}
          replaceUp(step, 'navBuild', function()
            builds=builds+1; S.navDirty=false; S.signalDirty=false; S.navSerial=m.buildSerial
            S.navAt=S.now
          end)
          S.stream, S.navPending, S.nav = {}, {}, {}
          S.navSerial, S.navPos, S.navAt = 1, {1,2}, 9
          S.navDirty, S.signalDirty, S.now = true, true, 10
          step(); assert(builds == 0 and updates == 0 and S.signalDirty)
          S.now=11; step(); assert(builds == 1 and updates == 0 and not S.signalDirty)
          -- A foreign reset likewise wins, even when the signal batch is ready.
          m.buildSerial=2; S.signalDirty=true; S.now=13
          step(); assert(builds == 2 and updates == 0 and not S.signalDirty)
        ''')

    def test_signal_refresh_waits_for_focus_module_and_owned_graph(self):
        self.lua.execute('''
          local step = assert(findUp(world.tick, 'navStep'))
          local focus = {x=1,y=2}
          replaceUp(step, 'focus', function() return focus end)
          local m = {buildSerial=1,nodes={n={links={}}}}
          map = {getMap=function() return m end}
          local updates = 0
          local signals = {navgraph=function() updates=updates+1 end}
          S.stream, S.navPending, S.nav = {}, {}, {}
          S.navSerial, S.navPos, S.navAt, S.navDirty = 1, {1,2}, 10, false
          S.signalDirty, S.now = true, 10
          focus=nil; world.signals=signals; step()
          assert(S.signalDirty and updates == 0)
          focus={x=1,y=2}; world.signals=nil; step()
          assert(S.signalDirty and updates == 0)
          world.signals=signals; S.navSerial=nil; step()
          assert(S.signalDirty and updates == 0)
          S.navSerial=1; m.nodes={}; step()
          assert(S.signalDirty and updates == 0)
          m.nodes={n={links={}}}; step()
          assert(not S.signalDirty and updates == 1)
        ''')

    def test_real_nav_build_absorbs_pending_signal_refresh(self):
        self.lua.execute('''
          local build = assert(findUp(world.tick, 'navBuild'))
          replaceUp(build, 'focus', function() return {x=1,y=2} end)
          table.clear = function(t) for k in pairs(t) do t[k]=nil end end
          local m = {buildSerial=1, nodes={}}
          map = {getMap=function() return m end, reset=function(nodes)
            m.nodes=nodes; m.buildSerial=m.buildSerial+1
          end}
          local updates = 0
          world.signals = {navgraph=function(nodes, nav, x, y)
            assert(nodes == m.nodes and nav == S.nav and x == 1 and y == 2)
            updates=updates+1
          end}
          S.nav, S.tiles, S.signalDirty, S.now = {}, {}, true, 10
          build()
          assert(updates == 1 and not S.signalDirty and S.signalAt == 10)
          -- If the signal module is not ready, do not lose a pending scene update.
          world.signals=nil; S.signalDirty=true; S.now=20; build()
          assert(S.signalDirty and S.signalAt == 10)
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
          S.signalDirty, S.signalAt = true, 5
          map = {reset=function()
            assert(next(S.navLights) == nil and S.signalDirty == nil and S.signalAt == nil)
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
          S.navLights = {key={{1,2}}}; S.signalDirty=true; S.signalAt=5
          world.onClientEndMission()
          assert(next(S.navLights) == nil and S.signalDirty == nil and S.signalAt == nil)
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
          S.navLights = {key={{1,2}}}; S.signalDirty=true; S.signalAt=5
          world.onModActivated()
          assert(next(S.navLights) == nil and S.stream == nil and S.signalDirty == nil and S.signalAt == nil)
        ''')


if __name__ == '__main__':
    unittest.main()
