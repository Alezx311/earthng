"""Copies of a shape in DynamicShapeBatch objects (mod/lua/ge/extensions/e2r/shapebatch.lua) against
a stand-in batch that behaves as the game's did (capacity/dsb3-5.lua): resize keeps the copies, a
slot enabled before it was ever placed stays unseen, remaps count only before finalizeShape."""
import unittest
from pathlib import Path

from lupa.luajit21 import LuaRuntime

SHAPEBATCH = Path(__file__).resolve().parents[1] / 'mod/lua/ge/extensions/e2r/shapebatch.lua'

# the game's DynamicShapeBatch as a table: size, enabled slots, their places and directions
FAKE = '''
BATCH = {made = 0, alive = 0, calls = 0, blind = 0}
local B = {}
B.__index = B
function B:registerObject() self.registered = true end
function B:setShape(s) self.shape = s end
function B:setMaterialRemap(a, b) self.remaps = (self.remaps or '') .. a .. '>' .. b .. ';' end
function B:finalizeShape() self.finals = (self.finals or 0) + 1 end
function B:resize(n)
  for i in pairs(self.at) do if i >= n then self.at[i], self.on[i] = nil, nil end end
  self.size = n
end
function B:setInstance(i, p, d, scale, c)
  assert(i >= 0 and i < self.size, 'slot past the size')
  BATCH.calls = BATCH.calls + 1
  -- the engine keeps the vectors and reads them when it draws, after later copies are placed
  self.pref[i], self.dref[i] = p, d
  self.at[i] = {p.x, p.y, p.z, d.x, d.y, d.z, c}
end
function B:setInstanceEnabled(i, on)
  assert(i < self.size)
  -- enabled before its first place: unseen (dsb-01)
  if on and not self.at[i] then BATCH.blind = BATCH.blind + 1 end
  self.on[i] = on or nil
end
function B:delete() BATCH.alive = BATCH.alive - 1; self.deleted = true end
function B:shown() local n = 0; for i in pairs(self.on) do if self.at[i] then n = n + 1 end end; return n end
CLASS = 'DynamicShapeBatch'
function createObject(kind)
  if kind ~= CLASS then error('no class ' .. kind) end
  BATCH.made, BATCH.alive = BATCH.made + 1, BATCH.alive + 1
  return setmetatable({size = 0, on = {}, at = {}, pref = {}, dref = {}}, B)
end
function vec3(x, y, z) return {x = x, y = y, z = z} end
function ColorF(r, g, b, a) return {r, g, b, a} end
GROUP = {n = 0, addObject = function(self) self.n = self.n + 1 end}
'''


