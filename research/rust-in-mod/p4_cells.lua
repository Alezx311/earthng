-- Real Kyiv-centre cells: today's varint decode vs a fixed-layout (Rust-written) read through ffi.copy.
-- The fixed layout is simulated from the decoded cell: what a MapBuilder encoder would write.
local ffi = require('ffi')
local CF = require('e2r/cellformat')
local path = '/earthng/countries/ukraine/regions/e0300-n500/blocks/-3_-1.bin'
local f = io.open(path, 'rb'); local data = f:read('*a'); f:close()
local slots = CF.block(data)
local list = {}
for k, range in pairs(slots) do list[#list + 1] = {k, range[1], range[2]} end
table.sort(list, function(a, b) return a[1] < b[1] end)
local CELLS = math.min(#list, tonumber(_G.__e2rCells or 24))
local rect = {0, 0, 1000, 1000}
local function clock() return hptimer() end

local res = {cells = CELLS, blockBytes = #data}
collectgarbage('collect')
collectgarbage('stop')
-- A: today's full decode (no keep filter: a whole cell), and only the grid
local decoded, t, k0 = {}, clock(), collectgarbage('count')
for i = 1, CELLS do local e = list[i]; decoded[i] = CF.cell(data, e[2], e[3], 0, 0, rect) end
res.A_cell_ms, res.A_cell_kb = t:stop(), collectgarbage('count') - k0
t, k0 = clock(), collectgarbage('count')
for i = 1, CELLS do local e = list[i]; CF.terrain(data, e[2], e[3], rect) end
res.A_grid_ms, res.A_grid_kb = t:stop(), collectgarbage('count') - k0
collectgarbage('restart'); collectgarbage('collect'); collectgarbage('stop')

-- Fixed layout per cell: int16 decimetre grid + float32 xyz of every feature point.
local fixed, npts, ngrid = {}, 0, 0
for i = 1, CELLS do
  local c = decoded[i]
  local hs = c.terrain.heights
  local g = ffi.new('int16_t[?]', #hs)
  for k = 1, #hs do g[k - 1] = math.floor(hs[k] * 10 + .5) end
  local pts = {}
  local function add(p) pts[#pts + 1] = p[1]; pts[#pts + 1] = p[2]; pts[#pts + 1] = p[3] end
  for _, kind in ipairs(CF.KINDS) do
    for _, ft in ipairs(c[kind]) do
      if ft.points then for _, p in ipairs(ft.points) do add(p) end end
      if ft.rings then for _, r in ipairs(ft.rings) do for _, p in ipairs(r) do add(p) end end end
      if ft.pos then add(ft.pos) end
    end
  end
  local a = ffi.new('float[?]', math.max(1, #pts))
  for k = 1, #pts do a[k - 1] = pts[k] end
  fixed[i] = {grid = ffi.string(g, 2 * #hs), ng = #hs, pts = ffi.string(a, 4 * #pts), np = #pts / 3}
  npts, ngrid = npts + #pts / 3, ngrid + #hs
end
res.points, res.gridValues = npts, ngrid
res.varintBytes, res.fixedBytes = 0, 0
for i = 1, CELLS do
  res.varintBytes = res.varintBytes + list[i][3] - list[i][2] + 1
  res.fixedBytes = res.fixedBytes + #fixed[i].grid + #fixed[i].pts
end
decoded = nil
collectgarbage('restart'); collectgarbage('collect'); collectgarbage('stop')

-- B: grid by memcpy into int16_t[] (generator would read g[k] / 10)
t, k0 = clock(), collectgarbage('count')
local keepB = {}
for i = 1, CELLS do
  local g = ffi.new('int16_t[?]', fixed[i].ng); ffi.copy(g, fixed[i].grid, #fixed[i].grid); keepB[i] = g
end
res.B_grid_ms, res.B_grid_kb = t:stop(), collectgarbage('count') - k0
-- B2: grid by memcpy, then a Lua table of metres (generator unchanged)
t, k0 = clock(), collectgarbage('count')
for i = 1, CELLS do
  local n = fixed[i].ng
  local g = ffi.new('int16_t[?]', n); ffi.copy(g, fixed[i].grid, 2 * n)
  local hs = {}
  for k = 1, n do hs[k] = g[k - 1] / 10 end
end
res.B2_gridTable_ms, res.B2_gridTable_kb = t:stop(), collectgarbage('count') - k0
-- C: points by memcpy only
t, k0 = clock(), collectgarbage('count')
for i = 1, CELLS do
  local a = ffi.new('float[?]', 3 * fixed[i].np); ffi.copy(a, fixed[i].pts, #fixed[i].pts)
end
res.C_pts_ms, res.C_pts_kb = t:stop(), collectgarbage('count') - k0
-- C2: points by memcpy, then {x, y, z} tables (today's shape)
t, k0 = clock(), collectgarbage('count')
for i = 1, CELLS do
  local n = fixed[i].np
  local a = ffi.new('float[?]', 3 * n); ffi.copy(a, fixed[i].pts, 4 * 3 * n)
  local out = {}
  for k = 0, n - 1 do out[k + 1] = {a[3 * k], a[3 * k + 1], a[3 * k + 2]} end
end
res.C2_ptsTables_ms, res.C2_ptsTables_kb = t:stop(), collectgarbage('count') - k0
collectgarbage('restart')
return res
