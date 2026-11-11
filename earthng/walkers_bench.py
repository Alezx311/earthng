"""Pedestrians (walkers.lua + pedhit.lua) bench outside the game: LuaJIT (lupa), ms and Lua garbage
per frame for 200 / 500 / 1000 walkers.

  python earthng/walkers_bench.py [--pack out/kyiv-oblast-polygon/earthng_kyiv-oblast.zip] [--counts 200,500,1000]
  python earthng/walkers_bench.py --synthetic        # a 12 x 12 grid of streets 100 m apart instead

The graph: the nav segments of the road tiles the native generator builds round a landing (the Kyiv
polygon pack, centre of Kyiv by default), simplified as world.lua does (navigation.simplify), cached
in out/walk-bench/<pack>-<lat>-<lon>.json. A frame is what world.lua walkersStep does: walkers.step
(with 9 moving vehicles and 400 flow cars to wait for), pedhit.step, walkers.draw into stand-in
TSStatics that count their calls. The focus drives along the streets at --speed m/s.

lupa is not the game (no engine calls behind setPosRot, another JIT state): read the numbers as
before / after on the same machine, and the call counts (setPosRot, setHidden, objects) as they are.
With the JIT on, the KB column is mostly compiled traces (jit.attach: every frame over 1.5 ms is a
trace compile); --jit-off gives the interpreter alone, the closer match to the game (200 walkers
before: 0.38 ms Lua + 0.27 ms of calls here, 0.5-0.6 ms measured in Kyiv). Each count runs --repeat
times and the least disturbed run is shown (a game or a build on the same machine shows in max).

  --walkers / --pedhit: another pair of modules, for before / after (git show HEAD:... > file)
  --flow N: flow cars the walkers look at before crossing; --speed: m/s of the focus

The sync line: the whole graph at once (a landing), one 500 m square of segments gone and back (a
tile), and that tile in 1.5 ms slices as world.lua runs it in a coroutine (frames, longest slice).
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / 'mod/lua/ge/extensions/e2r'
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lupa.luajit21 import LuaRuntime  # noqa: E402

GRAPH = '''
local native, frames, budget = ...
for f = 1, frames do
  native.update(1 / 60, budget)
  local st = native.status()
  if st.job.state == 'error' then error(st.job.message) end
  if st.job.state == 'ready' and f > 1 then
    local stream = st.stream
    if f == 2 or not FIRST then
      FIRST = true
      local p = st.job.manifest.spawn.pos
      native.pose({x = p[1], y = p[2], vx = 0, vy = 0, state = 'driving'})
    end
    if stream.queued == 0 and f > 200 then break end
  end
  -- what the renderer took is released at once (a layer left in the generator is evicted)
  for key, token in pairs(st.stream.ready) do
    local m = native.manifest(key, 'road')
    if m and m.navSegments and not SEEN[key] then
      SEEN[key] = true
      for _, s in ipairs(m.navSegments) do SEGS[s[1]] = s end
    end
    native.release(key, 'road')
  end
  for _, layer in ipairs({'scene', 'grass', 'far', 'horizon'}) do
    for key in pairs(st.stream[layer == 'scene' and 'scenes' or layer] or {}) do native.manifest(key, layer); native.release(key, layer) end
  end
end
local spawn = native.status().job.manifest.spawn.pos
return spawn[1], spawn[2]
'''


def kyiv_graph(pack, lat, lon):
    cache = ROOT / 'out/walk-bench' / f'{pack.stem}-{lat:.4f}-{lon:.4f}.json'
    if cache.exists():
        return json.loads(cache.read_text(encoding='utf8')), cache
    from bench_native import runtime
    lua, mods, _ = runtime(pack)
    native = mods['native']
    native.refresh()
    job = native.land(lua.table_from({'seq': 1, 'lat': lat, 'lon': lon}))
    if job.state == 'error':
        sys.exit(job.message)
    lua.execute('SEGS, SEEN = {}, {}')
    x, y = lua.execute(GRAPH, native, 3000, 50)
    simplify = lua.execute((LUA / 'navigation.lua').read_text(encoding='utf8')).simplify
    segs = []
    for s in lua.globals().SEGS.values():
        s = simplify(s)
        segs.append([s[k] for k in range(1, len(s) + 1)])
    data = {'pack': str(pack), 'lat': lat, 'lon': lon, 'spawn': [x, y], 'segments': segs}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding='utf8')
    return data, cache


def synthetic_graph(n=12, step=100):
    segs = []

    def add(sid, a, b, x0, y0, x1, y1):
        s = [sid, a, b, '-+', 13.9, 3.5, 1]
        for k in range(5):
            f = k / 4
            s += [x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, 0]
        segs.append(s)
    for i in range(n):
        for j in range(n):
            here = f'{i}_{j}'
            if i < n - 1:
                add('h' + here, here, f'{i + 1}_{j}', i * step, j * step, (i + 1) * step, j * step)
            if j < n - 1:
                add('v' + here, here, f'{i}_{j + 1}', i * step, j * step, i * step, (j + 1) * step)
    c = (n - 1) * step / 2
    return {'segments': segs, 'spawn': [c, c]}


# the game's side, counted: createObject, setPosRot, setHidden, colours
GAME = '''
CALLS = {create = 0, delete = 0, pos = 0, hide = 0, colour = 0, ground = 0, alive = 0}
local Obj = {}
Obj.__index = Obj
function Obj:setField() end
function Obj:registerObject() end
function Obj:setPosRot(x, y, z) CALLS.pos = CALLS.pos + 1; self.x, self.y = x, y end
function Obj:setHidden(h) CALLS.hide = CALLS.hide + 1; self.hidden = h end
function Obj:delete() CALLS.delete = CALLS.delete + 1; CALLS.alive = CALLS.alive - 1 end
Obj.__newindex = function(t, k, v)
  if k == 'instanceColor' or k == 'instanceColor1' or k == 'instanceColor2' then CALLS.colour = CALLS.colour + 1 end
end
function createObject() CALLS.create = CALLS.create + 1; CALLS.alive = CALLS.alive + 1; return setmetatable({}, Obj) end
local Col = {}
Col.__index = Col
function Col:asLinear4F() return self end
function ColorF(r, g, b, a) return setmetatable({r, g, b, a}, Col) end
function GROUND(x, y, z) CALLS.ground = CALLS.ground + 1; return z + .12 end
'''

FRAME = '''
local walkers, pedhit, segments, fx0, fy0, N, frames, warm, speed, seed, flowN = ...
-- the bench's own loop is not compiled: its traces would abort on collectgarbage every frame and count
jit.off(true)
local W = walkers.new{seed = seed}
local shapes = {}
for k = 1, walkers.POSES + 1 do shapes[k] = 'pose' .. k end
local V = walkers.view(W, shapes, nil)
-- the sync: all at once (the landing), then again with the segments of one 500 m square gone and
-- back (a tile evicted, a tile arrived)
collectgarbage('collect')
local sk, st = collectgarbage('count'), CLOCK()
walkers.sync(W, segments, fx0, fy0)
local syncMs, syncKb = (CLOCK() - st) * 1000, collectgarbage('count') - sk
local cut = {}
for sid, seg in pairs(segments) do
  if not (seg.x > fx0 and seg.x < fx0 + 500 and seg.y > fx0 - fx0 + fy0 and seg.y < fy0 + 500) then cut[sid] = seg end
end
walkers.sync(W, cut, fx0, fy0)
collectgarbage('collect')
sk, st = collectgarbage('count'), CLOCK()
walkers.sync(W, segments, fx0, fy0)
local tileMs, tileKb = (CLOCK() - st) * 1000, collectgarbage('count') - sk
-- the same in slices, as world.lua runs it: a coroutine whose pause yields after 1.5 ms of a frame
walkers.sync(W, cut, fx0, fy0)
local sliceStart
local co = coroutine.create(function()
  walkers.sync(W, segments, fx0, fy0, function() if (CLOCK() - sliceStart) * 1000 > 1.5 then coroutine.yield() end end)
end)
local slices, sliceMax = 0, 0
while coroutine.status(co) ~= 'dead' do
  sliceStart = CLOCK()
  assert(coroutine.resume(co))
  slices, sliceMax = slices + 1, math.max(sliceMax, (CLOCK() - sliceStart) * 1000)
end
walkers.setTarget(W, N)
-- the route: from the landing along the sidewalk pieces' graph, a straight run in the direction with the most road
local fx, fy = fx0, fy0
local dirx, diry = 1, 0
local best = -1
for a = 0, 7 do
  local hx, hy = math.cos(a * math.pi / 4), math.sin(a * math.pi / 4)
  local n = 0
  for _, piece in ipairs(W.list) do
    local px, py = piece.line[1] - fx0, piece.line[2] - fy0
    local along = px * hx + py * hy
    if along > 0 and along < speed * frames / 60 + 300 and math.abs(px * hy - py * hx) < 300 then n = n + 1 end
  end
  if n > best then best, dirx, diry = n, hx, hy end
end
-- flowN flow cars (400) and 8 moving AI cars round the focus, the player's car at it
local flow = {}
local r = 1
local function rnd() r = (r * 1103515245 + 12345) % 2147483648; return r / 2147483648 end
for k = 1, flowN do flow[k] = {drawnX = fx0 + (rnd() - .5) * 800, drawnY = fy0 + (rnd() - .5) * 800, drawnYaw = rnd() * 6.28, v = 8 + rnd() * 6} end
local hitters = {}
for k = 1, 9 do
  hitters[k] = {x = fx0, y = fy0, vx = 0, vy = 0, fx = 1, fy = 0, hl = 2.3, hw = .95, ox = (rnd() - .5) * 300, oy = (rnd() - .5) * 300, player = k == 1 or nil}
end
local api = {}
local bodies = {}
function api.spawn() bodies[#bodies + 1] = {x = 0, y = -2000}; return #bodies end
function api.pose(id) local b = bodies[id]; return b.x, b.y, 0, 0 end
function api.place(id, x, y) bodies[id].x, bodies[id].y = x, y end
function api.reset() end
function api.park(id) bodies[id].y = -2000 end
function api.delete() end
local P = pedhit.new{size = 6}
pedhit.prewarm(P, api, fx0, fy0)
local dt = 1 / 60
local ms, kb, simMs, drawMs, worst = {}, {}, 0, 0, 0
local calls0
local clock = CLOCK
for f = 1, warm + frames do
  if f == warm + 1 then
    calls0 = {}
    for k, v in pairs(CALLS) do calls0[k] = v end
  end
  fx, fy = fx + dirx * speed * dt, fy + diry * speed * dt
  for k, h in ipairs(hitters) do
    h.x, h.y = fx + (h.ox or 0) * (k > 1 and 1 or 0), fy + (h.oy or 0) * (k > 1 and 1 or 0)
    h.vx, h.vy, h.fx, h.fy = dirx * speed, diry * speed, dirx, diry
  end
  collectgarbage('stop')
  local k0 = collectgarbage('count')
  local t0 = clock()
  walkers.step(W, dt, fx, fy, hitters, flow)
  pedhit.step(P, walkers, W, hitters, f * dt, api, fx, fy)
  local t1 = clock()
  walkers.draw(W, V, fx, fy, GROUND)
  local t2 = clock()
  local k1 = collectgarbage('count')
  collectgarbage('restart')
  if f > warm then
    local m = (t2 - t0) * 1000
    ms[#ms + 1], kb[#kb + 1] = m, k1 - k0
    simMs, drawMs = simMs + (t1 - t0) * 1000, drawMs + (t2 - t1) * 1000
    if m > worst then worst = m end
  end
end
local calls = {}
for k, v in pairs(CALLS) do calls[k] = (v - calls0[k]) / frames end
calls.alive = CALLS.alive
local sum, gsum = 0, 0
for k = 1, #ms do sum, gsum = sum + ms[k], gsum + kb[k] end
table.sort(ms)
local length = 0
for _, piece in ipairs(W.list) do length = length + piece.len end
local asked, placed = N, W.count
if walkers.counts then asked, placed = walkers.counts(W) end
return {ms = sum / #ms, p99 = ms[math.floor(#ms * .99)], max = worst, sim = simMs / #ms, draw = drawMs / #ms,
  kb = gsum / #kb, count = placed, asked = asked, pieces = #W.list, km = length / 1000, calls = calls, hits = P.stats.placed,
  syncMs = syncMs, syncKb = syncKb, tileMs = tileMs, tileKb = tileKb, slices = slices, sliceMax = sliceMax, room = select(3, (walkers.counts or function() end)(W))}
'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--pack', type=Path, default=ROOT / 'out/kyiv-oblast-polygon/earthng_kyiv-oblast.zip')
    p.add_argument('--lat', type=float, default=50.4477)
    p.add_argument('--lon', type=float, default=30.5233)
    p.add_argument('--synthetic', action='store_true', help='a 12 x 12 grid of streets instead of the pack')
    p.add_argument('--counts', default='200,500,1000')
    p.add_argument('--frames', type=int, default=1800)
    p.add_argument('--warm', type=int, default=300, help='frames before the count starts (the walkers fill up)')
    p.add_argument('--speed', type=float, default=12, help='m/s the focus drives')
    p.add_argument('--seed', type=int, default=7)
    p.add_argument('--walkers', type=Path, default=LUA / 'walkers.lua', help='another walkers.lua (a before / after pair)')
    p.add_argument('--pedhit', type=Path, default=LUA / 'pedhit.lua')
    p.add_argument('--flow', type=int, default=400, help='flow cars the walkers wait for at the kerb')
    p.add_argument('--repeat', type=int, default=3, help='runs per count; the least disturbed (lowest mean) is shown')
    p.add_argument('--jit-off', action='store_true', help='the interpreter alone (with the JIT, compiled traces count as garbage)')
    a = p.parse_args()
    if a.synthetic or not a.pack.exists():
        graph, where = synthetic_graph(), 'synthetic 12 x 12 grid, 100 m'
        speed = min(a.speed, 2)   # the grid is 1.1 km across
    else:
        t = time.perf_counter()
        graph, cache = kyiv_graph(a.pack, a.lat, a.lon)
        where = f'{a.pack.name} at {a.lat}, {a.lon} ({len(graph["segments"])} segments, {cache.name}, {time.perf_counter() - t:.1f} s)'
        speed = a.speed
    print('graph:', where)
    lua = LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    if a.jit_off:
        lua.execute('jit.off()')
    g.walkers = lua.eval('function(s, n) return assert(load(s, "@" .. n))() end')(a.walkers.read_text(encoding='utf8'), 'walkers.lua')
    g.pedhit = lua.eval('function(s, n) return assert(load(s, "@" .. n))() end')(a.pedhit.read_text(encoding='utf8'), 'pedhit.lua')
    lua.execute(GAME)
    g.CLOCK = time.perf_counter
    segs = lua.table()
    for s in graph['segments']:
        st = lua.table_from(s)
        n = (len(s) - 7) // 3
        mid = 7 + 3 * ((n - 1) // 2)
        segs[s[0]] = lua.table_from({'s': st, 'x': s[mid], 'y': s[mid + 1]})
    fx, fy = graph['spawn'][0], graph['spawn'][1]
    print(f'{"asked":>6} {"placed":>6} {"ms/frame":>9} {"sim":>6} {"draw":>6} {"p99":>6} {"max":>6} {"KB/frame":>9} '
          f'{"setPosRot":>9} {"setHidden":>9} {"colours":>8} {"ground":>7} {"objects":>7} {"bodies":>6} {"engine":>6}')
    for n in (int(c) for c in a.counts.split(',')):
        r = None
        for _ in range(a.repeat):
            run = lua.execute(FRAME, g.walkers, g.pedhit, segs, fx, fy, n, a.frames, a.warm, speed, a.seed, a.flow)
            lua.execute('for k in pairs(CALLS) do CALLS[k] = 0 end')
            if r is None or run.ms < r.ms:
                r = run
        c = r.calls
        print(f'{int(r.asked):6d} {int(r.count):6d} {r.ms:9.3f} {r.sim:6.3f} {r.draw:6.3f} {r.p99:6.2f} {r.max:6.2f} {r.kb:9.2f} '
              f'{c.pos:9.1f} {c.hide:9.1f} {c.colour:8.2f} {c.ground:7.2f} {int(c.alive):7d} {int(r.hits):6d} {engine_ms(c):6.2f}')
    print(f'sidewalk pieces {int(r.pieces)}, {r.km:.1f} km in the synced graph, room for {r.room or "-"} walkers; '
          f'speed {speed} m/s, {a.frames} frames after {a.warm}')
    print(f'sync: all {r.syncMs:.1f} ms {r.syncKb:.0f} KB; one 500 m square back {r.tileMs:.1f} ms {r.tileKb:.0f} KB, '
          f'in 1.5 ms slices: {int(r.slices or 0)} frames, longest {r.sliceMax or 0:.2f} ms')
    print('engine: ms of game calls a frame at 3 us a setPosRot, 1.5 us a setHidden (p8, p12), 1 us a colour, '
          '10 us a ground read, 110 us a new object (walk-01); estimates, not measured')


def engine_ms(c):
    return (c.pos * 3 + c.hide * 1.5 + c.colour * 1 + c.ground * 10 + c.create * 110) / 1000


if __name__ == '__main__':
    main()
