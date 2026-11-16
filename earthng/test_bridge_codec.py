"""The tile pool's message codec (mod/lua/ge/extensions/e2r/bridge_codec.lua) under LuaJIT.

Run with: python -m unittest discover -s earthng -p test_bridge_codec.py
"""
from pathlib import Path
import unittest

from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
CODEC = ROOT / 'mod/lua/ge/extensions/e2r/bridge_codec.lua'

# the game's mesh struct, as generator.lua finds it when vec3 exists
STRUCTS = """
  local ffi = require('ffi')
  ffi.cdef('struct __luaVec3_t { double x, y, z; };')
  vec3 = ffi.typeof('struct __luaVec3_t')
"""

ROUND_TRIP = r"""
  local codec, base = ...
  local ffi = require('ffi')
  local V = ffi.typeof('struct __luaVec3_t')
  -- e2r_face_t / e2r_uv_t are declared by the codec on first use
  codec.encode({V(0, 0, 0)})
  local F, U = ffi.typeof('e2r_face_t'), ffi.typeof('e2r_uv_t')
  local shared = {name = 'mat', 1, 2}
  local verts = {}
  for k = 1, 3001 do verts[k] = V(k, -k * .5, k % 7) end
  local mesh = {verts = verts, odd = {V(1, 2, 3), V(-4.5, 1e300, -0.0)}, faces = {F(0, 1, 2), F(-1, 7, 2147483647), F(3, 4, 5)},
    uvs = {U(.25, .75)}, one = V(9, 8, 7)}
  local root = {mesh = mesh, a = shared, b = shared, list = {1, 2.5, -3, 'x\0y', true, false},
    big = 2^40, neg = -0.0, frac = 1 / 3, [7] = 'seven', nested = {{}, {{}}}, s = ('z'):rep(70000)}
  local s = codec.encode(root)
  if base > 0 then s = ('h'):rep(base) .. s end
  local back = codec.decode(s, nil, nil, base)
  assert(back.a == back.b, 'a shared table stays shared')
  assert(back.a.name == 'mat' and back.a[2] == 2)
  assert(back.list[2] == 2.5 and back.list[4] == 'x\0y' and back.list[5] == true and back.list[6] == false)
  assert(back.big == 2^40 and back.frac == 1 / 3 and back[7] == 'seven' and #back.s == 70000)
  assert(1 / back.neg < 0, 'negative zero')
  local v = back.mesh.verts
  assert(#v == 3001 and ffi.istype(V, v[1]) and v[3001].x == 3001 and v[3001].y == -1500.5 and v[3001].z == 3001 % 7)
  local o = back.mesh.odd
  assert(o[2].y == 1e300 and 1 / o[2].z < 0)
  local f = back.mesh.faces
  assert(#f == 3 and ffi.istype(F, f[2]) and f[2].v == -1 and f[2].u == 2147483647 and f[3].u == 5)
  assert(back.mesh.uvs[1].v == .75 and back.mesh.one.z == 7)
  assert(#back.nested == 2 and #back.nested[2] == 1)
  return true
"""


class CodecTests(unittest.TestCase):
    def make(self, structs=True):
        lua = LuaRuntime()
        if structs:
            lua.execute(STRUCTS)
        codec = lua.execute(CODEC.read_text(encoding='utf8'))
        return lua, codec

    def test_round_trip_keeps_values_shared_tables_and_mesh_arrays(self):
        lua, codec = self.make()
        self.assertTrue(lua.execute(ROUND_TRIP, codec, 0))

    def test_round_trip_after_a_frame_header(self):
        # the game decodes a PART in place, past its 16-byte header
        lua, codec = self.make()
        self.assertTrue(lua.execute(ROUND_TRIP, codec, 16))

    def test_canonical_encoding_ignores_insertion_order(self):
        lua, codec = self.make()
        same = lua.execute("""
          local codec = ...
          local a, b = {}, {}
          for k = 1, 200 do a['k' .. k] = k end
          for k = 200, 1, -1 do b['k' .. k] = k end
          a.sub, b.sub = {x = 1, y = 2, [1.5] = 3}, {[1.5] = 3, y = 2, x = 1}
          return codec.encode(a, true) == codec.encode(b, true)
        """, codec)
        self.assertTrue(same)

    def test_plain_tables_without_the_games_structs(self):
        lua, codec = self.make(structs=False)
        ok = lua.execute("""
          local codec = ...
          local back = codec.decode(codec.encode({verts = {{x = 1, y = 2, z = 3}}, n = 4}))
          return back.verts[1].y == 2 and back.n == 4
        """, codec)
        self.assertTrue(ok)

    def test_truncated_or_foreign_input_is_refused(self):
        lua, codec = self.make()
        result = lua.execute("""
          local codec = ...
          local s = codec.encode({1, 2, {x = 'y'}})
          local out = {}
          for _, bad in ipairs({s:sub(1, #s - 1), 'XXXX' .. s:sub(5), '', s .. 'z'}) do
            out[#out + 1] = pcall(codec.decode, bad) and 'accepted' or 'refused'
          end
          return table.concat(out, ',')
        """, codec)
        self.assertEqual(result, 'refused,refused,refused,refused')

    def test_decode_pauses_often_inside_long_arrays(self):
        lua, codec = self.make()
        pauses = lua.execute("""
          local codec = ...
          local V = require('ffi').typeof('struct __luaVec3_t')
          local verts = {}
          for k = 1, 20000 do verts[k] = V(k, 0, 0) end
          local n = 0
          local back = codec.decode(codec.encode({verts = verts}), nil, function() n = n + 1 end)
          assert(back.verts[20000].x == 20000)
          return n
        """, codec)
        self.assertGreaterEqual(pauses, 30)

    def test_a_small_message_while_a_big_one_waits_at_a_pause(self):
        # the stats of a finished job are decoded while a tile's decode is suspended
        lua, codec = self.make()
        ok = lua.execute("""
          local codec = ...
          local V = require('ffi').typeof('struct __luaVec3_t')
          local verts = {}
          for k = 1, 30000 do verts[k] = V(k, k, k) end
          local big = codec.encode({verts = verts})
          local co = coroutine.create(function() return codec.decode(big, nil, coroutine.yield) end)
          assert(coroutine.resume(co))
          local small = codec.decode(codec.encode({ms = 12.5, stage = {a = 1}}))
          assert(small.ms == 12.5 and small.stage.a == 1)
          -- and a second big one gets its own views
          local other = codec.decode(codec.encode({verts = {V(5, 6, 7)}, pad = ('p'):rep(80000)}))
          assert(other.verts[1].y == 6)
          local back
          while coroutine.status(co) ~= 'dead' do
            local okR, value = coroutine.resume(co)
            assert(okR, value)
            back = value or back
          end
          return back.verts[30000].z == 30000
        """, codec)
        self.assertTrue(ok)


if __name__ == '__main__':
    unittest.main()
