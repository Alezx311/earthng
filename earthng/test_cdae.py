"""The compiled-shape writers: earthng/cdae.py, mod/lua/ge/extensions/e2r/cdae.lua and tileshapes.lua.

    .venv\\Scripts\\python.exe -m unittest earthng.test_cdae
"""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cdae  # noqa: E402

LUA = HERE.parent / 'mod' / 'lua' / 'ge' / 'extensions' / 'e2r'

try:
    from lupa import luajit21 as lupa
except ImportError:  # pragma: no cover
    lupa = None


def triangles_of(mesh):
    """The mesh's triangles as sets of rounded corner positions, by material index."""
    n = mesh['verts'][0]
    pos = struct.unpack(f'<{n * 3}f', mesh['verts'][2])
    idx = struct.unpack(f"<{mesh['indices'][0]}I", mesh['indices'][2])
    prims = struct.unpack(f"<{mesh['primitives'][0] * 3}I", mesh['primitives'][2])
    out = {}
    for k in range(0, len(prims), 3):
        start, count, material = prims[k], prims[k + 1], prims[k + 2] & cdae.MATERIAL_MASK
        for t in range(start, start + count, 3):
            corners = tuple(tuple(round(v, 3) for v in pos[idx[t + c] * 3:idx[t + c] * 3 + 3]) for c in range(3))
            out.setdefault(material, []).append(corners)
    return out


