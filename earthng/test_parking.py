"""The parked cars' spots (parking.lua) under LuaJIT, with the game's sites and parking faked."""
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r'


class ParkingTests(unittest.TestCase):
    def setUp(self):
        lua = self.lua = LuaRuntime()
        lua.execute('''
          function vec3(x, y, z) return {x = x, y = y, z = z} end
          function quatFromDir(d) return {d.x, d.y} end
          created = 0
          local function fields()
            local f = {tags = {}}
            function f:addTag(t) assert(not self.tags[t], 'tag twice'); self.tags[t] = 1 end
            function f:removeTag(t) assert(self.tags[t], 'no tag'); self.tags[t] = nil end
            return f
          end
          local function sites()
            local s = {finalized = 0, parkingSpots = {objects = {}, sorted = {}}}
            function s.parkingSpots:create()
              created = created + 1
              local ps = {id = created, customFields = fields()}
              function ps:set(pos, rot, scl) self.pos, self.rot, self.scl = pos, rot, scl end
              self.objects[ps.id] = ps
              return ps
            end
            function s.parkingSpots:sort()
              self.sorted = {}
              for _, o in pairs(self.objects) do self.sorted[#self.sorted + 1] = o end
            end
            function s:finalizeSites() self.finalized = self.finalized + 1 end
            return s
          end
          function require(path) assert(path:find('gameplay/sites/sites', 1, true)); return sites end
          calls = {}
          extensions = {load = function() end}
          gameplay_traffic = {}
          gameplay_parking = {
            setSites = function(s) calls[#calls + 1] = 'setSites' end,
            setupVehicles = function(n, o) calls[#calls + 1] = 'setup ' .. n .. ' ' .. o.pos.x; return true end,
            deleteVehicles = function() calls[#calls + 1] = 'delete' end,
            deactivate = function() calls[#calls + 1] = 'deactivate' end}
        ''')
        lua.globals().parking = lua.execute((ROOT / 'parking.lua').read_text(encoding='utf8'))
        lua.execute('''
          P = parking.new()
          function lot(n, x0)
            local l = {}
            for k = 1, n do l[k] = {x0 + 2.7 * k, 10, 120, 0} end
            return l
          end
          tiles = {a = {parking = lot(10, 0), collided = true, state = 'loaded'},
                   b = {parking = lot(6, 100), collided = false, state = 'loaded'}}
        ''')

    def test_spots_of_tiles_without_collision_are_banned_not_removed(self):
        lua = self.lua
        self.assertEqual(lua.eval('parking.sync(P, tiles)'), 10)
        self.assertEqual(lua.eval('P.total'), 16)
        self.assertEqual(lua.eval('#P.sites.parkingSpots.sorted'), 16)
        banned = lua.eval('(function() local n = 0 for _, ps in pairs(P.sites.parkingSpots.objects) do '
                          'if ps.customFields.tags.banned then n = n + 1 end end return n end)()')
        self.assertEqual(banned, 6)
        lua.execute('tiles.a.collided, tiles.b.collided = false, true')
        self.assertEqual(lua.eval('parking.sync(P, tiles)'), 6)
        self.assertEqual(lua.eval('P.total'), 16)
        lua.execute('tiles.a = nil')
        self.assertEqual(lua.eval('parking.sync(P, tiles)'), 6)
        self.assertEqual(lua.eval('#P.sites.parkingSpots.sorted'), 16)

    def test_a_known_list_makes_no_new_spots(self):
        lua = self.lua
        lua.execute('parking.sync(P, tiles); first = created; finals = P.sites.finalized')
        lua.execute('parking.sync(P, tiles)')
        self.assertEqual(lua.eval('created'), lua.eval('first'))
        self.assertEqual(lua.eval('P.sites.finalized'), lua.eval('finals'))
        # a rebuilt tile with the same bays reuses their spots (a pool car keeps its spot id)
        lua.execute('tiles.a = {parking = lot(10, 0), collided = true, state = "loaded"}; parking.sync(P, tiles)')
        self.assertEqual(lua.eval('created'), lua.eval('first'))

    def test_cars_come_once_there_are_twice_as_many_spots(self):
        lua = self.lua
        lua.execute('parking.sync(P, tiles)')
        self.assertEqual(list(lua.eval('calls').values()), ['setSites'])
        lua.execute('calls = {}')
        self.assertFalse(lua.eval('parking.step(P, 8, vec3(5, 6, 7))'))
        self.assertEqual(lua.eval('#calls'), 0)
        self.assertTrue(lua.eval('parking.step(P, 4, vec3(5, 6, 7))'))
        self.assertEqual(list(lua.eval('calls').values())[-1], 'setup 4 5')
        self.assertFalse(lua.eval('parking.step(P, 4, vec3(5, 6, 7))'))
        lua.execute('parking.step(P, 0, vec3(5, 6, 7))')
        self.assertEqual(list(lua.eval('calls').values())[-2:], ['delete', 'deactivate'])
        lua.execute('parking.clear(P)')
        self.assertEqual(lua.eval('P.total'), 0)
        self.assertIsNone(lua.eval('P.sites'))


if __name__ == '__main__':
    unittest.main()
