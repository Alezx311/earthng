"""What a tile of a pack is built of under its universe, outside the game: the materials of its
road and scene, and what the car would stand on.

    python earthng/universe_census.py --pack out/polygon/earthng_polygon.zip MT-A1 DS-A5 SN-D12 MD-A12 D7
    python earthng/universe_census.py --pack out/polygon/earthng_polygon.zip --universe snow D7
    python earthng/universe_census.py --set climate=desert --set look.block=nordic A6
    python earthng/universe_census.py --flora data/flora/all --plants A3 A6 C4 JG-B5
    python earthng/universe_census.py --flora data/flora/all --plants --set floraZone=polissia A3

--flora: the flora pack's folder (earthng/build_flora.py), read as the game reads the mounted
pack; --plants: what stands in the tile, by species, and how much of it waits for a slow car.

The same chain as in the game: the pack's manifest names a tile's universe, lab.lua hands it to
native.lua, native.lua merges universe.lua's rules into generator.build's options. The planet's
climate grid is not mounted here, so the place's own climate is the temperate default; a
universe's given climate works as in the game. Needs lupa.luajit21.
"""
import argparse
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / 'mod/lua/ge/extensions/e2r'
# A runtime that has built tiles in coroutines crashes the interpreter when it is freed (lupa):
# every runtime is kept to the end, and main() leaves without the teardown.
_KEEP = []


FLORA_MANIFEST = '/art/shapes/earthng/flora/flora.json'


def runtime(pack, flora=None):
    """A LuaJIT with the mod's modules over one pack. The pack's files are Lua strings and its
    JSON Lua tables before anything is built: a landing runs in coroutines, and a coroutine that
    called back into Python (a timer, a file check) crashed the interpreter about every other
    run on a tile with many trees (21.11)."""
    from lupa.luajit21 import LuaRuntime
    archive = zipfile.ZipFile(pack)
    lua = LuaRuntime(unpack_returned_tuples=True)

    def convert(value):
        if isinstance(value, dict):
            return lua.table_from({k: convert(v) for k, v in value.items()})
        if isinstance(value, list):
            return lua.table_from([convert(v) for v in value])
        return value

    names = archive.namelist()
    g = lua.globals()
    g.files = lua.table_from({'/' + n: archive.read(n) for n in names if not n.endswith('/')})
    jsons = {'/' + n: convert(json.loads(archive.read(n))) for n in names if n.endswith('.json')}
    if flora:
        # the flora pack as the game mounts it: its manifest at its own path (its shapes count
        # as present, like the game's)
        jsons[FLORA_MANIFEST] = convert(json.loads((Path(flora) / FLORA_MANIFEST.lstrip('/')).read_text(encoding='utf8')))
    g.jsons = lua.table_from(jsons)
    g.manifests = convert(sorted('/' + n for n in names if n.count('/') == 3 and n.endswith('/manifest.json')))
    lua.execute('''
      local function copy(v)
        if type(v) ~= 'table' then return v end
        local out = {}
        for k, x in pairs(v) do out[k] = copy(x) end
        return out
      end
      -- the game's own content (stock trees, props) counts as present, as in the game
      FS = {fileExists = function(_, p)
          return files[p] ~= nil or p:sub(1, 8) == '/levels/' or p:sub(1, 5) == '/art/' or p:sub(1, 8) == '/assets/'
        end,
        findFiles = function() return copy(manifests) end}
      jsonReadFile = function(p) return copy(jsons[p]) end
      io.open = function(p)
        local data = files[p]
        if not data then return nil end
        local pos = 1
        return {read = function(_, n)
          if n == '*a' or n == nil then local chunk = data:sub(pos); pos = #data + 1; return chunk end
          if pos > #data then return nil end
          local last = math.min(#data, pos + n - 1)
          local chunk = data:sub(pos, last); pos = last + 1; return chunk
        end, close = function() end}
      end
      hptimer = function()
        local t0 = os.clock()
        return {stop = function() return (os.clock() - t0) * 1000 end,
                stopAndReset = function() local n = os.clock(); local d = (n - t0) * 1000; t0 = n; return d end}
      end
      mods = {}
      require = function(name) return mods[name:match('[^/]+$')] end
    ''')
    load = lua.eval('function(source, name) return assert(load(source, "@" .. name))() end')
    for name in ('biome', 'universe', 'flora', 'lab', 'countries', 'coordinates', 'cellformat', 'kit_cells', 'kit', 'generator',
                 'quality', 'manual', 'manual_editor', 'native'):
        g.mods[name] = load((LUA / f'{name}.lua').read_text(encoding='utf8'), f'{name}.lua')
        if name == 'biome':
            lua.execute('mods.biome.present = true')      # a given climate is taken; the grid itself is not here
    manifest = json.loads(archive.read(next(n for n in names if n.count('/') == 3 and n.endswith('/manifest.json'))))
    return lua, manifest


