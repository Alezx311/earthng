"""A real tile's layers as compiled shapes, without the game.

    python research/fast-tiles/tile_to_shapes.py --pack <earthng_x.zip> --lat 50.4504 --lon 30.5245 --out out/ft/tile [--far]

Builds the tile under the point with the generator (LuaJIT in lupa, the game's mesh structs), packs
each layer with tileshapes.lua and writes the shapes. Prints, per layer, what the game thread is
handed now (ProceduralMesh objects, triangles, materials) and what it would be handed instead
(shapes, their bytes, the meshes left as they are), the pack time, and which way the solid shape's
triangles face (the engine's front is clockwise: ground must face up).
"""
import argparse
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'earthng'))
import bench_native  # noqa: E402
import cdae  # noqa: E402

LUA = ROOT / 'mod' / 'lua' / 'ge' / 'extensions' / 'e2r'

BUILD = '''
local native, generator, shapes, i, j, far, outDir = ...
local function upvalue(f, name)
  for k = 1, 200 do local n, v = debug.getupvalue(f, k); if not n then return end; if n == name then return v end end
end
local active = upvalue(native.update, 'active')
local d = active.region.data
local loadCell = upvalue(upvalue(native.update, 'buildTile'), 'loadCell')
local function cellOf(ci, cj, keep)
  local co = coroutine.create(function() return loadCell(string.format('%d_%d', ci, cj), ci, cj, keep) end)
  while true do
    local ok, cell = coroutine.resume(co)
    if not ok then error(cell) end
    if coroutine.status(co) == 'dead' then return cell end
  end
end
local list = {}
local keep = {i * 500, j * 500, (i + 1) * 500, (j + 1) * 500}
for ci = math.floor((i * 500 - 40) / d.cellSize), math.floor((i * 500 + 540) / d.cellSize) do
  for cj = math.floor((j * 500 - 40) / d.cellSize), math.floor((j * 500 + 540) / d.cellSize) do
    local ok, c = pcall(cellOf, ci, cj, keep)
    if ok and c then list[#list + 1] = c end
  end
end
local t = clock()
local road, scene, farM = generator.build(list, i, j, {tileSize = 500, far = far, pause = function() end,
  seaLevel = d.seaLevel, latitude = d.geo and d.geo[4], geo = d.geo, nature = d.nature, look = d.look, realStyle = true,
  cellSize = d.cellSize})
local out = {buildMs = (clock() - t) * 1000, layers = {}}
for _, pair in ipairs({{'road', road}, {'scene', scene}, {'far', farM}}) do
  local layer, m = pair[1], pair[2]
  if m and m.items then
    local row = {layer = layer, kinds = {}, objects = 0, pairs = 0, tris = 0, materials = 0}
    local mats = {}
    for _, it in ipairs(m.items) do
      row.kinds[it.kind or '?'] = (row.kinds[it.kind or '?'] or 0) + 1
      if it.kind == 'proc' then
        row.objects, row.pairs = row.objects + 1, row.pairs + #it.meshes
        for _, mesh in ipairs(it.meshes) do
          row.tris = row.tris + #mesh.faces / 3
          if not mats[mesh.material] then mats[mesh.material] = true; row.materials = row.materials + 1 end
        end
      end
    end
    m.key = i .. '_' .. j
    local t1 = clock()
    local files = {}
    local stats = shapes.pack(m, layer,
      function(class) return outDir .. '/' .. i .. '_' .. j .. '_' .. layer .. '_' .. class .. '.cdae' end,
      function(path, bytes) local f = io_open(path, 'wb'); f:write(bytes); f:close(); files[#files + 1] = path end)
    row.packMs = (clock() - t1) * 1000
    row.stats, row.files = stats, files
    local left, leftTris = 0, 0
    for _, it in ipairs(m.items) do
      if it.kind == 'proc' then left = left + 1; leftTris = leftTris + (it.triangles or 0) end
    end
    row.leftObjects, row.leftTris = left, leftTris
    out.layers[#out.layers + 1] = row
  end
end
return out
'''


