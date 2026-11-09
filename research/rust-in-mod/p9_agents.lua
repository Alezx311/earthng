-- Agent step cost: N walkers/cars along polylines, Lua tables vs FFI struct arrays (one probe call).
-- Each step: leader gap on the same path, IDM-like speed, advance, position + heading on the polyline.
-- Paths: P polylines of 40 points; the FFI variant keeps them in one float array too.
local ffi = require('ffi')
local P, NP = 200, 40
local function paths()
  local list = {}
  for p = 1, P do
    local pts, x, y, h = {}, p * 37 % 900, p * 53 % 900, p
    for k = 1, NP do
      h = h + math.sin(p * 1.7 + k) * 0.3
      x, y = x + 12 * math.cos(h), y + 12 * math.sin(h)
      pts[k] = {x, y}
    end
    local s = {0}
    for k = 2, NP do s[k] = s[k - 1] + math.sqrt((pts[k][1] - pts[k - 1][1]) ^ 2 + (pts[k][2] - pts[k - 1][2]) ^ 2) end
    list[p] = {pts = pts, s = s, len = s[NP]}
  end
  return list
end
local PATHS = paths()

local function tablesBench(N, steps)
  local agents = {}
  for i = 1, N do agents[i] = {path = (i % P) + 1, s = (i * 7.3) % 400, v = 1.3, seg = 1, x = 0, y = 0, yaw = 0} end
  -- leaders: agents sorted per path by s once (a real sim keeps lane order)
  local byPath = {}
  for _, a in ipairs(agents) do local l = byPath[a.path] or {}; byPath[a.path] = l; l[#l + 1] = a end
  for _, l in pairs(byPath) do table.sort(l, function(a, b) return a.s < b.s end) end
  collectgarbage('collect')
  local k0, t = collectgarbage('count'), hptimer()
  for _ = 1, steps do
    for p, l in pairs(byPath) do
      local path = PATHS[p]
      for i = 1, #l do
        local a, lead = l[i], l[i + 1]
        local gap = lead and (lead.s - a.s - 0.6) or 1e9
        local acc = 0.8 * (1 - (a.v / 1.4) ^ 4 - ((0.5 + a.v * 1.0) / math.max(gap, 0.1)) ^ 2)
        a.v = math.max(0, a.v + acc * 0.016)
        a.s = (a.s + a.v * 0.016) % path.len
        local seg = a.seg
        while path.s[seg + 1] and path.s[seg + 1] < a.s do seg = seg + 1 end
        if path.s[seg] > a.s then seg = 1 end
        a.seg = seg
        local p0, p1 = path.pts[seg], path.pts[seg + 1] or path.pts[seg]
        local f = (a.s - path.s[seg]) / math.max(1e-6, (path.s[seg + 1] or path.s[seg] + 1) - path.s[seg])
        a.x, a.y = p0[1] + (p1[1] - p0[1]) * f, p0[2] + (p1[2] - p0[2]) * f
        a.yaw = math.atan2(p1[2] - p0[2], p1[1] - p0[1])
      end
    end
  end
  return t:stop() / steps, (collectgarbage('count') - k0) / steps
end

ffi.cdef('typedef struct { int32_t path, seg; float s, v, x, y, yaw; } e2rp_agent;')
local function ffiBench(N, steps)
  local pts = ffi.new('float[?]', P * NP * 2)
  local ss = ffi.new('float[?]', P * NP)
  local len = ffi.new('float[?]', P)
  for p = 1, P do
    for k = 1, NP do
      local o = (p - 1) * NP + (k - 1)
      pts[2 * o], pts[2 * o + 1] = PATHS[p].pts[k][1], PATHS[p].pts[k][2]
      ss[o] = PATHS[p].s[k]
    end
    len[p - 1] = PATHS[p].len
  end
  -- agents stored path by path in s order: the leader of i is i + 1 when on the same path
  local order = {}
  for i = 1, N do order[i] = {path = i % P, s = (i * 7.3) % 400} end
  table.sort(order, function(a, b) if a.path ~= b.path then return a.path < b.path end return a.s < b.s end)
  local A = ffi.new('e2rp_agent[?]', N)
  for i = 1, N do A[i - 1].path, A[i - 1].s, A[i - 1].v, A[i - 1].seg = order[i].path, order[i].s, 1.3, 0 end
  collectgarbage('collect')
  local k0, t = collectgarbage('count'), hptimer()
  for _ = 1, steps do
    for i = 0, N - 1 do
      local a = A[i]
      local p = a.path
      local gap = 1e9
      if i + 1 < N and A[i + 1].path == p then gap = A[i + 1].s - a.s - 0.6 end
      local g = math.max(gap, 0.1)
      local acc = 0.8 * (1 - (a.v / 1.4) ^ 4 - ((0.5 + a.v) / g) ^ 2)
      local v = math.max(0, a.v + acc * 0.016)
      local L = len[p]
      local s = (a.s + v * 0.016) % L
      local base = p * NP
      local seg = a.seg
      while seg + 1 < NP and ss[base + seg + 1] < s do seg = seg + 1 end
      if ss[base + seg] > s then seg = 0 end
      local n1 = seg + 1 < NP and seg + 1 or seg
      local o0, o1 = base + seg, base + n1
      local span = ss[o1] - ss[o0]
      local f = span > 1e-6 and (s - ss[o0]) / span or 0
      local x0, y0, x1, y1 = pts[2 * o0], pts[2 * o0 + 1], pts[2 * o1], pts[2 * o1 + 1]
      a.v, a.s, a.seg = v, s, seg
      a.x, a.y = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
      a.yaw = math.atan2(y1 - y0, x1 - x0)
    end
  end
  return t:stop() / steps, (collectgarbage('count') - k0) / steps
end

local out = {}
for _, n in ipairs({500, 2000, 10000}) do
  local tm, tk = tablesBench(n, 120)
  local fm, fk = ffiBench(n, 120)
  out['n' .. n] = string.format('tables %.3f ms %.1f KB/step | ffi %.3f ms %.1f KB/step', tm, tk, fm, fk)
end
return out