class PythonWriter(unittest.TestCase):
    def test_a_written_shape_reads_back_whole(self):
        mesh = cdae.grid(4, size=8.0, materials=2)
        data = cdae.write(None, [mesh], visible_size=2.0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'grid.cdae'
            path.write_bytes(data)
            shape = cdae.read(path)
        self.assertEqual(shape['left'], 0)
        self.assertEqual(shape['version'] & 0xff, cdae.VERSION)
        self.assertEqual(shape['header']['bodysize'], shape['bodyBytes'])
        self.assertEqual([m['name'] for m in shape['materials']], ['e2r_cdae_test_0', 'e2r_cdae_test_1'])
        self.assertEqual(shape['meshes'][0]['verts'][0], 25)
        self.assertEqual(shape['meshes'][0]['indices'][0], 4 * 4 * 6)
        self.assertEqual(shape['meshes'][0]['tangents'][0], 25)
        # one detail level that names all its triangles
        detail = struct.unpack('<3i3fi2i2IfI', shape['details'][2])
        self.assertEqual(detail[6], 32)

    def test_the_grid_faces_up_for_the_engine(self):
        # the engine draws and collides the clockwise side (research/fast-tiles, p3b)
        mesh = cdae.grid(2, size=2.0)
        part = mesh['parts'][0][1]
        p = mesh['positions']
        a, b, c = (p[i * 3:i * 3 + 2] for i in part[:3])
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        self.assertLess(cross, 0)

    def test_a_whole_float_is_written_as_an_int(self):
        self.assertEqual(bytes(cdae.pack(cdae.F32(25.0), bytearray())), b'\x19')
        self.assertEqual(bytes(cdae.pack(1.5, bytearray())), b'\xca' + struct.pack('>f', 1.5))


@unittest.skipIf(lupa is None, 'lupa.luajit21 is not installed')
class LuaWriter(unittest.TestCase):
    def setUp(self):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute("package.path = %r .. package.path" % (str(LUA.parents[2]).replace('\\', '/') + '/?.lua;'))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def build(self, body):
        """Run `body` (Lua, given `writer`, `shapes` and `write(path, bytes)`), return what it returns."""
        fn = self.lua.eval('''function(folder, body)
          local writer = require('ge/extensions/e2r/cdae')
          local shapes = require('ge/extensions/e2r/tileshapes')
          local function write(path, bytes) local f = io.open(folder .. '/' .. path, 'wb'); f:write(bytes); f:close() end
          return assert(loadstring(body))(writer, shapes, write)
        end''')
        return fn(self.tmp.name.replace('\\', '/'), body)

    QUAD = '''
      local function quad(material, z)
        -- two triangles, clockwise from above; the corners share one normal
        local verts = {{x = 0, y = 0, z = z}, {x = 1, y = 0, z = z}, {x = 1, y = 1, z = z}, {x = 0, y = 1, z = z}}
        local uvs = {{u = 0, v = 0}, {u = 1, v = 0}, {u = 1, v = -1}, {u = 0, v = -1}}
        local faces = {}
        for _, v in ipairs({0, 2, 1, 0, 3, 2}) do faces[#faces + 1] = {v = v, n = 0, u = v} end
        return {verts = verts, normals = {{x = 0, y = 0, z = 1}}, uvs = uvs, faces = faces, material = material}
      end
    '''

    def test_meshes_become_one_object_with_a_part_a_material(self):
        stats = self.build(self.QUAD + '''
          local writer, shapes, write = ...
          local b = writer.builder()
          b:add('solid', quad('e2rf_road', 0))
          b:add('solid', quad('e2rf_ground', 0), 10, 0, 0)
          b:add('solid', quad('e2rf_road', 0), 20, 0, 0)
          local bytes, stats = b:encode(2)
          write('one.cdae', bytes)
          return stats
        ''')
        self.assertEqual(dict(stats), {'triangles': 6, 'objects': 1, 'materials': 2})
        shape = cdae.read(Path(self.tmp.name) / 'one.cdae')
        self.assertEqual(shape['left'], 0)
        self.assertEqual(shape['header']['objectNames'], ['solid'])
        self.assertEqual([m['name'] for m in shape['materials']], ['e2rf_road', 'e2rf_ground'])
        mesh = shape['meshes'][0]
        self.assertEqual(mesh['verts'][0], 12)          # a corner met again is one vertex
        by_material = triangles_of(mesh)
        self.assertEqual(len(by_material[0]), 4)
        self.assertEqual(len(by_material[1]), 2)
        # the second road quad stands 20 m along x
        self.assertIn(((20.0, 0.0, 0.0), (21.0, 1.0, 0.0), (21.0, 0.0, 0.0)), by_material[0])
        self.assertEqual(mesh['bounds'], [0, 0, 0, 21, 1, 0])

    def test_the_triangles_keep_the_generators_winding(self):
        self.build(self.QUAD + '''
          local writer, shapes, write = ...
          local b = writer.builder()
          b:add('solid', quad('m', 0))
          write('wind.cdae', (b:encode(2)))
        ''')
        mesh = cdae.read(Path(self.tmp.name) / 'wind.cdae')['meshes'][0]
        (a, b, c) = triangles_of(mesh)[0][0]
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        self.assertLess(cross, 0, 'clockwise from above: the side the engine draws')

    def test_tangents_lie_along_u_with_the_games_hand(self):
        self.build(self.QUAD + '''
          local writer, shapes, write = ...
          local b = writer.builder()
          b:add('solid', quad('m', 0))
          write('tan.cdae', (b:encode(2)))
        ''')
        mesh = cdae.read(Path(self.tmp.name) / 'tan.cdae')['meshes'][0]
        tangents = struct.unpack(f"<{mesh['tangents'][0] * 4}f", mesh['tangents'][2])
        for v in range(0, len(tangents), 4):
            self.assertAlmostEqual(tangents[v], 1.0, places=5)      # u grows along +x
            self.assertAlmostEqual(tangents[v + 1], 0.0, places=5)
            self.assertEqual(tangents[v + 3], -1.0)                 # as the game bakes a map that is not mirrored

    def test_a_block_boundary_loses_no_number(self):
        # the packer writes 64 numbers a block: counts on both sides of a block's edge
        values = self.build('''
          local writer = ...
          local out = {}
          for _, count in ipairs({1, 63, 64, 65, 200}) do
            local t = {}
            for k = 1, count do t[k] = k * .5 end
            out[#out + 1] = #writer.floatBytes(t, count) / 4
            local ints = {}
            for k = 1, count do ints[k] = k + 70000 end
            out[#out + 1] = #writer.uintBytes(ints, count) / 4
          end
          return table.concat(out, ' ')
        ''')
        self.assertEqual(values, '1 1 63 63 64 64 65 65 200 200')

    def test_a_class_past_the_engines_vertex_limit_is_several_meshes(self):
        # the engine's indices are 16-bit: 23.11 a town scene of one 150 000-vertex mesh drew beams across streets
        result = self.build(self.QUAD + '''
          local writer, shapes, write = ...
          writer.VERTICES = 10
          local b = writer.builder()
          for k = 1, 7 do b:add('solid', quad('m', 0), k * 2, 0, 0) end
          b:add('quiet', quad('m', 0))
          local bytes, stats = b:encode(2)
          write('split.cdae', bytes)
          return stats.objects, stats.triangles
        ''')
        self.assertEqual(tuple(result), (5, 16))
        shape = cdae.read(Path(self.tmp.name) / 'split.cdae')
        self.assertEqual(shape['header']['objectNames'], ['solid', 'solid_2', 'solid_3', 'solid_4', 'quiet'])
        for mesh in shape['meshes']:
            self.assertLessEqual(mesh['verts'][0], 10)
            indices = struct.unpack(f"<{mesh['indices'][0]}I", mesh['indices'][2])
            self.assertLess(max(indices), mesh['verts'][0])

    def test_the_python_writer_refuses_a_mesh_past_the_limit(self):
        mesh = cdae.grid(256)       # 257 x 257 vertices
        with self.assertRaises(ValueError):
            cdae.write(None, [mesh])

    def test_a_layer_is_packed_by_collision_class(self):
        result = self.build(self.QUAD + '''
          local writer, shapes, write = ...
          local function item(material, extra)
            local it = {kind = 'proc', name = 'x', pos = {250, 250, 0}, meshes = {quad(material, 0)}, triangles = 2, layer = 'road'}
            for k, v in pairs(extra or {}) do it[k] = v end
            return it
          end
          local manifest = {key = '0_0', items = {
            item('e2rf_road_asphalt'),                       -- the car drives on it
            item('e2rf_mark'),                               -- drawn only
            item('e2rf_col_ground', {proxy = true, cell = {1, 1, 64}}),   -- a hidden proxy: left alone
            {kind = 'static', shape = '/levels/x/tree.dae', pos = {1, 2, 3}},
            item('e2rf_kerb'),
          }}
          local stats = shapes.pack(manifest, 'road', function(class) return 'road_' .. class .. '.cdae' end, write)
          local kinds = {}
          for _, it in ipairs(manifest.items) do
            kinds[#kinds + 1] = it.kind .. (it.kind == 'shape' and ((it.solid and ':solid:' or ':quiet:') .. it.triangles .. ':' .. table.concat(it.mats, '+')) or '')
          end
          return table.concat(kinds, ' '), stats.shapes, stats.objects, stats.left
        ''')
        kinds, shapes_made, objects, left = result
        self.assertEqual(kinds, 'proc static shape:solid:4:e2rf_road_asphalt+e2rf_kerb shape:quiet:2:e2rf_mark')
        self.assertEqual((shapes_made, objects, left), (2, 3, 1))
        solid = cdae.read(Path(self.tmp.name) / 'road_solid.cdae')
        self.assertEqual([m['name'] for m in solid['materials']], ['e2rf_road_asphalt', 'e2rf_kerb'])

    def test_a_class_is_cut_into_files_of_a_few_materials(self):
        # a new shape file holds a frame ~1.3 ms for each of its materials: a hundred in one was 110-230 ms
        result = self.build(self.QUAD + '''
          local writer, shapes, write = ...
          shapes.MATERIALS = 3
          local items = {}
          for k = 1, 7 do
            items[k] = {kind = 'proc', pos = {0, 0, 0}, meshes = {quad('e2rf_wall_' .. k, 0)}, triangles = 2, layer = 'far'}
          end
          -- a material met again goes where its first mesh went
          items[8] = {kind = 'proc', pos = {5, 0, 0}, meshes = {quad('e2rf_wall_2', 0)}, triangles = 2, layer = 'far'}
          local manifest = {key = '0_0', items = items}
          local stats = shapes.pack(manifest, 'far', function(name) return 'cut_' .. name .. '.cdae' end, write)
          local out = {}
          for _, it in ipairs(manifest.items) do out[#out + 1] = it.name .. '=' .. #it.mats .. ':' .. it.triangles end
          return table.concat(out, ' '), stats.shapes
        ''')
        names, count = result
        self.assertEqual(names, 'e2rs_0_0_far_solid=3:8 e2rs_0_0_far_solid2=3:6 e2rs_0_0_far_solid3=1:2')
        self.assertEqual(count, 3)
        first = cdae.read(Path(self.tmp.name) / 'cut_solid.cdae')
        self.assertEqual([m['name'] for m in first['materials']], ['e2rf_wall_1', 'e2rf_wall_2', 'e2rf_wall_3'])

    def test_a_far_layer_is_one_solid_shape(self):
        kinds = self.build(self.QUAD + '''
          local writer, shapes, write = ...
          local manifest = {key = '0_0', items = {
            {kind = 'proc', pos = {0, 0, 0}, meshes = {quad('e2rf_mark', 0), quad('e2rf_ground', 0)}, triangles = 4, layer = 'far'}}}
          shapes.pack(manifest, 'far', function(class) return 'far_' .. class .. '.cdae' end, write)
          return manifest.items[1].kind .. ' ' .. tostring(manifest.items[1].solid) .. ' ' .. #manifest.items
        ''')
        self.assertEqual(kinds, 'shape true 1')


if __name__ == '__main__':
    unittest.main()
