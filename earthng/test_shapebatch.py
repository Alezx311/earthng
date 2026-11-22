"""Copies of a shape in DynamicShapeBatch objects (mod/lua/ge/extensions/e2r/shapebatch.lua) against
a stand-in batch that behaves as the game's did (capacity/dsb3-5.lua): resize keeps the copies, a
slot enabled before it was ever placed stays unseen, remaps count only before finalizeShape."""
import math
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
-- a TSStatic: where it stands, how it is turned, hidden or not, its instance colour
STATIC = {made = 0, alive = 0, moves = 0}
local T = {}
T.__index = T
function T:setField(k, _, v) self.fields[k] = v end
function T:registerObject() self.registered = true end
function T:setPosRot(x, y, z, qx, qy, qz, qw) STATIC.moves = STATIC.moves + 1; self.at = {x, y, z, qx, qy, qz, qw} end
function T:setHidden(h) self.hidden = h end
function T:delete() STATIC.alive = STATIC.alive - 1; self.deleted = true end
CLASS = 'DynamicShapeBatch'
function createObject(kind)
  if kind == 'TSStatic' then
    STATIC.made, STATIC.alive = STATIC.made + 1, STATIC.alive + 1
    return setmetatable({fields = {}}, T)
  end
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


    def test_with_primers_a_kinds_first_batch_only_loads_the_shape_and_its_copies_come_later(self):
        out = self.lua().execute('''
          sb.PRIME_FRAMES = 10
          local P = sb.new(GROUP)
          local K = sb.kind(P, 'car.dae')
          local out = {}
          -- the first ask makes the primer: a finalized batch without a copy, and no copy yet
          P:tick()
          out[1] = P:add(K, 1, 2, 3, 0, 1, 0) == nil
          out[2] = BATCH.made
          out[3] = K.primer ~= nil and K.primer.finals == 1 and K.primer:shown() == 0 and K.batch == nil
          -- asked again until PRIME_FRAMES have passed: still none, and nothing more is made
          for f = 1, 9 do
            P:tick()
            if P:add(K, 1, 2, 3, 0, 1, 0) then out[4] = f end
          end
          out[4] = out[4] or 0
          out[5] = BATCH.made
          -- then its batch, and the primer goes once that one is there
          P:tick()
          local primer = K.primer
          local B, i = P:add(K, 1, 2, 3, 0, 1, 0)
          out[6] = B ~= nil and B.obj:shown() == 1 and B.obj ~= primer
          out[7] = primer.deleted == true and K.primer == nil
          out[8] = {BATCH.made, BATCH.alive, P.objects}
          -- a kind warmed is primed at once, whatever the frame made already; clear takes a primer too
          local K2 = sb.kind(P, 'van.dae')
          out[9] = P:warm(K2) == nil and K2.primer ~= nil
          P:clear()
          out[10] = {BATCH.alive, K2.primer == nil}
          return out
        ''')
        first, made, primer, early, made_wait, shown, gone, counts, warmed, cleared = list(out.values())
        self.assertTrue(first)
        self.assertEqual(made, 1)
        self.assertTrue(primer)
        self.assertEqual(early, 0)
        self.assertEqual(made_wait, 1)
        self.assertTrue(shown)
        self.assertTrue(gone)
        self.assertEqual(list(counts.values()), [2, 1, 1])
        self.assertTrue(warmed)
        self.assertEqual(list(cleared.values()), [0, True])

    def test_a_solid_copy_is_a_pooled_static_turned_like_the_batch_copy_with_its_colour_and_pitch(self):
        out = self.lua().execute('''
          local P = sb.new(GROUP)
          local K = P:kind('car.dae')
          local red = ColorF(1, 0, 0, 1)
          P:tick()
          -- heading east (+x): the shape's +y points north
          local B, i = P:addSolid(K, 1, 2, 3, 0, 1, 0, red)
          local o = B.objs[i]
          local out = {}
          out[1] = {BATCH.made, STATIC.made, GROUP.n, o.hidden == false, o.fields.shapeName, o.fields.collisionType}
          out[2] = {o.at[1], o.at[2], o.at[3], o.at[6], o.at[7]}
          out[3] = o.instanceColor == red
          -- heading north (+y): the shape's +y points west; BeamNG's quaternion is the conjugate
          P:move(B, i, 4, 5, 6, -1, 0, 0)
          out[4] = {o.at[1], o.at[6], o.at[7]}
          -- the nose up a slope
          P:move(B, i, 4, 5, 6, 0, 1, 0, nil, .1)
          out[5] = {o.at[4], o.at[5], o.at[6], o.at[7]}
          -- dropped: hidden, and the next copy of the kind takes the same object
          P:drop(B, i)
          P:drop(B, i)
          out[6] = {o.hidden, P.solidLive, B.nfree}
          local B2, i2 = P:addSolid(K, 7, 8, 9, 0, 1, 0)
          out[7] = {B2 == B, i2 == i, STATIC.made, o.hidden == false, o.instanceColor == P.white, P.solidObjects, P.solidLive}
          P:clear()
          out[8] = {STATIC.alive, P.solidObjects, K.solid == nil}
          return out
        ''')
        made, flat, red, north, slope, dropped, again, cleared = [list(v.values()) if hasattr(v, 'values') else v for v in out.values()]
        self.assertEqual(made, [0, 1, 1, True, 'car.dae', 'None'])
        self.assertEqual(flat[:3], [1, 2, 3])
        self.assertAlmostEqual(flat[3], 0)
        self.assertAlmostEqual(flat[4], 1)
        self.assertTrue(red)
        self.assertEqual(north[0], 4)
        self.assertAlmostEqual(north[1], -math.sin(math.pi / 4))
        self.assertAlmostEqual(north[2], math.cos(math.pi / 4))
        # flow.quat(0, .1): (0, sin(.05), 0, cos(.05))
        self.assertAlmostEqual(slope[0], 0)
        self.assertAlmostEqual(slope[1], math.sin(.05))
        self.assertAlmostEqual(slope[2], 0)
        self.assertAlmostEqual(slope[3], math.cos(.05))
        self.assertEqual(dropped, [True, 0, 1])
        self.assertEqual(again, [True, True, 1, True, True, 1, 1])
        self.assertEqual(cleared, [0, 0, True])

    def test_solid_copies_are_made_a_few_a_frame_and_a_kind_with_a_batch_waits_for_it(self):
        out = self.lua().execute('''
          sb.SOLID_PER_FRAME = 2
          local P = sb.new(nil)
          local K = P:kind('ped.dae')
          P:tick()
          local got = 0
          for k = 1, 5 do if P:addSolid(K, k, 0, 0, 0, 1, 0) then got = got + 1 end end
          local first = got
          P:tick()
          for k = 1, 5 do if P:addSolid(K, k, 0, 0, 0, 1, 0) then got = got + 1 end end
          -- a kind that is batched too: a batch copy until its batch is there, a static after
          local L = P:kind('pose.dae')
          L.batchToo = true
          P:tick()
          local B1 = P:addSolid(L, 0, 0, 0, 0, 1, 0)
          local B2 = P:addSolid(L, 0, 0, 0, 0, 1, 0)
          -- warmed: one hidden static, which the first copy takes
          local W = P:kind('van.dae')
          P:warmSolid(W)
          local made = STATIC.made
          local B3 = P:addSolid(W, 0, 0, 0, 0, 1, 0)
          return first, got, P.waits, B1.static == nil, B1 == L.batch, B2.static == true, STATIC.made == made, B3.live
        ''')
        self.assertEqual(tuple(out), (2, 4, 6, True, True, True, True, 1))

    def test_unused_solid_copies_go_after_a_while_but_a_few(self):
        out = self.lua().execute('''
          local P = sb.new(nil)
          local K = P:kind('car.dae')
          local h = {}
          for f = 1, 4 do
            P:tick()
            for k = 1, 5 do local B, i = P:addSolid(K, k, 0, 0, 0, 1, 0); if B then h[#h + 1] = {B, i} end end
          end
          local made = STATIC.alive
          for k = #h, 1, -1 do P:drop(h[k][1], h[k][2]) end
          for f = 1, 3000 do P:tick() end
          local B, i = P:addSolid(K, 1, 0, 0, 0, 1, 0)
          return made, STATIC.alive, P.solidObjects, B.objs[i].deleted == nil
        ''')
        self.assertEqual(tuple(out), (20, 4, 4, True))


if __name__ == '__main__':
    unittest.main()
