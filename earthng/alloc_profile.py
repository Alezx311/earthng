"""Where the native generator allocates: Lua garbage by function or line, outside the game.

  python earthng/alloc_profile.py --pack <country.zip> --lat 50.4475 --lon 30.5225 [--layer near] [--lines --count 3]

Lands like bench_native.py, then builds the tiles round the landing one by one with no time
budget (the same work every run) under a count hook: the heap growth between two hook calls
(GC stopped) goes to the function or line running at the second call. The JIT is off while
sampling (hooks do not fire in compiled code), so values a trace would sink count here too.
Every KB here is collector work in the game (world/gc.lua): read the ranking and the per-tile
total before and after a change.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_native import runtime  # noqa: E402

PROFILE = '''
local native, generator, radius, perLine, layer = ...
local function upvalue(f, name)
  for k = 1, 200 do local n, v = debug.getupvalue(f, k); if not n then return end; if n == name then return v end end
end
local active = upvalue(native.update, 'active')
local r, d = active.region, active.region.data
local loadCell = upvalue(upvalue(native.update, 'buildTile'), 'loadCell')
local function cellOf(i, j, keep)
  local co = coroutine.create(function() return loadCell(string.format('%d_%d', i, j), i, j, keep, {}) end)
  while true do
    local ok, cell = coroutine.resume(co)
    if not ok then error(cell) end
    if coroutine.status(co) == 'dead' then return cell end
  end
end
local by, total, last = {}, 0, 0
local getinfo = debug.getinfo
-- the hook's own tables and strings are left out: the count restarts after it
local function hook()
  local d = collectgarbage('count') - last
  if d > 0 then
    local info = getinfo(2, 'Sl')
    if info then
      local key = info.short_src .. ':' .. (perLine and info.currentline or info.linedefined)
      by[key] = (by[key] or 0) + d
      total = total + d
    end
  end
  last = collectgarbage('count')
end
local i0, j0 = math.floor(active.landing.x / 500), math.floor(active.landing.y / 500)
local s = d.cellSize
local tiles = 0
jit.off()
for di = -radius, radius do
  for dj = -radius, radius do
    local i, j = i0 + di, j0 + dj
    local rect = {i * 500, j * 500, (i + 1) * 500, (j + 1) * 500}
    local cells = {}
    for ci = math.floor(rect[1] / s), math.ceil(rect[3] / s) - 1 do
      for cj = math.floor(rect[2] / s), math.ceil(rect[4] / s) - 1 do
        cellOf(ci, cj, {0, 0, 1, 1})   -- the block into the cache: the decode below is the tile's own
        collectgarbage('collect'); collectgarbage('stop')
        last = collectgarbage('count')
        if layer == 'all' or layer == 'decode' then debug.sethook(hook, '', HOOK_COUNT or 200) end
        cells[#cells + 1] = cellOf(ci, cj, rect)
        debug.sethook(); hook(); collectgarbage('restart')
      end
    end
    if layer ~= 'decode' then
      collectgarbage('collect'); collectgarbage('stop')
      last = collectgarbage('count')
      debug.sethook(hook, '', HOOK_COUNT or 200)
      generator.build(cells, i, j, {tileSize = 500, far = layer == 'far', horizon = layer == 'horizon',
        pause = function() end, seaLevel = d.seaLevel, geo = d.geo, nature = d.nature, look = d.look,
        latitude = d.geo and d.geo[4], farStep = 100, horizonStep = 100,
        materials = '/earthng/planet/materials.json', packs = '/e2r_stream/fast-art/v10/packs.json'})
      debug.sethook(); hook(); collectgarbage('restart')
    end
    tiles = tiles + 1
  end
end
jit.on()
local list = {}
for k, v in pairs(by) do list[#list + 1] = {k, v} end
table.sort(list, function(a, b) return a[2] > b[2] end)
local out = {}
for i = 1, math.min(TOP or 60, #list) do out[i] = list[i] end
return out, total, tiles
'''


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--radius', type=int, default=1, help='tiles round the landing tile')
    p.add_argument('--layer', default='near', choices=('near', 'far', 'horizon', 'decode', 'all'),
                   help='what is profiled: a layer of generator.build, the cell decode, or decode and near')
    p.add_argument('--top', type=int, default=60)
    p.add_argument('--lines', action='store_true', help='by line instead of by function')
    p.add_argument('--count', type=int, default=200, help='VM instructions between hook calls (smaller: sharper, slower)')
    a = p.parse_args()
    lua, mods, _ = runtime(a.pack)
    # readPaused reads 256 KB at a time until a short read: the bench stub hands the whole file
    # to every read(), so give it once
    lua.execute('''io.open = function(p) local data = py_bytes(p); if not data then return nil end
      return {read = function() local d = data; data = nil; return d end, close = function() end} end''')
    native = mods['native']
    native.refresh()
    job = native.land(lua.table_from({'seq': 1, 'lat': a.lat, 'lon': a.lon}))
    if job.state == 'error':
        sys.exit(job.message)
    lua.globals().HOOK_COUNT, lua.globals().TOP = a.count, a.top
    rows, total, tiles = lua.execute(PROFILE, native, mods['generator'], a.radius, a.lines, a.layer)
    print(f'{int(tiles)} tiles, layer {a.layer}: {total / 1024:.0f} MB allocated ({total / 1024 / tiles:.0f} MB a tile, JIT off)')
    for r in rows.values():
        print(f'{r[2] / 1024:9.1f} MB {100 * r[2] / total:5.1f} %  {r[1]}')


if __name__ == '__main__':
    main()
