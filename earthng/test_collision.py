"""The static collision policy (collision.lua) under LuaJIT, with fake scene objects."""
from pathlib import Path
import sys
import unittest

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r'


class CollisionTests(unittest.TestCase):
    def make(self):
        lua = LuaRuntime()
        lua.globals().collision = lua.execute((ROOT / 'collision.lua').read_text())
        lua.execute('''
          objects, serial = {}, 0
          function make(owner, quiet)
            serial = serial + 1
            objects[serial] = {id = serial, hidden = false,
              isHidden = function(self) return self.hidden end,
              setHidden = function(self, h) self.hidden = h end}
            coll:track(owner, serial, quiet)
            return serial
          end
          function find(id) return objects[id] end
          seen = {}
          function reload()
            seen = {}
            for id, o in pairs(objects) do seen[id] = o.hidden end
          end
          function shown() for _, o in pairs(objects) do if o.hidden then return false end end return true end
          coll = collision.new()
          function mesh(...) local out = {} for k, m in ipairs({...}) do out[k] = {material = 'e2rf_' .. m} end return out end
        ''')
        return lua

    def test_quiet_materials_depend_on_layer(self):
        lua = self.make()
        lua.execute('''
          local q = collision.quiet
          assert(q(mesh('mark'), 'road') and q(mesh('mark_yellow'), 'scene'))
          -- the road layer's ground takes a cover's material where the cover fills a cell
          assert(not q(mesh('park'), 'road') and not q(mesh('ground'), 'road') and not q(mesh('road'), 'road'))
          assert(q(mesh('park'), 'scene') and q(mesh('footway', 'paved', 'roof'), 'scene'))
          -- one solid material keeps the whole object
          assert(not q(mesh('roof', 'wall_brk_red'), 'scene') and not q(mesh('car'), 'scene'))
          assert(not q(mesh('fence_mesh'), 'scene') and not q({}, 'scene') and not q(mesh('mark'), nil))
        ''')

    def test_rebuild_keeps_only_what_is_in_reach_and_shows_everything_after(self):
        lua = self.make()
        lua.execute('''
          local here, next, away = {i = 0, j = 0}, {i = 1, j = 0}, {i = 3, j = 0}
          local far, farAway, band = {i = -1, j = 0, far = true}, {i = 6, j = 0, far = true}, {horizon = true}
          local road, mark = make(here, false), make(here, true)
          local nextRoad, awayRoad = make(next, false), make(away, false)
          local farRoad, farAwayRoad, horizon = make(far, false), make(farAway, false), make(band, false)
          -- car at (250, 250) in tile 0_0; reach 800 m: tile 1_0 (250 m) and -1_0 (250 m) stay,
          -- 3_0 (1250 m) and 6_0 do not; the horizon and markings never join
          local hidden = coll:rebuild({{250, 250, 600, 800}}, 500, find, reload)
          assert(hidden == 4 and shown())
          assert(not seen[road] and not seen[nextRoad] and not seen[farRoad])
          assert(seen[mark] and seen[awayRoad] and seen[farAwayRoad] and seen[horizon])
          assert(collision.solid(here, {{250, 250, 600, 800}}, 500) and not collision.solid(away, {{250, 250, 600, 800}}, 500))
          -- tile 2_0 is 750 m away: kept by a rebuild (keep 800) but not yet wanted (want 600)
          local two = {i = 2, j = 0}
          assert(collision.solid(two, {{250, 250, 600, 800}}, 500) and not collision.within(two, {{250, 250, 600, 800}}, 500, 3))
          assert(collision.within(two, {{500, 250, 600, 800}}, 500, 3))
          -- a second focus point (a parked car, traffic) keeps its own ground
          coll:rebuild({{250, 250, 600, 800}, {1600, 250, 100, 300}}, 500, find, reload)
          assert(not seen[awayRoad] and seen[farAwayRoad])
          -- no focus at all: every live tile keeps its collision
          coll:rebuild({}, 500, find, reload)
          assert(not seen[awayRoad] and seen[mark] and seen[horizon])
        ''')

    def test_the_scene_keeps_to_its_own_window(self):
        lua = self.make()
        lua.execute('''
          function makeLayer(owner, layer)
            serial = serial + 1
            objects[serial] = {id = serial, hidden = false,
              isHidden = function(self) return self.hidden end,
              setHidden = function(self, h) self.hidden = h end}
            coll:track(owner, serial, false, 1000, layer)
            return serial
          end
          local here, ahead, beside = {i = 0, j = 0}, {i = 1, j = 0}, {i = 0, j = 1}
          local road, wall = makeLayer(here, 'road'), makeLayer(here, 'scene')
          local aheadRoad, aheadWall = makeLayer(ahead, 'road'), makeLayer(ahead, 'scene')
          local besideRoad, besideWall = makeLayer(beside, 'road'), makeLayer(beside, 'scene')
          -- at speed: the car at (250, 250) heading +x keeps the ground of all three tiles, its own
          -- walls (slot 5/6 of the car: 0, 100) and those round a point 100 m ahead (150 + 50 m):
          -- tile 1_0 is 150 m from it, tile 0_1 250 m
          local points = {{250, 250, 400, 600, 0, 100}, {350, 250, -1, -1, 150, 200}}
          coll:rebuild(points, 500, find, reload)
          assert(not seen[road] and not seen[aheadRoad] and not seen[besideRoad])
          assert(not seen[wall] and not seen[aheadWall] and seen[besideWall])
          assert(coll.lastScenes == 2 and coll.lastKept.scene == 2000 and coll.lastKept.road == 3000)
          assert(collision.sceneSolid(ahead, points, 500) and not collision.sceneSolid(beside, points, 500))
          -- the scene asks only within its own reach (slot 5)
          assert(collision.within(ahead, points, 500, 5) and not collision.within(beside, points, 500, 5))
          -- a point without scene slots keeps walls with the ground; with none at all, everything
          coll:rebuild({{250, 250, 400, 600}}, 500, find, reload)
          assert(not seen[besideWall])
          -- walls never stay where the ground goes
          coll:rebuild({{250, 250, 100, 200, 1000, 1000}}, 500, find, reload)
          assert(seen[besideRoad] and seen[besideWall] and not seen[wall])
        ''')

    def test_at_speed_the_world_keeps_a_lane_ahead(self):
        # world.lua's collisionPoints with the real policy: Kyiv tiles (500 m), the car in the
        # middle of tile 0_0 at 69 m/s along +x
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_widget import load_world
        lua = self.make()
        lua.execute('''
          ui_imgui = setmetatable({ArrayChar=function() return {} end}, {__index=function() return function() end end})
          realRequire, require = require, function() return {} end
          hptimer=function() return {stopAndReset=function() return 1 end, stop=function() return 1 end} end''')
        src = (ROOT / 'world.lua').read_text(encoding='utf8')
        lua.globals().mod = load_world(lua, src)
        lua.execute('''
          local function up(fn, name)
            for i = 1, 200 do local n, v = debug.getupvalue(fn, i); if not n then return end; if n == name then return v end end
          end
          local points = up(up(mod.tick, 'updateCollision'), 'collisionPoints')
          local S = up(mod.tick, 'S')
          local function at(speed)
            local v = {x = speed, y = 0}
            function v:length() return speed end
            return points({x = 250, y = 250}, v)
          end
          local function kept(pts, slot)
            local out = {}
            for i = -2, 3 do for j = -2, 2 do
              local tile = {i = i, j = j}
              local keep = slot == 6 and collision.sceneSolid(tile, pts, 500) or collision.solid(tile, pts, 500)
              if keep then out[#out + 1] = i .. '_' .. j end
            end end
            return table.concat(out, ' ')
          end
          S.state = 'driving'
          local fast = at(69)
          -- ground: the car's tile and the lane ahead (376 m + 200 m); not the tiles beside or behind
          assert(kept(fast, 4) == '0_0 1_0', kept(fast, 4))
          -- the next tile asks for its ground before the car is there (want 376 m along the lane)
          assert(collision.within({i = 1, j = 0}, fast, 500, 3) and not collision.within({i = 0, j = 1}, fast, 500, 3))
          -- walls: the car's tile and the next
          assert(kept(fast, 6) == '0_0 1_0', kept(fast, 6))
          -- slow: the disc round the car as before (want 200, keep 400)
          local slow = at(5)
          assert(kept(slow, 4) == '-1_-1 -1_0 -1_1 0_-1 0_0 0_1 1_-1 1_0 1_1', kept(slow, 4))
          assert(kept(slow, 6) == kept(slow, 4))
        ''')

    def test_graves_stay_out_until_deleted_and_failures_show_the_world(self):
        lua = self.make()
        lua.execute('''
          local old, other = {i = 0, j = 0}, {i = 0, j = 0}
          local a, b = make(old, false), make(old, false)
          make(other, false)
          old.dropped = true
          coll:rebuild({{0, 0, 600, 800}}, 500, find, reload)
          assert(seen[a] and seen[b] and coll.owners[old])
          objects[a], objects[b] = nil, nil
          coll:rebuild({{0, 0, 600, 800}}, 500, find, reload)
          assert(coll.owners[old] == nil and coll.owners[other] and #old.solidIds == 0)
          -- an already hidden object is left as it was
          local spare = make(other, true)
          objects[spare].hidden = true
          coll:rebuild({{0, 0, 600, 800}}, 500, find, reload)
          assert(objects[spare].hidden)
          objects[spare] = nil
          local ok, err = pcall(function()
            make(other, true)
            coll:rebuild({{0, 0, 600, 800}}, 500, find, function() error('engine') end)
          end)
          assert(not ok and tostring(err):find('engine') and shown())
        ''')


if __name__ == '__main__':
    unittest.main()
