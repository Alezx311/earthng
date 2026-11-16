"""Capture the actual first native.buildTile generator input, offline.

The LuaJIT test harness runs the real cell loading and scheduling code. This is
not an in-game capture: callbacks, engine state, and later generator output are
not serialized, and no claim of replay or parity is made.
"""
import argparse
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'earthng'))
from bench_native import runtime  # noqa: E402
from capture_road_fixture import plain  # noqa: E402


HOOK = r'''
local native, generator, target, maxFrames = ...
local original = generator.build
generator.build = function(cells, i, j, options)
  local lod = options.horizon and 'horizon' or (options.far and 'far' or 'near')
  if lod ~= target then return original(cells, i, j, options) end
  local values, omitted = {}, {}
  for k, v in pairs(options) do
    if type(v) == 'function' or k == 'farMap' then omitted[#omitted + 1] = k
    else values[k] = v end
  end
  table.sort(omitted)
  py_capture(cells, i, j, values, omitted)
  error('EARTHNG_CAPTURE_COMPLETE')
end
local ready = false
local released = {}
for frame=1,maxFrames do
  native.update(1/60, 50)
  if captured then return frame end
  local state = native.status()
  local job = state.job
  if job and job.state == 'error' then error(job.message) end
  if job and job.state == 'ready' and not ready then
    local p = job.manifest.spawn.pos
    native.pose({x=p[1],y=p[2],vx=0,vy=0,state='driving'})
    ready = true
  end
  if ready then
    for _, layer in ipairs({{'road',state.stream.ready}, {'scene',state.stream.scenes},
      {'grass',state.stream.grass or {}}, {'far',state.stream.far}, {'horizon',state.stream.horizon}}) do
      local name, seen = layer[1], released[layer[1]] or {}
      released[name] = seen
      for key, token in pairs(layer[2]) do
        token = type(token) == 'table' and token.serial or token
        if seen[key] ~= token then seen[key] = token; native.manifest(key, name); native.release(key, name) end
      end
      for key in pairs(seen) do if not layer[2][key] then seen[key] = nil end end
    end
  end
end
error('capture did not reach generator.build')
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--lat', type=float, default=50.447734)
    p.add_argument('--lon', type=float, default=30.52218)
    p.add_argument('--quality', type=int, default=50, choices=range(101))
    p.add_argument('--lod', choices=('near', 'far', 'horizon'), default='near')
    p.add_argument('--max-frames', type=int, default=5000,
                   help='maximum offline updates before giving up')
    a = p.parse_args()
    if a.max_frames < 1:
        p.error('--max-frames must be positive')
    if a.out.exists():
        raise SystemExit('Refusing to overwrite output')
    lua, mods, _ = runtime(a.pack)
    native = mods['native']
    native.refresh()
    # setTune() applies the same quality policy used by the native runtime.
    native.setTune(mods['quality'].preset(a.quality))
    job = native.land(lua.table_from({'seq': 1, 'lat': a.lat, 'lon': a.lon}))
    if job.state == 'error':
        raise SystemExit(job.message)
    result = {}

    def capture(cells, i, j, options, omitted):
        result.update(schema=1, note='offline LuaJIT capture; function callbacks omitted',
                      lat=a.lat, lon=a.lon, quality=a.quality, lod=a.lod,
                      tile={'i': i, 'j': j}, cells=plain(cells),
                      options=plain(options), omitted_callbacks=plain(omitted))
        lua.globals().captured = True

    lua.globals().py_capture = capture
    frame = lua.execute(HOOK, native, mods['generator'], a.lod, a.max_frames)
    result['capture_frame'] = frame
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.out, 'xt', encoding='utf8', compresslevel=3) as f:
        json.dump(result, f, ensure_ascii=False, allow_nan=False, sort_keys=True,
                  separators=(',', ':'))
    print(json.dumps({'tile': result['tile'], 'cells': len(result['cells']),
                      'options': sorted(result['options']), 'callbacks_omitted': result['omitted_callbacks'],
                      'frame': frame, 'path': str(a.out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
