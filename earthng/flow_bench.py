"""The flow (flow.lua) outside the game: ms and Lua garbage a frame on Kyiv's graph, in LuaJIT (lupa).

    .venv\\Scripts\\python.exe earthng\\flow_bench.py --pack <earthng_kyiv-oblast.zip> [--counts 100,400]
    .venv\\Scripts\\python.exe earthng\\flow_bench.py --pack ... --flow before.lua     (another flow.lua: before / after)

A frame is what world.lua flowStep does without the engine: flow.step with the obstacles of a drive
(the player's car, 8 real cars, --walkers pedestrians on a road), the hand-off's look round the
player four times a second (flow.near) and flow.draw into a stand-in batch. The focus drives along
at --speed m/s, and every --sync s the graph is synced again as after a new tile. The collector is
stopped while a frame runs, so KB is what the frame allocates; the game's own JIT limits are set
(a default LuaJIT reads about three times slower here, lupa-jit-limits).
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / 'mod/lua/ge/extensions/e2r'
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lupa.luajit21 import LuaRuntime  # noqa: E402

import walkers_bench  # noqa: E402 (its graph of a landing, cached)

FRAME = '''
local flow, segments, fx0, fy0, N, frames, speed, walkersN, syncEvery = ...
jit.off(true)
pcall(jit.opt.start, 'maxtrace=20000', 'maxrecord=40000', 'maxirconst=4000', 'maxmcode=65536', 'sizemcode=1024')
local F = flow.new{seed = 7, paints = flow.SHARE, bodies = flow.BODY_SHARE}
local segs = {}
for _, s in ipairs(segments) do segs[s[1]] = {s = s, x = s[8], y = s[9]} end
local batch = {n = 0}
local batches = {tick = function() end, kind = function(_, path) return path end, warm = function() end,
  add = function(_, K) batch.n = batch.n + 1; return batch, batch.n end,
  move = function() end, drop = function() end}
ColorF = function(r, g, b, a) return {r, g, b, a} end
local V = flow.view(F, {paintable = {'a', 'b', 'c', 'd'}}, nil, batches)
local clock = os.clock
local t = clock()
collectgarbage('collect')
local kb = collectgarbage('count')
flow.sync(F, segs, fx0, fy0, {}, {})
local syncMs, syncKb = (clock() - t) * 1000, collectgarbage('count') - kb
flow.setTarget(F, N)
local fx, fy = fx0, fy0
local sum, worst, garbage, syncs, syncSum, syncWorst, syncGarbage = 0, 0, 0, 0, 0, 0, 0
local links = 0
for _ in pairs(F.links) do links = links + 1 end
local warm = 120
for f = 1, frames + warm do
  fx = fx + speed / 60 * .7
  fy = fy + speed / 60 * .7
  local obs = {{x = fx, y = fy, vx = speed * .7, vy = speed * .7}}
  for k = 1, 8 do obs[#obs + 1] = {x = fx + 30 * math.cos(k), y = fy + 30 * math.sin(k), vx = 8 * math.cos(k * 2), vy = 8 * math.sin(k * 2)} end
  for k = 1, walkersN do obs[#obs + 1] = {x = fx + (k * 37 % 400) - 200, y = fy + (k * 53 % 400) - 200, vx = 0, vy = 0} end
  collectgarbage('collect')
  collectgarbage('stop')
  local k0 = collectgarbage('count')
  local t0 = clock()
  if syncEvery > 0 and f % math.floor(syncEvery * 60) == 0 then
    -- a tile's worth of segments gone and back: the graph changed
    local gone = {}
    for id, seg in pairs(segs) do
      if math.abs(seg.x - fx - 600) < 250 and math.abs(seg.y - fy) < 250 then gone[id] = seg; segs[id] = nil end
    end
    flow.sync(F, segs, fx, fy, {}, {})
    for id, seg in pairs(gone) do segs[id] = seg end
    flow.sync(F, segs, fx, fy, {}, {})
    local ms = (clock() - t0) * 1000
    syncs, syncSum, syncWorst = syncs + 1, syncSum + ms, math.max(syncWorst, ms)
    syncGarbage = syncGarbage + collectgarbage('count') - k0
    t0, k0 = clock(), collectgarbage('count')
  end
  flow.step(F, 1 / 60, fx, fy, obs, f / 60, nil)
  if f % 15 == 0 then flow.near(F, fx, fy, 150) end
  flow.draw(F, V, fx, fy)
  local ms = (clock() - t0) * 1000
  local g = collectgarbage('count') - k0
  collectgarbage('restart')
  if f > warm then
    sum, worst, garbage = sum + ms, math.max(worst, ms), garbage + g
  end
end
return sum / frames, worst, garbage / frames, F.count or 0, links, syncMs, syncKb,
  syncs > 0 and syncSum / syncs or 0, syncWorst, syncs > 0 and syncGarbage / syncs or 0
'''


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--lat', type=float, default=50.4501)
    p.add_argument('--lon', type=float, default=30.5234)
    p.add_argument('--counts', default='100,400')
    p.add_argument('--frames', type=int, default=1200)
    p.add_argument('--speed', type=float, default=20)
    p.add_argument('--walkers', type=int, default=12, help='pedestrians on a road (obstacles)')
    p.add_argument('--sync', type=float, default=5, help='s between two graph changes (0: none)')
    p.add_argument('--flow', type=Path, default=LUA / 'flow.lua')
    a = p.parse_args()
    data, _ = walkers_bench.kyiv_graph(a.pack, a.lat, a.lon)
    print(f'{len(data["segments"])} segments, flow: {a.flow}')
    for n in (int(v) for v in a.counts.split(',')):
        lua = LuaRuntime(unpack_returned_tuples=True)
        flow = lua.execute(a.flow.read_text(encoding='utf8'))
        segments = lua.eval('function(json) return json end')(lua.table_from([lua.table_from(s) for s in data['segments']]))
        r = lua.execute('return function(...) ' + FRAME + ' end')(flow, segments, data['spawn'][0], data['spawn'][1], n, a.frames,
                                                                    a.speed, a.walkers, a.sync)
        mean, worst, kb, cars, links, sync_ms, sync_kb, resync_ms, resync_worst, resync_kb = r
        print(f'{n:4d} cars ({cars} placed, {links} links): frame {mean:.3f} ms (max {worst:.2f}), {kb:.1f} KB a frame; '
              f'first sync {sync_ms:.1f} ms {sync_kb:.0f} KB; a tile\'s sync {resync_ms:.2f} ms (max {resync_worst:.2f}), {resync_kb:.0f} KB')


if __name__ == '__main__':
    main()