CENSUS = '''
local native, generator, lab, U, given, forced = ...
lab.bind{tune = generator.TUNE, universes = U.choices(), climates = U.climates, rules = U.get,
  floraZones = mods.flora and mods.flora.zoneChoices() or nil,
  universeOf = function(scope) return forced or given[scope] end}
seen = {}
local build = generator.build
generator.build = function(cells, i, j, options)
  local road, scene, far, nav, grass = build(cells, i, j, options)
  if not options.far and not options.horizon and not options.vista then
    local mats = {}
    for _, manifest in ipairs({road, scene}) do
      for _, item in ipairs(manifest and manifest.items or {}) do
        for _, mesh in ipairs(item.meshes or {}) do
          mats[mesh.material] = (mats[mesh.material] or 0) + #mesh.faces / 3
        end
      end
    end
    -- what stands: every placed shape, and how many of each wait for a slow car (the fill)
    local plants = {}
    for _, item in ipairs(scene and scene.items or {}) do
      if item.kind == 'static' and type(item.shape) == 'string' then
        local p = plants[item.shape]
        if not p then p = {n = 0, fill = 0}; plants[item.shape] = p end
        p.n = p.n + 1
        if item.fill then p.fill = p.fill + 1 end
      end
    end
    seen[i .. '_' .. j] = {mats = mats, plants = plants, climate = options.climate and (options.climate.class or 'lines') or 'place',
      block = options.look and options.look.block, feel = options.feel and true or false, swap = options.swap ~= nil,
      zone = options.floraZone}
  end
  return road, scene, far, nav, grass
end
'''


def plant_name(shape):
    """A shape as the census names it: a flora species (its folder), or a stock model's file."""
    parts = shape.split('/')
    if '/earthng/flora/' in shape:
        return parts[-2]
    return 'stock:' + parts[-1].rsplit('.', 1)[0]


def census(pack, codes, universe=None, emit=print, knobs=(), flora=None, plants=False):
    lua, manifest = runtime(pack, flora)
    _KEEP.append(lua)
    plan = manifest.get('polygon') or {}
    tiles = {t['code']: t for t in plan.get('tiles', [])}
    region = manifest['regions'][0]['id']
    given = lua.table_from({f"{region}:{t['i']}_{t['j']}": t['universe'] for t in tiles.values() if t.get('universe')})
    g = lua.globals()
    native = g.mods.native
    lua.execute('function census(...) ' + CENSUS + ' end')
    g.census(native, g.mods.generator, g.mods.lab, g.mods.universe, given, universe)
    for knob in knobs:                     # the lab's knobs for the whole world: 'look.block=nordic'
        key, value = knob.split('=', 1)
        if g.mods.lab.set(key, value)[0] is None:
            raise SystemExit(f'the lab refuses {knob}')
    out = {}
    for name in codes:
        tile = tiles[name]
        native.land(lua.table_from({'seq': 1, 'lat': tile['at'][0], 'lon': tile['at'][1]}))
        key = f"{tile['i']}_{tile['j']}"
        for _ in range(4000):
            native.update(1 / 60, 50)
            job = native.status().job
            if job.state == 'error':
                raise RuntimeError(f'{name}: {job.message}')
            if g.seen[key] is not None and job.state != 'working':
                break
        got = g.seen[key]
        if got is None:
            raise RuntimeError(f'{name}: tile {key} was not built')
        mats = {k: int(v) for k, v in got.mats.items()}
        out[name] = {'title': tile['titleEn'], 'universe': universe or tile.get('universe'), 'climate': got.climate,
                     'block': got.block, 'feel': got.feel, 'swap': got.swap, 'mats': mats}
        total = sum(mats.values())
        ground = {k: v for k, v in mats.items() if k.startswith('e2rf_col_')}
        top = sorted((k for k in mats if not k.startswith('e2rf_col_')), key=lambda k: -mats[k])[:9]
        emit(f"{name:8s} {tile['titleEn'][:26]:26s} universe {str(out[name]['universe']):9s} climate {str(got.climate):6s} "
             f"block {str(got.block):12s} {total:7d} tris")
        emit('           stands on: ' + ', '.join(f"{k[9:]} {v}" for k, v in sorted(ground.items(), key=lambda kv: -kv[1])))
        emit('           drawn with: ' + ', '.join(f"{k[5:]} {mats[k]}" for k in top))
        if plants:
            by, shapes, own, waiting = {}, 0, 0, 0
            for shape, count in got.plants.items():
                key = plant_name(shape)
                by[key] = by.get(key, 0) + count.n
                shapes += 1
                waiting += count.fill
                if not key.startswith('stock:'):
                    own += count.n
            total_plants = sum(by.values())
            out[name]['plants'] = dict(sorted(by.items(), key=lambda kv: -kv[1]))
            out[name].update(shapes=shapes, zone=got.zone, waiting=waiting, own=own)
            emit(f'           plants: {total_plants} of {len(by)} kinds ({shapes} shapes), {own} the pack\'s own, '
                 f'{waiting} wait for a slow car; zone {got.zone or "by the place"}')
            emit('           ' + ', '.join(f'{k} {v}' for k, v in list(out[name]['plants'].items())[:22]))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', type=Path, default=ROOT / 'out/polygon/earthng_polygon.zip')
    p.add_argument('--universe', help='build the tiles as this universe whatever the pack names for them')
    p.add_argument('--set', action='append', default=[], metavar='KNOB=VALUE', help="a knob of the lab for the whole world, e.g. climate=desert")
    p.add_argument('--json', type=Path)
    p.add_argument('--flora', type=Path, help="the flora pack's folder (data/flora/all): its plants grow")
    p.add_argument('--plants', action='store_true', help='count what stands in each tile, by species')
    p.add_argument('codes', nargs='+', help="tile codes of the pack's plan (D7, MT-A1, ...)")
    a = p.parse_args()
    result = census(a.pack, a.codes, a.universe, knobs=a.set, flora=a.flora, plants=a.plants)
    if a.json:
        a.json.write_text(json.dumps(result, indent=1), encoding='utf8')
    sys.stdout.flush()
    import os
    os._exit(0)


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
