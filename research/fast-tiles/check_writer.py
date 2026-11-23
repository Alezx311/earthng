"""The Lua shape writer (mod/lua/ge/extensions/e2r/cdae.lua) against what the game cooked.

    python research/fast-tiles/check_writer.py <cooked.cdae>

Feeds a cooked shape's own vertices and triangles to the writer's tangent pass and compares with
the tangents the game baked: the share of vertices within 25 degrees, and whether the hand (w)
agrees. Then writes a small shape and reads it back with earthng/cdae.py.
"""
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'earthng'))
import cdae  # noqa: E402
from lupa import luajit21 as lupa  # noqa: E402

lua = lupa.LuaRuntime(unpack_returned_tuples=True)
writer = lua.execute(f"return dofile({str(ROOT / 'mod/lua/ge/extensions/e2r/cdae.lua')!r})")

TANGENTS = lua.eval('''
function(writer, n, pos, nor, uv, indices)
  return writer.tangents({n = n, pos = pos, nor = nor, uv = uv}, indices, #indices)
end''')


def tangents_against(path):
    shape = cdae.read(path)
    for i, mesh in enumerate(shape['meshes']):
        if mesh['type'] != 0 or not mesh['tangents'][0]:
            continue
        n = mesh['verts'][0]
        pos = struct.unpack(f'<{n * 3}f', mesh['verts'][2])
        nor = struct.unpack(f'<{n * 3}f', mesh['norms'][2])
        uv = struct.unpack(f'<{n * 2}f', mesh['tverts'][2])
        idx = struct.unpack(f"<{mesh['indices'][0]}I", mesh['indices'][2])
        baked = struct.unpack(f'<{n * 4}f', mesh['tangents'][2])
        ours = list(TANGENTS(writer, n, lua.table_from(pos), lua.table_from(nor), lua.table_from(uv),
                             lua.table_from(idx)).values())
        close = hand = 0
        for v in range(n):
            a, b = baked[v * 4:v * 4 + 4], ours[v * 4:v * 4 + 4]
            dot = sum(x * y for x, y in zip(a[:3], b[:3]))
            close += dot > math.cos(math.radians(25))
            hand += (a[3] < 0) == (b[3] < 0)
        print(f'mesh {i}: {n} vertices, tangent within 25 deg {close / n:.1%}, hand agrees {hand / n:.1%}')


def round_trip():
    build = lua.eval('''
    function(writer, path)
      local b = writer.builder()
      local verts, normals, uvs, faces = {}, {}, {}, {}
      for j = 0, 2 do for i = 0, 2 do
        verts[#verts + 1] = {x = i, y = j, z = (i + j) * .5}
        uvs[#uvs + 1] = {u = i * .5, v = -j * .5}
      end end
      normals[1] = {x = 0, y = 0, z = 1}
      for j = 0, 1 do for i = 0, 1 do
        local a = j * 3 + i
        for _, v in ipairs({a, a + 4, a + 1, a, a + 3, a + 4}) do faces[#faces + 1] = {v = v, n = 0, u = v} end
      end end
      b:add('solid', {verts = verts, normals = normals, uvs = uvs, faces = faces, material = 'e2rf_ground'})
      b:add('solid', {verts = verts, normals = normals, uvs = uvs, faces = faces, material = 'e2rf_road'}, 10, 0, 0)
      b:add('quiet', {verts = verts, normals = normals, uvs = uvs, faces = faces, material = 'e2rf_mark'}, 0, 10, 0)
      local data, stats = b:encode(2)
      local f = io.open(path, 'wb'); f:write(data); f:close()
      return #data, stats
    end''')
    out = ROOT / 'out' / 'ft' / 'check_writer.cdae'
    out.parent.mkdir(parents=True, exist_ok=True)
    size, stats = build(writer, str(out))
    data = out.read_bytes()
    shape = cdae.read(out)
    print('written', len(data), 'bytes;', dict(stats), '; left', shape['left'])
    print('names', shape['names'], 'materials', [m['name'] for m in shape['materials']])
    for mesh in shape['meshes']:
        prims = struct.unpack(f"<{mesh['primitives'][0] * 3}I", mesh['primitives'][2])
        print('  mesh: verts', mesh['verts'][0], 'indices', mesh['indices'][0], 'prims', prims, 'bounds', mesh['bounds'])
    # front faces are clockwise: the geometric normal by the counter-clockwise rule points down
    mesh = shape['meshes'][0]
    pos = struct.unpack(f"<{mesh['verts'][0] * 3}f", mesh['verts'][2])
    a, b, c = struct.unpack('<3I', mesh['indices'][2][:12])
    ux, uy = pos[b * 3] - pos[a * 3], pos[b * 3 + 1] - pos[a * 3 + 1]
    wx, wy = pos[c * 3] - pos[a * 3], pos[c * 3 + 1] - pos[a * 3 + 1]
    print('first triangle', 'clockwise (the engine front)' if ux * wy - uy * wx < 0 else 'COUNTER-CLOCKWISE')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    for path in sys.argv[1:]:
        tangents_against(path)
    round_trip()
