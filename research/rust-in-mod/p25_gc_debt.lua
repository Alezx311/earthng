-- Where the debt comes from that the 0.4-0.75 s sweeps pay (out/rel090-vyt: 80-150 MB swept in one
-- frame every 20-50 s while driving, no Lua section of ours over 20 ms in it).
-- LuaJIT adds (total - threshold) to gc.debt at each step, so one allocation of S bytes owes ~S; and
-- lua_gc(LUA_GCSTEP, 0) loops lj_gc_step (10 * stepmul units of work each) until the debt is under
-- 1 KB or the cycle ends. In the sweep 1 KB of debt frees ~8 KB of small objects (offline: 16 MB of
-- debt, 129 MB freed in 37 ms; in the game the same sweep takes ~10x as long).
-- The game's FFI has no ffi.cast and no pointer types, so gc.debt is not readable. Instead a "debt
-- meter": collectgarbage('step', 0) pays the debt there and then, and its time is the debt's cost.
-- Meters at the start of e2r_world's onUpdate (A: debt made since our last frame, by the engine and
-- other extensions), after native.update (C: the generator) and at its end (B: our other parts).
-- A sweep that moves into a meter names the part that made its debt. The generator's pause points
-- log heap jumps over JUMP_KB between two of them (allocations, no stepping).
-- Run: probe.py --user <out>/user -f research/rust-in-mod/p25_gc_debt.lua --timeout 200 (after
-- the landing). SECONDS (default 70) of frames.
local SECONDS, SLOW_MS, METER_MS, JUMP_KB = SECONDS or 70, SLOW_MS or 150, METER_MS or 8, JUMP_KB or 1024
local r = {stepmul = collectgarbage('setstepmul', 200)}
collectgarbage('setstepmul', r.stepmul)
local count = collectgarbage
local frameNo = 0
local meters = {A = {n = 0, ms = 0, max = 0, big = {}}, B = {n = 0, ms = 0, max = 0, big = {}}, C = {n = 0, ms = 0, max = 0, big = {}}}
local frameMeter = {A = 0, B = 0, C = 0}
local function meter(name)
  local m = meters[name]
  local h0, t = count('count'), hptimer()
  local done = collectgarbage('step', 0)
  local ms = t:stop()
  local h1 = count('count')
  m.n, m.ms = m.n + 1, m.ms + ms
  if ms > m.max then m.max = ms end
  frameMeter[name] = frameMeter[name] + ms
  if ms > METER_MS and #m.big < 40 then
    m.big[#m.big + 1] = string.format('f%d %.1f ms heap %.0f -> %.0f MB%s', frameNo, ms, h0 / 1024, h1 / 1024, done and ' (cycle done)' or '')
  end
end

-- generator pause points: heap jumps between two of them
local native = require('ge/extensions/e2r/native')
local active
for i = 1, 80 do
  local name, value = debug.getupvalue(native.update, i)
  if not name then break end
  if name == 'active' then active = value end
end
local jumps, jumpN, lastHeap = {}, 0, count('count')
local origPause = active and active.pause
if origPause then
  active.pause = function()
    local h = count('count')
    if h - lastHeap > JUMP_KB then
      jumpN = jumpN + 1
      if #jumps < 60 then
        local info, up = debug.getinfo(2, 'Sl'), debug.getinfo(3, 'Sl')
        jumps[#jumps + 1] = string.format('f%d heap %+.0f KB at %s:%d < %s:%d', frameNo, h - lastHeap,
          info.short_src:match('[^/]*$'), info.currentline, up and up.short_src:match('[^/]*$') or '?', up and up.currentline or 0)
      end
    end
    lastHeap = h
    return origPause()
  end
end
local origUpdate = native.update
native.update = function(...)
  lastHeap = count('count')
  origUpdate(...)
  meter('C')
end
local W = extensions.e2r_world
local origOn = W.onUpdate
W.onUpdate = function(...)
  meter('A')
  origOn(...)
  meter('B')
end
extensions.hookUpdate('onUpdate')

local RING = 6
local ringMs, ringH, ringA, ringB, ringC = {}, {}, {}, {}, {}
for k = 1, RING do ringMs[k], ringH[k], ringA[k], ringB[k], ringC[k] = 0, 0, 0, 0, 0 end
local slow, after = {}, 0
local frames, msSum, over100 = 0, 0, 0
local timer = hptimer()
local function line(k)
  return string.format('%5.0f ms heap %4.0f MB | meters A %5.1f C %5.1f B %5.1f ms', ringMs[k], ringH[k] / 1024, ringA[k], ringC[k], ringB[k])
end
return P.task(function(dt, ms)
  frameNo = frameNo + 1
  frames, msSum = frames + 1, msSum + ms
  if ms > 100 then over100 = over100 + 1 end
  -- the meters of the previous frame (this probe runs once a frame, in an order of its own)
  local k = frameNo % RING + 1
  ringMs[k], ringH[k], ringA[k], ringB[k], ringC[k] = ms, count('count'), frameMeter.A, frameMeter.B, frameMeter.C
  frameMeter.A, frameMeter.B, frameMeter.C = 0, 0, 0
  if ms > SLOW_MS and #slow < 20 then
    local list = {}
    for j = RING - 1, 0, -1 do list[#list + 1] = line((frameNo - j) % RING + 1) end
    slow[#slow + 1] = {frame = frameNo, at = math.floor(timer:stop() / 100) / 10, frames = list}
    after = 2
  elseif after > 0 and #slow > 0 then
    local s = slow[#slow]
    s.frames[#s.frames + 1] = 'after: ' .. line(k)
    after = after - 1
  end
  if timer:stop() > SECONDS * 1000 then
    native.update = origUpdate
    if origPause then active.pause = origPause end
    W.onUpdate = origOn
    extensions.hookUpdate('onUpdate')
    r.frames, r.meanMs, r.over100 = frames, msSum / frames, over100
    for name, m in pairs(meters) do
      r['meter' .. name] = string.format('%d calls, %.1f ms in all, max %.1f ms', m.n, m.ms, m.max)
      r['big' .. name] = m.big
    end
    r.slow, r.jumps, r.jumpCount = slow, jumps, jumpN
    return r
  end
end)
