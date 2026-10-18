"""Where generator.build spends its time: LuaJIT's sampling profiler over real tiles.

    python earthng/profile_generator.py --pack <earthng_ukraine.zip> --lat 48.45306 --lon 24.55611 [--radius 1]

Builds the (2r+1)^2 tiles round the point near and far (no pauses) under jit.profile and
prints the hottest functions and lines with their share of samples, plus ms per tile.
"""
import argparse
import json
import sys

import bench_native

PROFILE = '''
local native, generator, i0, j0, radius, far = ...
local profile = package.loaded['jit.profile']
if not profile then  -- bench_native replaces require() with the module table lookup
  for _, loader in ipairs(package.loaders) do
    local f = loader('jit.profile')
    if type(f) == 'function' then profile = f('jit.profile'); break end
  end
end
local function upvalue(f, name)
  for k = 1, 200 do local n, v = debug.getupvalue(f, k); if not n then return end; if n == name then return v end end
end
local active = upvalue(native.update, 'active')
local d = active.region.data
local loadCell = upvalue(upvalue(native.update, 'buildTile'), 'loadCell')
local function cellOf(i, j, keep)
  local co = coroutine.create(function() return loadCell(string.format('%d_%d', i, j), i, j, keep) end)
  while true do
    local ok, cell = coroutine.resume(co)
    if not ok then error(cell) end
    if coroutine.status(co) == 'dead' then return cell end
  end
end
local inputs = {}
for di = -radius, radius do for dj = -radius, radius do
  local i, j = i0 + di, j0 + dj
  local list = {}
  for ci = math.floor((i * 500 - 40) / d.cellSize), math.floor((i * 500 + 540) / d.cellSize) do
    for cj = math.floor((j * 500 - 40) / d.cellSize), math.floor((j * 500 + 540) / d.cellSize) do
      local c = cellOf(ci, cj, {i * 500, j * 500, (i + 1) * 500, (j + 1) * 500})
      if c then list[#list + 1] = c end
    end
  end
  inputs[#inputs + 1] = {i = i, j = j, cells = list}
end end
local fns, lines, total = {}, {}, 0
profile.start('li1', function(thread, samples)
  total = total + samples
  local f = profile.dumpstack(thread, 'f;', 3)
  local l = profile.dumpstack(thread, 'l', 1)
  fns[f] = (fns[f] or 0) + samples
  lines[l] = (lines[l] or 0) + samples
end)
local times = {}
local t0 = clock()
for _, inp in ipairs(inputs) do
  local t = clock()
  generator.build(inp.cells, inp.i, inp.j, {tileSize = 500, far = far, pause = function() end, seaLevel = d.seaLevel,
    latitude = d.geo and d.geo[4], nature = d.nature, look = d.look})
  times[#times + 1] = (clock() - t) * 1000
end
local wall = (clock() - t0) * 1000
profile.stop()
local function top(map, n)
  local list = {}
  for k, v in pairs(map) do list[#list + 1] = {k, v} end
  table.sort(list, function(a, b) return a[2] > b[2] end)
  local out = {}
  for k = 1, math.min(n, #list) do out[k] = {list[k][1], list[k][2], math.floor(list[k][2] / total * 1000) / 10} end
  return out
end
return {total = total, wallMs = wall, tileMs = times, fns = top(fns, 30), lines = top(lines, 40)}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', required=True)
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--radius', type=int, default=1)
    p.add_argument('--far', action='store_true')
    a = p.parse_args()
    lua, mods, _ = bench_native.runtime(a.pack)
    native = mods['native']
    native.refresh()
    job = native.land(lua.table_from({'lat': a.lat, 'lon': a.lon, 'seq': 1}))
    if job['state'] == 'error':
        sys.exit(job['message'])
    x, y = native.localPoint(a.lat, a.lon)
    i0, j0 = int(x // 500), int(y // 500)
    res = lua.execute(PROFILE, native, mods['generator'], i0, j0, a.radius, a.far)

    def plain(v):
        if hasattr(v, 'items'):
            keys = list(v.keys())
            if keys and all(isinstance(k, int) for k in keys):
                return [plain(v[k]) for k in sorted(keys)]
            return {k: plain(x) for k, x in v.items()}
        return v
    out = plain(res)
    print(json.dumps({'wallMs': round(out['wallMs']), 'tileMs': [round(t) for t in out['tileMs']]}))
    print('-- functions')
    for name, n, pct in out['fns']:
        print(f'{pct:5.1f}%  {name}')
    print('-- lines')
    for name, n, pct in out['lines']:
        print(f'{pct:5.1f}%  {name}')


if __name__ == '__main__':
    main()
