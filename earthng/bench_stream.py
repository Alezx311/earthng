"""Streaming along a route outside the game: which tiles are in memory and whether the tile the
car drives onto is ready (LuaJIT under lupa, over a real country ZIP).

  python earthng/bench_stream.py --pack <earthng_kyiv-oblast.zip> --route out/routes/kyiv-center.json
      [--speed 16] [--seconds 120] [--renderer new|old] [--lua-dir <copy of mod/lua/ge/extensions/e2r>]

The car moves along the route at a steady speed; native.update runs every frame with the game's
budget (world.lua: 4 ms, 8 ms from 15 m/s, 12 ms parked) times --lua-factor, because LuaJIT under
lupa runs the generator ~2-3 times slower than the game (docs/PERFORMANCE.md). The renderer is a
model of world.lua updateTiles: one near road started a frame, scenes and grass as they come, the
far ring and the horizon taken at once. `old` unloads a near tile 350 m past the load radius or
behind the car at speed (world.lua before exp/predict-tiles); `new` unloads what native no longer
wants near.

Reported: tiles in memory (near, far, horizon: mean and max while driving), every tile entered
(its road, scene and grass in or not at the moment the car entered it) and the generator's time.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import bench_native  # noqa: E402

DRIVE = '''
local native, route, speed, seconds, frame, factor, renderer, hold, predictMode, predict, navigation = ...
-- the generator's time from here on (the landing's is not the drive's)
local spent0, built0, rebuilds0 = {}, native.status().stream.built, native.status().stream.rebuilds
for k, v in pairs(native.status().stream.spentMs) do spent0[k] = v end
local lost0 = {scene = native.status().stream.lost.scene, grass = native.status().stream.lost.grass}
local function upvalue(f, name)
  for k = 1, 200 do local n, v = debug.getupvalue(f, k); if not n then return end; if n == name then return v end end
end
-- the route in world metres, cumulative length
local pts, cum = {}, {0}
for k = 1, #route do
  local x, y = native.localPoint(route[k][1], route[k][2])
  if x then
    if #pts > 0 then
      local q = pts[#pts]
      local d = math.sqrt((x - q[1]) ^ 2 + (y - q[2]) ^ 2)
      if d > .5 then pts[#pts + 1] = {x, y}; cum[#cum + 1] = cum[#cum] + d end
    else pts[1] = {x, y} end
  end
end
local total = cum[#cum]
local seg = 1
local function at(s, k)
  s = math.min(s, total)
  local seg = k or seg
  while seg < #pts - 1 and cum[seg + 1] < s do seg = seg + 1 end
  local a, b = pts[seg], pts[seg + 1]
  local l = cum[seg + 1] - cum[seg]
  local f = l > 0 and (s - cum[seg]) / l or 0
  return a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, (b[1] - a[1]) / math.max(l, 1e-6), (b[2] - a[2]) / math.max(l, 1e-6)
end
-- the route ahead as a predicted path {x, y, d, ...} (the autopilot or the navigator has it)
local function routeAhead(s, length)
  local out, k = {}, seg
  local x, y = at(s)
  out[1], out[2], out[3] = x, y, 0
  local d = 0
  local px, py = x, y
  while k < #pts and d < length do
    k = k + 1
    local q = pts[k]
    d = d + math.sqrt((q[1] - px) ^ 2 + (q[2] - py) ^ 2)
    px, py = q[1], q[2]
    out[#out + 1], out[#out + 2], out[#out + 3] = px, py, d
  end
  return out
end

local routeFlat = {}
for k = 1, #pts do routeFlat[#routeFlat + 1], routeFlat[#routeFlat + 2] = pts[k][1], pts[k][2] end
-- the renderer's navgraph segments (world.lua navRead): from every road layer taken
local segments, navRev, navIndex, navIndexRev = {}, 0, nil, -1
local function addNav(key, road)
  for _, s in ipairs(road and road.navSegments or {}) do
    local seg = segments[s[1]]
    if not seg then
      local n = (#s - 7) / 3
      local mid = 8 + 3 * math.floor((n - 1) / 2)
      seg = {s = navigation.simplify(s), tiles = {}, x = s[mid], y = s[mid + 1]}
      local box = {math.huge, math.huge, -math.huge, -math.huge}
      for k = 8, #seg.s - 2, 3 do
        local px, py = seg.s[k], seg.s[k + 1]
        box[1], box[2], box[3], box[4] = math.min(box[1], px), math.min(box[2], py), math.max(box[3], px), math.max(box[4], py)
      end
      seg.box = box
      segments[s[1]] = seg
      navRev = navRev + 1
    end
    seg.tiles[key] = true
  end
end
local function dropNav(key)
  for id, seg in pairs(segments) do
    if seg.tiles[key] then
      seg.tiles[key] = nil
      if next(seg.tiles) == nil then segments[id] = nil; navRev = navRev + 1 end
    end
  end
end
local tileSize = native.status().stream.tile
local function keyAt(x, y) return math.floor(x / tileSize) .. '_' .. math.floor(y / tileSize) end
local R = {near = {}, far = {}, horizon = {}}   -- the renderer's tiles
-- The landing builds its tiles whole: their grass is inside the scene (generator.lua, no
-- sceneReady), and no grass layer ever comes. They count as whole once the scene is in.
local whole, landing = {}, {}
local gone, backAs = {}, {}   -- tile key -> why the renderer dropped it; far layers taken again by that
for key in pairs(native.status().stream.scenes or {}) do whole[key], landing[key] = true, true end
local now, s = 0, 0
local samples = {near = {}, far = {}, horizon = {}, nearArea = {}}
local arrivals, lastKey = {}, nil
local viewMiss, aheadMiss, frames = 0, 0, 0
-- the same past the landing's tiles: those were built before the drive, so they say nothing
-- about the prediction
local viewMissOut, aheadMissOut, framesOut, aheadOut = 0, 0, 0, 0
local x, y, ux, uy = at(0)
native.pose({x = x, y = y, vx = 0, vy = 0, state = 'driving'})
local poseAt = -1
local function count(t) local n = 0; for _ in pairs(t) do n = n + 1 end; return n end
local nextSample = 0
local function wantedNear(st, key)
  local due = st.wanted and st.wanted[key]
  return due and due < 1e6
end
while now < seconds do
  frames = frames + 1
  s = s + speed * frame
  if s >= total then break end
  while seg < #pts - 1 and cum[seg + 1] < s do seg = seg + 1 end
  x, y, ux, uy = at(s)
  local vx, vy = ux * speed, uy * speed
  now = now + frame
  if now - poseAt >= .5 then
    poseAt = now
    local pose = {x = x, y = y, vx = vx, vy = vy, state = 'driving'}
    -- the path world.lua would send: the route (navigator, autopilot) or the renderer's roads
    if predictMode == 'route' then
      pose.path = predict.along(routeFlat, x, y, 3000)
    elseif predictMode == 'nav' then
      if navRev ~= navIndexRev then navIndex, navIndexRev = predict.index(segments), navRev end
      pose.path = predict.ahead(navIndex, x, y, ux, uy, 3000, math.max(400, speed * 12))
    end
    native.pose(pose)
  end
  local budget = speed >= 15 and 8 or (speed < 2 and 12 or 4)
  native.update(frame, budget * factor, nil, now)
  if frames % 8 == 0 then collectgarbage('collect') end
  local st = native.status().stream
  if native.status().job.state == 'error' then error(native.status().job.message) end
  -- renderer: unload
  local underKey = keyAt(x, y)
  for key, t in pairs(R.near) do
    local i, j = key:match('^(-?%d+)_(-?%d+)$')
    local cx, cy = (tonumber(i) + .5) * tileSize, (tonumber(j) + .5) * tileSize
    local d = math.sqrt((cx - x) ^ 2 + (cy - y) ^ 2)
    local drop
    if renderer == 'old' then
      local loadR = st.loadRadius or 1000
      local keepBack = math.max(200, speed * 3.5) + tileSize * .5
      local behind = speed >= 15 and key ~= underKey and d > tileSize * .71
        and ((cx - x) * vx + (cy - y) * vy) < 0 and d > keepBack
      local held = key == underKey or (wantedNear(st, key) and not behind)
      drop = not held and (d > loadR + 350 or behind)
    else
      if wantedNear(st, key) or key == underKey then t.unwanted = nil
      else t.unwanted = t.unwanted or now end
      drop = t.unwanted and now - t.unwanted >= hold
    end
    if drop then R.near[key] = nil; whole[key] = nil; native.unload(key); dropNav(key); gone[key] = 'near' end
  end
  for key, t in pairs(R.far) do
    local i, j = key:match('^(-?%d+)_(-?%d+)$')
    local cx, cy = (tonumber(i) + .5) * tileSize, (tonumber(j) + .5) * tileSize
    local d = math.sqrt((cx - x) ^ 2 + (cy - y) ^ 2)
    local near = R.near[key]
    -- world.lua's rule for both: past the far ring by 500 m, or behind the car at speed
    local keepBack = math.max(200, speed * 3.5) + tileSize * .5
    local behind = speed >= 15 and key ~= underKey and d > tileSize * .71
      and ((cx - x) * vx + (cy - y) * vy) < 0 and d > keepBack
    local drop = (near and near.road) or d > (st.farRadius or 3000) + 500 or behind
    if drop then
      gone[key] = (near and near.road) and 'farUnderNear' or (behind and 'farBehind' or 'farOutside')
    end
    if drop or (st.far[key] and st.far[key] ~= t.serial) then R.far[key] = nil; if drop then native.unload(key, 'far') end end
  end
  for key in pairs(R.horizon) do
    if not (st.horizon and st.horizon[key]) then R.horizon[key] = nil end
  end
  -- renderer: start the nearest due road (one a frame), every scene and grass that is out
  local best, bestRank
  for key in pairs(st.ready or {}) do
    if not R.near[key] then
      local due = st.wanted and st.wanted[key]
      local i, j = key:match('^(-?%d+)_(-?%d+)$')
      local cx, cy = (tonumber(i) + .5) * tileSize, (tonumber(j) + .5) * tileSize
      local d = math.sqrt((cx - x) ^ 2 + (cy - y) ^ 2)
      local inRange = (due and due < 1e6) or (renderer == 'old' and d <= (st.loadRadius or 1000) and speed < 15)
      local rank = (due and due < 1e6) and due or d
      if inRange and (not bestRank or rank < bestRank) then best, bestRank = key, rank end
    end
  end
  if best then
    addNav(best, native.manifest(best, 'road')); native.release(best, 'road')
    R.near[best] = {road = now}
  end
  for key, t in pairs(R.near) do
    if not t.scene and st.scenes[key] then native.manifest(key, 'scene'); native.release(key, 'scene'); t.scene = now end
    if not t.grass and st.grass and st.grass[key] then native.manifest(key, 'grass'); native.release(key, 'grass'); t.grass = now end
    if not t.grass and t.scene and whole[key] then t.grass = t.scene end
  end
  for key, serial in pairs(st.far or {}) do
    local near = R.near[key]
    if not R.far[key] and not (near and near.road) then
      native.manifest(key, 'far'); native.release(key, 'far')
      R.far[key] = {serial = serial}
      -- a far layer taken again: why its tile went last time (farBehind: dropped behind the car,
      -- farUnderNear: the near ground replaced it, near: the near tile was dropped)
      if gone[key] then backAs[gone[key]] = (backAs[gone[key]] or 0) + 1; gone[key] = nil end
    end
  end
  for key, info in pairs(st.horizon or {}) do
    if not R.horizon[key] then native.manifest(key, 'horizon'); native.release(key, 'horizon'); R.horizon[key] = true end
  end
  -- the car's tile: entered with what? lead = s each layer was in before the car (negative: s
  -- after it, filled in when the layer comes; nil: never while the drive lasted)
  if underKey ~= lastKey then
    local t = R.near[underKey]
    local e = {key = underKey, at = now, landing = landing[underKey] or false}
    for _, layer in ipairs({'road', 'scene', 'grass'}) do
      e[layer] = t and t[layer] and true or false
      e[layer .. 'Lead'] = t and t[layer] and now - t[layer] or nil
    end
    arrivals[#arrivals + 1] = e
    lastKey = underKey
  end
  for k = math.max(1, #arrivals - 3), #arrivals do
    local e = arrivals[k]
    local t = R.near[e.key]
    for _, layer in ipairs({'road', 'scene', 'grass'}) do
      if t and t[layer] and e[layer .. 'Lead'] == nil then e[layer .. 'Lead'] = -(now - e.at) end
    end
  end
  -- the car's tile whole (road, scene, grass) and the tile the route reaches 10 s from now
  local here = R.near[underKey]
  local hereWhole = here and here.road and here.scene and here.grass
  if not hereWhole then viewMiss = viewMiss + 1 end
  if not landing[underKey] then
    framesOut = framesOut + 1
    if not hereWhole then viewMissOut = viewMissOut + 1 end
  end
  local fx, fy = at(s + speed * 10)
  local aheadKey = keyAt(fx, fy)
  local ahead = R.near[aheadKey]
  local aheadWhole = ahead and ahead.road and ahead.scene and ahead.grass
  if not aheadWhole then aheadMiss = aheadMiss + 1 end
  if not landing[aheadKey] then
    aheadOut = aheadOut + 1
    if not aheadWhole then aheadMissOut = aheadMissOut + 1 end
  end
  if now >= nextSample then
    nextSample = now + .5
    samples.near[#samples.near + 1] = count(R.near)
    samples.far[#samples.far + 1] = count(R.far)
    samples.horizon[#samples.horizon + 1] = count(R.horizon)
    local wn, wf = 0, 0
    for _, due in pairs(st.wanted or {}) do if due < 1e6 then wn = wn + 1 elseif due < 2e6 then wf = wf + 1 end end
    samples.wantNear = samples.wantNear or {}
    samples.wantFar = samples.wantFar or {}
    samples.wantNear[#samples.wantNear + 1] = wn
    samples.wantFar[#samples.wantFar + 1] = wf
  end
end
local st = native.status().stream
local spent = {}
for k, v in pairs(st.spentMs) do spent[k] = v - (spent0[k] or 0) end
return {samples = samples, arrivals = arrivals, viewMiss = viewMiss, aheadMiss = aheadMiss, frames = frames, distance = s, seconds = now,
  viewMissOut = viewMissOut, aheadMissOut = aheadMissOut, framesOut = framesOut, aheadOut = aheadOut, farBack = backAs,
  built = st.built - built0, rebuilds = st.rebuilds - rebuilds0, spentMs = spent,
  lost = {scene = st.lost.scene - lost0.scene, grass = st.lost.grass - lost0.grass},
  failed = st.failed, grassOut = st.grass, parkedGrass = st.parkedGrass, slowResumes = st.slowResumes}
'''


def lua_to_py(value):
    if hasattr(value, 'items'):
        keys = list(value.keys())
        if keys and all(isinstance(k, int) for k in keys):
            return [lua_to_py(value[k]) for k in sorted(keys)]
        return {k: lua_to_py(v) for k, v in value.items()}
    return value


def stats(values):
    if not values:
        return {'mean': 0, 'max': 0}
    return {'mean': round(sum(values) / len(values), 1), 'max': max(values)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--route', type=Path, required=True)
    p.add_argument('--speed', type=float, default=16)
    p.add_argument('--seconds', type=float, default=120)
    p.add_argument('--start', type=float, default=0, help='metres along the route to land at')
    p.add_argument('--frame', type=float, default=.026, help='game frame, s')
    p.add_argument('--lua-factor', type=float, default=2.5, help='lupa runs the generator this many times slower')
    p.add_argument('--renderer', choices=('old', 'new'), default='new')
    p.add_argument('--hold', type=float, default=4, help='new renderer: s a near tile stays after native stops wanting it')
    p.add_argument('--predict', choices=('heading', 'route', 'nav'), default='nav',
                   help='the path sent with the pose: none (native: the heading), the route ahead (navigator, '
                        'autopilot) or the roads the renderer has (predict.lua over the navgraph)')
    p.add_argument('--quality', type=int, default=50)
    p.add_argument('--lua-dir', type=Path, help='another copy of mod/lua/ge/extensions/e2r (a baseline)')
    p.add_argument('--json', type=Path)
    a = p.parse_args()
    if a.lua_dir:
        bench_native.LUA = a.lua_dir
    lua, mods, _ = bench_native.runtime(a.pack)
    native = mods['native']
    native.refresh()
    geo = json.loads(a.route.read_text(encoding='utf8'))['geo']
    if a.start > 0:
        # land further along: drop the route's first metres (approximate, by lat/lon steps)
        k = 1
        acc = 0.0
        while k < len(geo) and acc < a.start:
            dlat = (geo[k][0] - geo[k - 1][0]) * 111200
            dlon = (geo[k][1] - geo[k - 1][1]) * 111200 * math.cos(math.radians(geo[k][0]))
            acc += math.hypot(dlat, dlon)
            k += 1
        geo = geo[k - 1:]
    tune = mods['quality'].preset(a.quality)
    native.setTune(tune)
    job = native.land(lua.table_from({'seq': 1, 'lat': geo[0][0], 'lon': geo[0][1]}))
    if job.state == 'error':
        sys.exit(job.message)
    # the landing: the game gives it loadNativeMs (60) a frame
    collect = lua.eval("function() collectgarbage('collect') end")
    for k in range(20000):
        native.update(a.frame, 60 * a.lua_factor)
        # LuaJIT under lupa keeps its heap in 2 GB and a Kyiv tile makes ~180 MB of garbage: the
        # game paces its collector (gc.lua), the bench collects outright
        if k % 4 == 0:
            collect()
        state = native.status().job.state
        if state in ('ready', 'error'):
            break
    if native.status().job.state != 'ready':
        sys.exit('landing never became ready: ' + str(native.status().job.message))
    route = lua.table_from([lua.table_from(g) for g in geo])
    load = lua.eval('function(source, name) return assert(load(source, "@" .. name))() end')
    lua_dir = a.lua_dir or (ROOT.parent / 'mod/lua/ge/extensions/e2r')
    predict_src = lua_dir / 'predict.lua'
    if not predict_src.exists():
        predict_src = ROOT.parent / 'mod/lua/ge/extensions/e2r/predict.lua'
    predict = load(predict_src.read_text(encoding='utf8'), 'predict.lua')
    navigation = load((ROOT.parent / 'mod/lua/ge/extensions/e2r/navigation.lua').read_text(encoding='utf8'), 'navigation.lua')
    out = lua_to_py(lua.execute(DRIVE, native, route, a.speed, a.seconds, a.frame, a.lua_factor,
                                a.renderer, a.hold, a.predict, predict, navigation))
    arrivals = out.get('arrivals') or []
    entered = len(arrivals)
    report = {
        'route': str(a.route), 'speed': a.speed, 'renderer': a.renderer, 'predict': a.predict, 'quality': a.quality,
        'distance': round(out['distance']), 'seconds': round(out['seconds'], 1),
        'near': stats(out['samples']['near']), 'far': stats(out['samples']['far']),
        'horizon': stats(out['samples']['horizon']),
        'wantNear': stats(out['samples'].get('wantNear') or []), 'wantFar': stats(out['samples'].get('wantFar') or []),
        'entered': entered,
        'enteredRoad': sum(1 for e in arrivals if e['road']),
        'enteredScene': sum(1 for e in arrivals if e['scene']),
        'enteredGrass': sum(1 for e in arrivals if e['grass']),
        'carTileIncomplete': round(out['viewMiss'] / max(1, out['frames']), 3),
        'ahead10Incomplete': round(out['aheadMiss'] / max(1, out['frames']), 3),
        # past the landing's tiles only (None: the drive never left them)
        'carTileIncompleteOut': round(out['viewMissOut'] / out['framesOut'], 3) if out['framesOut'] else None,
        'ahead10IncompleteOut': round(out['aheadMissOut'] / out['aheadOut'], 3) if out['aheadOut'] else None,
        'secondsOut': round(out['framesOut'] * a.frame, 1),
        'farBack': out.get('farBack') or {},
        'built': out['built'], 'rebuilds': out['rebuilds'],
        'spentMs': {k: round(v) for k, v in (out.get('spentMs') or {}).items()}, 'lost': out.get('lost'),
        'arrivals': arrivals,
        # tiles whose build failed (message), the grass native.lua has out at the end
        'failed': out.get('failed') or {}, 'grassOut': sorted((out.get('grassOut') or {}).keys()),
        'parkedGrass': out.get('parkedGrass'),
    }
    resident = report['near']['mean'] + report['far']['mean']
    # leads only of the tiles past the landing's (those were whole before the drive began)
    fresh = [e for e in arrivals if not e.get('landing')]
    report['enteredPastLanding'] = len(fresh)

    def pct(value):
        return '-' if value is None else f"{value:.0%}"

    def lead(layer):
        values = sorted(e.get(layer + 'Lead') for e in fresh if e.get(layer + 'Lead') is not None)
        if not values:
            return '-'
        return f"{values[len(values) // 2]:.0f}/{values[0]:.0f}"
    for layer in ('road', 'scene', 'grass'):
        values = sorted(e.get(layer + 'Lead') for e in fresh if e.get(layer + 'Lead') is not None)
        report[layer + 'Lead'] = {'median': values[len(values) // 2] if values else None,
                                  'min': values[0] if values else None,
                                  'never': sum(1 for e in arrivals if e.get(layer + 'Lead') is None)}
    print(f"{a.renderer:>3} {a.predict:>7} {a.speed:4.0f} m/s {report['distance']:5d} m: "
          f"near {report['near']['mean']:5.1f} (max {report['near']['max']:3d})  far {report['far']['mean']:5.1f} "
          f"(max {report['far']['max']:3d})  near+far {resident:5.1f}  horizon {report['horizon']['mean']:5.1f}  | "
          f"entered {entered} ({len(fresh)} past the landing): road {report['enteredRoad']} scene {report['enteredScene']} grass {report['enteredGrass']}"
          f"  lead s (median/min) scene {lead('scene')} grass {lead('grass')}"
          f"  car tile not whole {report['carTileIncomplete']:.0%}, 10 s ahead {report['ahead10Incomplete']:.0%}"
          f" (past the landing {report['secondsOut']} s: {pct(report['carTileIncompleteOut'])}, {pct(report['ahead10IncompleteOut'])})"
          f"  | built {report['built']} rebuilds {report['rebuilds']} "
          f"lost {report['lost']} far back {report['farBack']} ms {report['spentMs']}")
    if report['failed']:
        print('failed:', {k: str(v)[:160] for k, v in report['failed'].items()})
    if a.json:
        a.json.write_text(json.dumps(report, indent=1), encoding='utf8')
    sys.stdout.flush()
    # lupa's runtime crashes in its own teardown under the garbage collector: leave without it
    os._exit(0)


if __name__ == '__main__':
    main()
