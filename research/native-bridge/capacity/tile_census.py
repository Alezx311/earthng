"""What a tile hands the game: items by kind, ProceduralMesh objects/pairs/verts/tris, statics,
Forest plants, grass, and the EMC2 bytes of each layer (offline, LuaJIT via lupa).

    .venv/Scripts/python.exe research/native-bridge/capacity/tile_census.py <pack.zip> <lat> <lon> <radius tiles>
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'earthng'))
import bench_native, mesh_pairs

COUNT = mesh_pairs.COUNT.split('local t = clock()')[0] + r'''
  local t = clock()
  local road, scene, farM = generator.build(list, i, j, {tileSize = 500, far = far, pause = function() end, seaLevel = d.seaLevel,
    latitude = d.geo and d.geo[4], nature = d.nature, look = d.look})
  local ms = (clock() - t) * 1000
  local codec = require('ge/extensions/e2r/bridge_codec')
  local row = {key = i .. '_' .. j, ms = ms}
  for name, m in pairs({road = road, scene = scene}) do
    local r = {kinds = {}, objects = 0, pairs = 0, tris = 0, verts = 0, shapes = {}, nshapes = 0}
    for _, it in ipairs(m and m.items or {}) do
      r.kinds[it.kind or '?'] = (r.kinds[it.kind or '?'] or 0) + 1
      if it.kind == 'proc' then
        r.objects = r.objects + 1
        r.pairs = r.pairs + #it.meshes
        for _, mesh in ipairs(it.meshes) do r.tris = r.tris + #mesh.faces / 3; r.verts = r.verts + #mesh.verts end
      elseif it.shape then
        if not r.shapes[it.shape] then r.nshapes = r.nshapes + 1; r.shapes[it.shape] = 0 end
        r.shapes[it.shape] = r.shapes[it.shape] + 1
      end
    end
    local grass = 0
    for _, g in ipairs(m and m.grass or {}) do grass = grass + (g.n or (g.x and #g.x) or 0) end
    r.grass = grass
    r.shapes = nil
    local ok, s = pcall(codec.encode, m)
    r.emcBytes = ok and #s or tostring(s)
    row[name] = r
  end
  out[#out + 1] = row
end end
return out
'''

import gc; gc.disable()
def main():
    pack, lat, lon, radius = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
    lua, mods, _ = bench_native.runtime(pack, game_structs=True)
    load = lua.eval('function(source, name) return assert(load(source, "@" .. name))() end')
    src = (ROOT / 'mod/lua/ge/extensions/e2r/bridge_codec.lua').read_text(encoding='utf8')
    lua.execute("mods.ffi = package.loaded.ffi or (function() local r = _G.require; return nil end)()")
    lua.execute("local ok, f = pcall(function() return package.loaded['ffi'] end); mods.ffi = f")
    lua.globals().mods['bridge_codec'] = load(src, 'bridge_codec.lua')
    native = mods['native']; native.refresh()
    job = native.land(lua.table_from({'lat': lat, 'lon': lon, 'seq': 1}))
    x, y = native.localPoint(lat, lon)
    res = lua.execute(COUNT, native, mods['generator'], int(x // 500), int(y // 500), radius, False)
    def conv(v):
        if hasattr(v, 'keys'):
            return {str(k): conv(v[k]) for k in v.keys()}
        return v
    rows = [conv(r) for r in res.values()]
    print(json.dumps(rows, indent=1), flush=True)
    import os; os._exit(0)

main()
