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
