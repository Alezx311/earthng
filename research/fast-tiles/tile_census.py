"""What a near tile is made of, without the game: the generator's time by stage and the scene's
geometry by material and by patch.

    python research/fast-tiles/tile_census.py --pack <earthng_x.zip> --lat 50.4504 --lon 30.5245 [--patch 125]

Builds the tile under the point as a worker VM does (LuaJIT in lupa with a vehicle VM's trace
limits, the collector stopped) and prints:
  - the generator's ms by stage (options.mark), and where the road and the scene went out;
  - each layer: ProceduralMesh objects, triangles, materials, statics;
  - the scene's triangles by material family, heaviest first;
  - how the scene's triangles, materials and statics fall into patches of --patch metres (a
    triangle by its first corner): what the game thread would be handed patch by patch;
  - what a collision rebuild takes of each layer (collision.lua): the triangles of its solid
    meshes, of its quiet ones, and of its proxies with the cells they lie in.
--option shell=false builds the scene as it collided until 24.11 (a building's own meshes solid).
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'earthng'))
import bench_native  # noqa: E402

VM_JIT = 'minstitch=10000000,maxtrace=2000,maxmcode=4000,maxside=10,hotexit=200'

BUILD = '''
local native, generator, i, j, far, patch, extra, collision = ...
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
collectgarbage('collect')
collectgarbage('stop')
local out = {stages = {}, order = {}, layers = {}}
local t0 = clock()
local last, lastStage = t0, 'start'
local function mark(stage)
  local now = clock()
  if not out.stages[stage] then out.order[#out.order + 1] = stage end
  out.stages[stage] = (out.stages[stage] or 0) + (now - last) * 1000
  last = now
end
local options = {tileSize = 500, far = far, pause = function() end, mark = mark,
  seaLevel = d.seaLevel, latitude = d.geo and d.geo[4], geo = d.geo, nature = d.nature, look = d.look, realStyle = true,
  cellSize = d.cellSize, hyper = true, farStep = 100, adaptiveFar = true}
for k, v in pairs(extra or {}) do options[k] = v end
if not far then
  options.roadReady = function() out.roadAt = (clock() - t0) * 1000 end
  options.sceneReady = function() out.sceneAt = (clock() - t0) * 1000 end
end
local road, scene, farM, nav, grass = generator.build(list, i, j, options)
mark('end')
out.buildMs = (clock() - t0) * 1000
out.garbageMB = collectgarbage('count') / 1024
local x0, y0 = i * 500, j * 500
for _, pair in ipairs({{'road', road}, {'scene', scene}, {'grass', grass}, {'far', farM}}) do
  local layer, m = pair[1], pair[2]
  if m and m.items then
    local row = {layer = layer, kinds = {}, objects = 0, tris = 0, materials = 0, byMaterial = {}, patches = {}, statics = 0,
      solid = 0, quiet = 0, proxy = 0, cells = 0, solidBy = {}}
    local cells = {}
    local mats = {}
    local function cell(x, y)
      local px, py = math.max(0, math.min(500 / patch - 1, math.floor((x - x0) / patch))), math.max(0, math.min(500 / patch - 1, math.floor((y - y0) / patch)))
      local key = px .. ',' .. py
      local c = row.patches[key]
      if not c then c = {tris = 0, statics = 0, mats = {}, materials = 0}; row.patches[key] = c end
      return c
    end
    for _, it in ipairs(m.items) do
      row.kinds[it.kind or '?'] = (row.kinds[it.kind or '?'] or 0) + 1
      if it.kind == 'proc' then
        -- as tileshapes.lua and world.lua class it
        local n = 0
        for _, mesh in ipairs(it.meshes) do n = n + #mesh.faces / 3 end
        if it.proxy then
          row.proxy = row.proxy + n
          local ck = it.cell[1] .. ',' .. it.cell[2] .. ',' .. it.cell[3]
          if not cells[ck] then cells[ck] = true; row.cells = row.cells + 1 end
        elseif not it.forceCollision and collision.quiet(it.meshes, it.layer or layer) then
          row.quiet = row.quiet + n
        else
          row.solid = row.solid + n
          for _, mesh in ipairs(it.meshes) do
            row.solidBy[mesh.material or '?'] = (row.solidBy[mesh.material or '?'] or 0) + #mesh.faces / 3
          end
        end
      end
      if it.kind == 'proc' and not it.proxy then
        row.objects = row.objects + 1
        local ox, oy = it.pos[1], it.pos[2]
        for _, mesh in ipairs(it.meshes) do
          local name = mesh.material or '?'
          local v, f = mesh.verts, mesh.faces
          local n = #f / 3
          row.tris = row.tris + n
          row.byMaterial[name] = (row.byMaterial[name] or 0) + n
          if not mats[name] then mats[name] = true; row.materials = row.materials + 1 end
          for t = 1, #f - 2, 3 do
            local a = v[f[t].v + 1]
            local c = cell(a.x + ox, a.y + oy)
            c.tris = c.tris + 1
            if not c.mats[name] then c.mats[name] = true; c.materials = c.materials + 1 end
          end
        end
      elseif it.kind ~= 'proc' and type(it.pos) == 'table' then
        row.statics = row.statics + 1
        local c = cell(it.pos[1], it.pos[2])
        c.statics = c.statics + 1
      end
    end
    for _, c in pairs(row.patches) do c.mats = nil end
    out.layers[#out.layers + 1] = row
  end
end
return out
'''


def family(material):
    name = material[5:] if material.startswith('e2rf_') else material
    for prefix, label in (('kw_', 'kit'), ('hw_', 'house wall'), ('wall_', 'wall'), ('clad_', 'cladding'), ('roof', 'roof'),
                          ('sh_', 'sheet facade'), ('shop', 'shop'), ('win', 'window'), ('door', 'door'), ('house_cells', 'house openings'),
                          ('fence', 'fence'), ('mark', 'marking'), ('road', 'road'), ('sidewalk', 'sidewalk'), ('curb', 'curb'),
                          ('poi', 'poi'), ('sign', 'sign'), ('farmap', 'far map'), ('ground', 'ground')):
        if name.startswith(prefix):
            return label
    return name


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', required=True)
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--patch', type=int, default=125)
    p.add_argument('--far', action='store_true')
    p.add_argument('--jit', default=VM_JIT)
    p.add_argument('--option', action='append', default=[], help='name=value for the generator (true, false or a number)')
    p.add_argument('--materials', type=int, default=24, help='material rows to print')
    p.add_argument('--names', action='store_true', help='every material of a layer with its triangles')
    p.add_argument('--quality', type=int, default=50, help="the game's quality preset the tile is built with")
    p.add_argument('--around', type=int, default=0, help='also the tiles this many steps round it, a line each')
    a = p.parse_args()
    lua, mods, _ = bench_native.runtime(a.pack, game_structs=True, kit=True, houses=True)
    g = lua.globals()
    lua.execute('jit.opt.start(' + ', '.join(repr(v) for v in a.jit.split(',')) + ')')
    lua.execute("mods.ffi, mods.bit = package.loaded.ffi, bit")
    native = mods['native']
    native.refresh()
    job = native.land(lua.table_from({'lat': a.lat, 'lon': a.lon, 'seq': 1}))
    if job['state'] == 'error':
        raise SystemExit(job['message'])
    x, y = native.localPoint(a.lat, a.lon)
    extra = {}
    tune = mods['quality'].preset(a.quality)
    for name in ('maxTrees', 'maxFarTrees', 'maxGrass', 'maxRocks', 'forestSpacing', 'groundSpacing', 'groundTrees',
                 'parkedCars', 'propSpacing', 'detail'):
        extra[name] = tune[name]
    for item in a.option:
        name, _, value = item.partition('=')
        extra[name] = True if value == 'true' else False if value == 'false' else float(value)
    build = lua.eval('function(src) return assert(load(src, "@tile_census")) end')(BUILD)
    collision = lua.eval('function(source) return assert(load(source, "@collision.lua"))() end')(
        (ROOT / 'mod/lua/ge/extensions/e2r/collision.lua').read_text(encoding='utf8'))
    if a.around:
        print('tile: generator ms (road out, scene out) | scene triangles / materials / statics | grass statics | collision triangles | stages')
        for dj in range(a.around, -a.around - 1, -1):
            for di in range(-a.around, a.around + 1):
                i, j = int(x // 500) + di, int(y // 500) + dj
                r = build(native, mods['generator'], i, j, a.far, a.patch, lua.table_from(extra), collision)
                rows = {row['layer']: row for row in r['layers'].values()}
                sc, gr = rows.get('scene'), rows.get('grass')
                top = sorted(((r['stages'][n], n) for n in r['order'].values()), reverse=True)[:5]
                rd = rows.get('road')
                print(f"{i}_{j}: {r['buildMs']:5.0f} ({r['roadAt'] or 0:4.0f}, {r['sceneAt'] or 0:4.0f}) | "
                      f"{int(sc['tris']) if sc else 0:6d} / {sc['materials'] if sc else 0:3d} / {sc['statics'] if sc else 0:4d} | "
                      f"{gr['statics'] if gr else 0:4d} | solid road {int(rd['solid']) if rd else 0}, scene {int(sc['solid']) if sc else 0},"
                      f" proxies {int((rd['proxy'] if rd else 0) + (sc['proxy'] if sc else 0))} | "
                      + ', '.join(f'{n} {ms:.0f}' for ms, n in top))
        return
    started = time.perf_counter()
    res = build(native, mods['generator'], int(x // 500), int(y // 500), a.far, a.patch, lua.table_from(extra), collision)
    print(f"tile {int(x // 500)}_{int(y // 500)}: generator {res['buildMs']:.0f} ms, garbage {res['garbageMB']:.0f} MB,"
          f" road out at {res['roadAt'] or 0:.0f} ms, scene out at {res['sceneAt'] or 0:.0f} ms (all {time.perf_counter() - started:.1f} s)")
    print('stages, ms: ' + ', '.join(f"{name} {res['stages'][name]:.0f}" for name in res['order'].values()))
    for row in res['layers'].values():
        kinds = ', '.join(f'{k} {v}' for k, v in sorted(row['kinds'].items()))
        print(f"\n{row['layer']}: {row['objects']} ProceduralMesh, {int(row['tris'])} triangles, {row['materials']} materials,"
              f" {row['statics']} statics; items: {kinds}")
        fam = {}
        for material, n in row['byMaterial'].items():
            f = family(material)
            fam.setdefault(f, [0, 0])
            fam[f][0] += n
            fam[f][1] += 1
        top = sorted(fam.items(), key=lambda kv: -kv[1][0])[:a.materials]
        print('  by family (triangles / materials): ' + ', '.join(f'{k} {int(v[0])}/{v[1]}' for k, v in top))
        solid = sorted(row['solidBy'].items(), key=lambda kv: -kv[1])[:14]
        print(f"  collision: solid {int(row['solid'])} triangles, quiet {int(row['quiet'])}, proxies {int(row['proxy'])} in {row['cells']} cells;"
              ' solid by material: ' + ', '.join(f'{k[5:] if k.startswith("e2rf_") else k} {int(v)}' for k, v in solid))
        if a.names:
            names = sorted(row['byMaterial'].items(), key=lambda kv: -kv[1])
            print('  materials: ' + ', '.join(f'{k[5:] if k.startswith("e2rf_") else k} {int(v)}' for k, v in names))
        cells = row['patches']
        n = 500 // a.patch
        print(f'  patches of {a.patch} m (triangles / materials / statics), north at the top:')
        pairs = 0
        for py in range(n - 1, -1, -1):
            line = []
            for px in range(n):
                c = cells[f'{px},{py}'] if f'{px},{py}' in cells else None
                if c:
                    pairs += c['materials']
                    line.append(f"{int(c['tris']):6d}/{int(c['materials']):3d}/{int(c['statics']):4d}")
                else:
                    line.append(' ' * 15)
            print('    ' + '  '.join(line))
        print(f'  material slots over the patches: {pairs} (the layer whole: {row["materials"]})')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    main()
