"""Offline timing of the Lua tile generator: the stretches of work between its pause() calls.

native.lua gives generator.build() a pause() that hands the frame back when the budget is spent, so a
long stretch without a pause is a long frame. This runs mod/lua/ge/extensions/e2r/generator.lua under
LuaJIT outside the game (pip install lupa) on a synthetic 1 km cell (a town grid with houses, blocks,
a park, a pond, a motorway with a slip road and a bridge, fences, lamps, trees, a rural road and
fields) and reports the longest stretches, where they ran, and the time per stage (options.mark).

The machine, the data and the JIT state differ from the game, so the milliseconds are only a ranking:
a stretch that is long here is long there. The collector is stopped during a timed build (--with-gc keeps
it running): its steps land in any stretch and hid the ranking behind noise; in the game they are the
`less-garbage` task's concern. Run: python earthng/generator_budget.py [--grid 10|25] [--tiles 0,0 1,1]
[--far] [--swept] [--repeat 2] [--top 20] [--threshold 4] [--with-gc]

--garbage measures the Lua garbage instead: the kB a build allocates with the collector stopped, per
stage, and what of it the result holds. --no-jit makes that count the same on every run (under the JIT
it also counts the trace objects the compiler allocates, several MB between runs); --digest hashes the
result, so a change that must keep the geometry can show the same digest; --alloc-lines N lists the
lines that allocate most, by stage (a line hook: slow, and the bytes are the interpreter's). Run:
python earthng/generator_budget.py --garbage --no-jit --digest [--far] [--swept] [--tiles ..]
"""
import argparse
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'earthng'))

CELL = 1000.


def lua_runtime():
    for name in ('luajit21', 'luajit20'):
        try:
            module = __import__('lupa.' + name, fromlist=[name])
            return module.LuaRuntime(unpack_returned_tuples=True), name
        except ImportError:
            pass
    raise SystemExit('LuaJIT is needed: pip install lupa (lupa.luajit21 or lupa.luajit20)')