class ShapeBatchTests(unittest.TestCase):
    def lua(self):
        lua = LuaRuntime()
        lua.execute(FAKE)
        lua.globals().sb = lua.execute(SHAPEBATCH.read_text(encoding='utf8'))
        return lua

    def test_copies_of_one_kind_share_one_object_and_survive_its_growth(self):
        out = self.lua().execute('''
          local P = sb.new(GROUP)
          local K = P:kind('car.dae')
          local red = ColorF(1, 0, 0, 1)
          local h = {}
          for k = 1, 100 do h[k] = {P:add(K, k, 2 * k, 3, 0, 1, 0, k == 50 and red or nil)} end
          local o = h[1][1].obj
          local wrong = 0
          for k = 1, 100 do
            local at = o.at[h[k][2]]
            if not at or at[1] ~= k or at[2] ~= 2 * k or at[5] ~= 1 or not o.on[h[k][2]] then wrong = wrong + 1 end
          end
          return BATCH.alive, GROUP.n, o.size, o:shown(), wrong, o.at[h[50][2]][7] == red, P.resizes, P.live,
            BATCH.blind, BATCH.calls, P:kind('car.dae') == K
        ''')
        alive, grouped, size, shown, wrong, red, resizes, live, blind, calls, same = out
        self.assertEqual((alive, grouped), (1, 1))
        self.assertEqual((size, shown, wrong), (128, 100, 0))
        self.assertTrue(red)
        self.assertEqual((resizes, live), (3, 100))
        # placed before enabled, once each: a resize sets nothing again
        self.assertEqual((blind, calls), (0, 100))
        self.assertTrue(same)

    def test_a_dropped_slot_is_hidden_reused_and_not_brought_back_by_a_resize(self):
        out = self.lua().execute('''
          local P = sb.new(nil)
          local K = P:kind('ped.dae')
          local h = {}
          for k = 1, 16 do h[k] = {P:add(K, k, 0, 0, 0, 1, 0)} end
          local B, o = h[1][1], h[1][1].obj
          P:drop(B, h[3][2])
          P:drop(B, h[3][2])            -- twice: once
          local hidden = not o.on[h[3][2]]
          local again = {P:add(K, 99, 0, 0, 0, 1, 0)}
          local reused = again[2] == h[3][2]
          P:drop(B, again[2])
          -- the 17th copy doubles the batch: the dropped slot stays hidden
          P:add(K, 17, 0, 0, 0, 1, 0)
          P:add(K, 18, 0, 0, 0, 1, 0)
          return hidden, reused, o:shown(), P.live, B.nfree + B.live == o.size
        ''')
        self.assertEqual(tuple(out), (True, True, 17, 17, True))

    def test_move_places_without_a_new_table_and_keeps_the_colour(self):
        out = self.lua().execute('''
          local P = sb.new(nil)
          local blue = ColorF(0, 0, 1, 1)
          local B, i = P:add(P:kind('car.dae'), 0, 0, 0, 0, 1, 0, blue)
          local p, d = B.p[i], B.d[i]
          P:move(B, i, 5, 6, 7, -.6, .8, 0)
          local at = B.obj.at[i]
          local _, i2 = P:add(P:kind('car.dae'), 1, 0, 0, 0, 1, 0)
          return at[1], at[3], at[4], at[7] == blue, B.p[i] == p, B.d[i] == d, B.p[i2] ~= p, B.obj.on[i]
        ''')
        self.assertEqual(tuple(out), (5, 7, -.6, True, True, True, True, True))

    def test_a_later_copy_does_not_move_the_ones_already_placed(self):
        out = self.lua().execute('''
          local P = sb.new(nil)
          local K = P:kind('ped.dae')
          local slot = {}
          for k = 1, 3 do slot[k] = {P:add(K, k * 10, k, 0, 0, 1, 0)} end
          local B = slot[1][1]
          P:move(B, slot[2][2], 50, 60, 70, 0, 1, 0)
          local bad = 0
          for k = 1, 3 do
            local i = slot[k][2]
            local x = k == 2 and 50 or k * 10
            local y = k == 2 and 60 or k
            local p, d = B.obj.pref[i], B.obj.dref[i]
            if p.x ~= x or p.y ~= y or p.z ~= (k == 2 and 70 or 0) or d.y ~= 1 then bad = bad + 1 end
            if p == B.obj.pref[slot[k % 3 + 1][2]] then bad = bad + 10 end
          end
          return bad
        ''')
        self.assertEqual(out, 0)

    def test_a_kind_remaps_before_its_one_finalize_and_new_batches_wait_for_the_next_frame(self):
        out = self.lua().execute('''
          local P = sb.new(nil)
          local K = P:kind('ped.dae', {'pants', 'pants_3', 'skin', 'skin_2'}, 'ped|3|2')
          local L = P:kind('ped.dae')
          P:tick()
          local B = P:add(K, 0, 0, 0, 0, 1, 0)
          -- the frame's one new batch is made: L waits, K's second copy does not
          local C = P:add(L, 0, 0, 0, 0, 1, 0)
          local K2 = P:add(K, 1, 0, 0, 0, 1, 0)
          P:tick()
          local C2 = P:add(L, 0, 0, 0, 0, 1, 0)
          for f = 1, 30 do P:tick() end
          return B.obj.remaps, C2.obj.remaps or '', B.obj.finals, C2.obj.finals, C == nil, K2 == B, P.waits, P.objects
        ''')
        remaps, plain, finals_b, finals_c, waited, same, waits, objects = out
        self.assertEqual(remaps, 'pants>pants_3;skin>skin_2;')
        self.assertEqual(plain, '')
        self.assertEqual((finals_b, finals_c), (1, 1))       # finalized once (11-27 ms a call)
        self.assertEqual((waited, same, waits, objects), (True, True, 1, 2))

    def test_each_kind_has_its_batch_and_clear_deletes_them(self):
        out = self.lua().execute('''
          local P = sb.new(GROUP)
          local A, Bk = P:kind('a.dae'), P:kind('b.dae')
          P:warm(A); P:tick(); P:add(A, 0, 0, 0, 0, 1, 0); P:add(Bk, 0, 0, 0, 0, 1, 0)
          local made = BATCH.alive
          P:clear()
          -- the kinds stay and make a batch again
          P:tick()
          P:add(A, 0, 0, 0, 0, 1, 0)
          return made, BATCH.alive, P.objects, P.live, A.batch ~= nil, Bk.batch == nil
        ''')
        self.assertEqual(tuple(out), (2, 1, 1, 1, True, True))

    def test_the_y_axis_of_a_shape_facing_its_heading(self):
        out = self.lua().execute('''
          local x0, y0 = sb.yAxis(0)
          local x1, y1 = sb.yAxis(math.pi / 2)
          return x0, y0, x1, y1
        ''')
        self.assertAlmostEqual(out[0], 0)
        self.assertAlmostEqual(out[1], 1)
        self.assertAlmostEqual(out[2], -1)
        self.assertAlmostEqual(out[3], 0, places=9)

    def test_an_older_game_without_the_class_keeps_its_statics(self):
        lua = self.lua()
        self.assertTrue(lua.execute('return sb.available()'))
        lua = self.lua()
        self.assertFalse(lua.execute('CLASS = "none"; return sb.available()'))
        lua = self.lua()
        # the class there but without the calls this module makes
        self.assertFalse(lua.execute('''
          local B = getmetatable(createObject(CLASS)).__index
          B.setMaterialRemap = nil
          return sb.available()
        '''))


if __name__ == '__main__':
    unittest.main()
