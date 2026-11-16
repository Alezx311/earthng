-- Run in a disposable game via earthng/probe.py; needs Ukraine pack and nearest.dll.
-- A real graph and the exact production Lua routing.nearest are the baseline.
local ffi = require('ffi')
local routing = require('ge/extensions/e2r/routing')
local root = 'e2r_bridge/'
local function write(name, data)
  local f = assert(io.open(root .. name, 'wb')); assert(f:write(data)); f:close()
end
local function read(name)
  local f = assert(io.open(root .. name, 'rb')); local s = f:read('*a'); f:close(); return s
end
local function remove(name) FS:removeFile('/' .. root .. name) end
local path = '/earthng/countries/ukraine/routing/e0300-n500.bin'
local f = assert(io.open(path, 'rb')); local blob = f:read('*a'); f:close()
local timer = hptimer()
local graph = routing.graph({routing.decode(blob)})
local graphMs = timer:stopAndReset()
assert(graph.n > 0, 'empty real graph')
local count = 128
local queries = ffi.new('double[?]', count * 2)
for i = 0, count - 1 do
  local node = (i * 7919 + 17) % graph.n
  queries[2*i], queries[2*i+1] = graph.x[node] + 13.25, graph.y[node] - 9.75
end
-- Warm LuaJIT before timing, then retain every answer for parity, including distances.
for i = 0, math.min(7, count - 1) do routing.nearest(graph, queries[2*i], queries[2*i+1]) end
timer:stopAndReset()
local expected, distances, luaMs = {}, {}, {}
for run = 1, 3 do
  timer:stopAndReset()
  for i = 0, count - 1 do expected[i], distances[i] = routing.nearest(graph, queries[2*i], queries[2*i+1]) end
  luaMs[run] = timer:stopAndReset()
end
local measurements, pending, elapsed = {}, nil, 0
local levels, round = {1, 4, 1, 4, 1, 4}, 0
local function submit()
  round = round + 1
  local head = ffi.new('uint32_t[3]', graph.n, count, levels[round])
  local clock = hptimer()
  local request = 'ENB1' .. ffi.string(head, 12) .. ffi.string(graph.x, 8*graph.n)
    .. ffi.string(graph.y, 8*graph.n) .. ffi.string(graph.used, 4*graph.n) .. ffi.string(queries, 16*count)
  write('bench-request.bin', request)
  write('bench-request.ready', '1')
  pending = {clock = clock, workers = levels[round], bytes = #request, submitMs = clock:stopAndReset()}
end
submit()
return P.task(function(dt)
  elapsed = elapsed + (dt or 0)
  if elapsed > 60 then write('bench-stop', '1'); return {error='timeout'} end
  if not FS:fileExists('/' .. root .. 'bench-response.ready') then return end
  local remainingMs = pending.clock:stopAndReset()
  if FS:fileExists('/' .. root .. 'bench-error.txt') then
    local err = read('bench-error.txt'); write('bench-stop', '1'); return {error=err}
  end
  local data = read('bench-response.bin')
  assert(data:sub(1,4) == 'ENR1' and #data == 16 + count*12, 'bad response')
  local header = ffi.new('uint32_t[3]'); ffi.copy(header, data:sub(5,16), 12)
  assert(header[0] == count, 'wrong count')
  local micros = tonumber(header[1]) + tonumber(header[2]) * 4294967296
  local ids, ds = ffi.new('uint32_t[1]'), ffi.new('double[1]')
  local mismatch = 0
  for i = 0, count - 1 do
    local pos = 17 + i * 12
    ffi.copy(ids, data:sub(pos,pos+3), 4); ffi.copy(ds, data:sub(pos+4,pos+11), 8)
    if tonumber(ids[0]) ~= expected[i] or math.abs(tonumber(ds[0]) - distances[i]) > 1e-7 then mismatch = mismatch + 1 end
  end
  local readVerifyMs = pending.clock:stopAndReset()
  assert(mismatch == 0, 'nearest-node parity failed: ' .. mismatch)
  measurements[#measurements+1] = {workers=pending.workers, mismatches=mismatch, inputBytes=pending.bytes,
    submitMs=pending.submitMs, waitMs=remainingMs, readVerifyMs=readVerifyMs,
    roundtripMs=pending.submitMs+remainingMs+readVerifyMs, rustMs=micros/1000}
  remove('bench-response.ready'); remove('bench-response.bin')
  if round < #levels then submit(); return end
  write('bench-stop', '1')
  return {graph=path, nodes=graph.n, queries=count, graphBuildMs=graphMs, luaMs=luaMs, native=measurements}
end)