def to_lua(L, value):
    if isinstance(value, dict):
        return L.table_from({k: to_lua(L, v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return L.table_from([to_lua(L, v) for v in value])
    return value


# ---------------------------------------------------------------------------------------------------
# A synthetic cell in the shape cellformat.cell() decodes (fields as the generator reads them)
# ---------------------------------------------------------------------------------------------------
def terrain_z(x, y):
    return 40 + 6 * math.sin(x / 170) + 5 * math.cos(y / 210 + 1) + 2 * math.sin((x + y) / 90)


def synthetic_cell(grid, rng):
    n = int(round(CELL / grid)) + 1
    heights = [round(terrain_z(ix * grid, iy * grid), 1) for iy in range(n) for ix in range(n)]
    terrain = {'rect': [0., 0., CELL, CELL], 'nx': n, 'ny': n, 'heights': heights}
    roads, buildings, areas, lines, points = [], [], [], [], []
    ids = {'n': 0}

    def next_id(prefix='w'):
        ids['n'] += 1
        return '%s%d' % (prefix, ids['n'])

    def pt(x, y, dz=0.):
        return [round(x, 2), round(y, 2), round(terrain_z(x, y) + dz, 2)]

    def road(nodes, xy, tags, width, dz=0., id=None):
        r = {'id': id or next_id(), 'width': width, 'tags': tags, 'nodes': list(nodes), 'points': [pt(x, y, dz) for x, y in xy]}
        roads.append(r)
        return r

    # the town: streets every 100 m from 200 to 800; the middle ones are a secondary and a primary road
    xs = [200 + 100 * k for k in range(7)]
    node = lambda i, j: 'n%d_%d' % (i, j)
    for i, x in enumerate(xs):
        for j in range(6):
            ya, yb = xs[j], xs[j + 1]
            if x == 500:
                tags, width = {'highway': 'secondary', 'lanes': '2', 'maxspeed': '50', 'lit': 'yes', 'sidewalk': 'both'}, 9.
            else:
                tags, width = {'highway': 'residential', 'maxspeed': '30', 'lit': 'yes'}, 6.
            road((node(i, j), node(i, j + 1)), [(x, ya), (x, yb)], tags, width)
    for j, y in enumerate(xs):
        for i in range(6):
            xa, xb = xs[i], xs[i + 1]
            if y == 500:
                tags, width = {'highway': 'primary', 'lanes': '2', 'maxspeed': '50', 'lit': 'yes', 'sidewalk': 'both'}, 11.
            else:
                tags, width = {'highway': 'residential', 'maxspeed': '30', 'lit': 'yes'}, 6.
            road((node(i, j), node(i + 1, j)), [(xa, y), (xb, y)], tags, width)
    # the secondary runs on south to the motorway's slip road and north to the edge
    road(('s_south', node(3, 0)), [(500, 150), (500, 200)], {'highway': 'secondary', 'lanes': '2', 'maxspeed': '50'}, 9.)
    road((node(3, 6), 's_north'), [(500, 800), (500, 1000)], {'highway': 'secondary', 'lanes': '2', 'maxspeed': '70'}, 9.)
    # the primary runs on to both edges
    road(('p_west', node(0, 3)), [(0, 500), (200, 500)], {'highway': 'primary', 'lanes': '2', 'maxspeed': '70'}, 11.)
    road((node(6, 3), 'p_east'), [(800, 500), (1000, 500)], {'highway': 'primary', 'lanes': '2', 'maxspeed': '70'}, 11.)
    # a motorway along the south edge in two ways (a node for the slip road at x = 500), a slip road to
    # the secondary, a service road over the motorway on a bridge
    def motorway_xy(x0, x1):
        return [(x, 80 + 30 * math.sin(x / 300)) for x in range(int(x0), int(x1) + 1, 25)]
    mtags = {'highway': 'motorway', 'lanes': '2', 'oneway': 'yes', 'maxspeed': 'none', 'ref': 'A'}
    motorway = [road(('m_w', 'm_mid'), motorway_xy(0, 500), dict(mtags), 12., id='1001'),
                road(('m_mid', 'm_e'), motorway_xy(500, 1000), dict(mtags), 12., id='1002')]
    link = road(('m_mid', 's_south'), [(500, 80 + 30 * math.sin(500 / 300)), (520, 110), (515, 135), (500, 150)],
                {'highway': 'motorway_link', 'lanes': '1', 'oneway': 'yes'}, 5.5, id='1003')
    road(('b_s', 'b_n'), [(300, 20), (300, 60), (300, 100), (300, 140)],
         {'highway': 'service', 'bridge': 'yes', 'layer': '1'}, 5., dz=6.)
    # a winding rural road along the north edge
    rural = [(x, 900 + 40 * math.sin(x / 120)) for x in range(0, 1001, 40)]
    road(('r_w', 'r_e'), rural, {'highway': 'tertiary', 'maxspeed': '100'}, 7.)

    # houses along the streets (both sides, every 20 m, clear of the junctions); apartment blocks, a
    # park, a pond and a car park take over some blocks
    special = {(4, 4): 'park', (1, 1): 'water', (4, 1): 'parking', (2, 4): 'apartments', (1, 3): 'apartments'}

    def block_of(x, y):
        return (int((x - 200) // 100), int((y - 200) // 100))

    def rect_ring(x0, y0, x1, y1):
        return [pt(x0, y0), pt(x1, y0), pt(x1, y1), pt(x0, y1), pt(x0, y0)]

    def house(cx, cy, along, w, d, tags, height):
        ux, uy = along
        nx, ny = -uy, ux
        ring = [pt(cx + ux * a + nx * b, cy + uy * a + ny * b) for a, b in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))]
        ring.append(ring[0])
        buildings.append({'id': next_id('b'), 'kind': tags['building'], 'height': height, 'minHeight': 0., 'tags': tags, 'rings': [ring]})
        return cx, cy

    for r in roads:
        if r['tags']['highway'] not in ('residential', 'secondary', 'primary') or len(r['points']) != 2:
            continue
        (xa, ya, _), (xb, yb, _) = r['points']
        if not (200 <= xa <= 800 and 200 <= ya <= 800 and 200 <= xb <= 800 and 200 <= yb <= 800):
            continue
        length = math.hypot(xb - xa, yb - ya)
        ux, uy = (xb - xa) / length, (yb - ya) / length
        for side in (-1, 1):
            off = r['width'] / 2 + 9
            for k in range(1, 5):
                s = 20 * k
                cx, cy = xa + ux * s - uy * side * off, ya + uy * s + ux * side * off
                special_kind = special.get(block_of(cx, cy))
                if special_kind in ('park', 'water', 'parking'):
                    continue
                if special_kind == 'apartments':
                    if k == 2:
                        house(cx - uy * side * 6, cy + ux * side * 6, (ux, uy), 34, 14,
                              {'building': 'apartments', 'building:levels': '6', 'roof:shape': 'flat'}, 19.)
                    continue
                levels = 1 + rng.randrange(2)
                house(cx, cy, (ux, uy), 10 + rng.random() * 3, 8 + rng.random() * 2,
                      {'building': 'house', 'building:levels': str(levels), 'roof:shape': 'gabled'}, 4 + 3 * levels)
                if rng.random() < .25:
                    px, py = cx - uy * side * 4, cy + ux * side * 4
                    lines.append({'id': next_id('f'), 'kind': 'fence', 'tags': {'barrier': 'fence'},
                                  'points': rect_ring(px - 10, py - 10, px + 10, py + 10)})

    areas.append({'id': next_id('a'), 'kind': 'residential', 'tags': {'landuse': 'residential'}, 'rings': [rect_ring(150, 150, 850, 850)]})
    for (bi, bj), kind in special.items():
        x0, y0 = 200 + 100 * bi + 8, 200 + 100 * bj + 8
        if kind == 'park':
            areas.append({'id': next_id('a'), 'kind': 'park', 'tags': {'leisure': 'park'}, 'rings': [rect_ring(x0, y0, x0 + 84, y0 + 84)]})
            for gx in range(10):
                for gy in range(10):
                    points.append({'id': next_id('t'), 'kind': 'tree', 'tags': {'natural': 'tree'}, 'pos': pt(x0 + 4 + gx * 8.4, y0 + 4 + gy * 8.4)})
            lines.append({'id': next_id('l'), 'kind': 'path', 'tags': {'highway': 'footway'},
                          'points': [pt(x0, y0), pt(x0 + 42, y0 + 30), pt(x0 + 84, y0 + 84)]})
        elif kind == 'water':
            ring = [pt(x0 + 42 + 40 * math.cos(a), y0 + 42 + 36 * math.sin(a)) for a in [k * 2 * math.pi / 16 for k in range(16)]]
            ring.append(ring[0])
            areas.append({'id': next_id('a'), 'kind': 'water', 'tags': {'natural': 'water'}, 'rings': [ring]})
        elif kind == 'parking':
            areas.append({'id': next_id('a'), 'kind': 'parking', 'tags': {'amenity': 'parking'}, 'rings': [rect_ring(x0, y0, x0 + 84, y0 + 84)]})
    # woods and fields outside the town, a meadow by the pond
    for ring in ([pt(0, 150), pt(140, 150), pt(170, 400), pt(120, 700), pt(150, 850), pt(0, 850)],
                 [pt(850, 600), pt(1000, 600), pt(1000, 860), pt(850, 860)]):
        ring.append(ring[0])
        areas.append({'id': next_id('a'), 'kind': 'forest', 'tags': {'natural': 'wood'}, 'rings': [ring]})
    areas.append({'id': next_id('a'), 'kind': 'farmland', 'tags': {'landuse': 'farmland'}, 'rings': [rect_ring(850, 150, 1000, 600)]})
    areas.append({'id': next_id('a'), 'kind': 'meadow', 'tags': {'landuse': 'meadow'}, 'rings': [rect_ring(150, 860, 850, 1000)]})
    lines.append({'id': next_id('l'), 'kind': 'path', 'tags': {'highway': 'track', 'tracktype': 'grade2'},
                  'points': [pt(860, 160 + 40 * k) for k in range(11)]})
    # a guard rail beside the motorway
    lines.append({'id': next_id('l'), 'kind': 'guard_rail', 'tags': {'barrier': 'guard_rail'},
                  'points': [pt(x, y + 7.5) for x, y in motorway_xy(100, 900)]})
    # lamps along the town streets, bus stops, zebra crossings
    for r in roads:
        if r['tags'].get('lit') == 'yes' and len(r['points']) == 2:
            (xa, ya, _), (xb, yb, _) = r['points']
            length = math.hypot(xb - xa, yb - ya)
            ux, uy = (xb - xa) / length, (yb - ya) / length
            for s in (25, 50, 75):
                points.append({'id': next_id('p'), 'kind': 'lamp', 'tags': {'highway': 'street_lamp'},
                               'pos': pt(xa + ux * s - uy * (r['width'] / 2 + 1), ya + uy * s + ux * (r['width'] / 2 + 1))})
    for x, y in ((450, 500), (550, 500), (500, 450), (500, 550)):
        points.append({'id': next_id('p'), 'kind': 'stop', 'tags': {'highway': 'bus_stop'}, 'pos': pt(x, y)})
    for i, j in ((2, 2), (3, 2), (4, 3), (3, 4), (2, 3), (4, 4)):
        points.append({'id': next_id('p'), 'kind': 'crossing', 'tags': {'highway': 'crossing', 'crossing': 'zebra'}, 'pos': pt(xs[i], xs[j])})
    cell = {'terrain': terrain, 'roads': roads, 'junctions': [], 'buildings': buildings, 'areas': areas, 'lines': lines, 'points': points}
    return cell, motorway + [link]


def swept_bytes(swept_roads):
    """Pack v3 road bytes of the motorway and its slip road (fast_roads: the exporter's own encoder)."""
    import fast_roads as fr
    segments = []
    for r in swept_roads:
        xy = [[p[0], p[1]] for p in r['points']]
        length = sum(math.dist(a, b) for a, b in zip(xy, xy[1:]))
        z = sum(p[2] for p in r['points']) / len(r['points'])
        # the paved width as fast_sources.road_width gives it for these tags (that module needs the
        # exporter's GIS stack): the tagged lanes at 3.5 m, a 3.75 m lane on the motorway
        lanes = float(r['tags'].get('lanes', 1))
        width = lanes * (3.75 if r['tags']['highway'] == 'motorway' else 3.5)
        segments.append({'id': int(r['id']), 'way': int(r['id']), 'tags': dict(r['tags']), 'xy': xy, 'nodes': list(r['nodes']),
                         'width': width, 'prof': [[0., length], [z, z]]})
    graph = fr.Graph(segments)
    strokes = fr.build_strokes(segments, graph)
    rows, nodes = fr.records(strokes, graph, segments, CELL)
    return fr.encode_cell([r[4] for r in rows], [n[3] for n in nodes], (0., 0.)), fr.VERSION


# ---------------------------------------------------------------------------------------------------
# The Lua side: the profiling pause and the build
# ---------------------------------------------------------------------------------------------------
PRELUDE = r'''
package.path = REPO_ROOT .. '/mod/lua/?.lua;' .. package.path
local clock = os.clock
P = {top = {}, sites = {}, stages = {}, keep = 40}
local function where(level)
  local parts = {}
  for l = level, level + 2 do
    local info = debug.getinfo(l, 'Sl')
    if not info then break end
    parts[#parts + 1] = (info.short_src:match('([^/\\]+)%.lua$') or info.short_src) .. ':' .. tostring(info.currentline)
  end
  return table.concat(parts, ' < ')
end
-- --profile: a sample of the running line every 1000 VM instructions, kept per stretch (the hook turns the
-- JIT off, so the times are several times longer; the shares within a stretch hold)
local function hook()
  local info = debug.getinfo(2, 'Sl')
  if info then
    local k = (info.short_src:match('([^/\\]+)%.lua$') or info.short_src) .. ':' .. tostring(info.currentline)
    P.hist[k] = (P.hist[k] or 0) + 1
  end
end
function P.start()
  P.count, P.total, P.worst, P.last, P.lastSite, P.stageAt = 0, 0, 0, clock(), 'start', clock()
  P.top, P.sites, P.stages, P.ring, P.worst8, P.hist = {}, {}, {}, {}, 0, {}
  if P.profile then debug.sethook(hook, '', 1000) end
end
local function record(dt, from, to)
  P.count, P.total = P.count + 1, P.total + dt
  if dt > P.worst then P.worst = dt end
  -- the work between every 8th pause: what native.lua's pause() let through while it read the clock
  -- only at every 8th call
  local ring = P.ring
  ring[P.count % 8 + 1] = dt
  local sum = 0
  for k = 1, 8 do sum = sum + (ring[k] or 0) end
  if sum > P.worst8 then P.worst8 = sum end
  local site = P.sites[to]
  if not site then site = {n = 0, sum = 0, max = 0, from = from}; P.sites[to] = site end
  site.n, site.sum = site.n + 1, site.sum + dt
  if dt > site.max then site.max, site.from = dt, from end
  local top = P.top
  if #top < P.keep or dt > top[#top].dt then
    top[#top + 1] = {dt = dt, from = from, to = to, hist = P.hist}
    table.sort(top, function(a, b) return a.dt > b.dt end)
    if #top > P.keep then top[#top] = nil end
  end
end
function P.pause()
  local now = clock()
  local here = where(3)
  record((now - P.last) * 1000, P.lastSite, here)
  P.hist = {}
  P.last, P.lastSite = clock(), here
end
-- mark(name) names the stage that just ended (generator.lua)
function P.mark(name)
  local now = clock()
  P.stages[#P.stages + 1] = {name, (now - P.stageAt) * 1000}
  P.stageAt = now
end
function P.finish()
  if P.profile then debug.sethook() end
  local now = clock()
  record((now - P.last) * 1000, P.lastSite, 'end')
  P.stages[#P.stages + 1] = {'end', (now - P.stageAt) * 1000}
end
GENERATOR = require('ge/extensions/e2r/generator')
local okRoads3, roads3Module = pcall(require, 'ge/extensions/e2r/roads3')  -- pack v3 swept roads (--swept) need roads3.lua
ROADS3 = okRoads3 and roads3Module or nil
function BUILD(cells, i, j, options, withGc)
  options.pause, options.mark = P.pause, P.mark
  if not withGc then collectgarbage(); collectgarbage('stop') end
  P.start()
  local road, scene, far, nav = GENERATOR.build(cells, i, j, options)
  P.finish()
  if not withGc then collectgarbage('restart'); collectgarbage() end
  local function count(m) local n = 0; for _, it in ipairs(m and m.items or {}) do n = n + (it.triangles or 0) end; return n end
  return count(road), count(scene), count(far), nav and #nav.segments or 0
end
-- --garbage: the bytes a build allocates (the collector stopped, so nothing is freed), per stage, and
-- the bytes its result holds; the rest is garbage the game's collector has to trace and sweep. pause()
-- is a no-op here (the profiling pause allocates its own strings), and the stage marks take their own
-- allocations out of the count.
local gcount = collectgarbage
local garbageResult
-- the build in a frame of its own: when it returns, its stack slots no longer hold the result
local function garbageBuild(cells, i, j, options, profile)
  local stages, stageAt, lines = {}, 0, {}
  options.pause = function() end
  options.mark = function(name)
    stages[#stages + 1] = {name, gcount('count') - stageAt}
    stageAt = gcount('count')
  end
  local last, lastKey, calls = 0, nil, 0
  local function hook(_, line)
    local now = gcount('count')
    if lastKey then lines[lastKey] = (lines[lastKey] or 0) + now - last end
    -- the hook's own tables pile up with the collector stopped (14 GB on a swept tile): a full
    -- collection now and then, inside the hook, where it is not counted
    calls = calls + 1
    if calls % 1048576 == 0 then collectgarbage(); collectgarbage('stop') end
    local info = debug.getinfo(2, 'S')
    -- the stage is its number until it ends (mark names the stage that just ended)
    lastKey = (#stages + 1) .. ' ' .. (info.short_src:match('([^/\\]+)%.lua$') or info.short_src) .. ':' .. line
    last = gcount('count')
  end
  collectgarbage(); collectgarbage(); collectgarbage('stop')
  local base = gcount('count')
  stageAt = base
  if profile then last = gcount('count'); debug.sethook(hook, 'l') end
  local t0 = clock()
  garbageResult = {GENERATOR.build(cells, i, j, options)}
  local ms = (clock() - t0) * 1000
  if profile then debug.sethook() end
  local after = gcount('count')
  stages[#stages + 1] = {'end', after - stageAt}
  collectgarbage('restart')
  return after - base, stages, ms, lines
end
-- the result's own bytes, counted by walking it (LuaJIT 2.1 GC64 sizes: a table 56 bytes, an array slot 8,
-- a hash node 24 rounded up to a power of two, a string 24 + its length). A count of the collector with and
-- without the result varied by megabytes between identical builds (the generator's caches and stale
-- stack slots), so it is not used.
local function resultBytes(value)
  local seen, bytes = {}, 0
  local function walk(v)
    if type(v) == 'string' then
      if not seen[v] then seen[v] = true; bytes = bytes + 24 + #v end
      return
    end
    if type(v) ~= 'table' or seen[v] then return end
    seen[v] = true
    local n, hash = #v, 0
    for k, x in pairs(v) do
      if not (type(k) == 'number' and k >= 1 and k <= n and k % 1 == 0) then hash = hash + 1; walk(k) end
      walk(x)
    end
    local size = 1
    while size < hash do size = size * 2 end
    bytes = bytes + 56 + 8 * (n + 1) + (hash > 0 and 24 * size or 0)
  end
  walk(value)
  return bytes / 1024
end
function GARBAGE(cells, i, j, options, profile, sink)
  local allocated, stages, ms, lines = garbageBuild(cells, i, j, options, profile)
  if sink then DIGEST(garbageResult, sink) end
  local kept = resultBytes(garbageResult)
  garbageResult = nil
  return allocated, kept, stages, ms, lines
end
-- the build's result as text in a fixed order (keys sorted, numbers at full precision), fed to sink in
-- pieces: two builds with the same digest made the same geometry
function DIGEST(value, sink)
  local buf, n, seen, ids = {}, 0, {}, 0
  local function put(s)
    n = n + 1; buf[n] = s
    if n >= 4096 then sink(table.concat(buf, '', 1, n)); n = 0 end
  end
  local order = {number = 1, string = 2, boolean = 3}
  local function less(a, b)
    local ta, tb = type(a), type(b)
    if ta ~= tb then return (order[ta] or 9) < (order[tb] or 9) end
    if ta == 'number' or ta == 'string' then return a < b end
    return tostring(a) < tostring(b)
  end
  local function walk(v)
    local t = type(v)
    if t == 'number' then put((v == math.floor(v) and math.abs(v) < 2^53) and string.format('%d', v) or string.format('%.17g', v))
    elseif t == 'string' then put(string.format('%q', v))
    elseif t == 'table' then
      if seen[v] then put('@' .. seen[v]); return end
      ids = ids + 1; seen[v] = ids
      local keys = {}
      for k in pairs(v) do keys[#keys + 1] = k end
      table.sort(keys, less)
      put('{')
      for _, k in ipairs(keys) do walk(k); put('='); walk(v[k]); put(',') end
      put('}')
    else put(t == 'boolean' and tostring(v) or t) end
  end
  walk(value)
  sink(table.concat(buf, '', 1, n))
end
function SWEPT(bytes, version)
  assert(ROADS3, '--swept needs ge/extensions/e2r/roads3.lua (pack v3 swept roads)')
  local cell = ROADS3.cell(bytes, 1, #bytes, 0, 0, version, function() end)
  return ROADS3.merge({cell}, nil)
end
'''


def tile_options(L, args, roads3):
    options = L.table_from({
        'tileSize': 500, 'regionId': 'synthetic', 'materials': '/earthng/planet/materials.json',
        'packs': '/e2r_stream/fast-art/v10/packs.json', 'far': args.far, 'horizon': False, 'farDecor': args.far,
        'farStep': 100, 'horizonStep': 100, 'latitude': 52.5, 'seaLevel': 0, 'country': 'de',
        'heightPipeline': not args.no_height_pipeline, 'detail': 50})
    if roads3 is not None:
        options.roads3 = roads3
    return options


def garbage(L, cells, roads3, args):
    """--garbage: kB allocated per build and per stage, kB the result keeps, and optionally a digest.

    The first build of a cell also decodes and sorts it (collect(), cached per cell); the last one is the
    steady state of a cell already loaded. The game spends the build over many frames, so its garbage per
    frame is about the kB per ms of build here times the generator's ms per frame there.
    """
    import hashlib
    for tile in args.tiles:
        i, j = (int(v) for v in tile.split(','))
        for n in range(args.repeat):
            h = hashlib.sha256() if args.digest and n == args.repeat - 1 else None
            sink = (lambda piece: h.update(piece.encode('utf-8', 'surrogatepass'))) if h else None
            allocated, kept, stages, ms, lines = L.globals().GARBAGE(cells, i, j, tile_options(L, args, roads3), False, sink)
            print('tile %d,%d build %d: allocated %.0f kB, the result holds ~%.0f kB, garbage %.0f kB, %.0f ms (%.1f kB garbage per ms)' % (
                i, j, n + 1, allocated, kept, allocated - kept, ms, (allocated - kept) / ms))
        print('  stages (kB allocated):', ', '.join('%s %.0f' % tuple(st.values()) for st in stages.values()))
        if h:
            print('  digest', h.hexdigest())
        if args.alloc_lines:
            _, _, stages, _, lines = L.globals().GARBAGE(cells, i, j, tile_options(L, args, roads3), True, None)
            names = {n + 1: st[1] for n, st in enumerate(stages.values())}
            rows = sorted(((kb, names.get(int(key.split(' ')[0]), '?'), key.split(' ')[1]) for key, kb in lines.items()), reverse=True)
            total = sum(row[0] for row in rows)
            print('  lines by kB allocated (interpreter, %.0f kB in all; stage, line):' % total)
            for kb, stage, where in rows[:args.alloc_lines]:
                print('    %8.0f  %-10s %s' % (kb, stage, where))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--grid', type=float, default=10, help='elevation grid step in m (10 = a national DTM, 25 = Terrarium)')
    ap.add_argument('--tiles', nargs='*', default=['0,0', '1,1'], help='500 m tiles i,j of the 1 km cell at the origin')
    ap.add_argument('--far', action='store_true', help='build the far layer instead of the near one')
    ap.add_argument('--swept', action='store_true', help='hand the tile pack v3 road cells of the motorway (sweep.lua)')
    ap.add_argument('--no-height-pipeline', action='store_true', help='the old height passes and ground pull')
    ap.add_argument('--repeat', type=int, default=2, help='builds per tile; the last one is reported (the JIT is warm)')
    ap.add_argument('--top', type=int, default=20, help='stretches listed')
    ap.add_argument('--threshold', type=float, default=4., help='ms: stretches over this are counted as long')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--with-gc', action='store_true', help='leave the collector running during the timed build')
    ap.add_argument('--profile', action='store_true', help='sample the running line and show where each long stretch spends its time')
    ap.add_argument('--garbage', action='store_true', help='measure the bytes a build allocates and keeps instead of its stretches')
    ap.add_argument('--alloc-lines', type=int, default=0, metavar='N',
                    help='with --garbage: the N lines that allocate most (a line hook: the JIT is off, so the bytes are the interpreter\'s)')
    ap.add_argument('--no-jit', action='store_true', help='run the interpreter only (with --garbage: the same kB on every run; '
                    'under the JIT the count also takes the trace objects the compiler makes, several MB between runs)')
    ap.add_argument('--digest', action='store_true', help='with --garbage: a hash of the result, to check that a change keeps the geometry')
    args = ap.parse_args()

    L, flavour = lua_runtime()
    L.globals().REPO_ROOT = ROOT
    L.globals().load(PRELUDE, '=harness')()
    L.globals().P.profile = args.profile
    if args.no_jit:
        L.execute('jit.off()')
    cell, swept_roads = synthetic_cell(args.grid, random.Random(args.seed))
    print('LuaJIT via lupa.%s; cell: %d roads, %d buildings, %d areas, %d lines, %d points, grid %g m' % (
        flavour, len(cell['roads']), len(cell['buildings']), len(cell['areas']), len(cell['lines']), len(cell['points']), args.grid))
    cells = to_lua(L, [cell])
    roads3 = None
    if args.swept:
        data, version = swept_bytes(swept_roads)
        roads3 = L.globals().SWEPT(data, version)
        print('swept roads: %d chunks, %d nodes from %d bytes' % (len(roads3.chunks), len(roads3.nodes), len(data)))
    if args.garbage:
        return garbage(L, cells, roads3, args)
    exit_code = 0
    for tile in args.tiles:
        i, j = (int(v) for v in tile.split(','))
        for _ in range(args.repeat):
            result = L.globals().BUILD(cells, i, j, tile_options(L, args, roads3), args.with_gc)
        P = L.globals().P
        stretches = [(e.dt, e['from'], e.to, dict(e.hist.items())) for e in P.top.values()]
        sites = sorted(((s.max, s.sum, s.n, to, s['from']) for to, s in P.sites.items()), reverse=True)
        long_ones = sum(1 for s in sites if s[0] > args.threshold)
        print('\n=== tile %d,%d (%s): road %d tris, scene %d tris, far %d tris, nav %d segments' % (
            i, j, 'far' if args.far else 'near', result[0], result[1], result[2], result[3]))
        print('build %.0f ms in %d pauses; worst stretch %.1f ms, worst 8 in a row %.1f ms; %d call sites with a stretch over %.0f ms' % (
            P.total, P.count, P.worst, P.worst8, long_ones, args.threshold))
        print('stages (ms):', ', '.join('%s %.0f' % (name, ms) for name, ms in (tuple(st.values()) for st in P.stages.values())))
        print('longest stretches (ms, ended at the pause at .. after the one at ..):')
        for dt, frm, to, hist in stretches[:args.top]:
            print('  %6.1f  %s  <-  %s' % (dt, to, frm))
            if args.profile and hist:
                total = sum(hist.values())
                lines = sorted(hist.items(), key=lambda kv: -kv[1])[:5]
                print('          ' + ', '.join('%s %d%%' % (k, round(100 * v / total)) for k, v in lines))
        print('call sites by their worst stretch (max ms, total ms, count):')
        for mx, total, n, to, frm in sites[:args.top]:
            print('  %6.1f %7.0f %6d  %s' % (mx, total, n, to))
        if P.worst > args.threshold * 2:
            exit_code = 1
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
