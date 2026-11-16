"""Compare roof mesh triangles with real Rust results injected offline.

This is a correctness harness, not a live bridge or a speed measurement.
"""
import argparse
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'earthng'))
from bench_native import runtime  # noqa: E402
from bench_roofs import pack, unpack  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture', type=Path, required=True)
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--cli', type=Path, required=True)
    p.add_argument('--lod', choices=('near', 'far'), default='near')
    a = p.parse_args()
    with gzip.open(a.fixture, 'rt', encoding='utf8') as f:
        fixture = json.load(f)
    buildings, seen = [], set()
    for cell in fixture['cells']:
        for i, b in enumerate(cell.get('buildings', []), 1):
            key = str(b.get('id', i))
            if key not in seen:
                seen.add(key)
                buildings.append(b)
    buildings.sort(key=lambda b: str(b.get('id', '')))
    i, j = fixture['tile']['i'], fixture['tile']['j']
    size = fixture['options']['tileSize']
    rect = [i*size, j*size, (i+1)*size, (j+1)*size]
    with tempfile.TemporaryDirectory() as td:
        request, response = Path(td)/'request', Path(td)/'response'
        request.write_bytes(pack(buildings, rect, 4, far=a.lod == 'far'))
        subprocess.run([str(a.cli.resolve()), str(request), str(response)], check=True)
        triangles, _ = unpack(response.read_bytes(), len(buildings))
    lua, mods, _ = runtime(a.pack)

    def table(v):
        if isinstance(v, dict):
            return lua.table_from({k: table(x) for k, x in v.items()})
        if isinstance(v, (list, tuple)):
            return lua.table_from([table(x) for x in v])
        return v

    result = lua.execute(r'''
      local generator, cellsA, cellsB, optionsA, optionsB, ids, tris, i, j, far = ...
      local cache, byId, hits = {}, {}, 0
      for n, id in ipairs(ids) do byId[id] = tris[n] end
      for _, cell in ipairs(cellsB) do
        for n, b in ipairs(cell.buildings or {}) do
          local id = tostring(b.id or n)
          if byId[id] then cache[b] = byId[id] end
        end
      end
      local provider = setmetatable({}, {__index = function(_, building)
        if cache[building] then hits = hits + 1 end
        return cache[building]
      end})
      optionsA.far, optionsB.far = far, far
      if far then optionsA.farDecor, optionsB.farDecor = true, true end
      if far then optionsB.farRoofTriangles = provider else optionsB.roofTriangles = provider end
      local _, sceneA, farA = generator.build(cellsA, i, j, optionsA)
      local _, sceneB, farB = generator.build(cellsB, i, j, optionsB)
      local a, b = far and farA or sceneA, far and farB or sceneB
      local function roof(scene)
        local out = {}
        for _, item in ipairs(scene.items) do
          for _, mesh in ipairs(item.meshes or {}) do
            if mesh.material == 'e2rf_roof' then
              for n = 1, #mesh.faces, 3 do
                local p = {}
                for k = n, n + 2 do
                  local v = mesh.verts[mesh.faces[k].v + 1]
                  p[#p+1] = string.format('%.7f,%.7f,%.7f',
                    v.x + item.pos[1], v.y + item.pos[2], v.z + item.pos[3])
                end
                out[#out+1] = table.concat(p, ';')
              end
            end
          end
        end
        table.sort(out)
        return out
      end
      local x, y = roof(a), roof(b)
      assert(hits > 0, 'no Rust roof results were consumed')
      assert(#x > 0 and #x == #y, 'roof triangle count mismatch')
      for n = 1, #x do assert(x[n] == y[n], 'roof triangle mismatch ' .. n) end
      return #x, hits
    ''', mods['generator'], table(fixture['cells']), table(fixture['cells']),
         table(fixture['options']), table(fixture['options']),
         table([str(b.get('id', '')) for b in buildings]), table(triangles), i, j, a.lod == 'far')
    count, hits = result
    print(json.dumps({'tile': [i, j], 'lod': a.lod, 'buildings': len(buildings),
                      'compared_roof_triangles': count, 'rust_results_used': hits, 'result': 'equal'}))


if __name__ == '__main__':
    main()