def facing(path):
    """Share of the shape's area whose engine front (clockwise) faces up, sideways, down."""
    shape = cdae.read(path)
    up = side = down = 0.0
    for mesh in shape['meshes']:
        n = mesh['verts'][0]
        pos = struct.unpack(f'<{n * 3}f', mesh['verts'][2])
        idx = struct.unpack(f"<{mesh['indices'][0]}I", mesh['indices'][2])
        for t in range(0, len(idx) - 2, 3):
            a, b, c = idx[t] * 3, idx[t + 1] * 3, idx[t + 2] * 3
            ux, uy, uz = pos[b] - pos[a], pos[b + 1] - pos[a + 1], pos[b + 2] - pos[a + 2]
            wx, wy, wz = pos[c] - pos[a], pos[c + 1] - pos[a + 1], pos[c + 2] - pos[a + 2]
            # clockwise front: the normal is w x u
            nx, ny, nz = wy * uz - wz * uy, wz * ux - wx * uz, wx * uy - wy * ux
            area = (nx * nx + ny * ny + nz * nz) ** .5
            if area <= 0:
                continue
            if nz > .5 * area:
                up += area
            elif nz < -.5 * area:
                down += area
            else:
                side += area
    total = up + side + down or 1
    return up / total, side / total, down / total, sum(m['verts'][0] for m in shape['meshes']), len(shape['materials'])


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', required=True)
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--far', action='store_true')
    p.add_argument('--jit', help="jit.opt.start arguments, comma separated (the game's GE Lua: "
                   "minstitch=10000000,maxtrace=10000,maxmcode=8192,maxside=25,hotexit=100)")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    lua, mods, _ = bench_native.runtime(a.pack, game_structs=True)
    load = lua.eval('function(source, name) return assert(load(source, "@" .. name))() end')
    g = lua.globals()
    if a.jit:
        lua.execute('jit.opt.start(' + ', '.join(repr(v) for v in a.jit.split(',')) + ')')
    # the bench replaced io.open with the pack's reader, and lupa hands a Lua string over as
    # text: the shape's bytes cross as hex
    g.py_write = lambda path, text: Path(path).write_bytes(bytes.fromhex(text))
    lua.execute("""io_open = function(path)
      local parts = {}
      return {write = function(_, data) parts[#parts + 1] = data end,
        close = function()
          local hex = {}
          local all = table.concat(parts)
          for at = 1, #all, 4096 do
            hex[#hex + 1] = (all:sub(at, at + 4095):gsub('.', function(c) return string.format('%02x', c:byte()) end))
          end
          py_write(path, table.concat(hex))
        end}
    end""")
    # the bench's require knows only its own modules
    lua.execute("mods.ffi, mods.bit = package.loaded.ffi, bit")
    for name in ('collision', 'cdae', 'tileshapes'):
        g.mods[name] = load((LUA / f'{name}.lua').read_text(encoding='utf8'), f'{name}.lua')
    native = mods['native']
    native.refresh()
    job = native.land(lua.table_from({'lat': a.lat, 'lon': a.lon, 'seq': 1}))
    if job['state'] == 'error':
        raise SystemExit(job['message'])
    x, y = native.localPoint(a.lat, a.lon)
    started = time.perf_counter()
    build = lua.eval('function(src) return assert(load(src, "@tile_to_shapes")) end')(BUILD)
    res = build(native, mods['generator'], g.mods['tileshapes'], int(x // 500), int(y // 500), a.far, str(a.out).replace('\\', '/'))
    print(f"tile {int(x // 500)}_{int(y // 500)}: generator {res['buildMs']:.0f} ms, all {time.perf_counter() - started:.1f} s")
    for row in res['layers'].values():
        kinds = ', '.join(f'{k} {v}' for k, v in sorted(row['kinds'].items()))
        print(f"\n{row['layer']}: items: {kinds}")
        print(f"  now:   {row['objects']} ProceduralMesh, {row['pairs']} pairs, {int(row['tris'])} triangles, {row['materials']} materials")
        st = row['stats']
        print(f"  packed: {st['shapes']} shapes for {st['objects']} objects, {int(st['triangles'])} triangles, {st['bytes'] / 1e6:.2f} MB,"
              f" pack {row['packMs']:.0f} ms; left as ProceduralMesh: {row['leftObjects']} ({int(row['leftTris'])} triangles)")
        for path in row['files'].values():
            up, side, down, verts, materials = facing(path)
            print(f"    {Path(path).name}: {verts} vertices, {materials} materials, {Path(path).stat().st_size / 1e6:.2f} MB;"
                  f" front faces up {up:.0%}, sideways {side:.0%}, down {down:.0%}")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    main()
