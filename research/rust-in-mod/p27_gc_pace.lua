-- Can the incremental collector finish its cycles before the engine's full collection does?
-- p26: the hitches are the engine's own full collection (LuaGC 415-442 ms in one frame), started
-- when the heap reaches ~4/3 of what its previous full collection left; our collectgarbage('collect')
-- does not move that point. At stepmul 100 a cycle needs far more allocation than the 4/3 leaves,
-- so the incremental cycle never ends while driving, and the full collection throws its work away.
-- Here gc.lua's step is replaced for SECONDS: the mutator's stepmul stays MUL, and every frame
-- collectgarbage('step', K) runs until BUDGET_MS is spent or the cycle ends. Reports each cycle
-- (frames, explicit ms, heap), the longest single step (the atomic phase), frames over SLOW_MS with
-- the engine's LuaGC, and the frame statistics.
-- Run: probe.py --user <out>/user -f research/rust-in-mod/p27_gc_pace.lua --timeout 200 (after the landing)
local SECONDS, BUDGET_MS, K, MUL, SLOW_MS = SECONDS or 65, BUDGET_MS or 1.5, K or 16, MUL or 100, SLOW_MS or 100
local gc = require('ge/extensions/e2r/gc')
local r = {}
for i = 1, 10 do
  local name, value = debug.getupvalue(gc.step, i)
  if not name then break end
  if name == 'saved' then r.engineStepmul = value end
end
r.pause = collectgarbage('setpause', 200)
collectgarbage('setpause', r.pause)
local origStep = gc.step
local mulBefore = collectgarbage('setstepmul', MUL)
gc.step = function() end
local m = {}
local timer = hptimer()
local frames, msSum, over = 0, 0, {}
local cycles, cycleFrames, cycleMs, cycleTop = {}, 0, 0, collectgarbage('count')
local worstStep, worstStepAt, explicitMs = 0, 0, 0
local slow, gcSum, gcMax = {}, 0, 0
local list = {}
return P.task(function(dt, ms)
  frames, msSum = frames + 1, msSum + ms
  list[#list + 1] = ms
  local gcMs = 0
  if pcall(Engine.Debug.getLastPerformanceMetrics, m) then gcMs = m.LuaGC or 0 end
  gcSum = gcSum + gcMs
  if gcMs > gcMax then gcMax = gcMs end
  if ms > SLOW_MS and #slow < 30 then
    slow[#slow + 1] = string.format('t=%.1f frame %.0f ms, engine LuaGC %.1f ms, heap %.0f MB', timer:stop() / 1000, ms, gcMs, collectgarbage('count') / 1024)
  end
  -- this frame's slice
  local t = hptimer()
  local h = collectgarbage('count')
  if h > cycleTop then cycleTop = h end
  cycleFrames = cycleFrames + 1
  local done
  repeat
    local s = hptimer()
    done = collectgarbage('step', K)
    local sm = s:stop()
    if sm > worstStep then worstStep, worstStepAt = sm, timer:stop() / 1000 end
  until done or t:stop() >= BUDGET_MS
  local used = t:stop()
  explicitMs, cycleMs = explicitMs + used, cycleMs + used
  if done then
    if #cycles < 40 then
      cycles[#cycles + 1] = string.format('t=%.1f: %d frames, %.0f ms of slices, heap top %.0f -> %.0f MB', timer:stop() / 1000,
        cycleFrames, cycleMs, cycleTop / 1024, collectgarbage('count') / 1024)
    end
    cycleFrames, cycleMs, cycleTop = 0, 0, collectgarbage('count')
  end
  if timer:stop() > SECONDS * 1000 then
    gc.step = origStep
    collectgarbage('setstepmul', mulBefore)
    table.sort(list)
    r.frames, r.meanMs, r.p99 = frames, msSum / frames, list[math.ceil(#list * .99)]
    r.over100 = 0
    for _, v in ipairs(list) do if v > 100 then r.over100 = r.over100 + 1 end end
    r.explicitMsPerFrame = explicitMs / frames
    r.engineLuaGCPerFrame, r.engineLuaGCMax = gcSum / frames, gcMax
    r.worstStep, r.worstStepAt = worstStep, worstStepAt
    r.cycles, r.slow = cycles, slow
    r.settings = string.format('budget %.1f ms, K %d, mul %d', BUDGET_MS, K, MUL)
    return r
  end
end)
