-- How the engine steps the GE collector each frame: is its step sized by the heap's growth since
-- its last step (so a frame whose sweep freed more than was allocated makes a negative size, which
-- LuaJIT's lua_gc(LUA_GCSTEP) reads as a huge unsigned one and finishes the whole cycle)?
-- Per frame: the engine's own split (Engine.Debug.getLastPerformanceMetrics: Lua, LuaGC) and the
-- heap. Three trials at TRIALS seconds: a full collection of our own (the heap falls by what it
-- frees), then the engine's LuaGC in the frames after it. A step sized by allocations stays ~1 ms;
-- one that read a fall as a huge size pays a second full cycle (300-400 ms at ~400 MB).
-- Then (CONTROL) the same, but the heap is brought back over its old level in the same frame by a
-- string kept until the end: no fall, so the engine's next step should stay small.
-- Run: probe.py --user <out>/user -f research/rust-in-mod/p26_engine_step.lua --timeout 120
local TRIALS = TRIALS or {4, 12, 20}
local CONTROL = CONTROL or {28, 36}
local SECONDS = SECONDS or 44
local m = {}
local timer = hptimer()
local frames, lines, events, keep = 0, {}, {}, {}
local watch = 0
local lastHeap = collectgarbage('count')
local gcBig = {}
local function metrics()
  if pcall(Engine.Debug.getLastPerformanceMetrics, m) then return m.Lua or -1, m.LuaGC or -1 end
  return -1, -1
end
local nextTrial, nextControl = 1, 1
return P.task(function(dt, ms)
  frames = frames + 1
  local now = timer:stop() / 1000
  local lua, gc = metrics()
  local heap = collectgarbage('count')
  if watch > 0 then
    lines[#lines + 1] = string.format('  +%d: frame %.0f ms, engine Lua %.1f ms LuaGC %.1f ms, heap %.0f -> %.0f MB', 6 - watch, ms, lua, gc, lastHeap / 1024, heap / 1024)
    watch = watch - 1
  elseif gc > 50 and #gcBig < 30 then
    gcBig[#gcBig + 1] = string.format('t=%.1f frame %.0f ms LuaGC %.1f ms heap %.0f -> %.0f MB', now, ms, gc, lastHeap / 1024, heap / 1024)
  end
  if TRIALS[nextTrial] and now > TRIALS[nextTrial] and watch == 0 then
    nextTrial = nextTrial + 1
    local h0, t = collectgarbage('count'), hptimer()
    collectgarbage('collect')
    lines[#lines + 1] = string.format('t=%.1f collect %.0f ms, heap %.0f -> %.0f MB (fall)', now, t:stop(), h0 / 1024, collectgarbage('count') / 1024)
    heap = collectgarbage('count')
    watch = 5
  elseif CONTROL[nextControl] and now > CONTROL[nextControl] and watch == 0 then
    nextControl = nextControl + 1
    local h0, t = collectgarbage('count'), hptimer()
    collectgarbage('collect')
    local freed = h0 - collectgarbage('count')
    -- a string as big as what was freed, plus 1 MB: the heap ends the frame higher than it began
    keep[#keep + 1] = string.rep('e', math.floor((freed + 1024) * 1024))
    lines[#lines + 1] = string.format('t=%.1f control: collect + %.0f MB string %.0f ms, heap %.0f -> %.0f MB (no fall)', now, freed / 1024 + 1,
      t:stop(), h0 / 1024, collectgarbage('count') / 1024)
    heap = collectgarbage('count')
    watch = 5
  end
  lastHeap = heap
  if now > SECONDS then
    keep = nil
    return {frames = frames, trials = lines, bigLuaGC = gcBig}
  end
end)
