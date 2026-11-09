-- EGB2 vs EGB3 in the running game (earthng/probe.py -f, then e.g. "return BENCH('<block>', 1, 16, {0,0,500,500})").
-- Copy cellformat3.lua and the v2/v3 block files (rust: cargo run --release -p pack --example egb3) into <user>/current/e2r_probe/ first.
CF = require('e2r/cellformat')
CF3 = loadstring(io.open('e2r_probe/cellformat3.lua', 'rb'):read('*a'), '=cellformat3')()
function READ(p) local f = io.open(p, 'rb'); local s = f:read('*a'); f:close(); return s end
function SAME(a, b)
  if type(a) ~= type(b) then return false end
  if type(a) ~= 'table' then return a == b end
  for k, v in pairs(a) do if not SAME(v, b[k]) then return false end end
  for k in pairs(b) do if a[k] == nil then return false end end
  return true
end
-- one command: block name, first..last cell (sorted slots), keep rect or nil
function BENCH(name, first, count, keep)
  local d2, d3 = READ('e2r_probe/' .. name .. '.bin'), READ('e2r_probe/' .. name .. '.v3.bin')
  local s2, s3 = CF.block(d2), CF3.block(d3)
  local list = {}
  for k in pairs(s2) do list[#list + 1] = k end
  table.sort(list)
  local sel = {}
  for i = first, math.min(#list, first + count - 1) do sel[#sel + 1] = list[i] end
  local rect, r, equal = {0, 0, 1000, 1000}, {cells = #sel, of = #list}, true
  for _, k in ipairs(sel) do
    if not SAME(CF.cell(d2, s2[k][1], s2[k][2], 0, 0, rect, nil, keep), CF3.cell(d3, s3[k][1], s3[k][2], 0, 0, rect, nil, keep)) then equal = false end
  end
  r.equal = equal
  local bytes2, bytes3 = 0, 0
  for _, k in ipairs(sel) do bytes2 = bytes2 + s2[k][2] - s2[k][1] + 1; bytes3 = bytes3 + s3[k][2] - s3[k][1] + 1 end
  r.kb2, r.kb3 = bytes2 / 1024, bytes3 / 1024
  for _, v in ipairs({{'v2', CF, d2, s2}, {'v3', CF3, d3, s3}}) do
    local best, mb = math.huge, 0
    for rep = 1, 2 do
      collectgarbage('collect')
      local k0, t = collectgarbage('count'), hptimer()
      collectgarbage('stop')
      for _, k in ipairs(sel) do v[2].cell(v[3], v[4][k][1], v[4][k][2], 0, 0, rect, nil, keep) end
      local ms = t:stop()
      mb = (collectgarbage('count') - k0) / 1024
      collectgarbage('restart')
      best = math.min(best, ms)
    end
    r[v[1] .. '_ms'], r[v[1] .. '_mb'] = best, mb
  end
  collectgarbage('collect')
  return r
end
function WARM(name, first, count, keep)
  local d3 = READ('e2r_probe/' .. name .. '.v3.bin')
  local s3 = CF3.block(d3)
  local list = {}
  for k in pairs(s3) do list[#list + 1] = k end
  table.sort(list)
  local sel = {}
  for i = first, math.min(#list, first + count - 1) do sel[#sel + 1] = list[i] end
  local rect = {0, 0, 1000, 1000}
  CF3.values = {}
  for _, k in ipairs(sel) do CF3.cell(d3, s3[k][1], s3[k][2], 0, 0, rect, nil, keep) end
  local best, mb = math.huge, 0
  for rep = 1, 2 do
    collectgarbage('collect')
    local k0, t = collectgarbage('count'), hptimer()
    collectgarbage('stop')
    for _, k in ipairs(sel) do CF3.cell(d3, s3[k][1], s3[k][2], 0, 0, rect, nil, keep) end
    local ms = t:stop()
    mb = (collectgarbage('count') - k0) / 1024
    collectgarbage('restart')
    best = math.min(best, ms)
  end
  CF3.values = nil
  collectgarbage('collect')
  return {cells = #sel, v3warm_ms = best, v3warm_mb = mb}
end
return 'ok'
