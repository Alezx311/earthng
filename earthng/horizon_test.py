"""Stale horizon blocks in native.lua (M.horizonCover, trimHorizon). Needs lupa (LuaJIT).
Run: python earthng/horizon_test.py"""
import os
import unittest

try:
    import lupa.luajit21 as lupa
except ImportError:  # pragma: no cover
    lupa = None

NATIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mod', 'lua', 'ge', 'extensions', 'e2r', 'native.lua')

# native.lua with its modules stubbed; `active` and `state` are set through its upvalues
HARNESS = r'''
local src, name = ...
for _, m in ipairs({'countries', 'generator', 'roads3', 'coordinates', 'cellformat', 'live', 'biome'}) do
  package.preload['ge/extensions/e2r/' .. m] = function() return {} end
end
package.preload['ge/extensions/e2r/quality'] = function()
  return {preset = function() return {} end, clamp = function(t) return t end}
end
local M = assert(loadstring(src, name))()
local function upvalue(f, want)
  for n = 1, 200 do
    local k, v = debug.getupvalue(f, n)
    if not k then return end
    if k == want then return n, v end
  end
end
local function set(f, want, value)
  local n = assert(upvalue(f, want), want)
  debug.setupvalue(f, n, value)
end
local _, trimHorizon = upvalue(M.release, 'trimHorizon')
return {
  M = M,
  trim = trimHorizon,
  setup = function(active, state)
    set(M.horizonCover, 'active', active); set(M.horizonCover, 'state', state)
    set(trimHorizon, 'active', active); set(trimHorizon, 'state', state)
  end,
}
'''


def table(lua, value):
    if isinstance(value, dict):
        t = lua.table()
        for k, v in value.items():
            t[k] = table(lua, v)
        return t
    return value


@unittest.skipIf(lupa is None, 'lupa.luajit21 not installed')
class HorizonCoverTest(unittest.TestCase):
    def setUp(self):
        self.lua = lupa.LuaRuntime()
        with open(NATIVE, encoding='utf-8') as f:
            src = f.read()
        self.h = self.lua.execute(HARNESS, src, 'native.lua')

    def world(self, desired, horizon):
        """desired: key -> {i, j, size?, horizon?}; horizon (built blocks): key -> {i, j, size}"""
        st = {'horizon': {k: dict(v, x=(v['i'] + .5) * v['size'], y=(v['j'] + .5) * v['size'], serial=1)
                          for k, v in horizon.items()}}
        self.active = table(self.lua, {'desired': desired, 'region': {'data': {'tileSize': 500}},
                                       'horizon': {}, 'evicted': {}, 'epoch': 1})
        self.state = table(self.lua, {'stream': st})
        self.h.setup(self.active, self.state)

    def cover(self, key):
        got = self.h.M.horizonCover(key)
        if got is None:
            return None
        return sorted((got[n][1], bool(got[n][2])) for n in range(1, len(got) + 1))

    def test_split_block_lists_quads_and_far_tiles(self):
        # a 1000 m block (x 2000-3000, y 0-1000) split as the car came near: two 500 m quads
        # and two far tiles; a 500 m neighbour sharing an edge only is not a replacement
        self.world({'h500:4_0': {'i': 4, 'j': 0, 'size': 500, 'horizon': True},
                    'h500:5_1': {'i': 5, 'j': 1, 'size': 500, 'horizon': True},
                    '4_1': {'i': 4, 'j': 1, 'size': 500, 'far': True},
                    '5_0': {'i': 5, 'j': 0, 'size': 500, 'far': True},
                    'h500:6_0': {'i': 6, 'j': 0, 'size': 500, 'horizon': True},
                    '3_1': {'i': 3, 'j': 1, 'size': 500, 'far': True}},
                   {'h1000:2_0': {'i': 2, 'j': 0, 'size': 1000}})
        self.assertEqual(self.cover('h1000:2_0'),
                         [('4_1', False), ('5_0', False), ('h500:4_0', True), ('h500:5_1', True)])

    def test_merged_block_replaces_quads(self):
        # leaving: the 500 m quads are stale under the new 1000 m block
        self.world({'h1000:2_0': {'i': 2, 'j': 0, 'size': 1000, 'horizon': True}},
                   {'h500:4_0': {'i': 4, 'j': 0, 'size': 500}, 'h1000:2_0': {'i': 2, 'j': 0, 'size': 1000}})
        self.assertEqual(self.cover('h500:4_0'), [('h1000:2_0', True)])
        self.assertIsNone(self.cover('h1000:2_0'))  # still wanted

    def test_landing_entry_without_size_uses_tile_size(self):
        self.world({'4_0': {'i': 4, 'j': 0}}, {'h1000:2_0': {'i': 2, 'j': 0, 'size': 1000}})
        self.assertEqual(self.cover('h1000:2_0'), [('4_0', False)])

    def test_nothing_wanted_over_it_is_an_empty_list(self):
        self.world({}, {'v4000:1_1': {'i': 1, 'j': 1, 'size': 4000}})
        self.assertEqual(self.cover('v4000:1_1'), [])
        self.assertIsNone(self.cover('unknown'))

    def test_one_list_per_wanted_set(self):
        self.world({'4_0': {'i': 4, 'j': 0, 'size': 500}}, {'h1000:2_0': {'i': 2, 'j': 0, 'size': 1000}})
        same = self.lua.eval('rawequal')
        first = self.h.M.horizonCover('h1000:2_0')
        self.assertTrue(same(self.h.M.horizonCover('h1000:2_0'), first))
        self.active.desired = table(self.lua, {'5_0': {'i': 5, 'j': 0, 'size': 500}})
        self.assertFalse(same(self.h.M.horizonCover('h1000:2_0'), first))
        self.assertEqual(self.cover('h1000:2_0'), [('5_0', False)])

    def test_trim_keeps_a_shown_stale_block(self):
        # over the count limit (96): undelivered stale blocks go, the shown one stays
        desired = {'h500:%d_0' % n: {'i': n, 'j': 0, 'size': 500, 'horizon': True, 'priority': 2e6 + n}
                   for n in range(100)}
        self.world(desired, {})
        self.active.horizonWanted = 0
        entries = {k: {'horizonTaken': True, 'horizonDelivered': True, 'used': 1, 'triangles': 0}
                   for k in desired}
        entries['h1000:900_0'] = {'horizonTaken': True, 'horizonDelivered': True, 'used': 0, 'triangles': 0}
        entries['h1000:901_0'] = {'used': 0, 'triangles': 10}
        self.active.horizon = table(self.lua, entries)
        self.h.trim()
        self.assertIsNotNone(self.active.horizon['h1000:900_0'])
        self.assertIsNone(self.active.horizon['h1000:901_0'])
        kept = sum(1 for _ in self.active.horizon.keys())
        self.assertEqual(kept, 97)  # 96 counted plus the shown stale block
        self.assertEqual(self.state.stream.horizonTiles, 96)


if __name__ == '__main__':
    unittest.main()
