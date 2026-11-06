"""Tests of detail.lua (the grass and rock cells round the camera), in LuaJIT through lupa.
Run: python earthng/detail_test.py"""
import os
import unittest

try:
    from lupa import luajit21 as lupa
except ImportError:  # pragma: no cover
    lupa = None

DETAIL = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mod', 'lua', 'ge', 'extensions', 'e2r', 'detail.lua')

# The expansion as detail.lua did it from a list of patch tables (before part.flat): the reference
REFERENCE = r'''
return function(statics, patches)
  local out = {n = 0, x = {}, y = {}, z = {}, yaw = {}, scale = {}, shape = {}}
  local function put(x, y, z, yaw, scale, shape)
    local n = out.n + 1; out.n = n
    out.x[n], out.y[n], out.z[n], out.yaw[n], out.scale[n], out.shape[n] = x, y, z, yaw, scale, shape
  end
  for _, s in ipairs(statics) do put(s[1], s[2], s[3], s[4], s[5], s[6]) end
  for _, patch in ipairs(patches) do
    for k = 1, #patch.samples, 4 do
      local slot, z, gx, gy = patch.samples[k], patch.samples[k+1], patch.samples[k+2], patch.samples[k+3]
      local x = patch.x + (slot % 4) * 2 + 1
      local y = patch.y + math.floor(slot / 4) * 2 + 1
      for iy = -1, 1 do for ix = -1, 1 do
        local h = math.floor(x) * 73856093 + math.floor(y) * 19349663 + (ix + 2) * 83492791 + (iy + 2) * 2654435761
        h = h % 2147483647
        if h < 0 then h = h + 2147483647 end
        local dx = ix * (2 / 3) + ((h % 101) / 100 - .5) * .12
        local dy = iy * (2 / 3) + ((math.floor(h / 101) % 101) / 100 - .5) * .12
        local model = h % 3 + 1
        local height = .32 + (math.floor(h / 10201) % 101) / 100 * .18
        local scale = height / patch.spans[model]
        put(x + dx, y + dy, z + gx * dx + gy * dy - patch.bottoms[model] * scale, h % 6283 / 1000, scale, patch.shapes[model])
      end end
    end
  end
  return out
end
'''

# Random patches and statics over a few cells (west and south of the origin too), two tiles
SETUP = r'''
math.randomseed(7)
local shapes = {'/art/shapes/3d_grass/a.dae', '/art/shapes/3d_grass/b.dae', '/art/shapes/3d_grass/c.dae'}
local spans, bottoms = {.5, .6, .7}, {.01, -.02, .03}
local items, byPart = {}, {}
for t = 1, 2 do
  for n = 1, 300 do
    local ox, oy = 8 * math.random(-6, 6), 8 * math.random(-6, 6)
    local it
    if n % 7 == 0 then
      it = {kind = 'static', shape = '/art/shapes/rocks/r' .. (n % 3) .. '.dae', pos = {ox + math.random() * 8, oy + math.random() * 8, math.random() * 50},
        rot = {0, 0, math.random() - .5, math.random()}, scale = .5 + math.random()}
    else
      local samples = {}
      for slot = 0, 15 do
        if math.random() < .6 then
          samples[#samples + 1], samples[#samples + 2] = slot, 40 + math.random() * 10
          samples[#samples + 1], samples[#samples + 2] = math.random() * .2 - .1, math.random() * .2 - .1
        end
      end
      if #samples == 0 then samples = {5, 41, 0, 0} end
      it = {kind = 'static', shape = shapes[1], pos = {ox + 1, oy + 1, samples[2]}, rot = {0, 0, 0, 1}, scale = 1,
        grassPatch = {x = ox, y = oy, shapes = shapes, spans = spans, bottoms = bottoms, samples = samples}}
    end
    items[#items + 1] = {t, it}
  end
end
return items
'''


@unittest.skipIf(lupa is None, 'lupa.luajit21 not installed')
class Expand(unittest.TestCase):
    def setUp(self):
        self.lua = lupa.LuaRuntime()
        with open(DETAIL, encoding='utf-8') as f:
            self.lua.execute('DETAIL = (function() ' + f.read() + ' end)()')
        self.lua.globals().REFERENCE = self.lua.execute(REFERENCE)
        self.lua.globals().ITEMS = self.lua.execute(SETUP)

    def test_compact_parts_expand_to_the_same_tufts(self):
        compared, mismatches, cells = self.lua.execute(r'''
        local stream = DETAIL.new(function() end, function() end)
        local tiles = {{i = 0, j = 0}, {i = 1, j = 0}}
        -- the reference keeps each part's statics and patch tables as they came
        local ref = {}
        for _, entry in ipairs(ITEMS) do
          local tile, it = tiles[entry[1]], entry[2]
          local kind = DETAIL.kind(it)
          if stream:add(tile, it) then
            local width = kind == 'grass' and DETAIL.GRASS_CELL or DETAIL.CELL
            local key = kind .. ':' .. math.floor(it.pos[1] / width) .. ':' .. math.floor(it.pos[2] / width)
            ref[key] = ref[key] or {}
            local r = ref[key][tile] or {statics = {}, patches = {}}
            ref[key][tile] = r
            if it.grassPatch then r.patches[#r.patches + 1] = it.grassPatch
            else
              local rot = it.rot
              r.statics[#r.statics + 1] = {it.pos[1], it.pos[2], it.pos[3], 2 * math.atan2(rot[3], rot[4]), it.scale, it.shape}
            end
          end
        end
        local compared, mismatches, cells = 0, 0, 0
        for key, parts in pairs(ref) do
          cells = cells + 1
          for tile, r in pairs(parts) do
            local a, b = REFERENCE(r.statics, r.patches), DETAIL.expand(stream.cells[key].parts[tile])
            if a.n ~= b.n then mismatches = mismatches + 1 end
            for k = 1, a.n do
              compared = compared + 1
              if a.x[k] ~= b.x[k] or a.y[k] ~= b.y[k] or a.z[k] ~= b.z[k] or a.yaw[k] ~= b.yaw[k]
                or a.scale[k] ~= b.scale[k] or a.shape[k] ~= b.shape[k] then mismatches = mismatches + 1 end
            end
          end
        end
        return compared, mismatches, cells
        ''')
        self.assertGreater(compared, 10000)
        self.assertGreater(cells, 50)
        self.assertEqual(mismatches, 0)

    def test_a_patch_part_has_no_static_arrays(self):
        fields = self.lua.execute(r'''
        local stream = DETAIL.new(function() end, function() end)
        local tile = {i = 0, j = 0}
        stream:add(tile, {kind = 'static', shape = '/art/shapes/3d_grass/a.dae', pos = {1, 1, 0}, rot = {0, 0, 0, 1}, scale = 1,
          grassPatch = {x = 0, y = 0, shapes = {'a', 'b', 'c'}, spans = {1, 1, 1}, bottoms = {0, 0, 0}, samples = {0, 0, 0, 0}}})
        local part = stream.cells['grass:0:0'].parts[tile]
        local n = 0
        for _ in pairs(part) do n = n + 1 end
        return n, part.x == nil, #part.flat
        ''')
        self.assertEqual(fields[0], 6)        # tile, serial, n, staticN, zSum, flat
        self.assertTrue(fields[1])
        self.assertEqual(fields[2], 6 + 4)    # the patch header and one sample


if __name__ == '__main__':
    unittest.main()
